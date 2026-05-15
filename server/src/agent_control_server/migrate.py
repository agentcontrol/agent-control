"""Run bundled Alembic migrations for agent-control-server.

Exposed as the ``agent-control-migrate`` console script. The wheel ships
its Alembic config and migration scripts under the package so this
command works in any install location (Docker, venv, system Python).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import NullPool

import agent_control_server
from agent_control_server.config import db_config

LOGGER = logging.getLogger(__name__)
_MIGRATION_LOCK_CLASS_ID = 0x4143544C  # "ACTL"
_MIGRATION_LOCK_OBJECT_ID = 0x4D494752  # "MIGR"
_MIGRATION_LOCK_POLL_SECONDS = 2.0
_DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS = 600.0
_MIGRATION_LOCK_TIMEOUT_ENV = "AGENT_CONTROL_MIGRATION_LOCK_TIMEOUT_SECONDS"
_MIGRATION_LOCK_PARAMS = {
    "class_id": _MIGRATION_LOCK_CLASS_ID,
    "object_id": _MIGRATION_LOCK_OBJECT_ID,
}


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


@contextmanager
def _runtime_bundled_config() -> Iterator[Config]:
    cfg = _bundled_config()
    if not isinstance(cfg, Config):
        yield cast(Config, cfg)
        return

    bundled_script_location = cfg.get_main_option("script_location")
    if bundled_script_location is None:
        raise RuntimeError("Bundled Alembic script_location is not configured.")

    with tempfile.TemporaryDirectory(prefix="agent-control-alembic-") as tmp:
        script_location = Path(tmp) / "_alembic"
        shutil.copytree(bundled_script_location, script_location)
        for injected_init in (script_location / "versions").rglob("__init__.py"):
            injected_init.unlink()
        cfg.set_main_option("script_location", str(script_location).replace("%", "%%"))
        yield cfg


def _migration_url(cfg: Config) -> str:
    configured_url = cfg.get_main_option("sqlalchemy.url")
    if configured_url:
        return configured_url
    return db_config.get_url()


def _migration_lock_timeout_seconds() -> float:
    raw_timeout = os.getenv(_MIGRATION_LOCK_TIMEOUT_ENV)
    if raw_timeout is None:
        return _DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS

    try:
        timeout = float(raw_timeout)
    except ValueError as exc:
        raise RuntimeError(f"{_MIGRATION_LOCK_TIMEOUT_ENV} must be a number.") from exc

    if timeout <= 0:
        raise RuntimeError(f"{_MIGRATION_LOCK_TIMEOUT_ENV} must be greater than zero.")
    return timeout


def _acquire_migration_lock(connection: Connection, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    logged_wait = False

    while True:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:class_id, :object_id)"),
                _MIGRATION_LOCK_PARAMS,
            ).scalar_one()
        )
        if acquired:
            LOGGER.info("Acquired Agent Control migration advisory lock.")
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Timed out after {timeout_seconds:g}s waiting for Agent Control "
                "migration advisory lock."
            )

        if not logged_wait:
            LOGGER.info("Waiting for another Agent Control migration to finish.")
            logged_wait = True
        time.sleep(min(_MIGRATION_LOCK_POLL_SECONDS, remaining))


@contextmanager
def _serialized_migration(cfg: Config, *, enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return

    url = _migration_url(cfg)
    if make_url(url).get_backend_name() != "postgresql":
        yield
        return

    engine = create_engine(url, future=True, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            _acquire_migration_lock(connection, _migration_lock_timeout_seconds())
            try:
                yield
            finally:
                released = bool(
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:class_id, :object_id)"),
                        _MIGRATION_LOCK_PARAMS,
                    ).scalar_one()
                )
                if released:
                    LOGGER.info("Released Agent Control migration advisory lock.")
                else:
                    LOGGER.warning("Agent Control migration advisory lock was not held at release.")
    finally:
        engine.dispose()


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
        with _runtime_bundled_config() as cfg:
            should_lock = parsed.command in {"upgrade", "downgrade"} and not parsed.sql
            with _serialized_migration(cfg, enabled=should_lock):
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
