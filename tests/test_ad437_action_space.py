"""AD-437: Ward Room Action Space — Structured Agent Actions."""

import re
import time
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock

import pytest

from probos.crew_profile import Rank
from probos.earned_agency import can_perform_action
from probos.runtime import ProbOSRuntime


# ---------- Earned Agency action gating ----------

class TestCanPerformAction:
    """Test action permission gating by rank."""

    def test_ensign_cannot_endorse(self):
        assert can_perform_action(Rank.ENSIGN, "endorse") is False

    def test_lieutenant_can_endorse(self):
        assert can_perform_action(Rank.LIEUTENANT, "endorse") is True

    def test_lieutenant_can_reply(self):
        assert can_perform_action(Rank.LIEUTENANT, "reply") is True

    def test_commander_can_endorse(self):
        assert can_perform_action(Rank.COMMANDER, "endorse") is True

    def test_commander_can_reply(self):
        assert can_perform_action(Rank.COMMANDER, "reply") is True

    def test_commander_cannot_lock(self):
        assert can_perform_action(Rank.COMMANDER, "lock") is False

    def test_senior_can_lock(self):
        assert can_perform_action(Rank.SENIOR, "lock") is True

    def test_senior_can_pin(self):
        assert can_perform_action(Rank.SENIOR, "pin") is True

    def test_unknown_action_denied(self):
        assert can_perform_action(Rank.SENIOR, "delete") is False


# ---------- Endorsement extraction in proactive path ----------

class TestProactiveEndorsementExtraction:
    """Endorsements in proactive think should be extracted and executed, not posted raw."""

    @pytest.mark.asyncio
    async def test_endorsements_extracted_from_proactive_response(self):
        """[ENDORSE] tags should be stripped from text and executed."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.ward_room = MagicMock()
        runtime.trust_network = MagicMock()
        runtime.trust_network.get_score.return_value = 0.6  # Lieutenant
        runtime.ward_room_router = MagicMock()
        runtime.ward_room_router.extract_endorsements.return_value = (
            "I noticed a pattern in the trust data.",
            [{"post_id": "abc123", "direction": "up"}],
        )
        runtime.ward_room_router.process_endorsements = AsyncMock()
        runtime.is_cold_start = False

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "security_officer"

        cleaned, actions = await loop._extract_and_execute_actions(
            agent, "I noticed a pattern. [ENDORSE abc123 UP]"
        )

        assert "[ENDORSE" not in cleaned
        runtime.ward_room_router.process_endorsements.assert_called_once()
        assert len(actions) == 1
        assert actions[0]["type"] == "endorse"

    @pytest.mark.asyncio
    async def test_ensign_endorsements_not_processed(self):
        """Ensigns cannot endorse — tags should remain in text (they won't post anyway)."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.ward_room = MagicMock()
        runtime.trust_network = MagicMock()
        runtime.trust_network.get_score.return_value = 0.3  # Ensign
        runtime.is_cold_start = False

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "security_officer"

        cleaned, actions = await loop._extract_and_execute_actions(
            agent, "Something. [ENDORSE abc123 UP]"
        )

        assert len(actions) == 0


# ---------- Reply extraction ----------

class TestProactiveReplyExtraction:
    """Commander+ agents can reply to existing threads."""

    @pytest.mark.asyncio
    async def test_reply_extracted_and_posted(self):
        """[REPLY thread_id]...[/REPLY] should create a post in the thread."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.ward_room = MagicMock()
        runtime.ward_room.get_thread = AsyncMock(return_value={"thread": {"locked": False}})
        runtime.ward_room.create_post = AsyncMock(return_value=MagicMock(id="new-post"))
        runtime.trust_network = MagicMock()
        runtime.trust_network.get_score.return_value = 0.75  # Commander
        runtime.ward_room_router = MagicMock()
        runtime.ward_room_router.extract_endorsements.return_value = ("text", [])
        runtime.ward_room_router.process_endorsements = AsyncMock()
        runtime.is_cold_start = False
        runtime.callsign_registry = MagicMock()
        runtime.callsign_registry.get_callsign.return_value = "Worf"

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)
        loop._resolve_thread_id = AsyncMock(return_value="thread-abc")

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "security_officer"

        text = (
            "Observation text.\n"
            "[REPLY thread-abc]\n"
            "I agree and want to add that the pattern also affects routing.\n"
            "[/REPLY]"
        )

        cleaned, actions = await loop._extract_and_execute_replies(agent, text)

        assert "[REPLY" not in cleaned
        runtime.ward_room.create_post.assert_called_once()
        call_kwargs = runtime.ward_room.create_post.call_args
        assert call_kwargs[1]["thread_id"] == "thread-abc"
        assert len(actions) == 1
        assert actions[0]["type"] == "reply"

    @pytest.mark.asyncio
    async def test_reply_to_locked_thread_skipped(self):
        """Replies to locked threads should be silently skipped."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.ward_room = MagicMock()
        runtime.ward_room.get_thread = AsyncMock(return_value={"thread": {"locked": True}})
        runtime.ward_room.create_post = AsyncMock()
        runtime.trust_network = MagicMock()
        runtime.trust_network.get_score.return_value = 0.75
        runtime.is_cold_start = False

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)
        loop._resolve_thread_id = AsyncMock(return_value="locked-thread")

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "security_officer"

        text = "[REPLY locked-thread]\nMy reply.\n[/REPLY]"
        cleaned, actions = await loop._extract_and_execute_replies(agent, text)

        runtime.ward_room.create_post.assert_not_called()
        assert len(actions) == 0

    @pytest.mark.asyncio
    async def test_ensign_cannot_reply(self):
        """Ensigns should not have reply actions processed (BF-061: gate is Lieutenant+)."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.ward_room = MagicMock()
        runtime.trust_network = MagicMock()
        runtime.trust_network.get_score.return_value = 0.3  # Ensign
        runtime.ward_room_router = MagicMock()
        runtime.ward_room_router.extract_endorsements.return_value = ("text", [])
        runtime.ward_room_router.process_endorsements = AsyncMock()
        runtime.is_cold_start = False
        runtime._records_store = MagicMock()
        runtime._records_store.write_notebook = AsyncMock()
        runtime.ontology = None
        runtime.callsign_registry = MagicMock()
        runtime.callsign_registry.get_callsign.return_value = "TestAgent"
        runtime.config = MagicMock()
        runtime.config.communications = MagicMock(dm_min_rank="ensign")

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)

        agent = MagicMock()
        agent.id = "test-agent"
        agent.agent_type = "security_officer"

        text = "Observation.\n[REPLY thread-abc]\nReply text.\n[/REPLY]"
        cleaned, actions = await loop._extract_and_execute_actions(agent, text)

        # Reply should NOT be extracted (Ensign can't reply — BF-061 lowered gate to Lieutenant+)
        assert not any(a["type"] == "reply" for a in actions)


# ---------- Skill reinforcement ----------

class TestSkillReinforcement:
    """Successful actions should reinforce Communication PCC."""

    @pytest.mark.asyncio
    async def test_endorsement_records_communication_exercise(self):
        """Endorsing a post should exercise the Communication PCC."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.ward_room = MagicMock()
        runtime.trust_network = MagicMock()
        runtime.trust_network.get_score.return_value = 0.6  # Lieutenant
        runtime.ward_room_router = MagicMock()
        runtime.ward_room_router.extract_endorsements.return_value = (
            "Clean text.",
            [{"post_id": "abc", "direction": "up"}],
        )
        runtime.ward_room_router.process_endorsements = AsyncMock()
        runtime.skill_service = MagicMock()
        runtime.skill_service.record_exercise = MagicMock()
        runtime.is_cold_start = False

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)

        agent = MagicMock()
        agent.id = "agent-123"
        agent.agent_type = "security_officer"

        await loop._extract_and_execute_actions(agent, "Text [ENDORSE abc UP]")

        runtime.skill_service.record_exercise.assert_called_once_with(
            "agent-123", "communication"
        )
