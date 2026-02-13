"""Tests for control step registry behavior."""

from __future__ import annotations

import functools
import logging
from collections.abc import Generator
from typing import Any

import pytest
from agent_control._control_registry import (
    clear,
    get_registered_steps,
    merge_explicit_and_auto_steps,
    register,
)
from pydantic import BaseModel


@pytest.fixture(autouse=True)
def _clean_registry() -> Generator[None, None, None]:
    """Ensure each test starts with an empty registry."""
    clear()
    yield
    clear()


class TestRegister:
    """Tests for register() and get_registered_steps()."""

    def test_register_simple_function(self) -> None:
        # Given a basic typed control function with a docstring.
        def chat(message: str) -> str:
            """Chat with the agent."""
            ...

        # When the function is registered and steps are retrieved.
        register(chat)
        steps = get_registered_steps()

        # Then one llm step is created with the expected name, description, and schemas.
        assert len(steps) == 1
        step = steps[0]
        assert step["name"] == "chat"
        assert step["type"] == "llm"
        assert step["description"] == "Chat with the agent."
        assert step["input_schema"]["type"] == "object"
        assert step["output_schema"]["type"] == "string"

    def test_register_tool_function(self) -> None:
        """Functions with .name or .tool_name should be registered as tools."""

        # Given a function that advertises tool-style metadata via attributes.
        def search_db(query: str, limit: int = 10) -> str:
            """Search the database."""
            ...

        search_db.name = "search_db"  # type: ignore[attr-defined]
        search_db.tool_name = "search_db"  # type: ignore[attr-defined]

        # When the function is registered.
        register(search_db)
        steps = get_registered_steps()

        # Then the registered step is classified as a tool using the declared tool name.
        assert len(steps) == 1
        assert steps[0]["type"] == "tool"
        assert steps[0]["name"] == "search_db"

    def test_register_with_policy(self) -> None:
        # Given a typed function and an explicit policy value at registration time.
        def my_func(x: str) -> str:
            ...

        # When the function is registered with that policy.
        register(my_func, policy="safety-policy")
        steps = get_registered_steps()

        # Then metadata contains the policy exactly once.
        assert steps[0]["metadata"] == {"policy": "safety-policy"}

    def test_register_no_policy_no_metadata(self) -> None:
        # Given a typed function registered without policy metadata.
        def my_func(x: str) -> str:
            ...

        # When registration completes.
        register(my_func)
        steps = get_registered_steps()

        # Then no metadata field is emitted for the step.
        assert "metadata" not in steps[0]

    def test_deduplicate_by_name(self) -> None:
        """Registering two functions with the same name should keep the last one."""

        # Given two functions that resolve to the same step name.
        def chat(message: str) -> str:
            """First version."""
            ...

        def chat_v2(message: str) -> int:  # noqa: ARG001
            """Second version."""
            ...

        chat_v2.__name__ = "chat"  # simulate same name

        # When both are registered in order.
        register(chat)
        register(chat_v2)
        steps = get_registered_steps()

        # Then only the second registration remains for that name.
        assert len(steps) == 1
        assert steps[0]["description"] == "Second version."

    def test_same_name_different_types_are_kept_distinct(self) -> None:
        # Given two controls that share a name but represent different step types.
        def llm_step(message: str) -> str:
            """LLM variant."""
            ...

        def tool_step(query: str) -> str:
            """Tool variant."""
            ...

        llm_step.__name__ = "shared_name"
        tool_step.name = "shared_name"  # type: ignore[attr-defined]
        tool_step.tool_name = "shared_name"  # type: ignore[attr-defined]

        # When both controls are registered.
        register(llm_step)
        register(tool_step)
        steps = get_registered_steps()

        # Then both entries are retained because deduplication key is (type, name).
        keys = {(step["type"], step["name"]) for step in steps}
        assert keys == {("llm", "shared_name"), ("tool", "shared_name")}

    def test_no_docstring(self) -> None:
        # Given a typed function without a docstring.
        def my_func(x: str) -> str:
            ...

        # When the function is registered.
        register(my_func)
        steps = get_registered_steps()

        # Then description is omitted from the resulting step.
        assert "description" not in steps[0]

    def test_no_type_hints(self) -> None:
        """Untyped functions still register with permissive schemas."""

        # Given an untyped function.
        def my_func(x, y):
            ...

        # When the function is registered.
        register(my_func)
        steps = get_registered_steps()

        # Then registration succeeds with a permissive input schema and fallback output schema.
        assert len(steps) == 1
        assert steps[0]["name"] == "my_func"
        assert steps[0]["input_schema"]["type"] == "object"
        assert set(steps[0]["input_schema"]["properties"]) == {"x", "y"}
        assert steps[0]["output_schema"] == {}

    def test_forward_reference_can_resolve_at_retrieval_time(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Given a function registered before its forward-referenced model is available in globals.
        def my_func(payload: LaterModel) -> str:
            ...

        register(my_func)

        class LaterModel(BaseModel):
            value: str

        my_func.__globals__["LaterModel"] = LaterModel

        # When registered steps are materialized (schema derivation occurs at retrieval time).
        with caplog.at_level(logging.WARNING):
            steps = get_registered_steps()

        # Then the forward reference resolves successfully without fallback warnings.
        payload_schema = steps[0]["input_schema"]["properties"]["payload"]
        assert ("$ref" in payload_schema) or (payload_schema.get("type") == "object")
        assert "failed to resolve type hints" not in caplog.text


class TestClear:
    """Tests for clear()."""

    def test_clear_empties_registry(self) -> None:
        # Given multiple registered functions in the global registry.
        def f1(x: str) -> str:
            ...

        def f2(x: str) -> str:
            ...

        register(f1)
        register(f2)
        assert len(get_registered_steps()) == 2

        # When clear() is called.
        clear()

        # Then the registry becomes empty.
        assert len(get_registered_steps()) == 0


class TestDecoratorRegistration:
    """Tests that @control() decorator registers functions in the registry."""

    def test_decorator_registers_async_function(self) -> None:
        # Given an async function decorated with @control().
        from agent_control.control_decorators import control

        @control()
        async def my_chat(message: str) -> str:
            """Handle a chat message."""
            return message

        # When registered steps are queried after decoration.
        steps = get_registered_steps()

        # Then the decorated async function appears as a single llm step with its docstring.
        assert len(steps) == 1
        assert steps[0]["name"] == "my_chat"
        assert steps[0]["type"] == "llm"
        assert steps[0]["description"] == "Handle a chat message."

    def test_decorator_registers_sync_function(self) -> None:
        # Given a sync function decorated with @control().
        from agent_control.control_decorators import control

        @control()
        def my_process(input: str) -> str:
            return input.upper()

        # When registered steps are retrieved.
        steps = get_registered_steps()

        # Then the function is registered with the expected name.
        assert len(steps) == 1
        assert steps[0]["name"] == "my_process"

    def test_decorator_registers_with_policy(self) -> None:
        # Given a decorated function that includes a policy in the decorator arguments.
        from agent_control.control_decorators import control

        @control(policy="my-policy")
        async def guarded(msg: str) -> str:
            return msg

        # When registered steps are fetched.
        steps = get_registered_steps()

        # Then the policy is persisted in step metadata.
        assert steps[0]["metadata"] == {"policy": "my-policy"}

    def test_decorator_registers_tool(self) -> None:
        """Tool-like functions (with .name attribute) should register as type=tool."""

        # Given a function decorated via @control() and marked with tool metadata attributes.
        from agent_control.control_decorators import control

        def _lookup(query: str) -> str:
            """Look up a record."""
            return query

        _lookup.name = "lookup_tool"  # type: ignore[attr-defined]
        _lookup.tool_name = "lookup_tool"  # type: ignore[attr-defined]

        # When the decorator is applied to the tool-like function.
        control()(_lookup)

        # Then the registry contains a tool step with the tool's declared name.
        steps = get_registered_steps()

        assert len(steps) == 1
        assert steps[0]["type"] == "tool"
        assert steps[0]["name"] == "lookup_tool"

    def test_stacked_decorators_deduplicate(self) -> None:
        """Stacking @control() twice on the same function deduplicates by name."""

        # Given a function wrapped by two @control() decorators with different policies.
        from agent_control.control_decorators import control

        @control(policy="p1")
        @control(policy="p2")
        async def stacked(msg: str) -> str:
            return msg

        # When the stacked decorators register the same function name.
        steps = get_registered_steps()

        # Then deduplication keeps one step, preserving the outermost decorator metadata.
        assert len(steps) == 1
        assert steps[0]["name"] == "stacked"
        assert steps[0]["metadata"] == {"policy": "p1"}

    def test_control_with_prior_wrapper_preserves_schema_fields(self) -> None:
        # Given a user wrapper applied before @control() using functools.wraps.
        from agent_control.control_decorators import control

        def with_tracing(func: Any) -> Any:
            @functools.wraps(func)
            async def wrapped(*args: Any, **kwargs: Any) -> Any:
                return await func(*args, **kwargs)

            return wrapped

        @control()
        @with_tracing
        async def wrapped_chat(message: str, include_context: bool = False) -> str:
            return message

        # When registered steps are materialized.
        steps = get_registered_steps()

        # Then registration keeps the original step identity and inferred schema fields.
        assert len(steps) == 1
        step = steps[0]
        assert step["type"] == "llm"
        assert step["name"] == "wrapped_chat"
        assert step["input_schema"]["properties"]["message"]["type"] == "string"
        assert step["input_schema"]["properties"]["include_context"]["type"] == "boolean"
        assert step["output_schema"]["type"] == "string"


class TestInitMerge:
    """Tests the explicit+auto merge behavior used by init()."""

    def test_auto_steps_merged_into_init(self) -> None:
        """Steps from @control() decorators should be available for init merge."""

        # Given an auto-registered control via decorator discovery.
        from agent_control.control_decorators import control

        @control()
        async def auto_tool(query: str) -> str:
            """Automatically discovered tool."""
            return query

        # When registered steps are collected for init-time merge.
        steps = get_registered_steps()

        # Then the auto-registered step is present by name.
        assert any(s["name"] == "auto_tool" for s in steps)

    def test_explicit_steps_take_precedence(self) -> None:
        """Explicit steps override auto-discovered steps on exact type+name key."""
        # Given auto-discovered steps and an explicit step that shares the same (type, name) key.
        register(lambda x: x)  # name will be "<lambda>"

        def my_step(query: str) -> str:
            ...

        register(my_step)

        explicit_steps: list[dict[str, Any]] = [
            {"type": "llm", "name": "my_step", "input_schema": {"custom": True}}
        ]

        # When explicit and auto steps are merged with explicit-first precedence.
        auto_steps = get_registered_steps()
        merge_result = merge_explicit_and_auto_steps(explicit_steps, auto_steps)
        merged = merge_result.steps

        # Then explicit wins for duplicates while unrelated auto steps are retained.
        my_step_entries = [s for s in merged if (s["type"], s["name"]) == ("llm", "my_step")]
        assert len(my_step_entries) == 1
        assert my_step_entries[0]["input_schema"] == {"custom": True}
        assert any(s["name"] == "<lambda>" for s in merged)
        assert merge_result.overridden_keys == [("llm", "my_step")]

    def test_no_auto_steps_leaves_explicit_unchanged(self) -> None:
        # Given only explicit steps and no auto-registered steps.
        explicit: list[dict[str, Any]] = [{"type": "tool", "name": "manual_tool"}]

        # When merge logic runs against an empty auto-step set.
        merged = merge_explicit_and_auto_steps(explicit, get_registered_steps()).steps

        # Then the output matches the explicit list unchanged.
        assert merged == explicit

    def test_merge_keeps_same_name_steps_with_different_types(self) -> None:
        # Given explicit and auto steps that share a name but have different step types.
        auto_steps: list[dict[str, Any]] = [{"type": "llm", "name": "shared"}]
        explicit_steps: list[dict[str, Any]] = [{"type": "tool", "name": "shared"}]

        # When merge logic deduplicates by (type, name) rather than by name only.
        merged = merge_explicit_and_auto_steps(explicit_steps, auto_steps).steps

        # Then both entries are preserved because their type dimension differs.
        merged_keys = {(s["type"], s["name"]) for s in merged}
        assert merged_keys == {("tool", "shared"), ("llm", "shared")}


class TestStepSchemaContract:
    """Contract tests that merged registry payloads satisfy StepSchema model."""

    def test_merged_steps_validate_against_stepschema_model(self) -> None:
        # Given one auto-discovered step and one explicit override for the same (type, name).
        from agent_control_models import StepSchema

        def auto_llm_step(query: str) -> str:
            """Auto-discovered llm step."""
            ...

        register(auto_llm_step)

        explicit_steps: list[dict[str, Any]] = [
            {
                "type": "llm",
                "name": "auto_llm_step",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                "output_schema": {"type": "string"},
            },
            {
                "type": "tool",
                "name": "manual_tool",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
            },
        ]

        # When explicit and auto steps are merged by the registry helper.
        merge_result = merge_explicit_and_auto_steps(explicit_steps, get_registered_steps())

        # Then every merged payload validates against the shared StepSchema contract.
        validated_steps = [StepSchema.model_validate(step) for step in merge_result.steps]
        assert len(validated_steps) == len(merge_result.steps)
        assert merge_result.overridden_keys == [("llm", "auto_llm_step")]
