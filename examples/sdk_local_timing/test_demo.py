"""Behavior checks for the SDK-local timing example."""

import pytest

from examples.sdk_local_timing.demo import distribution, format_table, run


def test_distribution_uses_nearest_rank() -> None:
    # Given: a sample with a known upper-tail observation.
    values = list(range(1, 21))

    # When: the collector summarizes the sample.
    summary = distribution(values)

    # Then: p95 is the nineteenth ordered value.
    assert summary == {"count": 20, "min_ms": 1, "p50_ms": 10, "p95_ms": 19, "max_ms": 20}


@pytest.mark.asyncio
async def test_cases_run_locally_and_have_control_time() -> None:
    # Given: an HTTP transport that rejects any outbound request.

    # When: each synthetic case runs through the SDK local path after one warmup.
    report = await run(iterations=2, warmup=1, concurrency=2)

    # Then: each case returns exactly one measured control result.
    assert set(report["scenarios"]) == {
        "list-allow",
        "list-block",
        "regex-steer",
        "sql-block",
        "json-valid",
    }
    for case in report["scenarios"].values():
        assert case["control"]["count"] == 2
        assert case["control"]["min_ms"] >= 0
        assert case["sdk_call"]["min_ms"] >= case["control"]["min_ms"]
        assert case["observed_calls_per_sec"] > 0
    table = format_table(report)
    assert "control p50/p95 (ms)" in table
    assert "regex-steer" in table
