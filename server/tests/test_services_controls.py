from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert

from agent_control_models.errors import ErrorCode
from agent_control_server.errors import APIValidationError
from agent_control_server.models import (
    Agent,
    Control,
    Policy,
    agent_controls,
    agent_policies,
    policy_controls,
)
from agent_control_server.services.controls import list_controls_for_agent, list_controls_for_policy

from .utils import VALID_CONTROL_PAYLOAD


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
    controls = await list_controls_for_policy(policy.id, async_db)

    # Then: both controls are returned
    names = {c.name for c in controls}
    assert names == {control_a.name, control_b.name}


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
    controls = await list_controls_for_agent(agent.name, async_db)

    # Then: both policy-derived and direct controls are returned
    assert len(controls) == 2
    names = {control.name for control in controls}
    assert names == {policy_control.name, direct_control.name}


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
        await list_controls_for_agent(agent.name, async_db)

    # Then: corrupted data error is raised
    assert exc_info.value.error_code == ErrorCode.CORRUPTED_DATA
