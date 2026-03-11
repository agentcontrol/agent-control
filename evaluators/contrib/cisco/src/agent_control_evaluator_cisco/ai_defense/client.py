from __future__ import annotations

# Thin REST client for Cisco AI Defense Chat Inspection.
# Uses httpx.AsyncClient and the OpenAPI-defined endpoint/header.
from dataclasses import dataclass
from typing import Any

try:
    import httpx

    AI_DEFENSE_HTTPX_AVAILABLE = True
except ImportError:  # Narrow to import error only
    httpx = None  # type: ignore
    AI_DEFENSE_HTTPX_AVAILABLE = False


# Regions from ai_defense_api.json "servers" section
REGION_BASE_URLS: dict[str, str] = {
    "us": "https://us.api.inspect.aidefense.security.cisco.com",
    "ap": "https://ap.api.inspect.aidefense.security.cisco.com",
    "eu": "https://eu.api.inspect.aidefense.security.cisco.com",
}


def build_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/api/v1/inspect/chat"


@dataclass
class AIDefenseClient:
    """Minimal async client for Cisco AI Defense Chat Inspection.

    Attributes:
        api_key: API key used for authentication header
        endpoint_url: Full URL to POST /api/v1/inspect/chat
        timeout_s: Timeout in seconds
    """

    api_key: str
    endpoint_url: str
    timeout_s: float

    _client: httpx.AsyncClient | None = None  # type: ignore[name-defined]

    async def _get_client(self) -> httpx.AsyncClient:  # type: ignore[name-defined]
        if not AI_DEFENSE_HTTPX_AVAILABLE:  # pragma: no cover
            raise RuntimeError("httpx not installed; cannot call Cisco AI Defense REST API")
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def chat_inspect(
        self,
        messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
        inspect_config: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        client = await self._get_client()

        req_headers: dict[str, str] = {
            "X-Cisco-AI-Defense-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        payload: dict[str, Any] = {"messages": messages}
        if metadata is not None:
            payload["metadata"] = metadata
        if inspect_config is not None:
            payload["config"] = inspect_config

        resp = await client.post(self.endpoint_url, json=payload, headers=req_headers)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid response payload: not a JSON object")
        return data

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        await self.aclose()

    async def __aenter__(self) -> "AIDefenseClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
