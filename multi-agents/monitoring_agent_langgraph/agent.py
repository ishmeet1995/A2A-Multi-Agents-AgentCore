"""
Monitoring Agent — LangGraph implementation.

Mirrors the role of multi-agents/monitoring_agent/monitoring_agent.py in the
reference repo (madhurprash/A2A-Multi-Agents-AgentCore), but built with
LangGraph instead of Strands, so it plugs into the same overall
Monitoring -> A2A -> Remediation architecture with a different framework.

Graph shape:

    START -> fetch_alarm -> retrieve_runbook -> diagnose -> route
                                                              |
                                    +-------------------------+-------------------------+
                                    |                                                   |
                            (needs_remediation)                                  (informational)
                                    v                                                   v
                          delegate_to_remediation                              respond_informational
                                    |                                                   |
                                    v                                                   v
                                   END                                                 END

`delegate_to_remediation` is currently a stub that will become a real A2A
JSON-RPC call to the Remediation Agent's Agent Card once that agent exists
(Step 5/6). Swapping it later does not require changing the graph shape.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal, TypedDict

from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from tools import get_cloudwatch_alarm_details, retrieve_runbook, AlarmDetails
from a2a_client import delegate_to_remediation_agent

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("monitoring_agent")


class AgentState(TypedDict):
    alarm_name: str
    alarm_details: AlarmDetails
    runbook: str
    diagnosis: str
    needs_remediation: bool
    final_response: str


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def fetch_alarm(state: AgentState) -> dict:
    """Node: pull the alarm details. Mocked CloudWatch call for now."""
    logger.info("fetch_alarm: %s", state["alarm_name"])
    details = get_cloudwatch_alarm_details(state["alarm_name"])
    logger.info("fetch_alarm: done")
    return {"alarm_details": details}


def retrieve_runbook_node(state: AgentState) -> dict:
    """Node: pull the relevant runbook. Mocked Bedrock KB call for now."""
    logger.info("retrieve_runbook: %s", state["alarm_details"]["metric"])
    runbook = retrieve_runbook(state["alarm_details"]["metric"])
    logger.info("retrieve_runbook: done")
    return {"runbook": runbook}


def diagnose(state: AgentState, llm) -> dict:
    """Node: ask the model to diagnose the alarm using the runbook as grounding."""
    logger.info("diagnose: building prompt")
    alarm = state["alarm_details"]
    prompt = (
        f"Alarm: {alarm['alarm_name']}\n"
        f"Metric: {alarm['metric']} = {alarm['current_value']} "
        f"(threshold {alarm['threshold']}, state {alarm['state']})\n\n"
        f"Relevant runbook:\n{state['runbook']}\n\n"
        "Based on the runbook, diagnose this alarm in 2-3 sentences. "
        "Then, on a new line, write exactly one of:\n"
        "REMEDIATION_NEEDED: <one line reason>\n"
        "or\n"
        "INFORMATIONAL_ONLY: <one line reason>"
    )
    logger.info("diagnose: calling llm.invoke (network call, may hang here)")
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a cloud ops monitoring agent. You diagnose CloudWatch "
                    "alarms strictly according to the runbook you're given. You never "
                    "invent remediation steps that aren't in the runbook."
                )
            ),
            HumanMessage(content=prompt),
        ]
    )
    logger.info("diagnose: llm.invoke returned")
    text = response.content
    needs_remediation = "REMEDIATION_NEEDED" in text
    logger.info("diagnose: needs_remediation=%s", needs_remediation)
    return {"diagnosis": text, "needs_remediation": needs_remediation}


def route_after_diagnosis(state: AgentState) -> Literal["remediate", "inform"]:
    """Conditional edge: decide which branch to take after diagnosis."""
    return "remediate" if state["needs_remediation"] else "inform"


def delegate_to_remediation(state: AgentState) -> dict:
    """
    Node: hand off to the Remediation Agent over a real A2A call.

    Requires the Remediation Agent's a2a_server.py to be running at
    http://localhost:9001 (see remediation_agent/a2a_server.py). If it's
    unreachable, that's a real failure — not a graph bug — so it surfaces
    clearly rather than silently falling back to a stub.
    """
    alarm = state["alarm_details"]
    logger.info("delegate_to_remediation: calling Remediation Agent via A2A for %s", alarm["alarm_name"])
    try:
        response_text = asyncio.run(
            delegate_to_remediation_agent(
                alarm_name=alarm["alarm_name"],
                metric=alarm["metric"],
                diagnosis=state["diagnosis"],
            )
        )
    except Exception as e:
        logger.error("delegate_to_remediation: A2A call failed: %s", e)
        response_text = f"[A2A CALL FAILED] Could not reach Remediation Agent: {e}"
    logger.info("delegate_to_remediation: received: %s", response_text)
    return {"final_response": response_text}


def respond_informational(state: AgentState) -> dict:
    """Node: no remediation needed, just surface the diagnosis."""
    logger.info("respond_informational: done")
    return {"final_response": f"[INFORMATIONAL] {state['diagnosis']}"}


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(llm):
    """Build and compile the monitoring agent graph, bound to a given LLM."""
    graph = StateGraph(AgentState)

    graph.add_node("fetch_alarm", fetch_alarm)
    graph.add_node("retrieve_runbook", retrieve_runbook_node)
    graph.add_node("diagnose", lambda state: diagnose(state, llm))
    graph.add_node("delegate_to_remediation", delegate_to_remediation)
    graph.add_node("respond_informational", respond_informational)

    graph.add_edge(START, "fetch_alarm")
    graph.add_edge("fetch_alarm", "retrieve_runbook")
    graph.add_edge("retrieve_runbook", "diagnose")
    graph.add_conditional_edges(
        "diagnose",
        route_after_diagnosis,
        {"remediate": "delegate_to_remediation", "inform": "respond_informational"},
    )
    graph.add_edge("delegate_to_remediation", END)
    graph.add_edge("respond_informational", END)

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

    alarm_name = sys.argv[1] if len(sys.argv) > 1 else "high-cpu-web-01"

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY to run against the real model.")
        print("Running structural test instead (see test_local.py).")
        sys.exit(1)

    app = build_graph(get_llm())
    result = app.invoke({"alarm_name": alarm_name})
    print("\n--- FINAL RESPONSE ---")
    print(result["final_response"])
