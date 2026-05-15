from __future__ import annotations

from pathlib import Path

import agent_control_server
from agent_control_server import migrate
from alembic.config import Config


class _FakeResult:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar_one(self) -> bool:
        return self.value


class _FakeConnection:
    def __init__(self, lock_results: list[bool]) -> None:
        self.lock_results = lock_results
        self.statements: list[str] = []

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: object, params: object) -> _FakeResult:
        statement_text = str(statement)
        self.statements.append(statement_text)
        if "pg_try_advisory_lock" in statement_text:
            return _FakeResult(self.lock_results.pop(0))
        if "pg_advisory_unlock" in statement_text:
            return _FakeResult(True)
        raise AssertionError(f"unexpected SQL statement: {statement_text}")


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.disposed = False

    def connect(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        self.disposed = True


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

    with migrate._runtime_bundled_config() as cfg:
        script_location = Path(cfg.get_main_option("script_location"))
        assert script_location.exists()
        assert (script_location / "versions" / "abc123_example.py").exists()
        assert not (script_location / "versions" / "__init__.py").exists()

    assert not script_location.exists()


def test_serialized_migration_skips_lock_for_non_postgres_url(monkeypatch) -> None:
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", "sqlite:///agent-control.db")

    def fail_create_engine(*args: object, **kwargs: object) -> object:
        raise AssertionError("non-postgres migrations should not create a lock connection")

    monkeypatch.setattr(migrate, "create_engine", fail_create_engine)

    with migrate._serialized_migration(cfg, enabled=True):
        pass


def test_serialized_migration_acquires_and_releases_postgres_lock(monkeypatch) -> None:
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pass@postgres/db")
    connection = _FakeConnection([False, True])
    engine = _FakeEngine(connection)
    sleeps: list[float] = []
    create_engine_kwargs: dict[str, object] = {}

    def fake_create_engine(*args: object, **kwargs: object) -> _FakeEngine:
        create_engine_kwargs.update(kwargs)
        return engine

    monkeypatch.setattr(migrate, "create_engine", fake_create_engine)
    monkeypatch.setattr(migrate.time, "sleep", lambda seconds: sleeps.append(seconds))

    with migrate._serialized_migration(cfg, enabled=True):
        pass

    assert create_engine_kwargs["isolation_level"] == "AUTOCOMMIT"
    assert connection.statements == [
        "SELECT pg_try_advisory_lock(:class_id, :object_id)",
        "SELECT pg_try_advisory_lock(:class_id, :object_id)",
        "SELECT pg_advisory_unlock(:class_id, :object_id)",
    ]
    assert sleeps == [2.0]
    assert engine.disposed


def test_serialized_migration_respects_disabled_lock(monkeypatch) -> None:
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://user:pass@postgres/db")

    def fail_create_engine(*args: object, **kwargs: object) -> object:
        raise AssertionError("disabled migration lock should not create a lock connection")

    monkeypatch.setattr(migrate, "create_engine", fail_create_engine)

    with migrate._serialized_migration(cfg, enabled=False):
        pass
