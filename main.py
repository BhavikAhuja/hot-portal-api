import os
import httpx
from datetime import datetime
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
ZOHO_API_BASE_V21  = "https://www.zohoapis.in/creator/v2.1/data/houseoftesting/house-of-testing-lab"
REPORT_PROJECTS    = "Booked_Projects"
REPORT_SRFS        = "SRF1_Report"

ALLOWED_DOC_FIELDS = {
    "test_report": "Test_Report",
    "raw_data":    "Raw_Data_Sheet",
    "ccl":         "CCL",
    "trf":         "TRF",
    "previous":    "Previous_Report",
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
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}"
    async with httpx.AsyncClient() as c:
        r = await c.post(url, json={"idToken": id_token}, timeout=10)
        data = r.json()
        print(f"[FIREBASE] status={r.status_code}")
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
        raise HTTPException(status_code=401, detail=f"Invalid auth header.")
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
    print(f"[REQ] /api/projects")
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)
    print(f"[OK] Email: {email}")

    if ZOHO_REFRESH_TOKEN:
        try:
            token = await get_zoho_token()
            data = await fetch_zoho(REPORT_PROJECTS, f'Customer_Email == "{email}"', token)
            return {"email": email, "count": len(data), "data": data, "mode": "LIVE"}
        except Exception as e:
            print(f"[ZOHO ERR] {e}")

    sample = [{
        "JOB_ID": "SAMPLE-001",
        "Project_Status": "Testing Started",
        "Standard": "IS 16047",
        "Product": "Sample",
        "Lead_Model": "M1",
        "Manufacturer_Name": "Test",
        "Booking_Date": "1-Jun-2026",
        "Testing_Start_Date": "5-Jun-2026",
        "Final_Report_Issue_Date": "",
        "Raw_Data_Sheet_Status": "Testing",
        "Test_Report_Download_Link": "",
        "Payment_Status": "",
        "Project_Remarks": "",
        "Customer_Name": email.split("@")[0].title(),
        "Customer_Email": email
    }]
    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}

@app.get("/api/srfs")
async def get_srfs(authorization: str = Header(default="")):
    print(f"[REQ] /api/srfs")
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)
    print(f"[OK] Email: {email}")

    if ZOHO_REFRESH_TOKEN:
        try:
            token = await get_zoho_token()
            data = await fetch_zoho(REPORT_SRFS, f'Email_id == "{email}"', token)
            return {"email": email, "count": len(data), "data": data, "mode": "LIVE"}
        except Exception as e:
            print(f"[ZOHO ERR] {e}")

    sample = [{
        "SRF_ID": "SRF-SAMPLE",
        "SRF_Status": "Submitted",
        "Product_Sample_Details_Technical_specifications": "Sample",
        "Test_Requirement": "IS 16047",
        "Added_Time": "1-Jun-2026",
        "Manufacturer_Name": "Test",
        "Brand_Name": "Test",
        "Model_Name": "M1",
        "Email_id": email
    }]
    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}

@app.get("/api/download")
async def download_document(
    job_id: str,
    field: str = "test_report",
    authorization: str = Header(default="")
):
    print(f"[REQ] /api/download job={job_id} field={field}")
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)

    field_key = field.lower().strip()
    if field_key not in ALLOWED_DOC_FIELDS:
        raise HTTPException(status_code=400, detail=f"Unknown document type: {field}")
    zoho_field = ALLOWED_DOC_FIELDS[field_key]

    if not ZOHO_REFRESH_TOKEN:
        raise HTTPException(status_code=503, detail="Server not connected to Zoho")

    token = await get_zoho_token()
    criteria = f'(JOB_ID == "{job_id}" && Customer_Email == "{email}")'
    rows = await fetch_zoho(REPORT_PROJECTS, criteria, token)
    if not rows:
        raise HTTPException(status_code=403, detail="You do not have access to this document.")

    record = rows[0]
    record_id = str(record.get("ID", ""))
    if not record_id:
        raise HTTPException(status_code=404, detail="Record ID not found")

    download_url = f"{ZOHO_API_BASE_V21}/report/{REPORT_PROJECTS}/{record_id}/{zoho_field}/download"
    print(f"[DOWNLOAD] {download_url}")

    async with httpx.AsyncClient() as c:
        r = await c.get(
            download_url,
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            timeout=60
        )
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not fetch file from Zoho")
        content = r.content
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
        headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'}
    )

@app.post("/api/note")
async def add_note(
    payload: dict,
    authorization: str = Header(default="")
):
    print(f"[REQ] /api/note")
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)
    print(f"[OK] Email: {email}")

    job_id = payload.get("job_id", "").strip()
    note   = payload.get("note", "").strip()

    if not job_id or not note:
        raise HTTPException(status_code=400, detail="job_id and note are required")

    if not ZOHO_REFRESH_TOKEN:
        raise HTTPException(status_code=503, detail="Server not connected to Zoho")

    token = await get_zoho_token()

    # 1. Verify this job belongs to this client
    criteria = f'(JOB_ID == "{job_id}" && Customer_Email == "{email}")'
    rows = await fetch_zoho(REPORT_PROJECTS, criteria, token)
    if not rows:
        raise HTTPException(status_code=403, detail="You do not have access to this job.")

    record = rows[0]
    record_id = str(record.get("ID", ""))
    existing_remarks = str(record.get("Project_Remarks", "") or "")

    # 2. Append new note with timestamp
    timestamp = datetime.now().strftime("%d-%b-%Y %H:%M")
    new_remark = f"[Client Note - {timestamp}]\n{note}"
    updated_remarks = (existing_remarks + "\n\n" + new_remark).strip()

    # 3. Update Project_Remarks in Zoho
    async with httpx.AsyncClient() as c:
        r = await c.patch(
            f"{ZOHO_API_BASE}/report/{REPORT_PROJECTS}/{record_id}",
            headers={
                "Authorization": f"Zoho-oauthtoken {token}",
                "Content-Type": "application/json"
            },
            json={"data": {"Project_Remarks": updated_remarks}},
            timeout=15
        )
        print(f"[ZOHO UPDATE] status={r.status_code} body={r.text[:200]}")
        if r.status_code not in [200, 201]:
            raise HTTPException(status_code=502, detail=f"Zoho update failed: {r.text[:200]}")

    print(f"[NOTE] Saved for job {job_id} by {email}")
    return {"status": "ok", "message": "Note saved and coordinator alerted"}

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
