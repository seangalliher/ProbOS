"""AD-720d-2.1: in-memory + on-disk vision-capability proposal history.

Mirrors the AD-721d-4 sidecar persistence pattern: module-level state,
RLock, atomic temp-file + ``os.replace`` writes, Tier-2 log-and-degrade
on disk failure.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, fields
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VisionProposalEntry:
    proposal_id: str
    agent_id: str
    rationale: str
    proposed_at: float
    resolved_at: float | None = None
    resolution: str | None = None  # "approved" | "denied"
    resolution_reason: str = ""


_entries: list[VisionProposalEntry] = []
_lock = RLock()
_path: Path | None = None


def configure(path: Path | None) -> None:
    """Bind on-disk sidecar (called once at startup from runtime.py).

    Passing ``None`` disables persistence (in-memory only). Existing file
    contents are loaded on bind; failures fall back to an empty list and
    log at WARNING (Tier-2 log-and-degrade).
    """
    global _path, _entries
    with _lock:
        _path = path
        if path is None:
            return
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            _entries = [VisionProposalEntry(**row) for row in raw]
        except (FileNotFoundError, json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "AD-720d-2.1: failed to load vision proposal history from %s; "
                "starting empty. err=%s",
                path, exc,
            )
            _entries = []


def append(entry: VisionProposalEntry) -> None:
    """Append a new proposal entry and persist."""
    with _lock:
        _entries.append(entry)
        _persist_locked()


def resolve(
    proposal_id: str, resolution: str, reason: str
) -> VisionProposalEntry | None:
    """Mark a proposal as resolved (approved/denied) and persist.

    Returns the resolved entry, or None if the proposal_id is unknown or
    already resolved.
    """
    with _lock:
        for idx, e in enumerate(_entries):
            if e.proposal_id == proposal_id and e.resolved_at is None:
                resolved = VisionProposalEntry(
                    proposal_id=e.proposal_id,
                    agent_id=e.agent_id,
                    rationale=e.rationale,
                    proposed_at=e.proposed_at,
                    resolved_at=time.time(),
                    resolution=resolution,
                    resolution_reason=reason,
                )
                _entries[idx] = resolved
                _persist_locked()
                return resolved
        return None


def list_for_agent(agent_id: str) -> list[VisionProposalEntry]:
    """Snapshot of proposals filed by ``agent_id`` (chronological order)."""
    with _lock:
        return [e for e in _entries if e.agent_id == agent_id]


def reset_all() -> None:
    """Test helper: clear in-memory state and persist empty list."""
    with _lock:
        _entries.clear()
        _persist_locked()


def _persist_locked() -> None:
    """Atomic write — caller MUST hold ``_lock``."""
    if _path is None:
        return
    try:
        tmp = _path.with_suffix(_path.suffix + ".tmp")
        payload = [
            {f.name: getattr(e, f.name) for f in fields(e)}
            for e in _entries
        ]
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_path)
    except OSError as exc:
        logger.warning(
            "AD-720d-2.1: failed to persist vision proposal history to %s; "
            "in-memory state remains authoritative. err=%s",
            _path, exc,
        )
