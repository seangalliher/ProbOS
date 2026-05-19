# WAVE 175 — DISPATCH

**Drafted:** 2026-05-18
**Status:** GATE 1 (architect-only). Pass-1 + Pass-2 complete.
**Captain authorization:** ~12h overnight, offline.
**Posture:** **CONSERVATIVE OVERNIGHT.** All three ADs are additive,
opt-in/safe-default, backend-only or behind opt-in flags. No live
perception path touched; current behavior preserved bit-for-bit when
defaults are honored.

## Slate

One-paragraph summary:

Wave 175 closes three perception forward markers (#674, #672, #677)
without changing any live behavior. **AD-742f** adds SQLite persistence
for per-agent vision working memory (default ON; ~10 KB total footprint;
honest-degrades to in-memory on DB failure). **AD-742d** ships four
alternative `SupervisorStrategy` implementations (motion / scene_change /
never / always) behind the existing AD-733a Protocol seam; default stays
`"ahash"` so VisionConsumer behavior is bit-for-bit unchanged. **AD-733c-6**
extends AD-742e budget telemetry into enforcement — engaged-mode auto-
drops to AMBIENT when per-session (200) or per-day (2000) vision LLM
caps hit, with hot-reload caps and once-per-session WARNING. The HXI
budget badge replaces its heuristic ceiling with the configured cap and
gains green/orange/red color states. Three new GH issues will be filed
at close (AD-742f-1 cross-host WM sync, AD-742d-1 CLIP strategy, AD-742d-2
per-session strategy override, AD-733c-6-1 day-counter persistence,
AD-733c-6-2 WardRoom notification).

## Highest current AD

**AD-742e** (shipped Wave 174, commit `db8973cf`). Wave 175 promotes
existing forward markers AD-742d / AD-742f and adds new sub-AD
**AD-733c-6** under the AD-733c series.

Confirmed via:
```
git log --all --oneline | Select-String "AD-742" | Select -First 5
  → AD-742e, AD-742b, AD-742a all shipped Wave 174.
```

No new top-level AD number assigned this wave.

## Drafted prompts

| # | Prompt | Closes | Tests |
|---|--------|--------|-------|
| 1 | `prompts/ad-742f-wm-persistence.md` | #674 | +10 pytest |
| 2 | `prompts/ad-742d-pluggable-supervisor.md` | #672 | +12 pytest |
| 3 | `prompts/ad-733c-6-engaged-budget-enforcement.md` | #677 | +9 pytest, +3 vitest |

Total: **+31 pytest, +3 vitest.** Zero new pip/npm deps. 0-line diff on
all 5 license files.

## Build order (strict)

1 → 2 → 3. Rationale:

1. **AD-742f first** (WM persistence) — isolated infrastructure addition.
   Adds `wm_store.py` (new file), threads a store through the WM factory.
   No interaction with supervisor or budget.
2. **AD-742d second** (supervisor strategies) — adds new classes after
   `PerceptualHashStrategy` in `supervisor.py`. Independent of WM. Both
   prompts insert `FieldDescriptor` entries in `__init__.py`; AD-742d's
   prompt has a footnote requiring the Builder to keep AD-742f's
   FieldDescriptor if it lands first (or vice versa). The
   `vision_supervisor_strategy` validator must land BEFORE
   `class LipSyncConfig` — Builder verifies the anchor at apply time.
3. **AD-733c-6 third** (budget enforcement) — depends on AD-742e (shipped
   Wave 174). Adds enforcement loop inside `_record_vision_call` +
   surfaces caps via `get_budget_snapshot`. HXI badge update is a small
   modify in `VisionBudgetBadge.tsx` (Builder reads HEAD shape first).

## Pre-flight gate

Before any Builder dispatch:

```pwsh
git status --porcelain
# expect: clean working tree (only architect prompts + wave-plan.yaml dirty)

git log --oneline -1
# expect: 1f250534 or newer

.\.venv\Scripts\pytest.exe tests/ -q -n 4 --dist=loadfile 2>&1 | Select -Last 3
# baseline: all green (Wave 174 + BF-313/314/315 shipped clean)

# Verify Captain's local-only setup unblocks builds:
ollama list | findstr moondream
# moondream:latest must be pulled (Wave 174 enablement)
```

If any line is unexpected, **stop** and surface to user instead of
proceeding.

## Conservative overnight posture

- **Default behavior unchanged**: every new field defaults to current
  behavior (`wm_persistence_enabled=True` is the only ON-default, and it
  silently no-ops when SQLite is unavailable).
- **No live perception path touched mid-flight**: WM persistence loads on
  WM construction (boot-time); strategy swap is restart-required; budget
  enforcement checks happen AFTER the call already succeeded.
- **No new deps**: 0-line diff on `pyproject.toml`,
  `requirements*.txt`, `package.json`, `THIRD_PARTY_LICENSES.md`,
  `LICENSE`. If any of these get touched during build, hard-stop.
- **Single source of truth for tests**: every new test uses real
  fixtures over MagicMock (BF-287); every new test uses single
  `replace_string_in_file` per adjacent edit (BF-274 lesson).
- **HXI gate**: AD-733c-6 modifies `VisionBudgetBadge.tsx`. Builder MUST
  run `cd ui && npm run build` AND `npx vitest run` (BF-279 — vitest
  passing is not sufficient evidence the bundle compiles).

## Hard-stop conditions

Builder must stop and surface (not work around) on any of:

1. Pre-flight grep finds a missing anchor (e.g., `working_memory_capacity`
   not at `config.py:2005` or `VisionConsumer(` not at
   `finalize.py:4017`).
2. Pre-flight gate fails — baseline tests not green.
3. New pip / npm dep gets introduced (license diff non-zero).
4. AD-731 invariant violation detected: any code path stores image bytes
   in `perception_wm.db` (schema review or test red-flag).
5. `pytest tests/test_ad733a_vision_consumer.py -v -n 0` fails after
   any of the three ADs land — proves default behavior diverged.
6. `cd ui && npm run build` fails — stale-bundle regression risk.
7. >5 quarantine markers added across the wave.
8. Builder's tracked-file working-tree shows deletions >200 lines on any
   file the wave didn't intend to modify (BF-274 / 2026-05-08 wipe
   pattern).

## Considerations surfaced beyond the issues

- **WM persistence default ON, not OFF.** The user prompt suggests
  default ON, and I agree — the storage cost is trivial (~10 KB) and the
  primary use case (Captain's restart-survivor recall) is exactly what
  the feature enables. Honest-degrade keeps it safe.
- **Sync sqlite3 vs aiosqlite in `wm_store.py`.** Chose stdlib
  synchronous `sqlite3` because `VisionWorkingMemory.append` is a
  synchronous method — adding aiosqlite would force every observer write
  into a `run_in_executor` round-trip for no gain on <1 ms inserts. The
  module-level Lock prevents concurrent-write conflicts. Alternative:
  push the WM hot path async — out of scope, higher-risk.
- **Strategy selection is restart-required**, not hot-reload. Rationale:
  swapping strategy mid-flight orphans the previous strategy's baseline
  state (last_hash / last_pixels / last_hist). The cleaner UX is "set,
  restart, observe." Cap values within a strategy stay hot-reload via
  BF-308.
- **Mode-transition cooldown vs budget-exhausted trigger.** The
  AD-733c-2 `PROGRAMMATIC_COOLDOWN_S = 1.0` floor applies to all
  non-manual triggers. For budget enforcement this is fine: post-cap
  describes are throttled by `_describe_lock` + supervisor already, so
  the 1s floor doesn't create a race where 50 transitions fire.
- **WardRoom notification deferred to forward marker.** AD-733c-6-2
  files this as a follow-up. WARNING log + HXI badge red state +
  `/api/perception/budget` `cap_reached_session=true` are the v1
  notification surface — enough to be operator-visible without taking on
  WardRoomPostPipeline coupling in an overnight build.
- **Day counter does NOT persist across restart.** Same shipping
  pattern as AD-742e. Filed as AD-733c-6-1. Not critical because Captain
  rarely restarts mid-day and the cap is 2000/day.
- **No new EventType enums.** Three ADs ship without touching the event
  system. Budget cap-hit is surfaced via the existing transition history
  (`trigger="budget_exhausted"`) which already flows through the
  controller's history ring — no event bus broadcast needed for v1.

## GATE 1 verdict

**✅ Approved (Conditional on Builder pre-flight).**
**All three prompts ready for Builder; build order strict 1→2→3.**

### Required (must verify at Builder pre-flight)

1. `config.py:2005` anchor (`working_memory_capacity`) and
   `config.py:~2065` anchor (`proactive_novelty_threshold`) match HEAD
   exactly — verified at draft time, but HEAD may shift if BF-316 or
   later lands first.
2. `finalize.py:4017` (`consumer = VisionConsumer(`) and
   `finalize.py:~4034` (`runtime.vision_consumer = consumer`) anchors
   match HEAD.
3. `consumer.py:185` (`_record_vision_call`), `consumer.py:203`
   (`get_budget_snapshot`), `consumer.py:130-134` (budget state init),
   `consumer.py:80-94` (VisionConsumer `__init__` PerceptualHashStrategy
   construction) all match HEAD.
4. `supervisor.py:36` (`class PerceptualHashStrategy`), `supervisor.py:31`
   (`class SupervisorStrategy`), and the closing brace of `evaluate` at
   `supervisor.py:~121` (last line of file body) match HEAD.

### Recommended

1. Builder runs `pytest tests/test_ad733a_vision_consumer.py tests/test_ad733c2_mode_controller.py tests/test_ad742e_vision_budget.py -v -n 0`
   BEFORE the first prompt and AFTER each prompt — confirms no default-
   behavior regression in the three most-relevant existing test files.
2. Builder caps each prompt's `_describe_lock`-adjacent edits to a single
   `replace_string_in_file` call — BF-274 lesson, applies to all three
   prompts.
3. Builder commits each AD as a standalone commit titled
   `AD-742f: vision WM persistence (closes #674)` /
   `AD-742d: pluggable supervisor strategies (closes #672)` /
   `AD-733c-6: engaged-mode budget enforcement (closes #677)`. Three
   commits, three PRs (or one wave PR with three commits).

### Nits

1. AD-742f's `WorkingMemoryStore.append` uses
   `with self._lock, sqlite3.connect(...)` — both context managers in
   one statement. Builder must format per PEP 8 if the line exceeds 100
   chars (it does in the SEARCH/REPLACE; Builder may need to split onto
   two `with` lines for some Python versions, though ≥3.10 supports
   parenthesized with-statements).
2. AD-742d's `_load_pil_image` helper is shared across MotionStrategy
   and SceneChangeStrategy. If the existing `_ahash_jpeg_bytes` helper
   does its own PIL import, consider unifying — out of scope tonight.

### Verified Improvements over previous waves

1. **License posture surfaced upfront.** 0-line diff on all 5 license
   files documented in each prompt's "License posture" block and again
   in this dispatch doc.
2. **AD-731 invariant explicitly preserved** in both AD-742f (no image
   bytes in WM DB) and AD-742d (strategies operate on bytes passed by
   reference, never write to disk).
3. **BF-274 single-edit discipline** enforced in every prompt's
   SEARCH/REPLACE structure — no overlapping multi-edits.
4. **BF-287 real-fixture discipline** enforced in every test plan — no
   MagicMock at the substrate boundary.
5. **HXI Principle #3** (no emoji) enforced in AD-733c-6's badge update
   spec — SVG glyphs only, reuse the AD-742e shipped stroke-circle.
6. **AD-722c-3 forward-marker triggers** explicitly checked in each
   prompt — none of the three ADs trigger a new technical-marker
   threshold.
7. **Anti-deadlock analysis** for AD-733c-6: confirmed
   `controller.transition_to` is synchronous, safe to call from inside
   `async with self._describe_lock`.
8. **Hot-reload posture** explicit per BF-308 in each prompt: cap values
   hot-reload, strategy selection restart-required, persistence flag
   hot-reload (writes only, not reads).

---

## NOT in this wave (forward markers post-build)

- **AD-742f-1** — Cross-host federation of WM rows.
- **AD-742f-2** — TTL-based privacy pruning (currently cap-only).
- **AD-742d-1** — CLIP-embedding-based semantic strategy.
- **AD-742d-2** — Per-session strategy override.
- **AD-733c-6-1** — SQLite persistence of daily aggregate across restart.
- **AD-733c-6-2** — WardRoom notification on cap-hit.

All to be filed as GH issues at wave close (per the standing
2026-05-08 rule from `/memories/repo/probos-notes.md`).

---

## Builder dispatch checklist (for after GATE 2)

- [ ] Pre-flight gate green.
- [ ] AD-742f built, tested, committed.
- [ ] AD-733a regression suite re-run after AD-742f → still green.
- [ ] AD-742d built, tested, committed.
- [ ] AD-733a + AD-733c2 regression suites re-run after AD-742d → still green.
- [ ] AD-733c-6 built, tested, committed.
- [ ] AD-742e + AD-733c2 regression suites re-run after AD-733c-6 → still green.
- [ ] Full wave gate green at `-n 4 --dist=loadfile`.
- [ ] `cd ui && npm run build` green (BF-279).
- [ ] 5 new GH issues filed for forward markers.
- [ ] PROGRESS.md + roadmap.md updated.
- [ ] Wave 175 prompts archived (mv to `prompts/archive/`).
