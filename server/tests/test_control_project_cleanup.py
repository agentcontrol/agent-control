"""Public cleanup contracts and protected-source regression tests."""

from copy import deepcopy
import asyncio
from typing import Any
from uuid import uuid4

import pytest
from agent_control_models.errors import ErrorCode
from agent_control_server.auth_framework import Operation, Principal, set_authorizer
from agent_control_server.errors import ForbiddenError
from agent_control_server.models import DEFAULT_NAMESPACE_KEY
from agent_control_server.services.control_projects import ensure_project_active
from agent_control_server.services.control_project_cleanup import cleanup_project_controls
from agent_control_server.services.controls import ControlService
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from agent_control_server.models import Control, ControlBinding, ControlProjectScope
from .conftest import AsyncSessionTest

from .utils import VALID_CONTROL_PAYLOAD


class ProjectAuthorizer:
    """Synthetic upstream grants, not a test of the real Orbit role policy."""

    binding_target_authorization = True
    project_control_authorization = True

    def __init__(self, targets: dict[str, str]) -> None:
        self.targets = targets
        self.denied_projects: set[str] = set()

    async def resolve_identity(self, request: Request, operation: Operation) -> Principal:
        return Principal(namespace_key=DEFAULT_NAMESPACE_KEY)

    async def authorize(
        self,
        request: Request,
        operation: Operation,
        context: dict[str, Any] | None = None,
    ) -> Principal:
        context = context or {}
        project = context.get("project_id")
        target = context.get("target_id")
        if target is not None:
            project = self.targets.get(target)
            if project is None:
                raise ForbiddenError(
                    error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                    detail="Target not granted.",
                )
        if project in self.denied_projects:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="Project not granted.",
            )
        return Principal(
            namespace_key=DEFAULT_NAMESPACE_KEY,
            project_id=project,
            target_type=context.get("target_type"),
            target_id=target,
        )


def create_control(client: TestClient, name: str, project: str | None = None) -> int:
    payload: dict[str, Any] = {"name": name, "data": deepcopy(VALID_CONTROL_PAYLOAD)}
    if project is not None:
        payload["owner_project_id"] = project
    response = client.put("/api/v1/controls", json=payload)
    assert response.status_code == 200, response.text
    return int(response.json()["control_id"])


def bind(client: TestClient, control: int, target: str) -> int:
    response = client.put(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": "log_stream",
            "target_id": target,
            "control_id": control,
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["binding_id"])


def test_project_cleanup_preserves_global_source_and_other_project(client: TestClient) -> None:
    # Given: source S, Project A's independent clone and detached definition, and Project B.
    project_a, project_b, target_a, target_b = (str(uuid4()) for _ in range(4))
    set_authorizer(ProjectAuthorizer({target_a: project_a, target_b: project_b}))
    source = create_control(client, "cleanup-source")
    clone_response = client.post(
        f"/api/v1/controls/{source}/clone-and-bind",
        json={
            "owner_project_id": project_a,
            "target_binding": {
                "target_type": "log_stream",
                "target_id": target_a,
                "enabled": True,
            },
        },
    )
    assert clone_response.status_code == 200, clone_response.text
    clone = clone_response.json()["id"]
    detached = create_control(client, "cleanup-detached", project_a)
    protected = create_control(client, "cleanup-project-b", project_b)
    protected_binding = bind(client, protected, target_b)
    bind(client, source, target_a)

    # When: deleting A's control scope, including its legacy link to a global source.
    response = client.post(
        f"/api/v1/control-projects/{project_a}:cleanup", json={"target_ids": [target_a]}
    )

    # Then: only A's definitions and bindings disappear. The source and B survive.
    assert response.status_code == 200, response.text
    assert response.json() == {
        "owner_project_id": project_a,
        "state": "deleted",
        "controls_deleted": 2,
        "bindings_deleted": 2,
    }
    assert client.get(f"/api/v1/controls/{clone}").status_code == 404
    assert client.get(f"/api/v1/controls/{detached}").status_code == 404
    assert client.get(f"/api/v1/controls/{source}").status_code == 200
    assert client.get(f"/api/v1/controls/{protected}").status_code == 200
    assert client.get(f"/api/v1/control-bindings/{protected_binding}").status_code == 200


def test_cleanup_retries_and_blocks_new_data(client: TestClient) -> None:
    # Given: a project whose cleanup committed but whose upstream deletion may be retried.
    project, target = str(uuid4()), str(uuid4())
    set_authorizer(ProjectAuthorizer({target: project}))
    source = create_control(client, "retry-source")
    create_control(client, "retry-project-copy", project)
    path = f"/api/v1/control-projects/{project}:cleanup"
    first = client.post(path, json={"target_ids": [target]})
    assert first.status_code == 200, first.text

    # When: repeating cleanup after a lost response or later upstream failure.
    repeat = client.post(path, json={"target_ids": [target]})

    # Then: the retry succeeds without recreating data or allowing new project writes.
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["controls_deleted"] == 0
    assert repeat.json()["bindings_deleted"] == 0
    create = client.put(
        "/api/v1/controls",
        json={
            "name": "after-cleanup",
            "data": deepcopy(VALID_CONTROL_PAYLOAD),
            "owner_project_id": project,
        },
    )
    assert create.status_code == 409, create.text
    attach = client.put(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": "log_stream",
            "target_id": target,
            "control_id": source,
            "enabled": True,
        },
    )
    assert attach.status_code == 409, attach.text
    assert client.get(f"/api/v1/controls/{source}").status_code == 200


def test_cleanup_rejects_another_projects_target_without_mutation(client: TestClient) -> None:
    # Given: A and B have independent definitions and B has a binding.
    project_a, project_b, target_b = (str(uuid4()) for _ in range(3))
    set_authorizer(ProjectAuthorizer({target_b: project_b}))
    control_a = create_control(client, "denied-a", project_a)
    control_b = create_control(client, "denied-b", project_b)
    binding_b = bind(client, control_b, target_b)

    # When: a caller includes B's stream in a cleanup request for A.
    response = client.post(
        f"/api/v1/control-projects/{project_a}:cleanup", json={"target_ids": [target_b]}
    )

    # Then: rejection precedes cleanup and every protected object is unchanged.
    assert response.status_code == 403, response.text
    assert client.get(f"/api/v1/controls/{control_a}").status_code == 200
    assert client.get(f"/api/v1/controls/{control_b}").status_code == 200
    assert client.get(f"/api/v1/control-bindings/{binding_b}").status_code == 200


def test_stream_cleanup_preserves_definition_for_same_project_reuse(client: TestClient) -> None:
    # Given: two streams in one project share a project-owned definition.
    project, first_target, second_target = (str(uuid4()) for _ in range(3))
    set_authorizer(ProjectAuthorizer({first_target: project, second_target: project}))
    control = create_control(client, "stream-cleanup-copy", project)
    bind(client, control, first_target)

    # When: deleting the first stream's attachment scope.
    response = client.post(f"/api/v1/control-projects/{project}/targets/{first_target}:detach")

    # Then: its definition survives and can be attached by the same ID to another stream.
    assert response.status_code == 200, response.text
    assert response.json()["controls_deleted"] == 0
    assert client.get(f"/api/v1/controls/{control}").status_code == 200
    bind(client, control, second_target)
    old_target = client.put(
        "/api/v1/control-bindings/by-key",
        json={
            "target_type": "log_stream",
            "target_id": first_target,
            "control_id": control,
            "enabled": True,
        },
    )
    assert old_target.status_code == 409, old_target.text


def test_cleanup_includes_previously_authorized_targets_not_in_request(client: TestClient) -> None:
    # Given: a global definition was bound to a trusted target after an upstream
    # stream-list snapshot. This target is absent from the cleanup request.
    project, target = str(uuid4()), str(uuid4())
    set_authorizer(ProjectAuthorizer({target: project}))
    source = create_control(client, "concurrent-stream-global-source")
    binding = bind(client, source, target)

    # When: project cleanup uses durable target ownership, not only the snapshot.
    response = client.post(f"/api/v1/control-projects/{project}:cleanup", json={})

    # Then: the stale-snapshot binding disappears but its global source survives.
    assert response.status_code == 200, response.text
    assert response.json()["bindings_deleted"] == 1
    assert client.get(f"/api/v1/control-bindings/{binding}").status_code == 404
    assert client.get(f"/api/v1/controls/{source}").status_code == 200


def test_cleanup_rolls_back_definitions_bindings_and_tombstone_on_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an owned definition and binding must survive an incomplete transaction.
    project, target = str(uuid4()), str(uuid4())
    set_authorizer(ProjectAuthorizer({target: project}))
    control = create_control(client, "rollback-owned-definition", project)
    binding = bind(client, control, target)

    async def fail_version(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic cleanup failure")

    with monkeypatch.context() as patch:
        patch.setattr(ControlService, "create_version", fail_version)
        # When: snapshot persistence fails after binding deletion and soft deletion.
        with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
            client.post(f"/api/v1/control-projects/{project}:cleanup", json={})

    # Then: the request transaction rolls back every mutation and permits retry.
    assert client.get(f"/api/v1/controls/{control}").status_code == 200
    assert client.get(f"/api/v1/control-bindings/{binding}").status_code == 200
    create_control(client, "rollback-project-remains-active", project)
    response = client.post(f"/api/v1/control-projects/{project}:cleanup", json={})
    assert response.status_code == 200, response.text
    assert response.json()["controls_deleted"] == 2


@pytest.mark.asyncio
async def test_inflight_writer_serializes_with_cleanup_and_new_writes_fail() -> None:
    # Given: a writer holds the same PostgreSQL row lock used by project cleanup.
    from agent_control_server.errors import ConflictError

    project = str(uuid4())
    writer_locked = asyncio.Event()
    release_writer = asyncio.Event()
    cleanup_started = asyncio.Event()

    async def writer() -> None:
        async with AsyncSessionTest() as db:
            await ensure_project_active(db, DEFAULT_NAMESPACE_KEY, project)
            db.add(
                Control(
                    name="inflight-owned",
                    data=deepcopy(VALID_CONTROL_PAYLOAD),
                    namespace_key=DEFAULT_NAMESPACE_KEY,
                    owner_project_id=project,
                )
            )
            await db.flush()
            writer_locked.set()
            await release_writer.wait()
            await db.commit()

    async def cleanup() -> None:
        await writer_locked.wait()
        async with AsyncSessionTest() as db:
            cleanup_started.set()
            result = await cleanup_project_controls(
                db, namespace_key=DEFAULT_NAMESPACE_KEY, project_id=project, target_ids=[]
            )
            assert result.controls_deleted == 1
            await db.commit()

    # When: cleanup competes with an already-authorized in-flight writer.
    writer_task = asyncio.create_task(writer())
    cleanup_task = asyncio.create_task(cleanup())
    try:
        await asyncio.wait_for(cleanup_started.wait(), timeout=5)
        assert not cleanup_task.done()
    finally:
        release_writer.set()
    await asyncio.wait_for(asyncio.gather(writer_task, cleanup_task), timeout=10)

    # Then: cleanup sees the committed write; no post-cleanup writer can recreate it.
    async with AsyncSessionTest() as db:
        control = (
            await db.execute(select(Control).where(Control.name == "inflight-owned"))
        ).scalar_one()
        assert control.deleted_at is not None
        scope = (
            await db.execute(
                select(ControlProjectScope).where(
                    ControlProjectScope.project_id == project,
                )
            )
        ).scalar_one()
        assert scope.state == "deleted"
        assert not (await db.execute(select(ControlBinding))).scalars().all()
        with pytest.raises(ConflictError):
            await ensure_project_active(db, DEFAULT_NAMESPACE_KEY, project)


@pytest.mark.parametrize(
    "body",
    [{"target_ids": [""]}, {"target_ids": ["x" * 256]}, {"target_ids": [], "force_global": True}],
)
def test_cleanup_rejects_invalid_contract(client: TestClient, body: dict[str, Any]) -> None:
    # Given: only the documented bounded target list is accepted.
    project = str(uuid4())
    set_authorizer(ProjectAuthorizer({}))

    # When: posting invalid target IDs or an unsupported override.
    response = client.post(f"/api/v1/control-projects/{project}:cleanup", json=body)

    # Then: validation fails before cleanup.
    assert response.status_code == 422, response.text
