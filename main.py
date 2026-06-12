import os
import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from urllib.parse import quote
import io

app = FastAPI(title="HoT Portal API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET","POST","OPTIONS"], allow_headers=["*"])

ZOHO_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
WEBHOOK_SECRET     = os.getenv("WEBHOOK_SECRET", "hot-secret")
FIREBASE_API_KEY   = "AIzaSyBmEFd1xIRY7I8XVSePqAHYIDeQ-iqpDmE"
ZOHO_API_BASE      = "https://creator.zoho.in/api/v2/houseoftesting/house-of-testing-lab"
# v2.1 base is needed for the file download endpoint
ZOHO_API_BASE_V21  = "https://www.zohoapis.in/creator/v2.1/data/houseoftesting/house-of-testing-lab"
REPORT_PROJECTS    = "Booked_Projects"
REPORT_SRFS        = "SRF1_Report"

# Which Creator file-upload fields a client is allowed to download
ALLOWED_DOC_FIELDS = {
    "test_report":  "Test_Report",
    "raw_data":     "Raw_Data_Sheet",
    "trf":          "TRF",
    "previous":     "Previous_Report",
    "ccl":          "CCL",
}

async def get_zoho_token():
    if not ZOHO_REFRESH_TOKEN:
        return ""
    async with httpx.AsyncClient() as c:
        r = await c.post(
            "https://accounts.zoho.in/oauth/v2/token",
            data={
                "grant_type":    "refresh_token",
                "client_id":     ZOHO_CLIENT_ID,
                "client_secret": ZOHO_CLIENT_SECRET,
                "refresh_token": ZOHO_REFRESH_TOKEN,
            },
            timeout=15
        )
        d = r.json()
        print(f"[ZOHO TOKEN] {d}")
        return d.get("access_token", "")

async def verify_firebase_token(id_token: str) -> str:
    """Firebase REST API se token verify karo aur email lo."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}"
    async with httpx.AsyncClient() as c:
        r = await c.post(
            url,
            json={"idToken": id_token},
            timeout=10
        )
        data = r.json()
        print(f"[FIREBASE] status={r.status_code} response={str(data)[:200]}")
        if r.status_code != 200:
            raise HTTPException(status_code=401, detail=f"Firebase error: {data}")
        if "users" not in data or not data["users"]:
            raise HTTPException(status_code=401, detail="No user found")
        return data["users"][0]["email"]

async def fetch_zoho(report: str, criteria: str, token: str) -> list:
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{ZOHO_API_BASE}/report/{report}",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            params={"criteria": criteria, "max_records": 200},
            timeout=20
        )
        print(f"[ZOHO] {report} status={r.status_code}")
        data = r.json()
        if "data" not in data:
            print(f"[ZOHO ERROR] {data}")
        return data.get("data", [])

def extract_token(auth: str) -> str:
    parts = auth.strip().split(" ")
    if len(parts) != 2 or parts[0] != "Bearer":
        print(f"[AUTH ERROR] Bad header: '{auth[:50]}'")
        raise HTTPException(status_code=401, detail=f"Invalid auth header. Got: '{auth[:30]}'")
    return parts[1]

@app.get("/health")
def health():
    return {
        "status": "ok",
        "server": "HoT Portal API v2",
        "zoho_connected": bool(ZOHO_REFRESH_TOKEN),
        "mode": "LIVE" if ZOHO_REFRESH_TOKEN else "SAMPLE",
        "reports": {"projects": REPORT_PROJECTS, "srfs": REPORT_SRFS}
    }

@app.get("/api/projects")
async def get_projects(authorization: str = Header(default="")):
    print(f"[REQ] /api/projects — auth header: '{authorization[:40]}...'")
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)
    print(f"[OK] Email verified: {email}")

    if ZOHO_REFRESH_TOKEN:
        try:
            token = await get_zoho_token()
            data = await fetch_zoho(REPORT_PROJECTS, f'Customer_Email == "{email}"', token)
            return {"email": email, "count": len(data), "data": data, "mode": "LIVE"}
        except Exception as e:
            print(f"[ZOHO ERR] {e}")

    sample = [{"JOB_ID": "SAMPLE-001", "Project_Status": "Testing Started", "Standard": "IS 16047", "Product": "Sample", "Lead_Model": "M1", "Manufacturer_Name": "Test", "Booking_Date": "1-Jun-2026", "Testing_Start_Date": "5-Jun-2026", "Final_Report_Issue_Date": "", "Raw_Data_Sheet_Status": "Testing", "Test_Report_Download_Link": "", "Customer_Name": email.split("@")[0].title(), "Customer_Email": email}]
    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}

@app.get("/api/srfs")
async def get_srfs(authorization: str = Header(default="")):
    print(f"[REQ] /api/srfs — auth header: '{authorization[:40]}...'")
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)
    print(f"[OK] Email verified: {email}")

    if ZOHO_REFRESH_TOKEN:
        try:
            token = await get_zoho_token()
            data = await fetch_zoho(REPORT_SRFS, f'Email_id == "{email}"', token)
            return {"email": email, "count": len(data), "data": data, "mode": "LIVE"}
        except Exception as e:
            print(f"[ZOHO ERR] {e}")

    sample = [{"SRF_ID": "SRF-SAMPLE", "SRF_Status": "Submitted", "Product_Sample_Details_Technical_specifications": "Sample", "Test_Requirement": "IS 16047", "Added_Time": "1-Jun-2026", "Manufacturer_Name": "Test", "Brand_Name": "Test", "Model_Name": "M1", "Email_id": email}]
    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}


# ──────────────────────────────────────────────────────────────
#  SECURE DOCUMENT DOWNLOAD
#  Client never sees a WorkDrive link. Portal calls this endpoint,
#  we verify the client owns the job, then stream the file from Zoho.
# ──────────────────────────────────────────────────────────────
@app.get("/api/download")
async def download_document(
    job_id: str,
    field: str = "test_report",
    authorization: str = Header(default="")
):
    print(f"[REQ] /api/download job={job_id} field={field}")

    # 1. Verify the caller is a logged-in client
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)
    print(f"[OK] Email verified: {email}")

    # 2. Validate requested field
    field_key = field.lower().strip()
    if field_key not in ALLOWED_DOC_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unknown document type: {field}")
    zoho_field = ALLOWED_DOC_FIELDS[field_key]

    if not ZOHO_REFRESH_TOKEN:
        raise HTTPException(status_code=503, detail="Server not connected to Zoho")

    token = await get_zoho_token()

    # 3. CRITICAL: confirm this job belongs to THIS client.
    #    We query the project by BOTH job id AND the caller's email.
    #    If no record comes back, the client does not own this job → block.
    criteria = f'(JOB_ID == "{job_id}" && Customer_Email == "{email}")'
    rows = await fetch_zoho(REPORT_PROJECTS, criteria, token)
    if not rows:
        print(f"[BLOCKED] {email} tried to access job {job_id} (not theirs / not found)")
        raise HTTPException(status_code=403, detail="You do not have access to this document.")

    record = rows[0]
    record_id = str(record.get("ID", ""))
    if not record_id:
        raise HTTPException(status_code=404, detail="Record ID not found")

    # 4. Stream the file from Zoho Creator's download endpoint.
    #    (We don't pre-check the file field because the report response may not
    #     include file-upload fields; Zoho returns 404 if the field is empty.)
    download_url = (
        f"{ZOHO_API_BASE_V21}/report/{REPORT_PROJECTS}/{record_id}/{zoho_field}/download"
    )
    print(f"[DOWNLOAD] fetching {download_url}")

    async with httpx.AsyncClient() as c:
        r = await c.get(
            download_url,
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            timeout=60
        )
        if r.status_code != 200:
            print(f"[DOWNLOAD ERR] status={r.status_code} body={r.text[:200]}")
            raise HTTPException(status_code=502, detail="Could not fetch file from Zoho")

        content = r.content
        # Try to keep the original filename from Zoho's headers
        cd = r.headers.get("content-disposition", "")
        filename = f"{job_id}_{zoho_field}.pdf"
        if "filename=" in cd:
            raw = cd.split("filename=")[-1].strip().strip('"')
            if raw:
                filename = raw
        ctype = r.headers.get("content-type", "application/octet-stream")

    return StreamingResponse(
        io.BytesIO(content),
        media_type=ctype,
        headers={
            "Content-Disposition": f'attachment; filename="{quote(filename)}"'
        }
    )


class WebhookPayload(BaseModel):
    email: str
    customer_name: str = ""
    srf_id: str = ""
    secret: str = ""

@app.post("/webhook/srf-submitted")
async def webhook(payload: WebhookPayload):
    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    return {"status": "ok", "message": f"Received for {payload.email}"}
