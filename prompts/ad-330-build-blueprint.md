# AD-330: BuildBlueprint & ChunkSpec — Pattern Buffer Data Structures

*"The transporter's pattern buffer stores the complete molecular pattern — every atom in its place. Without it, you're just disassembling matter and hoping for the best."*

The Transporter Pattern (Northstar II Phase 1) brings MapReduce-style code generation to the Builder: decompose large builds into independent chunks, generate them in parallel with focused context, then assemble the results. AD-330 establishes the foundational data structures — the "pattern buffer" that holds the molecular blueprint of a build before it's decomposed into matter streams.

Currently `BuildSpec` is a flat specification: title, description, target files, reference files, test files. It has no concept of interface contracts, chunk boundaries, or inter-chunk dependencies. The Builder generates everything in a single monolithic LLM call, which works for small changes but fails for large multi-file builds that exceed context budgets or timeout the proxy.

AD-330 introduces two new dataclasses:
- **`BuildBlueprint`** — wraps a `BuildSpec` with structural metadata: interface contracts (function signatures, class APIs that all chunks must conform to), shared imports (common dependencies every chunk needs), and chunk hints (suggested decomposition boundaries). This is the "truth document" that the ChunkDecomposer (AD-331) will analyze to produce chunk plans.
- **`ChunkSpec`** — a single unit of work for parallel execution: what to generate, what context it needs, what it produces, and which other chunks it depends on.
- **`ChunkResult`** — output from a single chunk execution: generated code, rationale, output signature, and a confidence score (1-5) for downstream conflict resolution.

**Current AD count:** AD-336. This prompt implements AD-330.
**Current test count:** 1,972 pytest + 30 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/builder.py` — full file. Focus on:
   - `BuildSpec` dataclass (lines 30-41) — AD-330 extends this, doesn't replace it
   - `BuildResult` dataclass (lines 44-58) — `ChunkResult` parallels this at chunk level
   - `BuilderAgent.instructions` (lines 163-205) — LLM instruction format (unchanged in this AD)
   - `_parse_file_blocks()` (lines 538-601) — `ChunkResult.generated_code` will eventually be parsed by this format
   - `_LOCALIZE_THRESHOLD` (line 217) — AD-336 will use this as the Transporter activation threshold
2. `src/probos/types.py` — read `LLMRequest`, `LLMResponse`, `TaskNode`, `TaskDAG` for structural patterns. The new dataclasses should follow the same style (dataclass with defaults, field factories for mutable defaults)
3. `tests/test_builder_agent.py` — full file. Focus on `TestBuildSpec` and `TestBuildResult` (lines 32-74) for test patterns. New tests should follow the same style
4. `docs/development/roadmap.md` — search for "AD-330" and read the full AD-330 description plus the Sensory Cortex Architecture introduction (provides design rationale)

---

## What To Build

### Step 1: Create the data structures (AD-330)

**File:** `src/probos/cognitive/builder.py`

Add three new dataclasses **after** `BuildResult` (after line 58) and **before** the existing agent class. These are pure data — no methods beyond what's described below.

**1a. `ChunkSpec` dataclass**

A single unit of parallel work in the Transporter Pattern:

```python
@dataclass
class ChunkSpec:
    """A single unit of work for parallel chunk execution (Transporter Pattern).

    Each chunk specifies what to generate, what context it needs,
    what it produces, and which other chunks it depends on.
    """

    chunk_id: str                                    # Unique ID, e.g. "chunk-0", "chunk-1"
    description: str                                 # Human-readable: "Add _verify_response() method to runtime"
    target_file: str                                 # Single file this chunk generates into
    what_to_generate: str                            # Specific instruction: "function", "class", "test_class", etc.
    required_context: list[str] = field(default_factory=list)
        # Lines of context this chunk needs: interface signatures, imports, type defs.
        # NOT full file content — only the slices relevant to this chunk.
    expected_output: str = ""                        # What this chunk should produce: "def verify(self, ...) -> bool"
    depends_on: list[str] = field(default_factory=list)
        # chunk_ids this chunk depends on (must complete first).
        # Forms a DAG. Empty = independent, can run in parallel.
    constraints: list[str] = field(default_factory=list)
        # Additional constraints: "must import from types", "must be async", etc.
```

**1b. `ChunkResult` dataclass**

Output from a single chunk's LLM generation. Follows a **Structured Information Protocol** adapted from LLM×MapReduce (Zhou et al., 2024):

```python
@dataclass
class ChunkResult:
    """Result from a single chunk's LLM generation (Transporter Pattern).

    Uses a Structured Information Protocol: generated code, rationale
    for decisions, output signature, and confidence score for
    downstream conflict resolution during assembly.
    """

    chunk_id: str                                    # Matches the ChunkSpec.chunk_id
    success: bool = False
    generated_code: str = ""                         # The generated code (in file-block format)
    decisions: str = ""                              # Rationale: why specific implementation choices were made
    output_signature: str = ""                       # What was actually produced (may differ from expected_output)
    confidence: int = 3                              # 1-5: contextual completeness
        # 5 = full interface contracts + reference code available
        # 4 = interface contracts available, some reference code
        # 3 = description only, reasonable inference
        # 2 = minimal context, significant guesswork
        # 1 = near-blind generation, very low confidence
    error: str = ""                                  # Error message if success=False
    tokens_used: int = 0                             # Tokens consumed for this chunk
```

**1c. `BuildBlueprint` dataclass**

Enhanced build specification that wraps a `BuildSpec` with structural metadata for chunk decomposition:

```python
@dataclass
class BuildBlueprint:
    """Enhanced build specification with structural metadata for chunk decomposition.

    The 'pattern buffer' — contains the interface contracts, shared context,
    and decomposition hints that the ChunkDecomposer uses to break the build
    into parallel ChunkSpecs.
    """

    spec: BuildSpec                                  # The original build specification
    interface_contracts: list[str] = field(default_factory=list)
        # Function signatures, class APIs, type definitions that ALL chunks
        # must conform to. These are the "ground truth" — any chunk output
        # that violates an interface contract is wrong.
        # Example: "def process(self, data: dict[str, Any]) -> ProcessResult:"
    shared_imports: list[str] = field(default_factory=list)
        # Import statements that every chunk needs. Prevents each chunk
        # from independently guessing what to import.
        # Example: "from probos.types import IntentMessage, IntentResult"
    shared_context: str = ""
        # Additional context shared across all chunks: module docstring,
        # class-level constants, base class definition, etc.
    chunk_hints: list[str] = field(default_factory=list)
        # Suggested decomposition boundaries from the Architect's proposal.
        # Example: "one chunk per new method", "tests in separate chunk"
        # Hints are advisory — the ChunkDecomposer may ignore them.
    chunks: list[ChunkSpec] = field(default_factory=list)
        # Populated by ChunkDecomposer (AD-331). Empty at creation time.
    results: list[ChunkResult] = field(default_factory=list)
        # Populated by Chunk Execution (AD-332). Empty until execution.
```

**1d. Add a helper method to `BuildBlueprint`**

A method that validates the chunk DAG has no cycles (a prerequisite for parallel execution):

```python
def validate_chunk_dag(self) -> tuple[bool, str]:
    """Validate that chunk dependencies form a DAG (no cycles).

    Returns (True, "") if valid, (False, error_message) if cycles detected.
    Uses Kahn's algorithm for topological sort.
    """
    if not self.chunks:
        return True, ""

    # Build adjacency from depends_on
    in_degree: dict[str, int] = {c.chunk_id: 0 for c in self.chunks}
    dependents: dict[str, list[str]] = {c.chunk_id: [] for c in self.chunks}

    for chunk in self.chunks:
        for dep_id in chunk.depends_on:
            if dep_id not in in_degree:
                return False, f"Chunk '{chunk.chunk_id}' depends on unknown chunk '{dep_id}'"
            dependents[dep_id].append(chunk.chunk_id)
            in_degree[chunk.chunk_id] += 1

    # Kahn's algorithm
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
```

**1e. Add a helper method to `BuildBlueprint` for execution ordering**

```python
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
```

---

### Step 2: Add factory method for creating blueprints from BuildSpec

**File:** `src/probos/cognitive/builder.py`

Add a module-level factory function after the dataclass definitions:

```python
def create_blueprint(spec: BuildSpec) -> BuildBlueprint:
    """Create a BuildBlueprint from a BuildSpec with no chunk decomposition.

    This is the entry point for the Transporter Pattern.
    The blueprint starts with empty chunks — the ChunkDecomposer (AD-331)
    populates them later.
    """
    return BuildBlueprint(spec=spec)
```

---

### Step 3: Write tests

**File:** `tests/test_builder_agent.py`

Add new test classes after the existing `TestBuildResult` class (after line 74). Follow the existing test style (pytest functions in classes, `assert` statements, no fixtures).

**3a. `TestChunkSpec` class** — 3 tests:

1. `test_defaults` — create a `ChunkSpec` with only required fields (`chunk_id`, `description`, `target_file`, `what_to_generate`), verify all optional fields have correct defaults (empty lists/strings)
2. `test_full_population` — create a `ChunkSpec` with all fields populated, verify every field
3. `test_depends_on` — create a `ChunkSpec` with `depends_on=["chunk-0"]`, verify the dependency is stored

**3b. `TestChunkResult` class** — 3 tests:

1. `test_defaults` — create with only `chunk_id`, verify `success=False`, `confidence=3`, `generated_code=""`, etc.
2. `test_success` — create a successful `ChunkResult` with `success=True`, `confidence=5`, `generated_code="def foo(): pass"`, verify all
3. `test_confidence_range` — create results with `confidence=1` and `confidence=5`, verify they store correctly (no validation — just storage)

**3c. `TestBuildBlueprint` class** — 6 tests:

1. `test_from_spec` — create via `create_blueprint(spec)`, verify `spec` is stored, `chunks` and `results` are empty lists, other fields are defaults
2. `test_interface_contracts` — create with `interface_contracts=["def foo(x: int) -> str:"]`, verify stored
3. `test_shared_imports` — create with `shared_imports=["from probos.types import LLMRequest"]`, verify stored
4. `test_validate_dag_empty` — call `validate_chunk_dag()` on blueprint with no chunks → `(True, "")`
5. `test_validate_dag_valid` — add 3 chunks: chunk-0 (no deps), chunk-1 (depends on chunk-0), chunk-2 (depends on chunk-0). Validate → `(True, "")`
6. `test_validate_dag_cycle` — add 2 chunks: chunk-0 (depends on chunk-1), chunk-1 (depends on chunk-0). Validate → `(False, "Cycle detected...")`

**3d. `TestGetReadyChunks` class** — 4 tests:

1. `test_all_independent` — 3 chunks with no deps → all 3 returned
2. `test_with_dependencies` — chunk-0 (no deps), chunk-1 (depends on chunk-0), chunk-2 (depends on chunk-1). `completed=set()` → `[chunk-0]`. `completed={"chunk-0"}` → `[chunk-1]`. `completed={"chunk-0", "chunk-1"}` → `[chunk-2]`
3. `test_none_completed` — call with `completed=None` → same as empty set
4. `test_unknown_dep_in_validate` — chunk with `depends_on=["nonexistent"]` → `validate_chunk_dag()` returns `(False, "...depends on unknown...")`

**3e. `TestCreateBlueprint` class** — 1 test:

1. `test_factory` — create a `BuildSpec`, pass to `create_blueprint()`, verify returned `BuildBlueprint` has the spec, empty chunks/results/contracts/imports

---

### Step 4: Update imports

**File:** `src/probos/cognitive/builder.py`

No new imports should be needed — the dataclasses use only `dataclass`, `field` (already imported), and built-in types.

Verify the new dataclasses are importable from the module:

```python
from probos.cognitive.builder import (
    BuildSpec, BuildResult,  # existing
    ChunkSpec, ChunkResult, BuildBlueprint, create_blueprint,  # new (AD-330)
)
```

---

## Constraints

- **Pure data structures only** — no LLM calls, no file I/O, no network. This AD is foundation; behavior comes in AD-331+
- **Do NOT modify existing code** — `BuildSpec`, `BuildResult`, `BuilderAgent`, `execute_approved_build()` etc. remain unchanged. The new structures sit alongside them
- **Follow existing patterns** — use `@dataclass`, `field(default_factory=list)`, type annotations. Same style as `BuildSpec` and `TaskNode`
- **No new files** — everything goes in `builder.py` (data structures) and `test_builder_agent.py` (tests). The Transporter pattern stays in the same module until it grows large enough to warrant extraction (AD-336 decision)
- **17 new tests** — 3 + 3 + 6 + 4 + 1 = 17 tests

---

## Verification

After completing all steps:

1. Run `python -m pytest tests/test_builder_agent.py -v` — all existing + new tests pass
2. Run `python -m pytest tests/ -x --timeout=30` — full test suite passes (no regressions)
3. Verify the new classes appear in module-level imports: `python -c "from probos.cognitive.builder import ChunkSpec, ChunkResult, BuildBlueprint, create_blueprint; print('OK')"`
