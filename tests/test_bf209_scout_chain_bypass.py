"""BF-209: Scout Duty Report Chain Bypass — Tests.

Verifies that ScoutAgent's duty-triggered proactive_think bypasses the
communication chain (routes through decide() → act() instead), while
ward_room_notification and non-duty proactive_think still use the chain.
"""

from unittest.mock import MagicMock

from probos.cognitive.scout import ScoutAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scout(*, has_executor: bool = True) -> ScoutAgent:
    agent = ScoutAgent(agent_id="scout-test", instructions="Test scout.")
    if has_executor:
        agent._sub_task_executor = MagicMock()
        agent._sub_task_executor.enabled = True
    else:
        agent._sub_task_executor = None
    return agent


# ---------------------------------------------------------------------------
# Test 1: Duty-triggered proactive_think bypasses chain
# ---------------------------------------------------------------------------

class TestDutyBypassesChain:

    def test_scout_report_duty_bypasses_chain(self):
        agent = _make_scout()
        observation = {
            "intent": "proactive_think",
            "params": {"duty": {"duty_id": "scout_report"}},
        }
        assert agent._should_activate_chain(observation) is False


# ---------------------------------------------------------------------------
# Test 2: Ward room notification still uses chain
# ---------------------------------------------------------------------------

class TestWardRoomUsesChain:

    def test_ward_room_notification_uses_chain(self):
        agent = _make_scout()
        observation = {
            "intent": "ward_room_notification",
            "params": {"channel_name": "general"},
        }
        assert agent._should_activate_chain(observation) is True


# ---------------------------------------------------------------------------
# Test 3: Non-duty proactive_think still uses chain
# ---------------------------------------------------------------------------

class TestNonDutyUsesChain:

    def test_non_duty_proactive_think_uses_chain(self):
        agent = _make_scout()
        observation = {
            "intent": "proactive_think",
            "params": {},
        }
        assert agent._should_activate_chain(observation) is True


# ---------------------------------------------------------------------------
# Test 4: Chain disabled entirely returns False
# ---------------------------------------------------------------------------

class TestChainDisabledReturnsFalse:

    def test_no_executor_returns_false(self):
        agent = _make_scout(has_executor=False)
        observation = {
            "intent": "ward_room_notification",
            "params": {"channel_name": "general"},
        }
        assert agent._should_activate_chain(observation) is False
