"""BF-894 (#1547): the builder's write-path boundary.

``builder_write_refusal`` is the one check for every path ``execute_approved_build``
writes on a model's behalf: the approved writes and the test-fix repair loop.

Lexical rules apply on every platform. Each path component is put in the form
Windows and macOS compare names in (HFS+ ignorable code points dropped, trailing
dots and spaces trimmed, upper-cased), so ``.GiT``, ``.git.``, ``.git `` and a
``.git`` carrying a zero-width joiner all equal ``.GIT``. A ``:`` (an NTFS stream or
a drive-relative form) and an 8.3 short-name form (``GIT~1``) are refused outright.
The rules follow git's own ``is_ntfs_dotgit`` and ``is_hfs_dotgit`` (CVE-2014-9390).
A case variant is refused on case-sensitive filesystems too: no builder write needs
one, and the rule is then the same everywhere.

The identity check applies when ``work_dir`` is given and ``<work_dir>/.git`` exists:
every existing prefix of the target is compared with that entry by ``os.stat``
identity, so any name the filesystem resolves to it (a form the lexical rules do not
name, or a hard link) is refused. A prefix that cannot be examined is refused.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Allowed top-level directories for builder file operations (moved from builder.py).
ALLOWED_PATH_PREFIXES = (
    "src/",
    "tests/",
    "config/",
    "docs/",
    "prompts/",
)

# Paths that must never be written by the builder; compared in canonical form.
FORBIDDEN_PATHS = (
    ".git/",
    ".env",
    "pyproject.toml",
    ".github/",
)

# Code points HFS+ ignores in names (git utf8.c, next_hfs_char).
_HFS_IGNORABLE = re.compile("[\u200c-\u200f\u202a-\u202e\u206a-\u206f\ufeff]")
# An 8.3 short-name form: GIT~1, GITHUB~1, PYPROJ~1.TOM, or a hashed GI7EBA~1.
_SHORT_NAME = re.compile(r"~[0-9]")


def _canonical(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()


def builder_write_refusal(
    path_str: str, work_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return why the builder must not write *path_str*, or None if it may.

    *path_str* is relative to *work_dir*. Without *work_dir* only the lexical rules run.
    """
    normalized = path_str.replace("\\", "/")
    if not normalized.strip():
        return "Empty path blocked"
    if ".." in normalized:
        return f"Path traversal blocked: {path_str}"
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return f"Absolute path blocked: {path_str}"

    parts = normalized.split("/")
    for part in parts:
        if ":" in part:
            return f"Forbidden path (stream or drive form): {path_str}"
        if _SHORT_NAME.search(part):
            return f"Forbidden path (8.3 short-name form): {path_str}"
        if _canonical(part) == ".GIT":
            return f"Forbidden path (.git alias): {path_str}"

    canonical = "/".join(_canonical(part) for part in parts)
    for forbidden in FORBIDDEN_PATHS:
        folded = forbidden.upper()
        if canonical.startswith(folded) or canonical == folded.rstrip("/"):
            return f"Forbidden path: {path_str}"

    if normalized.startswith("-"):
        return f"Option-shaped path blocked: {path_str}"

    if "/" in normalized and not any(normalized.startswith(p) for p in ALLOWED_PATH_PREFIXES):
        allowed = ", ".join(ALLOWED_PATH_PREFIXES)
        return f"Path outside allowed directories: {path_str} (allowed: {allowed})"

    if work_dir is None:
        return None
    return _git_identity_refusal(parts, path_str, Path(work_dir))


def _git_identity_refusal(parts: list[str], path_str: str, root: Path) -> str | None:
    """Refuse a target any existing prefix of which is the work tree's ``.git`` entry."""
    try:
        git_entry = os.stat(root / ".git")
    except (FileNotFoundError, NotADirectoryError):
        return None  # no .git entry: nothing to alias; the lexical rules already ran
    except OSError as exc:
        return f"Cannot verify write path against .git ({type(exc).__name__}): {path_str}"
    prefix = root
    for part in parts:
        prefix = prefix / part
        try:
            current = os.stat(prefix)
        except (FileNotFoundError, NotADirectoryError):
            return None  # this prefix is not on disk, so nothing under it is either
        except OSError as exc:
            return f"Cannot verify write path ({type(exc).__name__}): {path_str}"
        if os.path.samestat(current, git_entry):
            return f"Forbidden path (same file as .git): {path_str}"
    return None
