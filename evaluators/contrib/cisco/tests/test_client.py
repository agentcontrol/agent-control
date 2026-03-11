from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from agent_control_evaluator_cisco.ai_defense.client import (
    AIDefenseClient,
    build_endpoint,
)


@pytest.mark.asyncio
async def test_chat_inspect_happy_path_builds_headers_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeResponse:
        def __init__(self, data: dict[str, Any]):
            self._data = data

        def raise_for_status(self) -> None:  # no-op
            return None

        def json(self) -> dict[str, Any]:
            return self._data

    class FakeAsyncClient:
        def __init__(self, *_, **kwargs: Any):
            captured["timeout"] = kwargs.get("timeout")
            self.is_closed = False

        async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse({"ok": True, "is_safe": True})

        async def aclose(self) -> None:
            self.is_closed = True

    # Patch the constructor used by the module
    from agent_control_evaluator_cisco.ai_defense import client as client_mod

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeAsyncClient, raising=True)

    c = AIDefenseClient(
        api_key="k",
        endpoint_url="https://example.test/api/v1/inspect/chat",
        timeout_s=7.5,
    )

    data = await c.chat_inspect(
        messages=[{"role": "user", "content": "hello"}],
        metadata={"trace_id": "t1"},
        inspect_config={"mode": "strict"},
        headers={"X-Extra": "1"},
    )

    assert data["ok"] is True
    assert captured["url"] == "https://example.test/api/v1/inspect/chat"
    assert captured["timeout"] == 7.5
    # Headers
    assert captured["headers"]["X-Cisco-AI-Defense-API-Key"] == "k"
    assert captured["headers"]["X-Extra"] == "1"
    assert captured["headers"]["Content-Type"] == "application/json"
    # Payload
    assert captured["json"]["messages"][0]["content"] == "hello"
    assert captured["json"]["metadata"] == {"trace_id": "t1"}
    assert captured["json"]["config"] == {"mode": "strict"}
    assert "api_key='k'" not in repr(c)


@pytest.mark.asyncio
async def test_chat_inspect_non_dict_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:  # not a dict
            return [1, 2, 3]

    class FakeAsyncClient:
        def __init__(self, *_, **__):
            self.is_closed = False

        async def post(self, *_: Any, **__: Any):
            return FakeResponse()

        async def aclose(self) -> None:
            self.is_closed = True

    from agent_control_evaluator_cisco.ai_defense import client as client_mod

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeAsyncClient, raising=True)

    c = AIDefenseClient(api_key="k", endpoint_url="https://x/api/v1/inspect/chat", timeout_s=5)

    with pytest.raises(RuntimeError, match="not a JSON object"):
        await c.chat_inspect(messages=[{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_inspect_http_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeHTTPError(Exception):
        pass

    class FakeResponse:
        def raise_for_status(self) -> None:
            raise FakeHTTPError("bad status")

        def json(self) -> dict[str, Any]:  # never reached
            return {}

    class FakeAsyncClient:
        def __init__(self, *_, **__):
            self.is_closed = False

        async def post(self, *_: Any, **__: Any):
            return FakeResponse()

        async def aclose(self) -> None:
            self.is_closed = True

    from agent_control_evaluator_cisco.ai_defense import client as client_mod

    # Patch AsyncClient and also patch the exception class to a stable local one
    monkeypatch.setattr(client_mod, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient, HTTPStatusError=FakeHTTPError))

    c = AIDefenseClient(api_key="k", endpoint_url="https://x/api/v1/inspect/chat", timeout_s=5)

    with pytest.raises(FakeHTTPError, match="bad status"):
        await c.chat_inspect(messages=[{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_get_client_lifecycle_create_reuse_recreate(monkeypatch: pytest.MonkeyPatch) -> None:
    instances: list[FakeAsyncClient] = []

    class FakeAsyncClient:
        def __init__(self, *_, **kwargs: Any):
            self.timeout = kwargs.get("timeout")
            self.is_closed = False
            instances.append(self)

        async def aclose(self) -> None:
            self.is_closed = True

    from agent_control_evaluator_cisco.ai_defense import client as client_mod

    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeAsyncClient, raising=True)

    c = AIDefenseClient(api_key="k", endpoint_url="u", timeout_s=3.3)

    cl1 = await c._get_client()
    assert isinstance(cl1, FakeAsyncClient)
    assert cl1.timeout == 3.3

    # Reuse when not closed
    cl2 = await c._get_client()
    assert cl2 is cl1

    # Mark closed to trigger recreation
    cl1.is_closed = True
    cl3 = await c._get_client()
    assert cl3 is not cl1
    assert isinstance(cl3, FakeAsyncClient)


@pytest.mark.asyncio
async def test_aclose_closes_when_open_and_noops_when_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAsyncClient:
        def __init__(self):
            self.is_closed = False
            self.closed_count = 0

        async def aclose(self) -> None:
            self.closed_count += 1
            self.is_closed = True

    c = AIDefenseClient(api_key="k", endpoint_url="u", timeout_s=1)
    fake = FakeAsyncClient()
    c._client = fake  # type: ignore[assignment]
    await c.aclose()
    assert fake.is_closed is True
    assert fake.closed_count == 1

    # No-op when already closed
    await c.aclose()
    assert fake.closed_count == 1


def test_build_endpoint_trailing_slash() -> None:
    assert build_endpoint("https://x/") == "https://x/api/v1/inspect/chat"
    assert build_endpoint("https://x") == "https://x/api/v1/inspect/chat"


@pytest.mark.asyncio
async def test_importerror_path_disables_httpx_and_get_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure a clean reimport of the client module with ImportError for httpx
    monkeypatch.setitem(sys.modules, "httpx", None)

    class ImportBlocker:
        def find_spec(self, fullname, path=None, target=None):  # type: ignore[no-untyped-def]
            if fullname == "httpx":
                raise ImportError("blocked httpx")
            return None

    sys.meta_path.insert(0, ImportBlocker())
    try:
        from agent_control_evaluator_cisco.ai_defense import client as client_mod

        importlib.reload(client_mod)

        assert client_mod.AI_DEFENSE_HTTPX_AVAILABLE is False

        c = client_mod.AIDefenseClient(api_key="k", endpoint_url="u", timeout_s=1)
        with pytest.raises(RuntimeError, match="httpx not installed"):
            await c._get_client()
    finally:
        # Remove our import hook to avoid side effects
        sys.meta_path = [m for m in sys.meta_path if not isinstance(m, ImportBlocker)]
        # Best effort: if httpx is available, restore it by deleting None placeholder
        if sys.modules.get("httpx") is None:
            del sys.modules["httpx"]
