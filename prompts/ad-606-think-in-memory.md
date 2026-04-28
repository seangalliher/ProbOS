# AD-606: Think-in-Memory — Evolved Thought Storage

**Status:** Ready for builder
**Scope:** New file + integration edits (~180 lines new, ~25 lines edits)
**Depends on:** AD-669 (Working Memory conclusions), AD-567a (AnchorFrame)

**Acceptance Criteria:**
- All 10 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Summary

Agent reasoning produces conclusions that are communicated (Ward Room) or acted upon (intents) but never stored as first-class episodic entries. Pre-reasoned conclusions ("evolved thoughts") could be stored for future recall, avoiding re-reasoning from raw observations.

This AD adds a `ThoughtStore` that persists important conclusions from working memory as thought episodes in EpisodicMemory. These episodes use `source=MemorySource.REFLECTION` and a `channel="thought"` anchor, making them distinguishable from direct experience but naturally included in standard recall.

Key capabilities:
1. `ThoughtStore` — creates and stores thought episodes from working memory conclusions.
2. Thought types — "conclusion", "hypothesis", "observation_synthesis", "pattern_recognition".
3. Evidence linking — thought episodes reference the source episode IDs that led to the conclusion.
4. Importance threshold — only conclusions above a configurable importance threshold are persisted.

## Architecture

```
CognitiveAgent.decide() produces action
    │
    ├── Working memory records ConclusionEntry (AD-669)
    │
    ▼
ThoughtStore.store_thought(agent_id, thought, thought_type, evidence_episode_ids, importance)
    │
    ├── Check importance >= min_importance threshold
    ├── Check max_thoughts_per_cycle cap
    ├── Create Episode with:
    │   ├── source = MemorySource.REFLECTION
    │   ├── anchors.channel = "thought"
    │   ├── anchors.trigger_type = thought_type
    │   └── user_input = thought text
    │
    ▼
EpisodicMemory.store(episode)
    │
    └── Thought is now in standard recall pool
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/thought_store.py` | **NEW** — ThoughtStore class |
| `src/probos/config.py` | Add ThoughtStoreConfig + wire into SystemConfig |
| `src/probos/cognitive/cognitive_agent.py` | After decide(), check conclusions and store thoughts |
| `tests/test_ad606_think_in_memory.py` | **NEW** — 10 tests |

---

## Implementation

### Section 1: ThoughtStoreConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `SpreadingActivationConfig` (or after the last cognitive config):

```python
class ThoughtStoreConfig(BaseModel):
    """AD-606: Think-in-Memory thought storage configuration."""

    enabled: bool = True
    min_importance: int = 5
    max_thoughts_per_cycle: int = 3
```

Wire into `SystemConfig`:

```python
    thought_store: ThoughtStoreConfig = ThoughtStoreConfig()  # AD-606
```

### Section 2: ThoughtStore

**File:** `src/probos/cognitive/thought_store.py` (NEW)

```python
"""AD-606: Think-in-Memory — Evolved Thought Storage.

Persists important conclusions from working memory as thought episodes
in EpisodicMemory. Thought episodes use source=MemorySource.REFLECTION
and channel="thought" in their AnchorFrame, making them distinguishable
from direct experience while naturally participating in standard recall.

No LLM dependency — stores the raw conclusion text as the episode.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Valid thought types
THOUGHT_TYPES: frozenset[str] = frozenset({
    "conclusion",
    "hypothesis",
    "observation_synthesis",
    "pattern_recognition",
})


class ThoughtStore:
    """Stores evolved thoughts as episodic memory entries.

    Parameters
    ----------
    episodic_memory : EpisodicMemory or None
        The episodic memory instance for storing thought episodes.
    config : ThoughtStoreConfig-like or None
        Configuration. If None, uses hardcoded defaults.
    """

    def __init__(
        self,
        episodic_memory: Any = None,
        config: Any = None,
    ) -> None:
        self._episodic_memory = episodic_memory

        if config is not None:
            self._min_importance: int = config.min_importance
            self._max_per_cycle: int = config.max_thoughts_per_cycle
        else:
            self._min_importance = 5
            self._max_per_cycle = 3

        # Track thoughts stored in current cognitive cycle
        self._cycle_count: int = 0
        self._cycle_correlation_id: str = ""

    def reset_cycle(self, correlation_id: str = "") -> None:
        """Reset the per-cycle thought counter.

        Call at the start of each cognitive cycle (perceive/decide/act).

        Parameters
        ----------
        correlation_id : str
            The correlation ID for the current cognitive cycle.
        """
        self._cycle_count = 0
        self._cycle_correlation_id = correlation_id

    async def store_thought(
        self,
        agent_id: str,
        thought: str,
        thought_type: str,
        *,
        evidence_episode_ids: list[str] | None = None,
        importance: int = 6,
        correlation_id: str = "",
    ) -> Any | None:
        """Create and store a thought episode in episodic memory.

        Parameters
        ----------
        agent_id : str
            The thinking agent's ID.
        thought : str
            The thought/conclusion text.
        thought_type : str
            One of: "conclusion", "hypothesis", "observation_synthesis",
            "pattern_recognition".
        evidence_episode_ids : list[str] or None
            Episode IDs that led to this thought (provenance).
        importance : int
            Importance score (1-10). Must meet min_importance threshold.
        correlation_id : str
            Cognitive cycle correlation ID.

        Returns
        -------
        Episode or None
            The stored episode, or None if filtered out.
        """
        if not self._episodic_memory:
            logger.debug("AD-606: No episodic memory — thought not stored")
            return None

        if not thought or not thought.strip():
            return None

        # Validate thought type
        if thought_type not in THOUGHT_TYPES:
            logger.warning(
                "AD-606: Unknown thought type '%s' from %s — defaulting to 'conclusion'",
                thought_type, agent_id,
            )
            thought_type = "conclusion"

        # Importance threshold
        if importance < self._min_importance:
            logger.debug(
                "AD-606: Thought below importance threshold (%d < %d) — not stored",
                importance, self._min_importance,
            )
            return None

        # Per-cycle cap
        if self._cycle_count >= self._max_per_cycle:
            logger.debug(
                "AD-606: Max thoughts per cycle reached (%d) — not stored",
                self._max_per_cycle,
            )
            return None

        # Build Episode
        from probos.types import Episode, AnchorFrame, MemorySource

        anchor = AnchorFrame(
            channel="thought",
            trigger_type=thought_type,
        )

        evidence = evidence_episode_ids or []

        episode = Episode(
            id=uuid.uuid4().hex,
            timestamp=time.time(),
            user_input=thought,
            agent_ids=[agent_id],
            source=MemorySource.REFLECTION.value,
            anchors=anchor,
            importance=importance,
            correlation_id=correlation_id or self._cycle_correlation_id,
            outcomes=[{
                "thought_type": thought_type,
                "evidence_episode_ids": evidence,
            }],
        )

        try:
            await self._episodic_memory.store(episode)
            self._cycle_count += 1
            logger.debug(
                "AD-606: Stored thought episode %s — type=%s, importance=%d, agent=%s",
                episode.id, thought_type, importance, agent_id,
            )
            return episode
        except Exception:
            logger.warning(
                "AD-606: Failed to store thought episode for %s",
                agent_id, exc_info=True,
            )
            return None

    async def recall_thoughts(
        self,
        agent_id: str,
        query: str,
        *,
        k: int = 5,
        trust_network: Any = None,
        hebbian_router: Any = None,
    ) -> list[Any]:
        """Recall thought episodes specifically.

        Uses anchor-scored recall with channel="thought" filter to
        retrieve only thought episodes.

        Parameters
        ----------
        agent_id : str
            The agent whose thoughts to recall.
        query : str
            Semantic query for matching.
        k : int
            Max results to return.
        trust_network : TrustNetwork or None
            For salience-weighted scoring.
        hebbian_router : HebbianRouter or None
            For salience-weighted scoring.

        Returns
        -------
        list[RecallScore]
            Thought episodes matching the query.
        """
        if not self._episodic_memory or not query:
            return []

        try:
            results = await self._episodic_memory.recall_by_anchor_scored(
                agent_id=agent_id,
                channel="thought",
                k=k,
                trust_network=trust_network,
                hebbian_router=hebbian_router,
            )
            return results
        except Exception:
            logger.debug("AD-606: Thought recall failed", exc_info=True)
            return []

    @property
    def cycle_thought_count(self) -> int:
        """Number of thoughts stored in the current cognitive cycle."""
        return self._cycle_count
```

### Section 3: CognitiveAgent Integration

**File:** `src/probos/cognitive/cognitive_agent.py`

#### 3a: Instance variable

In `__init__`, after the `self._spreading_activation` line (added by AD-604), add:

```python
        # AD-606: Think-in-Memory thought store
        self._thought_store: Any = None
```

#### 3b: Thought storage after decide

After `decide()` produces an action, check working memory for conclusions and store important ones as thoughts. Find the location in the cognitive cycle where `decide()` has returned and working memory conclusions may exist.

**Builder:** Search for where `record_conclusion` is called or where `decide()` returns in the `perceive -> decide -> act` lifecycle. The thought storage should happen after `decide()` and before `act()`. Add:

```python
        # AD-606: Store important conclusions as thought episodes
        if self._thought_store is None and self._runtime:
            try:
                from probos.cognitive.thought_store import ThoughtStore
                _ts_config = None
                if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'thought_store'):
                    _ts_config = self._runtime.config.thought_store
                    if not _ts_config.enabled:
                        self._thought_store = False  # sentinel: disabled
                if self._thought_store is None:
                    em = getattr(self._runtime, 'episodic_memory', None)
                    self._thought_store = ThoughtStore(
                        episodic_memory=em,
                        config=_ts_config,
                    )
            except Exception:
                self._thought_store = False
                logger.debug("AD-606: ThoughtStore unavailable", exc_info=True)

        if self._thought_store and self._thought_store is not False:
            try:
                wm = getattr(self, '_working_memory', None)
                if wm:
                    conclusions = wm.get_conclusions(limit=3)
                    correlation_id = getattr(self, '_current_correlation_id', "") or ""
                    self._thought_store.reset_cycle(correlation_id)
                    for conc in conclusions:
                        await self._thought_store.store_thought(
                            agent_id=self.id,
                            thought=conc.summary,
                            thought_type=self._map_conclusion_to_thought_type(conc),
                            importance=6,  # Default moderate importance
                            correlation_id=correlation_id,
                        )
            except Exception:
                logger.debug("AD-606: Thought storage failed (non-critical)", exc_info=True)
```

#### 3c: Conclusion-to-thought-type mapping

Add a private helper method:

```python
    @staticmethod
    def _map_conclusion_to_thought_type(conclusion: Any) -> str:
        """AD-606: Map a ConclusionEntry type to a thought type string."""
        ct = getattr(conclusion, 'conclusion_type', None)
        if ct is None:
            return "conclusion"
        ct_value = ct.value if hasattr(ct, 'value') else str(ct)
        mapping = {
            "decision": "conclusion",
            "observation": "observation_synthesis",
            "escalation": "conclusion",
            "completion": "conclusion",
        }
        return mapping.get(ct_value, "conclusion")
```

**Builder:** The `get_conclusions` method on AgentWorkingMemory returns `list[ConclusionEntry]`. Verify the method name by searching `agent_working_memory.py` for `get_conclusions` or `recent_conclusions`. Use whatever method name exists. If no such method exists, use `_conclusions` directly (the deque attribute).

---

## Tests

**File:** `tests/test_ad606_think_in_memory.py` (NEW)

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_store_thought_creates_episode` | store_thought returns an Episode with correct fields |
| 2 | `test_store_thought_reflection_source` | Stored episode has source=MemorySource.REFLECTION |
| 3 | `test_thought_episode_channel` | Stored episode has anchors.channel="thought" |
| 4 | `test_thought_types_validated` | Valid thought types are accepted, unknown defaults to "conclusion" |
| 5 | `test_importance_threshold` | Thoughts below min_importance are not stored |
| 6 | `test_max_thoughts_per_cycle` | After max_thoughts_per_cycle, further thoughts are rejected |
| 7 | `test_reset_cycle` | reset_cycle resets the counter, allowing new thoughts |
| 8 | `test_evidence_linking` | evidence_episode_ids appear in episode outcomes |
| 9 | `test_config_disabled` | When enabled=False, thought store is not used |
| 10 | `test_recall_thoughts` | recall_thoughts uses anchor filter channel="thought" |

### Test Stubs

```python
import pytest
import time

from probos.cognitive.thought_store import ThoughtStore, THOUGHT_TYPES
from probos.types import MemorySource


class _FakeEpisodicMemory:
    def __init__(self):
        self.stored: list = []

    async def store(self, episode):
        self.stored.append(episode)

    async def recall_by_anchor_scored(self, **kwargs):
        return [e for e in self.stored if getattr(getattr(e, 'anchors', None), 'channel', '') == kwargs.get('channel', '')]


@pytest.fixture
def fake_memory():
    return _FakeEpisodicMemory()


@pytest.fixture
def thought_store(fake_memory):
    return ThoughtStore(episodic_memory=fake_memory)
```

---

## Targeted Test Commands

After Section 1 (Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad606_think_in_memory.py -v -k "config"
```

After Section 2 (ThoughtStore):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad606_think_in_memory.py -v
```

After Section 3 (CognitiveAgent integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad606_think_in_memory.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-606 Think-in-Memory — CLOSED`
- **docs/development/roadmap.md:** Update the AD-606 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-606: Think-in-Memory. ThoughtStore persists important working memory
  conclusions as thought episodes with source=REFLECTION, channel="thought".
  Importance threshold and per-cycle cap prevent noise. Evidence linking
  records provenance. Thoughts participate in standard recall naturally.
  No LLM dependency — stores raw conclusion text.
  ```

---

## Scope Boundaries

**DO:**
- Create `thought_store.py` with ThoughtStore class.
- Add ThoughtStoreConfig to config.py and wire into SystemConfig.
- Lazy-init ThoughtStore in CognitiveAgent, store conclusions after decide().
- Map ConclusionType to thought types.
- Write all 10 tests.

**DO NOT:**
- Use LLM-based thought quality assessment.
- Build thought chains (thought referencing other thoughts).
- Enable cross-agent thought sharing (thoughts are per-agent episodes).
- Add thought-specific recall weighting.
- Modify existing tests.
- Add API endpoints or HXI dashboard panels.
- Add database tables (thoughts are standard Episodes in EpisodicMemory).
