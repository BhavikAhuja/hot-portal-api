@app.post("/api/note")
async def add_note(
    payload: dict,
    authorization: str = Header(default="")
):
    print(f"[REQ] /api/note")
    id_token = extract_token(authorization)
    email = await verify_firebase_token(id_token)
    print(f"[OK] Email: {email}")

    job_id = payload.get("job_id","").strip()
    note   = payload.get("note","").strip()

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
    record_id = str(record.get("ID",""))
    existing_remarks = str(record.get("Project_Remarks2","") or "")
    coordinator_email = str(record.get("Project_Coordinator_Email","") or
                           record.get("Project_Manager_Email","") or "")

    # 2. Append new note to existing remarks
    from datetime import datetime
    timestamp = datetime.now().strftime("%d-%b-%Y %H:%M")
    new_remark = f"[Client Note - {timestamp}]\n{note}"
    updated_remarks = (existing_remarks + "\n\n" + new_remark).strip()

    # 3. Update Project_Remarks2 in Zoho
    async with httpx.AsyncClient() as c:
        r = await c.patch(
            f"{ZOHO_API_BASE}/form/{REPORT_PROJECTS}/{record_id}",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            json={"Project_Remarks2": updated_remarks},
            timeout=15
        )
        print(f"[ZOHO UPDATE] status={r.status_code}")

    print(f"[NOTE] Saved for job {job_id} by {email}")
    return {"status": "ok", "message": "Note saved and coordinator alerted"}
