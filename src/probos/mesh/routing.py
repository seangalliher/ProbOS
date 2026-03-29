"""Hebbian router — connection weight tracking with SQLite persistence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from probos.types import AgentID

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hebbian_weights (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    rel_type  TEXT NOT NULL DEFAULT 'intent',
    weight    REAL NOT NULL DEFAULT 0.0,
    updated   TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id, rel_type)
);
"""

# Relationship types
REL_INTENT = "intent"  # intent_id → agent_id (Phase 1 default)
REL_AGENT = "agent"  # agent_id → agent_id (Phase 2 verification)
REL_SOCIAL = "social"  # agent_id → agent_id (AD-453 Ward Room interactions)
REL_BUILDER_VARIANT = "builder_variant"  # build_code → native|visiting (AD-353)
REL_STRATEGY = "strategy"  # strategy_id → agent_type (AD-384)

# Key type: (source, target) for backward compat, internally keyed with rel_type
_WeightKey = tuple[AgentID, AgentID]
_FullKey = tuple[AgentID, AgentID, str]


class HebbianRouter:
    """Tracks connection weights between agents.

    Supports two relationship types:
    - intent: intent_id → agent_id (Phase 1 — intent routing)
    - agent: agent_id → agent_id (Phase 2 — verification relationships)

    When Agent A delegates to Agent B and the result is successful,
    the A→B weight increases. Failed interactions cause decay only.
    Weights are persisted to SQLite so learned topology survives restarts.
    """

    def __init__(
        self,
        decay_rate: float = 0.995,
        reward: float = 0.05,
        db_path: str | Path | None = None,
    ) -> None:
        self.decay_rate = decay_rate
        self.reward = reward
        self.db_path = str(db_path) if db_path else None
        # Full key: (source, target, rel_type)
        self._weights: dict[_FullKey, float] = {}
        # Backward-compat view: (source, target) → weight (aggregated)
        self._compat_weights: dict[_WeightKey, float] = {}
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        """Initialize — load weights from SQLite if configured."""
        if self.db_path:
            self._db = await aiosqlite.connect(self.db_path)
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._db.execute(_SCHEMA)
            await self._db.commit()
            await self._load_from_db()
            logger.info(
                "HebbianRouter loaded %d weights from %s",
                len(self._weights),
                self.db_path,
            )

    async def stop(self) -> None:
        """Persist weights and close DB."""
        if self._db:
            await self._save_to_db()
            await self._db.close()
            self._db = None

    def record_interaction(
        self,
        source: AgentID,
        target: AgentID,
        success: bool,
        rel_type: str = REL_INTENT,
    ) -> float:
        """Update connection weight after an interaction.

        Returns the new weight.
        """
        full_key = (source, target, rel_type)
        compat_key = (source, target)
        current = self._weights.get(full_key, 0.0)

        if success:
            new_weight = current * self.decay_rate + self.reward
        else:
            new_weight = current * self.decay_rate

        # Clamp to [0.0, 1.0]
        new_weight = max(0.0, min(1.0, new_weight))
        self._weights[full_key] = new_weight
        self._compat_weights[compat_key] = new_weight
        return new_weight

    def record_verification(
        self,
        verifier_id: AgentID,
        target_id: AgentID,
        verified: bool,
    ) -> float:
        """Record an agent-to-agent verification result.

        Convenience method for red team verification interactions.
        """
        return self.record_interaction(
            source=verifier_id,
            target=target_id,
            success=verified,
            rel_type=REL_AGENT,
        )

    def get_weight(
        self,
        source: AgentID,
        target: AgentID,
        rel_type: str | None = None,
    ) -> float:
        if rel_type is not None:
            return self._weights.get((source, target, rel_type), 0.0)
        return self._compat_weights.get((source, target), 0.0)

    def get_preferred_targets(
        self,
        source: AgentID,
        candidates: list[AgentID],
        rel_type: str | None = None,
        hint: str | None = None,           # AD-418
    ) -> list[AgentID]:
        """Rank candidates by their connection weight from source (descending)."""
        if rel_type is not None:
            scored = [
                (c, self._weights.get((source, c, rel_type), 0.0))
                for c in candidates
            ]
        else:
            scored = [
                (c, self._compat_weights.get((source, c), 0.0))
                for c in candidates
            ]

        # AD-418: Boost hinted agent so it wins when all weights are zero
        if hint:
            for i, (agent_id, score) in enumerate(scored):
                if hint in agent_id:
                    scored[i] = (agent_id, score + 1.0)

        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored]

    def get_agent_weights(self, agent_id: AgentID) -> dict[AgentID, float]:
        """Get all agent-to-agent weights where agent_id is the source."""
        result = {}
        for (src, tgt, rel), w in self._weights.items():
            if src == agent_id and rel == REL_AGENT:
                result[tgt] = w
        return result

    def decay_all(self) -> int:
        """Apply decay to all weights. Returns count of pruned zero-weights."""
        pruned = 0
        keys_to_remove = []
        for key, weight in self._weights.items():
            new_weight = weight * self.decay_rate
            if new_weight < 0.001:
                keys_to_remove.append(key)
                pruned += 1
            else:
                self._weights[key] = new_weight
        for key in keys_to_remove:
            del self._weights[key]
        # Rebuild compat view
        self._compat_weights.clear()
        for (src, tgt, _), w in self._weights.items():
            self._compat_weights[(src, tgt)] = w
        return pruned

    def prune_defunct_agents(self, live_agent_ids: set[str]) -> int:
        """Remove weights referencing agent targets not in the live roster.

        Only prunes entries where the target looks like a pool-based agent ID
        (contains underscore + hex suffix). Intent names are left alone.

        Returns count of pruned entries.
        """
        keys_to_remove = []
        for key in self._weights:
            target = key[1]
            # Heuristic: pool-based agent IDs have format like
            # "poolname_agenttype_N_hexhash" — skip bare intent names
            parts = target.split("_")
            if len(parts) >= 3 and target not in live_agent_ids:
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._weights[key]
        # Rebuild compat view
        self._compat_weights.clear()
        for (src, tgt, _), w in self._weights.items():
            self._compat_weights[(src, tgt)] = w
        if keys_to_remove:
            logger.info("Pruned %d Hebbian weights for defunct agents", len(keys_to_remove))
        return len(keys_to_remove)

    @property
    def weight_count(self) -> int:
        return len(self._weights)

    def all_weights(self) -> dict[tuple[AgentID, AgentID], float]:
        """Backward-compatible: return (source, target) → weight."""
        return dict(self._compat_weights)

    def all_weights_typed(self) -> dict[_FullKey, float]:
        """Return (source, target, rel_type) → weight."""
        return dict(self._weights)

    # ------------------------------------------------------------------
    # SQLite persistence
    # ------------------------------------------------------------------

    async def _load_from_db(self) -> None:
        if not self._db:
            return
        async with self._db.execute(
            "SELECT source_id, target_id, rel_type, weight FROM hebbian_weights"
        ) as cursor:
            async for row in cursor:
                full_key = (row[0], row[1], row[2])
                compat_key = (row[0], row[1])
                self._weights[full_key] = row[3]
                self._compat_weights[compat_key] = row[3]

    async def _save_to_db(self) -> None:
        if not self._db:
            return
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("DELETE FROM hebbian_weights")
        for (source, target, rel_type), weight in self._weights.items():
            await self._db.execute(
                "INSERT INTO hebbian_weights (source_id, target_id, rel_type, weight, updated) "
                "VALUES (?, ?, ?, ?, ?)",
                (source, target, rel_type, weight, now),
            )
        await self._db.commit()
        logger.debug("Saved %d hebbian weights to disk", len(self._weights))

    async def save(self) -> None:
        """Manually trigger a save to disk."""
        await self._save_to_db()
