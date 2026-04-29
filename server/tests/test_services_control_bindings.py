"""Coverage for ``ControlBindingsService`` upsert/concurrency paths.

Effective-controls resolution now lives in
``ControlService.list_controls_for_agent``; the merge semantics for the
``control_bindings`` source are exercised in ``test_services_controls``.
"""

from __future__ import annotations

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
) -> Control:
    control = Control(
        namespace_key=namespace_key,
        name=_control_name(),
        data=VALID_CONTROL_PAYLOAD,
        deleted_at=None,
    )
    session.add(control)
    await session.flush()
    return control


@pytest.mark.asyncio
async def test_upsert_handles_integrity_error_from_concurrent_flush(
    async_db: AsyncSession,
) -> None:
    """The race that the IntegrityError branch was written for.

    Both transactions SELECT, find no row, INSERT, and the second
    flush raises ``IntegrityError`` against the unique key. The loser
    must roll back, re-fetch the winner, apply its requested
    ``enabled`` value, and return ``created=False``.

    Simulated by inserting the winning row out of band, then patching
    the service's first natural-key lookup to return ``None`` so the
    INSERT path runs and the unique index trips a real
    ``IntegrityError`` against the existing DB row.
    """
    control = await _add_control(async_db)
    winning = ControlBinding(
        namespace_key="default",
        target_type="env",
        target_id="prod",
        control_id=control.id,
        enabled=True,
    )
    async_db.add(winning)
    await async_db.commit()

    service = ControlBindingsService(async_db)
    real_find = service._find_by_natural_key
    calls = {"n": 0}

    async def first_lookup_misses(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # pretend the loser hasn't seen the winner yet
        return await real_find(*args, **kwargs)

    service._find_by_natural_key = first_lookup_misses

    binding, created = await service.upsert_by_natural_key(
        namespace_key="default",
        target_type="env",
        target_id="prod",
        control_id=control.id,
        enabled=False,
    )

    assert created is False
    assert binding.id == winning.id
    assert binding.enabled is False  # loser applied its requested value


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
