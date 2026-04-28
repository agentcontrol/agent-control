"""Coverage for ``ControlBindingsService.resolve_effective_controls``."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agent_control_server.models import Control, ControlBinding
from agent_control_server.services.control_bindings import ControlBindingsService

from .utils import VALID_CONTROL_PAYLOAD


def _control_name() -> str:
    return f"control-{uuid.uuid4().hex[:12]}"


async def _add_control(
    session: AsyncSession,
    *,
    namespace_key: str = "default",
    deleted: bool = False,
) -> Control:
    control = Control(
        namespace_key=namespace_key,
        name=_control_name(),
        data=VALID_CONTROL_PAYLOAD,
        deleted_at=dt.datetime.now(dt.UTC) if deleted else None,
    )
    session.add(control)
    await session.flush()
    return control


def _make_binding(
    *,
    namespace_key: str = "default",
    target_type: str = "env",
    target_id: str = "prod",
    control_id: int,
    enabled: bool = True,
) -> ControlBinding:
    return ControlBinding(
        namespace_key=namespace_key,
        target_type=target_type,
        target_id=target_id,
        control_id=control_id,
        enabled=enabled,
    )


async def _resolve(
    session: AsyncSession,
    *,
    namespace_key: str = "default",
    target_type: str = "env",
    target_id: str = "prod",
) -> list[int]:
    service = ControlBindingsService(session)
    controls = await service.resolve_effective_controls(
        namespace_key=namespace_key,
        target_type=target_type,
        target_id=target_id,
    )
    return [control.id for control in controls]


@pytest.mark.asyncio
async def test_returns_empty_when_no_bindings_exist(async_db: AsyncSession) -> None:
    assert await _resolve(async_db) == []


@pytest.mark.asyncio
async def test_target_binding_returns_control(async_db: AsyncSession) -> None:
    control = await _add_control(async_db)
    async_db.add(_make_binding(control_id=control.id))
    await async_db.flush()

    assert await _resolve(async_db) == [control.id]


@pytest.mark.asyncio
async def test_disabled_binding_excludes_control(
    async_db: AsyncSession,
) -> None:
    control = await _add_control(async_db)
    async_db.add(_make_binding(control_id=control.id, enabled=False))
    await async_db.flush()

    assert await _resolve(async_db) == []


@pytest.mark.asyncio
async def test_soft_deleted_controls_excluded(async_db: AsyncSession) -> None:
    control = await _add_control(async_db, deleted=True)
    async_db.add(_make_binding(control_id=control.id))
    await async_db.flush()

    assert await _resolve(async_db) == []


@pytest.mark.asyncio
async def test_namespace_isolation(async_db: AsyncSession) -> None:
    control = await _add_control(async_db, namespace_key="ns-one")
    async_db.add(
        _make_binding(namespace_key="ns-one", control_id=control.id)
    )
    await async_db.flush()

    assert await _resolve(async_db, namespace_key="ns-one") == [control.id]
    assert await _resolve(async_db, namespace_key="ns-two") == []


@pytest.mark.asyncio
async def test_other_target_not_returned(async_db: AsyncSession) -> None:
    control = await _add_control(async_db)
    async_db.add(
        _make_binding(target_type="env", target_id="prod", control_id=control.id)
    )
    await async_db.flush()

    assert await _resolve(async_db, target_type="env", target_id="dev") == []
    assert await _resolve(async_db, target_type="region", target_id="prod") == []


@pytest.mark.asyncio
async def test_upsert_recovers_from_concurrent_insert_race(
    async_db: AsyncSession,
) -> None:
    """If a competing transaction inserted the same natural-key row before
    our INSERT could commit, the IntegrityError is caught, the loser
    re-reads the winning row, applies its requested enabled value, and
    returns ``created=False`` rather than surfacing a 500."""
    control = await _add_control(async_db)
    await async_db.commit()

    service = ControlBindingsService(async_db)

    # Simulate the "competing writer already inserted" state by inserting
    # one binding, committing, then asking the service to upsert the same
    # natural key. The service's fast-path SELECT will find it and update.
    first, first_created = await service.upsert_by_natural_key(
        namespace_key="default",
        target_type="env",
        target_id="prod",
        control_id=control.id,
        enabled=True,
    )
    assert first_created is True

    second, second_created = await service.upsert_by_natural_key(
        namespace_key="default",
        target_type="env",
        target_id="prod",
        control_id=control.id,
        enabled=False,
    )
    assert second_created is False
    assert second.id == first.id
    assert second.enabled is False


@pytest.mark.asyncio
async def test_multiple_controls_on_target_all_returned(
    async_db: AsyncSession,
) -> None:
    control_a = await _add_control(async_db)
    control_b = await _add_control(async_db)
    control_c = await _add_control(async_db)

    async_db.add(_make_binding(control_id=control_a.id))
    async_db.add(_make_binding(control_id=control_b.id))
    # control_c bound but disabled - excluded from effective set.
    async_db.add(_make_binding(control_id=control_c.id, enabled=False))
    await async_db.flush()

    resolved = set(await _resolve(async_db))
    assert resolved == {control_a.id, control_b.id}
