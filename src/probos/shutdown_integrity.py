"""AD-820: shutdown integrity marker + boot-time clean-shutdown check.

Today's #750 data corruption happened because the shutdown handler hit a
hardcoded 2-second consolidation timeout mid-dream-write, leaving
ChromaDB's HNSW index torn. The next boot had no signal that the previous
shutdown was unclean — it just tried to read the corrupted file and the
native side segfaulted before Python could see anything.

This module is the integrity layer that turns "silently corrupted, then
segfault on next boot" into "explicit refusal to start with an actionable
remediation message."

Two operations:

* :func:`mark_clean_shutdown` — called at the end of shutdown phase 1
  when consolidation completed fully. Atomically writes
  ``{data_dir}/shutdown_status.json`` recording status=clean +
  timestamp + consolidation outcome.

* :func:`check_previous_shutdown` — called at the start of ``_serve``
  before any database opens. Reads the marker; raises
  :class:`UncleanShutdownDetected` if the previous shutdown wasn't
  clean. Operator can override with ``--force-unclean`` for legitimate
  cases (eg first boot, manual recovery).

The atomic write is the critical part: write a temp file, fsync it,
rename over the destination. Survives mid-write process death.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

ShutdownStatus = Literal["clean", "partial", "aborted", "unknown"]
ConsolidationResult = Literal["full", "partial", "skipped", "failed"]

STATUS_FILENAME = "shutdown_status.json"


class UncleanShutdownDetected(RuntimeError):
    """The previous shutdown did not complete cleanly.

    Carries the recovered status payload so the caller can shape an
    operator-readable error message.
    """

    def __init__(self, data_dir: Path, payload: dict) -> None:
        self.data_dir = data_dir
        self.payload = payload
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        ts = self.payload.get("last_shutdown_at")
        ts_str = (
            time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))
            if ts
            else "(unknown)"
        )
        status = self.payload.get("status", "unknown")
        consolidation = self.payload.get("consolidation_result", "unknown")
        return (
            f"Previous shutdown was {status} (consolidation_result="
            f"{consolidation} at {ts_str}). The episodic memory may be in "
            f"an inconsistent state.\n\n"
            f"Options:\n"
            f"  (a) Run 'probos rebuild-episodic' to reconstruct ChromaDB "
            f"from the surviving journal + ward room (AD-819)\n"
            f"  (b) Pass --force-unclean to start anyway (risks segfault "
            f"if HNSW index is torn)\n"
            f"  (c) Restore the data dir from a backup\n\n"
            f"Data dir: {self.data_dir}"
        )


@dataclass(frozen=True)
class ShutdownStatusPayload:
    status: ShutdownStatus
    last_shutdown_at: float
    consolidation_result: ConsolidationResult
    version: str = ""
    note: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "status": self.status,
                "last_shutdown_at": self.last_shutdown_at,
                "consolidation_result": self.consolidation_result,
                "version": self.version,
                "note": self.note,
            },
            indent=2,
            sort_keys=True,
        )


def _atomic_write(target: Path, content: str) -> None:
    """Write ``content`` to ``target`` atomically.

    Writes via a sibling temp file + ``os.replace`` (POSIX + Windows
    atomic on the same filesystem). ``fsync`` between write and rename
    ensures the file contents are durable before the rename publishes
    them, so a crash mid-rename leaves either the OLD file or the NEW
    file — never a torn one.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(target))


def mark_clean_shutdown(
    data_dir: Path,
    *,
    consolidation_result: ConsolidationResult = "full",
    version: str = "",
    note: str = "",
) -> None:
    """Atomically record a clean shutdown for the next boot to discover."""
    payload = ShutdownStatusPayload(
        status="clean" if consolidation_result == "full" else "partial",
        last_shutdown_at=time.time(),
        consolidation_result=consolidation_result,
        version=version,
        note=note,
    )
    try:
        _atomic_write(Path(data_dir) / STATUS_FILENAME, payload.to_json())
        logger.info(
            "AD-820: shutdown_status.json written (status=%s, consolidation=%s)",
            payload.status, payload.consolidation_result,
        )
    except OSError:
        logger.warning(
            "AD-820: failed to write shutdown_status.json (continuing shutdown)",
            exc_info=True,
        )


def mark_dirty_shutdown(
    data_dir: Path,
    *,
    consolidation_result: ConsolidationResult,
    note: str = "",
) -> None:
    """Atomically record an unclean shutdown so the next boot blocks.

    Called when the shutdown path knows consolidation didn't fully
    complete (timed out, errored, was force-aborted). The next boot
    will read this and refuse to start.
    """
    payload = ShutdownStatusPayload(
        status="partial",
        last_shutdown_at=time.time(),
        consolidation_result=consolidation_result,
        version="",
        note=note,
    )
    try:
        _atomic_write(Path(data_dir) / STATUS_FILENAME, payload.to_json())
        logger.warning(
            "AD-820: shutdown_status.json marked partial (consolidation=%s, note=%s)",
            payload.consolidation_result, note,
        )
    except OSError:
        logger.warning(
            "AD-820: failed to write dirty shutdown_status.json",
            exc_info=True,
        )


def read_shutdown_status(data_dir: Path) -> dict:
    """Read ``shutdown_status.json``. Returns empty dict if absent."""
    path = Path(data_dir) / STATUS_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "AD-820: shutdown_status.json unreadable; treating as unknown",
            exc_info=True,
        )
        return {"status": "unknown"}


def check_previous_shutdown(
    data_dir: Path,
    *,
    force_unclean: bool = False,
    is_first_boot: bool = False,
) -> None:
    """Refuse to start if the previous shutdown wasn't clean.

    Args:
        data_dir: per-instance data directory.
        force_unclean: operator override (--force-unclean CLI flag).
            Even when set, the override is LOGGED so post-mortems can see
            the operator accepted the risk.
        is_first_boot: when True (no databases yet exist), treat absence
            of the marker as fine. Otherwise absence means the marker
            was lost or the previous boot crashed before writing it,
            which is suspicious enough to refuse.

    Raises:
        UncleanShutdownDetected: when the marker indicates a non-clean
            shutdown AND ``force_unclean`` is False.
    """
    data_dir = Path(data_dir)
    payload = read_shutdown_status(data_dir)

    if not payload:
        if is_first_boot:
            logger.info("AD-820: first boot — no shutdown_status.json (expected)")
            return
        # No marker BUT databases exist: the previous boot either crashed
        # before writing the marker, OR predates AD-820.
        if (data_dir / "events.db").exists() or (data_dir / "chroma.sqlite3").exists():
            logger.warning(
                "AD-820: data dir exists but shutdown_status.json is absent. "
                "Either the previous boot crashed or predates AD-820. "
                "Proceeding (would refuse on a subsequent unclean shutdown)."
            )
        return

    status = payload.get("status", "unknown")
    if status == "clean":
        logger.info(
            "AD-820: previous shutdown was clean at %.0f",
            payload.get("last_shutdown_at", 0),
        )
        return

    if force_unclean:
        logger.warning(
            "AD-820: --force-unclean override accepted; proceeding despite "
            "previous shutdown status=%s (consolidation_result=%s)",
            status, payload.get("consolidation_result"),
        )
        return

    raise UncleanShutdownDetected(data_dir, payload)
