"""AD-887: Skill Library unification (#851, Wave 244).

`SkillBridge.get_unified_profile` is the single query surface that reports both
skill kinds for an agent:

- developmental (T3) skills from ``AgentSkillService.get_profile`` (proficiency-
  tracked ``AgentSkillRecord``s), and
- cognitive (T2) skills from the ``CognitiveSkillCatalog`` (instruction-defined
  ``SKILL.md`` entries), tagged ``kind="cognitive"`` and appended to the new
  ``SkillProfile.cognitive_skills`` field.

The merge happens in the bridge — ``AgentSkillService`` stays T3-pure and the
catalog stays its own store. Tests use real components throughout (real
``AgentSkillService`` on a tmp DB, real ``SkillBridge``, real
``CognitiveSkillCatalog``) per the BF-287 substrate-boundary discipline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from probos.cognitive.skill_bridge import SkillBridge
from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from probos.skill_framework import (
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillDefinition,
    SkillProfile,
    SkillRegistry,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _write_skill(
    skills_root: Path,
    *,
    slug: str,
    name: str,
    description: str = "Do the thing carefully.",
    department: str | None = None,
    min_rank: str | None = None,
    skill_id: str | None = None,
) -> None:
    """Write one SKILL.md under ``skills_root/<slug>/`` with optional governance."""
    skill_dir = skills_root / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    meta_lines: list[str] = []
    if department is not None:
        meta_lines.append(f"  probos-department: {department}")
    if min_rank is not None:
        meta_lines.append(f"  probos-min-rank: {min_rank}")
    if skill_id is not None:
        meta_lines.append(f"  probos-skill-id: {skill_id}")
    meta_block = ("metadata:\n" + "\n".join(meta_lines) + "\n") if meta_lines else ""
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{meta_block}"
        "---\n\n"
        "## Instructions\nFollow the procedure.\n",
        encoding="utf-8",
    )


async def _make_catalog(skills_root: Path) -> CognitiveSkillCatalog:
    """Build and start a real catalog rooted at ``skills_root`` (may be empty)."""
    skills_root.mkdir(parents=True, exist_ok=True)
    catalog = CognitiveSkillCatalog(skills_dir=skills_root, db_path=None)
    await catalog.start()
    return catalog


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def skill_stack(tmp_path):
    """Real SkillRegistry + AgentSkillService on a tmp DB."""
    db_path = str(tmp_path / "skills.db")
    registry = SkillRegistry(db_path=db_path)
    await registry.start()
    service = AgentSkillService(db_path=db_path, registry=registry)
    await service.start()
    try:
        yield registry, service
    finally:
        await service.stop()
        await registry.stop()


async def _give_developmental_skill(
    registry: SkillRegistry,
    service: AgentSkillService,
    agent_id: str,
    skill_id: str = "tactical-debug",
) -> None:
    """Register an ACQUIRED skill definition and grant it to the agent."""
    await registry.register_skill(
        SkillDefinition(
            skill_id=skill_id,
            name="Tactical Debug",
            category=SkillCategory.ACQUIRED,
            description="Developmental debugging competency.",
        )
    )
    await service.acquire_skill(
        agent_id, skill_id, source="test", proficiency=ProficiencyLevel.APPLY
    )


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unified_profile_reports_both_kinds(skill_stack, tmp_path):
    """An agent with a developmental skill AND a cognitive entry reports both."""
    registry, service = skill_stack
    await _give_developmental_skill(registry, service, "agent-both")

    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root, slug="cog-skill", name="cog-skill",
        skill_id="cog-skill-id",
    )
    catalog = await _make_catalog(skills_root)
    bridge = SkillBridge(
        catalog=catalog, skill_registry=registry, skill_service=service
    )

    profile = await bridge.get_unified_profile("agent-both")

    assert isinstance(profile, SkillProfile)
    dev_ids = {r.skill_id for r in profile.all_skills}
    assert "tactical-debug" in dev_ids
    cog_names = {c["name"] for c in profile.cognitive_skills}
    assert "cog-skill" in cog_names


@pytest.mark.asyncio
async def test_cognitive_entries_tagged_kind(skill_stack, tmp_path):
    """Every merged cognitive entry carries kind='cognitive' and core keys."""
    registry, service = skill_stack
    skills_root = tmp_path / "skills"
    _write_skill(
        skills_root, slug="cog-skill", name="cog-skill",
        skill_id="cog-skill-id",
    )
    catalog = await _make_catalog(skills_root)
    bridge = SkillBridge(
        catalog=catalog, skill_registry=registry, skill_service=service
    )

    profile = await bridge.get_unified_profile("agent-cog")

    assert profile.cognitive_skills, "expected at least one cognitive entry"
    for entry in profile.cognitive_skills:
        assert entry["kind"] == "cognitive"
        assert {"name", "description", "skill_id"} <= set(entry)


@pytest.mark.asyncio
async def test_cognitive_only_agent_resolves(skill_stack, tmp_path):
    """Agent with no developmental skills still resolves cognitive entries."""
    registry, service = skill_stack
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, slug="cog-only", name="cog-only")
    catalog = await _make_catalog(skills_root)
    bridge = SkillBridge(
        catalog=catalog, skill_registry=registry, skill_service=service
    )

    profile = await bridge.get_unified_profile("agent-cog-only")

    assert profile.all_skills == []
    assert {c["name"] for c in profile.cognitive_skills} == {"cog-only"}


@pytest.mark.asyncio
async def test_developmental_only_agent_resolves(skill_stack, tmp_path):
    """Agent with a developmental skill and an empty catalog resolves cleanly."""
    registry, service = skill_stack
    await _give_developmental_skill(registry, service, "agent-dev-only")

    # Empty skills dir → catalog with zero entries.
    catalog = await _make_catalog(tmp_path / "empty_skills")
    bridge = SkillBridge(
        catalog=catalog, skill_registry=registry, skill_service=service
    )

    profile = await bridge.get_unified_profile("agent-dev-only")

    assert {r.skill_id for r in profile.all_skills} == {"tactical-debug"}
    assert profile.cognitive_skills == []


@pytest.mark.asyncio
async def test_department_filter_excludes_other_departments(skill_stack, tmp_path):
    """Passing a department filters out department-specific entries."""
    registry, service = skill_stack
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, slug="wild", name="wild")  # department='*'
    _write_skill(
        skills_root, slug="science-only", name="science-only",
        department="science",
    )
    catalog = await _make_catalog(skills_root)
    bridge = SkillBridge(
        catalog=catalog, skill_registry=registry, skill_service=service
    )

    profile = await bridge.get_unified_profile(
        "agent-eng", department="engineering"
    )

    names = {c["name"] for c in profile.cognitive_skills}
    assert "wild" in names  # wildcard always visible
    assert "science-only" not in names  # filtered out


@pytest.mark.asyncio
async def test_get_profile_stays_t3_only(skill_stack, tmp_path):
    """AgentSkillService.get_profile does not populate cognitive_skills."""
    registry, service = skill_stack
    await _give_developmental_skill(registry, service, "agent-t3")

    # Even with a catalog full of cognitive entries, the service is unaware.
    skills_root = tmp_path / "skills"
    _write_skill(skills_root, slug="cog-skill", name="cog-skill")
    await _make_catalog(skills_root)

    profile = await service.get_profile("agent-t3")

    assert isinstance(profile, SkillProfile)
    assert profile.cognitive_skills == []
    assert {r.skill_id for r in profile.all_skills} == {"tactical-debug"}


@pytest.mark.asyncio
async def test_catalog_failure_degrades_to_developmental_only(
    skill_stack, tmp_path, monkeypatch
):
    """A catalog query failure log-and-degrades to a developmental-only profile."""
    registry, service = skill_stack
    await _give_developmental_skill(registry, service, "agent-degrade")

    catalog = await _make_catalog(tmp_path / "skills")

    def _boom(*args, **kwargs):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(catalog, "list_entries", _boom)
    bridge = SkillBridge(
        catalog=catalog, skill_registry=registry, skill_service=service
    )

    profile = await bridge.get_unified_profile("agent-degrade")

    assert {r.skill_id for r in profile.all_skills} == {"tactical-debug"}
    assert profile.cognitive_skills == []
