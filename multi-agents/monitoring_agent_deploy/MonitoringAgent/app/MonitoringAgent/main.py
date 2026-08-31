import json
from typing import Literal, TypedDict

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from opentelemetry.instrumentation.langchain import LangchainInstrumentor

from a2a_client_sync import delegate_to_remediation_agent_sync
from model.load import load_model
from tools import AlarmDetails, get_cloudwatch_alarm_details, retrieve_runbook

LangchainInstrumentor().instrument()

app = BedrockAgentCoreApp()
log = app.logger

_llm = None


def get_or_create_model():
    global _llm
    if _llm is None:
        _llm = load_model()
    return _llm


class AgentState(TypedDict):
    alarm_name: str
    alarm_details: AlarmDetails
    runbook: str
    diagnosis: str
    needs_remediation: bool
    final_response: str


# ---------------------------------------------------------------------------
# Nodes — ported from monitoring_agent_langgraph/agent.py. Same graph shape:
#
#   START -> fetch_alarm -> retrieve_runbook -> diagnose -> route
#                                                             |
#                                   +-------------------------+-------------------------+
#                                   |                                                   |
#                           (needs_remediation)                                  (informational)
#                                   v                                                   v
#                         delegate_to_remediation                              respond_informational
#                                   |                                                   |
#                                   v                                                   v
#                                  END                                                 END
#
# delegate_to_remediation now calls a2a_client_sync.delegate_to_remediation_agent_sync()
# instead of the local asyncio.run(delegate_to_remediation_agent(...)) — that
# module picks between a real AgentCore Runtime call and a local A2A server.
# ---------------------------------------------------------------------------

def fetch_alarm(state: AgentState) -> dict:
    log.info("fetch_alarm: %s", state["alarm_name"])
    details = get_cloudwatch_alarm_details(state["alarm_name"])
    log.info("fetch_alarm: done")
    return {"alarm_details": details}


def retrieve_runbook_node(state: AgentState) -> dict:
    log.info("retrieve_runbook: %s", state["alarm_details"]["metric"])
    runbook = retrieve_runbook(state["alarm_details"]["metric"])
    log.info("retrieve_runbook: done")
    return {"runbook": runbook}


def diagnose(state: AgentState, llm) -> dict:
    log.info("diagnose: building prompt")
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
    log.info("diagnose: calling llm.invoke (network call, may hang here)")
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
    log.info("diagnose: llm.invoke returned")
    text = response.content
    needs_remediation = "REMEDIATION_NEEDED" in text
    log.info("diagnose: needs_remediation=%s", needs_remediation)
    return {"diagnosis": text, "needs_remediation": needs_remediation}


def route_after_diagnosis(state: AgentState) -> Literal["remediate", "inform"]:
    return "remediate" if state["needs_remediation"] else "inform"


def delegate_to_remediation(state: AgentState) -> dict:
    alarm = state["alarm_details"]
    log.info("delegate_to_remediation: delegating for %s", alarm["alarm_name"])
    try:
        response_text = delegate_to_remediation_agent_sync(
            alarm_name=alarm["alarm_name"],
            metric=alarm["metric"],
            diagnosis=state["diagnosis"],
        )
    except Exception as e:
        log.error("delegate_to_remediation: A2A call failed: %s", e)
        response_text = f"[A2A CALL FAILED] Could not reach Remediation Agent: {e}"
    log.info("delegate_to_remediation: received: %s", response_text)
    return {"final_response": response_text}


def respond_informational(state: AgentState) -> dict:
    log.info("respond_informational: done")
    return {"final_response": f"[INFORMATIONAL] {state['diagnosis']}"}


def build_graph(llm):
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


_graph = None


def get_or_create_graph():
    global _graph
    if _graph is None:
        _graph = build_graph(get_or_create_model())
    return _graph


@app.entrypoint
def invoke(payload, context):
    log.info("Invoking Agent.....")

    alarm_name = payload.get("alarm_name")
    if not isinstance(alarm_name, str) or not alarm_name:
        # agentcore CLI's --prompt flag wraps the payload as {"prompt": "<json string>"}
        # instead of sending our {"alarm_name": ...} shape directly.
        if isinstance(payload.get("prompt"), str):
            try:
                alarm_name = json.loads(payload["prompt"]).get("alarm_name")
            except json.JSONDecodeError:
                alarm_name = None
    if not isinstance(alarm_name, str) or not alarm_name:
        raise ValueError("payload must include a non-empty 'alarm_name' string")
    log.info(f"Agent input: alarm_name={alarm_name}")

    graph = get_or_create_graph()
    result = graph.invoke({"alarm_name": alarm_name})

    output = {
        "alarm_name": alarm_name,
        "diagnosis": result["diagnosis"],
        "needs_remediation": result["needs_remediation"],
        "final_response": result["final_response"],
    }
    log.info(f"Agent output: {output}")
    return output


if __name__ == "__main__":
    app.run()
