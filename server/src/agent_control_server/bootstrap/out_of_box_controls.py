"""Startup bootstrap for out-of-box controls.

Namespace rule:
- Standalone Agent Control seeds into ``DEFAULT_NAMESPACE_KEY``.
- Galileo-integrated Agent Control should call the same helper with
  ``namespace_key`` set to the Galileo ``organization_id`` carried by the
  upstream auth bridge.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Self, cast

from agent_control_models import ControlDefinition
from agent_control_models.server import SlugName
from pydantic import TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import DEFAULT_NAMESPACE_KEY
from ..services.controls import ControlService

_CONTROL_NAME_UNIQUE_CONSTRAINTS = frozenset(
    {
        "controls_name_key",
        "idx_controls_name_active",
        "idx_controls_namespace_name_active",
    }
)
_CONTROL_SEED_UNIQUE_CONSTRAINT = "idx_controls_namespace_seed_source"
_INITIAL_VERSION_NOTE = "Out-of-box control seed"
_SLUG_NAME_ADAPTER = TypeAdapter(SlugName)
_OUT_OF_BOX_TAGS = ["out-of-box"]
_SQL_TOOL_NAME_PATTERN = (
    r"(?i)(?:^|[._-])(?:sql|execute[_-]?sql|run[_-]?sql|sql[_-]?query|"
    r"query[_-]?database|execute[_-]?query)(?:$|[._-])"
)
# Issuer prefix + exact digit length per network, allowing the conventional
# grouping separators (space or dash) so both "4111111111111111" and
# "4111 1111 1111 1111" match. A bare digit-count check (e.g. `\d{13,19}`)
# would also match order numbers, tracking numbers, and other unrelated
# identifiers, so each branch is anchored to a real issuer prefix and length.
_CREDIT_CARD_PATTERN = (
    r"\b(?:"
    r"4\d{3}(?:[ -]?\d{4}){3}"  # Visa (16 digits)
    r"|5[1-5]\d{2}(?:[ -]?\d{4}){3}"  # Mastercard 51-55 (16 digits)
    r"|(?:2221|222[2-9]|22[3-9]\d|2[3-6]\d{2}|27[01]\d|2720)"  # Mastercard 2221-2720
    r"(?:[ -]?\d{4}){3}"
    r"|3[47]\d{2}(?:[ -]?\d{6})(?:[ -]?\d{5})"  # American Express (15 digits, 4-6-5)
    r"|6(?:011|5\d{2})(?:[ -]?\d{4}){3}"  # Discover (16 digits)
    r")\b"
)


@dataclass(frozen=True, slots=True)
class OutOfBoxControlTemplate:
    """Validated control definition plus the evaluator names it needs."""

    source_id: str
    name: str
    control: ControlDefinition
    required_evaluators: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _SLUG_NAME_ADAPTER.validate_python(self.source_id))
        object.__setattr__(self, "name", _SLUG_NAME_ADAPTER.validate_python(self.name))
        condition_evaluators = {
            evaluator.name for _, evaluator in self.control.iter_condition_leaf_parts()
        }
        object.__setattr__(
            self,
            "required_evaluators",
            frozenset(self.required_evaluators).union(condition_evaluators),
        )

    @classmethod
    def from_payload(
        cls,
        *,
        source_id: str,
        name: str,
        data: Mapping[str, object],
        required_evaluators: Collection[str] = frozenset(),
    ) -> Self:
        """Build a template from raw JSON-like data and validate it immediately."""
        return cls(
            source_id=source_id,
            name=name,
            control=ControlDefinition.model_validate(data),
            required_evaluators=frozenset(required_evaluators),
        )


@dataclass(frozen=True, slots=True)
class SkippedOutOfBoxControl:
    """A control skipped because the current pod cannot evaluate it."""

    name: str
    missing_evaluators: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OutOfBoxSeedResult:
    """Summary of one bootstrap seed pass."""

    created: tuple[str, ...] = ()
    skipped_existing: tuple[str, ...] = ()
    skipped_missing_evaluator: tuple[SkippedOutOfBoxControl, ...] = ()
    skipped_conflict: tuple[str, ...] = ()

    @property
    def created_count(self) -> int:
        """Number of controls inserted by this seed pass."""
        return len(self.created)

    @property
    def skipped_count(self) -> int:
        """Number of controls skipped by this seed pass."""
        return (
            len(self.skipped_existing)
            + len(self.skipped_missing_evaluator)
            + len(self.skipped_conflict)
        )


def _leaf_control_payload(
    *,
    description: str,
    selector_path: str,
    evaluator_name: str,
    evaluator_config: Mapping[str, object],
    step_types: list[str],
    stages: list[str],
    decision: str,
    tags: list[str],
    steering_message: str | None = None,
    step_name_regex: str | None = None,
) -> dict[str, object]:
    action: dict[str, object] = {"decision": decision}
    if steering_message is not None:
        action["steering_context"] = {"message": steering_message}

    scope: dict[str, object] = {"step_types": step_types, "stages": stages}
    if step_name_regex is not None:
        scope["step_name_regex"] = step_name_regex

    return {
        "description": description,
        "enabled": True,
        "execution": "server",
        "scope": scope,
        "condition": {
            "selector": {"path": selector_path},
            "evaluator": {
                "name": evaluator_name,
                "config": dict(evaluator_config),
            },
        },
        "action": action,
        "tags": [*_OUT_OF_BOX_TAGS, *tags],
    }


OUT_OF_BOX_CONTROL_TEMPLATES: tuple[OutOfBoxControlTemplate, ...] = (
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-ssn-match",
        name="oob-ssn-match",
        data=_leaf_control_payload(
            description="Block LLM output containing US Social Security Numbers.",
            selector_path="output",
            evaluator_name="regex",
            evaluator_config={"pattern": r"\b\d{3}-\d{2}-\d{4}\b"},
            step_types=["llm"],
            stages=["post"],
            decision="deny",
            tags=["pii", "regex"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-credit-card-number-match",
        name="oob-credit-card-number-match",
        data=_leaf_control_payload(
            description=(
                "Block LLM output containing Visa, Mastercard, American Express, or "
                "Discover card numbers (issuer prefix and length, formatted or unformatted)."
            ),
            selector_path="output",
            evaluator_name="regex",
            evaluator_config={"pattern": _CREDIT_CARD_PATTERN},
            step_types=["llm"],
            stages=["post"],
            decision="deny",
            tags=["pii", "payment", "regex"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-phone-number-match",
        name="oob-phone-number-match",
        data=_leaf_control_payload(
            description="Block LLM output containing common US phone number formats.",
            selector_path="output",
            evaluator_name="regex",
            evaluator_config={
                "pattern": (
                    r"\b(?:\+?1[-.\s]?)?(?:\(?[2-9]\d{2}\)?[-.\s]?)?"
                    r"[2-9]\d{2}[-.\s]?\d{4}\b"
                )
            },
            step_types=["llm"],
            stages=["post"],
            decision="deny",
            tags=["pii", "regex"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-dangerous-shell-command-match",
        name="oob-dangerous-shell-command-match",
        data=_leaf_control_payload(
            description="Block tool commands matching common destructive shell operations.",
            selector_path="input.command",
            evaluator_name="regex",
            evaluator_config={
                "pattern": (
                    r"(?:\brm\s+(?:-(?:rf|fr)|-r\s+-f|-f\s+-r)\s+"
                    r"(?:\"(?:/|~/?|\$HOME/?)\"|'(?:/|~/?|\$HOME/?)'|"
                    r"(?:/|~/?|\$HOME/?))(?:\s|[|;&]|$)|"
                    r"\bmkfs(?:\.[a-z0-9]+)?(?:\s|[|;&]|$)|"
                    r"\bdd\s+if=[^\s]+\s+of=/dev/[^\s]+(?:\s|[|;&]|$)|"
                    r"\bchmod\s+-R\s+777\s+/(?:\s|[|;&]|$)|"
                    r"\bchown\s+-R\s+[^|;&]*\s+/(?:\s|[|;&]|$)|"
                    r"\bshutdown\s+(?:-h\s+)?now(?:\s|[|;&]|$)|"
                    r"\breboot(?:\s|[|;&]|$))"
                ),
                "flags": ["IGNORECASE"],
            },
            step_types=["tool"],
            stages=["pre"],
            decision="deny",
            tags=["tool", "shell", "regex"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-high-value-action-requires-approval",
        name="oob-high-value-action-requires-approval",
        data=_leaf_control_payload(
            description=(
                "Steer tool calls over the default amount threshold to collect approval."
            ),
            selector_path="input",
            evaluator_name="json",
            evaluator_config={
                "json_schema": {
                    "type": "object",
                    "anyOf": [
                        {"not": {"required": ["amount"]}},
                        {
                            "required": ["amount"],
                            "properties": {
                                "amount": {"type": "number", "maximum": 10000}
                            },
                        },
                    ],
                }
            },
            step_types=["tool"],
            stages=["pre"],
            decision="steer",
            steering_message=(
                "Pause this high-value action and submit its exact parameters to a trusted "
                "host approval workflow. The host must bind any approval artifact to this "
                "specific action; approval fields supplied in tool input are not evidence."
            ),
            tags=["tool", "approval", "json"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-outbound-communication-requires-approval",
        name="oob-outbound-communication-requires-approval",
        data=_leaf_control_payload(
            description=(
                "Steer outbound communication tool calls to collect approval before sending."
            ),
            selector_path="input",
            evaluator_name="json",
            evaluator_config={
                "json_schema": {
                    "type": "object",
                    "anyOf": [
                        {
                            "not": {
                                "anyOf": [
                                    {"required": ["to"]},
                                    {"required": ["recipient"]},
                                    {"required": ["recipients"]},
                                    {"required": ["email"]},
                                    {"required": ["phone_number"]},
                                    {"required": ["channel"]},
                                    {"required": ["destination"]},
                                ]
                            }
                        }
                    ],
                }
            },
            step_types=["tool"],
            stages=["pre"],
            decision="steer",
            steering_message=(
                "Pause this outbound communication and submit its exact recipients and "
                "content to a trusted host approval workflow. The host must bind any "
                "approval artifact to this specific action; approval fields supplied in "
                "tool input are not evidence."
            ),
            tags=["tool", "approval", "exfiltration", "json"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-example-tool-allowlist",
        name="oob-example-tool-allowlist",
        data=_leaf_control_payload(
            description=(
                "Example static allowlist: deny tool calls whose canonical name is not "
                "in this list. The values below are placeholders, not a live MCP tool "
                "catalog — replace them with your own approved tool names before "
                "enabling this control."
            ),
            selector_path="canonical_name",
            evaluator_name="list",
            evaluator_config={
                "values": ["search", "web_search", "retrieve", "calculator"],
                "logic": "any",
                "match_on": "no_match",
                "match_mode": "exact",
                "case_sensitive": False,
            },
            step_types=["tool"],
            stages=["pre"],
            decision="deny",
            tags=["tool", "allowlist", "example", "list"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-owasp-llm05-select-only-sql",
        name="oob-owasp-llm05-select-only-sql",
        data=_leaf_control_payload(
            description=(
                "Block SQL tool calls that are not a single syntactic SELECT statement. "
                "This does not guarantee read-only execution; enforce a read-only database "
                "role or transaction for that boundary."
            ),
            selector_path="input.query",
            evaluator_name="sql",
            evaluator_config={
                "allowed_operations": ["SELECT"],
                "allow_multi_statements": False,
                "block_ddl": True,
                "block_dcl": True,
            },
            step_types=["tool"],
            stages=["pre"],
            decision="deny",
            tags=["owasp", "owasp-llm05", "owasp-asi02", "tool", "sql"],
            step_name_regex=_SQL_TOOL_NAME_PATTERN,
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-owasp-llm10-bounded-sql-query",
        name="oob-owasp-llm10-bounded-sql-query",
        data=_leaf_control_payload(
            description=("Block SQL queries without bounded results or with excessive complexity."),
            selector_path="input.query",
            evaluator_name="sql",
            evaluator_config={
                "require_limit": True,
                "max_limit": 1000,
                "max_result_window": 1000,
                "max_subquery_depth": 3,
                "max_joins": 5,
                "max_union_count": 2,
            },
            step_types=["tool"],
            stages=["pre"],
            decision="deny",
            tags=["owasp", "owasp-llm10", "tool", "sql", "resource-limit"],
            step_name_regex=_SQL_TOOL_NAME_PATTERN,
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-owasp-llm02-common-credential-output-match",
        name="oob-owasp-llm02-common-credential-output-match",
        data=_leaf_control_payload(
            description=("Block LLM output containing common private-key or API-token formats."),
            selector_path="output",
            evaluator_name="regex",
            evaluator_config={
                "pattern": (
                    r"(?:-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----|"
                    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|"
                    r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b|"
                    r"\bAIza[0-9A-Za-z_-]{35}\b|"
                    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b)"
                )
            },
            step_types=["llm"],
            stages=["post"],
            decision="deny",
            tags=["owasp", "owasp-llm02", "credential", "secret", "regex"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-owasp-llm05-dangerous-uri-output-match",
        name="oob-owasp-llm05-dangerous-uri-output-match",
        data=_leaf_control_payload(
            description=("Block LLM output containing executable or active-content URI schemes."),
            selector_path="output",
            evaluator_name="regex",
            evaluator_config={
                "pattern": (
                    r"(?:\b(?:javascript|vbscript)\s*:|"
                    r"\bdata\s*:\s*(?:text/html|application/xhtml\+xml|image/svg\+xml))"
                ),
                "flags": ["IGNORECASE"],
            },
            step_types=["llm"],
            stages=["post"],
            decision="deny",
            tags=["owasp", "owasp-llm05", "output-handling", "uri", "regex"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-owasp-llm01-prompt-injection-input-match",
        name="oob-owasp-llm01-prompt-injection-input-match",
        data=_leaf_control_payload(
            description=(
                "Block LLM input containing common prompt-injection or jailbreak phrasing."
            ),
            selector_path="input",
            evaluator_name="regex",
            evaluator_config={
                "pattern": (
                    r"(?:\b(?:ignore|disregard)\s+(?:all\s+|any\s+)?"
                    r"(?:previous|prior|above)\s+instructions\b|"
                    r"\b(?:override|bypass)\s+(?:the\s+)?"
                    r"(?:system|developer|safety|policy)\s*"
                    r"(?:prompt|instructions|rules|guidelines)?\b|"
                    r"\breveal\s+(?:the\s+)?(?:system|developer|hidden)\s+"
                    r"(?:prompt|message|instructions)\b|"
                    r"\bjailbreak\b)"
                ),
                "flags": ["IGNORECASE"],
            },
            step_types=["llm"],
            stages=["pre"],
            decision="deny",
            tags=["owasp", "owasp-llm01", "prompt-injection", "jailbreak", "regex"],
        ),
    ),
    OutOfBoxControlTemplate.from_payload(
        source_id="oob-ssrf-metadata-endpoint-match",
        name="oob-ssrf-metadata-endpoint-match",
        data=_leaf_control_payload(
            description=(
                "Block tool calls targeting cloud metadata or loopback endpoints "
                "commonly abused for SSRF."
            ),
            selector_path="input.url",
            evaluator_name="list",
            evaluator_config={
                "values": [
                    "169.254.169.254",
                    "metadata.google.internal",
                    "100.100.100.200",
                    "169.254.170.2",
                    "metadata.azure.com",
                    "localhost",
                    "127.0.0.1",
                    "0.0.0.0",
                    "[::1]",
                ],
                "logic": "any",
                "match_on": "match",
                "match_mode": "contains",
                "case_sensitive": False,
            },
            step_types=["tool"],
            stages=["pre"],
            decision="deny",
            tags=["tool", "ssrf", "network", "list"],
        ),
    ),
)


_LUNA_EVALUATOR_NAME = "galileo.luna"
_LUNA_OPERATOR = "gte"
_LUNA_THRESHOLD = 0.5

# (settings attribute, source_id, scorer_label, category, stage)
#
# `scorer_label` is the exact Luna scorer name observed via
# `galileo_metric_pull.py` discovery mode against the reference project; it
# is metadata-only (the evaluator invokes by `scorer_id`), kept here so the
# seeded control documents which scorer it maps to.
_LUNA_CONTROL_SPECS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "luna_input_toxicity_scorer_id",
        "oob-input-toxicity-slm-match",
        "input_toxicity_luna",
        "toxicity",
        "pre",
    ),
    (
        "luna_output_toxicity_scorer_id",
        "oob-output-toxicity-slm-match",
        "output_toxicity_luna",
        "toxicity",
        "post",
    ),
    ("luna_input_tone_scorer_id", "oob-input-tone-slm-match", "input_tone", "tone", "pre"),
    ("luna_output_tone_scorer_id", "oob-output-tone-slm-match", "output_tone", "tone", "post"),
    (
        "luna_input_sexism_scorer_id",
        "oob-input-sexism-slm-match",
        "input_sexist_luna",
        "sexism",
        "pre",
    ),
    (
        "luna_output_sexism_scorer_id",
        "oob-output-sexism-slm-match",
        "output_sexist_luna",
        "sexism",
        "post",
    ),
)


def _luna_control_template(
    *,
    source_id: str,
    scorer_id: str,
    scorer_label: str,
    category: str,
    stage: str,
) -> OutOfBoxControlTemplate:
    side = "input" if stage == "pre" else "output"
    return OutOfBoxControlTemplate.from_payload(
        source_id=source_id,
        name=source_id,
        data=_leaf_control_payload(
            description=(
                f"Block LLM {side} scored above threshold for {category} by the "
                f"Galileo Luna '{scorer_label}' SLM scorer."
            ),
            selector_path=side,
            evaluator_name=_LUNA_EVALUATOR_NAME,
            evaluator_config={
                "scorer_id": scorer_id,
                "scorer_label": scorer_label,
                "operator": _LUNA_OPERATOR,
                "threshold": _LUNA_THRESHOLD,
                "payload_field": side,
            },
            step_types=["llm"],
            stages=[stage],
            decision="deny",
            tags=["slm", "galileo", "luna", category, side],
        ),
    )


def luna_out_of_box_control_templates(
    *,
    input_toxicity_scorer_id: str | None = None,
    output_toxicity_scorer_id: str | None = None,
    input_tone_scorer_id: str | None = None,
    output_tone_scorer_id: str | None = None,
    input_sexism_scorer_id: str | None = None,
    output_sexism_scorer_id: str | None = None,
) -> tuple[OutOfBoxControlTemplate, ...]:
    """Build the Luna SLM out-of-box templates that have a configured scorer ID.

    `galileo.luna` invokes a scorer instance by ``scorer_id``, and that UUID is
    minted per Galileo project/org when the scorer is configured for it — unlike
    the rest of the out-of-box catalog, there is no stable literal to embed. Each
    of the 6 templates (toxicity/tone/sexism, each for input and output) is only
    included when the caller supplies its scorer ID; the rest are omitted so
    seeding neither creates a control that can never match nor fails outright.
    """
    scorer_ids_by_attr = {
        "luna_input_toxicity_scorer_id": input_toxicity_scorer_id,
        "luna_output_toxicity_scorer_id": output_toxicity_scorer_id,
        "luna_input_tone_scorer_id": input_tone_scorer_id,
        "luna_output_tone_scorer_id": output_tone_scorer_id,
        "luna_input_sexism_scorer_id": input_sexism_scorer_id,
        "luna_output_sexism_scorer_id": output_sexism_scorer_id,
    }
    templates: list[OutOfBoxControlTemplate] = []
    for attr, source_id, scorer_label, category, stage in _LUNA_CONTROL_SPECS:
        scorer_id = scorer_ids_by_attr[attr]
        if not scorer_id:
            continue
        templates.append(
            _luna_control_template(
                source_id=source_id,
                scorer_id=scorer_id,
                scorer_label=scorer_label,
                category=category,
                stage=stage,
            )
        )
    return tuple(templates)


def default_out_of_box_namespace_key() -> str:
    """Return the standalone namespace used for server startup seeding."""
    return DEFAULT_NAMESPACE_KEY


def missing_required_evaluators(
    required_evaluators: Collection[str],
    available_evaluators: Collection[str],
) -> tuple[str, ...]:
    """Return required evaluator names absent from the current pod."""
    missing = set(required_evaluators) - set(available_evaluators)
    return tuple(sorted(missing))


async def seed_out_of_box_controls(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    namespace_key: str,
    available_evaluators: Collection[str],
    templates: Sequence[OutOfBoxControlTemplate] = OUT_OF_BOX_CONTROL_TEMPLATES,
) -> OutOfBoxSeedResult:
    """Create missing out-of-box controls in a namespace.

    Existing seeded controls are found by immutable source ID, so customer
    renames and explicit deletion opt-outs survive restarts and upgrades.
    Duplicate-name and duplicate-source integrity errors are treated as benign
    races with another pod and are reported as ``skipped_conflict``.
    """
    if not templates:
        return OutOfBoxSeedResult()

    created: list[str] = []
    skipped_existing: list[str] = []
    skipped_missing_evaluator: list[SkippedOutOfBoxControl] = []
    skipped_conflict: list[str] = []

    available_evaluator_names = set(available_evaluators)
    async with session_factory() as session:
        eligible_templates: list[OutOfBoxControlTemplate] = []
        for template in templates:
            missing = missing_required_evaluators(
                template.required_evaluators,
                available_evaluator_names,
            )
            if missing:
                skipped_missing_evaluator.append(
                    SkippedOutOfBoxControl(
                        name=template.name,
                        missing_evaluators=missing,
                    )
                )
                continue

            eligible_templates.append(template)

        control_service = ControlService(session)
        existing_source_ids, active_names = await control_service.find_existing_seed_controls(
            namespace_key=namespace_key,
            source_ids={template.source_id for template in eligible_templates},
            names={template.name for template in eligible_templates},
        )
        for template in eligible_templates:
            if template.source_id in existing_source_ids or template.name in active_names:
                skipped_existing.append(template.name)
                continue

            outcome = await _seed_one_control(
                session,
                namespace_key=namespace_key,
                template=template,
            )
            if outcome == "created":
                created.append(template.name)
            elif outcome == "conflict":
                skipped_conflict.append(template.name)
            else:
                skipped_existing.append(template.name)

    return OutOfBoxSeedResult(
        created=tuple(created),
        skipped_existing=tuple(skipped_existing),
        skipped_missing_evaluator=tuple(skipped_missing_evaluator),
        skipped_conflict=tuple(skipped_conflict),
    )


async def _seed_one_control(
    session: AsyncSession,
    *,
    namespace_key: str,
    template: OutOfBoxControlTemplate,
) -> str:
    control_service = ControlService(session)
    control = control_service.create_control(
        namespace_key=namespace_key,
        name=template.name,
        data=_serialize_control_data(template.control),
        seed_source_id=template.source_id,
    )
    try:
        await control_service.create_version(
            control,
            event_type="created",
            note=_INITIAL_VERSION_NOTE,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _is_control_seed_conflict(exc):
            return "conflict"
        raise
    return "created"


def _serialize_control_data(control_data: ControlDefinition) -> dict[str, object]:
    data_json = control_data.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
        exclude_unset=True,
    )
    if "scope" in data_json and isinstance(data_json["scope"], dict):
        data_json["scope"] = {
            key: value for key, value in data_json["scope"].items() if value is not None
        }
    if "enabled" not in data_json:
        data_json["enabled"] = control_data.enabled
    return cast(dict[str, object], data_json)


def _is_control_name_conflict(error: IntegrityError) -> bool:
    diag = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if diag in _CONTROL_NAME_UNIQUE_CONSTRAINTS:
        return True

    error_text = " ".join(
        part for part in (str(error.orig), str(error)) if part and part != "None"
    )
    return any(name in error_text for name in _CONTROL_NAME_UNIQUE_CONSTRAINTS)


def _is_control_seed_conflict(error: IntegrityError) -> bool:
    diag = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    if diag == _CONTROL_SEED_UNIQUE_CONSTRAINT:
        return True
    if _is_control_name_conflict(error):
        return True

    error_text = " ".join(
        part for part in (str(error.orig), str(error)) if part and part != "None"
    )
    return _CONTROL_SEED_UNIQUE_CONSTRAINT in error_text
