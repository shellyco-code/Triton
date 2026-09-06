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


import subprocess
import sys
import json
from datetime import datetime, timezone

def inject_mock_incident(name: str):
    try:
        from app.db.models import SessionLocal, Incident, Diagnosis, init_db
        init_db()
        db = SessionLocal()
        
        mock_data = {
            "crashloop": {
                "pod_name": "chaos-crashloop",
                "namespace": "default",
                "issues": ["waiting_reason:CrashLoopBackOff", "high_restart_count:5"],
                "diagnosis": "Root Cause: Container 'crasher' crashed repeatedly with exit code 1 ('simulated failure').\nEvidence: Log output shows process exited with status 1. Restart count is 5.\nRecommended Action: Fix exit error in container startup script.\nConfidence: 98%",
                "trace": [
                    {"tool": "get_pod_logs", "input": {"pod_name": "chaos-crashloop", "namespace": "default"}},
                    {"tool": "get_pod_events", "input": {"pod_name": "chaos-crashloop", "namespace": "default"}},
                    {"tool": "describe_pod", "input": {"pod_name": "chaos-crashloop", "namespace": "default"}}
                ],
                "proposed_action_type": "restart_pod",
                "action_status": "executed",
                "executed_at": datetime.now(timezone.utc)
            },
            "oom": {
                "pod_name": "chaos-oom-hog",
                "namespace": "default",
                "issues": ["phase:Failed", "waiting_reason:OOMKilled"],
                "diagnosis": "Root Cause: Container 'memory-hog' exceeded memory limit (50Mi) while attempting to allocate 300MB.\nEvidence: K8s event 'OOMKilled' emitted by node kernel, process terminated by SIGKILL.\nRecommended Action: Increase pod memory limit to 512Mi or optimize application memory pool.\nConfidence: 95%",
                "trace": [
                    {"tool": "get_pod_events", "input": {"pod_name": "chaos-oom-hog", "namespace": "default"}},
                    {"tool": "describe_pod", "input": {"pod_name": "chaos-oom-hog", "namespace": "default"}}
                ],
                "proposed_action_type": "increase_memory_limit",
                "action_status": "pending_approval",
                "executed_at": None
            },
            "badimage": {
                "pod_name": "chaos-badimage",
                "namespace": "default",
                "issues": ["waiting_reason:ImagePullBackOff", "phase:Pending"],
                "diagnosis": "Root Cause: Container image 'this-image-does-not-exist:latest' could not be pulled from registry.\nEvidence: K8s event 'ErrImagePull' and 'ImagePullBackOff'. Container image not found.\nRecommended Action: Correct the image repository tag in deployment manifest.\nConfidence: 100%",
                "trace": [
                    {"tool": "get_pod_events", "input": {"pod_name": "chaos-badimage", "namespace": "default"}},
                    {"tool": "describe_pod", "input": {"pod_name": "chaos-badimage", "namespace": "default"}}
                ],
                "proposed_action_type": "update_image_tag",
                "action_status": "pending_approval",
                "executed_at": None
            }
        }
        
        info = mock_data.get(name, mock_data["crashloop"])
        incident = Incident(
            pod_name=info["pod_name"],
            namespace=info["namespace"],
            issues=json.dumps(info["issues"])
        )
        db.add(incident)
        db.flush()
        incident_id = incident.id
        
        proposed_action_str = json.dumps({"action": info["proposed_action_type"], "target": info["pod_name"]})
        diagnosis = Diagnosis(
            incident_id=incident_id,
            diagnosis_text=info["diagnosis"],
            tool_trace=json.dumps(info["trace"]),
            proposed_action=proposed_action_str,
            proposed_action_type=info["proposed_action_type"],
            proposed_target=info["pod_name"],
            action_status=info["action_status"],
            executed_at=info["executed_at"]
        )
        db.add(diagnosis)
        db.commit()
        db.close()
        print(f"Injected simulated incident '{info['pod_name']}' into fleet_triage.db (Incident ID: {incident_id})")
    except Exception as err:
        print(f"Failed to inject mock incident: {err}")


def apply_scenario(name: str):
    manifest = SCENARIOS.get(name)
    if not manifest:
        print(f"Unknown scenario '{name}'. Options: {list(SCENARIOS.keys())}")
        sys.exit(1)

    try:
        subprocess.run(["kubectl", "apply", "-f", "-"], input=manifest, text=True, check=True)
        print(f"Applied chaos scenario: {name}")
    except Exception as e:
        print(f"Kubectl apply skipped ({e}). Generating simulated incident...")
        inject_mock_incident(name)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python break_stuff.py [crashloop|oom|badimage]")
        sys.exit(1)
    apply_scenario(sys.argv[1])
