"""
Chaos scenarios: deploy deliberately broken workloads for the agent to catch.

Each scenario is a Deployment (not a bare Pod) so a restart remediation
actually gets the pod recreated by its ReplicaSet.

Usage:
    python -m app.chaos.break_stuff crashloop|oom|badimage|all
    python -m app.chaos.break_stuff cleanup
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys

NAMESPACE = "triton-chaos"
LABEL = "app.kubernetes.io/part-of=triton-chaos"


def _deployment(name: str, container: str) -> str:
    return f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  namespace: {NAMESPACE}
  labels: {{app.kubernetes.io/part-of: triton-chaos}}
spec:
  replicas: 1
  selector: {{matchLabels: {{app: {name}}}}}
  template:
    metadata:
      labels: {{app: {name}, app.kubernetes.io/part-of: triton-chaos}}
    spec:
      containers:
{container}
"""


SCENARIOS = {
    # Crashes ~20s after start: a restart "helps" briefly - tests the restart rate limit.
    "crashloop": _deployment(
        "chaos-crashloop",
        """      - name: crasher
        image: busybox:1.36
        command: ["sh", "-c"]
        args: ["echo starting worker; sleep 20; echo 'FATAL: lost connection to queue' >&2; exit 1"]""",
    ),
    # Allocates 300M with a 50Mi limit -> OOMKilled. Needs manual_intervention (raise the limit).
    "oom": _deployment(
        "chaos-oom",
        """      - name: memory-hog
        image: polinux/stress:1.0.4
        command: ["stress"]
        args: ["--vm", "1", "--vm-bytes", "300M", "--vm-hang", "1"]
        resources:
          limits: {memory: "50Mi"}""",
    ),
    # Image doesn't exist -> ImagePullBackOff. Needs manual_intervention (fix the tag).
    "badimage": _deployment(
        "chaos-badimage",
        """      - name: nope
        image: registry.invalid/this-image-does-not-exist:latest""",
    ),
}


def _kubectl(*args: str, stdin: str | None = None) -> None:
    if shutil.which("kubectl") is None:
        sys.exit("kubectl not found on PATH - install it and point it at your cluster (e.g. `minikube start`).")
    subprocess.run(["kubectl", *args], input=stdin, text=True, check=True)


def apply(names: list[str]) -> None:
    namespace = f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {NAMESPACE}\n"
    manifests = "---".join([namespace, *(SCENARIOS[n] for n in names)])
    _kubectl("apply", "-f", "-", stdin=manifests)
    print(f"Applied {', '.join(names)} in namespace '{NAMESPACE}'. Watch: kubectl get pods -n {NAMESPACE} -w")


def cleanup() -> None:
    _kubectl("delete", "namespace", NAMESPACE, "--ignore-not-found")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=[*SCENARIOS, "all", "cleanup"])
    args = parser.parse_args(argv)

    if args.scenario == "cleanup":
        cleanup()
    elif args.scenario == "all":
        apply(list(SCENARIOS))
    else:
        apply([args.scenario])


if __name__ == "__main__":
    main()
