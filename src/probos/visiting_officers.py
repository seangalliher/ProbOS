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
- **Capabilities are strings, not enums**: sessions, pairing rows and
  events carry them as strings. BF-903 (#1581) closes the set: a
  capability means something only where a checking path reads it, and
  that path is code, so a new capability lands in ``VISITOR_CAPABILITIES``
  with its check, in one change. Configuration and the Captain's
  ``--cap`` choose among the declared names; an undeclared one is refused
  by name, so a typo can neither grant nor deny in silence.
- **One guard** (BF-903): every path that acts for an actor id calls
  ``require_visitor_capability`` before acting. A crew member's slot id is
  never looked up; a visiting officer, named by its DID or its bare
  certificate UUID, must hold the capability in a live session, read at
  use. A path that already knows its sender is a visitor (a paired channel
  sender) calls ``require_session_capability``.
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
from typing import Any, Callable, Iterable

# BF-903 (#1581): the visiting-officer capability vocabulary. It is defined once, in
# ``probos.config_models.crew`` (Amendment A2): that module imports nothing from ``probos``, so the
# config default and validator read the names without an import, and this module re-exports them,
# as ``cognitive/dreaming.py`` imports AD-1326's bound from ``config_models/cognition.py``. The
# registry, the pairing defaults and every checking path import the names from here.
from probos.config_models.crew import (  # re-exported: the CAP_* names are imported from this module
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    VISITOR_CAPABILITIES,
    undeclared_capabilities,
)

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS: float = 3600.0
DEFAULT_SWEEP_INTERVAL_SECONDS: float = 60.0
VISITING_AGENT_TYPE: str = "visiting"

# BF-903: why a visiting officer was refused (AD-1316's stable-code syntax). The refusal event
# and ``VisitorScopeRefused.reason`` carry one of these.
REFUSED_NO_SESSION: str = "visitor_session_unknown"
REFUSED_EXPIRED: str = "visitor_session_expired"
REFUSED_CAPABILITY: str = "visitor_capability_missing"
REFUSED_REGISTRY_OFF: str = "visitor_registry_off"


class UnknownCapabilityError(ValueError):
    """BF-903: a capability name the vocabulary does not declare."""

    def __init__(self, unknown: Iterable[str]) -> None:
        self.unknown: tuple[str, ...] = tuple(unknown)
        super().__init__(
            f"undeclared visiting-officer capabilities {list(self.unknown)!r}; "
            f"declared: {sorted(VISITOR_CAPABILITIES)!r} (BF-903)"
        )


class VisitorScopeRefused(PermissionError):
    """BF-903: a visiting officer's request that its session does not allow.

    ``reason`` is one of the ``REFUSED_*`` codes. The API answers it with 403, as it answers
    BF-771's denial (``api.py``).
    """

    def __init__(self, did: str, capability: str, reason: str, surface: str) -> None:
        self.did = did
        self.capability = capability
        self.reason = reason
        self.surface = surface
        super().__init__(
            f"BF-903: visiting officer {did} may not use {capability!r} at {surface}: {reason}"
        )


def require_known_capabilities(capabilities: Iterable[str]) -> None:
    """BF-903: raise ``UnknownCapabilityError`` naming every capability the vocabulary lacks.

    A bare string is iterated as its characters and so refused, never read as one name.
    """
    unknown = undeclared_capabilities(capabilities)
    if unknown:
        raise UnknownCapabilityError(unknown)


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
      - capability_refusal(did, capability) -> str | None   (BF-903)
      - check(did, capability, *, surface) -> None   (BF-903; raises on refusal)
      - active() -> tuple[VisitingOfficerSession, ...]
      - async start() / async stop()

    BF-903: consumers call the module's ``require_visitor_capability``,
    which recognises a visiting officer and then calls ``check``. ``get``,
    ``capability_refusal`` and ``check`` read expiry at use, so an expired session is
    refused before the sweep removes it.
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
        require_known_capabilities(capabilities)  # BF-903 (#1581): refused before a certificate is issued
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
        session = self._sessions.get(did)
        if session is None or self._clock() >= session.expires_at:  # BF-903: an expired session is gone at use
            return None
        return session

    def capability_refusal(self, did: str, capability: str) -> str | None:  # BF-903 A5: AD-1343's census reads any call named "refusal" as a stop check
        """BF-903: why ``did`` may not use ``capability`` now, or None when it may.

        Read at each use: a deregistered session is refused at once and an expired one before
        the sweep removes it.
        """
        session = self._sessions.get(did)
        if session is None:
            return REFUSED_NO_SESSION
        if self._clock() >= session.expires_at:
            return REFUSED_EXPIRED
        if capability not in session.capabilities:
            return REFUSED_CAPABILITY
        return None

    def has_capability(self, did: str, capability: str) -> bool:
        return self.capability_refusal(did, capability) is None

    def check(self, did: str, capability: str, *, surface: str) -> None:
        """BF-903: return when ``did`` may use ``capability``; otherwise record the refusal and raise.

        The record is a ``VISITING_OFFICER_REFUSED`` event through this registry's emitter, the
        sink its registration and deregistration events use, and a warning.
        """
        reason = self.capability_refusal(did, capability)
        if reason is None:
            return
        self._emit("VISITING_OFFICER_REFUSED", {
            "did": did, "capability": capability, "reason": reason, "surface": surface,
        })
        logger.warning("BF-903: refused visiting officer %s %r at %s: %s", did, capability, surface, reason)
        raise VisitorScopeRefused(did, capability, reason, surface)

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


def visiting_certificate(identity_registry: Any, actor_id: object) -> Any:
    """BF-903: the birth certificate of the visiting officer ``actor_id`` names, or None.

    A sovereign identity takes two key shapes (BF-907's ``is_sovereign_identity_key``): a
    did:probos agent DID and its bare certificate UUID. Both name the visitor, because downstream
    stores key an identity by whichever id it acts as (an author's Ward Room episode is stored
    under the id it posts as). Only those two shapes are looked up, in the identity registry's
    in-memory certificate cache (``get_by_uuid``, which never raises); a slot id, a callsign,
    "captain", "system" or a 32-hex agent id matches neither and costs no lookup. A crew
    certificate's DID or UUID is looked up and is not a visitor. The certificate outlives its
    session, so an expired or deregistered visitor is still recognised and refused. BF-907's
    ``resolve_slot_id`` and AD-1346's ``IdentityService.resolve`` return None for a visitor, which
    holds no slot, so they cannot classify one; this reads the agent type AD-701 sets.
    """
    if type(actor_id) is not str or identity_registry is None:
        return None
    from probos.identity import is_sovereign_identity_key, parse_did  # BF-903: imported at use; at load this module reads only probos.config_models (A2)

    if not is_sovereign_identity_key(actor_id):
        return None
    agent_uuid = actor_id
    if actor_id.startswith("did:"):
        parsed = parse_did(actor_id)
        if parsed is None or parsed.get("type") != "agent":
            return None
        agent_uuid = parsed["agent_uuid"]
        if not is_sovereign_identity_key(agent_uuid):  # BF-903 (A3): a malformed agent part costs no lookup
            return None
    cert = identity_registry.get_by_uuid(agent_uuid)
    return cert if cert is not None and cert.agent_type == VISITING_AGENT_TYPE else None


def is_visiting_identity(identity_registry: Any, actor_id: object) -> bool:
    """BF-903: whether ``actor_id`` names a visiting officer, by its DID or its certificate UUID."""
    return visiting_certificate(identity_registry, actor_id) is not None


def require_session_capability(
    did: str,
    capability: str,
    *,
    surface: str,
    visiting_officers: VisitingOfficerRegistry | None,
) -> None:
    """BF-903 (#1581): a known visiting officer's DID must hold ``capability`` in a live session.

    For a caller that already knows its sender is a visitor (a paired channel sender, AD-802),
    and for ``require_visitor_capability`` once it has recognised one. With AD-701's registry off
    no session exists, so the visitor is refused. An undeclared ``capability`` raises
    ``UnknownCapabilityError``.
    """
    require_known_capabilities((capability,))  # BF-903: a typo in a checking path fails on its first call
    if visiting_officers is None:
        logger.warning(
            "BF-903: refused visiting officer %s %r at %s: AD-701's registry is off, so no session exists",
            did, capability, surface,
        )
        raise VisitorScopeRefused(did, capability, REFUSED_REGISTRY_OFF, surface)
    visiting_officers.check(did, capability, surface=surface)


def require_visitor_capability(
    actor_id: str,
    capability: str,
    *,
    surface: str,
    identity_registry: Any,
    visiting_officers: VisitingOfficerRegistry | None,
) -> None:
    """BF-903 (#1581): the one check every path that acts for an actor id calls before it acts.

    A crew member's slot id, the Captain or the system passes without a lookup. A visiting
    officer, named by its DID or its certificate UUID, must hold ``capability`` in a live
    session, checked under its DID (the registry's key); with AD-701's registry off it holds
    none and is refused. ``surface`` names the entry in the refusal and its record. An
    undeclared ``capability`` raises ``UnknownCapabilityError`` whoever acts, so a typo in a
    checking path fails on its first call.
    """
    if capability not in VISITOR_CAPABILITIES:
        raise UnknownCapabilityError([capability])
    cert = visiting_certificate(identity_registry, actor_id)
    if cert is None:
        return
    require_session_capability(cert.did, capability, surface=surface, visiting_officers=visiting_officers)
