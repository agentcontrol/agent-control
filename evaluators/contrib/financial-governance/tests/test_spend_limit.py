"""Tests for the spend_limit evaluator and supporting infrastructure."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import pytest

from agent_control_evaluator_financial_governance.spend_limit import (
    BudgetCheck,
    BudgetLimit,
    BudgetWindow,
    InMemorySpendStore,
    SpendLimitConfig,
    SpendLimitEvaluator,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rolling_window(seconds: int = 86400) -> BudgetWindow:
    return BudgetWindow(kind="rolling", seconds=seconds)


def _per_tx_limit(amount: str | Decimal, currency: str = "USDC", **kw: Any) -> BudgetLimit:
    """Build a per-transaction cap (no window)."""
    return BudgetLimit(amount=Decimal(str(amount)), currency=currency, **kw)


def _period_limit(
    amount: str | Decimal,
    currency: str = "USDC",
    seconds: int = 86400,
    **kw: Any,
) -> BudgetLimit:
    """Build a rolling-period budget limit."""
    return BudgetLimit(
        amount=Decimal(str(amount)),
        currency=currency,
        window=_rolling_window(seconds),
        **kw,
    )


def _make_evaluator(
    limits: list[BudgetLimit] | None = None,
    store: InMemorySpendStore | None = None,
    # Legacy convenience kwargs translated to BudgetLimit list
    max_per_transaction: str | Decimal | None = None,
    max_per_period: str | Decimal | None = None,
    period_seconds: int = 86400,
    currency: str = "USDC",
) -> SpendLimitEvaluator:
    if limits is None:
        limits = []
        if max_per_transaction is not None and Decimal(str(max_per_transaction)) > 0:
            limits.append(_per_tx_limit(max_per_transaction, currency=currency))
        if max_per_period is not None and Decimal(str(max_per_period)) > 0:
            limits.append(_period_limit(max_per_period, currency=currency, seconds=period_seconds))
    cfg = SpendLimitConfig(limits=limits)
    return SpendLimitEvaluator(cfg, store=store)


def _tx(
    amount: Any = "10.00",
    currency: str = "USDC",
    recipient: str = "0xABC",
    **extra: Any,
) -> dict[str, Any]:
    return {"amount": amount, "currency": currency, "recipient": recipient, **extra}


# ---------------------------------------------------------------------------
# InMemorySpendStore unit tests
# ---------------------------------------------------------------------------


def test_store_record_and_query() -> None:
    """Basic record/query round-trip."""
    store = InMemorySpendStore()
    since = time.time() - 1

    store.record_spend(Decimal("100"), "USDC")
    store.record_spend(Decimal("50"), "USDC")
    store.record_spend(Decimal("200"), "ETH")

    assert store.get_spend("USDC", since) == Decimal("150")
    assert store.get_spend("ETH", since) == Decimal("200")
    assert store.get_spend("USDT", since) == Decimal("0")


def test_store_since_timestamp_filters_old_records() -> None:
    store = InMemorySpendStore()
    store.record_spend(Decimal("1000"), "USDC")
    future_since = time.time() + 1
    assert store.get_spend("USDC", future_since) == Decimal("0")


def test_store_end_timestamp_filters_future_records() -> None:
    store = InMemorySpendStore()
    past_end = time.time() - 1
    store.record_spend(Decimal("100"), "USDC")
    assert store.get_spend("USDC", time.time() - 10, end=past_end) == Decimal("0")


def test_store_end_none_includes_all_current_records() -> None:
    store = InMemorySpendStore()
    store.record_spend(Decimal("100"), "USDC")
    assert store.get_spend("USDC", time.time() - 5) == Decimal("100")


def test_store_record_count() -> None:
    store = InMemorySpendStore()
    assert store.record_count() == 0
    store.record_spend(Decimal("1"), "USDC")
    store.record_spend(Decimal("2"), "USDC")
    assert store.record_count() == 2


def test_store_rejects_non_positive_amount() -> None:
    store = InMemorySpendStore()
    with pytest.raises(ValueError, match="amount must be positive"):
        store.record_spend(Decimal("0"), "USDC")
    with pytest.raises(ValueError, match="amount must be positive"):
        store.record_spend(Decimal("-5"), "USDC")


def test_store_metadata_accepted() -> None:
    store = InMemorySpendStore()
    store.record_spend(
        Decimal("10"), "USDC",
        metadata={"agent_id": "agent-1", "session_id": "s-99"},
    )
    assert store.record_count() == 1


def test_store_scope_filter() -> None:
    """get_spend with scope only returns matching records."""
    store = InMemorySpendStore()
    since = time.time() - 1
    store.record_spend(Decimal("90"), "USDC", metadata={"channel": "A"})
    store.record_spend(Decimal("20"), "USDC", metadata={"channel": "B"})

    assert store.get_spend("USDC", since, scope={"channel": "A"}) == Decimal("90")
    assert store.get_spend("USDC", since, scope={"channel": "B"}) == Decimal("20")
    assert store.get_spend("USDC", since) == Decimal("110")


# ---------------------------------------------------------------------------
# check_and_record atomic tests
# ---------------------------------------------------------------------------


def test_check_and_record_accepts_within_limit() -> None:
    """check_and_record records and returns (True, prior_spend)."""
    store = InMemorySpendStore()
    since = time.time() - 1

    accepted, prior = store.check_and_record(
        amount=Decimal("50"),
        currency="USDC",
        limit=Decimal("100"),
        start=since,
    )
    assert accepted is True
    assert prior == Decimal("0")
    assert store.record_count() == 1
    assert store.get_spend("USDC", since) == Decimal("50")


def test_check_and_record_rejects_over_limit() -> None:
    """check_and_record rejects when amount would exceed limit."""
    store = InMemorySpendStore()
    since = time.time() - 1
    store.record_spend(Decimal("90"), "USDC")

    accepted, prior = store.check_and_record(
        amount=Decimal("20"),
        currency="USDC",
        limit=Decimal("100"),
        start=since,
    )
    assert accepted is False
    assert prior == Decimal("90")
    assert store.record_count() == 1


def test_check_and_record_exact_boundary_accepted() -> None:
    """check_and_record accepts when spend exactly reaches the limit."""
    store = InMemorySpendStore()
    since = time.time() - 1
    store.record_spend(Decimal("90"), "USDC")

    accepted, prior = store.check_and_record(
        amount=Decimal("10"),
        currency="USDC",
        limit=Decimal("100"),
        start=since,
    )
    assert accepted is True
    assert prior == Decimal("90")
    assert store.get_spend("USDC", since) == Decimal("100")


def test_check_and_record_scoped_isolation() -> None:
    """check_and_record with scope only counts matching records."""
    store = InMemorySpendStore()
    since = time.time() - 1
    store.record_spend(Decimal("90"), "USDC", metadata={"channel": "A"})

    accepted, prior = store.check_and_record(
        amount=Decimal("20"),
        currency="USDC",
        limit=Decimal("100"),
        start=since,
        scope={"channel": "B"},
        metadata={"channel": "B"},
    )
    assert accepted is True
    assert prior == Decimal("0")
    assert store.get_spend("USDC", since, scope={"channel": "B"}) == Decimal("20")


def test_check_and_record_rejects_non_positive() -> None:
    store = InMemorySpendStore()
    with pytest.raises(ValueError):
        store.check_and_record(
            amount=Decimal("0"),
            currency="USDC",
            limit=Decimal("100"),
            start=time.time() - 1,
        )


def test_check_and_record_many_records_once_after_all_budgets_pass() -> None:
    store = InMemorySpendStore()
    since = time.time() - 1

    accepted, failed_index, current_spends = store.check_and_record_many(
        amount=Decimal("50"),
        currency="USDC",
        checks=[
            BudgetCheck(limit=Decimal("100"), start=since),
            BudgetCheck(limit=Decimal("100"), start=since, scope={"channel": "A"}),
        ],
        metadata={"channel": "A"},
    )

    assert accepted is True
    assert failed_index is None
    assert current_spends == [Decimal("0"), Decimal("0")]
    assert store.record_count() == 1
    assert store.get_spend("USDC", since) == Decimal("50")
    assert store.get_spend("USDC", since, scope={"channel": "A"}) == Decimal("50")


def test_check_and_record_many_does_not_record_when_any_budget_fails() -> None:
    store = InMemorySpendStore()
    since = time.time() - 1
    store.record_spend(Decimal("95"), "USDC")

    accepted, failed_index, current_spends = store.check_and_record_many(
        amount=Decimal("10"),
        currency="USDC",
        checks=[
            BudgetCheck(limit=Decimal("100"), start=since),
            BudgetCheck(limit=Decimal("100"), start=since, scope={"channel": "A"}),
        ],
        metadata={"channel": "A"},
    )

    assert accepted is False
    assert failed_index == 0
    assert current_spends == [Decimal("95")]
    assert store.record_count() == 1
    assert store.get_spend("USDC", since) == Decimal("95")


# ---------------------------------------------------------------------------
# BudgetWindow / BudgetLimit / SpendLimitConfig validation
# ---------------------------------------------------------------------------


def test_budget_limit_currency_normalized() -> None:
    limit = BudgetLimit(amount=Decimal("100"), currency="usdc")
    assert limit.currency == "USDC"


def test_budget_window_rolling_requires_seconds() -> None:
    with pytest.raises(Exception):
        BudgetWindow(kind="rolling")


def test_budget_window_fixed_requires_unit() -> None:
    with pytest.raises(Exception):
        BudgetWindow(kind="fixed")


def test_budget_window_rolling_valid() -> None:
    w = BudgetWindow(kind="rolling", seconds=3600)
    assert w.seconds == 3600


def test_budget_window_fixed_valid() -> None:
    w = BudgetWindow(kind="fixed", unit="day", timezone="America/New_York")
    assert w.unit == "day"
    assert w.timezone == "America/New_York"


def test_config_empty_limits() -> None:
    cfg = SpendLimitConfig(limits=[])
    assert cfg.limits == []


def test_config_limits_parsed_from_dict() -> None:
    """SpendLimitConfig parses limits from dicts (Pydantic coercion)."""
    cfg = SpendLimitConfig(limits=[
        {"amount": "100.00", "currency": "USDC"},
        {
            "amount": "1000.00",
            "currency": "USDC",
            "scope_by": ["channel"],
            "window": {"kind": "rolling", "seconds": 86400},
        },
    ])
    assert len(cfg.limits) == 2
    assert cfg.limits[0].amount == Decimal("100.00")
    assert cfg.limits[1].scope_by == ("channel",)
    assert cfg.limits[1].window is not None
    assert cfg.limits[1].window.kind == "rolling"


def test_budget_limit_rejects_non_positive_amount() -> None:
    with pytest.raises(Exception):
        BudgetLimit(amount=Decimal("0"), currency="USDC")
    with pytest.raises(Exception):
        BudgetLimit(amount=Decimal("-1"), currency="USDC")


# ---------------------------------------------------------------------------
# SpendLimitEvaluator — basic behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_data_is_allowed() -> None:
    ev = _make_evaluator(max_per_transaction="100")
    result = await ev.evaluate(None)
    assert result.matched is False
    assert result.error is None


@pytest.mark.asyncio
async def test_non_dict_data_is_allowed() -> None:
    ev = _make_evaluator(max_per_transaction="100")
    result = await ev.evaluate("not a dict")
    assert result.matched is False
    assert result.error is None


@pytest.mark.asyncio
async def test_missing_amount_not_matched() -> None:
    """Missing amount is a non-match, NOT an evaluator error."""
    ev = _make_evaluator(max_per_transaction="100")
    result = await ev.evaluate({"currency": "USDC", "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None
    assert "amount" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_missing_currency_not_matched() -> None:
    """Missing currency is a non-match, NOT an evaluator error."""
    ev = _make_evaluator(max_per_transaction="100")
    result = await ev.evaluate({"amount": "10.00", "recipient": "0xABC"})
    assert result.matched is False
    assert result.error is None
    assert "currency" in (result.message or "").lower()


@pytest.mark.asyncio
async def test_wrong_currency_is_skipped() -> None:
    """Transaction in a different currency should be allowed."""
    ev = _make_evaluator(limits=[_per_tx_limit("1", currency="USDC")])
    result = await ev.evaluate(_tx(amount="99999.00", currency="ETH"))
    assert result.matched is False


@pytest.mark.asyncio
async def test_no_limits_configured_allows_everything() -> None:
    ev = _make_evaluator(limits=[])
    result = await ev.evaluate(_tx(amount="999999.00"))
    assert result.matched is False


# ---------------------------------------------------------------------------
# Per-transaction cap tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_transaction_cap_violation() -> None:
    ev = _make_evaluator(max_per_transaction="100")
    result = await ev.evaluate(_tx(amount="101.00"))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "per_transaction_cap"
    assert result.error is None


@pytest.mark.asyncio
async def test_per_transaction_cap_exact_boundary_allowed() -> None:
    ev = _make_evaluator(max_per_transaction="100")
    result = await ev.evaluate(_tx(amount="100.00"))
    assert result.matched is False


# ---------------------------------------------------------------------------
# Period budget tests (atomic via check_and_record)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_period_budget_violation() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period="500", store=store)
    store.record_spend(Decimal("480"), "USDC")

    result = await ev.evaluate(_tx(amount="25.00"))
    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "period_budget"
    assert result.metadata["current_period_spend"] == Decimal("480")
    assert result.metadata["projected_period_spend"] == Decimal("505")


@pytest.mark.asyncio
async def test_period_budget_exact_boundary_allowed() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period="500", store=store)
    store.record_spend(Decimal("490"), "USDC")

    result = await ev.evaluate(_tx(amount="10.00"))
    assert result.matched is False
    since = time.time() - 5
    assert store.get_spend("USDC", since) == Decimal("500")


@pytest.mark.asyncio
async def test_successful_transaction_is_recorded() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_transaction="100", max_per_period="1000", store=store)

    assert store.record_count() == 0
    result = await ev.evaluate(_tx(amount="50.00"))
    assert result.matched is False
    assert store.record_count() == 1
    since = time.time() - 5
    assert store.get_spend("USDC", since) == Decimal("50")


@pytest.mark.asyncio
async def test_later_per_transaction_violation_does_not_record_early() -> None:
    store = InMemorySpendStore()
    cfg = SpendLimitConfig(limits=[
        _period_limit("1000"),
        _per_tx_limit("40"),
    ])
    ev = SpendLimitEvaluator(cfg, store=store)

    result = await ev.evaluate(_tx(amount="50.00"))

    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "per_transaction_cap"
    assert store.record_count() == 0


@pytest.mark.asyncio
async def test_multiple_period_limits_record_once() -> None:
    store = InMemorySpendStore()
    cfg = SpendLimitConfig(limits=[
        _period_limit("1000"),
        _period_limit("100", scope_by=("channel",)),
    ])
    ev = SpendLimitEvaluator(cfg, store=store)

    result = await ev.evaluate(_tx(amount="50.00", channel="channel-A"))

    assert result.matched is False
    since = time.time() - 5
    assert store.record_count() == 1
    assert store.get_spend("USDC", since) == Decimal("50")
    assert store.get_spend("USDC", since, scope={"channel": "channel-A"}) == Decimal("50")


@pytest.mark.asyncio
async def test_period_budget_failure_does_not_leave_partial_record() -> None:
    store = InMemorySpendStore()
    store.record_spend(Decimal("95"), "USDC")
    cfg = SpendLimitConfig(limits=[
        _period_limit("100"),
        _period_limit("100", scope_by=("channel",)),
    ])
    ev = SpendLimitEvaluator(cfg, store=store)

    result = await ev.evaluate(_tx(amount="10.00", channel="channel-A"))

    assert result.matched is True
    assert result.metadata and result.metadata["violation"] == "period_budget"
    since = time.time() - 5
    assert store.record_count() == 1
    assert store.get_spend("USDC", since) == Decimal("95")


@pytest.mark.asyncio
async def test_multiple_sequential_transactions_accumulate() -> None:
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_transaction="100", max_per_period="250", store=store)

    r1 = await ev.evaluate(_tx(amount="80.00"))
    assert r1.matched is False
    r2 = await ev.evaluate(_tx(amount="80.00"))
    assert r2.matched is False
    r3 = await ev.evaluate(_tx(amount="80.00"))
    assert r3.matched is False  # 240 <= 250
    r4 = await ev.evaluate(_tx(amount="80.00"))
    assert r4.matched is True
    assert r4.metadata and r4.metadata["violation"] == "period_budget"


@pytest.mark.asyncio
async def test_currency_case_insensitive_in_data() -> None:
    ev = _make_evaluator(max_per_transaction="100", currency="USDC")
    result = await ev.evaluate(_tx(amount="10.00", currency="usdc"))
    assert result.matched is False


# ---------------------------------------------------------------------------
# BudgetLimit.scope_by — independent dimension budget isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_by_channel_isolates_budgets() -> None:
    """scope_by=(channel,) gives each channel its own independent counter.

    lan17s specific test: 90 USDC in channel A, then 20 USDC in channel B
    with a 100 USDC per-channel budget.  Channel B should be ALLOWED because
    its scoped spend is 0, not 90.
    """
    store = InMemorySpendStore()
    limit = BudgetLimit(
        amount=Decimal("100"),
        currency="USDC",
        scope_by=("channel",),
        window=BudgetWindow(kind="rolling", seconds=86400),
    )
    ev = SpendLimitEvaluator(SpendLimitConfig(limits=[limit]), store=store)

    r1 = await ev.evaluate(_tx(amount="90.00", channel="channel-A"))
    assert r1.matched is False, f"Channel A 90 USDC should be allowed: {r1.message}"

    since = time.time() - 5
    assert store.get_spend("USDC", since, scope={"channel": "channel-A"}) == Decimal("90")

    r2 = await ev.evaluate(_tx(amount="20.00", channel="channel-B"))
    assert r2.matched is False, (
        f"Channel B 20 USDC should be allowed (channel B has 0 spend): {r2.message}"
    )
    assert store.get_spend("USDC", since, scope={"channel": "channel-B"}) == Decimal("20")
    assert store.get_spend("USDC", since, scope={"channel": "channel-A"}) == Decimal("90")


@pytest.mark.asyncio
async def test_scope_by_channel_accumulates_within_same_channel() -> None:
    """Spend within the same channel accumulates correctly."""
    store = InMemorySpendStore()
    limit = BudgetLimit(
        amount=Decimal("100"),
        currency="USDC",
        scope_by=("channel",),
        window=BudgetWindow(kind="rolling", seconds=86400),
    )
    ev = SpendLimitEvaluator(SpendLimitConfig(limits=[limit]), store=store)

    r1 = await ev.evaluate(_tx(amount="60.00", channel="channel-A"))
    assert r1.matched is False

    r2 = await ev.evaluate(_tx(amount="50.00", channel="channel-A"))
    assert r2.matched is True
    assert r2.metadata and r2.metadata["violation"] == "period_budget"


@pytest.mark.asyncio
async def test_scope_by_agent_id_isolation() -> None:
    """scope_by=(agent_id,) isolates budgets per agent."""
    store = InMemorySpendStore()
    limit = BudgetLimit(
        amount=Decimal("100"),
        currency="USDC",
        scope_by=("agent_id",),
        window=BudgetWindow(kind="rolling", seconds=86400),
    )
    ev = SpendLimitEvaluator(SpendLimitConfig(limits=[limit]), store=store)

    r1 = await ev.evaluate(_tx(amount="90.00", agent_id="agent-1"))
    assert r1.matched is False

    r2 = await ev.evaluate(_tx(amount="20.00", agent_id="agent-2"))
    assert r2.matched is False


@pytest.mark.asyncio
async def test_global_budget_without_scope() -> None:
    """scope_by=() means all spend in that currency counts together."""
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_period="100", store=store)

    r1 = await ev.evaluate(_tx(amount="90.00"))
    assert r1.matched is False

    r2 = await ev.evaluate(_tx(amount="20.00"))
    assert r2.matched is True


@pytest.mark.asyncio
async def test_multiple_limits_in_one_config() -> None:
    """Global per-tx cap and per-channel period budget co-exist."""
    store = InMemorySpendStore()
    cfg = SpendLimitConfig(limits=[
        BudgetLimit(amount=Decimal("200"), currency="USDC"),
        BudgetLimit(
            amount=Decimal("100"),
            currency="USDC",
            scope_by=("channel",),
            window=BudgetWindow(kind="rolling", seconds=86400),
        ),
    ])
    ev = SpendLimitEvaluator(cfg, store=store)

    r1 = await ev.evaluate(_tx(amount="90.00", channel="channel-A"))
    assert r1.matched is False

    r2 = await ev.evaluate(_tx(amount="90.00", channel="channel-B"))
    assert r2.matched is False

    r3 = await ev.evaluate(_tx(amount="20.00", channel="channel-A"))
    assert r3.matched is True
    assert r3.metadata and r3.metadata["violation"] == "period_budget"

    r4 = await ev.evaluate(_tx(amount="210.00", channel="channel-C"))
    assert r4.matched is True
    assert r4.metadata and r4.metadata["violation"] == "per_transaction_cap"


# ---------------------------------------------------------------------------
# Malformed input — matched=False, error=None (never error=...)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_input_is_not_evaluator_error() -> None:
    """Malformed input must return matched=False, error=None.

    The error field is reserved for evaluator crashes/timeouts/missing deps.
    """
    ev = _make_evaluator(max_per_transaction="100")

    r1 = await ev.evaluate({"currency": "USDC", "recipient": "0xABC"})
    assert r1.matched is False
    assert r1.error is None

    r2 = await ev.evaluate({"amount": "10.00", "recipient": "0xABC"})
    assert r2.matched is False
    assert r2.error is None

    r3 = await ev.evaluate({"amount": "-5.00", "currency": "USDC", "recipient": "0xABC"})
    assert r3.matched is False
    assert r3.error is None

    r4 = await ev.evaluate("not a dict")
    assert r4.matched is False
    assert r4.error is None

    r5 = await ev.evaluate(None)
    assert r5.matched is False
    assert r5.error is None


@pytest.mark.parametrize("bad_amount", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.asyncio
async def test_non_finite_amount_is_not_evaluator_error(bad_amount: str) -> None:
    ev = _make_evaluator(max_per_transaction="100")

    result = await ev.evaluate(_tx(amount=bad_amount))

    assert result.matched is False
    assert result.error is None


# ---------------------------------------------------------------------------
# Step normalization (selector.path: "*" vs "input")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_object_input_extraction() -> None:
    """selector.path=* passes a full Step dict; evaluator extracts from input."""
    ev = _make_evaluator(max_per_transaction="100")
    step_data = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": "50.00", "currency": "USDC", "recipient": "0xABC"},
        "context": None,
    }
    result = await ev.evaluate(step_data)
    assert result.matched is False


@pytest.mark.asyncio
async def test_step_context_merged_into_transaction() -> None:
    """Context fields from step.context are available for scoped budgets."""
    store = InMemorySpendStore()
    limit = BudgetLimit(
        amount=Decimal("100"),
        currency="USDC",
        scope_by=("channel",),
        window=BudgetWindow(kind="rolling", seconds=86400),
    )
    ev = SpendLimitEvaluator(SpendLimitConfig(limits=[limit]), store=store)

    step1 = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": "90.00", "currency": "USDC", "recipient": "0xABC"},
        "context": {"channel": "channel-A"},
    }
    r1 = await ev.evaluate(step1)
    assert r1.matched is False

    step2 = {
        "type": "tool",
        "name": "payment",
        "input": {"amount": "20.00", "currency": "USDC", "recipient": "0xABC"},
        "context": {"channel": "channel-B"},
    }
    r2 = await ev.evaluate(step2)
    assert r2.matched is False


@pytest.mark.asyncio
async def test_step_context_overrides_not_clobbered_by_input() -> None:
    """If input already has channel, step.context must NOT overwrite it.

    Asserts against actual store state to prove spend was recorded under
    channel=from-input, not from-context.
    """
    store = InMemorySpendStore()
    ev = _make_evaluator(max_per_transaction="100", max_per_period="1000", store=store)

    step_data = {
        "type": "tool",
        "name": "payment",
        "input": {
            "amount": "10.00",
            "currency": "USDC",
            "recipient": "0xABC",
            "channel": "from-input",
        },
        "context": {"channel": "from-context"},
    }
    result = await ev.evaluate(step_data)
    assert result.matched is False

    since = time.time() - 5
    assert store.get_spend("USDC", since, scope={"channel": "from-input"}) == Decimal("10")
    assert store.get_spend("USDC", since, scope={"channel": "from-context"}) == Decimal("0")


# ---------------------------------------------------------------------------
# lan17 specific channel-scope-independence test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lan17_channel_scope_independence() -> None:
    """lan17s test: 90 USDC in channel A, then 20 USDC in channel B.

    With a 100 USDC per-channel budget (scope_by=(channel,)), the second
    transaction must be ALLOWED — channel B has 0 spend.
    """
    store = InMemorySpendStore()
    limit = BudgetLimit(
        amount=Decimal("100"),
        currency="USDC",
        scope_by=("channel",),
        window=BudgetWindow(kind="rolling", seconds=86400),
    )
    ev = SpendLimitEvaluator(SpendLimitConfig(limits=[limit]), store=store)

    r1 = await ev.evaluate(_tx(amount="90.00", channel="channel-A"))
    assert r1.matched is False, f"Channel A 90 USDC should be allowed: {r1.message}"

    since = time.time() - 5
    assert store.get_spend("USDC", since, scope={"channel": "channel-A"}) == Decimal("90")

    r2 = await ev.evaluate(_tx(amount="20.00", channel="channel-B"))
    assert r2.matched is False, (
        f"Channel B 20 USDC should be allowed (channel B has 0 spend): {r2.message}"
    )

    assert store.get_spend("USDC", since, scope={"channel": "channel-B"}) == Decimal("20")
    assert store.get_spend("USDC", since, scope={"channel": "channel-A"}) == Decimal("90")


# ---------------------------------------------------------------------------
# Fixed window (calendar-aligned) budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixed_window_day_budget() -> None:
    """Fixed-day window budget works (uses UTC approximation)."""
    store = InMemorySpendStore()
    limit = BudgetLimit(
        amount=Decimal("100"),
        currency="USDC",
        window=BudgetWindow(kind="fixed", unit="day"),
    )
    ev = SpendLimitEvaluator(SpendLimitConfig(limits=[limit]), store=store)

    r1 = await ev.evaluate(_tx(amount="90.00"))
    assert r1.matched is False

    r2 = await ev.evaluate(_tx(amount="20.00"))
    assert r2.matched is True
    assert r2.metadata and r2.metadata["violation"] == "period_budget"
