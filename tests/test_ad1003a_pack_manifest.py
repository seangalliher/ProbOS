"""AD-1003a: Capability-Pack manifest parser/validator tests.

The read-only parse + validate layer for the cross-tool agent-plugin format
(VS Code / Copilot CLI / Claude Code plugin.json). BF-287: real files on
tmp_path, real Pydantic validation — no mocks.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from probos.packs import (
    PackManifest,
    PackParseError,
    describe_pack,
    find_manifest,
    load_manifest,
    parse_manifest,
)


def _write(pack_dir: Path, rel: str, data: dict) -> Path:
    p = pack_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# parse_manifest — schema + validation
# ---------------------------------------------------------------------------


def test_minimal_manifest():
    m = parse_manifest({"name": "my-dev-tools"})
    assert m.name == "my-dev-tools"
    # conventional defaults
    assert m.skill_paths() == ["skills/"]
    assert m.agent_paths() == ["agents/"]
    assert m.has_hooks() is False
    assert m.has_mcp() is False


def test_full_manifest_with_aliases():
    m = parse_manifest({
        "name": "react-utils",
        "description": "React development utilities",
        "version": "1.2.0",
        "author": {"name": "Jane Doe", "email": "jane@example.com"},
        "skills": ["skills/", "extra-skills/"],
        "agents": "agents/",
        "hooks": "hooks.json",
        "mcpServers": ".mcp.json",
    })
    assert m.version == "1.2.0"
    assert m.author is not None and m.author.name == "Jane Doe"
    assert m.skill_paths() == ["skills/", "extra-skills/"]
    assert m.has_hooks() is True
    assert m.has_mcp() is True  # mcpServers alias mapped


def test_inline_hooks_and_mcp_objects():
    m = parse_manifest({
        "name": "db-pack",
        "hooks": {"PostToolUse": [{"type": "command", "command": "fmt.sh"}]},
        "mcpServers": {"db": {"command": "db-server"}},
    })
    assert m.has_hooks() is True
    assert m.has_mcp() is True
    assert isinstance(m.hooks, dict)


def test_probos_extensions_preserved_via_extra():
    # ProbOS-native additive keys ride through (extra="allow") so a ProbOS pack
    # stays a valid base plugin elsewhere.
    m = parse_manifest({
        "name": "probos-pack",
        "meshIntentGrants": ["run_python"],
        "standingOrders": "orders/",
    })
    extra = m.model_dump()
    assert extra.get("meshIntentGrants") == ["run_python"]


# ---------------------------------------------------------------------------
# name validation — the cross-tool kebab-case rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    "MyPlugin",        # uppercase
    "my_plugin",       # underscore
    "myorg/my-plugin", # namespace prefix / slash
    "my:plugin",       # colon
    "-leading",        # leading hyphen
    "",                # empty
])
def test_invalid_names_raise(bad: str):
    with pytest.raises(PackParseError):
        parse_manifest({"name": bad})


def test_valid_kebab_names():
    for ok in ("my-dev-tools", "plugin1", "a", "test-runner-2"):
        assert parse_manifest({"name": ok}).name == ok


def test_name_too_long_raises():
    with pytest.raises(PackParseError):
        parse_manifest({"name": "a" * 65})


def test_description_too_long_raises():
    with pytest.raises(PackParseError):
        parse_manifest({"name": "ok", "description": "x" * 1025})


def test_non_dict_raises():
    with pytest.raises(PackParseError):
        parse_manifest(["not", "a", "dict"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# find_manifest — cross-tool auto-detection order
# ---------------------------------------------------------------------------


def test_find_manifest_detection_order(tmp_path: Path):
    # When multiple exist, .plugin/plugin.json wins (first in the order).
    _write(tmp_path, "plugin.json", {"name": "root"})
    _write(tmp_path, ".plugin/plugin.json", {"name": "dot-plugin"})
    found = find_manifest(tmp_path)
    assert found == tmp_path / ".plugin/plugin.json"


def test_find_manifest_claude_format(tmp_path: Path):
    _write(tmp_path, ".claude-plugin/plugin.json", {"name": "claude-pack"})
    found = find_manifest(tmp_path)
    assert found == tmp_path / ".claude-plugin/plugin.json"


def test_find_manifest_absent(tmp_path: Path):
    assert find_manifest(tmp_path) is None


# ---------------------------------------------------------------------------
# load_manifest — find + read + validate
# ---------------------------------------------------------------------------


def test_load_manifest_happy(tmp_path: Path):
    _write(tmp_path, "plugin.json", {"name": "loaded-pack", "version": "0.1.0"})
    m = load_manifest(tmp_path)
    assert isinstance(m, PackManifest)
    assert m.name == "loaded-pack"


def test_load_manifest_missing_raises(tmp_path: Path):
    with pytest.raises(PackParseError, match="no plugin.json manifest"):
        load_manifest(tmp_path)


def test_load_manifest_malformed_json_raises(tmp_path: Path):
    p = tmp_path / "plugin.json"
    p.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(PackParseError, match="malformed JSON"):
        load_manifest(tmp_path)


# ---------------------------------------------------------------------------
# describe_pack — install preview
# ---------------------------------------------------------------------------


def test_describe_pack():
    m = parse_manifest({
        "name": "test-runner", "version": "2.0.0",
        "skills": "skills/", "hooks": "hooks.json",
    })
    s = describe_pack(m)
    assert s.name == "test-runner"
    assert s.version == "2.0.0"
    assert s.skill_paths == ["skills/"]
    assert s.has_hooks is True
    assert s.has_mcp is False
