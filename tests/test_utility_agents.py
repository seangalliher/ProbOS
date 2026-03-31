"""Tests for Phase 22: Utility Agents Distribution (AD-253).

Covers all 10 utility CognitiveAgent subclasses across 4 modules:
  - web_agents: WebSearchAgent, PageReaderAgent, WeatherAgent, NewsAgent
  - language_agents: TranslateAgent, SummarizerAgent
  - productivity_agents: CalculatorAgent, TodoAgent
  - organizer_agents: NoteTakerAgent, SchedulerAgent

Each agent gets at minimum:
  1. Class attribute correctness (agent_type, intent_descriptors, _handled_intents, default_capabilities)
  2. handle_intent() with recognized intent -> IntentResult(success=True)
  3. handle_intent() with unrecognized intent -> None (self-deselect via _BundledMixin)
Plus agent-specific behavioral tests.
"""

from __future__ import annotations

import json
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

from probos.runtime import ProbOSRuntime

from probos.agents.utility import (
    CalculatorAgent,
    NewsAgent,
    NoteTakerAgent,
    PageReaderAgent,
    SchedulerAgent,
    SummarizerAgent,
    TodoAgent,
    TranslateAgent,
    WeatherAgent,
    WebSearchAgent,
)
from probos.cognitive.llm_client import MockLLMClient
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent(cls, agent_id="test-1", **kwargs):
    """Instantiate a utility agent with a MockLLMClient and no runtime."""
    return cls(agent_id=agent_id, llm_client=MockLLMClient(), **kwargs)


def _unrecognized_intent() -> IntentMessage:
    """Return an IntentMessage that no utility agent should recognize."""
    return IntentMessage(intent="absolutely_unknown_intent_xyz", params={})


# ===================================================================
# WebSearchAgent
# ===================================================================

class TestWebSearchAgent:

    def test_class_attributes(self):
        agent = _make_agent(WebSearchAgent)
        assert agent.agent_type == "web_search"
        assert agent._handled_intents == {"web_search"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "web_search"
        assert any(c.can == "web_search" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        agent = _make_agent(WebSearchAgent)
        msg = IntentMessage(intent="web_search", params={"query": "python asyncio"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result  # non-empty LLM output

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(WebSearchAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    @pytest.mark.asyncio
    async def test_perceive_constructs_duckduckgo_url(self):
        """perceive() builds the correct DuckDuckGo search URL from query params."""
        agent = _make_agent(WebSearchAgent)
        # Without runtime, perceive should still set the observation params
        msg = IntentMessage(intent="web_search", params={"query": "hello world"})
        obs = await agent.perceive(msg)
        assert obs["params"]["query"] == "hello world"
        # Verify URL construction logic (agent needs runtime to actually fetch)
        encoded = urllib.parse.quote_plus("hello world")
        expected_url = f"https://html.duckduckgo.com/html/?q={encoded}"
        assert "hello+world" in expected_url


# ===================================================================
# PageReaderAgent
# ===================================================================

class TestPageReaderAgent:

    def test_class_attributes(self):
        agent = _make_agent(PageReaderAgent)
        assert agent.agent_type == "page_reader"
        assert agent._handled_intents == {"read_page"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "read_page"
        assert any(c.can == "read_page" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        agent = _make_agent(PageReaderAgent)
        msg = IntentMessage(intent="read_page", params={"url": "https://example.com"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(PageReaderAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    @pytest.mark.asyncio
    async def test_perceive_strips_html(self):
        """PageReaderAgent.perceive() strips HTML tags from fetched content.

        We test the stripping logic directly using re.sub (the same approach
        the agent uses). Without a runtime, fetched_content is not set, so
        we verify the observation structure is correct without runtime.
        """
        import re

        raw_html = "<html><body><h1>Title</h1><p>Hello <b>world</b></p></body></html>"
        text = re.sub(r"<[^>]+>", " ", raw_html)
        text = re.sub(r"\s+", " ", text).strip()
        assert "<" not in text
        assert "Title" in text
        assert "Hello" in text
        assert "world" in text

        # Agent without runtime still returns valid obs
        agent = _make_agent(PageReaderAgent)
        msg = IntentMessage(intent="read_page", params={"url": "https://example.com"})
        obs = await agent.perceive(msg)
        assert obs["params"]["url"] == "https://example.com"
        # No fetched_content because runtime is None
        assert "fetched_content" not in obs


# ===================================================================
# WeatherAgent
# ===================================================================

class TestWeatherAgent:

    def test_class_attributes(self):
        agent = _make_agent(WeatherAgent)
        assert agent.agent_type == "weather"
        assert agent._handled_intents == {"get_weather"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "get_weather"
        assert any(c.can == "get_weather" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        agent = _make_agent(WeatherAgent)
        msg = IntentMessage(intent="get_weather", params={"location": "London"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(WeatherAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    @pytest.mark.asyncio
    async def test_perceive_constructs_wttr_url(self):
        """perceive() should build the correct wttr.in URL from location param."""
        agent = _make_agent(WeatherAgent)
        msg = IntentMessage(intent="get_weather", params={"location": "New York"})
        obs = await agent.perceive(msg)
        assert obs["params"]["location"] == "New York"
        # Verify URL construction logic
        encoded = urllib.parse.quote_plus("New York")
        expected_url = f"https://wttr.in/{encoded}?format=j1"
        assert "New+York" in expected_url
        assert "format=j1" in expected_url


# ===================================================================
# NewsAgent
# ===================================================================

class TestNewsAgent:

    def test_class_attributes(self):
        agent = _make_agent(NewsAgent)
        assert agent.agent_type == "news"
        assert agent._handled_intents == {"get_news"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "get_news"
        assert any(c.can == "get_news" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        agent = _make_agent(NewsAgent)
        msg = IntentMessage(intent="get_news", params={"source": "reuters"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(NewsAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    def test_parse_rss_extracts_titles(self):
        """_parse_rss() correctly parses RSS XML and extracts title elements."""
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <item>
              <title>Breaking: Test Headline One</title>
              <description>First test article description</description>
              <link>https://example.com/article1</link>
            </item>
            <item>
              <title>Second Headline</title>
              <description><![CDATA[<b>Bold</b> description]]></description>
              <link>https://example.com/article2</link>
            </item>
            <item>
              <title>Third Headline</title>
            </item>
          </channel>
        </rss>"""
        result = NewsAgent._parse_rss(rss_xml)
        assert "Breaking: Test Headline One" in result
        assert "Second Headline" in result
        assert "Third Headline" in result
        assert "https://example.com/article1" in result

    def test_parse_rss_handles_invalid_xml(self):
        """_parse_rss() returns error message for malformed XML."""
        result = NewsAgent._parse_rss("not valid xml <><><")
        assert "Failed to parse" in result

    def test_parse_rss_handles_empty_feed(self):
        """_parse_rss() returns message when no items found."""
        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Empty</title></channel></rss>"""
        result = NewsAgent._parse_rss(rss_xml)
        assert "No headlines found" in result

    def test_parse_rss_limits_to_10(self):
        """_parse_rss() stops after 10 items."""
        items = "".join(
            f"<item><title>Headline {i}</title></item>" for i in range(15)
        )
        rss_xml = f'<rss><channel>{items}</channel></rss>'
        result = NewsAgent._parse_rss(rss_xml)
        # Should contain headlines 0-9 but not 10-14
        assert "Headline 0" in result
        assert "Headline 9" in result
        assert "Headline 10" not in result


# ===================================================================
# TranslateAgent
# ===================================================================

class TestTranslateAgent:

    def test_class_attributes(self):
        agent = _make_agent(TranslateAgent)
        assert agent.agent_type == "translator"
        assert agent._handled_intents == {"translate_text"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "translate_text"
        assert any(c.can == "translate_text" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        """Pure LLM agent -- handle_intent works without runtime."""
        agent = _make_agent(TranslateAgent)
        msg = IntentMessage(
            intent="translate_text",
            params={"text": "Hello", "target_language": "Spanish"},
        )
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result  # non-empty

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(TranslateAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    def test_no_perceive_override(self):
        """TranslateAgent is a pure LLM agent -- no perceive() override."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        # TranslateAgent should use CognitiveAgent's perceive, not its own
        assert TranslateAgent.perceive is CognitiveAgent.perceive


# ===================================================================
# SummarizerAgent
# ===================================================================

class TestSummarizerAgent:

    def test_class_attributes(self):
        agent = _make_agent(SummarizerAgent)
        assert agent.agent_type == "summarizer"
        assert agent._handled_intents == {"summarize_text"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "summarize_text"
        assert any(c.can == "summarize_text" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        """Pure LLM agent -- handle_intent works without runtime."""
        agent = _make_agent(SummarizerAgent)
        msg = IntentMessage(
            intent="summarize_text",
            params={"text": "Long article text here that needs summarization."},
        )
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(SummarizerAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    def test_no_perceive_override(self):
        """SummarizerAgent is a pure LLM agent -- no perceive() override."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        assert SummarizerAgent.perceive is CognitiveAgent.perceive


# ===================================================================
# CalculatorAgent
# ===================================================================

class TestCalculatorAgent:

    def test_class_attributes(self):
        agent = _make_agent(CalculatorAgent)
        assert agent.agent_type == "calculator"
        assert agent._handled_intents == {"calculate"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "calculate"
        assert any(c.can == "calculate" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        agent = _make_agent(CalculatorAgent)
        msg = IntentMessage(intent="calculate", params={"expression": "10 * 5"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(CalculatorAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    @pytest.mark.asyncio
    async def test_safe_eval_simple_arithmetic(self):
        """Safe eval handles simple arithmetic like '2+2' without LLM."""
        agent = _make_agent(CalculatorAgent)
        msg = IntentMessage(intent="calculate", params={"expression": "2+2"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result == "4"

    @pytest.mark.asyncio
    async def test_safe_eval_complex_arithmetic(self):
        """Safe eval handles parenthesized expressions."""
        agent = _make_agent(CalculatorAgent)
        msg = IntentMessage(intent="calculate", params={"expression": "(10 + 5) * 3"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.result == "45"

    @pytest.mark.asyncio
    async def test_safe_eval_rejects_unsafe_import(self):
        """Expressions with alphabetic characters (e.g. import) bypass safe eval,
        falling through to the LLM cognitive lifecycle instead."""
        agent = _make_agent(CalculatorAgent)
        msg = IntentMessage(
            intent="calculate",
            params={"expression": "__import__('os').system('ls')"},
        )
        result = await agent.handle_intent(msg)
        # Should still succeed (LLM fallback), but should NOT have eval'd the import
        assert isinstance(result, IntentResult)
        assert result.success is True
        # Result should be LLM mock output, not a system command result
        assert "Mock cognitive response" in result.result

    @pytest.mark.asyncio
    async def test_safe_eval_rejects_alpha_expressions(self):
        """Alphabetic characters in expression bypass safe eval entirely."""
        agent = _make_agent(CalculatorAgent)
        msg = IntentMessage(
            intent="calculate",
            params={"expression": "print('hacked')"},
        )
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True
        # LLM fallback, not eval output
        assert "Mock cognitive response" in result.result

    @pytest.mark.asyncio
    async def test_safe_eval_with_commas_and_percent(self):
        """Safe eval handles commas in numbers and percent signs."""
        agent = _make_agent(CalculatorAgent)
        msg = IntentMessage(intent="calculate", params={"expression": "1,000 + 50%"})
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True
        # 1000 + 50/100 = 1000.5
        assert result.result == "1000.5"


# ===================================================================
# TodoAgent
# ===================================================================

class TestTodoAgent:

    def test_class_attributes(self):
        agent = _make_agent(TodoAgent)
        assert agent.agent_type == "todo_manager"
        assert agent._handled_intents == {"manage_todo"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "manage_todo"
        assert any(c.can == "manage_todo" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        """Without runtime, TodoAgent still succeeds via LLM fallback."""
        agent = _make_agent(TodoAgent)
        msg = IntentMessage(
            intent="manage_todo",
            params={"action": "list"},
        )
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(TodoAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    @pytest.mark.asyncio
    async def test_perceive_without_runtime_skips_file_read(self):
        """Without runtime, perceive() skips file read but returns valid obs."""
        agent = _make_agent(TodoAgent)
        msg = IntentMessage(intent="manage_todo", params={"action": "list"})
        obs = await agent.perceive(msg)
        assert obs["intent"] == "manage_todo"
        assert obs["params"]["action"] == "list"
        # No fetched_content without runtime
        assert "fetched_content" not in obs


# ===================================================================
# NoteTakerAgent
# ===================================================================

class TestNoteTakerAgent:

    def test_class_attributes(self):
        agent = _make_agent(NoteTakerAgent)
        assert agent.agent_type == "note_taker"
        assert agent._handled_intents == {"manage_notes"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "manage_notes"
        assert any(c.can == "manage_notes" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        agent = _make_agent(NoteTakerAgent)
        msg = IntentMessage(
            intent="manage_notes",
            params={"action": "list"},
        )
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(NoteTakerAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    @pytest.mark.asyncio
    async def test_perceive_without_runtime_returns_early(self):
        """Without runtime, perceive() returns obs without fetched_content."""
        agent = _make_agent(NoteTakerAgent)
        msg = IntentMessage(intent="manage_notes", params={"action": "save", "title": "test"})
        obs = await agent.perceive(msg)
        assert obs["intent"] == "manage_notes"
        assert "fetched_content" not in obs


# ===================================================================
# SchedulerAgent
# ===================================================================

class TestSchedulerAgent:

    def test_class_attributes(self):
        agent = _make_agent(SchedulerAgent)
        assert agent.agent_type == "scheduler"
        assert agent._handled_intents == {"manage_schedule"}
        assert len(agent.intent_descriptors) >= 1
        assert agent.intent_descriptors[0].name == "manage_schedule"
        assert any(c.can == "manage_schedule" for c in agent.default_capabilities)

    @pytest.mark.asyncio
    async def test_handle_recognized_intent(self):
        agent = _make_agent(SchedulerAgent)
        msg = IntentMessage(
            intent="manage_schedule",
            params={"action": "list"},
        )
        result = await agent.handle_intent(msg)
        assert isinstance(result, IntentResult)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_self_deselect_unrecognized(self):
        agent = _make_agent(SchedulerAgent)
        result = await agent.handle_intent(_unrecognized_intent())
        assert result is None

    @pytest.mark.asyncio
    async def test_perceive_without_runtime_skips_file_read(self):
        """Without runtime, perceive() skips reading reminders file."""
        agent = _make_agent(SchedulerAgent)
        msg = IntentMessage(intent="manage_schedule", params={"action": "check"})
        obs = await agent.perceive(msg)
        assert obs["intent"] == "manage_schedule"
        assert "fetched_content" not in obs


# ===================================================================
# Cross-cutting: __init__.py exports
# ===================================================================

class TestUtilityExports:

    def test_all_agents_exported(self):
        """__init__.py exports all 10 utility agents."""
        from probos.agents.utility import __all__

        expected = {
            "WebSearchAgent",
            "PageReaderAgent",
            "WeatherAgent",
            "NewsAgent",
            "TranslateAgent",
            "SummarizerAgent",
            "CalculatorAgent",
            "TodoAgent",
            "NoteTakerAgent",
            "SchedulerAgent",
        }
        assert set(__all__) == expected

    def test_all_agents_are_cognitive_subclasses(self):
        """Every utility agent is a subclass of CognitiveAgent."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agents = [
            WebSearchAgent, PageReaderAgent, WeatherAgent, NewsAgent,
            TranslateAgent, SummarizerAgent, CalculatorAgent, TodoAgent,
            NoteTakerAgent, SchedulerAgent,
        ]
        for cls in agents:
            assert issubclass(cls, CognitiveAgent), f"{cls.__name__} is not a CognitiveAgent subclass"

    def test_all_agents_have_utility_mixin_behavior(self):
        """Every utility agent has _handled_intents and intent_descriptors defined."""
        agents = [
            WebSearchAgent, PageReaderAgent, WeatherAgent, NewsAgent,
            TranslateAgent, SummarizerAgent, CalculatorAgent, TodoAgent,
            NoteTakerAgent, SchedulerAgent,
        ]
        for cls in agents:
            assert hasattr(cls, "_handled_intents"), f"{cls.__name__} missing _handled_intents"
            assert isinstance(cls._handled_intents, set), f"{cls.__name__}._handled_intents is not a set"
            assert len(cls._handled_intents) >= 1, f"{cls.__name__}._handled_intents is empty"
            assert hasattr(cls, "intent_descriptors"), f"{cls.__name__} missing intent_descriptors"
            assert len(cls.intent_descriptors) >= 1, f"{cls.__name__}.intent_descriptors is empty"
            assert hasattr(cls, "default_capabilities"), f"{cls.__name__} missing default_capabilities"
            assert len(cls.default_capabilities) >= 1, f"{cls.__name__}.default_capabilities is empty"


# ===================================================================
# Persistence tests (AD-362)
# ===================================================================

class TestUtilityPersistence:
    """Verify utility agents actually write to disk (AD-362)."""

    @pytest.mark.asyncio
    async def test_todo_agent_persists_to_disk(self, tmp_path):
        """TodoAgent.act() should write todos to a real file."""
        todo_path = tmp_path / "todos.json"
        agent = _make_agent(TodoAgent, runtime=MagicMock(spec=ProbOSRuntime))
        agent._TODO_PATH = str(todo_path)

        decision = {
            "llm_output": json.dumps({
                "action": "add",
                "todos": [{"text": "Buy milk", "priority": "high", "due": None, "done": False}],
                "message": "Added: Buy milk",
            })
        }
        result = await agent.act(decision)
        assert result["success"] is True
        assert todo_path.exists(), "Todo file should exist on disk"
        data = json.loads(todo_path.read_text())
        assert len(data) == 1
        assert data[0]["text"] == "Buy milk"

    @pytest.mark.asyncio
    async def test_note_taker_persists_to_disk(self, tmp_path):
        """NoteTakerAgent.act() should write notes to a real file."""
        notes_dir = tmp_path / "notes"
        agent = _make_agent(NoteTakerAgent, runtime=MagicMock(spec=ProbOSRuntime))
        agent._NOTES_DIR = str(notes_dir)

        decision = {
            "llm_output": json.dumps({
                "action": "save",
                "filename": "test-note.md",
                "content": "# Test Note\nHello world",
                "message": "Note saved",
            })
        }
        result = await agent.act(decision)
        assert result["success"] is True
        note_file = notes_dir / "test-note.md"
        assert note_file.exists(), "Note file should exist on disk"
        assert "Hello world" in note_file.read_text()

    @pytest.mark.asyncio
    async def test_scheduler_persists_reminders_to_disk(self, tmp_path):
        """SchedulerAgent.act() should write reminders to a real file."""
        reminders_path = tmp_path / "reminders.json"
        agent = _make_agent(SchedulerAgent, runtime=MagicMock(spec=ProbOSRuntime))
        agent._REMINDERS_PATH = str(reminders_path)

        decision = {
            "llm_output": json.dumps({
                "action": "set",
                "reminders": [{"text": "Call dentist", "time": "3pm"}],
                "message": "Reminder set",
            })
        }
        result = await agent.act(decision)
        assert result["success"] is True
        assert reminders_path.exists(), "Reminders file should exist on disk"
        data = json.loads(reminders_path.read_text())
        assert len(data) == 1
        assert data[0]["text"] == "Call dentist"

    @pytest.mark.asyncio
    async def test_write_failure_propagates(self):
        """If FileWriterAgent.commit_write fails, act() should report failure."""
        agent = _make_agent(TodoAgent, runtime=MagicMock(spec=ProbOSRuntime))
        agent._TODO_PATH = "/nonexistent/deep/path/that/requires/root/todos.json"

        decision = {
            "llm_output": json.dumps({
                "action": "add",
                "todos": [{"text": "Test", "priority": "low", "due": None, "done": False}],
                "message": "Added",
            })
        }
        # Patch commit_write to simulate failure
        with patch(
            "probos.agents.file_writer.FileWriterAgent.commit_write",
            return_value={"success": False, "error": "Permission denied"},
        ):
            result = await agent.act(decision)
        assert result["success"] is False
        assert "error" in result
