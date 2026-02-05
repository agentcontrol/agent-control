"""Unit tests for SDK validation helpers."""

from uuid import UUID, uuid4

import pytest

from agent_control.validation import ensure_uuid, ensure_uuid_str


def test_ensure_uuid_accepts_uuid_instance() -> None:
    value = uuid4()
    assert ensure_uuid(value) == value


def test_ensure_uuid_accepts_uuid_string() -> None:
    value = uuid4()
    assert ensure_uuid(str(value)) == value


def test_ensure_uuid_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="agent_id must be a valid UUID string"):
        ensure_uuid("not-a-uuid")


def test_ensure_uuid_respects_field_name() -> None:
    with pytest.raises(ValueError, match="agent_uuid must be a valid UUID string"):
        ensure_uuid("not-a-uuid", field_name="agent_uuid")


def test_ensure_uuid_str_returns_string() -> None:
    value = uuid4()
    assert ensure_uuid_str(value) == str(value)


def test_ensure_uuid_str_accepts_uuid_string() -> None:
    value = str(uuid4())
    assert ensure_uuid_str(value) == str(UUID(value))


def test_ensure_uuid_str_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="agent_id must be a valid UUID string"):
        ensure_uuid_str("not-a-uuid")
