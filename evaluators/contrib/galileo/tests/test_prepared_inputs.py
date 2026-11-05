"""Request-local preparation through the public engine and real scorer clients."""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from agent_control_engine.core import ControlEngine
from agent_control_evaluators import Evaluator, EvaluatorConfig, EvaluatorMetadata
from agent_control_models import ControlDefinition, EvaluationRequest, EvaluatorResult, Step


@dataclass
class _Control:
    id: int
    name: str
    control: ControlDefinition


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["llm", "luna"])
@pytest.mark.parametrize("record_type", ["llm", "trace"])
async def test_five_scorers_prepare_one_record_but_make_five_calls(
    monkeypatch: pytest.MonkeyPatch, provider: str, record_type: str
) -> None:
    # Given: real clients with a mock HTTP boundary; internal factory spying is
    # intentional because avoiding repeated conversion is the performance contract.
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://scorer.test")
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME", "enabled")
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_LLM_EVALUATOR", "enabled")
    module = importlib.import_module(f"agent_control_evaluator_galileo.{provider}.client")
    evaluator_module = importlib.import_module(
        f"agent_control_evaluator_galileo.{provider}.evaluator"
    )
    evaluator_type = getattr(
        evaluator_module, "LlmEvaluator" if provider == "llm" else "LunaEvaluator"
    )
    bodies: list[dict] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        await asyncio.sleep(0)  # Exercise sibling task fan-out.
        return httpx.Response(200, json={"score": 0.1, "status": "success"})

    evaluators: dict[str, Evaluator] = {}
    controls = []
    for i in range(5):
        config = {
            "scorer_id": f"scorer-{i}",
            "scorer_version_id": f"version-{i}",
            "threshold": 0.5,
            "payload_field": "output",
        }
        evaluator = evaluator_type.from_dict(config)
        evaluator._client._client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        evaluators[f"scorer-{i}"] = evaluator
        controls.append(_Control(i, f"control-{i}", ControlDefinition.model_validate({
            "enabled": True, "execution": "server",
            "scope": {"step_types": [record_type], "stages": ["post"]},
            "condition": {"selector": {"path": "*"}, "evaluator": {
                "name": f"galileo.{provider}", "config": config,
            }},
            "action": {"decision": "observe"},
        })))
    step = Step(
        type=record_type, name="request", input="question", output="answer",
        children=[Step(type="llm", name="child", input="q", output="a")]
        if record_type == "trace" else None,
    )
    request = EvaluationRequest(agent_name="prepare-input-agent", stage="post", step=step)
    engine = ControlEngine(controls)
    extensions = {"namespace_key": "org-a", "caller_id": "user-a",
                  "target_type": "log_stream", "target_id": "stream-a"}

    # When: five scorers evaluate the same full-step selection in one request.
    try:
        with patch("agent_control_engine.core.get_evaluator_instance",
                   side_effect=lambda spec: evaluators[spec.config["scorer_id"]]), patch.object(
            module, "record_from_step", wraps=module.record_from_step
        ) as prepare:
            result = await engine.process(request, extensions)
            assert prepare.call_count == 1
            # Reusing even the same Step object in another request must prepare again.
            second = await engine.process(request, {**extensions, "namespace_key": "org-b"})
            assert prepare.call_count == 2
    finally:
        for evaluator in evaluators.values():
            await evaluator._client.close()

    # Then: no scorer execution, configuration or authenticated context is reused.
    assert result.errors is None and second.errors is None
    assert len(result.non_matches or []) == 5
    assert len(bodies) == 10
    assert {body["scorer_id"] for body in bodies[:5]} == set(evaluators)
    assert all(body["record"]["type"] == record_type for body in bodies)
    assert all(body["record"]["name"] == "request" for body in bodies)
    assert all(body["execution_context"]["organization_id"] == "org-a" for body in bodies[:5])
    assert all(body["execution_context"]["organization_id"] == "org-b" for body in bodies[5:])
    assert all(body["record"] == bodies[0]["record"] for body in bodies[:5])


@pytest.mark.parametrize("provider", ["llm", "luna"])
def test_selector_and_payload_variants_match_uncached_records(provider: str) -> None:
    # Given: the conversion boundary is tested directly to cover distinct selected
    # values and payload sides without network/scorer work.
    from agent_control_evaluators.preparation import evaluation_preparation_scope

    module = importlib.import_module(f"agent_control_evaluator_galileo.{provider}.client")
    step = Step(type="llm", name="answer", input="original-input", output="original-output")
    left = {"output": "left"}
    right = {"output": "right"}
    variants = [(left, "input"), (right, "input"), ("scalar", "input"), ("scalar", "output")]

    def convert(data: object, side: str) -> object:
        record = module._scorer_invoke_record_from_step(
            step, selected_input="", selected_output="", selected_data=data, payload_field=side
        )
        # Core assigns conversion-time timestamps; compare content, not clock readings.
        return record.model_dump(mode="json", exclude={"created_at"})

    expected = [convert(data, side) for data, side in variants]
    # When: different selectors/payload sides are used within one evaluation.
    with evaluation_preparation_scope():
        actual = [convert(data, side) for data, side in variants]
    # Then: each remains byte-value equivalent to its independently prepared record.
    assert actual == expected
    assert actual[0] != actual[1]
    assert actual[2] != actual[3]


@pytest.mark.asyncio
async def test_non_opted_in_evaluators_keep_independent_wildcard_selections() -> None:
    # Given: a custom evaluator mutates its selected dictionary, not the shared Step.
    seen: list[str] = []

    class MutatingEvaluator(Evaluator[EvaluatorConfig]):
        metadata = EvaluatorMetadata(name="test.mutating", version="1", description="test")
        config_model = EvaluatorConfig

        async def evaluate(self, data: Any) -> EvaluatorResult:
            seen.append(data["input"])
            data["input"] = "changed"
            return EvaluatorResult(matched=False, confidence=1.0)

    evaluator = MutatingEvaluator.from_dict({})
    definition = ControlDefinition.model_validate({
        "enabled": True, "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "condition": {"selector": {"path": "*"},
                      "evaluator": {"name": "test.mutating", "config": {}}},
        "action": {"decision": "observe"},
    })
    step = Step(type="llm", name="answer", input="original")
    engine = ControlEngine([_Control(i, f"control-{i}", definition) for i in range(2)])
    # When: evaluate through the public engine with preparation scopes enabled.
    with patch("agent_control_engine.core.get_evaluator_instance", return_value=evaluator):
        result = await engine.process(EvaluationRequest(
            agent_name="prepare-input-agent", stage="post", step=step
        ))
    # Then: existing custom-evaluator mutation semantics are preserved.
    assert result.errors is None
    assert seen == ["original", "original"]
    assert step.input == "original"
