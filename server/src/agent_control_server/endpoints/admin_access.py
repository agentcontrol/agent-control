"""Admin-only user, credential, and user-owned control-grant management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from agent_control_models.errors import ErrorCode
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_framework import Operation, Principal, require_operation
from ..db import get_async_db
from ..errors import APIValidationError, ConflictError, NotFoundError
from ..models import AccessUser, AccessUserControlGrant, APIKeyCredential, Control
from ..services.access import generate_api_key

router = APIRouter(prefix="/admin/access", tags=["admin-access"])

AccessRole = Literal["admin", "member"]


class CreateAccessUserRequest(BaseModel):
    """Create a user and its first API key in one transaction."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    role: AccessRole = "member"
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class UpdateAccessUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: AccessRole | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class AccessUserResponse(BaseModel):
    id: str
    name: str
    role: AccessRole
    enabled: bool
    created_at: datetime


class AccessUserListResponse(BaseModel):
    users: list[AccessUserResponse]


class CredentialRequest(BaseModel):
    """Optional settings for issuing or rotating the user's only active key."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        if value <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        return value


class APIKeyResponse(BaseModel):
    id: str
    user_id: str
    name: str
    key_prefix: str
    enabled: bool
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class APIKeyListResponse(BaseModel):
    """Credential audit history; plaintext secrets are never returned."""

    api_keys: list[APIKeyResponse]


class CredentialSecretResponse(BaseModel):
    api_key: APIKeyResponse
    secret: str


class CreateAccessUserResponse(BaseModel):
    user: AccessUserResponse
    api_key: APIKeyResponse
    secret: str


class ReplaceAccessUserGrantsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(default_factory=list)


class AccessUserGrantResponse(BaseModel):
    user_id: str
    control_ids: list[int]


def _user_response(user: AccessUser) -> AccessUserResponse:
    return AccessUserResponse(
        id=user.id,
        name=user.name,
        role=user.role,  # type: ignore[arg-type]
        enabled=user.enabled,
        created_at=user.created_at,
    )


def _key_response(key: APIKeyCredential) -> APIKeyResponse:
    return APIKeyResponse(
        id=key.id,
        user_id=key.user_id,
        name=key.name,
        key_prefix=key.key_prefix,
        enabled=key.enabled,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


async def _get_user_or_404(
    db: AsyncSession,
    *,
    namespace_key: str,
    user_id: str,
    for_update: bool = False,
) -> AccessUser:
    statement = select(AccessUser).where(
        AccessUser.namespace_key == namespace_key,
        AccessUser.id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError(
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            detail="Access user was not found.",
            resource="AccessUser",
            resource_id=user_id,
        )
    return user


async def _live_credential(
    db: AsyncSession,
    *,
    namespace_key: str,
    user_id: str,
    for_update: bool = False,
) -> APIKeyCredential | None:
    statement = select(APIKeyCredential).where(
        APIKeyCredential.namespace_key == namespace_key,
        APIKeyCredential.user_id == user_id,
        APIKeyCredential.enabled.is_(True),
        APIKeyCredential.revoked_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


def _new_credential(
    *,
    namespace_key: str,
    user: AccessUser,
    body: CredentialRequest | None = None,
) -> tuple[APIKeyCredential, str]:
    secret, key_prefix, key_hash = generate_api_key()
    key = APIKeyCredential(
        namespace_key=namespace_key,
        user_id=user.id,
        name=(body.name.strip() if body and body.name else f"{user.name} access"),
        key_prefix=key_prefix,
        key_hash=key_hash,
        expires_at=body.expires_at if body else None,
    )
    return key, secret


def _revoke(key: APIKeyCredential, *, now: datetime) -> None:
    key.enabled = False
    if key.revoked_at is None:
        key.revoked_at = now


async def _commit_credential_change(
    db: AsyncSession,
    *,
    conflict_detail: str,
) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail=conflict_detail,
            resource="APIKeyCredential",
        ) from exc


@router.get("/users", response_model=AccessUserListResponse)
async def list_access_users(
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> AccessUserListResponse:
    result = await db.execute(
        select(AccessUser)
        .where(AccessUser.namespace_key == principal.namespace_key)
        .order_by(AccessUser.name, AccessUser.id)
    )
    return AccessUserListResponse(users=[_user_response(user) for user in result.scalars()])


@router.post(
    "/users",
    response_model=CreateAccessUserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_access_user(
    body: CreateAccessUserRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> CreateAccessUserResponse:
    user = AccessUser(
        namespace_key=principal.namespace_key,
        name=body.name.strip(),
        role=body.role,
        enabled=body.enabled,
    )
    db.add(user)
    try:
        await db.flush()
        key, secret = _new_credential(namespace_key=principal.namespace_key, user=user)
        db.add(key)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="An access user with this name already exists.",
            resource="AccessUser",
        ) from exc
    await db.refresh(user)
    await db.refresh(key)
    return CreateAccessUserResponse(
        user=_user_response(user),
        api_key=_key_response(key),
        secret=secret,
    )


@router.patch("/users/{user_id}", response_model=AccessUserResponse)
async def update_access_user(
    user_id: str,
    body: UpdateAccessUserRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> AccessUserResponse:
    user = await _get_user_or_404(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    for field_name, value in updates.items():
        setattr(user, field_name, value.strip() if field_name == "name" else value)
    if updates.get("role") == "admin":
        await db.execute(
            delete(AccessUserControlGrant).where(
                AccessUserControlGrant.namespace_key == principal.namespace_key,
                AccessUserControlGrant.user_id == user_id,
            )
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="An access user with this name already exists.",
            resource="AccessUser",
        ) from exc
    await db.refresh(user)
    return _user_response(user)


@router.get("/users/{user_id}/api-keys", response_model=APIKeyListResponse)
async def list_api_keys(
    user_id: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> APIKeyListResponse:
    """Return credential audit history, newest first, without secrets."""

    await _get_user_or_404(db, namespace_key=principal.namespace_key, user_id=user_id)
    result = await db.execute(
        select(APIKeyCredential)
        .where(
            APIKeyCredential.namespace_key == principal.namespace_key,
            APIKeyCredential.user_id == user_id,
        )
        .order_by(APIKeyCredential.created_at.desc(), APIKeyCredential.id.desc())
    )
    return APIKeyListResponse(api_keys=[_key_response(key) for key in result.scalars()])


@router.post(
    "/users/{user_id}/api-key",
    response_model=CredentialSecretResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_api_key(
    user_id: str,
    body: CredentialRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> CredentialSecretResponse:
    """Issue a key only when the user does not already have an active one."""

    user = await _get_user_or_404(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    current = await _live_credential(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    now = datetime.now(UTC)
    if current is not None and (current.expires_at is None or current.expires_at > now):
        raise ConflictError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="This user already has an active API key. Rotate it instead.",
            resource="APIKeyCredential",
            resource_id=current.id,
        )
    if current is not None:
        _revoke(current, now=now)
        await db.flush()
    key, secret = _new_credential(
        namespace_key=principal.namespace_key,
        user=user,
        body=body,
    )
    db.add(key)
    await _commit_credential_change(
        db,
        conflict_detail="API key issuance conflicted with another request. Reload and try again.",
    )
    await db.refresh(key)
    return CredentialSecretResponse(api_key=_key_response(key), secret=secret)


@router.post(
    "/users/{user_id}/api-key/rotate",
    response_model=CredentialSecretResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_api_key(
    user_id: str,
    body: CredentialRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> CredentialSecretResponse:
    """Atomically revoke the current key and issue its replacement."""

    user = await _get_user_or_404(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    current = await _live_credential(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    if current is None:
        raise ConflictError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="This user has no active API key. Issue a key instead.",
            resource="APIKeyCredential",
        )
    _revoke(current, now=datetime.now(UTC))
    await db.flush()
    replacement_body = body
    if body.name is None:
        replacement_body = body.model_copy(update={"name": current.name})
    key, secret = _new_credential(
        namespace_key=principal.namespace_key,
        user=user,
        body=replacement_body,
    )
    db.add(key)
    await _commit_credential_change(
        db,
        conflict_detail="API key rotation conflicted with another request. Reload and try again.",
    )
    await db.refresh(key)
    return CredentialSecretResponse(api_key=_key_response(key), secret=secret)


@router.delete("/users/{user_id}/api-key", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    user_id: str,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> None:
    """Revoke the user's current key; repeated revocation is idempotent."""

    await _get_user_or_404(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    current = await _live_credential(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    if current is not None:
        _revoke(current, now=datetime.now(UTC))
        await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/users/{user_id}/control-grants", response_model=AccessUserGrantResponse)
async def get_access_user_grants(
    user_id: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> AccessUserGrantResponse:
    await _get_user_or_404(db, namespace_key=principal.namespace_key, user_id=user_id)
    result = await db.execute(
        select(AccessUserControlGrant.control_id)
        .where(
            AccessUserControlGrant.namespace_key == principal.namespace_key,
            AccessUserControlGrant.user_id == user_id,
        )
        .order_by(AccessUserControlGrant.control_id)
    )
    return AccessUserGrantResponse(user_id=user_id, control_ids=list(result.scalars()))


@router.put("/users/{user_id}/control-grants", response_model=AccessUserGrantResponse)
async def replace_access_user_grants(
    user_id: str,
    body: ReplaceAccessUserGrantsRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> AccessUserGrantResponse:
    user = await _get_user_or_404(
        db,
        namespace_key=principal.namespace_key,
        user_id=user_id,
        for_update=True,
    )
    if user.role == "admin":
        raise APIValidationError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="Administrators are namespace-wide and cannot receive bucket grants.",
            resource="AccessUser",
            resource_id=user_id,
            hint="Create a member user for bucket-scoped SDK and Monitor access.",
        )
    requested_ids = sorted(set(body.control_ids))
    if requested_ids:
        result = await db.execute(
            select(Control.id).where(
                Control.namespace_key == principal.namespace_key,
                Control.id.in_(requested_ids),
                Control.deleted_at.is_(None),
            )
        )
        existing_ids = set(result.scalars())
        missing_ids = sorted(set(requested_ids) - existing_ids)
        if missing_ids:
            raise APIValidationError(
                error_code=ErrorCode.CONTROL_NOT_FOUND,
                detail="One or more requested controls do not exist in this namespace.",
                resource="Control",
                hint=f"Remove unknown control IDs: {missing_ids}",
            )

    await db.execute(
        delete(AccessUserControlGrant).where(
            AccessUserControlGrant.namespace_key == principal.namespace_key,
            AccessUserControlGrant.user_id == user_id,
        )
    )
    db.add_all(
        [
            AccessUserControlGrant(
                namespace_key=principal.namespace_key,
                user_id=user_id,
                control_id=control_id,
            )
            for control_id in requested_ids
        ]
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="Rule bucket assignments changed concurrently. Reload and try again.",
            resource="AccessUser",
            resource_id=user_id,
        ) from exc
    return AccessUserGrantResponse(user_id=user_id, control_ids=requested_ids)
