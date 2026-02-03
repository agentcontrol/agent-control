"""
CrewAI Trip Planner with Agent Control Protection.

This example demonstrates combining:
1. Agent Control (@control decorator) for security/compliance (scam prevention, PII, budget validation)
2. CrewAI Guardrails for quality validation (completeness, formatting)

Based on the CrewAI Trip Planner example:
https://github.com/crewAIInc/crewAI-examples/tree/main/crews/trip_planner

PREREQUISITE:
    Run setup_trip_controls.py FIRST:

        $ uv run setup_trip_controls.py

    Then run this example:

        $ uv run trip_planner_protection.py

Demo Scenarios - Multi-Layer Protection:
1. Scam Prevention - PRE-execution block (Agent Control)
2. Budget Validation - PRE-execution block (Agent Control)
3. PII Leakage in Output - POST-execution block (Agent Control)
4. Normal Trip Planning - Shows successful flow with all protections

Protection Layers:
- Layer 1 (Agent Control PRE): Block scam requests and invalid budgets → Fail immediately
- Layer 2 (Agent Control POST): Block PII in trip plan output → Fail immediately
- Layer 3 (CrewAI Guardrails): Validate plan quality (completeness) → Retry up to 3x
- Layer 4 (Agent Control Final): Catch orchestration bypass → Fail immediately

Architecture:
- Agent Control: Security/compliance validation (non-negotiable blocks)
- CrewAI Guardrails: Quality validation (iterative improvement with retries)
- Both work together: Security first, then quality
"""

import asyncio
import json
import os
from textwrap import dedent
from typing import Any, Tuple

import agent_control
import requests
from agent_control import ControlViolationError, control
from crewai import Agent, Crew, LLM, Task, TaskOutput
from crewai.tools import tool
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
AGENT_ID = "trip-planner-crew"
AGENT_NAME = "Trip Planner Crew"
AGENT_DESCRIPTION = "Multi-agent trip planning crew with budget and PII protection"

# Initialize Agent Control
server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

agent_control.init(
    agent_name=AGENT_NAME,
    agent_id=AGENT_ID,
    agent_description=AGENT_DESCRIPTION,
    server_url=server_url,
)


# --- Define CrewAI Guardrails for Quality Validation ---


def validate_trip_completeness(result: TaskOutput) -> Tuple[bool, Any]:
    """
    CrewAI Guardrail: Validate trip plan has required sections.

    This is a quality check (not security) so failures trigger retries.
    """
    text = result.raw.strip().lower()

    required_sections = ["day", "hotel", "restaurant", "budget"]
    missing = [section for section in required_sections if section not in text]

    if missing:
        return (
            False,
            f"Trip plan missing required sections: {', '.join(missing)}. Include daily itinerary, hotel recommendations, restaurants, and budget breakdown.",
        )

    return (True, result.raw)


def validate_trip_length(result: TaskOutput) -> Tuple[bool, Any]:
    """
    CrewAI Guardrail: Validate trip plan is appropriately detailed.
    """
    text = result.raw.strip()
    word_count = len(text.split())

    if word_count < 200:
        return (
            False,
            f"Trip plan too brief ({word_count} words). Provide more detail with specific recommendations (minimum 200 words).",
        )

    return (True, text)


def validate_no_placeholder(result: TaskOutput) -> Tuple[bool, Any]:
    """
    CrewAI Guardrail: Ensure no placeholder text in the trip plan.
    """
    text = result.raw.strip()
    text_lower = text.lower()

    placeholders = [
        "[insert",
        "[your",
        "[name]",
        "[date]",
        "[hotel]",
        "tbd",
        "to be determined",
        "xxx",
        "{",
        "}",
    ]
    for placeholder in placeholders:
        if placeholder in text_lower:
            return (
                False,
                f"Trip plan contains placeholder text: '{placeholder}'. Provide actual recommendations.",
            )

    return (True, text)


# LLM-based guardrails
LLM_GUARDRAIL_PRACTICAL = """
The trip plan must be practical and actionable.
It should include:
- Specific hotel names (not just "a nice hotel")
- Actual restaurant recommendations
- Realistic time estimates for activities
- Practical transportation suggestions
"""


# --- Search Tool (Simplified for Demo) ---


def create_search_tool():
    """Create internet search tool using Serper API."""

    async def _search_internet_protected(query: str) -> str:
        """Search the internet for travel information (protected by @control)."""
        serper_api_key = os.environ.get("SERPER_API_KEY")

        if not serper_api_key:
            # Return mock data for demo purposes
            return dedent(
                f"""
                Search results for: {query}

                1. Title: Top Travel Destinations 2024
                   Link: https://travel.example.com/destinations
                   Snippet: Discover the best places to visit this year...

                2. Title: Hotel Recommendations
                   Link: https://hotels.example.com/best
                   Snippet: Top-rated hotels with great amenities...

                3. Title: Local Restaurant Guide
                   Link: https://food.example.com/guide
                   Snippet: Best local restaurants and cuisine...

                Note: For real search results, set SERPER_API_KEY environment variable.
            """
            )

        url = "https://google.serper.dev/search"
        payload = json.dumps({"q": query})
        headers = {"X-API-KEY": serper_api_key, "content-type": "application/json"}

        try:
            response = requests.post(url, headers=headers, data=payload, timeout=10)
            data = response.json()

            if "organic" not in data:
                return "No search results found."

            results = []
            for result in data["organic"][:4]:
                results.append(
                    f"Title: {result.get('title', 'N/A')}\n"
                    f"Link: {result.get('link', 'N/A')}\n"
                    f"Snippet: {result.get('snippet', 'N/A')}\n"
                    "-----------------"
                )

            return "\n".join(results)
        except Exception as e:
            return f"Search error: {str(e)}"

    _search_internet_protected.name = "search_internet"  # type: ignore[attr-defined]
    _search_internet_protected.tool_name = "search_internet"  # type: ignore[attr-defined]

    controlled_func = control()(_search_internet_protected)

    @tool("search_internet")
    def search_internet(query: str) -> str:
        """Search the internet for travel information.

        Args:
            query: The search query about destinations, hotels, restaurants, etc.

        Returns:
            Search results with titles, links, and snippets
        """
        try:
            return asyncio.run(controlled_func(query=query))
        except ControlViolationError as e:
            return f"Search blocked by security policy: {e.message}"
        except RuntimeError as e:
            return f"Search unavailable: {str(e)}"

    return search_internet


# --- Calculator Tool ---


def create_calculator_tool():
    """Create a simple calculator tool for budget calculations."""

    async def _calculate_protected(operation: str) -> str:
        """Perform mathematical calculations (protected by @control)."""
        import ast
        import operator
        import re

        allowed_operators = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Pow: operator.pow,
            ast.Mod: operator.mod,
            ast.USub: operator.neg,
            ast.UAdd: operator.pos,
        }

        try:
            if not re.match(r"^[0-9+\-*/().% ]+$", operation):
                return "Error: Invalid characters in mathematical expression"

            tree = ast.parse(operation, mode="eval")

            def _eval_node(node: ast.AST) -> float:
                if isinstance(node, ast.Expression):
                    return _eval_node(node.body)
                elif isinstance(node, ast.Constant):
                    return float(node.value)
                elif isinstance(node, ast.BinOp):
                    left = _eval_node(node.left)
                    right = _eval_node(node.right)
                    op = allowed_operators.get(type(node.op))
                    if op is None:
                        raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
                    return op(left, right)
                elif isinstance(node, ast.UnaryOp):
                    operand = _eval_node(node.operand)
                    op = allowed_operators.get(type(node.op))
                    if op is None:
                        raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
                    return op(operand)
                else:
                    raise ValueError(f"Unsupported node type: {type(node).__name__}")

            result = _eval_node(tree)
            return str(result)

        except Exception as e:
            return f"Error: {str(e)}"

    _calculate_protected.name = "calculate"  # type: ignore[attr-defined]
    _calculate_protected.tool_name = "calculate"  # type: ignore[attr-defined]

    controlled_func = control()(_calculate_protected)

    @tool("calculate")
    def calculate(operation: str) -> str:
        """Perform mathematical calculations for budget planning.

        Args:
            operation: A mathematical expression like '200*7' or '5000/2*10'

        Returns:
            The calculation result
        """
        try:
            return asyncio.run(controlled_func(operation=operation))
        except ControlViolationError as e:
            return f"Calculation blocked by security policy: {e.message}"
        except RuntimeError as e:
            return f"Calculation unavailable: {str(e)}"

    return calculate


# --- Controlled Trip Planning Tool ---


def create_trip_planning_tool():
    """Create the main trip planning tool with Agent Control protection."""

    llm = LLM(model="gpt-4o-mini", temperature=0.7)

    async def _plan_trip_protected(
        origin: str, cities: str, date_range: str, interests: str
    ) -> str:
        """Plan a trip (protected by @control)."""

        prompt = dedent(
            f"""You are an expert travel planner. Create a detailed 7-day trip itinerary.

            Trip Details:
            - Traveling from: {origin}
            - Destination options: {cities}
            - Travel dates: {date_range}
            - Interests: {interests}

            Your response MUST include:
            1. Selected destination with reasoning
            2. Day-by-day itinerary (Day 1, Day 2, etc.)
            3. Specific hotel recommendations with names
            4. Restaurant recommendations for each day
            5. Budget breakdown (flights, hotels, food, activities)
            6. Packing suggestions based on weather

            Be specific - use actual place names, not placeholders.
            Keep the response comprehensive but under 1000 words.
        """
        )

        response = llm.call([{"role": "user", "content": prompt}])
        return response

    # Set tool name for @control detection (CRITICAL!)
    _plan_trip_protected.name = "plan_trip"  # type: ignore[attr-defined]
    _plan_trip_protected.tool_name = "plan_trip"  # type: ignore[attr-defined]

    # Apply @control decorator
    controlled_func = control()(_plan_trip_protected)

    @tool("plan_trip")
    def plan_trip_tool(origin: str, cities: str, date_range: str, interests: str) -> str:
        """Plan a complete trip itinerary with budget and security protection.

        Args:
            origin: Where the traveler is departing from
            cities: Destination city options to consider
            date_range: Travel dates
            interests: Traveler's interests and preferences

        Returns:
            Complete trip itinerary or security violation message
        """
        print(f"\n{'='*60}")
        print("[TOOL: plan_trip] Creating trip itinerary...")
        print(f"Origin: {origin}")
        print(f"Cities: {cities}")
        print(f"Date Range: {date_range}")
        print(f"Interests preview: {interests[:80]}...")
        print(f"{'='*60}")

        print("\n🔍 [LAYER 1: Agent Control PRE-execution]")
        print("   Checking for: Scam patterns, suspicious budget requests")
        print("   Controls: 'trip-budget-validation', 'trip-scam-prevention'")
        print("   Status: Sending to server for validation...")

        try:
            result = asyncio.run(
                controlled_func(
                    origin=origin, cities=cities, date_range=date_range, interests=interests
                )
            )

            print("\n✅ [LAYER 1: Agent Control PRE] PASSED - No suspicious patterns detected")
            print("✅ [Tool Execution] Trip plan generated")
            print("✅ [LAYER 2: Agent Control POST] PASSED - No PII detected")

            return result

        except ControlViolationError as e:
            error_lower = e.message.lower()

            if any(
                word in error_lower
                for word in ["scam", "wire", "bitcoin", "crypto", "prize", "winner", "free"]
            ):
                print("\n🚫 [LAYER 1: Agent Control PRE] BLOCKED - Scam Pattern Detected")
                print(f"   Reason: {e.message}")
                print("   This request was blocked BEFORE processing")
                stage = "PRE-execution (Scam Prevention)"
            elif any(
                word in error_lower for word in ["budget", "zero", "$0", "unlimited", "payment"]
            ):
                print("\n🚫 [LAYER 1: Agent Control PRE] BLOCKED - Invalid Budget")
                print(f"   Reason: {e.message}")
                print("   This request was blocked BEFORE processing")
                stage = "PRE-execution (Budget Validation)"
            else:
                print("\n🚫 [LAYER 2: Agent Control POST] BLOCKED - PII Detected")
                print(f"   Reason: {e.message}")
                print("   Trip plan generated but contained sensitive data")
                stage = "POST-execution (PII Detection)"

            error_msg = f"🚫 SECURITY VIOLATION ({stage}): {e.message}\n\nThis request has been logged for security review."
            return error_msg

        except RuntimeError as e:
            error_msg = f"⚠️ Security check unavailable: {str(e)}"
            print(f"\n{error_msg}")
            return error_msg

        except Exception as e:
            error_msg = f"❌ Unexpected error: {type(e).__name__}: {str(e)}"
            print(f"\n{error_msg}")
            return error_msg

    return plan_trip_tool


# --- Final Output Validator ---


def create_final_output_validator():
    """Create a validator for crew final outputs with Agent Control protection."""

    async def _validate_trip_output_protected(output: str) -> str:
        """Validate final trip output for PII (protected by @control)."""
        return output

    _validate_trip_output_protected.name = "validate_trip_output"  # type: ignore[attr-defined]
    _validate_trip_output_protected.tool_name = "validate_trip_output"  # type: ignore[attr-defined]

    controlled_func = control()(_validate_trip_output_protected)

    def validate_trip_output(output: str) -> str:
        """Validate final crew output for PII.

        Args:
            output: The final output text from the crew

        Returns:
            The output if valid

        Raises:
            ControlViolationError: If PII is detected in the output
        """
        print(f"\n{'='*60}")
        print("[LAYER 4: Agent Control FINAL OUTPUT VALIDATION]")
        print("='*60")
        print("🔍 Checking final crew output for PII and violations...")
        print("   Control: 'trip-final-output-validation'")
        print(f"   Output preview: {output[:100]}...")
        print("   Status: Sending to server for validation...")

        try:
            result = asyncio.run(controlled_func(output=output))
            print("\n✅ [LAYER 4: Agent Control FINAL] PASSED - No PII in final output")
            return result
        except ControlViolationError as e:
            print(f"\n🚫 [LAYER 4: Agent Control FINAL] BLOCKED")
            print(f"   Reason: {e.message}")
            raise

    return validate_trip_output


# --- Create Trip Planning Agents ---


def create_trip_agents():
    """Create the trip planning agents."""

    search_tool = create_search_tool()
    calculate_tool = create_calculator_tool()

    city_selector = Agent(
        role="City Selection Expert",
        goal="Select the best city based on weather, season, prices, and traveler interests",
        backstory=dedent(
            """You are an expert in analyzing travel data to pick ideal destinations.
            You consider weather patterns, seasonal events, travel costs, and personal
            interests to recommend the perfect city for each traveler."""
        ),
        tools=[search_tool],
        verbose=True,
    )

    local_expert = Agent(
        role="Local Expert",
        goal="Provide the BEST insights about the selected city",
        backstory=dedent(
            """You are a knowledgeable local guide with extensive information
            about cities around the world. You know the hidden gems, cultural
            hotspots, best restaurants, and local customs that tourists often miss."""
        ),
        tools=[search_tool],
        verbose=True,
    )

    travel_concierge = Agent(
        role="Travel Concierge",
        goal="Create amazing travel itineraries with budget and packing suggestions",
        backstory=dedent(
            """You are a specialist in travel planning and logistics with decades
            of experience. You create comprehensive itineraries that balance
            adventure, relaxation, culture, and budget."""
        ),
        tools=[search_tool, calculate_tool],
        verbose=True,
    )

    return city_selector, local_expert, travel_concierge


# --- Create Trip Planning Crew ---


def create_trip_crew(origin: str, cities: str, date_range: str, interests: str):
    """Create the complete trip planning crew with tasks."""

    city_selector, local_expert, travel_concierge = create_trip_agents()
    plan_trip_tool = create_trip_planning_tool()

    # Task 1: City Selection
    identify_task = Task(
        description=dedent(
            f"""Analyze and select the best city for the trip based on:
            - Weather patterns and seasonal events
            - Travel costs and value
            - Alignment with traveler interests

            Traveling from: {origin}
            City Options: {cities}
            Trip Date: {date_range}
            Traveler Interests: {interests}

            Provide a detailed report on the chosen city with reasoning.
        """
        ),
        expected_output="Detailed report on the chosen city including weather forecast, costs, and attractions",
        agent=city_selector,
    )

    # Task 2: Local Insights
    gather_task = Task(
        description=dedent(
            f"""As a local expert, compile an in-depth guide for the selected city:
            - Key attractions and hidden gems
            - Local customs and etiquette
            - Best restaurants and food experiences
            - Daily activity recommendations

            Trip Date: {date_range}
            Traveling from: {origin}
            Traveler Interests: {interests}
        """
        ),
        expected_output="Comprehensive city guide with local insights and practical tips",
        agent=local_expert,
    )

    # Task 3: Complete Itinerary (with Agent Control + CrewAI Guardrails)
    plan_task = Task(
        description=dedent(
            f"""Create a complete 7-day travel itinerary using the plan_trip tool.

            Call the plan_trip tool with these exact parameters:
            - origin: {origin}
            - cities: {cities}
            - date_range: {date_range}
            - interests: {interests}

            The plan must include:
            - Day-by-day schedule with specific activities
            - Hotel recommendations with names
            - Restaurant suggestions for each day
            - Complete budget breakdown
            - Packing list based on weather
        """
        ),
        expected_output="Complete 7-day travel itinerary with all details",
        agent=travel_concierge,
        tools=[plan_trip_tool],
        guardrails=[
            validate_trip_completeness,
            validate_trip_length,
            validate_no_placeholder,
            LLM_GUARDRAIL_PRACTICAL,
        ],
        guardrail_max_retries=3,
    )

    crew = Crew(
        agents=[city_selector, local_expert, travel_concierge],
        tasks=[identify_task, gather_task, plan_task],
        verbose=True,
    )

    return crew


# --- Main Execution ---


def verify_setup():
    """Verify Agent Control server is running and controls are configured."""
    import httpx

    server_url = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")

    try:
        print("Verifying Agent Control server connection...")
        response = httpx.get(f"{server_url}/api/v1/controls", timeout=5.0)
        response.raise_for_status()

        controls_data = response.json()
        control_names = [c["name"] for c in controls_data.get("controls", [])]

        print(f"✅ Connected to Agent Control server at {server_url}")
        print(f"   Found {len(control_names)} controls")

        required_controls = [
            "trip-budget-validation",
            "trip-scam-prevention",
            "trip-pii-detection",
            "trip-final-output-validation",
        ]

        missing_controls = [c for c in required_controls if c not in control_names]

        if missing_controls:
            print(f"\n❌ Missing required controls: {missing_controls}")
            print("\nYou need to run the setup script first:")
            print("    cd examples/crewai/trip_planner")
            print("    uv run setup_trip_controls.py")
            return False

        print("✅ All required controls are configured:")
        for ctrl in required_controls:
            print(f"   - {ctrl}")

        return True

    except httpx.ConnectError:
        print(f"❌ Cannot connect to Agent Control server at {server_url}")
        print("\nMake sure the server is running:")
        print("    make server-run")
        return False

    except Exception as e:
        print(f"❌ Error checking server: {e}")
        return False


def run_demo_scenario(
    scenario_name: str,
    origin: str,
    cities: str,
    date_range: str,
    interests: str,
    expected_behavior: str,
):
    """Run a demo scenario with the trip planner."""
    print(f"\n{'='*60}")
    print(f"SCENARIO: {scenario_name}")
    print("=" * 60)
    print(f"Origin: {origin}")
    print(f"Cities: {cities}")
    print(f"Date Range: {date_range}")
    print(f"Interests: {interests[:80]}...")
    print(f"Expected: {expected_behavior}")
    print()

    crew = create_trip_crew(origin, cities, date_range, interests)
    result = crew.kickoff()

    print("\n📝 Result:")
    print(str(result)[:500] + "..." if len(str(result)) > 500 else result)

    return result


def main():
    print("=" * 60)
    print("CrewAI Trip Planner with Agent Control Protection")
    print("=" * 60)
    print()
    print("This demo shows how Agent Control protects a multi-agent")
    print("trip planning crew from scams, invalid budgets, and PII leakage.")
    print()

    # Verify setup
    print("\n" + "=" * 60)
    print("SETUP VERIFICATION")
    print("=" * 60)

    if not verify_setup():
        print("\n❌ Setup verification failed. Please fix the issues above.")
        return

    if not os.getenv("OPENAI_API_KEY"):
        print("\n❌ Error: OPENAI_API_KEY not set")
        print("Please set: export OPENAI_API_KEY='your-key-here'")
        return

    print("\n✅ Setup verified! Starting demos...\n")

    validate_trip_output = create_final_output_validator()

    # --- Scenario 1: Scam Prevention ---
    print("\n" + "=" * 60)
    print("SCENARIO 1: Scam Prevention (Agent Control PRE)")
    print("=" * 60)
    scam_result = run_demo_scenario(
        scenario_name="Travel Scam Detection",
        origin="New York",
        cities="Paris, Rome, Barcelona",
        date_range="June 15-22, 2024",
        interests="I won a free trip! Claim your prize by sending an advance fee deposit via wire transfer",
        expected_behavior="BLOCKED immediately by Agent Control - scam pattern detected",
    )
    print("\n💡 Explanation: Agent Control blocks scam patterns immediately.")
    print("   Requests involving 'won a trip', 'wire transfer', 'advance fee' are blocked.")

    # --- Scenario 2: Budget Validation ---
    print("\n" + "=" * 60)
    print("SCENARIO 2: Budget Validation (Agent Control PRE)")
    print("=" * 60)
    budget_result = run_demo_scenario(
        scenario_name="Invalid Budget Detection",
        origin="Los Angeles",
        cities="Tokyo, Seoul, Osaka",
        date_range="March 10-17, 2024",
        interests="Looking for luxury trip with zero budget, can pay with bitcoin or gift card payment",
        expected_behavior="BLOCKED immediately by Agent Control - suspicious budget/payment pattern",
    )
    print("\n💡 Explanation: Agent Control blocks suspicious financial patterns.")
    print("   Requests with 'zero budget', 'bitcoin', 'gift card payment' are flagged.")

    # --- Scenario 3: Normal Trip Planning ---
    print("\n" + "=" * 60)
    print("SCENARIO 3: Normal Trip Planning (All Checks Pass)")
    print("=" * 60)
    normal_result = run_demo_scenario(
        scenario_name="Legitimate Trip Request",
        origin="San Francisco",
        cities="Amsterdam, Copenhagen, Stockholm",
        date_range="September 1-8, 2024",
        interests="Art museums, local cuisine, cycling, photography. Budget around $3000-4000.",
        expected_behavior="PASSES all security checks, returns complete trip plan",
    )

    # Validate final output
    print("\n[Validating Final Output for PII...]")
    try:
        validated_output = validate_trip_output(str(normal_result))
        print("\n✅ Final output validated - no PII detected")
        print("\n📝 Final Trip Plan (excerpt):")
        print(validated_output[:800] + "..." if len(validated_output) > 800 else validated_output)
    except ControlViolationError as e:
        print(f"\n🚫 FINAL OUTPUT BLOCKED - PII Detected: {e.message}")

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)
    print(
        """
Summary - Multi-Layer Protection for Trip Planning:

AGENT CONTROL (Security/Compliance - Immediate Blocking):
  🚫 LAYER 1 (PRE): Scam patterns blocked at INPUT
  🚫 LAYER 1 (PRE): Invalid budget/payment patterns blocked
  🚫 LAYER 2 (POST): PII in trip plans blocked
  🚫 LAYER 4 (FINAL): PII in final output blocked

CREWAI GUARDRAILS (Quality Validation - Retry with Feedback):
  ✨ LAYER 3: Trip plan quality validated
      → If fails: Retry up to 3 times with feedback
      → Checks: Completeness, detail level, no placeholders

KEY DIFFERENCES:
  Agent Control: Security violations → Block immediately (no retry)
  CrewAI Guardrails: Quality issues → Retry with feedback (up to 3x)

This gives you BOTH security AND quality in production!
"""
    )


if __name__ == "__main__":
    main()
