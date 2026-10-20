"""Ownership metadata is distinct from configuration and clone provenance."""

import pytest
from agent_control_models.server import CloneAndBindControlRequest
from pydantic import ValidationError


@pytest.mark.parametrize("owner", ["", "   ", "x" * 256, 123])
def test_clone_rejects_invalid_owner_identifier(owner):
    # Given: invalid owner metadata and an otherwise valid target.
    payload = {
        "owner_project_id": owner,
        "target_binding": {"target_type": "log_stream", "target_id": "stream-A"},
    }
    # When/Then: validation rejects the invalid owner rather than silently using org scope.
    with pytest.raises(ValidationError):
        CloneAndBindControlRequest.model_validate(payload)


def test_legacy_clone_defaults_to_organization_owner():
    # Given/When: the existing clone request without a new owner field.
    request = CloneAndBindControlRequest.model_validate(
        {"target_binding": {"target_type": "log_stream", "target_id": "stream-A"}}
    )
    # Then: compatibility remains explicit and serializes as null ownership.
    assert request.owner_project_id is None
    assert request.model_dump()["owner_project_id"] is None
