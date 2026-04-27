# AD-668: Salience Filter

**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-667 (Named Working Memory Buffers) — not yet implemented; this AD must work standalone
**Unlocks:** AD-670 (Working Memory Metabolism — uses salience scores for decay)

## Files

| File | Action | Est. Lines |
|------|--------|-----------|
| `src/probos/cognitive/salience_filter.py` | **Create** | ~150 |
| `src/probos/config.py` | Modify | ~15 |
| `src/probos/cognitive/agent_working_memory.py` | Modify | ~40 |
| `tests/test_ad668_salience_filter.py` | **Create** | ~250 |

## Problem

Working memory accepts all incoming events with equal priority. Every `record_action`, `record_observation`, `record_event`, and `record_conversation` call appends unconditionally to a ring buffer with FIFO eviction. There is no scoring to determine whether an event is worth promoting into the agent's active situation model vs. accumulating in a low-priority background stream. This means high-salience events (urgent alerts, trusted-agent messages, duty-relevant observations) compete equally with low-salience noise (routine heartbeats, stale events, low-trust chatter).

AD-668 introduces a salience scoring function that gates working memory promotion. Events above a configurable threshold enter the main ring buffers. Events below threshold go to a background stream for potential idle-cycle batch review.

## Scope

**In scope:**
- `SalienceScore` dataclass with total score and per-component breakdown
- `SalienceFilter` class with a `score()` method computing weighted salience
- Five scoring dimensions: relevance, recency, novelty, urgency, social
- Promotion gate: score >= threshold -> main buffer; score < threshold -> background stream
- Background stream: capped deque for sub-threshold events
- `SalienceConfig` in config.py
- Integration hooks in `AgentWorkingMemory` record methods

**Out of scope:**
- Named buffer routing (AD-667) — this AD scores events; buffer routing is AD-667's job
- Idle-cycle batch review of background stream (AD-633)
- Dream integration (AD-671)
- Metabolism / active decay (AD-670)

### Design Principles

- **Standalone operation:** AD-667 (named buffers) is not yet implemented. The salience filter must work with the current ring buffer architecture. When AD-667 lands, it will call `SalienceFilter.score()` to decide which buffer an event enters. For now, the filter gates admission to the existing monolithic ring buffers.
- **Constructor injection:** `SalienceFilter` receives its config and optional `NoveltyGate` via constructor, not via global lookup.
- **Pure computation:** `score()` is a synchronous, side-effect-free function. No I/O, no database calls, no LLM calls.
- **Graceful degradation:** Each scoring dimension has a neutral fallback (0.5) when its data source is unavailable. A filter with no context still passes events through with a middling score.

---

## Section 1: SalienceScore Dataclass

Create `src/probos/cognitive/salience_filter.py`. Add the following dataclass at module level.

```python
@dataclass
class SalienceScore:
    """Result of salience scoring for a working memory candidate."""
    total: float                         # Weighted sum, 0.0-1.0
    components: dict[str, float]         # Per-dimension scores, each 0.0-1.0
    promoted: bool                       # True if total >= threshold
    entry: WorkingMemoryEntry            # The scored entry (reference, not copy)
```

Fields:
- `total`: weighted sum of all component scores, clamped to [0.0, 1.0]
- `components`: dict with keys `"relevance"`, `"recency"`, `"novelty"`, `"urgency"`, `"social"` — each a float in [0.0, 1.0]
- `promoted`: True when `total >= threshold`
- `entry`: reference to the `WorkingMemoryEntry` that was scored

Import `WorkingMemoryEntry` from `probos.cognitive.agent_working_memory`.

## Section 2: SalienceFilter Class

In the same file, add the `SalienceFilter` class.

```python
class SalienceFilter:
    """Scores working memory candidates for promotion vs. background stream.

    Pure scoring — no side effects, no I/O. Caller decides what to do
    with the SalienceScore result.
    """

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        threshold: float = 0.3,
        novelty_gate: NoveltyGate | None = None,
    ) -> None:
```

Constructor parameters:
- `weights`: dict mapping dimension name to weight. Default: `{"relevance": 0.30, "recency": 0.25, "novelty": 0.15, "urgency": 0.20, "social": 0.10}`. Weights must sum to 1.0; if they don't, normalize them on construction.
- `threshold`: promotion threshold. Default 0.3 (low bar — most events promote; only true noise filtered).
- `novelty_gate`: optional `NoveltyGate` instance (from `probos.cognitive.novelty_gate`). Use `TYPE_CHECKING` guard for the import to avoid hard dependency.

Store these as `self._weights`, `self._threshold`, `self._novelty_gate`.

Add a `from_config` classmethod:
```python
@classmethod
def from_config(cls, config: "SalienceConfig", *, novelty_gate: NoveltyGate | None = None) -> "SalienceFilter":
```

Add a `score` method — this is the primary API:
```python
def score(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> SalienceScore:
```

The `agent_context` dict provides the agent's current state for scoring. Expected keys (all optional, with neutral fallbacks):
- `agent_id`: str — the agent's identifier
- `department`: str — agent's department (e.g., "science", "engineering")
- `current_duty`: str — agent's current duty description
- `trust_scores`: dict[str, float] — callsign -> trust score mapping
- `alert_level`: str — current ship alert level ("normal", "yellow", "red")
- `agent_callsign`: str — this agent's callsign

## Section 3: Score Computation

Implement the five scoring dimensions as private methods on `SalienceFilter`. Each returns a float in [0.0, 1.0].

### `_score_relevance(entry, agent_context) -> float`

Department and duty match. Measures how related the event is to the agent's current responsibilities.

Logic:
1. If `entry.metadata` contains a `"department"` key matching `agent_context.get("department")`, score = 0.8.
2. If `entry.metadata` contains a `"duty"` key matching `agent_context.get("current_duty")`, score = 0.9.
3. If both match, score = 1.0.
4. If `entry.category` is `"alert"`, score = max(score, 0.7) — alerts are always somewhat relevant.
5. If no context available for matching, return 0.5 (neutral).

### `_score_recency(entry, agent_context) -> float`

Exponential decay based on entry age.

Logic:
```python
age_seconds = entry.age_seconds()
# Half-life of 300 seconds (5 minutes) — events older than 5 min score ~0.5
half_life = 300.0
score = 2.0 ** (-age_seconds / half_life)
return max(0.0, min(1.0, score))
```

### `_score_novelty(entry, agent_context) -> float`

Semantic novelty via NoveltyGate integration.

Logic:
1. If `self._novelty_gate` is None, return 0.5 (neutral — no novelty data).
2. Call `self._novelty_gate.check(agent_id, entry.content)` where `agent_id = agent_context.get("agent_id", "unknown")`.
3. If `verdict.is_novel` is True, return `1.0 - verdict.similarity` (more novel = higher score).
4. If `verdict.is_novel` is False, return `max(0.1, 1.0 - verdict.similarity)` (floor at 0.1 — don't completely kill non-novel events, just deprioritize).

### `_score_urgency(entry, agent_context) -> float`

Alert severity and deadline proximity.

Logic:
1. Base score = 0.3 (normal).
2. If `entry.metadata.get("severity")` exists, map: `"critical"` -> 1.0, `"high"` -> 0.8, `"medium"` -> 0.5, `"low"` -> 0.3.
3. If `agent_context.get("alert_level")` is `"red"`, add 0.2 to score. If `"yellow"`, add 0.1.
4. If `entry.category == "alert"`, set score = max(score, 0.7).
5. Clamp to [0.0, 1.0].

### `_score_social(entry, agent_context) -> float`

Trust-weighted relationship relevance.

Logic:
1. Extract `source_agent = entry.metadata.get("from")` or `entry.metadata.get("partner")`.
2. If no source agent, return 0.5 (neutral — system event, no social dimension).
3. Look up `trust = agent_context.get("trust_scores", {}).get(source_agent)`.
4. If trust is not None, return `trust` (already 0.0-1.0).
5. If trust is None (unknown agent), return 0.4 (slight penalty for unknown sources).

### Score aggregation in `score()`

```python
components = {
    "relevance": self._score_relevance(entry, agent_context),
    "recency": self._score_recency(entry, agent_context),
    "novelty": self._score_novelty(entry, agent_context),
    "urgency": self._score_urgency(entry, agent_context),
    "social": self._score_social(entry, agent_context),
}
total = sum(self._weights[k] * components[k] for k in self._weights)
total = max(0.0, min(1.0, total))
promoted = total >= self._threshold
return SalienceScore(total=round(total, 4), components=components, promoted=promoted, entry=entry)
```

## Section 4: Promotion Gate

No separate class needed. The promotion decision is the `promoted` bool on `SalienceScore`, computed by comparing `total >= self._threshold` in the `score()` method (already covered in Section 3).

Add a convenience method on `SalienceFilter`:

```python
def should_promote(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> bool:
    """Quick check — returns True if entry should enter main working memory."""
    return self.score(entry, agent_context).promoted
```

## Section 5: Background Stream

Add a `BackgroundStream` class to `salience_filter.py`. This holds sub-threshold events for potential idle-cycle review.

```python
class BackgroundStream:
    """Capped deque for sub-threshold working memory events.

    Events that don't meet the salience threshold accumulate here.
    A future idle-cycle processor (AD-633) can batch-review them.
    """

    def __init__(self, *, max_entries: int = 50) -> None:
        self._entries: deque[SalienceScore] = deque(maxlen=max_entries)

    def add(self, scored: SalienceScore) -> None:
        """Add a sub-threshold scored entry."""
        self._entries.append(scored)

    def drain(self) -> list[SalienceScore]:
        """Remove and return all entries (for batch processing)."""
        result = list(self._entries)
        self._entries.clear()
        return result

    def peek(self) -> list[SalienceScore]:
        """Return entries without removing them."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
```

## Section 6: Config

Add `SalienceConfig` to `src/probos/config.py`, placed immediately after `WorkingMemoryConfig` (after line 681).

```python
class SalienceConfig(BaseModel):
    """AD-668: Salience filter for working memory promotion."""
    enabled: bool = True
    weights: dict[str, float] = {
        "relevance": 0.30,
        "recency": 0.25,
        "novelty": 0.15,
        "urgency": 0.20,
        "social": 0.10,
    }
    threshold: float = 0.3
    background_max_entries: int = 50
```

Add to `SystemConfig` (after the `working_memory` field, around line 1143):
```python
    salience: SalienceConfig = SalienceConfig()  # AD-668
```

## Section 7: Integration with AgentWorkingMemory

Modify `AgentWorkingMemory` to optionally use a `SalienceFilter` and `BackgroundStream`.

### Constructor changes

Add two optional constructor parameters:
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
    salience_filter: SalienceFilter | None = None,
    agent_context: dict[str, Any] | None = None,
) -> None:
```

Store as `self._salience_filter` and `self._agent_context` (default `{}`).

Add `self._background_stream = BackgroundStream()` if `salience_filter` is not None, else `None`.

### New public methods

```python
def set_agent_context(self, context: dict[str, Any]) -> None:
    """Update the agent context used for salience scoring."""
    self._agent_context = context

def get_background_stream(self) -> BackgroundStream | None:
    """Return the background stream (None if salience filter not configured)."""
    return self._background_stream
```

### Gate logic in record methods

Add a private helper:
```python
def _passes_salience_gate(self, entry: WorkingMemoryEntry) -> bool:
    """Check if entry passes salience filter. Always True if no filter configured."""
    if self._salience_filter is None:
        return True
    scored = self._salience_filter.score(entry, self._agent_context)
    if not scored.promoted:
        if self._background_stream is not None:
            self._background_stream.add(scored)
        logger.debug(
            "AD-668: Entry demoted to background stream "
            "(score=%.3f, threshold=%.3f, category=%s)",
            scored.total, self._salience_filter._threshold, entry.category,
        )
        return False
    return True
```

Modify the five `record_*` methods (`record_action`, `record_observation`, `record_conversation`, `record_event`, `record_reasoning`) to call the gate **after** constructing the `WorkingMemoryEntry` but **before** appending to the ring buffer.

Pattern for each method — insert after the entry is constructed and before the `.append()` call:

```python
entry = WorkingMemoryEntry(
    content=summary,
    category="...",
    source_pathway=source,
    metadata=_meta,
    knowledge_source=knowledge_source,
)
if not self._passes_salience_gate(entry):
    return
self._recent_<buffer>.append(entry)
```

Apply this pattern to all five record methods. The entry construction must be extracted into a local variable so it can be passed to the gate.

**Important:** `record_action` currently constructs the entry inline in the `.append()` call. Extract it to a local variable first.

### Serialization

Add `background_stream` to `to_dict()`:
```python
# In to_dict(), add:
"background_stream_count": len(self._background_stream) if self._background_stream else 0,
```

No need to persist full background stream entries (they are ephemeral by design).

## Section 8: Tests

Create `tests/test_ad668_salience_filter.py` with the following test classes and methods.

**Imports:**
```python
from probos.cognitive.salience_filter import SalienceFilter, SalienceScore, BackgroundStream
from probos.cognitive.agent_working_memory import AgentWorkingMemory, WorkingMemoryEntry
```

### Class: `TestSalienceScore`

1. `test_salience_score_fields` — construct a SalienceScore, verify all fields accessible.
2. `test_salience_score_promoted_true` — total above threshold -> promoted=True.
3. `test_salience_score_promoted_false` — total below threshold -> promoted=False.

### Class: `TestSalienceFilterConstruction`

4. `test_default_weights` — default construction has correct weight keys and values.
5. `test_custom_weights_normalized` — pass weights that don't sum to 1.0, verify they are normalized.
6. `test_from_config` — construct from a SalienceConfig, verify threshold and weights applied.

### Class: `TestScoreRelevance`

7. `test_relevance_department_match` — entry with matching department -> score >= 0.8.
8. `test_relevance_duty_match` — entry with matching duty -> score >= 0.9.
9. `test_relevance_no_context` — empty agent_context -> score == 0.5 (neutral).
10. `test_relevance_alert_category_floor` — alert category entry -> score >= 0.7.

### Class: `TestScoreRecency`

11. `test_recency_fresh_entry` — entry created just now -> score close to 1.0.
12. `test_recency_old_entry` — entry created 10 minutes ago -> score < 0.5.
13. `test_recency_very_old_entry` — entry created 1 hour ago -> score near 0.0.

### Class: `TestScoreNovelty`

14. `test_novelty_no_gate` — no NoveltyGate configured -> score == 0.5.
15. `test_novelty_with_novel_verdict` — mock NoveltyGate returning is_novel=True, similarity=0.2 -> score == 0.8.
16. `test_novelty_with_duplicate_verdict` — mock NoveltyGate returning is_novel=False, similarity=0.9 -> score == 0.1 (floor).

Use a `_FakeNoveltyGate` stub class with a `check()` method returning a `NoveltyVerdict` — do NOT use `unittest.mock`. Import `NoveltyVerdict` from `probos.cognitive.novelty_gate`.

### Class: `TestScoreUrgency`

17. `test_urgency_critical_severity` — metadata severity="critical" -> score == 1.0.
18. `test_urgency_normal_baseline` — no severity, normal alert level -> score == 0.3.
19. `test_urgency_red_alert_boost` — alert_level="red" adds 0.2 -> score >= 0.5.

### Class: `TestScoreSocial`

20. `test_social_trusted_source` — metadata from="known_agent", trust_scores has that agent at 0.9 -> score == 0.9.
21. `test_social_unknown_source` — metadata from="stranger", not in trust_scores -> score == 0.4.
22. `test_social_no_source` — no from/partner in metadata -> score == 0.5.

### Class: `TestScoreAggregation`

23. `test_score_total_is_weighted_sum` — construct entry and context with known dimension values, verify total matches manual calculation.
24. `test_score_total_clamped` — verify total never exceeds 1.0 or goes below 0.0.
25. `test_should_promote_convenience` — verify `should_promote()` matches `score().promoted`.

### Class: `TestBackgroundStream`

26. `test_add_and_peek` — add entries, peek returns them without removing.
27. `test_drain_clears` — drain returns all entries and clears the stream.
28. `test_max_entries_cap` — add more than max_entries, oldest are evicted.
29. `test_len` — `len()` returns correct count.

### Class: `TestWorkingMemoryIntegration`

30. `test_record_without_filter_always_passes` — AgentWorkingMemory with no filter, record_event always appends.
31. `test_record_with_filter_promotes_high_salience` — high-salience entry enters ring buffer.
32. `test_record_with_filter_demotes_low_salience` — low-salience entry goes to background stream, does NOT enter ring buffer. Use a very high threshold (0.99) to force demotion.
33. `test_background_stream_accessible` — `get_background_stream()` returns the BackgroundStream instance.
34. `test_set_agent_context` — `set_agent_context()` updates context used for scoring.
35. `test_all_record_methods_gated` — verify record_action, record_observation, record_conversation, record_event, record_reasoning all respect the salience gate. Use threshold=0.99 so all demote, confirm all ring buffers are empty.

**Test commands (run after each section):**

```bash
# After Sections 1-5 (new file):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v -k "TestSalienceScore or TestSalienceFilter or TestScoreR or TestScoreN or TestScoreU or TestScoreS or TestScoreAgg or TestBackgroundStream"

# After Section 6 (config):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v -k "from_config"

# After Section 7 (integration):
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v -k "TestWorkingMemoryIntegration"

# Full AD-668 test suite:
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad668_salience_filter.py -v

# Regression — existing working memory tests must still pass:
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_agent_working_memory.py tests/test_bf125_working_memory_desync.py tests/test_bf127_crew_only_wm_persistence.py -v

# Full suite (final):
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

## Section 9: Tracking Updates

After all tests pass:

1. **`PROGRESS.md`** — Add entry: `AD-668 Salience Filter — CLOSED`
2. **`docs/development/roadmap.md`** — Update AD-668 status from `Planned` to `Complete`
3. **`DECISIONS.md`** — Add entry:

```
### AD-668: Salience Filter (2026-04-26)
Scoring function for working memory promotion. Five dimensions (relevance, recency,
novelty, urgency, social) with configurable weights. Default threshold 0.3 — low bar
intentionally, designed to filter noise not signal. Background stream holds sub-threshold
events for future idle-cycle review. NoveltyGate integration optional — neutral fallback
when unavailable. Pure computation, no I/O.
```
