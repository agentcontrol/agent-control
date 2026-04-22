"""Agent Control evaluator adapter for detect-secrets-async."""

from __future__ import annotations

import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import re2
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult
from detect_secrets_async import (
    RuntimeConfigConflictError,
    RuntimeScanError,
    ScanConfig,
    ScanFinding,
    ScanRequest,
    get_runtime,
    get_runtime_info,
)

from agent_control_evaluator_detect_secrets.detect_secrets.config import (
    DetectSecretsEvaluatorConfig,
)
from agent_control_evaluator_detect_secrets.detect_secrets.normalization import (
    LineLocation,
    NormalizationError,
    NormalizedPayload,
    apply_line_exclusions,
    normalize_payload,
)

try:
    PACKAGE_VERSION = version("agent-control-evaluator-detect_secrets")
except PackageNotFoundError:
    PACKAGE_VERSION = "0.0.0.dev"

FAILURE_MESSAGES: dict[str, str] = {
    "invalid_config": "detect-secrets runtime rejected the scan configuration",
    "normalization_error": "selected payload could not be normalized for secret scanning",
    "payload_too_large": "normalized payload exceeded the configured size limit",
    "queue_full": "detect-secrets runtime queue is full",
    "queue_timeout": "secret scan timed out while waiting for runtime capacity",
    "worker_startup_error": "detect-secrets worker failed to start",
    "worker_timeout": "secret scan timed out",
    "worker_crash": "detect-secrets worker exited unexpectedly",
    "worker_protocol_error": "detect-secrets worker protocol error",
    "runtime_error": "detect-secrets runtime error",
}

IDENTIFIER_LIKE_KEY_PATTERN = re2.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,127}$")
JSON_SCALAR_LIKE_KEY_PATTERN = re2.compile(
    r"^(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)$"
)


@register_evaluator
class DetectSecretsEvaluator(Evaluator[DetectSecretsEvaluatorConfig]):
    """Scan selector-selected content for likely secrets using detect-secrets-async."""

    metadata = EvaluatorMetadata(
        name="yelp.detect_secrets",
        version=PACKAGE_VERSION,
        description="Potential secret detection via detect-secrets-async",
        timeout_ms=10_000,
    )
    config_model = DetectSecretsEvaluatorConfig

    def __init__(self, config: DetectSecretsEvaluatorConfig) -> None:
        super().__init__(config)
        self._exclude_line_patterns = tuple(
            re2.compile(pattern) for pattern in config.exclude_lines_regex
        )

    async def evaluate(self, data: Any) -> EvaluatorResult:
        """Normalize selector output, run detect-secrets, and map results into EvaluatorResult."""
        started_at = time.monotonic()
        try:
            normalized = normalize_payload(data)
        except (NormalizationError, RecursionError):
            return self._failure_result(
                failure_mode="normalization_error",
                normalized_payload_type=None,
                detect_secrets_version=self._runtime_version_or_unknown(),
            )

        if normalized.payload_type == "none":
            return self._success_result(
                normalized=normalized,
                detect_secrets_version=self._runtime_version_or_unknown(),
                findings=[],
            )

        try:
            runtime_info = get_runtime_info()
        except Exception:
            return self._failure_result(
                failure_mode="runtime_error",
                normalized_payload_type=None,
                detect_secrets_version="unknown",
            )

        assert normalized.text is not None
        filtered_text = apply_line_exclusions(normalized.text, self._exclude_line_patterns)
        if len(filtered_text.encode("utf-8")) > self.config.max_bytes:
            return self._failure_result(
                failure_mode="payload_too_large",
                normalized_payload_type=normalized.payload_type,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )

        if self._remaining_timeout_ms(started_at) <= 0:
            return self._failure_result(
                failure_mode="queue_timeout",
                normalized_payload_type=normalized.payload_type,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )

        request = ScanRequest(
            content=filtered_text,
            timeout_ms=self._bounded_remaining_timeout_ms(started_at),
            config=ScanConfig(
                enabled_plugins=tuple(self.config.enabled_plugins)
                if self.config.enabled_plugins is not None
                else None
            ),
        )

        try:
            configured_runtime = runtime_info.configured_runtime
            runtime = (
                get_runtime(configured_runtime) if configured_runtime is not None else get_runtime()
            )
            scan_result = await runtime.scan(request)
        except RuntimeConfigConflictError:
            return self._failure_result(
                failure_mode="runtime_error",
                normalized_payload_type=normalized.payload_type,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )
        except RuntimeScanError as exc:
            failure_mode = exc.code.value
            return self._failure_result(
                failure_mode=failure_mode,
                normalized_payload_type=normalized.payload_type,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )
        except Exception:
            return self._failure_result(
                failure_mode="runtime_error",
                normalized_payload_type=normalized.payload_type,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )

        findings = self._map_findings(normalized=normalized, findings=scan_result.findings)
        return self._success_result(
            normalized=normalized,
            detect_secrets_version=scan_result.detect_secrets_version,
            findings=findings,
        )

    def _map_findings(
        self,
        *,
        normalized: NormalizedPayload,
        findings: tuple[ScanFinding, ...],
    ) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []

        for finding in findings:
            finding_metadata: dict[str, Any] = {"type": finding.type}
            if normalized.payload_type == "str":
                if finding.line_number is not None:
                    finding_metadata["line_number"] = finding.line_number
            elif normalized.payload_type in {"dict", "list"}:
                if finding.line_number is not None:
                    location = normalized.line_locations_by_line.get(finding.line_number)
                    json_pointer = self._safe_structured_pointer(location=location)
                    if json_pointer is not None:
                        finding_metadata["json_pointer"] = json_pointer

            mapped.append(finding_metadata)

        return mapped

    def _safe_structured_pointer(self, *, location: LineLocation | None) -> str | None:
        if location is None:
            return None

        pointer = location.json_pointer
        if location.key_name is not None and self._key_name_is_secret_like(location.key_name):
            pointer = location.parent_pointer

        return self._truncate_pointer_at_secret_like_segment(pointer)

    def _truncate_pointer_at_secret_like_segment(self, pointer: str | None) -> str | None:
        if pointer is None or pointer == "":
            return pointer

        safe_segments: list[str] = []
        for encoded_segment in pointer.split("/")[1:]:
            segment = self._decode_json_pointer_segment(encoded_segment)
            if self._pointer_segment_is_secret_like(segment):
                break
            safe_segments.append(segment)
        else:
            return pointer

        if not safe_segments:
            return ""

        encoded_segments = [self._encode_json_pointer_segment(segment) for segment in safe_segments]
        return "/" + "/".join(encoded_segments)

    def _pointer_segment_is_secret_like(self, segment: str) -> bool:
        if segment.isdigit():
            return False
        return self._key_name_is_secret_like(segment)

    def _decode_json_pointer_segment(self, segment: str) -> str:
        return segment.replace("~1", "/").replace("~0", "~")

    def _encode_json_pointer_segment(self, segment: str) -> str:
        return segment.replace("~", "~0").replace("/", "~1")

    def _key_name_is_secret_like(self, key_name: str | None) -> bool:
        if key_name is None:
            return False

        if JSON_SCALAR_LIKE_KEY_PATTERN.fullmatch(key_name):
            return False

        if not IDENTIFIER_LIKE_KEY_PATTERN.fullmatch(key_name):
            return True

        has_alpha = any(character.isalpha() for character in key_name)
        has_digit = any(character.isdigit() for character in key_name)
        has_token_separator = any(character in "._:-" for character in key_name)
        return len(key_name) >= 20 and has_alpha and (has_digit or has_token_separator)

    def _runtime_version_or_unknown(self) -> str:
        try:
            return get_runtime_info().detect_secrets_version
        except Exception:
            return "unknown"

    def _remaining_timeout_ms(self, started_at: float) -> int:
        return int(self.config.timeout_ms - ((time.monotonic() - started_at) * 1000))

    def _bounded_remaining_timeout_ms(self, started_at: float) -> int:
        return max(1, self._remaining_timeout_ms(started_at))

    def _success_result(
        self,
        *,
        normalized: NormalizedPayload,
        detect_secrets_version: str,
        findings: list[dict[str, Any]],
    ) -> EvaluatorResult:
        matched = bool(findings)
        return EvaluatorResult(
            matched=matched,
            confidence=1.0,
            message=(
                f"Potential secrets detected ({len(findings)} findings)"
                if matched
                else "No potential secrets detected"
            ),
            metadata={
                "findings_count": len(findings),
                "findings": findings,
                "normalized_payload_type": normalized.payload_type,
                "detect_secrets_version": detect_secrets_version,
            },
        )

    def _failure_result(
        self,
        *,
        failure_mode: str,
        normalized_payload_type: str | None,
        detect_secrets_version: str,
    ) -> EvaluatorResult:
        detail = FAILURE_MESSAGES.get(failure_mode, FAILURE_MESSAGES["runtime_error"])
        metadata: dict[str, Any] = {
            "findings_count": 0,
            "findings": [],
            "detect_secrets_version": detect_secrets_version,
            "failure_mode": failure_mode,
        }
        if normalized_payload_type is not None:
            metadata["normalized_payload_type"] = normalized_payload_type

        if self.config.on_error == "deny":
            metadata["fallback_action"] = "deny"
            return EvaluatorResult(
                matched=True,
                confidence=0.0,
                message=f"Denied due to evaluator failure ({failure_mode}): {detail}",
                metadata=metadata,
            )

        metadata["fallback_action"] = "allow"
        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"Secret scan failed ({failure_mode}): {detail}; allowing request",
            metadata=metadata,
        )
