"""ORM round-trip coverage for the target schema.

Also provides a behavior-preservation smoke assertion confirming that
existing writes (Agent/Control/Policy created without tenant context) still
land in the synthetic default tenant via the ORM-level default.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_control_server.models import (
    DEFAULT_TENANT_ID,
    Agent,
    Control,
    Policy,
    Target,
    TargetControl,
)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def test_target_roundtrip_populates_defaults(async_db: AsyncSession) -> None:
    target = Target(
        target_type="environment",
        external_id=_unique("ls"),
        name="production",
    )
    async_db.add(target)
    await async_db.commit()
    await async_db.refresh(target)

    fetched = (
        await async_db.execute(select(Target).where(Target.id == target.id))
    ).scalar_one()

    assert fetched.tenant_id == DEFAULT_TENANT_ID
    assert fetched.target_type == "environment"
    assert fetched.data == {}
    assert fetched.created_at is not None


async def test_targets_unique_per_tenant_type_external_id(
    async_db: AsyncSession,
) -> None:
    external_id = _unique("ls")
    async_db.add(Target(target_type="environment", external_id=external_id))
    await async_db.commit()

    async_db.add(Target(target_type="environment", external_id=external_id))
    with pytest.raises(IntegrityError):
        await async_db.commit()
    await async_db.rollback()


async def test_target_control_roundtrip_defaults_enabled_true(
    async_db: AsyncSession,
) -> None:
    target = Target(target_type="environment", external_id=_unique("ls"))
    control = Control(name=_unique("control"), data={})
    async_db.add_all([target, control])
    await async_db.commit()

    attachment = TargetControl(target_id=target.id, control_id=control.id)
    async_db.add(attachment)
    await async_db.commit()
    await async_db.refresh(attachment)

    assert attachment.enabled is True
    assert attachment.created_at is not None


async def test_target_controls_unique_per_target_control(
    async_db: AsyncSession,
) -> None:
    target = Target(target_type="environment", external_id=_unique("ls"))
    control = Control(name=_unique("control"), data={})
    async_db.add_all([target, control])
    await async_db.commit()

    async_db.add(TargetControl(target_id=target.id, control_id=control.id))
    await async_db.commit()

    async_db.add(TargetControl(target_id=target.id, control_id=control.id))
    with pytest.raises(IntegrityError):
        await async_db.commit()
    await async_db.rollback()


async def test_target_delete_cascades_target_controls(
    async_db: AsyncSession,
) -> None:
    target = Target(target_type="environment", external_id=_unique("ls"))
    control = Control(name=_unique("control"), data={})
    async_db.add_all([target, control])
    await async_db.commit()

    async_db.add(TargetControl(target_id=target.id, control_id=control.id))
    await async_db.commit()

    await async_db.delete(target)
    await async_db.commit()

    remaining = (
        await async_db.execute(select(TargetControl).where(TargetControl.control_id == control.id))
    ).scalars().all()
    assert remaining == []


async def test_oss_agent_write_gets_default_tenant_without_explicit_input(
    async_db: AsyncSession,
) -> None:
    """Behavior-preservation smoke: existing OSS write path must not require tenant."""
    name = "oss-legacy-agent-01"
    async_db.add(Agent(name=name, data={}))
    await async_db.commit()

    agent = (
        await async_db.execute(select(Agent).where(Agent.name == name))
    ).scalar_one()
    assert agent.tenant_id == DEFAULT_TENANT_ID


async def test_oss_control_and_policy_writes_get_default_tenant(
    async_db: AsyncSession,
) -> None:
    control = Control(name=_unique("ctrl"), data={})
    policy = Policy(name=_unique("pol"))
    async_db.add_all([control, policy])
    await async_db.commit()
    await async_db.refresh(control)
    await async_db.refresh(policy)

    assert control.tenant_id == DEFAULT_TENANT_ID
    assert policy.tenant_id == DEFAULT_TENANT_ID
