"""
Remediation executor: the only code path that mutates the cluster.

The LLM's proposal is treated as untrusted. Every safety rail below is
deterministic code, evaluated in order, and each skip is recorded with a
human-readable reason in `Diagnosis.status_detail`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from kubernetes.client.exceptions import ApiException
from sqlalchemy import select

from app.config import get_settings
from app.db.models import ActionStatus, Diagnosis, Incident, SessionLocal, utcnow
from app.k8s import client as k8s

logger = logging.getLogger(__name__)

SUPPORTED_ACTIONS = {"restart_pod"}


class DiagnosisNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class RemediationOutcome:
    diagnosis_id: int
    status: str
    detail: str
    changed: bool  # False when nothing was attempted (already handled / not actionable)


def _set(diag: Diagnosis, status: ActionStatus, detail: str) -> RemediationOutcome:
    diag.action_status = status.value
    diag.status_detail = detail
    log = logger.info if status == ActionStatus.EXECUTED else logger.warning
    log("Diagnosis %s -> %s: %s", diag.id, status.value, detail)
    return RemediationOutcome(diag.id, status.value, detail, changed=True)


def _recent_restarts(db, namespace: str, workload: str, window_minutes: int) -> int:
    cutoff = utcnow() - timedelta(minutes=window_minutes)
    stmt = (
        select(Diagnosis.id)
        .join(Incident)
        .where(
            Incident.namespace == namespace,
            Incident.workload == workload,
            Diagnosis.action_status == ActionStatus.EXECUTED.value,
            Diagnosis.executed_at >= cutoff,
        )
    )
    return len(db.execute(stmt).all())


def execute_remediation(diagnosis_id: int, *, approved_by_human: bool = False) -> RemediationOutcome:
    """
    Evaluate and (if every safety rail passes) execute a remediation proposal.
    Automatic callers pass approved_by_human=False; this only acts when
    AUTO_REMEDIATE is enabled.
    """
    settings = get_settings()
    with SessionLocal() as db:
        diag = db.get(Diagnosis, diagnosis_id)
        if diag is None:
            raise DiagnosisNotFoundError(diagnosis_id)

        if diag.action_status != ActionStatus.PENDING_APPROVAL.value:
            return RemediationOutcome(
                diag.id, diag.action_status, f"not actionable in status '{diag.action_status}'", changed=False
            )
        if not approved_by_human and not settings.auto_remediate:
            return RemediationOutcome(diag.id, diag.action_status, "awaiting human approval", changed=False)

        incident = diag.incident
        outcome = _evaluate_and_execute(db, diag, incident, settings)
        db.commit()
        return outcome


def _evaluate_and_execute(db, diag: Diagnosis, incident: Incident, settings) -> RemediationOutcome:
    action, target, namespace = diag.proposed_action_type, diag.proposed_target, incident.namespace

    if action not in SUPPORTED_ACTIONS:
        return _set(diag, ActionStatus.MANUAL_INTERVENTION, f"action '{action}' cannot be automated")

    # The model may only act on the pod it was asked to investigate.
    if target != incident.pod_name:
        return _set(
            diag, ActionStatus.SKIPPED_BY_SAFETY, f"proposed target '{target}' != incident pod '{incident.pod_name}'"
        )

    if namespace in settings.protected_namespaces:
        return _set(diag, ActionStatus.SKIPPED_BY_SAFETY, f"namespace '{namespace}' is protected")

    try:
        live_workload = k8s.get_pod_workload(target, namespace)
    except k8s.ClusterUnavailableError as exc:
        # Transient: leave it pending so it can be retried once the cluster is back.
        return RemediationOutcome(diag.id, diag.action_status, f"cluster unavailable: {exc}", changed=False)
    except ApiException as exc:
        return _set(diag, ActionStatus.FAILED, f"could not read pod: {exc.status} {exc.reason}")
    if live_workload is None:
        return _set(diag, ActionStatus.SKIPPED_BY_SAFETY, "pod no longer exists")
    if live_workload.split("/", 1)[0] not in k8s.RECREATING_OWNERS:
        return _set(
            diag,
            ActionStatus.SKIPPED_BY_SAFETY,
            f"pod is not managed by a controller ({live_workload}); delete would not recreate it",
        )

    recent = _recent_restarts(db, namespace, live_workload, settings.restart_window_minutes)
    if recent >= settings.max_restarts_per_window:
        return _set(
            diag,
            ActionStatus.SKIPPED_BY_SAFETY,
            f"{live_workload} already restarted {recent}x in the last {settings.restart_window_minutes}m",
        )

    try:
        k8s.delete_pod(target, namespace)
    except ApiException as exc:
        return _set(diag, ActionStatus.FAILED, f"delete failed: {exc.status} {exc.reason}")

    diag.executed_at = utcnow()
    return _set(diag, ActionStatus.EXECUTED, f"deleted pod {namespace}/{target}; {live_workload} will recreate it")
