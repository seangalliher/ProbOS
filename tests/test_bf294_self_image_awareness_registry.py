"""BF-294 / AD-728d follow-up: self-image-awareness registered in SkillRegistry.

Captain log on warm boot 2026-05-17:

  WARNING probos.cognitive.skill_bridge  AD-596c: Cognitive skill
  'self-image-awareness' references skill_id 'self-image-awareness' not
  found in SkillRegistry - proficiency gating will be inactive

AD-728d (Wave 165) shipped the cognitive SKILL.md but never added the
matching SkillDefinition to BUILTIN_PCCS. Bridge degrades cleanly to
"no gating" but the warning is noise + we lose the proficiency-progression
benefit. BF-294 closes the gap.
"""

from __future__ import annotations


def test_bf294_self_image_awareness_in_builtin_pccs() -> None:
    from probos.skill_framework import BUILTIN_PCCS, SkillCategory

    by_id = {d.skill_id: d for d in BUILTIN_PCCS}
    assert "self-image-awareness" in by_id, (
        "BF-294: self-image-awareness must be in BUILTIN_PCCS so the AD-596c "
        "skill_bridge matches the cognitive SKILL.md at "
        "config/skills/self-image-awareness/SKILL.md."
    )
    entry = by_id["self-image-awareness"]
    assert entry.category is SkillCategory.PCC, (
        "self-image-awareness is a universal crew skill (Captain in DM, "
        "Ward Room post, proactive cycles) — PCC category."
    )
    assert entry.domain == "*", "Universal crew skill must cover all departments."
    assert entry.decay_rate_days == 30, (
        "Mirror the other PCC entries' 30-day decay rate."
    )


def test_bf294_skill_id_matches_cognitive_skill_md_frontmatter() -> None:
    """The SkillRegistry skill_id MUST match the cognitive SKILL.md frontmatter
    `probos-skill-id` value or AD-596c skill_bridge classifies the skill as
    'unmatched'."""
    from pathlib import Path

    skill_md = Path("config/skills/self-image-awareness/SKILL.md")
    assert skill_md.is_file(), f"Cognitive SKILL.md must exist at {skill_md}"
    text = skill_md.read_text(encoding="utf-8")
    assert "probos-skill-id: self-image-awareness" in text, (
        "Cognitive SKILL.md frontmatter must declare "
        "probos-skill-id: self-image-awareness (matching the BUILTIN_PCCS entry)."
    )
