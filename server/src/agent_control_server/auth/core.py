"""Generic request-authorization framework for Agent Control.

This module is the seam between HTTP endpoints and whatever auth system a
deployment wants to plug in. It speaks only generic operation names; no
Galileo, Cerbos, or HTTP-status vocabulary leaks in.

The full vision (incremental rollout)
-------------------------------------

Every authenticated Agent Control endpoint eventually runs through this
single seam by declaring an :class:`Operation` and depending on
:func:`require_operation`. A process-wide :class:`RequestAuthorizer`
(installed at startup) decides allow/deny for each request.

Endpoints classify into four families:

- **public** — no authentication needed (e.g. ``system.login``).
- **management** — catalog-level CRUD and binding operations.
- **runtime** — fast path for SDKs executing controls.
- **observability** — read-only event stream access.

Two providers ship in-tree:

- ``providers/header.HeaderAuthProvider`` — OSS / single-tenant default.
  Reads tenant from ``X-Tenant-Id`` and (except for PUBLIC operations)
  enforces the legacy API-key / admin-key check via :mod:`auth.local`.
  Its ``OSS_AUTH_LEVELS`` map is the single source of truth for which
  operations require which access level in OSS deployments.
- ``providers/http_upstream.HttpUpstreamAuthProvider`` — enterprise
  adapter. Forwards the caller's credential to a configured upstream
  endpoint and uses the upstream's allow/deny decision.

This PR wires only the **management** family. The other three families
still use the legacy ``require_api_key`` / ``require_admin_key`` deps
from :mod:`auth.local`; follow-ups will migrate them onto
``require_operation(...)``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fastapi import Request
from pydantic import BaseModel, Field


class Operation(StrEnum):
    """Generic operations Agent Control authorizes on its endpoints.

    One shared vocabulary across providers; providers translate these
    into their own action/resource models. Values are stable strings —
    they show up in logs and in the upstream wire protocol.
    """

    # --- management family (WIRED) ---
    # Shared Control Store (catalog-level) operations.
    controls_read = "controls.read"
    controls_create = "controls.create"
    controls_update = "controls.update"
    controls_delete = "controls.delete"
    # Per-target binding operations.
    target_bindings_read = "target_bindings.read"
    target_bindings_write = "target_bindings.write"

    # --- runtime family (reserved; not yet wired) ---
    # TODO(auth-framework): wire SDK runtime endpoints onto this operation
    # so the provider-based seam covers the hot path too.
    runtime_use = "runtime.use"

    # --- observability family (reserved; not yet wired) ---
    # TODO(auth-framework): add events_read / events_stream when the
    # observability endpoints migrate onto the framework.

    # --- public family (reserved; not yet wired) ---
    # TODO(auth-framework): add system_login / system_config_read when
    # the unauthenticated system endpoints migrate onto the framework.


class Principal(BaseModel):
    """The subject a successful authorization decision produces.

    Kept minimal on purpose. ``tenant_id`` is the only field downstream
    AC code consumes; ``subject_id`` is carried for logging/audit but AC
    core does not depend on a specific shape.
    """

    tenant_id: str = Field(..., description="Opaque tenant identifier the request resolved to.")
    subject_id: str | None = Field(
        default=None,
        description="Optional subject (user, API key) for observability. Not consumed by AC core.",
    )


# A context-builder reads whatever it needs off the ``Request`` (path params,
# query params, cookies, etc.) and returns the per-operation context dict
# handed to the authorizer. For ``target_bindings.*`` it typically returns
# ``{"target_type": ..., "external_id": ...}``; for ``controls.*`` it
# usually returns an empty dict.
ContextBuilder = Callable[[Request], dict[str, object]]


@runtime_checkable
class RequestAuthorizer(Protocol):
    """Provider interface.

    A provider receives the full request (so it can extract credentials
    from whichever headers/cookies it accepts without AC core prescribing
    a shape), the generic operation, and a context dict describing the
    target (if any). It returns a :class:`Principal` on allow or raises an
    appropriate ``HTTPException`` on deny.
    """

    async def authorize(
        self,
        request: Request,
        *,
        operation: Operation,
        context: dict[str, object],
    ) -> Principal: ...


# ---------------------------------------------------------------------------
# Process-wide active authorizer (installed at startup).
# ---------------------------------------------------------------------------


_active_authorizer: RequestAuthorizer | None = None


def set_request_authorizer(authorizer: RequestAuthorizer) -> None:
    """Install the active request authorizer. Intended for startup-time use."""
    global _active_authorizer
    _active_authorizer = authorizer


def get_request_authorizer() -> RequestAuthorizer:
    """Return the installed authorizer or raise if none has been configured."""
    if _active_authorizer is None:
        raise RuntimeError(
            "No request authorizer configured. Call set_request_authorizer(...) "
            "or enable header-mode via configure_auth_from_env()."
        )
    return _active_authorizer


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


def require_operation(
    operation: Operation,
    *,
    context_builder: ContextBuilder | None = None,
) -> Callable[[Request], Awaitable[Principal]]:
    """Produce a FastAPI dependency that authorizes ``operation`` per request.

    ``context_builder`` receives the full ``Request`` and returns the
    context dict handed to the authorizer (typically built from
    ``request.path_params``). For operations that need no context, pass
    ``None`` and an empty dict is sent.

    The returned dependency is async so providers can do I/O freely.
    """

    async def _dep(request: Request) -> Principal:
        context: dict[str, object] = {}
        if context_builder is not None:
            context = context_builder(request)
        authorizer = get_request_authorizer()
        return await authorizer.authorize(request, operation=operation, context=context)

    return _dep
