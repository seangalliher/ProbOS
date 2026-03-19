"""Tests for Code Review Agent (AD-341)."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.cognitive.code_reviewer import CodeReviewAgent, ReviewResult


class TestCodeReviewAgent:
    """Tests for CodeReviewAgent review pipeline."""

    @pytest.fixture
    def reviewer(self):
        return CodeReviewAgent(
            agent_id="code_reviewer",
            name="CodeReviewAgent",
        )

    @pytest.mark.asyncio
    async def test_review_approves_clean_code(self, reviewer):
        """Mock LLM returns approved review."""
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "approved": True,
                "issues": [],
                "suggestions": ["Consider adding a docstring"],
                "summary": "Clean code, approved.",
            }),
        ))

        result = await reviewer.review(
            file_changes=[{"path": "test.py", "content": "x = 1\n", "mode": "create"}],
            spec_title="Test Build",
            llm_client=mock_llm,
        )

        assert result.approved is True
        assert result.issues == []
        assert result.summary == "Clean code, approved."

    @pytest.mark.asyncio
    async def test_review_rejects_with_issues(self, reviewer):
        """Mock LLM returns issues."""
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content=json.dumps({
                "approved": False,
                "issues": ["Missing import: from probos.types import IntentMessage"],
                "suggestions": [],
                "summary": "Import violation detected.",
            }),
        ))

        result = await reviewer.review(
            file_changes=[{"path": "agent.py", "content": "class MyAgent: pass\n", "mode": "create"}],
            spec_title="Test Build",
            llm_client=mock_llm,
        )

        assert result.approved is False
        assert len(result.issues) == 1
        assert "Missing import" in result.issues[0]

    @pytest.mark.asyncio
    async def test_review_error_approves_with_warning(self, reviewer):
        """LLM error results in approved with warning."""
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        result = await reviewer.review(
            file_changes=[{"path": "test.py", "content": "x = 1\n", "mode": "create"}],
            spec_title="Test",
            llm_client=mock_llm,
        )

        assert result.approved is True
        assert any("error" in s.lower() for s in result.suggestions)
        assert "skipped" in result.summary.lower()


class TestParseReview:
    """Tests for _parse_review() JSON parsing."""

    @pytest.fixture
    def reviewer(self):
        return CodeReviewAgent(
            agent_id="code_reviewer",
            name="CodeReviewAgent",
        )

    def test_parse_review_json(self, reviewer):
        """Direct JSON response is parsed correctly."""
        content = json.dumps({
            "approved": True,
            "issues": [],
            "suggestions": ["Nice work"],
            "summary": "All good.",
        })
        result = reviewer._parse_review(content)
        assert result.approved is True
        assert result.summary == "All good."

    def test_parse_review_markdown_wrapped(self, reviewer):
        """JSON wrapped in markdown code block is extracted."""
        content = '```json\n{"approved": true, "issues": [], "suggestions": [], "summary": "ok"}\n```'
        result = reviewer._parse_review(content)
        assert result.approved is True

    def test_parse_review_fallback_approved(self, reviewer):
        """Unparseable response containing 'no issues' is treated as approved."""
        content = "The code looks good, no issues found."
        result = reviewer._parse_review(content)
        assert result.approved is True

    def test_parse_review_fallback_rejected(self, reviewer):
        """Unparseable response without approval signals is treated as rejected."""
        content = "There are several problems with this code."
        result = reviewer._parse_review(content)
        assert result.approved is False
        assert len(result.issues) == 1


class TestFormatChanges:
    """Tests for _format_changes()."""

    @pytest.fixture
    def reviewer(self):
        return CodeReviewAgent(
            agent_id="code_reviewer",
            name="CodeReviewAgent",
        )

    def test_format_changes_create(self, reviewer):
        """CREATE mode files are formatted with path and content."""
        changes = [{"path": "new.py", "content": "x = 1\n", "mode": "create"}]
        result = reviewer._format_changes(changes)
        assert "CREATE: new.py" in result
        assert "x = 1" in result

    def test_format_changes_modify(self, reviewer):
        """MODIFY mode files show SEARCH/REPLACE blocks."""
        changes = [{"path": "existing.py", "mode": "modify", "replacements": [
            {"search": "old_code", "replace": "new_code"},
        ]}]
        result = reviewer._format_changes(changes)
        assert "MODIFY: existing.py" in result
        assert "SEARCH:" in result
        assert "REPLACE:" in result


class TestReviewUsesStandingOrders:
    """Tests that review integrates with Standing Orders."""

    @pytest.mark.asyncio
    async def test_review_uses_standing_orders(self):
        """Verify compose_instructions is called with agent_type='code_reviewer'."""
        reviewer = CodeReviewAgent(
            agent_id="code_reviewer",
            name="CodeReviewAgent",
        )
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(return_value=MagicMock(
            content='{"approved": true, "issues": [], "suggestions": [], "summary": "ok"}',
        ))

        with patch("probos.cognitive.code_reviewer.compose_instructions", wraps=lambda **kw: kw.get("hardcoded_instructions", "")) as mock_compose:
            await reviewer.review(
                file_changes=[{"path": "test.py", "content": "x = 1", "mode": "create"}],
                spec_title="Test",
                llm_client=mock_llm,
            )
            mock_compose.assert_called_once()
            call_kwargs = mock_compose.call_args
            assert call_kwargs[1].get("agent_type") == "code_reviewer" or call_kwargs[0][0] == "code_reviewer"
