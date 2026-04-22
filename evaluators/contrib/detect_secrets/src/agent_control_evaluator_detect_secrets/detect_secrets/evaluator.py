"""Agent Control evaluator adapter for detect-secrets-async."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

import re2
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult
from detect_secrets_async import (
    DetectSecretsRuntime,
    RuntimeScanError,
    ScanConfig,
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
    PACKAGE_VERSION = version("agent-control-evaluator-detect-secrets")
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
        runtime_info = get_runtime_info()

        try:
            normalized = normalize_payload(data)
        except NormalizationError:
            return self._failure_result(
                failure_mode="normalization_error",
                normalized_payload_type=None,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )

        if normalized.payload_type == "none":
            return self._success_result(
                normalized=normalized,
                detect_secrets_version=runtime_info.detect_secrets_version,
                findings=[],
            )

        assert normalized.text is not None
        filtered_text = apply_line_exclusions(normalized.text, self._exclude_line_patterns)
        if len(filtered_text.encode("utf-8")) > self.config.max_bytes:
            return self._failure_result(
                failure_mode="payload_too_large",
                normalized_payload_type=normalized.payload_type,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )

        request = ScanRequest(
            content=filtered_text,
            timeout_ms=self.config.timeout_ms,
            config=ScanConfig(
                enabled_plugins=tuple(self.config.enabled_plugins)
                if self.config.enabled_plugins is not None
                else None
            ),
        )

        try:
            runtime = get_runtime()
            scan_result = await runtime.scan(request)
        except RuntimeScanError as exc:
            failure_mode = exc.code.value
            return self._failure_result(
                failure_mode=failure_mode,
                normalized_payload_type=normalized.payload_type,
                detect_secrets_version=runtime_info.detect_secrets_version,
            )

        findings = await self._map_findings(
            normalized=normalized,
            findings=scan_result.findings,
            runtime=runtime,
            scan_config=request.config,
        )
        return self._success_result(
            normalized=normalized,
            detect_secrets_version=scan_result.detect_secrets_version,
            findings=findings,
        )

    async def _map_findings(
        self,
        *,
        normalized: NormalizedPayload,
        findings: tuple[Any, ...],
        runtime: DetectSecretsRuntime,
        scan_config: ScanConfig,
    ) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        key_probe_cache: dict[str, set[str]] = {}

        for finding in findings:
            finding_metadata: dict[str, Any] = {"type": finding.type}
            if normalized.payload_type == "str":
                if finding.line_number is not None:
                    finding_metadata["line_number"] = finding.line_number
            elif normalized.payload_type in {"dict", "list"}:
                if finding.line_number is not None:
                    location = normalized.line_locations_by_line.get(finding.line_number)
                    json_pointer = await self._safe_structured_pointer(
                        location=location,
                        finding_type=finding.type,
                        runtime=runtime,
                        scan_config=scan_config,
                        key_probe_cache=key_probe_cache,
                    )
                    if json_pointer is not None:
                        finding_metadata["json_pointer"] = json_pointer

            mapped.append(finding_metadata)

        return mapped

    async def _safe_structured_pointer(
        self,
        *,
        location: LineLocation | None,
        finding_type: str,
        runtime: DetectSecretsRuntime,
        scan_config: ScanConfig,
        key_probe_cache: dict[str, set[str]],
    ) -> str | None:
        if location is None:
            return None

        if location.key_probe_text is None:
            return location.json_pointer

        key_probe_text = location.key_probe_text
        probe_findings = key_probe_cache.get(key_probe_text)
        if probe_findings is None:
            try:
                probe_result = await runtime.scan(
                    ScanRequest(
                        content=key_probe_text,
                        timeout_ms=self.config.timeout_ms,
                        config=scan_config,
                    )
                )
            except RuntimeScanError:
                return location.parent_pointer

            probe_findings = {finding.type for finding in probe_result.findings}
            key_probe_cache[key_probe_text] = probe_findings

        if finding_type in probe_findings:
            return location.parent_pointer

        return location.json_pointer

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

        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"Secret scan failed ({failure_mode}): {detail}; allowing request",
            metadata=metadata,
            error=f"detect-secrets evaluator failure: {failure_mode}",
        )
