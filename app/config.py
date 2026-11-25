"""
Runtime configuration, read from environment variables (and `.env` in dev).

Everything tunable lives here so the rest of the code never calls os.getenv
directly - that keeps behaviour testable and documented in one place.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

DEFAULT_PROTECTED_NAMESPACES = "kube-system,kube-public,kube-node-lease"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _optional(name: str) -> str | None:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else None


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./triton.db"

    # LLM
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    max_agent_iterations: int = 6
    max_tool_output_chars: int = 6000

    # Background poller
    enable_poller: bool = True
    poll_interval_seconds: int = 30
    triage_cooldown_minutes: int = 10
    watch_namespace: str | None = None
    pending_grace_seconds: int = 120

    # Remediation safety rails
    auto_remediate: bool = False
    max_restarts_per_window: int = 2
    restart_window_minutes: int = 30
    protected_namespaces: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_PROTECTED_NAMESPACES.split(","))
    )

    # API auth for mutating endpoints. Unset = open (local dev only).
    api_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    protected = os.getenv("PROTECTED_NAMESPACES", DEFAULT_PROTECTED_NAMESPACES)
    return Settings(
        database_url=os.getenv("DATABASE_URL", Settings.database_url),
        groq_api_key=_optional("GROQ_API_KEY"),
        groq_model=os.getenv("GROQ_MODEL", Settings.groq_model),
        max_agent_iterations=_int("MAX_AGENT_ITERATIONS", Settings.max_agent_iterations),
        max_tool_output_chars=_int("MAX_TOOL_OUTPUT_CHARS", Settings.max_tool_output_chars),
        enable_poller=_bool("ENABLE_POLLER", Settings.enable_poller),
        poll_interval_seconds=_int("POLL_INTERVAL_SECONDS", Settings.poll_interval_seconds),
        triage_cooldown_minutes=_int("TRIAGE_COOLDOWN_MINUTES", Settings.triage_cooldown_minutes),
        watch_namespace=_optional("WATCH_NAMESPACE"),
        pending_grace_seconds=_int("PENDING_GRACE_SECONDS", Settings.pending_grace_seconds),
        auto_remediate=_bool("AUTO_REMEDIATE", Settings.auto_remediate),
        max_restarts_per_window=_int("MAX_RESTARTS_PER_WINDOW", Settings.max_restarts_per_window),
        restart_window_minutes=_int("RESTART_WINDOW_MINUTES", Settings.restart_window_minutes),
        protected_namespaces=frozenset(ns.strip() for ns in protected.split(",") if ns.strip()),
        api_token=_optional("TRITON_API_TOKEN"),
    )
