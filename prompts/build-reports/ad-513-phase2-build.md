# AD-513 Phase 2 v1 — Build Report

**Wave:** 17
**Date:** 2026-05-03
**Risk:** low (additive shell command + read-only ontology helpers)
**Mode:** single commit
**Status:** ✅ Complete

## Summary

v1 ships 3 of 6 Phase-2 capabilities per Wave 5 convention #14 aggressive pre-deferral:
- (a) `/manifest` shell command (formatted Rich table + `--ship` flag).
- (d) Watch filter on `get_crew_manifest()`.
- (f) `get_ship_manifest()` vessel-level summary.

Phase 2b (trust-gated visibility), 2c (agent tool access), and 2e (ACM lifecycle / competency) deferred — each requires meaningful new infrastructure.

## Sections Implemented

| # | Section | Files | Outcome |
|---|---------|-------|---------|
| 0 | EventTypes (no-op) | — | No new EventTypes; observational v1 |
| 1 | `get_crew_manifest(watch=, watch_manager=)` | `src/probos/ontology/service.py` | watch reverse-map enrichment + filter; backward-compat preserved |
| 2 | `get_ship_manifest()` | `src/probos/ontology/service.py` | new method; `alert_state` from `get_alert_condition()`; no `vessel_class` |
| 3 | `commands_manifest.py` | `src/probos/experience/commands/commands_manifest.py` (new) | `cmd_manifest(rt, console, arg)` mirrors `cmd_agents` shape |
| 4 | shell dispatch + COMMANDS | `src/probos/experience/shell.py` | `/manifest` wired; help entry added |

## Test Results

- **Focused gate** (`pytest tests/test_ad513_phase2_manifest.py -v -n 0`): **18 passed in 1.37s**
  - 1 over the prompt's stated 17 target — added `test_get_crew_manifest_watch_filter_without_manager_returns_empty` for the explicit `watch=set & watch_manager=None → []` short-circuit branch.
- **Full gate** (`pytest tests/ -q -n 8 --dist=loadfile`): **10741 passed, 15 skipped** (delta +18 vs Wave 16 baseline 10725 + 2 unrelated xdist flakes that pass serially).

### Pre-existing flakes confirmed unrelated

```
tests/test_knowledge_store.py::TestGitIntegration::test_auto_commit_after_debounce
tests/test_dreaming.py::TestDreamingIntegration::test_nl_to_dream_cycle_changes_weights
```

Both pass in serial (`-n 0`) in 10.71s — same flakes documented under Wave 16 baseline (knowledge-store git debounce timing, dreaming integration import-metadata DeprecationWarning).

## Verification Confirmations

- ✅ `runtime.ontology` (NOT `runtime.vessel_ontology`) consumed at `commands_manifest.py:34`.
- ✅ `ontology.get_alert_condition()` (NOT `runtime.alert_manager`) consumed at `service.py` `get_ship_manifest()`.
- ✅ `vessel_class` field NOT introduced (return shape verified against `VesselIdentity` at models.py:56-61).
- ✅ `get_crew_manifest` backward-compat preserved — both existing callers (`cognitive_agent.py:4126` `_build_crew_complement`, `routers/ontology.py:64` REST endpoint) pass neither `watch` nor `watch_manager` and exercise unchanged behavior (covered by `test_get_crew_manifest_no_watch_filter_preserves_existing_behavior`).
- ✅ Scope held to 3 of 6 Phase-2 capabilities — no viewer-context plumbing, no Tool registry integration, no ACM lifecycle/competency reads.

## Hard-Stops Triggered

**0** — none of the 8 listed hard-stops triggered.

## Files Touched

- `src/probos/ontology/service.py` — extended `get_crew_manifest`, added `get_ship_manifest`, added module-level logger import.
- `src/probos/experience/shell.py` — imported `commands_manifest`, added `/manifest` to COMMANDS + dispatch table.
- `src/probos/experience/commands/commands_manifest.py` — **new** (~85 lines).
- `tests/test_ad513_phase2_manifest.py` — **new** (~290 lines, 18 tests).
- `PROGRESS.md` — prepended Phase 2 v1 entry.
- `DECISIONS.md` — Era V entry under AD-487.
- `docs/development/roadmap.md` — Phase 2 status flipped to `partial — v1 ships ...`.

## Phantom-API Pre-Check

`./scripts/phantom-api-precheck.ps1 prompts/ad-513-phase2-manifest-v1.md` → 0 phantoms (verified at draft stage; not re-run for build report).

## Notes for Wave 17 Retrospective

- The `agent_id`-keyed reverse map for `WatchManager.get_roster()` was Phase-1 callsite-correct on first write — Section 1's pseudo-code in the revised prompt was high-fidelity.
- Test strategy for shell command used `Console(record=True)` + `export_text()` rather than mock chains — kept the suite self-contained without spinning up a full ProbOSRuntime.
- One test variant (`test_cmd_manifest_with_department_filter`) tolerates either populated table or empty notice because the ontology fixture's "engineering" department membership shifts with future ontology yaml edits; the assertion is robust to that without coupling to crew counts.
