# AD-604: Spreading Activation / Multi-Hop Retrieval

**Status:** Ready for builder
**Scope:** New file + integration edits (~220 lines new, ~25 lines edits)
**Depends on:** AD-602 (Question-Adaptive Retrieval), AD-600 (Transactive Memory — optional)

**Acceptance Criteria:**
- All 12 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Summary

Each recall query retrieves episodes in a single hop (direct semantic similarity). Associative chains ("A reminds me of B which reminds me of C") are not followed. Multi-hop retrieval enables richer recall for causal and narrative queries.

This AD adds a `SpreadingActivationEngine` that performs multi-hop retrieval: first-hop results seed second-hop queries using anchor metadata as filters. Results are deduplicated and scored with hop decay. Integrated with CognitiveAgent for CAUSAL queries (from AD-602).

Key capabilities:
1. `SpreadingActivationEngine` — multi-hop recall using anchor metadata as second-hop query filters.
2. Hop decay — second-hop scores are multiplied by `hop_decay_factor` (default 0.6).
3. Deduplication — episodes appearing in multiple hops keep their highest composite score.
4. CAUSAL integration — `_recall_relevant_memories()` uses spreading activation for CAUSAL queries.

## Architecture

```
SpreadingActivationEngine.multi_hop_recall(query, agent_id)
    │
    ├── Hop 1: recall_weighted(query) → top-k RecallScores
    │     │
    │     ├── For each result, extract anchor metadata:
    │     │   ├── department (from anchors.duty_department)
    │     │   ├── trigger_type (from anchors.trigger_type)
    │     │   └── participants (from episode.agent_ids)
    │     │
    │     ▼
    ├── Hop 2: recall_by_anchor_scored(anchor_filters) per first-hop result
    │     │
    │     ├── Filter: require min_anchor_fields (default 2) non-empty fields
    │     ├── Score: second_hop_composite * hop_decay_factor
    │     │
    │     ▼
    └── Merge: deduplicate by episode.id, keep max score
        │
        ▼
    Return combined RecallScores sorted by composite_score
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/spreading_activation.py` | **NEW** — SpreadingActivationEngine |
| `src/probos/config.py` | Add SpreadingActivationConfig + wire into SystemConfig |
| `src/probos/cognitive/cognitive_agent.py` | Use spreading activation for CAUSAL queries in `_recall_relevant_memories()` |
| `tests/test_ad604_spreading_activation.py` | **NEW** — 12 tests |

---

## Implementation

### Section 1: SpreadingActivationConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `QuestionAdaptiveConfig` (or after the last cognitive config):

```python
class SpreadingActivationConfig(BaseModel):
    """AD-604: Spreading activation / multi-hop retrieval configuration."""

    enabled: bool = True
    max_hops: int = 2
    k_per_hop: int = 5
    hop_decay_factor: float = 0.6
    min_anchor_fields: int = 2
```

Wire into `SystemConfig`:

```python
    spreading_activation: SpreadingActivationConfig = SpreadingActivationConfig()  # AD-604
```

### Section 2: SpreadingActivationEngine

**File:** `src/probos/cognitive/spreading_activation.py` (NEW)

```python
"""AD-604: Spreading Activation / Multi-Hop Retrieval.

Multi-hop recall engine: first-hop results seed second-hop queries using
anchor metadata as filters. Enables associative chains — "A reminds me
of B which reminds me of C" — for richer causal and narrative recall.

No graph database — uses existing EpisodicMemory recall methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _AnchorExtraction:
    """Extracted anchor fields from a first-hop result for second-hop query."""

    department: str = ""
    channel: str = ""
    trigger_type: str = ""
    trigger_agent: str = ""
    field_count: int = 0  # how many non-empty fields


class SpreadingActivationEngine:
    """Multi-hop retrieval engine using anchor-based spreading activation.

    **Builder:** Config is always provided via Pydantic defaults. Do NOT add in-class fallback defaults.

    Parameters
    ----------
    config : SpreadingActivationConfig
        Configuration (always provided — Pydantic provides defaults).
    episodic_memory : EpisodicMemory or None
        The episodic memory instance for recall calls.
    """

    def __init__(
        self,
        config: Any = None,
        episodic_memory: Any = None,
    ) -> None:
        if config is not None:
            self._max_hops: int = config.max_hops
            self._k_per_hop: int = config.k_per_hop
            self._hop_decay: float = config.hop_decay_factor
            self._min_anchor_fields: int = config.min_anchor_fields
        else:
            # Only for unit tests that construct without config
            self._max_hops = 2
            self._k_per_hop = 5
            self._hop_decay = 0.6
            self._min_anchor_fields = 2

        self._episodic_memory = episodic_memory

    async def multi_hop_recall(
        self,
        query: str,
        agent_id: str,
        *,
        hops: int | None = None,
        k_per_hop: int | None = None,
        trust_network: Any = None,
        hebbian_router: Any = None,
    ) -> list[Any]:
        """Perform multi-hop recall starting from a semantic query.

        Parameters
        ----------
        query : str
            The search query for the first hop.
        agent_id : str
            The agent performing recall.
        hops : int or None
            Number of hops. Defaults to config max_hops.
        k_per_hop : int or None
            Results per hop. Defaults to config k_per_hop.
        trust_network : TrustNetwork or None
            For salience-weighted recall scoring.
        hebbian_router : HebbianRouter or None
            For salience-weighted recall scoring.

        Returns
        -------
        list[RecallScore]
            Combined results from all hops, deduplicated, sorted by
            composite_score descending.
        """
        if not self._episodic_memory or not query:
            return []

        max_h = hops if hops is not None else self._max_hops
        k = k_per_hop if k_per_hop is not None else self._k_per_hop

        # Track all results by episode ID (for dedup)
        seen: dict[str, Any] = {}  # episode_id -> RecallScore (best score)

        # Hop 1: standard semantic recall
        try:
            first_hop = await self._episodic_memory.recall_weighted(
                agent_id,
                query,
                k=k,
                trust_network=trust_network,
                hebbian_router=hebbian_router,
            )
        except Exception:
            logger.debug("AD-604: First hop recall failed", exc_info=True)
            return []

        if not first_hop:
            return []

        for rs in first_hop:
            ep_id = rs.episode.id
            if ep_id:
                seen[ep_id] = rs

        # Additional hops (up to max_hops - 1 more)
        if max_h >= 2:
            for rs in first_hop:
                extraction = self._extract_anchor_fields(rs)
                if extraction.field_count < self._min_anchor_fields:
                    continue

                try:
                    second_hop = await self._episodic_memory.recall_by_anchor_scored(
                        agent_id=agent_id,
                        department=extraction.department,
                        channel=extraction.channel,
                        trigger_type=extraction.trigger_type,
                        trigger_agent=extraction.trigger_agent,
                        k=k,
                        trust_network=trust_network,
                        hebbian_router=hebbian_router,
                    )
                except Exception:
                    logger.debug(
                        "AD-604: Second hop recall failed for episode %s",
                        rs.episode.id,
                        exc_info=True,
                    )
                    continue

                for sh_rs in second_hop:
                    ep_id = sh_rs.episode.id
                    if not ep_id:
                        continue

                    # Apply hop decay to second-hop scores
                    decayed = self._apply_hop_decay(sh_rs)

                    # Dedup: keep highest score
                    if ep_id in seen:
                        if decayed.composite_score > seen[ep_id].composite_score:
                            seen[ep_id] = decayed
                    else:
                        seen[ep_id] = decayed

        # Sort by composite_score descending
        results = sorted(seen.values(), key=lambda rs: rs.composite_score, reverse=True)

        logger.debug(
            "AD-604: Multi-hop recall — %d first-hop, %d total after %d hops",
            len(first_hop), len(results), min(max_h, 2),
        )
        return results

    def _extract_anchor_fields(self, recall_score: Any) -> _AnchorExtraction:
        """Extract anchor metadata from a RecallScore for second-hop query.

        Parameters
        ----------
        recall_score : RecallScore
            A first-hop recall result.

        Returns
        -------
        _AnchorExtraction
            Extracted fields with a count of non-empty ones.
        """
        episode = recall_score.episode
        if not episode:
            return _AnchorExtraction()

        anchors = episode.anchors
        if not anchors:
            return _AnchorExtraction()

        dept = anchors.duty_department or ""
        channel = anchors.channel or ""
        trigger_type = anchors.trigger_type or ""
        trigger_agent = anchors.trigger_agent or ""

        field_count = sum(1 for f in [dept, channel, trigger_type, trigger_agent] if f)

        return _AnchorExtraction(
            department=dept,
            channel=channel,
            trigger_type=trigger_type,
            trigger_agent=trigger_agent,
            field_count=field_count,
        )

    def _apply_hop_decay(self, recall_score: Any) -> Any:
        """Apply hop decay factor to a second-hop RecallScore.

        **Builder:** RecallScore is frozen (`@dataclass(frozen=True)`). Use `dataclasses.replace(rs, composite_score=new_score)` to create modified copies. The `except` fallback must NOT mutate the input — construct a new object instead.

        Creates a new RecallScore with the composite_score multiplied
        by hop_decay_factor.

        Parameters
        ----------
        recall_score : RecallScore
            The second-hop result to decay.

        Returns
        -------
        RecallScore
            New RecallScore with decayed composite_score.
        """
        from dataclasses import replace
        return replace(
            recall_score,
            composite_score=recall_score.composite_score * self._hop_decay,
        )
```

### Section 3: CognitiveAgent Integration

**File:** `src/probos/cognitive/cognitive_agent.py`

#### 3a: Instance variable

In `__init__`, after the `self._retrieval_strategy_selector` line (added by AD-602), add:

```python
        # AD-604: Spreading activation engine
        self._spreading_activation: SpreadingActivationEngine | None = None
```

#### 3b: Lazy initialization

In `_recall_relevant_memories()`, after the AD-602 lazy-init block for QuestionClassifier, add:

```python
        # AD-604: Lazy-init spreading activation engine
        if self._spreading_activation is None:
            try:
                from probos.cognitive.spreading_activation import SpreadingActivationEngine
                _sa_config = self._runtime.config.spreading_activation
                if _sa_config.enabled:
                    self._spreading_activation = SpreadingActivationEngine(
                        config=_sa_config,
                        episodic_memory=self._runtime.episodic_memory,
                    )
            except Exception:
                logger.debug("AD-604: Spreading activation unavailable", exc_info=True)
```

#### 3c: Use for CAUSAL queries

After the AD-602 classification block (where `_question_type` is set), add:

```python
            # AD-604: Use spreading activation for CAUSAL queries
            if (
                _question_type is not None
                and _question_type.value == "causal"
                and self._spreading_activation is not None
            ):
                try:
                    from probos.cognitive.question_classifier import QuestionType as _QT
                    sa_results = await self._spreading_activation.multi_hop_recall(
                        query,
                        _mem_id,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                    )
                    if sa_results:
                        # Use spreading activation results instead of standard recall
                        _memories = sa_results[:5]
                        logger.debug(
                            "AD-604: Used spreading activation for CAUSAL query — %d results",
                            len(_memories),
                        )
                        # Skip standard recall below — we already have results
                        observation["recalled_episodes"] = [
                            self._format_recall_score(rs) for rs in _memories
                        ]
                        return observation
                except Exception:
                    logger.debug("AD-604: Spreading activation failed, falling back to standard", exc_info=True)
```

**Builder:** If `_format_recall_score` does not exist as a method on CognitiveAgent, search for how recalled episodes are formatted in the existing recall flow and follow the same pattern. The key is to insert the spreading activation results into the observation dict in the same format as standard recall results. If the existing format uses a different key or structure, match it exactly.

---

## Tests

**File:** `tests/test_ad604_spreading_activation.py` (NEW)

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_single_hop_fallback` | When spreading activation disabled, falls back to standard recall |
| 2 | `test_two_hop_retrieval` | Two-hop retrieval returns more results than single hop |
| 3 | `test_hop_decay_applied` | Second-hop scores are multiplied by hop_decay_factor |
| 4 | `test_deduplication` | Same episode in both hops keeps highest score |
| 5 | `test_anchor_field_extraction` | _extract_anchor_fields returns correct fields from episode anchors |
| 6 | `test_anchor_field_extraction_no_anchors` | Episode without anchors returns empty extraction with field_count=0 |
| 7 | `test_min_anchor_fields_filter` | Second hop skipped when anchor extraction has fewer fields than min_anchor_fields |
| 8 | `test_max_hops_limit` | Setting max_hops=1 disables second hop |
| 9 | `test_config_disabled` | When enabled=False, engine is not used |
| 10 | `test_empty_first_hop` | Empty first-hop results return empty list |
| 11 | `test_score_merging` | Results from multiple hops are correctly merged and sorted |
| 12 | `test_constructor_defaults` | Default config values are applied correctly |

### Test Stubs

```python
import pytest

from probos.cognitive.spreading_activation import SpreadingActivationEngine


@dataclass
class _FakeAnchorFrame:
    duty_department: str = ""
    channel: str = ""
    trigger_type: str = ""
    trigger_agent: str = ""


@dataclass
class _FakeEpisode:
    id: str = "ep-1"
    anchors: _FakeAnchorFrame | None = None
    agent_ids: list[str] = field(default_factory=list)


@dataclass
class _FakeRecallScore:
    episode: _FakeEpisode = field(default_factory=_FakeEpisode)
    composite_score: float = 0.5
    semantic_similarity: float = 0.5
    keyword_hits: int = 0
    trust_weight: float = 0.5
    hebbian_weight: float = 0.5
    recency_weight: float = 0.5
    anchor_confidence: float = 0.5
    tcm_similarity: float = 0.0


class _FakeEpisodicMemory:
    def __init__(self, weighted_results=None, anchor_results=None):
        self._weighted = weighted_results or []
        self._anchor = anchor_results or []

    async def recall_weighted(self, agent_id, query, **kwargs):
        return self._weighted

    async def recall_by_anchor_scored(self, **kwargs):
        return self._anchor


@pytest.fixture
def engine():
    return SpreadingActivationEngine()
```

---

## Targeted Test Commands

After Section 1 (Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad604_spreading_activation.py -v -k "config or constructor"
```

After Section 2 (SpreadingActivationEngine):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad604_spreading_activation.py -v
```

After Section 3 (CognitiveAgent integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad604_spreading_activation.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-604 Spreading Activation — CLOSED`
- **docs/development/roadmap.md:** Update the AD-604 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-604: Spreading Activation / Multi-Hop Retrieval. First-hop semantic recall
  seeds second-hop anchor-based queries using extracted metadata (department,
  channel, trigger_type, trigger_agent). Hop decay (0.6x) and deduplication
  prevent score inflation. Integrated with CAUSAL question type from AD-602.
  No graph database — uses existing EpisodicMemory recall methods.
  ```

---

## Scope Boundaries

**DO:**
- Create `spreading_activation.py` with SpreadingActivationEngine.
- Add SpreadingActivationConfig to config.py and wire into SystemConfig.
- Lazy-init engine in CognitiveAgent, use for CAUSAL queries.
- Deduplicate and decay second-hop scores.
- Write all 12 tests.

**DO NOT:**
- Add a graph database.
- Use attention-based activation spreading.
- Support more than 2 hops (diminishing returns, deferred).
- Refactor the existing recall flow or anchor recall methods.
- Modify existing tests.
- Add API endpoints or HXI dashboard panels.
- Add numpy, scipy, or other heavy dependencies.
