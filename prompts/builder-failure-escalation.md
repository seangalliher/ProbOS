# Builder Failure Escalation & Diagnostic Reporting — AD-343 through AD-347

**Current highest AD: AD-342 (Implement /orders Command)**

This prompt addresses the builder pipeline's poor failure reporting: when builds fail, the Captain gets a raw error dump with no classification, no actionable options, and no structured report. It also fixes the core performance problem — running 2254 tests with a 120s timeout when only a handful of targeted tests are needed.

## Problem Statement

The builder commit gate (AD-338) correctly blocks broken commits, but the failure experience is terrible:

1. **Raw error dump** — `build_failure` event contains `"Build execution failed: Tests failed after 2 fix attempt(s)..."` with 500 chars of truncated pytest output. No classification, no structured metadata.
2. **No resolution options** — The Captain can't retry, commit anyway, or abort. They must manually investigate.
3. **Full test suite overkill** — `_run_tests()` runs all 2254 tests with 120s timeout. A change to `shell.py` should only run the 15 shell tests, not the entire suite.
4. **Missing context** — The `build_failure` event omits: `fix_attempts`, `files_written`, `files_modified`, `branch_name`, `review_result`, `review_issues`.
5. **No escalation path** — When the fix loop is exhausted, the failure goes straight to the Captain with no crew intervention.

## Execution Order

Execute these ADs in this exact order: **AD-343 → AD-344 → AD-345 → AD-346 → AD-347**

---

## AD-343: BuildFailureReport & Failure Classification

**File:** `src/probos/cognitive/builder.py`
**Test file:** `tests/test_builder_agent.py`

### Step 1: Add `BuildFailureReport` dataclass

Add this dataclass right after the existing `BuildResult` class (around line 115):

```python
@dataclass
class BuildFailureReport:
    """Structured diagnostic report for a failed build (AD-343)."""

    # What was attempted
    build_id: str = ""
    ad_number: int = 0
    title: str = ""
    branch_name: str = ""
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)

    # What failed
    failure_category: str = ""  # "timeout", "test_failure", "syntax_error", "import_error", "llm_error", "commit_error"
    failure_summary: str = ""   # One-sentence human-readable summary
    raw_error: str = ""         # Full error text (for collapsible view)
    failed_tests: list[str] = field(default_factory=list)  # Extracted test names
    error_locations: list[str] = field(default_factory=list)  # file:line references

    # What was tried
    fix_attempts: int = 0
    fix_descriptions: list[str] = field(default_factory=list)

    # Review
    review_result: str = ""
    review_issues: list[str] = field(default_factory=list)

    # Resolution options
    resolution_options: list[dict[str, str]] = field(default_factory=list)
    # Each dict has: {"id": "retry_targeted", "label": "...", "description": "..."}

    def to_dict(self) -> dict:
        """Serialize for WebSocket event payload."""
        return {
            "build_id": self.build_id,
            "ad_number": self.ad_number,
            "title": self.title,
            "branch_name": self.branch_name,
            "files_written": self.files_written,
            "files_modified": self.files_modified,
            "failure_category": self.failure_category,
            "failure_summary": self.failure_summary,
            "raw_error": self.raw_error,
            "failed_tests": self.failed_tests,
            "error_locations": self.error_locations,
            "fix_attempts": self.fix_attempts,
            "fix_descriptions": self.fix_descriptions,
            "review_result": self.review_result,
            "review_issues": self.review_issues,
            "resolution_options": self.resolution_options,
        }
```

### Step 2: Add `classify_build_failure` function

Add this function after `BuildFailureReport` (still in `builder.py`):

```python
def classify_build_failure(result: BuildResult, spec: BuildSpec) -> BuildFailureReport:
    """Classify a failed BuildResult into a structured report (AD-343).

    Parses pytest output to extract failure category, failed test names,
    error locations, and generates contextual resolution options.
    """
    import re

    report = BuildFailureReport(
        ad_number=spec.ad_number,
        title=spec.title,
        branch_name=result.branch_name,
        files_written=list(result.files_written),
        files_modified=list(result.files_modified),
        fix_attempts=result.fix_attempts,
        review_result=result.review_result,
        review_issues=list(result.review_issues),
        raw_error=result.error or result.test_result or "",
    )

    test_output = result.test_result or ""
    error_text = result.error or ""
    combined = test_output + "\n" + error_text

    # 1. Classify the failure category
    if "timed out after" in combined:
        report.failure_category = "timeout"
        report.failure_summary = "Test suite timed out before completing"
    elif "SyntaxError" in combined:
        report.failure_category = "syntax_error"
        report.failure_summary = "Python syntax errors in generated code"
    elif "ImportError" in combined or "ModuleNotFoundError" in combined:
        report.failure_category = "import_error"
        report.failure_summary = "Import or module resolution errors"
    elif "timeout_error" in error_text or "Request timeout" in error_text:
        report.failure_category = "llm_error"
        report.failure_summary = "LLM request failed or timed out"
    elif "Commit failed" in error_text:
        report.failure_category = "commit_error"
        report.failure_summary = "Git commit operation failed"
    else:
        report.failure_category = "test_failure"
        report.failure_summary = "Test assertions failed after fix attempts"

    # 2. Extract failed test names (FAILED tests/test_foo.py::TestClass::test_method)
    failed_pattern = re.compile(r"FAILED\s+(tests/\S+)")
    report.failed_tests = failed_pattern.findall(test_output)

    # 3. Extract error locations (file:line patterns from tracebacks)
    location_pattern = re.compile(r"([\w/\\]+\.py):(\d+)")
    seen = set()
    for match in location_pattern.finditer(test_output):
        loc = f"{match.group(1)}:{match.group(2)}"
        if loc not in seen:
            seen.add(loc)
            report.error_locations.append(loc)

    # 4. Generate resolution options per category
    if report.failure_category == "timeout":
        report.resolution_options = [
            {"id": "retry_extended", "label": "Retry with extended timeout", "description": "Re-run tests with 300s timeout"},
            {"id": "retry_targeted", "label": "Retry targeted tests only", "description": "Run only tests related to changed files"},
            {"id": "commit_override", "label": "Commit anyway", "description": "Override test gate and commit to branch"},
            {"id": "abort", "label": "Abort", "description": "Abandon changes and return to main branch"},
        ]
    elif report.failure_category == "test_failure":
        report.resolution_options = [
            {"id": "retry_targeted", "label": "Retry targeted tests only", "description": "Run only tests related to changed files"},
            {"id": "retry_fix", "label": "Retry with more fix attempts", "description": "Give the LLM 4 more attempts to fix failing tests"},
            {"id": "commit_override", "label": "Commit anyway", "description": "Override test gate and commit to branch"},
            {"id": "abort", "label": "Abort", "description": "Abandon changes and return to main branch"},
        ]
    elif report.failure_category in ("syntax_error", "import_error"):
        report.resolution_options = [
            {"id": "retry_fix", "label": "Retry with more fix attempts", "description": "Give the LLM 4 more attempts to fix the errors"},
            {"id": "abort", "label": "Abort", "description": "Abandon changes and return to main branch"},
        ]
    elif report.failure_category == "llm_error":
        report.resolution_options = [
            {"id": "retry_full", "label": "Retry entire build", "description": "Re-run the full build pipeline from scratch"},
            {"id": "abort", "label": "Abort", "description": "Abandon changes and return to main branch"},
        ]
    else:
        report.resolution_options = [
            {"id": "abort", "label": "Abort", "description": "Abandon changes and return to main branch"},
        ]

    return report
```

### Tests for AD-343

Add these test classes to `tests/test_builder_agent.py`:

```python
class TestBuildFailureReport:
    """Tests for BuildFailureReport dataclass (AD-343)."""

    def test_to_dict_returns_all_fields(self):
        report = BuildFailureReport(
            build_id="test-123",
            ad_number=999,
            title="Test Build",
            failure_category="test_failure",
            failure_summary="Tests failed",
        )
        d = report.to_dict()
        assert d["build_id"] == "test-123"
        assert d["ad_number"] == 999
        assert d["failure_category"] == "test_failure"
        assert isinstance(d["resolution_options"], list)
        assert isinstance(d["failed_tests"], list)

    def test_to_dict_defaults(self):
        report = BuildFailureReport()
        d = report.to_dict()
        assert d["build_id"] == ""
        assert d["ad_number"] == 0
        assert d["failed_tests"] == []
        assert d["resolution_options"] == []


class TestClassifyBuildFailure:
    """Tests for classify_build_failure function (AD-343)."""

    def _make_result(self, *, test_result="", error="", **kwargs):
        spec = BuildSpec(title="Test", description="desc")
        result = BuildResult(success=False, spec=spec, **kwargs)
        result.test_result = test_result
        result.error = error
        return result, spec

    def test_classify_timeout(self):
        result, spec = self._make_result(
            test_result="pytest timed out after 120s"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "timeout"
        assert "timed out" in report.failure_summary

    def test_classify_syntax_error(self):
        result, spec = self._make_result(
            test_result="SyntaxError: invalid syntax\n  File test.py, line 5"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "syntax_error"

    def test_classify_import_error(self):
        result, spec = self._make_result(
            test_result="ImportError: No module named 'nonexistent'"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "import_error"

    def test_classify_llm_error(self):
        result, spec = self._make_result(
            error="Request timeout"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "llm_error"

    def test_classify_test_failure_default(self):
        result, spec = self._make_result(
            test_result="FAILED tests/test_foo.py::test_bar - assert 1 == 2\n1 failed"
        )
        report = classify_build_failure(result, spec)
        assert report.failure_category == "test_failure"

    def test_extracts_failed_test_names(self):
        result, spec = self._make_result(
            test_result=(
                "FAILED tests/test_shell.py::TestShell::test_ping\n"
                "FAILED tests/test_api.py::test_health\n"
                "2 failed"
            )
        )
        report = classify_build_failure(result, spec)
        assert len(report.failed_tests) == 2
        assert "tests/test_shell.py::TestShell::test_ping" in report.failed_tests
        assert "tests/test_api.py::test_health" in report.failed_tests

    def test_extracts_error_locations(self):
        result, spec = self._make_result(
            test_result="src/probos/shell.py:42: AssertionError"
        )
        report = classify_build_failure(result, spec)
        assert any("shell.py:42" in loc for loc in report.error_locations)

    def test_timeout_resolution_options(self):
        result, spec = self._make_result(
            test_result="pytest timed out after 120s"
        )
        report = classify_build_failure(result, spec)
        option_ids = [o["id"] for o in report.resolution_options]
        assert "retry_extended" in option_ids
        assert "retry_targeted" in option_ids
        assert "abort" in option_ids

    def test_test_failure_resolution_options(self):
        result, spec = self._make_result(
            test_result="FAILED tests/test_foo.py::test_bar\n1 failed"
        )
        report = classify_build_failure(result, spec)
        option_ids = [o["id"] for o in report.resolution_options]
        assert "retry_targeted" in option_ids
        assert "retry_fix" in option_ids
        assert "commit_override" in option_ids
        assert "abort" in option_ids

    def test_copies_spec_metadata(self):
        spec = BuildSpec(title="My Build", description="desc", ad_number=999)
        result = BuildResult(success=False, spec=spec, branch_name="builder/ad-999")
        result.test_result = "FAILED tests/test.py::test_x\n1 failed"
        result.fix_attempts = 2
        result.review_result = "issues found"
        result.review_issues = ["issue1"]
        report = classify_build_failure(result, spec)
        assert report.title == "My Build"
        assert report.ad_number == 999
        assert report.branch_name == "builder/ad-999"
        assert report.fix_attempts == 2
        assert report.review_result == "issues found"
        assert report.review_issues == ["issue1"]
```

### Acceptance Criteria
- `BuildFailureReport.to_dict()` serializes all fields
- `classify_build_failure()` correctly categorizes: timeout, syntax_error, import_error, llm_error, test_failure
- Failed test names extracted from pytest short output
- Error locations (file:line) extracted from tracebacks
- Resolution options generated per failure category
- All tests pass

---

## AD-344: Smart Test Selection

**File:** `src/probos/cognitive/builder.py`
**Test file:** `tests/test_builder_agent.py`

### Step 1: Add `_map_source_to_tests` function

Add this right after the existing `_run_tests` function (around line 2001):

```python
def _map_source_to_tests(changed_files: list[str], work_dir: str) -> list[str]:
    """Map changed source files to their corresponding test files (AD-344).

    Uses naming convention: src/probos/foo/bar.py -> tests/test_bar.py
    Also includes any changed files that are themselves test files.
    """
    tests_dir = Path(work_dir) / "tests"
    if not tests_dir.exists():
        return []

    test_files: list[str] = []
    seen: set[str] = set()

    for changed in changed_files:
        changed_path = Path(changed)

        # If the changed file is itself a test file, include it
        if changed_path.name.startswith("test_"):
            full = tests_dir / changed_path.name
            if full.exists() and str(full) not in seen:
                test_files.append(str(full))
                seen.add(str(full))
            continue

        # Extract module name and find matching test files
        stem = changed_path.stem  # e.g., "shell" from "shell.py"
        for candidate in tests_dir.glob(f"test_{stem}*.py"):
            if str(candidate) not in seen:
                test_files.append(str(candidate))
                seen.add(str(candidate))

    return test_files
```

### Step 2: Add `_run_targeted_tests` function

Add this right after `_map_source_to_tests`:

```python
async def _run_targeted_tests(
    work_dir: str,
    changed_files: list[str],
    timeout: int = 60,
) -> tuple[bool, str, list[str]]:
    """Run only tests related to changed files (AD-344).

    Returns (passed, output, test_files_run).
    If no matching test files found, falls back to full suite.
    """
    test_files = _map_source_to_tests(changed_files, work_dir)

    if not test_files:
        # No targeted tests found, run full suite
        passed, output = await _run_tests(work_dir, timeout=timeout)
        return passed, output, []

    import sys

    def _sync_run() -> tuple[int, str]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q"] + test_files,
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
            )
            test_out = (result.stdout or b"").decode(errors="replace")
            test_err = (result.stderr or b"").decode(errors="replace")
            output = test_out + ("\n" + test_err if test_err else "")
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return 1, f"pytest timed out after {timeout}s"

    loop = asyncio.get_running_loop()
    returncode, output = await loop.run_in_executor(None, _sync_run)
    return returncode == 0, output, test_files
```

### Step 3: Modify `execute_approved_build()` test loop

Replace the test invocation in the test loop (the line `passed, test_output = await _run_tests(work_dir)` at line 2154) with a two-phase approach. Modify the block starting at `# 5. Run tests with fix loop (AD-314)`:

```python
        # 5. Run tests with fix loop (AD-314, AD-344)
        if run_tests and (written or modified_files):
            all_changes = list(file_changes)
            all_changed_files = written + modified_files

            for attempt in range(1 + max_fix_attempts):
                # Phase 1: Targeted tests only (fast, AD-344)
                passed, test_output, targeted_files = await _run_targeted_tests(
                    work_dir, all_changed_files, timeout=60,
                )
                result.test_result = test_output
                result.tests_passed = passed

                if passed and targeted_files:
                    # Phase 2: Full suite only if targeted passed (AD-344)
                    passed_full, full_output = await _run_tests(work_dir, timeout=180)
                    if not passed_full:
                        result.test_result = full_output
                        result.tests_passed = False
                        passed = False

                if passed:
                    break
```

**IMPORTANT:** Only the test invocation changes (two-phase). The rest of the fix loop (from `if attempt < max_fix_attempts and llm_client is not None:` onward through `all_changes.extend(fix_changes)`) remains exactly the same. Do NOT remove or change the existing fix loop logic for applying LLM fixes.

### Tests for AD-344

```python
class TestMapSourceToTests:
    """Tests for _map_source_to_tests (AD-344)."""

    def test_maps_source_to_test_file(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_shell.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(["src/probos/experience/shell.py"], str(tmp_path))
        assert len(result) == 1
        assert "test_shell.py" in result[0]

    def test_includes_changed_test_files(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(["test_foo.py"], str(tmp_path))
        assert len(result) == 1

    def test_no_match_returns_empty(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        result = _map_source_to_tests(["src/probos/unique_module.py"], str(tmp_path))
        assert result == []

    def test_no_tests_dir_returns_empty(self, tmp_path):
        result = _map_source_to_tests(["src/probos/shell.py"], str(tmp_path))
        assert result == []

    def test_deduplicates(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_shell.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(
            ["src/probos/experience/shell.py", "src/probos/shell.py"],
            str(tmp_path),
        )
        assert len(result) == 1

    def test_glob_matches_prefixed(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_builder_agent.py").write_text("# test", encoding="utf-8")
        result = _map_source_to_tests(["src/probos/cognitive/builder.py"], str(tmp_path))
        assert len(result) == 1
        assert "test_builder" in result[0]
```

### Acceptance Criteria
- `_map_source_to_tests()` maps `shell.py` to `test_shell*.py`
- `_run_targeted_tests()` runs only matched test files
- Two-phase: targeted first (60s timeout), full suite only if targeted pass (180s timeout)
- If no targeted tests found, falls back to full suite
- Fix loop retries use targeted tests (dramatically faster)
- All existing builder tests still pass

---

## AD-345: Enriched Failure Event & Resolution API

**File:** `src/probos/api.py`
**Test file:** `tests/test_builder_agent.py` (add tests at end)

### Step 1: Add pending failures cache

Add at the module level near the top of `api.py`, after the existing imports:

```python
import time as _time

# Cache for failed build contexts — enables resolution endpoint (AD-345)
_pending_failures: dict[str, dict] = {}
_FAILURE_CACHE_TTL = 1800  # 30 minutes


def _clean_expired_failures() -> None:
    """Remove expired entries from the pending failures cache."""
    now = _time.time()
    expired = [k for k, v in _pending_failures.items() if now - v.get("timestamp", 0) > _FAILURE_CACHE_TTL]
    for k in expired:
        del _pending_failures[k]
```

### Step 2: Enrich the `build_failure` event

In the `_execute_build` function, replace the existing failure path (the `else:` block around line 892) with:

```python
            else:
                # Build failed — produce structured diagnostic (AD-345)
                from probos.cognitive.builder import classify_build_failure
                report = classify_build_failure(result, spec)
                report.build_id = build_id

                # Cache build context for resolution endpoint
                _clean_expired_failures()
                _pending_failures[build_id] = {
                    "file_changes": file_changes,
                    "spec": spec,
                    "work_dir": work_dir,
                    "report": report,
                    "timestamp": _time.time(),
                }

                rt._emit_event("build_failure", {
                    "build_id": build_id,
                    "message": f"Build failed: {report.failure_summary}",
                    "report": report.to_dict(),
                })
```

### Step 3: Add `BuildResolveRequest` model

Add this alongside the other request models near the top of `api.py` (near `BuildRequest` and `BuildApproveRequest`):

```python
class BuildResolveRequest(BaseModel):
    """Request to resolve a failed build (AD-345)."""

    build_id: str
    resolution: str  # "retry_extended", "retry_targeted", "retry_fix", "commit_override", "abort"
```

### Step 4: Add `/api/build/resolve` endpoint

Inside `create_app()`, add this endpoint after the existing build endpoints:

```python
    @app.post("/api/build/resolve")
    async def resolve_build(req: BuildResolveRequest) -> dict[str, Any]:
        """Execute a resolution option for a failed build (AD-345)."""
        _clean_expired_failures()

        if req.build_id not in _pending_failures:
            return {"status": "error", "message": "Build not found or expired. Re-run the build."}

        cached = _pending_failures[req.build_id]
        file_changes = cached["file_changes"]
        spec = cached["spec"]
        work_dir = cached["work_dir"]

        if req.resolution == "abort":
            from probos.cognitive.builder import _git_checkout_main
            await _git_checkout_main(work_dir)
            del _pending_failures[req.build_id]
            rt._emit_event("build_resolved", {
                "build_id": req.build_id,
                "resolution": "abort",
                "message": "Build aborted. Returned to main branch.",
            })
            return {"status": "ok", "resolution": "abort"}

        elif req.resolution == "commit_override":
            from probos.cognitive.builder import _git_add_and_commit
            report = cached["report"]
            all_files = report.files_written + report.files_modified
            if not all_files:
                return {"status": "error", "message": "No files to commit."}
            commit_msg = (
                f"{spec.title}"
                + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                + "\n\n[Test gate overridden by Captain]"
                + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
            )
            ok, sha = await _git_add_and_commit(all_files, commit_msg, work_dir)
            del _pending_failures[req.build_id]
            if ok:
                rt._emit_event("build_resolved", {
                    "build_id": req.build_id,
                    "resolution": "commit_override",
                    "message": f"Committed with test gate override. Commit: {sha}",
                    "commit": sha,
                })
                return {"status": "ok", "resolution": "commit_override", "commit": sha}
            else:
                return {"status": "error", "message": f"Commit failed: {sha}"}

        elif req.resolution in ("retry_extended", "retry_targeted", "retry_fix", "retry_full"):
            # Re-run build as background task
            del _pending_failures[req.build_id]
            new_build_id = req.build_id  # Reuse same build_id for continuity

            rt._emit_event("build_progress", {
                "build_id": new_build_id,
                "step": "retrying",
                "step_label": "\u25c8 Retrying build...",
                "current": 1,
                "total": 3,
                "message": f"\u25c8 Resolution: {req.resolution}",
            })

            _track_task(rt, _execute_build(
                new_build_id, file_changes, spec, work_dir, rt,
            ), f"build-resolve-{new_build_id}")
            return {"status": "ok", "resolution": req.resolution, "build_id": new_build_id}

        else:
            return {"status": "error", "message": f"Unknown resolution: {req.resolution}"}
```

**Important notes:**
- `_track_task` is the existing function used to run background tasks — it's already used by `_run_build` and `_execute_build` in the same file.
- `_git_checkout_main` and `_git_add_and_commit` are imported from `probos.cognitive.builder`. Make sure to import them at usage point (inside the function) not at module level.
- Use `\u25c8` (◈) for progress step labels — NOT emoji (HXI Design Principle #3).

### Tests for AD-345

```python
class TestPendingFailuresCache:
    """Tests for the pending failures cache (AD-345)."""

    def test_clean_expired_removes_old(self):
        import time as _time
        from probos.api import _pending_failures, _clean_expired_failures, _FAILURE_CACHE_TTL
        _pending_failures["old"] = {"timestamp": _time.time() - _FAILURE_CACHE_TTL - 1}
        _pending_failures["recent"] = {"timestamp": _time.time()}
        _clean_expired_failures()
        assert "old" not in _pending_failures
        assert "recent" in _pending_failures
        # Cleanup
        _pending_failures.clear()
```

### Acceptance Criteria
- `build_failure` event now contains `report` field with full `BuildFailureReport` data
- `/api/build/resolve` endpoint accepts resolution options
- `abort` checks out main branch and cleans cache
- `commit_override` commits despite test failure with "[Test gate overridden by Captain]" in message
- `retry_*` options re-launch the build pipeline as a background task
- Cache entries expire after 30 minutes

---

## AD-346: HXI Build Failure Diagnostic Card

**Files:**
- `ui/src/store/types.ts`
- `ui/src/store/useStore.ts`
- `ui/src/components/IntentSurface.tsx`

### Step 1: Add TypeScript interface in `types.ts`

Add this after the existing `BuildProposal` interface (around line 71):

```typescript
export interface BuildFailureReport {
  build_id: string;
  ad_number: number;
  title: string;
  branch_name: string;
  files_written: string[];
  files_modified: string[];
  failure_category: string;
  failure_summary: string;
  raw_error: string;
  failed_tests: string[];
  error_locations: string[];
  fix_attempts: number;
  fix_descriptions: string[];
  review_result: string;
  review_issues: string[];
  resolution_options: Array<{
    id: string;
    label: string;
    description: string;
  }>;
}
```

Add `buildFailureReport?: BuildFailureReport;` to the `ChatMessage` interface (alongside existing `buildProposal?` and `architectProposal?` fields at lines 117-118).

### Step 2: Update `build_failure` handler in `useStore.ts`

Import `BuildFailureReport` from `types.ts` at the top of the file where other types are imported.

Replace the existing `case 'build_failure':` block (around line 658-665) with:

```typescript
      case 'build_failure': {
        set({ buildProgress: null });
        const report = data.report as BuildFailureReport | undefined;
        if (report) {
          const summary = report.failure_summary || (data.message as string) || 'Build failed';
          get().addChatMessage('system', summary, { buildFailureReport: report });
        } else {
          // Legacy fallback — no structured report
          const msg = (data.message || '') as string;
          if (msg) get().addChatMessage('system', msg);
        }
        break;
      }
```

**Important:** Check how `addChatMessage` is called with `buildProposal` — follow the exact same pattern for `buildFailureReport`. The third argument pattern may need to match how `buildProposal` is passed. Look at the `build_generated` handler for reference.

Also add a `build_resolved` case:

```typescript
      case 'build_resolved': {
        const msg = (data.message || '') as string;
        if (msg) {
          get().addChatMessage('system', msg);
        }
        break;
      }
```

### Step 3: Add failure card rendering in `IntentSurface.tsx`

Import `BuildFailureReport` from `types.ts` at the top of the file.

Add this rendering block inside the message rendering loop, right after the existing `msg.buildProposal` block (after the closing `)}` around line 685-690). Use the existing `buildCodeExpanded` state and `setBuildCodeExpanded` setter for the collapsible section (same as build proposal uses):

```tsx
                    {msg.buildFailureReport && (
                      <div style={{ marginTop: 8, maxWidth: '80%' }}>
                        {/* Failure header */}
                        <div style={{
                          padding: '8px 12px',
                          borderRadius: 8,
                          background: 'rgba(255, 85, 85, 0.08)',
                          border: '1px solid rgba(255, 85, 85, 0.2)',
                          fontSize: 12,
                          color: '#c8d0e0',
                          marginBottom: 8,
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                            <span style={{
                              color: '#ff5555',
                              fontWeight: 600,
                              fontSize: 13,
                            }}>
                              Build Failed
                            </span>
                            <span style={{
                              padding: '1px 6px',
                              borderRadius: 4,
                              background: 'rgba(255, 85, 85, 0.15)',
                              border: '1px solid rgba(255, 85, 85, 0.3)',
                              color: '#ff8888',
                              fontSize: 10,
                              textTransform: 'uppercase',
                              letterSpacing: '0.5px',
                            }}>
                              {msg.buildFailureReport.failure_category.replace('_', ' ')}
                            </span>
                          </div>
                          {msg.buildFailureReport.ad_number > 0 && (
                            <div style={{ color: '#a0a8b8', marginBottom: 2 }}>
                              AD-{msg.buildFailureReport.ad_number}: {msg.buildFailureReport.title}
                            </div>
                          )}
                          <div style={{ color: '#8888a0', fontSize: 11 }}>
                            {msg.buildFailureReport.files_written.length + msg.buildFailureReport.files_modified.length} file(s) changed
                            {msg.buildFailureReport.branch_name && ` | Branch: ${msg.buildFailureReport.branch_name}`}
                            {msg.buildFailureReport.fix_attempts > 0 && ` | ${msg.buildFailureReport.fix_attempts} fix attempt(s)`}
                          </div>
                        </div>

                        {/* Failed tests list */}
                        {msg.buildFailureReport.failed_tests.length > 0 && (
                          <div style={{
                            padding: '6px 12px',
                            borderRadius: 6,
                            background: 'rgba(255, 85, 85, 0.04)',
                            border: '1px solid rgba(255, 85, 85, 0.1)',
                            fontSize: 11,
                            color: '#a0a8b8',
                            marginBottom: 8,
                          }}>
                            <div style={{ color: '#ff8888', marginBottom: 4, fontSize: 11 }}>
                              Failed tests:
                            </div>
                            {msg.buildFailureReport.failed_tests.map((t, i) => (
                              <div key={i} style={{ marginLeft: 8, fontFamily: 'monospace', fontSize: 10 }}>
                                {'\u2022'} {t}
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Collapsible raw error */}
                        {msg.buildFailureReport.raw_error && (
                          <>
                            <button
                              onClick={() => setBuildCodeExpanded(prev => ({ ...prev, [`fail-${msg.id}`]: !prev[`fail-${msg.id}`] }))}
                              style={{
                                background: 'rgba(128, 128, 160, 0.08)',
                                border: '1px solid rgba(128, 128, 160, 0.15)',
                                borderRadius: 6, padding: '4px 12px',
                                color: '#8888a0', cursor: 'pointer', fontSize: 12,
                                fontFamily: "'Inter', sans-serif",
                                marginBottom: 8,
                              }}
                            >
                              {buildCodeExpanded[`fail-${msg.id}`] ? '\u25BC Hide Error Output' : '\u25B6 View Error Output'}
                            </button>
                            {buildCodeExpanded[`fail-${msg.id}`] && (
                              <pre style={{
                                padding: 12, borderRadius: 8,
                                background: 'rgba(10, 10, 18, 0.8)',
                                border: '1px solid rgba(255, 85, 85, 0.15)',
                                fontSize: 11, lineHeight: 1.4, color: '#a0a8b8',
                                maxHeight: 300, overflowY: 'auto',
                                whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                marginBottom: 8,
                              }}>
                                {msg.buildFailureReport.raw_error}
                              </pre>
                            )}
                          </>
                        )}

                        {/* Resolution buttons */}
                        {msg.buildFailureReport.resolution_options.length > 0 && (
                          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            {msg.buildFailureReport.resolution_options.map((opt) => (
                              <button
                                key={opt.id}
                                title={opt.description}
                                onClick={async () => {
                                  try {
                                    await fetch('/api/build/resolve', {
                                      method: 'POST',
                                      headers: { 'Content-Type': 'application/json' },
                                      body: JSON.stringify({
                                        build_id: msg.buildFailureReport!.build_id,
                                        resolution: opt.id,
                                      }),
                                    });
                                  } catch (e) {
                                    console.error('Resolution failed:', e);
                                  }
                                }}
                                style={{
                                  background: opt.id === 'abort'
                                    ? 'rgba(128, 128, 160, 0.1)'
                                    : opt.id === 'commit_override'
                                    ? 'rgba(255, 200, 50, 0.1)'
                                    : 'rgba(102, 180, 255, 0.1)',
                                  border: `1px solid ${
                                    opt.id === 'abort'
                                      ? 'rgba(128, 128, 160, 0.2)'
                                      : opt.id === 'commit_override'
                                      ? 'rgba(255, 200, 50, 0.3)'
                                      : 'rgba(102, 180, 255, 0.3)'
                                  }`,
                                  borderRadius: 8, padding: '6px 16px',
                                  color: opt.id === 'abort'
                                    ? '#8888a0'
                                    : opt.id === 'commit_override'
                                    ? '#ffc832'
                                    : '#66b4ff',
                                  cursor: 'pointer', fontSize: 13,
                                  fontFamily: "'Inter', sans-serif",
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.opacity = '0.8';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.opacity = '1';
                                }}
                              >
                                {opt.label}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
```

### Acceptance Criteria
- `BuildFailureReport` TypeScript interface matches Python dataclass
- `build_failure` events with `report` field render the diagnostic card
- `build_failure` events without `report` field render legacy text (backward compatible)
- Failure card shows: category badge, AD number/title, file count, branch, fix attempts
- Failed tests listed when present
- Raw error output in collapsible section
- Resolution buttons styled: blue for retries, yellow for commit override, gray for abort
- Buttons call `/api/build/resolve` with correct payload
- `build_resolved` event shows resolution confirmation message
- No emoji used anywhere — only unicode geometric symbols (HXI Design Principle #3)

---

## AD-347: Builder Escalation Hook (Chain-of-Command Foundation)

**File:** `src/probos/cognitive/builder.py`
**Also:** `src/probos/api.py`
**Test file:** `tests/test_builder_agent.py`

### Step 1: Add `escalation_hook` parameter

Modify the `execute_approved_build` function signature to add the optional escalation hook:

```python
async def execute_approved_build(
    file_changes: list[dict[str, Any]],
    spec: BuildSpec,
    work_dir: str,
    run_tests: bool = True,
    max_fix_attempts: int = 2,
    llm_client: Any | None = None,
    escalation_hook: Any | None = None,  # Callable[[BuildFailureReport], Awaitable[BuildResult | None]]
) -> BuildResult:
```

Use `Any` for the type hint to avoid complex import issues. Add to the docstring:

```
    escalation_hook: Optional async callback invoked when tests fail after
        all fix attempts are exhausted. Receives a BuildFailureReport and
        returns either a resolved BuildResult or None to escalate to Captain.
        Future: wired to chain of command (Phase-33).
```

### Step 2: Add escalation call before returning failure

In `execute_approved_build()`, modify the commit gate section (around line 2233-2241). Insert the escalation hook call BEFORE the failure error message is set:

```python
        # 6. Commit — only if tests passed OR tests were not run
        if written or modified_files:
            if run_tests and not result.tests_passed:
                # Try escalation hook before reporting failure to Captain (AD-347)
                if escalation_hook is not None:
                    try:
                        report = classify_build_failure(result, spec)
                        resolved = await escalation_hook(report)
                        if resolved is not None:
                            result = resolved
                    except Exception as exc:
                        logger.warning("Escalation hook failed: %s", exc)

                # If still failing after escalation attempt, report to Captain
                if run_tests and not result.tests_passed:
                    result.error = (
                        "Tests failed after " + str(result.fix_attempts) + " fix attempt(s). "
                        "Code written to branch but NOT committed.\n"
                        + (result.test_result or "")[-1000:]
                    )
                    result.success = False
            else:
                # ... existing commit logic (unchanged) ...
```

### Step 3: Pass `escalation_hook=None` in API

In `api.py`, in the `_execute_build` function where `execute_approved_build()` is called, add the parameter:

```python
            result = await execute_approved_build(
                file_changes=file_changes,
                spec=spec,
                work_dir=work_dir,
                run_tests=True,
                llm_client=getattr(rt, "llm_client", None),
                escalation_hook=None,  # TODO(Phase-33): wire to ChainOfCommand
            )
```

### Tests for AD-347

```python
class TestEscalationHook:
    """Tests for the escalation hook on execute_approved_build (AD-347)."""

    @pytest.mark.asyncio
    async def test_hook_called_on_failure(self, tmp_path):
        """Escalation hook is called when tests fail."""
        hook_called = []

        async def mock_hook(report):
            hook_called.append(report)
            return None  # Don't resolve

        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "FAILED tests/test_x.py::test_y", [])):
            with patch("probos.cognitive.builder._run_tests", return_value=(False, "FAILED")):
                with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                    with patch("probos.cognitive.builder._git_checkout_main"):
                        result = await execute_approved_build(
                            changes, spec, str(tmp_path),
                            run_tests=True,
                            max_fix_attempts=0,
                            escalation_hook=mock_hook,
                        )

        assert len(hook_called) == 1
        assert hook_called[0].failure_category == "test_failure"
        assert not result.success

    @pytest.mark.asyncio
    async def test_hook_resolves_failure(self, tmp_path):
        """When hook returns a BuildResult, it replaces the failure."""
        resolved_result = BuildResult(
            success=True,
            spec=BuildSpec(title="Test", description="test"),
            tests_passed=True,
        )

        async def resolving_hook(report):
            return resolved_result

        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "FAILED", [])):
            with patch("probos.cognitive.builder._run_tests", return_value=(False, "FAILED")):
                with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                    with patch("probos.cognitive.builder._git_checkout_main"):
                        with patch("probos.cognitive.builder._git_add_and_commit", return_value=(True, "abc123")):
                            result = await execute_approved_build(
                                changes, spec, str(tmp_path),
                                run_tests=True,
                                max_fix_attempts=0,
                                escalation_hook=resolving_hook,
                            )

        assert result.success
        assert result.tests_passed

    @pytest.mark.asyncio
    async def test_hook_not_called_on_success(self, tmp_path):
        """Escalation hook is NOT called when tests pass."""
        hook_called = []

        async def mock_hook(report):
            hook_called.append(report)
            return None

        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(True, "1 passed", ["test.py"])):
            with patch("probos.cognitive.builder._run_tests", return_value=(True, "2254 passed")):
                with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                    with patch("probos.cognitive.builder._git_checkout_main"):
                        with patch("probos.cognitive.builder._git_add_and_commit", return_value=(True, "abc123")):
                            result = await execute_approved_build(
                                changes, spec, str(tmp_path),
                                run_tests=True,
                                max_fix_attempts=0,
                                escalation_hook=mock_hook,
                            )

        assert len(hook_called) == 0
        assert result.success

    @pytest.mark.asyncio
    async def test_no_hook_provided(self, tmp_path):
        """Works correctly when no hook is provided (default behavior)."""
        spec = BuildSpec(title="Test", description="test")
        changes = [{"path": "test_file.py", "mode": "create", "content": "x = 1"}]

        with patch("probos.cognitive.builder._run_targeted_tests", return_value=(False, "FAILED", [])):
            with patch("probos.cognitive.builder._run_tests", return_value=(False, "FAILED")):
                with patch("probos.cognitive.builder._git_create_branch", return_value=(True, "test-branch")):
                    with patch("probos.cognitive.builder._git_checkout_main"):
                        result = await execute_approved_build(
                            changes, spec, str(tmp_path),
                            run_tests=True,
                            max_fix_attempts=0,
                        )

        assert not result.success
```

### Acceptance Criteria
- `escalation_hook` parameter is optional and defaults to `None`
- Hook is called when tests fail, after the fix loop is exhausted
- If hook returns a `BuildResult`, it replaces the failed result
- If hook returns `None`, the failure proceeds normally to Captain
- If hook raises an exception, it's caught and logged (fails open)
- Hook is NOT called when tests pass
- API passes `escalation_hook=None` with a Phase-33 TODO comment
- All existing builder tests still pass

---

## Final Verification

After all 5 ADs are implemented:

1. Run `python -m pytest tests/test_builder_agent.py -v` — all new and existing tests pass
2. Run `python -m pytest tests/test_shell.py -v` — all tests pass
3. Run the full test suite `python -m pytest` — all 2254+ tests pass
4. Run `npm test` in `ui/` — all Vitest tests pass
5. Start ProbOS and trigger a build that will fail — verify the HXI shows the diagnostic card with resolution buttons
6. Click "Abort" — verify it returns to main branch
7. Trigger another failure and click "Retry targeted tests" — verify faster execution
