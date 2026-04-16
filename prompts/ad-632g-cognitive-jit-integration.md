# AD-632g: Cognitive JIT Integration — Chain Pattern Learning

## Context

AD-632g closes the learning loop between Level 3 (sub-task chains, 2-4 LLM calls) and Level 1
(procedural replay, 0 LLM calls). When a chain pattern repeatedly produces good outcomes, the
system should learn it as a reusable procedure that replays deterministically.

This is the SOAR chunking analog: "if a sub-task decomposition pattern repeatedly produces good
results, Cognitive JIT should learn it as a reusable procedure" (docs/research/
cognitive-sub-task-protocol.md, Principle P5).

## Prior Work to Build On

1. **Sub-task chain infrastructure** (AD-632a–f): 5-step chains
   (Q→A→C→E→R) with journal recording (`dag_node_id = st:{chain_id}:{step}:{type}`),
   `SUB_TASK_CHAIN_COMPLETED` event, and `"sub_task_chain": True` in decision dicts.
2. **Cognitive JIT pipeline** (AD-531–539): Episode clustering → procedure extraction →
   procedure store → replay engine → graduated compilation (Dreyfus 1-5) → trust-gated
   promotion → observational learning → lifecycle management.
3. **Procedure dataclass** (`procedures.py:57-95`): Already has `learned_via` field
   ("direct"|"observational"|"taught") — add "chain_compiled".
4. **Dream Step 7** (`dreaming.py:~300`): Clusters success-dominant episodes →
   `extract_procedure_from_cluster()` → saves to ProcedureStore.
5. **Level 1 check** (`cognitive_agent.py:1147`): `_check_procedural_memory(observation)`
   queries ProcedureStore via ChromaDB semantic match → returns decision dict if found.
6. **Chain event** (`sub_task.py:362`): `SubTaskChainCompletedEvent` with `agent_id`,
   `intent`, `chain_steps`, `total_tokens`, `success`, `source`.

## Key Design Decisions

### What makes chain learning different from episode learning?

Episode-based procedure extraction (AD-532) works on free-text episode content clustered by
semantic similarity. Chain learning has **structured decomposition** — each step has a known
type, known context_keys, known prompt_template. This structure should be preserved in the
learned procedure's steps, not re-extracted by LLM.

### Learning pathway

1. Chain episodes are already stored with `sub_task_chain: True` in decision metadata
2. Dream Step 7 already clusters episodes and extracts procedures
3. **New: Chain-aware extraction** — when a cluster's episodes are predominantly chain-derived,
   extract a **ChainProcedure** that preserves the chain spec structure instead of using LLM
   extraction
4. The resulting procedure's `steps` map 1:1 to `SubTaskSpec` entries, enabling deterministic
   chain replay at Level 1

### Replay pathway

Current Level 1 replay (`_check_procedural_memory`) returns a flat decision dict. Chain
procedures need to reconstruct the `SubTaskChain` and replay via the existing executor — but
with cached/templated prompts instead of live LLM calls.

**However**, this introduces significant complexity. For Phase 1, the simpler approach is:
- Chain-derived procedures replay as **single-call shortcuts** (Level 1), not reconstructed
  chains
- The procedure captures the **Compose output pattern** (the final response template) that
  the chain produced
- This gives us 0-token replay for patterns the chain has validated

Full chain reconstruction replay is deferred to AD-632g-phase2.

## Engineering Principles

- **SOLID-O**: Extend `extract_procedure_from_cluster()` to detect chain episodes, not modify
  existing extraction path
- **SOLID-S**: Chain pattern detector is a separate function, not mixed into general extraction
- **DRY**: Reuse existing ProcedureStore `save()`/`find_matching()` — no parallel store
- **Law of Demeter**: Chain metadata accessed through episode.metadata dict, not reaching into
  chain internals
- **Fail Fast**: If chain metadata is malformed, fall through to standard LLM extraction
- **Defense in Depth**: Chain procedures validated against existing ProcedureStore dedup
  (`has_cluster()`) before save

## Implementation

### File 1: `src/probos/cognitive/procedures.py` — Chain-Aware Extraction

**Add `learned_via` value `"chain_compiled"`.**

Already present in `Procedure.learned_via` field (line 88). Add "chain_compiled" to the
documented enum.

**Add `extract_chain_procedure()`** — deterministic extraction (no LLM call):

```python
def extract_chain_procedure(
    cluster: "EpisodeCluster",
    episodes: list["Episode"],
) -> Procedure | None:
    """Extract a procedure from a chain-dominant episode cluster.

    Unlike extract_procedure_from_cluster() (LLM-based), this uses the
    structured chain metadata preserved in episode decisions to build
    procedure steps deterministically. Zero LLM calls.

    Returns None if the cluster is not chain-dominant or metadata is
    insufficient.
    """
```

**Logic:**
1. Check chain dominance: count episodes where `metadata.get("sub_task_chain") is True`.
   If < 60% of cluster episodes are chain-derived, return `None` (fall through to LLM
   extraction).
2. Extract chain spec from the most recent successful chain episode's metadata:
   - `intent` (from episode trigger_type or metadata)
   - `source` (from `chain_source` in metadata, e.g., "intent_trigger:ward_room_notification")
3. Build `ProcedureStep` list from the chain source pattern:
   - Step action = the final Compose/Reflect output pattern
   - Step expected_input = the intent type
   - Step expected_output = action tags found in episode content (REPLY, ENDORSE, etc.)
4. Build Procedure:
   - `name`: f"Chain pattern: {intent}" (e.g., "Chain pattern: ward_room_notification")
   - `intent_types`: [intent]
   - `learned_via`: "chain_compiled"
   - `compilation_level`: 2 (Guided — starts higher than episode-derived procedures because
     the chain has already validated quality through Evaluate/Reflect)
   - `origin_cluster_id`: cluster.cluster_id
   - `provenance`: episode IDs
   - `tags`: ["chain_compiled", f"chain_source:{source}"]
   - `source_anchors`: from chain episodes' AnchorFrames

### File 2: `src/probos/cognitive/cognitive_agent.py` — Chain Metadata Propagation

**In `_execute_sub_task_chain()` (line 1631):** Add chain metadata to the decision dict so it
persists into the episode:

```python
return {
    "action": "execute",
    "llm_output": llm_output,
    "tier_used": tier_used,
    "sub_task_chain": True,
    "chain_source": chain.source,  # NEW: e.g., "intent_trigger:ward_room_notification"
    "chain_steps": len(chain.steps),  # NEW: step count for extraction
}
```

These fields flow into episode metadata via the existing act() → episode storage pipeline.

### File 3: `src/probos/cognitive/dreaming.py` — Dream Step 7 Enhancement

**In the Step 7 procedure extraction loop**, before calling
`extract_procedure_from_cluster()`, attempt chain-aware extraction first:

```python
# AD-632g: Try chain-aware extraction first (0 LLM calls)
from probos.cognitive.procedures import extract_chain_procedure
chain_proc = extract_chain_procedure(cluster, cluster_episodes)
if chain_proc is not None:
    # Chain procedure extracted deterministically — skip LLM extraction
    await procedure_store.save(chain_proc)
    chain_procedures_extracted += 1
    continue
# Fall through to existing LLM-based extraction
```

Add a counter `chain_procedures_extracted` to the dream report dict for observability.
Add `"chain_procedures_extracted"` to the dream report return value alongside existing
`"procedures_extracted"`.

### File 4: `src/probos/cognitive/sub_task.py` — Chain Source Accessor

**On `SubTaskChain` dataclass** (line 67), the `source` field already exists. No changes needed
— the source string is already available for metadata propagation.

### File 5: `src/probos/startup/finalize.py` — No Changes

Existing wiring connects procedure store to dreaming engine. No new wiring needed.

## What This Does NOT Do

1. **No chain reconstruction replay** — procedures replay as flat Level 1 shortcuts, not
   reconstructed multi-step chains. Full chain replay is AD-632g-phase2.
2. **No new dream step** — uses existing Step 7 with a pre-check, not a separate step.
3. **No new events** — chain compilation is a procedure extraction variant, uses existing
   procedure events.
4. **No modification to `_check_procedural_memory()`** — chain-compiled procedures are stored
   in the same ProcedureStore and matched by the same semantic search. They're just procedures
   with `learned_via="chain_compiled"` and higher initial `compilation_level`.
5. **No parallel dispatch** — that's AD-632h.

## Tests — `tests/test_ad632g_cognitive_jit_integration.py`

Target: 25-35 tests across 6 classes.

### Class 1: TestChainDominanceDetection (4 tests)
- Episodes with >60% `sub_task_chain: True` → chain-dominant
- Episodes with <60% → not chain-dominant, returns None
- Episodes with no metadata → not chain-dominant
- Mixed chain + non-chain episodes at boundary (60%)

### Class 2: TestChainProcedureExtraction (6 tests)
- Successful extraction from ward_room_notification chain episodes
- Successful extraction from proactive_think chain episodes
- Procedure has `learned_via="chain_compiled"`
- Procedure has `compilation_level=2`
- Procedure has correct `intent_types` from episode metadata
- Procedure `tags` include "chain_compiled" and source

### Class 3: TestChainMetadataPropagation (4 tests)
- `_execute_sub_task_chain()` includes `chain_source` in decision dict
- `_execute_sub_task_chain()` includes `chain_steps` count
- `sub_task_chain: True` still present (regression)
- Metadata fields survive into mock episode storage

### Class 4: TestDreamStepChainExtraction (5 tests)
- Dream Step 7 tries chain extraction before LLM extraction
- Chain-dominant cluster → chain procedure saved, LLM extraction skipped
- Non-chain cluster → falls through to LLM extraction
- Dream report includes `chain_procedures_extracted` count
- `has_cluster()` dedup prevents duplicate chain procedures

### Class 5: TestChainProcedureReplay (4 tests)
- Chain-compiled procedure found by `find_matching()` semantic search
- Chain-compiled procedure replays at Level 1 (0 LLM calls)
- `learned_via` preserved through store save/load round-trip
- `compilation_level=2` enables earlier trust-gated promotion

### Class 6: TestChainProcedureEdgeCases (4 tests)
- Malformed chain metadata → falls through to LLM extraction
- Empty cluster → returns None
- Single chain episode (below clustering threshold) → not extracted
- Chain procedure with `is_negative=True` cluster → negative procedure extraction

## Acceptance Criteria

1. `extract_chain_procedure()` produces valid Procedure from chain-dominant clusters
2. Dream Step 7 transparently tries chain extraction before LLM extraction
3. Chain-compiled procedures replay at Level 1 via existing `_check_procedural_memory()`
4. Decision dict includes `chain_source` and `chain_steps` metadata
5. No regressions in existing procedure extraction (non-chain clusters unaffected)
6. Dream report includes `chain_procedures_extracted` counter
7. All new tests pass; existing AD-531-539 and AD-632 test suites unaffected

## Tracking

- **PROGRESS.md**: Add AD-632g status entry
- **DECISIONS.md**: Record chain learning design decisions
- **roadmap.md**: Update AD-632 umbrella + standalone AD-632g block
- **GitHub**: Close issue when complete

## Dependencies

- AD-632a (foundation — SubTaskChain, SubTaskSpec, executor)
- AD-632f (activation triggers — chain.source field)
- AD-531-539 (Cognitive JIT pipeline — procedure extraction, store, replay)
