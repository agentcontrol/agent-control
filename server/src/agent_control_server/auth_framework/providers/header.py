"""Default :class:`RequestAuthorizer` that uses local credentials only.

Resolves the namespace from a header (or falls back to
``DEFAULT_NAMESPACE_KEY``) and enforces a per-operation access level
using the legacy API-key + session-cookie credential check from
:mod:`agent_control_server.auth`. Behavior matches the pre-framework
local auth path verbatim:

- ``ADMIN`` operations require an admin key (or admin session).
- ``AUTHENTICATED`` operations require any valid credential.
- ``PUBLIC`` operations are open.
- When ``api_key_enabled`` is ``False`` (no-auth mode), every
  operation succeeds with a non-admin :class:`Principal` — preserved
  by the underlying credential check.

The header lookup is wired but currently inert: the provider always
returns the default namespace because non-binding write endpoints
still hardcode it. The header is kept here so a follow-up that
threads namespace resolution through the rest of the API can flip it
on without changing the provider contract.
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
    Operation.RUNTIME_TOKEN_EXCHANGE: AccessLevel.AUTHENTICATED,
    Operation.RUNTIME_USE: AccessLevel.AUTHENTICATED,
}


class HeaderAuthProvider(RequestAuthorizer):
    """Default authorizer.

    For each operation's configured access level, validates the
    request's credentials via the legacy local check; on success,
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
        # providers; an upstream that explicitly grants no scopes ends
        # up with an empty tuple and is rejected.
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
        # The provider always returns the default namespace because
        # non-binding write endpoints still hardcode it; serving
        # anything else here would create rows the rest of the API
        # cannot find. The branch is preserved so a future change can
        # lift the lock without touching the provider contract.
        del request
        return self._default_namespace_key
