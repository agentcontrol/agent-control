"""Tests for observability updates: event emission, non_matches propagation, applies_to mapping."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from agent_control import evaluation
from agent_control.evaluation import _map_applies_to, _merge_results


# =============================================================================
# _map_applies_to tests
# =============================================================================


class TestMapAppliesTo:
    """Tests for _map_applies_to helper."""

    def test_maps_tool_to_tool_call(self):
        assert _map_applies_to("tool") == "tool_call"

    def test_maps_llm_to_llm_call(self):
        assert _map_applies_to("llm") == "llm_call"

    def test_maps_unknown_to_llm_call(self):
        """Unknown types default to llm_call (matches server pattern)."""
        assert _map_applies_to("unknown") == "llm_call"
        assert _map_applies_to("") == "llm_call"


# =============================================================================
# _merge_results tests
# =============================================================================


class TestMergeResults:
    """Tests for _merge_results combining non_matches."""

    def _make_response(self, **kwargs):
        """Create a mock EvaluationResponse."""
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

    def _make_match(self, control_id, control_name="ctrl", action="allow", matched=True):
        from agent_control_models import ControlMatch, EvaluatorResult
        return ControlMatch(
            control_id=control_id,
            control_name=control_name,
            action=action,
            result=EvaluatorResult(matched=matched, confidence=0.9),
        )

    def test_combines_non_matches(self):
        """non_matches from both sides should be combined."""
        nm1 = self._make_match(1, "ctrl-1", matched=False)
        nm2 = self._make_match(2, "ctrl-2", matched=False)

        local = self._make_response(non_matches=[nm1])
        server = self._make_response(non_matches=[nm2])

        result = _merge_results(local, server)
        assert result.non_matches is not None
        assert len(result.non_matches) == 2
        ids = {nm.control_id for nm in result.non_matches}
        assert ids == {1, 2}

    def test_non_matches_none_when_both_empty(self):
        local = self._make_response()
        server = self._make_response()
        result = _merge_results(local, server)
        assert result.non_matches is None

    def test_non_matches_from_one_side(self):
        nm = self._make_match(1, matched=False)
        local = self._make_response(non_matches=[nm])
        server = self._make_response()
        result = _merge_results(local, server)
        assert result.non_matches is not None
        assert len(result.non_matches) == 1

    def test_still_combines_matches_and_errors(self):
        m1 = self._make_match(1, "m1")
        m2 = self._make_match(2, "m2")
        e1 = self._make_match(3, "e1", matched=False)

        local = self._make_response(matches=[m1], errors=[e1])
        server = self._make_response(matches=[m2])

        result = _merge_results(local, server)
        assert len(result.matches) == 2
        assert len(result.errors) == 1


# =============================================================================
# _emit_local_events tests
# =============================================================================


class TestEmitLocalEvents:
    """Tests for _emit_local_events helper."""

    def _make_control_adapter(self, id, name, evaluator_name="regex", selector_path="input"):
        """Create a _ControlAdapter for testing."""
        from agent_control.evaluation import _ControlAdapter
        from agent_control_models import ControlDefinition

        control_def = ControlDefinition(
            execution="sdk",
            evaluator={"name": evaluator_name, "config": {"pattern": "test"}},
            selector={"path": selector_path},
            action={"decision": "deny"},
        )
        return _ControlAdapter(id=id, name=name, control=control_def)

    def _make_response(self, matches=None, errors=None, non_matches=None):
        from agent_control_models import EvaluationResponse
        return EvaluationResponse(
            is_safe=not bool(matches),
            confidence=1.0 if not matches else 0.5,
            matches=matches,
            errors=errors,
            non_matches=non_matches,
        )

    def _make_match(self, control_id, control_name="ctrl", action="deny", matched=True):
        from agent_control_models import ControlMatch, EvaluatorResult
        return ControlMatch(
            control_id=control_id,
            control_name=control_name,
            action=action,
            result=EvaluatorResult(matched=matched, confidence=0.9),
        )

    def _make_request(self, step_type="llm"):
        from agent_control_models import EvaluationRequest
        # Tool steps require object input, LLM steps accept string
        step_input = {"query": "hello"} if step_type == "tool" else "hello"
        return EvaluationRequest(
            agent_name="agent-000000000001",
            step={"type": step_type, "name": "test-step", "input": step_input},
            stage="pre",
        )

    def test_emits_events_when_observability_enabled(self):
        """Should call add_event for each match/error/non_match."""
        from agent_control.evaluation import _emit_local_events

        ctrl = self._make_control_adapter(1, "ctrl-1")
        match = self._make_match(1, "ctrl-1")
        non_match = self._make_match(2, "ctrl-2", matched=False)
        response = self._make_response(matches=[match], non_matches=[non_match])
        request = self._make_request()

        with patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.add_event") as mock_add:
            _emit_local_events(
                response, request,
                [ctrl, self._make_control_adapter(2, "ctrl-2")],
                "trace123", "span456", "test-agent",
            )
            assert mock_add.call_count == 2
            # Verify event fields for the match
            event = mock_add.call_args_list[0][0][0]
            assert event.trace_id == "trace123"
            assert event.span_id == "span456"
            assert event.agent_name == "test-agent"
            assert event.matched is True
            assert event.evaluator_name == "regex"
            assert event.selector_path == "input"

    def test_skips_when_observability_disabled(self):
        """Should not call add_event when observability is disabled."""
        from agent_control.evaluation import _emit_local_events

        ctrl = self._make_control_adapter(1, "ctrl-1")
        match = self._make_match(1, "ctrl-1")
        response = self._make_response(matches=[match])
        request = self._make_request()

        with patch("agent_control.evaluation.is_observability_enabled", return_value=False), \
             patch("agent_control.evaluation.add_event") as mock_add:
            _emit_local_events(
                response, request, [ctrl],
                "trace123", "span456", "test-agent",
            )
            mock_add.assert_not_called()

    def test_maps_tool_step_to_tool_call(self):
        """Should set applies_to='tool_call' for tool steps."""
        from agent_control.evaluation import _emit_local_events

        ctrl = self._make_control_adapter(1, "ctrl-1")
        match = self._make_match(1, "ctrl-1")
        response = self._make_response(matches=[match])
        request = self._make_request(step_type="tool")

        with patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.add_event") as mock_add:
            _emit_local_events(
                response, request, [ctrl],
                "trace123", "span456", "test-agent",
            )
            event = mock_add.call_args_list[0][0][0]
            assert event.applies_to == "tool_call"

    def test_uses_fallback_ids_when_trace_context_missing(self):
        """Should emit events with all-zero fallback IDs when trace context is absent."""
        import agent_control.evaluation as eval_mod
        from agent_control.evaluation import (
            _FALLBACK_SPAN_ID,
            _FALLBACK_TRACE_ID,
            _emit_local_events,
        )

        ctrl = self._make_control_adapter(1, "ctrl-1")
        match = self._make_match(1, "ctrl-1")
        response = self._make_response(matches=[match])
        request = self._make_request()

        # Reset the once-only warning flag so the warning fires in this test
        eval_mod._trace_warning_logged = False

        with patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.add_event") as mock_add, \
             patch("agent_control.evaluation._logger") as mock_logger:
            _emit_local_events(
                response, request, [ctrl],
                None, None, "test-agent",
            )
            assert mock_add.call_count == 1
            event = mock_add.call_args_list[0][0][0]
            assert event.trace_id == _FALLBACK_TRACE_ID
            assert event.span_id == _FALLBACK_SPAN_ID
            assert event.trace_id == "0" * 32
            assert event.span_id == "0" * 16
            # Warning should have been logged
            mock_logger.warning.assert_called_once()
            assert "fallback" in mock_logger.warning.call_args[0][0].lower()

    def test_fallback_warning_logged_only_once(self):
        """The missing-trace-context warning should fire only on the first call."""
        import agent_control.evaluation as eval_mod
        from agent_control.evaluation import _emit_local_events

        ctrl = self._make_control_adapter(1, "ctrl-1")
        match = self._make_match(1, "ctrl-1")
        response = self._make_response(matches=[match])
        request = self._make_request()

        eval_mod._trace_warning_logged = False

        with patch("agent_control.evaluation.is_observability_enabled", return_value=True), \
             patch("agent_control.evaluation.add_event"), \
             patch("agent_control.evaluation._logger") as mock_logger:
            _emit_local_events(response, request, [ctrl], None, None, "agent-test-a1")
            _emit_local_events(response, request, [ctrl], None, None, "agent-test-a1")
            assert mock_logger.warning.call_count == 1


# =============================================================================
# check_evaluation_with_local event emission + header forwarding
# =============================================================================


class TestCheckEvaluationWithLocal:
    """Tests for check_evaluation_with_local event emission and non_matches."""

    @pytest.mark.asyncio
    async def test_emits_events_when_trace_context_provided(self):
        """Should emit observability events when trace_id and span_id are passed."""
        from agent_control_models import (
            ControlMatch,
            EvaluationResponse,
            EvaluatorResult,
            Step,
        )

        mock_response = EvaluationResponse(
            is_safe=True,
            confidence=1.0,
            matches=None,
            errors=None,
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
                "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                "selector": {"path": "input"},
                "action": {"decision": "allow"},
                "execution": "sdk",
            },
        }]

        client = MagicMock()
        client.http_client = AsyncMock()
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine), \
             patch("agent_control.evaluation.list_evaluators", return_value=["regex"]), \
             patch("agent_control.evaluation._emit_local_events") as mock_emit:
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

            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][2] is not None  # local_controls
            assert call_args[0][3] == "abc123"  # trace_id
            assert call_args[0][4] == "def456"  # span_id
            assert call_args.kwargs["agent_name"] == "test-agent"

        # Also verify non_matches propagated
        assert result.non_matches is not None
        assert len(result.non_matches) == 1

    @pytest.mark.asyncio
    async def test_emits_events_without_trace_context(self):
        """Should still emit events when trace_id/span_id not provided (fallback IDs)."""
        from agent_control_models import EvaluationResponse, Step

        mock_response = EvaluationResponse(
            is_safe=True, confidence=1.0, matches=None, errors=None, non_matches=None,
        )

        mock_engine = MagicMock()
        mock_engine.process = AsyncMock(return_value=mock_response)

        controls = [{
            "id": 1,
            "name": "test-ctrl",
            "control": {
                "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                "selector": {"path": "input"},
                "action": {"decision": "allow"},
                "execution": "sdk",
            },
        }]

        client = MagicMock()
        client.http_client = AsyncMock()
        step = Step(type="llm", name="test-step", input="hello")

        with patch("agent_control.evaluation.ControlEngine", return_value=mock_engine), \
             patch("agent_control.evaluation.list_evaluators", return_value=["regex"]), \
             patch("agent_control.evaluation._emit_local_events") as mock_emit:
            await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
                # No trace_id/span_id
            )
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][3] is None  # trace_id passed as None
            assert call_args[0][4] is None  # span_id passed as None

    @pytest.mark.asyncio
    async def test_forwards_trace_headers_to_server(self):
        """Server POST should include X-Trace-Id and X-Span-Id headers."""
        from agent_control_models import Step

        # Only server controls, no local controls
        controls = [{
            "id": 1,
            "name": "server-ctrl",
            "control": {
                "evaluator": {"name": "regex", "config": {"pattern": "test"}},
                "selector": {"path": "input"},
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

        with patch("agent_control.evaluation.list_evaluators", return_value=["regex"]):
            await evaluation.check_evaluation_with_local(
                client=client,
                agent_name="agent-000000000001",
                step=step,
                stage="pre",
                controls=controls,
                trace_id="aaaa1111bbbb2222cccc3333dddd4444",
                span_id="eeee5555ffff6666",
            )

        # Verify POST was called with headers
        call_kwargs = client.http_client.post.call_args
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers["X-Trace-Id"] == "aaaa1111bbbb2222cccc3333dddd4444"
        assert headers["X-Span-Id"] == "eeee5555ffff6666"


# =============================================================================
# control_decorators non_matches dict conversion
# =============================================================================


class TestControlDecoratorsNonMatches:
    """Tests for non_matches dict conversion in control_decorators._evaluate."""

    @pytest.mark.asyncio
    async def test_non_matches_populated_in_stats(self):
        """non_matches should be properly converted to dicts for stats tracking."""
        from agent_control.control_decorators import ControlContext, _log_control_evaluations

        # Simulate a result dict with non_matches
        result = {
            "is_safe": True,
            "confidence": 1.0,
            "matches": None,
            "errors": None,
            "non_matches": [
                {
                    "control_id": 1,
                    "control_name": "ctrl-1",
                    "action": "allow",
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
