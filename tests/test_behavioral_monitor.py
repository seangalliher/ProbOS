"""Tests for BehavioralMonitor — execution recording, trust tracking, removal recommendations."""

from __future__ import annotations

from probos.cognitive.behavioral_monitor import BehavioralMonitor


class TestRecordExecution:
    """Tests for record_execution()."""

    def test_record_successful_execution(self):
        """Recording a successful execution updates tracking data."""
        bm = BehavioralMonitor()
        bm.track_agent_type("test_agent")
        bm.record_execution("test_agent", duration_ms=100.0, success=True)
        status = bm.get_status()
        assert "test_agent" in status
        assert status["test_agent"]["successes"] == 1

    def test_record_failed_execution_alert(self):
        """Recording enough failures triggers a high_failure_rate alert."""
        bm = BehavioralMonitor()
        bm.track_agent_type("flaky_agent")
        for _ in range(6):
            bm.record_execution("flaky_agent", duration_ms=50.0, success=False)
        alerts = bm.get_alerts()
        assert any(a.alert_type == "high_failure_rate" for a in alerts)

    def test_untracked_agent_type_ignored(self):
        """Agent types not registered via track_agent_type() are silently ignored."""
        bm = BehavioralMonitor()
        bm.record_execution("unknown_type", duration_ms=100.0, success=True)
        status = bm.get_status()
        assert "unknown_type" not in status

    def test_slow_execution_alert(self):
        """Consistently slow executions trigger a slow_execution alert."""
        bm = BehavioralMonitor()
        bm.track_agent_type("slow_agent")
        for _ in range(4):
            bm.record_execution("slow_agent", duration_ms=30000.0, success=True)
        alerts = bm.get_alerts()
        assert any(a.alert_type == "slow_execution" for a in alerts)


class TestTrustTrajectory:
    """Tests for check_trust_trajectory()."""

    def test_stable_trust_no_decline_alert(self):
        """Stable trust scores produce no declining_trust alert."""
        bm = BehavioralMonitor()
        bm.track_agent_type("stable_agent")
        for _ in range(5):
            bm.check_trust_trajectory("stable_agent", 0.9)
        alerts = bm.get_alerts(agent_type="stable_agent")
        assert not any(a.alert_type == "declining_trust" for a in alerts)

    def test_declining_trust_triggers_alert(self):
        """Consistently declining trust triggers a declining_trust alert."""
        bm = BehavioralMonitor()
        bm.track_agent_type("declining_agent")
        for score in [0.9, 0.8, 0.7, 0.6]:
            bm.check_trust_trajectory("declining_agent", score)
        alerts = bm.get_alerts()
        assert any(a.alert_type == "declining_trust" for a in alerts)

    def test_untracked_agent_safe(self):
        """check_trust_trajectory for untracked agent does not crash."""
        bm = BehavioralMonitor()
        bm.check_trust_trajectory("nonexistent", 0.5)
        assert bm.get_alerts() == []


class TestGetAlerts:
    """Tests for get_alerts() with agent_type filter."""

    def test_filter_by_agent_type(self):
        """get_alerts(agent_type=...) filters to matching agent only."""
        bm = BehavioralMonitor()
        bm.track_agent_type("agent_a")
        bm.track_agent_type("agent_b")
        for _ in range(6):
            bm.record_execution("agent_a", duration_ms=50.0, success=False)
        for _ in range(6):
            bm.record_execution("agent_b", duration_ms=50.0, success=False)
        a_alerts = bm.get_alerts(agent_type="agent_a")
        b_alerts = bm.get_alerts(agent_type="agent_b")
        assert len(a_alerts) > 0
        assert len(b_alerts) > 0
        assert all(a.agent_type == "agent_a" for a in a_alerts)
        assert all(a.agent_type == "agent_b" for a in b_alerts)

    def test_all_alerts_returned_without_filter(self):
        """get_alerts() without filter returns all alerts."""
        bm = BehavioralMonitor()
        bm.track_agent_type("x")
        for _ in range(6):
            bm.record_execution("x", duration_ms=50.0, success=False)
        all_alerts = bm.get_alerts()
        assert len(all_alerts) > 0


class TestGetStatus:
    """Tests for get_status()."""

    def test_status_dict_structure(self):
        """get_status() returns dict with expected keys per agent."""
        bm = BehavioralMonitor()
        bm.track_agent_type("my_agent")
        bm.record_execution("my_agent", duration_ms=200.0, success=True)
        status = bm.get_status()
        assert "my_agent" in status
        info = status["my_agent"]
        assert "total_executions" in info
        assert "successes" in info
        assert "failures" in info
        assert "avg_execution_ms" in info
        assert "alert_count" in info
        assert info["total_executions"] == 1
        assert info["avg_execution_ms"] == 200.0


class TestShouldRecommendRemoval:
    """Tests for should_recommend_removal()."""

    def test_no_recommendation_for_healthy_agent(self):
        """Healthy agent is not recommended for removal."""
        bm = BehavioralMonitor()
        bm.track_agent_type("good_agent")
        bm.record_execution("good_agent", duration_ms=100.0, success=True)
        assert bm.should_recommend_removal("good_agent") is False

    def test_recommendation_for_high_failure_rate(self):
        """Agent with >50% failure rate across 10+ executions is recommended for removal."""
        bm = BehavioralMonitor()
        bm.track_agent_type("bad_agent")
        for _ in range(12):
            bm.record_execution("bad_agent", duration_ms=50.0, success=False)
        assert bm.should_recommend_removal("bad_agent") is True

    def test_recommendation_for_trust_decline(self):
        """Agent with sustained trust decline is recommended for removal."""
        bm = BehavioralMonitor()
        bm.track_agent_type("untrusted_agent")
        for score in [0.9, 0.7, 0.5]:
            bm.check_trust_trajectory("untrusted_agent", score)
        assert bm.should_recommend_removal("untrusted_agent") is True

    def test_unknown_agent_not_recommended(self):
        """Unknown agent returns False (not crash)."""
        bm = BehavioralMonitor()
        assert bm.should_recommend_removal("nonexistent") is False
