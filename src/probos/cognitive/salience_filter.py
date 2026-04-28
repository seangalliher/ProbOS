"""AD-668: Salience filter for working memory promotion."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.cognitive.agent_working_memory import WorkingMemoryEntry
    from probos.cognitive.novelty_gate import NoveltyGate
    from probos.config import SalienceConfig

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS: dict[str, float] = {
    "relevance": 0.30,
    "recency": 0.25,
    "novelty": 0.15,
    "urgency": 0.20,
    "social": 0.10,
}
_COMPONENT_KEYS: tuple[str, ...] = tuple(_DEFAULT_WEIGHTS.keys())


@dataclass
class SalienceScore:
    """Result of salience scoring for a working memory candidate."""

    total: float
    components: dict[str, float]
    promoted: bool
    entry: WorkingMemoryEntry


class SalienceFilter:
    """Scores working memory candidates for promotion vs. background stream."""

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
        threshold: float = 0.3,
        novelty_gate: NoveltyGate | None = None,
    ) -> None:
        raw_weights = _DEFAULT_WEIGHTS if weights is None else {
            key: max(0.0, value)
            for key, value in weights.items()
            if key in _DEFAULT_WEIGHTS
        }
        if not raw_weights:
            raw_weights = dict(_DEFAULT_WEIGHTS)
        total_weight = sum(raw_weights.values())
        if total_weight <= 0.0:
            raw_weights = dict(_DEFAULT_WEIGHTS)
            total_weight = sum(raw_weights.values())
        self._weights = {
            key: value / total_weight
            for key, value in raw_weights.items()
        }
        self._threshold = threshold
        self._novelty_gate = novelty_gate

    @classmethod
    def from_config(
        cls,
        config: SalienceConfig,
        *,
        novelty_gate: NoveltyGate | None = None,
    ) -> SalienceFilter:
        """Create a salience filter from config."""
        return cls(
            weights=config.weights,
            threshold=config.threshold,
            novelty_gate=novelty_gate,
        )

    def score(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> SalienceScore:
        """Score a working memory candidate for promotion."""
        components = {
            "relevance": self._score_relevance(entry, agent_context),
            "recency": self._score_recency(entry, agent_context),
            "novelty": self._score_novelty(entry, agent_context),
            "urgency": self._score_urgency(entry, agent_context),
            "social": self._score_social(entry, agent_context),
        }
        total = sum(self._weights[key] * components[key] for key in self._weights)
        total = max(0.0, min(1.0, total))
        promoted = total >= self._threshold
        return SalienceScore(
            total=round(total, 4),
            components=components,
            promoted=promoted,
            entry=entry,
        )

    def should_promote(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> bool:
        """Quick check: return True if entry should enter main working memory."""
        return self.score(entry, agent_context).promoted

    def _score_relevance(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> float:
        score = 0.5
        entry_department = entry.metadata.get("department")
        context_department = agent_context.get("department")
        entry_duty = entry.metadata.get("duty")
        context_duty = agent_context.get("current_duty")

        department_match = self._matches(entry_department, context_department)
        duty_match = self._matches(entry_duty, context_duty)
        if department_match and duty_match:
            score = 1.0
        elif duty_match:
            score = 0.9
        elif department_match:
            score = 0.8

        if entry.category == "alert":
            score = max(score, 0.7)
        return self._clamp(score)

    def _score_recency(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> float:
        age_seconds = entry.age_seconds()
        half_life = 300.0
        score = 2.0 ** (-age_seconds / half_life)
        return self._clamp(score)

    def _score_novelty(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> float:
        if self._novelty_gate is None:
            return 0.5
        agent_id = agent_context.get("agent_id", "unknown")
        try:
            verdict = self._novelty_gate.check(agent_id, entry.content)
        except Exception:
            logger.debug(
                "AD-668: NoveltyGate scoring failed for agent %s; using neutral novelty fallback",
                agent_id,
                exc_info=True,
            )
            return 0.5
        if verdict.is_novel:
            return self._clamp(1.0 - verdict.similarity)
        return self._clamp(max(0.1, 1.0 - verdict.similarity))

    def _score_urgency(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> float:
        score = 0.3
        severity = entry.metadata.get("severity")
        if isinstance(severity, str):
            score = {
                "critical": 1.0,
                "high": 0.8,
                "medium": 0.5,
                "low": 0.3,
            }.get(severity.lower(), score)

        alert_level = agent_context.get("alert_level")
        if isinstance(alert_level, str):
            if alert_level.lower() == "red":
                score += 0.2
            elif alert_level.lower() == "yellow":
                score += 0.1

        if entry.category == "alert":
            score = max(score, 0.7)
        return self._clamp(score)

    def _score_social(self, entry: WorkingMemoryEntry, agent_context: dict[str, Any]) -> float:
        source_agent = entry.metadata.get("from") or entry.metadata.get("partner")
        if not source_agent:
            return 0.5
        trust_scores = agent_context.get("trust_scores", {})
        trust = trust_scores.get(source_agent) if isinstance(trust_scores, dict) else None
        if trust is not None:
            return self._clamp(float(trust))
        return 0.4

    @staticmethod
    def _matches(value: Any, expected: Any) -> bool:
        if value is None or expected is None:
            return False
        return str(value).casefold() == str(expected).casefold()

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))


class BackgroundStream:
    """Capped deque for sub-threshold working memory events."""

    def __init__(self, *, max_entries: int = 50) -> None:
        self._entries: deque[SalienceScore] = deque(maxlen=max_entries)

    def add(self, scored: SalienceScore) -> None:
        """Add a sub-threshold scored entry."""
        self._entries.append(scored)

    def drain(self) -> list[SalienceScore]:
        """Remove and return all entries for batch processing."""
        result = list(self._entries)
        self._entries.clear()
        return result

    def peek(self) -> list[SalienceScore]:
        """Return entries without removing them."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
