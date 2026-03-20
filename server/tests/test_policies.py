import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from agent_control_server.db import get_async_db
from agent_control_server.models import Control, Policy

from .utils import VALID_CONTROL_PAYLOAD


def _create_policy(client: TestClient) -> int:
    name = f"pol-{uuid.uuid4()}"
    r = client.put("/api/v1/policies", json={"name": name})
    assert r.status_code == 200
    return r.json()["policy_id"]


def _create_control(client: TestClient) -> int:
    name = f"ctrl-{uuid.uuid4()}"
    r = client.put("/api/v1/controls", json={"name": name, "data": VALID_CONTROL_PAYLOAD})
    assert r.status_code == 200
    return r.json()["control_id"]


def test_create_policy_and_duplicate_name(client: TestClient) -> None:
    # Given: a policy name
    name = f"pol-{uuid.uuid4()}"
    # When: creating the policy
    r1 = client.put("/api/v1/policies", json={"name": name})
    # Then: the policy is created with an id
    assert r1.status_code == 200
    assert isinstance(r1.json()["policy_id"], int)

    # When: creating the same policy name again
    r2 = client.put("/api/v1/policies", json={"name": name})
    # Then: a conflict is returned
    assert r2.status_code == 409


def test_policy_add_control_and_list(client: TestClient) -> None:
    # Given: a policy and a control
    policy_id = _create_policy(client)
    control_id = _create_control(client)

    # When: associating the control to the policy
    r = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    # Then: association succeeds
    assert r.status_code == 200
    assert r.json()["success"] is True

    # When: listing policy controls
    l = client.get(f"/api/v1/policies/{policy_id}/controls")
    # Then: the control id is included
    assert l.status_code == 200
    assert control_id in l.json()["control_ids"]


def test_policy_add_control_idempotent(client: TestClient) -> None:
    # Given: a policy with a control already associated
    policy_id = _create_policy(client)
    control_id = _create_control(client)
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")

    # When: adding the same control again
    r = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    # Then: the request is still successful (idempotent)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # Then: listing still shows it once (set semantics by ids)
    l = client.get(f"/api/v1/policies/{policy_id}/controls")
    assert l.status_code == 200
    ids = l.json()["control_ids"]
    assert ids.count(control_id) == 1


def test_policy_remove_control(client: TestClient) -> None:
    # Given: a policy with an associated control
    policy_id = _create_policy(client)
    control_id = _create_control(client)
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")

    # When: removing the association
    d = client.delete(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    # Then: removal succeeds
    assert d.status_code == 200
    assert d.json()["success"] is True

    # When: listing controls
    l = client.get(f"/api/v1/policies/{policy_id}/controls")
    # Then: the control is not present
    assert l.status_code == 200
    assert control_id not in l.json()["control_ids"]


def test_policy_remove_control_idempotent_when_not_associated(client: TestClient) -> None:
    # Given: a policy and a control that are not associated
    policy_id = _create_policy(client)
    control_id = _create_control(client)

    # When: removing the association anyway
    resp = client.delete(f"/api/v1/policies/{policy_id}/controls/{control_id}")

    # Then: success is returned (idempotent)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Then: the control list remains empty
    list_resp = client.get(f"/api/v1/policies/{policy_id}/controls")
    assert list_resp.status_code == 200
    assert list_resp.json()["control_ids"] == []


def test_list_policy_controls_empty_for_new_policy(client: TestClient) -> None:
    # Given: a newly created policy with no controls
    policy_id = _create_policy(client)

    # When: listing policy controls
    resp = client.get(f"/api/v1/policies/{policy_id}/controls")

    # Then: an empty list is returned
    assert resp.status_code == 200
    assert resp.json()["control_ids"] == []


def test_policy_assoc_404s(client: TestClient) -> None:
    # Given: existing policy and control ids
    policy_id = _create_policy(client)
    control_id = _create_control(client)

    # When: the policy is missing
    r1 = client.post(f"/api/v1/policies/999999/controls/{control_id}")
    # Then: not found is returned
    assert r1.status_code == 404

    # When: the control is missing
    r2 = client.post(f"/api/v1/policies/{policy_id}/controls/999999")
    # Then: not found is returned
    assert r2.status_code == 404

    # When: listing controls for a missing policy
    r3 = client.get("/api/v1/policies/999999/controls")
    # Then: not found is returned
    assert r3.status_code == 404

    # When: removing an association with missing policy and control
    r4 = client.delete("/api/v1/policies/999999/controls/999999")
    # Then: not found is returned
    assert r4.status_code == 404


def test_policy_remove_control_missing_control_returns_404(client: TestClient) -> None:
    # Given: an existing policy and a missing control id
    policy_id = _create_policy(client)
    missing_control_id = 999999

    # When: removing a control that does not exist
    resp = client.delete(f"/api/v1/policies/{policy_id}/controls/{missing_control_id}")

    # Then: control not found is returned
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_policy_add_control_db_error_returns_500(
    app: FastAPI, client: TestClient
) -> None:
    # Given: a policy and control resolved from the database
    policy_id = 123
    control_id = 456
    policy = Policy(id=policy_id, name="policy-error")
    control = Control(id=control_id, name="control-error")

    # And: a database session that fails on commit
    policy_result = MagicMock()
    policy_result.scalars.return_value.first.return_value = policy
    control_result = MagicMock()
    control_result.scalars.return_value.first.return_value = control

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(
            side_effect=[policy_result, control_result, MagicMock()]
        )
        mock_session.commit.side_effect = Exception("db error")
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: associating the control and the commit fails
    app.dependency_overrides[get_async_db] = mock_db
    try:
        resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    finally:
        app.dependency_overrides.clear()

    # Then: a database error is returned
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_policy_remove_control_db_error_returns_500(
    app: FastAPI, client: TestClient
) -> None:
    # Given: a policy and control resolved from the database
    policy_id = 321
    control_id = 654
    policy = Policy(id=policy_id, name="policy-remove-error")
    control = Control(id=control_id, name="control-remove-error")

    policy_result = MagicMock()
    policy_result.scalars.return_value.first.return_value = policy
    control_result = MagicMock()
    control_result.scalars.return_value.first.return_value = control

    async def mock_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock(
            side_effect=[policy_result, control_result, MagicMock()]
        )
        mock_session.delete = AsyncMock()
        mock_session.commit.side_effect = Exception("db error")
        mock_session.rollback = AsyncMock()
        yield mock_session

    # When: removing the association and the commit fails
    app.dependency_overrides[get_async_db] = mock_db
    try:
        resp = client.delete(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    finally:
        app.dependency_overrides.clear()

    # Then: a database error is returned
    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"
