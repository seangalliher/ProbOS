# AD-701 v1 — Visiting Officers (formal external-participant Ward Room registration)

**Issue:** [#477](https://github.com/seangalliher/ProbOS/issues/477)
**Type:** Architecture Decision (substrate — external participant registration)
**Depends on:** AD-449 (MCPBridge — pattern for managing external connections); AgentIdentityRegistry (sovereign DID issuance); WardRoomService (post fabric).
**Wave:** 130

## Goal

Today, external AI tools (Claude Code, Copilot, etc.) can post into the Ward Room only by impersonating an `author_id` string — there is no formal substrate for binding an external participant to a sovereign identity, scoping their capabilities, or expiring their session. AD-449 stood up the **outbound** MCP bridge (probos calls external MCP tools); AD-701 stands up the **inbound** counterpart: a `VisitingOfficerRegistry` that mints a time-bounded, capability-scoped sovereign DID for each external participant and exposes a single registration / deregistration API the Ward Room (and any other substrate) can trust.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/identity.py:403` defines `class AgentIdentityRegistry`. `:707` exposes `async def issue_birth_certificate(agent_type, callsign, instance_id, vessel_name, department, post_id, baseline_version, slot_id="")` returning an `AgentBirthCertificate` (with `did`, `agent_uuid`, `certificate_hash`). The DID issuance machinery is fully present and reusable — `agent_type="visiting"` is a valid value (the field is a free-form `str`). No schema change required.
- ✅ `src/probos/ward_room/service.py:29` `class WardRoomService(EventEmitterMixin)`. Posts route through `_messages: MessageStore`. `WardRoomPost.author_id` (`src/probos/ward_room/models.py:46–58`) is a `str` — any DID is acceptable. No core fabric change needed; only attribution and capability gating.
- ✅ `src/probos/ward_room/models.py:62` `WardRoomEndorsement` and `:82` `WardRoomCredibility` exist; visiting-officer credibility tracking can reuse this.
- ✅ `src/probos/integrations/mcp_bridge/bridge.py:14` `class MCPBridge` is the pattern for "coordinator over external connections" — its `register_server / list_servers / close_all` shape is the template AD-701 mirrors (inverted: register **inbound** instead of outbound).
- ✅ `docs/development/roadmap.md:241` and `:312` already reserve AD-701 for "Visiting Officers — formal external-participant Ward Room registration" against issue #477.
- ✅ `src/probos/events.py:696,709,717,729,887` define the existing `WardRoom*` event family — no new events strictly required for v1.
- ⚠️ The dispatch suggested checking whether Ward Room "has a participant model that can be extended." It does not — `author_id` is a flat string. Visiting officers must therefore be a **registry-side** layer, not a Ward-Room-internal participant model. This prompt reflects that.

## Build Ordering Note

This prompt edits `src/probos/config.py` (D2). Four Wave 130 prompts touch that file; serialize commits in this order to avoid register-block collisions: **claude-bootstrap → AD-701 → AD-707 → Memvid-QP**. AD-701 is second; rebase on top of the claude-bootstrap commit before adding `VisitingOfficersConfig`.

## Builder pre-check (Recommended R2)

D3 reads `runtime.emit_event` and `runtime.identity_registry` directly. Before wiring, confirm both are public attributes on `ProbOSRuntime` (not `_emit_event_fn` callable / `_identity_registry`). The D2 callback signature `emit_event=Callable[[str, Any], None]` requires a real bound method matching that shape. If only the private name is exposed, add a one-line public alias on the runtime side rather than reaching into the underscore name.

## Scope

Ship the registry, the issuance flow that mints a DID under `agent_type="visiting"`, the capability scope object, the session-expiry tick, and the Ward Room post-attribution shim. Do **not** add inbound MCP transport, do **not** change `WardRoomService` API, do **not** introduce a new event tier — visiting officers piggyback on the existing `WardRoomPostCreatedEvent` with their visiting DID as `author_id`.

## Deliverables

### D1. New module `src/probos/visiting_officers.py`

```python
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
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS: float = 3600.0
DEFAULT_SWEEP_INTERVAL_SECONDS: float = 60.0
VISITING_AGENT_TYPE: str = "visiting"


@dataclass(frozen=True)
class VisitingOfficerSession:
    """Immutable record of an active visiting officer session."""

    did: str                          # AgentBirthCertificate.did
    callsign: str                     # human-readable, e.g. "claude-code-1"
    capabilities: frozenset[str]      # scoped capability strings
    registered_at: float
    expires_at: float
    origin: str = ""                  # caller-declared source ("claude-code", "copilot", ...)


class VisitingOfficerRegistry:
    """Manages active visiting-officer sessions.

    Public API:
      - async register(callsign, capabilities, *, origin="", session_ttl_seconds=None) -> VisitingOfficerSession
      - deregister(did) -> bool
      - get(did) -> VisitingOfficerSession | None
      - has_capability(did, capability) -> bool
      - active() -> tuple[VisitingOfficerSession, ...]
      - async start() / async stop()
    """

    def __init__(
        self,
        identity_registry: Any,                     # AgentIdentityRegistry
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
            "did": cert.did, "callsign": callsign, "origin": origin,
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
            "did": did, "callsign": session.callsign, "reason": "explicit",
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
                    "did": did, "callsign": session.callsign, "reason": "expired",
                })

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(event_name, payload)
        except Exception:
            logger.warning("AD-701: emit_event '%s' failed; continuing", event_name, exc_info=True)
```

### D2. Pydantic config

In `src/probos/config.py`, add a sibling to existing Ward-Room config sections:

```python
class VisitingOfficersConfig(BaseModel):
    """AD-701: Visiting officer registry tunables."""
    enabled: bool = False
    session_ttl_seconds: float = Field(default=3600.0, gt=0.0)
    sweep_interval_seconds: float = Field(default=60.0, gt=0.0)
    default_capabilities: list[str] = Field(
        default_factory=lambda: ["ward_room.post", "ward_room.read"]
    )
```

Wire into the top-level config model alongside other ward-room sections (verify-first: locate the existing `WardRoomConfig` registration site at `src/probos/config.py:1962` and add the new field beside it).

### D3. Runtime wiring (`src/probos/startup/finalize.py`)

After the existing identity-registry start and Ward-Room start, before MCPBridge wiring, add:

```python
# AD-701: Visiting Officer registry
vo_cfg = getattr(config, "visiting_officers", None)
if vo_cfg is not None and vo_cfg.enabled:
    from probos.visiting_officers import VisitingOfficerRegistry
    runtime.visiting_officers = VisitingOfficerRegistry(
        identity_registry=runtime.identity_registry,
        instance_id=runtime.instance_id,
        vessel_name=runtime.vessel_name,
        baseline_version=runtime.baseline_version,
        emit_event=runtime.emit_event,
        session_ttl_seconds=vo_cfg.session_ttl_seconds,
        sweep_interval_seconds=vo_cfg.sweep_interval_seconds,
    )
    await runtime.visiting_officers.start()
```

In `src/probos/startup/shutdown.py`, mirror with `await runtime.visiting_officers.stop()` if present.

### D4. Ward Room post attribution

No code change to `WardRoomService` itself. The visiting-officer DID is already a valid `author_id`. Document in the docstring of `VisitingOfficerRegistry.register` that consumers SHOULD call `has_capability(did, "ward_room.post")` before relaying a post.

### D5. Tests — `tests/test_ad701_visiting_officers.py`

Required (≥ 8):

1. `test_register_issues_did_via_identity_registry` — patch `AgentIdentityRegistry.issue_birth_certificate` to return a stub cert, assert it was called with `agent_type="visiting"`, `department="visiting"`, the supplied callsign and instance_id.
2. `test_register_records_session_with_capabilities` — register, then `get(did)` returns a session with the requested cap set frozen.
3. `test_register_emits_event` — emit_event mock called with `"VISITING_OFFICER_REGISTERED"` and the right payload keys.
4. `test_register_rejects_empty_callsign_or_caps` — `ValueError` for both.
5. `test_deregister_removes_session_and_emits` — explicit deregister returns True, second call returns False, emit fired with reason=`"explicit"`.
6. `test_has_capability_enforces_scope_and_expiry` — fake clock advanced past `expires_at` returns False even if cap is in the set.
7. `test_sweep_loop_deregisters_expired` — fake clock + manual `_sweep_once()` call; assert expired session removed and emit fired with reason=`"expired"`.
8. `test_active_excludes_expired` — `active()` filters by clock.
9. (recommended) `test_start_stop_idempotent` — two starts followed by two stops do not raise.

## Hard constraints (do NOT do)

- Do **not** add a new `events.py` enum value — reuse string event names through the existing `emit_event` callback (matches the `MCPBridge` pattern at `bridge.py:30`).
- Do **not** mutate `WardRoomService` to add a "visiting" code path — the registry is the enforcement seam; the service remains generic.
- Do **not** persist sessions to SQLite in v1 — schedule a follow-up `AD-701b-1` if needed.
- Do **not** introduce a new `agent_tier` enum value — `agent_type="visiting"` on the existing certificate suffices.
- Do **not** add inbound MCP transport logic. AD-449 owns transport; AD-701 owns identity + scope.
- Do **not** default `enabled=True` (Wave 10 standing convention #14: transitional flags default False).

## Acceptance criteria

- **Pre-flight (Wave 129 convention #20):** run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP and surface to the Architect before reading source.
- All new code passes lint with full type annotations on public methods.
- 8+ tests pass.
- Existing test suite passes unchanged (no regressions).
- Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad701_visiting_officers.py -v -n 0`
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **AD-701b**: SQLite persistence for visiting-officer sessions (survive restart with bounded TTL recompute).
- **AD-701c**: HXI surface — list active visiting officers in the Ward Room sidebar.
- **AD-701d**: Inbound MCP transport that registers itself as a visiting officer and relays Ward Room posts on its server's behalf.

## Revision (2026-05-08)

- Added Build Ordering Note (config.py serialization: claude-bootstrap → AD-701 → AD-707 → Memvid-QP).
- Added Builder pre-check section for `runtime.emit_event` / `runtime.identity_registry` public-attribute confirmation (Recommended R2).
- Added pre-flight working-tree integrity reminder to Acceptance (cross-cutting convention #20).
