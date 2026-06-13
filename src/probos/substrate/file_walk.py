"""AD-990: gitignore-aware file traversal (absorbs ripgrep's automatic filtering).

ripgrep's headline behavior is *automatic filtering*: it does not search files
ignored by ``.gitignore`` / ``.ignore``, hidden files, or binary files. ProbOS's
``FileSearchAgent`` previously used a raw ``Path.rglob`` that descended ``.venv/``,
``node_modules/``, ``__pycache__/``, ``data/`` and so on — returning noise. This
module absorbs the *pattern* (pure Python, zero new dependencies) so file and
content search both skip the junk by default.

Scope note: ``IgnoreSpec`` implements a **faithful common subset** of gitignore
semantics — comments, blank lines, ``!`` negation, trailing-``/`` directory-only,
leading-``/`` root-anchoring, and ``*`` / ``?`` / ``**`` globbing via
:func:`fnmatch.translate`. Exotic gitignore corner cases (e.g. complex
re-inclusion of files under an ignored directory) are intentionally out of scope;
a full engine (``pathspec`` / ``re2``) is a forward marker, not a hard dependency.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

__all__ = [
    "IgnoreSpec",
    "load_ignore_spec",
    "is_binary",
    "iter_files",
    "DEFAULT_IGNORE_DIRS",
    "DEFAULT_MAX_FILES",
]

# Backstop ignore set — pruned even when there is no .gitignore. These directories
# are never useful to search and are huge (the .venv / node_modules problem).
DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", "node_modules",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".cache",
    "dist", "build", "site", ".tox", ".eggs",
    ".idea", ".vscode",
    "data",
})

DEFAULT_MAX_FILES: int = 20000
_SNIFF_BYTES: int = 8192


@dataclass
class _Rule:
    regex: re.Pattern[str]
    negated: bool
    dir_only: bool


@dataclass
class IgnoreSpec:
    """A parsed set of gitignore-style rules. ``matches`` applies them in order
    with last-match-wins semantics (so a later ``!pattern`` re-includes)."""

    rules: list[_Rule] = field(default_factory=list)

    @classmethod
    def from_lines(cls, lines: list[str]) -> "IgnoreSpec":
        rules: list[_Rule] = []
        for raw in lines:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            dir_only = line.endswith("/")
            if dir_only:
                line = line[:-1]
            anchored = line.startswith("/")
            if anchored:
                line = line[1:]
            if not line:
                continue
            rules.append(_Rule(_compile_glob(line, anchored), negated, dir_only))
        return cls(rules)

    def matches(self, rel_posix: str, *, is_dir: bool) -> bool:
        """True if ``rel_posix`` (a forward-slash relative path) is ignored."""
        ignored = False
        for rule in self.rules:
            if rule.dir_only and not is_dir:
                continue
            if rule.regex.match(rel_posix):
                ignored = not rule.negated
        return ignored


def _compile_glob(pattern: str, anchored: bool) -> re.Pattern[str]:
    """Translate a gitignore glob into a regex. Anchored patterns match from the
    repo root; unanchored patterns match the path OR any of its trailing
    components (``*.log`` matches ``a/b/c.log``)."""
    # fnmatch.translate gives a full-string regex with a trailing anchor; strip it
    # so we can append our own suffix that also matches sub-paths under a dir.
    body = fnmatch.translate(pattern)
    # fnmatch.translate -> r'(?s:....)\Z' ; pull out the inner expression.
    m = re.match(r"\(\?s:(.*)\)\\Z", body)
    inner = m.group(1) if m else body
    if anchored:
        full = rf"(?s:{inner})(?:/.*)?\Z"
    else:
        # match either the whole path or any trailing path segment(s)
        full = rf"(?s:(?:.*/)?{inner})(?:/.*)?\Z"
    return re.compile(full)


def load_ignore_spec(root: Path) -> IgnoreSpec:
    """Load ``root/.gitignore`` + ``root/.ignore`` into one spec. Tier-2: missing
    or unreadable files contribute nothing (never raises)."""
    lines: list[str] = []
    for name in (".gitignore", ".ignore"):
        p = root / name
        try:
            if p.is_file():
                lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
    return IgnoreSpec.from_lines(lines)


def is_binary(path: Path, *, sniff_bytes: int = _SNIFF_BYTES) -> bool:
    """Heuristic: a file is binary if its first ``sniff_bytes`` contain a NUL.
    Tier-2: an unreadable file is treated as binary (skip it)."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(sniff_bytes)
    except OSError:
        return True
    return b"\x00" in chunk


def iter_files(
    root: Path,
    *,
    ignore_spec: IgnoreSpec | None = None,
    include_hidden: bool = False,
    skip_binary: bool = True,
    respect_default_ignores: bool = True,
    max_files: int = DEFAULT_MAX_FILES,
) -> Iterator[Path]:
    """Yield files under ``root``, pruning ignored / hidden / binary entries.

    os.walk-based with in-place directory pruning (so ignored dirs are never
    descended). Deterministic (sorted). Bounded by ``max_files``. Tier-2:
    per-entry errors are skipped, never raised.
    """
    root = Path(root)
    if not root.is_dir():
        return
    spec = ignore_spec if ignore_spec is not None else load_ignore_spec(root)
    yielded = 0
    for dirpath, dirnames, filenames in os.walk(root):
        cur = Path(dirpath)
        # Prune directories in place (don't descend).
        kept: list[str] = []
        for d in sorted(dirnames):
            if not include_hidden and d.startswith("."):
                continue
            if respect_default_ignores and d in DEFAULT_IGNORE_DIRS:
                continue
            rel_dir = (cur / d).relative_to(root).as_posix()
            if spec.matches(rel_dir, is_dir=True):
                continue
            kept.append(d)
        dirnames[:] = kept

        for f in sorted(filenames):
            if not include_hidden and f.startswith("."):
                continue
            fp = cur / f
            rel = fp.relative_to(root).as_posix()
            if spec.matches(rel, is_dir=False):
                continue
            if skip_binary and is_binary(fp):
                continue
            yield fp
            yielded += 1
            if yielded >= max_files:
                return
