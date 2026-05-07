"""AD-544: Tests for native SWE tool suite + register_native_swe_tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.swe_harness.tools import (
    CodebaseFindCallersTool,
    CodebaseFindTestsTool,
    CodebaseGetImportsTool,
    CodebaseQueryTool,
    CodebaseReadSourceTool,
    EditFileTool,
    ListFilesTool,
    ReadFileTool,
    RunCommandTool,
    StandingOrdersLookupTool,
    SystemSelfModelTool,
    WriteFileTool,
    register_native_swe_tools,
)
from probos.tools.protocol import ToolType
from probos.tools.registry import ToolRegistry


def _stub_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        codebase_index=SimpleNamespace(
            query=lambda c: {"matches": [c]},
            find_callers=lambda n, max_results=10: [{"name": n}],
            find_tests_for=lambda p: [f"tests/test_{Path(p).stem}.py"],
            get_imports=lambda p: ["os", "sys"],
        ),
        spawner=SimpleNamespace(list_pools=lambda: ["filesystem"]),
        registry=SimpleNamespace(all=lambda: []),
    )


def test_read_file_tool_metadata() -> None:
    t = ReadFileTool(_stub_runtime())
    assert t.tool_id == "read_file"
    assert t.tool_type == ToolType.UTILITY_AGENT
    assert "path" in t.input_schema["properties"]


def test_list_files_tool_metadata() -> None:
    t = ListFilesTool(_stub_runtime())
    assert t.tool_id == "list_files"
    assert "pattern" in t.input_schema["required"]


def test_codebase_query_tool_metadata() -> None:
    t = CodebaseQueryTool(_stub_runtime())
    assert t.tool_id == "codebase_query"
    assert t.tool_type == ToolType.DETERMINISTIC_FUNCTION


def test_codebase_find_callers_tool_metadata() -> None:
    t = CodebaseFindCallersTool(_stub_runtime())
    assert t.tool_id == "codebase_find_callers"


def test_codebase_find_tests_tool_metadata() -> None:
    t = CodebaseFindTestsTool(_stub_runtime())
    assert t.tool_id == "codebase_find_tests"


def test_codebase_get_imports_tool_metadata() -> None:
    t = CodebaseGetImportsTool(_stub_runtime())
    assert t.tool_id == "codebase_get_imports"


def test_codebase_read_source_tool_metadata() -> None:
    t = CodebaseReadSourceTool(_stub_runtime())
    assert t.tool_id == "codebase_read_source"


def test_standing_orders_lookup_tool_metadata() -> None:
    t = StandingOrdersLookupTool(_stub_runtime())
    assert t.tool_id == "standing_orders_lookup"
    assert t.input_schema["properties"]["scope"]["enum"] == ["ship", "department", "agent"]


def test_system_self_model_tool_metadata() -> None:
    t = SystemSelfModelTool(_stub_runtime())
    assert t.tool_id == "system_self_model"


def test_write_file_tool_metadata() -> None:
    t = WriteFileTool(_stub_runtime())
    assert t.tool_id == "write_file"
    assert "content" in t.input_schema["required"]


def test_edit_file_tool_metadata() -> None:
    t = EditFileTool(_stub_runtime())
    assert t.tool_id == "edit_file"


def test_run_command_tool_metadata() -> None:
    t = RunCommandTool(_stub_runtime())
    assert t.tool_id == "run_command"


def test_register_native_swe_tools_registers_twelve() -> None:
    registry = ToolRegistry()
    runtime = _stub_runtime()
    count = register_native_swe_tools(registry, runtime)
    assert count == 12
    # Every tool registered with engineering domain
    for tool_id in (
        "read_file", "list_files", "codebase_query", "codebase_find_callers",
        "codebase_find_tests", "codebase_get_imports", "codebase_read_source",
        "standing_orders_lookup", "system_self_model", "write_file",
        "edit_file", "run_command",
    ):
        reg = registry.get(tool_id)
        assert reg is not None
        assert reg.domain == "engineering"
        assert reg.default_permissions  # non-empty matrix
    # Spot-check rank-keyed permissions
    rf = registry.get("read_file")
    assert rf.default_permissions["ensign"] == "read"
    wf = registry.get("write_file")
    assert wf.default_permissions["ensign"] == "none"
    assert wf.default_permissions["lieutenant"] == "write"
    rc = registry.get("run_command")
    assert rc.default_permissions["lieutenant"] == "none"
    assert rc.default_permissions["commander"] == "write"


@pytest.mark.asyncio
async def test_read_file_tool_invoke_reads_file(tmp_path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello world", encoding="utf-8")
    t = ReadFileTool(_stub_runtime())
    result = await t.invoke({"path": str(target)})
    assert result.success
    assert result.output == "hello world"


@pytest.mark.asyncio
async def test_write_file_tool_returns_error_on_missing_content() -> None:
    t = WriteFileTool(_stub_runtime())
    result = await t.invoke({"path": "x"})
    assert not result.success
    assert "content is required" in (result.error or "")


@pytest.mark.asyncio
async def test_run_command_tool_returns_stdout_stderr_exit_code() -> None:
    import sys

    t = RunCommandTool(_stub_runtime())
    # Cross-platform: invoke python -c with a trivial print
    result = await t.invoke(
        {"command": f'"{sys.executable}" -c "print(\'hi\')"', "timeout": 10}
    )
    assert result.success, f"unexpected error: {result.error}"
    assert isinstance(result.output, dict)
    assert "stdout" in result.output
    assert "stderr" in result.output
    assert "exit_code" in result.output
    assert result.output["exit_code"] == 0
    assert "hi" in result.output["stdout"]
