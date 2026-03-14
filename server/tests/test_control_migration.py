"""Tests for stored control condition migration."""

from __future__ import annotations

from argparse import Namespace
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agent_control_server.scripts import migrate_control_conditions
from agent_control_server.services.control_migration import migrate_control_payload

from .utils import VALID_CONTROL_PAYLOAD


def test_migrate_control_payload_rewrites_legacy_leaf() -> None:
    # Given: a stored control payload in the legacy flat shape
    legacy_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    legacy_payload["selector"] = legacy_payload["condition"]["selector"]
    legacy_payload["evaluator"] = legacy_payload["condition"]["evaluator"]
    legacy_payload.pop("condition")

    # When: migrating the stored payload
    result = migrate_control_payload(legacy_payload)

    # Then: the payload is rewritten into canonical condition form
    assert result.status == "migrated"
    assert result.payload is not None
    assert "selector" not in result.payload
    assert "evaluator" not in result.payload
    assert result.payload["condition"]["selector"]["path"] == "input"


def test_migrate_control_payload_leaves_canonical_rows_unchanged() -> None:
    # Given: a stored payload that is already canonical
    # When: migrating the stored payload
    result = migrate_control_payload(deepcopy(VALID_CONTROL_PAYLOAD))

    # Then: no rewrite is needed and the payload is preserved
    assert result.status == "unchanged"
    assert result.payload == VALID_CONTROL_PAYLOAD


def test_migrate_control_payload_rejects_mixed_rows() -> None:
    # Given: a stored payload that mixes canonical and legacy fields
    mixed_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    mixed_payload["selector"] = {"path": "input"}

    # When: migrating the stored payload
    result = migrate_control_payload(mixed_payload)

    # Then: migration rejects the ambiguous row as invalid
    assert result.status == "invalid"
    assert result.reason is not None
    assert "mixes canonical condition fields" in result.reason


def test_migrate_control_payload_rejects_partial_legacy_rows() -> None:
    # Given: a legacy payload that is missing one of selector/evaluator
    partial_payload = deepcopy(VALID_CONTROL_PAYLOAD)
    partial_payload.pop("condition")
    partial_payload["selector"] = {"path": "input"}

    # When: migrating the stored payload
    result = migrate_control_payload(partial_payload)

    # Then: migration rejects the incomplete legacy row
    assert result.status == "invalid"
    assert result.reason == "Legacy control definition must include both selector and evaluator."


def test_migrate_control_payload_rejects_non_object_rows() -> None:
    # Given: stored control data that is not a JSON object
    # When: migrating the stored payload
    result = migrate_control_payload(["not", "an", "object"])

    # Then: migration reports the row as invalid
    assert result.status == "invalid"
    assert result.reason == "Stored control data must be a JSON object."


def test_migrate_control_payload_leaves_empty_draft_rows_unchanged() -> None:
    # Given: an unconfigured control row created with the default empty payload
    # When: migrating the stored payload
    result = migrate_control_payload({})

    # Then: the draft row is treated as unchanged instead of corrupted
    assert result.status == "unchanged"
    assert result.payload == {}


@dataclass
class _FakeControl:
    id: int
    name: str
    data: dict[str, Any]


class _FakeResult:
    def __init__(self, controls: list[_FakeControl]) -> None:
        self._controls = controls

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[_FakeControl]:
        return self._controls


class _FakeSession:
    def __init__(self, controls: list[_FakeControl]) -> None:
        self._controls = controls
        self.committed = False

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def execute(self, _statement: object) -> _FakeResult:
        return _FakeResult(self._controls)

    def commit(self) -> None:
        self.committed = True


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _make_legacy_payload() -> dict[str, Any]:
    payload = deepcopy(VALID_CONTROL_PAYLOAD)
    payload["selector"] = payload["condition"]["selector"]
    payload["evaluator"] = payload["condition"]["evaluator"]
    payload.pop("condition")
    return payload


def _run_migration_script(
    monkeypatch: Any,
    *,
    controls: list[_FakeControl],
    apply: bool,
) -> tuple[int, _FakeSession, _FakeEngine]:
    fake_session = _FakeSession(controls)
    fake_engine = _FakeEngine()

    # Given: fake engine/session dependencies and parsed CLI args
    monkeypatch.setattr(
        migrate_control_conditions,
        "_parse_args",
        lambda: Namespace(apply=apply, dry_run=not apply),
    )
    monkeypatch.setattr(
        migrate_control_conditions,
        "create_engine",
        lambda *_args, **_kwargs: fake_engine,
    )
    monkeypatch.setattr(
        migrate_control_conditions,
        "Session",
        lambda _engine: fake_session,
    )

    # When: running the migration script entrypoint
    exit_code = migrate_control_conditions.main()

    # Then: the caller can assert on exit code and fake side effects
    return exit_code, fake_session, fake_engine


def test_migration_script_dry_run_reports_summary_without_writing(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    # Given: one canonical row and one legacy row ready to migrate
    controls = [
        _FakeControl(id=1, name="canonical", data=deepcopy(VALID_CONTROL_PAYLOAD)),
        _FakeControl(id=2, name="legacy", data=_make_legacy_payload()),
    ]

    # When: running the script in dry-run mode
    exit_code, fake_session, fake_engine = _run_migration_script(
        monkeypatch,
        controls=controls,
        apply=False,
    )
    output = capsys.readouterr().out

    # Then: the summary is correct and no commit occurs
    assert exit_code == 0
    assert "Already canonical: 1" in output
    assert "Ready to migrate: 1" in output
    assert "Invalid/corrupted: 0" in output
    assert fake_session.committed is False
    assert fake_engine.disposed is True
    assert "condition" not in controls[1].data


def test_migration_script_apply_rewrites_legacy_rows_and_commits(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    # Given: one canonical row and one legacy row ready to migrate
    controls = [
        _FakeControl(id=1, name="canonical", data=deepcopy(VALID_CONTROL_PAYLOAD)),
        _FakeControl(id=2, name="legacy", data=_make_legacy_payload()),
    ]

    # When: running the script in apply mode
    exit_code, fake_session, fake_engine = _run_migration_script(
        monkeypatch,
        controls=controls,
        apply=True,
    )
    output = capsys.readouterr().out

    # Then: only the legacy row is rewritten and the session commits
    assert exit_code == 0
    assert "Applied migration to 1 controls." in output
    assert fake_session.committed is True
    assert fake_engine.disposed is True
    assert controls[0].data == VALID_CONTROL_PAYLOAD
    assert "condition" in controls[1].data
    assert "selector" not in controls[1].data
    assert "evaluator" not in controls[1].data


def test_migration_script_apply_ignores_empty_draft_rows(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    # Given: an empty draft row plus one legacy row ready to migrate
    controls = [
        _FakeControl(id=1, name="draft", data={}),
        _FakeControl(id=2, name="legacy", data=_make_legacy_payload()),
    ]

    # When: running the script in apply mode
    exit_code, fake_session, fake_engine = _run_migration_script(
        monkeypatch,
        controls=controls,
        apply=True,
    )
    output = capsys.readouterr().out

    # Then: empty draft rows do not block the migration and remain untouched
    assert exit_code == 0
    assert "Already canonical: 1" in output
    assert "Ready to migrate: 1" in output
    assert "Invalid/corrupted: 0" in output
    assert fake_session.committed is True
    assert fake_engine.disposed is True
    assert controls[0].data == {}
    assert "condition" in controls[1].data


def test_migration_script_apply_aborts_when_invalid_rows_exist(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    # Given: a legacy row plus an invalid partial-legacy row
    invalid_partial = _make_legacy_payload()
    invalid_partial.pop("evaluator")
    controls = [
        _FakeControl(id=1, name="legacy", data=_make_legacy_payload()),
        _FakeControl(id=2, name="invalid", data=invalid_partial),
    ]

    # When: running the script in apply mode
    exit_code, fake_session, fake_engine = _run_migration_script(
        monkeypatch,
        controls=controls,
        apply=True,
    )
    output = capsys.readouterr().out

    # Then: apply aborts before commit and leaves rows untouched
    assert exit_code == 1
    assert "Invalid/corrupted: 1" in output
    assert "Aborting apply because invalid controls must be fixed first." in output
    assert fake_session.committed is False
    assert fake_engine.disposed is True
    assert "condition" not in controls[0].data
