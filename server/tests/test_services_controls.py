from __future__ import annotations

import uuid
from copy import deepcopy

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
    ids = [control.id for control in controls]
    assert ids == sorted(ids, reverse=True)


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
    default_controls = await list_controls_for_agent(agent.name, async_db)

    # Then: only rendered and enabled controls are returned
    assert {control.name for control in default_controls} == {active_control.name}

    # When: requesting disabled rendered controls
    disabled_controls = await list_controls_for_agent(
        agent.name,
        async_db,
        enabled_state="disabled",
    )

    # Then: disabled rendered controls are included without unrendered drafts
    assert {control.name for control in disabled_controls} == {disabled_control.name}

    # When: requesting unrendered controls
    unrendered_controls = await list_controls_for_agent(
        agent.name,
        async_db,
        rendered_state="unrendered",
        enabled_state="all",
    )

    # Then: only unrendered drafts are returned
    assert {control.name for control in unrendered_controls} == {unrendered_control.name}

    # When: requesting the full associated set
    all_controls = await list_controls_for_agent(
        agent.name,
        async_db,
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
    impossible_controls = await list_controls_for_agent(
        agent.name,
        async_db,
        rendered_state="unrendered",
        enabled_state="enabled",
    )

    # Then: the service returns an empty list
    assert impossible_controls == []


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
        await list_controls_for_agent(
            agent.name,
            async_db,
            rendered_state="rendered",
            enabled_state="enabled",
        )

    # Then: corrupted data still fails fast
    assert exc_info.value.error_code == ErrorCode.CORRUPTED_DATA
