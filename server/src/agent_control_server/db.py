from collections.abc import AsyncGenerator
from typing import Any

from prometheus_client import Gauge
from sqlalchemy import event
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncEngine
from sqlalchemy.orm import DeclarativeBase

from .config import AgentControlServerDatabaseConfig, db_config


class Base(DeclarativeBase):
    pass


# Async SQLAlchemy setup for PostgreSQL
db_url = db_config.get_url()

SQLALCHEMY_CHECKED_OUT_CONNECTIONS = Gauge(
    "agent_control_server_sqlalchemy_checked_out_connections",
    "Number of checked out SQLAlchemy connections.",
    ["pool_name"],
    multiprocess_mode="livesum",
)


def _supports_queue_pool_config(url: str) -> bool:
    """Return whether SQLAlchemy QueuePool kwargs should be applied for this URL."""
    return make_url(url).get_backend_name() != "sqlite"


def _build_async_engine_kwargs(
    url: str,
    config: AgentControlServerDatabaseConfig,
) -> dict[str, Any]:
    """Build async SQLAlchemy engine kwargs from database config."""
    kwargs: dict[str, Any] = {"echo": False}
    if not _supports_queue_pool_config(url):
        return kwargs

    kwargs.update(
        pool_pre_ping=True,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout_seconds,
        pool_reset_on_return="rollback",
    )
    return kwargs


def _instrument_connection_pool(engine: AsyncEngine) -> None:
    """Track checked-out connections from the async engine's underlying pool."""

    @event.listens_for(engine.sync_engine.pool, "checkin")
    def receive_checkin(dbapi_conn: Any, connection_record: Any) -> None:
        SQLALCHEMY_CHECKED_OUT_CONNECTIONS.labels("default").dec()

    @event.listens_for(engine.sync_engine.pool, "checkout")
    def receive_checkout(dbapi_conn: Any, connection_record: Any, connection_proxy: Any) -> None:
        SQLALCHEMY_CHECKED_OUT_CONNECTIONS.labels("default").inc()


async_engine = create_async_engine(db_url, **_build_async_engine_kwargs(db_url, db_config))
_instrument_connection_pool(async_engine)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    autoflush=False,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
