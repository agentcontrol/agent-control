"""A very small LLM client for the chat demo.

Three providers, picked from the environment so the demo runs with whatever
you have. Standard library only, so there is nothing to install.

    LLM_GATEWAY_URL     calls any OpenAI-compatible endpoint, with optional
                        OAuth2 client-credentials auth. Covers corporate
                        gateways and Azure-style deployments.
    OPENAI_API_KEY      calls OpenAI, matching the other examples in this repo
    ANTHROPIC_API_KEY   calls Anthropic
    none of those       a scripted offline model, so the guardrail flow still
                        demos without a key

The offline model deliberately answers one question unsafely, so the
output-side control has something to catch.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, NamedTuple

import customers
import env_file

# These constants read the environment at import time, so the .env has to be
# loaded before them. Doing it here means import order in the callers does not
# matter.
env_file.load()

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

# An OpenAI-compatible endpoint. {model} is substituted if the URL contains it,
# which is how Azure-style deployment paths work.
GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "")
GATEWAY_MODEL = os.getenv("LLM_MODEL", "")
# Header carrying the credential. OpenAI uses "Authorization"; many gateways
# use "api-key".
GATEWAY_AUTH_HEADER = os.getenv("LLM_AUTH_HEADER", "api-key")
GATEWAY_AUTH_PREFIX = os.getenv("LLM_AUTH_PREFIX", "")
# Either a static key, or OAuth2 client credentials exchanged for a token.
GATEWAY_API_KEY = os.getenv("LLM_API_KEY", "")
GATEWAY_TOKEN_URL = os.getenv("LLM_TOKEN_URL", "")
GATEWAY_CLIENT_ID = os.getenv("LLM_CLIENT_ID", "")
GATEWAY_CLIENT_SECRET = os.getenv("LLM_CLIENT_SECRET", "")
# Extra JSON merged into the request body, for gateways that require their own
# fields such as an application key.
GATEWAY_EXTRA_BODY = os.getenv("LLM_EXTRA_BODY", "")

# An exchanged token is reused until shortly before it expires.
_gateway_token: tuple[str, float] | None = None
_gateway_lock = threading.Lock()

SYSTEM_PROMPT = (
    "You are a support assistant for Northwind Bank, a consumer bank. Answer "
    "briefly and plainly.\n\n"
    "You can read the bank's customer database with the lookup_customers tool. "
    "Use it whenever you need customer data, and never invent customer data. "
    "The person you are chatting with is "
    f"{customers.CURRENT_CUSTOMER}, account NB-1001.\n\n"
    "Answer the question the user actually asked, using the fields you "
    "retrieved."
)

#: The one tool the assistant has. The bulk-export control screens calls to it,
#: which is only meaningful because the tool will really answer them.
LOOKUP_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "lookup_customers",
        "description": "Read customer records from Northwind Bank's customer database.",
        "parameters": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Fields to return. One or more of: account_id, name, email, "
                        "phone, address, region, account_type, balance, ssn, card."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Return only the customer with this name.",
                },
                "region": {
                    "type": "string",
                    "description": (
                        "Return only customers in this region: Northeast, Southeast, "
                        "Midwest, or West. Use 'all' for every region."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return. Omit for no limit.",
                },
            },
            "required": ["fields"],
        },
    },
}


class ToolCall(NamedTuple):
    """One tool call the model asked for.

    Attributes:
        id: The provider's identifier, needed to return the result.
        name: The tool name.
        arguments: The decoded arguments. This is what a control screens.
    """

    id: str
    name: str
    arguments: dict[str, Any]


class Turn(NamedTuple):
    """One model response: either text, or tool calls, or both.

    Attributes:
        text: The assistant's text. Empty when it only asked for tools.
        tool_calls: The tool calls it asked for. Empty when it answered.
    """

    text: str
    tool_calls: list[ToolCall]


class PlatformRefusedError(Exception):
    """The model platform refused the prompt before the model saw it.

    Hosted models often sit behind their own content filter. A refusal there
    is not an application error: the platform simply will not engage with the
    text. It is reported separately so a guardrail decision is not confused
    with an outage.
    """

    def __init__(self, reason: str, categories: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.categories = categories or {}


def _raise_if_filtered(error: urllib.error.HTTPError) -> None:
    """Convert a platform content-filter rejection into PlatformRefusedError."""
    if error.code != 400:
        return
    try:
        body = json.loads(error.read().decode(errors="replace"))
    except Exception:
        return
    detail = body.get("error") or {}
    if detail.get("code") != "content_filter":
        return
    results = (detail.get("innererror") or {}).get("content_filter_result") or {}
    tripped = {
        name: info.get("severity")
        for name, info in results.items()
        if isinstance(info, dict) and info.get("filtered")
    }
    raise PlatformRefusedError(detail.get("message", "content filtered"), tripped)


def provider() -> str:
    """Return which provider this process will use."""
    if GATEWAY_URL:
        return "gateway"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "offline"


def model_name() -> str:
    """Return the model identifier for the active provider."""
    return {
        "gateway": GATEWAY_MODEL or "gateway",
        "openai": OPENAI_MODEL,
        "anthropic": ANTHROPIC_MODEL,
    }.get(provider(), "offline-script")


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        _raise_if_filtered(error)
        raise


def _gateway_credential() -> str:
    """Return the gateway credential, exchanging client credentials if needed."""
    if GATEWAY_API_KEY:
        return GATEWAY_API_KEY
    if not (GATEWAY_TOKEN_URL and GATEWAY_CLIENT_ID and GATEWAY_CLIENT_SECRET):
        raise RuntimeError(
            "Set LLM_API_KEY, or LLM_TOKEN_URL with LLM_CLIENT_ID and LLM_CLIENT_SECRET."
        )

    global _gateway_token
    with _gateway_lock:
        if _gateway_token is not None and time.time() < _gateway_token[1]:
            return _gateway_token[0]

        basic = base64.b64encode(
            f"{GATEWAY_CLIENT_ID}:{GATEWAY_CLIENT_SECRET}".encode()
        ).decode()
        request = urllib.request.Request(
            GATEWAY_TOKEN_URL,
            data=b"grant_type=client_credentials",
            headers={
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())

        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Token response had no access_token: {data}")
        # Refresh a minute early rather than racing the expiry.
        _gateway_token = (token, time.time() + int(data.get("expires_in", 3600)) - 60)
        return token


def _offline(conversation: list[dict[str, Any]]) -> Turn:
    """A scripted stand-in used when no API key is set.

    It imitates the two things the real model does: it asks for the tool when
    the message wants customer data, and it reads the rows back afterwards.
    """
    if conversation and conversation[-1].get("role") == "tool":
        rows = json.loads(str(conversation[-1].get("content") or "[]"))
        if not rows:
            return Turn("I could not find a matching customer.", [])
        parts = [", ".join(f"{k}: {v}" for k, v in row.items()) for row in rows[:3]]
        return Turn("Here is what I found. " + " | ".join(parts), [])

    message = ""
    for entry in conversation:
        if entry.get("role") == "user":
            message = str(entry.get("content") or "")
    lower = message.lower()

    def call(arguments: dict[str, Any]) -> Turn:
        return Turn("", [ToolCall("offline-1", "lookup_customers", arguments)])

    if any(w in lower for w in ("every", "all customers", "mailing list", "export")):
        region = "Northeast" if "northeast" in lower else "all"
        return call({"region": region, "fields": ["name", "email", "address"]})
    if any(w in lower for w in ("ssn", "social security", "card number")):
        return call({"name": customers.CURRENT_CUSTOMER, "fields": ["ssn", "card"]})
    if "address" in lower:
        return call({"name": customers.CURRENT_CUSTOMER, "fields": ["address"]})
    if any(w in lower for w in ("balance", "invoice", "charge", "billing")):
        return call({"name": customers.CURRENT_CUSTOMER, "fields": ["balance", "account_type"]})
    return Turn(
        "Thanks for reaching out. I can help with balances, payments, and your account.", []
    )


def _parse_openai_turn(message: dict[str, Any]) -> Turn:
    """Read an OpenAI-shaped assistant message into a Turn."""
    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(str(raw.get("id") or ""), str(function.get("name") or ""), arguments))
    return Turn((message.get("content") or "").strip(), calls)


def _to_anthropic(conversation: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the OpenAI-shaped conversation into Anthropic blocks."""
    out: list[dict[str, Any]] = []
    for entry in conversation:
        role = entry.get("role")
        if role == "user":
            out.append(
                {"role": "user", "content": [{"type": "text", "text": entry.get("content")}]}
            )
        elif role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": entry.get("tool_call_id"),
                            "content": str(entry.get("content") or ""),
                        }
                    ],
                }
            )
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if entry.get("content"):
                blocks.append({"type": "text", "text": entry["content"]})
            for raw in entry.get("tool_calls") or []:
                function = raw.get("function") or {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": raw.get("id"),
                        "name": function.get("name"),
                        "input": json.loads(function.get("arguments") or "{}"),
                    }
                )
            out.append({"role": "assistant", "content": blocks})
    return out


def assistant_message(turn: Turn) -> dict[str, Any]:
    """Render a Turn back into a conversation entry, so tools can be answered."""
    entry: dict[str, Any] = {"role": "assistant", "content": turn.text or None}
    if turn.tool_calls:
        entry["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in turn.tool_calls
        ]
    return entry


def tool_message(call: ToolCall, rows: Any) -> dict[str, Any]:
    """Render a tool result into a conversation entry."""
    return {"role": "tool", "tool_call_id": call.id, "content": json.dumps(rows, default=str)}


def respond(conversation: list[dict[str, Any]], guidance: str | None = None) -> Turn:
    """Ask the model for the next turn, given the conversation so far.

    The caller owns the conversation and the tool loop. That is deliberate:
    every tool call has to pass through Agent Control before it runs, so the
    provider cannot be left to resolve tools on its own.

    Args:
        conversation: Messages in OpenAI shape. The caller appends to this.
        guidance: Steering guidance from a control, prepended to the system
            prompt so the model adjusts rather than answering the literal
            request.

    Returns:
        The model's next turn: text, tool calls, or both.

    Raises:
        PlatformRefusedError: The provider's own content filter rejected the prompt.
    """
    system = SYSTEM_PROMPT
    if guidance:
        system = f"IMPORTANT GUIDANCE: {guidance}\n\n{system}"

    which = provider()
    if which == "offline":
        if guidance:
            return Turn(
                "I can't advise on what to do with your money, but I don't want to leave "
                "you without anything. I can explain how our accounts work, or put you in "
                "touch with a licensed advisor.",
                [],
            )
        return _offline(conversation)

    if which == "gateway":
        body: dict[str, Any] = {
            "messages": [{"role": "system", "content": system}, *conversation],
            "tools": [LOOKUP_TOOL],
        }
        if GATEWAY_MODEL and "{model}" not in GATEWAY_URL:
            body["model"] = GATEWAY_MODEL
        if GATEWAY_EXTRA_BODY:
            body.update(json.loads(GATEWAY_EXTRA_BODY))

        credential = _gateway_credential()
        data = _post_json(
            GATEWAY_URL.replace("{model}", GATEWAY_MODEL),
            body,
            {
                GATEWAY_AUTH_HEADER: f"{GATEWAY_AUTH_PREFIX}{credential}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        return _parse_openai_turn(data["choices"][0]["message"])

    if which == "openai":
        data = _post_json(
            "https://api.openai.com/v1/chat/completions",
            {
                "model": OPENAI_MODEL,
                "messages": [{"role": "system", "content": system}, *conversation],
                "tools": [LOOKUP_TOOL],
                "max_tokens": 400,
            },
            {
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
        )
        return _parse_openai_turn(data["choices"][0]["message"])

    function = LOOKUP_TOOL["function"]
    data = _post_json(
        f"{os.getenv('ANTHROPIC_BASE_URL', 'https://api.anthropic.com').rstrip('/')}/v1/messages",
        {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 400,
            "system": system,
            "messages": _to_anthropic(conversation),
            "tools": [
                {
                    "name": function["name"],
                    "description": function["description"],
                    "input_schema": function["parameters"],
                }
            ],
        },
        {
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    calls = [
        ToolCall(str(b.get("id") or ""), str(b.get("name") or ""), dict(b.get("input") or {}))
        for b in data.get("content", [])
        if b.get("type") == "tool_use"
    ]
    return Turn(text.strip(), calls)
