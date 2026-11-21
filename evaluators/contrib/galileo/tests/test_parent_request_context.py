"""Luna transports forward only the scoped parent ID and their own authentication."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from agent_control_evaluator_galileo.luna import GalileoLunaClient
from agent_control_models.request_context import get_request_id, request_id_context


@pytest.mark.asyncio
async def test_luna_client_forwards_parent_id_without_copying_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a local transport captures the real outgoing HTTP headers.
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://luna-invoke:8090")
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-only-secret")
    captured: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers)
        return httpx.Response(200, json={"score": 0.1, "status": "success"})

    client = GalileoLunaClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        # When: an evaluation supplies the scoped parent ID.
        with request_id_context("parent-run.request-1"):
            await client.invoke(
                scorer_id=str(uuid4()),
                input="benign",
                headers={"Galileo-API-Key": "must-not-forward", "x-request-id": "stale-child"},
            )
    finally:
        await client.close()
    # Then: the parent is retained, while caller credentials remain blocked.
    assert captured[0]["X-Request-ID"] == "parent-run.request-1"
    assert "Galileo-API-Key" not in captured[0]
    assert captured[0]["Authorization"].startswith("Bearer ")
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_luna_client_isolates_concurrent_parent_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: a shared pooled client receives overlapping evaluations.
    monkeypatch.setenv("GALILEO_LUNA_INVOKE_URL", "http://luna-invoke:8090")
    monkeypatch.setenv("GALILEO_API_SECRET_KEY", "test-only-secret")
    observed: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request.headers["X-Request-ID"])
        return httpx.Response(200, json={"score": 0.1, "status": "success"})

    client = GalileoLunaClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def invoke(parent: str) -> None:
        with request_id_context(parent):
            await client.invoke(scorer_id=str(uuid4()), input="benign")

    try:
        # When: separate task contexts invoke the same client.
        await asyncio.gather(invoke("first"), invoke("second"))
    finally:
        await client.close()
    # Then: the shared transport sees both distinct parent IDs.
    assert set(observed) == {"first", "second"}
    assert get_request_id() is None
