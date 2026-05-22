"""AD-808: tests for the OpenClaw/Hermes migration tool."""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.migration import (
    execute_plan,
    plan_migration,
    render_text_report,
)


def _seed_openclaw(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SOUL.md").write_text("# Persona\nFriendly assistant.\n", encoding="utf-8")
    (root / "MEMORY.md").write_text("Memory line 1\n", encoding="utf-8")
    (root / "USER.md").write_text("User pref line\n", encoding="utf-8")
    (root / "commands.json").write_text('["ls", "cat"]\n', encoding="utf-8")
    (root / "api_keys.json").write_text('{"openai": "sk-xxx"}\n', encoding="utf-8")
    skills = root / "skills" / "summarizer"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# Summarizer\n", encoding="utf-8")


def _seed_hermes(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SOUL.md").write_text("# Hermes Persona\n", encoding="utf-8")
    (root / "memory").mkdir()
    (root / "memory" / "ep1.md").write_text("Episode 1\n", encoding="utf-8")
    (root / "personalities").mkdir()
    (root / "personalities" / "scholar.md").write_text("# Scholar\n", encoding="utf-8")
    (root / "hermes.json").write_text("{}\n", encoding="utf-8")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-yyy\n", encoding="utf-8")


def test_plan_openclaw_user_data_excludes_secrets(tmp_path):
    src = tmp_path / "openclaw"
    tgt = tmp_path / "probos"
    _seed_openclaw(src)
    report = plan_migration("openclaw", source_dir=src, target_root=tgt, preset="user-data")
    kinds = {item.kind for item in report.items}
    assert "soul" in kinds and "memory" in kinds and "skill" in kinds
    assert "api_key" not in kinds
    assert report.skipped_secrets >= 1


def test_plan_openclaw_full_preset_includes_secrets(tmp_path):
    src = tmp_path / "openclaw"
    tgt = tmp_path / "probos"
    _seed_openclaw(src)
    report = plan_migration("openclaw", source_dir=src, target_root=tgt, preset="full")
    kinds = {item.kind for item in report.items}
    assert "api_key" in kinds


def test_execute_plan_dry_run_writes_nothing(tmp_path):
    src = tmp_path / "openclaw"
    tgt = tmp_path / "probos"
    _seed_openclaw(src)
    report = plan_migration("openclaw", source_dir=src, target_root=tgt)
    execute_plan(report, dry_run=True)
    assert not (tgt / "imports").exists()
    assert report.dry_run is True
    assert report.written == 0


def test_execute_plan_apply_copies_files(tmp_path):
    src = tmp_path / "openclaw"
    tgt = tmp_path / "probos"
    _seed_openclaw(src)
    report = plan_migration("openclaw", source_dir=src, target_root=tgt)
    execute_plan(report, dry_run=False)
    assert (tgt / "imports" / "openclaw" / "SOUL.md").read_text(encoding="utf-8").startswith("# Persona")
    assert (tgt / "imports" / "openclaw" / "memories" / "MEMORY.md").exists()
    assert (tgt / "skills" / "openclaw-imports" / "summarizer" / "SKILL.md").exists()
    assert report.written >= 4


def test_execute_plan_skip_existing_by_default(tmp_path):
    src = tmp_path / "openclaw"
    tgt = tmp_path / "probos"
    _seed_openclaw(src)
    # Pre-populate destination
    soul_target = tgt / "imports" / "openclaw" / "SOUL.md"
    soul_target.parent.mkdir(parents=True)
    soul_target.write_text("existing\n", encoding="utf-8")
    report = plan_migration("openclaw", source_dir=src, target_root=tgt, overwrite=False)
    execute_plan(report, dry_run=False)
    assert soul_target.read_text(encoding="utf-8") == "existing\n"
    assert report.skipped_existing >= 1


def test_execute_plan_overwrite_replaces(tmp_path):
    src = tmp_path / "openclaw"
    tgt = tmp_path / "probos"
    _seed_openclaw(src)
    soul_target = tgt / "imports" / "openclaw" / "SOUL.md"
    soul_target.parent.mkdir(parents=True)
    soul_target.write_text("existing\n", encoding="utf-8")
    report = plan_migration("openclaw", source_dir=src, target_root=tgt, overwrite=True)
    execute_plan(report, dry_run=False)
    assert soul_target.read_text(encoding="utf-8").startswith("# Persona")


def test_plan_hermes_imports_memory_dir_and_personalities(tmp_path):
    src = tmp_path / "hermes"
    tgt = tmp_path / "probos"
    _seed_hermes(src)
    report = plan_migration("hermes", source_dir=src, target_root=tgt, preset="user-data")
    kinds = {item.kind for item in report.items}
    paths = {item.target_path for item in report.items}
    assert "memory" in kinds
    assert any("personalities" in p for p in paths)
    assert "api_key" not in kinds  # .env filtered as a secret


def test_plan_missing_source_returns_error_report(tmp_path):
    report = plan_migration("openclaw", source_dir=tmp_path / "nope", target_root=tmp_path / "probos")
    assert report.errors
    assert "not found" in report.errors[0].lower()


def test_render_text_report_includes_summary(tmp_path):
    src = tmp_path / "openclaw"
    tgt = tmp_path / "probos"
    _seed_openclaw(src)
    report = plan_migration("openclaw", source_dir=src, target_root=tgt)
    execute_plan(report, dry_run=True)
    out = render_text_report(report)
    assert "dry-run" in out
    assert "Total:" in out
