"""BuilderAgent — code generation via LLM with Captain approval (AD-302/303).

A CognitiveAgent in the Engineering team that accepts structured build specs,
generates code via the deep LLM tier, parses file changes from the LLM output,
and returns them for Captain approval.  After approval, `execute_approved_build()`
orchestrates: git branch → write files → pytest → commit → return to main.
"""

from __future__ import annotations

import asyncio
import ast
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent


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


# ---------------------------------------------------------------------------
# Transporter Pattern data classes (AD-330)
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
    llm_client: Any,
    codebase_index: Any | None = None,
    work_dir: str | None = None,
    on_event: Any | None = None,
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
                pass
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
                asyncio.ensure_future(on_event("transporter_decomposed", {
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
                asyncio.ensure_future(on_event("transporter_decomposed", {
                    "chunk_count": len(blueprint.chunks),
                    "chunks": [{"chunk_id": c.chunk_id, "description": c.description, "target_file": c.target_file} for c in blueprint.chunks],
                    "fallback": True,
                }))
            return blueprint

    except Exception as exc:
        logger.warning("ChunkDecomposer: failed (%s), using fallback decomposition", exc)
        blueprint = _fallback_decompose(blueprint)
        if on_event:
            asyncio.ensure_future(on_event("transporter_decomposed", {
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
            asyncio.ensure_future(on_event("transporter_decomposed", {
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
        asyncio.ensure_future(on_event("transporter_decomposed", {
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
    llm_client: Any,
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
    llm_client: Any,
    per_chunk_timeout: float = 120.0,
    max_retries: int = 1,
    on_event: Any | None = None,
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
            await on_event("transporter_wave_start", {
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
                await on_event("transporter_chunk_done", {
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
        await on_event("transporter_execution_done", {
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
    rt._emit_event("transporter_assembled", {
        "build_id": build_id,
        "file_count": len(assembled_blocks),
        "summary": assembly_summary(blueprint),
    })

    rt._emit_event("transporter_validated", {
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


async def transporter_build(
    spec: BuildSpec,
    llm_client: Any,
    work_dir: str | None = None,
    codebase_index: Any | None = None,
    on_event: Any | None = None,
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
            def _emit_event(self_, event_type, data):
                asyncio.ensure_future(on_event(event_type, data))
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


async def _run_git(args: list[str], work_dir: str) -> tuple[int, str, str]:
    """Run a git command asynchronously.  Returns (returncode, stdout, stderr).

    Uses subprocess.run in a thread executor for Windows compatibility —
    asyncio.create_subprocess_exec requires ProactorEventLoop which
    uvicorn/FastAPI may not provide.
    """

    def _sync_run() -> tuple[int, str, str]:
        result = subprocess.run(
            ["git", *args],
            cwd=work_dir,
            capture_output=True,
        )
        return (
            result.returncode,
            (result.stdout or b"").decode(errors="replace").strip(),
            (result.stderr or b"").decode(errors="replace").strip(),
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_run)


async def _git_current_branch(work_dir: str) -> str:
    """Return the name of the current branch."""
    rc, out, _err = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], work_dir)
    return out if rc == 0 else "main"


async def _git_create_branch(branch_name: str, work_dir: str) -> tuple[bool, str]:
    """Create and checkout a new git branch.  Returns (success, message)."""
    safe = _sanitize_branch_name(branch_name)
    rc, out, err = await _run_git(["checkout", "-b", safe], work_dir)
    if rc != 0:
        return False, err or out
    return True, safe


async def _git_add_and_commit(
    files: list[str], message: str, work_dir: str,
) -> tuple[bool, str]:
    """Stage *files* and commit.  Returns (success, commit_hash_or_error)."""
    rc, _out, err = await _run_git(["add", *files], work_dir)
    if rc != 0:
        return False, err

    rc, out, err = await _run_git(["commit", "-m", message], work_dir)
    if rc != 0:
        return False, err or out

    # Get commit hash
    rc2, sha, _ = await _run_git(["rev-parse", "--short", "HEAD"], work_dir)
    return True, sha if rc2 == 0 else "unknown"


async def _git_checkout_main(work_dir: str) -> tuple[bool, str]:
    """Switch back to main branch.  Returns (success, message)."""
    rc, out, err = await _run_git(["checkout", "main"], work_dir)
    if rc != 0:
        return False, err or out
    return True, "switched to main"


# ---------------------------------------------------------------------------
# BuilderAgent (AD-302)
# ---------------------------------------------------------------------------

class BuilderAgent(CognitiveAgent):
    """Engineering agent that generates code from build specifications."""

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

        # Step 4: Check if Transporter Pattern should be used
        spec = BuildSpec(
            title=params.get("title", ""),
            description=params.get("description", ""),
            target_files=target_files,
            reference_files=reference_files,
            test_files=params.get("test_files", []),
            ad_number=params.get("ad_number", 0),
            constraints=params.get("constraints", []),
        )
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

        return obs

    async def decide(self, observation: dict) -> dict:
        """Short-circuit LLM call when Transporter has already produced results."""
        result = getattr(self, "_transporter_result", None)
        if result:
            self._transporter_result = None  # Consume once
            return result
        return await super().decide(observation)

    def _build_user_message(self, observation: dict) -> str:
        """Format the build spec and reference files into an LLM prompt."""
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
        if decision.get("action") == "error":
            logger.warning("Builder act: LLM returned error: %s", decision.get("reason"))
            return {"success": False, "error": decision.get("reason")}

        # Transporter Pattern result — blocks already parsed
        if decision.get("action") == "transporter_complete":
            file_changes = decision.get("file_changes", [])
            return {
                "success": True,
                "result": {
                    "file_changes": file_changes,
                    "llm_output": decision.get("llm_output", ""),
                    "change_count": len(file_changes),
                },
            }
            return {"success": False, "error": decision.get("reason")}

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


# ---------------------------------------------------------------------------
# Test & fix helpers (AD-314)
# ---------------------------------------------------------------------------

async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
    import sys

    def _sync_run() -> tuple[int, str]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"],
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
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
        "fix the bug, don't refactor."
    )


# ---------------------------------------------------------------------------
# Post-approval execution pipeline (AD-303)
# ---------------------------------------------------------------------------

async def execute_approved_build(
    file_changes: list[dict[str, Any]],
    spec: BuildSpec,
    work_dir: str,
    run_tests: bool = True,
    max_fix_attempts: int = 2,
    llm_client: Any | None = None,
) -> BuildResult:
    """Execute an approved build: write files, run tests, create git branch.

    Called AFTER the Captain reviews the BuilderAgent's output and approves
    the changes.  The agent generates the plan; this function executes it.
    """
    result = BuildResult(success=False, spec=spec)

    # 1. Save current branch
    original_branch = await _git_current_branch(work_dir)

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

    written: list[str] = []
    modified_files: list[str] = []
    validation_errors: list[str] = []
    try:
        # 4. Write/modify files
        for change in file_changes:
            path = Path(work_dir) / change["path"]
            if change["mode"] == "modify":
                if not path.exists():
                    logger.warning(
                        "BuilderAgent: MODIFY target %s does not exist, skipping",
                        change["path"],
                    )
                    continue

                original = path.read_text(encoding="utf-8")
                modified = original

                for i, repl in enumerate(change.get("replacements", [])):
                    search_text = repl["search"]
                    replace_text = repl["replace"]

                    if search_text not in modified:
                        logger.warning(
                            "BuilderAgent: SEARCH block %d not found in %s, "
                            "skipping this replacement",
                            i, change["path"],
                        )
                        continue

                    # Replace first occurrence only
                    modified = modified.replace(search_text, replace_text, 1)

                if modified != original:
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

                # Validate Python files after modify
                err = _validate_python(path)
                if err:
                    validation_errors.append(err)

                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change["content"], encoding="utf-8")
            written.append(change["path"])
            logger.info("BuilderAgent: wrote %s", change["path"])

            # Validate Python files after create
            err = _validate_python(path)
            if err:
                validation_errors.append(err)

        result.files_written = written
        result.files_modified = modified_files

        # 4b. Code review (AD-341)
        if llm_client and (written or modified_files):
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

        # 5. Run tests with fix loop (AD-314)
        if run_tests and (written or modified_files):
            all_changes = list(file_changes)  # track for fix prompt
            for attempt in range(1 + max_fix_attempts):
                passed, test_output = await _run_tests(work_dir)
                result.test_result = test_output
                result.tests_passed = passed

                if passed:
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
                        result.fix_attempts += 1
                        continue

                    # Apply fix changes
                    for change in fix_changes:
                        path = Path(work_dir) / change["path"]
                        if change["mode"] == "modify":
                            if not path.exists():
                                continue
                            original = path.read_text(encoding="utf-8")
                            mod = original
                            for repl in change.get("replacements", []):
                                if repl["search"] in mod:
                                    mod = mod.replace(
                                        repl["search"], repl["replace"], 1,
                                    )
                            if mod != original:
                                path.write_text(mod, encoding="utf-8")
                                if change["path"] not in modified_files:
                                    modified_files.append(change["path"])
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(
                                change["content"], encoding="utf-8",
                            )
                            if change["path"] not in written:
                                written.append(change["path"])
                        err = _validate_python(path)
                        if err:
                            validation_errors.append(err)

                    all_changes.extend(fix_changes)
                    result.fix_attempts += 1
                else:
                    # No LLM client or exhausted retries
                    if attempt < max_fix_attempts:
                        result.fix_attempts += 1

            result.files_written = written
            result.files_modified = modified_files

        # 6. Commit — only if tests passed OR tests were not run
        if written or modified_files:
            if run_tests and not result.tests_passed:
                result.error = (
                    "Tests failed after " + str(result.fix_attempts) + " fix attempt(s). "
                    "Code written to branch but NOT committed.\n"
                    + (result.test_result or "")[-1000:]
                )
                result.success = False
            else:
                desc_short = spec.description[:200] if spec.description else ""
                commit_msg = (
                    f"{spec.title}"
                    + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                    + (f"\n\n{desc_short}" if desc_short else "")
                    + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
                )
                ok, sha = await _git_add_and_commit(
                    written + modified_files, commit_msg, work_dir,
                )
                if ok:
                    result.commit_hash = sha
                else:
                    result.error = f"Commit failed: {sha}"

        if validation_errors:
            result.error = "Syntax errors:\n" + "\n".join(validation_errors)
            result.success = False
        elif not (run_tests and not result.tests_passed):
            result.success = True

    except Exception as exc:
        result.error = str(exc)
    finally:
        # 7. Return to original branch
        await _git_checkout_main(work_dir)

    return result
