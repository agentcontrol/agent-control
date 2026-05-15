"""Environment-driven setup for the request-auth framework.

Reading config at startup and installing the matching providers is
intentionally separate from :mod:`auth_framework.core` so tests can
swap providers without depending on env state.

The framework supports two flows:

- **Default flow** (everything except runtime). One authorizer handles
  every operation that does not have a specific override:
  :class:`NoAuthProvider` (no credentials),
  :class:`HeaderAuthProvider` (local API keys), or
  :class:`HttpUpstreamAuthProvider` (forwards to a configurable URL).
- **Runtime flow.** ``AGENT_CONTROL_RUNTIME_AUTH_MODE`` selects the
  override for :data:`Operation.RUNTIME_USE`: ``none`` uses
  :class:`NoAuthProvider`, ``api_key`` uses
  :class:`HeaderAuthProvider`, and ``jwt`` uses
  :class:`LocalJwtVerifyProvider`. When the mode is unset, startup
  selects ``jwt`` if ``AGENT_CONTROL_RUNTIME_TOKEN_SECRET`` is set;
  otherwise runtime falls through to the default authorizer.
  The ``runtime.token_exchange`` operation continues to flow through
  the default authorizer because the exchange itself is shaped like a
  management call (forward credential, get grant).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ..config import auth_settings
from ..logging_utils import get_logger
from .core import Operation, RequestAuthorizer, clear_authorizers, set_authorizer
from .providers import (
    HeaderAuthProvider,
    HttpUpstreamAuthProvider,
    LocalJwtVerifyProvider,
    NoAuthProvider,
)
from .providers.http_upstream import HttpUpstreamConfig

_logger = get_logger(__name__)

# Default flow.
_MODE_ENV = "AGENT_CONTROL_AUTH_MODE"
_UPSTREAM_URL_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_URL"
_UPSTREAM_TIMEOUT_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_TIMEOUT_SECONDS"
_UPSTREAM_TOKEN_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_SERVICE_TOKEN"
_UPSTREAM_TOKEN_HEADER_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_SERVICE_TOKEN_HEADER"
_UPSTREAM_EXTRA_FORWARD_HEADERS_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_EXTRA_FORWARD_HEADERS"

# Runtime flow.
_RUNTIME_MODE_ENV = "AGENT_CONTROL_RUNTIME_AUTH_MODE"
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

    - ``AGENT_CONTROL_AUTH_MODE=none``: :class:`NoAuthProvider`.
    - ``AGENT_CONTROL_AUTH_MODE=api_key``: :class:`HeaderAuthProvider`.
      ``header`` remains accepted as a backwards-compatible alias. When the mode
      is unset, startup selects ``api_key`` only if local API-key validation is
      enabled; otherwise it selects ``none``.
    - ``AGENT_CONTROL_AUTH_MODE=http_upstream``: :class:`HttpUpstreamAuthProvider`
      pointed at ``AGENT_CONTROL_AUTH_UPSTREAM_URL``.

    Runtime flow:

    - ``AGENT_CONTROL_RUNTIME_AUTH_MODE=none``: :class:`NoAuthProvider`.
    - ``AGENT_CONTROL_RUNTIME_AUTH_MODE=api_key``: :class:`HeaderAuthProvider`.
    - ``AGENT_CONTROL_RUNTIME_AUTH_MODE=jwt`` (default when a runtime token
      secret is configured): :class:`LocalJwtVerifyProvider`.
    - unset mode without a runtime token secret: fall through to the default
      authorizer.

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
    runtime_mode = _resolve_runtime_mode()
    _runtime_auth_config = (
        _load_runtime_auth_config(require_secret=True) if runtime_mode == "jwt" else None
    )

    default = _build_default_provider()
    set_authorizer(default)
    _active_providers.append(default)

    if runtime_mode == "default":
        _logger.info(
            "Runtime auth provider: default authorizer handles %s",
            Operation.RUNTIME_USE.value,
        )
    else:
        runtime_provider = _build_runtime_provider(runtime_mode, _runtime_auth_config)
        set_authorizer(runtime_provider, operation=Operation.RUNTIME_USE)
        _active_providers.append(runtime_provider)
        if runtime_mode == "jwt":
            _logger.info(
                "Runtime auth provider: jwt override installed for %s",
                Operation.RUNTIME_USE.value,
            )
        else:
            _logger.info(
                "Runtime auth provider: %s override installed for %s",
                runtime_mode,
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
    raw_mode = os.environ.get(_MODE_ENV)
    mode = (
        raw_mode
        if raw_mode is not None
        else ("api_key" if auth_settings.api_key_enabled else "none")
    ).strip().lower()
    if mode in {"none", "no_auth"}:
        _logger.info("Default auth provider: none")
        return NoAuthProvider()
    if mode in {"api_key", "header"}:
        _validate_local_api_key_mode()
        _logger.info("Default auth provider: api_key (local credentials)")
        return HeaderAuthProvider()
    if mode == "http_upstream":
        url = os.environ.get(_UPSTREAM_URL_ENV)
        if not url:
            raise RuntimeError(f"{_MODE_ENV}=http_upstream but {_UPSTREAM_URL_ENV} is not set.")
        timeout = float(os.environ.get(_UPSTREAM_TIMEOUT_ENV, "5.0"))
        token = os.environ.get(_UPSTREAM_TOKEN_ENV)
        token_header = os.environ.get(_UPSTREAM_TOKEN_HEADER_ENV, "X-Agent-Control-Service-Token")
        extra_forward_headers = _parse_extra_forward_headers(
            os.environ.get(_UPSTREAM_EXTRA_FORWARD_HEADERS_ENV)
        )
        _logger.info("Default auth provider: http_upstream url=%s", url)
        return HttpUpstreamAuthProvider(
            HttpUpstreamConfig(
                url=url,
                timeout_seconds=timeout,
                service_token=token,
                service_token_header=token_header,
                extra_forward_headers=extra_forward_headers,
            )
        )
    raise RuntimeError(
        f"Unknown {_MODE_ENV}={mode!r}; expected 'none', 'api_key', 'header', "
        "or 'http_upstream'."
    )


def _validate_local_api_key_mode(mode_env: str = _MODE_ENV) -> None:
    """Fail startup when local API-key mode has no local key validator."""
    if not auth_settings.api_key_enabled:
        raise RuntimeError(
            f"{mode_env}=api_key requires AGENT_CONTROL_API_KEY_ENABLED=true. "
            f"Use {mode_env}=none for deployments without credential enforcement."
        )
    if not auth_settings.get_api_keys() and not auth_settings.get_admin_api_keys():
        raise RuntimeError(
            f"{_MODE_ENV}=api_key requires AGENT_CONTROL_API_KEYS or "
            "AGENT_CONTROL_ADMIN_API_KEYS to be configured."
        )


def _parse_extra_forward_headers(raw: str | None) -> tuple[str, ...]:
    """Parse a comma-separated header list into a deduplicated tuple.

    Empty / unset env var returns an empty tuple. Whitespace around each
    name is stripped. Empty entries (e.g. ``"X-A,,X-B"``) are dropped.
    Order is preserved; duplicates (case-insensitive) are dropped after
    the first occurrence.
    """
    if not raw or not raw.strip():
        return ()
    seen: set[str] = set()
    result: list[str] = []
    for raw_name in raw.split(","):
        name = raw_name.strip()
        if not name:
            continue
        lower = name.lower()
        if lower in seen:
            continue
        seen.add(lower)
        result.append(name)
    return tuple(result)


def _resolve_runtime_mode() -> str:
    raw = os.environ.get(_RUNTIME_MODE_ENV)
    if raw is None or not raw.strip():
        return "jwt" if os.environ.get(_RUNTIME_TOKEN_SECRET_ENV) else "default"

    mode = raw.strip().lower()
    if mode in {"none", "no_auth"}:
        return "none"
    if mode in {"api_key", "header"}:
        return "api_key"
    if mode == "jwt":
        return mode
    raise RuntimeError(
        f"Unknown {_RUNTIME_MODE_ENV}={mode!r}; expected 'none', 'api_key', "
        "'header', or 'jwt'."
    )


def _build_runtime_provider(
    mode: str,
    config: RuntimeAuthConfig | None,
) -> RequestAuthorizer:
    if mode == "none":
        return NoAuthProvider()
    if mode == "api_key":
        _validate_local_api_key_mode(_RUNTIME_MODE_ENV)
        return HeaderAuthProvider()
    if mode == "jwt":
        if config is None:
            raise RuntimeError(f"{_RUNTIME_MODE_ENV}=jwt but runtime auth config is missing.")
        return LocalJwtVerifyProvider(secret=config.secret)
    raise RuntimeError(
        f"Unknown runtime auth mode {mode!r}; expected 'none', 'api_key', or 'jwt'."
    )


def _load_runtime_auth_config(*, require_secret: bool = False) -> RuntimeAuthConfig | None:
    """Parse, validate, and return the runtime-auth config from env.

    Returns ``None`` when no runtime secret is configured and
    ``require_secret`` is false. Raises ``RuntimeError`` when the
    secret is required, too short, or the TTL is invalid so
    misconfiguration surfaces at startup, not on the first request-time
    mint.
    """
    secret = os.environ.get(_RUNTIME_TOKEN_SECRET_ENV)
    if not secret:
        if require_secret:
            raise RuntimeError(
                f"{_RUNTIME_MODE_ENV}=jwt requires {_RUNTIME_TOKEN_SECRET_ENV} to be set."
            )
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
