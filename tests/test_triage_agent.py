from app.agent.triage_agent import parse_final_answer, triage_pod
from app.config import get_settings
from app.db.models import ActionStatus
from app.k8s import client as k8s

from .conftest import POD, FakeLLM, final_answer, llm_message, tool_call


def test_tool_loop_then_final_answer(fake_k8s):
    llm = FakeLLM(
        [
            llm_message(tool_calls=[tool_call("get_pod_events"), tool_call("get_pod_logs", {"previous": True}, "c2")]),
            final_answer(),
        ]
    )
    result = triage_pod(POD, llm_client=llm)

    assert result.status == ActionStatus.PENDING_APPROVAL
    assert result.proposal.action == "restart_pod"
    assert [t["tool"] for t in result.tool_trace] == ["get_pod_events", "get_pod_logs"]
    assert fake_k8s.tool_calls == [("events", "default", "web-abc"), ("logs", "default", "web-abc", True)]
    tool_msgs = [m for m in llm.requests[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_1", "c2"]


def test_tools_are_scoped_to_the_incident_pod(fake_k8s):
    """Model-supplied pod/namespace args are ignored, so prompt injection can't redirect reads."""
    llm = FakeLLM(
        [
            llm_message(tool_calls=[tool_call("describe_pod", {"pod_name": "secrets", "namespace": "kube-system"})]),
            final_answer(),
        ]
    )
    triage_pod(POD, llm_client=llm)
    assert fake_k8s.tool_calls == [("describe", "default", "web-abc")]


def test_tool_errors_are_reported_to_model_not_raised(fake_k8s, monkeypatch):
    def boom(name, ns):
        raise RuntimeError("api down")

    monkeypatch.setattr(k8s, "describe_pod", boom)
    llm = FakeLLM(
        [
            llm_message(
                tool_calls=[
                    tool_call("describe_pod"),
                    tool_call("not_a_tool", call_id="c2"),
                    tool_call("get_pod_logs", call_id="c3"),
                ]
            ),
            final_answer(action="manual_intervention"),
        ]
    )
    result = triage_pod(POD, llm_client=llm)
    assert [t["ok"] for t in result.tool_trace] == [False, False, True]
    assert "api down" in result.tool_trace[0]["error"]
    assert result.status == ActionStatus.MANUAL_INTERVENTION


def test_malformed_tool_arguments_do_not_crash(fake_k8s):
    bad = tool_call("get_pod_logs")
    bad.function.arguments = "{not json"
    result = triage_pod(POD, llm_client=FakeLLM([llm_message(tool_calls=[bad]), final_answer()]))
    assert result.tool_trace[0]["ok"] is False


def test_iteration_budget_forces_final_answer(fake_k8s, monkeypatch):
    monkeypatch.setenv("MAX_AGENT_ITERATIONS", "2")
    get_settings.cache_clear()
    looping = [llm_message(tool_calls=[tool_call("get_pod_events", call_id=f"c{i}")]) for i in range(2)]
    llm = FakeLLM([*looping, final_answer()])
    result = triage_pod(POD, llm_client=llm)

    assert len(llm.requests) == 3
    assert llm.requests[-1]["tool_choice"] == "none"
    assert result.status == ActionStatus.PENDING_APPROVAL


def test_unparseable_answer_is_parse_error(fake_k8s):
    result = triage_pod(POD, llm_client=FakeLLM([llm_message(content="I think it is broken.")]))
    assert result.status == ActionStatus.PARSE_ERROR
    assert result.proposal is None


def test_parse_final_answer_handles_fences_and_prose():
    content = 'Here you go:\n```json\n{"diagnosis": "x", "remediation_proposal": null}\n```'
    assert parse_final_answer(content).diagnosis == "x"
    assert parse_final_answer('{"diagnosis": ""}') is None  # empty diagnosis rejected
    assert parse_final_answer(None) is None
