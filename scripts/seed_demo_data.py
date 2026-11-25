"""
Seed SAMPLE incidents for UI development - no cluster or LLM needed.

Writes to a separate database so sample data never mixes with real history:

    DATABASE_URL=sqlite:///./demo.db python -m scripts.seed_demo_data
    DATABASE_URL=sqlite:///./demo.db ENABLE_POLLER=false uvicorn app.main:app

Every sample lives in the `demo` namespace.
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta

from app.db.models import ActionStatus, Diagnosis, Incident, SessionLocal, init_db, utcnow

NS = "demo"


def trace(*steps):
    return [
        {"tool": t, "input": i, "ok": ok, "duration_ms": ms, **({"error": e} if e else {})} for t, i, ok, ms, e in steps
    ]


SAMPLES = [
    dict(
        minutes_ago=2,
        pod="checkout-api-7d9f8c6b5-x2kqp",
        workload="ReplicaSet/checkout-api-7d9f8c6b5",
        issues=["waiting_reason:CrashLoopBackOff", "high_restart_count:4"],
        diagnosis=(
            "Root cause: the worker exits with code 1 about 20s after start because it loses its connection "
            "to the message queue.\nEvidence: previous container logs end with 'FATAL: lost connection to "
            "queue'; 4 restarts; BackOff events.\nRecommended fix: restart to recover now, then check queue "
            "availability and add reconnect/backoff logic.\nConfidence: high"
        ),
        trace=trace(
            ("get_pod_events", {}, True, 38, None),
            ("get_pod_logs", {"previous": True}, True, 112, None),
            ("describe_pod", {}, True, 41, None),
        ),
        action="restart_pod",
        reason="Transient dependency failure; a fresh pod should reconnect.",
        status=ActionStatus.PENDING_APPROVAL,
        ms=3420,
        tokens=(2810, 196),
    ),
    dict(
        minutes_ago=9,
        pod="report-worker-5c4b9d7f8-mz7tw",
        workload="ReplicaSet/report-worker-5c4b9d7f8",
        issues=["last_terminated:OOMKilled", "high_restart_count:6"],
        diagnosis=(
            "Root cause: container 'worker' is OOMKilled. It allocates ~300Mi while its memory limit is 50Mi.\n"
            "Evidence: last termination reason OOMKilled (exit 137); describe_pod shows limits.memory=50Mi.\n"
            "Recommended fix: raise the memory limit to at least 384Mi or reduce batch size. Restarting will "
            "not help.\nConfidence: high"
        ),
        trace=trace(("describe_pod", {}, True, 44, None), ("get_pod_events", {}, True, 35, None)),
        action="manual_intervention",
        reason="Resource limit misconfiguration needs a manifest change.",
        status=ActionStatus.MANUAL_INTERVENTION,
        detail="action 'manual_intervention' cannot be automated",
        ms=2650,
        tokens=(2140, 171),
    ),
    dict(
        minutes_ago=16,
        pod="search-indexer-6f7d8b9c4-q8rld",
        workload="ReplicaSet/search-indexer-6f7d8b9c4",
        issues=["waiting_reason:ImagePullBackOff", "phase:Pending"],
        diagnosis=(
            "Root cause: the image 'registry.internal/search-indexer:v2.31' cannot be pulled (manifest unknown).\n"
            "Evidence: events show 'Failed to pull image ... not found' followed by ImagePullBackOff.\n"
            "Recommended fix: correct the image tag (latest published is v2.30) or push v2.31.\n"
            "Confidence: high"
        ),
        trace=trace(("get_pod_events", {}, True, 29, None), ("describe_pod", {}, True, 47, None)),
        action="manual_intervention",
        reason="Bad image reference; a restart pulls the same missing image.",
        status=ActionStatus.MANUAL_INTERVENTION,
        ms=2210,
        tokens=(1980, 158),
    ),
    dict(
        minutes_ago=34,
        pod="payments-api-84c6d9f7b-7hkdn",
        workload="ReplicaSet/payments-api-84c6d9f7b",
        issues=["not_ready"],
        diagnosis=(
            "Root cause: readiness probe fails while the connection pool is exhausted after a deadlock in the "
            "request handler.\nEvidence: logs show 'pool timeout after 30s' repeated; probe failures in events.\n"
            "Recommended fix: restart to clear the stuck pool; file a bug for the handler lock ordering.\n"
            "Confidence: medium"
        ),
        trace=trace(
            ("get_pod_logs", {"previous": False}, True, 96, None),
            ("get_pod_events", {}, True, 33, None),
        ),
        action="restart_pod",
        reason="Process is wedged; restart restores service.",
        status=ActionStatus.EXECUTED,
        detail="deleted pod demo/payments-api-84c6d9f7b-7hkdn; ReplicaSet/payments-api-84c6d9f7b will recreate it",
        executed_minutes_ago=33,
        ms=4120,
        tokens=(3350, 214),
    ),
    dict(
        minutes_ago=51,
        pod="payments-api-84c6d9f7b-k2v9s",
        workload="ReplicaSet/payments-api-84c6d9f7b",
        issues=["not_ready", "high_restart_count:3"],
        diagnosis=(
            "Root cause: same pool exhaustion as the previous incident on this workload.\n"
            "Evidence: identical 'pool timeout' log lines.\nRecommended fix: restart; escalate if it recurs.\n"
            "Confidence: medium"
        ),
        trace=trace(("get_pod_logs", {"previous": False}, True, 88, None)),
        action="restart_pod",
        reason="Process is wedged; restart restores service.",
        status=ActionStatus.SKIPPED_BY_SAFETY,
        detail="ReplicaSet/payments-api-84c6d9f7b already restarted 2x in the last 30m",
        ms=2980,
        tokens=(2460, 162),
    ),
    dict(
        minutes_ago=73,
        pod="legacy-cron-runner",
        workload="Pod/legacy-cron-runner",
        issues=["phase:Failed"],
        diagnosis=(
            "Root cause: the job script exits 2 because the CRON_TARGET environment variable is missing.\n"
            "Evidence: logs: 'CRON_TARGET is required'.\nRecommended fix: add the variable; this is a bare pod, "
            "so convert it to a CronJob.\nConfidence: high"
        ),
        trace=trace(
            ("describe_pod", {}, True, 40, None),
            (
                "get_pod_logs",
                {"previous": True},
                False,
                61,
                "ApiException: (400) previous terminated container not found",
            ),
            ("get_pod_logs", {"previous": False}, True, 74, None),
        ),
        action="restart_pod",
        reason="Retry the job.",
        status=ActionStatus.SKIPPED_BY_SAFETY,
        detail="pod is not managed by a controller (Pod/legacy-cron-runner); delete would not recreate it",
        ms=3710,
        tokens=(2920, 188),
    ),
]


def main() -> None:
    url = os.getenv("DATABASE_URL")
    if not url or "demo" not in url:
        sys.exit("Refusing to seed: set DATABASE_URL to a dedicated demo database, e.g. sqlite:///./demo.db")
    init_db(url)
    now = utcnow()
    with SessionLocal() as db:
        db.query(Diagnosis).delete()
        db.query(Incident).delete()
        for s in SAMPLES:
            inc = Incident(
                pod_name=s["pod"],
                namespace=NS,
                workload=s["workload"],
                issues=s["issues"],
                detected_at=now - timedelta(minutes=s["minutes_ago"]),
            )
            inc.diagnosis = Diagnosis(
                diagnosis_text=s["diagnosis"],
                tool_trace=s["trace"],
                agent_iterations=len(s["trace"]) + 1,
                triage_duration_ms=s["ms"],
                prompt_tokens=s["tokens"][0],
                completion_tokens=s["tokens"][1],
                model="llama-3.3-70b-versatile",
                proposed_action_type=s["action"],
                proposed_target=s["pod"],
                proposal_reason=s["reason"],
                action_status=s["status"].value,
                status_detail=s.get("detail"),
                executed_at=now - timedelta(minutes=s["executed_minutes_ago"]) if "executed_minutes_ago" in s else None,
                created_at=now - timedelta(minutes=s["minutes_ago"]),
            )
            db.add(inc)
        db.commit()
    print(f"Seeded {len(SAMPLES)} sample incidents into {url}")


if __name__ == "__main__":
    main()
