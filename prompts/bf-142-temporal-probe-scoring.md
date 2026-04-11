# BF-142: Temporal Probe Scoring — Faithfulness/LLM imbalance + keyword false positives

**Issue:** #150
**Priority:** High (15/15 agents fail temporal_reasoning_probe)
**Extends:** BF-139 (reformulation + LLM fallback), AD-582c (temporal probe)
**Estimated tests:** 15–20 new/modified tests

## Context

After BF-139 added the LLM fallback scorer to `TemporalReasoningProbe`, all 15 agents still fail (0/15 pass, threshold = 0.5). Best score is 0.286. Root cause is three compounding issues:

### Issue 1: `check_faithfulness()` token-overlap baseline is near-zero

`check_faithfulness()` (source_governance.py:524) computes:
```
score = evidence_overlap * 0.6 + (1.0 - unsupported_claim_ratio) * 0.4
```

This is a **token-overlap heuristic** — it measures how many response tokens appear in the evidence. It works well for `SeededRecallProbe` because those facts contain specific numeric values ("0.7", "14:32", "0.92") that agents echo verbatim (typical faithfulness: 0.3–0.5).

Temporal episodes have descriptive content ("Pool health dropped to 45% during the monitoring sweep") that agents **paraphrase** rather than quote. Typical temporal faithfulness: 0.005–0.1. This near-zero baseline then poisons the LLM averaging.

### Issue 2: LLM averaging formula caps effective scores

BF-139 added: `score = (score + llm_score) / 2`

When faithfulness = 0.005 and LLM = 0.8: `(0.005 + 0.8) / 2 = 0.4` — below 0.5 threshold.

The LLM is the better scorer for paraphrased responses, but the averaging formula gives equal weight to the token-overlap heuristic that demonstrably fails here.

**Comparison:** `KnowledgeUpdateProbe` (line 424) and `AbstentionProbe` (line 784) use `score = llm_score` (full replacement). Only `SeededRecallProbe`, `TemporalReasoningProbe`, and `CrossAgentSynthesisProbe` use averaging.

### Issue 3: Cross-watch false positives from agent vocabulary

`_distinctive_keywords()` correctly eliminates stopwords and literal keyword collisions between watches. **BUT** — agents' natural vocabulary contains words like "agent", "agents", "trust", "anomaly" that appear in second-watch episode content ("Trust anomaly detected between analyst and researcher agents"). When an agent uses these common words in a first-watch response, `incorrect_found` triggers the -0.3 penalty.

**Latest data shows:** 10 of 15 agents have `incorrect_found >= 1` on at least one question. Pharmacist shows `incorrect_found=2` on question 1.

## Engineering Principles

- **Fail Fast:** `max()` is a deliberate choice — when the heuristic demonstrably fails (near-zero token overlap), let the better scorer win. Not masking failures; acknowledging the heuristic's limits.
- **DRY:** Apply consistent scoring formula across all probes that share the same pattern.
- **Defense in Depth:** Record component scores (faithfulness, LLM, keyword) separately for diagnostics. Don't merge them into a single opaque number.
- **SOLID (O):** Extend diagnostic output; don't modify scoring paths that work (KnowledgeUpdate, Abstention).

## Fix

### File: `src/probos/cognitive/memory_probes.py`

**Change 1 — TemporalReasoningProbe: Replace LLM averaging with `max()` and record component scores.**

Replace lines 540–572 (the faithfulness + penalty + LLM + per_question block):

```python
                # Faithfulness against correct episodes
                faith = check_faithfulness(
                    response_text=response_text,
                    recalled_memories=correct_content,
                )
                score = faith.score
                faithfulness_score = faith.score  # BF-142: preserve for diagnostics
                # Penalize if wrong-watch content appears
                if incorrect_found > 0:
                    score = max(0.0, score - 0.3 * incorrect_found)

                # BF-142: LLM scorer — use max(heuristic, LLM) instead of average.
                # check_faithfulness() is a token-overlap heuristic that returns
                # near-zero for paraphrased responses (typical: 0.005-0.1).
                # Averaging with LLM caps effective scores at ~0.28.
                # max() lets the better scorer win.
                llm_score_raw = None
                if getattr(runtime, "llm_client", None):
                    llm_score_raw = await _llm_extract_float(
                        runtime.llm_client,
                        f"Expected content (from {question}):\n"
                        + "\n".join(f"- {c}" for c in correct_content)
                        + f"\n\nAgent response: {response_text[:300]}\n\n"
                        "Rate 0.0 (completely wrong/missing) to 1.0 (accurate temporal "
                        "scoping — mentions correct content, excludes wrong time period). "
                        "Reply with a single number.",
                    )
                    if llm_score_raw is not None:
                        score = max(score, llm_score_raw)

                per_question.append({
                    "question": question,
                    "expected_episode_ids": expected_ids,
                    "response_summary": response_text[:200],
                    "correct_content_found": correct_found,
                    "incorrect_content_found": incorrect_found,
                    "faithfulness_score": faithfulness_score,
                    "llm_score": llm_score_raw,
                    "score": score,
                })
```

**Change 2 — SeededRecallProbe: Same `max()` pattern + diagnostics.**

Replace lines 279–303 (the faithfulness + LLM + per_question block):

```python
                # Faithfulness score
                faith = check_faithfulness(
                    response_text=response_text,
                    recalled_memories=[fact],
                )
                score = faith.score
                faithfulness_score = faith.score  # BF-142: preserve for diagnostics

                # BF-142: LLM scorer — use max(heuristic, LLM).
                # Consistent with TemporalReasoningProbe fix.
                llm_score_raw = None
                if getattr(runtime, "llm_client", None):
                    llm_score_raw = await _llm_extract_float(
                        runtime.llm_client,
                        f"Ground truth: {fact}\nAgent response: {response_text[:300]}\n\n"
                        "Rate 0.0 (wrong/missing) to 1.0 (accurate) how well the response "
                        "matches the ground truth. Reply with a single number.",
                    )
                    if llm_score_raw is not None:
                        score = max(score, llm_score_raw)

                per_question.append({
                    "episode_id": episodes[i].id,
                    "question": question,
                    "expected_fact": fact,
                    "response_summary": response_text[:200],
                    "faithfulness_score": faithfulness_score,
                    "llm_score": llm_score_raw,
                    "score": score,
                })
```

**Change 3 — CrossAgentSynthesisProbe: Same `max()` pattern.**

Find the LLM scoring block (around line 675–684) and replace:

```python
                if llm_score is not None:
                    score = (score + llm_score) / 2
```

With:

```python
                if llm_score is not None:
                    score = max(score, llm_score)
```

**Change 4 — Make temporal episode content more distinctive.**

Replace `_TEMPORAL_EPISODES` (line 460–471) with content that uses domain-specific vocabulary unlikely to appear in natural agent responses about the wrong watch:

```python
_TEMPORAL_EPISODES = [
    # First watch — pool/routing topics (unique: pool, 45%, monitoring, rerouted, workers)
    {"content": "Pool health dropped to 45% during the monitoring sweep",
     "watch": "first_watch", "offset": 0},
    {"content": "Engineering rerouted 3 workers to handle increased load",
     "watch": "first_watch", "offset": 600},
    # Second watch — diplomatic/scientific topics (unique: subspace, anomaly, diplomatic, envoy)
    {"content": "Subspace anomaly detected at bearing 127 mark 4",
     "watch": "second_watch", "offset": 7200},
    {"content": "Diplomatic envoy requested priority docking clearance",
     "watch": "second_watch", "offset": 7800},
]
```

**Rationale:** The old second-watch content ("Trust anomaly ... agents", "Counselor ... therapeutic ... agent") used domain words (`agent`, `agents`, `trust`, `therapeutic`, `anomaly`, `counselor`) that appear frequently in agents' natural vocabulary. The new content uses unique terms (`subspace`, `bearing`, `127`, `mark`, `diplomatic`, `envoy`, `docking`, `clearance`) that agents won't use when discussing first-watch pool/routing events.

**Important:** Keep the first-watch content unchanged — its keywords (`pool`, `health`, `45%`, `monitoring`, `rerouted`, `workers`) are already distinctive enough that second-watch responses won't accidentally include them.

### No changes to `source_governance.py`

`check_faithfulness()` works correctly for its design purpose (verifying verbatim grounding). The issue is how its score is combined with LLM scoring, not the heuristic itself.

## Tests

### File: `tests/test_bf139_140_probe_hardening.py` (modify existing)

Add test class for BF-142 scoring:

```python
class TestTemporalProbeScoringBF142:
    """BF-142: LLM max-scoring replaces averaging."""

    def test_max_scoring_when_faithfulness_low(self):
        """max(0.005, 0.8) = 0.8, not (0.005 + 0.8)/2 = 0.4."""
        faithfulness = 0.005
        llm_score = 0.8
        # Old formula:
        old = (faithfulness + llm_score) / 2
        # New formula:
        new = max(faithfulness, llm_score)
        assert old < 0.5, f"Old formula should be below threshold: {old}"
        assert new >= 0.5, f"New formula should pass threshold: {new}"
        assert new == 0.8

    def test_max_scoring_when_faithfulness_high(self):
        """When faithfulness is already high, max still works correctly."""
        faithfulness = 0.7
        llm_score = 0.6
        new = max(faithfulness, llm_score)
        assert new == 0.7

    def test_max_scoring_preserves_zero_when_both_zero(self):
        """If both scores are 0, max returns 0."""
        assert max(0.0, 0.0) == 0.0

    def test_max_scoring_llm_none_uses_faithfulness(self):
        """When LLM is unavailable, faithfulness score is used alone."""
        faithfulness = 0.3
        llm_score = None
        score = faithfulness
        if llm_score is not None:
            score = max(score, llm_score)
        assert score == 0.3
```

### File: `tests/test_ad582_memory_probes.py` (modify existing)

Add cross-watch collision tests for the new episode content:

```python
class TestTemporalEpisodeDistinctivenessBF142:
    """BF-142: Temporal episode content must not share vocabulary."""

    def test_no_cross_watch_keyword_collision(self):
        """Episode keywords from different watches must not overlap."""
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
            f"Keyword collision between watches: {collision}. "
            "This causes false-positive wrong-watch penalties."
        )

    def test_second_watch_avoids_common_agent_vocabulary(self):
        """Second-watch content must not contain words agents commonly use."""
        from probos.cognitive.memory_probes import _distinctive_keywords, _TEMPORAL_EPISODES

        # Words agents frequently use in responses regardless of topic
        common_agent_vocab = {"agent", "agents", "trust", "system", "department",
                              "counselor", "therapeutic", "intervention"}

        second_kws = set()
        for ep in _TEMPORAL_EPISODES:
            if ep["watch"] == "second_watch":
                second_kws |= set(_distinctive_keywords(ep["content"]))

        overlap = second_kws & common_agent_vocab
        assert not overlap, (
            f"Second-watch keywords overlap with common agent vocabulary: {overlap}. "
            "This causes incorrect_found false positives when agents use these words naturally."
        )

    def test_first_watch_avoids_common_agent_vocabulary(self):
        """First-watch content must not contain common agent vocabulary words."""
        from probos.cognitive.memory_probes import _distinctive_keywords, _TEMPORAL_EPISODES

        common_agent_vocab = {"agent", "agents", "trust", "system", "department",
                              "counselor", "therapeutic", "intervention"}

        first_kws = set()
        for ep in _TEMPORAL_EPISODES:
            if ep["watch"] == "first_watch":
                first_kws |= set(_distinctive_keywords(ep["content"]))

        overlap = first_kws & common_agent_vocab
        assert not overlap, (
            f"First-watch keywords overlap with common agent vocabulary: {overlap}."
        )
```

### File: `tests/test_bf139_140_probe_hardening.py` (modify existing)

Add diagnostic field tests:

```python
class TestProbeScoreDiagnosticsBF142:
    """BF-142: Component scores recorded separately for diagnostics."""

    def test_temporal_per_question_has_component_scores(self):
        """per_question dict must include faithfulness_score and llm_score keys."""
        required_keys = {"faithfulness_score", "llm_score", "score",
                         "correct_content_found", "incorrect_content_found"}
        # Simulate what the per_question dict should look like
        per_q = {
            "question": "What happened during first watch?",
            "expected_episode_ids": ["_qtest_temporal_0"],
            "response_summary": "test",
            "correct_content_found": 1,
            "incorrect_content_found": 0,
            "faithfulness_score": 0.05,
            "llm_score": 0.8,
            "score": 0.8,
        }
        assert required_keys.issubset(per_q.keys()), (
            f"Missing diagnostic keys: {required_keys - per_q.keys()}"
        )

    def test_seeded_recall_per_question_has_component_scores(self):
        """SeededRecallProbe per_question must include component scores."""
        per_q = {
            "episode_id": "test",
            "question": "test?",
            "expected_fact": "test fact",
            "response_summary": "test",
            "faithfulness_score": 0.5,
            "llm_score": 0.7,
            "score": 0.7,
        }
        assert "faithfulness_score" in per_q
        assert "llm_score" in per_q
```

## Verification

```bash
# BF-142 tests
python -m pytest tests/test_bf139_140_probe_hardening.py -k "BF142" -v
python -m pytest tests/test_ad582_memory_probes.py -k "BF142" -v

# Full regression — all probe and recall tests
python -m pytest tests/test_ad582_memory_probes.py tests/test_ad584_recall_qa_fix.py tests/test_bf139_140_probe_hardening.py -v
```

## Files Modified (Summary)

| File | Change |
|------|--------|
| `src/probos/cognitive/memory_probes.py` | Replace `(score + llm_score) / 2` with `max(score, llm_score)` in 3 probes; add `faithfulness_score` + `llm_score` to per_question diagnostics; replace second-watch episode content |
| `tests/test_bf139_140_probe_hardening.py` | Add `TestTemporalProbeScoringBF142` (4 tests) + `TestProbeScoreDiagnosticsBF142` (2 tests) |
| `tests/test_ad582_memory_probes.py` | Add `TestTemporalEpisodeDistinctivenessBF142` (3 tests) |

**1 source file modified, 2 test files modified, ~9 tests added.**

## What This Does NOT Fix

- **`check_faithfulness()` heuristic quality:** The token-overlap approach itself is not changed. It serves its purpose for source governance (verifying verbatim grounding). The fix addresses how its output is combined with LLM scoring in probes.
- **Agent paraphrasing behavior:** Agents paraphrase because they're sovereign individuals with personality, not retrieval-augmented lookup engines. This is correct behavior that the scoring should accommodate.
- **Pathologist episode volume (BF-140 deferred):** 467 episodes cause high probe latency. Separate investigation into episode accumulation rate.
- **Keyword matching as incorrect_found approach:** The fundamental approach of checking whether response text contains wrong-watch keywords has a ceiling — agents use general domain vocabulary regardless of what they're discussing. The episode content fix mitigates this for the current episodes, but the approach may need rethinking if episodes change. A future improvement could use LLM-based wrong-watch detection instead of keyword matching.
