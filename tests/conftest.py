from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.db.models import init_db


@pytest.fixture(autouse=True)
def settings_env(tmp_path, monkeypatch):
    """Isolated DB + deterministic settings for every test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("ENABLE_POLLER", "false")
    monkeypatch.setenv("AUTO_REMEDIATE", "false")
    monkeypatch.delenv("TRITON_API_TOKEN", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    get_settings.cache_clear()
    init_db(get_settings().database_url)
    yield
    get_settings.cache_clear()


# --- Fake LLM ------------------------------------------------------------------------


def tool_call(name: str, args: dict | None = None, call_id: str = "call_1"):
    return SimpleNamespace(
        id=call_id, type="function", function=SimpleNamespace(name=name, arguments=json.dumps(args or {}))
    )


def llm_message(content: str | None = None, tool_calls: list | None = None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def final_answer(action: str = "restart_pod", target: str = "web-abc", diagnosis: str = "Transient crash."):
    payload = {"diagnosis": diagnosis, "remediation_proposal": {"action": action, "target": target, "reason": "r"}}
    return llm_message(content=json.dumps(payload))


class FakeLLM:
    """Returns scripted responses in order and records every request."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)


# --- Fake cluster --------------------------------------------------------------------


@pytest.fixture
def fake_k8s(monkeypatch):
    """Patch app.k8s.client's cluster-touching functions with an in-memory fake."""
    from app.k8s import client as k8s

    state = SimpleNamespace(
        workloads={("default", "web-abc"): "ReplicaSet/web-5d8f"},
        deleted=[],
        tool_calls=[],
    )

    def get_pod_workload(name, ns):
        return state.workloads.get((ns, name))

    def delete_pod(name, ns):
        state.deleted.append((ns, name))

    def get_pod_logs(name, ns, tail_lines=100, previous=False):
        state.tool_calls.append(("logs", ns, name, previous))
        return "FATAL: lost connection to queue"

    def describe_pod(name, ns):
        state.tool_calls.append(("describe", ns, name))
        return {"name": name, "namespace": ns}

    def get_pod_events(name, ns):
        state.tool_calls.append(("events", ns, name))
        return [{"reason": "BackOff"}]

    for fn in (get_pod_workload, delete_pod, get_pod_logs, describe_pod, get_pod_events):
        monkeypatch.setattr(k8s, fn.__name__, fn)
    return state


POD = {
    "name": "web-abc",
    "namespace": "default",
    "workload": "ReplicaSet/web-5d8f",
    "phase": "Running",
    "issues": ["waiting_reason:CrashLoopBackOff"],
}
