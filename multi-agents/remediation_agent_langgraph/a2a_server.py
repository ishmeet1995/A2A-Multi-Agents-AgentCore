"""
A2A server for the Remediation Agent.

Mirrors the shape of the reference repo's monitoring_agent/__main__.py
(FastAPI + uvicorn, health check endpoint) but uses the generic a2a-sdk
Starlette application instead of Strands' built-in A2AServer, since
Strands' wrapper only works with a Strands Agent object, not a LangGraph
graph.

Run: python a2a_server.py
Then the agent is live at http://localhost:9001
Agent Card discoverable at http://localhost:9001/.well-known/agent-card.json
"""

import logging

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_executor import RemediationAgentExecutor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("remediation_agent.a2a_server")

HOST = "localhost"
PORT = 9001


def build_agent_card() -> AgentCard:
    """
    Describes this agent for discovery. This is what the Monitoring Agent
    fetches from /.well-known/agent-card.json before delegating to us.
    """
    skill = AgentSkill(
        id="remediate_alarm",
        name="Remediate CloudWatch Alarm",
        description=(
            "Given an alarm and a diagnosis from a monitoring agent, decides "
            "whether to restart an instance, scale out, or escalate to a "
            "human — strictly per the relevant runbook — and executes that action."
        ),
        tags=["ops", "remediation", "cloudwatch"],
        examples=[
            '{"alarm_name": "high-cpu-web-01", "metric": "CPUUtilization", "diagnosis": "..."}'
        ],
    )
    return AgentCard(
        name="Remediation Agent",
        description="Decides and executes remediation actions for diagnosed CloudWatch alarms.",
        url=f"http://{HOST}:{PORT}/",
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[skill],
    )


def build_app():
    agent_card = build_agent_card()
    request_handler = DefaultRequestHandler(
        agent_executor=RemediationAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
    return server.build()


if __name__ == "__main__":
    logger.info(f"Starting Remediation Agent A2A server at http://{HOST}:{PORT}")
    logger.info(f"Agent Card at http://{HOST}:{PORT}/.well-known/agent-card.json")
    app = build_app()
    uvicorn.run(app, host=HOST, port=PORT)
