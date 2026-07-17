"""
Simple chaos scripts to create real failures for your agent to catch.
Run these against your minikube cluster to generate demo-able incidents.
No fancy chaos engineering tool needed - just deliberately bad manifests.

Usage: python app/chaos/break_stuff.py crashloop
       python app/chaos/break_stuff.py oom
       python app/chaos/break_stuff.py badimage
"""

import subprocess
import sys

SCENARIOS = {
    "crashloop": """
apiVersion: v1
kind: Pod
metadata:
  name: chaos-crashloop
spec:
  containers:
  - name: crasher
    image: busybox
    command: ["sh", "-c", "echo 'simulated failure' && exit 1"]
""",
    "oom": """
apiVersion: v1
kind: Pod
metadata:
  name: chaos-oom
spec:
  containers:
  - name: memory-hog
    image: polinux/stress
    command: ["stress"]
    args: ["--vm", "1", "--vm-bytes", "300M", "--vm-hang", "1"]
    resources:
      limits:
        memory: "50Mi"
""",
    "badimage": """
apiVersion: v1
kind: Pod
metadata:
  name: chaos-badimage
spec:
  containers:
  - name: nope
    image: this-image-does-not-exist:latest
""",
}


def apply_scenario(name: str):
    manifest = SCENARIOS.get(name)
    if not manifest:
        print(f"Unknown scenario '{name}'. Options: {list(SCENARIOS.keys())}")
        sys.exit(1)

    subprocess.run(["kubectl", "apply", "-f", "-"], input=manifest, text=True, check=True)
    print(f"Applied chaos scenario: {name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python break_stuff.py [crashloop|oom|badimage]")
        sys.exit(1)
    apply_scenario(sys.argv[1])
