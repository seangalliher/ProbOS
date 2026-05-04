# AD-657 v1: Dream Consolidation Trace Preservation

**Status:** Drafted (Wave 27)
**Risk:** low (additive field on `Procedure` dataclass + one new public read primitive on `EpisodicMemory` + one observational context-assembly insertion)
**Depends on:** `Procedure` dataclass (shipped, AD-532); `ProcedureStore.find_matching/get` (shipped, AD-533); `Episode.importance` (shipped, AD-598); `runtime.procedure_store` property (shipped, AD-534); `runtime.episodic_memory` (shipped)
**Closes:** GitHub issue #316
**Source:** Meta-Harness research (Lee et al., Stanford/UW, arXiv:2603.28052) — full traces scored 50.0% median vs 34.9% for summaries.

---

## Solution Overview

Roadmap entry (`docs/development/roadmap.md:7092`) calls for "trace exemplars" — the 2-3 most diagnostically rich raw episodes per consolidated dream pattern, preserved alongside the abstraction. Today, dream Step 7 (`src/probos/cognitive/dreaming.py:435`) extracts a `Procedure` from a success-dominant `EpisodeCluster` and discards the source episodes from the procedure's read path; only `Procedure.provenance` (a flat list of all source episode IDs) is kept, and nothing on the retrieval side surfaces the original episodes when the procedure is recalled.

v1 ships **structure + producer + one consumer**:

1. **Schema:** add `trace_exemplars: list[str]` (episode IDs) to `Procedure` (`src/probos/cognitive/procedures.py:59`). Default `[]`. Round-tripped through `to_dict` / `from_dict`. Backward-compatible: old procedures load with empty exemplars.
2. **Producer (Step 7):** after each successful procedure extraction, select the top-N source episodes by **`Episode.importance` DESC, tie-break `Episode.timestamp` DESC**, take their IDs, write to `procedure.trace_exemplars`. N is config-driven (`DreamingConfig.trace_exemplars_per_procedure: int = 3`). N=0 disables the feature (stores `[]`). Selection happens BEFORE the existing dedup gate at `dreaming.py:506`, so the field is populated for every procedure that reaches `procedure_store.save()`.
3. **Read primitive:** add `EpisodicMemory.get_by_ids(episode_ids: list[str]) -> list[Episode]` (`src/probos/cognitive/episodic.py`). Wraps `self._collection.get(ids=..., include=["metadatas", "documents"])` and reuses the existing `_metadata_to_episode` static at `episodic.py:2083`. Returns episodes in the same order as input; missing IDs silently omitted (graceful degradation when an exemplar episode has been pruned by AD-593).
4. **Consumer (`_gather_context`):** in `src/probos/proactive.py:1156`, after the existing `recent_memories` block (ends at `proactive.py:1459` `context["recent_memories"] = memory_list`), add a small block that:
   - calls `runtime.procedure_store.find_matching(query, n_results=1, exclude_negative=True)` with the same `query` already built for `recall_weighted` (`agent.agent_type recent duty observations`)
   - if a match returns with `score >= 0.5`, calls `runtime.procedure_store.get(match["id"])` to get the full `Procedure`
   - if `procedure.trace_exemplars` is non-empty, calls `runtime.episodic_memory.get_by_ids(procedure.trace_exemplars)`
   - emits at most 3 exemplar summaries into `context["recalled_procedure_exemplars"]` with shape `{"procedure_name": str, "procedure_id": str, "exemplars": [{"input": str (≤300 chars), "reflection": str (≤300 chars), "importance": int, "age": str}]}`
   - whole block wrapped in `try/except Exception: logger.debug(..., exc_info=True)` — degrade silently, never break proactive thought

The "diagnostically rich" ranking uses `Episode.importance` (1-10, AD-598) — already computed at encoding time via `compute_importance()` (`src/probos/cognitive/importance_scorer.py`), already persisted in ChromaDB metadata (`episodic.py:1002`, `episodic.py:2104` `int(metadata.get("importance", 5))`), already used as a salience signal in retrieval. **No new scoring infrastructure.** Tie-break by `Episode.timestamp` DESC keeps the most recent exemplar when two episodes share an importance score.

## What This Does NOT Change

- **No re-ranking.** `trace_exemplars` is set ONCE at extraction time and never updated. Procedures evolved via FIX/DERIVED (AD-532b) keep their parent's exemplars unless the evolution path explicitly sets new ones (out of scope for v1).
- **No backfill of existing procedures.** Old procedures load via `from_dict` with `trace_exemplars=[]`. Retroactive population is a separate concern; v1 ships forward-only.
- **No mutation of `Procedure.provenance`.** That field continues to hold ALL source episode IDs from the cluster. `trace_exemplars` is a curated subset selected by importance.
- **No new EventType.** Observational v1; no `TRACE_EXEMPLARS_RECALLED` or similar.
- **No retention enforcement on the episode side.** Exemplar IDs are pointers. If AD-593 activation-pruning evicts an exemplar episode, `get_by_ids` returns fewer entries — consumer block degrades gracefully (omits the missing exemplar; if all gone, `recalled_procedure_exemplars` is absent from context).
- **No changes to `cognitive_agent._check_procedural_memory()`** (`cognitive_agent.py:307,333`). The replay-first dispatch path stays untouched. Exemplar surfacing is proactive-context-only in v1.
- **No score-floor / context-budget config.** Hard-coded thresholds (`score >= 0.5`, `≤300 chars per exemplar`, `≤3 exemplars`, `top-1 procedure match`) — externalize only if AD-657a integration data justifies tuning.
- **No anchor-aware selection.** v1 ranking is `(importance DESC, timestamp DESC)` only. AnchorFrame-aware exemplar selection (e.g., diversify by department) is deferred.

## Dependencies

- `src/probos/cognitive/procedures.py:59` — `Procedure` dataclass (mutable; `to_dict` line ~106; `from_dict` line ~141).
- `src/probos/cognitive/dreaming.py:435` — Step 7 procedure extraction loop. `matched_episodes` (list of `Episode` objects from the cluster) is in scope at line 467 (`matched_episodes = [ep for ep in episodes if ep.id in cluster.episode_ids]`).
- `src/probos/cognitive/episodic.py:2083` — `_metadata_to_episode` static reused by new `get_by_ids`. `self._collection` is the ChromaDB collection.
- `src/probos/proactive.py:1156` — `_gather_context`. Insertion point: directly after line 1459 `context["recent_memories"] = memory_list` (still inside the `try` block; or in a sibling `try` after the `except Exception` at 1461). Use a sibling `try` to keep failure isolation independent of episodic recall.
- `src/probos/config.py:508` — `DreamingConfig`. Add field at end of model.
- `src/probos/runtime.py:961` — `runtime.procedure_store` property (returns `self._procedure_store`, may be `None`).
- `src/probos/runtime.py:380` — `runtime.episodic_memory` attribute (may be `None`).

All reads/writes against existing public APIs. No new module.

## Sections

### Section 1 — `Procedure.trace_exemplars` field

In `src/probos/cognitive/procedures.py`, add the field to the `Procedure` dataclass (insert after `source_skill_id` line ~92 to keep AD-grouped fields contiguous), update `to_dict`, update `from_dict`:

```python
# in @dataclass class Procedure (line 59):
    # AD-657: Top-N source episodes preserved for diagnostic context recall (importance DESC, timestamp DESC)
    trace_exemplars: list[str] = field(default_factory=list)
```

```python
# in to_dict, append to the returned dict (after "source_skill_id"):
            "trace_exemplars": self.trace_exemplars,
```

```python
# in from_dict, append to the cls(...) call (after source_skill_id):
            trace_exemplars=data.get("trace_exemplars", []),
```

`Procedure` is NOT frozen (no `@dataclass(frozen=True)` at line 59) — mutation in Step 7 (`procedure.trace_exemplars = [...]`) is legal.

### Section 2 — `DreamingConfig.trace_exemplars_per_procedure`

In `src/probos/config.py`, append to `DreamingConfig` (insert before the closing of the class around line 560):

```python
    # AD-657: Trace exemplars preserved per consolidated procedure (0 = disabled)
    trace_exemplars_per_procedure: int = 3
```

`@field_validator` not required — int range enforcement isn't critical here; downstream `[:N]` slice tolerates 0 and large values. Document in the comment that 0 disables.

### Section 3 — Step 7 producer in `dream_cycle`

In `src/probos/cognitive/dreaming.py`, inside the Step 7 loop (line 438 onward), AFTER `procedure = await extract_procedure_from_cluster(...)` / `extract_compound_procedure_from_cluster(...)` / `extract_chain_procedure(...)` resolves and BEFORE the source_anchors attachment block (line 489 `if procedure: ... if cluster.anchor_summary: ...`), add the exemplar-selection step.

Place the new block immediately inside the `if procedure:` body (line 489), BEFORE the `if cluster.anchor_summary:` block — both are guarded by the same `if procedure:`:

```python
                    if procedure:
                        # AD-657: Select top-N diagnostically rich exemplars (importance DESC, timestamp DESC)
                        n_exemplars = self.config.trace_exemplars_per_procedure
                        if n_exemplars > 0 and matched_episodes:
                            ranked = sorted(
                                matched_episodes,
                                key=lambda ep: (ep.importance, ep.timestamp),
                                reverse=True,
                            )
                            procedure.trace_exemplars = [ep.id for ep in ranked[:n_exemplars]]
                        # AD-567d: Attach anchor provenance to procedure
                        if cluster.anchor_summary:
                            ...
```

(SEARCH/REPLACE to match exactly the existing `if procedure:` body — Builder confirms surrounding 3 lines of context.)

`matched_episodes` is bound at line 467 as `[ep for ep in episodes if ep.id in cluster.episode_ids]` — already in scope at this insertion point.

**Note for chain-extracted procedures:** `extract_chain_procedure` (line 472) is synchronous and may return early. The exemplar block runs unconditionally inside `if procedure:` regardless of which extractor produced it — so chain, compound, and standard procedures all get exemplars by the same rule.

### Section 4 — `EpisodicMemory.get_by_ids` read primitive

In `src/probos/cognitive/episodic.py`, add a new public async method on `EpisodicMemory`. Insert AFTER the existing `get_episode_metadata` method (line 1111) and BEFORE `update_episode_metadata` (line 1133):

```python
    async def get_by_ids(self, episode_ids: list[str]) -> list[Episode]:
        """AD-657: Fetch full Episode objects by ID, preserving input order.

        Missing IDs (e.g., evicted by AD-593 activation pruning) are silently
        omitted — caller treats absence as graceful degradation, not error.
        """
        if not self._collection or not episode_ids:
            return []
        try:
            result = self._collection.get(
                ids=list(episode_ids),
                include=["metadatas", "documents"],
            )
        except Exception:
            logger.debug("AD-657: get_by_ids ChromaDB query failed", exc_info=True)
            return []
        if not result or not result.get("ids"):
            return []

        # ChromaDB returns ids/metadatas/documents in match order, missing entries dropped.
        # Rebuild in input order using a lookup.
        by_id: dict[str, Episode] = {}
        result_ids = result["ids"]
        result_metas = result.get("metadatas") or [{} for _ in result_ids]
        result_docs = result.get("documents") or ["" for _ in result_ids]
        for i, doc_id in enumerate(result_ids):
            try:
                meta = result_metas[i] if i < len(result_metas) else {}
                doc = result_docs[i] if i < len(result_docs) else ""
                by_id[doc_id] = self._metadata_to_episode(doc_id, doc or "", meta or {})
            except Exception:
                logger.debug(
                    "AD-657: failed to reconstruct episode %s", doc_id, exc_info=True,
                )
                continue
        return [by_id[eid] for eid in episode_ids if eid in by_id]
```

`_metadata_to_episode` is the existing static at `episodic.py:2083` — reused, no duplication.

### Section 5 — `_gather_context` consumer block

In `src/probos/proactive.py`, in `_gather_context` (line 1156), insert AFTER the existing `recent_memories` block's `except Exception: logger.debug("Episodic recall failed for %s", agent.id, exc_info=True)` (line 1461) and BEFORE the `# AD-462d: Social Memory` block (line 1463). Use a fresh `try` for failure isolation:

```python
        # AD-657: Surface diagnostic exemplars for any consolidated dream pattern that matches recent activity
        try:
            store = getattr(rt, 'procedure_store', None)
            em = getattr(rt, 'episodic_memory', None)
            if store and em:
                # Reuse the same query already built for episodic recall above
                query = f"{agent.agent_type} recent duty observations".strip()
                matches = await store.find_matching(
                    query, n_results=1, exclude_negative=True,
                )
                if matches and matches[0].get("score", 0.0) >= 0.5:
                    proc_id = matches[0]["id"]
                    procedure = await store.get(proc_id)
                    if procedure and procedure.trace_exemplars:
                        exemplar_eps = await em.get_by_ids(procedure.trace_exemplars[:3])
                        if exemplar_eps:
                            now = time.time()
                            exemplars_payload = []
                            for ep in exemplar_eps:
                                ui = ep.user_input or ""
                                rf = ep.reflection or ""
                                exemplars_payload.append({
                                    "input": (ui[:300] + " [trimmed]") if len(ui) > 300 else ui,
                                    "reflection": (rf[:300] + " [trimmed]") if len(rf) > 300 else rf,
                                    "importance": ep.importance,
                                    "age": format_duration(now - ep.timestamp) if ep.timestamp > 0 else "",
                                })
                            context["recalled_procedure_exemplars"] = {
                                "procedure_name": procedure.name,
                                "procedure_id": procedure.id,
                                "exemplars": exemplars_payload,
                            }
        except Exception:
            logger.debug(
                "AD-657: trace-exemplar recall failed for %s", agent.id, exc_info=True,
            )
```

`format_duration` and `time` are already imported in `proactive.py` (used at line 1448, 1465). `procedure_store` access goes through the public `runtime.procedure_store` property (`runtime.py:961`); `episodic_memory` through the public attribute (`runtime.py:380`). No private-attribute access. Demeter clean.

### Section 6 — Tests (`tests/test_ad657_trace_exemplars.py`)

New test file. **Minimum 7 tests** — exceeds the "at least 5" floor:

1. **`test_procedure_trace_exemplars_default_empty`** — `Procedure()` has `trace_exemplars == []`.
2. **`test_procedure_trace_exemplars_round_trip`** — `Procedure(trace_exemplars=["a","b","c"]).to_dict()` round-trips through `from_dict` preserving the list. Old serialized dicts (without the key) load as `[]`.
3. **`test_dream_step_7_populates_top_n_by_importance`** — construct a fake cluster with 5 matched_episodes, importances `[3, 9, 5, 9, 1]`, timestamps `[10, 20, 30, 40, 50]`. With `trace_exemplars_per_procedure=3`, after Step 7, `procedure.trace_exemplars` is the IDs of episodes with importance 9 (timestamp 40), importance 9 (timestamp 20), importance 5 (timestamp 30) — in that order (importance DESC, timestamp DESC tie-break).
4. **`test_dream_step_7_caps_at_config`** — same setup but `trace_exemplars_per_procedure=2` produces exactly 2 exemplars (top-2 by ranking).
5. **`test_dream_step_7_disabled_when_n_zero`** — `trace_exemplars_per_procedure=0` → `procedure.trace_exemplars == []` even with rich source episodes.
6. **`test_episodic_get_by_ids_returns_in_input_order`** — store 4 episodes, request `[id3, id1, id4, id_missing, id2]`, verify result is `[ep3, ep1, ep4, ep2]` (missing silently dropped, order preserved).
7. **`test_gather_context_surfaces_exemplars_when_procedure_matches`** — fake `runtime` with `procedure_store.find_matching` returning a high-score match, `procedure_store.get` returning a `Procedure` with `trace_exemplars=[id1,id2]`, `episodic_memory.get_by_ids` returning 2 fake `Episode`s. Call `_gather_context`. Assert `context["recalled_procedure_exemplars"]` exists with 2 exemplars, correct `procedure_name`, `importance` field present, `input` truncated at 300 chars when long.
8. **`test_gather_context_omits_exemplars_when_episodes_missing`** — same setup but `get_by_ids` returns `[]` (all exemplar episodes pruned). Assert `"recalled_procedure_exemplars"` is NOT in `context`.

Tests use `_Fake*` stubs per testing standard (no MagicMock chains). Place fakes for `procedure_store` / `episodic_memory` / `runtime` inline in the test file; do not depend on conftest fixtures beyond `tmp_path` if needed for ChromaDB-backed `EpisodicMemory` integration tests (Section 6 test 6 only).

## Acceptance Criteria

- [ ] `Procedure.trace_exemplars: list[str]` field added with `to_dict`/`from_dict` round-trip.
- [ ] `DreamingConfig.trace_exemplars_per_procedure: int = 3` field added with default `3`.
- [ ] Step 7 producer populates `trace_exemplars` from `matched_episodes` ranked by `(importance, timestamp)` DESC, capped at config value.
- [ ] `EpisodicMemory.get_by_ids(episode_ids) -> list[Episode]` returns episodes in input order; missing IDs silently omitted.
- [ ] `_gather_context` adds `recalled_procedure_exemplars` to context when `procedure_store.find_matching` returns a match with `score >= 0.5` AND the matched procedure has non-empty `trace_exemplars` AND at least one exemplar episode is still retrievable.
- [ ] All 7+ new tests pass.
- [ ] No test count regression. Full gate green: `pytest tests/ -q -n 8 --dist=loadfile`.
- [ ] No EventType added. No new module created. No `runtime._private` access introduced.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Tracking

- `PROGRESS.md` — flip AD-657 to ✅ Closed with a one-line reason; update test count.
- `docs/development/roadmap.md:7092` — flip *(Scoped, OSS, Issue #316)* → *(Complete, OSS, Issue #316)*.
- `DECISIONS.md` — append AD-657 entry referencing this prompt.
- Issue #316 — close on merge.

## Verified Against Codebase (2026-05-04)

```
grep -n "^class Procedure" src/probos/cognitive/procedures.py
  59: class Procedure:

grep -n "def to_dict\|def from_dict" src/probos/cognitive/procedures.py
  86: (ProcedureStep.to_dict)
  106: (Procedure.to_dict)
  136: (Procedure.from_dict)

grep -n "Step 7: Procedure extraction\|matched_episodes = \[ep for ep" src/probos/cognitive/dreaming.py
  445:        # Step 7: Procedure extraction from success clusters (AD-532)
  467:                    matched_episodes = [
  468:                        ep for ep in episodes if ep.id in cluster.episode_ids
  469:                    ]

grep -n "if procedure:" src/probos/cognitive/dreaming.py
  489:                    if procedure:

grep -n "class DreamingConfig" src/probos/config.py
  508: class DreamingConfig(BaseModel):

grep -n "_metadata_to_episode\|async def get_episode_metadata" src/probos/cognitive/episodic.py
  1111:    async def get_episode_metadata(
  2083:    def _metadata_to_episode(

grep -n "async def _gather_context\|context\[\"recent_memories\"\] = memory_list\|# AD-462d: Social Memory" src/probos/proactive.py
  1156:    async def _gather_context(self, agent: Any, trust_score: float) -> dict:
  1459:                    context["recent_memories"] = memory_list
  1463:        # AD-462d: Social Memory — check for open memory queries to respond to

grep -n "def procedure_store\|self.episodic_memory = episodic_memory" src/probos/runtime.py
  380:        self.episodic_memory = episodic_memory  # None = disabled
  961:    def procedure_store(self):

grep -n "async def find_matching\|async def get" src/probos/cognitive/procedure_store.py
  451:    async def get(self, procedure_id: str) -> "Any | None":
  562:    async def find_matching(

grep -n "    importance: int" src/probos/types.py
  430:    importance: int = 5  # 1-10 scale, 5 = neutral

grep -n "format_duration\|^import time" src/probos/proactive.py
  (format_duration imported and used at line 1448; time imported at module top)
```

All concrete claims in the prompt map to a grep hit shown above.

---

## Commit Message (single commit)

```
AD-657 v1: Dream consolidation trace preservation (closes #316)

Preserve top-N (default 3) most diagnostically rich source episodes per
consolidated Procedure, ranked by (importance DESC, timestamp DESC).
Surfaces exemplar inputs/reflections in proactive context when a matching
dream pattern is recalled, grounding the abstraction in concrete diagnostic
detail. Meta-Harness research (Lee et al., arXiv:2603.28052): full traces
scored 50.0% vs 34.9% for summaries.

- Procedure.trace_exemplars: list[str] (episode IDs)
- DreamingConfig.trace_exemplars_per_procedure: int = 3 (0 disables)
- Step 7 selects exemplars from cluster's matched_episodes
- EpisodicMemory.get_by_ids() new public read primitive
- _gather_context surfaces recalled_procedure_exemplars (score >= 0.5,
  top-1 procedure, ≤3 exemplars, 300-char per-field cap)
- Backward compat: from_dict defaults trace_exemplars to []
- Graceful degradation: pruned exemplar episodes silently omitted

7 new tests. No new EventType. No private-attribute access.
```
