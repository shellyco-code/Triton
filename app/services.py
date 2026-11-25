"""
Application service layer shared by the API and the background poller.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.remediation_executor import execute_remediation
from app.agent.triage_agent import TriageResult, triage_pod
from app.db.models import Diagnosis, Incident, SessionLocal, utcnow

logger = logging.getLogger(__name__)


def record_triage(pod_summary: dict, result: TriageResult) -> tuple[int, int]:
    """Persist an incident and its diagnosis. Returns (incident_id, diagnosis_id)."""
    proposal = result.proposal
    with SessionLocal() as db:
        incident = Incident(
            pod_name=pod_summary["name"],
            namespace=pod_summary["namespace"],
            workload=pod_summary.get("workload") or f"Pod/{pod_summary['name']}",
            issues=pod_summary["issues"],
        )
        incident.diagnosis = Diagnosis(
            diagnosis_text=result.diagnosis,
            tool_trace=result.tool_trace,
            agent_iterations=result.iterations,
            proposed_action_type=proposal.action if proposal else None,
            proposed_target=proposal.target if proposal else None,
            proposal_reason=proposal.reason if proposal else None,
            action_status=result.status.value,
        )
        db.add(incident)
        db.commit()
        return incident.id, incident.diagnosis.id


def triage_and_record(pod_summary: dict, *, api_key: str | None = None, auto_remediate: bool = False) -> dict:
    """Run the agent on one pod, store the result, optionally attempt remediation."""
    result = triage_pod(pod_summary, api_key=api_key)
    incident_id, diagnosis_id = record_triage(pod_summary, result)
    outcome = execute_remediation(diagnosis_id) if auto_remediate else None
    logger.info(
        "Triaged %s/%s -> %s (incident %d, %d tool calls)",
        pod_summary["namespace"],
        pod_summary["name"],
        outcome.status if outcome else result.status.value,
        incident_id,
        len(result.tool_trace),
    )
    return {"incident_id": incident_id, "diagnosis_id": diagnosis_id}


def recently_triaged(namespace: str, workload: str, cooldown_minutes: int) -> bool:
    """Dedup by workload so a crash-looping Deployment isn't re-triaged on every new pod name."""
    cutoff = utcnow() - timedelta(minutes=cooldown_minutes)
    with SessionLocal() as db:
        stmt = select(Incident.id).where(
            Incident.namespace == namespace, Incident.workload == workload, Incident.detected_at >= cutoff
        )
        return db.execute(stmt.limit(1)).first() is not None


def serialize_incident(inc: Incident) -> dict:
    diag = inc.diagnosis
    return {
        "id": inc.id,
        "pod_name": inc.pod_name,
        "namespace": inc.namespace,
        "workload": inc.workload,
        "issues": inc.issues or [],
        "detected_at": inc.detected_at.isoformat(),
        "diagnosis_id": diag.id if diag else None,
        "diagnosis": diag.diagnosis_text if diag else None,
        "tool_trace": diag.tool_trace if diag else [],
        "agent_iterations": diag.agent_iterations if diag else None,
        "proposed_action_type": diag.proposed_action_type if diag else None,
        "proposed_target": diag.proposed_target if diag else None,
        "proposal_reason": diag.proposal_reason if diag else None,
        "action_status": diag.action_status if diag else None,
        "status_detail": diag.status_detail if diag else None,
        "executed_at": diag.executed_at.isoformat() if diag and diag.executed_at else None,
    }


def list_incidents(limit: int = 100, namespace: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        stmt = select(Incident).options(selectinload(Incident.diagnosis)).order_by(Incident.detected_at.desc())
        if namespace:
            stmt = stmt.where(Incident.namespace == namespace)
        return [serialize_incident(i) for i in db.scalars(stmt.limit(limit))]


def get_incident(incident_id: int) -> dict | None:
    with SessionLocal() as db:
        inc = db.get(Incident, incident_id, options=[selectinload(Incident.diagnosis)])
        return serialize_incident(inc) if inc else None
