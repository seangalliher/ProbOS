"""BF-894 (#1547): the builder's write-path boundary.

``builder_write_refusal`` is the one check for every path ``execute_approved_build``
writes on a model's behalf: the approved writes and the test-fix repair loop.

BF-898 (#1563): the repair loop's blocks are model-authored and unreviewed, and the
tests it reruns decide the commit, so the loop also applies ``fix_loop_write_refusal``:
a block's path must be under ``src/probos/``, must not name a test, a ``conftest.py``,
pytest configuration or the build's own grader (``FIX_LOOP_PROTECTED_PATHS``), and must
not contain a control or line-break character. The rule judges the path as written, so
it is a write boundary on the repair channel, not an immutable grader: it does not follow
a hard link, junction or symlink to a protected file, and it does not limit what repaired
source does when the tests import it (DECISIONS.md, BF-898). The rule's examples
(``FIX_LOOP_SELF_TEST``) are judged by ``fix_loop_self_test``.

Lexical rules apply on every platform. Each path component is put in the form
Windows and macOS compare names in (HFS+ ignorable code points dropped, trailing
dots and spaces trimmed, upper-cased), so ``.GiT``, ``.git.``, ``.git `` and a
``.git`` carrying a zero-width joiner all equal ``.GIT``. A ``:`` (an NTFS stream or
a drive-relative form), an 8.3 short-name form (``GIT~1``) and a Windows device name
(``NUL``, ``con.py``: a write to one succeeds and the file cannot be removed) are refused
outright.
The rules follow git's own ``is_ntfs_dotgit`` and ``is_hfs_dotgit`` (CVE-2014-9390).
A case variant is refused on case-sensitive filesystems too: no builder write needs
one, and the rule is then the same everywhere.

The identity check applies when ``work_dir`` is given and ``<work_dir>/.git`` exists:
every existing prefix of the target is compared with that entry by ``os.stat``
identity, so any name the filesystem resolves to it (a form the lexical rules do not
name, or a hard link) is refused. A prefix that cannot be examined is refused.

AD-1344 (#1596): ``constitution_write_refusal`` refuses a write to the Federation
Constitution (``standing_orders.CONSTITUTION_RELATIVE_PATH``); its docstring lists the
cases. ``builder_write_refusal`` calls it, and so do the writers listed in
``tests/test_ad1344_constitution_write_refusal.py`` (``_EXPECTED_CALLERS``).
"""

from __future__ import annotations

import os
import posixpath
import re
import unicodedata
from pathlib import Path

from probos.cognitive.standing_orders import CONSTITUTION_RELATIVE_PATH, constitution_path

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
# A Windows device name, with or without an extension: CON, PRN, AUX, NUL, COM0-9, LPT0-9
# (and the superscript digits Windows also reserves). Writing NUL succeeds and cannot be unlinked.
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9\u00b9\u00b2\u00b3]|LPT[0-9\u00b9\u00b2\u00b3]) *(\..*)?$")


def _canonical(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()


# AD-1344 (#1596): the constitution's path components, as written and in canonical form.
_CONSTITUTION_RELATIVE_PARTS = tuple(CONSTITUTION_RELATIVE_PATH.split("/"))
_CONSTITUTION_PARTS = tuple(_canonical(part) for part in _CONSTITUTION_RELATIVE_PARTS)
# A leading drive (``C:``), which a drive-relative path carries before its first component.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_NOT_A_STR = "Constitution write refused (AD-1344): the path is not an exact str, so it is not checked"


def _exception_name(exc: BaseException) -> str:
    """The class name of *exc*, read through ``type``'s own descriptor, if it is an exact-``str`` identifier.

    ``Exception`` under another metaclass (nothing of the class is read) or for any other name.
    """
    cls = type(exc)
    if type(cls) is not type:
        return "Exception"
    name = cls.__name__
    return name if type(name) is str and name.isidentifier() else "Exception"


def _constitution_component(name: str, expected: str) -> bool:
    """Whether canonical *name* is *expected*, or an 8.3 short form with its first two characters."""
    return name == expected or (_SHORT_NAME.search(name) is not None and name[:2] == expected[:2])


def _names_constitution(path_text: str) -> bool:
    """AD-1344: whether *path_text* (an exact ``str``) ends in the constitution's three components.

    Separators become ``/``, a leading drive is dropped and ``..`` is collapsed; each
    component loses any ``:`` suffix (an NTFS stream) and is put in canonical form;
    components then empty (``.``, ``...``) are dropped. What lies above the three is not
    compared, so a copy in another tree matches too.
    """
    unified = _DRIVE_PREFIX.sub("", path_text.replace("\\", "/"), count=1)
    collapsed = posixpath.normpath(unified)
    names = [_canonical(part.split(":", 1)[0]) for part in collapsed.split("/")]
    names = [name for name in names if name]
    tail = names[-len(_CONSTITUTION_PARTS):]
    return len(tail) == len(_CONSTITUTION_PARTS) and all(
        _constitution_component(name, expected) for name, expected in zip(tail, _CONSTITUTION_PARTS)
    )


def _constitution_refusal(path_text: str) -> str:
    return (
        f"Constitution write refused (AD-1344): {path_text!r} is the Federation Constitution "
        f"({CONSTITUTION_RELATIVE_PATH}), which the Captain amends through ordinary "
        "development, not an agent"
    )


def _constitution_unverifiable(path_text: str, stage: str, exc: BaseException) -> str:
    return (
        f"Constitution write refused (AD-1344): cannot verify that {path_text!r} is not the "
        f"Federation Constitution ({stage}: {_exception_name(exc)})"
    )


def _constitution_lexical_refusal(path_text: object) -> str | None:
    """AD-1344: the refusal for a value that is not an exact ``str`` or that names the constitution as written.

    The type is compared first, so no method of a ``str`` subclass or other object runs.
    """
    if type(path_text) is not str:
        return _NOT_A_STR
    if _names_constitution(path_text):
        return _constitution_refusal(path_text)
    return None


def constitution_write_refusal(
    path: str, root: str | os.PathLike[str] | None = None,
) -> str | None:
    """AD-1344 (#1596): why an agent-reachable writer must not write *path*, or None if it may.

    *path* is the path as the writer received it, relative to *root* (the writer's base
    directory) or absolute; a relative *path* with no *root* is taken relative to the
    working directory. Refused, with a one-line reason naming AD-1344: a value that is
    not an exact ``str``; a path whose last three components name the constitution as
    written or once resolved; an existing file with the ``os.stat`` identity of the
    constitution under *root* or of ``standing_orders.constitution_path()``; an
    examination by ``os.stat`` that raises ``OSError`` or ``ValueError`` other than
    ``FileNotFoundError`` or ``NotADirectoryError``; and a resolution that raises
    ``OSError``, ``RuntimeError`` or ``ValueError``. Any other exception propagates.
    """
    lexical = _constitution_lexical_refusal(path)
    if lexical is not None:
        return lexical
    target = Path(path)
    if root is not None and not target.is_absolute():
        target = Path(root) / target
    try:
        resolved = target.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return _constitution_unverifiable(path, "resolved", exc)
    if _names_constitution(str(resolved)):
        return _constitution_refusal(path)
    candidates = [constitution_path()]
    if root is not None:
        candidates.append(Path(root).joinpath(*_CONSTITUTION_RELATIVE_PARTS))
    for candidate in candidates:
        try:
            constitution = os.stat(candidate)
        except (FileNotFoundError, NotADirectoryError):
            continue  # no constitution there: nothing to alias
        except (OSError, ValueError) as exc:
            return _constitution_unverifiable(path, "constitution", exc)
        try:
            current = os.stat(target)
        except (FileNotFoundError, NotADirectoryError):
            return None  # not on disk, so not a second name of an existing file
        except (OSError, ValueError) as exc:
            return _constitution_unverifiable(path, "target", exc)
        if os.path.samestat(current, constitution):
            return _constitution_refusal(path)
    return None


def builder_write_refusal(
    path_str: str, work_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return why the builder must not write *path_str*, or None if it may.

    *path_str* is relative to *work_dir*. Without *work_dir* only the lexical rules run.
    AD-1344: after the empty-path check, ``_constitution_lexical_refusal`` judges *path_str*
    and its reason, if any, is returned; with *work_dir*, ``constitution_write_refusal``
    runs after the ``.git`` identity check.
    """
    normalized = path_str.replace("\\", "/")
    if not normalized.strip():
        return "Empty path blocked"
    constitution = _constitution_lexical_refusal(path_str)  # AD-1344: ahead of the rules below, so its reason is given
    if constitution is not None:
        return constitution
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
        if _RESERVED.match(_canonical(part)):
            return f"Forbidden path (Windows device name): {path_str}"
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
    git_refusal = _git_identity_refusal(parts, path_str, Path(work_dir))
    if git_refusal is not None:
        return git_refusal
    return constitution_write_refusal(path_str, work_dir)  # AD-1344: after the .git identity check


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


# BF-898 (#1563): the unreviewed test-fix loop may change source only. A repair that
# changed a test, a conftest.py, pytest configuration or the build's own grader would
# make its own rerun pass; a failure caused by a wrong test goes back to the Captain.
FIX_LOOP_WRITABLE_ROOT = ("src", "probos")

# Source the fix loop must not change: the fix loop, test runner and commit gate, the
# write boundary, the AD-341 reviewer, the visiting session's permission policy, the test
# environment, the sealed-core check and the build pipeline's own refusals.
FIX_LOOP_PROTECTED_PATHS = (
    "src/probos/cognitive/builder.py",
    "src/probos/cognitive/builder_paths.py",
    "src/probos/cognitive/code_reviewer.py",
    "src/probos/cognitive/copilot_adapter.py",
    "src/probos/execution/command_env.py",
    "src/probos/extensions/sealed_core.py",
    "src/probos/build_dispatcher.py",
    "src/probos/build_pipeline.py",
    "src/probos/worktree_manager.py",
    "src/probos/routers/build.py",
)

# File names pytest reads as configuration or plugins; refused at any depth.
FIX_LOOP_REFUSED_NAMES = (
    "conftest.py",
    "pytest.ini",
    ".pytest.ini",
    "tox.ini",
    "setup.cfg",
)

_FIX_LOOP_PROTECTED = frozenset(
    "/".join(_canonical(part) for part in path.split("/")) for path in FIX_LOOP_PROTECTED_PATHS
)
_FIX_LOOP_REFUSED = frozenset(_canonical(name) for name in FIX_LOOP_REFUSED_NAMES)

# Control characters (Cc) and the line and paragraph separators (Zl, Zp): a path that holds
# one can add a paragraph to the commit message that discloses it, and os.stat raises on a NUL.
_FIX_LOOP_LINE_BREAKING = frozenset({"Cc", "Zl", "Zp"})


def fix_loop_path(path_str: str) -> str:
    """The one spelling the fix loop judges and writes: separators as ``/``."""
    return path_str.replace("\\", "/")


def fix_loop_write_refusal(
    path_str: str, work_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """BF-898 (#1563): why the test-fix loop must not write *path_str*, or None if it may.

    A control or line-break character is refused first (the reason quotes the path with
    ``repr`` so it stays one line); then everything ``builder_write_refusal`` refuses is
    refused, with its reason.
    Then the path must be plain (no empty or ``.`` component), must start with the
    components ``src`` and ``probos`` exactly as written, must not be one of
    ``FIX_LOOP_PROTECTED_PATHS`` and must not be named one of
    ``FIX_LOOP_REFUSED_NAMES`` (both compared in the canonical form, so a case,
    trailing-dot or ignorable-code-point variant is the same name).
    """
    if any(unicodedata.category(char) in _FIX_LOOP_LINE_BREAKING for char in path_str):
        return (
            f"Fix-loop write refused (BF-898): {path_str!r} contains a control or "
            "line-break character"
        )
    refusal = builder_write_refusal(path_str, work_dir)
    if refusal is not None:
        return refusal
    parts = fix_loop_path(path_str).split("/")
    if any(part in ("", ".") for part in parts):
        return f"Fix-loop write refused (BF-898): {path_str} is not a plain relative path"
    if len(parts) < 3 or tuple(parts[:2]) != FIX_LOOP_WRITABLE_ROOT:
        return (
            f"Fix-loop write refused (BF-898): {path_str} is outside src/probos/; an "
            "unreviewed repair changes source only, never a test, a conftest.py or "
            "test configuration"
        )
    canonical = "/".join(_canonical(part) for part in parts)
    if canonical in _FIX_LOOP_PROTECTED:
        return (
            f"Fix-loop write refused (BF-898): {path_str} is part of the build's grader "
            "or write boundary"
        )
    if _canonical(parts[-1]) in _FIX_LOOP_REFUSED:
        return f"Fix-loop write refused (BF-898): {path_str} is pytest configuration"
    return None


# (path, refused): judged by fix_loop_self_test with the lexical rules only.
FIX_LOOP_SELF_TEST: tuple[tuple[str, bool], ...] = (
    # tests, conftest and pytest configuration, wherever they are
    ("tests/test_widget.py", True),
    ("tests/conftest.py", True),
    ("tests/unit/conftest.py", True),
    ("conftest.py", True),
    ("pytest.ini", True),
    (".pytest.ini", True),
    ("tox.ini", True),
    ("setup.cfg", True),
    ("src/probos/conftest.py", True),
    ("src/probos/pkg/conftest.py", True),
    ("src/probos/CONFTEST.PY", True),
    ("src/probos/pytest.ini", True),
    ("src/probos/.pytest.ini", True),
    ("src/probos/tox.ini", True),
    ("src/probos/setup.cfg", True),
    # outside src/probos/: top-level modules on the pytest PYTHONPATH, other trees
    ("src/sitecustomize.py", True),
    ("src/pytest.py", True),
    ("src/_pytest/runner.py", True),
    ("config/sealed_modules.yaml", True),
    ("docs/notes.md", True),
    ("prompts/notes.md", True),
    ("src/PROBOS/widget.py", True),
    ("src/probos", True),
    ("src/probos/", True),
    # non-plain forms
    ("src/probos//cognitive/builder.py", True),
    ("src/probos/./cognitive/builder.py", True),
    # control and line-break characters, refused before anything else
    ("src/probos/a\nb.py", True),
    ("src/probos/a\rb.py", True),
    ("src/probos/a\tb.py", True),
    ("src/probos/a\x0bb.py", True),
    ("src/probos/a\x0cb.py", True),
    ("src/probos/a\x00b.py", True),
    ("src/probos/a\x1bb.py", True),
    ("src/probos/a\x7fb.py", True),
    ("src/probos/a\x85b.py", True),
    ("src/probos/a\u2028b.py", True),
    ("src/probos/a\u2029b.py", True),
    # builder_write_refusal's own rules apply next
    ("src/probos/con.py", True),
    # the grader and the boundary
    ("src/probos/cognitive/builder.py", True),
    ("src/probos/cognitive/builder_paths.py", True),
    ("src/probos/cognitive/code_reviewer.py", True),
    ("src/probos/cognitive/copilot_adapter.py", True),
    ("src/probos/execution/command_env.py", True),
    ("src/probos/extensions/sealed_core.py", True),
    ("src/probos/build_dispatcher.py", True),
    ("src/probos/build_pipeline.py", True),
    ("src/probos/worktree_manager.py", True),
    ("src/probos/routers/build.py", True),
    ("src/probos/cognitive/Builder.py", True),
    ("src/probos/cognitive/builder.py.", True),
    ("src/probos/cognitive/build\u200cer.py", True),
    ("src\\probos\\routers\\build.py", True),
    # source the loop may change, including near misses of protected names
    ("src/probos/widget.py", False),
    ("src/probos/newpkg/fresh.py", False),
    ("src/probos/cognitive/builder_helpers.py", False),
    ("src/probos/cognitive/code_reviewer_rules.py", False),
    ("src/probos/routers/builds.py", False),
    ("src/probos/conftest_helpers.py", False),
    ("src/probos/execution/command_policy.py", False),
    ("src\\probos\\widget.py", False),
)


def fix_loop_self_test() -> tuple[str, ...]:
    """Judge every ``FIX_LOOP_SELF_TEST`` example with ``fix_loop_write_refusal``.

    Lexical rules only (no ``work_dir``), so the result does not depend on the host.
    Returns one line per example whose outcome differs from its expectation.
    """
    failures: list[str] = []
    for path, refused in FIX_LOOP_SELF_TEST:
        observed = fix_loop_write_refusal(path) is not None
        if observed != refused:
            expected_word = "refused" if refused else "allowed"
            observed_word = "refused" if observed else "allowed"
            failures.append(f"{path!r}: expected {expected_word}, got {observed_word}")
    return tuple(failures)


def operator_checkout_refusal(
    work_dir: str | os.PathLike[str], operator_root: str | os.PathLike[str],
) -> str | None:
    """BF-897 (#1559): why a build must not run in *work_dir*, or None if it may.

    *operator_root* is the checkout the runtime started from. A build that runs
    there switches the operator's branch, writes beside their uncommitted edits
    and commits in their tree, so it is refused. Git finds a work tree's
    repository at the nearest ``.git`` entry (a directory, or a linked
    worktree's pointer file) at or above it; *work_dir* is refused when that
    entry is *operator_root*'s. A linked worktree, nested inside the checkout or
    not, has its own ``.git`` entry and is allowed, and so is a tree outside any
    checkout. No git command runs, so a test that patches ``subprocess.run``
    sees no extra call. A path that cannot be examined is refused.

    The check compares locations, not the repository a ``.git`` entry names: a
    pointer file or junction to *operator_root*'s git directory passes it
    (recorded, #1523).
    """
    root = Path(operator_root)
    try:
        if not os.path.lexists(root / ".git"):
            return None  # the runtime does not run from a checkout: nothing to protect
        target = Path(work_dir).resolve()
        for candidate in (target, *target.parents):
            if os.path.lexists(candidate / ".git"):
                if os.path.samefile(candidate, root):
                    return (
                        f"Refused (BF-897): {work_dir} is in the checkout ProbOS runs from "
                        f"({root}); a build runs only in a linked worktree"
                    )
                return None
    except OSError as exc:
        return (
            "Refused (BF-897): cannot verify the build work tree against the checkout "
            f"ProbOS runs from ({type(exc).__name__}): {work_dir}"
        )
    return None
