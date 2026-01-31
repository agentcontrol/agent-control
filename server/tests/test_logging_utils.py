"""Tests for logging utilities."""

import logging

from agent_control_server.logging_utils import _parse_json, _parse_level, configure_logging


def test_parse_level_accepts_int() -> None:
    # Given: a numeric log level
    level = logging.WARNING

    # When: parsing the level
    parsed = _parse_level(level)

    # Then: the numeric level is returned unchanged
    assert parsed == logging.WARNING


def test_parse_level_uses_env_default(monkeypatch) -> None:
    # Given: LOG_LEVEL set in the environment
    monkeypatch.setenv("LOG_LEVEL", "ERROR")

    # When: parsing with no explicit level
    parsed = _parse_level(None)

    # Then: the environment level is used
    assert parsed == logging.ERROR


def test_parse_json_accepts_bool() -> None:
    # Given: an explicit JSON flag
    flag = True

    # When: parsing the JSON flag
    parsed = _parse_json(flag)

    # Then: the boolean value is returned unchanged
    assert parsed is True


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
