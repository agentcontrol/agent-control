"""Agent Control evaluator adapter for detect-secrets-async."""

from __future__ import annotations

import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import re2
from agent_control_evaluators import Evaluator, EvaluatorMetadata, register_evaluator
from agent_control_models import EvaluatorResult
from detect_secrets_async import (
    DetectSecretsRuntime,
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


@dataclass(frozen=True, slots=True)
class StructuredPointerAssignments:
    """Structured-line pointer assignments plus secret-bearing key ancestry."""

    by_line: dict[int, deque[str | None]]
    secret_key_pointers: set[str]


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
        except NormalizationError:
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

        findings = await self._map_findings(
            normalized=normalized,
            scanned_text=filtered_text,
            findings=scan_result.findings,
            runtime=runtime,
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
        runtime: DetectSecretsRuntime,
        scan_config: ScanConfig,
        started_at: float,
    ) -> list[dict[str, Any]]:
        mapped: list[dict[str, Any]] = []
        structured_pointer_assignments = await self._build_structured_pointer_assignments(
            normalized=normalized,
            scanned_text=scanned_text,
            findings=findings,
            runtime=runtime,
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
                        structured_pointer_assignments=structured_pointer_assignments.by_line,
                        secret_key_pointers=structured_pointer_assignments.secret_key_pointers,
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
        secret_key_pointers: set[str],
    ) -> str | None:
        if location is None:
            return None

        if location.key_probe_text is None:
            pointer = location.json_pointer
        else:
            assert finding.line_number is not None
            line_assignments = structured_pointer_assignments.get(finding.line_number)
            if line_assignments:
                pointer = line_assignments.popleft()
            else:
                return None

        if self._pointer_traverses_secret_key(pointer, secret_key_pointers):
            return None
        return pointer

    async def _build_structured_pointer_assignments(
        self,
        *,
        normalized: NormalizedPayload,
        scanned_text: str,
        findings: tuple[ScanFinding, ...],
        runtime: DetectSecretsRuntime,
        scan_config: ScanConfig,
        started_at: float,
    ) -> StructuredPointerAssignments:
        if normalized.payload_type not in {"dict", "list"}:
            return StructuredPointerAssignments(by_line={}, secret_key_pointers=set())

        if self._remaining_timeout_ms(started_at) <= 0:
            return StructuredPointerAssignments(by_line={}, secret_key_pointers=set())

        findings_by_line: dict[int, list[ScanFinding]] = defaultdict(list)
        for finding in findings:
            if finding.line_number is None:
                continue
            findings_by_line[finding.line_number].append(finding)

        if not findings_by_line:
            return StructuredPointerAssignments(by_line={}, secret_key_pointers=set())

        scanned_lines = scanned_text.splitlines()
        candidate_lines: list[int] = []
        full_line_batch: list[str] = []
        probe_line_batch: list[str] = []

        for line_number in sorted(findings_by_line):
            location = normalized.line_locations_by_line.get(line_number)
            if location is None or location.key_probe_text is None:
                continue

            line_index = line_number - 1
            if not 0 <= line_index < len(scanned_lines):
                continue

            candidate_lines.append(line_number)
            full_line_batch.append(scanned_lines[line_index])
            probe_line_batch.append(location.key_probe_text)

        if not candidate_lines:
            return StructuredPointerAssignments(by_line={}, secret_key_pointers=set())

        full_line_findings = await self._scan_line_batch(
            runtime=runtime,
            lines=full_line_batch,
            scan_config=scan_config,
            started_at=started_at,
        )
        if full_line_findings is None:
            return StructuredPointerAssignments(by_line={}, secret_key_pointers=set())

        probe_line_findings = await self._scan_line_batch(
            runtime=runtime,
            lines=probe_line_batch,
            scan_config=scan_config,
            started_at=started_at,
        )
        if probe_line_findings is None:
            return StructuredPointerAssignments(by_line={}, secret_key_pointers=set())

        assignments_by_line: dict[int, deque[str | None]] = {}
        secret_key_pointers: set[str] = set()
        for batch_index, line_number in enumerate(candidate_lines, start=1):
            location = normalized.line_locations_by_line[line_number]
            line_assignments, line_secret_key_pointers = self._assign_structured_line_pointers(
                location=location,
                line_findings=findings_by_line[line_number],
                full_line_findings=full_line_findings.get(batch_index, []),
                probe_line_findings=probe_line_findings.get(batch_index, []),
            )
            assignments_by_line[line_number] = deque(line_assignments)
            secret_key_pointers.update(line_secret_key_pointers)

        return StructuredPointerAssignments(
            by_line=assignments_by_line,
            secret_key_pointers=secret_key_pointers,
        )

    def _assign_structured_line_pointers(
        self,
        *,
        location: LineLocation,
        line_findings: list[ScanFinding],
        full_line_findings: list[ScanFinding],
        probe_line_findings: list[ScanFinding],
    ) -> tuple[list[str | None], set[str]]:
        if len(full_line_findings) != len(line_findings):
            return self._fallback_structured_line_pointers(
                location=location,
                line_findings=line_findings,
                probe_line_findings=probe_line_findings,
            )

        probe_type_counts = Counter(finding.type for finding in probe_line_findings)
        line_pointers: list[str | None] = []
        secret_key_pointers: set[str] = set()
        for finding, full_line_finding in zip(line_findings, full_line_findings, strict=True):
            if finding.type != full_line_finding.type:
                return self._fallback_structured_line_pointers(
                    location=location,
                    line_findings=line_findings,
                    probe_line_findings=probe_line_findings,
                )

            if probe_type_counts[full_line_finding.type] > 0:
                line_pointers.append(location.parent_pointer)
                if location.json_pointer is not None and self._key_name_is_secret_like(
                    location.key_name
                ):
                    secret_key_pointers.add(location.json_pointer)
                probe_type_counts[full_line_finding.type] -= 1
            else:
                line_pointers.append(location.json_pointer)

        return line_pointers, secret_key_pointers

    def _fallback_structured_line_pointers(
        self,
        *,
        location: LineLocation,
        line_findings: list[ScanFinding],
        probe_line_findings: list[ScanFinding],
    ) -> tuple[list[str | None], set[str]]:
        probe_types = {finding.type for finding in probe_line_findings}
        secret_key_pointers = (
            {location.json_pointer}
            if location.json_pointer
            and probe_types
            and self._key_name_is_secret_like(location.key_name)
            else set()
        )
        return (
            [
                location.parent_pointer if finding.type in probe_types else location.json_pointer
                for finding in line_findings
            ],
            secret_key_pointers,
        )

    def _pointer_traverses_secret_key(
        self, pointer: str | None, secret_key_pointers: set[str]
    ) -> bool:
        if pointer is None:
            return False

        return any(
            pointer == secret_key_pointer or pointer.startswith(f"{secret_key_pointer}/")
            for secret_key_pointer in secret_key_pointers
        )

    def _key_name_is_secret_like(self, key_name: str | None) -> bool:
        if key_name is None:
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

    async def _scan_line_batch(
        self,
        *,
        runtime: DetectSecretsRuntime,
        lines: list[str],
        scan_config: ScanConfig,
        started_at: float,
    ) -> dict[int, list[ScanFinding]] | None:
        remaining_ms = self._remaining_timeout_ms(started_at)
        if remaining_ms <= 0:
            return None

        try:
            result = await runtime.scan(
                ScanRequest(
                    content="\n".join(lines),
                    timeout_ms=max(1, remaining_ms),
                    config=scan_config,
                )
            )
        except RuntimeScanError:
            return None
        except Exception:
            return None

        findings_by_line: dict[int, list[ScanFinding]] = defaultdict(list)
        for finding in result.findings:
            if finding.line_number is None:
                continue
            findings_by_line[finding.line_number].append(finding)

        return findings_by_line

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
