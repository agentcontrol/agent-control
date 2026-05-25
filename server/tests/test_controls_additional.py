from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_control_evaluators import RegexEvaluatorConfig
from agent_control_models import ConditionNode
from agent_control_models.errors import ErrorCode, ErrorReason
from agent_control_server.auth_framework import Operation, Principal, set_authorizer
from agent_control_server.db import get_async_db
from agent_control_server.endpoints import controls as controls_module
from agent_control_server.errors import APIError, BadRequestError, ForbiddenError
from agent_control_server.main import app
from agent_control_server.models import (
    DEFAULT_NAMESPACE_KEY,
    Control,
    ControlBinding,
    ControlVersion,
)
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .conftest import engine
from .utils import VALID_CONTROL_PAYLOAD


def _make_integrity_error(constraint_name: str) -> IntegrityError:
    diag = SimpleNamespace(constraint_name=constraint_name)
    orig = Exception(f'duplicate key value violates unique constraint "{constraint_name}"')
    setattr(orig, "diag", diag)
    return IntegrityError("statement", {}, orig)


def _create_control(
    client: TestClient,
    name: str | None = None,
    data: dict | None = None,
) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    payload = deepcopy(data) if data is not None else deepcopy(VALID_CONTROL_PAYLOAD)
    resp = client.put("/api/v1/controls", json={"name": control_name, "data": payload})
    assert resp.status_code == 200
    return resp.json()["control_id"], control_name


def _insert_unconfigured_control(name: str | None = None) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    control = Control(name=control_name, data={})
    with Session(engine) as session:
        session.add(control)
        session.commit()
        session.refresh(control)
        return int(control.id), control_name


def _set_control_data(client: TestClient, control_id: int, data: dict) -> None:
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": data})
    assert resp.status_code == 200, resp.text


def test_clone_and_bind_creates_cloned_control_binding_and_version(
    client: TestClient,
) -> None:
    source_id, source_name = _create_control(client)

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-123",
                "enabled": False,
            }
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    clone_id = body["id"]
    binding_id = body["binding_id"]
    assert clone_id != source_id
    assert body["name"].startswith(f"{source_name}-clone-")
    assert body["cloned_from_control_id"] == source_id

    with Session(engine) as session:
        source = session.get_one(Control, source_id)
        clone = session.get_one(Control, clone_id)
        binding = session.execute(
            select(ControlBinding).where(ControlBinding.id == binding_id)
        ).scalar_one()
        version = session.execute(
            select(ControlVersion).where(ControlVersion.control_id == clone_id)
        ).scalar_one()

    assert clone.namespace_key == source.namespace_key
    assert clone.data == source.data
    assert clone.cloned_from_control_id == source_id
    assert binding.control_id == clone_id
    assert binding.target_type == "log_stream"
    assert binding.target_id == "logstream-123"
    assert binding.enabled is False
    assert version.version_num == 1
    assert version.event_type == "cloned"
    assert version.note == f"Cloned from control {source_id}"
    assert version.snapshot["cloned_from_control_id"] == source_id
    assert version.snapshot["cloned_control_id"] == source_id

    get_resp = client.get(f"/api/v1/controls/{clone_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["cloned_from_control_id"] == source_id


def test_control_clone_lineage_enforces_same_namespace() -> None:
    source = Control(
        namespace_key=DEFAULT_NAMESPACE_KEY,
        name=f"source-{uuid.uuid4()}",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
    )
    clone = Control(
        namespace_key="other-namespace",
        name=f"clone-{uuid.uuid4()}",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        cloned_from_control_id=1,
    )

    with Session(engine) as session:
        session.add(source)
        session.flush()
        clone.cloned_from_control_id = int(source.id)
        session.add(clone)
        with pytest.raises(IntegrityError):
            session.commit()


def test_clone_and_bind_generated_name_falls_back_for_legacy_name(
    client: TestClient,
) -> None:
    legacy_name = "legacy control name"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO controls (name, data) VALUES (:name, CAST(:data AS JSONB))"
            ),
            {
                "name": legacy_name,
                "data": json.dumps(VALID_CONTROL_PAYLOAD),
            },
        )
        row = conn.execute(
            text("SELECT id FROM controls WHERE name = :name"),
            {"name": legacy_name},
        ).fetchone()
        assert row is not None
        source_id = row[0]

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-legacy-name",
            },
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"].startswith(f"control-{source_id}-clone-")


def test_list_controls_filters_by_cloned_state(client: TestClient) -> None:
    source_id, _ = _create_control(client, name=f"Root-{uuid.uuid4()}")
    clone_name = f"Clone-{uuid.uuid4()}"
    clone_resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "name": clone_name,
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-456",
            },
        },
    )
    assert clone_resp.status_code == 200, clone_resp.text
    clone_id = clone_resp.json()["id"]

    root_resp = client.get("/api/v1/controls", params={"cloned": False, "limit": 100})
    assert root_resp.status_code == 200
    root_ids = {control["id"] for control in root_resp.json()["controls"]}
    assert source_id in root_ids
    assert clone_id not in root_ids

    clone_list_resp = client.get(
        "/api/v1/controls", params={"cloned": True, "limit": 100}
    )
    assert clone_list_resp.status_code == 200
    cloned_controls = clone_list_resp.json()["controls"]
    cloned_ids = {control["id"] for control in cloned_controls}
    assert clone_id in cloned_ids
    assert source_id not in cloned_ids
    listed_clone = next(control for control in cloned_controls if control["id"] == clone_id)
    assert listed_clone["cloned_from_control_id"] == source_id


def test_clone_and_bind_returns_conflict_for_duplicate_clone_name(
    client: TestClient,
) -> None:
    _, existing_name = _create_control(client)
    source_id, _ = _create_control(client)

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "name": existing_name,
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-789",
            },
        },
    )

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_clone_and_bind_integrity_error_name_conflict_returns_409(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id, _ = _create_control(client)

    async def fail_create_version(
        self: controls_module.ControlService,
        control: Control,
        *,
        event_type: str,
        note: str,
    ) -> None:
        _ = (self, control, event_type, note)
        raise _make_integrity_error("idx_controls_namespace_name_active")

    monkeypatch.setattr(
        controls_module.ControlService,
        "create_version",
        fail_create_version,
    )

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "name": f"race-{uuid.uuid4()}",
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-race",
            },
        },
    )

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_clone_and_bind_generated_name_retries_preflight_conflicts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id, source_name = _create_control(client, name=f"source-{uuid.uuid4()}")
    first_suffix = "1111111111111111"
    second_suffix = "2222222222222222"
    _create_control(client, name=f"{source_name}-clone-{first_suffix}")
    suffixes = iter([first_suffix, second_suffix])

    def fake_uuid4() -> SimpleNamespace:
        return SimpleNamespace(hex=next(suffixes))

    monkeypatch.setattr(controls_module.uuid, "uuid4", fake_uuid4)

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-retry-name",
            },
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == f"{source_name}-clone-{second_suffix}"


def test_clone_and_bind_rolls_back_clone_when_binding_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id, _ = _create_control(client)
    clone_name = f"CloneRollback-{uuid.uuid4()}"

    async def fail_create_binding(*args: Any, **kwargs: Any) -> None:
        raise BadRequestError(
            error_code=ErrorCode.CONTROL_BINDING_INCOMPATIBLE,
            detail="Binding failed after clone creation.",
            resource="ControlBinding",
        )

    monkeypatch.setattr(
        controls_module.ControlBindingsService,
        "create_binding",
        fail_create_binding,
    )

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "name": clone_name,
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-rollback",
            },
        },
    )

    assert resp.status_code == 400
    with Session(engine) as session:
        clone = session.execute(
            select(Control).where(Control.name == clone_name)
        ).scalar_one_or_none()
    assert clone is None


def test_clone_and_bind_locks_source_control(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id, _ = _create_control(client)
    original_get_active = controls_module.ControlService.get_active_control_or_404
    seen_for_update: list[bool] = []

    async def recording_get_active(
        self: controls_module.ControlService,
        control_id_arg: int,
        *,
        namespace_key: str | None = None,
        for_update: bool = False,
    ) -> Control:
        seen_for_update.append(for_update)
        return await original_get_active(
            self,
            control_id_arg,
            namespace_key=namespace_key,
            for_update=for_update,
        )

    monkeypatch.setattr(
        controls_module.ControlService,
        "get_active_control_or_404",
        recording_get_active,
    )

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-lock",
            },
        },
    )

    assert resp.status_code == 200, resp.text
    assert seen_for_update == [True]


def test_clone_and_bind_rejects_auth_namespace_mismatch(client: TestClient) -> None:
    source_id, _ = _create_control(client)

    class MismatchedNamespaceAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            namespace_key = (
                "other-namespace"
                if operation == Operation.CONTROL_BINDINGS_WRITE
                else DEFAULT_NAMESPACE_KEY
            )
            return Principal(namespace_key=namespace_key, is_admin=True)

    set_authorizer(MismatchedNamespaceAuthorizer())

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-mismatch",
            },
        },
    )

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "AUTH_INSUFFICIENT_PRIVILEGES"


def test_clone_and_bind_requires_source_read_authorization(
    client: TestClient,
) -> None:
    source_id, _ = _create_control(client)
    calls: list[tuple[Operation, dict[str, Any] | None]] = []

    class ReadMismatchAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            calls.append((operation, context))
            namespace_key = (
                "other-namespace"
                if operation == Operation.CONTROLS_READ
                else DEFAULT_NAMESPACE_KEY
            )
            return Principal(namespace_key=namespace_key, is_admin=True)

    set_authorizer(ReadMismatchAuthorizer())

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-read-auth",
            },
        },
    )

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "AUTH_INSUFFICIENT_PRIVILEGES"
    read_contexts = [
        context for operation, context in calls if operation == Operation.CONTROLS_READ
    ]
    assert read_contexts == [None]


def test_clone_and_bind_context_tolerates_invalid_body_shapes(
    client: TestClient,
) -> None:
    resp = client.post(
        "/api/v1/controls/1/clone-and-bind",
        content="{",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422

    list_resp = client.post("/api/v1/controls/1/clone-and-bind", json=[])
    assert list_resp.status_code == 422

    bad_target_resp = client.post(
        "/api/v1/controls/1/clone-and-bind",
        json={"target_binding": "not-an-object"},
    )
    assert bad_target_resp.status_code == 422


def test_clone_and_bind_context_drops_invalid_target_fields(
    client: TestClient,
) -> None:
    calls: list[tuple[Operation, dict[str, Any] | None]] = []

    class RecordingAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            calls.append((operation, context))
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(RecordingAuthorizer())

    resp = client.post(
        "/api/v1/controls/1/clone-and-bind",
        json={
            "target_binding": {
                "target_type": ["log_stream"],
                "target_id": {"id": "logstream-invalid"},
            },
        },
    )

    assert resp.status_code == 422
    binding_contexts = [
        context
        for operation, context in calls
        if operation == Operation.CONTROL_BINDINGS_WRITE
    ]
    assert binding_contexts == [{}]


def test_clone_and_bind_context_drops_overlong_target_fields(
    client: TestClient,
) -> None:
    calls: list[tuple[Operation, dict[str, Any] | None]] = []

    class RecordingAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            calls.append((operation, context))
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(RecordingAuthorizer())

    resp = client.post(
        "/api/v1/controls/1/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "x" * 256,
                "target_id": "logstream-invalid",
            },
        },
    )

    assert resp.status_code == 422
    binding_contexts = [
        context
        for operation, context in calls
        if operation == Operation.CONTROL_BINDINGS_WRITE
    ]
    assert binding_contexts == [{}]


def test_clone_and_bind_rejects_unknown_target_binding_fields(
    client: TestClient,
) -> None:
    source_id, _ = _create_control(client)

    resp = client.post(
        f"/api/v1/controls/{source_id}/clone-and-bind",
        json={
            "target_binding": {
                "target_type": "log_stream",
                "target_id": "logstream-extra",
                "unknown_field": "ignored-before",
            },
        },
    )

    assert resp.status_code == 422


@pytest.mark.parametrize(
    "constraint_name",
    ["idx_controls_name_active", "idx_controls_namespace_name_active"],
)
def test_create_control_integrity_error_returns_conflict(
    client: TestClient, constraint_name: str
) -> None:
    """DB uniqueness violations during create should be surfaced as 409 conflicts."""

    async def mock_db_integrity_error() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        existing_result = MagicMock()
        existing_result.first.return_value = None

        mock_session.execute = AsyncMock(return_value=existing_result)
        mock_session.add = MagicMock()
        mock_session.refresh = AsyncMock()
        mock_session.commit = AsyncMock(
            side_effect=_make_integrity_error(constraint_name)
        )
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db_integrity_error
    try:
        resp = client.put(
            "/api/v1/controls",
            json={"name": "duplicate-control", "data": VALID_CONTROL_PAYLOAD},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


@pytest.mark.parametrize(
    "constraint_name",
    ["idx_controls_name_active", "idx_controls_namespace_name_active"],
)
def test_patch_control_rename_integrity_error_returns_conflict(
    client: TestClient, constraint_name: str
) -> None:
    """DB uniqueness violations during rename should be surfaced as 409 conflicts."""
    control_obj = SimpleNamespace(
        id=1,
        name="old-control",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        deleted_at=None,
    )

    async def mock_db_integrity_error() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)

        control_lookup_result = MagicMock()
        control_lookup_result.scalars.return_value.first.return_value = control_obj

        name_lookup_result = MagicMock()
        name_lookup_result.first.return_value = None

        lock_result = MagicMock()
        version_lookup_result = MagicMock()
        version_lookup_result.scalar_one.return_value = 1

        mock_session.execute = AsyncMock(
            side_effect=[
                control_lookup_result,
                name_lookup_result,
                lock_result,
                version_lookup_result,
            ]
        )
        mock_session.commit = AsyncMock(
            side_effect=_make_integrity_error(constraint_name)
        )
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db_integrity_error
    try:
        resp = client.patch("/api/v1/controls/1", json={"name": "existing-control"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_patch_control_non_name_integrity_error_returns_500(client: TestClient) -> None:
    """Non-name integrity failures during patch should surface as database errors."""
    control_obj = SimpleNamespace(
        id=1,
        name="old-control",
        data=deepcopy(VALID_CONTROL_PAYLOAD),
        deleted_at=None,
    )

    async def mock_db_integrity_error() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)

        control_lookup_result = MagicMock()
        control_lookup_result.scalars.return_value.first.return_value = control_obj

        lock_result = MagicMock()
        version_lookup_result = MagicMock()
        version_lookup_result.scalar_one.return_value = 1

        mock_session.execute = AsyncMock(
            side_effect=[
                control_lookup_result,
                lock_result,
                version_lookup_result,
            ]
        )
        mock_session.commit = AsyncMock(
            side_effect=_make_integrity_error("uq_control_versions_control_version")
        )
        yield mock_session

    app.dependency_overrides[get_async_db] = mock_db_integrity_error
    try:
        resp = client.patch("/api/v1/controls/1", json={"enabled": False})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 500
    assert resp.json()["error_code"] == "DATABASE_ERROR"


def test_list_controls_filters_and_pagination(client: TestClient) -> None:
    # Given: three controls with varying data
    control1_id, control1_name = _create_control(client, name=f"AlphaControl-{uuid.uuid4()}")
    control2_id, control2_name = _create_control(client, name=f"BetaControl-{uuid.uuid4()}")
    control3_id, control3_name = _create_control(client, name=f"GammaControl-{uuid.uuid4()}")

    data1 = deepcopy(VALID_CONTROL_PAYLOAD)
    data1.update(
        {
            "description": "alpha",
            "enabled": True,
            "execution": "server",
            "scope": {"step_types": ["tool"], "stages": ["pre"]},
            "tags": ["pci"],
        }
    )

    data2 = deepcopy(VALID_CONTROL_PAYLOAD)
    data2.update(
        {
            "description": "beta",
            "enabled": False,
            "execution": "server",
            "scope": {"step_types": ["llm"], "stages": ["post"]},
            "tags": ["hipaa"],
        }
    )

    data3 = deepcopy(VALID_CONTROL_PAYLOAD)
    data3.pop("enabled", None)
    data3.pop("scope", None)
    data3.update({"description": "gamma", "tags": ["misc"]})

    _set_control_data(client, control1_id, data1)
    _set_control_data(client, control2_id, data2)
    _set_control_data(client, control3_id, data3)

    # When: filtering by name (case-insensitive partial match)
    resp = client.get("/api/v1/controls", params={"name": "alpha"})
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["controls"]]
    # Then: only the matching control is returned
    assert names == [control1_name]

    # When: filtering by enabled=false
    resp = client.get("/api/v1/controls", params={"enabled": "false"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: only explicitly disabled controls are returned
    assert names == {control2_name}

    # When: filtering by step_type=tool (controls without scope still match)
    resp = client.get("/api/v1/controls", params={"step_type": "tool"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: controls with matching step_type or missing scope are included
    assert control1_name in names
    assert control3_name in names
    assert control2_name not in names

    # When: filtering by tag
    resp = client.get("/api/v1/controls", params={"tag": "pci"})
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["controls"]]
    # Then: only controls with the tag are returned
    assert names == [control1_name]

    # Then: enabled defaults to True when missing
    resp = client.get("/api/v1/controls", params={"name": "gamma"})
    assert resp.status_code == 200
    control = resp.json()["controls"][0]
    assert control["name"] == control3_name
    assert control["enabled"] is True
    assert control["action"] == {"decision": "deny", "steering_context": None}

    # When: paginating
    resp = client.get("/api/v1/controls", params={"limit": 1})
    assert resp.status_code == 200
    page1 = resp.json()
    # Then: response indicates more pages
    assert page1["pagination"]["has_more"] is True
    assert page1["pagination"]["next_cursor"] is not None
    first_id = page1["controls"][0]["id"]

    # When: fetching the next page
    resp2 = client.get(
        "/api/v1/controls",
        params={"limit": 1, "cursor": page1["pagination"]["next_cursor"]},
    )
    assert resp2.status_code == 200
    page2 = resp2.json()
    # Then: the next page has a different item
    assert page2["controls"][0]["id"] != first_id


def test_patch_control_enabled_with_invalid_data_returns_corrupted_data(
    client: TestClient,
) -> None:
    # Given: a control with an invalid empty payload
    control_id, _ = _insert_unconfigured_control()

    # When: toggling enabled
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": False})

    # Then: corrupted-data validation is returned
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "CORRUPTED_DATA"


def test_patch_control_rename_conflict(client: TestClient) -> None:
    # Given: two controls
    _, existing_name = _create_control(client)
    control_id, _ = _create_control(client)

    # When: renaming to an existing name
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"name": existing_name})

    # Then: conflict
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_NAME_CONFLICT"


def test_patch_control_rename_with_spaces_rejected(client: TestClient) -> None:
    # Given: an existing control
    control_id, _ = _create_control(client)

    # When: renaming with spaces in the name
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": "control with spaces"},
    )

    # Then: request validation rejects the rename
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "VALIDATION_ERROR"


def test_create_control_trimmed_name_stored(client: TestClient) -> None:
    """Control names are canonicalized at the API boundary: leading/trailing whitespace is trimmed."""
    resp = client.put(
        "/api/v1/controls",
        json={"name": "  trimmed-control  ", "data": VALID_CONTROL_PAYLOAD},
    )
    assert resp.status_code == 200
    control_id = resp.json()["control_id"]
    get_resp = client.get(f"/api/v1/controls/{control_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "trimmed-control"


def test_patch_control_trimmed_name_stored(client: TestClient) -> None:
    """PATCH control name is canonicalized at the API boundary: leading/trailing whitespace is trimmed."""
    control_id, _ = _create_control(client)
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": "  new-trimmed-name  "},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-trimmed-name"


def test_patch_control_legacy_name_preserved_when_name_omitted(
    client: TestClient,
) -> None:
    """Controls with legacy names (e.g. created before slug validation) remain editable.

    Policy: existing invalid names stay as-is when the client does not send a name
    update. PATCH with only enabled or other fields must not change or re-validate
    the stored name.
    """
    # Insert a control with a legacy name that would not pass current SlugName validation.
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO controls (name, data) VALUES (:name, CAST(:data AS JSONB))"
            ),
            {
                "name": "legacy control name",
                "data": json.dumps(VALID_CONTROL_PAYLOAD),
            },
        )
        row = conn.execute(
            text("SELECT id FROM controls WHERE name = 'legacy control name'")
        ).fetchone()
        assert row is not None
        control_id = row[0]

    # When: PATCH without sending name (no name update, no enabled change)
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={},
    )
    assert resp.status_code == 200
    # Then: stored name is unchanged
    assert resp.json()["name"] == "legacy control name"
    get_resp = client.get(f"/api/v1/controls/{control_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "legacy control name"


def test_list_controls_filters_stage_and_execution(client: TestClient) -> None:
    # Given: controls with differing stages and execution targets
    control1_id, control1_name = _create_control(client)
    control2_id, control2_name = _create_control(client)
    control3_id, control3_name = _create_control(client)

    data1 = deepcopy(VALID_CONTROL_PAYLOAD)
    data1.update(
        {
            "execution": "server",
            "scope": {"stages": ["pre"], "step_types": ["llm"]},
        }
    )
    data2 = deepcopy(VALID_CONTROL_PAYLOAD)
    data2.update(
        {
            "execution": "sdk",
            "scope": {"stages": ["post"], "step_types": ["llm"]},
        }
    )
    data3 = deepcopy(VALID_CONTROL_PAYLOAD)
    data3.update({"execution": "server"})
    data3.pop("scope", None)

    _set_control_data(client, control1_id, data1)
    _set_control_data(client, control2_id, data2)
    _set_control_data(client, control3_id, data3)

    # When: filtering by stage=pre
    resp = client.get("/api/v1/controls", params={"stage": "pre"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: matching stage and missing scope are included
    assert names == {control1_name, control3_name}

    # When: filtering by stage=post
    resp = client.get("/api/v1/controls", params={"stage": "post"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: matching stage and missing scope are included
    assert names == {control2_name, control3_name}

    # When: filtering by execution=server
    resp = client.get("/api/v1/controls", params={"execution": "server"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: only server-executed controls are returned
    assert names == {control1_name, control3_name}

    # When: filtering by execution=sdk
    resp = client.get("/api/v1/controls", params={"execution": "sdk"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}
    # Then: only sdk-executed controls are returned
    assert names == {control2_name}


def test_list_controls_combined_filters(client: TestClient) -> None:
    # Given: controls with distinct names/tags
    control1_id, control1_name = _create_control(client, name=f"Alpha-{uuid.uuid4()}")
    control2_id, control2_name = _create_control(client, name=f"Alpha-{uuid.uuid4()}")

    data1 = deepcopy(VALID_CONTROL_PAYLOAD)
    data1.update({"tags": ["pci"], "enabled": True})
    data2 = deepcopy(VALID_CONTROL_PAYLOAD)
    data2.update({"tags": ["hipaa"], "enabled": True})

    _set_control_data(client, control1_id, data1)
    _set_control_data(client, control2_id, data2)

    # When: filtering by name and tag together
    resp = client.get(
        "/api/v1/controls",
        params={"name": "alpha", "tag": "pci"},
    )
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()["controls"]]

    # Then: only controls matching all filters are returned
    assert names == [control1_name]


def test_list_controls_enabled_true_includes_missing_enabled(client: TestClient) -> None:
    # Given: controls with enabled true, enabled false, and missing enabled
    control_true_id, control_true_name = _create_control(client, name=f"Enabled-{uuid.uuid4()}")
    control_false_id, control_false_name = _create_control(client, name=f"Disabled-{uuid.uuid4()}")
    control_missing_id, control_missing_name = _create_control(client, name=f"Missing-{uuid.uuid4()}")

    data_true = deepcopy(VALID_CONTROL_PAYLOAD)
    data_true["enabled"] = True
    data_false = deepcopy(VALID_CONTROL_PAYLOAD)
    data_false["enabled"] = False
    data_missing = deepcopy(VALID_CONTROL_PAYLOAD)
    data_missing.pop("enabled", None)

    _set_control_data(client, control_true_id, data_true)
    _set_control_data(client, control_false_id, data_false)
    _set_control_data(client, control_missing_id, data_missing)

    # When: filtering by enabled=true
    resp = client.get("/api/v1/controls", params={"enabled": "true"})
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["controls"]}

    # Then: enabled=true and missing enabled are included; enabled=false is excluded
    assert names == {control_true_name, control_missing_name}


def test_list_controls_cursor_with_tag_filter(client: TestClient) -> None:
    # Given: multiple controls sharing a tag and one without it
    control_ids = []
    control_names = []
    for _ in range(3):
        cid, name = _create_control(client, name=f"Tagged-{uuid.uuid4()}")
        control_ids.append(cid)
        control_names.append(name)

    other_id, other_name = _create_control(client, name=f"Other-{uuid.uuid4()}")

    data_tagged = deepcopy(VALID_CONTROL_PAYLOAD)
    data_tagged.update({"tags": ["pci"]})
    data_other = deepcopy(VALID_CONTROL_PAYLOAD)
    data_other.update({"tags": ["hipaa"]})

    for cid in control_ids:
        _set_control_data(client, cid, data_tagged)
    _set_control_data(client, other_id, data_other)

    # When: requesting the first page filtered by tag
    resp = client.get("/api/v1/controls", params={"tag": "pci", "limit": 2})
    assert resp.status_code == 200
    page1 = resp.json()

    # Then: pagination reflects filtered total and has more pages
    assert page1["pagination"]["total"] == 3
    assert page1["pagination"]["has_more"] is True
    assert page1["pagination"]["next_cursor"] is not None
    assert len(page1["controls"]) == 2
    assert all("pci" in c["tags"] for c in page1["controls"])

    # When: requesting the next page with cursor
    resp2 = client.get(
        "/api/v1/controls",
        params={"tag": "pci", "limit": 2, "cursor": page1["pagination"]["next_cursor"]},
    )
    assert resp2.status_code == 200
    page2 = resp2.json()

    # Then: remaining tagged control is returned
    assert page2["pagination"]["has_more"] is False
    assert len(page2["controls"]) == 1
    assert page2["controls"][0]["name"] in control_names


def test_list_controls_cursor_with_name_and_enabled_filters(client: TestClient) -> None:
    # Given: controls with shared name prefix and mixed enabled states
    matching_ids = []
    matching_names = []
    for enabled in (True, True, False):
        cid, name = _create_control(client, name=f"Match-{uuid.uuid4()}")
        matching_ids.append(cid)
        matching_names.append(name)
        data = deepcopy(VALID_CONTROL_PAYLOAD)
        data["enabled"] = enabled
        _set_control_data(client, cid, data)

    non_match_id, non_match_name = _create_control(client, name=f"Other-{uuid.uuid4()}")
    non_match_data = deepcopy(VALID_CONTROL_PAYLOAD)
    non_match_data["enabled"] = True
    _set_control_data(client, non_match_id, non_match_data)

    # When: listing with name filter and enabled=true
    resp = client.get(
        "/api/v1/controls",
        params={"name": "match", "enabled": "true", "limit": 1},
    )
    assert resp.status_code == 200
    page1 = resp.json()

    # Then: pagination reflects filtered total and results are enabled only
    assert page1["pagination"]["total"] == 2
    assert page1["pagination"]["has_more"] is True
    assert len(page1["controls"]) == 1
    assert page1["controls"][0]["enabled"] is True
    assert "Match-" in page1["controls"][0]["name"]

    # When: fetching next page with cursor
    resp2 = client.get(
        "/api/v1/controls",
        params={
            "name": "match",
            "enabled": "true",
            "limit": 1,
            "cursor": page1["pagination"]["next_cursor"],
        },
    )
    assert resp2.status_code == 200
    page2 = resp2.json()

    # Then: second enabled control is returned and pagination ends
    assert page2["pagination"]["has_more"] is False
    assert len(page2["controls"]) == 1
    assert page2["controls"][0]["enabled"] is True


def test_list_controls_includes_used_by_agent_mapping(client: TestClient) -> None:
    # Given: one control linked through Policy -> Agent
    control_id, control_name = _create_control(client, name=f"Mapped-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    policy_name = f"pol-{uuid.uuid4()}"
    policy_resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert policy_resp.status_code == 200
    policy_id = policy_resp.json()["policy_id"]

    assoc_resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc_resp.status_code == 200

    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert init_resp.status_code == 200

    assign_resp = client.post(f"/api/v1/agents/{agent_name}/policy/{policy_id}")
    assert assign_resp.status_code == 200

    # When: listing controls
    resp = client.get("/api/v1/controls", params={"name": "mapped"})
    assert resp.status_code == 200
    controls = resp.json()["controls"]

    # Then: used_by_agent is populated from the join traversal
    assert len(controls) == 1
    assert controls[0]["id"] == control_id
    assert controls[0]["name"] == control_name
    assert controls[0]["used_by_agent"] == {"agent_name": agent_name}


def test_delete_control_force_dissociates(client: TestClient) -> None:
    # Given: a control associated with a policy
    control_id, _ = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    _set_control_data(client, control_id, data)

    policy_name = f"pol-{uuid.uuid4()}"
    policy_resp = client.put("/api/v1/policies", json={"name": policy_name})
    assert policy_resp.status_code == 200
    policy_id = policy_resp.json()["policy_id"]

    assoc_resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert assoc_resp.status_code == 200

    # When: deleting without force
    resp = client.delete(f"/api/v1/controls/{control_id}")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONTROL_IN_USE"

    # When: deleting with force
    resp2 = client.delete(f"/api/v1/controls/{control_id}?force=true")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["success"] is True
    assert policy_id in body.get("dissociated_from", [])

    # Then: policy no longer lists the control
    list_resp = client.get(f"/api/v1/policies/{policy_id}/controls")
    assert list_resp.status_code == 200
    assert control_id not in list_resp.json()["control_ids"]

    # And: the deleted control is hidden from active lookups
    get_resp = client.get(f"/api/v1/controls/{control_id}")
    assert get_resp.status_code == 404


def test_delete_control_force_dissociates_direct_agent_links(client: TestClient) -> None:
    # Given: a control directly associated with an agent
    control_id, control_name = _create_control(client)
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert init_resp.status_code == 200

    assoc_resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert assoc_resp.status_code == 200

    # When: force-deleting the control
    resp = client.delete(f"/api/v1/controls/{control_id}?force=true")
    assert resp.status_code == 200
    body = resp.json()

    # Then: direct agent dissociation details are returned
    assert body["success"] is True
    assert body.get("dissociated_from_policies", []) == []
    assert body.get("dissociated_from_agents", []) == [agent_name]

    # And: the deleted control no longer appears in list results
    list_resp = client.get("/api/v1/controls", params={"name": control_name})
    assert list_resp.status_code == 200
    assert list_resp.json()["controls"] == []
    assert list_resp.json()["pagination"]["total"] == 0


def _create_target_binding(
    client: TestClient,
    *,
    control_id: int,
    target_type: str = "env",
    target_id: str = "prod",
    enabled: bool = True,
) -> int:
    resp = client.put(
        "/api/v1/control-bindings",
        json={
            "target_type": target_type,
            "target_id": target_id,
            "control_id": control_id,
            "enabled": enabled,
        },
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["binding_id"])


def test_list_controls_returns_null_attachments_by_default(
    client: TestClient,
) -> None:
    control_id, control_name = _create_control(client, name=f"Attachments-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    resp = client.get("/api/v1/controls", params={"name": control_name})

    assert resp.status_code == 200, resp.text
    controls = resp.json()["controls"]
    assert len(controls) == 1
    assert controls[0]["id"] == control_id
    assert controls[0]["attachments"] is None


def test_list_controls_filters_by_target_attachment_before_pagination(
    client: TestClient,
) -> None:
    prefix = f"AttachmentFilter-{uuid.uuid4()}"
    target_id = f"ls-{uuid.uuid4()}"
    matching_control_id, _ = _create_control(client, name=f"{prefix}-matching")
    _set_control_data(client, matching_control_id, deepcopy(VALID_CONTROL_PAYLOAD))
    matching_binding_id = _create_target_binding(
        client,
        control_id=matching_control_id,
        target_type="log_stream",
        target_id=target_id,
    )

    newer_unmatched_control_id, _ = _create_control(client, name=f"{prefix}-unmatched")
    _set_control_data(client, newer_unmatched_control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    resp = client.get(
        "/api/v1/controls",
        params={
            "name": prefix,
            "include_attachments": "true",
            "attachment_target_type": "log_stream",
            "attachment_target_id": target_id,
            "limit": 1,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pagination"]["total"] == 1
    assert body["pagination"]["has_more"] is False
    controls = body["controls"]
    assert len(controls) == 1
    assert controls[0]["id"] == matching_control_id
    assert controls[0]["id"] != newer_unmatched_control_id
    assert controls[0]["attachments"]["targets"] == [
        {
            "binding_id": matching_binding_id,
            "target_type": "log_stream",
            "target_id": target_id,
            "enabled": True,
        }
    ]
    assert controls[0]["attachments"]["targets_total"] == 1
    assert controls[0]["attachments"]["targets_truncated"] is False


def test_list_controls_expands_filtered_control_attachments(
    client: TestClient,
) -> None:
    control_id, control_name = _create_control(client, name=f"Attachments-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    policy_resp = client.put("/api/v1/policies", json={"name": f"pol-{uuid.uuid4()}"})
    assert policy_resp.status_code == 200
    policy_id = policy_resp.json()["policy_id"]
    policy_assoc_resp = client.post(f"/api/v1/policies/{policy_id}/controls/{control_id}")
    assert policy_assoc_resp.status_code == 200

    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    init_resp = client.post(
        "/api/v1/agents/initAgent",
        json={"agent": {"agent_name": agent_name}, "steps": []},
    )
    assert init_resp.status_code == 200
    agent_assoc_resp = client.post(f"/api/v1/agents/{agent_name}/controls/{control_id}")
    assert agent_assoc_resp.status_code == 200

    included_binding_id = _create_target_binding(
        client,
        control_id=control_id,
        target_type="log_stream",
        target_id="ls-prod",
        enabled=False,
    )
    _create_target_binding(
        client,
        control_id=control_id,
        target_type="log_stream",
        target_id="ls-dev",
    )
    _create_target_binding(
        client,
        control_id=control_id,
        target_type="environment",
        target_id="prod",
    )

    resp = client.get(
        "/api/v1/controls",
        params={
            "name": control_name,
            "include_attachments": "true",
            "attachment_target_type": "log_stream",
            "attachment_target_id": "ls-prod",
        },
    )

    assert resp.status_code == 200, resp.text
    controls = resp.json()["controls"]
    assert len(controls) == 1
    assert controls[0]["attachments"] == {
        "agents": [{"agent_name": agent_name}],
        "policies": [{"policy_id": policy_id}],
        "targets": [
            {
                "binding_id": included_binding_id,
                "target_type": "log_stream",
                "target_id": "ls-prod",
                "enabled": False,
            }
        ],
        "targets_total": 1,
        "targets_truncated": False,
    }


def test_list_controls_caps_inline_target_attachments(
    client: TestClient,
) -> None:
    control_id, control_name = _create_control(client, name=f"Attachments-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))
    binding_ids = [
        _create_target_binding(
            client,
            control_id=control_id,
            target_type="log_stream",
            target_id=f"ls-{index}",
        )
        for index in range(25)
    ]

    resp = client.get(
        "/api/v1/controls",
        params={
            "name": control_name,
            "include_attachments": "true",
        },
    )

    assert resp.status_code == 200, resp.text
    attachments = resp.json()["controls"][0]["attachments"]
    assert len(attachments["targets"]) == 20
    assert attachments["targets_total"] == 25
    assert attachments["targets_truncated"] is True
    assert [target["binding_id"] for target in attachments["targets"]] == list(
        reversed(binding_ids[-20:])
    )


def test_list_controls_omits_targets_without_binding_read_authorization(
    client: TestClient,
) -> None:
    control_id, control_name = _create_control(client, name=f"Attachments-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))
    _create_target_binding(
        client,
        control_id=control_id,
        target_type="log_stream",
        target_id="ls-prod",
    )
    calls: list[tuple[Operation, dict[str, Any] | None]] = []

    class BindingReadDenyAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            calls.append((operation, context))
            if operation == Operation.CONTROL_BINDINGS_READ:
                raise ForbiddenError(
                    error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                    detail="No target read access.",
                )
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(BindingReadDenyAuthorizer())

    resp = client.get(
        "/api/v1/controls",
        params={
            "name": control_name,
            "include_attachments": "true",
        },
    )

    assert resp.status_code == 200, resp.text
    controls = resp.json()["controls"]
    assert controls[0]["attachments"] == {
        "agents": [],
        "policies": [],
        "targets": [],
        "targets_total": 0,
        "targets_truncated": False,
    }
    assert (Operation.CONTROL_BINDINGS_READ, {}) in calls


def test_list_controls_omits_targets_when_broad_binding_read_upstream_rejects(
    client: TestClient,
) -> None:
    control_id, control_name = _create_control(client, name=f"Attachments-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))
    _create_target_binding(
        client,
        control_id=control_id,
        target_type="log_stream",
        target_id="ls-prod",
    )
    calls: list[tuple[Operation, dict[str, Any] | None]] = []

    class BindingReadRejectAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            calls.append((operation, context))
            if operation == Operation.CONTROL_BINDINGS_READ:
                raise APIError(
                    status_code=502,
                    error_code=ErrorCode.AUTH_UPSTREAM_REJECTED,
                    reason=ErrorReason.INTERNAL_ERROR,
                    detail="Authorization service rejected the authorization check.",
                )
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(BindingReadRejectAuthorizer())

    resp = client.get(
        "/api/v1/controls",
        params={
            "name": control_name,
            "include_attachments": "true",
        },
    )

    assert resp.status_code == 200, resp.text
    controls = resp.json()["controls"]
    assert controls[0]["attachments"] == {
        "agents": [],
        "policies": [],
        "targets": [],
        "targets_total": 0,
        "targets_truncated": False,
    }
    assert (Operation.CONTROL_BINDINGS_READ, {}) in calls


def test_list_controls_rejects_target_filter_without_binding_read_authorization(
    client: TestClient,
) -> None:
    control_id, control_name = _create_control(client, name=f"Attachments-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))
    _create_target_binding(
        client,
        control_id=control_id,
        target_type="log_stream",
        target_id="ls-prod",
    )
    calls: list[tuple[Operation, dict[str, Any] | None]] = []

    class BindingReadDenyAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            calls.append((operation, context))
            if operation == Operation.CONTROL_BINDINGS_READ:
                raise ForbiddenError(
                    error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                    detail="No target read access.",
                )
            return Principal(namespace_key=DEFAULT_NAMESPACE_KEY, is_admin=True)

    set_authorizer(BindingReadDenyAuthorizer())

    resp = client.get(
        "/api/v1/controls",
        params={
            "name": control_name,
            "include_attachments": "true",
            "attachment_target_type": "log_stream",
            "attachment_target_id": "ls-prod",
        },
    )

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "AUTH_INSUFFICIENT_PRIVILEGES"
    assert (
        Operation.CONTROL_BINDINGS_READ,
        {"target_type": "log_stream", "target_id": "ls-prod"},
    ) in calls


def test_list_controls_rejects_attachment_namespace_mismatch(
    client: TestClient,
) -> None:
    control_id, control_name = _create_control(client, name=f"Attachments-{uuid.uuid4()}")
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))

    class MismatchedBindingReadAuthorizer:
        async def authorize(
            self,
            request: Any,
            operation: Operation,
            context: dict[str, Any] | None = None,
        ) -> Principal:
            namespace_key = (
                "other-namespace"
                if operation == Operation.CONTROL_BINDINGS_READ
                else DEFAULT_NAMESPACE_KEY
            )
            return Principal(namespace_key=namespace_key, is_admin=True)

    set_authorizer(MismatchedBindingReadAuthorizer())

    resp = client.get(
        "/api/v1/controls",
        params={
            "name": control_name,
            "include_attachments": "true",
        },
    )

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "AUTH_INSUFFICIENT_PRIVILEGES"


def test_list_controls_rejects_attachment_filters_without_expansion(
    client: TestClient,
) -> None:
    resp = client.get(
        "/api/v1/controls",
        params={"attachment_target_type": "log_stream"},
    )

    assert resp.status_code == 422
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_delete_control_blocks_when_target_binding_exists(
    client: TestClient,
) -> None:
    # Given: a control attached via a target binding
    control_id, control_name = _create_control(client)
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))
    binding_id = _create_target_binding(client, control_id=control_id)

    # When: deleting without force
    resp = client.delete(f"/api/v1/controls/{control_id}")

    # Then: 409 with the binding listed as the in-use cause
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "CONTROL_IN_USE"
    binding_messages = [
        e for e in body.get("errors", []) if e.get("resource") == "ControlBinding"
    ]
    assert any(e.get("value") == binding_id for e in binding_messages)


def test_delete_control_force_detaches_target_bindings(
    client: TestClient,
) -> None:
    # Given: a control attached via a target binding
    control_id, control_name = _create_control(client)
    _set_control_data(client, control_id, deepcopy(VALID_CONTROL_PAYLOAD))
    binding_id = _create_target_binding(client, control_id=control_id)

    # When: force-deleting the control
    resp = client.delete(f"/api/v1/controls/{control_id}?force=true")

    # Then: success and the detached binding ID is returned
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body.get("detached_target_bindings", []) == [binding_id]

    # And: the binding no longer exists
    fetch = client.get(f"/api/v1/control-bindings/{binding_id}")
    assert fetch.status_code == 404


def test_create_control_allows_reusing_soft_deleted_name(client: TestClient) -> None:
    # Given: a control name that has been soft-deleted
    name = f"control-{uuid.uuid4()}"
    original_id, _ = _create_control(client, name=name)

    delete_resp = client.delete(f"/api/v1/controls/{original_id}", params={"force": True})
    assert delete_resp.status_code == 200

    # When: creating a new control with the same name
    recreate_resp = client.put("/api/v1/controls", json={"name": name, "data": VALID_CONTROL_PAYLOAD})

    # Then: creation succeeds because uniqueness only applies to active rows
    assert recreate_resp.status_code == 200, recreate_resp.text
    assert recreate_resp.json()["control_id"] != original_id


def test_patch_control_rename_allows_soft_deleted_name(client: TestClient) -> None:
    # Given: a soft-deleted control name and a separate active control
    deleted_name = f"control-{uuid.uuid4()}"
    deleted_id, _ = _create_control(client, name=deleted_name)
    delete_resp = client.delete(f"/api/v1/controls/{deleted_id}", params={"force": True})
    assert delete_resp.status_code == 200

    control_id, _ = _create_control(client)

    # When: renaming the active control to the deleted control's name
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"name": deleted_name})

    # Then: rename succeeds
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == deleted_name


def test_get_control_corrupted_data_returns_422(client: TestClient) -> None:
    # Given: a control with corrupted data in DB
    control_id, _ = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: fetching the control
    resp = client.get(f"/api/v1/controls/{control_id}")

    # Then: corrupted-data validation is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "CORRUPTED_DATA"


def test_get_control_data_corrupted_returns_422(client: TestClient) -> None:
    # Given: a control with corrupted data in DB
    control_id, _ = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: fetching control data
    resp = client.get(f"/api/v1/controls/{control_id}/data")

    # Then: validation error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "CORRUPTED_DATA"


def test_patch_control_enabled_with_corrupted_data(client: TestClient) -> None:
    # Given: a control with corrupted data in DB
    control_id, _ = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: toggling enabled
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": False})

    # Then: corrupted data error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "CORRUPTED_DATA"
    assert "ValidationError" not in resp.text


def test_set_control_data_agent_scoped_agent_not_found(client: TestClient) -> None:
    # Given: a control
    control_id, _ = _create_control(client)

    # When: setting data with a missing agent in evaluator ref
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {"name": "missing-agent:custom", "config": {"pattern": "x"}}
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: not found
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "AGENT_NOT_FOUND"


def test_set_control_data_agent_scoped_evaluator_missing(client: TestClient) -> None:
    # Given: an agent without the referenced evaluator
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name, "agent_name": agent_name},
            "steps": [],
            "evaluators": [],
        },
    )
    assert resp.status_code == 200

    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {"name": f"{agent_name}:missing", "config": {"pattern": "x"}}

    # When: setting data with evaluator not registered on agent
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: validation error
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "EVALUATOR_NOT_FOUND"
    assert any(err.get("field") == "data.condition.evaluator.name" for err in body.get("errors", []))


def test_set_control_data_agent_scoped_invalid_schema(client: TestClient) -> None:
    # Given: an agent with evaluator schema requiring "pattern"
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name, "agent_name": agent_name},
            "steps": [],
            "evaluators": [
                {
                    "name": "custom",
                    "description": "custom",
                    "config_schema": {
                        "type": "object",
                        "properties": {"pattern": {"type": "string"}},
                        "required": ["pattern"],
                    },
                }
            ],
        },
    )
    assert resp.status_code == 200

    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {"name": f"{agent_name}:custom", "config": {}}

    # When: setting data with config missing required fields
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: invalid config error
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "INVALID_CONFIG"
    assert any(err.get("field") == "data.condition.evaluator.config" for err in body.get("errors", []))


def test_patch_control_updates_name_and_enabled(client: TestClient) -> None:
    # Given: a control with configured data
    control_id, _ = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    data["enabled"] = True
    _set_control_data(client, control_id, data)

    # When: updating name and enabled status
    new_name = f"control-{uuid.uuid4()}"
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": new_name, "enabled": False},
    )

    # Then: patch succeeds with updated fields
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == new_name
    assert body["enabled"] is False

    # And: stored data reflects enabled=false
    get_resp = client.get(f"/api/v1/controls/{control_id}/data")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["enabled"] is False


def test_patch_control_not_found_returns_404(client: TestClient) -> None:
    # Given: a non-existent control id
    missing_id = 999999

    # When: patching the control
    resp = client.patch(f"/api/v1/controls/{missing_id}", json={"enabled": True})

    # Then: not found error is returned
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_delete_control_not_found_returns_404(client: TestClient) -> None:
    # Given: a non-existent control id
    missing_id = 999999

    # When: deleting the control
    resp = client.delete(f"/api/v1/controls/{missing_id}")

    # Then: not found error is returned
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "CONTROL_NOT_FOUND"


def test_set_control_data_agent_scoped_corrupted_agent_data_returns_422(
    client: TestClient,
) -> None:
    # Given: an agent whose stored data is corrupted
    agent_name = f"agent-{uuid.uuid4().hex[:12]}"
    agent_name = agent_name
    resp = client.post(
        "/api/v1/agents/initAgent",
        json={
            "agent": {"agent_name": agent_name, "agent_name": agent_name},
            "steps": [],
            "evaluators": [{"name": "custom", "config_schema": {"type": "object"}}],
        },
    )
    assert resp.status_code == 200

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE agents SET data = CAST(:data AS JSONB) WHERE name = :id"),
            {"data": json.dumps({"bad": "data"}), "id": agent_name},
        )

    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {"name": f"{agent_name}:custom", "config": {}}

    # When: setting control data referencing the corrupted agent's evaluator
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: corrupted agent data error is returned
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "CORRUPTED_DATA"


def test_set_control_data_unknown_evaluator_allowed(client: TestClient) -> None:
    # Given: a control with a non-registered evaluator name
    control_id, _ = _create_control(client)
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {"name": "unknown-eval", "config": {}}

    # When: setting the control data
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: update succeeds (unknown evaluators are allowed)
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_set_control_data_builtin_evaluator_validation_error(
    client: TestClient, monkeypatch
) -> None:
    # Given: a control and a server-side evaluator that enforces a schema
    control_id, _ = _create_control(client)

    class DummyEvaluator:
        config_model = RegexEvaluatorConfig

    monkeypatch.setattr(
        controls_module,
        "list_evaluators",
        lambda: {"dummy": DummyEvaluator},
    )

    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {"name": "dummy", "config": {}}

    # When: setting control data with invalid config
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: invalid config error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "INVALID_CONFIG"
    assert any(
        "data.condition.evaluator.config" in err.get("field", "")
        for err in body.get("errors", [])
    )


def test_set_control_data_builtin_evaluator_invalid_parameters(
    client: TestClient, monkeypatch
) -> None:
    # Given: a control and a server-side evaluator that raises TypeError
    control_id, _ = _create_control(client)

    class DummyEvaluator:
        @staticmethod
        def config_model(**_kwargs):  # type: ignore[no-untyped-def]
            raise TypeError("unexpected parameter")

    monkeypatch.setattr(
        controls_module,
        "list_evaluators",
        lambda: {"dummy": DummyEvaluator},
    )

    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["condition"]["evaluator"] = {"name": "dummy", "config": {"unexpected": "value"}}

    # When: setting control data with invalid parameters
    resp = client.put(f"/api/v1/controls/{control_id}/data", json={"data": payload})

    # Then: invalid parameters error is returned
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_code"] == "INVALID_CONFIG"
    assert any(err.get("code") == "invalid_parameters" for err in body.get("errors", []))
    assert any(
        err.get("message") == "Invalid config parameters for evaluator."
        for err in body.get("errors", [])
    )
    assert "unexpected parameter" not in resp.text


@pytest.mark.asyncio
async def test_set_control_data_selector_without_model_dump_uses_original_serialization(
    async_db,
) -> None:
    # Given: a control and a request whose selector cannot be re-dumped
    control = Control(name=f"control-{uuid.uuid4()}", data=None)
    async_db.add(control)
    await async_db.flush()

    payload = deepcopy(VALID_CONTROL_PAYLOAD)

    class DummyData:
        def __init__(self, data: dict[str, object]) -> None:
            self._data = data
            self.condition = ConditionNode.model_validate(data["condition"])

        def model_dump(self, *args: object, **kwargs: object) -> dict[str, object]:
            return self._data

    request = SimpleNamespace(data=DummyData(payload))

    # When: updating the control data with a non-Pydantic selector
    response = await controls_module.set_control_data(
        control.id,
        request,
        async_db,
        principal=Principal(namespace_key=DEFAULT_NAMESPACE_KEY),
    )

    # Then: the update succeeds and uses the original selector serialization
    assert response.success is True
    await async_db.refresh(control)
    assert control.data["condition"] == payload["condition"]


def test_patch_control_rename_preserves_enabled(client: TestClient) -> None:
    # Given: a control with enabled=false in its data
    control_id, control_name = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    data["enabled"] = False
    _set_control_data(client, control_id, data)

    # When: renaming the control without providing enabled
    new_name = f"{control_name}-renamed"
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"name": new_name})

    # Then: response preserves enabled status
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == new_name
    assert body["enabled"] is False


def test_patch_control_enabled_preserves_extra_fields(client: TestClient) -> None:
    # Given: a control with extra metadata in stored data
    control_id, _ = _create_control(client)
    data = deepcopy(VALID_CONTROL_PAYLOAD)
    _set_control_data(client, control_id, data)

    data_with_extra = deepcopy(data)
    data_with_extra["custom_meta"] = {"source": "unit-test"}
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps(data_with_extra), "id": control_id},
        )

    # When: toggling enabled via PATCH
    resp = client.patch(f"/api/v1/controls/{control_id}", json={"enabled": False})

    # Then: enabled is updated and extra fields are preserved
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    with Session(engine) as session:
        control = session.query(Control).filter(Control.id == control_id).first()
        assert control is not None
        assert control.data.get("custom_meta") == {"source": "unit-test"}


def test_patch_control_rename_with_corrupted_data_returns_422(
    client: TestClient,
) -> None:
    # Given: a control with corrupted data in DB
    control_id, control_name = _create_control(client)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE controls SET data = CAST(:data AS JSONB) WHERE id = :id"),
            {"data": json.dumps({"bad": "data"}), "id": control_id},
        )

    # When: renaming the control without enabled
    resp = client.patch(
        f"/api/v1/controls/{control_id}",
        json={"name": f"{control_name}-renamed"},
    )

    # Then: corrupted-data validation is returned
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "CORRUPTED_DATA"
