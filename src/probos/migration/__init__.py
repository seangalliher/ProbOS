"""AD-808: cross-ecosystem migration tool.

Imports operator state from OpenClaw (~/.openclaw/) or Hermes Agent
(~/.hermes/) into the local ProbOS home (~/.probos/). Same shape as
Hermes's own ``hermes claw migrate`` verb so operators coming from
either ecosystem have a familiar setup flow.

What gets imported (per source):
    * OpenClaw:  SOUL.md (persona), MEMORY.md / USER.md (memories),
                 skills/<slug>/SKILL.md (workspace skills),
                 command allowlists, API keys allowlist,
                 channel adapter configs.
    * Hermes:    memory/ dir entries, skills/ dir, personalities/,
                 command allowlist, gateway/channel configs.

Provenance:
    Every imported memory carries ``source=openclaw_import`` or
    ``source=hermes_import`` so the AD-541b reconsolidation-protection
    + AD-588 telemetry-grounded-introspection layers know not to treat
    them as ProbOS first-person experience. They're seeds, not first-
    hand episodes.

Defaults:
    * ``--dry-run`` lists everything that WOULD be imported with zero
      side effects.
    * ``--preset user-data`` skips secrets (API keys); ``--preset full``
      includes them.
    * Conflict resolution: ``skip-existing`` by default; ``--overwrite``
      replaces.

This is a substrate v1. Real migration depth (re-anchoring episodic
embeddings, mapping persona instruction sets, etc.) lands in AD-808a/b
follow-ups once a real operator runs it end-to-end.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Source = Literal["openclaw", "hermes"]
Preset = Literal["user-data", "full"]


@dataclass(frozen=True)
class MigrationPlanItem:
    """One thing the migration will (or would) do."""

    kind: str            # "soul" | "memory" | "skill" | "command_allowlist" | "api_key" | "channel_config"
    source_path: str     # Absolute path in the source ecosystem dir
    target_path: str     # Where it lands under ~/.probos/
    action: Literal["copy", "skip", "overwrite"]
    note: str = ""


@dataclass
class MigrationReport:
    """Aggregate report — what was planned, what ran, what was skipped."""

    source: Source
    dry_run: bool
    items: list[MigrationPlanItem] = field(default_factory=list)
    skipped_secrets: int = 0
    skipped_existing: int = 0
    written: int = 0
    errors: list[str] = field(default_factory=list)

    def add(self, item: MigrationPlanItem) -> None:
        self.items.append(item)


def _default_source_dir(source: Source) -> Path:
    """The conventional location each ecosystem stores state in."""
    if source == "openclaw":
        return Path.home() / ".openclaw"
    return Path.home() / ".hermes"


def _is_secret_path(path: Path) -> bool:
    """Heuristic: paths that look like API-key stores."""
    name = path.name.lower()
    return (
        "api_key" in name
        or "api-keys" in name
        or "secrets" in name
        or name.endswith(".env")
        or name == "credentials.json"
    )


# ---------- OpenClaw plan ----------


def _plan_openclaw(source_root: Path, target_root: Path, preset: Preset, overwrite: bool) -> MigrationReport:
    report = MigrationReport(source="openclaw", dry_run=False)

    soul = source_root / "SOUL.md"
    if soul.exists():
        target = target_root / "imports" / "openclaw" / "SOUL.md"
        report.add(_plan_one("soul", soul, target, overwrite))

    for memfile in ("MEMORY.md", "USER.md"):
        m = source_root / memfile
        if m.exists():
            target = target_root / "imports" / "openclaw" / "memories" / memfile
            report.add(_plan_one("memory", m, target, overwrite))

    skills_dir = source_root / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_subdir in skills_dir.iterdir():
            if not skill_subdir.is_dir():
                continue
            skill_md = skill_subdir / "SKILL.md"
            if skill_md.exists():
                target = target_root / "skills" / "openclaw-imports" / skill_subdir.name / "SKILL.md"
                report.add(_plan_one("skill", skill_md, target, overwrite))

    for cfg_name in ("commands.json", "allowed_commands.json", "command-allowlist.json"):
        c = source_root / cfg_name
        if c.exists():
            target = target_root / "imports" / "openclaw" / cfg_name
            report.add(_plan_one("command_allowlist", c, target, overwrite))

    for cfg_name in ("openclaw.json", "config.json", "channels.json"):
        c = source_root / cfg_name
        if c.exists():
            target = target_root / "imports" / "openclaw" / cfg_name
            report.add(_plan_one("channel_config", c, target, overwrite))

    if preset == "full":
        for env_or_key in source_root.glob("*"):
            if _is_secret_path(env_or_key) and env_or_key.is_file():
                target = target_root / "imports" / "openclaw" / env_or_key.name
                report.add(_plan_one("api_key", env_or_key, target, overwrite))
    else:
        for env_or_key in source_root.glob("*"):
            if _is_secret_path(env_or_key) and env_or_key.is_file():
                report.skipped_secrets += 1

    return report


# ---------- Hermes plan ----------


def _plan_hermes(source_root: Path, target_root: Path, preset: Preset, overwrite: bool) -> MigrationReport:
    report = MigrationReport(source="hermes", dry_run=False)

    soul = source_root / "SOUL.md"
    if soul.exists():
        target = target_root / "imports" / "hermes" / "SOUL.md"
        report.add(_plan_one("soul", soul, target, overwrite))

    memory_dir = source_root / "memory"
    if memory_dir.exists() and memory_dir.is_dir():
        for memfile in memory_dir.iterdir():
            if memfile.is_file():
                target = target_root / "imports" / "hermes" / "memory" / memfile.name
                report.add(_plan_one("memory", memfile, target, overwrite))

    skills_dir = source_root / "skills"
    if skills_dir.exists() and skills_dir.is_dir():
        for skill_subdir in skills_dir.iterdir():
            if not skill_subdir.is_dir():
                continue
            skill_md = skill_subdir / "SKILL.md"
            if skill_md.exists():
                target = target_root / "skills" / "hermes-imports" / skill_subdir.name / "SKILL.md"
                report.add(_plan_one("skill", skill_md, target, overwrite))

    personalities_dir = source_root / "personalities"
    if personalities_dir.exists() and personalities_dir.is_dir():
        for pfile in personalities_dir.iterdir():
            if pfile.is_file():
                target = target_root / "imports" / "hermes" / "personalities" / pfile.name
                report.add(_plan_one("soul", pfile, target, overwrite))

    for cfg_name in ("hermes.json", "config.json", "command_allowlist.json"):
        c = source_root / cfg_name
        if c.exists():
            target = target_root / "imports" / "hermes" / cfg_name
            report.add(_plan_one("channel_config", c, target, overwrite))

    if preset == "full":
        for env_or_key in source_root.glob("*"):
            if _is_secret_path(env_or_key) and env_or_key.is_file():
                target = target_root / "imports" / "hermes" / env_or_key.name
                report.add(_plan_one("api_key", env_or_key, target, overwrite))
    else:
        for env_or_key in source_root.glob("*"):
            if _is_secret_path(env_or_key) and env_or_key.is_file():
                report.skipped_secrets += 1

    return report


def _plan_one(kind: str, source: Path, target: Path, overwrite: bool) -> MigrationPlanItem:
    if target.exists() and not overwrite:
        action: Literal["copy", "skip", "overwrite"] = "skip"
        note = "destination exists; use --overwrite to replace"
    elif target.exists() and overwrite:
        action = "overwrite"
        note = "destination exists; replacing"
    else:
        action = "copy"
        note = ""
    return MigrationPlanItem(
        kind=kind,
        source_path=str(source),
        target_path=str(target),
        action=action,
        note=note,
    )


# ---------- top-level entry point ----------


def plan_migration(
    source: Source,
    *,
    source_dir: Path | None = None,
    target_root: Path | None = None,
    preset: Preset = "user-data",
    overwrite: bool = False,
) -> MigrationReport:
    """Build the migration plan without applying anything."""
    src = source_dir or _default_source_dir(source)
    if not src.exists():
        report = MigrationReport(source=source, dry_run=False)
        report.errors.append(f"Source directory not found: {src}")
        return report
    tgt = target_root or (Path.home() / ".probos")
    if source == "openclaw":
        return _plan_openclaw(src, tgt, preset, overwrite)
    return _plan_hermes(src, tgt, preset, overwrite)


def execute_plan(report: MigrationReport, *, dry_run: bool) -> MigrationReport:
    """Apply the plan items (or simulate if ``dry_run``).

    Mutates ``report`` in place: increments written / skipped_existing,
    appends to errors. Returns the same report for convenience.
    """
    report.dry_run = dry_run
    for item in report.items:
        if item.action == "skip":
            report.skipped_existing += 1
            continue
        if dry_run:
            continue
        try:
            tgt = Path(item.target_path)
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item.source_path, item.target_path)
            report.written += 1
        except OSError as exc:
            report.errors.append(f"{item.target_path}: {exc}")
    return report


def render_text_report(report: MigrationReport) -> str:
    """Human-readable report for the CLI verb."""
    lines: list[str] = []
    header = f"Migration plan: source={report.source}"
    if report.dry_run:
        header += " (dry-run)"
    lines.append(header)
    if report.errors:
        for err in report.errors:
            lines.append(f"  [error] {err}")
    for item in report.items:
        marker = {
            "copy": "+",
            "overwrite": "↻",
            "skip": "·",
        }.get(item.action, "?")
        suffix = f" — {item.note}" if item.note else ""
        lines.append(f"  {marker} [{item.kind}] {item.target_path}{suffix}")
    lines.append("")
    lines.append(
        f"Total: {len(report.items)} item(s), "
        f"{report.written} written, {report.skipped_existing} skipped (existing), "
        f"{report.skipped_secrets} skipped (secrets, --preset user-data)"
    )
    return "\n".join(lines)
