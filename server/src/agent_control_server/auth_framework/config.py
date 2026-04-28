"""Environment-driven setup for the request-auth framework.

Reading config at startup and installing the matching provider is
intentionally separate from :mod:`auth_framework.core` so tests can
swap providers without depending on env state.
"""

from __future__ import annotations

import os

from ..logging_utils import get_logger
from .core import RequestAuthorizer, set_authorizer
from .providers import HeaderAuthProvider, HttpUpstreamAuthProvider
from .providers.http_upstream import HttpUpstreamConfig

_logger = get_logger(__name__)

_MODE_ENV = "AGENT_CONTROL_MANAGEMENT_AUTH_MODE"
_UPSTREAM_URL_ENV = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_URL"
_UPSTREAM_TIMEOUT_ENV = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_TIMEOUT_SECONDS"
_UPSTREAM_TOKEN_ENV = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_SERVICE_TOKEN"
_UPSTREAM_TOKEN_HEADER_ENV = (
    "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_SERVICE_TOKEN_HEADER"
)


def configure_auth_from_env() -> RequestAuthorizer:
    """Install the authorizer selected by environment variables.

    Modes:

    - ``header`` (default): :class:`HeaderAuthProvider`. OSS / single-namespace.
    - ``http_upstream``: :class:`HttpUpstreamAuthProvider` pointed at
      the URL in ``AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_URL``.
    """
    mode = os.environ.get(_MODE_ENV, "header").strip().lower()

    if mode == "header":
        provider: RequestAuthorizer = HeaderAuthProvider()
        _logger.info("Auth framework configured: header (OSS default)")
    elif mode == "http_upstream":
        url = os.environ.get(_UPSTREAM_URL_ENV)
        if not url:
            raise RuntimeError(
                f"{_MODE_ENV}=http_upstream but {_UPSTREAM_URL_ENV} is not set."
            )
        timeout = float(os.environ.get(_UPSTREAM_TIMEOUT_ENV, "5.0"))
        token = os.environ.get(_UPSTREAM_TOKEN_ENV)
        token_header = os.environ.get(
            _UPSTREAM_TOKEN_HEADER_ENV, "X-Agent-Control-Service-Token"
        )
        provider = HttpUpstreamAuthProvider(
            HttpUpstreamConfig(
                url=url,
                timeout_seconds=timeout,
                service_token=token,
                service_token_header=token_header,
            )
        )
        _logger.info("Auth framework configured: http_upstream url=%s", url)
    else:
        raise RuntimeError(
            f"Unknown {_MODE_ENV}={mode!r}; expected 'header' or 'http_upstream'."
        )

    set_authorizer(provider)
    return provider
