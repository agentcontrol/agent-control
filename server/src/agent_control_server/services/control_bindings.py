"""Persistence and resolution helpers for the ``control_bindings`` table."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import cast

from agent_control_models.errors import ErrorCode
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from ..errors import ConflictError, NotFoundError
from ..models import Control, ControlBinding


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
        agent_name: str | None = None,
        enabled: bool = True,
    ) -> ControlBinding:
        """Insert a new binding row.

        Raises ``NotFoundError`` if the referenced control does not exist in
        the same namespace, and ``ConflictError`` if a binding with the same
        shape already exists.
        """
        await self._require_control(
            namespace_key=namespace_key, control_id=control_id
        )
        binding = ControlBinding(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            agent_name=agent_name,
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
                    "A binding with this (target_type, target_id, agent_name, "
                    "control_id) already exists in this namespace."
                ),
                resource="ControlBinding",
                hint="Update the existing binding instead of creating a new one.",
            ) from exc
        return binding

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
        agent_name: str | None = None,
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
        if agent_name is not None:
            stmt = stmt.where(ControlBinding.agent_name == agent_name)
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

    async def resolve_effective_controls(
        self,
        *,
        namespace_key: str,
        target_type: str,
        target_id: str,
        agent_name: str | None = None,
    ) -> list[Control]:
        """Return the effective set of active controls for a target-bearing request.

        Two binding shapes are considered:

        - target-default: ``agent_name IS NULL``; applies to all agents.
        - target-agent: ``agent_name`` matches the request; narrower.

        For each control_id, the most-specific binding wins (target-agent
        beats target-default). A binding with ``enabled = False`` excludes
        the control. Soft-deleted controls (``deleted_at IS NOT NULL``) are
        filtered out.
        """
        candidates = await self._fetch_candidate_bindings(
            namespace_key=namespace_key,
            target_type=target_type,
            target_id=target_id,
            agent_name=agent_name,
        )
        winners = self._most_specific_per_control(candidates)
        enabled_control_ids = [
            control_id
            for control_id, binding in winners.items()
            if binding.enabled
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
        agent_name: str | None,
    ) -> Sequence[ControlBinding]:
        agent_filter: ColumnElement[bool]
        if agent_name is None:
            agent_filter = ControlBinding.agent_name.is_(None)
        else:
            agent_filter = or_(
                ControlBinding.agent_name.is_(None),
                ControlBinding.agent_name == agent_name,
            )
        stmt = select(ControlBinding).where(
            and_(
                ControlBinding.namespace_key == namespace_key,
                ControlBinding.target_type == target_type,
                ControlBinding.target_id == target_id,
                agent_filter,
            )
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

    @staticmethod
    def _most_specific_per_control(
        bindings: Iterable[ControlBinding],
    ) -> dict[int, ControlBinding]:
        """Pick the most-specific binding per ``control_id``.

        Specificity: a binding with ``agent_name`` set is more specific than
        a target-default binding for the same ``control_id``. Per-shape
        uniqueness on the binding row guarantees there is at most one
        candidate per (control, agent) combination, so iteration order is
        irrelevant for the final result.
        """
        winners: dict[int, ControlBinding] = {}
        for binding in bindings:
            current = winners.get(binding.control_id)
            if current is None:
                winners[binding.control_id] = binding
                continue
            if binding.agent_name is not None and current.agent_name is None:
                winners[binding.control_id] = binding
        return winners
