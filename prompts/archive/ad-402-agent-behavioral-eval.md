# AD-402: Agent Behavioral Eval Framework — Phase 1

## Context

ProbOS has 2790+ code tests, strong operational health monitoring (trust, Counselor, BehavioralMonitor), but **zero agent cognition tests**. Every cognitive agent test mocks the LLM and asserts structural properties — never output quality. If the Decomposer starts misclassifying intents or Wesley's analysis quality degrades, nothing detects it.

Phase 1 builds the evaluation infrastructure and creates golden test datasets for the two most critical cognitive paths: the **Decomposer** (every user request) and the **CodeReviewer** (every builder output).

## Design Principles

1. **Evals are tests, not services.** Pytest test files that can run in CI. No new runtime services.
2. **Golden datasets drive quality.** Fixed input/expected-output pairs that catch behavioral regressions.
3. **LLM-as-judge for nuanced quality.** When exact-match isn't appropriate, use a cheap LLM to score outputs against criteria.
4. **Mock-first, live-optional.** Default to MockLLMClient for determinism. Optional `--live-llm` marker for real LLM evaluation runs.
5. **Build on existing data.** FeedbackEngine labels, EpisodicMemory traces, TrustEvents — use what's already collected.

## Part 1: Golden Test Fixtures

### Create `tests/fixtures/eval/` directory

Create golden test fixtures as JSON files:

### `tests/fixtures/eval/decomposer_cases.json`

A JSON array of test cases. Each case has an input, expected intents, and evaluation criteria:

```json
[
  {
    "id": "simple_read",
    "input": "Read the file src/probos/types.py",
    "expected_intents": [
      {"intent": "read_file", "params": {"path": "src/probos/types.py"}}
    ],
    "criteria": "Single intent, correct path extraction"
  },
  {
    "id": "multi_step",
    "input": "Read src/probos/runtime.py and then tell me how shutdown works",
    "expected_intents": [
      {"intent": "read_file", "params": {"path": "src/probos/runtime.py"}},
      {"intent": "analyze_code"}
    ],
    "criteria": "Two intents with dependency, file read before analysis"
  },
  {
    "id": "ambiguous_refactor",
    "input": "Refactor the trust model to use a sliding window",
    "expected_intents": [
      {"intent": "read_file"},
      {"intent": "generate_code"}
    ],
    "min_intents": 2,
    "criteria": "Must read before generating. Should identify consensus/trust.py as target."
  },
  {
    "id": "conversational_greeting",
    "input": "Hello, how are you?",
    "expected_response": true,
    "expected_intents": [],
    "criteria": "Should produce a conversational response, not a task DAG"
  },
  {
    "id": "slash_command",
    "input": "/status",
    "expected_intents": [
      {"intent": "system_status"}
    ],
    "criteria": "Direct slash command mapping"
  },
  {
    "id": "at_callsign",
    "input": "@wesley what did you find?",
    "expected_intents": [
      {"intent": "direct_message"}
    ],
    "criteria": "Callsign addressing should produce direct_message intent"
  },
  {
    "id": "complex_multi_file",
    "input": "Add a new agent that monitors disk usage and alerts when it's over 90%",
    "min_intents": 2,
    "criteria": "Should decompose into multiple steps: read existing patterns, generate agent code, register in pool"
  },
  {
    "id": "diagnostic_request",
    "input": "Run a diagnostic on the trust network",
    "expected_intents": [
      {"intent": "diagnose_system"}
    ],
    "criteria": "Should route to medical team diagnostic"
  }
]
```

Include at minimum **15 cases** spanning: simple single-intent, multi-step with dependencies, conversational/greeting, slash commands, callsign addressing, ambiguous requests, complex multi-file tasks, diagnostic requests, knowledge questions, error-provoking inputs (empty string, very long input, prompt injection attempts).

### `tests/fixtures/eval/code_review_cases.json`

```json
[
  {
    "id": "clean_code",
    "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
    "expected_approved": true,
    "criteria": "Simple clean function should be approved"
  },
  {
    "id": "sql_injection",
    "code": "def get_user(name):\n    query = f\"SELECT * FROM users WHERE name = '{name}'\"\n    return db.execute(query)\n",
    "expected_approved": false,
    "criteria": "SQL injection vulnerability must be caught"
  },
  {
    "id": "missing_error_handling",
    "code": "def read_config(path):\n    with open(path) as f:\n        return json.loads(f.read())\n",
    "expected_issues_min": 1,
    "criteria": "Should flag missing error handling for file/JSON operations"
  }
]
```

Include at minimum **10 cases** spanning: clean code, security vulnerabilities (SQL injection, command injection, XSS), missing error handling, code style issues, complex but correct code.

## Part 2: Eval Test Runner

### Create `tests/test_agent_evals.py`

```python
"""Agent behavioral evaluation tests (AD-402).

Golden-dataset driven quality tests for cognitive agent outputs.
Tests agent behavior, not code mechanics. Uses MockLLMClient by default;
mark with @pytest.mark.live_llm for real LLM evaluation.

These tests validate that:
- Agent outputs match expected structural patterns
- Quality criteria are met for known inputs
- Behavioral regressions are caught
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eval"


def load_fixture(name: str) -> list[dict]:
    """Load a golden test fixture file."""
    fixture_path = FIXTURES_DIR / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


# ---- Decomposer Eval ----

class TestDecomposerEval:
    """Evaluate decomposer output quality against golden dataset."""

    @pytest.fixture
    def decomposer_cases(self):
        return load_fixture("decomposer_cases.json")

    @pytest.fixture
    def decomposer(self):
        """Create a Decomposer with MockLLMClient."""
        from probos.cognitive.decomposer import Decomposer
        from probos.cognitive.llm_client import MockLLMClient
        llm = MockLLMClient()
        return Decomposer(llm_client=llm)

    @pytest.mark.parametrize("case_id", [
        "simple_read", "slash_command", "conversational_greeting",
        "diagnostic_request",
    ])
    async def test_decomposer_exact_match(self, decomposer, decomposer_cases, case_id):
        """Test cases where we expect exact intent matching."""
        case = next(c for c in decomposer_cases if c["id"] == case_id)
        dag = await decomposer.decompose(case["input"])

        if case.get("expected_response"):
            # Conversational — should have response text, no task intents
            assert dag.response, f"Case {case_id}: expected conversational response"
            return

        expected = case.get("expected_intents", [])
        actual_intents = [n.intent for n in dag.nodes]

        for exp in expected:
            assert exp["intent"] in actual_intents, (
                f"Case {case_id}: expected intent '{exp['intent']}' "
                f"not found in {actual_intents}"
            )

    @pytest.mark.parametrize("case_id", [
        "ambiguous_refactor", "complex_multi_file",
    ])
    async def test_decomposer_structural(self, decomposer, decomposer_cases, case_id):
        """Test cases where we check structural properties, not exact intents."""
        case = next(c for c in decomposer_cases if c["id"] == case_id)
        dag = await decomposer.decompose(case["input"])

        min_intents = case.get("min_intents", 1)
        assert len(dag.nodes) >= min_intents, (
            f"Case {case_id}: expected >= {min_intents} intents, "
            f"got {len(dag.nodes)}"
        )


# ---- Code Reviewer Eval ----

class TestCodeReviewerEval:
    """Evaluate code reviewer output quality against golden dataset."""

    @pytest.fixture
    def review_cases(self):
        return load_fixture("code_review_cases.json")

    @pytest.fixture
    def reviewer(self):
        """Create a CodeReviewer with MockLLMClient."""
        from probos.cognitive.code_reviewer import CodeReviewer
        from probos.cognitive.llm_client import MockLLMClient
        llm = MockLLMClient()
        return CodeReviewer(llm_client=llm)

    @pytest.mark.parametrize("case_id", [
        "clean_code", "sql_injection",
    ])
    async def test_review_verdict(self, reviewer, review_cases, case_id):
        """Test that reviewer produces correct approval/rejection."""
        case = next(c for c in review_cases if c["id"] == case_id)
        result = await reviewer.review(case["code"])

        if "expected_approved" in case:
            assert result.approved == case["expected_approved"], (
                f"Case {case_id}: expected approved={case['expected_approved']}, "
                f"got {result.approved}"
            )


# ---- Eval Metrics ----

class TestEvalMetrics:
    """Meta-tests that measure overall eval pass rates."""

    def test_decomposer_fixture_exists(self):
        """Verify the decomposer golden dataset exists and is valid."""
        cases = load_fixture("decomposer_cases.json")
        assert len(cases) >= 10, f"Need >= 10 decomposer cases, got {len(cases)}"
        for case in cases:
            assert "id" in case, "Every case needs an id"
            assert "input" in case, f"Case {case.get('id')} missing input"
            assert "criteria" in case, f"Case {case.get('id')} missing criteria"

    def test_code_review_fixture_exists(self):
        """Verify the code review golden dataset exists and is valid."""
        cases = load_fixture("code_review_cases.json")
        assert len(cases) >= 5, f"Need >= 5 review cases, got {len(cases)}"
```

**Implementation notes:**

- Use `pytest.mark.parametrize` with case IDs so each golden case is a separate test (individual pass/fail in CI output).
- Read the existing `Decomposer.__init__()` and `CodeReviewer.__init__()` signatures to match constructor args exactly — check what parameters they require.
- The `MockLLMClient` already has pattern-matched responses for some inputs. For inputs that don't match its patterns, it returns a generic response. The evals should work with both matched and unmatched inputs — that's the point (testing actual behavior, not mocked perfection).
- Make all async test methods compatible with `pytest-asyncio` (add `@pytest.mark.asyncio` if the project uses it, or check `conftest.py` for the asyncio mode configuration).

## Part 3: Eval Summary Reporter

### Add to `tests/test_agent_evals.py`

```python
def test_eval_summary(tmp_path):
    """Generate a human-readable eval summary report."""
    decomposer_cases = load_fixture("decomposer_cases.json")
    review_cases = load_fixture("code_review_cases.json")

    report = {
        "decomposer_total_cases": len(decomposer_cases),
        "code_review_total_cases": len(review_cases),
        "coverage": {
            "single_intent": sum(1 for c in decomposer_cases if len(c.get("expected_intents", [])) == 1),
            "multi_intent": sum(1 for c in decomposer_cases if len(c.get("expected_intents", [])) > 1),
            "conversational": sum(1 for c in decomposer_cases if c.get("expected_response")),
            "security_review": sum(1 for c in review_cases if "injection" in c.get("id", "") or "xss" in c.get("id", "")),
        },
    }

    report_path = tmp_path / "eval_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    # Just verify the report was generated — actual pass/fail metrics
    # would come from pytest's own collection results
    assert report["decomposer_total_cases"] >= 10
```

## What NOT to Build (Yet)

- **LLM-as-judge evaluation** — requires real LLM calls, adds cost and flakiness. Phase 2.
- **CognitiveJournal** — the production logging system for all LLM calls. Separate AD, significant scope.
- **Cross-agent comparison** — needs Ward Room (Phase 33) for agents to receive the same inputs.
- **Hallucination detection** — needs factual ground-truth corpus. Phase 2 after golden datasets mature.
- **`--live-llm` pytest marker** — infrastructure for running evals against a real LLM. Phase 2.

## Files Created

| File | Description |
|------|-------------|
| `tests/fixtures/eval/decomposer_cases.json` | 15+ golden test cases for decomposer |
| `tests/fixtures/eval/code_review_cases.json` | 10+ golden test cases for code reviewer |
| `tests/test_agent_evals.py` | Eval test runner with parametrized golden tests |

## Testing

```
uv run pytest tests/test_agent_evals.py -v
```

The fixture validation tests (`test_decomposer_fixture_exists`, `test_code_review_fixture_exists`) should always pass — they validate the golden datasets themselves.

The behavioral tests (`test_decomposer_exact_match`, `test_review_verdict`) run against MockLLMClient. Some may fail if MockLLMClient doesn't have appropriate canned responses for the golden inputs — that's expected and informative. Document which cases pass and which need live LLM validation.

Then run the full suite for regression:
```
uv run pytest tests/ --tb=short
```

## Commit Message

```
Add agent behavioral eval framework with golden datasets (AD-402)

Fixture-driven evaluation for decomposer and code reviewer. 15+
decomposer golden cases (single-intent, multi-step, conversational,
callsign, ambiguous, edge cases). 10+ code review golden cases
(clean code, security vulnerabilities, style issues). Parametrized
pytest runner with per-case pass/fail. Eval summary reporter.
Foundation for behavioral regression detection.
```
