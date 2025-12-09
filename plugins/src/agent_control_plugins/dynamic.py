"""Dynamic evaluator factory for custom evaluators from database.

Creates PluginEvaluator subclasses from code strings with instance caching.
"""

import logging
import signal
import threading
from contextlib import contextmanager
from types import CodeType
from typing import Any, Generator

from agent_control_models import EvaluatorResult, PluginEvaluator, PluginMetadata, register_plugin
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Cache for compiled code objects
_CODE_CACHE: dict[str, CodeType] = {}

# Cache for dynamically created plugin classes
_CLASS_CACHE: dict[str, type[PluginEvaluator[Any]]] = {}

# Cache for plugin instances (keyed by name + config hash)
_INSTANCE_CACHE: dict[str, PluginEvaluator[Any]] = {}


class DynamicConfig(BaseModel):
    """Config model for dynamic evaluators - wraps user_config."""

    user_config: dict[str, Any] = {}
    timeout_ms: int = 5000
    on_error: str = "deny"


@contextmanager
def timeout_context(seconds: float) -> Generator[None, None, None]:
    """Context manager for execution timeout using SIGALRM."""
    if not hasattr(signal, "SIGALRM"):
        yield
        return

    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"Execution exceeded {seconds}s timeout")

    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)

    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def _config_hash(config: dict[str, Any]) -> str:
    """Create a hashable key from config dict."""
    import json

    return json.dumps(config, sort_keys=True, default=str)


def create_dynamic_evaluator_class(
    name: str,
    code: str,
    description: str | None = None,
    entrypoint: str = "evaluate",
    timeout_ms: int = 5000,
    config_schema: dict[str, Any] | None = None,
) -> type[PluginEvaluator[DynamicConfig]]:
    """Create a PluginEvaluator subclass from code string.

    Args:
        name: Unique evaluator name
        code: Python code defining the evaluate function
        description: Optional description
        entrypoint: Function name to call (default: "evaluate")
        timeout_ms: Default timeout in milliseconds
        config_schema: JSON Schema for config validation

    Returns:
        A PluginEvaluator subclass that executes the custom code
    """
    # Check class cache first
    cache_key = f"{name}:{hash(code)}:{entrypoint}"
    if cache_key in _CLASS_CACHE:
        return _CLASS_CACHE[cache_key]

    # Compile code
    if code not in _CODE_CACHE:
        _CODE_CACHE[code] = compile(code, filename=f"<{name}>", mode="exec")
    compiled = _CODE_CACHE[code]

    class DynamicEvaluator(PluginEvaluator[DynamicConfig]):
        """Dynamically created evaluator from custom code."""

        metadata = PluginMetadata(
            name=name,
            version="1.0.0",
            description=description or f"Custom evaluator: {name}",
            timeout_ms=timeout_ms,
            config_schema=config_schema,
        )
        config_model = DynamicConfig

        _compiled: CodeType = compiled
        _entrypoint: str = entrypoint

        def evaluate(self, data: Any) -> EvaluatorResult:
            """Execute custom code to evaluate data."""
            timeout_sec = self.config.timeout_ms / 1000.0
            user_config = self.config.user_config

            exec_globals: dict[str, Any] = {
                "data": data,
                "config": user_config,
                "EvaluatorResult": EvaluatorResult,
                "re": __import__("re"),
                "json": __import__("json"),
                "math": __import__("math"),
            }

            try:
                with timeout_context(timeout_sec):
                    exec(self._compiled, exec_globals)
                    func = exec_globals.get(self._entrypoint)
                    if func is None or not callable(func):
                        raise ValueError(f"Entrypoint '{self._entrypoint}' not found")
                    result = func(data, user_config)
                    if not isinstance(result, EvaluatorResult):
                        raise TypeError(f"Must return EvaluatorResult, got {type(result).__name__}")
                    return result
            except TimeoutError as e:
                logger.warning(f"Custom evaluator '{name}' timeout: {e}")
                return self._handle_error(e)
            except Exception as e:
                logger.warning(f"Custom evaluator '{name}' error: {e}")
                return self._handle_error(e)

        def _handle_error(self, error: Exception) -> EvaluatorResult:
            """Handle errors based on on_error config."""
            fail_closed = self.config.on_error == "deny"
            return EvaluatorResult(
                matched=fail_closed,
                confidence=0.0,
                message=f"Custom evaluator error: {error}",
                metadata={"error": str(error), "error_type": type(error).__name__},
            )

    _CLASS_CACHE[cache_key] = DynamicEvaluator
    return DynamicEvaluator


def get_or_create_instance(
    name: str,
    code: str,
    config: dict[str, Any],
    description: str | None = None,
    entrypoint: str = "evaluate",
    timeout_ms: int = 5000,
    config_schema: dict[str, Any] | None = None,
) -> PluginEvaluator[Any]:
    """Get or create a cached evaluator instance.

    Args:
        name: Evaluator name
        code: Python code
        config: User config dict (will be wrapped in DynamicConfig)
        description: Optional description
        entrypoint: Function name
        timeout_ms: Timeout in ms
        config_schema: JSON Schema for config

    Returns:
        Cached or new evaluator instance
    """
    instance_key = f"{name}:{hash(code)}:{_config_hash(config)}"

    if instance_key in _INSTANCE_CACHE:
        return _INSTANCE_CACHE[instance_key]

    cls = create_dynamic_evaluator_class(
        name=name,
        code=code,
        description=description,
        entrypoint=entrypoint,
        timeout_ms=timeout_ms,
        config_schema=config_schema,
    )

    instance = cls(DynamicConfig(user_config=config, timeout_ms=timeout_ms))
    _INSTANCE_CACHE[instance_key] = instance
    return instance


def register_custom_evaluator(
    name: str,
    code: str,
    description: str | None = None,
    entrypoint: str = "evaluate",
    timeout_ms: int = 5000,
    config_schema: dict[str, Any] | None = None,
) -> type[PluginEvaluator[Any]]:
    """Create and register a custom evaluator in the plugin registry.

    This makes it available via get_plugin(name).

    Args:
        name: Unique evaluator name
        code: Python code
        description: Optional description
        entrypoint: Function name
        timeout_ms: Timeout in ms
        config_schema: JSON Schema

    Returns:
        The registered evaluator class
    """
    cls = create_dynamic_evaluator_class(
        name=name,
        code=code,
        description=description,
        entrypoint=entrypoint,
        timeout_ms=timeout_ms,
        config_schema=config_schema,
    )
    register_plugin(cls)
    return cls


def clear_caches() -> None:
    """Clear all caches. Useful for testing."""
    _CODE_CACHE.clear()
    _CLASS_CACHE.clear()
    _INSTANCE_CACHE.clear()
