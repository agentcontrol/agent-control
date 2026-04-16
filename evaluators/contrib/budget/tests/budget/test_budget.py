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
    ModelPricing,
)
from agent_control_evaluator_budget.budget.evaluator import (
    BudgetEvaluator,
    _extract_tokens,
    clear_budget_stores,
    get_or_create_store,
)
from agent_control_evaluator_budget.budget.memory_store import (
    InMemoryBudgetStore,
    _build_scope_key,
    _compute_utilization,
    _derive_period_key,
)


@pytest.fixture(autouse=True)
def _clean_store_registry() -> None:
    """Clear the module-level store registry before each test."""
    clear_budget_stores()


# ---------------------------------------------------------------------------
# InMemoryBudgetStore
# ---------------------------------------------------------------------------


class TestInMemoryBudgetStore:
    @pytest.mark.asyncio
    async def test_single_record_under_limit(self) -> None:
        # Given: store with a $10 daily limit (1000 cents)
        rules = [BudgetLimitRule(limit=1000, window_seconds=WINDOW_DAILY)]
        store = InMemoryBudgetStore(clock=lambda: 1700000000.0)

        # When: record 300 cents of usage
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=100, output_tokens=50, cost=300.0
        )

        # Then: not breached, ratio ~0.3
        assert len(results) == 1
        assert not results[0].exceeded
        assert results[0].utilization == pytest.approx(0.3, abs=0.01)

    @pytest.mark.asyncio
    async def test_accumulation_triggers_breach(self) -> None:
        # Given: store with 1000-cent limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 1700000000.0)

        # When: record 600 + 500 = 1100 cents
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=100, output_tokens=50, cost=600.0
        )
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=100, output_tokens=50, cost=500.0
        )

        # Then: exceeded
        assert results[0].exceeded is True
        assert results[0].spent == 1100

    @pytest.mark.asyncio
    async def test_scope_isolation(self) -> None:
        # Given: per-agent limits
        rules = [
            BudgetLimitRule(scope={"agent": "a"}, limit=1000),
            BudgetLimitRule(scope={"agent": "b"}, limit=1000),
        ]
        store = InMemoryBudgetStore(clock=lambda: 1700000000.0)

        # When: agent-a records 900, agent-b records 100
        results_a = await store.record_and_check(
            rules=rules, scope={"agent": "a"}, input_tokens=0, output_tokens=0, cost=900.0
        )
        results_b = await store.record_and_check(
            rules=rules, scope={"agent": "b"}, input_tokens=0, output_tokens=0, cost=100.0
        )

        # Then: agent-a near limit, agent-b well under
        assert results_a[0].spent == 900
        assert results_b[0].spent == 100
        assert not results_b[0].exceeded

    @pytest.mark.asyncio
    async def test_period_isolation(self) -> None:
        # Given: daily limit, clock at two different days
        rules = [BudgetLimitRule(limit=1000, window_seconds=WINDOW_DAILY)]
        day1 = 1700000000.0
        day2 = day1 + WINDOW_DAILY

        # When: record on day 1, then day 2
        store = InMemoryBudgetStore(clock=lambda: day1)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=800.0
        )

        store._clock = lambda: day2
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=300.0
        )

        # Then: day 2 is a fresh period
        assert results[0].spent == 300
        assert not results[0].exceeded

    @pytest.mark.asyncio
    async def test_exceeded_exact_limit(self) -> None:
        # Given: 1000-cent limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: spend exactly 1000
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1000.0
        )

        # Then: exceeded (>= not >)
        assert results[0].exceeded is True

    @pytest.mark.asyncio
    async def test_token_only_limit(self) -> None:
        # Given: 1000-token limit, no cost limit
        rules = [BudgetLimitRule(limit=1000, limit_unit="tokens")]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: consume 600+500 = 1100 tokens
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=600, output_tokens=500, cost=0.0
        )

        # Then: exceeded
        assert results[0].exceeded is True
        assert results[0].spent_tokens == 1100

    @pytest.mark.asyncio
    async def test_no_matching_rules(self) -> None:
        # Given: rule for agent=summarizer only
        rules = [BudgetLimitRule(scope={"agent": "summarizer"}, limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: step from agent=other
        results = await store.record_and_check(
            rules=rules, scope={"agent": "other"}, input_tokens=100, output_tokens=50, cost=999.0
        )

        # Then: no snapshots (rule didn't match)
        assert results == []

    @pytest.mark.asyncio
    async def test_group_by_user(self) -> None:
        # Given: global rule with group_by=user_id
        rules = [BudgetLimitRule(group_by="user_id", limit=500)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: two users each spend
        await store.record_and_check(
            rules=rules, scope={"user_id": "u1"}, input_tokens=0, output_tokens=0, cost=400.0
        )
        results_u1 = await store.record_and_check(
            rules=rules, scope={"user_id": "u1"}, input_tokens=0, output_tokens=0, cost=200.0
        )
        results_u2 = await store.record_and_check(
            rules=rules, scope={"user_id": "u2"}, input_tokens=0, output_tokens=0, cost=300.0
        )

        # Then: u1 exceeded, u2 not
        assert results_u1[0].exceeded is True
        assert results_u2[0].exceeded is False

    def test_thread_safety(self) -> None:
        # Given: high-limit rule and 10 concurrent threads
        # Each thread calls asyncio.run(store.record_and_check(rules=rules, ...)) -- the async
        # method wraps a sync critical section, so threading.Lock prevents races.
        rules = [BudgetLimitRule(limit=1_000_000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)
        errors: list[str] = []

        import asyncio

        def record_many() -> None:
            try:
                for _ in range(100):
                    asyncio.run(
                        store.record_and_check(
                            rules=rules, scope={}, input_tokens=1, output_tokens=1, cost=1.0
                        )
                    )
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

    @pytest.mark.asyncio
    async def test_max_buckets_fail_closed(self) -> None:
        # Given: store limited to 3 buckets with group_by=user_id
        rules = [BudgetLimitRule(group_by="user_id", limit=100_000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0, max_buckets=3)

        # When: 5 different users try to record
        exceeded_count = 0
        for i in range(5):
            results = await store.record_and_check(
                rules=rules, scope={"user_id": f"u{i}"}, input_tokens=1, output_tokens=1, cost=1.0
            )
            if results and results[0].exceeded:
                exceeded_count += 1

        # Then: first 3 succeed, last 2 fail-closed
        assert exceeded_count == 2

    @pytest.mark.asyncio
    async def test_reset_all(self) -> None:
        # Given: store with recorded usage
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=10, output_tokens=10, cost=100.0
        )

        # When: reset all
        store.reset()

        # Then: empty
        snap = store.get_snapshot("__global__", "", limit=1000)
        assert snap.spent == 0

    @pytest.mark.asyncio
    async def test_float_accumulation_precision(self) -> None:
        # Given: store with 1-cent limit
        rules = [BudgetLimitRule(limit=1)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: 100 calls each costing 0.003 cents (total = 0.3 cents)
        for _ in range(100):
            await store.record_and_check(
                rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=0.003
            )

        # Then: not exceeded (0.3 < 1), no ceil-per-call overcount
        snap = store.get_snapshot("__global__", "", limit=1)
        assert not snap.exceeded
        assert snap.spent == 0  # round(0.3) = 0

    @pytest.mark.asyncio
    async def test_float_accumulation_eventual_breach(self) -> None:
        # Given: store with 1-cent limit
        rules = [BudgetLimitRule(limit=1)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: 400 calls each costing 0.003 cents (total = 1.2 cents)
        for _ in range(400):
            results = await store.record_and_check(
                rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=0.003
            )

        # Then: exceeded (1.2 >= 1)
        assert results[0].exceeded is True


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtilities:
    def test_compute_utilization_no_limits(self) -> None:
        # Given/When: no limits set / Then: 0.0
        assert _compute_utilization(100.0, 10000, None, "usd_cents") == 0.0

    def test_compute_utilization_spend_only(self) -> None:
        # Given: 500 of 1000 spent / Then: 0.5
        assert _compute_utilization(500.0, 0, 1000, "usd_cents") == pytest.approx(0.5)

    def test_compute_utilization_clamped(self) -> None:
        # Given: overspent / Then: clamped to 1.0
        assert _compute_utilization(2000.0, 0, 1000, "usd_cents") == pytest.approx(1.0)

    def test_compute_utilization_negative_clamped_to_zero(self) -> None:
        # Given: refund made the accumulator go negative
        # When: utilization is computed
        # Then: clamped to 0.0 (BudgetSnapshot.utilization contract)
        assert _compute_utilization(-150.0, 0, 100, "usd_cents") == 0.0
        # And: negative tokens (not currently reachable but defensively clamped)
        assert _compute_utilization(0.0, -50, 100, "tokens") == 0.0

    def test_parse_period_key_valid(self) -> None:
        # Given: well-formed period key / Then: parsed tuple
        from agent_control_evaluator_budget.budget.memory_store import _parse_period_key

        assert _parse_period_key("P86400:19675") == (86400, 19675)
        assert _parse_period_key("P3600:0") == (3600, 0)

    def test_parse_period_key_malformed(self) -> None:
        # Given: empty, missing, or non-numeric period keys
        # When: parsed
        # Then: None returned (never raises)
        from agent_control_evaluator_budget.budget.memory_store import _parse_period_key

        assert _parse_period_key("") is None  # cumulative sentinel
        assert _parse_period_key("P") is None  # no separator
        assert _parse_period_key("P:1") is None  # empty window
        assert _parse_period_key("P86400:") is None  # empty index
        assert _parse_period_key("Pabc:1") is None  # non-numeric window
        assert _parse_period_key("P86400:xyz") is None  # non-numeric index
        assert _parse_period_key("X86400:1") is None  # wrong prefix
        assert _parse_period_key("PP86400:1") is None  # double P

    def test_derive_period_key_none(self) -> None:
        # Given: no window / Then: empty key
        assert _derive_period_key(None, 0.0) == ""

    def test_derive_period_key_daily(self) -> None:
        # Given: daily window at 1700000000 / Then: epoch-aligned key
        key = _derive_period_key(WINDOW_DAILY, 1700000000.0)
        assert key == "P86400:19675"

    def test_derive_period_key_weekly(self) -> None:
        # Given: weekly window / Then: key starts with P604800:
        key = _derive_period_key(WINDOW_WEEKLY, 1700000000.0)
        assert key.startswith("P604800:")

    def test_build_scope_key_global(self) -> None:
        # Given: empty scope / Then: __global__
        assert _build_scope_key({}, None, {}) == "__global__"

    def test_build_scope_key_with_scope(self) -> None:
        # Given: channel scope / Then: channel=slack
        key = _build_scope_key({"channel": "slack"}, None, {})
        assert key == "channel=slack"

    def test_build_scope_key_with_group_by(self) -> None:
        # Given: scope + group_by / Then: combined key
        key = _build_scope_key({"channel": "slack"}, "user_id", {"user_id": "u1"})
        assert key == "channel=slack|user_id=u1"

    def test_build_scope_key_group_by_missing(self) -> None:
        # Given: group_by field not in scope / Then: __global__
        key = _build_scope_key({}, "user_id", {})
        assert key == "__global__"

    def test_extract_tokens_standard(self) -> None:
        # Given: standard token fields / Then: extracted
        data = {"usage": {"input_tokens": 100, "output_tokens": 50}}
        assert _extract_tokens(data, None) == (100, 50)

    def test_extract_tokens_openai(self) -> None:
        # Given: OpenAI-style fields / Then: extracted
        data = {"usage": {"prompt_tokens": 80, "completion_tokens": 40}}
        assert _extract_tokens(data, None) == (80, 40)

    def test_extract_tokens_none(self) -> None:
        # Given: None data / Then: (0, 0)
        assert _extract_tokens(None, None) == (0, 0)


# ---------------------------------------------------------------------------
# BudgetLimitRule config validation
# ---------------------------------------------------------------------------


class TestBudgetLimitRuleConfig:
    def test_valid_rule(self) -> None:
        # Given/When: valid limit / Then: accepted
        rule = BudgetLimitRule(limit=1000)
        assert rule.limit == 1000

    def test_no_limit_rejected(self) -> None:
        # Given/When: no limit / Then: rejected
        with pytest.raises(ValidationError, match="Field required"):
            BudgetLimitRule()

    def test_negative_limit_rejected(self) -> None:
        # Given/When: negative limit / Then: rejected
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=-1)

    def test_zero_limit_rejected(self) -> None:
        # Given/When: zero limit / Then: rejected
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=0)

    def test_negative_window_seconds_rejected(self) -> None:
        # Given/When: negative window_seconds / Then: rejected
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=1000, window_seconds=-1)

    def test_zero_window_seconds_rejected(self) -> None:
        # Given/When: zero window_seconds / Then: rejected
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=1000, window_seconds=0)

    def test_token_only_rule(self) -> None:
        # Given/When: token limit_unit / Then: accepted
        rule = BudgetLimitRule(limit=5000, limit_unit="tokens")
        assert rule.limit == 5000
        assert rule.limit_unit == "tokens"

    def test_empty_limits_rejected(self) -> None:
        # Given/When: empty limits list / Then: rejected
        with pytest.raises(ValidationError):
            BudgetEvaluatorConfig(limits=[])

    def test_window_constants(self) -> None:
        # Given/When/Then: constants have expected values
        assert WINDOW_DAILY == 86400
        assert WINDOW_WEEKLY == 604800
        assert WINDOW_MONTHLY == 2592000


class TestModelPricing:
    def test_model_pricing_validation_requires_pricing_for_cost_rules(self) -> None:
        # Given: a cost-based rule without pricing
        # When/Then: config validation rejects it
        with pytest.raises(ValidationError, match="pricing is required"):
            BudgetEvaluatorConfig(limits=[BudgetLimitRule(limit=100)])

    def test_model_pricing_token_rule_no_pricing_ok(self) -> None:
        # Given: a token-only rule without pricing
        # When: config is created
        config = BudgetEvaluatorConfig(limits=[BudgetLimitRule(limit=100, limit_unit="tokens")])

        # Then: no pricing table is required
        assert config.pricing is None


# ---------------------------------------------------------------------------
# BudgetEvaluator integration
# ---------------------------------------------------------------------------


class TestBudgetEvaluator:
    def _make_evaluator(self, **kwargs: Any) -> BudgetEvaluator:
        config = BudgetEvaluatorConfig(**kwargs)
        return BudgetEvaluator(config)

    @pytest.mark.asyncio
    async def test_single_call_under_budget(self) -> None:
        # Given: evaluator with 1000-token limit (token-only, no pricing needed)
        ev = self._make_evaluator(limits=[{"limit": 1000, "limit_unit": "tokens"}])

        # When: evaluate with usage data
        result = await ev.evaluate({"usage": {"input_tokens": 100, "output_tokens": 50}})

        # Then: not matched (150 < 1000)
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
        # cost = (300*30 + 300*60) / 1000 = 27.0
        # total = 27 + 27 = 54 > 50
        step = {"model": "gpt-4", "usage": {"input_tokens": 300, "output_tokens": 300}}
        await ev.evaluate(step)
        result = await ev.evaluate(step)

        # Then: matched (54 > 50)
        assert result.matched is True
        assert result.metadata is not None

    @pytest.mark.asyncio
    async def test_group_by_user(self) -> None:
        # Given: per-user 1000-cent budget with pricing table
        ev = self._make_evaluator(
            limits=[{"group_by": "user_id", "limit": 1000}],
            pricing={"gpt-4": {"input_per_1k": 200.0, "output_per_1k": 0.0}},
            model_path="model",
            metadata_paths={"user_id": "user_id"},
        )

        # When: u1 spends 800+300=1100 cents, u2 spends 300 cents
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
        ev = self._make_evaluator(limits=[{"limit": 500, "limit_unit": "tokens"}])

        # When: consume 600 tokens
        result = await ev.evaluate({"usage": {"input_tokens": 300, "output_tokens": 300}})

        # Then: exceeded
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_no_data_returns_not_matched(self) -> None:
        # Given: evaluator / When: None data / Then: not matched
        ev = self._make_evaluator(limits=[{"limit": 1000}], pricing={}, model_path="model")
        result = await ev.evaluate(None)
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_confidence_always_one(self) -> None:
        # Given: evaluator with 1000-cent limit and pricing table
        ev = self._make_evaluator(
            limits=[{"limit": 1000}],
            pricing={"gpt-4": {"input_per_1k": 200.0, "output_per_1k": 0.0}},
            model_path="model",
        )

        # When: first call costs 50 cents, second costs 960 cents
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
        # cost = (100*30 + 200*60) / 1000 = 15.0 cents
        result = await ev.evaluate(
            {
                "model": "gpt-4",
                "usage": {"input_tokens": 100, "output_tokens": 200},
            }
        )

        # Then: not matched (15 < 100), cost tracked in metadata
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["cost"] == pytest.approx(15.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_unknown_model_cost_zero(self) -> None:
        # Given: evaluator with warn mode and data from an unknown model
        ev = self._make_evaluator(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 30.0, "output_per_1k": 60.0}},
            model_path="model",
            unknown_model_behavior="warn",
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
        assert result.metadata["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_small_cost_no_overcount(self) -> None:
        # Given: evaluator with 1-cent limit, pricing yields 0.003 cents per call
        ev = self._make_evaluator(
            limits=[{"limit": 1}],
            pricing={"gpt-4": {"input_per_1k": 0.03, "output_per_1k": 0.0}},
            model_path="model",
        )
        step = {"model": "gpt-4", "usage": {"input_tokens": 100, "output_tokens": 0}}

        # When: 100 calls (total cost = 0.3 cents, should NOT exceed 1 cent)
        for _ in range(100):
            result = await ev.evaluate(step)

        # Then: not exceeded (float accumulation, no per-call ceil)
        assert result.matched is False


class TestBudgetIdSemantics:
    @pytest.mark.asyncio
    async def test_same_budget_id_shares_store(self) -> None:
        # Given: two evaluators with the same budget_id
        config1 = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            budget_id="shared",
            pricing={"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}},
            model_path="model",
        )
        config2 = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            budget_id="shared",
            pricing={"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}},
            model_path="model",
        )
        ev1 = BudgetEvaluator(config1)
        ev2 = BudgetEvaluator(config2)
        step = {"model": "gpt-4", "usage": {"input_tokens": 500, "output_tokens": 0}}

        # When: each evaluator records a 50-cent call
        first = await ev1.evaluate(step)
        second = await ev2.evaluate(step)

        # Then: spend is shared and the second call reaches the 100-cent limit
        assert first.matched is False
        assert second.matched is True

    @pytest.mark.asyncio
    async def test_different_budget_id_isolates_store(self) -> None:
        # Given: two evaluators with different budget_id values
        config1 = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            budget_id="pool-a",
            pricing={"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}},
            model_path="model",
        )
        config2 = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            budget_id="pool-b",
            pricing={"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}},
            model_path="model",
        )
        ev1 = BudgetEvaluator(config1)
        ev2 = BudgetEvaluator(config2)
        step = {"model": "gpt-4", "usage": {"input_tokens": 500, "output_tokens": 0}}

        # When: each evaluator records a 50-cent call
        first = await ev1.evaluate(step)
        second = await ev2.evaluate(step)

        # Then: each pool remains below the 100-cent limit independently
        assert first.matched is False
        assert second.matched is False


class TestUnknownModelBehavior:
    @pytest.mark.asyncio
    async def test_unknown_model_block_default(self) -> None:
        # Given: a cost rule with pricing that does not include the incoming model
        config = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 10.0, "output_per_1k": 20.0}},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: the step uses an unknown model
        result = await evaluator.evaluate(
            {"model": "unknown-model", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: the evaluator fails closed and reports the unknown model
        assert result.matched is True
        assert result.metadata is not None
        assert result.metadata["unknown_model"] == "unknown-model"

    @pytest.mark.asyncio
    async def test_unknown_model_warn(self) -> None:
        # Given: a cost rule configured to warn on unknown models
        config = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 10.0, "output_per_1k": 20.0}},
            model_path="model",
            unknown_model_behavior="warn",
        )
        evaluator = BudgetEvaluator(config)

        # When: the step uses an unknown model
        result = await evaluator.evaluate(
            {"model": "unknown-model", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: the evaluator treats cost as 0 and does not block
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["cost"] == 0.0
        assert result.metadata["all_snapshots"][0]["spent_tokens"] == 150

    @pytest.mark.asyncio
    async def test_unknown_model_token_only_unaffected(self) -> None:
        # Given: a token-only rule with a pricing table that does not include
        # the incoming model and the default block setting
        config = BudgetEvaluatorConfig(
            limits=[{"limit": 1000, "limit_unit": "tokens"}],
            pricing={},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: the step uses an unknown model below the token limit
        result = await evaluator.evaluate(
            {"model": "unknown-model", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: unknown-model blocking is not applied without a cost rule
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["all_snapshots"][0]["spent_tokens"] == 150

    @pytest.mark.asyncio
    async def test_pricing_lookup_is_case_sensitive(self) -> None:
        # Given: pricing for lowercase gpt-4
        config = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 10.0, "output_per_1k": 20.0}},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: the step uses a differently cased model name
        result = await evaluator.evaluate(
            {"model": "GPT-4", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: lookup is case-sensitive and the default behavior fails closed
        assert result.matched is True
        assert result.metadata is not None
        assert result.metadata["unknown_model"] == "GPT-4"

    @pytest.mark.asyncio
    async def test_known_model_not_blocked(self) -> None:
        # Given: a cost rule whose pricing includes the incoming model
        config = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 10.0, "output_per_1k": 20.0}},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: the step uses the known model
        result = await evaluator.evaluate(
            {"model": "gpt-4", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: normal budget evaluation runs
        assert result.matched is False
        assert result.metadata is not None
        assert "unknown_model" not in result.metadata


# ---------------------------------------------------------------------------
# Store registry
# ---------------------------------------------------------------------------


class TestStoreRegistry:
    def test_same_config_returns_same_store(self) -> None:
        # Given: two configs with identical parameters
        config = BudgetEvaluatorConfig(limits=[{"limit": 1000}], pricing={}, model_path="model")

        # When: get store twice
        store1 = get_or_create_store(config)
        store2 = get_or_create_store(config)

        # Then: same object
        assert store1 is store2

    def test_different_budget_id_returns_different_store(self) -> None:
        # Given: two configs with different budget ids
        config1 = BudgetEvaluatorConfig(
            limits=[{"limit": 1000}], budget_id="a", pricing={}, model_path="model",
        )
        config2 = BudgetEvaluatorConfig(
            limits=[{"limit": 1000}], budget_id="b", pricing={}, model_path="model",
        )

        # When: get stores
        store1 = get_or_create_store(config1)
        store2 = get_or_create_store(config2)

        # Then: different objects
        assert store1 is not store2

    def test_clear_budget_stores(self) -> None:
        # Given: a registered store
        config = BudgetEvaluatorConfig(limits=[{"limit": 1000}], pricing={}, model_path="model")
        store1 = get_or_create_store(config)

        # When: clear all stores
        clear_budget_stores()
        store2 = get_or_create_store(config)

        # Then: new store (old one is gone)
        assert store1 is not store2

    @pytest.mark.asyncio
    async def test_evaluator_uses_registry(self) -> None:
        # Given: two evaluators with same config
        config = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            pricing={"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}},
            model_path="model",
        )
        ev1 = BudgetEvaluator(config)
        ev2 = BudgetEvaluator(config)

        # When: ev1 records usage, ev2 checks
        step = {"model": "gpt-4", "usage": {"input_tokens": 500, "output_tokens": 0}}
        await ev1.evaluate(step)
        result = await ev2.evaluate(step)

        # Then: ev2 sees ev1's accumulated spend (shared store via registry)
        assert result.matched is True  # 50 + 50 = 100 >= 100

    @pytest.mark.asyncio
    async def test_same_budget_id_shares_buckets_but_not_rules(self) -> None:
        # Given: two configs sharing budget_id but using different limits
        pricing = {"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}}
        config1 = BudgetEvaluatorConfig(
            limits=[{"limit": 100}],
            budget_id="shared",
            pricing=pricing,
            model_path="model",
        )
        config2 = BudgetEvaluatorConfig(
            limits=[{"limit": 1000}],
            budget_id="shared",
            pricing=pricing,
            model_path="model",
        )
        ev1 = BudgetEvaluator(config1)
        ev2 = BudgetEvaluator(config2)
        step = {"model": "gpt-4", "usage": {"input_tokens": 600, "output_tokens": 0}}

        # When: the first evaluator records 60 cents, then the second records
        # another 60 cents into the same budget bucket
        first = await ev1.evaluate(step)
        second = await ev2.evaluate(step)

        # Then: the second evaluator sees shared bucket state (120 cents) but
        # evaluates against its own 1000-cent rule, not config1's 100-cent rule.
        assert first.matched is False
        assert second.matched is False
        assert second.metadata is not None
        assert second.metadata["all_snapshots"][0]["spent"] == 120
        assert second.metadata["all_snapshots"][0]["limit"] == 1000


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

    @pytest.mark.asyncio
    async def test_group_by_without_metadata_skips_rule(self) -> None:
        # Given: rule with group_by=user_id but no user_id in scope
        rules = [BudgetLimitRule(group_by="user_id", limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: step without user_id
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=999.0
        )

        # Then: rule skipped
        assert results == []

    @pytest.mark.asyncio
    async def test_two_rules_same_scope_no_double_count(self) -> None:
        # Given: two global rules with different limit types
        rules = [
            BudgetLimitRule(limit=1000),
            BudgetLimitRule(limit=5000, limit_unit="tokens"),
        ]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: record once
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=100, output_tokens=100, cost=100.0
        )

        # Then: both rules get snapshot, but usage recorded only once
        assert len(results) == 2
        assert results[0].spent == 100  # not 200
        assert results[1].spent_tokens == 200  # not 400

    @pytest.mark.asyncio
    async def test_negative_cost_reduces_spend(self) -> None:
        # Given: store with 1000-cent limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: record positive then negative cost
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=500.0
        )
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=-200.0
        )

        # Then: negative cost reduces spend (store does not clamp; validation is caller's job)
        assert results[0].spent == 300

    @pytest.mark.asyncio
    async def test_window_seconds_boundary_alignment(self) -> None:
        # Given: hourly window, clock at boundary-1 and boundary
        rules = [BudgetLimitRule(limit=1000, window_seconds=3600)]
        boundary = 3600 * 100  # exact hour boundary

        # When: record just before and at boundary
        store = InMemoryBudgetStore(clock=lambda: boundary - 1)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=500.0
        )

        store._clock = lambda: boundary
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=500.0
        )

        # Then: boundary crossing starts fresh period
        assert results[0].spent == 500  # not 1000


class TestConfigValidationEdgeCases:
    def test_zero_token_limit_rejected(self) -> None:
        # Given/When: zero token limit
        with pytest.raises(ValidationError, match="positive"):
            BudgetLimitRule(limit=0, limit_unit="tokens")


class TestBoolGuard:
    """bool is a subclass of int in Python -- must be rejected."""

    def test_extract_tokens_rejects_bool(self) -> None:
        # Given: data with bool tokens
        data = {"usage": {"input_tokens": True, "output_tokens": False}}

        # When/Then: bools are not accepted as token counts
        assert _extract_tokens(data, None) == (0, 0)


# ---------------------------------------------------------------------------
# Store registry robustness
# ---------------------------------------------------------------------------


class TestStoreRegistryRobustness:
    def test_concurrent_get_or_create_store(self) -> None:
        # Given: 10 threads requesting the same config concurrently
        config = BudgetEvaluatorConfig(limits=[{"limit": 1000}], pricing={}, model_path="model")
        stores: list[Any] = []
        lock = threading.Lock()

        def get_store() -> None:
            s = get_or_create_store(config)
            with lock:
                stores.append(s)

        # When: 10 threads call get_or_create_store simultaneously
        threads = [threading.Thread(target=get_store) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Then: all threads got the same store object
        assert len(stores) == 10
        assert all(s is stores[0] for s in stores)

    @pytest.mark.asyncio
    async def test_evaluator_cache_eviction_preserves_budget_state(self) -> None:
        # Given: evaluator that has recorded usage
        from agent_control_evaluators._factory import (
            clear_evaluator_cache,
        )

        config = BudgetEvaluatorConfig(
            limits=[{"limit": 1000}],
            pricing={"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}},
            model_path="model",
        )
        ev = BudgetEvaluator(config)
        step = {"model": "gpt-4", "usage": {"input_tokens": 500, "output_tokens": 0}}
        await ev.evaluate(step)

        # When: simulate LRU eviction by clearing the evaluator cache
        clear_evaluator_cache()

        # Then: budget state survives (stored in module-level registry, not on evaluator)
        ev2 = BudgetEvaluator(config)
        result = await ev2.evaluate(step)

        # 500 tokens * 100 cents/1k = 50.0 cents per call.
        # Two calls = 100.0 cents total. limit=1000, so not exceeded.
        # Key assertion: state IS preserved across evaluator re-creation.
        assert result.metadata is not None
        assert result.metadata["cost"] == pytest.approx(50.0, abs=0.1)
        # The all_snapshots should show accumulated spend from both calls
        snaps = result.metadata["all_snapshots"]
        assert snaps[0]["spent"] == 100  # round(50.0 + 50.0) = 100, not 50


# ---------------------------------------------------------------------------
# _estimate_cost edge cases
# ---------------------------------------------------------------------------


class TestRoundingBoundary:
    @pytest.mark.asyncio
    async def test_spent_half_cent_below_limit_not_exceeded(self) -> None:
        # Given: store with 1000-cent limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: spend 999.5 cents (just below limit)
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=999.5
        )

        # Then: not exceeded (999.5 < 1000), spent display < limit
        assert results[0].exceeded is False
        assert results[0].spent < results[0].limit  # no contradiction

    @pytest.mark.asyncio
    async def test_spent_display_never_exceeds_actual(self) -> None:
        # Given: store with 100-cent limit
        rules = [BudgetLimitRule(limit=100)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: spend 99.9 cents
        results = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=99.9
        )

        # Then: floor truncation means spent=99, not rounded to 100
        assert results[0].spent == 99
        assert results[0].exceeded is False


class TestConfigKeyOrdering:
    def test_limits_order_does_not_affect_same_budget_id_store_identity(self) -> None:
        # Given: two configs with same budget_id and rules in different order
        rule_a = {"limit": 1000, "scope": {"agent": "a"}}
        rule_b = {"limit": 2000, "scope": {"agent": "b"}}
        config1 = BudgetEvaluatorConfig(
            limits=[rule_a, rule_b], budget_id="ordered", pricing={}, model_path="model",
        )
        config2 = BudgetEvaluatorConfig(
            limits=[rule_b, rule_a], budget_id="ordered", pricing={}, model_path="model",
        )

        # When: get stores for both
        store1 = get_or_create_store(config1)
        store2 = get_or_create_store(config2)

        # Then: same store (order-independent)
        assert store1 is store2


class TestEstimateCostEdgeCases:
    def test_nan_rate_returns_zero(self) -> None:
        from agent_control_evaluator_budget.budget.evaluator import _estimate_cost

        # Given: pricing table with NaN rate
        pricing = {"gpt-4": ModelPricing(input_per_1k=float("nan"), output_per_1k=0.0)}

        # When: estimate cost
        cost = _estimate_cost("gpt-4", 1000, 0, pricing)

        # Then: returns 0.0 (NaN guard)
        assert cost == 0.0

    def test_inf_rate_returns_zero(self) -> None:
        from agent_control_evaluator_budget.budget.evaluator import _estimate_cost

        # Given: pricing table with Inf rate
        pricing = {"gpt-4": ModelPricing(input_per_1k=float("inf"), output_per_1k=0.0)}

        # When: estimate cost
        cost = _estimate_cost("gpt-4", 1000, 0, pricing)

        # Then: returns 0.0 (Inf guard)
        assert cost == 0.0

    def test_negative_rate_returns_zero(self) -> None:
        from agent_control_evaluator_budget.budget.evaluator import _estimate_cost

        # Given: pricing table with negative rate
        pricing = {"gpt-4": ModelPricing(input_per_1k=-10.0, output_per_1k=0.0)}

        # When: estimate cost
        cost = _estimate_cost("gpt-4", 1000, 0, pricing)

        # Then: returns 0.0 (negative guard)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# Nested model_path extraction
# ---------------------------------------------------------------------------


class TestNestedModelPath:
    @pytest.mark.asyncio
    async def test_nested_model_path(self) -> None:
        # Given: evaluator with nested model_path
        ev = BudgetEvaluator(
            BudgetEvaluatorConfig(
                limits=[{"limit": 1000}],
                pricing={"gpt-4": {"input_per_1k": 100.0, "output_per_1k": 0.0}},
                model_path="llm.model_name",
            )
        )

        # When: evaluate with nested model structure
        result = await ev.evaluate(
            {
                "llm": {"model_name": "gpt-4"},
                "usage": {"input_tokens": 500, "output_tokens": 0},
            }
        )

        # Then: model resolved correctly, cost computed
        assert result.metadata is not None
        assert result.metadata["cost"] == pytest.approx(50.0, abs=0.1)


# ---------------------------------------------------------------------------
# TTL prune tests
# ---------------------------------------------------------------------------


class TestTTLPrune:
    @pytest.mark.asyncio
    async def test_ttl_prune_drops_old_period_on_rollover(self) -> None:
        # Given: store with daily window. Day N, N+1, N+2 timestamps.
        day_seconds = WINDOW_DAILY
        day_n = 1700000000.0
        # Align to exact day boundary
        day_n = (int(day_n) // day_seconds) * day_seconds
        day_n1 = day_n + day_seconds
        day_n2 = day_n + 2 * day_seconds

        rules = [BudgetLimitRule(limit=10_000, window_seconds=day_seconds)]
        store = InMemoryBudgetStore(clock=lambda: day_n)

        # When: record on day N
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        # record on day N+1
        store._clock = lambda: day_n1
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=2.0
        )
        # record on day N+2 -- should prune day N
        store._clock = lambda: day_n2
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=3.0
        )

        # Then: only buckets for day N+1 and N+2 remain for that scope
        with store._lock:
            period_keys = [k[1] for k in store._buckets]

        day_n_key = _derive_period_key(day_seconds, day_n)
        day_n1_key = _derive_period_key(day_seconds, day_n1)
        day_n2_key = _derive_period_key(day_seconds, day_n2)

        assert day_n_key not in period_keys, "Day N bucket should be pruned"
        assert day_n1_key in period_keys, "Day N+1 bucket must be retained"
        assert day_n2_key in period_keys, "Day N+2 bucket must be retained"

    @pytest.mark.asyncio
    async def test_ttl_prune_preserves_cumulative_buckets(self) -> None:
        # Given: store with both cumulative (window=None) and daily rules
        day_seconds = WINDOW_DAILY
        day_n = (int(1700000000.0) // day_seconds) * day_seconds

        rules = [
            BudgetLimitRule(limit=10_000),  # cumulative (window_seconds=None)
            BudgetLimitRule(limit=10_000, window_seconds=day_seconds),
        ]
        store = InMemoryBudgetStore(clock=lambda: day_n)

        # When: record on 3 consecutive days
        for i in range(3):
            store._clock = lambda i=i: day_n + i * day_seconds
            await store.record_and_check(
                rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
            )

        # Then: cumulative bucket (empty period key) must survive
        with store._lock:
            period_keys = [k[1] for k in store._buckets]

        assert "" in period_keys, "Cumulative bucket (period_key='') must not be pruned"

    @pytest.mark.asyncio
    async def test_ttl_prune_preserves_other_windows(self) -> None:
        # Given: store with hourly and daily rules
        hour = 3600
        day = WINDOW_DAILY
        t0 = (int(1700000000.0) // day) * day  # align to day boundary

        rules = [
            BudgetLimitRule(limit=10_000, window_seconds=hour),
            BudgetLimitRule(limit=100_000, window_seconds=day),
        ]
        store = InMemoryBudgetStore(clock=lambda: t0)

        # When: roll hours many times (within same day)
        for h in range(5):
            store._clock = lambda h=h: t0 + h * hour
            await store.record_and_check(
                rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
            )

        # Then: daily bucket must survive hourly rollovers
        day_key = _derive_period_key(day, t0)
        with store._lock:
            period_keys = [k[1] for k in store._buckets]

        assert day_key in period_keys, "Daily bucket must survive hourly rollovers"

        # When: roll day (prune old hourly buckets)
        t_day2 = t0 + day
        store._clock = lambda: t_day2
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )

        with store._lock:
            period_keys_after = [k[1] for k in store._buckets]

        # Then: old hour-0 through hour-3 (index < current_hour-1) should be pruned
        # daily bucket survives (different window)
        day_key2 = _derive_period_key(day, t_day2)
        assert day_key2 in period_keys_after or day_key in period_keys_after, (
            "At least one daily bucket must survive"
        )
        # hour 0 key should be gone (it's >1 period behind the new day's hour-0)
        hour0_key = _derive_period_key(hour, t0)
        # hour0 is many hours before t_day2's first hour -- must be pruned
        assert hour0_key not in period_keys_after, "Old hourly buckets should be pruned"

    @pytest.mark.asyncio
    async def test_ttl_prune_no_rescan_within_period(self) -> None:
        # Given: store with daily window. After a rollover, subsequent records
        # within the same new period must NOT trigger another prune scan.
        day_seconds = WINDOW_DAILY
        day_n = (int(1700000000.0) // day_seconds) * day_seconds
        day_n1 = day_n + day_seconds

        rules = [BudgetLimitRule(limit=10_000, window_seconds=day_seconds)]
        store = InMemoryBudgetStore(clock=lambda: day_n)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )

        # Roll over to day N+1
        store._clock = lambda: day_n1
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )

        # Capture _last_pruned_period state after first record of new period
        with store._lock:
            snapshot_index = dict(store._last_pruned_period)

        # When: record many more times within the same new period
        for _ in range(10):
            await store.record_and_check(
                rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
            )

        # Then: _last_pruned_period unchanged (no rescan occurred)
        with store._lock:
            after_index = dict(store._last_pruned_period)

        assert after_index == snapshot_index, "Prune scan must not repeat within same period"

    @pytest.mark.asyncio
    async def test_ttl_prune_sparse_rollover(self) -> None:
        # Given: daily rule, first record at index 5, then jump to index 100
        day = WINDOW_DAILY
        day_n = (int(1700000000.0) // day) * day
        rules = [BudgetLimitRule(limit=10_000, window_seconds=day)]
        store = InMemoryBudgetStore(clock=lambda: day_n)

        # When: record at baseline
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        # Jump forward ~95 days (any stale indices must be swept in one scan)
        for i in range(1, 6):
            store._clock = lambda i=i: day_n + i * day
            await store.record_and_check(
                rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
            )
        # Large gap -- should prune everything older than index-1
        far = day_n + 100 * day
        store._clock = lambda: far
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )

        # Then: only current (index 100) and previous-valid bucket survive for that window
        with store._lock:
            period_keys = [k[1] for k in store._buckets if k[1].startswith("P")]
        far_key = _derive_period_key(day, far)
        assert far_key in period_keys
        # Nothing from the early batch (indices 0..5) should remain
        for i in range(6):
            old_key = _derive_period_key(day, day_n + i * day)
            assert old_key not in period_keys, f"stale index {i} must be pruned"

    @pytest.mark.asyncio
    async def test_ttl_prune_reset_clears_prune_state(self) -> None:
        # Given: store that has pruned once
        day = WINDOW_DAILY
        day_n = (int(1700000000.0) // day) * day
        rules = [BudgetLimitRule(limit=10_000, window_seconds=day)]
        store = InMemoryBudgetStore(clock=lambda: day_n)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        store._clock = lambda: day_n + 2 * day
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        with store._lock:
            assert day in store._last_pruned_period

        # When: full reset
        store.reset()

        # Then: _last_pruned_period is cleared so that a future rollover
        # re-enables pruning against fresh state
        with store._lock:
            assert store._last_pruned_period == {}

        # And: a fresh rollover sequence prunes again (watermark advances)
        store._clock = lambda: day_n
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        store._clock = lambda: day_n + 2 * day
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        with store._lock:
            assert store._last_pruned_period.get(day) is not None

    @pytest.mark.asyncio
    async def test_ttl_prune_partial_reset_preserves_prune_state(self) -> None:
        # Given: store that has pruned once
        day = WINDOW_DAILY
        day_n = (int(1700000000.0) // day) * day
        rules = [BudgetLimitRule(limit=10_000, window_seconds=day)]
        store = InMemoryBudgetStore(clock=lambda: day_n)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        store._clock = lambda: day_n + 2 * day
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        with store._lock:
            before = dict(store._last_pruned_period)

        # When: partial reset (scope-scoped)
        store.reset(scope_key="__global__")

        # Then: prune state preserved (partial reset does not clobber watermark)
        with store._lock:
            assert store._last_pruned_period == before

    @pytest.mark.asyncio
    async def test_ttl_prune_cross_scope(self) -> None:
        # Given: group_by user, two users recording on the same day
        day = WINDOW_DAILY
        day_n = (int(1700000000.0) // day) * day
        rules = [
            BudgetLimitRule(limit=10_000, window_seconds=day, group_by="user_id"),
        ]
        store = InMemoryBudgetStore(clock=lambda: day_n)
        await store.record_and_check(
            rules=rules, scope={"user_id": "u1"}, input_tokens=0, output_tokens=0, cost=1.0
        )
        await store.record_and_check(
            rules=rules, scope={"user_id": "u2"}, input_tokens=0, output_tokens=0, cost=1.0
        )

        # Pre-condition: both users have distinct buckets on day N
        day_n_key = _derive_period_key(day, day_n)
        with store._lock:
            day_n_scope_keys = [k[0] for k in store._buckets if k[1] == day_n_key]
        assert "user_id=u1" in day_n_scope_keys, "u1 must have its own bucket"
        assert "user_id=u2" in day_n_scope_keys, "u2 must have its own bucket"

        # When: only u1 records on day N+2 (triggers prune)
        store._clock = lambda: day_n + 2 * day
        await store.record_and_check(
            rules=rules, scope={"user_id": "u1"}, input_tokens=0, output_tokens=0, cost=1.0
        )

        # Then: u2's day-N bucket is also pruned -- the period expired globally,
        # not per-scope. This is intentional: the prune sweeps all same-window
        # stale buckets regardless of which scope triggered it.
        day_n_key = _derive_period_key(day, day_n)
        with store._lock:
            period_keys = [k for k in store._buckets if k[1] == day_n_key]
        assert period_keys == [], "u2 day-N bucket must be pruned by u1's rollover"

    @pytest.mark.asyncio
    async def test_ttl_prune_respects_max_buckets_after_rollover(self) -> None:
        # Given: store with max_buckets=2 (hard cap). Record on day N and N+1
        # fills capacity. On day N+2 the prune must free the day-N slot BEFORE
        # the max_buckets check, otherwise rollover permanently fails closed.
        day = WINDOW_DAILY
        day_n = (int(1700000000.0) // day) * day
        rules = [BudgetLimitRule(limit=10_000, window_seconds=day)]
        store = InMemoryBudgetStore(clock=lambda: day_n, max_buckets=2)

        # When: fill 2 buckets
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        store._clock = lambda: day_n + day
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        # Day N+2 at capacity -- prune must free space
        store._clock = lambda: day_n + 2 * day
        snaps = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )

        # Then: day N+2 record succeeded (not fail-closed) and day-N bucket is gone
        assert len(snaps) == 1
        assert not snaps[0].exceeded
        with store._lock:
            period_keys = [k[1] for k in store._buckets]
        day_n_key = _derive_period_key(day, day_n)
        assert day_n_key not in period_keys, "stale day-N bucket must be pruned to free slot"

    @pytest.mark.asyncio
    async def test_ttl_prune_backwards_clock_is_noop(self) -> None:
        # Given: store that pruned at day N+5 (watermark = index 5)
        day = WINDOW_DAILY
        day_n = (int(1700000000.0) // day) * day
        rules = [BudgetLimitRule(limit=10_000, window_seconds=day)]
        store = InMemoryBudgetStore(clock=lambda: day_n)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        store._clock = lambda: day_n + 5 * day
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )
        with store._lock:
            watermark_before = store._last_pruned_period.get(day)
        assert watermark_before is not None

        # When: clock jumps backwards to day N+2 and creates a new bucket there
        store._clock = lambda: day_n + 2 * day
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=1.0
        )

        # Then: watermark did NOT drop (monotonic advance only)
        with store._lock:
            watermark_after = store._last_pruned_period.get(day)
        assert watermark_after == watermark_before, (
            "backwards clock must not lower the prune watermark"
        )


class TestModelPathRequired:
    def test_cost_rule_without_model_path_rejected(self) -> None:
        # Given: a cost-based rule with pricing but no model_path
        # When/Then: config validation rejects it
        with pytest.raises(ValidationError, match="model_path is required"):
            BudgetEvaluatorConfig(
                limits=[BudgetLimitRule(limit=100)],
                pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            )

    def test_token_rule_without_model_path_ok(self) -> None:
        # Given: a token-only rule without model_path
        # When: config is created
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=100, limit_unit="tokens")],
        )

        # Then: no model_path required
        assert config.model_path is None

    def test_cost_rule_with_model_path_accepted(self) -> None:
        # Given: a cost-based rule with pricing and model_path
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=100)],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
        )

        # Then: config is valid
        assert config.model_path == "model"

    def test_cost_rule_with_empty_model_path_rejected(self) -> None:
        # Given: cost rule with model_path="" (empty string is falsy)
        # When/Then: validator rejects it
        with pytest.raises(ValidationError, match="model_path is required"):
            BudgetEvaluatorConfig(
                limits=[BudgetLimitRule(limit=100)],
                pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
                model_path="",
            )

    def test_cost_rule_with_whitespace_model_path_rejected(self) -> None:
        # Given: cost rule with model_path="  " (whitespace-only is stripped)
        # When/Then: validator rejects it
        with pytest.raises(ValidationError, match="model_path is required"):
            BudgetEvaluatorConfig(
                limits=[BudgetLimitRule(limit=100)],
                pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
                model_path="  ",
            )


class TestModelPathRuntimeExtraction:
    @pytest.mark.asyncio
    async def test_model_field_missing_blocks_when_cost_rule_matches(self) -> None:
        # Given: cost rule with model_path, but data has no "model" field
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=100)],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: step data omits the model field entirely
        result = await evaluator.evaluate(
            {"usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: fail-closed -- model_path configured but model unresolvable
        assert result.matched is True
        assert result.metadata is not None
        assert result.metadata["unknown_model"] is None

    @pytest.mark.asyncio
    async def test_model_field_missing_block_message(self) -> None:
        # Given: cost rule with model_path, data has no model field
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=100)],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: step omits model field
        result = await evaluator.evaluate(
            {"usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: message distinguishes path-not-found from unknown-model
        assert result.matched is True
        assert "Model not found at path 'model'" in result.message

    @pytest.mark.asyncio
    async def test_unknown_model_block_message(self) -> None:
        # Given: cost rule with model_path, unknown model in data
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=100)],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: step has model not in pricing
        result = await evaluator.evaluate(
            {"model": "unknown-model", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: message names the unknown model
        assert result.matched is True
        assert "Unknown model: unknown-model" in result.message

    @pytest.mark.asyncio
    async def test_model_field_missing_warn_mode(self) -> None:
        # Given: cost rule with model_path, warn mode, data has no model
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=100)],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
            unknown_model_behavior="warn",
        )
        evaluator = BudgetEvaluator(config)

        # When: step data omits the model field
        result = await evaluator.evaluate(
            {"usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: not blocked (warn mode), cost=0
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_model_field_missing_token_only_with_model_path(self) -> None:
        # Given: token-only rule, model_path IS set, data has no model field
        # This exercises Branch B: model_path_configured=True, model=None,
        # has_matching_cost_rule=False (token rule only).
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=1000, limit_unit="tokens")],
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: step has no "model" field
        result = await evaluator.evaluate(
            {"usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: not blocked (no cost rule), tokens accumulated normally
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["all_snapshots"][0]["spent_tokens"] == 150
        assert result.metadata["cost"] == 0.0
        assert "unknown_model" not in result.metadata

    @pytest.mark.asyncio
    async def test_model_field_missing_token_only_unaffected(self) -> None:
        # Given: token-only rule, model_path not set, data has no model
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=1000, limit_unit="tokens")],
        )
        evaluator = BudgetEvaluator(config)

        # When: step data with no model
        result = await evaluator.evaluate(
            {"usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: normal token evaluation, no blocking
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_empty_pricing_with_model_triggers_block(self) -> None:
        # Given: cost rule, pricing={} (not None), model IS present
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(limit=100)],
            pricing={},
            model_path="model",
        )
        evaluator = BudgetEvaluator(config)

        # When: model present but not in empty pricing table
        result = await evaluator.evaluate(
            {"model": "gpt-4", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: model not in {}, blocked
        assert result.matched is True
        assert result.metadata is not None
        assert result.metadata["unknown_model"] == "gpt-4"


class TestScopedUnknownModelBlock:
    @pytest.mark.asyncio
    async def test_unknown_model_not_blocked_when_only_token_rule_matches(self) -> None:
        # Given: evaluator with a token-only rule for scope A and a cost rule for scope B
        config = BudgetEvaluatorConfig(
            limits=[
                BudgetLimitRule(scope={"agent": "a"}, limit=1000, limit_unit="tokens"),
                BudgetLimitRule(scope={"agent": "b"}, limit=100),
            ],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
            metadata_paths={"agent": "agent"},
        )
        evaluator = BudgetEvaluator(config)

        # When: scope A step uses an unknown model (only token rule applies)
        result = await evaluator.evaluate(
            {
                "agent": "a",
                "model": "unknown-model",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )

        # Then: not blocked -- only token rule matches scope A
        assert result.matched is False
        assert result.metadata is not None
        assert "unknown_model" not in result.metadata

    @pytest.mark.asyncio
    async def test_unknown_model_blocked_when_cost_rule_matches(self) -> None:
        # Given: same config but step targets scope B (where cost rule lives)
        config = BudgetEvaluatorConfig(
            limits=[
                BudgetLimitRule(scope={"agent": "a"}, limit=1000, limit_unit="tokens"),
                BudgetLimitRule(scope={"agent": "b"}, limit=100),
            ],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
            metadata_paths={"agent": "agent"},
        )
        evaluator = BudgetEvaluator(config)

        # When: scope B step uses an unknown model (cost rule applies)
        result = await evaluator.evaluate(
            {
                "agent": "b",
                "model": "unknown-model",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )

        # Then: blocked -- cost rule matches scope B
        assert result.matched is True
        assert result.metadata is not None
        assert result.metadata["unknown_model"] == "unknown-model"

    @pytest.mark.asyncio
    async def test_unknown_model_no_matching_rules_at_all(self) -> None:
        # Given: cost rule scoped to agent=b, step from agent=c (no match)
        config = BudgetEvaluatorConfig(
            limits=[
                BudgetLimitRule(scope={"agent": "b"}, limit=100),
            ],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
            metadata_paths={"agent": "agent"},
        )
        evaluator = BudgetEvaluator(config)

        # When: step from agent=c with unknown model
        result = await evaluator.evaluate(
            {
                "agent": "c",
                "model": "unknown-model",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )

        # Then: not blocked (no rules match this scope at all)
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_warn_mode_scoped_no_warning_when_scope_mismatches(self) -> None:
        # Given: cost rule scoped to agent=b, warn mode
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(scope={"agent": "b"}, limit=100)],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
            metadata_paths={"agent": "agent"},
            unknown_model_behavior="warn",
        )
        evaluator = BudgetEvaluator(config)

        # When: scope A step with unknown model (cost rule is scoped to B)
        result = await evaluator.evaluate(
            {
                "agent": "a",
                "model": "unknown-model",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )

        # Then: no block, no warn -- scope A has no matching cost rule
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_mixed_global_rules_warn_mode_token_accumulates(self) -> None:
        # Given: global cost rule (warn) + global token rule, unknown model
        config = BudgetEvaluatorConfig(
            limits=[
                BudgetLimitRule(limit=100),
                BudgetLimitRule(limit=1000, limit_unit="tokens"),
            ],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
            unknown_model_behavior="warn",
        )
        evaluator = BudgetEvaluator(config)

        # When: unknown model with tokens
        result = await evaluator.evaluate(
            {"model": "unknown-model", "usage": {"input_tokens": 100, "output_tokens": 50}}
        )

        # Then: not blocked (warn mode), token rule still accumulates
        assert result.matched is False
        assert result.metadata is not None
        token_snap = next(
            s for s in result.metadata["all_snapshots"] if s["limit_unit"] == "tokens"
        )
        assert token_snap["spent_tokens"] == 150

    @pytest.mark.asyncio
    async def test_group_by_unknown_model_block_no_bucket_created(self) -> None:
        # Given: group_by cost rule, unknown model
        config = BudgetEvaluatorConfig(
            limits=[BudgetLimitRule(group_by="user_id", limit=100)],
            pricing={"gpt-4": ModelPricing(input_per_1k=10.0, output_per_1k=20.0)},
            model_path="model",
            metadata_paths={"user_id": "user_id"},
        )
        evaluator = BudgetEvaluator(config)

        # When: unknown model is blocked (no bucket created)
        blocked = await evaluator.evaluate(
            {
                "user_id": "u1",
                "model": "unknown",
                "usage": {"input_tokens": 9000, "output_tokens": 0},
            }
        )
        assert blocked.matched is True

        # When: known model follows -- bucket starts fresh
        result = await evaluator.evaluate(
            {
                "user_id": "u1",
                "model": "gpt-4",
                "usage": {"input_tokens": 100, "output_tokens": 0},
            }
        )

        # Then: not contaminated by blocked step
        assert result.matched is False
        assert result.metadata is not None
        assert result.metadata["all_snapshots"][0]["spent"] > 0


class TestBudgetStoreABC:
    def test_subclass_with_sync_override_rejected_at_class_creation(self) -> None:
        # Given: a subclass that overrides record_and_check with a sync def
        # When: the class body is evaluated
        # Then: TypeError is raised, surfacing the contract violation at
        # class-creation time rather than failing silently at the first
        # `await` call site in production.
        from agent_control_evaluator_budget.budget.store import BudgetSnapshot, BudgetStore

        with pytest.raises(TypeError, match="must be an async def"):

            class BrokenStore(BudgetStore):  # type: ignore[unused-ignore]
                def record_and_check(  # noqa: D401, ANN001
                    self,
                    rules: list[BudgetLimitRule],
                    scope: dict[str, str],
                    input_tokens: int,
                    output_tokens: int,
                    cost: float,
                ) -> list[BudgetSnapshot]:
                    return []

    def test_subclass_with_async_override_accepted(self) -> None:
        # Given/When: a subclass that overrides with async def
        # Then: class creation succeeds and the subclass can be instantiated
        from agent_control_evaluator_budget.budget.store import BudgetSnapshot, BudgetStore

        class GoodStore(BudgetStore):
            async def record_and_check(
                self,
                rules: list[BudgetLimitRule],
                scope: dict[str, str],
                input_tokens: int,
                output_tokens: int,
                cost: float,
            ) -> list[BudgetSnapshot]:
                return []

        # And: instances pass nominal isinstance against the ABC
        instance = GoodStore()
        assert isinstance(instance, BudgetStore)

    def test_subclass_without_override_accepted_at_class_creation(self) -> None:
        # Given/When: a subclass that does NOT override record_and_check
        # Then: class creation succeeds (__init_subclass__ method=None path).
        # ABC enforces the abstractmethod at instantiation, not class creation.
        from agent_control_evaluator_budget.budget.store import BudgetStore

        class PartialStore(BudgetStore):
            pass  # no override; abstractmethod prevents instantiation

        # And: instantiation is blocked by ABC, not our __init_subclass__
        with pytest.raises(TypeError, match="abstract method"):
            PartialStore()

    def test_mixin_sync_override_rejected(self) -> None:
        # Given: a sync mixin that provides record_and_check, and a subclass
        # that inherits it via MRO without overriding in its own __dict__
        # When: class creation is attempted
        # Then: __init_subclass__ walks MRO and catches the sync mixin override
        from agent_control_evaluator_budget.budget.store import BudgetStore

        class SyncMixin:
            def record_and_check(self, rules, scope, input_tokens, output_tokens, cost):
                return []

        with pytest.raises(TypeError, match="must be an async def"):

            class MixinStore(SyncMixin, BudgetStore):
                pass


class TestNaNCostDefense:
    @pytest.mark.asyncio
    async def test_nan_cost_coerced_to_zero(self) -> None:
        # Given: store with a cost limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: NaN cost is injected directly (bypassing _estimate_cost)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=float("nan")
        )
        # And: a subsequent valid charge arrives
        snaps = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=500.0
        )

        # Then: the NaN was coerced to 0.0; the accumulator is 500, not NaN
        assert snaps[0].spent == 500
        assert not snaps[0].exceeded

    @pytest.mark.asyncio
    async def test_inf_cost_coerced_to_zero(self) -> None:
        # Given: store with a cost limit
        rules = [BudgetLimitRule(limit=1000)]
        store = InMemoryBudgetStore(clock=lambda: 0.0)

        # When: Inf cost is injected
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=float("inf")
        )
        snaps = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=100.0
        )

        # Then: Inf was coerced to 0.0; the accumulator is 100
        assert snaps[0].spent == 100
        assert not snaps[0].exceeded

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("neg_input", "neg_output"),
        [(-50, 0), (0, -50), (-30, -20)],
        ids=["neg_input_only", "neg_output_only", "both_negative"],
    )
    async def test_negative_tokens_clamped_to_zero(self, neg_input: int, neg_output: int) -> None:
        # Given: store with a token limit, filled to 90 tokens
        rules = [BudgetLimitRule(limit=100, limit_unit="tokens")]
        store = InMemoryBudgetStore(clock=lambda: 0.0)
        await store.record_and_check(
            rules=rules, scope={}, input_tokens=90, output_tokens=0, cost=0.0
        )

        # When: inject negative input/output tokens
        snaps = await store.record_and_check(
            rules=rules, scope={}, input_tokens=neg_input, output_tokens=neg_output, cost=0.0
        )

        # Then: negative tokens clamped to 0; accumulator stays at 90
        assert snaps[0].spent_tokens == 90
        assert not snaps[0].exceeded

    @pytest.mark.asyncio
    async def test_nan_clock_does_not_crash(self) -> None:
        # Given: store with a windowed rule AND a clock that returns NaN
        rules = [BudgetLimitRule(limit=1000, window_seconds=WINDOW_DAILY)]
        store = InMemoryBudgetStore(clock=lambda: float("nan"))

        # When: record_and_check is called (would raise OverflowError in
        # _derive_period_key without the guard)
        snaps = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=100.0
        )

        # Then: no crash; maps to epoch-zero period, budget still enforced
        assert len(snaps) == 1
        assert snaps[0].spent == 100

    @pytest.mark.asyncio
    async def test_inf_clock_does_not_crash(self) -> None:
        # Given: clock returning Inf
        rules = [BudgetLimitRule(limit=1000, window_seconds=WINDOW_DAILY)]
        store = InMemoryBudgetStore(clock=lambda: float("inf"))

        # When: record_and_check is called
        snaps = await store.record_and_check(
            rules=rules, scope={}, input_tokens=0, output_tokens=0, cost=100.0
        )

        # Then: no crash
        assert len(snaps) == 1
        assert snaps[0].spent == 100
