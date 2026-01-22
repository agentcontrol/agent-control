#!/usr/bin/env python3
"""
Demo script showing how to make evaluation requests that trigger human_review controls.

This script demonstrates:
1. Making evaluation requests with ToolCall payloads
2. Handling human_review_required responses
3. Distinguishing between hard denials vs. pending review

Prerequisites:
    1. Agent Control server running: cd server && make run
    2. Controls created (including human_review control):
       uv run python examples/agent_control_demo/setup_controls.py

Usage:
    uv run python examples/agent_control_demo/demo_human_review.py
"""

import asyncio
import os
import sys
from uuid import NAMESPACE_DNS, uuid5

# Add the SDK to path for development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdks/python/src"))

from agent_control import AgentControlClient
from agent_control_models.agent import ToolCall
from agent_control_models.evaluation import EvaluationRequest

# Configuration
AGENT_NAME = "demo-chatbot"  # Use same agent as setup_controls.py
AGENT_ID = "demo-chatbot-v1"  # Use same agent as setup_controls.py
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def make_evaluation_request(
    client: AgentControlClient,
    agent_uuid: str,
    tool_name: str,
    query: str,
    scenario_name: str
) -> dict:
    """
    Make an evaluation request and return the response.

    Args:
        client: AgentControlClient instance
        agent_uuid: UUID of the agent
        tool_name: Name of the tool being called
        query: SQL query to evaluate
        scenario_name: Human-readable scenario name

    Returns:
        dict: Evaluation response
    """
    print(f"\n{'─' * 70}")
    print(f"📋 SCENARIO: {scenario_name}")
    print(f"{'─' * 70}")
    print(f"Tool: {tool_name}")
    print(f"Query: {query}")
    print()

    # Create the evaluation request
    payload = ToolCall(
        tool_name=tool_name,
        arguments={"query": query},
        # Note: output is None for pre-execution checks
    )

    request = EvaluationRequest(
        agent_uuid=agent_uuid,
        payload=payload,
        check_stage="pre"  # Check BEFORE tool execution
    )

    try:
        # Make the evaluation request
        response = await client.http_client.post(
            "/api/v1/evaluation",
            json=request.model_dump(mode="json")
        )
        response.raise_for_status()
        result = response.json()

        # Display results
        print("📊 EVALUATION RESULT:")
        print(f"   is_safe: {result.get('is_safe')}")
        print(f"   human_review_required: {result.get('human_review_required', False)}")
        print(f"   confidence: {result.get('confidence')}")

        # Display matches
        matches = result.get('matches', [])
        if matches:
            print(f"\n   Matched Controls ({len(matches)}):")
            for match in matches:
                control_name = match.get('control_name', 'unknown')
                action = match.get('action', 'unknown')
                message = match.get('result', {}).get('message', 'No message')
                print(f"      • {control_name}")
                print(f"        Action: {action}")
                print(f"        Message: {message}")

        # Display errors
        errors = result.get('errors', [])
        if errors:
            print(f"\n   ⚠️  Errors ({len(errors)}):")
            for error in errors:
                print(f"      • {error.get('control_name', 'unknown')}: {error.get('result', {}).get('error', 'Unknown error')}")

        # Determine outcome
        print(f"\n{'─' * 70}")
        if result.get('is_safe'):
            print("✅ OUTCOME: ALLOWED - Request can proceed")
        elif result.get('human_review_required'):
            print("⏳ OUTCOME: PENDING REVIEW - Blocked pending human approval")
            print("   → This operation could be allowed after manual review")
            print("   → A reviewer can approve/reject via review dashboard")
        else:
            print("🚫 OUTCOME: DENIED - Hard block, cannot proceed")
            print("   → This is a policy violation that cannot be overridden")

        return result

    except Exception as e:
        print(f"❌ ERROR: {e}")
        raise


async def run_demo():
    """Run the human review demo scenarios."""
    print("\n" + "=" * 70)
    print("AGENT CONTROL DEMO: Human Review Evaluation Requests")
    print("=" * 70)

    # Generate agent UUID
    agent_uuid = str(uuid5(NAMESPACE_DNS, AGENT_ID))

    print(f"\n🤖 Agent: {AGENT_NAME}")
    print(f"   UUID: {agent_uuid}")
    print(f"   Server: {SERVER_URL}")

    async with AgentControlClient(base_url=SERVER_URL) as client:
        # Check server health
        try:
            health = await client.health_check()
            print(f"\n✓ Server is healthy: {health.get('status', 'unknown')}")
        except Exception as e:
            print(f"\n✗ Server not available: {e}")
            print("\nMake sure the server is running:")
            print("  cd server && make run")
            return

        # =======================================================================
        # SCENARIO 1: Safe SQL Query (Should be ALLOWED)
        # =======================================================================
        await make_evaluation_request(
            client=client,
            agent_uuid=agent_uuid,
            tool_name="sql_db_query",
            query="SELECT * FROM users WHERE id = 123",
            scenario_name="Safe SQL Query - Should be ALLOWED"
        )

        # =======================================================================
        # SCENARIO 2: Safe SELECT Query (Should be ALLOWED)
        # =======================================================================
        await make_evaluation_request(
            client=client,
            agent_uuid=agent_uuid,
            tool_name="sql_db_query",
            query="SELECT email, created_at FROM users WHERE id > 100",
            scenario_name="Safe SELECT Query - Should be ALLOWED"
        )

        # =======================================================================
        # SCENARIO 3: UPDATE Operation (Should require HUMAN REVIEW)
        # =======================================================================
        # This triggers the "high-risk-sql-review" regex control with action="human_review"
        await make_evaluation_request(
            client=client,
            agent_uuid=agent_uuid,
            tool_name="sql_db_query",
            query="UPDATE users SET last_login = NOW() WHERE id = 123",
            scenario_name="UPDATE Operation - Should require HUMAN REVIEW"
        )

        # =======================================================================
        # SCENARIO 4: Another UPDATE (Should require HUMAN REVIEW)
        # =======================================================================
        await make_evaluation_request(
            client=client,
            agent_uuid=agent_uuid,
            tool_name="execute_sql",
            query="UPDATE products SET price = price * 1.1 WHERE category = 'electronics'",
            scenario_name="UPDATE with WHERE clause - Should require HUMAN REVIEW"
        )

        # =======================================================================
        # SCENARIO 5: Safe INSERT (Should be ALLOWED)
        # =======================================================================
        await make_evaluation_request(
            client=client,
            agent_uuid=agent_uuid,
            tool_name="run_query",
            query="INSERT INTO logs (user_id, action, timestamp) VALUES (123, 'login', NOW())",
            scenario_name="Safe INSERT - Should be ALLOWED"
        )

        # Summary
        print("\n" + "=" * 70)
        print("DEMO COMPLETE!")
        print("=" * 70)
        print("""
Summary of Control Actions:

🟢 ALLOW:
   • Safe queries (SELECT, INSERT without matching controls)
   • Normal operations that don't match any control

🔴 DENY (Hard Block):
   • Dangerous SQL keywords in LLM input detected by list control:
     - DROP, DELETE, TRUNCATE, ALTER, GRANT, REVOKE, EXECUTE, SHUTDOWN, BACKUP
   • Only applies to llm_call (not tool_call)
   • These keywords in LLM context might indicate instruction injection
   • Note: These keywords ARE allowed in tool_call contexts

🟡 HUMAN_REVIEW (Pending Approval):
   • UPDATE operations on tool calls:
     - Any UPDATE statement in SQL query arguments
     - Requires approval before execution
     - Only applies to tool_call (sql_db_query, execute_sql, run_query)

Control Scope:
   The controls apply to different payload types:
   - block-dangerous-sql: Applies to llm_call (path: input)
   - high-risk-sql-review: Applies to tool_call (path: arguments.query)
   - This prevents overlap and ensures correct behavior

Key Differences:

DENY vs HUMAN_REVIEW:
  ├─ Both set is_safe = False (block execution)
  ├─ DENY: Policy violation, cannot proceed
  └─ HUMAN_REVIEW: Can proceed after approval
      ├─ human_review_required = True
      ├─ Review stored in database
      └─ Can be approved/rejected via dashboard

Response Structure:
{
  "is_safe": false,
  "human_review_required": true,  // Only true for human_review actions
  "confidence": 1.0,
  "matches": [
    {
      "control_name": "high-risk-sql-review",
      "action": "human_review",  // vs "deny"
      "result": {
        "matched": true,
        "message": "Pattern matched: UPDATE"
      }
    }
  ]
}

Next Steps:
  1. Implement review queue UI to approve/reject pending reviews
  2. Add notifications when human review is required
  3. Track approval/rejection history for audit
""")


async def demo_sdk_usage():
    """
    Demonstrate SDK usage with human review handling.

    This shows how application code can handle the different outcomes.
    """
    print("\n" + "=" * 70)
    print("BONUS: SDK Usage Pattern for Human Review")
    print("=" * 70)

    print("""
Application Code Pattern:

```python
from agent_control import AgentControlClient
from agent_control_models.agent import ToolCall
from agent_control_models.evaluation import EvaluationRequest

async def execute_tool_with_safety_check(tool_name: str, query: str):
    '''Execute a tool with safety checking.'''

    async with AgentControlClient(base_url=SERVER_URL) as client:
        # Create evaluation request
        payload = ToolCall(tool_name=tool_name, arguments={"query": query})
        request = EvaluationRequest(
            agent_uuid=AGENT_UUID,
            payload=payload,
            check_stage="pre"
        )

        # Check safety
        response = await client.http_client.post("/api/v1/evaluation", json=request.model_dump())
        result = response.json()

        # Handle different outcomes
        if result['is_safe']:
            # ✅ Safe to proceed
            return await execute_tool(tool_name, query)

        elif result.get('human_review_required'):
            # ⏳ Pending review
            review_id = await create_review_request(result)
            raise PendingReviewError(
                f"Operation requires approval. Review ID: {review_id}",
                review_id=review_id,
                matches=result['matches']
            )

        else:
            # 🚫 Hard denial
            raise ControlViolationError(
                "Operation blocked by policy",
                matches=result['matches']
            )

# Exception classes
class PendingReviewError(Exception):
    '''Raised when human review is required.'''
    def __init__(self, message, review_id, matches):
        super().__init__(message)
        self.review_id = review_id
        self.matches = matches

class ControlViolationError(Exception):
    '''Raised when control denies the operation.'''
    def __init__(self, message, matches):
        super().__init__(message)
        self.matches = matches

# Usage in application
try:
    result = await execute_tool_with_safety_check("sql_db_query", "UPDATE users SET status = 'active'")
    print(f"✅ Success: {result}")

except PendingReviewError as e:
    print(f"⏳ Pending review: {e.review_id}")
    # Show UI notification, send email, etc.
    # User can check review status via dashboard

except ControlViolationError as e:
    print(f"🚫 Blocked: {e}")
    # Log violation, show error to user
```

Key Points:
  1. Check is_safe first (both deny and human_review set this to False)
  2. Then check human_review_required to distinguish the two
  3. Use different exception types for different error handling
  4. Store review requests for later approval workflow
""")


if __name__ == "__main__":
    asyncio.run(run_demo())
    asyncio.run(demo_sdk_usage())
