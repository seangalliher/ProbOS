"""Ward Room post-processing pipeline (AD-654a).

DRY extraction of post-processing logic shared by:
- Agent self-posting path (AD-654a async dispatch)
- Proactive loop observation posting
- Ward Room Router response path (legacy/fallback)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.cognitive.novelty_gate import NoveltyGate
    from probos.ward_room.service import WardRoomService

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Minimal structured response used by AD-756 merge helper."""

    content: str
    agent: str
    intent: str


async def merge_agent_responses(responses: list[AgentResponse]) -> str:
    """Merge multi-agent responses into one coherent response.

    Current OSS implementation deduplicates repeated content and cites the
    originating agent for each retained line.
    """
    seen: set[str] = set()
    merged_lines: list[str] = []

    for response in responses:
        if response.content in seen:
            continue
        merged_lines.append(f"[{response.agent}] {response.content}")
        seen.add(response.content)

    return "\n".join(merged_lines)


@dataclass
class PostBudget:
    """BF-237: Tracks whether a create_post has fired in the current pipeline invocation."""
    spent: bool = False


class PostBudgetTelemetry:
    """BF-238: Aggregate per-agent + per-thread counters for PostBudget exhaustion.

    Records every `process_and_post()` invocation and every Step-7 suppression
    triggered by an already-spent PostBudget. Exposes per-agent / per-thread
    / overall exhaustion rate plus a bounded ring buffer of recent
    suppressions for ops review.

    Observational only - never mutates pipeline state, never blocks posts.
    The event_log row written by BF-237 in `WardRoomPostPipeline` is the
    durable audit trail; this class is the in-memory aggregate surface.
    """

    def __init__(
        self,
        *,
        exhaustion_alert_threshold: float = 0.5,
        min_samples_for_alert: int = 10,
        recent_suppressions_max: int = 100,
    ) -> None:
        self._exhaustion_alert_threshold = float(exhaustion_alert_threshold)
        self._min_samples_for_alert = int(min_samples_for_alert)
        self._recent_suppressions_max = int(recent_suppressions_max)
        self._total_invocations = 0
        self._total_exhaustions = 0
        self._invocations_by_agent: dict[str, int] = {}
        self._exhaustions_by_agent: dict[str, int] = {}
        self._invocations_by_thread: dict[str, int] = {}
        self._exhaustions_by_thread: dict[str, int] = {}
        self._recent_suppressions: list[tuple[float, str, str]] = []
        # One-shot guard: agents that have already triggered a threshold alert.
        self._alerted_agents: set[str] = set()

    # --- Public read-only properties ---

    @property
    def total_invocations(self) -> int:
        return self._total_invocations

    @property
    def total_exhaustions(self) -> int:
        return self._total_exhaustions

    @property
    def alert_threshold(self) -> float:
        return self._exhaustion_alert_threshold

    @property
    def min_samples_for_alert(self) -> int:
        return self._min_samples_for_alert

    # --- Recording API (called by WardRoomPostPipeline) ---

    def record_invocation(self, agent_type: str, thread_id: str) -> None:
        """Increment per-agent + per-thread + total invocation counters."""
        self._total_invocations += 1
        if agent_type:
            self._invocations_by_agent[agent_type] = (
                self._invocations_by_agent.get(agent_type, 0) + 1
            )
        if thread_id:
            self._invocations_by_thread[thread_id] = (
                self._invocations_by_thread.get(thread_id, 0) + 1
            )

    def record_exhaustion(self, agent_type: str, thread_id: str) -> None:
        """Increment per-agent + per-thread + total exhaustion counters and
        append to the recent-suppressions ring buffer.

        Triggers a one-shot WARN alert when the per-agent rate first crosses
        the configured threshold AND per-agent invocations are at or above
        the min-samples gate.
        """
        self._total_exhaustions += 1
        if agent_type:
            self._exhaustions_by_agent[agent_type] = (
                self._exhaustions_by_agent.get(agent_type, 0) + 1
            )
        if thread_id:
            self._exhaustions_by_thread[thread_id] = (
                self._exhaustions_by_thread.get(thread_id, 0) + 1
            )
        # Append to ring buffer, bounded by recent_suppressions_max.
        self._recent_suppressions.append((time.time(), agent_type, thread_id))
        if len(self._recent_suppressions) > self._recent_suppressions_max:
            # Drop oldest entries to enforce the bound.
            overflow = len(self._recent_suppressions) - self._recent_suppressions_max
            self._recent_suppressions = self._recent_suppressions[overflow:]

        # One-shot threshold alert.
        self._maybe_alert(agent_type)

    # --- Read API ---

    def exhaustion_rate(
        self,
        *,
        agent_type: str | None = None,
        thread_id: str | None = None,
    ) -> float | None:
        """Return exhaustion rate as `exhaustions / invocations`.

        Scope precedence (mutually exclusive in v1; if both supplied,
        agent_type wins to keep the API single-axis):
          - agent_type given -> per-agent rate
          - thread_id given  -> per-thread rate
          - neither          -> overall rate

        Returns None when the corresponding invocation count is zero.
        """
        if agent_type:
            invocations = self._invocations_by_agent.get(agent_type, 0)
            exhaustions = self._exhaustions_by_agent.get(agent_type, 0)
        elif thread_id:
            invocations = self._invocations_by_thread.get(thread_id, 0)
            exhaustions = self._exhaustions_by_thread.get(thread_id, 0)
        else:
            invocations = self._total_invocations
            exhaustions = self._total_exhaustions
        if invocations == 0:
            return None
        return exhaustions / invocations

    def recent_suppressions(
        self, limit: int = 10
    ) -> tuple[tuple[float, str, str], ...]:
        """Return the most recent suppressions for ops spot-check.

        Each entry is `(timestamp, agent_type, thread_id)`. Newest last.
        `limit <= 0` returns an empty tuple.
        """
        if limit <= 0:
            return ()
        # Slice from the tail; preserves insertion order (newest last).
        return tuple(self._recent_suppressions[-limit:])

    # --- Internal ---

    def _maybe_alert(self, agent_type: str) -> None:
        """One-shot per-agent WARN when rate first crosses threshold."""
        if not agent_type or agent_type in self._alerted_agents:
            return
        invocations = self._invocations_by_agent.get(agent_type, 0)
        if invocations < self._min_samples_for_alert:
            return
        rate = self.exhaustion_rate(agent_type=agent_type)
        if rate is None or rate <= self._exhaustion_alert_threshold:
            return
        self._alerted_agents.add(agent_type)
        logger.warning(
            "BF-238: PostBudget exhaustion rate %.2f for agent_type=%s "
            "exceeds threshold %.2f over %d invocations; review whether "
            "post_budget limit is too aggressive for this agent",
            rate, agent_type, self._exhaustion_alert_threshold, invocations,
        )


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
        novelty_gate: "NoveltyGate | None" = None,  # AD-493
        post_budget_telemetry: "PostBudgetTelemetry | None" = None,  # BF-238
    ) -> None:
        self._ward_room = ward_room
        self._router = ward_room_router
        self._proactive_loop = proactive_loop
        self._trust_network = trust_network
        self._callsign_registry = callsign_registry
        self._config = config
        self._runtime = runtime
        self._novelty_gate = novelty_gate
        self._post_budget_telemetry = post_budget_telemetry  # BF-238

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
        # BF-238: Record every pipeline invocation BEFORE early-return guards
        # so the rate denominator includes empty-text returns.
        if self._post_budget_telemetry is not None:
            self._post_budget_telemetry.record_invocation(
                agent.agent_type if agent else "",
                thread_id,
            )

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

        # Step 4b: Semantic novelty gate (AD-493)
        if self._novelty_gate and agent:
            try:
                verdict = self._novelty_gate.check(agent.id, response_text)
                if not verdict.is_novel:
                    logger.info(
                        "AD-493: Pipeline suppressed rehashed post from %s (sim=%.3f)",
                        agent.agent_type, verdict.similarity,
                    )
                    return False
            except Exception:
                logger.debug("AD-493: Pipeline novelty check failed, allowing post", exc_info=True)

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
            # AD-832: This is expected, healthy dedup behavior — the action
            # extractor already posted a [REPLY]/[MOVE] in this invocation, so
            # the redundant main post is intentionally suppressed. Logged at
            # info (not warning) so observers do not misread it as a fault.
            logger.info(
                "AD-832: Duplicate post suppressed for %s — action extractor already posted "
                "in this invocation (expected dedup behavior, not an error)",
                agent.agent_type,
            )
            # BF-238: Aggregate counter + threshold-alert surface.
            if self._post_budget_telemetry is not None:
                self._post_budget_telemetry.record_exhaustion(
                    agent.agent_type, thread_id,
                )
            # BF-237 / AD-832: Emit self-documenting telemetry event for observability.
            if self._runtime and getattr(self._runtime, 'event_log', None):
                try:
                    await self._runtime.event_log.log(
                        category="pipeline",
                        event="pipeline_duplicate_post_suppressed",
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        detail=(
                            f"thread_id={thread_id} — expected dedup: action extractor "
                            "already posted in this invocation (benign, not a fault)"
                        ),
                        data={
                            "benign": True,
                            "reason": "action_extractor_already_posted",
                            "thread_id": thread_id,
                            "expected": True,
                        },
                    )
                except Exception:
                    logger.debug("AD-832: telemetry log failed", exc_info=True)
        else:
            parent_id = post_id if event_type == "ward_room_post_created" else None
            await self._ward_room.create_post(
                thread_id=thread_id,
                author_id=agent.id,
                body=response_text,
                parent_id=parent_id,
                author_callsign=agent_callsign or agent.agent_type,
            )

        # AD-492: Log correlation_id for trace threading
        _wm = getattr(agent, '_working_memory', None) if agent else None
        _corr_id = _wm.get_correlation_id() if _wm else None
        if _corr_id:
            logger.debug(
                "AD-492: Ward Room post in thread %s by %s (correlation_id=%s)",
                thread_id[:8], agent.agent_type, _corr_id,
            )

        # AD-493: Record observation fingerprint (covers both posting paths)
        if self._novelty_gate and agent:
            try:
                self._novelty_gate.record(agent.id, response_text)
            except Exception:
                logger.debug("AD-493: Pipeline fingerprint recording failed", exc_info=True)

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
