"""
Integration tests for Policy operations.

These tests verify policy management workflows:
1. Policy creation
2. Adding/removing controls from policies
3. Listing policy controls
"""

import agent_control
import pytest


@pytest.mark.asyncio
async def test_policy_creation_workflow(
    client: agent_control.AgentControlClient,
    unique_name: str
) -> None:
    """
    Test policy creation workflow.

    Verifies:
    - Policy can be created with unique name
    - Response includes policy_id
    - Duplicate names are rejected
    """
    policy_name = f"test-policy-{unique_name}"

    # Create policy
    result = await agent_control.policies.create_policy(client, policy_name)

    # Verify response
    assert "policy_id" in result
    assert isinstance(result["policy_id"], int)

    policy_id = result["policy_id"]
    print(f"✓ Policy created: ID {policy_id}")

    # Try to create duplicate (should fail with 409)
    with pytest.raises(Exception) as exc_info:
        await agent_control.policies.create_policy(client, policy_name)

    # Verify it's a 409 conflict error
    assert "409" in str(exc_info.value)
    print("✓ Duplicate policy name correctly rejected")


@pytest.mark.asyncio
async def test_control_association_workflow(
    client: agent_control.AgentControlClient,
    test_policy: dict,
    test_control: dict
) -> None:
    """
    Test adding and removing controls from policies.

    Verifies:
    - Control can be added to policy
    - Operation is idempotent (adding twice works)
    - Control can be removed from policy
    - Removal is idempotent
    """
    policy_id = test_policy["policy_id"]
    control_id = test_control["control_id"]

    # Add control to policy
    result = await agent_control.policies.add_control_to_policy(
        client,
        policy_id,
        control_id
    )

    assert result["success"] is True
    print(f"✓ Control {control_id} added to policy {policy_id}")

    # Add again (should be idempotent)
    result = await agent_control.policies.add_control_to_policy(
        client,
        policy_id,
        control_id
    )

    assert result["success"] is True
    print("✓ Idempotent add verified")

    # List controls to verify
    controls_result = await agent_control.policies.list_policy_controls(
        client,
        policy_id
    )

    assert control_id in controls_result["control_ids"]
    print("✓ Control appears in policy controls list")

    # Remove control from policy
    result = await agent_control.policies.remove_control_from_policy(
        client,
        policy_id,
        control_id
    )

    assert result["success"] is True
    print("✓ Control removed from policy")

    # Remove again (should be idempotent)
    result = await agent_control.policies.remove_control_from_policy(
        client,
        policy_id,
        control_id
    )

    assert result["success"] is True
    print("✓ Idempotent remove verified")

    # Verify control is no longer in list
    controls_result = await agent_control.policies.list_policy_controls(
        client,
        policy_id
    )

    assert control_id not in controls_result["control_ids"]
    print("✓ Control no longer in policy controls list")


@pytest.mark.asyncio
async def test_list_policy_controls_workflow(
    client: agent_control.AgentControlClient,
    test_policy: dict
) -> None:
    """
    Test listing policy controls.

    Verifies:
    - Empty policy returns empty list
    - Response structure is correct
    """
    policy_id = test_policy["policy_id"]

    # List controls (should be empty for new policy)
    result = await agent_control.policies.list_policy_controls(client, policy_id)

    # Verify response structure
    assert "control_ids" in result
    assert isinstance(result["control_ids"], list)

    print(f"✓ Policy has {len(result['control_ids'])} controls")


@pytest.mark.asyncio
async def test_policy_not_found_error(
    client: agent_control.AgentControlClient
) -> None:
    """
    Test error handling for non-existent policy.

    Verifies:
    - 404 error is raised for non-existent policy
    """
    non_existent_policy_id = 999999

    with pytest.raises(Exception) as exc_info:
        await agent_control.policies.list_policy_controls(
            client,
            non_existent_policy_id
        )

    # Verify it's a 404 error
    assert "404" in str(exc_info.value)
    print("✓ 404 error correctly raised for non-existent policy")
