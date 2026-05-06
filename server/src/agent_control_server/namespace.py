"""Namespace resolution for request-scoped scoping.

V1 always resolves to the default namespace. The function exists as a
single seam so a future change can switch every namespace-scoped
endpoint to a real per-request resolver without touching each call
site. Overriding the dependency in V1 is not supported: only this
binding/evaluation layer reads it; controls, agents, and policies still
write under the default namespace, so an override here would create
inconsistent rows. Future work will thread a single resolver through
every write path together.
"""

from __future__ import annotations

from .models import DEFAULT_NAMESPACE_KEY


def get_namespace_key() -> str:
    """Return the namespace_key for the current request.

    V1 returns ``DEFAULT_NAMESPACE_KEY`` unconditionally.
    """
    return DEFAULT_NAMESPACE_KEY
