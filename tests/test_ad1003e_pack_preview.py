"""AD-1003e: pack content preview — read-only enumeration of a pack's declared
skill/agent component files (without loading/parsing/executing them).

BF-287: real tmp_path pack dirs with real component files; nothing is opened or
executed by the preview.
"""
from __future__ import annotations

import json
from pathlib import Path

from probos.packs import (
    PackComponent,
    PackContents,
    describe_pack_contents,
    preview_pack,
)


def _pack(tmp_path: Path, name: str, manifest: dict) -> Path:
    pack = tmp_path / name
    (pack / "plugin.json").parent.mkdir(parents=True, exist_ok=True)
    (pack / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pack


def _touch(pack: Path, rel: str, body: str = "x") -> None:
    p = pack / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# preview_pack
# ---------------------------------------------------------------------------


def test_preview_enumerates_folder_skills_and_agent_files(tmp_path: Path):
    pack = _pack(tmp_path, "dev", {"name": "dev-pack", "skills": "skills/", "agents": "agents/"})
    # folder-shaped skills (SKILL.md inside a subdir)
    _touch(pack, "skills/lint/SKILL.md")
    _touch(pack, "skills/format/SKILL.md")
    # a non-skill subdir (no SKILL.md) is ignored
    (pack / "skills" / "empty").mkdir()
    # agent definition files
    _touch(pack, "agents/reviewer.md")
    _touch(pack, "agents/builder.json")
    _touch(pack, "agents/notes.txt")  # wrong ext -> ignored

    contents = preview_pack(pack)
    assert isinstance(contents, PackContents)
    assert contents.name == "dev-pack"
    assert {c.name for c in contents.skills} == {"lint", "format"}
    assert all(c.kind == "skill" for c in contents.skills)
    assert {c.name for c in contents.agents} == {"reviewer", "builder"}
    assert "agents/reviewer.md" in {c.rel for c in contents.agents}


def test_preview_standalone_md_skills(tmp_path: Path):
    pack = _pack(tmp_path, "p", {"name": "p-pack", "skills": "skills/"})
    _touch(pack, "skills/summarize.md")
    _touch(pack, "skills/translate.md")
    contents = preview_pack(pack)
    assert {c.name for c in contents.skills} == {"summarize", "translate"}


def test_preview_missing_declared_dir_contributes_nothing(tmp_path: Path):
    # manifest declares skills/ + agents/ but neither dir exists -> empty, no error
    pack = _pack(tmp_path, "p", {"name": "p-pack"})
    contents = preview_pack(pack)
    assert contents is not None
    assert contents.skills == []
    assert contents.agents == []


def test_preview_reflects_hooks_and_mcp(tmp_path: Path):
    pack = _pack(tmp_path, "p", {"name": "p-pack", "hooks": "hooks.json", "mcpServers": ".mcp.json"})
    contents = preview_pack(pack)
    assert contents.has_hooks is True
    assert contents.has_mcp is True


def test_preview_no_manifest_returns_none(tmp_path: Path):
    (tmp_path / "not-a-pack").mkdir()
    assert preview_pack(tmp_path / "not-a-pack") is None


def test_preview_invalid_manifest_returns_none(tmp_path: Path):
    _pack(tmp_path, "bad", {"name": "Bad_Name"})  # kebab violation
    assert preview_pack(tmp_path / "bad") is None


def test_preview_does_not_escape_pack_dir(tmp_path: Path):
    # a declared path that tries to escape the pack dir is skipped (no traversal)
    pack = _pack(tmp_path, "p", {"name": "p-pack", "skills": "../outside/"})
    _touch(tmp_path, "outside/secret.md")  # exists, but outside the pack
    contents = preview_pack(pack)
    assert contents.skills == []


def test_pack_component_is_frozen():
    c = PackComponent(kind="skill", name="lint", rel="skills/lint")
    assert c.kind == "skill" and c.name == "lint"


# ---------------------------------------------------------------------------
# describe_pack_contents — serializable
# ---------------------------------------------------------------------------


def test_describe_pack_contents_shape(tmp_path: Path):
    pack = _pack(tmp_path, "dev", {"name": "dev-pack", "skills": "skills/", "agents": "agents/", "hooks": "h.json"})
    _touch(pack, "skills/lint/SKILL.md")
    _touch(pack, "agents/reviewer.md")
    out = describe_pack_contents(pack)
    assert out is not None
    assert out["name"] == "dev-pack"
    assert out["counts"] == {"skills": 1, "agents": 1}
    assert out["skills"][0]["name"] == "lint"
    assert out["agents"][0]["name"] == "reviewer"
    assert out["has_hooks"] is True


def test_describe_pack_contents_none_on_no_manifest(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    assert describe_pack_contents(tmp_path / "empty") is None
