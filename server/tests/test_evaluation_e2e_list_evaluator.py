"""End-to-end tests for AllowList/DenyList logic using the new ListEvaluator."""
import uuid
from fastapi.testclient import TestClient
from agent_control_models import EvaluationRequest, Step
from .utils import create_and_assign_policy

def test_list_evaluator_denylist_behavior(client: TestClient):
    """Test DenyList behavior: Block if ANY value matches."""
    # Given: A registered agent with a DenyList control blocking "rm" and "shutdown"
    control_data = {
        "description": "DenyList Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.cmd"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["rm", "shutdown"],
                "logic": "any",
                "match_on": "match" # Triggers (returns True) if any match found
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="DenyListAgent")

    # Case 1: Safe Value
    # When: Sending a tool step with a safe command "ls"
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="shell", input={"cmd": "ls"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))

    # Then: The request should be allowed (is_safe=True)
    assert resp.json()["is_safe"] is True

    # Case 2: Unsafe Value
    # When: Sending a tool step with a forbidden command "rm"
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="shell", input={"cmd": "rm"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))

    # Then: The request should be denied (is_safe=False) and match the control
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name


def test_list_evaluator_allowlist_behavior(client: TestClient):
    """Test AllowList behavior: Block if value is NOT in list."""
    # Given: A registered agent with an AllowList control allowing ONLY "safe_tool"
    # We use match_on="no_match" to trigger the control (Deny) if the value is NOT found in the list
    control_data = {
        "description": "AllowList Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "name"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["safe_tool"],
                "logic": "any", 
                "match_on": "no_match" # Triggers if NO match found
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="AllowListAgent")

    # Case 1: Allowed Value
    # When: Sending a tool step with the allowed tool "safe_tool"
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="safe_tool", input={}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))

    # Then: The request should be allowed
    assert resp.json()["is_safe"] is True

    # Case 2: Disallowed Value
    # When: Sending a tool step with a tool NOT in the list ("unknown_tool")
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="unknown_tool", input={}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))

    # Then: The request should be denied
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name


def test_list_evaluator_case_insensitive(client: TestClient):
    """Test case-insensitive matching."""
    # Given: A control blocking "BlockMe" with case_sensitive=False
    control_data = {
        "description": "Case Insensitive Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["pre"]},
        "selector": {"path": "input"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["BlockMe"],
                "case_sensitive": False,
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="CaseAgent")

    # When: Sending input "blockme" (lowercase)
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="llm", name="test-step", input="blockme", output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

    # Then: The request should be denied because it matches case-insensitively
    assert resp.json()["is_safe"] is False


def test_list_evaluator_list_input_any_match(client: TestClient):
    """Test matching against a list input (e.g. tags) with logic='any'."""
    # Given: A control blocking request if ANY tag is "restricted"
    control_data = {
        "description": "Restricted Tags",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.tags"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["restricted"],
                "logic": "any",
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="TagAgent")

    # Case 1: List containing restricted item
    # When: Sending tags ["public", "restricted"]
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="update", input={"tags": ["public", "restricted"]}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))

    # Then: The request should be denied
    assert resp.json()["is_safe"] is False

    # Case 2: List containing only safe items
    # When: Sending tags ["public", "internal"]
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="update", input={"tags": ["public", "internal"]}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))

    # Then: The request should be allowed
    assert resp.json()["is_safe"] is True


def test_list_evaluator_list_input_all_match(client: TestClient):
    """Test matching against a list input with logic='all'."""
    # Given: A control requiring ALL tags to be "safe_tag" or "audit_approved"
    # We trigger Deny if the condition (ALL items match) is NOT met (match_on="no_match")
    control_data = {
        "description": "Enforce Safe Tags",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.tags"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["safe_tag", "audit_approved"],
                "logic": "all",
                "match_on": "no_match" # Trigger if logic 'all' fails
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_data, agent_name="SafeTagAgent")

    # Case 1: All items match
    # When: Sending only safe tags
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="update", input={"tags": ["safe_tag", "audit_approved"]}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))

    # Then: The request should be allowed (logic=True, match_on="no_match" -> Trigger=False)
    assert resp.json()["is_safe"] is True

    # Case 2: Mixed items (one unsafe)
    # When: Sending tags with one risky item
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="update", input={"tags": ["safe_tag", "risky"]}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))

    # Then: The request should be denied (logic=False, match_on="no_match" -> Trigger=True)
    assert resp.json()["is_safe"] is False


def test_list_evaluator_disallow_name(client: TestClient):
    """Test Disallowing specific tool names (DenyList on name)."""
    # Given: A control blocking "delete_user" and "drop_db" tools
    control_data = {
        "description": "Block Dangerous Tools",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "name"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["delete_user", "drop_db"],
                "logic": "any",
                "match_on": "match" # Trigger if name is in list
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="NoDangerousTools")

    # Case 1: Allowed Tool
    # When: Calling a safe tool
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="get_user", input={"id": "123"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    # Then: evaluation is safe
    assert resp.json()["is_safe"] is True

    # Case 2: Disallowed Tool
    # When: Calling a dangerous tool
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="delete_user", input={"id": "123"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))
    # Then: evaluation is unsafe and matches the control
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name


def test_list_evaluator_allow_only_argument_values(client: TestClient):
    """Test Allowing ONLY specific values for an argument (AllowList on argument)."""
    # Given: A control allowing only "us-east-1" or "us-west-2" for "region" argument
    control_data = {
        "description": "Enforce Allowed Regions",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.region"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["us-east-1", "us-west-2"],
                "logic": "any",
                "match_on": "no_match" # Trigger if value is NOT in list
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_data, agent_name="RegionPolicy")

    # Case 1: Allowed Value
    # When: Using an allowed region
    req_safe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="deploy", input={"region": "us-east-1"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_safe.model_dump(mode="json"))
    # Then: evaluation is safe
    assert resp.json()["is_safe"] is True

    # Case 2: Disallowed Value
    # When: Using a disallowed region
    req_unsafe = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="deploy", input={"region": "eu-central-1"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_unsafe.model_dump(mode="json"))
    # Then: evaluation is unsafe and matches the control
    assert resp.json()["is_safe"] is False
    assert resp.json()["matches"][0]["control_name"] == control_name


def test_list_evaluator_edge_cases(client: TestClient):
    """Test edge cases: Empty inputs, Empty controls, Type coercion, Special chars."""
    # 1. Empty Control Values
    # Given: Control with empty values list
    control_empty = {
        "description": "Empty Values Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "name"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": [],
                "logic": "any",
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_empty, agent_name="EmptyControlAgent")

    # When: Calling any tool
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="something", input={}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))
    # Then: Should be safe (empty list matches nothing)
    assert resp.json()["is_safe"] is True

    # 2. Type Coercion (Int vs String)
    # Given: Control with integer values
    control_types = {
        "description": "Type Coercion Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.count"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": [10, 20], # Integers in control
                "logic": "any",
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_types, agent_name="TypeAgent")

    # When: Input is integer 10
    req_int = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="count", input={"count": 10}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_int.model_dump(mode="json"))
    # Then: Should match (deny)
    assert resp.json()["is_safe"] is False

    # When: Input is string "20"
    req_str = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="count", input={"count": "20"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_str.model_dump(mode="json"))
    # Then: Should match (deny) - coercion works
    assert resp.json()["is_safe"] is False

    # 3. Special Characters
    # Given: Control with regex special characters
    control_special = {
        "description": "Special Chars Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.query"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["(test)", "a.b*c"], # Literal parens and dot/star
                "logic": "any",
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, control_name = create_and_assign_policy(client, control_special, agent_name="SpecialCharAgent")

    # When: Input exactly matches "(test)"
    req_special = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="search", input={"query": "(test)"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_special.model_dump(mode="json"))
    # Then: Should match (deny)
    assert resp.json()["is_safe"] is False

    # When: Input is "test" (without parens)
    req_normal = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="search", input={"query": "test"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_normal.model_dump(mode="json"))
    # Then: Should NOT match (safe)
    assert resp.json()["is_safe"] is True

    # 4. Empty/None Input
    # Given: Control looking for "null" or empty string?
    # Actually testing if control blows up on None/Empty input
    control_null = {
        "description": "Null Input Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.missing_arg"}, # Will be None
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["something"],
                "logic": "any",
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_null, agent_name="NullAgent")

    # When: Selector returns None
    req_null = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="check", input={}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_null.model_dump(mode="json"))
    # Then: Should be safe (None input -> empty list -> no match)
    assert resp.json()["is_safe"] is True


def test_list_evaluator_re2_corner_cases(client: TestClient):
    """Test re2 specific corner cases: Large lists, Null bytes, Newlines."""
    # 1. Large List (Performance/Limits)
    # Given: A control with 1000 values
    large_list = [f"value_{i}" for i in range(1000)]
    large_list.append("target_value")
    
    control_large = {
        "description": "Large List Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.item"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": large_list,
                "logic": "any",
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_large, agent_name="LargeListAgent")

    # When: Matching the last item
    req = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="check", input={"item": "target_value"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))
    # Then: Should match
    assert resp.json()["is_safe"] is False


def test_list_evaluator_newline_strictness(client: TestClient):
    """Test that list matching is strict about newlines."""
    # Given: Control matching "exact"
    control_strict = {
        "description": "Strict Match Control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "input.val"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["exact"],
                "logic": "any",
                "match_on": "match"
            }
        },
        "action": {"decision": "deny"}
    }
    agent_uuid, _ = create_and_assign_policy(client, control_strict, agent_name="StrictAgent")

    # When: Sending "exact\n" (trailing newline)
    req_newline = EvaluationRequest(
        agent_uuid=agent_uuid,
        step=Step(type="tool", name="check", input={"val": "exact\n"}, output=None),
        stage="pre"
    )
    resp = client.post("/api/v1/evaluation", json=req_newline.model_dump(mode="json"))
    
    # Then: Should NOT match (Safe) because ^exact$ does not match "exact\n" in re2 default mode
    assert resp.json()["is_safe"] is True
