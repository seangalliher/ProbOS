"""Tests for FileReaderAgent."""

import pytest

from probos.agents.file_reader import FileReaderAgent
from probos.types import AgentState, IntentMessage


class TestFileReaderAgent:
    def test_agent_type_and_capabilities(self):
        agent = FileReaderAgent(pool="filesystem")
        assert agent.agent_type == "file_reader"
        assert any(c.can == "read_file" for c in agent.capabilities)
        assert any(c.can == "stat_file" for c in agent.capabilities)

    @pytest.mark.asyncio
    async def test_read_file(self, tmp_path):
        test_file = tmp_path / "hello.txt"
        test_file.write_text("Hello ProbOS!")

        agent = FileReaderAgent()
        intent = IntentMessage(
            intent="read_file",
            params={"path": str(test_file)},
        )

        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert result.result == "Hello ProbOS!"
        assert result.agent_id == agent.id

    @pytest.mark.asyncio
    async def test_read_missing_file(self, tmp_path):
        agent = FileReaderAgent()
        intent = IntentMessage(
            intent="read_file",
            params={"path": str(tmp_path / "missing.txt")},
        )

        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_stat_file(self, tmp_path):
        test_file = tmp_path / "data.txt"
        test_file.write_text("some content")

        agent = FileReaderAgent()
        intent = IntentMessage(
            intent="stat_file",
            params={"path": str(test_file)},
        )

        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert result.result["size"] == 12
        assert result.result["is_file"] is True

    @pytest.mark.asyncio
    async def test_declines_unhandled_intent(self):
        agent = FileReaderAgent()
        intent = IntentMessage(intent="send_email", params={})

        result = await agent.handle_intent(intent)
        assert result is None  # Declined

    @pytest.mark.asyncio
    async def test_missing_path_returns_error(self):
        agent = FileReaderAgent()
        intent = IntentMessage(intent="read_file", params={})

        result = await agent.handle_intent(intent)
        assert result is not None
        assert not result.success
        assert "no path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_confidence_updated_on_success(self, tmp_path):
        test_file = tmp_path / "conf.txt"
        test_file.write_text("data")

        agent = FileReaderAgent()
        original = agent.confidence
        intent = IntentMessage(
            intent="read_file",
            params={"path": str(test_file)},
        )
        await agent.handle_intent(intent)
        assert agent.confidence > original

    @pytest.mark.asyncio
    async def test_confidence_updated_on_failure(self, tmp_path):
        agent = FileReaderAgent()
        original = agent.confidence
        intent = IntentMessage(
            intent="read_file",
            params={"path": str(tmp_path / "nope.txt")},
        )
        await agent.handle_intent(intent)
        assert agent.confidence < original
