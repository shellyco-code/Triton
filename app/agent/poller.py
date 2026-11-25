"""
Background watch loop: scan -> dedup -> triage -> (optionally) remediate.

All blocking work (Kubernetes + LLM + DB) runs in a worker thread so the
FastAPI event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi.concurrency import run_in_threadpool

from app import services
from app.config import get_settings
from app.k8s.client import ClusterUnavailableError, list_unhealthy_pods
from app.observability import record_scan

logger = logging.getLogger(__name__)


def poll_once() -> int:
    """One scan + triage pass. Returns the number of pods triaged."""
    settings = get_settings()
    try:
        pods = list_unhealthy_pods(settings.watch_namespace, settings.pending_grace_seconds)
    except ClusterUnavailableError as exc:
        logger.warning("Cluster unavailable, skipping scan: %s", exc)
        record_scan(ok=False, error=str(exc)[:300])
        return 0
    record_scan(ok=True, unhealthy=len(pods))

    triaged = 0
    for pod in pods:
        if services.recently_triaged(pod["namespace"], pod["workload"], settings.triage_cooldown_minutes):
            logger.debug("Skipping %s/%s (cooldown)", pod["namespace"], pod["name"])
            continue
        try:
            services.triage_and_record(pod, auto_remediate=settings.auto_remediate)
            triaged += 1
        except Exception:  # noqa: BLE001 - one bad pod must not stop the loop
            logger.exception("Failed to triage %s/%s", pod["namespace"], pod["name"])
    return triaged


async def poll_cluster() -> None:
    settings = get_settings()
    logger.info(
        "Poller started (interval=%ss, cooldown=%sm, namespace=%s, auto_remediate=%s)",
        settings.poll_interval_seconds,
        settings.triage_cooldown_minutes,
        settings.watch_namespace or "*",
        settings.auto_remediate,
    )
    while True:
        try:
            await run_in_threadpool(poll_once)
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error in polling loop")
        await asyncio.sleep(settings.poll_interval_seconds)
