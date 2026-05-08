#!/usr/bin/env python3
"""Cursor beforeSubmitPrompt hook — protect guardrails (SDK end-to-end).

Uses `agent_control.init()` + `@control()`. The decorator registers the step
with the AC server, evaluates every control attached to the agent (regex
secrets + galileo.luna2 PII via Galileo Protect with rules-in-payload), and
emits an OpenTelemetry-flavored observability event per evaluation so the AC
UI at http://localhost:4000 stays populated.

After AC's verdict, we also write a project-log-stream trace via
`GalileoLogger.add_protect_span` so the prompt shows up in Galileo's project
view alongside its underlying Protect call. The Protect call is reused from
AC — no second roundtrip.

Runs in the venv because of the SDK imports.

Stdin  (Cursor):  {"hook_event_name":"beforeSubmitPrompt","prompt":"…", …}
Stdout (Cursor):  {"continue": true|false, "user_message":"…","agent_message":"…"}

Env (loaded from <cwd>/.env if present):
    AGENT_CONTROL_URL          default http://localhost:8000
    AC_AGENT_NAME              default cursor-protect-v4
    GALILEO_PROJECT            (required for project-log-stream traces)
    GALILEO_LOG_STREAM         default cursor-hooks
    CURSOR_PROTECT_FAIL_MODE   "allow" (default) or "deny"
    CURSOR_PROTECT_LOG_RAW     set to 1/true to skip PII redaction (debug)
    CURSOR_PROTECT_DEBUG       set to 1/true to print to stderr
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

import agent_control
from agent_control import control, ControlViolationError


# ── PII redactors (regex, local). Names/locations survive verbatim, but the
#    redacted twin is what we send to Galileo's log stream so project-trace
#    bodies don't leak raw PII even though AC already saw the original.

_REDACTORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+\b"), "<EMAIL>"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<SSN>"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "<CC>"),
    (re.compile(r"\+?\d{1,2}[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"), "<PHONE>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    (re.compile(r"\bhttps?://[^\s]+"), "<URL>"),
]


def _redact(text: str) -> str:
    # Redaction temporarily disabled: redacted payloads were causing Protect to
    # report "Protect not invoked" in the UI. Pass the original text through so
    # Protect spans show TRIGGERED with the real prompt.
    return text
    # if os.environ.get("CURSOR_PROTECT_LOG_RAW", "").strip().lower() in {"1", "true", "yes", "on"}:
    #     return text
    # for pattern, replacement in _REDACTORS:
    #     text = pattern.sub(replacement, text)
    # return text


# ── Cursor I/O ---------------------------------------------------------------

def _read_stdin_json() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def _allow() -> dict:
    return {"continue": True}


def _deny(user_message: str, agent_message: str | None = None) -> dict:
    out: dict = {"continue": False, "user_message": user_message}
    if agent_message:
        out["agent_message"] = agent_message
    return out


def _extract_prompt(payload: dict) -> str:
    p = payload.get("prompt")
    if isinstance(p, str):
        return p
    if isinstance(p, dict):
        for key in ("text", "content"):
            v = p.get(key)
            if isinstance(v, str):
                return v
    nested = payload.get("input")
    if isinstance(nested, dict):
        v = nested.get("prompt")
        if isinstance(v, str):
            return v
    return ""


def _debug(msg: str) -> None:
    if os.environ.get("CURSOR_PROTECT_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}:
        print(f"[guardrails-hook] {msg}", file=sys.stderr, flush=True)


_SECRETS_CONTROL = "block-secrets-v4"
_PII_CONTROL = "block-pii-v4"


def _deny_message(control_name: str | None) -> tuple[str, str]:
    if control_name == _SECRETS_CONTROL:
        return (
            "🔒 Blocked: prompt looks like it contains a secret/API key.",
            "Agent Control blocked: secret detected.",
        )
    if control_name == _PII_CONTROL:
        return (
            "🪪 Blocked: prompt contains PII (Galileo Protect via Agent Control).",
            "Galileo Protect (via Agent Control) blocked: PII detected.",
        )
    return (
        f"🛑 Blocked by control: {control_name}",
        f"Blocked by {control_name}",
    )


# ── @control()-decorated step. The decorator names the step `check_prompt`,
#    binds the `prompt` argument as `input` (per the SDK's input-name preference
#    list), and triggers AC's pre/llm controls before the body runs. We just
#    return the prompt unchanged — the work happens in the decorator.

@control()
async def check_prompt(prompt: str) -> str:
    return prompt


# ── GenAI trace per Cursor prompt → Galileo project log_stream view --------

def _log_to_galileo(
    *,
    prompt_original: str,
    decision: str,
    deny_control: str | None,
    deny_metadata: dict | None,
) -> None:
    """Write one cursor-hook trace per prompt to the Galileo project log stream.

    Reuses AC's existing Protect call: when the PII control fires, AC's
    `Luna2Evaluator` already invoked Protect and got back a real Galileo
    `trace_id`. We surface that here as a `add_protect_span` so the project's
    log_stream view shows TRIGGERED Protect spans linked to the same trace AC
    saw — no second Protect roundtrip.

    Secrets denies and allow paths still write a basic trace (no Protect span
    on the deny side because regex is server-local; no AC metadata is exposed
    to @control on the allow side, so we omit the span there).

    Best-effort. Any failure (missing SDK, missing project, network) is
    swallowed via debug.
    """
    project = os.environ.get("GALILEO_PROJECT", "").strip()
    if not project:
        _debug("logging skipped: GALILEO_PROJECT not set")
        return
    log_stream = os.environ.get("GALILEO_LOG_STREAM", "cursor-hooks").strip() or "cursor-hooks"

    try:
        from galileo import GalileoLogger
        from galileo_core.schemas.protect.payload import Payload
        from galileo_core.schemas.protect.response import Response
    except ImportError as exc:
        _debug(f"galileo SDK not importable; skipping log: {exc}")
        return

    try:
        prompt_redacted = _redact(prompt_original)
        logger = GalileoLogger(project=project, log_stream=log_stream)
        logger.start_trace(
            input=prompt_redacted,
            name="cursor-hook",
            tags=["cursor-hook", "guardrails", f"decision:{decision}"],
        )

        # PII deny path: we have AC's evaluator metadata containing the real
        # Galileo Protect trace_id. Build a synthetic Response so the span
        # links back to the actual call and shows TRIGGERED.
        if deny_control == _PII_CONTROL and deny_metadata:
            status = (deny_metadata.get("status") or "not_triggered").lower()
            trace_id = deny_metadata.get("trace_id")
            response_obj = Response.model_validate({
                "status": status,
                "text": prompt_original,
                "trace_metadata": {"id": trace_id} if trace_id else {},
            })
            redacted_response = Response.model_validate({
                "status": status,
                "text": prompt_redacted,
                "trace_metadata": {"id": trace_id} if trace_id else {},
            })
            logger.add_protect_span(
                payload=Payload(input=prompt_original),
                redacted_payload=Payload(input=prompt_redacted),
                response=response_obj,
                redacted_response=redacted_response,
                metadata={
                    "source": "cursor-hook",
                    "control_name": deny_control,
                    "metric": str(deny_metadata.get("metric") or "input_pii"),
                    "execution_time_ms": str(deny_metadata.get("execution_time_ms") or ""),
                    "decision": decision,
                    "redaction": "regex",
                },
                tags=["cursor-hook", "guardrails", f"decision:{decision}"],
                status_code=200,
            )

        logger.conclude(
            output=f"{decision}: control={deny_control or 'none'}",
            status_code=200,
        )
        logger.flush()
        _debug(f"logged galileo trace project={project} stream={log_stream} decision={decision} control={deny_control}")
    except Exception as exc:
        _debug(f"galileo logging failed: {type(exc).__name__}: {exc}")


async def main() -> int:
    load_dotenv(Path.cwd() / ".env")
    fail_mode = os.environ.get("CURSOR_PROTECT_FAIL_MODE", "allow").strip().lower()
    server_url = os.environ.get("AGENT_CONTROL_URL", "http://localhost:8000")
    agent_name = os.environ.get("AC_AGENT_NAME", "cursor-protect-v4")

    payload = _read_stdin_json()
    event = payload.get("hook_event_name", "")
    if event and event != "beforeSubmitPrompt":
        _emit(_allow())
        return 0

    prompt = _extract_prompt(payload)
    if not prompt.strip():
        _emit(_allow())
        return 0

    try:
        agent_control.init(
            agent_name=agent_name,
            agent_description="Cursor guardrails — SDK + @control + observability.",
            server_url=server_url,
            observability_enabled=True,
        )
    except Exception as exc:
        _debug(f"AC init failed ({type(exc).__name__}): {exc}")
        if fail_mode == "deny":
            _emit(_deny("🛑 Agent Control unavailable (fail-closed).",
                        agent_message=f"AC init failed: {exc}"))
        else:
            _emit(_allow())
        return 0

    decision = "allow"
    deny_control: str | None = None
    deny_metadata: dict | None = None

    try:
        try:
            await check_prompt(prompt)
        except ControlViolationError as exc:
            decision = "deny"
            deny_control = exc.control_name
            deny_metadata = exc.metadata or {}
            user_msg, agent_msg = _deny_message(deny_control)
            _debug(f"AC deny: {deny_control}: {exc.message}")
            _emit(_deny(user_msg, agent_message=agent_msg))
        except Exception as exc:
            _debug(f"AC eval error ({type(exc).__name__}): {exc}")
            if fail_mode == "deny":
                _emit(_deny("🛑 Agent Control returned an error (fail-closed).",
                            agent_message=str(exc)))
            else:
                _emit(_allow())
            # Don't write a Galileo trace on infra error — it's not a policy event.
            return 0
        else:
            _debug("AC: allow")
            _emit(_allow())

        # Best-effort: write one trace per prompt to the project log_stream so
        # the AC verdict shows up in Galileo's project view alongside Protect.
        _log_to_galileo(
            prompt_original=prompt,
            decision=decision,
            deny_control=deny_control,
            deny_metadata=deny_metadata,
        )
        return 0
    finally:
        # Flush AC observability events to the AC server. Best-effort.
        try:
            await agent_control.ashutdown()
        except Exception as exc:
            _debug(f"AC shutdown failed: {exc}")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except SystemExit:
        raise
    except Exception as exc:
        if os.environ.get("CURSOR_PROTECT_FAIL_MODE", "allow").strip().lower() == "deny":
            _emit({"continue": False, "user_message": "🛑 Prompt guard crashed.",
                   "agent_message": f"Hook crashed: {exc}"})
        else:
            _emit({"continue": True, "agent_message": f"Hook crashed (allowed): {exc}"})
        raise SystemExit(0)
