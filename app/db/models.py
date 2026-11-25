"""
SQLAlchemy schema.

- incidents: an unhealthy pod detected at a point in time
- diagnoses: the agent's investigation + remediation proposal for that incident
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """
    Stores datetimes as naive UTC and always returns timezone-aware UTC.
    SQLite drops tzinfo, which previously made clients misread timestamps
    as local time.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class ActionStatus(str, enum.Enum):
    PENDING_APPROVAL = "pending_approval"  # restart proposed, waiting for a human (or auto mode)
    EXECUTED = "executed"
    SKIPPED_BY_SAFETY = "skipped_by_safety"
    FAILED = "failed"
    MANUAL_INTERVENTION = "manual_intervention"  # agent says a human must fix it (no safe automation)
    PARSE_ERROR = "parse_error"


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    pod_name: Mapped[str] = mapped_column(String, index=True)
    namespace: Mapped[str] = mapped_column(String, index=True)
    # Stable identity across pod restarts, e.g. "ReplicaSet/api-7d9f" or "Pod/bare-pod".
    workload: Mapped[str] = mapped_column(String, index=True)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    diagnosis: Mapped[Diagnosis | None] = relationship(
        back_populates="incident", uselist=False, cascade="all, delete-orphan"
    )


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), unique=True)
    diagnosis_text: Mapped[str] = mapped_column(Text)
    tool_trace: Mapped[list] = mapped_column(JSON, default=list)
    agent_iterations: Mapped[int] = mapped_column(default=0)
    triage_duration_ms: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    model: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    proposed_action_type: Mapped[str | None] = mapped_column(String)
    proposed_target: Mapped[str | None] = mapped_column(String)
    proposal_reason: Mapped[str | None] = mapped_column(Text)

    action_status: Mapped[str] = mapped_column(String, default=ActionStatus.PENDING_APPROVAL.value)
    status_detail: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    incident: Mapped[Incident] = relationship(back_populates="diagnosis")


engine = None
SessionLocal = sessionmaker(expire_on_commit=False)


def init_db(database_url: str) -> None:
    """Create the engine, bind the session factory and create tables."""
    global engine
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    SessionLocal.configure(bind=engine)
    Base.metadata.create_all(engine)
