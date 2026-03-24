"""Tests for Bridge Alert Service (AD-410)."""

import time
import pytest
from unittest.mock import MagicMock, AsyncMock

from probos.bridge_alerts import (
    AlertSeverity, BridgeAlert, BridgeAlertService,
)


# ---------------------------------------------------------------------------
# AlertSeverity
# ---------------------------------------------------------------------------

class TestAlertSeverity:
    def test_severity_values(self):
        assert AlertSeverity.INFO == "info"
        assert AlertSeverity.ADVISORY == "advisory"
        assert AlertSeverity.ALERT == "alert"

    def test_severity_string_conversion(self):
        assert "alert" in str(AlertSeverity.ALERT).lower()
        assert "advisory" in str(AlertSeverity.ADVISORY).lower()


# ---------------------------------------------------------------------------
# BridgeAlert dataclass
# ---------------------------------------------------------------------------

class TestBridgeAlert:
    def test_alert_creation(self):
        a = BridgeAlert(
            id="a1", severity=AlertSeverity.ALERT,
            source="vitals_monitor", alert_type="pool_health_critical",
            title="Pool Critical", detail="Pool is down",
            department="engineering", dedup_key="pool_health_critical:http",
            related_pool="http",
        )
        assert a.id == "a1"
        assert a.severity == AlertSeverity.ALERT
        assert a.source == "vitals_monitor"
        assert a.related_pool == "http"

    def test_alert_defaults(self):
        a = BridgeAlert(
            id="a2", severity=AlertSeverity.INFO,
            source="test", alert_type="test_type",
            title="Test", detail="Detail",
            department=None, dedup_key="test:key",
        )
        assert a.timestamp > 0  # auto-populated
        assert a.related_agent_id is None
        assert a.related_pool is None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_same_key_suppressed(self):
        svc = BridgeAlertService(cooldown_seconds=300)
        alerts1 = svc.check_vitals({"pool_health": {"http": 0.2}})
        assert len(alerts1) == 1
        # Same key again within cooldown — suppressed
        alerts2 = svc.check_vitals({"pool_health": {"http": 0.2}})
        assert len(alerts2) == 0

    def test_different_key_passes(self):
        svc = BridgeAlertService(cooldown_seconds=300)
        alerts1 = svc.check_vitals({"pool_health": {"http": 0.2}})
        alerts2 = svc.check_vitals({"pool_health": {"shell": 0.2}})
        assert len(alerts1) == 1
        assert len(alerts2) == 1

    def test_expired_key_re_emits(self, monkeypatch):
        svc = BridgeAlertService(cooldown_seconds=10)
        t = [100.0]
        monkeypatch.setattr(time, "monotonic", lambda: t[0])
        alerts1 = svc.check_vitals({"pool_health": {"http": 0.2}})
        assert len(alerts1) == 1
        # Advance past cooldown
        t[0] = 111.0
        alerts2 = svc.check_vitals({"pool_health": {"http": 0.2}})
        assert len(alerts2) == 1


# ---------------------------------------------------------------------------
# Vitals alerts
# ---------------------------------------------------------------------------

class TestVitalsAlerts:
    def test_pool_health_warning(self):
        svc = BridgeAlertService()
        alerts = svc.check_vitals({"pool_health": {"http": 0.4}})
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY
        assert alerts[0].alert_type == "pool_health_warning"

    def test_pool_health_critical(self):
        svc = BridgeAlertService()
        alerts = svc.check_vitals({"pool_health": {"http": 0.2}})
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ALERT
        assert alerts[0].alert_type == "pool_health_critical"

    def test_pool_health_ok(self):
        svc = BridgeAlertService()
        alerts = svc.check_vitals({"pool_health": {"http": 0.8}})
        assert len(alerts) == 0

    def test_system_health_warning(self):
        svc = BridgeAlertService()
        alerts = svc.check_vitals({"system_health": 0.5})
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY
        assert alerts[0].alert_type == "system_health_warning"

    def test_system_health_critical(self):
        svc = BridgeAlertService()
        alerts = svc.check_vitals({"system_health": 0.2})
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ALERT
        assert alerts[0].alert_type == "system_health_critical"

    def test_trust_outliers(self):
        svc = BridgeAlertService()
        alerts_high = svc.check_vitals({"trust_outlier_count": 5})
        assert len(alerts_high) == 1
        assert alerts_high[0].severity == AlertSeverity.ADVISORY

        svc2 = BridgeAlertService()
        alerts_low = svc2.check_vitals({"trust_outlier_count": 2})
        assert len(alerts_low) == 0


# ---------------------------------------------------------------------------
# Trust change alerts
# ---------------------------------------------------------------------------

class TestTrustChangeAlerts:
    def test_below_threshold_no_alert(self):
        svc = BridgeAlertService()
        result = svc.check_trust_change("agent-1", 0.80, 0.75)
        assert result is None

    def test_advisory_threshold(self):
        svc = BridgeAlertService()
        result = svc.check_trust_change("agent-1", 0.80, 0.64)
        assert result is not None
        assert result.severity == AlertSeverity.ADVISORY
        assert result.alert_type == "trust_drop_advisory"

    def test_alert_threshold(self):
        svc = BridgeAlertService()
        result = svc.check_trust_change("agent-1", 0.80, 0.54)
        assert result is not None
        assert result.severity == AlertSeverity.ALERT
        assert result.alert_type == "trust_drop_alert"

    def test_dedup_suppresses_repeat(self):
        svc = BridgeAlertService()
        result1 = svc.check_trust_change("agent-1", 0.80, 0.64)
        assert result1 is not None
        result2 = svc.check_trust_change("agent-1", 0.64, 0.48)
        assert result2 is None  # Dedup suppresses


# ---------------------------------------------------------------------------
# Emergent pattern alerts
# ---------------------------------------------------------------------------

class TestEmergentAlerts:
    def test_trust_anomaly_significant(self):
        svc = BridgeAlertService()
        pattern = MagicMock()
        pattern.pattern_type = "trust_anomaly"
        pattern.severity = "significant"
        pattern.description = "Trust anomaly detected"
        alerts = svc.check_emergent_patterns([pattern])
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY

    def test_cooperation_cluster(self):
        svc = BridgeAlertService()
        pattern = MagicMock()
        pattern.pattern_type = "cooperation_cluster"
        pattern.severity = "info"
        pattern.description = "Cooperation cluster found"
        alerts = svc.check_emergent_patterns([pattern])
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.INFO
        assert alerts[0].department == "science"

    def test_routing_shift_significant(self):
        svc = BridgeAlertService()
        pattern = MagicMock()
        pattern.pattern_type = "routing_shift"
        pattern.severity = "significant"
        pattern.description = "Routing shift detected"
        alerts = svc.check_emergent_patterns([pattern])
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY

    def test_unknown_pattern_skipped(self):
        svc = BridgeAlertService()
        pattern = MagicMock()
        pattern.pattern_type = "unknown_pattern_type"
        pattern.severity = "info"
        pattern.description = "Something unknown"
        alerts = svc.check_emergent_patterns([pattern])
        assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Behavioral alerts
# ---------------------------------------------------------------------------

class TestBehavioralAlerts:
    def test_high_failure_rate(self):
        svc = BridgeAlertService()
        monitor = MagicMock()
        alert_obj = MagicMock()
        alert_obj.alert_type = "high_failure_rate"
        alert_obj.agent_type = "http_fetch"
        alert_obj.detail = "Failure rate above 50%"
        monitor.get_alerts.return_value = [alert_obj]
        monitor.get_status.return_value = {}
        alerts = svc.check_behavioral(monitor)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY

    def test_removal_recommended(self):
        svc = BridgeAlertService()
        monitor = MagicMock()
        monitor.get_alerts.return_value = []
        monitor.get_status.return_value = {"bad_agent": {}}
        monitor.should_recommend_removal.return_value = True
        alerts = svc.check_behavioral(monitor)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ALERT
        assert alerts[0].alert_type == "behavioral_removal"

    def test_no_monitor_returns_empty(self):
        svc = BridgeAlertService()
        alerts = svc.check_behavioral(None)
        assert alerts == []


# ---------------------------------------------------------------------------
# Alert delivery (mock runtime)
# ---------------------------------------------------------------------------

class TestAlertDelivery:
    async def test_advisory_posts_to_all_hands(self):
        """Advisory alert posts to ship channel + info notification."""
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock()
        runtime.ward_room = MagicMock()
        ship_channel = MagicMock()
        ship_channel.channel_type = "ship"
        ship_channel.id = "ship-ch"
        dept_channel = MagicMock()
        dept_channel.channel_type = "department"
        dept_channel.department = "engineering"
        dept_channel.id = "eng-ch"
        runtime.ward_room.list_channels = AsyncMock(return_value=[ship_channel, dept_channel])
        runtime.ward_room.create_thread = AsyncMock()
        runtime.notify = MagicMock()
        runtime.event_log = MagicMock()
        runtime.event_log.log = AsyncMock()

        alert = BridgeAlert(
            id="a1", severity=AlertSeverity.ADVISORY,
            source="vitals_monitor", alert_type="system_health_warning",
            title="System Health Warning", detail="Health is low",
            department=None, dedup_key="test",
        )

        import types
        runtime._deliver_bridge_alert = types.MethodType(
            ProbOSRuntime._deliver_bridge_alert, runtime,
        )
        await runtime._deliver_bridge_alert(alert)

        # Posted to ship channel (advisory -> All Hands)
        runtime.ward_room.create_thread.assert_called_once()
        call_kwargs = runtime.ward_room.create_thread.call_args[1]
        assert call_kwargs["channel_id"] == "ship-ch"
        assert call_kwargs["author_callsign"] == "Ship's Computer"
        assert "[ADVISORY]" in call_kwargs["title"]

        # Info notification to Captain
        runtime.notify.assert_called_once()
        notif_kwargs = runtime.notify.call_args[1]
        assert notif_kwargs["notification_type"] == "info"

    async def test_alert_posts_with_action_required(self):
        """Alert severity posts to ship channel + action_required notification."""
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock()
        runtime.ward_room = MagicMock()
        ship_channel = MagicMock()
        ship_channel.channel_type = "ship"
        ship_channel.id = "ship-ch"
        runtime.ward_room.list_channels = AsyncMock(return_value=[ship_channel])
        runtime.ward_room.create_thread = AsyncMock()
        runtime.notify = MagicMock()
        runtime.event_log = MagicMock()
        runtime.event_log.log = AsyncMock()

        alert = BridgeAlert(
            id="a2", severity=AlertSeverity.ALERT,
            source="vitals_monitor", alert_type="pool_health_critical",
            title="Pool Critical", detail="Down",
            department="engineering", dedup_key="test",
            related_agent_id="agent-x",
        )

        import types
        runtime._deliver_bridge_alert = types.MethodType(
            ProbOSRuntime._deliver_bridge_alert, runtime,
        )
        await runtime._deliver_bridge_alert(alert)

        runtime.ward_room.create_thread.assert_called_once()
        call_kwargs = runtime.ward_room.create_thread.call_args[1]
        assert "[ALERT]" in call_kwargs["title"]

        runtime.notify.assert_called_once()
        notif_kwargs = runtime.notify.call_args[1]
        assert notif_kwargs["notification_type"] == "action_required"

    async def test_info_posts_to_department_channel(self):
        """Info severity posts to department channel, no Captain notification."""
        from probos.runtime import ProbOSRuntime

        runtime = MagicMock()
        runtime.ward_room = MagicMock()
        ship_channel = MagicMock()
        ship_channel.channel_type = "ship"
        ship_channel.id = "ship-ch"
        eng_channel = MagicMock()
        eng_channel.channel_type = "department"
        eng_channel.department = "science"
        eng_channel.id = "sci-ch"
        runtime.ward_room.list_channels = AsyncMock(return_value=[ship_channel, eng_channel])
        runtime.ward_room.create_thread = AsyncMock()
        runtime.notify = MagicMock()
        runtime.event_log = MagicMock()
        runtime.event_log.log = AsyncMock()

        alert = BridgeAlert(
            id="a3", severity=AlertSeverity.INFO,
            source="emergent_detector", alert_type="emergent_cooperation_cluster",
            title="Cooperation Cluster", detail="Agents cooperating",
            department="science", dedup_key="test",
        )

        import types
        runtime._deliver_bridge_alert = types.MethodType(
            ProbOSRuntime._deliver_bridge_alert, runtime,
        )
        await runtime._deliver_bridge_alert(alert)

        runtime.ward_room.create_thread.assert_called_once()
        call_kwargs = runtime.ward_room.create_thread.call_args[1]
        assert call_kwargs["channel_id"] == "sci-ch"
        assert "[INFO]" in call_kwargs["title"]

        # No Captain notification for info severity
        runtime.notify.assert_not_called()


# ---------------------------------------------------------------------------
# Alert log
# ---------------------------------------------------------------------------

class TestAlertLog:
    def test_ring_buffer_capped(self):
        svc = BridgeAlertService(cooldown_seconds=0)  # No dedup for this test
        for i in range(250):
            svc.check_vitals({"pool_health": {f"pool-{i}": 0.2}})
        assert len(svc._alert_log) == 200

    def test_get_recent_alerts_limit(self):
        svc = BridgeAlertService(cooldown_seconds=0)
        for i in range(20):
            svc.check_vitals({"pool_health": {f"pool-{i}": 0.2}})
        recent = svc.get_recent_alerts(5)
        assert len(recent) == 5
        # Should be last 5
        assert recent[-1].related_pool == "pool-19"


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_full_pipeline_vitals_to_alerts(self):
        svc = BridgeAlertService()
        vitals = {
            "pool_health": {"http": 0.2, "shell": 0.4, "filesystem": 0.9},
            "system_health": 0.5,
            "trust_outlier_count": 5,
        }
        alerts = svc.check_vitals(vitals)
        # http critical + shell warning + system warning + trust outliers
        assert len(alerts) == 4
        severities = {a.alert_type: a.severity for a in alerts}
        assert severities["pool_health_critical"] == AlertSeverity.ALERT
        assert severities["pool_health_warning"] == AlertSeverity.ADVISORY
        assert severities["system_health_warning"] == AlertSeverity.ADVISORY
        assert severities["trust_outliers"] == AlertSeverity.ADVISORY

    def test_service_disabled_no_crashes(self):
        """bridge_alerts=None should not crash delivery code."""
        # Just verify the service can be instantiated and used safely
        svc = BridgeAlertService()
        assert svc.get_recent_alerts() == []
        assert svc.check_vitals({}) == []
        assert svc.check_trust_change("x", 0.5, 0.5) is None
        assert svc.check_emergent_patterns([]) == []
        assert svc.check_behavioral(None) == []
