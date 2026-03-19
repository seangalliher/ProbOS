"""Tests for BuilderAgent, BuildSpec, BuildResult, and git helpers (AD-302/303)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.builder import (
    BuilderAgent,
    BuildResult,
    BuildSpec,
    _build_fix_prompt,
    _git_create_branch,
    _run_tests,
    _sanitize_branch_name,
    _validate_python,
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
        """Old ===MODIFY:=== block with ===AFTER LINE:=== is deprecated and skipped."""
        text = (
            "===MODIFY: src/bar.py===\n"
            "===AFTER LINE: import os===\n"
            "import sys\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        # Deprecated format is now skipped
        assert len(blocks) == 0

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
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            ok, msg = await _git_create_branch("test-branch", "/tmp")
            assert ok is True

    @pytest.mark.asyncio
    async def test_failure(self):
        """_git_create_branch returns False on error."""
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"branch exists")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
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
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
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
    async def test_modify_skips_nonexistent_file(self, tmp_path: Path):
        """execute_approved_build skips MODIFY when target file doesn't exist."""
        spec = BuildSpec(title="Mod Test", description="Test modify skip")
        file_changes = [
            {
                "path": "src/mod.py",
                "mode": "modify",
                "replacements": [{"search": "old", "replace": "new"}],
            },
        ]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        # Should succeed but no files written or modified (target doesn't exist)
        assert result.success is True
        assert result.files_written == []
        assert result.files_modified == []

    @pytest.mark.asyncio
    async def test_branch_name_from_spec(self, tmp_path: Path):
        """Branch name is generated from spec title and ad_number."""
        spec = BuildSpec(title="Add VectorStore", description="Test", ad_number=400)
        file_changes = [
            {"path": "test.py", "content": "pass\n", "mode": "create", "after_line": None},
        ]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert "ad-400" in result.branch_name


# ---------------------------------------------------------------------------
# MODIFY block parsing (AD-313)
# ---------------------------------------------------------------------------


class TestParseModifyBlocks:
    def test_single_search_replace(self):
        """Parses a single SEARCH/REPLACE pair in a MODIFY block."""
        text = (
            "===MODIFY: src/foo.py===\n"
            "===SEARCH===\n"
            "def old():\n"
            "    return 1\n"
            "===REPLACE===\n"
            "def old():\n"
            "    return 2\n"
            "===END REPLACE===\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["path"] == "src/foo.py"
        assert blocks[0]["mode"] == "modify"
        assert len(blocks[0]["replacements"]) == 1
        assert blocks[0]["replacements"][0]["search"] == "def old():\n    return 1"
        assert blocks[0]["replacements"][0]["replace"] == "def old():\n    return 2"

    def test_multiple_search_replace_pairs(self):
        """Parses multiple SEARCH/REPLACE pairs in one MODIFY block."""
        text = (
            "===MODIFY: src/bar.py===\n"
            "===SEARCH===\n"
            "import os\n"
            "===REPLACE===\n"
            "import os\n"
            "import sys\n"
            "===END REPLACE===\n"
            "\n"
            "===SEARCH===\n"
            "x = 1\n"
            "===REPLACE===\n"
            "x = 2\n"
            "===END REPLACE===\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 1
        assert len(blocks[0]["replacements"]) == 2
        assert blocks[0]["replacements"][0]["search"] == "import os"
        assert blocks[0]["replacements"][0]["replace"] == "import os\nimport sys"
        assert blocks[0]["replacements"][1]["search"] == "x = 1"
        assert blocks[0]["replacements"][1]["replace"] == "x = 2"

    def test_mixed_file_and_modify(self):
        """Parses both FILE and MODIFY blocks in the same output."""
        text = (
            "===FILE: src/new.py===\nprint('new')\n===END FILE===\n"
            "===MODIFY: src/existing.py===\n"
            "===SEARCH===\nold_line\n===REPLACE===\nnew_line\n===END REPLACE===\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 2
        create_blocks = [b for b in blocks if b["mode"] == "create"]
        modify_blocks = [b for b in blocks if b["mode"] == "modify"]
        assert len(create_blocks) == 1
        assert len(modify_blocks) == 1
        assert create_blocks[0]["path"] == "src/new.py"
        assert modify_blocks[0]["path"] == "src/existing.py"

    def test_modify_no_search_replace_skipped(self):
        """MODIFY block with no SEARCH/REPLACE pairs is skipped."""
        text = (
            "===MODIFY: src/empty.py===\n"
            "just some text, no markers\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 0

    def test_whitespace_preservation(self):
        """Indentation is preserved exactly in SEARCH/REPLACE content."""
        text = (
            "===MODIFY: src/indent.py===\n"
            "===SEARCH===\n"
            "    def method(self):\n"
            "        return None\n"
            "===REPLACE===\n"
            "    def method(self):\n"
            "        return 42\n"
            "===END REPLACE===\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        assert len(blocks) == 1
        assert "    def method(self):" in blocks[0]["replacements"][0]["search"]
        assert "        return None" in blocks[0]["replacements"][0]["search"]
        assert "        return 42" in blocks[0]["replacements"][0]["replace"]

    def test_deprecated_after_line_skipped(self):
        """Old ===AFTER LINE:=== format is skipped with deprecation warning."""
        text = (
            "===MODIFY: src/old.py===\n"
            "===AFTER LINE: import os===\n"
            "import sys\n"
            "===END MODIFY==="
        )
        blocks = BuilderAgent._parse_file_blocks(text)
        # Should be skipped (no crash, no block added)
        assert len(blocks) == 0


# ---------------------------------------------------------------------------
# MODIFY execution (AD-313)
# ---------------------------------------------------------------------------


class TestExecuteModify:
    @pytest.mark.asyncio
    async def test_basic_modify(self, tmp_path: Path):
        """Single replacement applied correctly to existing file."""
        target = tmp_path / "src" / "target.py"
        target.parent.mkdir(parents=True)
        target.write_text("def hello():\n    return 'old'\n", encoding="utf-8")

        spec = BuildSpec(title="Modify Test", description="Test modify")
        file_changes = [{
            "path": "src/target.py",
            "mode": "modify",
            "replacements": [{"search": "return 'old'", "replace": "return 'new'"}],
        }]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True
        assert "src/target.py" in result.files_modified
        assert result.files_written == []
        content = target.read_text(encoding="utf-8")
        assert "return 'new'" in content
        assert "return 'old'" not in content

    @pytest.mark.asyncio
    async def test_multiple_replacements(self, tmp_path: Path):
        """Multiple replacements applied sequentially."""
        target = tmp_path / "multi.py"
        target.write_text("import os\n\nx = 1\ny = 2\n", encoding="utf-8")

        spec = BuildSpec(title="Multi", description="Multiple replacements")
        file_changes = [{
            "path": "multi.py",
            "mode": "modify",
            "replacements": [
                {"search": "import os", "replace": "import os\nimport sys"},
                {"search": "x = 1", "replace": "x = 10"},
            ],
        }]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True
        assert "multi.py" in result.files_modified
        content = target.read_text(encoding="utf-8")
        assert "import sys" in content
        assert "x = 10" in content

    @pytest.mark.asyncio
    async def test_modify_file_not_exists(self, tmp_path: Path):
        """MODIFY on nonexistent file is skipped without crashing."""
        spec = BuildSpec(title="No File", description="Missing target")
        file_changes = [{
            "path": "nonexistent.py",
            "mode": "modify",
            "replacements": [{"search": "old", "replace": "new"}],
        }]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True
        assert result.files_modified == []

    @pytest.mark.asyncio
    async def test_search_text_not_found(self, tmp_path: Path):
        """Replacement skipped when SEARCH text not found; other replacements still apply."""
        target = tmp_path / "partial.py"
        target.write_text("a = 1\nb = 2\n", encoding="utf-8")

        spec = BuildSpec(title="Partial", description="Partial match")
        file_changes = [{
            "path": "partial.py",
            "mode": "modify",
            "replacements": [
                {"search": "c = 3", "replace": "c = 30"},  # not found
                {"search": "b = 2", "replace": "b = 20"},  # found
            ],
        }]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True
        assert "partial.py" in result.files_modified
        content = target.read_text(encoding="utf-8")
        assert "b = 20" in content
        assert "a = 1" in content

    @pytest.mark.asyncio
    async def test_mixed_create_and_modify(self, tmp_path: Path):
        """Both create and modify changes handled in one build."""
        existing = tmp_path / "existing.py"
        existing.write_text("old_value = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Mixed", description="Create and modify")
        file_changes = [
            {"path": "new_file.py", "content": "print('new')\n", "mode": "create", "after_line": None},
            {
                "path": "existing.py",
                "mode": "modify",
                "replacements": [{"search": "old_value = 1", "replace": "old_value = 2"}],
            },
        ]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True
        assert "new_file.py" in result.files_written
        assert "existing.py" in result.files_modified

    @pytest.mark.asyncio
    async def test_no_net_change(self, tmp_path: Path):
        """When all SEARCH texts not found, files_modified stays empty."""
        target = tmp_path / "noop.py"
        target.write_text("keep = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Noop", description="No match")
        file_changes = [{
            "path": "noop.py",
            "mode": "modify",
            "replacements": [{"search": "missing_text", "replace": "new_text"}],
        }]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True
        assert result.files_modified == []


# ---------------------------------------------------------------------------
# AST validation (AD-313)
# ---------------------------------------------------------------------------


class TestValidatePython:
    def test_valid_python(self, tmp_path: Path):
        """Valid Python returns None."""
        f = tmp_path / "good.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert _validate_python(f) is None

    def test_syntax_error(self, tmp_path: Path):
        """Syntax error returns error string with line number."""
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n", encoding="utf-8")
        err = _validate_python(f)
        assert err is not None
        assert "line" in err

    def test_non_python_skipped(self, tmp_path: Path):
        """Non-Python files return None (skipped)."""
        f = tmp_path / "data.json"
        f.write_text("{broken json", encoding="utf-8")
        assert _validate_python(f) is None


# ---------------------------------------------------------------------------
# perceive() target files (AD-313)
# ---------------------------------------------------------------------------


class TestPerceiveTargetFiles:
    @pytest.mark.asyncio
    async def test_target_file_exists(self, tmp_path: Path):
        """perceive() reads existing target file into target_context."""
        target = tmp_path / "target.py"
        target.write_text("class Target: pass\n")

        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )

        intent = IntentMessage(
            intent="build_code",
            params={"target_files": [str(target)]},
        )
        obs = await agent.perceive(intent)
        assert "class Target: pass" in obs["target_context"]
        assert "TARGET" in obs["target_context"]

    @pytest.mark.asyncio
    async def test_target_file_not_exists(self):
        """perceive() notes nonexistent target as 'new file'."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )

        intent = IntentMessage(
            intent="build_code",
            params={"target_files": ["/nonexistent/new_file.py"]},
        )
        obs = await agent.perceive(intent)
        assert "target_context" in obs
        # Nonexistent path doesn't pass .exists() check, so it's just not included
        # (exception handling catches path issues)

    @pytest.mark.asyncio
    async def test_both_target_and_reference(self, tmp_path: Path):
        """perceive() loads both target and reference files."""
        ref = tmp_path / "ref.py"
        ref.write_text("class Ref: pass\n")
        target = tmp_path / "target.py"
        target.write_text("class Target: pass\n")

        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(),
        )

        intent = IntentMessage(
            intent="build_code",
            params={
                "reference_files": [str(ref)],
                "target_files": [str(target)],
            },
        )
        obs = await agent.perceive(intent)
        assert "class Ref: pass" in obs["file_context"]
        assert "class Target: pass" in obs["target_context"]


# ---------------------------------------------------------------------------
# Test-fix loop (AD-314)
# ---------------------------------------------------------------------------


class TestTestFixLoop:
    @pytest.mark.asyncio
    async def test_fix_loop_passes_on_first_try(self, tmp_path: Path):
        """Tests pass on first try — no fix attempts needed."""
        target = tmp_path / "ok.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="OK Build", description="Tests pass")
        file_changes = [
            {"path": "ok.py", "content": "x = 1\n", "mode": "create", "after_line": None},
        ]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_tests", return_value=(True, "1 passed")):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                )

        assert result.tests_passed is True
        assert result.fix_attempts == 0

    @pytest.mark.asyncio
    async def test_fix_loop_fixes_on_second_try(self, tmp_path: Path):
        """Tests fail once, LLM fix succeeds on retry."""
        target = tmp_path / "fixme.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Fix Build", description="Needs fix")
        file_changes = [
            {"path": "fixme.py", "content": "x = 1\n", "mode": "create", "after_line": None},
        ]

        # LLM returns a MODIFY block to fix the issue
        llm_client = AsyncMock()
        llm_fix_response = MagicMock()
        llm_fix_response.content = (
            "===MODIFY: fixme.py===\n"
            "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
            "===END MODIFY==="
        )
        llm_client.complete = AsyncMock(return_value=llm_fix_response)

        # First test fails, second passes
        test_results = [(False, "1 failed"), (True, "1 passed")]
        call_count = 0

        async def mock_run_tests(work_dir, timeout=120):
            nonlocal call_count
            result = test_results[min(call_count, len(test_results) - 1)]
            call_count += 1
            return result

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_tests", side_effect=mock_run_tests):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                    llm_client=llm_client,
                )

        assert result.tests_passed is True
        assert result.fix_attempts == 1
        assert llm_client.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_fix_loop_exhausts_retries(self, tmp_path: Path):
        """Tests fail on all attempts — retries exhausted."""
        target = tmp_path / "broken.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Broken Build", description="Always fails")
        file_changes = [
            {"path": "broken.py", "content": "x = 1\n", "mode": "create", "after_line": None},
        ]

        llm_client = AsyncMock()
        llm_fix_response = MagicMock()
        llm_fix_response.content = (
            "===MODIFY: broken.py===\n"
            "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
            "===END MODIFY==="
        )
        llm_client.complete = AsyncMock(return_value=llm_fix_response)

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_tests", return_value=(False, "1 failed")):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                    max_fix_attempts=2, llm_client=llm_client,
                )

        assert result.tests_passed is False
        assert result.fix_attempts == 2

    @pytest.mark.asyncio
    async def test_fix_loop_skips_empty_llm_response(self, tmp_path: Path):
        """Empty LLM response is handled gracefully — skips fix, increments attempt."""
        target = tmp_path / "empty.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Empty Fix", description="LLM returns nothing")
        file_changes = [
            {"path": "empty.py", "content": "x = 1\n", "mode": "create", "after_line": None},
        ]

        llm_client = AsyncMock()
        llm_fix_response = MagicMock()
        llm_fix_response.content = "I'm not sure what to fix."  # no file blocks
        llm_client.complete = AsyncMock(return_value=llm_fix_response)

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_tests", return_value=(False, "1 failed")):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                    max_fix_attempts=1, llm_client=llm_client,
                )

        assert result.tests_passed is False
        assert result.fix_attempts == 1

    def test_fix_prompt_truncates_long_output(self):
        """_build_fix_prompt truncates test output to last 3000 chars."""
        long_output = "X" * 5000
        changes = [{"path": "foo.py", "mode": "create"}]
        prompt = _build_fix_prompt("Test", long_output, changes, 1)
        # The prompt should contain only the last 3000 chars of test output
        assert "X" * 3000 in prompt
        assert "X" * 5000 not in prompt

    @pytest.mark.asyncio
    async def test_run_tests_helper(self):
        """_run_tests returns (True, output) on success and (False, output) on failure."""
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"5 passed\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            passed, output = await _run_tests("/tmp/test")
            assert passed is True
            assert "5 passed" in output

        # Failure case
        mock_fail = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"2 failed\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_fail):
            passed, output = await _run_tests("/tmp/test")
            assert passed is False
            assert "2 failed" in output

    @pytest.mark.asyncio
    async def test_fix_loop_disabled_with_zero_retries(self, tmp_path: Path):
        """max_fix_attempts=0 means no LLM fix calls are made."""
        target = tmp_path / "noop.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="No Retry", description="Zero retries")
        file_changes = [
            {"path": "noop.py", "content": "x = 1\n", "mode": "create", "after_line": None},
        ]

        llm_client = AsyncMock()

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_tests", return_value=(False, "1 failed")):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                    max_fix_attempts=0, llm_client=llm_client,
                )

        assert result.tests_passed is False
        assert result.fix_attempts == 0
        llm_client.complete.assert_not_called()
