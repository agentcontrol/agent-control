import datetime as dt
from http import HTTPStatus
from typing import Any

from agent_control_engine import list_evaluators
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
    CreateEvaluatorConfigRequest,
    DeleteEvaluatorConfigResponse,
    EvaluatorConfigItem,
    ListEvaluatorConfigsResponse,
    PaginationInfo,
    UpdateEvaluatorConfigRequest,
)
from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..db import get_async_db
from ..errors import APIValidationError, ConflictError, DatabaseError, NotFoundError
from ..logging_utils import get_logger
from ..models import EvaluatorConfigDB
from ..services.evaluator_utils import is_agent_scoped
from ..services.query_utils import escape_like_pattern

_logger = get_logger(__name__)

# Pagination constants
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100
_INVALID_PARAMETERS_MESSAGE = "Invalid config parameters for evaluator."

router = APIRouter(prefix="/evaluator-configs", tags=["evaluator-configs"])


def _to_item(config: EvaluatorConfigDB) -> EvaluatorConfigItem:
    return EvaluatorConfigItem(
        id=config.id,
        name=config.name,
        description=config.description,
        evaluator=config.evaluator,
        config=config.config,
        created_at=config.created_at.isoformat() if config.created_at else None,
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


def _ensure_not_agent_scoped(evaluator: str) -> None:
    if is_agent_scoped(evaluator):
        raise APIValidationError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="Agent-scoped evaluators are not supported for evaluator configs",
            resource="EvaluatorConfig",
            hint="Use a built-in evaluator name without an agent prefix.",
            errors=[
                ValidationErrorItem(
                    resource="EvaluatorConfig",
                    field="evaluator",
                    code="agent_scoped_not_supported",
                    message="Agent-scoped evaluator references are not supported",
                    value=evaluator,
                )
            ],
        )


def _raise_invalid_config(
    errors: list[ValidationErrorItem],
    *,
    detail: str,
    hint: str,
) -> None:
    raise APIValidationError(
        error_code=ErrorCode.INVALID_CONFIG,
        detail=detail,
        resource="EvaluatorConfig",
        hint=hint,
        errors=errors,
    )


def _validate_known_evaluator_config(evaluator: str, config: dict[str, Any]) -> None:
    evaluator_cls = list_evaluators().get(evaluator)
    if evaluator_cls is None:
        return

    try:
        evaluator_cls.config_model(**config)
    except ValidationError as e:
        _raise_invalid_config(
            [
                ValidationErrorItem(
                    resource="EvaluatorConfig",
                    field=f"config.{'.'.join(str(loc) for loc in err.get('loc', []))}",
                    code=err.get("type", "validation_error"),
                    message=err.get("msg", "Validation failed"),
                )
                for err in e.errors()
            ],
            detail=f"Config validation failed for evaluator '{evaluator}'",
            hint="Check the evaluator's config schema for required fields and types.",
        )
    except TypeError:
        _logger.warning(
            "Evaluator config parameter validation raised TypeError for '%s'",
            evaluator,
            exc_info=True,
        )
        _raise_invalid_config(
            [
                ValidationErrorItem(
                    resource="EvaluatorConfig",
                    field="config",
                    code="invalid_parameters",
                    message=_INVALID_PARAMETERS_MESSAGE,
                )
            ],
            detail=f"Invalid config parameters for evaluator '{evaluator}'",
            hint="Check the evaluator's config schema for valid parameter names.",
        )


def _validate_evaluator_config(evaluator: str, config: dict[str, Any]) -> None:
    _ensure_not_agent_scoped(evaluator)
    _validate_known_evaluator_config(evaluator, config)


def _is_name_conflict_error(exc: IntegrityError) -> bool:
    orig = exc.orig
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name == "evaluator_configs_name_key":
        return True

    message = str(exc).lower()
    return (
        "unique constraint" in message
        and "evaluator_configs" in message
        and "name" in message
    )


def _raise_name_conflict(name: str) -> None:
    raise ConflictError(
        error_code=ErrorCode.EVALUATOR_CONFIG_NAME_CONFLICT,
        detail=f"Evaluator config with name '{name}' already exists",
        resource="EvaluatorConfig",
        resource_id=name,
        hint="Choose a different name or update the existing evaluator config.",
    )


@router.post(
    "",
    dependencies=[Depends(require_admin_key)],
    response_model=EvaluatorConfigItem,
    summary="Create evaluator config",
    response_description="Created evaluator config",
    status_code=HTTPStatus.CREATED,
)
async def create_evaluator_config(
    request: CreateEvaluatorConfigRequest,
    db: AsyncSession = Depends(get_async_db),
) -> EvaluatorConfigItem:
    _validate_evaluator_config(request.evaluator, request.config)

    evaluator_config = EvaluatorConfigDB(
        name=request.name,
        description=request.description,
        evaluator=request.evaluator,
        config=request.config,
    )
    db.add(evaluator_config)
    try:
        await db.commit()
        await db.refresh(evaluator_config)
    except IntegrityError as exc:
        await db.rollback()
        if _is_name_conflict_error(exc):
            _raise_name_conflict(request.name)
        _logger.error(
            "Failed to create evaluator config '%s'",
            request.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to create evaluator config '{request.name}': database error",
            resource="EvaluatorConfig",
            operation="create",
        )
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to create evaluator config '%s'",
            request.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to create evaluator config '{request.name}': database error",
            resource="EvaluatorConfig",
            operation="create",
        )

    return _to_item(evaluator_config)


@router.get(
    "",
    response_model=ListEvaluatorConfigsResponse,
    summary="List evaluator configs",
    response_description="Paginated list of evaluator configs",
)
async def list_evaluator_configs(
    cursor: int | None = Query(None, description="Evaluator config ID to start after"),
    limit: int = Query(_DEFAULT_PAGINATION_LIMIT, ge=1, le=_MAX_PAGINATION_LIMIT),
    name: str | None = Query(None, description="Filter by name (partial, case-insensitive)"),
    evaluator: str | None = Query(None, description="Filter by evaluator name"),
    db: AsyncSession = Depends(get_async_db),
) -> ListEvaluatorConfigsResponse:
    query = select(EvaluatorConfigDB).order_by(EvaluatorConfigDB.id.desc())

    if cursor is not None:
        query = query.where(EvaluatorConfigDB.id < cursor)

    if name is not None:
        query = query.where(
            EvaluatorConfigDB.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\")
        )

    if evaluator is not None:
        query = query.where(EvaluatorConfigDB.evaluator == evaluator)

    query = query.limit(limit + 1)
    result = await db.execute(query)
    configs = list(result.scalars().all())

    total_query = select(func.count()).select_from(EvaluatorConfigDB)
    if name is not None:
        total_query = total_query.where(
            EvaluatorConfigDB.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\")
        )
    if evaluator is not None:
        total_query = total_query.where(EvaluatorConfigDB.evaluator == evaluator)
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    has_more = len(configs) > limit
    if has_more:
        configs = configs[:-1]

    items = [_to_item(cfg) for cfg in configs]
    next_cursor = str(configs[-1].id) if has_more and configs else None

    return ListEvaluatorConfigsResponse(
        evaluator_configs=items,
        pagination=PaginationInfo(
            limit=limit,
            total=total,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


@router.get(
    "/{config_id}",
    response_model=EvaluatorConfigItem,
    summary="Get evaluator config",
    response_description="Evaluator config details",
)
async def get_evaluator_config(
    config_id: int, db: AsyncSession = Depends(get_async_db)
) -> EvaluatorConfigItem:
    result = await db.execute(
        select(EvaluatorConfigDB).where(EvaluatorConfigDB.id == config_id)
    )
    evaluator_config = result.scalars().first()
    if evaluator_config is None:
        raise NotFoundError(
            error_code=ErrorCode.EVALUATOR_CONFIG_NOT_FOUND,
            detail=f"Evaluator config with ID '{config_id}' not found",
            resource="EvaluatorConfig",
            resource_id=str(config_id),
            hint="Verify the evaluator config ID is correct.",
        )

    return _to_item(evaluator_config)


@router.put(
    "/{config_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=EvaluatorConfigItem,
    summary="Update evaluator config",
    response_description="Updated evaluator config",
)
async def update_evaluator_config(
    config_id: int,
    request: UpdateEvaluatorConfigRequest,
    db: AsyncSession = Depends(get_async_db),
) -> EvaluatorConfigItem:
    result = await db.execute(
        select(EvaluatorConfigDB).where(EvaluatorConfigDB.id == config_id)
    )
    evaluator_config = result.scalars().first()
    if evaluator_config is None:
        raise NotFoundError(
            error_code=ErrorCode.EVALUATOR_CONFIG_NOT_FOUND,
            detail=f"Evaluator config with ID '{config_id}' not found",
            resource="EvaluatorConfig",
            resource_id=str(config_id),
            hint="Verify the evaluator config ID is correct.",
        )

    _validate_evaluator_config(request.evaluator, request.config)

    evaluator_config.name = request.name
    evaluator_config.description = request.description
    evaluator_config.evaluator = request.evaluator
    evaluator_config.config = request.config
    evaluator_config.updated_at = dt.datetime.now(dt.UTC)

    try:
        await db.commit()
        await db.refresh(evaluator_config)
    except IntegrityError as exc:
        await db.rollback()
        if _is_name_conflict_error(exc):
            _raise_name_conflict(request.name)
        _logger.error(
            "Failed to update evaluator config '%s' (%s)",
            evaluator_config.name,
            config_id,
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to update evaluator config '{evaluator_config.name}': "
                "database error"
            ),
            resource="EvaluatorConfig",
            operation="update",
        )
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to update evaluator config '%s' (%s)",
            evaluator_config.name,
            config_id,
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to update evaluator config '{evaluator_config.name}': "
                "database error"
            ),
            resource="EvaluatorConfig",
            operation="update",
        )

    return _to_item(evaluator_config)


@router.delete(
    "/{config_id}",
    dependencies=[Depends(require_admin_key)],
    response_model=DeleteEvaluatorConfigResponse,
    summary="Delete evaluator config",
    response_description="Deletion confirmation",
    status_code=HTTPStatus.OK,
)
async def delete_evaluator_config(
    config_id: int, db: AsyncSession = Depends(get_async_db)
) -> DeleteEvaluatorConfigResponse:
    result = await db.execute(
        select(EvaluatorConfigDB).where(EvaluatorConfigDB.id == config_id)
    )
    evaluator_config = result.scalars().first()
    if evaluator_config is None:
        raise NotFoundError(
            error_code=ErrorCode.EVALUATOR_CONFIG_NOT_FOUND,
            detail=f"Evaluator config with ID '{config_id}' not found",
            resource="EvaluatorConfig",
            resource_id=str(config_id),
            hint="Verify the evaluator config ID is correct.",
        )

    await db.delete(evaluator_config)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to delete evaluator config '%s' (%s)",
            evaluator_config.name,
            config_id,
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to delete evaluator config '{evaluator_config.name}': "
                "database error"
            ),
            resource="EvaluatorConfig",
            operation="delete",
        )

    return DeleteEvaluatorConfigResponse(success=True)
