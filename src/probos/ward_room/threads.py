"""ThreadManager — thread CRUD, browsing, pruning, and archival."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Awaitable

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.ward_room.models import WardRoomThread, extract_mentions

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# AD-506b: Standalone peer repetition detection (shared by threads + messages)
# ------------------------------------------------------------------

async def check_peer_similarity(
    db: Any, channel_id: str, author_id: str, body: str,
    window_seconds: float = 600.0, threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Check if body is similar to recent posts by OTHER authors in this channel.

    Returns list of matches: [{author_id, author_callsign, body_preview, similarity, post_id}]
    Empty list = no peer similarity detected.
    """
    try:
        since = time.time() - window_seconds
        body_words = text_to_words(body)
        if not body_words:
            return []

        matches: list[dict[str, Any]] = []

        # Check recent threads by other authors
        async with db.execute(
            "SELECT id, author_id, author_callsign, body FROM threads "
            "WHERE channel_id = ? AND created_at > ? AND author_id != ? "
            "ORDER BY created_at DESC LIMIT 20",
            (channel_id, since, author_id),
        ) as cursor:
            async for row in cursor:
                sim = jaccard_similarity(body_words, text_to_words(row[3] or ""))
                if sim >= threshold:
                    matches.append({
                        "author_id": row[1],
                        "author_callsign": row[2] or row[1][:8],
                        "body_preview": (row[3] or "")[:100],
                        "similarity": sim,
                        "post_id": row[0],
                    })

        # Check recent replies by other authors
        async with db.execute(
            "SELECT p.id, p.author_id, p.author_callsign, p.body FROM posts p "
            "JOIN threads t ON p.thread_id = t.id "
            "WHERE t.channel_id = ? AND p.created_at > ? AND p.author_id != ? AND p.deleted = 0 "
            "ORDER BY p.created_at DESC LIMIT 20",
            (channel_id, since, author_id),
        ) as cursor:
            async for row in cursor:
                sim = jaccard_similarity(body_words, text_to_words(row[3] or ""))
                if sim >= threshold:
                    matches.append({
                        "author_id": row[1],
                        "author_callsign": row[2] or row[1][:8],
                        "body_preview": (row[3] or "")[:100],
                        "similarity": sim,
                        "post_id": row[0],
                    })

        matches.sort(key=lambda m: m["similarity"], reverse=True)
        return matches
    except Exception:
        logger.debug("AD-506b: Peer similarity check failed", exc_info=True)
        return []


async def check_dm_convergence(
    db: Any, thread_id: str, window: int = 3, threshold: float = 0.55,
) -> dict[str, Any] | None:
    """AD-623: Detect mutual agreement in DM threads.

    Looks at the last ``window`` consecutive exchange pairs (A->B, B->A) in a
    DM thread. If the average Jaccard similarity across pairs >= threshold,
    the conversation has converged — both sides are restating the same position.

    Returns {"converged": True, "similarity": float, "exchange_count": int}
    if convergence detected, None otherwise.
    """
    try:
        async with db.execute(
            "SELECT author_id, body FROM posts "
            "WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
            (thread_id, window * 2 + 2),
        ) as cursor:
            posts = [(row[0], row[1] or "") async for row in cursor]

        if len(posts) < 4:
            return None  # Need at least 2 exchange pairs

        # Reverse to chronological order
        posts.reverse()

        # Find consecutive exchange pairs (different authors)
        pairs: list[float] = []
        i = 0
        while i < len(posts) - 1 and len(pairs) < window:
            a_author, a_body = posts[i]
            b_author, b_body = posts[i + 1]
            if a_author != b_author:  # Different authors = exchange pair
                sim = jaccard_similarity(text_to_words(a_body), text_to_words(b_body))
                pairs.append(sim)
            i += 1

        if len(pairs) < 2:
            return None  # Need at least 2 exchange pairs to detect convergence

        avg_sim = sum(pairs) / len(pairs)
        if avg_sim >= threshold:
            return {
                "converged": True,
                "similarity": round(avg_sim, 3),
                "exchange_count": len(pairs),
            }

        return None
    except Exception:
        logger.debug("AD-623: DM convergence check failed", exc_info=True)
        return None


class ThreadManager:
    """Thread lifecycle: create, list, browse, prune, archive."""

    def __init__(
        self,
        db: Any,
        emit_fn: Callable[..., Any],
        episodic_memory: Any = None,
        hebbian_router: Any = None,
        format_trust_fn: Callable[..., Any] | None = None,
        channel_cache: list[dict[str, Any]] | None = None,
        identity_registry: Any = None,  # BF-103: for sovereign ID resolution
    ) -> None:
        self._db = db
        self._emit = emit_fn
        self._episodic_memory = episodic_memory
        self._hebbian_router = hebbian_router
        self._format_trust = format_trust_fn
        self._channel_cache = channel_cache if channel_cache is not None else []
        self._prune_task: asyncio.Task | None = None
        self._prune_config: Any = None
        self._archive_dir: Any = None
        self._last_stats: dict[str, Any] | None = None
        self._identity_registry = identity_registry
        self._social_verification: Any = None  # AD-567f: late-bound
        self._content_firewall: Any = None  # AD-529: late-bound
        self._dispatcher: Any | None = None  # AD-654d: late-bound
        self._callsign_registry: Any | None = None  # AD-654d: late-bound

    def set_social_verification(self, svc: Any) -> None:
        """AD-567f: Late-bind social verification service."""
        self._social_verification = svc

    def attach_dispatcher(self, dispatcher: Any, callsign_registry: Any) -> None:
        """AD-654d: Late-bind dispatcher for mention TaskEvent emission."""
        self._dispatcher = dispatcher
        self._callsign_registry = callsign_registry

    def set_content_firewall(self, firewall: Any) -> None:
        """AD-529: Late-bind content contagion firewall."""
        self._content_firewall = firewall

    def set_echo_services(
        self,
        thread_echo_analyzer: Any = None,
        observable_state_verifier: Any = None,
        bridge_alerts: Any = None,
        ward_room_router: Any = None,
    ) -> None:
        """AD-583f/583g: Late-bind echo detection and state verification services."""
        self._thread_echo_analyzer = thread_echo_analyzer
        self._observable_state_verifier = observable_state_verifier
        self._bridge_alerts = bridge_alerts
        self._ward_room_router = ward_room_router

    async def _check_cascade_risk(
        self, peer_matches: list[dict], author_id: str,
        author_callsign: str, post_body: str, channel_id: str,
    ) -> None:
        """AD-567f: Delegate cascade check to shared helper (BF-113 DRY)."""
        from probos.ward_room._helpers import check_and_emit_cascade_risk
        await check_and_emit_cascade_risk(
            self._social_verification, self._emit,
            author_id=author_id, author_callsign=author_callsign,
            post_body=post_body, channel_id=channel_id,
            peer_matches=peer_matches,
        )

    async def _check_echo_trace(
        self, peer_matches: list[dict], thread_id: str, channel_id: str,
    ) -> None:
        """AD-583f/583g: Delegate to helper for echo tracing."""
        from probos.ward_room._helpers import check_and_trace_echo
        await check_and_trace_echo(
            getattr(self, '_thread_echo_analyzer', None),
            getattr(self, '_observable_state_verifier', None),
            self._emit,
            getattr(self, '_bridge_alerts', None),
            getattr(self, '_ward_room_router', None),
            thread_id=thread_id,
            channel_id=channel_id,
            peer_matches=peer_matches,
        )

    @staticmethod
    def _resolve_author_department(author_id: str) -> str:
        """AD-567g: Resolve department for Ward Room episode anchors."""
        from probos.ward_room._helpers import resolve_author_department
        return resolve_author_department(author_id)

    # ------------------------------------------------------------------
    # List / browse
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

    async def count_threads(self, channel_id: str) -> int:
        """AD-613: Return thread count for a channel without fetching rows."""
        if not self._db:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM threads WHERE channel_id = ? AND NOT archived",
            (channel_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_posts_by_author(self, thread_id: str, author_id: str) -> int:
        """AD-614: Count posts by a specific author in a thread."""
        if not self._db:
            return 0
        async with self._db.execute(
            "SELECT COUNT(*) FROM posts WHERE thread_id = ? AND author_id = ? AND deleted = 0",
            (thread_id, author_id),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def count_all_posts_by_author(
        self, author_id: str, since: float | None = None,
    ) -> int:
        """AD-630: Count all posts by an author across all threads.

        Args:
            author_id: Agent sovereign ID.
            since: Optional Unix timestamp — only count posts after this time.

        Returns:
            Total post count.
        """
        if not self._db:
            return 0
        if since is not None:
            sql = "SELECT COUNT(*) FROM posts WHERE author_id = ? AND deleted = 0 AND created_at >= ?"
            params: tuple = (author_id, since)
        else:
            sql = "SELECT COUNT(*) FROM posts WHERE author_id = ? AND deleted = 0"
            params = (author_id,)
        async with self._db.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def browse_threads(
        self,
        agent_id: str,
        channels: list[str] | None = None,
        thread_mode: str | None = None,
        limit: int = 10,
        since: float = 0.0,
        sort: str = "recent",
    ) -> list[WardRoomThread]:
        """Browse threads across one or more channels (AD-425)."""
        if not self._db:
            return []

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
        """Recent threads + posts in a channel since a timestamp."""
        if not self._db:
            return []

        items: list[dict[str, Any]] = []

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
                    "net_score": row[6],
                    "post_id": row[0],
                    "thread_id": row[0],
                })

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
                    "net_score": row[4],
                    "post_id": row[0],
                    "thread_id": row[5],
                })

        items.sort(key=lambda x: x["created_at"], reverse=True)
        return items[:limit]

    # ------------------------------------------------------------------
    # Create / update / get
    # ------------------------------------------------------------------

    async def create_thread(
        self, channel_id: str, author_id: str, title: str, body: str,
        author_callsign: str = "",
        thread_mode: str = "discuss",
        max_responders: int = 0,
    ) -> WardRoomThread:
        """Create thread in channel."""
        if not self._db:
            raise ValueError("Ward Room not initialized")

        # Check channel exists and not archived
        async with self._db.execute(
            "SELECT id, name, archived FROM channels WHERE id = ?", (channel_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Channel {channel_id} not found")
            if row[2]:
                raise ValueError("Channel is archived")
            channel_name = row[1]

        # Check restrictions (query credibility directly)
        async with self._db.execute(
            "SELECT restrictions FROM credibility WHERE agent_id = ?",
            (author_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                import json as _json
                restrictions = _json.loads(row[0]) if row[0] else []
                if "post" in restrictions:
                    raise ValueError("Author is restricted from posting")

        # AD-529: Content firewall scan (after restriction check, before INSERT)
        if self._content_firewall:
            # Thread context for new threads = title only
            _thread_ctx = title or ""
            _scan = self._content_firewall.scan_post(
                author_id=author_id, body=body, thread_context=_thread_ctx,
            )
            if _scan.flagged:
                body = f"[UNVERIFIED — {', '.join(_scan.reasons)}] {body}"
                self._content_firewall.record_flag(author_id, _scan)

        # AD-506b: Peer repetition detection (detection, not suppression)
        peer_matches = await check_peer_similarity(self._db, channel_id, author_id, body)

        now = time.time()
        thread = WardRoomThread(
            id=str(uuid.uuid4()), channel_id=channel_id, author_id=author_id,
            title=title, body=body, created_at=now, last_activity=now,
            author_callsign=author_callsign, channel_name=channel_name,
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

        from probos.events import EventType
        self._emit(EventType.WARD_ROOM_THREAD_CREATED, {
            "thread_id": thread.id,
            "channel_id": channel_id,
            "author_id": author_id,
            "title": title,
            "author_callsign": author_callsign,
            "thread_mode": thread_mode,
            "mentions": extract_mentions(body),
        })

        # AD-654d: Emit mention TaskEvent for each @mentioned agent
        mentions = extract_mentions(body)
        if mentions and self._dispatcher and self._callsign_registry:
            for callsign in mentions:
                resolved = self._callsign_registry.resolve(callsign)
                if resolved and resolved.get("agent_id") and resolved["agent_id"] != author_id:
                    try:
                        from probos.activation import task_event_for_agent
                        from probos.types import Priority
                        event = task_event_for_agent(
                            agent_id=resolved["agent_id"],
                            source_type="ward_room",
                            source_id=thread.id,
                            event_type="mention",
                            priority=Priority.NORMAL,
                            payload={
                                "mentioned_by": author_id,
                                "mentioned_by_callsign": author_callsign,
                                "channel_id": channel_id,
                                "body_preview": body[:200],
                            },
                            thread_id=thread.id,
                        )
                        await self._dispatcher.dispatch(event)
                    except Exception:
                        logger.debug("AD-654d: mention TaskEvent emission failed", exc_info=True)

        # AD-506b: Emit peer repetition event if matches found
        if peer_matches and self._emit:
            from probos.events import EventType as ET
            self._emit(ET.PEER_REPETITION_DETECTED, {
                "channel_id": channel_id,
                "author_id": author_id,
                "author_callsign": author_callsign,
                "matches": [
                    {
                        "author": m["author_callsign"],
                        "similarity": m["similarity"],
                        "post_id": m["post_id"],
                    }
                    for m in peer_matches[:3]
                ],
                "match_count": len(peer_matches),
                "top_similarity": peer_matches[0]["similarity"],
                "post_type": "thread",
                "thread_id": thread.id,
            })

        # AD-567f: Check cascade risk when peer similarity is detected
        await self._check_cascade_risk(peer_matches, author_id, author_callsign, body, channel_id)

        # AD-583f/583g: Echo chain tracing when peer similarity detected
        await self._check_echo_trace(peer_matches, thread.id, channel_id)

        # AD-430a: Store thread creation as authoring agent's episodic memory
        if self._episodic_memory and author_id:
            try:
                from probos.types import AnchorFrame, Episode
                from probos.cognitive.episodic import resolve_sovereign_id_from_slot
                sovereign_id = resolve_sovereign_id_from_slot(author_id, self._identity_registry)
                ch_name = ""
                for ch in self._channel_cache:
                    if ch.get("id") == channel_id:
                        ch_name = ch.get("name", "")
                        break
                episode = Episode(
                    user_input=f"[Ward Room] {ch_name} — {author_callsign or author_id}: {title}",
                    timestamp=time.time(),
                    agent_ids=[sovereign_id],
                    outcomes=[{
                        "intent": "ward_room_post",
                        "success": True,
                        "channel": ch_name,
                        "thread_title": title,
                        "thread_id": thread.id,
                        "is_reply": False,
                        "thread_mode": thread_mode,
                    }],
                    reflection=f"{author_callsign or author_id} posted to {ch_name}: {title[:100]}",
                    source="direct",
                    anchors=AnchorFrame(
                        channel="ward_room",
                        channel_id=channel_id,
                        thread_id=thread.id,
                        trigger_type="ward_room_post",
                        participants=[author_callsign or author_id],
                        trigger_agent=author_callsign or author_id,
                        department=self._resolve_author_department(author_id),
                        source_timestamp=thread.created_at,  # AD-577
                    ),
                )
                from probos.cognitive.episodic import EpisodicMemory
                if EpisodicMemory.should_store(episode):
                    await self._episodic_memory.store(episode)
            except Exception:
                logger.debug("Failed to store thread creation episode", exc_info=True)

        # AD-506b: Store peer repetition episode for the repeating agent
        if peer_matches and self._episodic_memory and author_id:
            top_match = peer_matches[0]
            try:
                from probos.types import AnchorFrame, Episode
                from probos.cognitive.episodic import resolve_sovereign_id_from_slot
                sovereign_id_rep = resolve_sovereign_id_from_slot(author_id, self._identity_registry)
                ep = Episode(
                    timestamp=time.time(),
                    user_input=(
                        f"[Peer echo] Your post in {channel_name} was similar to "
                        f"{top_match['author_callsign']}'s recent post "
                        f"(similarity {top_match['similarity']:.0%})"
                    ),
                    agent_ids=[sovereign_id_rep],
                    outcomes=[{
                        "intent": "peer_repetition",
                        "success": True,
                        "channel": channel_name,
                        "similar_to_author": top_match["author_callsign"],
                        "similarity": top_match["similarity"],
                        "post_id": top_match.get("post_id", ""),
                    }],
                    reflection=(
                        f"System detected overlap between my post and "
                        f"{top_match['author_callsign']}'s recent contribution. "
                        f"Similarity: {top_match['similarity']:.0%}."
                    ),
                    source="direct",
                    anchors=AnchorFrame(
                        channel="ward_room",
                        channel_id=channel_id,
                        thread_id=thread.id if thread else "",
                        trigger_type="peer_repetition",
                        trigger_agent=top_match["author_callsign"],
                        department=self._resolve_author_department(author_id),
                    ),
                )
                await self._episodic_memory.store(ep)
            except Exception:
                logger.debug("AD-506b: Failed to store peer repetition episode", exc_info=True)

        return thread

    async def update_thread(
        self, thread_id: str, **updates: Any,
    ) -> WardRoomThread | None:
        """Update thread fields (AD-424). Captain-level operation."""
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

        from probos.events import EventType
        self._emit(EventType.WARD_ROOM_THREAD_UPDATED, {
            "thread_id": thread_id,
            "updates": filtered,
        })
        return thread

    async def get_thread(self, thread_id: str, *, post_limit: int = 100) -> dict[str, Any] | None:
        """Thread with all posts as nested children tree."""
        if not self._db:
            return None

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

        posts: list[dict[str, Any]] = []
        # AD-613: Count total posts for pagination metadata
        async with self._db.execute(
            "SELECT COUNT(*) FROM posts WHERE thread_id = ?", (thread_id,)
        ) as cursor:
            total_row = await cursor.fetchone()
            total_post_count = total_row[0] if total_row else 0

        # AD-613: Paginate posts — fetch most recent N by default
        async with self._db.execute(
            "SELECT id, thread_id, parent_id, author_id, body, created_at, edited_at, "
            "deleted, delete_reason, deleted_by, net_score, author_callsign "
            "FROM posts WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
            (thread_id, post_limit),
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

        # Reverse to chronological order after DESC LIMIT fetch
        posts.reverse()

        by_id: dict[str, dict] = {p["id"]: p for p in posts}
        roots: list[dict] = []
        for post in posts:
            parent = post["parent_id"]
            if parent and parent in by_id:
                by_id[parent]["children"].append(post)
            else:
                roots.append(post)

        return {"thread": thread_dict, "posts": roots, "total_post_count": total_post_count}

    async def get_thread_posts_temporal(self, thread_id: str) -> list[dict[str, Any]]:
        """Return all posts in a thread, flat and ordered by created_at.

        Unlike get_thread() which nests into a tree, this returns a flat list
        suitable for temporal flow analysis. Includes parent_id for reply-chain
        reconstruction. The thread's own body is included as the first entry.

        AD-583g: Foundation for source tracing — trace how content propagates
        through a thread over time.
        """
        if not self._db:
            return []

        # Include the thread body as the first entry
        result: list[dict[str, Any]] = []
        async with self._db.execute(
            "SELECT id, channel_id, author_id, body, created_at, "
            "author_callsign FROM threads WHERE id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []
            result.append({
                "id": row[0],
                "thread_id": row[0],
                "parent_id": None,
                "author_id": row[2],
                "author_callsign": row[5] or "",
                "body": row[3] or "",
                "created_at": row[4],
            })

        # Flat list of all posts ordered by time
        async with self._db.execute(
            "SELECT id, thread_id, parent_id, author_id, body, created_at, "
            "author_callsign FROM posts WHERE thread_id = ? ORDER BY created_at",
            (thread_id,)
        ) as cursor:
            async for row in cursor:
                result.append({
                    "id": row[0],
                    "thread_id": row[1],
                    "parent_id": row[2],
                    "author_id": row[3],
                    "author_callsign": row[6] or "",
                    "body": row[4] or "",
                    "created_at": row[5],
                })

        return result

    # ------------------------------------------------------------------
    # DM archival
    # ------------------------------------------------------------------

    async def archive_dm_messages(self, max_age_hours: int = 24) -> int:
        """Archive DM thread posts older than max_age_hours. Returns count archived."""
        if not self._db:
            return 0
        cutoff = time.time() - (max_age_hours * 3600)

        async with self._db.execute(
            "SELECT id FROM channels WHERE channel_type = 'dm'"
        ) as cursor:
            dm_channel_ids = [row[0] async for row in cursor]

        if not dm_channel_ids:
            return 0

        placeholders = ','.join('?' * len(dm_channel_ids))
        async with self._db.execute(
            f"UPDATE threads SET archived = 1 WHERE channel_id IN ({placeholders}) "
            f"AND created_at < ? AND (archived = 0 OR archived IS NULL)",
            (*dm_channel_ids, cutoff),
        ) as cursor:
            count = cursor.rowcount

        await self._db.commit()
        return count

    # ------------------------------------------------------------------
    # Pruning (AD-416)
    # ------------------------------------------------------------------

    async def prune_old_threads(
        self,
        retention_days: int = 7,
        retention_days_endorsed: int = 30,
        retention_days_captain: int = 0,
        archive_path: str | None = None,
    ) -> dict[str, Any]:
        """Prune old threads, optionally archiving to JSONL first."""
        if not self._db:
            return {"threads_pruned": 0, "posts_pruned": 0, "endorsements_pruned": 0,
                    "archived_to": None}

        now = time.time()
        regular_cutoff = now - (retention_days * 86400)
        endorsed_cutoff = now - (retention_days_endorsed * 86400)

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

        pruneable: list[dict[str, Any]] = []
        for t in candidates:
            if t["net_score"] > 0 and t["last_activity"] >= endorsed_cutoff:
                continue
            if t["author_id"] == "captain" and retention_days_captain == 0:
                continue
            pruneable.append(t)

        if not pruneable:
            return {"threads_pruned": 0, "posts_pruned": 0, "endorsements_pruned": 0,
                    "archived_to": None}

        thread_ids = [t["id"] for t in pruneable]

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

        all_post_ids: list[str] = []
        for posts in post_map.values():
            all_post_ids.extend(p["id"] for p in posts)

        if archive_path:
            records = []
            for t in pruneable:
                records.append({
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
                })
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write_archive_sync, archive_path, records)

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

        from probos.events import EventType
        summary = {
            "threads_pruned": len(thread_ids),
            "posts_pruned": post_count,
            "endorsements_pruned": endorsement_count,
            "archived_to": archive_path,
            "pruned_thread_ids": thread_ids,
        }
        self._emit(EventType.WARD_ROOM_PRUNED, summary)

        return summary

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
        self._prune_config = config
        self._archive_dir = archive_dir
        self._prune_task = asyncio.create_task(self._prune_loop())

    async def _prune_loop(self) -> None:
        """Periodic pruning of old threads."""
        from datetime import datetime
        while True:
            await asyncio.sleep(self._prune_config.prune_interval_seconds)
            try:
                archive_path = None
                if self._prune_config.archive_enabled:
                    from pathlib import Path
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: Path(self._archive_dir).mkdir(parents=True, exist_ok=True))
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
        if self._prune_task:
            self._prune_task.cancel()
            try:
                await self._prune_task
            except asyncio.CancelledError:
                pass
            self._prune_task = None

    async def get_posts_by_author(
        self,
        author_callsign: str,
        limit: int = 5,
        since: float | None = None,
        thread_id: str | None = None,
    ) -> list[dict]:
        """Get recent posts by a specific author across all channels.

        Returns list of dicts with keys: channel_id, thread_id, post_id,
        body, created_at, parent_id.
        """
        if not self._db:
            return []
        since_ts = since or 0.0
        try:
            posts: list[dict] = []
            if thread_id:
                # AD-623: Filter by specific thread
                async with self._db.execute(
                    """
                    SELECT p.id, p.thread_id, p.body, p.created_at, p.parent_id,
                           t.channel_id
                    FROM posts p
                    JOIN threads t ON p.thread_id = t.id
                    WHERE p.author_callsign = ? AND p.created_at > ?
                          AND p.thread_id = ?
                    ORDER BY p.created_at DESC
                    LIMIT ?
                    """,
                    (author_callsign, since_ts, thread_id, limit),
                ) as cursor:
                    async for row in cursor:
                        posts.append({
                            "post_id": row[0],
                            "thread_id": row[1],
                            "body": row[2],
                            "created_at": row[3],
                            "parent_id": row[4],
                            "channel_id": row[5],
                        })
            else:
                async with self._db.execute(
                    """
                    SELECT p.id, p.thread_id, p.body, p.created_at, p.parent_id,
                           t.channel_id
                    FROM posts p
                    JOIN threads t ON p.thread_id = t.id
                    WHERE p.author_callsign = ? AND p.created_at > ?
                    ORDER BY p.created_at DESC
                    LIMIT ?
                    """,
                    (author_callsign, since_ts, limit),
                ) as cursor:
                    async for row in cursor:
                        posts.append({
                            "post_id": row[0],
                            "thread_id": row[1],
                            "body": row[2],
                            "created_at": row[3],
                            "parent_id": row[4],
                            "channel_id": row[5],
                        })
            return posts
        except Exception:
            logger.debug("Failed to query posts by author %s", author_callsign, exc_info=True)
            return []

    @staticmethod
    def _write_archive_sync(archive_path: str, records: list[dict]) -> None:
        """Write pruned thread records to JSONL archive (sync, run in executor)."""
        import os
        os.makedirs(os.path.dirname(archive_path) if os.path.dirname(archive_path) else ".", exist_ok=True)
        with open(archive_path, "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
