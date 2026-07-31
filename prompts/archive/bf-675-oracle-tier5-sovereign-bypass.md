# BF-675 — Oracle Tier 5 sovereign-shard bypass (cognitive / Oracle)

**Issue: #1058 · no epic dependency · prerequisite for the Σ epic #1057 (AD-1138+).**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1133 shipped; AD-1134–1137 assigned to #1053–#1056. BF ceiling: `PROGRESS.md` says BF-673, but **BF-674 is already claimed by uncommitted in-flight work** (`tests/test_bf674_llm_endpoint_cooldown.py` + modified `llm_client.py`/`config.py` — "bound shared-endpoint retries during empty-response outages"). Verified next free top-level = **BF-675**. NO new top-level AD is minted.**

Oracle Tier 5 returns other agents' episode content labelled `source_tier="semantic"`, which bypasses the AD-607e sovereign-shard filter entirely. Close the bypass at the source and add a defence-in-depth relabel. This is a correctness/containment fix only — no new capability, no config flag, no Σ work.

---

## Why / context

The Captain's design intent is that an agent's episodic memory is its own shard (AD-397), shared only through communication. That invariant **is** structurally enforced on the Tier 1 path — both retrieval axes hard-filter:

- vector: `if agent_id not in agent_ids: continue` — `src/probos/cognitive/episodic.py:3714`
- keyword: explicit `# Sovereign shard filter` before the FTS5 merge — `src/probos/cognitive/episodic.py:3892`

Tier 5 defeats it. Verified chain, every hop read at HEAD:

1. An ORACLE-tier agent calls `oracle.query_formatted(query_text=query, agent_id=_mem_id, k_per_tier=3, max_chars=2000)` with **no `tiers` argument** → all seven tiers active — `src/probos/cognitive/cognitive_agent.py:9296`
2. Tier 5 dispatch calls `self._query_semantic(query_text, k=k_per_tier)` with **no `types` argument** — `src/probos/cognitive/oracle_service.py:388`
3. `_query_semantic` forwards `types=None` → `layer.search(query_text, types=None, limit=k)` — `src/probos/cognitive/oracle_service.py:785`
4. `include_episodes = types is None or "episodes" in types` → **True** — `src/probos/knowledge/semantic.py:310`
5. `await self._episodic_memory.recall(query, k=limit)` → `recall_with_confidence` — **global, no agent filter** — `src/probos/knowledge/semantic.py:313`, `src/probos/cognitive/episodic.py:2552`
6. Oracle wraps the result with `source_tier="semantic"` — `src/probos/cognitive/oracle_service.py:789`
7. The AD-607e filter passes it straight through: `if r.source_tier != "episodic": filtered.append(r); continue` — `src/probos/cognitive/oracle_service.py:617`

Live-wired: `SemanticKnowledgeLayer(db_path=…, episodic_memory=episodic_memory)` — `src/probos/startup/structural_services.py:59`.

**Blast radius (do not overstate).** Only agents resolving to `RecallTier.ORACLE` = `Rank.SENIOR` (`src/probos/earned_agency.py:62`) reach step 1. The BF-265 branch for FULL/ENHANCED agents passes `tiers=["graph"]` (`src/probos/cognitive/cognitive_agent.py:9327`) and is unaffected. `/search` passes `tiers=["semantic"]` and is Captain-facing.

**Why this must be fixed before the Σ epic:** AD-1138 indexes Ship's Records into Tier 5. Shipping that over a leaking tier means the leak inherits new data and a much larger surface.

---

## Pinned design decisions

### DD-1 — Exclusion at the source is the fix; relabelling alone is NOT sufficient
`_filter_by_access_policy` returns early on the default policy:
```python
if access_policy == MemoryAccessPolicy.PERMISSIVE:
    return results
```
`src/probos/cognitive/oracle_service.py:607`, and `access_policy: str = "permissive"` is the shipped default (`src/probos/config.py:1021`). Relabelling episode-derived results would make the filter *capable* of catching them while leaving the bypass fully open in the default configuration. **Exclusion (DD-2) is the fix. Relabelling (DD-3) is defence-in-depth for non-default policies and future re-enablement.** Ship both; the exclusion test is the headline regression.

### DD-2 — Add `include_episodes` to `SemanticKnowledgeLayer.search()`, defaulting to today's behaviour
Add a keyword-only `include_episodes: bool = True` to `SemanticKnowledgeLayer.search()` (`src/probos/knowledge/semantic.py:259`). The default preserves every existing caller byte-identically. Gate the episode block:
```python
include_episodes = include_episodes and (types is None or "episodes" in types)
```
`Oracle._query_semantic` then passes `include_episodes=False`.

Chosen over "resolve `types` to `layer.COLLECTIONS.keys()` in the Oracle" because that couples the Oracle to the layer's collection registry and fails **open** if `COLLECTIONS` is ever empty. An explicit boolean fails closed and states intent.

### DD-3 — Defence-in-depth relabel in `_query_semantic`
When building each `OracleResult` in `_query_semantic`, if `r.get("type") == "episode"` (or `r["metadata"]["type"] == "episode"`), set `source_tier="episodic"` instead of `"semantic"`. After DD-2 this branch is unreachable through the Oracle, but it makes any future path that re-enables episodes correctly subject to AD-607e. Keep `provenance` consistent with the tier chosen.

### DD-4 — Captain's `/search` keeps its episodes
`cmd_search` calls `oracle.query(query, k_per_tier=10, tiers=["semantic"])` (`src/probos/experience/commands/commands_knowledge.py:87`). After DD-2 the Captain would silently stop seeing episodes there. Change that call to `tiers=["semantic", "episodic"]`. The Captain passes no `agent_id`, so `_query_episodic` takes the `elif hasattr(em, "recall")` global branch (`src/probos/cognitive/oracle_service.py:648`) — **same content as today, now correctly labelled**. No Captain-visible regression.

### DD-5 — FLAG AT BUILD: the legacy direct-layer path in IntrospectAgent
`src/probos/agents/introspect.py:785` calls `layer.search(query, types=types, limit=10)` directly in the `elif layer is not None:` fallback taken only when the Oracle is absent. Confirm at build whether `types` can be `None` there. **Recommended:** pass `include_episodes=False` at that call site too — IntrospectAgent is an agent, not the Captain. If `types` is provably always a non-empty list excluding `"episodes"`, leave it and say so in the build report.

### DD-6 — This is a bug fix, so the default-OFF byte-identity criterion does NOT apply
Behaviour **must** change for the ORACLE-tier agent path. Byte-identity is asserted only for (a) `SemanticKnowledgeLayer.search()` called without the new kwarg, and (b) non-episode Tier 5 content.

---

## Build

1. **`include_episodes` gate** — add keyword-only `include_episodes: bool = True` to `SemanticKnowledgeLayer.search()` in [semantic.py](src/probos/knowledge/semantic.py) and fold it into the existing `include_episodes` computation at line 310. Full type annotation; docstring states the default preserves prior behaviour.
2. **Oracle excludes episodes from Tier 5** — `_query_semantic` in [oracle_service.py](src/probos/cognitive/oracle_service.py) passes `include_episodes=False` to `layer.search(...)`.
3. **Defence-in-depth relabel** — in the same `_query_semantic` result loop, route any `type == "episode"` result to `source_tier="episodic"` with matching `provenance`.
4. **`/search` tier widening** — [commands_knowledge.py](src/probos/experience/commands/commands_knowledge.py) `cmd_search` passes `tiers=["semantic", "episodic"]`.
5. **DD-5 resolution** — inspect [introspect.py](src/probos/agents/introspect.py) line 785; apply `include_episodes=False` or document why it is unnecessary.
6. **Tests** — new `tests/test_bf675_oracle_tier5_sovereignty.py` per Acceptance below.

---

## Acceptance

- **Headline regression (must fail pre-fix, pass post-fix):** `test_tier5_does_not_leak_foreign_agent_episodes` — a real `EpisodicMemory` (`tmp_path`) seeded with an episode whose `agent_ids` contains ONLY `agent-b`; agent `agent-a` issues `oracle.query(query, agent_id="agent-a")`; assert no returned `OracleResult` contains that episode's content, under the **default** `permissive` policy.
- `test_tier5_still_returns_semantic_collections` — an indexed skill/workflow is still returned by Tier 5 after the fix.
- `test_semantic_search_default_unchanged` — `SemanticKnowledgeLayer.search()` called without `include_episodes` still includes episodes (existing callers byte-identical).
- `test_semantic_search_include_episodes_false_excludes` — direct layer-level unit test of the new gate.
- `test_episode_typed_result_is_labelled_episodic` — DD-3: a stub layer returning a `type: "episode"` row yields `source_tier="episodic"`, and that result IS dropped by `_filter_by_access_policy` under `OWN_SHARD_ONLY` for a non-owning caller.
- `test_cmd_search_still_surfaces_episodes_for_captain` — DD-4: `cmd_search` requests both tiers; Captain-visible content preserved.
- **Obsolete-contract sweep (expect breakage):** the stub layers in `tests/test_ad686_oracle_semantic_tier.py` (`test_query_semantic_happy_path_with_stub_layer`, `test_query_semantic_types_passthrough`, `test_end_to_end_query_returns_normalized_oracle_results`) define `search()` signatures that will not accept the new kwarg. Update the stubs to accept `include_episodes` — **repoint, do not delete** these guards.
- Real-fixture tests per BF-287: real `EpisodicMemory` + real `SemanticKnowledgeLayer` on `tmp_path` for the headline test; no MagicMock at the store boundary.
- Clean-checkout portable: no assertion depends on operator-local config, `config/system.yaml` (skip-worktree `S`), caches, or wall-clock ordering.
- Ownership unchanged: the Oracle remains a stateless aggregator; no new store, no new state owner, no new event.
- Verify compliance with `.github/copilot-instructions.md` (async hygiene, layer discipline, type annotations, logging context).

## Validation plan

- **Focused coding gate:** `tests/test_bf675_oracle_tier5_sovereignty.py tests/test_ad686_oracle_semantic_tier.py -n 0`
- **Adjacent regression gate:** `tests/test_ad686b_oracle_write_semantic.py tests/test_ad686c_semantic_stats.py tests/test_ad688_oracle_graph_integration.py tests/test_ad695_ship_health_oracle.py tests/test_ad696_agentic_oracle_retrieval.py tests/test_ad462f_memory_refs.py -n 0`
- **Wave-close gate (after Architect review):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile` with an isolated `PROBOS_DATA_DIR` and `PROBOS_EMBEDDINGS=local`.
- **Clean-checkout gate:** CI green on repository HEAD.
- No UI change ⇒ no Vitest/Playwright/build gate required.

## Do NOT build here

❌ Semantic indexing of Ship's Records (AD-1138). ❌ Any agent-facing Oracle tool (AD-1139). ❌ Any Σ publish path (AD-1140). ❌ Crew-loop wiring (AD-1141). ❌ Changing the `access_policy` default away from `permissive` — that is a separate, Captain-approved decision with its own blast radius. ❌ Touching the Tier 1 sovereign filters in `episodic.py` — they are correct. ❌ Any change to `MemoryAccessPolicy` members or `_filter_by_access_policy` structure beyond consuming the corrected tier label. ❌ Any change to `llm_client.py` / `config.py` LLM-rate fields — those belong to the separate in-flight BF-674. ❌ A new top-level AD number — this is **BF-675**.

## Files (verify each at build)

- `src/probos/knowledge/semantic.py` — add `include_episodes` kwarg to `search()`; gate the episode block.
- `src/probos/cognitive/oracle_service.py` — `_query_semantic` passes `include_episodes=False`; relabel `type == "episode"` results as `source_tier="episodic"`.
- `src/probos/experience/commands/commands_knowledge.py` — `cmd_search` tiers → `["semantic", "episodic"]`.
- `src/probos/agents/introspect.py` — DD-5: apply `include_episodes=False` or document.
- `tests/test_bf675_oracle_tier5_sovereignty.py` (NEW) — headline leak regression + gate units + relabel + `/search` parity.
- `tests/test_ad686_oracle_semantic_tier.py` — stub-signature repoint (obsolete-contract repair only).

## Done-when

All acceptance green; focused + adjacent gates green; Architect review findings repaired; consolidated wave-close and clean-checkout CI green; the headline test demonstrably fails on a pre-fix tree; `SemanticKnowledgeLayer.search()` default path byte-identical; full type annotations on the changed signatures; **verify compliance with `.github/copilot-instructions.md`.**
