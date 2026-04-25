# AD-331: ChunkDecomposer — Dematerializer

*"The dematerializer breaks matter into its constituent patterns. It must know exactly where the seams are — cut along the grain, never against it."*

The ChunkDecomposer takes a `BuildBlueprint` (AD-330) and produces a list of `ChunkSpec` entries — the parallel work units that the matter stream (AD-332) will execute concurrently. This is the critical planning step: good decomposition means each chunk is small enough for a single focused LLM call, carries only the context it needs, and produces output that assembles cleanly.

AD-331 uses an LLM call (fast tier) to analyze the build spec and determine chunk boundaries, then programmatically constructs the `ChunkSpec` list with context slices from CodebaseIndex and the blueprint's interface contracts. The decomposer validates coverage (every target file has at least one chunk) and DAG correctness (no cycles in dependencies) before returning.

**Current AD count:** AD-336. This prompt implements AD-331.
**Current test count:** 1,989 pytest + 30 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/builder.py` — full file. Focus on:
   - `ChunkSpec`, `ChunkResult`, `BuildBlueprint`, `create_blueprint()` (lines 61-181) — the data structures this AD populates
   - `BuilderAgent._build_file_outline()` (lines 342-390) — AST outline builder, reuse for context extraction
   - `BuilderAgent._localize_context()` (lines 392-492) — similar pattern (fast-tier LLM to analyze code structure)
   - `BuilderAgent.perceive()` (lines 512-586) — how files are read with path resolution
   - `BuilderAgent._LOCALIZE_THRESHOLD` (line 339) — 20,000 chars threshold
2. `src/probos/cognitive/codebase_index.py` — read the class definition and these methods: `get_imports()` (line 397), `find_importers()` (line 406), `get_api_surface()` (line 239), `get_full_api_surface()` (line 390), `read_source()` (line 243). The decomposer optionally uses CodebaseIndex to discover import relationships and class structure when available.
3. `src/probos/types.py` — read `LLMRequest` (lines 186-195) for fast-tier LLM call pattern
4. `tests/test_builder_agent.py` — full file. Understand existing test patterns, especially `TestBuildBlueprint` and `TestGetReadyChunks` (the new tests will follow the same style)

---

## What To Build

### Step 1: Add the `decompose_blueprint()` async function (AD-331)

**File:** `src/probos/cognitive/builder.py`

Add a new module-level async function **after** `create_blueprint()` (after line 181) and **before** the git helpers section. This is the Dematerializer.

```python
async def decompose_blueprint(
    blueprint: BuildBlueprint,
    llm_client: Any,
    codebase_index: Any | None = None,
    work_dir: str | None = None,
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
```

**Implementation details:**

**1a. Resolve work_dir and read target files**

```python
    project_root = Path(work_dir) if work_dir else Path(__file__).resolve().parent.parent.parent
    spec = blueprint.spec

    # Read target files to understand their structure
    target_contents: dict[str, str] = {}
    for path in spec.target_files:
        full = Path(path) if Path(path).is_absolute() else project_root / path
        if full.exists() and full.is_file():
            target_contents[path] = full.read_text(encoding="utf-8")
```

**1b. Build structural analysis for the LLM**

Build AST outlines for each target file (reuse `BuilderAgent._build_file_outline()`), and gather import data from CodebaseIndex if available:

```python
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
```

**1c. LLM call to determine chunk boundaries**

Use a fast-tier LLM call to analyze the blueprint and suggest decomposition. The LLM returns a JSON list of chunk definitions:

```python
    import json

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
            return _fallback_decompose(blueprint)

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
            return _fallback_decompose(blueprint)

    except Exception as exc:
        logger.warning("ChunkDecomposer: failed (%s), using fallback decomposition", exc)
        return _fallback_decompose(blueprint)
```

**1d. Convert LLM output into ChunkSpec objects**

```python
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
```

**1e. Validate and assign chunks**

```python
    blueprint.chunks = chunks

    # Validate
    valid, err = blueprint.validate_chunk_dag()
    if not valid:
        logger.warning("ChunkDecomposer: invalid DAG (%s), using fallback", err)
        return _fallback_decompose(blueprint)

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
    return blueprint
```

---

### Step 2: Add the `_build_chunk_context()` helper

**File:** `src/probos/cognitive/builder.py`

Add this helper **before** `decompose_blueprint()` (between `create_blueprint()` and `decompose_blueprint()`):

```python
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
```

---

### Step 3: Add the `_fallback_decompose()` helper

**File:** `src/probos/cognitive/builder.py`

Add this helper **before** `_build_chunk_context()`. The fallback creates one chunk per target file + one chunk for all test files — no LLM needed:

```python
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
        for j, test_path in enumerate(spec.test_files):
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
```

---

### Step 4: Write tests

**File:** `tests/test_builder_agent.py`

Add new test classes. You will need to import `decompose_blueprint`, `_fallback_decompose`, and `_build_chunk_context` alongside the existing imports from `probos.cognitive.builder`.

**4a. `TestFallbackDecompose` class** — 4 tests:

1. `test_single_target` — spec with 1 target file, no test files → 1 chunk, no deps
2. `test_multiple_targets` — spec with 3 target files, no test files → 3 chunks, no deps
3. `test_with_test_files` — spec with 2 target files and 1 test file → 3 chunks. Test chunk `depends_on` = [`chunk-0`, `chunk-1`]
4. `test_empty_spec` — spec with no target files, no test files → 0 chunks

**4b. `TestBuildChunkContext` class** — 4 tests:

1. `test_with_contracts` — blueprint with `interface_contracts=["def foo(): ..."]` → context list includes "## Interface Contracts" entry
2. `test_with_shared_imports` — blueprint with `shared_imports=["import os"]` → context includes "## Shared Imports" entry
3. `test_with_target_content` — pass `target_contents={"src/foo.py": "class Foo:\n    def bar(self): pass"}` → context includes "## Target File Structure" (outline) and "## Target File Imports"
4. `test_empty_blueprint` — blueprint with no contracts, no imports, no shared context, target file not in contents → empty context list

**4c. `TestDecomposeBlueprint` class** — 6 tests:

All tests use `MockLLMClient` from `tests/conftest.py` (or inline mock). The LLM should return valid JSON chunk definitions.

1. `test_basic_decomposition` — Set up MockLLMClient to return `{"chunks": [{"description": "Add function", "target_file": "src/foo.py", "what_to_generate": "function", "depends_on": [], "constraints": []}]}`. Call `decompose_blueprint()`. Verify: blueprint has 1 chunk, chunk_id="chunk-0", target_file correct, depends_on empty.

2. `test_multi_chunk` — LLM returns 3 chunks (2 impl + 1 test with `depends_on: [0, 1]`). Verify: 3 ChunkSpecs, test chunk depends on `["chunk-0", "chunk-1"]`. DAG is valid.

3. `test_fallback_on_llm_error` — LLM returns an error response (`response.error = "timeout"`). Verify: falls back gracefully, blueprint has chunks (one per target file).

4. `test_fallback_on_invalid_json` — LLM returns `"not json at all"`. Verify: falls back gracefully, blueprint has chunks.

5. `test_coverage_gap_filled` — LLM returns chunks covering `src/a.py` but NOT `src/b.py` (which is in spec.target_files). Verify: decomposer adds a catch-all chunk for `src/b.py`.

6. `test_fallback_on_cycle` — LLM returns chunks where chunk-0 depends on chunk-1 and chunk-1 depends on chunk-0. Verify: cycle detected, falls back to fallback decomposition.

For the MockLLMClient in these tests, use a simple inline pattern:

```python
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
```

---

## Constraints

- **Fast-tier LLM only** — the decomposition call uses `tier="fast"` (cheap/fast model). The expensive deep model is reserved for actual code generation in AD-332
- **No code generation** — the decomposer plans what to build, not how. It produces ChunkSpecs (work plans), not code
- **Fallback is mandatory** — if the LLM fails, returns bad JSON, or produces an invalid DAG, the decomposer MUST fall back to `_fallback_decompose()` rather than raising. The Transporter Pattern must be robust
- **Do NOT modify existing methods** — `perceive()`, `act()`, `_localize_context()`, `execute_approved_build()` etc. remain unchanged. Integration comes in AD-336
- **CodebaseIndex is optional** — the function works without it (codebase_index=None). It's a nice-to-have for richer context, not a requirement
- **14 new tests** — 4 + 4 + 6 = 14 tests
- **No new files** — everything in `builder.py` and `test_builder_agent.py`

---

## Verification

After completing all steps:

1. Run `python -m pytest tests/test_builder_agent.py -v` — all existing + new tests pass
2. Run `python -m pytest tests/ -x --timeout=30` — full test suite passes (no regressions)
3. Verify imports: `python -c "from probos.cognitive.builder import decompose_blueprint, _fallback_decompose, _build_chunk_context; print('OK')"`
