from __future__ import annotations

from pathlib import Path

import agent_control_server
from agent_control_server import migrate


def test_bundled_config_omits_injected_version_init(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "agent_control_server"
    versions_dir = package_dir / "_alembic" / "versions"
    versions_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "_alembic.ini").write_text(
        "[alembic]\nscript_location = _alembic\n",
        encoding="utf-8",
    )
    (package_dir / "_alembic" / "env.py").write_text("", encoding="utf-8")
    (versions_dir / "__init__.py").write_text("", encoding="utf-8")
    (versions_dir / "abc123_example.py").write_text("revision = 'abc123'\n", encoding="utf-8")

    monkeypatch.setattr(agent_control_server, "__file__", str(package_dir / "__init__.py"))

    with migrate._bundled_config() as cfg:
        script_location = Path(cfg.get_main_option("script_location"))
        assert script_location.exists()
        assert (script_location / "versions" / "abc123_example.py").exists()
        assert not (script_location / "versions" / "__init__.py").exists()

    assert not script_location.exists()
