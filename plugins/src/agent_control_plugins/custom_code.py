"""Custom code plugin for executing user-provided Python code."""

import logging
import signal
from contextlib import contextmanager
from types import CodeType
from typing import Any, Generator

from agent_control_models import (
    CustomCodeConfig,
    EvaluatorResult,
    PluginEvaluator,
    PluginMetadata,
    register_plugin,
)

logger = logging.getLogger(__name__)


@contextmanager
def timeout_context(seconds: float) -> Generator[None, None, None]:
    """Context manager for execution timeout using SIGALRM.

    Note: Only works on Unix systems. On Windows, timeout is not enforced.

    Args:
        seconds: Maximum execution time in seconds

    Raises:
        TimeoutError: If execution exceeds the timeout
    """
    if not hasattr(signal, "SIGALRM"):
        # Windows - no timeout support
        logger.warning("Timeout not supported on this platform")
        yield
        return

    def handler(signum: int, frame: Any) -> None:
        raise TimeoutError(f"Execution exceeded {seconds}s timeout")

    # Set up the signal handler
    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)

    try:
        yield
    finally:
        # Restore previous handler and cancel timer
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


@register_plugin
class CustomCodePlugin(PluginEvaluator[CustomCodeConfig]):
    """Execute user-provided Python code as an evaluator.

    The code must define a function matching the entrypoint name (default: "evaluate")
    that takes a single `data` argument and returns an EvaluatorResult.

    **Security Note**: For MVP, code runs with full Python permissions.
    Only use with trusted code sources.

    Example config:
        {
            "code": '''
def evaluate(data):
    if "secret" in str(data).lower():
        return EvaluatorResult(matched=True, confidence=1.0, message="Found secret")
    return EvaluatorResult(matched=False, confidence=1.0, message="Clean")
            ''',
            "entrypoint": "evaluate",
            "timeout_ms": 5000
        }
    """

    metadata = PluginMetadata(
        name="custom-code",
        version="1.0.0",
        description="Execute user-provided Python code (trusted sources only)",
        timeout_ms=5000,
    )
    config_model = CustomCodeConfig

    _compiled: CodeType | None = None

    def __init__(self, config: CustomCodeConfig) -> None:
        super().__init__(config)
        # Pre-compile the code to catch syntax errors early
        self._compiled = compile(
            config.code,
            filename="<custom-code>",
            mode="exec",
        )

    def evaluate(self, data: Any) -> EvaluatorResult:
        """Execute custom code to evaluate data.

        Args:
            data: Data to evaluate

        Returns:
            EvaluatorResult from the custom function
        """
        timeout_sec = self.config.timeout_ms / 1000.0

        # Set up execution environment with useful imports
        exec_globals: dict[str, Any] = {
            "data": data,
            "EvaluatorResult": EvaluatorResult,
            # Useful standard library modules
            "re": __import__("re"),
            "json": __import__("json"),
            "math": __import__("math"),
        }

        try:
            with timeout_context(timeout_sec):
                # Execute the code to define the function
                exec(self._compiled, exec_globals)

                # Get and call the entrypoint function
                func = exec_globals.get(self.config.entrypoint)
                if func is None:
                    raise ValueError(
                        f"Entrypoint function '{self.config.entrypoint}' not defined in code"
                    )
                if not callable(func):
                    raise ValueError(
                        f"Entrypoint '{self.config.entrypoint}' is not callable"
                    )

                result = func(data)

                # Validate return type
                if not isinstance(result, EvaluatorResult):
                    raise TypeError(
                        f"Function must return EvaluatorResult, got {type(result).__name__}"
                    )

                return result

        except TimeoutError as e:
            logger.warning(f"Custom code timeout: {e}")
            return self._handle_error(e)
        except Exception as e:
            logger.warning(f"Custom code error: {e}")
            return self._handle_error(e)

    def _handle_error(self, error: Exception) -> EvaluatorResult:
        """Handle errors based on on_error config."""
        fail_closed = self.config.on_error == "deny"

        return EvaluatorResult(
            matched=fail_closed,
            confidence=0.0,
            message=f"Custom code error: {error}",
            metadata={
                "error": str(error),
                "error_type": type(error).__name__,
                "on_error": self.config.on_error,
            },
        )
