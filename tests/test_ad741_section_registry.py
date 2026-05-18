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
    """Every wired section is operator-actionable (no readonly-only sections)."""
    for section in SECTIONS:
        kinds = {f.kind for f in section.fields}
        assert kinds - {"readonly"}, (
            f"Section {section.section_id!r} has only readonly fields — "
            f"belongs in raw YAML editing (AD-741-6)."
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
