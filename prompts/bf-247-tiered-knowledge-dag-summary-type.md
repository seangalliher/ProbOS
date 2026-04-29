# BF-247: TieredKnowledgeLoader Treats `dag_summary` as String — It's a Dict

## Problem

`TieredKnowledgeLoader._load_category()` (line 211) and `load_on_demand()` (line 161) in `tiered_knowledge.py` treat `Episode.dag_summary` as a string:

```python
# Line 211 — contextual loading
summary = getattr(episode, "dag_summary", "") or ""
if summary:
    snippets.append(summary[:150])  # KeyError: slice(None, 150, None)

# Line 161 — on-demand fallback
text = (
    getattr(episode, "reflection", "")
    or getattr(episode, "dag_summary", "")  # Falls through to dict
    or ""
)
if any(word in text.lower() for word in query_lower.split()):  # AttributeError on dict
    snippets.append(text[:200])  # KeyError on dict
```

But `Episode.dag_summary` is typed as `dict[str, Any]` (types.py line 417) and populated as a dict by `CognitiveAgent._build_episode_dag_summary()` (cognitive_agent.py line 5248). The `KnowledgeStore.load_episodes()` method also deserializes it as a dict (store.py line 110: `data.get("dag_summary", {})`).

**Runtime error:**
```
KeyError: slice(None, 150, None)
```

This crashes the contextual knowledge load for any intent, causing agents to operate without contextual knowledge:
```
AD-585: Contextual knowledge load failed for intent=proactive_think department=; returning empty.
```

## Why Tests Don't Catch It

The AD-585 test file (`tests/test_ad585_tiered_knowledge.py`) uses `_FakeEpisode` with `dag_summary: str = "Analyzed security patterns"` (line 20). This masks the real type. Production Episodes use `dict[str, Any]`.

## Prior Art

- **AD-585** (Complete): Tiered Knowledge Loading — built the `TieredKnowledgeLoader`. Original implementation.
- **AD-568e**: Added `_build_episode_dag_summary()` returning dict with faithfulness metadata.
- **`dreaming.py:2436-2444`**: Correctly handles `dag_summary` as dict with `isinstance` guard.
- **`guided_reminiscence.py:160`**: Correctly defaults to `{}` not `""`.

## Root Cause

AD-585 was built when `dag_summary` was assumed to be a string summary. AD-568e changed it to a structured dict with faithfulness/attribution metadata. The tiered_knowledge code was never updated.

## Fix

### Section 1: Fix `_load_category` episodes branch

**File:** `src/probos/cognitive/tiered_knowledge.py`

SEARCH (around line 208-216):
```python
        if category == "episodes":
            episodes = await self._source.load_episodes(limit=10)
            for episode in episodes:
                summary = getattr(episode, "dag_summary", "") or ""
                if department and hasattr(episode, "agent_ids"):
                    # TODO(AD-585): Apply department filtering once episodes persist department metadata.
                    pass
                if summary:
                    snippets.append(summary[:150])
```

REPLACE:
```python
        if category == "episodes":
            episodes = await self._source.load_episodes(limit=10)
            for episode in episodes:
                dag = getattr(episode, "dag_summary", None) or {}
                if isinstance(dag, str):
                    # BF-247: Legacy string format — use directly
                    summary_text = dag
                elif isinstance(dag, dict):
                    # BF-247: Current dict format — extract readable summary
                    summary_text = dag.get("summary", "") or str(dag.get("faithfulness_score", ""))
                    if not summary_text:
                        # Fallback: use reflection if dag has no readable summary
                        summary_text = getattr(episode, "reflection", "") or ""
                else:
                    summary_text = ""
                if department and hasattr(episode, "agent_ids"):
                    # TODO(AD-585): Apply department filtering once episodes persist department metadata.
                    pass
                if summary_text:
                    snippets.append(summary_text[:150])
```

### Section 2: Fix `load_on_demand` episodes fallback

**File:** `src/probos/cognitive/tiered_knowledge.py`

SEARCH (around line 155-167):
```python
        try:
            episodes = await self._source.load_episodes(limit=20)
            query_lower = query.lower()
            for episode in episodes:
                text = (
                    getattr(episode, "reflection", "")
                    or getattr(episode, "dag_summary", "")
                    or ""
                )
                if not text:
                    continue
                if any(word in text.lower() for word in query_lower.split()):
                    snippets.append(text[:200])
```

REPLACE:
```python
        try:
            episodes = await self._source.load_episodes(limit=20)
            query_lower = query.lower()
            for episode in episodes:
                # BF-247: dag_summary is dict[str, Any], not str — use reflection for text search
                text = getattr(episode, "reflection", "") or ""
                if not text:
                    dag = getattr(episode, "dag_summary", None) or {}
                    if isinstance(dag, str):
                        text = dag
                    elif isinstance(dag, dict):
                        text = dag.get("summary", "") or ""
                if not text:
                    continue
                if any(word in text.lower() for word in query_lower.split()):
                    snippets.append(text[:200])
```

### Section 3: Fix test fake to match production type

**File:** `tests/test_ad585_tiered_knowledge.py`

Find the `_FakeEpisode` dataclass. Change `dag_summary` from `str` to `dict`:

SEARCH:
```python
    dag_summary: str = "Analyzed security patterns"
```

REPLACE:
```python
    dag_summary: dict = field(default_factory=lambda: {"summary": "Analyzed security patterns"})
```

Add `from dataclasses import field` to imports if not already present.

Verify all existing tests still pass after this change. If any test asserts on the string value of `dag_summary`, update the assertion to use the dict structure.

## Tests

**File:** `tests/test_ad585_tiered_knowledge.py` (add to existing file)

4 new tests:

1. `test_load_category_episodes_dict_dag_summary` — episode with `dag_summary={"summary": "test observation"}`, verify snippet contains "test observation"
2. `test_load_category_episodes_empty_dag_summary` — episode with `dag_summary={}`, verify no crash, falls back to reflection
3. `test_on_demand_dict_dag_summary` — `load_on_demand` with dict `dag_summary`, verify no crash
4. `test_on_demand_no_reflection_uses_dag_summary` — episode with empty reflection but dict `dag_summary` with "summary" key, verify snippet extracted

## What This Does NOT Change

- No changes to `Episode` dataclass or `dag_summary` type annotation
- No changes to `KnowledgeStore.load_episodes()` deserialization
- No changes to `CognitiveAgent._build_episode_dag_summary()`
- No changes to `dreaming.py` or `guided_reminiscence.py` (already correct)

## Tracking

- `PROGRESS.md`: Add BF-247 as CLOSED
- `docs/development/roadmap.md`: Add BF-247 to Bug Tracker table

## Acceptance Criteria

- `TieredKnowledgeLoader` handles `dag_summary` as `dict[str, Any]` without crashing
- Contextual knowledge loads succeed for all intent types
- Test fake matches production `Episode.dag_summary` type
- No `KeyError: slice` in logs
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`
