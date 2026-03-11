"""Unit tests for Google ADK extractor helpers."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest


class MockPart:
    def __init__(
        self,
        text: str | None = None,
        function_call: object | None = None,
        function_response: object | None = None,
    ):
        self.text = text
        self.function_call = function_call
        self.function_response = function_response


class MockContent:
    def __init__(self, role: str = "user", parts: list[object] | None = None):
        self.role = role
        self.parts = parts or []


class MockLlmResponse:
    def __init__(self, content: object):
        self.content = content


class MockStructuredValue:
    def __init__(self, payload: object):
        self.payload = payload

    def model_dump(self, mode: str = "json") -> object:
        assert mode == "json"
        return self.payload


def _install_google_modules() -> None:
    google_mod = ModuleType("google")
    adk_mod = ModuleType("google.adk")
    models_mod = ModuleType("google.adk.models")
    genai_mod = ModuleType("google.genai")
    types_mod = ModuleType("google.genai.types")

    models_mod.LlmResponse = MockLlmResponse
    types_mod.Content = MockContent
    types_mod.Part = MockPart
    genai_mod.types = types_mod

    sys.modules["google"] = google_mod
    sys.modules["google.adk"] = adk_mod
    sys.modules["google.adk.models"] = models_mod
    sys.modules["google.genai"] = genai_mod
    sys.modules["google.genai.types"] = types_mod


@pytest.fixture
def extractor_module():
    _install_google_modules()
    module_name = "agent_control.integrations.google_adk._extractors"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    yield module
    sys.modules.pop(module_name, None)


def test_extract_request_text(extractor_module):
    request = SimpleNamespace(
        contents=[SimpleNamespace(parts=[MockPart("hello"), MockPart("world")])]
    )

    assert extractor_module.extract_request_text(request) == "hello\nworld"


def test_extract_response_text(extractor_module):
    response = MockLlmResponse(MockContent(role="model", parts=[MockPart("done")]))

    assert extractor_module.extract_response_text(response) == "done"


def test_extract_response_text_serializes_structured_parts(extractor_module):
    response = MockLlmResponse(
        MockContent(
            role="model",
            parts=[
                MockPart(
                    function_call=MockStructuredValue(
                        {"name": "get_weather", "args": {"city": "Rome"}}
                    )
                )
            ],
        )
    )

    assert (
        extractor_module.extract_response_text(response)
        == '{"args": {"city": "Rome"}, "name": "get_weather"}'
    )


def test_resolve_agent_name_prefers_nested_agent(extractor_module):
    context = SimpleNamespace(
        agent=SimpleNamespace(name="researcher"),
        agent_name="fallback",
    )

    assert extractor_module.resolve_agent_name(context) == "researcher"


def test_resolve_tool_name(extractor_module):
    tool = SimpleNamespace(name="search_docs")

    assert extractor_module.resolve_tool_name(tool) == "search_docs"


def test_resolve_tool_agent_name_prefers_callback_context(extractor_module):
    tool_context = SimpleNamespace(
        callback_context=SimpleNamespace(
            agent=SimpleNamespace(name="writer"),
            agent_name="fallback",
        ),
        agent_name="tool-fallback",
    )

    assert extractor_module.resolve_tool_agent_name(tool_context) == "writer"


def test_build_blocked_llm_response(extractor_module):
    response = extractor_module.build_blocked_llm_response("blocked")

    assert isinstance(response, MockLlmResponse)
    assert response.content.role == "model"
    assert response.content.parts[0].text == "blocked"


def test_build_blocked_tool_response(extractor_module):
    payload = extractor_module.build_blocked_tool_response("denied")

    assert payload == {"status": "blocked", "message": "denied"}
