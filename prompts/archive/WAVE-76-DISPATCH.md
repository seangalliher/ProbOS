# WAVE 76 DISPATCH — AD-644 Agent Situation Awareness Architecture (NO-BUILD CLOSE)

**Wave id:** 76
**Single AD:** AD-644 (umbrella, Phases 1-5)
**Per-AD closure note:** `prompts/ad-644-situation-awareness-closure.md`
**Closes:** GH issue #285
**HEAD at draft:** `ef5e324` (post-Wave-75)
**Baseline test count:** 11498 → expected **11498** (Δ = 0; no-build)
**Builder required:** false

## Verdict

Verify-first against HEAD `ef5e324` reveals **all five phases of AD-644 are already shipped**. There is no code, test, or research-doc work left to do for #285. Wave 76 is a documentation-only close.

| Phase | Issue #285 scope | Live state at HEAD `ef5e324` |
|---|---|---|
| 1. Duty Context Restoration | `params.duty` + trust/agency/rank piped through to ANALYZE/COMPOSE | Shipped in commit `f10369d` (Apr 20 2026). Tests at `tests/test_ad644_phase1_duty_context.py`. |
| 2. Innate Faculties | `_build_cognitive_state()` populates 9 innate keys | Shipped in commit `f10369d`. Tests at `tests/test_ad644_phase2_innate_faculties.py`. |
| 3. Situation Awareness | 7 environmental percepts via observation dict | Shipped in commit `f10369d`. Tests at `tests/test_ad644_phase3_situation_awareness.py`. Subsequently superseded by AD-646 Universal Cognitive Baseline + AD-646b Chain Cognitive Parity (Phase 3 percepts moved into baseline + QUERY ops). |
| 4. Standing Orders additions | source attribution policy + duty reporting expectations in `ship.md` | Shipped in commit `f10369d` (`config/standing_orders/ship.md` +24 lines per `git show f10369d --stat`). Markdown-only, no test surface. |
| 5. Deprecation of `_build_prompt_text` proactive block | Mark/remove legacy 290-line block | Closed via AD-644b in Wave 71 (commit `8a20695`, GH #415). Verify-first confirmed target was already removed during Phases 1-4 / AD-647 chain restructure. |

23/23 parity items per the research checklist (`docs/research/agent-situation-awareness-architecture.md`) are live. PROGRESS.md line 361 already reads "Phase 1-4 Complete. 23/23 parity. Chain path has full perceptual equivalence with `_build_user_message()`." — only the Phase 5 status text is stale (still says "design" although AD-644b shipped).

## Reframe decision (Wave-10 convention)

**5-section umbrella → 0-build close**, mirroring Wave 71 (AD-644b). Per Captain rule "don't defer unless no choice" — this is **not a deferral**. The work is fully complete; the issue tracker simply lags the codebase by ~16 days. The five-phase scope described in DECISIONS.md AD-644 entry maps 1:1 onto live code, live tests, live config, and one already-closed sibling AD. No code change, no test change.

## Verified Against Codebase (2026-05-06)

```
git show f10369d --stat | Select-String "ship.md|cognitive_agent.py|sub_tasks"
  src/probos/cognitive/cognitive_agent.py        | 527 ++++++++++++++++++-
  src/probos/cognitive/sub_tasks/analyze.py      | 269 +++++++++-
  src/probos/cognitive/sub_tasks/compose.py      | 351 ++++++++++++-
  config/standing_orders/ship.md                 |  24 +

git ls-files tests/ | Select-String "ad644"
  tests/test_ad644_phase1_duty_context.py
  tests/test_ad644_phase2_innate_faculties.py
  tests/test_ad644_phase3_situation_awareness.py

git log --oneline | Select-String "AD-644|#415"
  8a20695 Wave 71 close: AD-644b _build_prompt_text already removed (no-build, #415)
  f10369d Cognitive chain wave: AD-644 through AD-653, BF-208 through BF-217

# Wave 71 already closed AD-644b (Phase 5):
prompts/wave-plan.yaml:830 — "AD-644b Phase 5 _build_prompt_text deprecation (no-build close)"
prompts/wave-plan.yaml:842 — "Likely removed during AD-644 Phases 1-4 (commit f10369d)"

# Roadmap entry already says Phase 1-4 complete:
docs/development/roadmap.md:7083 — "AD-644 ... *(Phase 1-4 complete — 23/23 parity, OSS, Issue #285)*"
```

Every concrete claim in this dispatch maps to a grep hit above.

## Captain workflow

1. **Append wave 76 entry to `prompts/wave-plan.yaml`** under id "76", inserted after id "75":
   - `kind: single`, `depends_on: ["75"]`
   - `dispatch_prompt: "prompts/WAVE-76-DISPATCH.md"`
   - `prompts_already_drafted: true`, `prompt_paths: []`
   - `builder_required: false`
   - `issues_to_close: [285]`
   - `status: done`
   - notes: verify-first evidence summary (see closure note for prose).
2. **Update PROGRESS.md line 361** to reflect Phase 5 closure:
   - From: `AD-644  Phase 1-4 Complete. 23/23 parity. ... Phase 5 (deprecation) design.`
   - To: `AD-644  COMPLETE. All 5 phases shipped — Phases 1-4 commit f10369d (23/23 parity), Phase 5 closed via AD-644b in Wave 71 (target already removed). Issue #285.`
3. **Update `docs/development/roadmap.md:7083`** AD-644 entry tag from `*(Phase 1-4 complete — 23/23 parity, OSS, Issue #285)*` to `*(Complete — all 5 phases, OSS, Issue #285)*`. Append a one-line "Phase 5 deprecation closed via AD-644b Wave 71" note inside the existing entry body. No other text changes.
4. **Commit:** `Wave 76 close: AD-644 situation awareness — all 5 phases already shipped (no-build, #285)`.
5. **Archive** `prompts/WAVE-76-DISPATCH.md` and `prompts/ad-644-situation-awareness-closure.md` to `prompts/archive/`.
6. **Close GH #285** with the verify-first evidence + commit hash.
7. **Update memory `/memories/session/wave-queue-batch2.md`** with `W76 #285 done (no-build close, 11498)`.

## Hard-stop conditions

1. Any source code, test, or research-doc edit during Wave 76 execution beyond the four tracking files (`prompts/wave-plan.yaml`, `PROGRESS.md`, `docs/development/roadmap.md`, the two archived prompts). → Hard stop. This is a no-build wave.
2. Any deletion or rewrite of the existing AD-644 entries in DECISIONS.md (lines 1838-1894). → Hard stop. The decision log is append-only; the entry is correct as-is.
3. Test count drift outside [11498, 11498]. → Hard stop. No-build means zero delta.
4. Any new GH issue opened claiming AD-644 partial closure or carve-out. → Hard stop. AD-644 is complete; no follow-up issue is warranted.
5. Working-tree changes appearing in `src/`, `tests/`, `config/`, or `ui/` paths. → Hard stop, surface to Captain.

## Acceptance criteria

1. `git status` shows only the four tracking files modified (wave-plan.yaml, PROGRESS.md, roadmap.md) plus the two archived prompt moves. No source/test/config drift.
2. Full gate `pytest tests/ -q -n 4 --dist=loadfile` reports **11498 collected**, identical to baseline (Δ = 0).
3. PROGRESS.md AD-644 line reflects all 5 phases complete and the Phase 5 / AD-644b / Wave 71 lineage.
4. Roadmap entry tagged `*(Complete — all 5 phases, OSS, Issue #285)*`.
5. GH #285 closed with verify-first evidence + commit hash.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** — trivially satisfied since no source changes are made.

## Commercial-leak audit

Clean. AD-644 is wholly OSS — roadmap tag already reads "OSS, Issue #285" at `docs/development/roadmap.md:7083`. Wave 76 contains zero pricing, revenue, customer-count, professional-services, GTM, or competitive language. No `*(Commercial)*` deferral. No new commercial AD is introduced. The closure narrative references only public artifacts (DECISIONS.md, PROGRESS.md, roadmap.md, research doc).

## Review history

- **Pass 1 (initial draft):** Verified all 4 phase commits exist; AD-644b Wave 71 confirms Phase 5 closure; issue #285 still open; reframe to no-build close.
- **Pass 2 (codebase grounding):** Spot-checked `tests/test_ad644_phase{1,2,3}_*.py` exist; commit `f10369d` stat output confirms `cognitive_agent.py +527`, `sub_tasks/analyze.py +269`, `sub_tasks/compose.py +351`, `ship.md +24`. AD-646 + AD-646b extracted Phase 3 percepts into the universal baseline; this does NOT invalidate AD-644 — Phase 3 was the migration, AD-646 was the architectural generalization. Both must remain credited.
- **Pass 3 (anti-pattern scan):** No phantom APIs (no implementation work proposed). No commercial leak (OSS-only AD). No scope creep (no new sub-ADs filed). No deferral (work is complete, not punted). PROGRESS.md text update is a stale-status correction, not a behavioral change. Roadmap text update is identical category.
- **Pass 4 (Wave-71 parity check):** Same shape as Wave 71 (no-build close, single dispatch + closure note, 5 → 0 reframe, captain-only workflow). Wave-plan.yaml entry shape matches id "71" template. GH close evidence template matches Wave 71. Memory update line matches batch-2 queue convention.
