"""
Kubernetes API wrapper: detection, read-only diagnostics, and pod restarts.

Detection logic (`detect_issues`) is a pure function over V1Pod objects so it
can be unit-tested without a cluster.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)

BAD_WAITING_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "InvalidImageName",
}
RESTART_THRESHOLD = 3
# Owner kinds whose controllers recreate a deleted pod.
RECREATING_OWNERS = {"ReplicaSet", "StatefulSet", "DaemonSet", "ReplicationController"}


class ClusterUnavailableError(RuntimeError):
    """Raised when the Kubernetes API cannot be reached."""


_configured = False


def load_k8s() -> bool:
    """Load in-cluster config, falling back to local kubeconfig. Returns True on success."""
    global _configured
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
        _configured = True
    except config.ConfigException:
        try:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig")
            _configured = True
        except Exception as exc:  # noqa: BLE001 - kube config errors are varied
            logger.warning("Could not load Kubernetes config: %s", exc)
    return _configured


def _core() -> client.CoreV1Api:
    if not _configured:
        # Without config the client silently targets localhost:80 and retries for ~12s.
        raise ClusterUnavailableError("no Kubernetes config loaded (kubeconfig or in-cluster)")
    return client.CoreV1Api()


def workload_of(pod: client.V1Pod) -> str:
    """Stable identity for rate limiting / dedup: the controller, or the pod itself."""
    for ref in pod.metadata.owner_references or []:
        if ref.controller:
            return f"{ref.kind}/{ref.name}"
    return f"Pod/{pod.metadata.name}"


def detect_issues(pod: client.V1Pod, now: datetime, pending_grace_seconds: int = 120) -> list[str]:
    issues: list[str] = []
    status = pod.status
    phase = status.phase

    for cs in status.container_statuses or []:
        if cs.restart_count and cs.restart_count >= RESTART_THRESHOLD:
            issues.append(f"high_restart_count:{cs.restart_count}")

        waiting = cs.state.waiting if cs.state else None
        if waiting and waiting.reason in BAD_WAITING_REASONS:
            issues.append(f"waiting_reason:{waiting.reason}")

        terminated = cs.last_state.terminated if cs.last_state else None
        if terminated and terminated.reason == "OOMKilled":
            issues.append("last_terminated:OOMKilled")

        if not cs.ready and phase == "Running" and not (waiting and waiting.reason in BAD_WAITING_REASONS):
            issues.append("not_ready")

    if phase == "Failed":
        issues.append("phase:Failed")
    elif phase == "Pending":
        created = pod.metadata.creation_timestamp
        if created is None or (now - created).total_seconds() >= pending_grace_seconds:
            issues.append("phase:Pending")

    # De-duplicate (multi-container pods) while preserving order.
    return list(dict.fromkeys(issues))


def list_unhealthy_pods(namespace: str | None = None, pending_grace_seconds: int = 120) -> list[dict]:
    """Return a summary dict for every pod that looks broken."""
    try:
        api = _core()
        pods = api.list_namespaced_pod(namespace) if namespace else api.list_pod_for_all_namespaces()
    except Exception as exc:  # noqa: BLE001 - urllib3 / ApiException / config errors
        raise ClusterUnavailableError(str(exc)) from exc

    now = datetime.now(timezone.utc)
    unhealthy = []
    for pod in pods.items:
        if pod.metadata.deletion_timestamp:
            continue  # already terminating
        issues = detect_issues(pod, now, pending_grace_seconds)
        if issues:
            unhealthy.append(
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "workload": workload_of(pod),
                    "phase": pod.status.phase,
                    "issues": issues,
                    "checked_at": now.isoformat(),
                }
            )
    return unhealthy


# --- Read-only diagnostic tools exposed to the agent ---------------------------------


def get_pod_logs(pod_name: str, namespace: str, tail_lines: int = 100, previous: bool = False) -> str:
    """Recent logs. `previous=True` reads the last crashed container instance."""
    try:
        logs = _core().read_namespaced_pod_log(
            name=pod_name, namespace=namespace, tail_lines=tail_lines, previous=previous
        )
        return logs or "[no log output]"
    except ApiException as exc:
        return f"[error fetching logs: {exc.status} {exc.reason}]"


def describe_pod(pod_name: str, namespace: str) -> dict:
    """Structured equivalent of `kubectl describe pod`."""
    pod = _core().read_namespaced_pod(name=pod_name, namespace=namespace)
    container_statuses = {cs.name: cs for cs in pod.status.container_statuses or []}

    def _state(cs):
        if cs is None or cs.state is None:
            return None
        for key in ("waiting", "running", "terminated"):
            val = getattr(cs.state, key)
            if val is not None:
                return {
                    "state": key,
                    "reason": getattr(val, "reason", None),
                    "exit_code": getattr(val, "exit_code", None),
                }
        return None

    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "node": pod.spec.node_name,
        "phase": pod.status.phase,
        "owner": workload_of(pod),
        "containers": [
            {
                "name": c.name,
                "image": c.image,
                "resources": c.resources.to_dict() if c.resources else {},
                "restart_count": getattr(container_statuses.get(c.name), "restart_count", None),
                "current_state": _state(container_statuses.get(c.name)),
                "last_termination_reason": (
                    container_statuses[c.name].last_state.terminated.reason
                    if c.name in container_statuses
                    and container_statuses[c.name].last_state
                    and container_statuses[c.name].last_state.terminated
                    else None
                ),
            }
            for c in pod.spec.containers
        ],
        "conditions": [
            {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
            for c in (pod.status.conditions or [])
        ],
    }


def get_pod_events(pod_name: str, namespace: str) -> list[dict]:
    """Recent events for the pod - often the clearest signal (FailedScheduling, BackOff...)."""
    events = _core().list_namespaced_event(namespace=namespace, field_selector=f"involvedObject.name={pod_name}")
    return [
        {
            "reason": e.reason,
            "message": e.message,
            "type": e.type,
            "count": e.count,
            "last_timestamp": e.last_timestamp.isoformat() if e.last_timestamp else None,
        }
        for e in events.items
    ]


# --- Mutating operations (used only by the remediation executor) ---------------------


def get_pod_workload(pod_name: str, namespace: str) -> str | None:
    """Live owner lookup. Returns None if the pod no longer exists."""
    try:
        return workload_of(_core().read_namespaced_pod(name=pod_name, namespace=namespace))
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def delete_pod(pod_name: str, namespace: str) -> None:
    """Delete a pod so its controller recreates it. Raises ApiException on failure."""
    _core().delete_namespaced_pod(name=pod_name, namespace=namespace)
