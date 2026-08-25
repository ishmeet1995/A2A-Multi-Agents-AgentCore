"""
Tools for the Remediation Agent (local development).

retrieve_runbook() mirrors the Monitoring Agent's version — same local
markdown files, same eventual swap to bedrock-agent-runtime.retrieve().
Kept as its own copy (not a cross-import from the Monitoring Agent's
folder) because these are two independently deployable agents in the
real architecture — sharing code between them here would create a
coupling that doesn't exist once they're separate AgentCore deployments.

The three action functions below are mocked now. In the real architecture
these become AgentCore Gateway tool calls (Lambda functions fronted by the
Gateway, per the reference repo's pattern) rather than direct boto3 calls —
noted in each docstring.
"""

import os
import time
from pathlib import Path

_METRIC_TO_RUNBOOK: dict[str, str] = {
    "CPUUtilization": "cpu-utilization-high.md",
    "DiskSpaceUtilization": "disk-space-low.md",
    "Latency": "latency-elevated.md",
    "MemoryUtilization": "memory-utilization-high.md",
    "5xxErrorRate": "error-rate-5xx-elevated.md",
    "ApproximateAgeOfOldestMessage": "queue-backlog-high.md",
}

_DEFAULT_RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "runbooks"
_RUNBOOK_DIR = Path(os.environ.get("RUNBOOK_DIR", _DEFAULT_RUNBOOK_DIR))


def retrieve_runbook(metric: str) -> str:
    """Same local stand-in as the Monitoring Agent's tools.py — see there for full comments."""
    filename = _METRIC_TO_RUNBOOK.get(metric)
    if filename:
        path = _RUNBOOK_DIR / filename
        if path.exists():
            return path.read_text()

    if _RUNBOOK_DIR.exists():
        best_match, best_score = None, 0
        for md_file in _RUNBOOK_DIR.glob("*.md"):
            if md_file.name == "README.md":
                continue
            text = md_file.read_text()
            score = text.count(metric)
            if score > best_score:
                best_match, best_score = text, score
        if best_match:
            return best_match

    return "No runbook found for this metric. Escalate to human review."


def restart_instance(alarm_name: str) -> dict:
    """
    Mock remediation action: restart the affected instance/container.

    Real version: an AgentCore Gateway tool backed by a Lambda that calls
    ec2.reboot_instances() or ecs.update_service() with a forced new
    deployment, depending on the resource type in the alarm.
    """
    time.sleep(0.1)  # simulate the action taking a moment
    return {
        "action": "restart_instance",
        "target": alarm_name,
        "status": "completed",
        "detail": f"[MOCK] Restarted the resource associated with {alarm_name}",
    }


def scale_out(alarm_name: str) -> dict:
    """
    Mock remediation action: add capacity to the affected tier.

    Real version: an AgentCore Gateway tool backed by a Lambda that calls
    autoscaling.set_desired_capacity() or ecs.update_service() with an
    increased desired count.
    """
    time.sleep(0.1)
    return {
        "action": "scale_out",
        "target": alarm_name,
        "status": "completed",
        "detail": f"[MOCK] Increased capacity for the tier associated with {alarm_name}",
    }


def escalate_to_human(alarm_name: str, reason: str) -> dict:
    """
    Mock escalation: page/notify a human instead of auto-remediating.

    Real version: an AgentCore Gateway tool backed by a Lambda that posts
    to a paging system (PagerDuty/Opsgenie API, or an SNS topic feeding
    Slack) with the alarm and diagnosis attached.
    """
    time.sleep(0.1)
    return {
        "action": "escalate_to_human",
        "target": alarm_name,
        "status": "escalated",
        "detail": f"[MOCK] Paged on-call for {alarm_name}. Reason: {reason}",
    }
