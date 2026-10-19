"""Parent request identities remain bounded and scoped to one evaluation."""

from uuid import UUID

import pytest
from agent_control_models.request_context import get_request_id, request_id_context


@pytest.mark.parametrize("value", [None, "", "x" * 201, "unsafe\r\nvalue", "secret space", "é"])
def test_invalid_request_ids_are_replaced(value: str | None) -> None:
    # Given: a missing or unsafe external request ID.
    assert get_request_id() is None
    # When: entering the request context.
    with request_id_context(value) as actual:
        # Then: the context contains a generated UUID, never unsafe free text.
        assert str(UUID(actual)) == actual
        assert get_request_id() == actual
    assert get_request_id() is None


def test_nested_context_restores_parent_on_error() -> None:
    # Given: an established outer request.
    with request_id_context("parent"):
        # When: nested work raises.
        with pytest.raises(RuntimeError):
            with request_id_context("child"):
                assert get_request_id() == "child"
                raise RuntimeError("failure")
        # Then: the original context is restored.
        assert get_request_id() == "parent"
    assert get_request_id() is None
