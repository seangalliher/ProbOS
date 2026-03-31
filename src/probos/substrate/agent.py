"""Base agent class — the fundamental unit of ProbOS."""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from probos.types import AgentID, AgentMeta, AgentState, CapabilityDescriptor, IntentDescriptor
from probos.config import format_trust

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all ProbOS agents.

    Every agent follows the perceive -> decide -> act -> report lifecycle.
    Subclasses must implement these four methods.
    """

    agent_type: str = "base"
    tier: str = "domain"  # "core", "utility", or "domain"
    instructions: str | None = None  # Optional LLM instructions; CognitiveAgent requires them
    default_capabilities: list[CapabilityDescriptor] = []
    intent_descriptors: list[IntentDescriptor] = []
    initial_confidence: float = 0.8
    callsign: str = ""

    def __init__(self, pool: str = "default", **kwargs: Any) -> None:
        self.id: AgentID = kwargs.pop("agent_id", None) or uuid.uuid4().hex
        self.pool = pool
        self.sovereign_id: str = ""   # AD-441: Permanent UUID, set by identity registry
        self.did: str = ""            # AD-441: W3C DID, set by identity registry
        self.confidence: float = self.initial_confidence
        from probos.config import TRUST_DEFAULT
        self.trust_score: float = TRUST_DEFAULT
        self.capabilities: list[CapabilityDescriptor] = list(self.default_capabilities)
        self.connections: dict[AgentID, float] = {}
        self.state = AgentState.SPAWNING
        self.meta = AgentMeta()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._runtime: Any = kwargs.get("runtime")

    # ------------------------------------------------------------------
    # Lifecycle contract — subclasses implement these
    # ------------------------------------------------------------------

    @abstractmethod
    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Receive and interpret an intent from the mesh."""

    @abstractmethod
    async def decide(self, observation: Any) -> Any:
        """Determine action based on observation. May decline."""

    @abstractmethod
    async def act(self, plan: Any) -> Any:
        """Execute the planned action."""

    @abstractmethod
    async def report(self, result: Any) -> dict[str, Any]:
        """Package result for broadcast to the mesh."""

    # ------------------------------------------------------------------
    # Async start / stop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the agent. Transitions from SPAWNING to ACTIVE."""
        self.state = AgentState.ACTIVE
        self.meta.spawn_time = datetime.now(timezone.utc)
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=f"agent-{self.id[:8]}")
        logger.info(
            "Agent started: type=%s id=%s pool=%s",
            self.agent_type,
            self.id[:8],
            self.pool,
        )

    async def stop(self) -> None:
        """Gracefully stop the agent."""
        self.state = AgentState.RECYCLING
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.debug("Agent stopped: type=%s id=%s", self.agent_type, self.id[:8])

    @property
    def is_alive(self) -> bool:
        return self.state in (AgentState.ACTIVE, AgentState.DEGRADED)

    # ------------------------------------------------------------------
    # Confidence tracking
    # ------------------------------------------------------------------

    def update_confidence(self, success: bool) -> None:
        """Bayesian-style confidence update after an operation."""
        self.meta.last_active = datetime.now(timezone.utc)
        if success:
            self.meta.success_count += 1
            # Move toward 1.0, slower as we approach it
            self.confidence += (1.0 - self.confidence) * 0.1
        else:
            self.meta.failure_count += 1
            # Move toward 0.0, slower as we approach it
            self.confidence -= self.confidence * 0.15

        # Clamp
        self.confidence = max(0.01, min(1.0, self.confidence))

        # If confidence drops too low, mark degraded
        from probos.config import TRUST_DEGRADED
        if self.confidence < TRUST_DEGRADED:
            if self.state != AgentState.DEGRADED:
                self.state = AgentState.DEGRADED
                logger.warning(
                    "Agent degraded: type=%s id=%s confidence=%.3f",
                    self.agent_type,
                    self.id[:8],
                    self.confidence,
                )
        # BF-023: Recovery path — if confidence climbs back above threshold,
        # restore to ACTIVE. Without this, degraded agents stay dead forever.
        elif self.state == AgentState.DEGRADED:
            self.state = AgentState.ACTIVE
            logger.info(
                "Agent recovered: type=%s id=%s confidence=%.3f",
                self.agent_type,
                self.id[:8],
                self.confidence,
            )

    # ------------------------------------------------------------------
    # Run loop — subclasses can override for custom behavior
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Default run loop. Waits for stop signal.

        Subclasses like HeartbeatAgent override this with periodic work.
        """
        await self._stop_event.wait()

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def info(self) -> dict[str, Any]:
        """Return a snapshot of this agent's state."""
        return {
            "id": self.id,
            "type": self.agent_type,
            "callsign": self.callsign,  # BF-013
            "pool": self.pool,
            "state": self.state.value,
            "confidence": format_trust(self.confidence),
            "trust_score": format_trust(self.trust_score),
            "capabilities": [c.can for c in self.capabilities],
            "operations": self.meta.total_operations,
            "success_rate": (
                format_trust(self.meta.success_count / self.meta.total_operations)
                if self.meta.total_operations > 0
                else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id={self.id[:8]} "
            f"state={self.state.value} confidence={self.confidence:.3f}>"
        )

    # ------------------------------------------------------------------
    # AD-514: Public API
    # ------------------------------------------------------------------

    def set_temporal_context(self, birth_time: float, system_start_time: float) -> None:
        """Set temporal awareness for AD-502 lifecycle context."""
        self._birth_timestamp = birth_time
        self._system_start_time = system_start_time

    @property
    def has_llm_client(self) -> bool:
        """Whether this agent has an LLM client configured."""
        return hasattr(self, '_llm_client') and self._llm_client is not None

    @property
    def llm_client(self):
        """The agent's LLM client, or None."""
        return getattr(self, '_llm_client', None)

    def _replace_id(self, new_id: str) -> None:
        """Replace agent ID during hot-swap. Internal use only."""
        self.id = new_id
