"""AD-1021c: in-memory per-file *agent suggestions* for the Monaco workstation.

The co-edit surface (HXI #11) is **not** an IDE — there is no CRDT, no
operational transform, no live char-by-char editing. Instead a crew agent
proposes a FULL replacement body for one file in another agent's AD-997 working
folder, and the human Accepts (a governed AD-1021b write through consensus) or
Dismisses it. This module is the thin, additive substrate that holds those
pending proposals between "an agent proposed it" and "the human acted on it".

``WorkspaceSuggestionStore`` is keyed by ``(owner, path)`` — the owner is the
agent whose workspace the file lives in (the same owner key
``WorkspaceManager.key_for_agent`` produces), the path is the workspace-relative
file. It is **in-memory and volatile by design**: a pending suggestion is a
transient "someone wants to change this file" signal, not durable state — a
restart clears the queue (the agent can re-propose). It is honest-degrading
(never raises) and bounded per ``(owner, path)`` (oldest-evict) so a chatty
agent cannot grow the queue without bound.

The store performs NO path confinement itself — confinement is the API
boundary's job (``WorkspaceManager.resolve_file`` BEFORE the store is touched,
mirroring the AD-1021b write path), so a traversal never reaches ``add``.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Per-(owner, path) cap. A single file accrues at most this many pending
# proposals; the oldest is evicted on overflow. Generous for real review yet
# bounded so an agent that re-proposes in a loop cannot exhaust memory.
_DEFAULT_MAX_PER_PATH = 50


@dataclass(frozen=True)
class WorkspaceSuggestion:
    """One pending agent proposal for a single workspace file.

    Frozen — a suggestion is an immutable record of "agent *author_id* proposed
    *content* for *path* at *created_at*". Carries the FULL proposed body (the
    co-edit surface has no diff engine; Accept writes ``content`` verbatim
    through the governed AD-1021b write).
    """

    id: str
    owner: str
    path: str
    content: str
    author_id: str
    author_callsign: str = ""
    note: str = ""
    created_at: float = field(default_factory=time.time)

    def to_public(self) -> dict[str, object]:
        """Serialise for the API/HXI (the full content is included so the HXI
        can Preview/Accept without a second round-trip)."""
        return {
            "id": self.id,
            "owner": self.owner,
            "path": self.path,
            "content": self.content,
            "author_id": self.author_id,
            "author_callsign": self.author_callsign,
            "note": self.note,
            "created_at": self.created_at,
        }


class WorkspaceSuggestionStore:
    """Bounded, in-memory store of pending agent suggestions per ``(owner, path)``.

    All methods are honest-degrading and never raise on bad keys; the bound is
    enforced on ``add`` (oldest-evict). Not thread-safe by intent — it is touched
    only from the asyncio API handlers (single event loop), like the other
    in-memory runtime substrates.
    """

    def __init__(self, max_per_path: int = _DEFAULT_MAX_PER_PATH) -> None:
        # max_per_path < 1 is meaningless; clamp to 1 so add always keeps the
        # just-added suggestion (never evicts the item it just inserted).
        self._max_per_path: int = max(1, int(max_per_path))
        self._by_key: dict[tuple[str, str], list[WorkspaceSuggestion]] = {}

    @property
    def max_per_path(self) -> int:
        return self._max_per_path

    def add(
        self,
        owner: str,
        path: str,
        content: str,
        author_id: str,
        author_callsign: str = "",
        note: str = "",
    ) -> WorkspaceSuggestion:
        """Append a new suggestion for ``(owner, path)`` and return it.

        Generates a unique id + creation timestamp. When the ``(owner, path)``
        bucket would exceed ``max_per_path`` the OLDEST suggestion is evicted
        (FIFO) — the newly added one is always retained.
        """
        suggestion = WorkspaceSuggestion(
            id=uuid.uuid4().hex,
            owner=owner,
            path=path,
            content=content,
            author_id=author_id,
            author_callsign=author_callsign,
            note=note,
        )
        bucket = self._by_key.setdefault((owner, path), [])
        bucket.append(suggestion)
        if len(bucket) > self._max_per_path:
            # Drop oldest-first until within bound (normally a single eviction).
            del bucket[: len(bucket) - self._max_per_path]
        return suggestion

    def list(self, owner: str, path: str) -> list[WorkspaceSuggestion]:
        """Return the pending suggestions for ``(owner, path)`` (oldest-first).

        Returns a COPY so callers cannot mutate the internal bucket. Empty list
        for an unknown key (honest-degrade — never raises, never ``None``).
        """
        return list(self._by_key.get((owner, path), ()))

    def dismiss(self, owner: str, suggestion_id: str) -> bool:
        """Remove the suggestion with ``suggestion_id`` from any of ``owner``'s
        buckets. Returns ``True`` if one was removed, ``False`` if not found.

        The dismiss endpoint carries no path (the HXI dismisses by id), so the
        store searches ``owner``'s buckets — ids are globally unique, so at most
        one matches. Empties the bucket entry when it becomes empty.
        """
        for key in list(self._by_key.keys()):
            if key[0] != owner:
                continue
            bucket = self._by_key[key]
            for i, s in enumerate(bucket):
                if s.id == suggestion_id:
                    del bucket[i]
                    if not bucket:
                        del self._by_key[key]
                    return True
        return False

    def clear(self, owner: str, path: str | None = None) -> None:
        """Drop all of ``owner``'s suggestions (``path=None``) or just the
        ``(owner, path)`` bucket. Honest-degrade no-op for an unknown key."""
        if path is not None:
            self._by_key.pop((owner, path), None)
            return
        for key in [k for k in self._by_key if k[0] == owner]:
            del self._by_key[key]
