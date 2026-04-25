# BF-028: Proactive & Shell Recall Fallback Hardening

## Symptom

BF-027 added `recent_for_agent()` fallback to `_recall_relevant_memories()` in cognitive_agent.py — when semantic recall returns empty, it falls back to the agent's most recent episodes by timestamp. But two other recall sites were NOT updated:

1. **`_gather_context()` in proactive.py** (line 342): Uses `recall_for_agent(agent.id, "recent activity", k=5)` with the hardcoded query `"recent activity"`. If this doesn't clear the similarity threshold, the agent gets zero memory context for proactive thinks.

2. **Shell cross-session recall** (shell.py line 1468): Uses `recall_for_agent(agent_id, f"1:1 with {callsign}", k=3)`. If there are no semantically matching episodes, the shell session starts with no memory seeding.

Both should use the same `recent_for_agent()` fallback pattern from BF-027.

## Fix

### Fix 1: proactive.py `_gather_context()`

**File:** `src/probos/proactive.py`

Find the episodic recall block (around lines 339-354). Replace:

```python
        episodes = await rt.episodic_memory.recall_for_agent(
            agent.id, "recent activity", k=5
        )
```

With:

```python
        episodes = await rt.episodic_memory.recall_for_agent(
            agent.id, "recent activity", k=5
        )
        # BF-028: Fallback to recent episodes when semantic recall misses
        if not episodes and hasattr(rt.episodic_memory, 'recent_for_agent'):
            episodes = await rt.episodic_memory.recent_for_agent(agent.id, k=5)
```

### Fix 2: shell.py cross-session recall

**File:** `src/probos/experience/shell.py`

Find the cross-session recall block (around lines 1464-1478). After the `recall_for_agent` call, add fallback:

```python
        past = await self.runtime.episodic_memory.recall_for_agent(
            agent_id=resolved["agent_id"],
            query=f"1:1 with {resolved['callsign']}",
            k=3,
        )
        # BF-028: Fallback to recent episodes when semantic recall misses
        if not past and hasattr(self.runtime.episodic_memory, 'recent_for_agent'):
            past = await self.runtime.episodic_memory.recent_for_agent(
                resolved["agent_id"], k=3
            )
```

## Tests

**File:** `tests/test_proactive.py` — Add 1 test.

### Test 1: _gather_context falls back to recent_for_agent
```
Create a ProactiveCognitiveLoop with mock runtime.
Mock episodic_memory.recall_for_agent() to return [].
Mock episodic_memory.recent_for_agent() to return 2 episodes.
Call _gather_context(agent).
Assert context["recent_memories"] has 2 entries (fallback fired).
```

**File:** `tests/test_shell.py` or appropriate existing test file — Add 1 test.

### Test 2: Shell cross-session recall falls back to recent_for_agent
```
Mock episodic_memory.recall_for_agent() to return [].
Mock episodic_memory.recent_for_agent() to return 1 episode.
Trigger session start with a crew agent.
Assert session history contains the fallback episode.
```

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_proactive.py tests/test_shell.py -x -v -k "fallback or recall" 2>&1 | tail -20
```
