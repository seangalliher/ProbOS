# AD-641b: Ward Room Hebbian Learning — Topic↔Crew Weight Network (v1)

**Status:** Ready for builder
**Wave:** 9A (parallel-safe — independent of 641a/c/d/e/f at source-file level)
**Dependencies:** Mirrors API shape of `HebbianRouter` at `src/probos/mesh/routing.py:39` (verified). Reads `WardRoomEndorsement` events from `runtime.event_log.query()` (existing event surface — `EventType.WARD_ROOM_ENDORSEMENT` at `events.py:69`). Wires to `runtime.ward_room_router` for routing-priority hints (verified at `runtime.py:393, 1658, 1668`).
**Estimated tests:** ~14
**Risk:** MEDIUM — separate Hebbian instance, in-memory v1 storage. No coupling with mesh `HebbianRouter`.

---

## Problem

The mesh-side `HebbianRouter` learns which tool agents handle which intents best (intent → agent strengthening). Ward Room conversations have an analogous-but-separate learning surface: **which crew contribute best to which topic / channel types**. Today, Ward Room routing is static — endorsements feed trust but do not feed routing priority. Per the AD-641 design doc (Category C parallel systems), the Ward Room needs its own Hebbian instance, **not a merge** with the mesh router.

`grep -rn "class WardRoomHebbian\|class WardRoomHebbianRouter\|topic_crew_weights" src/probos/` returns no matches.

The roadmap entry (line 7056) names AD-641b as "Ward Room Hebbian Learning — Parallel Hebbian system for Ward Room routing. Learns which crew contribute best to which topic/channel types. Same math as mesh Hebbian, separate instance and storage. Informs routing priority, not hard gates."

## Solution Overview

One new module under `src/probos/cognitive/ward_room_hebbian/` (new package; AD-641b OWNS `__init__.py` creation):

1. **`WardRoomHebbianRouter`** (`router.py`) — separate Hebbian instance keyed by `(topic, agent_id)`. Public API: `record_contribution(topic, agent_id, signal)`, `get_weight(topic, agent_id) -> float`, `top_contributors(topic, k=5) -> list[tuple[str, float]]`, `decay()`, `weight_count` property. The math (Hebbian potentiation + decay) mirrors the mesh router; the storage and instance are independent.
2. **`WardRoomEndorsementListener`** (`listener.py`) — event-log subscriber that maps `WARD_ROOM_ENDORSEMENT` events into `record_contribution` calls. Endorsement-up = +1 signal, endorsement-down = -1 signal. Topic key derives from the post's thread metadata (`channel_id` or thread `topic` if present, falling back to `channel_id`).

This is **a parallel system**, per design doc. AD-641b does NOT modify mesh `HebbianRouter`, does NOT modify `TrustNetwork`, does NOT introduce hard gates on routing — weights are advisory.

**v1 scope (no-theater discipline; convention #7 + #14 — 3 of 6 capabilities ship):**

- **Real `record_contribution` + `get_weight` + `top_contributors`** with a real signal source (endorsement events).
- **In-memory storage** (dict-backed). Real Hebbian potentiation with decay parameter.
- **`runtime.ward_room_hebbian_router`** public attribute wired in finalize.

**3 wholesale-deferred to grandchild ADs:**

- **Persistent storage backend (SQLite/Chroma)** — `AD-641b-i`. v1 is in-memory; weights reset on restart. The mesh router has the same in-memory v1 history; persistence is a separate maintenance AD.
- **Routing priority integration with `WardRoomRouter`** — `AD-641b-ii`. v1 ships the router + listener; consumers query `top_contributors` voluntarily.
- **Adaptive decay cadence + reset semantics** — `AD-641b-iii`. v1 ships a fixed decay rate; per-topic decay tuning belongs to a follow-up.

---

## Section 0: Event Types

Add to `src/probos/events.py` (after `OBSERVABILITY_BRIDGE_FAILED` if AD-641a is built first; otherwise after `MCP_BRIDGE_FAILED` at line 224):

```
WARD_ROOM_HEBBIAN_UPDATED = "ward_room_hebbian_updated"  # AD-641b
WARD_ROOM_HEBBIAN_DECAYED = "ward_room_hebbian_decayed"  # AD-641b
```

Verified absent: `grep -n "WARD_ROOM_HEBBIAN_UPDATED\|WARD_ROOM_HEBBIAN_DECAYED" src/probos/events.py` returns no matches.

---

## Section 1: Package init

**File:** `src/probos/cognitive/ward_room_hebbian/__init__.py` (new — AD-641b OWNS directory creation)

```python
"""AD-641b: Ward Room Hebbian Learning -- topic<->crew weight network."""

from probos.cognitive.ward_room_hebbian.router import WardRoomHebbianRouter
from probos.cognitive.ward_room_hebbian.listener import WardRoomEndorsementListener

__all__ = [
    "WardRoomHebbianRouter",
    "WardRoomEndorsementListener",
]
```

---

## Section 2: `WardRoomHebbianRouter`

**File:** `src/probos/cognitive/ward_room_hebbian/router.py` (new)

```python
"""AD-641b: Ward Room Hebbian Router -- parallel to mesh Hebbian.

Same math, separate instance and storage. Tracks (topic, agent_id) co-activation
weights. Informs Ward Room routing priority hints; does NOT hard-gate routing.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


_DEFAULT_LEARNING_RATE = 0.10
_DEFAULT_DECAY = 0.99
_MIN_WEIGHT = 0.0
_MAX_WEIGHT = 1.0


class WardRoomHebbianRouter:
    """In-memory Hebbian router for (topic, agent_id) co-activation.

    Public API:
      - record_contribution(topic, agent_id, signal=+1.0) -> float (new weight)
      - get_weight(topic, agent_id) -> float (0.0 if absent)
      - top_contributors(topic, k=5) -> list[tuple[agent_id, weight]]
      - decay() -> int (number of weights modified)
      - weight_count (property) -> int
    """

    def __init__(
        self,
        *,
        emit_event: Any | None = None,
        learning_rate: float = _DEFAULT_LEARNING_RATE,
        decay_factor: float = _DEFAULT_DECAY,
    ) -> None:
        self._emit_event = emit_event
        self._learning_rate = float(learning_rate)
        self._decay_factor = float(decay_factor)
        self._weights: dict[tuple[str, str], float] = {}

    @property
    def weight_count(self) -> int:
        return len(self._weights)

    def record_contribution(
        self, topic: str, agent_id: str, signal: float = 1.0,
    ) -> float:
        if not topic or not agent_id:
            return 0.0
        key = (str(topic), str(agent_id))
        current = self._weights.get(key, 0.0)
        new_weight = current + self._learning_rate * float(signal)
        new_weight = max(_MIN_WEIGHT, min(_MAX_WEIGHT, new_weight))
        self._weights[key] = new_weight
        if self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.WARD_ROOM_HEBBIAN_UPDATED,
                    {
                        "topic": str(topic),
                        "agent_id": str(agent_id),
                        "weight": new_weight,
                        "signal": float(signal),
                    },
                )
            except Exception:
                pass
        return new_weight

    def get_weight(self, topic: str, agent_id: str) -> float:
        return self._weights.get((str(topic), str(agent_id)), 0.0)

    def top_contributors(
        self, topic: str, k: int = 5,
    ) -> list[tuple[str, float]]:
        if k <= 0:
            return []
        pairs = [
            (agent, weight)
            for (t, agent), weight in self._weights.items()
            if t == str(topic)
        ]
        pairs.sort(key=lambda p: p[1], reverse=True)
        return pairs[: int(k)]

    def decay(self) -> int:
        modified = 0
        for key in list(self._weights.keys()):
            self._weights[key] *= self._decay_factor
            modified += 1
        if modified and self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.WARD_ROOM_HEBBIAN_DECAYED,
                    {
                        "weights_decayed": modified,
                        "factor": self._decay_factor,
                    },
                )
            except Exception:
                pass
        return modified
```

---

## Section 3: `WardRoomEndorsementListener`

**File:** `src/probos/cognitive/ward_room_hebbian/listener.py` (new)

```python
"""AD-641b: Map WARD_ROOM_ENDORSEMENT events into Hebbian record_contribution calls.

Endorsement-up = +1 signal. Endorsement-down = -1 signal.
Topic derived from event payload: prefer 'topic' field, fall back to 'channel_id'.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WardRoomEndorsementListener:
    """v1 endorsement-event subscriber.

    Public API:
      - handle_event(event_payload: dict) -> bool  (True if recorded)
    """

    def __init__(self, *, router: Any) -> None:
        self._router = router

    def handle_event(self, payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        target_id = str(payload.get("target_agent_id") or payload.get("agent_id") or "")
        topic = str(payload.get("topic") or payload.get("channel_id") or "")
        endorsement = payload.get("endorsement") or payload.get("direction")
        if not target_id or not topic:
            return False
        if endorsement in ("up", "ENDORSE_UP", "+", 1, "1"):
            signal = 1.0
        elif endorsement in ("down", "ENDORSE_DOWN", "-", -1, "-1"):
            signal = -1.0
        else:
            return False
        self._router.record_contribution(topic, target_id, signal)
        return True
```

---

## Section 4: Configuration

**File:** `src/probos/config.py`

Add Pydantic model after the most recent addition:

```python
class WardRoomHebbianConfig(BaseModel):
    """AD-641b: Ward Room Hebbian Router configuration."""

    enabled: bool = True
    learning_rate: float = 0.10
    decay_factor: float = 0.99
```

Add `ward_room_hebbian: WardRoomHebbianConfig = Field(default_factory=WardRoomHebbianConfig)` to `SystemConfig`.

Verified absent: `grep -n "WardRoomHebbianConfig\|ward_room_hebbian" src/probos/config.py` returns no matches.

---

## Section 5: Startup wiring

**File:** `src/probos/startup/finalize.py`

After the most recent finalize wiring block (AD-449's `runtime.mcp_bridge` or AD-641a's `runtime.observability_bridge` if 641a lands first), append:

```python
# AD-641b: Ward Room Hebbian Router
wr_heb_cfg = getattr(getattr(runtime, "config", None), "ward_room_hebbian", None)
if wr_heb_cfg is not None and wr_heb_cfg.enabled:
    runtime.ward_room_hebbian_router = WardRoomHebbianRouter(
        emit_event=runtime.emit_event,
        learning_rate=wr_heb_cfg.learning_rate,
        decay_factor=wr_heb_cfg.decay_factor,
    )
    runtime.ward_room_endorsement_listener = WardRoomEndorsementListener(
        router=runtime.ward_room_hebbian_router,
    )
else:
    runtime.ward_room_hebbian_router = None
    runtime.ward_room_endorsement_listener = None
```

Anchor by content: insert after the most recent runtime.X attribute assignment in finalize.py. Verify by grep before applying.

---

## Section 6: Tests

**File:** `tests/test_ad641b_ward_room_hebbian.py` (new)

Cover (~14 tests):

1. `test_event_type_ward_room_hebbian_updated_exists`
2. `test_event_type_ward_room_hebbian_decayed_exists`
3. `test_ward_room_hebbian_config_defaults`
4. `test_record_contribution_creates_weight` — new (topic, agent) starts at 0; +1 signal → 0.10.
5. `test_record_contribution_clamped_to_max` — repeated +1 signals saturate at 1.0.
6. `test_record_contribution_clamped_to_min` — −1 signals from 0 stay at 0.0.
7. `test_record_contribution_emits_event` — confirm payload contains topic, agent_id, weight, signal.
8. `test_record_contribution_empty_topic_rejected` — returns 0.0; no weight created.
9. `test_get_weight_unknown_returns_zero`
10. `test_top_contributors_sorted_desc` — 3 agents, distinct weights.
11. `test_decay_modifies_all_weights_and_emits_event`
12. `test_listener_handles_endorsement_up` — payload with `endorsement=up` → router called with +1.0.
13. `test_listener_handles_endorsement_down` — `endorsement=down` → −1.0.
14. `test_listener_rejects_payload_missing_topic_or_target` — returns False.

Per convention #11 — listener tests pass real router; do not over-mock.

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **Mesh `HebbianRouter`** — not touched. The Ward Room router is a separate instance with separate storage.
2. **`WardRoomRouter` routing logic** — not touched in v1. Routing-priority integration is `AD-641b-ii`.
3. **`TrustNetwork`** — endorsements still flow into trust per existing `record_outcome()` paths. The Hebbian router is an additional consumer of the same signal, not a replacement.
4. **Persistent storage** — in-memory v1; SQLite backend is `AD-641b-i`.
5. **Decay cadence** — `decay()` is callable; no automatic timer in v1. Operators or a future grandchild AD wire the cadence.

---

## Engineering Principles Compliance

- **Single Responsibility:** Router does math + storage. Listener maps events. Two classes, two reasons to change.
- **Open/Closed:** New signal sources (DM exchanges, thread participation) become additional listeners; router unchanged.
- **Dependency Inversion:** Listener takes router as constructor parameter. Router has no upward dependencies.
- **Law of Demeter:** Listener reads payload fields directly; does not reach into router internals.
- **Fail Fast / Log-and-Degrade:** Emit failures are swallowed (event-emission is not critical to learning correctness).
- **DRY:** Hebbian math mirrors mesh router conceptually; storage and instance are intentionally separate per design doc.

---

## Verification

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad641b_ward_room_hebbian.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_hebbian.py -v -n 0   # mesh router regression
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracking

1. **PROGRESS.md** — Prepend AD-641b CLOSED entry with v1 scope summary + 3 deferred grandchildren.
2. **DECISIONS.md** — No entry required (parallel-systems pattern documented in design doc).
3. **docs/development/roadmap.md** — Update line 7056 AD-641 row reflecting AD-641b CLOSED.

---

## Acceptance Criteria

- 14/14 focused tests pass at `-n 0`.
- Full parallel gate non-decreasing.
- `runtime.ward_room_hebbian_router` and `runtime.ward_room_endorsement_listener` are public attributes (or `None` when disabled).
- 2 new EventTypes are members of `EventType`.
- Mesh `HebbianRouter` instance is unchanged (verified by `tests/test_hebbian.py` regression).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "class HebbianRouter" src/probos/mesh/routing.py
  src/probos/mesh/routing.py:39: class HebbianRouter:

grep -n "WARD_ROOM_ENDORSEMENT" src/probos/events.py
  src/probos/events.py:69: WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

grep -n "ward_room_router" src/probos/runtime.py
  src/probos/runtime.py:393: self.ward_room_router: WardRoomRouter | None = None
  src/probos/runtime.py:1658: self.ward_room_router = fin.ward_room_router

grep -n "WardRoomHebbian\|ward_room_hebbian\|topic_crew" src/probos/
  (no matches; new module)

grep -n "WARD_ROOM_HEBBIAN" src/probos/events.py
  (no matches; introduced by this prompt)

grep -n "class TrustNetwork" src/probos/consensus/trust.py
  src/probos/consensus/trust.py:103: class TrustNetwork:
  (referenced for boundary clarity; not modified)
```
