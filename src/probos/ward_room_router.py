"""AD-515: Ward Room event routing extracted from ProbOSRuntime.

Routes Ward Room events (threads, posts) to relevant crew agents via the intent bus.
Multi-layered loop prevention: depth cap, selective targeting, once-per-round, cooldown.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from probos.crew_utils import is_crew_agent

if TYPE_CHECKING:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.crew_profile import CallsignRegistry
    from probos.mesh.intent import IntentBus
    from probos.ontology import VesselOntologyService
    from probos.proactive import ProactiveCognitiveLoop
    from probos.substrate.event_log import EventLog
    from probos.substrate.registry import AgentRegistry
    from probos.ward_room import WardRoomService

logger = logging.getLogger(__name__)


class WardRoomRouter:
    """Routes Ward Room events to crew agents via intents."""

    _WARD_ROOM_COOLDOWN_SECONDS = 30  # Minimum seconds between responses per agent (captain-triggered)

    def __init__(
        self,
        *,
        ward_room: WardRoomService,
        registry: AgentRegistry,
        intent_bus: IntentBus,
        trust_network: TrustNetwork,
        ontology: VesselOntologyService | None,
        callsign_registry: CallsignRegistry,
        episodic_memory: EpisodicMemory | None,
        event_emitter: Callable,
        event_log: EventLog,
        config: SystemConfig,
        notify_fn: Callable | None = None,
        proactive_loop: ProactiveCognitiveLoop | None = None,
    ) -> None:
        self._ward_room = ward_room
        self._registry = registry
        self._intent_bus = intent_bus
        self._trust_network = trust_network
        self._ontology = ontology
        self._callsign_registry = callsign_registry
        self._episodic_memory = episodic_memory
        self._event_emitter = event_emitter
        self._event_log = event_log
        self._config = config
        self._notify_fn = notify_fn
        self._proactive_loop = proactive_loop

        # State
        self._cooldowns: dict[str, float] = {}  # agent_id -> last_response_timestamp
        self._thread_rounds: dict[str, int] = {}  # thread_id -> current agent round count
        self._round_participants: dict[str, set[str]] = {}  # "thread_id:round" -> set of agent_ids
        self._agent_thread_responses: dict[str, int] = {}  # "thread_id:agent_id" -> count
        self._coalesce_timers: dict[str, asyncio.TimerHandle] = {}  # AD-616: thread_id -> pending timer
        self._coalesce_ms: int = getattr(config.ward_room, 'event_coalesce_ms', 200)
        self._channel_members: dict[str, set[str]] = {}  # AD-621: channel_id -> {agent_ids}
        self._dept_thread_responses: dict[str, set[str]] = {}  # AD-629: thread_id -> {department_ids}
        # BF-198: Track threads each agent has already responded to.
        # Shared between router path and proactive loop to prevent double-response.
        # Key: (agent_id, thread_id), Value: timestamp of response.
        self._responded_threads: dict[tuple[str, str], float] = {}
        self._last_responded_eviction: float = time.time()
        self._cap_notices_posted: set[tuple[str, str]] = set()  # BF-200: (thread_id, cap_name)
        # BF-188: Captain delivery coordination — agent-reply routing waits
        # until Captain's routing to all targets completes
        self._captain_delivery_done: asyncio.Event = asyncio.Event()
        self._captain_delivery_done.set()  # Initially done (no Captain routing in progress)

    # ------------------------------------------------------------------
    # BF-198: Responded-thread tracker (prevents router/proactive double-post)
    # ------------------------------------------------------------------

    def record_agent_response(self, agent_id: str, thread_id: str) -> None:
        """BF-198: Record that agent has responded to thread."""
        if not agent_id or not thread_id:
            return
        self._responded_threads[(agent_id, thread_id)] = time.time()

    def has_agent_responded(self, agent_id: str, thread_id: str) -> bool:
        """BF-198: Check if agent already responded to thread."""
        if not agent_id or not thread_id:
            return False
        return (agent_id, thread_id) in self._responded_threads

    def _evict_stale_responses(self, max_age: float = 600.0) -> None:
        """BF-198: Evict response records older than ``max_age`` seconds."""
        cutoff = time.time() - max_age
        self._responded_threads = {
            k: v for k, v in self._responded_threads.items() if v > cutoff
        }
        self._last_responded_eviction = time.time()

    def _maybe_evict_stale_responses(self, interval: float = 60.0) -> None:
        """BF-198: Periodic eviction — runs at most once per ``interval`` seconds."""
        if time.time() - self._last_responded_eviction >= interval:
            self._evict_stale_responses()

    # ------------------------------------------------------------------
    # BF-200: Cap notification posting
    # ------------------------------------------------------------------

    async def _post_cap_notification(
        self, thread_id: str, agent_id: str, cap_name: str,
    ) -> None:
        """BF-200: Post a system notice when a response cap silences an agent."""
        if not self._ward_room:
            return
        # Deduplicate: only post once per (thread, cap_name)
        cap_key = (thread_id, cap_name)
        if cap_key in self._cap_notices_posted:
            return
        self._cap_notices_posted.add(cap_key)

        # Evict if set grows large
        if len(self._cap_notices_posted) > 500:
            self._cap_notices_posted.clear()

        callsign = ""
        if agent_id:
            # Try to get callsign from the agent registry
            try:
                agent = self._registry.get(agent_id)
                if agent:
                    callsign = getattr(agent, 'callsign', '') or agent_id[:8]
            except Exception:
                callsign = agent_id[:8]

        if callsign:
            body = (
                f"[System] Thread response limit reached for {callsign}. "
                "To continue this discussion, start a new thread or DM."
            )
        else:
            body = (
                "[System] Thread response limit reached. "
                "To continue this discussion, start a new thread or DM."
            )
        try:
            await self._ward_room.create_post(
                thread_id=thread_id,
                author_id="system",
                body=body,
                author_callsign="System",
            )
        except Exception:
            logger.debug("BF-200: Failed to post cap notification", exc_info=True)

    # ------------------------------------------------------------------
    # AD-625: Communication proficiency helpers
    # ------------------------------------------------------------------

    def _get_comm_gate_overrides(self, agent_id: str):
        """AD-625: Look up communication proficiency gate overrides for an agent."""
        _rt = getattr(self._proactive_loop, '_runtime', None) if self._proactive_loop else None
        if not _rt or not hasattr(_rt, 'skill_service'):
            return None
        try:
            _profile = getattr(_rt, '_comm_profiles', {}).get(agent_id)
            if _profile is None:
                return None
            for rec in _profile.all_skills:
                if rec.skill_id == "communication":
                    from probos.cognitive.comm_proficiency import get_gate_overrides
                    return get_gate_overrides(rec.proficiency)
        except Exception:
            logger.debug("Comm gate override lookup failed for %s", agent_id, exc_info=True)
        return None

    # ------------------------------------------------------------------
    # AD-629: Unified reply cap — single enforcement point
    # ------------------------------------------------------------------

    # Return sentinels for check_and_increment_reply_cap
    CAP_ALLOWED = "allowed"
    CAP_AGENT_LIMIT = "agent_limit"
    CAP_DEPT_GATE = "dept_gate"

    def check_and_increment_reply_cap(
        self, thread_id: str, agent_id: str,
        *, is_department_channel: bool = False,
    ) -> str:
        """Check whether agent_id may reply to thread_id.

        Returns CAP_ALLOWED if the agent is under the cap (reply allowed).
        Returns CAP_AGENT_LIMIT if the per-agent cap is reached.
        Returns CAP_DEPT_GATE if another agent from the same department
        already responded (first-responder filter, not a cap).
        When CAP_ALLOWED, atomically increments the counter.

        AD-629: Single enforcement point. Both ward_room_router.route_event()
        and proactive.py._extract_and_execute_replies() call this instead of
        inlining their own checks.

        BF-194: ``is_department_channel`` scopes the per-department gate. On
        department channels the gate fires (first responder per department
        wins). On ship-wide channels (All Hands, Recreation) the gate is
        skipped so all crew can acknowledge Captain all-hands messages.
        Default ``False`` over-permits rather than under-permits, which is
        the safe failure mode for Captain-facing traffic.
        """
        # --- Per-agent cap ---
        max_per_thread = getattr(
            self._config.ward_room, 'max_agent_responses_per_thread', 3,
        )
        # AD-625: Proficiency-modulated gate override
        _overrides = self._get_comm_gate_overrides(agent_id)
        if _overrides is not None:
            max_per_thread = _overrides.max_responses_per_thread

        thread_agent_key = f"{thread_id}:{agent_id}"
        prior_responses = self._agent_thread_responses.get(thread_agent_key, 0)
        if prior_responses >= max_per_thread:
            logger.debug(
                "AD-629: Agent %s hit per-thread cap (%d) in thread %s",
                agent_id[:12], max_per_thread, thread_id[:8],
            )
            return self.CAP_AGENT_LIMIT

        # --- Per-department gate (first responder wins) ---
        # BF-194: Only apply on department channels — ship-wide channels
        # (All Hands, Recreation) allow multiple agents per department.
        if is_department_channel:
            dept_id = None
            if self._ontology:
                agent_obj = self._registry.get(agent_id)
                if agent_obj:
                    dept_id = self._ontology.get_agent_department(agent_obj.agent_type)
            if dept_id:
                dept_set = self._dept_thread_responses.get(thread_id, set())
                if dept_id in dept_set:
                    logger.debug(
                        "AD-629: Dept %s already replied in thread %s, blocking %s",
                        dept_id, thread_id[:8], agent_id[:12],
                    )
                    return self.CAP_DEPT_GATE
                # Record department participation
                self._dept_thread_responses.setdefault(thread_id, set()).add(dept_id)

        # Increment and allow
        self._agent_thread_responses[thread_agent_key] = prior_responses + 1
        return self.CAP_ALLOWED

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def populate_membership_cache(self) -> None:
        """AD-621: Build channel→agents membership cache from DB.

        Called once from finalize.py after startup subscriptions are set.
        Provides O(1) lookup for find_targets() without async DB queries.
        """
        try:
            self._channel_members = await self._ward_room.get_all_channel_members()
        except Exception:
            self._channel_members = {}

    def _get_channel_subscribers(self, channel_id: str) -> set[str]:
        """AD-621: Get agent IDs subscribed to a channel from cache."""
        return self._channel_members.get(channel_id, set())

    def get_cooldowns(self) -> dict[str, float]:
        """Return a copy of current agent cooldowns."""
        return dict(self._cooldowns)

    async def route_event_coalesced(self, event_type: str, data: dict[str, Any]) -> None:
        """AD-616: Coalesce rapid-fire post events per thread.

        Thread creation events and non-post events are routed immediately.
        Post events are delayed by coalesce_ms — if another post arrives for the
        same thread within the window, the timer resets and only the latest
        event is routed.
        """
        # Thread creation and non-post events: route immediately
        if event_type != "ward_room_post_created" or self._coalesce_ms <= 0:
            await self.route_event(event_type, data)
            return

        thread_id = data.get("thread_id", "")
        if not thread_id:
            await self.route_event(event_type, data)
            return

        # Cancel any pending timer for this thread
        existing = self._coalesce_timers.pop(thread_id, None)
        if existing:
            existing.cancel()

        # Schedule routing after the coalesce window
        loop = asyncio.get_running_loop()

        async def _fire() -> None:
            self._coalesce_timers.pop(thread_id, None)
            await self.route_event(event_type, data)

        handle = loop.call_later(
            self._coalesce_ms / 1000.0,
            lambda: asyncio.create_task(_fire()),
        )
        self._coalesce_timers[thread_id] = handle

    async def route_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Route Ward Room events to relevant crew agents as intents.

        AD-407d: Supports both Captain->Agent and Agent->Agent routing
        with multi-layered loop prevention (depth cap, selective targeting,
        once-per-round, cooldown, [NO_RESPONSE]).
        """
        if not self._ward_room:
            return

        # BF-198: Periodic eviction of stale responded-thread records
        self._maybe_evict_stale_responses()

        # AD-416: Clean up tracking dicts when threads are pruned
        if event_type == "ward_room_pruned":
            pruned_ids = set(data.get("pruned_thread_ids", []))
            if pruned_ids:
                self.cleanup_tracking(pruned_ids)
            return

        # Only route new threads and new posts (not endorsements, mod actions)
        if event_type not in ("ward_room_thread_created", "ward_room_post_created"):
            return

        author_id = data.get("author_id", "")
        is_captain = (author_id == "captain")
        is_agent_post = not is_captain and author_id != ""

        thread_id = data.get("thread_id", "")

        # Captain posts reset the round counter (must happen before depth check)
        if is_captain and thread_id:
            self._thread_rounds[thread_id] = 0
            # Clear round participation tracking for this thread
            keys_to_clear = [k for k in self._round_participants
                             if k.startswith(f"{thread_id}:")]
            for k in keys_to_clear:
                del self._round_participants[k]

        # --- Get channel info ---
        channel_id = data.get("channel_id", "")
        thread_detail = None
        if event_type == "ward_room_post_created":
            # Posts don't include channel_id — look up the thread
            if thread_id:
                thread_detail = await self._ward_room.get_thread(thread_id)
                if thread_detail and "thread" in thread_detail:
                    channel_id = thread_detail["thread"].get("channel_id", "")

        if not channel_id:
            return

        # AD-424: Determine thread mode
        thread_mode = data.get("thread_mode", "discuss")
        if thread_detail and "thread" in thread_detail:
            thread_mode = thread_detail["thread"].get("thread_mode", "discuss")

        # AD-424: INFORM threads — no agent notification at all
        if thread_mode == "inform":
            return

        # Find the channel to determine routing scope
        channel = await self._ward_room.get_channel(channel_id)
        if not channel:
            return

        # --- Layer 1: Thread depth tracking ---
        # BF-156: DM channels bypass thread depth cap — private conversations
        # should not be artificially truncated.
        max_rounds = getattr(self._config.ward_room, 'max_agent_rounds', 3)
        if is_agent_post and thread_id and channel.channel_type != "dm":
            current_round = self._thread_rounds.get(thread_id, 0)
            if current_round >= max_rounds:
                logger.debug(
                    "Ward Room: thread %s hit agent round limit (%d), silencing",
                    thread_id[:8], max_rounds,
                )
                # BF-200: Notify thread that cap was hit
                await self._post_cap_notification(thread_id, "", "agent_round_limit")
                return

        # --- Layer 2: Selective targeting ---
        if is_captain:
            target_agent_ids = self.find_targets(
                channel=channel,
                author_id=author_id,
                mentions=data.get("mentions", []),
                thread_mode=thread_mode,
            )
        else:
            target_agent_ids = self.find_targets_for_agent(
                channel=channel,
                author_id=author_id,
                mentions=data.get("mentions", []),
            )

        if not target_agent_ids:
            return

        # AD-424: Apply responder cap for DISCUSS threads
        thread_max_responders = data.get("max_responders", 0)
        if thread_detail and "thread" in thread_detail:
            thread_max_responders = thread_detail["thread"].get("max_responders", 0)
        if thread_mode == "discuss" and thread_max_responders > 0:
            target_agent_ids = target_agent_ids[:thread_max_responders]

        # AD-623: DM convergence gate — thread-level check (before per-agent loop)
        if channel and channel.channel_type == "dm" and thread_id:
            try:
                convergence = await self._ward_room.check_dm_convergence(thread_id)
                if convergence and convergence.get("converged"):
                    logger.info(
                        "AD-623: DM thread %s converged (sim=%.3f, exchanges=%d)",
                        thread_id[:8],
                        convergence["similarity"],
                        convergence["exchange_count"],
                    )
                    self._event_emitter(
                        "dm_convergence_detected",
                        {
                            "thread_id": thread_id,
                            "channel_id": channel.id if channel else "",
                            "similarity": convergence["similarity"],
                            "exchange_count": convergence["exchange_count"],
                        },
                    )
                    # BF-200: Notify DM thread that convergence ended it
                    await self._post_cap_notification(thread_id, "", "dm_convergence")
                    return  # Thread is done — no more routing
            except Exception:
                logger.debug("AD-623: convergence gate check failed", exc_info=True)

        # --- Build thread context ---
        title = data.get("title", "")
        thread_context = ""
        if thread_id:
            if not thread_detail:
                thread_detail = await self._ward_room.get_thread(thread_id)
            if thread_detail:
                thread_obj = thread_detail.get("thread", {})
                posts = thread_detail.get("posts", [])
                title = title or (thread_obj.get("title", "") if isinstance(thread_obj, dict) else getattr(thread_obj, "title", ""))
                body = thread_obj.get("body", "") if isinstance(thread_obj, dict) else getattr(thread_obj, "body", "")
                thread_context = f"Thread: {title}\n{body}"
                # Include recent posts (last 5) for context
                recent_posts = posts[-5:] if len(posts) > 5 else posts
                for p in recent_posts:
                    p_id = p.get("id", "") if isinstance(p, dict) else getattr(p, "id", "")
                    p_callsign = p.get("author_callsign", "") if isinstance(p, dict) else getattr(p, "author_callsign", "")
                    p_body = p.get("body", "") if isinstance(p, dict) else getattr(p, "body", "")
                    # AD-629: Include post ID so agents can construct [ENDORSE post_id UP/DOWN]
                    _id_prefix = f"[{p_id[:8]}] " if p_id else ""
                    thread_context += f"\n{_id_prefix}{p_callsign}: {p_body}"

        # --- Send intents to target agents ---

        # Layer 4: Use longer cooldown for agent-triggered responses
        agent_cooldown = getattr(self._config.ward_room, 'agent_cooldown_seconds', 45)
        cooldown = agent_cooldown if is_agent_post else self._WARD_ROOM_COOLDOWN_SECONDS

        # Layer 3: Per-thread round participation
        current_round = self._thread_rounds.get(thread_id, 0)
        round_key = f"{thread_id}:{current_round}"
        round_participants = self._round_participants.setdefault(round_key, set())

        # BF-173: Enforce max_agent_rounds — stop notifying after N agent-only rounds
        max_rounds = getattr(self._config.ward_room, 'max_agent_rounds', 3)
        if is_agent_post and current_round >= max_rounds:
            logger.debug(
                "BF-173: Thread %s hit max agent rounds (%d/%d), suppressing notifications",
                thread_id[:8], current_round, max_rounds,
            )
            return

        # BF-188: Agent-reply routing waits for Captain delivery to complete
        if is_agent_post:
            try:
                await asyncio.wait_for(self._captain_delivery_done.wait(), timeout=120.0)
            except asyncio.TimeoutError:
                logger.warning("BF-188: Timed out waiting for Captain delivery, proceeding")

        # BF-157: Track which agents were explicitly @mentioned
        mentioned_agent_ids: set[str] = set()
        mentions = data.get("mentions", [])
        if mentions and self._callsign_registry:
            for callsign in mentions:
                resolved = self._callsign_registry.resolve(callsign)
                if resolved and resolved.get("agent_id"):
                    mentioned_agent_ids.add(resolved["agent_id"])

        # BF-188: Signal Captain delivery in progress
        if is_captain:
            self._captain_delivery_done.clear()

        try:
            await self._route_to_agents(
                target_agent_ids, is_captain, is_agent_post,
                mentioned_agent_ids, channel, thread_id, channel_id,
                event_type, title, author_id, data, thread_context,
                cooldown, current_round, round_participants,
            )
        finally:
            # BF-188: Signal Captain delivery complete (even on error)
            if is_captain:
                self._captain_delivery_done.set()

    async def _route_to_agents(
        self,
        target_agent_ids, is_captain, is_agent_post,
        mentioned_agent_ids, channel, thread_id, channel_id,
        event_type, title, author_id, data, thread_context,
        cooldown, current_round, round_participants,
    ):
        """Route intents to target agents — extracted for BF-188 try/finally.

        BF-193: Three-phase structure — pre-filter, dispatch, process.
        Captain messages dispatch concurrently; non-Captain sequential.
        """
        from probos.types import IntentMessage
        now = time.time()
        responded_this_event = False

        # ---------------------------------------------------------------
        # Phase 1: Pre-filter eligible agents and build intents
        # ---------------------------------------------------------------
        eligible: list[tuple[str, IntentMessage]] = []

        for agent_id in target_agent_ids:
            # BF-156/157: @mentioned agents and DM recipients bypass cooldown/caps.
            is_direct_target = (
                agent_id in mentioned_agent_ids
                or (channel and channel.channel_type == "dm")
            )

            # AD-614: DM thread exchange limit
            if channel and channel.channel_type == "dm":
                try:
                    dm_limit = getattr(
                        self._config.ward_room, 'dm_exchange_limit', 6
                    )
                    agent_post_count = await self._ward_room.count_posts_by_author(
                        thread_id, agent_id
                    )
                    if agent_post_count >= dm_limit:
                        logger.debug(
                            "AD-614: %s hit DM exchange limit (%d/%d) in thread %s",
                            agent_id[:12], agent_post_count, dm_limit, thread_id[:8],
                        )
                        # BF-200: Notify thread that cap was hit
                        await self._post_cap_notification(thread_id, agent_id, "dm_exchange_limit")
                        continue
                except Exception:
                    logger.debug("AD-614: exchange limit check failed", exc_info=True)

            # Layer 4: Per-agent cooldown
            if not is_direct_target:
                last_response = self._cooldowns.get(agent_id, 0)
                if now - last_response < cooldown:
                    continue

            # Layer 3: Agent already responded in this round of this thread
            if not is_direct_target and is_agent_post and agent_id in round_participants:
                continue

            # BF-016b: Per-thread agent response cap
            # AD-629: Unified reply cap
            # BF-194: Department gate only applies on department channels
            # BF-200: DM channels use dm_exchange_limit, not the per-thread reply cap
            if channel and channel.channel_type == "dm":
                pass  # Already guarded by AD-614 dm_exchange_limit above
            else:
                cap_result = self.check_and_increment_reply_cap(
                    thread_id, agent_id,
                    is_department_channel=(
                        channel is not None
                        and getattr(channel, 'channel_type', '') == "department"
                    ),
                )
                if cap_result == self.CAP_AGENT_LIMIT:
                    # BF-200: Notify thread that per-agent cap was hit
                    await self._post_cap_notification(thread_id, agent_id, "reply_cap")
                    continue
                elif cap_result == self.CAP_DEPT_GATE:
                    # Department first-responder filter — silent, not a cap
                    continue

            intent = IntentMessage(
                intent="ward_room_notification",
                params={
                    "event_type": event_type,
                    "thread_id": thread_id,
                    "channel_id": channel_id,
                    "channel_name": channel.name,
                    "title": title,
                    "author_id": author_id,
                    "author_callsign": data.get("author_callsign", ""),
                    "was_mentioned": agent_id in mentioned_agent_ids,
                    "is_dm_channel": getattr(channel, 'channel_type', '') == "dm",
                },
                context=thread_context,
                target_agent_id=agent_id,
                # BF-193: Captain messages get extended TTL to survive chain
                # slot contention when agents are busy with DM/proactive chains.
                ttl_seconds=120.0 if is_captain else 30.0,
            )
            eligible.append((agent_id, intent))

        if not eligible:
            return

        # ---------------------------------------------------------------
        # Phase 2: Dispatch — parallel for Captain, sequential otherwise
        # ---------------------------------------------------------------
        dispatch_results: list[tuple[str, object]] = []

        if is_captain:
            # BF-193: Parallel dispatch — all crew hear Captain simultaneously
            async def _dispatch_one(aid: str, intent: IntentMessage):
                try:
                    return aid, await self._intent_bus.send(intent)
                except Exception as e:
                    logger.warning("Ward Room agent notification failed for %s: %s", aid, e)
                    return aid, None

            dispatch_results = list(await asyncio.gather(
                *[_dispatch_one(aid, intent) for aid, intent in eligible],
            ))
        else:
            # Non-Captain: sequential (prevents thread explosion)
            for agent_id, intent in eligible:
                try:
                    result = await self._intent_bus.send(intent)
                    dispatch_results.append((agent_id, result))
                except Exception as e:
                    logger.warning("Ward Room agent notification failed for %s: %s", agent_id, e)
                    dispatch_results.append((agent_id, None))

        # ---------------------------------------------------------------
        # Phase 3: Sequential result processing
        # ---------------------------------------------------------------
        for agent_id, result in dispatch_results:
            if not result or not result.result:
                continue
            response_text = str(result.result).strip()
            # BF-199: Extract text from leaked chain JSON
            from probos.utils.text_sanitize import sanitize_ward_room_text
            response_text = sanitize_ward_room_text(response_text)
            if not response_text or response_text == "[NO_RESPONSE]":
                continue

            # Get agent's callsign for attribution
            agent = self._registry.get(agent_id)
            agent_callsign = ""
            if agent and self._callsign_registry:
                agent_callsign = self._callsign_registry.get_callsign(agent.agent_type)

            # BF-196: Unified action extraction — single pipeline shared with
            # proactive loop.  Handles endorsements, replies, DMs, notebooks,
            # rank gating, and markdown tag stripping in one place.  Replaces
            # piecemeal per-tag extraction that drifted out of sync (BF-195).
            if agent and self._proactive_loop:
                response_text, _actions = await self._proactive_loop._extract_and_execute_actions(
                    agent, response_text,
                )
                response_text = response_text.strip()
            else:
                # Fallback when proactive loop unavailable: endorsements only
                response_text, endorsements = self.extract_endorsements(response_text)
                if endorsements:
                    await self.process_endorsements(endorsements, agent_id=agent_id)

            # BF-197: Self-similarity guard — prevent near-duplicate posts
            # via the router path (mirrors BF-032 in proactive loop).
            if agent and self._proactive_loop:
                if await self._proactive_loop._is_similar_to_recent_posts(
                    agent, response_text,
                ):
                    logger.debug(
                        "BF-197: Suppressed similar router response from %s",
                        agent.agent_type,
                    )
                    continue

            # BF-123: Recreation commands (router-specific, not in proactive pipeline)
            if agent and self._proactive_loop:
                response_text = await self._extract_recreation_commands(
                    agent, response_text, agent_callsign,
                )
            if not response_text:
                continue
            # BF-174: Strip self-monitoring bracket markers
            from probos.proactive import _strip_bracket_markers
            response_text = _strip_bracket_markers(response_text)
            if not response_text:
                continue
            await self._ward_room.create_post(
                thread_id=thread_id,
                author_id=agent_id,
                body=response_text,
                parent_id=data.get("post_id") if event_type == "ward_room_post_created" else None,
                author_callsign=agent_callsign or (agent.agent_type if agent else "unknown"),
            )
            # BF-198: Record response so proactive loop doesn't double-post
            self.record_agent_response(agent_id, thread_id)
            # AD-625: Record communication exercise
            _rt = getattr(self._proactive_loop, '_runtime', None) if self._proactive_loop else None
            if _rt and hasattr(_rt, 'skill_service') and _rt.skill_service:
                try:
                    await _rt.skill_service.record_exercise(agent_id, "communication")
                except Exception:
                    logger.debug("Skill exercise recording failed for %s", agent_id, exc_info=True)
            self._cooldowns[agent_id] = time.time()
            round_participants.add(agent_id)
            responded_this_event = True

        # Increment round counter if any agent responded to an agent post
        if is_agent_post and responded_this_event:
            self._thread_rounds[thread_id] = current_round + 1

    async def _extract_recreation_commands(
        self,
        agent: Any,
        text: str,
        callsign: str,
    ) -> str:
        """BF-123: Extract CHALLENGE/MOVE tags from Ward Room response text.

        The Ward Room router response path only extracted endorsements and DMs.
        CHALLENGE/MOVE tags were posted as raw text because this path bypasses
        ``_extract_and_execute_actions()`` in proactive.py.
        """
        rt = getattr(self._proactive_loop, '_runtime', None) if self._proactive_loop else None
        if not rt:
            return text

        # BF-120: Strip markdown formatting that wraps structured tags
        text = re.sub(r'[`*]{1,3}\[', '[', text)
        text = re.sub(r'\][`*]{1,3}', ']', text)

        # --- Rank gate (same as proactive.py) ---
        from probos.crew_profile import Rank
        agent_trust = self._trust_network.get_score(agent.id) if self._trust_network else 0.5
        rank = Rank.from_trust(agent_trust)
        rec_min_rank_str = "ensign"
        if hasattr(self._config, 'communications'):
            rec_min_rank_str = self._config.communications.recreation_min_rank
        rec_min_rank = Rank[rec_min_rank_str.upper()] if rec_min_rank_str.upper() in Rank.__members__ else Rank.ENSIGN
        _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        if _RANK_ORDER.index(rank) < _RANK_ORDER.index(rec_min_rank):
            return text  # Below minimum rank — don't parse recreation commands

        rec_svc = getattr(rt, 'recreation_service', None)
        if not rec_svc:
            return text

        # --- CHALLENGE ---
        challenge_pattern = r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]'
        for match in re.finditer(challenge_pattern, text):
            target_callsign = match.group(1)
            game_type = match.group(2)
            try:
                target_agent = None
                if self._callsign_registry:
                    target_agent = self._callsign_registry.resolve(target_callsign)
                if not target_agent:
                    logger.debug("BF-123: Target callsign %s not found", target_callsign)
                    continue
                # Create Recreation channel thread
                rec_ch = None
                if self._ward_room:
                    rec_ch = await self._ward_room.get_channel_by_name("Recreation")
                thread_id = ""
                if rec_ch and self._ward_room:
                    thread = await self._ward_room.create_thread(
                        channel_id=rec_ch.id,
                        author_id=agent.id,
                        title=f"[Challenge] {callsign} challenges {target_callsign} to {game_type}!",
                        body=f"{callsign} has challenged {target_callsign} to a game of {game_type}! Reply to accept.",
                        author_callsign=callsign,
                    )
                    thread_id = thread.id if thread else ""
                game_info = await rec_svc.create_game(
                    game_type=game_type,
                    challenger=callsign,
                    opponent=target_callsign,
                    thread_id=thread_id,
                )
                logger.info("BF-123: %s challenged %s to %s (game %s)",
                            callsign, target_callsign, game_type, game_info["game_id"])
                # AD-573: Register game engagement in working memory
                try:
                    wm = getattr(agent, 'working_memory', None)
                    if wm:
                        from probos.cognitive.agent_working_memory import ActiveEngagement
                        wm.add_engagement(ActiveEngagement(
                            engagement_type="game",
                            engagement_id=game_info["game_id"],
                            summary=f"Playing {game_type} against {target_callsign}",
                            state={
                                "game_type": game_type,
                                "opponent": target_callsign,
                            },
                        ))
                except Exception:
                    logger.debug("BF-123: Working memory game engagement failed", exc_info=True)
            except Exception as e:
                logger.warning("BF-123: CHALLENGE failed for %s: %s", callsign, e)
        text = re.sub(challenge_pattern, '', text).strip()

        # --- MOVE ---
        move_pattern = r'\[MOVE\s+(\S+)\]'
        for match in re.finditer(move_pattern, text):
            position = match.group(1)
            try:
                player_game = rec_svc.get_game_by_player(callsign)
                if player_game and player_game.get("state", {}).get("current_player") == callsign:
                    game_info = await rec_svc.make_move(
                        game_id=player_game["game_id"],
                        player=callsign,
                        move=position,
                    )
                    # Post board update to Recreation channel
                    if self._ward_room and player_game.get("thread_id"):
                        board = rec_svc.render_board(player_game["game_id"]) if not game_info.get("result") else ""
                        result = game_info.get("result")
                        if result:
                            status = result.get("status", "")
                            winner = result.get("winner", "")
                            body = f"Game over! {'Winner: ' + winner if winner else 'Draw!'}"
                        else:
                            body = f"```\n{board}\n```\nNext: {game_info['state']['current_player']}"
                        try:
                            await self._ward_room.create_post(
                                thread_id=player_game["thread_id"],
                                author_id=agent.id,
                                body=body,
                                author_callsign=callsign,
                            )
                        except Exception:
                            logger.debug("BF-123: Board update post failed", exc_info=True)
                    # BF-125: Game-over WM cleanup handled by GAME_COMPLETED subscriber.
                else:
                    logger.debug("BF-123: No active game for %s", callsign)
            except Exception as e:
                logger.warning("BF-123: MOVE failed for %s: %s", callsign, e)
        text = re.sub(move_pattern, '', text).strip()

        return text

    def find_targets(
        self,
        channel: Any,
        author_id: str,
        mentions: list[str] | None = None,
        thread_mode: str = "discuss",
    ) -> list[str]:
        """Determine which crew agents should be notified about a Ward Room event."""
        target_ids: list[str] = []

        # 1. @mentioned agents always get notified
        if mentions:
            for callsign in mentions:
                resolved = self._callsign_registry.resolve(callsign)
                if resolved and resolved["agent_id"] and resolved["agent_id"] != author_id:
                    target_ids.append(resolved["agent_id"])

        # BF-016a: If Captain @mentions specific agents, only target those.
        if mentions and target_ids:
            return target_ids

        # 2. Route based on channel type (ambient — no @mentions)
        if channel.channel_type == "ship":
            # Ship-wide channel: notify all crew agents
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)):
                    # AD-357: Earned Agency trust-tier gating
                    effective_same_dept = (thread_mode == "discuss")
                    if self._config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self._trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=True,
                                                   same_department=effective_same_dept):
                            continue
                    target_ids.append(agent.id)

        elif channel.channel_type == "department" and channel.department:
            # AD-621: Department channel — notify all subscribed agents.
            # Subscription is the gate (set at startup by communication.py).
            # Home-department agents AND cross-department subscribers both receive.
            from probos.cognitive.standing_orders import get_department
            _subscribed_ids = self._get_channel_subscribers(channel.id)
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and agent.id in _subscribed_ids):
                    # AD-357: Earned Agency trust-tier gating
                    # Cross-department subscribers get same_department=False
                    # (higher response threshold — observe more, respond selectively).
                    _home_dept = ((self._ontology.get_agent_department(agent.agent_type) if self._ontology else None)
                                  or get_department(agent.agent_type))
                    _same_dept = (_home_dept == channel.department)
                    if self._config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self._trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=True,
                                                   same_department=_same_dept):
                            continue
                    target_ids.append(agent.id)

        elif channel.channel_type == "dm":
            # AD-574: DM channel — notify the other participant (no EA gating)
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and agent.id[:8] in channel.name):
                    target_ids.append(agent.id)

        return target_ids

    def find_targets_for_agent(
        self,
        channel: Any,
        author_id: str,
        mentions: list[str] | None = None,
    ) -> list[str]:
        """Determine targets for agent-authored posts (narrower than Captain posts).

        AD-407d: Agent posts only notify:
        1. @mentioned agents (always)
        2. DM channel: the other participant
        3. Department peers (if in a department channel)
        4. Never ship-wide broadcast for agent-to-agent
        """
        target_ids: list[str] = []

        # 1. @mentioned agents always get notified
        if mentions:
            for callsign in mentions:
                resolved = self._callsign_registry.resolve(callsign)
                if resolved and resolved["agent_id"] and resolved["agent_id"] != author_id:
                    target_ids.append(resolved["agent_id"])

        # 2. DM channel: notify the other participant
        if channel.channel_type == "dm":
            # Find the other agent in this DM channel by checking all agents
            for agent in self._registry.all():
                if (agent.id != author_id
                        and agent.is_alive
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)):
                    # Check if this agent's ID prefix appears in the DM channel name
                    if agent.id[:8] in channel.name:
                        if agent.id not in target_ids:
                            target_ids.append(agent.id)
                        break
            return target_ids

        # 3. Department channel: notify subscribed peers
        if channel.channel_type == "department" and channel.department:
            from probos.cognitive.standing_orders import get_department
            _subscribed_ids = self._get_channel_subscribers(channel.id)
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and agent.id in _subscribed_ids):
                    # AD-357: Earned Agency trust-tier gating
                    _home_dept = ((self._ontology.get_agent_department(agent.agent_type) if self._ontology else None)
                                  or get_department(agent.agent_type))
                    _same_dept = (_home_dept == channel.department)
                    if self._config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self._trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=False,
                                                   same_department=_same_dept):
                            continue
                    target_ids.append(agent.id)

        return target_ids

    async def handle_propose_improvement(
        self, intent: Any, agent: Any,
    ) -> dict[str, Any]:
        """AD-412: Handle a crew improvement proposal — post to #Improvement Proposals."""
        if not self._ward_room:
            return {"success": False, "error": "Ward Room not available"}

        params = intent.params if hasattr(intent, "params") else intent.get("params", {})
        title = params.get("title", "Untitled Proposal")
        rationale = params.get("rationale", "")
        affected_systems = params.get("affected_systems", [])
        priority = params.get("priority_suggestion", "medium")

        # Validate required fields
        if not rationale:
            return {"success": False, "error": "Proposal requires a rationale"}

        # Find #Improvement Proposals channel
        proposals_ch = await self._ward_room.get_channel_by_name("Improvement Proposals")

        if not proposals_ch:
            return {"success": False, "error": "Improvement Proposals channel not found"}

        # Get callsign for attribution
        callsign = ""
        if self._callsign_registry:
            callsign = self._callsign_registry.get_callsign(
                getattr(agent, "agent_type", "unknown")
            )

        # Format structured proposal body
        systems_str = ", ".join(affected_systems) if affected_systems else "Not specified"
        body = (
            f"**Proposed by:** {callsign or getattr(agent, 'agent_type', 'unknown')}\n"
            f"**Priority:** {priority}\n"
            f"**Affected Systems:** {systems_str}\n\n"
            f"**Rationale:**\n{rationale}"
        )

        # Create thread in proposals channel (DISCUSS mode)
        thread = await self._ward_room.create_thread(
            channel_id=proposals_ch.id,
            author_id=agent.id if hasattr(agent, "id") else "unknown",
            title=f"[Proposal] {title}",
            body=body,
            author_callsign=callsign,
            thread_mode="discuss",
        )

        return {
            "success": True,
            "thread_id": thread.id,
            "channel": "Improvement Proposals",
            "title": title,
        }

    def extract_endorsements(self, text: str) -> tuple[str, list[dict[str, str]]]:
        """Extract [ENDORSE post_id UP/DOWN] blocks from agent response text.

        Returns (cleaned_text, endorsements_list).
        """
        endorsements: list[dict[str, str]] = []
        pattern = re.compile(r'\[ENDORSE\s+(\S+)\s+(UP|DOWN)\]', re.IGNORECASE)
        for match in pattern.finditer(text):
            endorsements.append({
                "post_id": match.group(1),
                "direction": match.group(2).lower(),
            })
        cleaned = pattern.sub('', text).strip()
        return cleaned, endorsements

    async def process_endorsements(
        self, endorsements: list[dict[str, str]], agent_id: str,
    ) -> None:
        """AD-426: Execute endorsement decisions and emit trust signals."""
        if not self._ward_room:
            return

        for e in endorsements:
            post_id = e["post_id"]
            direction = e["direction"]  # "up" or "down"
            try:
                result = await self._ward_room.endorse(
                    target_id=post_id,
                    target_type="post",
                    voter_id=agent_id,
                    direction=direction,
                )
                net_score = result.get("net_score", 0)

                # AD-426 Pillar 3: Bridge endorsement to trust signal
                post_detail = await self._ward_room.get_post(post_id)
                if post_detail and self._trust_network:
                    author_id = post_detail.get("author_id", "")
                    if author_id and author_id != "captain":
                        success = (direction == "up")
                        self._trust_network.record_outcome(
                            agent_id=author_id,
                            success=success,
                            weight=0.05,  # Light signal — social endorsement
                            intent_type="ward_room_endorsement",
                            verifier_id=agent_id,
                        )
                        logger.debug(
                            "AD-426: Trust signal for %s from endorsement by %s (%s, net=%d)",
                            author_id, agent_id, direction, net_score,
                        )
            except ValueError as exc:
                # Self-endorsement, post not found, etc.
                logger.debug("AD-426: Endorsement skipped for %s: %s", post_id, exc)
            except Exception:
                logger.debug("AD-426: Endorsement failed for %s", post_id, exc_info=True)

    async def deliver_bridge_alert(self, alert: Any) -> None:
        """Post a Bridge Alert to the Ward Room and optionally notify the Captain."""
        from probos.bridge_alerts import AlertSeverity

        if not self._ward_room:
            return

        # Determine target channel
        if alert.severity == AlertSeverity.INFO and alert.department:
            channel = await self._ward_room.get_channel_by_department(alert.department)
        else:
            channel = await self._ward_room.get_channel_by_type("ship")

        if not channel:
            logger.warning("Bridge alert: no suitable channel for %s", alert.alert_type)
            return

        # Post as Ship's Computer
        try:
            await self._ward_room.create_thread(
                channel_id=channel.id,
                author_id="captain",
                title=f"[{alert.severity.value.upper()}] {alert.title}",
                body=alert.detail,
                author_callsign="Ship's Computer",
                thread_mode="inform",
            )
        except Exception as e:
            logger.warning("Bridge alert WR post failed: %s", e)
            return

        # Captain notification for advisory/alert severity
        if alert.severity in (AlertSeverity.ADVISORY, AlertSeverity.ALERT):
            if self._notify_fn:
                notif_type = "action_required" if alert.severity == AlertSeverity.ALERT else "info"
                self._notify_fn(
                    agent_id=alert.related_agent_id or "system",
                    title=alert.title,
                    detail=alert.detail,
                    notification_type=notif_type,
                )

        await self._event_log.log(
            category="bridge_alert",
            event=alert.alert_type,
            detail=f"severity={alert.severity.value} {alert.title}",
        )

    def cleanup_tracking(self, pruned_thread_ids: set[str]) -> None:
        """Remove in-memory tracking entries for pruned threads (AD-416)."""
        for tid in pruned_thread_ids:
            self._thread_rounds.pop(tid, None)
            # AD-629: Clean up department tracking
            self._dept_thread_responses.pop(tid, None)
            keys_to_remove = [k for k in self._round_participants
                              if k.startswith(f"{tid}:")]
            for k in keys_to_remove:
                del self._round_participants[k]
            keys_to_remove = [k for k in self._agent_thread_responses
                              if k.startswith(f"{tid}:")]
            for k in keys_to_remove:
                del self._agent_thread_responses[k]
