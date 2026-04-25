# BF-164: Oracle Cross-Agent Episodic Recall for Ship-Wide Authority

**Status:** Ready for builder
**Scope:** OSS
**Complexity:** Tiny (1 source file modified, 1 test file modified)
**Against:** AD-619

## Problem

AD-619 gave the Counselor Oracle access (recall tier override + strategy gate
relaxation). But the Oracle's episodic query is agent-scoped: `_query_episodic()`
passes `agent_id` to `recall_weighted()`, which chains to
`recall_for_agent_scored()`, which filters episodes where `agent_id not in
agent_ids` (line 1607 of `episodic.py`).

When Echo asks "What has Chapel been working on?", Oracle queries Echo's own
episodic shard → 0 results about Chapel. Chapel's 348 episodes sit in the
same ChromaDB collection but are filtered out by the agent_id check.

The Oracle was designed for cross-TIER recall (episodic + records + operational),
not cross-AGENT episodic recall. AD-619 opened the gate but the episodic query
behind the gate is still sovereign-scoped.

## Root Cause

In `cognitive_agent.py` line 2856-2861, the Oracle call passes `agent_id=_mem_id`
(Echo's own sovereign ID):

```python
oracle_text = await oracle.query_formatted(
    query_text=query,
    agent_id=_mem_id,
    k_per_tier=3,
    max_chars=2000,
)
```

In `oracle_service.py` line 179-186, `_query_episodic()` uses `recall_weighted()`
with that agent_id, scoping results to the caller's shard only.

The Oracle already has a global recall path at lines 202-213 that uses
`em.recall()` (no agent_id filtering). It triggers when `agent_id` is empty.

## Solution

One change in one file.

### Change 1: Pass empty agent_id for ship-wide authority agents

**File:** `src/probos/cognitive/cognitive_agent.py`

**Location:** Lines 2856-2861, inside the Oracle gate block that was modified
by AD-619. The `_swa` variable is already in scope from the AD-619 strategy
gate change (line ~2845).

**Current:**
```python
                        oracle_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=2000,
                        )
```

**Change to:**
```python
                        # BF-164: Ship-wide authority agents get cross-agent
                        # episodic recall (empty agent_id → global query).
                        oracle_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id="" if _swa else _mem_id,
                            k_per_tier=3,
                            max_chars=2000,
                        )
```

**Effect:**
- Ship-wide authority agents (Counselor): Oracle episodic tier queries the
  entire ChromaDB collection via `em.recall()` — global semantic search
  across ALL agents' episodes. No agent_id filtering.
- All other agents: unchanged — still use `recall_weighted()` with their
  own agent_id for sovereign-scoped, trust/Hebbian-scored recall.

**Tradeoff:** The global `recall()` path returns a flat `score=0.5` instead
of trust/Hebbian-weighted scoring. This is acceptable because:
1. The Counselor's use case is cross-agent visibility (breadth), not ranked
   precision within her own shard.
2. Results are still semantically ranked by ChromaDB cosine similarity.
3. Tier 2 (Records) and Tier 3 (Operational) remain scored normally.
4. The flat score keeps cross-agent episodes from dominating the merged
   results — they rank below well-scored self-shard episodes if the agent
   also had agent-scoped results at a higher score.

## Files

| # | File | Action |
|---|------|--------|
| 1 | `src/probos/cognitive/cognitive_agent.py` | MODIFY — conditional agent_id in Oracle call |
| 2 | `tests/test_ad619_counselor_awareness.py` | MODIFY — add cross-agent Oracle test |

## Tests

Add to the existing `TestOracleStrategyGate` class in
`tests/test_ad619_counselor_awareness.py`:

**`test_ship_wide_agent_oracle_empty_agent_id`**
- Mock CognitiveAgent with `agent_type="counselor"`.
- Verify that when the Oracle `query_formatted()` is called, `agent_id`
  is empty string `""` (not the agent's own ID).
- Assert the call uses `agent_id=""` by inspecting the mock call args.

**`test_non_ship_wide_agent_oracle_own_agent_id`**
- Mock CognitiveAgent with `agent_type="data_analyst"`.
- Verify that `agent_id` passed to Oracle is the agent's own `_mem_id`.

## Key References

- `src/probos/cognitive/cognitive_agent.py:2845` — `_swa = _has_swa(self)` (AD-619)
- `src/probos/cognitive/cognitive_agent.py:2856-2861` — Oracle query call site
- `src/probos/cognitive/oracle_service.py:173-216` — `_query_episodic()` with both paths
- `src/probos/cognitive/oracle_service.py:179` — agent-scoped path (`recall_weighted`)
- `src/probos/cognitive/oracle_service.py:202` — global path (`recall()`, no agent_id)
- `src/probos/cognitive/episodic.py:1127-1166` — `recall()` global semantic search
- `src/probos/cognitive/episodic.py:1607` — `if agent_id not in agent_ids: continue`

## Design Notes

**Why empty agent_id, not a new Oracle method:**
The Oracle already handles empty `agent_id` correctly — the `elif hasattr(em, "recall")`
path at line 202 was designed as a fallback for exactly this case. Adding a new method
or parameter would be over-engineering for a one-line conditional.

**Why not query both paths (self + global) and merge:**
Adds complexity for marginal benefit. The Counselor's primary need is cross-agent
visibility. Her own episodes are already available through her regular (non-Oracle)
episodic recall in the `perceive()` method. The Oracle is additive context.

**Future consideration:**
If the Counselor needs scored cross-agent recall (trust/Hebbian-weighted across
agent shards), that would be a larger AD to add a `recall_weighted_global()` method
to `EpisodicMemory`. Current `recall()` is sufficient for the use case.
