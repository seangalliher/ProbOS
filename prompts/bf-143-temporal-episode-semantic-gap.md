# BF-143: Temporal Episode Semantic Gap — Seeded episodes invisible to recall

**Issue:** TBD (file after review)
**Priority:** High (15/15 agents fail temporal_reasoning_probe)
**Extends:** BF-142 (scoring fix), AD-582c (temporal probe), AD-584b (query reformulation)
**Estimated tests:** 8–10 new tests

## Context

After BF-142 fixed the scoring formula (`max()` instead of averaging), all 15 agents still fail `temporal_reasoning_probe` (0/15 pass, threshold = 0.5). BF-142's scoring fix is correct but irrelevant — **the seeded episodes are never retrieved**.

### Root Cause: Semantic gap between probe questions and episode content

Empirical embedding similarity test (multi-qa-MiniLM-L6-cos-v1) shows:

| Query | Best seeded episode | Similarity | Real memory that beats it |
|-------|-------------------|------------|--------------------------|
| "What happened during first watch?" | Pool health (correct) | 0.151 | Stasis recovery: **0.197** |
| "What was discussed most recently?" | Diplomatic (seeded) | 0.179 | Metacognitive research: **0.411** |

The episode content has **zero temporal vocabulary**:
- Content: `"Pool health dropped to 45% during the monitoring sweep"`
- Question: `"What happened during first watch?"`
- The embedding model can't bridge "first watch" → "Pool health dropped to 45%"

Real agent memories (stasis recovery, qualification probes, metacognitive research) are semantically closer to the probe questions, so they dominate top-k retrieval results. Seeded episodes never reach the agent's context window.

### Why the recall pipeline works correctly

This is NOT a pipeline bug. `recall_weighted()` correctly returns the most semantically relevant memories. The problem is that the seeded test data lacks the temporal tokens needed for semantic matching. In production, real temporal episodes would naturally include temporal context from the Ward Room conversation they were part of.

### Why other probes don't have this problem

`SeededRecallProbe` questions target **specific content** in the episodes:
- Fact: "The pool health threshold was set to 0.7 during this session"
- Question: "What pool health threshold was configured?"

These share vocabulary (`pool`, `health`, `threshold`) — high semantic similarity. The temporal probe's questions target **time periods**, not content.

## Engineering Principles

- **Fail Fast:** The probe tests temporal scoping through the full recall pipeline. If episodes can't be retrieved, the probe correctly reports failure. The fix is in the test data, not the pipeline.
- **Defense in Depth:** Validate the fix with an embedding similarity test — don't assume the temporal prefix creates sufficient similarity.
- **DRY:** Apply the same temporal-prefix pattern to all episodes rather than introducing a different retrieval path.

## Fix

### File: `src/probos/cognitive/memory_probes.py`

**Change 1 — Add temporal markers to `_TEMPORAL_EPISODES` content.**

The embedded document is `_ward_room_content(te["content"], callsign=cs)`. Adding "During first/second watch:" to the content ensures the embedded text contains temporal tokens that match the probe questions.

Replace `_TEMPORAL_EPISODES` (lines 465–476):

```python
_TEMPORAL_EPISODES = [
    # First watch — pool/routing topics
    # BF-143: "During first watch:" prefix creates semantic bridge between
    # probe question ("What happened during first watch?") and episode content.
    # Without this prefix, cosine similarity is ~0.15 and real memories dominate top-k.
    {"content": "During first watch: Pool health dropped to 45% during the monitoring sweep",
     "watch": "first_watch", "offset": 0},
    {"content": "During first watch: Engineering rerouted 3 workers to handle increased load",
     "watch": "first_watch", "offset": 600},
    # Second watch — diplomatic/scientific topics (BF-142: domain-specific vocab)
    {"content": "During second watch: Subspace anomaly detected at bearing 127 mark 4",
     "watch": "second_watch", "offset": 7200},
    {"content": "During second watch: Diplomatic envoy requested priority docking clearance",
     "watch": "second_watch", "offset": 7800},
]
```

**Change 2 — Add probe-local stopwords to `_distinctive_keywords()` for temporal prefix words.**

`_distinctive_keywords()` (line 168) uses `_STOP_WORDS` imported from `probos.knowledge.embeddings` (line 25). That frozenset contains basic English stopwords (`a an the in on at to of is are was were for and or but with from by`). It does NOT contain `"during"`, `"first"`, `"second"`, or `"watch"`.

After adding temporal prefixes, these four words appear in episodes from BOTH watches — they're structural, not distinctive. They will cause cross-watch keyword collisions in the `incorrect_found` check (lines 542–544).

**Do NOT modify the global `_STOP_WORDS` in `embeddings.py`** — that set is used by `_tokenize()` for embedding/keyword search across the system. Instead, add a probe-local augmented set in `memory_probes.py`.

Add near the top of the file (after the `_STOP_WORDS` import at line 25):

```python
# BF-143: Temporal prefix words that appear in all episodes after adding
# "During first/second watch:" prefixes. These are structural, not distinctive,
# and must be excluded from cross-watch keyword matching.
_PROBE_STOP_WORDS = _STOP_WORDS | frozenset({"during", "first", "second", "watch"})
```

Then update `_distinctive_keywords()` (line 176) to use `_PROBE_STOP_WORDS`:

```python
def _distinctive_keywords(text: str, min_len: int = 3) -> list[str]:
    """Extract distinctive keywords from text, filtering stopwords.

    BF-139: Replaces naive c.lower().split()[:4] which included stopwords
    like 'to', 'the', 'agents' causing false-positive wrong-watch penalties.
    BF-143: Added temporal prefix words ('during', 'first', 'second', 'watch')
    to stopword set — structural words from "During first/second watch:" prefix.
    """
    return [
        w for w in text.lower().split()
        if len(w) >= min_len and w not in _PROBE_STOP_WORDS
    ]
```

**Change 3 — Update `correct_content` lists used for faithfulness checking.**

Lines 522–523 extract content for faithfulness scoring:
```python
first_watch_content = [te["content"] for te in _TEMPORAL_EPISODES if te["watch"] == "first_watch"]
second_watch_content = [te["content"] for te in _TEMPORAL_EPISODES if te["watch"] == "second_watch"]
```

These now include the "During first watch:" prefix. This is fine for faithfulness checking — the prefix tokens are neutral for `check_faithfulness()` (they're common words that don't affect token overlap scoring meaningfully). No change needed here.

### No changes to other files

- `episodic.py` — `seed()` correctly embeds `ep.user_input` (which is `_ward_room_content(te["content"])`)
- `embeddings.py` — `reformulate_query()` is unchanged
- `qualification_tests.py` — `_send_probe()` is unchanged
- `source_governance.py` — `check_faithfulness()` is unchanged

## Tests

### File: `tests/test_bf139_140_probe_hardening.py` (add new class)

```python
class TestTemporalEpisodeSemanticGapBF143:
    """BF-143: Temporal episodes must contain temporal markers for semantic retrieval."""

    def test_all_episodes_contain_watch_prefix(self):
        """Every temporal episode must include 'first watch' or 'second watch' in content."""
        from probos.cognitive.memory_probes import _TEMPORAL_EPISODES

        for ep in _TEMPORAL_EPISODES:
            content_lower = ep["content"].lower()
            watch = ep["watch"]
            if watch == "first_watch":
                assert "first watch" in content_lower, (
                    f"First-watch episode missing temporal marker: {ep['content']!r}"
                )
            elif watch == "second_watch":
                assert "second watch" in content_lower, (
                    f"Second-watch episode missing temporal marker: {ep['content']!r}"
                )

    def test_temporal_prefix_improves_similarity(self):
        """Episodes with temporal prefix must have higher similarity to probe questions.

        This test validates the root cause fix — without the prefix, cosine
        similarity is ~0.15 (below real memories at ~0.20+).
        """
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
        except ImportError:
            pytest.skip("sentence_transformers not installed")

        model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")

        question = "What happened during first watch?"
        with_prefix = "During first watch: Pool health dropped to 45% during the monitoring sweep"
        without_prefix = "Pool health dropped to 45% during the monitoring sweep"

        embeddings = model.encode([question, with_prefix, without_prefix])
        sim_with = float(np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        ))
        sim_without = float(np.dot(embeddings[0], embeddings[2]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[2])
        ))

        assert sim_with > sim_without, (
            f"Prefix should improve similarity: with={sim_with:.4f}, without={sim_without:.4f}"
        )
        # The prefix should meaningfully improve similarity, not just marginally
        assert sim_with - sim_without > 0.05, (
            f"Improvement too small: delta={sim_with - sim_without:.4f}"
        )

    def test_temporal_prefix_beats_real_memory_baseline(self):
        """Prefixed episodes must have higher similarity than typical real memories.

        Real memories score ~0.20 against first-watch question. Prefixed episodes
        must exceed this to survive top-k competition.
        """
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
        except ImportError:
            pytest.skip("sentence_transformers not installed")

        model = SentenceTransformer("multi-qa-MiniLM-L6-cos-v1")

        question = "What happened during first watch?"
        prefixed = "During first watch: Pool health dropped to 45% during the monitoring sweep"
        # Simulate a typical real memory that competes in recall
        real_memory = "[Ward Room] bridge — Echo: Stasis recovery complete, resuming normal operations"

        embeddings = model.encode([question, prefixed, real_memory])
        sim_prefixed = float(np.dot(embeddings[0], embeddings[1]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
        ))
        sim_real = float(np.dot(embeddings[0], embeddings[2]) / (
            np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[2])
        ))

        assert sim_prefixed > sim_real, (
            f"Prefixed episode must beat real memory: prefixed={sim_prefixed:.4f}, "
            f"real={sim_real:.4f}"
        )
```

### File: `tests/test_ad582_memory_probes.py` (add to existing BF-142 class or new class)

```python
class TestTemporalEpisodeContentBF143:
    """BF-143: Temporal markers in episode content for semantic retrieval."""

    def test_temporal_prefix_words_excluded_from_distinctive_keywords(self):
        """Temporal prefix words must not appear in distinctive keywords.

        'during', 'first', 'second', 'watch' are structural prefix words that
        appear in all episodes — they're not distinctive and would cause
        cross-watch false positives in incorrect_found counting.
        """
        from probos.cognitive.memory_probes import _distinctive_keywords, _TEMPORAL_EPISODES

        temporal_structure_words = {"during", "first", "second", "watch"}

        for ep in _TEMPORAL_EPISODES:
            kws = set(_distinctive_keywords(ep["content"]))
            collision = kws & temporal_structure_words
            assert not collision, (
                f"Temporal structure words in keywords for '{ep['content'][:50]}...': {collision}. "
                "These words appear across watches and cause cross-watch false positives."
            )

    def test_cross_watch_keywords_still_distinct_with_prefix(self):
        """BF-142 cross-watch keyword test must still pass with temporal prefixes.

        Adding temporal prefixes must not introduce new cross-watch keyword
        collisions beyond the prefix words themselves (which are filtered).
        """
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
            "BF-142 distinctiveness requirement still applies with BF-143 prefixes."
        )

    def test_ward_room_framed_content_contains_temporal_marker(self):
        """The actual embedded text (Ward Room framed) must contain the temporal marker."""
        from probos.cognitive.memory_probes import _ward_room_content, _TEMPORAL_EPISODES

        for ep in _TEMPORAL_EPISODES:
            framed = _ward_room_content(ep["content"], callsign="TestAgent")
            watch_label = ep["watch"].replace("_", " ")  # "first_watch" → "first watch"
            assert watch_label in framed.lower(), (
                f"Ward Room framed content missing '{watch_label}': {framed!r}"
            )
```

### File: `tests/test_bf139_140_probe_hardening.py` (add to existing BF-142 class)

```python
    # Add to TestTemporalEpisodeDistinctivenessBF142 or create new class:

    def test_temporal_prefix_does_not_affect_faithfulness_direction(self):
        """Adding temporal prefix should not reduce faithfulness scoring.

        The prefix words ('During', 'first', 'watch') are common words that
        should have neutral or slightly positive effect on token overlap.
        """
        from probos.cognitive.source_governance import check_faithfulness

        content_with = "During first watch: Pool health dropped to 45%"
        content_without = "Pool health dropped to 45%"
        response = "Pool health was at 45 percent during the monitoring sweep."

        faith_with = check_faithfulness(response_text=response, recalled_memories=[content_with])
        faith_without = check_faithfulness(response_text=response, recalled_memories=[content_without])

        # Prefix should not significantly hurt faithfulness (may slightly help due to 'during')
        assert faith_with.score >= faith_without.score * 0.8, (
            f"Prefix shouldn't significantly reduce faithfulness: "
            f"with={faith_with.score:.3f}, without={faith_without.score:.3f}"
        )
```

## Verification

```bash
# BF-143 tests — unit tests
python -m pytest tests/test_bf139_140_probe_hardening.py -k "BF143" -v
python -m pytest tests/test_ad582_memory_probes.py -k "BF143" -v

# BF-142 regression — ensure existing cross-watch tests still pass
python -m pytest tests/test_ad582_memory_probes.py -k "BF142" -v

# Full probe test regression
python -m pytest tests/test_ad582_memory_probes.py tests/test_ad584_recall_qa_fix.py tests/test_bf139_140_probe_hardening.py -v
```

## Files Modified (Summary)

| File | Change |
|------|--------|
| `src/probos/cognitive/memory_probes.py` | Add "During first/second watch:" prefix to `_TEMPORAL_EPISODES` content; add temporal prefix words to `_distinctive_keywords` exclusion |
| `tests/test_bf139_140_probe_hardening.py` | Add `TestTemporalEpisodeSemanticGapBF143` (3 tests) + faithfulness prefix test (1 test) |
| `tests/test_ad582_memory_probes.py` | Add `TestTemporalEpisodeContentBF143` (3 tests) |

**1 source file modified, 2 test files modified, ~7 tests added.**

## What This Does NOT Fix

- **Second probe question semantic gap:** "What was discussed most recently?" is a recency question, not a temporal-watch question. Real memories about recent events (metacognitive research: 0.41 similarity) will always beat seeded episodes from 4 hours ago. This question may need separate attention — either (a) seeded episodes should be timestamped more recently than real memories, or (b) the question should be watch-specific ("What happened during second watch?"). This is deferred — the first question fix alone should bring scores above threshold for most agents.
- **Top-k competition from high-volume agents:** Agents like Pathologist (467 episodes) have more real memories competing for top-k slots. The temporal prefix improves similarity but doesn't guarantee retrieval when there are hundreds of competing memories. The `recall_weighted()` over-fetch (k*3 from ChromaDB) helps but has limits.
- **Fundamental limits of keyword-based wrong-watch detection:** BF-142's vocabulary fix helps, but keyword matching for `incorrect_found` remains fragile. See BF-142 "What This Does NOT Fix" for discussion of LLM-based detection as future improvement.
