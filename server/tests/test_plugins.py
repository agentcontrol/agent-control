"""Tests for plugin system via server endpoints.

Tests:
1. Define a simple evaluator plugin (string match)
2. Use it in /evaluation endpoint successfully
3. Get it back from /plugins endpoint
4. Test validation for custom config
"""

import uuid
from typing import Any

import pytest
from agent_control_models import (
    EvaluationRequest,
    EvaluatorResult,
    LlmCall,
    PluginEvaluator,
    PluginMetadata,
    get_plugin,
    register_plugin,
)
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from .utils import create_and_assign_policy

# =============================================================================
# Test Plugin Definition
# =============================================================================


class StringMatchConfig(BaseModel):
    """Config for string match plugin."""

    target: str = Field(..., description="Target string to match")
    case_sensitive: bool = Field(default=True, description="Case-sensitive matching")
    match_type: str = Field(
        default="contains",
        description="Match type: 'contains', 'exact', or 'startswith'",
    )


class StringMatchPlugin(PluginEvaluator[StringMatchConfig]):
    """Simple string matching plugin for testing."""

    metadata = PluginMetadata(
        name="test-string-match",
        version="1.0.0",
        description="Simple string matching for tests",
        timeout_ms=5000,
    )
    config_model = StringMatchConfig

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Check if data contains/matches target string."""
        data_str = str(data) if data is not None else ""
        target = self.config.target

        if not self.config.case_sensitive:
            data_str = data_str.lower()
            target = target.lower()

        if self.config.match_type == "exact":
            matched = data_str == target
        elif self.config.match_type == "startswith":
            matched = data_str.startswith(target)
        else:  # contains
            matched = target in data_str

        return EvaluatorResult(
            matched=matched,
            confidence=1.0,
            message=f"String match ({self.config.match_type}): '{self.config.target}'",
            metadata={
                "target": self.config.target,
                "match_type": self.config.match_type,
                "case_sensitive": self.config.case_sensitive,
            },
        )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def register_test_plugin():
    """Register test plugin before each test, cleanup after."""
    # Register - may already be registered from previous test
    existing = get_plugin("test-string-match")
    if existing is None:
        register_plugin(StringMatchPlugin)
    yield
    # Don't clear - built-in plugins need to stay registered


# =============================================================================
# Test: Plugin Discovery Endpoint
# =============================================================================


class TestPluginsEndpoint:
    """Tests for GET /api/v1/plugins endpoint."""

    def test_list_plugins_returns_builtin(self, client: TestClient):
        """Test that built-in plugins are listed."""
        # Given: Server is running with built-in plugins registered

        # When: Requesting the plugins list
        resp = client.get("/api/v1/plugins")

        # Then: Built-in plugins should be present
        assert resp.status_code == 200
        plugins = resp.json()
        assert "regex" in plugins
        assert "list" in plugins

    def test_list_plugins_returns_test_plugin(self, client: TestClient):
        """Test that our registered test plugin appears."""
        # Given: Test plugin is registered (via fixture)

        # When: Requesting the plugins list
        resp = client.get("/api/v1/plugins")

        # Then: Test plugin appears with correct metadata
        assert resp.status_code == 200
        plugins = resp.json()
        assert "test-string-match" in plugins
        plugin_info = plugins["test-string-match"]
        assert plugin_info["name"] == "test-string-match"
        assert plugin_info["version"] == "1.0.0"
        assert plugin_info["description"] == "Simple string matching for tests"
        assert plugin_info["timeout_ms"] == 5000

    def test_plugin_config_schema_exposed(self, client: TestClient):
        """Test that plugin config schema is returned."""
        # Given: Test plugin is registered with a typed config model

        # When: Requesting the plugins list
        resp = client.get("/api/v1/plugins")
        plugins = resp.json()

        # Then: Config schema includes all properties
        schema = plugins["test-string-match"]["config_schema"]
        assert "properties" in schema
        assert "target" in schema["properties"]
        assert schema["properties"]["target"]["type"] == "string"
        assert "case_sensitive" in schema["properties"]
        assert "match_type" in schema["properties"]

    def test_plugin_schema_shows_required_fields(self, client: TestClient):
        """Test that required fields are marked in schema."""
        # Given: Test plugin has 'target' as a required field (no default)

        # When: Requesting the plugins list
        resp = client.get("/api/v1/plugins")
        plugins = resp.json()

        # Then: 'target' is listed in required fields
        schema = plugins["test-string-match"]["config_schema"]
        assert "required" in schema
        assert "target" in schema["required"]


# =============================================================================
# Test: Plugin Usage in /evaluation
# =============================================================================


class TestPluginEvaluation:
    """Tests for using custom plugins via /evaluation endpoint."""

    def test_evaluation_with_custom_plugin_match(self, client: TestClient):
        """Test custom plugin matches correctly via /evaluation."""
        # Given: Agent with policy using test-string-match plugin to block 'forbidden'
        control_data = {
            "description": "Block messages containing 'forbidden'",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "test-string-match",
                "config": {"target": "forbidden", "case_sensitive": True},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, control_name = create_and_assign_policy(
            client, control_data, agent_name="StringMatchAgent"
        )

        # When: Evaluating input containing 'forbidden'
        payload = LlmCall(input="This contains forbidden content", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Request is denied with the control match
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_safe"] is False
        assert len(data["matches"]) == 1
        assert data["matches"][0]["control_name"] == control_name

    def test_evaluation_with_custom_plugin_no_match(self, client: TestClient):
        """Test custom plugin allows non-matching content."""
        # Given: Agent with policy using test-string-match plugin to block 'secret'
        control_data = {
            "description": "Block 'secret'",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "test-string-match",
                "config": {"target": "secret"},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, _ = create_and_assign_policy(
            client, control_data, agent_name="NoMatchAgent"
        )

        # When: Evaluating input that does NOT contain 'secret'
        payload = LlmCall(input="This is safe content", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Request is allowed
        assert resp.status_code == 200
        assert resp.json()["is_safe"] is True

    def test_evaluation_case_insensitive(self, client: TestClient):
        """Test case-insensitive matching option."""
        # Given: Agent with case-insensitive plugin blocking 'PASSWORD'
        control_data = {
            "description": "Block 'PASSWORD' case-insensitive",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "test-string-match",
                "config": {"target": "PASSWORD", "case_sensitive": False},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, _ = create_and_assign_policy(
            client, control_data, agent_name="CaseInsensitiveAgent"
        )

        # When: Evaluating input with lowercase 'password'
        payload = LlmCall(input="my password is hunter2", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Request is denied (case-insensitive match)
        assert resp.status_code == 200
        assert resp.json()["is_safe"] is False

    def test_evaluation_exact_match(self, client: TestClient):
        """Test exact string matching mode."""
        # Given: Agent with plugin in exact match mode for 'STOP'
        control_data = {
            "description": "Block exact 'STOP'",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "test-string-match",
                "config": {"target": "STOP", "match_type": "exact"},
            },
            "action": {"decision": "deny"},
        }
        agent_uuid, _ = create_and_assign_policy(
            client, control_data, agent_name="ExactMatchAgent"
        )

        # When: Evaluating exact match 'STOP'
        payload_exact = LlmCall(input="STOP", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload_exact, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Exact match is denied
        assert resp.json()["is_safe"] is False

        # When: Evaluating input containing 'STOP' but not exactly
        payload_contains = LlmCall(input="Please STOP now", output=None)
        req = EvaluationRequest(
            agent_uuid=agent_uuid, payload=payload_contains, check_stage="pre"
        )
        resp = client.post("/api/v1/evaluation", json=req.model_dump(mode="json"))

        # Then: Non-exact match is allowed
        assert resp.json()["is_safe"] is True


# =============================================================================
# Test: Config Validation
# =============================================================================


class TestPluginConfigValidation:
    """Tests for plugin configuration validation."""

    def test_missing_required_config_field_rejected_at_save(self, client: TestClient):
        """Test that missing required field is rejected when saving control."""
        # Given: Control data with 'target' omitted (required field)
        control_data = {
            "description": "Invalid - missing target",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "test-string-match",
                "config": {"case_sensitive": True},  # Missing 'target'
            },
            "action": {"decision": "deny"},
        }
        control_name = f"control-{uuid.uuid4()}"
        resp = client.put("/api/v1/controls", json={"name": control_name})
        assert resp.status_code == 200
        control_id = resp.json()["control_id"]

        # When: Attempting to save the invalid control data
        resp = client.put(
            f"/api/v1/controls/{control_id}/data", json={"data": control_data}
        )

        # Then: Server rejects with validation error
        assert resp.status_code == 422

    def test_invalid_config_type_rejected_at_save(self, client: TestClient):
        """Test that wrong config type is rejected when saving control."""
        # Given: Control data with wrong type for case_sensitive (string instead of bool)
        control_data = {
            "description": "Invalid - wrong type for case_sensitive",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "test-string-match",
                "config": {
                    "target": "test",
                    "case_sensitive": "not-a-bool",
                },
            },
            "action": {"decision": "deny"},
        }
        control_name = f"control-{uuid.uuid4()}"
        resp = client.put("/api/v1/controls", json={"name": control_name})
        control_id = resp.json()["control_id"]

        # When: Attempting to save the control with invalid type
        resp = client.put(
            f"/api/v1/controls/{control_id}/data", json={"data": control_data}
        )

        # Then: Server either rejects (422)
        assert resp.status_code == 422

    def test_unknown_plugin_rejected_at_save(self, client: TestClient):
        """Test that unknown plugin name is rejected at save time."""
        # Given: Control referencing a nonexistent plugin
        control_data = {
            "description": "Invalid - unknown plugin",
            "enabled": True,
            "applies_to": "llm_call",
            "check_stage": "pre",
            "selector": {"path": "input"},
            "evaluator": {
                "plugin": "nonexistent-plugin",
                "config": {"whatever": "value"},
            },
            "action": {"decision": "deny"},
        }
        control_name = f"control-{uuid.uuid4()}"
        resp = client.put("/api/v1/controls", json={"name": control_name})
        control_id = resp.json()["control_id"]

        # When: Attempting to save control with unknown plugin
        resp = client.put(
            f"/api/v1/controls/{control_id}/data", json={"data": control_data}
        )

        # Then: Returns 422 with helpful error message
        assert resp.status_code == 422
        assert "unknown plugin" in resp.json()["detail"].lower()


# =============================================================================
# Test: Plugin Instantiation
# =============================================================================


class TestPluginInstantiation:
    """Tests for plugin from_dict() factory method."""

    def test_from_dict_with_all_fields(self):
        """Test creating plugin from dict with all config fields."""
        # Given: Config dict with all fields specified
        config = {
            "target": "test",
            "case_sensitive": False,
            "match_type": "startswith",
        }

        # When: Creating plugin via from_dict
        plugin = StringMatchPlugin.from_dict(config)

        # Then: All config values are set correctly
        assert plugin.config.target == "test"
        assert plugin.config.case_sensitive is False
        assert plugin.config.match_type == "startswith"

    def test_from_dict_with_defaults(self):
        """Test creating plugin with default values."""
        # Given: Config dict with only required field

        # When: Creating plugin via from_dict
        plugin = StringMatchPlugin.from_dict({"target": "hello"})

        # Then: Defaults are applied for optional fields
        assert plugin.config.target == "hello"
        assert plugin.config.case_sensitive is True  # default
        assert plugin.config.match_type == "contains"  # default

    def test_from_dict_validates(self):
        """Test that from_dict validates config."""
        # Given: Empty config dict (missing required 'target')

        # When/Then: Creating plugin raises validation error
        with pytest.raises(Exception):  # ValidationError
            StringMatchPlugin.from_dict({})

    @pytest.mark.asyncio
    async def test_evaluate_returns_result(self):
        """Test evaluate returns proper EvaluatorResult."""
        # Given: Plugin configured to match 'needle'
        plugin = StringMatchPlugin.from_dict({"target": "needle"})

        # When: Evaluating data containing 'needle'
        result = await plugin.evaluate("haystack with needle inside")

        # Then: Returns EvaluatorResult with match
        assert isinstance(result, EvaluatorResult)
        assert result.matched is True
        assert result.confidence == 1.0
        assert "needle" in result.message
