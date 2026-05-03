"""AD-641f: EngineeringSensorBundle -- frozen sensor snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EngineeringSensorBundle:
    captured_at: float
    pool_summary: dict[str, dict[str, Any]] = field(default_factory=dict)
    capability_summary: dict[str, Any] = field(default_factory=dict)
    gossip_summary: dict[str, Any] = field(default_factory=dict)
