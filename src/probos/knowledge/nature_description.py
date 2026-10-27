"""AD-1341 S6 (#1569): the nature description, culture's record of the nature a crew generation leaves behind.

The Captain's amendment of 2026-10-16 (nature, culture and nurture): proven Cognitive JIT procedures and skills persist
across a reset as nature, a crew's own ability that is never narrated as inherited, and they are not promoted into the
Ship's Archive. The archive gets a *description* instead: which procedures this generation developed and why. The
procedure itself (its steps, ``content_snapshot``) stays in its store and never enters the archive.

- The facts are the procedure store's own: name, description, evolution type, whether it is active, retired or an
  anti-pattern, its selection, completion and fallback counts, and an evolved procedure's change summary. They are
  read read-only from ``procedures/procedures.db``, from columns every version of its table has. No model is called.
  Each text is folded to one line, stripped of control and format characters, and cut to a bound.
- "Developed by this generation" means created at or after ``started``: the reset passes the modification time of
  ``ontology/instance_id``, which the ontology loader writes once, at the ship's first boot.
- Skills are not described: the skill catalog (``config/skills``) is part of the installation and outside every reset,
  and it does not keep which crew forged a skill (each boot registers a skill file again as ``internal``).
- The whole entry fits one Oracle tool entry (``NATURE_DESCRIPTION_MAX_CHARS``); procedures beyond it are counted, not
  listed. The entry names no agent: lineage stays in the store (the amendment's item 2).
  ``archive_promotion.promote_nature_description`` is its one writer.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.knowledge.archive_promotion import NATURE_DESCRIPTION_PREFIX
from probos.knowledge.archive_store import PromotionRecord, SourceKind
from probos.knowledge.lessons import EXIT_NOTE_TIMELINE_MAX_CHARS

if TYPE_CHECKING:
    from probos.protocols import DatabaseConnection

#: Where the procedure store keeps its index, under the data directory (``runtime.py``: ``data_dir / "procedures"``).
PROCEDURES_DB = Path("procedures") / "procedures.db"

#: The description's text at most: with its title, S2's longest label and the tool's marker it stays inside one Oracle
#: tool entry (``oracle_query_tool._MAX_ENTRY_CHARS``, 1,200), as S4's lessons do.
NATURE_DESCRIPTION_MAX_CHARS = 900
NATURE_NAME_MAX_CHARS = 60
NATURE_TEXT_MAX_CHARS = 120
#: At most this many procedures are read to be listed (a read bound; the text budget usually binds first).
NATURE_LISTED_MAX = 10

_MORE_RESERVE = 48  # room for "And N more in the procedure store."

_DEVELOPED_COUNT_SQL = "SELECT COUNT(*) FROM procedure_records WHERE created_at >= ?"
_DEVELOPED_SQL = (
    "SELECT name, description, evolution_type, is_active, is_negative, total_selections, total_completions, "
    "total_fallbacks, change_summary FROM procedure_records "
    "WHERE created_at >= ? ORDER BY total_completions DESC, created_at, id LIMIT ?"
)
_ACTIVE_SQL = "SELECT COUNT(*) FROM procedure_records WHERE is_active = 1 AND is_negative = 0"


def _one_line(value: object, limit: int) -> str:
    """One line of printable text of at most ``limit`` characters: control and format characters become spaces."""
    if type(value) is not str:
        return ""
    printable = "".join(" " if unicodedata.category(char)[0] == "C" else char for char in value)
    text = " ".join(printable.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _count(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0


@dataclass(frozen=True)
class ProcedureFact:
    """What the description may say about one procedure: never its steps."""

    name: str
    description: str
    evolution: str
    state: str  # "active", "retired" or "an anti-pattern"
    selections: int
    completions: int
    fallbacks: int
    change_summary: str = ""

    @classmethod
    def from_row(cls, row: Any) -> ProcedureFact:
        name, description, evolution, active, negative, selections, completions, fallbacks, summary = row
        state = "an anti-pattern" if negative else ("active" if active else "retired")
        return cls(
            name=_one_line(name, NATURE_NAME_MAX_CHARS) or "(unnamed)",
            description=_one_line(description, NATURE_TEXT_MAX_CHARS),
            evolution=_one_line(evolution, 16).lower() or "captured",
            state=state,
            selections=_count(selections),
            completions=_count(completions),
            fallbacks=_count(fallbacks),
            change_summary=_one_line(summary, NATURE_TEXT_MAX_CHARS),
        )


def _fact_line(fact: ProcedureFact) -> str:
    line = (
        f"- {fact.name}: {fact.description or '(no description)'} ({fact.evolution}, {fact.state}; "
        f"{fact.completions} of {fact.selections} uses completed, {fact.fallbacks} fell back)"
    )
    return f"{line}; changed because: {fact.change_summary}" if fact.change_summary else line


def describe_nature(
    timeline_id: str, started: datetime, facts: tuple[ProcedureFact, ...], *, developed: int, active: int,
) -> PromotionRecord:
    """The nature description entry: a header, one line per procedure that fits, and a count of the rest."""
    if type(timeline_id) is not str or not timeline_id.strip() or len(timeline_id) > EXIT_NOTE_TIMELINE_MAX_CHARS:
        raise ValueError(f"AD-1341 S6: a timeline of 1..{EXIT_NOTE_TIMELINE_MAX_CHARS} characters is required")
    since = started.astimezone(UTC).strftime("%Y-%m-%d")
    lines = [
        f"Procedures this crew developed since {since} (UTC, the ship's first boot): {developed}; "
        f"{active} active in the store at the close.",
        "They stay in the procedure store as nature. This records what they are and why, never their steps.",
    ]
    budget = NATURE_DESCRIPTION_MAX_CHARS - _MORE_RESERVE
    listed = 0
    for fact in facts:
        line = _fact_line(fact)
        if len("\n".join(lines)) + 1 + len(line) > budget:
            break
        lines.append(line)
        listed += 1
    if developed > listed:
        lines.append(f"And {developed - listed} more in the procedure store.")
    return PromotionRecord(
        timeline_id=timeline_id,
        source_kind=SourceKind.NATURE_DESCRIPTION,
        source_ref=f"{NATURE_DESCRIPTION_PREFIX}{timeline_id}",
        title=f"Procedures developed by the crew of timeline {timeline_id}",
        content="\n".join(lines),
        classification="ship",
        metadata={
            "procedures_developed": developed,
            "procedures_active_at_close": active,
            "procedures_listed": listed,
            "generation_started": started.astimezone(UTC).isoformat(),
        },
    )


async def nature_description_record(
    db_path: Path,
    open_read_only: Callable[[str], Awaitable[DatabaseConnection]],
    *,
    timeline_id: str,
    started: datetime,
) -> PromotionRecord | None:
    """The description of the procedures created since ``started``, or None when there is nothing to describe.

    None with no procedure store, or when no procedure was created since ``started``. The store is opened through
    ``open_read_only`` (the CLI passes SQLite's ``mode=ro``), so a missing file is never created and the database's
    own bytes never change. A2 (B-F4): the vessel's store is in WAL mode (``procedure_store.py:211``), and a reader may
    create or touch its ``-wal`` and ``-shm`` files (``storage/sqlite_factory.py:28-31``). Any database error
    propagates, and the reset refuses.
    """
    if not db_path.is_file():  # no procedure store: this generation developed nothing to describe
        return None
    since = started.timestamp()
    db = await open_read_only(str(db_path))
    try:
        cursor = await db.execute(_DEVELOPED_COUNT_SQL, (since,))
        developed = int((await cursor.fetchone())[0])
        if developed == 0:
            return None
        cursor = await db.execute(_DEVELOPED_SQL, (since, NATURE_LISTED_MAX))
        rows = await cursor.fetchall()
        cursor = await db.execute(_ACTIVE_SQL)
        active = int((await cursor.fetchone())[0])
    finally:
        await db.close()
    facts = tuple(ProcedureFact.from_row(row) for row in rows)
    return describe_nature(timeline_id, started, facts, developed=developed, active=active)


async def count_procedures(db_path: Path, open_read_only: Callable[[str], Awaitable[DatabaseConnection]]) -> int:
    """AD-1341 S6 (M3): how many procedures the store holds, for the clean slate's marker; 0 with no store.

    Opened read-only, as ``nature_description_record`` does; any error propagates.
    """
    if not db_path.is_file():
        return 0
    db = await open_read_only(str(db_path))
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM procedure_records")
        return int((await cursor.fetchone())[0])
    finally:
        await db.close()
