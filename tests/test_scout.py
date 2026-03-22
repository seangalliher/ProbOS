"""Tests for AD-394/AD-395: ScoutAgent — GitHub intelligence gathering."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.scout import (
    ScoutAgent,
    ScoutFinding,
    filter_findings,
    format_digest,
    parse_scout_reports,
)


# ── Sample LLM output (with AD-395 credibility/reliability fields) ──

_SAMPLE_LLM_OUTPUT = """\
===SCOUT_REPORT===
REPO: langchain-ai/open-swe
STARS: 3200
URL: https://github.com/langchain-ai/open-swe
CLASS: absorb
RELEVANCE: 4
CREDIBILITY: 4
RELIABILITY: 3
SUMMARY: MIT framework for internal coding agents with middleware-based determinism.
INSIGHT: Middleware pattern validates ProbOS Navigational Deflector concept. File-based context offloading matches Transporter Pattern.
===END===

===SCOUT_REPORT===
REPO: microsoft/autogen
STARS: 40000
URL: https://github.com/microsoft/autogen
CLASS: visiting_officer
RELEVANCE: 5
CREDIBILITY: 5
RELIABILITY: 5
SUMMARY: Multi-agent conversation framework supporting flexible agent topologies.
INSIGHT: Could serve as a visiting code generation engine. Supports disabling its orchestration — passes Subordination Principle.
===END===

===SCOUT_REPORT===
REPO: some-user/hello-world
STARS: 10
URL: https://github.com/some-user/hello-world
CLASS: skip
RELEVANCE: 1
CREDIBILITY: 1
RELIABILITY: 1
SUMMARY: A basic hello world project.
INSIGHT: Not relevant.
===END===

===SCOUT_REPORT===
REPO: low-rel/agent-tool
STARS: 80
URL: https://github.com/low-rel/agent-tool
CLASS: absorb
RELEVANCE: 2
CREDIBILITY: 2
RELIABILITY: 2
SUMMARY: Simple agent wrapper for LLM calls.
INSIGHT: Too basic for ProbOS absorption.
===END===
"""

# Sample without credibility/reliability (backward compat)
_SAMPLE_LLM_OUTPUT_LEGACY = """\
===SCOUT_REPORT===
REPO: legacy/repo
STARS: 100
URL: https://github.com/legacy/repo
CLASS: absorb
RELEVANCE: 4
SUMMARY: Legacy format without credibility/reliability.
INSIGHT: Should default to 3.
===END===
"""


class TestParseScoutReports:
    """Test ===SCOUT_REPORT=== block parsing."""

    def test_parse_scout_report(self):
        """Verify block parsing extracts all fields correctly."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        assert len(findings) == 3  # absorb(4), visiting_officer(5), absorb(2) — skip excluded
        first = findings[0]
        assert first.repo_full_name == "langchain-ai/open-swe"
        assert first.stars == 3200
        assert first.url == "https://github.com/langchain-ai/open-swe"
        assert first.classification == "absorb"
        assert first.relevance == 4
        assert first.credibility == 4
        assert first.reliability == 3
        assert "middleware" in first.summary.lower()
        assert "Transporter" in first.insight

    def test_classify_absorb(self):
        """Mock LLM output with absorb classification."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        absorbs = [f for f in findings if f.classification == "absorb"]
        assert len(absorbs) == 2
        assert absorbs[0].classification == "absorb"

    def test_classify_visiting_officer(self):
        """Verify visiting_officer classification."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        visiting = [f for f in findings if f.classification == "visiting_officer"]
        assert len(visiting) == 1
        assert visiting[0].repo_full_name == "microsoft/autogen"
        assert visiting[0].relevance == 5
        assert visiting[0].credibility == 5
        assert visiting[0].reliability == 5

    def test_parse_extracts_credibility_reliability(self):
        """AD-395: credibility and reliability fields parsed from report blocks."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        first = findings[0]
        assert first.credibility == 4
        assert first.reliability == 3

    def test_defaults_to_3_when_fields_missing(self):
        """AD-395: credibility/reliability default to 3 for backward compat."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT_LEGACY)
        assert len(findings) == 1
        assert findings[0].credibility == 3
        assert findings[0].reliability == 3


class TestCompositeScore:
    """AD-395: composite score calculation."""

    def test_composite_score(self):
        """Weighted composite: relevance 50%, credibility 25%, reliability 25%."""
        f = ScoutFinding("a/b", 100, "url", "absorb", 4, 4, 4, "s", "i")
        assert f.composite_score == 4.0

    def test_composite_score_mixed(self):
        """Mixed scores produce correct weighted average."""
        f = ScoutFinding("a/b", 100, "url", "absorb", 5, 3, 1, "s", "i")
        # 5*0.5 + 3*0.25 + 1*0.25 = 2.5 + 0.75 + 0.25 = 3.5
        assert f.composite_score == 3.5


class TestFilterFindings:
    """Test composite score filtering."""

    def test_filter_by_composite_score(self):
        """AD-395: filter uses composite_score, not just relevance."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        filtered = filter_findings(findings, min_relevance=3)
        assert len(filtered) == 2  # composite 3.75 and 5.0
        assert all(f.composite_score >= 3 for f in filtered)

    def test_sorted_by_composite_descending(self):
        """Filtered findings sorted by composite_score descending."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        filtered = filter_findings(findings)
        assert filtered[0].composite_score >= filtered[-1].composite_score


class TestSeenTracking:
    """Test seen repos deduplication."""

    def test_seen_tracking(self, tmp_path: Path):
        """Seen repos are persisted and duplicates are skipped."""
        seen_file = tmp_path / "scout_seen.json"

        with patch("probos.cognitive.scout._SEEN_FILE", seen_file):
            from probos.cognitive.scout import _load_seen, _save_seen

            assert _load_seen() == {}
            seen = {"owner/repo1": "2026-03-22T00:00:00+00:00"}
            _save_seen(seen)
            loaded = _load_seen()
            assert "owner/repo1" in loaded


class TestDiscordFormat:
    """Test digest formatting."""

    def test_discord_format(self):
        """Verify digest text formatting including AD-395 fields."""
        findings = [
            ScoutFinding(
                repo_full_name="test/absorb-repo",
                stars=500,
                url="https://github.com/test/absorb-repo",
                classification="absorb",
                relevance=4,
                credibility=3,
                reliability=4,
                summary="A useful pattern library.",
                insight="Context management patterns worth studying.",
                language="Python",
                license="MIT",
            ),
            ScoutFinding(
                repo_full_name="test/vo-repo",
                stars=1000,
                url="https://github.com/test/vo-repo",
                classification="visiting_officer",
                relevance=5,
                credibility=5,
                reliability=5,
                summary="A subordination-compatible tool.",
                insight="Can disable orchestration loop.",
                language="TypeScript",
                license="Apache-2.0",
            ),
        ]
        digest = format_digest(findings, "2026-03-22")
        assert "**ProbOS Scout Report -- 2026-03-22**" in digest
        assert "**ABSORB CANDIDATES:**" in digest
        assert "**VISITING OFFICER CANDIDATES:**" in digest
        assert "test/absorb-repo" in digest
        assert "test/vo-repo" in digest
        assert "500 stars, Python, MIT" in digest
        assert "2 findings" in digest
        # AD-395: composite score and R/C/L fields
        assert "score:" in digest
        assert "R:4 C:3 L:4" in digest


class TestNotificationThreshold:
    """Test Bridge notification behavior."""

    def test_notification_threshold_composite(self):
        """AD-395: composite_score >= 4 triggers notifications."""
        findings = [
            ScoutFinding("a/b", 100, "url", "absorb", 3, 3, 3, "s", "i"),  # composite 3.0
            ScoutFinding("c/d", 200, "url", "absorb", 4, 4, 4, "s", "i"),  # composite 4.0
            ScoutFinding("e/f", 300, "url", "visiting_officer", 5, 5, 5, "s", "i"),  # composite 5.0
        ]
        notified = [f for f in findings if f.composite_score >= 4]
        assert len(notified) == 2
        assert notified[0].repo_full_name == "c/d"
        assert notified[1].repo_full_name == "e/f"


class TestGhCliSearch:
    """AD-395: gh CLI search integration."""

    @pytest.mark.asyncio
    async def test_search_github_calls_gh_api(self):
        """_search_github calls gh api subprocess correctly."""
        agent = ScoutAgent(runtime=None)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"items": [{"full_name": "test/repo", "stargazers_count": 100}]})
        with patch("probos.cognitive.scout.subprocess.run", return_value=mock_result) as mock_run:
            items = await agent._search_github("topic:ai-agents", 50)
        assert len(items) == 1
        assert items[0]["full_name"] == "test/repo"
        # Verify gh api was called
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "gh"
        assert call_args[1] == "api"

    @pytest.mark.asyncio
    async def test_search_github_handles_gh_not_found(self):
        """Graceful degradation when gh CLI is not available."""
        agent = ScoutAgent(runtime=None)
        with patch("probos.cognitive.scout.subprocess.run", side_effect=FileNotFoundError):
            items = await agent._search_github("topic:ai-agents", 50)
        assert items == []


class TestGracefulNoDiscord:
    """Test graceful handling when Discord is absent."""

    @pytest.mark.asyncio
    async def test_graceful_no_discord(self):
        """No error when Discord adapter is absent or scout_channel_id is 0."""
        agent = ScoutAgent(runtime=None)
        await agent._deliver_discord([], "2026-03-22")

    @pytest.mark.asyncio
    async def test_graceful_channel_id_zero(self):
        """No error when scout_channel_id is 0."""
        mock_runtime = MagicMock()
        mock_runtime.channel_adapters = {"discord": MagicMock(running=True)}
        mock_runtime.config.channels.discord.scout_channel_id = 0

        agent = ScoutAgent(runtime=mock_runtime)
        await agent._deliver_discord([], "2026-03-22")
        mock_runtime.channel_adapters["discord"].send_response.assert_not_called()
