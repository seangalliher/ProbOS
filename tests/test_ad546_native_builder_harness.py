"""AD-546: Tests for NativeBuilderHarness + SoftwareEngineerAgent routing branch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
from probos.cognitive.swe_harness.tool_call import TextBlock


class _FakeRegistry:
    def __init__(self) -> None:
        self._tools: dict = {}

    def add(self, tool_id: str) -> None:
        # Build a minimal Tool-shaped object
        tool = SimpleNamespace(
            tool_id=tool_id,
            name=tool_id,
            description=f"desc {tool_id}",
            input_schema={"type": "object", "properties": {}},
        )
        self._tools[tool_id] = SimpleNamespace(tool=tool)

    def get(self, tool_id: str):
        return self._tools.get(tool_id)


def _make_harness(*, llm_client=None, executor=None, registry=None) -> NativeBuilderHarness:
    runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
    return NativeBuilderHarness(
        runtime=runtime,
        llm_client=llm_client or MagicMock(),
        tool_executor=executor or MagicMock(),
        tool_registry=registry or _FakeRegistry(),
    )


def test_harness_init_accepts_kwargs() -> None:
    h = _make_harness()
    assert h._max_iter == 25
    assert h._max_fix_iter == 5


def test_select_build_tools_filters_to_build_relevant() -> None:
    reg = _FakeRegistry()
    reg.add("read_file")
    reg.add("write_file")
    reg.add("system_self_model")  # not in build subset
    h = _make_harness(registry=reg)
    defs = h._select_build_tools()
    names = {d["function"]["name"] for d in defs}
    assert "read_file" in names
    assert "write_file" in names
    assert "system_self_model" not in names


def test_compose_system_prompt_includes_constraints_and_instructions() -> None:
    from probos.cognitive.builder import BuildSpec

    spec = BuildSpec(
        title="t",
        description="d",
        constraints=["use type hints", "no globals"],
    )
    h = _make_harness()
    prompt = h._compose_system_prompt(spec)
    assert "use type hints" in prompt
    assert "no globals" in prompt
    assert "===FILE:" in prompt or "===MODIFY:" in prompt


def test_format_build_message_contains_spec_fields() -> None:
    from probos.cognitive.builder import BuildSpec

    spec = BuildSpec(
        title="my-build",
        description="desc",
        target_files=["a.py"],
        reference_files=["b.py"],
        test_files=["test_a.py"],
        ad_number=999,
    )
    h = _make_harness()
    msg = h._format_build_message(spec, "/tmp/work")
    assert "my-build" in msg
    assert "AD-999" in msg
    assert "a.py" in msg
    assert "b.py" in msg
    assert "test_a.py" in msg
    assert "/tmp/work" in msg


@pytest.mark.asyncio
async def test_run_build_invokes_loop_and_returns_dict() -> None:
    from probos.cognitive.builder import BuildSpec

    # LLM returns plain text containing one ===FILE block
    file_block_text = (
        "Here is the change:\n"
        "===FILE: a.py===\n"
        "print('hi')\n"
        "===END FILE===\n"
    )

    class _Client:
        async def complete(self, request, **kwargs):
            from probos.types import LLMResponse

            return LLMResponse(
                content=file_block_text,
                tokens_used=5,
                content_blocks=[TextBlock(text=file_block_text)],
            )

    h = _make_harness(llm_client=_Client(), executor=MagicMock())
    spec = BuildSpec(title="t", description="d", target_files=["a.py"])
    result = await h.run_build(spec, work_dir="/tmp")
    assert "file_changes" in result
    assert "metadata" in result
    assert result["builder_source"] == "native_harness"


@pytest.mark.asyncio
async def test_run_build_metadata_populated() -> None:
    from probos.cognitive.builder import BuildSpec

    class _Client:
        async def complete(self, request, **kwargs):
            from probos.types import LLMResponse

            return LLMResponse(
                content="done",
                tokens_used=7,
                content_blocks=[TextBlock(text="done")],
            )

    h = _make_harness(llm_client=_Client())
    spec = BuildSpec(title="t", description="d")
    result = await h.run_build(spec, work_dir="/tmp")
    md = result["metadata"]
    assert md["builder_type"] == "native_harness"
    assert md["iterations"] == 1
    assert md["tools_used"] == []
    assert md["stopped_reason"] == "complete"


@pytest.mark.asyncio
async def test_run_build_invokes_parse_file_blocks() -> None:
    """Verify final_text is fed through BuildPipeline.parse_file_blocks."""
    from probos.cognitive.builder import BuildSpec

    text = (
        "===FILE: new.py===\n"
        "x = 1\n"
        "===END FILE===\n"
    )

    class _Client:
        async def complete(self, request, **kwargs):
            from probos.types import LLMResponse

            return LLMResponse(
                content=text, tokens_used=1, content_blocks=[TextBlock(text=text)]
            )

    h = _make_harness(llm_client=_Client())
    spec = BuildSpec(title="t", description="d")
    result = await h.run_build(spec, work_dir="/tmp")
    assert len(result["file_changes"]) >= 1
    assert any("new.py" in fc.get("path", "") for fc in result["file_changes"])


def test_native_swe_harness_config_default_disabled() -> None:
    from probos.config import SystemConfig

    cfg = SystemConfig()
    assert cfg.native_swe_harness.enabled is False


def test_native_swe_harness_config_enabled_true_when_set() -> None:
    from probos.config import NativeSWEHarnessConfig

    cfg = NativeSWEHarnessConfig(enabled=True)
    assert cfg.enabled is True
    # Defaults preserved when only one field set
    assert cfg.eligibility_modify_only is True


def test_native_harness_config_modify_only_default_true() -> None:
    from probos.config import NativeSWEHarnessConfig

    cfg = NativeSWEHarnessConfig()
    assert cfg.eligibility_modify_only is True
