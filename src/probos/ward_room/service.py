"""WardRoomService — thin facade over ChannelManager, ThreadManager, MessageStore."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any

import aiosqlite

from probos.config import format_trust
from probos.events import EventType
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin
from probos.ward_room.channels import ChannelManager
from probos.ward_room.messages import MessageStore
from probos.ward_room.models import (
    WardRoomChannel,
    WardRoomCredibility,
    WardRoomPost,
    WardRoomThread,
    _SCHEMA,
)
from probos.ward_room.threads import ThreadManager

logger = logging.getLogger(__name__)


class WardRoomService(EventEmitterMixin):
    """Ship's Computer communication fabric — Reddit-style threaded discussions."""

    def __init__(
        self,
        db_path: str | None = None,
        emit_event: Any = None,
        episodic_memory: Any = None,
        ontology: Any = None,
        hebbian_router: Any = None,
        connection_factory: ConnectionFactory | None = None,
        identity_registry: Any = None,  # BF-103: for sovereign ID resolution
    ):
        self.db_path = db_path
        self._db: DatabaseConnection | None = None
        self._emit_event = emit_event
        self._episodic_memory = episodic_memory
        self._ontology = ontology
        self._hebbian_router = hebbian_router
        self._connection_factory = connection_factory
        self._identity_registry = identity_registry
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

        # Sub-services (created in start())
        self._channels: ChannelManager | None = None
        self._threads: ThreadManager | None = None
        self._messages: MessageStore | None = None
        self._last_stats: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open DB, run schema, create default channels, wire sub-services."""
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            # AD-615: WAL mode for concurrent read/write performance.
            # Matches trust.py:161, routing.py:74 pattern (BF-099 canonical).
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            # AD-615: WAL-safe synchronous downgrade — only WAL checkpoints
            # require full fsync. Reduces write latency ~50% under sustained
            # load without sacrificing durability.
            await self._db.execute("PRAGMA synchronous=NORMAL")
            # AD-615: Verify WAL mode was accepted (can fail on network filesystems)
            async with self._db.execute("PRAGMA journal_mode") as cursor:
                row = await cursor.fetchone()
                actual_mode = row[0] if row else "unknown"
                if actual_mode != "wal":
                    logger.warning(
                        "Ward Room DB: WAL mode not accepted (got %s) — "
                        "concurrent performance may be degraded",
                        actual_mode,
                    )
                else:
                    logger.debug("Ward Room DB: WAL mode enabled")
            await self._db.execute("PRAGMA foreign_keys = ON")
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            # AD-424: Schema migration — add thread_mode and max_responders if missing
            try:
                await self._db.execute("ALTER TABLE threads ADD COLUMN thread_mode TEXT NOT NULL DEFAULT 'discuss'")
            except sqlite3.OperationalError:
                pass
            try:
                await self._db.execute("ALTER TABLE threads ADD COLUMN max_responders INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # AD-485: archived flag for DM message archival
            try:
                await self._db.execute("ALTER TABLE threads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            await self._db.commit()
            # AD-613: Index on archived column (must be after ALTER TABLE above)
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_channel_archived "
                "ON threads(channel_id, archived)"
            )
            await self._db.commit()

        # Wire sub-services (share DB connection)
        self._messages = MessageStore(
            db=self._db,
            emit_fn=self._emit,
            episodic_memory=self._episodic_memory,
            hebbian_router=self._hebbian_router,
            format_trust_fn=format_trust,
            identity_registry=self._identity_registry,
        )
        self._channels = ChannelManager(
            db=self._db,
            ontology=self._ontology,
            subscribe_fn=self._messages.subscribe,
        )
        self._threads = ThreadManager(
            db=self._db,
            emit_fn=self._emit,
            episodic_memory=self._episodic_memory,
            hebbian_router=self._hebbian_router,
            format_trust_fn=format_trust,
            channel_cache=self._channels._channel_cache,
            identity_registry=self._identity_registry,
        )

        await self._channels._ensure_default_channels()
        await self._channels._refresh_channel_cache()
        # Share refreshed cache reference with threads
        self._threads._channel_cache = self._channels._channel_cache

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def is_started(self) -> bool:
        """Whether the Ward Room database connection is active."""
        return self._db is not None

    def set_social_verification(self, svc: Any) -> None:
        """AD-567f / BF-113: Delegate social verification wiring to sub-services."""
        if self._threads:
            self._threads.set_social_verification(svc)
        if self._messages:
            self._messages.set_social_verification(svc)

    def attach_dispatcher(self, dispatcher: Any, callsign_registry: Any) -> None:
        """AD-654d: Late-bind dispatcher into message/thread stores."""
        if self._messages:
            self._messages.attach_dispatcher(dispatcher, callsign_registry)
        if self._threads:
            self._threads.attach_dispatcher(dispatcher, callsign_registry)

    def set_echo_services(
        self,
        thread_echo_analyzer: Any = None,
        observable_state_verifier: Any = None,
        bridge_alerts: Any = None,
        ward_room_router: Any = None,
    ) -> None:
        """AD-583f/583g: Delegate echo detection wiring to sub-services."""
        if self._threads:
            self._threads.set_echo_services(
                thread_echo_analyzer=thread_echo_analyzer,
                observable_state_verifier=observable_state_verifier,
                bridge_alerts=bridge_alerts,
                ward_room_router=ward_room_router,
            )
        if self._messages:
            self._messages.set_echo_services(
                thread_echo_analyzer=thread_echo_analyzer,
                observable_state_verifier=observable_state_verifier,
                bridge_alerts=bridge_alerts,
                ward_room_router=ward_room_router,
            )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> dict[str, Any]:
        """Return basic Ward Room stats for monitoring."""
        if self._last_stats:
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
        if self.db_path:
            loop = asyncio.get_running_loop()
            stats["db_size_bytes"] = await loop.run_in_executor(
                None, lambda: os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            )
        else:
            stats["db_size_bytes"] = 0

        self._last_stats = stats
        return stats

    # ------------------------------------------------------------------
    # Late-init wiring
    # ------------------------------------------------------------------

    def set_ontology(self, ontology: Any) -> None:
        """Inject ontology reference (constructed after WardRoom)."""
        self._ontology = ontology

    # ------------------------------------------------------------------
    # Channel delegation
    # ------------------------------------------------------------------

    async def list_channels(self, agent_id: str | None = None) -> list[WardRoomChannel]:
        return await self._channels.list_channels(agent_id)

    async def create_channel(
        self, name: str, channel_type: str, created_by: str,
        department: str = "", description: str = "",
    ) -> WardRoomChannel:
        return await self._channels.create_channel(name, channel_type, created_by, department, description)

    async def get_channel(self, channel_id: str) -> WardRoomChannel | None:
        return await self._channels.get_channel(channel_id)

    async def get_or_create_dm_channel(
        self, agent_a_id: str, agent_b_id: str,
        callsign_a: str = "", callsign_b: str = "",
    ) -> WardRoomChannel:
        return await self._channels.get_or_create_dm_channel(agent_a_id, agent_b_id, callsign_a, callsign_b)

    def get_channel_snapshot(self) -> list[dict[str, Any]]:
        return self._channels.get_channel_snapshot() if self._channels else []

    async def archive_channel(self, channel_id: str) -> None:
        """Archive a channel by ID (LoD-safe public API)."""
        if self._channels:
            await self._channels.archive_channel(channel_id)

    async def get_channel_by_name(self, name: str) -> WardRoomChannel | None:
        """Get a channel by name (LoD-safe public API)."""
        if self._channels:
            return await self._channels.get_channel_by_name(name)
        return None

    async def get_channel_by_department(self, department: str) -> WardRoomChannel | None:
        """AD-616: Get channel by department (LoD-safe public API)."""
        if self._channels:
            return await self._channels.get_channel_by_department(department)
        return None

    async def get_channel_by_type(self, channel_type: str) -> WardRoomChannel | None:
        """AD-616: Get channel by type (LoD-safe public API)."""
        if self._channels:
            return await self._channels.get_channel_by_type(channel_type)
        return None

    # ------------------------------------------------------------------
    # Thread delegation
    # ------------------------------------------------------------------

    async def list_threads(
        self, channel_id: str, limit: int = 50, offset: int = 0, sort: str = "recent",
        include_archived: bool = False,
    ) -> list[WardRoomThread]:
        return await self._threads.list_threads(channel_id, limit, offset, sort, include_archived)

    async def count_threads(self, channel_id: str) -> int:
        """AD-613: Return thread count for a channel without fetching rows."""
        return await self._threads.count_threads(channel_id)

    async def count_posts_by_author(self, thread_id: str, author_id: str) -> int:
        """AD-614: Count posts by a specific author in a thread."""
        return await self._threads.count_posts_by_author(thread_id, author_id)

    async def get_agent_comm_stats(
        self, agent_id: str, since: float | None = None,
    ) -> dict[str, int | float]:
        """AD-630: Aggregate communication stats for leadership feedback.

        Args:
            agent_id: Agent sovereign ID.
            since: Optional Unix timestamp. If provided, stats cover
                   the window [since, now]. If None, all-time stats.

        Returns:
            Dict with keys: posts_total, endorsements_given,
            endorsements_received, credibility_score.
        """
        posts_total = await self._threads.count_all_posts_by_author(agent_id, since)
        endorsements_given = await self._messages.count_endorsements_by_voter(agent_id, since)
        endorsements_received = await self._messages.count_endorsements_for_author(agent_id, since)
        cred = await self._messages.get_credibility(agent_id)
        return {
            "posts_total": posts_total,
            "endorsements_given": endorsements_given,
            "endorsements_received": endorsements_received,
            "credibility_score": cred.credibility_score,
        }

    async def check_dm_convergence(self, thread_id: str) -> dict | None:
        """AD-623: Check if a DM thread has converged."""
        from probos.ward_room.threads import check_dm_convergence
        if not self._db:
            return None
        return await check_dm_convergence(self._db, thread_id)

    async def browse_threads(
        self, agent_id: str, channels: list[str] | None = None,
        thread_mode: str | None = None, limit: int = 10,
        since: float = 0.0, sort: str = "recent",
    ) -> list[WardRoomThread]:
        return await self._threads.browse_threads(agent_id, channels, thread_mode, limit, since, sort)

    async def get_recent_activity(
        self, channel_id: str, since: float, limit: int = 10,
    ) -> list[dict[str, Any]]:
        return await self._threads.get_recent_activity(channel_id, since, limit)

    async def get_posts_by_author(
        self,
        author_callsign: str,
        limit: int = 5,
        since: float | None = None,
        thread_id: str | None = None,
    ) -> list[dict]:
        """Get recent posts by a specific author."""
        return await self._threads.get_posts_by_author(author_callsign, limit, since, thread_id)

    async def create_thread(
        self, channel_id: str, author_id: str, title: str, body: str,
        author_callsign: str = "", thread_mode: str = "discuss", max_responders: int = 0,
    ) -> WardRoomThread:
        return await self._threads.create_thread(
            channel_id, author_id, title, body, author_callsign, thread_mode, max_responders,
        )

    async def update_thread(self, thread_id: str, **updates: Any) -> WardRoomThread | None:
        return await self._threads.update_thread(thread_id, **updates)

    async def get_thread(self, thread_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return await self._threads.get_thread(thread_id, **kwargs)

    async def archive_dm_messages(self, max_age_hours: int = 24) -> int:
        return await self._threads.archive_dm_messages(max_age_hours)

    async def prune_old_threads(
        self, retention_days: int = 7, retention_days_endorsed: int = 30,
        retention_days_captain: int = 0, archive_path: str | None = None,
    ) -> dict[str, Any]:
        result = await self._threads.prune_old_threads(
            retention_days, retention_days_endorsed, retention_days_captain, archive_path,
        )
        self._last_stats = await self._build_stats()
        return result

    async def count_pruneable(
        self, retention_days: int = 7, retention_days_endorsed: int = 30,
        retention_days_captain: int = 0,
    ) -> int:
        return await self._threads.count_pruneable(retention_days, retention_days_endorsed, retention_days_captain)

    async def start_prune_loop(self, config: Any, archive_dir: Any) -> None:
        await self._threads.start_prune_loop(config, archive_dir)

    async def stop_prune_loop(self) -> None:
        await self._threads.stop_prune_loop()

    # ------------------------------------------------------------------
    # Message delegation
    # ------------------------------------------------------------------

    async def create_post(
        self, thread_id: str, author_id: str, body: str,
        parent_id: str | None = None, author_callsign: str = "",
    ) -> WardRoomPost:
        return await self._messages.create_post(thread_id, author_id, body, parent_id, author_callsign)

    async def get_post(self, post_id: str) -> dict[str, Any] | None:
        return await self._messages.get_post(post_id)

    async def edit_post(self, post_id: str, author_id: str, new_body: str) -> WardRoomPost:
        return await self._messages.edit_post(post_id, author_id, new_body)

    async def endorse(
        self, target_id: str, target_type: str, voter_id: str, direction: str,
    ) -> dict[str, Any]:
        return await self._messages.endorse(target_id, target_type, voter_id, direction)

    async def get_credibility(self, agent_id: str) -> WardRoomCredibility:
        return await self._messages.get_credibility(agent_id)

    async def subscribe(self, agent_id: str, channel_id: str, role: str = "member") -> None:
        await self._messages.subscribe(agent_id, channel_id, role)

    async def unsubscribe(self, agent_id: str, channel_id: str) -> None:
        await self._messages.unsubscribe(agent_id, channel_id)

    async def update_last_seen(self, agent_id: str, channel_id: str) -> None:
        await self._messages.update_last_seen(agent_id, channel_id)

    async def get_unread_counts(self, agent_id: str) -> dict[str, int]:
        return await self._messages.get_unread_counts(agent_id)

    async def get_channel_subscriber_ids(self, channel_id: str) -> set[str]:
        """AD-621: Agent IDs subscribed to a channel."""
        return await self._messages.get_channel_subscriber_ids(channel_id)

    async def get_all_channel_members(self) -> dict[str, set[str]]:
        """AD-621: {channel_id: {agent_ids}} for membership cache."""
        return await self._messages.get_all_channel_members()

    async def get_unread_dms(self, agent_id: str, limit: int = 3, exchange_limit: int = 0) -> list[dict]:
        return await self._messages.get_unread_dms(agent_id, limit, exchange_limit=exchange_limit)
