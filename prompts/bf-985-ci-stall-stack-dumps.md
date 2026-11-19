# BF-985 (#1820, bf-983 F2): a CI shard that stalls writes the stacks of its controller and workers, and a step limit lets them upload

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-19
**Status:** ready to build on `origin/main` `02079977` (after #1832), or on the tree after B4 (PR #1833) merges. B4 must not touch the five code, test and doc files below (premise M0-1). **Oracle:** none. This was a read-only consult: no test was run and no block was applied by a tool. The Builder runs the base check (M0-2) and the mutation campaign (section 9), and that run is the campaign of record.
**Base blobs (`02079977`):** `scripts/_ci_shard_pytest_plugin.py` `97fec40ec58e2c289cc56231792ebbd2414e4542`, `.github/workflows/ci.yml` `ec04bc6cffca9ca12eebd7135f367a64b3927b49`, `tests/test_ci_shards.py` `11f2bd7693a677e20738681f8c2363c4ceba9f19`, `tests/test_ci_shard_pytest_plugin.py` `12f4f70169e154d06f40333afc48866b99831d0f`, `docs/development/test-suite-optimization-plan.md` `3104cfe2b48237db91e72b746297e7f975dc97fb`, `PROGRESS.md` `2dd3e01faeea0f063aa80b30c91878279cc23361`, `DECISIONS.md` `dd1adda1ce831075583555186fceabeb8652e66e`. Unchanged and read: `scripts/ci_shards.py` `49b2c2f2b3eaf0379c19bbb54e45744d2a227d25`. Once B4 merges, only the two tracker blobs may differ, and their SEARCH text is chosen to survive that.
**Tier:** STANDARD. The change is CI diagnostics only: no product code, no gate, and no change to the exactly-once proof. **Estimated tests:** 19 new cases (13 in new functions and 6 new parameters), plus 10 existing cases edited in place, across `tests/test_ci_shard_pytest_plugin.py` and `tests/test_ci_shards.py`. No new test file. **BF number:** BF-985, allocated by the orchestrator. It enumerated 2026-11-19 02:53 to 03:01Z: the highest BF in `git log --all` subjects is BF-983; in issue titles of all states (1,541 issues) BF-984 (#1830); in `prompts/bf-*.md` leading numbers 983; in the roadmap Bug Tracker BF-927. A full-text search of BF-985 to BF-992 found 0 hits. I confirmed `git log --all -i --grep=BF-985`: empty.

**Which text describes the head.** Before building, `git rev-parse HEAD:<path>` must print the first five blobs above. A SEARCH that does not occur exactly once is a hard stop for the Architect. Working copies are CRLF and the SEARCH text is LF. Where the prose and a block differ, the block wins. Every block is ASCII.

## 0. Event types and new names

No EventType, config field, table or schema is added. The new public names are:
- in `scripts/_ci_shard_pytest_plugin.py`: `StallWatchdog`, `DEFAULT_STALL_SECONDS`, and the options `--probos-shard-stack-dir` and `--probos-shard-stall-seconds` (dests `probos_shard_stack_dir`, `probos_shard_stall_seconds`);
- in `ci.yml`: the step `Upload stall stack dumps` and the artifact `ci-shard-stacks-K`.

None of these occurs in the repository today. A grep for `StallWatchdog|probos-shard-stack|ci-shard-stacks` over the repository finds nothing (section 12).

## 1. Problem

Three CI Python shards have stalled. Each printed `[ 99%]`, then printed nothing until the 45-minute job limit (`ci.yml:27`) cancelled it with `##[error]The operation was canceled.`:
- run 44395509240 (shard 1, 2026-11-18): `[ 99%]` 12.6 minutes into `Run tests`;
- run 41764125537 (shard 1, 2026-11-04): `[ 99%]` at 13.8 minutes;
- #1452 item 8 (run 36907487200, before the sharding).

In each, the runner's cleanup ended `uv` and five `python` processes (the controller and gw0 to gw3), so no process of the shard had exited. A hung test would have failed at pytest-timeout's 180 s (`pyproject.toml:190`), so the stall is outside one test.

Nothing records where those processes were:
- The log is `-q`.
- The per-worker evidence (`_ci_shard_pytest_plugin.py:164-187`) is written only at session finish.
- A cancelled job skips the `Upload shard evidence` step (`ci.yml:77-78`, `if: ${{ !cancelled() }}`).

#1452 proposed a faulthandler watchdog and closed with item 8 unchecked.

## 2. Solution

Three parts, none of which changes the exactly-once proof:

1. **The watchdog.** The shard plugin gains an optional `--probos-shard-stack-dir DIR`. With it, every pytest process (the controller, each worker, or the only process under `-n 0`) opens `DIR/faulthandler-<controller|gwN>.txt` for its whole life. It arms `faulthandler.dump_traceback_later(S, repeat=True, file=...)` with S = 600 s by default. Every test event the process sees re-arms the timer, so the file holds a dump of every thread only after about S seconds with no event, and then another every S seconds. The timer is re-armed, never cancelled, at session finish and unconfigure. A process held at exit by a leftover non-daemon thread is therefore dumped too.
2. **The step limit.** `Run tests` gets `timeout-minutes: 38`. A step that reaches its own limit fails without cancelling the job (`actions/runner` `StepsRunner.cs`: `Result = TaskResult.Failed` when the job token is not cancelled), so later steps still run.
3. **The upload.** A new step `Upload stall stack dumps` uploads `DIR` as `ci-shard-stacks-K` on `failure() || cancelled()`, before the evidence upload. The evidence upload stays the last step, unchanged.

Heavier designs rejected:
- **Dumps inside the evidence directory, with a verifier exception.** It widens what `verify` reads for a diagnostic; the separate directory costs one step.
- **A Python watchdog thread calling `faulthandler.dump_traceback`.** It needs the GIL, so a hang that holds the GIL would never be dumped. faulthandler's own timer is a C thread.
- **pytest's `faulthandler_timeout`.** It covers only the time inside one test, and the stall is outside one.
- **An automatic retry of a stalled shard, or a longer job limit.** Both hide the stall.

## 3. Decisions

- **D1. Where the dumps live.**
  - **New optional option `--probos-shard-stack-dir DIR`** (default `None`, so no watchdog), like `--probos-shard-durations`: ignored when the plugin is inert, and the relative path resolves against the rootpath.
  - **Rejected: deriving the directory from the evidence directory.** A sibling path chosen by the plugin would couple the two and arm a watchdog in every local shard run.
  - **One file per process, opened in `pytest_configure`** (mode `w`), and never closed by the plugin. faulthandler holds a strong reference to the file object and writes to its descriptor from its C thread.
  - **Name: `controller` for any process that is not an xdist worker.** This avoids a fragile `-n 0` detection, and under `-n 0` that process is the whole run.
  - **An empty file after a normal run is kept.** Deleting it means doing so while the timer is armed, and the end-of-run window is the one the stalls point to. On Windows an open file cannot be deleted, and on Linux an unlinked file loses the dump. An empty file means "never silent for S seconds".
  - **Upload step:** `Upload stall stack dumps`, placed directly before `Upload shard evidence`, with:
    - `if: ${{ failure() || cancelled() }}`: green runs upload nothing, a step limit is `failure()`, and a cancellation is covered where the runner honours it;
    - `if-no-files-found: ignore`: a run that failed before pytest started has no directory;
    - `overwrite: true` and `retention-days: 7`, as for the evidence.
  - **The artifact name `ci-shard-stacks-K` must not match the summary job's `ci-shard-evidence-*` download pattern.** Otherwise the dumps land in the evidence root and `verify` fails (fact 1). The new test W4 pins this.
  - **`verify`, the download and the summary job are unchanged.**
- **D2. The bound and its arming.**
  - **The bound is 600 s, as an int option `--probos-shard-stall-seconds`, >= 1.** The option exists for the doubles (1 s).
  - **Why 600 s:**
    - The longest healthy silent stretch is one test phase, because each phase report re-arms.
    - CI's per-phase caps are pytest-timeout's 180 s, the AD-1192 capacity test's 300 s (`tests/test_ad1192_owned_steps_store.py:2888`), the AD-1198 gates' 300 and 480 s, and three #1419 cases at 600 s (`tests/test_issue1419_failed_start_rollback.py:2822,2844,2874,2943`). `tests/ablation` (3600 s) skips without live backends.
    - Worker collection, which emits no events, ends long before 600 s (the whole shard reached `[ 99%]` in 12.6 to 13.8 minutes).
    - A stall that starts at about 14 minutes gives dumps at about 24 and 34 minutes, before the 38-minute step limit. Two dumps 10 minutes apart separate a deadlock (the same stack twice) from slow progress.
    - A dump never changes an outcome (`exit=False`), so an early dump costs only a file with content.
  - **`repeat=True`.**
  - **Arming points, all on the `StallWatchdog` plugin object** registered in every process by the module-level `pytest_configure`:
    - `pytest_sessionstart` (tryfirst) arms. Construction does not arm, so the in-process unit tests never touch the timer of the worker running them.
    - `pytest_runtest_logstart` and `pytest_runtest_logreport` re-arm. xdist forwards both to the controller (`xdist/dsession.py:308-329`), so the controller is re-armed by every worker's events.
    - `pytest_exception_interact` (trylast) re-arms unconditionally. This is a sixth fact: pytest's own faulthandler plugin cancels the process's one timer there, tryfirst and regardless of `faulthandler_timeout` (`_pytest/faulthandler.py:113-119`). pytest calls that hook after the phase's logreport for every failing phase (`_pytest/runner.py:250-253`). Without the re-arm, every failing test would disarm the watchdog until the next event.
    - `pytest_sessionfinish` (tryfirst) and `pytest_unconfigure` (trylast) re-arm unconditionally.
  - **Throttle: a test event re-arms only when at least S/20 seconds** (30 s at 600) have passed since the last arm, measured with an injected `time.monotonic`. Each `dump_traceback_later` call joins the old watchdog thread and starts a new one (CPython 3.12 `faulthandler.c`). The controller sees about 4 events per test for its whole shard, about 72k at 18k tests. The cost is a dump up to S/20 early: a dump means at least 570 s with no event.
- **D3. End of run: re-arm and stay armed until exit (fact 5).**
  - A worker is shut down as soon as the work queue is empty (`xdist/scheduler/loadscope.py:313-326`; `tests/fixtures/duration_scheduler.py:274` inherits it). It never idles waiting for the controller, so a process silent for 600 s after its last event is the stall, not a false positive.
  - `Py_Finalize` cancels the timer on a normal exit (`_PyFaulthandler_Fini`).
  - The in-repo prior art arms a watchdog as `main` returns, for exactly the #1419 "leftover non-daemon thread keeps the interpreter alive" case (`tests/fixtures/failed_start_child.py:73,213-214`, `rollback_child.py:217-224`, `federation_cluster_node.py:238`).
  - Rejected: cancelling at session finish (my 2026-11-18 direction). It would blind the window after session finish (another plugin's session finish, unconfigure, atexit, `threading._shutdown`).
- **D4. The guard (fact 4).**
  - `pytest_configure` refuses `--probos-shard-stack-dir` when `faulthandler_timeout` > 0. pytest would then arm and cancel the same timer around every test (`_pytest/faulthandler.py:88-102`), silently defeating the watchdog.
  - `getini` raising `ValueError` means pytest's faulthandler plugin is off (`-p no:faulthandler`) and reads as 0 (`_pytest/config/__init__.py:1677-1680`).
  - `--probos-shard-stall-seconds` without a stack directory, a value below 1, an empty directory, and a worker id that is not `gwN` are refused too, all before any file is created or plugin registered.
  - `--pdb` also cancels the timer (`pytest_enter_pdb`). CI never uses it, so it is not handled (L5).
- **D5. Fork safety.**
  - CPython 3.12 `faulthandler.c` has no fork handling. A forked child inherits "armed" without the watchdog thread, with the `running` lock held. If that child reaches `Py_Finalize`, it blocks in `cancel_dump_traceback_later`.
  - Nothing in `src/` or `tests/` forks the pytest process (section 12, Absence):
    - `subprocess` execs at once;
    - `multiprocessing` fork children leave through `os._exit`;
    - BF-892's guard forbids `multiprocessing` launch APIs in `src`.
  - Recorded as L6, with no `os.register_at_fork` hook. Such a hook is process-global and cannot be unregistered, so it would leak into the in-process unit tests.
- **D6. `ci.yml`.**
  - **`timeout-minutes: 38` on `Run tests`.** Hung runs reached `[ 99%]` at 12.6 and 13.8 minutes, and BF-322 measured 18 to 22 minutes for the whole unsharded suite. 38 minutes is about 2.5 times a healthy shard and leaves at least 7 minutes of the job's 45 for setup (about 2) and the two uploads. M0-11 measures green runs.
  - **The rationale comment sits between `- name: Run tests` and `run:`, beside the BF-322 and BF-657 text,** which stays in place.
  - **`ci.yml:78` is unchanged (`!cancelled()`).** After a step limit the job is not cancelled, so the evidence uploads. Its partial content is a second signal: a worker missing from `shard-K/` never reached session finish. The summary job then fails at `Require every shard to succeed`, as for any red shard, before downloading anything. `always()` there would only upload evidence of a cancelled job, which nothing reads.
- **D7. Pins.** Each changed pin, and why it still guards what it guarded, is listed in section 8.

## 4. Every consumer (each command and what it found is in section 12)

| Consumer | Effect |
|---|---|
| `.github/workflows/ci.yml` shard job | new option on the command, step limit, new upload step before the evidence upload |
| `python-tests` job (download `ci-shard-evidence-*`, `verify`) | unchanged; the stacks artifact cannot match the pattern (W4) |
| `scripts/ci_shards.py` (`_read_shards`/`_read_shard`, `:418-462`) | unchanged; the dumps never enter the evidence root |
| `tests/test_ci_shards.py` (workflow drift guard `:1518-1698`) | W1 to W5 (section 8) |
| `tests/test_ci_shard_pytest_plugin.py` | modified cases and new cases (section 8) |
| `docs/development/test-suite-optimization-plan.md` P2.7 row (`:268`) | one bullet |
| `scripts/run_test_gate.py` | does not load this plugin; untouched |
| `tests/fixtures/file_durations.json` | names the test file; not regenerated (the new cases add seconds to one file; the split tolerates drift) |

## 5. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | T1 to T11 (tests), then P1 to P6 (plugin) | G0 (base), then G1 |
| M2 | W0 to W5 (pins), then Y1 (`ci.yml`) | G2 |
| M3 | D1 (doc row), K1 (PROGRESS), K2 (DECISIONS), then the ledger pair | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`.

**M0: premises to verify first-hand, each with its probe.** A probe that finds nothing where something is expected is a FAIL.

1. **The base.** `git rev-parse HEAD:scripts/_ci_shard_pytest_plugin.py HEAD:.github/workflows/ci.yml HEAD:tests/test_ci_shards.py HEAD:tests/test_ci_shard_pytest_plugin.py HEAD:docs/development/test-suite-optimization-plan.md` must print the header blobs. If B4 has merged, `git diff --stat 02079977 HEAD -- <those five>` must also be empty.
2. **The base shows the defect.** Apply T1 to T11 only, then run `PY -m pytest tests/test_ci_shard_pytest_plugin.py -q -n 0 -p no:randomly`.
   - **Expected to fail:**
     - the 8 cases that use `sharded_run`: the run exits 4 on the unknown `--probos-shard-stack-dir`;
     - `test_the_command_line_form_ci_uses_works_with_space_separated_options`;
     - the two new misconfiguration cases, on the message: the base says `unrecognized arguments`;
     - I1, I2 and I3;
     - U1, the three new U3 parameters (`DID NOT RAISE`), U4 x2, U5 x2, U6 x2, U7, U8 and U9.
   - **Expected to pass:** U2 (a guard) and every unmodified case.
   - Then apply W0 to W5 only and run `PY -m pytest tests/test_ci_shards.py -q -n 0 -p no:randomly`. Expected: W1, W2, W3, W4 and W5 fail; everything else passes.
3. **pytest's faulthandler plugin cancels in `pytest_exception_interact`.**
   ```
   PY -c "import inspect,_pytest.faulthandler as f; print('cancel_dump_traceback_later' in inspect.getsource(f.pytest_exception_interact))"
   ```
   Expected: `True`.
4. **One timer per process; a second arm replaces the first.**
   ```
   PY -c "import faulthandler,sys,time; faulthandler.dump_traceback_later(30, file=sys.stdout); faulthandler.dump_traceback_later(1, file=sys.stdout); time.sleep(2.5); faulthandler.cancel_dump_traceback_later()"
   ```
   Expected: exactly one `Timeout (0:00:01)!` block, and the process ends in about 2.5 s.
5. **`getini` raises `ValueError` for an unregistered key.**
   ```
   PY -c "import inspect,_pytest.config as c; print('unknown configuration value' in inspect.getsource(c))"
   ```
   Expected: `True`.
6. **xdist shuts down a worker as soon as the queue is empty.**
   ```
   PY -c "import inspect; from xdist.scheduler.loadscope import LoadScopeScheduling as L; s=inspect.getsource(L._reschedule); print('if not self.workqueue' in s and 'node.shutdown()' in s)"
   ```
   Expected: `True`.
7. **`workerinput` is set before `pytest_configure` in a worker.**
   ```
   PY -c "import inspect,xdist.remote as r; s=inspect.getsource(r); print(s.index('config.workerinput = workerinput') < s.index('config.hook.pytest_cmdline_main(config=config)'))"
   ```
   Expected: `True`.
8. **Nothing else uses faulthandler in the pytest process, and nothing forks it.**
   - `git grep -n "faulthandler.dump_traceback_later" -- src scripts tests`. Expected: exactly 6 lines, in `tests/fixtures/rollback_child.py`, `failed_start_child.py` and `federation_cluster_node.py`. This is the control.
   - `git grep -n -E "import (failed_start_child|rollback_child|federation_cluster_node)|fixtures\.(failed_start_child|rollback_child|federation_cluster_node)" -- src tests`. Expected: nothing (they run as child scripts).
   - `git grep -n -E "os\.fork\(|forkpty|pty\.fork|get_context\(.fork|set_start_method" -- src tests`. Expected: nothing.
   - `git grep -n faulthandler_timeout`. Expected: nothing before M1.
9. **xdist and pytest versions.** `PY -c "import xdist, pytest; print(xdist.__version__, pytest.__version__)"`. Expected: `3.8.0 9.0.2` (`uv.lock`). Differing versions are a hard stop only if probes 3, 6 or 7 fail.
10. **The number.** `gh issue list --state all --search "BF-985 in:title"`. Expected: nothing.
11. **Healthy shard time.** For three recent green `ci.yml` runs on `main`, read the `Run tests` step of each `python-tests-shard (K)` (`gh run view <id> --json jobs`). Expected: each at most 20 minutes, which leaves 38 minutes at least 1.9 times the slowest. More than 20 is a hard stop for the Architect.

**Gates.**
- **G0.** M0-2 as stated.
- **G1** (after P1 to P6):
  - `PY -m pytest tests/test_ci_shard_pytest_plugin.py -q -n 0 -p no:randomly`: 0 failed. Run it twice.
  - Then `PY -m pytest tests/test_ci_shard_pytest_plugin.py -q -n 4` (the nested runs under parallel load): 0 failed.
- **G2** (after Y1):
  - `PY -m pytest tests/test_ci_shards.py tests/test_ci_shard_pytest_plugin.py -q -n 0 -p no:randomly`: 0 failed.
  - `PY -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml', encoding='utf-8'))"`: no error.
  - `PY -P scripts/check_architecture_principles.py --check`: clean.
- **G3** (M3): `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. Commit the ledger pair it writes (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`) with M3.
- **Harness rule.**
  - No source change made to pass a test, no skip, no loosened assertion. A failing case goes back to the Architect.
  - The broad gate runs once, in the main session, with `--receipt`.
  - Stage explicit paths only; never `git add -A`.

## 6. Commit messages

- **M1:** `BF-985 M1: the CI shard plugin arms a faulthandler stall watchdog per process with --probos-shard-stack-dir (#1820)`
- **M2:** `BF-985 M2: a 38-minute limit on Run tests and an upload of the stall stack dumps apart from the evidence (#1820)`
- **M3:** `BF-985 M3: trackers, P2.7 row and ledger (#1820)`. #1820 stays open: no `Closes` line.

## 7. The contract

### 7.1 M1: tests (`tests/test_ci_shard_pytest_plugin.py`), then code (`scripts/_ci_shard_pytest_plugin.py`)

**T1.** `repo_strays` also catches stack files.
SEARCH:
```
    """Evidence-shaped names directly under the repository's root, scripts/ and tests/."""
    patterns = ("shard-*", "*evidence*", ".gw*.tmp", ".main.*.tmp")
    return {
```
REPLACE:
```
    """Evidence- and stack-shaped names directly under the repository's root, scripts/ and tests/."""
    patterns = ("shard-*", "*evidence*", ".gw*.tmp", ".main.*.tmp", "faulthandler-*", "*stacks*")
    return {
```

**T2.** `sharded_run` arms the watchdog (default bound) in both runs.
SEARCH:
```
@pytest.fixture(scope="module")
def sharded_run(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """Shard 1/2 under ``-n 2 --dist=loadfile`` and shard 2/2 under ``-n 0``, one evidence dir."""
    tree = make_tree(tmp_path_factory.mktemp("shard_tree") / "tree")
    evidence = tree.parent / "evidence"
    before = repo_strays()
    first = run_pytest(tree, "suite", "-q", "-n", "2", "--dist=loadfile", *shard_options(1, 2, evidence))
    second = run_pytest(tree, "suite", "-q", "-n", "0", *shard_options(2, 2, evidence))
    return SimpleNamespace(
        tree=tree,
        evidence=evidence,
        durations=tree / "durations.json",
        first=first,
        second=second,
        new_strays=repo_strays() - before,
    )
```
REPLACE:
```
@pytest.fixture(scope="module")
def sharded_run(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """Shard 1/2 under ``-n 2 --dist=loadfile`` and shard 2/2 under ``-n 0``, one evidence dir.

    BF-985: each run also arms the stall watchdog (the default bound) into its own stack dir.
    """
    tree = make_tree(tmp_path_factory.mktemp("shard_tree") / "tree")
    evidence = tree.parent / "evidence"
    stacks = tree.parent / "stacks"
    before = repo_strays()
    first = run_pytest(
        tree, "suite", "-q", "-n", "2", "--dist=loadfile", *shard_options(1, 2, evidence),
        f"--probos-shard-stack-dir={stacks / '1'}",
    )  # fmt: skip
    second = run_pytest(
        tree, "suite", "-q", "-n", "0", *shard_options(2, 2, evidence), f"--probos-shard-stack-dir={stacks / '2'}"
    )
    return SimpleNamespace(
        tree=tree,
        evidence=evidence,
        stacks=stacks,
        durations=tree / "durations.json",
        first=first,
        second=second,
        new_strays=repo_strays() - before,
    )
```

**T3.** The normal run leaves only empty stack files, outside the evidence (acceptance: "a normal run leaves no dump file with content").
SEARCH:
```
def test_the_runs_wrote_only_the_evidence_and_nothing_into_the_repository(
    sharded_run: SimpleNamespace,
) -> None:
    assert sharded_run.new_strays == set()
```
REPLACE:
```
def test_the_runs_wrote_the_evidence_and_empty_stack_files_apart_and_nothing_into_the_repository(
    sharded_run: SimpleNamespace,
) -> None:
    stack_sizes = {
        path.relative_to(sharded_run.stacks).as_posix(): path.stat().st_size
        for path in sharded_run.stacks.rglob("*")
        if path.is_file()
    }

    # BF-985: one stack file per process, outside the evidence, empty after a run that never stalled.
    assert stack_sizes == {
        "1/faulthandler-controller.txt": 0,
        "1/faulthandler-gw0.txt": 0,
        "1/faulthandler-gw1.txt": 0,
        "2/faulthandler-controller.txt": 0,
    }
    assert sharded_run.new_strays == set()
```

**T4.** The CI form with a space-separated `--probos-shard-stack-dir`.
SEARCH:
```
    tree = make_tree(tmp_path / "tree")
    evidence = tmp_path / "ci-shard-evidence"
    command = [
        "suite", "-n", "0", "-q", "--tb=short", "--maxfail=10", *PLUGIN_ARGS,
        "--probos-shard-index", "1", "--probos-shard-count", "2",
        "--probos-shard-evidence-dir", str(evidence), "--probos-shard-durations=durations.json",
    ]  # fmt: skip

    first = run_pytest(tree, *command)
    command[command.index("--probos-shard-index") + 1] = "2"
    second = run_pytest(tree, *command)

    assert (first.returncode, second.returncode) == (0, 0), first.stdout + second.stdout
    assert sorted(read_evidence(evidence)) == ["shard-1/main", "shard-2/main"]
    assert verify(cs, evidence, 2, tree / "durations.json") == 0, capsys.readouterr().out
```
REPLACE:
```
    tree = make_tree(tmp_path / "tree")
    evidence = tmp_path / "ci-shard-evidence"
    stacks = tmp_path / "ci-shard-stacks"
    command = [
        "suite", "-n", "0", "-q", "--tb=short", "--maxfail=10", *PLUGIN_ARGS,
        "--probos-shard-index", "1", "--probos-shard-count", "2",
        "--probos-shard-evidence-dir", str(evidence), "--probos-shard-durations=durations.json",
        "--probos-shard-stack-dir", str(stacks),
    ]  # fmt: skip

    first = run_pytest(tree, *command)
    command[command.index("--probos-shard-index") + 1] = "2"
    second = run_pytest(tree, *command)

    assert (first.returncode, second.returncode) == (0, 0), first.stdout + second.stdout
    assert sorted(read_evidence(evidence)) == ["shard-1/main", "shard-2/main"]
    assert verify(cs, evidence, 2, tree / "durations.json") == 0, capsys.readouterr().out
    assert [(path.name, path.stat().st_size) for path in stacks.iterdir()] == [("faulthandler-controller.txt", 0)]
```

**T5.** Two misconfiguration cases through a real run; no stack directory is created.
SEARCH:
```
@pytest.mark.parametrize(
    "case",
    ["partial options", "index above count under xdist", "count below one", "default durations absent", "bad durations"],
)
def test_misconfiguration_exits_four_before_any_test_or_worker_starts(tmp_path: Path, case: str) -> None:
    tree = make_tree(tmp_path / "tree")
    (tree / "bad.json").write_text('{"schema_version": 2, "files": {}}', encoding="utf-8")
    evidence = tmp_path / "evidence"
    cases = {
```
REPLACE:
```
@pytest.mark.parametrize(
    "case",
    [
        "partial options", "index above count under xdist", "count below one", "default durations absent",
        "bad durations", "stall bound without a stack dir", "stack dir beside faulthandler_timeout under xdist",
    ],
)  # fmt: skip
def test_misconfiguration_exits_four_before_any_test_or_worker_starts(tmp_path: Path, case: str) -> None:
    tree = make_tree(tmp_path / "tree")
    (tree / "bad.json").write_text('{"schema_version": 2, "files": {}}', encoding="utf-8")
    evidence = tmp_path / "evidence"
    stacks = tmp_path / "stacks"
    cases = {
```

**T5b.** The same test: the two cases and the assertion.
SEARCH:
```
        "bad durations": (
            ["-n", "0", *shard_options(1, 2, evidence, durations="bad.json")],
            "durations file bad.json: schema_version must be 1",
        ),
    }  # fmt: skip
    arguments, message = cases[case]

    result = run_pytest(tree, "suite", "-q", *arguments)

    assert result.returncode == 4, result.stdout + result.stderr
    assert message in result.stderr
    assert "bringing up nodes" not in result.stdout and "passed" not in result.stdout
    assert not evidence.exists()
```
REPLACE:
```
        "bad durations": (
            ["-n", "0", *shard_options(1, 2, evidence, durations="bad.json")],
            "durations file bad.json: schema_version must be 1",
        ),
        "stall bound without a stack dir": (
            ["-n", "0", *shard_options(1, 2, evidence), "--probos-shard-stall-seconds=5"],
            "--probos-shard-stall-seconds needs --probos-shard-stack-dir",
        ),
        "stack dir beside faulthandler_timeout under xdist": (
            ["-n", "2", "-o", "faulthandler_timeout=5", *shard_options(1, 2, evidence),
             f"--probos-shard-stack-dir={stacks}"],
            "cannot run with faulthandler_timeout > 0",
        ),
    }  # fmt: skip
    arguments, message = cases[case]

    result = run_pytest(tree, "suite", "-q", *arguments)

    assert result.returncode == 4, result.stdout + result.stderr
    assert message in result.stderr
    assert "bringing up nodes" not in result.stdout and "passed" not in result.stdout
    assert not evidence.exists()
    assert not stacks.exists()
```

**T6.** The three controlled doubles (I1, I2, I3), each a real pytest run that ends by itself.
SEARCH:
```
    assert "shard-1/main reports exitstatus 1, not 0" in out
    assert "missing (never executed): 3" in out


# --- the plugin's hooks, driven in-process for every branch --------------------------
```
REPLACE:
```
    assert "shard-1/main reports exitstatus 1, not 0" in out
    assert "missing (never executed): 3" in out


# --- BF-985: the stall watchdog, against controlled doubles that end by themselves ----

# A distinctively named function that blocks for a few seconds and then returns, so every run ends
# by itself and nothing is killed on the host.
BLOCKER = (
    "def _bf985_blocks_here(seconds):\n"
    "    deadline = time.monotonic() + seconds\n"
    "    while time.monotonic() < deadline:\n"
    "        time.sleep(0.05)\n\n\n"
)
NO_DURATIONS = {"schema_version": 1, "files": {}}


def stack_texts(stacks: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8", errors="replace") for path in sorted(stacks.iterdir())}


def test_a_worker_that_stalls_inside_a_test_is_dumped_by_name_and_the_controller_shows_its_wait(
    cs: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = {
        "suite/test_stalls.py": "import time\n\n\n" + BLOCKER + "def test_stalls_then_returns():\n    _bf985_blocks_here(5)\n",
        "suite/test_quick.py": "def test_quick():\n    pass\n",
    }
    tree = make_tree(tmp_path / "tree", files, durations=NO_DURATIONS)
    evidence = tmp_path / "evidence"
    stacks = tmp_path / "stacks"

    result = run_pytest(
        tree, "suite", "-q", "-n", "2", "--dist=loadfile", *shard_options(1, 1, evidence),
        f"--probos-shard-stack-dir={stacks}", "--probos-shard-stall-seconds=1",
    )  # fmt: skip

    texts = stack_texts(stacks)
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b2 passed\b", result.stdout)
    assert sorted(texts) == ["faulthandler-controller.txt", "faulthandler-gw0.txt", "faulthandler-gw1.txt"]
    stalled = [name for name in ("faulthandler-gw0.txt", "faulthandler-gw1.txt") if "_bf985_blocks_here" in texts[name]]
    assert len(stalled) == 1, texts
    assert "Timeout (0:00:01" in texts[stalled[0]] and "test_stalls_then_returns" in texts[stalled[0]]
    # The controller waits in xdist's event loop while the worker blocks.
    assert "dsession.py" in texts["faulthandler-controller.txt"]
    assert "_bf985_blocks_here" not in texts["faulthandler-controller.txt"]
    assert sorted(path.name for path in evidence.iterdir()) == ["shard-1"]
    assert verify(cs, evidence, 1, tree / "durations.json") == 0, capsys.readouterr().out


def test_a_failing_test_leaves_the_watchdog_armed_for_the_silence_after_it(tmp_path: Path) -> None:
    """pytest's faulthandler plugin cancels the process's one timer in pytest_exception_interact."""
    files = {
        "suite/test_fails.py": (
            "import time\n\nimport pytest\n\n\n" + BLOCKER
            + "@pytest.fixture\ndef slow_teardown():\n    yield\n    _bf985_blocks_here(4)\n\n\n"
            "def test_fails_then_tears_down_slowly(slow_teardown):\n    assert False\n"
        ),
    }
    tree = make_tree(tmp_path / "tree", files, durations=NO_DURATIONS)
    stacks = tmp_path / "stacks"

    result = run_pytest(
        tree, "suite", "-q", "-n", "0", *shard_options(1, 1, tmp_path / "evidence"),
        f"--probos-shard-stack-dir={stacks}", "--probos-shard-stall-seconds=1",
    )  # fmt: skip

    text = stack_texts(stacks)["faulthandler-controller.txt"]
    assert result.returncode == 1, result.stdout + result.stderr
    assert re.search(r"\b1 failed\b", result.stdout)
    assert "_bf985_blocks_here" in text and "slow_teardown" in text


def test_a_process_held_open_at_exit_by_a_leftover_thread_is_dumped_during_shutdown(tmp_path: Path) -> None:
    """The #1419 shape: interpreter shutdown joins a non-daemon thread after every pytest hook ran."""
    files = {
        "suite/test_leaves_a_thread.py": (
            "import threading\nimport time\n\n\n" + BLOCKER
            + "def test_leaves_a_non_daemon_thread_behind():\n"
            "    threading.Thread(target=_bf985_blocks_here, args=(4,), daemon=False).start()\n"
        ),
    }
    tree = make_tree(tmp_path / "tree", files, durations=NO_DURATIONS)
    stacks = tmp_path / "stacks"

    result = run_pytest(
        tree, "suite", "-q", "-n", "0", *shard_options(1, 1, tmp_path / "evidence"),
        f"--probos-shard-stack-dir={stacks}", "--probos-shard-stall-seconds=1",
    )  # fmt: skip

    text = stack_texts(stacks)["faulthandler-controller.txt"]
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b1 passed\b", result.stdout)
    assert "_bf985_blocks_here" in text
    assert "_shutdown" in text  # the main thread is in threading._shutdown, after pytest returned


# --- the plugin's hooks, driven in-process for every branch --------------------------
```

**T7.** Helpers for the in-process watchdog cases.
SEARCH:
```
def written(root: Path, name: str = "ev/shard-2/main.json") -> dict[str, Any]:
    return json.loads((root / name).read_text(encoding="utf-8"))


def test_plugin_module_is_marked_unrewritten_and_never_imports_the_gate_plugin() -> None:
```
REPLACE:
```
def written(root: Path, name: str = "ev/shard-2/main.json") -> dict[str, Any]:
    return json.loads((root / name).read_text(encoding="utf-8"))


class WatchdogConfig(FakeConfig):
    """A FakeConfig with ``getini`` (a missing key raises as pytest does) and an optional ``workerinput``."""

    def __init__(
        self, rootpath: Path, *, ini: dict[str, Any], workerinput: dict[str, Any] | None, **options: Any
    ) -> None:
        super().__init__(rootpath, **options)
        self.ini = ini
        if workerinput is not None:
            self.workerinput = workerinput

    def getini(self, name: str) -> Any:
        if name not in self.ini:
            raise ValueError(f"unknown configuration value: {name!r}")
        return self.ini[name]


def watchdog_configured(
    plugin: ModuleType,
    root: Path,
    *,
    ini: dict[str, Any] | None = None,
    workerinput: dict[str, Any] | None = None,
    **options: Any,
) -> tuple[WatchdogConfig, dict[str, Any]]:
    (root / "durations.json").write_text(json.dumps(DURATIONS), encoding="utf-8")
    values = {
        "probos_shard_index": 2,
        "probos_shard_count": 2,
        "probos_shard_evidence_dir": "ev",
        "probos_shard_durations": "durations.json",
        "probos_shard_stack_dir": "stacks",
        **options,
    }
    config = WatchdogConfig(
        root, ini={"faulthandler_timeout": "0"} if ini is None else ini, workerinput=workerinput, **values
    )
    plugin.pytest_configure(config)
    return config, dict(config.registered)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_plugin_module_is_marked_unrewritten_and_never_imports_the_gate_plugin() -> None:
```

**T8.** U1: six options.
SEARCH:
```
def test_addoption_registers_the_four_options_with_no_defaults(plugin: ModuleType) -> None:
    added: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    group = SimpleNamespace(addoption=lambda *names, **kwargs: added.append((names, kwargs)))
    parser = SimpleNamespace(getgroup=lambda *args: group)

    plugin.pytest_addoption(parser)

    assert [names for names, _ in added] == [
        ("--probos-shard-index",),
        ("--probos-shard-count",),
        ("--probos-shard-evidence-dir",),
        ("--probos-shard-durations",),
    ]
    assert all(kwargs["default"] is None for _, kwargs in added)
    assert [kwargs.get("type") for _, kwargs in added] == [int, int, None, None]
```
REPLACE:
```
def test_addoption_registers_the_six_options_with_no_defaults(plugin: ModuleType) -> None:
    added: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    group = SimpleNamespace(addoption=lambda *names, **kwargs: added.append((names, kwargs)))
    parser = SimpleNamespace(getgroup=lambda *args: group)

    plugin.pytest_addoption(parser)

    assert [names for names, _ in added] == [
        ("--probos-shard-index",),
        ("--probos-shard-count",),
        ("--probos-shard-evidence-dir",),
        ("--probos-shard-durations",),
        ("--probos-shard-stack-dir",),
        ("--probos-shard-stall-seconds",),
    ]
    assert all(kwargs["default"] is None for _, kwargs in added)
    assert [kwargs.get("type") for _, kwargs in added] == [int, int, None, None, None, int]
```

**T9.** U2: the stack options alone leave the plugin inert.
SEARCH:
```
def test_configure_is_inert_without_any_of_the_three_shard_options(plugin: ModuleType, tmp_path: Path) -> None:
    for options in ({}, {"probos_shard_durations": "ignored.json"}):
        config = FakeConfig(tmp_path, **options)

        plugin.pytest_configure(config)

        assert config.registered == []
```
REPLACE:
```
def test_configure_is_inert_without_any_of_the_three_shard_options(plugin: ModuleType, tmp_path: Path) -> None:
    for options in (
        {},
        {"probos_shard_durations": "ignored.json"},
        {"probos_shard_stack_dir": "stacks", "probos_shard_stall_seconds": 5},
    ):
        config = FakeConfig(tmp_path, **options)

        plugin.pytest_configure(config)

        assert config.registered == []
    assert not (tmp_path / "stacks").exists()
```

**T10.** U3: three new parameters (all refused before `getini`, so `FakeConfig` suffices).
SEARCH:
```
        ({"probos_shard_evidence_dir": "  "}, "must not be empty"),
        ({"probos_shard_durations": "absent.json"}, "durations file absent.json: unreadable"),
    ],
)
```
REPLACE:
```
        ({"probos_shard_evidence_dir": "  "}, "must not be empty"),
        ({"probos_shard_durations": "absent.json"}, "durations file absent.json: unreadable"),
        ({"probos_shard_stall_seconds": 5}, "--probos-shard-stall-seconds needs --probos-shard-stack-dir"),
        ({"probos_shard_stack_dir": "  "}, "--probos-shard-stack-dir must not be empty"),
        (
            {"probos_shard_stack_dir": "stacks", "probos_shard_stall_seconds": 0},
            r"--probos-shard-stall-seconds must be >= 1, got 0",
        ),
    ],
)
```

**T11.** U4 to U9 at the end of the file.
SEARCH:
```
def test_recorder_lets_an_unwritable_evidence_directory_fail_loudly(plugin: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "ev").write_text("a file where the evidence directory belongs", encoding="utf-8")
    config, recorder = configured(plugin, tmp_path)
    collect(recorder, config, ALL_NODES)

    with pytest.raises(OSError):
        recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), 0)
```
REPLACE:
```
def test_recorder_lets_an_unwritable_evidence_directory_fail_loudly(plugin: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "ev").write_text("a file where the evidence directory belongs", encoding="utf-8")
    config, recorder = configured(plugin, tmp_path)
    collect(recorder, config, ALL_NODES)

    with pytest.raises(OSError):
        recorder.pytest_sessionfinish(SimpleNamespace(config=SimpleNamespace()), 0)


# --- BF-985: the stall watchdog's configuration and hooks -----------------------------


@pytest.mark.parametrize("value", ["5", 5.0])
def test_configure_refuses_a_stack_dir_beside_pytests_faulthandler_timeout(
    plugin: ModuleType, tmp_path: Path, value: Any
) -> None:
    with pytest.raises(pytest.UsageError, match="cannot run with faulthandler_timeout > 0"):
        watchdog_configured(plugin, tmp_path, ini={"faulthandler_timeout": value})

    assert not (tmp_path / "stacks").exists()


@pytest.mark.parametrize(
    "ini", [{"faulthandler_timeout": "0"}, {}], ids=["timeout zero", "pytest faulthandler plugin off"]
)
def test_configure_accepts_a_stack_dir_when_nothing_else_drives_the_timer(
    plugin: ModuleType, tmp_path: Path, ini: dict[str, Any]
) -> None:
    _, registered = watchdog_configured(plugin, tmp_path, ini=ini, probos_shard_stall_seconds=7)
    watchdog = registered["probos-ci-stall-watchdog"]
    watchdog.stream.close()

    assert list(registered) == ["probos-ci-shard-recorder", "probos-ci-stall-watchdog"]
    assert watchdog.stall_seconds == 7


@pytest.mark.parametrize(
    ("workerinput", "name"),
    [
        (None, "faulthandler-controller.txt"),
        ({"workerid": "gw3", "workercount": 4, "testrunuid": "u"}, "faulthandler-gw3.txt"),
    ],
)
def test_configure_opens_this_processs_stack_file_and_arms_only_when_the_session_starts(
    plugin: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workerinput: dict[str, Any] | None,
    name: str,
) -> None:
    calls: list[tuple[int, dict[str, Any]]] = []
    monkeypatch.setattr(plugin.faulthandler, "dump_traceback_later", lambda seconds, **kw: calls.append((seconds, kw)))

    _, registered = watchdog_configured(plugin, tmp_path, workerinput=workerinput)
    watchdog = registered["probos-ci-stall-watchdog"]
    try:
        assert Path(watchdog.stream.name) == tmp_path / "stacks" / name
        assert sorted(path.name for path in (tmp_path / "stacks").iterdir()) == [name]
        assert watchdog.stall_seconds == 600 and calls == []

        watchdog.pytest_sessionstart()

        assert calls == [(600, {"repeat": True, "file": watchdog.stream})]
    finally:
        watchdog.stream.close()
    assert (tmp_path / "stacks" / name).read_text(encoding="utf-8") == ""


def test_configure_refuses_a_worker_id_it_cannot_name_a_stack_file_after(plugin: ModuleType, tmp_path: Path) -> None:
    worker = {"workerid": "../gw0", "workercount": 2, "testrunuid": "u"}

    with pytest.raises(pytest.UsageError, match="cannot name a stack file"):
        watchdog_configured(plugin, tmp_path, workerinput=worker)

    assert not (tmp_path / "stacks").exists()


def test_watchdog_rearms_on_test_events_at_most_once_per_twentieth_of_the_bound(
    plugin: ModuleType, tmp_path: Path
) -> None:
    calls: list[tuple[int, dict[str, Any]]] = []
    clock = FakeClock()
    with (tmp_path / "s.txt").open("w", encoding="utf-8") as stream:
        fresh = plugin.StallWatchdog(stream=stream, stall_seconds=600, arm=lambda s, **kw: calls.append((s, kw)), clock=clock)
        fresh.pytest_runtest_logreport()  # never armed: the first event arms
        assert len(calls) == 1
        calls.clear()
        watchdog = plugin.StallWatchdog(
            stream=stream, stall_seconds=600, arm=lambda s, **kw: calls.append((s, kw)), clock=clock
        )
        watchdog.pytest_sessionstart()
        armed = []
        for now, hook in [
            (10.0, watchdog.pytest_runtest_logstart),
            (29.9, watchdog.pytest_runtest_logreport),
            (30.0, watchdog.pytest_runtest_logreport),
            (59.9, watchdog.pytest_runtest_logstart),
            (60.0, watchdog.pytest_runtest_logstart),
        ]:
            clock.now = now
            before = len(calls)
            hook()
            armed.append(len(calls) > before)

    assert armed == [False, False, True, False, True]
    assert calls == [(600, {"repeat": True, "file": stream})] * 3


def test_watchdog_rearms_inside_the_gap_where_pytest_cancels_the_timer_and_as_the_session_ends(
    plugin: ModuleType, tmp_path: Path
) -> None:
    calls: list[float] = []
    clock = FakeClock()
    with (tmp_path / "s.txt").open("w", encoding="utf-8") as stream:
        watchdog = plugin.StallWatchdog(
            stream=stream, stall_seconds=600, arm=lambda s, **kw: calls.append(clock.now), clock=clock
        )
        watchdog.pytest_sessionstart()
        for now, hook in [
            (1.0, watchdog.pytest_exception_interact),
            (2.0, watchdog.pytest_sessionfinish),
            (3.0, watchdog.pytest_unconfigure),
            (3.5, watchdog.pytest_runtest_logreport),
        ]:
            clock.now = now
            hook()

    assert calls == [0.0, 1.0, 2.0, 3.0]
```

**P1.** `scripts/_ci_shard_pytest_plugin.py`, the docstring's options paragraph.
SEARCH:
```
    --probos-shard-index K --probos-shard-count N --probos-shard-evidence-dir DIR

plus, optionally, ``--probos-shard-durations PATH``. Relative paths resolve against
pytest's rootpath. With none of the first three options the plugin is inert. A partial
set, an index outside 1..N or an unusable durations file raises ``pytest.UsageError``
from ``pytest_configure``, before xdist starts any worker. Pytest's rootdir detection
```
REPLACE:
```
    --probos-shard-index K --probos-shard-count N --probos-shard-evidence-dir DIR

plus, optionally, ``--probos-shard-durations PATH``, ``--probos-shard-stack-dir DIR`` and
``--probos-shard-stall-seconds S`` (BF-985, below). Relative paths resolve against
pytest's rootpath. With none of the first three options the plugin is inert. A partial
set, an index outside 1..N, an unusable durations file, a stall bound without a stack
directory or below 1, or a stack directory beside pytest's ``faulthandler_timeout``
raises ``pytest.UsageError`` from ``pytest_configure``, before xdist starts any worker.
Pytest's rootdir detection
```

**P2.** The docstring's last paragraph.
SEARCH:
```
kept. ``scripts/ci_shards.py verify`` turns those into the exactly-once proof. The plugin
changes no markers, scheduling, timeouts or outcomes. The xdist controller never collects,
so it never writes.
"""
```
REPLACE:
```
kept. ``scripts/ci_shards.py verify`` turns those into the exactly-once proof. The plugin
changes no markers, scheduling, timeouts or outcomes. The xdist controller never collects,
so it never writes.

BF-985: with ``--probos-shard-stack-dir DIR`` every pytest process (the xdist controller,
or the only process under ``-n 0``, and each worker) opens
``DIR/faulthandler-<controller|gwN>.txt`` for its whole life and arms
``faulthandler.dump_traceback_later(S, repeat=True)`` on it at session start
(S = ``--probos-shard-stall-seconds``, default 600). Each test event the process sees
re-arms the timer (at most once per S/20 seconds), so the file stays empty unless the
process saw no event for about S seconds; then every thread's stack is written, and again
every S seconds while the silence lasts. The timer is re-armed after pytest's faulthandler
plugin cancels it on a failing phase, and re-armed, never cancelled, at session finish and
unconfigure, so a process that hangs in interpreter shutdown is dumped too; ``Py_Finalize``
cancels it on a normal exit. The dumps live outside the evidence directory, which
``verify`` requires to hold evidence files only. The watchdog only writes: it changes no
outcome.
"""
```

**P3.** Imports and constants.
SEARCH:
```
import uuid
from collections import Counter
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from scripts import ci_shards

_RECORDER_NAME = "probos-ci-shard-recorder"
_PREVIEW_LIMIT = 5
```
REPLACE:
```
import faulthandler
import re
import time
import uuid
from collections import Counter
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, TextIO

import pytest

from scripts import ci_shards

_RECORDER_NAME = "probos-ci-shard-recorder"
_WATCHDOG_NAME = "probos-ci-stall-watchdog"
_PREVIEW_LIMIT = 5
DEFAULT_STALL_SECONDS = 600
# Each dump_traceback_later call joins the old watchdog thread and starts a new one, so a test
# event re-arms at most once per this fraction of the bound.
_REARM_FRACTION = 20
_STACK_WORKER_ID = re.compile(r"gw[0-9]{1,6}")
```

**P4.** Two options.
SEARCH:
```
        help=f"durations JSON for the split (default: {ci_shards.DEFAULT_DURATIONS_PATH})",
    )


class ShardRecorder:
```
REPLACE:
```
        help=f"durations JSON for the split (default: {ci_shards.DEFAULT_DURATIONS_PATH})",
    )
    group.addoption(
        "--probos-shard-stack-dir",
        dest="probos_shard_stack_dir",
        default=None,
        metavar="DIR",
        help="arm a stall watchdog that writes every thread's stack to DIR/faulthandler-<process>.txt",
    )
    group.addoption(
        "--probos-shard-stall-seconds",
        dest="probos_shard_stall_seconds",
        type=int,
        default=None,
        metavar="S",
        help=f"seconds without a test event before a stack dump (default: {DEFAULT_STALL_SECONDS})",
    )


class ShardRecorder:
```

**P5.** `StallWatchdog` and its two helpers, before `pytest_configure`.
SEARCH:
```
        ci_shards.write_evidence(self._evidence_dir, payload)


def pytest_configure(config: pytest.Config) -> None:
```
REPLACE:
```
        ci_shards.write_evidence(self._evidence_dir, payload)


class StallWatchdog:
    """BF-985: writes every thread's stack to this process's file after a silence of the bound.

    One ``faulthandler`` dump timer exists per process, and ``dump_traceback_later`` replaces it.
    pytest's own faulthandler plugin cancels that timer in ``pytest_exception_interact``, so this
    re-arms after that hook; ``pytest_configure`` refuses ``faulthandler_timeout`` > 0 beside it,
    because pytest then arms and cancels the same timer around every test.
    """

    def __init__(
        self,
        *,
        stream: TextIO,
        stall_seconds: int,
        arm: Callable[..., None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stream = stream
        self._stall_seconds = stall_seconds
        self._rearm_gap = stall_seconds / _REARM_FRACTION
        self._arm_timer = faulthandler.dump_traceback_later if arm is None else arm
        self._clock = clock
        self._armed_at: float | None = None

    @property
    def stream(self) -> TextIO:
        """The file the dumps go to; it stays open for the life of the process."""
        return self._stream

    @property
    def stall_seconds(self) -> int:
        return self._stall_seconds

    def arm(self) -> None:
        """Restart the timer: a dump after ``stall_seconds`` unless re-armed, then every ``stall_seconds``."""
        self._arm_timer(self._stall_seconds, repeat=True, file=self._stream)
        self._armed_at = self._clock()

    def _rearm_on_event(self) -> None:
        if self._armed_at is None or self._clock() - self._armed_at >= self._rearm_gap:
            self.arm()

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionstart(self) -> None:
        self.arm()

    def pytest_runtest_logstart(self) -> None:
        self._rearm_on_event()

    def pytest_runtest_logreport(self) -> None:
        self._rearm_on_event()

    @pytest.hookimpl(trylast=True)
    def pytest_exception_interact(self) -> None:
        # pytest's faulthandler plugin (tryfirst) has just cancelled this process's one timer.
        self.arm()

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionfinish(self) -> None:
        # Re-armed, never cancelled: a process can still hang after this, in another plugin's
        # session finish, in unconfigure or in interpreter shutdown.
        self.arm()

    @pytest.hookimpl(trylast=True)
    def pytest_unconfigure(self) -> None:
        # The last arm covers threading._shutdown joining a leftover non-daemon thread;
        # Py_Finalize cancels the timer when the process exits normally.
        self.arm()


def _stack_file(config: pytest.Config) -> Path | None:
    """Check the BF-985 options; return this process's stack file, or None without a stack directory."""
    stack_dir = config.getoption("probos_shard_stack_dir")
    stall = config.getoption("probos_shard_stall_seconds")
    if stack_dir is None:
        if stall is not None:
            raise pytest.UsageError("--probos-shard-stall-seconds needs --probos-shard-stack-dir")
        return None
    if not stack_dir.strip():
        raise pytest.UsageError("--probos-shard-stack-dir must not be empty")
    if stall is not None and stall < 1:
        raise pytest.UsageError(f"--probos-shard-stall-seconds must be >= 1, got {stall}")
    try:
        pytest_timeout = config.getini("faulthandler_timeout")
    except ValueError:  # pytest's faulthandler plugin is off (-p no:faulthandler): nothing else drives the timer
        pytest_timeout = 0.0
    if float(pytest_timeout or 0.0) > 0:
        raise pytest.UsageError(
            "--probos-shard-stack-dir cannot run with faulthandler_timeout > 0: pytest's faulthandler "
            "plugin arms and cancels the same per-process dump timer around every test"
        )
    worker_input = getattr(config, "workerinput", None)
    name = "controller"
    if isinstance(worker_input, dict):
        name = str(worker_input["workerid"])
        if _STACK_WORKER_ID.fullmatch(name) is None:
            raise pytest.UsageError(f"CI shard plugin cannot name a stack file after worker id {name!r}")
    return _resolve(config.rootpath, stack_dir) / f"faulthandler-{name}.txt"


def _open_stack_file(path: Path) -> TextIO:
    """Create the stack directory and open this process's file for the rest of its life."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # faulthandler writes to this file's descriptor from its own C thread, without the GIL, and
    # holds a reference to it; nothing closes it, so a dump during shutdown still lands.
    return path.open("w", encoding="utf-8")


def pytest_configure(config: pytest.Config) -> None:
```

**P6.** The wiring at the end of `pytest_configure`.
SEARCH:
```
        raise pytest.UsageError(f"CI shard plugin: {exc}") from exc
    recorder = ShardRecorder(
        index=index,
        count=count,
        evidence_dir=_resolve(config.rootpath, evidence_dir),
        durations_label=_durations_label(config.rootpath, durations_path),
        durations=durations,
    )
    config.pluginmanager.register(recorder, _RECORDER_NAME)
```
REPLACE:
```
        raise pytest.UsageError(f"CI shard plugin: {exc}") from exc
    stack_file = _stack_file(config)
    stream = None if stack_file is None else _open_stack_file(stack_file)
    recorder = ShardRecorder(
        index=index,
        count=count,
        evidence_dir=_resolve(config.rootpath, evidence_dir),
        durations_label=_durations_label(config.rootpath, durations_path),
        durations=durations,
    )
    config.pluginmanager.register(recorder, _RECORDER_NAME)
    if stream is not None:
        stall = config.getoption("probos_shard_stall_seconds")
        watchdog = StallWatchdog(
            stream=stream,
            stall_seconds=DEFAULT_STALL_SECONDS if stall is None else stall,
        )
        config.pluginmanager.register(watchdog, _WATCHDOG_NAME)
```

### 7.2 M2: pins (`tests/test_ci_shards.py`), then `.github/workflows/ci.yml`

**W0.** The import.
SEARCH:
```
import hashlib
import importlib.util
import json
import os
```
REPLACE:
```
import fnmatch
import hashlib
import importlib.util
import json
import os
```

**W0b.** A step lookup by name.
SEARCH:
```
def _step_using(job: dict[str, Any], action: str) -> dict[str, Any]:
    steps = [step for step in job["steps"] if str(step.get("uses", "")).startswith(action + "@")]
    assert len(steps) == 1, steps
    return steps[0]
```
REPLACE:
```
def _step_using(job: dict[str, Any], action: str) -> dict[str, Any]:
    steps = [step for step in job["steps"] if str(step.get("uses", "")).startswith(action + "@")]
    assert len(steps) == 1, steps
    return steps[0]


def _step_named(job: dict[str, Any], name: str) -> dict[str, Any]:
    steps = [step for step in job["steps"] if step.get("name") == name]
    assert len(steps) == 1, steps
    return steps[0]
```

**W1.** The step limit.
SEARCH:
```
    assert _step_using(shard, "astral-sh/setup-uv")["uses"] == "astral-sh/setup-uv@v5"
    assert _run_of(shard, "uv sync") == "uv sync --group dev --extra discovery --extra browser"
```
REPLACE:
```
    assert _step_using(shard, "astral-sh/setup-uv")["uses"] == "astral-sh/setup-uv@v5"
    assert _run_of(shard, "uv sync") == "uv sync --group dev --extra discovery --extra browser"
    # BF-985: a step that reaches its own limit fails instead of cancelling the job, so the uploads still run.
    assert _step_named(shard, "Run tests")["timeout-minutes"] == 38
    assert _step_named(shard, "Run tests")["timeout-minutes"] < shard["timeout-minutes"]
```

**W2.** The command carries the stack directory and the default bound.
SEARCH:
```
    assert _option(args, "--probos-shard-evidence-dir") == ["<runner.temp>/ci-shard-evidence"]
    assert not [token for token in args if token.startswith("--probos-shard-durations")]
```
REPLACE:
```
    assert _option(args, "--probos-shard-evidence-dir") == ["<runner.temp>/ci-shard-evidence"]
    assert not [token for token in args if token.startswith("--probos-shard-durations")]
    assert _option(args, "--probos-shard-stack-dir") == ["<runner.temp>/ci-shard-stacks"]
    assert not [token for token in args if token.startswith("--probos-shard-stall-seconds")]
```

**W3 and W4.** The evidence upload, selected by name, and the new stacks upload.
SEARCH:
```
def test_shard_job_uploads_its_evidence_whatever_the_outcome() -> None:
    shard = _workflow()["jobs"][SHARD_JOB]
    upload = _step_using(shard, "actions/upload-artifact")
    major = int(upload["uses"].split("@v")[1].split(".")[0])

    assert major >= 4
```
REPLACE:
```
def test_shard_job_uploads_its_evidence_whatever_the_outcome() -> None:
    shard = _workflow()["jobs"][SHARD_JOB]
    uploads = [step for step in shard["steps"] if str(step.get("uses", "")).startswith("actions/upload-artifact@")]
    upload = _step_named(shard, "Upload shard evidence")
    major = int(upload["uses"].split("@v")[1].split(".")[0])

    # BF-985: the stall dumps have their own upload, before this one; the evidence upload stays last.
    assert [step["name"] for step in uploads] == ["Upload stall stack dumps", "Upload shard evidence"]
    assert major >= 4
```

**W4.** A new test after W3's function (it follows the unchanged `with` dictionary).
SEARCH:
```
        "if-no-files-found": "error",
        "overwrite": True,
        "retention-days": 7,
    }


def test_summary_job_keeps_the_check_name_and_cannot_pass_on_a_skipped_shard() -> None:
```
REPLACE:
```
        "if-no-files-found": "error",
        "overwrite": True,
        "retention-days": 7,
    }


def test_shard_job_uploads_the_stack_dumps_of_a_failed_or_cancelled_shard_apart_from_the_evidence() -> None:
    jobs = _workflow()["jobs"]
    shard = jobs[SHARD_JOB]
    steps = shard["steps"]
    run = _step_named(shard, "Run tests")
    stacks = _step_named(shard, "Upload stall stack dumps")
    evidence = _step_named(shard, "Upload shard evidence")
    pattern = _step_using(jobs[SUMMARY_JOB], "actions/download-artifact")["with"]["pattern"]
    stack_dir = _tokens(stacks["with"]["path"])[0]
    evidence_dir = _tokens(evidence["with"]["path"])[0]

    assert stacks["uses"] == evidence["uses"]
    assert steps.index(run) < steps.index(stacks) < steps.index(evidence)
    assert stacks["if"] == "${{ failure() || cancelled() }}"
    assert stacks["with"] == {
        "name": "ci-shard-stacks-${{ matrix.shard }}",
        "path": "${{ runner.temp }}/ci-shard-stacks",
        "if-no-files-found": "ignore",
        "overwrite": True,
        "retention-days": 7,
    }
    # verify rejects any entry in the evidence root but shard-K/<worker>.json: the dumps must never land there.
    for index in shard["strategy"]["matrix"]["shard"]:
        assert not fnmatch.fnmatchcase(stacks["with"]["name"].replace("${{ matrix.shard }}", str(index)), pattern)
    assert stack_dir != evidence_dir and not stack_dir.startswith(evidence_dir + "/")
    assert _option(_shard_pytest_tokens(), "--probos-shard-stack-dir") == [stack_dir]


def test_summary_job_keeps_the_check_name_and_cannot_pass_on_a_skipped_shard() -> None:
```

**W5.** The rationale sits beside the step limit.
SEARCH:
```
    assert "BF-322" in step_comments and "BF-657" in step_comments and "-n auto" in step_comments
    assert "--maxfail=10" in step_comments and "missing node" in step_comments
```
REPLACE:
```
    assert "BF-322" in step_comments and "BF-657" in step_comments and "-n auto" in step_comments
    assert "--maxfail=10" in step_comments and "missing node" in step_comments
    assert "BF-985" in step_comments and "timeout-minutes: 38" in step_comments
```

**Y1.** `.github/workflows/ci.yml`.
SEARCH:
```
        # AD-1270f P2.7: each shard keeps --maxfail=10 as its own budget. A shard that
        # stops early is red and leaves nodes unexecuted, which `python-tests` rejects
        # separately, so --maxfail can never give a green `python-tests` with a missing node.
        run: >-
          uv run python -m pytest tests/ -n auto --maxfail=10 -q --tb=short
          -p scripts._ci_shard_pytest_plugin
          --probos-shard-index ${{ matrix.shard }}
          --probos-shard-count 3
          --probos-shard-evidence-dir "${{ runner.temp }}/ci-shard-evidence"

      - name: Upload shard evidence
```
REPLACE:
```
        # AD-1270f P2.7: each shard keeps --maxfail=10 as its own budget. A shard that
        # stops early is red and leaves nodes unexecuted, which `python-tests` rejects
        # separately, so --maxfail can never give a green `python-tests` with a missing node.
        # BF-985: shards have stalled after `[ 99%]` until the job limit cancelled them, and a
        # cancelled job runs no later step. This step limit ends a stall as a FAILED step (a
        # healthy shard reaches `[ 99%]` in about 13-14 minutes), so both uploads below run.
        # --probos-shard-stack-dir makes the controller and every worker write all their stacks
        # to ci-shard-stacks after 600 s without a test event (scripts/_ci_shard_pytest_plugin.py).
        timeout-minutes: 38
        run: >-
          uv run python -m pytest tests/ -n auto --maxfail=10 -q --tb=short
          -p scripts._ci_shard_pytest_plugin
          --probos-shard-index ${{ matrix.shard }}
          --probos-shard-count 3
          --probos-shard-evidence-dir "${{ runner.temp }}/ci-shard-evidence"
          --probos-shard-stack-dir "${{ runner.temp }}/ci-shard-stacks"

      # BF-985: the stall dumps are their own artifact. `verify` rejects any entry in the
      # evidence root but shard-K/<worker>.json, and `python-tests` downloads every
      # ci-shard-evidence-* artifact into that root, so this name must not match that pattern.
      - name: Upload stall stack dumps
        if: ${{ failure() || cancelled() }}
        uses: actions/upload-artifact@v7
        with:
          name: ci-shard-stacks-${{ matrix.shard }}
          path: ${{ runner.temp }}/ci-shard-stacks
          if-no-files-found: ignore
          overwrite: true
          retention-days: 7

      - name: Upload shard evidence
```

### 7.3 M3: doc row, trackers, ledger

**D1.** `docs/development/test-suite-optimization-plan.md`, the P2.7 row (`:268`). The SEARCH is a substring of that one line.
SEARCH:
```
<br>CI evidence is not release authority; the canonical gate is unchanged. | About 36
```
REPLACE:
```
<br>• BF-985: `Run tests` has a 38-minute step limit, below the job's 45, so a shard that stalls ends as a failed step and the later steps still run. `--probos-shard-stack-dir` arms a `faulthandler` stall watchdog in the controller and every worker (a dump of every thread after 600 s without a test event, then every 600 s, re-armed through interpreter shutdown), each into `faulthandler-<controller|gwN>.txt`. A failed or cancelled shard uploads them as `ci-shard-stacks-K`, apart from the evidence `verify` reads; read one with `gh run download <run-id> -n ci-shard-stacks-<K>`.<br>CI evidence is not release authority; the canonical gate is unchanged. | About 36
```

**K1.** `PROGRESS.md`. The SEARCH is the title line alone, so that it still matches after B4 adds an entry. Replace `DATE` with M3's date and `N` with the PR number.
SEARCH:
```
# ProbOS Progress
```
REPLACE:
```
# ProbOS Progress

**BF-985 (DATE), #1820 -- a CI shard that stalls now writes the stacks of its controller and every worker, and a step limit lets them upload.**
- **Base.** Three CI shards stopped at `[ 99%]` until the 45-minute job limit cancelled them (bf-983 F2 in #1820; #1452 item 8). A cancelled job runs no later step, and nothing recorded where the five live processes were.
- **Fix.** `--probos-shard-stack-dir` makes the CI shard plugin open `faulthandler-<controller|gwN>.txt` in every pytest process and arm a `faulthandler` dump of every thread after 600 s without a test event. The dump is re-armed after pytest's own faulthandler plugin cancels it on a failing phase, and through interpreter shutdown. `Run tests` gets a 38-minute step limit, so a stall fails the step and both `ci-shard-stacks-K` and the shard evidence upload. A normal run leaves empty files, and the evidence, `verify` and the `python-tests` job are unchanged. 19 new cases across `tests/test_ci_shard_pytest_plugin.py` (three controlled doubles: a stall inside a test under `-n 2`, the silence after a failing test, and a leftover non-daemon thread at exit) and `tests/test_ci_shards.py`. Contract `prompts/bf-985-ci-stall-stack-dumps.md`.
- **Limits.** The cause of the stall is still unknown: the next stall's artifact names it (`gh run download <run-id> -n ci-shard-stacks-<K>`). Python frames only; a stall that starts after minute 28 of the step gets no dump before the limit; a forked child of a pytest process that finalises would block (nothing forks). L1 to L8 of the contract.
```

**K2.** `DECISIONS.md`. The entry goes straight after BF-983's, whose reversal line is unique.
SEARCH:
```
- *Reversal.* Revert the commits: the consultation raises `TypeError` again, the golden's lines and message go, and the reference returns to leaf headings without the three sections.
```
REPLACE:
```
- *Reversal.* Revert the commits: the consultation raises `TypeError` again, the golden's lines and message go, and the reference returns to leaf headings without the three sections.

### BF-985 -- A CI shard that stalls writes the stacks of its controller and workers, and a step limit lets them upload (DATE, #1820)

- *Scope.* `scripts/_ci_shard_pytest_plugin.py` (two options, `StallWatchdog`, its wiring in `pytest_configure`), `.github/workflows/ci.yml` (a 38-minute limit on `Run tests`, `--probos-shard-stack-dir`, the `Upload stall stack dumps` step), the pins in `tests/test_ci_shards.py` and `tests/test_ci_shard_pytest_plugin.py`, and the P2.7 row. `scripts/ci_shards.py` and the `python-tests` job are unchanged. From bf-983 F2 (#1820); #1452 item 8 proposed the watchdog. Contract `prompts/bf-985-ci-stall-stack-dumps.md`.
- *D1 (where the dumps go).* One file per pytest process, `faulthandler-<controller|gwN>.txt`, kept for the process's life. They go in their own directory and artifact (`ci-shard-stacks-K`), uploaded on `failure() || cancelled()` before the evidence upload; a normal run leaves them empty. Rejected: the evidence directory (`verify` rejects any entry but `shard-K/<worker>.json`, so every run would fail) and a verifier exception for them (it widens the exactly-once proof's input for a diagnostic).
- *D2 (the watchdog).* `faulthandler.dump_traceback_later(600, repeat=True)`. It is armed at session start and re-armed:
  - by every test event the process sees, at most once per 30 s;
  - unconditionally after `pytest_exception_interact`, where pytest's faulthandler plugin cancels the one per-process timer;
  - at session finish and unconfigure.

  It is never cancelled, so a process held at exit by a leftover non-daemon thread is dumped. `faulthandler_timeout` > 0 is refused beside it. Rejected: cancelling at session finish (it blinds the end-of-run window the three stalls point to); pytest's `faulthandler_timeout` (inside one test only, and it shares the timer); a Python watchdog thread (it needs the GIL).
- *D3 (ending the stall).* `timeout-minutes: 38` on `Run tests`: the step fails and the job is not cancelled, so both uploads run (`actions/runner` `StepsRunner.cs`). The evidence upload keeps `!cancelled()`, and `python-tests` fails at `Require every shard to succeed` as for any red shard. Rejected: `always()` on the evidence upload (nothing reads a cancelled job's evidence), a longer job limit, an automatic retry.
- *Residual.* The stall's cause stays unknown until the first stall's `ci-shard-stacks-K` is read. L1 to L8 of the contract. *Reversal.* Revert the commits; only seven-day artifacts remain.
```

**Ledger.** Run G3. Neither heading contains a word `gen_ad_ledger.py` reads as a status (`scripts/gen_ad_ledger.py:126-132`: retired, abandoned, withdrawn, superseded, deferred, postponed, closed, shipped, staged, landed, open). Do not edit the roadmap Bug Tracker: it lags at BF-927, and BF-980 and BF-983 did not edit it either.

## 8. Tests

**New cases, in `tests/test_ci_shard_pytest_plugin.py` unless marked.**

| Id | Case | Proves | On the base |
|---|---|---|---|
| I1 | `test_a_worker_that_stalls_inside_a_test_is_dumped_by_name_and_the_controller_shows_its_wait` (`-n 2`, bound 1 s, a 5 s block) | Acceptance: the stalled worker's file names `_bf985_blocks_here` and its test; the other worker's does not; the controller's shows `dsession.py`; the evidence holds only `shard-1` and `verify` passes | exit 4 (unknown option) |
| I2 | `test_a_failing_test_leaves_the_watchdog_armed_for_the_silence_after_it` (`-n 0`, a failing call, then a 4 s teardown) | D2: the re-arm after pytest's cancel in `pytest_exception_interact` | exit 4 |
| I3 | `test_a_process_held_open_at_exit_by_a_leftover_thread_is_dumped_during_shutdown` (`-n 0`, a 4 s non-daemon thread) | D3: armed through `threading._shutdown`; the dump shows `_shutdown` | exit 4 |
| U4 x2 | `test_configure_refuses_a_stack_dir_beside_pytests_faulthandler_timeout` (`"5"`, `5.0`) | D4 guard; no directory created | DID NOT RAISE |
| U5 x2 | `test_configure_accepts_a_stack_dir_when_nothing_else_drives_the_timer` (`"0"`; plugin off) | D4; an explicit bound (7) is used | KeyError (no watchdog) |
| U6 x2 | `test_configure_opens_this_processs_stack_file_and_arms_only_when_the_session_starts` (controller, gw3) | D1 naming; default 600; configure arms nothing; session start arms `(600, repeat=True, file=stream)` through the real `faulthandler` name | KeyError |
| U7 | `test_configure_refuses_a_worker_id_it_cannot_name_a_stack_file_after` | D4; no directory | DID NOT RAISE |
| U8 | `test_watchdog_rearms_on_test_events_at_most_once_per_twentieth_of_the_bound` | D2 throttle at the exact 30 s boundaries; a never-armed watchdog arms on its first event | AttributeError |
| U9 | `test_watchdog_rearms_inside_the_gap_where_pytest_cancels_the_timer_and_as_the_session_ends` | D2/D3: exception, session finish and unconfigure arm regardless of the throttle | AttributeError |
| U3 +3 | stall without a directory; empty directory; stall 0 | D4 | DID NOT RAISE |
| T5 +2 | real run: stall without a directory (`-n 0`); `-o faulthandler_timeout=5` under `-n 2` | refused before any worker; no directory | message differs (`unrecognized arguments`) |
| W4 (`test_ci_shards.py`) | `test_shard_job_uploads_the_stack_dumps_of_a_failed_or_cancelled_shard_apart_from_the_evidence` | D1/D6: position, `if`, exact `with`, the name cannot match `ci-shard-evidence-*`, the path is outside the evidence and equals the command's | `_step_named` finds nothing |

**Changed pins, one by one, and why each still guards what it guarded.**
- **`test_addoption_registers_the_four_options_with_no_defaults` becomes `..._six_...`.** It still pins every option's name, order, type and `default=None`, so no option can gain a default that arms anything locally.
- **`test_configure_is_inert_without_any_of_the_three_shard_options`.** One more option set; inertness is still asserted for every set, and now no stack directory is created either.
- **`sharded_run` and `test_the_runs_wrote_only_the_evidence_...` (renamed `..._the_evidence_and_empty_stack_files_apart_...`).** The evidence assertions are byte-identical. It adds the stack files (exact names and size 0), and `repo_strays` now also catches stack-shaped names. The eight cases on `sharded_run` (including `verify` = 0 and the three exactly-once mutations of real evidence) now run with the watchdog armed, which is the acceptance line "`verify` still passes".
- **`test_the_command_line_form_ci_uses_works_with_space_separated_options`.** It adds the space-separated stack option, which is exactly CI's form. The evidence and `verify` assertions are unchanged.
- **`test_misconfiguration_exits_four_...`.** Two cases are added. The existing assertions (exit 4, message, no nodes, no evidence) are unchanged, plus no stack directory.
- **`test_shard_job_keeps_the_runner_environment_extras_and_timeouts` (W1).** The job's 45 is still pinned; the step's 38 and `38 < 45` are added.
- **`test_shard_command_loads_the_plugin_...` (W2).** It adds the stack directory and the absence of a stall override. `_run_of(shard, "pytest")` still requires exactly one `run` containing `pytest`; the new step has no `run`.
- **`test_shard_job_uploads_its_evidence_whatever_the_outcome` (W3).** It now selects the step by name, because `_step_using` requires exactly one upload. It pins the exact list of upload steps, so a third upload or a rename still fails. Last position, `!cancelled()` and the exact `with` are byte-identical.
- **`test_summary_job_downloads_every_shard_artifact_and_runs_the_verifier`.** Unchanged: `steps[-1]` is still the evidence upload, which W3 pins.
- **`test_workflow_keeps_the_rationale_comments_...` (W5).** `lines.index("    timeout-minutes: 45")` still finds the job's line; the step's line has 8 spaces. The BF-322 and BF-657 comments stay between `- name: Run tests` and `run:`. It adds `BF-985` and `timeout-minutes: 38` in that span.

**Platforms (host Windows, CI Linux).**
- `faulthandler.dump_traceback_later` is thread-based and available on both (`faulthandler.register` is the Unix-only one, and it is not used).
- xdist starts workers with execnet `popen` on both: no fork.
- Every doubled run ends by itself (the block returns after 4 to 5 s), and `run_pytest`'s 180 s timeout kills nothing on the normal path.
- Every assertion is platform-neutral: function names, file basenames (`dsession.py`, and `_shutdown` from `threading.py`), the `Timeout (0:00:01` header prefix, and file names and sizes. No path separators and no thread ids.
- Startup on a loaded Windows host may add an early controller or worker dump during collection. No assertion forbids extra content, except that the non-stalled files must not name `_bf985_blocks_here`.

## 9. Mutation rows (lines in `scripts/_ci_shard_pytest_plugin.py` and `.github/workflows/ci.yml` on M2's head; where a stripped line repeats, the row names its method)

| # | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|
| 1 | `self._arm_timer(self._stall_seconds, repeat=True, file=self._stream)` | `repeat=False` | **U6**, **U8** |
| 2 | `if self._armed_at is None or self._clock() - self._armed_at >= self._rearm_gap:` | `if True:` | **U8**, U9 |
| 3 | same line | `>=` to `>` | **U8** (30.0 and 60.0 boundaries) |
| 4 | `self._armed_at = self._clock()` | `self._armed_at = None` | **U8** |
| 5 | `self._rearm_on_event()` in `pytest_runtest_logstart` | `pass` | **U8** |
| 6 | `self._rearm_on_event()` in `pytest_runtest_logreport` | `pass` | **U8**, U9 |
| 7 | `self.arm()` in `pytest_exception_interact` | `pass` | **I2**, U9 |
| 8 | `@pytest.hookimpl(trylast=True)` above `pytest_exception_interact` | `tryfirst=True` | **I2** (ours then runs before pytest's cancel) |
| 9 | `self.arm()` in `pytest_sessionstart` | `pass` | **U6**, U8, U9 |
| 10 | `self.arm()` in `pytest_sessionfinish` | `faulthandler.cancel_dump_traceback_later()` | **U9** (I3 survives because unconfigure re-arms after it; expected) |
| 11 | `self.arm()` in `pytest_unconfigure` | `faulthandler.cancel_dump_traceback_later()` | **I3**, U9 |
| 12 | `name = "controller"` | `name = "main"` | **U6[controller]**, I1, I2, I3, T3 |
| 13 | `if float(pytest_timeout or 0.0) > 0:` | `if False:` | **U4**, T5[faulthandler_timeout] |
| 14 | `if stall is not None:` | `if False:` | **U3[stall without dir]**, T5[stall] |
| 15 | `if _STACK_WORKER_ID.fullmatch(name) is None:` | `if False:` | **U7** |
| 16 | `stall_seconds=DEFAULT_STALL_SECONDS if stall is None else stall,` | `stall_seconds=DEFAULT_STALL_SECONDS,` | **U5**, I1, I2, I3 |
| 17 | `return path.open("w", encoding="utf-8")` | `return open(os.devnull, "w")` (add `import os`) | **I1**, I2, I3, U6, T3 |
| 18 | `timeout-minutes: 38` (ci.yml) | delete the line | **W1**, W5 |
| 19 | `if: ${{ failure() \|\| cancelled() }}` (ci.yml) | `if: ${{ !cancelled() }}` | **W4** |
| 20 | `name: ci-shard-stacks-${{ matrix.shard }}` (ci.yml) | `name: ci-shard-evidence-stacks-${{ matrix.shard }}` | **W4** (exact `with`, and the pattern match) |
| 21 | `--probos-shard-stack-dir "${{ runner.temp }}/ci-shard-stacks"` (ci.yml) | `... "${{ runner.temp }}/ci-shard-evidence/stacks"` | **W2**, W4 |

**Campaign.**
- The Builder runs it on M2's head with `tests/test_ci_shard_pytest_plugin.py` and `tests/test_ci_shards.py` (`-n 0 -p no:randomly`; baseline: both files 0 failed, counts recorded).
- It records the base tree, the LF sha256 of the plugin, `ci.yml` and both test files, and the cases each mutant fails.
- Each mutant must be killed by at least the case in bold. A survivor (other than the expected I3 survival in row 10, which U9 kills) is a hard stop for the Architect.
- That run is the campaign of record, and a later Builder whose four files match those hashes does not repeat it.

## 10. What this does NOT change

These are untouched:
- `scripts/ci_shards.py` (`verify`, `_read_shards`, `_read_shard`, `_WORKER_FILE`, the evidence schema);
- `ShardRecorder`;
- the `python-tests` job (download pattern, `Require every shard to succeed`, verify command);
- the evidence upload step (`if`, `with`, last position);
- the job's `timeout-minutes: 45`;
- `-n auto --maxfail=10 -q --tb=short`;
- `pyproject.toml` (no `faulthandler_timeout`, `timeout = 180`, `addopts`);
- `tests/conftest.py`, `tests/fixtures/duration_scheduler.py` and `tests/fixtures/file_durations.json`;
- `scripts/run_test_gate.py` and the canonical gate;
- the `ui-tests` job;
- `src/`, which gets no product change.

No dependency is added. OSS only.

## 11. Recorded limits

- **L1.** A process that keeps producing test events while making no real progress (a livelock across tests) is not dumped. It also does not stall at `[ 99%]`.
- **L2.** A stall that starts after minute 28 of `Run tests` gets no dump before the 38-minute limit. Healthy shards reach `[ 99%]` at about 13 to 14 minutes.
- **L3.** Python frames only. A thread blocked in C shows its last Python frame. faulthandler caps the threads per dump (100 in CPython, from memory, not re-read). Subprocesses that tests start are not covered (their own watchdogs exist).
- **L4.** The throttle lets a dump arrive up to S/20 (30 s) early: a dump means at least 570 s with no event.
- **L5.** `--pdb` cancels the timer (`pytest_enter_pdb`), and it is not re-armed. CI never uses `--pdb`.
- **L6.** A forked child of a pytest process that reaches `Py_Finalize` would block in faulthandler's cancel (CPython 3.12 has no fork handling). Nothing in `src/` or `tests/` forks the pytest process (section 12).
- **L7.** The `cancelled()` half of the upload condition depends on GitHub running `cancelled()` steps after a job-level timeout or a manual cancel. This is not verified; the step limit is the primary path.
- **L8.** Every failed shard's run uploads `ci-shard-stacks-K` (empty files unless it stalled). Green runs upload nothing.

## 12. Verified Against Codebase (2026-11-19, the scratch tree at `02079977`)

```
git rev-parse HEAD                      -> 020799776d5f0f23866f04fb48cf6608384c9166
git rev-parse HEAD:<paths>              -> the blobs in the header
scripts/ci_shards.py:54        _WORKER_FILE = re.compile(r"(?:main|gw[0-9]{1,6})\.json")
scripts/ci_shards.py:423-428   expected = {f"shard-{index}" ...}; "evidence root has an unexpected entry {name}"
scripts/ci_shards.py:444-445   _WORKER_FILE.fullmatch(entry.name) is None ... "has an unexpected entry"
scripts/ci_shards.py:316-317   write_evidence: worker id ... "is not main or gw<N>"
scripts/_ci_shard_pytest_plugin.py:24     "changes no markers, scheduling, timeouts or outcomes"
scripts/_ci_shard_pytest_plugin.py:87-93  --probos-shard-durations option (last option)
scripts/_ci_shard_pytest_plugin.py:164-187 ShardRecorder.pytest_sessionfinish writes evidence
scripts/_ci_shard_pytest_plugin.py:190-225 pytest_configure; :225 register(recorder, _RECORDER_NAME)
.github/workflows/ci.yml:27     timeout-minutes: 45
.github/workflows/ci.yml:58-75  Run tests (comments :59-69, run :70-75)
.github/workflows/ci.yml:77-85  Upload shard evidence, if: ${{ !cancelled() }}
.github/workflows/ci.yml:100-120 Require every shard to succeed; download pattern ci-shard-evidence-*, merge-multiple; verify
tests/test_ci_shards.py:1550-1553 _step_using asserts len == 1
tests/test_ci_shards.py:1579    assert shard["timeout-minutes"] == 45
tests/test_ci_shards.py:1617-1631 upload is last, !cancelled(), exact with
tests/test_ci_shards.py:1656    evidence = jobs[SHARD_JOB]["steps"][-1]["with"]["path"]
tests/test_ci_shards.py:1687-1695 lines.index("    timeout-minutes: 45"); step_comments between name and run
tests/test_ci_shard_pytest_plugin.py:162-170 repo_strays; :173-188 sharded_run; :245-251; :380-397; :422-454
tests/test_ci_shard_pytest_plugin.py:502-528 FakeConfig (no getini), configured() expects exactly one registration
tests/test_ci_shard_pytest_plugin.py:562-576 four options, defaults None, types [int,int,None,None]
pyproject.toml:190 timeout = 180 ; :196 addopts = "-n 16 --dist=loadfile"
tests/test_ad1192_owned_steps_store.py:2888 @pytest.mark.timeout(300, func_only=False)
tests/test_issue1419_failed_start_rollback.py:2822,2844,2874,2943 @pytest.mark.timeout(600)
tests/test_ad1198_peer_reset_gate.py:53, test_ad1198_fork_recovery_gate.py:99 @pytest.mark.timeout(480)
tests/conftest.py:306 def pytest_xdist_make_scheduler ; tests/fixtures/duration_scheduler.py:274 class DurationOrderedLoadFileScheduling(LoadFileScheduling)
venv _pytest/faulthandler.py:27 addini("faulthandler_timeout", ..., default=0.0); :78-79 float(getini(...) or 0.0)
venv _pytest/faulthandler.py:88-102 arms/cancels around each test when timeout > 0; :105-119 enter_pdb and exception_interact cancel (tryfirst)
venv _pytest/runner.py:250-253 logreport, then pytest_exception_interact when check_interactive_exception
venv _pytest/config/__init__.py:1677-1680 ValueError("unknown configuration value")
venv xdist/_version.py:20 '3.8.0'; xdist/scheduler/loadscope.py:313-326 _reschedule -> node.shutdown() when workqueue empty
venv xdist/dsession.py:95-99 sessionfinish -> teardown_nodes; :146-154 loop_once queue.get; :308-329 forwards logstart/logreport
venv xdist/remote.py:424-427 config.workerinput set before pytest_cmdline_main
CPython 3.12 Modules/faulthandler.c (fetched 2026-11-19): dump_traceback_later cancels the previous timer, stores a
  strong ref to the file, flushes once, starts a new thread; cancel joins via thread.running; no "fork" anywhere; Fini cancels
actions/runner StepsRunner.cs (blob 4a114fe0..., read by the orchestrator, .adq/f2/runner-step-timeout.txt): step timeout,
  job not cancelled -> TaskResult.Failed
scripts/gen_ad_ledger.py:126-132 status patterns
```

**Absence verified (2026-11-19).**
```
CLAIM: no faulthandler use in src/ or scripts/; in tests/ only the three child fixtures
RUN:   Grep "faulthandler" in src, scripts (no files); in tests (content)
FOUND: tests/fixtures/{federation_cluster_node,failed_start_child,rollback_child}.py and comments in test_issue1419
HOLDS: yes; and no test imports those fixtures (Grep "(import|from)\s+tests\.fixtures\.(failed_start_child|rollback_child|federation_cluster_node)" -> none)

CLAIM: no faulthandler_timeout anywhere; no pytest.ini/setup.cfg/tox.ini
RUN:   Grep faulthandler_timeout|dump_traceback over tests,src,scripts *.py; Grep faulthandler in pyproject/ini/workflows; Glob ini files
FOUND: only the fixture dump_traceback_later lines; no config hits; no ini files
HOLDS: yes

CLAIM: nothing forks the pytest process
RUN:   Grep os\.fork\(|get_context\(\s*["']fork|set_start_method|ProcessPoolExecutor|multiprocessing\.Process\(|mp\.Process\( in tests, src; Grep forkpty|pty\.fork
FOUND: tests/test_bf892_spawn_env_guard.py:74,657 (source strings inside a static guard's cases); src none
HOLDS: yes

CLAIM: pytest-timeout does not touch faulthandler
RUN:   Grep faulthandler|dump_traceback in venv pytest_timeout.py
FOUND: nothing
HOLDS: yes

CLAIM: no consumer of the plugin beyond the listed files
RUN:   Grep "_ci_shard_pytest_plugin|probos-shard" over scripts,tests,docs,.github,src
FOUND: ci.yml, the two test files, file_durations.json (a path key), ci_shards.py, the plugin, the optimization plan
HOLDS: yes

CLAIM: BF-985 unused in git history
RUN:   git log --all --oneline -i --grep=BF-985
FOUND: nothing
HOLDS: yes
```

## 13. Prior Art and Blind Spots

- **CPython `faulthandler`** (source read directly). Absorbed: a C watchdog thread that dumps without the GIL, `repeat=True`, and the file reference held by faulthandler. Its "one timer per process" and "no fork handling" drive D2, D4 and L6.
- **pytest's `faulthandler` plugin** (read). Rejected as the mechanism (`faulthandler_timeout` is per test). Its unconditional cancel in `pytest_exception_interact` is the blind spot the issue and my 2026-11-18 design missed; D2 re-arms after it, and I2 is its killer.
- **pytest-timeout** (read). It bounds a test, not the session; it has no faulthandler use, so no conflict.
- **In-repo child watchdogs** (#1419 fixtures). Adapted: arm as the process winds down, and keep the file open. Not adopted: `exit=True`, because CI must not change outcomes.
- **External search:** skipped. This is CI plumbing on a stdlib mechanism, and the primary sources were read directly. It is a BF, so the reference-projects review does not apply.
- **Blind spots settled:**
  - the evidence root is strict (D1);
  - the download pattern would swallow a `ci-shard-evidence-...` name (W4);
  - the `-q` log and `-n auto` change nothing here;
  - a worker missing from the uploaded evidence after a step limit is a second signal (D6).
- **Considered, deferred:**
  - native (`py-spy`) stacks: a new dependency;
  - covering pytest-started subprocesses: they have their own watchdogs;
  - the same watchdog in the canonical gate: a separate design if a gate ever stalls.

## 14. Diff Reviewer: properties to verify

1. **Inert by default.** Without `--probos-shard-stack-dir`, no file is created, no timer is armed, and the plugin registers exactly what it registered before. The shard options' validation and messages are unchanged.
2. **Validation before effects.** Every refusal (stall without a directory, stall below 1, empty directory, `faulthandler_timeout` > 0, bad worker id) raises `pytest.UsageError` before any directory is created or plugin registered.
3. **One timer, one owner.** Only `StallWatchdog.arm` calls `faulthandler.dump_traceback_later`, always with `repeat=True` and the process's own file. Nothing in the plugin calls `cancel_dump_traceback_later`. Construction does not arm.
4. **Arming points.**
   - Session start (tryfirst), session finish (tryfirst) and unconfigure (trylast) arm unconditionally.
   - `pytest_exception_interact` is trylast and arms unconditionally.
   - `logstart` and `logreport` arm through the throttle only, with `>=` against `stall_seconds / 20` on an injected monotonic clock.
5. **The file.** Exactly one file per process, `faulthandler-controller.txt` or `faulthandler-gwN.txt`, opened `w` with UTF-8, under the resolved stack directory, never closed by the plugin, and never inside the evidence directory.
6. **The workflow.**
   - `timeout-minutes: 38` sits on the `Run tests` step, between the BF-985 comment and `run:`, and the job's 45 is unchanged.
   - The command gains only `--probos-shard-stack-dir "${{ runner.temp }}/ci-shard-stacks"`.
   - The new upload step comes directly before `Upload shard evidence`, which is unchanged and last.
   - The artifact name cannot match `ci-shard-evidence-*`.
   - The `python-tests` job is byte-identical.
7. **Tests.** Each changed pin keeps every assertion it had except the one replaced by a name lookup (W3). The doubles end by themselves (no kill, no new timeout). No case depends on which gw gets the stalling file.
8. **Docstring and trackers.** The docstring says what the code does, and "changes no ... outcomes" remains true. The DECISIONS and PROGRESS heads carry no ledger status word, and the ledger pair is regenerated with M3.

## 15. Acceptance criteria

- G0 to G3 pass as stated, and the batch's broad gate is green with a receipt.
- **The issue's acceptance:**
  - A shard silent longer than the bound writes a stack dump for the controller and each live worker, into its own artifact uploaded when the step times out (I1, I3, W4, W1).
  - A normal run leaves no dump file with content (T3, T4).
  - `scripts/ci_shards.py verify` still passes (the `sharded_run` cases, I1, T4).
  - The contract shows the bound with a controlled double whose dump names the blocked function (I1, I2, I3).
- The mutation campaign of section 9 kills every row as stated.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1820)

- **Tick in #1820:** `- [x] **bf-983 F2** ... Repaired by BF-985 (PR #N, contract prompts/bf-985-ci-stall-stack-dumps.md): every pytest process of a CI shard now writes its stacks to faulthandler-<controller|gwN>.txt after 600 s without a test event (re-armed through interpreter shutdown), and Run tests has a 38-minute step limit, so a stall fails the step and ci-shard-stacks-K uploads. The stall's cause is still unknown; the first stall's artifact names it.` #1820 stays open for its other items.
- **Filing budget (append under the last update):** `Update after BF-985 (PR #N): no issue was opened or closed; the bf-983 F2 item is ticked as repaired by BF-985, so the counts of the update above stand. No security or data-integrity exception is claimed: the change is CI diagnostics only.`
- **Comment on #1452 (closed; item 8 unchecked):** `Item 8 (the end-of-run shard hang): the faulthandler watchdog proposed here is now built as BF-985 (PR #N, from #1820 bf-983 F2). A stalled CI shard now fails its Run tests step at 38 minutes and uploads ci-shard-stacks-K with one stack file per pytest process. Cause still open; it will be read from the first stall's artifact.`
- **What the first stall lets us read:**
  - Run `gh run download <run-id> -n ci-shard-stacks-<K> -D stacks-<run-id>`. Each `faulthandler-*.txt` holds one `Timeout (0:10:00)!` block per 600 s of silence: compare the last two blocks of each file (the same stack means a deadlock).
  - Run `gh run download <run-id> -n ci-shard-evidence-<K>`: a `gwN.json` missing from `shard-K/` marks a worker that never reached session finish.
  - The worker whose main thread is not in execnet's receive loop, or the thread inside `threading._shutdown`, names the cause. That becomes its own BF.

## 16. Amendment 1 (Diff Reviewer round 1, 2026-11-19)

The round-1 review of the frozen candidate `30397c18` (`gpt-6.1-sol`, an independent model family) found four things. This section governs where sections 2, 3, 7, 11 and the register text above read otherwise.

- **F1 (P2, ordinary reach, a regression): a stack directory inside the evidence directory was accepted.** pytest exited 0 and `scripts/ci_shards.py verify` then exited 1 (`unexpected entry faulthandler-controller.txt`, or `unexpected entry stacks`), so section 14 property 5 ("never inside the evidence directory") held only by the workflow's paths. `pytest_configure` now refuses a resolved stack directory that is the evidence directory or lies beneath it, with a `UsageError`, after the stack file is named and before any file is opened or directory made. The reverse (an evidence directory beneath the stack directory) is not refused: `verify` never reads the stack directory. Cases: five refused spellings and three accepted siblings. Mutation row **M-22**: the new condition set to `if False:`, killed by the refused cases. The workflow's two paths are disjoint, so CI is unchanged.
- **F2 (P2, injected-only reach, not a regression): the shutdown re-arm does not reach an xdist worker.** xdist ends a worker that is still alive 10 s after its run (`EXIT_TIMEOUT`), before a 600 s bound can fire, so "a process held at exit by a leftover non-daemon thread is dumped" holds for the controller and for the one process under `-n 0` only. The docstring, the comment of the last arm, the PROGRESS and DECISIONS entries and the P2.7 row now say so. New limit **L9**: a worker held at exit leaves no dump with the default bound, and no case holds a worker beyond `EXIT_TIMEOUT`; a diagnostic that runs before xdist ends the worker would be a new item, recorded in #1820. The three recorded stalls kept five processes alive for about 30 minutes, longer than xdist lets a worker outlive its run, so those runs had not ended: that is the case the dumps address.
- **F3 (P3): L2 was an absolute.** The dump is due one bound after the last arm, and the throttle can leave that arm up to S/20 = 30 s old, so a stall that starts shortly after minute 28 of the step can still be dumped before minute 38. L2 now reads: a stall that starts after about minute 28 of `Run tests` may get no dump before the 38-minute limit.
- **F4 (P3): "a cancelled job runs no later step" was too broad.** The runner keeps evaluating the conditions of later steps after a cancel (`StepsRunner`), so a step with `always()` or `cancelled()` can still run. The accurate claim is that the old evidence upload's `!cancelled()` skips a cancelled job, so the three recorded hangs uploaded nothing. The `ci.yml` comment and the PROGRESS entry now say that. L7 stands: whether `cancelled()` steps run after a job-level timeout is not verified here.

Tests: 26 new cases in all (the plugin file +25, `tests/test_ci_shards.py` +1). Mutation rows: 22.
