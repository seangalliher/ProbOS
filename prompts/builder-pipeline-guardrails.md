# Build Prompt: Builder Pipeline Guardrails (AD-360)

## Context

The visiting officer builder (Copilot SDK) has failed 2 of 3 real builds by
creating files in wrong directories (`probos/` instead of `src/probos/`) and
generating files not listed in the build spec. The native builder could have
similar issues. The pipeline needs structural guardrails that catch these
problems automatically before they reach the Captain.

**Goal:** Add six guardrails to `execute_approved_build()` and related
functions: (1) branch lifecycle management, (2) file path validation, (3) stray
file rejection, (4) build spec allowlist, (5) dirty working tree protection,
(6) untracked file cleanup. These are defensive safety nets, not behavioral
changes to the LLM.

**Inspired by:** Aider's pre-edit dirty commit and edit-lint-test-reflect cycle,
Cline's shadow git checkpoints and inside/outside workspace access tiers,
SWE-Agent's container-scoped isolation, OpenHands' overlay mount pattern.

---

## Issue 1: Build Branch Lifecycle Management

**File:** `src/probos/cognitive/builder.py`

The pipeline creates `builder/*` branches but never cleans them up on failure.
The `finally` block (line 2640) switches back to `main` but leaves the branch
behind. Next build with the same prompt hits a branch name collision and fails.

**Root cause:** The pipeline doesn't own the full lifecycle of branches it
creates. Fix: clean up on failure. The pipeline made them, the pipeline removes
them.

### 1a. Clean up build branch on failure (PRIMARY FIX)

In the `finally` block (line 2640), after returning to main, delete the build
branch if no commit was made (build failed):

```python
finally:
    # 7. Return to original branch
    await _git_checkout_main(work_dir)
    # Clean up build branch if no commit was made (failed build)
    if not result.commit_hash and result.branch_name:
        logger.info("Cleaning up failed build branch '%s'", result.branch_name)
        await _run_git(["branch", "-D", result.branch_name], work_dir)
```

### 1b. Defensive: handle pre-existing branch collision in `_git_create_branch()`

Safety net for edge cases (crash, power loss, manual intervention) where 1a
didn't run. Currently `_git_create_branch()` (line 1584) runs `git checkout -b`
which fails on collision. Delete the stale branch first if it exists:

```python
async def _git_create_branch(branch_name: str, work_dir: str) -> tuple[bool, str]:
    """Create and checkout a new git branch.  Returns (success, message)."""
    safe = _sanitize_branch_name(branch_name)
    # Safety net: delete stale branch from prior failed build (crash/power loss)
    _, list_out, _ = await _run_git(["branch", "--list", safe], work_dir)
    if list_out.strip():
        logger.info("Deleting stale branch '%s' from prior build", safe)
        await _run_git(["branch", "-D", safe], work_dir)
    rc, out, err = await _run_git(["checkout", "-b", safe], work_dir)
    if rc != 0:
        return False, err or out
    return True, safe
```

---

## Issue 2: File Path Validation

**File:** `src/probos/cognitive/builder.py`

### 2a. Add a path validation function

Add a new function `_validate_file_path()` after `_normalize_change_paths()`
(line 76):

```python
# Allowed top-level directories for builder file operations
_ALLOWED_PATH_PREFIXES = (
    "src/probos/",
    "tests/",
    "config/",
    "docs/",
    "prompts/",
)

# Paths that must never be written by the builder
_FORBIDDEN_PATHS = (
    ".git/",
    ".env",
    "pyproject.toml",
    ".github/",
)


def _validate_file_path(path_str: str) -> str | None:
    """Validate a file path is safe for builder to write.

    Returns None if valid, or an error message if invalid.
    """
    # Normalize separators
    normalized = path_str.replace("\\", "/")

    # Block path traversal
    if ".." in normalized:
        return f"Path traversal blocked: {path_str}"

    # Block forbidden paths
    for forbidden in _FORBIDDEN_PATHS:
        if normalized.startswith(forbidden) or normalized == forbidden.rstrip("/"):
            return f"Forbidden path: {path_str}"

    # Block absolute paths
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return f"Absolute path blocked: {path_str}"

    # Must be under an allowed prefix (or be a top-level config file like
    # setup.py, conftest.py — allow .py at root)
    if not any(normalized.startswith(prefix) for prefix in _ALLOWED_PATH_PREFIXES):
        # Allow top-level known files
        if normalized in ("conftest.py",):
            return None
        return f"Path outside allowed directories: {path_str} (allowed: {', '.join(_ALLOWED_PATH_PREFIXES)})"

    return None
```

### 2b. Validate paths before writing in `execute_approved_build()`

In the file-write loop (line 2414), add path validation **before** any file
operations:

```python
        # 4. Write/modify files
        for change in file_changes:
            # Validate file path before any disk operations
            path_error = _validate_file_path(change["path"])
            if path_error:
                logger.warning("BuilderAgent: %s — skipping", path_error)
                validation_errors.append(path_error)
                continue

            path = Path(work_dir) / change["path"]
```

This goes right after the `for change in file_changes:` line (2414) and before
the `path = Path(work_dir) / change["path"]` line (2415).

---

## Issue 3: Stray File Rejection in Visiting Officer Path

**File:** `src/probos/cognitive/copilot_adapter.py`

### 3a. Add path validation to disk scan capture

In `CopilotBuilderAdapter.execute()`, the disk scan loop (around line 513-524)
captures all changed/new files from the SDK workspace. Add path filtering so
files outside the expected project structure are logged and skipped:

After the existing skip logic for `__pycache__`, `.git/`, etc., add:

```python
                # Skip files outside expected project structure
                _EXPECTED_PREFIXES = ("src/", "tests/", "config/", "docs/", "prompts/")
                if not any(relative.startswith(p) for p in _EXPECTED_PREFIXES):
                    # Allow top-level known files
                    if relative not in ("conftest.py",):
                        logger.warning(
                            "Visiting officer created file outside expected structure: %s — skipping",
                            relative,
                        )
                        continue
```

This catches the exact failure pattern we've seen: the visiting officer creates
`probos/types.py` instead of `src/probos/types.py`, or `tests/cognitive/test_agent.py`
instead of `tests/test_agent.py`.

### 3b. Log summary of rejected files

After the disk scan loop, add a summary log if any files were rejected:

```python
            if rejected_count > 0:
                logger.warning(
                    "Visiting officer: %d file(s) rejected (outside project structure)",
                    rejected_count,
                )
```

Use a `rejected_count` counter initialized before the loop and incremented on
each skip.

---

## Issue 4: Build Spec File Allowlist (Optional Enhancement)

**File:** `src/probos/cognitive/builder.py`

The `BuildSpec` dataclass (line 89) already has a `target_files` field listing
expected output files. Currently this is only used for context loading in
`perceive()`. Add a soft validation that warns when the builder produces files
not in the spec:

In `execute_approved_build()`, after the file-write loop (after line 2472),
add:

```python
        # 4b. Warn about files not in build spec target list
        if spec.target_files:
            expected = set(spec.target_files)
            actual = set(written + modified_files)
            unexpected = actual - expected
            if unexpected:
                logger.warning(
                    "BuilderAgent: %d file(s) not in build spec target list: %s",
                    len(unexpected), ", ".join(sorted(unexpected)),
                )
                # Soft warning only — don't block. Future: make this a hard gate
                # after trust is established
```

This is advisory (soft gate), matching the pattern of CodeReview (AD-341).

---

## Issue 5: Dirty Working Tree Protection

**File:** `src/probos/cognitive/builder.py`

*Pattern from Aider:* Before editing any file, Aider checks `git status` and
commits existing dirty changes first, cleanly separating human work from AI
work. ProbOS should at minimum refuse to build on a dirty tree.

### 5a. Add dirty tree check at the start of `execute_approved_build()`

Before creating the build branch (before line 2402), check that the working
tree is clean:

```python
    # 2a. Verify clean working tree (prevent contaminating build branch)
    rc, porcelain, _ = await _run_git(["status", "--porcelain"], work_dir)
    if rc == 0 and porcelain.strip():
        result.error = (
            "Working tree has uncommitted changes. "
            "Commit or stash changes before running a build."
        )
        return result
```

This prevents uncommitted human changes from being swept into the build branch
and entangled with AI-generated code. The Captain can commit or stash first.

---

## Issue 6: Untracked File Cleanup on Failed Builds

**File:** `src/probos/cognitive/builder.py`

When a build fails, the `finally` block runs `_git_checkout_main()` which
restores modified files to their pre-build state. However, `git checkout` does
NOT delete newly created files. If the builder created `src/probos/new_file.py`
on the build branch, that file persists as an untracked file on main after
checkout.

The visiting officer path avoids this via temp dir isolation (AD-354), but the
native builder writes directly to the project root. The test-fix loop (AD-338)
can also create files during fix attempts.

### 6a. Track created files and clean up on failure

In the `finally` block, after returning to main and deleting the branch, delete
any files that were created (not modified) during the build if no commit was
made:

```python
    finally:
        # 7. Return to original branch
        await _git_checkout_main(work_dir)
        # Clean up build branch if no commit was made (failed build)
        if not result.commit_hash and result.branch_name:
            logger.info("Cleaning up failed build branch '%s'", result.branch_name)
            await _run_git(["branch", "-D", result.branch_name], work_dir)
            # Delete files created during the failed build (untracked on main)
            for created_path in written:
                full = Path(work_dir) / created_path
                if full.exists():
                    full.unlink()
                    logger.info("Cleaned up untracked file from failed build: %s", created_path)
                    # Remove empty parent dirs up to work_dir
                    parent = full.parent
                    while parent != Path(work_dir) and not any(parent.iterdir()):
                        parent.rmdir()
                        parent = parent.parent
```

Note: `written` is the list of newly created files (line 2409). Modified files
(`modified_files`) don't need cleanup because `git checkout main` restores
them. The empty parent directory cleanup prevents stray empty directories like
`probos/cognitive/` from lingering.

### 6b. Ensure `written` is accessible in `finally`

The `written` list is already declared before the `try` block (line 2409), so
it's accessible in `finally`. No changes needed for scoping.

---

## Test Requirements

### New Tests (add to a new `tests/test_builder_guardrails.py`)

1. **`test_validate_file_path_allowed`** — Verify `_validate_file_path()` returns
   `None` for valid paths: `src/probos/config.py`, `tests/test_foo.py`,
   `config/system.yaml`, `docs/guide.md`.

2. **`test_validate_file_path_traversal_blocked`** — Verify path traversal is
   blocked: `../../etc/passwd`, `src/../../../evil.py`.

3. **`test_validate_file_path_forbidden`** — Verify forbidden paths are blocked:
   `.git/config`, `.env`, `pyproject.toml`.

4. **`test_validate_file_path_outside_allowed`** — Verify paths outside allowed
   prefixes are blocked: `probos/types.py`, `random/file.py`, `node_modules/foo.js`.

5. **`test_validate_file_path_absolute_blocked`** — Verify absolute paths are
   blocked: `/etc/passwd`, `C:\Windows\system32\cmd.exe`.

6. **`test_stale_branch_cleanup`** — Create a branch named `builder/test-stale`,
   switch back to main, then call `_git_create_branch("builder/test-stale", ...)`.
   Verify it succeeds (old branch was deleted and new one created).

7. **`test_failed_build_deletes_branch`** — Mock a build that fails (tests don't
   pass), verify the build branch is deleted in the finally block. Use
   `git branch --list` to confirm branch no longer exists.

8. **`test_dirty_working_tree_aborts_build`** — Create an uncommitted change,
   then call `execute_approved_build()`. Verify `result.success` is `False` and
   `result.error` mentions uncommitted changes. Clean up after test.

9. **`test_untracked_files_cleaned_on_failure`** — Mock a build that creates a
   new file then fails. Verify the created file is deleted after the `finally`
   block runs. Verify empty parent dirs are also removed.

---

## Guardrail Coverage Matrix

Which builder paths are protected by each guardrail:

| Guardrail | Native Builder | Visiting Officer | Why |
|-----------|:-:|:-:|-----|
| Issue 1: Branch lifecycle | Yes | Yes | Both use `execute_approved_build()` |
| Issue 2: Path validation | Yes | Yes | Both use `execute_approved_build()` |
| Issue 3: Disk scan filtering | — | Yes | Visiting-only (copilot_adapter.py) |
| Issue 4: Spec allowlist | Yes | Yes | Both use `execute_approved_build()` |
| Issue 5: Dirty tree check | Yes | Yes | Both use `execute_approved_build()` |
| Issue 6: Untracked cleanup | Yes | Yes | Both use `execute_approved_build()` |

Issue 3 is the **first line of defense** for visiting officers — it catches bad
files before they reach the shared pipeline. Issues 1, 2, 4, 5, 6 are the
**shared second line** that protects against both builder types.

---

## Files to Modify

- `src/probos/cognitive/builder.py` — Issues 1, 2, 4, 5, 6
  - `_git_create_branch()`: stale branch handling (1b)
  - New function `_validate_file_path()` + constants: path validation (2a)
  - `execute_approved_build()`: dirty tree check (5a), path validation in file loop (2b), spec allowlist warning (4), branch cleanup + untracked file cleanup in finally (1a, 6a)
- `src/probos/cognitive/copilot_adapter.py` — Issue 3
  - `execute()` disk scan: path filtering for visiting officer output (3a, 3b)
- `tests/test_builder_guardrails.py` — New test file with 9 tests

## Constraints

- Do NOT modify any other files
- Do NOT change the build execution flow (order of operations stays the same)
- Do NOT make path validation a hard gate for Issue 4 (spec allowlist) — soft warning only
- Path validation (Issue 2) IS a hard gate — invalid paths are skipped with a validation error
- Dirty tree check (Issue 5) IS a hard gate — build aborts with error
- Untracked file cleanup (Issue 6) only deletes files from the `written` list — never touches files the builder didn't create
- Do NOT remove or modify existing validation (`_validate_python`, SEARCH block warnings)
- Keep `_ALLOWED_PATH_PREFIXES` and `_FORBIDDEN_PATHS` as module-level constants for easy maintenance
- Branch cleanup should only delete `builder/` prefixed branches, never `main` or user branches
- All new functions must have docstrings
- Empty parent directory cleanup must stop at `work_dir` (never remove project root dirs)
