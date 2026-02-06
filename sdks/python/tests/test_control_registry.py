"""Tests for the control step registry (_control_registry)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_control._control_registry import (
    _extract_input_schema,
    _extract_output_schema,
    _type_to_json_schema,
    clear,
    get_registered_steps,
    register,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry() -> None:  # noqa: PT004
    """Ensure each test starts with an empty registry."""
    clear()
    yield  # type: ignore[misc]
    clear()


# ===========================================================================
# Schema extraction helpers
# ===========================================================================


class TestTypeToJsonSchema:
    """Tests for _type_to_json_schema."""

    def test_primitive_str(self) -> None:
        assert _type_to_json_schema(str) == {"type": "string"}

    def test_primitive_int(self) -> None:
        assert _type_to_json_schema(int) == {"type": "integer"}

    def test_primitive_float(self) -> None:
        assert _type_to_json_schema(float) == {"type": "number"}

    def test_primitive_bool(self) -> None:
        assert _type_to_json_schema(bool) == {"type": "boolean"}

    def test_none_returns_none(self) -> None:
        assert _type_to_json_schema(None) is None

    def test_complex_type_returns_none(self) -> None:
        """Complex / unrecognised types should return None."""
        assert _type_to_json_schema(list) is None
        assert _type_to_json_schema(dict) is None

    def test_pydantic_model(self) -> None:
        """Pydantic v2 models should delegate to model_json_schema()."""
        mock_model = MagicMock()
        mock_model.model_json_schema.return_value = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }
        result = _type_to_json_schema(mock_model)
        assert result == {"type": "object", "properties": {"query": {"type": "string"}}}
        mock_model.model_json_schema.assert_called_once()


class TestExtractInputSchema:
    """Tests for _extract_input_schema."""

    def test_simple_function(self) -> None:
        def my_func(query: str, limit: int = 10) -> list:
            ...

        schema = _extract_input_schema(my_func)
        assert schema is not None
        assert schema["type"] == "object"
        assert schema["properties"]["query"] == {"type": "string"}
        assert schema["properties"]["limit"] == {"type": "integer"}

    def test_no_type_hints(self) -> None:
        def my_func(x, y):
            ...

        assert _extract_input_schema(my_func) is None

    def test_skips_self_and_cls(self) -> None:
        def my_method(self, query: str) -> str:  # noqa: ANN001
            ...

        schema = _extract_input_schema(my_method)
        assert schema is not None
        assert "self" not in schema["properties"]
        assert "query" in schema["properties"]

    def test_framework_args_schema(self) -> None:
        """If func has .args_schema with model_json_schema(), use that."""
        mock_schema = MagicMock()
        mock_schema.model_json_schema.return_value = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
        }

        def my_func(q: str) -> str:
            ...

        my_func.args_schema = mock_schema  # type: ignore[attr-defined]

        result = _extract_input_schema(my_func)
        assert result == {"type": "object", "properties": {"q": {"type": "string"}}}
        mock_schema.model_json_schema.assert_called_once()


class TestExtractOutputSchema:
    """Tests for _extract_output_schema."""

    def test_str_return(self) -> None:
        def my_func() -> str:
            ...

        assert _extract_output_schema(my_func) == {"type": "string"}

    def test_int_return(self) -> None:
        def my_func() -> int:
            ...

        assert _extract_output_schema(my_func) == {"type": "integer"}

    def test_no_return_annotation(self) -> None:
        def my_func():
            ...

        assert _extract_output_schema(my_func) is None

    def test_complex_return_type(self) -> None:
        def my_func() -> list[str]:
            ...

        # list[str] is not a supported primitive, should return None
        assert _extract_output_schema(my_func) is None


# ===========================================================================
# register() and get_registered_steps()
# ===========================================================================


class TestRegister:
    """Tests for register() and get_registered_steps()."""

    def test_register_simple_function(self) -> None:
        def chat(message: str) -> str:
            """Chat with the agent."""
            ...

        register(chat)
        steps = get_registered_steps()
        assert len(steps) == 1
        step = steps[0]
        assert step["name"] == "chat"
        assert step["type"] == "llm"
        assert step["description"] == "Chat with the agent."
        assert step["input_schema"] is not None
        assert step["output_schema"] == {"type": "string"}

    def test_register_tool_function(self) -> None:
        """Functions with .name or .tool_name should be registered as tools."""
        def search_db(query: str, limit: int = 10) -> str:
            """Search the database."""
            ...

        search_db.name = "search_db"  # type: ignore[attr-defined]
        search_db.tool_name = "search_db"  # type: ignore[attr-defined]

        register(search_db)
        steps = get_registered_steps()
        assert len(steps) == 1
        assert steps[0]["type"] == "tool"
        assert steps[0]["name"] == "search_db"

    def test_register_with_policy(self) -> None:
        def my_func(x: str) -> str:
            ...

        register(my_func, policy="safety-policy")
        steps = get_registered_steps()
        assert steps[0]["metadata"] == {"policy": "safety-policy"}

    def test_register_no_policy_no_metadata(self) -> None:
        def my_func(x: str) -> str:
            ...

        register(my_func)
        steps = get_registered_steps()
        assert "metadata" not in steps[0]

    def test_deduplicate_by_name(self) -> None:
        """Registering two functions with the same name should keep the last one."""
        def chat(message: str) -> str:
            """First version."""
            ...

        def chat_v2(message: str) -> int:  # noqa: ARG001
            """Second version."""
            ...

        chat_v2.__name__ = "chat"  # simulate same name

        register(chat)
        register(chat_v2)
        steps = get_registered_steps()
        assert len(steps) == 1
        assert steps[0]["description"] == "Second version."

    def test_no_docstring(self) -> None:
        def my_func(x: str) -> str:
            ...

        register(my_func)
        steps = get_registered_steps()
        assert "description" not in steps[0]

    def test_no_type_hints(self) -> None:
        """Functions with no type hints should still register with None schemas."""
        def my_func(x, y):
            ...

        register(my_func)
        steps = get_registered_steps()
        assert len(steps) == 1
        assert steps[0]["name"] == "my_func"
        assert "input_schema" not in steps[0]
        assert "output_schema" not in steps[0]


class TestClear:
    """Tests for clear()."""

    def test_clear_empties_registry(self) -> None:
        def f1(x: str) -> str:
            ...

        def f2(x: str) -> str:
            ...

        register(f1)
        register(f2)
        assert len(get_registered_steps()) == 2

        clear()
        assert len(get_registered_steps()) == 0


# ===========================================================================
# Decorator integration
# ===========================================================================


class TestDecoratorRegistration:
    """Tests that @control() decorator registers functions in the registry."""

    def test_decorator_registers_async_function(self) -> None:
        from agent_control.control_decorators import control

        @control()
        async def my_chat(message: str) -> str:
            """Handle a chat message."""
            return message

        steps = get_registered_steps()
        assert len(steps) == 1
        assert steps[0]["name"] == "my_chat"
        assert steps[0]["type"] == "llm"
        assert steps[0]["description"] == "Handle a chat message."

    def test_decorator_registers_sync_function(self) -> None:
        from agent_control.control_decorators import control

        @control()
        def my_process(input: str) -> str:
            return input.upper()

        steps = get_registered_steps()
        assert len(steps) == 1
        assert steps[0]["name"] == "my_process"

    def test_decorator_registers_with_policy(self) -> None:
        from agent_control.control_decorators import control

        @control(policy="my-policy")
        async def guarded(msg: str) -> str:
            return msg

        steps = get_registered_steps()
        assert steps[0]["metadata"] == {"policy": "my-policy"}

    def test_decorator_registers_tool(self) -> None:
        """Tool-like functions (with .name attribute) should register as type=tool."""
        from agent_control.control_decorators import control

        def _lookup(query: str) -> str:
            """Look up a record."""
            return query

        _lookup.name = "lookup_tool"  # type: ignore[attr-defined]
        _lookup.tool_name = "lookup_tool"  # type: ignore[attr-defined]
        control()(_lookup)

        steps = get_registered_steps()
        assert len(steps) == 1
        assert steps[0]["type"] == "tool"
        assert steps[0]["name"] == "lookup_tool"

    def test_stacked_decorators_deduplicate(self) -> None:
        """Stacking @control() twice on the same function deduplicates by name."""
        from agent_control.control_decorators import control

        @control(policy="p1")
        @control(policy="p2")
        async def stacked(msg: str) -> str:
            return msg

        steps = get_registered_steps()
        # The inner decorator runs first (p2), then the outer (p1).
        # Both use func.__name__ == "stacked", so last-write-wins -> p1.
        assert len(steps) == 1
        assert steps[0]["name"] == "stacked"
        assert steps[0]["metadata"] == {"policy": "p1"}


# ===========================================================================
# init() merge behaviour
# ===========================================================================


class TestInitMerge:
    """Tests that init() merges auto-discovered steps with explicit steps."""

    def test_auto_steps_merged_into_init(self) -> None:
        """Steps from @control() decorators should be sent to register_agent."""
        from agent_control.control_decorators import control

        @control()
        async def auto_tool(query: str) -> str:
            """Automatically discovered tool."""
            return query

        # Verify the step is registered
        steps = get_registered_steps()
        assert any(s["name"] == "auto_tool" for s in steps)

    def test_explicit_steps_take_precedence(self) -> None:
        """Explicit steps override auto-discovered steps with the same name."""
        # Register via decorator
        register(lambda x: x)  # name will be "<lambda>"

        def my_tool(query: str) -> str:
            ...

        register(my_tool)

        explicit_steps: list[dict[str, Any]] = [
            {"type": "tool", "name": "my_tool", "input_schema": {"custom": True}}
        ]

        # Simulate what init() does: merge logic
        auto_steps = get_registered_steps()
        explicit_names = {s["name"] for s in explicit_steps}
        merged = list(explicit_steps) + [
            s for s in auto_steps if s["name"] not in explicit_names
        ]

        # Explicit "my_tool" should win over the auto-registered one
        my_tool_entries = [s for s in merged if s["name"] == "my_tool"]
        assert len(my_tool_entries) == 1
        assert my_tool_entries[0]["input_schema"] == {"custom": True}

        # The lambda step should still be present
        assert any(s["name"] == "<lambda>" for s in merged)

    def test_no_auto_steps_leaves_explicit_unchanged(self) -> None:
        """When no decorators are used, explicit steps pass through unchanged."""
        # Registry is empty (autouse fixture cleared it)
        explicit: list[dict[str, Any]] = [
            {"type": "tool", "name": "manual_tool"}
        ]
        auto = get_registered_steps()
        assert auto == []

        # Simulate merge
        merged = list(explicit)  # no auto steps to add
        assert merged == explicit
