"""BF-208: Scout Duty-Triggered Perceive Fix — Tests.

Verifies that perceive() correctly handles duty-triggered proactive_think
by falling through to the GitHub search pipeline, while preserving
interactive scout_search and scout_report cache paths.
"""

import pytest
from unittest.mock import AsyncMock, patch


from probos.cognitive.scout import ScoutAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_REPO = {
    "full_name": "test-org/cool-agent",
    "description": "A cool agent framework",
    "stargazers_count": 500,
    "created_at": "2026-04-01T00:00:00Z",
    "updated_at": "2026-04-15T00:00:00Z",
    "language": "Python",
    "license": {"spdx_id": "MIT"},
    "topics": ["ai-agents", "llm"],
    "html_url": "https://github.com/test-org/cool-agent",
}


def _make_scout() -> ScoutAgent:
    scout = ScoutAgent(agent_id="test-scout")
    scout.callsign = "Wesley"
    return scout


# ---------------------------------------------------------------------------
# Test 1: Duty-triggered perceive runs search
# ---------------------------------------------------------------------------

class TestDutyTriggeredPerceive:

    @pytest.mark.asyncio
    async def test_duty_triggered_perceive_runs_search(self):
        """proactive_think with duty_id=scout_report triggers GitHub search."""
        scout = _make_scout()

        with (
            patch(
                "probos.cognitive.cognitive_agent.CognitiveAgent.perceive",
                new_callable=AsyncMock,
            ) as mock_perceive,
            patch.object(scout, "_search_github", new_callable=AsyncMock) as mock_search,
            patch("probos.cognitive.scout._load_seen", return_value={}),
            patch("probos.cognitive.scout._save_seen"),
        ):
            mock_perceive.return_value = {
                "intent": "proactive_think",
                "params": {
                    "duty": {
                        "duty_id": "scout_report",
                        "description": "Perform a comprehensive review",
                    },
                },
                "context": "",
            }
            mock_search.return_value = [SAMPLE_REPO]

            result = await scout.perceive({"intent": "proactive_think"})

        assert "Classify these" in result["context"]
        assert "test-org/cool-agent" in result["context"]

    @pytest.mark.asyncio
    async def test_non_scout_duty_does_not_trigger_search(self):
        """proactive_think with duty_id != scout_report does NOT search."""
        scout = _make_scout()

        with patch(
            "probos.cognitive.cognitive_agent.CognitiveAgent.perceive",
            new_callable=AsyncMock,
        ) as mock_perceive:
            mock_perceive.return_value = {
                "intent": "proactive_think",
                "params": {
                    "duty": {
                        "duty_id": "watch_report",
                        "description": "Something else",
                    },
                },
                "context": "",
            }

            result = await scout.perceive({"intent": "proactive_think"})

        assert "Classify these" not in result.get("context", "")

    @pytest.mark.asyncio
    async def test_proactive_think_without_duty_stays_silent(self):
        """proactive_think with no duty returns early (no search)."""
        scout = _make_scout()

        with patch(
            "probos.cognitive.cognitive_agent.CognitiveAgent.perceive",
            new_callable=AsyncMock,
        ) as mock_perceive:
            mock_perceive.return_value = {
                "intent": "proactive_think",
                "params": {"duty": None},
                "context": "",
            }

            result = await scout.perceive({"intent": "proactive_think"})

        assert "Classify these" not in result.get("context", "")


# ---------------------------------------------------------------------------
# Test 4: Interactive scout_search still works
# ---------------------------------------------------------------------------

class TestInteractivePath:

    @pytest.mark.asyncio
    async def test_interactive_scout_search_still_works(self):
        """scout_search intent triggers search pipeline as before."""
        scout = _make_scout()

        with (
            patch(
                "probos.cognitive.cognitive_agent.CognitiveAgent.perceive",
                new_callable=AsyncMock,
            ) as mock_perceive,
            patch.object(scout, "_search_github", new_callable=AsyncMock) as mock_search,
            patch("probos.cognitive.scout._load_seen", return_value={}),
            patch("probos.cognitive.scout._save_seen"),
        ):
            mock_perceive.return_value = {
                "intent": "scout_search",
                "params": {},
                "context": "",
            }
            mock_search.return_value = [SAMPLE_REPO]

            result = await scout.perceive({"intent": "scout_search"})

        assert "Classify these" in result["context"]
        assert "test-org/cool-agent" in result["context"]


# ---------------------------------------------------------------------------
# Test 5: scout_report cache path still works
# ---------------------------------------------------------------------------

class TestCachePath:

    @pytest.mark.asyncio
    async def test_scout_report_cache_still_works(self):
        """scout_report intent returns cached report text."""
        scout = _make_scout()

        with (
            patch(
                "probos.cognitive.cognitive_agent.CognitiveAgent.perceive",
                new_callable=AsyncMock,
            ) as mock_perceive,
            patch.object(scout, "_load_latest_report", return_value="Cached scout digest here"),
        ):
            mock_perceive.return_value = {
                "intent": "scout_report",
                "params": {},
                "context": "",
            }

            result = await scout.perceive({"intent": "scout_report"})

        assert result["context"] == "Cached scout digest here"
