"""Unit tests for Google ADK lazy imports."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def test_google_adk_init_all():
    import agent_control.integrations.google_adk as google_adk_module

    assert google_adk_module.__all__ == ["AgentControlPlugin"]


def test_google_adk_lazy_import_fails_without_dependency():
    import agent_control.integrations.google_adk as google_adk_module

    removed: dict[str, ModuleType] = {}
    for module_name in list(sys.modules):
        if module_name == "google" or module_name.startswith("google."):
            module = sys.modules.pop(module_name)
            if isinstance(module, ModuleType):
                removed[module_name] = module
    sys.modules.pop("agent_control.integrations.google_adk.plugin", None)

    try:
        with pytest.raises(RuntimeError, match="google-adk"):
            _ = google_adk_module.AgentControlPlugin
    finally:
        sys.modules.update(removed)


def test_google_adk_lazy_import_succeeds_with_mocked_modules():
    google_mod = ModuleType("google")
    adk_mod = ModuleType("google.adk")
    callback_context_mod = ModuleType("google.adk.agents.callback_context")
    models_mod = ModuleType("google.adk.models")
    plugins_mod = ModuleType("google.adk.plugins")
    tools_mod = ModuleType("google.adk.tools")
    tool_context_mod = ModuleType("google.adk.tools.tool_context")
    genai_mod = ModuleType("google.genai")
    types_mod = ModuleType("google.genai.types")

    plugins_mod.BasePlugin = type("BasePlugin", (), {"__init__": lambda self, name=None: None})
    callback_context_mod.CallbackContext = object
    models_mod.LlmRequest = object
    models_mod.LlmResponse = type("LlmResponse", (), {})
    tools_mod.BaseTool = object
    tool_context_mod.ToolContext = object
    types_mod.Content = MagicMock()
    types_mod.Part = MagicMock()
    genai_mod.types = types_mod

    with patch.dict(
        sys.modules,
        {
            "google": google_mod,
            "google.adk": adk_mod,
            "google.adk.agents.callback_context": callback_context_mod,
            "google.adk.models": models_mod,
            "google.adk.plugins": plugins_mod,
            "google.adk.tools": tools_mod,
            "google.adk.tools.tool_context": tool_context_mod,
            "google.genai": genai_mod,
            "google.genai.types": types_mod,
        },
    ):
        sys.modules.pop("agent_control.integrations.google_adk.plugin", None)
        module = importlib.import_module("agent_control.integrations.google_adk")
        assert module.AgentControlPlugin.__name__ == "AgentControlPlugin"
