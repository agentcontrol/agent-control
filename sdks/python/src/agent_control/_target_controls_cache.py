"""Per-target cache for effective control sets.

Caches the result of ``GET /api/v1/control-bindings/effective`` keyed by
``(target_type, target_id)`` so repeat target-bearing evaluations do not
re-fetch on every call. Entries are kept until evicted by the bounded
LRU policy or invalidated explicitly. Freshness is maintained by the
SDK's target-controls refresh loop, which mirrors the agent-bound
policy refresh loop.

This module owns the cache singleton; concurrency is handled with a
threading lock so it is safe under both async and threaded access.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any


class TargetControlsCache:
    """Bounded LRU cache keyed by ``(target_type, target_id)``."""

    def __init__(self, *, max_size: int) -> None:
        self._max_size = max_size
        self._entries: OrderedDict[tuple[str, str], list[dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def configure(self, *, max_size: int) -> None:
        """Update capacity. Existing entries are kept; capacity is enforced."""
        with self._lock:
            self._max_size = max_size
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)

    def get(
        self, target_type: str, target_id: str
    ) -> list[dict[str, Any]] | None:
        """Return cached controls for a target, or ``None`` on miss."""
        key = (target_type, target_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return list(entry)

    def put(
        self,
        target_type: str,
        target_id: str,
        controls: list[dict[str, Any]],
    ) -> None:
        """Store the effective controls for a target, evicting the oldest entry if full."""
        key = (target_type, target_id)
        with self._lock:
            self._entries[key] = list(controls)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)

    def invalidate(self, target_type: str, target_id: str) -> None:
        """Drop the cached entry for one target. No-op if not present."""
        key = (target_type, target_id)
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        """Drop every cached entry."""
        with self._lock:
            self._entries.clear()

    def keys_snapshot(self) -> list[tuple[str, str]]:
        """Return a snapshot of the cache keys safe to iterate without holding the lock."""
        with self._lock:
            return list(self._entries.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_cache = TargetControlsCache(max_size=1024)


def get_target_controls_cache() -> TargetControlsCache:
    """Return the process-wide target controls cache."""
    return _cache
