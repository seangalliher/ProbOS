"""Tests for BuilderAgent, BuildSpec, BuildResult, and git helpers (AD-302/303)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.builder import (
    BuilderAgent,
    BuildResult,
    BuildSpec,
    _git_create_branch,
    _sanitize_branch_name,
    execute_approved_build,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentMessage


# ---------------------------------------------------------------------------
# BuildSpec / BuildResult
# ---------------------------------------------------------------------------


class TestBuildSpec:
    def test_defaults(self):
        """BuildSpec has correct default values."""
        spec = BuildSpec(title="Test", description="A test")
        assert spec.title == "Test"
        assert spec.description == "A test"
        assert spec.target_files == []
        assert spec.reference_files == []
        assert spec.test_files == []
        assert spec.ad_number == 0
        assert spec.branch_name == ""
        assert spec.constraints == []

    def test_full_population(self):
        """BuildSpec populates all fields."""
        spec = BuildSpec(
            title="Add VectorStore",
            description="Abstract vector store",
            target_files=["src/vec.py"],
            reference_files=["src/existing.py"],
            test_files=["tests/test_vec.py"],
            ad_number=400,
            branch_name="builder/ad-400-vector",
            constraints=["No new deps"],
        )
        assert spec.ad_number == 400
        assert spec.target_files == ["src/vec.py"]


class TestBuildResult:
    def test_defaults(self):
        """BuildResult has correct default values."""
        spec = BuildSpec(title="T", description="D")
        result = BuildResult(success=False, spec=spec)
        assert result.success is False
        assert result.files_written == []
        assert result.files_modified == []
        assert result.test_result == ""
        assert result.tests_passed is False
        assert result.branch_name == ""
        assert result.commit_hash == ""
        assert result.error == ""
        assert result.llm_output == ""


# ---------------------------------------------------------------------------
# BuilderAgent
# ---------------------------------------------------------------------------


class TestBuilderAgent:
    def test_is_cognitive_agent(self):
        """BuilderAgent is a CognitiveAgent subclass."""
        assert issubclass(BuilderAgent, CognitiveAgent)

    def test_agent_type(self):
        """agent_type is 'builder'."""
        assert BuilderAgent.agent_type == "builder"

    def test_handled_intents(self):
        """_handled_intents includes build_code."""
        assert "build_code" in BuilderAgent._handled_intents

    def test_intent_descriptors(self):
        """intent_descriptors has build_code with correct settings."""
        names = [d.name for d in BuilderAgent.intent_descriptors]
        assert "build_code" in names
        desc = BuilderAgent.intent_descriptors[0]
        assert desc.requires_consensus is True
        assert desc.tier == "domain"

    def test_tier(self):
        """BuilderAgent tier is 'domain'."""
        assert BuilderAgent.tier == "domain"

    def test_resolve_tier(self):
        """_resolve_tier returns 'deep'."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )
        assert agent._resolve_tier() == "deep"


class TestParseFileBlocks:
    def test_single_file_block(self):
        """Parses a single ===FILE:=== block."""
        text = '===FILE: src/foo.py===\nprint("hello")\n===END FILE==='
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["path"] == "src/foo.py"
        assert blocks[0]["mode"] == "create"
        assert 'print("hello")' in blocks[0]["content"]

    def test_multiple_file_blocks(self):
        """Parses multiple ===FILE:=== blocks."""
        text = (
            "===FILE: a.py===\ncode_a\n===END FILE===\n"
            "===FILE: b.py===\ncode_b\n===END FILE==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["path"] == "a.py"
        assert blocks[1]["path"] == "b.py"

    def test_modify_block(self):
        """Parses ===MODIFY:=== block with ===AFTER LINE:===."""
        text = (
            "===MODIFY: src/bar.py===\n"
            "===AFTER LINE: import os===\n"
            "import sys\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["path"] == "src/bar.py"
        assert blocks[0]["mode"] == "modify"
        assert blocks[0]["after_line"] == "import os"
        assert "import sys" in blocks[0]["content"]

    def test_no_blocks(self):
        """Returns empty list when no blocks found."""
        blocks = BuilderAgent._parse_file_blocks("Just some text with no markers")
        assert blocks == []

    def test_malformed_input(self):
        """Returns empty list for malformed markers."""
        text = "===FILE: foo.py===\nno end marker here"
        blocks = BuilderAgent._parse_file_blocks(text)
        assert blocks == []


class TestBuildUserMessage:
    def test_formats_spec(self):
        """_build_user_message formats build spec fields."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )
        obs = {
            "params": {
                "title": "Add VectorStore",
                "description": "Create ABC for vector stores",
                "target_files": ["src/vec.py"],
                "test_files": ["tests/test_vec.py"],
                "constraints": ["No new deps"],
                "ad_number": 400,
            },
            "file_context": "=== src/existing.py ===\nclass Existing: pass\n",
        }
        msg = agent._build_user_message(obs)
        assert "Add VectorStore" in msg
        assert "AD-400" in msg
        assert "src/vec.py" in msg
        assert "tests/test_vec.py" in msg
        assert "No new deps" in msg
        assert "Reference Code" in msg

    def test_handles_missing_fields(self):
        """_build_user_message handles missing/empty fields gracefully."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )
        obs = {"params": {"title": "Minimal"}}
        msg = agent._build_user_message(obs)
        assert "Minimal" in msg


class TestPerceive:
    @pytest.mark.asyncio
    async def test_perceive_reads_files(self, tmp_path: Path):
        """perceive() reads reference files and adds file_context."""
        ref_file = tmp_path / "ref.py"
        ref_file.write_text("class Ref: pass\n")

        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )

        intent = IntentMessage(
            intent="build_code",
            params={"reference_files": [str(ref_file)]},
        )
        obs = await agent.perceive(intent)
        assert "class Ref: pass" in obs["file_context"]

    @pytest.mark.asyncio
    async def test_perceive_handles_missing_files(self):
        """perceive() gracefully handles files that don't exist."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )

        intent = IntentMessage(
            intent="build_code",
            params={"reference_files": ["/nonexistent/path.py"]},
        )
        obs = await agent.perceive(intent)
        # Should not crash
        assert "file_context" in obs


class TestAct:
    @pytest.mark.asyncio
    async def test_act_parses_file_blocks(self):
        """act() parses file blocks from LLM output."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )
        decision = {
            "llm_output": "===FILE: src/test.py===\nprint('hi')\n===END FILE===",
        }
        result = await agent.act(decision)
        assert result["success"] is True
        assert result["result"]["change_count"] == 1

    @pytest.mark.asyncio
    async def test_act_error_on_no_blocks(self):
        """act() returns error when no file blocks in output."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )
        decision = {"llm_output": "No blocks here"}
        result = await agent.act(decision)
        assert result["success"] is False
        assert "no file blocks" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_act_handles_error_decision(self):
        """act() handles error action from decide()."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )
        decision = {"action": "error", "reason": "LLM failed"}
        result = await agent.act(decision)
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


class TestSanitizeBranch:
    def test_basic(self):
        """Sanitizes branch names to lowercase alphanum + hyphens."""
        assert _sanitize_branch_name("Add VectorStore ABC") == "add-vectorstore-abc"

    def test_max_length(self):
        """Branch names are capped at 50 chars."""
        name = "a" * 100
        assert len(_sanitize_branch_name(name)) == 50

    def test_special_chars(self):
        """Special characters are replaced with hyphens."""
        assert _sanitize_branch_name("feat/add_v2.0!") == "feat-add-v2-0"


class TestGitCreateBranch:
    @pytest.mark.asyncio
    async def test_success(self):
        """_git_create_branch calls git checkout -b."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("probos.cognitive.builder.asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await _git_create_branch("test-branch", "/tmp")
            assert ok is True

    @pytest.mark.asyncio
    async def test_failure(self):
        """_git_create_branch returns False on error."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"branch exists"))

        with patch("probos.cognitive.builder.asyncio.create_subprocess_exec", return_value=mock_proc):
            ok, msg = await _git_create_branch("test-branch", "/tmp")
            assert ok is False
            assert "branch exists" in msg


# ---------------------------------------------------------------------------
# execute_approved_build
# ---------------------------------------------------------------------------


class TestExecuteApprovedBuild:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, tmp_path: Path):
        """execute_approved_build writes files and calls git operations."""
        spec = BuildSpec(
            title="Test Build",
            description="A test build",
            ad_number=999,
        )
        file_changes = [
            {"path": "src/new_file.py", "content": "print('hello')\n", "mode": "create", "after_line": None},
        ]

        # Mock all git calls
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"main\n", b""))

        with patch("probos.cognitive.builder.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True
        assert result.branch_name != ""
        assert "src/new_file.py" in result.files_written
        # File should be written to disk
        written = tmp_path / "src" / "new_file.py"
        assert written.exists()
        assert written.read_text() == "print('hello')\n"

    @pytest.mark.asyncio
    async def test_skips_modify_mode(self, tmp_path: Path):
        """execute_approved_build skips MODIFY mode files with a warning."""
        spec = BuildSpec(title="Mod Test", description="Test modify skip")
        file_changes = [
            {"path": "src/mod.py", "content": "new code\n", "mode": "modify", "after_line": "import os"},
        ]

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"main\n", b""))

        with patch("probos.cognitive.builder.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        # Should succeed but no files written (modify skipped)
        assert result.success is True
        assert result.files_written == []

    @pytest.mark.asyncio
    async def test_branch_name_from_spec(self, tmp_path: Path):
        """Branch name is generated from spec title and ad_number."""
        spec = BuildSpec(title="Add VectorStore", description="Test", ad_number=400)
        file_changes = [
            {"path": "test.py", "content": "pass\n", "mode": "create", "after_line": None},
        ]

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"main\n", b""))

        with patch("probos.cognitive.builder.asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert "ad-400" in result.branch_name
