"""AD-641e: WorkflowCacheBackend -- adapter wrapping the existing WorkflowCache.

The underlying WorkflowCache (AD-274; preexisting) is unchanged; this adapter
exposes the LearnedShortcutBackend Protocol surface so the registry can
observe and coordinate across backend kinds.
"""

from __future__ import annotations

from typing import Any


class WorkflowCacheBackend:
    """LearnedShortcutBackend adapter for WorkflowCache."""

    def __init__(self, *, workflow_cache: Any) -> None:
        self._cache = workflow_cache

    @property
    def kind(self) -> str:
        return "workflow_cache"

    @property
    def size(self) -> int:
        # WorkflowCache.size is a @property (verified at workflow_cache.py:115);
        # getattr() invokes the property descriptor, so the `or 0` is purely
        # defensive against a None return -- it is not a method-vs-property guard.
        return int(getattr(self._cache, "size", 0) or 0)

    def lookup(self, key: str) -> Any | None:
        if not key:
            return None
        # WorkflowCache.lookup uses 'user_input' as parameter name and returns
        # TaskDAG | None. The adapter maps the Protocol's 'key' to that.
        try:
            return self._cache.lookup(key)
        except Exception:
            return None

    def store(self, key: str, value: Any) -> None:
        if not key:
            return
        try:
            self._cache.store(key, value)
        except Exception:
            pass

    def evict(self, key: str) -> bool:
        # WorkflowCache currently does not expose a public evict() method;
        # v1 returns False (eviction is not supported on this backend yet).
        # AD-641e-ii will add cross-backend eviction including a public
        # evict() addition to WorkflowCache.
        return False
