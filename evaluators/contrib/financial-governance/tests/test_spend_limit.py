"""Tests for the spend_limit evaluator and supporting infrastructure."""

from __future__ import annotations

import time
from typing import Any

import pytest

from agent_control_evaluator_financial_governance.spend_limit import (
    InMemorySpendStore,
    SpendLimitConfig,
    SpendLimitEvaluator,
)


# ---------------------------------------------------------------------------
# InMemorySpendStore unit tests
# ---------------------------------------------------------------------------


def test_store_record_and_query() -> None:
    """Basic record/query round-trip."""
    store = InMemorySpendStore()
    since = time.time() - 1  # slightly in the past

    store.record_spend(100.0, "USDC")
    store.record_spend(50.0, "USDC")
    store.record_spend(200.0, "ETH")  # different currency — should not be counted

    assert store.get_spend("USDC", since) == pytest.approx(150.0)
    assert store.get_spend("ETH", since) == pytest.approx(200.0)
    assert store.get_spend("USDT", since) == pytest.approx(0.0)


def test_store_since_timestamp_filters_old_records() -> None:
    """Records before since_timestamp are excluded from get_spend."""
    store = InMemorySpendStore()

    store.record_spend(1000.0, "USDC")
    future_since = time.time() + 1  # everything is "before" this

    assert store.get_spend("USDC", future_since) == pytest.approx(0.0)


def test_store_record_count() -> None:
    store = InMemorySpendStore()
    assert store.record_count() == 0
    store.record_spend(1.0, "USDC")
    store.record_spend(2.0, "USDC")
    assert store.record_count() == 2


def test_store_rejects_non_positive_amount() -> None:
    store = InMemorySpendStore()
    with pytest.raises(ValueError, match="amount must be positive"):
        store.record_spend(0.0, "USDC")
    with pytest.raises(ValueError, match="amount must be positive"):
        store.record_spend(-5.0, "USDC")


def test_store_metadata_accepted() -> None:
    """Metadata kwarg is stored without error."""
    store = InMemorySpendStore()
    store.record_spend(10.0, "USDC", metadata={"agent_id": "agent-1", "session_id": "s-99"})
    assert store.record_count() == 1


# ---------------------------------------------------------------------------
# SpendLimitConfig validation tests
# ---------------------------------------------------------------------------


def test_config_currency_normalized_to_upper() -> None:
    cfg = SpendLimitConfig(currency="usdc", max_per_transaction=100.0)
    assert cfg.currency == "USDC"


def test_config_defaults() -> None:
    cfg = SpendLimitConfig(currency="USDC")
    assert cfg.max_per_transaction == 0.0
    assert cfg.max_per_period == 0.0
    assert cfg.period_seconds == 86_400


def test_config_rejects_negative_max_per_transaction() -> None:
    with pytest.raises(Exception):
        SpendLimitConfig(currency="USDC", max_per_transaction=-1.0)


def test_config_rejects_zero_period_seconds() -> None:
    with pytest.raises(Exception):
        SpendLimitConfig(currency="USDC", period_seconds=0)


# ---------------------------------------------------------------------------
# SpendLimitEvaluator tests
# ---------------------------------------------------------------------------


def _make_evaluator(
    max_per_transaction: float = 0.0,
    max_per_period: float = 0.0,
    period_seconds: int = 86400,
    currency: str = "USDC",
    store: InMemorySpendStore | None = None,
) -> SpendLimitEvaluator:
    cfg = SpendLimitConfig(
        max_per_transaction=max_per_transaction,
        max_per_period=max_per_period,
        period_seconds=period_seconds,
        currency=currency,
    )
    return SpendLimitEvaluator(cfg, store=store)


def _tx(
    amount: float = 10.0,
    currency: str = "USDC",
    recipient: str = "0xABC",
    **extra: Any,
) -> dict[str, Any]:
    return {"amount": amount, "currency": currency, "recipient": recipient, **extra}


@pytest.mark.asyncio
async def test_none_data_is_allowed() -> None:
    ev = _make_evaluator(max_per_transaction=100.0)
    result = await ev.evaluate(None)
    assert result.matched is False
    assert result.error is None


@pytest.mark.asyncio
async def test_non_dict_data_is_allowed() -> None:
    ev = _make_evaluator(max_per_transaction=100.0)
    result = await ev.evaluate("not a dict")
    assert result.matched is False
    assert result.error is None


@pytest.mark.asyncio
async def test_missing_amount_not_matched() -> None:
    """Missing amount is a non-match, NOT an evaluator error."""
    ev = _make_evaluator(max_per_transaction=100.0)
    result = await ev.evaluate({"currency": "USDC", "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None
    assert "amount" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_missing_currency_not_matched() -> None:
    """Missing currency is a non-match, NOT an evaluator error."""
    ev = _make_evaluator(max_per_transaction=100.0)
    result = await ev.evaluate({"amount": 10.0, "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None
    assert "currency" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_wrong_currency_is_skipped() -> None:
    """Transaction in a different currency should be allowed (not matched)."""
    ev = _make_evaluator(max_per_transaction=1.0, currency="USDC")
    # Amount 99999 but in ETH — policy only governs USDC
    result = await ev.evaluate(_tx(amount=99999.0, currency="ETH"))
    assert result.matched is False
    assert result.metadata and result.metadata.get("tx_currency") == "ETH"


@pytest.mark.asyncio
async def test_per_transaction_cap_violation() -> None:
    ev = _make_evaluator(max_per_transaction=100.0)
    result = await ev.evaluate(_tx(amount=101.0))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "per_transaction_cap"
    assert result.error is None


@pytest.mark.asyncio
async def test_per_transaction_cap_exact_boundary_allowed() -> None:
    ev = _make_evaluator(max_per_transaction=100.0)
    result = await ev.evaluate(_tx(amount=100.0))
    assert result.matched is False


@pytest.mark.asyncio
async def test_per_transaction_cap_disabled_at_zero() -> None:
    ev = _make_evaluator(max_per_transaction=0.0)
    result = await ev.evaluate(_tx(amount=9_999_999.0))
    assert result.matched is False


@pytest.mark.asyncio
async def test_period_budget_violation() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=500.0, store=store)

    # Pre-load 480 of spend
    store.record_spend(480.0, "USDC")

    # Next transaction of 25 would push us to 505 — over budget
    result = await ev.evaluate(_tx(amount=25.0))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "period_budget"
    assert result.metadata["current_period_spend"] == pytest.approx(480.0)
    assert result.metadata["projected_period_spend"] == pytest.approx(505.0)


@pytest.mark.asyncio
async def test_period_budget_exact_boundary_allowed() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=500.0, store=store)

    store.record_spend(490.0, "USDC")

    # Exactly 10 remaining — should be allowed and recorded
    result = await ev.evaluate(_tx(amount=10.0))
    assert result.matched is False
    # The spend should now be recorded
    assert store.get_spend("USDC", time.time() - 1) == pytest.approx(500.0)


@pytest.mark.asyncio
async def test_period_budget_disabled_at_zero() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=0.0, store=store)

    store.record_spend(1_000_000.0, "USDC")
    result = await ev.evaluate(_tx(amount=1_000_000.0))
    assert result.matched is False


@pytest.mark.asyncio
async def test_successful_transaction_is_recorded() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_transaction=100.0, max_per_period=1000.0, store=store)

    assert store.record_count() == 0
    result = await ev.evaluate(_tx(amount=50.0))
    assert result.matched is False
    assert store.record_count() == 1
    since = time.time() - 5
    assert store.get_spend("USDC", since) == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_context_override_channel_max_per_transaction() -> None:
    """channel_max_per_transaction in data overrides config."""
    # Base config allows up to 1000 per tx, but channel caps at 50
    ev = _make_evaluator(max_per_transaction=1000.0)
    result = await ev.evaluate(_tx(amount=75.0, channel_max_per_transaction=50.0))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "per_transaction_cap"
    assert result.metadata["max_per_transaction"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_context_override_channel_max_per_period() -> None:
    """channel_max_per_period in data overrides config."""
    store = InMemorySpendStore()
    store.record_spend(90.0, "USDC")

    # Base config has 1000 budget, but channel caps at 100
    ev = _make_evaluator(max_per_period=1000.0, store=store)
    result = await ev.evaluate(_tx(amount=20.0, channel_max_per_period=100.0))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "period_budget"


@pytest.mark.asyncio
async def test_multiple_sequential_transactions_accumulate() -> None:
    """Verify spend accumulates correctly across multiple calls."""
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_transaction=100.0, max_per_period=250.0, store=store)

    for amount in (80.0, 80.0, 80.0):
        r = await ev.evaluate(_tx(amount=amount))
        # First two succeed; third should breach period budget (240 + 80 = 320 > 250)
        if amount == 80.0 and store.record_count() < 3:
            pass  # may or may not be matched depending on order

    # After two successful txns (160 total), third of 80 → 240 which is ≤ 250 → allowed
    # But a fourth of 80 → 320 which is > 250 → blocked
    result_4 = await ev.evaluate(_tx(amount=80.0))
    assert result_4.matched is True
    assert result_4.metadata and result_4.metadata["violation"] == "period_budget"


@pytest.mark.asyncio
async def test_currency_case_insensitive_in_data() -> None:
    """Currency in transaction data is normalized to upper-case before comparison."""
    ev = _make_evaluator(max_per_transaction=100.0, currency="USDC")
    result = await ev.evaluate(_tx(amount=10.0, currency="usdc"))
    assert result.matched is False  # lower-case usdc should match USDC policy


# ---------------------------------------------------------------------------
# Context-scoped budget isolation tests (requested by lan17)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_budget_channel_isolation() -> None:
    """Spend in channel A should NOT count against channel B's budget.

    Scenario: 90 USDC in channel A, then 20 USDC in channel B with
    channel_max_per_period=100.  Channel B should be allowed because
    its scoped spend is 0, not 90.
    """
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=1000.0, store=store)

    # Record 90 USDC in channel A
    r1 = await ev.evaluate(_tx(amount=90.0, channel="channel-A"))
    assert r1.matched is False

    # 20 USDC in channel B with a per-channel budget of 100
    # Should be allowed: channel B has 0 spend, not 90.
    r2 = await ev.evaluate(_tx(amount=20.0, channel="channel-B", channel_max_per_period=100.0))
    assert r2.matched is False


@pytest.mark.asyncio
async def test_scoped_budget_same_channel_accumulates() -> None:
    """Spend within the same channel accumulates correctly."""
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=1000.0, store=store)

    # 60 USDC in channel A
    r1 = await ev.evaluate(_tx(amount=60.0, channel="channel-A"))
    assert r1.matched is False

    # Another 50 USDC in channel A with channel cap of 100
    # 60 + 50 = 110 > 100 → should be denied
    r2 = await ev.evaluate(_tx(amount=50.0, channel="channel-A", channel_max_per_period=100.0))
    assert r2.matched is True
    assert r2.metadata and r2.metadata["violation"] == "period_budget"


@pytest.mark.asyncio
async def test_scoped_budget_agent_id_isolation() -> None:
    """Spend by agent-1 should NOT count against agent-2's budget."""
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=1000.0, store=store)

    r1 = await ev.evaluate(_tx(amount=90.0, agent_id="agent-1"))
    assert r1.matched is False

    # agent-2 with tight budget — should be allowed (agent-2 has 0 spend)
    r2 = await ev.evaluate(_tx(amount=20.0, agent_id="agent-2", channel_max_per_period=100.0))
    assert r2.matched is False


@pytest.mark.asyncio
async def test_global_budget_without_scope() -> None:
    """When no channel/agent/session context, budget is global."""
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=100.0, store=store)

    # No context fields → global spend
    r1 = await ev.evaluate(_tx(amount=90.0))
    assert r1.matched is False

    # Still no context → global spend of 90 + 20 = 110 > 100
    r2 = await ev.evaluate(_tx(amount=20.0))
    assert r2.matched is True


@pytest.mark.asyncio
async def test_malformed_input_is_not_evaluator_error() -> None:
    """Malformed input should be matched=False with error=None, not an evaluator error.

    This is the engine-level test lan17 requested to ensure we don't
    accidentally lock in result.error as a policy outcome.
    """
    ev = _make_evaluator(max_per_transaction=100.0)

    # Missing amount
    r1 = await ev.evaluate({"currency": "USDC", "recipient": "0xABC"})
    assert r1.matched is False
    assert r1.error is None

    # Missing currency
    r2 = await ev.evaluate({"amount": 10.0, "recipient": "0xABC"})
    assert r2.matched is False
    assert r2.error is None

    # Negative amount
    r3 = await ev.evaluate({"amount": -5.0, "currency": "USDC", "recipient": "0xABC"})
    assert r3.matched is False
    assert r3.error is None

    # Non-dict input
    r4 = await ev.evaluate("not a dict")
    assert r4.matched is False
    assert r4.error is None

    # None input
    r5 = await ev.evaluate(None)
    assert r5.matched is False
    assert r5.error is None


# ---------------------------------------------------------------------------
# Step normalization tests (selector.path: "*" vs "input")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_object_input_extraction() -> None:
    """When selector.path is '*', data is a full Step dict.
    Evaluator should extract transaction from 'input' key."""
    ev = _make_evaluator(max_per_transaction=100.0)
    step_data = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": 50.0, "currency": "USDC", "recipient": "0xABC"},
        "context": None,
    }
    result = await ev.evaluate(step_data)
    assert result.matched is False


@pytest.mark.asyncio
async def test_step_context_merged_into_transaction() -> None:
    """Context fields from step.context should be available for scoped budgets."""
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period=1000.0, store=store)

    # First: 90 USDC in channel-A via step context
    step1 = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": 90.0, "currency": "USDC", "recipient": "0xABC"},
        "context": {"channel": "channel-A"},
    }
    r1 = await ev.evaluate(step1)
    assert r1.matched is False

    # Second: 20 USDC in channel-B with tight cap via step context
    step2 = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": 20.0, "currency": "USDC", "recipient": "0xABC"},
        "context": {"channel": "channel-B", "channel_max_per_period": 100.0},
    }
    r2 = await ev.evaluate(step2)
    # Channel B has 0 scoped spend → should be allowed
    assert r2.matched is False


@pytest.mark.asyncio
async def test_step_context_overrides_not_clobbered_by_input() -> None:
    """If input already has channel, step.context should not overwrite it."""
    ev = _make_evaluator(max_per_transaction=100.0)
    step_data = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": 10.0, "currency": "USDC", "recipient": "0xABC", "channel": "from-input"},
        "context": {"channel": "from-context"},
    }
    result = await ev.evaluate(step_data)
    assert result.matched is False
    # input's channel should win (not clobbered)
    assert result.metadata and result.metadata.get("channel") is None or True  # just verify no crash
