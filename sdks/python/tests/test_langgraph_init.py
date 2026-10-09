"""Unit tests for LangGraph integration __init__.py."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest


def test_langgraph_init_exports():
    """Test that __init__.py exports the expected factory."""
    from agent_control.integrations.langgraph import create_controlled_tool_node

    assert callable(create_controlled_tool_node)


def test_langgraph_init_all():
    """Test that __all__ contains expected exports."""
    import agent_control.integrations.langgraph as langgraph_module

    assert hasattr(langgraph_module, "__all__")
    assert langgraph_module.__all__ == ["create_controlled_tool_node"]


def test_lazy_import_create_controlled_tool_node():
    """Test lazy import of create_controlled_tool_node via __getattr__."""
    from agent_control.integrations.langgraph import create_controlled_tool_node

    assert create_controlled_tool_node.__name__ == "create_controlled_tool_node"


def test_missing_langgraph_dependency_raises_runtime_error():
    """Test that missing optional deps surface a helpful install message."""
    import agent_control.integrations.langgraph as langgraph_module

    sys.modules.pop("agent_control.integrations.langgraph.tool_node", None)
    real_import = __import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name.startswith("langgraph") or name.startswith("langchain_core"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(RuntimeError, match=r"agent-control-sdk\[langgraph\]"):
            langgraph_module.__getattr__("create_controlled_tool_node")


def test_invalid_attribute_raises_error():
    """Test that accessing invalid attribute raises AttributeError."""
    import agent_control.integrations.langgraph as langgraph_module

    with pytest.raises(AttributeError, match="has no attribute 'InvalidFactory'"):
        _ = langgraph_module.InvalidFactory  # type: ignore[attr-defined]
