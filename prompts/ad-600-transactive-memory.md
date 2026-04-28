# AD-600: Transactive Memory — Cross-Agent Expertise Routing

**Status:** Ready for builder
**Scope:** New file + integration edits (~250 lines new, ~40 lines edits)
**Depends on:** AD-531 (episode clustering), AD-462e (OracleService)

**Acceptance Criteria:**
- All 14 tests pass
- No new lint errors
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Summary

OracleService queries all 3 knowledge tiers across all agent shards — O(N) per query for N=55 agents. No model of which agents know what topics. SocialMemoryService broadcasts "does anyone remember?" to everyone.

This AD adds an `ExpertiseDirectory` that tracks which agents are expert on which topics, built from dream-cycle clustering. OracleService uses it to narrow queries to the top-k most relevant agent shards instead of scanning all.

Key capabilities:
1. `ExpertiseDirectory` — in-memory directory mapping agents to their expertise topics with confidence scores.
2. Dream integration — after episode clustering (Step 6), extract topics from cluster centroids and update expertise profiles.
3. Oracle integration — OracleService uses expertise routing to select top-k agent shards for episodic tier queries.
4. Time decay — expertise confidence decays each dream cycle to prevent stale profiles.

## Architecture

```
DreamingEngine (Step 6)
    │
    ├── cluster_episodes() → EpisodeClusters
    │
    ▼
ExpertiseDirectory.build_from_clusters(agent_id, clusters)
    ├── Extract topics from cluster intent_types + anchor_summary
    ├── Score by cluster.success_rate * cluster.episode_count
    └── Store in {agent_id: ExpertiseProfile}

OracleService.query(query_text, agent_id=...)
    │
    ▼
ExpertiseDirectory.query_experts(topic, top_k=3)
    ├── Keyword match topic against all profiles
    ├── Return ranked ExpertMatch list
    └── OracleService scans only top-k agent shards
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/expertise_directory.py` | **NEW** — ExpertiseDirectory, ExpertiseProfile, ExpertMatch |
| `src/probos/config.py` | Add ExpertiseConfig + wire into SystemConfig |
| `src/probos/cognitive/oracle_service.py` | Add optional `expertise_directory` parameter, use for shard selection |
| `src/probos/cognitive/dreaming.py` | After Step 6 clustering, call `build_from_clusters()` |
| `src/probos/startup/cognitive_services.py` | Create ExpertiseDirectory, pass to OracleService |
| `src/probos/startup/dreaming.py` | Pass ExpertiseDirectory to DreamingEngine |
| `tests/test_ad600_transactive_memory.py` | **NEW** — 14 tests |

---

## Implementation

### Section 1: ExpertiseConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `ConsultationConfig` (around line 800):

```python
class ExpertiseConfig(BaseModel):
    """AD-600: Transactive Memory expertise directory configuration."""

    enabled: bool = True
    max_topics_per_agent: int = 50
    min_confidence: float = 0.1
    decay_rate: float = 0.95
    top_k_experts: int = 3
```

Wire into `SystemConfig` (after the `consultation` field, around line 1343):

```python
    expertise: ExpertiseConfig = ExpertiseConfig()  # AD-600
```

### Section 2: ExpertiseDirectory

**File:** `src/probos/cognitive/expertise_directory.py` (NEW)

```python
"""AD-600: Transactive Memory — Cross-Agent Expertise Routing.

In-memory directory tracking which agents are expert on which topics.
Built from dream-cycle clustering. Used by OracleService to narrow
queries to top-k relevant agent shards instead of scanning all N agents.

No persistence — profiles are rebuilt from dream cycles on each boot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExpertiseProfile:
    """An agent's expertise profile: topics they know about."""

    agent_id: str
    department: str = ""
    topics: dict[str, float] = field(default_factory=dict)  # topic -> confidence (0.0-1.0)


@dataclass
class ExpertMatch:
    """A ranked match from querying the expertise directory."""

    agent_id: str
    department: str
    confidence: float
    topic_match: str


class ExpertiseDirectory:
    """In-memory directory of agent expertise, built from dream clustering.

    **Builder:** Config is always provided via Pydantic defaults. Do NOT add in-class fallback defaults.

    Parameters
    ----------
    config : ExpertiseConfig
        Configuration (always provided — Pydantic provides defaults).
    """

    def __init__(self, config: Any) -> None:
        self._max_topics: int = config.max_topics_per_agent
        self._min_confidence: float = config.min_confidence
        self._decay_rate: float = config.decay_rate
        self._top_k: int = config.top_k_experts

        # {agent_id: ExpertiseProfile}
        self._profiles: dict[str, ExpertiseProfile] = {}

    def update_profile(
        self,
        agent_id: str,
        topics: list[str],
        confidence: float,
        *,
        department: str = "",
    ) -> None:
        """Update an agent's expertise profile with new topics.

        If the agent has no profile yet, one is created. Topics are
        merged — existing topics get max(old, new) confidence. If topics
        exceed max_topics, lowest-confidence topics are pruned.

        Parameters
        ----------
        agent_id : str
            The agent whose profile to update.
        topics : list[str]
            Topic strings to add/update.
        confidence : float
            Confidence score (0.0-1.0) for these topics.
        department : str
            Optional department for enrichment.
        """
        if not topics:
            return

        profile = self._profiles.get(agent_id)
        if profile is None:
            profile = ExpertiseProfile(agent_id=agent_id, department=department)
            self._profiles[agent_id] = profile

        if department and not profile.department:
            profile.department = department

        for topic in topics:
            topic_lower = topic.lower().strip()
            if not topic_lower:
                continue
            existing = profile.topics.get(topic_lower, 0.0)
            profile.topics[topic_lower] = max(existing, confidence)

        # Prune to max_topics — keep highest-confidence entries
        if len(profile.topics) > self._max_topics:
            sorted_topics = sorted(
                profile.topics.items(), key=lambda kv: kv[1], reverse=True
            )
            profile.topics = dict(sorted_topics[: self._max_topics])

        # Filter below min_confidence
        profile.topics = {
            t: c for t, c in profile.topics.items() if c >= self._min_confidence
        }

    def query_experts(
        self, topic: str, top_k: int | None = None
    ) -> list[ExpertMatch]:
        """Return ranked agents most likely to have knowledge on a topic.

        Matching is keyword-based: each word in the query is checked
        against each topic string in each agent's profile. The best
        per-agent match confidence is used for ranking.

        Parameters
        ----------
        topic : str
            The topic to search for.
        top_k : int or None
            Max results. Defaults to config top_k_experts.

        Returns
        -------
        list[ExpertMatch]
            Ranked by confidence descending.
        """
        if not topic:
            return []

        k = top_k if top_k is not None else self._top_k
        topic_lower = topic.lower().strip()
        topic_words = set(topic_lower.split())

        matches: list[ExpertMatch] = []
        for profile in self._profiles.values():
            best_confidence = 0.0
            best_topic = ""
            for prof_topic, conf in profile.topics.items():
                # Exact substring match
                if topic_lower in prof_topic or prof_topic in topic_lower:
                    if conf > best_confidence:
                        best_confidence = conf
                        best_topic = prof_topic
                    continue
                # Word overlap match (partial)
                prof_words = set(prof_topic.split())
                overlap = topic_words & prof_words
                if overlap:
                    partial_conf = conf * (len(overlap) / max(len(topic_words), 1))
                    if partial_conf > best_confidence:
                        best_confidence = partial_conf
                        best_topic = prof_topic

            if best_confidence >= self._min_confidence:
                matches.append(ExpertMatch(
                    agent_id=profile.agent_id,
                    department=profile.department,
                    confidence=best_confidence,
                    topic_match=best_topic,
                ))

        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches[:k]

    def build_from_clusters(
        self,
        agent_id: str,
        clusters: list[Any],
        *,
        department: str = "",
    ) -> int:
        """Extract topics from episode clusters and update the agent's profile.

        Called during dream consolidation after Step 6 (clustering).
        Topics are extracted from cluster intent_types and anchor_summary
        fields. Confidence is derived from cluster success_rate weighted
        by episode count.

        Parameters
        ----------
        agent_id : str
            The dreaming agent's ID.
        clusters : list[EpisodeCluster]
            Clusters from the dream cycle.
        department : str
            The agent's department for profile enrichment.

        Returns
        -------
        int
            Number of topics extracted.
        """
        topics_added = 0
        for cluster in clusters:
            # Extract topics from intent_types
            intent_types = cluster.intent_types
            if not intent_types:
                continue

            # Confidence = success_rate * normalized episode count
            success_rate = cluster.success_rate
            episode_count = cluster.episode_count
            # Normalize: more episodes = higher confidence, capped at 1.0
            count_factor = min(episode_count / 10.0, 1.0)
            confidence = success_rate * 0.7 + count_factor * 0.3

            self.update_profile(
                agent_id,
                intent_types,
                confidence,
                department=department,
            )
            topics_added += len(intent_types)

            # Also extract from anchor_summary if available
            anchor_summary = cluster.anchor_summary
            if anchor_summary:
                departments = anchor_summary.get("departments", [])
                if departments and isinstance(departments, list):
                    self.update_profile(
                        agent_id,
                        [f"dept:{d}" for d in departments],
                        confidence * 0.5,  # Lower confidence for department topics
                        department=department,
                    )
                    topics_added += len(departments)

        logger.debug(
            "AD-600: Built expertise profile for %s — %d topics from %d clusters",
            agent_id, topics_added, len(clusters),
        )
        return topics_added

    def decay_profiles(self, factor: float | None = None) -> int:
        """Decay all topic confidences by a multiplicative factor.

        Called at the start of each dream cycle to prevent stale profiles.
        Topics that drop below min_confidence are removed.

        Parameters
        ----------
        factor : float or None
            Decay multiplier (0.0-1.0). Defaults to config decay_rate.

        Returns
        -------
        int
            Number of topics removed due to decay below threshold.
        """
        decay = factor if factor is not None else self._decay_rate
        removed = 0
        for profile in self._profiles.values():
            decayed_topics: dict[str, float] = {}
            for topic, conf in profile.topics.items():
                new_conf = conf * decay
                if new_conf >= self._min_confidence:
                    decayed_topics[topic] = new_conf
                else:
                    removed += 1
            profile.topics = decayed_topics

        # Remove empty profiles
        empty_ids = [aid for aid, p in self._profiles.items() if not p.topics]
        for aid in empty_ids:
            del self._profiles[aid]

        return removed

    @property
    def profile_count(self) -> int:
        """Number of agents with expertise profiles."""
        return len(self._profiles)

    def get_profile(self, agent_id: str) -> ExpertiseProfile | None:
        """Get a specific agent's expertise profile."""
        return self._profiles.get(agent_id)

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        return {
            "profile_count": self.profile_count,
            "total_topics": sum(
                len(p.topics) for p in self._profiles.values()
            ),
            "profiles": {
                aid: {
                    "department": p.department,
                    "topic_count": len(p.topics),
                    "top_topics": sorted(
                        p.topics.items(), key=lambda kv: kv[1], reverse=True
                    )[:5],
                }
                for aid, p in self._profiles.items()
            },
        }
```

### Section 3: OracleService Integration

**File:** `src/probos/cognitive/oracle_service.py`

#### 3a: Constructor parameter

Add an optional `expertise_directory` parameter to the `OracleService.__init__()` method. Find the constructor and add after the last existing parameter:

```python
        expertise_directory: Any = None,  # AD-600: transactive memory routing
```

Store it:

```python
        self._expertise_directory = expertise_directory
```

#### 3b: Use in query method

In the `query()` method, before the episodic tier query, add expertise routing logic. Find the section where episodic memory is queried (search for `episodic` in the method body). Before the episodic query, add:

```python
            # AD-600: Narrow episodic search to expert agent shards when available
            _target_agent_ids: list[str] | None = None
            if self._expertise_directory and query_text:
                try:
                    expert_matches = self._expertise_directory.query_experts(
                        query_text, top_k=k_per_tier
                    )
                    if expert_matches:
                        _target_agent_ids = [m.agent_id for m in expert_matches]
                        logger.debug(
                            "AD-600: Expertise routing — querying %d expert shards for '%s'",
                            len(_target_agent_ids), query_text[:50],
                        )
                except Exception:
                    logger.warning("AD-600: Expertise routing failed, falling back to full scan", exc_info=True)
```

**Builder:** If the episodic query already uses `agent_id` as a filter, keep it — the expertise routing is additive. If `_target_agent_ids` is populated AND the caller did not specify `agent_id`, use the first target as the agent scope. If the caller did specify `agent_id`, skip expertise routing (the caller already knows which shard to query). The intent is to narrow the search space, not override explicit requests.

### Section 4: DreamingEngine Integration

**File:** `src/probos/cognitive/dreaming.py`

#### 4a: Constructor parameter

Add an optional `expertise_directory` parameter to `DreamingEngine.__init__()`:

```python
        expertise_directory: Any = None,  # AD-600: transactive memory
```

Store it:

```python
        self._expertise_directory = expertise_directory
```

#### 4b: Dream cycle integration

After Step 6 (episode clustering) completes and before Step 7, add expertise profile update. Search for `Step 7: Procedure extraction` and add before it:

```python
        # Step 6b: Update expertise directory (AD-600)
        if self._expertise_directory and clusters:
            try:
                self._expertise_directory.decay_profiles()
                topics_added = self._expertise_directory.build_from_clusters(
                    agent_id=self._agent_id,
                    clusters=clusters,
                    department=self._get_department(self._agent_id) if self._get_department else "",
                )
                logger.debug(
                    "Step 6b: Updated expertise profile — %d topics from %d clusters",
                    topics_added, len(clusters),
                )
            except Exception:
                logger.debug("Step 6b expertise update failed (non-critical)", exc_info=True)
```

**Builder:** `self._get_department` may not exist as a stored callable. Check the constructor — it may be named `get_department` (the parameter in the existing constructor). Use whatever name is used in the constructor. If no department resolver exists, pass `department=""`.

### Section 5: Startup Wiring

**File:** `src/probos/startup/cognitive_services.py`

#### 5a: Create ExpertiseDirectory

After the OracleService initialization block (around line 417), add:

```python
    # AD-600: Transactive Memory expertise directory
    expertise_directory = None
    if config.expertise.enabled:
        try:
            from probos.cognitive.expertise_directory import ExpertiseDirectory as _ExpertiseDirectory

            expertise_directory = _ExpertiseDirectory(config=config.expertise)
            logger.info("AD-600: ExpertiseDirectory initialized")
        except Exception as e:
            logger.warning("AD-600: ExpertiseDirectory failed to start: %s — continuing without", e)
            expertise_directory = None
```

#### 5b: Pass to OracleService

Update the OracleService constructor call to include:

```python
            expertise_directory=expertise_directory,  # AD-600
```

#### 5c: Return in result

Add `expertise_directory` to `CognitiveServicesResult` in `src/probos/startup/results.py`:

```python
    expertise_directory: Any = None  # AD-600
```

And add to the return statement in `init_cognitive_services`:

```python
        expertise_directory=expertise_directory,  # AD-600
```

**File:** `src/probos/startup/dreaming.py`

#### 5d: Pass to DreamingEngine

Update the `DreamingEngine` constructor call in `init_dreaming` to include the expertise directory. The expertise directory comes from `CognitiveServicesResult`. Check how other results are accessed (e.g., `records_store=records_store`) and follow the same pattern:

```python
            expertise_directory=expertise_directory,  # AD-600
```

**Builder:** The expertise_directory must be passed through from the cognitive services result to the dreaming phase. Check how `records_store` or `activation_tracker` flow from cognitive_services to dreaming — follow the same pattern.

---

## Tests

**File:** `tests/test_ad600_transactive_memory.py` (NEW)

All tests use `pytest` + `pytest-asyncio`. Use `_Fake*` stubs, not complex mock chains.

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_update_profile_creates_new` | First update for an agent creates a new ExpertiseProfile |
| 2 | `test_update_profile_merges_topics` | Subsequent updates merge topics, keeping max confidence |
| 3 | `test_query_experts_ranked` | query_experts returns matches ranked by confidence descending |
| 4 | `test_query_experts_empty` | query_experts with no matching topic returns empty list |
| 5 | `test_build_from_clusters` | build_from_clusters extracts topics from cluster intent_types |
| 6 | `test_decay_profiles` | decay_profiles reduces confidence, removes below threshold |
| 7 | `test_max_topics_cap` | Profiles exceeding max_topics prune lowest-confidence entries |
| 8 | `test_min_confidence_filter` | Topics below min_confidence are not stored |
| 9 | `test_department_enrichment` | Department is set from first update call |
| 10 | `test_oracle_uses_expertise` | OracleService with expertise_directory narrows episodic query (integration) |
| 11 | `test_oracle_fallback_full_scan` | OracleService without expertise_directory does full scan |
| 12 | `test_config_disabled` | When expertise.enabled=False, directory is not created at startup |
| 13 | `test_multiple_topics_per_agent` | Agent can have many topics, all queryable |
| 14 | `test_expert_match_ordering` | ExpertMatch results are ordered by confidence descending, limited to top_k |

### Test Stubs

```python
import pytest

from probos.cognitive.expertise_directory import (
    ExpertiseDirectory,
    ExpertiseProfile,
    ExpertMatch,
)


@dataclass
class _FakeCluster:
    """Stub for EpisodeCluster."""
    cluster_id: str = "c1"
    intent_types: list[str] = field(default_factory=list)
    success_rate: float = 0.8
    episode_count: int = 5
    anchor_summary: dict = field(default_factory=dict)
    is_success_dominant: bool = True
    is_failure_dominant: bool = False


@pytest.fixture
def _fake_config():
    """Minimal config stub matching ExpertiseConfig fields."""
    @dataclass
    class _Cfg:
        max_topics_per_agent: int = 50
        min_confidence: float = 0.1
        decay_rate: float = 0.95
        top_k_experts: int = 3
    return _Cfg()


@pytest.fixture
def directory(_fake_config):
    return ExpertiseDirectory(config=_fake_config)
```

---

## Targeted Test Commands

After Section 1 (Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad600_transactive_memory.py -v -k "config"
```

After Section 2 (ExpertiseDirectory):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad600_transactive_memory.py -v
```

After Section 3-5 (Integration + Startup):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad600_transactive_memory.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_oracle_service.py -v -x
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-600 Transactive Memory — CLOSED`
- **docs/development/roadmap.md:** Update the AD-600 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-600: Transactive Memory. In-memory ExpertiseDirectory maps agents to
  topics with confidence scores, built from dream-cycle clustering. OracleService
  uses expertise routing to select top-k agent shards instead of O(N) full scan.
  Profiles decay each dream cycle. No persistence — rebuilt on boot. Unlocks
  AD-604 (Spreading Activation second-hop routing).
  ```

---

## Scope Boundaries

**DO:**
- Create `expertise_directory.py` with ExpertiseDirectory, ExpertiseProfile, ExpertMatch.
- Add ExpertiseConfig to config.py and wire into SystemConfig.
- Add optional `expertise_directory` parameter to OracleService for shard selection.
- Add optional `expertise_directory` parameter to DreamingEngine, call `build_from_clusters()` after Step 6.
- Wire ExpertiseDirectory in startup (create, pass to OracleService and DreamingEngine).
- Write all 14 tests.

**DO NOT:**
- Add SQLite persistence (rebuilt from dream cycles each boot).
- Use LLM-based topic extraction (use cluster intent_types and anchor_summary).
- Broadcast expertise profiles to Ward Room.
- Modify episode clustering logic.
- Change DreamReport fields (no new fields needed).
- Add API endpoints or HXI dashboard panels.
- Modify existing tests.
