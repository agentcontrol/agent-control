import pytest

from agent_control_evaluator_ai_defense.chat_inspect import (
    ChatInspectEvaluator,
    ChatInspectEvaluatorConfig,
)
from agent_control_evaluator_ai_defense.chat_inspect.client import AIDefenseClient


@pytest.fixture(autouse=True)
def _env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_DEFENSE_API_KEY", "test-key")


@pytest.mark.asyncio
async def test_none_input_returns_no_data() -> None:
    cfg = ChatInspectEvaluatorConfig()
    ev = ChatInspectEvaluator(cfg)
    res = await ev.evaluate(None)
    assert res.matched is False
    assert res.error is None


@pytest.mark.asyncio
async def test_is_safe_false_triggers_match(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat_inspect(self: AIDefenseClient, **kwargs):
        return {"is_safe": False, "severity": "HIGH"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake_chat_inspect, raising=True)

    cfg = ChatInspectEvaluatorConfig()
    ev = ChatInspectEvaluator(cfg)
    res = await ev.evaluate("bad content")
    assert res.matched is True
    assert res.metadata and res.metadata.get("severity") == "HIGH"


@pytest.mark.asyncio
async def test_is_safe_true_is_not_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat_inspect(self: AIDefenseClient, **kwargs):
        return {"is_safe": True, "severity": "LOW"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake_chat_inspect, raising=True)

    cfg = ChatInspectEvaluatorConfig()
    ev = ChatInspectEvaluator(cfg)
    res = await ev.evaluate("ok content")
    assert res.matched is False
    assert res.metadata and res.metadata.get("severity") == "LOW"


@pytest.mark.asyncio
async def test_on_error_deny_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(self: AIDefenseClient, **kwargs):
        raise RuntimeError("network error")

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", boom, raising=True)

    cfg = ChatInspectEvaluatorConfig(on_error="deny")
    ev = ChatInspectEvaluator(cfg)
    res = await ev.evaluate("anything")
    assert res.matched is True  # fail-closed
    assert res.metadata and res.metadata.get("fallback_action") == "deny"


@pytest.mark.asyncio
async def test_missing_api_key_respects_on_error_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """When API key env is missing, evaluator should honor on_error=deny."""
    # Ensure API key env is absent
    monkeypatch.delenv("AI_DEFENSE_API_KEY", raising=False)

    cfg = ChatInspectEvaluatorConfig(on_error="deny")
    ev = ChatInspectEvaluator(cfg)
    res = await ev.evaluate("payload")
    assert res.matched is True
    assert res.error is None
    assert res.metadata and res.metadata.get("fallback_action") == "deny"


@pytest.mark.asyncio
async def test_missing_api_key_respects_on_error_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    """When API key env is missing, evaluator should honor on_error=allow."""
    # Ensure API key env is absent
    monkeypatch.delenv("AI_DEFENSE_API_KEY", raising=False)

    cfg = ChatInspectEvaluatorConfig(on_error="allow")
    ev = ChatInspectEvaluator(cfg)
    res = await ev.evaluate("payload")
    assert res.matched is False
    assert isinstance(res.error, str) and res.error
    assert res.metadata and res.metadata.get("fallback_action") == "allow"


@pytest.mark.asyncio
async def test_missing_is_safe_uses_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AIDefenseClient, **kwargs):
        return {"severity": "LOW"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake, raising=True)

    cfg = ChatInspectEvaluatorConfig(on_error="allow")
    ev = ChatInspectEvaluator(cfg)
    res = await ev.evaluate("text")
    assert res.matched is False
    assert res.metadata and res.metadata.get("fallback_action") == "allow"


@pytest.mark.asyncio
async def test_api_url_override_used(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def capture(self: AIDefenseClient, **_):
        captured["endpoint_url"] = self.endpoint_url
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", capture, raising=True)

    cfg = ChatInspectEvaluatorConfig(api_url="https://example.com/custom/chat")
    ev = ChatInspectEvaluator(cfg)
    _ = await ev.evaluate("text")
    assert captured["endpoint_url"] == "https://example.com/custom/chat"


@pytest.mark.asyncio
async def test_client_reuse_and_recreate_on_key_change(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AIDefenseClient, **_):
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake, raising=True)

    # Start with key1
    monkeypatch.setenv("AI_DEFENSE_API_KEY", "k1")
    cfg = ChatInspectEvaluatorConfig()
    ev = ChatInspectEvaluator(cfg)
    _ = await ev.evaluate("text1")
    assert ev._client is not None
    first_client = ev._client
    assert first_client.api_key == "k1"

    # Same key should reuse client
    _ = await ev.evaluate("text2")
    assert ev._client is first_client

    # Change key should rebuild client
    monkeypatch.setenv("AI_DEFENSE_API_KEY", "k2")
    _ = await ev.evaluate("text3")
    assert ev._client is not first_client
    assert ev._client is not None and ev._client.api_key == "k2"


@pytest.mark.asyncio
async def test_messages_strategy_history_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def capture(self: AIDefenseClient, messages, **_):
        captured["messages"] = messages
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", capture, raising=True)

    cfg = ChatInspectEvaluatorConfig(messages_strategy="history")
    ev = ChatInspectEvaluator(cfg)
    data = {"messages": [{"role": "user", "content": "hello"}]}
    _ = await ev.evaluate(data)
    assert captured["messages"] == data["messages"]


@pytest.mark.asyncio
async def test_payload_field_output_sets_assistant_role(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def capture(self: AIDefenseClient, messages, **_):
        captured["messages"] = messages
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", capture, raising=True)

    cfg = ChatInspectEvaluatorConfig(payload_field="output")
    ev = ChatInspectEvaluator(cfg)
    _ = await ev.evaluate("some output text")
    assert captured["messages"][0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_messages_strategy_single_synthesizes_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def capture(self: AIDefenseClient, messages, **_):
        captured["messages"] = messages
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", capture, raising=True)

    cfg = ChatInspectEvaluatorConfig(messages_strategy="single", payload_field="input")
    ev = ChatInspectEvaluator(cfg)
    _ = await ev.evaluate("hello world")
    assert captured["messages"] == [{"role": "user", "content": "hello world"}]
