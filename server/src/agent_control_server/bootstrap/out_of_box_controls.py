"""Startup bootstrap for out-of-box controls.

Phase 1 provides the tooling needed to seed controls safely, but does not
register the static out-of-box control catalog yet. Phase 2 should add those
definitions to ``OUT_OF_BOX_CONTROL_TEMPLATES``.

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
_INITIAL_VERSION_NOTE = "Out-of-box control seed"
_SLUG_NAME_ADAPTER = TypeAdapter(SlugName)


@dataclass(frozen=True, slots=True)
class OutOfBoxControlTemplate:
    """Validated control definition plus the evaluator names it needs."""

    name: str
    control: ControlDefinition
    required_evaluators: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _SLUG_NAME_ADAPTER.validate_python(self.name))
        if not self.required_evaluators:
            required_evaluators = {
                evaluator.name for _, evaluator in self.control.iter_condition_leaf_parts()
            }
            object.__setattr__(self, "required_evaluators", frozenset(required_evaluators))
            return

        object.__setattr__(self, "required_evaluators", frozenset(self.required_evaluators))

    @classmethod
    def from_payload(
        cls,
        *,
        name: str,
        data: Mapping[str, object],
        required_evaluators: Collection[str] = frozenset(),
    ) -> Self:
        """Build a template from raw JSON-like data and validate it immediately."""
        return cls(
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


OUT_OF_BOX_CONTROL_TEMPLATES: tuple[OutOfBoxControlTemplate, ...] = ()


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

    Existing active controls are left untouched so customer edits survive
    restarts and upgrades. Duplicate-name integrity errors are treated as
    benign races with another pod and are reported as ``skipped_conflict``.
    """
    if not templates:
        return OutOfBoxSeedResult()

    created: list[str] = []
    skipped_existing: list[str] = []
    skipped_missing_evaluator: list[SkippedOutOfBoxControl] = []
    skipped_conflict: list[str] = []

    available_evaluator_names = set(available_evaluators)
    async with session_factory() as session:
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
    if await control_service.active_control_name_exists(template.name, namespace_key=namespace_key):
        return "existing"

    control = control_service.create_control(
        namespace_key=namespace_key,
        name=template.name,
        data=_serialize_control_data(template.control),
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
        if _is_control_name_conflict(exc):
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
