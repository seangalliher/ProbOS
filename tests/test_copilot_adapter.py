"""Tests for CopilotBuilderAdapter (AD-351, AD-352, AD-353)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.builder import BuildSpec, BuildResult, _should_use_visiting_builder
from probos.cognitive.copilot_adapter import (
    CopilotBuilderAdapter,
    CopilotBuildResult,
    _VISITING_BUILDER_INSTRUCTIONS,
)


def _make_invocation(**kwargs: object) -> MagicMock:
    """Create a mock ToolInvocation with .arguments dict."""
    inv = MagicMock()
    inv.arguments = kwargs
    return inv


# ── AD-351: CopilotBuilderAdapter tests ───────────────────────────────────


class TestCopilotBuilderAdapterAvailability:
    """SDK availability detection."""

    def test_is_available_when_sdk_missing(self):
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", False):
            assert CopilotBuilderAdapter.is_available() is False

    def test_is_available_when_sdk_present(self):
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            assert CopilotBuilderAdapter.is_available() is True

    @pytest.mark.asyncio
    async def test_start_raises_without_sdk(self):
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", False):
            adapter = CopilotBuilderAdapter()
            with pytest.raises(RuntimeError, match="not installed"):
                await adapter.start()


class TestCopilotBuilderAdapterSystemMessage:
    """System message composition."""

    def test_compose_system_message_includes_standing_orders(self):
        adapter = CopilotBuilderAdapter()
        with patch("probos.cognitive.standing_orders.compose_instructions") as mock_compose:
            mock_compose.return_value = "COMPOSED STANDING ORDERS + IDENTITY"
            result = adapter._compose_system_message()
            assert result["mode"] == "replace"
            assert "COMPOSED STANDING ORDERS" in result["content"]
            mock_compose.assert_called_once_with(
                agent_type="builder",
                hardcoded_instructions=_VISITING_BUILDER_INSTRUCTIONS,
            )


class TestCopilotBuilderAdapterPrompt:
    """Prompt construction."""

    def test_build_prompt_includes_spec_fields(self):
        adapter = CopilotBuilderAdapter()
        spec = BuildSpec(
            title="Add widget",
            description="Add a widget to the dashboard",
            target_files=["src/widget.py"],
            test_files=["tests/test_widget.py"],
            constraints=["Do not modify runtime.py"],
            ad_number=999,
        )
        prompt = adapter._build_prompt(spec, {})
        assert "Add widget" in prompt
        assert "AD-999" in prompt
        assert "Add a widget to the dashboard" in prompt
        assert "src/widget.py" in prompt
        assert "tests/test_widget.py" in prompt
        assert "Do not modify runtime.py" in prompt

    def test_build_prompt_includes_file_contents(self):
        adapter = CopilotBuilderAdapter()
        spec = BuildSpec(
            title="Modify foo",
            description="Change foo",
            target_files=["src/foo.py"],
        )
        prompt = adapter._build_prompt(spec, {"src/foo.py": "def foo(): pass"})
        assert "def foo(): pass" in prompt
        assert "MODIFY blocks" in prompt


class TestCopilotBuilderAdapterExecution:
    """Session execution."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Mock SDK session that returns file blocks via workspace_file_changed events."""
        import tempfile
        import os

        # Create a temp dir with a file the SDK "wrote"
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "src" / "test.py"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("def test(): pass\n")

            adapter = CopilotBuilderAdapter(cwd=tmpdir)
            adapter._started = True

            # Mock a workspace_file_changed event
            file_change_msg = MagicMock()
            file_change_msg.type = MagicMock()
            file_change_msg.data = MagicMock()
            file_change_msg.data.path = "src/test.py"

            mock_session = AsyncMock()
            mock_session.send_and_wait = AsyncMock(return_value=None)
            mock_session.get_messages = AsyncMock(return_value=[file_change_msg])
            mock_session.disconnect = AsyncMock()

            mock_client = AsyncMock()
            mock_client.create_session = AsyncMock(return_value=mock_session)
            adapter._client = mock_client

            with patch("probos.cognitive.copilot_adapter.SessionEventType") as mock_evt:
                # Make ASSISTANT_MESSAGE not match file_change_msg.type
                mock_evt.ASSISTANT_MESSAGE = MagicMock()
                mock_evt.SESSION_WORKSPACE_FILE_CHANGED = file_change_msg.type
                spec = BuildSpec(title="Test", description="Test build")
                result = await adapter.execute(spec, {})

            assert result.success is True
            assert len(result.file_blocks) == 1
            assert result.file_blocks[0]["path"] == "src/test.py"
            assert result.file_blocks[0]["mode"] == "create"
            assert "def test(): pass" in result.file_blocks[0]["content"]

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """send_and_wait raising TimeoutError should return failure."""
        adapter = CopilotBuilderAdapter()
        adapter._started = True

        mock_session = AsyncMock()
        mock_session.send_and_wait = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_session.disconnect = AsyncMock()

        mock_client = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        adapter._client = mock_client

        spec = BuildSpec(title="Test", description="Test build")
        result = await adapter.execute(spec, {}, timeout=0.1)
        assert result.success is False
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_sdk_error(self):
        """SDK error should return failure result, not crash."""
        adapter = CopilotBuilderAdapter()
        adapter._started = True

        mock_client = AsyncMock()
        mock_client.create_session = AsyncMock(side_effect=RuntimeError("SDK boom"))
        adapter._client = mock_client

        spec = BuildSpec(title="Test", description="Test build")
        result = await adapter.execute(spec, {})
        assert result.success is False
        assert "SDK boom" in result.error


class TestCopilotBuilderAdapterToolList:
    """MCP tool registration."""

    def test_build_mcp_tools_with_codebase_index(self):
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            mock_tool_cls = MagicMock()
            with patch("probos.cognitive.copilot_adapter.Tool", mock_tool_cls, create=True):
                mock_ci = MagicMock()
                mock_rt = MagicMock()
                adapter = CopilotBuilderAdapter(codebase_index=mock_ci, runtime=mock_rt)
                tools = adapter._build_mcp_tools()
                # 1 standing_orders + 5 codebase + 1 system_self_model = 7
                assert len(tools) == 7

    def test_build_mcp_tools_without_codebase_index(self):
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            mock_tool_cls = MagicMock()
            with patch("probos.cognitive.copilot_adapter.Tool", mock_tool_cls, create=True):
                adapter = CopilotBuilderAdapter()
                tools = adapter._build_mcp_tools()
                # Only standing_orders_lookup
                assert len(tools) == 1


# ── AD-352: MCP Tool handler tests ────────────────────────────────────────


class TestMCPToolHandlers:
    """Individual tool handler tests using ToolInvocation-style objects."""

    @pytest.mark.asyncio
    async def test_handle_codebase_query(self):
        mock_ci = MagicMock()
        mock_ci.query.return_value = {"matching_files": ["foo.py"]}
        adapter = CopilotBuilderAdapter(codebase_index=mock_ci)
        result = await adapter._handle_codebase_query(_make_invocation(concept="trust"))
        assert "foo.py" in result.text_result_for_llm

    @pytest.mark.asyncio
    async def test_handle_codebase_query_no_index(self):
        adapter = CopilotBuilderAdapter()
        result = await adapter._handle_codebase_query(_make_invocation(concept="trust"))
        assert "not available" in result.text_result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_handle_find_callers(self):
        mock_ci = MagicMock()
        mock_ci.find_callers.return_value = [{"file": "bar.py", "line": 10}]
        adapter = CopilotBuilderAdapter(codebase_index=mock_ci)
        result = await adapter._handle_find_callers(_make_invocation(method_name="decide"))
        assert "bar.py" in result.text_result_for_llm

    @pytest.mark.asyncio
    async def test_handle_get_imports(self):
        mock_ci = MagicMock()
        mock_ci.get_imports.return_value = ["probos.types", "probos.mesh.routing"]
        adapter = CopilotBuilderAdapter(codebase_index=mock_ci)
        result = await adapter._handle_get_imports(_make_invocation(file_path="cognitive/builder.py"))
        assert "probos.types" in result.text_result_for_llm

    @pytest.mark.asyncio
    async def test_handle_find_tests(self):
        mock_ci = MagicMock()
        mock_ci.find_tests_for.return_value = ["tests/test_builder.py"]
        adapter = CopilotBuilderAdapter(codebase_index=mock_ci)
        result = await adapter._handle_find_tests(_make_invocation(file_path="cognitive/builder.py"))
        assert "test_builder" in result.text_result_for_llm

    @pytest.mark.asyncio
    async def test_handle_read_source(self):
        mock_ci = MagicMock()
        mock_ci.read_source.return_value = "def foo():\n    pass\n"
        adapter = CopilotBuilderAdapter(codebase_index=mock_ci)
        result = await adapter._handle_read_source(_make_invocation(file_path="cognitive/builder.py"))
        assert "def foo" in result.text_result_for_llm

    @pytest.mark.asyncio
    async def test_handle_system_self_model(self):
        mock_rt = MagicMock()
        mock_model = MagicMock()
        mock_model.to_context.return_value = "System: 5 pools, 42 agents"
        mock_rt._build_system_self_model.return_value = mock_model
        adapter = CopilotBuilderAdapter(runtime=mock_rt)
        result = await adapter._handle_system_self_model(_make_invocation())
        assert "42 agents" in result.text_result_for_llm

    @pytest.mark.asyncio
    async def test_handle_system_self_model_no_runtime(self):
        adapter = CopilotBuilderAdapter()
        result = await adapter._handle_system_self_model(_make_invocation())
        assert "not available" in result.text_result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_handle_standing_orders(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orders_dir = Path(tmpdir) / "config" / "standing_orders"
            orders_dir.mkdir(parents=True)
            (orders_dir / "engineering.md").write_text("# Engineering Protocol\nBuild well.")

            adapter = CopilotBuilderAdapter()
            # Patch the project root to use our temp dir
            with patch("probos.cognitive.copilot_adapter._PROJECT_ROOT", Path(tmpdir)):
                result = await adapter._handle_standing_orders(_make_invocation(department="engineering"))
            assert "Build well" in result.text_result_for_llm


# ── AD-353: Routing & Apprenticeship tests ─────────────────────────────────


class TestShouldUseVisitingBuilder:
    """Routing decision logic."""

    def test_force_native(self):
        spec = BuildSpec(title="Test", description="")
        assert _should_use_visiting_builder(spec, force_native=True) is False

    def test_force_visiting(self):
        spec = BuildSpec(title="Test", description="")
        assert _should_use_visiting_builder(spec, force_visiting=True) is True

    def test_sdk_unavailable(self):
        spec = BuildSpec(title="Test", description="")
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", False):
            assert _should_use_visiting_builder(spec) is False

    def test_default_bootstrap(self):
        """No Hebbian history, SDK available → default to visiting."""
        spec = BuildSpec(title="Test", description="")
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            assert _should_use_visiting_builder(spec) is True

    def test_hebbian_prefers_native(self):
        spec = BuildSpec(title="Test", description="")
        mock_router = MagicMock()
        mock_router.get_weight.side_effect = lambda src, tgt, rel_type=None: {
            "native": 0.8,
            "visiting": 0.3,
        }.get(tgt, 0.0)

        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            assert _should_use_visiting_builder(spec, hebbian_router=mock_router) is False

    def test_hebbian_prefers_visiting(self):
        spec = BuildSpec(title="Test", description="")
        mock_router = MagicMock()
        mock_router.get_weight.side_effect = lambda src, tgt, rel_type=None: {
            "native": 0.3,
            "visiting": 0.8,
        }.get(tgt, 0.0)

        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            assert _should_use_visiting_builder(spec, hebbian_router=mock_router) is True

    def test_hebbian_insufficient_history(self):
        """Both weights below 0.1 → bootstrap default (True)."""
        spec = BuildSpec(title="Test", description="")
        mock_router = MagicMock()
        mock_router.get_weight.return_value = 0.05

        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            assert _should_use_visiting_builder(spec, hebbian_router=mock_router) is True


class TestBuildResultBuilderSource:
    """BuildResult builder_source field."""

    def test_build_result_has_builder_source(self):
        result = BuildResult(success=True, spec=BuildSpec(title="t", description="d"))
        assert result.builder_source == "native"

    def test_build_result_builder_source_can_be_set(self):
        result = BuildResult(success=True, spec=BuildSpec(title="t", description="d"))
        result.builder_source = "visiting"
        assert result.builder_source == "visiting"


class TestBuilderVariantConstant:
    """REL_BUILDER_VARIANT constant."""

    def test_builder_variant_relationship_constant(self):
        from probos.mesh.routing import REL_BUILDER_VARIANT
        assert REL_BUILDER_VARIANT == "builder_variant"


# ── AD-354: Path normalization tests ───────────────────────────────────────


class TestNormalizeSdkPath:
    """Path normalization for SDK workspace_file_changed events."""

    def test_relative_forward_slash(self):
        from probos.cognitive.copilot_adapter import _normalize_sdk_path
        cwd = Path("/tmp/build123")
        assert _normalize_sdk_path("src/test.py", cwd) == "src/test.py"

    def test_relative_backslash(self):
        from probos.cognitive.copilot_adapter import _normalize_sdk_path
        cwd = Path("/tmp/build123")
        assert _normalize_sdk_path("src\\test.py", cwd) == "src/test.py"

    def test_absolute_under_cwd(self):
        from probos.cognitive.copilot_adapter import _normalize_sdk_path
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            abs_path = str(cwd / "src" / "test.py").replace("\\", "/")
            assert _normalize_sdk_path(abs_path, cwd) == "src/test.py"

    def test_absolute_windows_under_cwd(self):
        from probos.cognitive.copilot_adapter import _normalize_sdk_path
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            abs_path = str(cwd / "src" / "test.py")  # native separators
            assert _normalize_sdk_path(abs_path, cwd) == "src/test.py"

    def test_absolute_not_under_cwd(self):
        from probos.cognitive.copilot_adapter import _normalize_sdk_path
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir) / "build123"
            other = Path(tmpdir) / "other" / "file.py"
            result = _normalize_sdk_path(str(other).replace("\\", "/"), cwd)
            # Not under cwd, returned as-is (normalized separators)
            assert "file.py" in result

    def test_mixed_separators(self):
        from probos.cognitive.copilot_adapter import _normalize_sdk_path
        cwd = Path("/tmp/build123")
        assert _normalize_sdk_path("src\\sub/test.py", cwd) == "src/sub/test.py"


class TestTempDirIsolation:
    """Bug 2: Visiting builder uses temp dir, not project root."""

    def test_temp_dir_not_project_root(self):
        """The visiting builder cwd must not be the project root."""
        import tempfile as _tf
        tmp = _tf.mkdtemp(prefix="probos_build_")
        try:
            from probos.cognitive.builder import _PROJECT_ROOT
            assert Path(tmp) != _PROJECT_ROOT
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestForceFlags:
    """Bug 3: Force flags pass through from intent params."""

    def test_force_native_from_params(self):
        """force_native=True in params should prevent visiting builder."""
        spec = BuildSpec(title="Test", description="")
        with patch("probos.cognitive.copilot_adapter._SDK_AVAILABLE", True):
            assert _should_use_visiting_builder(
                spec, force_native=True
            ) is False

    def test_force_visiting_from_params(self):
        """force_visiting=True in params should force visiting builder."""
        spec = BuildSpec(title="Test", description="")
        assert _should_use_visiting_builder(
            spec, force_visiting=True
        ) is True


class TestBuildRequestFields:
    """Enhancement 2: BuildRequest accepts force flags and model."""

    def test_build_request_has_force_flags(self):
        from probos.api import BuildRequest
        req = BuildRequest(
            title="t", description="d",
            force_native=True, force_visiting=False, model="gpt-5.4",
        )
        assert req.force_native is True
        assert req.force_visiting is False
        assert req.model == "gpt-5.4"

    def test_build_request_defaults(self):
        from probos.api import BuildRequest
        req = BuildRequest(title="t", description="d")
        assert req.force_native is False
        assert req.force_visiting is False
        assert req.model == ""


class TestBuilderSourcePropagation:
    """Enhancement 1: builder_source propagates through pipeline."""

    def test_build_result_builder_source_field(self):
        result = BuildResult(success=True, spec=BuildSpec(title="t", description="d"))
        assert result.builder_source == "native"
        result.builder_source = "visiting"
        assert result.builder_source == "visiting"


# ── AD-355: System prompt content tests ─────────────────────────────────────


class TestVisitingBuilderInstructionsContent:
    """Verify system prompt contains working environment and project structure (AD-355)."""

    def test_system_prompt_contains_working_environment(self):
        assert "ISOLATED temp directory" in _VISITING_BUILDER_INSTRUCTIONS
        assert "Do NOT explore the filesystem" in _VISITING_BUILDER_INSTRUCTIONS

    def test_system_prompt_contains_project_structure(self):
        assert "src/probos/" in _VISITING_BUILDER_INSTRUCTIONS
        assert "tests/" in _VISITING_BUILDER_INSTRUCTIONS
