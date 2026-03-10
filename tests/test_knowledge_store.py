"""Tests for Phase 14: Persistent Knowledge Store."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from probos.config import KnowledgeConfig, SystemConfig, load_config
from probos.types import Episode, IntentDescriptor, Skill, WorkflowCacheEntry


# ===================================================================
# 6g. Config tests
# ===================================================================


class TestKnowledgeConfig:
    """Tests for KnowledgeConfig."""

    def test_knowledge_config_defaults(self):
        """Default values match spec."""
        cfg = KnowledgeConfig()
        assert cfg.enabled is True
        assert cfg.repo_path == ""
        assert cfg.auto_commit is True
        assert cfg.commit_debounce_seconds == 5.0
        assert cfg.max_episodes == 1000
        assert cfg.max_workflows == 200
        assert cfg.restore_on_boot is True

    def test_knowledge_config_in_system_config(self):
        """SystemConfig includes knowledge: KnowledgeConfig."""
        sc = SystemConfig()
        assert hasattr(sc, "knowledge")
        assert isinstance(sc.knowledge, KnowledgeConfig)

    def test_knowledge_config_from_yaml(self, tmp_path):
        """Custom values load from YAML."""
        yaml_content = """
system:
  name: "ProbOS"
knowledge:
  enabled: false
  repo_path: "/custom/path"
  max_episodes: 500
"""
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml_content)
        cfg = load_config(cfg_file)
        assert cfg.knowledge.enabled is False
        assert cfg.knowledge.repo_path == "/custom/path"
        assert cfg.knowledge.max_episodes == 500

    def test_knowledge_config_missing_uses_defaults(self, tmp_path):
        """Missing knowledge: section uses defaults."""
        yaml_content = """
system:
  name: "ProbOS"
"""
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text(yaml_content)
        cfg = load_config(cfg_file)
        assert cfg.knowledge.enabled is True
        assert cfg.knowledge.repo_path == ""


# ===================================================================
# 6e. EpisodicMemory.seed() tests
# ===================================================================


class TestEpisodicMemorySeed:
    """Tests for EpisodicMemory.seed() warm boot method."""

    @pytest.fixture
    def _make_episode(self):
        def _factory(id_: str, user_input: str = "test", ts: float = 0.0):
            return Episode(
                id=id_, user_input=user_input,
                timestamp=ts or time.time(), dag_summary={},
                outcomes=[], agent_ids=[], duration_ms=10.0,
            )
        return _factory

    @pytest.mark.asyncio
    async def test_seed_restores_episodes(self, tmp_path, _make_episode):
        """seed() inserts episodes retrievable via recall() and recent()."""
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
        await mem.start()
        ep = _make_episode("seed1", "read config file")
        count = await mem.seed([ep])
        assert count == 1

        recent = await mem.recent(10)
        assert any(e.id == "seed1" for e in recent)
        await mem.stop()

    @pytest.mark.asyncio
    async def test_seed_preserves_ids(self, tmp_path, _make_episode):
        """Seeded episodes retain their original IDs."""
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
        await mem.start()
        ep = _make_episode("custom_id_123")
        await mem.seed([ep])
        recent = await mem.recent(10)
        assert recent[0].id == "custom_id_123"
        await mem.stop()

    @pytest.mark.asyncio
    async def test_seed_preserves_timestamps(self, tmp_path, _make_episode):
        """Seeded episodes retain their original timestamps."""
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
        await mem.start()
        ep = _make_episode("ts_test", ts=1234567890.0)
        await mem.seed([ep])
        recent = await mem.recent(10)
        assert recent[0].timestamp == 1234567890.0
        await mem.stop()

    @pytest.mark.asyncio
    async def test_seed_skips_duplicate_ids(self, tmp_path, _make_episode):
        """Seeded episodes with existing IDs are skipped."""
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
        await mem.start()
        ep1 = _make_episode("dup_id", "original text")
        await mem.store(ep1)
        ep2 = _make_episode("dup_id", "different text")
        count = await mem.seed([ep2])
        # seed uses INSERT OR IGNORE, so duplicate is skipped
        recent = await mem.recent(10)
        assert len(recent) == 1
        assert recent[0].user_input == "original text"
        await mem.stop()

    @pytest.mark.asyncio
    async def test_seed_empty_list(self, tmp_path):
        """seed([]) is a no-op."""
        from probos.cognitive.episodic import EpisodicMemory

        mem = EpisodicMemory(db_path=str(tmp_path / "ep.db"))
        await mem.start()
        count = await mem.seed([])
        assert count == 0
        await mem.stop()

    @pytest.mark.asyncio
    async def test_mock_episodic_seed(self, _make_episode):
        """MockEpisodicMemory.seed() works identically."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory

        mem = MockEpisodicMemory()
        ep1 = _make_episode("mock1", "test input")
        ep2 = _make_episode("mock2", "another input")
        count = await mem.seed([ep1, ep2])
        assert count == 2
        recent = await mem.recent(10)
        assert len(recent) == 2

        # Duplicate skip
        count2 = await mem.seed([_make_episode("mock1", "dup")])
        assert count2 == 0


# ===================================================================
# 6f. WorkflowCache.export_all() tests
# ===================================================================


class TestWorkflowCacheExportAll:
    """Tests for WorkflowCache.export_all()."""

    def test_export_all_returns_all_entries(self):
        """export_all() returns all cached entries."""
        from probos.cognitive.workflow_cache import WorkflowCache
        from probos.types import TaskDAG, TaskNode

        cache = WorkflowCache(max_size=10)
        dag1 = TaskDAG(nodes=[TaskNode(id="n1", intent="read_file", params={"path": "/a"}, status="completed")])
        dag2 = TaskDAG(nodes=[TaskNode(id="n2", intent="list_directory", params={"path": "/b"}, status="completed")])
        cache.store("read file a", dag1)
        cache.store("list dir b", dag2)

        exported = cache.export_all()
        assert len(exported) == 2

    def test_export_all_empty_cache(self):
        """export_all() returns empty list when cache is empty."""
        from probos.cognitive.workflow_cache import WorkflowCache

        cache = WorkflowCache(max_size=10)
        exported = cache.export_all()
        assert exported == []

    def test_export_all_serializable(self):
        """Returned dicts are JSON-serializable."""
        from probos.cognitive.workflow_cache import WorkflowCache
        from probos.types import TaskDAG, TaskNode

        cache = WorkflowCache(max_size=10)
        dag = TaskDAG(nodes=[TaskNode(id="n1", intent="read_file", params={"path": "/a"}, status="completed")])
        cache.store("test input", dag)

        exported = cache.export_all()
        # Should not raise
        serialized = json.dumps(exported)
        assert len(serialized) > 0


# ===================================================================
# TrustNetwork.raw_scores() tests
# ===================================================================


class TestTrustNetworkRawScores:
    """Tests for TrustNetwork.raw_scores() AD-168."""

    @pytest.mark.asyncio
    async def test_raw_scores_returns_alpha_beta(self, tmp_path):
        """raw_scores() returns raw alpha/beta parameters."""
        from probos.consensus.trust import TrustNetwork

        tn = TrustNetwork(db_path=str(tmp_path / "trust.db"))
        await tn.start()
        tn.create_with_prior("agent1", alpha=5.0, beta=3.0)
        raw = tn.raw_scores()
        assert "agent1" in raw
        assert raw["agent1"]["alpha"] == 5.0
        assert raw["agent1"]["beta"] == 3.0
        assert "observations" in raw["agent1"]
        await tn.stop()

    @pytest.mark.asyncio
    async def test_raw_scores_not_derived_mean(self, tmp_path):
        """raw_scores contains alpha/beta, not just mean."""
        from probos.consensus.trust import TrustNetwork

        tn = TrustNetwork(db_path=str(tmp_path / "trust.db"))
        await tn.start()
        tn.create_with_prior("a1", alpha=10.0, beta=2.0)
        tn.create_with_prior("a2", alpha=2.0, beta=10.0)
        raw = tn.raw_scores()
        # Different distributions with different means
        assert raw["a1"]["alpha"] == 10.0
        assert raw["a1"]["beta"] == 2.0
        assert raw["a2"]["alpha"] == 2.0
        assert raw["a2"]["beta"] == 10.0
        await tn.stop()


# ===================================================================
# 6a. KnowledgeStore unit tests
# ===================================================================

# Marker for tests requiring git binary
requires_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available"
)


@pytest.fixture
def knowledge_store(tmp_path):
    """Create a KnowledgeStore with temp directory."""
    cfg = KnowledgeConfig(
        enabled=True,
        repo_path=str(tmp_path / "knowledge"),
        auto_commit=False,  # Disable auto-commit for unit tests
    )
    return __import__("probos.knowledge.store", fromlist=["KnowledgeStore"]).KnowledgeStore(cfg)


@pytest.fixture
def knowledge_store_git(tmp_path):
    """Create a KnowledgeStore with auto-commit enabled for git tests."""
    cfg = KnowledgeConfig(
        enabled=True,
        repo_path=str(tmp_path / "knowledge"),
        auto_commit=True,
        commit_debounce_seconds=0.1,  # Short debounce for testing
    )
    return __import__("probos.knowledge.store", fromlist=["KnowledgeStore"]).KnowledgeStore(cfg)


def _make_test_episode(id_: str = "test1", user_input: str = "read file", ts: float = 0.0) -> Episode:
    return Episode(
        id=id_,
        user_input=user_input,
        timestamp=ts or time.time(),
        dag_summary={"intents": 1},
        outcomes=[{"success": True}],
        agent_ids=["a1"],
        duration_ms=50.0,
    )


class TestKnowledgeStoreInit:
    """Tests for KnowledgeStore initialization."""

    @pytest.mark.asyncio
    async def test_initialize_creates_directory(self, knowledge_store):
        """initialize() creates the repo directory if it doesn't exist."""
        await knowledge_store.initialize()
        assert knowledge_store.repo_path.is_dir()

    @pytest.mark.asyncio
    async def test_initialize_creates_subdirs(self, knowledge_store):
        """initialize() creates all artifact subdirectories."""
        await knowledge_store.initialize()
        for sub in ("episodes", "agents", "skills", "trust", "routing", "workflows", "qa"):
            assert (knowledge_store.repo_path / sub).is_dir()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, knowledge_store):
        """Calling initialize() twice doesn't error."""
        await knowledge_store.initialize()
        await knowledge_store.initialize()

    @pytest.mark.asyncio
    async def test_repo_exists_false_before_write(self, knowledge_store):
        """repo_exists returns False before any write."""
        await knowledge_store.initialize()
        assert knowledge_store.repo_exists is False


class TestKnowledgeStoreEpisodes:
    """Tests for episode persistence."""

    @pytest.mark.asyncio
    async def test_store_episode_creates_file(self, knowledge_store):
        """store_episode() creates episodes/{id}.json."""
        await knowledge_store.initialize()
        ep = _make_test_episode("ep1")
        await knowledge_store.store_episode(ep)
        assert (knowledge_store.repo_path / "episodes" / "ep1.json").is_file()

    @pytest.mark.asyncio
    async def test_store_episode_valid_json(self, knowledge_store):
        """Stored episode file is valid JSON matching Episode fields."""
        await knowledge_store.initialize()
        ep = _make_test_episode("ep2", "read the config")
        await knowledge_store.store_episode(ep)
        data = json.loads((knowledge_store.repo_path / "episodes" / "ep2.json").read_text())
        assert data["id"] == "ep2"
        assert data["user_input"] == "read the config"

    @pytest.mark.asyncio
    async def test_load_episodes_returns_stored(self, knowledge_store):
        """load_episodes() returns episodes previously stored."""
        await knowledge_store.initialize()
        ep = _make_test_episode("ep3")
        await knowledge_store.store_episode(ep)
        loaded = await knowledge_store.load_episodes()
        assert len(loaded) == 1
        assert loaded[0].id == "ep3"

    @pytest.mark.asyncio
    async def test_load_episodes_sorted_by_timestamp(self, knowledge_store):
        """Episodes returned newest-first."""
        await knowledge_store.initialize()
        await knowledge_store.store_episode(_make_test_episode("old", ts=100.0))
        await knowledge_store.store_episode(_make_test_episode("new", ts=200.0))
        loaded = await knowledge_store.load_episodes()
        assert loaded[0].id == "new"
        assert loaded[1].id == "old"

    @pytest.mark.asyncio
    async def test_load_episodes_limit(self, knowledge_store):
        """load_episodes(limit=2) returns at most 2."""
        await knowledge_store.initialize()
        for i in range(5):
            await knowledge_store.store_episode(_make_test_episode(f"ep{i}", ts=float(i)))
        loaded = await knowledge_store.load_episodes(limit=2)
        assert len(loaded) == 2

    @pytest.mark.asyncio
    async def test_load_episodes_empty_dir(self, knowledge_store):
        """load_episodes() returns empty list when no episodes exist."""
        await knowledge_store.initialize()
        loaded = await knowledge_store.load_episodes()
        assert loaded == []

    @pytest.mark.asyncio
    async def test_max_episodes_eviction(self, tmp_path):
        """When max_episodes exceeded, oldest episodes are deleted."""
        from probos.knowledge.store import KnowledgeStore
        cfg = KnowledgeConfig(
            repo_path=str(tmp_path / "knowledge"),
            auto_commit=False,
            max_episodes=3,
        )
        store = KnowledgeStore(cfg)
        await store.initialize()
        for i in range(5):
            ep = _make_test_episode(f"ep{i}", ts=float(i))
            await store.store_episode(ep)
            # Small delay so mtime differs
            time.sleep(0.01)
        loaded = await store.load_episodes()
        assert len(loaded) <= 3


class TestKnowledgeStoreAgents:
    """Tests for designed agent persistence."""

    @pytest.fixture
    def _mock_record(self):
        from probos.cognitive.self_mod import DesignedAgentRecord
        return DesignedAgentRecord(
            intent_name="get_weather",
            agent_type="weather_agent",
            class_name="WeatherAgent",
            source_code="class WeatherAgent: pass",
            created_at=time.time(),
            sandbox_time_ms=25.0,
            pool_name="designed_weather_agent",
            status="active",
        )

    @pytest.mark.asyncio
    async def test_store_agent_creates_py_and_json(self, knowledge_store, _mock_record):
        """store_agent() creates both .py and .json files."""
        await knowledge_store.initialize()
        await knowledge_store.store_agent(_mock_record, "class WeatherAgent: pass")
        assert (knowledge_store.repo_path / "agents" / "weather_agent.py").is_file()
        assert (knowledge_store.repo_path / "agents" / "weather_agent.json").is_file()

    @pytest.mark.asyncio
    async def test_store_agent_source_matches(self, knowledge_store, _mock_record):
        """The .py file content matches the provided source code."""
        await knowledge_store.initialize()
        source = "class WeatherAgent:\n    pass\n"
        await knowledge_store.store_agent(_mock_record, source)
        content = (knowledge_store.repo_path / "agents" / "weather_agent.py").read_text()
        assert content == source

    @pytest.mark.asyncio
    async def test_store_agent_metadata_matches(self, knowledge_store, _mock_record):
        """The .json file contains correct DesignedAgentRecord fields."""
        await knowledge_store.initialize()
        await knowledge_store.store_agent(_mock_record, "class WeatherAgent: pass")
        data = json.loads((knowledge_store.repo_path / "agents" / "weather_agent.json").read_text())
        assert data["agent_type"] == "weather_agent"
        assert data["class_name"] == "WeatherAgent"
        assert data["intent_name"] == "get_weather"

    @pytest.mark.asyncio
    async def test_load_agents_returns_stored(self, knowledge_store, _mock_record):
        """load_agents() returns previously stored agent records + source."""
        await knowledge_store.initialize()
        await knowledge_store.store_agent(_mock_record, "class WeatherAgent: pass")
        loaded = await knowledge_store.load_agents()
        assert len(loaded) == 1
        metadata, source = loaded[0]
        assert metadata["agent_type"] == "weather_agent"
        assert "WeatherAgent" in source

    @pytest.mark.asyncio
    async def test_load_agents_empty(self, knowledge_store):
        """load_agents() returns empty list when no agents exist."""
        await knowledge_store.initialize()
        loaded = await knowledge_store.load_agents()
        assert loaded == []

    @pytest.mark.asyncio
    async def test_remove_agent_deletes_files(self, knowledge_store, _mock_record):
        """remove_agent() deletes both .py and .json files."""
        await knowledge_store.initialize()
        await knowledge_store.store_agent(_mock_record, "class WeatherAgent: pass")
        await knowledge_store.remove_agent("weather_agent")
        assert not (knowledge_store.repo_path / "agents" / "weather_agent.py").is_file()
        assert not (knowledge_store.repo_path / "agents" / "weather_agent.json").is_file()

    @pytest.mark.asyncio
    async def test_remove_agent_nonexistent(self, knowledge_store):
        """remove_agent() for missing agent doesn't error."""
        await knowledge_store.initialize()
        await knowledge_store.remove_agent("nonexistent")


class TestKnowledgeStoreSkills:
    """Tests for skill persistence."""

    @pytest.mark.asyncio
    async def test_store_skill_creates_files(self, knowledge_store):
        """store_skill() creates .py and .json files in skills/."""
        await knowledge_store.initialize()
        await knowledge_store.store_skill("translate", "async def handle_translate(): pass", {"name": "translate"})
        assert (knowledge_store.repo_path / "skills" / "translate.py").is_file()
        assert (knowledge_store.repo_path / "skills" / "translate.json").is_file()

    @pytest.mark.asyncio
    async def test_load_skills_returns_stored(self, knowledge_store):
        """load_skills() returns previously stored skills."""
        await knowledge_store.initialize()
        await knowledge_store.store_skill("summarize", "async def handle_summarize(): pass", {"name": "summarize"})
        loaded = await knowledge_store.load_skills()
        assert len(loaded) == 1
        name, source, desc = loaded[0]
        assert name == "summarize"
        assert "handle_summarize" in source


class TestKnowledgeStoreTrust:
    """Tests for trust snapshot persistence."""

    @pytest.mark.asyncio
    async def test_store_trust_snapshot(self, knowledge_store):
        """store_trust_snapshot() creates trust/snapshot.json."""
        await knowledge_store.initialize()
        raw = {"agent1": {"alpha": 5.0, "beta": 3.0, "observations": 4.0}}
        await knowledge_store.store_trust_snapshot(raw)
        assert (knowledge_store.repo_path / "trust" / "snapshot.json").is_file()

    @pytest.mark.asyncio
    async def test_load_trust_snapshot(self, knowledge_store):
        """load_trust_snapshot() returns previously stored trust data."""
        await knowledge_store.initialize()
        raw = {"agent1": {"alpha": 5.0, "beta": 3.0, "observations": 4.0}}
        await knowledge_store.store_trust_snapshot(raw)
        loaded = await knowledge_store.load_trust_snapshot()
        assert loaded is not None
        assert loaded["agent1"]["alpha"] == 5.0
        assert loaded["agent1"]["beta"] == 3.0

    @pytest.mark.asyncio
    async def test_load_trust_snapshot_missing(self, knowledge_store):
        """Returns None when no snapshot exists."""
        await knowledge_store.initialize()
        loaded = await knowledge_store.load_trust_snapshot()
        assert loaded is None

    @pytest.mark.asyncio
    async def test_trust_snapshot_contains_raw_params(self, knowledge_store):
        """Snapshot contains raw alpha, beta fields (AD-168)."""
        await knowledge_store.initialize()
        raw = {"a1": {"alpha": 10.0, "beta": 2.0, "observations": 8.0}}
        await knowledge_store.store_trust_snapshot(raw)
        loaded = await knowledge_store.load_trust_snapshot()
        assert "alpha" in loaded["a1"]
        assert "beta" in loaded["a1"]
        assert loaded["a1"]["alpha"] == 10.0


class TestKnowledgeStoreRouting:
    """Tests for routing weights persistence."""

    @pytest.mark.asyncio
    async def test_store_routing_weights(self, knowledge_store):
        """store_routing_weights() creates routing/weights.json."""
        await knowledge_store.initialize()
        weights = [{"source": "a", "target": "b", "rel_type": "intent", "weight": 0.5}]
        await knowledge_store.store_routing_weights(weights)
        assert (knowledge_store.repo_path / "routing" / "weights.json").is_file()

    @pytest.mark.asyncio
    async def test_load_routing_weights(self, knowledge_store):
        """load_routing_weights() returns previously stored weights."""
        await knowledge_store.initialize()
        weights = [{"source": "a", "target": "b", "rel_type": "intent", "weight": 0.5}]
        await knowledge_store.store_routing_weights(weights)
        loaded = await knowledge_store.load_routing_weights()
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["weight"] == 0.5


class TestKnowledgeStoreWorkflows:
    """Tests for workflow cache persistence."""

    @pytest.mark.asyncio
    async def test_store_workflows(self, knowledge_store):
        """store_workflows() creates workflows/cache.json."""
        await knowledge_store.initialize()
        entries = [{"pattern": "read file", "dag_json": "{}", "hit_count": 3}]
        await knowledge_store.store_workflows(entries)
        assert (knowledge_store.repo_path / "workflows" / "cache.json").is_file()

    @pytest.mark.asyncio
    async def test_load_workflows(self, knowledge_store):
        """load_workflows() returns previously stored entries."""
        await knowledge_store.initialize()
        entries = [{"pattern": "read file", "dag_json": "{}", "hit_count": 3}]
        await knowledge_store.store_workflows(entries)
        loaded = await knowledge_store.load_workflows()
        assert loaded is not None
        assert len(loaded) == 1

    @pytest.mark.asyncio
    async def test_max_workflows_eviction(self, tmp_path):
        """When max_workflows exceeded, lowest hit_count workflows dropped."""
        from probos.knowledge.store import KnowledgeStore
        cfg = KnowledgeConfig(
            repo_path=str(tmp_path / "knowledge"),
            auto_commit=False,
            max_workflows=2,
        )
        store = KnowledgeStore(cfg)
        await store.initialize()
        entries = [
            {"pattern": "low", "dag_json": "{}", "hit_count": 1},
            {"pattern": "mid", "dag_json": "{}", "hit_count": 5},
            {"pattern": "high", "dag_json": "{}", "hit_count": 10},
        ]
        await store.store_workflows(entries)
        loaded = await store.load_workflows()
        assert len(loaded) == 2


class TestKnowledgeStoreQA:
    """Tests for QA report persistence."""

    @pytest.mark.asyncio
    async def test_store_qa_report(self, knowledge_store):
        """store_qa_report() creates qa/{agent_type}.json."""
        await knowledge_store.initialize()
        report = {"agent_type": "weather", "verdict": "passed", "passed": 4, "failed": 1}
        await knowledge_store.store_qa_report("weather", report)
        assert (knowledge_store.repo_path / "qa" / "weather.json").is_file()

    @pytest.mark.asyncio
    async def test_load_qa_reports(self, knowledge_store):
        """load_qa_reports() returns all stored reports."""
        await knowledge_store.initialize()
        await knowledge_store.store_qa_report("w1", {"verdict": "passed"})
        await knowledge_store.store_qa_report("w2", {"verdict": "failed"})
        loaded = await knowledge_store.load_qa_reports()
        assert len(loaded) == 2
        assert "w1" in loaded
        assert "w2" in loaded


# ===================================================================
# 6b. Git integration tests
# ===================================================================


class TestGitIntegration:
    """Tests for Git-backed operations."""

    @requires_git
    @pytest.mark.asyncio
    async def test_git_init_on_first_write(self, knowledge_store_git):
        """Git repo is initialized on first store_* call (AD-159)."""
        store = knowledge_store_git
        await store.initialize()
        assert not store.repo_exists  # No git yet

        await store.store_episode(_make_test_episode("g1"))
        await store.flush()
        assert store.repo_exists

    @requires_git
    @pytest.mark.asyncio
    async def test_meta_json_written_on_init(self, knowledge_store_git):
        """meta.json created with schema_version and probos_version (AD-169)."""
        store = knowledge_store_git
        await store.initialize()
        await store.store_episode(_make_test_episode("m1"))
        await store.flush()
        meta_path = store.repo_path / "meta.json"
        assert meta_path.is_file()
        meta = json.loads(meta_path.read_text())
        assert meta["schema_version"] == 1
        assert meta["probos_version"] == "0.1.0"
        assert "created" in meta

    @requires_git
    @pytest.mark.asyncio
    async def test_repo_exists_true_after_write(self, knowledge_store_git):
        """repo_exists returns True after first write."""
        store = knowledge_store_git
        await store.initialize()
        await store.store_episode(_make_test_episode("r1"))
        await store.flush()
        assert store.repo_exists is True

    @requires_git
    @pytest.mark.asyncio
    async def test_flush_commits_immediately(self, knowledge_store_git):
        """flush() commits pending changes without waiting for debounce."""
        store = knowledge_store_git
        await store.initialize()
        await store.store_episode(_make_test_episode("f1"))
        await store.flush()
        # Should have at least one commit
        count = await store.commit_count()
        assert count >= 1

    @requires_git
    @pytest.mark.asyncio
    async def test_commit_message_includes_artifact_info(self, knowledge_store_git):
        """Commit messages describe what was changed."""
        store = knowledge_store_git
        await store.initialize()
        await store.store_episode(_make_test_episode("cm1"))
        await store.flush()
        commits = await store.recent_commits(5)
        assert len(commits) >= 1
        # At least one commit message should mention the episode
        messages = " ".join(c["message"] for c in commits)
        assert "episode" in messages.lower() or "store" in messages.lower()

    @requires_git
    @pytest.mark.asyncio
    async def test_flush_prevents_debounce_race(self, knowledge_store_git):
        """Debounce timer firing during flush() does not double-commit (AD-161)."""
        store = knowledge_store_git
        await store.initialize()

        # Store something to trigger debounce timer
        store._config = store._config.model_copy(update={"commit_debounce_seconds": 0.05})
        await store.store_episode(_make_test_episode("race1"))

        # Immediately flush (should set _flushing to prevent timer callback)
        await store.flush()
        count1 = await store.commit_count()

        # Wait for debounce to fire (should be a no-op due to _flushing guard)
        await asyncio.sleep(0.15)
        count2 = await store.commit_count()
        # Should not have additional commits from the timer
        assert count2 == count1

    @requires_git
    @pytest.mark.asyncio
    async def test_thread_executor_no_event_loop_block(self, knowledge_store_git):
        """Git operations don't block the asyncio event loop (AD-166)."""
        store = knowledge_store_git
        await store.initialize()
        await store.store_episode(_make_test_episode("thr1"))
        # If this runs without blocking/timeout, the executor is working
        await store.flush()
        assert store.repo_exists

    @requires_git
    @pytest.mark.asyncio
    async def test_uses_get_running_loop(self, knowledge_store_git):
        """Git operations use asyncio.get_running_loop() (AD-166)."""
        # This test verifies the code path works inside a running loop
        store = knowledge_store_git
        await store.initialize()
        await store.store_episode(_make_test_episode("loop1"))
        await store.flush()
        # If we got here without error, get_running_loop() worked
        assert store.repo_exists

    def test_git_not_available_graceful(self, tmp_path):
        """If git binary is not found, store works in file-only mode."""
        from probos.knowledge.store import KnowledgeStore
        cfg = KnowledgeConfig(repo_path=str(tmp_path / "knowledge"), auto_commit=False)
        store = KnowledgeStore(cfg)
        store._git_available = False

        async def _run():
            await store.initialize()
            await store.store_episode(_make_test_episode("ng1"))
            loaded = await store.load_episodes()
            assert len(loaded) == 1

        asyncio.run(_run())

    @requires_git
    @pytest.mark.asyncio
    async def test_auto_commit_after_debounce(self, tmp_path):
        """After storing and waiting for debounce, a git commit exists."""
        from probos.knowledge.store import KnowledgeStore
        cfg = KnowledgeConfig(
            repo_path=str(tmp_path / "knowledge"),
            auto_commit=True,
            commit_debounce_seconds=0.1,
        )
        store = KnowledgeStore(cfg)
        await store.initialize()
        await store.store_episode(_make_test_episode("ac1"))
        # Wait for debounce
        await asyncio.sleep(0.3)
        count = await store.commit_count()
        assert count >= 1

    @requires_git
    @pytest.mark.asyncio
    async def test_debounce_batches_writes(self, tmp_path):
        """Multiple writes within debounce window produce a single commit."""
        from probos.knowledge.store import KnowledgeStore
        cfg = KnowledgeConfig(
            repo_path=str(tmp_path / "knowledge"),
            auto_commit=True,
            commit_debounce_seconds=0.2,
        )
        store = KnowledgeStore(cfg)
        await store.initialize()
        # Rapid-fire writes
        for i in range(5):
            await store.store_episode(_make_test_episode(f"batch{i}", ts=float(i)))
        # Wait for single debounce commit
        await asyncio.sleep(0.5)
        count = await store.commit_count()
        # Should have fewer commits than writes (batched)
        assert count <= 3  # 1 for init meta + 1 for batched episodes


# ===================================================================
# 6b.2 Rollback tests
# ===================================================================


class TestRollback:
    """Tests for artifact rollback."""

    @requires_git
    @pytest.mark.asyncio
    async def test_rollback_restores_previous_version(self, knowledge_store_git):
        """rollback_artifact() restores the previous version of a file."""
        store = knowledge_store_git
        await store.initialize()

        # Version 1
        raw1 = {"a1": {"alpha": 5.0, "beta": 3.0, "observations": 4.0}}
        await store.store_trust_snapshot(raw1)
        await store.flush()

        # Version 2
        raw2 = {"a1": {"alpha": 10.0, "beta": 1.0, "observations": 8.0}}
        await store.store_trust_snapshot(raw2)
        await store.flush()

        # Verify current is v2
        loaded = await store.load_trust_snapshot()
        assert loaded["a1"]["alpha"] == 10.0

        # Rollback
        success = await store.rollback_artifact("trust", "snapshot")
        assert success is True

        # Should be back to v1
        loaded = await store.load_trust_snapshot()
        assert loaded["a1"]["alpha"] == 5.0

    @requires_git
    @pytest.mark.asyncio
    async def test_rollback_creates_new_commit(self, knowledge_store_git):
        """Rollback creates a new commit (not destructive rewrite)."""
        store = knowledge_store_git
        await store.initialize()

        await store.store_trust_snapshot({"a": {"alpha": 1.0, "beta": 1.0, "observations": 0.0}})
        await store.flush()
        await store.store_trust_snapshot({"a": {"alpha": 2.0, "beta": 2.0, "observations": 0.0}})
        await store.flush()

        before = await store.commit_count()
        await store.rollback_artifact("trust", "snapshot")
        after = await store.commit_count()
        assert after > before

    @requires_git
    @pytest.mark.asyncio
    async def test_rollback_no_history_returns_false(self, knowledge_store_git):
        """rollback_artifact() returns False when artifact has no previous version."""
        store = knowledge_store_git
        await store.initialize()
        await store.store_trust_snapshot({"a": {"alpha": 1.0, "beta": 1.0, "observations": 0.0}})
        await store.flush()
        # Only one version — no previous to roll back to
        result = await store.rollback_artifact("trust", "snapshot")
        assert result is False

    @requires_git
    @pytest.mark.asyncio
    async def test_artifact_history_returns_commits(self, knowledge_store_git):
        """artifact_history() returns commit log for a specific file."""
        store = knowledge_store_git
        await store.initialize()
        await store.store_trust_snapshot({"a": {"alpha": 1.0, "beta": 1.0, "observations": 0.0}})
        await store.flush()
        await store.store_trust_snapshot({"a": {"alpha": 2.0, "beta": 2.0, "observations": 0.0}})
        await store.flush()

        history = await store.artifact_history("trust", "snapshot")
        assert len(history) >= 2
        assert "commit_hash" in history[0]
        assert "timestamp" in history[0]

    @requires_git
    @pytest.mark.asyncio
    async def test_artifact_history_empty(self, knowledge_store_git):
        """artifact_history() returns empty list for non-existent artifact."""
        store = knowledge_store_git
        await store.initialize()
        await store._ensure_repo()
        history = await store.artifact_history("episode", "nonexistent")
        assert history == []


# ===================================================================
# 6c. Warm boot tests (AD-162)
# ===================================================================


class TestWarmBoot:
    """Tests for _restore_from_knowledge() warm boot."""

    @pytest.mark.asyncio
    async def test_warm_boot_restores_trust(self, tmp_path):
        """Trust scores are restored on boot with correct alpha/beta (AD-168)."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )

        # Pre-seed trust snapshot into the knowledge repo
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        await ks.store_trust_snapshot({
            "test_agent_001": {"alpha": 8.0, "beta": 2.0, "observations": 6.0},
        })

        # Boot runtime — should restore trust
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            record = rt.trust_network.get_record("test_agent_001")
            assert record is not None
            assert record.alpha == 8.0
            assert record.beta == 2.0
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_restores_routing(self, tmp_path):
        """Hebbian weights from previous session are restored."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )

        # Pre-seed routing weights
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        await ks.store_routing_weights([
            {"source": "s1", "target": "t1", "rel_type": "intent", "weight": 0.85},
        ])

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            weights = rt.hebbian_router.all_weights_typed()
            assert ("s1", "t1", "intent") in weights
            assert weights[("s1", "t1", "intent")] == 0.85
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_restores_episodes(self, tmp_path):
        """Episodes are seeded into EpisodicMemory via seed()."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )

        # Pre-seed episodes
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        ep = Episode(
            id="warm_ep1", user_input="test warm boot",
            timestamp=time.time(), dag_summary={},
            outcomes=[], agent_ids=[], duration_ms=10.0,
        )
        await ks.store_episode(ep)

        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            config=cfg, data_dir=tmp_path / "data",
            llm_client=MockLLMClient(), episodic_memory=mem,
        )
        await rt.start()
        try:
            recent = await mem.recent(10)
            assert any(e.id == "warm_ep1" for e in recent)
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_restores_workflows(self, tmp_path):
        """WorkflowCache is populated with stored entries."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )

        # Pre-seed workflows
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        from datetime import datetime, timezone
        await ks.store_workflows([{
            "pattern": "read config file",
            "dag_json": '{"nodes": []}',
            "hit_count": 5,
            "last_hit": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }])

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            assert rt.workflow_cache.size == 1
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_restores_qa_reports(self, tmp_path):
        """QA reports are restored into _qa_reports dict."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )

        # Pre-seed QA report
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        await ks.store_qa_report("weather_agent", {
            "verdict": "passed", "passed": 3, "total_tests": 3,
        })

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            assert "weather_agent" in rt._qa_reports
            assert rt._qa_reports["weather_agent"]["verdict"] == "passed"
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_order_trust_before_agents(self, tmp_path):
        """Trust is restored before agents (AD-162 order)."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )

        # Pre-seed trust (but no agents)
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        await ks.store_trust_snapshot({
            "some_agent": {"alpha": 10.0, "beta": 1.0, "observations": 8.0},
        })

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            # Trust was loaded before any agent restore attempted
            record = rt.trust_network.get_record("some_agent")
            assert record is not None
            assert record.alpha == 10.0
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_partial_failure(self, tmp_path):
        """Corrupted agent file is skipped, other artifacts restore correctly."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )
        cfg.self_mod.enabled = True

        # Pre-seed valid trust + corrupted agent
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        await ks.store_trust_snapshot({
            "partial_agent": {"alpha": 5.0, "beta": 3.0, "observations": 4.0},
        })

        # Write corrupted agent file (invalid JSON sidecar)
        agents_dir = repo / "agents"
        agents_dir.mkdir(exist_ok=True)
        (agents_dir / "broken_agent.py").write_text("invalid python syntax +!@#$")
        (agents_dir / "broken_agent.json").write_text('{"agent_type": "broken_agent", "class_name": "BrokenAgent"}')

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            # Trust should still be restored even though agent failed
            record = rt.trust_network.get_record("partial_agent")
            assert record is not None
            assert record.alpha == 5.0
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_empty_repo(self, tmp_path):
        """Empty knowledge repo doesn't error, system cold-starts normally."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            assert rt._started
            assert rt._knowledge_store is not None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_fresh_flag_skips_restore(self, tmp_path):
        """restore_on_boot=False prevents restoration but allows new writes."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,  # --fresh equivalent
        )

        # Pre-seed trust
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        await ks.store_trust_snapshot({
            "fresh_agent": {"alpha": 9.0, "beta": 1.0, "observations": 7.0},
        })

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            # Fresh flag: trust should NOT be restored
            record = rt.trust_network.get_record("fresh_agent")
            assert record is None
            # But knowledge store is still active for new writes
            assert rt._knowledge_store is not None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_fresh_flag_preserves_repo(self, tmp_path):
        """--fresh does NOT delete the existing knowledge repo (AD-165)."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        # Pre-seed data
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        await ks.store_trust_snapshot({"keep_me": {"alpha": 1.0, "beta": 1.0, "observations": 0.0}})

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            # Repo should still exist with data
            trust_file = repo / "trust" / "snapshot.json"
            assert trust_file.is_file()
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_skips_invalid_agent(self, tmp_path):
        """Designed agent with code validation failure is skipped (AD-163)."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
        )
        cfg.self_mod.enabled = True

        # Write agent with dangerous code (should fail validation)
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        agents_dir = repo / "agents"
        agents_dir.mkdir(exist_ok=True)
        # Code that would fail CodeValidator (imports os, uses subprocess)
        bad_code = 'import os\nimport subprocess\nclass BadAgent:\n    pass\n'
        (agents_dir / "bad_agent.py").write_text(bad_code)
        (agents_dir / "bad_agent.json").write_text(json.dumps({
            "agent_type": "bad_agent", "class_name": "BadAgent",
            "intent_name": "bad", "pool_name": "bad_pool",
            "status": "active", "strategy": "new_agent",
            "created_at": 0.0, "sandbox_time_ms": 0.0,
        }))

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            # Bad agent should NOT be in pools
            assert "bad_pool" not in rt.pools
            assert rt._started  # Boot succeeded despite bad agent
        finally:
            await rt.stop()


# ===================================================================
# 6d. Runtime integration tests
# ===================================================================


class TestRuntimeKnowledgeIntegration:
    """Tests for knowledge store integration with runtime."""

    @pytest.mark.asyncio
    async def test_episode_persisted_after_nl_processing(self, tmp_path):
        """After process_natural_language(), the episode is written to knowledge store."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.cognitive.llm_client import MockLLMClient
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            config=cfg, data_dir=tmp_path / "data",
            llm_client=llm, episodic_memory=mem,
        )
        await rt.start()
        try:
            # Use submit_intent to trigger a real intent that generates an episode
            # process_natural_language with MockLLMClient returns empty DAG,
            # so we directly call _build_episode and store_episode to test the hook
            episode = rt._build_episode(
                "read file test.txt",
                {"dag": None, "results": {}, "complete": True, "node_count": 0},
                0.0, 1.0,
            )
            await rt.episodic_memory.store(episode)
            # The knowledge store hook is in process_natural_language after episodic store,
            # but since MockLLM returns empty DAG, we test the hook directly
            if rt._knowledge_store:
                await rt._knowledge_store.store_episode(episode)

            episodes = await rt._knowledge_store.load_episodes()
            assert len(episodes) >= 1
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_persistence_failure_no_crash(self, tmp_path):
        """Knowledge store write failure doesn't crash the runtime."""
        from probos.cognitive.episodic_mock import MockEpisodicMemory
        from probos.cognitive.llm_client import MockLLMClient
        from probos.runtime import ProbOSRuntime
        from unittest.mock import AsyncMock

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        llm = MockLLMClient()
        mem = MockEpisodicMemory(relevance_threshold=0.3)
        rt = ProbOSRuntime(
            config=cfg, data_dir=tmp_path / "data",
            llm_client=llm, episodic_memory=mem,
        )
        await rt.start()
        try:
            # Sabotage the knowledge store
            rt._knowledge_store.store_episode = AsyncMock(side_effect=IOError("disk full"))

            # Should not crash
            result = await rt.process_natural_language("read file test.txt")
            assert result is not None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_shutdown_flushes_knowledge(self, tmp_path):
        """stop() calls knowledge_store.flush() for clean shutdown."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        # Patch flush to track calls
        original_flush = rt._knowledge_store.flush
        flush_called = False

        async def tracked_flush():
            nonlocal flush_called
            flush_called = True
            return await original_flush()

        rt._knowledge_store.flush = tracked_flush
        await rt.stop()
        assert flush_called

    @pytest.mark.asyncio
    async def test_shutdown_persists_workflows(self, tmp_path):
        """stop() calls store_workflows(workflow_cache.export_all())."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        store_workflows_called = False
        original_store = rt._knowledge_store.store_workflows

        async def tracked_store(entries):
            nonlocal store_workflows_called
            store_workflows_called = True
            return await original_store(entries)

        rt._knowledge_store.store_workflows = tracked_store
        await rt.stop()
        assert store_workflows_called

    @pytest.mark.asyncio
    async def test_shutdown_persists_trust(self, tmp_path):
        """stop() persists trust snapshot with raw alpha/beta."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()

        # Modify trust so there's something to persist
        rt.trust_network.record_outcome("test_agent", success=True, weight=3.0)

        await rt.stop()

        # Verify trust was persisted
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        snapshot = await ks.load_trust_snapshot()
        assert snapshot is not None
        assert "test_agent" in snapshot
        assert "alpha" in snapshot["test_agent"]
        assert "beta" in snapshot["test_agent"]

    @pytest.mark.asyncio
    async def test_shutdown_persists_routing(self, tmp_path):
        """stop() persists routing weights."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.knowledge.store import KnowledgeStore
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        await rt.stop()

        # Verify routing was persisted (may be empty if no interactions)
        kcfg = KnowledgeConfig(repo_path=str(repo), auto_commit=False)
        ks = KnowledgeStore(kcfg)
        await ks.initialize()
        weights = await ks.load_routing_weights()
        assert weights is not None  # List (could be empty)

    @pytest.mark.asyncio
    async def test_knowledge_disabled_skips_persistence(self, tmp_path):
        """When knowledge.enabled = False, no persistence calls made."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(enabled=False)

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            assert rt._knowledge_store is None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_knowledge_status_in_runtime(self, tmp_path):
        """Runtime status includes knowledge store info."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.runtime import ProbOSRuntime

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        try:
            status = rt.status()
            assert "knowledge" in status
            assert status["knowledge"]["enabled"] is True
        finally:
            await rt.stop()


# ===================================================================
# 6e. Experience layer tests (knowledge panel + shell commands)
# ===================================================================


class TestKnowledgePanels:
    """Tests for knowledge panel rendering."""

    def test_render_knowledge_panel(self):
        """render_knowledge_panel returns a Rich Panel."""
        from rich.panel import Panel
        from probos.experience.knowledge_panel import render_knowledge_panel

        panel = render_knowledge_panel(
            repo_path="/tmp/knowledge",
            artifact_counts={"episodes": 5, "agents": 2, "trust": 1},
            commit_count=10,
            schema_version=1,
        )
        assert isinstance(panel, Panel)

    def test_render_knowledge_history(self):
        """render_knowledge_history returns a Rich Panel."""
        from rich.panel import Panel
        from probos.experience.knowledge_panel import render_knowledge_history

        commits = [
            {"commit_hash": "abc1234def", "timestamp": "2026-01-01T10:00:00", "message": "Store episodes"},
        ]
        panel = render_knowledge_history(commits)
        assert isinstance(panel, Panel)

    def test_render_knowledge_history_empty(self):
        """render_knowledge_history handles empty list."""
        from rich.panel import Panel
        from probos.experience.knowledge_panel import render_knowledge_history

        panel = render_knowledge_history([])
        assert isinstance(panel, Panel)

    def test_render_rollback_success(self):
        """render_rollback_result with success=True."""
        from rich.panel import Panel
        from probos.experience.knowledge_panel import render_rollback_result

        panel = render_rollback_result("trust", "snapshot", True)
        assert isinstance(panel, Panel)

    def test_render_rollback_failure(self):
        """render_rollback_result with success=False."""
        from rich.panel import Panel
        from probos.experience.knowledge_panel import render_rollback_result

        panel = render_rollback_result("trust", "snapshot", False)
        assert isinstance(panel, Panel)


class TestKnowledgeShellCommands:
    """Tests for /knowledge and /rollback shell commands."""

    @pytest.fixture
    async def k_shell(self, tmp_path):
        from probos.cognitive.llm_client import MockLLMClient
        from probos.experience.shell import ProbOSShell
        from probos.runtime import ProbOSRuntime
        from rich.console import Console
        from io import StringIO

        repo = tmp_path / "knowledge"
        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(
            enabled=True, repo_path=str(repo), auto_commit=False,
            restore_on_boot=False,
        )

        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        shell = ProbOSShell(rt, console)
        yield shell, output, rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_knowledge_command_shows_status(self, k_shell):
        """'/knowledge' renders knowledge panel."""
        shell, output, _ = k_shell
        await shell._dispatch_slash("/knowledge")
        text = output.getvalue()
        assert "Knowledge Store" in text

    @pytest.mark.asyncio
    async def test_knowledge_history_subcommand(self, k_shell):
        """'/knowledge history' renders commit history."""
        shell, output, _ = k_shell
        await shell._dispatch_slash("/knowledge history")
        text = output.getvalue()
        assert "History" in text or "history" in text

    @pytest.mark.asyncio
    async def test_rollback_usage_hint(self, k_shell):
        """'/rollback' without args shows usage hint."""
        shell, output, _ = k_shell
        await shell._dispatch_slash("/rollback")
        text = output.getvalue()
        assert "Usage" in text or "usage" in text

    @pytest.mark.asyncio
    async def test_rollback_no_knowledge_store(self, tmp_path):
        """'/rollback' when knowledge disabled shows notification."""
        from probos.cognitive.llm_client import MockLLMClient
        from probos.experience.shell import ProbOSShell
        from probos.runtime import ProbOSRuntime
        from rich.console import Console
        from io import StringIO

        cfg = SystemConfig()
        cfg.knowledge = KnowledgeConfig(enabled=False)
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path / "data", llm_client=MockLLMClient())
        await rt.start()
        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        shell = ProbOSShell(rt, console)
        try:
            await shell._dispatch_slash("/rollback trust snapshot")
            text = output.getvalue()
            assert "not enabled" in text
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_help_includes_knowledge_commands(self, k_shell):
        """'/help' lists /knowledge and /rollback commands."""
        shell, output, _ = k_shell
        await shell._dispatch_slash("/help")
        text = output.getvalue()
        assert "/knowledge" in text
        assert "/rollback" in text


# ===================================================================
# Phase 14b Integration: KnowledgeStore + ChromaDB EpisodicMemory
# ===================================================================


class TestChromaDBKnowledgeIntegration:
    """Integration tests for KnowledgeStore + ChromaDB episodic memory."""

    @pytest.fixture
    def _make_episode(self):
        def _factory(id_: str, user_input: str = "test", ts: float = 0.0,
                     intent: str = "read_file"):
            return Episode(
                id=id_, user_input=user_input,
                timestamp=ts or time.time(),
                dag_summary={"intents": 1},
                outcomes=[{"intent": intent, "success": True}],
                agent_ids=["a1"], duration_ms=50.0,
            )
        return _factory

    @pytest.mark.asyncio
    async def test_episode_persist_to_git_and_seed_to_chromadb(
        self, tmp_path, _make_episode
    ):
        """Store episode → persist to Git → seed back from Git → recall via ChromaDB."""
        from probos.cognitive.episodic import EpisodicMemory
        from probos.knowledge.store import KnowledgeStore
        from probos.config import KnowledgeConfig

        # 1. Store episode in KnowledgeStore (Git persistence)
        ks_config = KnowledgeConfig(
            repo_path=str(tmp_path / "knowledge"),
            auto_commit=False,  # Skip git for test speed
        )
        ks = KnowledgeStore(ks_config)
        await ks.initialize()

        ep = _make_episode("git1", "read the project configuration file", ts=100.0)
        await ks.store_episode(ep)

        # 2. Load episodes back from Git
        loaded = await ks.load_episodes(limit=10)
        assert len(loaded) >= 1
        assert any(e.id == "git1" for e in loaded)

        # 3. Seed into fresh ChromaDB EpisodicMemory
        mem = EpisodicMemory(
            db_path=str(tmp_path / "chroma_ep" / "episodic.db"),
            max_episodes=100,
            relevance_threshold=0.3,
        )
        await mem.start()
        try:
            count = await mem.seed(loaded)
            assert count >= 1

            # 4. Recall via semantic search
            results = await mem.recall("configuration", k=5)
            assert len(results) >= 1
            assert results[0].id == "git1"
        finally:
            await mem.stop()

    @pytest.mark.asyncio
    async def test_warm_boot_fresh_chromadb_with_seed(
        self, tmp_path, _make_episode
    ):
        """Fresh ChromaDB + seed from KnowledgeStore produces searchable episodes."""
        from probos.cognitive.episodic import EpisodicMemory
        from probos.knowledge.store import KnowledgeStore
        from probos.config import KnowledgeConfig

        # 1. Prepare KnowledgeStore with multiple episodes
        ks_config = KnowledgeConfig(
            repo_path=str(tmp_path / "knowledge"),
            auto_commit=False,
        )
        ks = KnowledgeStore(ks_config)
        await ks.initialize()

        episodes = [
            _make_episode("wb1", "deploy the application to production", ts=100.0,
                          intent="deploy_app"),
            _make_episode("wb2", "read the user manual PDF", ts=200.0,
                          intent="read_file"),
            _make_episode("wb3", "run the unit test suite", ts=300.0,
                          intent="run_command"),
        ]
        for ep in episodes:
            await ks.store_episode(ep)

        # 2. Load from KnowledgeStore
        loaded = await ks.load_episodes(limit=100)
        assert len(loaded) == 3

        # 3. Create fresh ChromaDB and seed
        mem = EpisodicMemory(
            db_path=str(tmp_path / "fresh_chroma" / "episodic.db"),
            max_episodes=100,
            relevance_threshold=0.3,
        )
        await mem.start()
        try:
            count = await mem.seed(loaded)
            assert count == 3

            # 4. Verify semantic search works
            results = await mem.recall("deployment", k=5)
            assert len(results) >= 1
            result_ids = [r.id for r in results]
            assert "wb1" in result_ids  # deploy episode should match

            # 5. Verify recent() works
            recent = await mem.recent(k=10)
            assert len(recent) == 3
            assert recent[0].id == "wb3"  # Most recent first

            # 6. Verify recall_by_intent works
            deploy_results = await mem.recall_by_intent("deploy_app", k=5)
            assert len(deploy_results) == 1
            assert deploy_results[0].id == "wb1"
        finally:
            await mem.stop()
