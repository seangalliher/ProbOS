# AD-584d: Enriched Embedding Document — Reflection + Question Seeding

**Issue:** TBD (create issue after review)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-584c (scoring rebalance — complete), AD-605 (anchor-enriched document — complete)
**Files:** `src/probos/cognitive/episodic.py`, `tests/test_ad584d_enriched_embedding.py` (NEW)

## Problem

The ChromaDB embedding document (`_prepare_document()` at line 1496 of `episodic.py`) embeds only anchor metadata + `user_input`:

```python
# Current _prepare_document (line 1504-1515):
parts: list[str] = []
if episode.anchors:
    if episode.anchors.department:
        parts.append(f"[{episode.anchors.department}]")
    # ... other anchor fields ...
parts.append(episode.user_input or "")
return " ".join(parts)
```

Meanwhile, the FTS5 index (line 866) already indexes `user_input + reflection`:

```python
fts_content = (episode.user_input or "") + " " + (episode.reflection or "")
```

This creates a retrieval asymmetry: FTS5 keyword search finds episodes by reflection content, but semantic (embedding) search does not. An episode with a rich reflection like "This routing failure was caused by a misconfigured Hebbian weight — the trust cascade dampened too aggressively" is invisible to semantic recall queries about "trust cascade" or "Hebbian routing failure" unless those exact words also appear in `user_input`.

**Root cause:** Embedding was designed before reflection was reliably populated. AD-584d aligns the embedding with FTS5 and adds question seeding for elaborative encoding.

## Design

Two changes to `_prepare_document()`:

1. **Add reflection to embedding document** — Append `episode.reflection` after `user_input` in the embedding text. This aligns ChromaDB embedding with FTS5 indexing.

2. **Question seeding** — Generate 2-3 heuristic questions the episode could answer and append them to the document. This bridges the Q→A gap: when a crew agent recalls "What caused the routing failure?", the episode's question seed "What caused this routing failure?" creates a direct semantic match. This is elaborative encoding (Craik & Tulving, 1975) — deeper processing at encoding time improves retrieval.

**Question generation is heuristic, not LLM-based.** No LLM call at store time. Questions are templated from the episode's structural metadata:

- Intent-based: `"What happened when {intent_type} was executed?"` (if dag_summary has intent)
- Outcome-based: `"What was the outcome of {first_outcome_result}?"` (if outcomes exist, references specific result)
- Department-based: `"What did {department} observe?"` (if anchors.department set, only when no intent question)

Reflection content is NOT templated into questions — the reflection text itself is already in the embedding (Section 1), and templating it produces grammatically broken questions that hurt embedding quality. These are appended as a `[Questions: ...]` suffix on the embedding document.

## What This Does NOT Change

- `Episode` dataclass — no new fields
- FTS5 index content (line 866) — already indexes reflection, no change needed
- `_episode_to_metadata()` — unchanged
- ChromaDB collection schema — unchanged (documents are just strings)
- `recall()`, `recall_for_agent()`, `recall_weighted()` — query side unchanged
- Importance scoring (`compute_importance()`) — unchanged
- Existing stored episodes — NOT re-embedded (migration not in scope)

---

## Section 1: Enrich `_prepare_document()` with reflection

**File:** `src/probos/cognitive/episodic.py`

Replace the current `_prepare_document()` method (lines 1496–1515):

Current:
```python
    @staticmethod
    def _prepare_document(episode: "Episode") -> str:
        """AD-605: Build enriched document text for ChromaDB embedding.

        Concatenates anchor metadata into the document text so the embedding
        captures structural context (department, channel, watch_section) in
        addition to raw content. Improves semantic separation between episodes
        from different contexts.
        """
        parts: list[str] = []
        if episode.anchors:
            if episode.anchors.department:
                parts.append(f"[{episode.anchors.department}]")
            if episode.anchors.channel:
                parts.append(f"[{episode.anchors.channel}]")
            if episode.anchors.watch_section:
                parts.append(f"[{episode.anchors.watch_section}]")
            if episode.anchors.trigger_type:
                parts.append(f"[{episode.anchors.trigger_type}]")
        parts.append(episode.user_input or "")
        return " ".join(parts)
```

Replace with:
```python
    @staticmethod
    def _prepare_document(episode: "Episode") -> str:
        """AD-584d: Build enriched document text for ChromaDB embedding.

        Concatenates anchor metadata, user_input, reflection, and heuristic
        question seeds into the document text. This aligns the embedding with
        FTS5 (which already indexes user_input + reflection) and adds
        elaborative encoding via question seeding (Craik & Tulving 1975).

        The output is embedding-only — never displayed to users or
        reconstructed back to Episode. Content order (anchors → user_input →
        reflection → questions) ensures structural context survives if the
        embedding model truncates long documents.
        """
        parts: list[str] = []

        # Structural context (AD-605)
        if episode.anchors:
            if episode.anchors.department:
                parts.append(f"[{episode.anchors.department}]")
            if episode.anchors.channel:
                parts.append(f"[{episode.anchors.channel}]")
            if episode.anchors.watch_section:
                parts.append(f"[{episode.anchors.watch_section}]")
            if episode.anchors.trigger_type:
                parts.append(f"[{episode.anchors.trigger_type}]")

        # Core content — user_input + reflection (AD-584d)
        if episode.user_input:
            parts.append(episode.user_input)
        if episode.reflection:
            parts.append(episode.reflection)

        # Question seeds — heuristic elaborative encoding (AD-584d)
        questions = EpisodicMemory._generate_question_seeds(episode)
        if questions:
            parts.append("[Questions: " + " | ".join(questions) + "]")

        return " ".join(parts)
```

---

## Section 2: Add question seed generator

**File:** `src/probos/cognitive/episodic.py`

Add a new static method after `_prepare_document()`:

```python
    @staticmethod
    def _generate_question_seeds(episode: "Episode") -> list[str]:
        """AD-584d: Generate heuristic questions this episode could answer.

        Elaborative encoding — deeper processing at write time improves
        retrieval at recall time. Questions bridge the Q→A gap so that
        query-like recall prompts have direct semantic overlap with the
        stored document.

        Returns 0-3 questions based on available metadata. No LLM call.

        Note: Reflection content is NOT templated into questions — it's
        already in the embedding via Section 1, and templating it produces
        grammatically broken questions that hurt embedding quality.
        """
        questions: list[str] = []

        # Intent-based question
        intent_type = ""
        if episode.dag_summary:
            intent_type = episode.dag_summary.get("intent", "") or episode.dag_summary.get("intent_type", "")
        if intent_type:
            questions.append(f"What happened when {intent_type} was executed?")

        # Outcome-based question (references specific result, not intent)
        if episode.outcomes:
            first_result = episode.outcomes[0].get("result", "")
            if first_result:
                questions.append(f"What was the outcome of {first_result}?")

        # Department-based question (if no intent question generated)
        if not intent_type and episode.anchors and episode.anchors.department:
            questions.append(f"What did {episode.anchors.department} observe?")

        return questions[:3]  # Cap at 3
```

---

## Section 3: Tests

**File:** `tests/test_ad584d_enriched_embedding.py` (NEW)

```python
"""Tests for AD-584d: Enriched embedding document with reflection + question seeding."""

from __future__ import annotations

import pytest
from probos.types import Episode, AnchorFrame
from probos.cognitive.episodic import EpisodicMemory


# --- _prepare_document tests ---

class TestPrepareDocument:

    def test_includes_user_input(self):
        """Embedding document includes user_input."""
        ep = Episode(user_input="test query")
        doc = EpisodicMemory._prepare_document(ep)
        assert "test query" in doc

    def test_includes_reflection(self):
        """AD-584d: Embedding document now includes reflection."""
        ep = Episode(user_input="test query", reflection="This was caused by a routing failure.")
        doc = EpisodicMemory._prepare_document(ep)
        assert "routing failure" in doc

    def test_includes_anchors(self):
        """Anchor metadata still included (AD-605 preserved)."""
        ep = Episode(
            user_input="test",
            anchors=AnchorFrame(department="engineering", channel="eng-ops"),
        )
        doc = EpisodicMemory._prepare_document(ep)
        assert "[engineering]" in doc
        assert "[eng-ops]" in doc

    def test_no_reflection_still_works(self):
        """Episodes without reflection produce valid documents."""
        ep = Episode(user_input="test query", reflection=None)
        doc = EpisodicMemory._prepare_document(ep)
        assert "test query" in doc
        assert "None" not in doc

    def test_empty_episode(self):
        """Totally empty episode produces non-empty document (question seeds may apply)."""
        ep = Episode()
        doc = EpisodicMemory._prepare_document(ep)
        # Should not crash
        assert isinstance(doc, str)

    def test_alignment_with_fts5(self):
        """AD-584d: Embedding document contains same content as FTS5 index."""
        ep = Episode(user_input="hello world", reflection="this was important")
        doc = EpisodicMemory._prepare_document(ep)
        fts_content = (ep.user_input or "") + " " + (ep.reflection or "")
        # Both user_input and reflection should be in the embedding doc
        assert "hello world" in doc
        assert "this was important" in doc


# --- Question seed tests ---

class TestQuestionSeeds:

    def test_intent_based_question(self):
        """Intent from dag_summary produces a question."""
        ep = Episode(dag_summary={"intent": "code_review"})
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert any("code_review" in q for q in questions)

    def test_outcome_based_question(self):
        """Outcomes produce a result-specific question."""
        ep = Episode(
            dag_summary={"intent": "build"},
            outcomes=[{"result": "compilation_failed"}],
        )
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert any("compilation_failed" in q for q in questions)

    def test_department_based_question(self):
        """Department question generated when no intent available."""
        ep = Episode(anchors=AnchorFrame(department="medical"))
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert any("medical" in q for q in questions)

    def test_no_department_question_when_intent_exists(self):
        """Department question NOT generated when intent question exists."""
        ep = Episode(
            dag_summary={"intent": "code_review_xyz"},
            anchors=AnchorFrame(department="medical"),
        )
        questions = EpisodicMemory._generate_question_seeds(ep)
        # Should have intent question, not department question
        assert any("code_review_xyz" in q for q in questions)
        assert not any("medical" in q for q in questions)

    def test_max_three_questions(self):
        """Question seeds capped at 3."""
        ep = Episode(
            dag_summary={"intent": "build"},
            outcomes=[{"result": "ok"}],
            anchors=AnchorFrame(department="engineering"),
        )
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert len(questions) <= 3

    def test_empty_episode_no_questions(self):
        """Empty episode produces no questions."""
        ep = Episode()
        questions = EpisodicMemory._generate_question_seeds(ep)
        assert questions == []

    def test_reflection_not_templated_into_question(self):
        """AD-584d: Reflection is NOT used for question generation (grammar issues)."""
        ep = Episode(reflection="The trust cascade dampened too aggressively. This needs tuning.")
        questions = EpisodicMemory._generate_question_seeds(ep)
        # No questions should be generated from reflection alone
        assert questions == []

    def test_questions_in_document(self):
        """Question seeds appear in the prepared document."""
        ep = Episode(
            user_input="test",
            dag_summary={"intent": "analyze"},
        )
        doc = EpisodicMemory._prepare_document(ep)
        assert "[Questions:" in doc
        assert "analyze" in doc

    def test_no_questions_no_tag(self):
        """No [Questions:] tag when no questions generated."""
        ep = Episode(user_input="test")
        doc = EpisodicMemory._prepare_document(ep)
        assert "[Questions:" not in doc
```

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad584d_enriched_embedding.py -v

# Existing episodic memory tests (must not break)
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "episodic" -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

**Existing test impact:** `tests/test_ad605_enhanced_embedding.py` has exact-match assertions on `_prepare_document()` output. Tests 1–3 and 5 use `_make_episode()` which doesn't set `reflection` or `dag_summary`, so no question seeds fire and those tests pass unchanged. **Test 4 (`test_empty_user_input`, line 94) will break:** the current code does `parts.append(episode.user_input or "")` which appends an empty string (producing a trailing space), but the new code does `if episode.user_input: parts.append(episode.user_input)` which skips it. Fix: update the assertion from `assert doc == "[science] [ward_room] [first] [direct_message] "` to `assert doc == "[science] [ward_room] [first] [direct_message]"` (no trailing space).

---

## Tracking

### PROGRESS.md
Add line:
```
AD-584d CLOSED. Enriched embedding document — _prepare_document() now includes reflection alongside user_input (aligning ChromaDB with FTS5) plus heuristic question seeding for elaborative encoding. Intent, outcome, and department question templates. Reflection NOT templated into questions (grammar issues). No LLM call. 15 new tests. Completes AD-584 recall improvement wave.
```

### DECISIONS.md
Add entry:
```
**AD-584d: Elaborative encoding via enriched embeddings.** ChromaDB embedding document now includes reflection text (aligning with FTS5 which already indexed it) and 2-3 heuristic question seeds per episode. Questions are template-based (no LLM call) using intent_type, outcome results, and department. Reflection is NOT templated into questions — it's already in the embedding text, and templating produces grammatically broken questions that hurt embedding quality. This bridges the Q→A retrieval gap: when agents recall with question-like queries, the question seeds create direct semantic overlap with stored episodes. Note: embedding now includes agent reflection content — recall queries may match on agent meta-commentary, not just observed events. This aligns with FTS5 behavior (which already indexed reflections). Research basis: Craik & Tulving (1975) depth of processing. Existing episodes are NOT retroactively re-embedded — new enrichment applies to episodes stored after deployment.
```

### docs/development/roadmap.md
Update AD-584d status from `planned` to `complete` in the sub-AD list.
