"""Tenant resolution for request handlers.

OSS deployments typically run as a single synthetic tenant. This module
exposes a request-scoped dependency, ``get_tenant_id``, that returns the
effective tenant for any handler. Resolution flows through a pluggable
``TenantResolver`` so deployments with their own tenant identity source
(e.g. authenticated JWT claims) can swap in an alternative implementation
via ``set_tenant_resolver`` at application startup.

The shipped default, ``HeaderTenantResolver``, reads the optional
``X-Tenant-Id`` header and falls back to ``DEFAULT_TENANT_ID``. That keeps
callers which do not supply a tenant header working unchanged.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import Header

from .models import DEFAULT_TENANT_ID

TENANT_HEADER_NAME = "X-Tenant-Id"


@runtime_checkable
class TenantResolver(Protocol):
    """Resolves the effective tenant for an incoming request.

    Implementations receive the raw header value (``None`` if absent) and
    return a non-empty tenant id. The interface intentionally keeps the
    surface minimal so enterprise extensions can grow it without forcing
    OSS code to adopt auth-specific types.
    """

    def resolve(self, x_tenant_id: str | None) -> str: ...


class HeaderTenantResolver:
    """Default resolver: read ``X-Tenant-Id`` header, fall back to ``DEFAULT_TENANT_ID``."""

    def resolve(self, x_tenant_id: str | None) -> str:
        if x_tenant_id is None:
            return DEFAULT_TENANT_ID
        trimmed = x_tenant_id.strip()
        return trimmed if trimmed else DEFAULT_TENANT_ID


_active_resolver: TenantResolver = HeaderTenantResolver()


def set_tenant_resolver(resolver: TenantResolver) -> None:
    """Install a replacement tenant resolver (e.g. for enterprise deployments).

    The replacement is process-wide; call this during app startup before any
    request is served. Tests that temporarily swap the resolver should restore
    the prior instance in teardown.
    """
    global _active_resolver
    _active_resolver = resolver


def get_active_resolver() -> TenantResolver:
    """Return the currently installed tenant resolver."""
    return _active_resolver


def get_tenant_id(
    x_tenant_id: str | None = Header(
        default=None,
        alias=TENANT_HEADER_NAME,
        # Tenant is a cross-cutting infrastructure concern. Keep it out of
        # per-operation OpenAPI so SDK callers set it via the client (a
        # default request header) rather than passing it into every call.
        include_in_schema=False,
    ),
) -> str:
    """FastAPI dependency that returns the effective tenant for this request.

    Callers that omit the tenant header land on ``DEFAULT_TENANT_ID``.
    Deployments that resolve tenants from their own context can override the
    active resolver via ``set_tenant_resolver``.
    """
    return _active_resolver.resolve(x_tenant_id)
