"""AD-596d: External Skill Import tests.

Tests for import_skill(), discover_package_skills(), enrich_skill(),
remove_skill(), REST endpoints, and /skill shell command.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    CognitiveSkillEntry,
    parse_skill_file,
)


# ── Helpers ──────────────────────────────────────────────────────────


VALID_SKILL_MD = textwrap.dedent("""\
    ---
    name: test_external
    description: A test external skill
    license: MIT
    ---

    ## Instructions
    Do the external thing.
""")

VALID_SKILL_WITH_META = textwrap.dedent("""\
    ---
    name: governed_skill
    description: A governed external skill
    license: Apache-2.0
    metadata:
      probos-department: science
      probos-skill-id: cognitive_analysis
      probos-min-proficiency: 3
      probos-min-rank: lieutenant
      probos-intents: analyze research
    ---

    ## Instructions
    Analyze things carefully.
""")

NO_NAME_SKILL_MD = textwrap.dedent("""\
    ---
    description: Missing name
    ---
    Body.
""")


def _write_skill(tmp_path: Path, name: str, content: str) -> Path:
    """Create a skill directory with SKILL.md and return the directory."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


async def _make_catalog(tmp_path: Path) -> CognitiveSkillCatalog:
    """Create a catalog with a skills_dir under tmp_path (no DB)."""
    skills_dir = tmp_path / "config" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    catalog = CognitiveSkillCatalog(skills_dir=skills_dir)
    return catalog


# ── import_skill() ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_valid_external_skill(tmp_path):
    """Import valid external skill → copies to config/skills, origin='external'."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "test_external", VALID_SKILL_MD)

    entry = await catalog.import_skill(source)

    assert entry.name == "test_external"
    assert entry.origin == "external"
    assert entry.description == "A test external skill"
    # Copied into skills_dir
    dest = tmp_path / "config" / "skills" / "test_external" / "SKILL.md"
    assert dest.exists()
    # Entry is in cache
    assert catalog.get_entry("test_external") is not None


@pytest.mark.asyncio
async def test_import_skill_no_metadata_ungoverned(tmp_path):
    """Import skill with no metadata block → ungoverned defaults."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "test_external", VALID_SKILL_MD)

    entry = await catalog.import_skill(source)

    assert entry.department == "*"
    assert entry.min_rank == "ensign"
    assert entry.min_proficiency == 1
    assert entry.intents == []


@pytest.mark.asyncio
async def test_import_skill_with_probos_metadata(tmp_path):
    """Import skill with full ProbOS metadata → governs normally."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "governed_skill", VALID_SKILL_WITH_META)

    entry = await catalog.import_skill(source)

    assert entry.department == "science"
    assert entry.skill_id == "cognitive_analysis"
    assert entry.min_proficiency == 3
    assert entry.min_rank == "lieutenant"
    assert entry.intents == ["analyze", "research"]
    assert entry.origin == "external"


@pytest.mark.asyncio
async def test_import_duplicate_rejected(tmp_path):
    """Import skill with existing name → rejected with error."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "test_external", VALID_SKILL_MD)

    await catalog.import_skill(source)

    source2 = _write_skill(tmp_path / "sources2", "test_external", VALID_SKILL_MD)
    with pytest.raises(ValueError, match="already exists"):
        await catalog.import_skill(source2)


@pytest.mark.asyncio
async def test_import_invalid_path(tmp_path):
    """Import from invalid path → fails fast."""
    catalog = await _make_catalog(tmp_path)
    with pytest.raises(ValueError, match="No SKILL.md"):
        await catalog.import_skill(tmp_path / "nonexistent")


@pytest.mark.asyncio
async def test_import_invalid_skill_md(tmp_path):
    """Import skill with invalid SKILL.md (no name) → rejected."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "bad", NO_NAME_SKILL_MD)

    with pytest.raises(ValueError, match="Invalid SKILL.md"):
        await catalog.import_skill(source)


@pytest.mark.asyncio
async def test_imported_skill_in_list_and_find(tmp_path):
    """Imported skill appears in list_entries() and find_by_intent()."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "governed_skill", VALID_SKILL_WITH_META)

    await catalog.import_skill(source)

    entries = catalog.list_entries()
    assert any(e.name == "governed_skill" for e in entries)

    by_intent = catalog.find_by_intent("analyze")
    assert len(by_intent) == 1
    assert by_intent[0].name == "governed_skill"


# ── discover_package_skills() ────────────────────────────────────────


def test_discover_no_installed_skills(tmp_path):
    """Discover with no installed skills → empty list."""
    catalog = CognitiveSkillCatalog(skills_dir=tmp_path)
    with patch("site.getsitepackages", return_value=[str(tmp_path / "empty_sp")]):
        with patch("site.getusersitepackages", return_value=str(tmp_path / "empty_usp")):
            results = catalog.discover_package_skills()
    assert results == []


def test_discover_finds_skill(tmp_path):
    """Discover finds skill in mock site-packages .agents/skills/ path."""
    sp = tmp_path / "sp"
    skill_dir = sp / "mypkg" / ".agents" / "skills" / "fastapi"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")

    catalog = CognitiveSkillCatalog(skills_dir=tmp_path / "skills")
    with patch("site.getsitepackages", return_value=[str(sp)]):
        with patch("site.getusersitepackages", return_value=str(tmp_path / "empty")):
            results = catalog.discover_package_skills()

    assert len(results) == 1
    assert results[0]["skill_name"] == "test_external"
    assert results[0]["has_probos_metadata"] is False


def test_discover_reports_probos_metadata(tmp_path):
    """Discover reports has_probos_metadata correctly."""
    sp = tmp_path / "sp"
    skill_dir = sp / "mypkg" / ".agents" / "skills" / "governed"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_WITH_META, encoding="utf-8")

    catalog = CognitiveSkillCatalog(skills_dir=tmp_path / "skills")
    with patch("site.getsitepackages", return_value=[str(sp)]):
        with patch("site.getusersitepackages", return_value=str(tmp_path / "empty")):
            results = catalog.discover_package_skills()

    assert len(results) == 1
    assert results[0]["has_probos_metadata"] is True


def test_discover_skips_invalid_skill_md(tmp_path):
    """Discover skips invalid SKILL.md files gracefully."""
    sp = tmp_path / "sp"
    skill_dir = sp / "mypkg" / ".agents" / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(NO_NAME_SKILL_MD, encoding="utf-8")

    catalog = CognitiveSkillCatalog(skills_dir=tmp_path / "skills")
    with patch("site.getsitepackages", return_value=[str(sp)]):
        with patch("site.getusersitepackages", return_value=str(tmp_path / "empty")):
            results = catalog.discover_package_skills()

    assert results == []


# ── enrich_skill() ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_adds_metadata(tmp_path):
    """Enrich adds metadata to external skill → frontmatter rewritten."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "test_external", VALID_SKILL_MD)
    await catalog.import_skill(source)

    entry = await catalog.enrich_skill("test_external", {
        "department": "science",
        "skill_id": "ext_analysis",
        "intents": ["analyze", "report"],
    })

    assert entry.department == "science"
    assert entry.skill_id == "ext_analysis"
    assert entry.intents == ["analyze", "report"]

    # Check frontmatter was rewritten
    dest_md = tmp_path / "config" / "skills" / "test_external" / "SKILL.md"
    content = dest_md.read_text(encoding="utf-8")
    assert "probos-department: science" in content


@pytest.mark.asyncio
async def test_enrich_preserves_body(tmp_path):
    """Enrich preserves markdown body exactly."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "test_external", VALID_SKILL_MD)
    await catalog.import_skill(source)

    await catalog.enrich_skill("test_external", {"department": "engineering"})

    dest_md = tmp_path / "config" / "skills" / "test_external" / "SKILL.md"
    content = dest_md.read_text(encoding="utf-8")
    assert "Do the external thing." in content


@pytest.mark.asyncio
async def test_enrich_preserves_non_probos_fields(tmp_path):
    """Enrich preserves existing non-ProbOS fields (license, etc.)."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "test_external", VALID_SKILL_MD)
    await catalog.import_skill(source)

    await catalog.enrich_skill("test_external", {"department": "ops"})

    dest_md = tmp_path / "config" / "skills" / "test_external" / "SKILL.md"
    content = dest_md.read_text(encoding="utf-8")
    assert "MIT" in content


@pytest.mark.asyncio
async def test_enrich_nonexistent_skill(tmp_path):
    """Enrich on nonexistent skill → error."""
    catalog = await _make_catalog(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        await catalog.enrich_skill("ghost", {"department": "science"})


@pytest.mark.asyncio
async def test_enrich_partial_fields(tmp_path):
    """Enrich partial fields (only department) → other fields unchanged."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "governed_skill", VALID_SKILL_WITH_META)
    await catalog.import_skill(source)

    entry = await catalog.enrich_skill("governed_skill", {"department": "engineering"})

    assert entry.department == "engineering"
    # Other fields unchanged
    assert entry.skill_id == "cognitive_analysis"
    assert entry.min_proficiency == 3
    assert entry.intents == ["analyze", "research"]


# ── remove_skill() ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_external_skill(tmp_path):
    """Remove external skill → deleted from catalog + filesystem."""
    catalog = await _make_catalog(tmp_path)
    source = _write_skill(tmp_path / "sources", "test_external", VALID_SKILL_MD)
    await catalog.import_skill(source)

    dest = tmp_path / "config" / "skills" / "test_external"
    assert dest.exists()

    await catalog.remove_skill("test_external")

    assert catalog.get_entry("test_external") is None
    assert not dest.exists()


@pytest.mark.asyncio
async def test_remove_internal_skill_rejected(tmp_path):
    """Remove internal skill → rejected."""
    catalog = await _make_catalog(tmp_path)
    # Manually add an internal entry
    entry = CognitiveSkillEntry(
        name="internal_skill",
        description="An internal skill",
        skill_dir=tmp_path / "config" / "skills" / "internal_skill",
        origin="internal",
    )
    await catalog.register(entry)

    with pytest.raises(ValueError, match="Cannot remove internal"):
        await catalog.remove_skill("internal_skill")


@pytest.mark.asyncio
async def test_remove_nonexistent_skill(tmp_path):
    """Remove nonexistent skill → error."""
    catalog = await _make_catalog(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        await catalog.remove_skill("ghost")


# ── /skill shell command ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_list_command(tmp_path):
    """'/skill list' shows registered skills."""
    from probos.experience.commands.commands_skill import cmd_skill

    runtime = MagicMock()
    entry = CognitiveSkillEntry(
        name="test_skill",
        description="Test",
        skill_dir=tmp_path,
        origin="external",
    )
    runtime.cognitive_skill_catalog.list_entries.return_value = [entry]

    console = MagicMock()
    await cmd_skill(runtime, console, "list")

    # Table was printed
    console.print.assert_called()


@pytest.mark.asyncio
async def test_skill_import_command(tmp_path):
    """'/skill import <path>' triggers import_skill."""
    from probos.experience.commands.commands_skill import cmd_skill

    runtime = MagicMock()
    mock_entry = CognitiveSkillEntry(
        name="imported", description="yes", skill_dir=tmp_path, origin="external",
    )
    runtime.cognitive_skill_catalog.import_skill = AsyncMock(return_value=mock_entry)

    console = MagicMock()
    await cmd_skill(runtime, console, f"import {tmp_path}")

    runtime.cognitive_skill_catalog.import_skill.assert_called_once()


@pytest.mark.asyncio
async def test_skill_info_command(tmp_path):
    """'/skill info <name>' shows full details."""
    from probos.experience.commands.commands_skill import cmd_skill

    runtime = MagicMock()
    entry = CognitiveSkillEntry(
        name="test_skill",
        description="Test skill",
        skill_dir=tmp_path,
        department="science",
        origin="external",
    )
    runtime.cognitive_skill_catalog.get_entry.return_value = entry

    console = MagicMock()
    await cmd_skill(runtime, console, "info test_skill")

    console.print.assert_called()


@pytest.mark.asyncio
async def test_skill_remove_command(tmp_path):
    """'/skill remove <name>' triggers removal."""
    from probos.experience.commands.commands_skill import cmd_skill

    runtime = MagicMock()
    runtime.cognitive_skill_catalog.remove_skill = AsyncMock()

    console = MagicMock()
    await cmd_skill(runtime, console, "remove some_skill")

    runtime.cognitive_skill_catalog.remove_skill.assert_called_once_with("some_skill")
