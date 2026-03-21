# Build Prompt: Move Validation Check Before Commit (AD-367)

## Context

GPT-5.4 code review found that in `execute_approved_build()`, validation
errors (syntax errors from `ast.parse()`) are accumulated during file writes
but only checked **after** the commit step. When `run_tests=False`, a file
with syntax errors can be committed to the build branch, then the result is
marked as failed — but the commit is already done.

The fix is to check `validation_errors` **before** the commit step, not after.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `src/probos/cognitive/builder.py`

**Change:** Move the `validation_errors` check from after the commit
(current line 2745) to before the commit (before line 2708).

Current order (wrong):
```
Step 5: Test-fix loop
Step 6: Commit (line 2708)
Step 7: Check validation_errors (line 2745) ← too late, already committed
```

Correct order:
```
Step 5: Test-fix loop
Step 5.5: Check validation_errors ← block commit if syntax errors exist
Step 6: Commit (only if no validation errors)
```

Find the section around line 2705-2749. Currently it looks like:

```python
        result.files_written = written
        result.files_modified = modified_files

    # 6. Commit — only if tests passed OR tests were not run
    if written or modified_files:
        if run_tests and not result.tests_passed:
            # ... test failure handling + escalation ...
        else:
            # ... commit ...

    if validation_errors:
        result.error = "Syntax errors:\n" + "\n".join(validation_errors)
        result.success = False
    elif not (run_tests and not result.tests_passed):
        result.success = True
```

Change it to:

```python
        result.files_written = written
        result.files_modified = modified_files

    # 5.5. Block commit if validation errors (syntax errors) exist
    if validation_errors:
        result.error = "Syntax errors:\n" + "\n".join(validation_errors)
        result.success = False
    # 6. Commit — only if tests passed OR tests were not run
    elif written or modified_files:
        if run_tests and not result.tests_passed:
            # ... test failure handling + escalation (unchanged) ...

            # If still failing after escalation attempt, report to Captain
            if run_tests and not result.tests_passed:
                result.error = (
                    "Tests failed after " + str(result.fix_attempts) + " fix attempt(s). "
                    "Code written to branch but NOT committed.\n"
                    + (result.test_result or "")[-1000:]
                )
                result.success = False
        else:
            # ... commit logic (unchanged) ...
            desc_short = spec.description[:200] if spec.description else ""
            commit_msg = (
                f"{spec.title}"
                + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                + (f"\n\n{desc_short}" if desc_short else "")
                + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
            )
            ok, sha = await _git_add_and_commit(
                written + modified_files, commit_msg, work_dir,
            )
            if ok:
                result.commit_hash = sha
            else:
                result.error = f"Commit failed: {sha}"

            if not result.error:
                result.success = True
    else:
        result.success = True
```

The key change: `validation_errors` is checked first. If there are syntax
errors, the commit is **never reached**. The `elif` means if we get to the
commit block, we know there are no validation errors.

---

## Tests

### File: `tests/test_builder_guardrails.py`

Add a test verifying validation errors block commits:

```python
@pytest.mark.asyncio
async def test_validation_errors_block_commit(tmp_path):
    """Files with syntax errors should not be committed even with run_tests=False."""
    work_dir = str(tmp_path)
    subprocess.run(["git", "init", "-b", "main", work_dir], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", work_dir, "commit", "--allow-empty", "-m", "init"],
                   check=True, capture_output=True)

    spec = BuildSpec(title="Bad syntax", description="Test syntax gate")
    file_changes = [
        {"path": "src/bad.py", "mode": "create", "content": "def broken(\n"},
    ]

    result = await execute_approved_build(
        file_changes, spec, work_dir, run_tests=False,
    )

    assert result.success is False
    assert "Syntax errors" in (result.error or "")
    assert result.commit_hash is None, "Should NOT have committed invalid code"
```

---

## Constraints

- Modify ONLY `src/probos/cognitive/builder.py` and the test file
- Do NOT change the validation logic itself — only move when it's checked
- Do NOT modify the escalation hook logic — preserve it exactly
- Keep the `finally` block (branch cleanup, untracked file cleanup) unchanged
- Run `pytest tests/test_builder_guardrails.py tests/test_builder_agent.py -x -q`
  to verify both new and existing tests pass
