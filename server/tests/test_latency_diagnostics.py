"""Evaluation diagnostics without database or network dependencies."""

import json
import logging
from unittest.mock import AsyncMock

import pytest
from agent_control_models import (
    ControlMatch,
    EvaluationRequest,
    EvaluationResponse,
    EvaluatorResult,
    Step,
)
from fastapi import Response

from agent_control_server.auth_framework import Principal
from agent_control_server.endpoints import evaluation
from agent_control_server.logging_utils import _JsonLogFormatter


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_evaluation_emits_scalar_control_timings(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    enabled: bool,
) -> None:
    # Given: the endpoint's storage and engine boundaries are replaced to avoid database I/O.
    monkeypatch.setenv("AGENT_CONTROL_LATENCY_DIAGNOSTICS_ENABLED", str(enabled))
    monkeypatch.setattr(evaluation, "_load_engine_controls", AsyncMock(return_value=[]))
    results = [
        ControlMatch(
            control_id=index,
            control_name=f"control-{index}",
            action="deny",
            result=EvaluatorResult(matched=False, confidence=1.0),
            execution_duration_ms=duration,
        )
        for index, duration in enumerate([0.0, 3.5, None], start=1)
    ]
    process = AsyncMock(
        return_value=EvaluationResponse(
            is_safe=True,
            confidence=1.0,
            matches=[results[0]],
            non_matches=[results[1]],
            errors=[results[2]],
        )
    )
    monkeypatch.setattr(evaluation.ControlEngine, "process", process)
    response = Response()
    caplog.set_level(logging.INFO)

    # When: the endpoint evaluates a target-bound request.
    await evaluation.evaluate(
        EvaluationRequest(
            agent_name="test-agent",
            stage="pre",
            step=Step(type="llm", name="answer", input="private-input"),
        ),
        response,
        Principal(namespace_key="org-1", target_type="log_stream", target_id="run-1"),
    )

    # Then: emitted JSON contains one scalar timing per returned control, only when enabled.
    records = [r for r in caplog.records if r.msg == "Evaluation control timing"]
    summaries = [r for r in caplog.records if r.msg == "Evaluation latency diagnostics"]
    if not enabled:
        assert "X-Galileo-Diagnostic-ID" not in response.headers
        assert records == []
        assert summaries == []
        assert "_agent_control_diagnostics" not in process.call_args.kwargs["extensions"]
        return
    diagnostic_id = response.headers["X-Galileo-Diagnostic-ID"]
    assert process.call_args.kwargs["extensions"]["_agent_control_diagnostics"] == {
        "request_id": diagnostic_id,
    }
    assert len(records) == 3
    for record, match in zip(records, results, strict=True):
        payload = json.loads(_JsonLogFormatter().format(record))
        assert payload["diagnostic_request_id"] == diagnostic_id
        assert payload["diagnostic_control_id"] == str(match.control_id)
        assert payload["execution_ms"] == match.execution_duration_ms
        assert "private-input" not in str(payload)
    assert len(summaries) == 1
    summary = json.loads(_JsonLogFormatter().format(summaries[0]))
    for key in (
        "controls_load_ms",
        "control_engine_ms",
        "response_sanitize_ms",
        "handler_total_ms",
    ):
        assert summary[key] >= 0


def test_json_formatter_retains_client_stages() -> None:
    # Given: a safe client timing record with unrelated sensitive extras.
    fields = {
        "diagnostic_request_id": "a" * 32,
        "diagnostic_control_id": "7",
        "request_preparation_ms": 1.0,
        "auth_token_ms": 2.0,
        "http_client_acquire_ms": 3.0,
        "runners_http_round_trip_ms": 4.0,
        "response_parse_ms": 5.0,
        "client_total_ms": 20.0,
        "http_status_code": 200,
    }
    record = logging.makeLogRecord(
        {
            "msg": "Agent Control scorer-invoke client timing",
            **fields,
            "Authorization": "private-secret",
            "request_body": "private-input",
        }
    )

    # When: the server's JSON formatter renders the record.
    payload = json.loads(_JsonLogFormatter().format(record))

    # Then: all approved stages survive without exposing arbitrary extras.
    for key, value in fields.items():
        assert payload[key] == value
    assert "Authorization" not in payload
    assert "request_body" not in payload
