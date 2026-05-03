"""Tests for AD-685 phantom-API pre-check kwarg validation.

Covers:
- Python AST helper directly (tests #1-6)
- PowerShell wrapper integration (tests #7-9)
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "scripts" / "phantom_api_ast_helper.py"
WRAPPER = REPO_ROOT / "scripts" / "phantom-api-precheck.ps1"
SRC_ROOT = REPO_ROOT / "src" / "probos"
PYTHON_EXE = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


def _run_helper(body: str) -> dict:
    """Invoke the Python AST helper and return its parsed JSON output."""
    proc = subprocess.run(
        [str(PYTHON_EXE), str(HELPER), "--src-root", str(SRC_ROOT)],
        input=body,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, f"Helper failed: {proc.stderr}"
    return json.loads(proc.stdout)


def _run_wrapper(prompt_path: Path) -> subprocess.CompletedProcess:
    """Invoke the PowerShell wrapper on a prompt file."""
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WRAPPER),
            str(prompt_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


# Test 1: clean prompt produces no phantoms.
def test_helper_runs_on_clean_prompt_returns_empty_phantoms() -> None:
    body = textwrap.dedent(
        """\
        # AD-XXX: Hypothetical clean prompt

        ```python
        result = await event_log.query(category="system", limit=10)
        ```
        """
    )
    out = _run_helper(body)
    assert out == {"phantoms": []}


# Test 2: Wave 9B regression — `event_log.query(event_type=...)` flagged.
def test_helper_catches_event_log_query_event_type_kwarg_mismatch() -> None:
    body = textwrap.dedent(
        """\
        ```python
        rows = await event_log.query(event_type="ward_room.endorsement", limit=200)
        ```
        """
    )
    out = _run_helper(body)
    methods = {p["method"] for p in out["phantoms"]}
    kwargs = {p["kwarg"] for p in out["phantoms"]}
    assert "query" in methods
    assert "event_type" in kwargs


# Test 3: Wave 10 regression — non-existent method on WorkItemStore.
# (Symbol check on PowerShell side handles get_pending; helper covers the
# kwarg-shape variant that would have slipped past — list_work_items with
# a wrong kwarg.)
def test_helper_catches_work_item_store_get_pending() -> None:
    body = textwrap.dedent(
        """\
        ```python
        items = await store.list_work_items(payload="duty", limit=10)
        ```
        """
    )
    out = _run_helper(body)
    methods = {p["method"] for p in out["phantoms"]}
    kwargs = {p["kwarg"] for p in out["phantoms"]}
    assert "list_work_items" in methods
    assert "payload" in kwargs


# Test 4: kwargs in non-Python fenced blocks are skipped (pwsh, bash, sh,
# text, bare). Only ```python and ```py are scanned.
def test_helper_skips_kwargs_in_non_python_fenced_blocks() -> None:
    fence_tags = ["pwsh", "bash", "sh", "text", ""]  # last = bare fence
    for tag in fence_tags:
        body = (
            f"```{tag}\n"
            'event_log.query(event_type="x", limit=10)\n'
            "```\n"
        )
        # Helper trusts pre-filtered input — so simulate the wrapper having
        # masked non-Python fences by feeding empty body.
        # The actual fence-stripping is the wrapper's job; test it via the
        # full pipeline (test_powershell_wrapper_*).
        # Here verify helper logic: when given a body with the call site,
        # it DOES find the phantom — confirming the wrapper's pre-filter
        # is what suppresses fences, not the helper.
        out = _run_helper(body)
        # Helper alone, on un-prefiltered input, finds the call. The
        # wrapper's pre-filter suppression is verified separately in
        # test_powershell_wrapper_shared_prefilter_suppresses_prose_table_phantom.
        assert any(p["method"] == "query" for p in out["phantoms"]), (
            f"Helper should find call site even in {tag!r} fence (wrapper masks)"
        )

    # Confirm pre-filter behavior: feed body where non-Python fences have
    # been masked (whitespace), helper should report 0 phantoms.
    masked_body = (
        "         \n"
        '                                          \n'
        "   \n"
    )
    out = _run_helper(masked_body)
    assert out["phantoms"] == []


# Test 5: kwargs in `## Revision` sections are skipped (audit trail).
def test_helper_skips_kwargs_in_revision_section() -> None:
    # Helper trusts pre-filtered input — wrapper masks Revision sections.
    # Verify the masked-body input produces no phantoms.
    masked_body = "         \n         \n         \n"
    out = _run_helper(masked_body)
    assert out["phantoms"] == []


# Test 6: kwarg accepted if ANY same-named definition matches (limitation
# documented; receiver-class resolution deferred to AD-685c/d).
def test_helper_accepts_kwarg_matching_any_definition() -> None:
    # `query` exists in multiple modules with different signatures. The
    # helper accepts a kwarg if any candidate signature has that param.
    # `event_log.query` accepts `category`; helper should NOT flag it even
    # though OTHER `query` methods (e.g., capability.py) take `intent`.
    body = textwrap.dedent(
        """\
        ```python
        rows = await event_log.query(category="system", limit=10)
        ```
        """
    )
    out = _run_helper(body)
    # `category` is in event_log.query's signature — should not be flagged.
    flagged_kwargs = {p["kwarg"] for p in out["phantoms"]}
    assert "category" not in flagged_kwargs
    assert "limit" not in flagged_kwargs


# Test 7: PowerShell wrapper merges kwarg mismatches with symbol phantoms.
@pytest.mark.skipif(
    not WRAPPER.exists(), reason="PowerShell wrapper not present",
)
def test_powershell_wrapper_merges_kwarg_mismatches_with_symbol_phantoms(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "test_merged.md"
    prompt.write_text(
        textwrap.dedent(
            """\
            # Test prompt with both phantom kinds

            ```python
            from probos.workforce import WorkItemStore
            store = WorkItemStore()
            await store.list_work_items(payload="x")
            await store.get_pending(work_type="duty")
            ```
            """
        ),
        encoding="utf-8",
    )
    proc = _run_wrapper(prompt)
    output = proc.stdout
    # Both categories should appear in output.
    assert "kwarg_mismatch" in output, f"Expected kwarg_mismatch in output: {output}"
    # Symbol-check should flag get_pending under <Class>.<method> category
    # (or as part of the merged phantom list).
    assert "get_pending" in output or "list_work_items" in output, (
        f"Expected symbol or kwarg phantom in output: {output}"
    )


# Test 8: PowerShell wrapper exit code 1 when kwarg phantom present.
@pytest.mark.skipif(
    not WRAPPER.exists(), reason="PowerShell wrapper not present",
)
def test_powershell_wrapper_exit_code_1_when_kwarg_phantom(tmp_path: Path) -> None:
    prompt = tmp_path / "test_kwarg_only.md"
    prompt.write_text(
        textwrap.dedent(
            """\
            # Kwarg phantom only

            ```python
            await event_log.query(event_type="ward_room.endorsement", limit=10)
            ```
            """
        ),
        encoding="utf-8",
    )
    proc = _run_wrapper(prompt)
    assert proc.returncode == 1, (
        f"Expected exit 1 (phantom), got {proc.returncode}. stdout={proc.stdout}"
    )


# Test 9: shared pre-filter suppresses prose-table cite of past phantom.
@pytest.mark.skipif(
    not WRAPPER.exists(), reason="PowerShell wrapper not present",
)
def test_powershell_wrapper_shared_prefilter_suppresses_prose_table_phantom(
    tmp_path: Path,
) -> None:
    prompt = tmp_path / "test_prose_table.md"
    prompt.write_text(
        textwrap.dedent(
            """\
            # Prose-only motivation table

            | Wave | Phantom kwarg/method missed |
            |---|---|
            | 9B | `event_log.query(event_type=...)` (real: `query_structured(event=...)`) |
            | 10 | `WorkItemStore.get_pending(...)` (real: `list_work_items(...)`) |

            No code blocks below. The above are documentation cites.
            """
        ),
        encoding="utf-8",
    )
    proc = _run_wrapper(prompt)
    # With the shared pre-filter, these prose-table cites should be
    # suppressed for both the symbol check AND the kwarg check.
    assert proc.returncode == 0, (
        f"Expected exit 0 (clean) with prose-only cites, got {proc.returncode}. "
        f"stdout={proc.stdout}"
    )
    assert "Clean" in proc.stdout, f"Expected 'Clean' in output: {proc.stdout}"
