"""Persistence and resolution helpers for the ``control_bindings`` table.

Each binding row attaches one control to one target inside a namespace.
Per-agent overrides and exemptions within a target are intentionally not
modeled at this stage; see ``ControlBinding`` for the documented forward
paths if and when they become a product requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from agent_control_models.controls import ControlDefinitionRuntime
from agent_control_models.errors import ErrorCode
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import BadRequestError, ConflictError, NotFoundError
from ..models import Control, ControlBinding
from .evaluator_utils import parse_evaluator_ref_full


@dataclass(frozen=True)
class ControlBindingListPage:
    """Paginated control-binding rows for list endpoints."""

    bindings: list[ControlBinding]
    total: int
    has_more: bool
    next_cursor: str | None


class ControlBindingsService:
    """Persistence and resolution helpers for control bindings."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_binding(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
        control_id: int,
        enabled: bool = True,
    ) -> ControlBinding:
        """Insert a new binding row.

        Raises ``NotFoundError`` if the referenced control does not exist in
        the same namespace, and ``ConflictError`` if a binding for the same
        ``(namespace_key, target_type, target_id, control_id)`` already
        exists.
        """
        await self._require_control(namespace_key=namespace_key, control_id=control_id)
        binding = ControlBinding(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            control_id=control_id,
            enabled=enabled,
        )
        # ``begin_nested`` opens a SAVEPOINT so a unique-constraint
        # collision rolls back only the conflicting insert. A bare
        # ``session.rollback()`` would discard every pending change in
        # the surrounding transaction, including unrelated writes from a
        # caller that composed this service after another flush.
        try:
            async with self._db.begin_nested():
                self._db.add(binding)
                await self._db.flush()
        except IntegrityError as exc:
            raise ConflictError(
                error_code=ErrorCode.CONTROL_BINDING_CONFLICT,
                detail=(
                    "A binding for this (target_type, target_id, control_id) "
                    "already exists in this namespace."
                ),
                resource="ControlBinding",
                hint="Update the existing binding instead of creating a new one.",
            ) from exc
        return binding

    async def upsert_by_natural_key(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
        control_id: int,
        enabled: bool = True,
    ) -> tuple[ControlBinding, bool]:
        """Idempotent attach by natural key.

        Returns ``(binding, created)``. If a binding for the same
        ``(namespace_key, target_type, target_id, control_id)`` already
        exists, ``enabled`` is updated to the supplied value; otherwise a
        new binding is created.

        Concurrent callers for the same natural key are handled safely: the
        loser of the unique-constraint race rolls back its insert, re-reads
        the winning row, and applies its ``enabled`` value as an update. Both
        calls return successfully; the create flag is true only for the
        caller whose insert actually wrote the row.
        """
        await self._require_control(namespace_key=namespace_key, control_id=control_id)
        existing = await self._find_by_natural_key(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            control_id=control_id,
        )
        if existing is not None:
            existing.enabled = enabled
            await self._db.flush()
            return existing, False

        binding = ControlBinding(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            control_id=control_id,
            enabled=enabled,
        )
        # ``begin_nested`` opens a SAVEPOINT so a unique-constraint
        # collision rolls back only the conflicting insert. A bare
        # ``session.rollback()`` would discard every pending change in
        # the surrounding transaction, including unrelated writes from a
        # caller that composed this service after another flush.
        try:
            async with self._db.begin_nested():
                self._db.add(binding)
                await self._db.flush()
            return binding, True
        except IntegrityError:
            # Concurrent insert won the natural-key race. Re-read the
            # winning row and apply the requested enabled value; the
            # surrounding transaction is intact because the rollback was
            # scoped to the savepoint above.
            existing = await self._find_by_natural_key(
                namespace_key=namespace_key,
                target_type=target_type,
                target_id=target_id,
                control_id=control_id,
            )
            if existing is None:
                raise
            existing.enabled = enabled
            await self._db.flush()
            return existing, False

    async def delete_by_natural_key(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
        control_id: int,
    ) -> bool:
        """Idempotent detach by natural key. Returns whether a row was deleted."""
        existing = await self._find_by_natural_key(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            control_id=control_id,
        )
        if existing is None:
            return False
        await self._db.delete(existing)
        await self._db.flush()
        return True

    async def set_enabled_by_natural_key(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
        control_id: int,
        enabled: bool,
    ) -> ControlBinding:
        """Update an existing binding by natural key.

        Unlike ``upsert_by_natural_key``, this never creates a binding.
        It is intended for target-scoped callers that need to toggle an
        already-attached control while preserving a clear 404 for missing
        attachments.
        """
        existing = await self._find_by_natural_key(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            control_id=control_id,
        )
        if existing is None:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_BINDING_NOT_FOUND,
                detail=(
                    "Control binding not found for the supplied "
                    "(target_type, target_id, control_id)."
                ),
                resource="ControlBinding",
                hint=(
                    "Verify the target and control IDs, or attach the control "
                    "before updating the binding."
                ),
            )
        existing.enabled = enabled
        await self._db.flush()
        return existing

    async def _find_by_natural_key(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
        control_id: int,
    ) -> ControlBinding | None:
        stmt = select(ControlBinding).where(
            ControlBinding.namespace_key == namespace_key,
            ControlBinding.target_type == target_type,
            ControlBinding.target_id == target_id,
            ControlBinding.control_id == control_id,
        )
        result = await self._db.execute(stmt)
        return cast(ControlBinding | None, result.scalars().first())

    async def get_binding_or_404(self, *, namespace_key: str, binding_id: int) -> ControlBinding:
        """Load a binding row scoped to ``namespace_key`` or raise 404."""
        stmt = select(ControlBinding).where(
            ControlBinding.id == binding_id,
            ControlBinding.namespace_key == namespace_key,
        )
        result = await self._db.execute(stmt)
        binding = cast(ControlBinding | None, result.scalars().first())
        if binding is None:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_BINDING_NOT_FOUND,
                detail=f"Control binding with ID '{binding_id}' not found",
                resource="ControlBinding",
                resource_id=str(binding_id),
                hint="Verify the binding ID and that it belongs to this namespace.",
            )
        return binding

    async def list_bindings(
        self,
        *,
        namespace_key: str,
        cursor: int | None = None,
        limit: int = 20,
        target_type: str | None = None,
        target_id: str | None = None,
        control_id: int | None = None,
    ) -> ControlBindingListPage:
        """List bindings scoped to ``namespace_key`` with optional filters and
        cursor-based pagination.

        Bindings are returned ordered by ID descending (newest first). Pass
        the ``next_cursor`` returned from one page as ``cursor`` to fetch the
        next page.
        """

        def _apply_filters(stmt):  # type: ignore[no-untyped-def]
            stmt = stmt.where(ControlBinding.namespace_key == namespace_key)
            if target_type is not None:
                stmt = stmt.where(ControlBinding.target_type == target_type)
            if target_id is not None:
                stmt = stmt.where(ControlBinding.target_id == target_id)
            if control_id is not None:
                stmt = stmt.where(ControlBinding.control_id == control_id)
            return stmt

        page_stmt = _apply_filters(select(ControlBinding)).order_by(ControlBinding.id.desc())
        if cursor is not None:
            page_stmt = page_stmt.where(ControlBinding.id < cursor)
        result = await self._db.execute(page_stmt.limit(limit + 1))
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        next_cursor = str(rows[-1].id) if has_more and rows else None

        total_stmt = _apply_filters(select(func.count()).select_from(ControlBinding))
        total_result = await self._db.execute(total_stmt)
        total = int(total_result.scalar_one())

        return ControlBindingListPage(
            bindings=rows,
            total=total,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def set_enabled(
        self, *, namespace_key: str, binding_id: int, enabled: bool
    ) -> ControlBinding:
        """Update the ``enabled`` flag on a single binding."""
        binding = await self.get_binding_or_404(namespace_key=namespace_key, binding_id=binding_id)
        binding.enabled = enabled
        await self._db.flush()
        return binding

    async def delete_binding(self, *, namespace_key: str, binding_id: int) -> None:
        """Delete a single binding. Raises 404 if it does not exist."""
        binding = await self.get_binding_or_404(namespace_key=namespace_key, binding_id=binding_id)
        await self._db.delete(binding)
        await self._db.flush()

    async def list_binding_ids_for_control(
        self, *, namespace_key: str, control_id: int
    ) -> list[int]:
        """Return binding IDs that reference a single control."""
        stmt = select(ControlBinding.id).where(
            ControlBinding.namespace_key == namespace_key,
            ControlBinding.control_id == control_id,
        )
        result = await self._db.execute(stmt)
        return list(result.scalars())

    async def delete_bindings_for_control(
        self, *, namespace_key: str, control_id: int
    ) -> list[int]:
        """Delete every binding referencing a control. Returns the deleted binding IDs."""
        binding_ids = await self.list_binding_ids_for_control(
            namespace_key=namespace_key, control_id=control_id
        )
        if not binding_ids:
            return []
        await self._db.execute(
            delete(ControlBinding).where(
                ControlBinding.namespace_key == namespace_key,
                ControlBinding.control_id == control_id,
            )
        )
        await self._db.flush()
        return binding_ids

    async def _require_control(self, *, namespace_key: str, control_id: int) -> None:
        """Require an active control in this namespace, eligible for target binding.

        Bindings attach a control to a target ``(target_type, target_id)``,
        so the control must be runnable against any agent that later
        evaluates against that target. Agent-scoped evaluators
        (``agent_name:evaluator_name``) are tied to a specific agent's
        registered evaluator set, so a control referencing one cannot be
        validated at binding time without choosing an agent. Reject those
        controls here so the misuse surfaces as a clear 400 instead of a
        runtime evaluation failure.
        """
        stmt = select(Control.id, Control.name, Control.data).where(
            Control.id == control_id,
            Control.namespace_key == namespace_key,
            Control.deleted_at.is_(None),
        )
        result = await self._db.execute(stmt)
        row = result.first()
        if row is None:
            raise NotFoundError(
                error_code=ErrorCode.CONTROL_NOT_FOUND,
                detail=f"Control with ID '{control_id}' not found",
                resource="Control",
                resource_id=str(control_id),
                hint=(
                    "Verify the control ID, that it has not been deleted, "
                    "and that it belongs to the same namespace as the binding."
                ),
            )

        _, control_name, control_data = row
        agent_scoped_refs = _agent_scoped_evaluators(control_data)
        if agent_scoped_refs:
            raise BadRequestError(
                error_code=ErrorCode.CONTROL_BINDING_INCOMPATIBLE,
                detail=(
                    f"Control '{control_name}' references agent-scoped "
                    f"evaluator(s) {sorted(agent_scoped_refs)!r} and cannot "
                    f"be attached to a target binding."
                ),
                hint=(
                    "Use a control whose evaluators are all global (built-in "
                    "or external), or attach this control directly to the "
                    "specific agent that registered the evaluator."
                ),
            )


def _agent_scoped_evaluators(control_data: object) -> set[str]:
    """Return the set of agent-scoped evaluator references in a control.

    Returns an empty set for unrendered template controls (no condition
    tree yet) and for any control whose stored data fails to parse —
    parse-failure validation is the responsibility of control creation,
    not target binding.
    """
    if not isinstance(control_data, dict):
        return set()
    if control_data.get("template") is not None and control_data.get("condition") is None:
        return set()
    try:
        definition = ControlDefinitionRuntime.model_validate(control_data)
    except ValidationError:
        return set()
    refs: set[str] = set()
    for _, evaluator_cfg in definition.iter_condition_leaf_parts():
        if parse_evaluator_ref_full(evaluator_cfg.name).type == "agent":
            refs.add(evaluator_cfg.name)
    return refs
