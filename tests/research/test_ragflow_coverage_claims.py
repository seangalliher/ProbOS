"""AD-714 / RAGFlow absorption — coverage-claim grep guard.

Section 3 of ``docs/research/ragflow-absorption.md`` claims ProbOS already
covers certain RAGFlow patterns. Each claim cites a ``path/file.py:NNN``
reference. This test extracts those citations and asserts the file exists
on disk so the absorption doc cannot silently drift as the codebase
evolves. Wave 5 standing convention #4 (no equivalence claim without a
grep-verified citation) hard rule.

This is a documentation-integrity guard, not a behavioral test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOC_PATH = Path(__file__).parent.parent.parent / "docs" / "research" / "ragflow-absorption.md"
REPO_ROOT = Path(__file__).parent.parent.parent

# Match `src/probos/.../file.py:NNN` patterns (the absorption doc's citation shape).
_CITATION_RE = re.compile(r"`(src/[A-Za-z0-9_./]+\.py):(\d+)`")


def _extract_citations() -> list[tuple[str, int]]:
    text = DOC_PATH.read_text(encoding="utf-8")
    return [(m.group(1), int(m.group(2))) for m in _CITATION_RE.finditer(text)]


def test_absorption_doc_exists() -> None:
    assert DOC_PATH.exists(), f"missing {DOC_PATH}"


def test_absorption_doc_has_required_sections() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")
    required = [
        "## 1. What It Does",
        "## 2. Architecture",
        "## 3. What ProbOS Has",
        "## 4. Absorption Candidates",
        "## 5. What We Reject",
        "## 6. Recommended Follow-ups",
    ]
    for header in required:
        assert header in text, f"missing required section: {header}"


def test_absorption_doc_states_artifact_choice() -> None:
    """R2: section 6 MUST state which artifact (a/b/c) was chosen."""
    text = DOC_PATH.read_text(encoding="utf-8")
    assert "Artifact chosen" in text, (
        "section 6 must state which (a)/(b)/(c) artifact was chosen"
    )


def test_every_citation_resolves_to_an_existing_file() -> None:
    citations = _extract_citations()
    assert citations, "absorption doc has no path/file.py:NNN citations to verify"
    for rel_path, line_no in citations:
        full = REPO_ROOT / rel_path
        assert full.exists(), f"citation target missing: {rel_path}"


def test_every_citation_line_is_within_file_bounds() -> None:
    citations = _extract_citations()
    for rel_path, line_no in citations:
        full = REPO_ROOT / rel_path
        try:
            n_lines = sum(1 for _ in full.open(encoding="utf-8"))
        except OSError as exc:
            pytest.fail(f"could not open {rel_path}: {exc}")
        assert line_no <= n_lines, (
            f"citation {rel_path}:{line_no} exceeds file length ({n_lines} lines)"
        )
