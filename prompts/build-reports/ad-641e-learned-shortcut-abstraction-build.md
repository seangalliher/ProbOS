# AD-641e Build Report

**Date:** 2026-05-02
**Wave:** 9B (slot 1 of 2)
**Baseline:** 10603 passed, 15 skipped

## Summary

Shipped `LearnedShortcutBackend` Protocol + `LearnedShortcutRegistry` + `WorkflowCacheBackend` adapter under new `src/probos/cognitive/learned_shortcuts/` package. WorkflowCache source unchanged (Open/Closed). Cognitive JIT adapter genuinely-deferred (service does not yet exist).

## Files

- **New:** 4 files in `src/probos/cognitive/learned_shortcuts/` (`__init__.py`, `protocol.py`, `registry.py`, `workflow_cache_adapter.py`)
- **New:** `tests/test_ad641e_learned_shortcuts.py` (14 tests)
- **Modified:** `src/probos/events.py` (+2 EventTypes), `src/probos/config.py` (+1 Pydantic model + SystemConfig field), `src/probos/startup/finalize.py` (wiring block after AD-641f), `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`

## Tests

- Focused: 14/14 pass at `-n 0` (one extra vs prompt's stated 13 — prompt enumeration counted 4b as a sibling but I broke it out as a discrete test; non-decreasing either way)
- Regression: `tests/test_workflow_cache.py` 23/23 pass — WorkflowCache untouched.

## Diff stat

11 files changed, 415 insertions(+), 3 deletions(-).

## Hard-stops triggered

None.

## Deferred nits

None.

## Convention compliance

- Convention #7 (no theater): JIT adapter genuinely-deferred (service absent).
- Convention #14 (aggressive pre-deferral): 3 grandchildren tagged (`AD-641e-i`/`-ii`/`-iii`).
- Convention #18 (real adopters in tests): registry tests use real `WorkflowCacheBackend` + `_StubWorkflowCache`; minimal-stub test exercises structural typing independently.
- Open/Closed: mechanical regression guard in test #14 asserts the WorkflowCache public surface is intact.
