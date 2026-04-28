"""Persistence and resolution helpers for the ``control_bindings`` table."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from ..models import Control, ControlBinding


class ControlBindingsService:
    """Resolve effective controls for target-bearing requests."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

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
