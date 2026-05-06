# WAVE 77 DISPATCH — AD-523 Ward Room & Records Overhaul (1-build + 2 verify-only)

**Wave id:** 77
**Umbrella AD:** AD-523 (HXI Ward Room & Records Overhaul)
**Sub-ADs in scope:** AD-523a, AD-523b, AD-523c
**Closes:** GH issue #98
**HEAD at draft:** `4479ec4` (post-Wave-76)
**Baseline test count:** 11498 → expected **11510 to 11516** (Δ = +12 to +18; vitest-only delta on the HXI side, pytest count unchanged)
**Builder required:** true (HXI panel build for 523b only)

## Verdict

Verify-first against HEAD `4479ec4` reveals **a/c are not buildable in their original scope** and **b is fully buildable as an HXI-only panel** (backend already shipped under AD-434). One build prompt ships in this wave; two siblings close as verify-only.

| Sub-AD | Live state at HEAD `4479ec4` | Wave 77 action |
|---|---|---|
| **AD-523a** DM Channel Viewer | ✅ **Already shipped via BF-080** (commit lineage in `docs/development/roadmap.md:7356`). `selectDmChannel` store action + `dm-detail` `wardRoomView` state in `ui/src/store/useStore.ts`; click-through DM Log in `ui/src/components/wardroom/WardRoomPanel.tsx`; reuses `WardRoomThreadDetail`. roadmap.md:2774 explicitly tags it complete. decisions-era-4-evolution.md:3247 also says "Satisfies: AD-523a." | **No-build verify-only.** Roadmap status flip from "✅ COMPLETE (via BF-080)" prose to canonical `*(complete)*` tag. |
| **AD-523b** Crew Notebooks Browser | 📋 **Buildable now.** Backend complete: `RecordsStore.list_entries(directory="notebooks")`, `read_entry()`, `search()` (records_store.py:730/700/818); routes `GET /api/records/{stats,documents,documents/{path:path},notebooks/{callsign},search}` (records.py:18-145). HXI side: zero panel exists. AD-513 `CrewRosterPanel` is the floating-panel template; AD-485/BF-080 `WardRoomPanel.tsx` is the three-column layout template. | **BUILD.** One prompt: `prompts/ad-523b-crew-notebooks-browser.md`. HXI-only (1 new component, 1 new test file, 3 modified files). Vitest delta +8 minimum. |
| **AD-523c** Ship's Records Dashboard | ⛔ **Superseded by AD-562** (Knowledge Browser w/ 3D graph + Obsidian-style backlinks + quality overlays). Explicit supersession at `decisions-era-4-evolution.md:2337` and `:2350`; roadmap.md:4237 confirms AD-562 "supersedes/absorbs this planned feature." AD-562 itself is `*(planned, OSS+commercial)*` and a much larger surface. Building a parallel lightweight dashboard now would be throwaway. | **No-build close-as-superseded.** Roadmap status flip to "closed (superseded by AD-562, see Issue #166-track or successor issue)". DECISIONS.md untouched (entries already exist + supersession recorded). |

## Reframe decision (Wave-10 convention)

**3-section umbrella → 1-build + 2 verify-only**, hybrid of Wave 71 (no-build close) and Wave 75 (single-AD HXI build). Per Captain rule "don't defer unless no choice" — this is **not a deferral**:

- **AD-523a:** the work is fully complete (BF-080 commit). The wave records that fact in the roadmap status tag and closes #98's `a` line.
- **AD-523b:** ships in this wave. The Builder writes the panel + tests against existing backend endpoints.
- **AD-523c:** the original scope is officially absorbed by a larger AD (AD-562) that has its own design + research doc + future build path. Re-implementing 523c's "lightweight dashboard" today would be discarded the moment AD-562 ships. The Captain agreed in DECISIONS.md (see :2337 and :2350) before this wave existed.

GH #98 closes cleanly because all three sub-ADs are now resolved (one shipped earlier, one ships this wave, one absorbed). #98 itself was the umbrella tracking issue; AD-562's own scope continues under whatever issue it gets when it leaves planned status (separate from #98).

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  4479ec47b30cb8eb3a19b7ef0ba6caaefe940515

# AD-523a — already shipped via BF-080:
docs/development/roadmap.md:2774
  - **AD-523a: DM Channel Viewer** — ✅ **COMPLETE** (via BF-080).
docs/development/roadmap.md:7356
  | BF-080 | DM channels listed but not clickable in HXI. ... Also satisfies AD-523a. | Medium | Closed |
decisions-era-4-evolution.md:3247
  **Satisfies:** AD-523a (DM Channel Viewer)
ui/src/store/useStore.ts — selectDmChannel action; wardRoomView 'dm-detail' state (BF-080).

# AD-523b — backend complete, HXI gap:
src/probos/knowledge/records_store.py:700  async def read_entry(self, path, reader_id, reader_department="")
src/probos/knowledge/records_store.py:730  async def list_entries(self, directory="", *, author="", status="", tags=None, classification="")
src/probos/knowledge/records_store.py:818  async def search(self, query, scope="ship")
src/probos/knowledge/records_store.py:854  async def get_stats(self)
src/probos/routers/records.py:18-145 — 9 endpoints, all of /api/records/* shipped.
ui/src/components/CrewRosterPanel.tsx — AD-513 floating-panel pattern.
ui/src/store/useStore.ts:260-542 — crewManifest slice pattern (state + actions).
ui/src/App.tsx:19,22-50,133-135 — toggle + mount points.

# AD-523c — superseded by AD-562:
decisions-era-4-evolution.md:2337
  3. AD-523c (Ship's Records Dashboard) — planned feature for records browsing. AD-562 supersedes and absorbs this.
decisions-era-4-evolution.md:2350
  | AD-562 supersedes AD-523c | AD-523c (Ship's Records Dashboard) was a simpler browsing view. AD-562 is the full-featured replacement... |
docs/development/roadmap.md:4237
  AD-523c (Ship's Records Dashboard — AD-562 supersedes/absorbs this planned feature)
docs/development/roadmap.md:4225
  AD-562: Ship's Records Knowledge Browser — Obsidian-Style HXI with 3D Knowledge Graph (planned, OSS+commercial...)

# GH #98 itself:
Title:   "AD-523a-c: HXI Ward Room & Records Overhaul"
State:   open
Created: 2026-04-08 (lagging the codebase — 523a shipped after creation)
```

Every concrete claim in this dispatch maps to a grep hit above.

## Captain workflow

1. **Append wave 77 entry to `prompts/wave-plan.yaml`** under id `"77"`, after id `"76"`:
   ```yaml
     - id: "77"
       title: "AD-523 v1 Ward Room & Records Overhaul (1-build + 2 verify-only)"
       kind: combo
       depends_on: ["76"]
       dispatch_prompt: "prompts/WAVE-77-DISPATCH.md"
       prompts_already_drafted: true
       prompt_paths:
         - "prompts/ad-523b-crew-notebooks-browser.md"
       builder_required: true
       issues_to_close: [98]
       status: pending
       notes: |
         Closes GH #98 (umbrella AD-523 a/b/c). Reframe 3 → 1-build:
         AD-523a already shipped via BF-080 (DM channel viewer);
         AD-523c officially superseded by AD-562 in DECISIONS.md
         (Knowledge Browser with 3D graph + backlinks); only AD-523b
         (Crew Notebooks Browser) builds in this wave — HXI-only panel
         on top of AD-434 RecordsStore endpoints which are already
         shipped. Vitest-only test delta (+12 to +18 window).
         Baseline 11498 → expected 11498 (pytest unchanged; vitest gate
         covers the new panel separately).
   ```
2. **Builder runs `prompts/ad-523b-crew-notebooks-browser.md`** end-to-end. Outputs: 1 new component, 1 new vitest test file, 3 modified UI files, 2 tracking-only edits (PROGRESS.md, roadmap.md). NO Python source touched. NO new pytest files.
3. **Pre-commit gate (Builder responsibility):**
   - `cd ui && npx vitest run` — new tests pass; no existing vitest test regresses.
   - `pytest tests/ -q -n 4 --dist=loadfile` — collects **11498**, identical to baseline (Δ = 0).
   - `git status` shows the expected file set; no `src/probos/` modifications; no new pytest files.
4. **Update `PROGRESS.md`** (top of the era-4 progress block) with one Wave 77 entry summarizing the 1-build + 2 verify-only resolution.
5. **Update `docs/development/roadmap.md`:**
   - Line 2774: AD-523a status row stays "✅ **COMPLETE** (via BF-080)" — no edit needed (already correct).
   - Line 2775: AD-523b — flip prose from planned description to: `**AD-523b: Crew Notebooks Browser** — ✅ **COMPLETE** (Wave 77). HXI panel...` (preserve the existing scope summary as the post-tag explanatory line).
   - Line 2776: AD-523c — flip to: `**AD-523c: Ship's Records Dashboard** — ⛔ **CLOSED — superseded by AD-562** (Knowledge Browser w/ 3D graph). See decisions-era-4-evolution.md:2337-2350 and AD-562 entry at line 4225.`
   - Line 2770: tag the AD-523 umbrella from `*(AD-523, planned, OSS)*` to `*(AD-523, complete — all sub-ADs resolved, OSS, Issue #98)*`.
6. **Commit:** `Wave 77 close: AD-523 ward room & records overhaul — 1 build (523b) + 2 verify-only (523a shipped via BF-080, 523c absorbed by AD-562) (#98)`.
7. **Archive** `prompts/WAVE-77-DISPATCH.md` and `prompts/ad-523b-crew-notebooks-browser.md` to `prompts/archive/` after the GH close.
8. **Close GH #98** with the verify-first evidence + commit hash + sub-AD-by-sub-AD resolution table.
9. **Update memory `/memories/session/wave-queue-batch2.md`** with `W77 #98 done (combo: 523b built; 523a/523c verify-only; baseline 11498)`.

## Hard-stop conditions

1. **Phantom API in implementation.** Every method asserted in `prompts/ad-523b-crew-notebooks-browser.md` is verified against HEAD `4479ec4` in the prompt's "Verified Against Codebase" section. If the Builder finds a mismatch (e.g. `/api/records/documents` 404s, `RecordsStore.list_entries` signature differs), → hard stop, surface to Architect.
2. **Architectural change required.** AD-523b is HXI-only. If the Builder concludes a backend change is required (new endpoint, new field on `NotebookEntry`-equivalent, new RecordsStore method), → hard stop. Architect re-scopes — the dispatch's "no backend changes" invariant is a hard line.
3. **Source code edits under `src/probos/`.** Any Python source file modification → hard stop. AD-523b is HXI-only by design.
4. **New pytest test file added.** Any `tests/test_ad523*.py` → hard stop. The dispatch states pytest delta is 0; backend is verify-only; no new Python tests are warranted.
5. **HXI emoji.** Any emoji character (👍, 📓, 🔊, etc.) introduced into `NotebooksPanel.tsx` or any other UI file → hard stop. HXI Design Principle #3 prohibits emoji; all glyphs must be inline SVG with `strokeWidth: 1.5`. The single `×` close character in the prompt is the Unicode multiplication sign, not an emoji — Builder may keep it OR replace with the existing `Close` import from `components/icons/Glyphs` (used by `WardRoomPanel.tsx`).
6. **Commercial leak.** Any pricing, revenue, customer-count, professional-services, GTM, or competitive-positioning language introduced into the prompt body, the panel component, the roadmap entry, or the GH close comment → hard stop. AD-523/523a/523b are wholly OSS. The AD-562 reference must remain to its existing public planned-status entry only — do NOT introduce new commercial detail about AD-562 in any Wave 77 artifact.
7. **Test count drift.** Pytest full gate must report **11498 collected**. Any drift (e.g. 11497 from a serendipitously-skipped test, 11500 from a bonus test) → hard stop, surface to Architect.
8. **Working-tree drift.** Untracked changes in `src/`, `tests/`, `config/`, or `data/` paths after the Builder's commit → hard stop. Only `ui/src/` (3 modified + 2 new), `PROGRESS.md`, `docs/development/roadmap.md`, and the two archived prompts may be modified.
9. **Wave-10 convention #14 / #3 collisions.** No new transitional flag with `default=True`. No deprecation of any existing API. (Not expected to apply, but stated for completeness.)

## Acceptance criteria

1. `git status` (post-Builder) shows exactly:
   - `M ui/src/store/types.ts`
   - `M ui/src/store/useStore.ts`
   - `M ui/src/App.tsx`
   - `?? ui/src/components/NotebooksPanel.tsx` (new)
   - `?? ui/src/__tests__/NotebooksPanel.test.tsx` (new)
   - `M PROGRESS.md`
   - `M docs/development/roadmap.md`
   - `M prompts/wave-plan.yaml` (id `"77"` entry)
   No other files.
2. **Vitest gate** `cd ui && npx vitest run` — new `NotebooksPanel.test.tsx` reports 8 passing; no pre-existing vitest test fails.
3. **Pytest full gate** `pytest tests/ -q -n 4 --dist=loadfile` — **11498 collected, 11498 passed, 16 skipped** (or whatever the current skip count is at HEAD `4479ec4`). Δ vs baseline = 0.
4. PROGRESS.md Wave 77 entry summarizes a/b/c resolution in one paragraph.
5. roadmap.md AD-523 umbrella + sub-AD lines tagged per the Captain workflow above.
6. wave-plan.yaml id `"77"` entry committed with `status: done` after Builder gate passes.
7. GH #98 closed with verify-first evidence + commit hash + the three-row resolution table.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — specifically: HXI emoji prohibition; SOLID-S (new component does only browse/search, no write surface); no fire-and-forget tasks; type annotations on all exported interfaces; classification-aware reads via existing `reader=captain` query param (defense in depth — backend already enforces classification at records_store.py:719-727).

## Commercial-leak audit

Clean.

- AD-523 umbrella: tagged OSS at `docs/development/roadmap.md:2770`.
- AD-523a: shipped (BF-080), no commercial surface.
- AD-523b: HXI panel, Captain-readable, OSS only. No paywall, no tier gating, no enterprise SKU language.
- AD-523c: closed-as-superseded; the supersession reference points at AD-562 which carries `*(planned, OSS+commercial)*` in its existing public entry. **No new commercial detail about AD-562 is introduced in Wave 77 artifacts** — the cross-reference is purely "see roadmap entry at :4225 for design status." This satisfies the OSS-vs-Commercial-tag rule from `.github/copilot-instructions.md` ("the `*(Commercial)*` tag means 'see commercial repo for full scope' — it is NOT permission to include commercial details inline").
- No `*(Commercial)*` deferral filed in this wave.
- No pricing/revenue/customer/professional-services/GTM/competitive language in the dispatch, build prompt, or component code.
- No private-repo content or GTM positioning leaked. No "Great Artists Steal" pattern descriptions. No tier specifications.

## Review history

- **Pass 1 (initial draft):** Confirmed AD-523a shipped via BF-080 (3 independent grep hits across roadmap + DECISIONS); confirmed AD-523c supersession (2 hits in decisions-era-4 + 1 in roadmap); confirmed AD-523b backend fully shipped (5 RecordsStore methods + 9 router endpoints); HXI panel pattern verified via CrewRosterPanel + WardRoomPanel reads; reframe to 1-build + 2 verify-only.
- **Pass 2 (verify-first sweep against HEAD `4479ec4`):** Spot-checked all 7 anchor lines in `useStore.ts` (260, 261, 303, 304, 476, 477, 542); all 3 anchors in `App.tsx` (19, 22, 133); all 5 method signatures in `records_store.py`; confirmed `data/ship-records/notebooks/` directory exists (empty in dev workspace, populated in production per roadmap.md:2775); confirmed Vitest test location at `ui/src/__tests__/`; confirmed `WardRoomPanel.test.tsx` mocking pattern. Phantom-API risk on the build prompt: **0** — every method, endpoint, and store anchor cited exists at HEAD.
- **Pass 3 (anti-pattern scan):** No phantom APIs in either dispatch or build prompt. No commercial leak (audit section above is exhaustive). No scope creep (build prompt's "What This Does NOT Change" enumerates 9 explicit out-of-scope items). No new transitional flag. No deferral hidden as a closure (523a/c are genuinely closed, not deferred). No fire-and-forget patterns required by the design (all fetches are awaited; closing the panel does not need cleanup tasks). Test delta sized within +12/+18 window: 8 vitest tests in the floor + Builder may add boundary cases up to ~+10 more.
- **Pass 4 (Wave-71/75/76 parity check + commercial-leak final):** Same dispatch shape as Wave 76 (verdict table + reframe + verify-first + Captain workflow + hard-stops + acceptance + commercial-leak audit + review history). Same wave-plan.yaml entry shape as id `"75"` (kind: combo for hybrid build + close; status: pending until Builder finishes). Same memory update line shape as Wave 75. AD-562 reference is read-only — does NOT introduce new commercial scope, simply cites the existing public roadmap entry where AD-562 lives. No emoji in any artifact (verified via re-read). Final commercial-leak audit: **clean** — `*(Commercial)*` tag is referenced once via cross-mention to AD-562's existing tag at roadmap.md:4225, not asserted on Wave 77's deliverables. Per `.github/copilot-instructions.md` "Commercial-tagged AD entries (HARD RULE)" — Wave 77 introduces zero pricing, revenue, customer counts, professional-services positioning, or GTM language.
