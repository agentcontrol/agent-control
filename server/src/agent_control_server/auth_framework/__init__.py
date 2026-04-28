"""Pluggable request-auth framework.

Endpoints declare an :class:`Operation` they need; an installed
:class:`RequestAuthorizer` decides whether the request is allowed and
returns the resulting :class:`Principal`. Two providers ship in-tree:
:class:`HeaderAuthProvider` (OSS default) and
:class:`HttpUpstreamAuthProvider` (delegates to an upstream HTTP
service).
"""

from .core import (
    Operation,
    Principal,
    RequestAuthorizer,
    get_authorizer,
    require_operation,
    set_authorizer,
)

__all__ = [
    "Operation",
    "Principal",
    "RequestAuthorizer",
    "get_authorizer",
    "require_operation",
    "set_authorizer",
]
