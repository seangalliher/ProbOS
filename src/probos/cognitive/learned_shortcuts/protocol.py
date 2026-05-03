"""AD-641e: LearnedShortcutBackend -- shared Protocol for learned-shortcut systems.

Both WorkflowCache and (future) Cognitive JIT adopt this Protocol. They keep
separate storage and tuning; the Protocol is the read-side abstraction.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LearnedShortcutBackend(Protocol):
    """Read-side interface for learned-shortcut backends."""

    @property
    def kind(self) -> str:
        """Backend identifier, e.g. 'workflow_cache' / 'cognitive_jit'."""
        ...

    @property
    def size(self) -> int:
        """Current number of stored entries."""
        ...

    def lookup(self, key: str) -> Any | None:
        """Return the stored value or None if not found."""
        ...

    def store(self, key: str, value: Any) -> None:
        """Store an entry under key."""
        ...

    def evict(self, key: str) -> bool:
        """Remove the entry under key. Returns True if an entry was removed."""
        ...
