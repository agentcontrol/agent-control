"""Persistence and resolution helpers for the ``control_bindings`` table.

Each binding row attaches one control to one target inside a namespace.
Per-agent overrides and exemptions within a target are intentionally not
modeled at this stage; see ``ControlBinding`` for the documented forward
paths if and when they become a product requirement.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from agent_control_models.errors import ErrorCode
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ConflictError, NotFoundError
from ..models import Control, ControlBinding
from .controls import RuntimeControl, parse_runtime_controls


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
        await self._require_control(
            namespace_key=namespace_key, control_id=control_id
        )
        binding = ControlBinding(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            control_id=control_id,
            enabled=enabled,
        )
        self._db.add(binding)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
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
        """
        await self._require_control(
            namespace_key=namespace_key, control_id=control_id
        )
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
        self._db.add(binding)
        await self._db.flush()
        return binding, True

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

    async def get_binding_or_404(
        self, *, namespace_key: str, binding_id: int
    ) -> ControlBinding:
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
        target_type: str | None = None,
        target_id: str | None = None,
        control_id: int | None = None,
    ) -> list[ControlBinding]:
        """List bindings scoped to ``namespace_key`` with optional filters."""
        stmt = select(ControlBinding).where(
            ControlBinding.namespace_key == namespace_key
        )
        if target_type is not None:
            stmt = stmt.where(ControlBinding.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(ControlBinding.target_id == target_id)
        if control_id is not None:
            stmt = stmt.where(ControlBinding.control_id == control_id)
        stmt = stmt.order_by(ControlBinding.id)
        result = await self._db.execute(stmt)
        return list(result.scalars())

    async def set_enabled(
        self, *, namespace_key: str, binding_id: int, enabled: bool
    ) -> ControlBinding:
        """Update the ``enabled`` flag on a single binding."""
        binding = await self.get_binding_or_404(
            namespace_key=namespace_key, binding_id=binding_id
        )
        binding.enabled = enabled
        await self._db.flush()
        return binding

    async def delete_binding(
        self, *, namespace_key: str, binding_id: int
    ) -> None:
        """Delete a single binding. Raises 404 if it does not exist."""
        binding = await self.get_binding_or_404(
            namespace_key=namespace_key, binding_id=binding_id
        )
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

    async def resolve_runtime_controls(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
        allow_invalid_step_name_regex: bool = False,
    ) -> list[RuntimeControl]:
        """Return runtime-parsed effective controls for a target-bearing request.

        Same selection logic as :meth:`resolve_effective_controls`; the
        returned controls are parsed into the form used by the evaluation
        engine.
        """
        controls = await self.resolve_effective_controls(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
        )
        return parse_runtime_controls(
            controls,
            allow_invalid_step_name_regex=allow_invalid_step_name_regex,
        )

    async def resolve_effective_controls(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
    ) -> list[Control]:
        """Return the effective set of active controls for a target-bearing request.

        Returns every active (not soft-deleted) control attached to the target
        whose binding has ``enabled = True``. ``enabled = False`` excludes the
        control. Soft-deleted controls (``deleted_at IS NOT NULL``) are
        filtered out.

        Per-agent narrowing is intentionally out of scope at this stage; the
        resolver returns the full target-level set.
        """
        candidates = await self._fetch_candidate_bindings(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
        )
        enabled_control_ids = [
            binding.control_id for binding in candidates if binding.enabled
        ]
        if not enabled_control_ids:
            return []
        return await self._fetch_active_controls(
            namespace_key=namespace_key,
            control_ids=enabled_control_ids,
        )

    async def _fetch_candidate_bindings(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
    ) -> Sequence[ControlBinding]:
        stmt = select(ControlBinding).where(
            ControlBinding.namespace_key == namespace_key,
            ControlBinding.target_type == target_type,
            ControlBinding.target_id == target_id,
        )
        result = await self._db.execute(stmt)
        return result.scalars().all()

    async def _fetch_active_controls(
        self,
        *,
        namespace_key: str,
        control_ids: Sequence[int],
    ) -> list[Control]:
        stmt = select(Control).where(
            Control.namespace_key == namespace_key,
            Control.id.in_(control_ids),
            Control.deleted_at.is_(None),
        )
        result = await self._db.execute(stmt)
        return list(result.scalars())

    async def _require_control(
        self, *, namespace_key: str, control_id: int
    ) -> None:
        stmt = select(Control.id).where(
            Control.id == control_id,
            Control.namespace_key == namespace_key,
            Control.deleted_at.is_(None),
        )
        result = await self._db.execute(stmt)
        if result.first() is None:
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
