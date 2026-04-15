"""AD-634: Notebook Analytical Quality Skill — config-only AD.

Tests skill discovery, metadata, co-activation with other augmentation
skills, and content checks (proficiency levels, pre-write gate, anti-
patterns, no hardcoded callsigns).
"""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Shared paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _REPO_ROOT / "config" / "skills"
_SKILL_PATH = _SKILLS_DIR / "notebook-quality" / "SKILL.md"


# ---------------------------------------------------------------------------
# 1. TestSkillDiscovery
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    """Verify the skill file exists, parses, and validates."""

    def test_skill_file_exists(self):
        assert _SKILL_PATH.exists(), "config/skills/notebook-quality/SKILL.md missing"
        assert _SKILL_PATH.is_file()

    def test_skill_parses(self):
        from probos.cognitive.skill_catalog import parse_skill_file

        entry = parse_skill_file(_SKILL_PATH)
        assert entry is not None, "parse_skill_file returned None"

    def test_skill_validates(self):
        """validate_skill (Layer 1 only, no context) returns valid=True."""
        from probos.cognitive.skill_catalog import parse_skill_file, _validate_spec

        entry = parse_skill_file(_SKILL_PATH)
        assert entry is not None
        errors = _validate_spec(entry)
        assert errors == [], f"Validation errors: {errors}"

    def test_skill_name_matches_directory(self):
        from probos.cognitive.skill_catalog import parse_skill_file

        entry = parse_skill_file(_SKILL_PATH)
        assert entry is not None
        assert entry.name == "notebook-quality"
        assert entry.name == _SKILL_PATH.parent.name


# ---------------------------------------------------------------------------
# 2. TestSkillMetadata
# ---------------------------------------------------------------------------


class TestSkillMetadata:
    """Verify YAML frontmatter fields."""

    @pytest.fixture(autouse=True)
    def _load_entry(self):
        from probos.cognitive.skill_catalog import parse_skill_file

        self.entry = parse_skill_file(_SKILL_PATH)
        assert self.entry is not None

    def test_department_is_wildcard(self):
        assert self.entry.department == "*"

    def test_min_rank_is_ensign(self):
        assert self.entry.min_rank == "ensign"

    def test_activation_is_augmentation(self):
        assert self.entry.activation == "augmentation"

    def test_intent_is_proactive_think(self):
        assert "proactive_think" in self.entry.intents

    def test_skill_id(self):
        assert self.entry.skill_id == "notebook-quality"


# ---------------------------------------------------------------------------
# 3. TestCoActivation
# ---------------------------------------------------------------------------


class TestCoActivation:
    """Verify notebook-quality co-activates with other augmentation skills."""

    @pytest.fixture(autouse=True)
    def _load_entries(self):
        from probos.cognitive.skill_catalog import parse_skill_file

        self.notebook_entry = parse_skill_file(_SKILL_PATH)
        self.comm_entry = parse_skill_file(
            _SKILLS_DIR / "communication-discipline" / "SKILL.md"
        )
        self.leadership_entry = parse_skill_file(
            _SKILLS_DIR / "leadership-feedback" / "SKILL.md"
        )
        assert self.notebook_entry is not None
        assert self.comm_entry is not None
        assert self.leadership_entry is not None

    def test_both_skills_load_for_proactive_think(self):
        """Ensign-rank agent should get communication-discipline AND
        notebook-quality for proactive_think."""
        # Both must be augmentation + proactive_think + rank-eligible
        for entry in (self.comm_entry, self.notebook_entry):
            assert entry.activation in ("augmentation", "both")
            assert "proactive_think" in entry.intents
            assert entry.min_rank == "ensign"

    def test_leadership_feedback_adds_third(self):
        """lieutenant_commander+ agent should get all three skills."""
        all_entries = [self.comm_entry, self.notebook_entry, self.leadership_entry]
        for entry in all_entries:
            assert entry.activation in ("augmentation", "both")
            assert "proactive_think" in entry.intents

    @pytest.mark.asyncio
    async def test_catalog_finds_all_augmentation_skills(self):
        """Full catalog scan returns both ensign-rank augmentation skills."""
        from probos.cognitive.skill_catalog import CognitiveSkillCatalog

        catalog = CognitiveSkillCatalog(skills_dir=_SKILLS_DIR, db_path=None)
        # Manually scan without DB
        await catalog.scan_and_register()

        results = catalog.find_augmentation_skills(
            intent_name="proactive_think",
            agent_rank="ensign",
        )
        names = {e.name for e in results}
        assert "communication-discipline" in names
        assert "notebook-quality" in names


# ---------------------------------------------------------------------------
# 4. TestSkillContent
# ---------------------------------------------------------------------------


class TestSkillContent:
    """Verify skill body contains required sections."""

    @pytest.fixture(autouse=True)
    def _load_body(self):
        self.body = _SKILL_PATH.read_text(encoding="utf-8")

    def test_has_proficiency_progression(self):
        for level in ["FOLLOW", "ASSIST", "APPLY", "ENABLE", "ADVISE", "LEAD", "SHAPE"]:
            assert level in self.body, f"Missing proficiency level: {level}"

    def test_has_pre_write_gate(self):
        assert "Pre-Write" in self.body, "Missing Pre-Write Verification Gate"

    def test_has_anti_patterns(self):
        assert "Anti-Pattern" in self.body or "anti-pattern" in self.body.lower()

    def test_has_analytical_purpose_gate(self):
        assert "Analytical Purpose Gate" in self.body

    def test_has_finding_first_structure(self):
        assert "Finding-First" in self.body or "finding-first" in self.body.lower()

    def test_has_temporal_threading(self):
        assert "Temporal Threading" in self.body

    def test_has_data_vs_analysis(self):
        assert "Data vs Analysis" in self.body

    def test_has_ward_room_differentiation(self):
        assert "Ward Room Differentiation" in self.body

    def test_no_hardcoded_callsigns(self):
        """Skill body must not contain any known crew callsigns.

        Uses word-boundary matching consistent with validate_skill Layer 3.
        Generic English words that happen to be callsigns (e.g. "Data") are
        excluded — the production validator uses the same \b pattern.
        """
        import re

        from probos.cognitive.skill_catalog import get_skill_body

        body = get_skill_body(_SKILL_PATH)
        assert body is not None
        # Callsigns that are unlikely to appear as regular English words
        unambiguous_callsigns = [
            "Meridian", "LaForge", "Worf", "O'Brien",
            "Kira", "Lynx", "Scotty", "Forge",
        ]
        for callsign in unambiguous_callsigns:
            pattern = re.compile(r"\b" + re.escape(callsign) + r"\b", re.IGNORECASE)
            assert not pattern.search(body), (
                f"Hardcoded callsign '{callsign}' found in skill body"
            )
