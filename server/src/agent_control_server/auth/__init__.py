"""Unified auth package for Agent Control.

The ``auth`` package has two layers:

- :mod:`auth.core` — the *generic* request-authorization framework.
  Defines :class:`Operation`, :class:`Principal`, the
  :class:`RequestAuthorizer` protocol, and the
  :func:`require_operation` FastAPI dependency factory. No OSS vs
  enterprise assumptions leak in here.
- :mod:`auth.local` — the legacy API-key / admin-key / session-cookie
  check used by OSS deployments. Currently still the only thing gating
  non-management endpoints; it is re-exported from this package so
  callers need only one import path.

Providers plug into the framework; see :mod:`auth.providers.header` for
the OSS default and :mod:`auth.providers.http_upstream` for the
enterprise adapter. Startup selects a provider via
:func:`auth.config.configure_auth_from_env`.

The full vision (incremental rollout): all authenticated endpoints
eventually declare an ``Operation`` and go through ``require_operation``.
Until those follow-ups land, non-management endpoints continue to use
``require_api_key`` / ``require_admin_key`` from :mod:`auth.local`.
"""

from __future__ import annotations

from .core import (
    ContextBuilder,
    Operation,
    Principal,
    RequestAuthorizer,
    get_request_authorizer,
    require_operation,
    set_request_authorizer,
)
from .local import (
    AuthenticatedClient,
    AuthLevel,
    OptionalAPIKey,
    RequireAdminKey,
    RequireAPIKey,
    authenticate_request,
    get_api_key_from_header,
    optional_api_key,
    require_admin_key,
    require_api_key,
)

__all__ = [
    # core framework
    "ContextBuilder",
    "Operation",
    "Principal",
    "RequestAuthorizer",
    "get_request_authorizer",
    "require_operation",
    "set_request_authorizer",
    # legacy OSS check (still used by non-management endpoints)
    "AuthLevel",
    "AuthenticatedClient",
    "OptionalAPIKey",
    "RequireAPIKey",
    "RequireAdminKey",
    "authenticate_request",
    "get_api_key_from_header",
    "optional_api_key",
    "require_admin_key",
    "require_api_key",
]
