"""Tests for ResearchPhase — Phase 11 Part C."""

from __future__ import annotations

import urllib.parse

import pytest

from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.research import ResearchPhase
from probos.config import SelfModConfig
from probos.types import IntentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides) -> SelfModConfig:
    """Create a SelfModConfig with research enabled."""
    defaults = {
        "enabled": True,
        "research_enabled": True,
        "research_max_pages": 3,
        "research_max_content_per_page": 2000,
    }
    defaults.update(overrides)
    return SelfModConfig(**defaults)


async def _mock_submit_success(intent, params=None, **kwargs):
    """Mock submit_intent that returns successful fetch results."""
    return [
        IntentResult(
            intent_id="test",
            agent_id="http_agent",
            success=True,
            result={"body": "Python json module: json.loads() json.dumps() example code"},
        )
    ]


async def _mock_submit_failure(intent, params=None, **kwargs):
    """Mock submit_intent that returns failed fetch results."""
    return [
        IntentResult(
            intent_id="test",
            agent_id="http_agent",
            success=False,
            error="Network error",
        )
    ]


async def _mock_submit_empty(intent, params=None, **kwargs):
    """Mock submit_intent that returns empty results."""
    return []


# ---------------------------------------------------------------------------
# ResearchPhase tests
# ---------------------------------------------------------------------------


class TestResearchPhase:
    """Tests for ResearchPhase."""

    @pytest.mark.asyncio
    async def test_research_returns_synthesis_on_success(self):
        """research returns synthesis string on success."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        result = await research.research(
            "translate_text", "Translate text between languages",
            {"text": "source text"},
        )
        assert result != "No research available."
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_research_returns_fallback_on_network_failure(self):
        """research returns 'No research available.' on network failure."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_failure, config)

        result = await research.research(
            "translate_text", "Translate text", {},
        )
        assert result == "No research available."

    @pytest.mark.asyncio
    async def test_research_returns_fallback_on_empty_content(self):
        """research returns 'No research available.' on empty content."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_empty, config)

        result = await research.research(
            "translate_text", "Translate text", {},
        )
        assert result == "No research available."

    @pytest.mark.asyncio
    async def test_generate_queries_returns_list(self):
        """_generate_queries returns list of strings."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        queries = await research._generate_queries(
            "translate_text", "Translate text", {},
        )
        assert isinstance(queries, list)
        assert len(queries) > 0
        assert all(isinstance(q, str) for q in queries)

    @pytest.mark.asyncio
    async def test_generate_queries_handles_malformed_response(self):
        """_generate_queries handles malformed LLM response gracefully."""
        from probos.types import LLMResponse

        class BadLLMClient(MockLLMClient):
            async def complete(self, request):
                return LLMResponse(content="not valid json", model="mock")

        config = _make_config()
        research = ResearchPhase(BadLLMClient(), _mock_submit_success, config)

        queries = await research._generate_queries(
            "translate_text", "Translate text", {},
        )
        assert isinstance(queries, list)
        assert len(queries) == 0

    def test_queries_to_urls_uses_urllib_parse(self):
        """_queries_to_urls uses urllib.parse (no raw string concat)."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        urls = research._queries_to_urls(["python json parsing"])
        assert len(urls) > 0
        for url in urls:
            # Verify the URL is properly encoded
            parsed = urllib.parse.urlparse(url)
            assert parsed.scheme == "https"
            # Query parameter should be properly encoded
            assert "q=" in url

    def test_queries_to_urls_filters_non_whitelisted_domains(self):
        """_queries_to_urls filters non-whitelisted domains."""
        # Config with a restricted whitelist
        config = _make_config(research_domain_whitelist=["docs.python.org"])
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        urls = research._queries_to_urls(["python json"])
        for url in urls:
            parsed = urllib.parse.urlparse(url)
            assert "docs.python.org" in parsed.netloc

    def test_queries_to_urls_returns_empty_for_empty_queries(self):
        """_queries_to_urls returns empty list for empty queries."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        urls = research._queries_to_urls([])
        assert urls == []

    def test_queries_to_urls_caps_at_max_pages(self):
        """_queries_to_urls caps total URLs at research_max_pages."""
        config = _make_config(research_max_pages=2)
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        urls = research._queries_to_urls(["query1", "query2", "query3"])
        assert len(urls) <= 2

    @pytest.mark.asyncio
    async def test_fetch_pages_truncates_content(self):
        """_fetch_pages truncates content to max chars."""
        config = _make_config(research_max_content_per_page=10)
        llm = MockLLMClient()

        async def long_content_submit(intent, params=None, **kwargs):
            return [
                IntentResult(
                    intent_id="test",
                    agent_id="http_agent",
                    success=True,
                    result={"body": "x" * 1000},
                )
            ]

        research = ResearchPhase(llm, long_content_submit, config)

        results = await research._fetch_pages(["https://example.com"])
        assert len(results) == 1
        assert len(results[0]["content"]) <= 10

    @pytest.mark.asyncio
    async def test_fetch_pages_handles_failed_fetches(self):
        """_fetch_pages handles failed fetches."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_failure, config)

        results = await research._fetch_pages(["https://example.com"])
        assert len(results) == 1
        assert results[0]["success"] is False

    @pytest.mark.asyncio
    async def test_synthesize_passes_content_to_llm(self):
        """_synthesize passes content to LLM."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        result = await research._synthesize(
            "translate_text", "Translate text",
            [{"url": "https://example.com", "content": "some docs", "success": True}],
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_synthesize_handles_no_useful_docs(self):
        """_synthesize handles 'no useful docs' response."""
        from probos.types import LLMResponse

        class NoDocsLLMClient(MockLLMClient):
            async def complete(self, request):
                if "DOCUMENTATION FETCHED:" in request.prompt:
                    return LLMResponse(content="No useful documentation found.", model="mock")
                return await super().complete(request)

        config = _make_config()
        research = ResearchPhase(NoDocsLLMClient(), _mock_submit_success, config)

        result = await research._synthesize(
            "translate_text", "Translate text",
            [{"url": "https://example.com", "content": "irrelevant", "success": True}],
        )
        assert "No useful documentation found" in result

    @pytest.mark.asyncio
    async def test_full_research_flow(self):
        """Full research flow: queries -> URLs -> fetch -> synthesize."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        result = await research.research(
            "json_parser", "Parse JSON data", {"data": "input"},
        )
        # Should have successfully synthesized something
        assert result != "No research available."

    @pytest.mark.asyncio
    async def test_research_context_in_design_prompt(self):
        """Research context injected into design prompt."""
        from probos.cognitive.agent_designer import AgentDesigner

        config = _make_config()
        llm = MockLLMClient()
        designer = AgentDesigner(llm, config)

        # Should not raise — the prompt template now includes {research_context}
        source = await designer.design_agent(
            intent_name="test_intent",
            intent_description="Test",
            parameters={"x": "y"},
            research_context="Use the json module for parsing.",
        )
        assert "class TestIntentAgent" in source

    @pytest.mark.asyncio
    async def test_pipeline_research_disabled_skips(self):
        """Pipeline with research_enabled=False skips research."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.self_mod import SelfModificationPipeline

        config = SelfModConfig(enabled=True, research_enabled=False)
        llm = MockLLMClient()

        # Create a research instance that would fail if called
        class FailingResearch:
            async def research(self, *args, **kwargs):
                raise AssertionError("Research should not be called!")

        import asyncio
        pipeline = SelfModificationPipeline(
            designer=AgentDesigner(llm, config),
            validator=CodeValidator(config),
            sandbox=SandboxRunner(config, llm_client=llm),
            monitor=BehavioralMonitor(),
            config=config,
            register_fn=lambda x: asyncio.sleep(0),
            create_pool_fn=lambda *a: asyncio.sleep(0),
            set_trust_fn=lambda *a: asyncio.sleep(0),
            research=FailingResearch(),
        )

        # Should succeed without calling research (research_enabled=False)
        record = await pipeline.handle_unhandled_intent(
            intent_name="test_intent",
            intent_description="Test intent",
            parameters={"x": "y"},
        )
        assert record is not None
        assert record.status == "active"

    @pytest.mark.asyncio
    async def test_pipeline_research_enabled_includes_context(self):
        """Pipeline with research_enabled=True includes context."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.self_mod import SelfModificationPipeline

        config = SelfModConfig(enabled=True, research_enabled=True)
        llm = MockLLMClient()

        research_called = False

        class MockResearch:
            async def research(self, *args, **kwargs):
                nonlocal research_called
                research_called = True
                return "Use json.loads() to parse JSON data."

        import asyncio
        pipeline = SelfModificationPipeline(
            designer=AgentDesigner(llm, config),
            validator=CodeValidator(config),
            sandbox=SandboxRunner(config, llm_client=llm),
            monitor=BehavioralMonitor(),
            config=config,
            register_fn=lambda x: asyncio.sleep(0),
            create_pool_fn=lambda *a: asyncio.sleep(0),
            set_trust_fn=lambda *a: asyncio.sleep(0),
            research=MockResearch(),
        )

        record = await pipeline.handle_unhandled_intent(
            intent_name="json_parser",
            intent_description="Parse JSON data",
            parameters={"data": "input"},
        )
        assert research_called is True
        assert record is not None


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


class TestResearchSecurity:
    """Security tests for web research."""

    def test_urls_use_urllib_parse_urlencode(self):
        """URLs use urllib.parse.urlencode."""
        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        urls = research._queries_to_urls(["test query with spaces"])
        for url in urls:
            # Should be properly encoded - no raw spaces
            assert " " not in url
            assert "q=test" in url

    def test_non_whitelisted_domain_urls_filtered(self):
        """Non-whitelisted domain URLs are filtered out."""
        config = _make_config(research_domain_whitelist=["docs.python.org"])
        llm = MockLLMClient()
        research = ResearchPhase(llm, _mock_submit_success, config)

        urls = research._queries_to_urls(["test"])
        for url in urls:
            parsed = urllib.parse.urlparse(url)
            assert parsed.netloc == "docs.python.org"

    @pytest.mark.asyncio
    async def test_content_truncation(self):
        """Content exceeding max_content_per_page is truncated."""
        config = _make_config(research_max_content_per_page=50)
        llm = MockLLMClient()

        async def big_content(intent, params=None, **kwargs):
            return [
                IntentResult(
                    intent_id="test",
                    agent_id="http_agent",
                    success=True,
                    result={"body": "A" * 5000},
                )
            ]

        research = ResearchPhase(llm, big_content, config)
        results = await research._fetch_pages(["https://docs.python.org/test"])
        assert len(results[0]["content"]) <= 50

    @pytest.mark.asyncio
    async def test_fetch_goes_through_consensus(self):
        """Fetch goes through submit_intent (which uses consensus)."""
        submitted_intents = []

        async def tracking_submit(intent, params=None, **kwargs):
            submitted_intents.append({"intent": intent, "params": params})
            return [
                IntentResult(
                    intent_id="test",
                    agent_id="http_agent",
                    success=True,
                    result={"body": "content"},
                )
            ]

        config = _make_config()
        llm = MockLLMClient()
        research = ResearchPhase(llm, tracking_submit, config)

        await research._fetch_pages(["https://docs.python.org/test"])
        assert len(submitted_intents) == 1
        assert submitted_intents[0]["intent"] == "http_fetch"
