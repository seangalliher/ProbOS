"""AD-730-2-1: persistence for the AD-730-2 per-Captain daily image budget.

Format: ``{captain_id: [[timestamp, count], ...]}``. Loaded on runtime
startup, saved on every mutation by ``ImagePolicyEnforcer.check_budget``.
Tier-2 throughout - disk I/O failure logs and degrades; the in-memory
tracker remains authoritative for the live process.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


def load(path: Path) -> dict[str, deque]:
    """Load tracker from JSON sidecar. Missing/corrupt file returns {}.

    Each loaded captain's deque is reconstructed in chronological order;
    expired entries are NOT pruned here - that's the gate's job at
    check-budget time (one window-cutoff pass per call).
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        logger.warning(
            "AD-730-2-1: failed to load %s; starting with empty budget tracker",
            path, exc_info=True,
        )
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "AD-730-2-1: %s contained non-dict root %r; starting empty",
            path, type(data).__name__,
        )
        return {}
    out: dict[str, deque] = {}
    for captain_id, entries in data.items():
        if not isinstance(captain_id, str) or not isinstance(entries, list):
            continue
        q: deque = deque()
        for entry in entries:
            if (
                isinstance(entry, list) and len(entry) == 2
                and isinstance(entry[0], (int, float))
                and isinstance(entry[1], int)
            ):
                q.append((float(entry[0]), int(entry[1])))
        out[captain_id] = q
    return out


def save(path: Path, tracker: dict[str, deque]) -> None:
    """Atomically write tracker to ``path``. Tier-2 - log-and-degrade.

    Writes to a sibling temp file then ``os.replace`` for atomicity.
    Empty captains (deque length 0) are skipped to keep the file compact.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            captain_id: [[ts, n] for (ts, n) in entries]
            for captain_id, entries in tracker.items()
            if entries  # skip empty deques
        }
        fd, tmp_path = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, separators=(",", ":"))
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
    except Exception:
        logger.warning(
            "AD-730-2-1: failed to persist budget tracker to %s; "
            "in-memory tracker remains authoritative for this process",
            path, exc_info=True,
        )
