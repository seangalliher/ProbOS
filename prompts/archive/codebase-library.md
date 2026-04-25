# AD-297: CodebaseIndex as Ship's Library — Open to All Agents

## Problem

CodebaseIndex (the ship's library) is currently locked inside the medical bay. Two issues:

1. **CodebaseIndex creation is gated behind `config.medical.enabled`** (runtime.py:478-484). If the medical team is disabled, `self.codebase_index` stays `None` and the introspect agent cannot examine source code. The library should be open to the whole crew regardless of which departments are active.

2. **`_introspect_design()` only returns metadata, not source code.** It calls `query()`, `get_agent_map()`, and `get_layer_map()` — all of which return structural metadata (file paths, class names, docstrings). It never calls `read_source()`, which is the method that actually reads source file contents. When ProbOS says "I can see my architecture but have no source files available for analysis," this is why.

## Pre-read

- `src/probos/runtime.py` — lines 263-264 (codebase_index init), lines 478-520 (medical-gated build + skill attachment)
- `src/probos/agents/introspect.py` — `_introspect_design()` method (line 659)
- `src/probos/cognitive/codebase_index.py` — full file, especially `read_source()` (line 159), `query()` (line 89)
- `src/probos/cognitive/codebase_skill.py` — full file, the `read_source` action at line 37
- `tests/test_introspect_design.py` — existing tests

## Step 1: Decouple CodebaseIndex from Medical Config

### `src/probos/runtime.py`

**Move CodebaseIndex build out of the `if self.config.medical.enabled:` block.** It should build unconditionally during `start()`, before any pool creation.

Find the current code at lines 478-484:

```python
# Medical team pool (AD-290)
if self.config.medical.enabled:
    med_cfg = self.config.medical
    # Build CodebaseIndex
    from probos.cognitive.codebase_index import CodebaseIndex
    self.codebase_index = CodebaseIndex(source_root=Path(__file__).resolve().parent)
    self.codebase_index.build()
```

Refactor to:

```python
# Build CodebaseIndex — ship's library, available to all agents (AD-297)
from probos.cognitive.codebase_index import CodebaseIndex
self.codebase_index = CodebaseIndex(source_root=Path(__file__).resolve().parent)
self.codebase_index.build()

# Medical team pool (AD-290)
if self.config.medical.enabled:
    med_cfg = self.config.medical
```

The `CodebaseIndex` import and build should happen **before** the medical block, so it's always available regardless of config.

The codebase_knowledge skill attachment to `medical_pathologist` (lines 512-520) stays where it is — the pathologist still uses the skill interface. The introspect agent accesses the index directly via `rt.codebase_index`.

## Step 2: Add Source Code Reading to `_introspect_design()`

### `src/probos/agents/introspect.py`

Update `_introspect_design()` to include relevant source code snippets when answering architecture questions.

After calling `codebase_index.query(question)`, use `read_source()` on the top matching files to include actual code in the response:

```python
def _introspect_design(self, rt: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Answer architectural questions using codebase knowledge."""
    question = params.get("question", "")
    if not question:
        return {"success": False, "error": "No question provided"}

    codebase_index = getattr(rt, "codebase_index", None)
    if codebase_index is None:
        return {
            "success": True,
            "data": {
                "message": "Codebase knowledge not available. Cannot introspect source architecture.",
            },
        }

    # Query architecture for the concept
    arch_data = codebase_index.query(question)
    agent_map = codebase_index.get_agent_map()
    layer_map = codebase_index.get_layer_map()

    # Read source snippets from the top matching files (AD-297)
    source_snippets: list[dict[str, str]] = []
    matching_files = arch_data.get("matching_files", [])
    for file_info in matching_files[:3]:  # top 3 most relevant files
        file_path = file_info.get("path", "")
        if not file_path:
            continue
        source = codebase_index.read_source(file_path, end_line=80)
        if source:
            source_snippets.append({
                "path": file_path,
                "source": source,
            })

    return {
        "success": True,
        "data": {
            "question": question,
            "architecture_context": arch_data,
            "agent_count": len(agent_map) if agent_map else 0,
            "layers": list(layer_map.keys()) if layer_map else [],
            "source_snippets": source_snippets,
        },
    }
```

**Design notes:**
- Reads the first 80 lines of each matching file — enough to see the module docstring, imports, and class/function signatures without overwhelming the response
- Limits to top 3 files by relevance score (from `query()`)
- If `read_source()` returns empty string (file not found / path traversal blocked), skip it
- The LLM reflection step will now have actual code to reason about when answering "is there a design limitation?" or "how does X work?"

## Step 3: Update Tests

### `tests/test_introspect_design.py`

**Update existing test** — `test_introspect_design_returns_architecture` should now also verify `source_snippets` is present in the response.

**Add mock for `read_source`** in `_make_rt_with_codebase()`:

```python
def _make_rt_with_codebase():
    """Create a mock runtime with a codebase_index."""
    rt = MagicMock()
    rt.codebase_index = MagicMock()
    rt.codebase_index.query.return_value = {
        "matching_files": [
            {"path": "consensus/trust.py", "docstring": "Trust network", "relevance": 5},
            {"path": "runtime.py", "docstring": "Runtime core", "relevance": 3},
        ],
        "matching_agents": [{"type": "introspect"}],
        "matching_methods": [],
        "layer": "consensus",
    }
    rt.codebase_index.read_source.return_value = "class TrustNetwork:\n    \"\"\"Trust scoring.\"\"\"\n    pass\n"
    rt.codebase_index.get_agent_map.return_value = [
        {"type": "introspect"},
        {"type": "shell_command"},
    ]
    rt.codebase_index.get_layer_map.return_value = {
        "substrate": ["agent.py"],
        "mesh": ["routing.py"],
        "consensus": ["trust.py", "quorum.py"],
        "cognitive": ["episodic.py"],
    }
    return rt
```

**Add new tests:**

1. `test_introspect_design_includes_source_snippets` — verify response includes `source_snippets` list with `path` and `source` keys from the top matching files

2. `test_introspect_design_limits_snippets_to_three` — mock 5 matching files, verify only 3 source snippets are returned

3. `test_introspect_design_skips_empty_source` — mock `read_source` returning empty string for one file, verify it's excluded from snippets

4. `test_codebase_index_always_available` — integration-style test: create a minimal runtime mock, verify `codebase_index` is not `None` even when medical config is disabled. (This tests the decoupling.)

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 4: Update Progress

- Update test count on PROGRESS.md line 3
- Add AD-297 entry to `progress-era-3-product.md`
- Add AD-297 entry to `DECISIONS.md`

## Constraints

- `read_source()` is bounded to source_root — no path traversal risk (already handled by CodebaseIndex)
- 80-line limit per file keeps response payload manageable — LLM context isn't overwhelmed
- Only reads `.py` files that are already indexed — no arbitrary file access
- Backward compatible — `source_snippets` is a new key, existing consumers get richer data
- No new dependencies

## Success Criteria

- "Are you able to analyze your own source code?" → ProbOS responds with actual source code snippets, not just metadata
- CodebaseIndex builds at startup regardless of `config.medical.enabled`
- `_introspect_design()` returns `source_snippets` with paths and source content
- Asking "How does trust scoring work?" returns snippets from `consensus/trust.py`
- All existing tests pass
- 4 new tests pass
