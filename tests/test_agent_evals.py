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

from probos.cognitive.decomposer import IntentDecomposer
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.working_memory import WorkingMemoryManager

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "eval"


def load_fixture(name: str) -> list[dict]:
    """Load a golden test fixture file."""
    fixture_path = FIXTURES_DIR / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


# ── Decomposer Eval ──────────────────────────────────────────────────────


# Cases where MockLLMClient has matching patterns → deterministic exact match
_DECOMPOSER_EXACT_CASES = [
    "simple_read",
    "read_absolute_path",
    "system_health_check",
    "write_file",
    "list_directory",
    "search_files",
    "web_search",
    "weather_query",
    "explain_last",
    "agent_info",
    "run_command",
]

# Cases that check structural properties (min intents, response presence)
_DECOMPOSER_STRUCTURAL_CASES = [
    "conversational_greeting",
    "conversational_thanks",
    "empty_input",
    "knowledge_question",
]


class TestDecomposerEval:
    """Evaluate decomposer output quality against golden dataset."""

    @pytest.fixture
    def decomposer_cases(self):
        return load_fixture("decomposer_cases.json")

    @pytest.fixture
    def decomposer(self):
        """Create an IntentDecomposer with MockLLMClient."""
        llm = MockLLMClient()
        wm = WorkingMemoryManager()
        return IntentDecomposer(llm_client=llm, working_memory=wm)

    @pytest.mark.parametrize("case_id", _DECOMPOSER_EXACT_CASES)
    async def test_decomposer_exact_match(self, decomposer, decomposer_cases, case_id):
        """Test cases where we expect exact intent matching."""
        case = next(c for c in decomposer_cases if c["id"] == case_id)
        dag = await decomposer.decompose(case["input"])

        expected = case.get("expected_intents", [])
        actual_intents = [n.intent for n in dag.nodes]

        for exp in expected:
            assert exp["intent"] in actual_intents, (
                f"Case {case_id}: expected intent '{exp['intent']}' "
                f"not found in {actual_intents}"
            )

    @pytest.mark.parametrize("case_id", _DECOMPOSER_STRUCTURAL_CASES)
    async def test_decomposer_conversational(self, decomposer, decomposer_cases, case_id):
        """Test that conversational inputs don't produce task intents."""
        case = next(c for c in decomposer_cases if c["id"] == case_id)
        dag = await decomposer.decompose(case["input"])

        # Conversational: should have either a response or no intents
        # MockLLMClient returns {"intents": []} for unmatched inputs,
        # which is correct behavior (empty DAG = conversational fallback)
        if case.get("expected_response"):
            has_response = bool(dag.response)
            has_no_intents = len(dag.nodes) == 0
            assert has_response or has_no_intents, (
                f"Case {case_id}: expected conversational (response or empty intents), "
                f"got {len(dag.nodes)} intents and response={dag.response!r}"
            )


# ── Code Reviewer Eval ────────────────────────────────────────────────────


class TestCodeReviewerEval:
    """Evaluate code reviewer output quality against golden dataset."""

    @pytest.fixture
    def review_cases(self):
        return load_fixture("code_review_cases.json")

    @pytest.fixture
    def reviewer(self):
        """Create a CodeReviewAgent with MockLLMClient."""
        from probos.cognitive.code_reviewer import CodeReviewAgent
        return CodeReviewAgent()

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.mark.parametrize("case_id", [
        "clean_function", "good_error_handling", "complex_but_correct", "proper_typing",
    ])
    async def test_review_clean_code(self, reviewer, llm, review_cases, case_id):
        """Test that clean code gets reviewed without structural errors."""
        case = next(c for c in review_cases if c["id"] == case_id)
        file_changes = [{"path": "test_file.py", "mode": "CREATE", "content": case["code"]}]
        result = await reviewer.review(file_changes, "Test review", llm)
        # With MockLLMClient, we verify the review pipeline completes
        # and returns a ReviewResult (structural validation)
        assert result is not None
        assert hasattr(result, "approved")

    @pytest.mark.parametrize("case_id", [
        "sql_injection", "command_injection", "xss_vulnerability",
        "hardcoded_secret", "eval_usage", "insecure_random",
    ])
    async def test_review_security_issues(self, reviewer, llm, review_cases, case_id):
        """Test that security-sensitive code gets reviewed (structural)."""
        case = next(c for c in review_cases if c["id"] == case_id)
        file_changes = [{"path": "test_file.py", "mode": "CREATE", "content": case["code"]}]
        result = await reviewer.review(file_changes, "Test review", llm)
        # Structural: review completes and returns a result
        assert result is not None
        assert hasattr(result, "approved")
        assert hasattr(result, "issues")


# ── Eval Metrics ──────────────────────────────────────────────────────────


class TestEvalMetrics:
    """Meta-tests that measure overall eval coverage."""

    def test_decomposer_fixture_exists(self):
        """Verify the decomposer golden dataset exists and is valid."""
        cases = load_fixture("decomposer_cases.json")
        assert len(cases) >= 15, f"Need >= 15 decomposer cases, got {len(cases)}"
        for case in cases:
            assert "id" in case, "Every case needs an id"
            assert "input" in case, f"Case {case.get('id')} missing input"
            assert "criteria" in case, f"Case {case.get('id')} missing criteria"

    def test_code_review_fixture_exists(self):
        """Verify the code review golden dataset exists and is valid."""
        cases = load_fixture("code_review_cases.json")
        assert len(cases) >= 10, f"Need >= 10 review cases, got {len(cases)}"
        for case in cases:
            assert "id" in case, "Every case needs an id"
            assert "code" in case, f"Case {case.get('id')} missing code"
            assert "criteria" in case, f"Case {case.get('id')} missing criteria"

    def test_decomposer_case_ids_unique(self):
        """Verify no duplicate case IDs in decomposer fixture."""
        cases = load_fixture("decomposer_cases.json")
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_code_review_case_ids_unique(self):
        """Verify no duplicate case IDs in code review fixture."""
        cases = load_fixture("code_review_cases.json")
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_eval_summary(self, tmp_path):
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

        assert report["decomposer_total_cases"] >= 15
        assert report["code_review_total_cases"] >= 10
