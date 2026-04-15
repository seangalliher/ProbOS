"""Tests for AD-596a: Cognitive Skill Catalog — SKILL.md format + loader."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    CognitiveSkillEntry,
    get_skill_body,
    parse_skill_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_SKILL_MD = """\
---
name: architecture-review
description: >
  Analyze proposed system designs against ProbOS architectural principles.
  Use when reviewing design proposals, enhancement requests, or refactoring plans.
license: Apache-2.0
compatibility: Requires CodebaseIndex access
metadata:
  probos-department: science
  probos-skill-id: architecture_review
  probos-min-proficiency: 3
  probos-min-rank: lieutenant
  probos-intents: "design_feature review_architecture"
---

# Architecture Review

## When to Use
Use this skill when reviewing design proposals or refactoring plans.

## Instructions
1. Check against SOLID principles.
2. Verify Law of Demeter compliance.
"""

MINIMAL_SKILL_MD = """\
---
name: basic-skill
description: A simple skill with only required fields.
---

# Basic Skill

Just a basic skill.
"""

EXTERNAL_SKILL_MD = """\
---
name: external-tool
description: An external AgentSkills.io skill with no ProbOS metadata.
license: MIT
compatibility: Requires network access
---

# External Tool

Generic instructions.
"""


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Create a temporary skills directory with test skill files."""
    # Full skill
    full_dir = tmp_path / "architecture-review"
    full_dir.mkdir()
    (full_dir / "SKILL.md").write_text(FULL_SKILL_MD, encoding="utf-8")

    # Minimal skill
    min_dir = tmp_path / "basic-skill"
    min_dir.mkdir()
    (min_dir / "SKILL.md").write_text(MINIMAL_SKILL_MD, encoding="utf-8")

    # External skill
    ext_dir = tmp_path / "external-tool"
    ext_dir.mkdir()
    (ext_dir / "SKILL.md").write_text(EXTERNAL_SKILL_MD, encoding="utf-8")

    # Directory with no SKILL.md (should be skipped)
    noise_dir = tmp_path / "not-a-skill"
    noise_dir.mkdir()
    (noise_dir / "README.md").write_text("Not a skill.", encoding="utf-8")

    return tmp_path


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_skills.db")


# ===========================================================================
# SkillFileLoader / Parsing Tests
# ===========================================================================


class TestSkillFileParsing:
    """Tests for parse_skill_file() and get_skill_body()."""

    def test_parse_valid_skill_md(self, skills_dir: Path) -> None:
        """Full frontmatter with all ProbOS metadata."""
        entry = parse_skill_file(skills_dir / "architecture-review" / "SKILL.md")
        assert entry is not None
        assert entry.name == "architecture-review"
        assert "Analyze proposed system designs" in entry.description
        assert entry.license == "Apache-2.0"
        assert entry.compatibility == "Requires CodebaseIndex access"
        assert entry.department == "science"
        assert entry.skill_id == "architecture_review"
        assert entry.min_proficiency == 3
        assert entry.min_rank == "lieutenant"
        assert entry.intents == ["design_feature", "review_architecture"]
        assert entry.origin == "internal"
        assert entry.loaded_at > 0

    def test_parse_minimal_skill_md(self, skills_dir: Path) -> None:
        """Only required fields (name, description), no metadata."""
        entry = parse_skill_file(skills_dir / "basic-skill" / "SKILL.md")
        assert entry is not None
        assert entry.name == "basic-skill"
        assert entry.description == "A simple skill with only required fields."
        assert entry.department == "*"
        assert entry.skill_id == ""
        assert entry.min_proficiency == 1
        assert entry.min_rank == "ensign"
        assert entry.intents == []
        assert entry.license == ""

    def test_parse_external_skill_no_probos_metadata(self, skills_dir: Path) -> None:
        """Standard AgentSkills.io with no metadata block."""
        entry = parse_skill_file(skills_dir / "external-tool" / "SKILL.md")
        assert entry is not None
        assert entry.name == "external-tool"
        assert entry.department == "*"
        assert entry.skill_id == ""
        assert entry.intents == []
        assert entry.license == "MIT"
        assert entry.compatibility == "Requires network access"

    def test_parse_missing_name_skips(self, tmp_path: Path) -> None:
        """Missing name → skip with warning."""
        path = tmp_path / "SKILL.md"
        path.write_text("---\ndescription: No name\n---\n\nBody", encoding="utf-8")
        assert parse_skill_file(path) is None

    def test_parse_missing_description_skips(self, tmp_path: Path) -> None:
        """Missing description → skip with warning."""
        path = tmp_path / "SKILL.md"
        path.write_text("---\nname: no-desc\n---\n\nBody", encoding="utf-8")
        assert parse_skill_file(path) is None

    def test_parse_invalid_yaml_skips(self, tmp_path: Path) -> None:
        """Malformed YAML → skip with warning."""
        path = tmp_path / "SKILL.md"
        path.write_text("---\n: invalid: [yaml: broken\n---\n\nBody", encoding="utf-8")
        assert parse_skill_file(path) is None

    def test_parse_no_frontmatter_skips(self, tmp_path: Path) -> None:
        """No --- delimiters → skip with warning."""
        path = tmp_path / "SKILL.md"
        path.write_text("# Just Markdown\n\nNo frontmatter here.", encoding="utf-8")
        assert parse_skill_file(path) is None

    def test_parse_preserves_body_content(self, skills_dir: Path) -> None:
        """Content below frontmatter preserved for get_instructions()."""
        body = get_skill_body(skills_dir / "architecture-review" / "SKILL.md")
        assert body is not None
        assert "# Architecture Review" in body
        assert "Check against SOLID principles" in body
        # Frontmatter should NOT be in body
        assert "probos-department" not in body


# ===========================================================================
# CognitiveSkillCatalog Tests
# ===========================================================================


class TestCognitiveSkillCatalog:
    """Tests for catalog lifecycle and query methods."""

    @pytest.mark.asyncio
    async def test_start_creates_table(self, db_path: str) -> None:
        """SQLite schema created on start."""
        catalog = CognitiveSkillCatalog(db_path=db_path)
        await catalog.start()
        try:
            assert catalog._db is not None
            cursor = await catalog._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='cognitive_skill_catalog'"
            )
            row = await cursor.fetchone()
            assert row is not None
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_scan_discovers_skills(self, skills_dir: Path, db_path: str) -> None:
        """Scan finds SKILL.md files in subdirectories."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            # Should find 3 skills (full, minimal, external)
            assert len(catalog._cache) == 3
            assert catalog.get_entry("architecture-review") is not None
            assert catalog.get_entry("basic-skill") is not None
            assert catalog.get_entry("external-tool") is not None
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_scan_ignores_non_skill_dirs(self, skills_dir: Path, db_path: str) -> None:
        """Directories without SKILL.md are skipped."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            assert catalog.get_entry("not-a-skill") is None
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_scan_idempotent(self, skills_dir: Path, db_path: str) -> None:
        """Re-scanning updates, doesn't duplicate."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            count1 = len(catalog._cache)
            count2 = await catalog.scan_and_register()
            assert count1 == count2
            assert len(catalog._cache) == count1
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_register_and_get_entry(self, db_path: str) -> None:
        """Round-trip register → get."""
        catalog = CognitiveSkillCatalog(db_path=db_path)
        await catalog.start()
        try:
            entry = CognitiveSkillEntry(
                name="test-skill",
                description="A test skill",
                skill_dir=Path("/fake"),
                loaded_at=time.time(),
            )
            await catalog.register(entry)
            got = catalog.get_entry("test-skill")
            assert got is not None
            assert got.name == "test-skill"
            assert got.description == "A test skill"
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_list_entries_no_filter(self, skills_dir: Path, db_path: str) -> None:
        """Returns all entries."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            entries = catalog.list_entries()
            assert len(entries) == 3
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_list_entries_department_filter(self, skills_dir: Path, db_path: str) -> None:
        """Only matching department + wildcard skills."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            # "science" department should get architecture-review (science) + basic-skill (*) + external-tool (*)
            entries = catalog.list_entries(department="science")
            names = {e.name for e in entries}
            assert "architecture-review" in names
            assert "basic-skill" in names
            assert "external-tool" in names

            # "engineering" should get only wildcard skills (not science-scoped)
            entries_eng = catalog.list_entries(department="engineering")
            names_eng = {e.name for e in entries_eng}
            assert "architecture-review" not in names_eng
            assert "basic-skill" in names_eng
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_list_entries_rank_filter(self, skills_dir: Path, db_path: str) -> None:
        """Only skills at or below the given rank."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            # Ensign should only see skills with min_rank=ensign
            entries_ensign = catalog.list_entries(min_rank="ensign")
            names_e = {e.name for e in entries_ensign}
            assert "basic-skill" in names_e
            assert "external-tool" in names_e
            # architecture-review requires lieutenant — should NOT be visible to ensign
            assert "architecture-review" not in names_e

            # Lieutenant should see all
            entries_lt = catalog.list_entries(min_rank="lieutenant")
            names_lt = {e.name for e in entries_lt}
            assert "architecture-review" in names_lt
            assert "basic-skill" in names_lt
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_get_descriptions_progressive_disclosure(self, skills_dir: Path, db_path: str) -> None:
        """Returns (name, description, skill_id) tuples only."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            descs = catalog.get_descriptions()
            assert all(isinstance(d, tuple) and len(d) == 3 for d in descs)
            names = [d[0] for d in descs]
            assert "basic-skill" in names
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_get_instructions_loads_body(self, skills_dir: Path, db_path: str) -> None:
        """Full markdown body returned (no frontmatter)."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            body = catalog.get_instructions("architecture-review")
            assert body is not None
            assert "# Architecture Review" in body
            assert "probos-department" not in body
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_get_instructions_missing_skill(self, db_path: str) -> None:
        """Returns None for nonexistent skill."""
        catalog = CognitiveSkillCatalog(db_path=db_path)
        await catalog.start()
        try:
            assert catalog.get_instructions("nonexistent") is None
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_get_intents(self, skills_dir: Path, db_path: str) -> None:
        """Returns parsed intent list."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            intents = catalog.get_intents("architecture-review")
            assert intents == ["design_feature", "review_architecture"]
            assert catalog.get_intents("basic-skill") == []
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_find_by_intent(self, skills_dir: Path, db_path: str) -> None:
        """Reverse lookup by intent name."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            matches = catalog.find_by_intent("design_feature")
            assert len(matches) == 1
            assert matches[0].name == "architecture-review"
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_find_by_intent_no_match(self, skills_dir: Path, db_path: str) -> None:
        """Returns empty list for unknown intent."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            assert catalog.find_by_intent("nonexistent_intent") == []
        finally:
            await catalog.stop()


# ===========================================================================
# REST API Tests
# ===========================================================================


class TestCatalogAPI:
    """Tests for the /api/skills/catalog endpoints."""

    @pytest.mark.asyncio
    async def test_api_catalog_list(self, skills_dir: Path, db_path: str) -> None:
        """GET /api/skills/catalog returns entries."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            runtime = MagicMock()
            runtime.cognitive_skill_catalog = catalog

            from probos.routers.skills import catalog_list

            result = await catalog_list(department=None, rank=None, runtime=runtime)
            assert "skills" in result
            assert len(result["skills"]) == 3
            names = {s["name"] for s in result["skills"]}
            assert "architecture-review" in names
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_api_catalog_get(self, skills_dir: Path, db_path: str) -> None:
        """GET /api/skills/catalog/{name} returns full entry + instructions."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            runtime = MagicMock()
            runtime.cognitive_skill_catalog = catalog

            from probos.routers.skills import catalog_get

            result = await catalog_get("architecture-review", runtime=runtime)
            assert result["name"] == "architecture-review"
            assert result["instructions"] is not None
            assert "# Architecture Review" in result["instructions"]
        finally:
            await catalog.stop()

    @pytest.mark.asyncio
    async def test_api_catalog_rescan(self, skills_dir: Path, db_path: str) -> None:
        """POST /api/skills/catalog/rescan triggers scan."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        try:
            runtime = MagicMock()
            runtime.cognitive_skill_catalog = catalog

            from probos.routers.skills import catalog_rescan

            result = await catalog_rescan(runtime=runtime)
            assert result["rescanned"] is True
            assert result["count"] == 3
        finally:
            await catalog.stop()


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestIntegration:
    """Tests for startup wiring and shutdown cleanup."""

    def test_startup_wiring_result_field(self) -> None:
        """CommunicationResult has cognitive_skill_catalog field."""
        from probos.startup.results import CommunicationResult
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(CommunicationResult)}
        assert "cognitive_skill_catalog" in field_names

    @pytest.mark.asyncio
    async def test_shutdown_cleanup(self, skills_dir: Path, db_path: str) -> None:
        """Catalog stopped during shutdown — stop() closes DB."""
        catalog = CognitiveSkillCatalog(skills_dir=skills_dir, db_path=db_path)
        await catalog.start()
        assert catalog._db is not None
        await catalog.stop()
        assert catalog._db is None
