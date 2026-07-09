"""Database API-key lifecycle and per-control authorization coverage."""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_control_models import BatchEventsRequest, ControlExecutionEvent
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from agent_control_server.auth_framework import Operation, set_authorizer
from agent_control_server.auth_framework.config import (
    RuntimeAuthConfig,
    set_runtime_auth_config,
)
from agent_control_server.auth_framework.providers import LocalJwtVerifyProvider
from agent_control_server.auth_framework.runtime_token import verify_runtime_token
from agent_control_server.endpoints.system import SESSION_COOKIE_NAME, decode_session_jwt
from agent_control_server.models import APIKeyCredential

from .utils import VALID_CONTROL_PAYLOAD, canonicalize_control_payload

_RUNTIME_SECRET = "runtime-test-secret-that-is-long-enough"


def _create_user_and_key(
    admin_client: TestClient,
    *,
    role: str = "member",
    user_name: str | None = None,
    key_name: str = "DefenseClaw SDK",
    expires_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    user_response = admin_client.post(
        "/api/v1/admin/access/users",
        json={
            "name": user_name or f"user-{uuid.uuid4().hex[:10]}",
            "role": role,
        },
    )
    assert user_response.status_code == 201, user_response.text
    user = user_response.json()

    body: dict[str, Any] = {"name": key_name}
    if expires_at is not None:
        body["expires_at"] = expires_at.isoformat()
    key_response = admin_client.post(
        f"/api/v1/admin/access/users/{user['id']}/api-keys",
        json=body,
    )
    assert key_response.status_code == 201, key_response.text
    created = key_response.json()
    return user, created["api_key"], created["secret"]


def _db_key_client(app: object, secret: str) -> TestClient:
    return TestClient(app, headers={"X-API-Key": secret})


def _create_control(admin_client: TestClient, suffix: str) -> int:
    payload = canonicalize_control_payload(deepcopy(VALID_CONTROL_PAYLOAD))
    response = admin_client.put(
        "/api/v1/controls",
        json={"name": f"bucket-{suffix}-{uuid.uuid4().hex[:8]}", "data": payload},
    )
    assert response.status_code == 200, response.text
    return int(response.json()["control_id"])


def _register_agent(admin_client: TestClient, agent_name: str) -> None:
    response = admin_client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {
                "agent_name": agent_name,
                "agent_description": "DefenseClaw policy sync",
                "agent_version": "1.0",
            },
            "steps": [],
            "evaluators": [],
        },
    )
    assert response.status_code == 200, response.text


def _grant_controls(admin_client: TestClient, api_key_id: str, control_ids: list[int]) -> None:
    response = admin_client.put(
        f"/api/v1/admin/access/api-keys/{api_key_id}/control-grants",
        json={"control_ids": control_ids},
    )
    assert response.status_code == 200, response.text
    assert response.json()["control_ids"] == sorted(set(control_ids))


def _event(*, agent_name: str, control_id: int, marker: str) -> ControlExecutionEvent:
    return ControlExecutionEvent(
        trace_id=marker * 32,
        span_id=marker * 16,
        agent_name=agent_name,
        control_id=control_id,
        control_name=f"bucket-{control_id}",
        check_stage="pre",
        applies_to="llm_call",
        action="deny",
        matched=True,
        confidence=0.99,
        timestamp=datetime.now(UTC),
        metadata={"blocked_input": {"prompt": f"exact-{marker}-prompt"}},
    )


def test_access_management_is_admin_only_and_secrets_are_one_time(
    app: object,
    admin_client: TestClient,
    non_admin_client: TestClient,
    db_engine,
) -> None:
    denied = non_admin_client.get("/api/v1/admin/access/users")
    assert denied.status_code == 403

    blank_user = admin_client.post(
        "/api/v1/admin/access/users", json={"name": "   ", "role": "member"}
    )
    assert blank_user.status_code == 422

    user, key, secret = _create_user_and_key(admin_client, user_name="  DefenseClaw operator  ")
    assert user["name"] == "DefenseClaw operator"
    assert secret.startswith("ac_")

    listed = admin_client.get(f"/api/v1/admin/access/users/{user['id']}/api-keys")
    assert listed.status_code == 200
    serialized = listed.text
    assert secret not in serialized
    assert "key_hash" not in serialized

    with db_engine.begin() as connection:
        digest = connection.execute(
            select(APIKeyCredential.key_hash).where(APIKeyCredential.id == key["id"])
        ).scalar_one()
    assert digest != secret
    assert len(digest) == 64

    invalid_bool_grant = admin_client.put(
        f"/api/v1/admin/access/api-keys/{key['id']}/control-grants",
        json={"control_ids": [True]},
    )
    assert invalid_bool_grant.status_code == 422

    missing_control = admin_client.put(
        f"/api/v1/admin/access/api-keys/{key['id']}/control-grants",
        json={"control_ids": [999999]},
    )
    assert missing_control.status_code == 422

    # The newly created DB key authenticates even though it is not in env key lists.
    db_client = _db_key_client(app, secret)
    assert db_client.get("/api/v1/evaluators").status_code == 200


def test_database_admin_key_is_unrestricted_and_rejects_bucket_grants(
    app: object,
    admin_client: TestClient,
) -> None:
    control_id = _create_control(admin_client, "admin-unrestricted")
    _, key, secret = _create_user_and_key(admin_client, role="admin")

    grant = admin_client.put(
        f"/api/v1/admin/access/api-keys/{key['id']}/control-grants",
        json={"control_ids": [control_id]},
    )
    assert grant.status_code == 422
    assert "namespace-wide" in grant.text

    database_admin = _db_key_client(app, secret)
    visible = database_admin.get(f"/api/v1/controls/{control_id}")
    assert visible.status_code == 200


def test_scoped_key_sees_only_assigned_controls_policies_bindings_and_counts(
    app: object,
    admin_client: TestClient,
) -> None:
    allowed_id = _create_control(admin_client, "allowed")
    hidden_id = _create_control(admin_client, "hidden")
    agent_name = f"defenseclaw-{uuid.uuid4().hex[:10]}"
    target_only_agent = f"defenseclaw-target-{uuid.uuid4().hex[:8]}"
    _register_agent(admin_client, agent_name)
    _register_agent(admin_client, target_only_agent)

    for control_id in (allowed_id, hidden_id):
        attached = admin_client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
        assert attached.status_code == 200, attached.text

    policy = admin_client.put("/api/v1/policies", json={"name": f"policy-{uuid.uuid4().hex[:8]}"})
    assert policy.status_code == 200
    policy_id = int(policy.json()["policy_id"])
    for control_id in (allowed_id, hidden_id):
        associated = admin_client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
        assert associated.status_code == 200

    binding_ids: dict[int, int] = {}
    for control_id in (allowed_id, hidden_id):
        binding = admin_client.put(
            "/api/v1/control-bindings",
            json={
                "target_type": "deployment",
                "target_id": "defenseclaw-prod",
                "control_id": control_id,
                "enabled": True,
            },
        )
        assert binding.status_code == 200, binding.text
        binding_ids[control_id] = int(binding.json()["binding_id"])

    _, key, secret = _create_user_and_key(admin_client)
    _grant_controls(admin_client, key["id"], [allowed_id])
    scoped = _db_key_client(app, secret)

    controls = scoped.get("/api/v1/controls")
    assert controls.status_code == 200, controls.text
    assert [control["id"] for control in controls.json()["controls"]] == [allowed_id]
    assert scoped.get(f"/api/v1/controls/{allowed_id}").status_code == 200
    assert scoped.get(f"/api/v1/controls/{hidden_id}").status_code == 404
    assert scoped.get(f"/api/v1/controls/{hidden_id}/data").status_code == 404
    assert scoped.get(f"/api/v1/controls/{hidden_id}/versions").status_code == 404

    policy_controls = scoped.get(f"/api/v1/policies/{policy_id}/controls")
    assert policy_controls.status_code == 200
    assert policy_controls.json()["control_ids"] == [allowed_id]

    bindings = scoped.get("/api/v1/control-bindings")
    assert bindings.status_code == 200
    assert [item["control_id"] for item in bindings.json()["bindings"]] == [allowed_id]
    assert scoped.get(f"/api/v1/control-bindings/{binding_ids[hidden_id]}").status_code == 404

    agents = scoped.get("/api/v1/agents")
    assert agents.status_code == 200
    summaries = {item["agent_name"]: item for item in agents.json()["agents"]}
    assert summaries[agent_name]["active_controls_count"] == 1
    # Target-only deployments remain reachable in Monitor even though there
    # is no persisted agent-to-target relation from which to filter inventory.
    assert target_only_agent in summaries

    target_controls = scoped.get(
        f"/api/v1/agents/{target_only_agent}/controls",
        params={"target_type": "deployment", "target_id": "defenseclaw-prod"},
    )
    assert target_controls.status_code == 200
    assert [item["id"] for item in target_controls.json()["controls"]] == [allowed_id]


def test_cookie_and_header_re_resolve_disabled_revoked_and_expired_keys(
    app: object,
    admin_client: TestClient,
    db_engine,
) -> None:
    user, key, secret = _create_user_and_key(admin_client)
    browser = TestClient(app, base_url="http://localhost")
    login = browser.post("/api/login", json={"api_key": secret})
    assert login.status_code == 200
    assert login.json() == {"authenticated": True, "is_admin": False}
    cookie = browser.cookies.get(SESSION_COOKIE_NAME)
    assert cookie is not None
    claims = decode_session_jwt(cookie)
    assert claims is not None
    assert claims["api_key_id"] == key["id"]
    assert claims["user_id"] == user["id"]
    assert "allowed_control_ids" not in claims
    config = browser.get("/api/config")
    assert config.status_code == 200
    assert config.json()["has_active_session"] is True
    assert config.json()["is_admin"] is False

    disabled = admin_client.patch(
        f"/api/v1/admin/access/users/{user['id']}", json={"enabled": False}
    )
    assert disabled.status_code == 200
    assert browser.get("/api/v1/evaluators").status_code == 401
    assert _db_key_client(app, secret).get("/api/v1/evaluators").status_code == 401

    enabled = admin_client.patch(f"/api/v1/admin/access/users/{user['id']}", json={"enabled": True})
    assert enabled.status_code == 200
    first_revoke = admin_client.delete(f"/api/v1/admin/access/api-keys/{key['id']}")
    assert first_revoke.status_code == 204
    listed = admin_client.get(f"/api/v1/admin/access/users/{user['id']}/api-keys").json()[
        "api_keys"
    ][0]
    revoked_at = listed["revoked_at"]
    second_revoke = admin_client.delete(f"/api/v1/admin/access/api-keys/{key['id']}")
    assert second_revoke.status_code == 204
    listed_again = admin_client.get(f"/api/v1/admin/access/users/{user['id']}/api-keys").json()[
        "api_keys"
    ][0]
    assert listed_again["revoked_at"] == revoked_at
    assert _db_key_client(app, secret).get("/api/v1/evaluators").status_code == 401

    _, expiring_key, expiring_secret = _create_user_and_key(
        admin_client,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    with db_engine.begin() as connection:
        connection.execute(
            update(APIKeyCredential)
            .where(APIKeyCredential.id == expiring_key["id"])
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert _db_key_client(app, expiring_secret).get("/api/v1/evaluators").status_code == 401


def test_admin_session_role_survives_refresh(app: object, admin_client: TestClient) -> None:
    # The configured environment admin key remains the bootstrap credential.
    bootstrap_secret = admin_client.headers["X-API-Key"]
    browser = TestClient(app, base_url="http://localhost")
    login = browser.post("/api/login", json={"api_key": bootstrap_secret})
    assert login.status_code == 200
    assert login.json()["is_admin"] is True
    config = browser.get("/api/config")
    assert config.status_code == 200
    assert config.json()["has_active_session"] is True
    assert config.json()["is_admin"] is True

    forged = browser.post(
        "/api/v1/admin/access/users",
        headers={"Origin": "https://attacker.example"},
        json={"name": "forged-admin", "role": "admin"},
    )
    assert forged.status_code == 403

    normalized_same_origin = browser.post(
        "/api/v1/admin/access/users",
        headers={"Origin": "http://localhost:80"},
        json={"name": "normalized-origin-admin", "role": "admin"},
    )
    assert normalized_same_origin.status_code == 201


def test_observability_grants_filter_reads_and_reject_mixed_batch_atomically(
    app: object,
    admin_client: TestClient,
    setup_observability: object,
) -> None:
    _ = setup_observability
    allowed_id = _create_control(admin_client, "event-allowed")
    hidden_id = _create_control(admin_client, "event-hidden")
    _, key, secret = _create_user_and_key(admin_client)
    _grant_controls(admin_client, key["id"], [allowed_id])
    scoped = _db_key_client(app, secret)
    _, second_key, second_secret = _create_user_and_key(admin_client)
    _grant_controls(admin_client, second_key["id"], [allowed_id])
    second_scoped = _db_key_client(app, second_secret)
    agent_name = f"defenseclaw-events-{uuid.uuid4().hex[:8]}"

    allowed_event = _event(agent_name=agent_name, control_id=allowed_id, marker="a")
    allowed_request = BatchEventsRequest(events=[allowed_event])
    accepted = scoped.post(
        "/api/v1/observability/events",
        json=allowed_request.model_dump(mode="json"),
    )
    assert accepted.status_code == 202, accepted.text

    second_request = BatchEventsRequest(
        events=[_event(agent_name=agent_name, control_id=allowed_id, marker="e")]
    )
    second_accepted = second_scoped.post(
        "/api/v1/observability/events",
        json=second_request.model_dump(mode="json"),
    )
    assert second_accepted.status_code == 202, second_accepted.text

    mixed_request = BatchEventsRequest(
        events=[
            _event(agent_name=agent_name, control_id=allowed_id, marker="b"),
            _event(agent_name=agent_name, control_id=hidden_id, marker="c"),
        ]
    )
    rejected = scoped.post(
        "/api/v1/observability/events",
        json=mixed_request.model_dump(mode="json"),
    )
    assert rejected.status_code == 403

    hidden_request = BatchEventsRequest(
        events=[_event(agent_name=agent_name, control_id=hidden_id, marker="d")]
    )
    assert (
        admin_client.post(
            "/api/v1/observability/events",
            json=hidden_request.model_dump(mode="json"),
        ).status_code
        == 202
    )

    scoped_query = scoped.post(
        "/api/v1/observability/events/query", json={"agent_name": agent_name}
    )
    assert scoped_query.status_code == 200
    assert scoped_query.json()["total"] == 1
    assert scoped_query.json()["events"][0]["control_id"] == allowed_id
    assert "access_user_id" not in scoped_query.json()["events"][0]
    assert (
        scoped_query.json()["events"][0]["metadata"]["blocked_input"]["prompt"] == "exact-a-prompt"
    )

    second_query = second_scoped.post(
        "/api/v1/observability/events/query", json={"agent_name": agent_name}
    )
    assert second_query.status_code == 200
    assert second_query.json()["total"] == 1
    assert (
        second_query.json()["events"][0]["metadata"]["blocked_input"]["prompt"] == "exact-e-prompt"
    )
    first_stats = scoped.get(
        "/api/v1/observability/stats",
        params={"agent_name": agent_name, "time_range": "1h"},
    )
    second_stats = second_scoped.get(
        "/api/v1/observability/stats",
        params={"agent_name": agent_name, "time_range": "1h"},
    )
    assert first_stats.status_code == 200
    assert second_stats.status_code == 200
    assert first_stats.json()["totals"]["execution_count"] == 1
    assert second_stats.json()["totals"]["execution_count"] == 1

    attempted_widen = scoped.post(
        "/api/v1/observability/events/query",
        json={"agent_name": agent_name, "control_ids": [hidden_id]},
    )
    assert attempted_widen.status_code == 200
    assert attempted_widen.json()["total"] == 0

    admin_query = admin_client.post(
        "/api/v1/observability/events/query", json={"agent_name": agent_name}
    )
    assert admin_query.status_code == 200
    # The rejected mixed batch wrote neither its allowed nor hidden event.
    assert admin_query.json()["total"] == 3


def test_soft_delete_revokes_member_grant_and_blocks_new_events(
    app: object,
    admin_client: TestClient,
    setup_observability: object,
) -> None:
    _ = setup_observability
    control_id = _create_control(admin_client, "deleted-event")
    _, key, secret = _create_user_and_key(admin_client)
    _grant_controls(admin_client, key["id"], [control_id])
    member = _db_key_client(app, secret)
    agent_name = f"defenseclaw-deleted-{uuid.uuid4().hex[:8]}"
    request = BatchEventsRequest(
        events=[_event(agent_name=agent_name, control_id=control_id, marker="7")]
    )

    accepted = member.post("/api/v1/observability/events", json=request.model_dump(mode="json"))
    assert accepted.status_code == 202

    deleted = admin_client.delete(f"/api/v1/controls/{control_id}")
    assert deleted.status_code == 200, deleted.text

    member_history = member.post(
        "/api/v1/observability/events/query", json={"agent_name": agent_name}
    )
    assert member_history.status_code == 200
    assert member_history.json()["total"] == 0
    assert member.get(f"/api/v1/controls/{control_id}/versions").status_code == 404

    rejected = member.post("/api/v1/observability/events", json=request.model_dump(mode="json"))
    assert rejected.status_code in {403, 404}

    admin_history = admin_client.post(
        "/api/v1/observability/events/query", json={"agent_name": agent_name}
    )
    assert admin_history.status_code == 200
    assert admin_history.json()["total"] == 1


def test_scoped_runtime_token_cannot_evaluate_unassigned_target_bucket(
    app: object,
    admin_client: TestClient,
    setup_observability: object,
) -> None:
    _ = setup_observability
    allowed_id = _create_control(admin_client, "runtime-allowed")
    hidden_id = _create_control(admin_client, "runtime-hidden")
    agent_name = f"defenseclaw-runtime-{uuid.uuid4().hex[:8]}"
    _register_agent(admin_client, agent_name)
    for control_id in (allowed_id, hidden_id):
        binding = admin_client.put(
            "/api/v1/control-bindings",
            json={
                "target_type": "deployment",
                "target_id": "defenseclaw-prod",
                "control_id": control_id,
                "enabled": True,
            },
        )
        assert binding.status_code == 200

    _, key, secret = _create_user_and_key(admin_client)
    _grant_controls(admin_client, key["id"], [allowed_id])
    scoped = _db_key_client(app, secret)
    _, second_key, second_secret = _create_user_and_key(admin_client)
    _grant_controls(admin_client, second_key["id"], [allowed_id])
    second_scoped = _db_key_client(app, second_secret)

    set_runtime_auth_config(RuntimeAuthConfig(secret=_RUNTIME_SECRET, ttl_seconds=300))
    try:
        exchange = scoped.post(
            "/api/v1/auth/runtime-token-exchange",
            json={
                "target_type": "deployment",
                "target_id": "defenseclaw-prod",
            },
        )
        assert exchange.status_code == 200, exchange.text
        token = exchange.json()["token"]
        second_exchange = second_scoped.post(
            "/api/v1/auth/runtime-token-exchange",
            json={
                "target_type": "deployment",
                "target_id": "defenseclaw-prod",
            },
        )
        assert second_exchange.status_code == 200, second_exchange.text
        second_token = second_exchange.json()["token"]
        claims = verify_runtime_token(token, _RUNTIME_SECRET)
        assert claims.allowed_control_ids == frozenset({allowed_id})
        assert claims.api_key_id == key["id"]
        set_authorizer(
            LocalJwtVerifyProvider(secret=_RUNTIME_SECRET),
            operation=Operation.RUNTIME_USE,
        )
        set_authorizer(
            LocalJwtVerifyProvider(secret=_RUNTIME_SECRET),
            operation=Operation.OBSERVABILITY_WRITE,
        )

        runtime = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        evaluated = runtime.post(
            "/api/v1/evaluation",
            json={
                "agent_name": agent_name,
                "step": {
                    "type": "llm",
                    "name": "prompt",
                    "input": "x marks the spot",
                    "context": {},
                },
                "stage": "pre",
                "target_type": "deployment",
                "target_id": "defenseclaw-prod",
            },
        )
        assert evaluated.status_code == 200, evaluated.text
        matched_ids = {match["control_id"] for match in (evaluated.json().get("matches") or [])}
        assert matched_ids == {allowed_id}
        assert hidden_id not in matched_ids

        runtime_event = BatchEventsRequest(
            events=[_event(agent_name=agent_name, control_id=allowed_id, marker="f")]
        )
        second_runtime_event = BatchEventsRequest(
            events=[_event(agent_name=agent_name, control_id=allowed_id, marker="9")]
        )
        first_ingest = runtime.post(
            "/api/v1/observability/events",
            json=runtime_event.model_dump(mode="json"),
        )
        second_runtime = TestClient(app, headers={"Authorization": f"Bearer {second_token}"})
        second_ingest = second_runtime.post(
            "/api/v1/observability/events",
            json=second_runtime_event.model_dump(mode="json"),
        )
        assert first_ingest.status_code == 202, first_ingest.text
        assert second_ingest.status_code == 202, second_ingest.text

        first_history = scoped.post(
            "/api/v1/observability/events/query", json={"agent_name": agent_name}
        )
        second_history = second_scoped.post(
            "/api/v1/observability/events/query", json={"agent_name": agent_name}
        )
        assert first_history.json()["total"] == 1
        assert second_history.json()["total"] == 1
        assert (
            first_history.json()["events"][0]["metadata"]["blocked_input"]["prompt"]
            == "exact-f-prompt"
        )
        assert (
            second_history.json()["events"][0]["metadata"]["blocked_input"]["prompt"]
            == "exact-9-prompt"
        )
        assert "access_user_id" not in first_history.json()["events"][0]
        admin_history = admin_client.post(
            "/api/v1/observability/events/query", json={"agent_name": agent_name}
        )
        assert admin_history.json()["total"] == 2
    finally:
        set_runtime_auth_config(None)
