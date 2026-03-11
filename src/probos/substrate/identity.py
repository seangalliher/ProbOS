"""Deterministic agent identity generation (Phase 14c).

Produces stable, human-readable agent IDs derived from deployment
topology (agent_type, pool_name, instance_index).  Same inputs
always produce the same ID — agents survive restarts as individuals.
"""

from __future__ import annotations

import hashlib


def generate_agent_id(agent_type: str, pool_name: str, instance_index: int) -> str:
    """Generate a deterministic, human-readable agent ID.

    Format: ``{agent_type}_{pool_name}_{index}_{hash8}``

    The hash suffix is the first 8 hex chars of
    ``sha256(agent_type:pool_name:instance_index)``.
    """
    raw = f"{agent_type}:{pool_name}:{instance_index}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"{agent_type}_{pool_name}_{instance_index}_{short_hash}"


def generate_pool_ids(
    agent_type: str, pool_name: str, count: int
) -> list[str]:
    """Generate deterministic IDs for all agents in a pool."""
    return [
        generate_agent_id(agent_type, pool_name, i)
        for i in range(count)
    ]
