"""Thin async REST client for the TypeSafe System One endpoint."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any

# Statuses worth retrying: the service is busy or briefly unavailable, not
# wrong. 529 is the overloaded response the API returns under load.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 0.4

try:
    import httpx

    TYPESAFE_HTTPX_AVAILABLE = True
except ImportError:  # Narrow to import error only
    httpx = None  # type: ignore[assignment]
    TYPESAFE_HTTPX_AVAILABLE = False


def build_endpoint(base_url: str) -> str:
    """Return the System One URL for an API origin."""
    return f"{base_url.rstrip('/')}/v1/systemone"


@dataclass
class TypeSafeClient:
    """Minimal async client for POST /v1/systemone.

    Attributes:
        api_key: Bearer token for the Authorization header.
        endpoint_url: Full URL to POST.
        timeout_s: Request timeout in seconds.
    """

    api_key: str = field(repr=False)
    endpoint_url: str
    #: Total budget for one system_one call, retries included. The engine wraps
    #: the evaluator in a timeout of its own, so retrying past this only turns a
    #: recoverable error into a timeout.
    timeout_s: float
    max_attempts: int = MAX_ATTEMPTS

    _client: httpx.AsyncClient | None = field(  # type: ignore[name-defined]
        default=None,
        repr=False,
        compare=False,
    )

    async def _get_client(self) -> httpx.AsyncClient:  # type: ignore[name-defined]
        if not TYPESAFE_HTTPX_AVAILABLE:  # pragma: no cover
            raise RuntimeError("httpx not installed; cannot call the TypeSafe API")
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def system_one(
        self,
        state: Any,
        questions: dict[str, dict[str, Any]],
        model: str,
    ) -> dict[str, Any]:
        """Ask one batch of typed questions about a state.

        Args:
            state: The context Jev evaluates. A string, mapping, or sequence.
            questions: Question objects keyed by question id.
            model: Model identifier.

        Returns:
            The decoded JSON response body.

        Raises:
            RuntimeError: The response body is not a JSON object.
            httpx.HTTPStatusError: The API returned a non-2xx status.
        """
        client = await self._get_client()
        payload: dict[str, Any] = {"model": model, "state": state, "questions": questions}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        deadline = time.monotonic() + self.timeout_s
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            resp = await client.post(
                self.endpoint_url, json=payload, headers=headers, timeout=remaining
            )
            if resp.status_code in RETRY_STATUSES and attempt < self.max_attempts - 1:
                # Honour Retry-After when the service sends one, otherwise back
                # off exponentially with jitter so retries do not synchronise.
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except ValueError:
                    delay = 0.0
                if delay <= 0:
                    delay = BACKOFF_BASE_SECONDS * (2**attempt)
                delay += random.uniform(0, 0.2)
                # Only wait if there is budget left to make the next attempt
                # worthwhile. Otherwise fall through and report this response.
                if time.monotonic() + delay >= deadline:
                    resp.raise_for_status()
                await asyncio.sleep(delay)
                continue
            try:
                resp.raise_for_status()
            except Exception as error:  # noqa: BLE001 - re-raised after the loop
                last_error = error
                break
            data = resp.json()
            if not isinstance(data, dict):
                raise RuntimeError("Invalid TypeSafe response payload: not a JSON object")
            return data

        if last_error is not None:
            raise last_error
        raise RuntimeError(
            f"TypeSafe API did not succeed after {self.max_attempts} attempts"
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
