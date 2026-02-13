"""Tests for control step registry behavior."""

from __future__ import annotations

from typing import Any

import pytest

from agent_control._control_registry import clear, get_registered_steps, register


@pytest.fixture(autouse=True)
def _clean_registry() -> None:  # noqa: PT004
    """Ensure each test starts with an empty registry."""
    clear()
    yield  # type: ignore[misc]
    clear()


def _merge_steps_by_key(
    explicit_steps: list[dict[str, Any]], auto_steps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Mirror init() merge behavior (explicit wins by type+name)."""
    explicit_keys = {(s["type"], s["name"]) for s in explicit_steps}
    return list(explicit_steps) + [
        s for s in auto_steps if (s["type"], s["name"]) not in explicit_keys
    ]


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
        assert step["input_schema"]["type"] == "object"
        assert step["output_schema"]["type"] == "string"

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
        """Untyped functions still register with permissive schemas."""

        def my_func(x, y):
            ...

        register(my_func)
        steps = get_registered_steps()

        assert len(steps) == 1
        assert steps[0]["name"] == "my_func"
        assert steps[0]["input_schema"]["type"] == "object"
        assert set(steps[0]["input_schema"]["properties"]) == {"x", "y"}
        assert steps[0]["output_schema"] == {}


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

        assert len(steps) == 1
        assert steps[0]["name"] == "stacked"
        assert steps[0]["metadata"] == {"policy": "p1"}


class TestInitMerge:
    """Tests the explicit+auto merge behavior used by init()."""

    def test_auto_steps_merged_into_init(self) -> None:
        """Steps from @control() decorators should be available for init merge."""
        from agent_control.control_decorators import control

        @control()
        async def auto_tool(query: str) -> str:
            """Automatically discovered tool."""
            return query

        steps = get_registered_steps()

        assert any(s["name"] == "auto_tool" for s in steps)

    def test_explicit_steps_take_precedence(self) -> None:
        """Explicit steps override auto-discovered steps on exact type+name key."""
        register(lambda x: x)  # name will be "<lambda>"

        def my_step(query: str) -> str:
            ...

        register(my_step)

        explicit_steps: list[dict[str, Any]] = [
            {"type": "llm", "name": "my_step", "input_schema": {"custom": True}}
        ]

        auto_steps = get_registered_steps()
        merged = _merge_steps_by_key(explicit_steps, auto_steps)

        my_step_entries = [s for s in merged if (s["type"], s["name"]) == ("llm", "my_step")]
        assert len(my_step_entries) == 1
        assert my_step_entries[0]["input_schema"] == {"custom": True}
        assert any(s["name"] == "<lambda>" for s in merged)

    def test_no_auto_steps_leaves_explicit_unchanged(self) -> None:
        explicit: list[dict[str, Any]] = [{"type": "tool", "name": "manual_tool"}]

        merged = _merge_steps_by_key(explicit, get_registered_steps())

        assert merged == explicit

    def test_merge_keeps_same_name_steps_with_different_types(self) -> None:
        auto_steps: list[dict[str, Any]] = [{"type": "llm", "name": "shared"}]
        explicit_steps: list[dict[str, Any]] = [{"type": "tool", "name": "shared"}]

        merged = _merge_steps_by_key(explicit_steps, auto_steps)

        merged_keys = {(s["type"], s["name"]) for s in merged}
        assert merged_keys == {("tool", "shared"), ("llm", "shared")}
