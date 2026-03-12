"""Base HTTP client for Agent Control server communication."""

import logging
import os
from types import TracebackType

import httpx

from . import __version__ as sdk_version

_logger = logging.getLogger(__name__)


class AgentControlClient:
    """
    Async HTTP client for Agent Control server.

    This is the base client that provides the HTTP connection management.
    Specific operations are organized into separate modules:
    agents, policies, controls, evaluation.

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
    BASE_URL_ENV_VAR = "AGENT_CONTROL_URL"

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        api_key: str | None = None,
    ):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the Agent Control server. If not provided,
                AGENT_CONTROL_URL is used, falling back to http://localhost:8000.
            timeout: Request timeout in seconds
            api_key: API key for authentication. If not provided, will attempt
                     to read from AGENT_CONTROL_API_KEY environment variable.
        """
        resolved_base_url = base_url or os.environ.get(
            self.BASE_URL_ENV_VAR, "http://localhost:8000"
        )
        self.base_url = resolved_base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key or os.environ.get(self.API_KEY_ENV_VAR)
        self._client: httpx.AsyncClient | None = None
        self._server_version_warning_emitted = False

    @property
    def api_key(self) -> str | None:
        """Get the configured API key (read-only)."""
        return self._api_key

    def _get_headers(self) -> dict[str, str]:
        """Build request headers including authentication."""
        headers: dict[str, str] = {
            "X-Agent-Control-SDK": "python",
            "X-Agent-Control-SDK-Version": sdk_version,
        }
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        return headers

    async def _check_server_version(self, response: httpx.Response) -> None:
        """Warn once when the server major version differs from the SDK major."""
        if self._server_version_warning_emitted:
            return

        server_version = response.headers.get("X-Agent-Control-Server-Version")
        if not server_version:
            return

        sdk_major = sdk_version.split(".", 1)[0]
        server_major = server_version.split(".", 1)[0]
        if sdk_major == server_major:
            return

        _logger.warning(
            "Agent Control SDK major version %s is talking to server major version %s. "
            "Upgrade the SDK and server together to avoid control-schema mismatches.",
            sdk_version,
            server_version,
        )
        self._server_version_warning_emitted = True

    async def __aenter__(self) -> "AgentControlClient":
        """Async context manager entry."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers=self._get_headers(),
            event_hooks={"response": [self._check_server_version]},
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
