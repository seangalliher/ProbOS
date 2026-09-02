"""Core substrate, mesh, consensus and runtime configuration models (AD-1270e2).

Batch 1 of the ``config.py`` extraction. Every model here is self-contained: it
references no other config model and no module-level helper in ``config.py``.
Import these from ``probos.config``, which re-exports them.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PoolConfig(BaseModel):
    """Agent pool configuration."""

    default_pool_size: int = 3
    max_pool_size: int = 7
    min_pool_size: int = 2
    spawn_cooldown_ms: int = 500
    # BF-846: must be a real, finite cadence. ``0.0`` was accepted and turned
    # the health loop into a busy loop -- measured at 1,054 exception records
    # in 50 ms against one permanently unrecyclable member. A negative value is
    # an immediate ``wait_for`` timeout with the same effect, ``inf`` silently
    # disables health checking altogether, and a denormal such as ``5e-324``
    # reproduces the busy loop while satisfying "greater than zero". The floor
    # is a decision, not an inheritance: 100 checks per second is already far
    # past useful, and disabling the loop should be an explicit choice rather
    # than a typo in a YAML file.
    health_check_interval_seconds: float = Field(
        default=5.0, ge=0.01, allow_inf_nan=False,
        description=(
            "Seconds between pool health passes. Must be a finite value of at "
            "least 0.01; `inf` would silently disable health checking, which "
            "should be an explicit choice rather than a typo."
        ),
    )


class MeshConfig(BaseModel):
    """Mesh communication configuration."""

    gossip_interval_ms: int = 1000
    hebbian_decay_rate: float = 0.995
    # AD-571c v1: per-rel_type decay. SOCIAL weights persist longer than intent-routing
    # weights. Default falls back to hebbian_decay_rate so v1 is behavior-equivalent;
    # AD-571c-i forcing function flips this to 0.999 once AD-557 benchmarks land.
    hebbian_social_decay_rate: float = 0.995
    # AD-428b v1: Map intent_id -> skill_id for skill-weighted routing.
    # Empty dict (default) means skill weighting is off; the router returns
    # base_weight unchanged. Reread per call so config reload picks up changes.
    intent_skill_map: dict[str, str] = Field(default_factory=dict)
    hebbian_reward: float = 0.05
    signal_ttl_seconds: float = 30.0
    capability_broadcast_interval_seconds: float = 5.0
    semantic_matching: bool = True  # Enable semantic matching in CapabilityRegistry
    handler_latency_deterministic_ms: float = 100.0
    handler_latency_network_ms: float = 10_000.0
    handler_latency_cognitive_ms: float = 30_000.0

    @field_validator(
        "handler_latency_deterministic_ms",
        "handler_latency_network_ms",
        "handler_latency_cognitive_ms",
        mode="before",
    )
    @classmethod
    def _validate_handler_latency_threshold(cls, v: Any) -> float:
        if isinstance(v, bool):
            raise ValueError("handler latency thresholds must be finite positive numbers")
        try:
            threshold = float(v)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "handler latency thresholds must be finite positive numbers"
            ) from exc
        if not math.isfinite(threshold) or threshold <= 0.0:
            raise ValueError("handler latency thresholds must be finite positive numbers")
        return threshold


class ConsensusConfig(BaseModel):
    """Consensus layer configuration."""

    min_votes: int = 3
    approval_threshold: float = 0.6
    use_confidence_weights: bool = True
    verification_timeout_seconds: float = 5.0
    red_team_pool_size: int = 2
    trust_prior_alpha: float = 2.0  # Beta distribution prior successes
    trust_prior_beta: float = 2.0  # Beta distribution prior failures
    trust_decay_rate: float = 0.999  # Slow decay of trust observations


class ScalingConfig(BaseModel):
    """Adaptive pool scaling configuration."""

    enabled: bool = True
    scale_up_threshold: float = 0.8
    scale_down_threshold: float = 0.2
    scale_up_step: int = 1
    scale_down_step: int = 1
    cooldown_seconds: float = 30.0
    observation_window_seconds: float = 60.0
    idle_scale_down_seconds: float = 120.0


class CircuitBreakerConfig(BaseModel):
    """Cognitive circuit breaker thresholds (AD-506a)."""

    velocity_threshold: int = 8
    velocity_window_seconds: float = 300.0
    similarity_threshold: float = 0.6
    similarity_min_events: int = 4
    base_cooldown_seconds: float = 900.0
    max_cooldown_seconds: float = 3600.0
    # Amber zone thresholds
    amber_similarity_ratio: float = 0.25  # Amber when similarity pair ratio exceeds this
    amber_velocity_ratio: float = 0.6     # Amber when velocity > this fraction of threshold
    amber_decay_seconds: float = 900.0    # 15 min quiet -> amber decays to green
    red_decay_seconds: float = 1800.0     # 30 min quiet -> red decays to amber
    critical_decay_seconds: float = 3600.0  # 1h quiet -> critical decays to red
    critical_trip_window_seconds: float = 3600.0  # Window for counting trips toward critical
    critical_trip_count: int = 3           # Trips in window to reach critical


class ConcurrencyConfig(BaseModel):
    """AD-672: Per-agent concurrency management."""

    enabled: bool = True
    default_max_concurrent: int = 4
    queue_max_size: int = 10
    capacity_warning_ratio: float = 0.75
    role_overrides: dict[str, int] = Field(default_factory=lambda: {
        "bridge": 3,
        "operations": 6,
        "engineering": 5,
        "science": 4,
        "medical": 3,
        "security": 3,
    })


class EventLogConfig(BaseModel):
    """Event log retention configuration."""
    retention_days: int = 7          # Delete events older than N days (0 = keep forever)
    max_rows: int = 100_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0  # Check for pruning every N seconds


class SystemInfo(BaseModel):
    """Top-level system identity."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"
