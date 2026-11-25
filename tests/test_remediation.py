import pytest

from app.agent.remediation_executor import DiagnosisNotFoundError, execute_remediation
from app.agent.triage_agent import RemediationProposal, TriageResult
from app.db.models import ActionStatus
from app.services import record_triage

from .conftest import POD


def make_diag(pod=POD, action="restart_pod", target=None, status=ActionStatus.PENDING_APPROVAL) -> int:
    proposal = RemediationProposal(action=action, target=target or pod["name"], reason="r")
    _, diag_id = record_triage(pod, TriageResult("diag", proposal, status))
    return diag_id


def test_approved_restart_executes(fake_k8s):
    outcome = execute_remediation(make_diag(), approved_by_human=True)
    assert outcome.status == "executed"
    assert fake_k8s.deleted == [("default", "web-abc")]


def test_requires_approval_when_auto_remediate_off(fake_k8s):
    outcome = execute_remediation(make_diag())
    assert outcome.changed is False
    assert outcome.detail == "awaiting human approval"
    assert fake_k8s.deleted == []


def test_target_must_match_incident_pod(fake_k8s):
    outcome = execute_remediation(make_diag(target="payments-db"), approved_by_human=True)
    assert outcome.status == "skipped_by_safety"
    assert "payments-db" in outcome.detail
    assert fake_k8s.deleted == []


def test_protected_namespace(fake_k8s):
    pod = {**POD, "namespace": "kube-system"}
    fake_k8s.workloads[("kube-system", "web-abc")] = "ReplicaSet/x"
    outcome = execute_remediation(make_diag(pod), approved_by_human=True)
    assert outcome.status == "skipped_by_safety"
    assert fake_k8s.deleted == []


def test_bare_pod_is_not_deleted(fake_k8s):
    fake_k8s.workloads[("default", "web-abc")] = "Pod/web-abc"
    outcome = execute_remediation(make_diag(), approved_by_human=True)
    assert outcome.status == "skipped_by_safety"
    assert "not managed by a controller" in outcome.detail


def test_pod_already_gone(fake_k8s):
    fake_k8s.workloads.clear()
    assert execute_remediation(make_diag(), approved_by_human=True).detail == "pod no longer exists"


def test_rate_limit_is_per_workload_across_pod_names(fake_k8s):
    """Deployment pods get a new name after every restart - the limit must follow the ReplicaSet."""
    for i in range(3):
        name = f"web-{i}"
        fake_k8s.workloads[("default", name)] = "ReplicaSet/web-5d8f"
        outcome = execute_remediation(make_diag({**POD, "name": name}), approved_by_human=True)
    assert outcome.status == "skipped_by_safety"
    assert len(fake_k8s.deleted) == 2


def test_non_restart_action_becomes_manual(fake_k8s):
    outcome = execute_remediation(make_diag(action="increase_memory_limit"), approved_by_human=True)
    assert outcome.status == "manual_intervention"


def test_already_executed_is_idempotent(fake_k8s):
    diag_id = make_diag()
    execute_remediation(diag_id, approved_by_human=True)
    again = execute_remediation(diag_id, approved_by_human=True)
    assert again.changed is False
    assert len(fake_k8s.deleted) == 1


def test_cluster_outage_leaves_proposal_pending(fake_k8s, monkeypatch):
    from app.k8s import client as k8s

    def down(name, ns):
        raise k8s.ClusterUnavailableError("no config")

    monkeypatch.setattr(k8s, "get_pod_workload", down)
    diag_id = make_diag()
    outcome = execute_remediation(diag_id, approved_by_human=True)
    assert outcome.changed is False
    assert outcome.status == "pending_approval"


def test_missing_diagnosis():
    with pytest.raises(DiagnosisNotFoundError):
        execute_remediation(999, approved_by_human=True)
