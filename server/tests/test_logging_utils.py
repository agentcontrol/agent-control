"""Tests for logging utilities."""

import logging

from agent_control_server.logging_utils import (
    _parse_json,
    _parse_level,
    configure_logging,
    get_log_level_name,
    get_uvicorn_log_level_name,
)


def test_parse_level_accepts_int() -> None:
    # Given: a numeric log level
    level = logging.WARNING

    # When: parsing the level
    parsed = _parse_level(level)

    # Then: the numeric level is returned unchanged
    assert parsed == logging.WARNING


def test_parse_level_uses_env_default(monkeypatch) -> None:
    # Given: AGENT_CONTROL_LOG_LEVEL set in the environment
    monkeypatch.setenv("AGENT_CONTROL_LOG_LEVEL", "ERROR")

    # When: parsing with no explicit level
    parsed = _parse_level(None)

    # Then: the environment level is used
    assert parsed == logging.ERROR


def test_parse_level_ignores_legacy_env(monkeypatch) -> None:
    # Given: only the legacy logging env var is set
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    # When: parsing with no explicit level
    parsed = _parse_level(None)

    # Then: the legacy env var is ignored
    assert parsed == logging.INFO


def test_parse_json_accepts_bool() -> None:
    # Given: an explicit JSON flag
    flag = True

    # When: parsing the JSON flag
    parsed = _parse_json(flag)

    # Then: the boolean value is returned unchanged
    assert parsed is True


def test_parse_json_uses_canonical_env_default(monkeypatch) -> None:
    # Given: AGENT_CONTROL_LOG_JSON is enabled
    monkeypatch.setenv("AGENT_CONTROL_LOG_JSON", "true")

    # When: parsing with no explicit flag
    parsed = _parse_json(None)

    # Then: the canonical env var is used
    assert parsed is True


def test_parse_json_treats_blank_env_value_as_false(monkeypatch) -> None:
    # Given: AGENT_CONTROL_LOG_JSON is declared but blank
    monkeypatch.setenv("AGENT_CONTROL_LOG_JSON", "")

    # When: parsing with no explicit flag
    parsed = _parse_json(None)

    # Then: the blank env var is treated as false instead of raising
    assert parsed is False


def test_get_log_level_name_falls_back_to_default_for_invalid_env(monkeypatch) -> None:
    # Given: AGENT_CONTROL_LOG_LEVEL is present but invalid
    monkeypatch.setenv("AGENT_CONTROL_LOG_LEVEL", "not-a-level")

    # When: resolving the log level with a DEBUG default
    resolved = get_log_level_name("DEBUG")

    # Then: the provided default is used
    assert resolved == "DEBUG"


def test_get_log_level_name_treats_blank_env_as_unset(monkeypatch) -> None:
    # Given: AGENT_CONTROL_LOG_LEVEL is declared but blank
    monkeypatch.setenv("AGENT_CONTROL_LOG_LEVEL", "")

    # When: resolving the log level with a DEBUG default
    resolved = get_log_level_name("DEBUG")

    # Then: the provided default is used
    assert resolved == "DEBUG"


def test_get_uvicorn_log_level_name_falls_back_from_notset(monkeypatch) -> None:
    # Given: a configured level that Python logging accepts but uvicorn does not
    monkeypatch.setenv("AGENT_CONTROL_LOG_LEVEL", "NOTSET")

    # When: resolving the uvicorn log level
    resolved = get_uvicorn_log_level_name("DEBUG")

    # Then: uvicorn gets a supported fallback level
    assert resolved == "DEBUG"


def test_configure_logging_resets_uvicorn_handlers() -> None:
    # Given: a uvicorn logger with a custom handler
    logger = logging.getLogger("uvicorn")
    handler = logging.StreamHandler()
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate
    logger.addHandler(handler)

    root = logging.getLogger()
    root_handlers = list(root.handlers)
    root_level = root.level

    try:
        # When: configuring logging
        configure_logging(level="INFO", json=False)

        # Then: uvicorn handlers are removed and propagate is enabled
        assert handler not in logger.handlers
        assert logger.propagate is True
        assert logger.level == logging.INFO
    finally:
        # Restore logger state to avoid cross-test side effects
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate
        root.handlers = root_handlers
        root.setLevel(root_level)
