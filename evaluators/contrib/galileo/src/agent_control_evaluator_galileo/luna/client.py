"""Direct HTTP client for Galileo Luna scorer invocation."""

from __future__ import annotations

import logging
import os
import ssl
from asyncio import Lock
from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import new as hmac_new
from json import dumps
from time import time
from typing import Literal, cast, get_args
from urllib.parse import urlsplit

import httpx
from agent_control_models import (
    DocumentEvidence,
    JSONObject,
    JSONValue,
    Step,
    ToolCallEvidence,
)
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from .config import ScorerInvokeConfig

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECS = 10.0
SERVER_TIMEOUT_RATIO = 0.8
DEFAULT_INTERNAL_TOKEN_TTL_SECS = 3600
DEFAULT_LUNA_SCORER_INVOKE_PATH = "/api/v1/scorers/invoke"
LUNA_INVOKE_URL_ENV = "GALILEO_LUNA_INVOKE_URL"
LUNA_INVOKE_CA_FILE_ENV = "GALILEO_LUNA_INVOKE_CA_FILE"
AUTH_UPSTREAM_CA_FILE_ENV = "AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE"

# Headers that must never be forwarded to the Luna invoke endpoint (checked case-insensitively).
_BLOCKED_REQUEST_HEADERS = frozenset({"galileo-api-key"})

# Keep pooled-connection reuse shorter than typical server keepalive/worker
# recycle windows so requests do not pick up sockets the server already closed.
DEFAULT_KEEPALIVE_EXPIRY_SECS = 1.0
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_CLIENT_POOL_SIZE = 1
LUNA_KEEPALIVE_EXPIRY_ENV = "GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS"
LUNA_MAX_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_CONNECTIONS"
LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV = "GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS"
LUNA_CLIENT_POOL_SIZE_ENV = "GALILEO_LUNA_CLIENT_POOL_SIZE"

# The public Galileo scorer-invocation contract accepts these record types. The
# Agent Control Step remains extensible; unsupported nested records are rejected
# only when crossing this provider boundary.
ScorerInvokeRecordType = Literal[
    "llm",
    "retriever",
    "tool",
    "workflow",
    "agent",
    "control",
    "trace",
    "session",
]
SUPPORTED_SCORER_INVOKE_RECORD_TYPES = frozenset(get_args(ScorerInvokeRecordType))


def _b64url(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _internal_auth_token(
    api_secret: str,
    ttl_seconds: int = DEFAULT_INTERNAL_TOKEN_TTL_SECS,
) -> str:
    """Create the internal JWT expected by Luna scorer invoke routes."""
    now = int(time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "internal": True,
        "scope": "scorers.invoke",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    signing_input = ".".join(
        [
            _b64url(dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url(dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac_new(api_secret.encode("utf-8"), signing_input.encode("ascii"), sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _normalize_luna_invoke_url(raw_url: str) -> str:
    """Use full invoke URLs as-is and append the default path to bare service roots."""
    url = raw_url.strip().rstrip("/")
    parsed = urlsplit(url)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return url
    return f"{url}{DEFAULT_LUNA_SCORER_INVOKE_PATH}"


def _load_float_env(env_name: str, default: float) -> float:
    raw = os.getenv(env_name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name}={raw!r} is not a number.") from exc


def _load_int_env(env_name: str, default: int) -> int:
    raw = os.getenv(env_name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name}={raw!r} is not an integer.") from exc


def _validate_connection_config(
    *,
    keepalive_expiry_seconds: float,
    max_connections: int,
    max_keepalive_connections: int,
    client_pool_size: int,
) -> None:
    if keepalive_expiry_seconds < 0:
        raise ValueError(
            f"{LUNA_KEEPALIVE_EXPIRY_ENV}={keepalive_expiry_seconds} "
            "must be greater than or equal to 0."
        )
    if max_connections <= 0:
        raise ValueError(f"{LUNA_MAX_CONNECTIONS_ENV}={max_connections} must be greater than 0.")
    if max_keepalive_connections < 0:
        raise ValueError(
            f"{LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV}={max_keepalive_connections} "
            "must be greater than or equal to 0."
        )
    if max_keepalive_connections > max_connections:
        raise ValueError(
            f"{LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV}={max_keepalive_connections} "
            f"must be less than or equal to {LUNA_MAX_CONNECTIONS_ENV}={max_connections}."
        )
    if client_pool_size <= 0:
        raise ValueError(f"{LUNA_CLIENT_POOL_SIZE_ENV}={client_pool_size} must be greater than 0.")


def _as_float_or_none(value: JSONValue) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _has_value(value: JSONValue) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def _has_structured_evidence(step: Step | None) -> bool:
    """Return whether a step contains evidence that can stand in for text."""
    if step is None:
        return False
    return any(
        value is not None and len(value) > 0
        for value in (step.documents, step.tool_calls, step.children, step.history)
    )


def _effective_scorer_timeout(
    config: ScorerInvokeConfig,
    *,
    http_timeout_seconds: float,
) -> ScorerInvokeConfig:
    """Resolve a server execution timeout that expires before the HTTP request.

    The server execution budget defaults to 80% of the caller's HTTP deadline,
    leaving time for the remote service to serialize and return the result. Explicit caller
    overrides are preserved only when they maintain the same ordering.

    Args:
        config: Caller-provided scorer-invoke configuration.
        http_timeout_seconds: Agent Control's HTTP request deadline in seconds.

    Returns:
        A scorer-invoke configuration with an effective execution timeout.

    Raises:
        ValueError: If either deadline is invalid or the explicit server timeout
            is not shorter than the HTTP deadline.
    """
    if http_timeout_seconds <= 0:
        raise ValueError("HTTP timeout must be greater than 0 seconds.")

    server_timeout = config.request_timeout_seconds
    if server_timeout is None:
        server_timeout = http_timeout_seconds * SERVER_TIMEOUT_RATIO
    elif server_timeout >= http_timeout_seconds:
        raise ValueError(
            "config.request_timeout_seconds must be shorter than the HTTP "
            f"timeout ({http_timeout_seconds:g} seconds)."
        )

    return config.model_copy(update={"request_timeout_seconds": server_timeout})


class ScorerInvokeInputs(BaseModel):
    """Input values sent to the Luna scorer invoke endpoint."""

    query: JSONValue = ""
    response: JSONValue = ""
    ground_truth: JSONValue = None
    tools: list[JSONObject] | None = None
    tool_calls: list[ScorerInvokeToolCall] | None = None
    documents: list[ScorerInvokeDocument] | None = None
    history: list[ScorerInvokeRecord] | None = None


class ScorerInvokeToolCallFunction(BaseModel):
    """Function portion of a Galileo tool-call payload."""

    name: str
    arguments: str


class ScorerInvokeDocument(BaseModel):
    """Galileo HTTP representation of generic document evidence."""

    content: str
    metadata: JSONObject | None = None


class ScorerInvokeToolCall(BaseModel):
    """Galileo HTTP representation of a model-selected tool call."""

    id: str = Field(min_length=1)
    function: ScorerInvokeToolCallFunction


class ScorerInvokeRecord(BaseModel):
    """Galileo HTTP representation of a structured runtime record.

    Identity, ownership, persistence, and execution IDs are intentionally not
    represented here. The Galileo service hydrates those fields from trusted
    server context.
    """

    type: ScorerInvokeRecordType
    name: str | None = None
    input: JSONValue = None
    output: JSONValue = None
    context: JSONObject | None = None
    tools: list[JSONObject] | None = None
    dataset_output: JSONValue = None
    documents: list[ScorerInvokeDocument] | None = None
    tool_calls: list[ScorerInvokeToolCall] | None = None
    status_code: int | None = None
    children: list[ScorerInvokeRecord] | None = None


class ScorerInvokeRequest(BaseModel):
    """Request payload for Luna scorer invocation.

    Attributes:
        scorer_id: Required scorer identifier.
        scorer_version_id: Deprecated optional compatibility identifier. The
            remote service currently invokes the scorer's current default version.
        scorer_label: Optional display/metadata label.
        inputs: Selected scorer input values.
        record: Optional structured runtime record.
        config: Scorer-specific configuration, always emitted.
    """

    scorer_id: str = Field(min_length=1)
    scorer_version_id: str | None = Field(default=None, min_length=1)
    scorer_label: str | None = Field(default=None, min_length=1)
    inputs: ScorerInvokeInputs
    record: ScorerInvokeRecord | None = None
    config: ScorerInvokeConfig = Field(default_factory=ScorerInvokeConfig)

    @model_validator(mode="after")
    def ensure_required_values(self) -> ScorerInvokeRequest:
        has_text = _has_value(self.inputs.query) or _has_value(self.inputs.response)
        has_evidence = any(
            value is not None and len(value) > 0
            for value in (self.inputs.documents, self.inputs.tool_calls, self.inputs.history)
        )
        if self.record is not None:
            has_evidence = has_evidence or any(
                value is not None and len(value) > 0
                for value in (self.record.documents, self.record.tool_calls, self.record.children)
            )
        if not (has_text or has_evidence):
            raise ValueError(
                "Either inputs.query or inputs.response must be set, or the request "
                "must contain structured evidence."
            )
        return self

    def to_dict(self) -> JSONObject:
        """Convert to the Luna scorer invoke request shape."""
        return self.model_dump(mode="json", exclude_none=True)


def _json_text(value: JSONValue) -> str:
    """Serialize structured JSON as compact text for Galileo's HTTP contract."""
    if isinstance(value, str):
        return value
    return dumps(value, ensure_ascii=False, separators=(",", ":"))


def _document_from_step(document: DocumentEvidence, *, path: str) -> ScorerInvokeDocument:
    """Translate provider-neutral document evidence to Galileo's document shape."""
    # The Step model has already validated this object, but keeping the narrow
    # attribute boundary here makes the provider adapter independent of model internals.
    content = getattr(document, "content")
    document_id = getattr(document, "id")
    source_metadata = getattr(document, "metadata")
    metadata = dict(source_metadata or {})
    existing_id = metadata.get("document_id")
    if document_id is not None and existing_id is not None and existing_id != document_id:
        raise ValueError(
            f"Galileo document {path} has conflicting id and metadata.document_id values."
        )
    if document_id is not None:
        metadata["document_id"] = document_id
    return ScorerInvokeDocument(
        content=_json_text(content),
        metadata=metadata or None,
    )


def _documents_from_steps(
    documents: list[DocumentEvidence] | None,
    *,
    path: str,
) -> list[ScorerInvokeDocument] | None:
    if documents is None:
        return None
    return [
        _document_from_step(document, path=f"{path}[{index}]")
        for index, document in enumerate(documents)
    ]


def _retriever_output_from_step(step: Step, *, path: str) -> JSONValue:
    """Adapt a retriever's native document collection for a Galileo record."""
    if step.documents is not None:
        documents = _documents_from_steps(step.documents, path=f"{path}.documents")
    elif isinstance(step.output, list):
        native_documents = [
            DocumentEvidence.model_validate(document)
            for document in step.output
        ]
        documents = _documents_from_steps(native_documents, path=f"{path}.output")
    else:
        return step.output

    return [
        document.model_dump(mode="json", exclude_none=True)
        for document in documents or []
    ]


def _tool_call_from_step(
    tool_call: ToolCallEvidence,
    *,
    path: str,
) -> ScorerInvokeToolCall:
    """Translate provider-neutral tool-call evidence to Galileo's function shape."""
    tool_call_id = getattr(tool_call, "id")
    if not tool_call_id:
        raise ValueError(f"Galileo tool call {path} requires an id.")
    return ScorerInvokeToolCall(
        id=tool_call_id,
        function=ScorerInvokeToolCallFunction(
            name=getattr(tool_call, "name"),
            arguments=_json_text(getattr(tool_call, "arguments")),
        ),
    )


def _tool_calls_from_steps(
    tool_calls: list[ToolCallEvidence] | None,
    *,
    path: str,
) -> list[ScorerInvokeToolCall] | None:
    if tool_calls is None:
        return None
    return [
        _tool_call_from_step(tool_call, path=f"{path}[{index}]")
        for index, tool_call in enumerate(tool_calls)
    ]


def _record_from_step(
    step: Step | None,
    *,
    selected_input: JSONValue,
    selected_output: JSONValue,
    include_documents: bool = True,
    path: str = "record",
) -> ScorerInvokeRecord | None:
    """Translate a generic Agent Control step into Galileo's record contract.

    LLM records may use selector-selected input and output for the legacy
    dual-write behavior. Non-LLM records use the native provider-neutral Step
    input and output; retriever document collections are adapted to Galileo's
    document shape. Selector-normalized values remain in legacy ``inputs`` for
    non-LLM records rather than replacing their structured evidence.

    Unknown Agent Control step types intentionally fall back to the legacy
    ``inputs`` contract. This keeps the open-source Step model extensible without
    sending an invalid discriminator to Galileo.

    Args:
        step: Complete Agent Control step, when contextual evaluation is used.
        selected_input: Selector-selected value sent as ``inputs.query``.
        selected_output: Selector-selected value sent as ``inputs.response``.

    Returns:
        A Galileo-compatible record, or ``None`` for absent/unsupported root steps.
    """
    if step is None:
        return None
    if step.type not in SUPPORTED_SCORER_INVOKE_RECORD_TYPES:
        # Preserve the legacy root fallback, but never hide invalid nested data
        # merely because the root record itself is unsupported.
        _nested_records(step.children, path=f"{path}.children")
        _nested_records(step.history, path=f"{path}.history")
        return None

    record_type = cast(ScorerInvokeRecordType, step.type)
    if step.type == "llm":
        record_input = selected_input if selected_input is not None else step.input
        record_output = selected_output if selected_output is not None else step.output
    else:
        record_input = step.input
        record_output = (
            _retriever_output_from_step(step, path=path)
            if step.type == "retriever"
            else step.output
        )
    return ScorerInvokeRecord(
        type=record_type,
        name=step.name,
        input=record_input,
        output=record_output,
        context=step.context,
        tools=step.tools,
        dataset_output=step.ground_truth,
        documents=(
            _documents_from_steps(step.documents, path=f"{path}.documents")
            if include_documents
            else None
        ),
        tool_calls=_tool_calls_from_steps(step.tool_calls, path=f"{path}.tool_calls"),
        status_code=step.status_code,
        children=_nested_records(step.children, path=f"{path}.children"),
    )


def _nested_records(
    steps: list[Step] | None,
    *,
    path: str,
) -> list[ScorerInvokeRecord] | None:
    """Convert nested records recursively without silently dropping any item."""
    if steps is None:
        return None
    records: list[ScorerInvokeRecord] = []
    for index, child in enumerate(steps):
        if child.type not in SUPPORTED_SCORER_INVOKE_RECORD_TYPES:
            raise ValueError(
                f"Galileo cannot serialize nested record {path}[{index}]: "
                f"unsupported step type {child.type!r}."
            )
        record = _record_from_step(
            child,
            selected_input=child.input,
            selected_output=child.output,
            include_documents=True,
            path=f"{path}[{index}]",
        )
        if record is None:  # pragma: no cover - guarded by the discriminator check
            raise ValueError(f"Galileo could not serialize nested record {path}[{index}].")
        records.append(record)
    return records


def _request_debug_metadata(request_body: JSONObject) -> JSONObject:
    """Build safe request metadata without logging scorer inputs or evidence."""
    inputs = request_body.get("inputs")
    record = request_body.get("record")

    def count(container: JSONValue, field: str) -> int:
        if isinstance(container, dict):
            value = container.get(field)
            return len(value) if isinstance(value, list) else 0
        return 0

    return {
        "scorer_id": request_body.get("scorer_id"),
        "record_type": record.get("type") if isinstance(record, dict) else None,
        "evidence_counts": {
            "input_documents": count(inputs, "documents"),
            "input_tool_calls": count(inputs, "tool_calls"),
            "input_history": count(inputs, "history"),
            "record_documents": count(record, "documents"),
            "record_tool_calls": count(record, "tool_calls"),
            "record_children": count(record, "children"),
        },
    }


class ScorerInvokeResponse(BaseModel):
    """Response from Luna scorer invocation.

    Attributes:
        scorer_label: Echoed scorer label, when returned.
        score: Raw scorer value.
        status: Invocation status.
        execution_time: Execution time in seconds, when returned.
        error_message: Error detail for non-success statuses.
    """

    scorer_label: str | None = None
    score: JSONValue
    status: str = "unknown"
    execution_time: float | None = None
    error_message: str | None = None
    _raw_response: JSONObject = PrivateAttr(default_factory=dict)

    @property
    def raw_response(self) -> JSONObject:
        return self._raw_response

    @classmethod
    def from_dict(cls, data: JSONObject) -> ScorerInvokeResponse:
        """Create a response model from the Luna scorer invoke JSON object."""
        response = cls.model_validate(
            data | {"execution_time": _as_float_or_none(data.get("execution_time"))}
        )
        response._raw_response = data
        return response


class GalileoLunaClient:
    """Thin HTTP client for Galileo Luna scorer invocation.

    Environment Variables:
        GALILEO_API_SECRET_KEY or GALILEO_API_SECRET: JWT signing secret for internal auth.
        GALILEO_LUNA_INVOKE_URL: Luna scorer invoke URL or service root (required).
        GALILEO_LUNA_INVOKE_CA_FILE: CA bundle used to verify Luna invoke TLS.
        AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE: Shared internal CA fallback.
        GALILEO_LUNA_KEEPALIVE_EXPIRY_SECONDS: HTTP pooled connection expiry.
        GALILEO_LUNA_MAX_CONNECTIONS: Maximum outbound HTTP connections.
        GALILEO_LUNA_MAX_KEEPALIVE_CONNECTIONS: Maximum idle pooled HTTP connections.
        GALILEO_LUNA_CLIENT_POOL_SIZE: Number of outbound HTTP clients to rotate across.
    """

    def __init__(
        self,
        api_secret: str | None = None,
        luna_invoke_url: str | None = None,
        luna_invoke_ca_file: str | None = None,
    ) -> None:
        """Initialize the Galileo Luna client.

        Args:
            api_secret: Internal JWT signing secret. If not provided, reads from
                GALILEO_API_SECRET_KEY or GALILEO_API_SECRET.
            luna_invoke_url: Luna scorer invoke URL or service root. If not provided,
                reads from GALILEO_LUNA_INVOKE_URL.
            luna_invoke_ca_file: Optional CA bundle used to verify Luna invoke TLS. If not
                provided, reads from GALILEO_LUNA_INVOKE_CA_FILE, then
                AGENT_CONTROL_AUTH_UPSTREAM_CA_FILE.

        Raises:
            ValueError: If the API secret, Luna invoke URL, CA bundle, or connection
                tuning configuration is invalid.
        """
        resolved_api_secret = (
            api_secret or os.getenv("GALILEO_API_SECRET_KEY") or os.getenv("GALILEO_API_SECRET")
        )
        if not resolved_api_secret:
            raise ValueError(
                "GALILEO_API_SECRET_KEY or GALILEO_API_SECRET is required for Luna "
                "scorer invocation. Set one as an environment variable or pass it "
                "to the constructor."
            )

        resolved_luna_invoke_url = luna_invoke_url or os.getenv(LUNA_INVOKE_URL_ENV)
        if resolved_luna_invoke_url is None or resolved_luna_invoke_url.strip() == "":
            raise ValueError(
                "GALILEO_LUNA_INVOKE_URL is required for Luna scorer invocation. "
                "Set it as an environment variable or pass it to the constructor."
            )

        self.api_secret = resolved_api_secret
        self.luna_invoke_url = _normalize_luna_invoke_url(resolved_luna_invoke_url)
        self.luna_invoke_ca_file = (
            luna_invoke_ca_file
            or os.getenv(LUNA_INVOKE_CA_FILE_ENV)
            or os.getenv(AUTH_UPSTREAM_CA_FILE_ENV)
            or ""
        ).strip() or None
        self._ssl_context = self._load_ssl_context(self.luna_invoke_ca_file)
        self.keepalive_expiry_seconds = _load_float_env(
            LUNA_KEEPALIVE_EXPIRY_ENV, DEFAULT_KEEPALIVE_EXPIRY_SECS
        )
        self.max_connections = _load_int_env(LUNA_MAX_CONNECTIONS_ENV, DEFAULT_MAX_CONNECTIONS)
        self.max_keepalive_connections = _load_int_env(
            LUNA_MAX_KEEPALIVE_CONNECTIONS_ENV, DEFAULT_MAX_KEEPALIVE_CONNECTIONS
        )
        self.client_pool_size = _load_int_env(LUNA_CLIENT_POOL_SIZE_ENV, DEFAULT_CLIENT_POOL_SIZE)
        _validate_connection_config(
            keepalive_expiry_seconds=self.keepalive_expiry_seconds,
            max_connections=self.max_connections,
            max_keepalive_connections=self.max_keepalive_connections,
            client_pool_size=self.client_pool_size,
        )
        self._client: httpx.AsyncClient | None = None
        self._clients: list[httpx.AsyncClient] = []
        self._next_client_index = 0
        self._client_lock = Lock()

    @staticmethod
    def _load_ssl_context(ca_file: str | None) -> ssl.SSLContext | None:
        """Build a TLS verification context from a CA bundle path, if configured."""
        if ca_file is None:
            return None
        try:
            return ssl.create_default_context(cafile=ca_file)
        except (OSError, ssl.SSLError) as exc:
            raise ValueError(f"Failed to load CA bundle from {ca_file!r}: {exc}") from exc

    def _create_client(self) -> httpx.AsyncClient:
        """Create an HTTP client with the configured TLS and connection limits."""
        verify: ssl.SSLContext | bool = self._ssl_context if self._ssl_context is not None else True
        return httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECS),
            limits=httpx.Limits(
                max_connections=self.max_connections,
                max_keepalive_connections=self.max_keepalive_connections,
                keepalive_expiry=self.keepalive_expiry_seconds,
            ),
            verify=verify,
        )

    def _select_pooled_client(self) -> httpx.AsyncClient:
        """Select the next pooled client while holding the client state lock."""
        client = self._clients[self._next_client_index % len(self._clients)]
        self._next_client_index = (self._next_client_index + 1) % len(self._clients)
        return client

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the next HTTP client."""
        async with self._client_lock:
            self._clients = [client for client in self._clients if not client.is_closed]

            if self.client_pool_size == 1:
                if self._client is not None and not self._client.is_closed:
                    return self._client
                self._client = self._clients[0] if self._clients else self._create_client()
                self._clients = [self._client]
                return self._client

            self._client = None
            while len(self._clients) < self.client_pool_size:
                self._clients.append(self._create_client())

            return self._select_pooled_client()

    def _endpoint_and_auth_header(self) -> tuple[str, str]:
        token = _internal_auth_token(self.api_secret)
        return self.luna_invoke_url, f"Bearer {token}"

    async def invoke(
        self,
        *,
        scorer_id: str,
        scorer_version_id: str | None = None,
        scorer_label: str | None = None,
        input: JSONValue = None,
        output: JSONValue = None,
        step: Step | None = None,
        config: ScorerInvokeConfig | JSONObject | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECS,
        headers: dict[str, str] | None = None,
    ) -> ScorerInvokeResponse:
        """Invoke a Galileo Luna scorer.

        Args:
            scorer_id: Required scorer identifier.
            scorer_version_id: Deprecated optional compatibility identifier. The
                remote service currently invokes the scorer's current default version.
            scorer_label: Optional display/metadata label.
            input: Optional user/system prompt text.
            output: Optional model response text.
            step: Optional complete runtime step used for structured dual-write.
            config: Optional scorer invocation configuration.
            timeout: Request timeout in seconds.
            headers: Additional request headers.

        Returns:
            Parsed scorer invocation response.

        Raises:
            ValueError: If neither input/output nor structured evidence is provided,
                config contains an unsupported field, or timeout ordering is invalid.
            RuntimeError: If the API response is not a JSON object.
            httpx.HTTPStatusError: If the Luna invoke endpoint returns an error status code.
            httpx.RequestError: If the request fails before a response is received.
        """
        if not (_has_value(input) or _has_value(output) or _has_structured_evidence(step)):
            raise ValueError(
                "At least one of input or output must be provided, or meaningful "
                "structured evidence must be provided."
            )

        # Accept dictionaries for source compatibility with the original client,
        # but validate them against the public scorer configuration locally.
        invoke_config = (
            ScorerInvokeConfig.model_validate(config)
            if config is not None
            else ScorerInvokeConfig()
        )
        invoke_config = _effective_scorer_timeout(
            invoke_config,
            http_timeout_seconds=timeout,
        )
        request_body = ScorerInvokeRequest(
            scorer_id=scorer_id,
            scorer_version_id=scorer_version_id,
            scorer_label=scorer_label,
            inputs=ScorerInvokeInputs(
                query="" if input is None else input,
                response="" if output is None else output,
                ground_truth=step.ground_truth if step is not None else None,
                tools=step.tools if step is not None else None,
                tool_calls=_tool_calls_from_steps(step.tool_calls, path="inputs.tool_calls")
                if step is not None
                else None,
                documents=_documents_from_steps(
                    step.documents if step is not None else None,
                    path="inputs.documents",
                ),
                history=_nested_records(
                    step.history if step is not None else None,
                    path="inputs.history",
                ),
            ),
            record=_record_from_step(
                step,
                selected_input=input,
                selected_output=output,
                include_documents=False,
            ),
            config=invoke_config,
        ).to_dict()

        endpoint, auth_header = self._endpoint_and_auth_header()
        request_headers = {
            k: v for k, v in (headers or {}).items() if k.lower() not in _BLOCKED_REQUEST_HEADERS
        }
        request_headers["Authorization"] = auth_header

        logger.debug("[GalileoLunaClient] POST %s", endpoint)
        logger.debug(
            "[GalileoLunaClient] Request metadata: %s",
            _request_debug_metadata(request_body),
        )

        try:
            client = await self._get_client()
            response = await client.post(
                endpoint,
                json=request_body,
                headers=request_headers,
                timeout=timeout,
            )
            response.raise_for_status()
            response_data = response.json()
            if not isinstance(response_data, dict):
                raise RuntimeError("Invalid response payload: not a JSON object")

            parsed = ScorerInvokeResponse.from_dict(response_data)
            logger.debug("[GalileoLunaClient] Response: %s", parsed.raw_response)
            return parsed
        except httpx.HTTPStatusError as exc:
            logger.error(
                "[GalileoLunaClient] API error: %s - %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise
        except httpx.RequestError as exc:
            logger.error("[GalileoLunaClient] Request failed: %s", exc)
            raise

    async def close(self) -> None:
        """Close HTTP clients and release resources."""
        async with self._client_lock:
            clients: list[httpx.AsyncClient] = []
            seen_client_ids: set[int] = set()
            if self._client is not None:
                clients.append(self._client)
                seen_client_ids.add(id(self._client))
            self._client = None
            for client in self._clients:
                if id(client) not in seen_client_ids:
                    clients.append(client)
                    seen_client_ids.add(id(client))
            self._clients = []
            self._next_client_index = 0

            for client in clients:
                if not client.is_closed:
                    await client.aclose()

    async def __aenter__(self) -> GalileoLunaClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Async context manager exit."""
        await self.close()
