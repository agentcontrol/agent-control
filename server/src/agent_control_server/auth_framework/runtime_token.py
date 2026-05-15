"""Runtime-token mint and verify helpers.

The runtime auth flow is two-phase:

1. **Exchange.** A target-bearing call presents a long-lived credential
   (e.g., an API key) plus ``(target_type, target_id)``. The server
   forwards the credential to an upstream authorization service which
   either denies the request or returns a normalized grant
   (``actor_id``, ``scopes``, ``target_type``, ``target_id``,
   ``expires_at``). The server then mints a short-lived local token
   stamped with those claims.
2. **Verify.** Subsequent target-bearing calls present the local token
   on the request. The server verifies the signature, the expiry, the
   ``runtime`` domain marker, and the scope; the resolved
   :class:`Principal` carries the bound target.

Token rules:

- Algorithm: HS256.
- Issuer: ``agent-control/server``; verifier: same.
- Signing key: dedicated secret (``AGENT_CONTROL_RUNTIME_TOKEN_SECRET``).
  Never reuse other JWT secrets.
- One token covers one target only.
- ``domain`` claim pins the token to the runtime path; tokens minted
  here MUST not be accepted on management endpoints.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

_ALGORITHM = "HS256"
_ISSUER = "agent-control/server"
_DOMAIN = "runtime"


class RuntimeTokenError(Exception):
    """Raised when a runtime token cannot be verified or minted."""


class UpstreamGrantExpiredError(RuntimeTokenError):
    """Raised when the upstream grant's ``expires_at`` is at or before
    the issuing time, so the resulting token would already be expired.

    Distinct from generic :class:`RuntimeTokenError` so the exchange
    endpoint can surface this as a 502 (upstream returned an unusable
    grant) rather than a 503 (server misconfigured).
    """


@dataclass(frozen=True)
class RuntimeTokenClaims:
    """Fields baked into a runtime token."""

    namespace_key: str
    actor_id: str
    target_type: str
    target_id: str
    scopes: tuple[str, ...]
    expires_at: datetime
    issued_at: datetime
    jti: str


def mint_runtime_token(
    *,
    namespace_key: str,
    actor_id: str,
    target_type: str,
    target_id: str,
    scopes: tuple[str, ...],
    secret: str,
    ttl_seconds: int,
    upstream_expires_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[str, RuntimeTokenClaims]:
    """Mint a runtime token. Returns ``(token, claims)``.

    The local token's expiry is the earlier of ``ttl_seconds`` from now
    and ``upstream_expires_at`` (when supplied), so the local lifetime
    can never outlive the upstream grant.
    """
    if not secret:
        raise RuntimeTokenError(
            "Runtime token secret is not configured. Set "
            "AGENT_CONTROL_RUNTIME_TOKEN_SECRET to enable runtime auth."
        )
    if not namespace_key:
        raise RuntimeTokenError("namespace_key is required to mint a runtime token")
    if not actor_id:
        raise RuntimeTokenError("actor_id is required to mint a runtime token")
    if not target_type:
        raise RuntimeTokenError("target_type is required to mint a runtime token")
    if not target_id:
        raise RuntimeTokenError("target_id is required to mint a runtime token")
    if ttl_seconds <= 0:
        raise RuntimeTokenError("ttl_seconds must be positive")
    if upstream_expires_at is not None and (
        upstream_expires_at.tzinfo is None or upstream_expires_at.utcoffset() is None
    ):
        # The HTTP-upstream parser already rejects naive datetimes, but
        # this helper has other call sites (custom authorizers, tests)
        # that can supply a naive value. Comparing it against
        # ``datetime.now(UTC)`` below would raise a raw ``TypeError``;
        # surface the misuse as a typed ``RuntimeTokenError`` instead.
        # Both ``tzinfo`` and ``utcoffset()`` are checked because a
        # custom ``tzinfo`` subclass can set the attribute but return
        # ``None`` from ``utcoffset()``, leaving comparisons broken.
        raise RuntimeTokenError(
            "upstream_expires_at must be timezone-aware "
            "(e.g., tz=UTC); naive datetimes are not supported."
        )

    issued_at = now or datetime.now(UTC)
    if upstream_expires_at is not None and upstream_expires_at <= issued_at:
        # Minting with an already-expired ``exp`` would return a 200 with
        # an unusable token; surface the timing problem here instead.
        raise UpstreamGrantExpiredError(
            "Upstream grant has already expired; cannot mint a runtime token."
        )
    candidate_expiry = issued_at + timedelta(seconds=ttl_seconds)
    if upstream_expires_at is not None and upstream_expires_at < candidate_expiry:
        expires_at = upstream_expires_at
    else:
        expires_at = candidate_expiry

    jti = secrets.token_urlsafe(16)
    payload: dict[str, Any] = {
        "iss": _ISSUER,
        "domain": _DOMAIN,
        "namespace_key": namespace_key,
        "actor_id": actor_id,
        "target_type": target_type,
        "target_id": target_id,
        "scopes": list(scopes),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    token = jwt.encode(payload, secret, algorithm=_ALGORITHM)
    claims = RuntimeTokenClaims(
        namespace_key=namespace_key,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        scopes=scopes,
        expires_at=expires_at,
        issued_at=issued_at,
        jti=jti,
    )
    return token, claims


def verify_runtime_token(token: str, secret: str) -> RuntimeTokenClaims:
    """Decode and verify a runtime token.

    Raises :class:`RuntimeTokenError` when the signature is invalid,
    the token is expired, the issuer is wrong, the domain marker is
    missing, or required claims are missing or malformed.
    """
    if not secret:
        raise RuntimeTokenError("Runtime token secret is not configured.")
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            issuer=_ISSUER,
            options={"require": ["exp", "iat", "iss", "domain"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise RuntimeTokenError("Runtime token has expired.") from exc
    except jwt.InvalidIssuerError as exc:
        raise RuntimeTokenError("Runtime token has the wrong issuer.") from exc
    except jwt.InvalidTokenError as exc:
        raise RuntimeTokenError(f"Runtime token is invalid: {exc}") from exc

    if payload.get("domain") != _DOMAIN:
        raise RuntimeTokenError("Token is not a runtime token; refusing to use it here.")

    namespace_key = payload.get("namespace_key")
    actor_id = payload.get("actor_id")
    target_type = payload.get("target_type")
    target_id = payload.get("target_id")
    if not isinstance(namespace_key, str) or not namespace_key:
        raise RuntimeTokenError("Runtime token missing namespace_key.")
    if not isinstance(actor_id, str) or not actor_id:
        raise RuntimeTokenError("Runtime token missing actor_id.")
    if not isinstance(target_type, str) or not target_type:
        raise RuntimeTokenError("Runtime token missing target_type.")
    if not isinstance(target_id, str) or not target_id:
        raise RuntimeTokenError("Runtime token missing target_id.")

    raw_scopes = payload.get("scopes", [])
    if not isinstance(raw_scopes, list) or not all(isinstance(s, str) for s in raw_scopes):
        raise RuntimeTokenError("Runtime token has malformed scopes.")
    scopes = tuple(raw_scopes)

    jti = payload.get("jti")
    if not isinstance(jti, str):
        jti = ""

    return RuntimeTokenClaims(
        namespace_key=namespace_key,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        scopes=scopes,
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
        jti=jti,
    )
