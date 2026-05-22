"""AD-819: rebuild-episodic — reconstruct ChromaDB from surviving ward room.

When ChromaDB's HNSW index is corrupted (#750), the operator quarantines
the chroma.sqlite3 + collection dir and boots against a fresh empty
ChromaDB. The agents come back but lose semantic recall over historical
conversations. This module replays the surviving ward_room.db
(threads + posts + DMs) back into ChromaDB so agents regain that recall.

What's reconstructible:
    * Ward room threads: title + body → Episode.user_input
    * Ward room posts (replies): body → Episode.user_input, links back to thread
    * DM exchanges: same shape as posts, special channel_id

What's NOT reconstructible:
    * Dream-cycle reflections (AD-599): synthesized insights that only
      lived in ChromaDB. The next idle cycle will regenerate fresh ones
      from the rebuilt episodic memory.
    * Outcomes, shapley values, trust deltas: those tied to specific
      DAG runs we don't have. Episodes get empty outcome lists.

Safety:
    * Refuses to run if AD-816 pidfile shows the runtime is using the
      data dir (concurrent writes would corrupt ChromaDB again).
    * Idempotent — uses a deterministic episode id derived from the
      source row id, so re-running skips already-imported rows.
    * Read-only on ward_room.db (open with mode=ro).
    * Writes go through EpisodicMemory.store() which honors the
      AD-610 storage gate + AD-607h security gate, same as live writes.

Usage:
    probos rebuild-episodic                    # all sources
    probos rebuild-episodic --dry-run          # show counts without writing
    probos rebuild-episodic --since YYYY-MM-DD # only newer rows
    probos rebuild-episodic --source wardroom  # explicit source filter
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class RebuildReport:
    """Aggregate report from a rebuild run."""

    source: str
    dry_run: bool
    rows_scanned: int = 0
    rows_skipped_existing: int = 0
    rows_skipped_filtered: int = 0
    episodes_written: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "dry_run": self.dry_run,
            "rows_scanned": self.rows_scanned,
            "rows_skipped_existing": self.rows_skipped_existing,
            "rows_skipped_filtered": self.rows_skipped_filtered,
            "episodes_written": self.episodes_written,
            "errors": list(self.errors),
        }


def _stable_episode_id(*, source: str, source_id: str) -> str:
    """Deterministic episode id so re-running is idempotent.

    Hash of (source, source_id) → 32 hex chars matching Episode.id shape.
    """
    h = hashlib.sha256()
    h.update(source.encode("utf-8"))
    h.update(b"\x00")
    h.update(source_id.encode("utf-8"))
    return h.hexdigest()[:32]


def _open_wardroom_readonly(db_path: Path) -> sqlite3.Connection:
    """Open ward_room.db with read-only URI.

    Using ``file:.../ward_room.db?mode=ro`` so the rebuild absolutely
    cannot mutate the source store. If the runtime grabs the same file
    in WAL mode concurrently, the read-only attach still works.
    """
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _iter_wardroom_rows(
    conn: sqlite3.Connection,
    *,
    since_ts: float | None = None,
):
    """Yield (kind, row_dict) tuples for threads then posts in chronological order."""
    where_threads = "WHERE created_at >= ?" if since_ts is not None else ""
    params_t: tuple = (since_ts,) if since_ts is not None else ()
    rows = conn.execute(
        f"SELECT id, channel_id, author_id, title, body, created_at, "
        f"channel_name, author_callsign FROM threads {where_threads} "
        f"ORDER BY created_at ASC",
        params_t,
    ).fetchall()
    for r in rows:
        yield "thread", dict(r)

    where_posts = "WHERE created_at >= ? AND deleted = 0" if since_ts is not None else "WHERE deleted = 0"
    params_p: tuple = (since_ts,) if since_ts is not None else ()
    rows = conn.execute(
        f"SELECT id, thread_id, parent_id, author_id, body, created_at, "
        f"author_callsign FROM posts {where_posts} "
        f"ORDER BY created_at ASC",
        params_p,
    ).fetchall()
    for r in rows:
        yield "post", dict(r)


def _row_to_episode_kwargs(kind: str, row: dict) -> dict:
    """Synthesize the kwargs for ``Episode(...)`` from a ward room row.

    Episode is a frozen dataclass; the caller does the actual instantiation.
    """
    if kind == "thread":
        title = row.get("title", "")
        body = row.get("body", "")
        text = f"{title}\n\n{body}" if title and body else (title or body)
        channel = row.get("channel_name") or row.get("channel_id", "")
        callsign = row.get("author_callsign") or row.get("author_id", "")
        return {
            "id": _stable_episode_id(
                source="wardroom_rebuild_thread", source_id=row["id"]
            ),
            "timestamp": float(row.get("created_at", 0.0)),
            "user_input": text.strip(),
            "agent_ids": [row.get("author_id", "")],
            "source": "wardroom_import",
            "importance": 5,
            "dag_summary": {
                "rebuild_source": "wardroom_thread",
                "thread_id": row["id"],
                "channel": channel,
                "author_callsign": callsign,
            },
        }
    # post
    callsign = row.get("author_callsign") or row.get("author_id", "")
    return {
        "id": _stable_episode_id(
            source="wardroom_rebuild_post", source_id=row["id"]
        ),
        "timestamp": float(row.get("created_at", 0.0)),
        "user_input": (row.get("body") or "").strip(),
        "agent_ids": [row.get("author_id", "")],
        "source": "wardroom_import",
        "importance": 5,
        "dag_summary": {
            "rebuild_source": "wardroom_post",
            "thread_id": row.get("thread_id", ""),
            "parent_id": row.get("parent_id") or "",
            "author_callsign": callsign,
        },
    }


async def rebuild_from_wardroom(
    *,
    wardroom_db: Path,
    store_episode: Callable[[dict], Awaitable[None]],
    existing_episode_ids: set[str] | None = None,
    since_ts: float | None = None,
    dry_run: bool = False,
    progress_every: int = 250,
) -> RebuildReport:
    """Replay surviving ward room rows into ChromaDB via ``store_episode``.

    ``store_episode`` is an injected coroutine — in production it's a
    thin wrapper around ``EpisodicMemory.store(Episode(**kwargs))``; in
    tests it's a stub that collects calls. This separation keeps the
    rebuilder testable without a live ChromaDB.

    ``existing_episode_ids`` is a fast-skip set of episode ids already
    present in ChromaDB (queried once up-front by the caller). If None,
    no pre-skip; the storage gate may still dedupe on write.

    Idempotent: re-running on the same source emits the same episode
    ids; rows whose id is in ``existing_episode_ids`` are skipped.
    """
    report = RebuildReport(source="wardroom", dry_run=dry_run)
    if not wardroom_db.exists():
        report.errors.append(f"Ward room store not found: {wardroom_db}")
        return report

    conn = _open_wardroom_readonly(wardroom_db)
    try:
        seen_ids = existing_episode_ids or set()
        for kind, row in _iter_wardroom_rows(conn, since_ts=since_ts):
            report.rows_scanned += 1
            try:
                kwargs = _row_to_episode_kwargs(kind, row)
            except Exception as exc:
                report.errors.append(f"row {row.get('id')!r}: {exc}")
                continue

            ep_id = kwargs["id"]
            if ep_id in seen_ids:
                report.rows_skipped_existing += 1
                continue
            if not kwargs["user_input"]:
                report.rows_skipped_filtered += 1
                continue

            if dry_run:
                report.episodes_written += 1
                continue

            try:
                await store_episode(kwargs)
                report.episodes_written += 1
                seen_ids.add(ep_id)
            except Exception as exc:
                report.errors.append(f"store {ep_id!r}: {exc}")

            if progress_every and report.rows_scanned % progress_every == 0:
                logger.info(
                    "AD-819: wardroom rebuild progress — scanned=%d written=%d "
                    "skipped_existing=%d errors=%d",
                    report.rows_scanned,
                    report.episodes_written,
                    report.rows_skipped_existing,
                    len(report.errors),
                )
    finally:
        conn.close()

    return report


def render_report(report: RebuildReport) -> str:
    """Human-readable summary for the CLI."""
    lines: list[str] = [
        f"AD-819 rebuild from {report.source}"
        + (" (dry-run)" if report.dry_run else ""),
        f"  rows scanned:           {report.rows_scanned:>7}",
        f"  episodes written:       {report.episodes_written:>7}",
        f"  skipped (already had):  {report.rows_skipped_existing:>7}",
        f"  skipped (empty body):   {report.rows_skipped_filtered:>7}",
    ]
    if report.errors:
        lines.append(f"  errors:                 {len(report.errors):>7}")
        for err in report.errors[:5]:
            lines.append(f"    - {err}")
        if len(report.errors) > 5:
            lines.append(f"    ... and {len(report.errors) - 5} more")
    return "\n".join(lines)
