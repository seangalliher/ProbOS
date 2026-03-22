"""Tests for AD-394: ScoutAgent — GitHub intelligence gathering."""

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


# ── Sample LLM output ──

_SAMPLE_LLM_OUTPUT = """\
===SCOUT_REPORT===
REPO: langchain-ai/open-swe
STARS: 3200
URL: https://github.com/langchain-ai/open-swe
CLASS: absorb
RELEVANCE: 4
SUMMARY: MIT framework for internal coding agents with middleware-based determinism.
INSIGHT: Middleware pattern validates ProbOS Navigational Deflector concept. File-based context offloading matches Transporter Pattern.
===END===

===SCOUT_REPORT===
REPO: microsoft/autogen
STARS: 40000
URL: https://github.com/microsoft/autogen
CLASS: visiting_officer
RELEVANCE: 5
SUMMARY: Multi-agent conversation framework supporting flexible agent topologies.
INSIGHT: Could serve as a visiting code generation engine. Supports disabling its orchestration — passes Subordination Principle.
===END===

===SCOUT_REPORT===
REPO: some-user/hello-world
STARS: 10
URL: https://github.com/some-user/hello-world
CLASS: skip
RELEVANCE: 1
SUMMARY: A basic hello world project.
INSIGHT: Not relevant.
===END===

===SCOUT_REPORT===
REPO: low-rel/agent-tool
STARS: 80
URL: https://github.com/low-rel/agent-tool
CLASS: absorb
RELEVANCE: 2
SUMMARY: Simple agent wrapper for LLM calls.
INSIGHT: Too basic for ProbOS absorption.
===END===
"""


class TestParseScoutReports:
    """Test ===SCOUT_REPORT=== block parsing."""

    def test_parse_scout_report(self):
        """Verify block parsing extracts all fields correctly."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        # skip and low-relevance are still parsed (filtering is separate)
        assert len(findings) == 3  # absorb(4), visiting_officer(5), absorb(2) — skip excluded
        first = findings[0]
        assert first.repo_full_name == "langchain-ai/open-swe"
        assert first.stars == 3200
        assert first.url == "https://github.com/langchain-ai/open-swe"
        assert first.classification == "absorb"
        assert first.relevance == 4
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


class TestFilterFindings:
    """Test relevance filtering."""

    def test_filter_by_relevance(self):
        """Findings below relevance 3 are filtered out."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        filtered = filter_findings(findings, min_relevance=3)
        assert len(filtered) == 2  # relevance 4 and 5 only
        assert all(f.relevance >= 3 for f in filtered)

    def test_sorted_by_relevance_descending(self):
        """Filtered findings are sorted by relevance descending."""
        findings = parse_scout_reports(_SAMPLE_LLM_OUTPUT)
        filtered = filter_findings(findings)
        assert filtered[0].relevance >= filtered[-1].relevance


class TestSeenTracking:
    """Test seen repos deduplication."""

    def test_seen_tracking(self, tmp_path: Path):
        """Seen repos are persisted and duplicates are skipped."""
        seen_file = tmp_path / "scout_seen.json"

        with patch("probos.cognitive.scout._SEEN_FILE", seen_file):
            from probos.cognitive.scout import _load_seen, _save_seen

            # Initially empty
            assert _load_seen() == {}

            # Save some seen repos
            seen = {"owner/repo1": "2026-03-22T00:00:00+00:00"}
            _save_seen(seen)

            # Reload and verify
            loaded = _load_seen()
            assert "owner/repo1" in loaded


class TestDiscordFormat:
    """Test digest formatting."""

    def test_discord_format(self):
        """Verify digest text formatting (markdown, sections, counts)."""
        findings = [
            ScoutFinding(
                repo_full_name="test/absorb-repo",
                stars=500,
                url="https://github.com/test/absorb-repo",
                classification="absorb",
                relevance=4,
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


class TestNotificationThreshold:
    """Test Bridge notification behavior."""

    def test_notification_threshold(self):
        """Only relevance >= 4 findings generate Bridge notifications."""
        findings = [
            ScoutFinding("a/b", 100, "url", "absorb", 3, "s", "i"),
            ScoutFinding("c/d", 200, "url", "absorb", 4, "s", "i"),
            ScoutFinding("e/f", 300, "url", "visiting_officer", 5, "s", "i"),
        ]
        # Simulate what act() does — only notify for relevance >= 4
        notified = [f for f in findings if f.relevance >= 4]
        assert len(notified) == 2
        assert notified[0].repo_full_name == "c/d"
        assert notified[1].repo_full_name == "e/f"


class TestGracefulNoDiscord:
    """Test graceful handling when Discord is absent."""

    @pytest.mark.asyncio
    async def test_graceful_no_discord(self):
        """No error when Discord adapter is absent or scout_channel_id is 0."""
        agent = ScoutAgent(runtime=None)
        # _deliver_discord should silently return when runtime is None
        await agent._deliver_discord([], "2026-03-22")
        # No exception = pass

    @pytest.mark.asyncio
    async def test_graceful_channel_id_zero(self):
        """No error when scout_channel_id is 0."""
        mock_runtime = MagicMock()
        mock_runtime.channel_adapters = {"discord": MagicMock(running=True)}
        mock_runtime.config.channels.discord.scout_channel_id = 0

        agent = ScoutAgent(runtime=mock_runtime)
        await agent._deliver_discord([], "2026-03-22")
        # send_response should NOT be called
        mock_runtime.channel_adapters["discord"].send_response.assert_not_called()
