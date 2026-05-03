# AD-641d: Crew Deliberation Protocol — Structured Discussion (v1)

**Status:** Ready for builder
**Wave:** 9C (high-risk — Captain workflow surface; distinct from QuorumEngine but adjacent to consensus semantics)
**Dependencies:** Reads `WardRoomService.create_thread` at `src/probos/ward_room/service.py:357` (verified). Reads `WardRoomService.create_post` at `src/probos/ward_room/service.py:400` (verified). Captain identity uses callsign-based path identical to BF-257 (Wave 8 convention; AD-499 ShipNamingPolicy canonical "Captain"). Distinct from `QuorumEngine` at `src/probos/consensus/quorum.py:21` (verified) — Crew Deliberation is judgment-level (should we), QuorumEngine is mechanical safety (does this look correct).
**Estimated tests:** ~15
**Risk:** HIGH — Captain-facing protocol. Convention #14: aggressive pre-deferral applied; v1 ships only the lifecycle skeleton, not deliberation analytics.

---

## Problem

The mesh `QuorumEngine` (`src/probos/consensus/quorum.py:21`) handles **mechanical** collective safety: confidence-weighted voting among tool agents for destructive operations. Strategic decisions ("should we onboard this new vendor?", "do we adopt the proposed reorg?") need a different protocol — **judgment-level deliberation** with structured argument turns and a Captain-resolved outcome.

`grep -rn "class DeliberationSession\|class CrewDeliberation\|deliberation_session" src/probos/` returns no matches.

The roadmap entry (line 7056) names AD-641d as "Crew Deliberation Protocol — Structured crew discussion for strategic decisions (not mechanical consensus). Captain or Chief initiates deliberation thread, crew contribute arguments, endorsements signal agreement, Captain resolves. Ward Room native, not consensus layer."

## Solution Overview

One new module under `src/probos/cognitive/deliberation/` (new package; AD-641d OWNS `__init__.py` creation):

1. **`DeliberationSession`** (frozen dataclass) — `id`, `topic`, `initiator_id`, `participants`, `phase`, `started_at`, `ended_at`, `thread_id`, `outcome`, `arguments_for`, `arguments_against`. Phases: `OPEN -> ARGUE -> ENDORSE -> RESOLVED`. Phases are advanced explicitly; no auto-progression.
2. **`DeliberationProtocol`** (`protocol.py`) — coordinator. Public API: `initiate(topic, initiator_id, initiator_callsign, participants) -> DeliberationSession`, `submit_argument(session_id, agent_id, agent_callsign, stance, body) -> bool`, `endorse(session_id, agent_id, target_argument_id) -> bool`, `resolve(session_id, captain_id, outcome, rationale) -> DeliberationSession`. Captain-only `resolve` (verified by callsign check; same v1 convention as BF-257). Creates a Ward Room thread for the deliberation; arguments and endorsements are posts under that thread.

This is **judgment-level**, not mechanical. AD-641d does NOT modify `QuorumEngine`, does NOT modify `TrustNetwork`, does NOT bypass Ward Room storage.

**v1 scope (no-theater discipline; convention #7 + #14 — 4 of 8 capabilities ship):**

- **Real lifecycle (`initiate`/`submit_argument`/`endorse`/`resolve`)** with real Ward Room thread + posts.
- **Captain-only resolve** (callsign check identical to BF-257 — v1 acceptable).
- **`DeliberationOutcome` enum** with `ADOPTED`, `REJECTED`, `DEFERRED` values.
- **Real session-state in-memory map**; persistence via Ward Room thread (the deliberation thread is the durable record).

**4 wholesale-deferred to grandchild ADs:**

- **Multi-Captain quorum (e.g., quorum of senior officers)** — `AD-641d-i`. Single-Captain resolve in v1.
- **Counselor mediation hook** — `AD-641d-ii`. v1 has no automatic Counselor injection on heated arguments; that needs the AD-561 surface and a separate analyzer.
- **Structured argument schema (claim / evidence / counter)** — `AD-641d-iii`. v1 stores argument body as free-form text.
- **Hebbian-feedback into routing (top contributors influence future deliberation invitations)** — `AD-641d-iv`. Depends on AD-641b.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
DELIBERATION_INITIATED = "deliberation_initiated"  # AD-641d
DELIBERATION_ARGUMENT_SUBMITTED = "deliberation_argument_submitted"  # AD-641d
DELIBERATION_RESOLVED = "deliberation_resolved"  # AD-641d
```

Verified absent: `grep -n "DELIBERATION_INITIATED\|DELIBERATION_ARGUMENT_SUBMITTED\|DELIBERATION_RESOLVED" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/deliberation/__init__.py` (new — AD-641d OWNS directory creation)

```python
"""AD-641d: Crew Deliberation Protocol -- structured judgment-level discussion."""

from probos.cognitive.deliberation.protocol import (
    DeliberationOutcome,
    DeliberationPhase,
    DeliberationProtocol,
    DeliberationSession,
)

__all__ = [
    "DeliberationOutcome",
    "DeliberationPhase",
    "DeliberationProtocol",
    "DeliberationSession",
]
```

---

## Section 2: `DeliberationProtocol` and dataclasses

**File:** `src/probos/cognitive/deliberation/protocol.py` (new)

```python
"""AD-641d: Crew Deliberation Protocol.

Judgment-level decision making, distinct from QuorumEngine's mechanical consensus.
Captain initiates or approves; crew contribute arguments; Captain resolves with
outcome ADOPTED/REJECTED/DEFERRED. Ward Room thread is the durable record.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class DeliberationPhase(str, Enum):
    OPEN = "open"
    ARGUE = "argue"
    ENDORSE = "endorse"
    RESOLVED = "resolved"


class DeliberationOutcome(str, Enum):
    PENDING = "pending"
    ADOPTED = "adopted"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class DeliberationArgument:
    id: str
    agent_id: str
    agent_callsign: str
    stance: str  # "for" | "against" | "neutral"
    body: str
    submitted_at: float


@dataclass(frozen=True)
class DeliberationSession:
    id: str
    topic: str
    initiator_id: str
    initiator_callsign: str
    participants: list[str]
    phase: DeliberationPhase
    started_at: float
    ended_at: float = 0.0
    thread_id: str = ""
    outcome: DeliberationOutcome = DeliberationOutcome.PENDING
    rationale: str = ""
    arguments: list[DeliberationArgument] = field(default_factory=list)


class DeliberationProtocol:
    """Coordinator for structured crew deliberation.

    Public API:
      - initiate(topic, initiator_id, initiator_callsign, participants) -> DeliberationSession
      - submit_argument(session_id, agent_id, agent_callsign, stance, body) -> bool
      - endorse(session_id, agent_id, target_argument_id) -> bool
      - resolve(session_id, captain_id, captain_callsign, outcome, rationale) -> DeliberationSession | None
      - get_session(session_id) -> DeliberationSession | None
    """

    def __init__(
        self,
        *,
        ward_room: Any | None,
        emit_event: Any | None = None,
        captain_callsign: str = "Captain",
    ) -> None:
        self._ward_room = ward_room
        self._emit_event = emit_event
        self._captain_callsign = (captain_callsign or "Captain").strip().lower()
        self._sessions: dict[str, DeliberationSession] = {}

    async def initiate(
        self,
        *,
        topic: str,
        initiator_id: str,
        initiator_callsign: str,
        participants: list[str] | None = None,
        channel_id: str = "deliberation",
    ) -> DeliberationSession:
        sid = uuid.uuid4().hex[:12]
        thread_id = ""
        if self._ward_room is not None:
            try:
                thread = await self._ward_room.create_thread(
                    channel_id=channel_id,
                    author_id=initiator_id,
                    title=f"Deliberation: {topic}",
                    body=f"[Deliberation OPEN] Topic: {topic}",
                    author_callsign=initiator_callsign or "",
                    thread_mode="discuss",
                )
                thread_id = str(getattr(thread, "id", "") or "")
            except Exception:
                thread_id = ""
        session = DeliberationSession(
            id=sid,
            topic=str(topic),
            initiator_id=str(initiator_id),
            initiator_callsign=str(initiator_callsign or ""),
            participants=[str(p) for p in (participants or []) if p],
            phase=DeliberationPhase.ARGUE,
            started_at=time.time(),
            thread_id=thread_id,
        )
        self._sessions[sid] = session
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.DELIBERATION_INITIATED,
                    {
                        "session_id": sid,
                        "topic": session.topic,
                        "initiator_id": session.initiator_id,
                        "thread_id": session.thread_id,
                    },
                )
            except Exception:
                pass
        return session

    async def submit_argument(
        self,
        *,
        session_id: str,
        agent_id: str,
        agent_callsign: str,
        stance: str,
        body: str,
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None or session.phase == DeliberationPhase.RESOLVED:
            return False
        if stance not in ("for", "against", "neutral"):
            return False
        arg = DeliberationArgument(
            id=uuid.uuid4().hex[:8],
            agent_id=str(agent_id),
            agent_callsign=str(agent_callsign or ""),
            stance=stance,
            body=str(body or ""),
            submitted_at=time.time(),
        )
        new_args = list(session.arguments) + [arg]
        self._sessions[session_id] = replace(session, arguments=new_args)
        if self._ward_room is not None and session.thread_id:
            try:
                await self._ward_room.create_post(
                    thread_id=session.thread_id,
                    author_id=str(agent_id),
                    author_callsign=str(agent_callsign or ""),
                    body=f"[{stance.upper()}] {body}",
                )
            except Exception:
                pass
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.DELIBERATION_ARGUMENT_SUBMITTED,
                    {
                        "session_id": session_id,
                        "argument_id": arg.id,
                        "agent_id": arg.agent_id,
                        "stance": arg.stance,
                    },
                )
            except Exception:
                pass
        return True

    async def endorse(
        self,
        *,
        session_id: str,
        agent_id: str,
        target_argument_id: str,
    ) -> bool:
        # v1: endorsement is delegated to existing Ward Room endorsement
        # surface (thread-level). DeliberationProtocol records the argument
        # post; consumers endorse it via WardRoomService.endorse().
        session = self._sessions.get(session_id)
        if session is None or session.phase == DeliberationPhase.RESOLVED:
            return False
        for arg in session.arguments:
            if arg.id == target_argument_id:
                return True
        return False

    async def resolve(
        self,
        *,
        session_id: str,
        captain_id: str,
        captain_callsign: str,
        outcome: DeliberationOutcome,
        rationale: str = "",
    ) -> DeliberationSession | None:
        if (captain_callsign or "").strip().lower() != self._captain_callsign:
            return None
        session = self._sessions.get(session_id)
        if session is None or session.phase == DeliberationPhase.RESOLVED:
            return session
        if outcome == DeliberationOutcome.PENDING:
            return None
        resolved = replace(
            session,
            phase=DeliberationPhase.RESOLVED,
            outcome=outcome,
            rationale=str(rationale or ""),
            ended_at=time.time(),
        )
        self._sessions[session_id] = resolved
        if self._ward_room is not None and session.thread_id:
            try:
                await self._ward_room.create_post(
                    thread_id=session.thread_id,
                    author_id=str(captain_id),
                    author_callsign=str(captain_callsign or "Captain"),
                    body=f"[RESOLVED: {outcome.value.upper()}] {rationale}",
                )
            except Exception:
                pass
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.DELIBERATION_RESOLVED,
                    {
                        "session_id": session_id,
                        "outcome": outcome.value,
                        "captain_id": str(captain_id),
                    },
                )
            except Exception:
                pass
        return resolved

    def get_session(self, session_id: str) -> DeliberationSession | None:
        return self._sessions.get(session_id)
```

---

## Section 3: Configuration

**File:** `src/probos/config.py`

Add Pydantic model after the most recent addition:

```python
class DeliberationConfig(BaseModel):
    """AD-641d: Crew Deliberation Protocol configuration."""

    enabled: bool = True
    captain_callsign: str = "Captain"
    default_channel_id: str = "deliberation"
```

Add `deliberation: DeliberationConfig = Field(default_factory=DeliberationConfig)` to `SystemConfig`.

Verified absent: `grep -n "DeliberationConfig\|deliberation:" src/probos/config.py` returns no matches.

---

## Section 4: Startup wiring

**File:** `src/probos/startup/finalize.py`

Append after the most recent finalize wiring block:

```python
# AD-641d: Crew Deliberation Protocol
delib_cfg = getattr(getattr(runtime, "config", None), "deliberation", None)
if delib_cfg is not None and delib_cfg.enabled:
    runtime.deliberation_protocol = DeliberationProtocol(
        ward_room=getattr(runtime, "ward_room", None),
        emit_event=runtime.emit_event,
        captain_callsign=delib_cfg.captain_callsign,
    )
else:
    runtime.deliberation_protocol = None
```

---

## Section 5: Tests

**File:** `tests/test_ad641d_deliberation.py` (new)

Cover (~15 tests):

1. `test_event_type_deliberation_initiated_exists`
2. `test_event_type_deliberation_argument_submitted_exists`
3. `test_event_type_deliberation_resolved_exists`
4. `test_deliberation_config_defaults`
5. `test_deliberation_session_is_frozen_dataclass`
6. `test_deliberation_argument_is_frozen_dataclass`
7. `test_initiate_creates_session_in_argue_phase` — Ward Room `AsyncMock`; confirm `create_thread` awaited.
8. `test_initiate_emits_event`
9. `test_submit_argument_appends_and_emits` — confirm posted to thread.
10. `test_submit_argument_rejects_after_resolved`
11. `test_submit_argument_rejects_invalid_stance`
12. `test_resolve_only_captain_callsign_accepts` — non-Captain returns None; session unchanged.
13. `test_resolve_idempotent_after_first_call` — second `resolve` returns session unchanged.
14. `test_resolve_emits_event_with_outcome`
15. `test_endorse_returns_true_for_known_argument_false_for_unknown`

Per convention #18, all `WardRoomService` mocks must be `AsyncMock(spec=WardRoomService)` — `create_thread` and `create_post` are async (BF-250 lesson).

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **`QuorumEngine`** — not touched. Mechanical consensus is its own surface.
2. **`TrustNetwork`** — endorsements still flow through existing trust API; deliberation outcomes do NOT directly modify trust in v1.
3. **`WardRoomService`** — used as a consumer; storage and lifecycle unchanged.
4. **Multi-Captain quorum** — wholesale-deferred to AD-641d-i.
5. **Counselor mediation** — wholesale-deferred to AD-641d-ii.
6. **Structured argument schema** — wholesale-deferred to AD-641d-iii.

---

## Engineering Principles Compliance

- **Single Responsibility:** Protocol owns lifecycle. Session/Argument/Outcome are value-classes.
- **Open/Closed:** Adding a new outcome (e.g., `ESCALATED`) is an enum addition; existing flow unchanged.
- **Dependency Inversion:** `ward_room` and `emit_event` are constructor parameters.
- **Law of Demeter:** No reach into Ward Room internals; calls public `create_thread` / `create_post`.
- **Fail Fast / Log-and-Degrade:** Ward Room calls are exception-tolerant — if posting fails, in-memory session-state still updates (the durable Ward Room record is best-effort in v1; a future grandchild AD can add atomic guarantees if needed).

---

## Verification

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad641d_deliberation.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_quorum.py tests/test_consensus.py tests/test_ward_room.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracking

1. **PROGRESS.md** — Prepend AD-641d CLOSED entry with v1 scope summary + 4 deferred grandchildren.
2. **DECISIONS.md** — Add an entry: rationale for separation between `QuorumEngine` (mechanical) and `DeliberationProtocol` (judgment); v1 single-Captain resolve; deferred grandchildren.
3. **docs/development/roadmap.md** — Update line 7056 reflecting AD-641d CLOSED.

---

## Acceptance Criteria

- 15/15 focused tests pass at `-n 0`.
- Full parallel gate non-decreasing.
- `runtime.deliberation_protocol` is a public attribute (or `None` when disabled).
- 3 new EventTypes are members of `EventType`.
- `DeliberationSession` and `DeliberationArgument` are frozen.
- Captain-only resolve enforced (non-Captain `resolve()` returns `None`).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "class QuorumEngine" src/probos/consensus/quorum.py
  src/probos/consensus/quorum.py:21: class QuorumEngine:

grep -n "class WardRoomService\|async def create_thread\|async def create_post" src/probos/ward_room/service.py
  src/probos/ward_room/service.py:29: class WardRoomService(EventEmitterMixin):
  src/probos/ward_room/service.py:357: async def create_thread(
  src/probos/ward_room/service.py:400: async def create_post(

grep -n "class DeliberationSession\|class CrewDeliberation\|deliberation_session" src/probos/
  (no matches; new module)

grep -n "DELIBERATION_INITIATED\|DELIBERATION_ARGUMENT_SUBMITTED\|DELIBERATION_RESOLVED" src/probos/events.py
  (no matches; introduced by this prompt)

grep -n "AD-499\|ShipNamingPolicy\|callsign.*captain" src/probos/
  Multiple sites; "Captain" canonical per AD-499 + BF-244 callsign sync. v1 callsign-based check
  identical to BF-257 pattern (DM rate limiter Captain exemption).
```
