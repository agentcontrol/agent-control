"""Tests for error handlers."""

import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent_control_server.config import settings
from agent_control_server.errors import InternalError, generic_exception_handler, http_exception_handler


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
async def test_generic_exception_handler_exposes_details_in_local_dev(monkeypatch) -> None:
    # Given: local dev settings enabled for error exposure
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setenv("AGENT_CONTROL_EXPOSE_ERRORS", "true")
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})

    # When: handling an unexpected exception
    response = await generic_exception_handler(request, ValueError("boom"))

    # Then: response includes exception type and message
    assert response.status_code == 500
    body = json.loads(response.body.decode("utf-8"))
    assert "ValueError: boom" in body["detail"]


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


def test_internal_error_sets_default_hint() -> None:
    # Given: an InternalError without an explicit hint
    err = InternalError(detail="boom")

    # When: converting to a problem detail response
    problem = err.to_problem_detail(instance="/boom")

    # Then: the default hint is included
    assert "unexpected error" in (problem.hint or "")
