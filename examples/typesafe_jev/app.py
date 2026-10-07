"""Web playground for TypeSafe Jev controls, served from an Agent Control server.

This is a thin client. It holds no controls and runs no engine. Each message is
POSTed to the server's /api/v1/evaluation endpoint, which loads the agent's
controls from its database and runs them. Edit a control in the Agent Control
UI and the next check here reflects it.

Standard library only.

Prerequisites:
    - An Agent Control server at AGENT_CONTROL_URL, default http://localhost:8000
    - This example installed into that server's environment, so the
      evaluator is discovered through its entry point
    - TYPESAFE_API_KEY set in the server's environment, not here
    - python setup_controls.py has been run

Run:
    python app.py
    open http://localhost:8400
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import env_file
import observe

env_file.load()

HERE = Path(__file__).parent
PORT = int(os.getenv("PORT", "8400"))
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000").rstrip("/")
AGENT_NAME = os.getenv("AGENT_NAME", "typesafe-jev-demo")
STEP_NAME = os.getenv("STEP_NAME", "chat")
TOOL_NAME = os.getenv("TOOL_NAME", "lookup_customers")


def _post(path: str, payload: dict[str, Any], timeout: float = 120.0) -> Any:
    """POST JSON to the Agent Control server and return the decoded response."""
    request = urllib.request.Request(
        f"{SERVER_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _get(path: str, timeout: float = 30.0) -> Any:
    """GET JSON from the Agent Control server."""
    request = urllib.request.Request(
        f"{SERVER_URL}{path}", headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _row(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten one ControlMatch into what the page renders.

    A control asks a battery, so one control carries several answers. The page
    shows the whole vector plus the routed outcome, the way the cookbook's
    interpret() does.
    """
    result = entry.get("result") or {}
    metadata = result.get("metadata") or {}
    usage = metadata.get("usage") or {}
    return {
        "control": entry.get("control_name"),
        "action": str(entry.get("action") or ""),
        "matched": result.get("matched"),
        "answers": metadata.get("answers") or {},
        "routed_action": metadata.get("routed_action"),
        "contributions": metadata.get("contributions") or {},
        "severity_escalated": bool(metadata.get("severity_escalated")),
        "decide_mode": metadata.get("decide_mode"),
        "decided_by": metadata.get("decided_by"),
        "confidence": round(result.get("confidence", 0.0), 3),
        "latency_ms": metadata.get("latency_ms"),
        "input_tokens": usage.get("input_tokens"),
        "message": result.get("message"),
        "error": result.get("error"),
    }


def _screen(stage: str, step: dict[str, Any], configured: int) -> dict[str, Any]:
    """Screen one step at one stage and normalise the response."""
    payload = {"agent_name": AGENT_NAME, "stage": stage, "step": step}
    started = time.monotonic()
    response = _post("/api/v1/evaluation", payload)
    wall_ms = int((time.monotonic() - started) * 1000)

    # The endpoint writes no observability events, so queue them separately.
    try:
        observe.record(payload, response, _get(f"/api/v1/agents/{AGENT_NAME}/controls"))
    except Exception:
        pass

    matches = [_row(m) for m in (response.get("matches") or [])]
    non_matches = [_row(m) for m in (response.get("non_matches") or [])]
    rows = matches + non_matches

    return {
        "stage": stage,
        "is_safe": response.get("is_safe"),
        "wall_ms": wall_ms,
        "controls_configured": configured,
        "controls_run": len(rows),
        "controls_cancelled": max(0, configured - len(rows)),
        "fired": len(matches),
        "rows": rows,
    }


def check(message: str, reply: str = "") -> dict[str, Any]:
    """Screen a user message, and the model's reply when one is supplied.

    Controls are scoped to a stage. An input-side control runs at ``pre`` and
    an output-side control runs at ``post``, so a reply is the only way to
    reach the post-stage controls.

    The engine short-circuits on the first deny within a stage: it cancels any
    control still running and those produce no result. So a denied message can
    report fewer controls than are attached. That is by design, not an error.
    """
    try:
        summaries = control_summaries()
    except Exception:
        summaries = []

    def configured_for(stage: str) -> int:
        return sum(1 for c in summaries if stage in (c["stages"] or [stage]))

    step: dict[str, Any] = {"type": "llm", "name": STEP_NAME, "input": message}
    stages = [_screen("pre", step, configured_for("pre"))]

    if reply.strip():
        post_step = {**step, "output": reply}
        stages.append(_screen("post", post_step, configured_for("post")))

    return {
        "is_safe": all(s["is_safe"] for s in stages),
        "stages": stages,
        "server": SERVER_URL,
        "agent": AGENT_NAME,
    }


def control_summaries() -> list[dict[str, Any]]:
    """List the agent's controls as the server currently has them."""
    payload = _get(f"/api/v1/agents/{AGENT_NAME}/controls")
    items = payload.get("controls", payload) if isinstance(payload, dict) else payload
    summaries = []
    for item in items:
        definition = item.get("control", item)
        evaluator = (definition.get("condition") or {}).get("evaluator") or {}
        config = evaluator.get("config") or {}
        decide = config.get("decide") or {}
        summaries.append(
            {
                "name": item.get("name"),
                "decision": str((definition.get("action") or {}).get("decision", "")),
                "evaluator": evaluator.get("name"),
                "questions": sorted(config.get("questions") or {}),
                "mode": decide.get("mode", "threshold"),
                "matches_on": decide.get("matches_on"),
                "stages": (definition.get("scope") or {}).get("stages") or [],
            }
        )
    return summaries


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

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        if self.path == "/api/controls":
            try:
                self._json(200, {"controls": control_summaries(), "server": SERVER_URL,
                                 "agent": AGENT_NAME})
            except Exception as exc:
                self._json(502, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/check":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return

        message = str(payload.get("message", "")).strip()
        reply = str(payload.get("reply", ""))
        if not message:
            self._json(400, {"error": "message is required"})
            return

        try:
            self._json(200, check(message, reply))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            self._json(502, {"error": f"server returned {exc.code}: {detail}"})
        except Exception as exc:
            self._json(502, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    """Check the server is reachable, then serve the playground."""
    try:
        summaries = control_summaries()
    except Exception as exc:
        raise SystemExit(
            f"Cannot reach Agent Control at {SERVER_URL} for agent {AGENT_NAME!r}.\n"
            f"  {type(exc).__name__}: {exc}\n"
            "Start the server and run: python setup_controls.py"
        ) from exc

    observing = observe.start(AGENT_NAME, SERVER_URL, STEP_NAME, TOOL_NAME)
    print(f"TypeSafe Jev playground on http://localhost:{PORT}")
    print(f"  observability {'on' if observing else 'off'}")
    print(f"  server   {SERVER_URL}")
    print(f"  agent    {AGENT_NAME}")
    print(f"  controls {len(summaries)} loaded from the server")
    if not summaries:
        print("  (no controls attached - run: python setup_controls.py)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
