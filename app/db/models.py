"""
SQLite schema via SQLAlchemy. Three tables, kept deliberately simple:
- incidents: an unhealthy pod detected at a point in time
- diagnoses: the agent's investigation result for an incident
- actions: what was done about it (manual for now, automated later)
"""

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

engine = create_engine("sqlite:///./fleet_triage.db", echo=False)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    pod_name = Column(String, nullable=False)
    namespace = Column(String, nullable=False)
    issues = Column(Text)  # JSON-encoded list of detected issues
    detected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    diagnosis_text = Column(Text)
    tool_trace = Column(Text)  # JSON-encoded list of tool calls made
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Remediation fields
    proposed_action = Column(String)  # JSON string of the proposal
    proposed_action_type = Column(String)
    proposed_target = Column(String)
    action_status = Column(String, default="pending_approval")
    executed_at = Column(DateTime, nullable=True)


class ActionTaken(Base):
    __tablename__ = "actions_taken"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"))
    action = Column(String)  # e.g. "restarted", "scaled", "ignored"
    taken_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(engine)
