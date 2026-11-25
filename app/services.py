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
from app.db.models import ActionStatus, Diagnosis, Incident, SessionLocal, utcnow
from app.observability import REMEDIATIONS, notify, record_triage_metrics

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
            triage_duration_ms=result.duration_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            model=result.model,
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
    record_triage_metrics(pod_summary["namespace"], result)
    notify(
        f":rotating_light: *{pod_summary['namespace']}/{pod_summary['name']}* "
        f"({', '.join(pod_summary['issues'])})\n{result.diagnosis}\n_Status: {result.status.value}_"
    )
    outcome = remediate(diagnosis_id, approved_by_human=False) if auto_remediate else None
    logger.info(
        "Triaged %s/%s -> %s (incident %d, %d tool calls)",
        pod_summary["namespace"],
        pod_summary["name"],
        outcome.status if outcome else result.status.value,
        incident_id,
        len(result.tool_trace),
    )
    return {"incident_id": incident_id, "diagnosis_id": diagnosis_id}


def remediate(diagnosis_id: int, *, approved_by_human: bool):
    """Run the executor and emit metrics/notifications for real outcomes."""
    outcome = execute_remediation(diagnosis_id, approved_by_human=approved_by_human)
    if outcome.changed:
        REMEDIATIONS.labels(outcome.status).inc()
        icon = ":white_check_mark:" if outcome.status == ActionStatus.EXECUTED.value else ":no_entry:"
        notify(f"{icon} Remediation for diagnosis {diagnosis_id}: *{outcome.status}* - {outcome.detail}")
    return outcome


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
        "detected_at": inc.detected_at.isoformat(timespec="seconds"),
        "diagnosis_id": diag.id if diag else None,
        "diagnosis": diag.diagnosis_text if diag else None,
        "tool_trace": diag.tool_trace if diag else [],
        "agent_iterations": diag.agent_iterations if diag else None,
        "triage_duration_ms": diag.triage_duration_ms if diag else None,
        "tokens": (diag.prompt_tokens + diag.completion_tokens) if diag else None,
        "model": diag.model if diag else None,
        "proposed_action_type": diag.proposed_action_type if diag else None,
        "proposed_target": diag.proposed_target if diag else None,
        "proposal_reason": diag.proposal_reason if diag else None,
        "action_status": diag.action_status if diag else None,
        "status_detail": diag.status_detail if diag else None,
        "executed_at": diag.executed_at.isoformat(timespec="seconds") if diag and diag.executed_at else None,
    }


def list_incidents(limit: int = 100, namespace: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        stmt = select(Incident).options(selectinload(Incident.diagnosis)).order_by(Incident.detected_at.desc())
        if namespace:
            stmt = stmt.where(Incident.namespace == namespace)
        return [serialize_incident(i) for i in db.scalars(stmt.limit(limit))]


def summary_stats() -> dict:
    """Aggregate numbers for the dashboard header and README metrics."""
    from sqlalchemy import func

    with SessionLocal() as db:
        by_status = dict(
            db.execute(select(Diagnosis.action_status, func.count()).group_by(Diagnosis.action_status)).all()
        )
        avg_ms, avg_tokens = db.execute(
            select(
                func.avg(Diagnosis.triage_duration_ms),
                func.avg(Diagnosis.prompt_tokens + Diagnosis.completion_tokens),
            ).where(Diagnosis.model.is_not(None))
        ).one()
        total = db.scalar(select(func.count()).select_from(Incident)) or 0
    return {
        "total_incidents": total,
        "by_status": by_status,
        "avg_triage_ms": round(avg_ms) if avg_ms else None,
        "avg_tokens": round(avg_tokens) if avg_tokens else None,
    }


def get_incident(incident_id: int) -> dict | None:
    with SessionLocal() as db:
        inc = db.get(Incident, incident_id, options=[selectinload(Incident.diagnosis)])
        return serialize_incident(inc) if inc else None
