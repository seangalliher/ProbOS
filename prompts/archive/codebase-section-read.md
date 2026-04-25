# AD-300: Section-Targeted Doc Reading in CodebaseIndex

## Problem

`_introspect_design()` reads the first 80 lines of every matched file, including project docs. The roadmap is 530+ lines — the first 80 lines only show the phase table header but none of the detailed team sections. When ProbOS is asked "review the roadmap and identify gaps", it sees the table of contents but not the content.

For source code files, 80 lines is reasonable (module docstring + imports + class signature). For Markdown docs, 80 lines captures almost nothing of value. The fix: store section line ranges during `_analyze_doc()`, then read the sections that match the query keywords instead of reading from the top.

## Pre-read

- `src/probos/cognitive/codebase_index.py` — `_analyze_doc()` (line 295), `query()` (line 126), `read_source()` (line 200)
- `src/probos/agents/introspect.py` — `_introspect_design()` (line 659)
- `tests/test_codebase_index.py` — existing tests

## Step 1: Store Section Line Ranges in `_analyze_doc()`

### `src/probos/cognitive/codebase_index.py`

Update `_analyze_doc()` to record the **line number** where each `## section` starts. This lets us read specific sections later.

```python
def _analyze_doc(self, path: Path, rel: str) -> dict[str, Any]:
    """Extract metadata from a Markdown document (AD-299)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"docstring": None, "classes": [], "sections": [], "type": "doc"}

    lines = text.splitlines()

    # First # heading is the title (equivalent to docstring)
    title: str | None = None
    sections: list[dict[str, Any]] = []  # AD-300: section name + line number
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
        elif stripped.startswith("## "):
            sections.append({
                "name": stripped.lstrip("#").strip(),
                "line": i + 1,  # 1-indexed
            })

    return {
        "docstring": title,
        "classes": [s["name"] for s in sections],  # keep for backward compat with query()
        "sections": sections,  # AD-300: structured section data
        "type": "doc",
    }
```

**Note:** `classes` stays as a flat list of section names for backward compatibility with `query()` keyword matching. `sections` is the new structured field with line numbers.

## Step 2: Add `read_doc_sections()` to CodebaseIndex

### `src/probos/cognitive/codebase_index.py`

Add a new public method that reads specific sections from a doc file based on keyword matching:

```python
def read_doc_sections(
    self,
    file_path: str,
    keywords: list[str],
    max_lines: int = 200,
) -> str:
    """Read sections of a doc file that match the given keywords.

    Returns concatenated text of matching sections, up to max_lines total.
    Falls back to reading the first max_lines if no sections match.
    """
    meta = self._file_tree.get(file_path)
    if meta is None or meta.get("type") != "doc":
        return self.read_source(file_path, end_line=max_lines)

    sections = meta.get("sections", [])
    if not sections:
        return self.read_source(file_path, end_line=max_lines)

    # Score each section by keyword matches
    scored: list[tuple[int, dict[str, Any]]] = []
    for sec in sections:
        name_lower = sec["name"].lower()
        score = sum(1 for kw in keywords if kw in name_lower)
        if score > 0:
            scored.append((score, sec))
    scored.sort(key=lambda t: -t[0])

    # If no sections matched keywords, read the full doc from the top
    if not scored:
        return self.read_source(file_path, end_line=max_lines)

    # Build section line ranges: each section runs from its start to the next section's start
    all_lines = sorted(s["line"] for s in sections)

    # Read the full file to slice sections
    full_text = self.read_source(file_path)
    if not full_text:
        return ""
    file_lines = full_text.splitlines(keepends=True)

    result_lines: list[str] = []
    for _score, sec in scored:
        start = sec["line"] - 1  # 0-indexed
        # Find the next section start after this one
        idx = all_lines.index(sec["line"])
        end = all_lines[idx + 1] - 1 if idx + 1 < len(all_lines) else len(file_lines)

        section_lines = file_lines[start:end]
        result_lines.extend(section_lines)

        if len(result_lines) >= max_lines:
            result_lines = result_lines[:max_lines]
            break

    return "".join(result_lines)
```

## Step 3: Update `_introspect_design()` to Use Section-Targeted Reading

### `src/probos/agents/introspect.py`

Update the snippet-reading loop to detect doc files and use section-targeted reading:

```python
# Read source snippets from the top matching files (AD-297)
source_snippets: list[dict[str, str]] = []
matching_files = arch_data.get("matching_files", [])

# Extract keywords for section targeting (AD-300)
from probos.cognitive.codebase_index import _STOP_WORDS
query_keywords = [
    w for w in question.lower().split()
    if w not in _STOP_WORDS and len(w) > 1
]

for file_info in matching_files[:3]:  # top 3 most relevant files
    file_path = file_info.get("path", "")
    if not file_path:
        continue

    # Use section-targeted reading for docs, fixed 80-line for source (AD-300)
    if file_path.startswith("docs:"):
        source = codebase_index.read_doc_sections(file_path, query_keywords)
    else:
        source = codebase_index.read_source(file_path, end_line=80)

    if source:
        source_snippets.append({
            "path": file_path,
            "source": source,
        })
```

**Note:** Import `_STOP_WORDS` from `codebase_index` to reuse the same stop word filtering. The keywords are the same ones `query()` used to find the file — so the sections that matched the search are the sections that get read.

## Step 4: Tests

### `tests/test_codebase_index.py`

1. `test_analyze_doc_stores_section_lines` — Create a temp markdown file with 3 sections. Build index. Verify `_file_tree["docs:test.md"]["sections"]` contains dicts with `name` and `line` keys, and line numbers are correct.

2. `test_read_doc_sections_returns_matching_sections` — Create a temp doc with sections "Medical Team", "Security Team", "Operations Team" each with distinct content. Call `read_doc_sections("docs:test.md", ["medical"])`. Verify only the Medical Team section content is returned.

3. `test_read_doc_sections_multiple_keywords` — Query with `["security", "team"]`. Verify Security Team section is returned first (matches 2 keywords), followed by other matching sections.

4. `test_read_doc_sections_fallback_on_no_match` — Query with keywords that don't match any section. Verify it falls back to reading from the top of the file.

5. `test_read_doc_sections_respects_max_lines` — Create a doc with very long sections. Call with `max_lines=10`. Verify output is capped at 10 lines.

### `tests/test_introspect_design.py`

6. `test_introspect_design_uses_section_reading_for_docs` — Mock a codebase_index where query returns a `docs:` prefixed file. Verify `read_doc_sections` is called instead of `read_source` with `end_line=80`.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 5: Update Progress

- Update test count on PROGRESS.md line 3
- Add AD-300 entry to `progress-era-3-product.md`
- Add AD-300 entry to `DECISIONS.md`

## Constraints

- `classes` field preserved for backward compat — `query()` still works unchanged
- `sections` is additive metadata — no existing tests break
- `read_doc_sections()` falls back to `read_source()` for non-doc files or when no sections match
- 200-line default for docs (vs 80 for source code) — docs are denser in relevant content per line
- No new dependencies

## Success Criteria

- "Review the roadmap" → ProbOS reads Medical Team, Security Team, Operations Team sections (not just first 80 lines)
- "What's planned for the security team?" → reads the Security Team section specifically
- "What architecture decisions have been made?" → reads relevant DECISIONS.md sections
- All existing tests pass
- 6 new tests pass
