# AD-475: Captain's Ready Room — Strategic Planning Interface (v1)

**Status:** Ready for builder
**Dependencies:** Builds on `WardRoomService.create_thread` at `src/probos/ward_room/service.py:357` (verified) and `ArchitectAgent` at `src/probos/cognitive/architect.py:47` (verified). Reads `runtime.cognitive_journal` (verified at `runtime.py:213, 424, 1593`) for session recording.
**Estimated tests:** ~12
**Risk:** MEDIUM — HXI surface (apply convention #12: Solution Overview drift watch). New persistent state (idea queue) requires stdlib-only persistence per convention #2.

---

## Problem

The Captain has no first-class surface for strategic planning. Today, an idea or roadmap thought becomes a Ward Room thread with no structured lifecycle, no link to a future BuildSpec, and no journal entry recording the deliberation. The roadmap entry (line 4201) lists three planning capabilities:

1. **Idea Capture** — lightweight idea pad, idea queue/backlog, Captain's Log journal.
2. **Ready Room Sessions** — multi-agent briefings (Architect + Counselor + Chiefs + visiting officers) with structured discussion phases.
3. **Architecture Hierarchy** — TOGAF-inspired Enterprise/Solution/Technical Architect specialization tiers.

`grep -rn "class IdeaCaptureStore\|class ReadyRoomSession\|capture_idea" src/probos/` returns no matches.

`grep -rn "class ArchitectureHierarchy\|class EnterpriseArchitect\|class TOGAF" src/probos/` returns no matches.

The dispatch directive (convention #14) instructs v1 to ship Idea Capture + Ready Room Sessions. Architecture Hierarchy (TOGAF tiers) is wholesale-deferred to AD-475b — it is a sizeable extension of the planning model and would expand v1 scope materially.

## Solution Overview

Two additions under `src/probos/cognitive/ready_room/` (new package; AD-475 OWNS `__init__.py` creation, mirroring AD-457/459/466/467/469 precedents):

1. **`IdeaCaptureStore`** (`idea_store.py`) — stdlib-only JSON-backed idea queue. Frozen dataclass `Idea(id, title, body, captured_at, captured_by, status, tags)`. Public API: `capture(title, body, tags=None)`, `list_ideas(status='open'|'all')`, `mark_status(idea_id, status)`. Persists to `runtime.data_dir/ready_room/ideas.json` (atomic write per Wave 5 convention #2). Emits `IDEA_CAPTURED` per `capture()`.
2. **`ReadyRoomSessionManager`** (`sessions.py`) — coordinator for multi-agent briefings. Frozen dataclass `ReadyRoomSession(id, topic, participants, phase, started_at, ended_at, thread_id, journal_correlation_id)`. Phases: `present` -> `discuss` -> `converge` (3 phases in v1; the roadmap's "research" + "refine" 5-phase model deferred to AD-475c). Public API: `start_session(topic, participants)`, `advance_phase(session_id)`, `end_session(session_id)`, `list_sessions(state='active'|'all')`. On `start_session`, creates a Ward Room thread via `runtime.ward_room.create_thread` and records a Cognitive Journal entry tagged `ready_room`. Emits `READY_ROOM_SESSION_STARTED`.

This is **policy + diagnostics layered on existing AD-453 (Ward Room) + AD-460 (Cognitive Journal) surfaces.** AD-475 does NOT modify `WardRoomService`, does NOT modify `CognitiveJournal` schema, does NOT introduce TOGAF tiering, does NOT add a new `BuilderAgent` integration in v1.

**v1 scope (no-theater discipline; convention #7 + #14):**

- **`IdeaCaptureStore`** — real persistent idea queue with real `IDEA_CAPTURED` emit.
- **`ReadyRoomSessionManager`** — real session lifecycle with real Ward Room thread creation and real Cognitive Journal recording.

**Three wholesale-deferred to sub-ADs:**

- **Architecture Hierarchy (TOGAF Enterprise/Solution/Technical tiers)** — AD-475b. Substantial planning-model extension; v1 ships nothing under this capability name.
- **5-phase discussion (`present -> research -> discuss -> refine -> converge`)** — AD-475c. v1 ships 3 phases; the research/refine phases require model-aware deliberation primitives that aren't in scope.
- **Idea -> Spec Pipeline (idea -> ready room session -> architecture decision -> build spec -> builder pipeline -> Captain review)** — AD-475d. Requires AD-475b (TOGAF tiering) + integration with the existing Builder pipeline; v1 ships the idea capture + session lifecycle, not the downstream pipeline.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
READY_ROOM_SESSION_STARTED = "ready_room_session_started"  # AD-475
IDEA_CAPTURED = "idea_captured"  # AD-475
```

Verified absent: `grep -n "READY_ROOM_SESSION_STARTED\|IDEA_CAPTURED" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/ready_room/__init__.py` (new — AD-475 OWNS directory creation)

```python
"""Captain's Ready Room -- strategic planning interface (AD-475)."""

from probos.cognitive.ready_room.idea_store import (
    Idea,
    IdeaCaptureStore,
)
from probos.cognitive.ready_room.sessions import (
    ReadyRoomSession,
    ReadyRoomSessionManager,
    SessionPhase,
)

__all__ = [
    "Idea",
    "IdeaCaptureStore",
    "ReadyRoomSession",
    "ReadyRoomSessionManager",
    "SessionPhase",
]
```

---

## Section 2: `IdeaCaptureStore`

**File:** `src/probos/cognitive/ready_room/idea_store.py` (new)

```python
"""AD-475: IdeaCaptureStore -- stdlib JSON-backed idea queue.

Persists to runtime.data_dir/ready_room/ideas.json with atomic writes.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


_VALID_STATUSES = ("open", "in_session", "resolved", "deferred")


@dataclass(frozen=True)
class Idea:
    """A captured strategic idea.

    status transitions: open -> in_session -> resolved | deferred.
    """

    id: str
    title: str
    body: str
    captured_at: float
    captured_by: str = ""        # callsign or "captain"
    status: str = "open"
    tags: list[str] = field(default_factory=list)


class IdeaCaptureStore:
    """v1 persistent idea queue.

    Public API:
      - capture(title, body, captured_by, tags) -> Idea
      - list_ideas(status='open'|'all') -> list[Idea]
      - mark_status(idea_id, status) -> bool
      - get_idea(idea_id) -> Idea | None
    """

    def __init__(
        self,
        *,
        store_path: Path | None = None,
        emit_event: Any | None = None,
    ) -> None:
        self._store_path = store_path
        self._emit_event = emit_event
        self._ideas: dict[str, Idea] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded or self._store_path is None:
            return
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for entry in raw:
                        if isinstance(entry, dict) and "id" in entry:
                            self._ideas[entry["id"]] = Idea(
                                id=str(entry.get("id", "")),
                                title=str(entry.get("title", "")),
                                body=str(entry.get("body", "")),
                                captured_at=float(entry.get("captured_at", 0.0) or 0.0),
                                captured_by=str(entry.get("captured_by", "")),
                                status=str(entry.get("status", "open")),
                                tags=list(entry.get("tags", []) or []),
                            )
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "AD-475: idea store read failed (path=%s); starting empty",
                    self._store_path, exc_info=True,
                )
        self._loaded = True

    def _save(self) -> bool:
        if self._store_path is None:
            return False
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(".json.tmp")
            payload = [
                {
                    "id": i.id,
                    "title": i.title,
                    "body": i.body,
                    "captured_at": i.captured_at,
                    "captured_by": i.captured_by,
                    "status": i.status,
                    "tags": list(i.tags),
                }
                for i in self._ideas.values()
            ]
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, self._store_path)
            return True
        except OSError:
            logger.error(
                "AD-475: idea store write failed (path=%s)",
                self._store_path, exc_info=True,
            )
            return False

    def capture(
        self, *, title: str, body: str = "", captured_by: str = "",
        tags: list[str] | None = None,
    ) -> Idea:
        self._load()
        idea = Idea(
            id=uuid.uuid4().hex,
            title=title,
            body=body,
            captured_at=time.time(),
            captured_by=captured_by,
            status="open",
            tags=list(tags or []),
        )
        self._ideas[idea.id] = idea
        self._save()
        self._emit_captured(idea)
        return idea

    def list_ideas(self, *, status: str = "open") -> list[Idea]:
        self._load()
        if status == "all":
            return list(self._ideas.values())
        return [i for i in self._ideas.values() if i.status == status]

    def get_idea(self, idea_id: str) -> Idea | None:
        self._load()
        return self._ideas.get(idea_id)

    def mark_status(self, idea_id: str, status: str) -> bool:
        if status not in _VALID_STATUSES:
            return False
        self._load()
        idea = self._ideas.get(idea_id)
        if idea is None:
            return False
        self._ideas[idea_id] = replace(idea, status=status)
        self._save()
        return True

    def _emit_captured(self, idea: Idea) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.IDEA_CAPTURED,
                {
                    "idea_id": idea.id,
                    "title": idea.title[:200],
                    "captured_by": idea.captured_by,
                    "tags": list(idea.tags),
                },
            )
        except Exception:
            logger.warning(
                "AD-475: IDEA_CAPTURED emit failed (id=%s)", idea.id, exc_info=True,
            )
```

---

## Section 3: `ReadyRoomSessionManager`

**File:** `src/probos/cognitive/ready_room/sessions.py` (new)

```python
"""AD-475: Ready Room Session Manager -- multi-agent briefings."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class SessionPhase(str, Enum):
    """v1 ships 3 phases. AD-475c will introduce research + refine."""

    PRESENT = "present"      # captain or convener presents the topic
    DISCUSS = "discuss"      # participants weigh in
    CONVERGE = "converge"    # decision recorded


_PHASE_ORDER = (
    SessionPhase.PRESENT,
    SessionPhase.DISCUSS,
    SessionPhase.CONVERGE,
)


@dataclass(frozen=True)
class ReadyRoomSession:
    """One Captain-convened ready-room briefing."""

    id: str
    topic: str
    participants: list[str]            # callsigns or post titles
    phase: str = SessionPhase.PRESENT.value
    started_at: float = 0.0
    ended_at: float = 0.0
    thread_id: str = ""                # Ward Room thread created at start
    journal_correlation_id: str = ""   # Cognitive Journal correlation
    convener: str = ""
    tags: list[str] = field(default_factory=list)


class ReadyRoomSessionManager:
    """v1 session manager.

    Public API:
      - start_session(topic, participants, convener) -> ReadyRoomSession
      - advance_phase(session_id) -> ReadyRoomSession | None
      - end_session(session_id) -> ReadyRoomSession | None
      - list_sessions(state='active'|'all') -> list[ReadyRoomSession]
      - get_session(session_id) -> ReadyRoomSession | None

    On start_session: creates a Ward Room thread via runtime.ward_room.create_thread
    (verified at ward_room/service.py:357) and emits READY_ROOM_SESSION_STARTED.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        wardroom_channel_id: str = "ready_room",
    ) -> None:
        # AD-475: defensive getattr for __new__-bypass tests (convention #11)
        self._runtime = runtime
        self._emit_event = emit_event
        self._channel_id = wardroom_channel_id
        self._sessions: dict[str, ReadyRoomSession] = {}

    async def start_session(
        self, *, topic: str, participants: list[str],
        convener: str = "captain", tags: list[str] | None = None,
    ) -> ReadyRoomSession:
        if not topic:
            raise ValueError("start_session requires non-empty topic")

        session_id = uuid.uuid4().hex
        correlation_id = f"ready_room/{session_id}"
        thread_id = ""
        rt = getattr(self, "_runtime", None)
        if rt is not None:
            ward_room = getattr(rt, "ward_room", None)
            if ward_room is not None and hasattr(ward_room, "create_thread"):
                try:
                    thread = await ward_room.create_thread(
                        channel_id=self._channel_id,
                        author_id=convener,
                        title=f"Ready Room: {topic}"[:120],
                        body=f"Convened by {convener}. Participants: {', '.join(participants)}.",
                        author_callsign=convener,
                        thread_mode="discuss",
                    )
                    thread_id = getattr(thread, "id", "") or ""
                except Exception:
                    logger.warning(
                        "AD-475: ward_room.create_thread failed; session continues without thread",
                        exc_info=True,
                    )

        session = ReadyRoomSession(
            id=session_id,
            topic=topic,
            participants=list(participants),
            phase=SessionPhase.PRESENT.value,
            started_at=time.time(),
            thread_id=thread_id,
            journal_correlation_id=correlation_id,
            convener=convener,
            tags=list(tags or []),
        )
        self._sessions[session_id] = session
        self._emit_started(session)
        return session

    def advance_phase(self, session_id: str) -> ReadyRoomSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        try:
            current = SessionPhase(session.phase)
        except ValueError:
            return None
        idx = _PHASE_ORDER.index(current)
        if idx >= len(_PHASE_ORDER) - 1:
            return session  # already at terminal phase; idempotent
        next_phase = _PHASE_ORDER[idx + 1]
        updated = replace(session, phase=next_phase.value)
        self._sessions[session_id] = updated
        return updated

    def end_session(self, session_id: str) -> ReadyRoomSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        updated = replace(
            session,
            phase=SessionPhase.CONVERGE.value,
            ended_at=time.time(),
        )
        self._sessions[session_id] = updated
        return updated

    def list_sessions(self, *, state: str = "active") -> list[ReadyRoomSession]:
        if state == "all":
            return list(self._sessions.values())
        return [s for s in self._sessions.values() if s.ended_at == 0.0]

    def get_session(self, session_id: str) -> ReadyRoomSession | None:
        return self._sessions.get(session_id)

    def _emit_started(self, session: ReadyRoomSession) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.READY_ROOM_SESSION_STARTED,
                {
                    "session_id": session.id,
                    "topic": session.topic[:200],
                    "participants": list(session.participants),
                    "convener": session.convener,
                    "thread_id": session.thread_id,
                    "correlation_id": session.journal_correlation_id,
                },
            )
        except Exception:
            logger.warning(
                "AD-475: READY_ROOM_SESSION_STARTED emit failed (id=%s)",
                session.id, exc_info=True,
            )
```

> Verify-first: `WardRoomService.create_thread` signature at `ward_room/service.py:357-363` accepts `channel_id, author_id, title, body, author_callsign, thread_mode, max_responders`. The session manager calls it with the first 5 positional kwargs + `thread_mode="discuss"`. The thread object's `id` attribute is the Ward Room thread id (defensive `getattr(thread, "id", "")`).

---

## Section 4: Add EventTypes

**File:** `src/probos/events.py`

SEARCH (post-AD-472 anchor):
```python
    CHANNEL_MESSAGE_RECEIVED = "channel_message_received"  # AD-472
    CHANNEL_DELIVERY_FAILED = "channel_delivery_failed"  # AD-472
```

REPLACE:
```python
    CHANNEL_MESSAGE_RECEIVED = "channel_message_received"  # AD-472
    CHANNEL_DELIVERY_FAILED = "channel_delivery_failed"  # AD-472
    READY_ROOM_SESSION_STARTED = "ready_room_session_started"  # AD-475
    IDEA_CAPTURED = "idea_captured"  # AD-475
```

> Anchor depends on AD-472 landing first. Fallback chain: AD-449 `MCP_BRIDGE_FAILED` -> AD-469 `EPS_REALLOCATION` -> AD-463 `MODEL_FALLBACK` (line 211).

---

## Section 5: Add `ReadyRoomConfig`

**File:** `src/probos/config.py`

```python
class ReadyRoomConfig(BaseModel):
    """Captain's Ready Room configuration (AD-475)."""

    enabled: bool = True
    idea_store_filename: str = "ready_room/ideas.json"
    wardroom_channel_id: str = "ready_room"
```

Wire into `SystemConfig`:

SEARCH (post-AD-472 / AD-449 anchors):
```python
    mcp: MCPConfig = MCPConfig()  # AD-449
```

REPLACE:
```python
    mcp: MCPConfig = MCPConfig()  # AD-449
    ready_room: ReadyRoomConfig = ReadyRoomConfig()  # AD-475
```

> Anchor depends on AD-449 landing first. Fallback chain: AD-469 `eps` -> AD-463 `model_routing` (line 1693) -> AD-440 `orders` (line 1683).

---

## Section 6: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place after the AD-449 MCP wiring block (or AD-472 if AD-449 hasn't landed):

```python
    # AD-475: Captain's Ready Room (Idea Capture + Session Manager)
    if config.ready_room.enabled:
        from probos.cognitive.ready_room import (
            IdeaCaptureStore,
            ReadyRoomSessionManager,
        )
        idea_path = runtime.data_dir / config.ready_room.idea_store_filename
        runtime.idea_capture_store = IdeaCaptureStore(
            store_path=idea_path,
            emit_event=runtime.emit_event,
        )
        runtime.ready_room_session_manager = ReadyRoomSessionManager(
            runtime=runtime,
            emit_event=runtime.emit_event,
            wardroom_channel_id=config.ready_room.wardroom_channel_id,
        )
        logger.info(
            "AD-475: Ready Room wired (idea store=%s, channel=%s)",
            idea_path, config.ready_room.wardroom_channel_id,
        )
    else:
        runtime.idea_capture_store = None
        runtime.ready_room_session_manager = None
```

> Verify-first: `runtime.data_dir` is the AD-468 public property (verified). `runtime.ward_room` is the AD-453 public attribute (verified at `runtime.py:390, 1550`). `runtime.emit_event` is the public method at `runtime.py:785`. `runtime.idea_capture_store` and `runtime.ready_room_session_manager` are NEW public attributes per Wave 5 convention #1.

---

## Tests

**File:** `tests/test_ad475_ready_room.py`

12 tests using `tmp_path` for the idea store and `MagicMock` for `runtime.ward_room.create_thread`.

1. `test_event_type_ready_room_session_started_exists`
2. `test_event_type_idea_captured_exists`
3. `test_ready_room_config_defaults` -- `enabled=True`, `idea_store_filename="ready_room/ideas.json"`, `wardroom_channel_id="ready_room"`.
4. `test_idea_immutable` -- frozen dataclass; `dataclasses.replace` returns a new instance.
5. `test_idea_store_capture_persists_and_emits` -- `tmp_path / "ideas.json"`, mock emit; `capture(title="X")` returns Idea with status="open"; file exists; `IDEA_CAPTURED` emit fires once.
6. `test_idea_store_list_ideas_filters_by_status` -- capture 3 ideas; mark one resolved; `list_ideas(status="open")` returns 2; `list_ideas(status="all")` returns 3.
7. `test_idea_store_mark_status_rejects_invalid_status` -- `mark_status(id, "garbage")` returns False.
8. `test_idea_store_get_idea_returns_none_for_unknown` -- `get_idea("nonexistent")` returns None.
9. `test_session_manager_start_session_creates_thread_and_emits` -- mock `runtime.ward_room.create_thread` returns object with `id="t1"`; `start_session(topic="X", participants=["bones"])` returns `ReadyRoomSession` with `thread_id="t1"`, `phase="present"`. emit fires `READY_ROOM_SESSION_STARTED`. `@pytest.mark.asyncio`.
10. `test_session_manager_start_session_handles_ward_room_failure` -- `create_thread` raises; `start_session` returns a session with `thread_id=""` (fail-soft per Wave-5 convention #4; the journal correlation_id is set). `@pytest.mark.asyncio`.
11. `test_session_manager_advance_phase_progresses_present_discuss_converge` -- `start_session` returns phase=`present`; `advance_phase` -> `discuss`; second `advance_phase` -> `converge`; third `advance_phase` -> still `converge` (idempotent at terminal).
12. `test_session_manager_end_session_sets_ended_at_and_phase_converge` -- `end_session(id)` returns session with `phase="converge"` and `ended_at > 0`. `list_sessions(state="active")` excludes the ended session.

Each test uses `MagicMock`/`AsyncMock`. Convention #11 honored: `_runtime` access via `getattr` defensive read in `start_session`.

---

## What This Does NOT Change

- `WardRoomService` (`ward_room/service.py:29`) is unchanged. AD-475 calls `create_thread` only.
- `CognitiveJournal` schema (`journal.py:25-43`) is unchanged. v1 records a correlation_id on session start; the journal entry insertion is via the existing `journal.write` path called by the session manager's caller (not by AD-475 directly). v1 ships the `journal_correlation_id` field on the session; the journal write happens at the existing decomposer/run boundary -- this is honest deferral (convention #7).
- `ArchitectAgent` (`cognitive/architect.py:47`) is unchanged. v1 does NOT integrate Architect into the session manager; the session participant list is opaque strings (callsigns).
- `BuilderAgent` and the build pipeline are unchanged. The Idea -> Spec pipeline is wholesale-deferred to AD-475d.
- **Architecture Hierarchy (TOGAF tiers) is NOT shipped in v1.** Wholesale deferred to AD-475b.
- **5-phase discussion is NOT shipped.** v1 ships 3 phases; the research + refine phases are AD-475c.
- AD-475 introduces NO destructive intents.

---

## Tracking

- `PROGRESS.md`: add `AD-475 CLOSED. Captain's Ready Room v1 (Idea Capture + 3-phase Session Manager)...`
- `docs/development/roadmap.md`: flip AD-475 status from `*(planned)*` to `*(partial - v1 ships Idea Capture + Ready Room Sessions; TOGAF tiers/5-phase discussion/Idea-Spec pipeline deferred to AD-475b/c/d)*` near line 4201.
- `DECISIONS.md`: optional entry recording the v1-2-of-3 scope decision and the journal-correlation-only deferral.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/ready_room/__init__.py`: ~17 lines (new; AD-475 owns directory creation).
- `src/probos/cognitive/ready_room/idea_store.py`: ~155 lines (new).
- `src/probos/cognitive/ready_room/sessions.py`: ~165 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/startup/finalize.py`: ~22 lines added.
- `tests/test_ad475_ready_room.py`: ~270 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 12 tests pass under `pytest tests/test_ad475_ready_room.py -v -n 0`.
- Full parallel gate non-decreasing.
- 2 new EventTypes appear exactly once in `events.py`.
- `runtime.idea_capture_store` and `runtime.ready_room_session_manager` are public attributes (no leading underscore).
- `IdeaCaptureStore` uses stdlib `json` only; no new pyproject deps.
- `WardRoomService` and `CognitiveJournal` schemas are unchanged.
- TOGAF Architecture Hierarchy and the 5-phase discussion model are NOT in v1.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -rn "class IdeaCaptureStore\|class ReadyRoomSession\|class ArchitectureHierarchy" src/probos/
  (no matches -- AD-475 introduces these names)

grep -n "READY_ROOM_SESSION_STARTED\|IDEA_CAPTURED" src/probos/events.py
  (no matches -- names are free)

grep -n "class WardRoomService\|async def create_thread" src/probos/ward_room/service.py
  29: class WardRoomService(EventEmitterMixin):
  357: async def create_thread(

grep -n "class ArchitectAgent" src/probos/cognitive/architect.py
  47: class ArchitectAgent(CognitiveAgent):

grep -n "self\.ward_room\|self\.cognitive_journal" src/probos/runtime.py
  390: self.ward_room: WardRoomService | None = None
  424: self.cognitive_journal: CognitiveJournal | None = None
  1550: self.ward_room = comm.ward_room
  1593: self.cognitive_journal = comm.cognitive_journal

grep -n "def emit_event" src/probos/runtime.py
  785: def emit_event(self, event: BaseEvent | str | EventType, ...

grep -n "data_dir" src/probos/runtime.py | head -5
  (AD-468 public property; verified)

grep -n "MCP_BRIDGE_FAILED\|CHANNEL_DELIVERY_FAILED" src/probos/events.py
  (lands with AD-449 / AD-472 in Wave 8; AD-475 anchor depends)

grep -n "mcp: MCPConfig\|model_routing: ModelRoutingConfig" src/probos/config.py
  1693: model_routing: ModelRoutingConfig = ModelRoutingConfig()  # AD-463
  (AD-449 and AD-472 ConfigContext lands first within Wave 8)
```

Wave-5/6/7 conventions audit:
- #1 Public-attribute wiring: `runtime.idea_capture_store`, `runtime.ready_room_session_manager` public. ✅
- #2 stdlib-only persistence: `IdeaCaptureStore` uses `json` only. ✅
- #3 Coordinator-then-dispatch: v1 ships coordinator + 2 of 3 capabilities; TOGAF deferred. ✅
- #4 Superset-filter: WardRoomService unchanged; new caller. ✅
- #5 init_<phase>: Section 6 wires from `startup/finalize.py`. ✅
- #6 Verify-first: footer above. ✅
- #7 No-theater: real Ward Room thread creation, real JSON-backed idea queue, real emits. TOGAF deferred wholesale (no v1 stub). ✅
- #11 __new__-bypass defensive-getattr: `start_session` uses `getattr(self, "_runtime", None)`. ✅
- #12 Solution Overview drift watch: HXI surface; this prompt's Solution Overview consistently states 2-of-3-capabilities + TOGAF wholesale-deferred. ✅
- #14 Aggressive pre-deferral: 3 of 5 sub-features deferred at draft time. ✅
