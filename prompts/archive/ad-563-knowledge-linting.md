# AD-563: Knowledge Linting — Inconsistency Detection, Coverage Gaps & Cross-Reference Suggestions

**Status:** Ready for builder
**Issue:** #34
**Dependencies:** AD-434 (RecordsStore), AD-555 (NotebookQualityEngine)
**Layer:** Knowledge (`src/probos/knowledge/`)

## Problem

Ship's Records notebook entries accumulate without structural or semantic quality
checks.  Factual disagreements within the knowledge base go undetected.  Coverage
gaps (topics with sparse analysis from a department) are invisible.  Entries on the
same topic from different agents are not cross-linked.

## Scope

- New file: `src/probos/knowledge/knowledge_linter.py`
- Modify: `src/probos/config.py` (add `LintConfig`, wire into `SystemConfig`)
- Modify: `src/probos/cognitive/dreaming.py` (Step 10 lint pass)
- Modify: `src/probos/types.py` (add lint fields to `DreamReport`)
- New test file: `tests/test_ad563_knowledge_linting.py`

## Do Not Build

- No LLM-based semantic inconsistency detection (keyword-based only).
- No auto-fix of inconsistencies (report only).
- No HXI lint dashboard.
- No cross-instance linting.

---

## Implementation

### 1. LintConfig in `src/probos/config.py`

Add after `RecordsConfig`:

```python
class LintConfig(BaseModel):
    """AD-563: Knowledge linting configuration."""

    enabled: bool = True
    min_coverage_per_department: int = 5
    inconsistency_keywords: dict[str, str] = Field(default_factory=lambda: {
        "increased": "decreased",
        "improved": "degraded",
        "rising": "falling",
        "positive": "negative",
        "success": "failure",
    })
```

The `inconsistency_keywords` field is a dict of contradicting term pairs.  Both
directions are checked (key vs value and value vs key).

Wire into `SystemConfig`:

```python
lint: LintConfig = LintConfig()  # AD-563
```

### 2. Data Models in `src/probos/knowledge/knowledge_linter.py`

New file.

```python
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

from probos.config import LintConfig

logger = logging.getLogger(__name__)
```

**`LintIssue` dataclass:**
```python
@dataclass
class LintIssue:
    severity: str  # "error", "warning", "info"
    category: str  # "inconsistency", "coverage_gap"
    description: str
    affected_paths: list[str] = field(default_factory=list)
```

**`LintSuggestion` dataclass:**
```python
@dataclass
class LintSuggestion:
    source_path: str
    target_path: str
    reason: str
```

**`LintReport` dataclass:**
```python
@dataclass
class LintReport:
    inconsistencies: list[LintIssue] = field(default_factory=list)
    coverage_gaps: list[LintIssue] = field(default_factory=list)
    cross_ref_suggestions: list[LintSuggestion] = field(default_factory=list)
    total_entries_scanned: int = 0
    lint_score: float = 1.0  # 1.0 = perfect, degrades with issues
```

### 3. KnowledgeLinter class

**Constructor:** `__init__(self, records_store: Any, config: LintConfig)`
- Store `self._records_store = records_store`
- Store `self._config = config`

**`async def lint_all(self) -> LintReport`:**
- If `config.enabled is False`, return empty `LintReport`.
- Get all notebook entries via `self._records_store.list_entries("notebooks")`.
  Wrap in try/except — return empty report on failure.
- Call each check method, combine results into `LintReport`.
- Compute `lint_score`:
  ```
  penalties = len(inconsistencies) * 0.1 + len(coverage_gaps) * 0.05
  lint_score = max(0.0, 1.0 - penalties)
  ```

**`def _check_inconsistencies(self, entries: list[dict]) -> list[LintIssue]`:**
- Group entries by topic (from frontmatter `topic` field).
- For each topic group with 2+ entries, scan content for contradicting keyword
  pairs from `config.inconsistency_keywords`.
- If entry A contains keyword "increased" and entry B (same topic) contains
  "decreased", emit a `LintIssue` with severity `"warning"`,
  category `"inconsistency"`, description explaining the contradiction,
  and `affected_paths` listing both entry paths.
- Content matching is case-insensitive, word-boundary aware (use `word in content.lower().split()`).

**`def _check_coverage_gaps(self, entries: list[dict]) -> list[LintIssue]`:**
- Group entries by department (from frontmatter `department` field).
- For each department with fewer entries than `config.min_coverage_per_department`,
  emit a `LintIssue` with severity `"info"`, category `"coverage_gap"`.
- Skip entries with no department (empty string).

**`def _suggest_cross_references(self, entries: list[dict]) -> list[LintSuggestion]`:**
- Group entries by topic.
- For each topic group with 2+ entries from different authors, suggest
  cross-references between each pair.
- `reason`: `"Same topic '{topic}' from different agents"`.
- Cap at 20 suggestions to avoid noise.

### 4. Dream Step 10 Integration — `src/probos/cognitive/dreaming.py`

After the existing Step 10 quality computation (and after any AD-444 confidence
cross-reference if present), add:

```python
# AD-563: Knowledge linting
lint_score = None
lint_issues_found = 0
if self._knowledge_linter:
    try:
        lint_report = await self._knowledge_linter.lint_all()
        lint_score = lint_report.lint_score
        lint_issues_found = (
            len(lint_report.inconsistencies)
            + len(lint_report.coverage_gaps)
        )
        if lint_issues_found > 0:
            logger.info(
                "AD-563 Step 10: Lint completed — score=%.3f, issues=%d "
                "(inconsistencies=%d, gaps=%d, xrefs=%d)",
                lint_report.lint_score,
                lint_issues_found,
                len(lint_report.inconsistencies),
                len(lint_report.coverage_gaps),
                len(lint_report.cross_ref_suggestions),
            )
    except Exception:
        logger.debug("AD-563 Step 10: Lint failed", exc_info=True)
```

Add `set_knowledge_linter()` late-bind method to `DreamingEngine`:

```python
def set_knowledge_linter(self, linter: Any) -> None:
    """AD-563: Late-bind knowledge linter."""
    self._knowledge_linter = linter
```

Initialize `self._knowledge_linter = None` in the constructor body (NOT as a
new constructor parameter — use the late-bind pattern).

### 5. DreamReport fields — `src/probos/types.py`

Add after the existing `notebook_quality_agents` field:

```python
# AD-563: Knowledge linting
lint_score: float | None = None
lint_issues_found: int = 0
```

Wire into `dream_cycle()` return at the bottom of the method where the
`DreamReport` is constructed.

### 6. Startup wiring — `src/probos/startup/dreaming.py`

After `NotebookQualityEngine` creation:

```python
# AD-563: Knowledge Linter
from probos.knowledge.knowledge_linter import KnowledgeLinter
knowledge_linter = None
if config.lint.enabled and records_store:
    knowledge_linter = KnowledgeLinter(
        records_store=records_store,
        config=config.lint,
    )
```

After dreaming engine creation, late-bind:

```python
if knowledge_linter:
    dreaming_engine.set_knowledge_linter(knowledge_linter)
```

---

## Tests

File: `tests/test_ad563_knowledge_linting.py`

12 tests:

| Test | Validates |
|------|-----------|
| `test_detect_inconsistency` | Two entries on same topic with contradicting keywords → `LintIssue` |
| `test_no_inconsistency` | Two entries on same topic without contradictions → no issue |
| `test_coverage_gap_detection` | Department with < 5 entries → coverage gap issue |
| `test_coverage_sufficient` | Department with >= 5 entries → no gap |
| `test_cross_reference_suggestion` | Two entries on same topic from different authors → suggestion |
| `test_lint_report_score` | Score degrades with issues (formula validation) |
| `test_severity_levels` | Inconsistencies are `"warning"`, gaps are `"info"` |
| `test_config_disabled` | `enabled=False` → empty report |
| `test_empty_records` | No entries → clean report, score 1.0 |
| `test_multiple_departments` | Entries spanning 3+ departments → correct per-dept gap check |
| `test_dream_integration` | DreamReport includes `lint_score` and `lint_issues_found` |
| `test_lint_all` | Full lint run across mixed entries → correct totals |

All tests use `_Fake*` stub for `RecordsStore`.  `_FakeRecordsStore.list_entries()`
returns canned entry dicts with frontmatter and content.  No LLM calls.

---

## Tracking

- `PROGRESS.md`: Add `AD-563  Knowledge Linting  CLOSED`
- `DECISIONS.md`: Add entry: "AD-563: Keyword-based knowledge linting during Dream Step 10. Detects inconsistencies (contradicting terms on same topic), coverage gaps (sparse departments), and cross-reference suggestions. No LLM — pure text matching."
- `docs/development/roadmap.md`: Update AD-563 row status to Complete.
- GitHub: Close issue #34.

## Acceptance Criteria

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
