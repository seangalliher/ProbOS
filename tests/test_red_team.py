"""Tests for RedTeamAgent."""

import pytest

from probos.agents.red_team import RedTeamAgent
from probos.types import IntentMessage, IntentResult


class TestRedTeamAgent:
    @pytest.fixture
    def agent(self):
        a = RedTeamAgent(pool="red_team")
        return a

    def test_agent_type(self, agent):
        assert agent.agent_type == "red_team"

    def test_capabilities(self, agent):
        caps = [c.can for c in agent.capabilities]
        assert "verify_read_file" in caps
        assert "verify_stat_file" in caps

    @pytest.mark.asyncio
    async def test_verify_read_file_correct(self, agent, tmp_path):
        """Red team verifies a correct read result."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        intent = IntentMessage(intent="read_file", params={"path": str(test_file)})
        claimed = IntentResult(
            intent_id=intent.id,
            agent_id="target-agent",
            success=True,
            result="hello world",
            confidence=0.8,
        )

        vr = await agent.verify("target-agent", intent, claimed)
        assert vr.verified is True
        assert vr.verifier_id == agent.id
        assert vr.target_agent_id == "target-agent"

    @pytest.mark.asyncio
    async def test_verify_read_file_corrupted(self, agent, tmp_path):
        """Red team catches corrupted data."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        intent = IntentMessage(intent="read_file", params={"path": str(test_file)})
        claimed = IntentResult(
            intent_id=intent.id,
            agent_id="bad-agent",
            success=True,
            result="CORRUPTED DATA",
            confidence=0.8,
        )

        vr = await agent.verify("bad-agent", intent, claimed)
        assert vr.verified is False
        assert "mismatch" in vr.discrepancy.lower()

    @pytest.mark.asyncio
    async def test_verify_missing_file_correct_failure(self, agent, tmp_path):
        """Agent correctly reports failure for missing file."""
        intent = IntentMessage(
            intent="read_file", params={"path": str(tmp_path / "missing.txt")}
        )
        claimed = IntentResult(
            intent_id=intent.id,
            agent_id="good-agent",
            success=False,
            error="File not found",
            confidence=0.8,
        )

        vr = await agent.verify("good-agent", intent, claimed)
        assert vr.verified is True

    @pytest.mark.asyncio
    async def test_verify_missing_file_false_success(self, agent, tmp_path):
        """Agent falsely claims success for missing file."""
        intent = IntentMessage(
            intent="read_file", params={"path": str(tmp_path / "missing.txt")}
        )
        claimed = IntentResult(
            intent_id=intent.id,
            agent_id="liar-agent",
            success=True,
            result="fake data",
            confidence=0.8,
        )

        vr = await agent.verify("liar-agent", intent, claimed)
        assert vr.verified is False
        assert "does not exist" in vr.discrepancy.lower()

    @pytest.mark.asyncio
    async def test_verify_unknown_intent(self, agent):
        """Unknown intent types get benefit of doubt."""
        intent = IntentMessage(intent="send_email", params={"to": "test@test.com"})
        claimed = IntentResult(
            intent_id=intent.id,
            agent_id="some-agent",
            success=True,
            result="sent",
            confidence=0.8,
        )

        vr = await agent.verify("some-agent", intent, claimed)
        assert vr.verified is True
        assert vr.confidence == 0.1  # Low confidence for unknown

    @pytest.mark.asyncio
    async def test_lifecycle_methods_are_noop(self, agent):
        """Red team agents are passive — lifecycle methods return None."""
        assert await agent.perceive({"intent": "read_file"}) is None
        assert await agent.decide("obs") is None
        assert await agent.act("plan") is None
        assert await agent.report("result") == {}
