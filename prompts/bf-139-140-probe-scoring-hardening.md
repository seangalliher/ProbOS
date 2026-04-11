# BF-139 + BF-140: Memory Probe Scoring — Recall Gap + Probe Hardening

**Issues:** #147 (BF-139), #148 (BF-140)
**Priority:** High (BF-139), Medium (BF-140)
**Extends:** AD-584b (query reformulation)
**Relates to:** BF-133, BF-134, BF-138, AD-582c
**Estimated tests:** 25–30 new tests across 3 test files

## Context

Qualification results show:
- `temporal_reasoning_probe`: **15/15 agents fail** (0.000–0.209)
- `seeded_recall_probe`: **5/15 agents fail** (0.000–0.509 vs 0.6 threshold)
- `pathologist`: **6 probes fail** — 5 via timeout (27 total across runs), 1 via scoring
  - Root cause: 467 episodes (most of any agent, ~2x medical peers) → 25.2s avg probe duration (vs 12-15s fleet avg) → multi-step probes exceed 60s timeout
  - NOT exception propagation — all failures are `"Test timed out"`

Three compounding root causes (temporal + seeded_recall):
1. AD-584b's `_REFORMULATION_PATTERNS` misses common question forms ("what happened", "what did")
2. Temporal probe keyword scoring collides on stopwords, causing false-positive penalties
3. Temporal probe has no LLM fallback scorer (unlike seeded_recall_probe)

Plus two hardening items:
4. `_send_probe()` has no exception handling — would propagate silently to `score=0.0` if exceptions occur
5. Pathologist timeout: episode volume causes 2x probe latency (BF-140 scope reduction — see below)

## Engineering Principles

- **DRY:** Reuse existing `_STOP_WORDS` from `embeddings.py` in the probe keyword filter
- **Fail Fast:** `_send_probe()` must capture and log exceptions, not let them silently produce 0.0
- **Defense in Depth:** Multiple scoring paths (faithfulness + LLM) prevent single-point scoring failure
- **SOLID (O):** Extend `_REFORMULATION_PATTERNS` list — open for extension, closed for modification
- **Law of Demeter:** Probes access `runtime.llm_client` directly (established pattern, no new coupling)

## Phase 1: Query Reformulation Gap (BF-139 core fix)

### File: `src/probos/knowledge/embeddings.py`

**What to change:** Add missing reformulation patterns to `_REFORMULATION_PATTERNS` (line 202).

**Current patterns (for reference — do NOT modify these):**
```python
_REFORMULATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^what (?:is|are) (.+)", re.IGNORECASE), r"\1 is"),
    (re.compile(r"^what (?:was|were) (.+)", re.IGNORECASE), r"\1 was"),
    (re.compile(r"^how does (.+?) work\b", re.IGNORECASE), r"\1 works by"),
    (re.compile(r"^how did (.+?) happen\b", re.IGNORECASE), r"\1 happened by"),
    (re.compile(r"^how (?:many|much) (.+)", re.IGNORECASE), r"\1 is"),
    (re.compile(r"^who (?:did|does|is|was) (.+)", re.IGNORECASE), r"\1"),
    (re.compile(r"^when did (.+)", re.IGNORECASE), r"\1 happened"),
    (re.compile(r"^why (?:did|does|do|is|was) (.+)", re.IGNORECASE), r"\1 because"),
    (re.compile(r"^(?:did|does|do|is|are|was|were|has|have|had|can|could|will|would|should) (.+)", re.IGNORECASE), r"\1"),
]
```

**Add these patterns BEFORE the final catch-all pattern (the `did|does|do|is|...` line):**
```python
(re.compile(r"^what (?:happened|occurred|took place) (?:during|in|at|with) (.+)", re.IGNORECASE), r"\1"),
(re.compile(r"^what did (.+)", re.IGNORECASE), r"\1"),
(re.compile(r"^(?:tell me|talk) about (.+)", re.IGNORECASE), r"\1"),
(re.compile(r"^what (?:happened|occurred)\b", re.IGNORECASE), r"events that occurred"),
```

**Rationale:** The temporal probe asks "What happened during first watch?" — the first new pattern captures this. "What did X do?" is another common probe form. "Tell me about X" appears in personality probes. The standalone "What happened?" (no qualifier) needs a generic reformulation.

**Order matters:** These MUST go before the final catch-all `^(?:did|does|...)` pattern because regex matching stops at the first match.

### Tests: `tests/test_ad584_recall_qa_fix.py`

Add a test class `TestReformulationCoverage` (or extend existing) with these cases:

```python
# Every probe question form must produce a reformulation
@pytest.mark.parametrize("question,expected_variant_count", [
    ("What happened during first watch?", 2),
    ("What was discussed most recently?", 2),
    ("What pool health threshold was configured?", 2),
    ("What did the Science department identify?", 2),
    ("Tell me about the trust anomaly", 2),
    ("What happened?", 2),
    # Existing patterns still work (regression)
    ("What is the current pool health?", 2),
    ("How does the routing system work?", 2),
    ("When did the anomaly occur?", 2),
    ("Why did the agent fail?", 2),
])
def test_probe_questions_reformulate(question, expected_variant_count):
    from probos.knowledge.embeddings import reformulate_query
    variants = reformulate_query(question)
    assert len(variants) == expected_variant_count, (
        f"Question '{question}' produced {len(variants)} variants "
        f"(expected {expected_variant_count}): {variants}"
    )
```

Also add negative tests: non-question text should produce 1 variant only.

## Phase 2: Temporal Probe Scoring Hardening (BF-139 scoring fix)

### File: `src/probos/cognitive/memory_probes.py`

**Change 1: Import `_STOP_WORDS` and add keyword filter helper.**

At the top of the file (after existing imports, around line 25), add:

```python
from probos.knowledge.embeddings import _STOP_WORDS
```

Add a module-level helper function (after `_ward_room_content`, around line 165):

```python
def _distinctive_keywords(text: str, min_len: int = 3) -> list[str]:
    """Extract distinctive keywords from text, filtering stopwords.

    BF-139: Replaces naive c.lower().split()[:4] which included stopwords
    like 'to', 'the', 'agents' causing false-positive wrong-watch penalties.
    """
    return [
        w for w in text.lower().split()
        if len(w) >= min_len and w not in _STOP_WORDS
    ]
```

**Change 2: Fix keyword collision in `TemporalReasoningProbe._run_inner()`.**

Replace lines 519-526 (the keyword matching block):

```python
# CURRENT (broken):
correct_found = sum(1 for c in correct_content if any(
    kw in resp_lower for kw in c.lower().split()[:4]
))
incorrect_found = sum(1 for c in wrong_content if any(
    kw in resp_lower for kw in c.lower().split()[:4]
))
```

With:

```python
# BF-139: Use distinctive keywords (stopword-filtered, all words)
correct_found = sum(1 for c in correct_content if any(
    kw in resp_lower for kw in _distinctive_keywords(c)
))
incorrect_found = sum(1 for c in wrong_content if any(
    kw in resp_lower for kw in _distinctive_keywords(c)
))
```

**Change 3: Add LLM fallback scorer to `TemporalReasoningProbe`.**

After the `check_faithfulness` call and penalty calculation (after line 536), add LLM scoring matching the `SeededRecallProbe` pattern (lines 274-282 of same file):

```python
# BF-139: LLM fallback scorer (matches SeededRecallProbe pattern)
if getattr(runtime, "llm_client", None):
    llm_score = await _llm_extract_float(
        runtime.llm_client,
        f"Expected content (from {question}):\n"
        + "\n".join(f"- {c}" for c in correct_content)
        + f"\n\nAgent response: {response_text[:300]}\n\n"
        "Rate 0.0 (completely wrong/missing) to 1.0 (accurate temporal "
        "scoping — mentions correct content, excludes wrong time period). "
        "Reply with a single number.",
    )
    if llm_score is not None:
        score = (score + llm_score) / 2
```

This goes AFTER the penalty application (line 536: `score = max(0.0, score - 0.3 * incorrect_found)`) and BEFORE `per_question.append(...)` (line 538).

### Tests: `tests/test_ad582_memory_probes.py`

Add tests for the scoring fix:

```python
class TestTemporalProbeScoringBF139:
    """BF-139: Temporal probe scoring hardening."""

    def test_distinctive_keywords_filters_stopwords(self):
        from probos.cognitive.memory_probes import _distinctive_keywords
        kws = _distinctive_keywords("Pool health dropped to 45%")
        assert "to" not in kws
        assert "pool" in kws
        assert "health" in kws
        assert "dropped" in kws

    def test_distinctive_keywords_filters_short_words(self):
        from probos.cognitive.memory_probes import _distinctive_keywords
        kws = _distinctive_keywords("A to B is on")
        assert len(kws) == 0  # all filtered

    def test_distinctive_keywords_captures_all_words(self):
        """BF-139: Uses all distinctive words, not just first 4."""
        from probos.cognitive.memory_probes import _distinctive_keywords
        text = "Trust anomaly detected between analyst and researcher agents"
        kws = _distinctive_keywords(text)
        assert "trust" in kws
        assert "anomaly" in kws
        assert "detected" in kws
        assert "analyst" in kws
        assert "researcher" in kws
        assert "agents" in kws
        # Stopwords filtered
        assert "between" not in kws
        assert "and" not in kws
```

Also add a specific regression test ensuring the temporal probe episode keywords don't collide:

```python
    def test_temporal_episodes_no_keyword_collision(self):
        """BF-139: First-watch keywords must not appear in second-watch episodes."""
        from probos.cognitive.memory_probes import _distinctive_keywords, _TEMPORAL_EPISODES

        first_kws = set()
        second_kws = set()
        for ep in _TEMPORAL_EPISODES:
            kws = set(_distinctive_keywords(ep["content"]))
            if ep["watch"] == "first_watch":
                first_kws |= kws
            else:
                second_kws |= kws

        collision = first_kws & second_kws
        assert not collision, (
            f"Keyword collision between watch sections: {collision}. "
            "This causes false-positive wrong-watch penalties."
        )
```

**Important:** If the collision test fails, the `_TEMPORAL_EPISODES` content strings need to be made more distinctive. Replace to use more clearly differentiated content. Suggested replacement if needed:

```python
_TEMPORAL_EPISODES = [
    # First watch — pool/routing topics
    {"content": "Pool health dropped to 45% during the monitoring sweep",
     "watch": "first_watch", "offset": 0},
    {"content": "Engineering rerouted 3 agents to handle increased load",
     "watch": "first_watch", "offset": 600},
    # Second watch — trust/counselor topics
    {"content": "Trust anomaly detected between analyst and researcher agents",
     "watch": "second_watch", "offset": 7200},
    {"content": "Counselor initiated therapeutic intervention for low-trust agent",
     "watch": "second_watch", "offset": 7800},
]
```

Check whether "agents" appears in both watches. If so, revise episode content to eliminate cross-watch keyword overlap. Priority: the test must pass; if content needs tweaking, tweak it.

## Phase 3: Probe Diagnostic Enhancement (BF-140)

**Revised scope:** Original diagnosis assumed exception propagation. Actual root cause is
pathologist timeout from heavy episodic memory (467 episodes → 2x probe latency). Phase 3
is now **defensive hardening** — the `_send_probe()` fix prevents silent failures if future
exceptions arise, and stage markers aid latency diagnosis.

### File: `src/probos/cognitive/qualification_tests.py`

**Change 1: Add exception handling to `_send_probe()`.**

Replace the current `_send_probe` function (lines 42-54) with:

```python
async def _send_probe(agent: Any, message: str) -> str:
    """Send a probe message to an agent via handle_intent() with episode suppression.

    BF-140: Added exception handling. Captures and logs exceptions instead of
    propagating them to the probe's outer handler (which returns score=0.0
    with no diagnostic info).
    """
    from probos.types import IntentMessage

    intent = IntentMessage(
        intent="direct_message",
        params={"text": message, "_qualification_test": True},
        target_agent_id=agent.id,
    )
    try:
        result = await agent.handle_intent(intent)
        if result and result.result:
            return str(result.result)
        return ""
    except Exception as exc:
        logger.warning(
            "BF-140: _send_probe failed for agent %s (type=%s): %s",
            getattr(agent, "id", "?"),
            getattr(agent, "agent_type", "?"),
            exc,
            exc_info=True,
        )
        return ""
```

**Note:** Verify that `logger` is defined at module level in `qualification_tests.py`. If not, add:
```python
import logging
logger = logging.getLogger(__name__)
```

**Change 2: Add stage markers to PersonalityProbe._run_inner().**

Inside `PersonalityProbe._run_inner()`, add diagnostic logging at key stages. Find the method (approximately line 216) and add `logger.debug(...)` calls before:
1. `load_seed_profile()` call
2. `_send_probe()` call
3. LLM scoring call
4. Final score calculation

Pattern (insert at the start of `_run_inner`):
```python
logger.debug("BF-140: PersonalityProbe starting for agent %s", agent_id)
```

And before the `_send_probe` call:
```python
logger.debug("BF-140: PersonalityProbe sending probe to agent %s", agent_id)
```

Apply the same pattern to `TemperamentProbe._run_inner()`.

### Tests: `tests/test_bf139_140_probe_hardening.py` (new file)

Create a new test file for BF-139/140 specific tests:

```python
"""BF-139 + BF-140: Probe scoring hardening and diagnostic enhancement tests."""

from __future__ import annotations

import pytest


class TestSendProbeExceptionHandling:
    """BF-140: _send_probe must not propagate exceptions."""

    @pytest.mark.asyncio
    async def test_send_probe_returns_empty_on_exception(self):
        """_send_probe returns '' when handle_intent raises."""
        from probos.cognitive.qualification_tests import _send_probe

        class FakeAgent:
            id = "test_agent"
            agent_type = "test"
            async def handle_intent(self, intent):
                raise RuntimeError("LLM client unavailable")

        result = await _send_probe(FakeAgent(), "test message")
        assert result == ""

    @pytest.mark.asyncio
    async def test_send_probe_returns_empty_on_none_result(self):
        """_send_probe returns '' when handle_intent returns None."""
        from probos.cognitive.qualification_tests import _send_probe

        class FakeAgent:
            id = "test_agent"
            agent_type = "test"
            async def handle_intent(self, intent):
                return None

        result = await _send_probe(FakeAgent(), "test message")
        assert result == ""


class TestReformulationPatterns:
    """BF-139: Reformulation pattern coverage for probe questions."""

    @pytest.mark.parametrize("question", [
        "What happened during first watch?",
        "What was discussed most recently?",
        "What did the Science department identify?",
        "Tell me about the trust anomaly",
    ])
    def test_probe_question_produces_reformulation(self, question):
        from probos.knowledge.embeddings import reformulate_query
        variants = reformulate_query(question)
        assert len(variants) >= 2, (
            f"'{question}' should produce at least 2 variants, got {variants}"
        )

    def test_existing_patterns_not_broken(self):
        """Regression: existing patterns still work."""
        from probos.knowledge.embeddings import reformulate_query
        for q in [
            "What is the pool health?",
            "What was the threshold?",
            "When did the failure occur?",
            "Why did the agent crash?",
        ]:
            variants = reformulate_query(q)
            assert len(variants) == 2, f"Regression: '{q}' broke, got {variants}"
```

## Verification Steps

After building, run:

```bash
# Phase 1 verification — reformulation patterns
python -m pytest tests/test_ad584_recall_qa_fix.py -k reformulat -v

# Phase 2 verification — temporal probe scoring
python -m pytest tests/test_ad582_memory_probes.py -k temporal -v

# Phase 3 verification — probe diagnostics
python -m pytest tests/test_bf139_140_probe_hardening.py -v

# Full regression — all recall and probe tests
python -m pytest tests/test_ad584_recall_qa_fix.py tests/test_ad582_memory_probes.py tests/test_bf139_140_probe_hardening.py -v
```

## Files Modified (Summary)

| File | Phase | Change |
|------|-------|--------|
| `src/probos/knowledge/embeddings.py` | 1 | Add 4 reformulation patterns |
| `src/probos/cognitive/memory_probes.py` | 2 | Import `_STOP_WORDS`, add `_distinctive_keywords()`, fix temporal scoring, add LLM scorer |
| `src/probos/cognitive/qualification_tests.py` | 3 | Harden `_send_probe()` with try/except, add diagnostic logging |
| `tests/test_ad584_recall_qa_fix.py` | 1 | Add reformulation coverage parametrize test |
| `tests/test_ad582_memory_probes.py` | 2 | Add temporal keyword collision + scoring tests |
| `tests/test_bf139_140_probe_hardening.py` | 3 | New file — exception handling + reformulation regression tests |

**6 files modified/created, ~25-30 tests added.**

## What This Does NOT Fix

- **AD-584d (enriched embedding):** Planned but separate scope. Embeds `user_input + reflection` at write-time. Complementary to this fix.
- **Seeded recall threshold adjustment:** The 0.6 threshold stays. BF-139 Phase 1 reformulation improvement should push borderline agents above threshold. If it doesn't, follow-up with threshold tuning.
- **BF-140 Pathologist timeout root cause (REVISED):** Investigation revealed the actual root cause is NOT exception propagation. Pathologist (Cortez) has **467 episodic memories** — the most of any agent and ~2x medical peers (diagnostician: 367, surgeon: 231). This bloats recall context, inflating avg probe duration to **25.2s** (vs 12-15s fleet average). Multi-step probes (seeded_recall 8/8 timeouts, mti_temperament 10/12, diagnostic_reasoning 6/12) exceed the 60s `test_timeout_seconds` limit. Phase 3 still hardens `_send_probe()` as defensive practice, but the pathologist timeout requires a separate investigation into: (a) why pathologist accumulates 2x more episodes, (b) whether recall context should be capped during probes, (c) whether the 60s timeout should scale with episode count. This should be a **follow-up BF-141** if pathologist timeouts persist after BF-139 scoring improvements.
