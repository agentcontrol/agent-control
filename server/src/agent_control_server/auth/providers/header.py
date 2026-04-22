"""OSS / single-tenant provider.

Preserves the legacy OSS behavior: endpoints that historically required a
plain API key still require one, endpoints that historically required an
admin key still require one, and unauthenticated endpoints stay
unauthenticated. The mapping lives in :data:`OSS_AUTH_LEVELS` so adding
a new operation or changing an access level is a one-line change.

Tenant identity in OSS is resolved from the ``X-Tenant-Id`` header,
defaulting to :data:`agent_control_server.models.DEFAULT_TENANT_ID`.
Multi-tenant deployments should swap this provider out for
:class:`auth.providers.http_upstream.HttpUpstreamAuthProvider`.
"""

from __future__ import annotations

from enum import Enum

from fastapi import Request

from ...models import DEFAULT_TENANT_ID
from ...tenancy import TENANT_HEADER_NAME
from ..core import Operation, Principal
from ..local import authenticate_request


class LocalAccessLevel(Enum):
    """Access requirement for an operation under the local / OSS provider.

    This concept is intentionally local to the header provider: other
    providers (e.g. ``HttpUpstreamAuthProvider``) do not use it. The AC
    core framework only speaks :class:`Operation`.
    """

    PUBLIC = "public"  # no authentication required
    AUTHENTICATED = "authenticated"  # any valid API key or session cookie
    ADMIN = "admin"  # admin API key or admin session cookie


# Single source of truth for which operations need which access level in
# OSS / single-tenant deployments. As new operations migrate onto the
# framework, add their entries here. The framework rejects operations
# that lack an entry to force the migration to be explicit.
#
# Levels chosen to match the legacy router gates:
#   - controls.read            AUTHENTICATED  (was router-level require_api_key)
#   - controls.{create,update,delete}  ADMIN  (was endpoint-level require_admin_key)
#   - target_bindings.read     AUTHENTICATED  (was router-level require_api_key)
#   - target_bindings.write    ADMIN          (was endpoint-level require_admin_key)
#   - runtime.use              AUTHENTICATED  (SDK hot path)
OSS_AUTH_LEVELS: dict[Operation, LocalAccessLevel] = {
    Operation.controls_read: LocalAccessLevel.AUTHENTICATED,
    Operation.controls_create: LocalAccessLevel.ADMIN,
    Operation.controls_update: LocalAccessLevel.ADMIN,
    Operation.controls_delete: LocalAccessLevel.ADMIN,
    Operation.target_bindings_read: LocalAccessLevel.AUTHENTICATED,
    Operation.target_bindings_write: LocalAccessLevel.ADMIN,
    Operation.runtime_use: LocalAccessLevel.AUTHENTICATED,
}


class HeaderAuthProvider:
    """Local credential check + tenant-from-header.

    Conforms to :class:`auth.core.RequestAuthorizer` via duck typing.
    """

    def __init__(self, default_tenant_id: str = DEFAULT_TENANT_ID) -> None:
        self._default_tenant_id = default_tenant_id

    async def authorize(
        self,
        request: Request,
        *,
        operation: Operation,
        context: dict[str, object],
    ) -> Principal:
        level = OSS_AUTH_LEVELS.get(operation)
        if level is None:
            # Force a migration: an operation without an explicit OSS
            # level is a programming error, not a silent allow.
            raise RuntimeError(
                f"No OSS access level registered for operation '{operation.value}'. "
                f"Add an entry to OSS_AUTH_LEVELS."
            )

        if level is LocalAccessLevel.AUTHENTICATED:
            await authenticate_request(request, require_admin=False)
        elif level is LocalAccessLevel.ADMIN:
            await authenticate_request(request, require_admin=True)
        # PUBLIC: no credential check.

        raw = request.headers.get(TENANT_HEADER_NAME)
        tenant_id = (raw or "").strip() or self._default_tenant_id
        return Principal(tenant_id=tenant_id, subject_id=None)
