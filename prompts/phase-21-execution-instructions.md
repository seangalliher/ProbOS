# Phase 21 — Execution Instructions

## How To Use This Document

1. Read `prompts/phase-21-semantic-knowledge-layer.md` first (the full spec)
2. This document repeats the highest-risk constraints and provides execution-order guidance
3. Follow the steps in order. Run tests after EVERY step

## Critical Constraints (stated redundantly)

### AD Numbering — HARD RULE
- **Current highest: AD-240** (Phase 20)
- Phase 21 uses: AD-241, AD-242, AD-243, AD-244, AD-245, AD-246
- VERIFY by reading PROGRESS.md before assigning any AD number
- If AD-240 is NOT the latest, shift ALL AD numbers up accordingly

### Test Gate — HARD RULE
- Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` after EVERY step
- All 1409 existing tests must continue passing
- Do NOT proceed to the next step if any test fails
- Report test count after each step

### Scope — DO NOT BUILD
- No knowledge graph (relational store)
- No provenance system
- No confidence decay or knowledge lifecycle management
- No federation knowledge sync (but design is federation-ready — artifacts indexed with metadata that can carry `source_node` when federation sync is built. Cross-node semantic search will be critical for Noöplex emergence testing via TC_N across federated meshes)
- No changes to existing EpisodicMemory (it keeps its own collection)
- No duplicate episode indexing — query via `episodic_memory.recall()` instead
- No new background loops
- No LLM dependency for indexing/search
- No changes to EmergentDetector behavior beyond the two fixes

### Episode Collection — DO NOT DUPLICATE
- Episodes already have a ChromaDB collection managed by `EpisodicMemory`
- The SemanticKnowledgeLayer queries episodes via `episodic_memory.recall()`, NOT via its own collection
- Do NOT create a `sk_episodes` collection — this would double storage and desync

### Auto-indexing — MUST NOT BLOCK
- Every `index_*()` call in the runtime must be wrapped in try/except
- Indexing failures must never block or crash the main operation
- These are fire-and-forget enrichments, not critical-path operations

### Layer Architecture — MUST RESPECT
- SemanticKnowledgeLayer lives in `src/probos/knowledge/` (knowledge layer)
- It reads from KnowledgeStore (same layer) — allowed
- It reads from EpisodicMemory (cognitive layer) — higher reading from lower... actually both are at the cognitive/knowledge boundary. This is acceptable since the knowledge layer already imports from types.py
- It MUST NOT import from runtime, agents, experience, or substrate layers

## Execution Sequence

### Step 1: Phase 20 cleanup + reflect fix (AD-241)
- **Edit** `src/probos/substrate/identity.py` — add `parse_agent_id()` with module-level `_ID_REGISTRY`
- **Edit** `src/probos/cognitive/emergent_detector.py` — update `_extract_pool()` to use `parse_agent_id()`, cap `_all_patterns` at 500
- **Edit** `src/probos/cognitive/decomposer.py` — add rule 6 to `REFLECT_PROMPT`: parse structured data (XML, JSON, HTML, CSV) and present extracted content instead of describing the format
- Run tests → expect 1409 pass (existing tests unaffected)

### Step 2: SemanticKnowledgeLayer module (AD-242)
- **Create** `src/probos/knowledge/semantic.py`
- Pure new file, no existing code changes
- Run tests → expect 1409 pass

### Step 3: Runtime wiring (AD-243)
- **Edit** `src/probos/runtime.py` — create layer in start(), auto-indexing hooks, warm boot re-index, status(), shutdown
- Run tests → expect 1409 pass

### Step 4: Introspection + MockLLMClient (AD-244)
- **Edit** `src/probos/agents/introspect.py` — add `search_knowledge` intent
- **Edit** `src/probos/cognitive/llm_client.py` — add MockLLMClient pattern
- Run tests → expect 1409 pass

### Step 5: Shell + panels (AD-245)
- **Edit** `src/probos/experience/shell.py` — add `/search` command
- **Edit** `src/probos/experience/panels.py` — add `render_search_panel()`
- Run tests → expect 1409 pass

### Step 6: Tests (AD-246)
- **Create** `tests/test_semantic_knowledge.py`
- Target ~44 tests
- Run tests → expect ~1453 pass
- If any fail, fix before proceeding

### Step 7: PROGRESS.md update
- Update status line with new test count
- Add SemanticKnowledgeLayer to "What's Been Built"
- Add Phase 21 test summary to "What's Working"
- Add AD-241 through AD-246 to "Architectural Decisions"
- Mark "Semantic Knowledge Layer" as complete in roadmap
- Update EmergentDetector description for the Phase 20 fixes

## Key Design Decisions Summary

| AD | File | Decision |
|----|------|----------|
| AD-241 | `identity.py` + `emergent_detector.py` + `decomposer.py` | Phase 20 cleanup + reflect fix: `parse_agent_id()` with module registry for reliable pool extraction; `_all_patterns` capped at 500 entries; `REFLECT_PROMPT` rule 6 for structured data extraction (XML/JSON/HTML/CSV) — parses and presents content instead of describing the format |
| AD-242 | `knowledge/semantic.py` | `SemanticKnowledgeLayer` — ChromaDB collections for agents, skills, workflows, QA reports, events. Episodes via existing EpisodicMemory. `search()` fans out + merges by score. `reindex_from_store()` for warm boot |
| AD-243 | `runtime.py` | Runtime wiring — conditional creation (needs episodic memory), auto-indexing hooks on store_*() calls (fire-and-forget), warm boot re-index, status() integration |
| AD-244 | `introspect.py` + `llm_client.py` | `search_knowledge` introspection intent — NL query → cross-type semantic search, with optional type filtering. MockLLMClient pattern |
| AD-245 | `shell.py` + `panels.py` | `/search <query>` command with optional `--type` filter. `render_search_panel()` with type-colored results table and per-collection stats |
| AD-246 | `test_semantic_knowledge.py` | ~44 tests: cleanup fixes (4), lifecycle (3), indexing per type (14), cross-type search (6), bulk re-index (3), runtime (5), introspection (4), shell/panel (5) |

## Highest-Risk Items

1. **ChromaDB client sharing** — EpisodicMemory and SemanticKnowledgeLayer may use the same db directory. Verify that ChromaDB supports multiple PersistentClient instances on the same directory, OR share a single client. ChromaDB >= 1.0 supports this via `get_or_create_collection()` — each collection is independent within a client. The safest approach: share the same `PersistentClient` instance by passing it from the runtime (if EpisodicMemory already created one) or use a sibling directory.

2. **Auto-indexing timing** — the `store_*()` calls in runtime.py happen at different lifecycle points (episode storage in the processing loop, agent storage in self-mod, workflow storage at shutdown). Make sure indexing doesn't run during shutdown race conditions. Guard with `if self._semantic_layer:` checks.

3. **Warm boot ordering** — `reindex_from_store()` must run AFTER `_restore_from_knowledge()` has loaded all artifacts. The knowledge layer needs the artifacts to exist before it can index them.

## Verification Checklist

After completion, verify:
- [ ] `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` — all tests pass
- [ ] `/search <query>` command works in interactive mode
- [ ] `search_knowledge` intent is in decomposer's intent table
- [ ] `status()` dict includes `"semantic_knowledge"` key
- [ ] `parse_agent_id()` correctly parses compound pool names
- [ ] `_all_patterns` list stays bounded after many analyze() calls
- [ ] Auto-indexing after `store_agent()` populates the sk_agents collection
- [ ] `reindex_from_store()` populates collections from existing KnowledgeStore data
- [ ] All 9 existing introspection intents still work
- [ ] PROGRESS.md updated with correct AD numbers and test count
