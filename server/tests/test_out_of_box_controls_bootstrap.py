from __future__ import annotations

import datetime as dt
import uuid
from copy import deepcopy
from typing import cast

import pytest
from agent_control_evaluators.json.config import JSONEvaluatorConfig
from agent_control_evaluators.json.evaluator import JSONEvaluator
from agent_control_evaluators.list.config import ListEvaluatorConfig
from agent_control_evaluators.list.evaluator import ListEvaluator
from agent_control_evaluators.regex.config import RegexEvaluatorConfig
from agent_control_evaluators.regex.evaluator import RegexEvaluator
from agent_control_evaluators.sql import SQLEvaluator, SQLEvaluatorConfig
from agent_control_models import EvaluatorSpec
from agent_control_server.bootstrap.out_of_box_controls import (
    OUT_OF_BOX_CONTROL_TEMPLATES,
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

_EXPECTED_OOB_CONTROL_NAMES = (
    "oob-ssn-match",
    "oob-credit-card-number-match",
    "oob-phone-number-match",
    "oob-dangerous-shell-command-match",
    "oob-high-value-action-requires-approval",
    "oob-outbound-communication-requires-approval",
    "oob-only-approved-tools-may-run",
    "oob-owasp-llm05-read-only-sql",
    "oob-owasp-llm10-bounded-sql-query",
    "oob-owasp-llm02-common-credential-output-match",
    "oob-owasp-llm05-dangerous-uri-output-match",
)
_AVAILABLE_PHASE_2_EVALUATORS = {"regex", "json", "list", "sql"}


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
    source_id: str | None = None,
    evaluator_name: str = "regex",
) -> OutOfBoxControlTemplate:
    template_name = name or f"oob-test-{uuid.uuid4().hex}"
    return OutOfBoxControlTemplate.from_payload(
        source_id=source_id or template_name,
        name=template_name,
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


def _oob_evaluator_spec(name: str) -> EvaluatorSpec:
    template = next(template for template in OUT_OF_BOX_CONTROL_TEMPLATES if template.name == name)
    leaf = template.control.primary_leaf()
    assert leaf is not None
    leaf_parts = leaf.leaf_parts()
    assert leaf_parts is not None
    _, evaluator = leaf_parts
    return evaluator


def test_default_namespace_key_uses_standalone_namespace() -> None:
    assert default_out_of_box_namespace_key() == DEFAULT_NAMESPACE_KEY


def test_out_of_box_catalog_contains_phase_2_templates() -> None:
    assert tuple(template.name for template in OUT_OF_BOX_CONTROL_TEMPLATES) == (
        _EXPECTED_OOB_CONTROL_NAMES
    )
    assert {
        evaluator
        for template in OUT_OF_BOX_CONTROL_TEMPLATES
        for evaluator in template.required_evaluators
    } == _AVAILABLE_PHASE_2_EVALUATORS
    approved_tools = next(
        template
        for template in OUT_OF_BOX_CONTROL_TEMPLATES
        if template.name == "oob-only-approved-tools-may-run"
    )
    approved_tools_leaf = approved_tools.control.primary_leaf()
    assert approved_tools_leaf is not None
    assert approved_tools_leaf.selector.path == "canonical_name"
    sql_controls = [
        template
        for template in OUT_OF_BOX_CONTROL_TEMPLATES
        if "sql" in template.control.tags
    ]
    assert len(sql_controls) == 2
    assert all(template.control.scope.step_name_regex for template in sql_controls)


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
        OutOfBoxControlTemplate.from_payload(
            source_id="invalid-oob-control",
            name="invalid-oob-control",
            data=payload,
        )


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
    assert control.seed_source_id == "oob-create-control"
    assert control.seed_opted_out_at is None
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
async def test_seed_default_catalog_creates_all_controls_without_bindings() -> None:
    result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators=_AVAILABLE_PHASE_2_EVALUATORS,
    )

    assert result.created == _EXPECTED_OOB_CONTROL_NAMES
    assert result.skipped_existing == ()
    assert result.skipped_missing_evaluator == ()
    assert result.skipped_conflict == ()

    controls = _fetch_controls()
    assert tuple(control.name for control in controls) == _EXPECTED_OOB_CONTROL_NAMES
    assert {control.namespace_key for control in controls} == {DEFAULT_NAMESPACE_KEY}
    assert len(_fetch_versions()) == len(_EXPECTED_OOB_CONTROL_NAMES)
    assert _count_table_rows(policy_controls) == 0
    assert _count_table_rows(agent_controls) == 0
    assert _count_table_rows(ControlBinding.__table__) == 0


@pytest.mark.asyncio
async def test_seed_default_catalog_is_idempotent() -> None:
    await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators=_AVAILABLE_PHASE_2_EVALUATORS,
    )

    result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators=_AVAILABLE_PHASE_2_EVALUATORS,
    )

    assert result.created == ()
    assert result.skipped_existing == _EXPECTED_OOB_CONTROL_NAMES
    assert len(_fetch_controls()) == len(_EXPECTED_OOB_CONTROL_NAMES)
    assert len(_fetch_versions()) == len(_EXPECTED_OOB_CONTROL_NAMES)


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
async def test_seed_does_not_duplicate_a_renamed_seeded_control() -> None:
    template = _template(name="oob-original-name", source_id="stable-seed-id")
    await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )
    with Session(engine) as session:
        control = session.scalar(select(Control))
        assert control is not None
        control.name = "customer-renamed-control"
        session.commit()

    result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )

    assert result.skipped_existing == ("oob-original-name",)
    assert [control.name for control in _fetch_controls()] == ["customer-renamed-control"]


@pytest.mark.asyncio
async def test_seed_respects_deleted_control_opt_out_tombstone() -> None:
    template = _template(name="oob-deleted-control", source_id="stable-seed-id")
    await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )
    deleted_at = dt.datetime.now(dt.UTC)
    with Session(engine) as session:
        control = session.scalar(select(Control))
        assert control is not None
        ControlService.mark_control_deleted(control, deleted_at=deleted_at)
        session.commit()

    result = await seed_out_of_box_controls(
        session_factory=AsyncSessionTest,
        namespace_key=DEFAULT_NAMESPACE_KEY,
        available_evaluators={"regex"},
        templates=(template,),
    )

    assert result.skipped_existing == ("oob-deleted-control",)
    controls = _fetch_controls()
    assert len(controls) == 1
    assert controls[0].deleted_at == deleted_at
    assert controls[0].seed_opted_out_at == deleted_at


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

    async def seed_source_exists(
        self: ControlService,
        seed_source_id: str,
        *,
        namespace_key: str,
    ) -> bool:
        return False

    monkeypatch.setattr(ControlService, "active_control_name_exists", active_control_name_exists)
    monkeypatch.setattr(ControlService, "seed_source_exists", seed_source_exists)

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


@pytest.mark.asyncio
async def test_regex_out_of_box_controls_match_representative_payloads() -> None:
    ssn_spec = _oob_evaluator_spec("oob-ssn-match")
    ssn_evaluator = RegexEvaluator(RegexEvaluatorConfig.model_validate(ssn_spec.config))
    ssn_result = await ssn_evaluator.evaluate("Customer SSN is 123-45-6789.")
    assert ssn_result.matched is True

    shell_spec = _oob_evaluator_spec("oob-dangerous-shell-command-match")
    shell_evaluator = RegexEvaluator(RegexEvaluatorConfig.model_validate(shell_spec.config))
    for command in (
        "sudo rm -rf /",
        "rm -rf /",
        "rm -rf ~",
        "chmod -R 777 /",
        "chown -R root /",
    ):
        shell_result = await shell_evaluator.evaluate(command)
        assert shell_result.matched is True, command


@pytest.mark.asyncio
async def test_json_out_of_box_controls_ignore_caller_controlled_approval_flags() -> None:
    high_value_spec = _oob_evaluator_spec("oob-high-value-action-requires-approval")
    high_value_evaluator = JSONEvaluator(
        JSONEvaluatorConfig.model_validate(high_value_spec.config)
    )

    high_value_result = await high_value_evaluator.evaluate({"amount": 25000})
    low_value_result = await high_value_evaluator.evaluate({"amount": 250})
    caller_approved_results = [
        await high_value_evaluator.evaluate({"amount": 25000, "approved": True}),
        await high_value_evaluator.evaluate(
            {"amount": 25000, "approval": {"approved": True}}
        ),
    ]

    assert high_value_result.matched is True
    assert low_value_result.matched is False
    assert all(result.matched is True for result in caller_approved_results)

    outbound_spec = _oob_evaluator_spec("oob-outbound-communication-requires-approval")
    outbound_evaluator = JSONEvaluator(JSONEvaluatorConfig.model_validate(outbound_spec.config))

    outbound_result = await outbound_evaluator.evaluate(
        {"to": "customer@example.com", "message": "Hello"}
    )
    internal_result = await outbound_evaluator.evaluate({"query": "customer history"})
    caller_approved_outbound_results = [
        await outbound_evaluator.evaluate(
            {"to": "customer@example.com", "message": "Hello", "approved": True}
        ),
        await outbound_evaluator.evaluate(
            {
                "to": "customer@example.com",
                "message": "Hello",
                "approval": {"approved": True},
            }
        ),
    ]

    assert outbound_result.matched is True
    assert internal_result.matched is False
    assert all(result.matched is True for result in caller_approved_outbound_results)


@pytest.mark.asyncio
async def test_list_out_of_box_control_matches_unapproved_tools() -> None:
    tool_spec = _oob_evaluator_spec("oob-only-approved-tools-may-run")
    tool_evaluator = ListEvaluator(ListEvaluatorConfig.model_validate(tool_spec.config))

    delete_result = await tool_evaluator.evaluate("delete_user")
    search_result = await tool_evaluator.evaluate("web_search")

    assert delete_result.matched is True
    assert search_result.matched is False


@pytest.mark.asyncio
async def test_owasp_credential_control_matches_common_secret_formats() -> None:
    # Given: the OWASP-aligned common credential output control
    spec = _oob_evaluator_spec("oob-owasp-llm02-common-credential-output-match")
    evaluator = RegexEvaluator(RegexEvaluatorConfig.model_validate(spec.config))

    # When: evaluating representative secret and non-secret output
    private_key_result = await evaluator.evaluate("-----BEGIN OPENSSH PRIVATE KEY-----\nredacted")
    aws_key_result = await evaluator.evaluate("Credential: AKIAIOSFODNN7EXAMPLE")
    safe_result = await evaluator.evaluate("The operation completed successfully.")

    # Then: recognizable credentials are blocked while ordinary output passes
    assert private_key_result.matched is True
    assert aws_key_result.matched is True
    assert safe_result.matched is False


@pytest.mark.asyncio
async def test_owasp_dangerous_uri_control_matches_active_content_schemes() -> None:
    # Given: the OWASP-aligned dangerous URI output control
    spec = _oob_evaluator_spec("oob-owasp-llm05-dangerous-uri-output-match")
    evaluator = RegexEvaluator(RegexEvaluatorConfig.model_validate(spec.config))

    # When: evaluating executable, active-content, and ordinary HTTPS links
    javascript_result = await evaluator.evaluate(
        '<a href="JaVaScRiPt:alert(document.domain)">click</a>'
    )
    data_uri_result = await evaluator.evaluate("data:image/svg+xml,<svg></svg>")
    safe_result = await evaluator.evaluate("https://docs.example.com/safety")

    # Then: active-content schemes are blocked while HTTPS passes
    assert javascript_result.matched is True
    assert data_uri_result.matched is True
    assert safe_result.matched is False


@pytest.mark.asyncio
async def test_owasp_read_only_sql_control_blocks_mutation_and_multiple_statements() -> None:
    # Given: the OWASP-aligned read-only SQL control
    spec = _oob_evaluator_spec("oob-owasp-llm05-read-only-sql")
    evaluator = SQLEvaluator(SQLEvaluatorConfig.model_validate(spec.config))

    # When: evaluating read-only, mutating, and multi-statement SQL
    select_result = await evaluator.evaluate("SELECT id FROM users")
    delete_result = await evaluator.evaluate("DELETE FROM users")
    multiple_result = await evaluator.evaluate("SELECT id FROM users; DROP TABLE users")

    # Then: only the single read-only query passes
    assert select_result.matched is False
    assert delete_result.matched is True
    assert multiple_result.matched is True


@pytest.mark.asyncio
async def test_owasp_bounded_sql_control_enforces_result_and_complexity_limits() -> None:
    # Given: the OWASP-aligned bounded SQL query control
    spec = _oob_evaluator_spec("oob-owasp-llm10-bounded-sql-query")
    evaluator = SQLEvaluator(SQLEvaluatorConfig.model_validate(spec.config))

    # When: evaluating bounded, unbounded, and oversized result windows
    bounded_result = await evaluator.evaluate("SELECT id FROM users LIMIT 100")
    missing_limit_result = await evaluator.evaluate("SELECT id FROM users")
    oversized_window_result = await evaluator.evaluate("SELECT id FROM users LIMIT 1000 OFFSET 1")

    # Then: only the bounded query within the configured result window passes
    assert bounded_result.matched is False
    assert missing_limit_result.matched is True
    assert oversized_window_result.matched is True
