"""Validation tests for target models.

These tests lock in the path-safe identifier contracts for ``target_type``
and ``external_id``. The contracts matter because both values are embedded
in URL path segments for natural-key attach routes; values that contain
``/``, whitespace, or non-ASCII characters would either break path routing
or require callers to URL-encode. We reject them at the model layer.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_control_models import CreateTargetRequest


@pytest.mark.parametrize(
    "bad_target_type",
    [
        "Log-Stream",        # uppercase + hyphen
        "log-stream",        # hyphen
        "log/stream",        # slash — would break path routing
        "log stream",        # whitespace
        "1_log_stream",      # starts with digit
        "",                  # empty
        "a" * 65,            # too long
        "log.stream",        # dot not allowed in target_type
    ],
)
def test_create_target_rejects_invalid_target_type(bad_target_type: str) -> None:
    # Given: a target payload with a non-slug target_type
    # When: constructing CreateTargetRequest
    # Then: a validation error is raised naming target_type
    with pytest.raises(ValidationError) as exc_info:
        CreateTargetRequest(
            target_type=bad_target_type,
            external_id="legitimate-external-id",
        )
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("target_type",) for err in errors), (
        f"Expected target_type error for {bad_target_type!r}, got {errors}"
    )


@pytest.mark.parametrize(
    "good_target_type",
    [
        "environment",
        "log_stream",
        "a",                 # single letter is valid
        "a1",                # letter followed by digit
        "a" * 64,            # max length
        "project_v2",
    ],
)
def test_create_target_accepts_valid_target_type(good_target_type: str) -> None:
    # Given: a slug-shaped target_type
    # When: constructing CreateTargetRequest
    # Then: no error is raised
    req = CreateTargetRequest(
        target_type=good_target_type,
        external_id="legitimate-external-id",
    )
    assert req.target_type == good_target_type


@pytest.mark.parametrize(
    "bad_external_id",
    [
        "env/prod",          # slash — would break path routing
        "env prod",          # whitespace
        "env:prod",          # colon
        "env?prod",          # query-string char
        "env#prod",          # fragment char
        "",                  # empty
        "a" * 256,           # too long
        "café",        # non-ASCII
    ],
)
def test_create_target_rejects_invalid_external_id(bad_external_id: str) -> None:
    # Given: a target payload with a path-unsafe external_id
    # When: constructing CreateTargetRequest
    # Then: a validation error is raised naming external_id
    with pytest.raises(ValidationError) as exc_info:
        CreateTargetRequest(
            target_type="environment",
            external_id=bad_external_id,
        )
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("external_id",) for err in errors), (
        f"Expected external_id error for {bad_external_id!r}, got {errors}"
    )


@pytest.mark.parametrize(
    "good_external_id",
    [
        "prod-us-east",
        "3f2a18c4-0b77-4c5c-a7c4-9f7c3e5d8b12",  # UUID
        "env.prod.us_east",
        "1",
        "a" * 255,           # max length
    ],
)
def test_create_target_accepts_valid_external_id(good_external_id: str) -> None:
    # Given: a URL-safe external_id
    # When: constructing CreateTargetRequest
    # Then: no error is raised
    req = CreateTargetRequest(
        target_type="environment",
        external_id=good_external_id,
    )
    assert req.external_id == good_external_id
