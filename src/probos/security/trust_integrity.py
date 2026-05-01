"""AD-455: Trust integrity monitor — burst-vote and coordinated-attack detection.

Stateless analyzer that takes a TrustNetwork reference and a recent-events
window. Reads derived signals only — does not touch raw (alpha, beta) storage.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrustViolation:
    kind: str
    agents_involved: tuple[str, ...]
    evidence: str
    severity: float
    detected_at: float


@dataclass(frozen=True)
class TrustIntegrityReport:
    violations: list[TrustViolation]
    generated_at: float
    sample_size: int


class TrustIntegrityMonitor:
    """Detect coordinated trust manipulation patterns.

    Read-only on TrustNetwork derived state. Three heuristic checks are
    framed for v1 (burst_vote, mutual_loop, anomalous_velocity); detection
    logic is wired in AD-455b once event-log query patterns are decided.
    The framework (config, public API, event types, wiring) is complete
    so AD-455b is an additive-only follow-up.

    v1 returns an empty report.
    """

    def __init__(
        self,
        *,
        trust_network: Any,
        event_log: Any,
        emit_event: Any | None = None,
        burst_window_seconds: float = 60.0,
        burst_threshold: int = 20,
        cycle_min_weight: float = 0.85,
    ) -> None:
        self._trust = trust_network
        self._event_log = event_log
        self._emit_event = emit_event
        self._burst_window = burst_window_seconds
        self._burst_threshold = burst_threshold
        self._cycle_min_weight = cycle_min_weight

    def analyze(self) -> TrustIntegrityReport:
        """Produce a violation report. Does not mutate any source."""
        now = time.time()
        violations: list[TrustViolation] = []
        report = TrustIntegrityReport(
            violations=violations,
            generated_at=now,
            sample_size=0,
        )
        for v in violations:
            self._emit(v)
        return report

    def _emit(self, violation: TrustViolation) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.TRUST_INTEGRITY_VIOLATION,
                {
                    "kind": violation.kind,
                    "agents_involved": list(violation.agents_involved),
                    "evidence": violation.evidence,
                    "severity": violation.severity,
                },
            )
        except Exception:
            logger.warning(
                "AD-455: TRUST_INTEGRITY_VIOLATION emit failed",
                exc_info=True,
            )
