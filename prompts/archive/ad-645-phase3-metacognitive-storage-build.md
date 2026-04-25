# AD-645 Phase 3: Metacognitive Storage

**AD:** AD-645 (Artifact-Mediated Cognitive Chain)
**Phase:** 3 of 5
**Status:** Ready for builder
**Issue:** #287
**Depends on:** AD-645 Phase 1+2 complete (composition briefs + COMPOSE enrichment)
**Scope:** 2 files modified (`agent_working_memory.py`, `cognitive_agent.py`), 1 test file created, zero new modules

---

## Context

AD-645 Phase 1+2 added composition briefs to the ANALYZE → COMPOSE handoff, improving chain-path response quality. However, briefs exist only in memory during chain execution — once `_execute_sub_task_chain()` returns, the ANALYZE result (including the composition brief) is discarded. There is no way to inspect what ANALYZE planned, debug brief quality, or let agents answer "What was I thinking?"

**Fix:** Store composition briefs in AgentWorkingMemory as `category="reasoning"` entries after chain execution completes. This provides:
- **Observability** — briefs appear in working memory context, visible in logs and future prompts
- **Metacognitive continuity** — agents can reference their prior reasoning in subsequent cycles
- **Stasis survival** — briefs persist across restart (< 24h staleness threshold)
- **Future foundation** — Phase 4 (EVALUATE alignment) and dream consolidation can draw on stored reasoning

---

## Phase 3A: WorkingMemory Reasoning Support

### File: `src/probos/cognitive/agent_working_memory.py`

#### Change 1: Add `max_recent_reasoning` parameter and deque

In `__init__()` (line 78-102), add a new parameter and deque for reasoning entries.

Add `max_recent_reasoning: int = 5` to the constructor signature after `max_events`:

```python
    def __init__(
        self,
        *,
        token_budget: int = 3000,
        max_recent_actions: int = 10,
        max_recent_observations: int = 5,
        max_recent_conversations: int = 5,
        max_events: int = 10,
        max_recent_reasoning: int = 5,
    ) -> None:
```

Add the deque after `self._recent_events` (after line 93):

```python
        self._recent_reasoning: deque[WorkingMemoryEntry] = deque(maxlen=max_recent_reasoning)
```

#### Change 2: Add `record_reasoning()` method

Add after the existing `record_event()` method (after line 158):

```python
    def record_reasoning(
        self, summary: str, *, source: str, metadata: dict[str, Any] | None = None,
        knowledge_source: str = "unknown",
    ) -> None:
        """AD-645: Record a composition brief or reasoning artifact from the cognitive chain."""
        self._recent_reasoning.append(WorkingMemoryEntry(
            content=summary,
            category="reasoning",
            source_pathway=source,
            metadata=metadata or {},
            knowledge_source=knowledge_source,
        ))
```

#### Change 3: Add reasoning section to `render_context()`

Add a Priority 3 section for reasoning AFTER the Priority 2 (recent actions) section and BEFORE the Priority 3 (recent conversations) section. Shift existing priorities: conversations becomes 4, observations becomes 5, cognitive state becomes 6, events becomes 7.

Replace the priority assignments in `render_context()` (lines 205-251) with:

```python
        # Priority 1 (highest): Active engagements — always include
        for eng in self._active_engagements.values():
            sections.append((1, eng.render()))

        # Priority 2: Recent actions — what I just did
        if self._recent_actions:
            action_lines = ["Recent actions:"]
            for entry in self._recent_actions:
                age = self._format_age(entry.age_seconds())
                _src_tag = f" [{entry.knowledge_source}]" if entry.knowledge_source != "unknown" else ""
                action_lines.append(f"  - ({age} ago, {entry.source_pathway}) {entry.content}{_src_tag}")
            sections.append((2, "\n".join(action_lines)))

        # Priority 3: Recent reasoning — what I was thinking (AD-645)
        if self._recent_reasoning:
            reason_lines = ["Recent reasoning:"]
            for entry in self._recent_reasoning:
                age = self._format_age(entry.age_seconds())
                reason_lines.append(f"  - ({age} ago) {entry.content}")
            sections.append((3, "\n".join(reason_lines)))

        # Priority 4: Recent conversations — who I just talked to
        if self._recent_conversations:
            conv_lines = ["Recent conversations:"]
            for entry in self._recent_conversations:
                age = self._format_age(entry.age_seconds())
                partner = entry.metadata.get("partner", "unknown")
                conv_lines.append(f"  - ({age} ago) with {partner}: {entry.content}")
            sections.append((4, "\n".join(conv_lines)))

        # Priority 5: Recent observations — what I noticed
        if self._recent_observations:
            obs_lines = ["Recent observations:"]
            for entry in self._recent_observations:
                age = self._format_age(entry.age_seconds())
                _src_tag = f" [{entry.knowledge_source}]" if entry.knowledge_source != "unknown" else ""
                obs_lines.append(f"  - ({age} ago) {entry.content}{_src_tag}")
            sections.append((5, "\n".join(obs_lines)))

        # Priority 6: Cognitive state — zone, cooldown
        if self._cognitive_state:
            state_parts = []
            if "zone" in self._cognitive_state:
                state_parts.append(f"Cognitive zone: {self._cognitive_state['zone']}")
            if "cooldown_reason" in self._cognitive_state:
                state_parts.append(f"Cooldown: {self._cognitive_state['cooldown_reason']}")
            if state_parts:
                sections.append((6, "Cognitive state: " + " | ".join(state_parts)))

        # Priority 7 (lowest): Recent events
        if self._recent_events:
            event_lines = ["Recent events:"]
            for entry in list(self._recent_events)[-5:]:
                event_lines.append(f"  - {entry.content}")
            sections.append((7, "\n".join(event_lines)))
```

#### Change 4: Add reasoning to `to_dict()` serialization

In `to_dict()` (lines 303-342), add after the `recent_events` serialization block:

```python
            "recent_reasoning": [
                {"content": e.content, "category": e.category,
                 "source_pathway": e.source_pathway, "timestamp": e.timestamp,
                 "metadata": e.metadata, "knowledge_source": e.knowledge_source}
                for e in self._recent_reasoning
            ],
```

#### Change 5: Add reasoning to `from_dict()` restoration

In `from_dict()` (lines 373-376), add after the `_recent_events` restoration:

```python
        _restore_entries(data.get("recent_reasoning", []), wm._recent_reasoning)
```

---

## Phase 3B: Chain Result Extraction and Storage

### File: `src/probos/cognitive/cognitive_agent.py`

#### Change 1: Extract composition brief and attach to decision dict

In `_execute_sub_task_chain()`, after the `results` are returned from the executor (line 1703) and before the final return dict (line 1781), extract the ANALYZE composition brief and attach it to the returned dict.

Add this block immediately before the `return {` statement at line 1781:

```python
        # AD-645 Phase 3: Extract composition brief for metacognitive storage
        _composition_brief = None
        for r in results:
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                _composition_brief = r.result.get("composition_brief")
                break
```

Then add `"_composition_brief": _composition_brief,` to the returned dict:

```python
        return {
            "action": "execute",
            "llm_output": llm_output,
            "tier_used": tier_used,
            "sub_task_chain": True,
            "chain_source": chain.source,
            "chain_steps": len(chain.steps),
            "_composition_brief": _composition_brief,  # AD-645 Phase 3
        }
```

Also add `"_composition_brief": None,` to the early-return suppress dict (around line 1745):

```python
                return {
                    "action": "execute",
                    "llm_output": "[NO_RESPONSE]",
                    "tier_used": "",
                    "sub_task_chain": True,
                    "chain_source": chain.source,
                    "chain_steps": len(chain.steps),
                    "_suppressed": True,
                    "_suppression_reason": rejection,
                    "_composition_brief": None,  # AD-645 Phase 3
                }
```

#### Change 2: Record composition brief to working memory after chain execution

In the post-execution recording block (lines 2340-2361), add composition brief storage after the existing `record_action` block and before the chain metadata propagation.

Insert after the `except Exception:` block at line 2350-2351:

```python
        # AD-645 Phase 3: Store composition brief as metacognitive memory
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm and decision.get("sub_task_chain") and decision.get("_composition_brief"):
                brief = decision["_composition_brief"]
                if isinstance(brief, dict):
                    # Build a human-readable summary from the brief
                    _situation = brief.get("situation", "")
                    _cover = brief.get("response_should_cover")
                    if isinstance(_cover, list):
                        _cover_text = "; ".join(str(c) for c in _cover[:3])
                    else:
                        _cover_text = str(_cover) if _cover else ""
                    summary_parts = []
                    if _situation:
                        summary_parts.append(_situation)
                    if _cover_text:
                        summary_parts.append(f"Planned to cover: {_cover_text}")
                    if summary_parts:
                        _wm.record_reasoning(
                            " | ".join(summary_parts),
                            source=intent.intent,
                            metadata={"composition_brief": brief},
                            knowledge_source="reasoning",
                        )
        except Exception:
            logger.debug("AD-645: Composition brief storage failed", exc_info=True)
```

---

## What NOT to Do

- Do NOT modify `analyze.py` or `compose.py` — those are Phase 1+2 (already complete).
- Do NOT modify `evaluate.py` or `reflect.py` — EVALUATE alignment is Phase 4.
- Do NOT modify `sub_task_executor.py` — results already flow back correctly.
- Do NOT modify `working_memory_store.py` — the `to_dict()`/`from_dict()` changes in `agent_working_memory.py` are sufficient; the store serializes whatever `to_dict()` returns.
- Do NOT add schema validation for the brief — `isinstance(brief, dict)` is the guard.
- Do NOT expose composition briefs to other agents — Minority Report Principle. Briefs stay in the agent's own working memory.
- Do NOT modify `render_context()` token budget — the default 3000 tokens accommodates 5 reasoning entries.
- Do NOT add reasoning entries for suppressed outputs — the `decision.get("_composition_brief")` check handles this naturally since suppressed decisions have `_composition_brief: None`.

---

## Tests

Create `tests/test_ad645_phase3_metacognitive.py` with the following tests:

### WorkingMemory Tests

1. **test_record_reasoning_stores_entry** — Call `record_reasoning()` with a summary string. Assert `_recent_reasoning` has 1 entry with `category="reasoning"`.

2. **test_reasoning_deque_maxlen** — Create `AgentWorkingMemory(max_recent_reasoning=3)`. Record 5 reasoning entries. Assert `_recent_reasoning` has exactly 3 entries (oldest evicted).

3. **test_render_context_includes_reasoning** — Record a reasoning entry. Call `render_context()`. Assert output contains "Recent reasoning:" and the entry's content.

4. **test_reasoning_priority_between_actions_and_conversations** — Record an action, a reasoning entry, and a conversation. Call `render_context()`. Assert "Recent reasoning:" appears after "Recent actions:" and before "Recent conversations:" in the output.

5. **test_render_context_no_reasoning_when_empty** — Call `render_context()` with no reasoning entries recorded. Assert "Recent reasoning:" does NOT appear in output.

6. **test_to_dict_includes_reasoning** — Record a reasoning entry. Call `to_dict()`. Assert `"recent_reasoning"` key exists and contains 1 entry with correct fields.

7. **test_from_dict_restores_reasoning** — Create a dict with `"recent_reasoning"` containing an entry with a recent timestamp. Call `from_dict()`. Assert `_recent_reasoning` has 1 entry.

8. **test_from_dict_prunes_stale_reasoning** — Create a dict with `"recent_reasoning"` containing an entry with a timestamp > 24h old. Call `from_dict()`. Assert `_recent_reasoning` is empty (entry pruned).

9. **test_from_dict_backward_compat_no_reasoning_key** — Create a dict WITHOUT `"recent_reasoning"` key (pre-AD-645 data). Call `from_dict()`. Assert no error and `_recent_reasoning` is empty.

### Chain Integration Tests

10. **test_composition_brief_in_chain_result** — Mock `_sub_task_executor.execute()` to return a list containing a successful ANALYZE `SubTaskResult` with `composition_brief` in `result` dict, plus a successful COMPOSE result. Call `_execute_sub_task_chain()`. Assert the returned dict contains `"_composition_brief"` with the brief dict.

11. **test_composition_brief_none_when_suppressed** — Mock executor to return results where EVALUATE recommends suppress. Call `_execute_sub_task_chain()`. Assert `"_composition_brief"` is `None` in returned dict.

12. **test_composition_brief_recorded_to_working_memory** — Set up an agent with `_working_memory`. Create a decision dict with `sub_task_chain=True` and `_composition_brief` containing `situation` and `response_should_cover` fields. Simulate the post-execution recording path. Assert `_working_memory._recent_reasoning` has 1 entry containing the situation text.

13. **test_composition_brief_not_recorded_when_null** — Create a decision dict with `_composition_brief=None`. Simulate post-execution recording. Assert `_working_memory._recent_reasoning` is empty.

14. **test_composition_brief_summary_format** — Create a brief with `situation="Captain asked about crew"` and `response_should_cover=["trust scores", "duty reports"]`. Simulate recording. Assert the stored entry's content contains "Captain asked about crew" and "Planned to cover: trust scores; duty reports".

15. **test_reasoning_survives_stasis_roundtrip** — Record a reasoning entry. Call `to_dict()`. Call `from_dict()` with the result. Assert reasoning entry is preserved. Then call `render_context()` and assert "Recent reasoning:" appears.

---

## Verification

After implementation:

1. `pytest tests/test_ad645_phase3_metacognitive.py -x -q` — all 15 tests pass
2. `pytest tests/test_ad645_composition_briefs.py -x -q` — all 15 Phase 1+2 tests still pass
3. `pytest tests/test_ad644*.py -x -q` — all 35 AD-644 tests still pass
4. `grep -c "record_reasoning" src/probos/cognitive/agent_working_memory.py` — returns 1 (method definition)
5. `grep -c "_composition_brief" src/probos/cognitive/cognitive_agent.py` — returns 4 (extract, return, suppress return, record)
6. `grep -c "recent_reasoning" src/probos/cognitive/agent_working_memory.py` — returns 4 (deque init, render, to_dict, from_dict)
