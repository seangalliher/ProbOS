"""AD-721i-1 (Wave 166) - Avatar asset manifest parser + license whitelist tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.avatars.asset_manifest import (
    AssetManifest,
    AssetManifestEntry,
    validate_license,
)


REPO_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "avatar-assets" / "MANIFEST.md"


def test_asset_manifest_loads_from_v1_file() -> None:
    """The v1 manifest at data/avatar-assets/MANIFEST.md parses without raising."""
    manifest = AssetManifest.load(REPO_MANIFEST)
    assert isinstance(manifest, AssetManifest)
    # Has at least some rows (the RESEARCH candidates + REJECTED ones).
    assert len(manifest.entries) >= 4


def test_asset_manifest_v1_has_zero_approved_rows() -> None:
    """Guard: v1 ships zero APPROVED assets. Any future APPROVED row should
    be deliberate and reviewed."""
    manifest = AssetManifest.load(REPO_MANIFEST)
    assert manifest.approved() == []


def test_asset_manifest_all_dispositions_valid() -> None:
    """Every row in the v1 manifest has a valid disposition."""
    manifest = AssetManifest.load(REPO_MANIFEST)
    valid = {"APPROVED", "RESEARCH", "REJECTED"}
    for entry in manifest.entries:
        assert entry.disposition in valid, (
            f"Invalid disposition {entry.disposition!r} on {entry.name!r}"
        )


def test_asset_manifest_rejects_disallowed_licenses() -> None:
    assert validate_license("GPL-3.0") is False
    assert validate_license("AGPL-3.0") is False
    assert validate_license("CC-BY-SA-4.0") is False
    assert validate_license("CC-BY-NC-4.0") is False
    assert validate_license("Proprietary") is False
    assert validate_license("Per-file metadata (VRM)") is False
    assert validate_license("") is False


def test_asset_manifest_accepts_whitelisted_licenses() -> None:
    for lic in (
        "CC0", "CC0-1.0",
        "MIT",
        "Apache-2.0", "Apache 2.0",
        "BSD", "BSD-2-Clause", "BSD-3-Clause",
        "CC-BY-4.0", "CC-BY",
    ):
        assert validate_license(lic) is True, f"{lic!r} should be whitelisted"


def test_asset_manifest_approved_filter(tmp_path: Path) -> None:
    """Synthetic manifest with mixed dispositions; approved('base_mesh')
    returns only approved base meshes."""
    text = """# Synthetic manifest

## Base meshes (body_type)

| name | source_url | license | version | sha256 | attribution | disposition |
|------|------------|---------|---------|--------|-------------|-------------|
| approved_mesh | http://example.com/a.blend | CC0 | 1.0 | aaa | Example (CC0) | APPROVED |
| research_mesh | http://example.com/b.blend | CC0 | TBD | TBD | Example (CC0) | RESEARCH |

## Hair styles

| name | source_url | license | version | sha256 | attribution | disposition |
|------|------------|---------|---------|--------|-------------|-------------|
| approved_hair | http://example.com/h.blend | MIT | 1.0 | bbb | Example (MIT) | APPROVED |
"""
    manifest_path = tmp_path / "manifest.md"
    manifest_path.write_text(text, encoding="utf-8")
    manifest = AssetManifest.load(manifest_path)
    approved_base = manifest.approved("base_mesh")
    assert len(approved_base) == 1
    assert approved_base[0].name == "approved_mesh"
    approved_all = manifest.approved()
    assert len(approved_all) == 2
    research = manifest.by_disposition("RESEARCH")
    assert len(research) == 1
    assert research[0].name == "research_mesh"
