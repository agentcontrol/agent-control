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
from dataclasses import dataclass

from ..logging_utils import get_logger
from .core import Operation, RequestAuthorizer, clear_authorizers, set_authorizer
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
# HS256 needs at least 256 bits (32 bytes) of secret material to be safe
# against brute force; reject anything shorter so production deployments
# cannot accidentally ship a weak signing key.
_RUNTIME_TOKEN_SECRET_MIN_BYTES = 32
# Hard ceiling on runtime token lifetime. The runtime path exists to keep
# the credential window short; a misconfigured TTL of weeks or years
# defeats the design. ``mint_runtime_token`` already clamps to the
# upstream grant's ``expires_at`` when present, but that only fires when
# the upstream surfaces an expiry; this cap closes the configuration
# gap independent of upstream behavior.
_MAX_RUNTIME_TOKEN_TTL_SECONDS = 86_400


@dataclass(frozen=True)
class RuntimeAuthConfig:
    """Validated runtime-auth configuration.

    Built once at startup so the mint side (exchange endpoint) and the
    verify side (:class:`LocalJwtVerifyProvider`) read the same values.
    """

    secret: str
    ttl_seconds: int


_runtime_auth_config: RuntimeAuthConfig | None = None
_active_providers: list[RequestAuthorizer] = []


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

    Clears any previously-installed default and operation overrides
    before installing fresh ones, so reconfiguration cannot leave
    stale routes pointing at a no-longer-relevant provider (e.g., a
    runtime override sticking around after the runtime secret is
    removed). Tracks installed providers so :func:`teardown_auth` can
    release any long-lived resources (e.g., the upstream HTTP client)
    at shutdown.
    """
    global _runtime_auth_config
    clear_authorizers()
    _active_providers.clear()
    _runtime_auth_config = _load_runtime_auth_config()

    default = _build_default_provider()
    set_authorizer(default)
    _active_providers.append(default)

    if _runtime_auth_config is not None:
        runtime_provider = LocalJwtVerifyProvider(secret=_runtime_auth_config.secret)
        set_authorizer(runtime_provider, operation=Operation.RUNTIME_USE)
        _active_providers.append(runtime_provider)
        _logger.info(
            "Runtime auth enabled: LocalJwtVerifyProvider override installed for %s",
            Operation.RUNTIME_USE.value,
        )
    else:
        _logger.warning(
            "Runtime auth disabled (%s not set); %s falls through to the "
            "default authorizer, which may grant any authenticated credential. "
            "Set the runtime token secret to bind runtime calls to a "
            "short-lived target-scoped JWT.",
            _RUNTIME_TOKEN_SECRET_ENV,
            Operation.RUNTIME_USE.value,
        )


async def teardown_auth() -> None:
    """Close long-lived resources and clear every installed authorizer.

    Called from the FastAPI lifespan at shutdown. Authorizers that own
    a persistent client (e.g., :class:`HttpUpstreamAuthProvider`) expose
    an async ``aclose`` method that gets invoked here. The default and
    operation-specific authorizers are then both removed from the
    registry so no stale state can survive into a subsequent
    :func:`configure_auth_from_env` call.
    """
    global _runtime_auth_config
    for provider in _active_providers:
        aclose = getattr(provider, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:  # noqa: BLE001  shutdown best-effort
                _logger.exception("Error closing auth provider %s", provider)
    _active_providers.clear()
    _runtime_auth_config = None
    clear_authorizers()


def runtime_auth_config() -> RuntimeAuthConfig | None:
    """Return the validated runtime-auth config, or ``None`` when disabled.

    Loaded once by :func:`configure_auth_from_env`; the mint and verify
    sides read this same object so they cannot drift apart.
    """
    return _runtime_auth_config


def set_runtime_auth_config(config: RuntimeAuthConfig | None) -> None:
    """Install a runtime-auth config without reading the environment.

    Test helper that mirrors :func:`set_authorizer`: lets tests pin a
    deterministic config (or clear it) without going through
    :func:`configure_auth_from_env`. Production code should never call
    this; use ``configure_auth_from_env`` instead so the secret-strength
    and TTL validations run.
    """
    global _runtime_auth_config
    _runtime_auth_config = config


def _build_default_provider() -> RequestAuthorizer:
    mode = os.environ.get(_MODE_ENV, "header").strip().lower()
    if mode == "header":
        _logger.info("Default auth provider: header (local credentials)")
        return HeaderAuthProvider()
    if mode == "http_upstream":
        url = os.environ.get(_UPSTREAM_URL_ENV)
        if not url:
            raise RuntimeError(f"{_MODE_ENV}=http_upstream but {_UPSTREAM_URL_ENV} is not set.")
        timeout = float(os.environ.get(_UPSTREAM_TIMEOUT_ENV, "5.0"))
        token = os.environ.get(_UPSTREAM_TOKEN_ENV)
        token_header = os.environ.get(_UPSTREAM_TOKEN_HEADER_ENV, "X-Agent-Control-Service-Token")
        _logger.info("Default auth provider: http_upstream url=%s", url)
        return HttpUpstreamAuthProvider(
            HttpUpstreamConfig(
                url=url,
                timeout_seconds=timeout,
                service_token=token,
                service_token_header=token_header,
            )
        )
    raise RuntimeError(f"Unknown {_MODE_ENV}={mode!r}; expected 'header' or 'http_upstream'.")


def _load_runtime_auth_config() -> RuntimeAuthConfig | None:
    """Parse, validate, and return the runtime-auth config from env.

    Returns ``None`` when no runtime secret is configured. Raises
    ``RuntimeError`` when the secret is too short or the TTL is invalid
    so misconfiguration surfaces at startup, not on the first
    request-time mint.
    """
    secret = os.environ.get(_RUNTIME_TOKEN_SECRET_ENV)
    if not secret:
        return None
    if len(secret.encode("utf-8")) < _RUNTIME_TOKEN_SECRET_MIN_BYTES:
        raise RuntimeError(
            f"{_RUNTIME_TOKEN_SECRET_ENV} must be at least "
            f"{_RUNTIME_TOKEN_SECRET_MIN_BYTES} bytes; HS256 signing keys "
            f"shorter than that are vulnerable to brute force."
        )
    return RuntimeAuthConfig(secret=secret, ttl_seconds=_load_runtime_ttl_seconds())


def _load_runtime_ttl_seconds() -> int:
    raw = os.environ.get(_RUNTIME_TOKEN_TTL_ENV)
    if raw is None:
        return _DEFAULT_RUNTIME_TOKEN_TTL_SECONDS
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{_RUNTIME_TOKEN_TTL_ENV}={raw!r} is not an integer.") from exc
    if ttl <= 0:
        raise RuntimeError(f"{_RUNTIME_TOKEN_TTL_ENV}={ttl} must be positive.")
    if ttl > _MAX_RUNTIME_TOKEN_TTL_SECONDS:
        raise RuntimeError(
            f"{_RUNTIME_TOKEN_TTL_ENV}={ttl} exceeds the maximum of "
            f"{_MAX_RUNTIME_TOKEN_TTL_SECONDS} seconds. Long-lived runtime "
            f"tokens defeat the short-credential design; configure a shorter "
            f"TTL or rotate via re-exchange."
        )
    return ttl
