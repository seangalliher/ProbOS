# WAVE 78 DISPATCH — AD-569 Behavioral Metrics Extensions (1-build + 5 verify-only + 1 defer)

**Wave id:** 78
**Umbrella AD:** AD-569 (Observation-Grounded Crew Intelligence Metrics)
**Sub-ADs in scope:** AD-569a, AD-569b, AD-569c, AD-569d, AD-569e, AD-569f, AD-569g
**Closes:** GH issue #108
**HEAD at draft:** `7bd1980` (post-Wave-77)
**Baseline test count:** 11498 → expected **11498** pytest (Δ = 0; pytest unchanged) + **+9 to +12 vitest** on the HXI side
**Builder required:** true (HXI panel build for 569g only)

## Verdict

Verify-first against HEAD `7bd1980` reveals **a/b/c/d/e are already shipped** (5 of 7 sub-ADs), **g is fully buildable as an HXI-only panel** on top of existing endpoints, and **f is genuinely research-grade work** that lacks a present-day consumer. One build prompt ships in this wave; five siblings close as verify-only; one defers with an explicit forcing function. **Closes #108 cleanly.**

| Sub-AD | Live state at HEAD `7bd1980` | Wave 78 action |
|---|---|---|
| **AD-569a** Analytical Frame Diversity | ✅ **Shipped via AD-569 main entry.** `BehavioralSnapshot.frame_diversity_score`, `frame_diversity_threads`, `department_representation` populated by `BehavioralMetricsEngine` (`src/probos/cognitive/behavioral_metrics.py:38-41`). PROGRESS.md:363 confirms "AD-569 COMPLETE … Analytical Frame Diversity". | **No-build verify-only.** Roadmap status flip from prose-deferred bullet to `*(complete)*` tag. |
| **AD-569b** Synthesis Detection | ✅ **Shipped via AD-569 main entry.** `synthesis_rate`, `synthesis_threads`, `total_novel_elements` fields on `BehavioralSnapshot:43-45`. PROGRESS.md:363 confirms. | **No-build verify-only.** Roadmap status flip. |
| **AD-569c** Cross-Department Trigger Rate | ✅ **Shipped via AD-569 main entry.** `cross_dept_trigger_rate`, `trigger_pairs`, `trigger_events` on `BehavioralSnapshot:47-49`. PROGRESS.md:363 confirms. | **No-build verify-only.** Roadmap status flip. |
| **AD-569d** Convergence Correctness | ✅ **Shipped via AD-583f/g satisfaction.** `convergence_correctness_rate` field on `BehavioralSnapshot:55` populated by `ObservableStateVerifier` (decisions-era-4-evolution.md:3219 explicitly states "Wires into `_compute_convergence_correctness()` stub … Satisfies AD-569d deferral"). PROGRESS.md:363 confirms "Satisfies AD-569d deferral — populates convergence_correctness_rate in BehavioralSnapshot". | **No-build verify-only.** Roadmap status flip to `*(complete via AD-583f/g)*`. |
| **AD-569e** Anchor-Grounded Emergence | ✅ **Shipped via AD-569 main entry.** `anchor_grounded_rate`, `anchor_independence_score`, `anchor_analyzed_threads` on `BehavioralSnapshot:58-60`. Engine consumes `social_verification.compute_anchor_independence()` per AD-569 main entry text. PROGRESS.md:363 confirms. | **No-build verify-only.** Roadmap status flip. |
| **AD-569f** Measurement Framework Infrastructure | ⏸ **Genuine future work.** G-study/D-study engine, ICC/r_wg computation, MTMM matrix generation, variance decomposition reporting. Pure-Python statistics layer. **No present-day consumer**: AD-583f/g satisfied 569d without it; existing Tier 3 probes don't yet require facet decomposition; AD-569's 5 metric scalars are sufficient for the v1 HXI dashboard. Decomposing this AD properly requires a research-design pass tied to the first probe that needs G-theory rigor. | **No-build defer with explicit forcing function.** Tag in roadmap: `*(deferred — forcing function: first qualification probe requiring variance decomposition; tracked under AD-569 umbrella)*`. Stays open for future wave. |
| **AD-569g** HXI Behavioral Dashboard | 📋 **Buildable now (v1).** Backend complete: `/api/behavioral-metrics` and `/api/behavioral-metrics/history` endpoints (`routers/system.py:299-326`, prefix `/api`). HXI side: zero behavioral surface (`grep -i behavioral ui/src/**` returns nothing). AD-523b `NotebooksPanel.tsx` (Wave 77) is the freshest HXI panel template. Facet breakdown explicitly out-of-scope (depends on 569f). | **BUILD.** One prompt: `prompts/ad-569g-hxi-behavioral-dashboard.md`. HXI-only (1 new component, 1 new test file, 2-3 modified UI files). Vitest delta +9 minimum. |

## Reframe decision (Captain rule applied)

**7-section umbrella → 1-build + 5 verify-only + 1 defer-with-forcing-function**, hybrid of Wave 77 (close-with-some-shipped + 1-build pattern) and Wave 71 (no-build close pattern). Per Captain rule "don't defer unless no choice — try to ship maximum buildable":

- **a/b/c/e:** all shipped via AD-569 main; the wave records that fact in roadmap status tags.
- **d:** shipped via AD-583f/g downstream satisfaction; roadmap tag flipped accordingly.
- **g:** ships in this wave as v1 (no facet breakdown, since that requires 569f).
- **f:** genuinely deferred. **This is not a "we don't want to build it" deferral** — it's a "no consumer needs it yet, building now would land an under-specified math layer" deferral. Per Wave-10 convention #3 (scope-reframe-at-AD-level for entanglement), the consumer-side entanglement requires a research-design pass. The deferral has an explicit forcing function: when the first qualification probe (or other consumer) requires variance decomposition / ICC / r_wg / MTMM, AD-569f gets decomposed and built then. Until then, the 5 scalar metrics + AD-583f/g satisfaction give the system everything it observably uses.

GH #108 closes cleanly because all 7 sub-ADs are now resolved against the original "Deferred sub-ADs" list in the issue body: 5 shipped, 1 ships this wave, 1 has a tracked forcing function. Issue #108's umbrella scope is satisfied.

The Captain's rule "ship maximum buildable" is honored: Wave 78 ships **everything that has a present-day consumer**. AD-569f does not.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  7bd19806b7a01957fa01c24d99434ec4d428dd3f

# AD-569 main + a/b/c/e shipped:
src/probos/cognitive/behavioral_metrics.py:35-77
  BehavioralSnapshot dataclass — all 5 metric field groups present.
src/probos/cognitive/behavioral_metrics.py:79-101
  BehavioralMetricsEngine — Dream Step 13 update path.
PROGRESS.md:363
  "AD-569 COMPLETE (Observation-Grounded Crew Intelligence Metrics —
   BehavioralMetricsEngine with 5 content-level behavioral metrics:
   Analytical Frame Diversity, Synthesis Detection, Cross-Department
   Trigger Rate, Convergence Correctness, Anchor-Grounded Emergence.
   Dream Step 13 integration. 5 Tier 3 qualification probes.
   API: /behavioral-metrics, /behavioral-metrics/history.
   BehavioralMetricsConfig. BEHAVIORAL_METRICS_UPDATED event.
   11 files modified, 36 new tests)."
decisions-era-4-evolution.md:2676-2682
  "AD-569: Observation-Grounded Crew Intelligence Metrics …
   Status: Complete … Five content-level behavioral metrics …"

# AD-569d shipped via AD-583f/g:
decisions-era-4-evolution.md:3219
  "Wire into `_compute_convergence_correctness()` stub | Satisfies
   AD-569d deferral. `convergence_correctness_rate` already exists
   on BehavioralSnapshot and is read by qualification probes."
PROGRESS.md:363
  "Satisfies AD-569d deferral — populates convergence_correctness_rate
   in BehavioralSnapshot. New events: WARD_ROOM_ECHO_DETECTED,
   OBSERVABLE_STATE_MISMATCH."
src/probos/cognitive/behavioral_metrics.py:55  convergence_correctness_rate: float | None = None
src/probos/cognitive/behavioral_metrics.py:90  observable_state_verifier: Any = None  # AD-583f
src/probos/cognitive/behavioral_metrics.py:99-101  set_observable_verifier(...) late-bind

# Backend endpoints for AD-569g:
src/probos/routers/system.py:18  router = APIRouter(prefix="/api", tags=["system"])
src/probos/routers/system.py:299  @router.get("/behavioral-metrics")
src/probos/routers/system.py:311  @router.get("/behavioral-metrics/history")

# AD-569f / AD-569g still open (no source/UI hits):
grep -r "AD-569f\|behavioral_dashboard\|psychometric" src/ ui/  → 0 hits
grep -i behavioral ui/src/  → 0 hits

# HXI panel template (AD-523b, Wave 77):
ui/src/components/NotebooksPanel.tsx:1-70  floating panel pattern
ui/src/App.tsx:20  import NotebooksPanel from './components/NotebooksPanel';
ui/src/App.tsx:22-54  inline NotebooksToggle() pattern (zIndex 25, top:12 left:200)
ui/src/App.tsx:170-171  <NotebooksPanel /> + <NotebooksToggle /> mount points
ui/src/store/useStore.ts:267-274,319-320,500-507,574-613  store-side template

# GH #108 itself:
Title:  "AD-569a-g: Behavioral Metrics Extensions"
State:  open
Body:   "Deferred sub-ADs: (a) Frame Diversity Probe, (b) Synthesis
         Detection, (c) Cross-Dept Trigger Rate, (d) Convergence
         Correctness, (e) Anchor-Grounded Emergence,
         (f) Measurement Framework Infra, (g) HXI Behavioral Dashboard."
```

Every concrete claim in this dispatch maps to a grep hit above.

## Captain workflow

1. **Append wave 78 entry to `prompts/wave-plan.yaml`** under id `"78"`, after id `"77"`:
   ```yaml
     - id: "78"
       title: "AD-569 v1 Behavioral Metrics Extensions (1-build + 5 verify-only + 1 defer)"
       kind: combo
       depends_on: ["77"]
       dispatch_prompt: "prompts/WAVE-78-DISPATCH.md"
       prompts_already_drafted: true
       prompt_paths:
         - "prompts/ad-569g-hxi-behavioral-dashboard.md"
       builder_required: true
       issues_to_close: [108]
       status: pending
       notes: |
         Closes GH #108 (umbrella AD-569 a-g). Reframe 7 → 1-build:
         AD-569a/b/c/e shipped via AD-569 main entry (PROGRESS.md:363);
         AD-569d shipped via AD-583f/g satisfaction (decisions-era-4
         :3219); only AD-569g (HXI Behavioral Dashboard v1) builds in
         this wave — HXI-only panel on top of /api/behavioral-metrics
         (shipped under AD-569). AD-569f (Measurement Framework Infra)
         deferred with forcing function — research-grade psychometric
         layer with no present-day consumer. Vitest-only delta
         (+9 to +12 window). Baseline 11498 → expected 11498 pytest
         (Δ = 0); vitest gate covers the new panel separately.
   ```
2. **Builder runs `prompts/ad-569g-hxi-behavioral-dashboard.md`** end-to-end. Outputs: 1 new component, 1 new vitest test file, 2-3 modified UI files (`useStore.ts`, `App.tsx`, optionally `types.ts`), 2 tracking-only edits (PROGRESS.md, roadmap.md). NO Python source touched. NO new pytest files.
3. **Pre-commit gate (Builder responsibility):**
   - `cd ui && npx vitest run` — new tests pass (9-12); no existing vitest test regresses.
   - `pytest tests/ -q -n 4 --dist=loadfile` — collects **11498**, identical to baseline (Δ = 0).
   - `git status` shows the expected file set; no `src/probos/` modifications; no new pytest files.
4. **Update `PROGRESS.md`** (top of the era-4 progress block) with one Wave 78 entry summarizing the 1-build + 5 verify-only + 1 defer resolution.
5. **Update `docs/development/roadmap.md`:**
   - Line 4394: AD-569 umbrella tag stays `*(complete)*` — no change.
   - Line 4501 (`569a`): tag `*(complete)*`. Preserve descriptive text.
   - Line 4502 (`569b`): tag `*(complete)*`.
   - Line 4503 (`569c`): tag `*(complete)*`.
   - Line 4504 (`569d`): tag `*(complete via AD-583f/g)*`.
   - Line 4505 (`569e`): tag `*(complete)*`.
   - Line 4506 (`569f`): tag `*(deferred — forcing function: first qualification probe requiring G-theory variance decomposition; tracked under AD-569 umbrella)*`.
   - Line 4507 (`569g`): tag `*(complete — Wave 78, v1 without facet breakdown)*`.
6. **Commit:** `Wave 78 close: AD-569 behavioral metrics extensions — 1 build (569g v1) + 5 verify-only (a/b/c/d/e shipped via AD-569 main + AD-583f/g) + 1 defer (569f forcing function) (#108)`.
7. **Archive** `prompts/WAVE-78-DISPATCH.md` and `prompts/ad-569g-hxi-behavioral-dashboard.md` to `prompts/archive/` after the GH close.
8. **Close GH #108** with the verify-first evidence + commit hash + the seven-row sub-AD-by-sub-AD resolution table from the verdict section above.
9. **Update memory `/memories/session/wave-queue-batch2.md`** with `W78 #108 done (combo: 569g v1 built; 569a/b/c/d/e verify-only; 569f deferred with forcing function; baseline 11498)`.

## Hard-stop conditions

1. **Phantom API in implementation.** Every method, endpoint, and store anchor asserted in `prompts/ad-569g-hxi-behavioral-dashboard.md` is verified against HEAD `7bd1980` in the prompt's "Verified Against Codebase" section. If the Builder finds a mismatch (e.g. `/api/behavioral-metrics` 404s, `BehavioralSnapshot.to_dict()` returns a different shape, store action signatures differ from the NotebooksPanel template), → hard stop, surface to Architect.
2. **Architectural change required.** AD-569g is HXI-only. If the Builder concludes a backend change is required (new endpoint, new field on `BehavioralSnapshot`, new engine method), → hard stop. Architect re-scopes — the dispatch's "no backend changes" invariant is a hard line.
3. **Source code edits under `src/probos/`.** Any Python source file modification → hard stop. AD-569g v1 is HXI-only by design.
4. **New pytest test file added.** Any `tests/test_ad569g*.py` → hard stop. The dispatch states pytest delta is 0; backend is verify-only; no new Python tests are warranted.
5. **HXI emoji.** Any emoji character (👍, 📊, ✨, 🎯, 🧠 etc.) introduced into `BehavioralMetricsPanel.tsx` or any other UI file → hard stop. HXI Design Principle #3 prohibits emoji; all glyphs must be inline SVG with `strokeWidth: 1.5` or Unicode geometric characters from the existing palette (`×`, `↻`, `—`).
6. **Commercial leak.** Any pricing, revenue, customer-count, professional-services, GTM, or competitive-positioning language introduced into the prompt body, the panel component, the roadmap entry, the GH close comment, or any wave artifact → hard stop. AD-569 and all sub-ADs are wholly OSS. AD-569f's deferral note must NOT introduce commercial framing — it's a technical "no consumer yet" deferral, not a "premium tier" deferral.
7. **Test count drift.** Pytest full gate must report **11498 collected**. Any drift (e.g. 11497 from a serendipitously-skipped test, 11500 from a bonus test) → hard stop, surface to Architect.
8. **Working-tree drift.** Untracked changes in `src/`, `tests/`, `config/`, or `data/` paths after the Builder's commit → hard stop. Only `ui/src/` (2-3 modified + 2 new), `PROGRESS.md`, `docs/development/roadmap.md`, and `prompts/wave-plan.yaml` may be modified.
9. **569f scope creep.** Any psychometric infrastructure (G-study engine, ICC computation, r_wg, MTMM, variance decomposition) introduced into the panel or store → hard stop. 569f is explicitly deferred. The panel's footer note "Facet breakdown lands with AD-569f" is the ONLY 569f reference allowed in this wave's deliverables.
10. **Wave-10 convention #14 / #3 collisions.** No new transitional flag with `default=True`. No deprecation of any existing API. (Not expected to apply, but stated for completeness.)

## Acceptance criteria

1. `git status` (post-Builder) shows exactly:
   - `M ui/src/store/useStore.ts`
   - `M ui/src/store/types.ts` *(only if Builder picks types.ts as the BehavioralSnapshot home; otherwise the type lives in useStore.ts and types.ts is untouched)*
   - `M ui/src/App.tsx`
   - `?? ui/src/components/BehavioralMetricsPanel.tsx` (new)
   - `?? ui/src/__tests__/BehavioralMetricsPanel.test.tsx` (new)
   - `M PROGRESS.md`
   - `M docs/development/roadmap.md`
   - `M prompts/wave-plan.yaml` (id `"78"` entry)
   No other files.
2. **Vitest gate** `cd ui && npx vitest run` — new `BehavioralMetricsPanel.test.tsx` reports 9-12 passing; no pre-existing vitest test fails.
3. **Pytest full gate** `pytest tests/ -q -n 4 --dist=loadfile` — **11498 collected, 11498 passed**. Δ vs baseline = 0.
4. PROGRESS.md Wave 78 entry summarizes a/b/c/d/e/f/g resolution in one paragraph.
5. roadmap.md AD-569 sub-AD lines tagged per the Captain workflow above.
6. wave-plan.yaml id `"78"` entry committed with `status: done` after Builder gate passes.
7. GH #108 closed with verify-first evidence + commit hash + the seven-row resolution table.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — specifically: HXI emoji prohibition; SOLID-S (panel does only display + refresh, no write surface); Liskov (BehavioralSnapshot type matches backend `BehavioralSnapshot.to_dict()` contract); type annotations on all exported interfaces; no fire-and-forget tasks (the `Promise.all` is awaited); SVG-only icons (no emoji).

## Commercial-leak audit

Clean.

- AD-569 umbrella: tagged OSS at `docs/development/roadmap.md:4394` (`*(planned, OSS, depends: AD-557, AD-567 series)*` → currently tagged `*(complete)*`).
- AD-569a-e: shipped under AD-569 main, no commercial surface.
- AD-569d: shipped via AD-583f/g satisfaction. AD-583 entries in DECISIONS.md are OSS — no commercial scope.
- AD-569f: deferred with technical (not commercial) forcing function. The deferral note is "first qualification probe requiring G-theory variance decomposition" — purely technical reasoning. **No "premium tier", "enterprise psychometrics", "advanced analytics SKU", or any commercial framing introduced**.
- AD-569g: HXI panel, Captain-readable, OSS only. No paywall, no tier gating, no enterprise SKU language.
- No `*(Commercial)*` deferral filed in this wave.
- No pricing/revenue/customer/professional-services/GTM/competitive language in the dispatch, build prompt, panel component, roadmap entries, or GH close comment.
- No private-repo content or GTM positioning leaked. No "Great Artists Steal" pattern descriptions. No tier specifications.
- AD-569f's research grounding (Cronbach G-theory, Shrout & Fleiss ICC, James/Demaree/Wolf r_wg, Campbell & Fiske MTMM) is academic — already public on the OSS roadmap at lines 4485-4490. No new academic citations introduced.

## Review history

- **Pass 1 (initial draft):** Confirmed AD-569 main shipped (PROGRESS.md:363 + decisions-era-4:2676-2682 + behavioral_metrics.py source); confirmed AD-569d shipped via AD-583f/g (decisions-era-4:3219 + PROGRESS.md:363); confirmed AD-569g backend ready (`/api/behavioral-metrics` + `/api/behavioral-metrics/history` at routers/system.py:299/311); confirmed HXI gap (zero behavioral hits in ui/src); HXI panel pattern verified via NotebooksPanel.tsx (Wave 77 — freshest template); reframe to 1-build + 5 verify-only + 1 defer.
- **Pass 2 (verify-first sweep against HEAD `7bd1980`):** Spot-checked all anchor lines: `behavioral_metrics.py:35-77` (BehavioralSnapshot dataclass with all 5 metric field groups), `:79-101` (engine class), `:90` and `:99-101` (AD-583f late-bind verifier hook); `routers/system.py:18` (`/api` prefix), `:299` and `:311` (both endpoints with shipped logic); `useStore.ts:267-274,319-320,500-507,574-613` (NotebooksPanel store-side template); `App.tsx:20,22-54,170-171` (import + inline toggle + mount template); `__tests__/NotebooksPanel.test.tsx:5,30` (vitest pattern). Phantom-API risk on the build prompt: **0** — every method, endpoint, store key, and panel anchor cited exists at HEAD.
- **Pass 3 (anti-pattern + scope-creep scan):** No phantom APIs in either dispatch or build prompt. No commercial leak (audit section above is exhaustive — explicitly screened the AD-569f deferral note for premium-tier framing). No scope creep (build prompt's "What This Does NOT Change" enumerates 12 explicit out-of-scope items, including the hard 569f boundary). No new transitional flag. No deferral hidden as a closure (a/b/c/d/e are genuinely shipped; 569g is shipping; 569f is openly deferred with forcing function — not a stealth close). No fire-and-forget patterns required (Promise.all is awaited; refresh button awaits). Test delta sized within +9/+12 window: 9-test floor + Builder may add boundary cases up to ~+12.
- **Pass 4 (Wave-77/76/75 parity check + 569f deferral defensibility + commercial-leak final):** Same dispatch shape as Wave 77 (verdict table + reframe + verify-first + Captain workflow + hard-stops + acceptance + commercial-leak audit + review history). Same wave-plan.yaml entry shape as id `"77"`. Same memory update line shape as Wave 77. **569f deferral defensibility:** the forcing function is concrete and bounded ("first qualification probe requiring variance decomposition"); the deferral does not block any present-day consumer (AD-583f/g already satisfied 569d without 569f, and the 5 scalar metrics are sufficient for v1 569g); the deferral matches Wave-10 convention #3 (scope-reframe-at-AD-level when consumer-side entanglement requires research-design). Captain rule "ship maximum buildable" honored: every sub-AD with a present-day consumer is either shipped or shipping. Final commercial-leak audit: **clean** — no pricing, no tier gating, no SKU language; the academic citations referenced in 569f's deferral are pre-existing public roadmap content. Per `.github/copilot-instructions.md` "Commercial-tagged AD entries (HARD RULE)" — Wave 78 introduces zero pricing, revenue, customer counts, professional-services positioning, or GTM language. No `*(Commercial)*` tag anywhere.
