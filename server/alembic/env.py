import os
import sys

from sqlalchemy import create_engine, pool

from alembic import context

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import agent_control_server.models  # noqa: E402,F401
from agent_control_server.config import db_config  # noqa: E402
from agent_control_server.db import Base  # noqa: E402

config = context.config

target_metadata = Base.metadata


def _get_migration_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url:
        return configured_url
    return db_config.get_url()


def run_migrations_offline() -> None:
    url = _get_migration_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _get_migration_url()
    connectable = create_engine(url, future=True, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
