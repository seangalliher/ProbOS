# AD-641b: Ward Room Hebbian Learning — Topic↔Crew Weight Network (v1)

**Status:** Ready for builder
**Wave:** 9A (parallel-safe — independent of 641a/c/d/e/f at source-file level)
**Dependencies:** Conceptually parallel to mesh `HebbianRouter` at `src/probos/mesh/routing.py:39` (verified) — separate instance, separate storage, deliberately divergent API shape (mesh uses `record_interaction(source, target, success)` + `decay_all()`; Ward Room uses `record_contribution(topic, agent_id, signal)` + `decay()` because the routing surface is `(topic, agent)` not `(agent, agent)`). v1 ships the router only; the endorsement listener is wholesale-deferred to AD-641b-iv per pass-1 review (no event-bus subscribe API exists in `src/probos/` — verified by `grep -rn "event_log\.subscribe\|register_handler\|add_event_handler\|subscribe_event" src/probos/` returning no matches).
**Estimated tests:** ~11
**Risk:** MEDIUM — separate Hebbian instance, in-memory v1 storage. No coupling with mesh `HebbianRouter`. No listener integration in v1 (deferred).

---

## Problem

The mesh-side `HebbianRouter` learns which tool agents handle which intents best (intent → agent strengthening). Ward Room conversations have an analogous-but-separate learning surface: **which crew contribute best to which topic / channel types**. Today, Ward Room routing is static — endorsements feed trust but do not feed routing priority. Per the AD-641 design doc (Category C parallel systems), the Ward Room needs its own Hebbian instance, **not a merge** with the mesh router.

`grep -rn "class WardRoomHebbian\|class WardRoomHebbianRouter\|topic_crew_weights" src/probos/` returns no matches.

The roadmap entry (line 7056) names AD-641b as "Ward Room Hebbian Learning — Parallel Hebbian system for Ward Room routing. Learns which crew contribute best to which topic/channel types. Same math as mesh Hebbian, separate instance and storage. Informs routing priority, not hard gates."

## Solution Overview

One new module under `src/probos/cognitive/ward_room_hebbian/` (new package; AD-641b OWNS `__init__.py` creation):

1. **`WardRoomHebbianRouter`** (`router.py`) — separate Hebbian instance keyed by `(topic, agent_id)`. Public API: `record_contribution(topic, agent_id, signal)`, `get_weight(topic, agent_id) -> float`, `top_contributors(topic, k=5) -> list[tuple[str, float]]`, `decay()`, `weight_count` property. Math (Hebbian potentiation + decay) is conceptually parallel to the mesh router, but the API shape is deliberately divergent: mesh routes `(source_agent → target_agent)` co-activation while Ward Room routes `(topic → agent)` contribution. Method names differ accordingly (`record_contribution` vs `record_interaction`, `decay` vs `decay_all`); this is documented divergence, not duplication.

This is **a parallel system**, per design doc. AD-641b does NOT modify mesh `HebbianRouter`, does NOT modify `TrustNetwork`, does NOT introduce hard gates on routing — weights are advisory. v1 also does NOT introduce an event-bus subscribe surface; the endorsement-events → Hebbian listener is wholesale-deferred to AD-641b-iv.

**v1 scope (no-theater discipline; convention #7 + #14 — 2 of 6 capabilities ship):**

- **Real `record_contribution` + `get_weight` + `top_contributors` + `decay`** with in-memory storage and real Hebbian potentiation. Callers (tests in v1; future listener / future routing in deferred grandchildren) invoke `record_contribution` directly to feed signals.
- **`runtime.ward_room_hebbian_router`** public attribute wired in finalize.

**4 wholesale-deferred to grandchild ADs:**

- **Persistent storage backend (SQLite/Chroma)** — `AD-641b-i`. v1 is in-memory; weights reset on restart. The mesh router has the same in-memory v1 history; persistence is a separate maintenance AD.
- **Routing priority integration with `WardRoomRouter`** — `AD-641b-ii`. v1 ships the router; consumers query `top_contributors` voluntarily once integrated.
- **Adaptive decay cadence + reset semantics** — `AD-641b-iii`. v1 ships a fixed decay rate; per-topic decay tuning belongs to a follow-up.
- **Endorsement-event → Hebbian listener (signal-source wiring)** — `AD-641b-iv`. v1 ships the router with NO automatic signal source. Per pass-1 review, ProbOS has no event-bus subscribe API today (`grep -rn "event_log\.subscribe\|register_handler\|add_event_handler\|subscribe_event" src/probos/` returns zero matches), so a `WardRoomEndorsementListener` would ship as dead code — convention #7 violation. The listener ships when ProbOS introduces an event-bus subscribe mechanism (separate AD), OR when the emit-side at `WARD_ROOM_ENDORSEMENT` (`src/probos/ward_room/messages.py:597`) is modified to call the listener directly. Until then, callers feed the router via direct `record_contribution()` invocations.

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

__all__ = [
    "WardRoomHebbianRouter",
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
        # AD-641b revision: filter zero-weight entries so decayed topics don't
        # surface as ghost contributors (per pass-1 R1).
        pairs = [
            (agent, weight)
            for (t, agent), weight in self._weights.items()
            if t == str(topic) and weight > 0.0
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

## Section 3: Endorsement Listener — Wholesale-Deferred to AD-641b-iv

The original Section 3 introduced a `WardRoomEndorsementListener` to map `WARD_ROOM_ENDORSEMENT` events into `record_contribution` calls. Pass-1 review flagged this as a convention #7 (no theater) violation: ProbOS has no event-bus subscribe API, so the listener would have shipped as a stranded object on `runtime` with no caller. Per the review's recommended fix-option (b), the listener is wholesale-deferred to grandchild AD-641b-iv.

**v1 signal source:** Direct `record_contribution()` invocations from tests and (in future grandchildren) from `WardRoomRouter` integration code at AD-641b-ii. The router is correct and exercisable without the listener.

**Forcing function for AD-641b-iv:** ships when ProbOS introduces a generic event-bus subscribe mechanism (separate AD), OR when the emit-side at `src/probos/ward_room/messages.py:597` (`self._emit(EventType.WARD_ROOM_ENDORSEMENT, {...})`) is modified to call the future listener directly. (AD-641b-iv will introduce the `ward_room_endorsement_listener` runtime attribute and its `handle_event` method.)

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
# AD-641b: Ward Room Hebbian Router (router only; listener deferred to AD-641b-iv)
wr_heb_cfg = getattr(getattr(runtime, "config", None), "ward_room_hebbian", None)
if wr_heb_cfg is not None and wr_heb_cfg.enabled:
    runtime.ward_room_hebbian_router = WardRoomHebbianRouter(
        emit_event=runtime.emit_event,
        learning_rate=wr_heb_cfg.learning_rate,
        decay_factor=wr_heb_cfg.decay_factor,
    )
else:
    runtime.ward_room_hebbian_router = None
```

Anchor by content: insert after the most recent runtime.X attribute assignment in finalize.py. Verify by grep before applying.

---

## Section 6: Tests

**File:** `tests/test_ad641b_ward_room_hebbian.py` (new)

Cover (~11 tests):

1. `test_event_type_ward_room_hebbian_updated_exists`
2. `test_event_type_ward_room_hebbian_decayed_exists`
3. `test_ward_room_hebbian_config_defaults`
4. `test_record_contribution_creates_weight` — new (topic, agent) starts at 0; +1 signal → 0.10.
5. `test_record_contribution_clamped_to_max` — repeated +1 signals saturate at 1.0.
6. `test_record_contribution_clamped_to_min` — −1 signals from 0 stay at 0.0.
7. `test_record_contribution_emits_event` — confirm payload contains topic, agent_id, weight, signal.
8. `test_record_contribution_empty_topic_rejected` — returns 0.0; no weight created.
9. `test_get_weight_unknown_returns_zero`
10. `test_top_contributors_filters_zero_weight_and_sorts_desc` — 4 agents (one with weight=0 after decay simulation), confirm zero-weight entry is filtered (per pass-1 R1) and remaining 3 are sorted desc.
11. `test_decay_modifies_all_weights_and_emits_event`

Listener tests (formerly tests 12/13/14) are wholesale-removed because the listener is deferred to AD-641b-iv (per pass-1 Required #1). They will ship with that grandchild AD.

Per convention #11 — router tests pass real `emit_event` mock; do not over-mock router internals.

---

## What This Does NOT Change (Explicit Scope Boundaries)

1. **Mesh `HebbianRouter`** — not touched. The Ward Room router is a separate instance with separate storage.
2. **`WardRoomRouter` routing logic** — not touched in v1. Routing-priority integration is `AD-641b-ii`.
3. **`TrustNetwork`** — endorsements still flow into trust per existing `record_outcome()` paths. The Hebbian router is intended as an additional consumer of the same signal once integrated, not a replacement.
4. **`WARD_ROOM_ENDORSEMENT` emit path** at `src/probos/ward_room/messages.py:597` — not touched in v1. The listener that would consume those events is deferred to AD-641b-iv.
5. **Persistent storage** — in-memory v1; SQLite backend is `AD-641b-i`.
6. **Decay cadence** — `decay()` is callable; no automatic timer in v1. Operators or a future grandchild AD wire the cadence.

---

## Engineering Principles Compliance

- **Single Responsibility:** Router does math + storage. (Listener will be its own class once AD-641b-iv lands.)
- **Open/Closed:** New signal sources (DM exchanges, thread participation) become additional callers of `record_contribution()` or, post-AD-641b-iv, additional listener subclasses; router unchanged.
- **Dependency Inversion:** Router has no upward dependencies. Future listener will take router as constructor parameter (AD-641b-iv).
- **Law of Demeter:** Router exposes only its public API; consumers do not reach into `_weights`.
- **Fail Fast / Log-and-Degrade:** Emit failures are swallowed (event-emission is not critical to learning correctness).
- **DRY:** Hebbian math is conceptually parallel to the mesh router; storage, instance, and API surface are intentionally distinct per design doc and per the divergence documented in the Solution Overview.

---

## Verification

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad641b_ward_room_hebbian.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_hebbian.py -v -n 0   # mesh router regression
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

---

## Tracking

1. **PROGRESS.md** — Prepend AD-641b CLOSED entry with v1 scope summary (router only — 2 capabilities ship) + 4 deferred grandchildren (i/ii/iii/iv).
2. **DECISIONS.md** — No entry required (parallel-systems pattern documented in design doc; listener defer rationale documented inline in this prompt).
3. **docs/development/roadmap.md** — Update line 7056 AD-641 row reflecting AD-641b CLOSED (router only; listener deferred to grandchild).

---

## Acceptance Criteria

- 11/11 focused tests pass at `-n 0`.
- Full parallel gate non-decreasing.
- `runtime.ward_room_hebbian_router` is a public attribute (or `None` when disabled). The `ward_room_endorsement_listener` attribute is NOT introduced in v1 (deferred to AD-641b-iv).
- 2 new EventTypes are members of `EventType`.
- Mesh `HebbianRouter` instance is unchanged (verified by `tests/test_hebbian.py` regression).
- `WardRoomEndorsementListener` is NOT shipped (deferred to AD-641b-iv); no `listener.py` file under `src/probos/cognitive/ward_room_hebbian/`; no `ward_room_endorsement_listener` attribute is set on the runtime in v1.
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

---

## Revision (2026-05-02)

Pass-1 review verdict was ❌ Not Ready with 1 Required (no-theater violation: listener has no caller) + 2 Recommended + 2 Nits. Revision applies the recommended fix-option (b) from the review (wholesale-defer the listener to AD-641b-iv), plus both Recommended findings.

- **Required #1 — Listener wholesale-deferred to AD-641b-iv** (Required, fix-option (b)): ProbOS has no event-bus subscribe API (`grep -rn "event_log\.subscribe\|register_handler\|add_event_handler\|subscribe_event" src/probos/` returns zero matches), so a listener would have shipped as dead code (convention #7 violation). All listener mentions removed from:
  - **Solution Overview:** dropped the second numbered bullet (listener); v1-deliverables now reads "router only — 2 of 6 capabilities ship", deferred grandchildren count 4 (added AD-641b-iv with explicit forcing function).
  - **Dependencies header:** rewritten to drop the WARD_ROOM_ENDORSEMENT consumer claim and add the divergence note vs mesh `HebbianRouter` API shape.
  - **Section 1 (`__init__.py`):** dropped `WardRoomEndorsementListener` import and `__all__` entry.
  - **Section 3:** former listener implementation block replaced with a "Wholesale-Deferred to AD-641b-iv" stub explaining the v1 signal source (direct `record_contribution()` calls) and the forcing function (event-bus subscribe API or direct emit-side wiring at `messages.py:597`).
  - **Section 5 (startup wiring):** dropped the `ward_room_endorsement_listener` assignment and `else` reset.
  - **Section 6 (tests):** dropped tests 12/13/14 (listener handle_event tests). Test count drops from ~14 to ~11. Pass-1 N1 (`test_listener_rejects_unknown_endorsement_value`) is moot because the listener is deferred — it ships with AD-641b-iv.
  - **What This Does NOT Change:** added explicit boundary line for `WARD_ROOM_ENDORSEMENT` emit path (not modified) and added the listener-defer rationale to boundary item 4.
  - **Engineering Principles Compliance:** dropped the listener-specific bullets; kept router-only principles.
  - **Tracking + Acceptance Criteria:** updated test count to 11; explicitly forbid shipping a `ward_room_endorsement_listener` runtime attribute or a `listener.py` file in v1.
- **R1 — `top_contributors` filters zero-weight** (Recommended): Section 2 router code adds `and weight > 0.0` to the topic-filter comprehension so decayed entries don't surface as ghost contributors. Test 10 description updated to assert the zero-weight filter explicitly.
- **R2 — mesh router API divergence documented** (Recommended): Solution Overview's bullet 1 now states the divergence explicitly: "mesh routes `(source_agent → target_agent)` co-activation while Ward Room routes `(topic → agent)` contribution. Method names differ accordingly (`record_contribution` vs `record_interaction`, `decay` vs `decay_all`); this is documented divergence, not duplication." Verified against `src/probos/mesh/routing.py:39, 96, 188` (mesh `HebbianRouter.record_interaction` and `decay_all`).
- **N2 — float-typed signal kept; calibrated-strength flagged for future** (Nit, judgment-called): Signature stays `signal: float = 1.0` because the listener (where unit-strength clamping would matter) is deferred. Calibrated-strength endorsements ship with AD-641b-iv (or a successor) when the listener lands. No prompt change needed.

Closing self-check (post-revision grep) — see verified-against-codebase footer below.

---

## Verified Against Codebase (2026-05-02 — revision pass)

```
grep -rn "event_log\.subscribe\|register_handler\|add_event_handler\|subscribe_event" src/probos/
  (no matches; confirms no event-bus subscribe API exists today; supports listener defer)

grep -n "def record_interaction\|def decay_all\|def get_weight" src/probos/mesh/routing.py
  96:  def record_interaction(  (mesh router signal-recording API — divergent from Ward Room's record_contribution)
  142: def get_weight(  (signature accepts source/target/rel_type)
  188: def decay_all(self) -> int:  (mesh decay; divergent from Ward Room's decay())
  → confirms documented divergence in Solution Overview is accurate.

grep -n "WARD_ROOM_ENDORSEMENT" src/probos/ward_room/messages.py
  597: self._emit(EventType.WARD_ROOM_ENDORSEMENT, {...})
  → confirms emit-side anchor for AD-641b-iv forcing function.

# Closing self-check — old listener identifiers should NOT appear in revised prompt body:
grep -n "WardRoomEndorsementListener\|ward_room_endorsement_listener\|listener\.py" prompts/ad-641b-ward-room-hebbian.md
  (only appears in Section 3 deferral stub, Required-#1 revision bullet, and acceptance-criteria forbid-line — all intentional)
```
