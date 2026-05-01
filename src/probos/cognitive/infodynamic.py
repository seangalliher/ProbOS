"""AD-491: Infodynamic Telemetry — Information Entropy Instrumentation.

Periodic whole-system entropy measurement. Distinct from AD-557
emergence metrics (PID over Ward Room threads) — AD-491 measures
cross-system entropy trajectory consistent with Vopson 2023's Second
Law of Infodynamics.

Pure observability. No mutations. Reads runtime.event_log,
runtime.trust_network, runtime.registry; writes one report per cycle.
"""

from __future__ import annotations

import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntropySignal:
    """One entropy measurement over a named distribution."""

    name: str
    entropy: float
    sample_size: int
    bucket_count: int


@dataclass(frozen=True)
class InfodynamicReport:
    """One probe-cycle entropy snapshot."""

    generated_at: float
    signals: list[EntropySignal] = field(default_factory=list)
    total_entropy_bits: float = 0.0


def _shannon_entropy(counts: list[int]) -> float:
    """Shannon entropy in bits over a list of bucket counts."""
    total = sum(counts)
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


class InfodynamicProbe:
    """Periodic entropy measurement over runtime state.

    Stateless on construction. Each `analyze()` call produces a fresh
    `InfodynamicReport`. Caller is responsible for scheduling.

    Default signals:
      - event_log_category — Shannon entropy over event categories in a
        recent window.
      - trust_score_distribution — entropy over quantized trust scores.
      - agent_state_distribution — entropy over agent state values.
    """

    DEFAULT_TRUST_BUCKETS = 10

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        event_window_seconds: float = 3600.0,
        trust_buckets: int = DEFAULT_TRUST_BUCKETS,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._event_window = event_window_seconds
        self._trust_buckets = trust_buckets

    async def analyze(self) -> InfodynamicReport:
        """Compute one entropy snapshot. Does not mutate any source."""
        signals: list[EntropySignal] = []
        signals.append(await self._event_log_entropy())
        signals.append(self._trust_distribution_entropy())
        signals.append(self._agent_state_entropy())
        report = InfodynamicReport(
            generated_at=time.time(),
            signals=signals,
            total_entropy_bits=sum(s.entropy for s in signals),
        )
        self._emit(report)
        return report

    async def _event_log_entropy(self) -> EntropySignal:
        rt = self._runtime
        log = getattr(rt, "event_log", None) if rt else None
        if log is None:
            return EntropySignal(
                name="event_log_category",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        try:
            # AD-491: EventLog.query() does NOT accept `since=` (verified at
            # event_log.py:132 — signature is category/agent_id/limit only).
            # We pull the latest 10K rows and post-filter by timestamp.
            events = await log.query(limit=10_000)
        except Exception:
            logger.debug("AD-491: event_log query failed; entropy=0", exc_info=True)
            return EntropySignal(
                name="event_log_category",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        cutoff = time.time() - self._event_window
        windowed = [e for e in events if float(e.get("timestamp", 0) or 0) >= cutoff]
        categories = Counter(e.get("category", "") for e in windowed)
        h = _shannon_entropy(list(categories.values()))
        return EntropySignal(
            name="event_log_category",
            entropy=h,
            sample_size=sum(categories.values()),
            bucket_count=len(categories),
        )

    def _trust_distribution_entropy(self) -> EntropySignal:
        rt = self._runtime
        net = getattr(rt, "trust_network", None) if rt else None
        if net is None:
            return EntropySignal(
                name="trust_score_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        scores: list[float] = []
        registry = getattr(rt, "registry", None)
        if registry is None:
            return EntropySignal(
                name="trust_score_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        for agent in registry.all():
            try:
                s = net.get_score(getattr(agent, "id", ""))
                if isinstance(s, (int, float)):
                    scores.append(float(s))
            except Exception:
                continue
        if not scores:
            return EntropySignal(
                name="trust_score_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        bucket_counts = [0] * self._trust_buckets
        for s in scores:
            # Defensive clamp to [0, 1] in case a future trust subclass returns
            # a different range (current TrustNetwork.get_score returns Beta mean ∈ [0,1]).
            s = max(0.0, min(1.0, s))
            idx = min(self._trust_buckets - 1, int(s * self._trust_buckets))
            bucket_counts[idx] += 1
        h = _shannon_entropy(bucket_counts)
        return EntropySignal(
            name="trust_score_distribution",
            entropy=h,
            sample_size=len(scores),
            bucket_count=sum(1 for c in bucket_counts if c > 0),
        )

    def _agent_state_entropy(self) -> EntropySignal:
        rt = self._runtime
        registry = getattr(rt, "registry", None) if rt else None
        if registry is None:
            return EntropySignal(
                name="agent_state_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        states: Counter = Counter()
        for agent in registry.all():
            state = getattr(agent, "state", None)
            # AD-491: AgentState is an enum; use .value to match the canonical
            # wire format used elsewhere (e.g., substrate/agent.py:166).
            states[state.value if state is not None and hasattr(state, "value") else "unknown"] += 1
        h = _shannon_entropy(list(states.values()))
        return EntropySignal(
            name="agent_state_distribution",
            entropy=h,
            sample_size=sum(states.values()),
            bucket_count=len(states),
        )

    def _emit(self, report: InfodynamicReport) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.INFODYNAMIC_REPORT,
                {
                    "generated_at": report.generated_at,
                    "total_entropy_bits": report.total_entropy_bits,
                    "signals": [
                        {
                            "name": s.name,
                            "entropy": s.entropy,
                            "sample_size": s.sample_size,
                            "bucket_count": s.bucket_count,
                        }
                        for s in report.signals
                    ],
                },
            )
        except Exception:
            logger.warning("AD-491: INFODYNAMIC_REPORT emit failed", exc_info=True)
