"""AD-610: Utility-Based Storage Gating.

Write-time duplicate detection, utility scoring, and contradiction
flagging for episodic memory. Runs before persistence to prevent
low-value or redundant episodes from entering the store.

Uses lightweight heuristics with no LLM calls for fast inline evaluation.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.types import Episode

logger = logging.getLogger(__name__)


@dataclass
class StorageDecision:
    """Result of storage gate evaluation."""

    action: str
    reason: str
    utility_score: float
    duplicate_of: str | None = None


class StorageGate:
    """Evaluates episodes at write time for utility and duplication."""

    def __init__(
        self,
        config: Any,
        emit_event_fn: Any = None,
    ) -> None:
        self._emit_event_fn = emit_event_fn

        self._enabled: bool = config.enabled
        self._duplicate_threshold: float = config.duplicate_threshold
        self._utility_floor: float = config.utility_floor
        self._recent_window: int = config.recent_window
        self._contradiction_check_enabled: bool = config.contradiction_check_enabled

        self._recent: deque[dict[str, Any]] = deque(maxlen=self._recent_window)

    def evaluate(self, episode: Episode) -> StorageDecision:
        """Evaluate an episode for storage worthiness."""
        if not self._enabled:
            return StorageDecision(
                action="ACCEPT",
                reason="gate_disabled",
                utility_score=1.0,
            )

        content = self._extract_content(episode)

        if not content.strip():
            self._emit_rejection(episode, "empty_content")
            return StorageDecision(
                action="REJECT",
                reason="empty_content",
                utility_score=0.0,
            )

        dup_id = self._check_near_duplicate(content)
        if dup_id is not None:
            self._record_fingerprint(episode, content)
            self._emit_rejection(episode, "near_duplicate")
            return StorageDecision(
                action="REJECT",
                reason="near_duplicate",
                utility_score=0.0,
                duplicate_of=dup_id,
            )

        utility = self._check_utility(episode, content)
        if utility < self._utility_floor and episode.importance < 8:
            self._record_fingerprint(episode, content)
            self._emit_rejection(episode, "below_utility_floor")
            return StorageDecision(
                action="REJECT",
                reason="below_utility_floor",
                utility_score=utility,
            )

        if self._contradiction_check_enabled:
            contradiction = self._check_contradiction(episode, content)
            if contradiction:
                logger.info(
                    "AD-610: Contradiction detected for episode %s: %s; accepting episode for later dream review",
                    episode.id,
                    contradiction,
                )

        self._record_fingerprint(episode, content)

        return StorageDecision(
            action="ACCEPT",
            reason="passed_all_checks",
            utility_score=utility,
        )

    def _extract_content(self, episode: Episode) -> str:
        """Extract searchable text content from an episode."""
        parts: list[str] = []
        if episode.user_input:
            parts.append(episode.user_input)
        if episode.reflection:
            parts.append(episode.reflection)
        for outcome in episode.outcomes:
            if isinstance(outcome, dict):
                result = outcome.get("result", "")
                if result:
                    parts.append(str(result))
        return " ".join(parts)

    def _check_near_duplicate(self, content: str) -> str | None:
        """Return the duplicate episode ID when content matches recent memory."""
        if not content:
            return None

        content_words = text_to_words(content)
        for recent in self._recent:
            sim = jaccard_similarity(content_words, recent["content_words"])
            if sim >= self._duplicate_threshold:
                return recent["id"]
        return None

    def _check_utility(self, episode: Episode, content: str) -> float:
        """Score episode utility as a weighted composite."""
        importance_score = min(episode.importance / 10.0, 1.0)
        length_score = min(len(content) / 500.0, 1.0)

        anchor_score = 0.0
        if episode.anchors is not None:
            filled = 0
            total = 6
            if episode.anchors.department:
                filled += 1
            if episode.anchors.channel:
                filled += 1
            if episode.anchors.trigger_type:
                filled += 1
            if episode.anchors.watch_section:
                filled += 1
            if episode.anchors.participants:
                filled += 1
            if episode.anchors.trigger_agent:
                filled += 1
            anchor_score = filled / total

        source_score = 0.5
        if episode.source and episode.source != "direct":
            source_score = 0.8

        return (
            0.4 * importance_score
            + 0.2 * length_score
            + 0.2 * anchor_score
            + 0.2 * source_score
        )

    def _check_contradiction(
        self,
        episode: Episode,
        content: str,
    ) -> str | None:
        """Check for potential contradictions with recent episodes."""
        if not content:
            return None

        content_words = text_to_words(content)
        ep_outcomes = self._summarize_outcomes(episode)
        ep_outcome_words = text_to_words(ep_outcomes)
        for recent in self._recent:
            word_overlap = jaccard_similarity(content_words, recent["content_words"])
            if word_overlap < 0.3:
                continue

            recent_outcome_words = recent.get("outcome_words", set())
            if ep_outcome_words and recent_outcome_words:
                outcome_sim = jaccard_similarity(ep_outcome_words, recent_outcome_words)
                if outcome_sim < 0.2 and word_overlap > 0.5:
                    return (
                        f"High content similarity ({word_overlap:.2f}) but "
                        f"low outcome similarity ({outcome_sim:.2f}) with "
                        f"episode {recent['id']}"
                    )
        return None

    def _summarize_outcomes(self, episode: Episode) -> str:
        """Extract outcome summary for contradiction comparison."""
        parts: list[str] = []
        for outcome in episode.outcomes:
            if isinstance(outcome, dict):
                success = outcome.get("success", None)
                if success is not None:
                    parts.append(f"success={success}")
                error = outcome.get("error", "")
                if error:
                    parts.append(f"error={error}")
        return " ".join(parts)

    def _record_fingerprint(self, episode: Episode, content: str) -> None:
        """Add episode fingerprint to the recent buffer."""
        outcomes_summary = self._summarize_outcomes(episode)
        self._recent.append({
            "id": episode.id,
            "content": content,
            "content_words": text_to_words(content),
            "outcomes_summary": outcomes_summary,
            "outcome_words": text_to_words(outcomes_summary),
            "timestamp": episode.timestamp or time.time(),
        })

    def _emit_rejection(self, episode: Episode, reason: str) -> None:
        """Emit an EPISODE_REJECTED event."""
        if self._emit_event_fn:
            try:
                from probos.events import EventType

                self._emit_event_fn(EventType.EPISODE_REJECTED, {
                    "episode_id": episode.id,
                    "agent_ids": episode.agent_ids,
                    "reason": reason,
                    "importance": episode.importance,
                })
            except Exception:
                logger.debug(
                    "AD-610: Failed to emit EPISODE_REJECTED for episode %s; storage decision still returned",
                    episode.id,
                    exc_info=True,
                )

    @property
    def recent_count(self) -> int:
        """Number of episodes in the recent dedup window."""
        return len(self._recent)

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        return {
            "enabled": self._enabled,
            "recent_count": self.recent_count,
            "duplicate_threshold": self._duplicate_threshold,
            "utility_floor": self._utility_floor,
        }