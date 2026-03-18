# AD-315: CodebaseIndex Import Graph + Architect Pattern Discovery

*"A First Officer who traces the wiring before presenting the schematics."*

After AD-311/312, the Architect reads full source of LLM-selected files, discovers test files, and verifies API surfaces. But it still has a critical blind spot: **it doesn't follow imports**. When the Architect selected `experience/shell.py` for a `/agents` command, it missed `experience/panels.py` — the file that actually renders every shell command's output — because `panels` wasn't in the keyword matches. A human developer would immediately see `from probos.experience import panels` at the top of `shell.py` and read `panels.py` too.

This prompt adds import graph tracing to close that gap:

1. **AD-315a:** Build an import graph in CodebaseIndex at index time using AST parsing.
2. **AD-315b:** Add `get_imports()` and `find_importers()` query methods.
3. **AD-315c:** Upgrade Architect Layer 2b to trace imports of selected files and include imported modules in the context.

**Current AD count:** AD-312. This prompt uses AD-315.
**Current test count:** 1860 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files completely before writing any code:

1. `src/probos/cognitive/codebase_index.py` — full file (~546 lines). Pay close attention to:
   - `_analyze_file()` (line 373) — you're adding import extraction here
   - `_file_tree` dict (line 80) — `rel_path → {path, docstring, classes}` — you'll add `imports` key
   - `find_callers()` (line 311) — pattern to follow for new methods
   - `find_tests_for()` (line 340) — pattern to follow
   - `_caller_cache` (line 85) — caching pattern to reuse
   - `build()` (line 92) — understand the build sequence

2. `src/probos/cognitive/architect.py` — full file (~574 lines). Pay close attention to:
   - Layer 2a (lines 206-261) — LLM file selection, `selected_paths` list
   - Layer 2b (lines 262-289) — full source reading with budget
   - Layer 2c (lines 291-333) — test/caller/API discovery — you're adding import tracing here
   - `instructions` system prompt (lines 72-168) — you'll update the context description

3. `tests/test_codebase_index.py` — full file. Understand:
   - `index` fixture (line 20) — builds from real source root
   - `TestStructuredQueries` class (line 284) — pattern for new tests
   - `TestProjectDocs.doc_index` fixture (line 119) — pattern for temp dir fixtures

4. `tests/test_architect_agent.py` — full file. Understand:
   - `_make_mock_index_with_source()` helper (line 739) — you'll add `get_imports`/`find_importers` to it
   - `_make_agent()` helper (line 458)
   - `TestDeepLocalize` class (line 755) — add new tests here

---

## What To Build

### Step 1: Import Graph in CodebaseIndex (AD-315a)

**File:** `src/probos/cognitive/codebase_index.py` (existing)

**1a. Add import extraction to `_analyze_file()`**

Modify `_analyze_file()` to also extract `import` and `from X import Y` statements using the AST:

```python
# Inside _analyze_file(), after the existing class walking loop:

# Extract import statements
imports: list[dict[str, str]] = []
for node in ast.iter_child_nodes(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            imports.append({"module": alias.name, "name": alias.asname or alias.name})
    elif isinstance(node, ast.ImportFrom):
        if node.module:
            for alias in node.names:
                imports.append({
                    "module": node.module,
                    "name": alias.name,
                })
meta["imports"] = imports
```

Note: Only extract top-level imports (direct children of the module), not imports inside functions. We only care about `probos.*` imports for the graph — external packages are noise. Filter to `probos.` prefix when building the graph.

**1b. Build `_import_graph` and `_reverse_import_graph` in `build()`**

After the file scan loop completes in `build()` (after line 106), build two dicts:

```python
# Build import graph: file → list of files it imports
self._import_graph: dict[str, list[str]] = {}     # rel_path → [imported_rel_paths]
self._reverse_import_graph: dict[str, list[str]] = {}  # rel_path → [files_that_import_it]

for rel, meta in self._file_tree.items():
    if rel.startswith("docs:"):
        continue
    imported_paths: list[str] = []
    for imp in meta.get("imports", []):
        module = imp["module"]
        if not module.startswith("probos."):
            continue
        # Convert module path to file path: probos.experience.panels → experience/panels.py
        parts = module.split(".")
        # Strip "probos" prefix
        rel_parts = parts[1:]  # e.g. ["experience", "panels"]
        # Try as module file
        candidate = "/".join(rel_parts) + ".py"
        if candidate in self._file_tree:
            imported_paths.append(candidate)
        else:
            # Try as package __init__
            candidate_init = "/".join(rel_parts) + "/__init__.py"
            if candidate_init in self._file_tree:
                imported_paths.append(candidate_init)
    self._import_graph[rel] = imported_paths

# Build reverse graph
for rel, imports in self._import_graph.items():
    for imp in imports:
        if imp not in self._reverse_import_graph:
            self._reverse_import_graph[imp] = []
        self._reverse_import_graph[imp].append(rel)
```

Initialize both dicts in `__init__()`:
```python
self._import_graph: dict[str, list[str]] = {}
self._reverse_import_graph: dict[str, list[str]] = {}
```

### Step 2: Query Methods (AD-315b)

**File:** `src/probos/cognitive/codebase_index.py` (existing)

Add after `get_full_api_surface()` (after line 367):

**2a. `get_imports(file_path: str) -> list[str]`**

```python
def get_imports(self, file_path: str) -> list[str]:
    """Return list of internal (probos.*) files that this file imports."""
    file_path = file_path.replace("\\", "/")
    return list(self._import_graph.get(file_path, []))
```

**2b. `find_importers(file_path: str) -> list[str]`**

```python
def find_importers(self, file_path: str) -> list[str]:
    """Return list of files that import this file (reverse import graph)."""
    file_path = file_path.replace("\\", "/")
    return list(self._reverse_import_graph.get(file_path, []))
```

### Step 3: Architect Import Tracing (AD-315c)

**File:** `src/probos/cognitive/architect.py` (existing)

**3a. Add import-traced files to `selected_paths`**

In `perceive()`, after Layer 2a selects files (after line 260, before Layer 2b begins), trace the imports of each selected file and add imported files that aren't already selected:

```python
# Layer 2a+: Expand selected files by tracing imports
import_expanded: list[str] = []
for path in selected_paths:
    imports = codebase_index.get_imports(path)
    for imp_path in imports:
        if imp_path not in selected_paths and imp_path not in import_expanded:
            import_expanded.append(imp_path)

# Add import-traced files to selected_paths (up to 12 total)
for imp_path in import_expanded:
    if len(selected_paths) >= 12:
        break
    selected_paths.append(imp_path)
```

Why 12? The source budget is 4000 lines. With average file sizes of ~200-400 lines, 12 files is a reasonable upper bound. The budget cap in Layer 2b already prevents excessive reads.

**3b. Add import graph section to Layer 2c context**

In Layer 2c (after the caller analysis section, around line 323), add an import graph section:

```python
# Import graph for selected files
import_lines: list[str] = []
for path in selected_paths:
    imports = codebase_index.get_imports(path)
    importers = codebase_index.find_importers(path)
    if imports or importers:
        parts = []
        if imports:
            parts.append(f"imports: {', '.join(imports[:5])}")
        if importers:
            parts.append(f"imported by: {', '.join(importers[:5])}")
        import_lines.append(f"- {path}: {' | '.join(parts)}")
if import_lines:
    context_parts.append(
        "## Import Graph\n" + "\n".join(import_lines)
    )
```

**3c. Update `instructions` context description**

In the `instructions` string (line 76-87), add a line to the context listing:

```
- Import graph showing which files import each selected file and vice versa
```

Add it after the "Caller analysis" line.

**3d. Add import-awareness to DESIGN PROCESS**

In the DESIGN PROCESS section of `instructions` (line 106-113), update step 3:

```
3. SURVEY — Read the source of related files. Follow imports to find collaborating
   modules (e.g., shell.py imports panels.py — read both). Identify patterns to follow.
```

### Step 4: Tests

**File:** `tests/test_codebase_index.py` (existing — add new tests)

Add test class `TestImportGraph` after `TestStructuredQueries`:

```python
class TestImportGraph:
    """Tests for AD-315 import graph methods."""

    def test_analyze_file_extracts_imports(self, index: CodebaseIndex):
        """_analyze_file() populates 'imports' key in file metadata."""
        # shell.py imports from probos.experience.panels
        meta = index._file_tree.get("experience/shell.py")
        assert meta is not None
        assert "imports" in meta
        imports = meta["imports"]
        assert isinstance(imports, list)
        # Should have at least one probos import
        probos_imports = [i for i in imports if i["module"].startswith("probos.")]
        assert len(probos_imports) > 0

    def test_import_graph_built(self, index: CodebaseIndex):
        """Import graph is populated after build()."""
        assert hasattr(index, "_import_graph")
        assert isinstance(index._import_graph, dict)
        assert len(index._import_graph) > 0

    def test_reverse_import_graph_built(self, index: CodebaseIndex):
        """Reverse import graph is populated after build()."""
        assert hasattr(index, "_reverse_import_graph")
        assert isinstance(index._reverse_import_graph, dict)
        assert len(index._reverse_import_graph) > 0

    def test_get_imports_shell(self, index: CodebaseIndex):
        """get_imports('experience/shell.py') includes panels.py."""
        imports = index.get_imports("experience/shell.py")
        assert isinstance(imports, list)
        assert any("panels" in p for p in imports)

    def test_get_imports_unknown_file(self, index: CodebaseIndex):
        """get_imports() returns [] for unknown file."""
        imports = index.get_imports("nonexistent/fake.py")
        assert imports == []

    def test_find_importers(self, index: CodebaseIndex):
        """find_importers() shows files that import a module."""
        # runtime.py is imported by many files
        importers = index.find_importers("runtime.py")
        assert isinstance(importers, list)
        # At least api.py or some other file imports runtime
        assert len(importers) > 0

    def test_find_importers_unknown(self, index: CodebaseIndex):
        """find_importers() returns [] for unknown file."""
        importers = index.find_importers("nonexistent/fake.py")
        assert importers == []

    def test_import_graph_consistency(self, index: CodebaseIndex):
        """Forward and reverse graphs are consistent."""
        for rel, imports in index._import_graph.items():
            for imp in imports:
                # The imported file should list this file as an importer
                importers = index._reverse_import_graph.get(imp, [])
                assert rel in importers, (
                    f"{rel} imports {imp} but {imp} doesn't list {rel} as importer"
                )
```

**File:** `tests/test_architect_agent.py` (existing — add new tests)

Add to `TestDeepLocalize` class:

```python
@pytest.mark.asyncio
async def test_perceive_expands_selected_files_via_imports(self):
    """Layer 2a+ expands selected files by tracing their imports."""
    mock_index = _make_mock_index_with_source(
        query={
            "matching_files": [
                {"path": "experience/shell.py", "relevance": 8, "docstring": "Shell"},
            ],
            "matching_methods": [],
        },
        file_tree={
            "experience/shell.py": {"classes": ["Shell"], "docstring": "Shell"},
            "experience/panels.py": {"classes": [], "docstring": "Panel renderers"},
        },
    )
    mock_index.read_source.return_value = "class Shell:\n    pass"
    mock_index.get_imports.return_value = ["experience/panels.py"]
    mock_index.find_importers.return_value = []

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(content="experience/shell.py")

    mock_runtime = MagicMock()
    mock_runtime.codebase_index = mock_index

    agent = ArchitectAgent(
        agent_id="test-import-1",
        llm_client=mock_llm,
        runtime=mock_runtime,
    )
    obs = await agent.perceive(_make_intent("add /agents command"))
    ctx = obs["codebase_context"]
    # panels.py should be included via import tracing
    assert "panels.py" in ctx

@pytest.mark.asyncio
async def test_perceive_includes_import_graph_section(self):
    """Context includes Import Graph section."""
    mock_index = _make_mock_index_with_source(
        query={
            "matching_files": [
                {"path": "experience/shell.py", "relevance": 8, "docstring": "Shell"},
            ],
            "matching_methods": [],
        },
        file_tree={
            "experience/shell.py": {"classes": [], "docstring": "Shell"},
        },
    )
    mock_index.read_source.return_value = "# source"
    mock_index.get_imports.return_value = ["experience/panels.py"]
    mock_index.find_importers.return_value = ["api.py"]

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = MagicMock(content="experience/shell.py")

    mock_runtime = MagicMock()
    mock_runtime.codebase_index = mock_index

    agent = ArchitectAgent(
        agent_id="test-import-2",
        llm_client=mock_llm,
        runtime=mock_runtime,
    )
    obs = await agent.perceive(_make_intent())
    ctx = obs["codebase_context"]
    assert "Import Graph" in ctx

def test_instructions_mention_imports(self):
    """System prompt mentions import graph in context description."""
    assert "import" in ArchitectAgent.instructions.lower()
    assert "Import graph" in ArchitectAgent.instructions or "import graph" in ArchitectAgent.instructions
```

Also update `_make_mock_index_with_source()` helper to include the new methods:

```python
mock.get_imports = MagicMock(return_value=overrides.get("get_imports", []))
mock.find_importers = MagicMock(return_value=overrides.get("find_importers", []))
```

---

## Architecture Diagram

```
Before (AD-311/312):
  perceive()
    Layer 2a: query() → 20 candidates → fast-tier LLM selects 8
    Layer 2b: read FULL source of 8 selected files (≤4000 lines)
    Layer 2c: find_tests_for() + find_callers() + get_full_api_surface()

After (AD-315):
  perceive()
    Layer 2a:  query() → 20 candidates → fast-tier LLM selects 8
    Layer 2a+: trace get_imports() for each selected file
               → add imported modules to selected_paths (up to 12 total)
    Layer 2b:  read FULL source of 12 selected files (≤4000 lines)
    Layer 2c:  find_tests_for() + find_callers() + get_full_api_surface()
               + import graph (get_imports + find_importers for each file)
```

CodebaseIndex build time impact: negligible — import extraction uses the same AST tree already parsed in `_analyze_file()`. Graph construction is O(files × avg_imports) which is ~100 files × ~5 imports = 500 dict operations.

---

## Concrete Example: Why This Matters

**Design request:** "Add a /agents command that lists all registered agent types"

Before AD-315 (what happened):
- LLM selects `experience/shell.py` (keyword match for "command")
- Reads shell.py fully — sees COMMANDS dict, `_dispatch_slash`, `_cmd_agents` pattern
- Does NOT see `experience/panels.py` despite `from probos.experience import panels` at the top of shell.py
- Proposal references shell.py but doesn't know about `render_agent_table()`, `render_status_panel()`, or the established shell→panels rendering pattern
- Result: incomplete proposal that misses the rendering layer

After AD-315:
- LLM selects `experience/shell.py`
- Import tracing automatically adds `experience/panels.py` (imported by shell.py)
- Also adds `probos.experience.renderer` and other shell imports
- Architect sees both shell.py AND panels.py, discovers the render pattern
- Import Graph section shows: `shell.py: imports panels.py, renderer.py | imported by: api.py`
- Proposal correctly identifies panels.py as a TARGET_FILE and follows the existing render pattern

---

## Do NOT Build

- Do NOT modify `_parse_proposal()` — output format stays the same
- Do NOT modify `act()` — post-processing stays the same
- Do NOT modify `_build_user_message()` — it already passes `codebase_context` through
- Do NOT modify `decide()` in CognitiveAgent — all changes go in `perceive()`
- Do NOT modify Layers 1, 3, 4, 5, 6, or 7 in `perceive()` — only Layer 2 changes
- Do NOT modify any Builder code — that's AD-313/314
- Do NOT add embedding-based search — that's a future enhancement
- Do NOT break the existing test suite — all 1860 pytest + 21 vitest must still pass
- Do NOT track external (non-probos) imports — they're noise for architectural analysis
- Do NOT do recursive import tracing (imports of imports) — one level deep is sufficient. Deeper tracing can be added later if needed.

---

## Verification

1. `uv run pytest tests/test_codebase_index.py -v` — new import graph tests + existing tests pass
2. `uv run pytest tests/test_architect_agent.py -v` — new import tracing tests + existing tests pass
3. `uv run pytest tests/ -x -q` — full suite green
4. Manual smoke test: `uv run probos serve` → `/design Add a /agents slash command that lists all registered agent types with their tier, team, and pool size` → verify the proposal now:
   - Includes `experience/panels.py` as a TARGET_FILE or REFERENCE_FILE (traced via imports from shell.py)
   - Shows the Import Graph section with shell.py → panels.py relationship
   - References `render_agent_table()` or `render_agent_roster()` as existing patterns
   - References correct API methods (verified against API Surface)
   - Identifies test files (`test_experience.py`)
