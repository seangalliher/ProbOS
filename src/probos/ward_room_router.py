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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
                    p_callsign = p.get("author_callsign", "") if isinstance(p, dict) else getattr(p, "author_callsign", "")
                    p_body = p.get("body", "") if isinstance(p, dict) else getattr(p, "body", "")
                    thread_context += f"\n{p_callsign}: {p_body}"

        # --- Send intents to target agents ---
        from probos.types import IntentMessage
        now = time.time()

        # Layer 4: Use longer cooldown for agent-triggered responses
        agent_cooldown = getattr(self._config.ward_room, 'agent_cooldown_seconds', 45)
        cooldown = agent_cooldown if is_agent_post else self._WARD_ROOM_COOLDOWN_SECONDS

        # Layer 3: Per-thread round participation
        current_round = self._thread_rounds.get(thread_id, 0)
        round_key = f"{thread_id}:{current_round}"
        round_participants = self._round_participants.setdefault(round_key, set())

        responded_this_event = False

        # BF-157: Track which agents were explicitly @mentioned
        mentioned_agent_ids: set[str] = set()
        mentions = data.get("mentions", [])
        if mentions and self._callsign_registry:
            for callsign in mentions:
                resolved = self._callsign_registry.resolve(callsign)
                if resolved and resolved.get("agent_id"):
                    mentioned_agent_ids.add(resolved["agent_id"])

        for agent_id in target_agent_ids:
            # BF-156/157: @mentioned agents and DM recipients bypass cooldown/caps.
            # These guards prevent thread explosion in public channels, not
            # suppress direct communication.
            is_direct_target = (
                agent_id in mentioned_agent_ids
                or (channel and channel.channel_type == "dm")
            )

            # AD-614: DM thread exchange limit — prevent conversation loops.
            # Unlike other guards, this applies even for is_direct_target because
            # DMs bypass all existing caps. Without this, DM conversations are unbounded.
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

            # BF-016b: Per-thread agent response cap — prevent thread explosion
            if not is_direct_target:
                max_per_thread = getattr(self._config.ward_room, 'max_agent_responses_per_thread', 3)
                thread_agent_key = f"{thread_id}:{agent_id}"
                prior_responses = self._agent_thread_responses.get(thread_agent_key, 0)
                if prior_responses >= max_per_thread:
                    logger.debug(
                        "Ward Room: agent %s hit per-thread response cap (%d) in thread %s",
                        agent_id[:12], max_per_thread, thread_id[:8],
                    )
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
                    # BF-157: Tell the agent it was directly mentioned
                    "was_mentioned": agent_id in mentioned_agent_ids,
                },
                context=thread_context,
                target_agent_id=agent_id,
            )
            try:
                result = await self._intent_bus.send(intent)
                # Layer 5: [NO_RESPONSE] filtering
                if result and result.result:
                    response_text = str(result.result).strip()
                    # AD-426: Extract endorsements before filtering
                    response_text, endorsements = self.extract_endorsements(response_text)
                    if endorsements:
                        await self.process_endorsements(
                            endorsements, agent_id=agent_id
                        )
                    if response_text and response_text != "[NO_RESPONSE]":
                        # Get agent's callsign for attribution
                        agent = self._registry.get(agent_id)
                        agent_callsign = ""
                        if agent and self._callsign_registry:
                            agent_callsign = self._callsign_registry.get_callsign(agent.agent_type)
                        # BF-066: Extract [DM @callsign]...[/DM] blocks before posting
                        if agent and self._proactive_loop:
                            response_text, dm_actions = await self._proactive_loop._extract_and_execute_dms(
                                agent, response_text,
                            )
                            response_text = response_text.strip()
                        # BF-123: Extract CHALLENGE/MOVE from Ward Room responses.
                        # Ward Room router only extracted endorsements + DMs — recreation
                        # commands were silently ignored because this path bypasses
                        # _extract_and_execute_actions() in proactive.py.
                        if agent and self._proactive_loop:
                            response_text = await self._extract_recreation_commands(
                                agent, response_text, agent_callsign,
                            )
                        if not response_text:
                            continue  # entire response was DM blocks, nothing to post publicly
                        await self._ward_room.create_post(
                            thread_id=thread_id,
                            author_id=agent_id,
                            body=response_text,
                            # BF-015: reply to the specific post, not just the thread
                            parent_id=data.get("post_id") if event_type == "ward_room_post_created" else None,
                            author_callsign=agent_callsign or (agent.agent_type if agent else "unknown"),
                        )
                        self._cooldowns[agent_id] = time.time()
                        round_participants.add(agent_id)
                        responded_this_event = True
                        # BF-016b: Increment per-thread response count
                        if not is_direct_target:
                            self._agent_thread_responses[thread_agent_key] = prior_responses + 1
            except Exception as e:
                logger.warning("Ward Room agent notification failed for %s: %s", agent_id, e)

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
            # Department channel: notify agents in that department
            from probos.cognitive.standing_orders import get_department
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and ((self._ontology.get_agent_department(agent.agent_type) if self._ontology else None) or get_department(agent.agent_type)) == channel.department):
                    # AD-357: Earned Agency trust-tier gating
                    if self._config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self._trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=True,
                                                   same_department=True):
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

        # 3. Department channel: notify department peers
        if channel.channel_type == "department" and channel.department:
            from probos.cognitive.standing_orders import get_department
            for agent in self._registry.all():
                if (agent.is_alive
                        and agent.id != author_id
                        and agent.id not in target_ids
                        and hasattr(agent, 'handle_intent')
                        and is_crew_agent(agent, self._ontology)
                        and ((self._ontology.get_agent_department(agent.agent_type) if self._ontology else None) or get_department(agent.agent_type)) == channel.department):
                    # AD-357: Earned Agency trust-tier gating
                    if self._config.earned_agency.enabled:
                        from probos.earned_agency import can_respond_ambient
                        from probos.crew_profile import Rank
                        _agent_rank = Rank.from_trust(self._trust_network.get_score(agent.id))
                        if not can_respond_ambient(_agent_rank, is_captain_post=False,
                                                   same_department=True):
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
            keys_to_remove = [k for k in self._round_participants
                              if k.startswith(f"{tid}:")]
            for k in keys_to_remove:
                del self._round_participants[k]
            keys_to_remove = [k for k in self._agent_thread_responses
                              if k.startswith(f"{tid}:")]
            for k in keys_to_remove:
                del self._agent_thread_responses[k]
