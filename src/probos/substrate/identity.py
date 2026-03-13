"""Deterministic agent identity generation (Phase 14c).

Produces stable, human-readable agent IDs derived from deployment
topology (agent_type, pool_name, instance_index).  Same inputs
always produce the same ID — agents survive restarts as individuals.
"""

from __future__ import annotations

import hashlib
import re

# Module-level registry: populated by generate_agent_id(), consulted by parse_agent_id()
_ID_REGISTRY: dict[str, dict[str, str]] = {}


def generate_agent_id(agent_type: str, pool_name: str, instance_index: int) -> str:
    """Generate a deterministic, human-readable agent ID.

    Format: ``{agent_type}_{pool_name}_{index}_{hash8}``

    The hash suffix is the first 8 hex chars of
    ``sha256(agent_type:pool_name:instance_index)``.
    """
    raw = f"{agent_type}:{pool_name}:{instance_index}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    agent_id = f"{agent_type}_{pool_name}_{instance_index}_{short_hash}"

    # Store in registry for reliable parsing
    _ID_REGISTRY[agent_id] = {
        "agent_type": agent_type,
        "pool_name": pool_name,
        "index": str(instance_index),
        "hash": short_hash,
    }

    return agent_id


def generate_pool_ids(
    agent_type: str, pool_name: str, count: int
) -> list[str]:
    """Generate deterministic IDs for all agents in a pool."""
    return [
        generate_agent_id(agent_type, pool_name, i)
        for i in range(count)
    ]


# Regex for right-to-left parsing: ends with _{digits}_{8hex}
_ID_SUFFIX_RE = re.compile(r"^(.+)_(\d+)_([0-9a-f]{8})$")


def parse_agent_id(agent_id: str) -> dict[str, str] | None:
    """Parse a deterministic agent ID back into its components.

    Returns {"agent_type": ..., "pool_name": ..., "index": ..., "hash": ...}
    or None if the ID doesn't match the deterministic format.

    Strategy: check module-level registry first (populated by generate_agent_id()).
    For IDs not in the registry (e.g., restored from persistence), fall back to
    right-to-left regex parsing: the last segment is the 8-char hex hash, the
    second-to-last is the integer index, and the prefix is {type}_{pool}.
    """
    # Fast path: registry lookup
    if agent_id in _ID_REGISTRY:
        return dict(_ID_REGISTRY[agent_id])

    # Fallback: right-to-left parsing
    m = _ID_SUFFIX_RE.match(agent_id)
    if not m:
        return None

    prefix = m.group(1)   # {agent_type}_{pool_name}
    index = m.group(2)
    hash8 = m.group(3)

    # We can't perfectly split prefix into type vs pool without registry,
    # but we know the format. Return the full prefix as agent_type,
    # and empty pool_name — callers should prefer registry when available.
    # However, we can attempt to verify against known hash to find the split.
    parts = prefix.split("_")
    for split_point in range(1, len(parts)):
        candidate_type = "_".join(parts[:split_point])
        candidate_pool = "_".join(parts[split_point:])
        raw = f"{candidate_type}:{candidate_pool}:{index}"
        computed_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
        if computed_hash == hash8:
            result = {
                "agent_type": candidate_type,
                "pool_name": candidate_pool,
                "index": index,
                "hash": hash8,
            }
            # Cache for future lookups
            _ID_REGISTRY[agent_id] = result
            return dict(result)

    # Hash didn't match any split — return prefix as best effort
    return {
        "agent_type": prefix,
        "pool_name": "",
        "index": index,
        "hash": hash8,
    }
