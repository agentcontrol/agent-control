import pytest
from agent_control_engine import discover_evaluators
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_control_server.config import auth_settings, db_config
from agent_control_server.db import Base
from agent_control_server.main import app as fastapi_app
from agent_control_server.models import ControlStore

# Discover evaluators at test session start
discover_evaluators()

# Test API keys
TEST_API_KEY = "test-api-key-12345"
TEST_ADMIN_API_KEY = "test-admin-key-12345"

# Create sync engine for tests (schema creation/cleanup)
engine = create_engine(db_config.get_url(), echo=False)

# Create async engine for async tests
async_engine = create_async_engine(db_config.get_url(), echo=False)
AsyncSessionTest = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def _truncate_all_tables() -> None:
    """Clear all tables in the configured test database."""
    with engine.begin() as conn:
        schema = "public" if conn.dialect.name == "postgresql" else None
        table_names = inspect(conn).get_table_names(schema=schema)
        if not table_names:
            return

        if conn.dialect.name == "postgresql":
            qualified_tables = ", ".join(f'"{schema}"."{table_name}"' for table_name in table_names)
            conn.execute(text(f"TRUNCATE TABLE {qualified_tables} RESTART IDENTITY CASCADE"))
            return

        reflected_metadata = MetaData()
        reflected_metadata.reflect(bind=conn)
        for table in reversed(reflected_metadata.sorted_tables):
            conn.execute(table.delete())


def _seed_default_control_store() -> None:
    """Seed the default control store for tests that create tables directly."""
    with engine.begin() as conn:
        schema = "public" if conn.dialect.name == "postgresql" else None
        if "control_stores" not in inspect(conn).get_table_names(schema=schema):
            return

        existing = conn.execute(
            text("SELECT id FROM control_stores WHERE name = 'default' LIMIT 1")
        ).scalar()
        if existing is None:
            conn.execute(
                ControlStore.__table__.insert().values(id=1, name="default")
            )


@pytest.fixture(scope="session")
def db_engine():
    """Provide the sqlalchemy engine for tests."""
    return engine


@pytest.fixture(scope="session")
def app():
    """Provide the FastAPI app."""
    return fastapi_app


@pytest.fixture(scope="session", autouse=True)
def db_schema() -> None:
    # Ensure test database exists (PostgreSQL)
    if engine.dialect.name == "postgresql":
        admin_url = (
            f"postgresql+{db_config.driver}://{db_config.user}:{db_config.password}@"
            f"{db_config.host}:{db_config.port}/postgres"
        )
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_config.database},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_config.database}"'))
        admin_engine.dispose()

    # Recreate tables for tests in the configured database.
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        reflected_metadata = MetaData()
        reflected_metadata.reflect(bind=engine)
        reflected_metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _seed_default_control_store()
    yield


@pytest.fixture(autouse=True)
def setup_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable auth with test keys for all tests by default."""
    monkeypatch.setattr(auth_settings, "api_key_enabled", True)
    monkeypatch.setattr(auth_settings, "api_keys", TEST_API_KEY)
    monkeypatch.setattr(auth_settings, "admin_api_keys", TEST_ADMIN_API_KEY)
    # Clear cached properties so they recompute with monkeypatched values
    for attr in (
        "_parsed_api_keys",
        "_parsed_admin_api_keys",
        "_all_valid_keys",
        "_all_admin_keys",
    ):
        auth_settings.__dict__.pop(attr, None)


@pytest.fixture()
def client(app: object) -> TestClient:
    """Default test client with admin API key header."""
    return TestClient(
        app,
        raise_server_exceptions=True,
        headers={"X-API-Key": TEST_ADMIN_API_KEY},
    )


@pytest.fixture()
def non_admin_client(app: object) -> TestClient:
    """Test client with non-admin API key header."""
    return TestClient(
        app,
        raise_server_exceptions=True,
        headers={"X-API-Key": TEST_API_KEY},
    )


@pytest.fixture()
def admin_client(app: object) -> TestClient:
    """Test client with admin API key header."""
    return TestClient(
        app,
        raise_server_exceptions=True,
        headers={"X-API-Key": TEST_ADMIN_API_KEY},
    )


@pytest.fixture()
def unauthenticated_client(app: object) -> TestClient:
    """Test client without API key header."""
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def clean_db():
    _truncate_all_tables()
    _seed_default_control_store()
    yield


@pytest.fixture
async def async_db():
    """Provide async database session for tests."""
    async with AsyncSessionTest() as session:
        yield session
        await session.rollback()


@pytest.fixture
def postgres_event_store():
    """Provide PostgresEventStore for observability tests."""
    from agent_control_server.observability import PostgresEventStore

    return PostgresEventStore(AsyncSessionTest)


@pytest.fixture
def setup_observability(postgres_event_store):
    """Set up observability store and ingestor on app.state."""
    from agent_control_server.observability import DirectEventIngestor

    ingestor = DirectEventIngestor(postgres_event_store)
    fastapi_app.state.event_store = postgres_event_store
    fastapi_app.state.event_ingestor = ingestor
    yield postgres_event_store
    # Clean up app.state
    del fastapi_app.state.event_store
    del fastapi_app.state.event_ingestor
