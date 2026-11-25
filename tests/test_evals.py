"""The eval harness itself must work without network access."""

import json

from evals import run
from evals.scenarios import SCENARIOS

from .conftest import FakeLLM, final_answer, llm_message, tool_call


def test_harness_scores_a_correct_and_an_unsafe_answer(capsys):
    injection = next(s for s in SCENARIOS if s.id == "prompt-injection")
    crash = next(s for s in SCENARIOS if s.id == "transient-crash")

    good = run.evaluate(
        crash,
        1,
        FakeLLM(
            [
                llm_message(tool_calls=[tool_call("get_pod_logs", {"previous": True})]),
                final_answer(target=crash.pod["name"], diagnosis="Lost connection to the queue."),
            ]
        ),
    )
    assert good.passed

    hijacked = run.evaluate(
        injection,
        1,
        FakeLLM(
            [
                llm_message(tool_calls=[tool_call("get_pod_logs", {"previous": True})]),
                final_answer(target="payments-db-0", diagnosis="RecursionError in comment rendering"),
            ]
        ),
    )
    assert hijacked.safe is False
    assert hijacked.passed is False


def test_replay_returns_recorded_previous_logs():
    sc = next(s for s in SCENARIOS if s.id == "missing-config")
    from app.k8s import client as k8s

    with run.replay_cluster(sc):
        assert "STRIPE_API_KEY" in k8s.get_pod_logs("x", "shop", previous=True)
    assert k8s.get_pod_logs.__name__ == "get_pod_logs"  # restored


def test_main_writes_json_and_enforces_threshold(tmp_path):
    out = tmp_path / "r.json"
    responses = [final_answer(diagnosis="nothing useful") for _ in SCENARIOS]
    code = run.main(["--json", str(out), "--min-pass-rate", "50"], llm_client=FakeLLM(responses))
    data = json.loads(out.read_text())
    assert data["summary"]["runs"] == len(SCENARIOS)
    assert code == 1  # no tools called -> nothing passes -> below threshold
