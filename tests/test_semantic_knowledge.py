"""Tests for Phase 21 — Semantic Knowledge Layer + Phase 20 cleanup (AD-246)."""

from __future__ import annotations

import json
import time
from io import StringIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.agents.introspect import IntrospectionAgent
from probos.cognitive.emergent_detector import EmergentDetector
from probos.cognitive.llm_client import MockLLMClient
from probos.consensus.trust import TrustNetwork
from probos.experience.panels import render_search_panel
from probos.experience.shell import ProbOSShell
from probos.knowledge.semantic import SemanticKnowledgeLayer
from probos.mesh.routing import HebbianRouter, REL_INTENT
from probos.substrate.identity import (
    _ID_REGISTRY,
    generate_agent_id,
    parse_agent_id,
)
from probos.types import LLMRequest


# ===========================================================================
# Phase 20 cleanup tests (AD-241)
# ===========================================================================


class TestParseAgentId:
    def test_simple_id_via_registry(self) -> None:
        """parse_agent_id returns correct components for a registry-generated ID."""
        agent_id = generate_agent_id("file_reader", "filesystem", 0)
        parsed = parse_agent_id(agent_id)
        assert parsed is not None
        assert parsed["agent_type"] == "file_reader"
        assert parsed["pool_name"] == "filesystem"
        assert parsed["index"] == "0"

    def test_compound_pool_via_registry(self) -> None:
        """parse_agent_id handles compound pool names like 'filesystem_writers'."""
        agent_id = generate_agent_id("file_writer", "filesystem_writers", 1)
        parsed = parse_agent_id(agent_id)
        assert parsed is not None
        assert parsed["agent_type"] == "file_writer"
        assert parsed["pool_name"] == "filesystem_writers"
        assert parsed["index"] == "1"

    def test_fallback_hash_verification(self) -> None:
        """parse_agent_id falls back to hash verification for IDs not in registry."""
        # Generate an ID, remove from registry, then parse
        agent_id = generate_agent_id("shell_command", "shell", 2)
        _ID_REGISTRY.pop(agent_id, None)
        parsed = parse_agent_id(agent_id)
        assert parsed is not None
        assert parsed["pool_name"] == "shell"
        assert parsed["agent_type"] == "shell_command"

    def test_non_deterministic_uuid_returns_none(self) -> None:
        """parse_agent_id returns None for UUIDs that don't match the format."""
        parsed = parse_agent_id("abc123-def456-ghi789")
        assert parsed is None


class TestAllPatternsCap:
    def test_all_patterns_capped_at_500(self) -> None:
        """EmergentDetector._all_patterns stays bounded after many analyze() calls."""
        router = MagicMock()
        router.all_weights_typed.return_value = {}
        trust = MagicMock()
        trust.raw_scores.return_value = {}
        d = EmergentDetector(
            hebbian_router=router,
            trust_network=trust,
        )
        from probos.cognitive.emergent_detector import EmergentPattern

        # Manually add > 500 patterns
        for i in range(600):
            d._all_patterns.append(EmergentPattern(
                pattern_type="test",
                description=f"pattern {i}",
                confidence=0.5,
            ))
        # Run analyze — should cap
        d.analyze()
        assert len(d._all_patterns) <= 500


# ===========================================================================
# SemanticKnowledgeLayer lifecycle tests
# ===========================================================================


class TestSemanticKnowledgeLayerLifecycle:
    @pytest.fixture
    def layer(self, tmp_path):
        return SemanticKnowledgeLayer(db_path=tmp_path / "semantic")

    @pytest.mark.asyncio
    async def test_start_creates_collections(self, layer) -> None:
        await layer.start()
        try:
            assert len(layer._collections) == 5
            assert "agents" in layer._collections
            assert "skills" in layer._collections
            assert "workflows" in layer._collections
            assert "qa_reports" in layer._collections
            assert "events" in layer._collections
        finally:
            await layer.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, layer) -> None:
        await layer.start()
        await layer.stop()
        assert layer._client is None
        assert len(layer._collections) == 0

    @pytest.mark.asyncio
    async def test_stats_returns_counts(self, layer) -> None:
        await layer.start()
        try:
            stats = layer.stats()
            assert isinstance(stats, dict)
            for name in ("agents", "skills", "workflows", "qa_reports", "events"):
                assert name in stats
                assert stats[name] == 0
        finally:
            await layer.stop()


# ===========================================================================
# Agent indexing tests
# ===========================================================================


class TestAgentIndexing:
    @pytest.fixture
    async def layer(self, tmp_path):
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        yield l
        await l.stop()

    @pytest.mark.asyncio
    async def test_index_agent_stores_document(self, layer) -> None:
        await layer.index_agent(
            agent_type="news_fetcher",
            intent_name="fetch_news",
            description="Fetches news from RSS feeds",
            strategy="new_agent",
        )
        assert layer._collections["agents"].count() == 1

    @pytest.mark.asyncio
    async def test_index_agent_metadata(self, layer) -> None:
        await layer.index_agent(
            agent_type="news_fetcher",
            intent_name="fetch_news",
            description="Fetches news from RSS feeds",
            strategy="new_agent",
        )
        result = layer._collections["agents"].get(ids=["agent_news_fetcher"])
        assert result["metadatas"][0]["agent_type"] == "news_fetcher"
        assert result["metadatas"][0]["intent_name"] == "fetch_news"

    @pytest.mark.asyncio
    async def test_index_agent_idempotent(self, layer) -> None:
        for _ in range(3):
            await layer.index_agent(
                agent_type="news_fetcher",
                intent_name="fetch_news",
                description="Fetches news",
                strategy="new_agent",
            )
        assert layer._collections["agents"].count() == 1

    @pytest.mark.asyncio
    async def test_multiple_agents_searchable(self, layer) -> None:
        await layer.index_agent("text_analyzer", "analyze_text", "Analyze text content", "new_agent")
        await layer.index_agent("image_proc", "process_image", "Process images", "new_agent")
        results = layer._collections["agents"].query(query_texts=["text analysis"], n_results=2)
        assert len(results["ids"][0]) >= 1


# ===========================================================================
# Skill indexing tests
# ===========================================================================


class TestSkillIndexing:
    @pytest.fixture
    async def layer(self, tmp_path):
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        yield l
        await l.stop()

    @pytest.mark.asyncio
    async def test_index_skill_stores_document(self, layer) -> None:
        await layer.index_skill("count_words", "Count words in text", target_agent="text_agent")
        assert layer._collections["skills"].count() == 1

    @pytest.mark.asyncio
    async def test_index_skill_metadata(self, layer) -> None:
        await layer.index_skill("count_words", "Count words in text", target_agent="text_agent")
        result = layer._collections["skills"].get(ids=["skill_count_words"])
        assert result["metadatas"][0]["intent_name"] == "count_words"
        assert result["metadatas"][0]["target_agent"] == "text_agent"

    @pytest.mark.asyncio
    async def test_skill_searchable(self, layer) -> None:
        await layer.index_skill("count_words", "Count words in text paragraphs")
        results = layer._collections["skills"].query(query_texts=["word counting"], n_results=1)
        assert len(results["ids"][0]) >= 1


# ===========================================================================
# Workflow indexing tests
# ===========================================================================


class TestWorkflowIndexing:
    @pytest.fixture
    async def layer(self, tmp_path):
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        yield l
        await l.stop()

    @pytest.mark.asyncio
    async def test_index_workflow_stores_document(self, layer) -> None:
        await layer.index_workflow("read a file", ["read_file"], hit_count=5)
        assert layer._collections["workflows"].count() == 1

    @pytest.mark.asyncio
    async def test_index_workflow_metadata(self, layer) -> None:
        await layer.index_workflow("read a file", ["read_file"], hit_count=5)
        result = layer._collections["workflows"].get(ids=["workflow_read a file"])
        assert result["metadatas"][0]["intent_count"] == 1
        assert result["metadatas"][0]["hit_count"] == 5

    @pytest.mark.asyncio
    async def test_workflow_searchable(self, layer) -> None:
        await layer.index_workflow("read a file and show it", ["read_file", "stat_file"])
        results = layer._collections["workflows"].query(query_texts=["file reading"], n_results=1)
        assert len(results["ids"][0]) >= 1


# ===========================================================================
# QA report indexing tests
# ===========================================================================


class TestQAReportIndexing:
    @pytest.fixture
    async def layer(self, tmp_path):
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        yield l
        await l.stop()

    @pytest.mark.asyncio
    async def test_index_qa_report_stores(self, layer) -> None:
        await layer.index_qa_report("news_fetcher", "PASS", 1.0)
        assert layer._collections["qa_reports"].count() == 1

    @pytest.mark.asyncio
    async def test_qa_report_searchable(self, layer) -> None:
        await layer.index_qa_report("news_fetcher", "PASS", 1.0)
        results = layer._collections["qa_reports"].query(query_texts=["news agent QA"], n_results=1)
        assert len(results["ids"][0]) >= 1


# ===========================================================================
# Event indexing tests
# ===========================================================================


class TestEventIndexing:
    @pytest.fixture
    async def layer(self, tmp_path):
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        yield l
        await l.stop()

    @pytest.mark.asyncio
    async def test_index_event_stores(self, layer) -> None:
        await layer.index_event("system", "started", "ProbOS started successfully")
        assert layer._collections["events"].count() == 1

    @pytest.mark.asyncio
    async def test_event_searchable(self, layer) -> None:
        await layer.index_event("system", "started", "ProbOS boot complete")
        results = layer._collections["events"].query(query_texts=["system startup"], n_results=1)
        assert len(results["ids"][0]) >= 1


# ===========================================================================
# Cross-type search tests
# ===========================================================================


class TestCrossTypeSearch:
    @pytest.fixture
    async def populated_layer(self, tmp_path):
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        await l.index_agent("text_analyzer", "analyze_text", "Analyze text content", "new_agent")
        await l.index_skill("count_words", "Count words in text paragraphs")
        await l.index_workflow("analyze text file", ["read_file", "analyze_text"])
        await l.index_event("system", "started", "ProbOS initialized")
        yield l
        await l.stop()

    @pytest.mark.asyncio
    async def test_search_returns_multiple_types(self, populated_layer) -> None:
        results = await populated_layer.search("text analysis", limit=10)
        types_found = {r["type"] for r in results}
        assert len(types_found) >= 2  # At least agent and skill

    @pytest.mark.asyncio
    async def test_search_with_type_filter(self, populated_layer) -> None:
        results = await populated_layer.search("text", types=["agents"], limit=10)
        for r in results:
            assert r["type"] == "agent"

    @pytest.mark.asyncio
    async def test_search_includes_episodes(self, tmp_path) -> None:
        """Episodes included when episodic memory available."""
        mock_em = AsyncMock()
        mock_episode = MagicMock()
        mock_episode.id = "ep1"
        mock_episode.user_input = "test query input"
        mock_episode.timestamp = 123.0
        mock_episode.agent_ids = ["a1"]
        mock_em.recall.return_value = [mock_episode]

        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic", episodic_memory=mock_em)
        await l.start()
        try:
            results = await l.search("test query", limit=10)
            episode_results = [r for r in results if r["type"] == "episode"]
            assert len(episode_results) >= 1
        finally:
            await l.stop()

    @pytest.mark.asyncio
    async def test_search_sorted_by_score(self, populated_layer) -> None:
        results = await populated_layer.search("text", limit=10)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i]["score"] >= results[i + 1]["score"]

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, populated_layer) -> None:
        results = await populated_layer.search("text", limit=2)
        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_search_no_matches_empty(self, tmp_path) -> None:
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        try:
            results = await l.search("xyzzy nonexistent query 12345")
            assert isinstance(results, list)
            assert len(results) == 0
        finally:
            await l.stop()


# ===========================================================================
# Bulk re-index tests
# ===========================================================================


class TestBulkReindex:
    @pytest.mark.asyncio
    async def test_reindex_indexes_agents(self, tmp_path) -> None:
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        try:
            mock_ks = AsyncMock()
            mock_ks.load_agents.return_value = [
                ({"agent_type": "foo", "intent_name": "bar", "strategy": "new_agent"}, "class Foo: pass"),
            ]
            mock_ks.load_skills.return_value = []
            mock_ks._read_json = AsyncMock(return_value=[])
            mock_ks._repo_path = tmp_path
            mock_ks.load_qa_reports.return_value = {}

            counts = await l.reindex_from_store(mock_ks)
            assert counts["agents"] == 1
            assert l._collections["agents"].count() == 1
        finally:
            await l.stop()

    @pytest.mark.asyncio
    async def test_reindex_indexes_skills(self, tmp_path) -> None:
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        try:
            mock_ks = AsyncMock()
            mock_ks.load_agents.return_value = []
            mock_ks.load_skills.return_value = [
                ("count_words", "async def handle_count_words(): pass", {"description": "Count words"}),
            ]
            mock_ks._read_json = AsyncMock(return_value=[])
            mock_ks._repo_path = tmp_path
            mock_ks.load_qa_reports.return_value = {}

            counts = await l.reindex_from_store(mock_ks)
            assert counts["skills"] == 1
        finally:
            await l.stop()

    @pytest.mark.asyncio
    async def test_reindex_returns_count_dict(self, tmp_path) -> None:
        l = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await l.start()
        try:
            mock_ks = AsyncMock()
            mock_ks.load_agents.return_value = []
            mock_ks.load_skills.return_value = []
            mock_ks._read_json = AsyncMock(return_value=[])
            mock_ks._repo_path = tmp_path
            mock_ks.load_qa_reports.return_value = {}

            counts = await l.reindex_from_store(mock_ks)
            assert "agents" in counts
            assert "skills" in counts
            assert "workflows" in counts
            assert "qa_reports" in counts
        finally:
            await l.stop()


# ===========================================================================
# Runtime integration tests
# ===========================================================================


class TestRuntimeIntegration:
    @pytest.fixture
    def runtime(self, tmp_path):
        from probos.runtime import ProbOSRuntime
        from probos.config import load_config

        config_path = tmp_path / "system.yaml"
        config_path.write_text(
            "system:\n  name: ProbOS\n  version: 0.1.0\n"
            "pools:\n  default_size: 2\n  min_size: 1\n  max_size: 5\n"
            "mesh:\n  hebbian_decay_rate: 0.99\n  hebbian_reward: 0.05\n"
            "  gossip_interval_ms: 5000\n  signal_ttl_seconds: 30\n"
            "  semantic_matching: false\n"
            "consensus:\n  min_votes: 2\n  approval_threshold: 0.6\n"
            "  use_confidence_weights: true\n  trust_prior_alpha: 2.0\n"
            "  trust_prior_beta: 2.0\n  trust_decay_rate: 0.999\n"
            "  red_team_pool_size: 2\n"
            "cognitive:\n  llm_base_url: 'http://localhost:8080/v1'\n"
            "  llm_api_key: ''\n  llm_model_fast: 'mock'\n"
            "  llm_model_standard: 'mock'\n  llm_model_deep: 'mock'\n"
            "  llm_timeout_seconds: 5\n  working_memory_token_budget: 2000\n"
            "  decomposition_timeout_seconds: 5\n  dag_execution_timeout_seconds: 10\n"
            "  max_concurrent_tasks: 5\n  attention_decay_rate: 0.95\n"
            "  focus_history_size: 5\n  background_demotion_factor: 0.5\n"
            "scaling:\n  enabled: false\n"
            "federation:\n  enabled: false\n"
            "self_mod:\n  enabled: false\n"
            "qa:\n  enabled: false\n"
            "knowledge:\n  enabled: false\n"
            "dreaming:\n  idle_threshold_seconds: 300\n  dream_interval_seconds: 600\n"
            "  replay_episode_count: 10\n  pathway_strengthening_factor: 0.02\n"
            "  pathway_weakening_factor: 0.01\n  prune_threshold: 0.005\n"
            "  trust_boost: 0.1\n  trust_penalty: 0.05\n  pre_warm_top_k: 5\n"
        )
        config = load_config(str(config_path))
        return ProbOSRuntime(config=config, data_dir=str(tmp_path / "data"))

    @pytest.mark.asyncio
    async def test_runtime_creates_layer_with_episodic(self, runtime, tmp_path) -> None:
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        runtime.episodic_memory = MockEpisodicMemory()
        runtime.episodic_memory.db_path = str(tmp_path / "data" / "episodic" / "chroma.db")
        (tmp_path / "data" / "episodic").mkdir(parents=True, exist_ok=True)
        await runtime.start()
        try:
            assert runtime._semantic_layer is not None
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_runtime_no_layer_without_episodic(self, runtime, tmp_path) -> None:
        await runtime.start()
        try:
            assert runtime._semantic_layer is None
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_status_includes_semantic_knowledge(self, runtime, tmp_path) -> None:
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        runtime.episodic_memory = MockEpisodicMemory()
        runtime.episodic_memory.db_path = str(tmp_path / "data" / "episodic" / "chroma.db")
        (tmp_path / "data" / "episodic").mkdir(parents=True, exist_ok=True)
        await runtime.start()
        try:
            status = runtime.status()
            assert "semantic_knowledge" in status
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_status_disabled_without_layer(self, runtime, tmp_path) -> None:
        await runtime.start()
        try:
            status = runtime.status()
            assert "semantic_knowledge" in status
            assert status["semantic_knowledge"] == {"enabled": False}
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up_layer(self, runtime, tmp_path) -> None:
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        runtime.episodic_memory = MockEpisodicMemory()
        runtime.episodic_memory.db_path = str(tmp_path / "data" / "episodic" / "chroma.db")
        (tmp_path / "data" / "episodic").mkdir(parents=True, exist_ok=True)
        await runtime.start()
        await runtime.stop()
        assert runtime._semantic_layer is None


# ===========================================================================
# Introspection integration tests
# ===========================================================================


class TestIntrospectionIntegration:
    @pytest.mark.asyncio
    async def test_search_knowledge_intent(self, tmp_path) -> None:
        agent = IntrospectionAgent(pool="introspect", agent_id="test_introspect_0")
        layer = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await layer.start()
        try:
            await layer.index_agent("test_agent", "test_intent", "Test description", "new_agent")
            rt = MagicMock()
            rt._semantic_layer = layer
            agent._runtime = rt

            from probos.types import IntentMessage
            intent = IntentMessage(intent="search_knowledge", params={"query": "test"})
            result = await agent.handle_intent(intent)
            assert result is not None
            assert result.success is True
            assert "results" in result.result
        finally:
            await layer.stop()

    @pytest.mark.asyncio
    async def test_search_knowledge_with_types(self, tmp_path) -> None:
        agent = IntrospectionAgent(pool="introspect", agent_id="test_introspect_0")
        layer = SemanticKnowledgeLayer(db_path=tmp_path / "semantic")
        await layer.start()
        try:
            await layer.index_agent("test_agent", "test_intent", "Test description", "new_agent")
            await layer.index_skill("test_skill", "A test skill")
            rt = MagicMock()
            rt._semantic_layer = layer
            agent._runtime = rt

            from probos.types import IntentMessage
            intent = IntentMessage(intent="search_knowledge", params={"query": "test", "types": "agents"})
            result = await agent.handle_intent(intent)
            assert result is not None
            assert result.success is True
        finally:
            await layer.stop()

    @pytest.mark.asyncio
    async def test_search_knowledge_no_layer(self) -> None:
        agent = IntrospectionAgent(pool="introspect", agent_id="test_introspect_0")
        rt = MagicMock(spec=[])
        agent._runtime = rt

        from probos.types import IntentMessage
        intent = IntentMessage(intent="search_knowledge", params={"query": "test"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        assert "not available" in result.result.get("message", "")

    @pytest.mark.asyncio
    async def test_mock_llm_routes_search(self) -> None:
        client = MockLLMClient()
        request = LLMRequest(prompt="search for text processing agents")
        response = await client.complete(request)
        data = json.loads(response.content)
        intents = data.get("intents", [])
        assert len(intents) == 1
        assert intents[0]["intent"] == "search_knowledge"


# ===========================================================================
# Shell and panel tests
# ===========================================================================


class TestShellAndPanel:
    def test_help_includes_search(self) -> None:
        assert "/search" in ProbOSShell.COMMANDS

    def test_render_search_panel_with_results(self) -> None:
        results = [
            {"type": "agent", "id": "agent_foo", "document": "Foo agent for testing", "score": 0.87, "metadata": {}},
            {"type": "skill", "id": "skill_bar", "document": "Bar skill for counting", "score": 0.72, "metadata": {}},
        ]
        stats = {"agents": 1, "skills": 1, "workflows": 0, "qa_reports": 0, "events": 0}
        panel = render_search_panel("test query", results, stats)
        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=True)
        console.print(panel)
        output = buf.getvalue()
        assert "test query" in output
        assert "agent" in output
        assert "skill" in output

    def test_render_search_panel_empty(self) -> None:
        panel = render_search_panel("test query", [], {})
        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=True)
        console.print(panel)
        output = buf.getvalue()
        assert "No matching results" in output

    def test_render_search_panel_score_format(self) -> None:
        results = [
            {"type": "agent", "id": "a1", "document": "Test agent", "score": 0.92, "metadata": {}},
        ]
        panel = render_search_panel("query", results, {"agents": 1})
        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=True)
        console.print(panel)
        output = buf.getvalue()
        assert "92%" in output

    @pytest.mark.asyncio
    async def test_search_command_no_query(self, tmp_path) -> None:
        from probos.config import load_config
        from probos.runtime import ProbOSRuntime

        config_path = tmp_path / "system.yaml"
        config_path.write_text(
            "system:\n  name: ProbOS\n  version: 0.1.0\n"
            "pools:\n  default_size: 2\n  min_size: 1\n  max_size: 5\n"
            "mesh:\n  hebbian_decay_rate: 0.99\n  hebbian_reward: 0.05\n"
            "  gossip_interval_ms: 5000\n  signal_ttl_seconds: 30\n"
            "  semantic_matching: false\n"
            "consensus:\n  min_votes: 2\n  approval_threshold: 0.6\n"
            "  use_confidence_weights: true\n  trust_prior_alpha: 2.0\n"
            "  trust_prior_beta: 2.0\n  trust_decay_rate: 0.999\n"
            "  red_team_pool_size: 2\n"
            "cognitive:\n  llm_base_url: 'http://localhost:8080/v1'\n"
            "  llm_api_key: ''\n  llm_model_fast: 'mock'\n"
            "  llm_model_standard: 'mock'\n  llm_model_deep: 'mock'\n"
            "  llm_timeout_seconds: 5\n  working_memory_token_budget: 2000\n"
            "  decomposition_timeout_seconds: 5\n  dag_execution_timeout_seconds: 10\n"
            "  max_concurrent_tasks: 5\n  attention_decay_rate: 0.95\n"
            "  focus_history_size: 5\n  background_demotion_factor: 0.5\n"
            "scaling:\n  enabled: false\n"
            "federation:\n  enabled: false\n"
            "self_mod:\n  enabled: false\n"
            "qa:\n  enabled: false\n"
            "knowledge:\n  enabled: false\n"
            "dreaming:\n  idle_threshold_seconds: 300\n  dream_interval_seconds: 600\n"
            "  replay_episode_count: 10\n  pathway_strengthening_factor: 0.02\n"
            "  pathway_weakening_factor: 0.01\n  prune_threshold: 0.005\n"
            "  trust_boost: 0.1\n  trust_penalty: 0.05\n  pre_warm_top_k: 5\n"
        )
        config = load_config(str(config_path))
        rt = ProbOSRuntime(config=config, data_dir=str(tmp_path / "data"))
        await rt.start()
        try:
            buf = StringIO()
            console = Console(file=buf, width=120, force_terminal=True)
            shell = ProbOSShell(rt, console=console)
            await shell.execute_command("/search")
            output = buf.getvalue()
            assert "Usage" in output or "not available" in output
        finally:
            await rt.stop()
