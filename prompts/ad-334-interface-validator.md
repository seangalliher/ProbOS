# AD-334: Interface Validator (Heisenberg Compensator)

**Transporter Pattern Step 5 of 7** — Post-assembly verification via static analysis.

## Context

The Transporter Pattern generates code in parallel chunks (AD-331/332) and assembles them (AD-333).
But parallel generation can introduce interface mismatches: Chunk A calls `process(data, strict=True)`
while Chunk B defines `process(data)` without the `strict` parameter. Or two chunks import different
names from the same module. The assembler (AD-333) merges mechanically — it doesn't verify semantic
correctness.

The Interface Validator is the **Heisenberg Compensator** — it verifies that the reassembled code
is internally consistent before handing it to `execute_approved_build()`. Named after the Star Trek
device that compensates for quantum uncertainty during transport: you can't observe a quantum state
without disturbing it, but the Heisenberg Compensator makes it work anyway.

**This is zero-LLM — pure static analysis using Python's `ast` module.**

## What to build

All code goes in `src/probos/cognitive/builder.py`. All tests go in `tests/test_builder_agent.py`.

### 1. `ValidationResult` dataclass

Add after the `BuildBlueprint` class (around line 171):

```python
@dataclass
class ValidationResult:
    """Result of post-assembly interface validation (Heisenberg Compensator).

    Captures validation errors with per-chunk attribution so the system
    knows which chunk to re-generate on failure.
    """
    valid: bool = True
    errors: list[dict[str, str]] = field(default_factory=list)
    # Each error: {"type": "...", "message": "...", "file": "...", "chunk_id": "..."}
    warnings: list[dict[str, str]] = field(default_factory=list)
    chunks_validated: int = 0
    checks_passed: int = 0
    checks_failed: int = 0
```

Fields:
- `valid` — True if no errors (warnings are OK)
- `errors` — list of error dicts, each with `type`, `message`, `file`, and optionally `chunk_id`
- `warnings` — same format, non-fatal issues
- `chunks_validated` — how many chunks had code to validate
- `checks_passed` / `checks_failed` — total check counts

### 2. `validate_assembly()` function

Signature:

```python
def validate_assembly(
    blueprint: BuildBlueprint,
    assembled_blocks: list[dict[str, Any]],
) -> ValidationResult:
```

This is the main entry point. It takes the blueprint (with `.chunks`, `.results`, and `.interface_contracts`)
and the assembled file blocks from `assemble_chunks()`, then runs all validation checks.

**Logic:**

```
result = ValidationResult()

# 1. Check each CREATE block for Python syntax validity
for block in assembled_blocks where mode == "create" and path ends with ".py":
    try ast.parse(block["content"])
    except SyntaxError as e:
        result.errors.append({"type": "syntax_error", "message": str(e), "file": block["path"], "chunk_id": _find_chunk_for_file(blueprint, block["path"])})

# 2. Check for duplicate top-level definitions within each file
for each CREATE block's AST:
    collect all top-level names (function defs, class defs, assignments)
    if any name appears more than once:
        result.errors.append({"type": "duplicate_definition", "message": f"'{name}' defined {count} times", "file": ..., "chunk_id": ...})

# 3. Check that MODIFY block search strings are non-empty
for block in assembled_blocks where mode == "modify":
    for replacement in block["replacements"]:
        if not replacement["search"].strip():
            result.errors.append({"type": "empty_search", "message": "Empty search string in replacement", "file": block["path"], "chunk_id": ...})

# 4. Check interface contracts (if blueprint has them)
for contract in blueprint.interface_contracts:
    # Contracts are free-text strings like "def process(data: str) -> Result"
    # Extract function name from contract using simple regex
    # Check that at least one CREATE block defines that function name
    if function_name not in any assembled block's top-level defs:
        result.warnings.append({"type": "unmet_contract", "message": f"Interface contract '{contract}' not found in assembled code", "file": "", "chunk_id": ""})

# 5. Confidence-aware stricter checking for low-confidence chunks
for result_obj in blueprint.results:
    if result_obj.success and result_obj.confidence <= 2:
        blocks_from_this_chunk = [b for b in assembled_blocks if _chunk_targets_file(chunk, b["path"])]
        for block in blocks_from_this_chunk:
            if block["mode"] == "create" and block["path"].endswith(".py"):
                # Check that all name references in function bodies resolve
                # to either: a local def, an import, a builtin, or a parameter
                unresolved = _find_unresolved_names(block["content"])
                for name in unresolved:
                    result.warnings.append({"type": "unresolved_name", "message": f"Name '{name}' used but not defined/imported (low-confidence chunk)", "file": block["path"], "chunk_id": result_obj.chunk_id})

result.valid = len(result.errors) == 0
result.chunks_validated = sum(1 for r in blueprint.results if r.success)
result.checks_passed = ... (count of passed checks)
result.checks_failed = len(result.errors)
return result
```

### 3. `_find_chunk_for_file()` helper

```python
def _find_chunk_for_file(blueprint: BuildBlueprint, file_path: str) -> str:
```

Returns the chunk_id of the chunk that targets the given file. If multiple chunks target it,
return the first one. If none, return empty string. This is used for error attribution.

Logic: iterate `blueprint.chunks`, return first chunk where `chunk.target_file == file_path`
or where `file_path` ends with `chunk.target_file` (handles relative vs absolute paths).

### 4. `_find_unresolved_names()` helper

```python
def _find_unresolved_names(source: str) -> list[str]:
```

Given Python source code, find names that are used but not defined locally.
Uses `ast` to walk the tree. This is a **best-effort** check — it does NOT need to be a full
type checker. Focus on obvious issues.

**Logic:**

```
tree = ast.parse(source)

# Collect defined names (top-level + nested)
defined: set[str] = set()
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        defined.add(node.name)
        # Add parameter names
        for arg in node.args.args:
            defined.add(arg.arg)
    elif isinstance(node, ast.ClassDef):
        defined.add(node.name)
    elif isinstance(node, ast.Import):
        for alias in node.names:
            defined.add(alias.asname or alias.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            defined.add(alias.asname or alias.name)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        # Simple assignment targets
        ... extract Name targets ...

# Collect used names (only ast.Name nodes in Load context)
used: set[str] = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        used.add(node.id)

# Python builtins to exclude
builtins_set = set(dir(__builtins__)) if isinstance(__builtins__, dict) else set(dir(__builtins__))
# Also exclude common typing names, common patterns
safe_names = builtins_set | {"__name__", "__file__", "__all__", "self", "cls", "super",
                              "Any", "Optional", "Union", "Dict", "List", "Set", "Tuple",
                              "Type", "Callable", "Iterator", "Generator", "Awaitable",
                              "annotations"}

unresolved = sorted(used - defined - safe_names)
return unresolved
```

**Important:** This should be conservative — it's better to miss an issue than to false-positive.
The goal is catching obvious chunk-merge errors (duplicate defs, broken imports), not replacing mypy.

## Tests

Add a new test class `TestValidateAssembly` in `tests/test_builder_agent.py`.

### Test imports

Add `validate_assembly`, `ValidationResult`, `_find_chunk_for_file`, `_find_unresolved_names` to the
existing import block from `probos.cognitive.builder`.

### Test class: `TestValidationResult` (2 tests)

```python
class TestValidationResult:
    def test_default_valid(self):
        """Fresh ValidationResult is valid with no errors."""
        r = ValidationResult()
        assert r.valid is True
        assert r.errors == []
        assert r.warnings == []

    def test_with_errors_is_invalid(self):
        """ValidationResult with errors should report as invalid when checked."""
        r = ValidationResult(valid=False, errors=[{"type": "syntax_error", "message": "bad", "file": "a.py", "chunk_id": "c1"}])
        assert r.valid is False
        assert len(r.errors) == 1
```

### Test class: `TestFindChunkForFile` (3 tests)

```python
class TestFindChunkForFile:
    def test_finds_matching_chunk(self):
        """Returns chunk_id when a chunk targets the given file."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d", target_file="src/foo.py", what_to_generate="code")]
        assert _find_chunk_for_file(bp, "src/foo.py") == "c1"

    def test_returns_empty_when_no_match(self):
        """Returns empty string when no chunk targets the file."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d", target_file="src/bar.py", what_to_generate="code")]
        assert _find_chunk_for_file(bp, "src/other.py") == ""

    def test_suffix_matching(self):
        """Matches when file_path ends with chunk's target_file (relative path handling)."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id="c1", description="d", target_file="src/foo.py", what_to_generate="code")]
        assert _find_chunk_for_file(bp, "/home/user/project/src/foo.py") == "c1"
```

### Test class: `TestFindUnresolvedNames` (3 tests)

```python
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
```

### Test class: `TestValidateAssembly` (7 tests)

```python
class TestValidateAssembly:
    def _make_blueprint_with_result(self, chunk_id="c1", target="src/foo.py", confidence=4):
        """Helper to create a blueprint with one chunk and one successful result."""
        bp = BuildBlueprint(spec=BuildSpec(title="t", description="d"))
        bp.chunks = [ChunkSpec(chunk_id=chunk_id, description="d", target_file=target, what_to_generate="code")]
        bp.results = [ChunkResult(chunk_id=chunk_id, success=True, confidence=confidence)]
        return bp

    def test_valid_assembly(self):
        """Clean Python code passes validation."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py", "content": "import os\n\ndef foo():\n    return 1\n", "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is True
        assert result.errors == []

    def test_syntax_error_detected(self):
        """Invalid Python syntax produces a syntax_error."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py", "content": "def foo(\n", "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is False
        assert any(e["type"] == "syntax_error" for e in result.errors)

    def test_duplicate_definition_detected(self):
        """Two functions with the same name at top level produce duplicate_definition."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py", "content": "def foo():\n    pass\n\ndef foo():\n    pass\n", "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is False
        assert any(e["type"] == "duplicate_definition" for e in result.errors)

    def test_empty_search_in_modify(self):
        """Empty search string in a modify replacement produces error."""
        bp = self._make_blueprint_with_result()
        blocks = [{"path": "src/foo.py", "mode": "modify", "replacements": [{"search": "", "replace": "new code"}]}]
        result = validate_assembly(bp, blocks)
        assert result.valid is False
        assert any(e["type"] == "empty_search" for e in result.errors)

    def test_non_python_files_skip_ast_checks(self):
        """Non-.py files skip AST-based validation but still pass."""
        bp = self._make_blueprint_with_result(target="src/config.yaml")
        blocks = [{"path": "src/config.yaml", "content": "key: value\n", "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is True

    def test_unmet_contract_produces_warning(self):
        """Interface contract not found in code produces warning (not error)."""
        bp = self._make_blueprint_with_result()
        bp.interface_contracts = ["def required_function(x: int) -> str"]
        blocks = [{"path": "src/foo.py", "content": "def other_function():\n    pass\n", "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        assert result.valid is True  # Warnings don't make it invalid
        assert any(w["type"] == "unmet_contract" for w in result.warnings)

    def test_low_confidence_triggers_stricter_check(self):
        """Chunks with confidence <= 2 get unresolved name warnings."""
        bp = self._make_blueprint_with_result(confidence=2)
        # 'unknown_func' is not defined or imported
        blocks = [{"path": "src/foo.py", "content": "def foo():\n    return unknown_func()\n", "mode": "create", "after_line": None}]
        result = validate_assembly(bp, blocks)
        # Should have warning about unresolved name (not error — it's a warning for low-confidence)
        assert any(w["type"] == "unresolved_name" for w in result.warnings)
```

## Implementation constraints

1. **Zero LLM** — no LLM calls anywhere. Pure `ast` module + string processing.
2. **Conservative** — better to miss an issue than false-positive. This is a safety net, not mypy.
3. **Per-chunk attribution** — every error/warning carries a `chunk_id` so the system knows which chunk to re-generate. Use `_find_chunk_for_file()` for attribution.
4. **Existing patterns** — follow the same code style as AD-330/331/332/333 (module-level functions, not methods on a class).
5. **Placement** — add code after `assembly_summary()` and before the git helpers section (`_sanitize_branch_name`).
6. **Import `ast`** — already imported at top of builder.py.
7. **Test placement** — add test classes at the end of `tests/test_builder_agent.py`, after existing test classes.
8. **Do NOT modify** any existing functions or tests.
9. **15 total tests** across 4 test classes (2 + 3 + 3 + 7 = 15).
