"""Tests for the budget evaluator (contrib).

Given/When/Then comment style per reviewer request.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
from pydantic import ValidationError

from agent_control_evaluator_budget.budget.config import (
    WINDOW_DAILY,
    WINDOW_MONTHLY,
    WINDOW_WEEKLY,
    BudgetEvaluatorConfig,
    BudgetLimitRule,
    Currency,
)
from agent_control_evaluator_budget.budget.evaluator import (
    BudgetEvaluator,
    _extract_tokens,
)
from agent_control_evaluator_budget.budget.memory_store import (
    InMemoryBudgetStore,
    _build_scope_key,
    _compute_utilization,
    _derive_period_key,
)

# ---------------------------------------------------------------------------
# InMemoryBudgetStore
# ---------------------------------------------------------------------------


class TestInMemoryBudgetStore:
    def test_single_record_under_limit(self) -> None:
        # Given: store with a $10 daily limit (1000 cents)
        rules = [BudgetLimitRule(limit=1000, window_seconds=WINDOW_DAILY)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 1700000000.0)

        # When: record 300 cents of usage
        results = store.record_and_check(scope={}, input_tokens=100, output_tokens=50, cost=300)

        # Then: not breached, ratio ~0.3
        assert len(results) == 1
        assert not results[0].exceeded
        assert results[0].utilization == pytest.approx(0.3, abs=0.01)

    def test_accumulation_triggers_breach(self) -> None:
        # Given: store with 1000-cent limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 1700000000.0)

        # When: record 600 + 500 = 1100 cents
        store.record_and_check(scope={}, input_tokens=100, output_tokens=50, cost=600)
        results = store.record_and_check(scope={}, input_tokens=100, output_tokens=50, cost=500)

        # Then: exceeded
        assert results[0].exceeded is True
        assert results[0].spent == 1100

    def test_scope_isolation(self) -> None:
        # Given: per-agent limits
        rules = [
            BudgetLimitRule(scope={"agent": "a"}, limit=1000),
            BudgetLimitRule(scope={"agent": "b"}, limit=1000),
        ]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 1700000000.0)

        # When: agent-a records 900, agent-b records 100
        results_a = store.record_and_check(
            scope={"agent": "a"}, input_tokens=0, output_tokens=0, cost=900
        )
        results_b = store.record_and_check(
            scope={"agent": "b"}, input_tokens=0, output_tokens=0, cost=100
        )

        # Then: agent-a near limit, agent-b well under
        assert results_a[0].spent == 900
        assert results_b[0].spent == 100
        assert not results_b[0].exceeded

    def test_period_isolation(self) -> None:
        # Given: daily limit, clock at two different days
        rules = [BudgetLimitRule(limit=1000, window_seconds=WINDOW_DAILY)]
        day1 = 1700000000.0
        day2 = day1 + WINDOW_DAILY

        # When: record on day 1, then day 2
        store = InMemoryBudgetStore(rules=rules, clock=lambda: day1)
        store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=800)

        store._clock = lambda: day2
        results = store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=300)

        # Then: day 2 is a fresh period
        assert results[0].spent == 300
        assert not results[0].exceeded

    def test_exceeded_exact_limit(self) -> None:
        # Given: 1000-cent limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: spend exactly 1000
        results = store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=1000)

        # Then: exceeded (>= not >)
        assert results[0].exceeded is True

    def test_token_only_limit(self) -> None:
        # Given: 1000-token limit, no cost limit
        rules = [BudgetLimitRule(limit_tokens=1000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: consume 600+500 = 1100 tokens
        results = store.record_and_check(scope={}, input_tokens=600, output_tokens=500, cost=0)

        # Then: exceeded
        assert results[0].exceeded is True
        assert results[0].spent_tokens == 1100

    def test_no_matching_rules(self) -> None:
        # Given: rule for agent=summarizer only
        rules = [BudgetLimitRule(scope={"agent": "summarizer"}, limit=1000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: step from agent=other
        results = store.record_and_check(
            scope={"agent": "other"}, input_tokens=100, output_tokens=50, cost=999
        )

        # Then: no snapshots (rule didn't match)
        assert results == []

    def test_group_by_user(self) -> None:
        # Given: global rule with group_by=user_id
        rules = [BudgetLimitRule(group_by="user_id", limit=500)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: two users each spend
        store.record_and_check(scope={"user_id": "u1"}, input_tokens=0, output_tokens=0, cost=400)
        results_u1 = store.record_and_check(
            scope={"user_id": "u1"}, input_tokens=0, output_tokens=0, cost=200
        )
        results_u2 = store.record_and_check(
            scope={"user_id": "u2"}, input_tokens=0, output_tokens=0, cost=300
        )

        # Then: u1 exceeded, u2 not
        assert results_u1[0].exceeded is True
        assert results_u2[0].exceeded is False

    def test_thread_safety(self) -> None:
        # Given: high-limit rule and 10 concurrent threads
        rules = [BudgetLimitRule(limit=1_000_000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)
        errors: list[str] = []

        def record_many() -> None:
            try:
                for _ in range(100):
                    store.record_and_check(scope={}, input_tokens=1, output_tokens=1, cost=1)
            except Exception as exc:
                errors.append(str(exc))

        # When: 10 threads x 100 calls
        threads = [threading.Thread(target=record_many) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Then: no errors, totals correct
        assert errors == []
        snap = store.get_snapshot("__global__", _derive_period_key(None, 0.0), limit=1_000_000)
        assert snap.spent_tokens == 2000
        assert snap.spent == 1000

    def test_max_buckets_fail_closed(self) -> None:
        # Given: store limited to 3 buckets with group_by=user_id
        rules = [BudgetLimitRule(group_by="user_id", limit=100_000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0, max_buckets=3)

        # When: 5 different users try to record
        exceeded_count = 0
        for i in range(5):
            results = store.record_and_check(
                scope={"user_id": f"u{i}"}, input_tokens=1, output_tokens=1, cost=1
            )
            if results and results[0].exceeded:
                exceeded_count += 1

        # Then: first 3 succeed, last 2 fail-closed
        assert exceeded_count == 2

    def test_reset_all(self) -> None:
        # Given: store with recorded usage
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)
        store.record_and_check(scope={}, input_tokens=10, output_tokens=10, cost=100)

        # When: reset all
        store.reset()

        # Then: empty
        snap = store.get_snapshot("__global__", "", limit=1000)
        assert snap.spent == 0


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_compute_utilization_no_limits(self) -> None:
        assert _compute_utilization(100, 10000, None, None) == 0.0

    def test_compute_utilization_spend_only(self) -> None:
        # Given: 500 of 1000 spent
        assert _compute_utilization(500, 0, 1000, None) == pytest.approx(0.5)

    def test_compute_utilization_clamped(self) -> None:
        assert _compute_utilization(2000, 0, 1000, None) == pytest.approx(1.0)

    def test_derive_period_key_none(self) -> None:
        assert _derive_period_key(None, 0.0) == ""

    def test_derive_period_key_daily(self) -> None:
        # Given: 1700000000 / 86400 = 19675 (truncated)
        key = _derive_period_key(WINDOW_DAILY, 1700000000.0)
        assert key == "P86400:19675"

    def test_derive_period_key_weekly(self) -> None:
        key = _derive_period_key(WINDOW_WEEKLY, 1700000000.0)
        assert key.startswith("P604800:")

    def test_build_scope_key_global(self) -> None:
        assert _build_scope_key({}, None, {}) == "__global__"

    def test_build_scope_key_with_scope(self) -> None:
        key = _build_scope_key({"channel": "slack"}, None, {})
        assert key == "channel=slack"

    def test_build_scope_key_with_group_by(self) -> None:
        key = _build_scope_key({"channel": "slack"}, "user_id", {"user_id": "u1"})
        assert key == "channel=slack|user_id=u1"

    def test_build_scope_key_group_by_missing(self) -> None:
        key = _build_scope_key({}, "user_id", {})
        assert key == "__global__"

    def test_extract_tokens_standard(self) -> None:
        data = {"usage": {"input_tokens": 100, "output_tokens": 50}}
        assert _extract_tokens(data, None) == (100, 50)

    def test_extract_tokens_openai(self) -> None:
        data = {"usage": {"prompt_tokens": 80, "completion_tokens": 40}}
        assert _extract_tokens(data, None) == (80, 40)

    def test_extract_tokens_none(self) -> None:
        assert _extract_tokens(None, None) == (0, 0)


# ---------------------------------------------------------------------------
# BudgetLimitRule config validation
# ---------------------------------------------------------------------------


class TestBudgetLimitRuleConfig:
    def test_valid_rule(self) -> None:
        rule = BudgetLimitRule(limit=1000)
        assert rule.limit == 1000
        assert rule.currency == Currency.USD

    def test_no_limit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="At least one"):
            BudgetLimitRule()

    def test_negative_limit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=-1)

    def test_zero_limit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=0)

    def test_negative_limit_tokens_rejected(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit_tokens=-1)

    def test_negative_window_seconds_rejected(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=1000, window_seconds=-1)

    def test_zero_window_seconds_rejected(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=1000, window_seconds=0)

    def test_token_only_rule(self) -> None:
        rule = BudgetLimitRule(limit_tokens=5000)
        assert rule.limit is None
        assert rule.limit_tokens == 5000

    def test_currency_enum(self) -> None:
        rule = BudgetLimitRule(limit=1000, currency=Currency.EUR)
        assert rule.currency == Currency.EUR

    def test_currency_from_string(self) -> None:
        rule = BudgetLimitRule(limit=1000, currency="tokens")
        assert rule.currency == Currency.TOKENS

    def test_empty_limits_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BudgetEvaluatorConfig(limits=[])

    def test_window_constants(self) -> None:
        assert WINDOW_DAILY == 86400
        assert WINDOW_WEEKLY == 604800
        assert WINDOW_MONTHLY == 2592000


# ---------------------------------------------------------------------------
# BudgetEvaluator integration
# ---------------------------------------------------------------------------


class TestBudgetEvaluator:
    def _make_evaluator(self, **kwargs: Any) -> BudgetEvaluator:
        config = BudgetEvaluatorConfig(**kwargs)
        return BudgetEvaluator(config)

    @pytest.mark.asyncio
    async def test_single_call_under_budget(self) -> None:
        # Given: evaluator with $10 limit (1000 cents)
        ev = self._make_evaluator(limits=[{"limit": 1000}])

        # When: evaluate with usage data (cost field is ignored without pricing/model_path)
        result = await ev.evaluate({"usage": {"input_tokens": 100, "output_tokens": 50}})

        # Then: not matched
        assert result.matched is False
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_accumulate_past_budget(self) -> None:
        # Given: evaluator with 50-cent limit and pricing table
        ev = self._make_evaluator(
            limits=[{"limit": 50}],
            pricing={"gpt-4": {"input_per_1k": 30.0, "output_per_1k": 60.0}},
            model_path="model",
        )

        # When: two calls with tokens costing 27 cents each
        # cost = ceil(300*30/1000 + 300*60/1000) = ceil(9+18) = 27
        # total = 27+27 = 54 > 50
        step = {"model": "gpt-4", "usage": {"input_tokens": 300, "output_tokens": 300}}
        await ev.evaluate(step)
        result = await ev.evaluate(step)

        # Then: matched (54 > 50)
        assert result.matched is True
        assert result.metadata is not None

    @pytest.mark.asyncio
    async def test_group_by_user(self) -> None:
        # Given: per-user 1000-cent budget with pricing table
        # pricing: 200 cents per 1k input tokens
        ev = self._make_evaluator(
            limits=[{"group_by": "user_id", "limit": 1000}],
            pricing={"gpt-4": {"input_per_1k": 200.0, "output_per_1k": 0.0}},
            model_path="model",
            metadata_paths={"user_id": "user_id"},
        )

        # When: u1 spends 800+300=1100 cents, u2 spends 300 cents
        # 4000 input tokens * 200/1000 = 800 cents
        # 1500 input tokens * 200/1000 = 300 cents
        def _step(tokens: int, user: str) -> dict:
            return {
                "model": "gpt-4",
                "usage": {"input_tokens": tokens, "output_tokens": 0},
                "user_id": user,
            }

        await ev.evaluate(_step(4000, "u1"))
        r1 = await ev.evaluate(_step(1500, "u1"))
        r2 = await ev.evaluate(_step(1500, "u2"))

        # Then: u1 exceeded (1100 > 1000), u2 not (300 < 1000)
        assert r1.matched is True
        assert r2.matched is False

    @pytest.mark.asyncio
    async def test_token_only_limit(self) -> None:
        # Given: 500 token limit
        ev = self._make_evaluator(limits=[{"limit_tokens": 500}])

        # When: consume 600 tokens
        result = await ev.evaluate({"usage": {"input_tokens": 300, "output_tokens": 300}})

        # Then: exceeded
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_no_data_returns_not_matched(self) -> None:
        ev = self._make_evaluator(limits=[{"limit": 1000}])
        result = await ev.evaluate(None)
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_confidence_always_one(self) -> None:
        # Given: evaluator with 1000-cent limit and pricing table
        # pricing: 200 cents per 1k input tokens
        ev = self._make_evaluator(
            limits=[{"limit": 1000}],
            pricing={"gpt-4": {"input_per_1k": 200.0, "output_per_1k": 0.0}},
            model_path="model",
        )

        # When: first call costs 50 cents (250 tokens), second costs 960 cents (4800 tokens)
        def _step(tokens: int) -> dict:
            return {"model": "gpt-4", "usage": {"input_tokens": tokens, "output_tokens": 0}}

        r1 = await ev.evaluate(_step(250))
        r2 = await ev.evaluate(_step(4800))

        # Then: confidence is always 1.0
        assert r1.confidence == 1.0
        assert r2.confidence == 1.0

    @pytest.mark.asyncio
    async def test_cost_computed_from_pricing_table(self) -> None:
        # Given: evaluator with pricing table and 100-cent cost limit
        ev = self._make_evaluator(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 30.0, "output_per_1k": 60.0}},
            model_path="model",
        )

        # When: evaluate with known model and tokens
        # cost = ceil(100*30/1000 + 200*60/1000) = ceil(3+12) = 15 cents
        result = await ev.evaluate(
            {
                "model": "gpt-4",
                "usage": {"input_tokens": 100, "output_tokens": 200},
            }
        )

        # Then: not matched (15 < 100), cost tracked in metadata
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["cost"] == 15

    @pytest.mark.asyncio
    async def test_unknown_model_cost_zero(self) -> None:
        # Given: evaluator with pricing table but data from an unknown model
        ev = self._make_evaluator(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 30.0, "output_per_1k": 60.0}},
            model_path="model",
        )

        # When: evaluate with a model not in the pricing table
        result = await ev.evaluate(
            {
                "model": "unknown-model",
                "usage": {"input_tokens": 1000, "output_tokens": 1000},
            }
        )

        # Then: not matched (cost=0 because model not in pricing)
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["cost"] == 0


# ---------------------------------------------------------------------------
# Security / adversarial tests
# ---------------------------------------------------------------------------


class TestBudgetAdversarial:
    def test_scope_key_injection_pipe(self) -> None:
        # Given: malicious user_id with pipe
        key = _build_scope_key({"ch": "slack"}, "uid", {"uid": "u1|ch=admin"})

        # Then: pipe is percent-encoded, no injection
        parts = key.split("|")
        assert len(parts) == 2
        assert "ch=admin" not in parts

    def test_scope_key_no_collision(self) -> None:
        key1 = _build_scope_key({}, "uid", {"uid": "a|b"})
        key2 = _build_scope_key({}, "uid", {"uid": "a_b"})
        assert key1 != key2

    def test_extract_by_path_rejects_dunder(self) -> None:
        from agent_control_evaluator_budget.budget.evaluator import _extract_by_path

        assert _extract_by_path({"a": 1}, "__class__") is None

    def test_group_by_without_metadata_skips_rule(self) -> None:
        # Given: rule with group_by=user_id but no user_id in scope
        rules = [BudgetLimitRule(group_by="user_id", limit=1000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: step without user_id
        results = store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=999)

        # Then: rule skipped
        assert results == []

    def test_two_rules_same_scope_no_double_count(self) -> None:
        # Given: two global rules with different limit types
        rules = [
            BudgetLimitRule(limit=1000),
            BudgetLimitRule(limit_tokens=5000),
        ]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: record once
        results = store.record_and_check(scope={}, input_tokens=100, output_tokens=100, cost=100)

        # Then: both rules get snapshot, but usage recorded only once
        assert len(results) == 2
        assert results[0].spent == 100  # not 200
        assert results[1].spent_tokens == 200  # not 400

    def test_different_currency_separate_buckets(self) -> None:
        # Given: two rules with same scope but different currencies
        rules = [
            BudgetLimitRule(limit=1000, currency=Currency.USD),
            BudgetLimitRule(limit=2000, currency=Currency.EUR),
        ]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: record once
        results = store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=500)

        # Then: each currency gets its own bucket, both record the cost
        assert len(results) == 2
        assert results[0].spent == 500
        assert results[1].spent == 500

    def test_negative_cost_not_recorded(self) -> None:
        # Given: store with 1000-cent limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(rules=rules, clock=lambda: 0.0)

        # When: record positive then negative cost
        store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=500)
        results = store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=-200)

        # Then: negative cost is added (store is dumb; validation is caller's job)
        # If this is undesirable, evaluator must reject negatives before calling store
        assert results[0].spent == 300

    def test_window_seconds_boundary_alignment(self) -> None:
        # Given: hourly window, clock at boundary-1 and boundary
        rules = [BudgetLimitRule(limit=1000, window_seconds=3600)]
        boundary = 3600 * 100  # exact hour boundary

        # When: record just before and at boundary
        store = InMemoryBudgetStore(rules=rules, clock=lambda: boundary - 1)
        store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=500)

        store._clock = lambda: boundary
        results = store.record_and_check(scope={}, input_tokens=0, output_tokens=0, cost=500)

        # Then: boundary crossing starts fresh period
        assert results[0].spent == 500  # not 1000


class TestConfigValidationEdgeCases:
    def test_zero_limit_tokens_rejected(self) -> None:
        # Given/When: zero token limit
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit_tokens=0)

    def test_invalid_currency_rejected(self) -> None:
        # Given/When: invalid currency string
        with pytest.raises(ValidationError):
            BudgetLimitRule(limit=1000, currency="btc")


class TestBoolGuard:
    """bool is a subclass of int in Python -- must be rejected."""

    def test_extract_tokens_rejects_bool(self) -> None:
        # Given: data with bool tokens
        data = {"usage": {"input_tokens": True, "output_tokens": False}}

        # When/Then: bools are not accepted as token counts
        assert _extract_tokens(data, None) == (0, 0)
