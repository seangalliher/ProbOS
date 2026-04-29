# BF-247: TieredKnowledgeLoader Treats `dag_summary` as String — It's a Dict

## Status

**Production fix already applied** (commit `8be47d5`, 2026-04-29). Sections 1-3 from the
original prompt are complete. This prompt now covers only the remaining test additions.

## Problem (for context)

`TieredKnowledgeLoader._load_category()` and `load_on_demand()` in `tiered_knowledge.py`
treated `Episode.dag_summary` as a string, but the actual type is `dict[str, Any]`
(types.py line 417). `summary[:150]` on a dict raised `KeyError: slice(None, 150, None)`,
crashing contextual knowledge loads for all intents.

## What Was Fixed

- `_load_category` episodes branch: `isinstance` guard on `dag_summary`, extracts
  `dag.get("summary", "")` with reflection fallback
- `load_on_demand` episodes fallback: same `isinstance` guard pattern
- Test fake `_FakeEpisode.dag_summary` changed from `str` to `dict`

## Remaining Work: Add Tests

**File:** `tests/test_ad585_tiered_knowledge.py` (add to existing file)

4 new tests to cover the fixed code paths:

1. `test_load_category_episodes_dict_dag_summary` — episode with `dag_summary={"summary": "test observation"}`, verify snippet contains "test observation"
2. `test_load_category_episodes_empty_dag_summary` — episode with `dag_summary={}`, verify no crash, falls back to reflection
3. `test_on_demand_dict_dag_summary` — `load_on_demand` with dict `dag_summary`, verify no crash
4. `test_on_demand_no_reflection_uses_dag_summary` — episode with empty reflection but dict `dag_summary` with "summary" key, verify snippet extracted

Use the existing `_FakeEpisode` (which now has `dag_summary: dict`) and `_FakeKnowledgeSource`
patterns already in the test file.

## What This Does NOT Change

- No changes to `Episode` dataclass or `dag_summary` type annotation
- No changes to `KnowledgeStore.load_episodes()` deserialization
- No changes to `CognitiveAgent._build_episode_dag_summary()`
- No changes to `dreaming.py` or `guided_reminiscence.py` (already correct)

## Tracking

- `PROGRESS.md`: Add BF-247 as CLOSED
- `docs/development/roadmap.md`: Update BF-247 status to Closed

## Acceptance Criteria

- All 4 new tests pass
- All existing tests in `test_ad585_tiered_knowledge.py` still pass (32 currently)
- No `KeyError: slice` in logs
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`
