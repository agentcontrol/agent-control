import pytest

from agent_control_evaluator_cisco.ai_defense import (
    CiscoAIDefenseEvaluator,
    CiscoAIDefenseConfig,
)
from agent_control_evaluator_cisco.ai_defense.client import AIDefenseClient


@pytest.fixture(autouse=True)
def _env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_DEFENSE_API_KEY", "test-key")


@pytest.mark.asyncio
async def test_none_input_returns_no_data() -> None:
    cfg = CiscoAIDefenseConfig()
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate(None)
    assert res.matched is False
    assert res.error is None


@pytest.mark.asyncio
async def test_is_safe_false_triggers_match(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat_inspect(self: AIDefenseClient, **kwargs):
        return {"is_safe": False, "severity": "HIGH"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake_chat_inspect, raising=True)

    cfg = CiscoAIDefenseConfig()
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("bad content")
    assert res.matched is True
    assert res.metadata and res.metadata.get("severity") == "HIGH"


@pytest.mark.asyncio
async def test_is_safe_true_is_not_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_chat_inspect(self: AIDefenseClient, **kwargs):
        return {"is_safe": True, "severity": "LOW"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake_chat_inspect, raising=True)

    cfg = CiscoAIDefenseConfig()
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("ok content")
    assert res.matched is False
    assert res.metadata and res.metadata.get("severity") == "LOW"


@pytest.mark.asyncio
async def test_on_error_deny_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(self: AIDefenseClient, **kwargs):
        raise RuntimeError("network error")

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", boom, raising=True)

    cfg = CiscoAIDefenseConfig(on_error="deny")
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("anything")
    assert res.matched is True  # fail-closed
    assert res.metadata and res.metadata.get("fallback_action") == "deny"


@pytest.mark.asyncio
async def test_missing_api_key_respects_on_error_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_DEFENSE_API_KEY", raising=False)

    cfg = CiscoAIDefenseConfig(on_error="deny")
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("payload")
    assert res.matched is True
    assert res.error is None
    assert res.metadata and res.metadata.get("fallback_action") == "deny"


@pytest.mark.asyncio
async def test_missing_api_key_respects_on_error_allow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_DEFENSE_API_KEY", raising=False)

    cfg = CiscoAIDefenseConfig(on_error="allow")
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("payload")
    assert res.matched is False
    assert isinstance(res.error, str) and res.error
    assert res.metadata and res.metadata.get("fallback_action") == "allow"


@pytest.mark.asyncio
async def test_missing_is_safe_uses_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AIDefenseClient, **kwargs):
        return {"severity": "LOW"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake, raising=True)

    cfg = CiscoAIDefenseConfig(on_error="allow")
    ev = CiscoAIDefenseEvaluator(cfg)
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

    cfg = CiscoAIDefenseConfig(api_url="https://example.com/custom/chat")
    ev = CiscoAIDefenseEvaluator(cfg)
    _ = await ev.evaluate("text")
    assert captured["endpoint_url"] == "https://example.com/custom/chat"


@pytest.mark.asyncio
async def test_client_reuse_and_recreate_on_key_change(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AIDefenseClient, **_):
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake, raising=True)

    monkeypatch.setenv("AI_DEFENSE_API_KEY", "k1")
    cfg = CiscoAIDefenseConfig()
    ev = CiscoAIDefenseEvaluator(cfg)
    _ = await ev.evaluate("text1")
    assert ev._client is not None
    first_client = ev._client
    assert first_client.api_key == "k1"

    _ = await ev.evaluate("text2")
    assert ev._client is first_client

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

    cfg = CiscoAIDefenseConfig(messages_strategy="history")
    ev = CiscoAIDefenseEvaluator(cfg)
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

    cfg = CiscoAIDefenseConfig(payload_field="output")
    ev = CiscoAIDefenseEvaluator(cfg)
    _ = await ev.evaluate("some output text")
    assert captured["messages"][0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_messages_strategy_single_synthesizes_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def capture(self: AIDefenseClient, messages, **_):
        captured["messages"] = messages
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", capture, raising=True)

    cfg = CiscoAIDefenseConfig(messages_strategy="single", payload_field="input")
    ev = CiscoAIDefenseEvaluator(cfg)
    _ = await ev.evaluate("hello world")
    assert captured["messages"] == [{"role": "user", "content": "hello world"}]

