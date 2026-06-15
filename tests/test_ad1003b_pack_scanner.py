"""AD-1003b: Capability-Pack scanner tests.

Read-only inventory of a packs directory. BF-287: real pack dirs on tmp_path
(real manifest files), no mocks. Nothing is installed/executed.
"""
from __future__ import annotations

import json
from pathlib import Path

from probos.packs import PackEntry, describe_scan, scan_packs


def _write_pack(packs_dir: Path, name: str, manifest: dict, rel: str = "plugin.json") -> Path:
    pack = packs_dir / name
    mpath = pack / rel
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    return pack


# ---------------------------------------------------------------------------
# scan_packs
# ---------------------------------------------------------------------------


def test_scan_empty_or_missing_dir(tmp_path: Path):
    assert scan_packs(tmp_path / "does-not-exist") == []
    (tmp_path / "empty").mkdir()
    assert scan_packs(tmp_path / "empty") == []


def test_scan_finds_valid_packs_sorted_by_name(tmp_path: Path):
    _write_pack(tmp_path, "zeta-dir", {"name": "zeta-pack", "version": "1.0.0"})
    _write_pack(tmp_path, "alpha-dir", {"name": "alpha-pack", "version": "2.0.0"})
    entries = scan_packs(tmp_path)
    assert [e.name for e in entries] == ["alpha-pack", "zeta-pack"]  # by manifest name
    assert all(e.ok for e in entries)
    assert entries[0].summary is not None
    assert entries[0].summary.version == "2.0.0"


def test_scan_skips_non_pack_subdirs(tmp_path: Path):
    _write_pack(tmp_path, "real", {"name": "real-pack"})
    (tmp_path / "just-a-folder").mkdir()
    (tmp_path / "just-a-folder" / "readme.txt").write_text("hi", encoding="utf-8")
    entries = scan_packs(tmp_path)
    assert [e.name for e in entries] == ["real-pack"]


def test_scan_bad_pack_becomes_error_entry_scan_continues(tmp_path: Path):
    _write_pack(tmp_path, "good", {"name": "good-pack"})
    # invalid: name violates the kebab-case rule -> PackParseError on load
    _write_pack(tmp_path, "bad", {"name": "Bad_Name"})
    entries = scan_packs(tmp_path)
    by_name = {e.name: e for e in entries}
    assert by_name["good-pack"].ok is True
    # the bad pack reports under its DIRECTORY name (manifest name unavailable)
    assert "bad" in by_name
    assert by_name["bad"].ok is False
    assert by_name["bad"].error is not None


def test_scan_malformed_json_is_error_entry(tmp_path: Path):
    pack = tmp_path / "broken"
    (pack).mkdir()
    (pack / "plugin.json").write_text("{ not json", encoding="utf-8")
    entries = scan_packs(tmp_path)
    assert len(entries) == 1
    assert entries[0].ok is False
    assert "malformed JSON" in (entries[0].error or "")


def test_scan_detects_claude_format_manifest(tmp_path: Path):
    _write_pack(tmp_path, "claude-style", {"name": "claude-pack"}, rel=".claude-plugin/plugin.json")
    entries = scan_packs(tmp_path)
    assert [e.name for e in entries] == ["claude-pack"]


def test_pack_entry_ok_and_name_helpers():
    ok = PackEntry(path="/p/x", summary=None, error="boom")
    assert ok.ok is False
    assert ok.name == "x"  # falls back to dir name on error


# ---------------------------------------------------------------------------
# describe_scan — serializable inventory
# ---------------------------------------------------------------------------


def test_describe_scan_shape(tmp_path: Path):
    _write_pack(tmp_path, "p1", {
        "name": "tools-pack", "version": "1.2.0", "description": "dev tools",
        "hooks": "hooks.json",
    })
    _write_pack(tmp_path, "p2", {"name": "Bad_Name"})  # invalid
    out = describe_scan(tmp_path)
    assert out["counts"] == {"total": 2, "valid": 1, "error": 1}
    by_name = {p["name"]: p for p in out["packs"]}  # type: ignore[index]
    assert by_name["tools-pack"]["ok"] is True
    assert by_name["tools-pack"]["version"] == "1.2.0"
    assert by_name["tools-pack"]["has_hooks"] is True
    assert by_name["tools-pack"]["has_mcp"] is False
    assert by_name["p2"]["ok"] is False
    assert by_name["p2"]["error"]


def test_describe_scan_empty(tmp_path: Path):
    out = describe_scan(tmp_path / "nope")
    assert out == {"packs": [], "counts": {"total": 0, "valid": 0, "error": 0}}
