"""Tests for the transaction_policy evaluator."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from agent_control_evaluator_financial_governance.transaction_policy import (
    TransactionPolicyConfig,
    TransactionPolicyEvaluator,
)

# ---------------------------------------------------------------------------
# TransactionPolicyConfig validation tests
# ---------------------------------------------------------------------------


def test_config_currencies_normalized() -> None:
    cfg = TransactionPolicyConfig(allowed_currencies=["usdc", "Usdt"])
    assert cfg.allowed_currencies == ["USDC", "USDT"]


def test_config_defaults_are_permissive() -> None:
    cfg = TransactionPolicyConfig()
    assert cfg.allowed_recipients == []
    assert cfg.blocked_recipients == []
    assert cfg.min_amount == Decimal("0")
    assert cfg.max_amount == Decimal("0")
    assert cfg.allowed_currencies == []


def test_config_max_amount_lt_min_raises() -> None:
    with pytest.raises(ValidationError, match="max_amount"):
        TransactionPolicyConfig(min_amount=Decimal("100"), max_amount=Decimal("10"))


def test_config_max_equals_min_is_valid() -> None:
    cfg = TransactionPolicyConfig(min_amount=Decimal("50"), max_amount=Decimal("50"))
    assert cfg.min_amount == Decimal("50")
    assert cfg.max_amount == Decimal("50")


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _make_evaluator(**kwargs: Any) -> TransactionPolicyEvaluator:
    cfg = TransactionPolicyConfig(**kwargs)
    return TransactionPolicyEvaluator(cfg)


def _tx(
    amount: float = 100.0,
    currency: str = "USDC",
    recipient: str = "0xABC",
    **extra: Any,
) -> dict[str, Any]:
    return {"amount": amount, "currency": currency, "recipient": recipient, **extra}


# ---------------------------------------------------------------------------
# Edge cases: None / non-dict inputs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_data_passes() -> None:
    ev = _make_evaluator(allowed_currencies=["USDC"])
    result = await ev.evaluate(None)
    assert result.matched is False
    assert result.error is None


@pytest.mark.asyncio
async def test_non_dict_data_passes() -> None:
    ev = _make_evaluator(allowed_currencies=["USDC"])
    result = await ev.evaluate(["not", "a", "dict"])
    assert result.matched is False


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_currency_not_matched() -> None:
    """Missing currency is a non-match, NOT an evaluator error."""
    ev = _make_evaluator()
    result = await ev.evaluate({"amount": 10.0, "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None
    assert "currency" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_missing_recipient_not_matched() -> None:
    """Missing recipient is a non-match, NOT an evaluator error."""
    ev = _make_evaluator()
    result = await ev.evaluate({"amount": 10.0, "currency": "USDC"})
    assert result.matched is False
    assert result.error is None
    assert "recipient" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_missing_amount_not_matched() -> None:
    """Missing amount is a non-match, NOT an evaluator error."""
    ev = _make_evaluator()
    result = await ev.evaluate({"currency": "USDC", "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None
    assert "amount" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_non_numeric_amount_not_matched() -> None:
    """Non-numeric amount is a non-match, NOT an evaluator error."""
    ev = _make_evaluator()
    result = await ev.evaluate({"amount": "lots", "currency": "USDC", "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None


@pytest.mark.parametrize("bad_amount", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.asyncio
async def test_non_finite_amount_not_matched(bad_amount: str) -> None:
    ev = _make_evaluator()
    result = await ev.evaluate({"amount": bad_amount, "currency": "USDC", "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None


# ---------------------------------------------------------------------------
# No restrictions configured → everything passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_config_allows_everything() -> None:
    ev = _make_evaluator()
    result = await ev.evaluate(_tx(amount=999_999.0, currency="XYZ", recipient="0xANY"))
    assert result.matched is False


# ---------------------------------------------------------------------------
# Currency allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_currency_not_in_allowlist_is_blocked() -> None:
    ev = _make_evaluator(allowed_currencies=["USDC", "USDT"])
    result = await ev.evaluate(_tx(currency="DAI"))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "currency_not_allowed"


@pytest.mark.asyncio
async def test_currency_in_allowlist_passes() -> None:
    ev = _make_evaluator(allowed_currencies=["USDC", "USDT"])
    result = await ev.evaluate(_tx(currency="USDT"))
    assert result.matched is False


@pytest.mark.asyncio
async def test_currency_allowlist_case_insensitive_in_data() -> None:
    """Currency from incoming data is uppercased before comparison."""
    ev = _make_evaluator(allowed_currencies=["USDC"])
    result = await ev.evaluate(_tx(currency="usdc"))
    assert result.matched is False


# ---------------------------------------------------------------------------
# Recipient blocklist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_recipient_is_denied() -> None:
    ev = _make_evaluator(blocked_recipients=["0xDEAD", "0xBAD"])
    result = await ev.evaluate(_tx(recipient="0xDEAD"))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "recipient_blocked"


@pytest.mark.asyncio
async def test_non_blocked_recipient_passes() -> None:
    ev = _make_evaluator(blocked_recipients=["0xDEAD"])
    result = await ev.evaluate(_tx(recipient="0xGOOD"))
    assert result.matched is False


# ---------------------------------------------------------------------------
# Recipient allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recipient_not_in_allowlist_is_blocked() -> None:
    ev = _make_evaluator(allowed_recipients=["0xALICE", "0xBOB"])
    result = await ev.evaluate(_tx(recipient="0xEVE"))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "recipient_not_allowed"


@pytest.mark.asyncio
async def test_recipient_in_allowlist_passes() -> None:
    ev = _make_evaluator(allowed_recipients=["0xALICE", "0xBOB"])
    result = await ev.evaluate(_tx(recipient="0xBOB"))
    assert result.matched is False


# ---------------------------------------------------------------------------
# Blocklist takes priority over allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_beats_allowlist() -> None:
    """A recipient on the blocklist should be denied even if also allowlisted."""
    ev = _make_evaluator(
        allowed_recipients=["0xALICE"],
        blocked_recipients=["0xALICE"],  # deliberately in both
    )
    result = await ev.evaluate(_tx(recipient="0xALICE"))
    assert result.matched is True
    # Violation should be blocklist (checked first)
    assert result.metadata and result.metadata["violation"] == "recipient_blocked"


# ---------------------------------------------------------------------------
# Amount bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_amount_below_minimum_is_blocked() -> None:
    ev = _make_evaluator(min_amount=Decimal("10"))
    result = await ev.evaluate(_tx(amount=9.99))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "amount_below_minimum"


@pytest.mark.asyncio
async def test_amount_at_minimum_passes() -> None:
    ev = _make_evaluator(min_amount=Decimal("10"))
    result = await ev.evaluate(_tx(amount=10.0))
    assert result.matched is False


@pytest.mark.asyncio
async def test_amount_above_maximum_is_blocked() -> None:
    ev = _make_evaluator(max_amount=Decimal("1000"))
    result = await ev.evaluate(_tx(amount=1000.01))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "amount_exceeds_maximum"


@pytest.mark.asyncio
async def test_amount_at_maximum_passes() -> None:
    ev = _make_evaluator(max_amount=Decimal("1000"))
    result = await ev.evaluate(_tx(amount=1000.0))
    assert result.matched is False


@pytest.mark.asyncio
async def test_amount_bounds_disabled_at_zero() -> None:
    ev = _make_evaluator(min_amount=Decimal("0"), max_amount=Decimal("0"))
    result = await ev.evaluate(_tx(amount=0.001))
    assert result.matched is False
    result2 = await ev.evaluate(_tx(amount=1_000_000_000.0))
    assert result2.matched is False


# ---------------------------------------------------------------------------
# Full policy (all fields configured)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_policy_passes_compliant_transaction() -> None:
    ev = _make_evaluator(
        allowed_currencies=["USDC", "USDT"],
        blocked_recipients=["0xDEAD"],
        allowed_recipients=["0xALICE", "0xBOB"],
        min_amount=Decimal("1"),
        max_amount=Decimal("5000"),
    )
    result = await ev.evaluate(_tx(amount=250.0, currency="USDC", recipient="0xALICE"))
    assert result.matched is False


@pytest.mark.asyncio
async def test_context_fields_appear_in_metadata() -> None:
    """Optional context fields (channel, agent_id, session_id) should surface in result metadata."""
    ev = _make_evaluator()
    result = await ev.evaluate(_tx(channel="discord", agent_id="agent-42", session_id="sess-1"))
    assert result.metadata
    assert result.metadata.get("channel") == "discord"
    assert result.metadata.get("agent_id") == "agent-42"
    assert result.metadata.get("session_id") == "sess-1"


# ---------------------------------------------------------------------------
# Check ordering: currency first, then blocklist, then allowlist, then bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_currency_check_before_recipient_check() -> None:
    """Currency violation should be reported even if recipient is also blocked."""
    ev = _make_evaluator(
        allowed_currencies=["USDC"],
        blocked_recipients=["0xDEAD"],
    )
    result = await ev.evaluate(_tx(currency="DAI", recipient="0xDEAD"))
    # Currency checked first
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "currency_not_allowed"


@pytest.mark.asyncio
async def test_blocklist_before_allowlist() -> None:
    """Blocklist violation should be reported even if recipient not in allowlist."""
    ev = _make_evaluator(
        allowed_recipients=["0xGOOD"],
        blocked_recipients=["0xBAD"],
    )
    result = await ev.evaluate(_tx(recipient="0xBAD"))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "recipient_blocked"


# ---------------------------------------------------------------------------
# Step normalization tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_object_input_extraction() -> None:
    """When data is a full Step dict, extract transaction from 'input'."""
    ev = _make_evaluator(allowed_currencies=["USDC"])
    step_data = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": 100.0, "currency": "USDC", "recipient": "0xABC"},
        "context": {"channel": "slack"},
    }
    result = await ev.evaluate(step_data)
    assert result.matched is False


@pytest.mark.asyncio
async def test_step_blocked_recipient_via_step() -> None:
    """Blocklist check should work when data comes as a Step dict."""
    ev = _make_evaluator(blocked_recipients=["0xDEAD"])
    step_data = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": 10.0, "currency": "USDC", "recipient": "0xDEAD"},
        "context": None,
    }
    result = await ev.evaluate(step_data)
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "recipient_blocked"
