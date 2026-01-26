"""
Centralized configuration for Agent Control SDK.

This module provides typed configuration via pydantic-settings, supporting:
- Environment variables with AGENT_CONTROL_ prefix
- Type coercion and validation
- Programmatic overrides

Usage:
    from agent_control.settings import settings

    # Access settings
    if settings.observability_enabled:
        send_events()

    # Settings are read from environment variables:
    # AGENT_CONTROL_URL, AGENT_CONTROL_OBSERVABILITY_ENABLED, etc.
"""

from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SDKSettings(BaseSettings):
    """
    Configuration for Agent Control SDK.

    Includes settings for:
    - Server connection (url, api_key)
    - Observability/event batching
    - Logging verbosity

    All settings can be configured via environment variables with the
    AGENT_CONTROL_ prefix. For example:
        AGENT_CONTROL_URL=http://localhost:8000
        AGENT_CONTROL_OBSERVABILITY_ENABLED=true

    Settings can also be overridden programmatically via configure_settings().
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENT_CONTROL_",
        extra="ignore",
    )

    # Server connection
    url: str = Field(
        default="http://localhost:8000",
        description="Base URL of the Agent Control server",
    )
    api_key: str = Field(
        default="",
        description="API key for server authentication",
    )

    # Observability (event batching)
    observability_enabled: bool = Field(
        default=False,
        description="Enable sending events to server (default: disabled)",
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        description="Maximum events per batch",
    )
    flush_interval: float = Field(
        default=10.0,
        gt=0,
        description="Seconds between automatic flushes",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="Maximum retry attempts for failed batch sends",
    )
    retry_delay: float = Field(
        default=1.0,
        gt=0,
        description="Base delay between retries (seconds)",
    )

    # Logging configuration
    log_enabled: bool = Field(
        default=True,
        description="Master switch for observability logging",
    )
    log_level: str = Field(
        default="INFO",
        description="Log level (DEBUG, INFO, WARNING, ERROR)",
    )
    log_span_start: bool = Field(
        default=True,
        description="Log span start events",
    )
    log_span_end: bool = Field(
        default=True,
        description="Log span end events",
    )
    log_control_eval: bool = Field(
        default=True,
        description="Log per-control evaluation events",
    )
    log_span_results: bool = Field(
        default=True,
        description="Log span results (legacy compatibility)",
    )


# Global settings instance - loaded from environment at import time
settings = SDKSettings()


def get_settings() -> SDKSettings:
    """Get the current settings instance."""
    return settings


def configure_settings(**kwargs: Any) -> SDKSettings:
    """
    Override settings programmatically.

    This creates a new settings instance with the provided overrides
    and replaces the global instance.

    Args:
        **kwargs: Setting names and values to override

    Returns:
        The updated settings instance

    Example:
        configure_settings(
            observability_enabled=True,
            batch_size=50,
            log_control_eval=False,
        )
    """
    global settings
    # Get current values as dict, apply overrides
    current = settings.model_dump()
    current.update(kwargs)
    settings = SDKSettings(**current)
    return settings
