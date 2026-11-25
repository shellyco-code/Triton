from datetime import datetime, timedelta, timezone

from kubernetes.client import (
    V1ContainerState,
    V1ContainerStateTerminated,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1ObjectMeta,
    V1OwnerReference,
    V1Pod,
    V1PodStatus,
)

from app.k8s.client import detect_issues, workload_of

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_pod(phase="Running", statuses=None, created=NOW - timedelta(hours=1), owners=None, name="p"):
    return V1Pod(
        metadata=V1ObjectMeta(name=name, namespace="default", creation_timestamp=created, owner_references=owners),
        status=V1PodStatus(phase=phase, container_statuses=statuses),
    )


def cstatus(ready=True, restarts=0, waiting=None, last_terminated=None):
    return V1ContainerStatus(
        name="c",
        image="img",
        image_id="",
        ready=ready,
        restart_count=restarts,
        state=V1ContainerState(waiting=V1ContainerStateWaiting(reason=waiting) if waiting else None),
        last_state=V1ContainerState(
            terminated=V1ContainerStateTerminated(exit_code=137, reason=last_terminated) if last_terminated else None
        ),
    )


def test_healthy_pod_has_no_issues():
    assert detect_issues(make_pod(statuses=[cstatus()]), NOW) == []


def test_crashloop_with_restarts():
    pod = make_pod(statuses=[cstatus(ready=False, restarts=5, waiting="CrashLoopBackOff")])
    # no redundant "not_ready" when the waiting reason already explains it
    assert detect_issues(pod, NOW) == ["high_restart_count:5", "waiting_reason:CrashLoopBackOff"]


def test_oomkilled_detected_from_last_state():
    pod = make_pod(statuses=[cstatus(restarts=1, last_terminated="OOMKilled")])
    assert "last_terminated:OOMKilled" in detect_issues(pod, NOW)


def test_not_ready_running_pod():
    assert detect_issues(make_pod(statuses=[cstatus(ready=False)]), NOW) == ["not_ready"]


def test_pending_respects_grace_period():
    fresh = make_pod(phase="Pending", created=NOW - timedelta(seconds=30))
    stale = make_pod(phase="Pending", created=NOW - timedelta(minutes=5))
    assert detect_issues(fresh, NOW, pending_grace_seconds=120) == []
    assert detect_issues(stale, NOW, pending_grace_seconds=120) == ["phase:Pending"]


def test_image_pull_backoff():
    pod = make_pod(phase="Pending", statuses=[cstatus(ready=False, waiting="ImagePullBackOff")])
    assert "waiting_reason:ImagePullBackOff" in detect_issues(pod, NOW)


def test_workload_prefers_controller_owner():
    owner = V1OwnerReference(api_version="apps/v1", kind="ReplicaSet", name="web-5d8f", uid="u", controller=True)
    assert workload_of(make_pod(owners=[owner])) == "ReplicaSet/web-5d8f"
    assert workload_of(make_pod(name="bare")) == "Pod/bare"
