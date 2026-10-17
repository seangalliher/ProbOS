# BF-898 (#1563): the unreviewed test-fix loop may change source only, so it cannot weaken the checks that grade it

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Revised by:** the orchestrator, 2026-10-17: BF-897 merged alone as `f2b884d3` (the batch was dropped under the batching rule, because BF-898's review was not ready), so Status, Dependencies and the Focused gate note say BF-898 has its own gate and its own PR closing #1563; the Section 4 and Section 5 SEARCH heads (and the BF-897 line each REPLACE restates) are re-anchored on the BF-897 heading and lead that BF-897's review reworded. No design change.
**Status:** ready to build. Drafted on the BF-897 round-1 candidate (`origin/main` `b91448c1` plus BF-897, staged tree `eca1c170`); BF-897 then merged as `f2b884d3` with a repaired fix-loop tail (the final `else:` of the loop is now a `break`); this contract builds on `f2b884d3`. BF-898 has its own gate and its own PR (closing #1563 only). No new AD or BF number; BF-898 is allocated by the title of #1563. AD ceiling for the record: AD-1341 (`scripts/ad_ceiling.py`, GitHub issue titles).
**Dependencies:** BF-897 (merged; this contract's SEARCH blocks are anchored on its tree). Nothing here changes BF-897 behaviour (see "Hooks in BF-897 lines").
**Estimated tests:** one new file with about 30 test items (8 functions, 2 of them parametrized over 6 cases), plus 3 existing tests updated in place.
**Milestones (each about 150 tool calls or fewer):**
- M1: Section 1 and test group T-S.
- M2: Section 2, test groups T-U, T-P and T-R, and the three existing-test updates.
- M3: Sections 3-5 (docs and trackers), then the mutation campaign.

## Risk classification (the Captain's rule: scale rigor to risk)

| Part | Property | Class | Rigor |
|---|---|---|---|
| `fix_loop_write_refusal` and its protected set | An unreviewed repair cannot change a test, test configuration or the build's grader | Security boundary | A self-test of must-refuse and must-allow paths, mutation rows for every element, refusal logic rows |
| The fix loop's use of it | A refused response blocks the commit, names the path and asks for no further repair | Security boundary | A real-git replay with real pytest: five grader-weakening fixes are refused and a source-only fix commits. Mutation rows B1-B4 and B8 |
| Disclosure | Files the fix loop changed are listed in `metadata["fix_loop_files"]` and in the commit message | Audit | Rows B5-B7 |
| Fix prompt | The model is told the rule | Standard | Row B9 |

## Hooks in BF-897 lines

One. Section 2.1 rewrites the import at `builder.py:22`, a line BF-897 last edited (it added `operator_checkout_refusal`). The rewrite only adds `fix_loop_write_refusal` to the imported names, because a second import line from the same module would split one import. No other BF-897 line changes. The test loop (`builder.py:2915-2933`), `_classify_test_run`, the entry guard and the commit-gate leads (`builder.py:3058-3072`) are untouched. Sections 2.2-2.6 anchor on pre-BF-897 lines.

## Decisions (ranked; the top option of each is chosen)

### D-a: the protected set and its owner

| Rank | Option | Correctness | Safety | Compatibility | Fit | Reversibility | Validation cost |
|---|---|---|---|---|---|---|---|
| **1 (chosen)** | Constants and one function in `builder_paths.py`, beside `builder_write_refusal`. The fix loop may write only `src/probos/<...>`, where `src` and `probos` are written exactly so. It may not write `FIX_LOOP_PROTECTED_PATHS` (10 exact files, compared in the canonical form `_canonical` already defines) or any file named in `FIX_LOOP_REFUSED_NAMES` (5 pytest configuration names, at any depth). `builder_write_refusal` runs first and keeps its reason. | Closes the class by construction | Fails closed: a non-plain component (empty or `.`) is refused, not normalised | No config field (the AD-1152 golden pin is unchanged). `ALLOWED_PATH_PREFIXES`, `FORBIDDEN_PATHS` and `builder_write_refusal` are unchanged, so the BF-896 permission policy (`copilot_adapter.py:254`) is unchanged | One owner, next to the boundary it extends | Three constants and one function | Low (pure function, self-test) |
| 2 | Reuse `config/sealed_modules.yaml` as the protected set | Misses `code_reviewer.py`, `builder_paths.py` and all tests | Couples to warn-only semantics that AD-481l owns; reads YAML in the build path | A config file change | Wrong owner | Medium | Medium |
| 3 | Protect directories (for example all of `src/probos/cognitive/`) | Over-refuses legitimate repairs | Safe | n/a | Coarse | Easy | Low |
| 4 | A new `SystemConfig` field listing protected paths | Correct | An operator-editable list lets the grader set be edited | Changes the AD-1152 default-config hash | Config is the wrong home for a security invariant | Medium | Medium |

**The protected set**, each entry with the reason it decides the grade or the boundary:

| Path | Why |
|---|---|
| `src/probos/cognitive/builder.py` | The fix loop, the test runner, `_classify_test_run` and the commit gate |
| `src/probos/cognitive/builder_paths.py` | The write boundary and this rule |
| `src/probos/cognitive/code_reviewer.py` | The AD-341 reviewer that runs on the build |
| `src/probos/cognitive/copilot_adapter.py` | The visiting session's deny-by-default permission policy (BF-896) |
| `src/probos/execution/command_env.py` | The environment the targeted pytest runs under (BF-892) |
| `src/probos/extensions/sealed_core.py` | The sealed-core check |
| `src/probos/build_dispatcher.py` | The queued build's identity pin and adoption (BF-896) |
| `src/probos/build_pipeline.py` | The wrapper over `execute_approved_build` |
| `src/probos/worktree_manager.py` | The merge refusal (BF-897) |
| `src/probos/routers/build.py` | The approve and resolve refusals (BF-897) |

### D-b: `conftest.py` and pytest configuration

- **Fix loop: refused (chosen; the acceptance requires it).** Outside `src/probos/` the prefix rule refuses them: `tests/conftest.py`, a root `conftest.py`, `pytest.ini`, `.pytest.ini`, `tox.ini` and `setup.cfg`. Inside `src/probos/` the name rule refuses them as defence in depth. pytest does not load a conftest from `src/probos/` for a run over `tests/` files, but a later runner might.
- **Approved writes: unchanged (chosen).** The ranking:
  1. **Keep their scope.** #1563 says "approved writes keep their scope". On the BF-896 route the approved writes are the visiting session's output. Any new refusal there changes that route's outcome, and #1563's Do Not Build forbids that.
  2. Refuse `conftest.py` and pytest configuration there too. This changes the BF-896 route and blocks a legitimate build that adds a shared fixture.

  The gap this leaves is recorded under Blind spots: on the visiting route the "approved" blocks are model output the Captain has not yet seen when the tests run. It belongs to AD-1336 (#1558), the amendment under which only service-written evidence counts.

### D-c: how "deletes a test, deletes a test function, marks a test skipped" is detected

| Rank | Option | Notes |
|---|---|---|
| **1 (chosen)** | **No detector. The fix loop may change source only.** A failure caused by a wrong test goes back to the Captain. | It closes every route by construction, because no test file, conftest or configuration file can be written: a skip or xfail marker, a `pytest.skip` or `importorskip` call, a renamed test that is no longer collected, a `__test__ = False` flag, a `pytest_plugins` line in a test module, a deselect hook or `collect_ignore` in a conftest, `addopts`, `-k` or `--deselect` in configuration, a body hollowed out to `pass`, a weakened assertion, and deletion by overwrite. It also closes two routes #1563 does not name. (1) A slash-free name passes `builder_write_refusal` (`builder_paths.py:95` checks prefixes only when the path has a `/`), so a root `conftest.py`, `pytest.ini`, `sitecustomize.py` or `pytest.py` was writable. (2) A top-level module under `src/` shadows an installed one in the pytest subprocess, because `_pytest_pythonpath` (`builder.py:2418-2422`) puts `<work_dir>/src` ahead of site-packages: `src/pytest.py`, `src/_pytest/...`, `src/sitecustomize.py`. Cost: the loop cannot repair a wrong test, including one this build wrote. That is the intended trade (see Prior art). |
| 2 | An AST detector over changed test files (removed `test_*` functions, added skip markers, `skip`/`importorskip` calls, `__test__`, hooks, hollowed bodies), with other test edits allowed and disclosed | Open-ended and bypassable: `assert True or ...`, an `if False:` guard, a parametrize list emptied, a helper the assertions call made permissive, `pytest_plugins` in a module. Each bypass needs a new rule. |
| 3 | Allow edits only to test files this build created, refuse pre-existing ones | The build's own new test is the approved grader of the build's own source; weakening it is the same reward hack |
| 4 | Refuse only the acceptance's three named shapes by detector | Option 2 with fewer rules |

A fix block can only create or modify. `_parse_file_blocks` emits `mode: "create"` (`builder.py:2347`) and `mode: "modify"` (`builder.py:2392`) only, so a fix "deletes" a test by overwriting or editing it. Both are refused by path.

### D-d: disclosure

| Rank | Option | Notes |
|---|---|---|
| **1 (chosen)** | Test edits cannot happen, so there are no edited assertions to list. Instead, every file the fix loop actually changed (bytes differ after the write) goes in `result.metadata["fix_loop_files"]` (sorted) and in one commit-message line: `Changed by the unreviewed test-fix loop (BF-898): a, b`. A refusal is in `result.error` with its path, and from there in `classify_build_failure`'s `raw_error`. | No new `BuildResult` field: `metadata` is the existing extension dict (`builder.py:136-138`, AD-549) |
| 2 | A new `BuildResult` list field | Changes the dataclass shape for no reader |
| 3 | A per-test "assertions changed" list | Moot under D-c |

### D-e: the self-test

| Rank | Option | Notes |
|---|---|---|
| **1 (chosen)** | `FIX_LOOP_SELF_TEST`, a tuple of `(path, refused)` examples beside the rules, and `fix_loop_self_test()`, which judges each example with the runtime function (lexical rules only, so it is OS-independent) and returns one line per mismatch. A test asserts that the result is empty and that every protected path and refused name has an example. | The AD-1328 pattern (`command_policy.py:1773-1803`): the examples sit with the rules and the runtime evaluator judges them |
| 2 | Also run it at runtime and refuse every fix write if it fails | AD-1328 does this because its rules are operator config. These are code constants: a failing example can come only from a code change, which the test catches before merge. Cut. |
| 3 | A table in the test file only | Separates the examples from the rules they document |

**Cut, and why:**
- **AD-481l (the sealed-core hard block).** Not built (#1563's Do Not Build). BF-898 hard-refuses the unreviewed path. A hard block for the approved writes still waits on AD-482's false-positive baseline, as `_check_sealed_path`'s docstring says. Record on #1563 as a follow-up note, not a new issue.
- **A runtime self-test.** See D-e.
- **A symlink write-through check.** Builder writes create regular files only. A link could come only from repository content the Captain committed. Considered, deferred.
- **Relabelling the "Syntax errors:" lead** that refusals share (`builder.py:3042`). It is pinned by `tests/test_bf896_executor_identity_and_blocks.py:585,600,615` and `tests/test_builder_guardrails.py:335`; the refusal text itself names BF-898 and the path.

## Needs the Captain

None. The rule strengthens a control and weakens none. There is no schema or public API change, no config field, no spending and no OSS boundary question. One behaviour change to state: the fix loop can no longer repair a test, including a test this build wrote. Such a build fails to the Captain with the refusal as its reason.

The residual risk below is recorded, not accepted. I rate it Medium, so it is not a Captain condition: the fix loop is unreachable in production on this tree (Absence Verified), and the forging fix is named in the commit message.

## Problem (verified on this tree)

1. **The fix loop's only gate is the write boundary.** `builder.py:2969-3009`: each repair block goes through `builder_write_refusal(change["path"], work_dir)` (`:2973`) and is then written (`:2991`, `:2998`). The targeted tests rerun on the next attempt (`:2917`). `builder_write_refusal` allows any path under `src/`, `tests/`, `config/`, `docs/` and `prompts/` (`builder_paths.py:30-36`), and any slash-free name (`builder_paths.py:95`). So a repair can edit or overwrite `tests/test_x.py`, add `tests/conftest.py`, write a root `pytest.ini`, or shadow pytest with `src/pytest.py` (`_pytest_pythonpath`, `builder.py:2418-2422`). Any of these makes the rerun pass, and the commit follows (`builder.py:3073-3090`).
2. **The grader's own files are writable.** `src/probos/cognitive/code_reviewer.py`, `builder_paths.py` and `builder.py` are under `src/`. `_check_sealed_path` only warns (`builder.py:2624-2651`).
3. **Fix-loop writes are unreviewed and undisclosed.** The AD-341 review runs on the approved `file_changes` only (`builder.py:2885-2908`), before the test loop. The commit message (`builder.py:3074-3080`) does not say which files the fix loop changed.
4. **Every apply site, enumerated** (Absence Verified has the commands):

| Site | Model-authored? | After approval? | Covered by |
|---|---|---|---|
| Approved writes, `builder.py:2752-2869` (native, and the BF-896 visiting blocks with `base`) | yes | yes | `builder_write_refusal`; scope unchanged by D-b |
| The test-fix loop, `builder.py:2970-3009` (the "BF-894 repair writes") | yes | yes, and unreviewed | **this contract** |
| The BF-896 visiting route's repair | none exists: `build_dispatcher.py:215-222` passes no `llm_client`, so the fix loop never runs there | n/a | n/a |
| The BF-896 adoption, `worktree_manager.py:170-207` | no: git `checkout` and `merge --ff-only` of the executor's commit | n/a | n/a |
| `escalation_hook` (`builder.py:3048-3055`) | both production callers pass `None` | n/a | n/a |
| Generation-phase parses (`builder.py:739`, `:1057`, `:2305`, `copilot_adapter.py:794`) and the AD-546 harness writes (`swe_harness/tools.py:970`, `:1087`) | yes | no: they produce the proposal, or belong to the out-of-scope native harness | n/a |

## Solution

- `builder_paths.fix_loop_write_refusal(path_str, work_dir)` runs `builder_write_refusal` first, then the source-only rule, then the protected set, then the refused names. Every refusal string contains `BF-898` and the path.
- In the fix loop, every block of a response is checked before any is written. If one is refused, none is written, each refusal goes into `validation_errors` (which blocks the commit, `builder.py:3041-3043`), the attempt is counted and the loop stops. The tests do not rerun, and no further deep-tier call is made.
- Files the fix loop changed are recorded in `metadata["fix_loop_files"]` and named in the commit message.
- The fix prompt states the rule and gives the model an abort: "if a test itself is wrong, say so and output no blocks".

---

## Section 1: `src/probos/cognitive/builder_paths.py`

### 1.1 Module docstring

<<<<<<< SEARCH
"""BF-894 (#1547): the builder's write-path boundary.

``builder_write_refusal`` is the one check for every path ``execute_approved_build``
writes on a model's behalf: the approved writes and the test-fix repair loop.
=======
"""BF-894 (#1547): the builder's write-path boundary.

``builder_write_refusal`` is the one check for every path ``execute_approved_build``
writes on a model's behalf: the approved writes and the test-fix repair loop.

BF-898 (#1563): the repair loop's blocks are model-authored and unreviewed, and the
tests it reruns decide the commit, so the loop also applies ``fix_loop_write_refusal``:
source under ``src/probos/`` only, never a test, a ``conftest.py``, pytest
configuration or the build's own grader (``FIX_LOOP_PROTECTED_PATHS``). The rule's
examples (``FIX_LOOP_SELF_TEST``) are judged by ``fix_loop_self_test``.
>>>>>>> REPLACE

### 1.2 The rule, its protected set and its self-test

<<<<<<< SEARCH
        if os.path.samestat(current, git_entry):
            return f"Forbidden path (same file as .git): {path_str}"
    return None


def operator_checkout_refusal(
=======
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


def fix_loop_write_refusal(
    path_str: str, work_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """BF-898 (#1563): why the test-fix loop must not write *path_str*, or None if it may.

    Everything ``builder_write_refusal`` refuses is refused first, with its reason.
    Then the path must be plain (no empty or ``.`` component), must start with the
    components ``src`` and ``probos`` exactly as written, must not be one of
    ``FIX_LOOP_PROTECTED_PATHS`` and must not be named one of
    ``FIX_LOOP_REFUSED_NAMES`` (both compared in the canonical form, so a case,
    trailing-dot or ignorable-code-point variant is the same name).
    """
    refusal = builder_write_refusal(path_str, work_dir)
    if refusal is not None:
        return refusal
    parts = path_str.replace("\\", "/").split("/")
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
    # builder_write_refusal's own rules come first
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
>>>>>>> REPLACE

## Section 2: `src/probos/cognitive/builder.py`

### 2.1 Import (the one BF-897 line touched; a name is added, nothing else)

<<<<<<< SEARCH
from probos.cognitive.builder_paths import builder_write_refusal, operator_checkout_refusal
from probos.cognitive.cognitive_agent import CognitiveAgent
=======
from probos.cognitive.builder_paths import (
    builder_write_refusal,
    fix_loop_write_refusal,
    operator_checkout_refusal,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
>>>>>>> REPLACE

### 2.2 The fix prompt states the rule and offers an abort

<<<<<<< SEARCH
        "Fix the failing tests. Output ONLY the file changes needed to fix the "
        "failures. Use the same ===MODIFY: path=== or ===FILE: path=== format. "
        "Do NOT rewrite files that don't need changes. Keep fixes minimal — "
        "fix the bug, don't refactor."
    )
=======
        "Fix the failing tests. Output ONLY the file changes needed to fix the "
        "failures. Use the same ===MODIFY: path=== or ===FILE: path=== format. "
        "Do NOT rewrite files that don't need changes. Keep fixes minimal — "
        "fix the bug, don't refactor.\n\n"
        "You may change only source files under src/probos/ (BF-898). Do not change "
        "any test, conftest.py or test configuration, or the builder, its reviewer or "
        "its write boundary: a response with such a block is refused whole and the "
        "build is not committed. If a test itself is wrong, say so and output no blocks."
    )
>>>>>>> REPLACE

### 2.3 The fix-loop file record

<<<<<<< SEARCH
        # 5. Run tests with fix loop (AD-314, AD-344)
        if run_tests and (written or modified_files):
            all_changes = list(file_changes)  # track for fix prompt
            all_changed_files = written + modified_files
=======
        # 5. Run tests with fix loop (AD-314, AD-344)
        if run_tests and (written or modified_files):
            all_changes = list(file_changes)  # track for fix prompt
            all_changed_files = written + modified_files
            fix_loop_files: list[str] = []  # BF-898: the paths the fix loop changed
>>>>>>> REPLACE

### 2.4 The whole response is checked before any block is written

<<<<<<< SEARCH
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
=======
                    # BF-898 (#1563): the repair is model-authored and unreviewed, so it may
                    # change source only (builder_paths.fix_loop_write_refusal, which applies
                    # BF-894's boundary first). A response with any refused block is refused
                    # whole and the fix loop stops; the refusal blocks the commit
                    # (validation_errors) and names the path.
                    fix_refusals = [
                        refusal
                        for refusal in (
                            fix_loop_write_refusal(change["path"], work_dir)
                            for change in fix_changes
                        )
                        if refusal is not None
                    ]
                    if fix_refusals:
                        for refusal in fix_refusals:
                            logger.warning("BuilderAgent: repair refused: %s", refusal)
                        validation_errors.extend(fix_refusals)
                        result.fix_attempts += 1
                        break  # BF-898: no further repair attempt

                    # Apply fix changes
                    for change in fix_changes:
                        path = Path(work_dir) / change["path"]
                        before_fix = path.read_bytes() if path.is_file() else None
>>>>>>> REPLACE

### 2.5 Record what the fix loop actually changed

<<<<<<< SEARCH
                        err = _validate_python(path)
                        if err:
                            validation_errors.append(err)

                    all_changes.extend(fix_changes)
                    result.fix_attempts += 1
=======
                        err = _validate_python(path)
                        if err:
                            validation_errors.append(err)
                        changed_by_fix = path.is_file() and path.read_bytes() != before_fix
                        if changed_by_fix and change["path"] not in fix_loop_files:
                            fix_loop_files.append(change["path"])

                    if fix_loop_files:
                        result.metadata["fix_loop_files"] = sorted(fix_loop_files)
                    all_changes.extend(fix_changes)
                    result.fix_attempts += 1
>>>>>>> REPLACE

### 2.6 The commit message names the fix loop's files

<<<<<<< SEARCH
                desc_short = spec.description[:200] if spec.description else ""
                commit_msg = (
                    f"{spec.title}"
                    + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                    + (f"\n\n{desc_short}" if desc_short else "")
                    + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
                )
=======
                desc_short = spec.description[:200] if spec.description else ""
                # BF-898: the files the unreviewed fix loop changed are named in the commit.
                disclosed_fix_files = result.metadata.get("fix_loop_files", [])
                commit_msg = (
                    f"{spec.title}"
                    + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                    + (f"\n\n{desc_short}" if desc_short else "")
                    + (
                        "\n\nChanged by the unreviewed test-fix loop (BF-898): "
                        + ", ".join(disclosed_fix_files)
                        if disclosed_fix_files
                        else ""
                    )
                    + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
                )
>>>>>>> REPLACE

## Section 3: `docs/development/architecture-reference.md`

<<<<<<< SEARCH
- Test-fix loop (AD-314): runs pytest after writes, feeds failures back to LLM for up to 2 fix attempts. `_run_tests()` helper, `_build_fix_prompt()` for fix context. `max_fix_attempts` parameter on `execute_approved_build()`
=======
- Test-fix loop (AD-314): runs the targeted tests after writes (BF-897) and feeds a real failure back to the LLM for up to 2 fix attempts. `_build_fix_prompt()` for fix context; `max_fix_attempts` parameter on `execute_approved_build()`. BF-898: the repair blocks are unreviewed, so `builder_paths.fix_loop_write_refusal` lets them change source under `src/probos/` only. They never change a test, a `conftest.py`, pytest configuration or the build's grader (`FIX_LOOP_PROTECTED_PATHS`). A response with a refused block is refused whole, the loop stops and the build is not committed. The files the loop changed are listed in `metadata["fix_loop_files"]` and in the commit message.
>>>>>>> REPLACE

## Section 4: `DECISIONS.md`

<<<<<<< SEARCH
### BF-897 -- The builder runs targeted tests only, and no build route merges in, or executes against, the checkout ProbOS runs from (2026-10-16, #1559)
=======
### BF-898 -- The unreviewed test-fix loop may change source only, so it cannot weaken the checks that grade it (2026-10-16, #1563)

- *Scope.* When the targeted tests failed, the fix loop wrote the model's repair blocks with only `builder_write_refusal` as a gate. That gate allows any path under `src/`, `tests/`, `config/`, `docs/` and `prompts/`, and any slash-free name. So a repair could edit or overwrite the failing test, add a deselect hook in `tests/conftest.py`, write a root `pytest.ini`, shadow pytest from `src/`, or edit the reviewer or the boundary, and its own rerun would pass and commit. This is the reward hack the Darwin Gödel Machine paper reported. Decided by the Architect (2026-10-16, Delegated AD Execution Mode); the rankings are in the contract.
- *D-a/D-c (the rule).* `builder_paths.fix_loop_write_refusal`, next to `builder_write_refusal` and run after it, allows only `src/probos/...` (components written exactly so, none empty or `.`). It refuses `FIX_LOOP_PROTECTED_PATHS`: the builder, the boundary, the AD-341 reviewer, the visiting permission policy, the test environment, the sealed-core check and the pipeline's refusals. It also refuses any file named in `FIX_LOOP_REFUSED_NAMES` (pytest configuration). No detector: a source-only rule closes every way a test stops grading by construction. A failure caused by a wrong test goes to the Captain. Rejected: an AST detector over test edits (open-ended and bypassable), and allowing edits to the build's own new tests (the same hack).
- *Fix loop.* All blocks of a response are checked before any is written. One refusal refuses the response, goes into `validation_errors` (no commit), counts the attempt and stops the loop. The prompt states the rule and says to output no blocks when a test is wrong.
- *D-b.* Approved writes keep their scope: refusing pytest configuration there would change the BF-896 route (#1563's Do Not Build).
- *D-d/D-e.* `metadata["fix_loop_files"]` and a commit-message line name every file the loop changed. `FIX_LOOP_SELF_TEST` examples sit beside the rule and are judged by `fix_loop_self_test` (the AD-1328 pattern); there is no runtime self-test, because the rule is code, not config. No config field.
- *Recorded, not fixed.* (1) A source-side fix can still forge a pass: `os._exit(0)` at import, patching `_pytest` from an imported module, `__eq__` overloading, special-casing. A path rule cannot close that. It belongs to AD-1336 (#1558, service-written evidence) and the Captain's diff review, which the commit-message line points at. (2) On the visiting route the approved blocks are unseen model output when the tests run (AD-1336). (3) AD-481l stays unfiled: the unreviewed path is now hard-refused, and the approved-write block still waits on AD-482. (4) The fix loop is unreachable in production on this tree (no production caller passes `llm_client` to a reachable execute), so the deterministic replay is the evidence.
- Contract `prompts/bf-898-fix-loop-grader-protection.md` (claude-architect).

### BF-897 -- The builder runs targeted tests only, and no build route merges in, or executes against, the checkout ProbOS runs from (2026-10-16, #1559)
>>>>>>> REPLACE

## Section 5: `PROGRESS.md`

<<<<<<< SEARCH
# ProbOS Progress

**BF-897 (2026-10-16), #1559 -- the builder runs targeted tests only, and no build route merges in, or executes against, the checkout ProbOS runs from.**
=======
# ProbOS Progress

**BF-898 (2026-10-16), #1563 -- the unreviewed test-fix loop may change source only, so it cannot weaken the checks that grade it.** A repair block that touches a test, a `conftest.py`, pytest configuration, anything outside `src/probos/`, or the builder, its reviewer or its write boundary is refused with its path. The whole response is refused, the loop stops and the build is not committed. The files the loop did change are listed in the build result and the commit message. A real-git replay with real pytest shows five grader-weakening repairs refused and a source-only repair committed. Contract `prompts/bf-898-fix-loop-grader-protection.md`.

**BF-897 (2026-10-16), #1559 -- the builder runs targeted tests only, and no build route merges in, or executes against, the checkout ProbOS runs from.**
>>>>>>> REPLACE

The Section 5 SEARCH ends at `checkout.**` mid-line; the rest of the BF-897 line stays as it is. If the installer needs whole lines, extend the SEARCH to the end of `PROGRESS.md` line 3, copied exactly.

**Roadmap Bug Tracker** (`docs/development/roadmap.md`): no row; it carries none for BF-896 or BF-897 (`grep -n "BF-898\|#1563" docs/development/roadmap.md` finds nothing).

---

## Tests

Builders write these. All are OS-independent:
- Paths use `pathlib`; git runs with list arguments and `-C`.
- Each temporary repository is created with `git init -q -b main` and sets `user.name`, `user.email`, `commit.gpgsign false` and `core.autocrlf false` locally. Fixture files are written with `newline="\n"`.
- Real-git tests carry `@pytest.mark.skipif(shutil.which("git") is None, reason="git not found on PATH")`. Real-pytest tests carry `@pytest.mark.timeout(150)` (the `tests/test_bf892_spawn_env.py:64,75` pattern).
- Copy, do not import, these helpers from `tests/test_bf897_build_pipeline_scale_and_checkout.py`:
  - `_GIT_REDIRECTS` and its autouse fixture (`:71-86`);
  - `_git`, `_out`, `_make_repo` and `_show` (`:92-128`);
  - `_FakeBuildGit`, the `fake_git` fixture and the `build_tree` fixture (`:472-529`).
- No test touches the real repository, and none relies on order.

**Real-git and executor premises, spelled out (BF-897's three first-draft mistakes, avoided by reading the executor).**
- The executor's branch for `BuildSpec(title="bf898 replay")` is `builder-bf898-replay`: `builder.py:2735-2738` builds `builder/<slug>`, and `_sanitize_branch_name` (`:1573-1576`) turns `/` into `-`. Do not create a branch with that name.
- After the build, the executor runs `git checkout main` (`builder.py:3100`). On no commit it deletes its branch (`:3105`) and unlinks every file in `files_written` (`:3107-3111`), so a file the fix loop *created* is gone after a failed build whether or not it was written. Discriminate with a file that existed before the build (it is in `files_modified` and survives), with the number of targeted runs, and with the committed tree (`git show <sha>:<path>`), never with the presence of a created file alone.
- The tree is the repository itself, cut from nothing but the seed commit on `main`. The BF-897 entry guard allows it: assert `operator_checkout_refusal(repo, builder_module._PROJECT_ROOT) is None` as a premise.
- `TARGETED_TEST_TIMEOUT_S` (60) is read at call time (`builder.py:2918`). The replay monkeypatches `builder_module.TARGETED_TEST_TIMEOUT_S` to 120 so a slow nested pytest under the parallel gate cannot turn "failed" into "timed_out" (which would skip the fix loop; the `fix prompts == 1` premise then fails loudly).
- The code reviewer also calls the fake model (`builder.py:2886-2897`); count fix requests by `"Test Fix Required" in prompt`.

### New file `tests/test_bf898_fix_loop_grader_protection.py`

Shared fixture text:
- `_WIDGET = "src/probos/widget.py"`, `_WIDGET_V1 = "VALUE = 1\n"`, `_WIDGET_TEST = "tests/test_widget.py"`.
- `_TEST_TEXT` holds, in order:
  - `import pathlib` and `import pytest`;
  - `SOURCE = pathlib.Path(__file__).resolve().parent.parent / 'src' / 'probos' / 'widget.py'`;
  - `def test_present() -> None:` asserting `SOURCE.is_file()`;
  - `def test_value() -> None:` asserting `'VALUE = 2' in SOURCE.read_text(encoding='utf-8')`.

  The test imports nothing from the work tree, so no installed `probos` package can stand in for it.
- The approved change is `{"path": _WIDGET, "mode": "create", "content": _WIDGET_V1}`, so the first targeted run is `1 failed, 1 passed`.

The six repair replies (`_REPAIRS`, a dict keyed by case). Each is the exact `===FILE:` / `===MODIFY:` text the fake model returns:

| Case | Reply | Refused path |
|---|---|---|
| `conftest_hook` | `===FILE: tests/conftest.py===` defining `pytest_collection_modifyitems(config, items)`: it calls `config.hook.pytest_deselected(items=[i for i in items if i.name == 'test_value'])`, then `items[:] = [i for i in items if i.name != 'test_value']` | `tests/conftest.py` |
| `delete_test` | `===FILE: tests/test_widget.py===` with `_TEST_TEXT` minus `test_value` | `tests/test_widget.py` |
| `skip_marker` | `===MODIFY: tests/test_widget.py===`, SEARCH `def test_value() -> None:`, REPLACE `@pytest.mark.skip(reason='bf898')` plus a newline plus `def test_value() -> None:` | `tests/test_widget.py` |
| `edit_assertion` | `===MODIFY: tests/test_widget.py===`, SEARCH `assert 'VALUE = 2' in`, REPLACE `assert 'VALUE = 1' in` | `tests/test_widget.py` |
| `root_pytest_ini` | `===FILE: pytest.ini===` with `[pytest]` and `addopts = --deselect tests/test_widget.py::test_value` | `pytest.ini` |
| `source_fix` (control) | `===MODIFY: src/probos/widget.py===`, SEARCH `VALUE = 1`, REPLACE `VALUE = 2` | none |

**T-S: the rule and its self-test (pure, no git)**
1. `test_fix_loop_self_test_passes`: `fix_loop_self_test() == ()`. Kills P1-P10, N1-N5 and L1-L6.
2. `test_self_test_covers_every_protected_path_and_name`:
   - `(p, True) in FIX_LOOP_SELF_TEST` for every `p` in `FIX_LOOP_PROTECTED_PATHS`;
   - `(n, True)` and `(f"src/probos/{n}", True)` are in it for every `n` in `FIX_LOOP_REFUSED_NAMES`;
   - at least five examples are `False`.

   This test catches an example deleted together with nothing else.
3. `test_self_test_reports_a_failing_example` (the self-test is not vacuous): `monkeypatch.setattr(builder_paths, "FIX_LOOP_SELF_TEST", (("src/probos/widget.py", True),))`. The result has one line containing `src/probos/widget.py` and "expected refused". Kills L7.
4. `test_builder_write_refusal_reason_comes_first`: for `.git/config`, `src/probos/con.py` and `src/probos/a:b.py`, `fix_loop_write_refusal(p) == builder_write_refusal(p)`, and the result is not `None`. Kills L1.
5. `test_every_bf898_refusal_names_the_rule_and_the_path`, parametrized over `tests/test_x.py`, `src/probos/cognitive/builder.py`, `src/probos/conftest.py` and `src/probos//x.py`: the result contains `"BF-898"` and the path as given.

**T-U: the fix loop with a fake runner and fake git (the BF-897 `fake_git` and `build_tree` fixtures)**

Each test seeds `build_tree / "src/probos/foo.py"` with `"x = 1\n"` before the build, and the approved change is a create over it with the same text. The file is pre-existing, so it lands in `files_modified` and survives the failed-build cleanup. The runner is `monkeypatch.setattr(builder_module, "_run_targeted_tests", runner)` with an `AsyncMock`. The model is a fake whose `complete` returns a reply object whose `content` attribute is the reply text (the BF-897 `_FakeLLM` with the reply as a parameter).
6. `test_a_response_with_one_refused_block_is_refused_whole_and_stops_the_loop` (kills B1-B4):
   - Setup: the runner always returns `(False, "1 failed", ["tests/test_foo.py"])`. The reply is `===MODIFY: src/probos/foo.py===` (`x = 1` to `x = 2`) followed by `===FILE: tests/conftest.py===` holding `collect_ignore = ['test_foo.py']`. Call with `max_fix_attempts=2`.
   - Assert: `src/probos/foo.py` still reads `"x = 1\n"` (no block of the response was written); `runner.await_count == 1`; exactly one fix prompt; `result.fix_attempts == 1`; `fake_git.add_and_commit.assert_not_awaited()`; `result.success is False`; `"BF-898" in result.error` and `"tests/conftest.py" in result.error`; `"fix_loop_files" not in result.metadata`.
7. `test_fix_loop_files_are_disclosed_in_metadata_and_commit_message` (kills B5-B7):
   - Setup: also seed `src/probos/other.py` with `"z = 1\n"`. The runner returns `(False, "1 failed", [...])`, then `(True, "1 passed", [...])`. The reply has three blocks:
     - MODIFY `src/probos/foo.py`, `x = 1` to `x = 2`;
     - FILE `src/probos/helper.py`, `y = 1`;
     - MODIFY `src/probos/other.py` whose SEARCH `nope` is not in the file, so nothing changes.
   - Assert: `result.success`; `result.metadata["fix_loop_files"] == ["src/probos/foo.py", "src/probos/helper.py"]` (`other.py` is absent: only real changes are disclosed); the commit message `fake_git.add_and_commit.await_args.args[1]` contains `"Changed by the unreviewed test-fix loop (BF-898): src/probos/foo.py, src/probos/helper.py"`.
   - Control in the same test, in a fresh `tmp_path` subdirectory, where the first run passes: the message contains no `"test-fix loop"` and `"fix_loop_files" not in result.metadata`.
8. `test_approved_writes_keep_their_scope` (kills B8): call with `run_tests=False` and approved creates of `tests/test_new.py`, `tests/conftest.py`, `pytest.ini` and `src/probos/cognitive/code_reviewer.py`. Assert `result.success`, all four paths are in `fake_git.add_and_commit.await_args.args[0]`, and `"BF-898" not in result.error`.
9. `test_fix_prompt_states_the_source_only_rule` (kills B9): `_build_fix_prompt("t", "1 failed", [{"path": "src/probos/foo.py", "mode": "modify"}], 1)` contains `"only source files under src/probos/"` and `"output no blocks"`.

**T-P: premise. Each weakening really passes the real targeted run (real pytest, no git)**
10. `test_premise_each_weakening_passes_the_real_targeted_run`, parametrized over the six `_REPAIRS` cases plus `none`:
    - Setup: a plain directory `tmp_path / "p"` holding `_TEST_TEXT` and `_WIDGET_V1`. Apply the case by hand: a FILE writes the file; a MODIFY does `str.replace(search, replace, 1)` on the target, and the test asserts that the SEARCH text was present.
    - Act: `await _run_targeted_tests(str(p), [_WIDGET], timeout=120)`.
    - Assert: `test_files == [str(p / "tests" / "test_widget.py")]`. Every case except `none` gives `passed is True`. `none` gives `passed is False` with `"1 failed"` in the output.

    This proves the replay discriminates: without the rule, each of the five weakenings would make the rerun pass and the build commit.

**T-R: the deterministic replay (real git, the real executor, real pytest)**
11. `test_replay_a_grader_weakening_repair_is_refused_and_a_source_fix_commits`, parametrized over the six `_REPAIRS` cases:
    - Setup:
      - `repo = _make_repo(tmp_path / "repo", {_WIDGET_TEST: _TEST_TEXT})`, with the entry-guard premise above;
      - `monkeypatch.setattr(builder_module, "TARGETED_TEST_TIMEOUT_S", 120)`;
      - a spy that wraps the real `_run_targeted_tests` (capture the original first, then `monkeypatch.setattr` a wrapper that counts calls and awaits the original);
      - `llm`, the BF-896 `_FakeLLM` pattern (`tests/test_bf896_executor_identity_and_blocks.py:200-209`: it records each prompt and replies with one fixed text) holding `_REPAIRS[case]`.
    - Act: `result = await execute_approved_build([approved], BuildSpec(title="bf898 replay", description=""), str(repo), run_tests=True, max_fix_attempts=2, llm_client=llm)`.
    - Premise (all cases): exactly one fix prompt.
    - **Refused cases** (the five weakenings) assert:
      - `result.success is False` and `result.commit_hash == ""`;
      - `"BF-898" in result.error` and the refused path from the table is in `result.error`;
      - `spy.calls == 1` (no rerun after the refusal);
      - `_out(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"`;
      - the sorted output of `for-each-ref --format=%(refname:short) refs/heads` is `["main"]`;
      - `rev-list --all --count` is `"1"`;
      - `(repo / _WIDGET_TEST).read_bytes() == _TEST_TEXT.encode("utf-8")` (the existing test was never touched);
      - neither `tests/conftest.py` nor `pytest.ini` exists;
      - `"fix_loop_files" not in result.metadata`.
    - **Control** (`source_fix`) asserts:
      - `result.success is True` and `result.commit_hash`;
      - `spy.calls == 2` and `result.metadata["targeted_tests"] == "passed"`;
      - `_show(repo, result.commit_hash, _WIDGET) == "VALUE = 2\n"` and `_show(repo, result.commit_hash, _WIDGET_TEST) == _TEST_TEXT`;
      - `result.metadata["fix_loop_files"] == [_WIDGET]`;
      - `"Changed by the unreviewed test-fix loop (BF-898): src/probos/widget.py"` is in `_out(repo, "log", "-1", "--format=%B", result.commit_hash)`;
      - `"BF-898" not in result.error`.

    This is the seam test of record: model reply, parse, refusal, the commit gate and the git outcome, in one test. Kills B1-B4 (the weakenings) and B5-B7 (the control).

### Changes to existing tests (update in place; record why inline; never delete)

| File and test | Today | Change |
|---|---|---|
| `tests/test_bf894_builder_write_boundary.py::test_repair_write_control_legitimate_fix_is_written` (line 204) | Its "legitimate" repair writes `tests/test_fixed.py`: it pins the defect as the contract | Use `src/probos/fixed.py`. Assert it is in `result.files_written` and `"Forbidden" not in result.error`. Inline: "BF-898 (#1563): a repair may no longer write a test; the legitimate control is a source file." |
| `tests/test_builder_agent.py::TestTestFixLoop::test_fix_loop_fixes_on_second_try` (line 191) | The approved create and the repair use the slash-free `fixme.py`, which the fix loop now refuses | Move both to `src/probos/fixme.py` (pre-write `tmp_path / "src" / "probos" / "fixme.py"` with its parent created). The assertions are unchanged. Inline reason. |
| `tests/test_builder_agent.py::TestTestFixLoop::test_fix_loop_exhausts_retries` (line 235) | The same with `broken.py`; `fix_attempts == 2` would become 1 under the refusal | Move to `src/probos/broken.py`. The assertions are unchanged. Inline reason. |

Unchanged, and they must stay green (verify; do not edit):
- `tests/test_bf894_builder_write_boundary.py::test_repair_write_is_path_validated`: every alias is still refused by `builder_write_refusal` first, with its "Forbidden" reason.
- `tests/test_bf896_executor_identity_and_blocks.py` repair tests: their repair paths are `src/probos/...` (`:55-58`, `:641`).
- `tests/test_bf897_build_pipeline_scale_and_checkout.py`: its repair is `src/probos/foo.py` (`:462-469`), and `control.fix_attempts == 2` (`:701`) still holds.
- `tests/test_builder_agent.py`: `TestCommitGate`, `TestEscalationHook`, and the other `TestTestFixLoop` tests (no repair block is applied).
- `tests/test_bf896_session_permission_handler.py` and `tests/test_bf896_dispatcher_confinement_seam.py`: `builder_write_refusal` is unchanged, and the visiting route has no fix loop.
- `tests/test_ad521_swe_pipeline_separation.py`: the signature is unchanged.
- `tests/test_ad1152_agentic_correlation.py`: no config field is added.

### Focused gate (per milestone)

`d:/ProbOS/.venv/Scripts/pytest.exe -n 0 -q` on these files:
- `tests/test_bf898_fix_loop_grader_protection.py`
- `tests/test_builder_agent.py`
- `tests/test_bf894_builder_write_boundary.py`
- `tests/test_bf896_executor_identity_and_blocks.py`
- `tests/test_bf897_build_pipeline_scale_and_checkout.py`
- `tests/test_builder_guardrails.py`
- `tests/test_bf892_spawn_env.py`
- `tests/test_bf896_session_permission_handler.py`
- `tests/test_ad521_swe_pipeline_separation.py`
- `tests/test_ad1152_agentic_correlation.py`

The broad gate runs once for BF-898 alone (BF-897 merged separately as `f2b884d3`), in the main session, per the orchestrator.

## Mutation campaign

Apply each mutant alone to the built tree, run the named killer, confirm it fails, and restore the file. Each anchor is one line that occurs exactly once in the named file after the build (leading spaces are part of the anchor). Rows P and N run only test 1 (`-k test_fix_loop_self_test_passes`), so each costs one fast run.

| # | File | Anchor | Replacement | Expected killer |
|---|---|---|---|---|
| P1 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/cognitive/builder.py",` | `    # removed` | T-S 1 |
| P2 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/cognitive/builder_paths.py",` | `    # removed` | T-S 1 |
| P3 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/cognitive/code_reviewer.py",` | `    # removed` | T-S 1 |
| P4 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/cognitive/copilot_adapter.py",` | `    # removed` | T-S 1 |
| P5 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/execution/command_env.py",` | `    # removed` | T-S 1 |
| P6 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/extensions/sealed_core.py",` | `    # removed` | T-S 1 |
| P7 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/build_dispatcher.py",` | `    # removed` | T-S 1 |
| P8 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/build_pipeline.py",` | `    # removed` | T-S 1 |
| P9 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/worktree_manager.py",` | `    # removed` | T-S 1 |
| P10 | `src/probos/cognitive/builder_paths.py` | `    "src/probos/routers/build.py",` | `    # removed` | T-S 1 |
| N1 | `src/probos/cognitive/builder_paths.py` | `    "conftest.py",` | `    # removed` | T-S 1 |
| N2 | `src/probos/cognitive/builder_paths.py` | `    "pytest.ini",` | `    # removed` | T-S 1 |
| N3 | `src/probos/cognitive/builder_paths.py` | `    ".pytest.ini",` | `    # removed` | T-S 1 |
| N4 | `src/probos/cognitive/builder_paths.py` | `    "tox.ini",` | `    # removed` | T-S 1 |
| N5 | `src/probos/cognitive/builder_paths.py` | `    "setup.cfg",` | `    # removed` | T-S 1 |
| L1 | `src/probos/cognitive/builder_paths.py` | `    refusal = builder_write_refusal(path_str, work_dir)` | `    refusal = None` | T-S 1, T-S 4; `test_bf894_builder_write_boundary.py::test_repair_write_is_path_validated` |
| L2 | `src/probos/cognitive/builder_paths.py` | `    if any(part in ("", ".") for part in parts):` | `    if False:` | T-S 1 |
| L3 | `src/probos/cognitive/builder_paths.py` | `    if len(parts) < 3 or tuple(parts[:2]) != FIX_LOOP_WRITABLE_ROOT:` | `    if False:` | T-S 1; T-R 11 (`delete_test`, `skip_marker`, `edit_assertion`) |
| L4 | `src/probos/cognitive/builder_paths.py` | `    canonical = "/".join(_canonical(part) for part in parts)` | `    canonical = "/".join(parts).upper()` | T-S 1 (the trailing-dot and U+200C examples) |
| L5 | `src/probos/cognitive/builder_paths.py` | `    if canonical in _FIX_LOOP_PROTECTED:` | `    if False:` | T-S 1 |
| L6 | `src/probos/cognitive/builder_paths.py` | `    if _canonical(parts[-1]) in _FIX_LOOP_REFUSED:` | `    if False:` | T-S 1 |
| L7 | `src/probos/cognitive/builder_paths.py` | `        if observed != refused:` | `        if False:` | T-S 3 |
| B1 | `src/probos/cognitive/builder.py` | `                            fix_loop_write_refusal(change["path"], work_dir)` | `                            builder_write_refusal(change["path"], work_dir)` | T-U 6; T-R 11 (the five weakenings) |
| B2 | `src/probos/cognitive/builder.py` | `                    if fix_refusals:` | `                    if False:` | T-U 6; T-R 11 |
| B3 | `src/probos/cognitive/builder.py` | `                        validation_errors.extend(fix_refusals)` | `                        pass` | T-U 6 ("BF-898" in the error); T-R 11 |
| B4 | `src/probos/cognitive/builder.py` | `                        break  # BF-898: no further repair attempt` | `                        pass` | T-U 6 (`foo.py` changed, runner awaited more than once); T-R 11 (test bytes, `spy.calls`) |
| B5 | `src/probos/cognitive/builder.py` | `                            fix_loop_files.append(change["path"])` | `                            pass` | T-U 7; T-R 11 (`source_fix`) |
| B6 | `src/probos/cognitive/builder.py` | `                        result.metadata["fix_loop_files"] = sorted(fix_loop_files)` | `                        pass` | T-U 7; T-R 11 (`source_fix`) |
| B7 | `src/probos/cognitive/builder.py` | `                        "\n\nChanged by the unreviewed test-fix loop (BF-898): "` | `                        "\n\n"` | T-U 7; T-R 11 (`source_fix`) |
| B8 | `src/probos/cognitive/builder.py` | `            path_error = builder_write_refusal(change["path"], work_dir)` | `            path_error = fix_loop_write_refusal(change["path"], work_dir)` | T-U 8; also `TestCommitGate` (slash-free `module.py`) |
| B9 | `src/probos/cognitive/builder.py` | `        "You may change only source files under src/probos/ (BF-898). Do not change "` | `        ""` | T-U 9 |

The campaign of record is the Builder's, on the frozen candidate. Record the base tree and the sha256 of `builder_paths.py` and `builder.py`. A file that later differs reruns its own rows only.

## Hidden pins (grep each before editing; each is handled above)

- `grep -rn "tests/test_fixed.py" tests/`: `test_bf894_builder_write_boundary.py:206,208` (changed).
- `grep -rn "===MODIFY: fixme.py\|===MODIFY: broken.py" tests/`: `test_builder_agent.py:2205,2248` (changed). No other fix-loop reply in the tests writes outside `src/probos/`: the other `===MODIFY:`/`===FILE:` hits in `test_builder_agent.py` are parser and generation tests, not `execute_approved_build` replies.
- `grep -rn "Syntax errors" tests/`: `test_bf896_executor_identity_and_blocks.py:585,600,615` and `test_builder_guardrails.py:335`. The lead is unchanged, and these are approved-write syntax errors.
- `grep -rn "Co-Authored-By: ProbOS" tests/`: none. No test pins the commit-message text.
- `grep -rn "_build_fix_prompt" tests/`: `test_builder_agent.py:26,2298`. It checks truncation only (`"X" * 3000`), so it is unchanged.
- `grep -rn "fix_attempts == " tests/`: `test_bf896_executor_identity_and_blocks.py:675` (repair to `src/probos/newpkg/fresh.py`, allowed); `test_bf897_build_pipeline_scale_and_checkout.py:685,701,722,741,763` (allowed path, or no fix loop); `test_builder_agent.py:2188,2231,2264,2292,2344` (2231 and 2264 are changed above).
- `grep -rn "ALLOWED_PATH_PREFIXES\|FORBIDDEN_PATHS" src/ tests/`: `builder_paths.py` only (unchanged).
- `grep -rn "from probos.cognitive.builder_paths import" src/ tests/`: `builder.py:22` (Section 2.1), `copilot_adapter.py:24` (unchanged), `routers/build.py:16` (unchanged), and the BF-894 and BF-897 test files (unchanged).
- `grep -rn "metadata ==" tests/test_builder*.py tests/test_bf89*.py`: none. The new key cannot break an equality pin.
- Source-scan tests over `builder.py` (`getsource`, `read_text` of the file): none found (`grep -rn "getsource(.*builder\|builder\.py\").read_text" tests/`).

## What this does not change

- `builder_write_refusal`, `ALLOWED_PATH_PREFIXES`, `FORBIDDEN_PATHS` and `operator_checkout_refusal`. The approved writes keep their scope (D-b).
- The BF-896 Copilot SDK route: `build_dispatcher.py`, the adapter, its permission policy (`copilot_adapter.py:254`, which calls `builder_write_refusal`), the identity pin and adoption.
- The native SWE harness route (AD-546), `run_command` and anything AD-1328 or AD-1335 owns.
- BF-897's test phase (`_run_targeted_tests`, `_classify_test_run`, `TARGETED_TEST_TIMEOUT_S`, the `not_run` and `timed_out` handling), the entry guard, `merge_to_main`, `/approve` and `/resolve`.
- `BuildResult`'s fields, `BuildFailureReport`, `classify_build_failure`, `_parse_file_blocks` and `_check_sealed_path`.
- `config/system.yaml` and every config model. AD-481l is not built.

## Tracking

- `DECISIONS.md`: Section 4. The orchestrator appends the review and evidence line at closure.
- `PROGRESS.md`: Section 5.
- `docs/development/architecture-reference.md`: Section 3 (the builder's write boundary).
- `docs/development/roadmap.md` Bug Tracker: no row.
- #1563, from the orchestrator:
  - the D-a to D-e rankings;
  - the recorded findings: source-side forging (AD-1336), the visiting route's unseen approved blocks, AD-481l left unfiled, and the fix loop's current unreachability;
  - a follow-up note that `docs/research/reference-projects.md` gains an ImpossibleBench row (Research lines).

## Acceptance criteria

- [ ] During the fix loop, a block that writes a test file, any `conftest.py`, pytest configuration (`pytest.ini`, `.pytest.ini`, `tox.ini`, `setup.cfg`; `pyproject.toml` stays forbidden everywhere), anything outside `src/probos/`, or a `FIX_LOOP_PROTECTED_PATHS` entry is refused. The whole response is refused, nothing is written, the loop stops, and the commit is blocked with a reason naming `BF-898` and the path.
- [ ] Approved writes may still write tests, `conftest.py` and pytest configuration (T-U 8).
- [ ] `metadata["fix_loop_files"]` and the commit message name every file the fix loop changed, and only those (T-U 7, T-R 11 `source_fix`).
- [ ] Real git, real executor, real pytest: the `conftest_hook`, `delete_test`, `skip_marker`, `edit_assertion` and `root_pytest_ini` repairs are refused and not committed, and the refusal names the path. The `source_fix` repair commits. Each weakening is shown to pass the real targeted run without the rule (T-P 10).
- [ ] `fix_loop_self_test() == ()`, and every protected path and refused name has an example.
- [ ] Every SEARCH block applies exactly once to the BF-897 candidate tree. Rows P1-P10, N1-N5, L1-L7 and B1-B9 are each killed.
- [ ] The default-config golden pin `tests/test_ad1152_agentic_correlation.py` passes unchanged.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior art and blind spots

Date used: 2026-10-16.

- **Internal.** `docs/research/darwin-godel-machine-absorption.md` drove #1563: the DGM agent removed the markers its hallucination check relied on. Absorbed: the grader is protected by construction, not by detection.
- **External.** ImpossibleBench (Zhong et al., arXiv 2510.20270; [summary](https://www.lesswrong.com/posts/qJYMbrabcQqCZ7iqm/impossiblebench-measuring-reward-hacking-in-llm-coding-1)) measured coding agents passing tests that contradict the specification.
  - It reports that read-only tests are "a promising middle ground" (hiding tests cut cheating to near zero but also cut legitimate performance), and that an explicit abort option cut cheating sharply for some model families.
  - **Absorbed:** read-only tests, as the source-only rule; the abort, as the fix prompt's "say so and output no blocks", which ends in a Captain-visible failure.
  - The same work lists source-side strategies: operator overloading, recorded state, special-casing. **Recorded:** they are out of reach of any path rule and are the residual risk below.
  - EvilGenie (arXiv 2511.21654) notes that some "hacks" are corrections of a wrong test. **Adapted:** that case goes to the Captain, not to the unreviewed loop.
- **`reference-projects.md`.** SWE-agent (last reviewed 2026-03-20), Aider and Cursor (2026-06-13) and OpenCode (2026-05-08) are overdue on the 90-day interval: considered, deferred. One search on SWE-bench's harness did not confirm how it isolates its reference tests from the model's patch, so nothing here rests on it. Row updates for the orchestrator: none examined. Proposed new row under Research lines: "ImpossibleBench (reward hacking in coding agents) | 2026-10-16 | checked | BF-898 (#1563) Prior art".
- **Blind spots found and absorbed:**
  - A slash-free name passes `builder_write_refusal` (`builder_paths.py:95`): a root `conftest.py`, `pytest.ini` or `sitecustomize.py`. Closed for the fix loop by the `src/probos/` rule.
  - `src/` is on the pytest subprocess's `PYTHONPATH` ahead of site-packages (`builder.py:2418-2422`), so `src/pytest.py`, `src/_pytest/...` and `src/sitecustomize.py` shadow the grader. Closed by the same rule.
  - Refusing per block and continuing (BF-894's shape) still applied the response's other blocks and spent another deep-tier call. Absorbed: whole-response refusal and a stop.
- **Recorded, not fixed (residual risk Medium):** a source-side fix can still forge a pass, for example with `os._exit(0)` at import or by patching `_pytest` from an imported module. The issue's premise that "the test result itself is not forgeable" is not quite right: the code under test runs in the grader's process. This is owned by AD-1336 (#1558, only service-written evidence counts) and mitigated here by the commit-message disclosure.
- **Considered, deferred:**
  - A symlink write-through check.
  - A runtime self-test.
  - Relabelling the "Syntax errors:" lead.
  - A refusal rule for the approved writes on the visiting route (AD-1336).
  - A fix `MODIFY` of a file this build created lists it in both `files_written` and `files_modified` (`builder.py:2992-2993`, pre-existing; `git add` takes the duplicate).

## Verified Against Codebase (2026-10-16, the BF-897 candidate tree)

```text
grep -n "builder_write_refusal|_parse_file_blocks|_build_fix_prompt|_check_sealed_path|validation_errors|not in build spec target list|NO_TARGETED_TESTS|_classify_test_run|operator_checkout_refusal|def execute_approved_build|tests_passed|class BuildResult" src/probos/cognitive/builder.py
  22:  from probos.cognitive.builder_paths import builder_write_refusal, operator_checkout_refusal
  92:  _validate_file_path = builder_write_refusal
  119: class BuildResult:          (fields 122-138; metadata: dict[str, Any] = field(default_factory=dict) at 138)
  2334: def _parse_file_blocks(text: str) -> list[dict[str, Any]]:   (modes: "create" 2347, "modify" 2392)
  2431: NO_TARGETED_TESTS = (
  2546: def _classify_test_run(passed: bool, output: str) -> str:
  2562: def _build_fix_prompt(      (prompt text 2577-2580)
  2624: def _check_sealed_path(...)  (warn-only; gated by enforce_sealed_core)
  2693: checkout_refusal = operator_checkout_refusal(work_dir, _PROJECT_ROOT)
  2749: validation_errors: list[str] = []
  2754: path_error = builder_write_refusal(change["path"], work_dir)
  2874-2883: 4b. Warn about files not in build spec target list (logger.warning only)
  2885-2908: 4c. Code review (AD-341) on file_changes only; soft gate
  2910-2913: 5. Run tests with fix loop; all_changes / all_changed_files
  2917-2933: BF-897 targeted run, _classify_test_run, break unless "failed"
  2951: fix_changes = BuilderAgent._parse_file_blocks(
  2969-3012: Apply fix changes; 2973 repair_error = builder_write_refusal(change["path"], work_dir)
  3041-3043: elif validation_errors: result.error = "Syntax errors:\n" + ...; success False
  3074-3080: commit_msg = (... Co-Authored-By: ProbOS Builder ...)
  3081: ok, sha = await _git_add_and_commit(written + modified_files, commit_msg, work_dir)
Read builder.py:2418-2422   _pytest_pythonpath: f"{work_dir}{os.pathsep}{src_dir}" + existing PYTHONPATH
Read builder.py:2470-2501   _map_source_to_tests: tests/test_{stem}*.py; a test_* name maps to tests/<name>
Read builder.py:1573-1576   _sanitize_branch_name: [^a-z0-9-]+ -> "-"
Read builder.py:1634-1649   _git_add_and_commit(files, message, work_dir): add -- files; commit -m message
Read builder.py:3096-3119   finally: _git_checkout_main; branch -D on no commit; unlink files_written
Read builder_paths.py:30-44 ALLOWED_PATH_PREFIXES ("src/","tests/","config/","docs/","prompts/"); FORBIDDEN_PATHS (".git/",".env","pyproject.toml",".github/")
Read builder_paths.py:55-57 _canonical: HFS-ignorables dropped, trailing " ." trimmed, upper-cased
Read builder_paths.py:95    if "/" in normalized and not any(normalized.startswith(p) ...)   (slash-free names pass)
Read builder_paths.py:104-123  _git_identity_refusal (the SEARCH anchor of Section 1.2 ends it at 121-123)
Read config/sealed_modules.yaml   builder.py and architect.py sealed; code_reviewer.py, builder_paths.py, tests/** not
Read execution/command_policy.py:1773-1803   self_test judges each rule's match/not_match examples with the runtime evaluator
grep -n "builder_write_refusal" src/probos/cognitive/copilot_adapter.py
  24: import; 254: if kind == "write" and builder_write_refusal(rel) is not None:
Read build_dispatcher.py:215-222   execute_approved_build(file_changes=..., run_tests=self._run_tests, builder_source="visiting", expected_git_dir=...)  (no llm_client)
Read routers/build.py:383-410      _execute_build -> execute_approved_build(..., llm_client=getattr(rt, "llm_client", None), escalation_hook=None)
Read routers/build.py:136-150      /resolve retry_* -> _execute_build (the only caller)
Read worktree_manager.py:170-207   adopt_commit: rev-parse, checkout, merge --ff-only, branch -D (git only)
Glob src/probos/{cognitive/code_reviewer.py,cognitive/copilot_adapter.py,execution/command_env.py,extensions/sealed_core.py,build_dispatcher.py,build_pipeline.py,worktree_manager.py,routers/build.py}   all 8 exist
Read tests/test_bf897_build_pipeline_scale_and_checkout.py:71-128, 462-551   helpers and fakes to copy
Read tests/test_bf896_executor_identity_and_blocks.py:55-61, 621-678         repair paths under src/probos/
Read tests/test_bf894_builder_write_boundary.py:182-208                      _repair_build; the tests/test_fixed.py control
Read tests/test_builder_agent.py:2167-2344, 2615-2723                        TestTestFixLoop, TestCommitGate
Read tests/test_bf892_spawn_env.py:46-86                                     real nested pytest via _run_targeted_tests, timeout(150)
Read docs/development/architecture-reference.md:187                          the test-fix loop line
Read DECISIONS.md:54; PROGRESS.md:1-3                                        the BF-897 entries (SEARCH anchors)
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py                     CEILING AD-1341 (no number allocated)
```

## Absence Verified (2026-10-16)

| Claim | Run | Found | Holds |
|---|---|---|---|
| A fix block can only create or modify (no delete mode) | read `_parse_file_blocks` (`builder.py:2334-2396`) | `"mode": "create"` (2347), `"mode": "modify"` (2392); nothing else is appended | yes |
| No other post-approval site applies model-authored blocks | grep `_parse_file_blocks\(` and `\.write_text\(` in `src/probos` | parses: `builder.py:739,1057,2305` (generation), `:2951` (fix loop), `copilot_adapter.py:794` (visiting generation), `build_pipeline.py:113` (wrapper); writes in the build path: `builder.py:2833,2854` (approved), `:2991,2998` (fix loop); `copilot_adapter.py:318` seeds the session directory with repository files; `swe_harness/tools.py:970,1087` (AD-546, out of scope) | yes |
| The visiting route never runs the fix loop | read `build_dispatcher.py:215-222` | no `llm_client` argument (default `None`; the loop needs one, `builder.py:2935`) | yes |
| The fix loop is unreachable in production on this tree | grep `_execute_build\(` and `_pending_failures` in `src/probos` | `routers/build.py:150` (in `/resolve`, the only caller); `_pending_failures` is written only at `routers/build.py:435` (inside `_execute_build`); `/approve` no longer schedules it (BF-897) | yes: latent until AD-1336 child 5 |
| No test pins the commit-message text | grep `Co-Authored-By: ProbOS` in `tests/` | none | yes |
| No test outside the three changed ones gives the fix loop a reply outside `src/probos/` | grep `(MODIFY\|FILE):\s*(tests/\|conftest\|pytest\.ini\|config/\|docs/\|prompts/\|src/[a-oq-z])` in `tests/`, then read each `execute_approved_build` fix-loop test | `test_builder_agent.py:2205,2248` (slash-free; changed) and `test_bf894_builder_write_boundary.py:206` (changed); every other hit is a parser or generation test | yes |
| No source-scan test reads `builder.py` or `builder_paths.py` | grep `getsource\(.*(builder\|execute_approved_build)\|builder\.py"\)\.read_text\|builder_paths\.py` in `tests/` | only `_map_source_to_tests` and architect-context strings (`test_builder_agent.py:3012`, `test_architect_agent.py`) | yes |
| No AD-481l issue exists | grep `AD-481l` across the tree (issue titles via #1563's own search) | code comments, archived prompts, `wave-plan.yaml`, the DGM note; #1563 records "no AD-481l issue exists (searched all issue states)" | yes, per #1563 (not re-run against GitHub here) |
