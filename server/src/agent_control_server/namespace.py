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
    to plug in deployment-specific namespace resolution.
    """
    return DEFAULT_NAMESPACE_KEY
