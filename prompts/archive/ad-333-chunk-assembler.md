# AD-333: ChunkAssembler — Rematerializer

*"The rematerializer takes the parallel matter streams and reassembles them into coherent matter. Every atom must be in the right place — or you get a very unhappy crew member."*

The ChunkAssembler takes the `ChunkResult` list from `execute_chunks()` (AD-332) and merges them into a unified `list[dict[str, Any]]` — the same file-block format that `execute_approved_build()` expects. This is the critical assembly step that makes the Transporter Pattern output-compatible with the existing Builder pipeline. No downstream changes needed.

The assembler handles the hard problems of merging parallel outputs:
1. **Multiple chunks targeting the same file** — their outputs must be merged, not overwritten
2. **Import deduplication** — when two chunks both add `import os`, it should appear once
3. **Confidence-weighted conflict resolution** — when chunks produce conflicting content for the same file, the higher-confidence chunk wins
4. **Per-chunk attribution** — track which chunk produced which file block for debugging

This AD implements a focused Reduce stage. The Collapse stage (iterative pre-merging when outputs exceed context) is deferred — it's an optimization for very large builds that can be added later without changing the API.

**Current AD count:** AD-336. This prompt implements AD-333.
**Current test count:** 2,018 pytest + 30 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/builder.py` — full file. Focus on:
   - `ChunkResult` (lines 84-100) — the input to the assembler
   - `BuildBlueprint` (lines 103-170) — holds `.results` after `execute_chunks()`
   - `BuilderAgent._parse_file_blocks()` (lines 1147-1210) — the assembler's output format must match this: `{"path": str, "content": str, "mode": "create", "after_line": None}` for new files, `{"path": str, "mode": "modify", "replacements": [{"search": str, "replace": str}]}` for modifications
   - `execute_approved_build()` (lines 1280+) — consumes the file-block list. This is the downstream consumer that must not break
   - `_parse_chunk_response()` (lines 445-488) — `generated_code` contains the full LLM output including file-block markers. The assembler re-parses this
2. `tests/test_builder_agent.py` — full file, especially `TestParseFileBlocks`, `TestParseModifyBlocks` for the expected output format

---

## What To Build

### Step 1: Add the `assemble_chunks()` function (AD-333)

**File:** `src/probos/cognitive/builder.py`

Add a new module-level function **after** `execute_chunks()` (after the `execute_chunks` function ends) and **before** the git helpers section. This is the Rematerializer.

```python
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
```

**Implementation details:**

**1a. Parse file blocks from each successful chunk result**

```python
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
```

**1b. Group blocks by file path and mode**

```python
    # Group by (path, mode)
    from collections import defaultdict
    creates: dict[str, list[tuple[dict[str, Any], ChunkResult]]] = defaultdict(list)
    modifies: dict[str, list[tuple[dict[str, Any], ChunkResult]]] = defaultdict(list)

    for block, result in tagged_blocks:
        if block["mode"] == "create":
            creates[block["path"]].append((block, result))
        else:  # modify
            modifies[block["path"]].append((block, result))
```

**1c. Merge CREATE blocks (same file from multiple chunks)**

When multiple chunks create the same file, merge their content. The higher-confidence chunk's content comes first. Imports are deduplicated.

```python
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
```

**1d. Merge MODIFY blocks (same file from multiple chunks)**

When multiple chunks modify the same file, concatenate their replacement lists. Higher-confidence chunks' replacements come first.

```python
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
```

---

### Step 2: Add the `_merge_create_blocks()` helper

**File:** `src/probos/cognitive/builder.py`

Add this helper **before** `assemble_chunks()`:

```python
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
```

---

### Step 3: Add an `assembly_summary()` helper for debugging

**File:** `src/probos/cognitive/builder.py`

Add this helper **after** `assemble_chunks()`. It's useful for logging and the HXI (AD-335):

```python
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
```

---

### Step 4: Write tests

**File:** `tests/test_builder_agent.py`

Add new test classes. Import `assemble_chunks`, `_merge_create_blocks`, and `assembly_summary` from `probos.cognitive.builder`.

**4a. `TestMergeCreateBlocks` class** — 4 tests:

1. `test_single_content` — single content string → returned as-is (with trailing newline)
2. `test_deduplicate_imports` — two contents both starting with `import os\nimport sys\n\ndef foo():...` and `import os\nimport json\n\ndef bar():...`. Verify: merged output has `import os` once, `import sys` once, `import json` once, and both `foo` and `bar` bodies present
3. `test_no_imports` — two content blocks with no import lines (just function defs). Verify: bodies are concatenated with double newline separator
4. `test_empty_contents` — list with empty string content → returns just `"\n"`

**4b. `TestAssembleChunks` class** — 7 tests:

1. `test_single_chunk_create` — Blueprint with one chunk result containing a CREATE file block. Verify: returns list with 1 dict, `mode="create"`, path and content correct

2. `test_single_chunk_modify` — Blueprint with one chunk result containing a MODIFY file block. Verify: returns list with 1 dict, `mode="modify"`, replacements correct

3. `test_multiple_chunks_different_files` — Two chunks targeting different files (src/a.py, src/b.py). Verify: returns 2 file blocks, one for each file

4. `test_multiple_chunks_same_file_create` — Two chunks both creating the same file (src/foo.py). Chunk A (confidence=5) has `import os\ndef foo(): pass`. Chunk B (confidence=3) has `import os\nimport json\ndef bar(): pass`. Verify: single merged file block with `import os` once, `import json` once, both functions present. Higher-confidence chunk's content comes first.

5. `test_multiple_chunks_same_file_modify` — Two chunks both modifying the same file. Chunk A (confidence=4) has 2 replacements. Chunk B (confidence=2) has 1 replacement. Verify: single MODIFY block with 3 replacements total, chunk A's replacements first (higher confidence)

6. `test_failed_chunks_skipped` — Three chunks: chunk-0 succeeds, chunk-1 fails, chunk-2 succeeds. Verify: only 2 file blocks in output (failed chunk skipped)

7. `test_no_successful_chunks` — All chunks failed. Verify: returns empty list

For these tests, build `BuildBlueprint` objects with pre-populated `.chunks` and `.results`. Set `ChunkResult.generated_code` to strings containing `===FILE:===`/`===MODIFY:===` markers that `_parse_file_blocks()` can parse. Example:

```python
result = ChunkResult(
    chunk_id="chunk-0",
    success=True,
    generated_code='===FILE: src/foo.py===\nimport os\n\ndef foo():\n    pass\n===END FILE===',
    confidence=5,
)
```

**4c. `TestAssemblySummary` class** — 2 tests:

1. `test_basic_summary` — Blueprint with 3 chunks (2 success, 1 failure). Verify: `total_chunks=3`, `successful=2`, `failed=1`, `chunks` list has 3 entries with correct fields
2. `test_empty_results` — Blueprint with no chunks/results. Verify: `total_chunks=0`, `successful=0`

---

## Constraints

- **Zero LLM** — the assembler is pure code, no LLM calls. This is static merging.
- **Output format must match `_parse_file_blocks()`** — the assembler's output is consumed by `execute_approved_build()`, which expects `list[dict[str, Any]]` with `path`, `content`/`replacements`, `mode`
- **Do NOT modify existing methods** — `_parse_file_blocks()`, `execute_approved_build()`, `execute_chunks()` etc. remain unchanged
- **Partial assembly is valid** — if 2 of 3 chunks fail, assemble the 2 that succeeded. Never raise on failed chunks.
- **Confidence ordering matters** — when merging chunks for the same file, higher-confidence chunk content/replacements come first. This is the "confidence-weighted conflict resolution" from the LLM×MapReduce research.
- **No new files** — everything in `builder.py` and `test_builder_agent.py`
- **13 new tests** — 4 + 7 + 2 = 13 tests

---

## Verification

After completing all steps:

1. Run `python -m pytest tests/test_builder_agent.py -v` — all existing + new tests pass
2. Run `python -m pytest tests/ -x --timeout=30` — full test suite passes (no regressions)
3. Verify imports: `python -c "from probos.cognitive.builder import assemble_chunks, _merge_create_blocks, assembly_summary; print('OK')"`
