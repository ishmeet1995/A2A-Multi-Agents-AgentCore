"""
Tools for local development.

get_cloudwatch_alarm_details() is still fully mocked -> will become a real
boto3 cloudwatch.describe_alarms() call once the AWS account is verified.

retrieve_runbook() now has two paths, chosen by the KNOWLEDGE_BASE_ID env var:
  - Set: real bedrock-agent-runtime.retrieve() call against that Knowledge
    Base (_retrieve_from_bedrock_kb) -> the actual production path.
  - Not set (local dev): read the runbook .md files off local disk
    (_retrieve_runbook_local), same as before the KB existed.
"""

import os
from pathlib import Path
from typing import TypedDict


class AlarmDetails(TypedDict):
    alarm_name: str
    metric: str
    current_value: float
    threshold: float
    state: str


# Fake CloudWatch alarms, keyed by name, so we can test multiple scenarios
_MOCK_ALARMS: dict[str, AlarmDetails] = {
    "high-cpu-web-01": {
        "alarm_name": "high-cpu-web-01",
        "metric": "CPUUtilization",
        "current_value": 91.4,
        "threshold": 80.0,
        "state": "ALARM",
    },
    "disk-space-low-db-02": {
        "alarm_name": "disk-space-low-db-02",
        "metric": "DiskSpaceUtilization",
        "current_value": 95.2,
        "threshold": 90.0,
        "state": "ALARM",
    },
    "elevated-latency-api-gw": {
        "alarm_name": "elevated-latency-api-gw",
        "metric": "Latency",
        "current_value": 420.0,
        "threshold": 500.0,
        "state": "OK",
    },
    "high-memory-worker-03": {
        "alarm_name": "high-memory-worker-03",
        "metric": "MemoryUtilization",
        "current_value": 89.0,
        "threshold": 85.0,
        "state": "ALARM",
    },
    "elevated-5xx-checkout-api": {
        "alarm_name": "elevated-5xx-checkout-api",
        "metric": "5xxErrorRate",
        "current_value": 3.2,
        "threshold": 1.0,
        "state": "ALARM",
    },
    "queue-backlog-orders": {
        "alarm_name": "queue-backlog-orders",
        "metric": "ApproximateAgeOfOldestMessage",
        "current_value": 2400.0,  # seconds = 40 min
        "threshold": 900.0,       # 15 min
        "state": "ALARM",
    },
}

# Maps a CloudWatch metric name to its runbook filename. This mirrors what
# you'd otherwise get "for free" from Bedrock KB's semantic retrieval — an
# explicit map is the honest local substitute, plus a fallback keyword scan
# below for anything not in the map.
_METRIC_TO_RUNBOOK: dict[str, str] = {
    "CPUUtilization": "cpu-utilization-high.md",
    "DiskSpaceUtilization": "disk-space-low.md",
    "Latency": "latency-elevated.md",
    "MemoryUtilization": "memory-utilization-high.md",
    "5xxErrorRate": "error-rate-5xx-elevated.md",
    "ApproximateAgeOfOldestMessage": "queue-backlog-high.md",
}

# Where the real runbook .md files live locally. Override with the
# RUNBOOK_DIR env var if your checkout layout differs from the default
# (sibling "knowledge_base/runbooks" folder two levels up from this file —
# i.e. multi-agents/knowledge_base/runbooks relative to
# multi-agents/monitoring_agent_langgraph/tools.py).
_DEFAULT_RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "knowledge_base" / "runbooks"
_RUNBOOK_DIR = Path(os.environ.get("RUNBOOK_DIR", _DEFAULT_RUNBOOK_DIR))

# Real Bedrock Knowledge Base backing the runbooks in production/deployed
# environments. When unset, retrieve_runbook() falls back to local files.
KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID")


def get_cloudwatch_alarm_details(alarm_name: str) -> AlarmDetails:
    """Mock of cloudwatch.describe_alarms() for a single alarm."""
    if alarm_name not in _MOCK_ALARMS:
        raise ValueError(f"Unknown mock alarm: {alarm_name}")
    return _MOCK_ALARMS[alarm_name]


def _retrieve_from_bedrock_kb(metric: str) -> str:
    """Real retrieval via bedrock-agent-runtime.retrieve() against the KB."""
    import boto3

    client = boto3.client(
        "bedrock-agent-runtime",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
    response = client.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": f"runbook for {metric} alarm"},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}},
    )
    results = response.get("retrievalResults", [])
    texts = [r["content"]["text"] for r in results if r.get("content", {}).get("text")]
    if not texts:
        return "No runbook found for this metric. Escalate to human review."
    return "\n\n---\n\n".join(texts)


def _retrieve_runbook_local(metric: str) -> str:
    """
    Local stand-in for bedrock-agent-runtime.retrieve() against the KB.

    1. Exact metric match against the known runbook map (fast path, mirrors
       what a well-tuned KB query should return as its top hit).
    2. Fallback: scan every .md file in the runbook dir and return whichever
       one mentions the metric name the most — a crude approximation of
       semantic retrieval for metrics not in the explicit map.
    """
    filename = _METRIC_TO_RUNBOOK.get(metric)
    if filename:
        path = _RUNBOOK_DIR / filename
        if path.exists():
            return path.read_text()

    # Fallback: keyword scan across all available runbooks
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


def retrieve_runbook(metric: str) -> str:
    """Dispatch to the real Bedrock KB if configured, else local files."""
    if KNOWLEDGE_BASE_ID:
        return _retrieve_from_bedrock_kb(metric)
    return _retrieve_runbook_local(metric)
