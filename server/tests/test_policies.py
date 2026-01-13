import uuid

from fastapi.testclient import TestClient


def _create_policy(client: TestClient) -> int:
    name = f"pol-{uuid.uuid4()}"
    r = client.put("/api/v1/policies", json={"name": name})
    assert r.status_code == 200
    return r.json()["policy_id"]


def _create_control(client: TestClient) -> int:
    name = f"ctrl-{uuid.uuid4()}"
    r = client.put("/api/v1/controls", json={"name": name})
    assert r.status_code == 200
    return r.json()["control_id"]


def test_create_policy_and_duplicate_name(client: TestClient) -> None:
    # Given: a policy name
    name = f"pol-{uuid.uuid4()}"
    # When: creating policy
    r1 = client.put("/api/v1/policies", json={"name": name})
    # Then: 200 with id
    assert r1.status_code == 200
    assert isinstance(r1.json()["policy_id"], int)

    # When: creating same name again
    r2 = client.put("/api/v1/policies", json={"name": name})
    # Then: 409
    assert r2.status_code == 409


def test_policy_add_control_and_list(client: TestClient) -> None:
    # Given: a policy and a control
    policy_id = _create_policy(client)
    control_id = _create_control(client)

    # When: associating control to policy
    r = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    # Then: success
    assert r.status_code == 200
    assert r.json()["success"] is True

    # When: listing policy controls
    l = client.get(f"/api/v1/policies/{policy_id}/controls")
    # Then: contains control id
    assert l.status_code == 200
    assert control_id in l.json()["control_ids"]


def test_policy_add_control_idempotent(client: TestClient) -> None:
    # Given: a policy with a control already associated
    policy_id = _create_policy(client)
    control_id = _create_control(client)
    client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")

    # When: adding the same control again
    r = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    # Then: still success (idempotent)
    assert r.status_code == 200
    assert r.json()["success"] is True

    # And listing still shows it once (set semantics by ids)
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
    # Then: success
    assert d.status_code == 200
    assert d.json()["success"] is True

    # When: listing controls
    l = client.get(f"/api/v1/policies/{policy_id}/controls")
    # Then: the control is not present
    assert l.status_code == 200
    assert control_id not in l.json()["control_ids"]


def test_policy_assoc_404s(client: TestClient) -> None:
    # Given: IDs
    policy_id = _create_policy(client)
    control_id = _create_control(client)

    # When: policy missing
    r1 = client.post(f"/api/v1/policies/999999/controls/{control_id}")
    # Then: 404
    assert r1.status_code == 404

    # When: control missing
    r2 = client.post(f"/api/v1/policies/{policy_id}/controls/999999")
    # Then: 404
    assert r2.status_code == 404

    # When: list on missing policy
    r3 = client.get("/api/v1/policies/999999/controls")
    # Then: 404
    assert r3.status_code == 404

    # When: delete with missing both sides
    r4 = client.delete("/api/v1/policies/999999/controls/999999")
    # Then: 404
    assert r4.status_code == 404
