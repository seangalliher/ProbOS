"""Domain-partitioned configuration models (AD-1270e2).

``probos.config`` remains the permanent public facade. Import from there, not
from here; this package exists so ``config.py`` can stop being 7,842 lines.
"""

from __future__ import annotations

from probos.config_models.core import (
    CircuitBreakerConfig,
    ConcurrencyConfig,
    ConsensusConfig,
    EventLogConfig,
    MeshConfig,
    PoolConfig,
    ScalingConfig,
    SystemInfo,
)

__all__ = [
    "CircuitBreakerConfig",
    "ConcurrencyConfig",
    "ConsensusConfig",
    "EventLogConfig",
    "MeshConfig",
    "PoolConfig",
    "ScalingConfig",
    "SystemInfo",
]
