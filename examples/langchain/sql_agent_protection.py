"""
LangGraph SQL Agent with Agent Control integration.

This example demonstrates using the @control() decorator to protect SQL queries
with graceful error handling.

PREREQUISITE:
    Run setup_sql_controls.py FIRST to create the SQL control and direct agent association:
    
        $ uv run setup_sql_controls.py
    
    Then run this example:
    
        $ uv run sql_agent_protection.py

The @control() decorator automatically:
1. Detects this is a tool step (from @tool decorator)
2. Sends the query to the server for evaluation
3. Blocks dangerous operations (DROP, DELETE, TRUNCATE, etc.)
4. Requires LIMIT clauses on SELECT statements
5. Prevents multi-statement SQL injection

Error Handling:
- ControlViolationError: Returns error message (query blocked)
- RuntimeError: Returns error message (server unavailable)
- Agent continues running even if control check fails
"""

import asyncio
import os
import pathlib
from typing import Annotated, Literal, TypedDict

import agent_control
from agent_control import (
    AgentControlClient,
    ControlViolationError,
    agents,
    check_evaluation_with_local,
    control,
)
import requests
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# --- Configuration ---
AGENT_ID = "edf66504-0db5-4ee8-9e09-3ef37bbb8faa"
AGENT_NAME = "SQL Demo Agent"
AGENT_DESCRIPTION = "SQL agent with server-side controls"
USE_LOCAL_CONTROLS = os.getenv("AGENT_CONTROL_LOCAL_EVAL", "false").lower() == "true"
# When enabled, controls must be configured with execution="sdk".

# --- 1. Setup Database ---
def setup_database():
    url = "https://storage.googleapis.com/benchmarks-artifacts/chinook/Chinook.db"
    local_path = pathlib.Path("Chinook.db")

    # Check if database exists and has Artist table
    needs_download = True
    if local_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(local_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM Artist")
            count = cursor.fetchone()[0]
            conn.close()
            print(f"✓ Database exists with {count} artists")
            needs_download = False
        except Exception as e:
            print(f"⚠️  Database corrupted or missing Artist table: {e}")
            needs_download = True
    
    if needs_download:
        print(f"📥 Downloading fresh Chinook database...")
        response = requests.get(url)
        if response.status_code == 200:
            local_path.write_bytes(response.content)
            print("✓ Download complete")
        else:
            raise Exception(f"Failed to download database: {response.status_code}")
    
    return SQLDatabase.from_uri("sqlite:///Chinook.db")

# --- 2. Define Tools with Server-Side Controls ---
def create_safe_tools(db, llm, *, use_local_controls: bool, local_controls: list[dict] | None):
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    original_tools = toolkit.get_tools()
    
    # Find the query tool
    query_tool = next(t for t in original_tools if t.name == "sql_db_query")
    
    # Create controlled SQL tool with graceful error handling
    
    # Inner function with @control decorator for validation
    async def _execute_query_with_validation(query: str):
        """Execute SQL query (this function is protected by @control)."""
        return query_tool.invoke(query)
    
    # Set tool name for @control detection
    _execute_query_with_validation.name = "sql_db_query"  # type: ignore
    _execute_query_with_validation.tool_name = "sql_db_query"  # type: ignore
    
    # Apply @control decorator
    validated_query_func = control()(_execute_query_with_validation)
    
    # Outer wrapper: catches exceptions and returns error messages gracefully
    @tool("sql_db_query", description="Execute a SQL query after safety validation")
    async def safe_query_tool(query: str):
        """Execute a SQL query with safety checks."""
        print(f"\n[SQL Safety Check] Validating query: {query[:60]}...")
        try:
            if use_local_controls:
                agent = agent_control.current_agent()
                if agent is None:
                    raise RuntimeError("Agent is not initialized.")
                if not local_controls:
                    raise RuntimeError("No local controls available for SDK evaluation.")

                step = {
                    "type": "tool",
                    "name": "sql_db_query",
                    "input": {"query": query},
                }
                async with AgentControlClient() as client:
                    result = await check_evaluation_with_local(
                        client=client,
                        agent_name=agent.agent_name,
                        step=step,
                        stage="pre",
                        controls=local_controls,
                    )
                if getattr(result, "errors", None):
                    raise RuntimeError("Local control evaluation failed.")
                if not result.is_safe:
                    raise ControlViolationError(message=result.reason or "Control blocked")
                output = query_tool.invoke(query)
            else:
                output = await validated_query_func(query)
            print("✅ Query executed successfully")
            return output
        except ControlViolationError as e:
            # SQL control blocked the query
            error_msg = f"🚫 Query blocked by safety control: {e.message}"
            print(error_msg)
            return error_msg
        except RuntimeError as e:
            # Server-side error (e.g., evaluator not loaded)
            error_msg = f"⚠️ Safety check unavailable: {str(e)}"
            print(error_msg)
            return error_msg
        except Exception as e:
            # Unexpected error
            error_msg = f"❌ Unexpected error: {type(e).__name__}: {str(e)}"
            print(error_msg)
            return error_msg

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
    print("=" * 60)
    print("SQL Agent with Server-Side Controls")
    print("=" * 60)
    print()
    print("NOTE: Make sure you've run setup_sql_controls.py first!")
    print("      $ uv run setup_sql_controls.py")
    print()
    print("Initializing SQL Agent...")

    agent_control.init(
        agent_name=AGENT_ID,
        agent_description=AGENT_DESCRIPTION,
        server_url=os.getenv("AGENT_CONTROL_URL"),
    )

    # 1. Setup DB
    db = setup_database()

    # 2. Setup LLM & Tools
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        return

    llm = ChatOpenAI(model="gpt-4o-mini")

    # Register agent and fetch controls if local evaluation is enabled
    local_controls: list[dict] | None = None
    if USE_LOCAL_CONTROLS:
        agent = agent_control.current_agent()
        if agent is None:
            raise RuntimeError("Agent is not initialized.")
        async with AgentControlClient() as client:
            response = await agents.register_agent(client, agent, steps=[])
            local_controls = response.get("controls", [])
            print(f"✓ Loaded {len(local_controls)} control(s) for local evaluation")

    tools = create_safe_tools(
        db,
        llm,
        use_local_controls=USE_LOCAL_CONTROLS,
        local_controls=local_controls,
    )
    
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
