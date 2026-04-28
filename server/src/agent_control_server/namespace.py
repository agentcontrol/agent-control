"""Namespace resolution for request-scoped scoping.

In single-namespace deployments, every request resolves to the default
namespace. Multi-namespace deployments override this dependency to derive
the namespace from the authenticated principal (e.g., JWT claim or API key
scope) on the integrating side - no AC code change required.
"""

from __future__ import annotations

from .models import DEFAULT_NAMESPACE_KEY


def get_namespace_key() -> str:
    """Return the namespace_key for the current request.

    Override via FastAPI's ``app.dependency_overrides[get_namespace_key]``
    to plug in deployment-specific namespace resolution. The override may
    declare any FastAPI-resolvable dependency in its signature (the request,
    other dependencies, etc.) and must return a string of at most 255
    characters that is non-empty.

    Example override that reads the namespace from a JWT claim::

        from fastapi import Depends, HTTPException, Request

        async def resolve_namespace_from_jwt(
            request: Request,
            principal: Principal = Depends(authenticate),
        ) -> str:
            namespace = principal.claims.get("tenant")
            if not namespace:
                raise HTTPException(status_code=401, detail="missing tenant")
            return namespace

        app.dependency_overrides[get_namespace_key] = resolve_namespace_from_jwt
    """
    return DEFAULT_NAMESPACE_KEY
