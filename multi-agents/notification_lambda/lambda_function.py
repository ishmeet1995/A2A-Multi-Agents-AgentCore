"""
Lambda: send_escalation_notification

This is the actual tool the Harness-based Notification Agent calls. It's a
real, deployable Lambda (no Bedrock dependency at all — pure AWS), so it
can be built and tested right now regardless of the InvokeModel block.

Input (from the Harness tool call):
    {"alarm_name": str, "reason": str, "severity": "critical" | "warning"}

Output:
    {"status": "sent", "channel": str, "detail": str}

Currently mocked (logs + returns success) rather than actually posting to
PagerDuty/Slack/SNS — same mocking convention as the rest of the project.
Swap the body for a real SNS publish or PagerDuty API call when ready;
the input/output contract stays the same.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info("Received escalation request: %s", json.dumps(event))

    alarm_name = event.get("alarm_name", "unknown-alarm")
    reason = event.get("reason", "no reason provided")
    severity = event.get("severity", "warning")

    # MOCK — replace with a real notification call, e.g.:
    #   boto3.client("sns").publish(TopicArn=..., Message=formatted_message)
    # or a PagerDuty/Opsgenie Events API POST.
    channel = "mock-pagerduty" if severity == "critical" else "mock-slack"
    detail = f"[{severity.upper()}] {alarm_name}: {reason}"
    logger.info("Would send to %s: %s", channel, detail)

    return {
        "status": "sent",
        "channel": channel,
        "detail": detail,
    }
