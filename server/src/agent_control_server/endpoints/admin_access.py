"""Admin-only user, API-key, and control-grant management endpoints."""

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
from ..models import (
    AccessUser,
    APIKeyControlGrant,
    APIKeyCredential,
    Control,
)
from ..services.access import generate_api_key

router = APIRouter(prefix="/admin/access", tags=["admin-access"])

AccessRole = Literal["admin", "member"]


class CreateAccessUserRequest(BaseModel):
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


class CreateAPIKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    expires_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
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
    api_keys: list[APIKeyResponse]


class CreateAPIKeyResponse(BaseModel):
    api_key: APIKeyResponse
    secret: str


class ReplaceAPIKeyGrantsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_ids: list[Annotated[int, Field(strict=True, gt=0)]] = Field(default_factory=list)


class APIKeyGrantResponse(BaseModel):
    api_key_id: str
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


async def _get_user_or_404(db: AsyncSession, *, namespace_key: str, user_id: str) -> AccessUser:
    result = await db.execute(
        select(AccessUser).where(
            AccessUser.namespace_key == namespace_key,
            AccessUser.id == user_id,
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError(
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            detail="Access user was not found.",
            resource="AccessUser",
            resource_id=user_id,
        )
    return user


async def _get_key_or_404(
    db: AsyncSession, *, namespace_key: str, api_key_id: str
) -> APIKeyCredential:
    result = await db.execute(
        select(APIKeyCredential).where(
            APIKeyCredential.namespace_key == namespace_key,
            APIKeyCredential.id == api_key_id,
        )
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise NotFoundError(
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
            detail="API key was not found.",
            resource="APIKeyCredential",
            resource_id=api_key_id,
        )
    return key


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


@router.post("/users", response_model=AccessUserResponse, status_code=status.HTTP_201_CREATED)
async def create_access_user(
    body: CreateAccessUserRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> AccessUserResponse:
    user = AccessUser(
        namespace_key=principal.namespace_key,
        name=body.name.strip(),
        role=body.role,
        enabled=body.enabled,
    )
    db.add(user)
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


@router.patch("/users/{user_id}", response_model=AccessUserResponse)
async def update_access_user(
    user_id: str,
    body: UpdateAccessUserRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> AccessUserResponse:
    user = await _get_user_or_404(db, namespace_key=principal.namespace_key, user_id=user_id)
    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field_name, value.strip() if field_name == "name" else value)
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
    await _get_user_or_404(db, namespace_key=principal.namespace_key, user_id=user_id)
    result = await db.execute(
        select(APIKeyCredential)
        .where(
            APIKeyCredential.namespace_key == principal.namespace_key,
            APIKeyCredential.user_id == user_id,
        )
        .order_by(APIKeyCredential.created_at, APIKeyCredential.id)
    )
    return APIKeyListResponse(api_keys=[_key_response(key) for key in result.scalars()])


@router.post(
    "/users/{user_id}/api-keys",
    response_model=CreateAPIKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    user_id: str,
    body: CreateAPIKeyRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> CreateAPIKeyResponse:
    await _get_user_or_404(db, namespace_key=principal.namespace_key, user_id=user_id)
    secret, key_prefix, key_hash = generate_api_key()
    key = APIKeyCredential(
        namespace_key=principal.namespace_key,
        user_id=user_id,
        name=body.name.strip(),
        key_prefix=key_prefix,
        key_hash=key_hash,
        expires_at=body.expires_at,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return CreateAPIKeyResponse(api_key=_key_response(key), secret=secret)


@router.delete("/api-keys/{api_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    api_key_id: str,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> None:
    key = await _get_key_or_404(db, namespace_key=principal.namespace_key, api_key_id=api_key_id)
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
    key.enabled = False
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT


@router.get("/api-keys/{api_key_id}/control-grants", response_model=APIKeyGrantResponse)
async def get_api_key_grants(
    api_key_id: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> APIKeyGrantResponse:
    await _get_key_or_404(db, namespace_key=principal.namespace_key, api_key_id=api_key_id)
    result = await db.execute(
        select(APIKeyControlGrant.control_id)
        .where(
            APIKeyControlGrant.namespace_key == principal.namespace_key,
            APIKeyControlGrant.api_key_id == api_key_id,
        )
        .order_by(APIKeyControlGrant.control_id)
    )
    return APIKeyGrantResponse(api_key_id=api_key_id, control_ids=list(result.scalars()))


@router.put("/api-keys/{api_key_id}/control-grants", response_model=APIKeyGrantResponse)
async def replace_api_key_grants(
    api_key_id: str,
    body: ReplaceAPIKeyGrantsRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.ACCESS_MANAGE)),
) -> APIKeyGrantResponse:
    await _get_key_or_404(db, namespace_key=principal.namespace_key, api_key_id=api_key_id)
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
        delete(APIKeyControlGrant).where(
            APIKeyControlGrant.namespace_key == principal.namespace_key,
            APIKeyControlGrant.api_key_id == api_key_id,
        )
    )
    db.add_all(
        [
            APIKeyControlGrant(
                namespace_key=principal.namespace_key,
                api_key_id=api_key_id,
                control_id=control_id,
            )
            for control_id in requested_ids
        ]
    )
    await db.commit()
    return APIKeyGrantResponse(api_key_id=api_key_id, control_ids=requested_ids)
