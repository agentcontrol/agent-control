"""Control execution duration response compatibility."""

import pytest
from agent_control_models.controls import ControlMatch
from pydantic import ValidationError


@pytest.mark.parametrize("duration_ms", [None, 0.0, 12.5])
def test_control_match_preserves_optional_execution_duration(duration_ms: float | None) -> None:
    # Given: a response with a recorded duration or an unevaluated control.
    payload = {
        "control_id": 1,
        "control_name": "Example control",
        "action": "deny",
        "result": {"matched": False, "confidence": 0.0},
        "execution_duration_ms": duration_ms,
    }

    # When: parsing and serializing the response model.
    match = ControlMatch.model_validate(payload)
    reconstructed = ControlMatch.model_validate_json(match.model_dump_json())

    # Then: the duration stays top-level and zero is preserved.
    assert reconstructed.execution_duration_ms == duration_ms
    assert match.model_dump()["execution_duration_ms"] == duration_ms
    assert "execution_duration_ms" not in match.result.model_dump()


def test_control_match_accepts_legacy_response_without_duration() -> None:
    # Given: an older server response with no duration field.
    payload = {
        "control_id": 1,
        "control_name": "Example control",
        "action": "deny",
        "result": {"matched": False, "confidence": 0.0},
    }

    # When: parsing the response model.
    match = ControlMatch.model_validate(payload)

    # Then: no duration is fabricated for the older response.
    assert match.execution_duration_ms is None


def test_control_match_rejects_negative_execution_duration() -> None:
    # Given: a response containing an invalid elapsed time.
    payload = {
        "control_id": 1,
        "control_name": "Example control",
        "action": "deny",
        "result": {"matched": False, "confidence": 0.0},
        "execution_duration_ms": -1,
    }

    # When: parsing the response model.
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        ControlMatch.model_validate(payload)
    # Then: the response follows the same nonnegative duration contract as events.
