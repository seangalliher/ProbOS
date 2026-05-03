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

1. **`DeliberationSession`** (frozen dataclass) — `id`, `topic`, `initiator_id`, `participants`, `phase`, `started_at`, `ended_at`, `thread_id`, `outcome`, `arguments`. Phases: `ARGUE -> RESOLVED` only in v1 (the two reachable states; `OPEN`/`ENDORSE` deferred along with their progression triggers).
2. **`DeliberationProtocol`** (`protocol.py`) — coordinator. Public API: `initiate(topic, initiator_id, initiator_callsign, participants) -> DeliberationSession`, `submit_argument(session_id, agent_id, agent_callsign, stance, body) -> bool`, `resolve(session_id, captain_id, captain_callsign, outcome, rationale) -> DeliberationSession | None`. Captain-only `resolve` (verified by callsign check; same v1 convention as BF-257). Creates a Ward Room thread for the deliberation; arguments are posts under that thread.

This is **judgment-level**, not mechanical. AD-641d does NOT modify `QuorumEngine`, does NOT modify `TrustNetwork`, does NOT bypass Ward Room storage.

**v1 scope (no-theater discipline; convention #7 + #14 — 3 of 8 capabilities ship):**

- **Real lifecycle (`initiate`/`submit_argument`/`resolve`)** with real Ward Room thread + posts.
- **Captain-only resolve** (callsign check identical to BF-257 — v1 acceptable).
- **`DeliberationOutcome` enum** with `ADOPTED`, `REJECTED`, `DEFERRED` values; in-memory session map; Ward Room thread is the durable record.

**5 wholesale-deferred to grandchild ADs:**

- **Multi-Captain quorum (e.g., quorum of senior officers)** — `AD-641d-i`. Single-Captain resolve in v1.
- **Counselor mediation hook** — `AD-641d-ii`. v1 has no automatic Counselor injection on heated arguments; that needs the AD-561 surface and a separate analyzer.
- **Structured argument schema (claim / evidence / counter)** — `AD-641d-iii`. v1 stores argument body as free-form text.
- **Hebbian-feedback into routing (top contributors influence future deliberation invitations)** — `AD-641d-iv`. Depends on AD-641b.
- **Endorsement bridge to `WardRoomService.endorse`** — `AD-641d-v`. v1 ships no `endorse()` method; deliberation arguments are recorded as posts but no endorsement plumbing wires through the Ward Room endorsement surface yet. Requires capturing the `WardRoomPost.id` returned from `create_post` and calling `await self._ward_room.endorse(target_id=post_id, target_type="post", voter_id=agent_id, direction="up")` (verified signature at [src/probos/ward_room/service.py:412](src/probos/ward_room/service.py#L412)).

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
    # v1 reachable phases only. OPEN/ENDORSE phases are deferred to grandchild
    # ADs along with the explicit transitions that would set them.
    ARGUE = "argue"
    RESOLVED = "resolved"


class DeliberationOutcome(str, Enum):
    # PENDING is the initial sentinel value before resolve(); it is NOT a
    # valid resolve() outcome. resolve(outcome=PENDING) returns None.
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
    # `participants` is captured for future grandchild ADs (scoping of
    # `submit_argument` to invited members; notification fan-out). v1 stores
    # but does not consult it.
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

    Public API (v1):
      - initiate(topic, initiator_id, initiator_callsign, participants) -> DeliberationSession
      - submit_argument(session_id, agent_id, agent_callsign, stance, body) -> bool
      - resolve(session_id, captain_id, captain_callsign, outcome, rationale) -> DeliberationSession | None
      - get_session(session_id) -> DeliberationSession | None

    Endorsement is deferred to AD-641d-v (bridges deliberation arguments to
    `WardRoomService.endorse(target_id=, target_type=, voter_id=, direction=)`).
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
                thread_id = thread.id
            except Exception:
                logger.warning(
                    "AD-641d: Ward Room create_thread failed for topic=%r; "
                    "continuing with in-memory session only",
                    topic, exc_info=True,
                )
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
                logger.warning(
                    "AD-641d: emit_event(DELIBERATION_INITIATED) failed; continuing",
                    exc_info=True,
                )
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
                logger.warning(
                    "AD-641d: Ward Room create_post failed for session=%s; "
                    "continuing (argument retained in-memory)",
                    session_id, exc_info=True,
                )
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
                logger.warning(
                    "AD-641d: emit_event(DELIBERATION_ARGUMENT_SUBMITTED) failed; continuing",
                    exc_info=True,
                )
        return True

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
                logger.warning(
                    "AD-641d: Ward Room create_post (resolution) failed for "
                    "session=%s; in-memory state still RESOLVED",
                    session_id, exc_info=True,
                )
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
                logger.warning(
                    "AD-641d: emit_event(DELIBERATION_RESOLVED) failed; continuing",
                    exc_info=True,
                )
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
```

Add `deliberation: DeliberationConfig = Field(default_factory=DeliberationConfig)` to `SystemConfig`.

No `default_channel_id` field in v1: the Ward Room channel for deliberations is hardcoded to `"deliberation"` inside `DeliberationProtocol.initiate(...)`'s default `channel_id` parameter. Configurable per-deployment channel selection is deferred (a future grandchild can promote this to config without breaking the v1 surface).

Verified absent: `grep -n "DeliberationConfig\|deliberation:" src/probos/config.py` returns no matches.

---

## Section 4: Startup wiring

**File:** `src/probos/startup/finalize.py`

Append after the most recent finalize wiring block:

```python
# AD-641d: Crew Deliberation Protocol
delib_cfg = getattr(getattr(runtime, "config", None), "deliberation", None)
if delib_cfg is not None and delib_cfg.enabled:
    from probos.cognitive.deliberation import DeliberationProtocol
    runtime.deliberation_protocol = DeliberationProtocol(
        ward_room=getattr(runtime, "ward_room", None),
        emit_event=runtime.emit_event,
        captain_callsign=delib_cfg.captain_callsign,
    )
    logger.info("AD-641d: DeliberationProtocol wired (captain=%s)",
                delib_cfg.captain_callsign)
else:
    runtime.deliberation_protocol = None
```

The inline `from probos.cognitive.deliberation import DeliberationProtocol` matches the sibling pattern at lines 730 (AD-641a), 753 (AD-641b), 767 (AD-641f), 789 (AD-641e), and 810 (AD-641c). The `logger.info(...)` line on success is required — every sibling AD-641X wiring logs a per-AD signature into the wave audit trail.

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
15. `test_runtime_deliberation_protocol_is_none_when_disabled` — round-trip the `DeliberationConfig.enabled = False` path through `finalize.py` and assert `runtime.deliberation_protocol is None` (per Wave 8.5 retrospective: cover the disabled-config branch of every wiring block).

Per convention #18, all `WardRoomService` mocks must be `AsyncMock(spec=WardRoomService)` — `create_thread` and `create_post` are async (BF-250 lesson).

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **`QuorumEngine`** — not touched. Mechanical consensus is its own surface.
2. **`TrustNetwork`** — endorsements still flow through existing trust API; deliberation outcomes do NOT directly modify trust in v1.
3. **`WardRoomService`** — used as a consumer; storage and lifecycle unchanged.
4. **Multi-Captain quorum** — wholesale-deferred to AD-641d-i.
5. **Counselor mediation** — wholesale-deferred to AD-641d-ii.
6. **Structured argument schema** — wholesale-deferred to AD-641d-iii.
7. **Hebbian-feedback into deliberation invitations** — wholesale-deferred to AD-641d-iv.
8. **Endorsement bridge to `WardRoomService.endorse`** — wholesale-deferred to AD-641d-v. v1 ships no `endorse(...)` method on `DeliberationProtocol`; deliberation arguments are recorded as Ward Room posts but no endorsement plumbing wires through. Adding it requires capturing `WardRoomPost.id` from `create_post` and forwarding to `WardRoomService.endorse(target_id=, target_type="post", voter_id=, direction="up")`.

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

1. **PROGRESS.md** — Prepend AD-641d CLOSED entry with v1 scope summary + 5 deferred grandchildren (AD-641d-i through AD-641d-v).
2. **DECISIONS.md** — Add the following entry under Era V (the Builder copies this verbatim):

   ```markdown
   ## AD-641d: Crew Deliberation Protocol — Captain-Resolved Judgment Surface

   **Era:** V (HXI Foundation)
   **Date:** 2026-05-02

   **Decision.** Crew deliberation is a separate surface from `QuorumEngine`. `QuorumEngine` is **mechanical** (confidence-weighted vote among tool agents for destructive ops; pass/fail). `DeliberationProtocol` is **judgment-level** (structured argument turns; Captain resolves with `ADOPTED` / `REJECTED` / `DEFERRED`).

   **Arbitration semantics (v1).**
   - Single Captain resolves; identity verified by callsign equality (case-insensitive) — same v1 convention as BF-257 DM rate limiter Captain exemption.
   - `resolve()` is idempotent: a second call after `RESOLVED` returns the existing resolved session unchanged (no overwrite).
   - `outcome=PENDING` is rejected at `resolve()` (returns `None`); only terminal outcomes `ADOPTED`/`REJECTED`/`DEFERRED` close a session.
   - Ward Room thread is the durable record; in-memory `_sessions` map is process-local. Persistence is best-effort (Ward Room calls log-and-degrade on `Exception`).

   **Distinct from existing Captain command paths.** AD-641d does NOT touch `_from_captain` priority routing in [src/probos/cognitive/sub_tasks/](src/probos/cognitive/sub_tasks/) or `captain_engagement.py`. Those are queue/quality concerns; deliberation is a strategic-decision surface invoked explicitly via `DeliberationProtocol.initiate(...)`.

   **Deferred to grandchildren.** AD-641d-i (multi-Captain quorum), AD-641d-ii (Counselor mediation), AD-641d-iii (structured argument schema), AD-641d-iv (Hebbian feedback to deliberation invitations), AD-641d-v (endorsement bridge to `WardRoomService.endorse`).

   **Closes:** AD-641 umbrella (issue #277).
   ```

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

grep -n "class WardRoomService\|async def create_thread\|async def create_post\|async def endorse" src/probos/ward_room/service.py
  src/probos/ward_room/service.py:29: class WardRoomService(EventEmitterMixin):
  src/probos/ward_room/service.py:357: async def create_thread(
  src/probos/ward_room/service.py:400: async def create_post(
  src/probos/ward_room/service.py:412: async def endorse(

sed -n '357,363p' src/probos/ward_room/service.py
  async def create_thread(
      self, channel_id: str, author_id: str, title: str, body: str,
      author_callsign: str = "", thread_mode: str = "discuss", max_responders: int = 0,
  ) -> WardRoomThread:
      return await self._threads.create_thread(
          channel_id, author_id, title, body, author_callsign, thread_mode, max_responders,
      )

sed -n '400,406p' src/probos/ward_room/service.py
  async def create_post(
      self, thread_id: str, author_id: str, body: str,
      parent_id: str | None = None, author_callsign: str = "",
  ) -> WardRoomPost:
      return await self._messages.create_post(thread_id, author_id, body, parent_id, author_callsign)

sed -n '412,415p' src/probos/ward_room/service.py
  async def endorse(
      self, target_id: str, target_type: str, voter_id: str, direction: str,
  ) -> dict[str, Any]:
      return await self._messages.endorse(target_id, target_type, voter_id, direction)
  # (Per-method signature evidence above per Wave 9B retro Recommended #2.)
  # `endorse` is included to verify the AD-641d-v deferral target's signature.

grep -n "def emit_event" src/probos/runtime.py
  src/probos/runtime.py:802: def emit_event(self, event, data=None) -> None:
  # Confirms emit_event is sync; AD-641d calls it sync (BF-Wave9B class avoided).

grep -n "AD-641a\|AD-641b\|AD-641c\|AD-641e\|AD-641f" src/probos/startup/finalize.py
  src/probos/startup/finalize.py:727:    # AD-641a: Observability Bridge
  src/probos/startup/finalize.py:730:        from probos.cognitive.observability import ObservabilityBridge
  src/probos/startup/finalize.py:750:    # AD-641b: Ward Room Hebbian Router (router only; listener deferred to AD-641b-iv)
  src/probos/startup/finalize.py:753:        from probos.cognitive.ward_room_hebbian import WardRoomHebbianRouter
  src/probos/startup/finalize.py:764:    # AD-641f: Engineering Sensor Service
  src/probos/startup/finalize.py:767:        from probos.cognitive.engineering_sensors import EngineeringSensorService
  src/probos/startup/finalize.py:786:    # AD-641e: LearnedShortcut Registry
  src/probos/startup/finalize.py:789:        from probos.cognitive.learned_shortcuts import (
  src/probos/startup/finalize.py:807:    # AD-641c: Thread Priority Service
  src/probos/startup/finalize.py:810:        from probos.cognitive.thread_priority import (
  # Confirms inline-import-at-wiring-block pattern; AD-641d Section 4 follows it.

grep -n "class DeliberationSession\|class CrewDeliberation\|deliberation_session\|DeliberationProtocol" src/probos/
  (no matches; new module)

grep -n "DELIBERATION_INITIATED\|DELIBERATION_ARGUMENT_SUBMITTED\|DELIBERATION_RESOLVED" src/probos/events.py
  (no matches; introduced by this prompt)

grep -n "DeliberationConfig\|deliberation:" src/probos/config.py
  (no matches; introduced by this prompt)

grep -n "AD-499\|ShipNamingPolicy\|callsign.*captain" src/probos/
  Multiple sites; "Captain" canonical per AD-499 + BF-244 callsign sync. v1 callsign-based check
  identical to BF-257 pattern (DM rate limiter Captain exemption).
```

---

## Revision (2026-05-02)

Pass-1 review verdict ⚠️ Conditional → revisions applied to converge to ✅ on pass-2. All 4 Required findings resolved; all 4 Recommended folded in; all 3 Nits applied.

**Required #1 — Section 4 missing inline import.** Section 4 wiring block now includes `from probos.cognitive.deliberation import DeliberationProtocol` immediately above the constructor call (matching the sibling pattern at finalize.py lines 730/753/767/789/810) plus a `logger.info("AD-641d: DeliberationProtocol wired (captain=%s)", ...)` line on success. Wave audit log now carries a per-AD signature.

**Required #2 — `DeliberationConfig.default_channel_id` was dead code.** Removed the field from `DeliberationConfig` (Section 3). The Ward Room channel `"deliberation"` remains the default via `DeliberationProtocol.initiate(..., channel_id: str = "deliberation")`; configurable per-deployment channel selection is deferred to a future grandchild without breaking the v1 surface. SRP/no-theater compliant.

**Required #3 — `endorse()` was theater.** `endorse()` removed wholesale from v1's `DeliberationProtocol` API surface. Deferred to **AD-641d-v: Endorsement bridge to `WardRoomService.endorse`** (added to deferred-grandchildren list and to "What This Does NOT Change" §8). Cascading edits:
- Solution Overview item 2: dropped `endorse(...)` from the Public API line.
- v1 scope: "4 of 8 capabilities ship" → "3 of 8 capabilities ship".
- v1 lifecycle bullet: `initiate`/`submit_argument`/`endorse`/`resolve` → `initiate`/`submit_argument`/`resolve`.
- Deferred grandchildren: "4 wholesale-deferred" → "5 wholesale-deferred"; AD-641d-v entry added with full spec hint (capture `WardRoomPost.id`; call `WardRoomService.endorse(target_id=, target_type="post", voter_id=, direction="up")` per verified signature at service.py:412).
- Section 2: `async def endorse(...)` method body removed entirely. Class docstring updated to list 3 v1 methods + `get_session`, plus an explicit pointer to AD-641d-v.
- Section 5 tests: removed `test_endorse_returns_true_for_known_argument_false_for_unknown`; replaced with `test_runtime_deliberation_protocol_is_none_when_disabled` (Nit #2 simultaneously). Test count stays at 15.
- Tracking: deferred-grandchildren count updated to 5 in PROGRESS.md entry note.

**Required #4 — DECISIONS.md inline draft block missing.** Tracking item #2 replaced with a fenced `markdown` block containing the full DECISIONS.md entry under Era V (decision, arbitration semantics, distinction from Captain command paths, all 5 deferred grandchildren including AD-641d-v, "Closes AD-641 umbrella"). Builder copies verbatim.

**Recommended #1 — phantom enum values.** `DeliberationPhase` trimmed to the two reachable v1 states: `ARGUE` and `RESOLVED`. `OPEN` and `ENDORSE` removed (no transitions set them in v1; deferred along with the capabilities they served).

**Recommended #2 — VAC missing per-method-signature evidence.** VAC enriched with `sed -n` blocks showing full kwarg signatures for `create_thread` (357-363), `create_post` (400-406), and `endorse` (412-415, included to verify the AD-641d-v deferral target). Also added `grep -n "def emit_event" src/probos/runtime.py` confirming sync signature, and `grep -n "AD-641a..."` showing the inline-import-at-wiring-block sibling pattern.

**Recommended #3 — `participants` field unread.** Inline comment added on the dataclass field documenting it as captured for future grandchild ADs (scoping of `submit_argument`; notification fan-out). v1 stores but does not consult it; comment makes the v1 boundary explicit.

**Recommended #4 — defensive `getattr(thread, "id", "")`.** Replaced with direct `thread.id` access. `WardRoomThread.id: str` is a declared dataclass field; defensive guard hid a real contract violation. The existing `except Exception` arm already handles the create_thread failure case correctly (now with a logger.warning per Nit #1).

**Nit #1 — bare `except Exception: pass` (six sites).** All six sites now use `logger.warning("AD-641d: <action> failed; ...", exc_info=True)` per the three-tier exception model. Sites: initiate's create_thread + emit_event; submit_argument's create_post + emit_event; resolve's create_post + emit_event.

**Nit #2 — `test_runtime_deliberation_protocol_is_none_when_disabled`.** Added as test 15 (replaces the dropped endorse test). Round-trips `DeliberationConfig.enabled = False` through finalize.py and asserts `runtime.deliberation_protocol is None`. Test count stays at 15.

**Nit #3 — `DeliberationOutcome.PENDING` sentinel.** Inline comment added on the enum class explicitly documenting that PENDING is the initial sentinel before resolve() and is NOT a valid resolve() outcome (resolve(outcome=PENDING) returns None).

**Closing self-check.** Grepped post-revision for OLD names that should have been swept:
- `endorse` only appears now in (1) the original roadmap quotation in §Problem (intentional historical context), (2) Recommended #4 line in this Revision section (intentional), (3) deferred grandchild references (intentional — AD-641d-v naming), and (4) the §Tracking DECISIONS.md inline block listing AD-641d-v.
- `"4 of 8"`, `"4 wholesale-deferred"`, and `ENDORSE = "endorse"` (the enum value) all return zero hits.
- `default_channel_id` returns zero hits.
- `getattr(thread, "id"` returns zero hits.
- `DeliberationPhase.OPEN` and `DeliberationPhase.ENDORSE` return zero hits.

**Phantom-API pre-check (mandatory per convention #16).** Run after revision; output appended below as evidence the revision did not introduce a verify-first regression.

**Beyond-review structural defects discovered.** None. Pass-1 already confirmed v1 isolation (zero direct calls into Wave 9A/9B artifacts), zero Wave 9B structural-defect class reproductions, and a consistent inline-import-at-wiring-block sibling pattern. The revision was purely mechanical cleanup driven by review findings; no new architectural concerns surfaced.
