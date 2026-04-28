"""AD-563: Knowledge linting for Ship's Records."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from probos.config import LintConfig

logger = logging.getLogger(__name__)


@dataclass
class LintIssue:
    """A knowledge lint issue detected in Ship's Records."""

    severity: str
    category: str
    description: str
    affected_paths: list[str] = field(default_factory=list)


@dataclass
class LintSuggestion:
    """A suggested cross-reference between notebook entries."""

    source_path: str
    target_path: str
    reason: str


@dataclass
class LintReport:
    """Aggregate knowledge linting results."""

    inconsistencies: list[LintIssue] = field(default_factory=list)
    coverage_gaps: list[LintIssue] = field(default_factory=list)
    cross_ref_suggestions: list[LintSuggestion] = field(default_factory=list)
    total_entries_scanned: int = 0
    lint_score: float = 1.0


class KnowledgeLinter:
    """Keyword-based linter for Ship's Records notebook entries."""

    def __init__(self, records_store: Any, config: LintConfig) -> None:
        self._records_store = records_store
        self._config = config

    async def lint_all(self) -> LintReport:
        """Run all knowledge lint checks over notebook entries."""
        if not self._config.enabled:
            return LintReport()

        try:
            entries = await self._records_store.list_entries("notebooks")
        except Exception:
            logger.debug("AD-563: Failed to list notebook entries for linting", exc_info=True)
            return LintReport()

        inconsistencies = self._check_inconsistencies(entries)
        coverage_gaps = self._check_coverage_gaps(entries)
        cross_ref_suggestions = self._suggest_cross_references(entries)
        penalties = len(inconsistencies) * 0.1 + len(coverage_gaps) * 0.05

        return LintReport(
            inconsistencies=inconsistencies,
            coverage_gaps=coverage_gaps,
            cross_ref_suggestions=cross_ref_suggestions,
            total_entries_scanned=len(entries),
            lint_score=max(0.0, 1.0 - penalties),
        )

    def _check_inconsistencies(self, entries: list[dict]) -> list[LintIssue]:
        """Detect contradictory keyword pairs on the same topic."""
        by_topic: dict[str, list[dict]] = {}
        for entry in entries:
            topic = self._frontmatter(entry).get("topic", "")
            if topic:
                by_topic.setdefault(topic, []).append(entry)

        issues: list[LintIssue] = []
        for topic, topic_entries in by_topic.items():
            if len(topic_entries) < 2:
                continue
            for index, left in enumerate(topic_entries):
                left_content = str(left.get("content", "")).lower()
                for right in topic_entries[index + 1:]:
                    right_content = str(right.get("content", "")).lower()
                    issue = self._detect_pair_inconsistency(
                        topic,
                        left,
                        left_content,
                        right,
                        right_content,
                    )
                    if issue:
                        issues.append(issue)
        return issues

    def _check_coverage_gaps(self, entries: list[dict]) -> list[LintIssue]:
        """Detect departments below the configured minimum notebook coverage."""
        by_department: dict[str, list[dict]] = {}
        for entry in entries:
            department = self._frontmatter(entry).get("department", "")
            if department:
                by_department.setdefault(department, []).append(entry)

        issues: list[LintIssue] = []
        for department, department_entries in by_department.items():
            count = len(department_entries)
            if count < self._config.min_coverage_per_department:
                issues.append(LintIssue(
                    severity="info",
                    category="coverage_gap",
                    description=(
                        f"Department '{department}' has {count} notebook entries; "
                        f"minimum is {self._config.min_coverage_per_department}"
                    ),
                    affected_paths=[str(entry.get("path", "")) for entry in department_entries],
                ))
        return issues

    def _suggest_cross_references(self, entries: list[dict]) -> list[LintSuggestion]:
        """Suggest cross-references between same-topic entries from different authors."""
        by_topic: dict[str, list[dict]] = {}
        for entry in entries:
            topic = self._frontmatter(entry).get("topic", "")
            if topic:
                by_topic.setdefault(topic, []).append(entry)

        suggestions: list[LintSuggestion] = []
        for topic, topic_entries in by_topic.items():
            if len(topic_entries) < 2:
                continue
            for index, left in enumerate(topic_entries):
                left_author = self._frontmatter(left).get("author", "")
                for right in topic_entries[index + 1:]:
                    right_author = self._frontmatter(right).get("author", "")
                    if left_author == right_author:
                        continue
                    suggestions.append(LintSuggestion(
                        source_path=str(left.get("path", "")),
                        target_path=str(right.get("path", "")),
                        reason=f"Same topic '{topic}' from different agents",
                    ))
                    if len(suggestions) >= 20:
                        return suggestions
        return suggestions

    def _detect_pair_inconsistency(
        self,
        topic: str,
        left: dict,
        left_content: str,
        right: dict,
        right_content: str,
    ) -> LintIssue | None:
        for keyword, opposite in self._config.inconsistency_keywords.items():
            left_has_keyword = self._contains_word(left_content, keyword)
            left_has_opposite = self._contains_word(left_content, opposite)
            right_has_keyword = self._contains_word(right_content, keyword)
            right_has_opposite = self._contains_word(right_content, opposite)
            if (left_has_keyword and right_has_opposite) or (left_has_opposite and right_has_keyword):
                return LintIssue(
                    severity="warning",
                    category="inconsistency",
                    description=(
                        f"Topic '{topic}' has contradictory terms "
                        f"'{keyword}' and '{opposite}'"
                    ),
                    affected_paths=[str(left.get("path", "")), str(right.get("path", ""))],
                )
        return None

    def _contains_word(self, content: str, word: str) -> bool:
        return re.search(rf"\b{re.escape(word.lower())}\b", content) is not None

    def _frontmatter(self, entry: dict) -> dict[str, Any]:
        frontmatter = entry.get("frontmatter", {})
        if isinstance(frontmatter, dict):
            return frontmatter
        return {}