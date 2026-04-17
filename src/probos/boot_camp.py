"""AD-638: Cold-Start Boot Camp Protocol.

Manages structured onboarding for fresh crew after system reset.
Accelerates trust-building and social connection through guided exercises.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, Callable

from probos.config import BootCampConfig
from probos.events import EventType

logger = logging.getLogger(__name__)


class TrustServiceProtocol(Protocol):
    """Narrow interface for trust lookups."""

    def get_trust_score(self, agent_id: str) -> float: ...


class WardRoomProtocol(Protocol):
    """Narrow interface for Ward Room operations."""

    async def get_or_create_dm_channel(
        self, agent_a_id: str, agent_b_id: str,
        callsign_a: str, callsign_b: str,
    ) -> Any: ...

    async def create_thread(
        self, channel_id: str, author_id: str, title: str, body: str,
        author_callsign: str, thread_mode: str, max_responders: int,
    ) -> Any: ...

    async def create_post(
        self, thread_id: str, author_id: str, body: str,
        parent_id: str | None, author_callsign: str,
    ) -> Any: ...

    async def list_channels(self) -> list: ...


class EpisodicMemoryProtocol(Protocol):
    """Narrow interface for episode count."""

    async def count_for_agent(self, agent_id: str) -> int: ...


@dataclass
class AgentBootCampState:
    """Per-agent boot camp tracking."""

    agent_id: str
    callsign: str
    department: str
    enrolled_at: float = field(default_factory=time.time)
    phase: int = 1  # 1=orientation, 2=introductions, 3=observation, 4=graduated
    introduced_to_chief: bool = False
    cross_dept_contact: bool = False
    shared_observation: bool = False
    notebook_started: bool = False
    ward_room_posts: int = 0
    dm_conversations: int = 0
    graduated: bool = False
    graduated_at: float | None = None


# Department chief mapping — same callsigns used in standing_orders.py
_DEPARTMENT_CHIEFS: dict[str, str] = {
    "medical": "Bones",
    "engineering": "LaForge",
    "science": "Number One",
    "security": "Worf",
    "operations": "O'Brien",
    "communications": "Uhura",
}


class BootCampCoordinator:
    """Manages cold-start boot camp lifecycle.

    Responsibilities:
    - Detect cold-start and enroll crew agents
    - Drive structured introduction exercises via Counselor
    - Relax quality gates during boot camp (context flag)
    - Track graduation criteria per agent
    - Transition agents to active duty

    Does NOT own: trust scoring, onboarding wiring, quality gate logic,
    Ward Room infrastructure, or Counselor agent behavior.
    """

    def __init__(
        self,
        config: BootCampConfig,
        ward_room: WardRoomProtocol,
        trust_service: TrustServiceProtocol,
        episodic_memory: EpisodicMemoryProtocol,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._ward_room = ward_room
        self._trust = trust_service
        self._episodic = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._agents: dict[str, AgentBootCampState] = {}
        self._active = False
        self._started_at: float | None = None
        self._nudge_cooldowns: dict[str, float] = {}
        self._observation_thread_id: str | None = None

    @property
    def is_active(self) -> bool:
        """True while boot camp is in progress."""
        return self._active

    def is_enrolled(self, agent_id: str) -> bool:
        """Check if agent is in boot camp (not yet graduated)."""
        state = self._agents.get(agent_id)
        return state is not None and not state.graduated

    def get_state(self, agent_id: str) -> AgentBootCampState | None:
        """Get boot camp state for an agent."""
        return self._agents.get(agent_id)

    # --- Public API ---

    async def activate(self, crew_agents: list[dict[str, str]]) -> None:
        """Start boot camp for all crew agents.

        Args:
            crew_agents: List of dicts with agent_id, callsign, department.
        """
        if not self._config.enabled:
            logger.info("AD-638: Boot camp disabled by config")
            return
        if self._active:
            logger.warning("AD-638: Boot camp already active, ignoring duplicate activation")
            return

        self._active = True
        self._started_at = time.time()

        for agent_info in crew_agents:
            agent_id = agent_info["agent_id"]
            callsign = agent_info.get("callsign", "")

            # AD-640: Skip agents already above graduation trust threshold
            # (Bridge/Chief agents initialized with high trust priors)
            current_trust = self._trust.get_trust_score(agent_id)
            if current_trust >= self._config.min_trust_score:
                logger.info(
                    "AD-640: %s trust=%.2f — skips boot camp (above graduation threshold)",
                    callsign, current_trust,
                )
                continue

            self._agents[agent_id] = AgentBootCampState(
                agent_id=agent_id,
                callsign=callsign,
                department=agent_info.get("department", ""),
            )

        logger.info(
            "AD-638: Boot camp activated for %d crew agents",
            len(crew_agents),
        )
        self._emit(EventType.BOOT_CAMP_ACTIVATED, {
            "agent_count": len(crew_agents),
            "timestamp": self._started_at,
        })

    async def check_graduation(self, agent_id: str) -> bool:
        """Check if agent meets graduation criteria."""
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return True

        # Time gate
        elapsed_min = (time.time() - state.enrolled_at) / 60
        if elapsed_min < self._config.min_time_minutes:
            return False

        # Episode count
        try:
            episode_count = await self._episodic.count_for_agent(agent_id)
        except Exception:
            logger.debug("AD-638: Episode count failed for %s, treating as 0", agent_id)
            episode_count = 0
        if episode_count < self._config.min_episodes:
            return False

        # Ward Room posts
        if state.ward_room_posts < self._config.min_ward_room_posts:
            return False

        # DM conversations
        if state.dm_conversations < self._config.min_dm_conversations:
            return False

        # Trust score
        try:
            trust = self._trust.get_trust_score(agent_id)
        except Exception:
            logger.debug("AD-638: Trust lookup failed for %s, treating as 0.5", agent_id)
            trust = 0.5
        if trust < self._config.min_trust_score:
            return False

        # All criteria met — graduate
        await self._graduate_agent(state, episode_count, trust)
        return True

    async def run_phase_2_introductions(
        self, counselor_id: str, counselor_callsign: str,
    ) -> None:
        """Counselor-driven introduction exercises."""
        # Group agents by department for cross-department pairing
        by_dept: dict[str, list[AgentBootCampState]] = {}
        for state in self._agents.values():
            if state.graduated:
                continue
            by_dept.setdefault(state.department, []).append(state)

        dept_names = list(by_dept.keys())

        for state in self._agents.values():
            if state.graduated or state.phase >= 2:
                continue

            # Cooldown check
            if not self._can_nudge(state.agent_id):
                continue

            # Exercise 1: Introduce to department chief
            chief_callsign = _DEPARTMENT_CHIEFS.get(state.department, "")
            if chief_callsign and not state.introduced_to_chief:
                try:
                    dm_channel = await self._ward_room.get_or_create_dm_channel(
                        counselor_id, state.agent_id,
                        counselor_callsign, state.callsign,
                    )
                    thread = await self._ward_room.create_thread(
                        channel_id=dm_channel.id,
                        author_id=counselor_id,
                        title=f"Welcome aboard, {state.callsign}",
                        body=(
                            f"You should introduce yourself to {chief_callsign}, "
                            f"your department chief. Send them a DM about your role "
                            f"and what you bring to the department."
                        ),
                        author_callsign=counselor_callsign,
                        thread_mode="discuss",
                        max_responders=0,
                    )
                    self._record_nudge(state.agent_id)
                    logger.debug(
                        "AD-638: Phase 2 chief intro nudge sent to %s",
                        state.callsign,
                    )
                except Exception:
                    logger.debug(
                        "AD-638: Failed to send chief intro nudge to %s",
                        state.callsign, exc_info=True,
                    )

            # Exercise 2: Cross-department contact
            if not state.cross_dept_contact and len(dept_names) > 1:
                # Pick a peer from a different department
                other_depts = [d for d in dept_names if d != state.department]
                if other_depts:
                    target_dept = other_depts[0]
                    peers = by_dept.get(target_dept, [])
                    if peers:
                        peer = peers[0]
                        if self._can_nudge(state.agent_id):
                            try:
                                dm_channel = await self._ward_room.get_or_create_dm_channel(
                                    counselor_id, state.agent_id,
                                    counselor_callsign, state.callsign,
                                )
                                await self._ward_room.create_thread(
                                    channel_id=dm_channel.id,
                                    author_id=counselor_id,
                                    title="Cross-department introduction",
                                    body=(
                                        f"Reach out to {peer.callsign} in {target_dept}. "
                                        f"Building cross-department relationships "
                                        f"strengthens the whole crew."
                                    ),
                                    author_callsign=counselor_callsign,
                                    thread_mode="discuss",
                                    max_responders=0,
                                )
                                self._record_nudge(state.agent_id)
                            except Exception:
                                logger.debug(
                                    "AD-638: Failed to send cross-dept nudge to %s",
                                    state.callsign, exc_info=True,
                                )

            # Advance to phase 2
            if state.phase < 2:
                old_phase = state.phase
                state.phase = 2
                self._emit(EventType.BOOT_CAMP_PHASE_ADVANCE, {
                    "agent_id": state.agent_id,
                    "callsign": state.callsign,
                    "from_phase": old_phase,
                    "to_phase": 2,
                })

    async def run_phase_3_observation(
        self, counselor_id: str, counselor_callsign: str,
    ) -> None:
        """Shared observation thread + notebook prompts."""
        # Create observation thread on All Hands if not already created
        if not self._observation_thread_id:
            try:
                channels = await self._ward_room.list_channels()
                all_hands = next(
                    (c for c in channels if getattr(c, 'channel_type', '') == "ship"),
                    None,
                )
                if all_hands:
                    thread = await self._ward_room.create_thread(
                        channel_id=all_hands.id,
                        author_id=counselor_id,
                        title="Boot Camp — Initial Observations",
                        body=(
                            "What have you noticed about the ship's current state? "
                            "Share your professional observations."
                        ),
                        author_callsign=counselor_callsign,
                        thread_mode="discuss",
                        max_responders=0,
                    )
                    self._observation_thread_id = thread.id
            except Exception:
                logger.debug(
                    "AD-638: Failed to create observation thread",
                    exc_info=True,
                )

        # Send notebook prompts to each agent
        for state in self._agents.values():
            if state.graduated or state.phase >= 3:
                continue

            if not self._can_nudge(state.agent_id):
                continue

            try:
                dm_channel = await self._ward_room.get_or_create_dm_channel(
                    counselor_id, state.agent_id,
                    counselor_callsign, state.callsign,
                )
                await self._ward_room.create_thread(
                    channel_id=dm_channel.id,
                    author_id=counselor_id,
                    title="Initial assessment",
                    body=(
                        "Start a notebook entry about your initial assessment "
                        "of your department's baseline."
                    ),
                    author_callsign=counselor_callsign,
                    thread_mode="discuss",
                    max_responders=0,
                )
                self._record_nudge(state.agent_id)
            except Exception:
                logger.debug(
                    "AD-638: Failed to send notebook nudge to %s",
                    state.callsign, exc_info=True,
                )

            # Advance to phase 3
            if state.phase < 3:
                old_phase = state.phase
                state.phase = 3
                self._emit(EventType.BOOT_CAMP_PHASE_ADVANCE, {
                    "agent_id": state.agent_id,
                    "callsign": state.callsign,
                    "from_phase": old_phase,
                    "to_phase": 3,
                })

    async def force_graduate_all(self) -> None:
        """Force-graduate all remaining agents (timeout)."""
        remaining = [
            s for s in self._agents.values() if not s.graduated
        ]
        if not remaining:
            return

        agent_ids = []
        for state in remaining:
            state.graduated = True
            state.graduated_at = time.time()
            state.phase = 4
            agent_ids.append(state.agent_id)

        elapsed_min = 0.0
        if self._started_at:
            elapsed_min = (time.time() - self._started_at) / 60

        self._active = False
        logger.info(
            "AD-638: Boot camp timed out — force-graduated %d agents after %.0f minutes",
            len(agent_ids), elapsed_min,
        )
        self._emit(EventType.BOOT_CAMP_TIMEOUT, {
            "agent_ids": agent_ids,
            "duration_minutes": round(elapsed_min, 1),
        })

    async def on_agent_post(self, agent_id: str, channel_type: str) -> None:
        """Track agent activity for graduation criteria."""
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return
        state.ward_room_posts += 1

        if channel_type == "ship" and self._observation_thread_id:
            state.shared_observation = True

        # Check graduation after each tracked activity
        await self.check_graduation(agent_id)

    async def on_agent_dm(self, agent_id: str) -> None:
        """Track DM activity for graduation criteria."""
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return
        state.dm_conversations += 1
        await self.check_graduation(agent_id)

    async def check_timeout(self) -> None:
        """Check if boot camp has exceeded its timeout."""
        if not self._active or not self._started_at:
            return
        elapsed_seconds = time.time() - self._started_at
        if elapsed_seconds >= self._config.timeout_minutes * 60:
            await self.force_graduate_all()

    # --- Private helpers ---

    async def _graduate_agent(
        self, state: AgentBootCampState,
        episode_count: int, trust_score: float,
    ) -> None:
        """Mark agent as graduated and emit event."""
        state.graduated = True
        state.graduated_at = time.time()
        state.phase = 4

        elapsed_min = (state.graduated_at - state.enrolled_at) / 60
        logger.info(
            "AD-638: %s graduated boot camp (episodes=%d, posts=%d, trust=%.2f, %.0f min)",
            state.callsign, episode_count, state.ward_room_posts,
            trust_score, elapsed_min,
        )
        self._emit(EventType.BOOT_CAMP_GRADUATION, {
            "agent_id": state.agent_id,
            "callsign": state.callsign,
            "episodes": episode_count,
            "posts": state.ward_room_posts,
            "trust_score": trust_score,
            "duration_minutes": round(elapsed_min, 1),
        })

        # Check if all agents graduated — deactivate boot camp
        if all(s.graduated for s in self._agents.values()):
            self._active = False
            logger.info("AD-638: All agents graduated — boot camp complete")

    def _can_nudge(self, agent_id: str) -> bool:
        """Check nudge cooldown for an agent."""
        last = self._nudge_cooldowns.get(agent_id, 0.0)
        return (time.time() - last) >= self._config.nudge_cooldown_seconds

    def _record_nudge(self, agent_id: str) -> None:
        """Record nudge timestamp."""
        self._nudge_cooldowns[agent_id] = time.time()

    def _emit(self, event_type: EventType, data: dict) -> None:
        """Emit event via the injectable event function."""
        if self._emit_event_fn:
            try:
                self._emit_event_fn(event_type, data)
            except Exception:
                logger.debug("AD-638: Event emission failed for %s", event_type, exc_info=True)
