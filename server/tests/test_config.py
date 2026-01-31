"""Tests for server configuration helpers."""

from agent_control_server.config import AgentControlServerDatabaseConfig, Settings


def test_db_config_prefers_explicit_url() -> None:
    # Given: a database config with an explicit URL set
    explicit_url = "sqlite:///tmp/test.db"
    config = AgentControlServerDatabaseConfig(url=explicit_url)

    # When: getting the database URL
    resolved = config.get_url()

    # Then: the explicit URL is returned
    assert resolved == explicit_url


def test_settings_parses_cors_origins_string() -> None:
    # Given: a comma-separated CORS origins string
    settings = Settings(cors_origins="https://a.example, https://b.example")

    # When: parsing CORS origins
    origins = settings.get_cors_origins()

    # Then: the origins are split and trimmed
    assert origins == ["https://a.example", "https://b.example"]


def test_settings_returns_cors_origins_list_unchanged() -> None:
    # Given: a CORS origins list
    settings = Settings(cors_origins=["https://a.example", "https://b.example"])

    # When: parsing CORS origins
    origins = settings.get_cors_origins()

    # Then: the list is returned as-is
    assert origins == ["https://a.example", "https://b.example"]
