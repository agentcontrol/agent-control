"""Compatibility coverage for canonical tool names in evaluation requests."""

from agent_control_models import EvaluationRequest, Step
from fastapi.testclient import TestClient

from .utils import create_and_assign_policy


def test_canonical_name_allowlist_supports_mixed_sdk_versions(client: TestClient) -> None:
    # Given: an allowlist using the canonical tool identity sent by current SDKs
    control_data = {
        "description": "Allow web search",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["tool"], "stages": ["pre"]},
        "selector": {"path": "canonical_name"},
        "evaluator": {
            "name": "list",
            "config": {
                "values": ["web_search"],
                "logic": "any",
                "match_on": "no_match",
                "match_mode": "exact",
                "case_sensitive": False,
            },
        },
        "action": {"decision": "deny"},
    }
    agent_name, _ = create_and_assign_policy(
        client,
        control_data,
        agent_name="MixedVersionAgent",
    )
    legacy_request = EvaluationRequest(
        agent_name=agent_name,
        step=Step(type="tool", name="writer.web_search", input={}),
        stage="pre",
    )
    current_request = EvaluationRequest(
        agent_name=agent_name,
        step=Step(
            type="tool",
            name="writer.web_search",
            canonical_name="web_search",
            input={},
        ),
        stage="pre",
    )

    # When: legacy and current SDK payloads are evaluated by the same server
    responses = [
        client.post("/api/v1/evaluation", json=request.model_dump(mode="json"))
        for request in (legacy_request, current_request)
    ]

    # Then: the approved tool is allowed for both client versions
    assert [response.status_code for response in responses] == [200, 200]
    assert [response.json()["is_safe"] for response in responses] == [True, True]
