"""Generic management-auth primitives.

The operation vocabulary is intentionally abstract: no Galileo nouns, no
Cerbos nouns, no HTTP status details. Providers map these operations onto
whatever upstream system a deployment uses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fastapi import Request
from pydantic import BaseModel, Field


class ManagementOperation(StrEnum):
    """Operations that Agent Control authorizes on management endpoints.

    The AC boundary deliberately uses one shared operation vocabulary
    instead of per-endpoint action enums. Providers translate these into
    their own action/resource model as needed.
    """

    # Shared Control Store (catalog-level) operations.
    controls_read = "controls.read"
    controls_create = "controls.create"
    controls_update = "controls.update"
    controls_delete = "controls.delete"
    # Per-target binding operations.
    target_bindings_read = "target_bindings.read"
    target_bindings_write = "target_bindings.write"
    # Runtime access. Reserved for a future runtime path; not wired here.
    runtime_use = "runtime.use"


class ManagementPrincipal(BaseModel):
    """The subject a successful authz decision produces.

    Kept minimal on purpose. ``tenant_id`` is the only field AC core uses
    downstream (it flows into existing tenant-scoped lookups). Providers
    may populate ``subject_id`` for audit/logging but AC core should not
    depend on a specific shape.
    """

    tenant_id: str = Field(..., description="Opaque tenant identifier the request resolved to.")
    subject_id: str | None = Field(
        default=None,
        description="Optional subject (user, API key) for observability. Not consumed by AC core.",
    )


# A context-builder reads whatever it needs off the Request (path_params,
# query params, cookies, etc.) and returns the per-operation context dict
# handed to the authorizer. For ``target_bindings.*`` operations it returns
# something like ``{"target_type": ..., "external_id": ...}``; for
# ``controls.*`` it can return an empty dict.
ContextBuilder = Callable[["Request"], dict[str, object]]


@runtime_checkable
class ManagementAuthorizer(Protocol):
    """Provider interface.

    A provider receives the full request (so it can extract credentials
    from headers / cookies without AC core prescribing the shape), the
    generic operation, and a context dict describing the target (if any).
    It returns a ``ManagementPrincipal`` on allow or raises an appropriate
    ``HTTPException`` on deny.
    """

    async def authorize(
        self,
        request: Request,
        *,
        operation: ManagementOperation,
        context: dict[str, object],
    ) -> ManagementPrincipal: ...


# ---------------------------------------------------------------------------
# Process-wide active authorizer (settable at startup by enterprise deployments).
# ---------------------------------------------------------------------------


_active_authorizer: ManagementAuthorizer | None = None


def set_management_authorizer(authorizer: ManagementAuthorizer) -> None:
    """Install the active management authorizer. Intended for startup-time use."""
    global _active_authorizer
    _active_authorizer = authorizer


def get_management_authorizer() -> ManagementAuthorizer:
    """Return the installed authorizer or raise if no mode has been configured."""
    if _active_authorizer is None:
        raise RuntimeError(
            "No management authorizer configured. Call set_management_authorizer(...) "
            "or enable header-mode via configure_management_auth_from_env()."
        )
    return _active_authorizer


# ---------------------------------------------------------------------------
# FastAPI dependency factory
# ---------------------------------------------------------------------------


def require_management_auth(
    operation: ManagementOperation,
    *,
    context_builder: ContextBuilder | None = None,
) -> Callable[[Request], Awaitable[ManagementPrincipal]]:
    """Produce a FastAPI dependency that authorizes ``operation`` per request.

    ``context_builder`` receives the full ``Request`` and returns the context
    dict handed to the authorizer (typically built from ``request.path_params``).
    For operations that do not need context (Control Store reads/writes),
    pass ``None`` and an empty dict is sent.

    The returned dependency is async so providers can do I/O freely.
    """

    async def _dep(request: Request) -> ManagementPrincipal:
        context: dict[str, object] = {}
        if context_builder is not None:
            context = context_builder(request)
        authorizer = get_management_authorizer()
        return await authorizer.authorize(request, operation=operation, context=context)

    return _dep
