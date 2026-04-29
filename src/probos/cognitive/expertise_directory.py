"""AD-600: Transactive Memory -- Cross-Agent Expertise Routing.

In-memory directory tracking which agents are expert on which topics.
Built from dream-cycle clustering. Used by OracleService to narrow
queries to top-k relevant agent shards instead of scanning all agents.
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
    topics: dict[str, float] = field(default_factory=dict)


@dataclass
class ExpertMatch:
    """A ranked match from querying the expertise directory."""

    agent_id: str
    department: str
    confidence: float
    topic_match: str


class ExpertiseDirectory:
    """In-memory directory of agent expertise, built from dream clustering."""

    def __init__(self, config: Any) -> None:
        self._max_topics: int = config.max_topics_per_agent
        self._min_confidence: float = config.min_confidence
        self._decay_rate: float = config.decay_rate
        self._top_k: int = config.top_k_experts
        self._profiles: dict[str, ExpertiseProfile] = {}

    def update_profile(
        self,
        agent_id: str,
        topics: list[str],
        confidence: float,
        *,
        department: str = "",
    ) -> None:
        """Update an agent's expertise profile with new topics."""
        if not agent_id or not topics:
            return

        profile = self._profiles.get(agent_id)
        if profile is None:
            profile = ExpertiseProfile(agent_id=agent_id, department=department)
            self._profiles[agent_id] = profile

        if department and not profile.department:
            profile.department = department

        bounded_confidence = max(0.0, min(float(confidence), 1.0))
        for topic in topics:
            topic_lower = topic.lower().strip()
            if not topic_lower:
                continue
            existing = profile.topics.get(topic_lower, 0.0)
            profile.topics[topic_lower] = max(existing, bounded_confidence)

        if len(profile.topics) > self._max_topics:
            sorted_topics = sorted(
                profile.topics.items(), key=lambda topic_conf: topic_conf[1], reverse=True
            )
            profile.topics = dict(sorted_topics[: self._max_topics])

        profile.topics = {
            topic: stored_confidence
            for topic, stored_confidence in profile.topics.items()
            if stored_confidence >= self._min_confidence
        }
        if not profile.topics:
            self._profiles.pop(agent_id, None)

    def query_experts(self, topic: str, top_k: int | None = None) -> list[ExpertMatch]:
        """Return ranked agents most likely to have knowledge on a topic."""
        if not topic:
            return []

        limit = top_k if top_k is not None else self._top_k
        topic_lower = topic.lower().strip()
        topic_words = set(topic_lower.split())
        matches: list[ExpertMatch] = []

        for profile in self._profiles.values():
            best_confidence = 0.0
            best_topic = ""
            for profile_topic, confidence in profile.topics.items():
                if topic_lower in profile_topic or profile_topic in topic_lower:
                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_topic = profile_topic
                    continue

                profile_words = set(profile_topic.split())
                overlap = topic_words & profile_words
                if overlap:
                    partial_confidence = confidence * (len(overlap) / max(len(topic_words), 1))
                    if partial_confidence > best_confidence:
                        best_confidence = partial_confidence
                        best_topic = profile_topic

            if best_confidence >= self._min_confidence:
                matches.append(ExpertMatch(
                    agent_id=profile.agent_id,
                    department=profile.department,
                    confidence=best_confidence,
                    topic_match=best_topic,
                ))

        matches.sort(key=lambda match: match.confidence, reverse=True)
        return matches[:limit]

    def build_from_clusters(
        self,
        agent_id: str,
        clusters: list[Any],
        *,
        department: str = "",
    ) -> int:
        """Extract topics from episode clusters and update the agent's profile."""
        topics_added = 0
        for cluster in clusters:
            intent_types = getattr(cluster, "intent_types", []) or []
            if not intent_types:
                continue

            success_rate = float(getattr(cluster, "success_rate", 0.0) or 0.0)
            episode_count = int(getattr(cluster, "episode_count", 0) or 0)
            count_factor = min(episode_count / 10.0, 1.0)
            confidence = success_rate * 0.7 + count_factor * 0.3

            self.update_profile(agent_id, intent_types, confidence, department=department)
            topics_added += len(intent_types)

            anchor_summary = getattr(cluster, "anchor_summary", None) or {}
            departments = anchor_summary.get("departments", []) if isinstance(anchor_summary, dict) else []
            if isinstance(departments, list) and departments:
                self.update_profile(
                    agent_id,
                    [f"dept:{dept}" for dept in departments],
                    confidence * 0.5,
                    department=department,
                )
                topics_added += len(departments)

        logger.debug(
            "AD-600: Built expertise profile for %s with %d topics from %d clusters",
            agent_id,
            topics_added,
            len(clusters),
        )
        return topics_added

    def decay_profiles(self, factor: float | None = None) -> int:
        """Decay all topic confidences by a multiplicative factor."""
        decay = factor if factor is not None else self._decay_rate
        removed = 0

        for profile in self._profiles.values():
            decayed_topics: dict[str, float] = {}
            for topic, confidence in profile.topics.items():
                decayed_confidence = confidence * decay
                if decayed_confidence >= self._min_confidence:
                    decayed_topics[topic] = decayed_confidence
                else:
                    removed += 1
            profile.topics = decayed_topics

        empty_agent_ids = [
            agent_id for agent_id, profile in self._profiles.items() if not profile.topics
        ]
        for agent_id in empty_agent_ids:
            del self._profiles[agent_id]

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
            "total_topics": sum(len(profile.topics) for profile in self._profiles.values()),
            "profiles": {
                agent_id: {
                    "department": profile.department,
                    "topic_count": len(profile.topics),
                    "top_topics": sorted(
                        profile.topics.items(), key=lambda topic_conf: topic_conf[1], reverse=True
                    )[:5],
                }
                for agent_id, profile in self._profiles.items()
            },
        }