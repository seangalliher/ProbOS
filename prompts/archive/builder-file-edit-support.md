# AD-313: Builder File Edit Support — Search-and-Replace MODIFY Mode

*"The Engineer can now retool existing systems — not just build from raw materials."*

Currently the Builder Agent can only **create new files**. The `===MODIFY:===` block parsing already exists in `_parse_file_blocks()`, but `execute_approved_build()` skips them with a warning. This means the Architect can design enhancements to existing code, but the Builder literally cannot execute them. Most real-world build tasks involve modifying existing files, making this the single biggest bottleneck in the Northstar pipeline.

This prompt implements MODIFY mode execution with a search-and-replace strategy: the LLM outputs a `===SEARCH===` / `===REPLACE===` block for each change within a MODIFY block, and the Builder applies them sequentially. This is more reliable than line-number-based insertion because:
1. It's resilient to minor line shifts between perceive-time and execute-time
2. It matches the proven pattern used by other code-generation tools (Aider, Claude Code)
3. The LLM only needs to reproduce a small context window, not guess exact line numbers

**Current AD count:** AD-315. This prompt uses AD-313.
**Current test count:** 1871 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/builder.py` — full file. Focus on:
   - `_parse_file_blocks()` (lines 266-307) — existing MODIFY parser with `===AFTER LINE:===`
   - `execute_approved_build()` (lines 314-405) — the skip on line 348-353
   - `BuildResult.files_modified` (line 49) — already exists but never populated
   - `BuilderAgent.instructions` (lines 152-182) — current LLM instructions
2. `src/probos/cognitive/architect.py` — read the `instructions` string to understand what format the Architect tells the Builder to expect
3. `tests/test_builder_agent.py` — full file, especially `TestParseFileBlocks` and `TestExecuteApprovedBuild`
4. `src/probos/api.py` lines 618-722 — `_run_build()` pipeline to see how `execute_approved_build()` results are used

---

## What To Build

### Step 1: Redesign the MODIFY block format (AD-313)

Replace the current `===AFTER LINE:===` insertion format with a search-and-replace format. The new format is:

```
===MODIFY: path/to/file.py===
===SEARCH===
def existing_function():
    return old_value
===REPLACE===
def existing_function():
    return new_value
===END REPLACE===

===SEARCH===
import os
===REPLACE===
import os
import sys
===END REPLACE===
===END MODIFY===
```

A single MODIFY block can contain **multiple** SEARCH/REPLACE pairs for the same file. Each pair replaces the first occurrence of the SEARCH text with the REPLACE text. The searches are applied sequentially (so earlier replacements affect the text for later ones).

**File:** `src/probos/cognitive/builder.py`

**1a.** Update `_parse_file_blocks()` to parse the new MODIFY format. The method should now return MODIFY blocks with a `replacements` field instead of `after_line`:

```python
# For create mode (unchanged):
{"path": str, "content": str, "mode": "create"}

# For modify mode (new):
{"path": str, "mode": "modify", "replacements": [{"search": str, "replace": str}, ...]}
```

The parser should:
- Find `===MODIFY: path===` ... `===END MODIFY===` blocks
- Within each, find all `===SEARCH===` ... `===REPLACE===` ... `===END REPLACE===` pairs
- Strip leading/trailing blank lines from search and replace content, but preserve internal whitespace/indentation exactly
- A MODIFY block with no valid SEARCH/REPLACE pairs should be skipped (log a warning)
- Keep backward compatibility: if the old `===AFTER LINE:===` format is detected, log a deprecation warning and skip it (don't crash)

**1b.** Update `BuilderAgent.instructions` to teach the LLM the new MODIFY format. Replace the existing MODIFY section (lines 177-181) with:

```
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
```

### Step 2: Read target files in perceive() (AD-313)

**File:** `src/probos/cognitive/builder.py`

The Builder currently only reads `reference_files` in `perceive()`. For MODIFY mode to work well, the LLM **must see the current content** of files it's going to modify. Update `perceive()` to also read `target_files` and include them in the observation:

```python
async def perceive(self, intent: Any) -> dict:
    """Read reference files AND target files to build context for the LLM."""
    obs = await super().perceive(intent)
    params = obs.get("params", {})

    # Read reference files (existing behavior)
    reference_files = params.get("reference_files", [])
    file_contexts: list[str] = []
    for ref_path in reference_files:
        try:
            full_path = Path(ref_path)
            if full_path.exists() and full_path.is_file():
                content = full_path.read_text(encoding="utf-8")
                file_contexts.append(f"=== {ref_path} ===\n{content}\n")
        except Exception:
            file_contexts.append(f"=== {ref_path} === (could not read)\n")
    obs["file_context"] = "\n".join(file_contexts)

    # NEW: Read target files so the LLM can produce accurate SEARCH blocks
    target_files = params.get("target_files", [])
    target_contexts: list[str] = []
    for tgt_path in target_files:
        try:
            full_path = Path(tgt_path)
            if full_path.exists() and full_path.is_file():
                content = full_path.read_text(encoding="utf-8")
                target_contexts.append(f"=== {tgt_path} (TARGET — will be modified) ===\n{content}\n")
        except Exception:
            # File doesn't exist — Builder will create it (use FILE block, not MODIFY)
            target_contexts.append(f"=== {tgt_path} (TARGET — new file, does not exist yet) ===\n")
    obs["target_context"] = "\n".join(target_contexts)

    return obs
```

Also update `_build_user_message()` to include `target_context` above the reference code:

```python
if target_context:
    parts.append(f"\n## Target Files (current content — use MODIFY blocks for changes)\n{target_context}")
if file_context:
    parts.append(f"\n## Reference Code\n{file_context}")
```

### Step 3: Implement MODIFY execution in execute_approved_build() (AD-313)

**File:** `src/probos/cognitive/builder.py`

Replace the MODIFY skip block (lines 348-353) with actual execution logic:

```python
if change["mode"] == "modify":
    path = Path(work_dir) / change["path"]
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
                "BuilderAgent: SEARCH block %d not found in %s, skipping this replacement",
                i, change["path"],
            )
            continue

        # Replace first occurrence only
        modified = modified.replace(search_text, replace_text, 1)

    if modified != original:
        path.write_text(modified, encoding="utf-8")
        modified_files.append(change["path"])
        logger.info("BuilderAgent: modified %s (%d replacements)", change["path"], len(change.get("replacements", [])))
    else:
        logger.warning("BuilderAgent: no changes applied to %s", change["path"])
    continue
```

You'll also need to:
- Add a `modified: list[str] = []` alongside `written: list[str] = []` (line 343)
- Populate `result.files_modified = modified_files` (alongside `result.files_written = written`)
- Include `modified_files` in the git add step — change `written` to `written + modified_files` in the `_git_add_and_commit()` call
- Only run tests if `written or modified_files` (not just `written`)
- Only commit if `written or modified_files`

### Step 4: Add AST validation for Python files (AD-313)

**File:** `src/probos/cognitive/builder.py`

After writing/modifying a `.py` file, validate it with `ast.parse()` to catch syntax errors before committing. Add a helper function:

```python
import ast

def _validate_python(path: Path) -> str | None:
    """Validate a Python file with ast.parse(). Returns error string or None."""
    if path.suffix != ".py":
        return None
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return None
    except SyntaxError as exc:
        return f"{path}: line {exc.lineno}: {exc.msg}"
```

Call this after each file write/modify. If validation fails:
- Log the error
- Add it to a `validation_errors: list[str]`
- Set `result.error` to include all validation errors
- Still commit the files (so the Captain can see what went wrong), but set `result.success = False`

### Step 5: Update the Architect instructions (AD-313)

**File:** `src/probos/cognitive/architect.py`

The Architect's `instructions` string tells the Builder what output format to expect. Since the Builder now supports real MODIFY mode, the Architect should know this. Find and update the DESCRIPTION section guidance in the instructions (around line 160-166) to add:

```
- For files that already exist and need modification, describe the specific
  changes needed (what to add, what to replace) so the Builder can produce
  accurate SEARCH/REPLACE blocks.
- For new files, describe the complete structure.
```

This is a small addition — do NOT rewrite the entire instructions string.

### Step 6: Tests (AD-313)

**File:** `tests/test_builder_agent.py`

Add new test classes covering:

**6a. TestParseModifyBlocks** — test the new MODIFY format parsing:
1. Single SEARCH/REPLACE pair → correct path, mode, replacements list
2. Multiple SEARCH/REPLACE pairs in one MODIFY block → all captured
3. Mixed FILE and MODIFY blocks → both parsed correctly
4. MODIFY block with no SEARCH/REPLACE pairs → skipped (empty replacements or block excluded)
5. Whitespace preservation — indented SEARCH/REPLACE content preserves indentation exactly
6. Old `===AFTER LINE:===` format → handled gracefully (skipped with deprecation, doesn't crash)

**6b. TestExecuteModify** — test MODIFY execution in `execute_approved_build()`:
1. Basic modify — file exists, single replacement applied correctly
2. Multiple replacements — file exists, two replacements applied sequentially
3. File doesn't exist — MODIFY skipped with warning, no crash
4. SEARCH text not found — replacement skipped, other replacements still applied
5. Mixed create + modify — both file types handled in one build
6. No net change — file exists but SEARCH text not found, `files_modified` stays empty

**6c. TestValidatePython** — test the AST validation:
1. Valid Python → returns None
2. Syntax error → returns error string with line number
3. Non-Python file → returns None (skipped)

**6d. TestPerceiveTargetFiles** — test that perceive() reads target files:
1. Target file exists → content included in `target_context`
2. Target file doesn't exist → note included saying "new file"
3. Both target and reference files → both in observation

Use `tmp_path` fixture for file operations. Follow existing test patterns in the file.

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_builder_agent.py -x -v`

Then run the full suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-313 | Builder MODIFY mode — search-and-replace execution for existing files. `_parse_file_blocks()` supports `===SEARCH===`/`===REPLACE===`/`===END REPLACE===` pairs within `===MODIFY:===` blocks. `execute_approved_build()` applies replacements sequentially (first occurrence). `perceive()` reads target files so the LLM sees current content. `ast.parse()` validation catches syntax errors before commit. Old `===AFTER LINE:===` format deprecated gracefully |

---

## Do NOT Build

- **Test-fix retry loop** — that's AD-314. If tests fail after MODIFY, just report the failure. No automatic LLM retry in this prompt
- **Diff generation or unified diff format** — search-and-replace is intentionally simpler and more LLM-friendly
- **Automatic merge conflict resolution** — if SEARCH text isn't found, skip it. Don't try fuzzy matching
- **API changes** — the existing `/api/build/submit` and `/api/build/approve` endpoints already handle `file_changes` as a list of dicts. The new `replacements` field will flow through. Don't modify `api.py`
- **Architect modifications beyond the small instruction update** — the Architect already references MODIFY in its instructions; just add the small clarification about SEARCH/REPLACE awareness

---

## Constraints

- Do NOT add new dependencies to `pyproject.toml` — `ast` is stdlib
- Do NOT modify `api.py` — the existing endpoints handle the new format transparently
- Do NOT rewrite the entire `BuilderAgent.instructions` — only update the MODIFY format section
- Do NOT rewrite `_parse_file_blocks()` from scratch — extend it. Keep the existing FILE block parsing untouched
- The `after_line` field is deprecated — don't remove it from old test assertions, but new tests should use `replacements`
- Follow existing code style: `from __future__ import annotations`, type hints, docstrings
- `builder.py` must remain self-contained (no new module files)
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

---

## Update Progress When Done

Add to `progress-era-4-evolution.md`:

```
## Phase 32h: Builder File Edit Support (AD-313)

| AD | Decision |
|----|----------|
| AD-313 | Builder MODIFY mode — search-and-replace (`===SEARCH===`/`===REPLACE===`) execution for existing files. perceive() reads target files for LLM context. ast.parse() validation on .py files. Old AFTER LINE format deprecated |

**Status:** Complete — N new tests (NNNN Python total)
```

Update the test count in `PROGRESS.md` line 3.

Add to `DECISIONS.md`:

```
| AD-313 | Builder MODIFY mode — search-and-replace execution for existing files. _parse_file_blocks() supports SEARCH/REPLACE pairs within MODIFY blocks. execute_approved_build() applies replacements sequentially (first occurrence only). perceive() reads target_files. ast.parse() validation for .py files |
```
