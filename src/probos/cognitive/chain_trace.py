"""ChainExecutionTrace — per-step harness measurement record (AD-658).

One row per cognitive-chain step. Captures latency, token usage, context
composition breakdown, and active modulation parameters for downstream
optimization analysis (AD-659). Forward-only; not retroactive.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ChainExecutionTrace:
    """Single-step harness trace. Frozen — emit once at step completion."""

    # Chain / step identity
    chain_id: str
    step_index: int
    step_name: str
    sub_task_type: str
    tier: str
    chain_source: str = ""

    # Caller identity
    agent_id: str = ""
    agent_type: str = ""
    intent: str = ""
    intent_id: str = ""

    # Wall-clock + execution
    started_at: float = 0.0
    duration_ms: float = 0.0
    tokens_used: int = 0
    success: bool = True
    error_truncated: str = ""

    # Context composition breakdown
    context_keys_declared: int = 0
    context_keys_passed: int = 0
    context_filter_applied: bool = False

    # Modulation snapshot (AD-649 / AD-639 / AD-638)
    communication_context: str | None = None
    chain_trust_band: str | None = None
    trust_score: float | None = None
    boot_camp_active: bool = False
    from_captain: bool = False
    is_dm: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict projection for JSON serialization and DB row binding."""
        return asdict(self)
