"""Social Memory -- Cross-Agent Memory Query Protocol (AD-462d).

"Does anyone remember?" -- When an agent can't recall something from
their own sovereign memory shard, they can post a memory query to
the Ward Room. Other agents detect the query during their proactive
cycle and respond from their episodic memory if they have relevant
matches.

This is PROTOCOL, not infrastructure. It uses existing Ward Room
threads + episodic recall. The SocialMemoryService coordinates
the query/response lifecycle.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    """Format a duration as a human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


class SocialMemoryService:
    """Cross-agent memory query protocol (AD-462d).

    Coordinates query/response lifecycle:
    1. post_memory_query() -- agent posts "does anyone remember?"
    2. check_and_respond_to_queries() -- other agents check & respond
    3. get_query_responses() -- requester collects answers
    """

    def __init__(
        self,
        *,
        ward_room: Any = None,
        episodic_memory: Any = None,
    ):
        self._ward_room = ward_room
        self._episodic_memory = episodic_memory

    async def post_memory_query(
        self,
        requesting_agent_id: str,
        requesting_callsign: str,
        query: str,
        *,
        department_channel_id: str = "",
        k: int = 3,
    ) -> str | None:
        """Post a memory query to the Ward Room.

        Creates a thread with thread_mode='memory_query' in the agent's
        department channel. Returns the thread_id if created, None if
        ward_room unavailable.
        """
        if not self._ward_room:
            return None

        try:
            thread = await self._ward_room.create_thread(
                channel_id=department_channel_id,
                author_id=requesting_agent_id,
                title=f"[Memory Query] {query[:80]}",
                body=f"Does anyone remember: {query}",
                author_callsign=requesting_callsign,
                thread_mode="memory_query",
                max_responders=k,
            )
            return thread.id
        except Exception:
            logger.debug("AD-462d: Failed to post memory query", exc_info=True)
            return None

    async def check_and_respond_to_queries(
        self,
        agent_id: str,
        agent_callsign: str,
        *,
        since: float = 0.0,
        max_queries: int = 3,
    ) -> list[dict[str, Any]]:
        """Check for open memory queries and respond if agent has relevant memories.

        Returns list of dicts: [{"thread_id": ..., "query": ..., "responded": bool}]
        """
        if not self._ward_room or not self._episodic_memory:
            return []

        responses: list[dict[str, Any]] = []
        try:
            threads = await self._ward_room.browse_threads(
                agent_id=agent_id,
                thread_mode="memory_query",
                limit=max_queries,
                since=since,
            )
        except Exception:
            logger.debug("AD-462d: Failed to browse memory query threads", exc_info=True)
            return []

        for thread in threads:
            thread_id = thread.id
            author_id = thread.author_id

            # Skip own queries
            if author_id == agent_id:
                responses.append({"thread_id": thread_id, "query": thread.title, "responded": False})
                continue

            # Check if already responded
            try:
                thread_data = await self._ward_room.get_thread(thread_id)
                if thread_data:
                    posts = thread_data.get("posts", [])
                    already_responded = any(
                        (p.get("author_id") if isinstance(p, dict) else getattr(p, "author_id", "")) == agent_id
                        for p in posts
                    )
                    if already_responded:
                        responses.append({"thread_id": thread_id, "query": thread.title, "responded": False})
                        continue
            except Exception:
                logger.debug("AD-462d: Failed to check thread %s", thread_id, exc_info=True)
                continue

            # Extract query text from title
            query_text = thread.title
            if query_text.startswith("[Memory Query] "):
                query_text = query_text[len("[Memory Query] "):]

            # Try to recall relevant memories
            responded = False
            try:
                if hasattr(self._episodic_memory, "recall_for_agent"):
                    episodes = await self._episodic_memory.recall_for_agent(agent_id, query_text, k=2)
                    if episodes:
                        for ep in episodes:
                            content = getattr(ep, "user_input", "") or ""
                            if len(content) > 20:
                                source = getattr(ep, "source", "unknown")
                                age = _format_duration(time.time() - getattr(ep, "timestamp", time.time()))
                                await self._ward_room.create_post(
                                    thread_id=thread_id,
                                    author_id=agent_id,
                                    body=f"I recall: {content[:300]}. Source: {source}, {age} ago.",
                                    author_callsign=agent_callsign,
                                )
                                responded = True
                                break  # One response per thread
            except Exception:
                logger.debug("AD-462d: Failed to respond to query %s", thread_id, exc_info=True)

            responses.append({"thread_id": thread_id, "query": thread.title, "responded": responded})

        return responses

    async def get_query_responses(
        self,
        thread_id: str,
    ) -> list[dict[str, str]]:
        """Get responses to a memory query thread.

        Returns list of dicts: [{"responder_id": ..., "content": ..., "timestamp": ...}]
        """
        if not self._ward_room:
            return []

        try:
            thread_data = await self._ward_room.get_thread(thread_id)
            if not thread_data:
                return []

            thread_info = thread_data.get("thread", {})
            original_author = (
                thread_info.get("author_id")
                if isinstance(thread_info, dict)
                else getattr(thread_info, "author_id", "")
            )

            responses: list[dict[str, str]] = []
            posts = thread_data.get("posts", [])
            for p in posts:
                if isinstance(p, dict):
                    p_author = p.get("author_id", "")
                    p_body = p.get("body", "")
                    p_ts = str(p.get("created_at", ""))
                else:
                    p_author = getattr(p, "author_id", "")
                    p_body = getattr(p, "body", "")
                    p_ts = str(getattr(p, "created_at", ""))

                # Skip the original query post
                if p_author == original_author:
                    continue

                responses.append({
                    "responder_id": p_author,
                    "content": p_body,
                    "timestamp": p_ts,
                })

            return responses
        except Exception:
            logger.debug("AD-462d: Failed to get query responses for %s", thread_id, exc_info=True)
            return []
