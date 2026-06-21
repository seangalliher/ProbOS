# AD-1043 — representativeQueries capture (empirically grounded sample queries)

**Epic:** ARD Integration (`docs/development/ard-integration.md`) · **Phase 1, Step 4**
**Issue:** #993 · **Epic:** #989 · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-1041 (projection) · **Blocks:** better AD-1044 search ranking
**Verification status:** ✅ verified against HEAD (episodic + workflow-cache sources exist)

## Objective

Populate each catalog entry's `representativeQueries` (ARD spec §4.2: 2–5 natural-language sample queries used by registries to seed semantic embeddings) from ProbOS's **real** routing history — the episodic store + workflow cache. This is a ProbOS differentiator: most publishers hand-author these; ProbOS has the empirical record of which phrasings actually routed to each capability.

## Why

ARD registries rank on `representativeQueries`. ProbOS can emit queries that *demonstrably* succeeded (from the workflow cache's successful NL→intent routings and episodic outcomes), which no hand-authored manifest can match. This is the highest-leverage, lowest-risk enrichment.

## Build

1. **New `representative_query_miner.py`** in `federation/ard/` with:
   ```python
   def mine_representative_queries(
       capability_id: str,
       *,
       workflow_cache=None,   # successful NL→intent routings
       episodic=None,         # outcome-tagged episodes
       limit: int = 5,
   ) -> list[str]: ...
   ```
   - Source 1 (preferred): the **workflow cache** — its exact/fuzzy NL→DAG entries already key successful natural-language inputs to the intents they routed to. Pull the inputs whose DAG used `capability_id`, dedupe, most-recent/most-frequent first.
   - Source 2 (fallback): episodic recall scoped to the capability, filtered to **successful** outcomes; take the user-input fragment.
   - Bound to `limit` (2–5 per spec), deterministic order, honest-degrade to `[]` when neither source is available or no history exists.
   - **Pure read** — no writes, no LLM, no network. Verify the exact workflow-cache / episodic public read APIs at build time (`grep` for the workflow cache class + its query method, and the episodic recall signature).
2. **Wire into the projector (AD-1041):** `project_catalog` gains optional `query_miner: Callable | None`; when provided, each entry's `representative_queries = query_miner(entry_capability_id)[:5]`. When `None` (default), entries keep `[]` (AD-1041 byte-identical).
3. **Wire at the AD-1042 handler:** pass a miner bound to `runtime.workflow_cache` + `runtime.episodic` so the served manifest carries real queries when the subsystems exist; degrade to empty otherwise.

## Acceptance criteria

- `mine_representative_queries("web_search", workflow_cache=<fake with 3 successful routings>)` → those 3 inputs, deduped, ≤5.
- No history / no subsystems → `[]` (honest-degrade, never raises).
- Deterministic: same inputs → same order.
- Projector with `query_miner=None` is byte-identical to AD-1041 (entries keep `[]`).
- Served manifest (AD-1042) carries `representativeQueries` when a miner + history exist; still passes the conformance tester's 2–5 sizing check (it allows fewer; never emit >5).
- Tests `tests/test_ad1043_representative_queries.py` (BF-287: real fake workflow cache + real episodic stub): mine-from-cache, mine-from-episodic-fallback, empty, dedupe, ≤5 cap, projector wiring on/off.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Do NOT build

- No LLM generation of queries — this is *mining real history*, not synthesis.
- No writes to episodic/workflow cache (read-only).
- No search endpoint (AD-1044). No change to AD-1041's default (miner is opt-in).
