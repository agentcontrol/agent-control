"""Authorizer for deployments that intentionally disable authentication."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ...models import DEFAULT_NAMESPACE_KEY
from ..core import Operation, Principal, RequestAuthorizer


class NoAuthProvider(RequestAuthorizer):
    """Allows every operation and returns the default namespace."""

    def __init__(self, *, default_namespace_key: str = DEFAULT_NAMESPACE_KEY) -> None:
        self._default_namespace_key = default_namespace_key

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        del request, context
        scopes: tuple[str, ...] = (
            (Operation.RUNTIME_USE.value,) if operation is Operation.RUNTIME_TOKEN_EXCHANGE else ()
        )
        return Principal(namespace_key=self._default_namespace_key, scopes=scopes)
