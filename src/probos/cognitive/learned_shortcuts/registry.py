"""AD-641e: LearnedShortcutRegistry -- coordinator for backends.

Read-side fan-out: lookup_first() walks registered backends in registration
order and returns the FIRST non-None hit (no merging). Write-side stays
per-backend; the registry does not multicast stores (that would violate the
design doc's 'separate stores' principle).
"""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.learned_shortcuts.protocol import LearnedShortcutBackend
from probos.events import EventType

logger = logging.getLogger(__name__)


class LearnedShortcutRegistry:
    """Coordinates registered LearnedShortcutBackend instances."""

    def __init__(self, *, emit_event: Any | None = None) -> None:
        self._emit_event = emit_event
        self._backends: list[LearnedShortcutBackend] = []

    @property
    def kinds(self) -> list[str]:
        return [b.kind for b in self._backends]

    @property
    def total_size(self) -> int:
        return sum(int(b.size or 0) for b in self._backends)

    def register(self, backend: LearnedShortcutBackend) -> bool:
        if backend is None:
            return False
        for existing in self._backends:
            if existing.kind == backend.kind:
                return False  # idempotent: same kind already registered
        self._backends.append(backend)
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.LEARNED_SHORTCUT_REGISTERED,
                    {"kind": backend.kind, "size": int(backend.size or 0)},
                )
            except Exception:
                logger.debug(
                    "LearnedShortcutRegistry: emit LEARNED_SHORTCUT_REGISTERED failed",
                    exc_info=True,
                )
        return True

    def lookup_first(self, key: str) -> tuple[str, Any] | None:
        if not key:
            return None
        for backend in self._backends:
            value = backend.lookup(key)
            if value is not None:
                if self._emit_event is not None:
                    try:
                        self._emit_event(
                            EventType.LEARNED_SHORTCUT_HIT,
                            {"kind": backend.kind, "key": str(key)},
                        )
                    except Exception:
                        logger.debug(
                            "LearnedShortcutRegistry: emit LEARNED_SHORTCUT_HIT failed",
                            exc_info=True,
                        )
                return (backend.kind, value)
        return None
