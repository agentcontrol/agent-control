"""Unit tests for LangChain integration __init__.py."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def test_langchain_init_exports() -> None:
    """Test that __init__.py exports the expected middleware."""
    from agent_control.integrations.langchain import AgentControlMiddleware

    assert isinstance(AgentControlMiddleware, type)


def test_langchain_init_all() -> None:
    """Test that __all__ contains expected exports."""
    import agent_control.integrations.langchain as langchain_module

    assert hasattr(langchain_module, "__all__")
    assert langchain_module.__all__ == ["AgentControlMiddleware"]


def test_lazy_import_agent_control_middleware() -> None:
    """Test lazy import of AgentControlMiddleware via __getattr__."""
    from agent_control.integrations.langchain import AgentControlMiddleware

    assert AgentControlMiddleware.__name__ == "AgentControlMiddleware"


def test_missing_langchain_dependency_raises_runtime_error() -> None:
    """Test that missing optional deps surface a helpful install message."""
    import agent_control.integrations.langchain as langchain_module

    sys.modules.pop("agent_control.integrations.langchain.middleware", None)
    real_import = __import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name.startswith("langchain") or name.startswith("langchain_core"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match=r"agent-control-sdk\[langchain\]"):
            langchain_module.__getattr__("AgentControlMiddleware")


def test_invalid_attribute_raises_error() -> None:
    """Test that accessing invalid attribute raises AttributeError."""
    import agent_control.integrations.langchain as langchain_module

    with pytest.raises(AttributeError, match="has no attribute 'InvalidMiddleware'"):
        _ = langchain_module.InvalidMiddleware  # type: ignore[attr-defined]
