"""Tests for server database engine configuration."""

from agent_control_server.config import AgentControlServerDatabaseConfig
from agent_control_server.db import _build_async_engine_kwargs


def test_build_async_engine_kwargs_applies_postgres_pool_config() -> None:
    # Given: custom PostgreSQL connection pool settings
    config = AgentControlServerDatabaseConfig(
        pool_size=7,
        max_overflow=2,
        pool_timeout_seconds=3.5,
    )

    # When: building async engine kwargs for Postgres
    kwargs = _build_async_engine_kwargs(
        "postgresql+psycopg://user:password@localhost:5432/agent_control",
        config,
    )

    # Then: the engine is configured with a bounded, health-checked pool
    assert kwargs == {
        "echo": False,
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 2,
        "pool_timeout": 3.5,
        "pool_reset_on_return": "rollback",
    }


def test_build_async_engine_kwargs_skips_pool_config_for_sqlite() -> None:
    # Given: custom pool settings with a SQLite URL
    config = AgentControlServerDatabaseConfig(
        pool_size=7,
        max_overflow=2,
        pool_timeout_seconds=3.5,
    )

    # When: building async engine kwargs for SQLite
    kwargs = _build_async_engine_kwargs("sqlite+aiosqlite:///tmp/agent-control.db", config)

    # Then: SQLite keeps SQLAlchemy's default local-dev pool behavior
    assert kwargs == {"echo": False}
