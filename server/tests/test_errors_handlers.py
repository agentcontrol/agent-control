"""Tests for error handlers."""

import json
import logging

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from starlette.requests import Request

from agent_control_server.errors import (
    InternalError,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)


@pytest.mark.asyncio
async def test_http_exception_handler_sets_www_authenticate() -> None:
    # Given: a 401 HTTPException
    request = Request({"type": "http", "method": "GET", "path": "/protected", "headers": []})
    exc = HTTPException(status_code=401, detail="missing api key")

    # When: handling the HTTPException
    response = await http_exception_handler(request, exc)

    # Then: response is RFC 7807 with WWW-Authenticate header
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "ApiKey"
    body = json.loads(response.body.decode("utf-8"))
    assert body["error_code"] == "AUTH_INVALID_KEY"


@pytest.mark.asyncio
async def test_generic_exception_handler_never_exposes_exception_details(monkeypatch) -> None:
    # Given: local debug flags are enabled
    monkeypatch.setenv("AGENT_CONTROL_EXPOSE_ERRORS", "true")
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})

    # When: handling an unexpected exception
    response = await generic_exception_handler(request, ValueError("boom"))

    # Then: response remains public-safe and does not include internals
    assert response.status_code == 500
    body = json.loads(response.body.decode("utf-8"))
    assert body["detail"] == "An unexpected error occurred. Please try again or contact support."
    assert "ValueError" not in body["detail"]
    assert body["metadata"]["request_id"]


@pytest.mark.asyncio
async def test_generic_exception_handler_logs_full_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: a request that triggers an unhandled exception
    caplog.set_level(logging.ERROR, logger="agent_control_server.errors")
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})

    # When: handling the exception while inside an except block
    try:
        raise ValueError("boom")
    except ValueError as exc:
        await generic_exception_handler(request, exc)

    # Then: server logs include traceback details
    assert "Unhandled exception (error_id=" in caplog.text
    assert "Traceback" in caplog.text
    assert "ValueError: boom" in caplog.text


@pytest.mark.asyncio
async def test_http_exception_handler_uses_dict_detail_message() -> None:
    # Given: an HTTPException with a dict detail payload
    request = Request({"type": "http", "method": "GET", "path": "/bad", "headers": []})
    exc = HTTPException(status_code=400, detail={"message": "bad input"})

    # When: handling the HTTPException
    response = await http_exception_handler(request, exc)

    # Then: the response uses the dict message as detail
    assert response.status_code == 400
    body = json.loads(response.body.decode("utf-8"))
    assert body["detail"] == "bad input"


@pytest.mark.asyncio
async def test_http_exception_handler_sanitizes_500_details() -> None:
    # Given: a 500 HTTPException containing internal details
    request = Request({"type": "http", "method": "GET", "path": "/bad", "headers": []})
    exc = HTTPException(
        status_code=500,
        detail='Traceback (most recent call last): File "/tmp/x.py", line 1 password=abc',
    )

    # When: handling the HTTPException
    response = await http_exception_handler(request, exc)

    # Then: the response detail is redacted to a safe generic message
    assert response.status_code == 500
    body = json.loads(response.body.decode("utf-8"))
    assert body["detail"] == "An unexpected error occurred. Please try again or contact support."
    assert "Traceback" not in body["detail"]
    assert "password" not in body["detail"]


@pytest.mark.asyncio
async def test_validation_exception_handler_redacts_string_values() -> None:
    # Given: a validation error containing a string input value
    request = Request({"type": "http", "method": "POST", "path": "/bad", "headers": []})
    exc = RequestValidationError(
        [
            {
                "type": "string_type",
                "loc": ("body", "api_key"),
                "msg": "Input should be a valid string",
                "input": "super-secret-token",
            }
        ]
    )

    # When: handling the validation error
    response = await validation_exception_handler(request, exc)

    # Then: the string value is redacted
    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    assert body["errors"][0]["value"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_validation_exception_handler_keeps_numeric_values() -> None:
    # Given: a validation error containing a numeric input value
    request = Request({"type": "http", "method": "POST", "path": "/bad", "headers": []})
    exc = RequestValidationError(
        [
            {
                "type": "less_than_equal",
                "loc": ("body", "limit"),
                "msg": "Input should be less than or equal to 100",
                "input": 101,
            }
        ]
    )

    # When: handling the validation error
    response = await validation_exception_handler(request, exc)

    # Then: numeric value is preserved
    assert response.status_code == 422
    body = json.loads(response.body.decode("utf-8"))
    assert body["errors"][0]["value"] == 101


def test_internal_error_sets_default_hint() -> None:
    # Given: an InternalError without an explicit hint
    err = InternalError(detail="boom")

    # When: converting to a problem detail response
    problem = err.to_problem_detail(instance="/boom")

    # Then: the default hint is included
    assert "unexpected error" in (problem.hint or "")
