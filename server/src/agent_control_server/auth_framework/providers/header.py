"""Default :class:`RequestAuthorizer` that uses local credentials only.

Returns ``DEFAULT_NAMESPACE_KEY`` and enforces a per-operation access
level using the local API-key + session-cookie credential check from
:mod:`agent_control_server.auth`:

- ``ADMIN`` operations require an admin key (or admin session).
- ``AUTHENTICATED`` operations require any valid credential.
- ``PUBLIC`` operations are open.
- When the underlying local credential layer is disabled, every
  operation succeeds with a non-admin :class:`Principal`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import Request

from ...auth import _validate_api_key
from ...models import DEFAULT_NAMESPACE_KEY
from ..core import Operation, Principal, RequestAuthorizer


class AccessLevel(Enum):
    """Access level required for an operation under the local-credential path."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    ADMIN = "admin"


# Single source of truth for the local-credential access policy. Adding
# a new :class:`Operation` here makes its required access level
# explicit and auditable; missing entries are rejected at startup so
# wiring drift is loud, not silent.
DEFAULT_OPERATION_ACCESS: dict[Operation, AccessLevel] = {
    Operation.CONTROL_BINDINGS_READ: AccessLevel.AUTHENTICATED,
    Operation.CONTROL_BINDINGS_WRITE: AccessLevel.ADMIN,
    Operation.CONTROLS_READ: AccessLevel.AUTHENTICATED,
    Operation.CONTROLS_CREATE: AccessLevel.ADMIN,
    Operation.CONTROLS_UPDATE: AccessLevel.ADMIN,
    Operation.CONTROLS_DELETE: AccessLevel.ADMIN,
    Operation.POLICIES_READ: AccessLevel.AUTHENTICATED,
    Operation.POLICIES_CREATE: AccessLevel.ADMIN,
    Operation.POLICIES_UPDATE: AccessLevel.ADMIN,
    Operation.AGENTS_READ: AccessLevel.AUTHENTICATED,
    Operation.AGENTS_CREATE: AccessLevel.AUTHENTICATED,
    Operation.AGENTS_UPDATE: AccessLevel.ADMIN,
    Operation.EVALUATORS_READ: AccessLevel.AUTHENTICATED,
    Operation.OBSERVABILITY_READ: AccessLevel.AUTHENTICATED,
    Operation.OBSERVABILITY_WRITE: AccessLevel.AUTHENTICATED,
    Operation.RUNTIME_TOKEN_EXCHANGE: AccessLevel.AUTHENTICATED,
    Operation.RUNTIME_USE: AccessLevel.AUTHENTICATED,
}


class HeaderAuthProvider(RequestAuthorizer):
    """Default authorizer.

    For each operation's configured access level, validates the
    request's credentials via the local credential check; on success,
    returns a :class:`Principal` scoped to the resolved namespace.
    """

    def __init__(
        self,
        *,
        operation_access: dict[Operation, AccessLevel] | None = None,
        default_namespace_key: str = DEFAULT_NAMESPACE_KEY,
    ) -> None:
        self._operation_access = (
            DEFAULT_OPERATION_ACCESS if operation_access is None else operation_access
        )
        self._default_namespace_key = default_namespace_key

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        del context  # The local-credential path does not use context.

        access = self._operation_access.get(operation)
        if access is None:
            raise RuntimeError(f"No access level configured for operation {operation.value!r}")

        namespace_key = self._resolve_namespace_key(request)

        if access is AccessLevel.PUBLIC:
            return Principal(namespace_key=namespace_key)

        api_key = request.headers.get("X-API-Key")
        client = await _validate_api_key(
            api_key,
            request,
            require_admin=access is AccessLevel.ADMIN,
        )
        # Runtime token exchange returns a normalized scope grant so the
        # exchange endpoint can require ``runtime.use`` uniformly across
        # providers.
        scopes: tuple[str, ...] = (
            (Operation.RUNTIME_USE.value,) if operation is Operation.RUNTIME_TOKEN_EXCHANGE else ()
        )
        return Principal(
            namespace_key=namespace_key,
            is_admin=client.is_admin,
            caller_id=client.key_id,
            scopes=scopes,
        )

    def _resolve_namespace_key(self, request: Request) -> str:
        # Local credentials do not carry namespace metadata. Providers
        # that resolve a namespace can return a different principal.
        del request
        return self._default_namespace_key
