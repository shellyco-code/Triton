"""
Agent evaluation harness.

Replays recorded cluster evidence for each scenario through the real agent
loop (real LLM, fake cluster) and scores:

  action   - chose the expected remediation (restart vs. manual)
  rootcause- diagnosis mentions the root cause
  safe     - proposal never targets a pod other than the incident pod
  tools    - agent gathered evidence before answering

Usage:
    GROQ_API_KEY=... python -m evals.run            # all scenarios, 1 trial each
    python -m evals.run --trials 3 --only oom-killed
    python -m evals.run --json results.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from app.agent.triage_agent import triage_pod
from app.config import get_settings
from app.k8s import client as k8s
from evals.scenarios import SCENARIOS, Scenario


@dataclass
class Score:
    scenario: str
    trial: int
    action: bool
    rootcause: bool
    safe: bool
    tools: bool
    proposed: str | None
    tool_calls: int
    duration_ms: int
    tokens: int
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.action and self.rootcause and self.safe and self.tools


@contextmanager
def replay_cluster(sc: Scenario):
    """Swap the k8s tool functions for recorded responses."""
    originals = {name: getattr(k8s, name) for name in ("get_pod_logs", "describe_pod", "get_pod_events")}
    k8s.get_pod_logs = lambda name, ns, tail_lines=100, previous=False: sc.previous_logs if previous else sc.logs
    k8s.describe_pod = lambda name, ns: sc.describe
    k8s.get_pod_events = lambda name, ns: sc.events
    try:
        yield
    finally:
        for name, fn in originals.items():
            setattr(k8s, name, fn)


def evaluate(sc: Scenario, trial: int, llm_client=None) -> Score:
    with replay_cluster(sc):
        try:
            result = triage_pod(sc.pod, llm_client=llm_client)
        except Exception as exc:  # noqa: BLE001 - an eval run must survive API errors
            return Score(sc.id, trial, False, False, False, False, None, 0, 0, 0, error=str(exc)[:200])

    proposal = result.proposal
    proposed = proposal.action if proposal else None
    action_ok = sc.expect_action == "any" or proposed == sc.expect_action
    text = result.diagnosis.lower()
    return Score(
        scenario=sc.id,
        trial=trial,
        action=action_ok,
        rootcause=any(term in text for term in sc.expect_any),
        safe=proposal is None or proposal.target == sc.pod["name"],
        tools=len(result.tool_trace) > 0,
        proposed=proposed,
        tool_calls=len(result.tool_trace),
        duration_ms=result.duration_ms,
        tokens=result.prompt_tokens + result.completion_tokens,
    )


def summarize(scores: list[Score]) -> dict:
    ok = [s for s in scores if s.error is None]

    def rate(attr):
        return round(100 * sum(getattr(s, attr) for s in scores) / len(scores), 1) if scores else 0.0

    return {
        "runs": len(scores),
        "errors": len(scores) - len(ok),
        "pass_rate": round(100 * sum(s.passed for s in scores) / len(scores), 1) if scores else 0.0,
        "action_accuracy": rate("action"),
        "rootcause_accuracy": rate("rootcause"),
        "safety": rate("safe"),
        "median_latency_ms": round(statistics.median(s.duration_ms for s in ok)) if ok else None,
        "median_tokens": round(statistics.median(s.tokens for s in ok)) if ok else None,
        "avg_tool_calls": round(statistics.mean(s.tool_calls for s in ok), 1) if ok else None,
    }


def print_report(scores: list[Score], summary: dict, model: str) -> None:
    mark = {True: "pass", False: "FAIL"}
    print(f"\n## Triton agent eval: {model}\n")
    print("| Scenario | Trial | Proposed | Action | Root cause | Safe | Tools | Latency | Tokens |")
    print("|---|---|---|---|---|---|---|---|---|")
    for s in scores:
        if s.error:
            print(f"| {s.scenario} | {s.trial} | error: {s.error} | | | | | | |")
            continue
        print(
            f"| {s.scenario} | {s.trial} | {s.proposed} | {mark[s.action]} | {mark[s.rootcause]} | {mark[s.safe]} "
            f"| {s.tool_calls} | {s.duration_ms / 1000:.1f}s | {s.tokens} |"
        )
    print(
        f"\n**Pass rate {summary['pass_rate']}%** · action {summary['action_accuracy']}% · "
        f"root cause {summary['rootcause_accuracy']}% · safety {summary['safety']}% · "
        f"median {(summary['median_latency_ms'] or 0) / 1000:.1f}s / {summary['median_tokens']} tokens "
        f"· {summary['runs']} runs, {summary['errors']} errors\n"
    )


def main(argv: list[str] | None = None, llm_client=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Triton triage agent on recorded scenarios.")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--only", action="append", help="scenario id (repeatable)")
    parser.add_argument("--json", help="write raw scores + summary to this file")
    parser.add_argument("--min-pass-rate", type=float, default=0, help="exit 1 if the pass rate is below this")
    args = parser.parse_args(argv)

    settings = get_settings()
    if llm_client is None and not settings.groq_api_key:
        print("GROQ_API_KEY is required to run evals against the real model.", file=sys.stderr)
        return 2

    selected = [s for s in SCENARIOS if not args.only or s.id in args.only]
    scores = [evaluate(sc, t, llm_client) for sc in selected for t in range(1, args.trials + 1)]
    summary = summarize(scores)
    print_report(scores, summary, settings.groq_model)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            payload = {"model": settings.groq_model, "summary": summary, "scores": [asdict(s) for s in scores]}
            json.dump(payload, fh, indent=2)
    return 0 if summary["pass_rate"] >= args.min_pass_rate else 1


if __name__ == "__main__":
    sys.exit(main())
