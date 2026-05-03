"""AD-641c: ThreadPriorityService -- runtime adapter.

Pulls thread state from runtime + WardRoomService, calls the scorer, emits
THREAD_PRIORITY_SCORED, exposes get_priority() and top_priorities() for
consumers (HXI, proactive loop, future grandchild ADs).
"""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.thread_priority.scorer import (
    ThreadPriorityInput,
    ThreadPriorityScore,
    ThreadPriorityScorer,
)
from probos.events import EventType

logger = logging.getLogger(__name__)


class ThreadPriorityService:
    """Public API:
    - get_priority(thread_id) -> ThreadPriorityScore | None
    - top_priorities(channel_id, k=10) -> list[(thread_id, score)]
    """

    def __init__(
        self,
        *,
        runtime: Any,
        scorer: ThreadPriorityScorer,
        emit_event: Any | None = None,
        captain_callsign: str = "Captain",
    ) -> None:
        self._runtime = runtime
        self._scorer = scorer
        self._emit_event = emit_event
        self._captain_callsign = (captain_callsign or "Captain").strip().lower()

    async def get_priority(self, thread_id: str) -> ThreadPriorityScore | None:
        if not thread_id:
            return None
        inp = await self._build_input(thread_id)
        if inp is None:
            return None
        score = self._scorer.score(inp)
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.THREAD_PRIORITY_SCORED,
                    {
                        "thread_id": score.thread_id,
                        "score": score.score,
                        "factors": dict(score.factors),
                    },
                )
            except Exception:
                logger.debug(
                    "ThreadPriorityService: emit THREAD_PRIORITY_SCORED failed",
                    exc_info=True,
                )
        return score

    async def top_priorities(
        self, channel_id: str, k: int = 10,
    ) -> list[tuple[str, float]]:
        if k <= 0 or not channel_id:
            return []
        thread_ids = await self._list_threads(channel_id)
        scored: list[tuple[str, float]] = []
        for tid in thread_ids:
            score = await self.get_priority(tid)
            if score is not None:
                scored.append((score.thread_id, score.score))
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[: int(k)]

    async def _list_threads(self, channel_id: str) -> list[str]:
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return []
        try:
            threads = await ward_room.list_threads(
                channel_id=channel_id, limit=100,
            )
        except Exception:
            return []
        out: list[str] = []
        for t in threads or []:
            tid = getattr(t, "id", None) or (
                t.get("id") if isinstance(t, dict) else None
            )
            if tid:
                out.append(str(tid))
        return out

    async def _build_input(self, thread_id: str) -> ThreadPriorityInput | None:
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return None
        try:
            thread = await ward_room.get_thread(thread_id, post_limit=10)
        except Exception:
            thread = None
        if not thread:
            return None
        # ward_room.get_thread returns a tree:
        #   {"thread": dict, "posts": list[root_post_dict_with_children],
        #    "total_post_count": int}
        # Reply posts are nested under each root's "children" list (verified
        # at threads.py:716-748). _extract_posts recursively flattens so all
        # priority factors run over the full thread, not roots-only.
        posts = self._extract_posts(thread)

        # Posts dicts have NO "department" key (verified at threads.py:727-734);
        # department is per-author and resolved via the standing-orders helper.
        from probos.ward_room._helpers import resolve_author_department

        recent_bodies = [str((p.get("body") or "")) for p in posts[-3:]]
        participants: list[str] = []
        captain_involved = False
        last_post_at = 0.0
        for p in posts:
            callsign = str(p.get("author_callsign") or "")
            if callsign.strip().lower() == self._captain_callsign:
                captain_involved = True
            author_id = str(p.get("author_id") or "")
            if author_id:
                try:
                    dept = resolve_author_department(author_id) or ""
                except Exception:
                    dept = ""
                if dept:
                    participants.append(dept)
            try:
                ts_f = float(p.get("created_at") or 0.0)
            except (TypeError, ValueError):
                ts_f = 0.0
            if ts_f > last_post_at:
                last_post_at = ts_f

        endorsement_count = await self._count_endorsements(thread_id)

        return ThreadPriorityInput(
            thread_id=str(thread_id),
            captain_involved=captain_involved,
            recent_post_bodies=recent_bodies,
            participant_departments=participants,
            last_post_at=last_post_at,
            endorsement_count=endorsement_count,
        )

    def _extract_posts(self, thread: Any) -> list[dict[str, Any]]:
        # ward_room.get_thread returns {"thread": ..., "posts": roots, ...}
        # where roots are dicts with nested "children" lists. Recursively
        # flatten so all reply posts are scored, not just roots.
        if isinstance(thread, dict):
            roots = thread.get("posts") or []
        else:
            roots = getattr(thread, "posts", None) or []
        flat: list[dict[str, Any]] = []

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                flat.append(node)
                children = node.get("children") or []
            else:
                # Defensive: object with attribute access; project to a dict
                # carrying the keys downstream code actually reads.
                flat.append({
                    "id": getattr(node, "id", "") or "",
                    "author_id": getattr(node, "author_id", "") or "",
                    "body": getattr(node, "body", "") or "",
                    "author_callsign": getattr(node, "author_callsign", "") or "",
                    "created_at": getattr(node, "created_at", 0.0) or 0.0,
                })
                children = getattr(node, "children", None) or []
            for child in children:
                _walk(child)

        for root in roots:
            _walk(root)
        return flat

    async def _count_endorsements(self, thread_id: str) -> int:
        event_log = getattr(self._runtime, "event_log", None)
        if event_log is None:
            return 0
        # EventLog.query is async and does NOT accept event_type=. The intended
        # surface is query_structured(event=...) (verified at
        # event_log.py:170-176). Rows are dicts with key "data" (NOT "payload");
        # see _row_to_dict at event_log.py:249-262.
        try:
            entries = await event_log.query_structured(
                event=EventType.WARD_ROOM_ENDORSEMENT.value, limit=200,
            )
        except Exception:
            return 0
        count = 0
        for entry in entries or []:
            data = entry.get("data") if isinstance(entry, dict) else {}
            if not isinstance(data, dict):
                data = {}
            if str(data.get("thread_id") or "") == str(thread_id):
                count += 1
        return count
