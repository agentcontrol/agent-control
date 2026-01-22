#!/usr/bin/env python
"""Initialize the database with tables."""

import asyncio

from sqlalchemy import create_engine

from src.agent_control_server.config import db_config
from src.agent_control_server.models import Base


async def init_db():
    """Create all database tables."""
    db_url = db_config.get_url()

    engine = create_engine(db_url, echo=True)

    print(f"Creating tables in database: {db_url}")
    Base.metadata.create_all(engine)
    print("✓ Database tables created successfully!")


if __name__ == "__main__":
    asyncio.run(init_db())

