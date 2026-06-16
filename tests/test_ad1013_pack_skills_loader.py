"""AD-1013: skills-only Capability-Pack loader (#948).

BF-287: a REAL :class:`CognitiveSkillCatalog` (cache-only, ``db_path=None``) and
REAL tmp_path pack dirs — no MagicMock at the substrate boundary. The loader
loads markdown skill *instructions* only; it executes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from probos.packs import PackLoadResult, load_pack_skills


def _pack(tmp_path: Path, name: str, manifest: dict) -> Path:
    pack = tmp_path / name
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pack


def _folder_skill(pack: Path, rel: str, skill_name: str, description: str = "A test skill.") -> None:
    d = pack / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {skill_name}\ndescription: {description}\n---\n\n# {skill_name}\n\nInstructions.\n",
        encoding="utf-8",
    )


@pytest.fixture
async def catalog(tmp_path: Path) -> CognitiveSkillCatalog:
    cat = CognitiveSkillCatalog(skills_dir=tmp_path / "config_skills", db_path=None)
    await cat.start()
    return cat


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


async def test_loads_declared_folder_skills(tmp_path: Path, catalog: CognitiveSkillCatalog):
    pack = _pack(tmp_path / "packs", "dev", {"name": "dev-pack", "skills": "skills/"})
    _folder_skill(pack, "skills/lint", "lint-code")
    _folder_skill(pack, "skills/format", "format-code")

    result = await load_pack_skills(pack, catalog)

    assert isinstance(result, PackLoadResult)
    assert result.pack_name == "dev-pack"
    assert set(result.loaded) == {"lint-code", "format-code"}
    assert result.skipped == []
    # The skills are now registered + queryable in the catalog.
    assert catalog.get_entry("lint-code") is not None
    assert catalog.get_entry("format-code") is not None


async def test_origin_tag_records_pack_provenance(tmp_path: Path, catalog: CognitiveSkillCatalog):
    pack = _pack(tmp_path / "packs", "dev", {"name": "dev-pack", "skills": "skills/"})
    _folder_skill(pack, "skills/lint", "lint-code")

    await load_pack_skills(pack, catalog)

    entry = catalog.get_entry("lint-code")
    assert entry is not None
    assert entry.origin == "pack:dev-pack"


async def test_custom_origin_prefix(tmp_path: Path, catalog: CognitiveSkillCatalog):
    pack = _pack(tmp_path / "packs", "dev", {"name": "dev-pack", "skills": "skills/"})
    _folder_skill(pack, "skills/lint", "lint-code")

    await load_pack_skills(pack, catalog, origin_prefix="vetted-pack")

    entry = catalog.get_entry("lint-code")
    assert entry is not None
    assert entry.origin == "vetted-pack:dev-pack"


# ---------------------------------------------------------------------------
# honest-degrade
# ---------------------------------------------------------------------------


async def test_no_manifest_returns_none(tmp_path: Path, catalog: CognitiveSkillCatalog):
    empty = tmp_path / "not-a-pack"
    empty.mkdir()
    assert await load_pack_skills(empty, catalog) is None


async def test_standalone_md_skill_is_skipped(tmp_path: Path, catalog: CognitiveSkillCatalog):
    # A skills dir with a loose .md (no SKILL.md folder) — preview classifies it
    # as a skill, but the importer needs a folder-skill, so it is skipped.
    pack = _pack(tmp_path / "packs", "loose", {"name": "loose-pack", "skills": "skills/"})
    (pack / "skills").mkdir(parents=True, exist_ok=True)
    (pack / "skills" / "tip.md").write_text("# just a tip", encoding="utf-8")

    result = await load_pack_skills(pack, catalog)

    assert result is not None
    assert result.loaded == []
    assert result.skipped_count == 1
    assert result.skipped[0][0] == "tip"
    assert "SKILL.md" in result.skipped[0][1]


async def test_duplicate_skill_is_skipped_not_raised(tmp_path: Path, catalog: CognitiveSkillCatalog):
    pack = _pack(tmp_path / "packs", "dev", {"name": "dev-pack", "skills": "skills/"})
    _folder_skill(pack, "skills/lint", "lint-code")

    first = await load_pack_skills(pack, catalog)
    assert first is not None
    assert first.loaded == ["lint-code"]

    # Loading the same pack again: the skill name already exists -> skipped,
    # never raised (idempotent honest-degrade).
    second = await load_pack_skills(pack, catalog)
    assert second is not None
    assert second.loaded == []
    assert second.skipped_count == 1
    assert second.skipped[0][0] == "lint"


async def test_agents_are_not_loaded_by_skills_tier(tmp_path: Path, catalog: CognitiveSkillCatalog):
    # Agent .py/.md/.json are out of scope for the skills-only tier — they are
    # never loaded here (that is the AD-1014 self-mod-chain slice). The skill
    # loads; the agent file is simply not touched.
    pack = _pack(
        tmp_path / "packs", "mixed",
        {"name": "mixed-pack", "skills": "skills/", "agents": "agents/"},
    )
    _folder_skill(pack, "skills/lint", "lint-code")
    (pack / "agents").mkdir(parents=True, exist_ok=True)
    (pack / "agents" / "rogue.py").write_text("raise RuntimeError('should never run')", encoding="utf-8")

    result = await load_pack_skills(pack, catalog)

    assert result is not None
    assert result.loaded == ["lint-code"]
    # No agent was registered as a skill.
    assert catalog.get_entry("rogue") is None


async def test_partial_load_mixes_loaded_and_skipped(tmp_path: Path, catalog: CognitiveSkillCatalog):
    pack = _pack(tmp_path / "packs", "dev", {"name": "dev-pack", "skills": "skills/"})
    _folder_skill(pack, "skills/good", "good-skill")
    (pack / "skills" / "loose.md").write_text("# loose", encoding="utf-8")

    result = await load_pack_skills(pack, catalog)

    assert result is not None
    assert result.loaded == ["good-skill"]
    assert result.skipped_count == 1
    assert result.loaded_count == 1
