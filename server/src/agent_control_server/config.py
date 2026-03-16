"""Server configuration settings."""

import logging
import secrets
from functools import cached_property
from typing import Any

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = logging.getLogger(__name__)

_COMMON_SETTINGS_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    env_ignore_empty=True,
    extra="ignore",
    populate_by_name=True,
)


def _env_alias_field(default: Any, *env_names: str) -> Any:
    """Create a field that accepts multiple environment variable names."""
    return Field(default=default, validation_alias=AliasChoices(*env_names))


class AuthSettings(BaseSettings):
    """Authentication configuration for API key validation."""

    model_config = SettingsConfigDict(**_COMMON_SETTINGS_CONFIG, env_prefix="AGENT_CONTROL_")

    # Master toggle for authentication (disabled by default for local development)
    # Enable in production: AGENT_CONTROL_API_KEY_ENABLED=true
    api_key_enabled: bool = False

    # API keys (comma-separated list supports multiple keys for rotation)
    # Env: AGENT_CONTROL_API_KEYS="key1,key2,key3"
    api_keys: str = ""

    # Admin API keys (subset with elevated privileges)
    # Env: AGENT_CONTROL_ADMIN_API_KEYS="admin-key1,admin-key2"
    admin_api_keys: str = ""

    # Secret for signing session JWTs.
    # Env: AGENT_CONTROL_SESSION_SECRET="<random-string>"
    # If unset, a random secret is generated at startup (sessions won't survive
    # restarts or work across multiple server instances).
    session_secret: str = ""

    @cached_property
    def _parsed_api_keys(self) -> set[str]:
        """Parse and cache API keys from comma-separated string."""
        if not self.api_keys:
            return set()
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @cached_property
    def _parsed_admin_api_keys(self) -> set[str]:
        """Parse and cache admin API keys from comma-separated string."""
        if not self.admin_api_keys:
            return set()
        return {k.strip() for k in self.admin_api_keys.split(",") if k.strip()}

    @cached_property
    def _all_valid_keys(self) -> set[str]:
        """Cache the union of all valid keys for fast lookup."""
        return self._parsed_api_keys | self._parsed_admin_api_keys

    def get_api_keys(self) -> set[str]:
        """Get parsed API keys (cached)."""
        return self._parsed_api_keys

    def get_admin_api_keys(self) -> set[str]:
        """Get parsed admin API keys (cached)."""
        return self._parsed_admin_api_keys

    def is_valid_api_key(self, key: str) -> bool:
        """Check if key is a valid API key (regular or admin). O(1) lookup."""
        return key in self._all_valid_keys

    def is_admin_api_key(self, key: str) -> bool:
        """Check if key is an admin API key. O(1) lookup."""
        return key in self._parsed_admin_api_keys

    @cached_property
    def _resolved_session_secret(self) -> str:
        """Resolve session secret, generating an ephemeral one if not configured."""
        if self.session_secret:
            return self.session_secret
        _config_logger.warning(
            "AGENT_CONTROL_SESSION_SECRET is not set. Using an ephemeral random secret. "
            "Sessions will not survive server restarts or work across multiple instances. "
            "Set AGENT_CONTROL_SESSION_SECRET for production deployments."
        )
        return secrets.token_urlsafe(32)

    def get_session_secret(self) -> str:
        """Get the JWT signing secret (cached)."""
        return self._resolved_session_secret


class AgentControlServerDatabaseConfig(BaseSettings):
    """Database configuration for the server."""

    model_config = SettingsConfigDict(**_COMMON_SETTINGS_CONFIG, env_prefix="AGENT_CONTROL_DB_")

    # Allow direct URL override for SQLite in local dev
    url: str | None = _env_alias_field(None, "AGENT_CONTROL_DB_URL", "DATABASE_URL", "DB_URL")

    # PostgreSQL settings (only used if url is not set)
    host: str = _env_alias_field("localhost", "AGENT_CONTROL_DB_HOST", "DB_HOST")
    port: int = _env_alias_field(5432, "AGENT_CONTROL_DB_PORT", "DB_PORT")
    user: str = _env_alias_field("agent_control", "AGENT_CONTROL_DB_USER", "DB_USER")
    password: str = _env_alias_field(
        "agent_control",
        "AGENT_CONTROL_DB_PASSWORD",
        "DB_PASSWORD",
    )
    database: str = _env_alias_field(
        "agent_control",
        "AGENT_CONTROL_DB_DATABASE",
        "DB_DATABASE",
    )
    driver: str = _env_alias_field("psycopg", "AGENT_CONTROL_DB_DRIVER", "DB_DRIVER")

    def get_url(self) -> str:
        """Get database URL, preferring an explicit URL if configured."""
        if self.url:
            return self.url
        return (
            f"postgresql+{self.driver}://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        )


class Settings(BaseSettings):
    """Server configuration settings."""

    model_config = SettingsConfigDict(**_COMMON_SETTINGS_CONFIG, env_prefix="AGENT_CONTROL_")

    # Server settings
    host: str = _env_alias_field("0.0.0.0", "AGENT_CONTROL_HOST", "HOST")
    port: int = _env_alias_field(8000, "AGENT_CONTROL_PORT", "PORT")
    debug: bool = _env_alias_field(False, "AGENT_CONTROL_DEBUG", "DEBUG")

    # API settings
    api_version: str = _env_alias_field("v1", "AGENT_CONTROL_API_VERSION", "API_VERSION")
    api_prefix: str = _env_alias_field("/api", "AGENT_CONTROL_API_PREFIX", "API_PREFIX")

    # Prometheus metrics settings
    prometheus_metrics_prefix: str = _env_alias_field(
        "agent_control_server",
        "AGENT_CONTROL_PROMETHEUS_METRICS_PREFIX",
        "PROMETHEUS_METRICS_PREFIX",
    )

    # CORS settings
    cors_origins: list[str] | str = _env_alias_field(
        "*",
        "AGENT_CONTROL_CORS_ORIGINS",
        "CORS_ORIGINS",
    )
    allow_methods: list[str] | str = _env_alias_field(
        ["*"],
        "AGENT_CONTROL_ALLOW_METHODS",
        "ALLOW_METHODS",
    )
    allow_headers: list[str] | str = _env_alias_field(
        ["*"],
        "AGENT_CONTROL_ALLOW_HEADERS",
        "ALLOW_HEADERS",
    )

    def get_cors_origins(self) -> list[str]:
        """Parse CORS origins from string or list."""
        return self._parse_list_setting(self.cors_origins)

    def get_allow_methods(self) -> list[str]:
        """Parse allow_methods from string or list."""
        return self._parse_list_setting(self.allow_methods)

    def get_allow_headers(self) -> list[str]:
        """Parse allow_headers from string or list."""
        return self._parse_list_setting(self.allow_headers)

    @staticmethod
    def _parse_list_setting(value: list[str] | str) -> list[str]:
        """Parse wildcard/comma-separated settings from string or list."""
        if isinstance(value, str):
            if value == "*":
                return ["*"]
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


class ObservabilitySettings(BaseSettings):
    """Observability configuration settings."""

    model_config = SettingsConfigDict(
        **_COMMON_SETTINGS_CONFIG,
        env_prefix="AGENT_CONTROL_OBSERVABILITY_",
    )

    # Enable/disable observability features
    enabled: bool = True

    # Stdout logging of events
    stdout: bool = False


class LoggingSettings(BaseSettings):
    """Server logging configuration settings."""

    model_config = SettingsConfigDict(**_COMMON_SETTINGS_CONFIG, env_prefix="AGENT_CONTROL_LOG_")

    level: str | None = None
    json_logs: bool = _env_alias_field(False, "AGENT_CONTROL_LOG_JSON")


class UISettings(BaseSettings):
    """Static UI hosting configuration settings."""

    model_config = SettingsConfigDict(**_COMMON_SETTINGS_CONFIG, env_prefix="AGENT_CONTROL_UI_")

    dist_dir: str | None = None


auth_settings = AuthSettings()
db_config = AgentControlServerDatabaseConfig()
settings = Settings()
observability_settings = ObservabilitySettings()
ui_settings = UISettings()
