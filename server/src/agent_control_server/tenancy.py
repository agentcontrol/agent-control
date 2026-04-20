"""Tenant resolution for request handlers.

OSS deployments typically run as a single synthetic tenant. This module
exposes a minimal dependency that reads an optional ``X-Tenant-Id`` header
and falls back to ``DEFAULT_TENANT_ID`` when absent. A richer resolver
(e.g. reading from authenticated context) can be added later; the
dependency signature is the stable contract callers should depend on.
"""

from __future__ import annotations

from fastapi import Header

from .models import DEFAULT_TENANT_ID

TENANT_HEADER_NAME = "X-Tenant-Id"


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
    """Return the effective tenant for this request.

    Callers that omit the header land on the default tenant.
    """
    if x_tenant_id is None:
        return DEFAULT_TENANT_ID
    trimmed = x_tenant_id.strip()
    return trimmed if trimmed else DEFAULT_TENANT_ID
