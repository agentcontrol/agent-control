"""Unit tests for the bundled-migrations entry point.

These do not run migrations; they only verify the wheel-bundling
contract: the console script resolves to the right callable, dispatches
correctly to Alembic commands, and the bundled-config helper raises a
clear error when assets are missing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_control_server import migrate


@pytest.fixture
def stub_config(monkeypatch: pytest.MonkeyPatch) -> object:
    """Replace bundled-config building with a sentinel object.

    Lets dispatch tests verify which Alembic command was called and
    what config was passed without needing real migration assets.
    """
    sentinel = object()
    monkeypatch.setattr(migrate, "_bundled_config", lambda: sentinel)
    return sentinel


def _patch_command(monkeypatch: pytest.MonkeyPatch, name: str) -> MagicMock:
    mock = MagicMock()
    monkeypatch.setattr(migrate.command, name, mock)
    return mock


def test_main_default_runs_upgrade_head(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade = _patch_command(monkeypatch, "upgrade")
    rc = migrate.main([])
    assert rc == 0
    upgrade.assert_called_once_with(stub_config, "head")


def test_main_explicit_upgrade_revision(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade = _patch_command(monkeypatch, "upgrade")
    rc = migrate.main(["upgrade", "abc123"])
    assert rc == 0
    upgrade.assert_called_once_with(stub_config, "abc123")


def test_main_bare_downgrade_requires_explicit_revision(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade = _patch_command(monkeypatch, "downgrade")
    rc = migrate.main(["downgrade"])
    assert rc == 2
    downgrade.assert_not_called()


def test_main_explicit_downgrade_revision(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade = _patch_command(monkeypatch, "downgrade")
    rc = migrate.main(["downgrade", "abc123"])
    assert rc == 0
    downgrade.assert_called_once_with(stub_config, "abc123")


@pytest.mark.parametrize("op", ["current", "history", "heads"])
def test_main_query_commands(
    stub_config: object, monkeypatch: pytest.MonkeyPatch, op: str
) -> None:
    cmd = _patch_command(monkeypatch, op)
    rc = migrate.main([op])
    assert rc == 0
    cmd.assert_called_once_with(stub_config)


def test_main_unknown_command_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force config building to succeed without touching real assets.
    monkeypatch.setattr(migrate, "_bundled_config", lambda: object())
    rc = migrate.main(["does-not-exist"])
    assert rc == 2


def test_bundled_config_raises_when_assets_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point the bundled-config lookup at a directory with no migration assets.
    fake_pkg_init = tmp_path / "__init__.py"
    fake_pkg_init.write_text("")
    monkeypatch.setattr(migrate.agent_control_server, "__file__", str(fake_pkg_init))

    with pytest.raises(RuntimeError, match="Bundled Alembic resources not found"):
        migrate._bundled_config()


def test_force_include_source_paths_exist() -> None:
    """The source paths hatch force-include reads must exist in-tree.

    If these go missing the wheel build silently drops migration assets.
    """
    server_dir = Path(__file__).resolve().parent.parent
    alembic_dir = server_dir / "alembic"
    alembic_ini = server_dir / "alembic.ini"

    assert alembic_dir.is_dir(), f"missing source dir: {alembic_dir}"
    assert alembic_ini.is_file(), f"missing source file: {alembic_ini}"

    versions = list((alembic_dir / "versions").glob("*.py"))
    assert versions, f"no migration scripts under {alembic_dir / 'versions'}"
