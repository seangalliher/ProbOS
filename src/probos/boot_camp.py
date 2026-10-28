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
    # 1=enrolled, 4=graduated. AD-1270 (#1324) deleted phases 2 and 3, which had no caller.
    phase: int = 1
    ward_room_posts: int = 0
    dm_conversations: int = 0
    graduated: bool = False
    graduated_at: float | None = None


class BootCampCoordinator:
    """Manages cold-start boot camp lifecycle.

    Responsibilities:
    - Enroll cold-start crew agents
    - Relax quality gates while enrolled, only when ``relax_quality_gates`` is on
    - Offer enrolled agents the AD-683 cold-start snapshot
    - Track graduation criteria per agent
    - Transition agents to active duty

    Does NOT own: trust scoring, onboarding wiring, quality gate logic,
    Ward Room infrastructure, or Counselor agent behavior. AD-1270 (#1324)
    deleted the uncalled Counselor-voiced introduction and observation phases.
    """

    def __init__(
        self,
        config: BootCampConfig,
        trust_service: TrustServiceProtocol,
        episodic_memory: EpisodicMemoryProtocol,
        emit_event_fn: Callable[..., Any] | None = None,
        *,
        ship_state_builder: Any | None = None,  # AD-683: ShipStateSnapshotBuilder | None
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        # AD-1270 (#1324): every time read goes through the clock, so tests need no wall time.
        self._clock = clock
        self._trust = trust_service
        self._episodic = episodic_memory
        self._emit_event_fn = emit_event_fn
        self._agents: dict[str, AgentBootCampState] = {}
        self._active = False
        self._started_at: float | None = None
        # AD-683: Cold-start ship state snapshot — populated at activate() end.
        self._ship_state_builder = ship_state_builder
        self.ship_state_snapshot: Any | None = None  # ShipStateSnapshot | None

    @property
    def is_active(self) -> bool:
        """True while boot camp is in progress."""
        self._expire_if_timed_out()  # AD-1270: is_active is False once the timeout passes
        return self._active

    def is_enrolled(self, agent_id: str) -> bool:
        """Check if agent is in boot camp (not yet graduated)."""
        self._expire_if_timed_out()  # AD-1270: nobody is enrolled past the timeout
        state = self._agents.get(agent_id)
        return state is not None and not state.graduated

    def relaxes_quality_gates(self, agent_id: str) -> bool:
        """AD-1270 (#1324): True only while enrolled AND ``relax_quality_gates`` is on.

        The chain reads this, not ``is_enrolled``. Off (the default), an enrolled
        agent's Evaluate, Reflect and AD-639 tuning run as for any other agent.
        """
        return self._config.relax_quality_gates and self.is_enrolled(agent_id)

    def get_state(self, agent_id: str) -> AgentBootCampState | None:
        """Get boot camp state for an agent."""
        return self._agents.get(agent_id)

    def bind_ship_state_builder(self, builder: Any) -> bool:
        """BF-261 / AD-1270 (#1324): late-bind the AD-683 builder unless one was injected.

        Finalization builds the builder after this coordinator (Phase 7) and binds it before
        ``activate``, which captures the snapshot once; a bind after activation captures
        nothing. True when bound.
        """
        if builder is None or self._ship_state_builder is not None:
            return False
        self._ship_state_builder = builder
        return True

    def orientation_snapshot_text(self, agent_id: str) -> str:
        """AD-683 / AD-1270 (#1324): the cold-start snapshot for an enrolled agent, else "".

        Keyed on enrolment, not on ``relax_quality_gates``: it is context, not a gate. It asks
        ``is_enrolled`` first, so it enforces the timeout like the other reads, with or without
        a snapshot. The text is the snapshot captured at ``activate``.
        """
        if not self.is_enrolled(agent_id) or self.ship_state_snapshot is None:
            return ""
        try:
            return self.ship_state_snapshot.render_text()
        except Exception:
            logger.debug("AD-683: ship_state_snapshot.render_text failed; no snapshot this turn", exc_info=True)
            return ""

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
        self._started_at = self._clock()

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
                enrolled_at=self._started_at,
            )

        logger.info(
            "AD-638: Boot camp activated for %d crew agents",
            len(crew_agents),
        )
        self._emit(EventType.BOOT_CAMP_ACTIVATED, {
            "agent_count": len(crew_agents),
            "timestamp": self._started_at,
        })

        # AD-683: Capture ship state snapshot for cold-start orientation.
        if self._ship_state_builder is not None:
            try:
                self.ship_state_snapshot = await self._ship_state_builder.build()
            except Exception:
                logger.warning(
                    "AD-683: ship_state_snapshot capture failed during activate; "
                    "cold-start agents will not see snapshot",
                    exc_info=True,
                )

    async def check_graduation(self, agent_id: str) -> bool:
        """Check if agent meets graduation criteria."""
        self._expire_if_timed_out()  # AD-1270: a timed-out agent is already graduated
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return True

        # Time gate
        elapsed_min = (self._clock() - state.enrolled_at) / 60
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

    async def force_graduate_all(self) -> None:
        """Force-graduate all remaining agents (timeout)."""
        self._graduate_remaining_on_timeout()

    def _graduate_remaining_on_timeout(self) -> None:
        """AD-1270 (#1324): end boot camp; mark each remaining agent graduated, once.

        Deletes nothing and touches no trust record, rank or memory.
        """
        self._active = False  # AD-1270: ends even when nobody is left to graduate
        remaining = [
            s for s in self._agents.values() if not s.graduated
        ]
        if not remaining:
            return

        now = self._clock()
        agent_ids = []
        for state in remaining:
            state.graduated = True
            state.graduated_at = now
            state.phase = 4
            agent_ids.append(state.agent_id)

        elapsed_min = 0.0
        if self._started_at:
            elapsed_min = (now - self._started_at) / 60
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
        self._expire_if_timed_out()  # AD-1270: no post is counted past the timeout
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return
        state.ward_room_posts += 1

        # Check graduation after each tracked activity
        await self.check_graduation(agent_id)

    async def on_agent_dm(self, agent_id: str) -> None:
        """Track DM activity for graduation criteria."""
        self._expire_if_timed_out()  # AD-1270: no DM is counted past the timeout
        state = self._agents.get(agent_id)
        if state is None or state.graduated:
            return
        state.dm_conversations += 1
        await self.check_graduation(agent_id)

    async def check_timeout(self) -> None:
        """Check if boot camp has exceeded its timeout."""
        self._expire_if_timed_out()

    def _expire_if_timed_out(self) -> None:
        """AD-1270 (#1324): enforce ``timeout_minutes`` by construction, with no task.

        ``is_active``, ``is_enrolled``, ``check_graduation``, ``on_agent_post``,
        ``on_agent_dm`` and ``check_timeout`` call this first; ``relaxes_quality_gates``
        reaches it through ``is_enrolled`` when ``relax_quality_gates`` is on, and
        ``orientation_snapshot_text`` (the AD-683 DM read) always does. ``get_state``
        returns the raw state and does not call it.
        """
        if not self._active or self._started_at is None:
            return
        if self._clock() - self._started_at >= self._config.timeout_minutes * 60:
            self._graduate_remaining_on_timeout()

    # --- Private helpers ---

    async def _graduate_agent(
        self, state: AgentBootCampState,
        episode_count: int, trust_score: float,
    ) -> None:
        """Mark agent as graduated and emit event."""
        state.graduated = True
        state.graduated_at = self._clock()
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

    def _emit(self, event_type: EventType, data: dict) -> None:
        """Emit event via the injectable event function."""
        if self._emit_event_fn:
            try:
                self._emit_event_fn(event_type, data)
            except Exception:
                logger.debug("AD-638: Event emission failed for %s", event_type, exc_info=True)
