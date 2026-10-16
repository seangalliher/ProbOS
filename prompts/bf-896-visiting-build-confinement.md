# BF-896 -- The queued visiting build runs in its own session directory under a deny-by-default permission policy, and its blocks reach the worktree only through the pinned executor

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Issue:** #1550 (BF-896; no AD allocated: a bug fix). **Base:** `main` `5a721bb2`.
**Status:** BUILD-READY. **Dependencies:** none outside this contract. Milestones run in order M1 -> M2 -> M3 (M2 uses M1's helper; M3 uses both).
**Estimated tests:** about 70 new (most of them parametrized cases), 6 updated.

## Problem

`BuildDispatcher._execute_build` (`src/probos/build_dispatcher.py:143-218`) builds `CopilotBuilderAdapter(model=..., cwd=worktree_info.path)` (:161-164), so the SDK session's `working_directory` is the build's real worktree, and the session approves every permission request (`copilot_adapter.py:509-510`, `PermissionHandler.approve_all`). The agent's own tools (write, shell) therefore reach the worktree, its `.git` pointer and any absolute path before anything is validated. The adapter's scan (`copilot_adapter.py:536-588`) `rglob`s the whole session directory and reports every file absent from `file_contents` as changed, so even an agent that wrote nothing would hand back most of the worktree. `execute_approved_build` (`cognitive/builder.py:2607`) refuses a dirty tree (:2636-2641), which is not a boundary: it asks whichever repository the worktree's `.git` currently names (BF-894 review round 2 replayed an identity change, a clean report and a commit including an unvalidated file).

A seam defect the fix exposes (orchestrator probe on a real temp git repo, `run_tests=False`): the adapter emits a changed existing file as `{"mode": "modify", "content": <whole file>}` with no `replacements` (`copilot_adapter.py:581-587`); the executor's modify branch applies only `replacements` (`builder.py:2695`), logs "no changes applied", reports success and commits nothing. Once generation runs off the worktree, every build that changes an existing file would report success with the change silently dropped.

## Decisions (Architect, 2026-10-16; in the Delegated AD Execution envelope)

- **D1 Handler.** One module-level factory `build_session_permission_handler(session_dir, tool_names)` in `copilot_adapter.py`. Approves: a `write` whose every named target resolves strictly inside the session directory AND passes `builder_write_refusal(rel)` lexically (the executor's own rules, applied earlier; `builder_paths.py` unchanged); a `read` strictly inside the session directory (no lexical write rules: a seeded `pyproject.toml` reference is a legitimate read); a `custom-tool` whose name is one of the adapter's registered tools. Denies `shell`, `url`, `mcp`, `memory`, any other or missing kind, any request it cannot parse, and anything that raises. It reads both request shapes (0.1.32 dataclass attributes `file_name`/`path`/`possible_paths`/`tool_name`; 0.1.30 wire-dict keys `fileName`/`path`/`possiblePaths`/`toolName`), normalizes an `Enum` kind to its `.value` and accepts only an exact `str` after that. Path checks: exact `str`, non-empty, no NUL, no `..` component, no `:` outside an absolute path's drive (NTFS stream, drive-relative `C:foo`), then `realpath` (symlinks followed; existing 8.3 components expand) and `commonpath` on `normcase` forms (a sibling `<session>_evil` fails), the root itself refused. Results are built at call time with the SDK's `PermissionRequestResult(kind=...)`: `"approved"` or `"denied-by-rules"` (both kinds exist in 0.1.30 and 0.1.32). That constructor builds a dataclass in 0.1.32 and a dict in 0.1.30, and each is what that release's client reads. Without the SDK a one-field fallback dataclass stands in, in the same way as the existing `ToolResult` fallback (`copilot_adapter.py:38-42`). The factory never raises: an unusable `session_dir` (`"bad\x00path"`, `""`, `None`, a relative or missing directory) makes every path request denied. The handler is built in `execute`, not in the constructor.
- **D2 Block shape: both ends, compare-and-swap.** Producer: a whole-file `modify` block also carries `"base"`, the text it was generated against. Consumer: a `modify` block with no `replacements` key and a `str` `content` is a whole-file replacement, applied only while the target's current text equals `base`; a missing or stale `base` is a refusal in `validation_errors` (it blocks the commit, visibly), never a silent drop. Consumer-only would be unsafe: the native visiting path seeds `all_files`, which `perceive` may already have replaced with *localized excerpts* (`builder.py:1981-1990`), and the session would then hand back excerpt-derived "whole files". With `base` = excerpt ≠ the file on disk, those blocks are refused. Producer-only (`create`) would be unsafe too: the failed-build cleanup unlinks `files_written` (`builder.py:2941-2944`). Also: a `create` block over a file that existed before this build is reported in `files_modified`, never `files_written`, on both write sites (approved and repair), so the cleanup can never unlink a pre-existing file. `BuildResult`: whole-file modify -> `files_modified`. `CodeReviewAgent._format_changes` renders a whole-file modify's content (it rendered an empty MODIFY).
- **D3 Identity pin.** New public `async repository_identity(work_dir) -> str | None` in `builder.py` (`git rev-parse --absolute-git-dir` through `_run_git`, normalized `normcase(realpath(...))`; `None` on non-zero exit, empty output, `OSError`/`ValueError`). The dispatcher captures it after the SDK check and before the session directory and adapter exist, and passes it as a new optional, last parameter `expected_git_dir` (default `None`: `routers/build.py:394` and every existing call are unchanged). The executor refuses (a) at entry, before any git command or write, and (b) immediately before the commit, after the tests that F-64 names as able to rewrite `.git`. The pre-commit check belongs here: it costs one call through the same helper and parameter, and it closes the entry-to-commit window for the identity change specifically. After (b) the executor runs no further git in the tree (no checkout, no `branch -D`: the tree now names a foreign repository whose hooks would run) and still unlinks only the files this build created. A capture that fails is fail-closed in the dispatcher (the route always holds a `WorktreeManager` worktree; an unreadable identity means the pin cannot defend). The executor's own non-repo behaviour, when no pin is given, is unchanged. F-64 keeps the broader hazard: tests rewriting the *contents* of the pinned git dir (hooks, config) without moving it.
- **D4 Session directory.** The dispatcher makes `mkdtemp(prefix="probos_visiting_")`, seeds it through the new `seed_session_directory`, passes it as `cwd` and the worktree as the new `instruction_work_dir`, and always removes it with `remove_workdir_off_loop` (the BF-844 pattern: cleanup failure logs, cancellation escapes). `execute` refuses to run a session when no explicit `cwd` was given (`CopilotBuildResult(success=False, error=...)` before discovery or `create_session`). A fallback session in `_PROJECT_ROOT` would let the agent write the live checkout. Absence verified below: no caller executes without `cwd`. `start()` keeps the `_PROJECT_ROOT` client cwd (`commands_llm.py:110` lists models only). `instruction_work_dir` defaults to `cwd` when omitted, so the native path and AD-1200's tests keep their discovery behaviour.
- **D5 SDK range: not capped here.** The handler fails closed on an unknown request or result shape, and 1.x cannot even construct the client (`CopilotClient(client_opts)` vs a keyword-only `__init__`), so a cap adds no confinement. Editing `pyproject.toml` and `uv.lock` widens this change into dependency resolution. Recorded for the wave follow-up.
- **D6 Native path: structure unchanged; seeding shared.** It keeps its `mkdtemp`, `finally` and BF-844 cleanup, and gets the handler through the same adapter. Its seeding loop is replaced by `seed_session_directory` (DRY, and it closes an escape: `tmp_path / file_path` with an absolute key, which is what `tests/test_bf844_visiting_builder_cleanup.py:132` passes, writes at the original location outside the temp dir). Seeding semantics stay the native ones: an empty entry (a target that does not exist yet, `builder.py:1970`) is not written.
- **D7 Tests.** Fakes only (no live SDK). One seam test on a real temp git repo through the real dispatcher, the real adapter on a fake SDK client (the AD-1200 pattern), the real handler, the real scan, the real `execute_approved_build(run_tests=False)` with `builder_write_refusal` live, and the real commit. Ownership is in **Milestones**.

## Solution overview

```
worktree (pinned: repository_identity)        session dir (mkdtemp, seeded)
        |                                              |
  _read_source_files --> seed_session_directory --> SDK session (cwd = session dir,
                                                       handler: write/read inside only,
                                                       registered tools only, shell denied)
                                                       |
                                       scan: only created/changed files
                                       (modify blocks carry "base")
                                                       |
  execute_approved_build(expected_git_dir) <-----------+
    entry identity check -> dirty check -> branch -> builder_write_refusal per block
    -> whole-file modify only on base match -> tests -> identity check -> commit
  finally: remove session dir (always)
```

## Implementation

Blocks are installed by script: each SEARCH occurs exactly once in its file at `5a721bb2`; LF line endings.

### Section 1 -- `src/probos/cognitive/copilot_adapter.py`

Imports.

<<<<<<< SEARCH
import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from probos.repository_instructions import (
=======
import asyncio
import json
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

from probos.cognitive.builder_paths import builder_write_refusal
from probos.repository_instructions import (
>>>>>>> REPLACE

### Section 2 -- `src/probos/cognitive/copilot_adapter.py`

The SDK import: `PermissionRequestResult` replaces `PermissionHandler` (its only use was `approve_all`), with a fallback for SDK-less tests.

<<<<<<< SEARCH
    from copilot import CopilotClient, PermissionHandler, Tool, ToolResult  # type: ignore[import-untyped]
    from copilot.generated.session_events import SessionEventType  # type: ignore[import-untyped]

    _SDK_AVAILABLE = True
except ImportError:
    # Minimal fallback so tool handlers work in tests without the SDK
    class ToolResult:  # type: ignore[no-redef]
        def __init__(self, *, text_result_for_llm: str = "") -> None:
            self.text_result_for_llm = text_result_for_llm
=======
    from copilot import CopilotClient, PermissionRequestResult, Tool, ToolResult  # type: ignore[import-untyped]
    from copilot.generated.session_events import SessionEventType  # type: ignore[import-untyped]

    _SDK_AVAILABLE = True
except ImportError:
    # Minimal fallback so tool handlers work in tests without the SDK
    class ToolResult:  # type: ignore[no-redef]
        def __init__(self, *, text_result_for_llm: str = "") -> None:
            self.text_result_for_llm = text_result_for_llm

    @dataclass
    class PermissionRequestResult:  # type: ignore[no-redef]
        """BF-896: stand-in with the SDK's ``kind`` field; used only without the SDK."""

        kind: str = "denied-no-approval-rule-and-could-not-request-from-user"
>>>>>>> REPLACE

### Section 3 -- `src/probos/cognitive/copilot_adapter.py`

The session policy and the seeding helper, inserted before the class.

<<<<<<< SEARCH
    # Already relative — just normalize separators
    return normalized


class CopilotBuilderAdapter:
=======
    # Already relative — just normalize separators
    return normalized


# ── BF-896: session confinement ────────────────────────────────────────────

_PERMISSION_APPROVED = "approved"
_PERMISSION_DENIED = "denied-by-rules"  # a denial kind in SDK 0.1.30 and 0.1.32
# 0.1.32 sends a dataclass (snake_case attributes); 0.1.30 a wire dict (camelCase keys).
_PATH_FIELDS = ("file_name", "fileName", "path")
_POSSIBLE_PATH_FIELDS = ("possible_paths", "possiblePaths")
_TOOL_NAME_FIELDS = ("tool_name", "toolName")


def _request_field(request: Any, name: str) -> Any:
    """One field of a permission request, from either SDK shape."""
    if isinstance(request, dict):
        return request.get(name)
    return getattr(request, name, None)


def _request_kind(request: Any) -> str | None:
    """The request's kind as an exact ``str`` (0.1.32 sends an ``Enum``), or None."""
    kind = _request_field(request, "kind")
    if isinstance(kind, Enum):
        kind = kind.value
    return kind if type(kind) is str else None


def _session_root(session_dir: Any) -> tuple[str, str] | None:
    """(real path, case-folded real path) of an existing session directory, or None."""
    if type(session_dir) is not str or not session_dir or "\x00" in session_dir:
        return None
    try:
        real = os.path.realpath(session_dir)
        if not os.path.isdir(real):
            return None
        return real, os.path.normcase(real)
    except (OSError, ValueError):
        return None


def _session_relative(root: tuple[str, str], raw: Any) -> str | None:
    """The forward-slash path *raw* names strictly inside the session root, or None.

    Fails closed: a non-string, an empty value, a NUL, a ``..`` component, a ``:``
    anywhere but an absolute path's drive (an NTFS stream or a drive-relative form),
    and anything that resolves (symlinks followed) outside the root, or to the root
    itself, are all None.
    """
    if type(raw) is not str or not raw or "\x00" in raw:
        return None
    if ".." in raw.replace("\\", "/").split("/"):
        return None
    drive, tail = os.path.splitdrive(raw)
    if ":" in tail or (drive and not os.path.isabs(raw)):
        return None
    real_root, folded_root = root
    try:
        candidate = raw if os.path.isabs(raw) else os.path.join(real_root, raw)
        real = os.path.realpath(candidate)
        folded = os.path.normcase(real)
        if folded == folded_root or os.path.commonpath([folded_root, folded]) != folded_root:
            return None
        return os.path.relpath(real, real_root).replace("\\", "/")
    except (OSError, ValueError):
        return None


def _permission_verdict(
    request: Any, root: tuple[str, str] | None, tools: frozenset[str],
) -> bool:
    """True only for a request the session policy approves (see the factory)."""
    kind = _request_kind(request)
    if kind == "custom-tool":
        names = [n for n in (_request_field(request, f) for f in _TOOL_NAME_FIELDS) if n is not None]
        return bool(names) and all(type(n) is str and n in tools for n in names)
    if kind not in ("write", "read") or root is None:
        return False
    targets: list[Any] = [
        value for value in (_request_field(request, f) for f in _PATH_FIELDS) if value is not None
    ]
    for name in _POSSIBLE_PATH_FIELDS:
        extra = _request_field(request, name)
        if extra is None:
            continue
        if not isinstance(extra, (list, tuple)):
            return False
        targets.extend(extra)
    if not targets:
        return False
    for raw in targets:
        rel = _session_relative(root, raw)
        if rel is None:
            return False
        if kind == "write" and builder_write_refusal(rel) is not None:
            return False
    return True


def build_session_permission_handler(
    session_dir: Any, tool_names: Iterable[Any],
) -> Callable[..., Any]:
    """BF-896: the permission policy of a visiting build session, deny by default.

    Approves only: a ``write`` whose every named target lies strictly inside
    *session_dir* and passes the builder's lexical write rules
    (``builder_write_refusal``); a ``read`` strictly inside *session_dir*; a
    ``custom-tool`` call to one of *tool_names* (the adapter's registered tools).
    Every other kind (``shell``, ``url``, ``mcp``, ``memory``, anything new), a
    request it cannot parse, and any error are denied. Never raises: an unusable
    *session_dir* denies every path request.
    """
    root = _session_root(session_dir)
    try:
        allowed = frozenset(name for name in tool_names if type(name) is str)
    except Exception:
        allowed = frozenset()

    def handler(request: Any, invocation: Any = None) -> Any:
        try:
            label = _request_kind(request)
            approved = _permission_verdict(request, root, allowed)
        except Exception:
            label, approved = "unparsed", False
            logger.warning("BF-896: a permission request could not be evaluated; denied", exc_info=True)
        if not approved:
            logger.info("BF-896: visiting build session denied a %s permission request", label)
        return PermissionRequestResult(kind=_PERMISSION_APPROVED if approved else _PERMISSION_DENIED)

    return handler


def seed_session_directory(session_dir: str, files: Mapping[str, str]) -> dict[str, str]:
    """BF-896: copy a build's existing files into its session directory.

    Writes each non-empty entry at its session-relative path; an empty entry (a file
    that does not exist yet) is kept in the result but not written. A key that does
    not name a path strictly inside *session_dir* is logged and dropped. Returns the
    entries keyed by session-relative path, which is the key the adapter's scan
    compares against. Raises ValueError when *session_dir* is not an existing
    directory.
    """
    root = _session_root(session_dir)
    if root is None:
        raise ValueError(f"BF-896: session directory {session_dir!r} is not an existing directory")
    seeded: dict[str, str] = {}
    for raw, content in files.items():
        if type(content) is not str:
            continue
        rel = _session_relative(root, raw)
        if rel is None:
            logger.warning("BF-896: not seeding %r: it names no path inside the session directory", raw)
            continue
        seeded[rel] = content
        if not content:
            continue
        dest = Path(root[0]) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return seeded


class CopilotBuilderAdapter:
>>>>>>> REPLACE

### Section 4 -- `src/probos/cognitive/copilot_adapter.py`

Constructor: the session directory and the instruction directory are separate.

<<<<<<< SEARCH
        model: str = "claude-sonnet-5.5",
        cwd: str = "",
        github_token: str = "",
    ) -> None:
        self._codebase_index = codebase_index
        self._runtime = runtime
        self._model = model
        self._instruction_work_dir = cwd
        self._cwd = cwd or str(_PROJECT_ROOT)
=======
        model: str = "claude-sonnet-5.5",
        cwd: str = "",
        github_token: str = "",
        instruction_work_dir: str | None = None,
    ) -> None:
        self._codebase_index = codebase_index
        self._runtime = runtime
        self._model = model
        # BF-896: repository instructions are discovered from instruction_work_dir
        # (the worktree on the queued route); the session runs in cwd. A caller that
        # names only cwd keeps AD-1200's behaviour (both the same directory).
        self._instruction_work_dir = cwd if instruction_work_dir is None else instruction_work_dir
        self._cwd = cwd or str(_PROJECT_ROOT)
        # BF-896: execute() runs a session only in a directory its caller named;
        # the _PROJECT_ROOT fallback above is the client cwd for start() alone.
        self._session_dir_given = bool(cwd)
>>>>>>> REPLACE

### Section 5 -- `src/probos/cognitive/copilot_adapter.py`

The agent is told what the policy enforces.

<<<<<<< SEARCH
    "- Write all output files directly to the current directory using the paths from the build spec\n"
=======
    "- Write all output files directly to the current directory using the paths from the build spec\n"
    "- Shell commands, and reads or writes outside the current directory, are denied by the session's permission policy\n"
>>>>>>> REPLACE

### Section 6 -- `src/probos/cognitive/copilot_adapter.py`

`execute`: refuse without a session directory.

<<<<<<< SEARCH
        if not self._started:
            raise RuntimeError("Adapter not started")

        try:
            system_message = self._compose_system_message()
=======
        if not self._started:
            raise RuntimeError("Adapter not started")
        if not self._session_dir_given:
            # BF-896: without an explicit session directory the session would run in
            # the project root with write permission there.
            return CopilotBuildResult(
                success=False,
                error=(
                    "BF-896: no session directory was given; a visiting build session "
                    "runs only in a directory its caller created"
                ),
            )

        try:
            system_message = self._compose_system_message()
>>>>>>> REPLACE

### Section 7 -- `src/probos/cognitive/copilot_adapter.py`

`execute`: the deny-by-default handler replaces `approve_all`.

<<<<<<< SEARCH
                "working_directory": self._cwd,
                "on_permission_request": PermissionHandler.approve_all,
            }
=======
                "working_directory": self._cwd,
                # BF-896: deny by default; writes and reads only inside the session
                # directory, and only the adapter's own registered tools.
                "on_permission_request": build_session_permission_handler(
                    self._cwd, [getattr(tool, "name", None) for tool in tools],
                ),
            }
>>>>>>> REPLACE

### Section 8 -- `src/probos/cognitive/copilot_adapter.py`

The scan: a whole-file modify block carries its base.

<<<<<<< SEARCH
                        original = file_contents.get(rel_path, "")
                        mode = "modify" if original else "create"
                        file_blocks.append({
                            "path": rel_path,
                            "mode": mode,
                            "content": content,
                        })
=======
                        original = file_contents.get(rel_path, "")
                        mode = "modify" if original else "create"
                        block: dict[str, Any] = {
                            "path": rel_path,
                            "mode": mode,
                            "content": content,
                        }
                        if mode == "modify":
                            # BF-896: a whole-file MODIFY carries the text it was
                            # generated against; execute_approved_build applies it
                            # only while the target still holds exactly that text.
                            block["base"] = original
                        file_blocks.append(block)
>>>>>>> REPLACE

### Section 9 -- `src/probos/cognitive/builder.py`

`repository_identity`, after `_git_checkout_main`.

<<<<<<< SEARCH
    rc, out, err = await _run_git(["checkout", "main"], work_dir)
    if rc != 0:
        return False, err or out
    return True, "switched to main"
=======
    rc, out, err = await _run_git(["checkout", "main"], work_dir)
    if rc != 0:
        return False, err or out
    return True, "switched to main"


async def repository_identity(work_dir: str) -> str | None:
    """BF-896: the repository *work_dir* names, as git resolves it, or None.

    ``git rev-parse --absolute-git-dir`` follows a linked worktree's ``.git``
    pointer file, so rewriting that file changes the answer. The value is
    normalized (real path, OS case) so two captures compare with ``==``. None
    means it could not be determined; a caller pinning identity refuses on None.
    """
    try:
        rc, out, _err = await _run_git(["rev-parse", "--absolute-git-dir"], work_dir)
    except (OSError, ValueError):
        return None
    if rc != 0 or not out:
        return None
    try:
        return os.path.normcase(os.path.realpath(out))
    except (OSError, ValueError):
        return None
>>>>>>> REPLACE

### Section 10 -- `src/probos/cognitive/builder.py`

Native visiting path: seeding through the shared helper (D6).

<<<<<<< SEARCH
                from probos.cognitive.copilot_adapter import CopilotBuilderAdapter

                # Create isolated temp dir so SDK doesn't write into project root
                tmp_dir = tempfile.mkdtemp(prefix="probos_build_")
                tmp_path = Path(tmp_dir)

                # Copy existing target files into temp dir (preserving structure)
                for file_path, content in all_files.items():
                    if content:  # Only copy files that exist
                        dest = tmp_path / file_path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(content, encoding="utf-8")
=======
                from probos.cognitive.copilot_adapter import (
                    CopilotBuilderAdapter,
                    seed_session_directory,
                )

                # Create isolated temp dir so SDK doesn't write into project root
                tmp_dir = tempfile.mkdtemp(prefix="probos_build_")

                # Copy existing target files into temp dir (preserving structure).
                # BF-896: the helper the dispatcher uses; a key naming a path outside
                # the temp dir (an absolute target) is skipped, not written there.
                seed_session_directory(tmp_dir, all_files)
>>>>>>> REPLACE

### Section 11 -- `src/probos/cognitive/builder.py`

`execute_approved_build`: the pin parameter and the entry refusal.

<<<<<<< SEARCH
    runtime: ProbOSRuntime | None = None,
    specialty: str = "general",
) -> BuildResult:
    """Execute an approved build: write files, run tests, create git branch.

    Called AFTER the Captain reviews the BuilderAgent's output and approves
    the changes.  The agent generates the plan; this function executes it.

    Args:
        escalation_hook: Optional async callback invoked when tests fail after
            all fix attempts are exhausted. Receives a BuildFailureReport and
            returns either a resolved BuildResult or None to escalate to Captain.
            Future: wired to chain of command (Phase-33).
    """
    result = BuildResult(success=False, spec=spec)

    # 1. Save current branch
=======
    runtime: ProbOSRuntime | None = None,
    specialty: str = "general",
    expected_git_dir: str | None = None,
) -> BuildResult:
    """Execute an approved build: write files, run tests, create git branch.

    Called AFTER the Captain reviews the BuilderAgent's output and approves
    the changes.  The agent generates the plan; this function executes it.

    Args:
        escalation_hook: Optional async callback invoked when tests fail after
            all fix attempts are exhausted. Receives a BuildFailureReport and
            returns either a resolved BuildResult or None to escalate to Captain.
            Future: wired to chain of command (Phase-33).
        expected_git_dir: BF-896. A value ``repository_identity(work_dir)``
            returned before generation began. When given, the build is refused
            at entry (before any git command or write) and again before the
            commit if *work_dir* no longer names that repository.
    """
    result = BuildResult(success=False, spec=spec)
    identity_lost = False

    # 0. BF-896: the tree must still name the repository pinned before generation.
    if expected_git_dir is not None:
        current_git_dir = await repository_identity(work_dir)
        if current_git_dir != expected_git_dir:
            result.error = (
                "Repository identity changed since the build was pinned "
                f"(expected {expected_git_dir!r}, found {current_git_dir!r}); "
                "refused before any write"
            )
            return result

    # 1. Save current branch
>>>>>>> REPLACE

### Section 12 -- `src/probos/cognitive/builder.py`

Approved writes, modify branch: whole-file modify on base match (D2).

<<<<<<< SEARCH
                original = path.read_text(encoding="utf-8")
                modified = original

                for i, repl in enumerate(change.get("replacements", [])):
=======
                original = path.read_text(encoding="utf-8")
                modified = original

                if "replacements" not in change and isinstance(change.get("content"), str):
                    # BF-896: a whole-file MODIFY (the visiting adapter's disk scan).
                    # It applies only while the target still holds the text it was
                    # generated against; otherwise it is refused, never dropped.
                    if change.get("base") != original:
                        validation_errors.append(
                            f"Whole-file change to {change['path']} was generated "
                            "against different content; refused"
                        )
                        continue
                    modified = change["content"]

                for i, repl in enumerate(change.get("replacements", [])):
>>>>>>> REPLACE

### Section 13 -- `src/probos/cognitive/builder.py`

Approved writes, create branch: a create over a pre-existing file is a modification (D2).

<<<<<<< SEARCH
            path.parent.mkdir(parents=True, exist_ok=True)
            _check_sealed_path(path, runtime)
            path.write_text(change["content"], encoding="utf-8")
            written.append(change["path"])
            logger.info("BuilderAgent: wrote %s", change["path"])
=======
            path.parent.mkdir(parents=True, exist_ok=True)
            _check_sealed_path(path, runtime)
            pre_existing = path.exists() and change["path"] not in written
            path.write_text(change["content"], encoding="utf-8")
            if pre_existing:
                # BF-896: a CREATE over a file that existed before this build is a
                # modification. The failed-build cleanup unlinks files_written, so a
                # pre-existing file must never be listed there.
                if change["path"] not in modified_files:
                    modified_files.append(change["path"])
                logger.info("BuilderAgent: overwrote %s", change["path"])
            elif change["path"] not in written:
                written.append(change["path"])
                logger.info("BuilderAgent: wrote %s", change["path"])
>>>>>>> REPLACE

### Section 14 -- `src/probos/cognitive/builder.py`

Repair loop, create branch: the same rule.

<<<<<<< SEARCH
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            _check_sealed_path(path, runtime)
                            path.write_text(
                                change["content"], encoding="utf-8",
                            )
                            if change["path"] not in written:
                                written.append(change["path"])
=======
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            _check_sealed_path(path, runtime)
                            pre_existing = path.exists() and change["path"] not in written
                            path.write_text(
                                change["content"], encoding="utf-8",
                            )
                            if pre_existing:
                                # BF-896: never list a pre-existing file in files_written.
                                if change["path"] not in modified_files:
                                    modified_files.append(change["path"])
                            elif change["path"] not in written:
                                written.append(change["path"])
>>>>>>> REPLACE

### Section 15 -- `src/probos/cognitive/builder.py`

The pre-commit identity check.

<<<<<<< SEARCH
        # 5.5. Block commit if validation errors (syntax errors) exist
        if validation_errors:
=======
        # 5.4. BF-896: the tests may have run arbitrary code; the tree must still
        # name the pinned repository before anything is committed.
        if expected_git_dir is not None:
            current_git_dir = await repository_identity(work_dir)
            if current_git_dir != expected_git_dir:
                identity_lost = True
                logger.error(
                    "BuilderAgent: repository identity changed during the build "
                    "(expected %r, found %r); refusing to commit",
                    expected_git_dir, current_git_dir,
                )

        # 5.5. Block commit if validation errors (syntax errors) exist
        if identity_lost:
            result.error = (
                "Repository identity changed during the build; refused before commit"
            )
            result.success = False
        elif validation_errors:
>>>>>>> REPLACE

### Section 16 -- `src/probos/cognitive/builder.py`

`finally`: no git in a tree that names a foreign repository.

<<<<<<< SEARCH
        # 7. Return to original branch
        await _git_checkout_main(work_dir)
        # Clean up build branch if no commit was made (failed build)
        if not result.commit_hash and result.branch_name:
            logger.info("Cleaning up failed build branch '%s'", result.branch_name)
            await _run_git(["branch", "-D", result.branch_name], work_dir)
=======
        # 7. Return to original branch. BF-896: not when the tree now names a
        # repository other than the pinned one (its hooks would run).
        if not identity_lost:
            await _git_checkout_main(work_dir)
        # Clean up build branch if no commit was made (failed build)
        if not result.commit_hash and result.branch_name:
            if not identity_lost:
                logger.info("Cleaning up failed build branch '%s'", result.branch_name)
                await _run_git(["branch", "-D", result.branch_name], work_dir)
>>>>>>> REPLACE

### Section 17 -- `src/probos/cognitive/code_reviewer.py`

The reviewer sees a whole-file modify's content.

<<<<<<< SEARCH
            if mode == "modify":
                repls = change.get("replacements", [])
=======
            if mode == "modify" and "replacements" not in change:
                # BF-896: a whole-file MODIFY carries the new text, not SEARCH/REPLACE pairs.
                content = str(change.get("content", ""))[:3000]
                parts.append(f"### MODIFY (whole file): {path}\n```python\n{content}\n```")
            elif mode == "modify":
                repls = change.get("replacements", [])
>>>>>>> REPLACE

### Section 18 -- `src/probos/build_dispatcher.py`

Imports.

<<<<<<< SEARCH
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from probos.build_queue import BuildQueue, QueuedBuild
from probos.cognitive.builder import BuildResult, BuildSpec, execute_approved_build
from probos.worktree_manager import WorktreeManager

try:
    from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
    _SDK_AVAILABLE = True
=======
import logging
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from probos.build_queue import BuildQueue, QueuedBuild
from probos.cognitive.builder import (
    BuildResult,
    BuildSpec,
    execute_approved_build,
    repository_identity,
)
from probos.execution.isolation import remove_workdir_off_loop
from probos.worktree_manager import WorktreeManager

try:
    from probos.cognitive.copilot_adapter import CopilotBuilderAdapter, seed_session_directory
    _SDK_AVAILABLE = True
>>>>>>> REPLACE

### Section 19 -- `src/probos/build_dispatcher.py`

`_execute_build`: pin, session directory, executor with the pin, always-removed session directory.

<<<<<<< SEARCH
    async def _execute_build(self, build: QueuedBuild) -> None:
        """Execute a single build: worktree -> adapter -> apply -> result."""
        worktree_info = None
        try:
            # 1. Create worktree
            worktree_info = await self._worktree_mgr.create(build.id)
            self._queue.update_status(
                build.id, "building",
                worktree_path=worktree_info.path,
            )

            # 2. Read source files from worktree
            file_contents = self._read_source_files(build.spec, worktree_info.path)

            # 3. Generate code via CopilotBuilderAdapter
            if not _SDK_AVAILABLE:
                raise RuntimeError("Copilot SDK not available")

            adapter = CopilotBuilderAdapter(
                model=self._builder_model,
                cwd=worktree_info.path,
            )
=======
    async def _execute_build(self, build: QueuedBuild) -> None:
        """Execute a single build: worktree -> adapter -> apply -> result.

        BF-896: generation runs in a fresh session directory, never in the
        worktree. The worktree's repository identity is pinned before the
        adapter exists and is checked by ``execute_approved_build``, the only
        route by which blocks reach the worktree. The session directory is
        always removed.
        """
        worktree_info = None
        session_dir: str | None = None
        try:
            # 1. Create worktree
            worktree_info = await self._worktree_mgr.create(build.id)
            self._queue.update_status(
                build.id, "building",
                worktree_path=worktree_info.path,
            )

            # 2. Read source files from worktree
            file_contents = self._read_source_files(build.spec, worktree_info.path)

            # 3. Generate code via CopilotBuilderAdapter
            if not _SDK_AVAILABLE:
                raise RuntimeError("Copilot SDK not available")

            # BF-896: pin the repository the worktree names before anything
            # model-driven runs; a tree whose identity cannot be read is refused.
            expected_git_dir = await repository_identity(worktree_info.path)
            if expected_git_dir is None:
                raise RuntimeError(
                    f"Cannot pin the repository identity of worktree {worktree_info.path}"
                )

            # BF-896: the session runs in its own directory, seeded with the files
            # it may change, so the scan reports only what the session changed.
            session_dir = tempfile.mkdtemp(prefix="probos_visiting_")
            file_contents = seed_session_directory(session_dir, file_contents)

            adapter = CopilotBuilderAdapter(
                model=self._builder_model,
                cwd=session_dir,
                instruction_work_dir=worktree_info.path,
            )
>>>>>>> REPLACE

### Section 20 -- `src/probos/build_dispatcher.py`

<<<<<<< SEARCH
                run_tests=self._run_tests,
                builder_source="visiting",
            )
=======
                run_tests=self._run_tests,
                builder_source="visiting",
                expected_git_dir=expected_git_dir,
            )
>>>>>>> REPLACE

### Section 21 -- `src/probos/build_dispatcher.py`

<<<<<<< SEARCH
        finally:
            # Fire callback if provided
            updated_build = self._queue.get(build.id)
=======
        finally:
            if session_dir is not None:
                # BF-896: the session directory is the SDK client's cwd. Removal
                # retries (BF-844); its failure must not change the recorded outcome,
                # and a cancellation still escapes.
                try:
                    await remove_workdir_off_loop(Path(session_dir))
                except asyncio.CancelledError:
                    raise
                except Exception as cleanup_exc:
                    logger.warning(
                        "build-dispatcher: could not remove session directory %s "
                        "(%s: %s); it may remain on disk. The build result is unaffected.",
                        session_dir, type(cleanup_exc).__name__, cleanup_exc,
                    )
            # Fire callback if provided
            updated_build = self._queue.get(build.id)
>>>>>>> REPLACE

## Milestones and tests

Each Builder (Sonnet 5.5) owns one milestone: the sections listed are already installed; the Builder writes and updates the tests named, runs the focused gate, and hard-stops on any failure in a file it was not told to change. Interpreter: `d:/ProbOS/.venv/Scripts/pytest.exe` (say which one if elsewhere). Fakes follow `tests/test_ad1200_repository_instruction_wire.py:807-933`: `monkeypatch.setattr(sdk, "_SDK_AVAILABLE", True)`, a fake `CopilotClient` that takes its options dict positionally, `SessionEventType=SimpleNamespace(ASSISTANT_MESSAGE="assistant")`, `Tool=lambda **kw: SimpleNamespace(**kw)`. Permission-request fakes use a **real `Enum`** for `kind` (never a `str`): `class _Kind(Enum): WRITE="write"; READ="read"; SHELL="shell"; URL="url"; MCP="mcp"; MEMORY="memory"; CUSTOM_TOOL="custom-tool"`, and a dataclass request with `kind, file_name, path, possible_paths, tool_name, full_command_text`. A result helper reads `r["kind"] if isinstance(r, dict) else r.kind`. Real-git tests: `pytest.mark.skipif(shutil.which("git") is None)`, `git init -b main`, repo-local `user.name`/`user.email`, one initial commit.

### M1 -- Sections 1-8 (`copilot_adapter.py`)

New `tests/test_bf896_session_permission_handler.py`:
- `test_handler_approves` (parametrized): relative write `src/x.py`; absolute write inside; write in a new subdirectory; read inside; read of a seeded `pyproject.toml`; `custom-tool` `standing_orders_lookup`; each in both shapes (dataclass + Enum kind, and 0.1.30 dict with str kind and `fileName`/`toolName`).
- `test_handler_denies` (parametrized): `shell` (with `full_command_text`), `url`, `mcp`, `memory`, unknown kind `"frobnicate"`, missing kind, kind `3`; writes to `../x`, `src/../../x`, an absolute path outside, `<session>_evil/x` (sibling prefix), `src/a.py:stream`, `C:foo` (Windows only), `GIT~1/config`, `.git/config`, `.GiT/hooks/pre-commit`, `.github/x.yml`, `pyproject.toml`, `NUL`, `con.py`, `src/x\x00.py`, `b"src/x.py"`, `5`, `""`, a write with no path field, `possible_paths` with one entry outside, `possible_paths` not a list; read outside; `custom-tool` with an unregistered name, a non-str name, and no name; a symlink inside pointing outside (skip when symlinks cannot be created).
- `test_handler_never_raises_and_fails_closed`: `build_session_permission_handler(x, [...])` for `"bad\x00path"`, `""`, `None`, `"ordinary-relative"`, a missing directory: constructs, denies write and read inside-looking paths, still approves a registered tool; a request whose attribute access raises is denied; a `tool_names` iterable that raises gives an empty set.
- `test_handler_result_uses_the_sdk_result_type`: with `sdk.PermissionRequestResult` monkeypatched to a recording dataclass and to `lambda **kw: dict(kw)` (the 0.1.30 TypedDict call shape), results carry `kind` `"approved"` / `"denied-by-rules"`.
- `test_seed_session_directory`: writes non-empty entries; keeps empty ones unwritten in the result; drops (and logs) `../x`, an absolute key outside, `x\x00`; normalizes `./src/a.py` and `src\\a.py` to `src/a.py`; raises `ValueError` on a missing directory.
- `test_execute_refuses_without_a_session_directory` (`cwd` `""` and `None`): `success is False`, the error names the session directory, `create_session` never called, discovery never runs.
- `test_execute_installs_the_session_policy`: the config's handler is callable, denies `shell` and an absolute write outside, approves a write inside `cwd` and every registered tool name from `config["tools"]`.
- `test_instruction_work_dir_is_separate_from_the_session_directory`: `discover_build_repository_instructions` (monkeypatched on `sdk`) receives `instruction_work_dir`; `working_directory` is `cwd`; omitting it keeps `cwd`.
- `test_scan_reports_only_changes_and_modify_blocks_carry_base`: the fake session creates one file, changes one seeded file, leaves one: exactly two blocks; the changed one is `modify` with `base` equal to the seeded text; the created one is `create` with no `base`.

Update (reason inline, do not delete): `tests/test_ad1200_repository_instruction_wire.py` `:866` -> the handler is callable, `is not approved`, denies `shell`, approves a write inside `repo` (the test name stays; BF-896 changes the permission policy on purpose). `:928-933` parametrized: for `"<work>"`, `"ordinary-relative"`, `"bad\x00path"`, keep the `working_directory == options[0]["cwd"] == cwd` and `system_message` assertions, and replace `is approved` with callable and `is not approved`. For `""` and `None`: `configs == []`, `options[0]["cwd"] == str(sdk._PROJECT_ROOT)`, `lifecycle == ["start", "stop"]`, `result.success is False` with the session-directory error. `tests/test_copilot_adapter.py:155,174` (`test_execute_timeout`, `test_execute_sdk_error`, skipped without the SDK): construct with `cwd=str(tmp_path)` so they still reach the path they test.

Focused gate: `pytest tests/test_bf896_session_permission_handler.py tests/test_ad1200_repository_instruction_wire.py tests/test_copilot_adapter.py tests/test_bf880_codebase_index_test_discovery.py -q -n 0`.

### M2 -- Sections 9-17 (`builder.py`, `code_reviewer.py`)

New `tests/test_bf896_executor_identity_and_blocks.py` (real temp git repo unless stated):
- `test_whole_file_modify_block_lands_and_commits`: premise 5 inverted. `{"path": "src/probos/a.py", "mode": "modify", "content": "x = 2\n", "base": <committed text>}`, `run_tests=False`: success, `files_modified == ["src/probos/a.py"]`, the branch's commit holds `x = 2`.
- `test_whole_file_modify_against_a_stale_base_is_refused` and `..._without_base_is_refused`: failed, the error names the path, no commit, file unchanged.
- `test_replacement_modify_is_unchanged` (control).
- `test_create_over_an_existing_file_is_a_modification_and_survives_a_failed_build`: create block with a syntax error over a tracked file: failed, file still exists, listed in `files_modified`, not `files_written`.
- `test_create_of_a_new_file_is_still_cleaned_up_on_failure` (control).
- `test_repair_create_over_an_existing_file_is_a_modification` (the `_repair_build` pattern of `tests/test_bf894_builder_write_boundary.py:182-191`).
- `test_identity_mismatch_at_entry_refuses_before_any_git_or_write`: pin, then swap `.git` for a gitfile naming a second repository; refused with "identity" in the error; no file written; no branch in either repository; `_run_git` (spied) received only `rev-parse --absolute-git-dir`.
- `test_identity_change_before_commit_refuses_and_runs_no_git_in_the_foreign_repo`: `run_tests=True` with `_run_targeted_tests` monkeypatched to swap `.git` and return `(True, "ok", [])`: no commit in either repository, no `checkout`/`branch -D` after the swap, created files unlinked.
- `test_no_pin_keeps_todays_behaviour`: without `expected_git_dir`, no `--absolute-git-dir` call (spy) and today's result.
- `test_repository_identity`: equal for two captures; changes when `.git` becomes a gitfile to another repo; `None` for a non-repo directory and a missing directory.
- `test_code_reviewer_renders_a_whole_file_modify` (no git).
- `test_native_visiting_path_does_not_seed_outside_its_temp_dir` (BF-844's `_FakeAdapter` pattern): an absolute target's original file is not rewritten.

Focused gate: `pytest tests/test_bf896_executor_identity_and_blocks.py tests/test_bf894_builder_write_boundary.py tests/test_bf844_visiting_builder_cleanup.py tests/test_builder_agent.py tests/test_builder_guardrails.py tests/test_builder_api.py tests/test_code_reviewer.py tests/test_ad521_swe_pipeline_separation.py tests/test_ad476_specialized_builders.py -q -n 0`.

### M3 -- Sections 18-21 (`build_dispatcher.py`)

New `tests/test_bf896_dispatcher_confinement_seam.py`: the real `BuildDispatcher(run_tests=False)._execute_build`, a real `BuildQueue`, `MagicMock(spec=WorktreeManager)` whose `create` returns `WorktreeInfo(path=<real temp git repo>)`, the real adapter on the fake SDK. The fake session reads `working_directory` and `on_permission_request` from its config, asks the handler before each write and writes only if approved.
- `test_a_queued_build_generates_off_the_worktree_and_commits_only_what_the_session_changed` (**the seam test the issue requires**): seeded `src/probos/a.py` (changed), `src/probos/b.py` (untouched), new `src/probos/new_mod.py`. Inside `send_and_wait`, after the writes: the worktree's bytes equal the pre-run snapshot and `git status --porcelain` is empty. After: status `reviewing`; `git diff --name-only main <result.branch_name>` is exactly the two files; `a.py` on the branch is the session's text; `files_modified == ["src/probos/a.py"]`, `files_written == ["src/probos/new_mod.py"]`; the session directory is gone.
- `test_the_session_cannot_write_into_the_worktree_or_run_a_shell`: verdicts the fake session recorded: an absolute write to `<repo>/src/probos/a.py` denied, a `shell` request denied, `standing_orders_lookup` approved; the worktree file unchanged.
- `test_a_git_alias_block_from_the_session_is_refused_at_the_write_boundary`: the session writes nothing and answers `===FILE: .git/hooks/pre-commit===...` (the adapter's fallback parse): failed, "Forbidden" in the error, no hook file, no commit.
- `test_an_identity_change_during_generation_is_refused_before_any_write`: the fake session (standing in for anything outside the handler) swaps the worktree's `.git` to a second repository: failed with "identity"; no worktree file changed; no new branch or commit in either repository.
- `test_the_session_directory_is_removed` (parametrized `success`, `adapter_failure` = no blocks, `client_raises` = fake client `start` raises; the path is recorded from the client's `options["cwd"]`).
- `test_the_session_directory_is_removed_on_cancellation`: `send_and_wait` awaits an event never set; cancel the task; `CancelledError` escapes; the directory is gone.
- `test_an_unpinnable_worktree_is_refused_before_the_adapter_is_built`: `repository_identity` -> `None`: failed, adapter class never called, no `probos_visiting_` directory created.

Update (reason inline): `tests/test_build_dispatcher.py` `test_execute_build_success` (:97) and `test_execute_build_adapter_failure` (:130) patch `probos.build_dispatcher.repository_identity` with `AsyncMock(return_value="/tmp/wt/.git")` (their `WorktreeInfo(path="/tmp/wt")` does not exist, and the route now fails closed on an unpinnable tree); the success test also asserts the adapter got `instruction_work_dir="/tmp/wt"` and a `cwd` that is not `/tmp/wt`.

Focused gate: `pytest tests/test_bf896_dispatcher_confinement_seam.py tests/test_build_dispatcher.py tests/test_bf896_session_permission_handler.py tests/test_bf896_executor_identity_and_blocks.py -q -n 0`.

Broad gate (main session, once, after review repairs are committed): `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf896 --receipt logs/gates/bf896.receipt.json`.

## What This Does NOT Change

`cognitive/builder_paths.py`; the dirty-tree guard; `routers/build.py` and every other `execute_approved_build` caller (no pin passed); the native path's temp-dir lifecycle and BF-844 cleanup; the scan's prefix filter and its `_parse_file_blocks` fallback; `start()`'s client cwd; `pyproject.toml`/`uv.lock`; no OS sandboxing, no new process launch, no new dependency.

## Tracking

- `PROGRESS.md`: one BF-896 line in the form of the BF-894/BF-895 lines (`PROGRESS.md:9-15`), with tests and this contract.
- `DECISIONS.md`: a `### BF-896 -- ...` entry in the BF-894/BF-895 form (`DECISIONS.md:48-67`) recording D1-D7.
- `docs/development/roadmap.md`: no row. Its Bug Tracker carries no BF-88x/89x rows (`Grep "BF-8[89][0-9]"`: no matches).

## Acceptance Criteria

1. The queued session's `working_directory` is a dispatcher-created temp directory that is removed on success, failure, exception and cancellation; repository instructions are still discovered from the worktree.
2. The session's permission handler is deny-by-default as in D1; `approve_all` is gone from `src/`.
3. The executor refuses a changed repository identity at entry (before any write) and before commit, when pinned; the queued route always pins.
4. Only files the session created or changed come back as blocks; a changed existing file lands (D2) or is refused visibly, never dropped.
5. Blocks reach the worktree only through `execute_approved_build`; the seam test proves generate -> `builder_write_refusal` -> commit on a real repository.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, `5a721bb2`)

```
build_dispatcher.py:143-218  _execute_build (read whole); :161-164 cwd=worktree_info.path; :182-188 execute_approved_build; :211-218 finally/callback
copilot_adapter.py:34  from copilot import CopilotClient, PermissionHandler, Tool, ToolResult
copilot_adapter.py:38-42  ToolResult fallback;  :124-147 _normalize_sdk_path; :150 class
copilot_adapter.py:161-177  __init__ (cwd: str = "", _instruction_work_dir = cwd, _cwd = cwd or _PROJECT_ROOT)
copilot_adapter.py:184-198  start (client_opts["cwd"] = self._cwd); :248-349 _build_mcp_tools (Tool(name=...))
copilot_adapter.py:484-488  started check; :506-511 session_config; :536-588 scan; :581-587 block shape (no replacements)
builder.py:14 import os; :1586 _run_git (subprocess.run, cwd=work_dir); :1652-1657 _git_checkout_main
builder.py:1957-1970 all_files ("" for a missing target); :1981-1990 localization replaces all_files
builder.py:2030-2124 native visiting path; :2036/:2041 the only uses of tmp_path
builder.py:2607-2630 signature/docstring; :2636 dirty check; :2677 builder_write_refusal; :2692-2695 modify; :2730-2734 create
builder.py:2863-2870 repair create; :2885-2886 step 5.5; :2933-2939 finally; :2941-2944 unlink written
code_reviewer.py:124-130  _format_changes modify rendering
builder_paths.py:60-101  builder_write_refusal lexical rules (.., absolute, ':', ~digit, device, .git, FORBIDDEN_PATHS, prefixes)
isolation.py:424  async def remove_workdir_off_loop(workdir: Path)
pyproject.toml:115-116 copilot = ["github-copilot-sdk>=0.1.30"]; uv.lock:1076-1077 version 0.1.32
SDK v0.1.32 types.py (fetched): PermissionRequestResult dataclass, kind default "denied-no-approval-rule-...", kinds incl. "approved", "denied-by-rules"; session.py: sync-or-awaitable handler(request, {"session_id"}); exception -> denial
SDK v0.1.30 types.py (fetched): PermissionRequest/PermissionRequestResult TypedDict(total=False); kinds incl. "approved", "denied-by-rules"
```

## Absence Verified (2026-10-16)

```
CLAIM: no caller executes the adapter without cwd
RUN:   Grep "CopilotBuilderAdapter\(" src/ scripts/
FOUND: build_dispatcher.py:161 (cwd given), builder.py:2046 (cwd=tmp_dir), commands_llm.py:110 (start/list_available_models/stop only, :110-116)
HOLDS: yes

CLAIM: only the adapter emits a modify block without "replacements"
RUN:   Grep '"mode": "modify"|mode="modify"|== "modify"' src/
FOUND: builder.py:1110 and :2372 (both with "replacements"), consumers builder.py:2684, :2848, code_reviewer.py:124; escalation.py:311 is unrelated
HOLDS: yes (plus copilot_adapter.py:582, the computed mode)

CLAIM: approve_all / on_permission_request appear nowhere else
RUN:   Grep 'approve_all|on_permission_request|PermissionHandler|PermissionRequestResult' src/ tests/
FOUND: copilot_adapter.py:34, :510; test_ad1200...:849, :866, :919, :931
HOLDS: yes (both tests updated in M1)

CLAIM: no test pins create-over-existing as files_written or the failed-build unlink
RUN:   Grep 'files_written' tests/ ; Grep 'Cleaned up untracked|created_path' tests/
FOUND: new-file paths only (test_builder_agent.py:1742, :2038; test_bf894...:168-208); second search: no matches
HOLDS: yes

CLAIM: no source-scan or golden test pins the changed text
RUN:   Grep 'copilot_adapter\.py|build_dispatcher\.py' tests/ ; Grep '_VISITING_BUILDER_INSTRUCTIONS' (test_copilot_adapter.py imports it and compares with itself)
FOUND: test_bf844...:4 (docstring), test_ad521...:124 (docstring), fixtures/file_durations.json
HOLDS: yes
```

## Prior Art and Blind Spots

- *Internal.* BF-894 (`DECISIONS.md:59-67`): its lexical rules are reused for handler writes, not re-implemented. BF-844: the cleanup pattern is reused. AD-1200: the fake-SDK pattern and `instruction_work_dir` semantics are kept.
- *External, bounded.* The SDK's own permission types (0.1.30 and 0.1.32, fetched). The SDK ships `approve_all` as a convenience and expects a real policy to be supplied; adopted. Whole-file compare-and-swap follows the conditional-write pattern (HTTP `If-Match`, RFC 9110 §13.1.1): adopted for D2, because it turns a silent drop into a visible refusal. OS sandboxing was considered and is out of scope by the issue.
- *Blind spots handled.* Excerpt seeds on the native path (the `base` refusal); create-over-existing unlinked on failure (D2); git hooks of a foreign repository run by cleanup (Section 16); seeding through an absolute key (D6); the agent losing its own tools under deny-by-default (registered names allowed).
