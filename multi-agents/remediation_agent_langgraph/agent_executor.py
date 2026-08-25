"""
Adapts the LangGraph Remediation Agent to the A2A protocol.

Protocol contract for this agent (documented here since A2A doesn't
enforce a payload schema beyond text parts — this is our own convention,
and the Monitoring Agent's client code must match it):

  Incoming message text: a JSON string with keys
    {"alarm_name": str, "metric": str, "diagnosis": str}

  Reply message text: the graph's final_response string, e.g.
    "[REMEDIATED] ..." or "[ESCALATED] ..."

A real production version would likely use structured A2A message parts
(DataPart) instead of a JSON-encoded TextPart, but TextPart + JSON keeps
this readable for a learning project and is still valid A2A.
"""

import json
import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from agent import build_graph, get_llm

logger = logging.getLogger("remediation_agent.a2a_executor")


class RemediationAgentExecutor(AgentExecutor):
    """A2A entrypoint for the LangGraph Remediation Agent."""

    def __init__(self):
        # Build once, reuse across requests — the compiled graph is stateless
        # between invocations (all state flows through the invoke() call).
        self._llm = get_llm()
        self._graph = build_graph(self._llm)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        raw_input = context.get_user_input()
        logger.info("execute: received raw input: %s", raw_input)

        try:
            payload = json.loads(raw_input)
            alarm_name = payload["alarm_name"]
            metric = payload["metric"]
            diagnosis = payload["diagnosis"]
        except (json.JSONDecodeError, KeyError) as e:
            error_msg = f"[ERROR] Malformed remediation request: {e}. Expected JSON with alarm_name, metric, diagnosis."
            logger.error(error_msg)
            await event_queue.enqueue_event(new_agent_text_message(error_msg))
            return

        # The LangGraph .invoke() call is sync; run it directly since we're
        # already in an async context managed by the A2A server/uvicorn.
        result = self._graph.invoke(
            {"alarm_name": alarm_name, "metric": metric, "diagnosis": diagnosis}
        )
        logger.info("execute: graph result: %s", result["final_response"])

        await event_queue.enqueue_event(new_agent_text_message(result["final_response"]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # No long-running/cancelable work in this agent — each request completes
        # synchronously within execute(). Nothing to do here for this project.
        raise NotImplementedError("Cancellation is not supported by the Remediation Agent.")
