from __future__ import annotations

import asyncio
from importlib.metadata import entry_points
from typing import Any, Literal

import pytest
from detect_secrets_async import (
    RuntimeConfig,
    RuntimeConfigConflictError,
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


def test_entry_point_load_returns_evaluator_class() -> None:
    # Given: the registered yelp.detect_secrets entry point
    evaluator_entry_points = {
        entry_point.name: entry_point
        for entry_point in entry_points(group="agent_control.evaluators")
    }
    entry_point = evaluator_entry_points["yelp.detect_secrets"]

    # When: the entry point is loaded
    loaded_class = entry_point.load()

    # Then: it resolves to the DetectSecretsEvaluator class
    assert loaded_class is DetectSecretsEvaluator


# ---------------------------------------------------------------------------
# Failure-mode matrix: every ScanFailureCode x {allow, deny} combination,
# plus evaluator-layer failures, plus a drift pin for FAILURE_MESSAGES.
# ---------------------------------------------------------------------------

_RUNTIME_FAILURE_CODES: tuple[ScanFailureCode, ...] = (
    ScanFailureCode.INVALID_CONFIG,
    ScanFailureCode.QUEUE_FULL,
    ScanFailureCode.QUEUE_TIMEOUT,
    ScanFailureCode.WORKER_STARTUP_ERROR,
    ScanFailureCode.WORKER_TIMEOUT,
    ScanFailureCode.WORKER_CRASH,
    ScanFailureCode.WORKER_PROTOCOL_ERROR,
    ScanFailureCode.RUNTIME_ERROR,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_code", _RUNTIME_FAILURE_CODES)
@pytest.mark.parametrize("on_error", ["allow", "deny"])
async def test_runtime_failure_routes_through_on_error_for_each_code(
    failure_code: ScanFailureCode,
    on_error: Literal["allow", "deny"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a runtime that raises the given ScanFailureCode on every scan
    class FakeRuntime:
        async def scan(self, request: Any) -> Any:
            raise RuntimeScanError(failure_code)

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        lambda config=None: FakeRuntime(),
    )
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(on_error=on_error))

    # When: a valid string payload is evaluated
    result = await evaluator.evaluate("safe content only")

    # Then: the failure_mode reflects the code and fallback_action mirrors on_error
    assert result.error is None
    assert result.confidence == 0.0
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == failure_code.value
    assert result.metadata["fallback_action"] == on_error
    assert result.message is not None
    assert FAILURE_MESSAGES[failure_code.value] in result.message
    assert result.matched is (on_error == "deny")


@pytest.mark.asyncio
@pytest.mark.parametrize("on_error", ["allow", "deny"])
@pytest.mark.parametrize(
    ("failure_mode", "config_kwargs", "payload"),
    [
        ("normalization_error", {}, {"bad": {1, 2, 3}}),
        ("payload_too_large", {"max_bytes": 8}, "0123456789"),
    ],
    ids=["normalization_error", "payload_too_large"],
)
async def test_evaluator_layer_failure_routes_through_on_error(
    failure_mode: str,
    config_kwargs: dict[str, Any],
    payload: Any,
    on_error: Literal["allow", "deny"],
) -> None:
    # Given: an evaluator configured to hit the given evaluator-layer failure
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(on_error=on_error, **config_kwargs)
    )

    # When: the triggering payload is evaluated
    result = await evaluator.evaluate(payload)

    # Then: metadata carries the expected failure_mode and fallback_action for both modes
    assert result.error is None
    assert result.confidence == 0.0
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == failure_mode
    assert result.metadata["fallback_action"] == on_error
    assert result.matched is (on_error == "deny")


def test_failure_messages_cover_all_runtime_scan_failure_codes() -> None:
    # Given: the detect-secrets-async ScanFailureCode enum and the evaluator's two
    #        evaluator-layer failure modes
    runtime_code_values = {code.value for code in ScanFailureCode}
    evaluator_layer_codes = {"normalization_error", "payload_too_large"}

    # When: the expected key set is formed
    expected_keys = runtime_code_values | evaluator_layer_codes

    # Then: FAILURE_MESSAGES has exactly that set, with a non-empty message for each
    assert set(FAILURE_MESSAGES) == expected_keys
    assert all(message for message in FAILURE_MESSAGES.values())


# ---------------------------------------------------------------------------
# Normalization edge cases (top-level types, NaN, empty containers,
# non-string dict keys).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_top_level_set_routes_through_normalization_error() -> None:
    # Given: a payload whose top-level type is not supported (a plain set)
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: the evaluator evaluates it
    result = await evaluator.evaluate({"abc", "def"})

    # Then: the failure is classified as normalization_error
    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "normalization_error"
    assert result.metadata["fallback_action"] == "allow"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_scalar", [float("nan"), float("inf"), float("-inf")])
async def test_nan_or_infinity_primitive_routes_through_normalization_error(
    bad_scalar: float,
) -> None:
    # Given: a non-finite float which json.dumps(allow_nan=False) rejects
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: the evaluator evaluates it
    result = await evaluator.evaluate(bad_scalar)

    # Then: normalization fails safely through on_error=allow
    assert result.matched is False
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "normalization_error"
    assert result.metadata["fallback_action"] == "allow"


@pytest.mark.asyncio
async def test_empty_dict_payload_yields_no_findings() -> None:
    # Given: an empty dict
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: the evaluator evaluates it
    result = await evaluator.evaluate({})

    # Then: it scans successfully with no findings
    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert result.metadata["findings"] == []
    assert result.metadata["findings_count"] == 0


@pytest.mark.asyncio
async def test_empty_list_payload_yields_no_findings() -> None:
    # Given: an empty list
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: the evaluator evaluates it
    result = await evaluator.evaluate([])

    # Then: it scans successfully with no findings
    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "list"
    assert result.metadata["findings"] == []
    assert result.metadata["findings_count"] == 0


@pytest.mark.asyncio
async def test_boolean_and_none_dict_keys_are_normalized_as_scalar_strings() -> None:
    # Given: a dict keyed by True/False/None alongside a GitHub token under the True key
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    # When: the evaluator normalizes and scans
    result = await evaluator.evaluate(
        {
            True: "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            False: "safe value",
            None: "also safe",
        }
    )

    # Then: the True key normalizes to "true" and the finding resolves to /true
    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "dict"
    assert result.metadata["findings"] == [{"type": "GitHub Token", "json_pointer": "/true"}]


@pytest.mark.asyncio
async def test_unsupported_dict_key_type_routes_through_normalization_error() -> None:
    # Given: a dict keyed by a tuple (unsupported JSON key type)
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: the evaluator evaluates it
    result = await evaluator.evaluate({("a", "b"): "value"})

    # Then: normalization fails safely
    assert result.matched is False
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "normalization_error"
    assert result.metadata["fallback_action"] == "allow"


# ---------------------------------------------------------------------------
# Runtime-side failure paths that aren't exercised elsewhere.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runtime_info_failure_during_non_none_evaluate_returns_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a get_runtime_info reference inside the evaluator module that always raises
    def raise_runtime_error() -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime_info",
        raise_runtime_error,
    )
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: a non-None payload is evaluated (the None short-circuit doesn't apply)
    result = await evaluator.evaluate("safe content only")

    # Then: the evaluator returns runtime_error with unknown detect-secrets version
    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "runtime_error"
    assert result.metadata["fallback_action"] == "allow"
    assert result.metadata["detect_secrets_version"] == "unknown"
    assert "normalized_payload_type" not in result.metadata


@pytest.mark.asyncio
async def test_runtime_config_conflict_routes_through_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: get_runtime that raises RuntimeConfigConflictError
    def raise_conflict(config: Any = None) -> Any:
        raise RuntimeConfigConflictError("conflict")

    monkeypatch.setattr(
        "agent_control_evaluator_detect_secrets.detect_secrets.evaluator.get_runtime",
        raise_conflict,
    )
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: a valid payload is evaluated
    result = await evaluator.evaluate("safe content only")

    # Then: the conflict is sanitized to a runtime_error failure
    assert result.matched is False
    assert result.error is None
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "runtime_error"
    assert result.metadata["fallback_action"] == "allow"
    assert result.metadata["normalized_payload_type"] == "str"


# ---------------------------------------------------------------------------
# exclude_lines_regex on structured payloads.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exclude_lines_regex_on_dict_payload_blanks_matching_line() -> None:
    # Given: an evaluator configured to exclude JSON lines that contain "authorization"
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(
            enabled_plugins=["GitHubTokenDetector"],
            exclude_lines_regex=[r'"authorization"'],
        )
    )

    # When: a dict carries the secret on the excluded line
    result = await evaluator.evaluate(
        {
            "authorization": "ghp_123456789012345678901234567890123456",
            "other": "safe",
        }
    )

    # Then: the excluded line is blanked and no finding is surfaced
    assert result.matched is False
    assert result.metadata is not None
    assert result.metadata["findings"] == []


@pytest.mark.asyncio
async def test_exclude_lines_regex_on_dict_payload_preserves_pointers_for_other_findings() -> None:
    # Given: a dict where one line matches the exclusion and a DIFFERENT line has a secret
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(
            enabled_plugins=["GitHubTokenDetector"],
            exclude_lines_regex=[r'"skip"'],
        )
    )

    # When: the evaluator scans
    result = await evaluator.evaluate(
        {
            "skip": "ghp_abcdefabcdefabcdefabcdefabcdefabcdef",
            "keep": "ghp_111111111111111111111111111111111111",
        }
    )

    # Then: line-number blanking does not disturb the surviving finding's pointer
    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["findings"] == [{"type": "GitHub Token", "json_pointer": "/keep"}]


# ---------------------------------------------------------------------------
# max_bytes boundary behavior.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payload_exactly_at_max_bytes_is_accepted() -> None:
    # Given: a payload whose UTF-8 byte length exactly equals max_bytes
    payload = "a" * 64
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(max_bytes=64))

    # When: the evaluator evaluates it
    result = await evaluator.evaluate(payload)

    # Then: the scan proceeds without tripping payload_too_large
    assert result.metadata is not None
    assert result.metadata.get("failure_mode") is None
    assert result.metadata["normalized_payload_type"] == "str"


@pytest.mark.asyncio
async def test_payload_one_byte_over_max_bytes_is_rejected() -> None:
    # Given: a payload one byte over the configured max_bytes
    payload = "a" * 65
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig(max_bytes=64))

    # When: the evaluator evaluates it
    result = await evaluator.evaluate(payload)

    # Then: failure_mode is payload_too_large
    assert result.matched is False
    assert result.metadata is not None
    assert result.metadata["failure_mode"] == "payload_too_large"
    assert result.metadata["fallback_action"] == "allow"


# ---------------------------------------------------------------------------
# Scan-mapping edge cases and concurrency.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_line_string_preserves_distinct_line_numbers() -> None:
    # Given: a multi-line string with GitHub tokens on lines 1 and 3
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )
    content = "\n".join(
        [
            "first = 'ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'",
            "safe middle line",
            "third = 'ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'",
        ]
    )

    # When: the evaluator evaluates it
    result = await evaluator.evaluate(content)

    # Then: findings carry their respective original line numbers
    assert result.matched is True
    assert result.metadata is not None
    line_numbers = sorted(finding["line_number"] for finding in result.metadata["findings"])
    assert line_numbers == [1, 3]


@pytest.mark.asyncio
async def test_list_with_scalar_elements_maps_pointer_to_index() -> None:
    # Given: a list whose element at index 1 is a bare secret string
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )

    # When: the evaluator scans it
    result = await evaluator.evaluate(["safe", "ghp_123456789012345678901234567890123456"])

    # Then: the finding pointer names the list index
    assert result.matched is True
    assert result.metadata is not None
    assert result.metadata["normalized_payload_type"] == "list"
    assert result.metadata["findings"] == [{"type": "GitHub Token", "json_pointer": "/1"}]


@pytest.mark.asyncio
async def test_evaluate_is_safe_under_concurrent_calls() -> None:
    # Given: a single evaluator instance and several distinct secret-bearing payloads
    evaluator = DetectSecretsEvaluator(
        DetectSecretsEvaluatorConfig(enabled_plugins=["GitHubTokenDetector"])
    )
    payloads = [
        f"github_token_{index} = 'ghp_{str(index).zfill(2)}3456789012345678901234567890123456'"
        for index in range(5)
    ]

    # When: many evaluate() calls run in parallel on the cached instance
    results = await asyncio.gather(*(evaluator.evaluate(payload) for payload in payloads))

    # Then: every call produces the correct finding with line_number=1 and no cross-talk
    assert all(result.matched for result in results)
    assert all(
        result.metadata is not None
        and result.metadata["findings"] == [{"type": "GitHub Token", "line_number": 1}]
        for result in results
    )


def test_safe_structured_pointer_returns_none_for_missing_location() -> None:
    # Given: an evaluator instance and no location metadata
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When: the pointer helper is invoked without a location
    pointer = evaluator._safe_structured_pointer(location=None)

    # Then: the helper returns None so the finding is emitted without a pointer
    assert pointer is None


# ---------------------------------------------------------------------------
# Additional _key_name_is_secret_like coverage (None, non-identifier keys).
# ---------------------------------------------------------------------------


def test_key_name_is_secret_like_returns_false_for_none() -> None:
    # Given: an evaluator instance
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When/Then: a None key name is treated as not secret-like
    assert evaluator._key_name_is_secret_like(None) is False


@pytest.mark.parametrize(
    ("key_name", "expected"),
    [
        # Starts with digit then letters -> fails IDENTIFIER_LIKE_KEY_PATTERN -> secret-like.
        ("12abcd", True),
        # Starts with symbol -> fails IDENTIFIER_LIKE_KEY_PATTERN -> secret-like.
        ("!bang", True),
        # Matches JSON_SCALAR_LIKE_KEY_PATTERN -> not secret-like.
        ("true", False),
        ("-1.5e10", False),
    ],
)
def test_key_name_is_secret_like_for_non_identifier_and_scalar_keys(
    key_name: str, expected: bool
) -> None:
    # Given: an evaluator instance
    evaluator = DetectSecretsEvaluator(DetectSecretsEvaluatorConfig())

    # When/Then: the heuristic honors the non-identifier and JSON-scalar branches
    assert evaluator._key_name_is_secret_like(key_name) is expected


# ---------------------------------------------------------------------------
# Config validator edge cases.
# ---------------------------------------------------------------------------


def test_explicit_none_enabled_plugins_is_accepted() -> None:
    # Given: enabled_plugins explicitly set to None
    config = DetectSecretsEvaluatorConfig(enabled_plugins=None)

    # Then: the config is accepted and enabled_plugins stays None
    assert config.enabled_plugins is None


def test_whitespace_only_enabled_plugin_name_is_rejected() -> None:
    # Given: a plugin list containing only whitespace
    # When/Then: construction raises a non-empty validation error
    with pytest.raises(ValueError, match="non-empty"):
        DetectSecretsEvaluatorConfig(enabled_plugins=["   "])


def test_enabled_plugins_strips_whitespace_and_dedups() -> None:
    # Given: duplicate and whitespace-padded plugin names
    config = DetectSecretsEvaluatorConfig(
        enabled_plugins=["  GitHubTokenDetector  ", "GitHubTokenDetector"]
    )

    # Then: names are stripped and duplicates removed in first-seen order
    assert config.enabled_plugins == ["GitHubTokenDetector"]


def test_zero_timeout_ms_is_rejected() -> None:
    # Given/When/Then: timeout_ms must be strictly positive
    with pytest.raises(ValueError):
        DetectSecretsEvaluatorConfig(timeout_ms=0)


def test_zero_max_bytes_is_rejected() -> None:
    # Given/When/Then: max_bytes must be strictly positive
    with pytest.raises(ValueError):
        DetectSecretsEvaluatorConfig(max_bytes=0)


def test_invalid_on_error_value_is_rejected() -> None:
    # Given/When/Then: on_error only accepts "allow" or "deny"
    with pytest.raises(ValueError):
        DetectSecretsEvaluatorConfig(on_error="maybe")  # type: ignore[arg-type]
