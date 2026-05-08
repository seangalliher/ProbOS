# Memvid pattern 1 build report — QueryPlanner relational lookup

**Prompt:** `prompts/memvid-queryplanner-relational-v1.md`
**Builder:** Wave 130 builder (continuous mode)
**Date:** 2026-05-08
**Status:** SHIPPED
**Issue closed:** #490 (QueryPlanner only; VersionRelation enum + per-engine version are out of scope)
**Wave:** 130 (4 of 10)
**AD assigned:** AD-712

## Files Changed

- `src/probos/cognitive/query_planner.py` — new module: `QueryPlan` (frozen dataclass) + `QueryPlanner` (regex-driven classifier + `recall_with_fallback`).
- `src/probos/config.py` — new `QueryPlannerConfig` model + wiring on `SystemConfig`.
- `src/probos/startup/finalize.py` — wire `runtime.query_planner` after AD-707; isinstance-gated.
- `tests/test_memvid_queryplanner_relational.py` — 13 new tests.
- `DECISIONS.md` — AD-712 entry appended.

## Sections Implemented

- **D1.** `QueryPlanner` module — done. Three relational regexes (WHO/WHERE/WHEN) + `_clean_target` helper that strips trailing punctuation and courtesy words ("please", "now"). `recall_with_fallback` is fully async and never raises on classification.
- **D2.** `QueryPlannerConfig` Pydantic model — done; placed at top-level `SystemConfig` adjacent to `workflow_cron`. Default `enabled=False` (convention #14).
- **D3.** Pipeline wiring — done as runtime attribute exposure (`runtime.query_planner`). Per the prompt's "do NOT widen `EpisodicMemoryProtocol` if doing so requires updating > 5 mock sites" constraint, no Protocol widening was performed; consumers call `runtime.query_planner.recall_with_fallback(episodic, query, k)` directly. The setter-injection variant on `EpisodicMemory` is left as a deferred sub-AD (memvid-qp-injection-v1) since it requires touching `EpisodicMemory.__init__` and several mocks.
- **D4.** Tests — 13 cases (8 required + multiword target heuristic + trailing-punctuation trim + immutability + config defaults).

## Post-Build Section Audit

All four `D*` sections from the prompt have corresponding code changes. No omissions.

## Verify-First Findings

- ✅ `EpisodicMemory.recall(query, k)` at `episodic.py:1648`.
- ✅ `EpisodicMemory.recall_by_anchor(...)` signature at `episodic.py:2747` matches the kwargs the classifier emits.
- ✅ `AnchorFrame` fields (`participants`, `department`, `channel`, etc.) at `types.py:358`.
- ✅ `EpisodicMemoryProtocol.recall` at `protocols.py:45` (Protocol does NOT include `recall_by_anchor`).
- ✅ Greenfield: no existing `class QueryPlanner` in the codebase.

## Test Results

```
.\.venv\Scripts\pytest.exe tests/test_memvid_queryplanner_relational.py -v -n 0
13 passed in 0.32s
```

Full gate:
```
.\.venv\Scripts\pytest.exe tests/ -q -n 8 --dist=loadfile
12817 passed, 16 skipped, 175 warnings in 473.54s
```

Pre-Memvid: 12804 → +13 = 12817. Test count non-decreasing.

## Hard Constraints Honored

- ✅ No `VersionRelation` enum (forward marker memvid-versionrelation-v1).
- ✅ No per-engine-version enrichment (forward marker memvid-engineversion-v1).
- ✅ No modifications to `recall` / `recall_by_anchor` signatures.
- ✅ No LLM calls in `classify` — pure regex, deterministic.
- ✅ No `EpisodicMemoryProtocol` widening.
- ✅ Default `enabled=False`.
- ✅ Anchor-failure log at `warning` level (not `debug`) per Recommended R4.

## Pre-Commit Deletion Check

Top-5 staged files by line count — no file shows >200 deletions. Clean.

## Engineering Principles Compliance

- ✅ SOLID: classifier and recall router are single-responsibility; classification logic isolated in `_clean_target` + three regexes.
- ✅ Open/Closed: adding a new relational shape is a new regex + branch; no existing branch needs modification.
- ✅ Type annotations on all public methods (`QueryPlan`, `classify`, `recall_with_fallback`).
- ✅ Log-and-degrade on anchor-lookup failure (regression-tested via `caplog`).
- ✅ Boundary tests: empty query, whitespace-only query, multiword target heuristic, trailing-punctuation trim, anchor empty → semantic fallback, anchor exception → semantic fallback.
- ✅ Test isolation: `_FakeEpisodic` stub instead of MagicMock; tests track call lists per instance, no shared state.
- ✅ Immutability: `QueryPlan` is `frozen=True`; verified by test.
