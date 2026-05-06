"""HTTP-level coverage for the auth seam on ``/controls`` and
``/control-templates``.

These tests exercise the wiring of ``require_operation`` on each route
through the default ``HeaderAuthProvider``: read operations require any
valid credential (``CONTROLS_READ`` -> ``AUTHENTICATED``), write
operations require an admin credential
(``CONTROLS_CREATE`` / ``CONTROLS_UPDATE`` / ``CONTROLS_DELETE`` ->
``ADMIN``), and ``GET /controls/schema`` is intentionally outside the
framework so it stays publicly reachable.

The provider primitives themselves are exercised in
``tests/test_auth_framework.py``; this file focuses on each endpoint
calling the right ``Operation`` so a future change to the operation
mapping is caught at the route level.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from agent_control_server.config import auth_settings

from .utils import VALID_CONTROL_PAYLOAD


_CONTROLS_URL = "/api/v1/controls"
_TEMPLATES_URL = "/api/v1/control-templates"


def _create_control(client: TestClient, name: str | None = None) -> int:
    payload = {
        "name": name or f"control-{uuid.uuid4().hex[:12]}",
        "data": VALID_CONTROL_PAYLOAD,
    }
    resp = client.put(_CONTROLS_URL, json=payload)
    assert resp.status_code == 200, resp.text
    return int(resp.json()["control_id"])


# ---------------------------------------------------------------------------
# /controls/schema is intentionally public meta — no require_operation.
# ---------------------------------------------------------------------------


def test_schema_endpoint_reachable_without_credentials(
    unauthenticated_client: TestClient,
) -> None:
    # Given: a client that never sends an API key
    # When: the schema endpoint is fetched
    resp = unauthenticated_client.get(f"{_CONTROLS_URL}/schema")

    # Then: the canonical ControlDefinition schema is returned
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "schema" in body
    assert isinstance(body["schema"], dict)


def test_schema_endpoint_reachable_with_admin_key(client: TestClient) -> None:
    # Given: an admin client
    # When: the schema endpoint is fetched
    resp = client.get(f"{_CONTROLS_URL}/schema")

    # Then: the schema is returned (header is ignored, route is public)
    assert resp.status_code == 200, resp.text


def test_schema_endpoint_reachable_with_non_admin_key(
    non_admin_client: TestClient,
) -> None:
    # Given: a non-admin client
    # When: the schema endpoint is fetched
    resp = non_admin_client.get(f"{_CONTROLS_URL}/schema")

    # Then: the schema is returned
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# CONTROLS_READ operations: AUTHENTICATED suffices.
# ---------------------------------------------------------------------------


def test_non_admin_can_list_controls(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control
    _create_control(client)

    # When: a non-admin lists controls
    resp = non_admin_client.get(_CONTROLS_URL)

    # Then: the list is returned
    assert resp.status_code == 200, resp.text


def test_non_admin_can_get_control(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control
    control_id = _create_control(client)

    # When: a non-admin reads it
    resp = non_admin_client.get(f"{_CONTROLS_URL}/{control_id}")

    # Then: the control is returned
    assert resp.status_code == 200, resp.text


def test_non_admin_can_get_control_data(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control
    control_id = _create_control(client)

    # When: a non-admin reads its data
    resp = non_admin_client.get(f"{_CONTROLS_URL}/{control_id}/data")

    # Then: the data is returned
    assert resp.status_code == 200, resp.text


def test_non_admin_can_list_versions(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control with at least one version (creation)
    control_id = _create_control(client)

    # When: a non-admin lists versions
    resp = non_admin_client.get(f"{_CONTROLS_URL}/{control_id}/versions")

    # Then: the version list is returned
    assert resp.status_code == 200, resp.text


def test_non_admin_can_get_specific_version(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control (version 1 = "created")
    control_id = _create_control(client)

    # When: a non-admin reads version 1
    resp = non_admin_client.get(f"{_CONTROLS_URL}/{control_id}/versions/1")

    # Then: the version snapshot is returned
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# CONTROLS_CREATE / UPDATE / DELETE: ADMIN required.
# ---------------------------------------------------------------------------


def test_non_admin_cannot_create_control(non_admin_client: TestClient) -> None:
    # When: a non-admin attempts to create
    resp = non_admin_client.put(
        _CONTROLS_URL,
        json={
            "name": f"control-{uuid.uuid4().hex[:12]}",
            "data": VALID_CONTROL_PAYLOAD,
        },
    )

    # Then: the request is forbidden by the auth seam
    assert resp.status_code == 403, resp.text


def test_non_admin_cannot_set_control_data(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control
    control_id = _create_control(client)

    # When: a non-admin attempts to replace its data
    resp = non_admin_client.put(
        f"{_CONTROLS_URL}/{control_id}/data",
        json={"data": VALID_CONTROL_PAYLOAD},
    )

    # Then: the request is forbidden
    assert resp.status_code == 403, resp.text


def test_non_admin_cannot_patch_control(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control
    control_id = _create_control(client)

    # When: a non-admin attempts to rename it
    resp = non_admin_client.patch(
        f"{_CONTROLS_URL}/{control_id}",
        json={"name": "renamed"},
    )

    # Then: the request is forbidden
    assert resp.status_code == 403, resp.text


def test_non_admin_cannot_delete_control(
    non_admin_client: TestClient, client: TestClient
) -> None:
    # Given: an existing control
    control_id = _create_control(client)

    # When: a non-admin attempts to delete it
    resp = non_admin_client.delete(f"{_CONTROLS_URL}/{control_id}")

    # Then: the request is forbidden
    assert resp.status_code == 403, resp.text


def test_non_admin_cannot_validate_control_data(
    non_admin_client: TestClient,
) -> None:
    """``/controls/validate`` is wired to ``CONTROLS_CREATE`` rather than
    ``CONTROLS_READ`` because validation exercises the create / update
    materialization path; a caller who cannot create has no use for the
    result. This pins that decision so it can't drift to ``READ``
    accidentally.
    """
    # When: a non-admin attempts to validate a draft payload
    resp = non_admin_client.post(
        f"{_CONTROLS_URL}/validate",
        json={"data": VALID_CONTROL_PAYLOAD},
    )

    # Then: validation is admin-only
    assert resp.status_code == 403, resp.text


def test_non_admin_cannot_render_template(non_admin_client: TestClient) -> None:
    """``/control-templates/render`` is wired to ``CONTROLS_CREATE`` for
    the same reason as ``/validate``: rendering is part of the authoring
    flow. The 422 path is not exercised here — only the auth gate is
    asserted, so the request shape need not validate.
    """
    # When: a non-admin attempts to render a template
    resp = non_admin_client.post(
        f"{_TEMPLATES_URL}/render",
        json={"template": {}, "template_values": {}},
    )

    # Then: rendering is admin-only — the auth gate fires before body
    # validation reaches the materialization path
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Unauthenticated requests are rejected on every framework-protected route.
# ---------------------------------------------------------------------------


def test_unauthenticated_cannot_list_controls(
    unauthenticated_client: TestClient,
) -> None:
    # When: a client without credentials lists controls
    resp = unauthenticated_client.get(_CONTROLS_URL)

    # Then: the request is rejected
    assert resp.status_code == 401, resp.text


def test_unauthenticated_cannot_create_control(
    unauthenticated_client: TestClient,
) -> None:
    # When: a client without credentials attempts to create
    resp = unauthenticated_client.put(
        _CONTROLS_URL,
        json={
            "name": f"control-{uuid.uuid4().hex[:12]}",
            "data": VALID_CONTROL_PAYLOAD,
        },
    )

    # Then: the request is rejected
    assert resp.status_code == 401, resp.text


def test_unauthenticated_cannot_validate(
    unauthenticated_client: TestClient,
) -> None:
    # When: a client without credentials attempts to validate
    resp = unauthenticated_client.post(
        f"{_CONTROLS_URL}/validate",
        json={"data": VALID_CONTROL_PAYLOAD},
    )

    # Then: the request is rejected
    assert resp.status_code == 401, resp.text


def test_unauthenticated_cannot_render_template(
    unauthenticated_client: TestClient,
) -> None:
    # When: a client without credentials attempts to render
    resp = unauthenticated_client.post(
        f"{_TEMPLATES_URL}/render",
        json={"template": {}, "template_values": {}},
    )

    # Then: the request is rejected
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# No-auth deployment mode: api_key_enabled=False bypasses every gate.
# ---------------------------------------------------------------------------


def test_no_auth_mode_allows_writes_without_credentials(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``api_key_enabled`` is False, the ``HeaderAuthProvider``
    short-circuits to a non-admin ``Principal`` for every operation,
    including admin-level writes. This pins the "no auth" deployment
    path so a future refactor can't silently start enforcing.
    """
    # Given: api_key_enabled is False (single-tenant OSS dev mode)
    monkeypatch.setattr(auth_settings, "api_key_enabled", False)

    # When: an unauthenticated client creates a control
    resp = unauthenticated_client.put(
        _CONTROLS_URL,
        json={
            "name": f"control-{uuid.uuid4().hex[:12]}",
            "data": VALID_CONTROL_PAYLOAD,
        },
    )

    # Then: the create succeeds because auth is disabled at the provider
    assert resp.status_code == 200, resp.text
    assert "control_id" in resp.json()


# ---------------------------------------------------------------------------
# Project-scoped API key deny — pending header forwarding follow-up.
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "Requires the upstream auth provider to forward an additional "
        "configurable credential header. The default forward set is "
        "fixed to (X-API-Key, Authorization, Cookie); deployments that "
        "use a different credential header can't surface a "
        "project-scoped credential to upstream until that becomes "
        "configurable. Re-enable when the follow-up PR adds an "
        "operator-configurable extra forward list."
    )
)
def test_project_scoped_credential_denied_on_org_scoped_controls() -> None:
    """Stub for the deny-test promised by the upstream provider's
    response contract: a project-scoped credential calling an
    org-scoped operation (``controls.*``) should resolve to a 403 from
    the upstream. The end-to-end path is unreachable today because the
    provider's credential-forward list is not configurable; tracked as
    the next follow-up after this PR.
    """
    pytest.fail("test stub — see skip reason")
