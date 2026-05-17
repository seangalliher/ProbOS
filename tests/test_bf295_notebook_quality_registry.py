"""BF-295 / AD-634 follow-up: notebook-quality registered in SkillRegistry.

Pre-existing AD-596c skill_bridge warning since Wave 70 (AD-634):

  WARNING probos.cognitive.skill_bridge  AD-596c: Cognitive skill
  'notebook-quality' references skill_id 'notebook-quality' not
  found in SkillRegistry - proficiency gating will be inactive

Same fix shape as BF-294 (self-image-awareness): append matching
SkillDefinition to BUILTIN_PCCS so AD-596c reports "matched".
"""

from __future__ import annotations


def test_bf295_notebook_quality_in_builtin_pccs() -> None:
    from probos.skill_framework import BUILTIN_PCCS, SkillCategory

    by_id = {d.skill_id: d for d in BUILTIN_PCCS}
    assert "notebook-quality" in by_id, (
        "BF-295: notebook-quality must be in BUILTIN_PCCS so the AD-596c "
        "skill_bridge matches the cognitive SKILL.md at "
        "config/skills/notebook-quality/SKILL.md."
    )
    entry = by_id["notebook-quality"]
    assert entry.category is SkillCategory.PCC
    assert entry.domain == "*"
    assert entry.decay_rate_days == 30


def test_bf295_skill_id_matches_cognitive_skill_md_frontmatter() -> None:
    from pathlib import Path

    skill_md = Path("config/skills/notebook-quality/SKILL.md")
    assert skill_md.is_file()
    text = skill_md.read_text(encoding="utf-8")
    assert 'probos-skill-id: "notebook-quality"' in text or \
           "probos-skill-id: notebook-quality" in text, (
        "Cognitive SKILL.md frontmatter must declare probos-skill-id: notebook-quality."
    )
