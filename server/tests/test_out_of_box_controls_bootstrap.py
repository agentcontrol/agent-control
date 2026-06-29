from __future__ import annotations

import uuid
from copy import deepcopy
from typing import cast

import pytest
from agent_control_server.bootstrap.out_of_box_controls import (
    OutOfBoxControlTemplate,
    default_out_of_box_namespace_key,
    missing_required_evaluators,
    seed_out_of_box_controls,
)
from agent_control_server.models import (
    DEFAULT_NAMESPACE_KEY,
    Control,
    ControlBinding,
    ControlVersion,
    agent_controls,
    policy_controls,
)
from agent_control_server.services.controls import ControlService
from pydantic import ValidationError
from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session

from .conftest import AsyncSessionTest, engine


def _control_payload(*, evaluator_name: str = "regex") -> dict[str, object]:
    return {
        "description": "Synthetic out-of-box control",
        "enabled": True,
        "execution": "server",
        "scope": {"step_types": ["llm"], "stages": ["post"]},
        "condition": {
            "selector": {"path": "output"},
            "evaluator": {
                "name": evaluator_name,
                "config": {"pattern": r"\bsecret\b"},
            },
        },
        "action": {"decision": "deny"},
        "tags": ["out-of-box"],
    }


def _template(
    *,
    name: str | None = None,
    evaluator_name: str = "regex",
) -> OutOfBoxControlTemplate:
    return OutOfBoxControlTemplate.from_payload(
        name=name or f"oob-test-{uuid.uuid4().hex}",
        data=_control_payload(evaluator_name=evaluator_name),
    )


def _fetch_controls() -> list[Control]:
    with Session(engine) as session:
        return list(session.scalars(select(Control).order_by(Control.id)).all())


def _fetch_versions() -> list[ControlVersion]:
    with Session(engine) as session:
        return list(session.scalars(select(ControlVersion).order_by(ControlVersion.id)).all())


def _count_table_rows(table: Table) -> int:
    with Session(engine) as session:
        return cast(int, session.scalar(select(func.count()).select_from(table)))


def test_default_namespace_key_uses_standalone_namespace() -> None:
    assert default_out_of_box_namespace_key() == DEFAULT_NAMESPACE_KEY


def test_missing_required_evaluators_returns_sorted_names() -> None:
    missing = missing_required_evaluators(
        {"galileo.luna", "regex", "json"},
        {"json"},
    )

    assert missing == ("galileo.luna", "regex")


def test_template_from_payload_validates_control_definition() -> None:
    payload = deepcopy(_control_payload())
    payload["condition"] = {
        "selector": {"path": "invalid_root.value"},
        "evaluator": {"name": "regex", "config": {"pattern": "x"}},
    }

    with pytest.raises(ValidationError):
        OutOfBoxControlTemplate.from_payload(name="invalid-oob-control", data=payload)


@pytest.mark.asyncio
async def test_seed_skips_template_when_required_evaluator_is_missing() -> None:
    template = _template(name="oob-missing-evaluator")

    result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"json"},
        templates=(template,),
    )

    assert result.created == ()
    assert result.skipped_existing == ()
    assert result.skipped_conflict == ()
    assert len(result.skipped_missing_evaluator) == 1
    assert result.skipped_missing_evaluator[0].name == "oob-missing-evaluator"
    assert result.skipped_missing_evaluator[0].missing_evaluators == ("regex",)
    assert _fetch_controls() == []


@pytest.mark.asyncio
async def test_seed_creates_control_version_in_namespace_without_bindings() -> None:
    template = _template(name="oob-create-control")

    result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key="galileo-org-123",
        available_evaluators={"regex"},
        templates=(template,),
    )

    assert result.created == ("oob-create-control",)
    controls = _fetch_controls()
    assert len(controls) == 1
    control = controls[0]
    assert control.namespace_key == "galileo-org-123"
    assert control.name == "oob-create-control"
    assert control.data["enabled"] is True
    assert control.data["condition"]["evaluator"]["name"] == "regex"

    versions = _fetch_versions()
    assert len(versions) == 1
    assert versions[0].control_id == control.id
    assert versions[0].version_num == 1
    assert versions[0].event_type == "created"
    assert versions[0].note == "Out-of-box control seed"
    assert versions[0].snapshot["name"] == "oob-create-control"

    assert _count_table_rows(policy_controls) == 0
    assert _count_table_rows(agent_controls) == 0
    assert _count_table_rows(ControlBinding.__table__) == 0


@pytest.mark.asyncio
async def test_seed_is_idempotent_for_existing_active_control_names() -> None:
    template = _template(name="oob-idempotent-control")

    first_result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )
    second_result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )

    assert first_result.created == ("oob-idempotent-control",)
    assert second_result.created == ()
    assert second_result.skipped_existing == ("oob-idempotent-control",)
    assert len(_fetch_controls()) == 1
    assert len(_fetch_versions()) == 1


@pytest.mark.asyncio
async def test_seed_treats_duplicate_insert_integrity_error_as_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = _template(name="oob-race-control")
    await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )

    async def active_control_name_exists(
        self: ControlService,
        name: str,
        *,
        namespace_key: str,
        exclude_control_id: int | None = None,
    ) -> bool:
        return False

    monkeypatch.setattr(ControlService, "active_control_name_exists", active_control_name_exists)

    result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )

    assert result.created == ()
    assert result.skipped_existing == ()
    assert result.skipped_conflict == ("oob-race-control",)
    assert len(_fetch_controls()) == 1
    assert len(_fetch_versions()) == 1

