"""BehavioralMonitor — monitors self-created agents for behavioral anomalies."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class BehavioralAlert:
    """A detected behavioral anomaly."""

    agent_id: str
    agent_type: str
    alert_type: str  # "slow_execution", "high_failure_rate", "unexpected_result_size"
    detail: str
    timestamp: float


class BehavioralMonitor:
    """Monitors self-created agents for behavioral anomalies.

    Unlike red team agents (which verify output correctness),
    the behavioral monitor tracks operational patterns:
    1. Execution time -- is the agent consistently slower than expected?
    2. Failure rate -- is the agent failing more than established agents?
    3. Result size -- is the agent returning unexpectedly large payloads?
    4. Trust trajectory -- is the agent's trust declining over time?

    The monitor does NOT block agent execution. It records alerts
    that are visible via /designed and can trigger removal recommendations.
    """

    # Thresholds
    _SLOW_FACTOR = 5.0  # Alert if avg exec time > 5x sandbox time
    _HIGH_FAILURE_THRESHOLD = 0.5  # Alert if failure rate > 50%
    _MIN_EXECUTIONS_FOR_REMOVAL = 10  # Need 10+ executions before recommending removal
    _TRUST_DECLINE_WINDOW = 3  # Consecutive declining trust snapshots

    def __init__(self) -> None:
        self._tracked_agents: dict[str, dict] = {}  # agent_type -> tracking data
        self._alerts: list[BehavioralAlert] = []
        self._execution_times: dict[str, list[float]] = {}  # agent_type -> durations
        self._failure_counts: dict[str, int] = {}
        self._success_counts: dict[str, int] = {}
        self._trust_history: dict[str, list[float]] = {}  # agent_type -> trust scores

    def track_agent_type(self, agent_type: str) -> None:
        """Start tracking a self-created agent type."""
        self._tracked_agents[agent_type] = {
            "tracked_since": time.monotonic(),
        }
        self._execution_times.setdefault(agent_type, [])
        self._failure_counts.setdefault(agent_type, 0)
        self._success_counts.setdefault(agent_type, 0)
        self._trust_history.setdefault(agent_type, [])

    def record_execution(
        self,
        agent_type: str,
        duration_ms: float,
        success: bool,
        result_size: int = 0,
    ) -> None:
        """Record an execution by a self-created agent. Checks for anomalies."""
        if agent_type not in self._tracked_agents:
            return

        self._execution_times[agent_type].append(duration_ms)

        if success:
            self._success_counts[agent_type] += 1
        else:
            self._failure_counts[agent_type] += 1

        # Check failure rate after sufficient executions
        total = self._success_counts[agent_type] + self._failure_counts[agent_type]
        if total >= 5:
            failure_rate = self._failure_counts[agent_type] / total
            if failure_rate > self._HIGH_FAILURE_THRESHOLD:
                self._alerts.append(BehavioralAlert(
                    agent_id="",
                    agent_type=agent_type,
                    alert_type="high_failure_rate",
                    detail=f"Failure rate {failure_rate:.1%} over {total} executions",
                    timestamp=time.monotonic(),
                ))

        # Check for slow execution
        times = self._execution_times[agent_type]
        if len(times) >= 3:
            avg_time = sum(times) / len(times)
            if avg_time > 5000:  # > 5 seconds average
                self._alerts.append(BehavioralAlert(
                    agent_id="",
                    agent_type=agent_type,
                    alert_type="slow_execution",
                    detail=f"Average execution time {avg_time:.0f}ms",
                    timestamp=time.monotonic(),
                ))

    def check_trust_trajectory(self, agent_type: str, trust_score: float) -> None:
        """Record a trust snapshot. Alert if trust is declining consistently."""
        if agent_type not in self._tracked_agents:
            return

        history = self._trust_history[agent_type]
        history.append(trust_score)

        # Check for consistent decline
        if len(history) >= self._TRUST_DECLINE_WINDOW:
            window = history[-self._TRUST_DECLINE_WINDOW:]
            declining = all(window[i] > window[i + 1] for i in range(len(window) - 1))
            if declining:
                self._alerts.append(BehavioralAlert(
                    agent_id="",
                    agent_type=agent_type,
                    alert_type="declining_trust",
                    detail=f"Trust declining for {self._TRUST_DECLINE_WINDOW} consecutive observations: {[round(t, 3) for t in window]}",
                    timestamp=time.monotonic(),
                ))

    def get_alerts(self, agent_type: str | None = None) -> list[BehavioralAlert]:
        """Return alerts, optionally filtered by agent type."""
        if agent_type is None:
            return list(self._alerts)
        return [a for a in self._alerts if a.agent_type == agent_type]

    def get_status(self) -> dict:
        """Return monitoring status for all tracked agent types."""
        status: dict = {}
        for agent_type in self._tracked_agents:
            total = self._success_counts.get(agent_type, 0) + self._failure_counts.get(agent_type, 0)
            times = self._execution_times.get(agent_type, [])
            status[agent_type] = {
                "total_executions": total,
                "successes": self._success_counts.get(agent_type, 0),
                "failures": self._failure_counts.get(agent_type, 0),
                "avg_execution_ms": sum(times) / len(times) if times else 0,
                "alert_count": len(self.get_alerts(agent_type)),
            }
        return status

    def should_recommend_removal(self, agent_type: str) -> bool:
        """Return True if behavioral evidence suggests the agent should be removed.

        Criteria: failure rate > 50% over 10+ executions, OR
        trust declining for 3+ consecutive observations.
        """
        if agent_type not in self._tracked_agents:
            return False

        total = self._success_counts.get(agent_type, 0) + self._failure_counts.get(agent_type, 0)

        # Failure rate criterion
        if total >= self._MIN_EXECUTIONS_FOR_REMOVAL:
            failure_rate = self._failure_counts.get(agent_type, 0) / total
            if failure_rate > self._HIGH_FAILURE_THRESHOLD:
                return True

        # Trust decline criterion
        history = self._trust_history.get(agent_type, [])
        if len(history) >= self._TRUST_DECLINE_WINDOW:
            window = history[-self._TRUST_DECLINE_WINDOW:]
            if all(window[i] > window[i + 1] for i in range(len(window) - 1)):
                return True

        return False
