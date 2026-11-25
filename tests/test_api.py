import pytest
from fastapi.testclient import TestClient

from app import main
from app.agent.triage_agent import RemediationProposal, TriageResult
from app.config import get_settings
from app.db.models import ActionStatus
from app.k8s.client import ClusterUnavailableError
from app.services import record_triage

from .conftest import POD


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(main, "load_k8s", lambda: False)
    with TestClient(main.app) as c:
        yield c


def seed() -> int:
    proposal = RemediationProposal(action="restart_pod", target="web-abc", reason="r")
    _, diag_id = record_triage(POD, TriageResult("CrashLoop due to queue", proposal, ActionStatus.PENDING_APPROVAL))
    return diag_id


def test_health_and_dashboard(api):
    assert api.get("/health").json() == {"status": "ok"}
    r = api.get("/dashboard")
    assert r.status_code == 200
    assert "Triton" in r.text


def test_incidents_have_timezone_aware_timestamps(api):
    seed()
    [inc] = api.get("/incidents").json()
    assert inc["pod_name"] == "web-abc"
    assert inc["detected_at"].endswith("+00:00")
    assert inc["action_status"] == "pending_approval"
    assert api.get(f"/incidents/{inc['id']}").json()["id"] == inc["id"]
    assert api.get("/incidents/999").status_code == 404


def test_remediate_flow(api, fake_k8s):
    diag_id = seed()
    r = api.post(f"/remediate/{diag_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "executed"
    assert api.post(f"/remediate/{diag_id}").status_code == 409  # not actionable twice
    assert api.post("/remediate/999").status_code == 404


def test_mutating_endpoints_require_token_when_configured(api, fake_k8s, monkeypatch):
    monkeypatch.setenv("TRITON_API_TOKEN", "s3cret")
    get_settings.cache_clear()
    diag_id = seed()
    assert api.post(f"/remediate/{diag_id}").status_code == 401
    assert api.post(f"/remediate/{diag_id}", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.post(f"/remediate/{diag_id}", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_scan_returns_503_when_cluster_down(api, monkeypatch):
    def down(*args, **kwargs):
        raise ClusterUnavailableError("connection refused")

    monkeypatch.setattr(main, "list_unhealthy_pods", down)
    assert api.get("/scan").status_code == 503


def test_triage_requires_groq_key(api, monkeypatch):
    monkeypatch.setattr(main, "list_unhealthy_pods", lambda *a, **k: [POD])
    assert api.post("/triage/default/web-abc").status_code == 401
