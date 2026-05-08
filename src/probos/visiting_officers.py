"""AD-701: Visiting Officer registry — formal external-participant registration.

External AI tools (Claude Code, Copilot, etc.) participate in the Ward Room
through a sovereign DID issued under the visiting tier. Each session is:

  * **Bound** to an AgentBirthCertificate (agent_type='visiting') so every
    post carries first-class identity provenance.
  * **Scoped** to a fixed set of capability strings — the registry is the
    enforcement seam; consumers (ward_room.service, future routers) check
    ``has_capability(did, cap)`` before honoring a request.
  * **Time-bounded**: session_ttl_seconds defaults to 3600. The registry
    runs a 60-second sweep that deregisters expired sessions and emits
    a deregistration event.

Design decisions
----------------
- **Capabilities are strings, not enums** (Open/Closed): new caps land
  via configuration, not code edits.
- **Registry storage is in-memory** for v1. Persistence is a follow-up
  AD-701b once the cap surface stabilizes.
- **DID issuance delegates to AgentIdentityRegistry** — we never invent
  a parallel identity chain.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS: float = 3600.0
DEFAULT_SWEEP_INTERVAL_SECONDS: float = 60.0
VISITING_AGENT_TYPE: str = "visiting"


@dataclass(frozen=True)
class VisitingOfficerSession:
    """Immutable record of an active visiting officer session."""

    did: str
    callsign: str
    capabilities: frozenset[str]
    registered_at: float
    expires_at: float
    origin: str = ""


class VisitingOfficerRegistry:
    """Manages active visiting-officer sessions.

    Public API:
      - async register(callsign, capabilities, *, origin="", session_ttl_seconds=None) -> VisitingOfficerSession
      - deregister(did) -> bool
      - get(did) -> VisitingOfficerSession | None
      - has_capability(did, capability) -> bool
      - active() -> tuple[VisitingOfficerSession, ...]
      - async start() / async stop()

    Consumers SHOULD call ``has_capability(did, "ward_room.post")`` before
    relaying a Ward Room post on behalf of a visiting officer (D4).
    """

    def __init__(
        self,
        identity_registry: Any,
        *,
        instance_id: str,
        vessel_name: str,
        baseline_version: str,
        emit_event: Callable[[str, Any], None] | None = None,
        session_ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        sweep_interval_seconds: float = DEFAULT_SWEEP_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._identity = identity_registry
        self._instance_id = instance_id
        self._vessel_name = vessel_name
        self._baseline_version = baseline_version
        self._emit_event = emit_event
        self._session_ttl = session_ttl_seconds
        self._sweep_interval = sweep_interval_seconds
        self._clock = clock
        self._sessions: dict[str, VisitingOfficerSession] = {}
        self._sweep_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._sweep_task is None or self._sweep_task.done():
            self._sweep_task = asyncio.create_task(self._sweep_loop(), name="ad701-sweep")

    async def stop(self) -> None:
        task = self._sweep_task
        self._sweep_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def register(
        self,
        callsign: str,
        capabilities: list[str] | tuple[str, ...] | frozenset[str],
        *,
        origin: str = "",
        session_ttl_seconds: float | None = None,
    ) -> VisitingOfficerSession:
        if not callsign:
            raise ValueError("callsign required")
        if not capabilities:
            raise ValueError("at least one capability required")
        ttl = session_ttl_seconds if session_ttl_seconds is not None else self._session_ttl
        if ttl <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        cert = await self._identity.issue_birth_certificate(
            agent_type=VISITING_AGENT_TYPE,
            callsign=callsign,
            instance_id=self._instance_id,
            vessel_name=self._vessel_name,
            department="visiting",
            post_id="",
            baseline_version=self._baseline_version,
        )
        now = self._clock()
        session = VisitingOfficerSession(
            did=cert.did,
            callsign=callsign,
            capabilities=frozenset(capabilities),
            registered_at=now,
            expires_at=now + ttl,
            origin=origin,
        )
        async with self._lock:
            self._sessions[cert.did] = session
        self._emit("VISITING_OFFICER_REGISTERED", {
            "did": cert.did,
            "callsign": callsign,
            "origin": origin,
            "capabilities": sorted(session.capabilities),
            "expires_at": session.expires_at,
        })
        logger.info("AD-701: registered visiting officer %s (%s)", callsign, cert.did)
        return session

    def deregister(self, did: str) -> bool:
        session = self._sessions.pop(did, None)
        if session is None:
            return False
        self._emit("VISITING_OFFICER_DEREGISTERED", {
            "did": did,
            "callsign": session.callsign,
            "reason": "explicit",
        })
        logger.info("AD-701: deregistered visiting officer %s", did)
        return True

    def get(self, did: str) -> VisitingOfficerSession | None:
        return self._sessions.get(did)

    def has_capability(self, did: str, capability: str) -> bool:
        session = self._sessions.get(did)
        if session is None:
            return False
        if self._clock() >= session.expires_at:
            return False
        return capability in session.capabilities

    def active(self) -> tuple[VisitingOfficerSession, ...]:
        now = self._clock()
        return tuple(s for s in self._sessions.values() if s.expires_at > now)

    async def _sweep_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._sweep_interval)
                await self._sweep_once()
        except asyncio.CancelledError:
            return

    async def _sweep_once(self) -> None:
        now = self._clock()
        async with self._lock:
            expired = [did for did, s in self._sessions.items() if s.expires_at <= now]
            for did in expired:
                session = self._sessions.pop(did)
                self._emit("VISITING_OFFICER_DEREGISTERED", {
                    "did": did,
                    "callsign": session.callsign,
                    "reason": "expired",
                })

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(event_name, payload)
        except Exception:
            logger.warning(
                "AD-701: emit_event '%s' failed; continuing", event_name, exc_info=True
            )
