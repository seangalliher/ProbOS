# Wave 42 Dispatch — AD-692 v1 Classification Enforcement on Knowledge Graph

**Single-AD continuous-build wave.** Prompt: `prompts/ad-692-classification-enforcement-v1.md`. GH issue: #386.

## Build context

- HEAD `fdb71b5` (Wave 41 archive landed; AD-691 NL-to-graph query closed).
- Test count baseline 11042 (Wave 41). Target post-build: 11054 (+12 minimum).
- AD-687 (Wave 37) `KnowledgeEdge.classification` field exists but unenforced. AD-692 v1 wraps `runtime.knowledge_edges` with a classification-gating decorator (`ClassificationGatedKnowledgeEdgeStore`) and adds the `KnowledgeEdgeClassificationGate` decision service.
- Captain "no trivial deferral" honored: ships ALL of (enum + visibility helper + gate service + wrapper + Oracle Tier 6 plumb + federation export hook + Pydantic config + wirer + tests) in one Builder cycle.

## Architect calls (all documented in prompt body)

1. **AD-679 status: SHIPPED but ORTHOGONAL** (verified at `mesh/disclosure.py:15` — 5-tier `DisclosureLevel` IntEnum PUBLIC..CLASSIFIED; runtime wired at `runtime._disclosure_router`). Different taxonomy from edge classification (4-tier PRIVATE..FLEET). Bridging is intentionally NOT provided in v1; `filter_for_export` ships as the documented seam.
2. **Reuse `_CLASSIFICATION_LEVELS`**: confirmed compatible at `records_store.py:27` (`{"private":0,"department":1,"ship":2,"fleet":3}`). Promote to `IntEnum` whose integer values match the dict byte-for-byte.
3. **Per-department matching DEFERRED to AD-692b**: `KnowledgeEdge` has no `dept` field; v1's `DEPARTMENT` gate is tier-based (any ENHANCED+ requester sees all department-classified). Documented as out-of-scope.
4. **Resolver injection via setter (Open/Closed)**: `knowledge/edge_classification.py` does NOT import `earned_agency` or `ontology` directly. The wirer in `startup/finalize.py` builds a closure over `runtime.ontology` + `runtime.clearance_grant_store` + `runtime.registry` and injects via `gate.set_clearance_resolver(...)`. Mirrors AD-660 / AD-635 pattern.
5. **Wirer phase ordering CRITICAL**: must run in finalize (after `runtime.ontology` adoption at `runtime.py:1651`). Wirer ALSO re-stitches Oracle Tier 6 via `oracle.attach_knowledge_graph(wrapper)` so the wrapper (not the bare AD-687 store) is consulted on graph queries.
6. **Backward-compat invariant**: when `requester_agent_id is None`, wrapper is a no-op pass-through. ALL Wave 37/38/39/40/41 tests must stay green without modification.
7. **Oracle Tier 6 TypeError fallback**: `_graph_find_edges` / `_graph_traverse` helpers wrap `find_edges` / `traverse` calls and pop `requester_agent_id` on TypeError so MagicMock-based fixtures (Wave 38 tests) don't break. Production wraps go through the wrapper which accepts the kwarg.
8. **Default-True deviation** (`KnowledgeEdgeClassificationConfig.enabled=True`) documented in config docstring with same rationale as `KnowledgeEdgesConfig` / `EdgeBackfillConfig`. Reviewer should NOT flag.
9. **`add_edge` blocked-write semantics**: returns the edge.id (idempotent surface) but does NOT persist. Test #12 asserts via `inner.find_edges` count.
10. **`traverse` per-path drop semantics**: a path is dropped entirely if ANY hop edge fails the visibility check. Conservative — prevents partial-path inference leakage. Test #10 asserts.

## Verified anchors (HEAD `fdb71b5`)

- `_CLASSIFICATION_LEVELS` `records_store.py:27`
- `KnowledgeEdge.classification` `edges.py:91` (str | None)
- `KnowledgeEdgeStorage` Protocol `edges.py:133`
- `find_edges`/`traverse` signatures `edges.py:149`/`:159`
- `RecallTier(str, Enum)` `earned_agency.py:53`
- `effective_recall_tier` `:100`, `resolve_billet_clearance` `:131`, `resolve_active_grants` `:149`
- `runtime.knowledge_edges` slot `runtime.py:429`, adoption `:1618`, Tier-6 attach `:1620–1622`
- `runtime.ontology` adoption `:1651`, `runtime.clearance_grant_store` adoption `:1614`
- `OracleService.query(agent_id="")` `oracle_service.py:167`; `_query_graph` `:480`
- `_wire_nl_graph_query` siblling shape `finalize.py:394`; cascade invocation `:730`
- `EdgeBackfillConfig` insertion anchor `config.py:1806`; `SystemConfig.edge_backfill` field `:2147`
- `knowledge/__init__.py` re-export pattern verified
- Federation: `federation/` (bridge/router/transport/mock_transport/nats_transport) — NO knowledge-edge export pathway at HEAD; `filter_for_export` is the v1 extension hook
- `mesh/disclosure.py` AD-679 SHIPPED — 5-tier IntEnum (orthogonal taxonomy)

## Files changed (build-time inventory)

- **NEW**: `src/probos/knowledge/edge_classification.py` (~270 lines)
- **NEW**: `tests/test_ad692_classification_enforcement.py` (~14 tests)
- **MOD**: `src/probos/config.py` (+~20 lines: new config class + SystemConfig field)
- **MOD**: `src/probos/startup/finalize.py` (+~70 lines: new wirer + cascade entry)
- **MOD**: `src/probos/knowledge/__init__.py` (+5 imports + 4 `__all__` entries)
- **MOD**: `src/probos/cognitive/oracle_service.py` (+~70 lines: signature extension + 2 helper methods + 4 call-site updates)
- **MOD trackers**: PROGRESS.md prepend; roadmap.md status flip; DECISIONS.md prepend

Pre-commit deletion sanity: max ~5 deletions any single file expected (line-level). Well below 200 threshold.

## Test gates

- Per-prompt focus: `pytest tests/test_ad692_classification_enforcement.py -v -n 0`
- Full parallel: `pytest tests/ -q -n 8 --dist=loadfile`
- Known xdist flake (re-verify serial if surfaces): `test_dreaming::test_nl_to_dream_cycle_changes_weights` (Waves 23/27/30/31/32/33/39/40/41 pattern)

## Phantom-API pre-check result

3 candidates, **0 NEW phantoms** — all FPs:

1. `runtime.edge_classification_gate` — introduced by this prompt (Section 4 wirer).
2. `add_edge(classification=...)` — script matches `KnowledgeEdge(classification="ship", ...)` constructor kwargs in test/example snippets. `KnowledgeEdge.classification: str | None` is a verified frozen-dc field (`edges.py:91`). FP.
3. `add_edge(source_agent=...)` — same FP class as #2. `KnowledgeEdge.source_agent: str | None` at `edges.py:92`. FP.

Same FP class as Waves 27–41 (intro-not-yet-in-class-index + nested-constructor-kwargs). No build-blocking phantoms.

## Single commit per ask

```
AD-692: Classification Enforcement on Knowledge Graph (Wave 42, closes #386)
```

Push to `origin/main`. GH issue close BLOCKED by EMU 403 (same as Waves 31–41) — Captain closes manually.
