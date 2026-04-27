# AD-669: Cross-Thread Conclusion Sharing

**Status:** Ready for builder
**Complexity:** Medium (~170 lines across 3 files + 14 tests)
**Prerequisites:** AD-573 (Working Memory), AD-492 (Correlation IDs)

## Overview

When an agent handles multiple concurrent intents (e.g., two Ward Room threads arriving simultaneously), each cognitive lifecycle runs independently with no awareness of what the other concluded. This causes redundant analysis and occasionally contradictory responses.

AD-669 adds a **ConclusionLog** to `AgentWorkingMemory`. After each cognitive lifecycle completes, the agent records a one-line conclusion. Sibling threads see these conclusions in their working memory context injection, enabling coordination without explicit message passing.

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/cognitive/agent_working_memory.py` | Add `ConclusionEntry` dataclass, `ConclusionType` StrEnum, conclusion deque + API methods, render support, serialization |
| `src/probos/cognitive/cognitive_agent.py` | Record conclusion after chain execution; inject sibling conclusions before `decide()` |
| `src/probos/config.py` | Add `conclusion_ttl_seconds` and `max_conclusions` to `WorkingMemoryConfig` |
| `tests/test_ad669_conclusion_sharing.py` | New test file, 14 tests |

---

## Implementation

### Section 1: ConclusionType StrEnum and ConclusionEntry Dataclass

**File:** `src/probos/cognitive/agent_working_memory.py`

Add imports and new types **after** the existing `ActiveEngagement` class (after line 64), **before** the `AgentWorkingMemory` class (line 67).

Add `StrEnum` to the imports from the `enum` module at the top of the file:

```python
from enum import StrEnum
```

Then add the new types:

```python
class ConclusionType(StrEnum):
    """AD-669: Types of conclusions a cognitive thread can reach."""
    DECISION = "decision"        # Agent chose a course of action
    OBSERVATION = "observation"  # Agent noticed something noteworthy
    ESCALATION = "escalation"    # Agent escalated to another agent or Captain
    COMPLETION = "completion"    # Agent finished a task or duty cycle


@dataclass
class ConclusionEntry:
    """AD-669: A conclusion reached by a cognitive thread.

    Recorded after chain execution completes. Sibling threads
    receive these in their working memory context injection.
    """
    thread_id: str              # Intent ID or engagement ID of the concluding thread
    conclusion_type: ConclusionType
    summary: str                # One-line human-readable conclusion
    timestamp: float = field(default_factory=time.time)
    relevance_tags: list[str] = field(default_factory=list)
    correlation_id: str | None = None  # AD-492 link when available
```

### Section 2: Conclusion Deque on AgentWorkingMemory

**File:** `src/probos/cognitive/agent_working_memory.py`

In `AgentWorkingMemory.__init__()`, add a new parameter `max_conclusions: int = 20` and a corresponding deque. Add it after the `_correlation_id` field (after line 107):

```python
        # AD-669: Cross-thread conclusion log
        self._conclusions: deque[ConclusionEntry] = deque(maxlen=max_conclusions)
```

### Section 3: Conclusion Write API

**File:** `src/probos/cognitive/agent_working_memory.py`

Add the following method in the "Write API" section, after `clear_correlation_id()` (after line 225):

```python
    def record_conclusion(
        self,
        thread_id: str,
        conclusion_type: ConclusionType,
        summary: str,
        *,
        relevance_tags: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """AD-669: Record a conclusion reached by a cognitive thread.

        Called after chain execution completes. Sibling threads will
        see this conclusion in their working memory context.
        """
        if not summary or not summary.strip():
            return  # Skip empty conclusions
        self._conclusions.append(ConclusionEntry(
            thread_id=thread_id,
            conclusion_type=conclusion_type,
            summary=summary.strip()[:200],  # Cap length
            relevance_tags=relevance_tags or [],
            correlation_id=correlation_id or self._correlation_id,
        ))
```

### Section 4: Conclusion Read API

**File:** `src/probos/cognitive/agent_working_memory.py`

Add the following methods after `record_conclusion()`:

```python
    def get_active_conclusions(
        self,
        *,
        exclude_thread: str | None = None,
        max_age_seconds: float = 1800.0,
    ) -> list[ConclusionEntry]:
        """AD-669: Get conclusions from sibling threads, excluding the caller's own.

        Returns conclusions younger than max_age_seconds, ordered oldest-first.
        """
        now = time.time()
        return [
            c for c in self._conclusions
            if (now - c.timestamp) < max_age_seconds
            and (exclude_thread is None or c.thread_id != exclude_thread)
        ]

    def render_conclusions(
        self,
        *,
        exclude_thread: str | None = None,
        max_age_seconds: float = 1800.0,
        budget: int = 500,
    ) -> str:
        """AD-669: Render sibling conclusions for LLM context injection.

        Returns empty string if no active sibling conclusions exist.
        Budget is in estimated tokens (chars / 4).
        """
        conclusions = self.get_active_conclusions(
            exclude_thread=exclude_thread,
            max_age_seconds=max_age_seconds,
        )
        if not conclusions:
            return ""

        lines = ["--- Sibling Thread Conclusions ---"]
        total_chars = len(lines[0])
        budget_chars = budget * CHARS_PER_TOKEN

        for c in conclusions:
            age = self._format_age(time.time() - c.timestamp)
            tags = f" [{', '.join(c.relevance_tags)}]" if c.relevance_tags else ""
            line = f"  - [{c.conclusion_type}] ({age} ago) {c.summary}{tags}"
            if total_chars + len(line) > budget_chars:
                break
            lines.append(line)
            total_chars += len(line)

        if len(lines) == 1:
            return ""  # Only header, no conclusions fit

        lines.append("--- End Sibling Conclusions ---")
        return "\n".join(lines)
```

### Section 5: Render Conclusions in Working Memory Context

**File:** `src/probos/cognitive/agent_working_memory.py`

In `render_context()`, add a new priority level for sibling conclusions. Insert **between Priority 5 (observations) and Priority 6 (cognitive state)**, shifting existing priorities 6 and 7 to 7 and 8.

After the Priority 5 block (after line 276), add:

```python
        # Priority 6: Sibling thread conclusions (AD-669)
        conclusion_text = self.render_conclusions()
        if conclusion_text:
            sections.append((6, conclusion_text))
```

Update the existing Priority 6 (cognitive state) comment to say Priority 7 and change its tuple value from `(6, ...)` to `(7, ...)`.

Update the existing Priority 7 (events) comment to say Priority 8 and change its tuple value from `(7, ...)` to `(8, ...)`.

### Section 6: Serialization — to_dict Extension

**File:** `src/probos/cognitive/agent_working_memory.py`

In `to_dict()`, add a `"conclusions"` key to the returned dict after the `"cognitive_state"` entry:

```python
            "conclusions": [
                {
                    "thread_id": c.thread_id,
                    "conclusion_type": c.conclusion_type.value,
                    "summary": c.summary,
                    "timestamp": c.timestamp,
                    "relevance_tags": c.relevance_tags,
                    "correlation_id": c.correlation_id,
                }
                for c in self._conclusions
            ],
```

### Section 7: Serialization — from_dict Extension

**File:** `src/probos/cognitive/agent_working_memory.py`

In `from_dict()`, restore conclusions after the `_restore_entries` calls and before the active engagements restoration. Add after line 430 (`_restore_entries(data.get("recent_reasoning", []), wm._recent_reasoning)`):

```python
        # AD-669: Restore conclusions (with TTL pruning)
        for raw_c in data.get("conclusions", []):
            age = now - raw_c.get("timestamp", 0)
            if age < stale_threshold_seconds:
                try:
                    wm._conclusions.append(ConclusionEntry(
                        thread_id=raw_c.get("thread_id", ""),
                        conclusion_type=ConclusionType(raw_c.get("conclusion_type", "completion")),
                        summary=raw_c.get("summary", ""),
                        timestamp=raw_c.get("timestamp", now),
                        relevance_tags=raw_c.get("relevance_tags", []),
                        correlation_id=raw_c.get("correlation_id"),
                    ))
                except (ValueError, KeyError):
                    pass  # Skip malformed conclusion entries
```

### Section 8: Config — WorkingMemoryConfig Extension

**File:** `src/probos/config.py`

Add two fields to `WorkingMemoryConfig` (after line 681, the `stale_threshold_hours` field):

```python
    conclusion_ttl_seconds: float = 1800.0  # AD-669: Conclusion decay TTL (30 minutes)
    max_conclusions: int = 20  # AD-669: Max conclusions in ring buffer
```

### Section 9: Record Conclusion After Chain Execution

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_run_cognitive_lifecycle()`, add conclusion recording **after** the AD-573 action summary block (after line 2462, `logger.debug("AD-573: Working memory action record failed", exc_info=True)`).

```python
        # AD-669: Record conclusion for cross-thread sharing
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                from probos.cognitive.agent_working_memory import ConclusionType
                _conclusion_summary = self._extract_conclusion_summary(decision, result)
                if _conclusion_summary:
                    _conclusion_type = self._classify_conclusion(intent, decision)
                    _wm.record_conclusion(
                        thread_id=intent.id,
                        conclusion_type=_conclusion_type,
                        summary=_conclusion_summary,
                        relevance_tags=self._extract_relevance_tags(intent),
                    )
        except Exception:
            logger.debug("AD-669: Conclusion recording failed", exc_info=True)
```

### Section 10: Conclusion Extraction Helpers

**File:** `src/probos/cognitive/cognitive_agent.py`

Add three helper methods near `_summarize_action()` (after line 3100, the end of `_summarize_action`).

```python
    @staticmethod
    def _extract_conclusion_summary(decision: dict, result: dict) -> str:
        """AD-669: Extract a one-line conclusion from chain execution results.

        Prefers the composition brief situation if available, otherwise
        truncates the llm_output. Returns empty string for NO_RESPONSE.
        """
        llm_output = decision.get("llm_output", "")
        if not llm_output or "[NO_RESPONSE]" in llm_output:
            return ""

        # Prefer composition brief (AD-645) — it's already a concise summary
        brief = decision.get("_composition_brief")
        if isinstance(brief, dict):
            situation = brief.get("situation", "")
            if situation:
                return situation[:200]

        # Fallback: first sentence of LLM output
        first_line = llm_output.split("\n")[0].strip()
        if len(first_line) > 200:
            return first_line[:197] + "..."
        return first_line

    @staticmethod
    def _classify_conclusion(intent, decision: dict) -> "ConclusionType":
        """AD-669: Classify conclusion type from intent and decision context."""
        from probos.cognitive.agent_working_memory import ConclusionType

        llm_output = (decision.get("llm_output") or "").lower()

        # Check for escalation patterns
        if "escalat" in llm_output or "captain" in llm_output or decision.get("compound"):
            return ConclusionType.ESCALATION

        # Proactive thinks are observations
        if intent.intent == "proactive_think":
            return ConclusionType.OBSERVATION

        # Duty completions
        if decision.get("duty"):
            return ConclusionType.COMPLETION

        # Default: decision (agent decided on a response)
        return ConclusionType.DECISION

    @staticmethod
    def _extract_relevance_tags(intent) -> list[str]:
        """AD-669: Extract relevance tags from the intent for conclusion indexing."""
        tags: list[str] = []
        if intent.intent:
            tags.append(intent.intent)
        channel = intent.params.get("channel_name", "")
        if channel:
            tags.append(f"channel:{channel}")
        topic = intent.params.get("topic", "")
        if topic:
            tags.append(f"topic:{topic}")
        return tags[:5]  # Cap tag count
```

### Section 11: Inject Sibling Conclusions Before decide()

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_run_cognitive_lifecycle()`, inject sibling conclusions into the observation dict. Add **after** line 2293 (the cognitive skill instructions injection block), **before** the `decision = await self.decide(observation)` call on line 2295:

```python
        # AD-669: Inject sibling thread conclusions into observation
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _sibling_text = _wm.render_conclusions(exclude_thread=intent.id)
            if _sibling_text:
                observation["_sibling_conclusions"] = _sibling_text
```

This will be picked up by `_build_user_message()` which includes all observation keys in the user message construction. No additional wiring needed in the rendering path — the key will appear in the observation dict alongside other context keys.

---

## Tests

**File:** `tests/test_ad669_conclusion_sharing.py`

All tests target `AgentWorkingMemory` and the new dataclass/enum directly. No LLM mocking needed.

### Test 1: `test_conclusion_type_enum_values`
Verify `ConclusionType` has exactly four members: DECISION, OBSERVATION, ESCALATION, COMPLETION with correct string values.

### Test 2: `test_conclusion_entry_defaults`
Create a `ConclusionEntry` with only required fields. Verify `timestamp` is auto-set, `relevance_tags` defaults to empty list, `correlation_id` defaults to None.

### Test 3: `test_record_conclusion_happy_path`
Create `AgentWorkingMemory`, call `record_conclusion()` with all fields. Verify `get_active_conclusions()` returns it. Check all fields round-trip correctly.

### Test 4: `test_record_conclusion_empty_summary_skipped`
Call `record_conclusion()` with empty string and whitespace-only summary. Verify `get_active_conclusions()` returns empty list.

### Test 5: `test_record_conclusion_summary_truncated`
Call `record_conclusion()` with a 500-char summary. Verify the stored summary is truncated to 200 characters.

### Test 6: `test_get_active_conclusions_excludes_own_thread`
Record 3 conclusions with different thread IDs. Call `get_active_conclusions(exclude_thread="thread-2")`. Verify only 2 conclusions returned (thread-2 excluded).

### Test 7: `test_get_active_conclusions_ttl_expiry`
Record a conclusion, then monkeypatch `time.time` to return `now + 1801`. Call `get_active_conclusions(max_age_seconds=1800.0)`. Verify empty list returned.

### Test 8: `test_get_active_conclusions_ttl_not_expired`
Record a conclusion, then monkeypatch `time.time` to return `now + 900`. Call `get_active_conclusions(max_age_seconds=1800.0)`. Verify conclusion returned.

### Test 9: `test_render_conclusions_empty_when_none`
Create `AgentWorkingMemory` with no conclusions. Call `render_conclusions()`. Verify returns empty string.

### Test 10: `test_render_conclusions_format`
Record 2 conclusions of different types. Call `render_conclusions()`. Verify output starts with `"--- Sibling Thread Conclusions ---"`, ends with `"--- End Sibling Conclusions ---"`, contains `[decision]` and `[observation]` tags, and includes the summary text.

### Test 11: `test_render_conclusions_budget_limit`
Record 10 conclusions each with 100-char summaries. Call `render_conclusions(budget=50)`. Verify not all 10 appear (budget should truncate).

### Test 12: `test_render_context_includes_conclusions`
Record a conclusion. Call `render_context(budget=5000)`. Verify the output contains `"Sibling Thread Conclusions"`.

### Test 13: `test_to_dict_includes_conclusions`
Record a conclusion. Call `to_dict()`. Verify `"conclusions"` key exists, contains one entry with correct fields including `conclusion_type` as a string value.

### Test 14: `test_from_dict_restores_conclusions`
Create a dict with a `"conclusions"` list containing one valid entry. Call `from_dict()`. Verify the restored memory has one active conclusion with correct type and summary. Also test that an entry with a timestamp older than `stale_threshold_seconds` is pruned.

### Test 15: `test_conclusion_ring_buffer_maxlen`
Create `AgentWorkingMemory` with default settings. Record 25 conclusions. Verify only 20 are retained (maxlen enforcement).

### Test 16: `test_correlation_id_auto_attached`
Set `wm.set_correlation_id("corr-123")`. Record a conclusion without explicit `correlation_id`. Verify the stored conclusion has `correlation_id="corr-123"`.

---

## Run Tests

```bash
# After each section, run targeted tests:
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad669_conclusion_sharing.py -v

# After all sections complete, run full suite:
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

1. **PROGRESS.md** — Add entry: `AD-669 | Cross-Thread Conclusion Sharing | CLOSED`
2. **docs/development/roadmap.md** — Update AD-669 row status to COMPLETE
3. **DECISIONS.md** — Add entry:
   > **AD-669: Cross-Thread Conclusion Sharing** — ConclusionLog in AgentWorkingMemory enables intra-agent coordination between concurrent thought threads. ConclusionEntry dataclass with ConclusionType StrEnum (DECISION/OBSERVATION/ESCALATION/COMPLETION). TTL-based decay (30min default). Rendered as priority 6 in working memory context. Recorded after chain execution, injected before decide(). No embedding-based redundancy detection — simple presence-in-context lets the LLM decide relevance.

---

## Scope Boundaries

- Do NOT add embedding-based semantic similarity for redundancy detection. The LLM sees sibling conclusions in context and can self-coordinate. Keep it simple.
- Do NOT modify `_build_user_message()` or `_build_cognitive_baseline()`. The conclusion text flows through `render_context()` which is already wired into `_build_cognitive_baseline()` at line 3225.
- Do NOT add new event types or NATS messages. This is purely intra-agent, in-memory coordination.
- Do NOT modify `attention.py`, `sub_task.py`, or `llm_client.py`.
- Do NOT add new API endpoints.
