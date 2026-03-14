import logging

from .config import LoggingSettings

_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def _parse_level(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        return _LEVELS.get(level.upper(), logging.INFO)
    configured_level = LoggingSettings().level
    if configured_level is not None:
        return _LEVELS.get(configured_level.upper(), logging.INFO)
    return logging.INFO


def get_log_level_name(default_level: str = "INFO") -> str:
    """Resolve the configured log level name, falling back to the provided default."""
    normalized_default = default_level.upper()
    if normalized_default not in _LEVELS:
        normalized_default = "INFO"

    configured_level = LoggingSettings().level
    if configured_level is not None:
        normalized = configured_level.upper()
        if normalized in _LEVELS:
            return normalized
        return normalized_default
    return normalized_default


def _parse_json(json_flag: bool | None) -> bool:
    if isinstance(json_flag, bool):
        return json_flag
    return LoggingSettings().json_logs


def configure_logging(
    *,
    level: str | int | None = None,
    json: bool | None = None,
    default_level: str = "INFO",
) -> None:
    resolved_level = level if level is not None else get_log_level_name(default_level)
    lvl = _parse_level(resolved_level)
    as_json = _parse_json(json)
    fmt = (
        '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}'
        if as_json
        else "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    datefmt = "%Y-%m-%dT%H:%M:%S%z"

    root = logging.getLogger()
    root.setLevel(lvl)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.setLevel(lvl)
        logger.propagate = True
        for h in list(logger.handlers):
            logger.removeHandler(h)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
