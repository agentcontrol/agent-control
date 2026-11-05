"""Isolation and lifecycle of evaluation-local preparation."""

import asyncio
from contextvars import copy_context

import pytest
from agent_control_evaluators.preparation import evaluation_preparation_scope, prepare_once


def test_no_reuse_outside_scope_and_cleanup_on_failure() -> None:
    # Given: a pure builder whose calls can be counted, including a failed evaluation.
    calls: list[int] = []
    value = object()

    def build() -> int:
        calls.append(1)
        return len(calls)

    # When: evaluate outside a scope, inside a scope, then fail that scope.
    assert prepare_once("test", (value,), build) == 1
    assert prepare_once("test", (value,), build) == 2
    with pytest.raises(ValueError), evaluation_preparation_scope():
        assert prepare_once("test", (value,), build) == 3
        assert prepare_once("test", (value,), build) == 3
        inherited = copy_context()
        raise ValueError("evaluation failed")
    # Then: inherited contexts cannot retain/repopulate an expired evaluation cache.
    assert inherited.run(prepare_once, "test", (value,), build) == 4
    assert inherited.run(prepare_once, "test", (value,), build) == 5


@pytest.mark.asyncio
async def test_concurrent_and_nested_scopes_are_independent() -> None:
    # Given: concurrent evaluations deliberately reuse the exact same input object.
    value = object()

    async def evaluate(label: str) -> None:
        with evaluation_preparation_scope():
            assert prepare_once("test", (value,), lambda: label) == label
            await asyncio.sleep(0)
            with evaluation_preparation_scope():
                assert prepare_once("test", (value,), lambda: "nested") == "nested"
            assert prepare_once("test", (value,), lambda: "wrong") == label

    # When/Then: neither nested nor sibling scopes overwrite one another.
    await asyncio.gather(evaluate("a"), evaluate("b"))


@pytest.mark.asyncio
async def test_cancellation_releases_inherited_scope() -> None:
    # Given: cancellation occurs after input preparation.
    ready = asyncio.Event()
    contexts = []
    value = object()

    async def evaluate() -> None:
        with evaluation_preparation_scope():
            prepare_once("test", (value,), lambda: "before")
            contexts.append(copy_context())
            ready.set()
            await asyncio.Event().wait()

    # When: cancel the evaluation.
    task = asyncio.create_task(evaluate())
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Then: an inherited context no longer returns the canceled evaluation's value.
    assert contexts[0].run(prepare_once, "test", (value,), lambda: "after") == "after"
