# AD-568d: Cognitive Proprioception — Ambient Source Attribution Sense

## Classification

- **Type:** Enhancement (metacognitive infrastructure)
- **Priority:** Medium
- **Risk:** Low — additive data flow layered onto existing retrieval pipeline; all new paths degrade to existing behavior on failure
- **Estimated Scope:** 4 files modified, 1 new file, ~250 lines changed, ~180 lines new, 30+ new tests

## Problem

Agents have two primary knowledge sources: LLM parametric knowledge (training data) and episodic memory (lived experience). AD-568a/b/c built the adaptive source governance pipeline — retrieval routing, budget scaling, and confidence-calibrated framing — so that the **system** governs how much episodic content reaches the agent's context window and how it's labeled.

But the **agent** itself still has no ambient awareness of where its knowledge originates. When an agent produces a response, it cannot distinguish:
- "I know this from my lived experience aboard this ship" (episodic)
- "I know this from my training data" (parametric)
- "I know this from a procedure I learned" (procedural / Cognitive JIT)
- "I know this from the Ship's Records" (Oracle service / cross-tier)

This is the metacognitive gap that AD-568d closes. The roadmap frames this as **cognitive proprioception** (Sacks, 1985 — "The Man Who Mistook His Wife for a Hat"): proprioception is pre-conscious body-position awareness. Patients who lose it must visually check where their limbs are — functional but **exhausting**. AD-568d ensures source attribution is an ambient *sense*, not a conscious *skill* the agent must invoke.

### Concrete gaps identified in the codebase

1. **No `knowledge_source` on WorkingMemoryEntry** — `agent_working_memory.py:30-44` has `source_pathway` (proactive/dm/ward_room/system) but no tag for knowledge origin (episodic/parametric/procedural/oracle).
2. **Confabulation rate never threaded to retrieval strategy** — `cognitive_agent.py:2433-2436` calls `classify_retrieval_strategy()` without `recent_confabulation_rate`. The Counselor's `CognitiveProfile.confabulation_rate` (counselor.py:149) exists but is never read by the cognitive agent. The 568a/b/c build prompt **explicitly deferred this wiring to 568d**.
3. **No source attribution data collected at runtime** — The retrieval pipeline produces `RetrievalStrategy`, `BudgetAdjustment`, and `SourceFraming` objects but discards them after prompt construction. No per-decision record is kept for later analysis.
4. **No dream consolidation step for source monitoring** — The dream pipeline (dreaming.py) has 14 steps but nothing that consolidates source attribution patterns or feeds them back to the Counselor.
5. **Counselor's `confabulation_rate` field is never updated** — It's initialized to `0.0` on `CognitiveProfile` (counselor.py:149) and never written to by any runtime path. AD-566b's qualification probe measures confabulation externally but doesn't feed results back to the profile.
6. **Working memory context lacks source tagging** — `render_context()` (agent_working_memory.py:175) outputs entries without indicating which knowledge source contributed to each action/observation.

## Prior Work Absorbed

- **AD-568a/b/c** (complete) — Built `source_governance.py` with `RetrievalStrategy`, `BudgetAdjustment`, `SourceFraming`. This AD wires the gap they left: confabulation rate threading and runtime data collection.
- **AD-566b** (complete) — Confabulation resistance qualification probe. Measures confabulation externally but doesn't feed back into the cognitive pipeline. AD-568d creates the feedback loop.
- **AD-573** (complete) — `AgentWorkingMemory` with ring buffers and `source_pathway`. AD-568d adds `knowledge_source` dimension without breaking the existing pathway tagging.
- **AD-504** (complete) — Agent self-monitoring context. AD-568d extends self-monitoring with source attribution awareness.
- **Johnson, Hashtroudi & Lindsay, 1993** — Source Monitoring Framework. Reality monitoring (internal vs external), external source monitoring (different external sources). Direct theoretical foundation for the `KnowledgeSource` enum.
- **Sacks, 1985** — Proprioception analogy. The design constraint: ambient sense, not invoked skill.
- **AD-557** (complete) — Emergence metrics. The source attribution data can feed future emergence analysis (do agents that track sources better produce higher synergy?). Not wired in this AD — noted as future work.

## What This Does NOT Do

- Does not implement AD-568e (Faithfulness Verification / Self-RAG ISSUP). That's a post-decision verification step; this is a pre- and during-decision awareness.
- Does not modify the retrieval pipeline itself (recall_weighted, recall_by_anchor). Those were scoped in 568a/b/c.
- Does not add new LLM calls. All source attribution is computed from existing pipeline signals — no token cost increase.
- Does not create a new qualification probe. AD-566b already measures confabulation. This wires the feedback loop.
- Does not change dream steps 0-13. Adds a new step 14.

## Engineering Principles Applied

| Principle | How This Build Complies |
|-----------|------------------------|
| **Single Responsibility** | `KnowledgeSource` enum and `SourceAttribution` dataclass added to `source_governance.py` (already owns source governance). Dream step 14 is a single method with one job. |
| **Open/Closed** | Extends `WorkingMemoryEntry` with an optional field (default preserves existing behavior). Extends `CognitiveProfile` with an update method. No internal modifications to existing classes. |
| **Dependency Inversion** | `compute_source_attribution()` is a pure function — no class dependencies. Dream step receives attribution data through the existing `DreamReport` mechanism. |
| **Liskov Substitution** | New `knowledge_source` field defaults to `"unknown"`, so all existing `WorkingMemoryEntry` creation sites continue working without modification. |
| **Interface Segregation** | Counselor update uses the existing `CognitiveProfile` dataclass — no new interface required. |
| **Law of Demeter** | Confabulation rate read via Counselor's public profile API, not by reaching into private state. Source attribution computed locally, not by querying other agents. |
| **Fail Fast / Log-and-Degrade** | All new code paths wrapped in try/except. Failure falls back to `KnowledgeSource.UNKNOWN` / existing behavior. No exception propagation from ambient sense logic. |
| **DRY** | Single `compute_source_attribution()` function used by both cognitive_agent.py and proactive.py recall paths. Single `_update_confabulation_rate()` used by dream step. |
| **Defense in Depth** | Confabulation rate clamped to [0.0, 1.0]. Source attribution validated at creation. Dream step validates data before updating Counselor profile. |
| **Cloud-Ready Storage** | No new storage. Source attribution data stored in existing SQLite columns via `CognitiveProfile` persistence (already async-safe). Working memory entries are transient (in-memory ring buffer). |
| **Westworld Principle** | Agents become MORE aware of their knowledge sources, not less. This is transparency, not manipulation. |

## Prerequisites

Verify these exist before building:

```bash
# source_governance.py with RetrievalStrategy, BudgetAdjustment, SourceFraming
grep -n "class RetrievalStrategy" src/probos/cognitive/source_governance.py
grep -n "class BudgetAdjustment" src/probos/cognitive/source_governance.py
grep -n "class SourceFraming" src/probos/cognitive/source_governance.py

# classify_retrieval_strategy with recent_confabulation_rate param
grep -n "recent_confabulation_rate" src/probos/cognitive/source_governance.py

# WorkingMemoryEntry dataclass
grep -n "class WorkingMemoryEntry" src/probos/cognitive/agent_working_memory.py

# CognitiveProfile with confabulation_rate field
grep -n "confabulation_rate" src/probos/cognitive/counselor.py

# Dream pipeline orchestrator
grep -n "async def dream_cycle" src/probos/cognitive/dreaming.py

# _recall_relevant_memories call site for classify_retrieval_strategy
grep -n "classify_retrieval_strategy" src/probos/cognitive/cognitive_agent.py
```

---

## Phase 1: Knowledge Source Enum and Source Attribution

### What It Does

Defines the vocabulary for source attribution and a pure function to compute it from existing pipeline signals. This is the "proprioceptive nerve" — the data structure that carries source awareness.

### 1.1 Add `KnowledgeSource` enum and `SourceAttribution` dataclass

**File:** `src/probos/cognitive/source_governance.py` (append to existing)

```python
class KnowledgeSource(str, Enum):
    """Knowledge origin classification (AD-568d).

    Ambient source attribution — what kind of knowledge contributed to
    the agent's current cognitive context. Modeled on Johnson et al. (1993)
    Source Monitoring Framework.
    """
    EPISODIC = "episodic"          # Lived experience (EpisodicMemory recall)
    PARAMETRIC = "parametric"      # LLM training data (no retrieval)
    PROCEDURAL = "procedural"      # Learned procedure (Cognitive JIT)
    ORACLE = "oracle"              # Ship's Records / cross-tier knowledge
    STANDING_ORDERS = "standing_orders"  # Standing orders / constitution
    UNKNOWN = "unknown"            # Source not determined


@dataclass(frozen=True)
class SourceAttribution:
    """Source attribution snapshot for a cognitive cycle (AD-568d).

    Captures the composition of knowledge sources that contributed to
    the agent's context for a single handle_intent() call. This is the
    proprioceptive data — the agent's awareness of where its knowledge
    came from.
    """
    retrieval_strategy: RetrievalStrategy
    primary_source: KnowledgeSource
    episodic_count: int          # Number of episodic memories in context
    procedural_count: int        # Number of procedures consulted
    oracle_used: bool            # Whether Oracle service was queried
    source_framing_authority: str  # SourceAuthority value from 568c
    confabulation_rate: float    # Agent's current confabulation rate
    budget_adjustment: float     # Scale factor from 568b


def compute_source_attribution(
    *,
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.SHALLOW,
    episodic_count: int = 0,
    procedural_count: int = 0,
    oracle_used: bool = False,
    source_framing: SourceFraming | None = None,
    budget_adjustment: BudgetAdjustment | None = None,
    confabulation_rate: float = 0.0,
) -> SourceAttribution:
    """Compute source attribution from pipeline signals (AD-568d).

    Pure function — derives the primary knowledge source from the
    retrieval strategy and what was actually retrieved. This is called
    once per cognitive cycle, after recall and before prompt construction.

    Args:
        retrieval_strategy: Strategy from classify_retrieval_strategy().
        episodic_count: Number of episodes that made it into context.
        procedural_count: Number of Cognitive JIT procedures available.
        oracle_used: Whether Oracle service returned results.
        source_framing: SourceFraming from compute_source_framing().
        budget_adjustment: BudgetAdjustment from compute_adaptive_budget().
        confabulation_rate: Agent's confabulation rate from Counselor profile.

    Returns:
        SourceAttribution snapshot.
    """
    # Determine primary source from what's actually in context
    if retrieval_strategy == RetrievalStrategy.NONE:
        if procedural_count > 0:
            primary = KnowledgeSource.PROCEDURAL
        else:
            primary = KnowledgeSource.PARAMETRIC
    elif oracle_used and episodic_count == 0:
        primary = KnowledgeSource.ORACLE
    elif episodic_count > 0:
        primary = KnowledgeSource.EPISODIC
    elif procedural_count > 0:
        primary = KnowledgeSource.PROCEDURAL
    else:
        primary = KnowledgeSource.PARAMETRIC

    return SourceAttribution(
        retrieval_strategy=retrieval_strategy,
        primary_source=primary,
        episodic_count=episodic_count,
        procedural_count=procedural_count,
        oracle_used=oracle_used,
        source_framing_authority=(
            source_framing.authority.value if source_framing else "unknown"
        ),
        confabulation_rate=confabulation_rate,
        budget_adjustment=(
            budget_adjustment.scale_factor if budget_adjustment else 1.0
        ),
    )
```

---

## Phase 2: Wire Confabulation Rate into Retrieval Strategy

### What It Does

Closes the gap explicitly deferred from AD-568a/b/c: threading the Counselor's `confabulation_rate` from the agent's `CognitiveProfile` to `classify_retrieval_strategy()`. This activates the DEEP→SHALLOW safety downgrade that's currently dead code.

### 2.1 Read confabulation rate in `_recall_relevant_memories()`

**File:** `src/probos/cognitive/cognitive_agent.py`

Find the `classify_retrieval_strategy()` call site (currently ~line 2433). Modify to read confabulation rate from the Counselor's profile:

```python
# AD-568d: Thread confabulation rate from Counselor profile
_confab_rate = 0.0
try:
    if (
        hasattr(self, '_runtime')
        and hasattr(self._runtime, 'counselor')
        and self._runtime.counselor
    ):
        _profile = await self._runtime.counselor.get_profile(self.id)
        if _profile:
            _confab_rate = getattr(_profile, 'confabulation_rate', 0.0)
except Exception:
    logger.debug("AD-568d: Could not read confabulation rate, defaulting to 0.0")

_retrieval_strategy = classify_retrieval_strategy(
    _intent_type,
    episodic_count=_episode_count,
    recent_confabulation_rate=_confab_rate,  # AD-568d: was missing
)
```

**IMPORTANT:** Verify how the Counselor exposes profiles. Check:
1. Is `self._runtime.counselor` the CounselorAgent or a service? Read the runtime startup wiring.
2. Does `get_profile()` exist as an async method? Check `counselor.py` for the exact method name and signature.
3. If the Counselor stores profiles in SQLite, `get_profile()` is likely async. Use `await`.

If the Counselor doesn't have a `get_profile()` method exposed via the runtime, look for alternative access patterns:
- `self._runtime._counselor_profiles` dict
- `CounselorAgent._profiles` (violates Law of Demeter — avoid)
- Best approach: Add a `get_confabulation_rate(agent_id)` convenience method to whatever service holds profiles, if one doesn't already exist.

### 2.2 Apply same pattern in proactive path

**File:** `src/probos/proactive.py`

The 568a build prompt noted: "The proactive path doesn't have access to the agent's confabulation rate. Pass `recent_confabulation_rate=0.0` (default) — the Counselor integration for this can be added in AD-568d."

Now add it. The proactive path has access to the runtime. Follow the same pattern as 2.1 to read the profile and pass the rate.

---

## Phase 3: Add `knowledge_source` to Working Memory

### What It Does

Adds an optional `knowledge_source` field to `WorkingMemoryEntry` so that actions and observations recorded in working memory carry their source attribution. This makes source awareness ambient in the agent's working context.

### 3.1 Extend `WorkingMemoryEntry`

**File:** `src/probos/cognitive/agent_working_memory.py`

Add `knowledge_source` field to the dataclass:

```python
@dataclass
class WorkingMemoryEntry:
    """Single entry in agent working memory."""

    content: str
    category: str  # "action", "observation", "conversation", "game", "alert", "event"
    source_pathway: str  # "proactive", "dm", "ward_room", "system"
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    knowledge_source: str = "unknown"  # AD-568d: "episodic", "parametric", "procedural", "oracle", "unknown"
```

**The default `"unknown"` ensures all existing creation sites continue working without modification (Liskov).**

### 3.2 Include `knowledge_source` in serialization

In `to_dict()` (~line 281) and `from_dict()` (~line 322), add the field:

```python
# In to_dict(), within the entry dict comprehension/construction:
"knowledge_source": entry.knowledge_source,

# In from_dict(), when reconstructing entries:
knowledge_source=entry_data.get("knowledge_source", "unknown"),
```

### 3.3 Include in `render_context()` output

In `render_context()` (~line 175), when formatting entries, include a brief source tag if not "unknown":

```python
# When rendering an entry line:
_src_tag = f" [{entry.knowledge_source}]" if entry.knowledge_source != "unknown" else ""
# Append to the formatted line, e.g.:
#   "  - [2m ago] Analyzed latency metrics [episodic]"
```

### 3.4 Tag entries with source in cognitive_agent.py

**File:** `src/probos/cognitive/cognitive_agent.py`

In `handle_intent()` (~line 1399), after the recall phase produces the `SourceAttribution`, pass the primary source to working memory recording calls:

```python
# After computing source_attribution (Phase 4):
_knowledge_src = _source_attribution.primary_source.value if _source_attribution else "unknown"

# When recording actions to working memory:
self._working_memory.record_action(
    action_summary,
    source=source_pathway,
    metadata={...},
    # AD-568d: New parameter
)
```

**IMPORTANT:** The `record_action()` signature currently doesn't accept `knowledge_source`. Check the method signature. If it doesn't have the parameter, add it as an optional kwarg with default `"unknown"`:

```python
def record_action(self, summary: str, *, source: str,
                  metadata: dict[str, Any] | None = None,
                  knowledge_source: str = "unknown") -> None:
```

Apply the same change to `record_observation()` and `record_conversation()`.

---

## Phase 4: Compute and Record Source Attribution in Cognitive Pipeline

### What It Does

Integrates `compute_source_attribution()` into the handle_intent() pipeline, creating a per-decision source attribution record that can be consumed by the dream consolidation step and the Counselor.

### 4.1 Compute attribution after recall

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_recall_relevant_memories()`, after computing `_retrieval_strategy`, `_budget_adj`, and `_framing`, compute the attribution:

```python
# AD-568d: Compute source attribution snapshot
from probos.cognitive.source_governance import compute_source_attribution, KnowledgeSource
_procedural_count = 0
try:
    if hasattr(self, '_procedure_store') and self._procedure_store:
        # Count procedures relevant to this intent type
        _intent_procs = await self._procedure_store.get_by_intent(
            _intent_type
        ) if hasattr(self._procedure_store, 'get_by_intent') else []
        _procedural_count = len(_intent_procs) if _intent_procs else 0
except Exception:
    pass

_source_attribution = compute_source_attribution(
    retrieval_strategy=_retrieval_strategy,
    episodic_count=len(scored_results) if scored_results else 0,
    procedural_count=_procedural_count,
    oracle_used=bool(observation.get("_oracle_context")),
    source_framing=_framing,
    budget_adjustment=_budget_adj if '_budget_adj' in dir() else None,
    confabulation_rate=_confab_rate,
)

# Store for downstream consumption (dream step, episode recording)
observation["_source_attribution"] = _source_attribution
```

### 4.2 Record attribution in episode metadata

When the cognitive agent records the episode (in the `_record_episode()` or equivalent method), include the source attribution:

```python
# In episode metadata dict:
if observation.get("_source_attribution"):
    _attr = observation["_source_attribution"]
    metadata["source_attribution"] = {
        "primary_source": _attr.primary_source.value,
        "retrieval_strategy": _attr.retrieval_strategy.value,
        "episodic_count": _attr.episodic_count,
        "procedural_count": _attr.procedural_count,
        "oracle_used": _attr.oracle_used,
        "confabulation_rate": _attr.confabulation_rate,
    }
```

**IMPORTANT:** Verify how episode metadata is stored. Check the Episode dataclass — does it have a `metadata` dict? If not, the `user_input` or `tool_calls` field contains the episode data. Find where the episode is constructed in `handle_intent()` and add the attribution there. Do NOT create a new storage mechanism — piggyback on whatever metadata field already exists.

---

## Phase 5: Dream Step 14 — Source Attribution Consolidation

### What It Does

Adds a dream consolidation step that aggregates source attribution data across recent episodes and updates the Counselor's `CognitiveProfile` with computed metrics — primarily `confabulation_rate` and a new `source_diversity_score`.

### 5.1 Add dream step 14 method

**File:** `src/probos/cognitive/dreaming.py`

Add after the existing step 13 (Behavioral Metrics):

```python
# ---------------------------------------------------------------
# Step 14: Source Attribution Consolidation (AD-568d)
# ---------------------------------------------------------------
async def _step_14_source_attribution(
    self, episodes: list[Episode],
) -> dict[str, Any]:
    """Dream step 14: Consolidate source attribution patterns (AD-568d).

    Aggregates source attribution metadata from recent episodes to:
    1. Compute running confabulation rate estimate
    2. Measure source diversity (healthy agents use multiple sources)
    3. Update Counselor's CognitiveProfile with findings

    Returns dict with consolidation metrics for DreamReport.
    """
    result: dict[str, Any] = {
        "episodes_with_attribution": 0,
        "source_distribution": {},
        "mean_confabulation_rate": 0.0,
        "source_diversity_score": 0.0,
    }

    if not episodes:
        return result

    # Extract source attribution from episode metadata
    attributions: list[dict] = []
    for ep in episodes:
        _meta = getattr(ep, 'metadata', None) or {}
        if isinstance(_meta, str):
            try:
                import json
                _meta = json.loads(_meta)
            except Exception:
                continue
        _attr = _meta.get("source_attribution")
        if _attr and isinstance(_attr, dict):
            attributions.append(_attr)

    if not attributions:
        return result

    result["episodes_with_attribution"] = len(attributions)

    # 1. Source distribution
    source_counts: dict[str, int] = {}
    for attr in attributions:
        src = attr.get("primary_source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
    result["source_distribution"] = source_counts

    # 2. Mean confabulation rate from attribution snapshots
    confab_rates = [
        attr.get("confabulation_rate", 0.0) for attr in attributions
    ]
    mean_confab = sum(confab_rates) / len(confab_rates) if confab_rates else 0.0
    result["mean_confabulation_rate"] = round(mean_confab, 4)

    # 3. Source diversity score (Shannon entropy normalized to [0, 1])
    total = sum(source_counts.values())
    if total > 0 and len(source_counts) > 1:
        import math
        entropy = -sum(
            (c / total) * math.log2(c / total)
            for c in source_counts.values()
            if c > 0
        )
        max_entropy = math.log2(len(source_counts))
        diversity = entropy / max_entropy if max_entropy > 0 else 0.0
    else:
        diversity = 0.0
    result["source_diversity_score"] = round(diversity, 4)

    # 4. Update Counselor profile if available
    try:
        if self._counselor and hasattr(self._counselor, 'update_source_metrics'):
            await self._counselor.update_source_metrics(
                agent_id=self._agent_id,
                confabulation_rate=mean_confab,
                source_diversity=diversity,
                source_distribution=source_counts,
            )
    except Exception:
        logger.debug("AD-568d: Could not update Counselor source metrics")

    return result
```

### 5.2 Wire step 14 into `dream_cycle()`

In `dream_cycle()` (~line 164), after step 13 (Behavioral Metrics, ~line 929):

```python
# Step 14: Source Attribution Consolidation (AD-568d)
try:
    _source_attr_result = await self._step_14_source_attribution(episodes)
    report.source_attribution = _source_attr_result
except Exception:
    logger.debug("AD-568d: Dream step 14 (source attribution) failed")
```

**IMPORTANT:** Check the `DreamReport` dataclass. If it doesn't have a `source_attribution` field, add one as an optional dict:

```python
source_attribution: dict[str, Any] = field(default_factory=dict)  # AD-568d
```

### 5.3 Add `update_source_metrics()` to Counselor

**File:** `src/probos/cognitive/counselor.py`

Add a method to update source metrics on the CognitiveProfile:

```python
async def update_source_metrics(
    self,
    agent_id: str,
    *,
    confabulation_rate: float = 0.0,
    source_diversity: float = 0.0,
    source_distribution: dict[str, int] | None = None,
) -> None:
    """Update source attribution metrics on agent profile (AD-568d).

    Called by dream step 14 to feed source monitoring data back
    into the Counselor's wellness tracking.
    """
    profile = self._profiles.get(agent_id)
    if not profile:
        return

    # Update confabulation rate (exponential moving average)
    alpha = 0.3  # Weight for new observation
    profile.confabulation_rate = round(
        alpha * confabulation_rate + (1 - alpha) * profile.confabulation_rate,
        4,
    )

    # Persist
    await self._save_profile(profile)
```

**IMPORTANT:** Verify:
1. How the Counselor stores profiles — is `self._profiles` a dict? Is `_save_profile()` async?
2. Can `CognitiveProfile` fields be mutated directly, or is it frozen? If frozen, replace with a new instance using `dataclasses.replace()`.
3. Check the Counselor's existing `_save_profile()` or equivalent persistence method signature.

---

## Phase 6: Ambient Source Tag in Cognitive Prompt

### What It Does

Injects a one-line ambient source awareness tag into the agent's cognitive prompt, so the LLM sees what knowledge sources contributed to the current context. This is the "sense" — not a tool the agent invokes, but information passively present in its frame.

### 6.1 Add source attribution tag in `_build_user_message()`

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_build_user_message()`, after the memory section and before the task/intent section, inject a brief source awareness line:

```python
# AD-568d: Ambient source attribution tag (cognitive proprioception)
_attr = observation.get("_source_attribution")
if _attr:
    _sources_present = []
    if _attr.episodic_count > 0:
        _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
    if _attr.procedural_count > 0:
        _sources_present.append(f"learned procedures ({_attr.procedural_count})")
    if _attr.oracle_used:
        _sources_present.append("ship's records")
    if not _sources_present:
        _sources_present.append("training knowledge only")

    composed += (
        f"\n[Source awareness: Your response draws on: {', '.join(_sources_present)}. "
        f"Primary basis: {_attr.primary_source.value}.]\n"
    )
```

This is deliberately minimal — one line, passive, informational. Not a tool, not a command, not a prompt manipulation. Pure proprioception.

---

## Tests

**File:** `tests/test_ad568d_cognitive_proprioception.py` (NEW)

### Test Class 1: KnowledgeSource and SourceAttribution (8 tests)

```python
class TestKnowledgeSourceAttribution:
    """AD-568d: Knowledge source enum and attribution computation."""

    def test_knowledge_source_values(self):
        """KnowledgeSource enum has all expected values."""
        assert set(KnowledgeSource) == {
            KnowledgeSource.EPISODIC, KnowledgeSource.PARAMETRIC,
            KnowledgeSource.PROCEDURAL, KnowledgeSource.ORACLE,
            KnowledgeSource.STANDING_ORDERS, KnowledgeSource.UNKNOWN,
        }

    def test_none_strategy_parametric_primary(self):
        """NONE strategy with no procedures → PARAMETRIC primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.NONE,
        )
        assert attr.primary_source == KnowledgeSource.PARAMETRIC

    def test_none_strategy_with_procedures(self):
        """NONE strategy with procedures → PROCEDURAL primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.NONE,
            procedural_count=3,
        )
        assert attr.primary_source == KnowledgeSource.PROCEDURAL

    def test_episodic_recall_primary(self):
        """Episodes recalled → EPISODIC primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.SHALLOW,
            episodic_count=5,
        )
        assert attr.primary_source == KnowledgeSource.EPISODIC

    def test_oracle_only_primary(self):
        """Oracle used without episodic → ORACLE primary."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.DEEP,
            oracle_used=True,
            episodic_count=0,
        )
        assert attr.primary_source == KnowledgeSource.ORACLE

    def test_attribution_captures_confab_rate(self):
        """SourceAttribution stores confabulation rate."""
        attr = compute_source_attribution(confabulation_rate=0.15)
        assert attr.confabulation_rate == 0.15

    def test_attribution_captures_budget_scale(self):
        """SourceAttribution stores budget adjustment scale factor."""
        budget = BudgetAdjustment(4000, 5200, "test", 1.3)
        attr = compute_source_attribution(budget_adjustment=budget)
        assert attr.budget_adjustment == 1.3

    def test_attribution_defaults_safe(self):
        """Default attribution is safe (PARAMETRIC, no confabulation)."""
        attr = compute_source_attribution()
        assert attr.primary_source == KnowledgeSource.PARAMETRIC
        assert attr.confabulation_rate == 0.0
        assert attr.budget_adjustment == 1.0
```

### Test Class 2: Confabulation Rate Threading (5 tests)

```python
class TestConfabulationRateThreading:
    """AD-568d: Confabulation rate wired from Counselor to retrieval strategy."""

    def test_high_confab_downgrades_deep(self):
        """High confabulation rate should downgrade DEEP to SHALLOW."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=10,
            recent_confabulation_rate=0.5,
        )
        assert result == RetrievalStrategy.SHALLOW

    def test_low_confab_preserves_deep(self):
        """Low confabulation rate preserves DEEP strategy."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=10,
            recent_confabulation_rate=0.1,
        )
        assert result == RetrievalStrategy.DEEP

    def test_confab_threshold_boundary(self):
        """Exactly 0.3 does NOT trigger downgrade."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=10,
            recent_confabulation_rate=0.3,
        )
        assert result == RetrievalStrategy.DEEP

    def test_confab_does_not_affect_shallow(self):
        """Confabulation rate only affects DEEP, not SHALLOW intents."""
        result = classify_retrieval_strategy(
            "direct_message",
            episodic_count=10,
            recent_confabulation_rate=0.9,
        )
        assert result == RetrievalStrategy.SHALLOW

    def test_confab_does_not_affect_none(self):
        """Confabulation rate irrelevant when NONE (no episodes)."""
        result = classify_retrieval_strategy(
            "incident_response",
            episodic_count=0,
            recent_confabulation_rate=0.9,
        )
        assert result == RetrievalStrategy.NONE
```

### Test Class 3: Working Memory Source Tagging (5 tests)

```python
class TestWorkingMemorySourceTag:
    """AD-568d: WorkingMemoryEntry knowledge_source field."""

    def test_default_knowledge_source_unknown(self):
        """Default knowledge_source is 'unknown'."""
        entry = WorkingMemoryEntry(
            content="test", category="action", source_pathway="system",
        )
        assert entry.knowledge_source == "unknown"

    def test_explicit_knowledge_source(self):
        """Explicit knowledge_source is stored."""
        entry = WorkingMemoryEntry(
            content="test", category="action", source_pathway="dm",
            knowledge_source="episodic",
        )
        assert entry.knowledge_source == "episodic"

    def test_to_dict_includes_knowledge_source(self):
        """Serialization includes knowledge_source."""
        mem = AgentWorkingMemory()
        mem.record_action("test action", source="system")
        d = mem.to_dict()
        entries = d.get("actions", d.get("recent_actions", []))
        assert all("knowledge_source" in e for e in entries)

    def test_from_dict_restores_knowledge_source(self):
        """Deserialization restores knowledge_source."""
        # Create, serialize, deserialize
        mem = AgentWorkingMemory()
        mem.record_action("test", source="system")
        d = mem.to_dict()
        mem2 = AgentWorkingMemory.from_dict(d)
        # Verify restored
        d2 = mem2.to_dict()
        entries = d2.get("actions", d2.get("recent_actions", []))
        assert all("knowledge_source" in e for e in entries)

    def test_render_context_includes_source_tag(self):
        """render_context() shows source tag for non-unknown entries."""
        mem = AgentWorkingMemory()
        # Record with explicit source
        entry = WorkingMemoryEntry(
            content="analyzed logs", category="action",
            source_pathway="system", knowledge_source="episodic",
        )
        mem._actions.append(entry)
        output = mem.render_context()
        assert "episodic" in output
```

### Test Class 4: Dream Step 14 (7 tests)

```python
class TestDreamStep14SourceAttribution:
    """AD-568d: Dream consolidation step for source attribution."""

    @pytest.mark.asyncio
    async def test_step_returns_empty_for_no_episodes(self):
        """No episodes → empty result."""
        engine = _make_dream_engine()  # Use existing test helper pattern
        result = await engine._step_14_source_attribution([])
        assert result["episodes_with_attribution"] == 0

    @pytest.mark.asyncio
    async def test_step_counts_attributions(self):
        """Counts episodes with source_attribution metadata."""
        episodes = [_make_episode_with_attribution("episodic")]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["episodes_with_attribution"] == 1

    @pytest.mark.asyncio
    async def test_source_distribution_computed(self):
        """Source distribution tallies primary sources."""
        episodes = [
            _make_episode_with_attribution("episodic"),
            _make_episode_with_attribution("episodic"),
            _make_episode_with_attribution("parametric"),
        ]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["source_distribution"]["episodic"] == 2
        assert result["source_distribution"]["parametric"] == 1

    @pytest.mark.asyncio
    async def test_mean_confabulation_rate(self):
        """Mean confabulation rate computed from attribution snapshots."""
        episodes = [
            _make_episode_with_attribution("episodic", confab=0.1),
            _make_episode_with_attribution("episodic", confab=0.3),
        ]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert abs(result["mean_confabulation_rate"] - 0.2) < 0.01

    @pytest.mark.asyncio
    async def test_source_diversity_score_single_source(self):
        """Single source type → diversity 0."""
        episodes = [_make_episode_with_attribution("episodic")]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["source_diversity_score"] == 0.0

    @pytest.mark.asyncio
    async def test_source_diversity_score_multiple_sources(self):
        """Multiple source types → diversity > 0."""
        episodes = [
            _make_episode_with_attribution("episodic"),
            _make_episode_with_attribution("parametric"),
        ]
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution(episodes)
        assert result["source_diversity_score"] > 0.0

    @pytest.mark.asyncio
    async def test_step_degrades_gracefully_on_bad_metadata(self):
        """Episodes with missing/corrupt metadata → skip gracefully."""
        ep = _make_episode()  # No source_attribution in metadata
        engine = _make_dream_engine()
        result = await engine._step_14_source_attribution([ep])
        assert result["episodes_with_attribution"] == 0
```

### Test Class 5: Ambient Source Tag in Prompt (5 tests)

```python
class TestAmbientSourceTag:
    """AD-568d: Source awareness tag in cognitive prompt."""

    def test_tag_includes_episodic_count(self):
        """Source tag mentions episodic count when present."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.SHALLOW,
            episodic_count=3,
        )
        # Verify the fields that the tag renderer would use
        assert attr.episodic_count == 3
        assert attr.primary_source == KnowledgeSource.EPISODIC

    def test_tag_shows_training_only_when_no_retrieval(self):
        """No retrieval → tag says 'training knowledge only'."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.NONE,
        )
        assert attr.primary_source == KnowledgeSource.PARAMETRIC
        assert attr.episodic_count == 0
        assert attr.procedural_count == 0
        assert attr.oracle_used is False

    def test_tag_includes_oracle(self):
        """Oracle used → tag includes ship's records."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.DEEP,
            oracle_used=True,
            episodic_count=2,
        )
        assert attr.oracle_used is True

    def test_tag_includes_procedures(self):
        """Procedures available → tag mentions them."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.SHALLOW,
            procedural_count=5,
            episodic_count=2,
        )
        assert attr.procedural_count == 5

    def test_attribution_survives_serialization(self):
        """SourceAttribution fields are all primitives — JSON-safe."""
        attr = compute_source_attribution(
            retrieval_strategy=RetrievalStrategy.DEEP,
            episodic_count=3,
            procedural_count=2,
            oracle_used=True,
            confabulation_rate=0.1,
        )
        import json
        d = {
            "primary_source": attr.primary_source.value,
            "retrieval_strategy": attr.retrieval_strategy.value,
            "episodic_count": attr.episodic_count,
            "procedural_count": attr.procedural_count,
            "oracle_used": attr.oracle_used,
            "confabulation_rate": attr.confabulation_rate,
        }
        serialized = json.dumps(d)
        assert serialized  # No serialization errors
```

**Total: 30 tests across 5 test classes.**

---

## Regression Test Targets

Run these test files after the build to verify no regressions:

```bash
pytest tests/test_ad568d_cognitive_proprioception.py -v   # New tests (30)
pytest tests/test_source_governance.py -v                  # 568a/b/c not broken
pytest tests/test_episodic*.py -v                          # Recall pipeline intact
pytest tests/test_proactive*.py -v                         # Proactive cycle intact
pytest tests/test_working_memory*.py -v                    # Working memory intact
pytest tests/test_dreaming*.py -v                          # Dream pipeline intact
pytest tests/test_counselor*.py -v                         # Counselor intact
```

---

## Build Verification Checklist

Before starting:
- [ ] `RetrievalStrategy` enum exists in `source_governance.py`
- [ ] `classify_retrieval_strategy()` has `recent_confabulation_rate` param
- [ ] `WorkingMemoryEntry` dataclass exists in `agent_working_memory.py`
- [ ] `CognitiveProfile` has `confabulation_rate` field in `counselor.py`
- [ ] `dream_cycle()` method exists with numbered steps in `dreaming.py`
- [ ] `DreamReport` dataclass exists — check for `source_attribution` field availability
- [ ] Counselor profile persistence method (verify name: `_save_profile`? `_persist_profile`?)
- [ ] `_recall_relevant_memories()` call site for `classify_retrieval_strategy` (~line 2433)
- [ ] Episode metadata storage — verify how metadata is persisted on Episode dataclass

After building:
- [ ] All 30 new tests pass
- [ ] Regression tests pass (source_governance, episodic, proactive, working_memory, dreaming, counselor)
- [ ] No circular imports (`python -c "from probos.cognitive.source_governance import KnowledgeSource, compute_source_attribution"`)
- [ ] Confabulation rate flows from CognitiveProfile → classify_retrieval_strategy (verify with debug log)
- [ ] WorkingMemoryEntry accepts `knowledge_source` with default "unknown"
- [ ] Dream step 14 runs without error (even with no attribution data)
- [ ] Ambient source tag appears in cognitive prompt when attribution is present
- [ ] Full test suite passes: `pytest --timeout=60 -x`
