"""AD-563: Knowledge linting tests."""

from __future__ import annotations

import pytest

from probos.config import LintConfig
from probos.knowledge.knowledge_linter import KnowledgeLinter
from probos.types import DreamReport


class _FakeRecordsStore:
    def __init__(self, entries: list[dict]) -> None:
        self._entries = entries

    async def list_entries(self, prefix: str) -> list[dict]:
        assert prefix == "notebooks"
        return self._entries


def _entry(
    path: str,
    *,
    topic: str = "trust",
    author: str = "Chapel",
    department: str = "Medical",
    content: str = "Systems stable.",
) -> dict:
    return {
        "path": path,
        "frontmatter": {
            "topic": topic,
            "author": author,
            "department": department,
        },
        "content": content,
    }


@pytest.mark.asyncio
async def test_detect_inconsistency() -> None:
    linter = KnowledgeLinter(
        _FakeRecordsStore([
            _entry("notebooks/a.md", content="Trust increased after intervention."),
            _entry("notebooks/b.md", author="Dax", content="Trust decreased after intervention."),
        ]),
        LintConfig(min_coverage_per_department=0),
    )

    report = await linter.lint_all()

    assert len(report.inconsistencies) == 1
    issue = report.inconsistencies[0]
    assert issue.category == "inconsistency"
    assert issue.affected_paths == ["notebooks/a.md", "notebooks/b.md"]


@pytest.mark.asyncio
async def test_no_inconsistency() -> None:
    linter = KnowledgeLinter(
        _FakeRecordsStore([
            _entry("notebooks/a.md", content="Trust increased after intervention."),
            _entry("notebooks/b.md", author="Dax", content="Trust remained stable."),
        ]),
        LintConfig(min_coverage_per_department=0),
    )

    report = await linter.lint_all()

    assert report.inconsistencies == []


@pytest.mark.asyncio
async def test_coverage_gap_detection() -> None:
    linter = KnowledgeLinter(
        _FakeRecordsStore([
            _entry("notebooks/a.md", department="Engineering"),
            _entry("notebooks/b.md", department="Engineering"),
        ]),
        LintConfig(min_coverage_per_department=5),
    )

    report = await linter.lint_all()

    assert len(report.coverage_gaps) == 1
    assert report.coverage_gaps[0].category == "coverage_gap"


@pytest.mark.asyncio
async def test_coverage_sufficient() -> None:
    entries = [
        _entry(f"notebooks/{index}.md", topic=f"topic-{index}", department="Science")
        for index in range(5)
    ]
    linter = KnowledgeLinter(_FakeRecordsStore(entries), LintConfig(min_coverage_per_department=5))

    report = await linter.lint_all()

    assert report.coverage_gaps == []


@pytest.mark.asyncio
async def test_cross_reference_suggestion() -> None:
    linter = KnowledgeLinter(
        _FakeRecordsStore([
            _entry("notebooks/a.md", author="Chapel"),
            _entry("notebooks/b.md", author="Dax"),
        ]),
        LintConfig(min_coverage_per_department=0),
    )

    report = await linter.lint_all()

    assert len(report.cross_ref_suggestions) == 1
    suggestion = report.cross_ref_suggestions[0]
    assert suggestion.source_path == "notebooks/a.md"
    assert suggestion.target_path == "notebooks/b.md"
    assert suggestion.reason == "Same topic 'trust' from different agents"


@pytest.mark.asyncio
async def test_lint_report_score() -> None:
    linter = KnowledgeLinter(
        _FakeRecordsStore([
            _entry("notebooks/a.md", content="Signal quality improved."),
            _entry("notebooks/b.md", author="Dax", content="Signal quality degraded."),
        ]),
        LintConfig(min_coverage_per_department=5),
    )

    report = await linter.lint_all()

    assert len(report.inconsistencies) == 1
    assert len(report.coverage_gaps) == 1
    assert report.lint_score == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_severity_levels() -> None:
    linter = KnowledgeLinter(
        _FakeRecordsStore([
            _entry("notebooks/a.md", content="Outcome was success."),
            _entry("notebooks/b.md", author="Dax", content="Outcome was failure."),
        ]),
        LintConfig(min_coverage_per_department=5),
    )

    report = await linter.lint_all()

    assert report.inconsistencies[0].severity == "warning"
    assert report.coverage_gaps[0].severity == "info"


@pytest.mark.asyncio
async def test_config_disabled() -> None:
    linter = KnowledgeLinter(
        _FakeRecordsStore([
            _entry("notebooks/a.md", content="Trust increased."),
            _entry("notebooks/b.md", author="Dax", content="Trust decreased."),
        ]),
        LintConfig(enabled=False),
    )

    report = await linter.lint_all()

    assert report.total_entries_scanned == 0
    assert report.lint_score == 1.0
    assert report.inconsistencies == []
    assert report.coverage_gaps == []
    assert report.cross_ref_suggestions == []


@pytest.mark.asyncio
async def test_empty_records() -> None:
    linter = KnowledgeLinter(_FakeRecordsStore([]), LintConfig())

    report = await linter.lint_all()

    assert report.total_entries_scanned == 0
    assert report.lint_score == 1.0
    assert report.inconsistencies == []
    assert report.coverage_gaps == []


@pytest.mark.asyncio
async def test_multiple_departments() -> None:
    entries = [
        _entry("notebooks/medical-1.md", department="Medical"),
        _entry("notebooks/medical-2.md", department="Medical"),
        _entry("notebooks/engineering-1.md", department="Engineering"),
    ]
    entries.extend(
        _entry(f"notebooks/science-{index}.md", topic=f"science-{index}", department="Science")
        for index in range(3)
    )
    linter = KnowledgeLinter(_FakeRecordsStore(entries), LintConfig(min_coverage_per_department=3))

    report = await linter.lint_all()

    gap_departments = {issue.description.split("'")[1] for issue in report.coverage_gaps}
    assert gap_departments == {"Medical", "Engineering"}


def test_dream_integration() -> None:
    report = DreamReport(lint_score=0.85, lint_issues_found=2)

    assert report.lint_score == 0.85
    assert report.lint_issues_found == 2


@pytest.mark.asyncio
async def test_lint_all() -> None:
    entries = [
        _entry("notebooks/medical-a.md", content="Trust is rising."),
        _entry("notebooks/medical-b.md", author="Dax", content="Trust is falling."),
    ]
    entries.extend(
        _entry(
            f"notebooks/science-{index}.md",
            topic=f"science-{index}",
            author="Spock",
            department="Science",
        )
        for index in range(5)
    )
    linter = KnowledgeLinter(_FakeRecordsStore(entries), LintConfig(min_coverage_per_department=5))

    report = await linter.lint_all()

    assert report.total_entries_scanned == 7
    assert len(report.inconsistencies) == 1
    assert len(report.coverage_gaps) == 1
    assert len(report.cross_ref_suggestions) == 1
    assert report.lint_score == pytest.approx(0.85)