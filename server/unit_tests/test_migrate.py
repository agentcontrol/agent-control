"""Unit tests for the bundled-migrations entry point.

These do not run migrations; they only verify the wheel-bundling
contract: the console script resolves to the right callable, and the
bundled-config helper raises a clear error when assets are missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_control_server import migrate


def test_main_unknown_command_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
