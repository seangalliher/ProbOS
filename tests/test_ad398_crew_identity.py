"""Tests for AD-398: Crew Identity Alignment — Three-Tier Agent Architecture."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.crew_profile import CallsignRegistry
from probos.types import IntentMessage, IntentResult


# ---------------------------------------------------------------------------
# 1. direct_message passthrough in act() overrides
# ---------------------------------------------------------------------------

class TestDirectMessagePassthrough:
    """AD-398: act() early-return guard for direct_message intents."""

    @pytest.mark.asyncio
    async def test_scout_direct_message(self):
        from probos.cognitive.scout import ScoutAgent
        agent = ScoutAgent(runtime=None)
        decision = {"intent": "direct_message", "llm_output": "Hello, I'm Wesley."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Hello, I'm Wesley."

    @pytest.mark.asyncio
    async def test_builder_direct_message(self):
        from unittest.mock import patch
        with patch("probos.cognitive.builder._should_use_visiting_builder", return_value=False):
            from probos.cognitive.builder import BuilderAgent
            agent = BuilderAgent(agent_id="builder-dm-0", llm_client=MagicMock(), runtime=MagicMock())
            decision = {"intent": "direct_message", "llm_output": "Aye, Captain."}
            result = await agent.act(decision)
            assert result["success"] is True
            assert result["result"] == "Aye, Captain."

    @pytest.mark.asyncio
    async def test_architect_direct_message(self):
        from probos.cognitive.architect import ArchitectAgent
        agent = ArchitectAgent(agent_id="arch-dm-0", llm_client=MagicMock())
        decision = {"intent": "direct_message", "llm_output": "Understood, sir."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Understood, sir."

    @pytest.mark.asyncio
    async def test_surgeon_direct_message(self):
        from probos.agents.medical.surgeon import SurgeonAgent
        agent = SurgeonAgent(llm_client=MagicMock(), runtime=MagicMock())
        decision = {"intent": "direct_message", "llm_output": "Patient stable."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Patient stable."

    @pytest.mark.asyncio
    async def test_counselor_direct_message(self):
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=MagicMock())
        decision = {"intent": "direct_message", "llm_output": "How are you feeling?"}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "How are you feeling?"


# ---------------------------------------------------------------------------
# 1b. BF-024: Passthrough for ward_room_notification and proactive_think
# ---------------------------------------------------------------------------

class TestConversationalPassthrough:
    """BF-024: act() passthrough for ward_room_notification and proactive_think."""

    @pytest.mark.asyncio
    async def test_scout_ward_room_notification(self):
        from probos.cognitive.scout import ScoutAgent
        agent = ScoutAgent(runtime=None)
        decision = {"intent": "ward_room_notification", "llm_output": "Acknowledged."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Acknowledged."

    @pytest.mark.asyncio
    async def test_scout_proactive_think(self):
        from probos.cognitive.scout import ScoutAgent
        agent = ScoutAgent(runtime=None)
        decision = {"intent": "proactive_think", "llm_output": "Sector scan complete."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Sector scan complete."

    @pytest.mark.asyncio
    async def test_builder_ward_room_notification(self):
        from unittest.mock import patch
        with patch("probos.cognitive.builder._should_use_visiting_builder", return_value=False):
            from probos.cognitive.builder import BuilderAgent
            agent = BuilderAgent(agent_id="builder-wr-0", llm_client=MagicMock(), runtime=MagicMock())
            decision = {"intent": "ward_room_notification", "llm_output": "Noted, Captain."}
            result = await agent.act(decision)
            assert result["success"] is True
            assert result["result"] == "Noted, Captain."

    @pytest.mark.asyncio
    async def test_builder_proactive_think(self):
        from unittest.mock import patch
        with patch("probos.cognitive.builder._should_use_visiting_builder", return_value=False):
            from probos.cognitive.builder import BuilderAgent
            agent = BuilderAgent(agent_id="builder-pt-0", llm_client=MagicMock(), runtime=MagicMock())
            decision = {"intent": "proactive_think", "llm_output": "Build pipeline nominal."}
            result = await agent.act(decision)
            assert result["success"] is True
            assert result["result"] == "Build pipeline nominal."

    @pytest.mark.asyncio
    async def test_architect_ward_room_notification(self):
        from probos.cognitive.architect import ArchitectAgent
        agent = ArchitectAgent(agent_id="arch-wr-0", llm_client=MagicMock())
        decision = {"intent": "ward_room_notification", "llm_output": "Design reviewed."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Design reviewed."

    @pytest.mark.asyncio
    async def test_architect_proactive_think(self):
        from probos.cognitive.architect import ArchitectAgent
        agent = ArchitectAgent(agent_id="arch-pt-0", llm_client=MagicMock())
        decision = {"intent": "proactive_think", "llm_output": "Architecture stable."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Architecture stable."

    @pytest.mark.asyncio
    async def test_surgeon_ward_room_notification(self):
        from probos.agents.medical.surgeon import SurgeonAgent
        agent = SurgeonAgent(llm_client=MagicMock(), runtime=MagicMock())
        decision = {"intent": "ward_room_notification", "llm_output": "Ready for surgery."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Ready for surgery."

    @pytest.mark.asyncio
    async def test_surgeon_proactive_think(self):
        from probos.agents.medical.surgeon import SurgeonAgent
        agent = SurgeonAgent(llm_client=MagicMock(), runtime=MagicMock())
        decision = {"intent": "proactive_think", "llm_output": "All patients stable."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "All patients stable."

    @pytest.mark.asyncio
    async def test_counselor_ward_room_notification(self):
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=MagicMock())
        decision = {"intent": "ward_room_notification", "llm_output": "Crew morale noted."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "Crew morale noted."

    @pytest.mark.asyncio
    async def test_counselor_proactive_think(self):
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=MagicMock())
        decision = {"intent": "proactive_think", "llm_output": "No concerns."}
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"] == "No concerns."


# ---------------------------------------------------------------------------
# 2. Crew profile removal — infrastructure agents no longer have callsigns
# ---------------------------------------------------------------------------

class TestInfrastructureNoCallsigns:
    """AD-398: Infrastructure agents reclassified — no callsigns."""

    def _registry(self) -> CallsignRegistry:
        reg = CallsignRegistry()
        reg.load_from_profiles()
        return reg

    def test_no_data_callsign(self):
        """IntrospectAgent (Data) no longer has a callsign."""
        assert self._registry().resolve("data") is None

    def test_no_chapel_callsign(self):
        """VitalsMonitor (Chapel) no longer has a callsign."""
        assert self._registry().resolve("chapel") is None

    def test_no_dax_callsign(self):
        """EmergentDetector (Dax) no longer has a callsign."""
        assert self._registry().resolve("dax") is None

    def test_introspect_type_no_callsign(self):
        """get_callsign('introspect') returns empty."""
        assert self._registry().get_callsign("introspect") == ""

    def test_vitals_monitor_type_no_callsign(self):
        """get_callsign('vitals_monitor') returns empty."""
        assert self._registry().get_callsign("vitals_monitor") == ""

    def test_red_team_type_no_callsign(self):
        """get_callsign('red_team') returns empty."""
        assert self._registry().get_callsign("red_team") == ""

    def test_system_qa_type_no_callsign(self):
        """get_callsign('system_qa') returns empty."""
        assert self._registry().get_callsign("system_qa") == ""


# ---------------------------------------------------------------------------
# 3. New crew profiles resolve correctly
# ---------------------------------------------------------------------------

class TestNewCrewProfiles:
    """AD-398: New cognitive crew agents have correct callsign mappings."""

    def _registry(self) -> CallsignRegistry:
        reg = CallsignRegistry()
        reg.load_from_profiles()
        return reg

    def test_worf_resolves_to_security_officer(self):
        result = self._registry().resolve("worf")
        assert result is not None
        assert result["agent_type"] == "security_officer"
        assert result["callsign"] == "Worf"

    def test_obrien_resolves_to_operations_officer(self):
        result = self._registry().resolve("o'brien")
        assert result is not None
        assert result["agent_type"] == "operations_officer"
        assert result["callsign"] == "O'Brien"

    def test_laforge_resolves_to_engineering_officer(self):
        result = self._registry().resolve("laforge")
        assert result is not None
        assert result["agent_type"] == "engineering_officer"
        assert result["callsign"] == "LaForge"


# ---------------------------------------------------------------------------
# 4. New agents instantiate with correct attributes
# ---------------------------------------------------------------------------

class TestNewAgentInstantiation:
    """AD-398: New crew agents construct correctly."""

    def test_security_agent_attributes(self):
        from probos.cognitive.security_officer import SecurityAgent
        agent = SecurityAgent(llm_client=MagicMock(), runtime=MagicMock())
        assert agent.agent_type == "security_officer"
        assert agent.tier == "domain"
        assert agent.instructions  # non-empty
        assert len(agent.intent_descriptors) == 2
        assert agent._handled_intents == {"security_assess", "security_review"}

    def test_operations_agent_attributes(self):
        from probos.cognitive.operations_officer import OperationsAgent
        agent = OperationsAgent(llm_client=MagicMock(), runtime=MagicMock())
        assert agent.agent_type == "operations_officer"
        assert agent.tier == "domain"
        assert agent.instructions  # non-empty
        assert len(agent.intent_descriptors) == 2
        assert agent._handled_intents == {"ops_status", "ops_coordinate"}

    def test_engineering_agent_attributes(self):
        from probos.cognitive.engineering_officer import EngineeringAgent
        agent = EngineeringAgent(llm_client=MagicMock(), runtime=MagicMock())
        assert agent.agent_type == "engineering_officer"
        assert agent.tier == "domain"
        assert agent.instructions  # non-empty
        assert len(agent.intent_descriptors) == 2
        assert agent._handled_intents == {"engineering_analyze", "engineering_optimize"}


# ---------------------------------------------------------------------------
# 5. New agents handle direct_message via handle_intent()
# ---------------------------------------------------------------------------

class TestNewAgentsDirectMessage:
    """AD-398: New crew agents respond to direct_message via full lifecycle."""

    @pytest.mark.asyncio
    async def test_security_agent_direct_message(self):
        from probos.cognitive.security_officer import SecurityAgent
        llm = MockLLMClient()
        agent = SecurityAgent(llm_client=llm, runtime=MagicMock())
        intent = IntentMessage(
            intent="direct_message",
            params={"message": "What threats do you see?"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result  # non-empty LLM response

    @pytest.mark.asyncio
    async def test_operations_agent_direct_message(self):
        from probos.cognitive.operations_officer import OperationsAgent
        llm = MockLLMClient()
        agent = OperationsAgent(llm_client=llm, runtime=MagicMock())
        intent = IntentMessage(
            intent="direct_message",
            params={"message": "Status report?"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result

    @pytest.mark.asyncio
    async def test_engineering_agent_direct_message(self):
        from probos.cognitive.engineering_officer import EngineeringAgent
        llm = MockLLMClient()
        agent = EngineeringAgent(llm_client=llm, runtime=MagicMock())
        intent = IntentMessage(
            intent="direct_message",
            params={"message": "How are the engines?"},
            target_agent_id=agent.id,
        )
        result = await agent.handle_intent(intent)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result


# ---------------------------------------------------------------------------
# 7. Intent propagation — decision["intent"] set after decide()
# ---------------------------------------------------------------------------

class TestIntentPropagation:
    """AD-398: handle_intent() injects intent name into decision dict."""

    @pytest.mark.asyncio
    async def test_intent_field_in_decision(self):
        """Verify decision dict has 'intent' key after handle_intent()."""
        from probos.cognitive.security_officer import SecurityAgent
        llm = MockLLMClient()
        agent = SecurityAgent(llm_client=llm, runtime=MagicMock())

        captured_decisions = []
        original_act = agent.act

        async def capture_act(decision):
            captured_decisions.append(decision)
            return await original_act(decision)

        agent.act = capture_act

        intent = IntentMessage(intent="security_assess", params={"target": "runtime"})
        await agent.handle_intent(intent)

        assert len(captured_decisions) == 1
        assert captured_decisions[0].get("intent") == "security_assess"

    @pytest.mark.asyncio
    async def test_direct_message_intent_propagated(self):
        """Verify direct_message intent is propagated to act()."""
        from probos.cognitive.security_officer import SecurityAgent
        llm = MockLLMClient()
        agent = SecurityAgent(llm_client=llm, runtime=MagicMock())

        captured_decisions = []
        original_act = agent.act

        async def capture_act(decision):
            captured_decisions.append(decision)
            return await original_act(decision)

        agent.act = capture_act

        intent = IntentMessage(
            intent="direct_message",
            params={"message": "hi"},
            target_agent_id=agent.id,
        )
        await agent.handle_intent(intent)

        assert len(captured_decisions) == 1
        assert captured_decisions[0].get("intent") == "direct_message"
