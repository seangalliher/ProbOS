"""AD-1003b: Capability-Pack scanner — read-only inventory of installed packs.

Walks a packs directory and reports what packs are present, the way VS Code /
Copilot CLI / Claude Code list installed plugins. Builds on the AD-1003a manifest
parser (``find_manifest`` / ``load_manifest`` / ``describe_pack``).

**Read-only — NOTHING is installed, loaded, executed, or wired.** A pack whose
manifest is malformed or invalid is reported as an error entry rather than
crashing the scan (honest-degrade), so one bad pack never hides the others. The
loader (mapping a pack into the live registries behind the operator trust gate)
and any execution are later slices.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from probos.packs.manifest import (
    PackParseError,
    PackSummary,
    describe_pack,
    find_manifest,
    load_manifest,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PackEntry:
    """One discovered pack directory.

    ``summary`` is the parsed, validated :class:`PackSummary` when the pack's
    manifest is well-formed; ``error`` carries the parse/validate failure message
    when it is not (mutually exclusive — exactly one is set). ``path`` is the
    pack directory (the folder containing the manifest, not the manifest file).
    """

    path: str
    summary: PackSummary | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when the pack's manifest parsed and validated."""
        return self.summary is not None and self.error is None

    @property
    def name(self) -> str:
        """The pack name (from the manifest) or the directory name on error."""
        if self.summary is not None:
            return self.summary.name
        return Path(self.path).name


def scan_packs(packs_dir: str | Path) -> list[PackEntry]:
    """Inventory the immediate subdirectories of ``packs_dir`` that hold a pack.

    A subdirectory is a pack candidate when ``find_manifest`` locates a manifest
    in it (any of the cross-tool locations). Each candidate is loaded + described
    (AD-1003a); a malformed/invalid manifest becomes an error :class:`PackEntry`
    rather than raising. Returns the entries sorted by name.

    Honest-degrade: a missing or non-directory ``packs_dir`` (the default —
    nothing installed) returns ``[]``; a directory that cannot be listed logs a
    warning and returns ``[]``. NEVER raises. Read-only — nothing is installed,
    loaded, executed, or wired.
    """
    base = Path(packs_dir)
    if not base.is_dir():
        return []
    try:
        children = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        logger.warning(
            "AD-1003b: could not list packs directory %s; reporting no packs",
            base, exc_info=True,
        )
        return []

    entries: list[PackEntry] = []
    for child in children:
        if find_manifest(child) is None:
            continue  # not a pack directory — skip silently
        try:
            manifest = load_manifest(child)
            entries.append(PackEntry(path=str(child), summary=describe_pack(manifest)))
        except PackParseError as exc:
            logger.warning(
                "AD-1003b: pack at %s has an invalid manifest; reporting as error "
                "(scan continues): %s", child, exc,
            )
            entries.append(PackEntry(path=str(child), error=str(exc)))
    entries.sort(key=lambda e: e.name)
    return entries


def describe_scan(packs_dir: str | Path) -> dict[str, object]:
    """A serializable inventory of ``packs_dir`` — the read-only "installed
    packs" surface (the shape a future ``GET /api/packs`` / UI list would use).

    ``packs`` carries one dict per discovered pack (name/version/description +
    component presence on success, or ``error`` on failure); ``counts`` totals
    valid vs error packs. Honest-degrade mirrors :func:`scan_packs`.
    """
    entries = scan_packs(packs_dir)
    packs: list[dict[str, object]] = []
    for e in entries:
        if e.ok and e.summary is not None:
            packs.append({
                "name": e.summary.name,
                "version": e.summary.version,
                "description": e.summary.description,
                "path": e.path,
                "skill_paths": list(e.summary.skill_paths),
                "agent_paths": list(e.summary.agent_paths),
                "has_hooks": e.summary.has_hooks,
                "has_mcp": e.summary.has_mcp,
                "ok": True,
            })
        else:
            packs.append({"name": e.name, "path": e.path, "error": e.error, "ok": False})
    return {
        "packs": packs,
        "counts": {
            "total": len(entries),
            "valid": sum(1 for e in entries if e.ok),
            "error": sum(1 for e in entries if not e.ok),
        },
    }


__all__ = ["PackEntry", "scan_packs", "describe_scan"]
