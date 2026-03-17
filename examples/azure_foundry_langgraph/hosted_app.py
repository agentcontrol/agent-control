"""Entrypoint for Azure AI Foundry Hosted Agents.

Wraps the LangGraph agent with the Foundry adapter and serves on port 8088.
"""

from agent_control_setup import bootstrap_agent_control
from graph import build_graph
from azure.ai.agentserver.langgraph import from_langgraph

bootstrap_agent_control()
agent = build_graph()
adapter = from_langgraph(agent)

if __name__ == "__main__":
    adapter.run()
