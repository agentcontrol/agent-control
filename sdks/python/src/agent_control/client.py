"""Base HTTP client for Agent Control server communication."""

import os
from types import TracebackType

import httpx


class AgentControlClient:
    """
    Async HTTP client for Agent Control server.

    This is the base client that provides the HTTP connection management.
    Specific operations are organized into separate modules:
    agents, controls, evaluation.

    Authentication:
        The client supports API key authentication via the X-API-Key header.
        API key can be provided:
        1. Directly via the `api_key` parameter
        2. Via the AGENT_CONTROL_API_KEY environment variable

    Usage:
        # Explicit API key
        async with AgentControlClient(api_key="my-secret-key") as client:
            await client.health_check()

        # From environment variable
        os.environ["AGENT_CONTROL_API_KEY"] = "my-secret-key"
        async with AgentControlClient() as client:
            await client.health_check()
    """

    # Environment variable name for API key
    API_KEY_ENV_VAR = "AGENT_CONTROL_API_KEY"

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 30.0,
        api_key: str | None = None,
    ):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the Agent Control server
            timeout: Request timeout in seconds
            api_key: API key for authentication. If not provided, will attempt
                     to read from AGENT_CONTROL_API_KEY environment variable.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key or os.environ.get(self.API_KEY_ENV_VAR)
        self._client: httpx.AsyncClient | None = None

    @property
    def api_key(self) -> str | None:
        """Get the configured API key (read-only)."""
        return self._api_key

    def _get_headers(self) -> dict[str, str]:
        """Build request headers including authentication."""
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def __aenter__(self) -> "AgentControlClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._get_headers(),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    async def health_check(self) -> dict[str, str]:
        """
        Check server health.

        Returns:
            Dictionary with health status

        Raises:
            httpx.HTTPError: If request fails
        """
        if self._client is None:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")
        response = await self._client.get("/health")
        response.raise_for_status()
        from typing import cast
        return cast(dict[str, str], response.json())

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Get the underlying HTTP client."""
        if self._client is None:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")
        return self._client

