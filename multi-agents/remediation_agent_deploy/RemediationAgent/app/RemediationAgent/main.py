import json
import logging
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part
from bedrock_agentcore.runtime import serve_a2a
from model.load import load_model
from tools import escalate_to_human, restart_instance, retrieve_runbook, scale_out

LangchainInstrumentor().instrument()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediation_agent")

VALID_ACTIONS = {"RESTART_INSTANCE", "SCALE_OUT", "ESCALATE_HUMAN"}


class RemediationState(TypedDict):
    alarm_name: str
    metric: str
    diagnosis: str
    runbook: str
    decided_action: str
    decision_reasoning: str
    final_response: str


# ---------------------------------------------------------------------------
# Nodes — ported from remediation_agent_langgraph/agent.py. Same graph shape:
#
#   START -> retrieve_runbook -> decide_action -> route
#                                                    |
#                       +----------------------------+----------------------------+
#                       |                            |                            |
#               (RESTART_INSTANCE)             (SCALE_OUT)                (ESCALATE_HUMAN)
#                       v                            v                            v
#               execute_restart              execute_scale_out            execute_escalation
#                       |                            |                            |
#                       +----------------------------+----------------------------+
#                                                      v
#                                                     END
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


model = load_model()
graph = build_graph(model)


class LangGraphA2AExecutor(AgentExecutor):
    """Wraps a LangGraph CompiledGraph as an a2a-sdk AgentExecutor."""

    def __init__(self, graph):
        self.graph = graph

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # user_text is a JSON string {"alarm_name", "metric", "diagnosis"} sent by the
        # Monitoring Agent's delegate_to_remediation node, not a chat message.
        user_text = context.get_user_input()
        initial_state = json.loads(user_text)
        result = await self.graph.ainvoke(initial_state)
        response = result["final_response"]

        await updater.add_artifact([Part(text=response)])
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


card = AgentCard(
    name="Remediation Agent",
    description="Decides and executes remediation actions for diagnosed CloudWatch alarms, strictly per the relevant runbook",
    version="0.1.0",
    capabilities=AgentCapabilities(streaming=True),
    skills=[
        AgentSkill(
            id="remediate_alarm",
            name="remediate_alarm",
            description="Decide and execute a remediation action for a diagnosed CloudWatch alarm",
            tags=["remediation"],
        )
    ],
    default_input_modes=["text"],
    default_output_modes=["text"],
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            protocol_version="1.0",
            url="http://localhost:9000/",
        )
    ],
)

if __name__ == "__main__":
    serve_a2a(LangGraphA2AExecutor(graph), card)
