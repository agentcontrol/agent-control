"""Offline preparation-only comparison; no HTTP, Redis, DB or model requests.

Run from the repository root with the Galileo development environment:
    python evaluators/contrib/galileo/benchmarks/prepare_inputs.py

The baseline materializes each selection/record independently. The optimized arm
uses the same evaluation-local scope as ControlEngine. Both serialize a separate
record for every scorer, which remains necessary for separate HTTP requests.
These synthetic timings are not service or end-to-end LT latency predictions.
"""

from contextlib import nullcontext
from json import dumps
from statistics import median
from time import perf_counter_ns

from agent_control_engine.selectors import select_data
from agent_control_evaluator_galileo.llm.client import _scorer_invoke_record_from_step
from agent_control_evaluators.preparation import evaluation_preparation_scope, prepare_once
from agent_control_models import Step


def measure(step: Step, controls: int, reuse: bool) -> float:
    started = perf_counter_ns()
    with evaluation_preparation_scope() if reuse else nullcontext():
        for _ in range(controls):
            data = (
                prepare_once("engine.selector:*", (step,), lambda: select_data(step, "*"))
                if reuse else select_data(step, "*")
            )
            record = _scorer_invoke_record_from_step(
                step, selected_input="question", selected_output="answer", selected_data=data
            )
            assert record is not None
            record.model_dump(mode="json", exclude_none=True)
    return (perf_counter_ns() - started) / 1_000_000


def main() -> None:
    steps = {
        "small_llm": Step(type="llm", name="answer", input="question", output="answer"),
        "trace_100_spans": Step(
            type="trace", name="request", input="question", output="answer",
            children=[Step(type="llm", name=f"child-{i}", input="question", output="answer")
                      for i in range(100)],
        ),
    }
    rows = []
    for name, step in steps.items():
        for controls in (5, 10):
            baseline, reused = [], []
            for iteration in range(35):
                # Alternate order; discard five warm-up pairs.
                modes = (False, True) if iteration % 2 else (True, False)
                values = {mode: measure(step, controls, mode) for mode in modes}
                if iteration >= 5:
                    baseline.append(values[False])
                    reused.append(values[True])
            before, after = median(baseline), median(reused)
            rows.append({"fixture": name, "controls": controls,
                         "baseline_preparation_median_ms": round(before, 4),
                         "reused_preparation_median_ms": round(after, 4),
                         "saved_ms": round(before-after, 4),
                         "reduction_pct": round((before-after)/before*100, 1)})
    print(dumps({"scope": "synthetic local preparation only; not end-to-end LT",
                 "measured_pairs_per_case": 30, "results": rows}, indent=2))


if __name__ == "__main__":
    main()
