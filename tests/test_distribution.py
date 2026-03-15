"""Distribution + runtime integration tests for Phase 22 (AD-253).

Tests cover:
- Runtime integration: bundled agent pools, descriptors, config gating
- Distribution: `probos init`, FastAPI endpoints, WebSocket
"""

from __future__ import annotations

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
    """Runtime with MockLLMClient and bundled agents enabled."""
    llm = MockLLMClient()
    rt = ProbOSRuntime(data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


@pytest.fixture
async def runtime_no_bundled(tmp_path):
    """Runtime with bundled agents disabled."""
    config = SystemConfig()
    config.bundled_agents.enabled = False
    llm = MockLLMClient()
    rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


# ------------------------------------------------------------------
# Runtime integration tests
# ------------------------------------------------------------------

class TestBundledRuntimeIntegration:
    """Runtime-level tests for bundled agent registration and lifecycle."""

    BUNDLED_POOLS = {
        "web_search", "page_reader", "weather", "news",
        "translator", "summarizer", "calculator",
        "todo_manager", "note_taker", "scheduler",
    }

    BUNDLED_INTENTS = {
        "web_search", "read_page", "get_weather", "get_news",
        "translate_text", "summarize_text", "calculate",
        "manage_todo", "manage_notes", "manage_schedule",
    }

    @pytest.mark.asyncio
    async def test_all_bundled_pools_created(self, runtime):
        """All 10 bundled pool types are created at boot."""
        pool_names = set(runtime.pools.keys())
        assert self.BUNDLED_POOLS.issubset(pool_names), (
            f"Missing bundled pools: {self.BUNDLED_POOLS - pool_names}"
        )

    @pytest.mark.asyncio
    async def test_bundled_agents_have_llm_client(self, runtime):
        """Bundled agents have llm_client reference set."""
        for pool_name in self.BUNDLED_POOLS:
            pool = runtime.pools[pool_name]
            for agent_id in pool._agent_ids:
                agent = runtime.registry.get(agent_id)
                assert agent is not None
                assert agent._llm_client is not None, (
                    f"Agent {agent_id} in pool {pool_name} has no llm_client"
                )

    @pytest.mark.asyncio
    async def test_bundled_agents_have_runtime(self, runtime):
        """Bundled agents have runtime reference set."""
        for pool_name in self.BUNDLED_POOLS:
            pool = runtime.pools[pool_name]
            for agent_id in pool._agent_ids:
                agent = runtime.registry.get(agent_id)
                assert agent is not None
                assert agent._runtime is not None, (
                    f"Agent {agent_id} in pool {pool_name} has no runtime"
                )

    @pytest.mark.asyncio
    async def test_intent_descriptors_include_bundled(self, runtime):
        """_collect_intent_descriptors() includes all bundled agent intents."""
        descriptors = runtime.decomposer._intent_descriptors
        descriptor_names = {d.name for d in descriptors}
        assert self.BUNDLED_INTENTS.issubset(descriptor_names), (
            f"Missing bundled intents: {self.BUNDLED_INTENTS - descriptor_names}"
        )

    @pytest.mark.asyncio
    async def test_disabled_skips_bundled_pools(self, runtime_no_bundled):
        """bundled_agents.enabled: false skips bundled pool creation."""
        pool_names = set(runtime_no_bundled.pools.keys())
        overlap = self.BUNDLED_POOLS & pool_names
        assert len(overlap) == 0, (
            f"Bundled pools should not exist when disabled: {overlap}"
        )

    @pytest.mark.asyncio
    async def test_status_includes_bundled_pools(self, runtime):
        """Runtime status() includes bundled agent pools."""
        status = runtime.status()
        for pool_name in self.BUNDLED_POOLS:
            assert pool_name in status["pools"], (
                f"Pool {pool_name} missing from status"
            )

    @pytest.mark.asyncio
    async def test_total_agent_count(self, runtime):
        """Total agent count includes bundled agents (~47 total)."""
        status = runtime.status()
        total = status["total_agents"]
        # 20 bundled (10 pools × 2) + core agents
        assert total >= 40, f"Expected >= 40 agents, got {total}"

    @pytest.mark.asyncio
    async def test_bundled_nl_query(self, runtime):
        """Bundled agents respond to NL queries via MockLLMClient."""
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
        assert config.get("bundled_agents", {}).get("enabled") is True

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
    """Tests for ``probos reset`` CLI subcommand (AD-264)."""

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

    def test_reset_clears_artifacts(self, tmp_path):
        """Reset deletes *.json and *.py from all subdirs, keeps dirs and .gitkeep."""
        import argparse
        from probos.__main__ import _cmd_reset, _RESET_SUBDIRS

        repo = self._make_repo(tmp_path)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        args = argparse.Namespace(
            yes=True, keep_trust=False, config=None, data_dir=data_dir,
        )
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        for sub in _RESET_SUBDIRS:
            d = repo / sub
            assert d.is_dir(), f"{sub}/ directory should still exist"
            assert not list(d.glob("*.json")), f"{sub}/ should have no .json files"
            assert not list(d.glob("*.py")), f"{sub}/ should have no .py files"
            assert (d / ".gitkeep").exists(), f"{sub}/.gitkeep should survive"

    def test_reset_keeps_trust_with_flag(self, tmp_path):
        """--keep-trust preserves trust/ but clears everything else."""
        import argparse
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        args = argparse.Namespace(
            yes=True, keep_trust=True, config=None, data_dir=data_dir,
        )
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        # Trust files should survive
        assert (repo / "trust" / "sample.json").exists()
        assert (repo / "trust" / "sample.py").exists()
        # Other dirs should be cleared
        assert not list((repo / "episodes").glob("*.json"))
        assert not list((repo / "agents").glob("*.py"))

    def test_reset_clears_chromadb(self, tmp_path):
        """Reset removes the chroma/ directory."""
        import argparse
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = tmp_path / "data"
        chroma_dir = data_dir / "chroma"
        chroma_dir.mkdir(parents=True)
        (chroma_dir / "chroma.sqlite3").write_text("fake")

        args = argparse.Namespace(
            yes=True, keep_trust=False, config=None, data_dir=data_dir,
        )
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            from types import SimpleNamespace
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        assert not chroma_dir.exists()

    def test_reset_no_crash_empty_repo(self, tmp_path):
        """Reset on a nonexistent knowledge dir doesn't crash."""
        import argparse
        from probos.__main__ import _cmd_reset

        repo = tmp_path / "nonexistent_knowledge"
        data_dir = tmp_path / "data"

        args = argparse.Namespace(
            yes=True, keep_trust=False, config=None, data_dir=data_dir,
        )
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
