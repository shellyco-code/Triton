"""
FastAPI entry point: health, cluster scan, on-demand triage, incident history,
human-approved remediation, and the live dashboard.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import groq
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse

from app import services
from app.agent.poller import poll_cluster
from app.agent.remediation_executor import DiagnosisNotFoundError, execute_remediation
from app.config import get_settings
from app.db.models import init_db
from app.k8s.client import ClusterUnavailableError, list_unhealthy_pods, load_k8s

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("triton")

DASHBOARD = Path(__file__).parent / "static" / "dashboard.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db(settings.database_url)
    k8s_ready = load_k8s()

    if not settings.api_token:
        logger.warning("TRITON_API_TOKEN is not set - mutating endpoints are unauthenticated (dev mode)")

    poller = None
    if settings.enable_poller and k8s_ready and settings.groq_api_key:
        poller = asyncio.create_task(poll_cluster())
    elif settings.enable_poller:
        logger.warning("Poller disabled: needs a reachable cluster and GROQ_API_KEY")

    yield

    if poller:
        poller.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller


app = FastAPI(title="Triton", description="AI triage agent for Kubernetes", version="1.0.0", lifespan=lifespan)


# --- Dependencies -----------------------------------------------------------------------


def require_api_token(authorization: str | None = Header(None)) -> None:
    expected = get_settings().api_token
    if not expected:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


def groq_api_key(x_groq_key: str | None = Header(None)) -> str:
    key = x_groq_key or get_settings().groq_api_key
    if not key:
        raise HTTPException(status_code=401, detail="No Groq API key (X-Groq-Key header or GROQ_API_KEY)")
    return key


# --- Routes -----------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/dashboard")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD, media_type="text/html")


@app.get("/scan")
async def scan(namespace: str | None = None):
    """Detection only - lists unhealthy pods without calling the LLM."""
    try:
        pods = await run_in_threadpool(list_unhealthy_pods, namespace, get_settings().pending_grace_seconds)
    except ClusterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Kubernetes API unavailable: {exc}") from exc
    return {"count": len(pods), "pods": pods}


@app.post("/triage/{namespace}/{pod_name}", dependencies=[Depends(require_api_token)])
async def triage(namespace: str, pod_name: str, api_key: str = Depends(groq_api_key)):
    """Run the agent on one pod now. The proposal is stored but never auto-executed."""
    try:
        pods = await run_in_threadpool(list_unhealthy_pods, namespace, 0)
    except ClusterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Kubernetes API unavailable: {exc}") from exc

    pod = next((p for p in pods if p["name"] == pod_name), None)
    if pod is None:
        raise HTTPException(status_code=404, detail=f"{namespace}/{pod_name} is not in the unhealthy list")

    try:
        ids = await run_in_threadpool(services.triage_and_record, pod, api_key=api_key)
    except groq.AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="Groq rejected the API key") from exc
    except groq.APIError as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider error: {exc}") from exc
    return services.get_incident(ids["incident_id"])


@app.get("/incidents")
def incidents(limit: int = Query(100, ge=1, le=500), namespace: str | None = None):
    return services.list_incidents(limit=limit, namespace=namespace)


@app.get("/incidents/{incident_id}")
def incident(incident_id: int):
    found = services.get_incident(incident_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return found


@app.post("/remediate/{diagnosis_id}", dependencies=[Depends(require_api_token)])
async def remediate(diagnosis_id: int):
    """Human approval: run the proposed action through every safety rail."""
    try:
        outcome = await run_in_threadpool(execute_remediation, diagnosis_id, approved_by_human=True)
    except DiagnosisNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Diagnosis not found") from exc
    if not outcome.changed:
        raise HTTPException(status_code=409, detail=outcome.detail)
    return {"diagnosis_id": outcome.diagnosis_id, "status": outcome.status, "detail": outcome.detail}
