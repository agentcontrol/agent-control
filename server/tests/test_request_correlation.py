"""HTTP ingress preserves parent identity and resets it on every exit."""

import asyncio
from uuid import UUID

import httpx
import pytest
from agent_control_models.request_context import get_request_id, request_id_context
from starlette.types import Message, Receive, Scope, Send

from agent_control_server.request_correlation import RequestCorrelationMiddleware


@pytest.mark.asyncio
async def test_request_correlation_round_trip_and_reset() -> None:
    # Given: a narrow ASGI app avoids unrelated authentication and database setup.
    observed: list[str | None] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        observed.append(get_request_id())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=RequestCorrelationMiddleware(app)), base_url="http://test"
    ) as client:
        # When: a caller supplies a valid parent ID.
        response = await client.get("/evaluate", headers={"X-Request-ID": "run-1.request-2"})
    # Then: the same ID reaches evaluation and returns without leaking context.
    assert observed == ["run-1.request-2"]
    assert response.headers["X-Request-ID"] == "run-1.request-2"
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_request_correlation_replaces_invalid_header() -> None:
    # Given: an ingress ID exceeds the shared bound.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=RequestCorrelationMiddleware(app)), base_url="http://test"
    ) as client:
        # When: the ID reaches the middleware.
        response = await client.get("/evaluate", headers={"X-Request-ID": "x" * 201})
    # Then: only a generated UUID is returned.
    assert str(UUID(response.headers["X-Request-ID"])) == response.headers["X-Request-ID"]
    assert get_request_id() is None


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_request_correlation_restores_context_after_failure(
    error: type[BaseException],
) -> None:
    # Given: an existing outer context and a failing downstream app.
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        assert get_request_id() == "inner"
        raise error()

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        pass

    with request_id_context("outer"):
        # When: evaluation raises or is cancelled.
        with pytest.raises(error):
            await RequestCorrelationMiddleware(app)(
                {"type": "http", "headers": [(b"x-request-id", b"inner")]}, receive, send
            )
        # Then: the previous context survives.
        assert get_request_id() == "outer"
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_request_correlation_isolates_concurrent_requests() -> None:
    # Given: two overlapping requests to the same middleware instance.
    ready = asyncio.Event()
    observed: list[tuple[str | None, str | None]] = []
    entered = 0

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal entered
        before = get_request_id()
        entered += 1
        if entered == 2:
            ready.set()
        await ready.wait()
        observed.append((before, get_request_id()))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=RequestCorrelationMiddleware(app)), base_url="http://test"
    ) as client:
        # When: both requests proceed concurrently.
        responses = await asyncio.gather(
            client.get("/evaluate", headers={"X-Request-ID": "first"}),
            client.get("/evaluate", headers={"X-Request-ID": "second"}),
        )
    # Then: each task retains its own ID.
    assert set(observed) == {("first", "first"), ("second", "second")}
    assert [response.headers["X-Request-ID"] for response in responses] == ["first", "second"]
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_server_app_installs_request_correlation() -> None:
    from agent_control_server.main import app

    # Given: the real app without starting its database lifespan.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # When: a probe supplies a parent ID.
        response = await client.get("/health", headers={"X-Request-ID": "parent-probe"})
    # Then: the installed middleware preserves the ID.
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "parent-probe"
    assert get_request_id() is None
