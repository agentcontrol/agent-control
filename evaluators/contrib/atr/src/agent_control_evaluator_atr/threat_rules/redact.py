"""
Match-value redaction utility — Python port of the same helper that ships
in ATR upstream (``agent-threat-rules@2.1.2`` ``src/redact.ts``).

Per @lan17's 2026-04-26 review on PR #170: the previous evaluator metadata
embedded ``matched_text[:200]`` directly, which re-exposes the very secrets
that a rule fires on (AWS access keys, GitHub tokens, OAuth credentials).
The fix is to never return raw matched values from this evaluator; instead,
every match is run through :func:`redact_matched_value` and only the
triage-safe summary surfaces in the ``EvaluatorResult.metadata``.

The output records:

  * recognised secret class (when known)
  * leading 4 bytes of the match (configurable via ``head_bytes``)
  * original length

…and nothing else. Output is capped at 80 characters by default.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Tuple


# Ordered prefix → label table. The first match wins.
_SECRET_PREFIXES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^AKIA[A-Z0-9]"), "aws_access_key_id"),
    (re.compile(r"^ASIA[A-Z0-9]"), "aws_session_credential"),
    (re.compile(r"^AGPA[A-Z0-9]"), "aws_user_identity"),
    (re.compile(r"^ghp_[A-Za-z0-9]"), "github_personal_token"),
    (re.compile(r"^gho_[A-Za-z0-9]"), "github_oauth_token"),
    (re.compile(r"^ghs_[A-Za-z0-9]"), "github_server_token"),
    (re.compile(r"^ghu_[A-Za-z0-9]"), "github_user_token"),
    (re.compile(r"^ghr_[A-Za-z0-9]"), "github_refresh_token"),
    (re.compile(r"^xox[abprs]-"), "slack_token"),
    (re.compile(r"^xoxe-"), "slack_external_token"),
    (re.compile(r"^sk-ant-[A-Za-z0-9_]"), "anthropic_secret"),
    (re.compile(r"^sk-[A-Za-z0-9_]"), "openai_or_compatible_secret"),
    (re.compile(r"^Bearer\s+", re.IGNORECASE), "bearer_credential"),
    (re.compile(r"^-----BEGIN [A-Z ]+PRIVATE KEY-----"), "pem_private_key"),
    (re.compile(r"^eyJ[A-Za-z0-9_-]"), "jwt_or_jose"),
)


_DEFAULT_HEAD_BYTES = 4
_MAX_REDACTED_OUTPUT = 80


def redact_matched_value(
    value: str,
    *,
    head_bytes: int = _DEFAULT_HEAD_BYTES,
    max_length: int = _MAX_REDACTED_OUTPUT,
) -> str:
    """
    Replace a raw matched value with a triage-safe summary.

    The output never contains more than ``head_bytes`` (default 4) of the
    original value. The remainder is replaced with a structured placeholder
    that records the recognised secret class (when known), the original
    length, and an elision marker.
    """
    if not isinstance(value, str):
        return "[redacted:non-string]"
    if not value:
        return "[redacted:empty]"

    head_bytes = max(0, head_bytes)
    max_length = max(8, max_length)

    trimmed = value.strip()
    secret_class = None
    for pattern, label in _SECRET_PREFIXES:
        if pattern.match(trimmed):
            secret_class = label
            break

    head = value[:head_bytes]
    length = len(value)
    if secret_class is not None:
        summary = f'[redacted:{secret_class} head="{head}" len={length}]'
    else:
        summary = f'[redacted head="{head}" len={length}]'

    if len(summary) <= max_length:
        return summary
    return summary[: max_length - 1] + "]"


def redact_matched_values(values: Iterable[str], **kwargs) -> List[str]:
    """Apply :func:`redact_matched_value` to every entry of an iterable."""
    return [redact_matched_value(v, **kwargs) for v in values]
