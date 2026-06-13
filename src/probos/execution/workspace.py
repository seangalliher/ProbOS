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
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories whose *contents* are noise for the Captain (the venv has thousands
# of files; caches are derived). They appear as a single opaque entry, never
# recursed into.
_OPAQUE_DIRS = {".venv", "__pycache__", ".git", "node_modules"}

_SANITIZE_RE = re.compile(r"[^a-z0-9_-]+")


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
        entry but are never recursed into. Honest-degrade: returns ``[]`` when
        the folder is absent or unreadable (never raises).
        """
        base = self.resolve(owner_key)
        if not base.is_dir():
            return []
        out: list[WorkspaceFile] = []
        try:
            for dirpath, dirnames, filenames in os.walk(base):
                rel_dir = Path(dirpath).relative_to(base)
                # Record opaque dirs as a single entry, then stop descending.
                kept_dirs = []
                for d in sorted(dirnames):
                    entry_rel = (rel_dir / d).as_posix()
                    full = Path(dirpath) / d
                    try:
                        st = full.stat()
                        out.append(WorkspaceFile(entry_rel, True, _dir_size(full) if d in _OPAQUE_DIRS else 0, st.st_mtime))
                    except OSError:
                        continue
                    if d not in _OPAQUE_DIRS:
                        kept_dirs.append(d)
                    if len(out) >= limit:
                        return out[:limit]
                dirnames[:] = kept_dirs  # prune opaque dirs from the walk
                for f in sorted(filenames):
                    entry_rel = (rel_dir / f).as_posix()
                    full = Path(dirpath) / f
                    try:
                        st = full.stat()
                    except OSError:
                        continue
                    out.append(WorkspaceFile(entry_rel, False, st.st_size, st.st_mtime))
                    if len(out) >= limit:
                        return out[:limit]
        except OSError:
            logger.debug("AD-997: list_files failed for %s", owner_key, exc_info=True)
            return out
        return out

    def total_bytes(self, owner_key: str) -> int:
        """Total size of ``owner_key``'s folder (incl. venv). 0 if absent."""
        base = self.resolve(owner_key)
        return _dir_size(base) if base.is_dir() else 0


def _dir_size(path: Path) -> int:
    """Recursive byte size of a directory tree; best-effort (skips unreadable)."""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += (Path(dirpath) / f).stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total
