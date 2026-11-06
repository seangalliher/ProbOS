"""AD-1358 S1 (#1750): the recorded games between two players, from the AD-526a game records.

``RecreationService._record_game`` writes one Ship's Records document per finished game, at
``recreation/games/<game_type>/<game_id>.md``, tagged ``game`` and the game type. Its
frontmatter names no players and no result; its body does, in a fixed form:
``**Players:** A (X) vs B (O)``, then ``**Result:** won — **A** wins!`` or ``**Result:** draw``.
:func:`parse_game_record` reads that form, and the AD-1358 tests round-trip the writer's own
output through it, so the two cannot drift apart.

:func:`read_head_to_head` reads one game type's records as one reader, through
``RecordsStore.list_entries`` and ``RecordsStore.read_entry``, so a record that reader may not
read is not counted. It returns ``None`` when no game between the two players is recorded,
when more than :data:`MAX_GAME_RECORDS` records of the type are listed, and on any failure.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from probos.cognitive.provenance import iso_utc, record_write_time

logger = logging.getLogger(__name__)

#: The most records of one game type read for one tally. Above it no tally is shown:
#: a count of some of the records would be a wrong count.
MAX_GAME_RECORDS: Final = 256
#: The longest player name the block repeats.
MAX_NAME_CHARS: Final = 64
#: The longest block :meth:`HeadToHead.render` can return, by construction.
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


async def read_head_to_head(
    records_store: Any,
    *,
    game_type: str,
    me: str,
    opponent: str,
    reader_id: str,
    reader_department: str,
) -> HeadToHead | None:
    """The recorded ``game_type`` games between ``me`` and ``opponent``, read as one reader.

    One strict listing of ``recreation/games/<game_type>/`` (a file that cannot be read fails the
    read rather than going uncounted), then at most :data:`MAX_GAME_RECORDS` ``read_entry`` calls
    as ``reader_id``/``reader_department``: a record that reader may not read is not counted.
    ``None`` when nothing is recorded, above the cap, and on any failure.
    """
    if records_store is None or type(me) is not str or type(opponent) is not str:
        return None
    if not me or not opponent or me == opponent:
        return None
    if type(game_type) is not str or _GAME_TYPE.fullmatch(game_type) is None:
        return None
    me_won = opponent_won = drawn = 0
    latest: float | None = None
    try:
        listed = await records_store.list_entries(
            f"recreation/games/{game_type}", tags=["game", game_type], strict=True,
        )
        if len(listed) > MAX_GAME_RECORDS:
            logger.warning(
                "AD-1358: %d %s game records exceed the head-to-head cap of %d; no tally is shown",
                len(listed), game_type, MAX_GAME_RECORDS,
            )
            return None
        for entry in listed:
            doc = await records_store.read_entry(
                entry["path"], reader_id=reader_id, reader_department=reader_department,
            )
            if doc is None:
                continue
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
