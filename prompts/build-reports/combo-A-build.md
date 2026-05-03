# Combo A Build Report

**Date:** 2026-05-02
**Builder:** Wave 8 continuous-build (4 of 6) — single commit covering 7 child ADs

## Sections Implemented

| Section | File | Status |
|---|---|---|
| Section 0: 5 EventTypes | `src/probos/events.py` | ✅ Added `DREAM_MANIFEST_UPDATED`, `CAPTAIN_DM_PRIORITY_QUEUED`, `RECREATION_GAME_REGISTERED`, `CONTRASTIVE_RECALL`, `DEPT_PROFILE_APPLIED` after AD-472 anchor |
| AD-538b: DreamManifest | `src/probos/cognitive/dream_manifest.py` (new) + `dreaming.py` `DreamingEngine` | ✅ Stdlib JSON store with atomic write; `micro_dream` filters episodes via manifest |
| AD-572b: CaptainEngagementProvider | `src/probos/cognitive/captain_engagement.py` (new) + `proactive.py` `_gather_context` | ✅ Snapshot via runtime.bridge_alerts/ward_room; emits CAPTAIN_DM_PRIORITY_QUEUED |
| AD-573b: WorkingMemory extensions | `src/probos/cognitive/working_memory.py` | ✅ 3 new fields on snapshot; 3 bounded-ring helpers on manager |
| AD-576b: proactive.py LLM retry | `src/probos/proactive.py:693+` | ✅ 2 retries at [0.5, 1.5]s backoff before failure-counter increment |
| AD-526c: Recreation metadata | `src/probos/recreation/metadata.py` (new) + `service.py` | ✅ Extended `register_engine(engine, metadata=None)`; new `default_game` property + `get_metadata` accessor; emits `RECREATION_GAME_REGISTERED`. Existing API preserved (no DRY violation) |
| AD-655: Contrastive recall | `src/probos/cognitive/episodic.py` + `sub_tasks/evaluate.py` | ✅ `retrieve_contrastive_episodes` mid-band [0.4, 0.65]; `EvaluateHandler.__call__` populates `context["_contrastive_priors"]` |
| AD-656: Department profiles | `src/probos/config.py` + `sub_tasks/evaluate.py` | ✅ `DepartmentCognitiveProfile` + `DepartmentProfilesConfig`; `EvaluateHandler` overrides recall depth from profile; emits `DEPT_PROFILE_APPLIED` |
| Finalize wiring | `src/probos/startup/finalize.py` | ✅ `runtime.dream_manifest` + `runtime.captain_engagement_provider` (always-wired with try/except per Wave-5 convention #1) |
| Tests | `tests/test_combo_a_*.py` (7 new files) | ✅ 26/26 pass at `-n 0` |
| Tracking | `PROGRESS.md`, `docs/development/roadmap.md` (multiple anchors) | ✅ Updated |

## Test Results

- Focused gate: 7 test files combined → **26/26 passed in 1.28s** at `-n 0`
- Full parallel gate: **10,524 passed (+26 vs AD-472 baseline 10,498), 15 skipped, 151 warnings in 430.75s**

## Notes / Decisions

- **AD-538b: `DreamingEngine` not `DreamScheduler`.** Combo prompt verify-first cited "line 2664: class DreamScheduler" but the class with `__init__(router, trust_network, episodic_memory, config, ...)` accepting the manifest kwarg is `DreamingEngine` at `dreaming.py:54`. The standalone `DreamScheduler` at line 2701 is a higher-level scheduler; the consolidation logic with `_replay_episodes` lives on `DreamingEngine`. Implementation correctly targets `DreamingEngine`; test renamed to use `DreamingEngine` directly. Documented in test docstring as a verify-first refinement.
- **AD-575b dropped wholesale (theater per convention #7).** Confirmed by live grep: `runtime.self_summary_provider` does not exist anywhere in the codebase. Both halves of AD-575b (proactive context surfacing + DM forwarded content) would have been permanent no-ops. Wholesale deferred to a future AD that ships the upstream surface with a real consumer.
- **AD-526c extension-over-parallel.** Existing `register_engine` / `get_available_games` / `_engines` API preserved. New `_metadata` dict + `get_metadata` / `default_game` additive. No DRY violation.
- **AD-655 + AD-656 share `EvaluateHandler.__call__`.** Implemented as a single coherent pre-safety-checks block: department profile (if wired) overrides recall depth; contrastive recall (if episodic memory wired) populates `context["_contrastive_priors"]`. Both emit their respective EventTypes.
- **AD-576b retry block** uses tuple `_BACKOFFS_SECONDS = (0.5, 1.5)` — exactly two retries on top of the initial attempt = 3 total attempts before incrementing the failure counter. Only retries on transient LLM errors (the existing keyword set, hoisted to a shared `_LLM_ERROR_KEYWORDS` tuple to avoid duplication).
- **All 15 standing conventions applied.** Convention #6 (verify-first) caught the `DreamingEngine` vs `DreamScheduler` naming early. Convention #7 (no-theater) drove the AD-575b wholesale-drop. Convention #14 (aggressive pre-deferral) preserves AD-526c spectators / holodeck and AD-573c relational scope as deferred.

## Pre-Commit Sanity Check

19 files changed, ~880 insertions, ~17 deletions. Max per-file deletion: 6 lines (`recreation/service.py` for the `register_engine` extension; expected). Well under 200-line threshold.
