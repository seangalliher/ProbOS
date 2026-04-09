# AD-568e: Faithfulness Verification — Post-Decision Source Fidelity Check

## Classification

| Field | Value |
|-------|-------|
| **AD** | 568e |
| **Title** | Faithfulness Verification — Post-Decision Source Fidelity Check |
| **Type** | Cognitive Architecture |
| **Priority** | Medium |
| **Risk** | Low — additive checks, no existing behavior modified |
| **Estimated scope** | 4 phases, ~25 tests |
| **Depends on** | AD-568a (retrieval strategy) ✅, AD-568b (budget scaling) ✅, AD-568c (source framing) ✅, AD-568d (source attribution + confabulation rate pipeline) ✅, AD-541 (verified/unverified episode tags) ✅ |

## Problem

Agents recall episodic memories (verified and tagged with source attribution), generate a response via the LLM, then commit that response — but **nothing checks whether the response is actually faithful to the evidence the agent was given**. An agent might have 5 verified episodic memories about a topic and still generate a response that contradicts or ignores them (hallucination/confabulation).

The source governance pipeline provides:
- **Input side**: AD-541 cross-checks episodes against EventLog (verified/unverified tags). AD-568a routes retrieval strategy. AD-568b scales budget. AD-568c frames source authority.
- **Attribution**: AD-568d tracks which knowledge source the agent drew from and computes confabulation rate via Dream Step 14.
- **Output side**: **Nothing.** The confabulation rate in AD-568d is an aggregate statistical measure from dream consolidation — it doesn't catch individual unfaithful responses in real-time.

Self-RAG (Asai et al., 2023) defines three reflection decisions:
1. **Retrieve?** → AD-568a `classify_retrieval_strategy()` ✅
2. **Relevant?** → AD-567b `recall_weighted()` composite scoring ✅
3. **Faithful?** → **This AD**

### Concrete codebase gaps

1. **No post-decision faithfulness check.** In `handle_intent()` (cognitive_agent.py ~line 1431), `decide()` returns a decision dict, then `act()` commits it immediately. There is no gate between these steps that verifies the response aligns with recalled evidence.

2. **Confabulation rate is retrospective only.** Dream Step 14 (`_step_14_source_attribution`, dreaming.py ~line 1838) computes aggregate confabulation rate across all recent episodes — it cannot flag an individual response as unfaithful at the time it's generated.

3. **No faithfulness signal in episode metadata.** When `_store_action_episode()` stores the episode (~line 2697), there's no `faithfulness_score` or `grounded` field. The episode has `source_attribution` (AD-568d) but not whether the response honored that attribution.

4. **Counselor has no per-response fidelity data.** `CognitiveProfile.confabulation_rate` (~line 149 counselor.py) is updated only during dream consolidation, not per cognitive cycle. Persistent unfaithfulness in a single session isn't visible until the next dream.

## Prior Work Absorbed

| Source | What's absorbed |
|--------|----------------|
| **Self-RAG** (Asai et al., 2023) | ISSUP faithfulness token — lightweight binary check "is the response supported by the retrieved evidence?" Not their full retrieve/critique/refine loop (too expensive for ProbOS's single-shot cycles). |
| **CRAG** (Yan et al., 2024) | Retrieval confidence triggering corrective action — maps to threshold-based logging, not full re-retrieval. |
| **AD-541 verified/unverified tags** | Ground truth for comparison — faithful responses should cite verified memories, not fabricate unsupported claims. |
| **AD-567f social verification** | Cascade confabulation detection — AD-568e is the individual-agent complement. 567f catches confabulation spreading between agents; 568e catches it at the source. |
| **AD-566b ConfabricationProbe** | External measurement of confabulation resistance — AD-568e provides the runtime mechanism that produces the data the probe measures. |

## What This Does NOT Do

- **Does NOT re-generate responses.** This is a check-and-tag, not a correction loop. If a response is unfaithful, it's flagged in episode metadata and the confabulation rate is updated — the agent isn't asked to try again. (Correction loops are a future AD.)
- **Does NOT use a second LLM call.** Faithfulness is assessed heuristically by comparing the response against recalled memories — no additional token cost. This keeps the check lightweight enough to run on every cognitive cycle.
- **Does NOT block the intent pipeline.** Faithfulness scoring is fire-and-forget. A low score logs a warning and updates metrics but doesn't prevent the response from being delivered.
- **Does NOT replace Dream Step 14.** Dream consolidation remains the aggregate trend tracker. AD-568e feeds per-response data into the same confabulation rate that Dream Step 14 then consolidates.

## Engineering Principles Applied

| Principle | Application |
|-----------|-------------|
| **Single Responsibility** | `FaithfulnessChecker` is a standalone module — does not modify `decide()`, `act()`, or the retrieval pipeline |
| **Open/Closed** | Extends `handle_intent()` with a post-decision check inserted between `decide()` and `act()`. No existing method signatures change. |
| **Liskov Substitution** | `faithfulness_score` defaults to `None` in episode metadata — existing episodes without the field remain valid |
| **Dependency Inversion** | `FaithfulnessChecker` depends on abstract inputs (response text + memory list), not on CognitiveAgent internals |
| **Law of Demeter** | Checker receives pre-extracted data (response string, memory texts, source attribution), doesn't reach into agent internals |
| **Fail Fast / Log-and-Degrade** | All faithfulness checks wrapped in try/except with log-and-degrade. If checker fails, response proceeds unscored. |
| **Cloud-Ready Storage** | No new storage — writes to existing episode metadata dict and existing CognitiveProfile fields |
| **Westworld Principle** | Agents can see their own faithfulness scores via source awareness tag (AD-568d already provides the ambient context) |

## Prerequisites

Before building, verify these exist in the live codebase:

```bash
# AD-568d source attribution infrastructure
grep -n "class KnowledgeSource" src/probos/cognitive/source_governance.py
grep -n "class SourceAttribution" src/probos/cognitive/source_governance.py
grep -n "compute_source_attribution" src/probos/cognitive/source_governance.py

# Episode metadata source_attribution field (AD-568d)
grep -n "source_attribution" src/probos/cognitive/cognitive_agent.py

# Confabulation rate on CognitiveProfile
grep -n "confabulation_rate" src/probos/cognitive/counselor.py

# Dream Step 14
grep -n "step_14_source_attribution" src/probos/cognitive/dreaming.py

# Verified/unverified tags on recalled memories (AD-541)
grep -n "verified" src/probos/cognitive/cognitive_agent.py

# handle_intent flow: decide → act
grep -n "await self.decide" src/probos/cognitive/cognitive_agent.py
grep -n "await self.act" src/probos/cognitive/cognitive_agent.py
```

---

## Phase 1: FaithfulnessChecker Module

**File:** `src/probos/cognitive/source_governance.py` (extend existing module)

### What It Does

Add a `FaithfulnessResult` dataclass and a `check_faithfulness()` pure function that heuristically scores whether an LLM response is faithful to the recalled episodic memories.

### Implementation

**Step 1.1:** Add `FaithfulnessResult` frozen dataclass after the `SourceAttribution` class (~after line 320):

```python
@dataclass(frozen=True)
class FaithfulnessResult:
    """AD-568e: Post-decision faithfulness assessment.

    Heuristic check: does the response align with recalled evidence?
    Not a second LLM call — keyword overlap + claim density scoring.
    """
    score: float  # 0.0 (no evidence alignment) to 1.0 (fully grounded)
    evidence_overlap: float  # Fraction of response tokens found in evidence
    unsupported_claim_ratio: float  # Fraction of assertion-like sentences not backed by evidence
    evidence_count: int  # Number of recalled memories available
    grounded: bool  # score >= threshold (default 0.5)
    detail: str  # Human-readable summary
```

**Step 1.2:** Add `check_faithfulness()` pure function after the dataclass:

```python
def check_faithfulness(
    *,
    response_text: str,
    recalled_memories: list[str],
    source_attribution: SourceAttribution | None = None,
    threshold: float = 0.5,
) -> FaithfulnessResult:
    """AD-568e: Heuristic faithfulness scoring.

    Compares the LLM response against recalled episodic memories using:
    1. Token overlap — what fraction of response content words appear in evidence
    2. Unsupported claim detection — sentences with assertion markers
       (numbers, proper nouns, specific claims) not overlapping with evidence

    Pure function, no LLM call, no I/O. Designed to run on every cognitive
    cycle without measurable latency impact.

    Returns FaithfulnessResult with grounded=True if score >= threshold.
    """
```

**IMPORTANT:** The implementation should:
- Tokenize by splitting on whitespace and normalizing to lowercase
- Build an evidence token set from all recalled memories combined
- Score `evidence_overlap` as `len(response_tokens & evidence_tokens) / len(response_tokens)` (guarding division by zero)
- Detect "assertion sentences" using simple heuristics: sentences containing digits, ALL_CAPS words (>2 chars), or quoted strings
- Score `unsupported_claim_ratio` as fraction of assertion sentences whose tokens have <30% overlap with evidence tokens
- Compute final `score` as weighted combination: `evidence_overlap * 0.6 + (1.0 - unsupported_claim_ratio) * 0.4`
- If `evidence_count == 0` (no memories recalled), return score=1.0, grounded=True, detail="No episodic evidence to verify against — parametric response" (cannot be unfaithful if there was nothing to be faithful to)
- If `source_attribution` and `source_attribution.primary_source == KnowledgeSource.PARAMETRIC`, also return score=1.0 (parametric responses are self-contained)
- Return `grounded = score >= threshold`

**Step 1.3:** Add `_ASSERTION_PATTERN` compiled regex at module level for assertion detection:

```python
import re as _re

# AD-568e: Heuristic assertion markers — sentences likely making specific claims
_ASSERTION_PATTERN = _re.compile(
    r'\d+\.?\d*'  # Numbers (dates, counts, percentages)
    r'|[A-Z]{3,}'  # ALL_CAPS words (acronyms, names)
    r'|"[^"]*"'  # Quoted strings
    r"|'[^']*'"  # Single-quoted strings
)
```

---

## Phase 2: Wire Faithfulness Check into handle_intent()

**File:** `src/probos/cognitive/cognitive_agent.py`

### What It Does

Insert a faithfulness check between `decide()` and `act()` in the `handle_intent()` pipeline. The check is fire-and-forget — it scores the response but never blocks it.

### Implementation

**Step 2.1:** Add import at the top of the file (with existing source_governance imports):

```python
from probos.cognitive.source_governance import check_faithfulness, FaithfulnessResult
```

**IMPORTANT:** Check the existing import block for `source_governance` imports (~search for `from probos.cognitive.source_governance import`). Add `check_faithfulness` and `FaithfulnessResult` to the existing import line rather than creating a new one.

**Step 2.2:** Add `_check_response_faithfulness()` method on `CognitiveAgent`:

```python
def _check_response_faithfulness(
    self,
    decision: dict,
    observation: dict,
) -> FaithfulnessResult | None:
    """AD-568e: Post-decision faithfulness check.

    Compares the LLM response against recalled memories that were
    in the observation context. Fire-and-forget — never blocks the
    intent pipeline.

    Returns FaithfulnessResult or None if check cannot be performed.
    """
    try:
        # Extract response text from decision
        response_text = decision.get("llm_output", "") or decision.get("response", "")
        if not response_text:
            return None

        # Extract recalled memories from observation
        raw_memories = observation.get("memories", [])
        if not raw_memories:
            # No memories were recalled — parametric response, faithfulness N/A
            return FaithfulnessResult(
                score=1.0,
                evidence_overlap=0.0,
                unsupported_claim_ratio=0.0,
                evidence_count=0,
                grounded=True,
                detail="No episodic evidence to verify against — parametric response",
            )

        # Build memory text list
        memory_texts = []
        for mem in raw_memories:
            if isinstance(mem, dict):
                text = mem.get("user_input", "") or mem.get("content", "")
                if text:
                    memory_texts.append(text)
            elif isinstance(mem, str):
                memory_texts.append(mem)

        # Get source attribution from observation (AD-568d)
        source_attr = observation.get("_source_attribution_obj")

        return check_faithfulness(
            response_text=response_text,
            recalled_memories=memory_texts,
            source_attribution=source_attr,
        )

    except Exception:
        logger.debug("AD-568e: Faithfulness check failed", exc_info=True)
        return None
```

**Step 2.3:** Insert the faithfulness check in `handle_intent()` between `decide()` and `act()`. Find the line:

```python
        decision = await self.decide(observation)
        decision["intent"] = intent.intent  # AD-398: propagate intent name to act()
```

After this block (and before the compound procedure dispatch), insert:

```python
        # AD-568e: Post-decision faithfulness verification
        _faithfulness = self._check_response_faithfulness(decision, observation)
        if _faithfulness is not None:
            observation["_faithfulness"] = _faithfulness
            if not _faithfulness.grounded:
                logger.info(
                    "AD-568e: Unfaithful response detected for %s (score=%.2f, overlap=%.2f, claims=%.2f)",
                    self.callsign or self.agent_type,
                    _faithfulness.score,
                    _faithfulness.evidence_overlap,
                    _faithfulness.unsupported_claim_ratio,
                )
```

**IMPORTANT:** Place this BEFORE the compound procedure dispatch block (`if decision.get("compound")`), because procedural replay responses are pre-validated and should be checked too.

**Step 2.4:** Store the `SourceAttribution` object (not just the dict) in the observation during source attribution computation (~line 2634). Find where `observation["_source_attribution"]` is set and add:

```python
        observation["_source_attribution_obj"] = _attribution  # AD-568e: typed object for faithfulness checker
```

**IMPORTANT:** The existing `observation["_source_attribution"]` stores a dict (via `._asdict()` or similar). The `_source_attribution_obj` key stores the actual `SourceAttribution` dataclass instance for type-safe access in the faithfulness checker. Check the actual code to see how `_source_attribution` is currently set — preserve that, add the `_obj` variant alongside it.

---

## Phase 3: Faithfulness Metadata in Episodes + Counselor Integration

**File:** `src/probos/cognitive/cognitive_agent.py` (episode storage), `src/probos/cognitive/counselor.py` (profile update)

### What It Does

1. Store faithfulness score in episode metadata when storing action episodes
2. Update Counselor's confabulation rate with per-response data (not just dream-consolidated aggregates)

### Implementation

**Step 3.1:** In `_store_action_episode()` (~line 2697), find where episode metadata is assembled. Add faithfulness data if available:

```python
        # AD-568e: Faithfulness metadata
        _faith = observation.get("_faithfulness")
        if _faith is not None:
            # Store as simple dict for ChromaDB serialization
            metadata["faithfulness_score"] = _faith.score
            metadata["faithfulness_grounded"] = _faith.grounded
```

**IMPORTANT:** Examine how `_store_action_episode()` currently builds the episode. The `metadata` variable may be named differently — it might be built inline in the `Episode()` constructor call or assembled in a separate dict. Adapt accordingly. The key requirement is that `faithfulness_score` and `faithfulness_grounded` end up in the episode's metadata (likely in `dag_summary` or as top-level Episode fields — check how `source_attribution` from AD-568d is stored and follow the same pattern).

**Step 3.2:** In `counselor.py`, add a `record_faithfulness_event()` method on the Counselor agent class:

```python
    async def record_faithfulness_event(
        self,
        agent_id: str,
        *,
        faithfulness_score: float,
        grounded: bool,
    ) -> None:
        """AD-568e: Per-response faithfulness feedback into confabulation rate.

        Updates confabulation rate with real-time signal (not just dream-consolidated).
        Unfaithful responses (grounded=False) increase confabulation rate.
        Faithful responses slowly decrease it.

        Uses EMA with alpha=0.1 (slower than Dream Step 14's alpha=0.3) to
        avoid overreacting to individual responses.
        """
        try:
            profile = self.get_or_create_profile(agent_id)

            # EMA update: unfaithful = 1.0, faithful = 0.0
            signal = 0.0 if grounded else 1.0
            alpha = 0.1  # Slower than dream EMA (0.3) — individual responses are noisy
            new_rate = alpha * signal + (1.0 - alpha) * profile.confabulation_rate

            profile.confabulation_rate = round(new_rate, 4)
            await self._profile_store.save_profile(profile)

            # Alert if crossing threshold
            if new_rate >= self._confabulation_alert_threshold and grounded is False:
                logger.warning(
                    "AD-568e: Agent %s confabulation rate %.3f exceeds threshold %.2f",
                    agent_id, new_rate, self._confabulation_alert_threshold,
                )

        except Exception:
            logger.debug("AD-568e: record_faithfulness_event failed", exc_info=True)
```

**Step 3.3:** Wire the Counselor call from `handle_intent()`. After the faithfulness check block added in Phase 2, add:

```python
        # AD-568e: Feed faithfulness signal to Counselor (fire-and-forget)
        if _faithfulness is not None:
            try:
                _rt = getattr(self, '_runtime', None)
                if _rt:
                    _counselors = _rt.registry.get_by_pool("counselor")
                    if _counselors:
                        _counselor = _counselors[0]
                        if hasattr(_counselor, 'record_faithfulness_event'):
                            await _counselor.record_faithfulness_event(
                                self.id,
                                faithfulness_score=_faithfulness.score,
                                grounded=_faithfulness.grounded,
                            )
            except Exception:
                logger.debug("AD-568e: Counselor faithfulness update failed", exc_info=True)
```

**IMPORTANT:** Check how the existing AD-568d confabulation rate lookup accesses the Counselor (cognitive_agent.py ~line 2487-2499). Follow the same pattern for consistency. The `_rt.registry.get_by_pool("counselor")` pattern should match what's there.

---

## Phase 4: Dream Step 14 Enhancement — Faithfulness Aggregation

**File:** `src/probos/cognitive/dreaming.py`

### What It Does

Extend Dream Step 14 (`_step_14_source_attribution`) to also aggregate per-episode faithfulness scores alongside source attribution. This provides the dream-level view of faithfulness trends.

### Implementation

**Step 4.1:** In `_step_14_source_attribution()` (~line 1838), find where episode metadata is extracted (the loop over episodes). Add faithfulness score extraction alongside source attribution extraction:

```python
            # AD-568e: Extract faithfulness score from episode metadata
            _faith_score = None
            if isinstance(_meta, dict):
                _faith_score = _meta.get("faithfulness_score")
            if _faith_score is not None:
                _faithfulness_scores.append(float(_faith_score))
```

**IMPORTANT:** Initialize `_faithfulness_scores: list[float] = []` before the episode loop.

**Step 4.2:** After the source distribution computation, add faithfulness aggregation:

```python
        # AD-568e: Aggregate faithfulness scores
        _mean_faithfulness = 0.0
        _unfaithful_count = 0
        if _faithfulness_scores:
            _mean_faithfulness = sum(_faithfulness_scores) / len(_faithfulness_scores)
            _unfaithful_count = sum(1 for s in _faithfulness_scores if s < 0.5)
```

**Step 4.3:** Include faithfulness data in the returned dict. Find where the result dict is assembled (the `return` statement) and add:

```python
            "mean_faithfulness_score": round(_mean_faithfulness, 4),
            "unfaithful_episodes": _unfaithful_count,
            "faithfulness_episodes_assessed": len(_faithfulness_scores),
```

**Step 4.4:** Add faithfulness fields to the `DreamReport` dataclass in `types.py`:

```python
    # AD-568e: Faithfulness verification
    mean_faithfulness_score: float | None = None
    unfaithful_episodes: int = 0
```

**Step 4.5:** In the `dream_cycle()` method, where `_source_attr_result` is unpacked into the `DreamReport`, add the faithfulness fields:

```python
            mean_faithfulness_score=_source_attr_result.get("mean_faithfulness_score"),
            unfaithful_episodes=_source_attr_result.get("unfaithful_episodes", 0),
```

**IMPORTANT:** Find where `dream_cycle()` constructs the `DreamReport` and verify the exact kwarg pattern. The existing `source_attribution` field is already set from `_source_attr_result` — follow the same pattern.

---

## Tests

**File:** `tests/test_ad568e_faithfulness_verification.py`

### Test Class 1: TestFaithfulnessChecker (8 tests)

Tests the pure `check_faithfulness()` function.

```python
class TestFaithfulnessChecker:
    """AD-568e: Heuristic faithfulness scoring."""

    def test_faithful_response_high_overlap(self):
        """Response that closely mirrors recalled evidence scores high."""
        # Response uses words from memories → high evidence_overlap, grounded=True

    def test_unfaithful_response_no_overlap(self):
        """Response with fabricated content not in evidence scores low."""
        # Response contains specific claims not in any memory → grounded=False

    def test_no_memories_returns_parametric(self):
        """Empty memory list → score=1.0, grounded=True (parametric response)."""

    def test_parametric_source_attribution_returns_grounded(self):
        """Source attribution primary_source=PARAMETRIC → score=1.0 regardless."""

    def test_assertion_detection_numbers(self):
        """Sentences with specific numbers flagged as assertions."""

    def test_assertion_detection_quotes(self):
        """Sentences with quoted strings flagged as assertions."""

    def test_threshold_boundary(self):
        """Score exactly at threshold → grounded=True. Below → grounded=False."""

    def test_empty_response_returns_none_gracefully(self):
        """Empty response text → check returns meaningful default (not crash)."""
```

### Test Class 2: TestHandleIntentFaithfulness (5 tests)

Tests the integration in `handle_intent()`.

```python
class TestHandleIntentFaithfulness:
    """AD-568e: Faithfulness check wired into cognitive pipeline."""

    async def test_faithfulness_stored_in_observation(self):
        """After decide(), observation contains _faithfulness key."""

    async def test_unfaithful_response_logs_warning(self):
        """Unfaithful response (grounded=False) produces INFO log."""

    async def test_faithfulness_check_failure_degrades_gracefully(self):
        """If check_faithfulness raises, handle_intent continues normally."""

    async def test_procedural_replay_also_checked(self):
        """Compound procedure responses are also faithfulness-checked."""

    async def test_no_memories_skips_gracefully(self):
        """When observation has no memories, faithfulness check returns parametric result."""
```

### Test Class 3: TestCounselorFaithfulnessIntegration (5 tests)

Tests `record_faithfulness_event()` on the Counselor.

```python
class TestCounselorFaithfulnessIntegration:
    """AD-568e: Per-response faithfulness feedback to Counselor."""

    async def test_faithful_response_decreases_confabulation_rate(self):
        """grounded=True signal with alpha=0.1 EMA decreases rate."""

    async def test_unfaithful_response_increases_confabulation_rate(self):
        """grounded=False signal with alpha=0.1 EMA increases rate."""

    async def test_ema_alpha_slower_than_dream(self):
        """Per-response alpha=0.1 is slower than Dream Step 14 alpha=0.3."""

    async def test_threshold_crossing_logs_warning(self):
        """Rate crossing confabulation_alert_threshold (0.3) logs warning."""

    async def test_record_failure_degrades_gracefully(self):
        """If profile_store.save_profile raises, no propagation."""
```

### Test Class 4: TestDreamStep14Faithfulness (5 tests)

Tests the faithfulness aggregation in Dream Step 14.

```python
class TestDreamStep14Faithfulness:
    """AD-568e: Dream Step 14 faithfulness aggregation."""

    async def test_faithfulness_scores_extracted_from_episodes(self):
        """Episodes with faithfulness_score metadata are aggregated."""

    async def test_mean_faithfulness_computed(self):
        """Mean of all faithfulness scores across episodes."""

    async def test_unfaithful_count_threshold(self):
        """Episodes with score < 0.5 counted as unfaithful."""

    async def test_no_faithfulness_data_zero_defaults(self):
        """Episodes without faithfulness metadata → 0.0 mean, 0 unfaithful."""

    async def test_dream_report_includes_faithfulness_fields(self):
        """DreamReport has mean_faithfulness_score and unfaithful_episodes."""
```

### Test Class 5: TestFaithfulnessResultDataclass (2 tests)

```python
class TestFaithfulnessResultDataclass:
    """AD-568e: FaithfulnessResult frozen dataclass."""

    def test_frozen_immutable(self):
        """FaithfulnessResult is frozen — cannot modify fields."""

    def test_all_fields_present(self):
        """All 6 fields: score, evidence_overlap, unsupported_claim_ratio, evidence_count, grounded, detail."""
```

**Total: 25 tests across 5 classes.**

---

## Regression Test Targets

Run after all phases complete:

```bash
# AD-568e unit tests
pytest tests/test_ad568e_faithfulness_verification.py -v

# AD-568d tests (must not regress — shared source_governance.py)
pytest tests/test_ad568d_cognitive_proprioception.py -v

# Source governance module
pytest tests/ -k "source_governance or source_framing or retrieval_strategy" -v

# Cognitive agent pipeline
pytest tests/ -k "cognitive_agent or handle_intent" -v

# Dream cycle
pytest tests/ -k "dream" -v

# Counselor
pytest tests/ -k "counselor" -v

# Full suite
pytest tests/ -x --timeout=120
```

---

## Build Verification Checklist

### Before building — verify prerequisites exist:

- [ ] `KnowledgeSource` enum exists in `source_governance.py`
- [ ] `SourceAttribution` dataclass exists in `source_governance.py`
- [ ] `compute_source_attribution()` function exists in `source_governance.py`
- [ ] `observation["_source_attribution"]` set in cognitive_agent.py (AD-568d)
- [ ] `CognitiveProfile.confabulation_rate` field exists in counselor.py
- [ ] `update_source_metrics()` method exists on Counselor
- [ ] `_step_14_source_attribution()` exists in dreaming.py
- [ ] `handle_intent()` has `decide()` → `act()` flow (~lines 1431/1479)
- [ ] `_store_action_episode()` exists (~line 2697)
- [ ] Episode `source` field and `verified` tag exist (AD-541)

### After building — verify:

- [ ] `FaithfulnessResult` dataclass is frozen with 6 fields
- [ ] `check_faithfulness()` is a pure function (no I/O, no LLM)
- [ ] `check_faithfulness()` handles edge cases: empty response, no memories, parametric source
- [ ] `_check_response_faithfulness()` is fire-and-forget (try/except, returns None on failure)
- [ ] Faithfulness check is inserted BEFORE compound procedure dispatch in `handle_intent()`
- [ ] `record_faithfulness_event()` uses alpha=0.1 (slower than dream's 0.3)
- [ ] Episode metadata includes `faithfulness_score` and `faithfulness_grounded`
- [ ] `DreamReport` has `mean_faithfulness_score` and `unfaithful_episodes` fields
- [ ] Dream Step 14 extracts and aggregates faithfulness data from episodes
- [ ] All 25 tests pass
- [ ] No regressions in AD-568d, source governance, cognitive agent, dream, counselor tests
- [ ] Full suite green
