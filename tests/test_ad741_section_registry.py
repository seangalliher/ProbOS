"""AD-741: Section registry shape tests."""
from __future__ import annotations

import pytest

from probos.config import SystemConfig
from probos.settings.section_registry import (
    SECTIONS,
    FieldDescriptor,
    SectionDescriptor,
    domain_render_order,
    resolve_dot_path,
)


def test_every_section_domain_is_known() -> None:
    valid = set(domain_render_order())
    for section in SECTIONS:
        assert section.domain in valid, (
            f"AD-741 phantom domain {section.domain!r} on section {section.section_id!r}"
        )


def test_every_section_has_an_editable_field() -> None:
    """Every wired field-driven section is operator-actionable (no readonly-only sections).

    Custom-panel sections (``fields=()``) are exempt — they are rendered by a
    per-section branch in ``SettingsMain.tsx`` (e.g. AD-762 ``proactive``)
    and carry their own interactive controls outside the field-row pipeline.
    """
    for section in SECTIONS:
        if not section.fields:
            continue  # custom panel; rendered by SettingsMain branch
        kinds = {f.kind for f in section.fields}
        assert kinds - {"readonly"}, (
            f"Section {section.section_id!r} has only readonly fields — "
            f"belongs in raw YAML editing (AD-741-6)."
        )


def test_ad762_proactive_section_registered() -> None:
    """AD-762: the relocated proactive status surface has a Core/custom-panel slot."""
    proactive = next((s for s in SECTIONS if s.section_id == "proactive"), None)
    assert proactive is not None, "AD-762 proactive section missing from SECTIONS"
    assert proactive.label == "Proactive"
    assert proactive.domain == "Core"
    assert proactive.fields == (), (
        "AD-762 proactive is a custom panel rendered by SettingsMain branch; "
        "fields tuple must stay empty (see AD-762 spec §2)."
    )


def test_every_field_id_resolves_against_system_config() -> None:
    """Standing-rule guard: prevents phantom field references between waves."""
    cfg = SystemConfig()
    for section in SECTIONS:
        for f in section.fields:
            resolve_dot_path(cfg, f.field_id)


def test_dataclass_frozen() -> None:
    sd = SectionDescriptor(
        section_id="x", label="X", glyph="?", domain="Core", description="",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        sd.label = "Y"  # type: ignore[misc]
    fd = FieldDescriptor("a.b", "Label", "text")
    with pytest.raises(Exception):
        fd.label = "Other"  # type: ignore[misc]
