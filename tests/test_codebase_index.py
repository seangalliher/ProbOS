"""Tests for CodebaseIndex service (AD-290)."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.cognitive.codebase_index import CodebaseIndex
from probos.cognitive.codebase_skill import create_codebase_skill
from probos.types import IntentMessage

# The real ProbOS source tree
_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src" / "probos"


@pytest.fixture
def index() -> CodebaseIndex:
    idx = CodebaseIndex(source_root=_SOURCE_ROOT)
    idx.build()
    return idx


class TestCodebaseIndex:
    def test_index_builds_successfully(self, index: CodebaseIndex):
        """build() completes without error and sets _built."""
        assert index._built is True
        assert len(index._file_tree) > 0

    def test_index_finds_agents(self, index: CodebaseIndex):
        """Agent map includes known agents like file_reader and introspect."""
        agent_types = {a["type"] for a in index.get_agent_map()}
        assert "file_reader" in agent_types
        assert "introspect" in agent_types

    def test_index_layer_map(self, index: CodebaseIndex):
        """Layer map includes the core architectural layers."""
        layers = set(index.get_layer_map().keys())
        for expected in ("substrate", "mesh", "consensus", "cognitive"):
            assert expected in layers, f"Missing layer: {expected}"

    def test_index_query_trust(self, index: CodebaseIndex):
        """Querying 'trust' returns files from consensus/trust.py."""
        result = index.query("trust")
        paths = [f["path"] for f in result["matching_files"]]
        assert any("consensus/trust.py" in p for p in paths)

    def test_index_query_dreaming(self, index: CodebaseIndex):
        """Querying 'dreaming' returns files from cognitive/dreaming.py."""
        result = index.query("dreaming")
        paths = [f["path"] for f in result["matching_files"]]
        assert any("cognitive/dreaming.py" in p for p in paths)

    def test_index_read_source(self, index: CodebaseIndex):
        """read_source returns contents for a known file."""
        content = index.read_source("config.py")
        assert "SystemConfig" in content
        assert len(content) > 100

    def test_index_read_source_bounded(self, index: CodebaseIndex):
        """read_source refuses to read outside src/probos/."""
        content = index.read_source("../../pyproject.toml")
        assert content == ""

    def test_index_api_surface(self, index: CodebaseIndex):
        """get_api_surface returns known methods for TrustNetwork."""
        methods = index.get_api_surface("TrustNetwork")
        method_names = {m["method"] for m in methods}
        assert "get_score" in method_names or "record_outcome" in method_names

    @pytest.mark.asyncio
    async def test_codebase_skill_dispatch(self, index: CodebaseIndex):
        """Codebase skill dispatches 'query' action correctly."""
        skill = create_codebase_skill(index)
        intent = IntentMessage(intent="codebase_knowledge", params={"action": "query", "query": "trust"})
        result = await skill.handler(intent)
        assert result.success
        assert isinstance(result.result, dict)
        assert "matching_files" in result.result
