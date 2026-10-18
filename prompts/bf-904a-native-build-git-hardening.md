# BF-904a (Part of #1585): the native build pipeline's git calls run no repository code, and a failed or empty build leaves the operator's tree as it found it

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18

**Status:** ready to build. **Base:** `origin/main` at `cf08d4c9` (AD-1340 S2b complete). **Number:** BF-904a is the first half of BF-904 (#1585); no new AD or BF number. The PR says "Part of #1585", and #1585 stays open for BF-904b (items 2, 4, 6 and 7). Current highest: AD-1342 (`scripts/ad_ceiling.py`, GitHub issue titles); nothing is allocated here. **Shape:** one PR, three local commits (M1 = item 3, M2 = item 1, M3 = item 5, built in that order), one receipted broad gate. **Estimated tests:** 22 new test functions in three new files (M1: 8, M2: 7, M3: 6, plus one parametrised case set per file), and 18 existing assertions or helpers updated, each with its reason inline.

One-line summary: every git process of the pipeline starts with `-c core.hooksPath=<null device> -c core.fsmonitor=false`, a change in git's resolved config or hooks directory while the tests ran blocks every later git call, an unpinned build is pinned at entry when it can be; a build that does not commit writes back the bytes of every file it changed and returns to the ref it started from; a missing MODIFY target, an unmatched SEARCH block or a change list that changes nothing is a failure with a reason.

---

## Problem

Verified on this tree (`cf08d4c9`); every anchor below is unchanged from the issue (`28a3786b`) and from the options consult (`56e45c28`).

**Item 3: code under test can plant repository code that a later pipeline git command runs.**
- `_run_targeted_tests` runs model-written code with `cwd=work_dir` as the operator's user. That code can write `<git common dir>/hooks/*` or the repository config (`core.hooksPath`, `core.fsmonitor`, a `filter.<name>.clean` driver) without changing `rev-parse --absolute-git-dir`, so BF-896's identity check (`builder.py:2717`, `:3068`) passes, and `_git_add_and_commit` (`:1639`, called at `:3132`) runs what was planted.
- No pipeline git call sets an override (Absence Verified 1). The git launch sites are `_run_git` (`builder.py:1603-1605`, `["git", *args]`), the two launches in `_is_dirty_working_tree` (`:2616`, `:2628`, which start git themselves; `git status` refreshes the index and so runs a configured fsmonitor), and `WorktreeManager`'s `_run_git` (`worktree_manager.py:49-67`), which `adopt_commit` uses for `checkout`, `merge --ff-only` and `branch -D` in the tested worktree right after the tests (`:192`, `:196`, `:207`; dispatcher `build_dispatcher.py:252`). Correction to the issue: `_run_git` is not the only runner.
- `routers/build.py:412-419` (`_execute_build`) and `BuildPipeline` (`build_pipeline.py:89-96`) pass no `expected_git_dir`, and `execute_approved_build` does not pin when it is None (`builder.py:2717`). Correction to the issue: `build_dispatcher.py:182-221` DOES pin and pass it.

**Item 1: a failed build leaves the operator's tracked files modified and moves the checkout to `main`.**
- `original_branch = await _git_current_branch(work_dir)` (`builder.py:2728`) is never used. `_git_current_branch` runs `rev-parse --abbrev-ref HEAD`, which prints `HEAD` for a detached checkout, and falls back to `"main"` on an error (`:1619-1622`).
- The `finally` block (`:3147-3170`) always runs `_git_checkout_main` (`:1657-1662`, `checkout main`), ignores its return value, runs `branch -D` with its return value ignored, and unlinks only `written`. The bytes of `modified_files` are never restored, so their uncommitted edits follow the checkout to `main`. In a linked worktree whose `main` is checked out elsewhere, `checkout main` fails, and so does `branch -D` of the current branch.
- A commit that fails after `git add` (`:1644`) leaves the paths staged.
- `/api/build/resolve` depends on the defect: `abort` runs `_git_checkout_main` (`routers/build.py:109-118`), and `commit_override` commits `files_written + files_modified` in place (`:120-143`), which only worked by committing a modify build's leftover edits onto whatever branch the checkout was on; for created files it already failed, because the cleanup had deleted them.

**Item 5: unmatched SEARCH blocks and missing MODIFY targets are skipped silently.**
- A missing MODIFY target logs and `continue`s (`builder.py:2811-2817`); a SEARCH block not found logs and `continue`s (`:2838-2844`), so one file can be committed with only some of its replacements.
- If nothing applies, `written` and `modified_files` are empty, the tests are skipped, and `else: result.success = True` (`:3142-3143`) reports success with no commit.
- The repair loop skips a missing target (`:3017-3018`) and an unmatched block (`:3022`) silently too, so a partial repair can pass the tests and be committed.

## Solution overview

1. **M1 (item 3).** One constant, `HARDENED_GIT_CONFIG_ARGS`, in `execution/command_env.py` (the owner of what a spawned command starts with), is placed after `"git"` in all three builder launch sites and in every call of the worktree manager's `_run_git`. Just before the first test run the executor snapshots `git config --list --show-origin -z` and the repository's hooks directory (names and sha256, read in Python); after the fix loop it compares them. A change or a failed capture sets `git_unsafe`: no commit and no further git call. With no pin from the caller, the identity read at entry is pinned when readable.
2. **M2 (item 1).** The executor saves the bytes of every pre-existing file before its first write. A build that does not commit unstages its paths (only if `git add` ran), writes the bytes back, deletes the files it created, returns to the original ref (the branch from `symbolic-ref`, else the detached commit; neither refuses at entry), then deletes the build branch only if the return succeeded. Every step's result is checked and reported in `metadata["cleanup_errors"]`. The router's `abort` runs no git; `commit_override` re-runs the cached changes with `run_tests=False` and the override marker in the commit body.
3. **M3 (item 5).** A missing MODIFY target or an unmatched SEARCH block is a refusal in `validation_errors` (the file is not written); a repair with such a block is refused whole before any of it applies; a non-empty `file_changes` that changed nothing ends `success=False` with "No change applied: <paths>".

## Decisions (decided by the Architect under Delegated AD Execution Mode; the orchestrator records each on #1585; the Captain may overrule any afterwards)

Consult `56e45c28` decisions are adopted as written. The items marked **(new)** refine them after this tree was read; none widens scope.

- **D1. One PR, three commits, order item 3, item 1, item 5** (consult D4). M2 adds git calls after the tests (`reset`, `checkout`, `branch -D`) that are hardened from the start and branch on `git_unsafe`; M3 relies on M2's restore.
- **D2 (new). The constant lives in `execution/command_env.py`.** Builder and worktree manager both already import that module (`builder.py:30`, `worktree_manager.py:11`); a builder-owned constant would make the worktree manager import the cognitive layer. `execution/authority.py:792-801` keeps its literal copy (out of scope, unchanged).
- **D3 (new). Every call of the worktree manager's `_run_git` is hardened, not only `adopt_commit`'s.** The consult proposed a keyword parameter for `adopt_commit`'s calls. Unconditional hardening changes no signature (five test fakes replace that runner with `(*args, cwd=None)`: `test_worktree_manager.py:242,280,313`, `test_bf897...:440,459`, `test_bf896_dispatcher...:1249`), and `remove`'s `branch -D` and `create`'s `worktree add`, which run in the repository root, fire `reference-transaction` and `post-checkout` hooks from the common hooks directory the tested worktree shares.
- **D4 (new). The hooks directory is `<rev-parse --git-common-dir>/hooks`, not `rev-parse --git-path hooks`.** Under the override, `--git-path hooks` resolves to the null device (git substitutes `core.hooksPath`), so the consult's command would digest nothing. A configured `core.hooksPath` directory is not digested: a change to that setting shows in the config digest, and the override stops the directory from running.
- **D5 (new). The baseline is taken at the start of the test phase, compared once after the fix loop, and skipped when no tests ran** (no model code ran) **or when the identity is already lost** (no git in a foreign repository; keeps BF-896's `args_after_swap() == [IDENTITY_ARGS]` at `test_bf896_executor_identity_and_blocks.py:776`). Outside a repository the baseline has no hooks directory; a repository appearing during the tests changes the config listing, which catches it.
- **D6. A failed capture, before or after, counts as a change** (consult D2).
- **D7. One flag, `git_unsafe`, blocks every later git call**; `identity_lost` stays for its existing message.
- **D8. Restore by bytes, with no git** (consult D1, option 1). Saved with `setdefault` at the three write sites, only for paths not in `written`.
- **D9. Original ref.** `_git_current_branch` keeps its name (four harnesses patch it), returns `str | None` from `symbolic-ref -q --short HEAD`; new `_git_head_commit` (`rev-parse --verify -q HEAD^{commit}`); both None refuses at entry. `_git_checkout_main` becomes `_git_return_to(branch, commit, work_dir)`, which runs `checkout -q <branch> --` or `checkout -q --detach <commit> --`. Never `"main"`.
- **D10 (new). Restore is keyed on "no commit"; the error append is keyed on `result.success`.** A build with no commit is restored, as today's cleanup is keyed on `commit_hash`. A failed build gets `"\nCleanup incomplete: ..."` after its own error; a successful result (a commit, or an escalation result with none, `builder.py:3094-3096`) stays a success and logs at ERROR (`adopt_commit` checks out its own branch, `worktree_manager.py:179-180`).
- **D11. The build branch name is a local,** because `result = resolved` can replace `result` (`:3096`).
- **D12 (new). `commit_override` narrows to "lift the test gate only".** Re-executing through `execute_approved_build` keeps the syntax check, the write boundary, the BF-896 base check and M3's refusals, so a cached failure caused by any of those fails again. That is stronger, not weaker; the button and its request are unchanged, and the result arrives as `build_success` or `build_failure`. The marker is the description's first line, because the commit body takes `description[:200]` (`:3117`).
- **D13. `abort` runs no git** (consult D1).
- **D14 (new). M3 detail.** A main-loop file with an unmatched block is not written at all (`files_modified` stays clean). The repair pre-check is a helper, `_unapplied_repair_blocks`, which matches blocks in order against the text earlier blocks of the same response leave (creates parse first, `builder.py:2344-2399`), refuses a missing target, and leaves a target that exists but is not a regular file to the application, which raises as before (BF-898's disclosure test `test_bf898...:597` depends on that raise). The application's two skips become unreachable and are removed.
- **D15 (new). The consult's mutant 12 ("restore the fix loop's `if repl["search"] in mod` skip") is replaced.** After the pre-check it is an equivalent mutant (every block matches). The rows that replace it disable the pre-check and its two refusals.
- **D16. The `Syntax errors:` header stays** for refusals; `classify_build_failure` files them as `test_failure` (`:239-241`). BF-904b item 4 owns both. Every new refusal contains `; refused`, so item 4 can classify them.
- **D17. Hook-run proof on Windows.** Each runtime test that shows a hook or filter did not run first runs the same planted code with plain git (no override) in a sibling fixture and asserts the marker IS written. A pass therefore cannot be vacuous: if this machine's git does not run that hook, the premise fails loudly. These tests are skipped only when `git` is absent.
- **D18. Disclosed effect:** pipeline git calls no longer run the operator's local hooks (including git-lfs's `post-checkout`/`post-commit`/`post-merge`). Client hooks are not a ProbOS control; the receipted gate is (`scripts/run_test_gate.py:1137-1149` runs the phantom-API precheck itself). No hook framework is tracked (Absence Verified 9).

Captain: none. No security, governance or audit control is weakened; no config field; no irreversible action on the operator's tree.

## Section 0: Event types

None. BF-904a adds no `EventType`.

## Section 1 (M1): `src/probos/execution/command_env.py`

### 1a. `src/probos/execution/command_env.py`: the hardening constant
SEARCH:
```python
# config_models/operations.py holds literal twins of the four values above (it
# may not import probos); tests/test_bf890_command_env.py asserts they agree.

_ENV_NAME_SHAPE_RE = re.compile(ENV_NAME_SHAPE_PATTERN)
```
REPLACE:
```python
# config_models/operations.py holds literal twins of the four values above (it
# may not import probos); tests/test_bf890_command_env.py asserts they agree.

#: BF-904a (#1585): the options every git process of the build pipeline starts with. Code under
#: test runs as the operator's user in the tree it builds, so it can plant a hook or set
#: core.fsmonitor in the repository; neither may run at a later git command of the pipeline.
#: Nothing can be planted under the null device (the value execution/authority.py uses too).
HARDENED_GIT_CONFIG_ARGS: tuple[str, ...] = (
    "-c", f"core.hooksPath={os.devnull}",  # BF-904a: no repository hook runs
    "-c", "core.fsmonitor=false",  # BF-904a: no fsmonitor hook runs
)

_ENV_NAME_SHAPE_RE = re.compile(ENV_NAME_SHAPE_PATTERN)
```

## Section 2 (M1): `src/probos/cognitive/builder.py`

### 2a. `src/probos/cognitive/builder.py`: imports
SEARCH:
```python
import asyncio
import ast
import logging
```
REPLACE:
```python
import asyncio
import ast
import hashlib
import logging
```

SEARCH:
```python
from probos.execution.command_env import build_command_env
```
REPLACE:
```python
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS, build_command_env
```

### 2b. `src/probos/cognitive/builder.py`: `_run_git`
SEARCH:
```python
        result = subprocess.run(
            ["git", *args],
            env=build_command_env(_GIT_HOME_NAMES),
```
REPLACE:
```python
        result = subprocess.run(
            ["git", *HARDENED_GIT_CONFIG_ARGS, *args],  # BF-904a: no repository hook or fsmonitor runs
            env=build_command_env(_GIT_HOME_NAMES),
```

### 2c. `src/probos/cognitive/builder.py`: the safety snapshot (after `repository_identity`)
SEARCH:
```python
    try:
        return os.path.normcase(os.path.realpath(out))
    except (OSError, ValueError):
        return None
```
REPLACE:
```python
    try:
        return os.path.normcase(os.path.realpath(out))
    except (OSError, ValueError):
        return None


#: BF-904a (#1585): the listing of every config source git resolves for a tree (system, global,
#: the repository's shared config, config.worktree, every include). Its values never leave memory.
_GIT_CONFIG_LISTING_ARGS: tuple[str, ...] = ("config", "--list", "--show-origin", "-z")


@dataclass(frozen=True)
class _GitSafetySnapshot:
    """BF-904a (#1585): what git would run on its own in a tree, read before model code runs."""

    config: str  # the `git config --list --show-origin -z` listing
    hooks_dir: Path | None  # the repository's own hooks directory; None outside a repository
    hooks: tuple[tuple[str, str], ...]  # (entry name, sha256 of its bytes or "dir"), by name


def _hooks_listing(hooks_dir: Path | None) -> tuple[tuple[str, str], ...] | None:
    """BF-904a: each entry of *hooks_dir* with the sha256 of its bytes ("dir" for a directory).

    Read in Python, so no git runs. A missing directory is an empty listing; any other read
    failure is None, which the caller counts as a change.
    """
    if hooks_dir is None:
        return ()
    try:
        entries = sorted(hooks_dir.iterdir(), key=lambda entry: entry.name)
    except FileNotFoundError:
        return ()
    except OSError:
        return None
    listing: list[tuple[str, str]] = []
    try:
        for entry in entries:
            digest = "dir" if entry.is_dir() else hashlib.sha256(entry.read_bytes()).hexdigest()
            listing.append((entry.name, digest))
    except OSError:
        return None
    return tuple(listing)


def _config_change_names(before: str, after: str) -> str:
    """BF-904a: the sources and keys whose entries differ between two `-z` listings, never a value."""

    def entries(listing: str) -> set[tuple[str, str]]:
        fields = listing.split("\0")
        return {(fields[i], fields[i + 1]) for i in range(0, len(fields) - 1, 2)}

    differing = entries(before) ^ entries(after)
    names = sorted({origin + " " + entry.split("\n", 1)[0] for origin, entry in differing})
    shown = ", ".join(names[:10]) + (", ..." if len(names) > 10 else "")
    return f"({shown})" if shown else "(the listing changed)"


async def _git_safety_snapshot(work_dir: str) -> _GitSafetySnapshot | None:
    """BF-904a (#1585): the resolved git config and the hooks directory of *work_dir*, or None.

    None means the config listing or the hooks directory could not be read; the comparison
    after the tests counts that as a change.
    """
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir)
        if rc != 0:
            return None
        rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir)
    except (OSError, ValueError):
        return None
    # `--git-common-dir`, not `--git-path hooks`: under the core.hooksPath override the latter
    # names the null device. Outside a repository there is no hooks directory to watch; a
    # repository appearing during the tests changes the config listing instead.
    hooks_dir = Path(work_dir, common_dir, "hooks") if rc == 0 else None
    hooks = _hooks_listing(hooks_dir)
    if hooks is None:
        return None
    return _GitSafetySnapshot(config=config, hooks_dir=hooks_dir, hooks=hooks)


async def _git_safety_change(work_dir: str, before: _GitSafetySnapshot | None) -> str | None:
    """BF-904a (#1585): what changed since *before* in the config git resolves or the hooks directory.

    None when nothing changed. A capture that failed, before the tests or now, is a change: git
    is not run again when it cannot be shown to be as it was. The text names config sources and
    keys and hook file names only, never a value or a file's content.
    """
    if before is None:
        return "the git configuration or hooks directory could not be read before the tests"
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir)
    except (OSError, ValueError):
        rc, config = 1, ""
    if rc != 0:
        return "the git configuration could not be read after the tests"
    changes: list[str] = []
    if config != before.config:  # BF-904a: a filter, an include or any other config source changed
        changes.append("git config " + _config_change_names(before.config, config))
    hooks = _hooks_listing(before.hooks_dir)
    if hooks is None:
        changes.append(f"the hooks directory {before.hooks_dir} could not be read")
    elif hooks != before.hooks:  # BF-904a: a hook file appeared, changed or went away
        names = sorted({name for name, _digest in set(hooks) ^ set(before.hooks)})
        changes.append(f"hook files in {before.hooks_dir}: " + ", ".join(names))
    return "; ".join(changes) or None
```

If F2 (Section 4) finds that git's `-z` layout is not `origin NUL key LF value NUL`, fix `_config_change_names` to the layout `git help config` documents for `--show-origin` with `-z`; do not weaken the test. The decision to refuse uses string equality and does not depend on the parse.

### 2d. `src/probos/cognitive/builder.py`: both launches of `_is_dirty_working_tree`
SEARCH:
```python
        # First verify we're inside a git repo
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--git-dir",
            env=git_env,
```
REPLACE:
```python
        # First verify we're inside a git repo. BF-904a (#1585): both launches carry the
        # hardening options; `git status` refreshes the index, which runs a configured fsmonitor.
        proc = await asyncio.create_subprocess_exec(
            "git", *HARDENED_GIT_CONFIG_ARGS, "rev-parse", "--git-dir",
            env=git_env,
```

SEARCH:
```python
        proc = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain",
            env=git_env,
```
REPLACE:
```python
        proc = await asyncio.create_subprocess_exec(
            "git", *HARDENED_GIT_CONFIG_ARGS, "status", "--porcelain",
            env=git_env,
```

### 2e. `src/probos/cognitive/builder.py`: state of `execute_approved_build`
SEARCH:
```python
    result = BuildResult(success=False, spec=spec)
    identity_lost = False
```
REPLACE:
```python
    result = BuildResult(success=False, spec=spec)
    identity_lost = False
    # BF-904a (#1585): set when the identity changed, or git's config or hooks changed while the
    # tests ran; no further git command runs in this call, the commit included.
    git_unsafe = False
    git_tampered: str | None = None
    git_baseline: _GitSafetySnapshot | None = None
    tests_ran = False
```

### 2f. `src/probos/cognitive/builder.py`: the entry pin when the caller gave none
SEARCH:
```python
            return result

    # 1. Save current branch
    original_branch = await _git_current_branch(work_dir)
```
REPLACE:
```python
            return result

    # 0b. BF-904a (#1585): with no pin from the caller (the /api/build routes, BuildPipeline), pin
    # what the tree names now when it is readable, so the check before the commit covers every
    # caller. An unreadable identity keeps today's path: a real non-repository fails later.
    pinned_git_dir = expected_git_dir
    if pinned_git_dir is None:
        pinned_git_dir = await repository_identity(work_dir)  # BF-904a: pin what the tree names now, when readable

    # 1. Save current branch
    original_branch = await _git_current_branch(work_dir)
```

### 2g. `src/probos/cognitive/builder.py`: the baseline before the first test run
SEARCH:
```python
        if run_tests and (written or modified_files):
            all_changes = list(file_changes)  # track for fix prompt
```
REPLACE:
```python
        if run_tests and (written or modified_files):
            # BF-904a (#1585): what git would run on its own, read before any model code runs.
            git_baseline = await _git_safety_snapshot(work_dir)
            tests_ran = True
            all_changes = list(file_changes)  # track for fix prompt
```

### 2h. `src/probos/cognitive/builder.py`: the checks before the commit
SEARCH:
```python
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
```
REPLACE:
```python
        # 5.4. BF-896: the tests may have run arbitrary code; the tree must still
        # name the pinned repository before anything is committed (BF-904a: the
        # entry pin when the caller gave none).
        if pinned_git_dir is not None:
            current_git_dir = await repository_identity(work_dir)
            if current_git_dir != pinned_git_dir:
                identity_lost = True
                git_unsafe = True
                logger.error(
                    "BuilderAgent: repository identity changed during the build "
                    "(expected %r, found %r); refusing to commit",
                    pinned_git_dir, current_git_dir,
                )
        # 5.4b. BF-904a (#1585): a hook or a config entry (a filter driver, an include) the tests
        # planted would run at the next git command; any change blocks every later git call.
        if tests_ran and not identity_lost:
            git_tampered = await _git_safety_change(work_dir, git_baseline)
            if git_tampered is not None:
                git_unsafe = True  # BF-904a: a changed config or hooks directory blocks every later git call
                logger.error(
                    "BuilderAgent: git configuration or hooks changed while the tests ran (%s); "
                    "refusing to commit and running no further git command",
                    git_tampered,
                )

        # 5.5. Block commit if validation errors (syntax errors) exist
        if identity_lost:
            result.error = (
                "Repository identity changed during the build; refused before commit"
            )
            result.success = False
        elif git_tampered is not None:
            result.error = (
                f"Git configuration or hooks changed while the tests ran ({git_tampered}); "
                "refused before commit. No further git command was run, so the checkout is "
                f"left on branch {result.branch_name}; inspect the repository's config and "
                "hooks before running git there."
            )
            result.success = False
        elif validation_errors:
```

### 2i. `src/probos/cognitive/builder.py`: the `finally` block honours `git_unsafe` (interim; M2 rewrites it)
SEARCH:
```python
        # 7. Return to original branch. BF-896: not when the tree now names a
        # repository other than the pinned one (its hooks would run).
        if not identity_lost:
            await _git_checkout_main(work_dir)
        # Clean up build branch if no commit was made (failed build)
        if not result.commit_hash and result.branch_name:
            if not identity_lost:
```
REPLACE:
```python
        # 7. Return to original branch. BF-896: not when the tree now names a
        # repository other than the pinned one (its hooks would run). BF-904a: nor
        # when its config or hooks changed during the tests (git_unsafe).
        if not git_unsafe:
            await _git_checkout_main(work_dir)
        # Clean up build branch if no commit was made (failed build)
        if not result.commit_hash and result.branch_name:
            if not git_unsafe:
```

## Section 3 (M1): `src/probos/worktree_manager.py`

### 3a. `src/probos/worktree_manager.py`: import
SEARCH:
```python
from probos.execution.command_env import trusted_command_env
```
REPLACE:
```python
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS, trusted_command_env
```

### 3b. `src/probos/worktree_manager.py`: every git call of the manager
SEARCH:
```python
        """Run a git command and return (returncode, stdout, stderr)."""
        work_dir = cwd or str(self._repo_root)
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            env=trusted_command_env(),
```
REPLACE:
```python
        """Run a git command and return (returncode, stdout, stderr).

        BF-904a (#1585): every call starts with the hardening options. ``adopt_commit`` runs
        ``checkout``, ``merge --ff-only`` and ``branch -D`` in the tested worktree right after
        its tests, and ``remove`` and ``create`` run in the repository root, whose hooks
        directory that worktree shares; no repository hook or fsmonitor runs at any of them.
        """
        work_dir = cwd or str(self._repo_root)
        proc = await asyncio.create_subprocess_exec(
            "git",
            *HARDENED_GIT_CONFIG_ARGS,  # BF-904a: every worktree git call, adopt_commit's included
            *args,
            env=trusted_command_env(),
```

## Section 4 (M1): tests

### 4a. `tests/test_bf904a_git_hardening.py` (new)

Real git in temporary repositories under `tmp_path` with repo-local identity, `commit.gpgsign false` and `core.autocrlf false`; the helpers are copied from `test_bf896_executor_identity_and_blocks.py` (`_git`, `_init_repo`, `_plain_repo`, `_linked_worktree`, `_repoint`, `_refs`, `_repo_state`, `_tree`, `_GitSpy`) and `test_bf897...` (`_common_dir`), not imported. Module marker: `needs_git = pytest.mark.skipif(shutil.which("git") is None, ...)`; nothing else skips, on any OS. No mock of the git runner for the guarantees below; `_run_targeted_tests` is replaced by an async fake that runs the "model code" and returns `(True, "1 passed", [])` unless stated. The test's own git commands use plain `git` with no override (they are the premise controls). Every test asserts its premise first. No wall-clock ordering; no unbounded wait (every subprocess the tests start has `timeout=60`).

Hook and filter scripts: `_plant_hook(hooks_dir, name, marker)` writes `#!/bin/sh\ncat >/dev/null 2>&1\necho "$0" >> "<marker as posix path>"\n` with LF endings, then `os.chmod(path, 0o755)`. Git for Windows runs `#!/bin/sh` hooks with its bundled shell. Read the marker immediately after the call under test, before any other git command of the test.

| ID | Test | Asserts |
|---|---|---|
| H1 | `test_a_hook_present_before_the_build_never_runs` | Premise (sibling repo, plain git): with `pre-commit`, `prepare-commit-msg`, `commit-msg`, `post-commit`, `post-checkout`, `reference-transaction` planted, `git commit --allow-empty -m p` then `git checkout -q -b p` write the marker, and it names at least `pre-commit`, `post-commit`, `post-checkout`, `reference-transaction`. Probe: the same hooks planted in the probe repo's `_common_dir/hooks` before the build (marker absent); `execute_approved_build([create NEW, modify TARGET], run_tests=True)` with a passing fake: `success`, `commit_hash`, and the marker file does not exist. |
| H2 | `test_a_hook_planted_during_the_tests_is_refused_and_no_git_runs_after` | Build of `[create NEW]` in a plain repo, `run_tests=True`; the fake plants `post-checkout` and `reference-transaction` in `_common_dir/hooks` and sets `spy.swapped`. `success is False`; `"Git configuration or hooks changed while the tests ran"`, `"post-checkout"`, `"reference-transaction"` and `result.branch_name` are in `result.error`; `spy.args_after_swap() == [["rev-parse", "--absolute-git-dir"], ["config", "--list", "--show-origin", "-z"]]` (the entry pin's re-read, then the config read; no add, commit, checkout, reset or branch); the marker does not exist; plain `git symbolic-ref --short HEAD` names the build branch (left there, as the error says); `NEW` does not exist. |
| H3 | `test_a_failed_capture_counts_as_a_change` (parametrised `before`, `after`) | A wrapper around the real `_run_git` returns `(1, "", "fatal: bf904a")` for `["config", "--list", "--show-origin", "-z"]` on its first call (`before`) or after the fake ran (`after`). `success is False`, no `commit_hash`; error contains `"could not be read before the tests"` or `"could not be read after the tests"` respectively. Control first: the same build without the wrapper commits. |
| F1 | `test_an_fsmonitor_set_before_the_build_never_runs` | Premise (sibling repo, plain git): `git config core.fsmonitor <script>` then `git status` writes the marker (message on failure: "premise: this git runs a hook-path fsmonitor; report this, do not skip"). Probe: `core.fsmonitor` set to the same script in the probe repo before the build (so the baseline includes it and the comparison cannot catch it); the build commits; the marker does not exist. |
| F2 | `test_a_filter_planted_during_the_tests_is_refused_and_never_runs` | Premise (sibling repo): `git config filter.bf904a.clean "sh -c 'echo bf904a-filter-command >> <marker>; cat'"` plus `.git/info/attributes` holding `* filter=bf904a`, then plain `git add -- f.txt` writes the marker. Probe: the fake writes the same config entry (plain `git config`) and attributes file. `success is False`; `"filter.bf904a.clean"` is in `result.error`; `"bf904a-filter-command"` is NOT in `result.error` nor in any `caplog` record message (no config value leaves memory); the marker does not exist. |
| P1 | `test_an_unpinned_build_is_pinned_at_entry_and_refuses_a_rewritten_pointer` | `_linked_worktree` fixture; build in `wt` with NO `expected_git_dir`, `run_tests=True`. Control first (fresh fixture): the same build commits. Probe: the fake repoints `wt/.git` at `victim` and passes. `success is False`, `"identity" in result.error.lower()`; `_repo_state(victim)` unchanged; the commit count of `base` unchanged. |
| A1 | `test_adopt_commit_runs_no_repository_hook` | `WorktreeManager(repo_root=base, worktree_base=tmp_path/"wts")`, `await create("bf904a-adopt-0001")`; in the worktree, plain git creates `exec-bf904a` with one commit. Premise (sibling fixture built the same way): plain `git checkout <info.branch>`, `git merge --ff-only exec-bf904a`, `git branch -D exec-bf904a` with `post-checkout`, `post-merge`, `reference-transaction` planted write the marker. Probe: the same hooks planted in the common hooks dir; `await adopt_commit(...)` returns `(True, sha)`; the marker does not exist. |
| E1 | `test_every_git_process_of_the_pipeline_carries_both_options` | Capture `real_run = subprocess.run` and `real_exec = asyncio.create_subprocess_exec` BEFORE patching; build every fixture first; then install recorders on `builder_module.subprocess` `run` and `builder_module.asyncio` `create_subprocess_exec` that append the argv when its first element is `"git"` and call through (`subprocess.run` receives the argv as one list; `create_subprocess_exec` receives it as positional arguments). Run (a) a committed real build with `run_tests=True` and a passing fake, (b) a failed real build (a create with `def broken(:`), (c) the worktree manager's `create`, `adopt_commit` and `remove`. Premise: the verbs seen (the first argv element after the options) include `rev-parse`, `status`, `config`, `checkout`, `add`, `commit`, `branch`, `worktree`, `merge`. Every recorded argv has `argv[1:5] == list(HARDENED_GIT_CONFIG_ARGS)`, and `HARDENED_GIT_CONFIG_ARGS == ("-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false")`. Post-checks use `real_run`. |

### 4b. `tests/test_bf896_executor_identity_and_blocks.py`: the unpinned test pinned the item-3 gap
SEARCH:
```python
async def test_no_pin_keeps_todays_behaviour(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _plain_repo(tmp_path / "repo")
```
REPLACE:
```python
async def test_no_pin_is_pinned_at_entry_when_readable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # BF-904a (#1585): this test used to pin the gap ("without a pin repository_identity is never consulted").
    # A caller that gives no pin (the /api/build routes, BuildPipeline) now gets the identity read at entry and
    # compared again before the commit, so the unpinned path is guarded too.
    repo = _plain_repo(tmp_path / "repo")
```

SEARCH:
```python
    assert identity_calls == [], "without a pin repository_identity is never consulted"
    assert IDENTITY_ARGS not in [args for _swapped, args in spy.calls], "and no --absolute-git-dir command runs"
    assert spy.calls[0][1] == ["rev-parse", "--abbrev-ref", "HEAD"], "the executor still starts with the branch read, as before"
```
REPLACE:
```python
    assert identity_calls == [str(repo), str(repo)], "pinned at entry, compared again before the commit"
    assert spy.calls[0][1] == IDENTITY_ARGS, "the entry pin is the executor's first git command"
```

## Section 5 (M2): `src/probos/cognitive/builder.py`

### 5a. `src/probos/cognitive/builder.py`: the ref the build started from
SEARCH:
```python
async def _git_current_branch(work_dir: str) -> str:
    """Return the name of the current branch."""
    rc, out, _err = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], work_dir)
    return out if rc == 0 else "main"
```
REPLACE:
```python
async def _git_current_branch(work_dir: str) -> str | None:
    """BF-904a (#1585): the branch HEAD names, or None when HEAD is detached or unreadable.

    ``rev-parse --abbrev-ref HEAD`` printed ``HEAD`` for a detached checkout, and a failure
    fell back to ``main``; neither is the ref a failed build must return to.
    """
    rc, out, _err = await _run_git(["symbolic-ref", "-q", "--short", "HEAD"], work_dir)
    return out if rc == 0 and out else None  # BF-904a: never a guessed "main"


async def _git_head_commit(work_dir: str) -> str | None:
    """BF-904a: the commit a detached HEAD is at, or None when there is none."""
    rc, out, _err = await _run_git(["rev-parse", "--verify", "-q", "HEAD^{commit}"], work_dir)
    return out if rc == 0 and out else None
```

### 5b. `src/probos/cognitive/builder.py`: returning, and the cleanup helpers
SEARCH:
```python
async def _git_checkout_main(work_dir: str) -> tuple[bool, str]:
    """Switch back to main branch.  Returns (success, message)."""
    rc, out, err = await _run_git(["checkout", "main"], work_dir)
    if rc != 0:
        return False, err or out
    return True, "switched to main"
```
REPLACE:
```python
async def _git_return_to(branch: str | None, commit: str | None, work_dir: str) -> tuple[bool, str]:
    """BF-904a (#1585): check out the ref a build started from. Returns (success, detail).

    *branch* when the build started on one, otherwise *commit*, detached. Replaces
    ``_git_checkout_main``, which always switched to ``main``: from another branch that moved
    the operator, and in a linked worktree whose ``main`` is checked out elsewhere it failed.
    Never raises.
    """
    if branch is not None:
        args = ["checkout", "-q", branch, "--"]
    elif commit is not None:
        args = ["checkout", "-q", "--detach", commit, "--"]
    else:
        return False, "no branch or commit to return to"
    try:
        rc, out, err = await _run_git(args, work_dir)
    except (OSError, ValueError) as exc:
        return False, f"git checkout could not start ({type(exc).__name__})"
    if rc != 0:
        return False, (err or out or f"git checkout exited {rc}")[:300]
    return True, branch if branch is not None else str(commit)


async def _cleanup_git(args: list[str], work_dir: str) -> str | None:
    """BF-904a: one cleanup git command; its failure as text, or None on success. Never raises."""
    try:
        rc, out, err = await _run_git(args, work_dir)
    except (OSError, ValueError) as exc:
        return f"git {args[0]} could not start ({type(exc).__name__})"
    if rc != 0:
        return f"git {args[0]} exited {rc}: {(err or out)[:300]}"
    return None


def _restore_pre_build_files(work_dir: str, originals: dict[str, bytes], created: list[str]) -> list[str]:
    """BF-904a (#1585): put the tree back as the build found it, with no git.

    Writes each saved file back byte for byte, then deletes each file the build created and its
    emptied parent directories. Runs no git, so no filter or attribute planted in the tree runs.
    Returns one message per path it could not put back (names only); never raises.
    """
    errors: list[str] = []
    root = Path(work_dir)
    for rel, data in originals.items():
        try:
            (root / rel).write_bytes(data)
        except OSError as exc:
            errors.append(f"could not restore {rel} ({type(exc).__name__})")
    for created_path in created:
        full = root / created_path
        if not full.exists():
            continue
        try:
            full.unlink()
        except OSError as exc:
            errors.append(f"could not delete {created_path} ({type(exc).__name__})")
            continue
        logger.info("Cleaned up untracked file from failed build: %s", created_path)
        # Remove empty parent dirs up to work_dir
        parent = full.parent
        try:
            while parent != root and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
        except OSError:
            pass  # Directory not empty or permission issue
    return errors
```

### 5c. `src/probos/cognitive/builder.py`: read the original ref, or refuse
SEARCH:
```python
    # 1. Save current branch
    original_branch = await _git_current_branch(work_dir)

    # 1a. Verify clean working tree (prevent contaminating build branch)
```
REPLACE:
```python
    # 1. BF-904a (#1585): the ref a build returns to, read before anything changes: the
    # branch, or the commit of a detached HEAD. A tree with neither is refused here, before
    # the build branch exists; it is never sent to a guessed "main".
    original_branch = await _git_current_branch(work_dir)
    original_commit = None if original_branch is not None else await _git_head_commit(work_dir)
    if original_branch is None and original_commit is None:
        result.error = (
            "Cannot read the checkout's current branch or commit, so a failed build could "
            "not return to it; refused before any write"
        )
        return result

    # 1a. Verify clean working tree (prevent contaminating build branch)
```

### 5d. `src/probos/cognitive/builder.py`: the build branch, the saved bytes, the add flag
SEARCH:
```python
    result.branch_name = _sanitize_branch_name(branch)

    written: list[str] = []
    modified_files: list[str] = []
    validation_errors: list[str] = []
    try:
```
REPLACE:
```python
    result.branch_name = _sanitize_branch_name(branch)
    # BF-904a: a local, because the escalation hook's result can replace ``result``.
    build_branch = result.branch_name

    written: list[str] = []
    modified_files: list[str] = []
    validation_errors: list[str] = []
    # BF-904a (#1585): the bytes of every file that existed before this build, saved before its
    # first write (setdefault keeps that first copy); a build that does not commit writes them back.
    originals: dict[str, bytes] = {}
    add_attempted = False
    try:
```

### 5e. `src/probos/cognitive/builder.py`: save before the first write (three sites)
SEARCH:
```python
                if modified != original:
                    _check_sealed_path(path, runtime)
                    path.write_text(modified, encoding="utf-8")
```
REPLACE:
```python
                if modified != original:
                    _check_sealed_path(path, runtime)
                    if change["path"] not in written:
                        originals.setdefault(change["path"], path.read_bytes())  # BF-904a: saved before the first write
                    path.write_text(modified, encoding="utf-8")
```

SEARCH:
```python
            path.parent.mkdir(parents=True, exist_ok=True)
            _check_sealed_path(path, runtime)
            pre_existing = path.exists() and change["path"] not in written
            path.write_text(change["content"], encoding="utf-8")
```
REPLACE:
```python
            path.parent.mkdir(parents=True, exist_ok=True)
            _check_sealed_path(path, runtime)
            pre_existing = path.exists() and change["path"] not in written
            if pre_existing:
                originals.setdefault(change["path"], path.read_bytes())  # BF-904a: a create over an existing file saves it first
            path.write_text(change["content"], encoding="utf-8")
```

SEARCH:
```python
                        path = Path(work_dir) / change["path"]
                        before_fix = path.read_bytes() if path.is_file() else None
                        try:
```
REPLACE:
```python
                        path = Path(work_dir) / change["path"]
                        before_fix = path.read_bytes() if path.is_file() else None
                        if before_fix is not None and change["path"] not in written:
                            originals.setdefault(change["path"], before_fix)  # BF-904a: a repair saves a file the build did not create
                        try:
```

### 5f. `src/probos/cognitive/builder.py`: remember that `git add` ran
SEARCH:
```python
                ok, sha = await _git_add_and_commit(
                    written + modified_files, commit_msg, work_dir,
                )
```
REPLACE:
```python
                add_attempted = True  # BF-904a: a failed commit may leave these paths staged
                ok, sha = await _git_add_and_commit(
                    written + modified_files, commit_msg, work_dir,
                )
```

### 5g. `src/probos/cognitive/builder.py`: the `finally` block
SEARCH:
```python
    finally:
        # 7. Return to original branch. BF-896: not when the tree now names a
        # repository other than the pinned one (its hooks would run). BF-904a: nor
        # when its config or hooks changed during the tests (git_unsafe).
        if not git_unsafe:
            await _git_checkout_main(work_dir)
        # Clean up build branch if no commit was made (failed build)
        if not result.commit_hash and result.branch_name:
            if not git_unsafe:
                logger.info("Cleaning up failed build branch '%s'", result.branch_name)
                await _run_git(["branch", "-D", result.branch_name], work_dir)
            # Delete files created during the failed build (untracked on main)
            for created_path in written:
                full = Path(work_dir) / created_path
                if full.exists():
                    full.unlink()
                    logger.info("Cleaned up untracked file from failed build: %s", created_path)
                    # Remove empty parent dirs up to work_dir
                    parent = full.parent
                    try:
                        while parent != Path(work_dir) and not any(parent.iterdir()):
                            parent.rmdir()
                            parent = parent.parent
                    except OSError:
                        pass  # Directory not empty or permission issue
```
REPLACE:
```python
    finally:
        # 7. BF-904a (#1585): put the operator's checkout back as the build found it. A build
        # with no commit: unstage (only if `git add` ran), write the saved bytes back, delete
        # the files it created, return to the ORIGINAL ref, and only then delete the build
        # branch. A committed build only returns. BF-896/BF-904a: when git is unsafe (identity
        # lost, config or hooks changed) no git runs at all.
        cleanup_errors: list[str] = []
        restore_tree = not result.commit_hash
        if restore_tree:
            if add_attempted and not git_unsafe:
                unstaged = await _cleanup_git(["reset", "-q", "--", *written, *modified_files], work_dir)  # BF-904a: unstage before the restore
                if unstaged is not None:
                    cleanup_errors.append(unstaged)
            cleanup_errors.extend(_restore_pre_build_files(work_dir, originals, written))
        if git_unsafe:
            cleanup_errors.append(
                f"no git command was run after the tests, so the checkout is left on branch {build_branch}"
            )
        else:
            returned, detail = await _git_return_to(original_branch, original_commit, work_dir)
            if not returned:  # BF-904a: a failed return keeps the build branch and is reported
                cleanup_errors.append(
                    f"could not return to {original_branch or original_commit}: {detail}; "
                    f"branch {build_branch} kept"
                )
            elif restore_tree:
                logger.info("Cleaning up failed build branch '%s'", build_branch)
                deleted = await _cleanup_git(["branch", "-D", build_branch], work_dir)
                if deleted is not None:
                    cleanup_errors.append(deleted)
        if cleanup_errors:
            result.metadata["cleanup_errors"] = cleanup_errors
            if result.success:
                # A successful result stays one: a commit is on the build branch, and
                # adopt_commit checks out its own branch (worktree_manager.py).
                logger.error("BuilderAgent: build cleanup incomplete: %s", "; ".join(cleanup_errors))
            else:
                result.error = (result.error or "Build failed") + "\nCleanup incomplete: " + "; ".join(cleanup_errors)
```

## Section 6 (M2): `src/probos/routers/build.py`

### 6a. `src/probos/routers/build.py`: import and marker
SEARCH:
```python
import logging
import time
from pathlib import Path
```
REPLACE:
```python
import dataclasses
import logging
import time
from pathlib import Path
```

SEARCH:
```python
    "and its branch is kept for delivery."
)
```
REPLACE:
```python
    "and its branch is kept for delivery."
)
#: BF-904a (#1585): the first line of a commit_override build's commit body.
OVERRIDE_MARKER = "[Test gate overridden by Captain]"
```

### 6b. `src/probos/routers/build.py`: `abort` and `commit_override`
SEARCH:
```python
    # BF-897: abort and commit_override run git in work_dir, and a retry executes
    # there; the guard refuses the checkout ProbOS runs from (it compares locations,
    # see operator_checkout_refusal).
```
REPLACE:
```python
    # BF-897: commit_override and a retry execute in work_dir (BF-904a: abort runs no
    # git); the guard refuses the checkout ProbOS runs from (it compares locations,
    # see operator_checkout_refusal).
```

SEARCH:
```python
    if req.resolution == "abort":
        from probos.cognitive.builder import _git_checkout_main
        await _git_checkout_main(work_dir)
        del _pending_failures[req.build_id]
        runtime.emit_event(EventType.BUILD_RESOLVED, {
            "build_id": req.build_id,
            "resolution": "abort",
            "message": "Build aborted. Returned to main branch.",
        })
        return {"status": "ok", "resolution": "abort"}

    elif req.resolution == "commit_override":
        from probos.cognitive.builder import _git_add_and_commit
        report = cached["report"]
        all_files = report.files_written + report.files_modified
        if not all_files:
            return {"status": "error", "message": "No files to commit."}
        commit_msg = (
            f"{spec.title}"
            + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
            + "\n\n[Test gate overridden by Captain]"
            + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
        )
        ok, sha = await _git_add_and_commit(all_files, commit_msg, work_dir)
        del _pending_failures[req.build_id]
        if ok:
            runtime.emit_event(EventType.BUILD_RESOLVED, {
                "build_id": req.build_id,
                "resolution": "commit_override",
                "message": f"Committed with test gate override. Commit: {sha}",
                "commit": sha,
            })
            return {"status": "ok", "resolution": "commit_override", "commit": sha}
        else:
            return {"status": "error", "message": f"Commit failed: {sha}"}
```
REPLACE:
```python
    if req.resolution == "abort":
        # BF-904a (#1585): runs no git. The failed build already wrote its files back, deleted
        # the ones it created and returned to the ref it started from (execute_approved_build).
        del _pending_failures[req.build_id]
        runtime.emit_event(EventType.BUILD_RESOLVED, {
            "build_id": req.build_id,
            "resolution": "abort",
            "message": "Build aborted. Its changes were discarded when it failed.",
        })
        return {"status": "ok", "resolution": "abort"}

    elif req.resolution == "commit_override":
        # BF-904a (#1585): the failed build restored the checkout, so nothing is left to commit
        # in place (the old body committed leftover edits onto whatever branch was checked out,
        # and failed for created files, which had been deleted). The cached changes run again
        # through execute_approved_build with the test gate off, every other guard on, and the
        # override named in the commit body. The outcome arrives as build_success or
        # build_failure, as for the retry paths.
        if not file_changes:
            return {"status": "error", "message": "No files to commit."}
        override_spec = dataclasses.replace(
            spec,
            description=OVERRIDE_MARKER + (f"\n\n{spec.description}" if spec.description else ""),
        )
        del _pending_failures[req.build_id]
        runtime.emit_event(EventType.BUILD_RESOLVED, {
            "build_id": req.build_id,
            "resolution": "commit_override",
            "message": "Re-running the build with the test gate overridden by the Captain.",
        })
        track_task(
            _execute_build(req.build_id, file_changes, override_spec, work_dir, runtime, run_tests=False),  # BF-904a: the test gate is the only guard the override lifts
            name=f"build-resolve-{req.build_id}",
        )
        return {"status": "ok", "resolution": "commit_override", "build_id": req.build_id}
```

### 6c. `src/probos/routers/build.py`: `_execute_build` takes `run_tests`
SEARCH:
```python
    work_dir: str,
    rt: Any,
) -> None:
    """Background execution of approved build."""
```
REPLACE:
```python
    work_dir: str,
    rt: Any,
    run_tests: bool = True,
) -> None:
    """Background execution of approved build.

    BF-904a (#1585): *run_tests* is False only for the Captain's ``commit_override``.
    """
```

SEARCH:
```python
            run_tests=True,
            llm_client=getattr(rt, "llm_client", None),
```
REPLACE:
```python
            run_tests=run_tests,  # BF-904a: False only for the Captain's commit_override
            llm_client=getattr(rt, "llm_client", None),
```

## Section 7 (M2): tests

### 7a. `tests/test_bf904a_failed_build_restore.py` (new)

Same fixture rules as 4a (helpers copied). Seed: `TARGET = "src/probos/a.py"` (`x = 1\n`), `OTHER = "src/probos/other.py"` (`y = 1\n`); `NEW = "src/probos/newpkg/fresh.py"`, `BAD = "src/probos/bad.py"`, `BROKEN = "def broken(:\n"`. The failing change list `FAILING = [modify TARGET (SEARCH "x = 1" REPLACE "x = 2"), create OTHER "y = 2\n" (a create over an existing file), create NEW "ok = 1\n", create BAD BROKEN]`. `_state(tree)` returns `(git status --porcelain, git symbolic-ref -q --short HEAD or the sha of git rev-parse HEAD, sorted local branches with their tips, _tree(tree))`, all read with plain git.

| ID | Test | Asserts |
|---|---|---|
| R1 | `test_a_failed_build_leaves_the_tree_and_head_as_they_were` parametrised: `other-branch` (repo on `captain-work`, one commit ahead of `main`), `detached` (`git checkout -q --detach HEAD`), `linked-worktree-main-elsewhere` (base repo on `main`; `git worktree add -b wt-bf904a <wt> main`; the build runs in `wt`), `fix-loop-edit` (repo on `main`; build `[create NEW]` with `run_tests=True`, a fake that always returns `(False, "1 failed", ["tests/test_x.py"])`, `max_fix_attempts=1`, and a fake model whose repair is `===MODIFY: OTHER===` SEARCH `y = 1` REPLACE `y = 3`), `commit-failed-after-add` (repo on `main`; `[modify TARGET, create NEW]` with `run_tests=False`; `_git_add_and_commit` replaced by a fake that runs the real `_run_git(["add", "--", *files], work_dir)` and returns `(False, "bf904a: commit refused")`). | Premise per case: the starting HEAD is as named (for `linked`, plain `git worktree list` shows `main` checked out in base); for `fix-loop-edit`, the fake model received one repair request and `metadata["fix_loop_files"] == [OTHER]`; for `commit-failed-after-add`, plain `git diff --cached --name-only` inside the fake, after the add, lists TARGET and NEW. Then `success is False` and `_state(tree)` after equals `_state(tree)` before (porcelain, HEAD ref, branches and every byte). For `linked`, base's `_state` is unchanged too. |
| R2 | `test_a_failed_return_is_reported_and_keeps_the_build_branch` | `_git_return_to` replaced by a wrapper that calls the real one (premise: it returned `(True, ...)`) and then returns `(False, "bf904a: simulated return failure")`. Build `FAILING` on `main`. `result.error.startswith("Syntax errors")` (the build's own error first); `"\nCleanup incomplete: "` and `"simulated return failure"` in `result.error`; `metadata["cleanup_errors"]` has exactly one entry, which names `result.branch_name` and "kept"; `result.branch_name` is still a local branch; every file's bytes equal the seed. |
| R2b | `test_a_committed_build_that_cannot_return_stays_a_success_and_logs` | The same wrapper; build `[create NEW]` (commits). `success is True`, `commit_hash` set, `metadata["cleanup_errors"]` non-empty, and `caplog` has an ERROR record containing "build cleanup incomplete". |
| R3 | `test_a_committed_build_returns_to_the_branch_it_started_on` | Repo on `captain-work`; `[create NEW]` commits; plain `git symbolic-ref --short HEAD == "captain-work"`; the commit is on `result.branch_name` (`git show <branch>:NEW == "ok = 1\n"`). |
| R4 | `test_a_tree_with_neither_branch_nor_commit_is_refused_before_any_write` | A plain directory (premise: `git rev-parse --git-dir` fails there). A `_GitSpy` on `_run_git`. `result.error.startswith("Cannot read the checkout's current branch or commit")`; no spy call starts with `["checkout", "-b"]`; nothing written. |
| R5 | `test_abort_runs_no_git_and_leaves_the_checkout` | Import `probos.api` first (it owns the failure cache); seed `_pending_failures[ID]` (with `monkeypatch.setitem`) for a repo on `captain-work`; recorders as in E1 (call through). `await resolve_build(BuildResolveRequest(build_id=ID, resolution="abort"), runtime=rt, track_task=capture)` with `rt` a `MagicMock`. Response `{"status": "ok", "resolution": "abort"}`; no git argv recorded; HEAD still `captain-work`; `ID not in _pending_failures`; `rt.emit_event` called once with the `BUILD_RESOLVED` type and a message without "main branch". |
| R6 | `test_commit_override_reruns_the_cached_changes_without_the_test_gate` | Repo on `captain-work`; seed the cache with `file_changes=[create NEW "ok = 1\n"]`, `spec` a build spec titled `bf904a override` with description `d`, `work_dir` the repo, `report` an empty failure report. `_run_targeted_tests` replaced by an `AsyncMock`. `track_task` captures the coroutine. Response `{"status": "ok", "resolution": "commit_override", "build_id": ID}`; then `await` the captured coroutine with `rt.llm_client = None`. The targeted-test mock was never awaited; the emitted event types are, in order, `BUILD_RESOLVED`, then `BUILD_PROGRESS` (`_execute_build`'s "writing" step), then `BUILD_SUCCESS`, and no `BUILD_FAILURE`; the success event's `branch` has a commit whose message (`git log -1 --format=%B <branch>`) contains `[Test gate overridden by Captain]` on the line after the title's blank line, and whose tree holds NEW; HEAD is back on `captain-work`; porcelain is empty. |

### 7b. `tests/test_bf894_builder_write_boundary.py`: the renamed return helper
SEARCH:
```python
def _no_real_git(stack: ExitStack) -> AsyncMock:
    for name, value in (("_git_current_branch", "main"), ("_is_dirty_working_tree", False),
                        ("_git_create_branch", (True, "builder-bf894")), ("_git_checkout_main", (True, "ok")),
```
REPLACE:
```python
def _no_real_git(stack: ExitStack) -> AsyncMock:
    # BF-904a (#1585): _git_checkout_main became _git_return_to (it returns to the ref the build started from).
    for name, value in (("_git_current_branch", "main"), ("_is_dirty_working_tree", False),
                        ("_git_create_branch", (True, "builder-bf894")), ("_git_return_to", (True, "ok")),
```

### 7c. `tests/test_bf897_build_pipeline_scale_and_checkout.py`: the renamed helper, and abort runs no git
SEARCH:
```python
        self.checkout_main = AsyncMock(return_value=(True, "switched to main"))
        self.current_branch = AsyncMock(return_value="main")
        self.add_and_commit = AsyncMock(return_value=(True, "abc1234"))
        self.is_dirty = AsyncMock(return_value=False)
        self.run_git = AsyncMock(return_value=(0, "", ""))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, fake in (
            ("_git_create_branch", self.create_branch),
            ("_git_checkout_main", self.checkout_main),
```
REPLACE:
```python
        # BF-904a (#1585): _git_checkout_main became _git_return_to (the ref the build started from).
        self.return_to = AsyncMock(return_value=(True, "main"))
        self.current_branch = AsyncMock(return_value="main")
        self.add_and_commit = AsyncMock(return_value=(True, "abc1234"))
        self.is_dirty = AsyncMock(return_value=False)
        self.run_git = AsyncMock(return_value=(0, "", ""))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, fake in (
            ("_git_create_branch", self.create_branch),
            ("_git_return_to", self.return_to),
```

SEARCH:
```python
    assert _out(linked, "rev-parse", "--abbrev-ref", "HEAD") == "main", "the abort did not run in the worktree"
```
REPLACE:
```python
    # BF-904a (#1585): abort runs no git (the failed build already returned to its ref), so the worktree stays put.
    assert _out(linked, "rev-parse", "--abbrev-ref", "HEAD") == "wt-resolve", "the abort ran git in the worktree"
```

### 7d. `tests/test_bf898_fix_loop_grader_protection.py`: the renamed helper, and restored bytes
SEARCH:
```python
        self.checkout_main = AsyncMock(return_value=(True, "switched to main"))
        self.current_branch = AsyncMock(return_value="main")
        self.add_and_commit = AsyncMock(return_value=(True, "abc1234"))
        self.is_dirty = AsyncMock(return_value=False)
        self.run_git = AsyncMock(return_value=(0, "", ""))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, fake in (
            ("_git_create_branch", self.create_branch),
            ("_git_checkout_main", self.checkout_main),
```
REPLACE:
```python
        # BF-904a (#1585): _git_checkout_main became _git_return_to (the ref the build started from).
        self.return_to = AsyncMock(return_value=(True, "main"))
        self.current_branch = AsyncMock(return_value="main")
        self.add_and_commit = AsyncMock(return_value=(True, "abc1234"))
        self.is_dirty = AsyncMock(return_value=False)
        self.run_git = AsyncMock(return_value=(0, "", ""))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name, fake in (
            ("_git_create_branch", self.create_branch),
            ("_git_return_to", self.return_to),
```

SEARCH:
```python
    assert foo.read_text(encoding="utf-8") == "x = 2\n", "premise: the earlier block was applied before the error"
```
REPLACE:
```python
    # BF-904a (#1585): the disclosure below is the evidence the earlier block wrote foo.py; the failed build restores it.
    assert foo.read_text(encoding="utf-8") == _FOO_TEXT, "the failed build writes foo.py's original bytes back"
```

SEARCH:
```python
    assert foo.read_text(encoding="utf-8") == "x = 2\n", "the write happened before the error"
```
REPLACE:
```python
    # BF-904a (#1585): the disclosure below shows the repair wrote foo.py; the failed build writes the original back.
    assert foo.read_text(encoding="utf-8") == _FOO_TEXT, "the failed build restores foo.py"
```

SEARCH:
```python
    assert foo.read_text(encoding="utf-8") == "", "the file was truncated by the failed write"
```
REPLACE:
```python
    # BF-904a (#1585): foo_writes shows the truncating write happened; the failed build writes the original back.
    assert foo.read_text(encoding="utf-8") == _FOO_TEXT, "the truncated file is restored"
```

### 7e. `tests/test_bf896_executor_identity_and_blocks.py`: entry refusal and restored bytes
SEARCH:
```python
    assert unpinned.success is False and unpinned.error.startswith("Failed to create branch"), unpinned.error
```
REPLACE:
```python
    # BF-904a (#1585): a tree with neither a branch nor a commit is now refused at entry, before the branch.
    assert unpinned.success is False and unpinned.error.startswith("Cannot read the checkout's current branch or commit"), unpinned.error
```

SEARCH:
```python
    assert (repo / TARGET).exists(), "a tracked file the build overwrote must survive the failed-build cleanup"
```
REPLACE:
```python
    # BF-904a (#1585): stronger than "survives": the failed build writes the file's bytes back.
    assert (repo / TARGET).read_bytes() == ORIGINAL.encode("utf-8"), "a tracked file the build overwrote is restored"
```

SEARCH:
```python
    assert (repo / TARGET).read_text(encoding="utf-8").strip() == "x = 3", "the repair was written"
```
REPLACE:
```python
    # BF-904a (#1585): the repair wrote TARGET (files_modified above); the failed build writes the original back.
    assert (repo / TARGET).read_bytes() == ORIGINAL.encode("utf-8"), "the repaired file is restored"
```

### 7f. `tests/test_builder_agent.py`: four patch sites (prose; the four lines are identical, so no SEARCH block)

In `TestEscalationHook` (`test_builder_agent.py:3062`, `:3092`, `:3123`, `:3145`), replace each `patch("probos.cognitive.builder._git_checkout_main")` with `patch("probos.cognitive.builder._git_return_to", return_value=(True, "main"))`, and add one comment above the first: `# BF-904a (#1585): _git_checkout_main became _git_return_to; its (ok, detail) result is now read.` A bare patch would return a mock that cannot be unpacked.

## Section 8 (M3): `src/probos/cognitive/builder.py`

### 8a. `src/probos/cognitive/builder.py`: a missing MODIFY target is a refusal
SEARCH:
```python
            if change["mode"] == "modify":
                if not path.exists():
                    logger.warning(
                        "BuilderAgent: MODIFY target %s does not exist, skipping",
                        change["path"],
                    )
                    continue
```
REPLACE:
```python
            if change["mode"] == "modify":
                if not path.exists():
                    # BF-904a (#1585): a refusal that blocks the commit, never a silent skip.
                    validation_errors.append(f"MODIFY target {change['path']} does not exist; refused")
                    continue
```

### 8b. `src/probos/cognitive/builder.py`: an unmatched SEARCH block is a refusal, and its file is not written
SEARCH:
```python
                for i, repl in enumerate(change.get("replacements", [])):
                    search_text = repl["search"]
                    replace_text = repl["replace"]

                    if search_text not in modified:
                        logger.warning(
                            "BuilderAgent: SEARCH block %d not found in %s, "
                            "skipping this replacement",
                            i, change["path"],
                        )
                        continue

                    # Replace first occurrence only
                    modified = modified.replace(search_text, replace_text, 1)

                if modified != original:
```
REPLACE:
```python
                unmatched = False
                for i, repl in enumerate(change.get("replacements", [])):
                    search_text = repl["search"]
                    replace_text = repl["replace"]

                    if search_text not in modified:
                        # BF-904a (#1585): recorded (names the block and the file, never its text); the
                        # file is not written, the commit is blocked and the tree is restored.
                        validation_errors.append(f"SEARCH block {i} not found in {change['path']}; refused")
                        unmatched = True
                        continue

                    # Replace first occurrence only
                    modified = modified.replace(search_text, replace_text, 1)
                if unmatched:
                    continue  # BF-904a: a file with an unmatched block is not written at all

                if modified != original:
```

### 8c. `src/probos/cognitive/builder.py`: the repair pre-check (before `_check_sealed_path`)
SEARCH:
```python
def _check_sealed_path(target_path: "Path", runtime: "ProbOSRuntime | None") -> None:
```
REPLACE:
```python
def _unapplied_repair_blocks(fix_changes: list[dict[str, Any]], work_dir: str) -> list[str]:
    """BF-904a (#1585): a refusal for each repair MODIFY block that cannot apply as written.

    The blocks are checked in order against the text the earlier blocks of the same response
    leave (the parser puts creates first), so the check agrees with the application. A target
    that exists but is not a regular file is left to the application, which raises as before
    (BF-898 keeps its disclosure). Names the block and the file, never their text.
    """
    refusals: list[str] = []
    texts: dict[str, str] = {}
    for change in fix_changes:
        rel = change["path"]
        if change["mode"] != "modify":
            if isinstance(change.get("content"), str):
                texts[rel] = change["content"]
            continue
        if rel not in texts:
            path = Path(work_dir) / rel
            if not path.exists():
                refusals.append(f"MODIFY target {rel} does not exist; refused")  # BF-904a: a repair's missing target
                continue
            if not path.is_file():
                continue
            try:
                texts[rel] = path.read_text(encoding="utf-8")
            except (OSError, ValueError):
                refusals.append(f"MODIFY target {rel} could not be read; refused")
                continue
        text = texts[rel]
        for i, repl in enumerate(change.get("replacements", [])):
            if repl["search"] not in text:
                refusals.append(f"SEARCH block {i} not found in {rel}; refused")  # BF-904a: a repair's unmatched block
                continue
            text = text.replace(repl["search"], repl["replace"], 1)
        texts[rel] = text
    return refusals


def _check_sealed_path(target_path: "Path", runtime: "ProbOSRuntime | None") -> None:
```

### 8d. `src/probos/cognitive/builder.py`: the repair is checked whole before any block applies
SEARCH:
```python
                    if fix_refusals:
                        for refusal in fix_refusals:
                            logger.warning("BuilderAgent: repair refused: %s", refusal)
                        validation_errors.extend(fix_refusals)
                        break  # BF-898: no further repair attempt

                    # Apply fix changes
```
REPLACE:
```python
                    if fix_refusals:
                        for refusal in fix_refusals:
                            logger.warning("BuilderAgent: repair refused: %s", refusal)
                        validation_errors.extend(fix_refusals)
                        break  # BF-898: no further repair attempt
                    # BF-904a (#1585): every MODIFY block of the repair must apply as written; one that
                    # cannot refuses the whole response and stops the loop, as BF-898 does for paths.
                    unapplied = _unapplied_repair_blocks(fix_changes, work_dir)  # BF-904a: checked before any block is applied
                    if unapplied:
                        for refusal in unapplied:
                            logger.warning("BuilderAgent: repair refused: %s", refusal)
                        validation_errors.extend(unapplied)
                        break  # BF-904a: no further repair attempt

                    # Apply fix changes
```

### 8e. `src/probos/cognitive/builder.py`: the application's silent skips go
SEARCH:
```python
                            if change["mode"] == "modify":
                                if not path.exists():
                                    continue
                                original = path.read_text(encoding="utf-8")
                                mod = original
                                for repl in change.get("replacements", []):
                                    if repl["search"] in mod:
                                        mod = mod.replace(
                                            repl["search"], repl["replace"], 1,
                                        )
                                if mod != original:
```
REPLACE:
```python
                            if change["mode"] == "modify":
                                # BF-904a: _unapplied_repair_blocks has checked that the target exists
                                # and that every block matches, in order.
                                original = path.read_text(encoding="utf-8")
                                mod = original
                                for repl in change.get("replacements", []):
                                    mod = mod.replace(repl["search"], repl["replace"], 1)
                                if mod != original:
```

### 8f. `src/probos/cognitive/builder.py`: a change list that changed nothing is a failure
SEARCH:
```python
                if not result.error:
                    result.success = True
        else:
            result.success = True

    except Exception as exc:
```
REPLACE:
```python
                if not result.error:
                    result.success = True
        elif file_changes:
            # BF-904a (#1585): changes were asked for and none applied (every block left its file
            # as it was): a failure with a reason, never a success with nothing to commit.
            result.error = "No change applied: " + ", ".join(
                sorted({str(change["path"]) for change in file_changes})
            )
            result.success = False  # BF-904a: a change list that changed nothing is not a success
        else:
            result.success = True

    except Exception as exc:
```

## Section 9 (M3): tests

### 9a. `tests/test_bf904a_unapplied_blocks.py` (new)

Same fixture rules as 4a and 7a (plain repo on `main`, seed `TARGET` `x = 1\n` and `OTHER` `y = 1\n`). `_state` as in 7a.

| ID | Test | Asserts |
|---|---|---|
| S1 | `test_an_unmatched_search_block_fails_the_build_and_writes_nothing` | `[modify TARGET with blocks (0) "x = 1" to "x = 2", (1) "no such text" to "z"]`, `run_tests=False`. Premise: block 0's text is in the file and block 1's is not. `success is False`, no commit; `"SEARCH block 1 not found in src/probos/a.py; refused" in result.error`; `result.files_modified == []`; `_state` unchanged. |
| S2 | `test_a_missing_modify_target_fails_the_build` | `[modify "src/probos/gone.py" ("a" to "b"), create NEW]`. Premise: the target is absent. `success is False`; `"MODIFY target src/probos/gone.py does not exist; refused" in result.error`; NEW does not exist; `_state` unchanged. |
| S3 | `test_a_change_list_that_changes_nothing_fails_with_a_reason` | `[modify TARGET ("x = 1" to "x = 1")]` (a matched no-op). `success is False`; `result.error == "No change applied: src/probos/a.py"`; no commit; `_state` unchanged. Control: `execute_approved_build([], ...)` keeps today's result (`success is True`, no error). |
| S4 | `test_a_repair_with_a_block_that_cannot_apply_is_refused_whole` parametrised `unmatched` (repair: MODIFY TARGET "x = 2" to "x = 3" plus MODIFY OTHER "absent" to "q") and `missing` (MODIFY TARGET plus MODIFY "src/probos/gone.py") | Build `[modify TARGET "x = 1" to "x = 2"]`, `run_tests=True`, the runner fake always fails, `max_fix_attempts=2`. Premise: the runner was awaited once before the repair and the fake model received exactly one repair request. `success is False`; the runner's `await_count == 1` (the loop stopped); `result.fix_attempts == 1`; `"fix_loop_files" not in result.metadata` (no block applied, TARGET's block included); error contains `"SEARCH block 0 not found in src/probos/other.py; refused"` or `"MODIFY target src/probos/gone.py does not exist; refused"`; `_state` unchanged. |
| S5 | `test_a_repair_that_creates_then_modifies_a_file_applies` (the pre-check's control) | Build `[create NEW]`, runner fails then passes; repair is `===FILE: src/probos/helper.py===` holding `h = 1` plus `===MODIFY: src/probos/helper.py===` "h = 1" to "h = 2". `success is True`, a commit; `git show <branch>:src/probos/helper.py == "h = 2\n"`. |
| E2 | `test_no_refusal_message_or_log_carries_file_content` | `caplog.set_level(DEBUG)`. The file holds `secret = "BF904A-CONTENT"`; the unmatched SEARCH text is `BF904A-SEARCH`. Neither sentinel appears in `result.error` nor in any record's `getMessage()`. |

### 9b. `tests/test_bf896_executor_identity_and_blocks.py`: the two tests that pinned the silent outcome
SEARCH:
```python
async def test_modify_blocks_outside_the_whole_file_shape_keep_the_old_no_op(
    tmp_path: Path, block_extra: dict[str, Any]
) -> None:
    """A block is a whole-file change only with NO ``replacements`` key AND a ``str`` ``content``.

    Anything else keeps today's executor behaviour: no refusal, no write, success with nothing to commit.
    """
    await _assert_whole_file_control_lands(tmp_path)
    repo = _plain_repo(tmp_path / "probe")
    tree_before = _tree(repo)

    result = await _build(repo, [{"path": TARGET, "mode": "modify", **block_extra}])

    assert result.success is True and not result.error, result.error
```
REPLACE:
```python
async def test_modify_blocks_outside_the_whole_file_shape_change_nothing_and_fail(
    tmp_path: Path, block_extra: dict[str, Any]
) -> None:
    """A block is a whole-file change only with NO ``replacements`` key AND a ``str`` ``content``.

    Anything else writes nothing. BF-904a (#1585): a change list that changed nothing is a failure
    with a reason ("No change applied"), no longer a success with nothing to commit.
    """
    await _assert_whole_file_control_lands(tmp_path)
    repo = _plain_repo(tmp_path / "probe")
    tree_before = _tree(repo)

    result = await _build(repo, [{"path": TARGET, "mode": "modify", **block_extra}])

    assert result.success is False and result.error == f"No change applied: {TARGET}", result.error
```

SEARCH:
```python
async def test_replacement_modify_of_an_absent_target_without_base_keeps_the_legacy_skip(tmp_path: Path) -> None:
    """A block with NO ``base`` key (native LLM flow, repair loop) keeps the absent-target skip."""
    repo = _plain_repo(tmp_path / "repo")
    block = {"path": "src/probos/gone.py", "mode": "modify", "replacements": [{"search": "a", "replace": "b"}]}

    result = await _build(repo, [block, _whole(TARGET, "x = 2\n", base=ORIGINAL)])

    assert result.success, result.error
    assert result.files_modified == [TARGET], "the absent-target replacement is skipped, the other block lands"
    assert _blob(repo, result.branch_name, TARGET) == "x = 2\n"
```
REPLACE:
```python
async def test_replacement_modify_of_an_absent_target_without_base_is_refused(tmp_path: Path) -> None:
    """BF-904a (#1585): this used to pin the silent absent-target skip, which let the other block commit alone.

    A missing MODIFY target is now a refusal that blocks the commit, and the other block's write is undone.
    """
    repo = _plain_repo(tmp_path / "repo")
    block = {"path": "src/probos/gone.py", "mode": "modify", "replacements": [{"search": "a", "replace": "b"}]}

    result = await _build(repo, [block, _whole(TARGET, "x = 2\n", base=ORIGINAL)])

    assert result.success is False and not result.commit_hash
    assert "MODIFY target src/probos/gone.py does not exist; refused" in result.error, result.error
    assert (repo / TARGET).read_bytes() == ORIGINAL.encode("utf-8"), "the other block's write is undone"
    assert _refs(repo) == ["main"]
```

### 9c. `tests/test_builder_agent.py`: three tests that pinned the silent skips
SEARCH:
```python
        """MODIFY on nonexistent file is skipped without crashing."""
```
REPLACE:
```python
        """BF-904a (#1585): a MODIFY of a nonexistent file is refused (it used to be skipped)."""
```

SEARCH:
```python
        assert result.success is True
        assert result.files_modified == []

    @pytest.mark.asyncio
    async def test_search_text_not_found(self, tmp_path: Path):
        """Replacement skipped when SEARCH text not found; other replacements still apply."""
```
REPLACE:
```python
        assert result.success is False
        assert "MODIFY target nonexistent.py does not exist; refused" in result.error
        assert result.files_modified == []

    @pytest.mark.asyncio
    async def test_search_text_not_found(self, tmp_path: Path):
        """BF-904a (#1585): one unmatched SEARCH block refuses the build, and the file's other blocks are not applied."""
```

SEARCH:
```python
        assert result.success is True
        assert "partial.py" in result.files_modified
        content = target.read_text(encoding="utf-8")
        assert "b = 20" in content
        assert "a = 1" in content
```
REPLACE:
```python
        assert result.success is False
        assert "SEARCH block 0 not found in partial.py; refused" in result.error
        assert result.files_modified == []
        assert target.read_text(encoding="utf-8") == "a = 1\nb = 2\n"
```

SEARCH:
```python
        """When all SEARCH texts not found, files_modified stays empty."""
```
REPLACE:
```python
        """BF-904a (#1585): when no SEARCH text is found, the build is refused (it used to succeed with nothing)."""
```

SEARCH:
```python
        assert result.success is True
        assert result.files_modified == []


# ---------------------------------------------------------------------------
# AST validation (AD-313)
```
REPLACE:
```python
        assert result.success is False
        assert "SEARCH block 0 not found in noop.py; refused" in result.error
        assert result.files_modified == []


# ---------------------------------------------------------------------------
# AST validation (AD-313)
```

### 9d. `tests/test_bf897_build_pipeline_scale_and_checkout.py`: the repair block must apply on every attempt
SEARCH:
```python
_FIX_BLOCK = (
    f"===MODIFY: {_FOO}===\n"
    "===SEARCH===\nx = 1\n===REPLACE===\nx = 2\n===END REPLACE===\n"
    "===END MODIFY==="
)
```
REPLACE:
```python
# BF-904a (#1585): a whole-file block, which applies on every attempt. The MODIFY block it replaces stopped
# matching after the first repair (x = 1 had become x = 2), and an unmatched repair block is now refused whole.
_FIX_BLOCK = f"===FILE: {_FOO}===\nx = 2\n===END FILE===\n"
```

SEARCH:
```python
    assert [(block["mode"], block["path"]) for block in blocks] == [("modify", _FOO)], "premise: a valid fix block"
```
REPLACE:
```python
    assert [(block["mode"], block["path"]) for block in blocks] == [("create", _FOO)], "premise: a valid fix block"
```

### 9e. `tests/test_bf898_fix_loop_grader_protection.py`: the unmatched third block, and the two refused cases
SEARCH:
```python
        + f"===MODIFY: {_OTHER}===\n===SEARCH===\nnope\n===REPLACE===\nz = 2\n===END REPLACE===\n===END MODIFY===\n"
    )
    llm = _FakeLLM(reply)
    parsed = sorted((block["mode"], block["path"]) for block in BuilderAgent._parse_file_blocks(reply))
    assert parsed == [("create", _HELPER), ("modify", _FOO), ("modify", _OTHER)], "premise: three source blocks"
    assert "nope" not in other.read_text(encoding="utf-8"), "premise: the third block's SEARCH text is not in the file"
```
REPLACE:
```python
        # BF-904a (#1585): the third block matches and leaves the file as it was. It used to be an unmatched
        # block, silently skipped; an unmatched repair block now refuses the whole response.
        + f"===MODIFY: {_OTHER}===\n===SEARCH===\nz = 1\n===REPLACE===\nz = 1\n===END REPLACE===\n===END MODIFY===\n"
    )
    llm = _FakeLLM(reply)
    parsed = sorted((block["mode"], block["path"]) for block in BuilderAgent._parse_file_blocks(reply))
    assert parsed == [("create", _HELPER), ("modify", _FOO), ("modify", _OTHER)], "premise: three source blocks"
    assert "z = 1" in other.read_text(encoding="utf-8"), "premise: the third block's SEARCH text is in the file"
```

SEARCH:
```python
    assert result.success is False
    assert result.error, "the directory block must raise and be reported"
    assert result.fix_attempts == 1
    assert "fix_loop_files" not in result.metadata
```
REPLACE:
```python
    assert result.success is False
    if case in ("no_op_modify", "missing_modify"):
        # BF-904a (#1585): the leading block cannot apply, so the repair is refused whole before the
        # directory block is reached; the outcome below is the same, for that reason.
        assert "; refused" in result.error, result.error
    else:
        assert result.error, "the directory block must raise and be reported"
    assert result.fix_attempts == 1
    assert "fix_loop_files" not in result.metadata
```

Other existing tests: `test_builder_agent.py` `test_fix_loop_exhausts_retries` (`:2237`) still passes (its second repair no longer matches and is refused, but `fix_attempts == 2` counts the request, `builder.py:2969`). Any further test that fails only because a build that does not commit now restores a pre-existing file, or because an unmatched block is now refused, is updated the same way, with the reason inline, and listed in the build report. A test that fails for any other reason is a hard stop.

## Tests summary

New: H1, H2, H3 (2 cases), F1, F2, P1, A1, E1 (M1); R1 (5 cases), R2, R2b, R3, R4, R5, R6 (M2); S1, S2, S3, S4 (2 cases), S5, E2 (M3). Boundaries: happy path (H1, F1, R3, S5, the S3 control), errors and refusals (H2, H3, F2, P1, R2, R4, S1 to S4), empty (S3's empty-list control), privacy (F2, E2), the seam across the route (R5, R6) and the worktree manager (A1, E1). Updated: 4b, 7b to 7f, 9b to 9e.

## Focused gates (per milestone; `-n 0 -p no:randomly`; first confirm `probos.__file__` resolves inside this worktree's `src`)

Consumer tests of the changed files, enumerated by grep (Absence Verified 10), called CONSUMERS: `tests/test_builder_agent.py tests/test_builder_guardrails.py tests/test_builder_api.py tests/test_bf892_spawn_env.py tests/test_bf892_spawn_env_guard.py tests/test_bf894_builder_write_boundary.py tests/test_bf896_executor_identity_and_blocks.py tests/test_bf896_dispatcher_confinement_seam.py tests/test_bf896_session_permission_handler.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_bf898_fix_loop_grader_protection.py tests/test_worktree_manager.py tests/test_build_dispatcher.py tests/test_dispatch_wiring.py tests/test_ad521_swe_pipeline_separation.py tests/test_ad476_specialized_builders.py tests/test_architect_agent.py tests/test_ad1200_repository_instructions.py tests/test_events.py`. For `command_env.py`, ENV: `tests/test_bf890_command_env.py tests/test_bf890_config.py tests/test_bf890_shell_agent_env.py tests/test_bf893_process_tree.py tests/test_ad1328_s2a_run_command_tool.py tests/test_ad1328_s2b_seam_and_wiring.py tests/test_ad1328_s2b_tool_router_shell.py`.

- **M1:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf904a_git_hardening.py <CONSUMERS> <ENV> -q -n 0 -p no:randomly`
- **M2:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf904a_failed_build_restore.py tests/test_bf904a_git_hardening.py <CONSUMERS> -q -n 0 -p no:randomly`
- **M3:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf904a_unapplied_blocks.py tests/test_bf904a_failed_build_restore.py tests/test_bf904a_git_hardening.py <CONSUMERS> -q -n 0 -p no:randomly`
- **Each milestone:** `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` exits 0. No config field, so the config checks are unaffected.
- No order-in-time dependency in any new test (no timestamps compared), so no coarse-clock run is needed.
- The broad gate runs once, by the orchestrator, after M3 and its review: `scripts/run_test_gate.py --label bf-904a --receipt logs/gates/bf-904a.receipt.json`.

## Milestones and cut points (Builder milestones of at most about 150 tool calls)

| Milestone | Sections | Estimate | Cut if past about 150 calls |
|---|---|---|---|
| M1 | 1, 2, 3, 4 | 90 to 120 | Commit after Sections 1 to 3, 4b, and E1, H1, H2 green; F1, F2, H3, P1, A1 become M1b (same commit series, before M2). |
| M2 | 5, 6, 7 | 110 to 140 | Commit after Section 5, 7b to 7f, and R1, R2 green; Section 6 with R5, R6 and R2b, R3, R4 become M2b. |
| M3 | 8, 9, Tracking | 60 to 90 | Not split. |

Commit by explicit path (never `git add -A`); run `git diff --cached --stat` and stop on any unexpected file with more than 200 deletions. `PROGRESS.md` and `DECISIONS.md` may hold unrelated Captain work: stage only the named hunks. Hard stops: H1, F1, F2 or A1's premise fails on this machine (report the stderr; do not skip or weaken the test); a test outside the lists above fails for a reason other than the two named in Section 9; the `_GitSpy` sequence in H2 shows any git after the config read.

## Diff Reviewer properties (verify each)

**M1 (security-relevant: Diff Reviewer plus one GPT-6.1 Sol cross-family review)**
1. Every git process of the pipeline carries `-c core.hooksPath=<os.devnull>` and `-c core.fsmonitor=false` before its verb: the builder's `_run_git`, both launches of `_is_dirty_working_tree`, and every call of the worktree manager's `_run_git` (`create`, `remove`, `collect_diff`, `adopt_commit`). No new subprocess launch site exists; every new git command goes through `_run_git`.
2. Any difference in the resolved config listing or in the hooks directory between the snapshot before the first test run and the check after the fix loop, or a failed capture of either, sets `git_unsafe`; while it is set, no git command runs again in that call (no add, commit, checkout, reset or branch).
3. The guarantee holds with no pin: the override and the comparison do not depend on `expected_git_dir`; with no pin given, the identity read at entry is pinned when readable and compared before the commit, and an unreadable one keeps today's path.
4. The hooks comparison reads files in Python; the only git the check runs is the config listing, and it is skipped when the identity is already lost.
5. No message or log line this change adds carries a config value or a file's content (sources, keys and file names only).
6. BF-896's pinned path behaves as before (`test_bf896...:701`, `:740` unchanged and green); no config field; `config/system.yaml` untouched.

**M2**
7. A build that does not commit leaves `git status --porcelain`, the HEAD ref, every local branch and every file's bytes identical to before, for each starting state: a branch other than `main`, a detached HEAD, a linked worktree with `main` checked out elsewhere, a fix-loop edit, a commit that failed after `add`.
8. Cleanup order: unstage only if `git add` ran and git is safe; restore the bytes; delete created files; return to the original ref; delete the build branch only if the return succeeded. Every step's result is checked; every failure is in `metadata["cleanup_errors"]`; a failed build's own error comes first; a successful result stays a success and logs at ERROR.
9. Nothing falls back to `"main"`; a tree with neither a branch nor a commit is refused before the build branch exists. The byte restore runs no git.
10. `abort` runs no git. `commit_override` executes the cached changes through `execute_approved_build` with `run_tests=False`, every other guard on, `OVERRIDE_MARKER` as the description's first line, asynchronously, and returns the build id; the request and the `BUILD_RESOLVED` event keep their shape.

**M3**
11. A missing MODIFY target or an unmatched SEARCH block, in the main loop or a repair, is a refusal in `validation_errors` that names only the block index and the path; the main-loop file is not written; a repair with one such block applies none of its blocks and stops the loop.
12. A non-empty `file_changes` that changed nothing ends `success=False` with `No change applied: <paths>`; an empty one keeps today's result.
13. The repair pre-check agrees with the application: blocks matched in order against the text earlier blocks leave; a non-regular target keeps today's raise.

**Consumers that must accept the change:** the dispatcher (`build_dispatcher.py:226-238` treats success without a commit as a failure, and now gets `success=False` directly; `adopt_commit` after a committed build); `routers/build.py` `_execute_build` (a failure goes to `classify_build_failure` and the failure cache; the retry paths need a clean tree, which M2 now leaves); the HXI resolve buttons (`IntentSurface.tsx:1587-1594` ignores the response body; `useStore.ts:3821-3826` shows the `build_resolved` message); `BuildPipeline` (`build_pipeline.py:89-96`, pass-through, now pinned at entry).

## Mutation table (campaign of record: record it in the BF-904a entry of `DECISIONS.md` with the base tree, each pinned file's sha256, each result and its killer, row ids prefixed `BF904a-`)

Every SEARCH is the stripped post-build line, including its trailing comment, and has exactly one match in the named file (count it against the built file first; zero or more than one is INERT). Run the unmodified baseline first, mutate in place with a `.mutbak` sibling, restore in `finally`, treat a timeout as INVALID, and run each row against the test file that holds its killer.

**Partition P1, `tests/test_bf904a_git_hardening.py`** (M1)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| K1 | `src/probos/cognitive/builder.py` | `["git", *HARDENED_GIT_CONFIG_ARGS, *args],  # BF-904a: no repository hook or fsmonitor runs` | `["git", *args],` | E1, H1 |
| K2 | `src/probos/cognitive/builder.py` | `"git", *HARDENED_GIT_CONFIG_ARGS, "rev-parse", "--git-dir",` | `"git", "rev-parse", "--git-dir",` | E1 |
| K3 | `src/probos/cognitive/builder.py` | `"git", *HARDENED_GIT_CONFIG_ARGS, "status", "--porcelain",` | `"git", "status", "--porcelain",` | E1, F1 |
| K4 | `src/probos/worktree_manager.py` | `*HARDENED_GIT_CONFIG_ARGS,  # BF-904a: every worktree git call, adopt_commit's included` | `"--no-pager",` | A1, E1 |
| K5 | `src/probos/execution/command_env.py` | `"-c", f"core.hooksPath={os.devnull}",  # BF-904a: no repository hook runs` | `"-c", "core.bf904amutant=1",` | H1, A1, E1 |
| K6 | `src/probos/execution/command_env.py` | `"-c", "core.fsmonitor=false",  # BF-904a: no fsmonitor hook runs` | `"-c", "core.bf904amutant=2",` | F1, E1 |
| K7 | `src/probos/cognitive/builder.py` | `if config != before.config:  # BF-904a: a filter, an include or any other config source changed` | `if False:` | F2 |
| K8 | `src/probos/cognitive/builder.py` | `elif hooks != before.hooks:  # BF-904a: a hook file appeared, changed or went away` | `elif False:` | H2 |
| K9 | `src/probos/cognitive/builder.py` | `git_unsafe = True  # BF-904a: a changed config or hooks directory blocks every later git call` | `pass` | H2 (the git after the plant) |
| K10 | `src/probos/cognitive/builder.py` | `pinned_git_dir = await repository_identity(work_dir)  # BF-904a: pin what the tree names now, when readable` | `pinned_git_dir = None` | P1 |
| K11 | `src/probos/cognitive/builder.py` | `elif git_tampered is not None:` | `elif False:` | H2, F2 |
| K12 | `src/probos/cognitive/builder.py` | `if tests_ran and not identity_lost:` | `if False:` | H2, F2, H3 |

**Partition P2, `tests/test_bf904a_failed_build_restore.py`** (M2)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| R-a | `src/probos/cognitive/builder.py` | `(root / rel).write_bytes(data)` | `pass` | R1 (all cases) |
| R-b | `src/probos/cognitive/builder.py` | `return out if rc == 0 and out else None  # BF-904a: never a guessed "main"` | `return out if rc == 0 and out else "main"` | R1 `detached` |
| R-c | `src/probos/cognitive/builder.py` | `args = ["checkout", "-q", branch, "--"]` | `args = ["checkout", "-q", "main", "--"]` | R1 `other-branch`, `linked-worktree-main-elsewhere`; R3 |
| R-d | `src/probos/cognitive/builder.py` | `elif restore_tree:` | `if restore_tree:` | R2 (branch deleted after a failed return) |
| R-e | `src/probos/cognitive/builder.py` | `if not returned:  # BF-904a: a failed return keeps the build branch and is reported` | `if False:` | R2, R2b |
| R-f | `src/probos/cognitive/builder.py` | `unstaged = await _cleanup_git(["reset", "-q", "--", *written, *modified_files], work_dir)  # BF-904a: unstage before the restore` | `unstaged = None` | R1 `commit-failed-after-add` |
| R-g | `src/probos/cognitive/builder.py` | `originals.setdefault(change["path"], path.read_bytes())  # BF-904a: saved before the first write` | `pass` | R1 (TARGET) |
| R-h | `src/probos/cognitive/builder.py` | `originals.setdefault(change["path"], path.read_bytes())  # BF-904a: a create over an existing file saves it first` | `pass` | R1 (OTHER) |
| R-i | `src/probos/cognitive/builder.py` | `originals.setdefault(change["path"], before_fix)  # BF-904a: a repair saves a file the build did not create` | `pass` | R1 `fix-loop-edit` |
| R-j | `src/probos/cognitive/builder.py` | `if original_branch is None and original_commit is None:` | `if False:` | R4 |
| R-k | `src/probos/cognitive/builder.py` | `add_attempted = True  # BF-904a: a failed commit may leave these paths staged` | `pass` | R1 `commit-failed-after-add` |
| R-l | `src/probos/routers/build.py` | `_execute_build(req.build_id, file_changes, override_spec, work_dir, runtime, run_tests=False),  # BF-904a: the test gate is the only guard the override lifts` | `_execute_build(req.build_id, file_changes, override_spec, work_dir, runtime, run_tests=True),` | R6 |
| R-m | `src/probos/routers/build.py` | `description=OVERRIDE_MARKER + (f"\n\n{spec.description}" if spec.description else ""),` | `description=spec.description,` | R6 |
| R-n | `src/probos/routers/build.py` | `run_tests=run_tests,  # BF-904a: False only for the Captain's commit_override` | `run_tests=True,` | R6 |

**Partition P3, `tests/test_bf904a_unapplied_blocks.py`** (M3)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| S-a | `src/probos/cognitive/builder.py` | `validation_errors.append(f"MODIFY target {change['path']} does not exist; refused")` | `pass` | S2 |
| S-b | `src/probos/cognitive/builder.py` | `validation_errors.append(f"SEARCH block {i} not found in {change['path']}; refused")` | `pass` | S1 |
| S-c | `src/probos/cognitive/builder.py` | `continue  # BF-904a: a file with an unmatched block is not written at all` | `pass` | S1 (`files_modified == []`) |
| S-d | `src/probos/cognitive/builder.py` | `result.success = False  # BF-904a: a change list that changed nothing is not a success` | `result.success = True` | S3 |
| S-e | `src/probos/cognitive/builder.py` | `unapplied = _unapplied_repair_blocks(fix_changes, work_dir)  # BF-904a: checked before any block is applied` | `unapplied = []` | S4 (both cases) |
| S-f | `src/probos/cognitive/builder.py` | `refusals.append(f"MODIFY target {rel} does not exist; refused")  # BF-904a: a repair's missing target` | `continue` | S4 `missing` |
| S-g | `src/probos/cognitive/builder.py` | `refusals.append(f"SEARCH block {i} not found in {rel}; refused")  # BF-904a: a repair's unmatched block` | `continue` | S4 `unmatched` |
| S-h | `src/probos/cognitive/builder.py` | `break  # BF-904a: no further repair attempt` | `pass` | S4 (the refused response is applied, and the runner runs again) |

Mapping to the consult's twelve mutations: hooksPath argument (K1, K5), fsmonitor (K3, K6), config comparison (K7), hook comparison (K8), restore loop (R-a), `"main"` as target (R-b, R-c), `branch -D` before the return (R-d), ignored return value (R-e), `continue` at the SEARCH miss (S-b, S-c), `continue` at the missing target (S-a), `else: result.success = True` (S-d), and the fix loop's skip, replaced by S-e to S-h (D15).

## What this does NOT change

- Items 2, 4, 6 and 7 of #1585 (BF-904b): the sealed-core check, the re-evaluation of syntax errors and `all_changed_files`, the footprint conflict and `_git_create_branch`'s `branch -D`, the visiting builder's excerpts and path normalisation. `classify_build_failure` and the `Syntax errors:` header stay (D16).
- AD-481l, AD-1334 and AD-1335 (sandboxing test execution). Recorded residual risk, owned by AD-1335: if a refused build N planted a filter driver plus `info/attributes`, build N+1 starts from the tampered config and runs the filter on its `git add`; BF-904a's mitigation is build N's refusal message naming the change.
- `builder_write_refusal`, `fix_loop_write_refusal` (F-124), the native harness route (F-120), the worktree start point (F-121), `merge_to_main`, `collect_diff`'s output, `execution/authority.py`.
- `config/system.yaml`, `config.py` (no config field), the event types, `api_models.py`, the HXI.

## Tracking

- `DECISIONS.md`: a `### BF-904a` entry (decisions D1 to D18 in one line each, the disclosed effect D18, the residual risk above, and the mutation campaign of record). Stage only that hunk.
- `PROGRESS.md`: one BF-904a line in the form the BF-898 line uses (`PROGRESS.md:17`), "Part of #1585; BF-904b open". Stage only that hunk.
- `docs/development/roadmap.md`: no row (it carries no BF-89x or BF-90x rows; Absence Verified 12).
- `docs/research/reference-projects.md`: the Aider row (orchestrator applies; see Prior Art).

## Acceptance criteria

1. Every git process the pipeline starts carries both options (E1); a hook or fsmonitor present before the build never runs (H1, F1); one planted during the tests, or a filter driver, refuses the build with no later git and no execution (H2, F2); a failed capture refuses (H3); an unpinned build is pinned at entry (P1); `adopt_commit` runs no hook (A1).
2. A build that does not commit leaves porcelain, HEAD ref, branches and bytes identical for the five starting states (R1); a failed return is reported and keeps the branch (R2, R2b); a commit returns to the starting branch (R3); an unreadable ref is refused at entry (R4); `abort` runs no git (R5); `commit_override` re-runs without the test gate, with the marker (R6).
3. A missing target, an unmatched block, a repair that cannot apply and a change list that changes nothing each fail with a reason and leave the tree unchanged (S1 to S4); the pre-check's control applies (S5); no message or log carries file content (E2).
4. Every updated test carries its reason inline; the mutation campaign of record kills every row.
5. Focused gates green per milestone; `check_architecture_principles.py --check` exits 0; one receipted broad gate after M3.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior Art and Blind Spots (2026-10-18)

- **Git's own documentation** suggests `git -c core.hooksPath=/dev/null ...` per command to disable all hooks, and git's test `t1350-config-hooks-path.sh` accepts `nul` on Windows ([docs commit](https://code.googlesource.com/git/+/1b2eee94f120969690d772af5a14f681f7d875a7%5E%21/), [t1350](https://code.googlesource.com/git/+/HEAD/t/t1350-config-hooks-path.sh)). **Adopted** with `os.devnull`, which is also `execution/authority.py:792-801`'s value. The literal `/dev/null` is not used on Windows, where Go-based git-lfs resolves it relative to the worktree and writes a `dev/null/` directory ([report](https://claudeissues.com/issue/81812-windows-worktree-creation-in-an-lfs-repo-creates-a-literal-dev-null-directory)); `os.devnull` there is `nul`. Rejected: an empty temporary directory, which code under test, running as the same user, could write a hook into.
- **The 2026 coding-agent git-config attacks** ([GitSpawn, CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-ai-coding-agent-git-config-rce-20260904-cs/), [CVE-2026-19592](https://www.sentinelone.com/vulnerability-database/cve-2026-19592/)), from the consult: fsmonitor and planted config are the vectors. **Adopted**: `core.fsmonitor=false`, and a digest of the *resolved* config, because filter driver names are arbitrary and cannot be listed with `-c`.
- **Aider** (reference-projects row overdue: last reviewed 2026-06-13, 90-day interval, judged on 2026-10-18): `--git-commit-verify` defaults to False, so its commits pass `--no-verify` and skip the pre-commit hooks ([options](https://aider.chat/docs/config/options.html)). **Adapted**: the same default reasoning (an agent's commits do not run repository hooks), widened to every hook and every git call, because `--no-verify` leaves `post-checkout`, `reference-transaction` and fsmonitor running. Row update for the orchestrator: Aider, 2026-10-18, checked, "BF-904a (#1585) Prior Art, `prompts/bf-904a-native-build-git-hardening.md` (`--git-commit-verify` default False)".
- Considered, deferred (overdue, not relevant enough to this fix): SWE-agent (2026-03-20), Cursor (2026-06-13). Internal: no `docs/research/` note covers git hook hardening; BF-892 (`_GIT_HOME_NAMES`), BF-896 (identity pin) and BF-897 (operator-checkout refusal) are the in-tree prior work, and this contract extends each without changing it.
- **Blind spots named and decided:** (a) `rev-parse --git-path hooks` under the override (D4); (b) the worktree manager's `remove` and `create` share the hooks directory (D3); (c) an escalation result with no commit (D10); (d) `commit_override` now refuses what any other guard refuses (D12); (e) an unborn branch (a repository with no commit): `symbolic-ref` answers, the build's commit makes the branch; a failed build's return to an unborn branch fails and is reported in `cleanup_errors`. Accepted, no production caller builds in an empty repository; (f) a file the TESTS (not the build) modified is not restored: out of scope, the AD-1335 sandbox owns it; (g) git-lfs hooks no longer run on pipeline git calls (D18); (h) operator `core.hooksPath` directories are not digested (D4).

## Verified Against Codebase (2026-10-18, base `cf08d4c9`)

```
grep -n "async def _run_git\|_GIT_HOME_NAMES\|def _git_\|def repository_identity\|original_branch\|identity_lost\|result.success = True\|create_subprocess_exec\|async def execute_approved_build\|def _is_dirty_working_tree\|def _check_sealed_path\|def classify_build_failure" src/probos/cognitive/builder.py
  199:def classify_build_failure(result: BuildResult, spec: BuildSpec) -> BuildFailureReport:
  1588:_GIT_HOME_NAMES: tuple[str, ...] = ("HOME", "XDG_CONFIG_HOME")
  1591:async def _run_git(args: list[str], work_dir: str) -> tuple[int, str, str]:
  1619:async def _git_current_branch(work_dir: str) -> str:
  1625:async def _git_create_branch(branch_name: str, work_dir: str) -> tuple[bool, str]:
  1639:async def _git_add_and_commit(
  1657:async def _git_checkout_main(work_dir: str) -> tuple[bool, str]:
  1665:async def repository_identity(work_dir: str) -> str | None:
  2606:async def _is_dirty_working_tree(work_dir: str) -> bool:
  2616:        proc = await asyncio.create_subprocess_exec(
  2628:        proc = await asyncio.create_subprocess_exec(
  2641:def _check_sealed_path(target_path: "Path", runtime: "ProbOSRuntime | None") -> None:
  2677:async def execute_approved_build(
  2706:    identity_lost = False
  2728:    original_branch = await _git_current_branch(work_dir)
  3071:                identity_lost = True
  3141:                    result.success = True
  3143:            result.success = True
  3150:        if not identity_lost:
Read builder.py:1599-1622   subprocess.run(["git", *args], env=build_command_env(_GIT_HOME_NAMES), ...); rev-parse --abbrev-ref HEAD; `return out if rc == 0 else "main"`
Read builder.py:1644-1662   add "--" *files; commit -m; checkout main
Read builder.py:2617, 2629 "git", "rev-parse", "--git-dir"; "git", "status", "--porcelain"
Read builder.py:2759-2767   _git_create_branch; result.branch_name = _sanitize_branch_name(branch); written/modified_files/validation_errors
Read builder.py:2811-2817   MODIFY target ... does not exist, skipping / continue
Read builder.py:2834-2852   SEARCH block %d not found ... continue; modified != original; path.write_text(modified)
Read builder.py:2869-2882   mkdir; _check_sealed_path; pre_existing = path.exists() and change["path"] not in written; write_text
Read builder.py:2929-2931   if run_tests and (written or modified_files): all_changes = list(file_changes)
Read builder.py:2969        result.fix_attempts += 1 (before the request)
Read builder.py:3005-3043   fix_refusals ... break; before_fix = path.read_bytes(); if not path.exists(): continue; if repl["search"] in mod
Read builder.py:3066-3086   5.4 identity check on expected_git_dir; 5.5 identity_lost / validation_errors "Syntax errors:\n"
Read builder.py:3094-3096   resolved = await escalation_hook(report); result = resolved
Read builder.py:3117        desc_short = spec.description[:200]
Read builder.py:3132-3170   _git_add_and_commit; else: result.success = True; finally: _git_checkout_main, branch -D, unlink written
grep -n "^import \|^from probos.execution" src/probos/cognitive/builder.py
  11:import asyncio   12:import ast   13:import logging   14:import os ... 18:from dataclasses import dataclass, field
  30:from probos.execution.command_env import build_command_env
grep -n "^@dataclass\|^class BuildSpec\|metadata: dict" src/probos/cognitive/builder.py
  109:@dataclass   110:class BuildSpec:   143:    metadata: dict[str, Any] = field(default_factory=dict)
grep -n "def _parse_file_blocks" -A 60 src/probos/cognitive/builder.py
  2344: ===FILE: pattern first; 2357: ===MODIFY: pattern second; 2380: search_text = sr.group(1).strip("\n")
grep -n "def _validate_python" -A 6 src/probos/cognitive/builder.py
  2413:        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
grep -n "hooksPath\|fsmonitor" src/probos
  src/probos/execution/authority.py:796:            "core.fsmonitor=false",
  src/probos/execution/authority.py:798:            f"core.hooksPath={os.devnull}",
Read src/probos/execution/command_env.py:17-66   imports os; four constants; the twins comment at 63-64; _ENV_NAME_SHAPE_RE at 66
Read src/probos/worktree_manager.py:11, 49-67, 84-86, 107-115, 170-223
  11:from probos.execution.command_env import trusted_command_env
  54:        proc = await asyncio.create_subprocess_exec(   55: "git",   56: *args,   57: env=trusted_command_env(),
  179-180: "Every git call runs in the worktree and nothing assumes where its HEAD is."
  192: checkout info.branch   196: merge --ff-only   207: branch -D
Read src/probos/build_dispatcher.py:180-252   182: expected_git_dir = await repository_identity(...); 215-222 execute_approved_build(..., expected_git_dir=...); 226-238 success without sha -> failed; 252 adopt_commit
grep -n "execute_approved_build|escalation_hook|expected_git_dir" src/probos/build_pipeline.py
  89: return await _legacy_execute_approved_build(   96: escalation_hook=escalation_hook,  (no expected_git_dir)
Read src/probos/routers/build.py:1-33, 84-165, 392-463
  5-8 imports (logging, time, Path, typing); 29-33 APPROVE_REFUSED; 101-103 BF-897 comment; 109-118 abort; 120-143 commit_override; 145-162 retries; 392-399 _execute_build(build_id, file_changes, spec, work_dir, rt); 416 run_tests=True
grep -n "class BuildResolve\|commit_override\|resolution" src/probos/api_models.py
  137:class BuildResolveRequest(BaseModel):   140:    resolution: str  # "retry_extended", ..., "commit_override", "abort"
Read ui/src/components/IntentSurface.tsx:1585-1598   await fetch('/api/build/resolve', ...) ; response unused
Read ui/src/store/useStore.ts:3821-3826              case 'build_resolved': addChatMessage('system', data.message)
grep -n "def get_task_tracker" src/probos/routers/deps.py
  34:def get_task_tracker(request: Request) -> Callable:
Read tests/test_bf897_build_pipeline_scale_and_checkout.py:214-224 (_add_worktree: worktree add -b <branch> <path> main; _common_dir), 477-504 (_FIX_BLOCK, _FakeBuildGit), 682-714, 800-826, 834-888 (seed; resolve abort; :887 asserts HEAD == "main")
Read tests/test_bf898_fix_loop_grader_protection.py:363-383, 450-459, 500-560, 586-686, 688-732
Read tests/test_bf896_executor_identity_and_blocks.py:62, 76-120, 171-188, 303-343, 571-590, 636-658, 700-822
Read tests/test_builder_agent.py:1965-2062, 2236-2268, 3045-3153
Read tests/test_bf894_builder_write_boundary.py:139-146
Read tests/test_bf892_spawn_env.py:175-203 (counts 3 launches: _run_git once, _is_dirty_working_tree twice; unchanged by this contract)
Read tests/test_bf892_spawn_env_guard.py:103  ("src/probos/worktree_manager.py", "WorktreeManager._run_git"): (1, "git worktree verbs")
Read tests/test_builder_api.py:337-411 (_execute_build called with five positional arguments; unchanged by the new keyword)
Read scripts/run_test_gate.py:1137-1149 (the gate runs phantom-api-precheck.ps1 itself)
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py
  CEILING: AD-1342 (from: GitHub issue titles (all states))   NEXT: AD-1343
```

## Absence Verified (2026-10-18)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| 1 | No pipeline git call sets a hook or fsmonitor override | `rg -n "hooksPath\|fsmonitor" src/probos` | `authority.py:796`, `:798` only | yes |
| 2 | The builder's git launch sites are `_run_git` and `_is_dirty_working_tree`'s two | `rg -n "subprocess\.run\(\|create_subprocess_exec\(\|subprocess\.Popen\(" src/probos/cognitive/builder.py` | `:1603` (`_run_git`), `:2464` (`_run_tests`, pytest), `:2540` (`_run_targeted_tests`, pytest), `:2616`, `:2628` | yes |
| 3 | The dispatcher starts no git itself | `rg -n "subprocess\|_run_git\(\|git" src/probos/build_dispatcher.py` | `:182`, `:183`, `:221`, `:239` (identity pin only) | yes |
| 4 | The router's git use is `abort` and `commit_override` only | `rg -n "subprocess\|_run_git\|_git_" src/probos/routers/build.py` | `:110`, `:111`, `:121`, `:132` | yes |
| 5 | `_git_checkout_main` and `_git_current_branch` have no other source callers | `rg -n "_git_checkout_main\|_git_current_branch" src` | `builder.py:1619`, `:1657`, `:2728`, `:3151`; `routers/build.py:110`, `:111` | yes |
| 6 | No response model names `commit` for the resolve route | `rg -n "class BuildResolve\|commit_override\|resolution" src/probos/api_models.py` | `:137-140` (request only) | yes |
| 7 | The UI reads no field of the resolve response | `rg -n "api/build/resolve\|commit_override\|build_resolved" ui/src` | `IntentSurface.tsx:1587` (fetch, result not read), `:1602`, `:1608`, `:1615` (button colours); `useStore.ts:3821` (event message) | yes |
| 8 | No production caller passes an escalation hook other than through `BuildPipeline` | `rg -n "escalation_hook=" src` | `build_pipeline.py:96` (pass-through), `routers/build.py:418` (`None`) | yes |
| 9 | No hook framework or attributes file is tracked | Glob `{.pre-commit-config.yaml,.githooks/*,.husky/*,.gitattributes,.lfsconfig}` | none | yes |
| 10 | The consumer test files of the changed modules are the CONSUMERS and ENV lists | `rg -l "execute_approved_build\|WorktreeManager\|worktree_manager\|routers import build\|routers\.build\|/api/build/\|_is_dirty_working_tree\|repository_identity" tests`; `rg -l "command_env import\|import command_env" tests` | the 18 + `test_events.py` (BUILD_RESOLVED) files and the 7 ENV files listed | yes |
| 11 | No existing test runs a planted git hook | `rg -n "hooks[/\"']\|pre-commit\|post-checkout\|reference-transaction" tests` | write-refusal path strings only (`test_bf896_dispatcher_confinement_seam.py:409-462`, `test_bf896_session_permission_handler.py:232`) | yes |
| 12 | The roadmap carries no BF-89x or BF-90x row | `rg -n "BF-89[0-9]\|BF-90[0-9]" docs/development/roadmap.md` | none | yes |
| 13 | Tests that patch the renamed helper are exactly these | `rg -n "_git_checkout_main\|_git_current_branch" tests` | `test_bf894...:140-141`; `test_bf897...:489-499`; `test_bf898...:368-378`; `test_builder_agent.py:3062-3146`; `test_builder_guardrails.py:236` (`_git_current_branch` only, unchanged) | yes |

## Not verified (stated, not assumed)

- **Git for Windows with `core.hooksPath=nul` and with a hook-path `core.fsmonitor`.** Evidence: git's docs and `t1350`, and `authority.py`'s precedent (which only shows git accepts the value). The runtime proof is H1, A1 and F1, each with a premise control that must show the planted code runs without the override on this machine (D17). If a premise fails, that is a hard stop for the Architect, not a skip.
- **The `--show-origin -z` field layout** used by `_config_change_names`: F2 checks it; the refusal itself does not depend on it (Section 2c note).
- **`git checkout -q --detach <sha> --`** with the trailing `--`: R1 `detached` checks it. If git rejects that form, drop the `--` for the detached form only and say so in the build report.
- No live database or vessel data was opened.

## Amendment A1 (2026-10-18): a bounded off-loop hooks listing, a lossless config comparison, escaped names, and fail-closed hooks location and test phase

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18. This is a read-only consult after M1's cross-family review round 1 (GPT-6.1 Sol: one P1 and three P2 findings, all regressions). The orchestrator appends it, so no line above moves. It supersedes the contract lines named in A1.12. Every SEARCH is against the STAGED M1 candidate (tree `3eeed557`). The Builder applies it tests first: A1.9 and A1.10 first, which must fail on the candidate, then A1.1 to A1.8.

**Gaps.**
- **F1 (P1, ordinary).** `_hooks_listing` (`builder.py:1700-1721`) sorts the hooks directory without a bound and calls `read_bytes()` on every non-directory entry. It follows symlinks, runs on the event loop, can block on a FIFO for good on POSIX, and allocates whole files.
- **F2 (P2, ordinary).** `_run_git` decodes with `errors="replace"` (`:1612`), so config values that differ only in undecodable bytes compare equal, and the build commits.
- **F3 (P2, ordinary).** Origins, keys and hook names reach `result.error` (rendered as Markdown) and the log with no escaping and no length bound.
- **F4 (P2, injected only).** A non-zero `--git-common-dir` becomes `hooks_dir = None` and an empty listing that counts as success.
- **Found while repairing (D23, D24):**
  - a cancellation or exception during the test phase or the comparison runs git in `finally`;
  - an unbounded config listing is parsed on the event loop;
  - the snapshot's `repr` would include the config text.

**Decisions** (recorded on #1585): **D19** lossless listing (A1.2). **D20** bounded `lstat` listing off the loop (A1.3). **D21** `_display_token` (A1.3). **D22** hooks-location table (A1.3, A1.4). **D23** unsafe from the start of the test phase (A1.4, A1.5). **D24** config listing bound (A1.3).

### A1.1 `src/probos/cognitive/builder.py`: import (against `builder.py:15-17`)
SEARCH:
```python
import os
import re
import subprocess
```
REPLACE:
```python
import os
import re
import stat
import subprocess
```

### A1.2 `src/probos/cognitive/builder.py`: `_run_git` gains `lossless` (against `builder.py:1592-1617`; K1's line is unchanged)
SEARCH:
```python
async def _run_git(args: list[str], work_dir: str) -> tuple[int, str, str]:
    """Run a git command asynchronously.  Returns (returncode, stdout, stderr).

    Uses subprocess.run in a thread executor for Windows compatibility —
    asyncio.create_subprocess_exec requires ProactorEventLoop which
    uvicorn/FastAPI may not provide.
    """

    def _sync_run() -> tuple[int, str, str]:
        # BF-892 (#1543): the allowlist. This git runs in the tree the model writes
        # into, so its config and hooks are not ProbOS's own; these local verbs need
        # only PATH and the home variables (identity from ~/.gitconfig), HOME included.
        result = subprocess.run(
            ["git", *HARDENED_GIT_CONFIG_ARGS, *args],  # BF-904a: no repository hook or fsmonitor runs
            env=build_command_env(_GIT_HOME_NAMES),
            cwd=work_dir,
            capture_output=True,
        )
        return (
            result.returncode,
            (result.stdout or b"").decode(errors="replace").strip(),
            (result.stderr or b"").decode(errors="replace").strip(),
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_run)
```
REPLACE:
```python
async def _run_git(args: list[str], work_dir: str, *, lossless: bool = False) -> tuple[int, str, str]:
    """Run a git command asynchronously.  Returns (returncode, stdout, stderr).

    Uses subprocess.run in a thread executor for Windows compatibility —
    asyncio.create_subprocess_exec requires ProactorEventLoop which
    uvicorn/FastAPI may not provide.

    BF-904a A1: with *lossless*, stdout is decoded with ``surrogateescape`` and not stripped,
    so two outputs are equal exactly when their bytes are. That text can hold lone surrogates:
    it stays in memory, or passes through ``_display_token`` before any message, log or event.
    """

    def _sync_run() -> tuple[int, str, str]:
        # BF-892 (#1543): the allowlist. This git runs in the tree the model writes
        # into, so its config and hooks are not ProbOS's own; these local verbs need
        # only PATH and the home variables (identity from ~/.gitconfig), HOME included.
        result = subprocess.run(
            ["git", *HARDENED_GIT_CONFIG_ARGS, *args],  # BF-904a: no repository hook or fsmonitor runs
            env=build_command_env(_GIT_HOME_NAMES),
            cwd=work_dir,
            capture_output=True,
        )
        stdout = result.stdout or b""
        return (
            result.returncode,
            stdout.decode(errors="surrogateescape") if lossless else stdout.decode(errors="replace").strip(),  # BF-904a A1: lossless only on request
            (result.stderr or b"").decode(errors="replace").strip(),
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_run)
```

### A1.3 `src/probos/cognitive/builder.py`: the snapshot block (against `builder.py:1686-1784`, whole)
SEARCH:
```python
#: BF-904a (#1585): the listing of every config source git resolves for a tree (system, global,
#: the repository's shared config, config.worktree, every include). Its values never leave memory.
_GIT_CONFIG_LISTING_ARGS: tuple[str, ...] = ("config", "--list", "--show-origin", "-z")


@dataclass(frozen=True)
class _GitSafetySnapshot:
    """BF-904a (#1585): what git would run on its own in a tree, read before model code runs."""

    config: str  # the `git config --list --show-origin -z` listing
    hooks_dir: Path | None  # the repository's own hooks directory; None outside a repository
    hooks: tuple[tuple[str, str], ...]  # (entry name, sha256 of its bytes or "dir"), by name


def _hooks_listing(hooks_dir: Path | None) -> tuple[tuple[str, str], ...] | None:
    """BF-904a: each entry of *hooks_dir* with the sha256 of its bytes ("dir" for a directory).

    Read in Python, so no git runs. A missing directory is an empty listing; any other read
    failure is None, which the caller counts as a change.
    """
    if hooks_dir is None:
        return ()
    try:
        entries = sorted(hooks_dir.iterdir(), key=lambda entry: entry.name)
    except FileNotFoundError:
        return ()
    except OSError:
        return None
    listing: list[tuple[str, str]] = []
    try:
        for entry in entries:
            digest = "dir" if entry.is_dir() else hashlib.sha256(entry.read_bytes()).hexdigest()
            listing.append((entry.name, digest))
    except OSError:
        return None
    return tuple(listing)


def _config_change_names(before: str, after: str) -> str:
    """BF-904a: the sources and keys whose entries differ between two `-z` listings, never a value."""

    def entries(listing: str) -> set[tuple[str, str]]:
        fields = listing.split("\0")
        return {(fields[i], fields[i + 1]) for i in range(0, len(fields) - 1, 2)}

    differing = entries(before) ^ entries(after)
    names = sorted({origin + " " + entry.split("\n", 1)[0] for origin, entry in differing})
    shown = ", ".join(names[:10]) + (", ..." if len(names) > 10 else "")
    return f"({shown})" if shown else "(the listing changed)"


async def _git_safety_snapshot(work_dir: str) -> _GitSafetySnapshot | None:
    """BF-904a (#1585): the resolved git config and the hooks directory of *work_dir*, or None.

    None means the config listing or the hooks directory could not be read; the comparison
    after the tests counts that as a change.
    """
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir)
        if rc != 0:
            return None
        rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir)
    except (OSError, ValueError):
        return None
    # `--git-common-dir`, not `--git-path hooks`: under the core.hooksPath override the latter
    # names the null device. Outside a repository there is no hooks directory to watch; a
    # repository appearing during the tests changes the config listing instead.
    hooks_dir = Path(work_dir, common_dir, "hooks") if rc == 0 else None
    hooks = _hooks_listing(hooks_dir)
    if hooks is None:
        return None
    return _GitSafetySnapshot(config=config, hooks_dir=hooks_dir, hooks=hooks)


async def _git_safety_change(work_dir: str, before: _GitSafetySnapshot | None) -> str | None:
    """BF-904a (#1585): what changed since *before* in the config git resolves or the hooks directory.

    None when nothing changed. A capture that failed, before the tests or now, is a change: git
    is not run again when it cannot be shown to be as it was. The text names config sources and
    keys and hook file names only, never a value or a file's content.
    """
    if before is None:
        return "the git configuration or hooks directory could not be read before the tests"
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir)
    except (OSError, ValueError):
        rc, config = 1, ""
    if rc != 0:
        return "the git configuration could not be read after the tests"
    changes: list[str] = []
    if config != before.config:  # BF-904a: a filter, an include or any other config source changed
        changes.append("git config " + _config_change_names(before.config, config))
    hooks = _hooks_listing(before.hooks_dir)
    if hooks is None:
        changes.append(f"the hooks directory {before.hooks_dir} could not be read")
    elif hooks != before.hooks:  # BF-904a: a hook file appeared, changed or went away
        names = sorted({name for name, _digest in set(hooks) ^ set(before.hooks)})
        changes.append(f"hook files in {before.hooks_dir}: " + ", ".join(names))
    return "; ".join(changes) or None
```
REPLACE:
```python
#: BF-904a (#1585): the listing of every config source git resolves for a tree (system, global,
#: the repository's shared config, config.worktree, every include). Its values never leave memory.
_GIT_CONFIG_LISTING_ARGS: tuple[str, ...] = ("config", "--list", "--show-origin", "-z")
#: BF-904a A1: a resolved config is kilobytes (git documents about a thousand keys). Its comparison
#: and name parse run on the event loop, so a listing past 4 Mi characters is a failed capture.
_GIT_CONFIG_LISTING_MAX_CHARS = 4 * 1024 * 1024
#: BF-904a A1: the bounds of one hooks listing (`_hooks_listing`, run in a worker thread). git knows
#: about 30 hook names and `git init` writes 14 samples, so 256 entries is several full directories;
#: a directory of thousands stops at the 257th name. Past a bound the listing is a failed capture
#: (D6): the build is refused, never committed on a partial listing.
_HOOKS_MAX_ENTRIES = 256
#: Hook scripts are kilobytes and a compiled hook a few megabytes; hashing 64 MiB takes well under a
#: second off the event loop.
_HOOKS_MAX_TOTAL_BYTES = 64 * 1024 * 1024
#: One read: the most of a hook file held in memory at once.
_HOOKS_READ_CHUNK = 64 * 1024
#: The one open of a regular entry: bytes on Windows; on POSIX never follow a link, nor block on a
#: pipe, swapped in after the lstat. A flag the platform lacks is 0, a no-op.
_HOOK_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
#: BF-904a A1: how much of a name a refusal shows (`_display_token`). git's keys and hook names are
#: under 50 characters, so 100 keeps every real one whole; a path is cut at 200. With at most 10
#: names of each kind, a refusal's whole text stays under 6,000 characters.
_DISPLAY_NAME_CHARS = 100
_DISPLAY_PATH_CHARS = 200
_GIT_CHANGE_NAMES_SHOWN = 10


@dataclass(frozen=True)
class _GitSafetySnapshot:
    """BF-904a (#1585): what git would run on its own in a tree, read before model code runs."""

    # BF-904a A1: the lossless `git config --list --show-origin -z` listing. Global config can hold
    # credentials and the text can hold lone surrogates, so it is kept out of repr and never formatted.
    config: str = field(repr=False)
    hooks_dir: Path | None  # the repository's own hooks directory; None when no repository was shown at entry
    hooks: tuple[tuple[str, str], ...]  # (entry name, its `_hooks_listing` token), by name


def _escaped_char(ch: str) -> str:
    """BF-904a A1: one character as a Python escape."""
    code = ord(ch)
    if ch == "\\":
        return "\\\\"
    if code < 0x100:
        return f"\\x{code:02x}"
    if code < 0x10000:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"


def _display_token(text: str, limit: int) -> str:
    """BF-904a A1: *text* as one inline-code token, safe in a log record, an event and Markdown.

    Every character that is not printable (controls, line and paragraph separators, format
    characters such as bidi overrides, lone surrogates), and the backslash and the backtick, is a
    Python escape: the token is one line, encodes as UTF-8, and cannot close its code span, inside
    which Markdown is literal. At most *limit* characters of the escaped form are kept, never half
    an escape; the rest are counted, not shown.
    """
    shown: list[str] = []
    width = 0
    for index, ch in enumerate(text):
        piece = ch if ch.isprintable() and ch not in "\\`" else _escaped_char(ch)
        if width + len(piece) > limit:
            return "`" + "".join(shown) + f"` ...[{len(text) - index} more characters]"
        shown.append(piece)
        width += len(piece)
    return "`" + "".join(shown) + "`"


def _listed(names: list[str], total: int) -> str:
    """BF-904a A1: *names* (the first escaped tokens) joined, then how many of *total* were not shown."""
    hidden = total - len(names)
    return ", ".join(names) + (f", ...[{hidden} more]" if hidden > 0 else "")


def _hooks_listing(hooks_dir: Path | None) -> tuple[tuple[str, str], ...] | None:
    """BF-904a: each entry of *hooks_dir* with a token for what git could run from it, or None.

    Read in Python, so no git runs; it blocks, so the build calls it through `_read_hooks`.
    A1: each entry is classified by `os.lstat`, never followed. A regular file is
    ``file:<permission bits>:<sha256>`` (the bits, because a chmod makes a present file run), a
    symlink ``link:<target>``, a directory ``dir``, anything else (a pipe, a device, a socket)
    ``other:<file type>``; only regular files are opened. A missing directory is an empty
    listing. An unreadable directory or entry, an entry that is no longer a regular file when
    opened, more than _HOOKS_MAX_ENTRIES entries, or more than _HOOKS_MAX_TOTAL_BYTES bytes in
    all is None, which the caller counts as a change (D6).
    """
    if hooks_dir is None:
        return ()
    names: list[str] = []
    try:
        with os.scandir(hooks_dir) as scan:
            for entry in scan:
                names.append(entry.name)
                if len(names) > _HOOKS_MAX_ENTRIES:  # BF-904a A1: a directory past the entry bound is a failed capture
                    return None
    except FileNotFoundError:
        return ()
    except OSError:
        return None
    listing: list[tuple[str, str]] = []
    total = 0
    try:
        for name in sorted(names):
            path = os.path.join(hooks_dir, name)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):  # BF-904a A1: a link is recorded by its target, never followed
                token = "link:" + os.readlink(path)
            elif stat.S_ISDIR(st.st_mode):
                token = "dir"
            elif not stat.S_ISREG(st.st_mode):  # BF-904a A1: a pipe or device is never opened
                token = f"other:{stat.S_IFMT(st.st_mode):o}"
            else:
                digest = hashlib.sha256()
                fd = os.open(path, _HOOK_OPEN_FLAGS)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):  # BF-904a A1: no longer a regular file when opened
                        return None
                    while chunk := os.read(fd, _HOOKS_READ_CHUNK):
                        total += len(chunk)
                        if total > _HOOKS_MAX_TOTAL_BYTES:  # BF-904a A1: past the byte bound is a failed capture
                            return None
                        digest.update(chunk)
                finally:
                    os.close(fd)
                token = f"file:{stat.S_IMODE(st.st_mode):o}:{digest.hexdigest()}"
            listing.append((name, token))
    except OSError:
        return None
    return tuple(listing)


async def _read_hooks(hooks_dir: Path | None) -> tuple[tuple[str, str], ...] | None:
    """BF-904a A1: `_hooks_listing` in a worker thread, so the build's event loop never blocks on it.

    The thread cannot be interrupted; the listing's bounds keep it short. If the awaiting build is
    cancelled, the thread finishes and its result is dropped; `git_unsafe` is already set, so the
    `finally` block runs no git (D23).
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _hooks_listing, hooks_dir)  # BF-904a A1: off the event loop


def _config_change_names(before: str, after: str) -> str:
    """BF-904a: the sources and keys whose entries differ between two `-z` listings, never a value.

    A1: at most _GIT_CHANGE_NAMES_SHOWN of them, each origin and key a `_display_token`, so no
    control character, lone surrogate or 20,000-character subsection reaches a message raw.
    """

    def entries(listing: str) -> set[tuple[str, str]]:
        fields = listing.split("\0")
        return {(fields[i], fields[i + 1]) for i in range(0, len(fields) - 1, 2)}

    keys = sorted({(origin, entry.split("\n", 1)[0]) for origin, entry in entries(before) ^ entries(after)})
    names = [_display_token(origin, _DISPLAY_PATH_CHARS) + " " + _display_token(key, _DISPLAY_NAME_CHARS) for origin, key in keys[:_GIT_CHANGE_NAMES_SHOWN]]  # BF-904a A1: escaped and bounded
    return f"({_listed(names, len(keys))})" if names else "(the listing changed)"


async def _git_safety_snapshot(work_dir: str, repository_proven: bool) -> _GitSafetySnapshot | None:
    """BF-904a (#1585): the resolved git config and the hooks directory of *work_dir*, or None.

    None means the config listing or the hooks directory could not be read; the comparison
    after the tests counts that as a change. A1: the listing is read lossless, so equal text
    means equal bytes. *repository_proven* is True when an identity was pinned before any model
    code ran; then a hooks location git does not name is a failed capture too.
    """
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir, lossless=True)  # BF-904a A1: lossless baseline
        if rc != 0 or len(config) > _GIT_CONFIG_LISTING_MAX_CHARS:  # BF-904a A1: a listing past its bound is a failed capture
            return None
        rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir)
    except (OSError, ValueError):
        return None
    # `--git-common-dir`, not `--git-path hooks`: under the core.hooksPath override the latter
    # names the null device.
    if rc == 0 and common_dir:  # BF-904a A1: git named the common directory
        hooks_dir: Path | None = Path(work_dir, common_dir, "hooks")
    elif repository_proven:  # BF-904a A1: a repository whose hooks location is unreadable is a failed capture
        return None
    else:
        # D5: no identity was pinned at entry, so no repository was shown and there is no hooks
        # directory to watch; a repository appearing during the tests changes the config listing.
        hooks_dir = None
    hooks = await _read_hooks(hooks_dir)
    if hooks is None:
        return None
    return _GitSafetySnapshot(config=config, hooks_dir=hooks_dir, hooks=hooks)


async def _git_safety_change(work_dir: str, before: _GitSafetySnapshot | None) -> str | None:
    """BF-904a (#1585): what changed since *before* in the config git resolves or the hooks directory.

    None when nothing changed. A capture that failed, before the tests or now, is a change: git
    is not run again when it cannot be shown to be as it was. The text names config sources and
    keys and hook file names only, never a value or a file's content; A1: each name is a
    `_display_token`, so the text is fixed words plus escaped, bounded tokens.
    """
    if before is None:
        return "the git configuration or hooks directory could not be read before the tests"
    try:
        rc, config, _err = await _run_git(list(_GIT_CONFIG_LISTING_ARGS), work_dir, lossless=True)  # BF-904a A1: lossless comparison
    except (OSError, ValueError):
        rc, config = 1, ""
    if rc != 0 or len(config) > _GIT_CONFIG_LISTING_MAX_CHARS:  # BF-904a A1: past its bound after the tests is a failed capture
        return "the git configuration could not be read after the tests"
    changes: list[str] = []
    if config != before.config:  # BF-904a: a filter, an include or any other config source changed
        changes.append("git config " + _config_change_names(before.config, config))
    hooks = await _read_hooks(before.hooks_dir)
    shown_dir = _display_token(str(before.hooks_dir), _DISPLAY_PATH_CHARS)
    if hooks is None:
        changes.append(
            f"the hooks directory {shown_dir} could not be read (an unreadable or changing entry, "
            f"or more than {_HOOKS_MAX_ENTRIES} entries or {_HOOKS_MAX_TOTAL_BYTES // (1024 * 1024)} MiB)"
        )
    elif hooks != before.hooks:  # BF-904a: a hook file appeared, changed or went away
        changed = sorted({name for name, _token in set(hooks) ^ set(before.hooks)})
        names = [_display_token(name, _DISPLAY_NAME_CHARS) for name in changed[:_GIT_CHANGE_NAMES_SHOWN]]  # BF-904a A1: escaped and bounded
        changes.append(f"hook files in {shown_dir}: " + _listed(names, len(changed)))
    return "; ".join(changes) or None
```

### A1.4 `src/probos/cognitive/builder.py`: the baseline, and unsafe from the start of the test phase (against `builder.py:3045-3049`)
SEARCH:
```python
        if run_tests and (written or modified_files):
            # BF-904a (#1585): what git would run on its own, read before any model code runs.
            git_baseline = await _git_safety_snapshot(work_dir)
            tests_ran = True
            all_changes = list(file_changes)  # track for fix prompt
```
REPLACE:
```python
        if run_tests and (written or modified_files):
            # BF-904a (#1585): what git would run on its own, read before any model code runs.
            git_baseline = await _git_safety_snapshot(work_dir, pinned_git_dir is not None)
            tests_ran = True
            # BF-904a A1 (D23): from here model code may run, so git is unsafe until the comparison at
            # 5.4b finds it unchanged; an error or a cancellation before then runs no git in `finally`.
            git_unsafe = True  # BF-904a A1: model code may run from here; only a clean comparison clears it
            all_changes = list(file_changes)  # track for fix prompt
```

### A1.5 `src/probos/cognitive/builder.py`: 5.4b clears `git_unsafe` only on a clean comparison (against `builder.py:3198-3208`; the 5.5 message and K11/K12 lines are unchanged)
SEARCH:
```python
        # 5.4b. BF-904a (#1585): a hook or a config entry (a filter driver, an include) the tests
        # planted would run at the next git command; any change blocks every later git call.
        if tests_ran and not identity_lost:
            git_tampered = await _git_safety_change(work_dir, git_baseline)
            if git_tampered is not None:
                git_unsafe = True  # BF-904a: a changed config or hooks directory blocks every later git call
                logger.error(
                    "BuilderAgent: git configuration or hooks changed while the tests ran (%s); "
                    "refusing to commit and running no further git command",
                    git_tampered,
                )
```
REPLACE:
```python
        # 5.4b. BF-904a (#1585): a hook or a config entry (a filter driver, an include) the tests
        # planted would run at the next git command; any change blocks every later git call.
        # A1: git_unsafe has been set since the test phase began; only a clean comparison clears it.
        if tests_ran and not identity_lost:
            git_tampered = await _git_safety_change(work_dir, git_baseline)
            if git_tampered is None:
                git_unsafe = False  # BF-904a A1: the comparison found git as it was before the tests
            else:
                # BF-904a A1: git_tampered is fixed words plus _display_token tokens, so %s can
                # neither split the record nor carry a control character (%r would double escapes).
                logger.error(
                    "BuilderAgent: git configuration or hooks changed while the tests ran (%s); "
                    "refusing to commit and running no further git command",
                    git_tampered,
                )
```

### A1.6 `tests/test_bf904a_git_hardening.py`: imports
SEARCH:
```python
import asyncio
import logging
import os
```
REPLACE:
```python
import asyncio
import hashlib
import logging
import os
```
SEARCH:
```python
import subprocess
import sys
from collections.abc import Awaitable, Callable
```
REPLACE:
```python
import subprocess
import sys
import threading
from collections.abc import Awaitable, Callable
```
SEARCH:
```python
from typing import Any

import pytest
```
REPLACE:
```python
from typing import Any
from unittest.mock import AsyncMock

import pytest
```
SEARCH:
```python
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS
from probos.worktree_manager import WorktreeManager
```
REPLACE:
```python
from probos.execution.command_env import HARDENED_GIT_CONFIG_ARGS
from probos.security.pii_redaction import LogRedactionFormatter
from probos.worktree_manager import WorktreeManager
```

### A1.7 `tests/test_bf904a_git_hardening.py`: the two wrappers forward `lossless`
SEARCH:
```python
    async def __call__(self, args: list[str], work_dir: str) -> tuple[int, str, str]:
        self.calls.append((self.swapped, list(args)))
        return await self._real(args, work_dir)
```
REPLACE:
```python
    async def __call__(self, args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
        # BF-904a A1: the safety capture reads the config listing with lossless=True; forward it.
        self.calls.append((self.swapped, list(args)))
        return await self._real(args, work_dir, **kwargs)
```
SEARCH:
```python
    async def __call__(self, args: list[str], work_dir: str) -> tuple[int, str, str]:
        if args == CONFIG_ARGS:
            self.config_reads += 1
            if (self._when == "before" and self.config_reads == 1) or (self._when == "after" and self.tests_ran):
                self.injected += 1
                return 1, "", "fatal: bf904a"
        return await self._real(args, work_dir)
```
REPLACE:
```python
    async def __call__(self, args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
        # BF-904a A1: forward lossless=True to the real runner.
        if args == CONFIG_ARGS:
            self.config_reads += 1
            if (self._when == "before" and self.config_reads == 1) or (self._when == "after" and self.tests_ran):
                self.injected += 1
                return 1, "", "fatal: bf904a"
        return await self._real(args, work_dir, **kwargs)
```

### A1.8 `tests/test_bf904a_git_hardening.py`: `_Unreadable` follows the listing's own calls
SEARCH:
```python
class _Unreadable:
    """Patches ``Path.iterdir`` or ``Path.read_bytes`` so that, for the hooks directory (``iterdir``) or a direct child of it
    (``read_bytes``), the first listing (``before``) or every one made after the tests ran (``after``) raises ``PermissionError``."""

    def __init__(self, hooks_dir: Path, target: str, when: str) -> None:
        self._hooks_dir = hooks_dir.resolve()
        self._target = target
        self._when = when
        self.injected = 0
        self.tests_ran = False

    def mark_tests_ran(self) -> None:
        self.tests_ran = True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = getattr(Path, self._target)
        guard = self

        def wrapper(path: Path, *args: Any, **kwargs: Any) -> Any:
            watched = path.resolve() if guard._target == "iterdir" else path.resolve().parent
            if watched == guard._hooks_dir and (
                (guard._when == "before" and guard.injected == 0 and not guard.tests_ran)
                or (guard._when == "after" and guard.tests_ran)
            ):
                guard.injected += 1
                raise PermissionError(13, "bf904a: unreadable", str(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(Path, self._target, wrapper)
```
REPLACE:
```python
class _Unreadable:
    """Patches ``os.scandir`` or ``os.open`` so that, for the hooks directory (``scandir``) or a direct child of it
    (``open``), the first listing (``before``) or every one made after the tests ran (``after``) raises ``PermissionError``.
    BF-904a A1: the listing reads through ``os.scandir``, ``os.lstat`` and ``os.open`` now (it used ``Path.iterdir`` and
    ``Path.read_bytes``), so the injection point moved with it; what is injected, and when, is unchanged."""

    def __init__(self, hooks_dir: Path, target: str, when: str) -> None:
        self._hooks_dir = hooks_dir.resolve()
        self._target = target
        self._when = when
        self.injected = 0
        self.tests_ran = False

    def mark_tests_ran(self) -> None:
        self.tests_ran = True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = getattr(os, self._target)
        guard = self

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            path = args[0] if args else None
            if isinstance(path, (str, os.PathLike)):
                resolved = Path(path).resolve()
                watched = resolved if guard._target == "scandir" else resolved.parent
                if watched == guard._hooks_dir and (
                    (guard._when == "before" and guard.injected == 0 and not guard.tests_ran)
                    or (guard._when == "after" and guard.tests_ran)
                ):
                    guard.injected += 1
                    raise PermissionError(13, "bf904a: unreadable", str(path))
            return real(*args, **kwargs)

        monkeypatch.setattr(os, self._target, wrapper)
```
SEARCH:
```python
    unreadable = _Unreadable(hooks_dir, "iterdir" if target == "iterdir" else "read_bytes", when)
```
REPLACE:
```python
    unreadable = _Unreadable(hooks_dir, "scandir" if target == "iterdir" else "open", when)  # BF-904a A1: the listing's own calls
```

### A1.9 `tests/test_bf896_executor_identity_and_blocks.py`: `_GitSpy` forwards `lossless` (the run-tests probe at `:768` reaches the baseline)
SEARCH:
```python
    async def __call__(self, args: list[str], work_dir: str) -> tuple[int, str, str]:
        self.calls.append((self.swapped, list(args)))
        return await self._real(args, work_dir)
```
REPLACE:
```python
    async def __call__(self, args: list[str], work_dir: str, **kwargs: Any) -> tuple[int, str, str]:
        # BF-904a A1: the safety capture reads the config listing with lossless=True; forward it.
        self.calls.append((self.swapped, list(args)))
        return await self._real(args, work_dir, **kwargs)
```

### A1.10 New tests (append to `tests/test_bf904a_git_hardening.py` under `# BF-904a A1`; write and run them first, and each must fail on the candidate)

Conventions:
- Builder privates are reached through `builder_module.`.
- Patched module constants use `monkeypatch.setattr(builder_module, "<NAME>", value)`.
- Each build test asserts its premise first.
- Plant hooks with `_plant_hook` (from `_common_dir(...) / "hooks"`) or with plain `write_bytes`.

**Shared helpers (full code):**
```python
def _stat_as(real: os.stat_result, mode: int) -> os.stat_result:
    """*real* with st_mode replaced: the seam that stands for a pipe, a link or other mode bits on any OS."""
    return os.stat_result((mode,) + tuple(real)[1:10])


class _ListingSeam:
    """Answers os.lstat / os.readlink / os.fstat for named hook entries and records each open, read and close.
    A FIFO, a device and a symlink are not creatable portably (Windows), so a real regular file stands in."""

    def __init__(self, hooks_dir: Path) -> None:
        self.hooks_dir = hooks_dir.resolve()
        self.modes: dict[str, int] = {}
        self.links: dict[str, str] = {}
        self.fstat_modes: dict[str, int] = {}
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.reads: list[int] = []
        self._fds: dict[int, str] = {}

    def _name(self, path: Any) -> str | None:
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve().parent == self.hooks_dir:
            return Path(path).name
        return None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = {name: getattr(os, name) for name in ("lstat", "readlink", "open", "fstat", "read", "close")}
        seam = self

        def lstat(path: Any, *a: Any, **k: Any) -> os.stat_result:
            st, name = real["lstat"](path, *a, **k), seam._name(path)
            return _stat_as(st, seam.modes[name]) if name in seam.modes else st

        def readlink(path: Any, *a: Any, **k: Any) -> str:
            name = seam._name(path)
            return seam.links[name] if name in seam.links else real["readlink"](path, *a, **k)

        def open_(path: Any, *a: Any, **k: Any) -> int:
            fd, name = real["open"](path, *a, **k), seam._name(path)
            if name is not None:
                seam.opened.append(name)
                seam._fds[fd] = name
            return fd

        def fstat(fd: int, *a: Any, **k: Any) -> os.stat_result:
            st, name = real["fstat"](fd, *a, **k), seam._fds.get(fd)
            return _stat_as(st, seam.fstat_modes[name]) if name in seam.fstat_modes else st

        def read(fd: int, n: int, *a: Any, **k: Any) -> bytes:
            if fd in seam._fds:
                seam.reads.append(n)
            return real["read"](fd, n, *a, **k)

        def close(fd: int, *a: Any, **k: Any) -> None:
            name = seam._fds.pop(fd, None)
            if name is not None:
                seam.closed.append(name)
            return real["close"](fd, *a, **k)

        for name, fn in (("lstat", lstat), ("readlink", readlink), ("open", open_), ("fstat", fstat), ("read", read), ("close", close)):
            monkeypatch.setattr(os, name, fn)
```

| ID | Test | Asserts |
|---|---|---|
| N1 | `test_the_hooks_listing_records_each_entry_kind_and_opens_only_regular_files` (sync, unit) | **Setup:** `hooks = tmp_path/"hooks"` with real files `pre-commit` (`b"a"`), `pre-push` (`b"b"`), `post-merge` (`b""`) and a directory `sub`. Seam: `modes = {"pre-commit": S_IFREG\|0o644, "pre-push": S_IFLNK\|0o777, "post-merge": S_IFIFO\|0o644}`, `links = {"pre-push": "target-a"}`. **First listing:** `_hooks_listing(hooks) == (("post-merge", f"other:{stat.S_IFIFO:o}"), ("pre-commit", "file:644:" + sha256(b"a")), ("pre-push", "link:target-a"), ("sub", "dir"))`; `opened == ["pre-commit"]`; `closed == ["pre-commit"]`. **Re-pointed link:** after `links["pre-push"] = "target-b"`, only the `pre-push` token differs and is `"link:target-b"`. **chmod:** after `modes["pre-commit"] = S_IFREG\|0o755`, only the `pre-commit` token differs and starts with `"file:755:"`. Kills K16, K17, K21. |
| N2 | `test_an_entry_no_longer_regular_when_opened_fails_the_listing` (sync) | **Control:** `hooks/pre-commit` (`b"a"`) gives a listing that is not None. **Probe:** `fstat_modes = {"pre-commit": S_IFIFO\|0o644}` gives `_hooks_listing(hooks) is None`, with `opened == ["pre-commit"]` and `closed == ["pre-commit"]` (the fd is closed). Kills K18. |
| N3 | `test_the_hooks_listing_is_bounded` (sync, parametrised `bound` over `entries`, `bytes`) | **First**, before any patch: `(builder_module._HOOKS_MAX_ENTRIES, _HOOKS_MAX_TOTAL_BYTES, _HOOKS_READ_CHUNK, _GIT_CONFIG_LISTING_MAX_CHARS) == (256, 64 * 1024 * 1024, 64 * 1024, 4 * 1024 * 1024)`. **`entries`:** with `_HOOKS_MAX_ENTRIES = 3`, three empty files give a listing of 3; a fourth gives None. **`bytes`:** with `_HOOKS_MAX_TOTAL_BYTES = 100` and `_HOOKS_READ_CHUNK = 16`, files `a` (50 bytes) and `b` (50 bytes) give a listing, and with the seam installed `seam.reads` is non-empty and every entry is `16`; appending one byte to `b` gives None. Kills K15, K19, K20. |
| N4 | `test_the_hooks_listing_runs_off_the_event_loop` | `loop_thread = threading.get_ident()`. Wrap `builder_module._hooks_listing` with a recorder that appends `threading.get_ident()` and calls the real one. A `[create NEW]` build in `_plain_repo` with `run_tests=True` and `_FakeTests()` commits. The recorder ran exactly twice, and `loop_thread not in threads`. Kills K14. |
| N5 | `test_a_capture_past_a_bound_refuses_the_build` (parametrised `case`) | **Measure first:** `n_cfg = len((await builder_module._run_git(list(CONFIG_ARGS), str(probe), lossless=True))[1])`, `n_ent = len(os.listdir(hooks))`, `n_bytes = sum` of the regular files' sizes (premise: `n_ent >= 1`). **`config-before`:** `_GIT_CONFIG_LISTING_MAX_CHARS = n_cfg - 1` gives `"could not be read before the tests"`. **`config-after`:** bound `n_cfg`, and the fake runs plain `git config bf904a.grow 1`, giving `"could not be read after the tests"`. **`entries-before`:** `_HOOKS_MAX_ENTRIES = n_ent - 1` gives `"could not be read before the tests"`. **`entries-after`:** bound `n_ent`, and the fake writes `hooks/extra.sample`, giving `"the hooks directory"` and `"could not be read"` in the error with no `"before the tests"`. **`bytes-after`:** `_HOOKS_MAX_TOTAL_BYTES = n_bytes`, and the fake appends one byte to an existing sample (the same assertion). **Every case:** `success is False`, no `commit_hash`, `fake.runs == 1`. Kills K15, K19, K35, K36. |
| N6 | `test_a_config_value_that_differs_only_in_undecodable_bytes_is_refused` | **Premise (sibling repo):** append `b"[bf904a]\n\tkey = \x80\n"` to `_common_dir(s)/"config"`. Read `_run_git(list(CONFIG_ARGS), s)` as text A, replace `\x80` with `\x81`, and read text B. Assert `A == B` (the lossy default collides on this git) and that the two `lossless=True` reads differ. **Control (fresh repo with the `\x80` config, unchanged):** the build commits, so a non-UTF-8 config is no false positive. **Probe:** the fake rewrites `key = \x80` to `key = \x81`. Then `success is False`; `REFUSAL`, `"bf904a.key"` and `` "`" `` are in the error; `"\ufffd"` is not; `result.error.encode("utf-8")` succeeds. Kills K22, K23, K24. |
| N7 | `test_display_tokens_are_escaped_bounded_and_markdown_literal` (sync, unit) | `_display_token("a\nb\rc\x1bd\u202ee\udc80f`g\\h*_[x](y)<z>", 100) == "`a\\x0ab\\x0dc\\x1bd\\u202ee\\udc80f\\x60g\\\\h*_[x](y)<z>`"`. `_display_token("k" * 20013, 100) == "`" + "k" * 100 + "` ...[19913 more characters]"`. `_display_token("k" * 99 + "\x1b" + "z", 100) == "`" + "k" * 99 + "` ...[2 more characters]"` (an escape is never split). `_display_token("k" * 100, 100) == "`" + "k" * 100 + "`"`. `_display_token("\U0001f600\U000e0001", 100) == "`\U0001f600\\U000e0001`"`. `_config_change_names("file:c\0a.b\nv\0", after)`, where `after` adds 12 entries `file:c\0z.k{i:02d}\nv\0`, ends with `", ...[2 more])"` and holds exactly 10 `` "`file:c`" `` tokens. `"secret-value" not in repr(builder_module._GitSafetySnapshot(config="file:x\0user.password\nsecret-value\0", hooks_dir=None, hooks=()))`. Kills K29, K30, K33, K34. |
| N8 | `test_hostile_config_and_hook_names_reach_no_message_raw` (`caplog` at DEBUG) | **Probe:** the fake appends `b'[bf904a "a\rb\x1bc\x80\xe2\x80\xae`' + b"s" * 20000 + b'"]\n\tkey = v\n'` to the probe's config and writes the regular file `hooks/("h" * 120)`. **Premise:** plain `git config --list -z` (`_REAL_RUN`, bytes, `env=_control_env()`, `timeout=60`) returns rc 0 and its stdout contains `b"\x1b"` and `b"\r"`. **Assert:** `success is False`; `REFUSAL` is in the error; `all(ch.isprintable() for ch in result.error)`; `len(result.error) < 6000`; every one of `"\\x0d"`, `"\\x1b"`, `"\\udc80"`, `"\\u202e"`, `"\\x60"` and `"h" * 100` is in the error; neither `"s" * 101` nor `"h" * 101` is in it. Then take `[record]`, the builder records whose message contains `"git configuration or hooks changed"`; `rendered = LogRedactionFormatter("%(message)s").format(record)` contains none of `"\r"`, `"\n"`, `"\x1b"`, and `all(ch.isprintable() for ch in rendered)`. Kills K29 to K32. |
| N9 | `test_a_hooks_location_git_does_not_name_is_a_failed_capture_in_a_repository` (parametrised `case` over `nonzero`, `empty`, `unproven`) | **Wrapper `_CommonDirAnswers(real, outcome)`:** `(args, work_dir, **kwargs)`; it answers `["rev-parse", "--git-common-dir"]` with the outcome and counts `asked`; every other call goes to the real runner, kwargs forwarded. **Control first:** the same build with no wrapper commits. **`nonzero`** `(128, "", "fatal: bf904a")` and **`empty`** `(0, "", "")`: `success is False` and the error holds `"could not be read before the tests"`. **`unproven`:** the nonzero outcome plus `monkeypatch.setattr(builder_module, "repository_identity", AsyncMock(return_value=None))` (no pin, so D5 applies): the build commits. **Every case:** `asked == 1`. Kills K25 to K28. |
| N10 | `test_an_error_or_cancellation_after_the_test_phase_began_runs_no_git` (parametrised `raised` over `error`, `cancel`) | **Control first:** a `_GitSpy` and a fake whose model code sets `spy.swapped`, with the real comparison. The build commits; `["checkout", "main"] in spy.args_after_swap()`; plain `git symbolic-ref --short HEAD` gives `"main"`. **Probe:** patch `builder_module._git_safety_change` with an async function that raises `RuntimeError("bf904a-injected")` or `asyncio.CancelledError()`. **`error`:** through `_build`: `success is False`, `"bf904a-injected"` is in the error. **`cancel`:** `task = asyncio.ensure_future(execute_approved_build(...))`, then `await asyncio.wait({task}, timeout=120)` and assert `task.cancelled()`. **Both:** `spy.args_after_swap() == [IDENTITY_ARGS]`; HEAD names `result.branch_name` (error case) or the branch that `["checkout", "-b", X]` in `spy.args_before_swap()` named (cancel case); `NEW` does not exist. Kills K9′, K13. |

M1's file now has 27 test functions. All 17 of M1's existing cases stay green: H2's `[IDENTITY_ARGS, CONFIG_ARGS]` sequence is unchanged, and H2, H4 to H6 and F2 still find their names as substrings inside the tokens.

### A1.11 Partition P1 rows (whole stripped lines, each unique in the A1-built `builder.py`; count each before mutating)
K9 is **replaced**: its old line is gone. Re-run K1 to K8 and K10 to K12; their anchors are unchanged, but `builder.py` has a new sha256.

| ID | SEARCH | REPLACE | Killed by |
|---|---|---|---|
| K9′ | `git_unsafe = True  # BF-904a A1: model code may run from here; only a clean comparison clears it` | `pass` | H2, N10 |
| K13 | `git_unsafe = False  # BF-904a A1: the comparison found git as it was before the tests` | `pass` | N10 (control) |
| K14 | `return await loop.run_in_executor(None, _hooks_listing, hooks_dir)  # BF-904a A1: off the event loop` | `return _hooks_listing(hooks_dir)` | N4 |
| K15 | `if len(names) > _HOOKS_MAX_ENTRIES:  # BF-904a A1: a directory past the entry bound is a failed capture` | `if False:` | N3[entries], N5[entries-*] |
| K16 | `if stat.S_ISLNK(st.st_mode):  # BF-904a A1: a link is recorded by its target, never followed` | `if False:` | N1 |
| K17 | `elif not stat.S_ISREG(st.st_mode):  # BF-904a A1: a pipe or device is never opened` | `elif False:` | N1 |
| K18 | `if not stat.S_ISREG(os.fstat(fd).st_mode):  # BF-904a A1: no longer a regular file when opened` | `if False:` | N2 |
| K19 | `if total > _HOOKS_MAX_TOTAL_BYTES:  # BF-904a A1: past the byte bound is a failed capture` | `if False:` | N3[bytes], N5[bytes-after] |
| K20 | `while chunk := os.read(fd, _HOOKS_READ_CHUNK):` | `while chunk := os.read(fd, _HOOKS_MAX_TOTAL_BYTES + 1):` | N3[bytes] |
| K21 | `token = f"file:{stat.S_IMODE(st.st_mode):o}:{digest.hexdigest()}"` | `token = f"file:{digest.hexdigest()}"` | N1 |
| K22 | `stdout.decode(errors="surrogateescape") if lossless else stdout.decode(errors="replace").strip(),  # BF-904a A1: lossless only on request` | `stdout.decode(errors="replace").strip(),` | N6 |
| K23 | (the baseline read, `… lossless=True)  # BF-904a A1: lossless baseline`) | the same without `, lossless=True` | N6 (control) |
| K24 | (the comparison read, `… lossless=True)  # BF-904a A1: lossless comparison`) | the same without `, lossless=True` | N6 (control) |
| K25 | `if rc == 0 and common_dir:  # BF-904a A1: git named the common directory` | `if rc == 0:` | N9[empty] |
| K26 | `elif repository_proven:  # BF-904a A1: a repository whose hooks location is unreadable is a failed capture` | `elif False:` | N9[nonzero], N9[empty] |
| K27 | (K26's line) | `elif True:` | N9[unproven] |
| K28 | `git_baseline = await _git_safety_snapshot(work_dir, pinned_git_dir is not None)` | `git_baseline = await _git_safety_snapshot(work_dir, False)` | N9[nonzero], N9[empty] |
| K29 | ``piece = ch if ch.isprintable() and ch not in "\\`" else _escaped_char(ch)`` | `piece = ch` | N7, N8 |
| K30 | `if width + len(piece) > limit:` | `if False:` | N7, N8 |
| K31 | (the `names = [_display_token(origin, …` line in `_config_change_names`) | `names = [origin + " " + key for origin, key in keys[:_GIT_CHANGE_NAMES_SHOWN]]` | N8 |
| K32 | (the `names = [_display_token(name, …` line in `_git_safety_change`) | `names = [name for name in changed[:_GIT_CHANGE_NAMES_SHOWN]]` | N8 |
| K33 | (K31's line) | the same with `keys` in place of `keys[:_GIT_CHANGE_NAMES_SHOWN]` | N7 |
| K34 | `config: str = field(repr=False)` | `config: str` | N7 |
| K35 | `if rc != 0 or len(config) > _GIT_CONFIG_LISTING_MAX_CHARS:  # BF-904a A1: a listing past its bound is a failed capture` | `if rc != 0:` | N5[config-before] |
| K36 | `if rc != 0 or len(config) > _GIT_CONFIG_LISTING_MAX_CHARS:  # BF-904a A1: past its bound after the tests is a failed capture` | `if rc != 0:` | N5[config-after] |

Mark the result as the campaign of record against the A1-built `builder.py` sha256 and the test file's sha256.

### A1.12 Supersessions (the original lines stay)

**Decisions:**
- **D4:** append "A1: with a pin, an empty or failed `--git-common-dir` is a failed capture (D22)."
- **D5:** "Outside a repository the baseline has no hooks directory" now reads "With no identity pinned at entry, the baseline has no hooks directory."
- **D6:** append "so is a listing past its bounds (D20, D24), and any error or cancellation between the start of the test phase and a clean comparison (D23)."

**Section 2c note (line 250):** "The decision to refuse uses equality of the lossless listing (equal text means equal bytes) and does not depend on the parse."

**Section 4a preamble (line 471):** "No mock of the git runner" now carries the exception "except A1's injected answers (N9, H3) and the `os` seams of N1 to N3 and `_Unreadable`".

**Section 5g REPLACE:** the comment at lines 771-772 reads "…no git runs at all: identity lost, config or hooks changed, or the test phase ended without a clean comparison (A1)." The message at line 783 is unchanged.

**Sections 7a and 9a:** a new test file that copies `_GitSpy` copies the A1 form, which forwards `**kwargs`.

**Header and tests summary:**
- **Line 5:** M1 has 27 test functions (N1 to N10 added). Updated helpers: A1.7 to A1.9.
- **Tests summary (line 1548):** add N1 to N10. Boundaries: limits (N3, N5), lossless (N6), escaping (N7, N8), fail-closed (N9, N10).

**Hard stops (line 1569):** add N6's and N8's premises. **Pre-decided fallback:** if this git refuses or rewrites CR inside a quoted subsection, drop `\r` from N8's plant and its assertion, keep the rest, and report it.

**Diff Reviewer properties:**
- **Property 1:** append "`_run_git` gains only a keyword-only `lossless` flag; no new launch site."
- **Property 2:** append "`git_unsafe` is set when the test phase begins and cleared only by a clean comparison; an exception or a cancellation in between runs no git (N10)."
- **Property 4:** "The hooks listing runs in a worker thread, is classified by `os.lstat` without following, opens only regular files (`O_NOFOLLOW`/`O_NONBLOCK`, re-checked by `fstat`), reads 64 KiB chunks, and fails the capture past 256 entries or 64 MiB; the only git the check runs is the lossless config listing, skipped when the identity is already lost."
- **Property 5:** append "Every origin, key, hook name and hooks path in a message or log is a `_display_token` (escaped, inline code, at most 100 or 200 characters, at most 10 of each kind); the snapshot's config is excluded from `repr`."
- **New 5a:** "The config comparison is byte-exact; an unchanged non-UTF-8 config does not refuse (N6)."
- **New 5b:** "With a pin, a hooks location git does not name refuses; without one it is D5's path (N9)."

**Other sections:**
- **Mutation table:** K9 replaced and K13 to K36 added (A1.11).
- **Tracking:** the DECISIONS entry lists D1 to D24.
- **What this does NOT change:** the HXI is still unchanged.

### A1.13 Considered, deferred
- **Bounding git's own stdout capture.** `subprocess.run(capture_output=True)` in `_run_git` still reads a huge listing whole, in the worker thread. That memory cost already exists for every `_run_git` call. Fixing it needs streaming in the one launch site, so it goes to BF-904b or AD-1335. D24 bounds the work on the event loop.
- **A shared display-token helper in `probos/utils/text_sanitize.py`.** Deferred until there is a second caller.
- **Symlink targets outside the hooks directory.** Their content is not watched, the same residual as D4's `core.hooksPath`. The override stops them running.
- **`classify_build_failure` substring matching.** A planted key named `SyntaxError` would misfile the category. BF-904b item 4 owns that classifier.

### Absence Verified (A1, 2026-10-18)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No existing escape helper covers controls, surrogates and Markdown | Grep `def (normalise_error\|_safe_exception_text\|\w*escape\w*\|\w*sanitiz\w*\|\w*display\w*\|\w*truncat\w*\|\w*printable\w*)\(` in `src/probos`; Grep `_safe_exception_text\|isprintable\(\)\|backslashreplace` | `fault_report.py:124`, `command_escalation.py:150` (surrogates only), `provider_setup.py:376` (spaces); no `_safe_exception_text` | yes |
| No test calls the safety functions directly | Grep `_git_safety_snapshot\|_git_safety_change\|_hooks_listing\|_config_change_names` in `tests/` | none | yes |
| The `_run_git` replacements with a strict signature are exactly three | Grep `async def __call__\(self, args: list\[str\], work_dir: str\)` in `tests/`, plus every `"_run_git"` patch site | `bf896:179`, `bf904a:212`, `:250`; the other builder patches are AsyncMock (`bf894:142`, `bf897:502`, `bf898:381`); `bf896:880/896/947` call `repository_identity` only | yes |
| `stat` is not already a name in `builder.py` | Grep `\bstat\b` | none | yes |
| No Section 5 to 9 SEARCH anchors on A1's lines | Grep the contract for `git_tampered\|_git_safety\|_hooks_listing\|No further git command\|all_changes = list\(file_changes\)\|def __call__\(self, args` | Sections 2 and 4 and the K rows only | yes |

### Verified Against Codebase (A1, staged candidate)
```
builder.py:15-17 import os/re/subprocess; :19 from dataclasses import dataclass, field
builder.py:1592-1617 _run_git (decode errors="replace" at :1612)
builder.py:1686-1784 snapshot block (read whole)
builder.py:2839-2841 pinned_git_dir = expected_git_dir / repository_identity
builder.py:2875-2878 checkout -b failure returns before any test
builder.py:3045-3049 baseline; :3198-3208 5.4b; :3285-3297 except Exception, finally checkout/branch -D gated on git_unsafe
identity_key_store.py:226 getattr(os, "O_BINARY", 0) precedent
pii_redaction.py:76-81 LogRedactionFormatter.format
test_builder_agent.py:2181 (subprocess.run mock), :3117-3134 (real _run_git, success expected)
test_bf904a_git_hardening.py:29-45 imports, :204-256 _GitSpy/_ConfigReadFails, :539-586 _Unreadable
test_bf896_executor_identity_and_blocks.py:171-188 _GitSpy, :758-776 run_tests probe
```

## Amendment A2 (2026-10-18): the common-directory path is read byte-exactly, and the listing seam resolves no path

**Revised by:** the orchestrator (Claude Sonnet 5.5, Delegated AD Execution Mode), 2026-10-18, after M1 review round 2 (`gpt-6.1-sol`, review of the whole candidate, tree `645b9a09`: two P2 findings with ordinary reach, everything else verified, all 44 requested mutants killed). A2 is the mechanical consequence of D19 (byte-exact reads for the safety capture) and D22 (a hooks location git does not name is a failed capture), and of the Testing Standards' rule that a test seam must not re-enter the function it patches. It carries no new design decision; the Architect may overrule it. A1 stays as written; A2 supersedes the lines named in A2.4.

**Gaps.**
- **F5 (P2, ordinary, found by round 2).** `_git_safety_snapshot` reads `rev-parse --git-common-dir` through `_run_git`'s default decode, which strips Unicode whitespace from both ends of the output. Git accepts a separate git directory whose last component ends in a nonbreaking space (U+00A0) and names it WITH that character. The stripped path names a directory that does not exist, `_hooks_listing` answers a missing directory with an empty successful listing, and a build whose real hooks changed is committed and adopted (the reviewer ran the real queue, worktree, executor and adoption path). The orchestrator re-checked the premises on this host: git ends its answer with exactly one LF and no CR (`b'.git\n'`), the NBSP-ended directory exists and holds hooks, `.strip()` names a path that does not exist and `removesuffix("\n")` names the real one, for the linked worktree too (`files2\probes\probe_bf904a_nbsp_common_dir.py`).
- **F6 (P2, ordinary CI, found by round 2).** A1.10's `_ListingSeam._name()` calls `Path(path).resolve()` inside the patched `os.lstat`. On POSIX, `Path.resolve()` calls `os.lstat`, so every lstat re-enters the seam: N1, N2 and N3[bytes] raise `RecursionError` on the Ubuntu CI job (the reviewer executed the exact definitions with the stock POSIX resolver over Windows files: 166 lstat calls, then `RecursionError`). A Windows run cannot show it, and no Linux run is available before CI.

### A2.1 `src/probos/cognitive/builder.py`: the common-directory read (against the A1-built `_git_safety_snapshot`)
SEARCH:
```python
        rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir)
    except (OSError, ValueError):
        return None
```
REPLACE:
```python
        rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir, lossless=True)  # BF-904a A2: byte-exact: a directory name may end in whitespace
        common_dir = common_dir.removesuffix("\n")  # BF-904a A2: git ends its answer with one newline; nothing else is trimmed
    except (OSError, ValueError):
        return None
```
`lossless=True` leaves the text unstripped, so only git's own record terminator is removed; an empty answer is still a failed capture (`if rc == 0 and common_dir:` is unchanged). The flag now has three callers, all of them the safety capture (the baseline listing, the comparison listing and this read).

### A2.2 `tests/test_bf904a_git_hardening.py`: the listing seam resolves no path (prose; the Builder writes it)
- **`_ListingSeam`.** Compute every form of the hooks directory the seam compares against BEFORE `install` runs: `os.path.abspath(hooks_dir)` and `os.path.realpath(hooks_dir)` (strings). `_name(path)` becomes a pure string operation: for a `str` or `os.PathLike` argument, `os.path.dirname(os.path.abspath(os.fspath(path)))` is compared with those precomputed strings, and the entry name is `os.path.basename`. No call that touches the filesystem (`Path.resolve`, `os.path.realpath`, `Path.exists`, `os.stat`, `os.lstat`) may run inside any function the seam installs. Apply the same rule to `_Unreadable.install` (A1.8): precompute the two forms, compare lexically.
- **A guard that makes the class detectable on Windows.** The seam keeps an `inside` counter that its installed functions raise while they run. While the seam is installed, the test monkeypatches `pathlib.Path.resolve` and `os.path.realpath` with wrappers that call the real function, except that they raise `AssertionError("a filesystem-resolving call inside the listing seam")` when `inside` is non-zero. N1, N2 and N3[bytes] (and the `_Unreadable` cases) must still pass, and the guard must fail the pre-A2 seam (verify: put the old `_name()` back in the scratch worktree: the guard fires on Windows).
- **No other filesystem-resolving call may run inside any patched `os` function in the module**; audit every `monkeypatch.setattr(os, ...)`, `monkeypatch.setattr(Path, ...)` and `monkeypatch.setattr(builtins, ...)` of the module for it, and for any assumption that holds only on Windows (case-insensitive path comparison, 8.3 names, `O_*` flags that are absent here, the `attrib` call), and list what you found in the report.

### A2.3 New test and mutation rows
| ID | Test | Asserts |
|---|---|---|
| N13 | `test_a_hooks_directory_whose_name_ends_in_whitespace_is_watched` (parametrised `layout` over `separate-git-dir`, `linked-worktree-of-it`) | Setup: `admin = tmp_path / "admin\u00a0"`, `work = tmp_path / "work"`, `git init -q -b main --separate-git-dir <admin> <work>` with the module's repo-local identity settings and a seed commit; for `linked-worktree-of-it`, `git worktree add -q -b wt <tmp_path / "wt">` and the build runs in `wt`. **Premises, first (plain git, bytes, `env=_control_env()`):** `rev-parse --git-common-dir` in the build directory returns bytes that end with `admin\xc2\xa0\n` (UTF-8 of the NBSP, then one LF); `os.path.exists` of the stripped text is False and of the exact text is True; `<admin>/hooks` is a directory with at least one entry. **Control, first:** the same layout (a fresh pair) with nothing planted commits. **Probe:** the fake plants `post-checkout` in `<admin>/hooks` during the tests; `success is False`, `REFUSAL` and `"post-checkout"` in `result.error`, no `commit_hash`, the marker absent. **Cleanup:** the NBSP-ended directory cannot be removed by an ordinary Windows path; register a finalizer that removes it through `\\?\` plus the absolute path on Windows and with `shutil.rmtree` elsewhere, so the test leaves nothing behind. If this host refuses the name, use `\u2003` (an em space, which `str.strip()` also removes) and say so. Kills HRA2a, HRA2b. |

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| HRA2a | `src/probos/cognitive/builder.py` | `rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir, lossless=True)  # BF-904a A2: byte-exact: a directory name may end in whitespace` | `rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir)  # BF-904a A2: byte-exact: a directory name may end in whitespace` | N13 |
| HRA2b | `src/probos/cognitive/builder.py` | `common_dir = common_dir.removesuffix("\n")  # BF-904a A2: git ends its answer with one newline; nothing else is trimmed` | `common_dir = common_dir.strip()` | N13 |
| HRA2c | `src/probos/cognitive/builder.py` | `common_dir = common_dir.removesuffix("\n")  # BF-904a A2: git ends its answer with one newline; nothing else is trimmed` | `pass` | H1, H4, N13 |

A1's hand row HR1 (`--git-common-dir` to `--git-dir`) now anchors on A2.1's REPLACE line: SEARCH `rc, common_dir, _err = await _run_git(["rev-parse", "--git-common-dir"], work_dir, lossless=True)  # BF-904a A2: byte-exact: a directory name may end in whitespace`, REPLACE the same with `"--git-dir"`.

### A2.4 Supersessions (the original lines stay)
- **A1 D19:** "the safety capture is its only caller" stays true with three call sites; the round-2 and A1 texts that say "exactly two" lossless callers read "three".
- **A1.12, Diff Reviewer property 4:** "the only git the check runs is the lossless config listing" reads "the lossless config listing and the lossless common-directory read".
- **A1.10's `_ListingSeam` and A1.8's `_Unreadable`** read as A2.2 describes.
- **Tests summary and header:** M1's module has 30 test functions (40 cases) after N13 (27 after A1, N11 and N12 from the orchestrator's earlier test-only repair, then N13), and the hard stops add N13's premises.
- **D22's table** is unchanged: the common-directory read answers the same three cases, now byte-exact.

### A2.5 Considered, deferred
- **`repository_identity` (BF-896) strips its `--absolute-git-dir` answer the same way,** so two git directories whose names differ only by a trailing whitespace character compare equal. Pre-existing, injected-only (it needs a rewritten pointer to a sibling directory), and outside this amendment; recorded for the consolidated #1523 follow-up.
- **A POSIX run of the module** is not available before CI; the guard in A2.2 makes the re-entrancy class detectable on Windows, and the round-3 review is asked to re-run the stock POSIX resolver probe against the repaired seam.
