"""Dynamic evaluator factory for custom evaluators from database.

Creates PluginEvaluator subclasses from code strings with namespace caching.

Async-First:
    Custom evaluators MUST define an async evaluate function:
        async def evaluate(data, config) -> EvaluatorResult

    Sync functions are rejected at registration time.

Namespace Persistence:
    Custom evaluator code is executed once per evaluator. The resulting namespace
    (including any module-level variables, caches, or compiled patterns) persists
    across evaluate() calls. This allows evaluators to maintain state for performance.

    Example:
        ```python
        import re2
        _pattern_cache = {}

        def _get_pattern(p):
            if p not in _pattern_cache:
                _pattern_cache[p] = re2.compile(p)
            return _pattern_cache[p]

        async def evaluate(data, config):
            pattern = _get_pattern(config["pattern"])
            ...
        ```

    WARNING: Module-level state persists for the lifetime of the evaluator.
    Be careful with memory usage - don't cache unbounded data.

LRU Eviction:
    Namespaces are cached with LRU eviction. Configure max cached evaluators via:
    - Environment variable: CUSTOM_EVALUATOR_CACHE_SIZE (default: 100)
"""

import asyncio
import inspect
import logging
import os
from collections import OrderedDict
from types import CodeType
from typing import Any

from agent_control_models import EvaluatorResult, PluginEvaluator, PluginMetadata, register_plugin
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_CACHE_SIZE = 100
CACHE_SIZE = int(os.environ.get("CUSTOM_EVALUATOR_CACHE_SIZE", DEFAULT_CACHE_SIZE))

# Cache for compiled code objects
_CODE_CACHE: dict[str, CodeType] = {}

# Cache for dynamically created plugin classes
_CLASS_CACHE: dict[str, type[PluginEvaluator[Any]]] = {}

# LRU cache for executed namespaces (evaluator name -> exec_globals)
# This preserves module-level state across evaluate() calls
_NAMESPACE_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()

# Cache for plugin instances (keyed by name + config hash)
_INSTANCE_CACHE: dict[str, PluginEvaluator[Any]] = {}


class DynamicConfig(BaseModel):
    """Config model for dynamic evaluators - wraps user_config."""

    user_config: dict[str, Any] = {}
    timeout_ms: int = 5000
    on_error: str = "deny"


def _config_hash(config: dict[str, Any]) -> str:
    """Create a hashable key from config dict."""
    import json

    return json.dumps(config, sort_keys=True, default=str)


def _get_or_create_namespace(
    name: str,
    code: str,
    compiled: CodeType,
) -> dict[str, Any]:
    """Get or create a cached namespace for an evaluator.

    The namespace contains the executed code's globals, preserving any
    module-level state (caches, compiled patterns, etc.) across calls.

    Uses LRU eviction when cache is full.
    """
    cache_key = f"{name}:{hash(code)}"

    # Check if already cached
    if cache_key in _NAMESPACE_CACHE:
        # Move to end (most recently used)
        _NAMESPACE_CACHE.move_to_end(cache_key)
        return _NAMESPACE_CACHE[cache_key]

    # Create new namespace with builtins
    namespace: dict[str, Any] = {
        "__builtins__": __builtins__,
        "EvaluatorResult": EvaluatorResult,
        "re": __import__("re"),
        "json": __import__("json"),
        "math": __import__("math"),
    }

    # Execute code once to populate namespace
    exec(compiled, namespace)

    # Evict oldest if cache is full
    while len(_NAMESPACE_CACHE) >= CACHE_SIZE:
        evicted_key, _ = _NAMESPACE_CACHE.popitem(last=False)
        logger.debug(f"Evicted namespace from cache: {evicted_key}")

    # Cache the namespace
    _NAMESPACE_CACHE[cache_key] = namespace
    logger.debug(f"Cached namespace for evaluator: {name} (cache size: {len(_NAMESPACE_CACHE)})")

    return namespace


def invalidate_namespace(name: str) -> None:
    """Invalidate cached namespace for an evaluator.

    Call this when evaluator code is updated.
    """
    # Remove all cache entries for this evaluator name
    keys_to_remove = [k for k in _NAMESPACE_CACHE if k.startswith(f"{name}:")]
    for key in keys_to_remove:
        del _NAMESPACE_CACHE[key]
        logger.debug(f"Invalidated namespace: {key}")


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

        async def evaluate(self, data: Any) -> EvaluatorResult:
            """Execute custom async code to evaluate data.

            The code's namespace is cached, so module-level state persists.
            Uses asyncio.wait_for() for timeout.
            """
            timeout_sec = self.config.timeout_ms / 1000.0
            user_config = self.config.user_config

            try:
                # Get cached namespace (or create and cache it)
                namespace = _get_or_create_namespace(name, code, self._compiled)

                # Get the entrypoint function from cached namespace
                func = namespace.get(self._entrypoint)
                if func is None or not callable(func):
                    raise ValueError(f"Entrypoint '{self._entrypoint}' not found")

                if not inspect.iscoroutinefunction(func):
                    raise TypeError(
                        f"Entrypoint '{self._entrypoint}' must be async. "
                        f"Use 'async def {self._entrypoint}(data, config)'"
                    )

                # Call async function with timeout
                coro = func(data, user_config)
                result = await asyncio.wait_for(coro, timeout=timeout_sec)

                if not isinstance(result, EvaluatorResult):
                    raise TypeError(f"Must return EvaluatorResult, got {type(result).__name__}")
                return result
            except asyncio.TimeoutError:
                logger.warning(f"Custom evaluator '{name}' timeout after {timeout_sec}s")
                return self._handle_error(TimeoutError(f"Timeout after {timeout_sec}s"))
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
    _NAMESPACE_CACHE.clear()
    _INSTANCE_CACHE.clear()


def get_cache_stats() -> dict[str, int]:
    """Get cache statistics for monitoring."""
    return {
        "code_cache_size": len(_CODE_CACHE),
        "class_cache_size": len(_CLASS_CACHE),
        "namespace_cache_size": len(_NAMESPACE_CACHE),
        "namespace_cache_limit": CACHE_SIZE,
        "instance_cache_size": len(_INSTANCE_CACHE),
    }
