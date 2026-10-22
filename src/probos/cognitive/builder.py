"""BuilderAgent — code generation via LLM with Captain approval (AD-302/303).

A CognitiveAgent in the Engineering team that accepts structured build specs,
generates code via the deep LLM tier, parses file changes from the LLM output,
and returns them for Captain approval.  After approval, `execute_approved_build()`
orchestrates: git branch → write files → pytest → commit → return to the ref it started from (BF-904a).
"""

from __future__ import annotations

import asyncio
import ast
import hashlib
import logging
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.cognitive.builder_paths import (
    builder_write_refusal,
    fix_loop_path,
    fix_loop_write_refusal,
    operator_checkout_refusal,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.events import EventType
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS, build_command_env
from probos.execution.isolation import remove_workdir_off_loop

if TYPE_CHECKING:
    from collections.abc import Callable

    from probos.cognitive.codebase_index import CodebaseIndex
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.runtime import ProbOSRuntime


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

# The true project root (D:\ProbOS or equivalent).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# The source package root (D:\ProbOS\src\probos).
_SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _resolve_path(file_path: str) -> Path:
    """Resolve a file path that may be relative to different roots.

    The Architect outputs paths in two formats:
      - CodebaseIndex-relative: ``experience/shell.py`` (relative to src/probos/)
      - Project-relative: ``src/probos/experience/shell.py`` (relative to project root)

    Try in order: absolute, project-relative, source-relative.
    Returns the first match, or the project-relative path if nothing exists.
    """
    p = Path(file_path)
    if p.is_absolute():
        return p
    # Try project-root-relative first  (src/probos/experience/shell.py)
    candidate = _PROJECT_ROOT / file_path
    if candidate.exists():
        return candidate
    # Try source-root-relative  (experience/shell.py → src/probos/experience/shell.py)
    candidate = _SOURCE_ROOT / file_path
    if candidate.exists():
        return candidate
    # Nothing exists — return project-relative as default (new file)
    return _PROJECT_ROOT / file_path


def _normalize_change_paths(file_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize file paths in change blocks to project-relative paths.

    The LLM may output CodebaseIndex-relative paths (``experience/shell.py``)
    which need to become ``src/probos/experience/shell.py`` for
    ``execute_approved_build()`` to find them relative to the project root.
    """
    for change in file_changes:
        raw = change["path"]
        resolved = _resolve_path(raw)
        try:
            change["path"] = str(resolved.relative_to(_PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            pass  # Path not under project root — leave as-is
    return file_changes


# BF-894 (#1547): the write-path boundary is builder_paths.builder_write_refusal, called
# from both write paths in execute_approved_build. This name is kept for
# tests/test_builder_guardrails.py.
_validate_file_path = builder_write_refusal


from probos.types import IntentDescriptor, LLMRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes (AD-302)
# ---------------------------------------------------------------------------

@dataclass
class BuildSpec:
    """A structured specification for a code change."""

    title: str
    description: str
    target_files: list[str] = field(default_factory=list)
    reference_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    ad_number: int = 0
    branch_name: str = ""
    constraints: list[str] = field(default_factory=list)


@dataclass
class BuildResult:
    """Result of a builder agent execution."""

    success: bool
    spec: BuildSpec
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    test_result: str = ""
    tests_passed: bool = False
    branch_name: str = ""
    commit_hash: str = ""
    error: str = ""
    llm_output: str = ""
    fix_attempts: int = 0
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)
    builder_source: str = "native"  # "native" | "visiting" | "native_harness" (AD-353/546)
    # AD-549: Structured execution metadata. Populated by NativeBuilderHarness with
    # builder_type / iterations / tools_used / compactions / stopped_reason / total_tokens.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuildFailureReport:
    """Structured diagnostic report for a failed build (AD-343)."""

    # What was attempted
    build_id: str = ""
    ad_number: int = 0
    title: str = ""
    branch_name: str = ""
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)

    # What failed
    failure_category: str = ""  # "timeout", "test_failure", "syntax_error", "import_error", "llm_error", "commit_error"
    failure_summary: str = ""   # One-sentence human-readable summary
    raw_error: str = ""         # Full error text (for collapsible view)
    cleanup_errors: list[str] = field(default_factory=list)  # BF-904a A3 (D28): non-empty: the checkout is not known to be as the build found it
    failed_tests: list[str] = field(default_factory=list)  # Extracted test names
    error_locations: list[str] = field(default_factory=list)  # file:line references

    # What was tried
    fix_attempts: int = 0
    fix_descriptions: list[str] = field(default_factory=list)

    # Review
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)

    # Resolution options
    resolution_options: list[dict[str, str]] = field(default_factory=list)
    # Each dict has: {"id": "retry_targeted", "label": "...", "description": "..."}

    def to_dict(self) -> dict:
        """Serialize for WebSocket event payload."""
        return {
            "build_id": self.build_id,
            "ad_number": self.ad_number,
            "title": self.title,
            "branch_name": self.branch_name,
            "files_written": self.files_written,
            "files_modified": self.files_modified,
            "failure_category": self.failure_category,
            "failure_summary": self.failure_summary,
            "raw_error": self.raw_error,
            "failed_tests": self.failed_tests,
            "error_locations": self.error_locations,
            "fix_attempts": self.fix_attempts,
            "fix_descriptions": self.fix_descriptions,
            "review_result": self.review_result,
            "review_issues": self.review_issues,
            "resolution_options": self.resolution_options,
        }


def classify_build_failure(result: BuildResult, spec: BuildSpec) -> BuildFailureReport:
    """Classify a failed BuildResult into a structured report (AD-343).

    Parses pytest output to extract failure category, failed test names,
    error locations, and generates contextual resolution options.
    """
    import re

    report = BuildFailureReport(
        ad_number=spec.ad_number,
        title=spec.title,
        branch_name=result.branch_name,
        files_written=list(result.files_written),
        files_modified=list(result.files_modified),
        fix_attempts=result.fix_attempts,
        review_result=result.review_result,
        review_issues=list(result.review_issues),
        raw_error=result.error or result.test_result or "",
        cleanup_errors=list(result.metadata.get("cleanup_errors", [])),  # BF-904a A3 (D28)
    )

    test_output = result.test_result or ""
    error_text = result.error or ""
    combined = test_output + "\n" + error_text

    # 1. Classify the failure category
    if "timed out after" in combined:
        report.failure_category = "timeout"
        report.failure_summary = "Test suite timed out before completing"
    elif "SyntaxError" in combined:
        report.failure_category = "syntax_error"
        report.failure_summary = "Python syntax errors in generated code"
    elif "ImportError" in combined or "ModuleNotFoundError" in combined:
        report.failure_category = "import_error"
        report.failure_summary = "Import or module resolution errors"
    elif "timeout_error" in error_text or "Request timeout" in error_text:
        report.failure_category = "llm_error"
        report.failure_summary = "LLM request failed or timed out"
    elif "Commit failed" in error_text:
        report.failure_category = "commit_error"
        report.failure_summary = "Git commit operation failed"
    else:
        report.failure_category = "test_failure"
        report.failure_summary = "Test assertions failed after fix attempts"

    # 2. Extract failed test names (FAILED tests/test_foo.py::TestClass::test_method)
    failed_pattern = re.compile(r"FAILED\s+(tests/\S+)")
    report.failed_tests = failed_pattern.findall(test_output)

    # 3. Extract error locations (file:line patterns from tracebacks)
    location_pattern = re.compile(r"([\w/\\]+\.py):(\d+)")
    seen: set[str] = set()
    for match in location_pattern.finditer(test_output):
        loc = f"{match.group(1)}:{match.group(2)}"
        if loc not in seen:
            seen.add(loc)
            report.error_locations.append(loc)

    # 4. Generate resolution options per category
    if report.failure_category == "timeout":
        report.resolution_options = [
            {"id": "retry_extended", "label": "Retry with extended timeout", "description": "Re-run tests with 300s timeout"},
            {"id": "retry_targeted", "label": "Retry targeted tests only", "description": "Run only tests related to changed files"},
            {"id": "commit_override", "label": "Commit anyway", "description": "Override test gate and commit to branch"},
            {"id": "abort", "label": "Abort", "description": "Dismiss the failed build. Runs no git: its cleanup already ran; check the report for any cleanup notes"},
        ]
    elif report.failure_category == "test_failure":
        report.resolution_options = [
            {"id": "retry_targeted", "label": "Retry targeted tests only", "description": "Run only tests related to changed files"},
            {"id": "retry_fix", "label": "Retry with more fix attempts", "description": "Give the LLM 4 more attempts to fix failing tests"},
            {"id": "commit_override", "label": "Commit anyway", "description": "Override test gate and commit to branch"},
            {"id": "abort", "label": "Abort", "description": "Dismiss the failed build. Runs no git: its cleanup already ran; check the report for any cleanup notes"},
        ]
    elif report.failure_category in ("syntax_error", "import_error"):
        report.resolution_options = [
            {"id": "retry_fix", "label": "Retry with more fix attempts", "description": "Give the LLM 4 more attempts to fix the errors"},
            {"id": "abort", "label": "Abort", "description": "Dismiss the failed build. Runs no git: its cleanup already ran; check the report for any cleanup notes"},
        ]
    elif report.failure_category == "llm_error":
        report.resolution_options = [
            {"id": "retry_full", "label": "Retry entire build", "description": "Re-run the full build pipeline from scratch"},
            {"id": "abort", "label": "Abort", "description": "Dismiss the failed build. Runs no git: its cleanup already ran; check the report for any cleanup notes"},
        ]
    else:
        report.resolution_options = [
            {"id": "abort", "label": "Abort", "description": "Dismiss the failed build. Runs no git: its cleanup already ran; check the report for any cleanup notes"},
        ]

    return report
# ---------------------------------------------------------------------------


@dataclass
class ChunkSpec:
    """A single unit of work for parallel chunk execution (Transporter Pattern).

    Each chunk specifies what to generate, what context it needs,
    what it produces, and which other chunks it depends on.
    """

    chunk_id: str
    description: str
    target_file: str
    what_to_generate: str
    required_context: list[str] = field(default_factory=list)
    expected_output: str = ""
    depends_on: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass
class ChunkResult:
    """Result from a single chunk's LLM generation (Transporter Pattern).

    Uses a Structured Information Protocol: generated code, rationale
    for decisions, output signature, and confidence score for
    downstream conflict resolution during assembly.
    """

    chunk_id: str
    success: bool = False
    generated_code: str = ""
    decisions: str = ""
    output_signature: str = ""
    confidence: int = 3
    error: str = ""
    tokens_used: int = 0


@dataclass
class BuildBlueprint:
    """Enhanced build specification with structural metadata for chunk decomposition.

    The 'pattern buffer' — contains the interface contracts, shared context,
    and decomposition hints that the ChunkDecomposer uses to break the build
    into parallel ChunkSpecs.
    """

    spec: BuildSpec
    interface_contracts: list[str] = field(default_factory=list)
    shared_imports: list[str] = field(default_factory=list)
    shared_context: str = ""
    chunk_hints: list[str] = field(default_factory=list)
    chunks: list[ChunkSpec] = field(default_factory=list)
    results: list[ChunkResult] = field(default_factory=list)

    def validate_chunk_dag(self) -> tuple[bool, str]:
        """Validate that chunk dependencies form a DAG (no cycles).

        Returns (True, "") if valid, (False, error_message) if cycles detected.
        Uses Kahn's algorithm for topological sort.
        """
        if not self.chunks:
            return True, ""

        in_degree: dict[str, int] = {c.chunk_id: 0 for c in self.chunks}
        dependents: dict[str, list[str]] = {c.chunk_id: [] for c in self.chunks}

        for chunk in self.chunks:
            for dep_id in chunk.depends_on:
                if dep_id not in in_degree:
                    return False, f"Chunk '{chunk.chunk_id}' depends on unknown chunk '{dep_id}'"
                dependents[dep_id].append(chunk.chunk_id)
                in_degree[chunk.chunk_id] += 1

        queue = [cid for cid, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            node = queue.pop(0)
            visited += 1
            for dep in dependents[node]:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if visited != len(self.chunks):
            return False, "Cycle detected in chunk dependencies"
        return True, ""

    def get_ready_chunks(self, completed: set[str] | None = None) -> list[ChunkSpec]:
        """Return chunks whose dependencies are all satisfied.

        Args:
            completed: Set of chunk_ids already completed. None = no chunks completed.

        Returns:
            List of ChunkSpecs ready for execution.
        """
        if completed is None:
            completed = set()

        return [
            c for c in self.chunks
            if c.chunk_id not in completed
            and all(dep in completed for dep in c.depends_on)
        ]


@dataclass
class ValidationResult:
    """Result of post-assembly interface validation (Heisenberg Compensator).

    Captures validation errors with per-chunk attribution so the system
    knows which chunk to re-generate on failure.
    """

    valid: bool = True
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)
    chunks_validated: int = 0
    checks_passed: int = 0
    checks_failed: int = 0


def create_blueprint(spec: BuildSpec) -> BuildBlueprint:
    """Create a BuildBlueprint from a BuildSpec with no chunk decomposition.

    This is the entry point for the Transporter Pattern.
    The blueprint starts with empty chunks — the ChunkDecomposer (AD-331)
    populates them later.
    """
    return BuildBlueprint(spec=spec)


def _fallback_decompose(blueprint: BuildBlueprint) -> BuildBlueprint:
    """Fallback decomposition: one chunk per target file, one for tests.

    Used when the LLM decomposition fails or returns invalid results.
    Simple but correct — every file gets exactly one chunk.
    """
    spec = blueprint.spec
    chunks: list[ChunkSpec] = []

    # One chunk per target file
    for i, path in enumerate(spec.target_files):
        chunks.append(ChunkSpec(
            chunk_id=f"chunk-{i}",
            description=f"Generate changes for {path}",
            target_file=path,
            what_to_generate="code",
        ))

    # One chunk for all test files (depends on all implementation chunks)
    if spec.test_files:
        impl_ids = [c.chunk_id for c in chunks]
        for _j, test_path in enumerate(spec.test_files):
            chunks.append(ChunkSpec(
                chunk_id=f"chunk-{len(chunks)}",
                description=f"Generate tests in {test_path}",
                target_file=test_path,
                what_to_generate="test_class",
                depends_on=impl_ids,
            ))

    blueprint.chunks = chunks
    logger.info("ChunkDecomposer fallback: %d chunks (%d impl + %d test)",
                len(chunks), len(spec.target_files), len(spec.test_files))
    return blueprint


def _build_chunk_context(
    blueprint: BuildBlueprint,
    target_file: str,
    target_contents: dict[str, str],
) -> list[str]:
    """Build the required_context list for a single chunk.

    Includes interface contracts, shared imports, shared context,
    and a structural outline of the target file (if it exists).
    Context is kept minimal — the chunk gets L1-L3 abstractions,
    not full file content.
    """
    context: list[str] = []

    # Interface contracts are always included (ground truth for all chunks)
    if blueprint.interface_contracts:
        context.append("## Interface Contracts\n" + "\n".join(blueprint.interface_contracts))

    # Shared imports
    if blueprint.shared_imports:
        context.append("## Shared Imports\n" + "\n".join(blueprint.shared_imports))

    # Shared context (module docstring, base class, constants)
    if blueprint.shared_context:
        context.append("## Shared Context\n" + blueprint.shared_context)

    # Target file outline (L1 abstraction — AST structure, not full content)
    if target_file in target_contents:
        content = target_contents[target_file]
        if content:
            outline = BuilderAgent._build_file_outline(content, target_file)
            context.append(f"## Target File Structure\n{outline}")

            # Also include imports section (first 30 lines) for reference
            lines = content.split("\n")
            import_section = "\n".join(lines[:30])
            context.append(f"## Target File Imports\n{import_section}")

    return context


async def decompose_blueprint(
    blueprint: BuildBlueprint,
    llm_client: BaseLLMClient,
    codebase_index: CodebaseIndex | None = None,
    work_dir: str | None = None,
    on_event: Callable | None = None,
) -> BuildBlueprint:
    """Decompose a BuildBlueprint into parallel ChunkSpecs (Dematerializer).

    Analyzes the build spec and produces independent chunks that can be
    executed in parallel. Each chunk carries only the context it needs.

    Args:
        blueprint: The BuildBlueprint to decompose (mutated in place).
        llm_client: LLM client for fast-tier analysis.
        codebase_index: Optional CodebaseIndex for import/structure analysis.
        work_dir: Project root for reading source files. Defaults to
            probos project root.

    Returns:
        The same blueprint with .chunks populated.

    Raises:
        ValueError: If decomposition produces invalid chunks (cycles, no coverage).
    """
    import json

    project_root = Path(work_dir) if work_dir else _PROJECT_ROOT
    spec = blueprint.spec

    # Read target files to understand their structure
    target_contents: dict[str, str] = {}
    for path in spec.target_files:
        full = _resolve_path(path) if not work_dir else (Path(work_dir) / path)
        if full.exists() and full.is_file():
            target_contents[path] = full.read_text(encoding="utf-8")

    # Build structural information
    outlines: list[str] = []
    for path, content in target_contents.items():
        outlines.append(BuilderAgent._build_file_outline(content, path))

    # Gather import context from CodebaseIndex if available
    import_context = ""
    if codebase_index is not None:
        import_lines: list[str] = []
        for path in spec.target_files:
            try:
                imports = codebase_index.get_imports(path)
                if imports:
                    import_lines.append(f"{path} imports: {', '.join(imports)}")
                importers = codebase_index.find_importers(path)
                if importers:
                    import_lines.append(f"{path} imported by: {', '.join(importers)}")
            except Exception:
                logger.debug("Builder context failed", exc_info=True)
        if import_lines:
            import_context = "\n## Import Relationships\n" + "\n".join(import_lines)

    # Build the decomposition prompt
    outline_text = "\n\n".join(outlines) if outlines else "(all new files)"
    hints_text = "\n".join(f"- {h}" for h in blueprint.chunk_hints) if blueprint.chunk_hints else "(none)"
    contracts_text = "\n".join(blueprint.interface_contracts) if blueprint.interface_contracts else "(none)"

    decompose_prompt = (
        f"# Decompose this build into independent parallel chunks\n\n"
        f"## Build: {spec.title}\n{spec.description}\n\n"
        f"## Target Files\n" + "\n".join(f"- {f}" for f in spec.target_files) + "\n\n"
        f"## Test Files\n" + "\n".join(f"- {f}" for f in spec.test_files) + "\n\n"
        f"## File Structure\n{outline_text}\n\n"
        f"## Interface Contracts\n{contracts_text}\n\n"
        f"## Decomposition Hints\n{hints_text}\n"
        f"{import_context}\n\n"
        f"## Instructions\n"
        f"Break this build into the smallest independent chunks that can be "
        f"generated by separate LLM calls in parallel.\n\n"
        f"Rules:\n"
        f"- One chunk per new function/method being added or modified\n"
        f"- One chunk per test class or test group\n"
        f"- One chunk per file if the build spans multiple files\n"
        f"- If a chunk depends on another chunk's output (e.g., tests depend on "
        f"the implementation), mark the dependency\n"
        f"- Each chunk should target exactly ONE file\n"
        f"- Chunks that modify the same file are OK — they will be merged later\n\n"
        f"Respond with ONLY a JSON object, no markdown fences:\n"
        f'{{"chunks": [\n'
        f'  {{"description": "what to generate", "target_file": "path/to/file.py", '
        f'"what_to_generate": "function/class/test_class/imports/etc", '
        f'"depends_on": [], '
        f'"constraints": []}},\n'
        f'  ...\n'
        f']}}'
    )

    try:
        request = LLMRequest(
            prompt=decompose_prompt,
            system_prompt=(
                "You are a code decomposition planner. Break builds into the smallest "
                "independent parallel work units. Return only valid JSON."
            ),
            tier="fast",
            temperature=0.0,
        )
        response = await llm_client.complete(request)

        if response.error:
            logger.warning("ChunkDecomposer: LLM error: %s, using fallback", response.error)
            blueprint = _fallback_decompose(blueprint)
            if on_event:
                asyncio.create_task(on_event(EventType.TRANSPORTER_DECOMPOSED, {
                    "chunk_count": len(blueprint.chunks),
                    "chunks": [{"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file} for c in blueprint.chunks],
                    "fallback": True,
                }))
            return blueprint

        text = response.content.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0] if "```" in text else text
            text = text.strip()

        data = json.loads(text)
        raw_chunks = data.get("chunks", [])

        if not raw_chunks:
            logger.warning("ChunkDecomposer: LLM returned empty chunks, using fallback")
            blueprint = _fallback_decompose(blueprint)
            if on_event:
                asyncio.create_task(on_event(EventType.TRANSPORTER_DECOMPOSED, {
                    "chunk_count": len(blueprint.chunks),
                    "chunks": [{"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file} for c in blueprint.chunks],
                    "fallback": True,
                }))
            return blueprint

    except Exception as exc:
        logger.warning("ChunkDecomposer: failed (%s), using fallback decomposition", exc)
        blueprint = _fallback_decompose(blueprint)
        if on_event:
            asyncio.create_task(on_event(EventType.TRANSPORTER_DECOMPOSED, {
                "chunk_count": len(blueprint.chunks),
                "chunks": [{"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file} for c in blueprint.chunks],
                "fallback": True,
            }))
        return blueprint

    # Convert raw LLM chunks into ChunkSpec objects
    chunks: list[ChunkSpec] = []
    for i, raw in enumerate(raw_chunks):
        chunk_id = f"chunk-{i}"
        # Map depends_on from description references to chunk IDs
        # The LLM may use indices or descriptions — normalize to chunk IDs
        raw_deps = raw.get("depends_on", [])
        dep_ids: list[str] = []
        for dep in raw_deps:
            if isinstance(dep, int):
                dep_ids.append(f"chunk-{dep}")
            elif isinstance(dep, str) and dep.startswith("chunk-"):
                dep_ids.append(dep)
            # else: ignore unrecognizable dependency references

        chunks.append(ChunkSpec(
            chunk_id=chunk_id,
            description=raw.get("description", f"Chunk {i}"),
            target_file=raw.get("target_file", spec.target_files[0] if spec.target_files else ""),
            what_to_generate=raw.get("what_to_generate", "code"),
            required_context=_build_chunk_context(
                blueprint, raw.get("target_file", ""), target_contents,
            ),
            expected_output=raw.get("expected_output", ""),
            depends_on=dep_ids,
            constraints=raw.get("constraints", []) + blueprint.spec.constraints,
        ))

    blueprint.chunks = chunks

    # Validate
    valid, err = blueprint.validate_chunk_dag()
    if not valid:
        logger.warning("ChunkDecomposer: invalid DAG (%s), using fallback", err)
        blueprint = _fallback_decompose(blueprint)
        if on_event:
            asyncio.create_task(on_event(EventType.TRANSPORTER_DECOMPOSED, {
                "chunk_count": len(blueprint.chunks),
                "chunks": [{"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file} for c in blueprint.chunks],
                "fallback": True,
            }))
        return blueprint

    # Validate coverage: every target file must be addressed by at least one chunk
    covered_files = {c.target_file for c in chunks}
    missing = set(spec.target_files) - covered_files
    if missing:
        # Add catch-all chunks for uncovered files
        for path in missing:
            chunks.append(ChunkSpec(
                chunk_id=f"chunk-{len(chunks)}",
                description=f"Generate changes for {path}",
                target_file=path,
                what_to_generate="code",
                required_context=_build_chunk_context(blueprint, path, target_contents),
            ))
        blueprint.chunks = chunks

    logger.info(
        "ChunkDecomposer: produced %d chunks for %d target files",
        len(chunks), len(spec.target_files),
    )
    if on_event:
        asyncio.create_task(on_event(EventType.TRANSPORTER_DECOMPOSED, {
            "chunk_count": len(blueprint.chunks),
            "chunks": [
                {"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file}
                for c in blueprint.chunks
            ],
        }))
    return blueprint


def _parse_chunk_response(chunk: ChunkSpec, response: Any) -> ChunkResult:
    """Parse an LLM response into a ChunkResult.

    Extracts generated code (file blocks), decisions rationale,
    confidence score, and output signature.
    """
    content = response.content or ""

    # Extract decisions rationale
    decisions = ""
    decisions_match = re.search(r"DECISIONS:\s*(.+?)(?=\nCONFIDENCE:|\Z)", content, re.DOTALL)
    if decisions_match:
        decisions = decisions_match.group(1).strip()

    # Extract confidence score
    confidence = 3  # default
    confidence_match = re.search(r"CONFIDENCE:\s*(\d)", content)
    if confidence_match:
        confidence = max(1, min(5, int(confidence_match.group(1))))

    # Extract file blocks to use as generated_code
    # Reuse the existing parser to validate the output has parseable blocks
    file_blocks = BuilderAgent._parse_file_blocks(content)
    has_code = len(file_blocks) > 0

    # Build output signature from file blocks
    output_sig_parts: list[str] = []
    for block in file_blocks:
        if block["mode"] == "create":
            output_sig_parts.append(f"CREATE {block['path']}")
        else:
            output_sig_parts.append(f"MODIFY {block['path']} ({len(block.get('replacements', []))} replacements)")
    output_signature = "; ".join(output_sig_parts) if output_sig_parts else ""

    return ChunkResult(
        chunk_id=chunk.chunk_id,
        success=has_code,
        generated_code=content,
        decisions=decisions,
        output_signature=output_signature,
        confidence=confidence,
        error="" if has_code else "No file blocks found in LLM output",
        tokens_used=response.tokens_used if hasattr(response, "tokens_used") else 0,
    )


def _build_chunk_prompt(chunk: ChunkSpec, blueprint: BuildBlueprint) -> str:
    """Build the LLM prompt for a single chunk.

    Includes only the chunk's required context, not the full codebase.
    """
    spec = blueprint.spec
    parts: list[str] = [
        f"# Chunk: {chunk.description}",
        f"Part of build: {spec.title}",
        f"AD Number: AD-{spec.ad_number}" if spec.ad_number else "",
        f"\n## What to Generate\n{chunk.what_to_generate}",
        f"Target file: {chunk.target_file}",
    ]

    if chunk.expected_output:
        parts.append(f"\n## Expected Output\n{chunk.expected_output}")

    if chunk.constraints:
        parts.append("\n## Constraints\n" + "\n".join(f"- {c}" for c in chunk.constraints))

    # Add chunk-specific context (L1-L3 abstractions from _build_chunk_context)
    if chunk.required_context:
        parts.append("\n## Context")
        parts.extend(chunk.required_context)

    # Add results from dependency chunks (so this chunk can reference their output)
    if chunk.depends_on and blueprint.results:
        dep_results: list[str] = []
        for dep_id in chunk.depends_on:
            for result in blueprint.results:
                if result.chunk_id == dep_id and result.success:
                    dep_results.append(
                        f"--- {dep_id}: {result.output_signature} ---\n"
                        f"{result.generated_code[:2000]}"
                    )
        if dep_results:
            parts.append("\n## Completed Dependency Chunks\n" + "\n".join(dep_results))

    return "\n".join(p for p in parts if p)


async def _execute_single_chunk(
    chunk: ChunkSpec,
    blueprint: BuildBlueprint,
    llm_client: BaseLLMClient,
    timeout: float,
    max_retries: int,
) -> ChunkResult:
    """Execute a single chunk's LLM generation with timeout and retry.

    Builds a focused prompt from the chunk's context and spec,
    sends it to the deep LLM tier, and parses the output.
    """
    # Build chunk-specific prompt
    prompt = _build_chunk_prompt(chunk, blueprint)

    # System prompt reuses the Builder's instructions format
    system_prompt = (
        "You are the Builder Agent for ProbOS, generating code for one specific chunk "
        "of a larger build. Generate ONLY what this chunk asks for — nothing else.\n\n"
        "OUTPUT FORMAT:\n"
        "For new files:\n"
        "===FILE: path/to/file.py===\n"
        "<complete file contents>\n"
        "===END FILE===\n\n"
        "For modifications to existing files:\n"
        "===MODIFY: path/to/file.py===\n"
        "===SEARCH===\n<exact existing code>\n===REPLACE===\n"
        "<replacement code>\n===END REPLACE===\n===END MODIFY===\n\n"
        "After the code blocks, add a brief DECISIONS section explaining your choices, "
        "and rate your CONFIDENCE (1-5) based on how much context you had:\n"
        "5=full contracts+reference, 4=contracts only, 3=description only, "
        "2=minimal context, 1=near-blind.\n\n"
        "DECISIONS: <your rationale>\n"
        "CONFIDENCE: <1-5>"
    )

    last_error = ""
    for attempt in range(1 + max_retries):
        try:
            request = LLMRequest(
                prompt=prompt if attempt == 0 else prompt + f"\n\n(Previous attempt failed: {last_error})",
                system_prompt=system_prompt,
                tier="deep",
                temperature=0.0,
            )

            response = await asyncio.wait_for(
                llm_client.complete(request),
                timeout=timeout,
            )

            if response.error:
                last_error = response.error
                logger.warning(
                    "Chunk %s attempt %d: LLM error: %s",
                    chunk.chunk_id, attempt + 1, response.error,
                )
                continue

            # Parse the response
            return _parse_chunk_response(chunk, response)

        except asyncio.TimeoutError:
            last_error = f"timeout after {timeout}s"
            logger.warning("Chunk %s attempt %d: %s", chunk.chunk_id, attempt + 1, last_error)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Chunk %s attempt %d: error: %s", chunk.chunk_id, attempt + 1, exc)

    # All attempts exhausted
    return ChunkResult(
        chunk_id=chunk.chunk_id,
        success=False,
        error=f"Failed after {1 + max_retries} attempts: {last_error}",
        confidence=1,
    )


async def execute_chunks(
    blueprint: BuildBlueprint,
    llm_client: BaseLLMClient,
    per_chunk_timeout: float = 120.0,
    max_retries: int = 1,
    on_event: Callable | None = None,
) -> BuildBlueprint:
    """Execute all chunks in a decomposed BuildBlueprint in parallel (Matter Stream).

    Respects chunk dependency ordering: independent chunks run concurrently,
    dependent chunks wait for their prerequisites to complete.

    Args:
        blueprint: Blueprint with .chunks populated by decompose_blueprint().
        llm_client: LLM client for deep-tier generation.
        per_chunk_timeout: Timeout per chunk LLM call in seconds.
        max_retries: Max retry attempts per failed chunk (0 = no retries).
        on_event: Optional async callback for HXI event emission.

    Returns:
        The same blueprint with .results populated.
    """
    completed: set[str] = set()
    results: dict[str, ChunkResult] = {}
    wave_num = 0

    while True:
        ready = blueprint.get_ready_chunks(completed)
        if not ready:
            break

        wave_num += 1

        if on_event:
            await on_event(EventType.TRANSPORTER_WAVE_START, {
                "wave": wave_num,
                "chunk_ids": [c.chunk_id for c in ready],
                "message": f"Wave {wave_num}: executing {len(ready)} chunks in parallel",
            })

        # Execute all ready chunks in parallel
        wave_tasks = [
            _execute_single_chunk(chunk, blueprint, llm_client, per_chunk_timeout, max_retries)
            for chunk in ready
        ]
        wave_results = await asyncio.gather(*wave_tasks, return_exceptions=True)

        # Collect results
        for chunk, result in zip(ready, wave_results):
            if isinstance(result, Exception):
                result = ChunkResult(
                    chunk_id=chunk.chunk_id,
                    success=False,
                    error=str(result),
                    confidence=1,
                )
            results[chunk.chunk_id] = result
            completed.add(chunk.chunk_id)

            if on_event:
                await on_event(EventType.TRANSPORTER_CHUNK_DONE, {
                    "chunk_id": chunk.chunk_id,
                    "success": result.success,
                    "confidence": result.confidence,
                    "target_file": chunk.target_file,
                    "error": result.error if not result.success else "",
                })

    # Store results on blueprint in chunk order
    blueprint.results = [
        results.get(c.chunk_id, ChunkResult(chunk_id=c.chunk_id, success=False, error="not executed"))
        for c in blueprint.chunks
    ]

    success_count = sum(1 for r in blueprint.results if r.success)
    total = len(blueprint.results)
    logger.info("Matter Stream: %d/%d chunks succeeded", success_count, total)

    if on_event:
        await on_event(EventType.TRANSPORTER_EXECUTION_DONE, {
            "total_chunks": len(blueprint.chunks),
            "successful": success_count,
            "failed": len(blueprint.chunks) - success_count,
            "waves": wave_num,
        })

    return blueprint


def _merge_create_blocks(contents: list[str]) -> str:
    """Merge multiple CREATE block contents for the same file.

    Deduplicates import lines and concatenates the rest.
    First content block (highest confidence) is the base;
    subsequent blocks contribute non-duplicate content.
    """
    if len(contents) == 1:
        return contents[0]

    # Separate imports from body for each content block
    all_imports: list[str] = []  # Ordered, will be deduped
    all_body_parts: list[str] = []

    for content in contents:
        lines = content.split("\n")
        imports: list[str] = []
        body_lines: list[str] = []
        in_body = False

        for line in lines:
            stripped = line.strip()
            if not in_body and (
                stripped.startswith("import ")
                or stripped.startswith("from ")
                or stripped == ""
                or stripped.startswith("#")
            ):
                if stripped.startswith("import ") or stripped.startswith("from "):
                    imports.append(line)
                # Skip blank lines and comments in import section
            else:
                in_body = True
                body_lines.append(line)

        all_imports.extend(imports)
        body_text = "\n".join(body_lines).strip()
        if body_text:
            all_body_parts.append(body_text)

    # Deduplicate imports while preserving order
    seen_imports: set[str] = set()
    unique_imports: list[str] = []
    for imp in all_imports:
        normalized = imp.strip()
        if normalized not in seen_imports:
            seen_imports.add(normalized)
            unique_imports.append(imp)

    # Reassemble: imports, blank line, body parts separated by double newlines
    parts: list[str] = []
    if unique_imports:
        parts.append("\n".join(unique_imports))
    if all_body_parts:
        parts.append("\n\n".join(all_body_parts))

    return "\n\n".join(parts) + "\n"


def assemble_chunks(blueprint: BuildBlueprint) -> list[dict[str, Any]]:
    """Assemble chunk results into unified file-block list (Rematerializer).

    Takes the ChunkResults from execute_chunks() and merges them into the
    same format that _parse_file_blocks() produces, so the existing
    execute_approved_build() pipeline works unchanged.

    Handles:
    - Multiple chunks targeting the same file (merged)
    - Import deduplication for CREATE mode files
    - Confidence-weighted conflict resolution
    - Failed chunks are skipped (partial assembly)

    Args:
        blueprint: Blueprint with .results populated by execute_chunks().

    Returns:
        list[dict] in _parse_file_blocks() format, ready for execute_approved_build().
    """
    # Collect file blocks from all successful chunks, tagged with source chunk
    tagged_blocks: list[tuple[dict[str, Any], ChunkResult]] = []

    for result in blueprint.results:
        if not result.success:
            logger.warning("Assembler: skipping failed chunk %s: %s", result.chunk_id, result.error)
            continue

        blocks = BuilderAgent._parse_file_blocks(result.generated_code)
        if not blocks:
            logger.warning("Assembler: chunk %s succeeded but produced no file blocks", result.chunk_id)
            continue

        for block in blocks:
            tagged_blocks.append((block, result))

    if not tagged_blocks:
        logger.warning("Assembler: no file blocks from any chunk")
        return []

    # Group by (path, mode)
    from collections import defaultdict
    creates: dict[str, list[tuple[dict[str, Any], ChunkResult]]] = defaultdict(list)
    modifies: dict[str, list[tuple[dict[str, Any], ChunkResult]]] = defaultdict(list)

    for block, result in tagged_blocks:
        if block["mode"] == "create":
            creates[block["path"]].append((block, result))
        else:  # modify
            modifies[block["path"]].append((block, result))

    merged: list[dict[str, Any]] = []

    for path, block_results in creates.items():
        if len(block_results) == 1:
            # Single chunk — use as-is
            merged.append(block_results[0][0])
        else:
            # Multiple chunks creating the same file — merge
            # Sort by confidence (highest first)
            block_results.sort(key=lambda br: br[1].confidence, reverse=True)
            merged_content = _merge_create_blocks(
                [br[0]["content"] for br in block_results]
            )
            merged.append({
                "path": path,
                "content": merged_content,
                "mode": "create",
                "after_line": None,
            })

    for path, block_results in modifies.items():
        # Sort by confidence (highest first)
        block_results.sort(key=lambda br: br[1].confidence, reverse=True)
        all_replacements: list[dict[str, str]] = []
        for block, _result in block_results:
            all_replacements.extend(block.get("replacements", []))

        if all_replacements:
            merged.append({
                "path": path,
                "mode": "modify",
                "replacements": all_replacements,
            })

    logger.info(
        "Assembler: produced %d file blocks from %d successful chunks (%d skipped)",
        len(merged),
        sum(1 for r in blueprint.results if r.success),
        sum(1 for r in blueprint.results if not r.success),
    )
    return merged


def assembly_summary(blueprint: BuildBlueprint) -> dict[str, Any]:
    """Produce a summary of the assembly for logging and HXI display.

    Returns a dict with chunk statuses, per-file attribution,
    and overall success metrics.
    """
    chunk_statuses: list[dict[str, Any]] = []
    for chunk, result in zip(blueprint.chunks, blueprint.results):
        chunk_statuses.append({
            "chunk_id": chunk.chunk_id,
            "description": chunk.description,
            "target_file": chunk.target_file,
            "success": result.success,
            "confidence": result.confidence,
            "error": result.error,
            "tokens_used": result.tokens_used,
        })

    return {
        "total_chunks": len(blueprint.chunks),
        "successful": sum(1 for r in blueprint.results if r.success),
        "failed": sum(1 for r in blueprint.results if not r.success),
        "total_tokens": sum(r.tokens_used for r in blueprint.results),
        "avg_confidence": (
            sum(r.confidence for r in blueprint.results if r.success)
            / max(1, sum(1 for r in blueprint.results if r.success))
        ),
        "chunks": chunk_statuses,
    }


async def _emit_transporter_events(
    rt: Any,
    build_id: str,
    blueprint: BuildBlueprint,
    assembled_blocks: list,
    validation_result: Any,
) -> None:
    """Emit summary transporter events for HXI display.

    Called after the transporter pipeline completes. Emits assembly
    and validation results so the UI can display the full chunk lifecycle.
    """
    rt.emit_event(EventType.TRANSPORTER_ASSEMBLED, {
        "build_id": build_id,
        "file_count": len(assembled_blocks),
        "summary": assembly_summary(blueprint),
    })

    rt.emit_event(EventType.TRANSPORTER_VALIDATED, {
        "build_id": build_id,
        "valid": validation_result.valid,
        "errors": validation_result.errors,
        "warnings": validation_result.warnings,
        "checks_passed": validation_result.checks_passed,
        "checks_failed": validation_result.checks_failed,
    })


def _should_use_transporter(spec: BuildSpec, context_size: int = 0) -> bool:
    """Decide whether to use the Transporter Pattern for this build.

    Uses Transporter when the build is complex enough that parallel chunk
    generation would outperform single-pass generation. Falls back to
    single-pass for small, simple builds.

    Args:
        spec: The BuildSpec describing what to build.
        context_size: Total character count of target file contents (0 if unknown).

    Returns:
        True if Transporter should be used.
    """
    # Multiple target files → Transporter
    if len(spec.target_files) > 2:
        return True

    # Large context → Transporter
    if context_size > 20_000:  # ~500 lines, matches _LOCALIZE_THRESHOLD
        return True

    # Multiple test files alongside implementation → Transporter
    if len(spec.target_files) >= 1 and len(spec.test_files) >= 1:
        # At least 2 distinct concerns (impl + tests)
        if len(spec.target_files) + len(spec.test_files) > 2:
            return True

    return False


def _should_use_visiting_builder(
    spec: BuildSpec,
    hebbian_router: Any | None = None,
    force_native: bool = False,
    force_visiting: bool = False,
) -> bool:
    """Decide whether to route to the visiting Copilot Builder (AD-353).

    Decision factors (in priority order):
    1. force_native / force_visiting overrides
    2. Copilot SDK availability
    3. Hebbian weight comparison (if enough history)
    4. Default: prefer visiting (bootstrap phase)
    """
    if force_native:
        return False
    if force_visiting:
        return True

    from probos.cognitive.copilot_adapter import CopilotBuilderAdapter

    if not CopilotBuilderAdapter.is_available():
        return False

    if hebbian_router is not None:
        from probos.mesh.routing import REL_BUILDER_VARIANT

        try:
            visiting_weight = hebbian_router.get_weight(
                "build_code", "visiting", rel_type=REL_BUILDER_VARIANT,
            )
            native_weight = hebbian_router.get_weight(
                "build_code", "native", rel_type=REL_BUILDER_VARIANT,
            )
            # Only compare if both have enough history
            if visiting_weight > 0.1 and native_weight > 0.1:
                return visiting_weight > native_weight
        except (TypeError, AttributeError):
            pass  # Mock or incompatible router — skip Hebbian comparison

    # Bootstrap default: prefer visiting (more capable with MCP tools)
    return True


async def transporter_build(
    spec: BuildSpec,
    llm_client: BaseLLMClient,
    work_dir: str | None = None,
    codebase_index: CodebaseIndex | None = None,
    on_event: Callable | None = None,
) -> list[dict[str, Any]]:
    """Run the full Transporter Pattern pipeline and return file blocks.

    Orchestrates: Blueprint → Decompose → Execute → Assemble → Validate.
    Returns the same list[dict] format as BuilderAgent._parse_file_blocks(),
    ready for execute_approved_build().

    On validation failure, logs warnings but still returns the assembled blocks
    (the downstream test-fix loop in execute_approved_build handles errors).
    On total failure (no chunks succeed), returns an empty list.

    Args:
        spec: BuildSpec describing the build.
        llm_client: LLM client (must support .complete() for deep tier
                    and fast-tier decomposition).
        work_dir: Project root directory.
        codebase_index: Optional CodebaseIndex for import/structure analysis.
        on_event: Optional async callback for HXI events.

    Returns:
        list[dict] of file blocks in _parse_file_blocks() format.
    """
    # Step 1: Create Blueprint
    blueprint = create_blueprint(spec)

    # Step 2: Decompose into chunks
    blueprint = await decompose_blueprint(
        blueprint, llm_client,
        codebase_index=codebase_index,
        work_dir=work_dir,
        on_event=on_event,
    )

    if not blueprint.chunks:
        logger.warning("Transporter: decomposition produced no chunks, aborting")
        return []

    # Step 3: Execute chunks in parallel waves
    blueprint = await execute_chunks(
        blueprint, llm_client,
        on_event=on_event,
    )

    # Step 4: Assemble results
    assembled = assemble_chunks(blueprint)

    if not assembled:
        logger.warning("Transporter: assembly produced no file blocks")
        return []

    # Step 5: Validate
    validation = validate_assembly(blueprint, assembled)

    # Emit HXI events for assembly + validation
    if on_event:
        class _EventEmitter:
            # BF-253: AD-680 migrated _emit_transporter_events to rt.emit_event().
            # This shim must expose the public name to match the helper's contract.
            # The legacy private name is kept for any other consumers.
            def emit_event(self_, event_type, data):
                asyncio.create_task(on_event(event_type, data))

            def _emit_event(self_, event_type, data):
                asyncio.create_task(on_event(event_type, data))
        await _emit_transporter_events(_EventEmitter(), "", blueprint, assembled, validation)

    if not validation.valid:
        logger.warning(
            "Transporter: validation found %d error(s): %s",
            len(validation.errors),
            "; ".join(e.get("message", "") for e in validation.errors[:3]),
        )
        # Still return blocks — the test-fix loop downstream will catch real issues

    logger.info(
        "Transporter: pipeline complete — %d file blocks, %d/%d chunks succeeded, valid=%s",
        len(assembled),
        sum(1 for r in blueprint.results if r.success),
        len(blueprint.chunks),
        validation.valid,
    )

    return assembled


def _find_chunk_for_file(blueprint: BuildBlueprint, file_path: str) -> str:
    """Return the chunk_id of the chunk targeting the given file.

    If multiple chunks target it, returns the first. If none, returns "".
    Handles relative vs absolute paths via suffix matching.
    """
    for chunk in blueprint.chunks:
        if chunk.target_file == file_path or file_path.endswith(chunk.target_file):
            return chunk.chunk_id
    return ""


def _find_unresolved_names(source: str) -> list[str]:
    """Find names used but not defined locally in Python source (best-effort).

    Uses ast to collect defined names (defs, imports, assignments, params)
    and used names (Name nodes in Load context). Returns sorted list of
    names that are used but not defined, excluding builtins and common types.
    Conservative — better to miss an issue than false-positive.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    # Collect defined names
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
            for arg in node.args.args:
                defined.add(arg.arg)
            if node.args.vararg:
                defined.add(node.args.vararg.arg)
            if node.args.kwarg:
                defined.add(node.args.kwarg.arg)
            for arg in node.args.kwonlyargs:
                defined.add(arg.arg)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                defined.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
                elif isinstance(target, ast.Tuple):
                    for elt in target.elts:
                        if isinstance(elt, ast.Name):
                            defined.add(elt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                    defined.add(item.optional_vars.id)
        elif isinstance(node, ast.comprehension) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)

    # Collect used names
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)

    # Builtins and common safe names to exclude
    import builtins as _builtins_mod
    builtins_names = set(dir(_builtins_mod))
    safe_names = builtins_names | {
        "__name__", "__file__", "__all__", "__doc__", "__spec__",
        "self", "cls", "super",
        "Any", "Optional", "Union", "Dict", "List", "Set", "Tuple",
        "Type", "Callable", "Iterator", "Generator", "Awaitable",
        "Sequence", "Mapping", "Iterable",
        "annotations",
    }

    return sorted(used - defined - safe_names)


def validate_assembly(
    blueprint: BuildBlueprint,
    assembled_blocks: list[dict[str, Any]],
) -> ValidationResult:
    """Validate assembled file blocks for interface consistency (Heisenberg Compensator).

    Runs static analysis checks on the assembled output:
    1. Python syntax validity for CREATE blocks
    2. Duplicate top-level definitions
    3. Non-empty search strings in MODIFY replacements
    4. Interface contract satisfaction
    5. Stricter unresolved-name checking for low-confidence chunks

    Zero-LLM — pure ast + string processing.
    """
    result = ValidationResult()
    checks_run = 0

    # Collect all top-level defs across all CREATE blocks for contract checking
    all_top_level_names: set[str] = set()

    # Check 1 & 2: Syntax validity and duplicate definitions for CREATE .py blocks
    for block in assembled_blocks:
        if block["mode"] != "create" or not block["path"].endswith(".py"):
            continue

        content = block["content"]
        chunk_id = _find_chunk_for_file(blueprint, block["path"])
        checks_run += 1

        # Check 1: Syntax validity
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            result.errors.append({
                "type": "syntax_error",
                "message": str(e),
                "file": block["path"],
                "chunk_id": chunk_id,
            })
            continue  # Can't check defs if syntax is broken

        # Check 2: Duplicate top-level definitions
        top_names: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top_names.append(node.name)
            elif isinstance(node, ast.ClassDef):
                top_names.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        top_names.append(target.id)

        all_top_level_names.update(top_names)
        checks_run += 1

        from collections import Counter
        counts = Counter(top_names)
        for name, count in counts.items():
            if count > 1:
                result.errors.append({
                    "type": "duplicate_definition",
                    "message": f"'{name}' defined {count} times",
                    "file": block["path"],
                    "chunk_id": chunk_id,
                })

    # Check 3: Empty search strings in MODIFY blocks
    for block in assembled_blocks:
        if block["mode"] != "modify":
            continue
        chunk_id = _find_chunk_for_file(blueprint, block["path"])
        for replacement in block.get("replacements", []):
            checks_run += 1
            if not replacement["search"].strip():
                result.errors.append({
                    "type": "empty_search",
                    "message": "Empty search string in replacement",
                    "file": block["path"],
                    "chunk_id": chunk_id,
                })

    # Check 4: Interface contracts
    for contract in blueprint.interface_contracts:
        checks_run += 1
        # Extract function/class name from contract string
        name_match = re.search(r"(?:def|class)\s+(\w+)", contract)
        if name_match:
            func_name = name_match.group(1)
            if func_name not in all_top_level_names:
                result.warnings.append({
                    "type": "unmet_contract",
                    "message": f"Interface contract '{contract}' not found in assembled code",
                    "file": "",
                    "chunk_id": "",
                })

    # Check 5: Stricter checking for low-confidence chunks
    for result_obj in blueprint.results:
        if result_obj.success and result_obj.confidence <= 2:
            # Find blocks from this chunk
            matching_chunk = None
            for chunk in blueprint.chunks:
                if chunk.chunk_id == result_obj.chunk_id:
                    matching_chunk = chunk
                    break
            if not matching_chunk:
                continue

            for block in assembled_blocks:
                if block["mode"] != "create" or not block["path"].endswith(".py"):
                    continue
                if block["path"] != matching_chunk.target_file and not block["path"].endswith(matching_chunk.target_file):
                    continue
                checks_run += 1
                unresolved = _find_unresolved_names(block["content"])
                for name in unresolved:
                    result.warnings.append({
                        "type": "unresolved_name",
                        "message": f"Name '{name}' used but not defined/imported (low-confidence chunk)",
                        "file": block["path"],
                        "chunk_id": result_obj.chunk_id,
                    })

    result.valid = len(result.errors) == 0
    result.chunks_validated = sum(1 for r in blueprint.results if r.success)
    result.checks_failed = len(result.errors)
    result.checks_passed = checks_run - result.checks_failed

    return result


# ---------------------------------------------------------------------------
# Git helpers (AD-303) — async only, no subprocess import
# ---------------------------------------------------------------------------

def _sanitize_branch_name(name: str) -> str:
    """Lowercase, alphanum + hyphens, max 50 chars."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return slug[:50]


#: BF-892 (#1543): the names the builder's git launches add to the allowlist. Git for Windows
#: reads HOME before USERPROFILE (Git Bash sets it); without it a commit can lose the identity
#: in ~/.gitconfig and a globally ignored file makes a clean tree look dirty. XDG_CONFIG_HOME
#: is git's other global-config location. Neither name is credential-shaped.
_GIT_HOME_NAMES: tuple[str, ...] = ("HOME", "XDG_CONFIG_HOME")


async def _run_git(args: list[str], work_dir: str, *, lossless: bool = False) -> tuple[int, str, str]:
    """Run a git command asynchronously.  Returns (returncode, stdout, stderr).

    Uses subprocess.run in a thread executor for Windows compatibility —
    asyncio.create_subprocess_exec requires ProactorEventLoop which
    uvicorn/FastAPI may not provide.

    BF-904a A1: with *lossless*, stdout is decoded with ``surrogateescape`` and not stripped,
    so two outputs are equal exactly when their bytes are. That text can hold lone surrogates:
    it stays in memory, or passes through ``_display_token`` before any message, log or event.
    """

    def _sync_run() -> tuple[int, str, str]:
        # BF-892 (#1543): the allowlist. This git runs in the tree the model writes
        # into, so its config and hooks are not ProbOS's own; these local verbs need
        # only PATH and the home variables (identity from ~/.gitconfig), HOME included.
        result = subprocess.run(
            ["git", *HARDENED_GIT_CONFIG_ARGS, *args],  # BF-904a: no repository hook or fsmonitor runs
            env=build_command_env(_GIT_HOME_NAMES),
            cwd=work_dir,
            capture_output=True,
        )
        stdout = result.stdout or b""
        return (
            result.returncode,
            stdout.decode(errors="surrogateescape") if lossless else stdout.decode(errors="replace").strip(),  # BF-904a A1: lossless only on request
            (result.stderr or b"").decode(errors="replace").strip(),
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_run)


async def _git_current_branch(work_dir: str) -> str | None:
    """BF-904a (#1585): the branch HEAD names, or None when HEAD is detached or unreadable.

    ``rev-parse --abbrev-ref HEAD`` printed ``HEAD`` for a detached checkout, and a failure
    fell back to ``main``; neither is the ref a failed build must return to.
    """
    # BF-904a A4 (D33): a valid ref may end in Unicode whitespace (U+00A0) that the default decode's
    # strip() would cut, and the return would then check out a different, existing branch.
    # BF-904a A7 (D40): the full ref. --short prints "heads/<name>" when a tag shares the name, and
    # checking that out detaches HEAD. Only a local branch is a branch; any other target is None.
    rc, out, _err = await _run_git(["symbolic-ref", "-q", "HEAD"], work_dir, lossless=True)  # BF-904a A7 (D40): the full ref, never git's disambiguated short name
    out = out.removesuffix("\n")  # BF-904a A4 (D33): only the LF git ends the line with
    out = out.removeprefix("refs/heads/") if out.startswith("refs/heads/") else ""  # BF-904a A7 (D40): a local branch's name, or none
    return out if rc == 0 and out else None  # BF-904a: never a guessed "main"


#: BF-904a A7 (D39): the bytes a process argument reaches git as. On POSIX, subprocess passes
#: os.fsencode's bytes. On Windows the argument travels as UTF-16 and git turns a lone surrogate
#: into U+FFFD; os.fsencode there (surrogatepass) differs from the printed bytes for exactly those
#: names. A module seam, so a test models either host without patching os.
_argv_bytes = os.fsencode


def _ref_survives_argv(name: str) -> bool:
    """BF-904a A7 (D39): whether git receives *name* as the bytes it printed it as (UTF-8, surrogateescape)."""
    try:
        return _argv_bytes(name) == name.encode("utf-8", "surrogateescape")  # BF-904a A7 (D39): the bytes git printed
    except UnicodeError:  # a name this host cannot encode cannot be passed
        return False


async def _git_head_commit(work_dir: str) -> str | None:
    """BF-904a: the commit a detached HEAD is at, or None when there is none."""
    rc, out, _err = await _run_git(["rev-parse", "--verify", "-q", "HEAD^{commit}"], work_dir)
    return out if rc == 0 and out else None


async def _git_create_branch(branch_name: str, work_dir: str) -> tuple[bool, str]:
    """Create and checkout a new git branch.  Returns (success, message)."""
    safe = _sanitize_branch_name(branch_name)
    # BF-904a A4 (D31): an existing branch of this name is never deleted. The name comes from the
    # spec title, so it may hold a successful build's commit; the build is refused before any write.
    # A branch a crash left, or one a failed return kept, is the Captain's to delete.
    # BF-904a A5 (D36): ask for the full ref name and compare it exactly: no marker or colour to strip,
    # and an answer naming any other ref (or a fake runner's "main") is not a collision.
    _, list_out, _ = await _run_git(["branch", "--list", "--format=%(refname)", safe], work_dir)  # BF-904a A5 (D36): exact ref names only
    if f"refs/heads/{safe}" in list_out.splitlines():  # BF-904a A5 (D36): this exact branch exists
        return False, f"branch {safe} already exists; it is kept: merge or delete it, or give the build another title"  # BF-904a A4 (D31): never delete a branch this build did not create
    rc, out, err = await _run_git(["checkout", "-b", safe], work_dir)
    if rc != 0:
        return False, err or out
    return True, safe


async def _git_add_and_commit(
    files: list[str], message: str, work_dir: str,
) -> tuple[bool, str]:
    """Stage *files* and commit.  Returns (success, commit_hash_or_error)."""
    # BF-894 (#1547): "--" so a model-authored name beginning with "-" is a path, not an option.
    rc, _out, err = await _run_git(["add", "--", *files], work_dir)
    if rc != 0:
        return False, err

    rc, out, err = await _run_git(["commit", "-m", message], work_dir)
    if rc != 0:
        return False, err or out

    # Get commit hash
    rc2, sha, _ = await _run_git(["rev-parse", "--short", "HEAD"], work_dir)
    return True, sha if rc2 == 0 else "unknown"


async def _git_return_to(branch: str | None, commit: str | None, work_dir: str) -> tuple[bool, str]:
    """BF-904a (#1585): check out the ref a build started from. Returns (success, detail).

    *branch* when the build started on one, otherwise *commit*, detached. Replaces
    ``_git_checkout_main``, which always switched to ``main``: from another branch that moved
    the operator, and in a linked worktree whose ``main`` is checked out elsewhere it failed.
    Never raises.
    """
    if branch is not None:
        args = ["checkout", "-q", branch, "--"]
    elif commit is not None:
        args = ["checkout", "-q", "--detach", commit, "--"]
    else:
        return False, "no branch or commit to return to"
    try:
        rc, out, err = await _run_git(args, work_dir)
    except Exception as exc:  # BF-904a A4 (D34): any ordinary failure is a failed return; BaseException propagates
        return False, f"git checkout could not start ({type(exc).__name__})"
    if rc != 0:
        return False, (err or out or f"git checkout exited {rc}")[:300]
    return True, branch if branch is not None else str(commit)


async def _cleanup_git(args: list[str], work_dir: str) -> str | None:
    """BF-904a: one cleanup git command; its failure as text, or None on success. Never raises."""
    try:
        rc, out, err = await _run_git(args, work_dir)
    except Exception as exc:  # BF-904a A4 (D34): reported, and the cleanup goes on; BaseException propagates
        return f"git {args[0]} could not start ({type(exc).__name__})"
    if rc != 0:
        return f"git {args[0]} exited {rc}: {_display_token(err or out, _DISPLAY_PATH_CHARS)}"  # BF-904a A3: git's answer, escaped and bounded
    return None


def _cleanup_log(level: int, msg: str, *args: object) -> None:
    """BF-904a A8 (D43): one cleanup log line that cannot stop the cleanup.

    ``Handler.handle`` calls ``emit`` unguarded, so a handler whose ``emit`` raises would skip the
    remaining deletions and the return. The failure is dropped: the same logger would raise again,
    and the cleanup's outcome is carried by ``cleanup_errors``.
    """
    try:
        logger.log(level, msg, *args, stacklevel=2)  # BF-904a A8 (D43): the record names the cleanup step that logged it
    except Exception:  # BF-904a A8 (D43): a raising handler loses one log line, never a cleanup step; BaseException propagates
        pass


def _restore_pre_build_files(work_dir: str, originals: dict[str, bytes], created: list[str]) -> list[str]:
    """BF-904a (#1585): put the tree back as the build found it, with no git.

    Writes each saved file back byte for byte, then deletes each file the build created and its
    emptied parent directories. Runs no git, so no filter or attribute planted in the tree runs.
    Returns one message per path it could not put back (each name a `_display_token`, A3); never raises.
    """
    errors: list[str] = []
    root = Path(work_dir)
    # BF-904a A4 (D32): newest snapshot first. Where two spellings of one file were both saved (a hard
    # link; case on a case-folding POSIX filesystem), the first snapshot is written last and wins.
    for rel, data in reversed(originals.items()):  # BF-904a A4 (D32): the first snapshot of a file wins
        try:
            (root / rel).write_bytes(data)
        except Exception as exc:  # BF-904a A4 (D34): a failed restore is reported; the other paths go on
            errors.append(f"could not restore {_display_token(rel, _DISPLAY_PATH_CHARS)} ({type(exc).__name__})")  # BF-904a A3: escaped and bounded
    for created_path in created:
        full = root / created_path
        try:
            if not full.exists():  # BF-904a A4 (D34): inside the try, so a failed check is a failed delete
                continue
            full.unlink()
        except Exception as exc:  # BF-904a A4 (D34): a failed check or delete is reported; the other paths go on
            errors.append(f"could not delete {_display_token(created_path, _DISPLAY_PATH_CHARS)} ({type(exc).__name__})")  # BF-904a A3: escaped and bounded
            continue
        _cleanup_log(logging.INFO, "Cleaned up untracked file from failed build: %s", _display_token(created_path, _DISPLAY_PATH_CHARS))  # BF-904a A3, A8 (D43): one log line that cannot stop the cleanup
        # Remove empty parent dirs up to work_dir
        parent = full.parent
        try:
            while parent != root and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except Exception:  # BF-904a A7 (D42): an empty directory left is invisible to git; the deletions and the return go on. BaseException propagates
            pass  # Directory not empty or permission issue
    return errors


def _write_target_key(work_dir: str, rel: str) -> str:
    """BF-904a A4 (D32): one key per file a build writes, whatever accepted spelling names it.

    ``repository_identity``'s normalisation: ``realpath`` drops ``.`` components, unifies separators
    and resolves symbolic links; ``normcase`` folds case where the host does (Windows). A hard link,
    or case on a case-folding POSIX filesystem, still gets a second key; the restore's newest-first
    order makes the first snapshot win there too.
    """
    return os.path.normcase(os.path.realpath(os.path.join(work_dir, rel)))


def _first_found(work_dir: str, rel: str, found: set[str]) -> bool:
    """BF-904a A4 (D32): True, recording the file in *found*, the first time a build saves it."""
    key = _write_target_key(work_dir, rel)
    if key in found:  # BF-904a A4 (D32): already saved under another spelling
        return False
    found.add(key)
    return True


async def repository_identity(work_dir: str) -> str | None:
    """BF-896: the repository *work_dir* names, as git resolves it, or None.

    ``git rev-parse --absolute-git-dir`` follows a linked worktree's ``.git``
    pointer file, so rewriting that file changes the answer. The value is
    normalized (real path, OS case) so two captures compare with ``==``. None
    means it could not be determined; a caller pinning identity refuses on None.
    """
    try:
        rc, out, _err = await _run_git(["rev-parse", "--absolute-git-dir"], work_dir)
    except (OSError, ValueError):
        return None
    if rc != 0 or not out:
        return None
    try:
        return os.path.normcase(os.path.realpath(out))
    except (OSError, ValueError):
        return None


#: BF-904a (#1585): the listing of every config source git resolves for a tree (system, global,
#: the repository's shared config, config.worktree, every include). Its values never leave memory.
_GIT_CONFIG_LISTING_ARGS: tuple[str, ...] = ("config", "--list", "--show-origin", "-z")
#: BF-904a A1: a resolved config is kilobytes (git documents about a thousand keys). Its comparison
#: and name parse run on the event loop, so a listing past 4 Mi characters is a failed capture.
_GIT_CONFIG_LISTING_MAX_CHARS = 4 * 1024 * 1024
#: BF-904a A1: the bounds of one hooks listing (`_hooks_listing`, run in a worker thread). git knows
#: about 30 hook names and `git init` writes 14 samples, so 256 entries is several full directories;
#: a directory of thousands stops at the 257th name. Past a bound the listing is a failed capture
#: (D6): the build is refused, never committed on a partial listing.
_HOOKS_MAX_ENTRIES = 256
#: Hook scripts are kilobytes and a compiled hook a few megabytes; hashing 64 MiB takes well under a
#: second off the event loop.
_HOOKS_MAX_TOTAL_BYTES = 64 * 1024 * 1024
#: One read: the most of a hook file held in memory at once.
_HOOKS_READ_CHUNK = 64 * 1024
#: The one open of a regular entry: bytes on Windows; on POSIX never follow a link, nor block on a
#: pipe, swapped in after the lstat. A flag the platform lacks is 0, a no-op.
_HOOK_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
#: BF-904a A1: how much of a name a refusal shows (`_display_token`). git's keys and hook names are
#: under 50 characters, so 100 keeps every real one whole; a path is cut at 200. With at most 10
#: names of each kind, a refusal's whole text stays under 6,000 characters.
_DISPLAY_NAME_CHARS = 100
_DISPLAY_PATH_CHARS = 200
_GIT_CHANGE_NAMES_SHOWN = 10


@dataclass(frozen=True)
class _GitSafetySnapshot:
    """BF-904a (#1585): what git would run on its own in a tree, read before model code runs."""

    # BF-904a A1: the lossless `git config --list --show-origin -z` listing. Global config can hold
    # credentials and the text can hold lone surrogates, so it is kept out of repr and never formatted.
    config: str = field(repr=False)
    hooks_dir: Path | None  # the repository's own hooks directory; None when no repository was shown at entry
    hooks: tuple[tuple[str, str], ...]  # (entry name, its `_hooks_listing` token), by name


def _escaped_char(ch: str) -> str:
    """BF-904a A1: one character as a Python escape."""
    code = ord(ch)
    if ch == "\\":
        return "\\\\"
    if code < 0x100:
        return f"\\x{code:02x}"
    if code < 0x10000:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"


def _display_token(text: str, limit: int) -> str:
    """BF-904a A1: *text* as one inline-code token, safe in a log record, an event and Markdown.

    Every character that is not printable (controls, line and paragraph separators, format
    characters such as bidi overrides, lone surrogates), and the backslash and the backtick, is a
    Python escape: the token is one line, encodes as UTF-8, and cannot close its code span, inside
    which Markdown is literal. At most *limit* characters of the escaped form are kept, never half
    an escape; the rest are counted, not shown.
    """
    shown: list[str] = []
    width = 0
    for index, ch in enumerate(text):
        piece = ch if ch.isprintable() and ch not in "\\`" else _escaped_char(ch)
        if width + len(piece) > limit:
            return "`" + "".join(shown) + f"` ...[{len(text) - index} more characters]"
        shown.append(piece)
        width += len(piece)
    return "`" + "".join(shown) + "`"


def _listed(names: list[str], total: int) -> str:
    """BF-904a A1: *names* (the first escaped tokens) joined, then how many of *total* were not shown."""
    hidden = total - len(names)
    return ", ".join(names) + (f", ...[{hidden} more]" if hidden > 0 else "")


def _hooks_listing(hooks_dir: Path | None) -> tuple[tuple[str, str], ...] | None:
    """BF-904a: each entry of *hooks_dir* with a token for what git could run from it, or None.

    Read in Python, so no git runs; it blocks, so the build calls it through `_read_hooks`.
    A1: each entry is classified by `os.lstat`, never followed. A regular file is
    ``file:<permission bits>:<sha256>`` (the bits, because a chmod makes a present file run), a
    symlink ``link:<target>``, a directory ``dir``, anything else (a pipe, a device, a socket)
    ``other:<file type>``; only regular files are opened. A missing directory is an empty
    listing. An unreadable directory or entry, an entry that is no longer a regular file when
    opened, more than _HOOKS_MAX_ENTRIES entries, or more than _HOOKS_MAX_TOTAL_BYTES bytes in
    all is None, which the caller counts as a change (D6).
    """
    if hooks_dir is None:
        return ()
    names: list[str] = []
    try:
        with os.scandir(hooks_dir) as scan:
            for entry in scan:
                names.append(entry.name)
                if len(names) > _HOOKS_MAX_ENTRIES:  # BF-904a A1: a directory past the entry bound is a failed capture
                    return None
    except FileNotFoundError:
        return ()
    except OSError:
        return None
    listing: list[tuple[str, str]] = []
    total = 0
    try:
        for name in sorted(names):
            path = os.path.join(hooks_dir, name)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):  # BF-904a A1: a link is recorded by its target, never followed
                token = "link:" + os.readlink(path)
            elif stat.S_ISDIR(st.st_mode):
                token = "dir"
            elif not stat.S_ISREG(st.st_mode):  # BF-904a A1: a pipe or device is never opened
                token = f"other:{stat.S_IFMT(st.st_mode):o}"
            else:
                digest = hashlib.sha256()
                fd = os.open(path, _HOOK_OPEN_FLAGS)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):  # BF-904a A1: no longer a regular file when opened
                        return None
                    while chunk := os.read(fd, _HOOKS_READ_CHUNK):
                        total += len(chunk)
                        if total > _HOOKS_MAX_TOTAL_BYTES:  # BF-904a A1: past the byte bound is a failed capture
                            return None
                        digest.update(chunk)
                finally:
                    os.close(fd)
                token = f"file:{stat.S_IMODE(st.st_mode):o}:{digest.hexdigest()}"
            listing.append((name, token))
    except OSError:
        return None
    return tuple(listing)


async def _read_hooks(hooks_dir: Path | None) -> tuple[tuple[str, str], ...] | None:
    """BF-904a A1: `_hooks_listing` in a worker thread, so the build's event loop never blocks on it.

    The thread cannot be interrupted; the listing's bounds keep it short. If the awaiting build is
    cancelled, the thread finishes and its result is dropped; `git_unsafe` is already set, so the
    `finally` block runs no git (D23).
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _hooks_listing, hooks_dir)  # BF-904a A1: off the event loop


def _config_change_names(before: str, after: str) -> str:
    """BF-904a: the sources and keys whose entries differ between two `-z` listings, never a value.

    A1: at most _GIT_CHANGE_NAMES_SHOWN of them, each origin and key a `_display_token`, so no
    control character, lone surrogate or 20,000-character subsection reaches a message raw.
    """

    def entries(listing: str) -> set[tuple[str, str]]:
        fields = listing.split("\0")
        return {(fields[i], fields[i + 1]) for i in range(0, len(fields) - 1, 2)}

    keys = sorted({(origin, entry.split("\n", 1)[0]) for origin, entry in entries(before) ^ entries(after)})
    names = [_display_token(origin, _DISPLAY_PATH_CHARS) + " " + _display_token(key, _DISPLAY_NAME_CHARS) for origin, key in keys[:_GIT_CHANGE_NAMES_SHOWN]]  # BF-904a A1: escaped and bounded
    return f"({_listed(names, len(keys))})" if names else "(the listing changed)"


async def _git_safety_snapshot(work_dir: str, repository_proven: bool) -> _GitSafetySnapshot | None:
    """BF-904a (#1585): the resolved git config and the hooks directory of *work_dir*, or None.

    None means the config listing or the hooks directory could not be read; the comparison
    after the tests counts that as a change. A1: the listing is read lossless, so equal text
    means equal bytes. *repository_proven* is True when an identity was pinned before any model
    code ran; then a hooks location git does not name is a failed capture too.
    """
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir, lossless=True)  # BF-904a A1: lossless baseline
        if rc != 0 or len(config) > _GIT_CONFIG_LISTING_MAX_CHARS:  # BF-904a A1: a listing past its bound is a failed capture
            return None
        rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir, lossless=True)  # BF-904a A2: byte-exact: a directory name may end in whitespace
        common_dir = common_dir.removesuffix("\n")  # BF-904a A2: git ends its answer with one newline; nothing else is trimmed
    except (OSError, ValueError):
        return None
    # `--git-common-dir`, not `--git-path hooks`: under the core.hooksPath override the latter
    # names the null device.
    if rc == 0 and common_dir:  # BF-904a A1: git named the common directory
        hooks_dir: Path | None = Path(work_dir, common_dir, "hooks")
    elif repository_proven:  # BF-904a A1: a repository whose hooks location is unreadable is a failed capture
        return None
    else:
        # D5: no identity was pinned at entry, so no repository was shown and there is no hooks
        # directory to watch; a repository appearing during the tests changes the config listing.
        hooks_dir = None
    hooks = await _read_hooks(hooks_dir)
    if hooks is None:
        return None
    return _GitSafetySnapshot(config=config, hooks_dir=hooks_dir, hooks=hooks)


async def _git_safety_change(work_dir: str, before: _GitSafetySnapshot | None) -> str | None:
    """BF-904a (#1585): what changed since *before* in the config git resolves or the hooks directory.

    None when nothing changed. A capture that failed, before the tests or now, is a change: git
    is not run again when it cannot be shown to be as it was. The text names config sources and
    keys and hook file names only, never a value or a file's content; A1: each name is a
    `_display_token`, so the text is fixed words plus escaped, bounded tokens.
    """
    if before is None:
        return "the git configuration or hooks directory could not be read before the tests"
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir, lossless=True)  # BF-904a A1: lossless comparison
    except (OSError, ValueError):
        rc, config = 1, ""
    if rc != 0 or len(config) > _GIT_CONFIG_LISTING_MAX_CHARS:  # BF-904a A1: past its bound after the tests is a failed capture
        return "the git configuration could not be read after the tests"
    changes: list[str] = []
    if config != before.config:  # BF-904a: a filter, an include or any other config source changed
        changes.append("git config " + _config_change_names(before.config, config))
    hooks = await _read_hooks(before.hooks_dir)
    shown_dir = _display_token(str(before.hooks_dir), _DISPLAY_PATH_CHARS)
    if hooks is None:
        changes.append(
            f"the hooks directory {shown_dir} could not be read (an unreadable or changing entry, "
            f"or more than {_HOOKS_MAX_ENTRIES} entries or {_HOOKS_MAX_TOTAL_BYTES // (1024 * 1024)} MiB)"
        )
    elif hooks != before.hooks:  # BF-904a: a hook file appeared, changed or went away
        changed = sorted({name for name, _token in set(hooks) ^ set(before.hooks)})
        names = [_display_token(name, _DISPLAY_NAME_CHARS) for name in changed[:_GIT_CHANGE_NAMES_SHOWN]]  # BF-904a A1: escaped and bounded
        changes.append(f"hook files in {shown_dir}: " + _listed(names, len(changed)))
    return "; ".join(changes) or None


# ---------------------------------------------------------------------------
# BuilderAgent (AD-302)
# ---------------------------------------------------------------------------

class SoftwareEngineerAgent(CognitiveAgent):
    """SWE crew agent (Scotty) — engineering judgment, quality gates, tool delegation (AD-521).

    Per AD-521 SWE/Build Pipeline Separation Model A, this agent is
    the sovereign crew member that owns build output quality. It
    receives build specs from the Architect, applies engineering
    judgment, selects a tool (native BuildPipeline service, visiting
    Copilot builder, or future agentic-loop harness from AD-543–549),
    validates output against standing-orders quality gates, and
    reports up.

    Identity continuity: agent_type, callsign, pool name, and
    standing-orders mapping are preserved — the rename is class-only.
    `BuilderAgent` is kept as a module-level alias for back-compat
    (16 test files import the name; all keep working unchanged).
    """

    agent_type = "builder"
    tier = "domain"
    _handled_intents = {"build_code"}
    intent_descriptors = [
        IntentDescriptor(
            name="build_code",
            params={
                "title": "Short title for the code change",
                "description": "Detailed specification of what to build",
            },
            description=(
                "Generate code changes from a build specification. "
                "Creates a git branch, writes code, runs tests, and "
                "presents results for Captain approval."
            ),
            requires_consensus=True,
            # Captain approval on the merge is the control, not the mesh vote.
            consensus_mode="external_gate",
            requires_reflect=False,
            tier="domain",
        ),
    ]

    instructions = """You are the Builder Agent for ProbOS, a probabilistic agent-native OS.
Your job is to execute code changes based on build specifications.

When given a build spec:
1. Read the reference files to understand the existing code patterns
2. Plan the changes needed to fulfill the specification
3. Generate the code for EACH target file, following existing patterns exactly
4. Generate test code for the test files specified
5. Present the complete set of file changes

IMPORTANT RULES:
- Follow existing code patterns in the codebase exactly (imports, naming, style)
- Every public function/method needs a test
- Use the same typing patterns as existing code (from __future__ import annotations, etc.)
- Do NOT add features beyond what the spec requests
- Do NOT modify files that aren't listed in target_files or test_files
- Include the AD number in code comments where relevant

TEST WRITING RULES:
- Before writing test fixtures, READ the class __init__ signature in the reference code. Only pass arguments that __init__ accepts. Do not invent keyword arguments.
- Import paths must use the full module path: `from probos.experience.shell import ProbOSShell`, never `from experience.shell import ...`
- Use `_Fake*` stub classes (like _FakeRuntime, _FakeAgent) over complex Mock() chains. Check existing test files for patterns.
- For async methods, use `pytest.mark.asyncio` and `async def test_*`.
- Every mock must cover ALL attributes accessed in the code path under test. Trace the target method body to find every self.x access.
- Test assertions must match the ACTUAL output format of the code you just wrote, not a guessed format.
- Do NOT use emoji in code strings -- they cause encoding crashes on Windows.

OUTPUT FORMAT:
For each file, output a block like:
===FILE: path/to/file.py===
<complete file contents or changes>
===END FILE===

If modifying an existing file, use SEARCH/REPLACE blocks to specify exact changes.
Each SEARCH block must match existing code EXACTLY (including whitespace and indentation).
Multiple changes to the same file go in a single MODIFY block:

===MODIFY: path/to/file.py===
===SEARCH===
<exact existing code to find>
===REPLACE===
<replacement code>
===END REPLACE===
===END MODIFY===

Rules for MODIFY blocks:
- The SEARCH text must match EXACTLY — copy it character-for-character from the reference code
- Keep SEARCH blocks as small as possible — just enough context to be unique
- Order SEARCH/REPLACE pairs from top to bottom in the file
- For new imports, SEARCH for the last existing import line and REPLACE with it plus the new one
- For adding a new method to a class, SEARCH for the preceding method's last line and REPLACE with that line plus the new method
"""

    # -- tier override --------------------------------------------------------

    def _resolve_tier(self) -> str:
        """Builder uses deep tier for code generation quality."""
        return "deep"

    # -- lifecycle overrides --------------------------------------------------

    # Context threshold: if total file content exceeds this, use fast-tier
    # localization to select relevant sections instead of sending everything.
    _LOCALIZE_THRESHOLD: int = 20_000  # chars — ~500 lines of code

    @staticmethod
    def _build_file_outline(content: str, path: str) -> str:
        """Build a compact AST outline of a Python file with line numbers.

        Shows class definitions, method signatures, and important assignments
        so the localization LLM can identify which sections to read in full.
        """
        lines = content.split("\n")
        line_count = len(lines)
        header = f"{path} ({line_count} lines):"

        if not path.endswith(".py"):
            # Non-Python: just show line count and first/last few lines
            preview = lines[:5] + ["  ..."] + lines[-5:] if line_count > 15 else lines
            return header + "\n" + "\n".join(f"  L{i+1}: {l}" for i, l in enumerate(preview))

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return header + "\n  (syntax error — cannot outline)"

        parts = [header]

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue  # Skip individual imports — too noisy

            if isinstance(node, ast.ClassDef):
                parts.append(f"  L{node.lineno}: class {node.name}:")
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = ", ".join(a.arg for a in child.args.args)
                        prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                        parts.append(f"    L{child.lineno}: {prefix} {child.name}({args})")
                    elif isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                parts.append(f"    L{child.lineno}: {target.id} = ...")

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = ", ".join(a.arg for a in node.args.args)
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                parts.append(f"  L{node.lineno}: {prefix} {node.name}({args})")

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        parts.append(f"  L{node.lineno}: {target.id} = ...")

        return "\n".join(parts)

    async def _localize_context(
        self,
        description: str,
        title: str,
        all_files: dict[str, str],
        target_paths: list[str],
    ) -> dict[str, str]:
        """Use fast-tier LLM to select relevant sections from large files.

        Returns a dict of path -> selected content (only relevant sections).
        Falls back to head+tail truncation if localization fails.
        """
        # Build outlines for all files
        outlines = "\n\n".join(
            self._build_file_outline(content, path)
            for path, content in all_files.items()
        )

        localize_prompt = (
            f"# Task: Identify code sections needed for this build\n\n"
            f"## Build: {title}\n{description}\n\n"
            f"## File Outlines\n{outlines}\n\n"
            f"## Instructions\n"
            f"For each file, list the line ranges needed to implement this build.\n"
            f"Include:\n"
            f"- Lines 1-20 (imports) for every file\n"
            f"- Class/dict definitions that need modification\n"
            f"- The area where new code should be inserted (include the method BEFORE and AFTER)\n"
            f"- Any related methods referenced in the description\n"
            f"- Add 5 lines of buffer above and below each range\n\n"
            f"Respond with ONLY a JSON object, no markdown fences:\n"
            f'{{"sections": {{"path/to/file.py": [[start, end], [start2, end2]], ...}}}}'
        )

        try:
            request = LLMRequest(
                prompt=localize_prompt,
                system_prompt="You identify relevant code sections. Return only JSON.",
                tier="fast",
                temperature=0.0,
            )
            response = await self._llm_client.complete(request)

            if response.error:
                logger.warning("Builder localize: LLM error, falling back to truncation: %s", response.error)
                return self._fallback_truncate(all_files)

            # Parse JSON response
            import json
            text = response.content.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text
                text = text.rsplit("```", 1)[0] if "```" in text else text
                text = text.strip()

            data = json.loads(text)
            sections = data.get("sections", {})
            logger.info("Builder localize: got sections for %d files", len(sections))

        except Exception as exc:
            logger.warning("Builder localize: failed (%s), falling back to truncation", exc)
            return self._fallback_truncate(all_files)

        # Extract selected line ranges from each file
        result: dict[str, str] = {}
        for path, content in all_files.items():
            file_lines = content.split("\n")
            ranges = sections.get(path)

            if not ranges:
                # File not mentioned by localizer — include first 100 lines as context
                selected = file_lines[:100]
                if len(file_lines) > 100:
                    selected.append(f"  ... [{len(file_lines) - 100} more lines] ...")
                result[path] = "\n".join(selected)
                continue

            # Merge and extract ranges
            selected_parts: list[str] = []
            last_end = 0
            for r in sorted(ranges):
                start = max(1, int(r[0])) - 1  # 0-indexed
                end = min(len(file_lines), int(r[1]))
                if start > last_end + 1:
                    selected_parts.append(f"\n  ... [lines {last_end + 1}-{start} omitted] ...\n")
                selected_parts.append("\n".join(file_lines[start:end]))
                last_end = end

            if last_end < len(file_lines):
                selected_parts.append(f"\n  ... [lines {last_end + 1}-{len(file_lines)} omitted] ...")

            result[path] = "\n".join(selected_parts)
            logger.info(
                "Builder localize: %s — %d ranges, %d/%d lines selected",
                path, len(ranges),
                sum(min(len(file_lines), int(r[1])) - max(0, int(r[0]) - 1) for r in ranges),
                len(file_lines),
            )

        return result

    @staticmethod
    def _fallback_truncate(all_files: dict[str, str]) -> dict[str, str]:
        """Fallback: keep first and last sections of each file."""
        result: dict[str, str] = {}
        for path, content in all_files.items():
            if len(content) <= 15_000:
                result[path] = content
            else:
                lines = content.split("\n")
                head = "\n".join(lines[:200])
                tail = "\n".join(lines[-200:])
                result[path] = (
                    head
                    + f"\n\n  ... [{len(lines) - 400} lines omitted] ...\n\n"
                    + tail
                )
        return result

    async def perceive(self, intent: Any) -> dict:
        """Read reference files and build context for the LLM.

        If total file content exceeds _LOCALIZE_THRESHOLD, uses a fast-tier
        LLM call to identify which sections are relevant, then reads only those.
        """
        obs = await super().perceive(intent)

        # Skip domain enrichment for conversational intents
        if obs.get("intent") in ("direct_message", "ward_room_notification", "proactive_think"):
            return obs

        params = obs.get("params", {})
        reference_files = params.get("reference_files", [])
        target_files = params.get("target_files", [])

        # Step 1: Read all files fully
        all_files: dict[str, str] = {}
        is_target: set[str] = set(target_files)

        for file_path in target_files + reference_files:
            if file_path in all_files:
                continue  # Already read (might be in both lists)
            try:
                full_path = _resolve_path(file_path)
                if full_path.exists() and full_path.is_file():
                    all_files[file_path] = full_path.read_text(encoding="utf-8")
                    logger.info("Builder perceive: read %s (%d chars)", file_path, len(all_files[file_path]))
                else:
                    if file_path in is_target:
                        all_files[file_path] = ""  # New file to create
                        logger.info("Builder perceive: target %s does not exist (new file)", file_path)
                    else:
                        logger.warning("Builder perceive: file not found: %s (resolved: %s)", file_path, full_path)
            except Exception as exc:
                logger.warning("Builder perceive: error reading %s: %s", file_path, exc)

        total_size = sum(len(c) for c in all_files.values())
        logger.info("Builder perceive: %d files, %d total chars", len(all_files), total_size)

        # BF-904b (#1585): the whole files, kept for the visiting builder. Only the native prompt context below
        # (and the Transporter's size estimate) uses the localized excerpts.
        full_files = dict(all_files)

        # Step 2: If files are large, use localization to select relevant sections
        if total_size > self._LOCALIZE_THRESHOLD:
            logger.info("Builder perceive: total %d > threshold %d, running localization", total_size, self._LOCALIZE_THRESHOLD)
            localized = await self._localize_context(
                description=params.get("description", ""),
                title=params.get("title", ""),
                all_files=all_files,
                target_paths=target_files,
            )
            # Replace full content with localized content
            all_files = localized

        # Step 3: Build context strings
        target_contexts: list[str] = []
        file_contexts: list[str] = []
        for file_path, content in all_files.items():
            if not content and file_path in is_target:
                target_contexts.append(
                    f"=== {file_path} (TARGET — new file, does not exist yet) ===\n"
                )
            elif file_path in is_target:
                target_contexts.append(
                    f"=== {file_path} (TARGET — will be modified) ===\n{content}\n"
                )
            else:
                file_contexts.append(f"=== {file_path} ===\n{content}\n")

        obs["file_context"] = "\n".join(file_contexts)
        obs["target_context"] = "\n".join(target_contexts)

        total_context = len(obs["file_context"]) + len(obs["target_context"])
        logger.info("Builder perceive: final context = %d chars", total_context)

        # Step 4: Check if visiting builder should be used (AD-353)
        spec = BuildSpec(
            title=params.get("title", ""),
            description=params.get("description", ""),
            target_files=target_files,
            reference_files=reference_files,
            test_files=params.get("test_files", []),
            ad_number=params.get("ad_number", 0),
            constraints=params.get("constraints", []),
        )

        if _should_use_visiting_builder(
            spec,
            hebbian_router=getattr(self._runtime, "hebbian_router", None) if self._runtime else None,
            force_native=params.get("force_native", False),
            force_visiting=params.get("force_visiting", False),
        ):
            tmp_dir = None
            try:
                from probos.cognitive.copilot_adapter import (
                    CopilotBuilderAdapter,
                    seed_session_directory,
                )

                # Create isolated temp dir so SDK doesn't write into project root
                tmp_dir = tempfile.mkdtemp(prefix="probos_build_")

                # Copy existing target files into temp dir (preserving structure).
                # BF-896: the helper the dispatcher uses; a key naming a path outside
                # the temp dir (an absolute target) is skipped, not written there.
                # BF-904b (#1585): whole files, and the adapter is given what was seeded (as the
                # dispatcher does), because its scan takes each change's "base" from that mapping.
                seeded = seed_session_directory(tmp_dir, full_files)

                model = params.get("model", "")
                adapter = CopilotBuilderAdapter(
                    codebase_index=getattr(self._runtime, "codebase_index", None) if self._runtime else None,
                    runtime=self._runtime,
                    cwd=tmp_dir,
                    **({"model": model} if model else {}),
                )
                await adapter.start()
                try:
                    copilot_result = await adapter.execute(spec, seeded)
                finally:
                    try:
                        await adapter.stop()
                    except Exception as stop_exc:
                        # BF-844: the SDK client holds `tmp_dir` as its cwd, so a
                        # failed shutdown means a descendant may still be holding
                        # the tree the `finally` below removes.
                        logger.warning(
                            "Visiting builder: adapter.stop() failed (%s: %s); an SDK "
                            "descendant may still hold the build tree %s, so its removal "
                            "will retry and will warn if it cannot complete.",
                            type(stop_exc).__name__, stop_exc, tmp_dir,
                        )

                if copilot_result.success and copilot_result.file_blocks:
                    self._transporter_result = {
                        "action": "transporter_complete",
                        "file_changes": copilot_result.file_blocks,
                        "llm_output": copilot_result.raw_output,
                        "builder_source": "visiting",
                    }
                    # Record success for Hebbian learning
                    if self._runtime and hasattr(self._runtime, "hebbian_router"):
                        from probos.mesh.routing import REL_BUILDER_VARIANT

                        self._runtime.hebbian_router.record_interaction(
                            "build_code", "visiting", success=True, rel_type=REL_BUILDER_VARIANT,
                        )
                    logger.info("Visiting builder produced %d file blocks", len(copilot_result.file_blocks))
                    return obs  # Skip native pipeline
                else:
                    logger.warning("Visiting builder failed: %s — falling back to native", copilot_result.error)
                    # Record failure for Hebbian learning
                    if self._runtime and hasattr(self._runtime, "hebbian_router"):
                        from probos.mesh.routing import REL_BUILDER_VARIANT

                        self._runtime.hebbian_router.record_interaction(
                            "build_code", "visiting", success=False, rel_type=REL_BUILDER_VARIANT,
                        )
            except Exception as e:
                logger.warning("Visiting builder error: %s — falling back to native", e)
            finally:
                if tmp_dir:
                    # BF-844: `tmp_dir` is the SDK client's cwd, so a surviving
                    # descendant holds it. A one-shot `rmtree(ignore_errors=True)`
                    # cannot remove a held directory on Windows and reports
                    # nothing when it fails -- measured: the tree survived the
                    # call AND the holder's exit, because nothing retried.
                    #
                    # Normally off-loop, because this `finally` runs on the event
                    # loop and the retry budget reaches ~9s. `remove_workdir_off_loop`
                    # falls back to a SYNCHRONOUS removal when it cannot submit to
                    # the executor (a loop whose executor has already shut down), so
                    # during shutdown this can still block for that budget.
                    #
                    # The `except` is not defensive padding: the replaced one-shot
                    # could not raise at all, and this helper deliberately
                    # propagates a worker failure. Measured without it, a cleanup
                    # error escaped `perceive` and discarded an already-successful
                    # build. Cleanup must not be able to destroy the work.
                    try:
                        await remove_workdir_off_loop(Path(tmp_dir))
                    except asyncio.CancelledError:
                        raise
                    except Exception as cleanup_exc:
                        logger.warning(
                            "Visiting builder: could not remove build tree %s (%s: %s); "
                            "it may remain on disk. The build result is unaffected.",
                            tmp_dir, type(cleanup_exc).__name__, cleanup_exc,
                        )

        # Step 5: Check if Transporter Pattern should be used
        target_size = sum(len(all_files.get(f, "")) for f in target_files)
        if _should_use_transporter(spec, target_size):
            logger.info(
                "Builder: using Transporter Pattern (%d files, %d chars context)",
                len(target_files), target_size,
            )
            try:
                transporter_blocks = await transporter_build(
                    spec=spec,
                    llm_client=self._llm_client,
                    work_dir=str(_PROJECT_ROOT),
                    codebase_index=getattr(self, "_codebase_index", None),
                )
                if transporter_blocks:
                    self._transporter_result = {
                        "action": "transporter_complete",
                        "file_changes": transporter_blocks,
                        "llm_output": f"[Transporter Pattern: {len(transporter_blocks)} file blocks from parallel chunks]",
                    }
                    return obs
                else:
                    logger.warning("Builder: Transporter returned no blocks, falling back to single-pass")
            except Exception as exc:
                logger.warning("Builder: Transporter failed (%s), falling back to single-pass", exc)

        # AD-546: Native SWE Harness routing branch (default-False, modify-only).
        if self._runtime is not None:
            cfg_root = getattr(self._runtime, "config", None)
            harness_cfg = getattr(cfg_root, "native_swe_harness", None) if cfg_root is not None else None
            harness = getattr(self._runtime, "native_builder_harness", None)
            if (
                harness is not None
                and harness_cfg is not None
                and getattr(harness_cfg, "enabled", False)
            ):
                eligibility_modify_only = getattr(harness_cfg, "eligibility_modify_only", True)
                eligible = True
                if eligibility_modify_only:
                    if not target_files:
                        eligible = False
                    else:
                        for tf in target_files:
                            tp = Path(tf)
                            if not tp.is_absolute():
                                tp = _PROJECT_ROOT / tf
                            if not tp.exists():
                                eligible = False
                                break
                if eligible:
                    try:
                        result = await harness.run_build(
                            spec,
                            work_dir=str(_PROJECT_ROOT),
                            agent_id=self.id,
                            department="engineering",
                            rank="lieutenant",
                        )
                        self._transporter_result = {
                            "action": "transporter_complete",
                            "file_changes": result.get("file_changes", []),
                            "llm_output": result.get("llm_output", ""),
                            "builder_source": "native_harness",
                        }
                        self._native_harness_metadata = result.get("metadata", {})
                        logger.info(
                            "AD-546: Native SWE harness produced %d file blocks (iterations=%d)",
                            len(result.get("file_changes", [])),
                            result.get("metadata", {}).get("iterations", 0),
                        )
                        return obs
                    except Exception as exc:
                        logger.warning(
                            "AD-546: Native SWE harness failed (%s); falling back to single-pass",
                            exc,
                            exc_info=True,
                        )

        return obs

    async def decide(self, observation: dict) -> dict:
        """Short-circuit LLM call when Transporter has already produced results."""
        result = getattr(self, "_transporter_result", None)
        if result:
            self._transporter_result = None  # Consume once
            return result
        return await super().decide(observation)

    async def _build_user_message(self, observation: dict) -> str:
        """Format the build spec and reference files into an LLM prompt."""
        # Delegate to parent for conversational intents
        intent_name = observation.get("intent", "unknown")
        if intent_name in ("direct_message", "ward_room_notification", "proactive_think"):
            return await super()._build_user_message(observation)

        params = observation.get("params", {})
        title = params.get("title", "Untitled")
        description = params.get("description", "")
        target_files = params.get("target_files", [])
        test_files = params.get("test_files", [])
        constraints = params.get("constraints", [])
        ad_number = params.get("ad_number", 0)
        file_context = observation.get("file_context", "")
        target_context = observation.get("target_context", "")

        parts = [
            f"# Build Spec: {title}",
            f"AD Number: AD-{ad_number}" if ad_number else "",
            f"\n## Description\n{description}",
        ]

        if target_files:
            parts.append("\n## Target Files\n" + "\n".join(f"- {f}" for f in target_files))
        if test_files:
            parts.append("\n## Test Files\n" + "\n".join(f"- {f}" for f in test_files))
        if constraints:
            parts.append("\n## Constraints\n" + "\n".join(f"- {c}" for c in constraints))
        if target_context:
            parts.append(
                f"\n## Target Files (current content — use MODIFY blocks for changes)\n{target_context}"
            )
        if file_context:
            parts.append(f"\n## Reference Code\n{file_context}")

        return "\n".join(p for p in parts if p)

    async def act(self, decision: dict) -> dict:
        """Parse LLM output into file blocks — does NOT write files."""
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think"):
            return {"success": True, "result": decision.get("llm_output", "")}
        if decision.get("action") == "error":
            logger.warning("Builder act: LLM returned error: %s", decision.get("reason"))
            return {"success": False, "error": decision.get("reason")}

        # Transporter Pattern result — blocks already parsed
        if decision.get("action") == "transporter_complete":
            # BF-904b (#1585): project-relative paths, as the single-pass route below gives them; a
            # CodebaseIndex-relative path would otherwise be refused at the write boundary.
            file_changes = _normalize_change_paths(decision.get("file_changes", []))
            result_dict: dict[str, Any] = {
                "file_changes": file_changes,
                "llm_output": decision.get("llm_output", ""),
                "change_count": len(file_changes),
                "builder_source": decision.get("builder_source", "native"),
            }
            # AD-546/549: Propagate native-harness metadata when present.
            metadata = getattr(self, "_native_harness_metadata", None)
            if metadata:
                result_dict["metadata"] = metadata
                self._native_harness_metadata = None  # consume once
            return {
                "success": True,
                "result": result_dict,
            }

        llm_output = decision.get("llm_output", "")
        logger.info("Builder act: LLM output length = %d chars", len(llm_output))
        if llm_output:
            logger.debug("Builder act: LLM output first 500 chars:\n%s", llm_output[:500])

        file_changes = self._parse_file_blocks(llm_output)
        if not file_changes:
            # Log enough to diagnose why parsing failed
            logger.warning(
                "Builder act: no file blocks parsed. Output length=%d, "
                "contains ===FILE: %s, contains ===MODIFY: %s, first 300 chars: %s",
                len(llm_output),
                "===FILE:" in llm_output,
                "===MODIFY:" in llm_output,
                llm_output[:300],
            )
            return {
                "success": False,
                "error": "LLM output contained no file blocks",
                "llm_output": llm_output,
            }

        return {
            "success": True,
            "result": {
                "file_changes": _normalize_change_paths(file_changes),
                "llm_output": llm_output,
                "change_count": len(file_changes),
            },
        }

    # -- file-block parser ----------------------------------------------------

    @staticmethod
    def _parse_file_blocks(text: str) -> list[dict[str, Any]]:
        """Extract file paths and content from ===FILE:=== and ===MODIFY:=== markers."""
        blocks: list[dict[str, Any]] = []

        # Pattern for ===FILE: path=== ... ===END FILE===
        for m in re.finditer(
            r"===FILE:\s*(.+?)===\s*\n(.*?)===END FILE===",
            text,
            re.DOTALL,
        ):
            blocks.append({
                "path": m.group(1).strip(),
                "content": m.group(2).strip() + "\n",
                "mode": "create",
                "after_line": None,
            })

        # Pattern for ===MODIFY: path=== ... ===END MODIFY===
        for m in re.finditer(
            r"===MODIFY:\s*(.+?)===\s*\n(.*?)===END MODIFY===",
            text,
            re.DOTALL,
        ):
            body = m.group(2)

            # Check for deprecated ===AFTER LINE:=== format
            if "===AFTER LINE:" in body:
                logger.warning(
                    "BuilderAgent: deprecated ===AFTER LINE:=== format in "
                    "MODIFY block for %s, skipping",
                    m.group(1).strip(),
                )
                continue

            # Parse ===SEARCH=== / ===REPLACE=== / ===END REPLACE=== pairs
            replacements: list[dict[str, str]] = []
            for sr in re.finditer(
                r"===SEARCH===\s*\n(.*?)===REPLACE===\s*\n(.*?)===END REPLACE===",
                body,
                re.DOTALL,
            ):
                search_text = sr.group(1).strip("\n")
                replace_text = sr.group(2).strip("\n")
                replacements.append({
                    "search": search_text,
                    "replace": replace_text,
                })

            if not replacements:
                logger.warning(
                    "BuilderAgent: MODIFY block for %s has no valid "
                    "SEARCH/REPLACE pairs, skipping",
                    m.group(1).strip(),
                )
                continue

            blocks.append({
                "path": m.group(1).strip(),
                "mode": "modify",
                "replacements": replacements,
            })

        return blocks


# ---------------------------------------------------------------------------
# Validation helpers (AD-313)
# ---------------------------------------------------------------------------

def _validate_python(path: Path) -> str | None:
    """Validate a Python file with ast.parse(). Returns error string or None."""
    if path.suffix != ".py":
        return None
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return None
    except SyntaxError as exc:
        return f"{path}: line {exc.lineno}: {exc.msg}"


def _fix_loop_changed(path: Path, before: bytes | None) -> bool:
    """BF-898: whether a repair block left *path* holding other bytes than *before* (None: absent)."""
    try:
        return path.is_file() and path.read_bytes() != before
    except OSError:
        return True  # cannot be read back, so it cannot be shown unchanged


class _SyntaxReadRefused(Exception):
    """BF-904b A3 (#1585): the final syntax read will not read a path; the message says why."""


def _syntax_read_opener(name: str, flags: int) -> int:
    """BF-904b A3: the one open of the final syntax read, as BF-904a's hooks read opens (``_HOOK_OPEN_FLAGS``).

    Never a final link, never blocking on a pipe; *flags*, the text layer's, are not used.
    """
    return os.open(name, _HOOK_OPEN_FLAGS)


def _work_tree_text(root: Path, path: Path) -> str:
    """BF-904b A3 (#1585): the text of *path*, read only if it is a regular file inside the work tree *root*.

    ``realpath`` follows every symbolic link, junction and other name-surrogate reparse point on the way, the
    last name included, so an alias the tests left is followed to where it leads; that must lie inside *root*'s
    own resolved form (by ``normcase``), or the path is refused unread. An alias that stays inside the tree is
    read, as the write before it followed it (F-124 owns aliases). A path that is gone or not a regular file by
    ``lstat`` is refused before any open. The one open neither follows a final link nor blocks on a pipe, and its
    handle must be that same regular file (``samestat``). Strict UTF-8 with universal newlines, as ``read_text``.
    """
    real = os.path.realpath(path)
    if not Path(os.path.normcase(real)).is_relative_to(os.path.normcase(os.path.realpath(root))):
        raise _SyntaxReadRefused("resolves outside the work tree")
    try:
        info = os.lstat(real)
    except (FileNotFoundError, NotADirectoryError):
        raise _SyntaxReadRefused("is no longer a regular file") from None
    if not stat.S_ISREG(info.st_mode):
        raise _SyntaxReadRefused("is no longer a regular file")
    with open(real, encoding="utf-8", opener=_syntax_read_opener) as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(opened, info):
            raise _SyntaxReadRefused("changed while it was read")
        return stream.read()


def _python_syntax_error(path: Path, text: str) -> str | None:
    """BF-904b A3 (#1585): *text*, read from *path*, parsed as ``_validate_python`` parses; the error line, or None."""
    try:
        ast.parse(text, filename=str(path))
        return None
    except SyntaxError as exc:
        return f"{path}: line {exc.lineno}: {exc.msg}"


def _syntax_errors(root: Path, paths: list[Path]) -> list[str]:
    """BF-904b (#1585): the syntax state of *paths* as they are now, one line per file that fails.

    Read at the commit decision, after any repair and after the tests, which run model-written code and can
    leave any filesystem state. A3: each Python file is read through ``_work_tree_text``, so one that resolves
    outside the work tree *root*, is gone, is not a regular file or changed while it was read is refused unread;
    one that cannot be read or decoded, or does not parse, blocks the commit. Every examination is inside the
    ``try``: ``OSError`` and ``ValueError`` become a line; anything else (``RecursionError``, ``MemoryError``)
    reaches the executor's ``except``. Only ``.py`` files are judged, as in ``_validate_python``.
    """
    errors: list[str] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        try:
            message = _python_syntax_error(path, _work_tree_text(root, path))
        except _SyntaxReadRefused as exc:
            message = f"{path}: {exc}; refused"
        except (OSError, ValueError) as exc:
            message = f"{path}: could not be read for the syntax check ({type(exc).__name__}); refused"
        if message is not None:
            errors.append(message)
    return errors


# ---------------------------------------------------------------------------
# Test & fix helpers (AD-314)
# ---------------------------------------------------------------------------

def _pytest_pythonpath(work_dir: str) -> str:
    """The work tree and its ``src``, then the runtime's own ``PYTHONPATH`` (the pre-BF-892 order)."""
    src_dir = str(Path(work_dir) / "src")
    existing = os.environ.get("PYTHONPATH", "")
    return f"{work_dir}{os.pathsep}{src_dir}" + (f"{os.pathsep}{existing}" if existing else "")


# BF-897 (#1559): the builder runs only the targeted tests. The full suite (about 48K
# tests, 14 to 19 minutes) never fit the 180 s phase 2 or the 60 s fallback, so every
# build with tests failed. It belongs to the receipted gate (AD-1336 child 2); the
# builder records it as not run, at the one place a governed runner later replaces.
TARGETED_TEST_TIMEOUT_S = 60
FULL_SUITE_NOT_RUN = "not_run"
NO_TARGETED_TESTS = (
    "No targeted tests map to the changed files, and the builder does not run the "
    "full suite (BF-897), so the change was not tested and is not committed."
)
_PYTEST_TIMEOUT_PREFIX = "pytest timed out after"


async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run the whole pytest suite in *work_dir* and return (passed, output).

    BF-897: no build path calls this any more (the full suite is the receipted
    gate's). It is kept because BF-892's environment boundary is tested through it.
    """
    import sys

    def _sync_run() -> tuple[int, str]:
        try:
            # BF-892 (#1543): the tests are model-authored; they get the command
            # allowlist plus PYTHONPATH, never the runtime's environment.
            run_env = {**build_command_env(), "PYTHONPATH": _pytest_pythonpath(work_dir)}
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"],
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
                env=run_env,
            )
            test_out = (result.stdout or b"").decode(errors="replace")
            test_err = (result.stderr or b"").decode(errors="replace")
            output = test_out + ("\n" + test_err if test_err else "")
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return 1, f"pytest timed out after {timeout}s"

    loop = asyncio.get_running_loop()
    returncode, output = await loop.run_in_executor(None, _sync_run)
    return returncode == 0, output


def _map_source_to_tests(changed_files: list[str], work_dir: str) -> list[str]:
    """Map changed source files to their corresponding test files (AD-344).

    Uses naming convention: src/probos/foo/bar.py -> tests/test_bar.py
    Also includes any changed files that are themselves test files.
    """
    tests_dir = Path(work_dir) / "tests"
    if not tests_dir.exists():
        return []

    test_files: list[str] = []
    seen: set[str] = set()

    for changed in changed_files:
        changed_path = Path(changed)

        # If the changed file is itself a test file, include it
        if changed_path.name.startswith("test_"):
            full = tests_dir / changed_path.name
            if full.exists() and str(full) not in seen:
                test_files.append(str(full))
                seen.add(str(full))
            continue

        # Extract module name and find matching test files
        stem = changed_path.stem  # e.g., "shell" from "shell.py"
        for candidate in tests_dir.glob(f"test_{stem}*.py"):
            if str(candidate) not in seen:
                test_files.append(str(candidate))
                seen.add(str(candidate))

    return test_files


async def _run_targeted_tests(
    work_dir: str,
    changed_files: list[str],
    timeout: int = 60,
) -> tuple[bool, str, list[str]]:
    """Run only tests related to changed files (AD-344).

    Returns (passed, output, test_files_run).
    BF-897 (#1559): when no test file maps to the changed files nothing runs and
    the result is ``(False, NO_TARGETED_TESTS, [])``. The full suite never finished
    within this budget; it belongs to the receipted gate (AD-1336 child 2).
    """
    test_files = _map_source_to_tests(changed_files, work_dir)

    if not test_files:
        return False, NO_TARGETED_TESTS, []

    import sys

    def _sync_run() -> tuple[int, str]:
        try:
            # BF-892 (#1543): model-authored tests; allowlist plus PYTHONPATH only.
            targeted_env = {**build_command_env(), "PYTHONPATH": _pytest_pythonpath(work_dir)}
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"] + test_files,
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
                env=targeted_env,
            )
            test_out = (result.stdout or b"").decode(errors="replace")
            test_err = (result.stderr or b"").decode(errors="replace")
            output = test_out + ("\n" + test_err if test_err else "")
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return 1, f"pytest timed out after {timeout}s"

    loop = asyncio.get_running_loop()
    returncode, output = await loop.run_in_executor(None, _sync_run)
    return returncode == 0, output, test_files


def _classify_test_run(passed: bool, output: str) -> str:
    """BF-897: ``passed``, ``timed_out``, ``not_run`` or ``failed``.

    Only ``failed`` reaches the fix loop: a timeout or an untested change is
    nothing a model's repair can fix, and asking for one spends a deep-tier call
    on output that names no failing test.
    """
    if passed:
        return "passed"
    if output.startswith(_PYTEST_TIMEOUT_PREFIX):
        return "timed_out"
    if output == NO_TARGETED_TESTS:
        return "not_run"
    return "failed"


def _build_fix_prompt(
    spec_title: str,
    test_output: str,
    file_changes: list[dict[str, Any]],
    attempt: int,
) -> str:
    """Build a prompt asking the LLM to fix test failures."""
    file_listing = "\n".join(
        f"- {c['path']} ({c['mode']})" for c in file_changes
    )
    return (
        f"# Test Fix Required (attempt {attempt})\n\n"
        f"Build: {spec_title}\n\n"
        f"## Files Changed\n{file_listing}\n\n"
        f"## Test Failures\n```\n{test_output[-3000:]}\n```\n\n"
        "Fix the failing tests. Output ONLY the file changes needed to fix the "
        "failures. Use the same ===MODIFY: path=== or ===FILE: path=== format. "
        "Do NOT rewrite files that don't need changes. Keep fixes minimal — "
        "fix the bug, don't refactor.\n\n"
        "You may change only source files under src/probos/ (BF-898). Do not change "
        "any test, conftest.py or test configuration, or the builder, its reviewer or "
        "its write boundary: a response with such a block is refused whole and the "
        "build is not committed. If a test itself is wrong, say so and output no blocks."
    )


# ---------------------------------------------------------------------------
# Post-approval execution pipeline (AD-303)
# ---------------------------------------------------------------------------


async def _is_dirty_working_tree(work_dir: str) -> bool:
    """Check if the git working tree has uncommitted changes.

    Returns False if not inside a git repo or if the tree is clean.
    Uses create_subprocess_exec directly to avoid interference with
    subprocess.run mocks in existing tests.
    """
    try:
        git_env = build_command_env(_GIT_HOME_NAMES)
        # First verify we're inside a git repo. BF-904a (#1585): both launches carry the
        # hardening options; `git status` refreshes the index, which runs a configured fsmonitor.
        proc = await asyncio.create_subprocess_exec(
            "git", *HARDENED_GIT_CONFIG_ARGS, "rev-parse", "--git-dir",
            env=git_env,
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            return False  # Not a git repo — skip check

        # Check for uncommitted changes. BF-904a A7 (D41): uncached. Git for Windows' file-system cache
        # reads NTFS directory entries, which a hard link's other name refreshes lazily, so a restored
        # file can read as modified. Other hosts ignore the setting.
        proc = await asyncio.create_subprocess_exec(
            "git", *HARDENED_GIT_CONFIG_ARGS, "-c", "core.fscache=false", "status", "--porcelain",  # BF-904a A7 (D41): the dirty check reads the file, not the cache
            env=git_env,
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return proc.returncode == 0 and bool(stdout.decode().strip())
    except (OSError, FileNotFoundError):
        return False  # git not available


def _round_trip(text: str) -> str:
    r"""BF-904a A10 (D45): the text ``Path.read_text`` returns after ``Path.write_text(text)`` on this host.

    The write turns each ``\n`` into ``os.linesep`` (``\r\n`` on Windows, unchanged on POSIX); the read
    maps ``\r\n``, then a lone ``\r``, to ``\n`` (universal newlines). A ``\r\n`` in a replacement so
    reads back as ``\n\n`` on Windows and ``\n`` on POSIX, and never with a ``\r``.
    """
    return text.replace("\n", os.linesep).replace("\r\n", "\n").replace("\r", "\n")


def _same_file_key(work_dir: str, rel: str) -> tuple[Any, ...]:
    """BF-904a A10 (D44), A11 (D53), A12 (D54): one key per file on disk, for every name this host's file calls unify.

    An existing target is keyed by ``(st_dev, st_ino)`` (``os.stat`` follows symbolic links), so a hard
    link and a case variant on a case-folding filesystem are one file. A target that does not exist, or
    a filesystem that reports no inode number, is keyed by the ``os.path.abspath`` form of its
    ``_write_target_key``: the physical path first (``realpath`` resolves symbolic links, so a ``..`` in
    the work directory is taken as the kernel takes it), then the host's full-path form. On Windows that
    is ``GetFullPathNameW``, the trimming the writer's own calls get (the last name's trailing dots and
    spaces, an inner name's single trailing dot); on POSIX it is the identity on a resolved path, so the
    key is D32's and ``fresh.py.`` stays another name. The pre-check writes nothing, so a file a change
    creates is absent, and keyed by path, for the whole check.
    """
    key = os.path.abspath(_write_target_key(work_dir, rel))  # BF-904a A12 (D54): the physical path first, then the host's full-path form
    try:
        info = os.stat(key)
    except (OSError, ValueError):
        return ("path", key)
    return ("file", info.st_dev, info.st_ino) if info.st_ino else ("path", key)


def _unapplied_blocks(changes: list[dict[str, Any]], work_dir: str) -> list[str]:
    """BF-904a (#1585): a refusal for each MODIFY block in *changes* that cannot apply as written.

    A10: the main loop's list (after BF-894's path check) and a repair response are each checked whole
    before any write. Blocks are matched in order against the text the earlier changes of the same file
    leave, as the disk returns it (``_round_trip``), one file per ``_same_file_key``; creates parse
    first. A change carrying ``base`` is BF-896's, judged by the main loop, and its file's later blocks
    are left to the writer (D47). A target that exists but is not a regular file is left to the writer,
    which raises as before (BF-898 keeps its disclosure). Names the block and the file, never their text.
    """
    refusals: list[str] = []
    texts: dict[tuple[Any, ...], str | None] = {}  # None: the writer judges this file's later blocks
    for change in changes:
        rel = change["path"]
        key = _same_file_key(work_dir, rel)
        if "base" in change:  # BF-904a A10 (D47): BF-896's compare-and-swap is the main loop's
            texts[key] = None
            continue
        if change["mode"] != "modify":
            if isinstance(change.get("content"), str):
                texts[key] = _round_trip(change["content"])
            continue
        if key not in texts:
            path = Path(work_dir) / rel
            if not path.exists():
                refusals.append(f"MODIFY target {rel} does not exist; refused")  # BF-904a: a repair's missing target
                continue
            if not path.is_file():
                continue
            try:
                texts[key] = path.read_text(encoding="utf-8")
            except (OSError, ValueError):
                refusals.append(f"MODIFY target {rel} could not be read; refused")
                continue
        text = texts[key]
        if text is None:
            continue
        for i, repl in enumerate(change.get("replacements", [])):
            if repl["search"] not in text:
                refusals.append(f"SEARCH block {i} not found in {rel}; refused")  # BF-904a: a repair's unmatched block
                continue
            text = text.replace(repl["search"], repl["replace"], 1)
        texts[key] = _round_trip(text)  # BF-904a A10 (D45): what the next change reads back
    return refusals


#: BF-904b (#1585): the sealed-core policy this ProbOS runs under. Never the work tree's copy (a build writes
#: the work tree, config/ included, so it could rewrite its own policy) and never a path relative to the
#: process's working directory, which is not the repository.
_SEALED_POLICY = _PROJECT_ROOT / "config" / "sealed_modules.yaml"


def sealed_core_enforced(runtime: Any) -> bool:
    """BF-904b (#1585): whether *runtime*'s config turns the sealed-core observation (AD-481f) on.

    True only when ``runtime.config.extensions.enforce_sealed_core`` is the boolean True; False for None,
    for an object without that chain (a test double) and for any other value, as the AttributeError branch
    of the check this replaces did. The /api/build routes call it on their runtime: they pass no runtime to
    the executor, which would switch on the pre-flight runner and Hebbian recording for them.
    """
    try:
        return runtime.config.extensions.enforce_sealed_core is True
    except AttributeError:
        return False


def _sealed_globs() -> tuple[str, ...]:
    """BF-904b (#1585): the globs of this ProbOS's sealed-core policy; empty when it is missing or cannot be read.

    The loader degrades a missing file, a YAML error and an OS error in the read itself. Whatever else it raises
    on this file is caught here, of any class: an OS error from its existence check, a file that is not UTF-8,
    and what PyYAML's constructors and composer raise on corrupt content (an impossible date, a sexagesimal float
    too large, an unknown ``!!bool``, an empty ``!!int``, nesting past the recursion limit). That set is open:
    each constructor raises what its own code raises, and a later PyYAML can add a class. So the boundary is this
    one call, not a list (Amendment A4); the code after it handles ``str`` values only and is not guarded. One
    warning names the file and the exception class, and the observation never changes a build's outcome (D5). A
    ``MemoryError`` still propagates: the process, not the policy, has failed. Nothing is cached when the loader
    raises, so each flagged build reads the file again.
    """
    from probos.extensions.sealed_core import load_sealed_globs

    try:
        return load_sealed_globs(str(_SEALED_POLICY))
    except MemoryError:
        raise  # BF-904b A4: the process is out of memory, not the policy unreadable; the build fails as before
    except Exception as exc:  # BF-904b A4: third-party parsing of an external file; its failure set is open
        logger.warning(
            "BF-904b: the sealed policy %s cannot be read (%s); this build observes nothing",
            _SEALED_POLICY, type(exc).__name__,
        )
        return ()  # BF-904b A2: no globs, so nothing is observed and the build goes on


def _check_sealed_path(change_path: str, sealed_globs: tuple[str, ...]) -> None:
    """AD-481f: warn-only sealed-core pre-write check. BF-904b (#1585): it can fire.

    *sealed_globs* is what ``execute_approved_build`` loaded at entry: the policy's globs when
    ``enforce_sealed_core`` is on, otherwise empty, and then nothing is matched or logged. *change_path* is
    the block's repository-relative path, which BF-894's write boundary has admitted. It is matched with ``/``
    separators, ``.`` and doubled separators removed, and case folded on both sides, so a spelling the host's
    filesystem resolves to a sealed file is observed on every host. A path naming nothing inside the
    repository (absolute, or escaping with ``..``) matches no repository-relative glob; the boundary refuses
    it before this runs. One ``logger.warning`` per write; never raises. The hard block is AD-481l, after
    the AD-482 RedTeam baseline; the per-BuildSpec ``core_modification`` override lands with it.
    """
    if not sealed_globs:
        return
    rel = os.path.normpath(change_path.replace("\\", "/")).replace("\\", "/").casefold()
    from probos.extensions.sealed_core import is_sealed_path

    if is_sealed_path(rel, tuple(glob.casefold() for glob in sealed_globs)):
        logger.warning(
            "AD-481f: Builder writing to sealed-core path %r "
            "(enforce_sealed_core=True); v1 is observation-only — "
            "hard-block ships at AD-481l",
            change_path,
        )


# AD-521: Back-compat alias. Existing imports
# (`from probos.cognitive.builder import BuilderAgent`) continue to resolve.
# 16 test files use the BuilderAgent name; all keep working unchanged.
BuilderAgent = SoftwareEngineerAgent


async def execute_approved_build(
    file_changes: list[dict[str, Any]],
    spec: BuildSpec,
    work_dir: str,
    run_tests: bool = True,
    max_fix_attempts: int = 2,
    llm_client: BaseLLMClient | None = None,
    escalation_hook: Callable | None = None,
    builder_source: str = "native",
    runtime: ProbOSRuntime | None = None,
    specialty: str = "general",
    expected_git_dir: str | None = None,
    enforce_sealed_core: bool | None = None,
) -> BuildResult:
    """Execute an approved build: write files, run tests, create git branch.

    Called AFTER the Captain reviews the BuilderAgent's output and approves
    the changes.  The agent generates the plan; this function executes it.

    Args:
        escalation_hook: Optional async callback invoked when tests fail after
            all fix attempts are exhausted. Receives a BuildFailureReport and
            returns either a resolved BuildResult or None to escalate to Captain.
            Future: wired to chain of command (Phase-33).
        expected_git_dir: BF-896. A value ``repository_identity(work_dir)``
            returned before generation began. When given, the build is refused
            at entry (before any git command or write) and again before the
            commit if *work_dir* no longer names that repository.
        enforce_sealed_core: BF-904b (#1585). Whether writes to sealed-core paths
            are observed (AD-481f: a warning per write, never a refusal). None
            reads ``runtime``'s config (``BuildPipeline``); the /api/build routes
            and the dispatcher pass the flag, because they pass no runtime.
    """
    result = BuildResult(success=False, spec=spec)
    identity_lost = False
    # BF-904a (#1585): set when the identity changed, or git's config or hooks changed while the
    # tests ran; no further git command runs in this call, the commit included.
    git_unsafe = False
    git_tampered: str | None = None
    git_baseline: _GitSafetySnapshot | None = None
    tests_ran = False
    # BF-904b (#1585): the sealed-core observation (AD-481f). The caller's flag, else the runtime's config;
    # the policy is read only when it is on, before any git command or write.
    observe_sealed = enforce_sealed_core if enforce_sealed_core is not None else sealed_core_enforced(runtime)
    sealed_globs = _sealed_globs() if observe_sealed is True else ()

    # 0a. BF-897 (#1559): refuse the checkout the runtime started from (a location
    # check, see operator_checkout_refusal). Before any git command or write; no
    # subprocess, so tests that patch subprocess.run see none.
    checkout_refusal = operator_checkout_refusal(work_dir, _PROJECT_ROOT)
    if checkout_refusal is not None:
        result.error = checkout_refusal
        return result

    # 0. BF-896: the tree must still name the repository pinned before generation.
    if expected_git_dir is not None:
        current_git_dir = await repository_identity(work_dir)
        if current_git_dir != expected_git_dir:
            result.error = (
                "Repository identity changed since the build was pinned "
                f"(expected {expected_git_dir!r}, found {current_git_dir!r}); "
                "refused before any write"
            )
            return result

    # 0b. BF-904a (#1585): with no pin from the caller (the /api/build routes, BuildPipeline), pin
    # what the tree names now when it is readable, so the check before the commit covers every
    # caller. An unreadable identity keeps today's path: a real non-repository fails later.
    pinned_git_dir = expected_git_dir
    if pinned_git_dir is None:
        pinned_git_dir = await repository_identity(work_dir)  # BF-904a: pin what the tree names now, when readable

    # 1. BF-904a (#1585): the ref a build returns to, read before anything changes: the
    # branch, or the commit of a detached HEAD. A tree with neither is refused here, before
    # the build branch exists; it is never sent to a guessed "main".
    original_branch = await _git_current_branch(work_dir)
    original_commit = None if original_branch is not None else await _git_head_commit(work_dir)
    if original_branch is None and original_commit is None:
        result.error = (
            "Cannot read the checkout's current branch or commit, so a failed build could "
            "not return to it; refused before any write"
        )
        return result
    if original_branch is not None and not _ref_survives_argv(original_branch):  # BF-904a A7 (D39): git would receive another name
        result.error = (
            f"The checkout's branch {_display_token(original_branch, _DISPLAY_NAME_CHARS)} cannot be passed to git "
            "unchanged on this host, so a failed build could not return to it; refused before any write"
        )
        return result

    # 1a. Verify clean working tree (prevent contaminating build branch)
    if await _is_dirty_working_tree(work_dir):
        result.error = (
            "Working tree has uncommitted changes. "
            "Commit or stash changes before running a build."
        )
        return result

    # 1b. AD-458: Pre-flight validation (after clean-tree check, before branch creation)
    pre_flight = getattr(runtime, "pre_flight_runner", None) if runtime is not None else None
    if pre_flight is not None:
        emit = runtime.emit_event if runtime is not None else None
        report = await pre_flight.run(spec, emit_event=emit)
        if not report.passed:
            blocking_failures = [
                r for r in report.results if not r.passed and r.blocking
            ]
            result.error = "pre-flight validation failed: " + ", ".join(
                f"{r.check_name}: {r.detail}" for r in blocking_failures
            )
            return result

    # 2. Generate branch name
    branch = spec.branch_name
    if not branch:
        slug = _sanitize_branch_name(spec.title)
        branch = f"builder/ad-{spec.ad_number}-{slug}" if spec.ad_number else f"builder/{slug}"

    # 3. Create branch
    ok, msg = await _git_create_branch(branch, work_dir)
    if not ok:
        result.error = f"Failed to create branch: {msg}"
        return result
    result.branch_name = _sanitize_branch_name(branch)
    # BF-904a: a local, because the escalation hook's result can replace ``result``.
    build_branch = result.branch_name

    written: list[str] = []
    modified_files: list[str] = []
    # BF-904b (#1585): refusals only, and permanent: no later step can lift one.
    validation_errors: list[str] = []
    # BF-904b (#1585): every path a write validated, in order. Syntax is state: it is read again on the files as
    # they are at the commit decision (5.5), so an error a repair fixed no longer blocks the commit.
    syntax_checked: dict[Path, None] = {}
    # BF-904a (#1585): the bytes of every file that existed before this build, saved before its
    # first write (setdefault keeps that first copy); a build that does not commit writes them back.
    originals: dict[str, bytes] = {}
    found_keys: set[str] = set()  # BF-904a A4 (D32): the _write_target_key of every saved file
    add_attempted = False
    try:
        # 4. Write/modify files
        admitted: list[dict[str, Any]] = []
        for change in file_changes:
            # Validate file path before any disk operations (BF-894: lexical and identity)
            path_error = builder_write_refusal(change["path"], work_dir)
            if path_error:
                logger.warning("BuilderAgent: %s — skipping", path_error)
                validation_errors.append(path_error)
                continue
            admitted.append(change)
        # BF-904a A10 (D46): every SEARCH/REPLACE block of the list is checked before any write, as a
        # repair's is; a list with one that cannot apply writes nothing, so no partial file reaches the
        # review or the tests. The checks below stay and refuse whatever this pre-pass did not model.
        blocked = _unapplied_blocks(admitted, work_dir)  # BF-904a A10: the main loop's pre-pass
        validation_errors.extend(blocked)
        for change in [] if blocked else admitted:  # BF-904a A10 (D46): a blocked list writes nothing
            path = Path(work_dir) / change["path"]
            if "base" in change:
                # BF-896: a block carrying "base" (the visiting adapter's disk scan,
                # create or modify) applies only while the target's current text
                # equals it ("" when the target does not exist); otherwise it is
                # refused, never skipped or overwritten.
                if path.exists() and not path.is_file():
                    validation_errors.append(
                        f"Whole-file change to {change['path']} targets a "
                        "non-regular file; refused"
                    )
                    continue
                if path.exists():
                    try:
                        current_text = path.read_text(encoding="utf-8")
                    except (OSError, ValueError):
                        validation_errors.append(
                            f"Whole-file change to {change['path']} could not be "
                            "compared with its current content; refused"
                        )
                        continue
                else:
                    current_text = ""
                if (
                    not isinstance(change["base"], str)
                    or change["base"] != current_text
                    or (change["mode"] == "modify" and not path.exists())
                ):
                    validation_errors.append(
                        f"Whole-file change to {change['path']} was generated "
                        "against different content; refused"
                    )
                    continue
            if change["mode"] == "modify":
                if not path.exists():
                    # BF-904a (#1585): a refusal that blocks the commit, never a silent skip.
                    validation_errors.append(f"MODIFY target {change['path']} does not exist; refused")
                    continue

                original = path.read_text(encoding="utf-8")
                modified = original

                if "replacements" not in change and isinstance(change.get("content"), str):
                    # BF-896: a whole-file MODIFY (the visiting adapter's disk scan).
                    # It applies only while the target still holds the text it was
                    # generated against; otherwise it is refused, never dropped.
                    if change.get("base") != original:
                        validation_errors.append(
                            f"Whole-file change to {change['path']} was generated "
                            "against different content; refused"
                        )
                        continue
                    modified = change["content"]

                unmatched = False
                for i, repl in enumerate(change.get("replacements", [])):
                    search_text = repl["search"]
                    replace_text = repl["replace"]

                    if search_text not in modified:
                        # BF-904a (#1585): recorded (names the block and the file, never its text); the
                        # file is not written, the commit is blocked and the tree is restored.
                        validation_errors.append(f"SEARCH block {i} not found in {change['path']}; refused")
                        unmatched = True
                        continue

                    # Replace first occurrence only
                    modified = modified.replace(search_text, replace_text, 1)
                if unmatched:
                    continue  # BF-904a: a file with an unmatched block is not written at all

                if modified != original:
                    _check_sealed_path(change["path"], sealed_globs)  # BF-904b: the main loop's modify
                    if change["path"] not in written and _first_found(work_dir, change["path"], found_keys):  # BF-904a A4 (D32): once per file
                        originals.setdefault(change["path"], path.read_bytes())  # BF-904a: saved before the first write
                    path.write_text(modified, encoding="utf-8")
                    modified_files.append(change["path"])
                    logger.info(
                        "BuilderAgent: modified %s (%d replacements)",
                        change["path"], len(change.get("replacements", [])),
                    )
                else:
                    logger.warning(
                        "BuilderAgent: no changes applied to %s", change["path"],
                    )

                # Validate Python files after modify (BF-904b: read at 5.5, on the file as it is then)
                syntax_checked[path] = None  # BF-904b: a main-loop modify, read again at 5.5

                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            _check_sealed_path(change["path"], sealed_globs)  # BF-904b: the main loop's create
            pre_existing = path.exists() and change["path"] not in written
            if pre_existing and _first_found(work_dir, change["path"], found_keys):  # BF-904a A4 (D32): once per file, a create over it too
                originals.setdefault(change["path"], path.read_bytes())  # BF-904a: a create over an existing file saves it first
            path.write_text(change["content"], encoding="utf-8")
            if pre_existing:
                # BF-896: a CREATE over a file that existed before this build is a
                # modification. The failed-build cleanup unlinks files_written, so a
                # pre-existing file must never be listed there.
                if change["path"] not in modified_files:
                    modified_files.append(change["path"])
                logger.info("BuilderAgent: overwrote %s", change["path"])
            elif change["path"] not in written:
                written.append(change["path"])
                logger.info("BuilderAgent: wrote %s", change["path"])

            # Validate Python files after create (BF-904b: read at 5.5, on the file as it is then)
            syntax_checked[path] = None  # BF-904b: a main-loop create, read again at 5.5

        result.files_written = written
        result.files_modified = modified_files

        # 4b. Warn about files not in build spec target list
        if spec.target_files:
            expected = set(spec.target_files)
            actual = set(written + modified_files)
            unexpected = actual - expected
            if unexpected:
                logger.warning(
                    "BuilderAgent: %d file(s) not in build spec target list: %s",
                    len(unexpected), ", ".join(sorted(unexpected)),
                )

        # 4c. Code review (AD-341). BF-904b (#1585): not after a refusal, which nothing later can lift.
        if llm_client and (written or modified_files) and not validation_errors:
            from probos.cognitive.code_reviewer import CodeReviewAgent
            reviewer = CodeReviewAgent(
                agent_id="code_reviewer",
                name="CodeReviewAgent",
            )
            try:
                review = await reviewer.review(
                    file_changes=file_changes,
                    spec_title=spec.title,
                    llm_client=llm_client,
                )
                result.review_result = review.summary
                if not review.approved:
                    logger.warning(
                        "CodeReviewAgent: review REJECTED -- %s",
                        "; ".join(review.issues),
                    )
                    # Soft gate: log issues but don't block.
                    # Future: hard gate after reviewer earns trust.
                    result.review_issues = review.issues
            except Exception as exc:
                logger.warning("CodeReviewAgent: review error: %s", exc)

        # 5. Run tests with fix loop (AD-314, AD-344). BF-904b (#1585): a build that already holds a refusal
        # cannot commit, so it runs no model-written code and asks for no repair (#1523 F-153 item 18).
        if run_tests and (written or modified_files) and not validation_errors:
            # BF-904a (#1585): what git would run on its own, read before any model code runs.
            git_baseline = await _git_safety_snapshot(work_dir, pinned_git_dir is not None)
            tests_ran = True
            # BF-904a A1 (D23): from here model code may run, so git is unsafe until the comparison at
            # 5.4b finds it unchanged; an error or a cancellation before then runs no git in `finally`.
            git_unsafe = True  # BF-904a A1: model code may run from here; only a clean comparison clears it
            all_changes = list(file_changes)  # track for fix prompt
            fix_loop_files: list[str] = []  # BF-898: the paths the fix loop changed

            for attempt in range(1 + max_fix_attempts):
                # BF-904b (#1585): read at the start of each attempt, so a file an earlier repair created is targeted.
                all_changed_files = written + modified_files
                # Targeted tests only (AD-344). BF-897: there is no full-suite phase here.
                passed, test_output, _targeted_files = await _run_targeted_tests(
                    work_dir, all_changed_files, timeout=TARGETED_TEST_TIMEOUT_S,
                )
                result.test_result = test_output
                result.tests_passed = passed
                test_outcome = _classify_test_run(passed, test_output)
                result.metadata["targeted_tests"] = test_outcome

                if passed:
                    break
                if test_outcome != "failed":
                    # BF-897: a timeout or an untested change never enters the fix loop.
                    logger.warning(
                        "BuilderAgent: targeted tests %s on attempt %d; no fix requested",
                        test_outcome, attempt + 1,
                    )
                    break

                if attempt < max_fix_attempts and llm_client is not None:
                    logger.info(
                        "BuilderAgent: test failures on attempt %d/%d, "
                        "requesting fix from LLM",
                        attempt + 1, max_fix_attempts,
                    )
                    fix_prompt = _build_fix_prompt(
                        spec.title, test_output, all_changes, attempt + 1,
                    )
                    fix_request = LLMRequest(
                        prompt=fix_prompt,
                        system_prompt=BuilderAgent.instructions,
                        tier="deep",
                    )
                    # BF-898 review r1: a request counts when it is sent, so an error below keeps it.
                    result.fix_attempts += 1
                    try:
                        fix_response = await llm_client.complete(fix_request)
                        fix_changes = BuilderAgent._parse_file_blocks(
                            fix_response.content,
                        )
                    except Exception as exc:
                        logger.warning(
                            "BuilderAgent: LLM fix call failed: %s", exc,
                        )
                        fix_changes = []

                    if not fix_changes:
                        logger.warning(
                            "BuilderAgent: LLM returned no fix blocks, "
                            "skipping attempt %d",
                            attempt + 1,
                        )
                        continue

                    # BF-898 (#1563): the repair is model-authored and unreviewed, so it may
                    # change source only (builder_paths.fix_loop_write_refusal, which refuses a
                    # control or line-break character first, then applies BF-894's boundary). A
                    # response with any refused block is refused whole and the fix loop stops;
                    # the refusal blocks the commit (validation_errors) and names the path. Each
                    # path is put in one spelling first, so the rule judges the string written.
                    for change in fix_changes:
                        change["path"] = fix_loop_path(change["path"])
                    fix_refusals = [
                        refusal
                        for refusal in (
                            fix_loop_write_refusal(change["path"], work_dir)
                            for change in fix_changes
                        )
                        if refusal is not None
                    ]
                    if fix_refusals:
                        for refusal in fix_refusals:
                            logger.warning("BuilderAgent: repair refused: %s", refusal)
                        validation_errors.extend(fix_refusals)
                        break  # BF-898: no further repair attempt
                    # BF-904a (#1585): every MODIFY block of the repair must apply as written; one that
                    # cannot refuses the whole response and stops the loop, as BF-898 does for paths.
                    unapplied = _unapplied_blocks(fix_changes, work_dir)  # BF-904a: checked before any block is applied
                    if unapplied:
                        for refusal in unapplied:
                            logger.warning("BuilderAgent: repair refused: %s", refusal)
                        validation_errors.extend(unapplied)
                        break  # BF-904a: no further repair attempt

                    # Apply fix changes
                    late_refused = False  # BF-904a A10 (D48): a block the disk does not match at write time
                    for change in fix_changes:
                        path = Path(work_dir) / change["path"]
                        before_fix = path.read_bytes() if path.is_file() else None
                        if before_fix is not None and change["path"] not in written and _first_found(work_dir, change["path"], found_keys):  # BF-904a A4 (D32): not again under a second spelling
                            originals.setdefault(change["path"], before_fix)  # BF-904a: a repair saves a file the build did not create
                        try:
                            if change["mode"] == "modify":
                                # BF-904a: _unapplied_blocks has checked that the target exists and that
                                # every block matches, in order; A10 (D48) matches again against the disk.
                                original = path.read_text(encoding="utf-8")
                                mod = original
                                late: list[str] = []
                                for i, repl in enumerate(change.get("replacements", [])):
                                    if repl["search"] not in mod:
                                        late.append(f"SEARCH block {i} not found in {change['path']} when applied; refused")
                                        continue
                                    mod = mod.replace(repl["search"], repl["replace"], 1)
                                if late:
                                    # BF-904a A10 (D48): never a silent no-op. This change is not written,
                                    # the repair stops and the build is refused; earlier writes are disclosed.
                                    for refusal in late:
                                        logger.warning("BuilderAgent: repair refused: %s", refusal)
                                    validation_errors.extend(late)
                                    late_refused = True
                                    break
                                if mod != original:
                                    _check_sealed_path(change["path"], sealed_globs)  # BF-904b: a repair's modify
                                    path.write_text(mod, encoding="utf-8")
                                    if change["path"] not in modified_files:
                                        modified_files.append(change["path"])
                            else:
                                path.parent.mkdir(parents=True, exist_ok=True)
                                _check_sealed_path(change["path"], sealed_globs)  # BF-904b: a repair's create
                                pre_existing = path.exists() and change["path"] not in written
                                path.write_text(
                                    change["content"], encoding="utf-8",
                                )
                                if pre_existing or _write_target_key(work_dir, change["path"]) in found_keys:  # BF-904a A4 (D32): a saved file the tests deleted is restored, never deleted as created
                                    # BF-896: never list a pre-existing file in files_written.
                                    if change["path"] not in modified_files:
                                        modified_files.append(change["path"])
                                elif change["path"] not in written:
                                    written.append(change["path"])
                            syntax_checked[path] = None  # BF-904b: a repair's file, read again at 5.5
                        finally:
                            # Settled however the block ends: a write or the validation can raise
                            # after the file has changed, and the change must still be disclosed.
                            if _fix_loop_changed(path, before_fix) and change["path"] not in fix_loop_files:
                                fix_loop_files.append(change["path"])
                                result.metadata["fix_loop_files"] = sorted(fix_loop_files)

                    if late_refused:
                        break  # BF-904a A10 (D48): no further repair attempt
                    all_changes.extend(fix_changes)
                else:
                    # BF-897: no repair client, or the attempts are used up. The tree is
                    # unchanged, so another run would only repeat this one, and no repair was
                    # requested.
                    break  # BF-897 review r1: fix_attempts counts repair requests only

            result.files_written = written
            result.files_modified = modified_files
            # BF-897: the full suite is the receipted gate's (AD-1336 child 2); not run here.
            result.metadata["full_suite"] = FULL_SUITE_NOT_RUN

        # 5.4. BF-896: the tests may have run arbitrary code; the tree must still
        # name the pinned repository before anything is committed (BF-904a: the
        # entry pin when the caller gave none).
        if pinned_git_dir is not None:
            current_git_dir = await repository_identity(work_dir)
            if current_git_dir != pinned_git_dir:
                identity_lost = True
                git_unsafe = True
                logger.error(
                    "BuilderAgent: repository identity changed during the build "
                    "(expected %r, found %r); refusing to commit",
                    pinned_git_dir, current_git_dir,
                )
        # 5.4b. BF-904a (#1585): a hook or a config entry (a filter driver, an include) the tests
        # planted would run at the next git command; any change blocks every later git call.
        # A1: git_unsafe has been set since the test phase began; only a clean comparison clears it.
        if tests_ran and not identity_lost:
            git_tampered = await _git_safety_change(work_dir, git_baseline)
            if git_tampered is None:
                git_unsafe = False  # BF-904a A1: the comparison found git as it was before the tests
            else:
                # BF-904a A1: git_tampered is fixed words plus _display_token tokens, so %s can
                # neither split the record nor carry a control character (%r would double escapes).
                logger.error(
                    "BuilderAgent: git configuration or hooks changed while the tests ran (%s); "
                    "refusing to commit and running no further git command",
                    git_tampered,
                )

        # 5.5. Block commit if validation errors (syntax errors) exist. BF-904b (#1585): the refusals stand;
        # syntax is read now, on the files as the build and its tests left them.
        # BF-904b A3: only inside the work tree; an alias the tests left that leads out of it is refused unread.
        syntax_errors = _syntax_errors(Path(work_dir), list(syntax_checked))
        if identity_lost:
            result.error = (
                "Repository identity changed during the build; refused before commit"
            )
            result.success = False
        elif git_tampered is not None:
            result.error = (
                f"Git configuration or hooks changed while the tests ran ({git_tampered}); "
                "refused before commit. No further git command was run, so the checkout is "
                f"left on branch {result.branch_name}; inspect the repository's config and "
                "hooks before running git there."
            )
            result.success = False
        elif validation_errors or syntax_errors:
            # BF-904b: the lead is unchanged (the resolve route and the tests read it); refusals first.
            result.error = "Syntax errors:\n" + "\n".join(validation_errors + syntax_errors)
            result.success = False
        # 6. Commit — only if tests passed OR tests were not run
        elif written or modified_files:
            if run_tests and not result.tests_passed:
                # Try escalation hook before reporting failure to Captain (AD-347)
                if escalation_hook is not None:
                    try:
                        report = classify_build_failure(result, spec)
                        resolved = await escalation_hook(report)
                        if resolved is not None:
                            result = resolved
                    except Exception as exc:
                        logger.warning("Escalation hook failed: %s", exc)

                # If still failing after escalation attempt, report to Captain
                if run_tests and not result.tests_passed:
                    # BF-897: only a failure is "Tests failed".
                    test_outcome = result.metadata.get("targeted_tests", "failed")
                    if test_outcome == "timed_out":
                        lead = "Targeted tests timed out; no fix was requested. "
                    elif test_outcome == "not_run":
                        lead = "No targeted tests ran. "
                    else:
                        lead = "Tests failed after " + str(result.fix_attempts) + " fix attempt(s). "
                    result.error = (
                        lead
                        + "Code written to branch but NOT committed.\n"
                        + (result.test_result or "")[-1000:]
                    )
                    result.success = False
            else:
                desc_short = spec.description[:200] if spec.description else ""
                # BF-898: the files the unreviewed fix loop changed are named in the commit.
                disclosed_fix_files = result.metadata.get("fix_loop_files", [])
                commit_msg = (
                    f"{spec.title}"
                    + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                    + (f"\n\n{desc_short}" if desc_short else "")
                    + (
                        "\n\nChanged by the unreviewed test-fix loop (BF-898): "
                        + ", ".join(disclosed_fix_files)
                        if disclosed_fix_files
                        else ""
                    )
                    + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
                )
                add_attempted = True  # BF-904a: a failed commit may leave these paths staged
                ok, sha = await _git_add_and_commit(
                    written + modified_files, commit_msg, work_dir,
                )
                if ok:
                    result.commit_hash = sha
                else:
                    result.error = f"Commit failed: {sha}"

                if not result.error:
                    result.success = True
        elif file_changes:
            # BF-904a (#1585): changes were asked for and none applied (every block left its file
            # as it was): a failure with a reason, never a success with nothing to commit.
            result.error = "No change applied: " + ", ".join(
                sorted({str(change["path"]) for change in file_changes})
            )
            result.success = False  # BF-904a: a change list that changed nothing is not a success
        else:
            result.success = True

    except Exception as exc:
        result.error = str(exc)
    finally:
        # 7. BF-904a (#1585): put the operator's checkout back as the build found it. A build
        # with no commit: unstage (only if `git add` ran), write the saved bytes back, delete
        # the files it created, return to the ORIGINAL ref, and only then delete the build
        # branch. A committed build only returns. BF-896/BF-904a: when git is unsafe, no git
        # runs at all: identity lost, config or hooks changed, or the test phase ended without
        # a clean comparison (A1).
        cleanup_errors: list[str] = []
        restore_tree = not result.commit_hash
        if restore_tree:
            if add_attempted and not git_unsafe:
                unstaged = await _cleanup_git(["reset", "-q", "--", *written, *modified_files], work_dir)  # BF-904a: unstage before the restore
                if unstaged is not None:
                    cleanup_errors.append(unstaged)
            cleanup_errors.extend(_restore_pre_build_files(work_dir, originals, written))
        if git_unsafe:
            cleanup_errors.append(
                f"no git command was run after the tests, so the checkout is left on branch {build_branch}"
            )
        else:
            returned, detail = await _git_return_to(original_branch, original_commit, work_dir)
            if not returned:  # BF-904a: a failed return keeps the build branch and is reported
                start_ref = _display_token(str(original_branch or original_commit), _DISPLAY_NAME_CHARS)  # BF-904a A3: the operator's ref, escaped and bounded
                shown_detail = _display_token(detail, _DISPLAY_PATH_CHARS)  # BF-904a A3: git's answer, escaped and bounded
                cleanup_errors.append(
                    f"could not return to {start_ref}: {shown_detail}; "
                    f"branch {build_branch} kept"
                )
            elif restore_tree:
                _cleanup_log(logging.INFO, "Cleaning up failed build branch '%s'", build_branch)  # BF-904a A8 (D43)
                deleted = await _cleanup_git(["branch", "-D", build_branch], work_dir)
                if deleted is not None:
                    cleanup_errors.append(deleted)
        if cleanup_errors:
            result.metadata["cleanup_errors"] = cleanup_errors
            if result.success:
                # A successful result stays one: a commit is on the build branch, and
                # adopt_commit checks out its own branch (worktree_manager.py).
                _cleanup_log(logging.ERROR, "BuilderAgent: build cleanup incomplete: %s", "; ".join(cleanup_errors))  # BF-904a A8 (D43)
            else:
                result.error = (result.error or "Build failed") + "\nCleanup incomplete: " + "; ".join(cleanup_errors)

    # Tag builder source and record Hebbian outcome (AD-353)
    result.builder_source = builder_source
    if runtime and hasattr(runtime, "hebbian_router") and builder_source in ("native", "visiting"):
        from probos.mesh.routing import REL_BUILDER_VARIANT

        runtime.hebbian_router.record_interaction(
            "build_code", builder_source, success=result.tests_passed,
            rel_type=REL_BUILDER_VARIANT,
        )

    return result
