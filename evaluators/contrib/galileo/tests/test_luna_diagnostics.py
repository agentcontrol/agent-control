"""Opt-in Luna diagnostics through the evaluator and HTTP client."""

from __future__ import annotations

import logging
from itertools import count

import httpx
import pytest
from agent_control_evaluator_galileo.luna import LunaEvaluator
from agent_control_evaluator_galileo.luna import client as luna_client
from agent_control_evaluator_galileo.luna.client import GalileoLunaClient
from agent_control_models import JSONObject, Step

DIAGNOSTIC_ID = "a" * 32


@pytest.fixture(autouse=True)
def luna_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "private-secret")
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://runners:8090")
    monkeypatch.setenv("GALILEO_FEATURE_FLAG_SCORER_INVOKE_RUNTIME", "enabled")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "diagnostic",
    [
        None,
        {"request_id": DIAGNOSTIC_ID},
        {"request_id": 42, "control_id": "7"},
        {"request_id": DIAGNOSTIC_ID, "control_id": "7"},
    ],
)
async def test_luna_diagnostics_reach_http_transport(
    diagnostic: JSONObject | None,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real evaluator/client with only the network transport replaced.
    evaluator = LunaEvaluator.from_dict({"scorer_id": "scorer-123", "threshold": 0.5})
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"score": 0.8, "status": "success"})

    evaluator._client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extensions: JSONObject = {"namespace_key": "org-1", "caller_id": "user-1"}
    if diagnostic is not None:
        extensions["_agent_control_diagnostics"] = diagnostic
    ticks = count(1)
    monkeypatch.setattr(luna_client, "perf_counter", lambda: next(ticks) / 1000)
    caplog.set_level(logging.INFO, logger=luna_client.__name__)

    # When: the contextual evaluator invokes Luna.
    try:
        result = await evaluator.evaluate_with_extensions(
            "private-input", Step(type="llm", name="answer", input="private-input"), extensions
        )
    finally:
        await evaluator._client.close()

    # Then: only complete diagnostic metadata enables correlation and timing logs.
    assert result.error is None
    assert result.matched is True
    enabled = diagnostic == {"request_id": DIAGNOSTIC_ID, "control_id": "7"}
    assert len(requests) == 1
    records = [r for r in caplog.records if r.msg == "Agent Control scorer-invoke client timing"]
    if not enabled:
        assert "X-Galileo-Diagnostic-ID" not in requests[0].headers
        assert "X-Galileo-Diagnostic-Control-ID" not in requests[0].headers
        assert records == []
        return
    assert requests[0].headers.get("X-Galileo-Diagnostic-ID") == DIAGNOSTIC_ID
    assert requests[0].headers.get("X-Galileo-Diagnostic-Control-ID") == "7"
    assert len(records) == 1
    fields = vars(records[0])
    assert fields["diagnostic_request_id"] == DIAGNOSTIC_ID
    assert fields["diagnostic_control_id"] == "7"
    for field in (
        "request_preparation_ms",
        "auth_token_ms",
        "http_client_acquire_ms",
        "runners_http_round_trip_ms",
        "response_parse_ms",
    ):
        assert fields[field] == pytest.approx(1.0)
    assert fields["client_total_ms"] == pytest.approx(10.0)
    assert fields["http_status_code"] == 200
    assert "private-input" not in str(fields)
    assert "private-secret" not in str(fields)
    assert "Authorization" not in str(fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "transport", "parse"])
async def test_luna_diagnostics_capture_failed_stages(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Given: a client whose transport or response fails without real network I/O.
    client = GalileoLunaClient()

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "transport":
            raise httpx.ConnectError("unavailable", request=request)
        if failure == "http":
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json=[])

    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    caplog.set_level(logging.INFO, logger=luna_client.__name__)

    # When: invocation fails after diagnostic headers have been supplied.
    try:
        with pytest.raises((httpx.HTTPStatusError, httpx.ConnectError, RuntimeError)):
            await client.invoke(
                scorer_id="scorer-123",
                input="private-input",
                headers={
                    "X-Galileo-Diagnostic-ID": DIAGNOSTIC_ID,
                    "X-Galileo-Diagnostic-Control-ID": "7",
                },
            )
    finally:
        await client.close()

    # Then: completed/failed stages remain timed and unreached stages remain absent.
    records = [r for r in caplog.records if r.msg == "Agent Control scorer-invoke client timing"]
    assert len(records) == 1
    fields = vars(records[0])
    assert fields["diagnostic_request_id"] == DIAGNOSTIC_ID
    assert fields["diagnostic_control_id"] == "7"
    assert fields["http_client_acquire_ms"] >= 0
    assert fields["runners_http_round_trip_ms"] >= 0
    assert fields["client_total_ms"] >= fields["runners_http_round_trip_ms"]
    assert fields["http_status_code"] == {"http": 503, "transport": None, "parse": 200}[failure]
    if failure == "parse":
        assert fields["response_parse_ms"] >= 0
    else:
        assert fields["response_parse_ms"] is None
