"""
Thin wrapper around the Kubernetes Python client.
Everything the agent needs to "see" a cluster lives here.
Keep this dumb on purpose - no AI logic, just data fetching.
"""

from kubernetes import client, config
from datetime import datetime, timezone


def load_k8s():
    """
    Loads kube config. Works for both local (minikube) and in-cluster use.
    Call this once at startup.
    """
    try:
        config.load_kube_config()  # local dev, reads ~/.kube/config
    except config.ConfigException:
        config.load_incluster_config()  # if this were running inside a pod


def list_unhealthy_pods(namespace: str | None = None):
    """
    Returns pods that look broken: CrashLoopBackOff, Pending too long,
    high restart counts, or not Ready.
    If namespace is None, queries all namespaces.
    This is what the agent's watch loop polls on an interval.
    """
    v1 = client.CoreV1Api()
    if namespace:
        pods = v1.list_namespaced_pod(namespace)
    else:
        pods = v1.list_pod_for_all_namespaces()

    unhealthy = []
    for pod in pods.items:
        issues = []

        # Check container statuses for crash loops / waiting states
        for cs in pod.status.container_statuses or []:
            if cs.restart_count and cs.restart_count >= 3:
                issues.append(f"high_restart_count:{cs.restart_count}")

            waiting = cs.state.waiting
            if waiting and waiting.reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                issues.append(f"waiting_reason:{waiting.reason}")

            if not cs.ready and pod.status.phase == "Running":
                issues.append("not_ready")

        if pod.status.phase in ("Pending", "Failed"):
            issues.append(f"phase:{pod.status.phase}")

        if issues:
            unhealthy.append({
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "phase": pod.status.phase,
                "issues": issues,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            })

    return unhealthy


def get_pod_logs(pod_name: str, namespace: str = "default", tail_lines: int = 100) -> str:
    """
    Fetches recent logs for a pod. This is the agent's primary
    diagnostic tool - most root causes show up here.
    """
    v1 = client.CoreV1Api()
    try:
        return v1.read_namespaced_pod_log(
            name=pod_name, namespace=namespace, tail_lines=tail_lines
        )
    except client.exceptions.ApiException as e:
        return f"[error fetching logs: {e.reason}]"


def describe_pod(pod_name: str, namespace: str = "default") -> dict:
    """
    Structured pod detail - equivalent to `kubectl describe pod`,
    but returned as data the agent can reason over.
    """
    v1 = client.CoreV1Api()
    pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)

    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "node": pod.spec.node_name,
        "phase": pod.status.phase,
        "containers": [
            {
                "name": c.name,
                "image": c.image,
                "resources": c.resources.to_dict() if c.resources else {},
            }
            for c in pod.spec.containers
        ],
        "conditions": [
            {"type": c.type, "status": c.status, "message": c.message}
            for c in (pod.status.conditions or [])
        ],
    }


def get_pod_events(pod_name: str, namespace: str = "default") -> list:
    """
    Fetches recent Kubernetes events tied to a pod - often has the
    clearest signal (e.g. "OOMKilled", "FailedScheduling").
    """
    v1 = client.CoreV1Api()
    events = v1.list_namespaced_event(
        namespace=namespace,
        field_selector=f"involvedObject.name={pod_name}",
    )
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

def delete_pod(pod_name: str, namespace: str = "default"):
    """
    Deletes a pod. For pods managed by a ReplicaSet/Deployment,
    this effectively restarts them.
    """
    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
        return True
    except client.exceptions.ApiException as e:
        print(f"Failed to delete pod {pod_name}: {e}")
        return False

