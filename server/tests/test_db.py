"""Tests for server database engine configuration."""

import logging
from typing import cast

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.ext.asyncio.engine import AsyncEngine

from agent_control_server.config import AgentControlServerDatabaseConfig
from agent_control_server.db import (
    _build_async_engine_kwargs,
    _checked_out_connection_count,
    _instrument_connection_pool,
    async_engine,
)


class _PoolWithCheckedout:
    def __init__(self, value: int) -> None:
        self.value = value

    def checkedout(self) -> int:
        return self.value


class _PoolWithoutCheckedout:
    pass


class _SyncEngine:
    def __init__(self, pool: object) -> None:
        self.pool = pool


class _Engine:
    def __init__(self, pool: object) -> None:
        self.sync_engine = _SyncEngine(pool)


def _engine_with_pool(pool: object) -> AsyncEngine:
    return cast(AsyncEngine, _Engine(pool))


def _checked_out_connections_sample() -> float | None:
    return REGISTRY.get_sample_value(
        "agent_control_server_sqlalchemy_checked_out_connections",
        {"pool_name": "default"},
    )


def test_build_async_engine_kwargs_applies_postgres_pool_config() -> None:
    # Given: custom PostgreSQL connection pool and timeout settings
    config = AgentControlServerDatabaseConfig(
        pool_size=7,
        max_overflow=2,
        pool_timeout_seconds=3.5,
        connect_timeout_seconds=4,
        statement_timeout_seconds=2.5,
    )

    # When: building async engine kwargs for Postgres
    kwargs = _build_async_engine_kwargs(
        "postgresql+psycopg://user:password@localhost:5432/agent_control",
        config,
    )

    # Then: the engine is configured with a bounded, health-checked pool and timeouts
    assert kwargs == {
        "echo": False,
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 2,
        "pool_timeout": 3.5,
        "pool_reset_on_return": "rollback",
        "connect_args": {
            "connect_timeout": 4,
            "options": "-c statement_timeout=2500",
        },
    }


def test_build_async_engine_kwargs_uses_asyncpg_connect_args() -> None:
    # Given: timeout settings with an asyncpg driver URL
    config = AgentControlServerDatabaseConfig(
        connect_timeout_seconds=4,
        statement_timeout_seconds=2.5,
    )

    # When: building async engine kwargs for asyncpg
    kwargs = _build_async_engine_kwargs(
        "postgresql+asyncpg://user:password@localhost:5432/agent_control",
        config,
    )

    # Then: the timeouts are expressed as asyncpg connect args
    assert kwargs["connect_args"] == {
        "timeout": 4.0,
        "server_settings": {"statement_timeout": "2500"},
    }


def test_build_async_engine_kwargs_can_disable_statement_timeout() -> None:
    # Given: the statement timeout is disabled
    config = AgentControlServerDatabaseConfig(
        connect_timeout_seconds=5,
        statement_timeout_seconds=0,
    )

    # When: building async engine kwargs for Postgres
    kwargs = _build_async_engine_kwargs(
        "postgresql+psycopg://user:password@localhost:5432/agent_control",
        config,
    )

    # Then: no statement timeout option is passed to the driver
    assert kwargs["connect_args"] == {"connect_timeout": 5}


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


def test_build_async_engine_kwargs_logs_when_driver_timeout_args_unknown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: a non-sqlite backend whose driver has no known timeout connect args
    config = AgentControlServerDatabaseConfig()

    # When: building async engine kwargs
    with caplog.at_level(logging.DEBUG, logger="agent_control_server.db"):
        kwargs = _build_async_engine_kwargs(
            "postgresql+someasync://user:password@localhost:5432/agent_control",
            config,
        )

    # Then: pool bounds still apply, but the missing driver-level timeouts are visible
    assert kwargs["pool_pre_ping"] is True
    assert "connect_args" not in kwargs
    assert (
        "No driver-level database timeout connect args configured for "
        "backend=postgresql driver=someasync"
    ) in caplog.text


def test_checked_out_connections_gauge_reports_zero_when_idle() -> None:
    # Given: the database module is imported and the pool is instrumented

    # When: reading the gauge while no connection is checked out
    value = _checked_out_connections_sample()

    # Then: the series exists and reports zero instead of being absent
    assert value == 0.0


def test_checked_out_connections_gauge_reads_pool_state_at_collection() -> None:
    # Given: a pool whose checked-out connection count changes over time
    pool = _PoolWithCheckedout(3)

    try:
        _instrument_connection_pool(_engine_with_pool(pool))

        # When: the Prometheus registry collects the gauge
        value = _checked_out_connections_sample()

        # Then: the gauge reports the pool's current checked-out count
        assert value == 3.0

        # When: the pool state changes without any metric event
        pool.value = 1

        # Then: the next collection reflects the new pool state directly
        assert _checked_out_connections_sample() == 1.0
    finally:
        _instrument_connection_pool(async_engine)


def test_checked_out_connection_count_defaults_to_zero_without_pool_support() -> None:
    # Given: a pool implementation without SQLAlchemy QueuePool's checkedout method
    engine = _engine_with_pool(_PoolWithoutCheckedout())

    # When: reading the checked-out connection count
    value = _checked_out_connection_count(engine)

    # Then: unsupported pools report zero instead of failing metrics collection
    assert value == 0.0
