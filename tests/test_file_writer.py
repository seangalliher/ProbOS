"""Tests for FileWriterAgent."""

import pytest

from probos.agents.file_writer import FileWriterAgent
from probos.types import IntentMessage


class TestFileWriterAgent:
    @pytest.fixture
    def agent(self):
        a = FileWriterAgent(pool="filesystem")
        a.state = a.state  # Keep spawning state for testing
        return a

    def test_agent_type(self, agent):
        assert agent.agent_type == "file_writer"

    def test_capabilities(self, agent):
        caps = [c.can for c in agent.capabilities]
        assert "write_file" in caps

    @pytest.mark.asyncio
    async def test_handle_write_intent(self, agent, tmp_path):
        """Writer proposes a write without committing."""
        await agent.start()
        intent = IntentMessage(
            intent="write_file",
            params={"path": str(tmp_path / "new.txt"), "content": "hello"},
        )
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        assert result.result["requires_consensus"] is True
        assert result.result["path"] == str(tmp_path / "new.txt")
        # File should NOT actually be written yet
        assert not (tmp_path / "new.txt").exists()
        await agent.stop()

    @pytest.mark.asyncio
    async def test_handle_write_no_path(self, agent):
        """Missing path returns error."""
        await agent.start()
        intent = IntentMessage(
            intent="write_file",
            params={"content": "hello"},
        )
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is False
        assert "path" in result.error.lower()
        await agent.stop()

    @pytest.mark.asyncio
    async def test_handle_write_no_content(self, agent):
        """Missing content returns error."""
        await agent.start()
        intent = IntentMessage(
            intent="write_file",
            params={"path": "/tmp/test.txt"},
        )
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is False
        assert "content" in result.error.lower()
        await agent.stop()

    @pytest.mark.asyncio
    async def test_declines_unhandled_intent(self, agent):
        """Writer declines non-write intents."""
        await agent.start()
        intent = IntentMessage(intent="read_file", params={"path": "/tmp/test.txt"})
        result = await agent.handle_intent(intent)
        assert result is None
        await agent.stop()

    @pytest.mark.asyncio
    async def test_commit_write(self, tmp_path):
        """Static commit method actually writes the file."""
        path = str(tmp_path / "committed.txt")
        result = await FileWriterAgent.commit_write(path, "committed content")
        assert result["success"] is True
        assert (tmp_path / "committed.txt").read_text() == "committed content"

    @pytest.mark.asyncio
    async def test_commit_write_creates_dirs(self, tmp_path):
        """Commit creates parent directories if needed."""
        path = str(tmp_path / "sub" / "dir" / "file.txt")
        result = await FileWriterAgent.commit_write(path, "nested")
        assert result["success"] is True
        assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"
