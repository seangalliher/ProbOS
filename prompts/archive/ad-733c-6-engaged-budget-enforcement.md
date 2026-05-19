# AD-733c-6 — Engaged-mode LLM call budget enforcement

**Wave:** 175
**Closes:** #677
**Status:** drafting → GATE 1
**Dependencies:** AD-742e (`_record_vision_call`, `get_budget_snapshot`,
`/api/perception/budget` shipped Wave 174), AD-733c-2
(`PerceptionModeController.transition_to`), BF-308 (hot-reload setters).
**Estimated tests:** +9 pytest, +3 vitest.
**License posture:** 0-line diff (no new deps).

---

## Problem

AD-742e ships **telemetry only** — per-tier vision LLM call counters,
session/UTC reset, `/api/perception/budget` endpoint, HXI badge with a
heuristic ceiling (`proactive_max_emissions × 40`). There is no
**enforcement**: a runaway ENGAGED-mode session can call the vision LLM
hundreds of times in an hour with no automatic brake. Captain's idle
drop-back (AD-733c-4) catches lack-of-activity but not over-activity.

## Solution

Add per-session and per-day soft caps with auto-drop ENGAGED → AMBIENT on
cap hit. Reuses the shipped pieces:

- AD-742e counters (`_budget_calls_session`, `_budget_calls_today`)
- AD-733c-2 `PerceptionModeController.transition_to(Mode.AMBIENT,
  trigger="budget_exhausted")`
- AD-742e `/api/perception/budget` endpoint (snapshot gains `cap` +
  `cap_reached` fields)
- HXI `VisionBudgetBadge` (replaces heuristic ceiling with configured cap;
  shows orange at >80%, red at ≥100%)

Defaults:

- `engaged_call_cap_per_session: int = 200` (Captain's typical session is
  ~50-100 vision calls based on AD-742e baseline data)
- `engaged_call_cap_per_day: int = 2000`
- `engaged_budget_enforcement: bool = True` (opt-out flag)

Cap values are **hot-reload** (operator dials mid-session); enforcement
on/off is hot-reload too. The mode controller transition itself is
synchronous and called from inside `_describe_lock` — safe (no async
acquisition, no callback re-entry).

---

## Section 0: Configuration (additive, hot-reload)

### File: `src/probos/config.py`

Add to `PerceptionConfig` (anchor after `proactive_novelty_threshold` at
line ~2065):

```
===SEARCH===
    proactive_novelty_threshold: float = Field(default=0.50, ge=0.0, le=1.0,
        description="Minimum novelty score for a high-novelty proactive trigger (separate from supervisor admission threshold).",
    )


class LipSyncConfig(BaseModel):
===REPLACE===
    proactive_novelty_threshold: float = Field(default=0.50, ge=0.0, le=1.0,
        description="Minimum novelty score for a high-novelty proactive trigger (separate from supervisor admission threshold).",
    )

    # AD-733c-6 (Wave 175): engaged-mode vision LLM call budget.
    # AD-742e ships the counters; this section ships the enforcement.
    engaged_budget_enforcement: bool = Field(default=True,
        description="AD-733c-6: when True, exceeding the per-session or per-day vision call cap in ENGAGED mode auto-drops to AMBIENT. False = counters-only behavior (AD-742e baseline).",
    )
    engaged_call_cap_per_session: int = Field(default=200, ge=10, le=10000,
        description="AD-733c-6: vision LLM calls per session in ENGAGED mode before auto-drop to AMBIENT. Captain default 200; tune via Settings or BF-308 hot-reload.",
    )
    engaged_call_cap_per_day: int = Field(default=2000, ge=50, le=100000,
        description="AD-733c-6: vision LLM calls per UTC day before auto-drop to AMBIENT. Captain default 2000.",
    )
===END REPLACE===
```

> If AD-742d's prompt already inserted its validator immediately before
> `class LipSyncConfig`, this SEARCH still matches because the anchor is
> on `proactive_novelty_threshold`. Builder applies AD-742d first → the
> validator is between the new fields and `LipSyncConfig`. Re-target the
> REPLACE block tail to land BEFORE the validator if needed.

### File: `src/probos/perception/__init__.py`

Append three FieldDescriptors (all hot-reload per BF-308 posture for cap
values):

```
===SEARCH===
        FieldDescriptor(
            "perception.vision_baseline_max_age_seconds",
            "Baseline refresh window (s)",
            "float",
            description="BF-309: after this many seconds with no admit, re-baseline on the next frame. Prevents static-scene lock-up. 30s default. 0 = disable.",
            hot_reload=True,
        ),
===REPLACE===
        FieldDescriptor(
            "perception.vision_baseline_max_age_seconds",
            "Baseline refresh window (s)",
            "float",
            description="BF-309: after this many seconds with no admit, re-baseline on the next frame. Prevents static-scene lock-up. 30s default. 0 = disable.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.engaged_budget_enforcement",
            "Engaged budget enforcement",
            "bool",
            description="AD-733c-6: auto-drop ENGAGED→AMBIENT when cap reached. Hot-reload.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.engaged_call_cap_per_session",
            "Engaged calls/session cap",
            "int",
            description="AD-733c-6: vision LLM calls per session in ENGAGED before auto-drop. Default 200.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.engaged_call_cap_per_day",
            "Engaged calls/day cap",
            "int",
            description="AD-733c-6: vision LLM calls per UTC day before auto-drop. Default 2000.",
            hot_reload=True,
        ),
===END REPLACE===
```

> If AD-742d / AD-742f's prompts inserted FieldDescriptors at the same
> anchor, keep all inserts — Builder is responsible for merging.

---

## Section 1: Mode controller — accept budget trigger

### File: `src/probos/perception/mode_controller.py`

`transition_to` already accepts an arbitrary `trigger` string. The
existing `Transition.trigger` docstring lists known triggers; extend it
to enumerate `"budget_exhausted"` so future readers find the AD:

```
===SEARCH===
@dataclass
class Transition:
    """One row in the transition history ring buffer."""
    at: float
    from_mode: Mode
    to_mode: Mode
    trigger: str  # "init" | "dm_activity" | "wake_word" | "novelty" | "idle_timer" | "manual"
===REPLACE===
@dataclass
class Transition:
    """One row in the transition history ring buffer."""
    at: float
    from_mode: Mode
    to_mode: Mode
    trigger: str  # "init" | "dm_activity" | "wake_word" | "novelty" |
                  # "idle_timer" | "manual" | "budget_exhausted" (AD-733c-6)
===END REPLACE===
```

No other mode_controller code changes — `transition_to` accepts arbitrary
trigger strings; the budget path uses it directly.

---

## Section 2: Consumer — cap check + auto-drop

### File: `src/probos/perception/consumer.py`

Replace `_record_vision_call` to (a) increment as today, (b) snapshot cap
state, (c) on cap-hit AND enforcement-on AND mode==ENGAGED, call
`controller.transition_to(Mode.AMBIENT, trigger="budget_exhausted")` and
log INFO (rate-limited per session).

```
===SEARCH===
    def _record_vision_call(self, tier: str, session_id: str) -> None:
        """AD-742e: record one vision LLM call against the budget counters."""
        import time as _time
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if session_id != self._budget_current_session_id:
            self._budget_current_session_id = session_id
            self._budget_calls_session = {"vision": 0, "vision_fast": 0}
        if today != self._budget_current_date:
            self._budget_current_date = today
            self._budget_calls_today = {"vision": 0, "vision_fast": 0}
        if tier not in self._budget_calls_session:
            self._budget_calls_session[tier] = 0
            self._budget_calls_today[tier] = 0
        self._budget_calls_session[tier] += 1
        self._budget_calls_today[tier] += 1
        self._budget_last_call_at = _time.monotonic()
===REPLACE===
    def _record_vision_call(self, tier: str, session_id: str) -> None:
        """AD-742e: record one vision LLM call. AD-733c-6: enforce cap."""
        import time as _time
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if session_id != self._budget_current_session_id:
            self._budget_current_session_id = session_id
            self._budget_calls_session = {"vision": 0, "vision_fast": 0}
            # AD-733c-6: clear the "we've already notified" flag so the
            # cap-hit log fires once per session, not once per process.
            self._budget_cap_notified_sessions.discard(session_id)
        if today != self._budget_current_date:
            self._budget_current_date = today
            self._budget_calls_today = {"vision": 0, "vision_fast": 0}
        if tier not in self._budget_calls_session:
            self._budget_calls_session[tier] = 0
            self._budget_calls_today[tier] = 0
        self._budget_calls_session[tier] += 1
        self._budget_calls_today[tier] += 1
        self._budget_last_call_at = _time.monotonic()
        # AD-733c-6: cap-check + auto-drop. Defense-in-depth: if any piece
        # of the path is missing (config, controller), silently skip — the
        # counters still work (AD-742e behavior preserved).
        self._maybe_enforce_budget(session_id)

    def _maybe_enforce_budget(self, session_id: str) -> None:
        """AD-733c-6: drop to AMBIENT when cap exceeded in ENGAGED mode."""
        cfg = getattr(getattr(self._runtime, "config", None), "perception", None)
        if cfg is None or not getattr(cfg, "engaged_budget_enforcement", True):
            return
        controller = getattr(self._runtime, "perception_mode_controller", None)
        if controller is None:
            return
        # Late-import the enum so module-load order doesn't trip us.
        from probos.perception.mode_controller import Mode as _Mode
        if controller.current_mode is not _Mode.ENGAGED:
            return
        cap_session = int(getattr(cfg, "engaged_call_cap_per_session", 200))
        cap_day = int(getattr(cfg, "engaged_call_cap_per_day", 2000))
        total_session = sum(self._budget_calls_session.values())
        total_today = sum(self._budget_calls_today.values())
        if total_session < cap_session and total_today < cap_day:
            return
        # Cap hit. Transition synchronously (mode_controller.transition_to
        # is sync; safe to call while holding describe_lock — no async
        # acquisition, no re-entry).
        reason = "session" if total_session >= cap_session else "day"
        try:
            controller.transition_to(_Mode.AMBIENT, trigger="budget_exhausted")
        except Exception:
            logger.warning(
                "AD-733c-6: budget-exhausted transition failed (cap=%s)",
                reason, exc_info=True,
            )
            return
        # Rate-limited operator-visible notification — once per session.
        if session_id and session_id not in self._budget_cap_notified_sessions:
            self._budget_cap_notified_sessions.add(session_id)
            logger.warning(
                "AD-733c-6: vision LLM %s cap reached (session=%d/%d, "
                "day=%d/%d); ENGAGED -> AMBIENT auto-drop",
                reason,
                total_session, cap_session,
                total_today, cap_day,
            )
===END REPLACE===
```

Add the notification-set initializer alongside the existing AD-742e state
(anchor: the `_budget_last_call_at = None` block in `__init__`):

```
===SEARCH===
        self._budget_current_session_id: str = ""
        self._budget_current_date: str = ""  # YYYY-MM-DD UTC
        self._budget_last_call_at: float | None = None
        self._sessions_with_observations: set[str] = set()
===REPLACE===
        self._budget_current_session_id: str = ""
        self._budget_current_date: str = ""  # YYYY-MM-DD UTC
        self._budget_last_call_at: float | None = None
        # AD-733c-6: per-session set so the cap-hit WARNING + WardRoom-class
        # log fires once per session, not once per ENGAGED call past the cap.
        self._budget_cap_notified_sessions: set[str] = set()
        self._sessions_with_observations: set[str] = set()
===END REPLACE===
```

---

## Section 3: Budget snapshot — surface caps + cap_reached

### File: `src/probos/perception/consumer.py`

Replace `get_budget_snapshot` to emit the configured caps + `cap_reached`
flag. The HXI badge reads this directly.

```
===SEARCH===
    def get_budget_snapshot(self) -> dict[str, Any]:
        """AD-742e: structured snapshot for /api/perception/budget."""
        import time as _time
        next_allowed_in: float = 0.0
        if self._budget_last_call_at is not None:
            # Heuristic: use the configured vision_min_interval_seconds floor
            # as a proxy for "when's the next describe likely allowed?" — the
            # supervisor enforces the actual cadence; this is informational.
            cfg_perception = getattr(self._runtime.config, "perception", None)
            min_interval = (
                float(getattr(cfg_perception, "vision_min_interval_seconds", 3.0))
                if cfg_perception is not None
                else 3.0
            )
            elapsed = _time.monotonic() - self._budget_last_call_at
            next_allowed_in = max(0.0, min_interval - elapsed)
        ceiling = 0
        # session ceiling = proactive_max_emissions * 40 (heuristic — actual
        # ceiling is a function of session duration which isn't known here).
        cfg = getattr(self._runtime.config, "perception", None)
        if cfg is not None:
            ceiling = int(getattr(cfg, "proactive_max_emissions", 3)) * 40
        return {
            "session_id": self._budget_current_session_id,
            "calls_this_session": dict(self._budget_calls_session),
            "calls_today": dict(self._budget_calls_today),
            "total_session": sum(self._budget_calls_session.values()),
            "total_today": sum(self._budget_calls_today.values()),
            "session_ceiling_estimate": ceiling,
            "next_allowed_in_seconds": round(next_allowed_in, 2),
        }
===REPLACE===
    def get_budget_snapshot(self) -> dict[str, Any]:
        """AD-742e + AD-733c-6: snapshot for /api/perception/budget."""
        import time as _time
        next_allowed_in: float = 0.0
        cfg = getattr(getattr(self._runtime, "config", None), "perception", None)
        if self._budget_last_call_at is not None:
            min_interval = (
                float(getattr(cfg, "vision_min_interval_seconds", 3.0))
                if cfg is not None
                else 3.0
            )
            elapsed = _time.monotonic() - self._budget_last_call_at
            next_allowed_in = max(0.0, min_interval - elapsed)
        # AD-733c-6: configured caps (replace AD-742e heuristic ceiling).
        cap_session = int(getattr(cfg, "engaged_call_cap_per_session", 200)) if cfg else 200
        cap_day = int(getattr(cfg, "engaged_call_cap_per_day", 2000)) if cfg else 2000
        enforcement = bool(getattr(cfg, "engaged_budget_enforcement", True)) if cfg else True
        # Backwards-compat: keep session_ceiling_estimate for any caller
        # that hasn't migrated to the new cap field. Map to cap_session.
        ceiling = cap_session
        total_session = sum(self._budget_calls_session.values())
        total_today = sum(self._budget_calls_today.values())
        return {
            "session_id": self._budget_current_session_id,
            "calls_this_session": dict(self._budget_calls_session),
            "calls_today": dict(self._budget_calls_today),
            "total_session": total_session,
            "total_today": total_today,
            "session_ceiling_estimate": ceiling,  # AD-742e backcompat
            "cap_per_session": cap_session,
            "cap_per_day": cap_day,
            "enforcement_enabled": enforcement,
            "cap_reached_session": total_session >= cap_session,
            "cap_reached_day": total_today >= cap_day,
            "next_allowed_in_seconds": round(next_allowed_in, 2),
        }
===END REPLACE===
```

---

## Section 4: HXI badge — use configured cap

### File: `ui/src/perception/VisionBudgetBadge.tsx` (modify; AD-742e shipped this)

Read the new `cap_per_session` + `cap_reached_session` fields. Color:
green <80%, orange 80–99%, red ≥100%. When `enforcement_enabled=false`,
still show the percentage but in dim color (no enforcement → no alarm
state).

Builder: read the existing AD-742e badge component first, then mirror the
new logic. Snapshot of expected change:

- Replace `session_ceiling_estimate` reference with `cap_per_session`.
- Add `cap_reached_session` boolean from snapshot.
- Compute `pct = total_session / cap_per_session` (guard cap > 0).
- Apply `color = pct >= 1.0 ? "rgb(220,80,80)" : pct >= 0.8 ? "rgb(220,160,60)" : "rgb(80,180,120)"`.
- When `!enforcement_enabled`, override to dim (`rgb(100,100,120)`).
- HXI Principle #3: SVG glyphs only, no emoji. The AD-742e badge already
  uses a stroke-circle glyph; reuse it.

> Concrete SEARCH/REPLACE deferred to the Builder so the exact AD-742e
> component shape is matched at HEAD time. The Builder applies a
> single-pass edit + adds 3 vitest cases (see Section 5).

---

## Section 5: Tests

### New file: `tests/test_ad733c6_engaged_budget_enforcement.py`

Real `VisionConsumer` over a stub runtime (real `SystemConfig`, real
`PerceptionModeController`). BF-287 — no MagicMock at the substrate
boundary.

1. `test_under_cap_no_transition` — set caps to (100/1000), ENGAGED mode,
   record 50 calls, assert mode stays ENGAGED, no WARNING logged.
2. `test_session_cap_hit_drops_to_ambient` — set cap_per_session=5,
   ENGAGED mode, record 5 calls, assert mode==AMBIENT after the 5th, and
   transition history's last entry has `trigger="budget_exhausted"`.
3. `test_day_cap_hit_drops_to_ambient` — set cap_per_session=999,
   cap_per_day=3, record 3 calls, assert AMBIENT + trigger.
4. `test_enforcement_disabled_no_transition` — set
   `engaged_budget_enforcement=False`, cap_per_session=5, record 10 calls,
   assert mode stays ENGAGED.
5. `test_ambient_mode_no_transition` — mode==AMBIENT, record past cap,
   assert no transition attempted (no infinite loop).
6. `test_cap_notification_rate_limited_per_session` — cap_per_session=2,
   ENGAGED, record 5 calls, assert exactly ONE WARNING log line matching
   `"AD-733c-6"` (use `caplog.records` filter).
7. `test_session_change_resets_notification_flag` — session A hits cap +
   notifies once; switch to session B; session B hits cap; assert a SECOND
   WARNING fires for session B.
8. `test_snapshot_exposes_caps_and_cap_reached` — call
   `get_budget_snapshot`, assert keys `cap_per_session`, `cap_per_day`,
   `cap_reached_session`, `cap_reached_day`, `enforcement_enabled` all
   present with correct values.
9. `test_hot_reload_cap_change_takes_effect` — start with cap=100, record
   50 calls, mutate `cfg.engaged_call_cap_per_session=10`, record 1 more
   call, assert mode==AMBIENT (the new cap is honored on the very next
   call, no controller re-init required).

### New vitest in `ui/src/perception/VisionBudgetBadge.test.tsx` (extend AD-742e tests)

10. `renders orange when total_session / cap >= 0.8`
11. `renders red when cap_reached_session is true`
12. `renders dim when enforcement_enabled is false`

### Acceptance:

- `pytest tests/test_ad733c6_engaged_budget_enforcement.py -v -n 0` → 9 passed.
- `cd ui && npx vitest run src/perception/VisionBudgetBadge.test.tsx` → all green.
- BF-279 UI gate: `cd ui && npm run build` — must succeed (catches stale-
  bundle / JSX-element-resolve regressions).

---

## What this does NOT change

- AD-742e counter semantics — `_record_vision_call` still increments
  per-tier; the new path is additive after the existing increment.
- `/api/perception/budget` URL or auth — same route, additive fields.
- AD-733c-2 mode-transition cooldown — `budget_exhausted` is treated as a
  non-manual transition, subject to the `PROGRAMMATIC_COOLDOWN_S = 1.0`
  floor. In practice this is fine: post-cap describes are throttled by
  `_describe_lock` + supervisor anyway.
- AD-733c-4 idle drop-back — independent path; both can fire.
- WardRoom message posting — out of scope. The WARNING log + the budget
  endpoint + the HXI badge color shift constitute the operator-facing
  notification surface. Future enhancement = AD-733c-6-2 forward marker.

## Forward markers

- **AD-733c-6-1** — Persist daily aggregate across restarts (`data/perception_budget.db`).
  Today the day counter resets on process restart. Not critical because the
  cap is 2000/day and Captain rarely restarts mid-day; nevertheless filed
  for completeness.
- **AD-733c-6-2** — WardRoom "Budget reached" message post on cap-hit.
  Today the WARNING log + HXI badge red state are the surface. Surfacing
  in the WardRoom feed gives Captain an in-conversation breadcrumb.

File both as GitHub issues at wave close.

---

## AD-722c-3 forward-marker triggers

None new.

## License posture

0-line diff on all 5 license files. No new pip / npm deps.

## Acceptance criteria

- 9 new pytest + 3 vitest green.
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` net-green vs baseline.
- `pytest tests/test_ad742e_vision_budget.py -v -n 0` MUST still pass
  (snapshot backcompat: `session_ceiling_estimate` retained).
- `pytest tests/test_ad733c2_mode_controller.py -v -n 0` MUST still pass
  (transition_to signature unchanged).
- `cd ui && npm run build` green (BF-279 UI gate).
- After a real over-cap session: budget endpoint reports
  `cap_reached_session=true`, mode controller transition history shows
  `budget_exhausted`, HXI badge is red (manual verification step).
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-18)

```
grep -n "_record_vision_call" src/probos/perception/consumer.py
  185:     def _record_vision_call(self, tier: str, session_id: str) -> None:
  530:             self._record_vision_call(describe_tier, self._budget_current_session_id or "default")

grep -n "get_budget_snapshot" src/probos/perception/consumer.py
  203:     def get_budget_snapshot(self) -> dict[str, Any]:

grep -n "_budget_calls_session\|_budget_calls_today\|_budget_current_session_id\|_budget_last_call_at" src/probos/perception/consumer.py
  130:         self._budget_calls_session: dict[str, int] = {...}
  131:         self._budget_calls_today: dict[str, int] = {...}
  132:         self._budget_current_session_id: str = ""
  133:         self._budget_current_date: str = ""
  134:         self._budget_last_call_at: float | None = None
  (+ updates inside _record_vision_call)

grep -n "def transition_to" src/probos/perception/mode_controller.py
  165:     def transition_to(self, mode: Mode, *, trigger: str = "manual") -> bool:

grep -n "perception_mode_controller" src/probos/startup/finalize.py
  4111:             runtime.perception_mode_controller = _controller

grep -n "PROGRAMMATIC_COOLDOWN_S" src/probos/perception/mode_controller.py
  93:     PROGRAMMATIC_COOLDOWN_S = 1.0

grep -n "@router.get.*budget" src/probos/routers/perception.py
  383: @router.get("/budget", dependencies=[Depends(require_crew_scope)])

grep -n "VisionBudgetBadge" ui/src/perception/
  (file exists per Wave 174 build report)
```

`_record_vision_call` is invoked at `consumer.py:530`, INSIDE
`async with self._describe_lock` (acquired at line 324). The new
`_maybe_enforce_budget` call is synchronous (controller.transition_to is
sync; no await). Safe to call while holding the lock — no async
acquisition, no re-entry into `_describe`. Confirmed.
