# AD-641c: Ward Room Thread Priority — Importance Scoring Parallel to Attention Manager (v1)

**Status:** Ready for builder
**Wave:** 9B (cross-cutting — reads thread + post + endorsement surfaces; writes a public scorer)
**Dependencies:** Reads `ThreadManager.list_threads` at `src/probos/ward_room/threads.py:232` (verified). Reads endorsement events via `runtime.event_log.query()` (existing surface). Captain identity check uses callsign-based path identical to BF-257's pattern (Wave 8 convention; AD-499 ShipNamingPolicy canonical "Captain").
**Estimated tests:** ~14
**Risk:** MEDIUM-HIGH — touches the thread-prioritization surface that downstream HXI / proactive-loop consumers may read; v1 returns scores only, no consumer changes.

---

## Problem

The mesh `AttentionManager` (`src/probos/cognitive/attention.py:24`) scores DAG tasks by urgency × deadline × dependency. Ward Room threads have an analogous-but-separate prioritization need: which threads should be surfaced to Captain first? Which threads need attention from a department chief? Today, threads are listed by `last_post_at` only — no importance signal.

`grep -rn "class ThreadPriorityScorer\|class WardRoomThreadPriority\|thread_importance" src/probos/` returns no matches.

The roadmap entry (line 7056) names AD-641c as "Ward Room Thread Priority — Thread importance scoring parallel to Attention Manager. Factors: Captain involvement, unresolved questions, cross-department threads, thread age, endorsement density. Surfaces as thread priority in HXI."

## Solution Overview

One new module under `src/probos/cognitive/thread_priority/` (new package; AD-641c OWNS `__init__.py` creation):

1. **`ThreadPriorityScorer`** (`scorer.py`) — pure scoring class: takes a `ThreadPriorityInput` dataclass, returns a `ThreadPriorityScore` (frozen). Scoring is deterministic and side-effect-free. Public API: `score(input) -> ThreadPriorityScore`. The scorer is a value-class — no I/O, no event emission, no runtime coupling.
2. **`ThreadPriorityService`** (`service.py`) — coordinator that pulls a `ThreadPriorityInput` for a given `thread_id` from the runtime (queries `ThreadManager`, recent endorsements, recent posts) and calls the scorer. Public API: `get_priority(thread_id) -> ThreadPriorityScore | None`, `top_priorities(k=10) -> list[tuple[str, float]]`. Emits `THREAD_PRIORITY_SCORED` per `get_priority` call.

This is the **parallel** counterpart to `AttentionManager` per design doc Category C. AD-641c does NOT modify `AttentionManager`, does NOT modify `ThreadManager`, does NOT change thread storage.

**v1 scope (no-theater discipline; convention #7 + #14 — 4 of 7 capabilities ship):**

- **4 priority factors wired:** Captain involvement (boolean +0.30), unresolved-question marker (presence of "?" in latest 3 post bodies, +0.20), cross-department thread (>=2 distinct departments among participants, +0.15), thread age (recent posts elevate, exponential 24h half-life, up to +0.20). Endorsement density (+0.15) is wired but reads from event_log — see scope.
- **Real `score()` + `get_priority()` + `top_priorities()`** with deterministic results.
- **`runtime.thread_priority_service`** public attribute wired in finalize.

**3 wholesale-deferred to grandchild ADs:**

- **HXI rendering of priority indicators** — `AD-641c-i`. v1 emits a score; HXI surface is its own AD.
- **Auto-archival of low-priority threads** — `AD-641c-ii`. v1 ranks; pruning policy belongs to a follow-up.
- **Hebbian-fed priority bump** (top contributors elevate threads they participate in) — `AD-641c-iii`. Depends on AD-641b.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
THREAD_PRIORITY_SCORED = "thread_priority_scored"  # AD-641c
```

Verified absent: `grep -n "THREAD_PRIORITY_SCORED" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/thread_priority/__init__.py` (new — AD-641c OWNS directory creation)

```python
"""AD-641c: Ward Room Thread Priority -- thread importance scorer."""

from probos.cognitive.thread_priority.scorer import (
    ThreadPriorityInput,
    ThreadPriorityScore,
    ThreadPriorityScorer,
)
from probos.cognitive.thread_priority.service import ThreadPriorityService

__all__ = [
    "ThreadPriorityInput",
    "ThreadPriorityScore",
    "ThreadPriorityScorer",
    "ThreadPriorityService",
]
```

---

## Section 2: `ThreadPriorityScorer`

**File:** `src/probos/cognitive/thread_priority/scorer.py` (new)

```python
"""AD-641c: Pure thread-priority scoring.

Deterministic, side-effect-free. Factors:
  Captain involvement       weight 0.30
  Unresolved question       weight 0.20
  Cross-department thread   weight 0.15
  Thread age (recency)      weight 0.20 (24h half-life)
  Endorsement density       weight 0.15

Score is bounded [0.0, 1.0].
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


_HALF_LIFE_SECONDS = 86400.0  # 24h


@dataclass(frozen=True)
class ThreadPriorityInput:
    """Snapshot of a thread for scoring."""

    thread_id: str
    captain_involved: bool = False
    recent_post_bodies: list[str] = field(default_factory=list)
    participant_departments: list[str] = field(default_factory=list)
    last_post_at: float = 0.0
    endorsement_count: int = 0


@dataclass(frozen=True)
class ThreadPriorityScore:
    thread_id: str
    score: float
    factors: dict[str, float] = field(default_factory=dict)


class ThreadPriorityScorer:
    """Pure scorer. No I/O. No event emission."""

    def __init__(
        self,
        *,
        weight_captain: float = 0.30,
        weight_unresolved: float = 0.20,
        weight_cross_department: float = 0.15,
        weight_recency: float = 0.20,
        weight_endorsement: float = 0.15,
    ) -> None:
        self._w_captain = float(weight_captain)
        self._w_unresolved = float(weight_unresolved)
        self._w_cross = float(weight_cross_department)
        self._w_recency = float(weight_recency)
        self._w_endorsement = float(weight_endorsement)

    def score(self, inp: ThreadPriorityInput) -> ThreadPriorityScore:
        factors: dict[str, float] = {}
        total = 0.0

        if inp.captain_involved:
            factors["captain"] = self._w_captain
            total += self._w_captain

        if any("?" in (b or "") for b in inp.recent_post_bodies):
            factors["unresolved"] = self._w_unresolved
            total += self._w_unresolved

        unique_depts = {d for d in inp.participant_departments if d}
        if len(unique_depts) >= 2:
            factors["cross_department"] = self._w_cross
            total += self._w_cross

        recency = self._recency_factor(inp.last_post_at)
        if recency > 0.0:
            factors["recency"] = recency * self._w_recency
            total += recency * self._w_recency

        endorsement = self._endorsement_factor(inp.endorsement_count)
        if endorsement > 0.0:
            factors["endorsement"] = endorsement * self._w_endorsement
            total += endorsement * self._w_endorsement

        total = max(0.0, min(1.0, total))
        return ThreadPriorityScore(
            thread_id=inp.thread_id, score=total, factors=factors,
        )

    def _recency_factor(self, last_post_at: float) -> float:
        if last_post_at <= 0.0:
            return 0.0
        age_seconds = max(0.0, time.time() - last_post_at)
        return math.exp(-age_seconds / _HALF_LIFE_SECONDS)

    def _endorsement_factor(self, count: int) -> float:
        # Diminishing returns: 0 -> 0.0, 1 -> 0.5, 5 -> ~0.92, 10 -> ~0.99.
        if count <= 0:
            return 0.0
        return 1.0 - math.exp(-0.5 * float(count))
```

---

## Section 3: `ThreadPriorityService`

**File:** `src/probos/cognitive/thread_priority/service.py` (new)

```python
"""AD-641c: ThreadPriorityService -- runtime adapter.

Pulls thread state from runtime + WardRoomService, calls the scorer, emits
THREAD_PRIORITY_SCORED, exposes get_priority() and top_priorities() for
consumers (HXI, proactive loop, future grandchild ADs).
"""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.thread_priority.scorer import (
    ThreadPriorityInput,
    ThreadPriorityScore,
    ThreadPriorityScorer,
)
from probos.events import EventType

logger = logging.getLogger(__name__)


class ThreadPriorityService:
    """Public API:
    - get_priority(thread_id) -> ThreadPriorityScore | None
    - top_priorities(channel_id, k=10) -> list[(thread_id, score)]
    """

    def __init__(
        self,
        *,
        runtime: Any,
        scorer: ThreadPriorityScorer,
        emit_event: Any | None = None,
        captain_callsign: str = "Captain",
    ) -> None:
        self._runtime = runtime
        self._scorer = scorer
        self._emit_event = emit_event
        self._captain_callsign = (captain_callsign or "Captain").strip().lower()

    async def get_priority(self, thread_id: str) -> ThreadPriorityScore | None:
        if not thread_id:
            return None
        inp = await self._build_input(thread_id)
        if inp is None:
            return None
        score = self._scorer.score(inp)
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.THREAD_PRIORITY_SCORED,
                    {
                        "thread_id": score.thread_id,
                        "score": score.score,
                        "factors": dict(score.factors),
                    },
                )
            except Exception:
                pass
        return score

    async def top_priorities(
        self, channel_id: str, k: int = 10,
    ) -> list[tuple[str, float]]:
        if k <= 0 or not channel_id:
            return []
        thread_ids = await self._list_threads(channel_id)
        scored: list[tuple[str, float]] = []
        for tid in thread_ids:
            score = await self.get_priority(tid)
            if score is not None:
                scored.append((score.thread_id, score.score))
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[: int(k)]

    async def _list_threads(self, channel_id: str) -> list[str]:
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return []
        try:
            threads = await ward_room.list_threads(
                channel_id=channel_id, limit=100,
            )
        except Exception:
            return []
        out: list[str] = []
        for t in threads or []:
            tid = getattr(t, "id", None) or (
                t.get("id") if isinstance(t, dict) else None
            )
            if tid:
                out.append(str(tid))
        return out

    async def _build_input(self, thread_id: str) -> ThreadPriorityInput | None:
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            return None
        try:
            thread = await ward_room.get_thread(thread_id, post_limit=10)
        except Exception:
            thread = None
        if not thread:
            return None
        posts = self._extract_posts(thread)

        recent_bodies = [str((p.get("body") or "")) for p in posts[-3:]]
        participants: list[str] = []
        captain_involved = False
        last_post_at = 0.0
        for p in posts:
            callsign = str(p.get("author_callsign") or "")
            if callsign.strip().lower() == self._captain_callsign:
                captain_involved = True
            dept = str(p.get("department") or "")
            if dept:
                participants.append(dept)
            try:
                ts_f = float(p.get("created_at") or 0.0)
            except (TypeError, ValueError):
                ts_f = 0.0
            if ts_f > last_post_at:
                last_post_at = ts_f

        endorsement_count = self._count_endorsements(thread_id)

        return ThreadPriorityInput(
            thread_id=str(thread_id),
            captain_involved=captain_involved,
            recent_post_bodies=recent_bodies,
            participant_departments=participants,
            last_post_at=last_post_at,
            endorsement_count=endorsement_count,
        )

    def _extract_posts(self, thread: Any) -> list[dict[str, Any]]:
        # ward_room.get_thread returns a nested thread dict with "posts" or
        # similar; extract a flat list. Defensive: handle both dict and object.
        if isinstance(thread, dict):
            posts = thread.get("posts") or []
        else:
            posts = getattr(thread, "posts", None) or []
        flat: list[dict[str, Any]] = []
        for p in posts:
            if isinstance(p, dict):
                flat.append(p)
            else:
                flat.append({
                    "body": getattr(p, "body", "") or "",
                    "author_callsign": getattr(p, "author_callsign", "") or "",
                    "department": getattr(p, "department", "") or "",
                    "created_at": getattr(p, "created_at", 0.0) or 0.0,
                })
        return flat

    def _count_endorsements(self, thread_id: str) -> int:
        event_log = getattr(self._runtime, "event_log", None)
        if event_log is None:
            return 0
        try:
            entries = event_log.query(
                event_type=EventType.WARD_ROOM_ENDORSEMENT.value, limit=200,
            )
        except Exception:
            return 0
        count = 0
        for entry in entries or []:
            payload = getattr(entry, "payload", None) or (
                entry.get("payload") if isinstance(entry, dict) else None
            ) or {}
            if str(payload.get("thread_id") or "") == str(thread_id):
                count += 1
        return count
```

---

## Section 4: Configuration

**File:** `src/probos/config.py`

Add Pydantic model after the most recent addition:

```python
class ThreadPriorityConfig(BaseModel):
    """AD-641c: Ward Room Thread Priority configuration."""

    enabled: bool = True
    weight_captain: float = 0.30
    weight_unresolved: float = 0.20
    weight_cross_department: float = 0.15
    weight_recency: float = 0.20
    weight_endorsement: float = 0.15
    captain_callsign: str = "Captain"
```

Add `thread_priority: ThreadPriorityConfig = Field(default_factory=ThreadPriorityConfig)` to `SystemConfig`.

Verified absent: `grep -n "ThreadPriorityConfig\|thread_priority " src/probos/config.py` returns no matches.

---

## Section 5: Startup wiring

**File:** `src/probos/startup/finalize.py`

Append after the most recent finalize wiring block:

```python
# AD-641c: Thread Priority Service
tp_cfg = getattr(getattr(runtime, "config", None), "thread_priority", None)
if tp_cfg is not None and tp_cfg.enabled:
    runtime.thread_priority_service = ThreadPriorityService(
        runtime=runtime,
        scorer=ThreadPriorityScorer(
            weight_captain=tp_cfg.weight_captain,
            weight_unresolved=tp_cfg.weight_unresolved,
            weight_cross_department=tp_cfg.weight_cross_department,
            weight_recency=tp_cfg.weight_recency,
            weight_endorsement=tp_cfg.weight_endorsement,
        ),
        emit_event=runtime.emit_event,
        captain_callsign=tp_cfg.captain_callsign,
    )
else:
    runtime.thread_priority_service = None
```

Anchor by content. Verify by grep before applying.

---

## Section 6: Tests

**File:** `tests/test_ad641c_thread_priority.py` (new)

Cover (~14 tests):

1. `test_event_type_thread_priority_scored_exists`
2. `test_thread_priority_config_defaults`
3. `test_input_and_score_are_frozen_dataclasses`
4. `test_score_with_no_factors_returns_zero`
5. `test_captain_involvement_adds_captain_factor`
6. `test_unresolved_question_detected_in_recent_bodies`
7. `test_cross_department_requires_two_distinct`
8. `test_recency_decays_over_24h_half_life` — 0s ago = 1.0; 24h ago = ~0.5; 48h ago = ~0.25.
9. `test_endorsement_diminishing_returns` — 0 → 0; 1 → 0.5; 10 → ~0.99.
10. `test_score_clamped_to_one`
11. `test_service_get_priority_emits_event` — `AsyncMock` for ward_room; confirm payload.
12. `test_service_get_priority_returns_none_when_no_ward_room`
13. `test_service_top_priorities_takes_channel_id_and_sorts_desc`
14. `test_count_endorsements_filters_by_thread_id`

Per convention #18, mock all attributes on `Post`-shaped objects the service reads: `body`, `author_callsign`, `department`, `created_at`.

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **`AttentionManager`** — not touched. Mesh attention scores DAG tasks; thread priority is its parallel sibling.
2. **`ThreadManager`** — read-only consumer of `list_threads`; storage and lifecycle unchanged.
3. **HXI surfaces** — wholesale-deferred to AD-641c-i.
4. **Auto-archival policy** — wholesale-deferred to AD-641c-ii.
5. **Hebbian feedback into priority** — wholesale-deferred to AD-641c-iii (depends on AD-641b).

---

## Engineering Principles Compliance

- **Single Responsibility:** Scorer is pure logic. Service is the runtime adapter.
- **Open/Closed:** Adding a new factor is a new weight + branch in `score()`; existing factors unchanged.
- **Dependency Inversion:** Service constructor takes `runtime`, `scorer`, `emit_event` — no global lookup.
- **Law of Demeter:** Service reads typed `ThreadManager.list_threads` and `ward_room.get_posts`; does not reach into thread internals.
- **Fail Fast / Log-and-Degrade:** Event emission swallowed; `get_priority` returns `None` rather than raising.

---

## Verification

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad641c_thread_priority.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ward_room.py tests/test_ward_room_dms.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracking

1. **PROGRESS.md** — Prepend AD-641c CLOSED entry with v1 scope summary + 3 deferred grandchildren.
2. **DECISIONS.md** — No entry required.
3. **docs/development/roadmap.md** — Update line 7056 reflecting AD-641c CLOSED.

---

## Acceptance Criteria

- 14/14 focused tests pass at `-n 0`.
- Full parallel gate non-decreasing.
- `runtime.thread_priority_service` is a public attribute (or `None` when disabled).
- `THREAD_PRIORITY_SCORED` is a member of `EventType`.
- `ThreadPriorityInput` and `ThreadPriorityScore` are frozen.
- Scorer is pure (no I/O, no emit).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "async def get_thread\|async def list_threads\|async def create_thread" src/probos/ward_room/service.py
  src/probos/ward_room/service.py:289: async def list_threads( (channel_id required)
  src/probos/ward_room/service.py:357: async def create_thread(
  src/probos/ward_room/service.py:368: async def get_thread( (delegates to ThreadManager.get_thread which has post_limit kw)

grep -n "async def get_thread\b" src/probos/ward_room/threads.py
  src/probos/ward_room/threads.py:688: async def get_thread(self, thread_id, *, post_limit=100) -> dict | None
  (returns nested dict with "posts" key)

grep -n "class WardRoomService" src/probos/ward_room/service.py
  src/probos/ward_room/service.py:29: class WardRoomService(EventEmitterMixin):

grep -n "WARD_ROOM_ENDORSEMENT" src/probos/events.py
  src/probos/events.py:69: WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

grep -n "class AttentionManager" src/probos/cognitive/attention.py
  src/probos/cognitive/attention.py:24: class AttentionManager:

grep -n "ThreadPriority\|thread_priority\|class ThreadPriorityScorer" src/probos/
  (no matches; new module)

grep -n "THREAD_PRIORITY_SCORED" src/probos/events.py
  (no matches; introduced by this prompt)
```
