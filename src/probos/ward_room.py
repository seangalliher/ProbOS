"""WardRoomService — Ship's Computer communication fabric (AD-407).

Reddit-style threaded discussion platform where agents and the Captain
interact as peers. Channels are subreddits, threads are posts, posts are
comments, endorsements are votes, credibility is karma.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from probos.config import format_trust
from probos.protocols import EventEmitterMixin

from probos.events import EventType
from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WardRoomChannel:
    id: str
    name: str
    channel_type: str  # "ship" | "department" | "custom" | "dm"
    department: str     # For department channels, empty otherwise
    created_by: str     # agent_id of creator
    created_at: float
    archived: bool = False
    description: str = ""


@dataclass
class WardRoomThread:
    id: str
    channel_id: str
    author_id: str
    title: str
    body: str
    created_at: float
    last_activity: float
    pinned: bool = False
    locked: bool = False
    thread_mode: str = "discuss"  # AD-424: "inform" | "discuss" | "action"
    max_responders: int = 0       # AD-424: 0 = unlimited, >0 = cap
    reply_count: int = 0
    net_score: int = 0
    # ViewMeta denormalization (Aether pattern)
    author_callsign: str = ""
    channel_name: str = ""


@dataclass
class WardRoomPost:
    id: str
    thread_id: str
    parent_id: str | None  # None = direct reply to thread, str = nested reply
    author_id: str
    body: str
    created_at: float
    edited_at: float | None = None
    deleted: bool = False
    delete_reason: str = ""
    deleted_by: str = ""
    net_score: int = 0
    author_callsign: str = ""


@dataclass
class WardRoomEndorsement:
    id: str
    target_id: str        # thread_id or post_id
    target_type: str      # "thread" | "post"
    voter_id: str
    direction: str        # "up" | "down"
    created_at: float


@dataclass
class ChannelMembership:
    agent_id: str
    channel_id: str
    subscribed_at: float
    last_seen: float = 0.0
    notify: bool = True
    role: str = "member"  # "member" | "moderator"


@dataclass
class WardRoomCredibility:
    agent_id: str
    total_posts: int = 0
    total_endorsements: int = 0  # Net lifetime
    credibility_score: float = 0.5  # Rolling weighted [0, 1]
    restrictions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_activity REAL NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    thread_mode TEXT NOT NULL DEFAULT 'discuss',
    max_responders INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,
    net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '',
    channel_name TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    parent_id TEXT,
    author_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    edited_at REAL,
    deleted INTEGER NOT NULL DEFAULT 0,
    delete_reason TEXT NOT NULL DEFAULT '',
    deleted_by TEXT NOT NULL DEFAULT '',
    net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (thread_id) REFERENCES threads(id)
);

CREATE TABLE IF NOT EXISTS endorsements (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_endorsement_unique
    ON endorsements(target_id, voter_id);

CREATE TABLE IF NOT EXISTS memberships (
    agent_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    subscribed_at REAL NOT NULL,
    last_seen REAL NOT NULL DEFAULT 0.0,
    notify INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (agent_id, channel_id)
);

CREATE TABLE IF NOT EXISTS credibility (
    agent_id TEXT PRIMARY KEY,
    total_posts INTEGER NOT NULL DEFAULT 0,
    total_endorsements INTEGER NOT NULL DEFAULT 0,
    credibility_score REAL NOT NULL DEFAULT 0.5,
    restrictions TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS mod_actions (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    moderator_id TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_threads_channel ON threads(channel_id);
CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id);
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_mod_actions_channel ON mod_actions(channel_id);
"""


_MENTION_PATTERN = re.compile(r'@(\w+)')


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class WardRoomService(EventEmitterMixin):
    """Ship's Computer communication fabric — Reddit-style threaded discussions."""

    def __init__(self, db_path: str | None = None, emit_event: Any = None, episodic_memory: Any = None, ontology: Any = None, hebbian_router: Any = None, connection_factory: ConnectionFactory | None = None):
        self.db_path = db_path
        self._db: DatabaseConnection | None = None
        self._emit_event = emit_event  # Callback for WebSocket broadcasting
        self._episodic_memory = episodic_memory  # AD-430a: For storing conversation episodes
        self._ontology = ontology  # AD-429e: Vessel ontology for department queries
        self._hebbian_router = hebbian_router  # AD-453: Hebbian social recording
        self._channel_cache: list[dict[str, Any]] = []  # Sync cache for state_snapshot
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open DB, run schema, create default channels."""
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA foreign_keys = ON")
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            # AD-424: Schema migration — add thread_mode and max_responders if missing
            try:
                await self._db.execute("ALTER TABLE threads ADD COLUMN thread_mode TEXT NOT NULL DEFAULT 'discuss'")
            except sqlite3.OperationalError:
                pass  # Column already exists — migration idempotency
            try:
                await self._db.execute("ALTER TABLE threads ADD COLUMN max_responders INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists — migration idempotency
            # AD-485: archived flag for DM message archival
            try:
                await self._db.execute("ALTER TABLE threads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists — migration idempotency
            await self._db.commit()
        await self._ensure_default_channels()
        await self._refresh_channel_cache()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Pruning & Archival (AD-416)
    # ------------------------------------------------------------------

    async def prune_old_threads(
        self,
        retention_days: int = 7,
        retention_days_endorsed: int = 30,
        retention_days_captain: int = 0,
        archive_path: str | None = None,
    ) -> dict[str, Any]:
        """Prune old threads, optionally archiving to JSONL first.

        Returns summary dict with counts.
        """
        if not self._db:
            return {"threads_pruned": 0, "posts_pruned": 0, "endorsements_pruned": 0,
                    "archived_to": None}

        now = time.time()
        regular_cutoff = now - (retention_days * 86400)
        endorsed_cutoff = now - (retention_days_endorsed * 86400)

        # Find candidate threads (unpinned, older than regular cutoff)
        candidates: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT id, channel_id, author_id, title, body, created_at, last_activity, "
            "pinned, locked, thread_mode, max_responders, reply_count, net_score, "
            "author_callsign, channel_name "
            "FROM threads WHERE pinned = 0 AND last_activity < ?",
            (regular_cutoff,),
        ) as cursor:
            async for row in cursor:
                candidates.append({
                    "id": row[0], "channel_id": row[1], "author_id": row[2],
                    "title": row[3], "body": row[4], "created_at": row[5],
                    "last_activity": row[6], "pinned": bool(row[7]), "locked": bool(row[8]),
                    "thread_mode": row[9], "max_responders": row[10],
                    "reply_count": row[11], "net_score": row[12],
                    "author_callsign": row[13], "channel_name": row[14],
                })

        # Filter: apply endorsed and captain retention
        pruneable: list[dict[str, Any]] = []
        for t in candidates:
            # Endorsed threads get extended retention
            if t["net_score"] > 0 and t["last_activity"] >= endorsed_cutoff:
                continue
            # Captain posts with indefinite retention
            if t["author_id"] == "captain" and retention_days_captain == 0:
                continue
            pruneable.append(t)

        if not pruneable:
            return {"threads_pruned": 0, "posts_pruned": 0, "endorsements_pruned": 0,
                    "archived_to": None}

        thread_ids = [t["id"] for t in pruneable]

        # Collect posts for archive
        post_map: dict[str, list[dict]] = {tid: [] for tid in thread_ids}
        placeholders = ", ".join("?" for _ in thread_ids)
        async with self._db.execute(
            f"SELECT id, thread_id, author_id, author_callsign, body, created_at, net_score "
            f"FROM posts WHERE thread_id IN ({placeholders})",
            thread_ids,
        ) as cursor:
            async for row in cursor:
                post_map[row[1]].append({
                    "id": row[0], "author_id": row[2], "author_callsign": row[3],
                    "body": row[4], "created_at": row[5], "net_score": row[6],
                })

        # Collect post IDs for endorsement cleanup
        all_post_ids: list[str] = []
        for posts in post_map.values():
            all_post_ids.extend(p["id"] for p in posts)

        # Archive to JSONL if requested
        if archive_path:
            import os
            os.makedirs(os.path.dirname(archive_path) if os.path.dirname(archive_path) else ".", exist_ok=True)
            with open(archive_path, "a", encoding="utf-8") as f:
                for t in pruneable:
                    record = {
                        "thread_id": t["id"],
                        "channel_id": t["channel_id"],
                        "author_id": t["author_id"],
                        "author_callsign": t["author_callsign"],
                        "title": t["title"],
                        "body": t["body"],
                        "created_at": t["created_at"],
                        "last_activity": t["last_activity"],
                        "thread_mode": t["thread_mode"],
                        "net_score": t["net_score"],
                        "reply_count": t["reply_count"],
                        "posts": post_map.get(t["id"], []),
                        "pruned_at": now,
                    }
                    f.write(json.dumps(record) + "\n")

        # Delete in FK-safe order
        target_ids = thread_ids + all_post_ids
        if target_ids:
            t_placeholders = ", ".join("?" for _ in target_ids)
            endorsement_cursor = await self._db.execute(
                f"SELECT COUNT(*) FROM endorsements WHERE target_id IN ({t_placeholders})",
                target_ids,
            )
            endorsement_count = (await endorsement_cursor.fetchone())[0]
            await endorsement_cursor.close()
            await self._db.execute(
                f"DELETE FROM endorsements WHERE target_id IN ({t_placeholders})",
                target_ids,
            )
        else:
            endorsement_count = 0

        p_placeholders = ", ".join("?" for _ in thread_ids)
        post_cursor = await self._db.execute(
            f"SELECT COUNT(*) FROM posts WHERE thread_id IN ({p_placeholders})",
            thread_ids,
        )
        post_count = (await post_cursor.fetchone())[0]
        await post_cursor.close()
        await self._db.execute(
            f"DELETE FROM posts WHERE thread_id IN ({p_placeholders})",
            thread_ids,
        )
        await self._db.execute(
            f"DELETE FROM threads WHERE id IN ({p_placeholders})",
            thread_ids,
        )
        await self._db.commit()

        summary = {
            "threads_pruned": len(thread_ids),
            "posts_pruned": post_count,
            "endorsements_pruned": endorsement_count,
            "archived_to": archive_path,
            "pruned_thread_ids": thread_ids,
        }
        self._emit(EventType.WARD_ROOM_PRUNED, summary)

        # Update cached stats
        self._last_stats = await self._build_stats()

        return summary

    async def get_stats(self) -> dict[str, Any]:
        """Return basic Ward Room stats for monitoring."""
        if hasattr(self, '_last_stats') and self._last_stats:
            return dict(self._last_stats)
        return await self._build_stats()

    async def _build_stats(self) -> dict[str, Any]:
        """Build stats from DB."""
        if not self._db:
            return {"total_threads": 0, "total_posts": 0, "total_endorsements": 0,
                    "oldest_thread_at": None, "db_size_bytes": 0}

        import os
        stats: dict[str, Any] = {}

        async with self._db.execute("SELECT COUNT(*) FROM threads") as cur:
            stats["total_threads"] = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM posts") as cur:
            stats["total_posts"] = (await cur.fetchone())[0]
        async with self._db.execute("SELECT COUNT(*) FROM endorsements") as cur:
            stats["total_endorsements"] = (await cur.fetchone())[0]
        async with self._db.execute("SELECT MIN(created_at) FROM threads") as cur:
            row = await cur.fetchone()
            stats["oldest_thread_at"] = row[0] if row and row[0] else None
        stats["db_size_bytes"] = os.path.getsize(self.db_path) if self.db_path else 0

        self._last_stats = stats
        return stats

    async def count_pruneable(
        self,
        retention_days: int = 7,
        retention_days_endorsed: int = 30,
        retention_days_captain: int = 0,
    ) -> int:
        """Dry-run count of pruneable threads."""
        if not self._db:
            return 0

        now = time.time()
        regular_cutoff = now - (retention_days * 86400)
        endorsed_cutoff = now - (retention_days_endorsed * 86400)

        count = 0
        async with self._db.execute(
            "SELECT author_id, last_activity, net_score "
            "FROM threads WHERE pinned = 0 AND last_activity < ?",
            (regular_cutoff,),
        ) as cursor:
            async for row in cursor:
                if row[2] > 0 and row[1] >= endorsed_cutoff:
                    continue
                if row[0] == "captain" and retention_days_captain == 0:
                    continue
                count += 1
        return count

    async def start_prune_loop(self, config: Any, archive_dir: Any) -> None:
        """Start background pruning task (AD-416)."""
        import asyncio
        self._prune_config = config
        self._archive_dir = archive_dir
        self._prune_task = asyncio.create_task(self._prune_loop())

    async def _prune_loop(self) -> None:
        """Periodic pruning of old threads."""
        import asyncio
        from datetime import datetime
        while True:
            await asyncio.sleep(self._prune_config.prune_interval_seconds)
            try:
                archive_path = None
                if self._prune_config.archive_enabled:
                    from pathlib import Path
                    Path(self._archive_dir).mkdir(parents=True, exist_ok=True)
                    month = datetime.now().strftime("%Y-%m")
                    archive_path = str(Path(self._archive_dir) / f"ward_room_archive_{month}.jsonl")
                result = await self.prune_old_threads(
                    retention_days=self._prune_config.retention_days,
                    retention_days_endorsed=self._prune_config.retention_days_endorsed,
                    retention_days_captain=self._prune_config.retention_days_captain,
                    archive_path=archive_path,
                )
                if result["threads_pruned"] > 0:
                    logger.info(
                        "Ward Room pruned: %d threads, %d posts archived to %s",
                        result["threads_pruned"], result["posts_pruned"],
                        result.get("archived_to", "none"),
                    )
            except Exception:
                logger.warning("Ward Room prune failed", exc_info=True)

    async def stop_prune_loop(self) -> None:
        """Cancel the prune task."""
        import asyncio
        if hasattr(self, '_prune_task') and self._prune_task:
            self._prune_task.cancel()
            try:
                await self._prune_task
            except asyncio.CancelledError:
                pass
            self._prune_task = None

    def _extract_mentions(self, text: str) -> list[str]:
        """Extract @callsign mentions from text."""
        return _MENTION_PATTERN.findall(text)

    # ------------------------------------------------------------------
    # Channel cache (sync snapshot for build_state_snapshot)
    # ------------------------------------------------------------------

    async def _refresh_channel_cache(self) -> None:
        """Rebuild the in-memory channel cache from DB."""
        channels = await self.list_channels()
        self._channel_cache = [vars(c) for c in channels]

    def get_channel_snapshot(self) -> list[dict[str, Any]]:
        """Return cached channels as dicts (sync for state_snapshot)."""
        return list(self._channel_cache)

    # ------------------------------------------------------------------
    # Channel operations
    # ------------------------------------------------------------------

    async def _ensure_default_channels(self) -> None:
        """Create 'All Hands' + one channel per department if they don't exist."""
        if not self._db:
            return

        from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS

        # AD-429e: Prefer ontology department list, fall back to legacy dict
        if self._ontology:
            departments = sorted(d.id for d in self._ontology.get_departments())
        else:
            departments = sorted(set(_AGENT_DEPARTMENTS.values()))

        # Check existing channel names
        existing: set[str] = set()
        async with self._db.execute("SELECT name FROM channels") as cursor:
            async for row in cursor:
                existing.add(row[0])

        now = time.time()
        system_id = "system"

        # Ship-wide channel
        if "All Hands" not in existing:
            await self._db.execute(
                "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "All Hands", "ship", "", system_id, now,
                 "Ship-wide announcements and discussion"),
            )

        # Department channels
        for dept in departments:
            dept_name = dept.capitalize()
            if dept_name not in existing:
                await self._db.execute(
                    "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), dept_name, "department", dept, system_id, now,
                     f"{dept_name} department channel"),
                )

        # AD-412: Crew Improvement Proposals channel
        if "Improvement Proposals" not in existing:
            await self._db.execute(
                "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "Improvement Proposals", "ship", "", system_id, now,
                 "Structured crew improvement proposals — endorse to approve, downvote to shelve"),
            )

        await self._db.commit()

    async def list_channels(self, agent_id: str | None = None) -> list[WardRoomChannel]:
        """All channels."""
        if not self._db:
            return []
        channels: list[WardRoomChannel] = []
        async with self._db.execute(
            "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
            "FROM channels ORDER BY created_at"
        ) as cursor:
            async for row in cursor:
                channels.append(WardRoomChannel(
                    id=row[0], name=row[1], channel_type=row[2],
                    department=row[3], created_by=row[4], created_at=row[5],
                    archived=bool(row[6]), description=row[7],
                ))
        return channels

    async def create_channel(
        self, name: str, channel_type: str, created_by: str,
        department: str = "", description: str = "",
    ) -> WardRoomChannel:
        """Create custom channel."""
        if not self._db:
            raise ValueError("Ward Room not initialized")

        # Check for duplicate names
        async with self._db.execute(
            "SELECT COUNT(*) FROM channels WHERE name = ?", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] > 0:
                raise ValueError(f"Channel '{name}' already exists")

        # Check credibility
        cred = await self.get_credibility(created_by)
        from probos.config import TRUST_FLOOR_CREDIBILITY
        if cred.credibility_score < TRUST_FLOOR_CREDIBILITY:
            raise ValueError("Insufficient credibility to create channels")

        now = time.time()
        channel = WardRoomChannel(
            id=str(uuid.uuid4()), name=name, channel_type=channel_type,
            department=department, created_by=created_by, created_at=now,
            description=description,
        )
        await self._db.execute(
            "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (channel.id, channel.name, channel.channel_type, channel.department,
             channel.created_by, channel.created_at, channel.description),
        )
        await self._db.commit()
        await self._refresh_channel_cache()
        return channel

    async def get_channel(self, channel_id: str) -> WardRoomChannel | None:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
            "FROM channels WHERE id = ?", (channel_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return WardRoomChannel(
                id=row[0], name=row[1], channel_type=row[2],
                department=row[3], created_by=row[4], created_at=row[5],
                archived=bool(row[6]), description=row[7],
            )

    async def get_or_create_dm_channel(
        self, agent_a_id: str, agent_b_id: str,
        callsign_a: str = "", callsign_b: str = "",
    ) -> WardRoomChannel:
        """AD-453: Get or create a DM channel between two agents. Deterministic naming."""
        if not self._db:
            raise ValueError("Ward Room not initialized")
        sorted_ids = sorted([agent_a_id, agent_b_id])
        channel_name = f"dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}"

        # Check if channel already exists
        async with self._db.execute(
            "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
            "FROM channels WHERE name = ? AND channel_type = 'dm'", (channel_name,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return WardRoomChannel(
                    id=row[0], name=row[1], channel_type=row[2],
                    department=row[3], created_by=row[4], created_at=row[5],
                    archived=bool(row[6]), description=row[7],
                )

        # Create new DM channel (bypass credibility check for system-created DMs)
        label_a = callsign_a or agent_a_id[:12]
        label_b = callsign_b or agent_b_id[:12]
        now = time.time()
        channel = WardRoomChannel(
            id=str(uuid.uuid4()), name=channel_name, channel_type="dm",
            department="", created_by=agent_a_id, created_at=now,
            description=f"DM: {label_a} \u2194 {label_b}",
        )
        await self._db.execute(
            "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (channel.id, channel.name, channel.channel_type,
             channel.department, channel.created_by, channel.created_at, channel.description),
        )
        await self._db.commit()

        # Subscribe both agents
        await self.subscribe(agent_a_id, channel.id)
        await self.subscribe(agent_b_id, channel.id)
        await self._refresh_channel_cache()
        return channel

    # ------------------------------------------------------------------
    # Thread operations
    # ------------------------------------------------------------------

    async def list_threads(
        self, channel_id: str, limit: int = 50, offset: int = 0, sort: str = "recent",
        include_archived: bool = False,
    ) -> list[WardRoomThread]:
        """Threads in channel. Pinned first, then sorted by last_activity or net_score."""
        if not self._db:
            return []

        order_col = "net_score" if sort == "top" else "last_activity"
        archive_filter = "" if include_archived else "AND (archived = 0 OR archived IS NULL) "
        sql = (
            "SELECT id, channel_id, author_id, title, body, created_at, last_activity, "
            "pinned, locked, thread_mode, max_responders, reply_count, net_score, "
            "author_callsign, channel_name "
            f"FROM threads WHERE channel_id = ? {archive_filter}"
            f"ORDER BY pinned DESC, {order_col} DESC "
            "LIMIT ? OFFSET ?"
        )
        threads: list[WardRoomThread] = []
        async with self._db.execute(sql, (channel_id, limit, offset)) as cursor:
            async for row in cursor:
                threads.append(WardRoomThread(
                    id=row[0], channel_id=row[1], author_id=row[2],
                    title=row[3], body=row[4], created_at=row[5],
                    last_activity=row[6], pinned=bool(row[7]), locked=bool(row[8]),
                    thread_mode=row[9], max_responders=row[10],
                    reply_count=row[11], net_score=row[12],
                    author_callsign=row[13], channel_name=row[14],
                ))
        return threads

    async def archive_dm_messages(self, max_age_hours: int = 24) -> int:
        """Archive DM thread posts older than max_age_hours. Returns count archived."""
        if not self._db:
            return 0
        cutoff = time.time() - (max_age_hours * 3600)

        # Find DM channels
        async with self._db.execute(
            "SELECT id FROM channels WHERE channel_type = 'dm'"
        ) as cursor:
            dm_channel_ids = [row[0] async for row in cursor]

        if not dm_channel_ids:
            return 0

        # Archive old threads in DM channels (mark as archived, don't delete)
        placeholders = ','.join('?' * len(dm_channel_ids))
        async with self._db.execute(
            f"UPDATE threads SET archived = 1 WHERE channel_id IN ({placeholders}) "
            f"AND created_at < ? AND (archived = 0 OR archived IS NULL)",
            (*dm_channel_ids, cutoff),
        ) as cursor:
            count = cursor.rowcount

        await self._db.commit()
        return count

    async def browse_threads(
        self,
        agent_id: str,
        channels: list[str] | None = None,
        thread_mode: str | None = None,
        limit: int = 10,
        since: float = 0.0,
        sort: str = "recent",  # AD-426: "recent" (default) or "top"
    ) -> list[WardRoomThread]:
        """Browse threads across one or more channels (AD-425).

        Args:
            agent_id: The browsing agent (for channel scoping via memberships).
            channels: Channel IDs to browse. None = all subscribed channels.
            thread_mode: Filter by thread mode ("discuss", "inform", "action"). None = all.
            limit: Max threads to return.
            since: Only threads with last_activity after this epoch timestamp.

        Returns:
            List of WardRoomThread sorted by last_activity descending.
        """
        if not self._db:
            return []

        # Resolve channel list
        if channels is None:
            channel_ids: list[str] = []
            async with self._db.execute(
                "SELECT channel_id FROM memberships WHERE agent_id = ?",
                (agent_id,),
            ) as cursor:
                async for row in cursor:
                    channel_ids.append(row[0])
            if not channel_ids:
                return []
        else:
            channel_ids = channels

        # Build query
        placeholders = ", ".join("?" for _ in channel_ids)
        sql = (
            "SELECT id, channel_id, author_id, title, body, created_at, last_activity, "
            "pinned, locked, thread_mode, max_responders, reply_count, net_score, "
            "author_callsign, channel_name "
            f"FROM threads WHERE channel_id IN ({placeholders}) AND last_activity > ?"
        )
        params: list[Any] = list(channel_ids) + [since]

        if thread_mode:
            sql += " AND thread_mode = ?"
            params.append(thread_mode)

        # AD-426: Sort by net_score or last_activity
        order_clause = "net_score DESC, last_activity DESC" if sort == "top" else "last_activity DESC"
        sql += f" ORDER BY {order_clause} LIMIT ?"
        params.append(limit)

        threads: list[WardRoomThread] = []
        async with self._db.execute(sql, params) as cursor:
            async for row in cursor:
                threads.append(WardRoomThread(
                    id=row[0], channel_id=row[1], author_id=row[2],
                    title=row[3], body=row[4], created_at=row[5],
                    last_activity=row[6], pinned=bool(row[7]), locked=bool(row[8]),
                    thread_mode=row[9], max_responders=row[10],
                    reply_count=row[11], net_score=row[12],
                    author_callsign=row[13], channel_name=row[14],
                ))
        return threads

    async def get_recent_activity(
        self, channel_id: str, since: float, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Recent threads + posts in a channel since a timestamp.

        Returns a flat list of dicts with author_callsign, body (truncated),
        created_at, and type ('thread' or 'reply').  Designed for proactive
        loop context injection — compact, no nesting.
        """
        if not self._db:
            return []

        items: list[dict[str, Any]] = []

        # Recent threads
        async with self._db.execute(
            "SELECT id, author_callsign, title, body, created_at, thread_mode, net_score "
            "FROM threads WHERE channel_id = ? AND created_at > ? "
            "ORDER BY created_at DESC LIMIT ?",
            (channel_id, since, limit),
        ) as cursor:
            async for row in cursor:
                items.append({
                    "type": "thread",
                    "author": row[1] or "unknown",
                    "title": row[2][:200],
                    "body": row[3][:500],
                    "created_at": row[4],
                    "thread_mode": row[5],
                    "net_score": row[6],       # AD-426
                    "post_id": row[0],         # AD-426: thread id for endorsement ref
                    "thread_id": row[0],       # AD-437: same as post_id for threads
                })

        # Recent replies in threads from this channel
        async with self._db.execute(
            "SELECT p.id, p.author_callsign, p.body, p.created_at, p.net_score, p.thread_id "
            "FROM posts p JOIN threads t ON p.thread_id = t.id "
            "WHERE t.channel_id = ? AND p.created_at > ? AND p.deleted = 0 "
            "ORDER BY p.created_at DESC LIMIT ?",
            (channel_id, since, limit),
        ) as cursor:
            async for row in cursor:
                items.append({
                    "type": "reply",
                    "author": row[1] or "unknown",
                    "body": row[2][:500],
                    "created_at": row[3],
                    "net_score": row[4],       # AD-426
                    "post_id": row[0],         # AD-426
                    "thread_id": row[5],       # AD-437
                })

        # Sort by time, most recent first, cap total
        items.sort(key=lambda x: x["created_at"], reverse=True)
        return items[:limit]

    async def create_thread(
        self, channel_id: str, author_id: str, title: str, body: str,
        author_callsign: str = "",
        thread_mode: str = "discuss",      # AD-424
        max_responders: int = 0,           # AD-424
    ) -> WardRoomThread:
        """Create thread in channel."""
        if not self._db:
            raise ValueError("Ward Room not initialized")

        # Check channel exists and not archived
        channel = await self.get_channel(channel_id)
        if not channel:
            raise ValueError(f"Channel {channel_id} not found")
        if channel.archived:
            raise ValueError("Channel is archived")

        # Check restrictions
        cred = await self.get_credibility(author_id)
        if "post" in cred.restrictions:
            raise ValueError("Author is restricted from posting")

        now = time.time()
        thread = WardRoomThread(
            id=str(uuid.uuid4()), channel_id=channel_id, author_id=author_id,
            title=title, body=body, created_at=now, last_activity=now,
            author_callsign=author_callsign, channel_name=channel.name,
            thread_mode=thread_mode, max_responders=max_responders,
        )
        await self._db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, "
            "last_activity, author_callsign, channel_name, thread_mode, max_responders) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (thread.id, thread.channel_id, thread.author_id, thread.title,
             thread.body, thread.created_at, thread.last_activity,
             thread.author_callsign, thread.channel_name,
             thread.thread_mode, thread.max_responders),
        )

        # Update credibility
        await self._db.execute(
            "INSERT INTO credibility (agent_id, total_posts) VALUES (?, 1) "
            "ON CONFLICT(agent_id) DO UPDATE SET total_posts = total_posts + 1",
            (author_id,),
        )
        await self._db.commit()

        self._emit(EventType.WARD_ROOM_THREAD_CREATED, {
            "thread_id": thread.id,
            "channel_id": channel_id,
            "author_id": author_id,
            "title": title,
            "author_callsign": author_callsign,
            "thread_mode": thread_mode,
            "mentions": self._extract_mentions(body),
        })
        # AD-430a: Store thread creation as authoring agent's episodic memory
        if self._episodic_memory and author_id:
            try:
                import time as _time
                from probos.types import Episode
                channel_name = ""
                for ch in self._channel_cache:
                    if ch.get("id") == channel_id:
                        channel_name = ch.get("name", "")
                        break
                episode = Episode(
                    user_input=f"[Ward Room] {channel_name} — {author_callsign or author_id}: {title}",
                    timestamp=_time.time(),
                    agent_ids=[author_id],
                    outcomes=[{
                        "intent": "ward_room_post",
                        "success": True,
                        "channel": channel_name,
                        "thread_title": title,
                        "thread_id": thread.id,
                        "is_reply": False,
                        "thread_mode": thread_mode,
                    }],
                    reflection=f"{author_callsign or author_id} posted to {channel_name}: {title[:100]}",
                )
                # BF-039: Route through should_store() selective encoding gate
                from probos.cognitive.episodic import EpisodicMemory
                if EpisodicMemory.should_store(episode):
                    await self._episodic_memory.store(episode)
            except Exception:
                logger.debug("Failed to store thread creation episode", exc_info=True)
        return thread

    async def update_thread(
        self, thread_id: str, **updates: Any,
    ) -> WardRoomThread | None:
        """Update thread fields (AD-424). Captain-level operation.

        Supported fields: locked, thread_mode, max_responders, pinned.
        """
        if not self._db:
            return None
        allowed = {"locked", "thread_mode", "max_responders", "pinned"}
        filtered = {k: v for k, v in updates.items() if k in allowed}
        if not filtered:
            return None

        sets = ", ".join(f"{k} = ?" for k in filtered)
        vals = list(filtered.values())
        vals.append(thread_id)
        await self._db.execute(f"UPDATE threads SET {sets} WHERE id = ?", vals)
        await self._db.commit()

        # Re-fetch thread via list query to get a WardRoomThread object
        async with self._db.execute(
            "SELECT id, channel_id, author_id, title, body, created_at, last_activity, "
            "pinned, locked, thread_mode, max_responders, reply_count, net_score, "
            "author_callsign, channel_name FROM threads WHERE id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            thread = WardRoomThread(
                id=row[0], channel_id=row[1], author_id=row[2],
                title=row[3], body=row[4], created_at=row[5],
                last_activity=row[6], pinned=bool(row[7]), locked=bool(row[8]),
                thread_mode=row[9], max_responders=row[10],
                reply_count=row[11], net_score=row[12],
                author_callsign=row[13], channel_name=row[14],
            )

        self._emit(EventType.WARD_ROOM_THREAD_UPDATED, {
            "thread_id": thread_id,
            "updates": filtered,
        })
        return thread

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Thread with all posts as nested children tree."""
        if not self._db:
            return None

        # Fetch thread
        async with self._db.execute(
            "SELECT id, channel_id, author_id, title, body, created_at, last_activity, "
            "pinned, locked, thread_mode, max_responders, reply_count, net_score, "
            "author_callsign, channel_name "
            "FROM threads WHERE id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            thread_dict = {
                "id": row[0], "channel_id": row[1], "author_id": row[2],
                "title": row[3], "body": row[4], "created_at": row[5],
                "last_activity": row[6], "pinned": bool(row[7]), "locked": bool(row[8]),
                "thread_mode": row[9], "max_responders": row[10],
                "reply_count": row[11], "net_score": row[12],
                "author_callsign": row[13], "channel_name": row[14],
            }

        # Fetch all posts for thread
        posts: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT id, thread_id, parent_id, author_id, body, created_at, edited_at, "
            "deleted, delete_reason, deleted_by, net_score, author_callsign "
            "FROM posts WHERE thread_id = ? ORDER BY created_at", (thread_id,)
        ) as cursor:
            async for row in cursor:
                posts.append({
                    "id": row[0], "thread_id": row[1], "parent_id": row[2],
                    "author_id": row[3], "body": row[4], "created_at": row[5],
                    "edited_at": row[6], "deleted": bool(row[7]),
                    "delete_reason": row[8], "deleted_by": row[9],
                    "net_score": row[10], "author_callsign": row[11],
                    "children": [],
                })

        # Build recursive children tree
        by_id: dict[str, dict] = {p["id"]: p for p in posts}
        roots: list[dict] = []
        for post in posts:
            parent = post["parent_id"]
            if parent and parent in by_id:
                by_id[parent]["children"].append(post)
            else:
                roots.append(post)

        return {"thread": thread_dict, "posts": roots}

    # ------------------------------------------------------------------
    # Post operations
    # ------------------------------------------------------------------

    async def create_post(
        self, thread_id: str, author_id: str, body: str,
        parent_id: str | None = None, author_callsign: str = "",
    ) -> WardRoomPost:
        """Reply to thread or nested reply to post."""
        if not self._db:
            raise ValueError("Ward Room not initialized")

        # Check thread exists and not locked
        async with self._db.execute(
            "SELECT locked FROM threads WHERE id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Thread {thread_id} not found")
            if row[0]:
                raise ValueError("Thread is locked")

        # Check restrictions
        cred = await self.get_credibility(author_id)
        if "post" in cred.restrictions:
            raise ValueError("Author is restricted from posting")

        now = time.time()
        post = WardRoomPost(
            id=str(uuid.uuid4()), thread_id=thread_id, parent_id=parent_id,
            author_id=author_id, body=body, created_at=now,
            author_callsign=author_callsign,
        )
        await self._db.execute(
            "INSERT INTO posts (id, thread_id, parent_id, author_id, body, created_at, author_callsign) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (post.id, post.thread_id, post.parent_id, post.author_id,
             post.body, post.created_at, post.author_callsign),
        )

        # Update thread reply_count and last_activity
        await self._db.execute(
            "UPDATE threads SET reply_count = reply_count + 1, last_activity = ? WHERE id = ?",
            (now, thread_id),
        )

        # Update credibility
        await self._db.execute(
            "INSERT INTO credibility (agent_id, total_posts) VALUES (?, 1) "
            "ON CONFLICT(agent_id) DO UPDATE SET total_posts = total_posts + 1",
            (author_id,),
        )
        await self._db.commit()

        self._emit(EventType.WARD_ROOM_POST_CREATED, {
            "post_id": post.id,
            "thread_id": thread_id,
            "author_id": author_id,
            "parent_id": parent_id,
            "author_callsign": author_callsign,
            "mentions": self._extract_mentions(body),
        })
        # AD-430a: Store reply as authoring agent's episodic memory
        if self._episodic_memory and author_id:
            try:
                import time as _time
                from probos.types import Episode
                # Get thread title and channel for context
                thread_title = ""
                channel_name = ""
                try:
                    async with self._db.execute(
                        "SELECT t.title, c.name FROM threads t LEFT JOIN channels c ON t.channel_id = c.id WHERE t.id = ?",
                        (thread_id,)
                    ) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        thread_title = row[0] or ""
                        channel_name = row[1] or ""
                except Exception:
                    logger.debug("Thread title lookup failed", exc_info=True)
                episode = Episode(
                    user_input=f"[Ward Room reply] {channel_name} — {author_callsign or author_id}: {body[:500]}",
                    timestamp=_time.time(),
                    agent_ids=[author_id],
                    outcomes=[{
                        "intent": "ward_room_post",
                        "success": True,
                        "channel": channel_name,
                        "thread_title": thread_title,
                        "thread_id": thread_id,
                        "is_reply": True,
                    }],
                    reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:60]}': {body[:300]}",
                )
                # BF-039: Route through should_store() selective encoding gate
                from probos.cognitive.episodic import EpisodicMemory
                if EpisodicMemory.should_store(episode):
                    await self._episodic_memory.store(episode)
            except Exception:
                logger.debug("Failed to store reply episode", exc_info=True)

        # AD-453: Record Hebbian social connections for replies
        if self._hebbian_router and author_id:
            try:
                from probos.mesh.routing import REL_SOCIAL
                # Get thread author for author→thread_author connection
                async with self._db.execute(
                    "SELECT author_id FROM threads WHERE id = ?", (thread_id,)
                ) as cursor:
                    trow = await cursor.fetchone()
                if trow and trow[0] and trow[0] != author_id:
                    self._hebbian_router.record_interaction(
                        source=author_id, target=trow[0],
                        success=True, rel_type=REL_SOCIAL,
                    )
                    self._emit(EventType.HEBBIAN_UPDATE, {
                        "source": author_id, "target": trow[0],
                        "weight": format_trust(self._hebbian_router.get_weight(author_id, trow[0])),
                        "rel_type": "social",
                    })
                # @mention connections
                mentions = self._extract_mentions(body)
                if mentions and hasattr(self, '_resolve_callsign_to_id'):
                    for callsign in mentions:
                        mid = self._resolve_callsign_to_id(callsign)
                        if mid and mid != author_id:
                            self._hebbian_router.record_interaction(
                                source=author_id, target=mid,
                                success=True, rel_type=REL_SOCIAL,
                            )
                            self._emit(EventType.HEBBIAN_UPDATE, {
                                "source": author_id, "target": mid,
                                "weight": format_trust(self._hebbian_router.get_weight(author_id, mid)),
                                "rel_type": "social",
                            })
            except Exception:
                logger.debug("Failed to record Hebbian social interaction", exc_info=True)
        return post

    async def get_post(self, post_id: str) -> dict[str, Any] | None:
        """Return a single post by ID, or None if not found.  AD-426."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, thread_id, author_id, body, created_at, net_score, author_callsign "
            "FROM posts WHERE id = ?",
            (post_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "thread_id": row[1],
                "author_id": row[2],
                "body": row[3],
                "created_at": row[4],
                "net_score": row[5],
                "author_callsign": row[6],
            }

    async def edit_post(self, post_id: str, author_id: str, new_body: str) -> WardRoomPost:
        """Edit own post. Only original author can edit."""
        if not self._db:
            raise ValueError("Ward Room not initialized")

        async with self._db.execute(
            "SELECT id, thread_id, parent_id, author_id, body, created_at, edited_at, "
            "deleted, delete_reason, deleted_by, net_score, author_callsign "
            "FROM posts WHERE id = ?", (post_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Post {post_id} not found")
            if row[3] != author_id:
                raise ValueError("Only the original author can edit")

        now = time.time()
        await self._db.execute(
            "UPDATE posts SET body = ?, edited_at = ? WHERE id = ?",
            (new_body, now, post_id),
        )
        await self._db.commit()

        return WardRoomPost(
            id=row[0], thread_id=row[1], parent_id=row[2], author_id=row[3],
            body=new_body, created_at=row[5], edited_at=now,
            deleted=bool(row[7]), delete_reason=row[8], deleted_by=row[9],
            net_score=row[10], author_callsign=row[11],
        )

    # ------------------------------------------------------------------
    # Endorsement operations
    # ------------------------------------------------------------------

    async def endorse(
        self, target_id: str, target_type: str, voter_id: str, direction: str,
    ) -> dict[str, Any]:
        """Up/down/unvote. Returns {"net_score": int, "voter_direction": str}."""
        if not self._db:
            raise ValueError("Ward Room not initialized")

        # Get author of target to prevent self-endorsement
        if target_type == "thread":
            async with self._db.execute(
                "SELECT author_id FROM threads WHERE id = ?", (target_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise ValueError(f"Thread {target_id} not found")
                author_id = row[0]
        else:
            async with self._db.execute(
                "SELECT author_id FROM posts WHERE id = ?", (target_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise ValueError(f"Post {target_id} not found")
                author_id = row[0]

        if voter_id == author_id:
            raise ValueError("Cannot endorse own content")

        # Get existing endorsement
        existing_direction: str | None = None
        async with self._db.execute(
            "SELECT direction FROM endorsements WHERE target_id = ? AND voter_id = ?",
            (target_id, voter_id),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                existing_direction = row[0]

        # Calculate delta for net_score and credibility
        score_delta = 0
        cred_delta = 0

        if direction == "unvote":
            if existing_direction == "up":
                score_delta = -1
                cred_delta = -1
            elif existing_direction == "down":
                score_delta = 1
                cred_delta = 1
            # Remove endorsement
            await self._db.execute(
                "DELETE FROM endorsements WHERE target_id = ? AND voter_id = ?",
                (target_id, voter_id),
            )
            final_direction = "none"
        else:
            # direction is "up" or "down"
            new_val = 1 if direction == "up" else -1
            if existing_direction is None:
                score_delta = new_val
                cred_delta = new_val
            elif existing_direction == direction:
                # Same vote again — no change
                final_direction = direction
                async with self._db.execute(
                    f"SELECT net_score FROM {'threads' if target_type == 'thread' else 'posts'} WHERE id = ?",
                    (target_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return {"net_score": row[0] if row else 0, "voter_direction": final_direction}
            else:
                # Vote change: up→down = delta -2, down→up = delta +2
                old_val = 1 if existing_direction == "up" else -1
                score_delta = new_val - old_val
                cred_delta = new_val - old_val

            # Upsert endorsement
            now = time.time()
            await self._db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(target_id, voter_id) DO UPDATE SET direction = ?, created_at = ?",
                (str(uuid.uuid4()), target_id, target_type, voter_id, direction, now,
                 direction, now),
            )
            final_direction = direction

        # Update target net_score
        table = "threads" if target_type == "thread" else "posts"
        if score_delta != 0:
            await self._db.execute(
                f"UPDATE {table} SET net_score = net_score + ? WHERE id = ?",
                (score_delta, target_id),
            )

        # Update author credibility
        if cred_delta != 0:
            await self._update_credibility(author_id, cred_delta)

        await self._db.commit()

        # Get final net_score
        async with self._db.execute(
            f"SELECT net_score FROM {table} WHERE id = ?", (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
            net_score = row[0] if row else 0

        self._emit(EventType.WARD_ROOM_ENDORSEMENT, {
            "target_id": target_id,
            "target_type": target_type,
            "voter_id": voter_id,
            "direction": final_direction,
            "net_score": net_score,
        })

        return {"net_score": net_score, "voter_direction": final_direction}

    # ------------------------------------------------------------------
    # Membership operations
    # ------------------------------------------------------------------

    async def subscribe(self, agent_id: str, channel_id: str, role: str = "member") -> None:
        """Subscribe to channel."""
        if not self._db:
            return
        now = time.time()
        await self._db.execute(
            "INSERT INTO memberships (agent_id, channel_id, subscribed_at, last_seen, role) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(agent_id, channel_id) DO UPDATE SET role = ?",
            (agent_id, channel_id, now, now, role, role),
        )
        await self._db.commit()

    async def unsubscribe(self, agent_id: str, channel_id: str) -> None:
        """Remove membership. Cannot unsubscribe from department channels."""
        if not self._db:
            return
        # Check if it's a department channel
        async with self._db.execute(
            "SELECT channel_type FROM channels WHERE id = ?", (channel_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] == "department":
                raise ValueError("Cannot unsubscribe from department channels")

        await self._db.execute(
            "DELETE FROM memberships WHERE agent_id = ? AND channel_id = ?",
            (agent_id, channel_id),
        )
        await self._db.commit()

    async def update_last_seen(self, agent_id: str, channel_id: str) -> None:
        """Set last_seen to now (marks all as read)."""
        if not self._db:
            return
        now = time.time()
        await self._db.execute(
            "UPDATE memberships SET last_seen = ? WHERE agent_id = ? AND channel_id = ?",
            (now, agent_id, channel_id),
        )
        await self._db.commit()

    async def get_unread_counts(self, agent_id: str) -> dict[str, int]:
        """For each subscribed channel, count threads with last_activity > last_seen."""
        if not self._db:
            return {}
        counts: dict[str, int] = {}
        async with self._db.execute(
            "SELECT m.channel_id, COUNT(t.id) "
            "FROM memberships m "
            "LEFT JOIN threads t ON t.channel_id = m.channel_id AND t.last_activity > m.last_seen "
            "WHERE m.agent_id = ? "
            "GROUP BY m.channel_id",
            (agent_id,),
        ) as cursor:
            async for row in cursor:
                counts[row[0]] = row[1]
        return counts

    async def get_unread_dms(self, agent_id: str, limit: int = 3) -> list[dict]:
        """Return DM threads where agent_id is a participant but hasn't replied.

        BF-082: A thread is 'unread' if:
        1. It's in a DM channel (channel_type = 'dm')
        2. The agent's ID prefix appears in the channel name (they're a participant)
        3. The agent has NOT authored any posts in that thread
        4. The thread is not archived
        5. The agent did NOT author the thread (don't flag own threads)

        Returns list of dicts with thread_id, channel_id, author_id,
        author_callsign, title, body, created_at.
        """
        if not self._db:
            return []
        prefix = agent_id[:8]
        async with self._db.execute(
            "SELECT t.id, t.channel_id, t.author_id, t.author_callsign, "
            "       t.title, t.body, t.created_at "
            "FROM threads t "
            "JOIN channels c ON c.id = t.channel_id "
            "LEFT JOIN posts p ON p.thread_id = t.id AND p.author_id = ? "
            "WHERE c.channel_type = 'dm' "
            "  AND c.name LIKE ? "
            "  AND (t.archived = 0 OR t.archived IS NULL) "
            "  AND t.author_id != ? "
            "  AND p.id IS NULL "
            "ORDER BY t.created_at DESC "
            "LIMIT ?",
            (agent_id, f"%{prefix}%", agent_id, limit),
        ) as cursor:
            results = []
            async for row in cursor:
                results.append({
                    "thread_id": row[0],
                    "channel_id": row[1],
                    "author_id": row[2],
                    "author_callsign": row[3],
                    "title": row[4],
                    "body": row[5],
                    "created_at": row[6],
                })
            return results

    # ------------------------------------------------------------------
    # Credibility operations
    # ------------------------------------------------------------------

    async def get_credibility(self, agent_id: str) -> WardRoomCredibility:
        """Return credibility record (create with defaults if not exists)."""
        if not self._db:
            return WardRoomCredibility(agent_id=agent_id)

        async with self._db.execute(
            "SELECT agent_id, total_posts, total_endorsements, credibility_score, restrictions "
            "FROM credibility WHERE agent_id = ?", (agent_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                restrictions = json.loads(row[4]) if row[4] else []
                return WardRoomCredibility(
                    agent_id=row[0], total_posts=row[1],
                    total_endorsements=row[2], credibility_score=row[3],
                    restrictions=restrictions,
                )
        return WardRoomCredibility(agent_id=agent_id)

    async def _update_credibility(self, agent_id: str, endorsement_delta: int) -> None:
        """Adjust total_endorsements and recalculate credibility_score."""
        if not self._db:
            return

        # Ensure record exists
        await self._db.execute(
            "INSERT INTO credibility (agent_id) VALUES (?) ON CONFLICT(agent_id) DO NOTHING",
            (agent_id,),
        )

        # Get current values
        async with self._db.execute(
            "SELECT credibility_score, total_endorsements FROM credibility WHERE agent_id = ?",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return
            score = row[0]
            total = row[1]

        # Rolling weighted average
        new_score = score * 0.95 + (0.5 + endorsement_delta * 0.1) * 0.05
        new_score = max(0.0, min(1.0, new_score))
        new_total = total + endorsement_delta

        await self._db.execute(
            "UPDATE credibility SET credibility_score = ?, total_endorsements = ? WHERE agent_id = ?",
            (new_score, new_total, agent_id),
        )

    # ------------------------------------------------------------------
    # AD-514: Public API
    # ------------------------------------------------------------------

    def set_ontology(self, ontology: Any) -> None:
        """Inject ontology reference for crew-aware channel management."""
        self._ontology = ontology

    async def post_system_message(self, channel_name: str, content: str, author: str = "ship_computer") -> None:
        """Post a system-generated message to a named channel.

        Used for lifecycle announcements (System Online, Entering Stasis, etc.).
        Creates thread + post in the named channel. No-op if channel not found.
        """
        if self._db is None:
            return
        cursor = await self._db.execute(
            "SELECT id FROM channels WHERE name = ?", (channel_name,)
        )
        row = await cursor.fetchone()
        if not row:
            return
        channel_id = row[0]
        thread_id = str(uuid.uuid4())
        post_id = str(uuid.uuid4())
        now = time.time()
        await self._db.execute(
            "INSERT INTO threads (id, channel_id, title, body, author_id, created_at, last_activity) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (thread_id, channel_id, content[:80], content, author, now, now),
        )
        await self._db.execute(
            "INSERT INTO posts (id, thread_id, author_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (post_id, thread_id, author, content, now),
        )
        await self._db.commit()
        logger.info("System message posted to channel %s: %s", channel_name, content[:80])

    @property
    def is_started(self) -> bool:
        """Whether the Ward Room database connection is active."""
        return self._db is not None
