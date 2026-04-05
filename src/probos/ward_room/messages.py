"""MessageStore — post CRUD, endorsements, credibility, and memberships."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable

from probos.ward_room.models import (
    WardRoomCredibility,
    WardRoomPost,
    extract_mentions,
)

logger = logging.getLogger(__name__)


class MessageStore:
    """Post lifecycle, endorsements, credibility, and channel memberships."""

    def __init__(
        self,
        db: Any,
        emit_fn: Callable[..., Any],
        episodic_memory: Any = None,
        hebbian_router: Any = None,
        format_trust_fn: Callable[..., Any] | None = None,
        identity_registry: Any = None,  # BF-103: for sovereign ID resolution
    ) -> None:
        self._db = db
        self._emit = emit_fn
        self._episodic_memory = episodic_memory
        self._hebbian_router = hebbian_router
        self._format_trust = format_trust_fn
        self._identity_registry = identity_registry

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
            "SELECT locked, channel_id FROM threads WHERE id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Thread {thread_id} not found")
            if row[0]:
                raise ValueError("Thread is locked")
            thread_channel_id = row[1]

        # Check restrictions (query credibility directly)
        async with self._db.execute(
            "SELECT restrictions FROM credibility WHERE agent_id = ?",
            (author_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                restrictions = json.loads(row[0]) if row[0] else []
                if "post" in restrictions:
                    raise ValueError("Author is restricted from posting")

        # AD-506b: Peer repetition detection
        from probos.ward_room.threads import check_peer_similarity
        peer_matches = await check_peer_similarity(
            self._db, thread_channel_id, author_id, body,
        )

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

        from probos.events import EventType
        self._emit(EventType.WARD_ROOM_POST_CREATED, {
            "post_id": post.id,
            "thread_id": thread_id,
            "author_id": author_id,
            "parent_id": parent_id,
            "author_callsign": author_callsign,
            "mentions": extract_mentions(body),
        })

        # AD-506b: Emit peer repetition event if matches found
        if peer_matches and self._emit:
            from probos.events import EventType as ET
            self._emit(ET.PEER_REPETITION_DETECTED, {
                "channel_id": thread_channel_id,
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
                "post_type": "reply",
                "thread_id": thread_id,
                "post_id": post.id,
            })

        # AD-430a: Store reply as authoring agent's episodic memory
        if self._episodic_memory and author_id:
            try:
                from probos.types import AnchorFrame, Episode
                from probos.cognitive.episodic import resolve_sovereign_id_from_slot
                sovereign_id = resolve_sovereign_id_from_slot(author_id, self._identity_registry)
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
                    timestamp=time.time(),
                    agent_ids=[sovereign_id],
                    outcomes=[{
                        "intent": "ward_room_post",
                        "success": True,
                        "channel": channel_name,
                        "thread_title": thread_title,
                        "thread_id": thread_id,
                        "is_reply": True,
                    }],
                    reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:60]}': {body[:300]}",
                    source="direct",
                    anchors=AnchorFrame(
                        channel="ward_room",
                        channel_id=channel_name,
                        thread_id=thread_id,
                        trigger_type="ward_room_reply",
                        participants=[author_callsign or author_id],
                        trigger_agent=author_callsign or author_id,
                    ),
                )
                from probos.cognitive.episodic import EpisodicMemory
                if EpisodicMemory.should_store(episode):
                    await self._episodic_memory.store(episode)
            except Exception:
                logger.debug("Failed to store reply episode", exc_info=True)

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
                        f"[Peer echo] Your reply was similar to "
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
                        f"System detected overlap between my reply and "
                        f"{top_match['author_callsign']}'s recent contribution. "
                        f"Similarity: {top_match['similarity']:.0%}."
                    ),
                    source="direct",
                    anchors=AnchorFrame(
                        channel="ward_room",
                        channel_id=channel_name,
                        thread_id=thread_id,
                        trigger_type="peer_repetition",
                        trigger_agent=top_match["author_callsign"],
                    ),
                )
                await self._episodic_memory.store(ep)
            except Exception:
                logger.debug("AD-506b: Failed to store peer repetition episode", exc_info=True)

        # AD-453: Record Hebbian social connections for replies
        if self._hebbian_router and author_id:
            try:
                from probos.mesh.routing import REL_SOCIAL
                from probos.events import EventType as ET
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
                    if self._format_trust:
                        self._emit(ET.HEBBIAN_UPDATE, {
                            "source": author_id, "target": trow[0],
                            "weight": self._format_trust(self._hebbian_router.get_weight(author_id, trow[0])),
                            "rel_type": "social",
                        })
                # @mention connections
                mentions = extract_mentions(body)
                if mentions and hasattr(self, '_resolve_callsign_to_id'):
                    for callsign in mentions:
                        mid = self._resolve_callsign_to_id(callsign)
                        if mid and mid != author_id:
                            self._hebbian_router.record_interaction(
                                source=author_id, target=mid,
                                success=True, rel_type=REL_SOCIAL,
                            )
                            if self._format_trust:
                                self._emit(ET.HEBBIAN_UPDATE, {
                                    "source": author_id, "target": mid,
                                    "weight": self._format_trust(self._hebbian_router.get_weight(author_id, mid)),
                                    "rel_type": "social",
                                })
            except Exception:
                logger.debug("Failed to record Hebbian social interaction", exc_info=True)
        return post

    async def get_post(self, post_id: str) -> dict[str, Any] | None:
        """Return a single post by ID, or None if not found. AD-426."""
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

        score_delta = 0
        cred_delta = 0

        if direction == "unvote":
            if existing_direction == "up":
                score_delta = -1
                cred_delta = -1
            elif existing_direction == "down":
                score_delta = 1
                cred_delta = 1
            await self._db.execute(
                "DELETE FROM endorsements WHERE target_id = ? AND voter_id = ?",
                (target_id, voter_id),
            )
            final_direction = "none"
        else:
            new_val = 1 if direction == "up" else -1
            if existing_direction is None:
                score_delta = new_val
                cred_delta = new_val
            elif existing_direction == direction:
                final_direction = direction
                async with self._db.execute(
                    f"SELECT net_score FROM {'threads' if target_type == 'thread' else 'posts'} WHERE id = ?",
                    (target_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    return {"net_score": row[0] if row else 0, "voter_direction": final_direction}
            else:
                old_val = 1 if existing_direction == "up" else -1
                score_delta = new_val - old_val
                cred_delta = new_val - old_val

            now = time.time()
            await self._db.execute(
                "INSERT INTO endorsements (id, target_id, target_type, voter_id, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(target_id, voter_id) DO UPDATE SET direction = ?, created_at = ?",
                (str(uuid.uuid4()), target_id, target_type, voter_id, direction, now,
                 direction, now),
            )
            final_direction = direction

        table = "threads" if target_type == "thread" else "posts"
        if score_delta != 0:
            await self._db.execute(
                f"UPDATE {table} SET net_score = net_score + ? WHERE id = ?",
                (score_delta, target_id),
            )

        if cred_delta != 0:
            await self._update_credibility(author_id, cred_delta)

        await self._db.commit()

        async with self._db.execute(
            f"SELECT net_score FROM {table} WHERE id = ?", (target_id,),
        ) as cursor:
            row = await cursor.fetchone()
            net_score = row[0] if row else 0

        from probos.events import EventType
        self._emit(EventType.WARD_ROOM_ENDORSEMENT, {
            "target_id": target_id,
            "target_type": target_type,
            "voter_id": voter_id,
            "direction": final_direction,
            "net_score": net_score,
        })

        return {"net_score": net_score, "voter_direction": final_direction}

    # ------------------------------------------------------------------
    # Credibility
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

        await self._db.execute(
            "INSERT INTO credibility (agent_id) VALUES (?) ON CONFLICT(agent_id) DO NOTHING",
            (agent_id,),
        )

        async with self._db.execute(
            "SELECT credibility_score, total_endorsements FROM credibility WHERE agent_id = ?",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return
            score = row[0]
            total = row[1]

        new_score = score * 0.95 + (0.5 + endorsement_delta * 0.1) * 0.05
        new_score = max(0.0, min(1.0, new_score))
        new_total = total + endorsement_delta

        await self._db.execute(
            "UPDATE credibility SET credibility_score = ?, total_endorsements = ? WHERE agent_id = ?",
            (new_score, new_total, agent_id),
        )

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
        """Return DM threads where agent_id is a participant but hasn't replied."""
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
