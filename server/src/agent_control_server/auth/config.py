"""Startup-time configuration of the request authorizer.

Selects and installs a provider based on environment variables. Call
``configure_auth_from_env`` during app startup; subsequent request
handling uses the installed authorizer via the ``require_operation``
dependency.

Env var names keep their ``MANAGEMENT_AUTH`` prefix for backward
compatibility with existing deployments. The underlying framework is
generic (see :mod:`auth.core`), but today only the management family
of endpoints is wired onto it.
"""

from __future__ import annotations

import os

from ..logging_utils import get_logger
from .core import RequestAuthorizer, set_request_authorizer
from .providers.header import HeaderAuthProvider
from .providers.http_upstream import HttpUpstreamAuthProvider

_logger = get_logger(__name__)

_MODE_HEADER = "header"
_MODE_HTTP_UPSTREAM = "http_upstream"

ENV_MODE = "AGENT_CONTROL_MANAGEMENT_AUTH_MODE"
ENV_UPSTREAM_URL = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_URL"
ENV_UPSTREAM_CHECK_PATH = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_CHECK_PATH"
ENV_UPSTREAM_SERVICE_TOKEN = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_SERVICE_TOKEN"
ENV_UPSTREAM_SERVICE_TOKEN_HEADER = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_SERVICE_TOKEN_HEADER"
ENV_UPSTREAM_TIMEOUT_SECONDS = "AGENT_CONTROL_MANAGEMENT_AUTH_UPSTREAM_TIMEOUT_SECONDS"


def configure_auth_from_env() -> RequestAuthorizer:
    """Read env vars, construct a provider, and install it process-wide.

    Defaults to the header provider so OSS self-hosted deployments work
    without any configuration. Returns the installed authorizer so callers
    that want to hold a reference (e.g. for shutdown) can do so.
    """
    mode = (os.environ.get(ENV_MODE) or _MODE_HEADER).strip().lower()

    if mode == _MODE_HEADER:
        authorizer: RequestAuthorizer = HeaderAuthProvider()
    elif mode == _MODE_HTTP_UPSTREAM:
        upstream_url = os.environ.get(ENV_UPSTREAM_URL, "").strip()
        if not upstream_url:
            raise RuntimeError(
                f"Management auth mode is '{_MODE_HTTP_UPSTREAM}' but {ENV_UPSTREAM_URL} is unset."
            )
        timeout_raw = os.environ.get(ENV_UPSTREAM_TIMEOUT_SECONDS, "").strip()
        timeout_seconds = float(timeout_raw) if timeout_raw else 5.0
        check_path = (
            os.environ.get(ENV_UPSTREAM_CHECK_PATH, "").strip()
            or "/internal/agent_control/auth/check_management_access"
        )
        service_token = os.environ.get(ENV_UPSTREAM_SERVICE_TOKEN, "").strip() or None
        service_token_header = (
            os.environ.get(ENV_UPSTREAM_SERVICE_TOKEN_HEADER, "").strip()
            or "X-Agent-Control-Service-Token"
        )
        authorizer = HttpUpstreamAuthProvider(
            upstream_url=upstream_url,
            check_path=check_path,
            service_token=service_token,
            service_token_header=service_token_header,
            timeout_seconds=timeout_seconds,
        )
    else:
        raise RuntimeError(
            f"Unsupported value for {ENV_MODE}: '{mode}'. "
            f"Expected one of: '{_MODE_HEADER}', '{_MODE_HTTP_UPSTREAM}'."
        )

    set_request_authorizer(authorizer)
    _logger.info("Configured request authorizer", extra={"mode": mode})
    return authorizer
