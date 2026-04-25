# AD-410: Bridge Alerts — Proactive Captain & Crew Notifications

## Context

ProbOS has three monitoring systems that actively detect anomalies — VitalsMonitor (pool health, system health, trust outliers), EmergentDetector (trust anomalies, cooperation clusters, routing shifts), and BehavioralMonitor (failure rates, declining trust) — but none of them surface findings to the Captain or crew. The Ward Room (AD-407) is live with full agent-to-agent conversation capability, but agents are purely reactive.

Bridge Alerts is the first step toward autonomous crew communication: event-driven alerts posted to the Ward Room as threads, which crew agents then discuss organically via existing AD-407d mechanics. No LLM cost for the alert itself — it's mechanical threshold checking.

**Goal:** When something significant happens on the ship, the Ship's Computer posts an alert to the Ward Room. Crew agents respond naturally. The Captain gets a notification for advisory/alert severity.

## Design Summary

### Severity Levels

| Severity | Ward Room Channel | Captain Notification |
|----------|-------------------|---------------------|
| `info` | Department channel | None |
| `advisory` | All Hands (ship) | `info` notification |
| `alert` | All Hands (ship) | `action_required` notification |

### Author Attribution

All alerts post as `author_id="captain"` with `author_callsign="Ship's Computer"`. This gives Captain-level routing (all crew notified on ship channels, department members on department channels).

### Deduplication

Key format: `"{alert_type}:{subject}"`. Same key within `cooldown_seconds` (default 300s) → suppressed.

---

## Part 1: Config — `src/probos/config.py` + `config/system.yaml`

### config.py

Insert `BridgeAlertConfig` after `AssignmentConfig` (line ~281):

```python
class BridgeAlertConfig(BaseModel):
    """Bridge Alerts — proactive Captain & crew notifications (AD-410)."""
    enabled: bool = False
    cooldown_seconds: float = 300        # Dedup window per alert type+subject
    trust_drop_threshold: float = 0.15   # Trust drop triggering advisory
    trust_drop_alert_threshold: float = 0.25  # Trust drop triggering alert
```

Add to `SystemConfig` (line ~339, after `assignments`):

```python
bridge_alerts: BridgeAlertConfig = BridgeAlertConfig()
```

### system.yaml

Add after the `assignments` block:

```yaml
bridge_alerts:
  enabled: true
  cooldown_seconds: 300
  trust_drop_threshold: 0.15
  trust_drop_alert_threshold: 0.25
```

---

## Part 2: Service — NEW `src/probos/bridge_alerts.py`

Create this file with the complete `BridgeAlertService`:

```python
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

    def get_recent_alerts(self, limit: int = 50) -> list[BridgeAlert]:
        """Return recent alerts for status/API exposure."""
        return self._alert_log[-limit:]
```

---

## Part 3: Runtime Wiring — `src/probos/runtime.py`

### 3a. New attribute (line ~213, alongside `self.ward_room`)

Add:

```python
self.bridge_alerts: Any | None = None  # AD-410
```

### 3b. Initialization (line ~1195, after Assignment Service init)

Add after the assignment service block:

```python
# --- Bridge Alerts (AD-410) ---
if self.config.bridge_alerts.enabled and self.ward_room:
    from probos.bridge_alerts import BridgeAlertService
    self.bridge_alerts = BridgeAlertService(
        cooldown_seconds=self.config.bridge_alerts.cooldown_seconds,
        trust_drop_threshold=self.config.bridge_alerts.trust_drop_threshold,
        trust_drop_alert_threshold=self.config.bridge_alerts.trust_drop_alert_threshold,
    )
    logger.info("bridge-alerts started")
```

### 3c. New private method `_deliver_bridge_alert()`

Add as a new method on the runtime class (near other Ward Room methods):

```python
async def _deliver_bridge_alert(self, alert) -> None:
    """Post a Bridge Alert to the Ward Room and optionally notify the Captain (AD-410)."""
    from probos.bridge_alerts import AlertSeverity

    if not self.ward_room:
        return

    # Determine target channel
    channels = await self.ward_room.list_channels()
    if alert.severity == AlertSeverity.INFO and alert.department:
        channel = next((c for c in channels if c.department == alert.department), None)
    else:
        channel = next((c for c in channels if c.channel_type == "ship"), None)

    if not channel:
        logger.warning("Bridge alert: no suitable channel for %s", alert.alert_type)
        return

    # Post as Ship's Computer (captain author_id for proper crew routing)
    try:
        await self.ward_room.create_thread(
            channel_id=channel.id,
            author_id="captain",
            title=f"[{alert.severity.value.upper()}] {alert.title}",
            body=alert.detail,
            author_callsign="Ship's Computer",
        )
    except Exception as e:
        logger.warning("Bridge alert WR post failed: %s", e)
        return

    # Captain notification for advisory/alert severity
    if alert.severity in (AlertSeverity.ADVISORY, AlertSeverity.ALERT):
        notif_type = "action_required" if alert.severity == AlertSeverity.ALERT else "info"
        self.notify(
            agent_id=alert.related_agent_id or "system",
            title=alert.title,
            detail=alert.detail,
            notification_type=notif_type,
        )

    await self.event_log.log(
        category="bridge_alert",
        event=alert.alert_type,
        detail=f"severity={alert.severity.value} {alert.title}",
    )
```

### 3d. Trust change hook — TWO locations

**Location 1:** Around line 1509-1522 (consensus verification). Before `self.trust_network.record_outcome(...)`, capture old score. After `self._emit_event("trust_update", ...)`, add the bridge alert check.

The pattern:
```python
# BEFORE record_outcome:
_old_trust = self.trust_network.get_score(result.agent_id)  # AD-410
# ... existing record_outcome call ...
# ... existing _emit_event("trust_update", ...) ...

# AFTER _emit_event("trust_update", ...):
# AD-410: Bridge Alert on significant trust drop
if self.bridge_alerts:
    _trust_alert = self.bridge_alerts.check_trust_change(
        result.agent_id, _old_trust,
        self.trust_network.get_score(result.agent_id),
    )
    if _trust_alert:
        asyncio.create_task(self._deliver_bridge_alert(_trust_alert))
```

**Location 2:** Around line 3805-3814 (QA test trust updates). Same pattern — capture old score before `record_outcome`, check after `_emit_event`. Note: at this location the agent_id variable is `aid`, not `result.agent_id`.

### 3e. Post-dream hook — `_on_post_dream()` (around line 2996)

After the existing emergent pattern logging loop (after line 3015), add three blocks:

```python
# AD-410: Bridge Alerts from emergent patterns
if self.bridge_alerts and patterns:
    emergent_alerts = self.bridge_alerts.check_emergent_patterns(patterns)
    for ea in emergent_alerts:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._deliver_bridge_alert(ea))
        except RuntimeError:
            pass

# AD-410: Bridge Alerts from behavioral monitor
if self.bridge_alerts and self._behavioral_monitor:
    behavioral_alerts = self.bridge_alerts.check_behavioral(self._behavioral_monitor)
    for ba in behavioral_alerts:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._deliver_bridge_alert(ba))
        except RuntimeError:
            pass

# AD-410: Bridge Alerts from vitals snapshot
if self.bridge_alerts:
    vitals_agent = None
    for agent in self.registry.get_by_pool("medical_vitals"):
        if hasattr(agent, "_window") and agent._window:
            vitals_agent = agent
            break
    if vitals_agent and vitals_agent._window:
        latest = vitals_agent._window[-1]
        vitals_data = {
            "pool_health": latest.get("pool_health", {}),
            "system_health": latest.get("system_health"),
            "trust_outlier_count": len(latest.get("trust_outliers", [])),
        }
        vitals_alerts = self.bridge_alerts.check_vitals(vitals_data)
        for va in vitals_alerts:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._deliver_bridge_alert(va))
            except RuntimeError:
                pass
```

### 3f. State snapshot — `build_state_snapshot()` (around line 466)

Add to the snapshot dict:

```python
"bridge_alerts": {
    "recent": [
        {"id": a.id, "severity": a.severity.value, "title": a.title, "timestamp": a.timestamp}
        for a in (self.bridge_alerts.get_recent_alerts(10) if self.bridge_alerts else [])
    ],
} if self.bridge_alerts else None,
```

---

## Part 4: Tests — NEW `tests/test_bridge_alerts.py`

Create comprehensive tests (~25-30 tests across 8-10 classes):

### Test Classes

**TestAlertSeverity** (2 tests):
- `test_severity_values` — INFO="info", ADVISORY="advisory", ALERT="alert"
- `test_severity_string_conversion` — str(AlertSeverity.ALERT) contains "alert"

**TestBridgeAlert** (2 tests):
- `test_alert_creation` — all fields populated correctly
- `test_alert_defaults` — timestamp auto-populated, optional fields default to None

**TestDeduplication** (3 tests):
- `test_same_key_suppressed` — second alert with same key within cooldown returns empty
- `test_different_key_passes` — different keys both emit
- `test_expired_key_re_emits` — after cooldown expires, same key fires again (use monkeypatch on `time.monotonic`)

**TestVitalsAlerts** (5 tests):
- `test_pool_health_warning` — health=0.4 → advisory
- `test_pool_health_critical` — health=0.2 → alert
- `test_pool_health_ok` — health=0.8 → no alert
- `test_system_health_warning` — 0.5 → advisory
- `test_system_health_critical` — 0.2 → alert
- `test_trust_outliers` — count=5 → advisory, count=2 → no alert

**TestTrustChangeAlerts** (4 tests):
- `test_below_threshold_no_alert` — drop of 0.05 → None
- `test_advisory_threshold` — drop of 0.16 → advisory
- `test_alert_threshold` — drop of 0.26 → alert
- `test_dedup_suppresses_repeat` — second call within cooldown → None

**TestEmergentAlerts** (4 tests):
- `test_trust_anomaly_significant` — severity="significant" → advisory
- `test_cooperation_cluster` — → info, department="science"
- `test_routing_shift_significant` — → advisory
- `test_unknown_pattern_skipped` — unknown type → empty list

**TestBehavioralAlerts** (3 tests):
- `test_high_failure_rate` — → advisory
- `test_removal_recommended` — → alert
- `test_no_monitor_returns_empty` — None monitor → empty list

**TestAlertDelivery** (3 tests — use mock runtime with mock ward_room):
- `test_advisory_posts_to_all_hands` — advisory → ship channel thread + info notification
- `test_alert_posts_with_action_required` — alert → ship channel thread + action_required notification
- `test_info_posts_to_department_channel` — info → department channel thread, no notification

**TestAlertLog** (2 tests):
- `test_ring_buffer_capped` — after 250 alerts, only 200 remain
- `test_get_recent_alerts_limit` — limit=5 returns last 5

**TestIntegration** (2 tests — optional, heavier):
- `test_full_pipeline_vitals_to_ward_room` — vitals data → service → alerts → mock deliver
- `test_service_disabled_no_alerts` — bridge_alerts=None → no crashes

### Test Patterns

Use `unittest.mock.MagicMock` for:
- `runtime.ward_room` (mock `list_channels()` returning ship + department channels, mock `create_thread()`)
- `runtime.notify()` for notification verification
- `runtime.event_log.log()` for audit trail assertions
- `behavioral_monitor` (mock `get_alerts()`, `get_status()`, `should_recommend_removal()`)

For EmergentDetector patterns, create simple mock objects with `pattern_type`, `severity`, `description` attributes.

For dedup timing tests, use `monkeypatch` on `time.monotonic` to control the clock.

---

## Verification

Run in this order:

```bash
# 1. Targeted — new tests
uv run pytest tests/test_bridge_alerts.py -x -v

# 2. Ward Room routing regression
uv run pytest tests/test_ward_room_agents.py -x -v

# 3. Pool groups regression
uv run pytest tests/test_pool_groups.py -x -v

# 4. Full suite
uv run pytest tests/ --tb=short -q
```

## What This Does NOT Change

- Ward Room data model / schema (no changes to `ward_room.py`)
- Agent cognitive lifecycle (no LLM calls for the alert itself)
- Existing notification system (adds TO it, doesn't change it)
- Five-layer Ward Room safety (crew responses to alerts go through existing AD-407d mechanics)
- HXI / frontend (alerts appear as normal Ward Room threads authored by "Ship's Computer")
- WebSocket event system (same events, same broadcasts)
