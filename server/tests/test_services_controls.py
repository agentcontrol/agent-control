from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent_control_models.errors import ErrorCode
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from agent_control_server.errors import APIValidationError
from agent_control_server.models import (
    Agent,
    Control,
    ControlVersion,
    Policy,
    agent_controls,
    agent_policies,
    policy_controls,
)
from agent_control_server.services.controls import (
    ControlService,
)

from .conftest import AsyncSessionTest, engine
from .utils import VALID_CONTROL_PAYLOAD


def _unrendered_template_payload() -> dict[str, object]:
    return {
        "template": {
            "description": "Regex denial template",
            "parameters": {
                "pattern": {
                    "type": "regex_re2",
                    "label": "Pattern",
                },
            },
            "definition_template": {
                "description": "Template-backed control",
                "execution": "server",
                "scope": {"step_types": ["llm"], "stages": ["pre"]},
                "condition": {
                    "selector": {"path": "input"},
                    "evaluator": {
                        "name": "regex",
                        "config": {"pattern": {"$param": "pattern"}},
                    },
                },
                "action": {"decision": "deny"},
            },
        },
        "template_values": {},
    }


async def _create_versioned_control(
    *,
    name: str | None = None,
    data: dict[str, object] | None = None,
) -> tuple[int, str]:
    control_name = name or f"control-{uuid.uuid4()}"
    control_data = deepcopy(data) if data is not None else deepcopy(VALID_CONTROL_PAYLOAD)

    async with AsyncSessionTest() as session:
        service = ControlService(session)
        control = service.create_control(name=control_name, data=control_data)
        await service.create_version(
            control,
            event_type="created",
            note="Initial creation",
        )
        await session.commit()
        return control.id, control_name


def _fetch_control(control_id: int) -> Control | None:
    with Session(engine) as session:
        return session.scalars(select(Control).where(Control.id == control_id)).first()


def _fetch_control_by_name(name: str) -> Control | None:
    with Session(engine) as session:
        return session.scalars(select(Control).where(Control.name == name)).first()


def _fetch_versions(control_id: int) -> list[ControlVersion]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(ControlVersion)
                .where(ControlVersion.control_id == control_id)
                .order_by(ControlVersion.version_num)
            ).all()
        )


def _fetch_all_versions() -> list[ControlVersion]:
    with Session(engine) as session:
        return list(session.scalars(select(ControlVersion)).all())


@pytest.mark.asyncio
async def test_create_version_locks_control_row_before_allocating_version_number() -> None:
    # Given: a control service with a mocked session
    mock_session = AsyncMock(spec=AsyncSession)
    lock_result = MagicMock()
    version_lookup_result = MagicMock()
    version_lookup_result.scalar_one.return_value = 4
    mock_session.execute = AsyncMock(side_effect=[lock_result, version_lookup_result])
    mock_session.flush = AsyncMock()
    mock_session.add = MagicMock()

    service = ControlService(mock_session)
    control = Control(
        id=123,
        name=f"control-{uuid.uuid4()}",
        data=VALID_CONTROL_PAYLOAD,
        deleted_at=None,
    )

    # When: creating a new version row
    version = await service.create_version(control, event_type="updated", note="Edited")

    # Then: the service first takes a row-level lock on the control
    lock_stmt = mock_session.execute.await_args_list[0].args[0]
    assert getattr(lock_stmt, "_for_update_arg", None) is not None

    # And: the allocated version number comes from the subsequent query
    assert version.version_num == 4


@pytest.mark.asyncio
async def test_create_control_transaction_rollback_does_not_persist_control_or_version() -> None:
    # Given: a new control plus its initial version inside an open transaction
    control_name = f"control-{uuid.uuid4()}"
    async with AsyncSessionTest() as session:
        service = ControlService(session)
        control = service.create_control(
            name=control_name,
            data=deepcopy(VALID_CONTROL_PAYLOAD),
        )
        await service.create_version(
            control,
            event_type="created",
            note="Initial creation",
        )

        # When: the transaction is rolled back before commit
        await session.rollback()

    # Then: neither the control row nor the version row persist
    assert _fetch_control_by_name(control_name) is None
    assert _fetch_all_versions() == []


@pytest.mark.asyncio
async def test_replace_control_data_transaction_rollback_preserves_prior_state() -> None:
    # Given: a committed control with an initial version row
    control_id, _ = await _create_versioned_control()

    async with AsyncSessionTest() as session:
        service = ControlService(session)
        control = await service.get_active_control_or_404(control_id)
        updated_data = deepcopy(control.data)
        updated_data["description"] = "Should not persist"
        service.replace_control_data(control, data=updated_data)
        await service.create_version(
            control,
            event_type="updated",
            note="Edited",
        )

        # When: the edit transaction is rolled back
        await session.rollback()

    # Then: the persisted control state and version history remain unchanged
    persisted_control = _fetch_control(control_id)
    assert persisted_control is not None
    assert persisted_control.data["description"] == VALID_CONTROL_PAYLOAD["description"]
    assert [version.version_num for version in _fetch_versions(control_id)] == [1]


@pytest.mark.asyncio
async def test_patch_mutation_transaction_rollback_preserves_prior_state() -> None:
    # Given: a committed control with an initial version row
    control_id, control_name = await _create_versioned_control()

    async with AsyncSessionTest() as session:
        service = ControlService(session)
        control = await service.get_active_control_or_404(control_id)
        service.rename_control(control, name=f"{control_name}-renamed")
        service.set_control_enabled(control, enabled=False)
        await service.create_version(
            control,
            event_type="updated",
            note="Edited",
        )

        # When: the patch transaction is rolled back
        await session.rollback()

    # Then: the persisted control row and version history stay at the pre-patch state
    persisted_control = _fetch_control(control_id)
    assert persisted_control is not None
    assert persisted_control.name == control_name
    assert persisted_control.data["enabled"] is True
    assert [version.version_num for version in _fetch_versions(control_id)] == [1]


@pytest.mark.asyncio
async def test_delete_control_transaction_rollback_preserves_active_state() -> None:
    # Given: a committed control with an initial version row
    control_id, _ = await _create_versioned_control()

    async with AsyncSessionTest() as session:
        service = ControlService(session)
        control = await service.get_active_control_or_404(control_id)
        service.mark_control_deleted(control, deleted_at=dt.datetime.now(dt.UTC))
        await service.create_version(
            control,
            event_type="deleted",
            note="Deleted",
        )

        # When: the delete transaction is rolled back
        await session.rollback()

    # Then: the control remains active and no deleted version is persisted
    persisted_control = _fetch_control(control_id)
    assert persisted_control is not None
    assert persisted_control.deleted_at is None
    assert [version.version_num for version in _fetch_versions(control_id)] == [1]


@pytest.mark.asyncio
async def test_list_controls_for_policy_returns_controls(async_db) -> None:
    # Given: a policy with two associated controls
    policy = Policy(name=f"policy-{uuid.uuid4()}")
    control_a = Control(name=f"control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    control_b = Control(name=f"control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    async_db.add_all([policy, control_a, control_b])
    await async_db.flush()

    await async_db.execute(
        insert(policy_controls).values(
            [
                {"policy_id": policy.id, "control_id": control_a.id},
                {"policy_id": policy.id, "control_id": control_b.id},
            ]
        )
    )
    await async_db.commit()

    # When: listing controls for the policy
    controls = await ControlService(async_db).list_controls_for_policy(policy.id)

    # Then: both controls are returned
    names = {c.name for c in controls}
    assert names == {control_a.name, control_b.name}


@pytest.mark.asyncio
async def test_list_controls_for_policy_excludes_deleted_controls(async_db) -> None:
    # Given: a policy associated with one active and one soft-deleted control
    policy = Policy(name=f"policy-{uuid.uuid4()}")
    active_control = Control(name=f"control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    deleted_control = Control(
        name=f"deleted-control-{uuid.uuid4()}",
        data=VALID_CONTROL_PAYLOAD,
        deleted_at=dt.datetime.now(dt.UTC),
    )
    async_db.add_all([policy, active_control, deleted_control])
    await async_db.flush()

    await async_db.execute(
        insert(policy_controls).values(
            [
                {"policy_id": policy.id, "control_id": active_control.id},
                {"policy_id": policy.id, "control_id": deleted_control.id},
            ]
        )
    )
    await async_db.commit()

    # When: listing controls for the policy
    controls = await ControlService(async_db).list_controls_for_policy(policy.id)

    # Then: only active controls are returned
    assert [control.id for control in controls] == [active_control.id]


@pytest.mark.asyncio
async def test_list_controls_for_agent_returns_controls(async_db) -> None:
    # Given: an agent associated with one policy control and one direct control
    policy = Policy(name=f"policy-{uuid.uuid4()}")
    policy_control = Control(name=f"policy-control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    direct_control = Control(name=f"direct-control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    agent = Agent(
        name=f"agent-{uuid.uuid4()}",
        data={},
    )
    async_db.add_all([policy, policy_control, direct_control, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_policies).values({"agent_name": agent.name, "policy_id": policy.id})
    )
    await async_db.execute(
        insert(policy_controls).values({"policy_id": policy.id, "control_id": policy_control.id})
    )
    await async_db.execute(
        insert(agent_controls).values({"agent_name": agent.name, "control_id": direct_control.id})
    )
    await async_db.commit()

    # When: listing controls for the agent
    controls = await ControlService(async_db).list_controls_for_agent(agent.name)

    # Then: both policy-derived and direct controls are returned
    assert len(controls) == 2
    names = {control.name for control in controls}
    assert names == {policy_control.name, direct_control.name}
    ids = [control.id for control in controls]
    assert ids == sorted(ids, reverse=True)


@pytest.mark.asyncio
async def test_list_controls_for_agent_excludes_deleted_controls(async_db) -> None:
    # Given: an agent associated with one active and one soft-deleted control
    active_control = Control(name=f"active-control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    deleted_control = Control(
        name=f"deleted-control-{uuid.uuid4()}",
        data=VALID_CONTROL_PAYLOAD,
        deleted_at=dt.datetime.now(dt.UTC),
    )
    agent = Agent(name=f"agent-{uuid.uuid4()}", data={})
    async_db.add_all([active_control, deleted_control, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_controls).values(
            [
                {"agent_name": agent.name, "control_id": active_control.id},
                {"agent_name": agent.name, "control_id": deleted_control.id},
            ]
        )
    )
    await async_db.commit()

    # When: listing controls for the agent
    controls = await ControlService(async_db).list_controls_for_agent(
        agent.name,
        rendered_state="all",
        enabled_state="all",
    )

    # Then: soft-deleted controls are excluded
    assert [control.id for control in controls] == [active_control.id]


@pytest.mark.asyncio
async def test_list_controls_for_agent_filters_by_rendered_and_enabled_state(async_db) -> None:
    # Given: an agent with active, disabled, and unrendered associated controls
    policy = Policy(name=f"policy-{uuid.uuid4()}")
    active_control = Control(name=f"active-control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    disabled_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    disabled_payload["enabled"] = False
    disabled_control = Control(
        name=f"disabled-control-{uuid.uuid4()}",
        data=disabled_payload,
    )
    unrendered_control = Control(
        name=f"unrendered-control-{uuid.uuid4()}",
        data=_unrendered_template_payload(),
    )
    agent = Agent(name=f"agent-{uuid.uuid4()}", data={})
    async_db.add_all([policy, active_control, disabled_control, unrendered_control, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_policies).values({"agent_name": agent.name, "policy_id": policy.id})
    )
    await async_db.execute(
        insert(policy_controls).values({"policy_id": policy.id, "control_id": active_control.id})
    )
    await async_db.execute(
        insert(agent_controls).values(
            [
                {"agent_name": agent.name, "control_id": disabled_control.id},
                {"agent_name": agent.name, "control_id": unrendered_control.id},
            ]
        )
    )
    await async_db.commit()

    # When: listing controls with the default active-only behavior
    default_controls = await ControlService(async_db).list_controls_for_agent(agent.name)

    # Then: only rendered and enabled controls are returned
    assert {control.name for control in default_controls} == {active_control.name}

    # When: requesting disabled rendered controls
    disabled_controls = await ControlService(async_db).list_controls_for_agent(
        agent.name,
        enabled_state="disabled",
    )

    # Then: disabled rendered controls are included without unrendered drafts
    assert {control.name for control in disabled_controls} == {disabled_control.name}

    # When: requesting unrendered controls
    unrendered_controls = await ControlService(async_db).list_controls_for_agent(
        agent.name,
        rendered_state="unrendered",
        enabled_state="all",
    )

    # Then: only unrendered drafts are returned
    assert {control.name for control in unrendered_controls} == {unrendered_control.name}

    # When: requesting the full associated set
    all_controls = await ControlService(async_db).list_controls_for_agent(
        agent.name,
        rendered_state="all",
        enabled_state="all",
    )

    # Then: all associated controls are returned
    assert {control.name for control in all_controls} == {
        active_control.name,
        disabled_control.name,
        unrendered_control.name,
    }

    # When: requesting the impossible intersection of unrendered and enabled
    impossible_controls = await ControlService(async_db).list_controls_for_agent(
        agent.name,
        rendered_state="unrendered",
        enabled_state="enabled",
    )

    # Then: the service returns an empty list
    assert impossible_controls == []


@pytest.mark.asyncio
async def test_list_active_control_counts_by_agent_deduplicates_and_filters_inactive(
    async_db,
) -> None:
    # Given: an agent with overlapping policy/direct controls plus inactive controls
    policy = Policy(name=f"policy-{uuid.uuid4()}")
    agent = Agent(name=f"agent-{uuid.uuid4()}", data={})
    shared_control = Control(name=f"shared-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    policy_only_control = Control(name=f"policy-only-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    disabled_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    disabled_payload["enabled"] = False
    disabled_control = Control(name=f"disabled-{uuid.uuid4()}", data=disabled_payload)
    deleted_control = Control(
        name=f"deleted-{uuid.uuid4()}",
        data=VALID_CONTROL_PAYLOAD,
        deleted_at=dt.datetime.now(dt.UTC),
    )
    async_db.add_all(
        [
            policy,
            agent,
            shared_control,
            policy_only_control,
            disabled_control,
            deleted_control,
        ]
    )
    await async_db.flush()

    await async_db.execute(
        insert(agent_policies).values({"agent_name": agent.name, "policy_id": policy.id})
    )
    await async_db.execute(
        insert(policy_controls).values(
            [
                {"policy_id": policy.id, "control_id": shared_control.id},
                {"policy_id": policy.id, "control_id": policy_only_control.id},
                {"policy_id": policy.id, "control_id": deleted_control.id},
            ]
        )
    )
    await async_db.execute(
        insert(agent_controls).values(
            [
                {"agent_name": agent.name, "control_id": shared_control.id},
                {"agent_name": agent.name, "control_id": disabled_control.id},
            ]
        )
    )
    await async_db.commit()

    # When: counting active controls for the agent
    counts = await ControlService(async_db).list_active_control_counts_by_agent([agent.name])

    # Then: active controls are deduplicated and inactive controls are excluded
    assert counts == {agent.name: 2}


@pytest.mark.asyncio
async def test_remove_control_from_agent_reports_policy_inheritance(async_db) -> None:
    # Given: a control linked both directly and through an assigned policy
    policy = Policy(name=f"policy-{uuid.uuid4()}")
    agent = Agent(name=f"agent-{uuid.uuid4()}", data={})
    control = Control(name=f"control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    async_db.add_all([policy, agent, control])
    await async_db.flush()

    await async_db.execute(
        insert(agent_policies).values({"agent_name": agent.name, "policy_id": policy.id})
    )
    await async_db.execute(
        insert(policy_controls).values({"policy_id": policy.id, "control_id": control.id})
    )
    await async_db.execute(
        insert(agent_controls).values({"agent_name": agent.name, "control_id": control.id})
    )
    await async_db.commit()

    service = ControlService(async_db)

    # When: removing the direct association
    first_result = await service.remove_control_from_agent(
        agent_name=agent.name,
        control_id=control.id,
    )

    # Then: the direct link is removed but the control is still active via policy inheritance
    assert first_result.removed_direct_association is True
    assert first_result.control_still_active is True

    # When: removing it again without a direct association
    second_result = await service.remove_control_from_agent(
        agent_name=agent.name,
        control_id=control.id,
    )

    # Then: the service reports that only the inherited policy link remains
    assert second_result.removed_direct_association is False
    assert second_result.control_still_active is True


@pytest.mark.asyncio
@pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="Concurrent version allocation test requires PostgreSQL row locking semantics",
)
async def test_create_version_allocates_sequential_numbers_under_concurrent_mutations() -> None:
    # Given: an existing control with an initial version
    async with AsyncSessionTest() as setup_session:
        setup_service = ControlService(setup_session)
        control = setup_service.create_control(
            name=f"control-{uuid.uuid4()}",
            data=deepcopy(VALID_CONTROL_PAYLOAD),
        )
        await setup_service.create_version(
            control,
            event_type="created",
            note="Initial creation",
        )
        await setup_session.commit()
        control_id = control.id

    start = asyncio.Event()
    ready_count = 0
    ready_lock = asyncio.Lock()

    async def mutate_and_version(description: str) -> None:
        nonlocal ready_count

        async with AsyncSessionTest() as session:
            service = ControlService(session)
            control = await service.get_active_control_or_404(control_id)
            updated_data = deepcopy(control.data)
            updated_data["description"] = description
            service.replace_control_data(control, data=updated_data)

            async with ready_lock:
                ready_count += 1
                if ready_count == 2:
                    start.set()

            await start.wait()
            await service.create_version(
                control,
                event_type="updated",
                note=f"Edited to {description}",
            )
            await session.commit()

    # When: two sessions create versions concurrently for the same control
    await asyncio.wait_for(
        asyncio.gather(
            mutate_and_version("Concurrent update A"),
            mutate_and_version("Concurrent update B"),
        ),
        timeout=10,
    )

    # Then: version numbers remain sequential for that control
    with Session(engine) as session:
        versions = list(
            session.scalars(
                select(ControlVersion)
                .where(ControlVersion.control_id == control_id)
                .order_by(ControlVersion.version_num)
            ).all()
        )

    assert [version.version_num for version in versions] == [1, 2, 3]
    assert [version.event_type for version in versions] == [
        "created",
        "updated",
        "updated",
    ]
    assert {
        version.snapshot["data"]["description"] for version in versions[1:]
    } == {"Concurrent update A", "Concurrent update B"}


@pytest.mark.asyncio
async def test_list_controls_for_agent_corrupted_data_raises(async_db) -> None:
    # Given: an agent associated with a policy containing corrupted control data
    policy = Policy(name=f"policy-{uuid.uuid4()}")
    control = Control(name=f"control-{uuid.uuid4()}", data={"bad": "data"})
    agent = Agent(
        name=f"agent-{uuid.uuid4()}",
        data={},
    )
    async_db.add_all([policy, control, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_policies).values({"agent_name": agent.name, "policy_id": policy.id})
    )
    await async_db.execute(
        insert(policy_controls).values({"policy_id": policy.id, "control_id": control.id})
    )
    await async_db.commit()

    # When: listing controls for the agent
    with pytest.raises(APIValidationError) as exc_info:
        await ControlService(async_db).list_controls_for_agent(agent.name)

    # Then: corrupted data error is raised
    assert exc_info.value.error_code == ErrorCode.CORRUPTED_DATA


@pytest.mark.asyncio
async def test_list_controls_for_agent_corrupted_unrendered_data_raises(async_db) -> None:
    # Given: an agent directly associated with corrupted unrendered template data
    control = Control(
        name=f"control-{uuid.uuid4()}",
        data={"template": {"description": "bad template"}},
    )
    agent = Agent(name=f"agent-{uuid.uuid4()}", data={})
    async_db.add_all([control, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_controls).values({"agent_name": agent.name, "control_id": control.id})
    )
    await async_db.commit()

    # When: listing active controls, which would normally exclude unrendered drafts
    with pytest.raises(APIValidationError) as exc_info:
        await ControlService(async_db).list_controls_for_agent(
            agent.name,
            rendered_state="rendered",
            enabled_state="enabled",
        )

    # Then: corrupted data still fails fast
    assert exc_info.value.error_code == ErrorCode.CORRUPTED_DATA
