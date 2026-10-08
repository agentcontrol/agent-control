"""Compare SDK-local per-control time with the full SDK call, without network I/O."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from agent_control import AgentControlClient
from agent_control.evaluation import check_evaluation_with_local
from agent_control.settings import configure_settings, get_settings
from agent_control_models import Step


@dataclass(frozen=True)
class Scenario:
    name: str
    evaluator: str
    config: dict[str, Any]
    selector: str
    decision: Literal["deny", "steer", "observe"]
    step_input: dict[str, Any]
    expected_bucket: Literal["matches", "non_matches"]


LIST_CONFIG = {
    "values": ["delete_customer"],
    "logic": "any",
    "match_on": "match",
    "match_mode": "exact",
    "case_sensitive": False,
}

SCENARIOS = (
    Scenario(
        "list-allow",
        "list",
        LIST_CONFIG,
        "input.action",
        "deny",
        {"action": "read_customer"},
        "non_matches",
    ),
    Scenario(
        "list-block",
        "list",
        LIST_CONFIG,
        "input.action",
        "deny",
        {"action": "delete_customer"},
        "matches",
    ),
    Scenario(
        "regex-steer",
        "regex",
        {"pattern": "transfer"},
        "input.action",
        "steer",
        {"action": "transfer"},
        "matches",
    ),
    Scenario(
        "sql-block",
        "sql",
        {"blocked_operations": ["DROP"]},
        "input.sql",
        "deny",
        {"sql": "DROP TABLE customers"},
        "matches",
    ),
    Scenario(
        "json-valid",
        "json",
        {"required_fields": ["customer_id"]},
        "input.payload",
        "observe",
        {"payload": '{"customer_id":"synthetic-1"}'},
        "non_matches",
    ),
)


def control_payload(scenario: Scenario, control_id: int) -> dict[str, Any]:
    return {
        "id": control_id,
        "name": scenario.name,
        "control": {
            "enabled": True,
            "execution": "sdk",
            "scope": {"step_types": ["tool"], "stages": ["pre"], "step_names": ["timing_probe"]},
            "condition": {
                "selector": {"path": scenario.selector},
                "evaluator": {"name": scenario.evaluator, "config": scenario.config},
            },
            "action": {"decision": scenario.decision},
        },
    }


def distribution(values: list[float]) -> dict[str, float | int]:
    """Summarize a nonempty sample using nearest-rank percentiles."""
    ordered = sorted(values)

    def rank(fraction: float) -> float:
        return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]

    return {
        "count": len(ordered),
        "min_ms": ordered[0],
        "p50_ms": rank(0.50),
        "p95_ms": rank(0.95),
        "max_ms": ordered[-1],
    }


def reject_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"SDK-local demo attempted HTTP to {request.url.host}")


def format_table(report: dict[str, Any]) -> str:
    """Render each local control's timing beside the enclosing SDK call."""
    rows = [
        f"iterations={report['iterations']} warmup={report['warmup']}",
        "scenario      outcome      control p50/p95 (ms)  SDK call p50/p95 (ms)",
    ]
    for name, result in report["scenarios"].items():
        control = result["control"]
        sdk_call = result["sdk_call"]
        rows.append(
            f"{name:<13} {result['outcome']:<12} "
            f"{control['p50_ms']:>8.3f}/{control['p95_ms']:>8.3f} "
            f"{sdk_call['p50_ms']:>8.3f}/{sdk_call['p95_ms']:>8.3f}"
        )
    return "\n".join(rows)


async def run(*, iterations: int, warmup: int) -> dict[str, Any]:
    """Run each synthetic control locally and validate its measured result."""
    if not 1 <= iterations <= 100_000 or not 0 <= warmup <= 10_000:
        raise ValueError("iterations must be 1..100000 and warmup must be 0..10000")

    previous_settings = get_settings().model_dump()
    configure_settings(observability_enabled=False)
    try:
        report: dict[str, Any] = {"iterations": iterations, "warmup": warmup, "scenarios": {}}
        async with AgentControlClient(
            base_url="https://unused.invalid", transport=httpx.MockTransport(reject_network)
        ) as client:
            for control_id, scenario in enumerate(SCENARIOS, start=1):
                control = control_payload(scenario, control_id)
                step = Step(type="tool", name="timing_probe", input=scenario.step_input)
                control_times: list[float] = []
                sdk_times: list[float] = []
                for index in range(warmup + iterations):
                    started_at = time.perf_counter()
                    result = await check_evaluation_with_local(
                        client, "sdk-local-timing-demo", step, "pre", [control]
                    )
                    sdk_ms = (time.perf_counter() - started_at) * 1000
                    bucket = getattr(result, scenario.expected_bucket) or []
                    other_buckets = (
                        ["non_matches"] if scenario.expected_bucket == "matches" else ["matches"]
                    ) + ["errors"]
                    if len(bucket) != 1 or any(getattr(result, name) for name in other_buckets):
                        raise RuntimeError(f"{scenario.name}: unexpected control outcome")
                    if bucket[0].control_id != control_id:
                        raise RuntimeError(f"{scenario.name}: wrong control result")
                    expected_match = scenario.expected_bucket == "matches"
                    if (
                        bucket[0].action != scenario.decision
                        or bucket[0].result.matched != expected_match
                        or result.is_safe != (not expected_match)
                    ):
                        raise RuntimeError(f"{scenario.name}: unexpected action or safety result")
                    duration_ms = bucket[0].execution_duration_ms
                    if duration_ms is None or not math.isfinite(duration_ms) or duration_ms < 0:
                        raise RuntimeError(f"{scenario.name}: missing or invalid control duration")
                    if index >= warmup:
                        control_times.append(duration_ms)
                        sdk_times.append(sdk_ms)
                report["scenarios"][scenario.name] = {
                    "evaluator": scenario.evaluator,
                    "outcome": scenario.expected_bucket,
                    "control": distribution(control_times),
                    "sdk_call": distribution(sdk_times),
                }
        return report
    finally:
        configure_settings(**previous_settings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="emit machine-readable samples summary")
    args = parser.parse_args()
    report = asyncio.run(run(iterations=args.iterations, warmup=args.warmup))
    print(json.dumps(report, indent=2) if args.json else format_table(report))


if __name__ == "__main__":
    main()
