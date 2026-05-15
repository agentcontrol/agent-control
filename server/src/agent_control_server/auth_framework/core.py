"""Generic primitives for the pluggable request-auth framework.

This module is intentionally provider-neutral: no upstream-specific
nouns, no transport assumptions, no policy engine references.
Providers wire those concerns in
:mod:`agent_control_server.auth_framework.providers`.

Concepts:

- :class:`Operation` is the vocabulary endpoints declare. Adding a new
  endpoint that needs a new permission means adding a member here, not
  changing every provider.
- :class:`Principal` is the resolved-identity result of authorization:
  the namespace the request runs in plus optional caller metadata.
- :class:`RequestAuthorizer` is the seam. Implementations decide whether
  a request may perform an operation; failure raises an HTTP-typed
  error and short-circuits the request.
- :func:`require_operation` is the FastAPI dependency factory endpoints
  attach to. It looks up the active authorizer, builds an optional
  per-request context, and returns the :class:`Principal`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from fastapi import Request


class Operation(StrEnum):
    """Authorization vocabulary spoken on the endpoint side.

    Members are stable wire identifiers; providers map them to whatever
    permission system a deployment uses.
    """

    # Control bindings (target attachments).
    CONTROL_BINDINGS_READ = "control_bindings.read"
    CONTROL_BINDINGS_WRITE = "control_bindings.write"

    # Runtime token exchange - wired on the exchange endpoint.
    RUNTIME_TOKEN_EXCHANGE = "runtime.token_exchange"

    CONTROLS_READ = "controls.read"
    CONTROLS_CREATE = "controls.create"
    CONTROLS_UPDATE = "controls.update"
    CONTROLS_DELETE = "controls.delete"
    POLICIES_READ = "policies.read"
    POLICIES_CREATE = "policies.create"
    POLICIES_UPDATE = "policies.update"
    AGENTS_READ = "agents.read"
    AGENTS_CREATE = "agents.create"
    AGENTS_UPDATE = "agents.update"
    EVALUATORS_READ = "evaluators.read"
    OBSERVABILITY_READ = "observability.read"
    OBSERVABILITY_WRITE = "observability.write"
    RUNTIME_USE = "runtime.use"


@dataclass(frozen=True)
class Principal:
    """Resolved identity for an authorized request.

    Attributes:
        namespace_key: The namespace the request runs in. Endpoints use
            this to scope every read and write.
        is_admin: Whether the caller has admin privileges in the
            current namespace.
        caller_id: Opaque, provider-supplied identifier for the caller
            (e.g., a key fingerprint or user id). Useful for audit
            logging; never echo back to clients.
        target_type: Set when the authorization grants access to a
            specific target. Endpoints can use it to verify the request
            target matches.
        target_id: Companion to ``target_type``; opaque identifier of
            the bound target.
        scopes: Granted capabilities (e.g., ``("runtime.use",)``).
            Populated by providers that surface a normalized grant.
        grant_expires_at: When the upstream grant expires. Used by the
            runtime-token exchange endpoint to bound the local token's
            lifetime.
    """

    namespace_key: str
    is_admin: bool = False
    caller_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    scopes: tuple[str, ...] = ()
    grant_expires_at: datetime | None = None


ContextBuilder = Callable[[Request], dict[str, Any] | Awaitable[dict[str, Any]]]
"""Optional per-request context, e.g. path-parameter pluck for ABAC."""


class RequestAuthorizer(Protocol):
    """Decides whether a request may perform an :class:`Operation`.

    Implementations raise ``AuthenticationError`` (401),
    ``ForbiddenError`` (403), or ``NotFoundError`` (404) on denial; the
    framework does not catch these. On success they return the resolved
    :class:`Principal`.
    """

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal: ...


_default_authorizer: RequestAuthorizer | None = None
_operation_authorizers: dict[Operation, RequestAuthorizer] = {}


def set_authorizer(
    authorizer: RequestAuthorizer | None,
    *,
    operation: Operation | None = None,
) -> None:
    """Install an authorizer.

    Without ``operation``, this becomes the default authorizer used by
    every operation that does not have a specific override. With
    ``operation``, it overrides the default for that operation only -
    used to route a different family (e.g., runtime) through a
    different provider.

    Passing ``None`` clears the default (or the override). Tests use
    this via fixtures to install deterministic providers.
    """
    global _default_authorizer
    if operation is None:
        _default_authorizer = authorizer
        return
    if authorizer is None:
        _operation_authorizers.pop(operation, None)
        return
    _operation_authorizers[operation] = authorizer


def get_authorizer(operation: Operation | None = None) -> RequestAuthorizer:
    """Return the authorizer that should handle ``operation``.

    Looks up the operation-specific override first; falls back to the
    default. Raises if nothing is installed.
    """
    if operation is not None:
        specific = _operation_authorizers.get(operation)
        if specific is not None:
            return specific
    if _default_authorizer is None:
        raise RuntimeError(
            "No RequestAuthorizer installed. Call set_authorizer() at "
            "application startup, or use configure_auth_from_env()."
        )
    return _default_authorizer


def clear_authorizers() -> None:
    """Remove every installed authorizer (default + overrides). Test helper."""
    global _default_authorizer
    _default_authorizer = None
    _operation_authorizers.clear()


def require_operation(
    operation: Operation,
    *,
    context_builder: ContextBuilder | None = None,
) -> Callable[..., Awaitable[Principal]]:
    """Build a FastAPI dependency that authorizes ``operation``.

    The dependency consults the installed authorizer for this specific
    operation (falling back to the default) and returns the resulting
    :class:`Principal` so endpoints can read the resolved
    ``namespace_key`` and target binding without re-deriving them.

    A ``context_builder`` may extract additional context (e.g., path
    parameters) the provider needs to make a decision; the result is
    forwarded to :meth:`RequestAuthorizer.authorize` as ``context``.
    """
    import inspect

    async def dependency(request: Request) -> Principal:
        context: dict[str, Any] | None = None
        if context_builder is not None:
            built = context_builder(request)
            if inspect.isawaitable(built):
                built = await built
            context = built
        authorizer = get_authorizer(operation)
        return await authorizer.authorize(request, operation, context)

    return dependency
