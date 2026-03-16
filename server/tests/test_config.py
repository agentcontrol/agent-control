"""Tests for server configuration helpers."""

from agent_control_server.config import (
    AgentControlServerDatabaseConfig,
    ObservabilitySettings,
    Settings,
)


def test_db_config_prefers_explicit_url() -> None:
    # Given: a database config with an explicit URL set
    explicit_url = "sqlite:///tmp/test.db"
    config = AgentControlServerDatabaseConfig(url=explicit_url)

    # When: getting the database URL
    resolved = config.get_url()

    # Then: the explicit URL is returned
    assert resolved == explicit_url


def test_db_config_reads_agent_control_url_from_env(monkeypatch) -> None:
    # Given: the canonical database URL env var is set
    monkeypatch.setenv("AGENT_CONTROL_DB_URL", "sqlite:///tmp/canonical.db")

    # When: loading DB config from the environment
    config = AgentControlServerDatabaseConfig()

    # Then: the canonical Agent Control env var is used
    assert config.get_url() == "sqlite:///tmp/canonical.db"


def test_db_config_reads_database_url_from_env(monkeypatch) -> None:
    # Given: only the legacy DATABASE_URL env var is set
    monkeypatch.delenv("AGENT_CONTROL_DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/legacy.db")

    # When: loading DB config from the environment
    config = AgentControlServerDatabaseConfig()

    # Then: the legacy env var is still supported during migration
    assert config.get_url() == "sqlite:///tmp/legacy.db"


def test_db_config_reads_legacy_db_prefix_from_env(monkeypatch) -> None:
    # Given: only the legacy DB_* env vars are set
    monkeypatch.delenv("AGENT_CONTROL_DB_HOST", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_DB_PORT", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_DB_USER", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_DB_PASSWORD", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_DB_DATABASE", raising=False)
    monkeypatch.delenv("AGENT_CONTROL_DB_DRIVER", raising=False)
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_PORT", "15432")
    monkeypatch.setenv("DB_USER", "legacy_user")
    monkeypatch.setenv("DB_PASSWORD", "legacy_password")
    monkeypatch.setenv("DB_DATABASE", "legacy_db")
    monkeypatch.setenv("DB_DRIVER", "psycopg")

    # When: loading DB config from the environment
    config = AgentControlServerDatabaseConfig()

    # Then: the legacy env vars remain compatible
    assert config.get_url() == "postgresql+psycopg://legacy_user:legacy_password@db.example:15432/legacy_db"


def test_db_config_prefers_agent_control_env_over_legacy(monkeypatch) -> None:
    # Given: both canonical and legacy database URLs are present
    monkeypatch.setenv("AGENT_CONTROL_DB_URL", "sqlite:///tmp/canonical.db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/legacy.db")

    # When: loading DB config from the environment
    config = AgentControlServerDatabaseConfig()

    # Then: the canonical env var wins
    assert config.get_url() == "sqlite:///tmp/canonical.db"


def test_db_config_ignores_blank_agent_control_url_and_uses_legacy(monkeypatch) -> None:
    # Given: the canonical URL is blank but a legacy URL is still configured
    monkeypatch.setenv("AGENT_CONTROL_DB_URL", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///tmp/legacy.db")

    # When: loading DB config from the environment
    config = AgentControlServerDatabaseConfig()

    # Then: the blank canonical env var is ignored
    assert config.get_url() == "sqlite:///tmp/legacy.db"


def test_settings_parses_cors_origins_string() -> None:
    # Given: a comma-separated CORS origins string
    settings = Settings(cors_origins="https://a.example, https://b.example")

    # When: parsing CORS origins
    origins = settings.get_cors_origins()

    # Then: the origins are split and trimmed
    assert origins == ["https://a.example", "https://b.example"]


def test_settings_reads_agent_control_prefixed_env_vars(monkeypatch) -> None:
    # Given: canonical Agent Control server env vars are set
    monkeypatch.setenv("AGENT_CONTROL_HOST", "127.0.0.1")
    monkeypatch.setenv("AGENT_CONTROL_CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("AGENT_CONTROL_ALLOW_METHODS", "GET, POST")
    monkeypatch.setenv("AGENT_CONTROL_ALLOW_HEADERS", "Authorization, Content-Type")

    # When: loading settings from the environment
    config = Settings()

    # Then: the canonical env vars are parsed correctly
    assert config.host == "127.0.0.1"
    assert config.get_cors_origins() == ["https://a.example", "https://b.example"]
    assert config.get_allow_methods() == ["GET", "POST"]
    assert config.get_allow_headers() == ["Authorization", "Content-Type"]


def test_settings_reads_legacy_env_vars(monkeypatch) -> None:
    # Given: only legacy server env vars are set
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("API_VERSION", "v2")
    monkeypatch.setenv("API_PREFIX", "/legacy")
    monkeypatch.setenv("PROMETHEUS_METRICS_PREFIX", "legacy_metrics")
    monkeypatch.setenv("CORS_ORIGINS", "https://legacy.example")
    monkeypatch.setenv("ALLOW_METHODS", "GET, POST")
    monkeypatch.setenv("ALLOW_HEADERS", "Authorization, Content-Type")

    # When: loading settings from the environment
    config = Settings()

    # Then: the legacy env vars remain compatible
    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.debug is True
    assert config.api_version == "v2"
    assert config.api_prefix == "/legacy"
    assert config.prometheus_metrics_prefix == "legacy_metrics"
    assert config.get_cors_origins() == ["https://legacy.example"]
    assert config.get_allow_methods() == ["GET", "POST"]
    assert config.get_allow_headers() == ["Authorization", "Content-Type"]


def test_settings_prefers_agent_control_env_vars_over_legacy(monkeypatch) -> None:
    # Given: both canonical and legacy server env vars are set
    monkeypatch.setenv("AGENT_CONTROL_PORT", "7000")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("AGENT_CONTROL_CORS_ORIGINS", "https://canonical.example")
    monkeypatch.setenv("CORS_ORIGINS", "https://legacy.example")

    # When: loading settings from the environment
    config = Settings()

    # Then: the canonical env vars win
    assert config.port == 7000
    assert config.get_cors_origins() == ["https://canonical.example"]


def test_settings_ignore_blank_agent_control_port_and_use_legacy(monkeypatch) -> None:
    # Given: the canonical port is blank but the legacy port is still set
    monkeypatch.setenv("AGENT_CONTROL_PORT", "")
    monkeypatch.setenv("PORT", "9000")

    # When: loading settings from the environment
    config = Settings()

    # Then: the blank canonical env var is ignored
    assert config.port == 9000


def test_settings_returns_cors_origins_list_unchanged() -> None:
    # Given: a CORS origins list
    settings = Settings(cors_origins=["https://a.example", "https://b.example"])

    # When: parsing CORS origins
    origins = settings.get_cors_origins()

    # Then: the list is returned as-is
    assert origins == ["https://a.example", "https://b.example"]


def test_observability_settings_support_prefixed_env_vars(monkeypatch) -> None:
    # Given: canonical observability env vars are set
    monkeypatch.setenv("AGENT_CONTROL_OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("AGENT_CONTROL_OBSERVABILITY_STDOUT", "true")

    # When: loading observability settings from the environment
    config = ObservabilitySettings()

    # Then: the Agent Control-prefixed env vars are used
    assert config.enabled is False
    assert config.stdout is True


def test_observability_settings_ignore_legacy_env_vars(monkeypatch) -> None:
    # Given: only legacy observability env vars are set
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "false")
    monkeypatch.setenv("OBSERVABILITY_STDOUT", "true")

    # When: loading observability settings from the environment
    config = ObservabilitySettings()

    # Then: the legacy env vars are ignored
    assert config.enabled is True
    assert config.stdout is False
