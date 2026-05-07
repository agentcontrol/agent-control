"""Pluggable request-auth framework.

Endpoints declare an :class:`Operation` they need; an installed
:class:`RequestAuthorizer` decides whether the request is allowed and
returns the resulting :class:`Principal`. Providers ship in-tree for
disabled auth, local credential checks, upstream HTTP authorization,
and local runtime-JWT verification.
"""

from .core import (
    Operation,
    Principal,
    RequestAuthorizer,
    clear_authorizers,
    get_authorizer,
    require_operation,
    set_authorizer,
)

__all__ = [
    "Operation",
    "Principal",
    "RequestAuthorizer",
    "clear_authorizers",
    "get_authorizer",
    "require_operation",
    "set_authorizer",
]
