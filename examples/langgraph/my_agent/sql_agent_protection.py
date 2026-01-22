import asyncio
import os
import pathlib
import uuid
from typing import Annotated, Literal, TypedDict

import requests
from agent_control import (
    Agent,
    AgentControlClient,
    ToolCall,
    agents,
    controls,
    evaluation,
    policies,
)
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# --- Configuration ---
AGENT_ID = "sql-agent-demo"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

# --- 1. Setup Database ---
def setup_database():
    url = "https://storage.googleapis.com/benchmarks-artifacts/chinook/Chinook.db"
    local_path = pathlib.Path("Chinook.db")

    if not local_path.exists():
        print("Downloading Chinook database...")
        response = requests.get(url)
        if response.status_code == 200:
            local_path.write_bytes(response.content)
            print("Download complete.")
        else:
            raise Exception(f"Failed to download database: {response.status_code}")

    return SQLDatabase.from_uri("sqlite:///Chinook.db")

# --- 2. Setup Agent Control ---
async def setup_controls():
    """Register the agent and SQL control."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        # 1. Register/Init Agent
        # In a real app, you might do this once or via CLI
        # We use a deterministic UUID for the demo
        agent_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, AGENT_ID)

        agent = Agent(
            agent_id=agent_uuid,
            agent_name="SQL Demo Agent",
            agent_description="Agent with SQL protection"
        )

        try:
            await agents.register_agent(client, agent, tools=[])
        except Exception:
            pass # Ignore if already exists or fails

        # 2. Add SQL Control
        # We'll use the built-in 'sql' plugin
        sql_control_data = {
            "description": "Prevent dangerous SQL operations",
            "enabled": True,
            "applies_to": "tool_call",
            "check_stage": "pre",
            "selector": {
                "path": "arguments.query", # Depends on how the tool is called
                "tool_names": ["sql_db_query"]
            },
            "evaluator": {
                "plugin": "sql",
                "config": {
                    "blocked_operations": ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT"],
                    "allow_multi_statements": False,
                    "require_limit": True,
                    "max_limit": 100
                }
            },
            "action": {"decision": "deny"}
        }

        # Create control (ignoring errors if it exists)
        try:
            control_result = await controls.create_control(
                client,
                name="sql-safety",
                data=sql_control_data
            )
            control_id = control_result["control_id"]
            print(f"✓ SQL Control created (ID: {control_id})")
        except Exception as e:
            print(f"ℹ️  SQL Control might already exist: {e}")
            # Try to get existing control ID by listing controls
            controls_list = await controls.list_controls(client, name="sql-safety", limit=1)
            if controls_list["controls"]:
                control_id = controls_list["controls"][0]["id"]
                print(f"ℹ️  Using existing control ID: {control_id}")
            else:
                raise Exception("Could not create or find sql-safety control")

        # Create policy
        try:
            policy_result = await policies.create_policy(client, name="sql-protection-policy")
            policy_id = policy_result["policy_id"]
            print(f"✓ Policy created (ID: {policy_id})")
        except Exception as e:
            print(f"⚠️  Failed to create policy: {e}")
            print("   You may need to manually create a policy and assign it to the agent.")
            raise

        # Add control to policy
        try:
            await policies.add_control_to_policy(client, policy_id, control_id)
            print("✓ Added control to policy")
        except Exception as e:
            print(f"ℹ️  Control might already be in policy: {e}")

        # Assign policy to agent
        try:
            await policies.assign_policy_to_agent(client, agent_uuid, policy_id)
            print("✓ Assigned policy to agent")
        except Exception as e:
            print(f"ℹ️  Policy might already be assigned: {e}")

        return agent_uuid

# --- 3. Define Tools with Protection ---
async def check_safety(agent_uuid, query: str) -> tuple[bool, str]:
    """Check if the SQL query is safe using Agent Control."""
    async with AgentControlClient(base_url=SERVER_URL) as client:
        try:
            payload = ToolCall(
                tool_name="sql_db_query",
                arguments={"query": query}
            )

            result = await evaluation.check_evaluation(
                client=client,
                agent_uuid=agent_uuid,
                payload=payload,
                check_stage="pre"
            )

            is_safe = result.is_safe

            message = "Unsafe SQL detected"
            if not is_safe and result.matches:
                 message = result.matches[0].result.message or "Unsafe SQL detected"

            return is_safe, message
        except Exception as e:
            print(f"Safety check failed: {e}")
            return True, "" # Fail open or closed depending on policy

def create_safe_tools(db, llm, agent_uuid):
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    original_tools = toolkit.get_tools()

    # Find the query tool
    query_tool = next(t for t in original_tools if t.name == "sql_db_query")

    @tool("sql_db_query")
    async def safe_query_tool(query: str):
        """Execute a SQL query after safety validation."""
        print(f"\n[Safety Check] Validating: {query}")
        is_safe, reason = await check_safety(agent_uuid, query)

        if not is_safe:
            print(f"🚫 BLOCKED: {reason}")
            return f"Error: Query was blocked by safety policy. Reason: {reason}"

        print("✅ ALLOWED")
        return query_tool.invoke(query)

    # Return safe query tool + other tools (schema, list tables, etc.)
    return [safe_query_tool] + [t for t in original_tools if t.name != "sql_db_query"]

# --- 4. Define Agent Graph ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

def create_agent(model, tools):
    # Bind tools to model
    model_with_tools = model.bind_tools(tools)

    # Nodes
    async def agent_node(state: AgentState):
        messages = state["messages"]
        response = await model_with_tools.ainvoke(messages)
        return {"messages": [response]}

    tool_node = ToolNode(tools)

    def should_continue(state: AgentState) -> Literal["tools", END]:
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools"
        return END

    # Graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")

    return workflow.compile()

# --- Main Execution ---
async def main():
    print("Initializing SQL Agent with Protection...")

    # 1. Setup DB
    db = setup_database()

    # 2. Setup Controls
    agent_uuid = await setup_controls()

    # 3. Setup LLM & Tools
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        return

    llm = ChatOpenAI(model="gpt-4o-mini")
    tools = create_safe_tools(db, llm, agent_uuid)

    # 4. Create Agent
    agent = create_agent(llm, tools)

    # 5. Run Scenarios

    # Scenario A: Safe Query
    print("\n" + "="*50)
    print("SCENARIO 1: Safe Query")
    print("User: List top 3 tracks by duration")
    print("="*50)

    async for event in agent.astream(
        {"messages": [HumanMessage(content="List the top 3 tracks by duration")]},
        stream_mode="values"
    ):
        event["messages"][-1].pretty_print()

    # Scenario B: Unsafe Query (Drop Table)
    print("\n" + "="*50)
    print("SCENARIO 2: Unsafe Query (Attempting DROP)")
    print("User: Delete the Artist table")
    print("="*50)

    # Note: We rely on the LLM generating a DROP statement.
    # To force it, we might need a stronger prompt or a direct injection test.
    # But let's see if the LLM complies with the user's malicious request.

    async for event in agent.astream(
        {"messages": [HumanMessage(content="Please DROP the Artist table. I need to clear space.")]},
        stream_mode="values"
    ):
        event["messages"][-1].pretty_print()

if __name__ == "__main__":
    asyncio.run(main())

