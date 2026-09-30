"""Shared evaluator helper functions for Galileo scorer evaluators.

Used by both galileo.luna and galileo.llm evaluators. Neither subpackage
is guaranteed to be installed alongside the other, so all shared helper
code lives here rather than in either evaluator's own module tree.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from agent_control_models import JSONValue

from agent_control_evaluator_galileo._shared.config import coerce_number

_HTTP_ERROR_BODY_LIMIT = 500


def _coerce_payload_text(value: Any) -> str | None:
    """Coerce selected data into scorer text without losing structured values."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _has_text(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def _extract_dict_text(data: dict[str, Any], key: str) -> str | None:
    if key not in data:
        return None
    return _coerce_payload_text(data.get(key))


def _contains(score: JSONValue, threshold: JSONValue) -> bool:
    if threshold is None:
        return False
    if isinstance(score, str):
        return str(threshold) in score
    if isinstance(score, list):
        return threshold in score
    if isinstance(score, dict):
        return threshold in score.values()
    return False


def _confidence_from_score(score: JSONValue) -> float:
    if isinstance(score, bool):
        return 1.0 if score else 0.0
    number = coerce_number(score)
    if number is not None and 0.0 <= number <= 1.0:
        return number
    return 1.0


def _truncated_http_response_body(body: str) -> tuple[str, bool]:
    if len(body) <= _HTTP_ERROR_BODY_LIMIT:
        return body, False
    return body[:_HTTP_ERROR_BODY_LIMIT], True


def _http_status_error_metadata(error: httpx.HTTPStatusError) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    request = error.request
    metadata["http_method"] = request.method
    metadata["http_endpoint_path"] = request.url.path

    response = error.response
    metadata["http_status_code"] = response.status_code
    metadata["http_response_content_type"] = response.headers.get("content-type")

    body = response.text
    if body:
        metadata["http_response_body"], metadata["http_response_body_truncated"] = (
            _truncated_http_response_body(body)
        )

    return {key: value for key, value in metadata.items() if value is not None}


def score_matches(score: JSONValue, *, operator: str, threshold: JSONValue) -> bool:
    """Apply a threshold comparison to a raw scorer score."""
    if operator == "any":
        return bool(score)
    if operator == "eq":
        return score == threshold
    if operator == "ne":
        return score != threshold
    if operator == "contains":
        return _contains(score, threshold)

    score_number = coerce_number(score)
    threshold_number = coerce_number(threshold)
    if score_number is None:
        raise ValueError(f"Scorer score {score!r} is not numeric")
    if threshold_number is None:
        raise ValueError(f"Scorer threshold {threshold!r} is not numeric")

    if operator == "gt":
        return score_number > threshold_number
    if operator == "gte":
        return score_number >= threshold_number
    if operator == "lt":
        return score_number < threshold_number
    if operator == "lte":
        return score_number <= threshold_number

    raise ValueError(f"Unsupported scorer operator: {operator}")


def base_metadata(
    scorer_id: str,
    *,
    scorer_version_id: str | None,
    scorer_label: str | None,
) -> dict[str, Any]:
    """Build result metadata without implying a requested version executed."""
    metadata: dict[str, Any] = {"scorer_id": scorer_id}
    if scorer_version_id is not None:
        metadata["requested_scorer_version_id"] = scorer_version_id
    if scorer_label is not None:
        metadata["scorer_label"] = scorer_label
    return metadata


def full_metadata(
    response: Any,
    *,
    scorer_id: str,
    scorer_version_id: str | None,
    scorer_label: str | None,
    threshold: JSONValue,
    operator: str,
) -> dict[str, Any]:
    """Build full result metadata including score and response fields."""
    metadata = base_metadata(scorer_id, scorer_version_id=scorer_version_id, scorer_label=scorer_label)
    echoed_label = response.scorer_label or scorer_label
    if echoed_label is not None:
        metadata["scorer_label"] = echoed_label
    metadata.update(
        {
            "score": response.score,
            "threshold": threshold,
            "operator": operator,
            "status": response.status,
            "execution_time_seconds": response.execution_time,
            "error_message": response.error_message,
        }
    )
    return metadata
