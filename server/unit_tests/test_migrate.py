"""Unit tests for the bundled-migrations entry point.

These do not run migrations against a database. They verify the wheel-bundling
contract: the console script resolves to the right callable, dispatches
correctly to Alembic commands, and the bundled-config helper can load the
packaged migration layout.
"""

from __future__ import annotations

import tomllib
from pathlib import Path, PurePosixPath
from unittest.mock import MagicMock

import pytest
from alembic.script import ScriptDirectory

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
    upgrade.assert_called_once_with(stub_config, "head", sql=False)


def test_main_bare_upgrade_runs_upgrade_head(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade = _patch_command(monkeypatch, "upgrade")
    rc = migrate.main(["upgrade"])
    assert rc == 0
    upgrade.assert_called_once_with(stub_config, "head", sql=False)


def test_main_explicit_upgrade_revision(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade = _patch_command(monkeypatch, "upgrade")
    rc = migrate.main(["upgrade", "abc123"])
    assert rc == 0
    upgrade.assert_called_once_with(stub_config, "abc123", sql=False)


def test_main_upgrade_supports_sql(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade = _patch_command(monkeypatch, "upgrade")
    rc = migrate.main(["upgrade", "head", "--sql"])
    assert rc == 0
    upgrade.assert_called_once_with(stub_config, "head", sql=True)


def test_main_bare_downgrade_requires_explicit_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(migrate, "_bundled_config", pytest.fail)
    with pytest.raises(SystemExit) as exc_info:
        migrate.main(["downgrade"])
    assert exc_info.value.code == 2


def test_main_explicit_downgrade_revision(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade = _patch_command(monkeypatch, "downgrade")
    rc = migrate.main(["downgrade", "abc123"])
    assert rc == 0
    downgrade.assert_called_once_with(stub_config, "abc123", sql=False)


def test_main_downgrade_supports_sql(
    stub_config: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade = _patch_command(monkeypatch, "downgrade")
    rc = migrate.main(["downgrade", "-1", "--sql"])
    assert rc == 0
    downgrade.assert_called_once_with(stub_config, "-1", sql=True)


@pytest.mark.parametrize("op", ["current", "history", "heads"])
def test_main_query_commands(
    stub_config: object, monkeypatch: pytest.MonkeyPatch, op: str
) -> None:
    cmd = _patch_command(monkeypatch, op)
    rc = migrate.main([op])
    assert rc == 0
    cmd.assert_called_once_with(stub_config)


def test_main_unknown_command_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrate, "_bundled_config", pytest.fail)
    with pytest.raises(SystemExit) as exc_info:
        migrate.main(["does-not-exist"])
    assert exc_info.value.code == 2


def test_main_unknown_command_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate, "_bundled_config", pytest.fail)
    with pytest.raises(SystemExit):
        migrate.main(["does-not-exist"])
    out = capsys.readouterr()
    assert "invalid choice: 'does-not-exist'" in out.err
    assert "usage:" in out.err


def test_main_help_prints_usage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate, "_bundled_config", pytest.fail)
    with pytest.raises(SystemExit) as exc_info:
        migrate.main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr()
    assert "usage:" in out.out
    assert "Run bundled Alembic migrations" in out.out


def test_main_rejects_extra_positional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrate, "_bundled_config", pytest.fail)
    with pytest.raises(SystemExit) as exc_info:
        migrate.main(["upgrade", "head", "typo"])
    assert exc_info.value.code == 2


def test_main_returns_nonzero_for_command_errors(
    stub_config: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    upgrade = _patch_command(monkeypatch, "upgrade")
    upgrade.side_effect = RuntimeError("database unavailable")
    rc = migrate.main(["upgrade", "head"])
    assert rc == 1
    out = capsys.readouterr()
    assert "agent-control-migrate: database unavailable" in out.err


def test_bundled_config_raises_when_assets_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point the bundled-config lookup at a directory with no migration assets.
    fake_pkg_init = tmp_path / "__init__.py"
    fake_pkg_init.write_text("")
    monkeypatch.setattr(migrate.agent_control_server, "__file__", str(fake_pkg_init))

    with pytest.raises(RuntimeError, match="Bundled Alembic resources not found"):
        migrate._bundled_config()


def test_bundled_config_loads_real_bundled_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg_dir = tmp_path / "agent_control_server"
    versions_dir = pkg_dir / "_alembic" / "versions"
    versions_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "_alembic.ini").write_text("[alembic]\nscript_location = unused\n")
    (pkg_dir / "_alembic" / "env.py").write_text("")
    (pkg_dir / "_alembic" / "script.py.mako").write_text("")
    (versions_dir / "abc123_initial.py").write_text(
        '"""Initial revision."""\n'
        'revision = "abc123"\n'
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
    )
    monkeypatch.setattr(
        migrate.agent_control_server,
        "__file__",
        str(pkg_dir / "__init__.py"),
    )

    cfg = migrate._bundled_config()
    script_dir = ScriptDirectory.from_config(cfg)

    assert script_dir.get_heads() == ["abc123"]


def test_bundled_config_escapes_percent_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg_dir = tmp_path / "agent%control_server"
    (pkg_dir / "_alembic").mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "_alembic.ini").write_text("[alembic]\nscript_location = unused\n")
    monkeypatch.setattr(
        migrate.agent_control_server,
        "__file__",
        str(pkg_dir / "__init__.py"),
    )

    cfg = migrate._bundled_config()

    assert cfg.get_main_option("script_location") == str(pkg_dir / "_alembic")


def test_force_include_source_paths_exist() -> None:
    """Hatch force-include mappings must ship real migration assets under the package."""
    server_dir = Path(__file__).resolve().parent.parent
    with (server_dir / "pyproject.toml").open("rb") as pyproject:
        config = tomllib.load(pyproject)

    scripts = config["project"]["scripts"]
    assert scripts["agent-control-migrate"] == "agent_control_server.migrate:main"

    wheel_config = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    force_include = wheel_config["force-include"]
    assert force_include

    for source, target in force_include.items():
        source_path = server_dir / source
        assert source_path.exists(), f"missing force-include source: {source_path}"

        target_path = PurePosixPath(target)
        assert target_path.parts[0] == "agent_control_server"

    alembic_target = force_include["alembic"]
    versions = list((server_dir / "alembic" / "versions").glob("*.py"))
    assert alembic_target == "agent_control_server/_alembic"
    assert versions, f"no migration scripts under {server_dir / 'alembic' / 'versions'}"
