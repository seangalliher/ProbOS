# Review: AD-722d — Auto-write significance events to Ship's Records

**Verdict:** ⚠️ Conditional
**Sound design + correct anchors, but Section 2 ships sketched-then-corrected code that's a footgun for the Builder.**

## Required (must fix before building)
1. **Section 2 `_classify` body presents broken code first, then corrects it in a "Design note" paragraph.** The shown body reads `prior._last_div_mag` from a frozen dataclass that has no such field, then a paragraph below says "Builder MUST use the parallel-dict version. Frozen dataclasses cannot be mutated." The risk per BF-274/278 user-memory: Builder applies the shown SEARCH/REPLACE literally before reading the design note, then has to revert. **Rewrite Section 2 so the shown `_classify` body uses `self._prior_div_mag.get(snap.agent_id, 0.0)` directly**, with `self._prior_div_mag: dict[str, float] = {}` initialized in `__init__` alongside `self._prior`, and add the `self._prior_div_mag[snap.agent_id] = float(latest.magnitude)` update after classify. Drop the sketch entirely.

## Recommended
1. **`_pick_priority` "defensive: ordered set guarantees at least one element"** — `set` is unordered. The defensive `next(iter(events))` only runs when none of the three named events is in `events`, which is impossible given `_classify` only adds those three. Either drop the defensive branch or reorder to a `list` for clarity.
2. **Throttle key is per-agent globally**, not per-(agent, event). A single divergence write throttles a subsequent `working_state_to_blocked` for the same agent for an hour. Probably intentional ("max 1 Records entry per agent per hour" per issue #570) — but worth one explicit line in the AD-722d DECISIONS entry confirming the choice.
3. **`sustained_silence` re-fire window** — comment says "throttle handles re-fire" but doesn't explain the 4-hour upper bound (`gap <= 4 * 3600`). State the rationale (avoid firing for agents that never had a recent reply baseline) in either a code comment or the DECISIONS entry.

## Nits
1. `now_iso.split("T", 1)[-1][:5]` is correct but cryptic. `datetime.now(timezone.utc).strftime('%H:%M')` is identical and self-documenting.
2. The frozenset alias `KNOWN_EVENTS` and the three `EVENT_*` string constants serve the same purpose. Could collapse to just the frozenset literal, but the constants are referenced by `_pick_priority` — fine as-is.

## Verified
- `AvatarTelemetryConfig` at `src/probos/config.py:1025` — anchor confirmed.
- `RecordsStore.write_entry` at `src/probos/knowledge/records_store.py:90` — `async def write_entry(...)` signature confirmed.
- `runtime._records_store = cog.records_store` at `runtime.py:1528` — finalize wiring anchor confirmed.
- `runtime.records_store` property at `runtime.py:1131`.
- `runtime.divergence_results: dict[str, DivergenceResult]` at `runtime.py:440` — exists (prompt's `getattr(runtime, "divergence_results", None)` is safe even if None).
- `DivergenceResult.intent_emotion: str` (`divergence_detector.py:160`), `DivergenceResult.magnitude: float` (line 164) — fields exist.
- `agent.last_reply_emitted_at` is the agent attribute (telemetry.py:715 reads it via `getattr`). Writer's `getattr(agent, "last_reply_emitted_at", 0.0)` mirrors this exactly.
- `working_state: str` at `telemetry.py:291` with values `'idle' | 'responding' | 'blocked'` — transition detection logic correct.
- Two-phase finalize wiring (Section 3) is explicit and matches §10 phase-ordering pattern (BF-259/260): default `None` at construction; populate in finalize after `_records_store` is wired. Dispatch's wave-specific reminder block warns reviewer not to flag the None-assignment.
- `Field(default_factory=lambda: [...])` used for `records_significant_events` — avoids the Pydantic mutable-default trap (review-criteria anti-pattern).
- Test plan: 5 tests — happy paths for each event, throttle, unknown event drop, exception swallow. Boundary coverage met.
- WS publish loop hook at `routers/agents.py:737` lands AFTER the AD-722c history-append block per dispatch dependency ordering. Verified.
- Tier-2 log-and-degrade everywhere (writes can't disrupt WS publish or agent reply). Correct.
- License: stdlib + existing `RecordsStore`. AD-731 invariant N/A.
- No UI changes — AD-738b UI gate not triggered.

---

**Re-review:** _(pending Section 2 rewrite)_

### Re-review (pass-2, 2026-05-14)

**Verdict:** ✅ Approved.

**Required #1 — RESOLVED.** Section 2 ships a single canonical `_classify` body. Verified against `prompts/ad-722d-records-auto-write.md`:
- `__init__` declares `self._prior_div_mag: dict[str, float] = {}` at line 135 alongside `self._prior` (line 132 region).
- `_classify` reads `prior_mag = self._prior_div_mag.get(snap.agent_id, 0.0)` directly (line 178) and updates `self._prior_div_mag[snap.agent_id] = float(latest.magnitude)` always when a fresh `divergence_results` entry exists (line 183).
- No `_last_div_mag` references remain anywhere in the prompt body. No `prior._last_div_mag` against the frozen dataclass. No trailing "Builder MUST use the parallel-dict version" design-note paragraph. Self-check in the Revision footer asserts the same — grep-confirmed.
- Comments in the body (`# FRESH divergence is detected against self._prior_div_mag (parallel ... NOT a field on the frozen snapshot)`) document the choice in-place rather than as a trailing corrective paragraph. BF-274/278-style "sketch then correct" footgun is removed.

No new Required findings. Recommended/Nits from pass 1 unchanged (Captain may address pre-dispatch or defer).
