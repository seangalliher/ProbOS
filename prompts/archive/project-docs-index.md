# AD-299: Index Project Docs — Ship's Logs in the Library

## Problem

CodebaseIndex (the ship's library) only indexes Python source files under `src/probos/`. The ship's logs — roadmap, architecture decisions, progress — live in Markdown files at the project root and `docs/`. When ProbOS is asked "what's on the roadmap?" or "what decisions have been made?", it has no access to these documents.

The library should contain the ship's logs alongside the engine schematics.

## Pre-read

- `src/probos/cognitive/codebase_index.py` — full file (especially `__init__`, `build()`, `query()`, `read_source()`)
- `src/probos/runtime.py` — line 478-481 (CodebaseIndex creation with `source_root`)
- `src/probos/agents/introspect.py` — `_introspect_design()` method (line 659)
- `tests/test_codebase_index.py` — existing tests

## Design

The project root is two levels above `source_root` (`src/probos/` → `src/` → project root). We add a `_project_root` and a whitelist of project docs to index. Markdown files get lightweight parsing — extract the title (first `# heading`) as docstring and section headings (`## heading`) as the "classes" equivalent for search matching.

## Step 1: Add Project Docs Scanning to CodebaseIndex

### `src/probos/cognitive/codebase_index.py`

**Add a project doc whitelist constant** above the `CodebaseIndex` class:

```python
# Project documents to index alongside source code (AD-299)
_PROJECT_DOCS = [
    "DECISIONS.md",
    "PROGRESS.md",
    "progress-era-1-genesis.md",
    "progress-era-2-emergence.md",
    "progress-era-3-product.md",
    "progress-era-4-evolution.md",
    "docs/development/roadmap.md",
    "docs/development/contributing.md",
]
```

**Update `__init__`** — add `_project_root`:

```python
def __init__(self, source_root: Path) -> None:
    self._source_root = Path(source_root)
    self._project_root = self._source_root.parent.parent  # src/probos/ → project root (AD-299)
    self._file_tree: dict[str, dict[str, Any]] = {}
    ...
```

**Update `build()`** — after scanning `.py` files, also scan project docs:

```python
def build(self) -> None:
    """Scan source tree and populate all indexes."""
    src = self._source_root
    if not src.is_dir():
        logger.warning("CodebaseIndex: source root %s not found", src)
        self._built = True
        return

    # Scan Python source files
    py_files = sorted(src.rglob("*.py"))
    for py in py_files:
        rel = str(py.relative_to(src)).replace("\\", "/")
        meta = self._analyze_file(py, rel)
        self._file_tree[rel] = meta

    # Scan project documents (AD-299)
    for doc_rel in _PROJECT_DOCS:
        doc_path = self._project_root / doc_rel
        if doc_path.is_file():
            meta = self._analyze_doc(doc_path, doc_rel)
            # Prefix with "docs:" to distinguish from source files
            self._file_tree[f"docs:{doc_rel}"] = meta

    self._build_layer_map()
    self._extract_config_schema()
    self._built = True
    logger.info(
        "CodebaseIndex built: %d files, %d agents, %d layers, %d docs",
        len([k for k in self._file_tree if not k.startswith("docs:")]),
        len(self._agent_map),
        len(self._layer_map),
        len([k for k in self._file_tree if k.startswith("docs:")]),
    )
```

**Add `_analyze_doc()` method** — lightweight Markdown parsing:

```python
def _analyze_doc(self, path: Path, rel: str) -> dict[str, Any]:
    """Extract metadata from a Markdown document."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"docstring": None, "classes": [], "type": "doc"}

    lines = text.splitlines()

    # First # heading is the title (equivalent to docstring)
    title: str | None = None
    sections: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
        elif stripped.startswith("## "):
            sections.append(stripped[3:].strip())

    return {
        "docstring": title,
        "classes": sections,  # section headings serve as searchable "classes"
        "type": "doc",
    }
```

**Update `read_source()`** — also handle doc files:

Rename to something more general or add doc support. The simplest approach: if the `file_path` starts with `docs:`, resolve it against `_project_root` instead of `_source_root`.

```python
def read_source(
    self,
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read source or doc file contents.  Bounded to source_root / project_root only."""
    file_path = file_path.replace("\\", "/")

    # Resolve against the correct root (AD-299)
    if file_path.startswith("docs:"):
        actual_path = file_path[5:]  # strip "docs:" prefix
        target = (self._project_root / actual_path).resolve()
        try:
            target.relative_to(self._project_root.resolve())
        except ValueError:
            return ""
    else:
        target = (self._source_root / file_path).resolve()
        try:
            target.relative_to(self._source_root.resolve())
        except ValueError:
            return ""

    if not target.is_file():
        return ""

    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    if start_line is not None or end_line is not None:
        s = (start_line or 1) - 1
        e = end_line or len(lines)
        lines = lines[s:e]

    return "".join(lines)
```

## Step 2: No Changes Needed to `_introspect_design()`

The existing code in `_introspect_design()` already calls `query()` → gets matching files → calls `read_source()` on top 3. Since project docs are now in `_file_tree` with `docs:` prefixed paths, they'll naturally show up in query results and `read_source()` knows how to handle the prefix. No changes needed.

## Step 3: Tests

### `tests/test_codebase_index.py`

Add tests using a temp directory structure:

1. `test_build_indexes_project_docs` — Create a temp dir mimicking the project structure (create `src/probos/` as source root and put a `DECISIONS.md` and `docs/development/roadmap.md` at the project root). Build the index. Verify `docs:DECISIONS.md` and `docs:docs/development/roadmap.md` appear in `_file_tree` with correct title and section headings parsed.

2. `test_query_matches_doc_sections` — Build index with a roadmap file containing `## Medical Team` section. Query for "medical team". Verify the roadmap doc is returned with relevance score.

3. `test_read_source_reads_docs` — Build index, call `read_source("docs:DECISIONS.md")`. Verify it returns the file contents. Test with `start_line` / `end_line` too.

4. `test_read_source_doc_path_traversal_blocked` — Call `read_source("docs:../../etc/passwd")`. Verify empty string returned (path traversal blocked).

5. `test_missing_project_docs_skipped` — Build index where some whitelisted docs don't exist. Verify build succeeds without errors and only existing docs are indexed.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 4: Update Progress

- Update test count on PROGRESS.md line 3
- Add AD-299 entry to `progress-era-3-product.md`
- Add AD-299 entry to `DECISIONS.md`

## Constraints

- Whitelist approach — only specific known project docs are indexed, no arbitrary file scanning
- `docs:` prefix in file_tree keys clearly distinguishes docs from source
- Path traversal protection applies to both source and doc roots
- No new dependencies — just file I/O and string parsing
- Markdown parsing is intentionally minimal — just titles and `##` section headings, no full Markdown AST
- Doc files do not contribute to `_agent_map`, `_layer_map`, or `_api_surface` — they're searchable text only

## Success Criteria

- "What's on the roadmap?" → ProbOS returns roadmap content with phase details
- "What architecture decisions have been made?" → ProbOS returns DECISIONS.md excerpts
- "Tell me about the medical team roadmap" → query matches roadmap sections containing "medical" and "team"
- Build log shows doc count alongside file/agent/layer counts
- Path traversal blocked for doc paths
- All existing tests pass
- 5 new tests pass
