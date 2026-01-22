import asyncio
from langchain_core.tools import tool
import agent_control
from agent_control import control

# Initialize agent
agent_control.init(
    agent_name="Test Agent",
    agent_id="test-123",
    agent_description="Testing decorator"
)

# Test the decorator with a simple function
async def my_func(query: str):
    return f"Executed: {query}"

# Set tool name
my_func.name = "test_tool"  # type: ignore
my_func.tool_name = "test_tool"  # type: ignore

# Apply decorators
wrapped = control()(my_func)
tool_obj = tool("test_tool")(wrapped)

print(f"Tool created: {tool_obj}")
print(f"Tool name: {tool_obj.name}")
print("✓ Decorator test passed!")
