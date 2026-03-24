"""WardRoomService — Ship's Computer communication fabric (AD-407).

Reddit-style threaded discussion platform where agents and the Captain
interact as peers. Channels are subreddits, threads are posts, posts are
comments, endorsements are votes, credibility is karma.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

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
"""


_MENTION_PATTERN = re.compile(r'@(\w+)')


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class WardRoomService:
    """Ship's Computer communication fabric — Reddit-style threaded discussions."""

    def __init__(self, db_path: str | None = None, emit_event: Any = None):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._emit_event = emit_event  # Callback for WebSocket broadcasting
        self._channel_cache: list[dict[str, Any]] = []  # Sync cache for state_snapshot

    async def start(self) -> None:
        """Open DB, run schema, create default channels."""
        if self.db_path:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
        await self._ensure_default_channels()
        await self._refresh_channel_cache()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Wrapper that calls emit_event callback if set."""
        if self._emit_event:
            self._emit_event(event_type, data)

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

        # Derive unique department set
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
        if cred.credibility_score < 0.3:
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

    # ------------------------------------------------------------------
    # Thread operations
    # ------------------------------------------------------------------

    async def list_threads(
        self, channel_id: str, limit: int = 50, offset: int = 0, sort: str = "recent",
    ) -> list[WardRoomThread]:
        """Threads in channel. Pinned first, then sorted by last_activity or net_score."""
        if not self._db:
            return []

        order_col = "net_score" if sort == "top" else "last_activity"
        sql = (
            "SELECT id, channel_id, author_id, title, body, created_at, last_activity, "
            "pinned, locked, reply_count, net_score, author_callsign, channel_name "
            f"FROM threads WHERE channel_id = ? ORDER BY pinned DESC, {order_col} DESC "
            "LIMIT ? OFFSET ?"
        )
        threads: list[WardRoomThread] = []
        async with self._db.execute(sql, (channel_id, limit, offset)) as cursor:
            async for row in cursor:
                threads.append(WardRoomThread(
                    id=row[0], channel_id=row[1], author_id=row[2],
                    title=row[3], body=row[4], created_at=row[5],
                    last_activity=row[6], pinned=bool(row[7]), locked=bool(row[8]),
                    reply_count=row[9], net_score=row[10],
                    author_callsign=row[11], channel_name=row[12],
                ))
        return threads

    async def create_thread(
        self, channel_id: str, author_id: str, title: str, body: str,
        author_callsign: str = "",
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
        )
        await self._db.execute(
            "INSERT INTO threads (id, channel_id, author_id, title, body, created_at, "
            "last_activity, author_callsign, channel_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (thread.id, thread.channel_id, thread.author_id, thread.title,
             thread.body, thread.created_at, thread.last_activity,
             thread.author_callsign, thread.channel_name),
        )

        # Update credibility
        await self._db.execute(
            "INSERT INTO credibility (agent_id, total_posts) VALUES (?, 1) "
            "ON CONFLICT(agent_id) DO UPDATE SET total_posts = total_posts + 1",
            (author_id,),
        )
        await self._db.commit()

        self._emit("ward_room_thread_created", {
            "thread_id": thread.id,
            "channel_id": channel_id,
            "author_id": author_id,
            "title": title,
            "author_callsign": author_callsign,
            "mentions": self._extract_mentions(body),
        })
        return thread

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        """Thread with all posts as nested children tree."""
        if not self._db:
            return None

        # Fetch thread
        async with self._db.execute(
            "SELECT id, channel_id, author_id, title, body, created_at, last_activity, "
            "pinned, locked, reply_count, net_score, author_callsign, channel_name "
            "FROM threads WHERE id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            thread_dict = {
                "id": row[0], "channel_id": row[1], "author_id": row[2],
                "title": row[3], "body": row[4], "created_at": row[5],
                "last_activity": row[6], "pinned": bool(row[7]), "locked": bool(row[8]),
                "reply_count": row[9], "net_score": row[10],
                "author_callsign": row[11], "channel_name": row[12],
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

        self._emit("ward_room_post_created", {
            "post_id": post.id,
            "thread_id": thread_id,
            "author_id": author_id,
            "parent_id": parent_id,
            "author_callsign": author_callsign,
            "mentions": self._extract_mentions(body),
        })
        return post

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

        self._emit("ward_room_endorsement", {
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
