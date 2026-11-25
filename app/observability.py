"""
Prometheus metrics, live runtime status, and outbound notifications.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime

import httpx
from prometheus_client import Counter, Gauge, Histogram

from app.config import get_settings

logger = logging.getLogger(__name__)

# --- Metrics --------------------------------------------------------------------------

INCIDENTS = Counter("triton_incidents_total", "Incidents triaged", ["namespace", "status"])
TRIAGE_SECONDS = Histogram(
    "triton_triage_duration_seconds", "End-to-end agent triage time", buckets=(1, 2, 4, 8, 15, 30, 60, 120)
)
TOOL_CALLS = Counter("triton_agent_tool_calls_total", "Agent tool invocations", ["tool", "ok"])
LLM_TOKENS = Counter("triton_llm_tokens_total", "LLM tokens consumed", ["kind"])
REMEDIATIONS = Counter("triton_remediations_total", "Remediation outcomes", ["status"])
UNHEALTHY_PODS = Gauge("triton_unhealthy_pods", "Unhealthy pods seen in the last scan")
SCAN_ERRORS = Counter("triton_scan_errors_total", "Failed cluster scans")


def record_triage_metrics(namespace: str, result) -> None:
    INCIDENTS.labels(namespace, result.status.value).inc()
    TRIAGE_SECONDS.observe(result.duration_ms / 1000)
    LLM_TOKENS.labels("prompt").inc(result.prompt_tokens)
    LLM_TOKENS.labels("completion").inc(result.completion_tokens)
    for call in result.tool_trace:
        TOOL_CALLS.labels(call["tool"], str(call.get("ok", True)).lower()).inc()


# --- Runtime status (what the dashboard's status bar shows) ---------------------------


@dataclass
class RuntimeStatus:
    k8s_connected: bool = False
    poller_running: bool = False
    poller_note: str | None = None
    last_scan_at: str | None = None
    last_scan_ok: bool | None = None
    last_scan_unhealthy: int | None = None
    last_scan_error: str | None = None


_status = RuntimeStatus()
_lock = threading.Lock()


def update_status(**changes) -> None:
    with _lock:
        for key, value in changes.items():
            setattr(_status, key, value)


def record_scan(ok: bool, unhealthy: int | None = None, error: str | None = None) -> None:
    update_status(
        last_scan_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        last_scan_ok=ok,
        last_scan_unhealthy=unhealthy,
        last_scan_error=error,
    )
    if ok:
        UNHEALTHY_PODS.set(unhealthy or 0)
    else:
        SCAN_ERRORS.inc()


def status_snapshot() -> dict:
    with _lock:
        return asdict(_status)


# --- Notifications --------------------------------------------------------------------


def notify(text: str) -> None:
    """POST a Slack-compatible {"text": ...} payload. Never raises."""
    url = get_settings().notify_webhook_url
    if not url:
        return
    try:
        httpx.post(url, json={"text": text}, timeout=5).raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Notification webhook failed: %s", exc)
