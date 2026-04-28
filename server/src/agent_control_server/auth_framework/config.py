"""Environment-driven setup for the request-auth framework.

Reading config at startup and installing the matching providers is
intentionally separate from :mod:`auth_framework.core` so tests can
swap providers without depending on env state.

The framework supports two flows:

- **Default flow** (everything except runtime). One authorizer handles
  every operation that does not have a specific override:
  :class:`HeaderAuthProvider` (local credentials) or
  :class:`HttpUpstreamAuthProvider` (forwards to a configurable URL).
- **Runtime flow.** When ``AGENT_CONTROL_RUNTIME_TOKEN_SECRET`` is
  configured, :class:`LocalJwtVerifyProvider` is registered as the
  override for :data:`Operation.RUNTIME_USE`; the
  ``runtime.token_exchange`` operation continues to flow through the
  default authorizer because the exchange itself is shaped like a
  management call (forward credential, get grant). Without the secret,
  no runtime override is installed.
"""

from __future__ import annotations

import os

from ..logging_utils import get_logger
from .core import Operation, RequestAuthorizer, set_authorizer
from .providers import (
    HeaderAuthProvider,
    HttpUpstreamAuthProvider,
    LocalJwtVerifyProvider,
)
from .providers.http_upstream import HttpUpstreamConfig

_logger = get_logger(__name__)

# Default flow.
_MODE_ENV = "AGENT_CONTROL_AUTH_MODE"
_UPSTREAM_URL_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_URL"
_UPSTREAM_TIMEOUT_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_TIMEOUT_SECONDS"
_UPSTREAM_TOKEN_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_SERVICE_TOKEN"
_UPSTREAM_TOKEN_HEADER_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_SERVICE_TOKEN_HEADER"

# Runtime flow.
_RUNTIME_TOKEN_SECRET_ENV = "AGENT_CONTROL_RUNTIME_TOKEN_SECRET"
_RUNTIME_TOKEN_TTL_ENV = "AGENT_CONTROL_RUNTIME_TOKEN_TTL_SECONDS"
_DEFAULT_RUNTIME_TOKEN_TTL_SECONDS = 300


def configure_auth_from_env() -> None:
    """Install the authorizers selected by environment variables.

    Default flow:

    - ``AGENT_CONTROL_AUTH_MODE=header`` (default): :class:`HeaderAuthProvider`.
    - ``AGENT_CONTROL_AUTH_MODE=http_upstream``: :class:`HttpUpstreamAuthProvider`
      pointed at ``AGENT_CONTROL_AUTH_UPSTREAM_URL``.

    Runtime flow:

    - When ``AGENT_CONTROL_RUNTIME_TOKEN_SECRET`` is set, register
      :class:`LocalJwtVerifyProvider` as an override for
      :data:`Operation.RUNTIME_USE`.
    """
    set_authorizer(_build_default_provider())
    runtime_provider = _maybe_build_runtime_provider()
    if runtime_provider is not None:
        set_authorizer(runtime_provider, operation=Operation.RUNTIME_USE)


def _build_default_provider() -> RequestAuthorizer:
    mode = os.environ.get(_MODE_ENV, "header").strip().lower()
    if mode == "header":
        _logger.info("Default auth provider: header (local credentials)")
        return HeaderAuthProvider()
    if mode == "http_upstream":
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
        _logger.info("Default auth provider: http_upstream url=%s", url)
        return HttpUpstreamAuthProvider(
            HttpUpstreamConfig(
                url=url,
                timeout_seconds=timeout,
                service_token=token,
                service_token_header=token_header,
            )
        )
    raise RuntimeError(
        f"Unknown {_MODE_ENV}={mode!r}; expected 'header' or 'http_upstream'."
    )


def _maybe_build_runtime_provider() -> LocalJwtVerifyProvider | None:
    secret = os.environ.get(_RUNTIME_TOKEN_SECRET_ENV)
    if not secret:
        _logger.info(
            "Runtime auth disabled (%s not set); runtime endpoints "
            "will fall through to the default authorizer.",
            _RUNTIME_TOKEN_SECRET_ENV,
        )
        return None
    _logger.info(
        "Runtime auth enabled: LocalJwtVerifyProvider override installed for %s",
        Operation.RUNTIME_USE.value,
    )
    return LocalJwtVerifyProvider(secret=secret)


def runtime_token_secret() -> str | None:
    """Return the configured runtime-token signing secret, or ``None``."""
    return os.environ.get(_RUNTIME_TOKEN_SECRET_ENV)


def runtime_token_ttl_seconds() -> int:
    """Return the configured runtime-token TTL in seconds (default 300)."""
    raw = os.environ.get(_RUNTIME_TOKEN_TTL_ENV)
    if raw is None:
        return _DEFAULT_RUNTIME_TOKEN_TTL_SECONDS
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"{_RUNTIME_TOKEN_TTL_ENV}={raw!r} is not an integer."
        ) from exc
    if ttl <= 0:
        raise RuntimeError(
            f"{_RUNTIME_TOKEN_TTL_ENV}={ttl} must be positive."
        )
    return ttl
