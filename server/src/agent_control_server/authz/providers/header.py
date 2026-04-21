"""Header-based provider for OSS / single-tenant deployments.

Trusts an ``X-Tenant-Id`` header and performs no real authorization. All
requests are allowed as long as the tenant header resolves (defaulting to
``DEFAULT_TENANT_ID`` when absent). This matches the existing OSS behavior
and lets self-hosted single-tenant deployments continue to work without
requiring any external auth system.

Do not use this provider in multi-tenant deployments.
"""

from __future__ import annotations

from fastapi import Request

from ...models import DEFAULT_TENANT_ID
from ...tenancy import TENANT_HEADER_NAME
from ..base import ManagementOperation, ManagementPrincipal


class HeaderManagementAuthorizer:
    """Resolves tenant from ``X-Tenant-Id`` header; allow-all otherwise.

    The shape matches the ``ManagementAuthorizer`` protocol via duck typing.
    """

    def __init__(self, default_tenant_id: str = DEFAULT_TENANT_ID) -> None:
        self._default_tenant_id = default_tenant_id

    async def authorize(
        self,
        request: Request,
        *,
        operation: ManagementOperation,
        context: dict[str, object],
    ) -> ManagementPrincipal:
        raw = request.headers.get(TENANT_HEADER_NAME)
        tenant_id = (raw or "").strip() or self._default_tenant_id
        return ManagementPrincipal(tenant_id=tenant_id, subject_id=None)
