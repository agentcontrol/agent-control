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
    agent_name: str | None = None,
    enabled: bool = True,
) -> ControlBinding:
    return ControlBinding(
        namespace_key=namespace_key,
        target_type=target_type,
        target_id=target_id,
        agent_name=agent_name,
        control_id=control_id,
        enabled=enabled,
    )


async def _resolve(
    session: AsyncSession,
    *,
    namespace_key: str = "default",
    target_type: str = "env",
    target_id: str = "prod",
    agent_name: str | None = None,
) -> list[int]:
    service = ControlBindingsService(session)
    controls = await service.resolve_effective_controls(
        namespace_key=namespace_key,
        target_type=target_type,
        target_id=target_id,
        agent_name=agent_name,
    )
    return [control.id for control in controls]


@pytest.mark.asyncio
async def test_returns_empty_when_no_bindings_exist(async_db: AsyncSession) -> None:
    assert await _resolve(async_db) == []


@pytest.mark.asyncio
async def test_target_default_binding_returns_control(
    async_db: AsyncSession,
) -> None:
    control = await _add_control(async_db)
    async_db.add(_make_binding(control_id=control.id))
    await async_db.flush()

    assert await _resolve(async_db) == [control.id]


@pytest.mark.asyncio
async def test_target_default_returned_even_without_request_agent(
    async_db: AsyncSession,
) -> None:
    control = await _add_control(async_db)
    async_db.add(_make_binding(control_id=control.id))
    await async_db.flush()

    assert await _resolve(async_db, agent_name=None) == [control.id]


@pytest.mark.asyncio
async def test_agent_override_alone_not_returned_for_other_agent(
    async_db: AsyncSession,
) -> None:
    control = await _add_control(async_db)
    async_db.add(
        _make_binding(control_id=control.id, agent_name="support-router")
    )
    await async_db.flush()

    # Different agent - no binding applies.
    assert await _resolve(async_db, agent_name="other-agent") == []


@pytest.mark.asyncio
async def test_agent_override_returned_for_matching_agent(
    async_db: AsyncSession,
) -> None:
    control = await _add_control(async_db)
    async_db.add(
        _make_binding(control_id=control.id, agent_name="support-router")
    )
    await async_db.flush()

    assert await _resolve(async_db, agent_name="support-router") == [control.id]


@pytest.mark.asyncio
async def test_agent_disable_overrides_target_default(
    async_db: AsyncSession,
) -> None:
    control = await _add_control(async_db)
    async_db.add(_make_binding(control_id=control.id, enabled=True))
    async_db.add(
        _make_binding(
            control_id=control.id,
            agent_name="support-router",
            enabled=False,
        )
    )
    await async_db.flush()

    # Target-default would include the control; the agent-specific exemption
    # wins because it is more specific.
    assert (
        await _resolve(async_db, agent_name="support-router")
    ) == []
    # A different agent in the same target still gets the default.
    assert (
        await _resolve(async_db, agent_name="other-agent")
    ) == [control.id]


@pytest.mark.asyncio
async def test_agent_enable_overrides_target_disabled(
    async_db: AsyncSession,
) -> None:
    control = await _add_control(async_db)
    async_db.add(_make_binding(control_id=control.id, enabled=False))
    async_db.add(
        _make_binding(
            control_id=control.id,
            agent_name="support-router",
            enabled=True,
        )
    )
    await async_db.flush()

    assert (
        await _resolve(async_db, agent_name="support-router")
    ) == [control.id]


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
async def test_multiple_controls_mixed_shapes(async_db: AsyncSession) -> None:
    control_a = await _add_control(async_db)
    control_b = await _add_control(async_db)
    control_c = await _add_control(async_db)

    # control_a: target-default only.
    async_db.add(_make_binding(control_id=control_a.id))
    # control_b: target-default + agent disable for support-router.
    async_db.add(_make_binding(control_id=control_b.id))
    async_db.add(
        _make_binding(
            control_id=control_b.id,
            agent_name="support-router",
            enabled=False,
        )
    )
    # control_c: agent-only attachment for support-router.
    async_db.add(
        _make_binding(control_id=control_c.id, agent_name="support-router")
    )
    await async_db.flush()

    # support-router: a (default), c (agent attachment); b is exempted.
    by_agent = set(
        await _resolve(async_db, agent_name="support-router")
    )
    assert by_agent == {control_a.id, control_c.id}

    # other agent: a, b (defaults).
    by_other = set(await _resolve(async_db, agent_name="other-agent"))
    assert by_other == {control_a.id, control_b.id}

    # no agent context: only target-defaults; a and b apply.
    by_no_agent = set(await _resolve(async_db))
    assert by_no_agent == {control_a.id, control_b.id}
