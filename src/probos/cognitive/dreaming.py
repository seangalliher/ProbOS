"""Dreaming engine — offline consolidation of Hebbian weights, trust, and pre-warming.

During idle periods the system replays recent episodes, strengthens successful
pathways, prunes weak connections, and pre-warms likely upcoming workflows
based on temporal patterns.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from typing import Any

from probos.config import DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter, REL_INTENT
from probos.types import DreamReport, Episode

logger = logging.getLogger(__name__)


class DreamingEngine:
    """Performs a single dream cycle: replay, prune, trust consolidation, pre-warm."""

    def __init__(
        self,
        router: HebbianRouter,
        trust_network: TrustNetwork,
        episodic_memory: Any,
        config: DreamingConfig,
        idle_scale_down_fn: Any = None,
    ) -> None:
        self.router = router
        self.trust_network = trust_network
        self.episodic_memory = episodic_memory
        self.config = config
        self.pre_warm_intents: list[str] = []
        self._idle_scale_down_fn = idle_scale_down_fn

    async def dream_cycle(self) -> DreamReport:
        """Execute one full dream pass.

        Steps:
        1. Replay recent episodes — strengthen/weaken Hebbian weights
        2. Prune — decay all weights and remove below-threshold connections
        3. Trust consolidation — boost/penalize agents based on track records
        4. Pre-warm — identify temporal intent sequences for faster routing
        """
        t_start = time.monotonic()

        episodes = await self.episodic_memory.recent(k=self.config.replay_episode_count)

        if not episodes:
            return DreamReport(duration_ms=(time.monotonic() - t_start) * 1000)

        # Step 1: Replay
        weights_strengthened = self._replay_episodes(episodes)

        # Step 2: Prune
        weights_pruned = self._prune_weights()

        # Step 3: Trust consolidation
        trust_adjustments = self._consolidate_trust(episodes)

        # Step 4: Pre-warm
        pre_warm = self._compute_pre_warm(episodes)
        self.pre_warm_intents = pre_warm

        # Step 5: Idle pool scale-down (if scaler wired)
        if self._idle_scale_down_fn:
            try:
                await self._idle_scale_down_fn()
            except Exception as e:
                logger.debug("Idle scale-down failed: %s", e)

        duration_ms = (time.monotonic() - t_start) * 1000

        report = DreamReport(
            episodes_replayed=len(episodes),
            weights_strengthened=weights_strengthened,
            weights_pruned=weights_pruned,
            trust_adjustments=trust_adjustments,
            pre_warm_intents=pre_warm,
            duration_ms=duration_ms,
        )

        logger.debug(
            "Dream cycle complete: %d episodes, %d strengthened, %d pruned, "
            "%d trust adjustments, %d pre-warm intents (%.1fms)",
            report.episodes_replayed,
            report.weights_strengthened,
            report.weights_pruned,
            report.trust_adjustments,
            len(report.pre_warm_intents),
            report.duration_ms,
        )

        return report

    def _replay_episodes(self, episodes: list[Episode]) -> int:
        """Replay episodes: strengthen weights for successes, weaken for failures."""
        strengthened = 0

        for episode in episodes:
            intents = self._extract_intents(episode)
            agent_ids = episode.agent_ids

            for outcome in episode.outcomes:
                intent = outcome.get("intent", "")
                success = outcome.get("success", False)

                if not intent:
                    continue

                # Strengthen/weaken the connection between this intent and
                # each agent that participated in the episode
                for agent_id in agent_ids:
                    if success:
                        current = self.router.get_weight(intent, agent_id, REL_INTENT)
                        new_weight = min(
                            1.0,
                            current + self.config.pathway_strengthening_factor,
                        )
                        self.router._weights[(intent, agent_id, REL_INTENT)] = new_weight
                        self.router._compat_weights[(intent, agent_id)] = new_weight
                        strengthened += 1
                    else:
                        current = self.router.get_weight(intent, agent_id, REL_INTENT)
                        new_weight = max(
                            0.0,
                            current - self.config.pathway_weakening_factor,
                        )
                        self.router._weights[(intent, agent_id, REL_INTENT)] = new_weight
                        self.router._compat_weights[(intent, agent_id)] = new_weight

        return strengthened

    def _prune_weights(self) -> int:
        """Apply decay and remove connections below prune threshold."""
        # First apply standard Hebbian decay
        self.router.decay_all()

        # Then remove anything below our (potentially higher) prune threshold
        pruned = 0
        keys_to_remove = []
        for key, weight in self.router._weights.items():
            if weight < self.config.prune_threshold:
                keys_to_remove.append(key)
                pruned += 1

        for key in keys_to_remove:
            del self.router._weights[key]

        # Rebuild compat view
        self.router._compat_weights.clear()
        for (src, tgt, _), w in self.router._weights.items():
            self.router._compat_weights[(src, tgt)] = w

        return pruned

    def _consolidate_trust(self, episodes: list[Episode]) -> int:
        """Adjust trust based on agent track records in recent episodes.

        Agents with many successes get a trust boost (alpha increment).
        Agents with many failures get a trust penalty (beta increment).
        """
        # Count successes and failures per agent across episodes
        agent_successes: Counter[str] = Counter()
        agent_failures: Counter[str] = Counter()

        for episode in episodes:
            all_success = all(o.get("success", False) for o in episode.outcomes) if episode.outcomes else False
            all_failed = all(not o.get("success", True) for o in episode.outcomes) if episode.outcomes else False

            for agent_id in episode.agent_ids:
                if all_success:
                    agent_successes[agent_id] += 1
                if all_failed:
                    agent_failures[agent_id] += 1

        adjustments = 0

        # Boost agents with consistent success (threshold: >1 successful episode)
        for agent_id, count in agent_successes.items():
            if count > 1:
                record = self.trust_network.get_or_create(agent_id)
                record.alpha += self.config.trust_boost
                adjustments += 1

        # Penalize agents appearing in multiple failed episodes
        for agent_id, count in agent_failures.items():
            if count > 1:
                record = self.trust_network.get_or_create(agent_id)
                record.beta += self.config.trust_penalty
                adjustments += 1

        return adjustments

    def _compute_pre_warm(self, episodes: list[Episode]) -> list[str]:
        """Analyze temporal patterns to predict likely next intents.

        Looks at sequential intent pairs across episodes to find common
        transitions (e.g., list_directory -> read_file).
        """
        # Build bigram counts of intent sequences
        bigram_counts: Counter[str] = Counter()

        for episode in episodes:
            intents = self._extract_intents(episode)
            for i in range(len(intents) - 1):
                # The intent that follows another is a candidate for pre-warming
                bigram_counts[intents[i + 1]] += 1

        # Also count standalone intent frequency for recency weighting
        intent_freq: Counter[str] = Counter()
        for episode in episodes:
            for intent in self._extract_intents(episode):
                intent_freq[intent] += 1

        # Combine bigram successors with frequency
        combined: Counter[str] = Counter()
        for intent, count in bigram_counts.items():
            combined[intent] += count * 2  # Transition patterns weighted 2x
        for intent, count in intent_freq.items():
            combined[intent] += count

        # Return top-K
        return [intent for intent, _ in combined.most_common(self.config.pre_warm_top_k)]

    @staticmethod
    def _extract_intents(episode: Episode) -> list[str]:
        """Extract ordered list of intents from an episode's outcomes."""
        intents: list[str] = []
        for outcome in episode.outcomes:
            intent = outcome.get("intent", "")
            if intent:
                intents.append(intent)
        return intents


class DreamScheduler:
    """Background scheduler that triggers dream cycles during idle periods."""

    def __init__(
        self,
        engine: DreamingEngine,
        idle_threshold_seconds: float = 300.0,
        dream_interval_seconds: float = 600.0,
    ) -> None:
        self.engine = engine
        self.idle_threshold_seconds = idle_threshold_seconds
        self.dream_interval_seconds = dream_interval_seconds

        self._last_activity_time: float = time.monotonic()
        self._last_dream_time: float = 0.0
        self._is_dreaming: bool = False
        self._task: asyncio.Task[None] | None = None
        self._last_dream_report: DreamReport | None = None
        self._stopped = False

    @property
    def is_dreaming(self) -> bool:
        return self._is_dreaming

    @property
    def last_dream_report(self) -> DreamReport | None:
        return self._last_dream_report

    def record_activity(self) -> None:
        """Record that user activity occurred (resets idle timer)."""
        self._last_activity_time = time.monotonic()

    def start(self) -> None:
        """Start the background monitoring task."""
        if self._task is not None:
            return
        self._stopped = False
        self._last_activity_time = time.monotonic()
        self._task = asyncio.ensure_future(self._monitor_loop())

    async def stop(self) -> None:
        """Stop the background monitoring task."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def force_dream(self) -> DreamReport:
        """Force an immediate dream cycle (for /dream now command)."""
        self._is_dreaming = True
        try:
            report = await self.engine.dream_cycle()
            self._last_dream_report = report
            self._last_dream_time = time.monotonic()
            return report
        finally:
            self._is_dreaming = False

    async def _monitor_loop(self) -> None:
        """Background loop: check idle time and trigger dreams."""
        while not self._stopped:
            try:
                await asyncio.sleep(1.0)

                if self._is_dreaming:
                    continue

                now = time.monotonic()
                idle_time = now - self._last_activity_time
                time_since_last_dream = now - self._last_dream_time

                if (
                    idle_time >= self.idle_threshold_seconds
                    and time_since_last_dream >= self.dream_interval_seconds
                ):
                    self._is_dreaming = True
                    try:
                        report = await self.engine.dream_cycle()
                        self._last_dream_report = report
                        self._last_dream_time = time.monotonic()
                    except Exception as e:
                        logger.warning("Dream cycle failed: %s", e)
                    finally:
                        self._is_dreaming = False
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Dream monitor error: %s", e)
