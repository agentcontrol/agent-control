"""A guarded bank assistant, to show what the controls feel like in a product.

The score inspector in app.py shows what the guardrails think. This shows what
the user experiences: a chat window where some turns answer normally, some are
refused before the model is ever called, some are steered, some have a tool
call stopped, and some have the model's reply withheld.

A guarded turn screens up to four things:

    1. the user's message, at the pre stage on the chat step
    2. every tool call the model asks for, at the pre stage on the tool step
    3. nothing, if a deny already stopped the turn
    4. the model's reply, at the post stage, withheld on a deny

The turn is streamed to the page as newline-delimited JSON, one event per
step. That is not decoration: the guardrail calls take a few hundred
milliseconds each and the model takes seconds, so a single spinner makes the
controls look like the slow part when they are not.

Standard library only.

Prerequisites:
    - An Agent Control server at AGENT_CONTROL_URL, default http://localhost:8000
    - This example installed into that server's environment, so the
      evaluator is discovered through its entry point
    - python setup_controls.py has been run
    - Optionally OPENAI_API_KEY or ANTHROPIC_API_KEY, otherwise a scripted
      offline model is used

Run:
    python chat_app.py
    open http://localhost:8500
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import customers
import env_file
import llm
import observe

env_file.load()

HERE = Path(__file__).parent
PORT = int(os.getenv("CHAT_PORT", "8500"))
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000").rstrip("/")
AGENT_NAME = os.getenv("AGENT_NAME", "typesafe-jev-demo")
STEP_NAME = os.getenv("STEP_NAME", "chat")
TOOL_NAME = os.getenv("TOOL_NAME", "lookup_customers")
#: How many times the model may call a tool before the app gives up.
MAX_TOOL_STEPS = 3
#: How many returned rows the page shows before it says "and N more".
TRACE_ROW_LIMIT = 3

WITHHELD = (
    "I generated a reply, but a guardrail withheld it before it reached you. "
    "Please rephrase, or contact support if you need this information."
)

# Steering context is written for the model, not the person. When the model
# platform refuses outright there is no reply to steer, so the application
# needs its own user-facing fallback.
STEER_FALLBACK = (
    "I'm not able to advise on that one. I can put you in touch with a licensed "
    "advisor, or help with something else."
)


def _agent_controls() -> Any:
    """Fetch the agent's controls, used to stamp identity onto events."""
    request = urllib.request.Request(
        f"{SERVER_URL}/api/v1/agents/{AGENT_NAME}/controls",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _evaluate(stage: str, step: dict[str, Any]) -> dict[str, Any]:
    """Screen one step at one stage through the Agent Control server.

    The endpoint writes no observability events, so the reconstructed events
    are queued separately. Without this the Monitor tab stays empty.
    """
    payload = {"agent_name": AGENT_NAME, "stage": stage, "step": step}
    request = urllib.request.Request(
        f"{SERVER_URL}/api/v1/evaluation",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read())

    try:
        observe.record(payload, result, _agent_controls())
    except Exception:
        pass
    return result


def _breakdown(entry: dict[str, Any], *, matched: bool) -> dict[str, Any]:
    """Describe one control's Jev request and what it did with the answers.

    The evaluator reports the raw answer for every question, and alongside it
    the type, operator and threshold each question carried. Together those are
    enough to show the whole path from one request to one boolean.
    """
    result = entry.get("result") or {}
    meta = result.get("metadata") or {}
    answers = meta.get("answers") or {}
    asked = meta.get("questions") or {}
    tripped = set(meta.get("tripped") or [])
    deciding = set(meta.get("deciding") or [])

    questions = [
        {
            "id": question_id,
            "type": (asked.get(question_id) or {}).get("type"),
            "answer": answers.get(question_id),
            "operator": (asked.get(question_id) or {}).get("operator"),
            "threshold": (asked.get(question_id) or {}).get("threshold"),
            "decides": question_id in deciding,
            "tripped": question_id in tripped,
        }
        for question_id in sorted(answers)
    ]
    # What the engine actually handed to Jev, after the selector picked it out
    # of the payload. Without this the page shows a verdict with no subject.
    preview = meta.get("engine_selected_data_preview") or {}

    return {
        "control": entry.get("control_name"),
        "action": str(entry.get("action") or ""),
        "matched": matched,
        "detail": result.get("message"),
        "evaluated": preview.get("value"),
        "evaluated_truncated": bool(preview.get("truncated")),
        "answers": answers,
        "questions": questions,
        "combine": meta.get("combine"),
        "latency_ms": meta.get("latency_ms"),
        "routed": meta.get("routed_action"),
        "steering": (entry.get("steering_context") or {}).get("message"),
        "tokens": (meta.get("usage") or {}).get("input_tokens"),
    }


def _decisions(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Summarise the controls that fired, strongest action first."""
    out = [_breakdown(m, matched=True) for m in result.get("matches") or []]
    order = {"deny": 0, "steer": 1, "observe": 2}
    return sorted(out, key=lambda d: order.get(d["action"], 3))


def _screened(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Summarise every control that ran, whether or not it fired.

    The page shows these so a reader can see the answers Jev returned for the
    controls that stayed quiet, not only for the one that acted.
    """
    fired = _decisions(result)
    quiet = [
        _breakdown(entry, matched=False)
        for entry in result.get("non_matches") or []
        if (entry.get("result") or {}).get("metadata", {}).get("answers")
    ]
    return fired + sorted(quiet, key=lambda d: str(d["control"]))


def guarded_turn(message: str) -> Iterator[dict[str, Any]]:
    """Run one chat turn, reporting each step as it happens.

    The caller receives a stream of events. Every "step" event brackets one
    piece of work, so the page can show what the turn is doing and how long
    each piece took. The last event is the "result", which carries the reply
    and the full trace.

    The split matters for reading the demo: the guardrail calls are short and
    the model call is not. Without it, a slow model makes the controls look
    slow.

    Args:
        message: The user's message.

    Yields:
        Zero or more {"type": "step"} events, then one {"type": "result"}.
    """
    started = time.monotonic()
    trace: list[dict[str, Any]] = []

    def finish(**fields: Any) -> dict[str, Any]:
        """Close a turn with the fields every outcome shares."""
        return {
            "type": "result",
            "trace": trace,
            "wall_ms": int((time.monotonic() - started) * 1000),
            "provider": llm.provider(),
            "model": llm.model_name(),
            **fields,
        }

    def step(name: str, label: str, **fields: Any) -> tuple[dict[str, Any], float]:
        """Announce the start of a step, and return its event and start time."""
        return {"type": "step", "step": name, "label": label, "state": "start", **fields}, (
            time.monotonic()
        )

    def done(
        name: str, at: float, fired: list[dict[str, Any]] | None = None, **fields: Any
    ) -> dict[str, Any]:
        """Close a step, reporting how long it took and what fired."""
        return {
            "type": "step",
            "step": name,
            "state": "done",
            "ms": int((time.monotonic() - at) * 1000),
            "fired": [d["control"] for d in fired or []],
            "blocked": any(d["action"] == "deny" for d in fired or []),
            **fields,
        }

    event, at = step("screen_input", "screening the message")
    yield event
    pre = _evaluate("pre", {"type": "llm", "name": STEP_NAME, "input": message})
    pre_screened = _screened(pre)
    pre_fired = [d for d in pre_screened if d["matched"]]
    trace.append({"stage": "pre", "fired": pre_fired, "screened": pre_screened})
    yield done("screen_input", at, pre_fired)

    denied = next((d for d in pre_fired if d["action"] == "deny"), None)
    if denied:
        yield finish(
            outcome="blocked_input",
            reply=(
                "I can't help with that. A guardrail stopped this message before it "
                "reached the model."
            ),
            llm_called=False,
            control=denied["control"],
        )
        return

    steered = next((d for d in pre_fired if d["action"] == "steer"), None)
    guidance = steered["steering"] if steered else None

    conversation: list[dict[str, Any]] = [{"role": "user", "content": message}]
    tool_calls_made: list[dict[str, Any]] = []
    turn: llm.Turn | None = None

    for _ in range(MAX_TOOL_STEPS):
        event, at = step("model", "asking the model")
        yield event
        try:
            turn = llm.respond(conversation, guidance)
        except llm.PlatformRefusedError as refusal:
            # The hosted model's own filter refused the prompt. When a control
            # had already steered, its guidance is the right thing to serve
            # instead: the person still gets a useful response, not a dead end.
            yield done("model", at, refused=True)
            yield finish(
                outcome="platform_refused",
                reply=(
                    STEER_FALLBACK
                    if guidance
                    else "The model provider declined to respond to that message."
                ),
                llm_called=True,
                control=steered["control"] if steered else None,
                platform_categories=refusal.categories,
            )
            return
        except Exception as exc:  # surface provider failures in the chat window
            yield done("model", at, failed=True)
            yield finish(
                outcome="llm_error",
                reply=f"The model call failed: {type(exc).__name__}: {exc}",
                llm_called=True,
            )
            return

        yield done(
            "model",
            at,
            chose_tool=turn.tool_calls[0].name if turn.tool_calls else None,
            calls=len(turn.tool_calls),
        )

        if not turn.tool_calls:
            break

        conversation.append(llm.assistant_message(turn))

        for call in turn.tool_calls:
            # The model has chosen the arguments. Screen that call before it
            # touches the database, not the message that led to it.
            event, at = step(
                "screen_tool",
                f"screening {call.name}",
                tool=call.name,
                arguments=call.arguments,
            )
            yield event
            tool_pre = _evaluate(
                "pre", {"type": "tool", "name": call.name, "input": call.arguments}
            )
            tool_screened = _screened(tool_pre)
            tool_fired = [d for d in tool_screened if d["matched"]]
            trace.append(
                {
                    "stage": "tool",
                    "tool": call.name,
                    "arguments": call.arguments,
                    "fired": tool_fired,
                    "screened": tool_screened,
                }
            )
            yield done("screen_tool", at, tool_fired)

            blocked = next((d for d in tool_fired if d["action"] == "deny"), None)
            if blocked:
                yield finish(
                    outcome="blocked_tool",
                    reply=(
                        "I can't pull that. A guardrail stopped the lookup before it "
                        "reached the customer database."
                    ),
                    llm_called=True,
                    control=blocked["control"],
                    blocked_tool={"name": call.name, "arguments": call.arguments},
                )
                return

            event, at = step("tool", f"running {call.name}", tool=call.name)
            yield event
            rows = customers.lookup_customers(**call.arguments)
            tool_calls_made.append(
                {"name": call.name, "arguments": call.arguments, "rows": len(rows)}
            )
            conversation.append(llm.tool_message(call, rows))
            # Show what came back. This is the demo's only sight of personal
            # data entering the turn, which is what the post stage then catches.
            trace.append(
                {
                    "stage": "tool_result",
                    "tool": call.name,
                    "rows": rows[:TRACE_ROW_LIMIT],
                    "total_rows": len(rows),
                }
            )
            yield done("tool", at, rows=len(rows))
    else:
        # The loop ran out of steps without the model settling on an answer.
        turn = llm.Turn("I wasn't able to finish that lookup. Please try rephrasing.", [])

    reply = (turn.text if turn else "") or "(the model returned no text)"

    event, at = step("screen_output", "screening the reply")
    yield event
    post = _evaluate(
        "post", {"type": "llm", "name": STEP_NAME, "input": message, "output": reply}
    )
    post_screened = _screened(post)
    post_fired = [d for d in post_screened if d["matched"]]
    trace.append({"stage": "post", "fired": post_fired, "screened": post_screened})
    yield done("screen_output", at, post_fired)

    withheld = next((d for d in post_fired if d["action"] == "deny"), None)
    if withheld:
        yield finish(
            outcome="blocked_output",
            reply=WITHHELD,
            withheld_reply=reply,
            llm_called=True,
            control=withheld["control"],
            tool_calls=tool_calls_made,
        )
        return

    yield finish(
        outcome="steered" if steered else "answered",
        reply=reply,
        llm_called=True,
        control=steered["control"] if steered else None,
        tool_calls=tool_calls_made,
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _stream(self, events: Iterator[dict[str, Any]]) -> None:
        """Write events as newline-delimited JSON, flushing each one.

        The body has no Content-Length because its size is not known when the
        headers go out. The connection closes to mark the end instead.
        """
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        for event in events:
            self.wfile.write((json.dumps(event) + "\n").encode())
            self.wfile.flush()

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "chat.html").read_bytes(), "text/html; charset=utf-8")
            return
        if self.path == "/api/info":
            self._json(
                200,
                {
                    "provider": llm.provider(),
                    "model": llm.model_name(),
                    "server": SERVER_URL,
                    "agent": AGENT_NAME,
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return

        message = str(payload.get("message", "")).strip()
        if not message:
            self._json(400, {"error": "message is required"})
            return

        def events() -> Iterator[dict[str, Any]]:
            """Run the turn, turning a mid-stream failure into a final event.

            The headers are already sent by then, so an error cannot become an
            HTTP status. It is reported as the last event instead.
            """
            try:
                yield from guarded_turn(message)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                yield {"type": "error", "error": f"Agent Control returned {exc.code}: {detail}"}
            except Exception as exc:
                yield {"type": "error", "error": f"{type(exc).__name__}: {exc}"}

        self._stream(events())


def main() -> None:
    """Check Agent Control is reachable, then serve the chat demo."""
    try:
        urllib.request.urlopen(f"{SERVER_URL}/api/v1/agents/{AGENT_NAME}", timeout=10).read()
    except Exception as exc:
        raise SystemExit(
            f"Cannot reach Agent Control at {SERVER_URL} for agent {AGENT_NAME!r}.\n"
            f"  {type(exc).__name__}: {exc}\n"
            "Start the server and run: python setup_controls.py"
        ) from exc

    observing = observe.start(AGENT_NAME, SERVER_URL, STEP_NAME, TOOL_NAME)

    which = llm.provider()
    print(f"Guarded chat on http://localhost:{PORT}")
    print(f"  observability {'on, events appear in the Monitor tab' if observing else 'off'}")
    print(f"  agent control {SERVER_URL}  agent {AGENT_NAME}")
    print(f"  model         {llm.model_name()} ({which})")
    if which == "offline":
        print("  no OPENAI_API_KEY or ANTHROPIC_API_KEY set, using the scripted offline model")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
