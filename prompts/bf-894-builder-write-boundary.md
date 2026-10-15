# Build contract: BF-894 (#1547): one write boundary for both builder write paths

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-15, through the bridge (read-only). Saved by the orchestrator from the Architect's answer; its cover note is carried into the follow-ups below: every line number is from `5aaa7c00`, the model-authored tests (run as the builder's own user in `work_dir`) are a larger route to `.git` than the declared write paths and are follow-up 1, and `red_team.py:584` has a second case-only `.git` check (follow-up 3). Base for the build: `main` at `f2a0db6d` (BF-892 and BF-893 merged); the contract's edits were dry-run against that tree's `builder.py` before the build.
**Status:** ready to build as one slice · **Depends on:** BF-892 on `main` (builder.py environment edits) · **New tests:** about 45 cases, most of them parametrized rows, in one new file.

**Corrections (orchestrator, after review round 1, 2026-10-15; claude-architect decided each):** (1) the Absence row "No other module writes into a builder work_dir" was incomplete: the Copilot SDK agent writes through its own tools into the worktree on the queued `BuildDispatcher` route, which no grep for write calls can see; that route is descoped to BF-896 (#1550), where it fails closed at the clean-tree guard, and this change does **not** bound it (wording below); (2) Windows device names (`NUL`, `con.py`) are now refused here: a write to `NUL` succeeds and its cleanup `unlink` then raises `PermissionError` (executed), so the build crashed instead of returning a result; the Architect's pattern `^(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(\..*)?$` did not match `lpt9 .py`, which his own test list requires, so the built rule allows spaces before the extension (`^(...) *(\..*)?$`); (3) the repair loop now passes the same boundary as the approved writes, so a repair outside `src/ tests/ config/ docs/ prompts/` (for example `ui/`) is refused: intended, because the approved writes were always limited to those prefixes and the repair loop only fixes pytest failures.

**What this change guarantees, and what it does not.** Every path `execute_approved_build` writes into a builder `work_dir` (the approved writes and the test-fix repair loop) passes `builder_write_refusal`. It does **not** bound writes made by the Copilot SDK agent's own tools on the queued `BuildDispatcher` route (`build_dispatcher.py:161-163`, `copilot_adapter.py:509-510`, `approve_all`): there the agent writes into the worktree before any validation, the executor's clean-tree guard (`builder.py:2679`) then refuses the build so no unvalidated write is committed, but the route cannot succeed and the agent is unconfined. Tracked in BF-896 (#1550).

**Verdict: build it.** Both checks are used together:

- **Name rules on every platform.** Each path component is compared in canonical form: HFS+ ignorable code points dropped, trailing dots and spaces trimmed, upper-cased. Any `:` and any 8.3 `~<digit>` form are refused.
- **An identity check whenever `<work_dir>/.git` exists.** Every existing prefix of the target is compared with that entry using `os.path.samestat`.

Neither check is enough alone:
- The name rules are the only defence when `.git` does not exist yet. On HFS+, creating `.g\u200cit` creates `.git`.
- The identity check catches anything the filesystem resolves to `.git` that no name rule lists (a hard link, a dotless `ı` the upper-casing misses on some filesystem, and similar).

One function, `builder_write_refusal(path, work_dir)`, goes in a new module `src/probos/cognitive/builder_paths.py`. Both write paths call it. A refusal on either path goes into `validation_errors`, which blocks the commit; that is the result shape the initial path already uses. `git add` gains `--`.

---

## Verified Against Codebase (2026-10-15, HEAD `5aaa7c00`)

```
git log --oneline -3   -> 5aaa7c00 BF-893 repair round 2; 6cbf559a; 550edeba
Grep '_validate_file_path|_check_sealed_path|write_text|...|def _git_' src/probos/cognitive/builder.py
  106  def _validate_file_path(path_str: str) -> str | None:
  88-103 _ALLOWED_PATH_PREFIXES / _FORBIDDEN_PATHS (".git/", ".env", "pyproject.toml", ".github/")
  128-131 not under an allowed prefix and no "/" -> "Root-level file — allow"  (why .GiT, GIT~1, .git. pass today)
  2710 path_error = _validate_file_path(change["path"])   (initial writes; refusal -> validation_errors, :2713)
  2716 path = Path(work_dir) / change["path"]; :2745 / :2765 write_text (modify / create)
  2872-2873 for change in fix_changes: path = Path(work_dir) / change["path"]   (repair; NO validation)
  2885-2886 / 2891-2892 _check_sealed_path then write_text (repair modify / create)
  2912-2913 if validation_errors: result.error = "Syntax errors:\n" + ...   (blocks the commit)
  2967-2970 failure cleanup unlinks only `written` entries
  1669-1673 _git_add_and_commit: _run_git(["add", *files], work_dir)   (no "--")
  1621-1646 _run_git: subprocess.run(["git", *args], env=build_command_env(), cwd=work_dir)
  2348-2363 _parse_file_blocks: path = m.group(1).strip()   (trailing spaces cannot arrive via the parser)
  2473-2497 _map_source_to_tests: every result is tests_dir / name or tests_dir.glob(...)
  2525 subprocess.run([sys.executable, "-m", "pytest", "--tb=short", "-q"] + test_files, ...)
  2604 def _check_sealed_path(target_path, runtime)   (untouched)
  172 BuildResult.error: str = ""
Grep 'execute_approved_build|_validate_file_path' src/probos
  build_dispatcher.py:182 (work_dir=worktree_info.path: a LINKED worktree, .git is a pointer file)
  routers/build.py:394 (work_dir = repo root, :60); build_pipeline.py:89 (delegates); builder.py:2710 only caller of the validator
Grep 'write_text|write_bytes|open\(|unlink|mkdir' build_dispatcher.py routers/build.py -> none (dispatcher :232 read_text only)
routers/build.py:105-114 commit_override: _git_add_and_commit(report.files_written + files_modified, ...)
tests/test_builder_guardrails.py:15-21 imports _validate_file_path; :45,:55,:59,:63,:69,:81,:85 assert
  "traversal" / "Forbidden" / "outside allowed" / "Absolute" substrings; :89-91 root-level files accepted
tests/test_builder_agent.py:2167-2228 fix-loop tests: root-level paths in tmp_path (no .git); patch _run_targeted_tests
tests/test_bf892_spawn_env_guard.py:41,440 scans src/ only (_SRC.rglob)
pyproject.toml:181 asyncio_mode = "auto"
agents/red_team.py:584 forbidden = (".git/", ".env", "pyproject.toml", ".github/workflows/")  (separate check, same alias class)
cognitive/swe_harness/tools.py:229-232 _resolve_path -> _PROJECT_ROOT / p (absolute passes); :963, :1080 write_text
```

### Absence Verified

| Claim | Run | Found | Holds |
|---|---|---|---|
| The validator has no other production caller | Grep `_validate_file_path` src/probos | builder.py:106, :2710 | yes |
| No other module **in ProbOS code** writes into a builder work_dir | Grep write/open/unlink/mkdir in build_dispatcher.py, routers/build.py, build_pipeline.py | none in code; **but the Copilot SDK agent writes through its own tools** (`copilot_adapter.py:509-510`, `approve_all`, `cwd` = worktree via `build_dispatcher.py:163`), which no grep can see | **no, partial: the SDK route is descoped to BF-896 (#1550) and fails closed at the clean-tree guard (`builder.py:2679`)** |
| No other builder.py argv carries a model-authored path that could start with `-` | Grep `_run_git\(\|subprocess.run\(\|create_subprocess_exec` builder.py | :1651, :1659/:1662/:1663 (branch name via `_sanitize_branch_name`: `[a-z0-9-]` then `.strip("-")`, so never a leading `-`), :1673 add (**fixed here**), :1677 `commit -m message` (an option value), :1682, :1688, :2965 (sanitized branch), :2449 (no paths), :2525 (all under `tests_dir`), :2579/:2591 (no paths) | yes; pytest argv is pinned by a test rather than changed |
| No test pins the lines this contract edits | Grep `getsource\(.*(execute_approved_build\|_git_add_and_commit)\|\["add", \*files\]\|Path\(work_dir\) / change` tests/ | none | yes |
| No test patches `_validate_file_path` | Grep `_validate_file_path` tests/ | only the test_builder_guardrails import and calls | yes |
| No internal prior art | Grep `is_ntfs_dotgit\|GIT~1\|CVE-2014-9390\|samestat` docs/ src/ DECISIONS.md | `repository_instructions.py:228` samefile (unrelated) | yes |
| The SWE harness write tool has no `.git` guard | Grep `\.git\b\|_FORBIDDEN\|samefile` cognitive/swe_harness | none | yes (follow-up 2) |

---

## Hidden pins

| Pin | Why | Action |
|---|---|---|
| `tests/test_builder_guardrails.py:19` imports `_validate_file_path`; :45-91 assert message substrings | a rename or reworded messages would break it | keep the alias `_validate_file_path = builder_write_refusal`; keep "Path traversal blocked", "Absolute path blocked", "Forbidden path…", "Path outside allowed directories"; check traversal and absolute paths before the per-component rules (`C:\…` must still say "Absolute") |
| `tests/test_builder_agent.py` fix-loop tests (`ok.py`, `fixme.py` root-level in tmp_path) | the repair loop now validates | safe: root-level names pass the name rules; tmp_path has no `.git`, so the identity check returns None |
| `tests/test_bf892_spawn_env.py:175-203` counts `_run_git` launches and their env | argv changes, launch count does not | safe |

---

## Section 1: `src/probos/cognitive/builder_paths.py` (new, whole file)

```python
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
```

## Section 2: `src/probos/cognitive/builder.py`

### 2.1 Import

<<<<<<< SEARCH
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.events import EventType
from probos.execution.command_env import build_command_env
=======
from probos.cognitive.builder_paths import builder_write_refusal
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.events import EventType
from probos.execution.command_env import build_command_env
>>>>>>> REPLACE

### 2.2 The old validator becomes an alias

<<<<<<< SEARCH
# Allowed top-level directories for builder file operations
_ALLOWED_PATH_PREFIXES = (
    "src/",
    "tests/",
    "config/",
    "docs/",
    "prompts/",
)

# Paths that must never be written by the builder
_FORBIDDEN_PATHS = (
    ".git/",
    ".env",
    "pyproject.toml",
    ".github/",
)


def _validate_file_path(path_str: str) -> str | None:
    """Validate a file path is safe for the builder to write.

    Returns None if valid, or an error message if invalid.
    """
    # Normalize separators
    normalized = path_str.replace("\\", "/")

    # Block path traversal
    if ".." in normalized:
        return f"Path traversal blocked: {path_str}"

    # Block forbidden paths
    for forbidden in _FORBIDDEN_PATHS:
        if normalized.startswith(forbidden) or normalized == forbidden.rstrip("/"):
            return f"Forbidden path: {path_str}"

    # Block absolute paths
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return f"Absolute path blocked: {path_str}"

    # Must be under an allowed prefix
    if not any(normalized.startswith(prefix) for prefix in _ALLOWED_PATH_PREFIXES):
        # Allow top-level known files (conftest.py, test scripts, etc.)
        if "/" not in normalized:
            return None  # Root-level file — allow
        return f"Path outside allowed directories: {path_str} (allowed: {', '.join(_ALLOWED_PATH_PREFIXES)})"

    return None
=======
# BF-894 (#1547): the write-path boundary is builder_paths.builder_write_refusal, called
# from both write paths in execute_approved_build. This name is kept for
# tests/test_builder_guardrails.py.
_validate_file_path = builder_write_refusal
>>>>>>> REPLACE

### 2.3 Initial writes

<<<<<<< SEARCH
            # Validate file path before any disk operations
            path_error = _validate_file_path(change["path"])
            if path_error:
=======
            # Validate file path before any disk operations (BF-894: lexical and identity)
            path_error = builder_write_refusal(change["path"], work_dir)
            if path_error:
>>>>>>> REPLACE

### 2.4 Repair loop

<<<<<<< SEARCH
                    # Apply fix changes
                    for change in fix_changes:
                        path = Path(work_dir) / change["path"]
                        if change["mode"] == "modify":
=======
                    # Apply fix changes
                    for change in fix_changes:
                        # BF-894 (#1547): the same boundary as the approved writes; a refusal
                        # blocks the commit the same way (validation_errors).
                        repair_error = builder_write_refusal(change["path"], work_dir)
                        if repair_error:
                            logger.warning("BuilderAgent: repair %s, skipping", repair_error)
                            validation_errors.append(repair_error)
                            continue
                        path = Path(work_dir) / change["path"]
                        if change["mode"] == "modify":
>>>>>>> REPLACE

### 2.5 `git add --`

<<<<<<< SEARCH
    """Stage *files* and commit.  Returns (success, commit_hash_or_error)."""
    rc, _out, err = await _run_git(["add", *files], work_dir)
=======
    """Stage *files* and commit.  Returns (success, commit_hash_or_error)."""
    # BF-894 (#1547): "--" so a model-authored name beginning with "-" is a path, not an option.
    rc, _out, err = await _run_git(["add", "--", *files], work_dir)
>>>>>>> REPLACE

---

## Section 3: `tests/test_bf894_builder_write_boundary.py` (new, whole file)

```python
"""BF-894 (#1547): the builder's write-path boundary.

Every negative has a control: the exact ``.git`` form is refused too, and legitimate paths
are accepted with the same work_dir. The Windows-only forms are refused lexically on every
platform; whether they WRITE THROUGH to ``.git`` can be shown only on a case-insensitive
filesystem, so their end-to-end rows skip elsewhere. The hard-link alias proves the identity
check and the write-through on every platform, Linux CI included.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive import builder as builder_module
from probos.cognitive import builder_paths
from probos.cognitive.builder import BuildSpec, _git_add_and_commit, _map_source_to_tests, _validate_file_path, execute_approved_build
from probos.cognitive.builder_paths import builder_write_refusal

_HAS_GIT = shutil.which("git") is not None
_POINTER = "gitdir: ../elsewhere/.git/worktrees/wt\n"
_LEGIT = ("src/probos/x.py", "tests/test_x.py", "config/system.yaml", "docs/a b.md", "conftest.py", ".gitignore", "tests/fixtures/.gitkeep", "tests/-n.py")
_ALIASES = [".GiT", "GIT~1", ".git.", ".git::$DATA", "pointer-alias"]


def _refused(path: str, work_dir: Path | None = None) -> str:
    refusal = builder_write_refusal(path, work_dir)
    assert refusal is not None, f"{path!r} must be refused"
    return refusal


def test_premise_exact_forms_refused_and_legitimate_paths_accepted() -> None:
    assert "Forbidden" in _refused(".git") and "Forbidden" in _refused(".git/config")
    assert [builder_write_refusal(p) for p in _LEGIT] == [None] * len(_LEGIT)
    assert _validate_file_path is builder_write_refusal


@pytest.mark.parametrize("alias", [".GiT", ".Git", ".GIT", ".g\u0131t", "src/.GIT/config"])
def test_validate_rejects_case_variant_git(alias: str) -> None:
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize("alias", [".git.", ".git ", ".git. .", ".git::$DATA", ".GiT::$DATA", ".git\\.", "src\\.git"])
def test_validate_rejects_trailing_dot_and_stream_forms(alias: str) -> None:
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize("alias", ["GIT~1", "git~1", "git~2/config", "GITHUB~1/workflows/ci.yml", "PYPROJ~1.TOM"])
def test_validate_rejects_short_name_forms(alias: str) -> None:
    assert "8.3" in _refused(alias)


@pytest.mark.parametrize("alias", [".g\u200cit", "\ufeff.git", ".gi\u206at"])
def test_validate_rejects_hfs_ignorable_forms(alias: str) -> None:
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize("alias", [".ENV", ".env.", "PyProject.toml", "pyproject.toml ", ".GitHub/workflows/ci.yml"])
def test_validate_rejects_variants_of_the_other_forbidden_paths(alias: str) -> None:
    assert "Forbidden" in _refused(".env") and "Forbidden" in _refused("pyproject.toml")  # premise
    assert "Forbidden" in _refused(alias)


@pytest.mark.parametrize("name", ["-n.py", "--output=x.txt", "-"])
def test_validate_rejects_option_shaped_first_component(name: str) -> None:
    assert builder_write_refusal("tests/-n.py") is None  # control: only the first component reaches argv first
    assert "Option-shaped" in _refused(name)


@pytest.mark.parametrize("empty", ["", "   "])
def test_validate_rejects_empty_path(empty: str) -> None:
    assert "Empty" in _refused(empty)


def _make_pointer(root: Path) -> Path:
    pointer = root / ".git"
    pointer.write_text(_POINTER, encoding="utf-8")
    return pointer


def test_identity_check_refuses_a_hard_link_to_the_git_pointer(tmp_path: Path) -> None:
    pointer = _make_pointer(tmp_path)
    os.link(pointer, tmp_path / "pointer-alias")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    assert os.path.samefile(tmp_path / "pointer-alias", pointer), "premise: the link is the same file"
    assert builder_write_refusal("pointer-alias") is None, "premise: no lexical rule names it"
    assert "same file as .git" in _refused("pointer-alias", tmp_path)
    assert builder_write_refusal("other.txt", tmp_path) is None  # control: an existing unrelated file
    assert builder_write_refusal("src/new.py", tmp_path) is None  # control: not on disk yet


def test_without_a_git_entry_the_lexical_rules_still_apply(tmp_path: Path) -> None:
    assert not (tmp_path / ".git").exists(), "premise"
    assert builder_write_refusal("src/new.py", tmp_path) is None
    assert "Forbidden" in _refused(".GiT", tmp_path)


def test_identity_check_fails_closed_when_a_prefix_cannot_be_examined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_pointer(tmp_path)
    (tmp_path / "src").mkdir()
    assert builder_write_refusal("src/new.py", tmp_path) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):
        if Path(path).name == "src":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = builder_write_refusal("src/new.py", tmp_path)
    monkeypatch.undo()
    assert refusal is not None and "Cannot verify" in refusal


def _no_real_git(stack: ExitStack) -> AsyncMock:
    for name, value in (("_git_current_branch", "main"), ("_is_dirty_working_tree", False),
                        ("_git_create_branch", (True, "builder-bf894")), ("_git_checkout_main", (True, "ok")),
                        ("_run_git", (0, "", ""))):
        stack.enter_context(patch.object(builder_module, name, AsyncMock(return_value=value)))
    commit = AsyncMock(return_value=(True, "abc123"))
    stack.enter_context(patch.object(builder_module, "_git_add_and_commit", commit))
    return commit


def _setup_root(tmp_path: Path, alias: str) -> tuple[Path, set[str]]:
    pointer = _make_pointer(tmp_path)
    if alias == "pointer-alias":
        os.link(pointer, tmp_path / alias)
    return pointer, set(os.listdir(tmp_path))


def _create(path: str, content: str = "gitdir: /victim/.git\n") -> dict:
    return {"path": path, "content": content, "mode": "create", "after_line": None}


@pytest.mark.parametrize("alias", _ALIASES)
async def test_initial_write_is_path_validated(tmp_path: Path, alias: str) -> None:
    pointer, before = _setup_root(tmp_path, alias)
    with ExitStack() as stack:
        commit = _no_real_git(stack)
        result = await execute_approved_build([_create(alias)], BuildSpec(title="BF-894 probe", description=""), str(tmp_path), run_tests=False)
    assert pointer.read_text(encoding="utf-8") == _POINTER  # catches write-through (Windows, hard link)
    assert set(os.listdir(tmp_path)) == before  # catches a new distinct file (case-sensitive filesystems)
    assert result.files_written == [] and "Forbidden" in result.error
    commit.assert_not_awaited()


async def test_initial_write_control_legitimate_path_is_written_and_committed(tmp_path: Path) -> None:
    _make_pointer(tmp_path)
    with ExitStack() as stack:
        commit = _no_real_git(stack)
        result = await execute_approved_build([_create("src/ok.py", "x = 1\n")], BuildSpec(title="BF-894 control", description=""), str(tmp_path), run_tests=False)
    assert result.files_written == ["src/ok.py"] and not result.error
    assert (tmp_path / "src" / "ok.py").read_text(encoding="utf-8") == "x = 1\n"
    assert commit.await_args.args[0] == ["src/ok.py"]


async def _repair_build(tmp_path: Path, fix_path: str) -> tuple[object, int]:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=MagicMock(content=f"===FILE: {fix_path}===\ngitdir: /victim/.git\n===END FILE===\n"))
    with ExitStack() as stack:
        _no_real_git(stack)
        stack.enter_context(patch.object(builder_module, "_run_targeted_tests", AsyncMock(return_value=(False, "1 failed", []))))
        result = await execute_approved_build([_create("ok.py", "x = 1\n")], BuildSpec(title="BF-894 repair", description=""),
                                              str(tmp_path), run_tests=True, max_fix_attempts=1, llm_client=llm)
    fix_calls = sum("Test Fix Required" in call.args[0].prompt for call in llm.complete.await_args_list)
    return result, fix_calls


@pytest.mark.parametrize("alias", _ALIASES)
async def test_repair_write_is_path_validated(tmp_path: Path, alias: str) -> None:
    pointer, before = _setup_root(tmp_path, alias)
    result, fix_calls = await _repair_build(tmp_path, alias)
    assert fix_calls == 1, "premise: the repair loop ran and received the alias block"
    assert pointer.read_text(encoding="utf-8") == _POINTER
    assert set(os.listdir(tmp_path)) == before  # ok.py was cleaned up; no alias file appeared
    assert alias not in result.files_written and "Forbidden" in result.error


async def test_repair_write_control_legitimate_fix_is_written(tmp_path: Path) -> None:
    _make_pointer(tmp_path)
    result, fix_calls = await _repair_build(tmp_path, "tests/test_fixed.py")
    assert fix_calls == 1
    assert "tests/test_fixed.py" in result.files_written and "Forbidden" not in result.error


def test_targeted_pytest_argv_is_anchored_under_work_dir(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for name in ("test_-k.py", "test_-n.py"):
        (tests_dir / name).write_text("", encoding="utf-8")
    found = _map_source_to_tests(["test_-k.py", "src/-n.py"], str(tmp_path))
    assert len(found) == 2, "premise: both option-shaped names are mapped"
    assert all(p.startswith(str(tests_dir)) for p in found)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _init_repo(path: Path, branch: str) -> None:
    path.mkdir()
    for args in (("init", "-q", "-b", branch), ("config", "user.email", "bf894@example.invalid"),
                 ("config", "user.name", "BF894 Tester"), ("config", "commit.gpgsign", "false"),
                 ("commit", "-q", "--allow-empty", "-m", "seed")):
        assert _git(path, *args).returncode == 0, f"premise: git {args[0]} must succeed"


@pytest.mark.skipif(not _HAS_GIT, reason="git is not installed")
async def test_git_add_stages_an_option_shaped_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, "main")
    name = "--bf894-option-shaped.txt"
    (repo / name).write_text("x\n", encoding="utf-8")
    bare = _git(repo, "add", name)
    staged = _git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    assert bare.returncode != 0 and name not in staged, "premise: without '--' git parses the name as an option"
    ok, sha = await _git_add_and_commit([name], "bf894 probe", str(repo))
    assert ok, sha
    assert name in _git(repo, "ls-tree", "--name-only", "HEAD").stdout.splitlines()


def _linked_worktree(tmp_path: Path) -> tuple[Path, Path, Path]:
    base, victim, wt = tmp_path / "base", tmp_path / "victim", tmp_path / "wt"
    _init_repo(base, "trunk")
    _init_repo(victim, "trunk")
    assert _git(base, "worktree", "add", "-q", "-b", "main", str(wt)).returncode == 0, "premise"
    (base / ".git" / "info").mkdir(exist_ok=True)
    with open(base / ".git" / "info" / "exclude", "a", encoding="utf-8") as fh:
        fh.write("pointer-alias\n")  # keeps the hard link out of `git status`
    pointer = wt / ".git"
    assert pointer.is_file(), "premise: a linked worktree's .git is a pointer file"
    if sys.platform == "win32":
        subprocess.run(["attrib", "-h", str(pointer)], check=True, capture_output=True)
        assert not os.stat(pointer).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN, "premise: pointer not hidden"
    return wt, victim, pointer


@pytest.mark.skipif(not _HAS_GIT, reason="git is not installed")
@pytest.mark.parametrize("alias", ["pointer-alias", ".GiT", "GIT~1"])
async def test_alias_write_does_not_move_the_repository(tmp_path: Path, alias: str) -> None:
    wt, victim, pointer = _linked_worktree(tmp_path)
    if alias == "pointer-alias":
        os.link(pointer, wt / alias)
    if not (wt / alias).exists() or not os.path.samefile(wt / alias, pointer):
        pytest.skip(f"{alias} is not an alias of .git here (case-sensitive filesystem or no 8.3 names)")
    git_dir = _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip()
    victim_head = _git(victim, "rev-parse", "HEAD").stdout.strip()
    pointer_bytes = pointer.read_bytes()
    assert _git(wt, "status", "--porcelain").stdout == "", "premise: the worktree is clean, so the build runs"
    change = _create(alias, f"gitdir: {(victim / '.git').as_posix()}\n")
    result = await execute_approved_build([change], BuildSpec(title="BF-894 probe", description=""), str(wt), run_tests=False)
    assert "Forbidden" in result.error
    assert pointer.read_bytes() == pointer_bytes
    assert _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip() == git_dir
    assert _git(victim, "rev-parse", "HEAD").stdout.strip() == victim_head
    assert _git(victim, "branch", "--list").stdout.split() == ["*", "trunk"]


@pytest.mark.skipif(not _HAS_GIT, reason="git is not installed")
async def test_legitimate_build_commits_in_the_linked_worktree(tmp_path: Path) -> None:
    wt, victim, _pointer = _linked_worktree(tmp_path)
    git_dir = _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip()
    victim_head = _git(victim, "rev-parse", "HEAD").stdout.strip()
    result = await execute_approved_build([_create("src/ok.py", "x = 1\n")], BuildSpec(title="BF-894 control", description=""), str(wt), run_tests=False)
    assert result.success and result.commit_hash, result.error
    assert _git(wt, "log", "-1", "--format=%s", result.branch_name).stdout.strip() == "BF-894 control"
    assert _git(wt, "rev-parse", "--absolute-git-dir").stdout.strip() == git_dir
    assert _git(victim, "rev-parse", "HEAD").stdout.strip() == victim_head
```

**Test premises (why each one fails before the fix):**
- On Windows, the unit rows `.GiT`, `GIT~1` (when 8.3 names are on), `.git.` and `.git::$DATA` write through. A Python-created `.git` is not hidden, so the pointer content changes.
- On Linux, the same rows create a new, separate file, so the directory listing changes.
- The `pointer-alias` row writes through on every operating system.
- In the end-to-end test without the fix, the pointer is rewritten and the commit lands in `victim`, so `victim`'s HEAD moves.

**What the Linux CI job cannot prove:**
- That `.GiT`, `GIT~1`, trailing-dot/space and `::$DATA` names actually write through on a real filesystem. Those end-to-end rows skip; the unit rows still prove they are refused.
- The `attrib -h` branch.

The Linux job does prove the identity check and an actual write-through, using the hard link. The Windows rows run on the Captain's machine. macOS on its default APFS (case-insensitive) would run the `.GiT` row, but CI has no macOS job.

**Focused gate:**

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf894_builder_write_boundary.py tests/test_builder_guardrails.py tests/test_builder_agent.py tests/test_bf892_spawn_env.py -q -n 0
```

---

## Mutation table (single-line anchors; CRLF tree; one campaign on the frozen candidate)

| # | File | Anchor line | Mutant | Killed by |
|---|---|---|---|---|
| 1 | builder_paths.py | `        if ":" in part:` | `if False:` | trailing_dot_and_stream[`.git::$DATA`] |
| 2 | builder_paths.py | `    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()` | drop `.rstrip(" .")` | trailing_dot_and_stream[`.git.`] |
| 3 | same line | | drop `_HFS_IGNORABLE.sub("", part)` (use `part`) | hfs_ignorable[*] |
| 4 | same line | | drop `.upper()` | case_variant[`.GiT`] |
| 5 | builder_paths.py | `        if _SHORT_NAME.search(part):` | `if False:` | short_name[*] |
| 6 | builder_paths.py | `        if _canonical(part) == ".GIT":` | `if False:` | case_variant[`src/.GIT/config`] |
| 7 | builder_paths.py | `        if canonical.startswith(folded) or canonical == folded.rstrip("/"):` | `canonical` → `normalized` (both) | other_forbidden_paths[`.ENV`] |
| 8 | builder_paths.py | `    if normalized.startswith("-"):` | `if False:` | option_shaped[*] |
| 9 | builder_paths.py | `    if not normalized.strip():` | `if False:` | empty_path[""] |
| 10 | builder_paths.py | `        if os.path.samestat(current, git_entry):` | `if False:` | hard_link unit; initial/repair[`pointer-alias`]; e2e[`pointer-alias`] |
| 11 | builder_paths.py | `    return _git_identity_refusal(parts, path_str, Path(work_dir))` | `return None` | same as 10 |
| 12 | builder_paths.py | `            return f"Cannot verify write path ({type(exc).__name__}): {path_str}"` | `return None` | fails_closed |
| 13 | builder.py | `            path_error = builder_write_refusal(change["path"], work_dir)` | drop `, work_dir` | initial[`pointer-alias`]; e2e[`pointer-alias`] |
| 14 | builder.py | `                        repair_error = builder_write_refusal(change["path"], work_dir)` | `repair_error = None` | repair[*] |
| 15 | builder.py | `                        if repair_error:` | `if False:` | repair[*] |
| 16 | builder.py | `                            validation_errors.append(repair_error)` | `pass` | repair[*] ("Forbidden" missing from the error) |
| 17 | builder.py | `    rc, _out, err = await _run_git(["add", "--", *files], work_dir)` | remove `"--", ` | git_add_option_shaped |
| 18 | builder_paths.py | `        if _RESERVED.match(_canonical(part)):` | `if False:` | windows_device_names[`nul`] (review round 1) |
| 19 | builder_paths.py | the `_RESERVED` pattern line | drop the `(\..*)?` extension group | windows_device_names[`src/con.py`] |
| 20 | builder_paths.py | the `_RESERVED` pattern line | drop the `^` anchor (match anywhere) | names_that_only_resemble_devices[`src/console.py`] |
| 21 | builder_paths.py | `        if _RESERVED.match(_canonical(part)):` | `_canonical(part)` → `part` | windows_device_names[`src/Nul.`] |

If a file differs from the campaign's overlay, rerun only the rows anchored in that file.

---

## Decisions (with reasons)

1. **Both checks.** The name rules cost one clause per alias form but work when `.git` is absent. The identity check covers whatever the filesystem itself decides is an alias. The probe showed every listed variant `samefile`-equal to `.git`, which no fixed list can promise to stay complete.
   - **Every OS refuses a case variant.** On Linux, `.GiT` is a different, harmless file, but no builder output needs one, and one rule everywhere keeps the tests portable.
   - **APFS and HFS+.** APFS normalisation adds no alias for plain-ASCII `.git`. HFS+ ignorable code points are removed by the name rules, and also caught by the identity check when `.git` exists.
   - **Where it lives.** A new module, `builder_paths.py` (SRP), with one public function. The `_validate_file_path` alias exists only for an existing test.
2. **argv handling.**
   - `git add` gets `--`; that is the fix.
   - Refusing a leading `-` in the validator is defence in depth, so the first component can never become an option for any later consumer.
   - pytest's argv is always anchored under `tests_dir` (`builder.py:2485`, `:2493`), so it needs no change; a test pins this.
   - No other launch in builder.py takes a model-authored path as argv (Absence table).
3. **Write sites.**
   - Covered: `builder.py:2745`, `:2765` (initial), `:2886`, `:2892` (repair), and transitively the `:2970` cleanup and `routers/build.py:114` (they only use validated entries).
   - Out of scope:
     - `builder.py:2077`: a visiting-builder copy of spec-authored files into a fresh `mkdtemp` that has no `.git`; git never runs there.
     - `swe_harness/tools.py:963` and `:1080`: they write under `_PROJECT_ROOT`, not a builder `work_dir`, and sit behind the harness's own effect boundary (follow-up 2).
4. **A refusal is reported the same way on both paths:** `logger.warning` plus `validation_errors`, so the commit is blocked.

## Do not build

- `_check_sealed_path`.
- OS-level sandboxing.
- Symlink containment, or any other change to what the builder may write elsewhere.
- `ALLOWED_PATH_PREFIXES` contents.
- `red_team.py:584`.
- `swe_harness/tools.py`.
- `_run_targeted_tests` / `_map_source_to_tests`.
- The misleading "Syntax errors:" label at `builder.py:2913`.

## Tracking

- `PROGRESS.md`: BF-894 CLOSED line.
- `docs/development/roadmap.md`: Bug Tracker row for BF-894 (#1547).
- `.claude/agent-memory/claude-architect/feedback_control_premise_check.md` already records the premise error behind this bug.

## Acceptance criteria

1. Every alias form is refused on both write paths (unit rows), with the exact `.git` premise refused too.
2. The linked-worktree reproduction no longer moves `git rev-parse --absolute-git-dir`, and `victim` is untouched (`pointer-alias` row on every OS; `.GiT`/`GIT~1` rows on Windows).
3. Legitimate `src/…`, `tests/…` and root-level writes are unchanged, and the legitimate build commits in the linked worktree.
4. An option-shaped name stages and commits through `_git_add_and_commit`.
5. `tests/test_builder_guardrails.py`, `tests/test_builder_agent.py` and `tests/test_bf892_spawn_env.py` pass unchanged.
6. All 21 mutants are killed (one campaign).
7. Reviewed by the Copilot Diff Reviewer (security-relevant). Brief it with properties: one function on both paths; fail-closed on a prefix that cannot be examined; old messages preserved; no new launch.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Follow-ups (with reach)

1. **The model's tests can rewrite `.git` themselves.**
   - The tests run as the builder's user in `work_dir`; this contract closes only the declared write paths.
   - Fix: at build start, fix the repository by construction (record `git rev-parse --absolute-git-dir` and pass `--git-dir`/`--work-tree` to every `_run_git` in the build), or at least check it is unchanged before `commit`.
   - Reach: every build through `build_dispatcher.py:182` and `routers/build.py:394`.
   - Highest value of the follow-ups. OS-level sandboxing stays a separate decision.
2. **The SWE-harness write tools have no `.git` guard** (`tools.py:963`, `:1080`, `_resolve_path` `:229-232` accepts absolute paths). Reach: the native agentic builder writing against `_PROJECT_ROOT`. File it (I could not confirm an existing issue; `gh search` returned nothing for my query).
3. **`red_team.py:584`'s forbidden list has the same alias gap** (exact, case-sensitive). Reach: the verifier passes a `.GiT` write. Reuse `builder_write_refusal` there.
4. **Symlink names.**
   - A dangling or outward symlink inside `work_dir` lets a write land outside it (the identity check follows symlinks only to compare with `.git`).
   - ~~Windows reserved names (`nul`, `con.py`) write to devices.~~ Done in review round 1: the rule refuses them.
   - Reach: small.
5. **Cosmetic:** a path refusal is reported under "Syntax errors:" (`builder.py:2913`).

## Prior art and blind spots

- **Absorbed: git's own rules from CVE-2014-9390.** `is_ntfs_dotgit` (case, trailing spaces and periods, `:` ends the name, `git~1` and hashed `~N` short names) and `is_hfs_dot_generic` (the ignorable code points U+200C-200F, U+202A-202E, U+206A-206F, U+FEFF). Sources: git `path.c` and `utf8.c` (github.com/git/git). Adapted: any `:` and any `~<digit>` is refused, because the builder has no legitimate use for either.
- **Absorbed: the orchestrator's 2026-10-15 probe.** `samestat` identity matches every listed variant; it is the backstop.
- **Python `str.upper()` vs `casefold()`.** `str.upper()` maps the dotless `ı` to `I`, as the NTFS upcase table does; `casefold()` does not, so the comparison uses `upper()`.
- **Internal research:** none found (Absence table).
- **Blind spot recorded:** the hidden attribute is an accidental barrier, not a control. Every test clears it, so the proof does not depend on it.
