"""
A2A client for calling the Remediation Agent from the Monitoring Agent.

This replaces the stub in agent.py's delegate_to_remediation node with a
real network call: discover the Remediation Agent's Agent Card, then send
it a message over JSON-RPC and read back its decision.
"""

import json
import logging
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import MessageSendParams, SendMessageRequest

logger = logging.getLogger("monitoring_agent.a2a_client")

REMEDIATION_AGENT_URL = "http://localhost:9001"


async def delegate_to_remediation_agent(alarm_name: str, metric: str, diagnosis: str) -> str:
    """
    Sends a remediation request to the Remediation Agent over A2A and
    returns its text response (e.g. "[REMEDIATED] ..." or "[ESCALATED] ...").

    Raises on connection failure — the caller decides how to handle a
    Remediation Agent that's unreachable (e.g. fall back to escalation).
    """
    payload = json.dumps({"alarm_name": alarm_name, "metric": metric, "diagnosis": diagnosis})

    async with httpx.AsyncClient(timeout=120.0) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=REMEDIATION_AGENT_URL)
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

        # Extract the text part from the agent's reply message
        try:
            parts = result_dict["result"]["parts"]
            text = next(p["text"] for p in parts if p.get("kind") == "text")
            return text
        except (KeyError, StopIteration) as e:
            raise RuntimeError(f"Unexpected A2A response shape: {result_dict}") from e
