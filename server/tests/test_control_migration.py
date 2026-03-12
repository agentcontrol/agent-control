"""Tests for stored control condition migration."""

from __future__ import annotations

from copy import deepcopy

from agent_control_server.services.control_migration import migrate_control_payload

from .utils import VALID_CONTROL_PAYLOAD


def test_migrate_control_payload_rewrites_legacy_leaf() -> None:
    # Given: a stored control payload in the legacy flat shape
    legacy_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    legacy_payload["selector"] = legacy_payload["condition"]["selector"]
    legacy_payload["evaluator"] = legacy_payload["condition"]["evaluator"]
    legacy_payload.pop("condition")

    # When: migrating the stored payload
    result = migrate_control_payload(legacy_payload)

    # Then: the payload is rewritten into canonical condition form
    assert result.status == "migrated"
    assert result.payload is not None
    assert "selector" not in result.payload
    assert "evaluator" not in result.payload
    assert result.payload["condition"]["selector"]["path"] == "input"


def test_migrate_control_payload_leaves_canonical_rows_unchanged() -> None:
    # Given: a stored payload that is already canonical
    # When: migrating the stored payload
    result = migrate_control_payload(deepcopy(VALID_CONTROL_PAYLOAD))

    # Then: no rewrite is needed and the payload is preserved
    assert result.status == "unchanged"
    assert result.payload == VALID_CONTROL_PAYLOAD


def test_migrate_control_payload_rejects_mixed_rows() -> None:
    # Given: a stored payload that mixes canonical and legacy fields
    mixed_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    mixed_payload["selector"] = {"path": "input"}

    # When: migrating the stored payload
    result = migrate_control_payload(mixed_payload)

    # Then: migration rejects the ambiguous row as invalid
    assert result.status == "invalid"
    assert result.reason is not None
    assert "mixes canonical condition fields" in result.reason


def test_migrate_control_payload_rejects_partial_legacy_rows() -> None:
    # Given: a legacy payload that is missing one of selector/evaluator
    partial_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    partial_payload.pop("condition")
    partial_payload["selector"] = {"path": "input"}

    # When: migrating the stored payload
    result = migrate_control_payload(partial_payload)

    # Then: migration rejects the incomplete legacy row
    assert result.status == "invalid"
    assert result.reason == "Legacy control definition must include both selector and evaluator."


def test_migrate_control_payload_rejects_non_object_rows() -> None:
    # Given: stored control data that is not a JSON object
    # When: migrating the stored payload
    result = migrate_control_payload(["not", "an", "object"])

    # Then: migration reports the row as invalid
    assert result.status == "invalid"
    assert result.reason == "Stored control data must be a JSON object."
