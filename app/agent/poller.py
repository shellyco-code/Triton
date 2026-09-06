import asyncio
import os
import json
import logging
from datetime import datetime, timedelta, timezone
from fastapi.concurrency import run_in_threadpool

from app.k8s.client import list_unhealthy_pods
from app.agent.triage_agent import triage_pod
from app.db.models import SessionLocal, Incident, Diagnosis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

async def poll_cluster():
    """
    Background loop that scans for unhealthy pods on an interval.
    If a new unhealthy pod is found, it triggers the triage_pod agent workflow.
    """
    interval = int(os.getenv("POLL_INTERVAL_SECONDS", "30"))
    # Cooldown before we re-triage the same pod (e.g. 10 minutes)
    cooldown_minutes = int(os.getenv("TRIAGE_COOLDOWN_MINUTES", "10"))
    
    logger.info(f"Starting poller. Interval: {interval}s, Cooldown: {cooldown_minutes}m")
    
    while True:
        try:
            logger.info("Scanning for unhealthy pods...")
            
            # Since list_unhealthy_pods does HTTP requests synchronously to k8s, 
            # we run it in a threadpool to not block the asyncio event loop.
            watch_namespace = os.getenv("WATCH_NAMESPACE")
            unhealthy_pods = await run_in_threadpool(list_unhealthy_pods, watch_namespace)
            
            if not unhealthy_pods:
                logger.info("Cluster looks healthy, no unhealthy pods found.")
            else:
                db = SessionLocal()
                try:
                    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
                    
                    for pod in unhealthy_pods:
                        pod_name = pod["name"]
                        
                        # Check if we recently triaged this pod
                        recent_incident = db.query(Incident).filter(
                            Incident.pod_name == pod_name,
                            Incident.detected_at >= cutoff_time
                        ).first()
                        
                        if recent_incident:
                            logger.info(f"Skipping '{pod_name}' (recently triaged at {recent_incident.detected_at})")
                            continue
                            
                        logger.info(f"New unhealthy pod detected: '{pod_name}'. Triggering triage agent...")
                        
                        try:
                            # Run the triage agent loop using threadpool for non-blocking execution
                            result = await run_in_threadpool(triage_pod, pod)
                            
                            # Store incident and diagnosis
                            incident = Incident(
                                pod_name=pod_name,
                                namespace=pod["namespace"],
                                issues=json.dumps(pod["issues"]),
                            )
                            db.add(incident)
                            db.commit()
                            db.refresh(incident)

                            remediation_proposal = result.get("remediation_proposal")
                            action_status = result.get("action_status", "pending_approval")
                            
                            proposed_action_type = None
                            proposed_target = None
                            proposed_action_str = None
                            
                            if remediation_proposal:
                                proposed_action_str = json.dumps(remediation_proposal)
                                proposed_action_type = remediation_proposal.get("action")
                                proposed_target = remediation_proposal.get("target")

                            diagnosis = Diagnosis(
                                incident_id=incident.id,
                                diagnosis_text=result["diagnosis"],
                                tool_trace=json.dumps(result["tool_trace"]),
                                proposed_action=proposed_action_str,
                                proposed_action_type=proposed_action_type,
                                proposed_target=proposed_target,
                                action_status=action_status,
                            )
                            db.add(diagnosis)
                            db.commit()
                            db.refresh(diagnosis)
                            
                            diagnosis_id = diagnosis.id
                            
                            # Execute the remediation if proposed (rate limits apply inside)
                            from app.agent.remediation_executor import execute_remediation
                            execute_remediation(diagnosis_id)
                            
                            logger.info(f"Triage complete for '{pod_name}'. Diagnosis saved (Incident ID: {incident.id}).")
                            logger.info(f"Diagnosis Snippet: {result['diagnosis'][:150]}...")
                        except Exception as triage_err:
                            logger.error(f"Failed to triage pod '{pod_name}': {triage_err}", exc_info=True)
                            db.rollback()
                finally:
                    db.close()
                    
        except Exception as e:
            logger.error(f"Error in polling loop: {e}", exc_info=True)
            
        await asyncio.sleep(interval)
