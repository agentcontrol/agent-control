"""OSS / single-namespace default :class:`RequestAuthorizer`.

Resolves the namespace from a header (or falls back to
``DEFAULT_NAMESPACE_KEY``) and enforces a per-operation OSS access
level using the legacy API-key + session-cookie credential check from
:mod:`agent_control_server.auth`. This preserves existing OSS behavior
verbatim: ``ADMIN`` operations require an admin key (or admin session),
``AUTHENTICATED`` operations require any valid credential, ``PUBLIC``
operations are open.

The header lookup is wired but currently inert: V1 only supports the
default namespace because non-binding write endpoints still hardcode
it. The header is kept here so a follow-up migration that threads
namespace resolution through the rest of the API can flip it on
without changing the provider contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import Request

from ...auth import _validate_api_key
from ...models import DEFAULT_NAMESPACE_KEY
from ..core import Operation, Principal, RequestAuthorizer


class OssAccessLevel(Enum):
    """OSS-side access level required for an operation."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    ADMIN = "admin"


# Single source of truth for OSS access policy. Adding a new
# :class:`Operation` here makes its OSS access level explicit and
# auditable; missing entries are rejected at startup so wiring drift is
# loud, not silent.
OSS_OPERATION_ACCESS: dict[Operation, OssAccessLevel] = {
    Operation.CONTROL_BINDINGS_READ: OssAccessLevel.AUTHENTICATED,
    Operation.CONTROL_BINDINGS_WRITE: OssAccessLevel.ADMIN,
    Operation.CONTROLS_READ: OssAccessLevel.AUTHENTICATED,
    Operation.CONTROLS_CREATE: OssAccessLevel.ADMIN,
    Operation.CONTROLS_UPDATE: OssAccessLevel.ADMIN,
    Operation.CONTROLS_DELETE: OssAccessLevel.ADMIN,
    Operation.RUNTIME_USE: OssAccessLevel.AUTHENTICATED,
}


class HeaderAuthProvider(RequestAuthorizer):
    """OSS-default authorizer.

    For the operation's OSS access level, validates the request's
    credentials via the legacy local check; on success, returns a
    :class:`Principal` scoped to the resolved namespace.
    """

    def __init__(
        self,
        *,
        operation_access: dict[Operation, OssAccessLevel] | None = None,
        default_namespace_key: str = DEFAULT_NAMESPACE_KEY,
    ) -> None:
        self._operation_access = (
            OSS_OPERATION_ACCESS if operation_access is None else operation_access
        )
        self._default_namespace_key = default_namespace_key

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        del context  # OSS path does not need per-request context.

        access = self._operation_access.get(operation)
        if access is None:
            raise RuntimeError(
                f"No OSS access level configured for operation {operation.value!r}"
            )

        namespace_key = self._resolve_namespace_key(request)

        if access is OssAccessLevel.PUBLIC:
            return Principal(namespace_key=namespace_key)

        api_key = request.headers.get("X-API-Key")
        client = await _validate_api_key(
            api_key,
            request,
            require_admin=access is OssAccessLevel.ADMIN,
        )
        return Principal(
            namespace_key=namespace_key,
            is_admin=client.is_admin,
            caller_id=client.key_id,
        )

    def _resolve_namespace_key(self, request: Request) -> str:
        # V1 ignores the supplied header value because non-binding write
        # endpoints still hardcode the default namespace; serving anything
        # else here would create rows the rest of the API cannot find. The
        # branch is preserved so a future migration can lift the lock.
        del request
        return self._default_namespace_key
