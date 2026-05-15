"""AD-721d-1: in-memory per-agent proposal history.

The Captain can iterate up to ``AvatarsConfig.max_proposal_iterations``
times on an agent's avatar DSL. Each call to ``POST /appearance/propose``
appends to the history; ``PUT /appearance`` (approve) and
``DELETE /appearance/proposal-history`` (explicit clear) clear it.

This module is intentionally a process-local module-level dict. v1 is
single-process; cluster-wide consistency, persistence across restarts,
and quorum on the iteration counter are out of scope. The DSL itself
persists ONLY when the Captain approves (via the existing AD-721d
``AppearanceProfile.dsl`` path).

AD-721d-4: optional disk persistence is wired via ``configure(path)`` -
the on-disk JSON sidecar is loaded on configure and rewritten after
every mutation. Tier-2 throughout - disk failure logs and degrades; the
in-memory ``_history`` remains authoritative for the live process.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposalEntry:
    """One iteration in an agent's current DSL-proposal session."""

    dsl: dict          # AvatarDSL.model_dump() snapshot
    captain_note: str  # the revision hint used to produce this dsl ("" for iteration 1)
    timestamp: float


# Module-level state - guarded by a re-entrant lock so concurrent FastAPI
# requests on the same agent don't race the counter.
_lock = threading.RLock()
_history: dict[str, list[ProposalEntry]] = {}
# AD-721d-4: optional disk persistence. ``configure`` is called once at
# runtime boot to set the sidecar path AND load any prior state. When the
# path is None, the module operates in pure in-memory mode (matches
# AD-721d-1 behavior - required for tests and zero-config operators).
_persist_path: Path | None = None


def configure(path: Path | None) -> None:
    """Set the on-disk sidecar path and load any pre-existing state.

    Idempotent - calling with the same path repopulates from disk
    (useful for tests that need to inspect the persisted state).
    Calling with None disables persistence and clears the in-memory
    state (test-only convenience; production should not pass None
    after a real path has been set).
    """
    global _persist_path
    with _lock:
        _persist_path = path
        _history.clear()
        if path is None:
            return
        _load_from_disk_locked()


def _load_from_disk_locked() -> None:
    """Internal - called under ``_lock``. Loads ``_persist_path`` into ``_history``.

    Tier-2: load failure leaves ``_history`` empty and logs WARNING.
    """
    import json
    if _persist_path is None or not _persist_path.exists():
        return
    try:
        raw = _persist_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        logger.warning(
            "AD-721d-4: failed to load proposal history from %s; "
            "starting with empty in-memory state",
            _persist_path, exc_info=True,
        )
        return
    if not isinstance(data, dict):
        logger.warning(
            "AD-721d-4: %s contained non-dict root %r; starting empty",
            _persist_path, type(data).__name__,
        )
        return
    for agent_id, entries in data.items():
        if not isinstance(agent_id, str) or not isinstance(entries, list):
            continue
        loaded: list[ProposalEntry] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                loaded.append(ProposalEntry(
                    dsl=entry["dsl"],
                    captain_note=str(entry.get("captain_note", "")),
                    timestamp=float(entry["timestamp"]),
                ))
            except (KeyError, TypeError, ValueError):
                logger.warning(
                    "AD-721d-4: skipping malformed entry for agent=%s in %s",
                    agent_id, _persist_path,
                )
        if loaded:
            _history[agent_id] = loaded


def _persist_locked() -> None:
    """Internal - called under ``_lock``. Atomically writes ``_history`` to disk.

    Tier-2 - failures log and degrade; in-memory state is authoritative.
    """
    import json
    import os
    import tempfile
    if _persist_path is None:
        return
    try:
        _persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            agent_id: [
                {"dsl": e.dsl, "captain_note": e.captain_note, "timestamp": e.timestamp}
                for e in entries
            ]
            for agent_id, entries in _history.items()
            if entries
        }
        fd, tmp_path = tempfile.mkstemp(
            prefix=_persist_path.name + ".",
            suffix=".tmp",
            dir=str(_persist_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp_path, _persist_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
    except Exception:
        logger.warning(
            "AD-721d-4: failed to persist proposal history to %s; "
            "in-memory state remains authoritative",
            _persist_path, exc_info=True,
        )


def append(agent_id: str, dsl: dict, captain_note: str) -> int:
    """Append a proposal entry; return the new iteration count (1-based)."""
    with _lock:
        entries = _history.setdefault(agent_id, [])
        entries.append(
            ProposalEntry(dsl=dsl, captain_note=captain_note, timestamp=time.time())
        )
        _persist_locked()
        return len(entries)


def iteration_count(agent_id: str) -> int:
    """Return current iteration count for ``agent_id`` (0 if no history)."""
    with _lock:
        return len(_history.get(agent_id, []))


def latest(agent_id: str) -> ProposalEntry | None:
    """Return the most-recent ProposalEntry for ``agent_id``, or None."""
    with _lock:
        entries = _history.get(agent_id)
        return entries[-1] if entries else None


def clear(agent_id: str) -> int:
    """Drop history for ``agent_id``; return the prior iteration count."""
    with _lock:
        prior = len(_history.get(agent_id, []))
        _history.pop(agent_id, None)
        _persist_locked()
        return prior


def reset_all() -> None:
    """Test-only: drop ALL history. Production callers should use ``clear``."""
    with _lock:
        _history.clear()
        _persist_locked()


__all__ = [
    "ProposalEntry",
    "append",
    "iteration_count",
    "latest",
    "clear",
    "reset_all",
    "configure",
]
