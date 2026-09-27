"""AD-1229 (#1202): body-free facts about the DM threads an agent wrote.

A fact here is a stored row: a DM thread the agent authored, who posted in it,
and who wrote elsewhere in the same DM channel afterwards. No statement selects a
body column. The thread statement selects the title only to hand it to
``addressed_callsign``, so the one piece of title text that leaves this module is
the callsign a producer addressed the DM to (A-3); per-author aggregates (count,
first, last) keep the row count bounded by receipts x authors.

What this cannot say, by construction:

* a send that was dropped before it was stored (a cooldown, a similarity gate,
  an unknown callsign) left no row, so an empty page means *nothing is stored*,
  never *not sent*;
* the store keeps no read record for a DM channel, so nothing here reports
  whether a message was read.

It logs nothing and catches nothing: it is a data-access layer, and a database
error propagates to the caller.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.protocols import DatabaseConnection

#: The most receipts one page may hold (the tool's own cap is the same number).
MAX_THREADS = 20
#: The most DM channel names one recipient filter may name.
MAX_CHANNEL_NAMES = 8
MAX_CHANNEL_NAME_CHARS = 64
#: The two producer titles that say whom a DM was sent to: proactive.py ``[DM to @X]``
#: and counselor.py ``[Counselor check-in with @X]``. Only X may leave this module.
_ADDRESSED_TITLE_RE = re.compile(r"\[(?:DM to|Counselor check-in with) @([^\[\]\r\n]{1,64})\]")

_DM_THREADS_HEAD = (
    "SELECT t.id, c.name, t.created_at, t.archived, t.title "
    "FROM threads t JOIN channels c ON c.id = t.channel_id "
    "WHERE c.channel_type = 'dm' AND t.author_id = ? AND t.created_at >= ? "
)
_DM_THREADS_TAIL = "ORDER BY t.created_at DESC, t.id DESC LIMIT ?"
_IN_THREAD_SQL = (
    "SELECT p.thread_id, p.author_id, COUNT(*), MIN(p.created_at), MAX(p.created_at) "
    "FROM posts p JOIN threads t ON t.id = p.thread_id "
    "WHERE p.thread_id IN ({marks}) AND p.deleted = 0 AND p.author_id != t.author_id "
    "GROUP BY p.thread_id, p.author_id"
)
_LATER_THREADS_SQL = (
    "SELECT t.id, o.author_id, COUNT(*), MIN(o.created_at), MAX(o.created_at) "
    "FROM threads t JOIN threads o ON o.channel_id = t.channel_id "
    "AND o.created_at > t.created_at AND o.author_id != t.author_id "
    "WHERE t.id IN ({marks}) "
    "GROUP BY t.id, o.author_id"
)
_LATER_POSTS_SQL = (
    "SELECT t.id, p.author_id, COUNT(*), MIN(p.created_at), MAX(p.created_at) "
    "FROM threads t JOIN threads o ON o.channel_id = t.channel_id AND o.id != t.id "
    "JOIN posts p ON p.thread_id = o.id AND p.created_at > t.created_at "
    "AND p.deleted = 0 AND p.author_id != t.author_id "
    "WHERE t.id IN ({marks}) "
    "GROUP BY t.id, p.author_id"
)


@dataclass(frozen=True)
class AuthorActivity:
    """How often one author wrote, and when first and last."""

    author_id: str
    count: int
    first_at: float
    last_at: float


@dataclass(frozen=True)
class DmThreadFacts:
    """One DM thread the agent wrote. ``thread_id`` is an internal handle, never rendered."""

    thread_id: str
    channel_name: str
    created_at: float
    archived: bool
    in_thread: tuple[AuthorActivity, ...]
    later_in_channel: tuple[AuthorActivity, ...]
    addressed: str | None = None  # the callsign the title addressed (addressed_callsign), never the title


@dataclass(frozen=True)
class DmFactsPage:
    threads: tuple[DmThreadFacts, ...]
    truncated: bool


EMPTY_PAGE = DmFactsPage(threads=(), truncated=False)


def addressed_callsign(title: object) -> str | None:
    """The callsign a producer's DM title names as its recipient, or None -- never any other title text."""
    match = _ADDRESSED_TITLE_RE.fullmatch(title) if isinstance(title, str) else None
    return match.group(1) if match else None


def merge_activity(*groups: tuple[AuthorActivity, ...]) -> tuple[AuthorActivity, ...]:
    """Per author: counts summed, the earliest first and the latest last; ordered by first write."""
    merged: dict[str, AuthorActivity] = {}
    for group in groups:
        for activity in group:
            prior = merged.get(activity.author_id)
            if prior is None:
                merged[activity.author_id] = activity
                continue
            merged[activity.author_id] = AuthorActivity(
                author_id=activity.author_id,
                count=prior.count + activity.count,
                first_at=min(prior.first_at, activity.first_at),
                last_at=max(prior.last_at, activity.last_at),
            )
    return tuple(sorted(merged.values(), key=lambda a: (a.first_at, a.author_id)))


class DmReceiptFacts:
    """Reads the facts over the Ward Room's own connection; writes nothing."""

    def __init__(self, db: DatabaseConnection | None) -> None:
        self._db = db

    async def threads_by_author(
        self,
        author_id: str,
        *,
        since: float,
        limit: int,
        channel_names: tuple[str, ...] = (),
    ) -> DmFactsPage:
        """The newest DM threads ``author_id`` wrote since ``since``, at most ``limit`` of them."""
        if not isinstance(author_id, str) or not author_id:
            raise ValueError("AD-1229: author_id must be a non-empty string; an empty id is not a wildcard")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_THREADS:
            raise ValueError(f"AD-1229: limit must be a whole number from 1 to {MAX_THREADS}")
        if isinstance(since, bool) or not isinstance(since, (int, float)) or not math.isfinite(since):
            raise ValueError("AD-1229: since must be a finite timestamp")
        if (
            not isinstance(channel_names, tuple)
            or len(channel_names) > MAX_CHANNEL_NAMES
            or not all(
                isinstance(name, str) and 0 < len(name) <= MAX_CHANNEL_NAME_CHARS for name in channel_names
            )
        ):
            raise ValueError(
                f"AD-1229: channel_names must be a tuple of at most {MAX_CHANNEL_NAMES} non-empty names "
                f"of at most {MAX_CHANNEL_NAME_CHARS} characters"
            )
        db = self._db
        if db is None:
            return EMPTY_PAGE
        sql = (
            _DM_THREADS_HEAD
            + (f"AND c.name IN ({','.join('?' * len(channel_names))}) " if channel_names else "")
            + _DM_THREADS_TAIL
        )
        params = (author_id, float(since), *channel_names, limit + 1)
        async with db.execute(sql, params) as cursor:
            rows = list(await cursor.fetchall())
        truncated = len(rows) > limit
        rows = rows[:limit]
        if not rows:
            return DmFactsPage(threads=(), truncated=truncated)
        ids = tuple(str(row[0]) for row in rows)
        in_thread = await self._activity(db, _IN_THREAD_SQL, ids)
        later_threads = await self._activity(db, _LATER_THREADS_SQL, ids)
        later_posts = await self._activity(db, _LATER_POSTS_SQL, ids)
        return DmFactsPage(
            threads=tuple(
                DmThreadFacts(
                    thread_id=thread_id,
                    channel_name=str(row[1]),
                    created_at=float(row[2]),
                    archived=bool(row[3]),
                    addressed=addressed_callsign(row[4]),
                    in_thread=in_thread.get(thread_id, ()),
                    later_in_channel=merge_activity(
                        later_threads.get(thread_id, ()), later_posts.get(thread_id, ()),
                    ),
                )
                for thread_id, row in zip(ids, rows)
            ),
            truncated=truncated,
        )

    @staticmethod
    async def _activity(
        db: DatabaseConnection, sql: str, ids: tuple[str, ...],
    ) -> dict[str, tuple[AuthorActivity, ...]]:
        """Run one per-author aggregate over ``ids``; ``{marks}`` only ever holds bound parameters."""
        grouped: dict[str, list[AuthorActivity]] = {}
        async with db.execute(sql.format(marks=",".join("?" * len(ids))), ids) as cursor:
            for thread_id, author_id, count, first_at, last_at in await cursor.fetchall():
                grouped.setdefault(str(thread_id), []).append(
                    AuthorActivity(
                        author_id=str(author_id), count=int(count),
                        first_at=float(first_at), last_at=float(last_at),
                    )
                )
        return {
            thread_id: tuple(sorted(group, key=lambda a: (a.first_at, a.author_id)))
            for thread_id, group in grouped.items()
        }
