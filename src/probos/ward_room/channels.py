"""ChannelManager — channel CRUD and caching."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Awaitable

from probos.ward_room.models import WardRoomChannel

logger = logging.getLogger(__name__)

#: AD-1229 (#1202): the key the Captain holds in a DM channel name. The Captain
#: is not a registered agent, so the name carries this word instead of an id.
CAPTAIN_DM_KEY = "captain"


def dm_channel_name(agent_a_id: str, agent_b_id: str) -> str:
    """AD-453: the DM channel name for a pair -- both ids sorted, each cut to 8 characters.

    Promoted from ``get_or_create_dm_channel`` by AD-1229 so the receipts reader
    derives the name exactly as the writer does. Eight characters of an id are its
    agent type's prefix (``substrate/identity.py``), so types that share a prefix
    share a channel name; a reader must not treat a key as one agent.
    """
    sorted_ids = sorted([agent_a_id, agent_b_id])
    return f"dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}"


def captain_dm_channel_name(agent_id: str) -> str:
    """AD-485: the Captain DM channel an agent writes to (the proactive and notifier form)."""
    return f"dm-{CAPTAIN_DM_KEY}-{agent_id[:8]}"


def dm_channel_keys(name: str) -> tuple[str, str] | None:
    """AD-1229: the two keys of a ``dm-<key>-<key>`` channel name, or None for any other name."""
    parts = name.split("-")
    if len(parts) != 3 or parts[0] != "dm" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


class ChannelManager:
    """Channel CRUD, default channel creation, and channel caching."""

    def __init__(
        self,
        db: Any,
        ontology: Any = None,
        subscribe_fn: Callable[..., Awaitable[None]] | None = None,
    ) -> None:
        self._db = db
        self._ontology = ontology
        self._subscribe_fn = subscribe_fn
        self._channel_cache: list[dict[str, Any]] = []

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

        # AD-526a: Recreation channel — games, challenges, social interaction
        if "Recreation" not in existing:
            await self._db.execute(
                "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "Recreation", "ship", "", system_id, now,
                 "Games, challenges, and social interaction between crew members"),
            )

        # AD-526a: Creative channel — collaborative creative expression
        if "Creative" not in existing:
            await self._db.execute(
                "INSERT INTO channels (id, name, channel_type, department, created_by, created_at, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "Creative", "ship", "", system_id, now,
                 "Collaborative creative expression — stories, wordplay, shared creativity"),
            )

        await self._db.commit()

    async def list_channels(self, agent_id: str | None = None) -> list[WardRoomChannel]:
        """List channels, optionally filtered by agent membership.

        AD-621: When agent_id is provided, return only channels the agent
        is subscribed to. When None, return all channels (admin view).
        """
        if not self._db:
            return []
        channels: list[WardRoomChannel] = []

        if agent_id:
            sql = (
                "SELECT c.id, c.name, c.channel_type, c.department, c.created_by, "
                "c.created_at, c.archived, c.description "
                "FROM channels c "
                "INNER JOIN memberships m ON m.channel_id = c.id "
                "WHERE m.agent_id = ? "
                "ORDER BY c.created_at"
            )
            params: tuple = (agent_id,)
        else:
            sql = (
                "SELECT id, name, channel_type, department, created_by, created_at, "
                "archived, description FROM channels ORDER BY created_at"
            )
            params = ()

        async with self._db.execute(sql, params) as cursor:
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

        # Check credibility (query directly — same DB, avoids circular dep)
        from probos.config import TRUST_FLOOR_CREDIBILITY
        async with self._db.execute(
            "SELECT credibility_score FROM credibility WHERE agent_id = ?",
            (created_by,),
        ) as cursor:
            row = await cursor.fetchone()
            score = row[0] if row else 0.5
        if score < TRUST_FLOOR_CREDIBILITY:
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
        """AD-453: Get or create a DM channel between two agents."""
        if not self._db:
            raise ValueError("Ward Room not initialized")
        channel_name = dm_channel_name(agent_a_id, agent_b_id)

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

        # Create new DM channel
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
        if self._subscribe_fn:
            await self._subscribe_fn(agent_a_id, channel.id)
            await self._subscribe_fn(agent_b_id, channel.id)
        await self._refresh_channel_cache()
        return channel

    async def _refresh_channel_cache(self) -> None:
        """Rebuild the in-memory channel cache from DB."""
        channels = await self.list_channels()
        self._channel_cache = [vars(c) for c in channels]

    def get_channel_snapshot(self) -> list[dict[str, Any]]:
        """Return cached channels as dicts (sync for state_snapshot)."""
        return list(self._channel_cache)

    # ------------------------------------------------------------------
    # LoD fix: public methods for external callers
    # ------------------------------------------------------------------

    async def archive_channel(self, channel_id: str) -> None:
        """Archive a channel by ID."""
        if not self._db:
            return
        await self._db.execute(
            "UPDATE channels SET archived = 1 WHERE id = ?",
            (channel_id,),
        )
        await self._db.commit()

    async def get_channel_by_name(self, name: str) -> WardRoomChannel | None:
        """Get a channel by name."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
            "FROM channels WHERE name = ? LIMIT 1", (name,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return WardRoomChannel(
                id=row[0], name=row[1], channel_type=row[2],
                department=row[3], created_by=row[4], created_at=row[5],
                archived=bool(row[6]), description=row[7],
            )

    async def get_channel_by_department(self, department: str) -> WardRoomChannel | None:
        """AD-616: Get the first channel matching a department."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
            "FROM channels WHERE department = ? AND (archived = 0 OR archived IS NULL) LIMIT 1",
            (department,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return WardRoomChannel(
                id=row[0], name=row[1], channel_type=row[2],
                department=row[3], created_by=row[4], created_at=row[5],
                archived=bool(row[6]), description=row[7],
            )

    async def get_channel_by_type(self, channel_type: str) -> WardRoomChannel | None:
        """AD-616: Get the first channel matching a channel type."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, name, channel_type, department, created_by, created_at, archived, description "
            "FROM channels WHERE channel_type = ? AND (archived = 0 OR archived IS NULL) LIMIT 1",
            (channel_type,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return WardRoomChannel(
                id=row[0], name=row[1], channel_type=row[2],
                department=row[3], created_by=row[4], created_at=row[5],
                archived=bool(row[6]), description=row[7],
            )
