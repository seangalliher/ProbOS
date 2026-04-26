"""Ward Room post-processing pipeline (AD-654a).

DRY extraction of post-processing logic shared by:
- Agent self-posting path (AD-654a async dispatch)
- Proactive loop observation posting
- Ward Room Router response path (legacy/fallback)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.ward_room.service import WardRoomService

logger = logging.getLogger(__name__)


@dataclass
class PostBudget:
    """BF-237: Tracks whether a create_post has fired in the current pipeline invocation."""
    spent: bool = False


class WardRoomPostPipeline:
    """Process and post an agent's Ward Room response.

    Applies the full post-processing chain: text sanitization (BF-199),
    action extraction (endorsements, replies, DMs, notebooks, recreation),
    similarity guard (BF-197), bracket marker stripping (BF-174),
    and ward room posting.  Records response tracking (BF-198),
    skill exercise (AD-625), and cooldown.
    """

    def __init__(
        self,
        *,
        ward_room: "WardRoomService",
        ward_room_router: Any,  # WardRoomRouter — for record_agent_response, cooldowns, endorsements
        proactive_loop: Any | None,  # ProactiveCognitiveLoop — for extract_and_execute_actions, similarity
        trust_network: Any | None,
        callsign_registry: Any | None,
        config: Any,
        runtime: Any | None = None,  # For skill_service access
    ) -> None:
        self._ward_room = ward_room
        self._router = ward_room_router
        self._proactive_loop = proactive_loop
        self._trust_network = trust_network
        self._callsign_registry = callsign_registry
        self._config = config
        self._runtime = runtime

    async def process_and_post(
        self,
        *,
        agent: Any,
        response_text: str,
        thread_id: str,
        event_type: str,
        post_id: str | None = None,
    ) -> bool:
        """Process agent response text and post to ward room.

        Applies the full post-processing pipeline. Returns True if a post
        was created, False if the response was suppressed (empty, similar,
        or filtered).

        Args:
            agent: Agent object (needs .id, .agent_type attributes)
            response_text: Raw LLM response text
            thread_id: Ward Room thread to post to
            event_type: Original event type ("ward_room_thread_created" or "ward_room_post_created")
            post_id: Parent post ID (for replies to posts, not thread creation)
        """
        # Step 1: Text sanitization (BF-199)
        from probos.utils.text_sanitize import sanitize_ward_room_text
        response_text = sanitize_ward_room_text(response_text)
        if not response_text or response_text == "[NO_RESPONSE]":
            return False

        # Step 2: Resolve callsign
        agent_callsign = ""
        if self._callsign_registry:
            agent_callsign = self._callsign_registry.get_callsign(agent.agent_type)

        # Step 3: Action extraction (endorsements, replies, DMs, notebooks, recreation)
        # BF-237: Budget tracks whether action extractor already posted.
        budget = PostBudget()
        if agent and self._proactive_loop:
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
                post_budget=budget,
            )
            response_text = response_text.strip()
        elif self._router:
            # Fallback: endorsements only
            response_text, endorsements = self._router.extract_endorsements(response_text)
            if endorsements:
                await self._router.process_endorsements(endorsements, agent_id=agent.id)

        if not response_text:
            return False

        # Step 4: Similarity guard (BF-197)
        if agent and self._proactive_loop:
            if await self._proactive_loop.is_similar_to_recent_posts(
                agent, response_text,
            ):
                logger.debug(
                    "AD-654a/BF-197: Suppressed similar response from %s",
                    agent.agent_type,
                )
                return False

        # Step 5: Recreation commands (BF-123)
        if agent and self._router:
            response_text = await self._router.extract_recreation_commands(
                agent, response_text, agent_callsign,
            )
        if not response_text:
            return False

        # Step 6: Bracket marker stripping (BF-174)
        from probos.proactive import _strip_bracket_markers
        response_text = _strip_bracket_markers(response_text)
        if not response_text:
            return False

        # Step 7: Post to Ward Room
        # BF-237: If action extractor already posted, suppress the main post.
        if budget.spent:
            logger.warning(
                "BF-237: Suppressing main post for %s — action extractor already posted in this invocation",
                agent.agent_type,
            )
            # BF-237: Emit telemetry event for observability
            if self._runtime and getattr(self._runtime, 'event_log', None):
                try:
                    await self._runtime.event_log.log(
                        category="pipeline",
                        event="pipeline_post_budget_exceeded",
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        detail=f"thread_id={thread_id}",
                    )
                except Exception:
                    logger.debug("BF-237: telemetry log failed", exc_info=True)
        else:
            parent_id = post_id if event_type == "ward_room_post_created" else None
            await self._ward_room.create_post(
                thread_id=thread_id,
                author_id=agent.id,
                body=response_text,
                parent_id=parent_id,
                author_callsign=agent_callsign or agent.agent_type,
            )

        # Step 8: Record response (BF-198 anti-double-posting)
        # UNCONDITIONAL — runs whether or not Step 7 posted. If the extractor
        # already posted, BF-236's round tracker must still record it so the
        # agent is correctly marked as "has posted in this round."
        if self._router:
            self._router.record_agent_response(agent.id, thread_id)
            self._router.record_round_post(agent.id, thread_id)  # BF-236

        # Step 9: Skill exercise recording (AD-625)
        _rt = self._runtime
        if _rt and hasattr(_rt, 'skill_service') and _rt.skill_service:
            try:
                await _rt.skill_service.record_exercise(agent.id, "communication")
            except Exception:
                logger.debug("AD-654a: Skill exercise recording failed for %s", agent.id, exc_info=True)

        # Step 10: Cooldown update
        if self._router:
            self._router.update_cooldown(agent.id)

        return True
