# Build Prompt: AD-541c — Spaced Retrieval Therapy: Active Recall Practice

**Ticket:** AD-541c
**Priority:** Medium (memory strengthening — reinforces genuine memory traces against LLM contamination)
**Scope:** New dream step for active episodic recall practice with spaced repetition scheduling, per-agent sovereign shard practice, SQLite schedule persistence, fast-tier LLM routing, Counselor integration
**Principles Compliance:** Single Responsibility (RetrievalPracticeEngine owns scheduling + scoring), Open/Closed (new dream step, no modification to existing steps), Cloud-Ready Storage (ConnectionFactory protocol for schedule SQLite store), Defense in Depth (AD-541b prevents corruption, AD-541c strengthens genuine traces), DRY (reuse existing EpisodicMemory API + CognitiveProfile pattern + Jaccard similarity)
**Dependencies:** AD-541b (COMPLETE — frozen Episode, write-once guard), AD-503 (COMPLETE — Counselor activation), AD-505 (COMPLETE — Counselor therapeutic intervention), Phase 32 (Cognitive Division of Labor — fast tier for recall tasks)

---

## Context

AD-541b prevents memory corruption (read-only framing, frozen episodes, write-once storage). But prevention alone is insufficient — genuine memory traces can still degrade through disuse while LLM training patterns remain ever-present. AD-541c addresses the complementary problem: **strengthening real memories so they persist above the noise floor of training data.**

**Clinical basis:** Spaced Retrieval Therapy (Camp, 1989; Camp et al., 1996) is the most validated memory intervention for dementia patients — 90%+ retention at 1-week intervals. The core mechanism: active recall strengthens neural pathways more than passive review. Successful recall → extend interval. Failed recall → shorten interval. Over time, memories that matter get reinforced at decreasing cost.

**ProbOS application:** During dream cycles, select high-impact episodes from each agent's sovereign memory shard. Present the episode's context (user_input, dag_summary) but withhold the outcome. Ask the agent to recall what happened. Compare against the stored episode. Score accuracy. Adjust retrieval interval. Persist schedule to SQLite. Surface results to Counselor.

**Token cost mitigation:** This step uses the "fast" LLM tier (Cognitive Division of Labor). Recall is a pattern-matching task, not deep reasoning. Limited to K episodes per agent per cycle (default 3). Gated by config flag (default off).

---

## Architecture

### RetrievalPracticeEngine

New module: `src/probos/cognitive/retrieval_practice.py`

The engine manages:
1. **Per-agent episode selection** — which episodes to practice this cycle per agent (prioritized by impact, filtered by spaced interval)
2. **Recall prompt construction** — present context, withhold outcome, ask for recall
3. **Accuracy scoring** — compare recalled content against stored episode (Jaccard similarity on key terms)
4. **Interval scheduling** — spaced repetition: success → double interval, failure → halve interval
5. **SQLite persistence** — retrieval schedules survive restarts via Cloud-Ready Storage pattern
6. **Result reporting** — feed scores to DreamReport and emit events for Counselor

### Retrieval Schedule

Each episode-agent pair has a retrieval schedule tracked in SQLite, keyed by `{agent_id}:{episode_id}`:

```python
@dataclass
class RetrievalSchedule:
    """Spaced repetition schedule for one episode-agent pair."""
    agent_id: str
    episode_id: str
    interval_hours: float = 24.0  # Current interval — starts at 24h
    last_practiced: float = 0.0   # Timestamp of last practice
    next_due: float = 0.0         # When next practice is due
    consecutive_successes: int = 0 # Streak — drives interval growth
    consecutive_failures: int = 0  # Failure streak — drives interval shrink + Counselor flag
    total_practices: int = 0
    total_successes: int = 0
    recall_accuracy: float = 0.0  # Most recent recall accuracy (0.0–1.0)
    retired: bool = False         # True if interval exceeds max (memory is stable)
```

### Per-Agent Practice

Practice runs per-agent, not system-wide. Each agent practices their own sovereign shard episodes via `episodic_memory.recent_for_agent(agent_id)`. This respects the sovereign memory architecture — agents practice recalling their own experiences, not other agents' memories.

The dream step iterates over all agent IDs found in the dream cycle's episode set and runs practice for each.

### Recall Accuracy Scoring

Use Jaccard similarity (reuse `cognitive/similarity.py`) between the agent's recalled content and the stored episode's `reflection` + outcome summary. This is the same similarity function used by AD-550/551/552 — DRY.

**Scoring tiers:**
- **≥ 0.6** = successful recall — extend interval
- **0.3–0.6** = partial recall — maintain interval
- **< 0.3** = failed recall — shorten interval, flag for Counselor if `consecutive_failures ≥ 3`

### Fast-Tier LLM Routing

Recall practice uses the "fast" LLM tier from CognitiveConfig. The DreamingEngine receives a separate `_retrieval_llm_client` constructed from `config.cognitive.tier_config("fast")` at startup. This keeps recall costs low (pattern matching, not reasoning).

### Dream Step Placement

**Step 11** — after Step 10 (Notebook Quality). End-of-pipeline placement because:
1. Requires LLM calls (most expensive step type)
2. Should not block cheaper analytical steps
3. Results feed into DreamReport which is finalized after all steps

---

## Deliverables

### D1: RetrievalPracticeEngine core

**File:** `src/probos/cognitive/retrieval_practice.py` (NEW)

```python
"""AD-541c: Spaced Retrieval Therapy — Active recall practice during dream cycles.

Strengthens genuine episodic memories through spaced repetition. During dream
cycles, agents actively recall episode outcomes from their sovereign memory
shard (not passively replay). Successful recall extends the practice interval;
failed recall shortens it and flags the episode for Counselor attention.

Schedules persist to SQLite via Cloud-Ready Storage pattern (ConnectionFactory).

Clinical basis: Camp (1989), Camp et al. (1996) — SRT is the most validated
memory intervention, achieving 90%+ retention at 1-week intervals.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.types import Episode

logger = logging.getLogger(__name__)
```

**1a.** `RetrievalSchedule` dataclass as specified above.

**1b.** `RetrievalPracticeResult` dataclass — result of a single practice trial:

```python
@dataclass
class RetrievalPracticeResult:
    """Result of a single recall practice trial."""
    agent_id: str
    episode_id: str
    recall_accuracy: float  # 0.0–1.0 Jaccard similarity
    success: bool           # accuracy >= threshold
    recalled_text: str      # What the agent recalled
    expected_text: str      # What actually happened (episode reflection + outcomes)
    interval_before: float  # Interval before this practice
    interval_after: float   # Interval after adjustment
    practice_number: int    # Nth practice for this episode
```

**1c.** `RetrievalPracticeEngine` class:

```python
class RetrievalPracticeEngine:
    """Spaced Retrieval Therapy engine for dream-time memory strengthening."""

    def __init__(
        self,
        *,
        success_threshold: float = 0.6,
        partial_threshold: float = 0.3,
        initial_interval_hours: float = 24.0,
        max_interval_hours: float = 168.0,  # 7 days — retire after this
        episodes_per_cycle: int = 3,
        counselor_failure_streak: int = 3,
        connection_factory: "ConnectionFactory | None" = None,
        data_dir: str | Path = "",
    ) -> None:
        self._schedules: dict[str, RetrievalSchedule] = {}
        self._success_threshold = success_threshold
        self._partial_threshold = partial_threshold
        self._initial_interval_hours = initial_interval_hours
        self._max_interval_hours = max_interval_hours
        self._episodes_per_cycle = episodes_per_cycle
        self._counselor_failure_streak = counselor_failure_streak
        self._connection_factory = connection_factory
        self._data_dir = Path(data_dir) if data_dir else None
        self._db: DatabaseConnection | None = None
```

**1d.** `select_episodes_for_practice(episodes: list[Episode], agent_id: str) -> list[Episode]` method:

Selection priority (descending):
1. Episodes that are **due for practice** (`next_due ≤ now`) — spaced repetition schedule
2. **New episodes not yet scheduled** — high-impact first (non-empty `trust_deltas` > failed outcomes > DIRECT source > other)
3. Limited to `episodes_per_cycle` (default 3)
4. Skip episodes with `source != "direct"` (only practice firsthand memories)
5. Skip retired schedules
6. Filter to episodes where `agent_id` appears in the episode's `agent_ids` list — sovereign shard boundary

**1e.** `build_recall_prompt(episode: Episode) -> str` method:

Construct a prompt that presents episode context but withholds the outcome:

```python
def build_recall_prompt(self, episode: Episode) -> str:
    """Build a recall prompt — present context, withhold outcome."""
    context_parts = [f"Timestamp: {episode.timestamp}"]
    if episode.user_input:
        context_parts.append(f"Situation: {episode.user_input}")
    if episode.dag_summary:
        intent_types = episode.dag_summary.get("intent_types", [])
        if intent_types:
            context_parts.append(f"Intent types involved: {', '.join(intent_types)}")
        node_count = episode.dag_summary.get("node_count", 0)
        if node_count:
            context_parts.append(f"Agents involved: {node_count}")
    context = "\n".join(context_parts)
    return (
        f"You are practicing active recall of a past experience.\n\n"
        f"=== EPISODE CONTEXT ===\n{context}\n=== END CONTEXT ===\n\n"
        f"Based on this context, recall what happened. What was the outcome? "
        f"What did you observe? What was the result?\n\n"
        f"Respond with a concise summary of what you remember happening."
    )
```

**1f.** `build_expected_text(episode: Episode) -> str` method:

Extract the "ground truth" from the stored episode for comparison:

```python
def build_expected_text(self, episode: Episode) -> str:
    """Extract ground truth text from episode for accuracy comparison."""
    parts = []
    if episode.reflection:
        parts.append(episode.reflection)
    for outcome in episode.outcomes:
        status = outcome.get("status", outcome.get("success", ""))
        intent = outcome.get("intent", "")
        if intent:
            parts.append(f"{intent}: {status}")
    return " ".join(parts) if parts else ""
```

**1g.** `score_recall(recalled_text: str, expected_text: str) -> float` method:

Use Jaccard similarity (from `cognitive/similarity.py`) to score recall accuracy:

```python
def score_recall(self, recalled_text: str, expected_text: str) -> float:
    """Score recall accuracy using Jaccard similarity."""
    if not expected_text:
        return 1.0  # No ground truth to compare — pass by default
    return jaccard_similarity(recalled_text, expected_text)
```

**1h.** `update_schedule(agent_id: str, episode_id: str, accuracy: float) -> RetrievalSchedule` method:

Apply spaced repetition logic:
- `accuracy >= success_threshold` → `consecutive_successes += 1`, `consecutive_failures = 0`, `interval *= 2.0` (double on success)
- `partial_threshold <= accuracy < success_threshold` → maintain interval, reset streaks
- `accuracy < partial_threshold` → `consecutive_failures += 1`, `consecutive_successes = 0`, `interval = max(initial_interval, interval / 2.0)` (halve on failure, floor at initial)
- If `interval > max_interval_hours` → mark `retired = True` (memory is stable, stop practicing)
- Update `next_due = now + interval_hours * 3600`

**1i.** `get_counselor_concerns(agent_id: str | None = None) -> list[RetrievalSchedule]` method:

Return schedules where `consecutive_failures >= counselor_failure_streak` and not retired. If `agent_id` is provided, filter to that agent. If None, return all concerns across all agents.

**1j.** `get_agent_recall_stats(agent_id: str) -> dict[str, Any]` method:

Return aggregate stats for an agent:

```python
{
    "total_scheduled": N,
    "total_practiced": N,
    "total_retired": N,
    "avg_recall_accuracy": float,
    "episodes_at_risk": N,  # consecutive_failures >= counselor_failure_streak
    "practice_sessions_total": N,
}
```

### D2: SQLite schedule persistence

**File:** `src/probos/cognitive/retrieval_practice.py` (same file as D1)

Follow the Cloud-Ready Storage pattern established by TrustNetwork and CounselorProfileStore.

**2a.** Schema constant:

```python
_RETRIEVAL_SCHEMA = """\
CREATE TABLE IF NOT EXISTS retrieval_schedules (
    agent_id   TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    interval_hours REAL NOT NULL DEFAULT 24.0,
    last_practiced REAL NOT NULL DEFAULT 0.0,
    next_due REAL NOT NULL DEFAULT 0.0,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_practices INTEGER NOT NULL DEFAULT 0,
    total_successes INTEGER NOT NULL DEFAULT 0,
    recall_accuracy REAL NOT NULL DEFAULT 0.0,
    retired INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, episode_id)
);
"""
```

**2b.** `async def start(self) -> None` method:

```python
async def start(self) -> None:
    """Initialize SQLite store and load existing schedules."""
    if not self._data_dir:
        return  # In-memory only (tests)
    if self._connection_factory is None:
        from probos.storage.sqlite_factory import default_factory
        self._connection_factory = default_factory
    db_path = str(self._data_dir / "retrieval_practice.db")
    self._db = await self._connection_factory.connect(db_path)
    await self._db.executescript(_RETRIEVAL_SCHEMA)
    await self._db.commit()
    await self._load_schedules()
```

**2c.** `async def _load_schedules(self) -> None` method:

Load all rows from `retrieval_schedules` table into `self._schedules` dict. Key format: `{agent_id}:{episode_id}`.

**2d.** `async def _save_schedule(self, schedule: RetrievalSchedule) -> None` method:

Upsert a single schedule row using `INSERT ... ON CONFLICT(agent_id, episode_id) DO UPDATE SET ...`. Commit after write. Called after each `update_schedule()`.

**2e.** `async def stop(self) -> None` method:

Close the database connection if open.

### D3: Dream Step 11 integration (per-agent)

**File:** `src/probos/cognitive/dreaming.py`

**3a.** Import `RetrievalPracticeEngine` and `RetrievalPracticeResult` at the top.

**3b.** Add to `DreamingEngine.__init__()`:

```python
self._retrieval_practice_engine: RetrievalPracticeEngine | None = None
self._retrieval_llm_client: Any = None  # Fast-tier LLM for recall practice
```

**3c.** Add wiring methods (called from startup):

```python
def set_retrieval_practice_engine(self, engine: RetrievalPracticeEngine) -> None:
    """Wire retrieval practice engine for AD-541c."""
    self._retrieval_practice_engine = engine

def set_retrieval_llm_client(self, client: Any) -> None:
    """Wire fast-tier LLM client for retrieval practice."""
    self._retrieval_llm_client = client
```

**3d.** Add Step 11 method `_step_11_retrieval_practice(episodes, report)`:

```python
async def _step_11_retrieval_practice(
    self, episodes: list[Episode], report: DreamReport
) -> None:
    """Step 11: Active recall practice (Spaced Retrieval Therapy — AD-541c).

    Per-agent sovereign shard practice. Each agent practices recalling their
    own episodes, not other agents' memories.
    """
    if not self.config.active_retrieval_enabled:
        return
    if not self._retrieval_practice_engine:
        return

    engine = self._retrieval_practice_engine
    # Use fast-tier LLM if available, fall back to default
    llm = self._retrieval_llm_client or self._llm_client
    if not llm:
        return

    # Collect unique agent IDs from this cycle's episodes
    agent_ids: set[str] = set()
    for ep in episodes:
        agent_ids.update(ep.agent_ids)
    if not agent_ids:
        return

    all_results: list[RetrievalPracticeResult] = []
    all_concerns: list[RetrievalSchedule] = []

    for agent_id in agent_ids:
        # Select episodes for this agent's practice
        candidates = engine.select_episodes_for_practice(episodes, agent_id)
        if not candidates:
            continue

        for ep in candidates:
            prompt = engine.build_recall_prompt(ep)
            expected = engine.build_expected_text(ep)
            if not expected:
                continue  # No ground truth — skip

            try:
                recalled = await llm(prompt)
            except Exception:
                logger.warning(
                    "SRT: LLM recall failed for agent %s episode %s",
                    agent_id[:8], ep.id[:8],
                )
                continue

            old_interval = engine._schedules.get(
                f"{agent_id}:{ep.id}", RetrievalSchedule(agent_id=agent_id, episode_id=ep.id)
            ).interval_hours

            accuracy = engine.score_recall(recalled, expected)
            schedule = engine.update_schedule(agent_id, ep.id, accuracy)
            success = accuracy >= engine._success_threshold

            result = RetrievalPracticeResult(
                agent_id=agent_id,
                episode_id=ep.id,
                recall_accuracy=accuracy,
                success=success,
                recalled_text=recalled,
                expected_text=expected,
                interval_before=old_interval,
                interval_after=schedule.interval_hours,
                practice_number=schedule.total_practices,
            )
            all_results.append(result)

            logger.info(
                "SRT: Agent %s episode %s recall=%.2f %s (interval=%.0fh, streak=%d)",
                agent_id[:8], ep.id[:8], accuracy,
                "pass" if success else "fail",
                schedule.interval_hours,
                schedule.consecutive_successes if success else -schedule.consecutive_failures,
            )

        # Check for concerns per agent
        concerns = engine.get_counselor_concerns(agent_id)
        all_concerns.extend(concerns)

    # Update DreamReport
    report.retrieval_practices = len(all_results)
    report.retrieval_accuracy = (
        sum(r.recall_accuracy for r in all_results) / len(all_results)
        if all_results else None
    )
    report.retrieval_concerns = len(all_concerns)

    # Emit Counselor concern events if needed
    if all_concerns and self._emit_event_fn:
        # Group concerns by agent
        from collections import defaultdict
        by_agent: dict[str, list[RetrievalSchedule]] = defaultdict(list)
        for c in all_concerns:
            by_agent[c.agent_id].append(c)
        for aid, agent_concerns in by_agent.items():
            self._emit_event_fn(
                EventType.RETRIEVAL_PRACTICE_CONCERN,
                {
                    "agent_id": aid,
                    "episodes_at_risk": len(agent_concerns),
                    "episode_ids": [s.episode_id for s in agent_concerns],
                    "avg_recall_accuracy": (
                        sum(s.recall_accuracy for s in agent_concerns) / len(agent_concerns)
                    ),
                },
            )
```

**3e.** Wire Step 11 into `dream_cycle()` — add the call after Step 10 (notebook quality):

```python
# Step 11: Active recall practice (SRT — AD-541c)
await self._step_11_retrieval_practice(episodes, report)
```

### D4: DreamReport and DreamingConfig additions

**File:** `src/probos/types.py`

**4a.** Add to `DreamReport` after the notebook quality fields:

```python
    # AD-541c: Spaced Retrieval Therapy
    retrieval_practices: int = 0
    retrieval_accuracy: float | None = None
    retrieval_concerns: int = 0  # Episodes with failing recall streaks
```

**File:** `src/probos/config.py`

**4b.** Add to `DreamingConfig`:

```python
    # AD-541c: Spaced Retrieval Therapy
    active_retrieval_enabled: bool = False  # Gated — enable when ready
    retrieval_episodes_per_cycle: int = 3
    retrieval_success_threshold: float = 0.6
    retrieval_partial_threshold: float = 0.3
    retrieval_initial_interval_hours: float = 24.0
    retrieval_max_interval_hours: float = 168.0  # 7 days
    retrieval_counselor_failure_streak: int = 3
```

### D5: Counselor integration

**File:** `src/probos/events.py`

**5a.** Add new EventType:

```python
RETRIEVAL_PRACTICE_CONCERN = "retrieval_practice_concern"
```

**File:** `src/probos/cognitive/counselor.py`

**5b.** Add handler `_on_retrieval_practice_concern(self, event)` in the Counselor:

```python
async def _on_retrieval_practice_concern(self, event: Any) -> None:
    """Handle retrieval practice concern — agent struggling to recall episodes."""
    data = event.get("data", {}) if isinstance(event, dict) else getattr(event, "data", {})
    agent_id = data.get("agent_id", "")
    episodes_at_risk = data.get("episodes_at_risk", 0)
    avg_accuracy = data.get("avg_recall_accuracy", 0.0)

    if not agent_id:
        return

    logger.info(
        "Counselor: Retrieval practice concern for %s — %d episodes at risk (avg accuracy=%.2f)",
        agent_id[:8], episodes_at_risk, avg_accuracy,
    )

    # Update CognitiveProfile if we have one
    profile = self._profiles.get(agent_id)
    if profile:
        profile.retrieval_concerns = episodes_at_risk
        profile.last_retrieval_accuracy = avg_accuracy
```

**5c.** Add fields to `CognitiveProfile`:

```python
    # AD-541c: Retrieval practice tracking
    retrieval_concerns: int = 0
    last_retrieval_accuracy: float = 0.0
```

**5d.** Subscribe to the event in the Counselor's `_subscribe_events()` method (or equivalent event registration block):

```python
EventType.RETRIEVAL_PRACTICE_CONCERN: self._on_retrieval_practice_concern,
```

### D6: Startup wiring (fast-tier LLM + engine construction)

**File:** `src/probos/startup/dreaming.py`

**6a.** In `init_dreaming()`, construct the `RetrievalPracticeEngine` and fast-tier LLM client, then wire both into DreamingEngine:

```python
from probos.cognitive.retrieval_practice import RetrievalPracticeEngine

# After DreamingEngine construction:
if config.dreaming.active_retrieval_enabled:
    retrieval_engine = RetrievalPracticeEngine(
        success_threshold=config.dreaming.retrieval_success_threshold,
        partial_threshold=config.dreaming.retrieval_partial_threshold,
        initial_interval_hours=config.dreaming.retrieval_initial_interval_hours,
        max_interval_hours=config.dreaming.retrieval_max_interval_hours,
        episodes_per_cycle=config.dreaming.retrieval_episodes_per_cycle,
        counselor_failure_streak=config.dreaming.retrieval_counselor_failure_streak,
        data_dir=str(data_dir),  # Same data_dir used by other stores
    )
    await retrieval_engine.start()
    dreaming_engine.set_retrieval_practice_engine(retrieval_engine)

    # Fast-tier LLM client for recall practice (Cognitive Division of Labor)
    # Use config.cognitive.tier_config("fast") to construct a tier-specific client
    # If the main llm_client supports tier routing, pass it directly.
    # Otherwise, construct a separate client from fast tier config.
    dreaming_engine.set_retrieval_llm_client(llm_client)  # Same client — it routes internally via tier_config
```

**6b.** Ensure the `RetrievalPracticeEngine.stop()` is called during shutdown. Add to the shutdown sequence (find where other `.stop()` calls happen):

```python
if hasattr(dreaming_engine, '_retrieval_practice_engine') and dreaming_engine._retrieval_practice_engine:
    await dreaming_engine._retrieval_practice_engine.stop()
```

---

## Scope Exclusions

1. **Counselor therapeutic reminiscence sessions** — **AD-541d** (separate scope). AD-541c surfaces concerns via events; AD-541d acts on them with structured 1:1 therapeutic sessions.
2. **Content hashing for tamper detection** — **AD-541e** (separate scope). Orthogonal to recall practice.
3. **Eviction audit trail** — **AD-541f** (separate scope). Forensic analysis of memory gaps.
4. **memory_integrity_score on CognitiveProfile** — Full composite scoring requires AD-541d's reminiscence findings + AD-541c's recall accuracy + AD-540's provenance scoring. AD-541c adds `retrieval_concerns` and `last_retrieval_accuracy` as partial signals. The composite `memory_integrity_score` is deferred to **AD-541d** which has all three inputs.

---

## Test Requirements (30 tests)

### D1 Tests — RetrievalPracticeEngine core (14 tests)

**File:** `tests/test_ad541c_retrieval_practice.py` (NEW)

1. `test_retrieval_schedule_defaults` — Construct `RetrievalSchedule`, verify defaults (interval=24h, retired=False, etc.).
2. `test_select_episodes_filters_non_direct` — Call `select_episodes_for_practice()` with a mix of DIRECT and SECONDHAND episodes, verify only DIRECT episodes are selected.
3. `test_select_episodes_limits_to_max` — Pass 10 eligible episodes with `episodes_per_cycle=3`, verify exactly 3 returned.
4. `test_select_episodes_prioritizes_trust_deltas` — Pass episodes with and without trust_deltas, verify trust-delta episodes are selected first.
5. `test_select_episodes_due_before_new` — Create schedules with `next_due` in the past, pass those episodes plus new ones, verify due episodes are selected first.
6. `test_select_episodes_skips_retired` — Create a retired schedule, verify its episode is not selected.
7. `test_select_episodes_filters_by_agent_id` — Pass episodes with different `agent_ids`, verify only episodes containing the target agent are selected.
8. `test_build_recall_prompt_contains_context` — Build prompt for an episode with user_input and dag_summary, verify context appears but reflection/outcomes do NOT appear.
9. `test_build_recall_prompt_withholds_outcome` — Build prompt, verify the episode's `reflection` and `outcomes` text does NOT appear in the prompt.
10. `test_build_expected_text_combines_reflection_and_outcomes` — Verify expected text includes both reflection and outcome summaries.
11. `test_score_recall_high_accuracy` — Provide recalled text similar to expected, verify score ≥ 0.6.
12. `test_score_recall_low_accuracy` — Provide unrelated recalled text, verify score < 0.3.
13. `test_update_schedule_success_doubles_interval` — Score ≥ 0.6, verify interval doubles, consecutive_successes increments.
14. `test_update_schedule_failure_halves_interval` — Score < 0.3, verify interval halves (floored at initial), consecutive_failures increments.

### D1 Tests — Extended (4 tests)

15. `test_update_schedule_retires_at_max_interval` — Push interval past max_interval_hours, verify `retired=True`.
16. `test_update_schedule_partial_maintains_interval` — Score between 0.3 and 0.6, verify interval unchanged, streaks reset.
17. `test_get_counselor_concerns_filters_by_agent` — Create concerns for two agents, verify filtering by agent_id returns only that agent's concerns.
18. `test_get_agent_recall_stats` — Create schedules with mixed results, verify stats dict has correct values.

### D2 Tests — SQLite persistence (4 tests)

19. `test_save_and_load_schedules_roundtrip` — Create engine with temp dir, add schedules via `update_schedule()`, stop engine, create new engine with same dir, `start()`, verify schedules loaded match originals.
20. `test_persistence_survives_restart` — Start engine, practice some episodes (update schedules), stop, restart, verify schedules have correct intervals and streaks from before restart.
21. `test_start_without_data_dir_is_memory_only` — Create engine with no `data_dir`, verify `start()` succeeds, schedules work in-memory only.
22. `test_stop_closes_db` — Start engine, stop, verify no errors on double-stop.

### D3 Tests — Dream Step 11 per-agent (4 tests)

23. `test_step_11_skipped_when_disabled` — Set `active_retrieval_enabled=False`, run step, verify no LLM calls made.
24. `test_step_11_skipped_when_no_engine` — Leave `_retrieval_practice_engine=None`, run step, verify no errors.
25. `test_step_11_per_agent_practice` — Enable SRT with episodes from 2 different agents, mock LLM, run step, verify each agent's episodes are practiced separately and `report.retrieval_practices` counts both.
26. `test_step_11_emits_per_agent_concern_events` — Set up a failing agent, run step, verify `RETRIEVAL_PRACTICE_CONCERN` event emitted with correct agent_id.

### D4 Tests — Config and DreamReport (2 tests)

27. `test_dreaming_config_retrieval_defaults` — Construct `DreamingConfig()`, verify `active_retrieval_enabled=False`, `retrieval_episodes_per_cycle=3`, etc.
28. `test_dream_report_retrieval_fields_default` — Construct `DreamReport()`, verify `retrieval_practices=0`, `retrieval_accuracy=None`, `retrieval_concerns=0`.

### D5 Tests — Counselor integration (2 tests)

29. `test_counselor_handles_retrieval_practice_concern` — Fire `RETRIEVAL_PRACTICE_CONCERN` event, verify Counselor updates CognitiveProfile with `retrieval_concerns` and `last_retrieval_accuracy`.
30. `test_cognitive_profile_retrieval_fields` — Construct `CognitiveProfile`, verify `retrieval_concerns=0`, `last_retrieval_accuracy=0.0`.

---

## Validation Checklist

Before marking complete, verify:

- [ ] `RetrievalPracticeEngine` in new `cognitive/retrieval_practice.py` — all methods implemented
- [ ] `select_episodes_for_practice()` filters DIRECT-only, filters by agent_id, respects schedule, limits to K
- [ ] `build_recall_prompt()` presents context but withholds reflection/outcomes
- [ ] `score_recall()` uses Jaccard similarity from `cognitive/similarity.py` — DRY
- [ ] `update_schedule()` implements correct spaced repetition: success doubles, failure halves, retires at max
- [ ] SQLite persistence: `start()` creates table, `_save_schedule()` upserts, `_load_schedules()` restores, `stop()` closes
- [ ] Cloud-Ready Storage: constructor accepts `ConnectionFactory`, falls back to `default_factory`
- [ ] Dream Step 11 iterates per-agent (not system-wide), wired after Step 10 in `dream_cycle()`
- [ ] Step 11 uses `_retrieval_llm_client` (fast tier) with fallback to `_llm_client`
- [ ] Step 11 gated by `active_retrieval_enabled` config
- [ ] Per-agent concern events emitted (grouped by agent_id)
- [ ] `DreamReport` has `retrieval_practices`, `retrieval_accuracy`, `retrieval_concerns` fields
- [ ] `DreamingConfig` has all 7 retrieval config fields with correct defaults
- [ ] `RETRIEVAL_PRACTICE_CONCERN` EventType added to events.py
- [ ] Counselor subscribes to `RETRIEVAL_PRACTICE_CONCERN`, updates CognitiveProfile
- [ ] `CognitiveProfile` has `retrieval_concerns` and `last_retrieval_accuracy` fields
- [ ] Startup wiring in `startup/dreaming.py` — conditionally creates engine + fast-tier client
- [ ] Engine `stop()` called during shutdown
- [ ] All 30 tests pass
- [ ] Existing dream tests still pass (0 regressions)
- [ ] Existing Counselor tests still pass (0 regressions)
- [ ] No modification to existing dream steps 0–10

---

## File Summary

| File | Changes |
|------|---------|
| `src/probos/cognitive/retrieval_practice.py` | NEW: RetrievalPracticeEngine, RetrievalSchedule, RetrievalPracticeResult, SQLite persistence |
| `src/probos/cognitive/dreaming.py` | D3: Step 11 method (per-agent), engine + LLM wiring, dream_cycle() call |
| `src/probos/types.py` | D4: DreamReport retrieval fields (3) |
| `src/probos/config.py` | D4: DreamingConfig retrieval settings (7 fields) |
| `src/probos/events.py` | D5: RETRIEVAL_PRACTICE_CONCERN EventType |
| `src/probos/cognitive/counselor.py` | D5: Event handler, CognitiveProfile fields (2), subscription |
| `src/probos/startup/dreaming.py` | D6: Conditional engine construction + fast-tier LLM wiring + shutdown |
| `tests/test_ad541c_retrieval_practice.py` | NEW: 30 tests |
