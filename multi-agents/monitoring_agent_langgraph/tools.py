"""
Tools for the Remediation Agent.

retrieve_runbook() calls the real Bedrock Knowledge Base via
bedrock-agent-runtime.retrieve(), with a fallback to local markdown files
if the KB is unreachable — same pattern as the Monitoring Agent's tools.py.
Kept as its own copy (not a cross-import from the Monitoring Agent's
folder) because these are two independently deployable agents in the
real architecture — sharing code between them here would create a
coupling that doesn't exist once they're separate AgentCore deployments.

The three action functions below are mocked (restart/scale) or call the
real Harness (escalate). In the real architecture restart/scale become
AgentCore Gateway tool calls (Lambda functions fronted by the Gateway,
per the reference repo's pattern) rather than direct boto3 calls — noted
in each docstring.
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

# Where the real runbook .md files live locally — used only as a fallback
# if the Bedrock Knowledge Base is unreachable.
_DEFAULT_RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "runbooks"
_RUNBOOK_DIR = Path(os.environ.get("RUNBOOK_DIR", _DEFAULT_RUNBOOK_DIR))

# Real Bedrock Knowledge Base config
_KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID")
_KB_REGION = os.environ.get("AWS_REGION", "us-east-1")


def retrieve_runbook(metric: str) -> str:
    """
    Retrieves the runbook for a given metric from the real Bedrock
    Knowledge Base. Falls back to reading local files if KNOWLEDGE_BASE_ID
    isn't set or the call fails — keeps local dev/testing working without
    AWS configured.
    """
    if _KNOWLEDGE_BASE_ID:
        try:
            return _retrieve_from_bedrock_kb(metric)
        except Exception as e:
            print(f"[WARN] Bedrock KB retrieval failed ({e}), falling back to local files")

    return _retrieve_runbook_local(metric)


def _retrieve_from_bedrock_kb(metric: str) -> str:
    """Real call to bedrock-agent-runtime.retrieve() against the Knowledge Base."""
    import boto3

    client = boto3.client("bedrock-agent-runtime", region_name=_KB_REGION)

    query = f"What is the runbook for a {metric} alarm? Diagnosis steps, remediation decision, and escalation criteria."

    response = client.retrieve(
        knowledgeBaseId=_KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 2}},
    )

    results = response.get("retrievalResults", [])
    if not results:
        return "No runbook found for this metric. Escalate to human review."

    return results[0]["content"]["text"]


def _retrieve_runbook_local(metric: str) -> str:
    """Local stand-in for the KB — reads the markdown files directly off disk."""
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


def escalate_to_human(alarm_name: str, reason: str, severity: str = "warning") -> dict:
    """
    Escalation: calls the Harness-based Notification Agent to format and
    send the page. Falls back to a local mock if the harness isn't
    reachable (no AWS configured, invocation not yet authorized, harness
    not yet created) — so local dev and testing keep working either way.

    HARNESS_ARN env var must be set to actually invoke the real harness;
    see notification_lambda/README.md for how to create it.
    """
    harness_arn = os.environ.get("HARNESS_ARN")
    if not harness_arn:
        return _escalate_mock(alarm_name, reason, "no HARNESS_ARN configured")

    try:
        import boto3

        client = boto3.client("bedrock-agentcore", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        response = client.invoke_harness(
            harnessArn=harness_arn,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": (
                                f"Alarm: {alarm_name}\nReason: {reason}\nSeverity: {severity}\n"
                                "Format and send this escalation notification."
                            )
                        }
                    ],
                }
            ],
        )
        # InvokeHarness streams events; for a simple case, collect the final text.
        detail = _extract_harness_response_text(response)
        return {
            "action": "escalate_to_human",
            "target": alarm_name,
            "status": "escalated",
            "detail": detail or f"Harness invoked for {alarm_name}, no text response parsed",
        }
    except Exception as e:
        return _escalate_mock(alarm_name, reason, f"harness call failed: {e}")


def _escalate_mock(alarm_name: str, reason: str, fallback_note: str) -> dict:
    time.sleep(0.1)
    return {
        "action": "escalate_to_human",
        "target": alarm_name,
        "status": "escalated",
        "detail": f"[MOCK, {fallback_note}] Paged on-call for {alarm_name}. Reason: {reason}",
    }


def _extract_harness_response_text(response) -> str:
    """Best-effort extraction of text content from an InvokeHarness event stream."""
    try:
        chunks = []
        for event in response.get("stream", []):
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            if "text" in delta:
                chunks.append(delta["text"])
        return "".join(chunks)
    except Exception:
        return ""