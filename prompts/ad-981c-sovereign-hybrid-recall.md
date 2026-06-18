# AD-981c — Wire AD-979c hybrid retrieval onto the sovereign recall path (shard-aware)

**Issue #974 · Oracle-recall epic (advances #902, #900) · depends on AD-979c (hybrid, shipped) + AD-981a (sovereign FoK, shipped).**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1027 (#973, verified highest). This AD = AD-981c (sovereign-recall live-wiring family: 981a FoK-logging shipped, 981b expand/consult earmarked, 981c = hybrid on sovereign path; verified free).**

Make the **sovereign** agent recall (`recall_for_agent_with_confidence`) honor the existing `hybrid_recall_enabled` flag by fusing the FTS5 sparse axis with the dense ranking — **shard-filtered to the agent's own episodes** — so a memory encoded under different vocabulary than the query (the gold-standard cross-session "dog" miss) is surfaced. Mirrors the global `recall_with_confidence` hybrid tail; default config unchanged.

---

## Why / context (proven end-to-end, 2026-06-18)
Gold-standard cross-session test: the Captain told Yeo (1:1) about two giant schnauzers; after a clean restart Yeo could not recall them (*"you haven't mentioned dogs to me"*) though the episodes ARE stored — read-only FTS proved it (`"...Giant Schnauzer is a solid dog..."`, `"[1:1 with yeoman] Captain: Schnauzer..."`). Root cause: the per-message recall fired with the user's query but the **dense/cosine** sovereign recall didn't rank the dog episodes high enough, and the **FTS sparse axis that would catch "dogs"→"dog/schnauzer" by keyword is wired only on the global path**. `config/system.yaml:117` already has `hybrid_recall_enabled: true`, but `recall_for_agent_with_confidence` ignores it (dense-only). SOTA validation: mem0, Hindsight, Graphiti, supermemory, cognee all use hybrid (semantic + BM25/keyword [+ graph]) fused by **reciprocal rank fusion** — exactly AD-979c. (DECISIONS:512 already cites mem0 + RRF as AD-979c's absorbed prior art.)

## Pinned design decisions

### DD-1 — Gate on the EXISTING `hybrid_recall_enabled` flag (no new flag)
The Captain already enabled `hybrid_recall_enabled` expecting hybrid recall; the sovereign path not honoring it is the bug. Gate the sovereign fusion on the same `self._hybrid_recall_enabled and self._fts_db is not None` condition the global path uses ([episodic.py](src/probos/cognitive/episodic.py#L2259)). `config.py` default stays `False` → byte-identical for default installs; the Captain's `true` config activates it on next reboot (the immediate fix). Do NOT add a new config field.

### DD-2 — SOVEREIGN-LEAK GUARD (load-bearing — get this right)
`_fuse_dense_sparse` ([episodic.py](src/probos/cognitive/episodic.py#L2264)) calls `keyword_search` over the **GLOBAL** FTS index and hydrates sparse-only ids via `get_by_ids` — neither is shard-scoped. A blind mirror onto the sovereign path would fuse/hydrate **other agents' episodes** into THIS agent's recall — a sovereign-memory leak (violates the AD-397 shard isolation the dense path enforces via the `agent_ids` `is_owned` check at [episodic.py](src/probos/cognitive/episodic.py#L2635-L2645)). The sovereign fusion MUST filter sparse hits / fused results to episodes the agent owns (`agent_id in episode.agent_ids`). Implement a sovereign variant (e.g. `_fuse_dense_sparse_for_agent(agent_id, query, dense_episodes, k)`) OR add an `owner_id` param to `_fuse_dense_sparse` — and **post-filter the hydrated episodes to owned** as the final guard regardless. A regression test asserting NO non-owned episode appears is mandatory.

### DD-3 — Keep the FoK band as the DENSE distribution (mirror the global choice)
The AD-981a agent-scoped band/`best_sim`/logging is computed from the dense owned distribution BEFORE fusion — leave it exactly as-is ([episodic.py](src/probos/cognitive/episodic.py#L2655-L2675)). Hybrid changes WHICH episodes return, not the cosine confidence signal (same decision AD-979c made for the global path). The fusion is applied to the returned `episodes` list only, after the band is built.

## Build
1. **Sovereign hybrid fusion** — in `recall_for_agent_with_confidence` ([episodic.py](src/probos/cognitive/episodic.py#L2562)), after the `episodes` list + `confidence` band are built and BEFORE `return`, add the gated tail: `if self._hybrid_recall_enabled and self._fts_db is not None: episodes = await <shard-aware fusion>(agent_id, query, episodes, k)`. Mirror the global tail at [episodic.py](src/probos/cognitive/episodic.py#L2258-L2261).
2. **Shard-aware fusion helper** — per DD-2: keyword_search → RRF with the owned dense ids → hydrate → **post-filter to owned** → cap at k. Honest-degrade (empty/failed sparse → dense unchanged), mirroring `_fuse_dense_sparse`'s try/except.
3. **`recall_for_agent` shim unchanged** — it delegates to `recall_for_agent_with_confidence`; no signature change.
4. **Tests** — new `tests/test_ad981c_sovereign_hybrid.py`.

## Acceptance
- `tests/test_ad981c_sovereign_hybrid.py` (BF-287 real `EpisodicMemory` on `tmp_path` + real embeddings + the real FTS sidecar):
  - **Headline (reproduces the incident):** seed an agent-owned episode whose text shares a keyword with the query but is dense-sub-threshold; with `hybrid_recall_enabled=True`, `recall_for_agent_with_confidence(agent_id, <vocabulary-mismatch query>)` surfaces it; with `False`, it does not (proves the fusion + the gate).
  - **SOVEREIGN-LEAK guard (mandatory):** a NON-owned episode that matches the keyword query is NOT returned in the agent's hybrid recall (assert absent). This is the load-bearing correctness test.
  - **FoK band unchanged:** the logged band/`best_sim` equals the dense-only value (fusion doesn't alter the AD-981a signal).
  - **Default-off byte-identical:** `hybrid_recall_enabled=False` → identical episode ids to pre-AD-981c `recall_for_agent`.
  - Honest-degrade: empty/failed sparse axis → dense list unchanged.
- Gate `-k "ad981c or ad979c or ad981a or recall_for_agent or hybrid or episodic"` green; the existing `test_ad979c_hybrid_retrieval.py` + `test_ad981a_recall_fok_logging.py` unchanged.
- Real-fixture per BF-287 (no MagicMock for the store); full type annotations; logging context preserved.
- **Verify compliance with `.github/copilot-instructions.md`** (sovereign isolation, async hygiene, type annotations, no scope creep).

## Do NOT build here
❌ A new config flag — reuse `hybrid_recall_enabled` (DD-1). ❌ The AD-981b expand/consult control loop on the sovereign path (`recall_with_control` wiring) — separate, earmarked. ❌ Cross-encoder reranking / write-time fact extraction / user-profile auto-population — those are the external-survey forward absorbs (separate ADs). ❌ Changing the dense path, the FoK band computation, the `relevance_threshold`/BF-027 relaxed threshold, or `recall_weighted`'s anchor-gating. ❌ Touching `recall_with_confidence` (global path already has hybrid). ❌ A new top-level AD number — this is AD-981c.

## Files (verify each at build)
- [src/probos/cognitive/episodic.py](src/probos/cognitive/episodic.py) — gated sovereign hybrid tail in `recall_for_agent_with_confidence` (~L2562) + the shard-aware fusion helper (mirror `_fuse_dense_sparse` ~L2264 with the ownership filter).
- `tests/test_ad981c_sovereign_hybrid.py` (NEW) — headline + sovereign-leak + FoK-unchanged + default-off coverage.

## Done-when
With `hybrid_recall_enabled=True`, sovereign recall surfaces keyword-matched owned episodes the dense axis missed (the dog case), with ZERO non-owned leakage; default-off byte-identical; gate green; **verify compliance with `.github/copilot-instructions.md`**; update `PROGRESS.md` + `DECISIONS.md` (AD-981c) in the same commit.
