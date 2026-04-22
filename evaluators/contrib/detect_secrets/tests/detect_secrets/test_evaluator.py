from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

import pytest
from detect_secrets_async import (
    RuntimeScanError,
    ScanFailureCode,
    ScanFinding,
    ScanResult,
    get_runtime_info,
)

from agent_control_evaluator_detect_secrets.detect_secrets import (
    DetectSecretsEvaluator,
    DetectSecretsEvaluatorConfig,
)
from agent_control_evaluator_detect_secrets.detect_secrets.evaluator import FAILURE_MESSAGES
from agent_control_evaluator_detect_secrets.detect_secrets.normalization import (
    LineLocation,
    NormalizedPayload,
    normalize_payload,
)


@pytest.mark.asyncio
async def test_none_input_returns_no_match() -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    result = await evaluator.evaluate(None)

    assert result.matched is False
    assert result.error is None
    assert result.metadata == {
        "findings_count": 0,
        "findings": [],
        "normalized_payload_type": "none",
        "detect_secrets_version": get_runtime_info().detect_secrets_version,
    }


@pytest.mark.asyncio
async def test_string_secret_matches() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate("github_token = 'ghp_123456789012345678901234567890123456'")

    assert result.matched is True
    assert result.confidence == 1.0
    assert result.metadata is not None
    assert result.metadata["findings_count"] == 1
    assert result.metadata["normalized_payload_type"] == "str"
    assert result.metadata["findings"] == [{"type": "GitHub Token", "line_number": 1}]


@pytest.mark.asyncio
async def test_string_without_findings_does_not_match() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate("safe content only")

    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["findings_count"] == 0


@pytest.mark.asyncio
async def test_dict_payload_maps_findings_to_json_pointer() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        {
            "response": {
                "headers": {
                    "authorization": "ghp_123456789012345678901234567890123456",
                }
            }
        }
    )

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert result.metadata["findings"] == [
        {
            "type": "GitHub Token",
            "json_pointer": "/response/headers/authorization",
        }
    ]


@pytest.mark.asyncio
async def test_dict_key_with_container_value_maps_findings_to_json_pointer() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        {
            "outer": {
                "ghp_123456789012345678901234567890123456": {
                    "nested": "safe",
                }
            }
        }
    )

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert result.metadata["findings"] == [
        {
            "type": "GitHub Token",
            "json_pointer": "/outer",
        }
    ]


@pytest.mark.asyncio
async def test_dict_key_with_scalar_value_omits_json_pointer() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        {
            "ghp_123456789012345678901234567890123456": "safe",
        }
    )

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert result.metadata["findings"] == [
        {
            "type": "GitHub Token",
        }
    ]


@pytest.mark.asyncio
async def test_list_payload_maps_findings_to_json_pointer() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        [
            {"kind": "safe"},
            {"token": "ghp_123456789012345678901234567890123456"},
        ]
    )

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "list"
    assert result.metadata["findings"] == [
        {
            "type": "GitHub Token",
            "json_pointer": "/1/token",
        }
    ]


@pytest.mark.asyncio
async def test_primitive_payload_is_normalized_and_omits_line_numbers() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(True)

    assert result.matched is False
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "primitive"
    assert result.metadata["findings"] == []


@pytest.mark.asyncio
async def test_non_json_serializable_payload_routes_through_on_error_allow() -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    result = await evaluator.evaluate({"bad": {1, 2, 3}})

    assert result.matched is False
    assert result.confidence == 0.0
    assert result.error == "detect-secrets evaluator failure: normalization_error"
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "normalization_error"


@pytest.mark.asyncio
async def test_oversized_payload_routes_through_on_error_allow() -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(max_bytes=8))

    result = await evaluator.evaluate("0123456789")

    assert result.matched is False
    assert result.error == "detect-secrets evaluator failure: payload_too_large"
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "payload_too_large"
    assert result.metadata["normalized_payload_type"] == "str"


@pytest.mark.asyncio
async def test_on_error_deny_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        async def scan(self, request: Any) -> Any:
            raise RuntimeScanError(ScanFailureCode.WORKER_TIMEOUT)

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda: FakeRuntime(),
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(on_error="deny"))
    result = await evaluator.evaluate("hello")

    assert result.matched is True
    assert result.confidence == 0.0
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "worker_timeout"
    assert result.metadata["fallback_action"] == "deny"


@pytest.mark.asyncio
async def test_explicit_runtime_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        async def scan(self, request: Any) -> Any:
            raise RuntimeScanError(ScanFailureCode.WORKER_CRASH, "raw runtime detail")

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda: FakeRuntime(),
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())
    result = await evaluator.evaluate("hello")

    assert result.matched is False
    assert result.error == "detect-secrets evaluator failure: worker_crash"
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "worker_crash"
    assert result.message is not None
    assert FAILURE_MESSAGES["worker_crash"] in result.message


@pytest.mark.asyncio
async def test_structured_key_probes_are_batched(monkeypatch: pytest.MonkeyPatch) -> None:
    normalized = NormalizedPayload(
        payload_type="dict",
        text='{"ignored": true}',
        line_locations_by_line={
            1: LineLocation(
                json_pointer="/safe-one",
                parent_pointer="/parent-one",
                key_probe_text='"probe-one": null',
            ),
            2: LineLocation(
                json_pointer="/safe-two",
                parent_pointer="/parent-two",
                key_probe_text='"probe-two": null',
            ),
        },
    )

    class FakeRuntime:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def scan(self, request: Any) -> ScanResult:
            self.requests.append(request)
            if len(self.requests) == 1:
                return ScanResult(
                    findings=(
                        ScanFinding(type="GitHub Token", line_number=1),
                        ScanFinding(type="GitHub Token", line_number=2),
                    ),
                    detect_secrets_version="1.5.0",
                )
            return ScanResult(
                findings=(ScanFinding(type="GitHub Token", line_number=1),),
                detect_secrets_version="1.5.0",
            )

    fake_runtime = FakeRuntime()
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.normalize_payload",
        lambda data: normalized,
    )
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda: fake_runtime,
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())
    result = await evaluator.evaluate({"ignored": "ignored"})

    assert result.matched is True
    assert result.metadata is not None
    assert fake_runtime.requests[1].content == '"probe-one": null\n"probe-two": null'
    assert len(fake_runtime.requests) == 2
    assert result.metadata["findings"] == [
        {"type": "GitHub Token", "json_pointer": "/parent-one"},
        {"type": "GitHub Token", "json_pointer": "/safe-two"},
    ]


@pytest.mark.asyncio
async def test_initial_scan_uses_remaining_timeout_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRuntime:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def scan(self, request: Any) -> ScanResult:
            self.requests.append(request)
            return ScanResult(findings=(), detect_secrets_version="1.5.0")

    fake_runtime = FakeRuntime()
    monotonic_values = [100.0, 100.04]

    def fake_monotonic() -> float:
        if monotonic_values:
            return monotonic_values.pop(0)
        return 100.04

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda: fake_runtime,
    )
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.time.monotonic",
        fake_monotonic,
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(timeout_ms=50))
    result = await evaluator.evaluate("safe content only")

    assert result.matched is False
    assert len(fake_runtime.requests) == 1
    assert 1 <= fake_runtime.requests[0].timeout_ms < 50


@pytest.mark.asyncio
async def test_exclude_lines_regex_suppresses_findings() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(
            enabled_plugins=["GitHubTokenDetector"],
            exclude_lines_regex=["ghp_[A-Za-z0-9]{36}"],
        )
    )

    result = await evaluator.evaluate("github_token = 'ghp_123456789012345678901234567890123456'")

    assert result.matched is False
    assert result.metadata is not None
    assert result.metadata["findings"] == []


@pytest.mark.asyncio
async def test_exclude_lines_preserves_line_numbers_for_plain_strings() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(
            enabled_plugins=["GitHubTokenDetector"],
            exclude_lines_regex=["^ignore me$"],
        )
    )

    content = "\n".join(
        [
            "line 1",
            "ignore me",
            "github_token = 'ghp_123456789012345678901234567890123456'",
        ]
    )
    result = await evaluator.evaluate(content)

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["findings"] == [{"type": "GitHub Token", "line_number": 3}]


def test_invalid_regex_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid RE2 pattern"):
        DetectSecretsEvaluatorConfig(exclude_lines_regex=["("])


def test_unknown_plugin_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown detect-secrets plugin"):
        DetectSecretsEvaluatorConfig(enabled_plugins=["NoSuchPlugin"])


@pytest.mark.asyncio
async def test_omitted_enabled_plugins_uses_upstream_defaults() -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())
    sample = "api_key = 'abcdefghijklmnopqrstuvwxyz0123456789ABCDE='"

    result = await evaluator.evaluate(sample)

    assert result.matched is True
    assert result.metadata is not None
    finding_types = {finding["type"] for finding in result.metadata["findings"]}
    assert "Secret Keyword" in finding_types


def test_normalize_payload_renders_expected_json_pointer_lines() -> None:
    normalized = normalize_payload({"outer": [{"inner": "secret"}]})

    assert normalized.payload_type == "dict"
    assert normalized.line_locations_by_line[4].json_pointer == "/outer/0/inner"


def test_entry_point_is_registered() -> None:
    evaluator_entry_points = {
        entry_point.name: entry_point.value
        for entry_point in entry_points(group="agent_control.evaluators")
    }

    assert evaluator_entry_points["yelp.detect_secrets"] == (
        "agent_control_evaluator_detect_secrets.detect_secrets:DetectSecretsEvaluator"
    )
