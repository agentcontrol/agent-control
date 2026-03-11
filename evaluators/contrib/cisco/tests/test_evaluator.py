import pytest
from pydantic import ValidationError

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
    assert "raw" not in (res.metadata or {})


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


def test_missing_api_key_raises_on_init(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_DEFENSE_API_KEY", raising=False)

    cfg = CiscoAIDefenseConfig()
    with pytest.raises(ValueError, match="Missing Cisco AI Defense API key"):
        CiscoAIDefenseEvaluator(cfg)


@pytest.mark.asyncio
async def test_missing_is_safe_uses_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(self: AIDefenseClient, **kwargs):
        return {"severity": "LOW"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", fake, raising=True)

    cfg = CiscoAIDefenseConfig(on_error="allow")
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("text")
    assert res.matched is False
    assert res.error == "Cisco AI Defense response missing 'is_safe'"
    assert res.metadata and res.metadata.get("fallback_action") == "allow"
    assert "raw" not in (res.metadata or {})


@pytest.mark.asyncio
async def test_include_raw_response_success_and_missing_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    # Success path includes raw when flag is True
    success_payload = {"is_safe": True, "severity": "LOW", "classifications": {"a": 1}}

    async def success(self: AIDefenseClient, **kwargs):
        return success_payload

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", success, raising=True)

    cfg = CiscoAIDefenseConfig(include_raw_response=True)
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("ok")
    assert res.matched is False
    assert res.metadata and res.metadata.get("classifications") == {"a": 1}
    assert res.metadata.get("raw") == success_payload

    # Missing is_safe path includes raw when flag is True
    async def no_bool(self: AIDefenseClient, **kwargs):
        return {"severity": "MEDIUM"}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", no_bool, raising=True)

    cfg2 = CiscoAIDefenseConfig(include_raw_response=True, on_error="allow")
    ev2 = CiscoAIDefenseEvaluator(cfg2)
    res2 = await ev2.evaluate("x")
    assert res2.matched is False
    assert res2.metadata and res2.metadata.get("fallback_action") == "allow"
    assert "raw" in res2.metadata


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
async def test_on_error_allow_fail_open_sets_error_field(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(self: AIDefenseClient, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", boom, raising=True)

    cfg = CiscoAIDefenseConfig(on_error="allow")
    ev = CiscoAIDefenseEvaluator(cfg)
    res = await ev.evaluate("anything")
    assert res.matched is False
    assert res.error == "network down"
    assert res.metadata and res.metadata.get("fallback_action") == "allow"


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


@pytest.mark.asyncio
async def test_dict_input_prefers_input_field_over_python_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def capture(self: AIDefenseClient, messages, **_):
        captured["messages"] = messages
        return {"is_safe": True}

    monkeypatch.setattr(AIDefenseClient, "chat_inspect", capture, raising=True)

    cfg = CiscoAIDefenseConfig(messages_strategy="single", payload_field="input")
    ev = CiscoAIDefenseEvaluator(cfg)
    _ = await ev.evaluate({"input": "hello world", "extra": "ignored"})
    assert captured["messages"] == [{"role": "user", "content": "hello world"}]


def test_on_error_validation() -> None:
    """on_error must be either 'allow' or 'deny'."""
    # Valid values
    cfg_allow = CiscoAIDefenseConfig(on_error="allow")
    assert cfg_allow.on_error == "allow"

    cfg_deny = CiscoAIDefenseConfig(on_error="deny")
    assert cfg_deny.on_error == "deny"

    # Invalid value should raise ValidationError
    with pytest.raises(ValidationError):
        CiscoAIDefenseConfig(on_error="invalid")
