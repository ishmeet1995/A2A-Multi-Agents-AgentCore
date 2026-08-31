"""
Sync A2A client for calling the Remediation Agent from the Monitoring Agent's
AgentCore Runtime entrypoint (which is invoked synchronously, unlike the
local monitoring_agent_langgraph/agent.py which wraps an async client in
asyncio.run() itself).

Two paths, chosen by REMEDIATION_AGENT_RUNTIME_ARN:
  - Set: the Remediation Agent is itself deployed to AgentCore Runtime as an
    A2A-protocol runtime. We send it the same JSON-RPC 2.0 "message/send"
    envelope the a2a-sdk sends over HTTP, but routed through boto3's
    invoke_agent_runtime() instead of a direct POST.
  - Not set (local dev): fall back to the same async a2a-sdk client used by
    monitoring_agent_langgraph/a2a_client.py, against a local A2A server,
    wrapped in asyncio.run().
"""

import json
import logging
import os
from uuid import uuid4

logger = logging.getLogger("monitoring_agent.a2a_client_sync")

LOCAL_REMEDIATION_AGENT_URL = "http://localhost:9000"


def _build_a2a_payload(alarm_name: str, metric: str, diagnosis: str) -> dict:
    message_text = json.dumps({"alarm_name": alarm_name, "metric": metric, "diagnosis": diagnosis})
    return {
        "jsonrpc": "2.0",
        "method": "message/send",
        "id": str(uuid4()),
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message_text}],
                "messageId": uuid4().hex,
            }
        },
    }


def _extract_text(result_dict: dict) -> str:
    """
    A2A can return either shape: a Task result (text nested under
    result.artifacts[0].parts[...] — what the Remediation Agent actually
    returns) or a plain Message result (text directly under result.parts[...]).
    Try the Task shape first, fall back to the Message shape, only raise if
    neither matches.
    """
    result = result_dict.get("result", {})

    artifacts = result.get("artifacts")
    if artifacts:
        try:
            parts = artifacts[0]["parts"]
            return next(p["text"] for p in parts if p.get("kind") == "text")
        except (KeyError, IndexError, StopIteration):
            pass

    try:
        parts = result["parts"]
        return next(p["text"] for p in parts if p.get("kind") == "text")
    except (KeyError, StopIteration) as e:
        raise RuntimeError(f"Unexpected A2A response shape: {result_dict}") from e


def _delegate_via_runtime(alarm_name: str, metric: str, diagnosis: str, runtime_arn: str) -> str:
    import boto3

    client = boto3.client("bedrock-agentcore")
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=str(uuid4()),
        payload=json.dumps(_build_a2a_payload(alarm_name, metric, diagnosis)).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    raw = response["response"].read().decode("utf-8")
    logger.info("delegate_via_runtime: raw response: %s", raw)

    try:
        result_dict = json.loads(raw)
    except json.JSONDecodeError:
        # ponytail: naive SSE fallback, only handles the last "data: " line.
        # The Remediation Agent advertises capabilities.streaming=False so
        # plain JSON is the expected case above; upgrade this if a
        # streaming A2A agent is ever put behind this client.
        lines = [line[len("data: "):] for line in raw.splitlines() if line.startswith("data: ")]
        if not lines:
            raise RuntimeError(f"Could not parse A2A runtime response: {raw}")
        result_dict = json.loads(lines[-1])

    return _extract_text(result_dict)


async def _delegate_via_local_http(alarm_name: str, metric: str, diagnosis: str) -> str:
    import httpx
    from a2a.client import A2ACardResolver, A2AClient
    from a2a.types import MessageSendParams, SendMessageRequest

    payload = json.dumps({"alarm_name": alarm_name, "metric": metric, "diagnosis": diagnosis})

    async with httpx.AsyncClient(timeout=120.0) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=LOCAL_REMEDIATION_AGENT_URL)
        agent_card = await resolver.get_agent_card()
        logger.info("Discovered agent: %s (%s)", agent_card.name, agent_card.description)

        client = A2AClient(httpx_client=httpx_client, agent_card=agent_card)
        request = SendMessageRequest(
            id=str(uuid4()),
            params=MessageSendParams(
                message={
                    "role": "user",
                    "parts": [{"kind": "text", "text": payload}],
                    "messageId": uuid4().hex,
                }
            ),
        )
        response = await client.send_message(request)
        result_dict = response.model_dump(mode="json", exclude_none=True)
        logger.info("Raw A2A response: %s", result_dict)
        return _extract_text(result_dict)


def delegate_to_remediation_agent_sync(alarm_name: str, metric: str, diagnosis: str) -> str:
    """Sync entrypoint used by main.py's delegate_to_remediation node."""
    runtime_arn = os.environ.get("REMEDIATION_AGENT_RUNTIME_ARN")
    if runtime_arn:
        logger.info("delegate_to_remediation_agent_sync: using AgentCore Runtime ARN %s", runtime_arn)
        return _delegate_via_runtime(alarm_name, metric, diagnosis, runtime_arn)

    logger.info(
        "delegate_to_remediation_agent_sync: REMEDIATION_AGENT_RUNTIME_ARN not set, "
        "using local A2A server at %s",
        LOCAL_REMEDIATION_AGENT_URL,
    )
    import asyncio

    return asyncio.run(_delegate_via_local_http(alarm_name, metric, diagnosis))
