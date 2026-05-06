"""Run bundled Alembic migrations for agent-control-server.

Exposed as the ``agent-control-migrate`` console script. The wheel ships
its Alembic config and migration scripts under the package so this
command works in any install location (Docker, venv, system Python).
"""

from __future__ import annotations

import argparse
import logging
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
    cfg.set_main_option("script_location", str(alembic_dir).replace("%", "%%"))
    return cfg


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-control-migrate",
        description="Run bundled Alembic migrations for agent-control-server.",
    )
    subparsers = parser.add_subparsers(dest="command")

    upgrade = subparsers.add_parser("upgrade", help="Upgrade to a revision.")
    upgrade.add_argument("revision", nargs="?", default="head")
    upgrade.add_argument("--sql", action="store_true", help="Emit SQL instead of executing.")

    downgrade = subparsers.add_parser("downgrade", help="Downgrade to a revision.")
    downgrade.add_argument("revision")
    downgrade.add_argument("--sql", action="store_true", help="Emit SQL instead of executing.")

    subparsers.add_parser("current", help="Show the current revision.")
    subparsers.add_parser("history", help="List migration history.")
    subparsers.add_parser("heads", help="Show current available heads.")
    return parser


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``agent-control-migrate`` console script.

    With no arguments, runs ``upgrade head``. Supports a small subset of
    Alembic commands sufficient for deploys and operational debugging:
    ``upgrade``, ``downgrade``, ``current``, ``history``, ``heads``.
    """
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        args = ["upgrade", "head"]

    parser = _build_parser()
    parsed = parser.parse_args(args)
    _configure_logging()

    try:
        cfg = _bundled_config()
        if parsed.command == "upgrade":
            command.upgrade(cfg, parsed.revision, sql=parsed.sql)
        elif parsed.command == "downgrade":
            command.downgrade(cfg, parsed.revision, sql=parsed.sql)
        elif parsed.command == "current":
            command.current(cfg)
        elif parsed.command == "history":
            command.history(cfg)
        elif parsed.command == "heads":
            command.heads(cfg)
        else:  # pragma: no cover - argparse guarantees this cannot happen.
            parser.error("missing command")
    except Exception as exc:
        print(f"agent-control-migrate: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
