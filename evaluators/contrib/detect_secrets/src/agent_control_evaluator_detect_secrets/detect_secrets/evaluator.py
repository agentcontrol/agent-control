"""Agent Control evaluator adapter for detect-secrets-async."""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict, deque
from contextlib import AbstractContextManager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import re2
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult
from detect_secrets.core.scan import scan_line
from detect_secrets.settings import default_settings, transient_settings
from detect_secrets_async import (
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
_LOCAL_SCAN_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class _LocalLineMatch:
    """A direct detect-secrets match for a single rendered line."""

    type: str
    secret_value: str | None


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
            timeout_ms=self._bounded_remaining_timeout_ms(started_at),
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
            scanned_text=filtered_text,
            findings=scan_result.findings,
            scan_config=request.config,
            started_at=started_at,
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
        scanned_text: str,
        findings: tuple[ScanFinding, ...],
        scan_config: ScanConfig,
        started_at: float,
    ) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        structured_pointer_assignments = self._build_structured_pointer_assignments(
            normalized=normalized,
            scanned_text=scanned_text,
            findings=findings,
            scan_config=scan_config,
            started_at=started_at,
        )

        for finding in findings:
            finding_metadata: dict[str, Any] = {"type": finding.type}
            if normalized.payload_type == "str":
                if finding.line_number is not None:
                    finding_metadata["line_number"] = finding.line_number
            elif normalized.payload_type in {"dict", "list"}:
                if finding.line_number is not None:
                    location = normalized.line_locations_by_line.get(finding.line_number)
                    json_pointer = self._safe_structured_pointer(
                        location=location,
                        finding=finding,
                        structured_pointer_assignments=structured_pointer_assignments,
                    )
                    if json_pointer is not None:
                        finding_metadata["json_pointer"] = json_pointer

            mapped.append(finding_metadata)

        return mapped

    def _safe_structured_pointer(
        self,
        *,
        location: LineLocation | None,
        finding: ScanFinding,
        structured_pointer_assignments: dict[int, deque[str | None]],
    ) -> str | None:
        if location is None:
            return None

        if location.key_probe_text is None:
            return location.json_pointer

        assert finding.line_number is not None
        line_assignments = structured_pointer_assignments.get(finding.line_number)
        if line_assignments:
            return line_assignments.popleft()

        return location.parent_pointer

    def _build_structured_pointer_assignments(
        self,
        *,
        normalized: NormalizedPayload,
        scanned_text: str,
        findings: tuple[ScanFinding, ...],
        scan_config: ScanConfig,
        started_at: float,
    ) -> dict[int, deque[str | None]]:
        if normalized.payload_type not in {"dict", "list"}:
            return {}

        if self._remaining_timeout_ms(started_at) <= 0:
            return {}

        findings_by_line: dict[int, list[ScanFinding]] = defaultdict(list)
        for finding in findings:
            if finding.line_number is None:
                continue
            findings_by_line[finding.line_number].append(finding)

        if not findings_by_line:
            return {}

        scanned_lines = scanned_text.splitlines()
        assignments_by_line: dict[int, deque[str | None]] = {}
        for line_number, line_findings in findings_by_line.items():
            location = normalized.line_locations_by_line.get(line_number)
            if location is None or location.key_probe_text is None:
                continue

            if self._remaining_timeout_ms(started_at) <= 0:
                break

            line_index = line_number - 1
            if not 0 <= line_index < len(scanned_lines):
                continue

            full_matches = self._scan_line_matches(scanned_lines[line_index], scan_config)
            if not full_matches:
                continue
            probe_matches = self._scan_line_matches(location.key_probe_text, scan_config)
            line_assignments = self._assign_structured_line_pointers(
                location=location,
                line_findings=line_findings,
                full_matches=full_matches,
                probe_matches=probe_matches,
            )
            assignments_by_line[line_number] = deque(line_assignments)

        return assignments_by_line

    def _assign_structured_line_pointers(
        self,
        *,
        location: LineLocation,
        line_findings: list[ScanFinding],
        full_matches: tuple[_LocalLineMatch, ...],
        probe_matches: tuple[_LocalLineMatch, ...],
    ) -> list[str | None]:
        if len(full_matches) != len(line_findings):
            return self._fallback_structured_line_pointers(
                location=location,
                line_findings=line_findings,
                probe_matches=probe_matches,
            )

        probe_match_counts = Counter((match.type, match.secret_value) for match in probe_matches)
        line_pointers: list[str | None] = []
        for finding, full_match in zip(line_findings, full_matches, strict=True):
            if finding.type != full_match.type:
                return self._fallback_structured_line_pointers(
                    location=location,
                    line_findings=line_findings,
                    probe_matches=probe_matches,
                )

            match_key = (full_match.type, full_match.secret_value)
            if probe_match_counts[match_key] > 0:
                line_pointers.append(location.parent_pointer)
                probe_match_counts[match_key] -= 1
            else:
                line_pointers.append(location.json_pointer)

        return line_pointers

    def _fallback_structured_line_pointers(
        self,
        *,
        location: LineLocation,
        line_findings: list[ScanFinding],
        probe_matches: tuple[_LocalLineMatch, ...],
    ) -> list[str | None]:
        probe_types = {match.type for match in probe_matches}
        return [
            location.parent_pointer if finding.type in probe_types else location.json_pointer
            for finding in line_findings
        ]

    def _scan_line_matches(
        self,
        line: str,
        scan_config: ScanConfig,
    ) -> tuple[_LocalLineMatch, ...]:
        with _LOCAL_SCAN_LOCK:
            with self._scan_settings(scan_config):
                return tuple(
                    _LocalLineMatch(type=secret.type, secret_value=secret.secret_value)
                    for secret in scan_line(line)
                )

    def _scan_settings(self, scan_config: ScanConfig) -> AbstractContextManager[object]:
        if scan_config.enabled_plugins is None:
            return default_settings()

        return transient_settings(
            {"plugins_used": [{"name": plugin_name} for plugin_name in scan_config.enabled_plugins]}
        )

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

        return EvaluatorResult(
            matched=False,
            confidence=0.0,
            message=f"Secret scan failed ({failure_mode}): {detail}; allowing request",
            metadata=metadata,
            error=f"detect-secrets evaluator failure: {failure_mode}",
        )
