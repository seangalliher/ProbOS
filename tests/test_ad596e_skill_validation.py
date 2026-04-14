"""AD-596e: Skill Validation + Instruction Linting tests.

Tests for _validate_spec(), validate_skill(), validate_all(),
enrichment validation, shell command, and API endpoints.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.skill_catalog import (
    CognitiveSkillCatalog,
    CognitiveSkillEntry,
    SkillValidationResult,
    _validate_spec,
)


# ── Helpers ──────────────────────────────────────────────────────────


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


def _make_entry(
    name: str = "my-skill",
    description: str = "A test skill",
    skill_dir: Path | None = None,
    department: str = "*",
    min_rank: str = "ensign",
    min_proficiency: int = 1,
    skill_id: str = "",
    compatibility: str = "",
) -> CognitiveSkillEntry:
    """Create a CognitiveSkillEntry for testing."""
    return CognitiveSkillEntry(
        name=name,
        description=description,
        skill_dir=skill_dir or Path(f"/skills/{name}"),
        department=department,
        min_rank=min_rank,
        min_proficiency=min_proficiency,
        skill_id=skill_id,
        compatibility=compatibility,
    )


VALID_SKILL_MD = textwrap.dedent("""\
    ---
    name: my-skill
    description: A valid test skill
    ---

    ## Instructions
    Do the thing correctly.
""")

SKILL_WITH_CALLSIGN = textwrap.dedent("""\
    ---
    name: callsign-test
    description: A skill mentioning callsigns
    ---

    ## Instructions
    Coordinate with LaForge to fix the issue.
    Report findings to Echo after analysis.
""")

SKILL_WITH_MULTIPLE_CALLSIGNS = textwrap.dedent("""\
    ---
    name: multi-callsign
    description: Multiple callsign mentions
    ---

    ## Instructions
    Tell Meridian about the plan.
    Ask Echo for advice.
    Have LaForge check the wiring.
""")


# ── Layer 1: AgentSkills.io spec validation ──────────────────────────


def test_validate_spec_valid_name():
    """Valid skill (lowercase name, within limits) → no errors."""
    entry = _make_entry(name="my-skill-2")
    errors = _validate_spec(entry)
    assert errors == []


def test_validate_spec_name_uppercase():
    """Name with uppercase letters → error."""
    entry = _make_entry(name="MySkill")
    errors = _validate_spec(entry)
    assert len(errors) >= 1
    assert "lowercase" in errors[0].lower() or "alphanumeric" in errors[0].lower()


def test_validate_spec_name_too_long():
    """Name exceeding 64 chars → error."""
    entry = _make_entry(name="a" * 65)
    errors = _validate_spec(entry)
    assert any("64 characters" in e for e in errors)


def test_validate_spec_consecutive_hyphens():
    """Name with consecutive hyphens (my--skill) → error."""
    entry = _make_entry(name="my--skill")
    errors = _validate_spec(entry)
    assert len(errors) >= 1


def test_validate_spec_leading_hyphen():
    """Name with leading hyphen → error."""
    entry = _make_entry(name="-my-skill")
    errors = _validate_spec(entry)
    assert len(errors) >= 1


def test_validate_spec_name_dir_mismatch():
    """Name not matching directory name → error."""
    entry = _make_entry(name="my-skill", skill_dir=Path("/skills/other-dir"))
    errors = _validate_spec(entry)
    assert any("does not match directory" in e for e in errors)


def test_validate_spec_description_too_long():
    """Description exceeding 1024 chars → error."""
    entry = _make_entry(description="x" * 1025)
    errors = _validate_spec(entry)
    assert any("1024 characters" in e for e in errors)


def test_validate_spec_compatibility_too_long():
    """Compatibility exceeding 500 chars → error."""
    entry = _make_entry(compatibility="x" * 501)
    errors = _validate_spec(entry)
    assert any("500 characters" in e for e in errors)


def test_validate_spec_valid_with_hyphens_and_digits():
    """Valid name with hyphens and digits (my-skill-2) → no error."""
    entry = _make_entry(name="my-skill-2")
    errors = _validate_spec(entry)
    assert errors == []


# ── Layer 2: ProbOS metadata validation ──────────────────────────────


VALID_CONTEXT = {
    "valid_departments": {"bridge", "engineering", "science", "medical", "security", "operations", "*"},
    "valid_ranks": {"ensign", "lieutenant", "commander", "senior_officer"},
    "valid_skill_ids": {"cognitive_analysis", "report_writing"},
    "known_callsigns": {"Echo", "Meridian", "LaForge"},
}


@pytest.mark.asyncio
async def test_validate_valid_department(tmp_path):
    """Valid department ('science') → no error."""
    catalog = await _make_catalog(tmp_path)
    skill_dir = _write_skill(tmp_path / "config" / "skills", "valid-dept", textwrap.dedent("""\
        ---
        name: valid-dept
        description: Valid department
        metadata:
          probos-department: science
        ---
        Instructions here.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("valid-dept", VALID_CONTEXT)
    dept_errors = [e for e in result.errors if "department" in e.lower()]
    assert dept_errors == []


@pytest.mark.asyncio
async def test_validate_wildcard_department(tmp_path):
    """Wildcard department ('*') → no error."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "star-dept", textwrap.dedent("""\
        ---
        name: star-dept
        description: Wildcard department
        ---
        Instructions here.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("star-dept", VALID_CONTEXT)
    dept_errors = [e for e in result.errors if "department" in e.lower()]
    assert dept_errors == []


@pytest.mark.asyncio
async def test_validate_invalid_department(tmp_path):
    """Invalid department ('starfleet') → error."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "bad-dept", textwrap.dedent("""\
        ---
        name: bad-dept
        description: Invalid department
        metadata:
          probos-department: starfleet
        ---
        Instructions here.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("bad-dept", VALID_CONTEXT)
    assert not result.valid
    assert any("department" in e.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_validate_valid_rank(tmp_path):
    """Valid rank ('lieutenant') → no error."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "good-rank", textwrap.dedent("""\
        ---
        name: good-rank
        description: Valid rank
        metadata:
          probos-min-rank: lieutenant
        ---
        Instructions here.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("good-rank", VALID_CONTEXT)
    rank_errors = [e for e in result.errors if "rank" in e.lower()]
    assert rank_errors == []


@pytest.mark.asyncio
async def test_validate_invalid_rank(tmp_path):
    """Invalid rank ('admiral') → error."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "bad-rank", textwrap.dedent("""\
        ---
        name: bad-rank
        description: Invalid rank
        metadata:
          probos-min-rank: admiral
        ---
        Instructions here.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("bad-rank", VALID_CONTEXT)
    assert not result.valid
    assert any("rank" in e.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_validate_valid_proficiency(tmp_path):
    """Valid min_proficiency (1-5) → no error."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "good-prof", textwrap.dedent("""\
        ---
        name: good-prof
        description: Valid proficiency
        metadata:
          probos-min-proficiency: 3
        ---
        Instructions here.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("good-prof", VALID_CONTEXT)
    prof_errors = [e for e in result.errors if "proficiency" in e.lower()]
    assert prof_errors == []


@pytest.mark.asyncio
async def test_validate_invalid_proficiency(tmp_path):
    """Invalid min_proficiency (0, 6) → error."""
    catalog = await _make_catalog(tmp_path)
    # Register manually with proficiency=0
    entry = CognitiveSkillEntry(
        name="bad-prof",
        description="Bad prof",
        skill_dir=tmp_path / "config" / "skills" / "bad-prof",
        min_proficiency=0,
    )
    (entry.skill_dir).mkdir(parents=True, exist_ok=True)
    (entry.skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: bad-prof
        description: Bad prof
        ---
        Instructions.
    """), encoding="utf-8")
    await catalog.register(entry)

    result = await catalog.validate_skill("bad-prof", VALID_CONTEXT)
    assert not result.valid
    assert any("proficiency" in e.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_validate_skill_id_exists(tmp_path):
    """Non-empty skill_id exists in SkillRegistry → no warning."""
    catalog = await _make_catalog(tmp_path)
    entry = CognitiveSkillEntry(
        name="has-id",
        description="Has skill_id",
        skill_dir=tmp_path / "config" / "skills" / "has-id",
        skill_id="cognitive_analysis",
    )
    entry.skill_dir.mkdir(parents=True, exist_ok=True)
    (entry.skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: has-id
        description: Has skill_id
        ---
        Instructions.
    """), encoding="utf-8")
    await catalog.register(entry)

    result = await catalog.validate_skill("has-id", VALID_CONTEXT)
    assert not any("skill_id" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_validate_skill_id_not_found(tmp_path):
    """Non-empty skill_id NOT in SkillRegistry → warning."""
    catalog = await _make_catalog(tmp_path)
    entry = CognitiveSkillEntry(
        name="bad-id",
        description="Bad skill_id",
        skill_dir=tmp_path / "config" / "skills" / "bad-id",
        skill_id="nonexistent_skill",
    )
    entry.skill_dir.mkdir(parents=True, exist_ok=True)
    (entry.skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: bad-id
        description: Bad skill_id
        ---
        Instructions.
    """), encoding="utf-8")
    await catalog.register(entry)

    result = await catalog.validate_skill("bad-id", VALID_CONTEXT)
    assert any("skill_id" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_validate_empty_skill_id_no_warning(tmp_path):
    """Empty skill_id → no warning (ungoverned is fine)."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "no-id", textwrap.dedent("""\
        ---
        name: no-id
        description: No skill_id
        ---
        Instructions.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("no-id", VALID_CONTEXT)
    assert not any("skill_id" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_validate_no_context_skips_layers_2_3(tmp_path):
    """No validation_context → Layers 2-3 skipped gracefully."""
    catalog = await _make_catalog(tmp_path)
    entry = CognitiveSkillEntry(
        name="no-ctx",
        description="No context",
        skill_dir=tmp_path / "config" / "skills" / "no-ctx",
        department="starfleet",  # Would fail Layer 2 if checked
    )
    entry.skill_dir.mkdir(parents=True, exist_ok=True)
    (entry.skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: no-ctx
        description: No context
        ---
        Instructions.
    """), encoding="utf-8")
    await catalog.register(entry)

    # Without context, only Layer 1 runs — department won't be checked
    result = await catalog.validate_skill("no-ctx", validation_context=None)
    assert result.valid  # No spec errors


# ── Layer 3: Callsign linting ────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_callsign_in_body(tmp_path):
    """Instruction body contains hardcoded callsign → warning."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "callsign-test", SKILL_WITH_CALLSIGN)
    await catalog.scan_and_register()

    result = await catalog.validate_skill("callsign-test", VALID_CONTEXT)
    callsign_warnings = [w for w in result.warnings if "Callsign" in w]
    assert len(callsign_warnings) >= 1
    assert any("LaForge" in w for w in callsign_warnings)


@pytest.mark.asyncio
async def test_validate_callsign_substring_no_match(tmp_path):
    """Callsign as substring (not word boundary) → no warning."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "substring-test", textwrap.dedent("""\
        ---
        name: substring-test
        description: Substring test
        ---

        ## Instructions
        Use the echoing procedure for feedback.
    """))
    await catalog.scan_and_register()

    # "echoing" should NOT match "Echo" (word boundary)
    result = await catalog.validate_skill("substring-test", VALID_CONTEXT)
    callsign_warnings = [w for w in result.warnings if "Callsign" in w]
    assert callsign_warnings == []


@pytest.mark.asyncio
async def test_validate_no_callsigns_in_body(tmp_path):
    """Instruction body with no callsigns → no warnings."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "clean-skill", textwrap.dedent("""\
        ---
        name: clean-skill
        description: Clean skill
        ---

        ## Instructions
        Do the analysis step by step.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("clean-skill", VALID_CONTEXT)
    callsign_warnings = [w for w in result.warnings if "Callsign" in w]
    assert callsign_warnings == []


@pytest.mark.asyncio
async def test_validate_multiple_callsigns(tmp_path):
    """Multiple callsigns in body → multiple warnings."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "multi-callsign", SKILL_WITH_MULTIPLE_CALLSIGNS)
    await catalog.scan_and_register()

    result = await catalog.validate_skill("multi-callsign", VALID_CONTEXT)
    callsign_warnings = [w for w in result.warnings if "Callsign" in w]
    assert len(callsign_warnings) == 3


@pytest.mark.asyncio
async def test_validate_callsign_case_insensitive(tmp_path):
    """Case-insensitive match ('echo' vs 'Echo') → warning."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "case-test", textwrap.dedent("""\
        ---
        name: case-test
        description: Case test
        ---

        ## Instructions
        Talk to echo about the results.
    """))
    await catalog.scan_and_register()

    result = await catalog.validate_skill("case-test", VALID_CONTEXT)
    callsign_warnings = [w for w in result.warnings if "Callsign" in w]
    assert len(callsign_warnings) == 1
    assert "Echo" in callsign_warnings[0]


@pytest.mark.asyncio
async def test_validate_no_known_callsigns_skips_layer3(tmp_path):
    """No known_callsigns in context → Layer 3 skipped."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "no-cs-ctx", textwrap.dedent("""\
        ---
        name: no-cs-ctx
        description: No callsign context
        ---

        ## Instructions
        Talk to LaForge about warp core.
    """))
    await catalog.scan_and_register()

    ctx_no_callsigns = {
        "valid_departments": {"*"},
        "valid_ranks": {"ensign"},
    }
    result = await catalog.validate_skill("no-cs-ctx", ctx_no_callsigns)
    callsign_warnings = [w for w in result.warnings if "Callsign" in w]
    assert callsign_warnings == []


# ── validate_all() ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_all_mixed(tmp_path):
    """Multiple skills, mixed validity → returns all results."""
    catalog = await _make_catalog(tmp_path)
    # Valid skill
    _write_skill(tmp_path / "config" / "skills", "good-one", textwrap.dedent("""\
        ---
        name: good-one
        description: Good skill
        ---
        Instructions.
    """))
    # Invalid department
    _write_skill(tmp_path / "config" / "skills", "bad-one", textwrap.dedent("""\
        ---
        name: bad-one
        description: Bad skill
        metadata:
          probos-department: starfleet
        ---
        Instructions.
    """))
    await catalog.scan_and_register()

    results = await catalog.validate_all(VALID_CONTEXT)
    assert len(results) == 2
    names = {r.skill_name for r in results}
    assert "good-one" in names
    assert "bad-one" in names

    bad = next(r for r in results if r.skill_name == "bad-one")
    assert not bad.valid


@pytest.mark.asyncio
async def test_validate_all_empty():
    """Empty catalog → returns empty list."""
    catalog = CognitiveSkillCatalog()
    results = await catalog.validate_all(VALID_CONTEXT)
    assert results == []


# ── Enrichment validation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_with_valid_metadata_no_warnings(tmp_path):
    """Enrich with valid metadata + validation_context → no warnings logged."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "enrich-ok", textwrap.dedent("""\
        ---
        name: enrich-ok
        description: Enrichment test
        ---
        Instructions.
    """))
    await catalog.scan_and_register()

    entry = await catalog.enrich_skill(
        "enrich-ok",
        {"department": "science"},
        validation_context=VALID_CONTEXT,
    )
    assert entry.department == "science"


@pytest.mark.asyncio
async def test_enrich_with_invalid_department_warns(tmp_path, caplog):
    """Enrich with invalid department + validation_context → warning logged, enrichment succeeds."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "enrich-warn", textwrap.dedent("""\
        ---
        name: enrich-warn
        description: Enrichment warning test
        ---
        Instructions.
    """))
    await catalog.scan_and_register()

    import logging
    with caplog.at_level(logging.WARNING):
        entry = await catalog.enrich_skill(
            "enrich-warn",
            {"department": "starfleet"},
            validation_context=VALID_CONTEXT,
        )

    # Enrichment succeeds
    assert entry.department == "starfleet"
    # Warning was logged
    assert any("AD-596e" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_enrich_without_context_no_validation(tmp_path):
    """Enrich without validation_context → no validation run (backward compatible)."""
    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "enrich-novc", textwrap.dedent("""\
        ---
        name: enrich-novc
        description: No validation context
        ---
        Instructions.
    """))
    await catalog.scan_and_register()

    # No validation_context param — should not raise
    entry = await catalog.enrich_skill("enrich-novc", {"department": "starfleet"})
    assert entry.department == "starfleet"


# ── SkillValidationResult ────────────────────────────────────────────


def test_validation_result_to_dict():
    """SkillValidationResult.to_dict() returns correct structure."""
    result = SkillValidationResult(
        skill_name="test",
        valid=False,
        errors=["err1"],
        warnings=["warn1"],
    )
    d = result.to_dict()
    assert d["skill_name"] == "test"
    assert d["valid"] is False
    assert d["errors"] == ["err1"]
    assert d["warnings"] == ["warn1"]


def test_validate_skill_not_found():
    """validate_skill on nonexistent skill → not found error."""
    catalog = CognitiveSkillCatalog()

    import asyncio
    result = asyncio.get_event_loop().run_until_complete(
        catalog.validate_skill("nonexistent")
    )
    assert not result.valid
    assert any("not found" in e for e in result.errors)


# ── Shell command ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shell_validate_all(tmp_path):
    """/skill validate with no args → validates all, shows summary."""
    from rich.console import Console
    from io import StringIO

    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "shell-test", textwrap.dedent("""\
        ---
        name: shell-test
        description: Shell test skill
        ---
        Instructions.
    """))
    await catalog.scan_and_register()

    runtime = MagicMock()
    runtime.cognitive_skill_catalog = catalog
    runtime.skill_registry = None
    runtime.callsign_registry = None

    output = StringIO()
    console = Console(file=output, force_terminal=True)

    from probos.experience.commands.commands_skill import cmd_skill
    await cmd_skill(runtime, console, "validate")

    text = output.getvalue()
    assert "shell-test" in text
    assert "Summary" in text


@pytest.mark.asyncio
async def test_shell_validate_single(tmp_path):
    """/skill validate <name> → validates single skill, shows detail."""
    from rich.console import Console
    from io import StringIO

    catalog = await _make_catalog(tmp_path)
    _write_skill(tmp_path / "config" / "skills", "single-test", textwrap.dedent("""\
        ---
        name: single-test
        description: Single test skill
        ---
        Instructions.
    """))
    await catalog.scan_and_register()

    runtime = MagicMock()
    runtime.cognitive_skill_catalog = catalog
    runtime.skill_registry = None
    runtime.callsign_registry = None

    output = StringIO()
    console = Console(file=output, force_terminal=True)

    from probos.experience.commands.commands_skill import cmd_skill
    await cmd_skill(runtime, console, "validate single-test")

    text = output.getvalue()
    assert "single-test" in text
