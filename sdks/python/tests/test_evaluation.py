"""Tests for check_evaluation behavior."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from agent_control import evaluation
from agent_control.evaluation import EvaluationResult
from pydantic import ValidationError


@pytest.mark.asyncio
async def test_check_evaluation_requires_step_name_before_server_call():
    """Typed request validation should reject steps without a name before server call."""

    client = MagicMock()
    client.http_client = AsyncMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValidationError):
        await evaluation.check_evaluation(
            client=client,
            agent_name=UUID("00000000-0000-0000-0000-000000000001"),
            step={"type": "llm", "input": "hello"},
            stage="pre",
        )

    client.http_client.post.assert_not_called()


@pytest.mark.asyncio
async def test_check_evaluation_returns_result_model():
    """check_evaluation returns a parsed EvaluationResult."""
    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"is_safe": True, "confidence": 0.75, "reason": "ok"}

    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock(return_value=DummyResponse())

    result = await evaluation.check_evaluation(
        client=client,
        agent_name="Agent-Example_01",
        step={"type": "llm", "name": "chat", "input": "hello"},
        stage="pre",
    )

    assert result.is_safe is True
    assert result.confidence == 0.75
    assert result.reason == "ok"
    client.http_client.post.assert_awaited_once_with(
        "/api/v1/evaluation",
        json={
            "agent_name": "agent-example_01",
            "step": {
                "type": "llm",
                "name": "chat",
                "input": "hello",
                "output": None,
                "context": None,
            },
            "stage": "pre",
            "target_type": None,
            "target_id": None,
        },
        headers=None,
    )


@pytest.mark.asyncio
async def test_evaluate_controls_requires_server_url():
    """evaluate_controls should require server_url to be configured."""
    with patch("agent_control.state.server_url", None):
        with pytest.raises(RuntimeError, match="Server URL not configured"):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_name="test-bot",
            )


@pytest.mark.asyncio
async def test_evaluate_controls_with_explicit_agent_name(monkeypatch):
    """evaluate_controls should call check_evaluation_with_local."""
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            result = await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_name="test-bot",
            )

    assert result.is_safe is True
    assert result.confidence == 1.0
    mock_check.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_controls_with_context(monkeypatch):
    """evaluate_controls should pass context through to evaluation."""
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"):
        with patch("agent_control.state.api_key", None):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                context={"user_id": "123"},
                stage="pre",
                agent_name="test-bot",
            )

    assert mock_check.call_args is not None


@pytest.mark.asyncio
async def test_evaluate_controls_uses_session_api_key_header(monkeypatch):
    """evaluate_controls should pass init's API-key header into the client."""
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"), patch(
        "agent_control.state.api_key", "test-key"
    ), patch("agent_control.state.api_key_header", "Galileo-API-Key"):
        await evaluation.evaluate_controls(
            step_name="chat",
            input="hello",
            stage="pre",
            agent_name="test-bot",
        )

    client = mock_check.call_args.kwargs["client"]
    assert client.api_key_header == "Galileo-API-Key"


@pytest.mark.asyncio
async def test_check_evaluation_forwards_target_context():
    """When target_type and target_id are supplied, they are forwarded to the server."""

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"is_safe": True, "confidence": 1.0}

    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock(return_value=DummyResponse())

    await evaluation.check_evaluation(
        client=client,
        agent_name="Agent-Example_01",
        step={"type": "llm", "name": "chat", "input": "hello"},
        stage="pre",
        target_type="env",
        target_id="prod",
    )

    sent = client.http_client.post.await_args.kwargs["json"]
    assert sent["target_type"] == "env"
    assert sent["target_id"] == "prod"


@pytest.mark.asyncio
async def test_evaluate_controls_forwards_target_context(monkeypatch):
    """evaluate_controls passes target_type/target_id into check_evaluation_with_local.

    Per the V1 contract, per-call target must match the session target.
    The test pins forwarding behavior with state.target_type/state.target_id
    set to the same values as the per-call args.
    """
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"), patch(
        "agent_control.state.api_key", None
    ), patch("agent_control._state.state.target_type", "env"), patch(
        "agent_control._state.state.target_id", "prod"
    ):
        await evaluation.evaluate_controls(
            step_name="chat",
            input="hello",
            stage="pre",
            agent_name="test-bot",
            target_type="env",
            target_id="prod",
        )

    kwargs = mock_check.call_args.kwargs
    assert kwargs["target_type"] == "env"
    assert kwargs["target_id"] == "prod"


@pytest.mark.asyncio
async def test_check_evaluation_does_not_default_target_from_state():
    """``check_evaluation`` is not session-bound.

    The caller supplies its own client; the helper does not consult
    ``init()``-time session state. A caller that omits target params gets
    a non-target-bearing request even when the session has a target set —
    session-target enforcement lives on the session-bound entry point
    (``evaluate_controls``).
    """

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"is_safe": True, "confidence": 1.0}

    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock(return_value=DummyResponse())

    with patch("agent_control._state.state.target_type", "env"), patch(
        "agent_control._state.state.target_id", "prod"
    ):
        await evaluation.check_evaluation(
            client=client,
            agent_name="Agent-Example_01",
            step={"type": "llm", "name": "chat", "input": "hello"},
            stage="pre",
        )

    sent = client.http_client.post.await_args.kwargs["json"]
    assert sent["target_type"] is None
    assert sent["target_id"] is None


@pytest.mark.asyncio
async def test_check_evaluation_partial_target_pair_rejected():
    """Per-call target params must be supplied together."""
    client = MagicMock()
    client.http_client = MagicMock()
    client.http_client.post = AsyncMock()

    with pytest.raises(ValueError):
        await evaluation.check_evaluation(
            client=client,
            agent_name="Agent-Example_01",
            step={"type": "llm", "name": "chat", "input": "hello"},
            stage="pre",
            target_type="env",  # target_id missing
        )


@pytest.mark.asyncio
async def test_evaluate_controls_per_call_target_must_match_session_target(monkeypatch):
    """A per-call target that disagrees with init()'s target is rejected.

    The cached controls are fetched for the session target; accepting a
    mismatched per-call target would drive stale local-first evaluation.
    """
    mock_check = AsyncMock(return_value=EvaluationResult(is_safe=True, confidence=1.0))
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)
    session_agent = MagicMock(name="session_agent")

    with patch("agent_control.state.server_url", "http://localhost:8000"), patch(
        "agent_control.state.api_key", None
    ), patch("agent_control._state.state.current_agent", session_agent), patch(
        "agent_control._state.state.target_type", "env"
    ), patch("agent_control._state.state.target_id", "prod"):
        with pytest.raises(ValueError, match="must match the target context fixed at init"):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_name="test-bot",
                target_type="env",
                target_id="staging",  # session is "prod"
            )


@pytest.mark.asyncio
async def test_evaluate_controls_no_target_session_rejects_per_call_target(monkeypatch):
    """An init() without target context is itself a fixed (None, None) session.

    The session's cached controls were fetched without target context, so a
    per-call target that supplies an explicit (target_type, target_id) would
    drive stale local-first evaluation. Reject the mismatch.
    """
    mock_check = AsyncMock(return_value=EvaluationResult(is_safe=True, confidence=1.0))
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)
    session_agent = MagicMock(name="session_agent")

    with patch("agent_control.state.server_url", "http://localhost:8000"), patch(
        "agent_control.state.api_key", None
    ), patch("agent_control._state.state.current_agent", session_agent), patch(
        "agent_control._state.state.target_type", None
    ), patch("agent_control._state.state.target_id", None):
        with pytest.raises(
            ValueError, match="must match the target context fixed at init"
        ):
            await evaluation.evaluate_controls(
                step_name="chat",
                input="hello",
                stage="pre",
                agent_name="test-bot",
                target_type="env",
                target_id="prod",
            )


@pytest.mark.asyncio
async def test_evaluate_controls_defaults_target_from_state(monkeypatch):
    """``evaluate_controls`` falls back to state target when params omitted."""
    mock_result = EvaluationResult(is_safe=True, confidence=1.0)
    mock_check = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(evaluation, "check_evaluation_with_local", mock_check)

    with patch("agent_control.state.server_url", "http://localhost:8000"), patch(
        "agent_control.state.api_key", None
    ), patch("agent_control._state.state.target_type", "env"), patch(
        "agent_control._state.state.target_id", "prod"
    ):
        await evaluation.evaluate_controls(
            step_name="chat",
            input="hello",
            stage="pre",
            agent_name="test-bot",
        )

    kwargs = mock_check.call_args.kwargs
    assert kwargs["target_type"] == "env"
    assert kwargs["target_id"] == "prod"
