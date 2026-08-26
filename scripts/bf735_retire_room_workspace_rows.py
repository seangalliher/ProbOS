"""BF-735 (#1194): retire the `Room workspace` scaffolding rows on one vessel.

Those rows exist because a chat thread needs a `task_id` for its FILES rail to
bind to. Nothing was ever meant to complete them, and while they sat in `open`
the ship told the Captain it had N open work items in three separate narrations
plus the board and the Quartermaster's sweep. AD-1271 makes the store exclude
flagged rows by default; this script is what puts the flag on.

A ONE-OFF, not a startup migration, and deliberately so. There is no schema
change to force a boot hook, the producer is already dead (AD-1128 removed the
passive UI POST), so the population is CLOSED -- and a startup migration would
bake a title-string match into every boot of every future vessel forever, so a
Captain who names a real item "Room workspace" would have it silently hidden.

Two dispositions, on two independent axes:

  * PROVENANCE -- every matched row came from a rail binding, so every matched
    row is flagged `metadata.ui_scaffold = true`. A Captain later typing a
    checklist into one does not change where it came from.
  * WORK STATE -- a matched row carrying a real checklist is abandoned WORK,
    not scaffolding, so it is additionally transitioned `open -> cancelled`.
    Asked of the real registry: `task` has no `open -> done` edge at all, and
    `open -> cancelled` needs no assignment, which is what makes this legal for
    rows that are all unassigned.

Nothing is deleted. All matched rows are live-bound -- a chat thread holds each
one's id in `task_id` -- so deleting them would break the FILES rail on every
room the Captain has, and would destroy the checklists outright. The room's
Todo panel fetches steps BY ID, so a cancelled row still shows what was asked
and how far it got.

Usage:
    python scripts/bf735_retire_room_workspace_rows.py            # dry run
    python scripts/bf735_retire_room_workspace_rows.py --apply
    python scripts/bf735_retire_room_workspace_rows.py --expect 36 --apply

Idempotent: a second run matches nothing, because already-flagged rows are
excluded from the selection.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

SCAFFOLD_TITLE = "Room workspace"
FLAG = "ui_scaffold"


def _data_dir() -> Path:
    """Resolve the data dir the way the runtime does, not the way the repo looks.

    `d:\\ProbOS\\data` is a stale decoy; the running vessel writes to
    %LOCALAPPDATA%\\ProbOS\\data unless PROBOS_DATA_DIR says otherwise.
    """
    override = os.environ.get("PROBOS_DATA_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "ProbOS" / "data"
    return Path.home() / ".local" / "share" / "ProbOS" / "data"


def _select(conn: sqlite3.Connection, threads_db: Path) -> list[sqlite3.Row]:
    """Rows that are scaffolding: the right title AND bound by a live thread.

    The thread join is what makes this a migration of a KNOWN population rather
    than of everything that happens to share a title.
    """
    rows = conn.execute(
        "SELECT id, title, status, assigned_to, metadata, steps "
        "FROM work_items WHERE title = ? AND status = 'open'",
        (SCAFFOLD_TITLE,),
    ).fetchall()

    bound: set[str] = set()
    if threads_db.exists():
        tconn = sqlite3.connect(f"file:{threads_db}?mode=ro", uri=True)
        try:
            bound = {
                r[0]
                for r in tconn.execute(
                    "SELECT task_id FROM chat_threads "
                    "WHERE task_id IS NOT NULL AND task_id != ''"
                )
            }
        finally:
            tconn.close()

    selected = []
    for row in rows:
        if row["id"] not in bound:
            continue
        meta = _load(row["metadata"])
        if meta.get(FLAG) is True:
            continue  # already migrated
        selected.append(row)
    return selected


def _load(raw: object) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _console(text: str) -> str:
    """Render text the console can actually encode.

    Step labels are Captain-authored and the live ones contain emoji; on a
    cp1252 console `print` raises UnicodeEncodeError and takes the whole run
    down. A migration that crashes while REPORTING what it is about to do is
    worse than one that does nothing.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, "replace").decode(encoding, "replace")


def _has_checklist(row: sqlite3.Row) -> bool:
    """Does this row carry real Captain-visible work rather than nothing at all?"""
    raw = row["steps"]
    if not isinstance(raw, str) or not raw.strip():
        return False
    try:
        steps = json.loads(raw)
    except ValueError:
        return False
    return bool(steps)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="write the changes; without it this only reports",
    )
    parser.add_argument(
        "--expect", type=int, default=36,
        help="abort unless exactly this many rows are selected (0 disables). "
             "A migration that silently matched 3 rows proves nothing about "
             "the population it claims to close.",
    )
    args = parser.parse_args()

    data_dir = _data_dir()
    wf_db = data_dir / "workforce.db"
    threads_db = data_dir / "chat_threads.db"
    print(f"data dir     : {data_dir}")
    print(f"workforce.db : {wf_db}  exists={wf_db.exists()}")
    print(f"chat_threads : {threads_db}  exists={threads_db.exists()}")
    if not wf_db.exists():
        print("nothing to do: no workforce database")
        return 0

    mode = "" if args.apply else "?mode=ro"
    conn = sqlite3.connect(f"file:{wf_db}{mode}", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        selected = _select(conn, threads_db)
        with_steps = [r for r in selected if _has_checklist(r)]
        inert = [r for r in selected if not _has_checklist(r)]

        print(f"\nselected      : {len(selected)}")
        print(f"  inert       : {len(inert)}  -> flag only")
        print(f"  with steps  : {len(with_steps)}  -> flag AND cancel")

        if args.expect and len(selected) != args.expect:
            print(
                f"\nABORT: expected exactly {args.expect} rows, selected "
                f"{len(selected)}. Re-run with --expect {len(selected)} once you "
                f"have confirmed that is the population you mean to change.",
                file=sys.stderr,
            )
            return 2

        for row in with_steps:
            steps = json.loads(row["steps"])
            print(f"\n  {row['id'][:12]}  {len(steps)} step(s), will be CANCELLED")
            for step in steps[:4]:
                label = step.get("label") if isinstance(step, dict) else str(step)
                status = step.get("status") if isinstance(step, dict) else "?"
                print(_console(f"      [{status}] {str(label)[:72]}"))

        if not args.apply:
            print("\nDRY RUN -- nothing written. Re-run with --apply.")
            return 0

        for row in selected:
            meta = _load(row["metadata"])
            meta[FLAG] = True
            conn.execute(
                "UPDATE work_items SET metadata = ?, updated_at = strftime('%s','now') "
                "WHERE id = ?",
                (json.dumps(meta, sort_keys=True), row["id"]),
            )
        for row in with_steps:
            conn.execute(
                "UPDATE work_items SET status = 'cancelled', "
                "updated_at = strftime('%s','now') WHERE id = ?",
                (row["id"],),
            )
        conn.commit()

        remaining = conn.execute(
            "SELECT COUNT(*) FROM work_items WHERE status = 'open'"
        ).fetchone()[0]
        print(f"\napplied. flagged {len(selected)}, cancelled {len(with_steps)}.")
        print(f"rows still in 'open': {remaining}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
