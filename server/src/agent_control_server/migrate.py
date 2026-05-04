"""Run bundled Alembic migrations for agent-control-server.

Exposed as the ``agent-control-migrate`` console script. The wheel ships
its Alembic config and migration scripts under the package so this
command works in any install location (Docker, venv, system Python).
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

import agent_control_server


def _bundled_config() -> Config:
    pkg_dir = Path(agent_control_server.__file__).parent
    ini_path = pkg_dir / "_alembic.ini"
    alembic_dir = pkg_dir / "_alembic"
    if not ini_path.exists() or not alembic_dir.exists():
        raise RuntimeError(
            "Bundled Alembic resources not found. Expected "
            f"{ini_path} and {alembic_dir}. The installed wheel is missing "
            "migration assets."
        )
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(alembic_dir))
    return cfg


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``agent-control-migrate`` console script.

    With no arguments, runs ``upgrade head``. Supports a small subset of
    Alembic commands sufficient for deploys and operational debugging:
    ``upgrade``, ``downgrade``, ``current``, ``history``, ``heads``.
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        args = ["upgrade", "head"]

    cfg = _bundled_config()
    op, *rest = args

    if op == "upgrade":
        command.upgrade(cfg, rest[0] if rest else "head")
    elif op == "downgrade":
        # Require an explicit revision: downgrade is destructive and
        # there is no safe default for an operational CLI.
        if not rest:
            print(
                "agent-control-migrate downgrade requires an explicit revision "
                "(e.g. 'downgrade -1' or 'downgrade <rev>')",
                file=sys.stderr,
            )
            return 2
        command.downgrade(cfg, rest[0])
    elif op == "current":
        command.current(cfg)
    elif op == "history":
        command.history(cfg)
    elif op == "heads":
        command.heads(cfg)
    else:
        print(f"agent-control-migrate: unknown command '{op}'", file=sys.stderr)
        print(
            "Supported: upgrade [rev], downgrade [rev], current, history, heads",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
