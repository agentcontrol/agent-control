"""Tests for reconstructed control-execution events in SDK evaluation flows."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_control import evaluation
from agent_control.evaluation import (
    _ControlAdapter,
    _build_server_control_lookup,
    _has_applicable_prefiltered_server_controls,
    _merge_results,
)
from agent_control.evaluation_events import (
    build_control_execution_events,
    enqueue_observability_events,
    map_applies_to,
)
from agent_control.telemetry.trace_context import (
    clear_trace_context_provider,
    set_trace_context_provider,
)
from agent_control_models import ControlDefinition


class TestMapAppliesTo:
    def test_maps_tool_to_tool_call(self):
        assert map_applies_to("tool") == "tool_call"

    def test_maps_llm_to_llm_call(self):
        assert map_applies_to("llm") == "llm_call"


class TestMergeResults:
    def _make_response(self, **kwargs):
        from agent_control_models import EvaluationResponse

        defaults = {
            "is_safe": True,
            "confidence": 1.0,
            "reason": None,
            "matches": None,
            "errors": None,
            "non_matches": None,
        }
        defaults.update(kwargs)
        return EvaluationResponse(**defaults)

    def _make_match(self, control_id, control_name="ctrl", action="observe", matched=True):
        from agent_control_models import ControlMatch, EvaluatorResult

        return ControlMatch(
            control_id=control_id,
            control_name=control_name,
            action=action,
            result=EvaluatorResult(matched=matched, confidence=0.9),
        )

    def test_combines_matches_errors_and_non_matches(self):
        local = self._make_response(
            matches=[self._make_match(1)],
            errors=[self._make_match(2, matched=False)],
        )
        server = self._make_response(non_matches=[self._make_match(3, matched=False)])

        result = _merge_results(local, server)

        assert [match.control_id for match in result.matches or []] == [1]
        assert [match.control_id for match in result.errors or []] == [2]
        assert [match.control_id for match in result.non_matches or []] == [3]


class TestEvaluationHelpers:
    def test_build_server_control_lookup_skips_unparseable_controls(self):
        lookup = _build_server_control_lookup(
            [
                {
                    "id": 1,
                    "name": "ctrl-1",
                    "control": {
                        "condition": {
                            "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                            "selector": {"path": "input"},
                        },
                        "action": {"decision": "observe"},
                        "execution": "server",
                    },
                },
                {
                    "id": 2,
                    "name": "ctrl-2",
                    "control": {
                        "condition": {"selector": {"path": "input"}},
                        "action": {"decision": "observe"},
                        "execution": "server",
                    },
                },
            ]
        )

        assert list(lookup.keys()) == [1]

    def test_has_applicable_prefiltered_server_controls_returns_true_for_malformed_payload(self):
        from agent_control_models import EvaluationRequest

        request = EvaluationRequest(
            agent_name="agent-000000000001",
            step={"type": "llm", "name": "test-step", "input": "hello"},
            stage="pre",
        )

        assert _has_applicable_prefiltered_server_controls(
            [
                {
                    "id": 1,
                    "name": "bad-server-ctrl",
                    "control": {
                        "condition": {"selector": {"path": "input"}},
                        "action": {"decision": "observe"},
                        "execution": "server",
                    },
                }
            ],
            request,
        ) is True






class TestBuildControlExecutionEvents:
    def _make_control(self, id, name, condition):
        return _ControlAdapter(
            id=id,
            name=name,
            control=ControlDefinition(
                execution="sdk",
                condition=condition,
                action={"decision": "allow"},
            ),
        )

    def _make_request(self, step_type="llm"):
        from agent_control_models import EvaluationRequest

        step_input = {"query": "hello"} if step_type == "tool" else "hello"
        return EvaluationRequest(
            agent_name="agent-000000000001",
            step={"type": step_type, "name": "test-step", "input": step_input},
            stage="pre",
        )

    def _make_match(self, control_id, control_name="ctrl", action="allow", matched=True):
        from agent_control_models import ControlMatch, EvaluatorResult

        return ControlMatch(
            control_id=control_id,
            control_name=control_name,
            action=action,
            result=EvaluatorResult(matched=matched, confidence=0.9),
        )

    def _make_response(self, matches=None, errors=None, non_matches=None):
        from agent_control_models import EvaluationResponse

        return EvaluationResponse(
            is_safe=not bool(matches),
            confidence=1.0 if not matches else 0.5,
            matches=matches,
            errors=errors,
            non_matches=non_matches,
        )

    def test_builds_events_with_trace_context(self):
        response = self._make_response(matches=[self._make_match(1, "ctrl-1")])
        request = self._make_request()
        control_lookup = {
            1: self._make_control(
                1,
                "ctrl-1",
                {
                    "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    "selector": {"path": "input"},
                },
            ).control
        }

        events = build_control_execution_events(
            response,
            request,
            control_lookup,
            "trace123",
            "span456",
            "test-agent",
        )

        assert len(events) == 1
        event = events[0]
        assert event.trace_id == "trace123"
        assert event.span_id == "span456"
        assert event.agent_name == "test-agent"
        assert event.evaluator_name == "regex"
        assert event.selector_path == "input"

    def test_composite_control_uses_representative_observability_identity(self):
        response = self._make_response(non_matches=[self._make_match(1, "ctrl-1", matched=False)])
        request = self._make_request()
        control_lookup = {
            1: self._make_control(
                1,
                "ctrl-1",
                {
                    "and": [
                        {
                            "selector": {"path": "input"},
                            "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                        },
                        {
                            "selector": {"path": "output"},
                            "evaluator": {"name": "regex", "config": {"pattern": "done"}},
                        },
                    ]
                },
            ).control
        }

        events = build_control_execution_events(
            response,
            request,
            control_lookup,
            "trace123",
            "span456",
            "test-agent",
        )

        assert len(events) == 1
        event = events[0]
        assert event.evaluator_name == "regex"
        assert event.selector_path == "input"
        assert event.metadata["primary_evaluator"] == "regex"
        assert event.metadata["primary_selector_path"] == "input"
        assert event.metadata["leaf_count"] == 2
        assert event.metadata["all_evaluators"] == ["regex"]
        assert event.metadata["all_selector_paths"] == ["input", "output"]

    def test_preserves_error_message_parity_by_result_category(self):
        from agent_control_models import ControlMatch, EvaluationResponse, EvaluatorResult

        request = self._make_request()
        control_lookup = {
            1: self._make_control(
                1,
                "ctrl-1",
                {
                    "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    "selector": {"path": "input"},
                },
            ).control
        }
        response = EvaluationResponse(
            is_safe=False,
            confidence=0.5,
            matches=[
                ControlMatch(
                    control_id=1,
                    control_name="ctrl-1",
                    action="allow",
                    result=EvaluatorResult(
                        matched=True,
                        confidence=0.9,
                        metadata={"server_error_message": "match-error"},
                    ),
                )
            ],
            errors=[
                ControlMatch(
                    control_id=1,
                    control_name="ctrl-1",
                    action="allow",
                    result=EvaluatorResult(matched=False, confidence=0.2, error="eval-error"),
                )
            ],
            non_matches=[
                ControlMatch(
                    control_id=1,
                    control_name="ctrl-1",
                    action="allow",
                    result=EvaluatorResult(matched=False, confidence=0.1, error="ignored-error"),
                )
            ],
        )

        events = build_control_execution_events(
            response,
            request,
            control_lookup,
            "trace123",
            "span456",
            "test-agent",
        )

        assert events[0].error_message is None
        assert events[1].error_message == "eval-error"
        assert events[2].error_message is None

    def test_enqueue_observability_events_uses_existing_batcher(self):
        from agent_control_models import ControlExecutionEvent

        events = [
            ControlExecutionEvent(
                trace_id="a" * 32,
                span_id="b" * 16,
                agent_name="agent-000000000001",
                control_id=1,
                control_name="ctrl-1",
                check_stage="pre",
                applies_to="llm_call",
                action="allow",
                matched=False,
                confidence=1.0,
            )
        ]

        with patch("agent_control.evaluation_events.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation_events.add_event") as mock_add:
            enqueue_observability_events(events)

        mock_add.assert_called_once_with(events[0])


class TestCheckEvaluationWithLocal:
    def teardown_method(self) -> None:
        clear_trace_context_provider()

    @pytest.mark.asyncio
    async def test_delivers_local_events_in_oss_mode(self):
        from agent_control_models import ControlMatch, EvaluationResponse, EvaluatorResult, Step

        mock_response = EvaluationResponse(
            is_safe=True,
            confidence=1.0,
            non_matches=[
                ControlMatch(
                    control_id=1,
                    control_name="test-ctrl",
                    action="observe",
                    result=EvaluatorResult(matched=False, confidence=0.1),
                )
            ],
        )
        mock_engine = MagicMock()
        mock_engine.process = AsyncMock(return_value=mock_response)

        controls = [{
            "id": 1,
            "name": "test-ctrl",
            "control": {
                "condition": {
                    "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    "selector": {"path": "input"},
                },
                "action": {"decision": "observe"},
                "execution": "sdk",
            },
        }]

        client = MagicMock()
        client.http_client = AsyncMock()
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine), \
             patch("agent_control.evaluation.list_evaluators", return_value=["regex"]), \
             patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            result = await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
                trace_id="abc123",
                span_id="def456",
                event_agent_name="test-agent",
            )
        mock_enqueue.assert_called_once()
        delivered_events = mock_enqueue.call_args.args[0]
        assert len(delivered_events) == 1
        assert delivered_events[0].trace_id == "abc123"
        assert delivered_events[0].span_id == "def456"
        assert result.non_matches is not None
        assert len(result.non_matches) == 1

    @pytest.mark.asyncio
    async def test_resolves_provider_trace_context_for_local_events(self):
        from agent_control_models import ControlMatch, EvaluationResponse, EvaluatorResult, Step

        mock_response = EvaluationResponse(
            is_safe=True,
            confidence=1.0,
            non_matches=[
                ControlMatch(
                    control_id=1,
                    control_name="test-ctrl",
                    action="allow",
                    result=EvaluatorResult(matched=False, confidence=0.1),
                )
            ],
        )
        mock_engine = MagicMock()
        mock_engine.process = AsyncMock(return_value=mock_response)
        controls = [{
            "id": 1,
            "name": "test-ctrl",
            "control": {
                "condition": {
                    "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    "selector": {"path": "input"},
                },
                "action": {"decision": "observe"},
                "execution": "sdk",
            },
        }]

        client = MagicMock()
        client.http_client = AsyncMock()
        step = Step(type="llm", name="test-step", input="hello")
        set_trace_context_provider(lambda: {"trace_id": "a" * 32, "span_id": "b" * 16})

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine), \
             patch("agent_control.evaluation.list_evaluators", return_value=["regex"]), \
             patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
            )

        delivered_events = mock_enqueue.call_args.args[0]
        assert delivered_events[0].trace_id == "a" * 32
        assert delivered_events[0].span_id == "b" * 16

    @pytest.mark.asyncio
    async def test_forwards_provider_trace_headers_to_server_when_ids_omitted(self):
        """Server POST should resolve trace headers from the provider when omitted."""
        from agent_control_models import Step

        controls = [{
            "id": 1,
            "name": "server-ctrl",
            "control": {
                "condition": {
                    "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    "selector": {"path": "input"},
                },
                "action": {"decision": "deny"},
                "execution": "server",
            },
        }]

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = {
            "is_safe": True,
            "confidence": 1.0,
            "matches": None,
            "errors": None,
            "non_matches": None,
        }
        mock_http_response.raise_for_status = MagicMock()

        client = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_http_response)
        step = Step(type="llm", name="test-step", input="hello")
        set_trace_context_provider(
            lambda: {
                "trace_id": "c" * 32,
                "span_id": "d" * 16,
            }
        )

        with patch("agent_control.evaluation.list_evaluators", return_value=["regex"]):
            await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
            )

        call_kwargs = client.http_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers["X-Trace-Id"] == "c" * 32
        assert headers["X-Span-Id"] == "d" * 16


class TestCheckEvaluation:

    @pytest.mark.asyncio
    async def test_check_evaluation_enqueues_reconstructed_server_events_when_observability_enabled(self):
        from agent_control_models import Step

        mock_http_response = MagicMock()
        mock_http_response.raise_for_status = MagicMock()
        mock_http_response.json.return_value = {
            "is_safe": True,
            "confidence": 0.9,
            "matches": None,
            "errors": None,
            "non_matches": [
                {
                    "control_id": 1,
                    "control_name": "ctrl-1",
                    "action": "observe",
                    "control_execution_id": "ce-1",
                    "result": {"matched": False, "confidence": 0.1},
                }
            ],
        }

        client = MagicMock()
        client.base_url = "http://localhost:8000"
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_http_response)
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.is_observability_enabled", return_value=True),              patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            result = await evaluation.check_evaluation(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
            )

        call_kwargs = client.http_client.post.call_args.kwargs
        assert call_kwargs["headers"] is None
        mock_enqueue.assert_called_once()
        assert result.is_safe is True
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_skips_local_event_reconstruction_when_observability_disabled(self):
        from agent_control_models import EvaluationResponse, Step

        controls = [{
            "id": 1,
            "name": "local-ctrl",
            "control": {
                "condition": {
                    "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                    "selector": {"path": "input"},
                },
                "action": {"decision": "allow"},
                "execution": "sdk",
            },
        }]

        mock_response = EvaluationResponse(is_safe=True, confidence=1.0)
        mock_engine = MagicMock()
        mock_engine.process = AsyncMock(return_value=mock_response)

        client = MagicMock()
        client.http_client = AsyncMock()
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine),              patch("agent_control.evaluation.list_evaluators", return_value=["regex"]),              patch("agent_control.evaluation.is_observability_enabled", return_value=False),              patch("agent_control.evaluation.build_control_execution_events") as mock_build,              patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            result = await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
            )

        mock_build.assert_not_called()
        mock_enqueue.assert_not_called()
        assert result.is_safe is True
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_check_evaluation_skips_enqueue_when_observability_disabled(self):
        from agent_control_models import Step

        mock_http_response = MagicMock()
        mock_http_response.raise_for_status = MagicMock()
        mock_http_response.json.return_value = {
            "is_safe": True,
            "confidence": 0.9,
            "matches": None,
            "errors": None,
            "non_matches": None,
        }

        client = MagicMock()
        client.base_url = "http://localhost:8000"
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_http_response)
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.is_observability_enabled", return_value=False),              patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            result = await evaluation.check_evaluation(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
            )

        call_kwargs = client.http_client.post.call_args.kwargs
        assert call_kwargs["headers"] is None
        mock_enqueue.assert_not_called()
        assert result.is_safe is True
        assert result.confidence == 0.9


# =============================================================================
# Merged Event Creation
# =============================================================================


class TestMergedEventCreation:
    """Tests for SDK-side merged event reconstruction and enqueueing."""

    @pytest.mark.asyncio
    async def test_merged_event_mode_enqueues_reconstructed_local_and_server_events_once(self):
        from agent_control_models import ControlMatch, EvaluationResponse, EvaluatorResult, Step

        local_response = EvaluationResponse(
            is_safe=True,
            confidence=1.0,
            matches=[
                ControlMatch(
                    control_id=1,
                    control_name="local-ctrl",
                    action="allow",
                    result=EvaluatorResult(matched=False, confidence=0.8),
                )
            ],
        )
        server_response = {
            "is_safe": True,
            "confidence": 0.9,
            "matches": [
                {
                    "control_id": 2,
                    "control_name": "server-ctrl",
                    "action": "allow",
                    "control_execution_id": "ce-server",
                    "result": {"matched": False, "confidence": 0.4},
                }
            ],
            "errors": None,
            "non_matches": None,
        }

        controls = [
            {
                "id": 1,
                "name": "local-ctrl",
                "control": {
                    "condition": {
                        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                        "selector": {"path": "input"},
                    },
                    "action": {"decision": "allow"},
                    "execution": "sdk",
                },
            },
            {
                "id": 2,
                "name": "server-ctrl",
                "control": {
                    "condition": {
                        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                        "selector": {"path": "input"},
                    },
                    "action": {"decision": "allow"},
                    "execution": "server",
                },
            },
        ]

        mock_engine = MagicMock()
        mock_engine.process = AsyncMock(return_value=local_response)
        mock_http_response = MagicMock()
        mock_http_response.raise_for_status = MagicMock()
        mock_http_response.json.return_value = server_response

        client = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(return_value=mock_http_response)
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine), \
             patch("agent_control.evaluation.list_evaluators", return_value=["regex"]), \
             patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            result = await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
                trace_id="abc123",
                span_id="def456",
                event_agent_name="test-agent",
            )
        mock_enqueue.assert_called_once()
        merged_events = mock_enqueue.call_args.args[0]
        assert len(merged_events) == 2
        assert {event.control_id for event in merged_events} == {1, 2}
        assert result.matches is not None
        assert len(result.matches) == 2

    @pytest.mark.asyncio
    async def test_merged_event_mode_enqueues_local_events_before_reraising_server_failure(self):
        from agent_control_models import ControlMatch, EvaluationResponse, EvaluatorResult, Step

        local_response = EvaluationResponse(
            is_safe=True,
            confidence=1.0,
            matches=[
                ControlMatch(
                    control_id=1,
                    control_name="local-ctrl",
                    action="allow",
                    result=EvaluatorResult(matched=False, confidence=0.8),
                )
            ],
        )

        controls = [
            {
                "id": 1,
                "name": "local-ctrl",
                "control": {
                    "condition": {
                        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                        "selector": {"path": "input"},
                    },
                    "action": {"decision": "allow"},
                    "execution": "sdk",
                },
            },
            {
                "id": 2,
                "name": "server-ctrl",
                "control": {
                    "condition": {
                        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                        "selector": {"path": "input"},
                    },
                    "action": {"decision": "allow"},
                    "execution": "server",
                },
            },
        ]

        mock_engine = MagicMock()
        mock_engine.process = AsyncMock(return_value=local_response)

        client = MagicMock()
        client.http_client = AsyncMock()
        client.http_client.post = AsyncMock(side_effect=RuntimeError("server unavailable"))
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine),              patch("agent_control.evaluation.list_evaluators", return_value=["regex"]), patch("agent_control.evaluation.is_observability_enabled", return_value=True),              patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            with pytest.raises(RuntimeError, match="server unavailable"):
                await evaluation.check_evaluation_with_local(
                    client=client,
                    agent_name="agent-000000000001",
                    step=step,
                    stage="pre",
                    controls=controls,
                    trace_id="abc123",
                    span_id="def456",
                    event_agent_name="test-agent",
                )

        mock_enqueue.assert_called_once()
        local_events = mock_enqueue.call_args.args[0]
        assert len(local_events) == 1
        assert local_events[0].control_id == 1
        assert local_events[0].trace_id == "abc123"
        assert local_events[0].span_id == "def456"

    @pytest.mark.asyncio
    async def test_merged_event_mode_enqueues_only_local_events_when_no_server_controls_apply(self):
        from agent_control_models import ControlMatch, EvaluationResponse, EvaluatorResult, Step

        local_response = EvaluationResponse(
            is_safe=True,
            confidence=1.0,
            matches=[
                ControlMatch(
                    control_id=1,
                    control_name="local-ctrl",
                    action="allow",
                    result=EvaluatorResult(matched=True, confidence=0.8),
                )
            ],
        )
        controls = [
            {
                "id": 1,
                "name": "local-ctrl",
                "control": {
                    "condition": {
                        "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                        "selector": {"path": "input"},
                    },
                    "action": {"decision": "allow"},
                    "execution": "sdk",
                },
            }
        ]

        mock_engine = MagicMock()
        mock_engine.process = AsyncMock(return_value=local_response)
        client = MagicMock()
        client.http_client = AsyncMock()
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine), \
             patch("agent_control.evaluation.list_evaluators", return_value=["regex"]), \
             patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.enqueue_observability_events") as mock_enqueue:
            result = await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
                trace_id="abc123",
                span_id="def456",
                event_agent_name="test-agent",
            )

        client.http_client.post.assert_not_called()
        mock_enqueue.assert_called_once()
        merged_events = mock_enqueue.call_args.args[0]
        assert len(merged_events) == 1
        assert merged_events[0].control_id == 1
        assert result.matches is not None
        assert len(result.matches) == 1


# =============================================================================
# control_decorators non_matches dict conversion
# =============================================================================


class TestControlDecoratorsNonMatches:
    """Tests for non_matches dict conversion in control_decorators._evaluate."""

    @pytest.mark.asyncio
    async def test_non_matches_populated_in_stats(self):
        """non_matches should be properly converted to dicts for stats tracking."""
        from agent_control.control_decorators import ControlContext

        result = {
            "is_safe": True,
            "confidence": 1.0,
            "matches": None,
            "errors": None,
            "non_matches": [
                {
                    "control_id": 1,
                    "control_name": "ctrl-1",
                    "action": "observe",
                    "result": {"matched": False, "confidence": 0.1},
                },
                {
                    "control_id": 2,
                    "control_name": "ctrl-2",
                    "action": "deny",
                    "result": {"matched": False, "confidence": 0.2},
                },
            ],
        }

        ctx = ControlContext(
            agent_name="test-agent",
            server_url="http://localhost:8000",
            func=lambda: None,
            args=(),
            kwargs={},
            trace_id="trace123",
            span_id="span456",
            start_time=0,
        )

        ctx._update_stats(result)
        assert ctx.total_executions == 2
        assert ctx.total_non_matches == 2
        assert ctx.total_matches == 0
        assert ctx.total_errors == 0

    def test_legacy_advisory_matches_collapse_into_observe_stats(self):
        """Legacy advisory action names should not leak into local action counters."""
        from agent_control.control_decorators import ControlContext

        result = {
            "is_safe": True,
            "confidence": 1.0,
            "matches": [
                {
                    "control_id": 1,
                    "control_name": "ctrl-allow",
                    "action": "allow",
                    "result": {"matched": True, "confidence": 0.3},
                },
                {
                    "control_id": 2,
                    "control_name": "ctrl-warn",
                    "action": "warn",
                    "result": {"matched": True, "confidence": 0.4},
                },
                {
                    "control_id": 3,
                    "control_name": "ctrl-log",
                    "action": "log",
                    "result": {"matched": True, "confidence": 0.5},
                },
                {
                    "control_id": 4,
                    "control_name": "ctrl-observe",
                    "action": "observe",
                    "result": {"matched": True, "confidence": 0.6},
                },
            ],
            "errors": None,
            "non_matches": None,
        }

        ctx = ControlContext(
            agent_name="test-agent",
            server_url="http://localhost:8000",
            func=lambda: None,
            args=(),
            kwargs={},
            trace_id="trace123",
            span_id="span456",
            start_time=0,
        )

        ctx._update_stats(result)
        assert ctx.total_executions == 4
        assert ctx.total_matches == 4
        assert ctx.total_non_matches == 0
        assert ctx.total_errors == 0
        assert ctx.actions == {"observe": 4}
