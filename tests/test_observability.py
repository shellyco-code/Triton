from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, observability
from app.agent.triage_agent import triage_pod
from app.config import get_settings
from app.services import triage_and_record

from .conftest import POD, FakeLLM, final_answer, llm_message, tool_call


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(main, "load_k8s", lambda: False)
    with TestClient(main.app) as c:
        yield c


def with_usage(response, prompt, completion):
    response.usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    return response


def test_agent_records_tokens_and_duration(fake_k8s):
    llm = FakeLLM(
        [
            with_usage(llm_message(tool_calls=[tool_call("get_pod_events")]), 100, 20),
            with_usage(final_answer(), 150, 60),
        ]
    )
    result = triage_pod(POD, llm_client=llm)
    assert (result.prompt_tokens, result.completion_tokens) == (250, 80)
    assert result.duration_ms >= 0
    assert result.model == get_settings().groq_model


def test_status_reports_why_poller_is_off(api):
    body = api.get("/status").json()
    assert body["poller_running"] is False
    assert body["poller_note"] == "disabled by ENABLE_POLLER=false"
    assert body["k8s_connected"] is False
    assert "kube-system" in body["protected_namespaces"]


def test_stats_and_metrics(api, fake_k8s, monkeypatch):
    from app.agent import triage_agent

    monkeypatch.setattr(triage_agent, "make_groq_client", lambda key: FakeLLM([with_usage(final_answer(), 300, 100)]))
    triage_and_record(POD)

    stats = api.get("/stats").json()
    assert stats["total_incidents"] == 1
    assert stats["by_status"] == {"pending_approval": 1}
    assert stats["avg_tokens"] == 400

    metrics = api.get("/metrics/").text
    assert "triton_incidents_total" in metrics
    assert "triton_triage_duration_seconds_bucket" in metrics


def test_webhook_notification(monkeypatch, fake_k8s):
    from app.agent import triage_agent

    sent = []

    class Resp:
        def raise_for_status(self):
            pass

    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example/x")
    get_settings.cache_clear()
    monkeypatch.setattr(observability.httpx, "post", lambda url, json, timeout: sent.append(json) or Resp())
    monkeypatch.setattr(triage_agent, "make_groq_client", lambda key: FakeLLM([final_answer()]))

    triage_and_record(POD)
    assert len(sent) == 1
    assert "default/web-abc" in sent[0]["text"]


def test_webhook_failure_never_raises(monkeypatch):
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "https://hooks.example/x")
    get_settings.cache_clear()

    def boom(*a, **k):
        raise observability.httpx.ConnectError("down")

    monkeypatch.setattr(observability.httpx, "post", boom)
    observability.notify("hello")  # must not raise
