"""Server configuration settings."""
import os
from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Authentication configuration for API key validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="AGENT_CONTROL_",
    )

    # Master toggle for authentication (disabled by default for local development)
    # Enable in production: AGENT_CONTROL_API_KEY_ENABLED=true
    api_key_enabled: bool = False

    # API keys (comma-separated list supports multiple keys for rotation)
    # Env: AGENT_CONTROL_API_KEYS="key1,key2,key3"
    api_keys: str = ""

    # Admin API keys (subset with elevated privileges)
    # Env: AGENT_CONTROL_ADMIN_API_KEYS="admin-key1,admin-key2"
    admin_api_keys: str = ""

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


class AgentControlServerDatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="DB_",
        extra="ignore",  # Ignore extra fields in .env
    )

    # Allow direct URL override for SQLite in local dev
    url: str | None = None

    # PostgreSQL settings (only used if url is not set)
    host: str = "localhost"
    port: int = 5432
    user: str = "agent_control"
    password: str = "agent_control"
    database: str = "agent_control"
    driver: str = "psycopg"

    def get_url(self) -> str:
        """Get database URL, preferring explicit url if set."""

        # Check for DATABASE_URL first (Docker standard), then DB_URL
        database_url = os.getenv('DATABASE_URL') or self.url
        if database_url:
            return database_url
        return (
            f"postgresql+{self.driver}://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        )


class Settings(BaseSettings):
    """Server configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields in .env (like DB_* fields)
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # API settings
    api_version: str = "v1"
    api_prefix: str = "/api"

    # Prometheus metrics settings
    prometheus_metrics_prefix: str = "agent_control_server"

    # CORS settings
    cors_origins: list[str] | str = "*"
    allow_methods: list[str] = ["*"]
    allow_headers: list[str] = ["*"]

    def get_cors_origins(self) -> list[str]:
        """Parse CORS origins from string or list."""
        if isinstance(self.cors_origins, str):
            if self.cors_origins == "*":
                return ["*"]
            return [origin.strip() for origin in self.cors_origins.split(",")]
        return self.cors_origins


class ObservabilitySettings(BaseSettings):
    """Observability configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="OBSERVABILITY_",
        extra="ignore",
    )

    # Enable/disable observability features
    enabled: bool = True

    # Stdout logging of events
    stdout: bool = False


auth_settings = AuthSettings()
db_config = AgentControlServerDatabaseConfig()
settings = Settings()
observability_settings = ObservabilitySettings()
