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

    BF-857: that first sentence was false for three of the five call shapes.
    ``add``, ``list`` and ``clear(path=...)`` build a ``dict`` key from
    ``(owner, path)``, so an unhashable owner raised ``TypeError``. ``dismiss``
    and ``clear(path=None)`` compare rather than hash and were always safe.
    Measured against a store that already held an entry::

        add: TypeError   list: TypeError   clear(path=...): TypeError
        dismiss: ok      clear(path=None): ok

    The seeding matters. A first measurement ran each method against an EMPTY
    store and reported ``clear: ok``, because CPython can answer a lookup on an
    empty dict without hashing -- a probe that did not discriminate, and it read
    as a clean result. The issue was filed with that wrong table.

    Fixed by making the claim true rather than narrowing it. Honest-degrade is
    this module's stated contract, most of the class already honoured it, and
    the keys arrive from agent-supplied paths -- so "well-formed key" would be
    an assumption about a caller, and BF-763's lesson is that a module cannot
    honestly summarise what its callers do.
    """

    def __init__(self, max_per_path: int = _DEFAULT_MAX_PER_PATH) -> None:
        # max_per_path < 1 is meaningless; clamp to 1 so add always keeps the
        # just-added suggestion (never evicts the item it just inserted).
        self._max_per_path: int = max(1, int(max_per_path))
        self._by_key: dict[tuple[str, str], list[WorkspaceSuggestion]] = {}

    @property
    def max_per_path(self) -> int:
        return self._max_per_path

    @staticmethod
    def _key(owner: object, path: object) -> tuple[str, str]:
        """A hashable bucket key, whatever was handed in.

        BF-857: the two methods that raised did so on ``dict`` lookup, not on
        anything they meant to validate. Coercion keeps the guarantee inside
        this class instead of asking every caller for it -- the same reason
        ``trace_analysis.quote_for_prose`` stopped documenting its safety as a
        caller obligation (BF-856).

        Total: a ``__str__`` that itself raises degrades to a sentinel rather
        than propagating, because a store whose contract is "never raises"
        cannot make an exception for the object that made it hard.
        """
        def _one(value: object) -> str:
            # ``isinstance``, NOT ``type(value) is str``: a ``str`` subclass is
            # already hashable and already compares equal to its plain form, so
            # it worked before this change. An exact-type check would send it
            # through ``str()`` instead -- and a subclass with a custom
            # ``__str__`` would land in a DIFFERENT bucket than the one the
            # same caller read from. Caught by this change's own test; a fix
            # for a crash must not quietly move where data lives.
            if isinstance(value, str):
                return value
            try:
                return str(value)
            except Exception:
                return "<unrenderable>"

        return (_one(owner), _one(path))

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
        bucket = self._by_key.setdefault(self._key(owner, path), [])
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
        return list(self._by_key.get(self._key(owner, path), ()))

    def dismiss(self, owner: str, suggestion_id: str) -> bool:
        """Remove the suggestion with ``suggestion_id`` from any of ``owner``'s
        buckets. Returns ``True`` if one was removed, ``False`` if not found.

        The dismiss endpoint carries no path (the HXI dismisses by id), so the
        store searches ``owner``'s buckets — ids are globally unique, so at most
        one matches. Empties the bucket entry when it becomes empty.

        BF-857: this compares rather than hashes, so it never raised on a bad
        key. The owner is normalised anyway so it matches what ``add`` stored;
        without that, a suggestion added under a coerced key could not be
        dismissed by the same caller that added it.
        """
        owner_key, _ = self._key(owner, "")
        for key in list(self._by_key.keys()):
            if key[0] != owner_key:
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
        ``(owner, path)`` bucket. Honest-degrade no-op for an unknown key.

        BF-857: the ``path is not None`` branch hashes, so it raised on an
        unhashable owner exactly like ``add`` and ``list``. It was reported as
        safe because the probe that measured it ran against an EMPTY store, and
        CPython skips hashing a lookup on an empty dict -- a probe that did not
        discriminate, and read as a clean result. The ``path is None`` branch
        compares rather than hashes and was always safe.
        """
        if path is not None:
            self._by_key.pop(self._key(owner, path), None)
            return
        owner_key, _ = self._key(owner, "")
        for key in [k for k in self._by_key if k[0] == owner_key]:
            del self._by_key[key]
