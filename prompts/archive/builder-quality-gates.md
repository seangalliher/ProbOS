# Builder Quality Gates, Standing Orders & Code Review Agent — AD-338 through AD-341

**Current highest AD: AD-337 (Implement /ping Command)**

This prompt addresses three systemic failures discovered during the Builder's first end-to-end test (AD-337), introduces ProbOS's Standing Orders architecture (the agent instructions system), and adds a Code Review Agent as a pipeline quality gate.

## Problem Statement

The Builder generated and committed code with failing tests. Four root causes:

1. **No commit gate on test passage** — `execute_approved_build()` commits regardless of whether tests pass. `result.success` is based on syntax validation only.
2. **Test-fix loop disabled** — `api.py._execute_build()` calls `execute_approved_build()` without passing `llm_client`, so the 2-retry fix loop is a no-op.
3. **Minimal test-writing guidance** — The Builder's `instructions` string has only "Generate test code for the test files specified" and "Every public function/method needs a test." No guidance on constructor signatures, mock setup, import conventions, or assertion patterns.
4. **"Files: 0" reporting bug** — `_execute_build()` reports `len(result.files_written)` but MODIFY-only builds populate `result.files_modified` instead, so the UI always shows 0 for modification builds.
5. **No standalone standards enforcement** — ProbOS relies on `.github/copilot-instructions.md` (an IDE artifact) for coding standards but has no internal standards system. ProbOS must operate standalone without assuming any specific IDE.

### The Deeper Issue: ProbOS Needs Its Own Constitution

Claude Code enforces standards via `CLAUDE.md`. OpenClaw has `soul.md`. ProbOS currently has extensive engineering knowledge embedded in an IDE config file (`.github/copilot-instructions.md`) and hardcoded Python string literals (`class.instructions`). Neither is standalone, evolvable, or hierarchical.

ProbOS needs **Standing Orders** — its own layered instructions architecture that:
- Operates standalone (no IDE dependency)
- Composes hierarchically (Federation → Ship → Department → Agent)
- Evolves as agents learn (corrections → instruction updates via self-mod pipeline)
- Adapts per Ship Class (warship vs science vessel vs cargo)

---

## AD-338: Builder Commit Gate & Fix Loop (Pipeline Safety)

**File:** `src/probos/cognitive/builder.py`
**Also:** `src/probos/api.py`
**Test file:** `tests/test_builder_agent.py`

### Step 1: Gate commits on test passage

In `execute_approved_build()`, after the test-fix loop (around line 2197), add a test-passage check before committing:

```python
# 6. Commit — only if tests passed OR tests were not run
if written or modified_files:
    if run_tests and not result.tests_passed:
        result.error = (
            "Tests failed after " + str(result.fix_attempts) + " fix attempt(s). "
            "Code written to branch but NOT committed.\n"
            + (result.test_result or "")[-1000:]
        )
        result.success = False
    else:
        # ... existing commit logic ...
```

Acceptance criteria:
- When tests fail: files are written to disk (for debugging) but NOT committed
- `result.success = False` when tests fail
- `result.error` contains the test failure output (last 1000 chars)
- When tests pass: commit proceeds as before
- When `run_tests=False`: commit proceeds as before (no regression)

### Step 2: Pass `llm_client` from API to enable test-fix loop

In `src/probos/api.py`, `_execute_build()` function (around line 867):

```python
from probos.cognitive.llm_client import LLMClient

# Inside _execute_build:
llm = LLMClient(rt._config.llm)

result = await execute_approved_build(
    file_changes=file_changes,
    spec=spec,
    work_dir=work_dir,
    run_tests=True,
    llm_client=llm,  # Enable test-fix loop
)
```

Acceptance criteria:
- `llm_client` is passed to `execute_approved_build()`
- On test failure, the Builder gets up to 2 LLM-powered fix attempts before giving up
- The fix loop uses the deep tier for quality fixes

### Step 3: Fix "Files: 0" reporting bug

In `src/probos/api.py`, `_execute_build()` (around line 885), change:

```python
# BEFORE (bug — only counts created files, not modified):
f"Files: {len(result.files_written)}, "

# AFTER:
f"Files: {len(result.files_written) + len(result.files_modified)}, "
```

Also update the `files_written` field in the event payload to include both:

```python
"files_written": result.files_written + result.files_modified,
```

### Step 4: Tests

Add to `tests/test_builder_agent.py`:

1. `test_execute_build_gates_commit_on_test_failure` — Tests fail → verify no commit was made, `result.success is False`, `result.error` contains test output
2. `test_execute_build_commits_on_test_pass` — Tests pass → verify commit was made, `result.success is True`
3. `test_execute_build_commits_when_tests_disabled` — `run_tests=False` → verify commit proceeds regardless
4. `test_execute_build_fix_loop_with_llm_client` — Mock `llm_client`, make first test run fail and second pass → verify 1 fix attempt, commit made

**Do not change:** Any existing test behavior. The existing tests that check `result.success` with syntax errors should still work — syntax errors should still set `result.success = False`.

---

## AD-339: Standing Orders Architecture (ProbOS Instructions System)

**New file:** `src/probos/cognitive/standing_orders.py`
**New directory:** `config/standing_orders/`
**New files in directory:** `federation.md`, `ship.md`, `engineering.md`, `science.md`, `medical.md`, `security.md`, `bridge.md`
**Test file:** `tests/test_standing_orders.py`
**Also modify:** `src/probos/cognitive/cognitive_agent.py`

### Concept: The Four Tiers of Standing Orders

In Star Trek, orders flow through a clear hierarchy: Federation law → Starfleet regulations → ship standing orders → department protocols → individual duty assignments. ProbOS adopts this same pattern for agent instructions.

```
┌─────────────────────────────────────────────┐
│  Federation Constitution (federation.md)     │  Universal, immutable principles
│  "The laws of physics" — never overridden    │  across ALL ProbOS instances
├─────────────────────────────────────────────┤
│  Ship Standing Orders (ship.md)              │  This ProbOS instance's config
│  Per-instance customization by the Captain   │  (project-specific conventions)
├─────────────────────────────────────────────┤
│  Department Protocols (engineering.md, etc.)  │  Department-level standards
│  Shared by all agents in a department        │  (test patterns, review rules)
├─────────────────────────────────────────────┤
│  Agent Standing Orders (builder.md, etc.)     │  Individual agent learned practices
│  Evolve through corrections + dreaming       │  (specific to one agent's role)
├─────────────────────────────────────────────┤
│  Hardcoded instructions (class attribute)    │  Agent's core identity — immutable
│  "Starfleet Academy training"                │  (defines WHAT the agent IS)
└─────────────────────────────────────────────┘
```

**Composition rule**: At runtime, an agent's effective system prompt is assembled bottom-up:

```
effective_instructions = (
    class.instructions           # Hardcoded identity (always present)
    + "\n\n" + federation.md     # Universal principles
    + "\n\n" + ship.md           # This ship's customs
    + "\n\n" + department.md     # Department standards (if agent belongs to one)
    + "\n\n" + agent.md          # Agent's personal learned rules (if exists)
)
```

**Two layers, distinct roles:**

| Layer | Source | Nature | Analogy |
|---|---|---|---|
| `class.instructions` | Hardcoded Python string | Agent's **identity** — what it fundamentally is | Starfleet Academy training |
| Standing Orders files | `config/standing_orders/*.md` | Agent's **standards** — learned, evolvable | Standing orders, SOPs |

The hardcoded `instructions` define the agent's core behavior and output format. Standing Orders add quality standards, coding conventions, and learned best practices on top.

### Step 1: Create the StandingOrders loader

Create `src/probos/cognitive/standing_orders.py`:

```python
"""Standing Orders — ProbOS agent instruction system.

Loads hierarchical instruction files that compose with each agent's
hardcoded instructions to form the complete system prompt.

Hierarchy (highest to lowest precedence for conflict resolution):
    federation.md  — Universal principles (immutable across all instances)
    ship.md        — This ProbOS instance's configuration
    {department}.md — Department-level protocols (engineering, medical, etc.)
    {agent}.md     — Individual agent learned practices (evolvable)
"""

from __future__ import annotations

import logging
from pathlib import Path
from functools import lru_cache

logger = logging.getLogger(__name__)

# Default location for standing orders
_DEFAULT_ORDERS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "standing_orders"

# Department mapping: agent_type -> department name
_AGENT_DEPARTMENTS: dict[str, str] = {
    # Engineering
    "builder": "engineering",
    "code_reviewer": "engineering",
    # Science
    "architect": "science",
    "emergent_detector": "science",
    "codebase_index": "science",
    # Medical
    "diagnostician": "medical",
    "vitals_monitor": "medical",
    "surgeon": "medical",
    "pharmacist": "medical",
    "pathologist": "medical",
    # Security
    "red_team": "security",
    "system_qa": "security",
    # Bridge
    "counselor": "bridge",
}


def get_department(agent_type: str) -> str | None:
    """Return the department name for an agent type, or None if unassigned."""
    return _AGENT_DEPARTMENTS.get(agent_type)


def register_department(agent_type: str, department: str) -> None:
    """Register an agent type's department assignment.

    Used by dynamically designed agents to declare their department.
    """
    _AGENT_DEPARTMENTS[agent_type] = department


@lru_cache(maxsize=32)
def _load_file(path: Path) -> str:
    """Load a standing orders file, returning empty string if not found."""
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8").strip()
            logger.debug("StandingOrders: loaded %s (%d chars)", path.name, len(text))
            return text
        except Exception as exc:
            logger.warning("StandingOrders: failed to read %s: %s", path, exc)
    return ""


def clear_cache() -> None:
    """Clear the file cache (call after standing orders are updated)."""
    _load_file.cache_clear()


def compose_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
) -> str:
    """Compose an agent's complete instructions from all tiers.

    Args:
        agent_type: The agent's type identifier (e.g., "builder", "architect").
        hardcoded_instructions: The agent's class-level instructions string.
        orders_dir: Override path to standing orders directory. Defaults
            to ``config/standing_orders/`` relative to the project root.
        department: Override department name. If None, looks up from
            ``_AGENT_DEPARTMENTS`` mapping.

    Returns:
        The composed instructions string with all applicable tiers.
    """
    d = orders_dir or _DEFAULT_ORDERS_DIR

    parts: list[str] = []

    # 1. Hardcoded identity (always first — defines what the agent IS)
    if hardcoded_instructions:
        parts.append(hardcoded_instructions.strip())

    # 2. Federation Constitution (universal principles)
    fed = _load_file(d / "federation.md")
    if fed:
        parts.append(f"## Federation Constitution\n\n{fed}")

    # 3. Ship Standing Orders (this instance's config)
    ship = _load_file(d / "ship.md")
    if ship:
        parts.append(f"## Ship Standing Orders\n\n{ship}")

    # 4. Department Protocols (if agent belongs to a department)
    dept = department or get_department(agent_type)
    if dept:
        dept_text = _load_file(d / f"{dept}.md")
        if dept_text:
            parts.append(f"## {dept.title()} Department Protocols\n\n{dept_text}")

    # 5. Agent Standing Orders (individual learned practices)
    agent_text = _load_file(d / f"{agent_type}.md")
    if agent_text:
        parts.append(f"## Personal Standing Orders\n\n{agent_text}")

    return "\n\n---\n\n".join(parts)
```

### Step 2: Integrate into CognitiveAgent

In `src/probos/cognitive/cognitive_agent.py`, modify the `decide()` method to compose standing orders with the hardcoded instructions. The composition happens at call time, not at `__init__` time, so standing orders updates take effect immediately.

Find the `decide()` method (around line 100-115). Change:

```python
# BEFORE:
request = LLMRequest(
    prompt=user_message,
    system_prompt=self.instructions,
    tier=self._resolve_tier(),
)

# AFTER:
from probos.cognitive.standing_orders import compose_instructions

composed = compose_instructions(
    agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
    hardcoded_instructions=self.instructions or "",
)

request = LLMRequest(
    prompt=user_message,
    system_prompt=composed,
    tier=self._resolve_tier(),
)
```

**Important**: This change ONLY affects `decide()`. The Builder's sub-calls (chunk decomposition, chunk execution, localization) use separate ad-hoc `system_prompt` strings — leave those unchanged. They are task-specific prompts, not agent identity prompts.

### Step 3: Seed the Standing Orders files

Create `config/standing_orders/` directory with these initial files, seeded from the knowledge in `.github/copilot-instructions.md`. This is a one-time extraction — after this, ProbOS owns its own standards.

**`config/standing_orders/federation.md`** — Universal principles that apply across ALL ProbOS instances. These are the "laws of physics" — never overridden by lower tiers.

```markdown
# Federation Constitution

These principles apply to all agents across all ProbOS instances.
They cannot be overridden by ship, department, or agent standing orders.

## Core Directives

1. **Safety Budget**: Risk-proportional consensus. Destructive operations require multi-agent quorum. The higher the risk, the more agents must agree.
2. **Reversibility Preference**: When multiple approaches exist, prefer the reversible one. Reversible actions need less consensus than irreversible ones.
3. **Minimal Authority**: Agents operate with the minimum capabilities needed for their current task. Trust is earned, not assumed.
4. **Instructions-First Design**: CognitiveAgent behavior is defined by instructions (system prompt), not hardcoded logic in decide(). The LLM reasons; the code orchestrates.
5. **Episodic Completeness**: Every execution path stores an episode. If it doesn't, the learning loop breaks.
6. **Trust Integrity**: Trust stores raw Beta(alpha, beta) parameters, never derived means. Derived scores lose distribution information.

## Layer Architecture (Inviolable)

```
Experience → Cognitive → Consensus → Mesh → Substrate
```

Lower layers must NEVER import from higher layers. This is a hard architectural constraint.

## Encoding Safety

No emoji or non-ASCII characters in code strings, log messages, or test output.
They cause encoding crashes on Windows terminals (cp1252). Use ASCII alternatives.

## Agent Classification

- **Core**: Deterministic tool agents. Domain-agnostic. Always available.
- **Utility**: System maintenance. Operate on the system, not for the user.
- **Domain**: User-facing cognitive work. Self-designed agents land here.
```

**`config/standing_orders/ship.md`** — This ProbOS instance's local conventions. The Captain can customize this per project.

```markdown
# Ship Standing Orders

These orders apply to all agents aboard this ProbOS instance.

## Import Conventions

- All imports use full module paths: `from probos.experience.shell import ProbOSShell`
- Never use relative-looking paths: `from experience.shell import ...`
- Cross-cutting imports go through `probos.runtime` or `probos.types`

## Testing Standards

- Tests use pytest + pytest-asyncio
- Prefer `_Fake*` stub classes over complex Mock() chains
- Test files mirror source paths
- Every public function/method needs a test
- Run tests with: `pytest tests/ -x -q`
- UI changes require Vitest component tests
- API endpoints need at least 2 tests (happy path + error)

## Code Patterns

- Use `from __future__ import annotations` in all modules
- Use `asyncio.get_running_loop()`, never `get_event_loop()`
- Follow existing patterns — check how similar things are done before inventing
- New destructive intents must set `requires_consensus=True`
- HTTP in designed agents must use mesh-fetch pattern, not raw httpx
- Restored designed agent code must pass CodeValidator before importlib loading

## Scope Discipline

- Do NOT expand scope beyond what was asked
- Do NOT add features, refactor adjacent code, or "improve" things not in the spec
- Do NOT add emoji to UI — use stroke-based SVG icons (HXI Design Principle #3)
```

**`config/standing_orders/engineering.md`** — Engineering department protocols. Shared by Builder, Code Reviewer, and future engineering agents.

```markdown
# Engineering Department Protocols

Standards for all agents in the Engineering department (Builder, Code Reviewer, etc.).

## Build Pipeline Standards

- Builder output uses `===FILE: path===` for new files and `===MODIFY: path===` with SEARCH/REPLACE blocks for modifications
- SEARCH blocks must match existing code EXACTLY — character-for-character
- Keep SEARCH blocks small — just enough context to be unique
- Order SEARCH/REPLACE pairs top-to-bottom in the file
- Test-gate: run the full test suite after each logical build step. Do not proceed if tests fail.

## Test Writing Rules

- Before writing test fixtures, READ the target class __init__ signature. Only pass arguments __init__ accepts. Do NOT invent keyword arguments.
- Every mock must cover ALL attributes accessed in the code path under test. Trace the method body to find every self.runtime.*, self.console.*, etc. access.
- Test assertions must match the ACTUAL output format of the code being tested, not a guessed format. If you wrote `console.print(f"Uptime: {x}")`, the test must assert that exact string.
- Use `pytest.mark.asyncio` and `async def test_*` for async methods.
- Test validation: the pipeline runs pytest after generating code. Tests must pass for the commit to proceed.

## Code Review Checklist

1. Import correctness — full `probos.*` paths, no layer violations
2. Constructor contracts — only pass args the __init__ accepts
3. Mock completeness — every accessed attribute has a mock
4. Assertion accuracy — assertions match actual output
5. Pattern adherence — follows existing codebase patterns
6. Scope discipline — no unrequested changes
7. Consensus gates — destructive intents gated
8. Agent contracts — instructions-first, not hardcoded decide()
```

**`config/standing_orders/science.md`** — Science department protocols.

```markdown
# Science Department Protocols

Standards for all agents in the Science department (Architect, EmergentDetector, CodebaseIndex).

## Architecture Review

- Every design proposal must reference specific files, line numbers, and existing patterns
- Enhancement proposals for partially-existing features must produce FULL proposals, not punt
- Never reference an unverified method or attribute in a design proposal
- Verify API surfaces against CodebaseIndex before proposing integrations

## Context Budget Awareness

- Source budget: 2000 lines total across selected files
- Per-file cap: 300 lines (truncate with note)
- Import expansion: up to 12 files (8 LLM-selected + 4 import-traced)
- Total context target: ~60K-100K chars — exceeding this will timeout through the proxy
```

**`config/standing_orders/medical.md`** — Medical department protocols.

```markdown
# Medical Department Protocols

Standards for all agents in Medical (Diagnostician, VitalsMonitor, Surgeon, Pharmacist, Pathologist).

## Diagnostic Standards

- Always read system state from sensors (CodebaseIndex, runtime status), never fabricate
- Diagnostics must be evidence-based — cite specific metrics, logs, or state
- Triage: classify issues by severity before recommending treatment
- Surgeon operates on code ONLY with explicit Captain approval
```

**`config/standing_orders/security.md`** — Security department protocols.

```markdown
# Security Department Protocols

Standards for all agents in Security (RedTeam, SystemQA, future security agents).

## Verification Standards

- Independent verification: never trust the agent being reviewed to self-report
- RedTeam reviews are adversarial by design — find what others miss
- Self-mod validation chain must be preserved: static analysis -> sandbox test -> probationary trust -> QA smoke tests -> behavioral monitoring
- On warm boot: CodeValidator MUST validate restored agent code before importlib loading
```

**`config/standing_orders/bridge.md`** — Bridge crew protocols.

```markdown
# Bridge Department Protocols

Standards for Bridge officers (First Officer/Architect, Ship's Counselor, future bridge agents).

## Ship's Computer Identity

The runtime's conversational voice is the Ship's Computer — LCARS-era, TNG/Voyager.
Calm, precise, authoritative, never fabricates. Reports from sensors, not imagination.
"Unable to comply" over hallucination. "Specify parameters" over guessing.

## Command Protocol

- Bridge officers have ship-wide cross-department authority
- Captain (Human) decisions are final — always defer to Captain approval gates
- Chain of command: Captain → First Officer → Department Chiefs → Crew
```

### Step 4: Tests

Create `tests/test_standing_orders.py`:

1. `test_compose_with_all_tiers` — Create temp dir with federation.md, ship.md, engineering.md, builder.md. Call `compose_instructions("builder", "I am the Builder.")`. Verify output contains all five sections in order.
2. `test_compose_without_department` — Agent type not in department map → verify federation + ship included, no department section.
3. `test_compose_with_unknown_agent` — No agent-specific .md file exists → verify no "Personal Standing Orders" section, but federation + ship still included.
4. `test_compose_empty_directory` — Empty orders dir → returns just the hardcoded instructions.
5. `test_compose_missing_directory` — Non-existent orders dir → returns just the hardcoded instructions (graceful degradation).
6. `test_department_lookup` — Verify `get_department("builder")` returns `"engineering"`, `get_department("architect")` returns `"science"`, unknown returns `None`.
7. `test_register_department` — Call `register_department("new_agent", "engineering")`, verify lookup works.
8. `test_cache_clear` — Modify a file, call `clear_cache()`, verify new content is loaded.
9. `test_compose_preserves_hardcoded_first` — Hardcoded instructions always appear before standing orders in the output.
10. `test_compose_with_override_department` — Pass `department="medical"` for a builder agent → verify medical protocols loaded instead of engineering.

### Step 5: Integration verification

After wiring into `cognitive_agent.py`, verify that existing tests still pass. The composition should be transparent — agents that have no standing orders files get their existing behavior (hardcoded instructions only). Agents that DO have standing orders get the enriched prompt.

**Key invariant**: If `config/standing_orders/` is empty or missing, every agent behaves exactly as before. Standing orders are additive, never subtractive.

---

## AD-340: Enhanced Builder Instructions (Test Quality)

**File:** `src/probos/cognitive/builder.py`
**Test file:** `tests/test_builder_agent.py`

### Step 1: Enhance the hardcoded `instructions` class attribute

Keep all existing rules in `BuilderAgent.instructions` (lines 1457-1499) and ADD these test-writing rules after "Every public function/method needs a test":

```
TEST WRITING RULES:
- Before writing test fixtures, READ the class __init__ signature in the reference code. Only pass arguments that __init__ accepts. Do not invent keyword arguments.
- Import paths must use the full module path: `from probos.experience.shell import ProbOSShell`, never `from experience.shell import ...`
- Use `_Fake*` stub classes (like _FakeRuntime, _FakeAgent) over complex Mock() chains. Check existing test files for patterns.
- For async methods, use `pytest.mark.asyncio` and `async def test_*`.
- Every mock must cover ALL attributes accessed in the code path under test. Trace the target method body to find every self.x access.
- Test assertions must match the ACTUAL output format of the code you just wrote, not a guessed format.
- Do NOT use emoji in code strings — they cause encoding crashes on Windows.
```

**Note**: Some of these rules overlap with `engineering.md` standing orders. That's intentional — the hardcoded instructions are the minimum viable safety net. Standing orders add depth and context. Redundancy at the safety layer is a feature, not a bug.

### Step 2: Tests

Add to `tests/test_builder_agent.py`:

1. `test_instructions_contain_test_rules` — Verify `BuilderAgent.instructions` contains key phrases: `"__init__ signature"`, `"from probos."`, `"_Fake"`, `"pytest.mark.asyncio"`

**Do not change:** The existing `instructions` text for non-test rules (output format, MODIFY blocks, etc.)

---

## AD-341: Code Review Agent (Quality Gate)

**New file:** `src/probos/cognitive/code_reviewer.py`
**New test file:** `tests/test_code_reviewer.py`
**Also modify:** `src/probos/cognitive/builder.py` (integration)

### Concept

The Code Review Agent reviews Builder output against ProbOS engineering standards before the commit gate. It operates in the Engineering department and reads its standards from ProbOS's own Standing Orders — not from any IDE config file.

### Step 1: Create CodeReviewAgent

```python
"""Code Review Agent — reviews Builder output against ProbOS standards."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import LLMClient, LLMRequest
from probos.cognitive.standing_orders import compose_instructions

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result of a code review."""
    approved: bool = False
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    summary: str = ""


class CodeReviewAgent(CognitiveAgent):
    """Reviews code changes against ProbOS engineering standards.

    Reads standards from Standing Orders (federation.md + ship.md + engineering.md
    + code_reviewer.md). Operates standalone — no IDE dependency.

    Pipeline position:
    Builder generates code → CodeReviewer reviews → tests run → commit (if all pass).
    """

    agent_type = "code_reviewer"
    tier = "utility"

    instructions = """You are the Code Review Agent for ProbOS. You review code changes
produced by the Builder Agent before they are committed.

You receive the project's engineering standards via Standing Orders. Review
all code changes against those standards.

OUTPUT FORMAT:
Return a JSON object:
{
  "approved": true/false,
  "issues": ["Critical issue 1 — file:line — description"],
  "suggestions": ["Non-blocking suggestion 1"],
  "summary": "One-sentence review summary"
}

RULES:
- Issues are blocking — the build should NOT commit if any issues exist.
- Suggestions are non-blocking improvements for future consideration.
- Be specific: reference file paths and the problematic code.
- Do NOT flag style preferences (bracket placement, blank lines). Only flag
  violations of the engineering standards in your Standing Orders.
- If the code is clean, approve with an empty issues list.
"""

    def _resolve_tier(self) -> str:
        """Use standard tier — review is classification, not generation."""
        return "standard"

    async def review(
        self,
        file_changes: list[dict[str, Any]],
        spec_title: str,
        llm_client: LLMClient,
    ) -> ReviewResult:
        """Review file changes against Standing Orders.

        Args:
            file_changes: List of file change dicts from Builder output.
            spec_title: Title of the build spec being reviewed.
            llm_client: LLM client for the review call.

        Returns:
            ReviewResult with approval status and any issues found.
        """
        # Compose instructions from Standing Orders (federation + ship + engineering + agent)
        system_prompt = compose_instructions(
            agent_type=self.agent_type,
            hardcoded_instructions=self.instructions,
        )

        # Build review prompt
        changes_text = self._format_changes(file_changes)

        prompt = (
            f"## Build Spec\n{spec_title}\n\n"
            f"## Code Changes to Review\n{changes_text}\n\n"
            "Review these changes against the engineering standards in your "
            "Standing Orders. Return your review as a JSON object."
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            tier="standard",
        )

        try:
            response = await llm_client.complete(request)
            return self._parse_review(response.content)
        except Exception as exc:
            logger.warning("CodeReviewAgent: review failed: %s", exc)
            # On failure, approve with warning — don't block pipeline on reviewer errors
            return ReviewResult(
                approved=True,
                suggestions=[f"Code review skipped due to error: {exc}"],
                summary="Review skipped (LLM error)",
            )

    def _format_changes(self, file_changes: list[dict[str, Any]]) -> str:
        """Format file changes for the review prompt."""
        parts = []
        for change in file_changes:
            path = change.get("path", "unknown")
            mode = change.get("mode", "create")
            if mode == "modify":
                repls = change.get("replacements", [])
                repl_text = "\n".join(
                    f"SEARCH:\n{r['search']}\nREPLACE:\n{r['replace']}"
                    for r in repls
                )
                parts.append(f"### MODIFY: {path}\n{repl_text}")
            else:
                content = change.get("content", "")[:3000]
                parts.append(f"### CREATE: {path}\n```python\n{content}\n```")
        return "\n\n".join(parts)

    def _parse_review(self, content: str) -> ReviewResult:
        """Parse LLM review response into ReviewResult."""
        result = ReviewResult()

        # Extract JSON from response (may be wrapped in markdown code block)
        text = content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            data = json.loads(text)
            result.approved = data.get("approved", False)
            result.issues = data.get("issues", [])
            result.suggestions = data.get("suggestions", [])
            result.summary = data.get("summary", "")
        except (json.JSONDecodeError, AttributeError):
            lower = content.lower()
            if "no issues" in lower or '"approved": true' in lower:
                result.approved = True
                result.summary = "Approved (parsed from text)"
            else:
                result.approved = False
                result.issues = ["Could not parse review response"]
                result.summary = content[:200]

        return result
```

### Step 2: Integrate into Builder pipeline

In `execute_approved_build()` in `builder.py`, add a review step between file writes and the test loop.

Insert after step 4 (validation) and before step 5 (test loop), around line 2113:

```python
# 4b. Code review (AD-341)
if llm_client and (written or modified_files):
    from probos.cognitive.code_reviewer import CodeReviewAgent
    reviewer = CodeReviewAgent(
        agent_id="code_reviewer",
        name="CodeReviewAgent",
    )
    try:
        review = await reviewer.review(
            file_changes=file_changes,
            spec_title=spec.title,
            llm_client=llm_client,
        )
        result.review_result = review.summary
        if not review.approved:
            logger.warning(
                "CodeReviewAgent: review REJECTED -- %s",
                "; ".join(review.issues),
            )
            # Soft gate: log issues but don't block.
            # Future: hard gate after reviewer earns trust.
            result.review_issues = review.issues
    except Exception as exc:
        logger.warning("CodeReviewAgent: review error: %s", exc)
```

### Step 3: Add `review_result` and `review_issues` to BuildResult

In `builder.py`, find the `BuildResult` dataclass and add:

```python
review_result: str = ""
review_issues: list[str] = field(default_factory=list)
```

### Step 4: Surface review in HXI

In `api.py`, `_execute_build()`, add review info to the build event payload:

```python
"review": result.review_result,
"review_issues": result.review_issues,
```

### Step 5: Tests

Create `tests/test_code_reviewer.py`:

1. `test_review_approves_clean_code` — Mock LLM returns `{"approved": true, ...}` → `ReviewResult.approved is True`
2. `test_review_rejects_with_issues` — Mock LLM returns issues → `approved is False`, issues populated
3. `test_parse_review_json` — Test JSON parsing from LLM response
4. `test_parse_review_markdown_wrapped` — Test JSON extraction from ```json``` code blocks
5. `test_parse_review_fallback_approved` — Unparseable response containing "no issues" → approved
6. `test_parse_review_fallback_rejected` — Unparseable response without approval signals → rejected
7. `test_review_error_approves_with_warning` — LLM error → approved=True with warning
8. `test_format_changes_create` — Test change formatting for CREATE mode
9. `test_format_changes_modify` — Test change formatting for MODIFY mode
10. `test_review_uses_standing_orders` — Verify `compose_instructions` is called with `agent_type="code_reviewer"`

Add to `tests/test_builder_agent.py`:

11. `test_execute_build_runs_code_review` — Mock CodeReviewAgent, verify `review()` is called when `llm_client` is provided
12. `test_execute_build_logs_review_issues` — Review returns issues → verify they appear in `result.review_issues`

---

## Verification

After all four ADs, run the full test suite:

```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

Expected: All existing tests pass + new tests pass. No regressions.

**Key invariant**: If `config/standing_orders/` is empty or missing, every agent behaves exactly as before. Standing orders are purely additive.

## Execution Order

Build in this order — each AD depends on the previous:

1. **AD-338** (Commit gate + fix loop) — Foundation: makes the pipeline safe
2. **AD-339** (Standing Orders architecture) — Infrastructure: creates the instructions system
3. **AD-340** (Builder instructions enhancement) — Content: adds test-writing rules to the Builder
4. **AD-341** (Code Review Agent) — Quality gate: adds the reviewer that reads standing orders

## Do NOT Build

- Do not add the CodeReviewAgent to runtime.py pool registration — it's invoked directly by the Builder pipeline
- Do not add a `/review` slash command — the reviewer is an internal pipeline component
- Do not make the reviewer a hard gate yet — soft gate until trust is earned
- Do not add self-mod integration for standing orders evolution yet — that's a future AD
- Do not add Ship Class standing orders variants — that's a commercial roadmap item
- Do not refactor existing Builder code beyond the specified integration points
- Do not add federation gossip for standing orders sharing — future phase
- Do not modify `.github/copilot-instructions.md` — it stays as-is for human IDE use
- Do not add HXI visualization for standing orders or the reviewer beyond the event payload fields

## Architectural Notes

### Why Standing Orders Instead of Just `.github/copilot-instructions.md`?

| Property | copilot-instructions.md | Standing Orders |
|---|---|---|
| IDE dependency | Requires VS Code + Copilot | Standalone |
| Hierarchy | Flat, single file | 4-tier composition |
| Evolution | Manual human edits only | Agent-proposable via self-mod |
| Ship Classes | N/A | Different orders per class |
| Federation | N/A | Shareable via gossip |
| Scope | One file for all contexts | Per-department, per-agent |

### How This Maps to Industry Patterns

| System | Constitution File | ProbOS Equivalent |
|---|---|---|
| Claude Code | `CLAUDE.md` | `federation.md` + `ship.md` |
| OpenClaw | `soul.md` | `federation.md` (identity/personality) |
| GitHub Copilot | `.github/copilot-instructions.md` | `ship.md` (project standards) |
| Cursor | `.cursorrules` | `ship.md` (coding conventions) |

ProbOS is the first to make this hierarchical and evolvable. Others have a single flat file. ProbOS composes four tiers, and the agent tiers can evolve through the learning loop.

### Evolution Path (Future ADs — not in this prompt)

1. **Correction → Standing Orders**: When an agent is corrected 3+ times for the same issue, the Counselor proposes a standing orders update through the self-mod pipeline
2. **Dream → Standing Orders**: Dream consolidation identifies repeated patterns and proposes them as standing orders
3. **Federation sharing**: Ships gossip standing orders updates (metadata only, not full content) — fleet-wide best practices
4. **Ship Classes**: `probos init --class=warship` loads security-heavy `federation.md` variant
5. **Captain's Log integration**: Captain-authored standing orders updates get journaled

### Trust Progression for Code Reviewer

1. **Phase 1 (this AD)**: Soft gate — logs issues, doesn't block commits
2. **Phase 2 (future)**: Hard gate for test files only — blocks on test issues
3. **Phase 3 (future)**: Hard gate for all files — blocks on any issue
4. **Phase 4 (future)**: Reviewer proposes standing orders updates based on patterns it sees

This mirrors ProbOS's trust model: `Beta(1,3) = 0.25` probationary trust, earned through demonstrated competence.
