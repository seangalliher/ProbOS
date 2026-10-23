"""AD-1347 S4 (#1627): one Ward Room thread or post by id, live or in the prune archive.

Crew asked the Captain for reads such as "thread 51d91a7d" or "was that post deleted".
A thread older than ``ward_room.retention_days`` is pruned from the database into the
monthly ``ward_room_archive_<month>.jsonl`` files (AD-416), and nothing read them back.

``WardRoomRecordLookup`` is that read. It finds candidates by id prefix (the live
``threads`` and ``posts`` tables, then a bounded scan of the archive) and keeps only the
ones the asker may see, by AD-621's rule: a member of the record's channel sees it, and
in a DM channel an author of the thread or of a post in it does too (AD-485's Captain
DM channels are created with no membership rows). A record the asker may not see is
reported exactly as one that does not exist. A blank asker, a visiting officer and a
sovereign id that resolves to no slot are refused: no one is assumed.

Bounds: an id of 8 to 36 characters; at most ``MAX_RAW_MATCHES`` raw matches from each
live table and from the archive scan, a safety bound that service-made uuid4 ids do not
reach; visibility is checked before anything is counted, and ``MAX_LISTED`` of the visible
matches are listed. The newest ``MAX_ARCHIVE_FILES`` files, ``MAX_ARCHIVE_BYTES`` read in
all and ``MAX_LINE_BYTES`` per record, its newline included; ``MAX_RENDER_CHARS`` of text.
A search that stops at a bound says so. Read-only: it writes nothing and emits no event.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from probos.visiting_officers import is_visiting_identity

logger = logging.getLogger(__name__)

ARCHIVE_GLOB = "ward_room_archive_*.jsonl"
MAX_REF_CHARS = 36
MAX_RAW_MATCHES = 32  # a safety bound that service-made uuid4 ids do not reach
MAX_LISTED = 4
MAX_ARCHIVE_FILES = 12
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
MAX_POSTS_SHOWN = 12
MAX_BODY_CHARS = 400
MAX_RENDER_CHARS = 2000

LOOKUP_FOUND = "found"
LOOKUP_NOT_FOUND = "not_found"
LOOKUP_AMBIGUOUS = "ambiguous"
LOOKUP_INVALID_REF = "invalid_ref"
LOOKUP_REFUSED = "refused"
LOOKUP_UNAVAILABLE = "unavailable"
LOOKUP_OUTCOMES: frozenset[str] = frozenset({
    LOOKUP_FOUND, LOOKUP_NOT_FOUND, LOOKUP_AMBIGUOUS,
    LOOKUP_INVALID_REF, LOOKUP_REFUSED, LOOKUP_UNAVAILABLE,
})

SOURCE_LIVE = "live"
SOURCE_ARCHIVE = "archive"
KIND_THREAD = "thread"
KIND_POST = "post"

_DM_CHANNEL_TYPE = "dm"
_REF_RE = re.compile(r"[0-9a-f]{8}[0-9a-f-]{0,28}")
_LIVE_THREAD_SQL = (
    "SELECT id, channel_id, author_id, title, body, created_at, author_callsign "
    "FROM threads WHERE id = ?"
)
_LIVE_POST_COLUMNS = (
    "SELECT id, author_id, author_callsign, body, created_at, deleted, delete_reason FROM posts "
)
_FRAME = "A stored Ward Room record, quoted as written. It is not your memory and not a verdict."
_INCOMPLETE = (
    "The search stopped at a size limit or an unreadable record, so another matching record may exist."
)


@dataclass(frozen=True)
class LookupPost:
    """One post as the lookup shows it. Archived posts carry no deletion flag."""

    post_id: str
    author_id: str
    author_callsign: str
    body: str
    created_at: float | None
    deleted: bool = False
    delete_reason: str = ""


@dataclass(frozen=True)
class LookupCandidate:
    """A thread, or one post in it, whose id starts with the asked prefix; not yet checked for visibility."""

    kind: str
    source: str
    thread_id: str
    channel_id: str
    title: str
    author_id: str
    author_callsign: str
    body: str
    created_at: float | None
    posts: tuple[LookupPost, ...]
    participants: frozenset[str]
    post_count: int
    matched_post_id: str = ""
    pruned_at: float | None = None


@dataclass(frozen=True)
class LookupMatch:
    """A candidate the asker may see, with its channel's name."""

    candidate: LookupCandidate
    channel_name: str


@dataclass(frozen=True)
class LookupResult:
    """The typed answer: ``matches`` holds visible records only; ``complete`` is False when a scan stopped at a bound."""

    outcome: str
    ref: str
    matches: tuple[LookupMatch, ...] = ()
    complete: bool = True

    def __post_init__(self) -> None:
        if self.outcome not in LOOKUP_OUTCOMES:
            raise ValueError(f"AD-1347: unknown lookup outcome {self.outcome!r}")
        if self.outcome == LOOKUP_FOUND and len(self.matches) != 1:
            raise ValueError("AD-1347: a found lookup holds exactly one match")
        if self.outcome == LOOKUP_AMBIGUOUS and len(self.matches) < 2:
            raise ValueError("AD-1347: an ambiguous lookup holds at least two matches")
        if self.outcome not in (LOOKUP_FOUND, LOOKUP_AMBIGUOUS) and self.matches:
            raise ValueError("AD-1347: only a found or ambiguous lookup holds matches")


class ChannelReader(Protocol):
    """``ChannelManager.get_channel``: a channel by id, or None."""

    async def get_channel(self, channel_id: str) -> Any: ...


class MemberReader(Protocol):
    """``MessageStore.get_channel_subscriber_ids``: AD-621's members of a channel."""

    async def get_channel_subscriber_ids(self, channel_id: str) -> set[str]: ...


def normalize_ref(ref: object) -> str | None:
    """The id prefix ``ref`` names, in lower case, or None when it is not 8 to 36 id characters."""
    if type(ref) is not str:
        return None
    text = ref.strip().lower().removeprefix("#")
    return text if _REF_RE.fullmatch(text) is not None else None


def _text(value: object) -> str:
    return value if type(value) is str else ""


def _number(value: object) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


async def live_candidates(db: Any, ref: str) -> tuple[list[LookupCandidate], bool]:
    """Live threads, then live posts, whose id starts with ``ref``, unfiltered.

    The flag is False when either prefix query reached ``MAX_RAW_MATCHES`` rows: more may exist.
    """
    async with db.execute(
        "SELECT id FROM threads WHERE substr(id, 1, ?) = ? LIMIT ?", (len(ref), ref, MAX_RAW_MATCHES),
    ) as cursor:
        thread_ids = [row[0] async for row in cursor]
    async with db.execute(
        "SELECT id, thread_id FROM posts WHERE substr(id, 1, ?) = ? LIMIT ?", (len(ref), ref, MAX_RAW_MATCHES),
    ) as cursor:
        post_rows = [(row[0], row[1]) async for row in cursor]
    complete = len(thread_ids) < MAX_RAW_MATCHES and len(post_rows) < MAX_RAW_MATCHES
    candidates: list[LookupCandidate] = []
    for thread_id in thread_ids:
        candidate = await _live_candidate(db, thread_id, "")
        if candidate is not None:
            candidates.append(candidate)
    for post_id, thread_id in post_rows:
        candidate = await _live_candidate(db, thread_id, post_id)
        if candidate is not None:
            candidates.append(candidate)
    return candidates, complete


async def _live_candidate(db: Any, thread_id: str, matched_post_id: str) -> LookupCandidate | None:
    """The live thread ``thread_id`` with its last posts, or with only ``matched_post_id`` when one is named."""
    async with db.execute(_LIVE_THREAD_SQL, (thread_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    async with db.execute("SELECT DISTINCT author_id FROM posts WHERE thread_id = ?", (thread_id,)) as cursor:
        authors = [_text(author[0]) async for author in cursor]
    async with db.execute("SELECT COUNT(*) FROM posts WHERE thread_id = ?", (thread_id,)) as cursor:
        count_row = await cursor.fetchone()
    params: tuple[Any, ...]
    if matched_post_id:
        sql = _LIVE_POST_COLUMNS + "WHERE id = ?"
        params = (matched_post_id,)
    else:
        sql = _LIVE_POST_COLUMNS + "WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?"
        params = (thread_id, MAX_POSTS_SHOWN)
    async with db.execute(sql, params) as cursor:
        posts = [_live_post(post_row) async for post_row in cursor]
    posts.reverse()
    author_id = _text(row[2])
    return LookupCandidate(
        kind=KIND_POST if matched_post_id else KIND_THREAD,
        source=SOURCE_LIVE,
        thread_id=_text(row[0]),
        channel_id=_text(row[1]),
        title=_text(row[3]),
        author_id=author_id,
        author_callsign=_text(row[6]),
        body=_text(row[4]),
        created_at=_number(row[5]),
        posts=tuple(posts),
        participants=frozenset(a for a in (author_id, *authors) if a),
        post_count=int(count_row[0]) if count_row else 0,
        matched_post_id=matched_post_id,
    )


def _live_post(row: Any) -> LookupPost:
    return LookupPost(
        post_id=_text(row[0]),
        author_id=_text(row[1]),
        author_callsign=_text(row[2]),
        body=_text(row[3]),
        created_at=_number(row[4]),
        deleted=bool(row[5]),
        delete_reason=_text(row[6]),
    )


def scan_archive(archive_dir: Any, ref: str) -> tuple[list[LookupCandidate], bool]:
    """Archived threads and posts whose id starts with ``ref``, newest month first. Synchronous; run it off the loop.

    Returns the candidates, before any visibility check, and whether every archive file was
    read to its end. A directory nothing was pruned into yet is an empty archive. No known
    directory, an unreadable file, a record over ``MAX_LINE_BYTES`` with its newline, an
    unterminated last line (the writer ends every record with a newline, so it is torn,
    whatever it holds), a line that is not a record, or ``MAX_RAW_MATCHES`` reached makes the
    scan incomplete. Termination and length are checked before the id prefilter, so
    completeness never depends on the id asked. Never raises ``OSError`` once the directory
    check has run.
    """
    if archive_dir is None:
        return [], False
    root = Path(archive_dir)
    if not root.is_dir():
        return [], True
    try:
        files = sorted((p for p in root.glob(ARCHIVE_GLOB) if p.is_file()), key=lambda p: p.name, reverse=True)
    except OSError:
        logger.warning("AD-1347: the Ward Room archive at %s could not be listed", root, exc_info=True)
        return [], False
    complete = len(files) <= MAX_ARCHIVE_FILES
    thread_marker = b'"thread_id": "' + ref.encode("ascii")
    post_marker = b'"id": "' + ref.encode("ascii")
    budget = MAX_ARCHIVE_BYTES
    found: list[LookupCandidate] = []
    for path in files[:MAX_ARCHIVE_FILES]:
        try:
            with open(path, "rb") as handle:
                while True:
                    if budget <= 0:
                        return found, False
                    line = handle.readline(MAX_LINE_BYTES + 1)
                    if not line:
                        break
                    budget -= len(line)
                    if not line.endswith(b"\n"):  # a torn tail, or the head of an over-cap record
                        complete = False
                        if len(line) > MAX_LINE_BYTES:  # the rest of an over-cap record is still unread
                            budget = _skip_rest_of_line(handle, budget)
                        continue
                    if len(line) > MAX_LINE_BYTES:  # the cap counts the record's newline
                        complete = False
                        continue
                    if thread_marker not in line and post_marker not in line:
                        continue
                    parsed = _archived_candidates(line, ref)
                    if parsed is None:
                        complete = False
                        continue
                    found.extend(parsed)
                    if len(found) >= MAX_RAW_MATCHES:
                        return found, False
        except OSError:
            logger.warning("AD-1347: the Ward Room archive file %s could not be read", path, exc_info=True)
            complete = False
    return found, complete


def _skip_rest_of_line(handle: BinaryIO, budget: int) -> int:
    """Read past the rest of an oversized record without holding it; returns the budget left."""
    while budget > 0:
        chunk = handle.readline(MAX_LINE_BYTES)
        budget -= len(chunk)
        if not chunk or chunk.endswith(b"\n"):
            break
    return budget


def _archived_candidates(line: bytes, ref: str) -> list[LookupCandidate] | None:
    """The thread and the posts in one archive record that match ``ref``; None for a line that is not a record."""
    try:
        record = json.loads(line)
    except MemoryError:
        raise
    except Exception:  # a torn tail during an append, or a hand edit: not a record, and never fatal
        return None
    if not isinstance(record, dict):
        return None
    thread_id = _text(record.get("thread_id"))
    channel_id = _text(record.get("channel_id"))
    if not thread_id or not channel_id:
        return None
    raw_posts = record.get("posts")
    listed = [_archived_post(p) for p in raw_posts if isinstance(p, dict)] if isinstance(raw_posts, list) else []
    posts = sorted(listed, key=lambda p: p.created_at or 0.0)
    author_id = _text(record.get("author_id"))
    participants = frozenset(a for a in (author_id, *(p.author_id for p in posts)) if a)

    def _candidate(kind: str, shown: tuple[LookupPost, ...], matched_post_id: str = "") -> LookupCandidate:
        return LookupCandidate(
            kind=kind,
            source=SOURCE_ARCHIVE,
            thread_id=thread_id,
            channel_id=channel_id,
            title=_text(record.get("title")),
            author_id=author_id,
            author_callsign=_text(record.get("author_callsign")),
            body=_text(record.get("body")),
            created_at=_number(record.get("created_at")),
            posts=shown,
            participants=participants,
            post_count=len(posts),
            matched_post_id=matched_post_id,
            pruned_at=_number(record.get("pruned_at")),
        )

    matched: list[LookupCandidate] = []
    if thread_id.startswith(ref):
        matched.append(_candidate(KIND_THREAD, tuple(posts[-MAX_POSTS_SHOWN:])))
    for post in posts:
        if post.post_id.startswith(ref):
            matched.append(_candidate(KIND_POST, (post,), post.post_id))
    return matched


def _archived_post(raw: dict) -> LookupPost:
    return LookupPost(
        post_id=_text(raw.get("id")),
        author_id=_text(raw.get("author_id")),
        author_callsign=_text(raw.get("author_callsign")),
        body=_text(raw.get("body")),
        created_at=_number(raw.get("created_at")),
    )


def render_lookup(result: LookupResult) -> str:
    """The chain's text for ``result``: the record, or one line saying why there is none.

    "Not found" reads the same whether the record is absent or not visible to the asker.
    """
    if result.outcome == LOOKUP_FOUND:
        text = "\n".join([_FRAME, *_match_lines(result.matches[0])])
    elif result.outcome == LOOKUP_AMBIGUOUS:
        more = len(result.matches) - MAX_LISTED
        text = "\n".join([
            f"More than one Ward Room thread or post you can see starts with {result.ref}; "
            "look it up again with more of its id:",
            *(_summary_line(match) for match in result.matches[:MAX_LISTED]),
            *([f"- and {more} more you can see"] if more > 0 else []),
        ])
    elif result.outcome == LOOKUP_NOT_FOUND:
        text = f"No Ward Room thread or post with id {result.ref} that you can see is in the Ward Room or its archive."
    elif result.outcome == LOOKUP_INVALID_REF:
        text = f"'{result.ref}' is not a Ward Room id: give 8 to 36 characters of a thread or post id, such as 51d91a7d."
    elif result.outcome == LOOKUP_REFUSED:
        text = "The Ward Room lookup could not confirm who is asking, so it returned nothing."
    else:
        text = "The Ward Room is not available, so the lookup returned nothing."
    if result.complete:
        return text[:MAX_RENDER_CHARS]
    return text[: MAX_RENDER_CHARS - len(_INCOMPLETE) - 1] + "\n" + _INCOMPLETE


def _match_lines(match: LookupMatch) -> list[str]:
    found = match.candidate
    if found.source == SOURCE_LIVE:
        where = "the live Ward Room"
    elif found.pruned_at is not None:
        where = f"the Ward Room archive (pruned {_utc(found.pruned_at)})"
    else:
        where = "the Ward Room archive"
    if found.kind == KIND_POST:
        return [
            f"Post {found.matched_post_id} in thread {found.thread_id}, #{match.channel_name}, from {where}.",
            f"Thread title: {_clip(found.title, MAX_BODY_CHARS)}",
            *(_post_line(post) for post in found.posts),
        ]
    if found.post_count > len(found.posts):
        replies = f"{found.post_count} replies; the last {len(found.posts)}:"
    else:
        replies = f"{found.post_count} replies:"
    return [
        f"Thread {found.thread_id}, #{match.channel_name}, from {where}.",
        f"Title: {_clip(found.title, MAX_BODY_CHARS)}",
        f"Opened by {_who(found.author_callsign, found.author_id)} at {_utc(found.created_at)}: "
        f"{_clip(found.body, MAX_BODY_CHARS)}",
        replies,
        *(_post_line(post) for post in found.posts),
    ]


def _summary_line(match: LookupMatch) -> str:
    found = match.candidate
    record_id = found.matched_post_id or found.thread_id
    return f"- {found.kind} {record_id} in #{match.channel_name}: {_clip(found.title, 80)}"


def _post_line(post: LookupPost) -> str:
    who = _who(post.author_callsign, post.author_id)
    if post.deleted:
        reason = f": {_clip(post.delete_reason, 120)}" if post.delete_reason else ""
        return f"- {who} at {_utc(post.created_at)}: [deleted{reason}]"
    return f"- {who} at {_utc(post.created_at)}: {_clip(post.body, MAX_BODY_CHARS)}"


def _who(callsign: str, author_id: str) -> str:
    return callsign or author_id[:8] or "unknown"


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _utc(value: float | None) -> str:
    if value is None:
        return "an unknown time"
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return "an unknown time"


class WardRoomRecordLookup:
    """AD-1347 S4: the asker's view of one thread or post by id. ``WardRoomService.lookup_record`` builds one per call."""

    def __init__(
        self,
        *,
        db: Any,
        channels: ChannelReader | None,
        members: MemberReader | None,
        identity_registry: Any = None,
    ) -> None:
        self._db = db
        self._channels = channels
        self._members = members
        self._identity_registry = identity_registry

    async def lookup(self, requester_id: object, ref: object, *, archive_dir: Any = None) -> LookupResult:
        """The record ``ref`` names, if ``requester_id`` may see it. A bad input is a typed outcome, never a raise."""
        requester = self._requester(requester_id)
        normalized = normalize_ref(ref)
        if requester is None:
            result = LookupResult(LOOKUP_REFUSED, "")
        elif normalized is None:
            result = LookupResult(LOOKUP_INVALID_REF, _clip(ref if isinstance(ref, str) else "", MAX_REF_CHARS + 4))
        elif self._db is None or self._channels is None or self._members is None:
            result = LookupResult(LOOKUP_UNAVAILABLE, normalized)
        else:
            result = await self._find(requester, normalized, archive_dir)
        logger.info(
            "AD-1347: Ward Room lookup by %s for %r: %s (%d visible)",
            requester or "<refused>", result.ref, result.outcome, len(result.matches),
        )
        return result

    def _requester(self, requester_id: object) -> str | None:
        """The slot a lookup is asked for, or None: blank, a visiting officer, or an unresolved sovereign id."""
        if type(requester_id) is not str or not requester_id.strip():
            return None
        if is_visiting_identity(self._identity_registry, requester_id):
            return None
        from probos.identity import is_sovereign_identity_key  # at use, as visiting_officers imports it

        if not is_sovereign_identity_key(requester_id):
            return requester_id
        if self._identity_registry is None:
            return None
        slot = self._identity_registry.resolve_slot_id(requester_id)
        return slot if type(slot) is str and slot else None

    async def _find(self, requester: str, ref: str, archive_dir: Any) -> LookupResult:
        live, complete = await live_candidates(self._db, ref)
        visible = await self._visible(requester, live)
        if not visible:
            archived, archive_complete = await asyncio.to_thread(scan_archive, archive_dir, ref)
            visible = await self._visible(requester, archived)
            complete = complete and archive_complete
        if len(visible) == 1:
            return LookupResult(LOOKUP_FOUND, ref, tuple(visible), complete)
        if visible:
            return LookupResult(LOOKUP_AMBIGUOUS, ref, tuple(visible), complete)
        return LookupResult(LOOKUP_NOT_FOUND, ref, (), complete)

    async def _visible(self, requester: str, candidates: list[LookupCandidate]) -> list[LookupMatch]:
        """AD-621's rule for each candidate; an unknown channel is visible to no one."""
        visible: list[LookupMatch] = []
        for candidate in candidates:
            channel = await self._channels.get_channel(candidate.channel_id)
            if channel is None:
                continue
            members = await self._members.get_channel_subscriber_ids(candidate.channel_id)
            in_dm = channel.channel_type == _DM_CHANNEL_TYPE and requester in candidate.participants
            if requester in members or in_dm:
                visible.append(LookupMatch(candidate=candidate, channel_name=channel.name))
        return visible
