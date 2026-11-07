"""AD-1358 S1 (#1750): the recorded games between two players, from the AD-526a game records.

``RecreationService._record_game`` writes one Ship's Records document per finished game, at
``recreation/games/<game_type>/<game_id>.md``, tagged ``game`` and the game type. Its
frontmatter names no players and no result; its body does, in a fixed form:
``**Players:** A (X) vs B (O)``, then ``**Result:** won — **A** wins!`` or ``**Result:** draw``.
:func:`parse_game_record` reads that form, and the AD-1358 tests round-trip the writer's own
output through it, so the two cannot drift apart.

:func:`read_head_to_head` reads one game type's records as one reader, through
``RecordsStore.list_entries`` and ``RecordsStore.read_entry``, so a record that reader may not
read is not counted. The reads run in a worker thread, never on the event loop (A1). It returns
``None`` when no game between the two players is recorded, when more than
:data:`MAX_GAME_RECORDS` ``*.md`` files are counted by name in the directory (then none is read)
or listed, when the count finds a directory that leads out of the records (contract L14), and when
a listing or read raises. The record of the game the tally is shown in is not passed to
``read_entry`` and not counted (A3); the strict listing reads and parses it when it is present
(contract L13).
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from probos.cognitive.provenance import iso_utc, record_write_time

logger = logging.getLogger(__name__)

#: The most records of one game type read for one tally. Above it no tally is shown:
#: a count of some of the records would be a wrong count.
MAX_GAME_RECORDS: Final = 256
#: The longest player name the block repeats.
MAX_NAME_CHARS: Final = 64
#: The longest block :meth:`HeadToHead.render` returns for a tally :func:`read_head_to_head` built:
#: its game type is checked, each count is at most :data:`MAX_GAME_RECORDS` and the name is cut to
#: :data:`MAX_NAME_CHARS` (at most 317 characters). A ``HeadToHead`` built directly is not checked.
MAX_BLOCK_CHARS: Final = 400
HEADER: Final = "--- Previous Games (Ship's Records) ---"

_GAME_TYPE = re.compile(r"[a-z0-9_]{1,32}")
_PLAYERS = re.compile(r"^\*\*Players:\*\* (.+?) \(X\) vs (.+?) \(O\)$", re.MULTILINE)
_RESULT = re.compile(r"^\*\*Result:\*\* (won|draw)(?: — \*\*(.+?)\*\* wins!)?$", re.MULTILINE)


@dataclass(frozen=True)
class GameOutcome:
    """One finished game, as its AD-526a record states it."""

    x_player: str
    o_player: str
    winner: str  # "" for a draw


@dataclass(frozen=True)
class HeadToHead:
    """The recorded games of one type between the reader and ``opponent``, from the reader's side."""

    game_type: str
    opponent: str
    me_won: int
    opponent_won: int
    drawn: int
    last_date: str  # "YYYY-MM-DD" (UTC) of the latest counted record, or "" when none has a date

    @property
    def total(self) -> int:
        return self.me_won + self.opponent_won + self.drawn

    def render(self) -> str:
        """The prompt block: the header, one line, the closing rule."""
        name = self.opponent[:MAX_NAME_CHARS]
        line = (
            f"Recorded {self.game_type} games between you and {name} before this one: {self.total}. "
            f"{name} won {self.opponent_won}, you won {self.me_won}, {self.drawn} drawn."
        )
        if self.last_date:
            line += f" Most recent: {self.last_date}."
        return "\n".join([HEADER, line, "---"])


def parse_game_record(content: Any) -> GameOutcome | None:
    """The players and result of an AD-526a game record's body, or ``None`` when it is not one."""
    if type(content) is not str:
        return None
    players = _PLAYERS.search(content)
    result = _RESULT.search(content)
    if players is None or result is None:
        return None
    x_player, o_player = players.group(1), players.group(2)
    status, winner = result.group(1), result.group(2) or ""
    if status == "draw":
        return GameOutcome(x_player, o_player, "") if not winner else None
    if winner not in (x_player, o_player):
        return None
    return GameOutcome(x_player, o_player, winner)


def _drive(make: Callable[..., Coroutine[Any, Any, Any]], /, *args: Any) -> Any:
    """A1 (F1): run ``make(*args)`` to its end in this worker thread, with no event loop.

    ``RecordsStore.list_entries`` and ``read_entry`` are coroutines that await nothing, so one
    ``send`` runs one to its end. A coroutine that suspends would need an event loop this thread
    does not have: it is closed and ``RuntimeError`` raised, which the caller logs as a failure.
    """
    coro = make(*args)
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    coro.close()
    raise RuntimeError("AD-1358: a records store read suspended; the tally reads only stores that do not")


def _count_record_names(repo_path: Path, directory: str, limit: int) -> int:
    """A3 (F2, F3): the ``*.md`` names the store's strict listing would list under ``directory``, up to ``limit + 1``.

    No file is opened. The walk is ``_markdown_files_or_raise``'s: the resolved ``directory`` is
    listed; an entry that ``is_dir(follow_symlinks=False)`` is descended by its unresolved path,
    never counted; any other entry matching ``*.md`` (``fnmatch``, the platform's case rule) is
    counted; a missing ``directory`` counts 0 and any other ``OSError`` raises. A directory cycle (a
    Windows junction to an ancestor) lengthens the path until the OS refuses it: ``OSError``, as in
    the store's walk. Before each directory is listed, its resolved path must lie inside the resolved
    repository (the rule of ``RecordsStore._safe_path``; the store has no public path check), else
    ``ValueError``. For a layout that does not change during the pass, nothing outside the records is
    listed, a refusal never reaches the store, and the count is the number of paths that walk lists. A
    directory replaced by an outside link after its check is listed, names only (contract L14).
    """
    root = Path(repo_path).resolve()
    top = Path(repo_path, directory).resolve()
    count = 0
    pending = [top]
    while pending:
        current = pending.pop()
        # The rule of RecordsStore._safe_path, applied to every directory before it is listed.
        if not current.resolve().is_relative_to(root):
            raise ValueError(f"AD-1358: path traversal denied: {directory!r}")
        try:
            listing = os.scandir(current)
        except (FileNotFoundError, NotADirectoryError):
            if current is not top:
                raise  # as the store's walk: a directory a listing reported is never "no records"
            return 0
        with listing:
            for entry in listing:
                if entry.is_dir(follow_symlinks=False):
                    # Unresolved, as the store descends: a cycle grows the path until the OS refuses it.
                    pending.append(Path(current, entry.name))
                elif fnmatch.fnmatch(entry.name, "*.md"):
                    count += 1
                    if count > limit:
                        return count
    return count


async def _read_records(
    records_store: Any, game_type: str, reader_id: str, reader_department: str, current_record: str,
) -> list[dict[str, Any]] | None:
    """The records of one game type that the reader may read, or ``None`` above the cap.

    Run by :func:`_drive` in a worker thread. The directory's ``*.md`` names are counted first
    (:func:`_count_record_names`, which opens no file and refuses a directory it finds outside the
    records), so a directory above the cap costs one scan and no reads. Files are then read only
    through the store's own ``list_entries`` and ``read_entry``, which touch no store state but the
    repository path, so they are safe off the event loop, as BF-952's ``_search_records`` walk is. The
    listing reads every file present when it runs, including any created after the count (contract
    L13) and any below a subdirectory replaced by an outside link after the count; ``read_entry``
    refuses such a path if it reaches it (contract L14) and still runs at most
    :data:`MAX_GAME_RECORDS` times. The entry named ``current_record``, the record of the game the
    tally is shown in, is not passed to ``read_entry`` and not counted (A3).
    """
    directory = f"recreation/games/{game_type}"
    if _count_record_names(records_store.repo_path, directory, MAX_GAME_RECORDS) > MAX_GAME_RECORDS:
        logger.warning(
            "AD-1358: more than %d %s game records; no head-to-head tally is shown",
            MAX_GAME_RECORDS, game_type,
        )
        return None
    listed = await records_store.list_entries(
        directory, tags=["game", game_type], strict=True,
    )
    if len(listed) > MAX_GAME_RECORDS:
        logger.warning(
            "AD-1358: %d %s game records exceed the head-to-head cap of %d; no tally is shown",
            len(listed), game_type, MAX_GAME_RECORDS,
        )
        return None
    docs: list[dict[str, Any]] = []
    for entry in listed:
        # A3 (F1): the game the tally is shown in may finish, and be recorded, during this pass.
        if entry["path"].rpartition("/")[2] == current_record:
            continue
        doc = await records_store.read_entry(
            entry["path"], reader_id=reader_id, reader_department=reader_department,
        )
        if doc is not None:
            docs.append(doc)
    return docs


async def read_head_to_head(
    records_store: Any,
    *,
    game_type: str,
    me: str,
    opponent: str,
    reader_id: str,
    reader_department: str,
    current_game_id: str = "",
) -> HeadToHead | None:
    """The recorded ``game_type`` games between ``me`` and ``opponent``, read as one reader.

    A count by name of ``recreation/games/<game_type>/*.md`` (refused when it finds a directory that
    leads out of the records; contract L14), then one strict listing, then at most
    :data:`MAX_GAME_RECORDS` ``read_entry`` calls as ``reader_id``/``reader_department``, all in a
    worker thread (:func:`_read_records`): a record that reader may not read is not counted. The
    record ``<current_game_id>.md``, the game the tally is shown in, is not passed to ``read_entry``
    and not counted (A3). A listing or read that raises gives ``None`` and a
    warning. A file the store's listing itself skips (bytes that are not UTF-8, a frontmatter whose
    constructor raises) and a ``read_entry`` that returns ``None`` are not counted (contract L11).
    ``None`` when nothing is recorded and above the cap. While the directory does not grow during the
    pass, it reads at most 2 × :data:`MAX_GAME_RECORDS` files; the listing also reads any file created
    after the count (L13). A cancelled caller gets ``CancelledError`` at once; the worker finishes
    its pass and its result is dropped.
    """
    if records_store is None or type(me) is not str or type(opponent) is not str:
        return None
    if not me or not opponent or me == opponent:
        return None
    if type(game_type) is not str or _GAME_TYPE.fullmatch(game_type) is None:
        return None
    current_record = f"{current_game_id}.md" if type(current_game_id) is str and current_game_id else ""
    me_won = opponent_won = drawn = 0
    latest: float | None = None
    try:
        # A1 (F1): every file read and parse runs in a worker thread, never on the event loop.
        read_args = (_read_records, records_store, game_type, reader_id, reader_department, current_record)
        docs = await asyncio.to_thread(_drive, *read_args)
        if docs is None:
            return None
        for doc in docs:
            outcome = parse_game_record(doc.get("content"))
            if outcome is None or {outcome.x_player, outcome.o_player} != {me, opponent}:
                continue
            if outcome.winner == me:
                me_won += 1
            elif outcome.winner == opponent:
                opponent_won += 1
            else:
                drawn += 1
            written = record_write_time(doc.get("frontmatter"))
            if written is not None and (latest is None or written > latest):
                latest = written
    except Exception:
        logger.warning(
            "AD-1358: the %s game records could not be read for a head-to-head tally; none is shown",
            game_type, exc_info=True,
        )
        return None
    if me_won + opponent_won + drawn == 0:
        return None
    return HeadToHead(
        game_type=game_type,
        opponent=opponent,
        me_won=me_won,
        opponent_won=opponent_won,
        drawn=drawn,
        last_date=iso_utc(latest)[:10] if latest is not None else "",
    )
