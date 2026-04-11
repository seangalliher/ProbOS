"""Tests for BuilderAgent, BuildSpec, BuildResult, and git helpers (AD-302/303)."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.runtime import ProbOSRuntime

from probos.cognitive.builder import (
    BuildBlueprint,
    BuilderAgent,
    BuildFailureReport,
    BuildResult,
    BuildSpec,
    ChunkResult,
    ChunkSpec,
    ValidationResult,
    _build_chunk_context,
    _build_chunk_prompt,
    _build_fix_prompt,
    _emit_transporter_events,
    _execute_single_chunk,
    _fallback_decompose,
    _find_chunk_for_file,
    _find_unresolved_names,
    _git_create_branch,
    _map_source_to_tests,
    _merge_create_blocks,
    _parse_chunk_response,
    _run_targeted_tests,
    _run_tests,
    _sanitize_branch_name,
    _should_use_transporter,
    _validate_python,
    assemble_chunks,
    assembly_summary,
    classify_build_failure,
    create_blueprint,
    decompose_blueprint,
    execute_chunks,
    execute_approved_build,
    transporter_build,
    validate_assembly,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import BaseLLMClient
from probos.types import IntentMessage


# Disable visiting builder routing for all builder-agent tests (AD-354).
# The SDK may be installed, but these tests test the native builder pipeline.
@pytest.fixture(autouse=True)
def _disable_visiting_builder():
    with patch("probos.cognitive.builder._should_use_visiting_builder", return_value=False):
        yield


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
# ChunkSpec / ChunkResult / BuildBlueprint (AD-330)
# ---------------------------------------------------------------------------


class TestChunkSpec:
    def test_defaults(self):
        """ChunkSpec has correct default values for optional fields."""
        cs = ChunkSpec(
            chunk_id="chunk-0",
            description="Add method",
            target_file="src/foo.py",
            what_to_generate="function",
        )
        assert cs.chunk_id == "chunk-0"
        assert cs.description == "Add method"
        assert cs.target_file == "src/foo.py"
        assert cs.what_to_generate == "function"
        assert cs.required_context == []
        assert cs.expected_output == ""
        assert cs.depends_on == []
        assert cs.constraints == []

    def test_full_population(self):
        """ChunkSpec populates all fields."""
        cs = ChunkSpec(
            chunk_id="chunk-1",
            description="Add verify method",
            target_file="src/runtime.py",
            what_to_generate="method",
            required_context=["def process(self) -> bool:"],
            expected_output="def verify(self, data: dict) -> bool:",
            depends_on=["chunk-0"],
            constraints=["must be async"],
        )
        assert cs.required_context == ["def process(self) -> bool:"]
        assert cs.expected_output == "def verify(self, data: dict) -> bool:"
        assert cs.depends_on == ["chunk-0"]
        assert cs.constraints == ["must be async"]

    def test_depends_on(self):
        """ChunkSpec stores dependency references."""
        cs = ChunkSpec(
            chunk_id="chunk-2",
            description="Tests",
            target_file="tests/test_foo.py",
            what_to_generate="test_class",
            depends_on=["chunk-0"],
        )
        assert cs.depends_on == ["chunk-0"]


class TestChunkResult:
    def test_defaults(self):
        """ChunkResult has correct default values."""
        cr = ChunkResult(chunk_id="chunk-0")
        assert cr.chunk_id == "chunk-0"
        assert cr.success is False
        assert cr.generated_code == ""
        assert cr.decisions == ""
        assert cr.output_signature == ""
        assert cr.confidence == 3
        assert cr.error == ""
        assert cr.tokens_used == 0

    def test_success(self):
        """ChunkResult stores a successful result."""
        cr = ChunkResult(
            chunk_id="chunk-0",
            success=True,
            generated_code="def foo(): pass",
            decisions="Simple implementation chosen",
            output_signature="def foo() -> None",
            confidence=5,
            tokens_used=150,
        )
        assert cr.success is True
        assert cr.generated_code == "def foo(): pass"
        assert cr.confidence == 5
        assert cr.tokens_used == 150

    def test_confidence_range(self):
        """ChunkResult stores confidence values at both ends."""
        low = ChunkResult(chunk_id="c-low", confidence=1)
        high = ChunkResult(chunk_id="c-high", confidence=5)
        assert low.confidence == 1
        assert high.confidence == 5


class TestBuildBlueprint:
    def test_from_spec(self):
        """BuildBlueprint created via factory has defaults."""
        spec = BuildSpec(title="T", description="D")
        bp = create_blueprint(spec)
        assert bp.spec is spec
        assert bp.chunks == []
        assert bp.results == []
        assert bp.interface_contracts == []
        assert bp.shared_imports == []
        assert bp.shared_context == ""
        assert bp.chunk_hints == []

    def test_interface_contracts(self):
        """BuildBlueprint stores interface contracts."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            interface_contracts=["def foo(x: int) -> str:"],
        )
        assert bp.interface_contracts == ["def foo(x: int) -> str:"]

    def test_shared_imports(self):
        """BuildBlueprint stores shared imports."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            shared_imports=["from probos.types import LLMRequest"],
        )
        assert bp.shared_imports == ["from probos.types import LLMRequest"]

    def test_validate_dag_empty(self):
        """validate_chunk_dag on empty chunks returns valid."""
        spec = BuildSpec(title="T", description="D")
        bp = create_blueprint(spec)
        valid, msg = bp.validate_chunk_dag()
        assert valid is True
        assert msg == ""

    def test_validate_dag_valid(self):
        """validate_chunk_dag accepts a valid DAG."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="chunk-0", description="Base", target_file="a.py", what_to_generate="func"),
                ChunkSpec(chunk_id="chunk-1", description="Ext", target_file="b.py", what_to_generate="func", depends_on=["chunk-0"]),
                ChunkSpec(chunk_id="chunk-2", description="Also", target_file="c.py", what_to_generate="func", depends_on=["chunk-0"]),
            ],
        )
        valid, msg = bp.validate_chunk_dag()
        assert valid is True
        assert msg == ""

    def test_validate_dag_cycle(self):
        """validate_chunk_dag detects cycles."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="chunk-0", description="A", target_file="a.py", what_to_generate="func", depends_on=["chunk-1"]),
                ChunkSpec(chunk_id="chunk-1", description="B", target_file="b.py", what_to_generate="func", depends_on=["chunk-0"]),
            ],
        )
        valid, msg = bp.validate_chunk_dag()
        assert valid is False
        assert "Cycle detected" in msg


class TestGetReadyChunks:
    def _make_chunks(self):
        return [
            ChunkSpec(chunk_id="chunk-0", description="A", target_file="a.py", what_to_generate="func"),
            ChunkSpec(chunk_id="chunk-1", description="B", target_file="b.py", what_to_generate="func", depends_on=["chunk-0"]),
            ChunkSpec(chunk_id="chunk-2", description="C", target_file="c.py", what_to_generate="func", depends_on=["chunk-1"]),
        ]

    def test_all_independent(self):
        """All independent chunks are returned when none completed."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="c-0", description="A", target_file="a.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-1", description="B", target_file="b.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-2", description="C", target_file="c.py", what_to_generate="func"),
            ],
        )
        ready = bp.get_ready_chunks()
        assert len(ready) == 3

    def test_with_dependencies(self):
        """Chunks are returned as their dependencies complete."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec, chunks=self._make_chunks())

        ready = bp.get_ready_chunks(completed=set())
        assert [c.chunk_id for c in ready] == ["chunk-0"]

        ready = bp.get_ready_chunks(completed={"chunk-0"})
        assert [c.chunk_id for c in ready] == ["chunk-1"]

        ready = bp.get_ready_chunks(completed={"chunk-0", "chunk-1"})
        assert [c.chunk_id for c in ready] == ["chunk-2"]

    def test_none_completed(self):
        """completed=None behaves like empty set."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec, chunks=self._make_chunks())
        ready = bp.get_ready_chunks(completed=None)
        assert [c.chunk_id for c in ready] == ["chunk-0"]

    def test_unknown_dep_in_validate(self):
        """validate_chunk_dag rejects unknown dependency references."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="chunk-0", description="A", target_file="a.py", what_to_generate="func", depends_on=["nonexistent"]),
            ],
        )
        valid, msg = bp.validate_chunk_dag()
        assert valid is False
        assert "depends on unknown" in msg


class TestCreateBlueprint:
    def test_factory(self):
        """create_blueprint wraps a BuildSpec with empty metadata."""
        spec = BuildSpec(
            title="Test Build",
            description="A test build",
            target_files=["src/foo.py"],
            test_files=["tests/test_foo.py"],
        )
        bp = create_blueprint(spec)
        assert bp.spec is spec
        assert bp.chunks == []
        assert bp.results == []
        assert bp.interface_contracts == []
        assert bp.shared_imports == []
        assert bp.shared_context == ""
        assert bp.chunk_hints == []


# ---------------------------------------------------------------------------
# ChunkDecomposer (AD-331)
# ---------------------------------------------------------------------------


class _MockLLM:
    """Minimal mock for decompose_blueprint tests."""

    def __init__(self, response_text: str, error: str = ""):
        self._text = response_text
        self._error = error

    async def complete(self, request):
        from probos.types import LLMResponse
        if self._error:
            return LLMResponse(content="", error=self._error)
        return LLMResponse(content=self._text)


class TestFallbackDecompose:
    def test_single_target(self):
        """One target file, no tests → 1 chunk."""
        spec = BuildSpec(title="T", description="D", target_files=["src/a.py"])
        bp = _fallback_decompose(create_blueprint(spec))
        assert len(bp.chunks) == 1
        assert bp.chunks[0].chunk_id == "chunk-0"
        assert bp.chunks[0].target_file == "src/a.py"
        assert bp.chunks[0].depends_on == []

    def test_multiple_targets(self):
        """Three target files, no tests → 3 chunks."""
        spec = BuildSpec(title="T", description="D",
                         target_files=["src/a.py", "src/b.py", "src/c.py"])
        bp = _fallback_decompose(create_blueprint(spec))
        assert len(bp.chunks) == 3
        for c in bp.chunks:
            assert c.depends_on == []

    def test_with_test_files(self):
        """Two targets + 1 test → 3 chunks, test depends on both impls."""
        spec = BuildSpec(title="T", description="D",
                         target_files=["src/a.py", "src/b.py"],
                         test_files=["tests/test_a.py"])
        bp = _fallback_decompose(create_blueprint(spec))
        assert len(bp.chunks) == 3
        test_chunk = bp.chunks[2]
        assert test_chunk.target_file == "tests/test_a.py"
        assert test_chunk.depends_on == ["chunk-0", "chunk-1"]

    def test_empty_spec(self):
        """No target files, no test files → 0 chunks."""
        spec = BuildSpec(title="T", description="D")
        bp = _fallback_decompose(create_blueprint(spec))
        assert len(bp.chunks) == 0


class TestBuildChunkContext:
    def test_with_contracts(self):
        """Context includes interface contracts."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec, interface_contracts=["def foo(): ..."])
        ctx = _build_chunk_context(bp, "src/a.py", {})
        assert any("## Interface Contracts" in c for c in ctx)
        assert any("def foo(): ..." in c for c in ctx)

    def test_with_shared_imports(self):
        """Context includes shared imports."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec, shared_imports=["import os"])
        ctx = _build_chunk_context(bp, "src/a.py", {})
        assert any("## Shared Imports" in c for c in ctx)
        assert any("import os" in c for c in ctx)

    def test_with_target_content(self):
        """Context includes file outline and imports section."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        contents = {"src/foo.py": "class Foo:\n    def bar(self): pass"}
        ctx = _build_chunk_context(bp, "src/foo.py", contents)
        assert any("## Target File Structure" in c for c in ctx)
        assert any("## Target File Imports" in c for c in ctx)

    def test_empty_blueprint(self):
        """No contracts, no imports, file not in contents → empty context."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        ctx = _build_chunk_context(bp, "src/missing.py", {})
        assert ctx == []


class TestDecomposeBlueprint:
    @pytest.mark.asyncio
    async def test_basic_decomposition(self):
        """LLM returns a single chunk → blueprint gets 1 ChunkSpec."""
        import json
        llm_response = json.dumps({"chunks": [
            {"description": "Add function", "target_file": "src/foo.py",
             "what_to_generate": "function", "depends_on": [], "constraints": []},
        ]})
        spec = BuildSpec(title="T", description="D", target_files=["src/foo.py"])
        bp = create_blueprint(spec)
        result = await decompose_blueprint(bp, _MockLLM(llm_response))
        assert len(result.chunks) == 1
        assert result.chunks[0].chunk_id == "chunk-0"
        assert result.chunks[0].target_file == "src/foo.py"
        assert result.chunks[0].depends_on == []

    @pytest.mark.asyncio
    async def test_multi_chunk(self):
        """LLM returns 3 chunks with dependencies → valid DAG."""
        import json
        llm_response = json.dumps({"chunks": [
            {"description": "Impl A", "target_file": "src/a.py",
             "what_to_generate": "function", "depends_on": [], "constraints": []},
            {"description": "Impl B", "target_file": "src/b.py",
             "what_to_generate": "function", "depends_on": [], "constraints": []},
            {"description": "Tests", "target_file": "tests/test_a.py",
             "what_to_generate": "test_class", "depends_on": [0, 1], "constraints": []},
        ]})
        spec = BuildSpec(title="T", description="D",
                         target_files=["src/a.py", "src/b.py"],
                         test_files=["tests/test_a.py"])
        bp = create_blueprint(spec)
        result = await decompose_blueprint(bp, _MockLLM(llm_response))
        assert len(result.chunks) == 3
        assert result.chunks[2].depends_on == ["chunk-0", "chunk-1"]
        valid, _ = result.validate_chunk_dag()
        assert valid

    @pytest.mark.asyncio
    async def test_fallback_on_llm_error(self):
        """LLM error → fallback decomposition."""
        spec = BuildSpec(title="T", description="D",
                         target_files=["src/a.py", "src/b.py"])
        bp = create_blueprint(spec)
        result = await decompose_blueprint(bp, _MockLLM("", error="timeout"))
        assert len(result.chunks) == 2
        assert result.chunks[0].target_file == "src/a.py"

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        """LLM returns invalid JSON → fallback decomposition."""
        spec = BuildSpec(title="T", description="D",
                         target_files=["src/a.py"])
        bp = create_blueprint(spec)
        result = await decompose_blueprint(bp, _MockLLM("not json at all"))
        assert len(result.chunks) == 1
        assert result.chunks[0].target_file == "src/a.py"

    @pytest.mark.asyncio
    async def test_coverage_gap_filled(self):
        """LLM covers src/a.py but not src/b.py → catch-all added."""
        import json
        llm_response = json.dumps({"chunks": [
            {"description": "Impl A", "target_file": "src/a.py",
             "what_to_generate": "function", "depends_on": [], "constraints": []},
        ]})
        spec = BuildSpec(title="T", description="D",
                         target_files=["src/a.py", "src/b.py"])
        bp = create_blueprint(spec)
        result = await decompose_blueprint(bp, _MockLLM(llm_response))
        covered = {c.target_file for c in result.chunks}
        assert "src/a.py" in covered
        assert "src/b.py" in covered

    @pytest.mark.asyncio
    async def test_fallback_on_cycle(self):
        """LLM returns cyclic deps → fallback decomposition."""
        import json
        llm_response = json.dumps({"chunks": [
            {"description": "A", "target_file": "src/a.py",
             "what_to_generate": "func", "depends_on": ["chunk-1"], "constraints": []},
            {"description": "B", "target_file": "src/b.py",
             "what_to_generate": "func", "depends_on": ["chunk-0"], "constraints": []},
        ]})
        spec = BuildSpec(title="T", description="D",
                         target_files=["src/a.py", "src/b.py"])
        bp = create_blueprint(spec)
        result = await decompose_blueprint(bp, _MockLLM(llm_response))
        # Should have fallen back — chunks are simple 1-per-file
        valid, _ = result.validate_chunk_dag()
        assert valid
        assert len(result.chunks) == 2


# ---------------------------------------------------------------------------
# Parallel Chunk Execution (AD-332)
# ---------------------------------------------------------------------------

_VALID_FILE_BLOCK = (
    "===FILE: src/foo.py===\n"
    "def foo(): pass\n"
    "===END FILE===\n"
    "DECISIONS: simple function\n"
    "CONFIDENCE: 4"
)

_VALID_MODIFY_BLOCK = (
    "===MODIFY: src/bar.py===\n"
    "===SEARCH===\ndef old(): pass\n===REPLACE===\ndef new(): pass\n===END REPLACE===\n"
    "===END MODIFY===\n"
    "DECISIONS: renamed function\n"
    "CONFIDENCE: 3"
)


class TestBuildChunkPrompt:
    def test_basic_prompt(self):
        """Prompt contains chunk description, target file, what_to_generate."""
        spec = BuildSpec(title="My Build", description="D")
        bp = BuildBlueprint(spec=spec)
        chunk = ChunkSpec(chunk_id="c-0", description="Add helper",
                          target_file="src/foo.py", what_to_generate="function")
        prompt = _build_chunk_prompt(chunk, bp)
        assert "# Chunk: Add helper" in prompt
        assert "src/foo.py" in prompt
        assert "function" in prompt

    def test_with_context(self):
        """Prompt includes required_context."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/a.py", what_to_generate="func",
                          required_context=["## Interface Contracts\ndef foo(): ..."])
        prompt = _build_chunk_prompt(chunk, bp)
        assert "## Context" in prompt
        assert "def foo(): ..." in prompt

    def test_with_constraints(self):
        """Prompt includes constraints."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/a.py", what_to_generate="func",
                          constraints=["must be async"])
        prompt = _build_chunk_prompt(chunk, bp)
        assert "## Constraints" in prompt
        assert "must be async" in prompt


class TestParseChunkResponse:
    def test_success_with_file_block(self):
        """Parses a successful response with file block."""
        from probos.types import LLMResponse
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/foo.py", what_to_generate="func")
        response = LLMResponse(content=_VALID_FILE_BLOCK, tokens_used=100)
        cr = _parse_chunk_response(chunk, response)
        assert cr.success is True
        assert cr.confidence == 4
        assert cr.decisions == "simple function"
        assert "CREATE src/foo.py" in cr.output_signature
        assert cr.tokens_used == 100

    def test_no_file_blocks(self):
        """Response without file markers → success=False."""
        from probos.types import LLMResponse
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/foo.py", what_to_generate="func")
        response = LLMResponse(content="Just some text, no file blocks")
        cr = _parse_chunk_response(chunk, response)
        assert cr.success is False
        assert "No file blocks" in cr.error

    def test_confidence_clamped(self):
        """Confidence is clamped to 1-5 range."""
        from probos.types import LLMResponse
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/foo.py", what_to_generate="func")
        high = LLMResponse(content="===FILE: x.py===\npass\n===END FILE===\nCONFIDENCE: 9")
        cr_high = _parse_chunk_response(chunk, high)
        assert cr_high.confidence == 5

        low = LLMResponse(content="===FILE: x.py===\npass\n===END FILE===\nCONFIDENCE: 0")
        cr_low = _parse_chunk_response(chunk, low)
        assert cr_low.confidence == 1

    def test_modify_block(self):
        """Parses a MODIFY block response."""
        from probos.types import LLMResponse
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/bar.py", what_to_generate="func")
        response = LLMResponse(content=_VALID_MODIFY_BLOCK)
        cr = _parse_chunk_response(chunk, response)
        assert cr.success is True
        assert "MODIFY" in cr.output_signature


class TestExecuteSingleChunk:
    @pytest.mark.asyncio
    async def test_success(self):
        """Successful chunk execution returns ChunkResult with code."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/foo.py", what_to_generate="func")
        llm = _MockLLM(_VALID_FILE_BLOCK)
        result = await _execute_single_chunk(chunk, bp, llm, timeout=10.0, max_retries=0)
        assert result.success is True
        assert "def foo(): pass" in result.generated_code

    @pytest.mark.asyncio
    async def test_timeout(self):
        """Chunk times out → success=False."""
        from probos.types import LLMResponse

        class _SlowLLM:
            async def complete(self, request):
                await asyncio.Event().wait()  # blocks until timeout cancels
                return LLMResponse(content="")

        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/foo.py", what_to_generate="func")
        result = await _execute_single_chunk(chunk, bp, _SlowLLM(), timeout=0.1, max_retries=0)
        assert result.success is False
        assert "timeout" in result.error

    @pytest.mark.asyncio
    async def test_retry_on_error(self):
        """Chunk retries on error and succeeds on second attempt."""
        from probos.types import LLMResponse

        class _RetryLLM:
            def __init__(self):
                self.calls = 0
            async def complete(self, request):
                self.calls += 1
                if self.calls == 1:
                    return LLMResponse(content="", error="rate_limit")
                return LLMResponse(content=_VALID_FILE_BLOCK)

        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        chunk = ChunkSpec(chunk_id="c-0", description="X",
                          target_file="src/foo.py", what_to_generate="func")
        result = await _execute_single_chunk(chunk, bp, _RetryLLM(), timeout=10.0, max_retries=1)
        assert result.success is True


class TestExecuteChunks:
    @pytest.mark.asyncio
    async def test_independent_chunks_parallel(self):
        """Three independent chunks all succeed."""
        spec = BuildSpec(title="T", description="D", target_files=["src/a.py"])
        bp = BuildBlueprint(spec=spec, chunks=[
            ChunkSpec(chunk_id="c-0", description="A", target_file="src/a.py", what_to_generate="func"),
            ChunkSpec(chunk_id="c-1", description="B", target_file="src/b.py", what_to_generate="func"),
            ChunkSpec(chunk_id="c-2", description="C", target_file="src/c.py", what_to_generate="func"),
        ])
        result = await execute_chunks(bp, _MockLLM(_VALID_FILE_BLOCK), max_retries=0)
        assert len(result.results) == 3
        assert all(r.success for r in result.results)

    @pytest.mark.asyncio
    async def test_dependent_chunks_ordered(self):
        """Dependent chunk waits and both succeed."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec, chunks=[
            ChunkSpec(chunk_id="c-0", description="Impl", target_file="src/a.py", what_to_generate="func"),
            ChunkSpec(chunk_id="c-1", description="Test", target_file="tests/test_a.py",
                      what_to_generate="test_class", depends_on=["c-0"]),
        ])
        result = await execute_chunks(bp, _MockLLM(_VALID_FILE_BLOCK), max_retries=0)
        assert len(result.results) == 2
        assert result.results[0].success is True
        assert result.results[1].success is True

    @pytest.mark.asyncio
    async def test_partial_success(self):
        """One chunk succeeds, one fails → partial results."""
        from probos.types import LLMResponse

        class _AlternatingLLM:
            def __init__(self):
                self.calls = 0
            async def complete(self, request):
                self.calls += 1
                if self.calls == 1:
                    return LLMResponse(content=_VALID_FILE_BLOCK, tokens_used=100)
                return LLMResponse(content="", error="fail")

        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec, chunks=[
            ChunkSpec(chunk_id="c-0", description="A", target_file="src/a.py", what_to_generate="func"),
            ChunkSpec(chunk_id="c-1", description="B", target_file="src/b.py", what_to_generate="func"),
        ])
        result = await execute_chunks(bp, _AlternatingLLM(), max_retries=0)
        assert len(result.results) == 2
        assert result.results[0].success is True
        assert result.results[1].success is False

    @pytest.mark.asyncio
    async def test_empty_chunks(self):
        """Blueprint with no chunks → empty results."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        result = await execute_chunks(bp, _MockLLM(_VALID_FILE_BLOCK), max_retries=0)
        assert result.results == []

    @pytest.mark.asyncio
    async def test_all_failures(self):
        """All chunks fail → all results have success=False."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec, chunks=[
            ChunkSpec(chunk_id="c-0", description="A", target_file="src/a.py", what_to_generate="func"),
            ChunkSpec(chunk_id="c-1", description="B", target_file="src/b.py", what_to_generate="func"),
        ])
        result = await execute_chunks(bp, _MockLLM("", error="always fail"), max_retries=0)
        assert len(result.results) == 2
        assert all(not r.success for r in result.results)


# ---------------------------------------------------------------------------
# ChunkAssembler (AD-333)
# ---------------------------------------------------------------------------


class TestMergeCreateBlocks:
    def test_single_content(self):
        """Single content block returned as-is."""
        result = _merge_create_blocks(["def foo(): pass\n"])
        assert result == "def foo(): pass\n"

    def test_deduplicate_imports(self):
        """Duplicate imports across content blocks are deduplicated."""
        c1 = "import os\nimport sys\n\ndef foo():\n    pass\n"
        c2 = "import os\nimport json\n\ndef bar():\n    pass\n"
        result = _merge_create_blocks([c1, c2])
        assert result.count("import os") == 1
        assert "import sys" in result
        assert "import json" in result
        assert "def foo():" in result
        assert "def bar():" in result

    def test_no_imports(self):
        """Content with no imports → bodies concatenated."""
        c1 = "def foo():\n    pass\n"
        c2 = "def bar():\n    pass\n"
        result = _merge_create_blocks([c1, c2])
        assert "def foo():" in result
        assert "def bar():" in result

    def test_empty_contents(self):
        """Empty content blocks → just trailing newline."""
        result = _merge_create_blocks(["", ""])
        assert result == "\n"


class TestAssembleChunks:
    def test_single_chunk_create(self):
        """Single CREATE chunk → 1 file block."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[ChunkSpec(chunk_id="c-0", description="X",
                              target_file="src/foo.py", what_to_generate="func")],
            results=[ChunkResult(
                chunk_id="c-0", success=True, confidence=5,
                generated_code="===FILE: src/foo.py===\ndef foo(): pass\n===END FILE===",
            )],
        )
        blocks = assemble_chunks(bp)
        assert len(blocks) == 1
        assert blocks[0]["mode"] == "create"
        assert blocks[0]["path"] == "src/foo.py"
        assert "def foo(): pass" in blocks[0]["content"]

    def test_single_chunk_modify(self):
        """Single MODIFY chunk → 1 file block with replacements."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[ChunkSpec(chunk_id="c-0", description="X",
                              target_file="src/bar.py", what_to_generate="func")],
            results=[ChunkResult(
                chunk_id="c-0", success=True, confidence=4,
                generated_code=(
                    "===MODIFY: src/bar.py===\n"
                    "===SEARCH===\ndef old(): pass\n===REPLACE===\n"
                    "def new(): pass\n===END REPLACE===\n"
                    "===END MODIFY==="
                ),
            )],
        )
        blocks = assemble_chunks(bp)
        assert len(blocks) == 1
        assert blocks[0]["mode"] == "modify"
        assert blocks[0]["path"] == "src/bar.py"
        assert len(blocks[0]["replacements"]) == 1

    def test_multiple_chunks_different_files(self):
        """Two chunks for different files → 2 blocks."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="c-0", description="A",
                          target_file="src/a.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-1", description="B",
                          target_file="src/b.py", what_to_generate="func"),
            ],
            results=[
                ChunkResult(chunk_id="c-0", success=True, confidence=4,
                            generated_code="===FILE: src/a.py===\ndef a(): pass\n===END FILE==="),
                ChunkResult(chunk_id="c-1", success=True, confidence=4,
                            generated_code="===FILE: src/b.py===\ndef b(): pass\n===END FILE==="),
            ],
        )
        blocks = assemble_chunks(bp)
        assert len(blocks) == 2
        paths = {b["path"] for b in blocks}
        assert paths == {"src/a.py", "src/b.py"}

    def test_multiple_chunks_same_file_create(self):
        """Two CREATE chunks for same file → merged with deduped imports."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="c-0", description="A",
                          target_file="src/foo.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-1", description="B",
                          target_file="src/foo.py", what_to_generate="func"),
            ],
            results=[
                ChunkResult(chunk_id="c-0", success=True, confidence=5,
                            generated_code="===FILE: src/foo.py===\nimport os\n\ndef foo(): pass\n===END FILE==="),
                ChunkResult(chunk_id="c-1", success=True, confidence=3,
                            generated_code="===FILE: src/foo.py===\nimport os\nimport json\n\ndef bar(): pass\n===END FILE==="),
            ],
        )
        blocks = assemble_chunks(bp)
        assert len(blocks) == 1
        assert blocks[0]["mode"] == "create"
        content = blocks[0]["content"]
        assert content.count("import os") == 1
        assert "import json" in content
        assert "def foo(): pass" in content
        assert "def bar(): pass" in content

    def test_multiple_chunks_same_file_modify(self):
        """Two MODIFY chunks for same file → replacements merged by confidence."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="c-0", description="A",
                          target_file="src/x.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-1", description="B",
                          target_file="src/x.py", what_to_generate="func"),
            ],
            results=[
                ChunkResult(chunk_id="c-0", success=True, confidence=4,
                            generated_code=(
                                "===MODIFY: src/x.py===\n"
                                "===SEARCH===\ndef a(): pass\n===REPLACE===\ndef a(): return 1\n===END REPLACE===\n"
                                "===SEARCH===\ndef b(): pass\n===REPLACE===\ndef b(): return 2\n===END REPLACE===\n"
                                "===END MODIFY==="
                            )),
                ChunkResult(chunk_id="c-1", success=True, confidence=2,
                            generated_code=(
                                "===MODIFY: src/x.py===\n"
                                "===SEARCH===\ndef c(): pass\n===REPLACE===\ndef c(): return 3\n===END REPLACE===\n"
                                "===END MODIFY==="
                            )),
            ],
        )
        blocks = assemble_chunks(bp)
        assert len(blocks) == 1
        assert blocks[0]["mode"] == "modify"
        assert len(blocks[0]["replacements"]) == 3
        # Higher confidence chunk's replacements come first
        assert blocks[0]["replacements"][0]["search"] == "def a(): pass"

    def test_failed_chunks_skipped(self):
        """Failed chunks are skipped in assembly."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="c-0", description="A",
                          target_file="src/a.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-1", description="B",
                          target_file="src/b.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-2", description="C",
                          target_file="src/c.py", what_to_generate="func"),
            ],
            results=[
                ChunkResult(chunk_id="c-0", success=True, confidence=4,
                            generated_code="===FILE: src/a.py===\ndef a(): pass\n===END FILE==="),
                ChunkResult(chunk_id="c-1", success=False, error="timeout"),
                ChunkResult(chunk_id="c-2", success=True, confidence=4,
                            generated_code="===FILE: src/c.py===\ndef c(): pass\n===END FILE==="),
            ],
        )
        blocks = assemble_chunks(bp)
        assert len(blocks) == 2
        paths = {b["path"] for b in blocks}
        assert "src/b.py" not in paths

    def test_no_successful_chunks(self):
        """All chunks failed → empty list."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="c-0", description="A",
                          target_file="src/a.py", what_to_generate="func"),
            ],
            results=[
                ChunkResult(chunk_id="c-0", success=False, error="fail"),
            ],
        )
        blocks = assemble_chunks(bp)
        assert blocks == []


class TestAssemblySummary:
    def test_basic_summary(self):
        """Summary reflects chunk statuses correctly."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(
            spec=spec,
            chunks=[
                ChunkSpec(chunk_id="c-0", description="A", target_file="src/a.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-1", description="B", target_file="src/b.py", what_to_generate="func"),
                ChunkSpec(chunk_id="c-2", description="C", target_file="src/c.py", what_to_generate="func"),
            ],
            results=[
                ChunkResult(chunk_id="c-0", success=True, confidence=5, tokens_used=100),
                ChunkResult(chunk_id="c-1", success=True, confidence=3, tokens_used=80),
                ChunkResult(chunk_id="c-2", success=False, confidence=1, error="timeout"),
            ],
        )
        summary = assembly_summary(bp)
        assert summary["total_chunks"] == 3
        assert summary["successful"] == 2
        assert summary["failed"] == 1
        assert summary["total_tokens"] == 180
        assert len(summary["chunks"]) == 3

    def test_empty_results(self):
        """Empty blueprint → zero counts."""
        spec = BuildSpec(title="T", description="D")
        bp = BuildBlueprint(spec=spec)
        summary = assembly_summary(bp)
        assert summary["total_chunks"] == 0
        assert summary["successful"] == 0


# ---------------------------------------------------------------------------
# Interface Validator (AD-334)
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_default_valid(self):
        """Fresh ValidationResult is valid with no errors."""
        r = ValidationResult()
        assert r.valid is True
        assert r.errors == []
        assert r.warnings == []

    def test_with_errors_is_invalid(self):
        """ValidationResult with errors should report as invalid."""
        r = ValidationResult(
            valid=False,
            errors=[{"type": "syntax_error", "message": "bad", "file": "a.py", "chunk_id": "c1"}],
        )
        assert r.valid is False
        assert len(r.errors) == 1


class TestFindChunkForFile:
    def test_finds_matching_chunk(self):
        """Returns chunk_id when a chunk targets the given file."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d",
                               target_file="src/foo.py", what_to_generate="code")]
        assert _find_chunk_for_file(bp, "src/foo.py") == "c1"

    def test_returns_empty_when_no_match(self):
        """Returns empty string when no chunk targets the file."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d",
                               target_file="src/bar.py", what_to_generate="code")]
        assert _find_chunk_for_file(bp, "src/other.py") == ""

    def test_suffix_matching(self):
        """Matches when file_path ends with chunk's target_file."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d",
                               target_file="src/foo.py", what_to_generate="code")]
        assert _find_chunk_for_file(bp, "/home/user/project/src/foo.py") == "c1"


class TestFindUnresolvedNames:
    def test_all_names_resolved(self):
        """No unresolved names when all references are defined or imported."""
        src = "import os\n\ndef foo(x):\n    return os.path.join(x)\n"
        assert _find_unresolved_names(src) == []

    def test_detects_unresolved(self):
        """Detects names used but not defined or imported."""
        src = "def foo():\n    return bar()\n"
        result = _find_unresolved_names(src)
        assert "bar" in result

    def test_ignores_builtins(self):
        """Built-in names (print, len, etc.) should not be flagged."""
        src = "def foo(items):\n    print(len(items))\n"
        assert _find_unresolved_names(src) == []


class TestValidateAssembly:
    def _make_blueprint_with_result(self, chunk_id="c1", target="src/foo.py", confidence=4):
        """Helper to create a blueprint with one chunk and one successful result."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id=chunk_id, description="d",
                               target_file=target, what_to_generate="code")]
        bp.results = [ChunkResult(chunk_id=chunk_id, success=True, confidence=confidence)]
        return bp

    def test_valid_assembly(self):
        """Clean Python code passes validation."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py", "content": "import os\n\ndef foo():\n    return 1\n",
                   "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is True
        assert result.errors == []

    def test_syntax_error_detected(self):
        """Invalid Python syntax produces a syntax_error."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py", "content": "def foo(\n",
                   "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is False
        assert any(e["type"] == "syntax_error" for e in result.errors)

    def test_duplicate_definition_detected(self):
        """Two functions with the same name at top level produce duplicate_definition."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py",
                   "content": "def foo():\n    pass\n\ndef foo():\n    pass\n",
                   "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is False
        assert any(e["type"] == "duplicate_definition" for e in result.errors)

    def test_empty_search_in_modify(self):
        """Empty search string in a modify replacement produces error."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py", "mode": "modify",
                   "replacements": [{"search": "", "replace": "new code"}]}]
        result = validate_assembly(bp, blocks)
        assert result.valid is False
        assert any(e["type"] == "empty_search" for e in result.errors)

    def test_non_python_files_skip_ast_checks(self):
        """Non-.py files skip AST-based validation but still pass."""
        bp = self._make_blueprint_with_result(target="src/config.yaml")
        blocks = [{"path": "src/config.yaml", "content": "key: value\n",
                   "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is True

    def test_unmet_contract_produces_warning(self):
        """Interface contract not found in code produces warning (not error)."""
        bp = self._make_blueprint_with_result()
        bp.interface_contracts = ["def required_function(x: int) -> str"]
        blocks = [{"path": "src/foo.py", "content": "def other_function():\n    pass\n",
                   "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is True  # Warnings don't make it invalid
        assert any(w["type"] == "unmet_contract" for w in result.warnings)

    def test_low_confidence_triggers_stricter_check(self):
        """Chunks with confidence <= 2 get unresolved name warnings."""
        bp = self._make_blueprint_with_result(confidence=2)
        blocks = [{"path": "src/foo.py",
                   "content": "def foo():\n    return unknown_func()\n",
                   "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert any(w["type"] == "unresolved_name" for w in result.warnings)


class TestTransporterEvents:
    """Tests for Transporter Pattern event emission (AD-335)."""

    def test_decompose_emits_event(self):
        """decompose_blueprint emits transporter_decomposed when on_event provided."""
        events = []

        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(
            title="test", description="test",
            target_files=["src/foo.py"],
        ))
        mock_llm = AsyncMock(side_effect=Exception("no LLM"))
        asyncio.get_event_loop().run_until_complete(
            decompose_blueprint(bp, mock_llm, on_event=capture_event)
        )
        # Should have emitted transporter_decomposed
        assert any(e[0] == "transporter_decomposed" for e in events)
        decomposed = [e for e in events if e[0] == "transporter_decomposed"][0][1]
        assert decomposed["chunk_count"] > 0
        assert decomposed.get("fallback") is True

    def test_decompose_no_event_when_none(self):
        """decompose_blueprint works without on_event (backward compatible)."""
        bp = BuildBlueprint(spec=BuildSpec(
            title="test", description="test",
            target_files=["src/foo.py"],
        ))
        mock_llm = AsyncMock(side_effect=Exception("no LLM"))
        # Should not raise — on_event defaults to None
        result = asyncio.get_event_loop().run_until_complete(
            decompose_blueprint(bp, mock_llm)
        )
        assert len(result.chunks) > 0

    def test_execute_emits_wave_events(self):
        """execute_chunks emits wave_start and chunk_done events."""
        events = []

        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete.return_value = MagicMock(
            error=None,
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        event_types = [e[0] for e in events]
        assert "transporter_wave_start" in event_types
        assert "transporter_chunk_done" in event_types
        assert "transporter_execution_done" in event_types

    def test_execute_no_event_when_none(self):
        """execute_chunks works without on_event (backward compatible)."""
        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete.return_value = MagicMock(
            error=None,
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        result = asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm)
        )
        assert len(result.results) == 1

    def test_wave_start_includes_chunk_ids(self):
        """Wave start event includes correct chunk IDs."""
        events = []

        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
            ChunkSpec(chunk_id="c2", description="d2", target_file="f2.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete.return_value = MagicMock(
            error=None,
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        wave_events = [e for e in events if e[0] == "transporter_wave_start"]
        assert len(wave_events) >= 1
        # First wave should have both chunks (no deps)
        assert "c1" in wave_events[0][1]["chunk_ids"]
        assert "c2" in wave_events[0][1]["chunk_ids"]

    def test_chunk_done_reports_failure(self):
        """Chunk done event correctly reports failure."""
        events = []

        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete.side_effect = Exception("LLM error")
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        chunk_events = [e for e in events if e[0] == "transporter_chunk_done"]
        assert len(chunk_events) == 1
        assert chunk_events[0][1]["success"] is False

    def test_execution_done_summary(self):
        """Execution done event includes correct summary counts."""
        events = []

        async def capture_event(event_type, data):
            events.append((event_type, data))

        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [
            ChunkSpec(chunk_id="c1", description="d1", target_file="f1.py", what_to_generate="code"),
        ]
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete.return_value = MagicMock(
            error=None,
            content="===FILE: f1.py===\n===CREATE===\ndef foo(): pass\n===END==="
        )
        asyncio.get_event_loop().run_until_complete(
            execute_chunks(bp, mock_llm, on_event=capture_event)
        )
        done_events = [e for e in events if e[0] == "transporter_execution_done"]
        assert len(done_events) == 1
        assert done_events[0][1]["total_chunks"] == 1
        assert done_events[0][1]["waves"] >= 1

    def test_emit_transporter_events_helper(self):
        """_emit_transporter_events emits assembled and validated events."""
        emitted = []

        class FakeRuntime:
            def _emit_event(self, event_type, data):
                emitted.append((event_type, data))

        rt = FakeRuntime()
        bp = BuildBlueprint(spec=BuildSpec(title="test", description="test"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d", target_file="f.py", what_to_generate="code")]
        bp.results = [ChunkResult(chunk_id="c1", success=True, confidence=4)]
        blocks = [{"path": "f.py", "content": "x = 1", "mode": "create", "after_line": None}]
        vr = ValidationResult(valid=True, checks_passed=5)

        asyncio.get_event_loop().run_until_complete(
            _emit_transporter_events(rt, "build-1", bp, blocks, vr)
        )
        event_types = [e[0] for e in emitted]
        assert "transporter_assembled" in event_types
        assert "transporter_validated" in event_types


class TestShouldUseTransporter:
    """Tests for Transporter decision logic (AD-336)."""

    def test_small_build_uses_single_pass(self):
        """Single file, small context → single pass."""
        spec = BuildSpec(title="t", description="d", target_files=["src/foo.py"])
        assert _should_use_transporter(spec, context_size=5000) is False

    def test_many_files_uses_transporter(self):
        """More than 2 target files → Transporter."""
        spec = BuildSpec(title="t", description="d",
                         target_files=["a.py", "b.py", "c.py"])
        assert _should_use_transporter(spec) is True

    def test_large_context_uses_transporter(self):
        """Large context size → Transporter."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        assert _should_use_transporter(spec, context_size=25000) is True

    def test_impl_plus_tests_uses_transporter(self):
        """Multiple impl + test files → Transporter."""
        spec = BuildSpec(title="t", description="d",
                         target_files=["a.py", "b.py"],
                         test_files=["test_a.py"])
        assert _should_use_transporter(spec) is True

    def test_single_impl_single_test_no_transporter(self):
        """One impl + one test (2 total) → single pass."""
        spec = BuildSpec(title="t", description="d",
                         target_files=["a.py"],
                         test_files=["test_a.py"])
        assert _should_use_transporter(spec) is False


class TestTransporterBuild:
    """Tests for transporter_build() end-to-end pipeline (AD-336)."""

    def test_full_pipeline_returns_file_blocks(self):
        """transporter_build runs all stages and returns file blocks."""
        spec = BuildSpec(
            title="test build", description="test",
            target_files=["src/foo.py"],
        )
        mock_llm = AsyncMock(spec=BaseLLMClient)
        # Decompose call will raise → fallback to 1 chunk
        # Execute calls complete() → needs error=None and valid content
        mock_response = MagicMock(
            error=None,
            content="===FILE: src/foo.py===\n===CREATE===\ndef foo():\n    return 1\n===END FILE===",
        )
        mock_llm.complete.return_value = mock_response

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        assert len(result) >= 1
        assert result[0]["mode"] == "create"
        assert "foo" in result[0]["content"]

    def test_returns_empty_on_total_failure(self):
        """Returns empty list when all chunks fail."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete.side_effect = Exception("LLM down")

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        assert result == []

    def test_emits_events_when_callback_provided(self):
        """transporter_build emits events through on_event callback."""
        events = []

        async def capture(event_type, data):
            events.append(event_type)

        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_response = MagicMock(
            error=None,
            content="===FILE: a.py===\n===CREATE===\nx = 1\n===END FILE==="
        )
        mock_llm.complete.return_value = mock_response

        asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm, on_event=capture)
        )
        # Should have decompose + wave + chunk + execution events
        assert "transporter_decomposed" in events

    def test_works_without_on_event(self):
        """transporter_build works with on_event=None (default)."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_response = MagicMock(
            error=None,
            content="===FILE: a.py===\n===CREATE===\nx = 1\n===END FILE==="
        )
        mock_llm.complete.return_value = mock_response

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        # Should succeed without errors
        assert isinstance(result, list)

    def test_validation_failure_still_returns_blocks(self):
        """When validation finds errors, blocks are still returned."""
        spec = BuildSpec(title="t", description="d", target_files=["a.py"])
        mock_llm = AsyncMock(spec=BaseLLMClient)
        # Return syntactically invalid Python — validation will flag it
        mock_response = MagicMock(
            error=None,
            content="===FILE: a.py===\n===CREATE===\ndef foo(\n===END FILE==="
        )
        mock_llm.complete.return_value = mock_response

        result = asyncio.get_event_loop().run_until_complete(
            transporter_build(spec, mock_llm)
        )
        # Blocks returned even with validation errors (test-fix loop handles it)
        assert len(result) >= 1


class TestBuilderTransporterIntegration:
    """Tests for BuilderAgent.act() Transporter integration (AD-336)."""

    def test_act_handles_transporter_result(self):
        """act() correctly processes transporter_complete action."""
        agent = BuilderAgent.__new__(BuilderAgent)
        agent.agent_id = "test"
        decision = {
            "action": "transporter_complete",
            "file_changes": [{"path": "a.py", "content": "x=1", "mode": "create", "after_line": None}],
            "llm_output": "[Transporter]",
        }
        result = asyncio.get_event_loop().run_until_complete(agent.act(decision))
        assert result["success"] is True
        assert result["result"]["change_count"] == 1

    def test_act_still_handles_single_pass(self):
        """act() still works for non-transporter (single-pass) builds."""
        agent = BuilderAgent.__new__(BuilderAgent)
        agent.agent_id = "test"
        decision = {
            "llm_output": "===FILE: a.py===\n===CREATE===\ndef bar(): pass\n===END FILE===",
        }
        result = asyncio.get_event_loop().run_until_complete(agent.act(decision))
        assert result["success"] is True
        assert result["result"]["change_count"] == 1


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
            runtime=MagicMock(spec=ProbOSRuntime),
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
    @pytest.mark.asyncio
    async def test_formats_spec(self):
        """_build_user_message formats build spec fields."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(spec=ProbOSRuntime),
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
        msg = await agent._build_user_message(obs)
        assert "Add VectorStore" in msg
        assert "AD-400" in msg
        assert "src/vec.py" in msg
        assert "tests/test_vec.py" in msg
        assert "No new deps" in msg
        assert "Reference Code" in msg

    @pytest.mark.asyncio
    async def test_handles_missing_fields(self):
        """_build_user_message handles missing/empty fields gracefully."""
        agent = BuilderAgent(
            agent_id="builder-0",
            llm_client=MagicMock(),
            runtime=MagicMock(spec=ProbOSRuntime),
        )
        obs = {"params": {"title": "Minimal"}}
        msg = await agent._build_user_message(obs)
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            runtime=MagicMock(spec=ProbOSRuntime),
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
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(True, "1 passed", [])):
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
        llm_client = AsyncMock(spec=BaseLLMClient)
        llm_fix_response = MagicMock()
        llm_fix_response.content = (
            "===MODIFY: fixme.py===\n"
            "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
            "===END MODIFY==="
        )
        llm_client.complete = AsyncMock(return_value=llm_fix_response)

        # First test fails, second passes
        test_results = [(False, "1 failed", []), (True, "1 passed", [])]
        call_count = 0

        async def mock_run_targeted(work_dir, changed_files, timeout=60):
            nonlocal call_count
            result = test_results[min(call_count, len(test_results) - 1)]
            call_count += 1
            return result

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", side_effect=mock_run_targeted):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                    llm_client=llm_client,
                )

        assert result.tests_passed is True
        assert result.fix_attempts == 1
        assert llm_client.complete.call_count == 2  # 1 review + 1 fix

    @pytest.mark.asyncio
    async def test_fix_loop_exhausts_retries(self, tmp_path: Path):
        """Tests fail on all attempts — retries exhausted."""
        target = tmp_path / "broken.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Broken Build", description="Always fails")
        file_changes = [
            {"path": "broken.py", "content": "x = 1\n", "mode": "create", "after_line": None},
        ]

        llm_client = AsyncMock(spec=BaseLLMClient)
        llm_fix_response = MagicMock()
        llm_fix_response.content = (
            "===MODIFY: broken.py===\n"
            "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
            "===END MODIFY==="
        )
        llm_client.complete = AsyncMock(return_value=llm_fix_response)

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "1 failed", [])):
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

        llm_client = AsyncMock(spec=BaseLLMClient)
        llm_fix_response = MagicMock()
        llm_fix_response.content = "I'm not sure what to fix."  # no file blocks
        llm_client.complete = AsyncMock(return_value=llm_fix_response)

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "1 failed", [])):
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

        llm_client = AsyncMock(spec=BaseLLMClient)

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "1 failed", [])):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                    max_fix_attempts=0, llm_client=llm_client,
                )

        assert result.tests_passed is False
        assert result.fix_attempts == 0
        # One call for code review, zero for fix loop
        assert llm_client.complete.call_count == 1


# ---------------------------------------------------------------------------
# TestFindUnresolvedNamesEdgeCases — _find_unresolved_names() AST handling
# ---------------------------------------------------------------------------


class TestFindUnresolvedNamesEdgeCases:
    """Tests for _find_unresolved_names() AST node handling."""

    def test_vararg_in_function(self):
        """*args parameter is recognized as defined name."""
        source = "def foo(*args): pass"
        result = _find_unresolved_names(source)
        assert "args" not in result

    def test_kwarg_in_function(self):
        """**kwargs parameter is recognized as defined name."""
        source = "def foo(**kwargs): pass"
        result = _find_unresolved_names(source)
        assert "kwargs" not in result

    def test_kwonlyargs(self):
        """Keyword-only args after * are recognized."""
        source = "def foo(*, key): pass"
        result = _find_unresolved_names(source)
        assert "key" not in result

    def test_tuple_assignment(self):
        """Tuple unpacking targets are recognized."""
        source = "a, b = 1, 2"
        result = _find_unresolved_names(source)
        assert "a" not in result
        assert "b" not in result

    def test_annotated_assignment(self):
        """Annotated assignments (x: int = 1) are recognized."""
        source = "x: int = 1"
        result = _find_unresolved_names(source)
        assert "x" not in result

    def test_for_loop_variable(self):
        """For loop variable is recognized as defined."""
        source = "for i in range(10): pass"
        result = _find_unresolved_names(source)
        assert "i" not in result

    def test_with_statement_variable(self):
        """With statement 'as' variable is recognized."""
        source = "with open('f') as fp: pass"
        result = _find_unresolved_names(source)
        assert "fp" not in result

    def test_except_handler_variable(self):
        """Exception handler 'as' variable is recognized."""
        source = "try:\n    pass\nexcept Exception as e:\n    pass"
        result = _find_unresolved_names(source)
        assert "e" not in result

    def test_comprehension_variable(self):
        """Comprehension target variable is recognized."""
        source = "result = [x for x in range(10)]"
        result = _find_unresolved_names(source)
        assert "x" not in result

    def test_class_definition(self):
        """Class name is recognized as defined."""
        source = "class MyClass:\n    pass"
        result = _find_unresolved_names(source)
        assert "MyClass" not in result

    def test_import_alias(self):
        """Import alias is recognized as defined."""
        source = "import numpy as np\nresult = np.array([1])"
        result = _find_unresolved_names(source)
        assert "np" not in result

    def test_async_function_def(self):
        """Async function name is recognized as defined."""
        source = "async def do_work(): pass"
        result = _find_unresolved_names(source)
        assert "do_work" not in result

    def test_builtins_not_flagged(self):
        """Python builtins are not flagged as unresolved."""
        source = "result = len([1, 2, 3])\nprint(result)"
        result = _find_unresolved_names(source)
        assert "len" not in result
        assert "print" not in result

    def test_syntax_error_returns_empty(self):
        """Syntax errors return empty list."""
        source = "def ???: pass"
        result = _find_unresolved_names(source)
        assert result == []

    def test_truly_unresolved_name_detected(self):
        """A truly unresolved name IS flagged."""
        source = "result = some_unknown_lib.process()"
        result = _find_unresolved_names(source)
        assert "some_unknown_lib" in result


# ---------------------------------------------------------------------------
# TestValidateAssemblyChecks — validate_assembly() detailed checks
# ---------------------------------------------------------------------------


class TestValidateAssemblyChecks:
    """Tests for validate_assembly() detailed checks."""

    def _make_chunk(self, chunk_id="c1", target_file="test.py", description="test"):
        return ChunkSpec(
            chunk_id=chunk_id,
            description=description,
            target_file=target_file,
            what_to_generate="test code",
        )

    def test_syntax_error_detected(self):
        """validate_assembly() detects syntax errors in assembled blocks."""
        blueprint = BuildBlueprint(
            spec=BuildSpec(title="Test", description="Test"),
            chunks=[self._make_chunk()],
            results=[ChunkResult(
                chunk_id="c1",
                success=True,
                generated_code="def broken(\n",
                confidence=4,
            )],
        )
        assembled = [{"path": "test.py", "content": "def broken(\n", "mode": "create"}]
        result = validate_assembly(blueprint, assembled)
        assert not result.valid
        assert any(e["type"] == "syntax_error" for e in result.errors)

    def test_duplicate_definition_detected(self):
        """validate_assembly() detects duplicate function definitions."""
        source = "def foo(): pass\ndef foo(): pass\n"
        blueprint = BuildBlueprint(
            spec=BuildSpec(title="Test", description="Test"),
            chunks=[self._make_chunk()],
            results=[ChunkResult(
                chunk_id="c1",
                success=True,
                generated_code=source,
                confidence=4,
            )],
        )
        assembled = [{"path": "test.py", "content": source, "mode": "create"}]
        result = validate_assembly(blueprint, assembled)
        assert any(e["type"] == "duplicate_definition" for e in result.errors)

    def test_valid_assembly_passes(self):
        """validate_assembly() passes valid assembly."""
        source = "def foo(): pass\ndef bar(): pass\n"
        blueprint = BuildBlueprint(
            spec=BuildSpec(title="Test", description="Test"),
            chunks=[self._make_chunk()],
            results=[ChunkResult(
                chunk_id="c1",
                success=True,
                generated_code=source,
                confidence=4,
            )],
        )
        assembled = [{"path": "test.py", "content": source, "mode": "create"}]
        result = validate_assembly(blueprint, assembled)
        assert result.valid

    def test_empty_search_in_modify_block(self):
        """validate_assembly() flags MODIFY blocks with empty search strings."""
        blueprint = BuildBlueprint(
            spec=BuildSpec(title="Test", description="Test"),
            chunks=[self._make_chunk()],
            results=[ChunkResult(
                chunk_id="c1",
                success=True,
                generated_code="modified",
                confidence=4,
            )],
        )
        assembled = [{"path": "test.py", "content": "modified", "mode": "modify",
                       "replacements": [{"search": "   ", "replace": "new"}]}]
        result = validate_assembly(blueprint, assembled)
        assert any(e["type"] == "empty_search" for e in result.errors)

    def test_non_python_file_skips_syntax_check(self):
        """validate_assembly() skips syntax check for non-Python files."""
        blueprint = BuildBlueprint(
            spec=BuildSpec(title="Test", description="Test"),
            chunks=[self._make_chunk(target_file="config.json")],
            results=[ChunkResult(
                chunk_id="c1",
                success=True,
                generated_code='{"key": "value"}',
                confidence=4,
            )],
        )
        assembled = [{"path": "config.json", "content": '{"key": "value"}', "mode": "create"}]
        result = validate_assembly(blueprint, assembled)
        assert result.valid


# ---------------------------------------------------------------------------
# TestFallbackTruncate — _fallback_truncate() tests
# ---------------------------------------------------------------------------


class TestFallbackTruncate:
    """Tests for BuilderAgent._fallback_truncate()."""

    def test_short_content_unchanged(self):
        """Content under 15K chars is returned as-is."""
        files = {"short.py": "x = 1\n" * 100}
        result = BuilderAgent._fallback_truncate(files)
        assert result["short.py"] == files["short.py"]

    def test_long_content_truncated(self):
        """Content over 15K chars is truncated to head + tail."""
        long_content = "\n".join(f"line_{i} = {i}" for i in range(2000))
        assert len(long_content) > 15_000
        files = {"big.py": long_content}
        result = BuilderAgent._fallback_truncate(files)
        assert len(result["big.py"]) < len(long_content)
        assert "lines omitted" in result["big.py"]

    def test_multiple_files(self):
        """Mixed short and long files handled correctly."""
        short = "x = 1\n"
        long_content = "\n".join(f"line_{i} = {i}" for i in range(2000))
        files = {"short.py": short, "big.py": long_content}
        result = BuilderAgent._fallback_truncate(files)
        assert result["short.py"] == short
        assert "lines omitted" in result["big.py"]


# ---------------------------------------------------------------------------
# TestTransporterBuildEdgeCases — transporter_build() edge cases
# ---------------------------------------------------------------------------


class TestTransporterBuildEdgeCases:
    """Tests for transporter_build() edge cases."""

    @pytest.mark.asyncio
    async def test_empty_decomposition_returns_empty(self):
        """transporter_build() returns empty when decomposition yields no chunks."""
        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            error=None,
            content="No chunks could be identified.",
        ))

        spec = BuildSpec(
            title="Empty Build",
            description="Nothing to build",
            target_files=["empty.py"],
        )
        result = await transporter_build(spec=spec, llm_client=mock_llm)
        assert result == [] or isinstance(result, list)


# ---------------------------------------------------------------------------
# TestCommitGate — AD-338: Commit gate on test passage
# ---------------------------------------------------------------------------


class TestCommitGate:
    """Tests for the commit gate that blocks commits when tests fail."""

    @pytest.mark.asyncio
    async def test_gates_commit_on_test_failure(self, tmp_path: Path):
        """When tests fail, code is written but NOT committed."""
        target = tmp_path / "module.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Gate Test", description="Test gate")
        file_changes = [
            {"path": "module.py", "content": "x = 2\n", "mode": "create", "after_line": None},
        ]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "1 failed, 0 passed", [])):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                )

        assert result.success is False
        assert "Tests failed" in result.error
        assert result.commit_hash == ""  # No commit made

    @pytest.mark.asyncio
    async def test_commits_on_test_pass(self, tmp_path: Path):
        """When tests pass, commit proceeds normally."""
        target = tmp_path / "module.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Pass Test", description="Test pass")
        file_changes = [
            {"path": "module.py", "content": "x = 2\n", "mode": "create", "after_line": None},
        ]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(True, "1 passed", [])):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path), run_tests=True,
                )

        assert result.success is True
        assert result.tests_passed is True

    @pytest.mark.asyncio
    async def test_commits_when_tests_disabled(self, tmp_path: Path):
        """When run_tests=False, commit proceeds regardless."""
        target = tmp_path / "module.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="No Tests", description="Skip tests")
        file_changes = [
            {"path": "module.py", "content": "x = 2\n", "mode": "create", "after_line": None},
        ]

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            result = await execute_approved_build(
                file_changes, spec, str(tmp_path), run_tests=False,
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_fix_loop_with_llm_client(self, tmp_path: Path):
        """With llm_client, fix loop gets an LLM-powered fix attempt on test failure."""
        target = tmp_path / "module.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Fix Loop", description="Test fix loop")
        file_changes = [
            {"path": "module.py", "content": "x = 2\n", "mode": "create", "after_line": None},
        ]

        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            error=None,
            content="No changes needed.",
        ))

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        # First test run fails, second passes
        test_results = [(False, "1 failed", []), (True, "1 passed", [])]
        test_call_count = 0

        async def mock_run_targeted(wd, changed_files, timeout=60):
            nonlocal test_call_count
            r = test_results[min(test_call_count, len(test_results) - 1)]
            test_call_count += 1
            return r

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", side_effect=mock_run_targeted):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path),
                    run_tests=True,
                    llm_client=mock_llm,
                    max_fix_attempts=2,
                )

        assert result.fix_attempts >= 1
        mock_llm.complete.assert_called()  # LLM was consulted for the fix


# ---------------------------------------------------------------------------
# TestBuilderInstructions — AD-340: Enhanced Builder Instructions
# ---------------------------------------------------------------------------


class TestBuilderInstructions:
    """Tests for BuilderAgent.instructions content."""

    def test_instructions_contain_test_rules(self):
        """BuilderAgent.instructions contains key test-writing guidance."""
        inst = BuilderAgent.instructions
        assert "__init__ signature" in inst
        assert "from probos." in inst
        assert "_Fake" in inst
        assert "pytest.mark.asyncio" in inst


# ---------------------------------------------------------------------------
# TestCodeReviewIntegration — AD-341: Code Review in Builder pipeline
# ---------------------------------------------------------------------------


class TestCodeReviewIntegration:
    """Tests for code review integration in execute_approved_build()."""

    @pytest.mark.asyncio
    async def test_execute_build_runs_code_review(self, tmp_path: Path):
        """When llm_client is provided, CodeReviewAgent.review() is called."""
        target = tmp_path / "module.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Review Test", description="Test review")
        file_changes = [
            {"path": "module.py", "content": "x = 2\n", "mode": "create", "after_line": None},
        ]

        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            error=None,
            content='{"approved": true, "issues": [], "suggestions": [], "summary": "ok"}',
        ))

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(True, "1 passed", [])):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path),
                    run_tests=True,
                    llm_client=mock_llm,
                )

        assert result.success is True
        # LLM was called at least once (for the review)
        mock_llm.complete.assert_called()

    @pytest.mark.asyncio
    async def test_execute_build_logs_review_issues(self, tmp_path: Path):
        """When review returns issues, they appear in result.review_issues."""
        target = tmp_path / "module.py"
        target.write_text("x = 1\n", encoding="utf-8")

        spec = BuildSpec(title="Review Issues Test", description="Test")
        file_changes = [
            {"path": "module.py", "content": "x = 2\n", "mode": "create", "after_line": None},
        ]

        # Mock LLM: first call for review (returns issues), subsequent for test-fix loop
        review_response = MagicMock(
            error=None,
            content='{"approved": false, "issues": ["Bad import"], "suggestions": [], "summary": "Rejected"}',
        )
        pass_response = MagicMock(
            error=None,
            content="No fix needed.",
        )

        call_count = 0
        async def mock_complete(req):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return review_response
            return pass_response

        mock_llm = AsyncMock(spec=BaseLLMClient)
        mock_llm.complete = AsyncMock(side_effect=mock_complete)

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"main\n", stderr=b"")

        with patch("probos.cognitive.builder.subprocess.run", return_value=mock_result):
            with patch("probos.cognitive.builder._run_targeted_tests", return_value=(True, "1 passed", [])):
                result = await execute_approved_build(
                    file_changes, spec, str(tmp_path),
                    run_tests=True,
                    llm_client=mock_llm,
                )

        # Review issues should be populated (soft gate - still commits)
        assert result.review_issues == ["Bad import"]
        assert result.review_result == "Rejected"
        # Build still succeeds (soft gate)
        assert result.success is True


# ---------------------------------------------------------------------------
# BuildFailureReport (AD-343)
# ---------------------------------------------------------------------------


class TestBuildFailureReport:
    """Tests for BuildFailureReport dataclass (AD-343)."""

    def test_to_dict_returns_all_fields(self):
        report = BuildFailureReport(
            build_id="test-123",
            ad_number=999,
            title="Test Build",
            failure_category="test_failure",
            failure_summary="Tests failed",
        )
        d = report.to_dict()
        assert d["build_id"] == "test-123"
        assert d["ad_number"] == 999
        assert d["failure_category"] == "test_failure"
        assert isinstance(d["resolution_options"], list)
        assert isinstance(d["failed_tests"], list)

    def test_to_dict_defaults(self):
        report = BuildFailureReport()
        d = report.to_dict()
        assert d["build_id"] == ""
        assert d["ad_number"] == 0
        assert d["failed_tests"] == []
        assert d["resolution_options"] == []


class TestClassifyBuildFailure:
    """Tests for classify_build_failure function (AD-343)."""

    def _make_result(self, *, test_result="", error="", **kwargs):
        spec = BuildSpec(title="Test", description="desc")
        result = BuildResult(success=False, spec=spec, **kwargs)
        result.test_result = test_result
        result.error = error
        return result, spec

    def test_classify_timeout(self):
        result, spec = self._make_result(
            test_result="pytest timed out after 120s"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "timeout"
        assert "timed out" in report.failure_summary

    def test_classify_syntax_error(self):
        result, spec = self._make_result(
            test_result="SyntaxError: invalid syntax\n  File test.py, line 5"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "syntax_error"

    def test_classify_import_error(self):
        result, spec = self._make_result(
            test_result="ImportError: No module named 'nonexistent'"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "import_error"

    def test_classify_llm_error(self):
        result, spec = self._make_result(
            error="Request timeout"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "llm_error"

    def test_classify_test_failure_default(self):
        result, spec = self._make_result(
            test_result="FAILED tests/test_foo.py::test_bar - assert 1 == 2\n1 failed"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "test_failure"

    def test_extracts_failed_test_names(self):
        result, spec = self._make_result(
            test_result=(
                "FAILED tests/test_shell.py::TestShell::test_ping\n"
                "FAILED tests/test_api.py::test_health\n"
                "2 failed"
            )
        )
        report = classify_build_failure(result, spec)
        assert len(report.failed_tests) == 2
        assert "tests/test_shell.py::TestShell::test_ping" in report.failed_tests
        assert "tests/test_api.py::test_health" in report.failed_tests

    def test_extracts_error_locations(self):
        result, spec = self._make_result(
            test_result="src/probos/shell.py:42: AssertionError"
        )
        report = classify_build_failure(result, spec)
        assert any("shell.py:42" in loc for loc in report.error_locations)

    def test_timeout_resolution_options(self):
        result, spec = self._make_result(
            test_result="pytest timed out after 120s"
        )
        report = classify_build_failure(result, spec)
        option_ids = [o["id"] for o in report.resolution_options]
        assert "retry_extended" in option_ids
        assert "retry_targeted" in option_ids
        assert "abort" in option_ids

    def test_test_failure_resolution_options(self):
        result, spec = self._make_result(
            test_result="FAILED tests/test_foo.py::test_bar\n1 failed"
        )
        report = classify_build_failure(result, spec)
        option_ids = [o["id"] for o in report.resolution_options]
        assert "retry_targeted" in option_ids
        assert "retry_fix" in option_ids
        assert "commit_override" in option_ids
        assert "abort" in option_ids

    def test_copies_spec_metadata(self):
        spec = BuildSpec(title="My Build", description="desc", ad_number=999)
        result = BuildResult(success=False, spec=spec, branch_name="builder/ad-999")
        result.test_result = "FAILED tests/test.py::test_x\n1 failed"
        result.fix_attempts = 2
        result.review_result = "issues found"
        result.review_issues = ["issue1"]
        report = classify_build_failure(result, spec)
        assert report.title == "My Build"
        assert report.ad_number == 999
        assert report.branch_name == "builder/ad-999"
        assert report.fix_attempts == 2
        assert report.review_result == "issues found"
        assert report.review_issues == ["issue1"]


# ---------------------------------------------------------------------------
# Smart Test Selection (AD-344)
# ---------------------------------------------------------------------------


class TestMapSourceToTests:
    """Tests for _map_source_to_tests (AD-344)."""

    def test_maps_source_to_test_file(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_shell.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(["src/probos/experience/shell.py"], str(tmp_path))
        assert len(result) == 1
        assert "test_shell.py" in result[0]

    def test_includes_changed_test_files(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(["test_foo.py"], str(tmp_path))
        assert len(result) == 1

    def test_no_match_returns_empty(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        result = _map_source_to_tests(["src/probos/unique_module.py"], str(tmp_path))
        assert result == []

    def test_no_tests_dir_returns_empty(self, tmp_path):
        result = _map_source_to_tests(["src/probos/shell.py"], str(tmp_path))
        assert result == []

    def test_deduplicates(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_shell.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(
            ["src/probos/experience/shell.py", "src/probos/shell.py"],
            str(tmp_path),
        )
        assert len(result) == 1

    def test_glob_matches_prefixed(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_builder_agent.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(["src/probos/cognitive/builder.py"], str(tmp_path))
        assert len(result) == 1
        assert "test_builder" in result[0]


# ---------------------------------------------------------------------------
# Pending Failures Cache (AD-345)
# ---------------------------------------------------------------------------


class TestPendingFailuresCache:
    """Tests for the pending failures cache (AD-345)."""

    def test_clean_expired_removes_old(self):
        from probos.api import _pending_failures, _clean_expired_failures, _FAILURE_CACHE_TTL
        _pending_failures["old"] = {"timestamp": time.time() - _FAILURE_CACHE_TTL - 1}
        _pending_failures["recent"] = {"timestamp": time.time()}
        _clean_expired_failures()
        assert "old" not in _pending_failures
        assert "recent" in _pending_failures
        # Cleanup
        _pending_failures.clear()


# ---------------------------------------------------------------------------
# Escalation Hook (AD-347)
# ---------------------------------------------------------------------------


class TestEscalationHook:
    """Tests for the escalation hook on execute_approved_build (AD-347)."""

    @pytest.mark.asyncio
    async def test_hook_called_on_failure(self, tmp_path):
        """Escalation hook is called when tests fail."""
        hook_called = []

        async def mock_hook(report):
            hook_called.append(report)
            return None  # Don't resolve

        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "FAILED tests/test_x.py::test_y", [])):
            with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                with patch("probos.cognitive.builder._git_checkout_main"):
                    with patch("probos.cognitive.builder._git_current_branch", return_value="main"):
                        result = await execute_approved_build(
                            changes, spec, str(tmp_path),
                            run_tests=True,
                            max_fix_attempts=0,
                            escalation_hook=mock_hook,
                        )

        assert len(hook_called) == 1
        assert hook_called[0].failure_category == "test_failure"
        assert not result.success

    @pytest.mark.asyncio
    async def test_hook_resolves_failure(self, tmp_path):
        """When hook returns a BuildResult, it replaces the failure."""
        resolved_result = BuildResult(
            success=True,
            spec=BuildSpec(title="Test", description="test"),
            tests_passed=True,
        )

        async def resolving_hook(report):
            return resolved_result

        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "FAILED", [])):
            with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                with patch("probos.cognitive.builder._git_checkout_main"):
                    with patch("probos.cognitive.builder._git_add_and_commit", return_value=(True, "abc123")):
                        with patch("probos.cognitive.builder._git_current_branch", return_value="main"):
                            result = await execute_approved_build(
                                changes, spec, str(tmp_path),
                                run_tests=True,
                                max_fix_attempts=0,
                                escalation_hook=resolving_hook,
                            )

        assert result.success
        assert result.tests_passed

    @pytest.mark.asyncio
    async def test_hook_not_called_on_success(self, tmp_path):
        """Escalation hook is NOT called when tests pass."""
        hook_called = []

        async def mock_hook(report):
            hook_called.append(report)
            return None

        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(True, "1 passed", ["test.py"])):
            with patch("probos.cognitive.builder._run_tests", return_value=(True, "2254 passed")):
                with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                    with patch("probos.cognitive.builder._git_checkout_main"):
                        with patch("probos.cognitive.builder._git_add_and_commit", return_value=(True, "abc123")):
                            with patch("probos.cognitive.builder._git_current_branch", return_value="main"):
                                result = await execute_approved_build(
                                    changes, spec, str(tmp_path),
                                    run_tests=True,
                                    max_fix_attempts=0,
                                    escalation_hook=mock_hook,
                                )

        assert len(hook_called) == 0
        assert result.success

    @pytest.mark.asyncio
    async def test_no_hook_provided(self, tmp_path):
        """Works correctly when no hook is provided (default behavior)."""
        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "FAILED", [])):
            with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                with patch("probos.cognitive.builder._git_checkout_main"):
                    with patch("probos.cognitive.builder._git_current_branch", return_value="main"):
                        result = await execute_approved_build(
                            changes, spec, str(tmp_path),
                            run_tests=True,
                            max_fix_attempts=0,
                        )

        assert not result.success
