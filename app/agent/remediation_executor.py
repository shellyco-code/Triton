import json
import logging
from datetime import datetime, timedelta, timezone
from app.db.models import Diagnosis, SessionLocal
from app.k8s.client import delete_pod

logger = logging.getLogger(__name__)

MAX_RESTARTS_PER_30_MIN = 2

def execute_remediation(diagnosis_id: int):
    """
    Evaluates and potentially executes a remediation proposal safely.
    Checks the rate limit before executing automated actions.
    """
    db = SessionLocal()
    try:
        diag = db.query(Diagnosis).filter(Diagnosis.id == diagnosis_id).first()
        if not diag:
            return
            
        if diag.action_status == "parse_error":
            logger.warning(f"Diagnosis {diagnosis_id} had a parse_error. Skipping remediation.")
            return

        if diag.action_status in ("executed", "skipped_by_safety"):
            logger.info(f"Diagnosis {diagnosis_id} has already been processed (status: {diag.action_status}).")
            return

        action = diag.proposed_action_type
        target = diag.proposed_target

        if not action or not target:
            # Fallback to json parsing if columns are empty (e.g. older entries before migration)
            if diag.proposed_action:
                try:
                    proposal = json.loads(diag.proposed_action)
                    action = proposal.get("action")
                    target = proposal.get("target")
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in proposed_action for Diagnosis {diagnosis_id}")
                    diag.action_status = "failed"
                    db.commit()
                    return
            else:
                diag.action_status = "failed"
                db.commit()
                logger.error(f"Diagnosis {diagnosis_id}: 'action' or 'target' missing from proposal.")
                return

        # We only automate restart_pod for the MVP
        if action != "restart_pod":
            diag.action_status = "pending_approval"
            db.commit()
            logger.info(f"Diagnosis {diagnosis_id}: Action '{action}' requires manual approval.")
            return

        if not target:
            diag.action_status = "failed"
            db.commit()
            logger.error(f"Diagnosis {diagnosis_id}: 'target' missing from proposal.")
            return

        # --- SAFETY CHECK: Rate Limiter ---
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        
        # Count how many times this specific target was restarted recently
        recent_restarts = db.query(Diagnosis).filter(
            Diagnosis.id != diagnosis_id,
            Diagnosis.created_at >= cutoff_time,
            Diagnosis.action_status == "executed",
            Diagnosis.proposed_target == target,
            Diagnosis.proposed_action_type == "restart_pod"
        ).count()

        if recent_restarts >= MAX_RESTARTS_PER_30_MIN:
            diag.action_status = "skipped_by_safety"
            db.commit()
            logger.warning(f"Safety Triggered: Pod '{target}' has been restarted {recent_restarts} times in 30m. Skipping.")
            return

        # --- SAFETY CHECK: System Namespaces ---
        target_namespace = diag.incident.namespace if diag.incident else "default"
        SYSTEM_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}
        if target_namespace in SYSTEM_NAMESPACES:
            diag.action_status = "skipped_by_safety"
            db.commit()
            logger.warning(f"Safety Triggered: Pod '{target}' is in system namespace '{target_namespace}'. Skipping.")
            return

        # --- EXECUTION ---
        logger.info(f"Executing restart_pod for '{target}' in namespace '{target_namespace}'...")
        success = delete_pod(pod_name=target, namespace=target_namespace)

        if success:
            diag.action_status = "executed"
            diag.executed_at = datetime.now(timezone.utc)
            logger.info(f"Successfully restarted pod '{target}'.")
        else:
            diag.action_status = "failed"
            logger.error(f"Failed to execute restart_pod for '{target}'.")

        db.commit()
    finally:
        db.close()
