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

The module exposes module-level functions, not a class — there is no
state worth dependency-injecting and the OSS-tier wiring stays trivial.
A future commercial overlay may swap to a redis-backed implementation
behind the same function signatures.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProposalEntry:
    """One iteration in an agent's current DSL-proposal session."""

    dsl: dict          # AvatarDSL.model_dump() snapshot
    captain_note: str  # the revision hint used to produce this dsl ("" for iteration 1)
    timestamp: float


# Module-level state — guarded by a re-entrant lock so concurrent FastAPI
# requests on the same agent don't race the counter.
_lock = threading.RLock()
_history: dict[str, list[ProposalEntry]] = {}


def append(agent_id: str, dsl: dict, captain_note: str) -> int:
    """Append a proposal entry; return the new iteration count (1-based)."""
    with _lock:
        entries = _history.setdefault(agent_id, [])
        entries.append(
            ProposalEntry(dsl=dsl, captain_note=captain_note, timestamp=time.time())
        )
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
        return prior


def reset_all() -> None:
    """Test-only: drop ALL history. Production callers should use ``clear``."""
    with _lock:
        _history.clear()


__all__ = [
    "ProposalEntry",
    "append",
    "iteration_count",
    "latest",
    "clear",
    "reset_all",
]
