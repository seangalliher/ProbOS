# AD-722d — Auto-write telemetry events to Ship's Records

**AD:** AD-722d. **GH issue closed:** [#570](https://github.com/seangalliher/ProbOS/issues/570).
**Parent ADs:** AD-722b (WS push channel, Wave 142), AD-722c (telemetry history, this wave), AD-477 (Records as ledger), AD-575 (Records autoseed).
**Wave:** 159. **Estimated tests:** +5 pytest. **Estimated wall-time:** ~1.5h. **Risk:** LOW (additive, throttled, Tier-2 log-and-degrade).

---

## Solution Overview

Significant avatar telemetry events (first-emission divergence today, sustained-block transitions, anomalous-modulation episodes) currently live only in memory + (after AD-722c lands) in JSONL. Ship's Records — the durable narrative ledger backed by git — never sees them. This AD subscribes a writer to `runtime.avatar_event_bus.notify()` and emits a narrative entry to Records when a snapshot crosses a configurable significance threshold.

**Throttle:** issue #570 mandates "max 1 Records entry per agent per hour" — implemented as an in-memory `dict[str, float]` of last-write timestamps. Restart resets the throttle; intentional (Records aren't a metrics store, and a restart-burst of significance lines is signal, not noise).

**Significance vocabulary (v1, 3 events):**
1. `emotion_divergence_high` — `applied_modulation.intent_emotion` set AND a divergence_history entry with `magnitude > divergence_negative_threshold` has just landed for this agent (i.e. the agent's voice diverged sharply from declared intent).
2. `working_state_transition_to_blocked` — current_signals.working_state flipped to `"blocked"` (from any prior state in the previous snapshot for the same agent).
3. `sustained_silence` — `mouth_active=False` AND time since `last_reply_emitted_at > sustained_silence_seconds` (default 1800 = 30 min) for an agent that previously emitted within the last 4 hours.

All three are computed at notify-time from the freshly-built snapshot + a tiny per-agent prior-state cache. Events outside this vocabulary are silently ignored (extensible via config in v2).

**Tier-2 log-and-degrade everywhere.** A Records write failure NEVER blocks the WS publish loop, the agent's reply, or the telemetry history write (AD-722c).

**Folded:** none.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | ~1025 (`AvatarTelemetryConfig`) | Add `records_auto_write_enabled: bool = False` (Captain opt-in — Records writes have audit weight), `records_throttle_seconds: int = 3600`, `records_significant_events: list[str] = ["emotion_divergence_high", "working_state_transition_to_blocked", "sustained_silence"]`, `sustained_silence_seconds: int = 1800`. |
| `src/probos/avatars/records_writer.py` | NEW (~180 lines) | `TelemetryRecordsWriter` class — classify snapshot → significance event names → throttled `RecordsStore.write_entry` call. |
| `src/probos/runtime.py` | ~430 (next to AD-722c construction) | Construct on enabled; pass `records_store` (already on runtime). |
| `src/probos/routers/agents.py` | ~707 + ~737 (publish loop) | Tier-2 best-effort `await writer.observe(snap, prior_snap)` after history append. |
| `tests/test_ad722d_records_auto_write.py` | NEW | 5 boundary tests. |

Live grep confirms:
- `runtime._records_store` set in `runtime.py:1528` from `cog.records_store`; public property `runtime.records_store` at `runtime.py:1131`.
- `RecordsStore.write_entry(author, path, content, message, classification="ship", ...)` signature at `records_store.py:90`.
- `runtime.avatar_event_bus.notify()` is the wake-trigger called from `cognitive_agent.py:1737` and elsewhere — but for THIS AD we don't subscribe to the event bus directly; we hook the publish-loop's existing per-frame `snap` (cheaper and gives us prior-snapshot for transition detection).

---

## Section 1 — `AvatarTelemetryConfig` fields

In `src/probos/config.py`, in `AvatarTelemetryConfig` (around line 1025), add after the AD-722c history fields:

```python
    # AD-722d: auto-write significant telemetry events to Ship's Records.
    # Default OFF — Records is a durable git-backed ledger; the Captain
    # opts in. v1 vocabulary covers three event names; unknown event
    # names in records_significant_events are silently ignored.
    records_auto_write_enabled: bool = False
    records_throttle_seconds: int = 3600           # max 1 Records entry per agent per hour
    records_significant_events: list[str] = Field(
        default_factory=lambda: [
            "emotion_divergence_high",
            "working_state_transition_to_blocked",
            "sustained_silence",
        ],
    )
    sustained_silence_seconds: int = 1800          # 30 min
```

Add a `field_validator` bounding `records_throttle_seconds >= 1` and `sustained_silence_seconds >= 60`. Use `Field(default_factory=lambda: [...])` for the list — bare list defaults trip Pydantic's mutable-default trap (review-criteria.md anti-pattern).

---

## Section 2 — `TelemetryRecordsWriter` module (NEW)

Create `src/probos/avatars/records_writer.py`. Two classes:

(a) `_PriorStateCache` — `dict[str, AvatarTelemetrySnapshot | None]` keyed by agent_id. Last seen snapshot per agent. Used by `_classify` to detect transitions.

(b) `TelemetryRecordsWriter` — observes snapshots, classifies into a (possibly empty) set of significance event names from the configured vocabulary, applies per-agent throttle, and dispatches `RecordsStore.write_entry`.

```python
"""AD-722d: auto-write significant avatar telemetry events to Ship's Records.

Hooks the WS publish loop. Tier-2 — never raises out of public methods.
Throttle window is per-agent (default 1 hr); enforced via an in-memory
dict of last-write timestamps. Restart resets — intentional, see AD doc.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.avatars.telemetry import AvatarTelemetrySnapshot
    from probos.knowledge.records_store import RecordsStore

logger = logging.getLogger(__name__)

# v1 vocabulary; classify() returns a subset of these. Unknown names in
# config.records_significant_events are silently dropped at classify-time.
EVENT_EMOTION_DIVERGENCE_HIGH = "emotion_divergence_high"
EVENT_WORKING_STATE_TO_BLOCKED = "working_state_transition_to_blocked"
EVENT_SUSTAINED_SILENCE = "sustained_silence"

KNOWN_EVENTS: frozenset[str] = frozenset({
    EVENT_EMOTION_DIVERGENCE_HIGH,
    EVENT_WORKING_STATE_TO_BLOCKED,
    EVENT_SUSTAINED_SILENCE,
})


class TelemetryRecordsWriter:
    def __init__(
        self,
        *,
        records_store: "RecordsStore",
        runtime: Any,
        throttle_seconds: int,
        significant_events: list[str],
        sustained_silence_seconds: int,
        divergence_threshold: float,
    ) -> None:
        self._records = records_store
        self._runtime = runtime
        self._throttle_s = max(1, int(throttle_seconds))
        self._silence_s = max(60, int(sustained_silence_seconds))
        self._div_threshold = float(divergence_threshold)
        # Subset of v1 vocabulary the operator opted into. Unknown names dropped.
        self._enabled_events: frozenset[str] = frozenset(
            e for e in significant_events if e in KNOWN_EVENTS
        )
        self._prior: dict[str, "AvatarTelemetrySnapshot"] = {}
        # Parallel per-agent prior divergence magnitude. Required because
        # AvatarTelemetrySnapshot is a frozen dataclass and cannot carry
        # writer-side state. Used by _classify to detect FRESH divergence.
        self._prior_div_mag: dict[str, float] = {}
        self._last_write: dict[str, float] = {}

    async def observe(self, snap: "AvatarTelemetrySnapshot") -> None:
        """Classify + maybe write. Tier-2 — never raises."""
        try:
            events = self._classify(snap)
            prior = self._prior.get(snap.agent_id)
            # ALWAYS update prior, even if no events fire — needed for
            # accurate next-frame transition detection.
            self._prior[snap.agent_id] = snap
            if not events:
                return
            now = time.time()
            last = self._last_write.get(snap.agent_id, 0.0)
            if (now - last) < self._throttle_s:
                logger.debug(
                    "AD-722d: throttled for agent=%s (events=%s)",
                    snap.agent_id, sorted(events),
                )
                return
            # Pick highest-signal event (emotion_divergence > blocked > silence).
            event = self._pick_priority(events)
            await self._write(snap, prior, event)
            self._last_write[snap.agent_id] = now
        except Exception:
            logger.warning(
                "AD-722d: observe failed for agent=%s",
                getattr(snap, "agent_id", "?"), exc_info=True,
            )

    def _classify(self, snap: "AvatarTelemetrySnapshot") -> set[str]:
        out: set[str] = set()
        prior = self._prior.get(snap.agent_id)

        # 1. emotion_divergence_high — read divergence_history latest entry.
        # FRESH divergence is detected against self._prior_div_mag (parallel
        # per-agent dict, NOT a field on the frozen snapshot).
        if EVENT_EMOTION_DIVERGENCE_HIGH in self._enabled_events:
            dr = getattr(self._runtime, "divergence_results", None)
            if dr is not None:
                latest = dr.get(snap.agent_id)
                if latest is not None and getattr(latest, "magnitude", 0.0) > self._div_threshold:
                    prior_mag = self._prior_div_mag.get(snap.agent_id, 0.0)
                    if latest.magnitude > prior_mag + 0.01:  # epsilon — only fresh rises
                        out.add(EVENT_EMOTION_DIVERGENCE_HIGH)
                    # ALWAYS update prior_div_mag so next frame compares against
                    # the latest observed magnitude (not a stale baseline).
                    self._prior_div_mag[snap.agent_id] = float(latest.magnitude)

        # 2. working_state transition to blocked.
        if EVENT_WORKING_STATE_TO_BLOCKED in self._enabled_events and prior is not None:
            prior_ws = getattr(prior.current_signals, "working_state", None)
            now_ws = getattr(snap.current_signals, "working_state", None)
            if now_ws == "blocked" and prior_ws != "blocked":
                out.add(EVENT_WORKING_STATE_TO_BLOCKED)

        # 3. sustained_silence — mouth_active False AND a real prior reply existed.
        if EVENT_SUSTAINED_SILENCE in self._enabled_events:
            registry = getattr(self._runtime, "registry", None)
            agent = registry.get(snap.agent_id) if registry is not None else None
            last_reply = getattr(agent, "last_reply_emitted_at", 0.0) or 0.0
            if last_reply > 0 and not snap.mouth_active:
                gap = time.time() - last_reply
                if self._silence_s <= gap <= 4 * 3600:
                    # Don't repeat-fire — only fire once per silence period
                    # (subsequent observations within the same silence stay
                    # in this gap window; the throttle handles re-fire).
                    out.add(EVENT_SUSTAINED_SILENCE)
        return out

    @staticmethod
    def _pick_priority(events: set[str]) -> str:
        # Stable priority — divergence beats blocked beats silence.
        for candidate in (
            EVENT_EMOTION_DIVERGENCE_HIGH,
            EVENT_WORKING_STATE_TO_BLOCKED,
            EVENT_SUSTAINED_SILENCE,
        ):
            if candidate in events:
                return candidate
        # Defensive: ordered set guarantees at least one element.
        return next(iter(events))

    async def _write(
        self,
        snap: "AvatarTelemetrySnapshot",
        prior: "AvatarTelemetrySnapshot | None",
        event: str,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        clock = now_iso.split("T", 1)[-1][:5]  # "HH:MM"
        if event == EVENT_EMOTION_DIVERGENCE_HIGH:
            dr = getattr(self._runtime, "divergence_results", None)
            latest = dr.get(snap.agent_id) if dr is not None else None
            mag = getattr(latest, "magnitude", 0.0) if latest is not None else 0.0
            emotion = getattr(latest, "intent_emotion", "?") if latest is not None else "?"
            narrative = (
                f"At {clock}, voice modulation diverged from declared "
                f"emotion '{emotion}' (magnitude {mag:.2f})."
            )
        elif event == EVENT_WORKING_STATE_TO_BLOCKED:
            narrative = (
                f"At {clock}, working state transitioned to 'blocked'."
            )
        else:  # sustained_silence
            narrative = (
                f"At {clock}, sustained silence observed "
                f"(no reply emitted in > {self._silence_s // 60} minutes)."
            )
        path = (
            f"notebooks/{snap.agent_id}/telemetry-events-"
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
        )
        content = f"- [{now_iso}] [{event}] {narrative}\n"
        try:
            await self._records.write_entry(
                author=snap.agent_id,
                path=path,
                content=content,
                message=f"telemetry: {event}",
                classification="ship",
                topic="avatar-telemetry",
                tags=["telemetry", event],
            )
        except Exception:
            logger.warning(
                "AD-722d: RecordsStore write failed for agent=%s event=%s",
                snap.agent_id, event, exc_info=True,
            )
```

---

## Section 3 — Runtime construction

In `src/probos/runtime.py`, near the AD-722c construction block, add:

```python
        # AD-722d: significance-event Records writer. Gated independently
        # so the Captain can have history (AD-722c) without the Records
        # ledger write surface. Records store is wired later — guard on
        # availability at construction time.
        self.avatar_telemetry_records_writer = None
        if (
            getattr(self.config, "avatar_telemetry", None) is not None
            and self.config.avatar_telemetry.enabled
            and self.config.avatar_telemetry.records_auto_write_enabled
        ):
            # Defer to a setter — records_store is wired in Phase 4 (see
            # runtime.py:1528). Set None now; populate in a finalize hook.
            self.avatar_telemetry_records_writer = None  # filled in finalize
```

Then, find the finalize phase that assigns `self._records_store = cog.records_store` (around `runtime.py:1528`) and immediately after, add:

```python
        # AD-722d: instantiate the writer once records_store is available.
        if (
            getattr(self.config, "avatar_telemetry", None) is not None
            and self.config.avatar_telemetry.enabled
            and self.config.avatar_telemetry.records_auto_write_enabled
            and self._records_store is not None
        ):
            from probos.avatars.records_writer import TelemetryRecordsWriter
            self.avatar_telemetry_records_writer = TelemetryRecordsWriter(
                records_store=self._records_store,
                runtime=self,
                throttle_seconds=self.config.avatar_telemetry.records_throttle_seconds,
                significant_events=self.config.avatar_telemetry.records_significant_events,
                sustained_silence_seconds=self.config.avatar_telemetry.sustained_silence_seconds,
                divergence_threshold=self.config.avatar_telemetry.divergence_negative_threshold,
            )
```

(Two-phase wiring is necessary because Phase 4 builds the records store while the WS publish loop's hasattr-guard wants the attribute to exist at construction time. Both phases use the same attribute name; default of `None` keeps the Tier-2 read clean.)

---

## Section 4 — Wire into WS publish loop

In `src/probos/routers/agents.py:_publish_loop` (around line 737, AFTER the AD-722c history-append block from the AD-722c prompt), add:

```python
                _rw = getattr(runtime, "avatar_telemetry_records_writer", None)
                if _rw is not None:
                    try:
                        await _rw.observe(snap)
                    except Exception:
                        logger.debug(
                            "AD-722d: records writer raised in publish loop",
                            exc_info=True,
                        )
```

Apply the same 3-line guard inside the `initial` snapshot block (around line 707), so first-frame events also get classified.

**Ordering:** AD-722d hook MUST go after AD-722c history-append so a Records write failure can't disrupt JSONL persistence. If AD-722c lands first in the wave (it should — lower commit number), the AD-722d Builder will apply this section relative to the AD-722c block.

---

## Test plan (boundary tests)

Create `tests/test_ad722d_records_auto_write.py` with 5 tests:

1. `test_observe_writes_on_emotion_divergence_high` — seed `runtime.divergence_results` with magnitude > threshold; call `observe(snap)` twice (second call with same magnitude must NOT re-fire) → exactly one `write_entry` call.
2. `test_observe_writes_on_working_state_transition_to_blocked` — feed two snapshots: first with `working_state="responding"`, second with `working_state="blocked"` → exactly one write on second observe.
3. `test_observe_throttles_within_window` — fire two distinct high-signal events within `throttle_seconds=10` → exactly one write.
4. `test_observe_unknown_event_name_in_config_silently_dropped` — config with `records_significant_events=["bogus_event"]` → zero writes even on divergence.
5. `test_observe_swallows_records_failure` — mock `RecordsStore.write_entry` to raise → `observe()` returns normally, no exception bubbles.

Use a `_FakeRecordsStore` stub with an async `write_entry` that records call args in a list. No real RecordsStore initialization (avoid git subprocess). No UI test.

---

## What this does NOT change

- The 3 named events are the v1 vocabulary; no machinery for operator-defined event classifiers (forward marker AD-722d-1).
- The Records folder structure (`notebooks/<agent>/telemetry-events-YYYY-MM-DD.md`).
- The git commit cadence (`RecordsStore` already auto-commits per its config).
- AD-722c history JSONL — orthogonal.
- WS frame shape — unchanged.
- `prompts/BUILDER-EXECUTION-PLAN.md` — not edited in this prompt.

---

## Verification commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad722d_records_auto_write.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

No UI changes — `npm run build` not required.

---

## Tracker updates

- `PROGRESS.md` — append closure line with test count delta.
- `docs/development/roadmap.md` — mark #570 closed; add AD-722d-1 forward marker (operator-defined significance event classifiers).
- `DECISIONS.md` — append AD-722d entry; document the throttle-resets-on-restart choice and the two-phase finalize wiring pattern.

Commit message:
```
AD-722d: significance-event auto-write to Ship's Records

Closes #570
```

---

## License Disposition

**All-internal Apache 2.0.** No new pip deps (stdlib only). No new npm deps. No model weights, no binaries. Records writes route through the existing `RecordsStore` (git subprocess via the same path as AD-575 ship-records — no new external tooling).

---

## Forward markers

- **AD-722d-1** — operator-defined event classifiers (`SignificanceClassifier` Protocol + plugin registry); trigger: Captain wants per-agent custom event names (e.g. Worf's "threat_perception_active").
- **AD-722d-2** — Records-side dedup/aggregation (collapse identical events within N hours into one entry with a count); trigger: telemetry-heavy operator finds the daily notebook noisy.

---

## Acceptance criteria

- All 5 new tests pass under `-n 0`.
- Full gate green.
- Records writes are throttled per-agent (verified by test #3).
- Writer NEVER raises out of `observe()` (verified by test #5).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
grep -n "class AvatarTelemetryConfig" src/probos/config.py
  1025: class AvatarTelemetryConfig(BaseModel):

grep -n "class RecordsStore" src/probos/knowledge/records_store.py
  47: class RecordsStore:

grep -n "async def write_entry" src/probos/knowledge/records_store.py
  90:     async def write_entry(

grep -n "self._records_store = cog.records_store" src/probos/runtime.py
  1528:         self._records_store = cog.records_store

grep -n "divergence_results" src/probos/routers/agents.py
  1377:         _dr = getattr(runtime, "divergence_results", None)

grep -n "last_reply_emitted_at" src/probos/avatars/telemetry.py
  (mouth_active derives from this — class doc at line 346-350)
```

---

## Revision (2026-05-14)

**Pass 1 review:** prompts/Reviews/ad-722d-records-auto-write-review.md — Verdict ⚠️ Conditional. One Required finding.

**Applied:**
- **Required #1 (Section 2 sketched-then-corrected `_classify` body)**: collapsed the broken sketch and the trailing "Design note" paragraph into a single canonical implementation. `__init__` now declares `self._prior_div_mag: dict[str, float] = {}` alongside `self._prior`. `_classify` reads `prior_mag = self._prior_div_mag.get(snap.agent_id, 0.0)` directly (no more `getattr(prior, '_last_div_mag', ...)` against a frozen dataclass) and ALWAYS updates `self._prior_div_mag[snap.agent_id]` whenever a fresh `divergence_results` entry exists for the agent — so subsequent frames compare against the latest observed magnitude, not a stale baseline. The trailing "Builder MUST use the parallel-dict version" paragraph is removed; the body is now the only version.

**Deferred (Recommended, not blocking):**
- Recommended #1 (drop the `_pick_priority` defensive `next(iter(events))` fallback) — left as-is; the defensive branch is unreachable but cheap and self-documenting.
- Recommended #2 (per-(agent, event) throttle instead of per-agent) — intentional per issue #570; documented in the existing DECISIONS-entry plan.
- Recommended #3 (4-hour silence upper bound rationale) — Builder may add a one-line code comment at apply time; not architecturally load-bearing.

**Self-check:** `_last_div_mag` is no longer referenced in the prompt body (sketch retired); confirmed by grep below.
