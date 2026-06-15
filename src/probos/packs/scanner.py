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

# AD-1003e: file extensions enumerated as components when previewing a pack's
# declared directories. Cross-tool agent-plugins keep skills as Markdown
# (``SKILL.md``) and agents as Markdown / JSON; ``.py`` is included so a pack
# can ship a deterministic tool/agent handler. The preview LISTS these files —
# it never opens, parses, imports, or executes them.
_SKILL_EXTS = (".md",)
_AGENT_EXTS = (".md", ".json", ".py")


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


@dataclass(frozen=True)
class PackComponent:
    """One component file a pack declares (a skill or agent definition).

    ``kind`` is ``"skill"`` or ``"agent"``; ``name`` is the display name (the
    enclosing directory name for a ``SKILL.md``, else the file stem); ``rel`` is
    the path relative to the pack directory. The preview only records that the
    file EXISTS — it is never opened, parsed, imported, or executed.
    """

    kind: str
    name: str
    rel: str


@dataclass(frozen=True)
class PackContents:
    """Read-only preview of what a pack DECLARES (AD-1003e).

    Enumerates the component files under the pack's declared ``skill_paths`` /
    ``agent_paths`` (from the AD-1003a manifest) so the operator can see what a
    pack contains BEFORE deciding to load it. Loading + executing those
    components is the deferred loader slice (behind the operator trust gate);
    this is the read-only inventory that slice will build on.
    """

    name: str
    skills: list[PackComponent]
    agents: list[PackComponent]
    has_hooks: bool
    has_mcp: bool


def _enumerate_components(
    pack_dir: Path, rel_paths: list[str], kind: str, exts: tuple[str, ...],
) -> list[PackComponent]:
    """List the component files under each declared ``rel_paths`` directory.

    A declared path that does not exist contributes nothing (no error). For a
    skill directory, an immediate subdirectory containing a ``SKILL.md`` counts
    as one skill (the conventional folder-skill shape); standalone files with a
    matching extension count individually. Read-only: directories are listed,
    files are never opened. Never raises (Tier-2 honest-degrade per declared
    path).
    """
    out: list[PackComponent] = []
    seen: set[str] = set()
    for rel in rel_paths:
        base = (pack_dir / rel).resolve()
        # Stay within the pack dir — a declared path must not escape it.
        try:
            base.relative_to(pack_dir.resolve())
        except ValueError:
            logger.warning(
                "AD-1003e: declared %s path %r escapes the pack dir; skipped",
                kind, rel,
            )
            continue
        if not base.is_dir():
            continue
        try:
            children = sorted(base.iterdir(), key=lambda p: p.name)
        except OSError:
            logger.warning(
                "AD-1003e: could not list %s dir %s; skipped", kind, base, exc_info=True,
            )
            continue
        for child in children:
            try:
                if kind == "skill" and child.is_dir() and (child / "SKILL.md").is_file():
                    relpath = child.relative_to(pack_dir).as_posix()
                    if relpath not in seen:
                        seen.add(relpath)
                        out.append(PackComponent(kind=kind, name=child.name, rel=relpath))
                elif child.is_file() and child.suffix.lower() in exts:
                    relpath = child.relative_to(pack_dir).as_posix()
                    if relpath not in seen:
                        seen.add(relpath)
                        out.append(PackComponent(kind=kind, name=child.stem, rel=relpath))
            except OSError:
                logger.debug("AD-1003e: stat failed for %s; skipped", child, exc_info=True)
    return out


def preview_pack(pack_dir: str | Path) -> PackContents | None:
    """AD-1003e: read-only preview of a pack's DECLARED components.

    Loads the pack's manifest (AD-1003a) and enumerates the actual skill/agent
    files under its declared ``skill_paths`` / ``agent_paths``. Returns ``None``
    when the directory has no valid manifest (honest-degrade). **Read-only —
    nothing is opened, parsed, imported, or executed**; this is the inventory the
    deferred loader will consume, surfaced now so the operator can inspect a pack
    before loading it. Never raises.
    """
    base = Path(pack_dir)
    try:
        manifest = load_manifest(base)
    except PackParseError:
        return None
    return PackContents(
        name=manifest.name,
        skills=_enumerate_components(base, manifest.skill_paths(), "skill", _SKILL_EXTS),
        agents=_enumerate_components(base, manifest.agent_paths(), "agent", _AGENT_EXTS),
        has_hooks=manifest.has_hooks(),
        has_mcp=manifest.has_mcp(),
    )


def describe_pack_contents(pack_dir: str | Path) -> dict[str, object] | None:
    """Serializable form of :func:`preview_pack` (the shape a future
    ``GET /api/packs/{name}`` detail view / UI would use). ``None`` when the
    pack has no valid manifest."""
    contents = preview_pack(pack_dir)
    if contents is None:
        return None
    return {
        "name": contents.name,
        "skills": [{"name": c.name, "rel": c.rel} for c in contents.skills],
        "agents": [{"name": c.name, "rel": c.rel} for c in contents.agents],
        "has_hooks": contents.has_hooks,
        "has_mcp": contents.has_mcp,
        "counts": {"skills": len(contents.skills), "agents": len(contents.agents)},
    }


__all__ = [
    "PackEntry",
    "PackComponent",
    "PackContents",
    "scan_packs",
    "describe_scan",
    "preview_pack",
    "describe_pack_contents",
]
