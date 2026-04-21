"""Management-auth seam for Agent Control.

Agent Control delegates management authentication and authorization to a
pluggable provider. The core of AC speaks generic operation names
(``controls.read`` etc.); providers map those operations onto whatever
upstream auth system a deployment uses.

Two providers ship in-tree:

- ``providers/header.py`` — OSS / single-tenant default. Trusts an
  ``X-Tenant-Id`` header, does no real authz. Keeps OSS self-hosted use
  working without any auth infrastructure.
- ``providers/http_upstream.py`` — enterprise-style upstream HTTP adapter.
  Forwards the caller's credential to a configured upstream URL and uses
  the upstream's allow/deny decision. The upstream endpoint and shape are
  configurable; no upstream-specific nouns leak into AC core.

Select the active provider via ``AGENT_CONTROL_MANAGEMENT_AUTH_MODE``.
"""

from __future__ import annotations

from .base import (
    ManagementAuthorizer,
    ManagementOperation,
    ManagementPrincipal,
    get_management_authorizer,
    require_management_auth,
    set_management_authorizer,
)

__all__ = [
    "ManagementAuthorizer",
    "ManagementOperation",
    "ManagementPrincipal",
    "get_management_authorizer",
    "require_management_auth",
    "set_management_authorizer",
]
