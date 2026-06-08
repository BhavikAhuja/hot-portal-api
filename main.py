"""
HoT Client Portal — API Server
================================
Railway pe deploy hoga.
Firebase token verify karega + Zoho Creator se data laayega.

Environment Variables (Railway mein set karo):
  ZOHO_CLIENT_ID       → Zoho API Console se
  ZOHO_CLIENT_SECRET   → Zoho API Console se
  ZOHO_REFRESH_TOKEN   → OAuth flow se
  WEBHOOK_SECRET       → koi bhi secret string
"""

import os
import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="HoT Portal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Config ───────────────────────────────────────────────────────────
ZOHO_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
WEBHOOK_SECRET     = os.getenv("WEBHOOK_SECRET", "hot-secret")
FIREBASE_API_KEY   = "AIzaSyBmEFd1xIRY7I8XVSePqAHYIDeQ-iqpDmE"

ZOHO_ACCOUNT       = "houseoftesting"
ZOHO_APP           = "house-of-testing-lab"
ZOHO_API_BASE      = f"https://creator.zoho.in/api/v2/{ZOHO_ACCOUNT}/{ZOHO_APP}"

# ── Correct Report Names (from schema) ──────────────────────────────
REPORT_PROJECTS    = "Booked_Projects"   # Book_a_Project report
REPORT_SRFS        = "SRF1_Report"       # SRF1 report

# ── Zoho Token ───────────────────────────────────────────────────────
async def get_zoho_token() -> str:
    if not ZOHO_REFRESH_TOKEN:
        return ""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://accounts.zoho.in/oauth/v2/token",
            data={
                "grant_type":    "refresh_token",
                "client_id":     ZOHO_CLIENT_ID,
                "client_secret": ZOHO_CLIENT_SECRET,
                "refresh_token": ZOHO_REFRESH_TOKEN,
            },
            timeout=15
        )
        data = r.json()
        return data.get("access_token", "")

# ── Firebase Token Verify ────────────────────────────────────────────
async def verify_firebase_token(id_token: str) -> str:
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}"
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json={"idToken": id_token}, timeout=10)
        data = r.json()
        if "users" not in data or not data["users"]:
            raise HTTPException(status_code=401, detail="Invalid token")
        return data["users"][0]["email"]

# ── Zoho API fetch ───────────────────────────────────────────────────
async def fetch_zoho(report: str, criteria: str, token: str) -> list:
    params = {"criteria": criteria, "max_records": 200}
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{ZOHO_API_BASE}/report/{report}",
            headers=headers,
            params=params,
            timeout=20
        )
        print(f"[ZOHO] {report} status: {r.status_code}")
        data = r.json()
        if "data" not in data:
            print(f"[ZOHO] Error response: {data}")
        return data.get("data", [])

# ── Token extract helper ─────────────────────────────────────────────
def extract_token(authorization: str) -> str:
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    return parts[1]

# ═══════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {
        "status": "ok",
        "server": "HoT Portal API",
        "zoho_connected": bool(ZOHO_REFRESH_TOKEN),
        "mode": "LIVE" if ZOHO_REFRESH_TOKEN else "SAMPLE DATA",
        "reports": {
            "projects": REPORT_PROJECTS,
            "srfs": REPORT_SRFS
        }
    }

@app.get("/api/projects")
async def get_projects(authorization: str = Header(default="")):
    id_token = extract_token(authorization)

    try:
        email = await verify_firebase_token(id_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

    print(f"[API] /api/projects called for: {email}")

    if ZOHO_REFRESH_TOKEN:
        try:
            zoho_token = await get_zoho_token()
            if not zoho_token:
                raise Exception("Could not get Zoho token")

            criteria = f'Customer_Email == "{email}"'
            projects = await fetch_zoho(REPORT_PROJECTS, criteria, zoho_token)

            print(f"[API] Found {len(projects)} projects for {email}")
            return {
                "email":  email,
                "count":  len(projects),
                "data":   projects,
                "mode":   "LIVE"
            }
        except Exception as e:
            print(f"[ZOHO ERROR] {e} — falling back to sample data")

    # Sample data fallback
    sample = get_sample_projects(email)
    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}


@app.get("/api/srfs")
async def get_srfs(authorization: str = Header(default="")):
    id_token = extract_token(authorization)

    try:
        email = await verify_firebase_token(id_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")

    print(f"[API] /api/srfs called for: {email}")

    if ZOHO_REFRESH_TOKEN:
        try:
            zoho_token = await get_zoho_token()
            if not zoho_token:
                raise Exception("Could not get Zoho token")

            criteria = f'Email_id == "{email}"'
            srfs = await fetch_zoho(REPORT_SRFS, criteria, zoho_token)

            print(f"[API] Found {len(srfs)} SRFs for {email}")
            return {
                "email": email,
                "count": len(srfs),
                "data":  srfs,
                "mode":  "LIVE"
            }
        except Exception as e:
            print(f"[ZOHO ERROR] {e} — falling back to sample data")

    sample = get_sample_srfs(email)
    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}


class WebhookPayload(BaseModel):
    email:         str
    customer_name: str = ""
    srf_id:        str = ""
    secret:        str = ""

@app.post("/webhook/srf-submitted")
async def webhook_srf(payload: WebhookPayload):
    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    print(f"[WEBHOOK] New SRF from: {payload.email} — {payload.srf_id}")
    return {"status": "ok", "message": f"Received for {payload.email}"}


# ═══════════════════════════════════════════════════════════
# SAMPLE DATA
# ═══════════════════════════════════════════════════════════

def get_sample_projects(email: str) -> list:
    return [
        {
            "JOB_ID": "JOB-2026-047",
            "Project_Status": "Testing Started",
            "Standard": "IS 16047 Part 3",
            "Product": "LED Luminaire 40W",
            "Lead_Model": "BN126C LED40",
            "Manufacturer_Name": "Philips",
            "Booking_Date": "28-May-2026",
            "Testing_Start_Date": "1-Jun-2026",
            "Final_Report_Issue_Date": "",
            "Raw_Data_Sheet_Status": "Testing",
            "Test_Report_Download_Link": "",
            "Customer_Name": email.split("@")[0].replace(".", " ").title(),
            "Customer_Email": email,
        },
        {
            "JOB_ID": "JOB-2026-031",
            "Project_Status": "Final Report Issued",
            "Standard": "IS 616 (2017)",
            "Product": "Street Light 80W",
            "Lead_Model": "HVSL-80-NW",
            "Manufacturer_Name": "Havells",
            "Booking_Date": "8-May-2026",
            "Testing_Start_Date": "12-May-2026",
            "Final_Report_Issue_Date": "20-May-2026",
            "Raw_Data_Sheet_Status": "Completed",
            "Test_Report_Download_Link": "#",
            "Customer_Name": email.split("@")[0].replace(".", " ").title(),
            "Customer_Email": email,
        },
    ]

def get_sample_srfs(email: str) -> list:
    return [
        {
            "SRF_ID": "SRF-0024",
            "SRF_Status": "Booked",
            "Product_Sample_Details_Technical_specifications": "LED Luminaire 40W",
            "Test_Requirement": "IS 16047 Part 3",
            "Added_Time": "28-May-2026",
            "Manufacturer_Name": "Philips",
            "Brand_Name": "Philips",
            "Model_Name": "BN126C LED40",
            "Email_id": email,
        },
        {
            "SRF_ID": "SRF-0019",
            "SRF_Status": "Submitted",
            "Product_Sample_Details_Technical_specifications": "Street Light 80W",
            "Test_Requirement": "IS 616 (2017)",
            "Added_Time": "8-May-2026",
            "Manufacturer_Name": "Havells",
            "Brand_Name": "Havells",
            "Model_Name": "HVSL-80-NW",
            "Email_id": email,
        },
    ]
