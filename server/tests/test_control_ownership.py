"""Public HTTP contracts for project ownership and independent clones."""

from copy import deepcopy
from typing import Any

import pytest
from agent_control_models.errors import ErrorCode
from fastapi import Request
from fastapi.testclient import TestClient

from agent_control_server.auth_framework import Operation, Principal, set_authorizer
from agent_control_server.auth_framework.providers.header import HeaderAuthProvider
from agent_control_server.errors import ForbiddenError
from agent_control_server.models import DEFAULT_NAMESPACE_KEY

from .utils import VALID_CONTROL_PAYLOAD


class ProjectAuthorizer:
    """Deterministic trusted upstream surrogate, not a browser-provided grant."""

    binding_target_authorization = True
    project_control_authorization = True

    def __init__(self) -> None:
        self.allowed = {"A", "B"}
        self.bad_grant = False
        self.org_read = True

    async def resolve_identity(self, request: Request, operation: Operation) -> Principal:
        return Principal(namespace_key=DEFAULT_NAMESPACE_KEY)

    async def authorize(
        self, request: Request, operation: Operation, context: dict[str, Any] | None = None
    ) -> Principal:
        context = context or {}
        project = context.get("project_id")
        target = context.get("target_id")
        if target:
            project = {"stream-A": "A", "stream-B": "B"}.get(target)
        if project is not None and project not in self.allowed:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES, detail="Project denied"
            )
        if operation is Operation.CONTROLS_READ and not self.org_read:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES, detail="Organization read denied"
            )
        return Principal(
            namespace_key=DEFAULT_NAMESPACE_KEY,
            project_id="wrong-project" if self.bad_grant else project,
            target_type=context.get("target_type"),
            target_id=target,
        )


@pytest.fixture
def owner_provider():
    provider = ProjectAuthorizer()
    set_authorizer(provider)
    try:
        yield provider
    finally:
        set_authorizer(HeaderAuthProvider())


def create(client: TestClient, name: str, owner: str | None = None) -> int:
    body: dict[str, Any] = {"name": name, "data": deepcopy(VALID_CONTROL_PAYLOAD)}
    if owner is not None:
        body["owner_project_id"] = owner
    response = client.put("/api/v1/controls", json=body)
    assert response.status_code == 200, response.text
    return response.json()["control_id"]


def key(control_id: int, project: str = "A") -> dict[str, Any]:
    return {
        "target_type": "log_stream",
        "target_id": "stream-" + project,
        "control_id": control_id,
        "enabled": True,
    }


def test_owner_list_filters_before_pagination_and_global_discovery(client, owner_provider):
    # Given: many other-project rows newer than the requested project's row.
    source = create(client, "global")
    own = create(client, "project-a", "A")
    for index in range(22):
        create(client, "project-b-" + str(index), "B")
    # When: reading the global and project collections with a one-row page.
    global_page = client.get("/api/v1/controls").json()
    project_page = client.get(
        "/api/v1/controls", params={"owner_project_id": "A", "limit": 1}
    ).json()
    # Then: ownership applies before paging and totals; A does not become global.
    assert {row["id"] for row in global_page["controls"]} == {source}
    assert [row["id"] for row in project_page["controls"]] == [own]
    assert project_page["pagination"]["total"] == 1
    assert project_page["pagination"]["has_more"] is False


@pytest.mark.parametrize("suffix", ["", "/data", "/versions", "/versions/1"])
def test_direct_id_and_history_use_stored_owner(client, owner_provider, suffix):
    # Given: a project-A control and a caller authorized only for B.
    own = create(client, "private-a", "A")
    owner_provider.allowed = {"B"}
    # When/Then: every direct read surface is non-disclosing.
    response = client.get(f"/api/v1/controls/{own}{suffix}")
    assert response.status_code == 404


def test_denied_mutations_preserve_definition(client, owner_provider):
    own = create(client, "private-a", "A")
    original = client.get(f"/api/v1/controls/{own}").json()
    owner_provider.allowed = {"B"}
    assert client.patch(f"/api/v1/controls/{own}", json={"name": "stolen"}).status_code == 404
    assert (
        client.put(f"/api/v1/controls/{own}/data", json={"data": VALID_CONTROL_PAYLOAD}).status_code
        == 404
    )
    assert client.delete(f"/api/v1/controls/{own}").status_code == 404
    owner_provider.allowed = {"A"}
    assert client.get(f"/api/v1/controls/{own}").json() == original


def test_binding_checks_trusted_project_and_detached_discovery(client, owner_provider):
    own = create(client, "retained-a", "A")
    assert client.put("/api/v1/control-bindings/by-key", json=key(own, "B")).status_code == 404
    attached = client.put("/api/v1/control-bindings/by-key", json=key(own))
    assert attached.status_code == 200
    detach = key(own)
    detach.pop("enabled")
    assert client.post("/api/v1/control-bindings/by-key:delete", json=detach).status_code == 200
    page = client.get("/api/v1/controls", params={"owner_project_id": "A"}).json()
    assert [row["id"] for row in page["controls"]] == [own]
    assert page["controls"][0]["owner_project_id"] == "A"
    assert client.put("/api/v1/control-bindings/by-key", json=key(own)).json()["created"] is True


def test_stream_list_keeps_legacy_org_rows_but_excludes_other_projects(client, owner_provider):
    source = create(client, "legacy-global")
    own = create(client, "owned-a", "A")
    create(client, "owned-b", "B")
    for identifier in (source, own):
        assert (
            client.put("/api/v1/control-bindings/by-key", json=key(identifier)).status_code == 200
        )
    params = {
        "include_attachments": True,
        "attachment_target_type": "log_stream",
        "attachment_target_id": "stream-A",
    }
    response = client.get("/api/v1/controls", params=params)
    assert response.status_code == 200, response.text
    assert {row["id"] for row in response.json()["controls"]} == {source, own}
    owner_provider.org_read = False
    response = client.get("/api/v1/controls", params=params)
    assert response.status_code == 200
    assert {row["id"] for row in response.json()["controls"]} == {own}


def test_independent_clone_delete_and_source_delete(client, owner_provider):
    source = create(client, "source")
    clones = []
    for project in ("A", "B"):
        response = client.post(
            f"/api/v1/controls/{source}/clone-and-bind",
            json={
                "owner_project_id": project,
                "target_binding": {"target_type": "log_stream", "target_id": "stream-" + project},
            },
        )
        assert response.status_code == 200, response.text
        clones.append(response.json()["id"])
    clone_a, clone_b = clones
    assert client.patch(f"/api/v1/controls/{clone_a}", json={"name": "edited-a"}).status_code == 200
    assert client.get(f"/api/v1/controls/{source}").json()["name"] == "source"
    assert client.delete(f"/api/v1/controls/{clone_a}").status_code == 409
    assert client.delete(f"/api/v1/controls/{clone_a}", params={"force": True}).status_code == 200
    assert client.get(f"/api/v1/controls/{source}").status_code == 200
    assert client.get(f"/api/v1/controls/{clone_b}").status_code == 200
    assert client.delete(f"/api/v1/controls/{source}").status_code == 200
    assert client.get(f"/api/v1/controls/{clone_b}").status_code == 200
    remaining = client.get(
        "/api/v1/control-bindings", params={"target_type": "log_stream", "target_id": "stream-B"}
    ).json()
    assert [row["control_id"] for row in remaining["bindings"]] == [clone_b]


def test_project_grant_mismatch_rolls_back_create(client, owner_provider):
    owner_provider.bad_grant = True
    response = client.put(
        "/api/v1/controls",
        json={"name": "invalid-grant", "data": VALID_CONTROL_PAYLOAD, "owner_project_id": "A"},
    )
    assert response.status_code == 403
    owner_provider.bad_grant = False
    assert client.get("/api/v1/controls", params={"owner_project_id": "A"}).json()["controls"] == []


def test_standalone_provider_rejects_project_ownership_but_preserves_org_create(client):
    response = client.put(
        "/api/v1/controls",
        json={"name": "unsupported", "data": VALID_CONTROL_PAYLOAD, "owner_project_id": "A"},
    )
    assert response.status_code == 403
    assert create(client, "ordinary-org") > 0


def test_project_definition_cannot_enter_org_policy(client, owner_provider):
    own = create(client, "owned-a", "A")
    policy = client.put("/api/v1/policies", json={"name": "org-policy"}).json()["policy_id"]
    assert client.post(f"/api/v1/policies/{policy}/controls/{own}").status_code == 404
    assert client.get(f"/api/v1/policies/{policy}/controls").json()["control_ids"] == []


@pytest.mark.parametrize("destination", [None, "B"])
def test_clone_cannot_implicitly_promote_or_change_project(client, owner_provider, destination):
    # Given: an existing project-A definition.
    own = create(client, "source-a", "A")
    payload = {
        "target_binding": {
            "target_type": "log_stream",
            "target_id": "stream-" + (destination or "A"),
        }
    }
    if destination is not None:
        payload["owner_project_id"] = destination
    # When/Then: clone cannot change the stored ownership boundary.
    response = client.post(f"/api/v1/controls/{own}/clone-and-bind", json=payload)
    assert response.status_code == 403
    assert client.get("/api/v1/controls").json()["controls"] == []
    assert (
        len(client.get("/api/v1/controls", params={"owner_project_id": "A"}).json()["controls"])
        == 1
    )
