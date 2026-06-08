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

# ── CORS — Firebase Hosting URL allow karo ──────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nabl-raw-data-sheet.web.app",
        "https://nabl-raw-data-sheet.firebaseapp.com",
        "http://localhost",
        "http://127.0.0.1",
        "*"  # testing ke liye — production mein hatao
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Config ───────────────────────────────────────────────────────────
ZOHO_CLIENT_ID     = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
WEBHOOK_SECRET     = os.getenv("WEBHOOK_SECRET", "hot-secret")
FIREBASE_PROJECT   = os.getenv("FIREBASE_PROJECT_ID", "nabl-raw-data-sheet")

ZOHO_ACCOUNT       = "houseoftesting"
ZOHO_APP           = "house-of-testing-lab"
ZOHO_API_BASE      = f"https://creator.zoho.in/api/v2/{ZOHO_ACCOUNT}/{ZOHO_APP}"

# ── Sample data (jab tak Zoho connect nahi) ─────────────────────────
SAMPLE_PROJECTS = [
    {
        "JOB_ID": "JOB-2026-047", "Project_Status": "Testing Started",
        "Standard": "IS 16047 Part 3", "Product": "LED Luminaire 40W",
        "Lead_Model": "BN126C LED40", "Manufacturer_Name": "Philips",
        "Booking_Date": "28-May-2026", "Testing_Start_Date": "1-Jun-2026",
        "Final_Report_Issue_Date": "", "Raw_Data_Sheet_Status": "Testing",
        "Test_Report_Download_Link": "", "Test_Report": "",
        "Raw_Data_Sheet": "", "CCL": "", "TRF": "", "Request_Letter_ILC": "",
        "Test_Report_No": "TR-2026-084", "Customer_Name": "Client",
        "Customer_Email": "", "SRF_ID": "SRF-0024",
    },
    {
        "JOB_ID": "JOB-2026-031", "Project_Status": "Final Report Issued",
        "Standard": "IS 616 (2017)", "Product": "Street Light 80W",
        "Lead_Model": "HVSL-80-NW", "Manufacturer_Name": "Havells",
        "Booking_Date": "8-May-2026", "Testing_Start_Date": "12-May-2026",
        "Final_Report_Issue_Date": "20-May-2026", "Raw_Data_Sheet_Status": "Completed",
        "Test_Report_Download_Link": "#", "Test_Report": "#",
        "Raw_Data_Sheet": "#", "CCL": "#", "TRF": "#", "Request_Letter_ILC": "",
        "Test_Report_No": "TR-2026-058", "Customer_Name": "Client",
        "Customer_Email": "", "SRF_ID": "SRF-0019",
    },
]

SAMPLE_SRFS = [
    {
        "SRF_ID": "SRF-0024", "SRF_Status": "Booked",
        "Product_Sample_Details_Technical_specifications": "LED Luminaire 40W",
        "Test_Requirement": "IS 16047 Part 3", "Added_Time": "28-May-2026",
        "Manufacturer_Name": "Philips", "Brand_Name": "Philips",
        "Model_Name": "BN126C LED40", "Email_id": "",
    },
    {
        "SRF_ID": "SRF-0019", "SRF_Status": "Submitted",
        "Product_Sample_Details_Technical_specifications": "Street Light 80W",
        "Test_Requirement": "IS 616 (2017)", "Added_Time": "8-May-2026",
        "Manufacturer_Name": "Havells", "Brand_Name": "Havells",
        "Model_Name": "HVSL-80-NW", "Email_id": "",
    },
]

# ── Zoho Token ───────────────────────────────────────────────────────
async def get_zoho_token() -> str:
    """Zoho refresh token se access token lao."""
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
            }
        )
        data = r.json()
        return data.get("access_token", "")

# ── Firebase Token Verify ────────────────────────────────────────────
async def verify_firebase_token(id_token: str) -> str:
    """Firebase ID token verify karo — client email return karo."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key=AIzaSyBmEFd1xIRY7I8XVSePqAHYIDeQ-iqpDmE"
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json={"idToken": id_token})
        data = r.json()
        if "users" not in data or not data["users"]:
            raise HTTPException(status_code=401, detail="Invalid token")
        return data["users"][0]["email"]

# ── Zoho API fetch ───────────────────────────────────────────────────
async def fetch_zoho(report: str, criteria: str, token: str) -> list:
    """Zoho Creator se records lao."""
    params = {"criteria": criteria, "max_records": 200}
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{ZOHO_API_BASE}/report/{report}",
            headers=headers,
            params=params,
            timeout=15
        )
        data = r.json()
        return data.get("data", [])

# ═══════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════

@app.get("/health")
def health():
    zoho_configured = bool(ZOHO_REFRESH_TOKEN)
    return {
        "status": "ok",
        "server": "HoT Portal API",
        "zoho_connected": zoho_configured,
        "mode": "LIVE" if zoho_configured else "SAMPLE DATA"
    }

@app.get("/api/projects")
async def get_projects(authorization: str = Header(default="")):
    """Client ke projects return karo — filtered by email."""
    # Token extract karo
    token_parts = authorization.split(" ")
    if len(token_parts) != 2 or token_parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    id_token = token_parts[1]

    # Firebase token verify karo — email lo
    try:
        email = await verify_firebase_token(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Token verification failed")

    # Zoho configured hai? Real data lao
    if ZOHO_REFRESH_TOKEN:
        try:
            zoho_token = await get_zoho_token()
            criteria   = f'Customer_Email == "{email}"'
            projects   = await fetch_zoho("User_Client_Portal", criteria, zoho_token)

            # Customer name inject karo
            for p in projects:
                p["Customer_Email"] = email

            return {"email": email, "count": len(projects), "data": projects, "mode": "LIVE"}
        except Exception as e:
            print(f"Zoho error: {e} — falling back to sample data")

    # Sample data — email inject karo taaki naam dikhaye
    sample = []
    for p in SAMPLE_PROJECTS:
        proj = dict(p)
        proj["Customer_Email"] = email
        sample.append(proj)

    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}

@app.get("/api/srfs")
async def get_srfs(authorization: str = Header(default="")):
    """Client ke SRFs return karo — filtered by email."""
    token_parts = authorization.split(" ")
    if len(token_parts) != 2 or token_parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    id_token = token_parts[1]

    try:
        email = await verify_firebase_token(id_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Token verification failed")

    if ZOHO_REFRESH_TOKEN:
        try:
            zoho_token = await get_zoho_token()
            criteria   = f'Email_id == "{email}"'
            srfs       = await fetch_zoho("All_SRF_Records", criteria, zoho_token)
            return {"email": email, "count": len(srfs), "data": srfs, "mode": "LIVE"}
        except Exception as e:
            print(f"Zoho error: {e} — falling back to sample data")

    sample = []
    for s in SAMPLE_SRFS:
        srf = dict(s)
        srf["Email_id"] = email
        sample.append(srf)

    return {"email": email, "count": len(sample), "data": sample, "mode": "SAMPLE"}


class WebhookPayload(BaseModel):
    email:         str
    customer_name: str = ""
    srf_id:        str = ""
    secret:        str = ""

@app.post("/webhook/srf-submitted")
async def webhook_srf(payload: WebhookPayload):
    """Zoho workflow se call hota hai — Firebase account banata hai."""
    if payload.secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    # Firebase Admin SDK se account create (baad mein implement karenge)
    print(f"[WEBHOOK] New SRF from: {payload.email} — {payload.srf_id}")

    return {
        "status": "ok",
        "message": f"Account creation queued for {payload.email}"
    }
