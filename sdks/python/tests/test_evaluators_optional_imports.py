"""Coverage for the optional galileo import fallbacks in agent_control.evaluators.

The galileo extras are normally installed in the dev environment, so the
``except ImportError`` branches in ``agent_control/evaluators/__init__.py``
never fire under regular tests. This module forces those failures by hiding
the relevant modules in ``sys.modules`` and reloading the package.
"""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import sys

import pytest


def _module_available(name: str) -> bool:
    """Return whether ``name`` resolves without raising for missing parents."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        # ``find_spec`` raises ModuleNotFoundError (a subclass of ImportError)
        # when a *parent* package is missing, instead of returning None. Treat
        # that as "not installed."
        return False


_GALILEO_INSTALLED = _module_available("agent_control_evaluator_galileo.luna")


def _reload_evaluators_with_blocked(prefix: str) -> object:
    """Reload ``agent_control.evaluators`` while ``prefix.*`` imports fail.

    Returns the freshly loaded module so callers can inspect ``__all__``.
    Restores the original ``builtins.__import__`` and ``sys.modules`` entries
    on the way out.
    """
    original_import = builtins.__import__

    def fail_for_prefix(name: str, *args: object, **kwargs: object) -> object:
        if name == prefix or name.startswith(f"{prefix}."):
            raise ImportError(f"forced failure for {name}")
        return original_import(name, *args, **kwargs)  # type: ignore[arg-type]

    # Drop any cached entries so the patched import is consulted.
    blocked_modules = [m for m in list(sys.modules) if m == prefix or m.startswith(f"{prefix}.")]
    saved_modules = {m: sys.modules.pop(m) for m in blocked_modules}
    saved_evaluators = sys.modules.pop("agent_control.evaluators", None)

    builtins.__import__ = fail_for_prefix
    try:
        import agent_control.evaluators as reloaded

        reloaded = importlib.reload(reloaded)
        return reloaded
    finally:
        builtins.__import__ = original_import
        # Restore the cached modules so other tests keep their state.
        for name, module in saved_modules.items():
            sys.modules[name] = module
        if saved_evaluators is not None:
            sys.modules["agent_control.evaluators"] = saved_evaluators


def test_module_loads_when_galileo_luna_is_unavailable():
    """Hiding ``agent_control_evaluator_galileo.luna`` exercises its except branch."""
    reloaded = _reload_evaluators_with_blocked("agent_control_evaluator_galileo.luna")

    # Core names are always present.
    assert "Evaluator" in reloaded.__all__
    # Luna1 names are NOT present because the import failed.
    assert "LunaEvaluator" not in reloaded.__all__
    assert "GalileoLunaClient" not in reloaded.__all__


def test_module_loads_when_galileo_package_is_unavailable():
    """Hiding the whole package exercises the ImportError fallback."""
    reloaded = _reload_evaluators_with_blocked("agent_control_evaluator_galileo")

    assert "Evaluator" in reloaded.__all__
    # The optional luna names are absent.
    for absent in (
        "LunaEvaluator",
        "GalileoLunaClient",
        "LUNA_AVAILABLE",
    ):
        assert absent not in reloaded.__all__


@pytest.mark.skipif(
    not _GALILEO_INSTALLED,
    reason="agent-control-evaluator-galileo extras not installed in this environment",
)
def test_module_loads_galileo_optional_imports_when_available():
    """Sanity check: with galileo installed, the optional names ARE exposed.

    Reloading without patching __import__ runs both success branches.
    """
    saved = sys.modules.pop("agent_control.evaluators", None)
    try:
        import agent_control.evaluators as reloaded

        reloaded = importlib.reload(reloaded)
        # Sanity: at least one luna name should reappear.
        assert "LunaEvaluator" in reloaded.__all__
    finally:
        if saved is not None:
            sys.modules["agent_control.evaluators"] = saved
