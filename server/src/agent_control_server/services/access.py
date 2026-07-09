"""Credential generation and database-backed identity resolution."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import AsyncSessionLocal
from ..models import AccessUser, APIKeyControlGrant, APIKeyCredential


@dataclass(frozen=True)
class CredentialIdentity:
    """Stable identity and authorization scope resolved from a database key."""

    user_id: str
    api_key_id: str
    namespace_key: str
    is_admin: bool
    allowed_control_ids: frozenset[int] | None
    key_prefix: str


def hash_api_key(raw_key: str) -> str:
    """Return the one-way digest stored for a high-entropy API key."""

    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Generate a key and return ``(plaintext, display_prefix, digest)``."""

    plaintext = f"ac_{secrets.token_urlsafe(32)}"
    return plaintext, plaintext[:12], hash_api_key(plaintext)


def _active_credential_statement() -> Select[tuple[APIKeyCredential, AccessUser]]:
    return (
        select(APIKeyCredential, AccessUser)
        .join(
            AccessUser,
            (AccessUser.namespace_key == APIKeyCredential.namespace_key)
            & (AccessUser.id == APIKeyCredential.user_id),
        )
        .where(
            APIKeyCredential.enabled.is_(True),
            APIKeyCredential.revoked_at.is_(None),
            or_(
                APIKeyCredential.expires_at.is_(None),
                APIKeyCredential.expires_at > func.now(),
            ),
            AccessUser.enabled.is_(True),
        )
    )


async def _identity_from_rows(
    db: AsyncSession,
    credential: APIKeyCredential,
    user: AccessUser,
) -> CredentialIdentity:
    is_admin = user.role == "admin"
    allowed_control_ids: frozenset[int] | None = None
    if not is_admin:
        result = await db.execute(
            select(APIKeyControlGrant.control_id).where(
                APIKeyControlGrant.namespace_key == credential.namespace_key,
                APIKeyControlGrant.api_key_id == credential.id,
            )
        )
        allowed_control_ids = frozenset(result.scalars().all())

    return CredentialIdentity(
        user_id=user.id,
        api_key_id=credential.id,
        namespace_key=credential.namespace_key,
        is_admin=is_admin,
        allowed_control_ids=allowed_control_ids,
        key_prefix=credential.key_prefix,
    )


async def authenticate_database_api_key(raw_key: str) -> CredentialIdentity | None:
    """Resolve an active database key without ever loading stored plaintext."""

    digest = hash_api_key(raw_key)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            _active_credential_statement().where(APIKeyCredential.key_hash == digest)
        )
        row = result.first()
        if row is None:
            return None
        credential, user = row
        return await _identity_from_rows(db, credential, user)


async def resolve_database_credential(
    api_key_id: str,
    *,
    expected_user_id: str | None = None,
) -> CredentialIdentity | None:
    """Re-resolve a cookie credential so revocation and grant changes are immediate."""

    async with AsyncSessionLocal() as db:
        statement = _active_credential_statement().where(APIKeyCredential.id == api_key_id)
        if expected_user_id is not None:
            statement = statement.where(APIKeyCredential.user_id == expected_user_id)
        result = await db.execute(statement)
        row = result.first()
        if row is None:
            return None
        credential, user = row
        return await _identity_from_rows(db, credential, user)


async def database_has_active_credentials() -> bool:
    """Return whether at least one active DB credential can authenticate."""

    async with AsyncSessionLocal() as db:
        result = await db.execute(_active_credential_statement().limit(1))
        return result.first() is not None
