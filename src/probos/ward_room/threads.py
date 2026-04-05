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

    def set_social_verification(self, svc: Any) -> None:
        """AD-567f: Late-bind social verification service."""
        self._social_verification = svc

    def _resolve_author_department(self, author_id: str) -> str:
        """AD-567g: Resolve department for Ward Room episode anchors."""
        try:
            from probos.cognitive.standing_orders import get_department
            return get_department(author_id) or ""
        except Exception:
            return ""

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
        if peer_matches and self._social_verification:
            try:
                cascade = await self._social_verification.check_cascade_risk(
                    author_id=author_id,
                    author_callsign=author_callsign,
                    post_body=body,
                    channel_id=channel_id,
                    peer_matches=peer_matches,
                )
                if cascade and cascade.risk_level in ("medium", "high"):
                    import dataclasses
                    from probos.events import EventType as _ET
                    if self._emit:
                        self._emit(
                            _ET.CASCADE_CONFABULATION_DETECTED,
                            dataclasses.asdict(cascade),
                        )
            except Exception:
                logger.debug("AD-567f: cascade check failed", exc_info=True)

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

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
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
