# Wave 36 Dispatch — AD-686 v1 Oracle Absorbs SemanticKnowledgeLayer

**Status:** Pending
**Issue:** #380 (closes on merge)
**Prompt:** [`prompts/ad-686-oracle-absorbs-semantic-v1.md`](ad-686-oracle-absorbs-semantic-v1.md)
**Wave plan slot:** id="36" (already populated, status=pending)
**Predecessor:** Wave 35 (AD-635 v1 Clinical Telemetry, commit `8f91624`, gate 10957)
**Expected gate after build:** 10968 (+11)

---

## v1 Scope (one line)

Add `_query_semantic()` (Tier 5) to `OracleService`; introduce a public `runtime.oracle` accessor; migrate **all three** read-path consumers (`introspect.py`, `organizer_agents.py`, `commands_knowledge.py::cmd_search`) to query through Oracle. `SemanticKnowledgeLayer` is unchanged.

**Deferred to AD-686b–d:** write-path migration; removing `runtime._semantic_layer`; tier reordering.

## Phase Context

This is **Phase A, Foundation** of the Unified Knowledge Graph + Oracle Unification stack (`docs/research/unified-knowledge-graph.md` §Phase A). AD-686 is the first of four Phase-A ADs: AD-686 (this), AD-687 (knowledge edges), AD-688 (Tier 6 graph + post-merge expansion), AD-689 (edge backfill).

## Dependencies — Verify-First Findings (HEAD `af418f3`)

| Dep | Status | Used in v1? |
|---|---|---|
| AD-462e (OracleService) | Shipped (`oracle_service.py:43`, ctor `cognitive_services.py:495`, runtime wire `runtime.py:1323`) | YES — extended (new param + tier method + late-bind setter + public alias) |
| Phase 21 (`SemanticKnowledgeLayer`) | Shipped (`semantic.py:22`); `search()` async at `:256`; result dict `{type,id,document,score,metadata}` at `:295–303` | YES — read-path delegation only |
| Wirer order | `oracle_service` built in cognitive phase (cognitive_services.py:495); `semantic_layer` built later in structural phase (structural_services.py:55–69) — late-bind required | acknowledged in Section 1a (`attach_semantic_layer`) and Section 2b (runtime stitching at line 1525) |

**Zero `_query_semantic` / `attach_semantic_layer` symbols in src today** — fully greenfield surface additions.

## Decision Log (architect calls)

1. **Late-bind setter, not constructor-only.** Oracle is built before semantic layer exists in the startup order. `attach_semantic_layer(layer)` keeps construction Open/Closed and idempotent.
2. **Public `runtime.oracle` alias.** Wave 5 #1 (public over private) — `_oracle_service` preserved for the 3 existing private consumers (`cognitive_agent.py:5164–5168`, `routers/system.py:337`); new code uses `runtime.oracle`.
3. **Default active tiers extended.** `["episodic","records","operational","archive"]` → `["episodic","records","operational","archive","semantic"]`. Behavior change is additive — when no semantic layer is attached, Tier 5 returns `[]` and logs at debug.
4. **Stats panel stays on direct layer.** `cmd_search` keeps `layer.stats()` because Oracle has no equivalent surface in v1 (collection counts are a layer-side concern, not a tier-merged concept). Stats migration deferred — `runtime._semantic_layer` is preserved.
5. **All 3 consumers migrated in v1, not split.** Each consumer's diff is ≤25 lines. Total migration touch ≤75 lines — well under the 100-line scope-down threshold. Splitting introduces a phantom mid-state where Oracle owns Tier 5 but consumers still bypass it.
6. **`runtime.oracle` fallback to `_oracle_service`.** Each consumer uses `getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)` — preserves test fixtures that may patch only the private attr (e.g., `test_commands_knowledge.py:62` patches `_semantic_layer` directly via `MagicMock(spec=ProbOSRuntime)`).
7. **Side benefit — `organizer_agents.py:146` missing-`await` bug is silently fixed.** The pre-existing call `self._runtime._semantic_layer.search(query, limit=5)` (no `await`) was a real bug because `search()` is `async def`. Routing through `await oracle.query(...)` properly awaits. Documented inline in Section 3b.

## Phantom-API Pre-Check

```
$ ./scripts/phantom-api-precheck.ps1 prompts/ad-686-oracle-absorbs-semantic-v1.md
=== prompts/ad-686-oracle-absorbs-semantic-v1.md ===
  Clean — no phantom symbols detected.

=== Summary ===
Prompts scanned: 1
Total phantom candidates: 0
```

**Cleanest result since Wave 27.** The script correctly resolves `OracleService._query_semantic` and `OracleService.attach_semantic_layer` as intra-prompt-introduced (Sections 1a/1d). No FPs to document — the test-fixture sections in Section 4 are described in prose, not literal `class:SimpleNamespace` source, so no stdlib FPs surface either.

## Test Plan (11 over 7 floor by 4)

1. `test_query_semantic_method_shape` — service surface present + idempotent setter accepts `None`.
2. `test_query_semantic_happy_path_with_stub_layer` — 3 dicts → 3 `OracleResult`s with `source_tier="semantic"`, provenance `[semantic: <type>]`, metadata flattening.
3. `test_query_semantic_none_layer_returns_empty_and_logs` — no layer → `[]` + DEBUG `"Tier 5"` line.
4. `test_query_semantic_types_passthrough` — `types=` and `limit=` forwarded to `layer.search`.
5. `test_query_semantic_score_coercion` — `None` and `"0.7"` score values coerce cleanly.
6. `test_semantic_in_default_active_tiers` — default `tiers=None` invokes `_query_semantic` exactly once.
7. `test_attach_semantic_layer_late_bind_works` — None at ctor, then attach, then query returns rows.
8. `test_introspect_search_knowledge_uses_oracle` — `IntrospectionAgent._search_knowledge` awaits `oracle.query(tiers=["semantic"])` and projects to legacy dict shape.
9. `test_organizer_note_taker_uses_oracle_and_awaits` — `NoteTakerAgent.perceive(action="search")` awaits Oracle (regression on missing-`await` bug).
10. `test_cmd_search_uses_oracle_and_keeps_stats_panel` — `/search` shell command awaits Oracle AND still calls `layer.stats()` for panel.
11. `test_end_to_end_query_returns_normalized_oracle_results` — real `OracleService` + stub semantic + stub episodic → merged sorted list with `source_tier="semantic"` provenance entries.

**Test count baseline:** 10957 (Wave 35).
**Expected after build:** 10968 (+11 exact). _Drop targets if count drift: tests #5 and #11._

## Build Quality Reminders

- **Property collision (Wave 32 retrospective).** `OracleService` is NOT a `CognitiveAgent` subclass; new field `_semantic_layer` does not collide with any existing property. The `runtime.oracle` public alias was checked against `runtime.py` for prior `def oracle\b` — none. No collision.
- **Wirer ordering.** Section 2b (late-bind at `runtime.py:1525`) MUST come after `self._semantic_layer = semantic_layer` and before any consumer's first call. Current insertion site preserves this ordering.
- **MagicMock backward-compat.** Existing tests use `MagicMock(spec=ProbOSRuntime)` and set `rt._semantic_layer = None` (e.g., `tests/test_commands_knowledge.py:28`). The migrated consumers' `getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)` chain returns `None` against these mocks → consumers fall through to legacy `await layer.search(...)` path → existing tests must continue to pass without edits. **Builder MUST verify** `tests/test_commands_knowledge.py` and `tests/test_experience.py::test_search_no_semantic_layer` still pass post-migration.
- **`test_commands_knowledge.py::test_cmd_search_no_query`** sets `mock_runtime._semantic_layer = MagicMock()` and expects "Usage" output — this should still work because the Usage gate fires before Oracle is consulted.
- **Pre-commit deletion sanity.** Diff per file:
  - `oracle_service.py`: ~50 added (Section 1a/1c/1d), 0 deleted, 8 modified (Section 1b active-tiers list).
  - `runtime.py`: 1 line added (Section 2a) + 9 lines added (Section 2b) — 0 deleted.
  - `introspect.py`: ~17 added, 4 deleted.
  - `organizer_agents.py`: ~17 added, 4 deleted.
  - `commands_knowledge.py`: ~16 added, 1 deleted.
  - Total: well below the 200-line single-file deletion threshold.
- **`runtime.oracle` is the SAME instance as `runtime._oracle_service`** — not a new construction. Section 2a is `self.oracle = cog.oracle_service`, NOT `self.oracle = OracleService(...)`.

## Out of Scope (Hard Limits)

| Out | Where it lives next |
|---|---|
| `SemanticKnowledgeLayer` write-path migration (`index_*` methods) | AD-686b |
| Removing `runtime._semantic_layer` attribute | AD-686c (forcing function: zero remaining direct consumers) |
| Tier numbering / unifying tier-name strings | AD-686d |
| `oracle.query_formatted` migration of any consumer | none of the 3 sites use it |
| New EventType, Pydantic config, router, or shell command | none |
| Federation / classification graph edges | AD-687 (Issue #381) |
| Tier 6 graph + post-merge expansion | AD-688 (Issue #382) |
| Edge backfill from existing data | AD-689 (Issue #383) |

## Success Criteria

1. Full parallel gate green at `pytest tests/ -q -n 8 --dist=loadfile`.
2. Test-count delta exactly +11 vs baseline 10957 → 10968 (tolerated drift: +9 if tests #5/#11 dropped).
3. `OracleService._query_semantic` exists with the spec'd signature; `attach_semantic_layer` is idempotent; constructor accepts `semantic_layer=` kwarg.
4. `runtime.oracle` is the same instance as `runtime._oracle_service`.
5. All three consumers route through Oracle when present; legacy fallback works when Oracle is absent (preserves existing MagicMock-based tests).
6. `runtime._semantic_layer` is still attached; `layer.stats()` still callable.
7. Phantom-API pre-check exits with 0 phantom candidates (matches draft-time result).
8. PROGRESS.md flipped from `AD-686` planned → `AD-686 v1 CLOSED`.
9. `docs/development/roadmap.md` AD-686 entry status flipped to `complete`.
10. DECISIONS.md AD-686 entry appended.
11. Issue #380 closed on merge (or surfaced for manual close per EMU 403).
