"""Distribution + runtime integration tests for Phase 22 (AD-253).

Tests cover:
- Runtime integration: utility agent pools, descriptors, config gating
- Distribution: `probos init`, FastAPI endpoints, WebSocket
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
async def runtime(tmp_path):
    """Runtime with MockLLMClient and utility agents enabled."""
    llm = MockLLMClient()
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


@pytest.fixture
async def runtime_no_utility(tmp_path):
    """Runtime with utility agents disabled."""
    config = SystemConfig()
    config.utility_agents.enabled = False
    llm = MockLLMClient()
    rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


# ------------------------------------------------------------------
# Runtime integration tests
# ------------------------------------------------------------------

class TestUtilityRuntimeIntegration:
    """Runtime-level tests for utility agent registration and lifecycle."""

    UTILITY_POOLS = {
        "web_search", "page_reader", "weather", "news",
        "translator", "summarizer", "calculator",
        "todo_manager", "note_taker", "scheduler",
    }

    UTILITY_INTENTS = {
        "web_search", "read_page", "get_weather", "get_news",
        "translate_text", "summarize_text", "calculate",
        "manage_todo", "manage_notes", "manage_schedule",
    }

    @pytest.mark.asyncio
    async def test_all_utility_pools_created(self, runtime):
        """All 10 utility pool types are created at boot."""
        pool_names = set(runtime.pools.keys())
        assert self.UTILITY_POOLS.issubset(pool_names), (
            f"Missing utility pools: {self.UTILITY_POOLS - pool_names}"
        )

    @pytest.mark.asyncio
    async def test_utility_agents_have_llm_client(self, runtime):
        """Utility agents have llm_client reference set."""
        for pool_name in self.UTILITY_POOLS:
            pool = runtime.pools[pool_name]
            for agent_id in pool._agent_ids:
                agent = runtime.registry.get(agent_id)
                assert agent is not None
                assert agent._llm_client is not None, (
                    f"Agent {agent_id} in pool {pool_name} has no llm_client"
                )

    @pytest.mark.asyncio
    async def test_utility_agents_have_runtime(self, runtime):
        """Utility agents have runtime reference set."""
        for pool_name in self.UTILITY_POOLS:
            pool = runtime.pools[pool_name]
            for agent_id in pool._agent_ids:
                agent = runtime.registry.get(agent_id)
                assert agent is not None
                assert agent._runtime is not None, (
                    f"Agent {agent_id} in pool {pool_name} has no runtime"
                )

    @pytest.mark.asyncio
    async def test_intent_descriptors_include_utility(self, runtime):
        """_collect_intent_descriptors() includes all utility agent intents."""
        descriptors = runtime.decomposer._intent_descriptors
        descriptor_names = {d.name for d in descriptors}
        assert self.UTILITY_INTENTS.issubset(descriptor_names), (
            f"Missing utility intents: {self.UTILITY_INTENTS - descriptor_names}"
        )

    @pytest.mark.asyncio
    async def test_disabled_skips_utility_pools(self, runtime_no_utility):
        """utility_agents.enabled: false skips utility pool creation."""
        pool_names = set(runtime_no_utility.pools.keys())
        overlap = self.UTILITY_POOLS & pool_names
        assert len(overlap) == 0, (
            f"Utility pools should not exist when disabled: {overlap}"
        )

    @pytest.mark.asyncio
    async def test_status_includes_utility_pools(self, runtime):
        """Runtime status() includes utility agent pools."""
        status = runtime.status()
        for pool_name in self.UTILITY_POOLS:
            assert pool_name in status["pools"], (
                f"Pool {pool_name} missing from status"
            )

    @pytest.mark.asyncio
    async def test_total_agent_count(self, runtime):
        """Total agent count includes utility agents (~47 total)."""
        status = runtime.status()
        total = status["total_agents"]
        # 20 utility (10 pools × 2) + core agents
        assert total >= 40, f"Expected >= 40 agents, got {total}"

    @pytest.mark.asyncio
    async def test_utility_nl_query(self, runtime):
        """Utility agents respond to NL queries via MockLLMClient."""
        result = await runtime.process_natural_language("what's the weather in Paris")
        assert result["node_count"] >= 1
        assert result["complete"]


# ------------------------------------------------------------------
# Distribution tests: probos init
# ------------------------------------------------------------------

class TestProbOSInit:
    """Tests for `probos init` config wizard."""

    def test_init_creates_directory_structure(self, tmp_path):
        """probos init creates ~/.probos/ with subdirectories."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        args = argparse.Namespace(probos_home=str(home), force=False)

        # Simulate user input (enter defaults)
        with patch("builtins.input", return_value=""):
            _cmd_init(args)

        assert home.exists()
        assert (home / "config.yaml").exists()
        assert (home / "data").is_dir()
        assert (home / "notes").is_dir()

    def test_init_creates_valid_yaml(self, tmp_path):
        """probos init creates a parseable YAML config."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        args = argparse.Namespace(probos_home=str(home), force=False)

        with patch("builtins.input", return_value=""):
            _cmd_init(args)

        content = (home / "config.yaml").read_text()
        config = yaml.safe_load(content)
        assert isinstance(config, dict)
        assert config["system"]["name"] == "ProbOS"
        assert "cognitive" in config
        assert config.get("utility_agents", {}).get("enabled") is True

    def test_init_force_overwrites(self, tmp_path):
        """probos init --force overwrites existing config."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        home.mkdir()
        (home / "config.yaml").write_text("old: true")

        args = argparse.Namespace(probos_home=str(home), force=True)
        with patch("builtins.input", return_value=""):
            _cmd_init(args)

        content = (home / "config.yaml").read_text()
        assert "old: true" not in content
        assert "ProbOS" in content

    def test_init_skips_without_force(self, tmp_path, capsys):
        """probos init without --force skips if config exists."""
        from probos.__main__ import _cmd_init
        import argparse

        home = tmp_path / ".probos"
        home.mkdir()
        (home / "config.yaml").write_text("existing: true")

        args = argparse.Namespace(probos_home=str(home), force=False)
        _cmd_init(args)

        content = (home / "config.yaml").read_text()
        assert content == "existing: true"


class TestProbOSReset:
    """Tests for ``probos reset`` CLI subcommand (BF-070: Tiered Reset)."""

    def _make_repo(self, tmp_path):
        """Create a fake KnowledgeStore directory with sample files."""
        from probos.__main__ import _RESET_SUBDIRS
        repo = tmp_path / "knowledge"
        for sub in _RESET_SUBDIRS:
            d = repo / sub
            d.mkdir(parents=True, exist_ok=True)
            (d / "sample.json").write_text("{}")
            (d / "sample.py").write_text("# code")
            (d / ".gitkeep").write_text("")
        return repo

    def _make_data_dir(self, tmp_path):
        """Create a data dir with files across all tiers."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # Tier 1 (transients)
        (data_dir / "events.db").write_text("events")
        (data_dir / "scheduled_tasks.db").write_text("tasks")
        cp_dir = data_dir / "checkpoints"
        cp_dir.mkdir()
        (cp_dir / "dag1.json").write_text("{}")
        # Tier 2 (cognition + identity) — session_last.json lives here now
        (data_dir / "session_last.json").write_text("{}")
        (data_dir / "chroma.sqlite3").write_text("chroma")
        (data_dir / "cognitive_journal.db").write_text("journal")
        (data_dir / "hebbian_weights.db").write_text("hebbian")
        (data_dir / "trust.db").write_text("trust")
        (data_dir / "service_profiles.db").write_text("profiles")
        sem_dir = data_dir / "semantic"
        sem_dir.mkdir()
        (sem_dir / "index.bin").write_text("idx")
        (data_dir / "identity.db").write_text("identity")
        (data_dir / "acm.db").write_text("acm")
        (data_dir / "skills.db").write_text("skills")
        (data_dir / "directives.db").write_text("directives")
        ont_dir = data_dir / "ontology"
        ont_dir.mkdir()
        (ont_dir / "instance_id").write_text("did:probos:old")
        # Tier 3 (institutional knowledge)
        (data_dir / "ward_room.db").write_text("ward room data")
        (data_dir / "workforce.db").write_text("workforce")
        sr_dir = data_dir / "ship-records"
        sr_dir.mkdir()
        (sr_dir / "log.md").write_text("captain's log")
        scout_dir = data_dir / "scout_reports"
        scout_dir.mkdir()
        (scout_dir / "report.json").write_text("{}")
        return data_dir

    def _reset_args(self, data_dir, **overrides):
        """Create argparse Namespace for reset with tier flags."""
        defaults = dict(
            yes=True, soft=False, full=False,
            dry_run=False, wipe_records=False, config=None, data_dir=data_dir,
        )
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_tier1_soft_only_clears_transients(self, tmp_path):
        """--soft (Tier 1) clears only runtime transients, preserves timeline."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, soft=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Tier 1 files cleared
        assert not (data_dir / "events.db").exists()
        assert not (data_dir / "scheduled_tasks.db").exists()
        assert len(list((data_dir / "checkpoints").glob("*.json"))) == 0

        # session_last.json SURVIVES soft reset (timeline intact for stasis recovery)
        assert (data_dir / "session_last.json").exists()

        # Tier 2+ files preserved
        assert (data_dir / "chroma.sqlite3").exists()
        assert (data_dir / "trust.db").exists()
        assert (data_dir / "hebbian_weights.db").exists()
        assert (data_dir / "identity.db").exists()
        assert (data_dir / "ward_room.db").exists()

    def test_tier2_default_clears_cognition_and_identity(self, tmp_path):
        """Default reset (Tier 2) clears cognition + identity, preserves institutional."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir)  # no tier flag = default Tier 2

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Tier 1+2 files cleared
        assert not (data_dir / "session_last.json").exists()
        assert not (data_dir / "chroma.sqlite3").exists()
        assert not (data_dir / "trust.db").exists()
        assert not (data_dir / "hebbian_weights.db").exists()
        assert not (data_dir / "cognitive_journal.db").exists()
        assert not (data_dir / "service_profiles.db").exists()
        assert not (data_dir / "identity.db").exists()
        assert not (data_dir / "acm.db").exists()
        assert not (data_dir / "skills.db").exists()
        assert not (data_dir / "directives.db").exists()
        assert not (data_dir / "ontology" / "instance_id").exists()
        assert not (data_dir / "events.db").exists()

        # Tier 3 files preserved
        assert (data_dir / "ward_room.db").exists()
        assert (data_dir / "workforce.db").exists()
        assert (data_dir / "ship-records").is_dir()
        assert (data_dir / "scout_reports").is_dir()

        # Knowledge subdirs cleared (Tier 2 special)
        for sub in ("episodes", "agents", "routing"):
            assert not list((repo / sub).glob("*.json"))
            assert not list((repo / sub).glob("*.py"))

    def test_tier3_full_clears_everything(self, tmp_path):
        """--full (Tier 3) clears everything including records."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, full=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # All tiers cleared
        assert not (data_dir / "session_last.json").exists()
        assert not (data_dir / "chroma.sqlite3").exists()
        assert not (data_dir / "identity.db").exists()
        assert not (data_dir / "ward_room.db").exists()
        assert not (data_dir / "workforce.db").exists()

        # Ward Room archived
        archives = list((data_dir / "archives").glob("ward_room_*.db"))
        assert len(archives) == 1
        assert archives[0].read_text() == "ward room data"

    def test_wipe_records_is_alias_for_full(self, tmp_path):
        """--wipe-records backward compat alias triggers Tier 3."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, wipe_records=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Same as Tier 4 — everything cleared
        assert not (data_dir / "ward_room.db").exists()
        assert not (data_dir / "workforce.db").exists()
        assert not (data_dir / "identity.db").exists()

    def test_dry_run_changes_nothing(self, tmp_path):
        """--dry-run shows what would happen but doesn't delete anything."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        args = self._reset_args(data_dir, dry_run=True)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Everything should still exist
        assert (data_dir / "session_last.json").exists()
        assert (data_dir / "chroma.sqlite3").exists()
        assert (data_dir / "identity.db").exists()
        assert (data_dir / "ward_room.db").exists()

    def test_chromadb_uuid_dirs_cleaned(self, tmp_path):
        """Default reset (Tier 2) cleans UUID-named ChromaDB HNSW index directories."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = self._make_data_dir(tmp_path)
        # Create a UUID-named dir (ChromaDB HNSW index)
        uuid_dir = data_dir / "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        uuid_dir.mkdir()
        (uuid_dir / "index.bin").write_text("hnsw data")

        args = self._reset_args(data_dir)  # Default = Tier 2 (includes ChromaDB cleanup)

        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        assert not uuid_dir.exists()

    def test_reset_no_crash_empty_repo(self, tmp_path):
        """Reset on a nonexistent knowledge dir doesn't crash."""
        from probos.__main__ import _cmd_reset

        repo = tmp_path / "nonexistent_knowledge"
        data_dir = tmp_path / "data"

        args = self._reset_args(data_dir)
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)  # Should not raise


# ------------------------------------------------------------------
# Distribution tests: FastAPI endpoints
# ------------------------------------------------------------------

class TestFastAPIEndpoints:
    """Tests for the REST API and WebSocket server."""

    @pytest.fixture
    async def app_and_runtime(self, tmp_path):
        """Create a FastAPI app with a running runtime."""
        llm = MockLLMClient()
        rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
        await rt.start()
        app = create_app(rt)
        yield app, rt
        await rt.stop()

    @pytest.mark.asyncio
    async def test_health_endpoint(self, app_and_runtime):
        """GET /api/health returns correct JSON structure."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["agents"], int)
        assert data["agents"] > 0
        assert isinstance(data["health"], float)

    @pytest.mark.asyncio
    async def test_status_endpoint(self, app_and_runtime):
        """GET /api/status returns runtime status."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/status")

        assert resp.status_code == 200
        data = resp.json()
        assert "total_agents" in data
        assert "pools" in data

    @pytest.mark.asyncio
    async def test_chat_endpoint(self, app_and_runtime):
        """POST /api/chat processes message and returns response."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/chat",
                json={"message": "hello"},
                timeout=30.0,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "dag" in data
        assert "results" in data

    @pytest.mark.asyncio
    async def test_create_app_returns_fastapi(self):
        """create_app() returns a FastAPI instance."""
        from fastapi import FastAPI

        class FakeRuntime:
            def status(self):
                return {"total_agents": 0}

        app = create_app(FakeRuntime())
        assert isinstance(app, FastAPI)
        assert app.title == "ProbOS"

    @pytest.mark.asyncio
    async def test_enrich_endpoint_returns_enriched(self, app_and_runtime):
        """POST /api/selfmod/enrich returns enriched spec from LLM."""
        from httpx import ASGITransport, AsyncClient

        app, rt = app_and_runtime
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/selfmod/enrich",
                json={
                    "intent_name": "lookup_person",
                    "intent_description": "Look up a person online",
                    "parameters": {"name": "<person_name>"},
                    "user_guidance": "Search DuckDuckGo, find LinkedIn profiles",
                },
                timeout=30.0,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "enriched" in data
        assert len(data["enriched"]) > 0
        assert data["status"] == "ok"
        assert data["intent_name"] == "lookup_person"

    @pytest.mark.asyncio
    async def test_enrich_endpoint_fallback_without_llm(self):
        """Enrich returns user_guidance when no LLM is available."""
        from httpx import ASGITransport, AsyncClient

        class NoLLMRuntime:
            def status(self):
                return {"total_agents": 0}

        app = create_app(NoLLMRuntime())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/selfmod/enrich",
                json={
                    "intent_name": "test_intent",
                    "intent_description": "A test",
                    "parameters": {},
                    "user_guidance": "My raw guidance text",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["enriched"] == "My raw guidance text"
        assert data["status"] == "no_llm"
