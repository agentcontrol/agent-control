"""Behavioral coverage using the installed Quarry compiler and scanner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib.metadata import entry_points
from unittest.mock import AsyncMock, patch

import pytest
from agent_control_engine.core import ControlEngine
from agent_control_evaluators import clear_evaluator_cache, get_evaluator_instance
from agent_control_models import (
    ControlDefinition,
    EvaluationRequest,
    EvaluatorSpec,
    JSONObject,
    JSONValue,
    Step,
)
from pydantic import ValidationError
from quarry import CompiledPolicy, ScanResult, compile_policy

from agent_control_evaluator_quarry import QuarryEvaluator, QuarryEvaluatorConfig

RULE = 'rule "Blocked request"\ncondition:\n    user_said("blocked")\n'
SEQUENCE = 'rule "Read then send"\ncondition:\n    has_sequence("read", "send")\n'


def trace(*children: Step) -> Step:
    return Step(type="trace", name="trace", input=None, children=list(children))


def turn(text: str, output: JSONValue = None) -> Step:
    return Step(type="llm", name="model", input=text, output=output)


def tool(name: str, *, call_id: str | None = None) -> Step:
    return Step(
        type="tool",
        name=name,
        input={"query": "value"},
        output="done",
        context={"tool_call_id": call_id} if call_id else None,
    )


def evaluator(**config: JSONValue) -> QuarryEvaluator:
    return QuarryEvaluator(QuarryEvaluatorConfig.model_validate({"rule": RULE, **config}))


@pytest.mark.parametrize("data", [None, "", [], {}])
@pytest.mark.asyncio
async def test_empty_input_is_nonmatch(data: JSONValue) -> None:
    # Given: a valid local policy and empty selected data
    guard = evaluator()
    # When: evaluating empty input
    result = await guard.evaluate(data)
    # Then: empty data is not an infrastructure failure
    assert result.matched is False
    assert result.error is None


@pytest.mark.parametrize("text,matched", [("blocked operation", True), ("hello", False)])
@pytest.mark.asyncio
async def test_real_policy_matches(text: str, matched: bool) -> None:
    # Given: an ordinary trace and the real Quarry compiler
    guard = evaluator()
    # When: evaluating the recursive Step public contract
    result = await guard.evaluate(trace(turn(text)).model_dump(mode="json"))
    # Then: a policy match is a normal result, with rule identity and complete status
    assert result.error is None
    assert result.matched is matched
    assert result.metadata is not None
    assert result.metadata["matched_rules"] == (["Blocked request"] if matched else [])
    assert result.metadata["completion_state"] == "complete"


@pytest.mark.asyncio
async def test_empty_hierarchy_is_nonmatch() -> None:
    # Given: nested containers without messages
    step = trace(trace())
    # When: evaluating the hierarchy
    result = await evaluator().evaluate(step)
    # Then: the evaluator does not invent messages from container names
    assert result.matched is False
    assert result.error is None


@pytest.mark.parametrize(
    "config",
    [
        {"rule": " "},
        {"timeout_ms": 0},
        {"timeout_ms": True},
        {"max_messages": 0},
        {"session_mode": "automatic"},
        {"model": "remote"},
    ],
)
def test_invalid_config_is_rejected(config: dict[str, object]) -> None:
    # Given: an unsupported or unsafe configuration
    # When: validating through the public config model
    with pytest.raises(ValidationError):
        QuarryEvaluatorConfig.model_validate({"rule": RULE, **config})
    # Then: no policy instance was admitted


@pytest.mark.parametrize(
    "source",
    [
        "not a rule",
        RULE + RULE.replace("Blocked request", "Second"),
        'rule "Remote"\ncondition:\n    model("guard").complete(messages).content contains "x"\n',
        'rule "Missing text"\ncondition:\n    user_said(text_ref("secret"))\n',
        'rule "Parameters"\nparameters:\n    threshold: number\n'
        'condition:\n    1 > params.threshold\n',
    ],
)
def test_unusable_policy_fails_at_construction(source: str) -> None:
    # Given: invalid source, multiple rules, or a rule needing unavailable resources
    # When: constructing the evaluator through its public factory
    with pytest.raises(ValueError, match="could not compile"):
        QuarryEvaluator.from_dict({"rule": source})
    # Then: no incomplete rule generation can serve requests


@pytest.mark.asyncio
async def test_nested_tools_keep_sequence_and_arguments() -> None:
    # Given: nested trace children whose tool arguments and order matter
    source = """rule "Ordered arguments"
condition:
    has_sequence("read", "send") and
    any call in tool_calls where call.name == "send" and call.arguments.query == "value"
"""
    step = trace(trace(tool("read")), tool("send"))
    # When: scanning through the real Quarry runtime
    result = await evaluator(rule=source).evaluate(step)
    # Then: the conversion preserved event order, tool names, and structured arguments
    assert result.error is None
    assert result.matched is True


@pytest.mark.asyncio
async def test_tool_children_and_structured_result_keep_order() -> None:
    # Given: a parent tool whose child runs before the parent returns structured output
    parent = Step(
        type="tool", name="parent", input={}, output={"status": "blocked"}, children=[tool("read")]
    )
    source = """rule "Nested tool result"
condition:
    has_sequence("parent", "read") and
    any response in get_tool_responses("parent") where response.content contains "blocked"
"""
    # When: evaluating the nested tool hierarchy
    result = await evaluator(rule=source).evaluate(trace(parent))
    # Then: nested tool calls are distinct and the structured parent result remains visible
    assert result.error is None
    assert result.matched is True


@pytest.mark.asyncio
async def test_offered_tools_are_not_executed_calls() -> None:
    # Given: a model offered a tool without calling it
    step = trace(
        Step(
            type="llm",
            name="model",
            input="hello",
            tools=[
                {
                    "type": "function",
                    "function": {"name": "read", "parameters": {"type": "object"}},
                }
            ],
        )
    )
    source = 'rule "Offered only"\ncondition:\n    has_tool("read") and not called_tool("read")\n'
    # When: scanning the real Quarry tools surface
    result = await evaluator(rule=source).evaluate(step)
    # Then: tool availability stays separate from events that actually occurred
    assert result.error is None
    assert result.matched is True


@pytest.mark.asyncio
async def test_pending_tool_call_has_no_invented_result() -> None:
    # Given: a tool pre-check with no result yet
    step = trace(Step(type="tool", name="read", input={"query": "value"}))
    source = '''rule "Pending call"
condition:
    called_tool("read") and
    not (any response in tool_responses where response.content contains "done")
'''
    # When: evaluating the trace before the tool returns
    result = await evaluator(rule=source).evaluate(step)
    # Then: the call is visible but no response was invented
    assert result.error is None
    assert result.matched is True


@pytest.mark.parametrize("mode,matched,scans", [("per_trace", False, 2), ("continuous", True, 1)])
@pytest.mark.asyncio
async def test_session_boundaries_are_explicit(mode: str, matched: bool, scans: int) -> None:
    # Given: a sequence split across two ordered traces
    step = Step(
        type="session",
        name="session",
        input=None,
        children=[trace(tool("read")), trace(tool("send"))],
    )
    # When: scanning with the caller's explicit boundary choice
    result = await evaluator(rule=SEQUENCE, session_mode=mode).evaluate(step)
    # Then: only continuous sessions permit rules to span traces
    assert result.error is None
    assert result.matched is matched
    assert result.metadata is not None
    assert result.metadata["scan_count"] == scans
    assert result.metadata["session_mode"] == mode


@pytest.mark.parametrize(
    "step,reason",
    [
        (Step(type="session", name="s", input=None, children=[]), "session_mode"),
        (
            Step(type="session", name="s", input=None, children=[turn("blocked")]),
            "Session children",
        ),
        (trace(Step(type="retriever", name="r", input="blocked")), "Supported child types"),
        (turn("blocked"), "trace or session root"),
        (Step(type="trace", name="t", input="blocked"), "Step.children"),
        (trace(Step(type="llm", name="m", input={"prompt": "blocked"})), "messages array"),
        (trace(Step(type="llm", name="m", input=None, output={"value": "blocked"})), "LLM output"),
        (
            trace(Step(type="llm", name="m", input="blocked", children=[tool("read")])),
            "cannot have",
        ),
    ],
)
@pytest.mark.asyncio
async def test_ambiguous_steps_report_error(step: Step, reason: str) -> None:
    # Given: a shape that would require guessing or dropping content
    guard = evaluator(session_mode=None if not step.children else "per_trace")
    # When: attempting a scan
    result = await guard.evaluate(step)
    # Then: unsupported data is an explicit evaluation error, not a clean pass
    assert result.matched is False
    assert result.error is not None and reason in result.error


@pytest.mark.asyncio
async def test_cumulative_history_and_tool_step_do_not_duplicate_calls() -> None:
    # Given: an assistant call, a linked tool execution, and a later full LLM history
    call: JSONObject = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read", "arguments": '{"query":"value"}'},
            }
        ],
    }
    history: list[JSONValue] = [
        {"role": "user", "content": "hello"},
        call,
        {"role": "tool", "tool_call_id": "call-1", "content": "done"},
    ]
    source = 'rule "Single call"\ncondition:\n    count_tool_calls("read") == 1\n'
    step = trace(
        turn("hello", call),
        tool("read", call_id="call-1"),
        Step(type="llm", name="next", input={"messages": history}, output="answer"),
    )
    before = step.model_dump(mode="json")
    # When: scanning the linked recursive representation
    result = await evaluator(rule=source).evaluate(step)
    # Then: the call exists exactly once and the supplied Step is unchanged
    assert result.error is None
    assert result.matched is True
    assert step.model_dump(mode="json") == before


@pytest.mark.parametrize(
    "call_id,arguments,name,reason",
    [
        (None, '{"query":"value"}', "read", "need context.tool_call_id"),
        ("call-1", '{"query":"different"}', "read", "arguments do not match"),
        ("call-1", '{"query":"value"}', "other", "name does not match"),
    ],
)
@pytest.mark.asyncio
async def test_tool_link_requires_consistent_identity(
    call_id: str | None, arguments: str, name: str, reason: str
) -> None:
    # Given: a tool step that cannot reliably be linked to its assistant call
    call: JSONObject = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    }
    # When: evaluating the trace
    result = await evaluator().evaluate(trace(turn("hello", call), tool("read", call_id=call_id)))
    # Then: identity mismatches cannot silently invent a second call
    assert result.error is not None and reason in result.error


@pytest.mark.asyncio
async def test_invalid_quarry_messages_return_safe_error() -> None:
    # Given: an orphan tool response with sensitive data in its identifier
    step = trace(
        Step(
            type="llm",
            name="m",
            input=[
                {
                    "role": "tool",
                    "tool_call_id": "private-secret-id",
                    "content": "secret",
                }
            ],
        )
    )
    # When: Quarry validates the conversation
    result = await evaluator().evaluate(step)
    # Then: the scan fails without returning upstream input-bearing diagnostics
    assert result.matched is False
    assert result.error is not None and "invalid conversation" in result.error
    assert "private-secret-id" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_bad_tool_json_is_rejected_by_quarry() -> None:
    # Given: malformed tool arguments and a rule that reads their structured fields
    call: JSONObject = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "read", "arguments": "{broken-private-value"},
            }
        ],
    }
    source = """rule "Inspect arguments"
condition:
    any call in tool_calls where call.arguments.query == "value"
"""
    # When: the real pinned Quarry runtime validates those arguments
    result = await evaluator(rule=source).evaluate(trace(turn("hello", call)))
    # Then: a decode failure is not mistaken for a clean non-match
    assert result.matched is False
    assert result.error is not None and "invalid conversation" in result.error
    assert "private-value" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_divergent_history_is_rejected() -> None:
    # Given: a later history that would rewrite a previously emitted message
    step = trace(
        turn("blocked"),
        Step(
            type="llm",
            name="next",
            input=[
                {
                    "role": "user",
                    "content": "different",
                }
            ],
        ),
    )
    # When: converting cumulative histories
    result = await evaluator().evaluate(step)
    # Then: the evaluator cannot silently replace or duplicate the conversation
    assert result.matched is False
    assert result.error is not None and "exact conversation prefix" in result.error


@pytest.mark.asyncio
async def test_deep_hierarchy_is_bounded() -> None:
    # Given: more container levels than the documented conversion limit
    step = turn("blocked")
    for _ in range(34):
        step = trace(step)
    # When: evaluating the recursive hierarchy
    result = await evaluator().evaluate(step)
    # Then: the evaluator fails explicitly without omitting deeper events
    assert result.matched is False
    assert result.error is not None and "32 levels" in result.error


@pytest.mark.parametrize(
    "scan",
    [
        ScanResult(
            file_path=None,
            rule_matches=["Blocked request"],
            scan_time=0,
            timed_out_rules=["Blocked request"],
        ),
        ScanResult(file_path=None, rule_matches=[], scan_time=0, skipped_rules=["Blocked request"]),
        ScanResult(file_path=None, rule_matches=[], scan_time=0, was_truncated=True),
        ScanResult(
            file_path=None,
            rule_matches=[],
            scan_time=0,
            evaluation_errors={"Blocked request": "secret"},
        ),
        ScanResult(file_path=None, rule_matches=[], scan_time=0, evaluation_warnings=["limited"]),
    ],
)
@pytest.mark.asyncio
async def test_incomplete_scans_never_return_partial_decisions(scan: ScanResult) -> None:
    # Given: the upstream scan boundary is mocked to force rare incomplete states
    guard = evaluator()
    with patch.object(CompiledPolicy, "scan_async", new=AsyncMock(return_value=scan)):
        # When: scanning through the public evaluator
        result = await guard.evaluate(trace(turn("blocked")))
    # Then: neither partial matches nor partial clean results are authoritative
    assert result.matched is False
    assert result.error is not None and "incomplete" in result.error
    assert "secret" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_infrastructure_failure_is_error() -> None:
    # Given: the upstream boundary is mocked to simulate an unexpected runtime failure
    guard = evaluator()
    with patch.object(
        CompiledPolicy, "scan_async", new=AsyncMock(side_effect=RuntimeError("secret"))
    ):
        # When: scanning the complete trace
        result = await guard.evaluate(trace(turn("blocked")))
    # Then: infrastructure failure is visible without leaking raw diagnostics
    assert result.matched is False
    assert result.error == "Quarry evaluation failed."


@pytest.mark.asyncio
async def test_timeout_returns_error() -> None:
    # Given: the upstream boundary waits indefinitely so only our deadline can end it
    guard = evaluator(timeout_ms=10)

    async def wait_for_scan(*args: object, **kwargs: object) -> ScanResult:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    with patch.object(CompiledPolicy, "scan_async", new=wait_for_scan):
        # When: scanning with a bounded timeout
        result = await guard.evaluate(trace(turn("blocked")))
    # Then: timeout is an evaluation error rather than a policy decision
    assert result.matched is False
    assert result.error == "Quarry evaluation timed out."


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    # Given: upstream cancellation is injected at the scan boundary
    guard = evaluator()
    with patch.object(
        CompiledPolicy, "scan_async", new=AsyncMock(side_effect=asyncio.CancelledError)
    ):
        # When: the caller cancels evaluation
        with pytest.raises(asyncio.CancelledError):
            await guard.evaluate(trace(turn("blocked")))
    # Then: cached evaluation does not swallow cancellation


@pytest.mark.asyncio
async def test_later_trace_error_overrides_earlier_match() -> None:
    # Given: a session whose first trace matches and second trace is invalid
    invalid = Step(type="llm", name="m", input=[{"role": "unsupported", "content": "hello"}])
    session = Step(
        type="session", name="s", input=None, children=[trace(turn("blocked")), trace(invalid)]
    )
    # When: all independent traces are scanned
    result = await evaluator(session_mode="per_trace").evaluate(session)
    # Then: an early match cannot hide incomplete session coverage
    assert result.matched is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_message_limit_is_error_without_truncation() -> None:
    # Given: a trace longer than the configured scan limit
    guard = evaluator(max_messages=1)
    # When: converting the full trace
    result = await guard.evaluate(trace(turn("blocked", "answer")))
    # Then: no partial match is reported for a truncated conversation
    assert result.matched is False
    assert result.error is not None and "max_messages" in result.error


@pytest.mark.asyncio
async def test_cached_policy_is_reused_and_requests_are_isolated() -> None:
    # Given: the compile I/O boundary is wrapped to observe the public factory cache
    clear_evaluator_cache()
    spec = EvaluatorSpec(name="quarry.policy", config={"rule": RULE})
    with patch(
        "agent_control_evaluator_quarry.evaluator.compile_policy", wraps=compile_policy
    ) as compile_mock:
        first = get_evaluator_instance(spec)
        second = get_evaluator_instance(spec)
        # When: concurrent requests use the same cached instance
        results = await asyncio.gather(
            first.evaluate(trace(turn("blocked"))),
            second.evaluate(trace(turn("hello"))),
        )
    # Then: compilation happens once and conversation state does not cross requests
    assert first is second
    assert compile_mock.call_count == 1
    assert [result.matched for result in results] == [True, False]
    assert all(result.error is None for result in results)
    clear_evaluator_cache()


def test_installed_entry_point_loads_evaluator() -> None:
    # Given: the optional distribution is installed
    entries = entry_points(group="agent_control.evaluators", name="quarry.policy")
    # When: discovery loads the published entry point
    loaded = next(iter(entries)).load()
    # Then: the entry point and evaluator metadata agree
    assert loaded is QuarryEvaluator
    assert loaded.metadata.name == "quarry.policy"


@dataclass
class _Control:
    id: int
    name: str
    control: ControlDefinition


@pytest.mark.parametrize("step_type", ["trace", "session"])
@pytest.mark.asyncio
async def test_engine_scopes_and_context_hook(step_type: str) -> None:
    # Given: a trace/session control and a selector with no selected content
    control = ControlDefinition.model_validate(
        {
            "enabled": True,
            "execution": "server",
            "description": "Quarry integration",
            "scope": {"step_types": [step_type], "stages": ["post"]},
            "condition": {
                "selector": {"path": "context.absent"},
                "evaluator": {
                    "name": "quarry.policy",
                    "config": {
                        "rule": RULE,
                        "session_mode": "continuous",
                    },
                },
            },
            "action": {"decision": "deny"},
        }
    )
    engine = ControlEngine([_Control(1, "quarry-test", control)])
    step = trace(turn("blocked"))
    if step_type == "session":
        step = Step(type="session", name="s", input=None, children=[step])
    # When: the existing engine evaluates the configured scope and context hook
    result = await engine.process(
        EvaluationRequest(
            agent_name="test-agent",
            step=step,
            stage="post",
        )
    )
    # Then: complete Step data triggers the control through the standard engine
    assert result.is_safe is False
    assert result.matches[0].result.error is None
