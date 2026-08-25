"""
Remediation Agent — LangGraph implementation.

Receives a diagnosis handed off by the Monitoring Agent (currently via the
stub in monitoring_agent_langgraph/agent.py's delegate_to_remediation node;
will become a real A2A JSON-RPC call in Step 6) and decides what to do
about it, constrained to the actions each runbook actually authorizes.

Graph shape:

    START -> retrieve_runbook -> decide_action -> route
                                                     |
                        +----------------------------+----------------------------+
                        |                            |                            |
                (RESTART_INSTANCE)             (SCALE_OUT)                (ESCALATE_HUMAN)
                        v                            v                            v
                execute_restart              execute_scale_out            execute_escalation
                        |                            |                            |
                        +----------------------------+----------------------------+
                                                       v
                                                      END

The model is deliberately constrained to choose from exactly three actions
(not free-form), because letting an LLM invent its own remediation action
outside what the runbook authorizes is the failure mode this whole
project's design is trying to avoid.
"""

from __future__ import annotations

import logging
import os
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from tools import retrieve_runbook, restart_instance, scale_out, escalate_to_human

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediation_agent")

VALID_ACTIONS = {"RESTART_INSTANCE", "SCALE_OUT", "ESCALATE_HUMAN"}


class RemediationState(TypedDict):
    alarm_name: str
    metric: str
    diagnosis: str  # the reasoning handed off by the Monitoring Agent
    runbook: str
    decided_action: str
    decision_reasoning: str
    final_response: str


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def retrieve_runbook_node(state: RemediationState) -> dict:
    logger.info("retrieve_runbook: %s", state["metric"])
    runbook = retrieve_runbook(state["metric"])
    return {"runbook": runbook}


def decide_action(state: RemediationState, llm) -> dict:
    """Ask the model to pick exactly one of the three authorized actions."""
    prompt = (
        f"An upstream monitoring agent diagnosed this alarm:\n"
        f"Alarm: {state['alarm_name']} (metric: {state['metric']})\n"
        f"Diagnosis: {state['diagnosis']}\n\n"
        f"Runbook for this metric:\n{state['runbook']}\n\n"
        "Based STRICTLY on what the runbook authorizes, choose exactly one action:\n"
        "RESTART_INSTANCE, SCALE_OUT, or ESCALATE_HUMAN.\n"
        "If the runbook says this alarm class should always be escalated, or if "
        "you're not confident the situation matches an auto-approved case in the "
        "runbook, choose ESCALATE_HUMAN — do not guess.\n\n"
        "Respond in exactly this format:\n"
        "ACTION: <one of the three>\n"
        "REASONING: <one sentence, grounded in the runbook>"
    )
    logger.info("decide_action: calling llm.invoke")
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a cloud ops remediation agent. You only take actions "
                    "explicitly authorized by the runbook you're given. When in doubt, "
                    "you escalate to a human rather than guess."
                )
            ),
            HumanMessage(content=prompt),
        ]
    )
    text = response.content
    logger.info("decide_action: llm.invoke returned")

    action = "ESCALATE_HUMAN"  # safe default if parsing fails
    reasoning = text
    for line in text.splitlines():
        if line.strip().startswith("ACTION:"):
            candidate = line.split(":", 1)[1].strip()
            if candidate in VALID_ACTIONS:
                action = candidate
        if line.strip().startswith("REASONING:"):
            reasoning = line.split(":", 1)[1].strip()

    logger.info("decide_action: parsed action=%s reasoning=%s", action, reasoning)
    return {"decided_action": action, "decision_reasoning": reasoning}


def route_action(state: RemediationState) -> Literal["restart", "scale", "escalate"]:
    logger.info("route_action: %s", state["decided_action"])
    return {
        "RESTART_INSTANCE": "restart",
        "SCALE_OUT": "scale",
        "ESCALATE_HUMAN": "escalate",
    }[state["decided_action"]]


def execute_restart(state: RemediationState) -> dict:
    logger.info("execute_restart: %s", state["alarm_name"])
    result = restart_instance(state["alarm_name"])
    logger.info("execute_restart: done")
    return {"final_response": f"[REMEDIATED] {result['detail']} — reasoning: {state['decision_reasoning']}"}


def execute_scale_out(state: RemediationState) -> dict:
    logger.info("execute_scale_out: %s", state["alarm_name"])
    result = scale_out(state["alarm_name"])
    logger.info("execute_scale_out: done")
    return {"final_response": f"[REMEDIATED] {result['detail']} — reasoning: {state['decision_reasoning']}"}


def execute_escalation(state: RemediationState) -> dict:
    logger.info("execute_escalation: %s", state["alarm_name"])
    result = escalate_to_human(state["alarm_name"], state["decision_reasoning"])
    logger.info("execute_escalation: done")
    return {"final_response": f"[ESCALATED] {result['detail']}"}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(llm):
    graph = StateGraph(RemediationState)

    graph.add_node("retrieve_runbook", retrieve_runbook_node)
    graph.add_node("decide_action", lambda state: decide_action(state, llm))
    graph.add_node("execute_restart", execute_restart)
    graph.add_node("execute_scale_out", execute_scale_out)
    graph.add_node("execute_escalation", execute_escalation)

    graph.add_edge(START, "retrieve_runbook")
    graph.add_edge("retrieve_runbook", "decide_action")
    graph.add_conditional_edges(
        "decide_action",
        route_action,
        {
            "restart": "execute_restart",
            "scale": "execute_scale_out",
            "escalate": "execute_escalation",
        },
    )
    graph.add_edge("execute_restart", END)
    graph.add_edge("execute_scale_out", END)
    graph.add_edge("execute_escalation", END)

    return graph.compile()


_ipv4_patched = False


def _force_ipv4_dns():
    """
    Patch socket.getaddrinfo process-wide to only return IPv4 addresses.

    Without this, httpx (which the Anthropic SDK uses under the hood) can
    spend 20-100+ seconds per call falling back from a broken/blackholed
    IPv6 route before trying IPv4 — httpx doesn't implement Happy Eyeballs
    (RFC 6555) the way curl does, so it tries addresses sequentially instead
    of racing them.

    This used to be done by passing http_client/http_async_client into
    ChatAnthropic, but that's not a real constructor field on this version
    of langchain-anthropic (0.125.0) — pydantic silently dropped it into
    model_kwargs, which then got forwarded straight into the Anthropic SDK's
    Messages.create() call and raised TypeError. Patching the resolver
    itself works regardless of which HTTP client library is underneath.
    """
    global _ipv4_patched
    if _ipv4_patched:
        return
    import socket

    _orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = _ipv4_only_getaddrinfo
    _ipv4_patched = True


def get_llm():
    """Real model call — needs ANTHROPIC_API_KEY set locally."""
    from langchain_anthropic import ChatAnthropic

    _force_ipv4_dns()
    return ChatAnthropic(model="claude-sonnet-4-6", temperature=0, timeout=30)


if __name__ == "__main__":
    import sys

    # Simple manual test inputs — normally this comes from the Monitoring Agent via A2A
    test_cases = {
        "high-cpu-web-01": ("CPUUtilization", "CPU sustained above 80% threshold, single runaway process, traffic normal"),
        "disk-space-low-db-02": ("DiskSpaceUtilization", "Disk usage above 90% on db instance"),
        "queue-backlog-orders": ("ApproximateAgeOfOldestMessage", "Consumers stalled, no recent deploy correlation"),
    }
    alarm_name = sys.argv[1] if len(sys.argv) > 1 else "high-cpu-web-01"
    metric, diagnosis = test_cases.get(alarm_name, ("CPUUtilization", "Generic test diagnosis"))

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run against the real model.")
        print("Running structural test instead (see test_local.py).")
        sys.exit(1)

    app = build_graph(get_llm())
    result = app.invoke({"alarm_name": alarm_name, "metric": metric, "diagnosis": diagnosis})
    print("\n--- FINAL RESPONSE ---")
    print(result["final_response"])
