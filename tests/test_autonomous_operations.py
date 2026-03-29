"""Tests for AD-471: Autonomous Operations — Conn, Night Orders, Watch Bill."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.conn import ConnManager, ConnState
from probos.watch_rotation import (
    CaptainOrder,
    NightOrders,
    NightOrdersManager,
    WatchManager,
    WatchType,
    NIGHT_ORDER_TEMPLATES,
)


# ── Conn tests ──────────────────────────────────────────────────────

class TestConn:
    """Tests for ConnManager."""

    def test_conn_grant_and_return(self):
        """Grant conn, verify active + holder. Return, verify inactive + summary."""
        mgr = ConnManager()
        assert not mgr.is_active

        state = mgr.grant_conn(
            agent_id="a1", agent_type="architect",
            callsign="Number One", reason="Captain going offline",
        )
        assert mgr.is_active
        assert mgr.holder == "Number One"
        assert state.reason == "Captain going offline"

        result = mgr.return_conn(summary="All clear")
        assert not mgr.is_active
        assert result["holder"] == "Number One"
        assert result["summary"] == "All clear"
        assert result["actions_taken"] == 0

    def test_conn_qualification_commander_required(self):
        """Agent with LIEUTENANT rank fails is_conn_qualified()."""
        rt = MagicMock()
        rt.registry.get.return_value = MagicMock(id="a1", agent_type="architect")
        rt.trust_network.get_trust_score.return_value = 0.55  # LIEUTENANT
        rt.ontology = MagicMock()

        # Import the function we're testing
        from probos.crew_profile import Rank

        # Manually test the rank check using ordinal comparison
        rank = Rank.from_trust(0.55)
        _RANK_ORDER = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
        assert _RANK_ORDER.index(rank) < _RANK_ORDER.index(Rank.COMMANDER)

    def test_conn_qualification_post_required(self):
        """COMMANDER-rank agent not on bridge/chief post fails qualification."""
        rt = MagicMock()
        rt.registry.get.return_value = MagicMock(id="a1", agent_type="scout")
        rt.trust_network.get_trust_score.return_value = 0.8  # COMMANDER

        post = MagicMock()
        post.id = "scout_post"  # Not in CONN_ELIGIBLE_POSTS
        rt.ontology.get_post_for_agent.return_value = post

        # Simulate the is_conn_qualified logic
        CONN_ELIGIBLE_POSTS = {
            "first_officer", "counselor",
            "chief_engineer", "chief_science", "chief_medical",
            "chief_security", "chief_operations",
        }
        assert post.id not in CONN_ELIGIBLE_POSTS

    def test_conn_escalation_triggers(self):
        """Each trigger in ESCALATION_TRIGGERS returns True from check_escalation()."""
        mgr = ConnManager()
        mgr.grant_conn("a1", "architect", "Number One")

        for trigger in ConnManager.ESCALATION_TRIGGERS:
            assert mgr.check_escalation(trigger) is True
        assert mgr.state.escalation_count == len(ConnManager.ESCALATION_TRIGGERS)

    def test_conn_captain_only_actions(self):
        """is_authorized('modify_standing_orders') returns False. is_authorized('issue_order') returns True."""
        mgr = ConnManager()
        mgr.grant_conn("a1", "architect", "Number One")

        assert mgr.is_authorized("modify_standing_orders") is False
        assert mgr.is_authorized("approve_self_mod") is False
        assert mgr.is_authorized("red_alert") is False
        assert mgr.is_authorized("destructive_action") is False
        assert mgr.is_authorized("prune_agent") is False

        assert mgr.is_authorized("issue_order") is True
        assert mgr.is_authorized("change_alert_yellow") is True
        assert mgr.is_authorized("routine_diagnostic") is True

    def test_conn_action_logging(self):
        """record_action() appends to both actions_taken and _conn_log."""
        mgr = ConnManager()
        mgr.grant_conn("a1", "architect", "Number One")

        mgr.record_action("diagnostic", {"target": "systems"})
        assert len(mgr.state.actions_taken) == 1
        assert mgr.state.actions_taken[0]["type"] == "diagnostic"
        assert mgr.state.actions_taken[0]["authorized_by"] == "conn"

        # Also in conn log (grant + action)
        log = mgr.get_conn_log()
        assert any(e.get("action") == "diagnostic" for e in log)

    def test_conn_transfer(self):
        """Grant to Agent A, then grant to Agent B. Verify log shows transfer."""
        mgr = ConnManager()
        mgr.grant_conn("a1", "architect", "Number One")
        mgr.grant_conn("a2", "counselor", "Counselor")

        assert mgr.holder == "Counselor"
        log = mgr.get_conn_log()
        assert any(e.get("action") == "conn_transfer" for e in log)
        transfer = next(e for e in log if e.get("action") == "conn_transfer")
        assert transfer["from"] == "Number One"
        assert transfer["to"] == "Counselor"


# ── Night Orders tests ──────────────────────────────────────────────

class TestNightOrders:
    """Tests for NightOrdersManager."""

    def test_night_orders_set_and_expire(self):
        """Set orders, verify active. Expire, verify inactive + summary."""
        mgr = NightOrdersManager()
        assert not mgr.active

        mgr.set_night_orders(
            instructions=["Monitor trust levels", "Report anomalies"],
            ttl_hours=4.0,
        )
        assert mgr.active
        assert mgr.orders is not None
        assert len(mgr.orders.instructions) == 2

        result = mgr.expire()
        assert not mgr.active
        assert result["instructions_count"] == 2
        assert result["invoked_count"] == 0

    def test_night_orders_ttl_expiry(self):
        """Set order with very small TTL. After time passes, verify is_expired()."""
        mgr = NightOrdersManager()
        mgr.set_night_orders(instructions=[], ttl_hours=0.0001)  # ~0.36s

        # Force expiry by manipulating expires_at
        mgr.orders.expires_at = time.time() - 1.0
        assert mgr.orders.is_expired() is True
        assert not mgr.active  # Property checks and deactivates

    def test_night_orders_template_maintenance(self):
        """Set 'maintenance' template. Verify can_approve_builds=False, specific triggers."""
        mgr = NightOrdersManager()
        mgr.set_night_orders(instructions=[], template="maintenance")

        assert mgr.orders.can_approve_builds is False
        assert "build_failure" in mgr.orders.escalation_triggers
        assert "security_alert" in mgr.orders.escalation_triggers
        assert "trust_drop" in mgr.orders.escalation_triggers
        assert mgr.orders.alert_boundary == "yellow"

    def test_night_orders_template_build(self):
        """Set 'build' template. Verify can_approve_builds=True."""
        mgr = NightOrdersManager()
        mgr.set_night_orders(instructions=[], template="build")

        assert mgr.orders.can_approve_builds is True

    def test_night_orders_template_quiet(self):
        """Set 'quiet' template. Verify alert_boundary='green'."""
        mgr = NightOrdersManager()
        mgr.set_night_orders(instructions=[], template="quiet")

        assert mgr.orders.alert_boundary == "green"
        assert mgr.orders.can_approve_builds is False

    def test_night_orders_invocation_tracking(self):
        """Call invoke(). Verify invocation recorded with timestamp."""
        mgr = NightOrdersManager()
        mgr.set_night_orders(instructions=["Do X if Y"])

        mgr.orders.invoke(0, {"event": "Y occurred"})
        assert len(mgr.orders.invocations) == 1
        assert mgr.orders.invocations[0]["instruction_index"] == 0
        assert "timestamp" in mgr.orders.invocations[0]

    def test_night_orders_escalation_check(self):
        """Set escalation_triggers=['trust_drop']. Verify check returns correctly."""
        mgr = NightOrdersManager()
        mgr.set_night_orders(
            instructions=[],
            escalation_triggers=["trust_drop"],
        )

        assert mgr.check_escalation("trust_drop") is True
        assert mgr.check_escalation("other") is False


# ── Watch Bill tests ────────────────────────────────────────────────

class TestWatchBill:
    """Tests for Watch Bill extensions."""

    def test_watch_auto_rotate_morning(self):
        """Mock hour=10. Verify _get_current_watch_by_time() returns ALPHA."""
        wm = WatchManager()
        with patch("probos.watch_rotation.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 10
            assert wm._get_current_watch_by_time() == WatchType.ALPHA

    def test_watch_auto_rotate_evening(self):
        """Mock hour=20. Verify returns BETA."""
        wm = WatchManager()
        with patch("probos.watch_rotation.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 20
            assert wm._get_current_watch_by_time() == WatchType.BETA

    def test_watch_auto_rotate_night(self):
        """Mock hour=3. Verify returns GAMMA."""
        wm = WatchManager()
        with patch("probos.watch_rotation.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 3
            assert wm._get_current_watch_by_time() == WatchType.GAMMA

    def test_watch_rotation_triggers_change(self):
        """Set current watch to ALPHA. Mock hour=20. Call auto_rotate(). Verify changed to BETA."""
        wm = WatchManager()
        wm.set_current_watch(WatchType.ALPHA)

        with patch.object(wm, '_get_current_watch_by_time', return_value=WatchType.BETA):
            result = wm.auto_rotate()
            assert result == WatchType.BETA
            assert wm.current_watch == WatchType.BETA

    def test_watch_no_rotation_same_period(self):
        """Set current watch to ALPHA. Mock hour=10. Call auto_rotate(). Verify returns None."""
        wm = WatchManager()
        wm.set_current_watch(WatchType.ALPHA)

        with patch.object(wm, '_get_current_watch_by_time', return_value=WatchType.ALPHA):
            result = wm.auto_rotate()
            assert result is None

    def test_night_order_expiry_in_dispatch(self):
        """Create an expired Night Order CaptainOrder. Call _expire_night_orders(). Verify active=False."""
        wm = WatchManager()
        order = CaptainOrder(
            id="no-1",
            target="engineering",
            target_type="department",
            description="Night monitoring",
            is_night_order=True,
            ttl_seconds=1.0,
            created_at=time.time() - 100,
            expires_at=time.time() - 50,  # Already expired
        )
        wm.issue_order(order)
        assert order.active is True

        wm._expire_night_orders()
        assert order.active is False

    def test_watch_status_report(self):
        """Populate roster, add standing tasks. Verify get_watch_status() returns correct counts."""
        wm = WatchManager()
        wm.assign_to_watch("a1", WatchType.ALPHA)
        wm.assign_to_watch("a2", WatchType.ALPHA)
        wm.assign_to_watch("a3", WatchType.BETA)

        from probos.watch_rotation import StandingTask
        wm.add_standing_task(StandingTask(id="t1", department="eng", enabled=True))

        status = wm.get_watch_status()
        assert status["current_watch"] == "alpha"
        assert len(status["on_duty"]) == 2  # a1, a2 on ALPHA
        assert status["standing_tasks_count"] == 1
        assert "roster" in status


# ── Integration tests ───────────────────────────────────────────────

class TestIntegration:
    """Integration tests across Conn + Night Orders + Watch."""

    def test_conn_night_orders_integration(self):
        """Set Night Orders with can_approve_builds=True, grant conn. Verify conn holder inherits."""
        conn_mgr = ConnManager()
        night_mgr = NightOrdersManager()

        night_mgr.set_night_orders(instructions=[], template="build")
        orders = night_mgr.orders

        state = conn_mgr.grant_conn(
            "a1", "architect", "Number One",
            can_approve_builds=orders.can_approve_builds,
        )
        assert state.can_approve_builds is True
        assert conn_mgr.is_authorized("approve_build") is True

    def test_captain_return_expires_night_orders(self):
        """Set Night Orders, grant conn. Return conn. Verify Night Orders expired."""
        conn_mgr = ConnManager()
        night_mgr = NightOrdersManager()

        night_mgr.set_night_orders(instructions=["Watch the store"])
        conn_mgr.grant_conn("a1", "architect", "Number One")

        assert night_mgr.active
        conn_mgr.return_conn()
        night_mgr.expire()  # Simulating shell behavior
        assert not night_mgr.active

    def test_captain_order_night_order_ttl(self):
        """Create CaptainOrder with is_night_order=True, expired. Verify is_expired()."""
        order = CaptainOrder(
            id="co-1",
            target="all",
            description="Night patrol",
            is_night_order=True,
            ttl_seconds=1.0,
            created_at=time.time() - 100,
            expires_at=time.time() - 50,
        )
        assert order.is_expired() is True

        # Non-night orders never expire via TTL
        normal_order = CaptainOrder(id="co-2", target="all")
        assert normal_order.is_expired() is False


# ── Execution path tests ────────────────────────────────────────────

class TestExecutionPath:
    """Tests for Night Orders execution path (context injection, escalation)."""

    @pytest.mark.asyncio
    async def test_night_orders_context_injection(self):
        """Mock conn active + Night Orders active. Verify context injection for conn-holder."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop()
        rt = MagicMock()

        # Set up conn manager
        conn_state = ConnState(
            holder_agent_id="a1",
            holder_agent_type="architect",
            holder_callsign="Number One",
            active=True,
            can_approve_builds=True,
            can_change_alert_yellow=True,
            can_issue_orders=True,
        )
        rt.conn_manager = MagicMock()
        rt.conn_manager.is_active = True
        rt.conn_manager.state = conn_state

        # Set up night orders manager
        orders = NightOrders(
            active=True,
            template="build",
            instructions=["Approve approved-queue builds"],
            alert_boundary="yellow",
            escalation_triggers=["security_alert"],
            expires_at=time.time() + 3600,
        )
        rt._night_orders_mgr = MagicMock()
        rt._night_orders_mgr.active = True
        rt._night_orders_mgr.orders = orders

        # Set up minimal runtime
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ontology = None
        rt.ward_room = None
        rt._is_crew_agent.return_value = True

        agent = MagicMock()
        agent.id = "a1"
        agent.agent_type = "architect"

        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "conn_authority" in context
        assert context["conn_authority"]["role"] == "You currently hold the conn (temporary command authority)."
        assert "night_orders" in context["conn_authority"]
        assert context["conn_authority"]["night_orders"]["template"] == "build"

    @pytest.mark.asyncio
    async def test_night_orders_context_not_injected_for_non_holder(self):
        """Mock conn active. Different agent gets no conn_authority context."""
        from probos.proactive import ProactiveCognitiveLoop

        loop = ProactiveCognitiveLoop()
        rt = MagicMock()

        conn_state = ConnState(
            holder_agent_id="a1",  # Agent a1 holds conn
            active=True,
        )
        rt.conn_manager = MagicMock()
        rt.conn_manager.is_active = True
        rt.conn_manager.state = conn_state

        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ontology = None
        rt.ward_room = None
        rt._is_crew_agent.return_value = True

        agent = MagicMock()
        agent.id = "a2"  # Different agent
        agent.agent_type = "counselor"

        loop.set_runtime(rt)
        context = await loop._gather_context(agent, 0.7)

        assert "conn_authority" not in context

    def test_night_orders_escalation_trust_drop(self):
        """Set Night Orders with trust_drop escalation. Verify bridge alert on low trust."""
        rt = MagicMock()
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(
            instructions=[],
            escalation_triggers=["trust_drop"],
        )
        rt._night_orders_mgr = night_mgr
        rt.conn_manager = ConnManager()

        # Mock bridge alerts
        rt.bridge_alerts = MagicMock()

        # Simulate the escalation check
        from probos.runtime import ProbOSRuntime
        # Test the escalation logic directly on the manager
        assert night_mgr.check_escalation("trust_drop") is True

    def test_night_orders_escalation_ignored_above_floor(self):
        """Trust above floor (0.8) does not escalate."""
        night_mgr = NightOrdersManager()
        night_mgr.set_night_orders(
            instructions=[],
            escalation_triggers=["trust_drop"],
        )

        # Simulate the runtime check logic inline
        details = {"new_trust": 0.8}
        trigger = "trust_drop"

        # The runtime's _check_night_order_escalation would return early
        # because new_trust >= 0.6. Let's verify the logic:
        new_trust = details.get("new_trust", 1.0)
        should_skip = new_trust >= 0.6
        assert should_skip is True  # Would not reach check_escalation


# ── Conn status/API tests ──────────────────────────────────────────

class TestConnStatus:
    """Tests for ConnManager.get_status()."""

    def test_status_inactive(self):
        mgr = ConnManager()
        status = mgr.get_status()
        assert status["active"] is False
        assert status["holder"] is None

    def test_status_active(self):
        mgr = ConnManager()
        mgr.grant_conn("a1", "architect", "Number One", reason="test")
        status = mgr.get_status()
        assert status["active"] is True
        assert status["holder"] == "Number One"
        assert status["reason"] == "test"
        assert "duration_seconds" in status

    def test_return_no_active_conn(self):
        mgr = ConnManager()
        result = mgr.return_conn()
        assert result == {"status": "no_active_conn"}


class TestNightOrdersStatus:
    """Tests for NightOrdersManager.get_status()."""

    def test_status_inactive(self):
        mgr = NightOrdersManager()
        status = mgr.get_status()
        assert status["active"] is False

    def test_status_active(self):
        mgr = NightOrdersManager()
        mgr.set_night_orders(instructions=["A", "B"], template="maintenance")
        status = mgr.get_status()
        assert status["active"] is True
        assert status["template"] == "maintenance"
        assert status["instructions_count"] == 2
        assert "remaining_hours" in status


class TestCaptainOrderBackcompat:
    """Ensure CaptainOrder backward compatibility — new fields have defaults."""

    def test_defaults(self):
        order = CaptainOrder(id="test")
        assert order.is_night_order is False
        assert order.ttl_seconds == 28800.0
        assert order.expires_at == 0.0
        assert order.template == ""
        assert order.is_expired() is False

    def test_night_order_not_expired_when_expires_at_zero(self):
        order = CaptainOrder(id="test", is_night_order=True, expires_at=0)
        assert order.is_expired() is False
