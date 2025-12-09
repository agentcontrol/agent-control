"""Service layer for custom evaluator CRUD operations."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_utils import get_logger
from ..models import CustomEvaluator

_logger = get_logger(__name__)


async def create_or_update_evaluator(
    name: str,
    code: str,
    config_schema: dict,
    db: AsyncSession,
    description: str | None = None,
    entrypoint: str = "evaluate",
    timeout_ms: int = 5000,
) -> CustomEvaluator:
    """Create or update a custom evaluator.

    Args:
        name: Unique evaluator name
        code: Python code with evaluate(data, config) function
        config_schema: JSON Schema for config validation
        db: Database session
        description: Optional description
        entrypoint: Function name to call (default: evaluate)
        timeout_ms: Execution timeout in milliseconds

    Returns:
        Created or updated CustomEvaluator
    """
    # Check if exists
    stmt = select(CustomEvaluator).where(CustomEvaluator.name == name)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Update
        existing.code = code
        existing.config_schema = config_schema
        existing.description = description
        existing.entrypoint = entrypoint
        existing.timeout_ms = timeout_ms
        await db.commit()
        await db.refresh(existing)
        _logger.info(f"Updated custom evaluator: {name}")
        return existing
    else:
        # Create
        evaluator = CustomEvaluator(
            name=name,
            code=code,
            config_schema=config_schema,
            description=description,
            entrypoint=entrypoint,
            timeout_ms=timeout_ms,
        )
        db.add(evaluator)
        await db.commit()
        await db.refresh(evaluator)
        _logger.info(f"Created custom evaluator: {name}")
        return evaluator


async def get_evaluator_by_name(name: str, db: AsyncSession) -> CustomEvaluator | None:
    """Get a custom evaluator by name.

    Args:
        name: Evaluator name
        db: Database session

    Returns:
        CustomEvaluator or None if not found
    """
    stmt = select(CustomEvaluator).where(CustomEvaluator.name == name)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_custom_evaluators(db: AsyncSession) -> list[CustomEvaluator]:
    """List all custom evaluators.

    Args:
        db: Database session

    Returns:
        List of CustomEvaluator
    """
    stmt = select(CustomEvaluator).order_by(CustomEvaluator.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_evaluator(name: str, db: AsyncSession) -> bool:
    """Delete a custom evaluator by name.

    Args:
        name: Evaluator name
        db: Database session

    Returns:
        True if deleted, False if not found
    """
    stmt = select(CustomEvaluator).where(CustomEvaluator.name == name)
    result = await db.execute(stmt)
    evaluator = result.scalar_one_or_none()

    if evaluator is None:
        return False

    await db.delete(evaluator)
    await db.commit()
    _logger.info(f"Deleted custom evaluator: {name}")
    return True


async def is_evaluator_in_use(name: str, db: AsyncSession) -> bool:
    """Check if a custom evaluator is referenced by any Control.

    Scans the Controls table's JSONB data for plugin references.

    Args:
        name: Evaluator name to check
        db: Database session

    Returns:
        True if evaluator is in use, False otherwise
    """
    # Query controls where data->'evaluator'->>'plugin' = name
    query = text("""
        SELECT EXISTS (
            SELECT 1 FROM controls
            WHERE data->'evaluator'->>'plugin' = :name
        )
    """)
    result = await db.execute(query, {"name": name})
    return bool(result.scalar())
