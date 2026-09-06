"""
FastAPI Service Entry Point for Fleet Triage Agent.
Exposes endpoints for health check, cluster telemetry scans, pod triage execution,
remediation control, and live dashboard UI rendering.
"""

import json
import os
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import groq
load_dotenv()

from app.k8s.client import load_k8s, list_unhealthy_pods
from app.agent.triage_agent import triage_pod
from app.db.models import init_db, SessionLocal, Incident, Diagnosis
from app.agent.poller import poll_cluster
import asyncio

app = FastAPI(title="Fleet Triage Agent")

def validate_groq_key(x_groq_key: str | None = Header(None)):
    api_key = x_groq_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(status_code=401, detail="No Groq API key provided (header or .env)")
    return api_key


@app.on_event("startup")
def startup():
    load_k8s()
    init_db()
    asyncio.create_task(poll_cluster())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/scan")
def scan(namespace: str | None = None, api_key: str = Depends(validate_groq_key)):
    """Detection pass only - no AI call yet, just reports what's unhealthy."""
    unhealthy = list_unhealthy_pods(namespace)
    return {"count": len(unhealthy), "pods": unhealthy}


@app.post("/remediate/{diagnosis_id}")
def remediate_manual(diagnosis_id: int):
    """Temporary endpoint to manually trigger a remediation."""
    from app.agent.remediation_executor import execute_remediation
    execute_remediation(diagnosis_id)
    return {"status": "triggered", "diagnosis_id": diagnosis_id}


@app.post("/triage/{pod_name}")
def triage(pod_name: str, namespace: str | None = None, api_key: str = Depends(validate_groq_key)):
    """
    Runs the full agent loop on a specific pod and stores the result.
    In practice you'd call /scan first, then triage whichever pods look bad.
    """
    unhealthy = list_unhealthy_pods(namespace)
    pod_summary = next((p for p in unhealthy if p["name"] == pod_name), None)

    if pod_summary is None:
        raise HTTPException(status_code=404, detail="Pod not found in unhealthy list")

    try:
        result = triage_pod(pod_summary, api_key=api_key)
    except groq.AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))

    db = SessionLocal()
    incident = Incident(
        pod_name=pod_name,
        namespace=pod_summary["namespace"],
        issues=json.dumps(pod_summary["issues"]),
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)

    remediation_proposal = result.get("remediation_proposal")
    action_status = result.get("action_status", "pending_approval")
    
    proposed_action_type = None
    proposed_target = None
    proposed_action_str = None
    
    if remediation_proposal:
        proposed_action_str = json.dumps(remediation_proposal)
        proposed_action_type = remediation_proposal.get("action")
        proposed_target = remediation_proposal.get("target")

    diagnosis = Diagnosis(
        incident_id=incident.id,
        diagnosis_text=result["diagnosis"],
        tool_trace=json.dumps(result["tool_trace"]),
        proposed_action=proposed_action_str,
        proposed_action_type=proposed_action_type,
        proposed_target=proposed_target,
        action_status=action_status,
    )
    db.add(diagnosis)
    db.commit()
    db.refresh(diagnosis)
    
    incident_id = incident.id
    diagnosis_id = diagnosis.id
    db.close()

    return {"incident_id": incident_id, "diagnosis_id": diagnosis_id, **result}

@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    with open(os.path.join(os.path.dirname(__file__), "static", "dashboard.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/incidents")
def list_incidents():
    db = SessionLocal()
    incidents = db.query(Incident).all()
    out = []
    for inc in incidents:
        diag = db.query(Diagnosis).filter(Diagnosis.incident_id == inc.id).first()
        out.append({
            "id": inc.id,
            "pod_name": inc.pod_name,
            "issues": json.loads(inc.issues) if inc.issues else [],
            "detected_at": inc.detected_at.isoformat(),
            "diagnosis": diag.diagnosis_text if diag else None,
            "tool_trace": diag.tool_trace if diag else None,
            "proposed_action_type": diag.proposed_action_type if diag else None,
            "action_status": diag.action_status if diag else None,
            "executed_at": diag.executed_at.isoformat() if diag and diag.executed_at else None,
            "diagnosis_id": diag.id if diag else None,
        })
    db.close()
    return out
