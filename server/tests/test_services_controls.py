from __future__ import annotations

import uuid

import pytest
from sqlalchemy import insert

from agent_control_models.errors import ErrorCode
from agent_control_server.errors import APIValidationError
from agent_control_server.models import Agent, Control, agent_controls
from agent_control_server.services.controls import list_controls_for_agent

from .utils import VALID_CONTROL_PAYLOAD


@pytest.mark.asyncio
async def test_list_controls_for_agent_returns_controls(async_db) -> None:
    # Given: an agent with a directly associated control
    control = Control(name=f"control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    agent = Agent(
        agent_uuid=uuid.uuid4(),
        name=f"agent-{uuid.uuid4()}",
        data={},
    )
    async_db.add_all([control, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_controls).values(
            {"agent_uuid": agent.agent_uuid, "control_id": control.id}
        )
    )
    await async_db.commit()

    # When: listing controls for the agent
    controls = await list_controls_for_agent(agent.agent_uuid, async_db)

    # Then: the API control is returned with expected fields
    assert len(controls) == 1
    assert controls[0].name == control.name
    assert controls[0].control.evaluator.name == VALID_CONTROL_PAYLOAD["evaluator"]["name"]


@pytest.mark.asyncio
async def test_list_controls_for_agent_returns_multiple(async_db) -> None:
    # Given: an agent with two associated controls
    control_a = Control(name=f"control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    control_b = Control(name=f"control-{uuid.uuid4()}", data=VALID_CONTROL_PAYLOAD)
    agent = Agent(
        agent_uuid=uuid.uuid4(),
        name=f"agent-{uuid.uuid4()}",
        data={},
    )
    async_db.add_all([control_a, control_b, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_controls).values(
            [
                {"agent_uuid": agent.agent_uuid, "control_id": control_a.id},
                {"agent_uuid": agent.agent_uuid, "control_id": control_b.id},
            ]
        )
    )
    await async_db.commit()

    # When: listing controls for the agent
    controls = await list_controls_for_agent(agent.agent_uuid, async_db)

    # Then: both controls are returned
    names = {c.name for c in controls}
    assert names == {control_a.name, control_b.name}


@pytest.mark.asyncio
async def test_list_controls_for_agent_corrupted_data_raises(async_db) -> None:
    # Given: an agent with a corrupted control
    control = Control(name=f"control-{uuid.uuid4()}", data={"bad": "data"})
    agent = Agent(
        agent_uuid=uuid.uuid4(),
        name=f"agent-{uuid.uuid4()}",
        data={},
    )
    async_db.add_all([control, agent])
    await async_db.flush()

    await async_db.execute(
        insert(agent_controls).values(
            {"agent_uuid": agent.agent_uuid, "control_id": control.id}
        )
    )
    await async_db.commit()

    # When: listing controls for the agent
    with pytest.raises(APIValidationError) as exc_info:
        await list_controls_for_agent(agent.agent_uuid, async_db)

    # Then: corrupted data error is raised
    assert exc_info.value.error_code == ErrorCode.CORRUPTED_DATA
