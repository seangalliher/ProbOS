# AD-570c: Natural Language Anchor Query Routing

## Context

AD-570 delivered `recall_by_anchor()` — structured, dimension-filtered episodic recall (department, channel, trigger_type, trigger_agent, participants, time_range). AD-570b added participant indexing. But these APIs require the caller to pass structured filter parameters. No path exists for an agent's natural language query ("who observed this in Engineering?", "what happened during the morning watch?") to automatically route through anchor-indexed recall.

Currently, ALL recall goes through `recall_weighted()` (semantic + salience scoring) or `recall_for_agent()` (pure vector similarity). These work well for content-based queries but miss relational/dimensional queries where the user is asking about *who*, *where*, *when*, or *which department* — exactly the dimensions AD-570 indexes.

**This AD adds the NL front door to the anchor-indexed recall infrastructure.**

## Design

### Core: `parse_anchor_query()` Pure Function

A single pure function in `source_governance.py` that analyzes a query string and extracts structured anchor filter parameters. No LLM call — deterministic regex + vocabulary matching. Returns `None` if the query doesn't contain anchor-routable signals (caller falls through to normal `recall_weighted()` path).

### Detection Strategy (Three Extractors)

1. **Department extraction** — Match canonical department names and common aliases against query text. Vocabulary: `bridge`, `engineering`, `science`, `medical`, `security`, `operations` plus aliases (`eng`, `sci`, `med`, `sec`, `ops`, `sickbay`, `medbay`, `lab`, `armory`, `brig`).

2. **Temporal extraction** — Match watch section names and relative time phrases. Vocabulary: `mid watch`, `morning watch`, `forenoon`, `afternoon`, `first dog`, `second dog`, `first watch` plus relative phrases (`last watch`, `previous watch`, `this watch`, `today`, `yesterday`, `recent`). Maps to `time_range` tuples or `watch_section` filter using the inverse of `derive_watch_section()`.

3. **Agent/participant extraction** — Detect `@callsign` mentions via existing `extract_callsign_mention()` pattern. Also detect bare callsign references when preceded by relational indicators (`by`, `from`, `with`, `involving`, `about`).

### Routing Integration

Wire into `_recall_relevant_memories()` in `cognitive_agent.py`: after building the semantic query but *before* calling `recall_weighted()`, attempt `parse_anchor_query()`. If it returns anchor filters, call `recall_by_anchor()` instead of (or in addition to) `recall_weighted()`. Merge results.

Also wire into `_gather_context()` in `proactive.py` for the proactive path.

## Prerequisites

Verify before building (run these grep commands):

```bash
# 1. recall_by_anchor signature
grep -n "async def recall_by_anchor" src/probos/cognitive/episodic.py
# Expected: line ~1495, keyword-only params: department, channel, trigger_type, trigger_agent, agent_id, participants, time_range, semantic_query, limit

# 2. derive_watch_section exists
grep -n "def derive_watch_section" src/probos/cognitive/orientation.py
# Expected: line ~56, maps UTC hour → watch section string

# 3. extract_callsign_mention exists
grep -n "def extract_callsign_mention" src/probos/crew_profile.py
# Expected: line ~430, returns (callsign, remaining_text) or None

# 4. _recall_relevant_memories builds query
grep -n "query = " src/probos/cognitive/cognitive_agent.py | head -5
# Expected: lines ~2480-2484 showing query construction per intent type

# 5. recall_weighted call site
grep -n "recall_weighted" src/probos/cognitive/cognitive_agent.py
# Expected: line ~2555

# 6. Canonical department list
grep -n "_AGENT_DEPARTMENTS" src/probos/cognitive/standing_orders.py
# Expected: line ~33, dict with 6 departments

# 7. _gather_context recall call
grep -n "recall_weighted" src/probos/proactive.py
# Expected: line ~880
```

## Implementation

### Phase 1: `AnchorQuery` Dataclass + `parse_anchor_query()` Pure Function

**File: `src/probos/cognitive/source_governance.py`**

Add after the existing AD-568e `FaithfulnessResult` section:

```python
@dataclass(frozen=True)
class AnchorQuery:
    """AD-570c: Parsed anchor filter parameters from natural language query."""
    department: str = ""
    trigger_agent: str = ""
    participants: list[str] = field(default_factory=list)
    watch_section: str = ""
    time_range: tuple[float, float] | None = None
    semantic_query: str = ""  # Remaining query text after extraction
    has_anchor_signal: bool = False  # True if any anchor field was extracted
```

**Constants** (module-level, private):

```python
_DEPARTMENT_ALIASES: dict[str, str] = {
    # Canonical names
    "bridge": "bridge",
    "engineering": "engineering",
    "science": "science",
    "medical": "medical",
    "security": "security",
    "operations": "operations",
    # Common aliases
    "eng": "engineering",
    "sci": "science",
    "med": "medical",
    "sec": "security",
    "ops": "operations",
    "sickbay": "medical",
    "medbay": "medical",
    "lab": "science",
    "armory": "security",
    "brig": "security",
}

_WATCH_SECTIONS: dict[str, str] = {
    "mid watch": "mid",
    "morning watch": "morning",
    "forenoon watch": "forenoon",
    "forenoon": "forenoon",
    "afternoon watch": "afternoon",
    "afternoon": "afternoon",
    "first dog watch": "first_dog",
    "first dog": "first_dog",
    "second dog watch": "second_dog",
    "second dog": "second_dog",
    "first watch": "first",
}

_WATCH_HOUR_RANGES: dict[str, tuple[int, int]] = {
    "mid": (0, 4),
    "morning": (4, 8),
    "forenoon": (8, 12),
    "afternoon": (12, 16),
    "first_dog": (16, 18),
    "second_dog": (18, 20),
    "first": (20, 24),
}

_AGENT_INDICATORS = re.compile(
    r'\b(?:by|from|with|involving|about|ask)\s+(\w+)\b', re.IGNORECASE
)
```

**Function:**

```python
def parse_anchor_query(
    query: str,
    known_callsigns: list[str] | None = None,
) -> AnchorQuery:
    """AD-570c: Extract anchor filter parameters from a natural language query.

    Pure function. No LLM call, no I/O. Returns AnchorQuery with
    has_anchor_signal=True if any dimensional filter was detected.
    When no anchor signal is found, the caller should fall through
    to normal recall_weighted() path.

    Args:
        query: Natural language query text.
        known_callsigns: Optional list of valid callsigns for bare-name matching.
            If not provided, only @mention syntax is recognized.
    """
```

Implementation approach:
1. Copy `query` to a working string `remaining`.
2. **Department pass:** Case-insensitive scan for department aliases. Use word-boundary regex `r'\b{alias}\b'` for each alias in `_DEPARTMENT_ALIASES`, longest-first to avoid partial matches (e.g., "sec" matching inside "section"). Extract first match, strip from `remaining`.
3. **Watch section pass:** Case-insensitive scan for watch section phrases in `_WATCH_SECTIONS`, longest-first. Also detect relative phrases: `"last watch"` → resolve to the watch section *before* the current one via `derive_watch_section()`, `"this watch"` → current watch section, `"today"` → time_range from midnight UTC to now, `"yesterday"` → time_range from yesterday midnight to today midnight. Extract first match, strip from `remaining`.
4. **Agent pass:** First try `@callsign` extraction (reuse the regex pattern from `extract_callsign_mention`). Then scan `_AGENT_INDICATORS` for `"by/from/with/involving/about/ask {name}"`. If `known_callsigns` provided, validate extracted name against the list (case-insensitive). Unvalidated bare names are discarded (too high false positive risk without LLM). Extract matches, strip from `remaining`.
5. **Assemble:** Build `AnchorQuery` with extracted fields. `has_anchor_signal = True` if any of department, watch_section, time_range, trigger_agent, or participants is non-empty. `semantic_query` = `remaining.strip()` (the leftover text for semantic re-ranking).

**For `time_range` computation from watch sections:** Use `_WATCH_HOUR_RANGES` + today's UTC date to compute `(start_timestamp, end_timestamp)`. Import `datetime` from stdlib. For `"last watch"`, get current watch via `derive_watch_section()`, decrement to previous watch in the rotation, compute that range. For `"this watch"`, use current watch's range.

### Phase 2: Wire into `_recall_relevant_memories()` (cognitive_agent.py)

**File: `src/probos/cognitive/cognitive_agent.py`**

Insert anchor query routing **after** the query string is built (after line ~2484) and **before** the retrieval strategy classification (line ~2507). This placement means the anchor routing is attempted before the semantic recall path, giving it priority for relational queries.

Add a new private method `_try_anchor_recall()`:

```python
async def _try_anchor_recall(
    self, query: str, agent_mem_id: str
) -> list[Episode] | None:
    """AD-570c: Attempt anchor-indexed recall if query has relational signals."""
    from probos.cognitive.source_governance import parse_anchor_query, AnchorQuery

    # Gather known callsigns for bare-name validation
    known_callsigns: list[str] = []
    if self._runtime and hasattr(self._runtime, 'callsign_registry'):
        try:
            known_callsigns = self._runtime.callsign_registry.all_callsigns()
        except Exception:
            pass

    anchor = parse_anchor_query(query, known_callsigns=known_callsigns)
    if not anchor.has_anchor_signal:
        return None

    em = self._runtime.episodic_memory
    if not hasattr(em, 'recall_by_anchor'):
        return None

    results = await em.recall_by_anchor(
        department=anchor.department,
        trigger_agent=anchor.trigger_agent,
        participants=anchor.participants if anchor.participants else None,
        time_range=anchor.time_range,
        semantic_query=anchor.semantic_query,
        agent_id=agent_mem_id,
        limit=10,
    )

    if results:
        logger.debug(
            "AD-570c: Anchor recall returned %d episodes (dept=%s, agent=%s, watch=%s)",
            len(results), anchor.department, anchor.trigger_agent, anchor.watch_section,
        )
    return results if results else None
```

**Integration point in `_recall_relevant_memories()`:**

After the query is built (~line 2484) and before the retrieval strategy block (~line 2507), insert:

```python
# AD-570c: Try anchor-indexed recall for relational queries
_anchor_episodes = None
try:
    _anchor_episodes = await self._try_anchor_recall(query, _mem_id)
except Exception:
    logger.debug("AD-570c: Anchor recall failed, falling through to semantic", exc_info=True)

if _anchor_episodes:
    # Anchor recall succeeded — use these as primary episodes
    # Still proceed with semantic recall to merge results
    observation["_anchor_recall_episodes"] = _anchor_episodes
```

Then, after the existing semantic recall block completes (after ~line 2600), merge anchor results with semantic results:

```python
# AD-570c: Merge anchor recall with semantic recall
if observation.get("_anchor_recall_episodes"):
    _anchor_eps = observation.pop("_anchor_recall_episodes")
    # Deduplicate by episode ID, anchor results take precedence
    _seen_ids = {ep.id for ep in _anchor_eps}
    for ep in episodes:
        if ep.id not in _seen_ids:
            _anchor_eps.append(ep)
            _seen_ids.add(ep.id)
    episodes = _anchor_eps
```

### Phase 3: Wire into `_gather_context()` (proactive.py)

**File: `src/probos/proactive.py`**

Same pattern as Phase 2 but for the proactive recall path. Insert anchor query attempt after the query string is built (~line 878) and before `recall_weighted()` is called (~line 880).

Add anchor recall attempt:

```python
# AD-570c: Try anchor-indexed recall for proactive queries
_anchor_episodes = None
try:
    from probos.cognitive.source_governance import parse_anchor_query
    known_callsigns = []
    if hasattr(rt, 'callsign_registry'):
        try:
            known_callsigns = rt.callsign_registry.all_callsigns()
        except Exception:
            pass
    _anchor_q = parse_anchor_query(query, known_callsigns=known_callsigns)
    if _anchor_q.has_anchor_signal and hasattr(em, 'recall_by_anchor'):
        _anchor_results = await em.recall_by_anchor(
            department=_anchor_q.department,
            trigger_agent=_anchor_q.trigger_agent,
            participants=_anchor_q.participants if _anchor_q.participants else None,
            time_range=_anchor_q.time_range,
            semantic_query=_anchor_q.semantic_query,
            agent_id=_agent_mem_id,
            limit=10,
        )
        if _anchor_results:
            _anchor_episodes = _anchor_results
            logger.debug("AD-570c: Proactive anchor recall returned %d episodes", len(_anchor_results))
except Exception:
    logger.debug("AD-570c: Proactive anchor recall failed", exc_info=True)
```

After semantic recall completes, merge:

```python
# AD-570c: Merge anchor recall into proactive context
if _anchor_episodes:
    _seen = {ep.id for ep in _anchor_episodes}
    for ep in episodes:
        if ep.id not in _seen:
            _anchor_episodes.append(ep)
            _seen.add(ep.id)
    episodes = _anchor_episodes
```

### Phase 4: `CallsignRegistry.all_callsigns()` Helper

**File: `src/probos/crew_profile.py`**

Add a convenience method to `CallsignRegistry`:

```python
def all_callsigns(self) -> list[str]:
    """AD-570c: Return all registered callsigns for NL query validation."""
    return list(self._callsigns.keys())
```

This is needed for `parse_anchor_query()` to validate bare callsign references against the actual crew roster. Check if this method already exists before adding.

## Engineering Principles Compliance

| Principle | How Applied |
|-----------|-------------|
| **Single Responsibility** | `parse_anchor_query()` does one thing: NL → anchor filters. Routing logic stays in cognitive_agent/proactive. |
| **Open/Closed** | Extends recall dispatch without modifying `recall_by_anchor()` or `recall_weighted()`. New extractors can be added to `parse_anchor_query()` without changing callers. |
| **Liskov** | `AnchorQuery` with all defaults produces `has_anchor_signal=False` → caller falls through. No behavioral change for queries without anchor signals. |
| **Interface Segregation** | Callers need only `parse_anchor_query()` + `AnchorQuery`. No dependency on EpisodicMemory internals. |
| **Dependency Inversion** | `parse_anchor_query()` takes `known_callsigns: list[str]`, not `CallsignRegistry`. Pure function, no runtime dependency. |
| **Law of Demeter** | Accesses `self._runtime.episodic_memory` and `self._runtime.callsign_registry` — same pattern as existing recall code. No new deep reaches. |
| **Fail Fast / Degrade** | Anchor recall failure falls through to semantic recall (log-and-degrade). `has_anchor_signal=False` is the safe default. |
| **DRY** | Reuses `extract_callsign_mention` pattern, `derive_watch_section()`, canonical department list. No duplication. |
| **Defense in Depth** | Bare callsign names validated against `known_callsigns`. Unknown names discarded. Department aliases validated against fixed vocabulary. |

## Tests

**File: `tests/test_ad570c_nl_anchor_query.py`**

### TestParseAnchorQuery (12 tests)

1. `test_no_signal_returns_empty` — Plain query with no anchor signals → `has_anchor_signal=False`, all fields empty, `semantic_query` = original query.
2. `test_department_extraction_canonical` — "what happened in engineering" → `department="engineering"`, `has_anchor_signal=True`.
3. `test_department_extraction_alias` — "check sickbay logs" → `department="medical"`.
4. `test_department_extraction_case_insensitive` — "Engineering observations" → `department="engineering"`.
5. `test_watch_section_extraction` — "during the morning watch" → `watch_section="morning"`, `time_range` is a valid tuple.
6. `test_watch_section_relative_last` — "last watch" → resolves to previous watch section relative to current time.
7. `test_watch_section_relative_this` — "this watch" → resolves to current watch section.
8. `test_agent_at_mention` — "what did @Worf observe" → `trigger_agent="Worf"`.
9. `test_agent_bare_name_with_callsigns` — "observations from Worf" with `known_callsigns=["Worf"]` → `trigger_agent="Worf"`.
10. `test_agent_bare_name_without_callsigns` — "observations from Worf" with `known_callsigns=None` → no trigger_agent (bare names rejected without validation list).
11. `test_combined_query` — "what did @LaForge see in engineering during the forenoon watch" → `department="engineering"`, `trigger_agent="LaForge"`, `watch_section="forenoon"`, `semantic_query` contains leftover text.
12. `test_semantic_query_preserves_remainder` — After extracting department, remaining text preserved as `semantic_query`.

### TestAnchorQueryTimeRange (4 tests)

13. `test_watch_section_to_time_range` — Known watch section → time_range tuple with correct hour boundaries.
14. `test_today_time_range` — "today" → time_range from midnight UTC to now.
15. `test_yesterday_time_range` — "yesterday" → time_range from yesterday midnight to today midnight.
16. `test_no_temporal_signal` — Query without temporal phrases → `time_range=None`, `watch_section=""`.

### TestTryAnchorRecall (5 tests)

17. `test_no_signal_returns_none` — Query with no anchor signals → returns `None`, `recall_by_anchor` not called.
18. `test_anchor_recall_called_with_department` — Query with department signal → `recall_by_anchor` called with correct `department` param.
19. `test_anchor_recall_fallthrough_on_empty` — `recall_by_anchor` returns `[]` → returns `None` (fall through to semantic).
20. `test_anchor_recall_failure_returns_none` — `recall_by_anchor` raises → returns `None` (log-and-degrade).
21. `test_known_callsigns_passed` — `all_callsigns()` called on registry, result passed to `parse_anchor_query()`.

### TestRecallMemoriesMerge (4 tests)

22. `test_anchor_and_semantic_merged` — Both paths return episodes → deduplicated merge, anchor episodes first.
23. `test_anchor_only` — Anchor returns results, semantic returns empty → anchor episodes used.
24. `test_semantic_only` — No anchor signal → normal semantic path unchanged.
25. `test_dedup_by_episode_id` — Same episode in both anchor and semantic results → appears only once.

### TestAllCallsigns (1 test)

26. `test_all_callsigns_returns_list` — `CallsignRegistry.all_callsigns()` returns list of registered callsign strings.

**Total: 26 tests.**

## Build Verification

After all phases, verify:

```bash
# 1. New tests pass
python -m pytest tests/test_ad570c_nl_anchor_query.py -v

# 2. Existing recall tests still pass
python -m pytest tests/ -k "recall" -v

# 3. Existing source governance tests still pass
python -m pytest tests/ -k "source_governance or faithfulness or proprioception" -v

# 4. No import errors
python -c "from probos.cognitive.source_governance import parse_anchor_query, AnchorQuery; print('OK')"

# 5. Full suite
python -m pytest tests/ -x -q
```

## Files Modified

| File | Changes |
|------|---------|
| `src/probos/cognitive/source_governance.py` | `AnchorQuery` dataclass, `parse_anchor_query()` pure function, `_DEPARTMENT_ALIASES`, `_WATCH_SECTIONS`, `_WATCH_HOUR_RANGES`, `_AGENT_INDICATORS` constants |
| `src/probos/cognitive/cognitive_agent.py` | `_try_anchor_recall()` method, anchor routing in `_recall_relevant_memories()`, merge logic |
| `src/probos/proactive.py` | Anchor query attempt + merge in `_gather_context()` |
| `src/probos/crew_profile.py` | `all_callsigns()` method on `CallsignRegistry` (if not already present) |
| `tests/test_ad570c_nl_anchor_query.py` | 26 new tests |
