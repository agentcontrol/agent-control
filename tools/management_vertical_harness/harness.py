#!/usr/bin/env python3
"""End-to-end management-vertical harness.

Walks the full management flow against a locally-running stack of
agent-control, Galileo api, and Galileo authz. Intended as reproducible
validation for the management-vertical work (see PR #195 / sc-63146).

Required env vars:

    HARNESS_AC_URL                Agent Control base URL
                                  (default: http://localhost:8000)
    HARNESS_GALILEO_USER_TOKEN    user's Galileo bearer token
                                  (owner on HARNESS_LOG_STREAM_ID's project)
    HARNESS_LOG_STREAM_ID         UUID of a log_stream (Run) to bind to
    HARNESS_CONTROL_ID            integer ID of a pre-seeded control to attach

Optional env vars (deny cases; skipped when unset):

    HARNESS_CROSS_ORG_USER_TOKEN     user in a different org
    HARNESS_CROSS_PROJECT_USER_TOKEN user in same org, different project
    HARNESS_VIEWER_TOKEN             user with viewer/editor role (no update_control_bindings)

Exits non-zero on the first failed assertion.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

DEFAULT_AC_URL = "http://localhost:8000"
TARGET_TYPE = "log_stream"


def _env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"error: missing required env var {name}", file=sys.stderr)
        sys.exit(2)
    return value


def _env_optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _expect(got: int, wanted: int, label: str, body: Any = None) -> None:
    if got != wanted:
        print(f"FAIL [{label}] expected HTTP {wanted}, got {got}", file=sys.stderr)
        if body is not None:
            print(f"  body: {body}", file=sys.stderr)
        sys.exit(1)
    print(f"  ok  [{label}] HTTP {got}")


def main() -> None:
    ac_url = os.environ.get("HARNESS_AC_URL", DEFAULT_AC_URL).rstrip("/")
    user_token = _env_required("HARNESS_GALILEO_USER_TOKEN")
    log_stream_id = _env_required("HARNESS_LOG_STREAM_ID")
    control_id = int(_env_required("HARNESS_CONTROL_ID"))

    cross_org_token = _env_optional("HARNESS_CROSS_ORG_USER_TOKEN")
    cross_project_token = _env_optional("HARNESS_CROSS_PROJECT_USER_TOKEN")
    viewer_token = _env_optional("HARNESS_VIEWER_TOKEN")

    print(f"Agent Control: {ac_url}")
    print(f"log_stream_id: {log_stream_id}")
    print(f"control_id:    {control_id}")

    client = httpx.Client(timeout=10.0)

    # -----------------------------------------------------------------
    # Happy path (plan §9 steps 2-7)
    # -----------------------------------------------------------------
    print("\n== Happy path ==")

    # 2. List org-level controls
    r = client.get(f"{ac_url}/api/v1/controls", headers=_bearer(user_token))
    _expect(r.status_code, 200, "GET /controls", r.text)
    payload = r.json()
    names = [c["name"] for c in payload.get("controls", [])]
    if not any(c["id"] == control_id for c in payload.get("controls", [])):
        print(
            f"FAIL [GET /controls] expected control_id={control_id} in catalog, got {names}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  ok  [GET /controls] sees {len(names)} controls including the seed")

    # 3. Read bindings for the log_stream (starts empty)
    bindings_url = f"{ac_url}/api/v1/targets/{TARGET_TYPE}/{log_stream_id}/controls"
    r = client.get(bindings_url, headers=_bearer(user_token))
    _expect(r.status_code, 200, "GET bindings (initial)", r.text)
    initial = r.json().get("controls", [])
    if any(b["control_id"] == control_id and b["enabled"] for b in initial):
        print(
            f"FAIL [GET bindings (initial)] control {control_id} is already attached+enabled; "
            "pre-seeded state is unexpected. Detach manually before running the harness.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  ok  [GET bindings (initial)] {len(initial)} existing bindings, target binding absent")

    # 4. Attach (PUT)
    attach_url = f"{ac_url}/api/v1/targets/{TARGET_TYPE}/{log_stream_id}/controls/{control_id}"
    r = client.put(attach_url, headers=_bearer(user_token), json={"enabled": True})
    _expect(r.status_code, 200, "PUT attach (enabled=true)", r.text)
    body = r.json()
    if body.get("control_id") != control_id or body.get("enabled") is not True:
        print(f"FAIL [PUT attach] unexpected response: {body}", file=sys.stderr)
        sys.exit(1)
    print(f"  ok  [PUT attach] control_id={control_id} enabled=true")

    # 5. Re-read bindings; attachment should be present
    r = client.get(bindings_url, headers=_bearer(user_token))
    _expect(r.status_code, 200, "GET bindings (after attach)", r.text)
    bindings = r.json().get("controls", [])
    if not any(b["control_id"] == control_id and b["enabled"] for b in bindings):
        print(
            f"FAIL [GET bindings (after attach)] control {control_id} missing or not enabled; got {bindings}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  ok  [GET bindings (after attach)] attachment present and enabled")

    # 6. Detach (DELETE)
    r = client.delete(attach_url, headers=_bearer(user_token))
    _expect(r.status_code, 204, "DELETE detach", r.text)

    # 7. Re-read bindings; attachment should be gone
    r = client.get(bindings_url, headers=_bearer(user_token))
    _expect(r.status_code, 200, "GET bindings (after detach)", r.text)
    bindings = r.json().get("controls", [])
    if any(b["control_id"] == control_id for b in bindings):
        print(
            f"FAIL [GET bindings (after detach)] control {control_id} still present",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"  ok  [GET bindings (after detach)] attachment removed")

    # -----------------------------------------------------------------
    # Deny cases (plan §9 step 7) — each skipped when its token is unset
    # -----------------------------------------------------------------
    print("\n== Deny cases ==")

    if cross_org_token is not None:
        r = client.put(
            attach_url,
            headers=_bearer(cross_org_token),
            json={"enabled": True},
        )
        _expect(r.status_code, 404, "cross-org: PUT attach should 404", r.text)
    else:
        print("  skip [cross-org] HARNESS_CROSS_ORG_USER_TOKEN not set")

    if cross_project_token is not None:
        r = client.put(
            attach_url,
            headers=_bearer(cross_project_token),
            json={"enabled": True},
        )
        _expect(r.status_code, 404, "cross-project: PUT attach should 404", r.text)
    else:
        print("  skip [cross-project] HARNESS_CROSS_PROJECT_USER_TOKEN not set")

    if viewer_token is not None:
        r = client.put(
            attach_url,
            headers=_bearer(viewer_token),
            json={"enabled": True},
        )
        _expect(r.status_code, 403, "insufficient_permissions: PUT attach should 403", r.text)
    else:
        print("  skip [insufficient_permissions] HARNESS_VIEWER_TOKEN not set")

    # Fail-closed (upstream-api unreachable -> AC 503) is not exercised
    # here because it's a property of the upstream provider, not of the
    # end-to-end request flow; ``tests/test_auth_framework.py`` covers
    # it as a unit test against ``HttpUpstreamAuthProvider`` directly.

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
