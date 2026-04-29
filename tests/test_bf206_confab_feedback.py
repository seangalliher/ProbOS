"""BF-206: Enforce Evaluate suppress + confabulation feedback loop.

Tests cover:
- Chain dependency fix (Reflect depends on Evaluate)
- Suppress enforcement in _execute_sub_task_chain()
- CONFABULATION_SUPPRESSED event emission
- Counselor graduated feedback (warning → trust penalty)
- Integration scenarios
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.events import EventType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt.emit_event = MagicMock()
    return rt


@pytest.fixture
def mock_trust_network():
    tn = MagicMock()
    tn.get_trust_score = MagicMock(return_value=0.4)
    tn.record_outcome = MagicMock(return_value=0.35)
    return tn


def _make_eval_result(recommendation: str = "approve", rejection_reason: str = "") -> SubTaskResult:
    result: dict[str, Any] = {"recommendation": recommendation}
    if rejection_reason:
        result["rejection_reason"] = rejection_reason
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-reply",
        result=result,
        success=True,
        tier_used="tier1",
    )


def _make_compose_result(output: str = "Test output") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-reply",
        result={"output": output},
        success=True,
        tier_used="tier1",
    )


def _make_reflect_result(output: str = "Reflected output") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.REFLECT,
        name="reflect-reply",
        result={"output": output},
        success=True,
        tier_used="tier1",
    )


# ===========================================================================
# Part 1: Chain Dependency Fix
# ===========================================================================

class TestReflectDependency:
    """Verify Reflect depends_on includes Evaluate step name."""

    def test_ward_room_reflect_depends_on_evaluate(self):
        """ward_room_notification chain: Reflect depends on evaluate-reply."""
        import inspect
        from probos.cognitive import cognitive_agent as ca_mod
        src = inspect.getsource(ca_mod.CognitiveAgent._build_chain_for_intent)
        assert 'depends_on=("compose-reply", "evaluate-reply")' in src, \
            "Reflect in ward_room chain must depend on evaluate-reply"

    def test_proactive_reflect_depends_on_evaluate(self):
        """proactive_think chain: Reflect depends on evaluate-observation."""
        import inspect
        from probos.cognitive import cognitive_agent as ca_mod
        src = inspect.getsource(ca_mod.CognitiveAgent._build_chain_for_intent)
        assert 'depends_on=("compose-observation", "evaluate-observation")' in src, \
            "Reflect in proactive chain must depend on evaluate-observation"


# ===========================================================================
# Part 2: Suppress Enforcement in _execute_sub_task_chain()
# ===========================================================================

class TestSuppressEnforcement:
    """_execute_sub_task_chain() suppresses output when Evaluate says suppress."""

    @pytest.fixture
    def agent(self, mock_runtime):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        a = CognitiveAgent.__new__(CognitiveAgent)
        a.id = "agent-1"
        a.agent_type = "test"
        a.callsign = "TestAgent"
        a._runtime = mock_runtime
        a._sub_task_executor = MagicMock()
        return a

    @pytest.mark.asyncio
    async def test_suppress_returns_no_response(self, agent):
        """When Evaluate recommends suppress, chain returns [NO_RESPONSE]."""
        results = [
            _make_compose_result("Hello world"),
            _make_eval_result("suppress", "fabricated_hex_ids"),
        ]
        chain = MagicMock()
        chain.source = "intent_trigger:ward_room_notification"
        chain.steps = [MagicMock(), MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        observation = {"intent": "ward_room", "_trust_score": 0.3}
        decision = await agent._execute_sub_task_chain(chain, observation)

        assert decision is not None
        assert decision["llm_output"] == "[NO_RESPONSE]"
        assert decision["_suppressed"] is True
        assert decision["_suppression_reason"] == "fabricated_hex_ids"

    @pytest.mark.asyncio
    async def test_approve_returns_compose_output(self, agent):
        """When Evaluate approves, chain returns normal compose output."""
        results = [
            _make_compose_result("Good post"),
            _make_eval_result("approve"),
        ]
        chain = MagicMock()
        chain.source = "intent_trigger:ward_room_notification"
        chain.steps = [MagicMock(), MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        observation = {"intent": "ward_room"}
        decision = await agent._execute_sub_task_chain(chain, observation)

        assert decision is not None
        assert decision["llm_output"] == "Good post"
        assert "_suppressed" not in decision

    @pytest.mark.asyncio
    async def test_no_evaluate_returns_compose_output(self, agent):
        """When Evaluate is skipped, chain returns compose output."""
        results = [_make_compose_result("Normal output")]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        observation = {"intent": "ward_room"}
        decision = await agent._execute_sub_task_chain(chain, observation)

        assert decision is not None
        assert decision["llm_output"] == "Normal output"
        assert "_suppressed" not in decision

    @pytest.mark.asyncio
    async def test_suppress_sets_metadata(self, agent):
        """Suppression sets _suppressed and _suppression_reason in decision."""
        results = [
            _make_compose_result(),
            _make_eval_result("suppress", "raw_json_detected"),
        ]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock(), MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        decision = await agent._execute_sub_task_chain(chain, {})

        assert decision["_suppressed"] is True
        assert decision["_suppression_reason"] == "raw_json_detected"
        assert decision["sub_task_chain"] is True

    @pytest.mark.asyncio
    async def test_suppress_default_reason(self, agent):
        """When rejection_reason is missing, defaults to quality_gate."""
        results = [
            _make_compose_result(),
            _make_eval_result("suppress"),  # No rejection_reason
        ]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        decision = await agent._execute_sub_task_chain(chain, {})

        assert decision["_suppression_reason"] == "quality_gate"

    @pytest.mark.asyncio
    async def test_reflect_overrides_compose_when_approved(self, agent):
        """When both Reflect and Compose succeed and Evaluate approves, Reflect wins."""
        results = [
            _make_compose_result("Compose text"),
            _make_eval_result("approve"),
            _make_reflect_result("Reflected text"),
        ]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock(), MagicMock(), MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        decision = await agent._execute_sub_task_chain(chain, {})

        assert decision["llm_output"] == "Reflected text"


# ===========================================================================
# Part 3: Event Emission
# ===========================================================================

class TestEventEmission:
    """CONFABULATION_SUPPRESSED event emitted on suppress."""

    @pytest.fixture
    def agent(self, mock_runtime):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        a = CognitiveAgent.__new__(CognitiveAgent)
        a.id = "agent-1"
        a.agent_type = "test"
        a.callsign = "TestAgent"
        a._runtime = mock_runtime
        a._sub_task_executor = MagicMock()
        return a

    @pytest.mark.asyncio
    async def test_event_emitted_on_suppress(self, agent):
        """CONFABULATION_SUPPRESSED event fires when suppress enforced."""
        results = [
            _make_compose_result(),
            _make_eval_result("suppress", "fabricated_hex_ids"),
        ]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        observation = {"intent": "ward_room", "_trust_score": 0.3, "_chain_trust_band": "low"}
        await agent._execute_sub_task_chain(chain, observation)

        agent._runtime.emit_event.assert_called_once()
        call_args = agent._runtime.emit_event.call_args
        assert call_args[0][0] == EventType.CONFABULATION_SUPPRESSED
        data = call_args[0][1]
        assert data["agent_id"] == "agent-1"
        assert data["callsign"] == "TestAgent"
        assert data["rejection_reason"] == "fabricated_hex_ids"
        assert data["trust_score"] == 0.3
        assert data["chain_trust_band"] == "low"

    @pytest.mark.asyncio
    async def test_event_data_includes_intent(self, agent):
        """Event data includes the intent from observation."""
        results = [_make_compose_result(), _make_eval_result("suppress", "test")]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        await agent._execute_sub_task_chain(chain, {"intent": "ward_room_notification"})

        data = agent._runtime.emit_event.call_args[0][1]
        assert data["intent"] == "ward_room_notification"

    @pytest.mark.asyncio
    async def test_no_event_on_approve(self, agent):
        """No event emitted when Evaluate approves."""
        results = [_make_compose_result(), _make_eval_result("approve")]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        await agent._execute_sub_task_chain(chain, {})

        agent._runtime.emit_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_event_when_evaluate_skipped(self, agent):
        """No event emitted when Evaluate wasn't in the chain."""
        results = [_make_compose_result()]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        await agent._execute_sub_task_chain(chain, {})

        agent._runtime.emit_event.assert_not_called()


# ===========================================================================
# Part 4: Counselor Feedback
# ===========================================================================

class TestCounselorFeedback:
    """Counselor graduated response to confabulation suppression."""

    @pytest.fixture
    def counselor(self, mock_trust_network):
        from probos.cognitive.counselor import CounselorAgent
        c = CounselorAgent.__new__(CounselorAgent)
        c.id = "counselor-1"
        c.agent_type = "counselor"
        c.callsign = "Echo"
        c._trust_network = mock_trust_network
        c._cognitive_profiles = {}
        c._profile_store = None
        c._send_therapeutic_dm = AsyncMock(return_value=True)
        c._dm_cooldowns = {}
        return c

    @pytest.mark.asyncio
    async def test_routes_confabulation_event(self, counselor):
        """Counselor routes CONFABULATION_SUPPRESSED to handler."""
        counselor._on_confabulation_suppressed = AsyncMock()
        data = {"agent_id": "a1", "callsign": "Wesley"}
        await counselor._on_event_async({
            "type": EventType.CONFABULATION_SUPPRESSED.value,
            "data": data,
        })
        counselor._on_confabulation_suppressed.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_first_offense_warning_dm(self, counselor):
        """First confabulation in window sends warning DM, no trust penalty."""
        data = {
            "agent_id": "agent-x",
            "callsign": "Wesley",
            "rejection_reason": "fabricated_hex_ids",
            "trust_score": 0.3,
        }
        await counselor._on_confabulation_suppressed(data)

        counselor._send_therapeutic_dm.assert_awaited_once()
        msg = counselor._send_therapeutic_dm.call_args[0][2]
        assert "held back" in msg
        assert "completely normal" in msg
        # No trust penalty on first offense
        counselor._trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_second_offense_trust_penalty(self, counselor):
        """Second confabulation in window triggers trust penalty + escalated DM."""
        data = {
            "agent_id": "agent-x",
            "callsign": "Wesley",
            "rejection_reason": "fabricated_hex_ids",
            "trust_score": 0.3,
        }
        # First call
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.reset_mock()
        counselor._trust_network.record_outcome.reset_mock()

        # Second call — same window
        await counselor._on_confabulation_suppressed(data)

        # Trust penalty applied
        counselor._trust_network.record_outcome.assert_called_once_with(
            agent_id="agent-x",
            success=False,
            weight=0.5,
            intent_type="confabulation_suppressed",
            source="confabulation",
        )
        # Escalated DM
        msg = counselor._send_therapeutic_dm.call_args[0][2]
        assert "2nd" in msg
        assert "trust rating has been adjusted" in msg

    @pytest.mark.asyncio
    async def test_trust_penalty_weight(self, counselor):
        """Trust penalty uses weight=0.5 and source='confabulation'."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}
        # Two offenses to trigger penalty
        await counselor._on_confabulation_suppressed(data)
        await counselor._on_confabulation_suppressed(data)

        call = counselor._trust_network.record_outcome.call_args
        assert call.kwargs["weight"] == 0.5
        assert call.kwargs["source"] == "confabulation"

    @pytest.mark.asyncio
    async def test_outside_window_resets_count(self, counselor):
        """Offenses outside 1h window don't count toward repeat threshold."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}

        # First offense
        await counselor._on_confabulation_suppressed(data)

        # Simulate time passing beyond window
        counselor._confab_history["agent-x"] = [time.time() - 3700]

        # Second offense — but old one expired
        counselor._trust_network.record_outcome.reset_mock()
        await counselor._on_confabulation_suppressed(data)

        # Should NOT trigger trust penalty (only 1 in window after prune)
        # Wait — the second call adds a new entry, prunes old one, so count = 1
        # Actually let's re-check: old timestamp pruned, new one added = count 1
        # But then the append happens first: [old, new], prune removes old → [new] → count=1
        # Actually the code appends THEN prunes. So: [old, new] → prune → [new] → count = 1
        # count >= 2 is False → no penalty
        counselor._trust_network.record_outcome.assert_not_called()

    @pytest.mark.asyncio
    async def test_confabulation_count_incremented(self, counselor):
        """confabulation_count incremented in cognitive profile."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}
        await counselor._on_confabulation_suppressed(data)

        profile = counselor._cognitive_profiles["agent-x"]
        assert profile.confabulation_count == 1

        await counselor._on_confabulation_suppressed(data)
        assert profile.confabulation_count == 2

    @pytest.mark.asyncio
    async def test_ignores_self_events(self, counselor):
        """Counselor ignores events about itself."""
        data = {"agent_id": "counselor-1", "callsign": "Echo"}
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_third_offense_th_suffix(self, counselor):
        """Third+ offenses use 'th' suffix in DM message."""
        data = {"agent_id": "agent-x", "callsign": "W", "trust_score": 0.3}
        await counselor._on_confabulation_suppressed(data)
        await counselor._on_confabulation_suppressed(data)
        counselor._send_therapeutic_dm.reset_mock()
        await counselor._on_confabulation_suppressed(data)

        msg = counselor._send_therapeutic_dm.call_args[0][2]
        assert "3rd" in msg


# ===========================================================================
# Part 5: Integration Scenarios
# ===========================================================================

class TestIntegration:
    """End-to-end scenarios combining suppress + event + Counselor."""

    @pytest.fixture
    def agent(self, mock_runtime):
        from probos.cognitive.cognitive_agent import CognitiveAgent
        a = CognitiveAgent.__new__(CognitiveAgent)
        a.id = "low-trust-agent"
        a.agent_type = "test"
        a.callsign = "Wesley"
        a._runtime = mock_runtime
        a._sub_task_executor = MagicMock()
        return a

    @pytest.mark.asyncio
    async def test_low_trust_confab_suppress_flow(self, agent):
        """Low-trust agent: Evaluate catches → suppress → [NO_RESPONSE]."""
        results = [
            _make_compose_result("Thread abc123 showed metrics 0.847"),
            _make_eval_result("suppress", "fabricated_hex_ids"),
        ]
        chain = MagicMock()
        chain.source = "intent_trigger:ward_room_notification"
        chain.steps = [MagicMock(), MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        observation = {
            "intent": "ward_room_notification",
            "_trust_score": 0.3,
            "_chain_trust_band": "low",
        }
        decision = await agent._execute_sub_task_chain(chain, observation)

        assert decision["llm_output"] == "[NO_RESPONSE]"
        assert decision["_suppressed"] is True
        agent._runtime.emit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_mid_trust_confab_suppress_with_reflect(self, agent):
        """Mid-trust: Evaluate catches, Reflect present but suppress takes priority."""
        results = [
            _make_compose_result("Some output"),
            _make_eval_result("suppress", "fabricated_hex_ids"),
            _make_reflect_result("Reflected version"),
        ]
        chain = MagicMock()
        chain.source = "intent_trigger:ward_room_notification"
        chain.steps = [MagicMock(), MagicMock(), MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        observation = {"_trust_score": 0.5, "_chain_trust_band": "mid"}
        decision = await agent._execute_sub_task_chain(chain, observation)

        # Suppress takes priority over Reflect output
        assert decision["llm_output"] == "[NO_RESPONSE]"
        assert decision["_suppressed"] is True

    @pytest.mark.asyncio
    async def test_suppress_no_runtime_no_crash(self, agent):
        """Suppress works even if runtime is None (graceful degradation)."""
        agent._runtime = None
        results = [
            _make_compose_result(),
            _make_eval_result("suppress", "test"),
        ]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        decision = await agent._execute_sub_task_chain(chain, {})
        assert decision["_suppressed"] is True
        assert decision["llm_output"] == "[NO_RESPONSE]"

    @pytest.mark.asyncio
    async def test_failed_evaluate_not_treated_as_suppress(self, agent):
        """Failed Evaluate result (success=False) is not treated as suppress."""
        failed_eval = SubTaskResult(
            sub_task_type=SubTaskType.EVALUATE,
            name="evaluate-reply",
            result={"recommendation": "suppress"},
            success=False,  # Failed — should be ignored
            tier_used="tier1",
        )
        results = [_make_compose_result("Good output"), failed_eval]
        chain = MagicMock()
        chain.source = "test"
        chain.steps = [MagicMock(), MagicMock()]

        agent._sub_task_executor.can_execute.return_value = True
        agent._sub_task_executor.execute = AsyncMock(return_value=results)

        decision = await agent._execute_sub_task_chain(chain, {})
        assert decision["llm_output"] == "Good output"
        assert "_suppressed" not in decision


# ===========================================================================
# Part 6: Event Type Exists
# ===========================================================================

class TestEventType:
    """CONFABULATION_SUPPRESSED event type exists in EventType enum."""

    def test_event_type_exists(self):
        assert hasattr(EventType, "CONFABULATION_SUPPRESSED")
        assert EventType.CONFABULATION_SUPPRESSED.value == "confabulation_suppressed"
