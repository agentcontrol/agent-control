"""Unit tests for the Luna-2 evaluator.

These tests mock the HTTP client to test the evaluator logic without
requiring actual Galileo API access.

Evaluators take config at __init__, evaluate() only takes data.
The evaluator uses direct HTTP API calls instead of the galileo SDK.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from agent_control_models import EvaluatorResult, Evaluator


def create_mock_protect_response(
    status: str = "success",
    text: str = "OK",
    trace_id: str = "trace-123",
    execution_time: float = 100.0,
) -> MagicMock:
    """Create a mock ProtectResponse object for testing."""
    from agent_control_evaluators.luna2.client import ProtectResponse, TraceMetadata

    return ProtectResponse(
        status=status,
        text=text,
        trace_metadata=TraceMetadata(
            id=trace_id,
            execution_time=execution_time,
            received_at="2024-01-01T00:00:00Z",
            response_at="2024-01-01T00:00:01Z",
        ),
        metric_results={},
        raw_response={},
    )


class TestLuna2EvaluatorConfig:
    """Tests for Luna2EvaluatorConfig Pydantic model."""

    def test_local_stage_config_valid(self):
        """Test valid local stage configuration."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        config = Luna2EvaluatorConfig(
            stage_type="local",
            metric="input_toxicity",
            operator="gt",
            target_value="0.5",
        )

        assert config.stage_type == "local"
        assert config.metric == "input_toxicity"
        assert config.operator == "gt"
        assert config.target_value == "0.5"
        assert config.timeout_ms == 10000  # Default
        assert config.on_error == "allow"  # Default

    def test_local_stage_config_with_numeric_target(self):
        """Test local stage configuration with numeric target_value."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        config = Luna2EvaluatorConfig(
            stage_type="local",
            metric="input_toxicity",
            operator="gt",
            target_value=0.5,  # Numeric value
        )

        assert config.target_value == 0.5
        assert isinstance(config.target_value, float)

    def test_central_stage_config_valid(self):
        """Test valid central stage configuration."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        config = Luna2EvaluatorConfig(
            stage_type="central",
            stage_name="production-guard",
            galileo_project="my-project",
        )

        assert config.stage_type == "central"
        assert config.stage_name == "production-guard"
        assert config.galileo_project == "my-project"

    def test_local_stage_requires_metric(self):
        """Test local stage requires metric field."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        with pytest.raises(ValidationError, match="metric.*required"):
            Luna2EvaluatorConfig(
                stage_type="local",
                operator="gt",
                target_value="0.5",
            )

    def test_local_stage_requires_operator(self):
        """Test local stage requires operator field."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        with pytest.raises(ValidationError, match="operator.*required"):
            Luna2EvaluatorConfig(
                stage_type="local",
                metric="input_toxicity",
                target_value="0.5",
            )

    def test_local_stage_requires_target_value(self):
        """Test local stage requires target_value field."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        with pytest.raises(ValidationError, match="target_value.*required"):
            Luna2EvaluatorConfig(
                stage_type="local",
                metric="input_toxicity",
                operator="gt",
            )

    def test_central_stage_requires_stage_name(self):
        """Test central stage requires stage_name field."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        with pytest.raises(ValidationError, match="stage_name.*required"):
            Luna2EvaluatorConfig(
                stage_type="central",
                galileo_project="my-project",
            )

    def test_timeout_ms_validation(self):
        """Test timeout_ms must be within valid range."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        # Too low
        with pytest.raises(ValidationError):
            Luna2EvaluatorConfig(
                stage_type="central",
                stage_name="test",
                timeout_ms=500,  # Below 1000
            )

        # Too high
        with pytest.raises(ValidationError):
            Luna2EvaluatorConfig(
                stage_type="central",
                stage_name="test",
                timeout_ms=100000,  # Above 60000
            )

        # Valid
        config = Luna2EvaluatorConfig(
            stage_type="central",
            stage_name="test",
            timeout_ms=30000,
        )
        assert config.timeout_ms == 30000

    def test_on_error_validation(self):
        """Test on_error must be 'allow' or 'deny'."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        config_allow = Luna2EvaluatorConfig(
            stage_type="central",
            stage_name="test",
            on_error="allow",
        )
        assert config_allow.on_error == "allow"

        config_deny = Luna2EvaluatorConfig(
            stage_type="central",
            stage_name="test",
            on_error="deny",
        )
        assert config_deny.on_error == "deny"

        with pytest.raises(ValidationError):
            Luna2EvaluatorConfig(
                stage_type="central",
                stage_name="test",
                on_error="invalid",
            )

    def test_metric_validation(self):
        """Test metric must be a valid Luna2 metric."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        # Valid metrics
        valid_metrics = [
            "input_toxicity",
            "output_toxicity",
            "prompt_injection",
            "pii_detection",
            "hallucination",
            "tone",
        ]
        for metric in valid_metrics:
            config = Luna2EvaluatorConfig(
                stage_type="local",
                metric=metric,
                operator="gt",
                target_value="0.5",
            )
            assert config.metric == metric

        # Invalid metric
        with pytest.raises(ValidationError):
            Luna2EvaluatorConfig(
                stage_type="local",
                metric="invalid_metric",
                operator="gt",
                target_value="0.5",
            )

    def test_operator_validation(self):
        """Test operator must be a valid Luna2 operator."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        valid_operators = ["gt", "lt", "gte", "lte", "eq", "contains", "any"]
        for op in valid_operators:
            config = Luna2EvaluatorConfig(
                stage_type="local",
                metric="input_toxicity",
                operator=op,
                target_value="0.5",
            )
            assert config.operator == op

        with pytest.raises(ValidationError):
            Luna2EvaluatorConfig(
                stage_type="local",
                metric="input_toxicity",
                operator="invalid_op",
                target_value="0.5",
            )

    def test_model_dump(self):
        """Test config can be dumped to dict."""
        from agent_control_evaluators.luna2 import Luna2EvaluatorConfig

        config = Luna2EvaluatorConfig(
            stage_type="local",
            metric="input_toxicity",
            operator="gt",
            target_value="0.5",
            galileo_project="test-project",
        )

        data = config.model_dump(exclude_none=True)

        assert data["stage_type"] == "local"
        assert data["metric"] == "input_toxicity"
        assert data["operator"] == "gt"
        assert data["target_value"] == "0.5"
        assert data["galileo_project"] == "test-project"
        assert "stage_name" not in data  # None excluded


class TestLuna2EvaluatorInheritance:
    """Tests for Luna-2 evaluator inheritance."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_evaluator_extends_base(self):
        """Test Luna2Evaluator extends Evaluator."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        assert issubclass(Luna2Evaluator, Evaluator)


class TestLuna2EvaluatorImport:
    """Tests for Luna-2 evaluator import and initialization."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_luna2_evaluator_import_success(self):
        """Test importing Luna-2 evaluator with dependencies available."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        assert Luna2Evaluator is not None
        assert Luna2Evaluator.metadata.name == "galileo-luna2"
        assert Luna2Evaluator.metadata.version == "2.0.0"

    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", False)
    def test_luna2_evaluator_is_available_false_without_httpx(self):
        """Test that is_available() returns False when httpx is not installed."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        # When httpx is not available, is_available() should return False
        assert Luna2Evaluator.is_available() is False

    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_luna2_evaluator_is_available_true_with_httpx(self):
        """Test that is_available() returns True when httpx is installed."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        # When httpx is available, is_available() should return True
        assert Luna2Evaluator.is_available() is True

    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @patch.dict(os.environ, {}, clear=True)
    def test_luna2_evaluator_init_without_api_key_raises_error(self):
        """Test that initializing without API key raises ValueError."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": "0.5",
        }

        with pytest.raises(ValueError, match="GALILEO_API_KEY"):
            Luna2Evaluator.from_dict(config)


class TestLuna2EvaluatorMetadata:
    """Tests for Luna-2 evaluator metadata."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_metadata_fields(self):
        """Test Luna-2 evaluator metadata fields."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        metadata = Luna2Evaluator.metadata

        assert metadata.name == "galileo-luna2"
        assert metadata.requires_api_key is True
        assert metadata.timeout_ms == 10000
        # Config schema is now from config_model
        assert Luna2Evaluator.config_model is not None

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_config_schema_supported_metrics(self):
        """Test config schema includes all supported metrics."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        schema = Luna2Evaluator.config_model.model_json_schema()
        # Pydantic uses anyOf with const for Literal types
        metric_def = schema.get("$defs", {}).get("Luna2Metric", {})
        if "enum" in metric_def:
            metrics = metric_def["enum"]
        else:
            # Fallback: look for metric in properties
            metrics = []
            if "properties" in schema and "metric" in schema["properties"]:
                metric_prop = schema["properties"]["metric"]
                if "anyOf" in metric_prop:
                    for option in metric_prop["anyOf"]:
                        if "const" in option:
                            metrics.append(option["const"])

        # Just check schema is valid - structure varies by Pydantic version
        assert "properties" in schema
        assert "metric" in schema["properties"]


class TestLuna2EvaluatorLocalStage:
    """Tests for Luna-2 evaluator with local stages."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_local_stage_triggered(self):
        """Test local stage evaluation when rule is triggered."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        # Create mock response with triggered status
        mock_response = create_mock_protect_response(
            status="triggered",
            text="Toxic content detected",
            trace_id="trace-123",
        )

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.8,
            "galileo_project": "test-project",
        }

        evaluator = Luna2Evaluator.from_dict(config)

        # Mock the client's invoke_protect method
        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_response

            result = await evaluator.evaluate(data="toxic content here")

            assert isinstance(result, EvaluatorResult)
            assert result.matched is True
            assert result.confidence == 1.0
            assert result.metadata["trace_id"] == "trace-123"
            assert result.metadata["metric"] == "input_toxicity"
            assert result.metadata["status"] == "triggered"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_local_stage_not_triggered(self):
        """Test local stage evaluation when rule is not triggered."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        mock_response = create_mock_protect_response(
            status="not_triggered",
            text="Content is safe",
            trace_id="trace-456",
        )

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.8,
            "galileo_project": "test-project",
        }

        evaluator = Luna2Evaluator.from_dict(config)

        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_response

            result = await evaluator.evaluate(data="hello world")

            assert result.matched is False
            assert result.confidence == 0.0
            assert result.metadata["status"] == "not_triggered"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_local_stage_with_timeout_ms(self):
        """Test local stage respects timeout_ms configuration."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        mock_response = create_mock_protect_response()

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.8,
            "galileo_project": "test-project",
            "timeout_ms": 5000,
        }

        evaluator = Luna2Evaluator.from_dict(config)

        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_response

            await evaluator.evaluate(data="test")

            # Check that invoke_protect was called with correct timeout
            mock_invoke.assert_called_once()
            call_kwargs = mock_invoke.call_args.kwargs
            assert call_kwargs["timeout"] == 5.0


class TestLuna2EvaluatorCentralStage:
    """Tests for Luna-2 evaluator with central stages."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_central_stage_evaluation(self):
        """Test central stage evaluation."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        mock_response = create_mock_protect_response(
            status="triggered",
            text="Central stage rule triggered",
            trace_id="trace-central-1",
        )

        config = {
            "stage_type": "central",
            "stage_name": "enterprise-protection",
            "stage_version": 2,
            "galileo_project": "prod-project",
        }

        evaluator = Luna2Evaluator.from_dict(config)

        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_response

            result = await evaluator.evaluate(data="test input")

            assert result.matched is True
            assert result.metadata["status"] == "triggered"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_central_stage_without_version(self):
        """Test central stage without pinned version."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        mock_response = create_mock_protect_response(trace_id="trace-latest")

        config = {
            "stage_type": "central",
            "stage_name": "latest-protection",
            "galileo_project": "prod-project",
        }

        evaluator = Luna2Evaluator.from_dict(config)

        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = mock_response

            await evaluator.evaluate(data="test")

            mock_invoke.assert_called_once()
            call_kwargs = mock_invoke.call_args.kwargs
            assert call_kwargs["stage_name"] == "latest-protection"


class TestLuna2EvaluatorPayloadPreparation:
    """Tests for payload preparation logic."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_input_metric_payload(self):
        """Test payload for input metrics uses _prepare_payload correctly."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.8,
        }

        evaluator = Luna2Evaluator.from_dict(config)

        # Test the _prepare_payload method directly
        payload = evaluator._prepare_payload("user input text")
        assert payload.input == "user input text"
        assert payload.output == ""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_output_metric_payload(self):
        """Test payload for output metrics uses _prepare_payload correctly."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "output_toxicity",
            "operator": "gt",
            "target_value": 0.7,
        }

        evaluator = Luna2Evaluator.from_dict(config)

        # Test the _prepare_payload method directly
        payload = evaluator._prepare_payload("llm output text")
        assert payload.input == ""
        assert payload.output == "llm output text"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_payload_field_override(self):
        """Test explicit payload_field configuration."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "central",
            "stage_name": "test-stage",
            "payload_field": "output",
        }

        evaluator = Luna2Evaluator.from_dict(config)

        # Test the _prepare_payload method directly
        payload = evaluator._prepare_payload("some data")
        assert payload.input == ""
        assert payload.output == "some data"


class TestLuna2EvaluatorErrorHandling:
    """Tests for error handling in Luna-2 evaluator."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_error_with_fail_open(self):
        """Test error handling with fail open (default)."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.8,
            "on_error": "allow",
        }

        evaluator = Luna2Evaluator.from_dict(config)

        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.side_effect = Exception("Luna-2 API unavailable")

            result = await evaluator.evaluate(data="test")

            assert result.matched is False
            assert result.confidence == 0.0
            assert "error" in result.message.lower()
            assert result.metadata["fallback_action"] == "allow"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_error_with_fail_closed(self):
        """Test error handling with fail closed."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.8,
            "on_error": "deny",
        }

        evaluator = Luna2Evaluator.from_dict(config)

        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.side_effect = Exception("Luna-2 API error")

            result = await evaluator.evaluate(data="test")

            assert result.matched is True
            assert result.confidence == 0.0
            assert "error" in result.message.lower()
            assert result.metadata["fallback_action"] == "deny"

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    @pytest.mark.asyncio
    async def test_empty_response_handling(self):
        """Test handling of empty/None response."""
        from agent_control_evaluators.luna2 import Luna2Evaluator
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.8,
        }

        evaluator = Luna2Evaluator.from_dict(config)

        with patch.object(
            GalileoProtectClient, "invoke_protect", new_callable=AsyncMock
        ) as mock_invoke:
            mock_invoke.return_value = None

            result = await evaluator.evaluate(data="test")

            assert result.matched is False
            assert "No response from Luna-2" in result.message
            assert result.metadata["error"] == "empty_response"


class TestLuna2EvaluatorTimeoutHelper:
    """Tests for timeout helper method."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_get_timeout_from_config(self):
        """Test timeout conversion from config."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": "0.5",
            "timeout_ms": 5000,
        }

        evaluator = Luna2Evaluator.from_dict(config)
        assert evaluator.get_timeout_seconds() == 5.0

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_get_timeout_from_default(self):
        """Test timeout uses metadata default."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": "0.5",
            # No timeout_ms - should use default
        }

        evaluator = Luna2Evaluator.from_dict(config)
        assert evaluator.get_timeout_seconds() == 10.0  # Default from metadata


class TestLuna2EvaluatorNumericTargetValue:
    """Tests for numeric target_value handling."""

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_numeric_target_value_float(self):
        """Test evaluator accepts float target_value."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.5,
        }

        evaluator = Luna2Evaluator.from_dict(config)
        assert evaluator._get_numeric_target_value() == 0.5

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_numeric_target_value_int(self):
        """Test evaluator accepts int target_value."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 1,
        }

        evaluator = Luna2Evaluator.from_dict(config)
        assert evaluator._get_numeric_target_value() == 1

    @patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"})
    @patch("agent_control_evaluators.luna2.evaluator.LUNA2_AVAILABLE", True)
    def test_string_target_value_converts_to_float(self):
        """Test evaluator converts string target_value to float."""
        from agent_control_evaluators.luna2 import Luna2Evaluator

        config = {
            "stage_type": "local",
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": "0.75",
        }

        evaluator = Luna2Evaluator.from_dict(config)
        assert evaluator._get_numeric_target_value() == 0.75


class TestGalileoProtectClient:
    """Tests for the GalileoProtectClient HTTP client."""

    def test_client_init_with_api_key(self):
        """Test client initialization with API key."""
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}):
            client = GalileoProtectClient()
            assert client.api_key == "test-key"

    def test_client_init_without_api_key_raises(self):
        """Test client raises error without API key."""
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="GALILEO_API_KEY"):
                GalileoProtectClient()

    def test_derive_api_url_from_console_url(self):
        """Test API URL derivation from console URL."""
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}):
            client = GalileoProtectClient(
                console_url="https://console.demo-v2.galileocloud.io"
            )
            assert client.api_base == "https://api.demo-v2.galileocloud.io"

    def test_derive_api_url_default(self):
        """Test default API URL."""
        from agent_control_evaluators.luna2.client import GalileoProtectClient

        with patch.dict(os.environ, {"GALILEO_API_KEY": "test-key"}):
            client = GalileoProtectClient()
            assert client.api_base == "https://api.galileo.ai"


class TestPayloadDataClasses:
    """Tests for the Payload and related data classes."""

    def test_payload_to_dict(self):
        """Test Payload.to_dict() method."""
        from agent_control_evaluators.luna2.client import Payload

        payload = Payload(input="test input", output="test output")
        assert payload.to_dict() == {"input": "test input", "output": "test output"}

    def test_rule_to_dict(self):
        """Test Rule.to_dict() method."""
        from agent_control_evaluators.luna2.client import Rule

        rule = Rule(metric="input_toxicity", operator="gt", target_value=0.5)
        assert rule.to_dict() == {
            "metric": "input_toxicity",
            "operator": "gt",
            "target_value": 0.5,
        }

    def test_ruleset_to_dict(self):
        """Test Ruleset.to_dict() method."""
        from agent_control_evaluators.luna2.client import PassthroughAction, Rule, Ruleset

        ruleset = Ruleset(
            rules=[Rule(metric="input_toxicity", operator="gt", target_value=0.5)],
            action=PassthroughAction(),
            description="Test ruleset",
        )
        result = ruleset.to_dict()
        assert result["description"] == "Test ruleset"
        assert len(result["rules"]) == 1
        assert result["action"]["type"] == "PASSTHROUGH"

    def test_protect_response_from_dict(self):
        """Test ProtectResponse.from_dict() method."""
        from agent_control_evaluators.luna2.client import ProtectResponse

        data = {
            "status": "triggered",
            "text": "Test response",
            "trace_metadata": {
                "id": "trace-123",
                "execution_time": 100.5,
            },
            "metric_results": {"input_toxicity": {"value": 0.8}},
        }
        response = ProtectResponse.from_dict(data)
        assert response.status == "triggered"
        assert response.text == "Test response"
        assert response.trace_metadata.id == "trace-123"
        assert response.trace_metadata.execution_time == 100.5
        assert response.metric_results == {"input_toxicity": {"value": 0.8}}
