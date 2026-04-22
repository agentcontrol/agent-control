from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

import pytest
from detect_secrets_async import (
    RuntimeConfig,
    RuntimeScanError,
    ScanFailureCode,
    ScanResult,
    get_runtime_info,
)

from agent_control_evaluator_detect_secrets.detect_secrets import (
    DetectSecretsEvaluator,
    DetectSecretsEvaluatorConfig,
)
from agent_control_evaluator_detect_secrets.detect_secrets.evaluator import FAILURE_MESSAGES
from agent_control_evaluator_detect_secrets.detect_secrets.normalization import normalize_payload


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
async def test_none_input_short_circuits_runtime_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime_info",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(on_error="deny"))
    result = await evaluator.evaluate(None)

    assert result.matched is False
    assert result.error is None
    assert result.metadata == {
        "findings_count": 0,
        "findings": [],
        "normalized_payload_type": "none",
        "detect_secrets_version": "unknown",
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
async def test_root_dict_key_with_container_value_maps_findings_to_root_pointer() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        {
            "ghp_123456789012345678901234567890123456": {
                "nested": "safe",
            }
        }
    )

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert result.metadata["findings"] == [
        {
            "type": "GitHub Token",
            "json_pointer": "",
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
            "json_pointer": "",
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
async def test_secret_bearing_object_keys_do_not_leak_through_json_pointer() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    key_secret = "ghp_123456789012345678901234567890123456"
    value_secret = "ghp_abcdefabcdefabcdefabcdefabcdefabcdef"
    result = await evaluator.evaluate({key_secret: {"nested": value_secret}})

    assert result.matched is True
    assert result.metadata is not None
    assert all(finding.get("json_pointer", "") == "" for finding in result.metadata["findings"])
    assert all(
        key_secret not in finding.get("json_pointer", "") for finding in result.metadata["findings"]
    )


@pytest.mark.asyncio
async def test_nested_findings_under_secret_like_key_truncate_to_safe_ancestor() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    key_secret = "ghp_123456789012345678901234567890123456"
    value_secret = "ghp_abcdefabcdefabcdefabcdefabcdefabcdef"
    result = await evaluator.evaluate({"outer": {key_secret: {"nested": value_secret}}})

    assert result.matched is True
    assert result.metadata is not None
    assert all(
        finding.get("json_pointer", "") == "/outer" for finding in result.metadata["findings"]
    )
    assert all(
        key_secret not in finding.get("json_pointer", "") for finding in result.metadata["findings"]
    )


@pytest.mark.asyncio
async def test_tuple_payload_maps_findings_like_a_list() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        (
            {"token": "ghp_123456789012345678901234567890123456"},
            {"kind": "safe"},
        )
    )

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "list"
    assert result.metadata["findings"] == [
        {
            "type": "GitHub Token",
            "json_pointer": "/0/token",
        }
    ]


@pytest.mark.asyncio
async def test_mixed_key_types_still_normalize_and_scan() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        {
            1: "ghp_123456789012345678901234567890123456",
            "kind": "safe",
        }
    )

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert result.metadata["findings"] == [
        {
            "type": "GitHub Token",
            "json_pointer": "/1",
        }
    ]


@pytest.mark.asyncio
async def test_colliding_normalized_keys_route_through_normalization_error() -> None:
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    result = await evaluator.evaluate(
        {
            1: "ghp_123456789012345678901234567890123456",
            "1": "safe",
        }
    )

    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "normalization_error"
    assert result.metadata["fallback_action"] == "allow"


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
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "normalization_error"
    assert result.metadata["fallback_action"] == "allow"


@pytest.mark.asyncio
async def test_recursive_payload_routes_through_normalization_error() -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())
    payload: dict[str, Any] = {}
    payload["self"] = payload

    result = await evaluator.evaluate(payload)

    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "normalization_error"
    assert result.metadata["fallback_action"] == "allow"


@pytest.mark.asyncio
async def test_oversized_payload_routes_through_on_error_allow() -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(max_bytes=8))

    result = await evaluator.evaluate("0123456789")

    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "payload_too_large"
    assert result.metadata["normalized_payload_type"] == "str"
    assert result.metadata["fallback_action"] == "allow"


@pytest.mark.asyncio
async def test_exhausted_timeout_budget_short_circuits_before_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_values = [100.0, 100.02]

    def fake_monotonic() -> float:
        if monotonic_values:
            return monotonic_values.pop(0)
        return 100.02

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.time.monotonic",
        fake_monotonic,
    )
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda config=None: pytest.fail("runtime should not be invoked"),
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(timeout_ms=10))
    result = await evaluator.evaluate("safe content only")

    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "queue_timeout"
    assert result.metadata["fallback_action"] == "allow"


@pytest.mark.asyncio
async def test_on_error_deny_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        async def scan(self, request: Any) -> Any:
            raise RuntimeScanError(ScanFailureCode.WORKER_TIMEOUT)

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda config=None: FakeRuntime(),
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
        lambda config=None: FakeRuntime(),
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())
    result = await evaluator.evaluate("hello")

    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "worker_crash"
    assert result.metadata["fallback_action"] == "allow"
    assert result.message is not None
    assert FAILURE_MESSAGES["worker_crash"] in result.message


@pytest.mark.asyncio
async def test_structured_same_line_findings_map_to_field_pointer_without_probing() -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    result = await evaluator.evaluate({"secret": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="})

    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert all(finding.get("json_pointer") == "/secret" for finding in result.metadata["findings"])
    assert {"type": "Secret Keyword", "json_pointer": "/secret"} in result.metadata["findings"]


@pytest.mark.asyncio
async def test_preconfigured_runtime_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        async def scan(self, request: Any) -> ScanResult:
            return ScanResult(findings=(), detect_secrets_version="1.5.0")

    runtime_config = RuntimeConfig(pool_size=2, max_queue_depth=6, max_requests_per_worker=40)
    runtime_info = get_runtime_info().model_copy(update={"configured_runtime": runtime_config})
    runtime_calls: list[RuntimeConfig | None] = []

    def fake_get_runtime(config: RuntimeConfig | None = None) -> FakeRuntime:
        runtime_calls.append(config)
        return FakeRuntime()

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime_info",
        lambda: runtime_info,
    )
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        fake_get_runtime,
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())
    result = await evaluator.evaluate("safe content only")

    assert result.matched is False
    assert runtime_calls == [runtime_config]


@pytest.mark.asyncio
async def test_unexpected_runtime_errors_honor_on_error_deny(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda config=None: (_ for _ in ()).throw(ValueError("boom")),
    )

    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(on_error="deny"))
    result = await evaluator.evaluate("safe content only")

    assert result.matched is True
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "runtime_error"
    assert result.metadata["fallback_action"] == "deny"


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
        lambda config=None: fake_runtime,
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


def test_blank_regex_is_rejected() -> None:
    with pytest.raises(ValueError, match="exclude_lines_regex entries must be non-empty"):
        DetectSecretsEvaluatorConfig(exclude_lines_regex=[""])


def test_unknown_plugin_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown detect-secrets plugin"):
        DetectSecretsEvaluatorConfig(enabled_plugins=["NoSuchPlugin"])


def test_plugin_validation_runtime_failures_are_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.config.get_runtime_info",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(
        ValueError,
        match="Unable to validate detect-secrets plugins because runtime introspection failed",
    ):
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])


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


@pytest.mark.parametrize(
    ("key_name", "expected"),
    [
        ("github_token_key_name", True),
        ("MyVeryLongFunctionName", False),
        ("api_key_v2", False),
        ("github_pat_11ABCDEFG1234567890123", True),
        ("0", False),
    ],
)
def test_key_name_is_secret_like_heuristic(key_name: str, expected: bool) -> None:
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    assert evaluator._key_name_is_secret_like(key_name) is expected


def test_entry_point_is_registered() -> None:
    evaluator_entry_points = {
        entry_point.name: entry_point.value
        for entry_point in entry_points(group="agent_control.evaluators")
    }

    assert evaluator_entry_points["yelp.detect_secrets"] == (
        "agent_control_evaluator_detect_secrets.detect_secrets:DetectSecretsEvaluator"
    )
