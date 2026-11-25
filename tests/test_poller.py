from app.agent import poller, triage_agent
from app.config import get_settings

from .conftest import POD, FakeLLM, final_answer


def test_poll_once_triages_then_respects_cooldown(fake_k8s, monkeypatch):
    monkeypatch.setattr(poller, "list_unhealthy_pods", lambda *a, **k: [POD])
    monkeypatch.setattr(triage_agent, "make_groq_client", lambda key: FakeLLM([final_answer()]))

    assert poller.poll_once() == 1
    # Same workload under a new pod name (Deployment recreated it) is still in cooldown.
    monkeypatch.setattr(poller, "list_unhealthy_pods", lambda *a, **k: [{**POD, "name": "web-xyz"}])
    assert poller.poll_once() == 0
    assert fake_k8s.deleted == []  # AUTO_REMEDIATE is off


def test_poll_once_auto_remediates_when_enabled(fake_k8s, monkeypatch):
    monkeypatch.setenv("AUTO_REMEDIATE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(poller, "list_unhealthy_pods", lambda *a, **k: [POD])
    monkeypatch.setattr(triage_agent, "make_groq_client", lambda key: FakeLLM([final_answer()]))

    poller.poll_once()
    assert fake_k8s.deleted == [("default", "web-abc")]


def test_one_failing_pod_does_not_stop_the_loop(fake_k8s, monkeypatch):
    pods = [{**POD, "name": "a", "workload": "ReplicaSet/a"}, {**POD, "name": "b", "workload": "ReplicaSet/b"}]
    monkeypatch.setattr(poller, "list_unhealthy_pods", lambda *a, **k: pods)
    responses = iter([RuntimeError("LLM down"), final_answer(target="b")])

    class Flaky(FakeLLM):
        def _create(self, **kwargs):
            r = next(responses)
            if isinstance(r, Exception):
                raise r
            return r

    monkeypatch.setattr(triage_agent, "make_groq_client", lambda key: Flaky([]))
    assert poller.poll_once() == 1
