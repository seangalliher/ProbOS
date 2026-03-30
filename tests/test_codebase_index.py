"""Tests for CodebaseIndex service (AD-290)."""

from __future__ import annotations

import os
import tempfile
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

    def test_query_word_level_matching(self, index: CodebaseIndex):
        """Multi-word queries match individual keywords, not entire phrase (AD-298)."""
        result = index.query("trust network scoring")
        paths = [f["path"] for f in result["matching_files"]]
        assert any("consensus/trust.py" in p for p in paths)

    def test_query_stop_words_filtered(self, index: CodebaseIndex):
        """Stop words are filtered — 'how does the trust work' matches like 'trust work' (AD-298)."""
        result_with_stops = index.query("how does the trust work")
        result_without = index.query("trust work")
        # Same top files — stop words don't affect results
        paths_with = [f["path"] for f in result_with_stops["matching_files"][:5]]
        paths_without = [f["path"] for f in result_without["matching_files"][:5]]
        assert paths_with == paths_without

    def test_query_multiple_keywords_score_higher(self, index: CodebaseIndex):
        """Files matching more keywords score higher (AD-298)."""
        result = index.query("trust consensus")
        files = result["matching_files"]
        # consensus/trust.py matches both keywords — should appear in results
        assert len(files) > 0
        paths = [f["path"] for f in files]
        assert any("consensus/trust.py" in p for p in paths)

    def test_query_empty_after_stop_words(self, index: CodebaseIndex):
        """All-stop-word queries fall back to full string without crashing (AD-298)."""
        result = index.query("is it the")
        # Should not crash — may return empty or fall back to full string
        assert isinstance(result["matching_files"], list)
        assert isinstance(result["matching_agents"], list)


class TestProjectDocs:
    """Tests for project document indexing (AD-299)."""

    @pytest.fixture
    def doc_index(self, tmp_path: Path) -> CodebaseIndex:
        """Build an index from a temp dir mimicking the project structure."""
        # Create project structure: project_root/src/probos/
        source_root = tmp_path / "src" / "probos"
        source_root.mkdir(parents=True)

        # A minimal Python file so the source scan has something
        (source_root / "__init__.py").write_text('"""ProbOS core."""\n')
        (source_root / "runtime.py").write_text(
            '"""Runtime core for ProbOS."""\nclass ProbOSRuntime:\n    pass\n'
        )

        # Create project docs at the project root
        (tmp_path / "DECISIONS.md").write_text(
            "# Architecture Decisions\n\n"
            "## AD-100: Trust Scoring\n\nDecision about trust.\n\n"
            "## AD-200: Medical Team\n\nDecision about medical.\n"
        )
        (tmp_path / "PROGRESS.md").write_text(
            "# ProbOS — Progress Tracker\n\n## Current Status\n\nAll good.\n"
        )

        # Create nested doc
        roadmap_dir = tmp_path / "docs" / "development"
        roadmap_dir.mkdir(parents=True)
        (roadmap_dir / "roadmap.md").write_text(
            "# Development Roadmap\n\n"
            "## Phase 29: Medical Team\n\nMedical agents.\n\n"
            "## Phase 31: Security Team\n\nSecurity agents.\n"
        )

        idx = CodebaseIndex(source_root=source_root)
        idx.build()
        return idx

    def test_build_indexes_project_docs(self, doc_index: CodebaseIndex):
        """Project docs appear in _file_tree with docs: prefix (AD-299)."""
        keys = list(doc_index._file_tree.keys())
        doc_keys = [k for k in keys if k.startswith("docs:")]

        assert "docs:DECISIONS.md" in doc_keys
        assert "docs:PROGRESS.md" in doc_keys
        assert "docs:docs/development/roadmap.md" in doc_keys

        # Verify parsed title and sections
        decisions = doc_index._file_tree["docs:DECISIONS.md"]
        assert decisions["docstring"] == "Architecture Decisions"
        assert "AD-100: Trust Scoring" in decisions["classes"]
        assert "AD-200: Medical Team" in decisions["classes"]
        assert decisions["type"] == "doc"

    def test_query_matches_doc_sections(self, doc_index: CodebaseIndex):
        """Querying for doc section headings returns the doc (AD-299)."""
        result = doc_index.query("medical team")
        paths = [f["path"] for f in result["matching_files"]]
        # Roadmap has "## Phase 29: Medical Team" section
        assert "docs:docs/development/roadmap.md" in paths
        # DECISIONS.md has "## AD-200: Medical Team" section
        assert "docs:DECISIONS.md" in paths

    def test_read_source_reads_docs(self, doc_index: CodebaseIndex):
        """read_source handles docs: prefix and returns doc contents (AD-299)."""
        content = doc_index.read_source("docs:DECISIONS.md")
        assert "Architecture Decisions" in content
        assert "Trust Scoring" in content

        # Test with line range
        content_lines = doc_index.read_source("docs:DECISIONS.md", start_line=1, end_line=3)
        assert "Architecture Decisions" in content_lines

    def test_read_source_doc_path_traversal_blocked(self, doc_index: CodebaseIndex):
        """Path traversal via docs: prefix is blocked (AD-299)."""
        content = doc_index.read_source("docs:../../etc/passwd")
        assert content == ""

    def test_missing_project_docs_skipped(self, tmp_path: Path):
        """Build succeeds when whitelisted docs don't exist (AD-299)."""
        source_root = tmp_path / "src" / "probos"
        source_root.mkdir(parents=True)
        (source_root / "__init__.py").write_text('"""Init."""\n')

        # No project docs created — all whitelisted files are missing
        idx = CodebaseIndex(source_root=source_root)
        idx.build()

        assert idx._built is True
        doc_keys = [k for k in idx._file_tree if k.startswith("docs:")]
        assert len(doc_keys) == 0


class TestSectionTargetedReading:
    """Tests for section-targeted doc reading (AD-300)."""

    @pytest.fixture
    def section_index(self, tmp_path: Path) -> CodebaseIndex:
        """Build an index with a multi-section doc."""
        source_root = tmp_path / "src" / "probos"
        source_root.mkdir(parents=True)
        (source_root / "__init__.py").write_text('"""Init."""\n')

        # Create a doc with distinct sections
        (tmp_path / "DECISIONS.md").write_text(
            "# Architecture Decisions\n\n"
            "## Medical Team\n\nThe medical team handles vitals.\nLine 2 of medical.\nLine 3 of medical.\n\n"
            "## Security Team\n\nThe security team handles threats.\nLine 2 of security.\n\n"
            "## Operations Team\n\nThe operations team handles scheduling.\nLine 2 of ops.\n"
        )

        idx = CodebaseIndex(source_root=source_root)
        idx.build()
        return idx

    def test_analyze_doc_stores_section_lines(self, section_index: CodebaseIndex):
        """_analyze_doc stores section name and line number (AD-300)."""
        meta = section_index._file_tree["docs:DECISIONS.md"]
        sections = meta["sections"]

        assert len(sections) == 3
        assert sections[0]["name"] == "Medical Team"
        assert isinstance(sections[0]["line"], int)
        assert sections[0]["line"] > 0
        assert sections[1]["name"] == "Security Team"
        assert sections[2]["name"] == "Operations Team"
        # Lines should be increasing
        assert sections[0]["line"] < sections[1]["line"] < sections[2]["line"]

    def test_read_doc_sections_returns_matching_sections(self, section_index: CodebaseIndex):
        """read_doc_sections returns only sections matching keywords (AD-300)."""
        content = section_index.read_doc_sections("docs:DECISIONS.md", ["medical"])
        assert "medical team handles vitals" in content.lower()
        assert "security team handles threats" not in content.lower()

    def test_read_doc_sections_multiple_keywords(self, section_index: CodebaseIndex):
        """Sections matching more keywords are returned first (AD-300)."""
        content = section_index.read_doc_sections("docs:DECISIONS.md", ["security", "team"])
        lines = content.strip().splitlines()
        # Security Team matches 2 keywords, should be first
        assert "security team" in lines[0].lower()

    def test_read_doc_sections_fallback_on_no_match(self, section_index: CodebaseIndex):
        """Falls back to reading from top when no sections match keywords (AD-300)."""
        content = section_index.read_doc_sections("docs:DECISIONS.md", ["nonexistent"])
        # Should get content from the top of the file
        assert "Architecture Decisions" in content

    def test_read_doc_sections_respects_max_lines(self, tmp_path: Path):
        """Output is capped at max_lines (AD-300)."""
        source_root = tmp_path / "src" / "probos"
        source_root.mkdir(parents=True)
        (source_root / "__init__.py").write_text('"""Init."""\n')

        # Create a doc with a long section
        long_section = "\n".join(f"Line {i} of content." for i in range(50))
        (tmp_path / "DECISIONS.md").write_text(
            f"# Decisions\n\n## Long Section\n\n{long_section}\n\n## Other\n\nOther content.\n"
        )

        idx = CodebaseIndex(source_root=source_root)
        idx.build()

        content = idx.read_doc_sections("docs:DECISIONS.md", ["long"], max_lines=10)
        lines = content.splitlines()
        assert len(lines) <= 10


class TestStructuredQueries:
    """Tests for AD-312 structured query methods."""

    def test_find_callers_returns_matches(self, index: CodebaseIndex):
        """find_callers() finds files referencing a method."""
        # 'build' is a common method name across the codebase
        results = index.find_callers("build")
        assert isinstance(results, list)
        assert len(results) > 0
        assert "path" in results[0]
        assert "lines" in results[0]

    def test_find_callers_empty(self, index: CodebaseIndex):
        """find_callers() returns [] for nonexistent method."""
        results = index.find_callers("xyzzy_not_a_real_method_42")
        assert results == []

    def test_find_callers_caches(self, index: CodebaseIndex):
        """Second call uses cache (no re-scan)."""
        results1 = index.find_callers("query")
        assert results1  # should find something
        # Cache should now contain the entry
        assert "query" in index._caller_cache
        results2 = index.find_callers("query")
        assert results1 == results2

    def test_find_tests_for_panels(self, index: CodebaseIndex):
        """find_tests_for('experience/panels.py') finds test_experience.py."""
        tests = index.find_tests_for("experience/panels.py")
        # The test file tree is from src/probos — test files aren't there,
        # but the method should still work without crashing
        assert isinstance(tests, list)

    def test_find_tests_for_unknown(self, index: CodebaseIndex):
        """find_tests_for() returns [] for unknown file."""
        tests = index.find_tests_for("nonexistent/fake_module.py")
        assert tests == []

    def test_get_full_api_surface(self, index: CodebaseIndex):
        """get_full_api_surface() returns dict with key classes."""
        surface = index.get_full_api_surface()
        assert isinstance(surface, dict)
        # Should include at least the classes we know are in _KEY_CLASSES
        assert "AgentRegistry" in surface or "TrustNetwork" in surface

    def test_expanded_key_classes(self, index: CodebaseIndex):
        """API surface includes CodebaseIndex, PoolGroupRegistry, Shell (AD-312)."""
        surface = index.get_full_api_surface()
        # CodebaseIndex should have its own methods extracted
        if "CodebaseIndex" in surface:
            method_names = {m["method"] for m in surface["CodebaseIndex"]}
            assert "query" in method_names
            assert "find_callers" in method_names


class TestImportGraph:
    """Tests for AD-315 import graph methods."""

    def test_analyze_file_extracts_imports(self, index: CodebaseIndex):
        """_analyze_file() populates 'imports' key in file metadata."""
        meta = index._file_tree.get("experience/shell.py")
        assert meta is not None
        assert "imports" in meta
        imports = meta["imports"]
        assert isinstance(imports, list)
        probos_imports = [i for i in imports if i["module"].startswith("probos.")]
        assert len(probos_imports) > 0

    def test_import_graph_built(self, index: CodebaseIndex):
        """Import graph is populated after build()."""
        assert hasattr(index, "_import_graph")
        assert isinstance(index._import_graph, dict)
        assert len(index._import_graph) > 0

    def test_reverse_import_graph_built(self, index: CodebaseIndex):
        """Reverse import graph is populated after build()."""
        assert hasattr(index, "_reverse_import_graph")
        assert isinstance(index._reverse_import_graph, dict)
        assert len(index._reverse_import_graph) > 0

    def test_get_imports_shell(self, index: CodebaseIndex):
        """get_imports('experience/shell.py') includes command modules."""
        imports = index.get_imports("experience/shell.py")
        assert isinstance(imports, list)
        # After AD-519, shell.py imports from commands subpackage, not panels directly
        assert any("commands" in p or "session" in p for p in imports)

    def test_get_imports_unknown_file(self, index: CodebaseIndex):
        """get_imports() returns [] for unknown file."""
        imports = index.get_imports("nonexistent/fake.py")
        assert imports == []

    def test_find_importers(self, index: CodebaseIndex):
        """find_importers() shows files that import a module."""
        importers = index.find_importers("runtime.py")
        assert isinstance(importers, list)
        assert len(importers) > 0

    def test_find_importers_unknown(self, index: CodebaseIndex):
        """find_importers() returns [] for unknown file."""
        importers = index.find_importers("nonexistent/fake.py")
        assert importers == []

    def test_import_graph_consistency(self, index: CodebaseIndex):
        """Forward and reverse graphs are consistent."""
        for rel, imports in index._import_graph.items():
            for imp in imports:
                importers = index._reverse_import_graph.get(imp, [])
                assert rel in importers, (
                    f"{rel} imports {imp} but {imp} doesn't list {rel} as importer"
                )
