"""Bridge Alerts — proactive notifications to Ward Room & Captain (AD-410).

Monitors ship systems (VitalsMonitor, EmergentDetector, BehavioralMonitor,
TrustNetwork) and posts significant events to the Ward Room as threads.
Crew agents respond naturally via existing AD-407d mechanics.

No LLM calls — purely mechanical threshold checking with deduplication.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Bridge Alert severity levels."""
    INFO = "info"          # Department channel, no Captain notification
    ADVISORY = "advisory"  # All Hands, info notification to Captain
    ALERT = "alert"        # All Hands, action_required notification to Captain


@dataclass
class BridgeAlert:
    """A single bridge alert ready for delivery."""
    id: str
    severity: AlertSeverity
    source: str              # "vitals_monitor", "emergent_detector", etc.
    alert_type: str          # "pool_health_warning", "trust_drop", etc.
    title: str
    detail: str
    department: str | None   # For info-severity routing to department channel
    dedup_key: str
    timestamp: float = field(default_factory=time.time)
    related_agent_id: str | None = None
    related_pool: str | None = None


class BridgeAlertService:
    """Evaluates monitoring signals and produces alerts for Ward Room + notifications.

    The service itself does NOT post to the Ward Room — it returns BridgeAlert
    objects that the runtime delivers via _deliver_bridge_alert().
    """

    def __init__(
        self,
        cooldown_seconds: float = 300,
        trust_drop_threshold: float = 0.15,
        trust_drop_alert_threshold: float = 0.25,
    ) -> None:
        self._cooldown = cooldown_seconds
        self._trust_drop_threshold = trust_drop_threshold
        self._trust_drop_alert = trust_drop_alert_threshold
        self._recent: dict[str, float] = {}     # dedup_key -> monotonic timestamp
        self._alert_log: list[BridgeAlert] = []
        self._max_log = 200

    def _should_emit(self, dedup_key: str) -> bool:
        """Check dedup cache. Returns True if alert should fire."""
        now = time.monotonic()
        last = self._recent.get(dedup_key)
        if last is not None and now - last < self._cooldown:
            return False
        self._recent[dedup_key] = now
        # Prune expired entries
        cutoff = now - self._cooldown * 2
        self._recent = {k: v for k, v in self._recent.items() if v > cutoff}
        return True

    def _record(self, alert: BridgeAlert) -> None:
        """Add alert to the ring buffer log."""
        self._alert_log.append(alert)
        if len(self._alert_log) > self._max_log:
            self._alert_log = self._alert_log[-self._max_log:]

    # --- Signal processors ---

    def check_vitals(self, vitals_data: dict) -> list[BridgeAlert]:
        """Process VitalsMonitor snapshot data. Returns alerts to emit.

        Expected vitals_data keys:
            pool_health: dict[str, float]   -- pool_name -> health ratio (0-1)
            system_health: float | None     -- overall system health (0-1)
            trust_outlier_count: int        -- number of agents below trust floor
        """
        alerts: list[BridgeAlert] = []

        # Pool health checks
        for pool_name, health in vitals_data.get("pool_health", {}).items():
            if health < 0.25:
                key = f"pool_health_critical:{pool_name}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()), severity=AlertSeverity.ALERT,
                        source="vitals_monitor", alert_type="pool_health_critical",
                        title=f"Pool '{pool_name}' Critical \u2014 {int(health * 100)}% capacity",
                        detail=(
                            f"Pool '{pool_name}' has dropped to {int(health * 100)}% of target capacity. "
                            f"Agents may be degraded or failing to spawn."
                        ),
                        department="engineering", dedup_key=key,
                        related_pool=pool_name,
                    )
                    self._record(a)
                    alerts.append(a)
            elif health < 0.5:
                key = f"pool_health_warning:{pool_name}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()), severity=AlertSeverity.ADVISORY,
                        source="vitals_monitor", alert_type="pool_health_warning",
                        title=f"Pool '{pool_name}' Degraded \u2014 {int(health * 100)}% capacity",
                        detail=f"Pool '{pool_name}' is running at {int(health * 100)}% of target capacity.",
                        department="engineering", dedup_key=key,
                        related_pool=pool_name,
                    )
                    self._record(a)
                    alerts.append(a)

        # System health checks
        sys_health = vitals_data.get("system_health")
        if sys_health is not None:
            if sys_health < 0.3:
                key = "system_health_critical"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()), severity=AlertSeverity.ALERT,
                        source="vitals_monitor", alert_type="system_health_critical",
                        title=f"System Health Critical \u2014 {sys_health:.2f}",
                        detail=(
                            f"Overall system health has dropped to {sys_health:.2f}. "
                            f"Multiple agent pools may be affected."
                        ),
                        department=None, dedup_key=key,
                    )
                    self._record(a)
                    alerts.append(a)
            elif sys_health < 0.6:
                key = "system_health_warning"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()), severity=AlertSeverity.ADVISORY,
                        source="vitals_monitor", alert_type="system_health_warning",
                        title=f"System Health Warning \u2014 {sys_health:.2f}",
                        detail=f"Overall system health is at {sys_health:.2f}.",
                        department=None, dedup_key=key,
                    )
                    self._record(a)
                    alerts.append(a)

        # Trust outlier checks
        outlier_count = vitals_data.get("trust_outlier_count", 0)
        if outlier_count > 3:
            key = f"trust_outliers:{outlier_count}"
            if self._should_emit(key):
                a = BridgeAlert(
                    id=str(uuid.uuid4()), severity=AlertSeverity.ADVISORY,
                    source="vitals_monitor", alert_type="trust_outliers",
                    title=f"Multiple Trust Outliers Detected ({outlier_count} agents)",
                    detail=(
                        f"{outlier_count} agents are below the trust floor. "
                        f"This may indicate systemic task difficulty or environmental changes."
                    ),
                    department=None, dedup_key=key,
                )
                self._record(a)
                alerts.append(a)

        return alerts

    def check_trust_change(
        self, agent_id: str, old_score: float, new_score: float,
    ) -> BridgeAlert | None:
        """Check if a trust change is significant enough to alert.

        Args:
            agent_id: The agent whose trust changed.
            old_score: Trust score before the change.
            new_score: Trust score after the change.

        Returns:
            A BridgeAlert if the drop exceeds the threshold, else None.
        """
        drop = old_score - new_score
        if drop < self._trust_drop_threshold:
            return None

        if drop >= self._trust_drop_alert:
            severity = AlertSeverity.ALERT
            alert_type = "trust_drop_alert"
        else:
            severity = AlertSeverity.ADVISORY
            alert_type = "trust_drop_advisory"

        key = f"trust_drop:{agent_id}"
        if not self._should_emit(key):
            return None

        a = BridgeAlert(
            id=str(uuid.uuid4()), severity=severity,
            source="trust_network", alert_type=alert_type,
            title=f"Trust Drop \u2014 {agent_id[:20]} ({old_score:.2f} \u2192 {new_score:.2f})",
            detail=f"Agent {agent_id} experienced a trust drop of {drop:.2f} in a single event.",
            department=None, dedup_key=key,
            related_agent_id=agent_id,
        )
        self._record(a)
        return a

    def check_emergent_patterns(self, patterns: list) -> list[BridgeAlert]:
        """Process EmergentDetector patterns. Returns alerts to emit.

        Args:
            patterns: List of EmergentPattern objects from the detector.
        """
        alerts: list[BridgeAlert] = []
        for p in patterns:
            ptype = getattr(p, "pattern_type", "")
            severity_str = getattr(p, "severity", "info")
            desc = getattr(p, "description", str(p))

            if ptype == "trust_anomaly" and severity_str in ("significant", "notable"):
                sev = AlertSeverity.ADVISORY
            elif ptype == "cooperation_cluster":
                sev = AlertSeverity.INFO
            elif ptype == "routing_shift" and severity_str == "significant":
                sev = AlertSeverity.ADVISORY
            else:
                continue  # Skip info-level or unknown patterns

            key = f"emergent:{ptype}"
            if not self._should_emit(key):
                continue

            dept = None
            if ptype == "cooperation_cluster":
                dept = "science"

            a = BridgeAlert(
                id=str(uuid.uuid4()), severity=sev,
                source="emergent_detector", alert_type=f"emergent_{ptype}",
                title=f"{ptype.replace('_', ' ').title()} Detected",
                detail=desc, department=dept, dedup_key=key,
            )
            self._record(a)
            alerts.append(a)

        return alerts

    def check_behavioral(self, behavioral_monitor: Any) -> list[BridgeAlert]:
        """Check BehavioralMonitor for actionable alerts.

        Args:
            behavioral_monitor: The BehavioralMonitor instance.
        """
        alerts: list[BridgeAlert] = []
        if not behavioral_monitor:
            return alerts

        for alert in behavioral_monitor.get_alerts():
            atype = getattr(alert, "alert_type", "")
            agent_type = getattr(alert, "agent_type", "unknown")

            if atype == "high_failure_rate":
                key = f"behavioral_failure:{agent_type}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()), severity=AlertSeverity.ADVISORY,
                        source="behavioral_monitor", alert_type="behavioral_failure",
                        title=f"High Failure Rate \u2014 {agent_type}",
                        detail=getattr(
                            alert, "detail",
                            f"Agent type {agent_type} is experiencing a high failure rate (>50%).",
                        ),
                        department="engineering", dedup_key=key,
                    )
                    self._record(a)
                    alerts.append(a)

        # Check for removal recommendations
        status = behavioral_monitor.get_status()
        for agent_type_key in status:
            if behavioral_monitor.should_recommend_removal(agent_type_key):
                key = f"behavioral_removal:{agent_type_key}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()), severity=AlertSeverity.ALERT,
                        source="behavioral_monitor", alert_type="behavioral_removal",
                        title=f"Agent Removal Recommended \u2014 {agent_type_key}",
                        detail=(
                            f"Agent type '{agent_type_key}' has sustained failure rates "
                            f"warranting removal consideration."
                        ),
                        department="engineering", dedup_key=key,
                    )
                    self._record(a)
                    alerts.append(a)

        return alerts

    def check_llm_health(self, llm_health: dict) -> list[BridgeAlert]:
        """BF-069: Evaluate LLM proxy health and emit bridge alerts."""
        alerts: list[BridgeAlert] = []
        overall = llm_health.get("overall", "unknown")
        tiers = llm_health.get("tiers", {})

        if overall == "offline":
            key = "llm_offline"
            if self._should_emit(key):
                a = BridgeAlert(
                    id=str(uuid.uuid4()),
                    severity=AlertSeverity.ALERT,
                    source="llm_client",
                    alert_type="llm_offline",
                    title="Communications Array Offline",
                    detail="All LLM tiers unreachable. Crew cognitive functions suspended. Check Copilot proxy at 127.0.0.1:8080.",
                    department=None,
                    dedup_key=key,
                )
                self._record(a)
                alerts.append(a)
        elif overall == "degraded":
            unreachable = [t for t, info in tiers.items() if info.get("status") == "unreachable"]
            if unreachable:
                key = f"llm_degraded_{'_'.join(sorted(unreachable))}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()),
                        severity=AlertSeverity.ADVISORY,
                        source="llm_client",
                        alert_type="llm_degraded",
                        title="Communications Array Degraded",
                        detail=f"LLM tier(s) unreachable: {', '.join(unreachable)}. Remaining tiers operational. Fallback routing active.",
                        department=None,
                        dedup_key=key,
                    )
                    self._record(a)
                    alerts.append(a)

        return alerts

    def check_convergence(self, convergence_data: dict) -> list[BridgeAlert]:
        """AD-551: Evaluate cross-agent convergence and emit bridge alerts."""
        alerts: list[BridgeAlert] = []
        reports_generated = convergence_data.get("convergence_reports_generated", 0)
        if reports_generated <= 0:
            return alerts
        reports = convergence_data.get("convergence_reports", [])
        for report in reports:
            topic = report.get("topic", "unknown")
            agents = report.get("agents", [])
            departments = report.get("departments", [])
            key = f"convergence:{topic}"
            if self._should_emit(key):
                a = BridgeAlert(
                    id=str(uuid.uuid4()),
                    severity=AlertSeverity.ADVISORY,
                    source="dream_consolidation",
                    alert_type="convergence_detected",
                    title="Crew Convergence Detected",
                    detail=(
                        f"{len(agents)} agents from {len(departments)} departments "
                        f"independently reached convergent conclusions on {topic}"
                    ),
                    department=None,
                    dedup_key=key,
                )
                self._record(a)
                alerts.append(a)
        return alerts

    def check_realtime_convergence(self, conv_result: dict) -> list[BridgeAlert]:
        """AD-554: Evaluate real-time cross-agent convergence and emit bridge alerts."""
        alerts: list[BridgeAlert] = []
        if not conv_result.get("convergence_detected"):
            return alerts

        topic = conv_result.get("convergence_topic", "unknown")
        agents = conv_result.get("convergence_agents", [])
        departments = conv_result.get("convergence_departments", [])
        key = f"realtime_convergence:{topic}"

        if self._should_emit(key):
            a = BridgeAlert(
                id=str(uuid.uuid4()),
                severity=AlertSeverity.ADVISORY,
                source="notebook_monitor",
                alert_type="realtime_convergence_detected",
                title="Real-Time Crew Convergence",
                detail=(
                    f"{len(agents)} agents from {len(departments)} departments "
                    f"independently reached convergent conclusions on {topic}"
                ),
                department=None,
                dedup_key=key,
            )
            self._record(a)
            alerts.append(a)
        return alerts

    def check_divergence(self, divergence_data: dict) -> list[BridgeAlert]:
        """AD-554: Evaluate cross-agent divergence and emit bridge alerts."""
        alerts: list[BridgeAlert] = []
        if not divergence_data.get("divergence_detected"):
            return alerts

        topic = divergence_data.get("divergence_topic", "unknown")
        agents = divergence_data.get("divergence_agents", [])
        departments = divergence_data.get("divergence_departments", [])
        similarity = divergence_data.get("divergence_similarity", 0.0)
        key = f"divergence:{topic}"

        if self._should_emit(key):
            a = BridgeAlert(
                id=str(uuid.uuid4()),
                severity=AlertSeverity.ADVISORY,
                source="notebook_monitor",
                alert_type="divergence_detected",
                title="Cross-Department Divergence",
                detail=(
                    f"{', '.join(agents)} from {', '.join(departments)} "
                    f"reached different conclusions on {topic} "
                    f"(similarity={similarity:.2f})"
                ),
                department=None,
                dedup_key=key,
            )
            self._record(a)
            alerts.append(a)
        return alerts

    def check_notebook_quality(self, quality_snapshot: dict) -> list[BridgeAlert]:
        """AD-555: Check notebook quality metrics for alert conditions."""
        alerts: list[BridgeAlert] = []
        score = quality_snapshot.get("system_quality_score", 1.0)
        stale_rate = quality_snapshot.get("stale_entry_rate", 0.0)

        # Read thresholds from snapshot (caller passes config values)
        low_threshold = quality_snapshot.get("_low_threshold", 0.3)
        warn_threshold = quality_snapshot.get("_warn_threshold", 0.5)
        staleness_alert_rate = quality_snapshot.get("_staleness_alert_rate", 0.7)

        if score < low_threshold:
            key = "notebook_quality_low"
            if self._should_emit(key):
                a = BridgeAlert(
                    id=str(uuid.uuid4()),
                    severity=AlertSeverity.ALERT,
                    source="notebook_quality",
                    alert_type="notebook_quality_low",
                    title="Notebook quality critically low",
                    detail=f"System notebook quality score {score:.2f} — high noise, low signal across crew notebooks",
                    department=None,
                    dedup_key=key,
                )
                self._record(a)
                alerts.append(a)
        elif score < warn_threshold:
            key = "notebook_quality_degraded"
            if self._should_emit(key):
                a = BridgeAlert(
                    id=str(uuid.uuid4()),
                    severity=AlertSeverity.ADVISORY,
                    source="notebook_quality",
                    alert_type="notebook_quality_degraded",
                    title="Notebook quality degraded",
                    detail=f"System notebook quality score {score:.2f} — recommend reviewing agent observation triggers",
                    department=None,
                    dedup_key=key,
                )
                self._record(a)
                alerts.append(a)

        if stale_rate > staleness_alert_rate:
            key = "notebook_staleness_high"
            if self._should_emit(key):
                a = BridgeAlert(
                    id=str(uuid.uuid4()),
                    severity=AlertSeverity.ADVISORY,
                    source="notebook_quality",
                    alert_type="notebook_staleness_high",
                    title="High notebook staleness",
                    detail=f"{stale_rate:.0%} of notebook entries are stale — crew may not be actively observing",
                    department=None,
                    dedup_key=key,
                )
                self._record(a)
                alerts.append(a)

        # Per-agent quality alerts
        for agent in quality_snapshot.get("per_agent", []):
            if isinstance(agent, dict):
                aq_score = agent.get("quality_score", 1.0)
                aq_callsign = agent.get("callsign", "unknown")
            else:
                aq_score = getattr(agent, "quality_score", 1.0)
                aq_callsign = getattr(agent, "callsign", "unknown")

            if aq_score < 0.25:
                key = f"agent_quality_low_{aq_callsign}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()),
                        severity=AlertSeverity.INFO,
                        source="notebook_quality",
                        alert_type="agent_quality_low",
                        title=f"{aq_callsign}: notebook quality low",
                        detail=f"{aq_callsign} quality score {aq_score:.2f} — may need different observation triggers",
                        department=None,
                        dedup_key=key,
                    )
                    self._record(a)
                    alerts.append(a)

        return alerts

    def get_recent_alerts(self, limit: int = 50) -> list[BridgeAlert]:
        """Return recent alerts for status/API exposure."""
        return self._alert_log[-limit:]
