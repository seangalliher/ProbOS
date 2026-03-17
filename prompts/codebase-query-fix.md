# AD-298: Word-Level Query Matching in CodebaseIndex

## Problem

`CodebaseIndex.query()` uses **exact substring matching** against the full concept string. When the decomposer sends a question like "source code analysis capability" or "How does trust scoring work?", it searches for that entire phrase as a substring in file paths, docstrings, and class names. This matches almost nothing because no file path or docstring contains the exact multi-word phrase.

Result: `_introspect_design()` gets no matching files from `query()`, so `read_source()` is never called, and `source_snippets` comes back empty. ProbOS reports "I can see my architecture but no source files available."

## Pre-read

- `src/probos/cognitive/codebase_index.py` — `query()` method (line 89)
- `tests/test_introspect_design.py` — existing tests

## Fix: Word-Level Matching in `query()`

### `src/probos/cognitive/codebase_index.py`

Replace the substring matching logic in `query()` with word-level scoring.

**Add stop words set** above the `CodebaseIndex` class:

```python
# Common words to ignore in keyword matching
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "between",
    "through", "during", "before", "after", "above", "below", "and", "but",
    "or", "not", "no", "if", "then", "than", "so", "up", "out", "it",
    "its", "this", "that", "these", "those", "my", "your", "our", "their",
    "i", "you", "we", "they", "he", "she", "me", "him", "her", "us",
    "them", "what", "which", "who", "whom", "how", "when", "where", "why",
    "own", "very", "just", "also", "any", "each", "all", "both", "more",
})
```

**Update `query()` to split concept into keywords and score per-word:**

```python
def query(self, concept: str) -> dict[str, Any]:
    """Keyword-based lookup across files, agents, methods, and layers."""
    # Split concept into meaningful keywords (AD-298)
    keywords = [
        w for w in concept.lower().split()
        if w not in _STOP_WORDS and len(w) > 1
    ]
    if not keywords:
        # Fallback: use the whole concept if all words were stop words
        keywords = [concept.lower().strip()]

    matching_files: list[dict[str, Any]] = []
    for rel, meta in self._file_tree.items():
        relevance = 0
        rel_lower = rel.lower()
        doc_lower = (meta.get("docstring") or "").lower()
        cls_names_lower = [c.lower() for c in meta.get("classes", [])]

        for kw in keywords:
            if kw in rel_lower:
                relevance += 3
            if kw in doc_lower:
                relevance += 2
            for cls in cls_names_lower:
                if kw in cls:
                    relevance += 2

        if relevance > 0:
            matching_files.append({
                "path": rel,
                "docstring": meta.get("docstring"),
                "relevance": relevance,
            })
    matching_files.sort(key=lambda m: -m["relevance"])

    matching_agents = [
        a for a in self._agent_map
        if any(
            kw in a.get("type", "").lower()
            or kw in (a.get("module") or "").lower()
            for kw in keywords
        )
    ]

    matching_methods: list[dict[str, str]] = []
    for cls_name, methods in self._api_surface.items():
        cls_lower = cls_name.lower()
        for m in methods:
            method_lower = m["method"].lower()
            if any(kw in method_lower or kw in cls_lower for kw in keywords):
                matching_methods.append({**m, "class": cls_name})

    layer: str | None = None
    for layer_name, files in self._layer_map.items():
        if any(kw in layer_name for kw in keywords):
            layer = layer_name
            break

    return {
        "matching_files": matching_files[:20],
        "matching_agents": matching_agents[:20],
        "matching_methods": matching_methods[:20],
        "layer": layer,
    }
```

**Key design decisions:**
- Each keyword is matched independently — "trust scoring" matches files containing "trust" OR "scoring", with higher relevance for files matching both
- Stop words are filtered out so "How does trust scoring work?" becomes `["trust", "scoring", "work"]`
- Single-character words are dropped (avoids noise from "a", "I", etc.)
- Fallback to original full string if all words are stop words (edge case)
- Scoring is additive — a file matching 3 keywords scores higher than one matching 1
- No new dependencies — pure string operations

## Tests

### `tests/test_codebase_index.py` (create if doesn't exist, or add to existing)

1. `test_query_word_level_matching` — Build a real CodebaseIndex from a temp directory with a few `.py` files. Query with a multi-word phrase like "trust network scoring". Verify files with "trust" in their path or docstring are returned.

2. `test_query_stop_words_filtered` — Query "how does the trust work" → should match same files as querying "trust work". Verify stop words don't pollute results.

3. `test_query_multiple_keywords_score_higher` — Create files where one matches 1 keyword and another matches 2. Verify the 2-keyword file has higher relevance and sorts first.

4. `test_query_empty_after_stop_words` — Query "is it the" (all stop words). Verify it falls back to the full string and doesn't crash.

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Progress Updates

- Update test count on PROGRESS.md line 3
- Add AD-298 entry to `progress-era-3-product.md`
- Add AD-298 entry to `DECISIONS.md`

## Constraints

- No new dependencies — pure string operations
- Backward compatible — `query()` return format is unchanged
- Existing tests should still pass (same return structure, just better matching)
- Stop words list is intentionally minimal — covers English common words only

## Success Criteria

- "Can you analyze your own source code?" → `query()` extracts keywords like `["analyze", "source", "code"]` → matches `codebase_index.py` (has "source code" in docstring) and other relevant files → `read_source()` returns actual code → ProbOS answers with source snippets
- "How does trust scoring work?" → matches `consensus/trust.py`, returns source code
- Multi-word queries return relevant results instead of empty lists
- All existing tests pass
