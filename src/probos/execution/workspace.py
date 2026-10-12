"""AD-997: per-agent working folders for governed code execution.

The Captain's model: each crew member that runs code should have its own
**persistent working folder** (not a shared dir, not an ephemeral scratch that
vanishes after each run) — so the work products (scripts, generated files, the
installed venv) survive and can be *seen* from the agent's profile card.

``WorkspaceManager`` is the single source of truth for "where does agent *X*
work". It resolves a stable per-owner folder under a configurable root, lists
its contents for the HXI, and is honest-degrading (never raises). It is keyed
by an *owner* string (a crew agent's callsign / type / id), so:

* the ``CodeRunnerAgent`` writes into the requesting owner's folder, and
* the ``GET /api/agent/{id}/workspace`` endpoint resolves the *same* folder for
  that agent — the write side and the view side agree by construction.

Tier 1 isolation note (AD-993): a per-owner folder is *organizational*
attribution and confinement-by-convention, not a kernel-enforced boundary —
a determined payload at Tier 1 can still reach outside its folder. The real
controls remain consensus + default-OFF; the folder gives the Captain
visibility and keeps one agent's work from clobbering another's by default.

AD-1240: the ``.tool-results`` directory inside an owner folder is a
runtime-reserved namespace (``workspace_results``), not a work product.
``resolve_file`` refuses it and every alias into it before anything is
created, and the inspection walks (``list_files`` / ``total_bytes``) never
list, enter or size it. A walk resolves a directory or a link once and a plain
file never (its own lstat is all there is to know); a link that leads outside
the owner folder or into the namespace is dropped, and any other link is listed
once and never entered (a directory link is not sized either: its target is
walked once, as itself); a directory is entered only while it is still the
object that was checked, seen without following a link. A hard link created
by a process outside ProbOS is indistinguishable from an ordinary file and is
listed and served as one. Publishing, reading and reaping the namespace's
contents live in ``workspace_result_store``, which depends on this module and
not the reverse.
"""

from __future__ import annotations

import logging
import operator
import os
import re
import stat
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from probos.execution.workspace_results import RESULT_DIRECTORY, is_workspace_result_path
from probos.security.file_access import is_reparse_point

logger = logging.getLogger(__name__)

# Directories whose *contents* are noise for the Captain (the venv has thousands
# of files; caches are derived). They appear as a single opaque entry, never
# recursed into.
_OPAQUE_DIRS = {".venv", "__pycache__", ".git", "node_modules"}

_SANITIZE_RE = re.compile(r"[^a-z0-9_-]+")

# AD-1021b: hard cap on a single governed workspace write (and the size a read
# will surface). 1 MiB — generous for source/text, bounded so the API never
# loads an arbitrary blob into memory or broadcasts a megabyte write intent.
_MAX_WRITE_BYTES = 1_048_576


def _platform_data_dir() -> Path:
    """Platform data dir — an inlined mirror of ``runtime._platform_data_dir``
    / ``__main__._default_data_dir`` so this leaf utility does NOT import the
    heavy ``probos.runtime`` module (which pulls optional deps like ``keyring``
    and fails to import without them). ``PROBOS_DATA_DIR`` overrides.

    Keep in sync with ``runtime._platform_data_dir`` (stable platform switch).
    """
    override = os.environ.get("PROBOS_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local" / "ProbOS"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "ProbOS"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) / "ProbOS" if xdg else Path.home() / ".local" / "share" / "ProbOS"
    return base / "data"


def _resolve_workspace_root(configured: str | os.PathLike[str]) -> Path:
    """Resolve the configured workspace root to an absolute path.

    Absolute paths are used as-is (tests, explicit operator paths). A relative
    path (the config default ``data/execution/workspaces``) is rooted under the
    platform data dir, stripping a leading ``data/`` since that dir already ends
    in ``/data`` — mirrors ``_resolve_attachments_dir`` (AD-720) so the working
    folders live alongside all other ProbOS runtime data (Windows
    ``%LOCALAPPDATA%/ProbOS/data``, XDG on Linux), **not** split-brained relative
    to the process cwd — the exact hazard ``_platform_data_dir`` exists to prevent.
    """
    p = Path(configured)
    if p.is_absolute():
        return p
    parts = p.parts
    if parts and parts[0] == "data":
        parts = parts[1:]
    base = _platform_data_dir()
    return base.joinpath(*parts) if parts else base


@dataclass(frozen=True)
class WorkspaceFile:
    """One entry in a working folder, for the HXI file list."""

    name: str          # path relative to the workspace root, '/'-joined
    is_dir: bool
    size_bytes: int
    modified: float    # POSIX mtime


# AD-1240: the reserved result namespace, as ordinary operations must treat it.
# What separates one directory from another that now sits at the same path.
_Identity = tuple[int, int]


def _identity(info: os.stat_result) -> _Identity:
    return (info.st_dev, info.st_ino)


def _resolve_once(path: Path) -> Path | None:
    """One resolution of ``path``; ``None`` (a refusal, never an exception) if it fails."""
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


class _Resolutions:
    """One call's resolutions: a path is resolved at most once, failures included.

    ``resolve_file`` checks the exact values held here and returns one of them,
    so what it authorizes is what it hands back.
    """

    def __init__(self) -> None:
        self._seen: dict[Path, Path | None] = {}

    def of(self, path: Path) -> Path | None:
        if path not in self._seen:
            self._seen[path] = _resolve_once(path)
        return self._seen[path]


def _admit_owner(base: Path) -> tuple[Path, _Identity] | None:
    """The single owner/root decision of an inspection walk.

    ``base`` and each of its ancestors are resolved once. The folder is admitted
    only when none of those resolutions is, or leads into, the reserved
    namespace and the resolved folder is a directory. It is returned with its
    identity so the walk can tell when what it enters is no longer what was
    admitted. Nothing is remembered between walks: a folder swapped for an
    alias gets a fresh decision.
    """
    if is_workspace_result_path(base):
        return None
    top = _resolve_once(base)
    if top is None or is_workspace_result_path(top):
        return None
    for ancestor in base.parents:
        resolved = _resolve_once(ancestor)
        if resolved is None or is_workspace_result_path(resolved):
            return None
    try:
        info = top.stat()
    except OSError:
        return None
    return (top, _identity(info)) if stat.S_ISDIR(info.st_mode) else None


class _Child(NamedTuple):
    """One entry of a scanned directory: classified, not yet checked."""

    name: str
    path: str
    info: os.stat_result   # the scan entry's lstat; a real directory's is re-read, so it carries its identity
    is_dir: bool           # a directory, or a link to one
    link: bool             # a symlink, a junction or any other reparse point


@dataclass(frozen=True)
class _Entry:
    """One checked entry of an inspection walk."""

    name: str              # path relative to the walked folder, '/'-joined
    is_dir: bool
    opaque: bool           # a real directory listed as one entry, sized and never recursed into; a link never is
    info: os.stat_result   # of the entry itself, or of a link's checked target
    checked: Path | None   # the exact resolution that was checked; None for a plain file


def _is_checked_directory(directory: Path, expected: _Identity) -> bool:
    """Whether ``directory`` is still the real directory that was checked, seen without following a link.

    A link, junction or other reparse point is refused even when it leads to
    the very object that was checked: that object may since have been moved
    into the reserved namespace, and following the link would enter it.
    """
    info = os.lstat(directory)  # no-follow: os.stat would report the identity of what an alias leads to
    return stat.S_ISDIR(info.st_mode) and not is_reparse_point(info) and _identity(info) == expected


def _listing(directory: Path, expected: _Identity) -> list[os.DirEntry[str]] | None:
    """The entries of ``directory``, or ``None`` if it is not the object that was checked.

    It is observed before the listing and again after it, each time without
    following a link, so a listing taken from a replaced directory, or through
    an alias that replaced it, is never used.
    """
    try:
        if not _is_checked_directory(directory, expected):
            return None
        with os.scandir(directory) as scanned:
            entries = list(scanned)
        return entries if _is_checked_directory(directory, expected) else None
    except OSError:
        return None


def _classify(entry: os.DirEntry[str], info: os.stat_result) -> tuple[bool, bool]:
    """``(is_dir, link)`` of a scan entry: its link flag, and the kind of anything that is not a link, from ``info``.

    A link is a symlink, a junction or any other reparse point. ``info`` is a
    no-follow stat, so for a link the kind of its target is the scan entry's own
    answer (``entry.is_dir()``, which may have been cached when the directory was
    scanned); for anything else the stat itself says whether it is a directory.
    """
    link = is_reparse_point(info)
    return (entry.is_dir() if link else stat.S_ISDIR(info.st_mode)), link


def _children(entries: list[os.DirEntry[str]]) -> tuple[list[_Child], list[_Child]]:
    """Classify scan entries as ``(directories and links to them, everything else)``, each sorted by name.

    An entry named for the reserved namespace is dropped here, whatever it is
    and in whatever case it is spelt. A real directory is observed a second
    time, for its identity, and classified again from that observation: a
    child's link flag and, unless it is a link, its kind always belong to the
    stat it carries.
    """
    dirs: list[_Child] = []
    others: list[_Child] = []
    for entry in entries:
        if entry.name.casefold() == RESULT_DIRECTORY:  # the reserved name, in any case
            continue
        try:
            info = entry.stat(follow_symlinks=False)
            is_dir, link = _classify(entry, info)
            if is_dir and not link:
                info = os.lstat(entry.path)  # a scan entry's stat carries no identity on Windows
                is_dir, link = _classify(entry, info)  # a directory replaced since the scan is what is there now
        except OSError:
            continue
        (dirs if is_dir else others).append(_Child(entry.name, entry.path, info, is_dir, link))
    return sorted(dirs, key=operator.attrgetter("name")), sorted(others, key=operator.attrgetter("name"))


def _checked_entry(child: _Child, base: Path, prefix: str) -> _Entry | None:
    """Check one scanned child; ``None`` if it must not be listed, sized or entered.

    A plain file is never resolved: its own lstat says all there is to know. A
    directory or a link is resolved once and kept only if that exact resolution
    lies under ``base`` and outside the reserved namespace. A file link is then
    sized from its checked target; a directory link is listed once with size 0
    and is neither entered nor sized, because its target is walked once, as itself.
    """
    name = prefix + child.name
    if not child.link and not child.is_dir:
        return _Entry(name, False, False, child.info, None)
    checked = _resolve_once(Path(child.path))
    if checked is None or is_workspace_result_path(checked) or not checked.is_relative_to(base):
        return None
    info = child.info
    if child.link:
        try:
            info = checked.stat()
        except OSError:
            return None
    opaque = child.is_dir and not child.link and child.name in _OPAQUE_DIRS  # a link's target is never sized
    return _Entry(name, child.is_dir, opaque, info, checked)


def _ordinary_entries(
    top: Path, identity: _Identity, *, base: Path, descend_opaque: bool,
) -> Iterator[_Entry]:
    """Ordinary entries below an admitted ``top``, lazily, in listing order.

    A folder's directories (and links to them) come first, then its other
    entries, each sorted; the walk then enters the kept real directories in
    turn. Only real directories are entered, each only while it is still the
    object whose lstat was taken from its scan entry. ``base`` is the owner's
    resolved folder that every resolved directory and link must lie under.
    """
    pending: list[tuple[Path, str, _Identity]] = [(top, "", identity)]
    while pending:
        directory, prefix, expected = pending.pop()
        entries = _listing(directory, expected)
        if entries is None:
            continue
        dirs, others = _children(entries)
        entered: list[tuple[Path, str, _Identity]] = []
        for child in (*dirs, *others):
            entry = _checked_entry(child, base, prefix)
            if entry is None:
                continue
            yield entry
            enter = entry.is_dir and not child.link and (descend_opaque or not entry.opaque)
            if enter and entry.checked is not None:
                entered.append((entry.checked, f"{entry.name}/", _identity(child.info)))
        pending.extend(reversed(entered))


class WorkspaceManager:
    """Resolve + inspect per-owner working folders under a single root."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = _resolve_workspace_root(root)

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # keying
    # ------------------------------------------------------------------

    @staticmethod
    def sanitize(key: str) -> str:
        """Reduce an owner key to a safe, stable folder name.

        Lowercase, keep ``[a-z0-9_-]``, collapse the rest to ``_``. Falls back
        to ``"shared"`` for an empty/degenerate key so a workspace always
        resolves to *something* under the root (never the root itself, never a
        traversal). Length-bounded.
        """
        s = _SANITIZE_RE.sub("_", str(key).strip().lower()).strip("_")
        return s[:64] if s else "shared"

    def key_for_agent(self, agent: Any) -> str:
        """Stable folder key for an agent object: callsign → type → id.

        The same agent always resolves to the same key, so the write side
        (CodeRunnerAgent acting for an owner) and the read side (the profile
        card / API) agree.
        """
        for attr in ("callsign", "agent_type", "id"):
            val = getattr(agent, attr, "") or ""
            if val:
                return self.sanitize(val)
        return "shared"

    # ------------------------------------------------------------------
    # resolution
    # ------------------------------------------------------------------

    def resolve(self, owner_key: str, *, create: bool = False) -> Path:
        """Absolute path to ``owner_key``'s working folder under the root.

        Sanitized so the result is always a direct child of the root (no
        traversal). Creates the folder (and the root) when ``create=True``.
        """
        path = self._root / self.sanitize(owner_key)
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_file(
        self, owner_key: str, rel_path: str, *, create_parents: bool = False
    ) -> Path | None:
        """Confine ``rel_path`` to ``owner_key``'s folder; ``None`` if it escapes.

        AD-1021b: the path-safety primitive for the governed Monaco write-through.
        Resolves ``<owner-folder>/<rel_path>`` and returns the absolute target
        ONLY when it stays strictly inside the *resolved* owner folder — the
        symlink-escape-safe ``resolve() + is_relative_to`` confinement used by the
        attachment + records stores. Returns ``None`` (never raises, never a path
        outside the folder) for an empty / absolute / NUL-bearing /
        traversal-escaping ``rel_path``, or for the folder itself (not a file).
        AD-1240: the reserved result namespace is refused too, whoever owns it
        and whatever its expiry: a lexical component naming it, any lexical
        prefix or the owner folder that resolves into it (including an alias
        that enters it and a later ``..`` that leaves it), and the final
        resolution. The folder and the target are each resolved ONCE, those
        exact values are what is checked, and the checked target is what is
        returned; refusal happens before any parent is created.
        When ``create_parents`` is set the parent directories of the confined
        target are created best-effort so a first write under a new sub-path can
        succeed (a failed mkdir is logged and left for the write to surface — it
        does not turn a safe path unsafe).
        """
        if not rel_path or "\x00" in rel_path:
            return None
        lexical_base = self.resolve(owner_key)
        candidate = lexical_base / rel_path
        if is_workspace_result_path(candidate):
            return None
        resolutions = _Resolutions()
        base = resolutions.of(lexical_base)
        resolved = resolutions.of(candidate)
        if base is None or resolved is None:
            return None
        if resolved == base or not resolved.is_relative_to(base):
            return None
        if is_workspace_result_path(base) or is_workspace_result_path(resolved):
            return None
        for prefix in (*lexical_base.parents, *candidate.parents):
            aliased = resolutions.of(prefix)
            if aliased is None or is_workspace_result_path(aliased):
                return None
        if create_parents:
            try:
                resolved.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.debug(
                    "AD-1021b: parent mkdir failed for %s (write will surface it)",
                    resolved, exc_info=True,
                )
        return resolved

    def venv_dir(self, owner_key: str) -> Path:
        """The reusable per-owner virtualenv path (``<workspace>/.venv``)."""
        return self.resolve(owner_key) / ".venv"

    # ------------------------------------------------------------------
    # inspection (HXI)
    # ------------------------------------------------------------------

    def list_files(self, owner_key: str, *, limit: int = 200) -> list[WorkspaceFile]:
        """List the work products in ``owner_key``'s folder for the HXI.

        Deterministic (sorted), bounded by ``limit``, and *shallow into noise*:
        ``.venv`` / ``__pycache__`` / ``.git`` appear as a single directory
        entry but are never recursed into. AD-1240: the reserved result
        namespace, and any alias into it, is omitted from entries and sizes, and
        so is a link that leads outside the owner folder; links are listed but
        never entered. The folder is resolved once, a plain file never, and a
        directory or link once. Honest-degrade: returns ``[]`` when the folder
        is absent, reserved or unreadable (never raises).
        """
        owner = _admit_owner(self.resolve(owner_key))
        if owner is None:
            return []
        top, identity = owner
        out: list[WorkspaceFile] = []
        try:
            for entry in _ordinary_entries(top, identity, base=top, descend_opaque=False):
                size = entry.info.st_size
                if entry.is_dir:
                    size = _dir_size(entry.checked, _identity(entry.info), base=top) if entry.opaque else 0
                out.append(WorkspaceFile(entry.name, entry.is_dir, size, entry.info.st_mtime))
                if len(out) >= limit:
                    return out[:limit]
        except OSError:
            logger.debug("AD-997: list_files failed for %s", owner_key, exc_info=True)
            return out
        return out

    def total_bytes(self, owner_key: str) -> int:
        """Total ordinary size of ``owner_key``'s folder (incl. venv, excluding the result namespace). 0 if absent."""
        owner = _admit_owner(self.resolve(owner_key))
        if owner is None:
            return 0
        top, identity = owner
        return _dir_size(top, identity, base=top)


def _dir_size(top: Path, identity: _Identity, *, base: Path) -> int:
    """Recursive byte size of an admitted directory tree; best-effort (skips unreadable)."""
    total = 0
    try:
        for entry in _ordinary_entries(top, identity, base=base, descend_opaque=True):
            if not entry.is_dir:
                total += entry.info.st_size
    except OSError:
        return total
    return total
