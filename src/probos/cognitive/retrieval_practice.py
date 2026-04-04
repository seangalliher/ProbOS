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

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.types import Episode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RetrievalSchedule:
    """Spaced repetition schedule for one episode-agent pair."""

    agent_id: str = ""
    episode_id: str = ""
    interval_hours: float = 24.0
    last_practiced: float = 0.0
    next_due: float = 0.0
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    total_practices: int = 0
    total_successes: int = 0
    recall_accuracy: float = 0.0
    retired: bool = False


@dataclass
class RetrievalPracticeResult:
    """Result of a single recall practice trial."""

    agent_id: str = ""
    episode_id: str = ""
    recall_accuracy: float = 0.0
    success: bool = False
    recalled_text: str = ""
    expected_text: str = ""
    interval_before: float = 0.0
    interval_after: float = 0.0
    practice_number: int = 0


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RetrievalPracticeEngine:
    """Spaced Retrieval Therapy engine for dream-time memory strengthening."""

    def __init__(
        self,
        *,
        success_threshold: float = 0.6,
        partial_threshold: float = 0.3,
        initial_interval_hours: float = 24.0,
        max_interval_hours: float = 168.0,
        episodes_per_cycle: int = 3,
        counselor_failure_streak: int = 3,
        connection_factory: Any = None,
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
        self._db: Any = None

    # ------------------------------------------------------------------
    # Lifecycle (D2)
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialize SQLite store and load existing schedules."""
        if not self._data_dir:
            return
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory
        db_path = str(self._data_dir / "retrieval_practice.db")
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript(_RETRIEVAL_SCHEMA)
        await self._db.commit()
        await self._load_schedules()

    async def stop(self) -> None:
        """Close the database connection if open."""
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                pass
            self._db = None

    async def _load_schedules(self) -> None:
        """Load all rows from retrieval_schedules table."""
        if self._db is None:
            return
        cursor = await self._db.execute("SELECT * FROM retrieval_schedules")
        rows = await cursor.fetchall()
        for row in rows:
            sched = RetrievalSchedule(
                agent_id=row[0],
                episode_id=row[1],
                interval_hours=row[2],
                last_practiced=row[3],
                next_due=row[4],
                consecutive_successes=row[5],
                consecutive_failures=row[6],
                total_practices=row[7],
                total_successes=row[8],
                recall_accuracy=row[9],
                retired=bool(row[10]),
            )
            key = f"{sched.agent_id}:{sched.episode_id}"
            self._schedules[key] = sched

    async def _save_schedule(self, schedule: RetrievalSchedule) -> None:
        """Upsert a single schedule row."""
        if self._db is None:
            return
        await self._db.execute(
            """INSERT INTO retrieval_schedules
               (agent_id, episode_id, interval_hours, last_practiced, next_due,
                consecutive_successes, consecutive_failures, total_practices,
                total_successes, recall_accuracy, retired)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(agent_id, episode_id) DO UPDATE SET
                 interval_hours = excluded.interval_hours,
                 last_practiced = excluded.last_practiced,
                 next_due = excluded.next_due,
                 consecutive_successes = excluded.consecutive_successes,
                 consecutive_failures = excluded.consecutive_failures,
                 total_practices = excluded.total_practices,
                 total_successes = excluded.total_successes,
                 recall_accuracy = excluded.recall_accuracy,
                 retired = excluded.retired
            """,
            (
                schedule.agent_id,
                schedule.episode_id,
                schedule.interval_hours,
                schedule.last_practiced,
                schedule.next_due,
                schedule.consecutive_successes,
                schedule.consecutive_failures,
                schedule.total_practices,
                schedule.total_successes,
                schedule.recall_accuracy,
                int(schedule.retired),
            ),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Core methods (D1)
    # ------------------------------------------------------------------

    def select_episodes_for_practice(
        self, episodes: list[Episode], agent_id: str,
    ) -> list[Episode]:
        """Select up to K episodes for this agent to practice."""
        now = time.time()

        # Filter: DIRECT source only, agent must appear in agent_ids
        eligible = [
            ep for ep in episodes
            if ep.source == "direct"
            and agent_id in ep.agent_ids
        ]

        due: list[Episode] = []
        new: list[Episode] = []

        for ep in eligible:
            key = f"{agent_id}:{ep.id}"
            sched = self._schedules.get(key)
            if sched:
                if sched.retired:
                    continue
                if sched.next_due <= now:
                    due.append(ep)
            else:
                new.append(ep)

        # Prioritize new episodes: trust_deltas > failed outcomes > others
        def _impact_sort(ep: Episode) -> tuple[int, int]:
            has_deltas = 1 if ep.trust_deltas else 0
            has_failures = 1 if any(
                not o.get("success", True) for o in ep.outcomes
            ) else 0
            return (-has_deltas, -has_failures)

        new.sort(key=_impact_sort)

        # Due first, then new
        combined = due + new
        return combined[: self._episodes_per_cycle]

    def build_recall_prompt(self, episode: Episode) -> str:
        """Build a recall prompt — present context, withhold outcome."""
        context_parts = [f"Timestamp: {episode.timestamp}"]
        if episode.user_input:
            context_parts.append(f"Situation: {episode.user_input}")
        if episode.dag_summary:
            intent_types = episode.dag_summary.get("intent_types", [])
            if intent_types:
                context_parts.append(
                    f"Intent types involved: {', '.join(intent_types)}"
                )
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

    def build_expected_text(self, episode: Episode) -> str:
        """Extract ground truth text from episode for accuracy comparison."""
        parts: list[str] = []
        if episode.reflection:
            parts.append(episode.reflection)
        for outcome in episode.outcomes:
            status = outcome.get("status", outcome.get("success", ""))
            intent = outcome.get("intent", "")
            if intent:
                parts.append(f"{intent}: {status}")
        return " ".join(parts) if parts else ""

    def score_recall(self, recalled_text: str, expected_text: str) -> float:
        """Score recall accuracy using Jaccard similarity."""
        if not expected_text:
            return 1.0
        return jaccard_similarity(
            text_to_words(recalled_text),
            text_to_words(expected_text),
        )

    def update_schedule(
        self, agent_id: str, episode_id: str, accuracy: float,
    ) -> RetrievalSchedule:
        """Apply spaced repetition logic and update schedule."""
        key = f"{agent_id}:{episode_id}"
        now = time.time()

        sched = self._schedules.get(key)
        if sched is None:
            sched = RetrievalSchedule(
                agent_id=agent_id,
                episode_id=episode_id,
                interval_hours=self._initial_interval_hours,
            )

        sched.total_practices += 1
        sched.recall_accuracy = accuracy
        sched.last_practiced = now

        if accuracy >= self._success_threshold:
            # Success — extend interval
            sched.consecutive_successes += 1
            sched.consecutive_failures = 0
            sched.total_successes += 1
            sched.interval_hours *= 2.0
        elif accuracy >= self._partial_threshold:
            # Partial — maintain interval, reset streaks
            sched.consecutive_successes = 0
            sched.consecutive_failures = 0
        else:
            # Failure — shorten interval
            sched.consecutive_failures += 1
            sched.consecutive_successes = 0
            sched.interval_hours = max(
                self._initial_interval_hours, sched.interval_hours / 2.0,
            )

        # Retire if interval exceeds max
        if sched.interval_hours > self._max_interval_hours:
            sched.retired = True

        sched.next_due = now + sched.interval_hours * 3600

        self._schedules[key] = sched
        return sched

    def get_counselor_concerns(
        self, agent_id: str | None = None,
    ) -> list[RetrievalSchedule]:
        """Return schedules with concerning failure streaks."""
        concerns: list[RetrievalSchedule] = []
        for sched in self._schedules.values():
            if sched.retired:
                continue
            if sched.consecutive_failures < self._counselor_failure_streak:
                continue
            if agent_id is not None and sched.agent_id != agent_id:
                continue
            concerns.append(sched)
        return concerns

    def get_agent_recall_stats(self, agent_id: str) -> dict[str, Any]:
        """Return aggregate stats for an agent."""
        total_scheduled = 0
        total_practiced = 0
        total_retired = 0
        accuracy_sum = 0.0
        accuracy_count = 0
        at_risk = 0
        sessions_total = 0

        for sched in self._schedules.values():
            if sched.agent_id != agent_id:
                continue
            total_scheduled += 1
            if sched.total_practices > 0:
                total_practiced += 1
                accuracy_sum += sched.recall_accuracy
                accuracy_count += 1
            if sched.retired:
                total_retired += 1
            if sched.consecutive_failures >= self._counselor_failure_streak:
                at_risk += 1
            sessions_total += sched.total_practices

        return {
            "total_scheduled": total_scheduled,
            "total_practiced": total_practiced,
            "total_retired": total_retired,
            "avg_recall_accuracy": (
                accuracy_sum / accuracy_count if accuracy_count else 0.0
            ),
            "episodes_at_risk": at_risk,
            "practice_sessions_total": sessions_total,
        }
