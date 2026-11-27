# AD-1346 M3e2b (#1604): the builder's targeted-test subprocess sink, and the census with no pending launch

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-31
**Status:** build-ready. **Issue:** #1604 (AD-1346 M3, epic #1601). The second part of M3e2 (D174), register R76. No new AD or BF number. **Tier:** HIGH (M1, M2), docs (M3). Nothing parked.
**Dependencies:** AD-1346 M3e2a (`prompts/ad-1346-m3e2a-subprocess-plumbing.md`) merged to `origin/main`. The build base is `origin/main` at the M3e2a merge.
**Anchors:** every SEARCH text in §7 and §8 was read on the detached checkout `34fce0da` (tree `3f97cf46`): `origin/main` at M3e1's merge (`9f78d3ec`) plus M3e2a's contract and its three milestones applied by tool, not merged; M1-16 and M1-19, which A2 re-anchored on M3e2a's review amendment A4, were read on M3e2a's merge `f0c5495b` (tree `82fc9d68`). 26 pairs (M1 24, M3 2), 1 new file (`tests/test_ad1346_admission_build_test_sink.py`), 2 regenerated files in M3 (`docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json`).
**Contract file:** `prompts/ad-1346-m3e2b-build-test-sink.md`.

**Identifiers.**
- Register rows: earlier slices' R10 to R83, and this contract's R84 to R89, are written "register R<n>".
- Tests: SK7 (`tests/test_ad1346_admission_ticket_sinks.py`), T16 (`tests/test_ad1346_admission_service.py`), EC1 to EC10 (`tests/test_ad1346_admission_effect_census.py`), SP1 to SP5 (`tests/test_ad1346_admission_subprocess_plumbing.py`), and this slice's BT1 to BT4 (`tests/test_ad1346_admission_build_test_sink.py`).
- Mutation rows are EQ-<n>. Decisions D185 to D193 follow M3e2a's D174 to D184. #1604's properties are numbered 1 to 13.

**Which text describes the head.**
- **Records of the read tree `3f97cf46` (commit `34fce0da`):** the Status and Anchors paragraphs, §1, §11 (Verified Against Codebase, Absence Verified), every line number cited in any section of this contract (`file:line` or `:line`), and every SEARCH text in §7 and §8 except M1-16's and M1-19's, which A2 re-anchored. Each of those SEARCH texts occurs once in its file on that tree, in the order the pairs are applied; M1-16's and M1-19's occur once on the merged tree below.
- **The M3e2a files.** M3e2a is merged: `origin/main` is `f0c5495b`, whose tree `82fc9d68` is the tree of M3e2a's gated head `ff604e48`. Its review moved text in seven files of the read tree `34fce0da`: M3e2a's contract (amendments A3 to A5), `tests/fixtures/ad1346_effect_census.py`, `tests/test_ad1346_admission_effect_census.py` and `tests/test_ad1346_admission_subprocess_plumbing.py` (review round 1's repair, M3e2a's amendment A4), `DECISIONS.md` (one inserted line) and the two regenerated AD-ledger files (their metadata). On the merged tree the 26 pairs of §7 and §8 apply by tool with no failure once M1-16 and M1-19 carry A4's text (13 files changed, 432 insertions, 26 deletions by `git diff --shortstat`, the AD ledger not regenerated). Re-verified there:
  - the M3e2a files this contract **edits**: `tests/fixtures/ad1346_effect_census.py` (M1-13 anchors on M3e2a's `EFFECT_CLASSES` value, M1-14 on its `_COMPONENT_SERVICE`, M1-15 on its Pending row); `tests/test_ad1346_admission_effect_census.py` (M1-16 to M1-19 anchor on M3e2a's docstring bullets, EC2 counts, EC3 service line and EC4 body); `tests/test_ad1346_admission_service.py` (M1-21 to M1-23 anchor on M3e2a's T16 lines); `src/probos/admission/service.py` (M1-10, M1-11) and `src/probos/admission/seam.py` (M1-12), on M3e2a's "seven from AD-1346 M3e2a" text; `src/probos/runtime.py` (M1-09 anchors on lines M3e2a does not edit, in a file it edits); `PROGRESS.md` (M3-01 anchors on M3e2a's paragraph head); `DECISIONS.md` (M3-02 anchors on the heading after M3e2a's entry);
  - the M3e2a code it **cites**, unedited: SP4's and SP5's fixtures and launch replacement (`tests/test_ad1346_admission_subprocess_plumbing.py:108-171`, `:269-305` on `34fce0da`; `:109-172` and `:271-307` on the merged tree, the same text), which BT3 and BT4 follow; `DependencyResolver.set_admission` (`cognitive/dependency_resolver.py:77-81`), D187's precedent; `runtime.py:3097-3098`; D174 to D184 and R76 to R83.

  A2 moved M1-16 and M1-19 only (A2-2 and A2-3 in §16); no other pair's SEARCH text differs from the one read on `34fce0da`.
- **Parts that describe the candidate's head and name no commit:** the Milestones and Tests lists, §2 to §6, §8's tracker text, §9, §10, §12, §14 and §15.
- **Text inside the new-file block** (docstrings, comments, failure messages) is head text and is reviewed as such.
- Where a record and the candidate differ, re-measure; the record does not bind.

**Milestones:**
- **M1 (HIGH):** the sink, its keyword and the three callers' wiring; the census row and the pins that move with it (EC2 to EC4, T16); three docstring passages that counted M3e2a's seven subprocess sinks (M1-10 to M1-12).
- **M2 (HIGH):** the new test file, BT1 to BT4.
- **M3 (docs):** `PROGRESS.md`, `DECISIONS.md`, and the AD ledger regenerated by its tool.

**Process:**
- Each milestone is one Builder delegation and one local commit. Stage by explicit path, never `git add -A`. `git add` the new file before M2's focused gate.
- Commit subjects take the form `AD-1346 M3e2b, M<n>: ... (#1604)`.
- One cross-family review (`gpt-6.1-sol`) of M1 and M2 against §14.
- One mutation campaign of record on the M2 tree (§10), after an unmutated baseline passes.
- The broad gate runs once, after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1346-m3e2b --receipt logs/gates/ad1346-m3e2b.receipt.json`.

**Tests:**
- New: `tests/test_ad1346_admission_build_test_sink.py` (M2), BT1 to BT4. The block in §7.2 defines 4 `def test_` functions and no parametrised case.
- Updated, each file's `def test_` count unchanged: EC2, EC3, EC4 and the module docstring (`tests/test_ad1346_admission_effect_census.py`); T16's module bullet, docstring and three sets (`tests/test_ad1346_admission_service.py`).
- The acceptance greps for the new file are in §15.

## 1. Problem

- M3e2a left one launch as `Pending("M3e2b", "model-authored tests of an approved build")` (`tests/fixtures/ad1346_effect_census.py:109` on `34fce0da`; register R76). EC2 pins it (`tests/test_ad1346_admission_effect_census.py:210`, `:212`), and D160 requires the pending count to reach zero by M3e5.
- The launch, on `34fce0da`:
  - `_run_targeted_tests` (`cognitive/builder.py:2961`) maps the changed files to test files (`:2973`), returns `(False, NO_TARGETED_TESTS, [])` with no launch when none maps (`:2975-2976`), and otherwise hands `_sync_run` (`:2980`) to an executor (`:2998-2999`). `_sync_run` runs `subprocess.run([sys.executable, "-m", "pytest", ...] + test_files)` (`:2984-2990`) on "model-authored tests" (`:2982`).
  - `execute_approved_build` (`:3244`) calls it once per attempt (`:3562`, `:3566-3568`), inside `if run_tests and (written or modified_files) and not validation_errors:` (`:3552`).
- Its three `src` calls (Absence Verified):
  - `routers/build.py:441`, in `_execute_build` (`:417`), which `resolve_build` schedules at `:165` (`commit_override`, `run_tests=False`) and `:184` (the retries) with `runtime`, `request.app.state.runtime` (`routers/deps.py:15-17`). It passes `enforce_sealed_core=sealed_core_enforced(rt)` and no runtime (`:448`).
  - `build_dispatcher.py:224`, in `BuildDispatcher._execute_build` (`:159`). `init_structural_services` builds the dispatcher (`startup/structural_services.py:126-131`) and starts it (`:132`), and `ProbOSRuntime.start` keeps it (`runtime.py:3328`). Its constructor takes no service (`build_dispatcher.py:40-52`).
  - `build_pipeline.py:89`, in `BuildPipeline.execute_approved_build` (`:56`), which passes `runtime=self._runtime` (`:98`). `ProbOSRuntime.start` builds `BuildPipeline(runtime=self)` (`runtime.py:3730`). No `src` code calls the method (Absence Verified).
- Why the executor's `runtime` parameter is not the carrier: the router and the dispatcher pass none, because a runtime switches on the pre-flight runner and Hebbian recording (`builder.py:3176-3177`, `:3274-3275`, `:3343`, `:3878`).
- Hidden pins this slice meets:
  - SK7 requires the `src` functions that call `check_at` to be the two M3d3a sinks plus `subprocess_sink_functions()` (`tests/test_ad1346_admission_ticket_sinks.py:509-510`).
  - EC3 accepts two service forms (`tests/test_ad1346_admission_effect_census.py:226`). EC4's set of split rows is three files (`:246-248`), and each link's name is searched in its file (`:254`). `builder.py` holds two other functions with a nested `_sync_run` that they reference: `_run_git` (`:1607`, `:1625`) and `_run_tests` (`:2903`, `:2923`).
  - T16 pins the files outside `probos/admission/` whose text contains `admission_service` (`tests/test_ad1346_admission_service.py:610-611`, `:619-628`), those that import `probos.admission` (`:612-618`, `:629-638`), and the routers among them (`:639-640`).
  - `test_expected_git_dir_keeps_its_position_and_only_optional_parameters_follow_it` reads `execute_approved_build`'s parameters (`tests/test_bf896_executor_identity_and_blocks.py:705-715`): the first eleven keep their names, indices and kind, and every parameter after `work_dir` has a default.
  - `scripts/check_architecture_principles.py` fails on a new `srp-size` trigger: `if span > SRP_MAX_BODY_LINES:` (`:566`) or `if methods > SRP_MAX_DIRECT_METHODS:` (`:568`), with `SRP_MAX_BODY_LINES = 500` and `SRP_MAX_DIRECT_METHODS = 15` (`:187-188`). Category, key, callee, triggers and count form the baseline identity and payload (`:256-257`).
  - BF-892's floor `_KNOWN_LAUNCH_FLOOR = 39` (`tests/test_bf892_spawn_env_guard.py:78`). This slice adds no launch.

## 2. Solution

- **The sink.** `execute_approved_build` gains a keyword `admission_service: object = None`, appended after `enforce_sealed_core`. In each attempt of its test loop it calls `check_at(admission_service, effect=EFFECT_SUBPROCESS, presented_id=None)` before the `_run_targeted_tests` call. With anything but an exact `AdmissionService`, `check_at` does nothing.
- **The wiring.**
  - the router's `_execute_build` passes `getattr(rt, "admission_service", None)`;
  - `BuildPipeline.execute_approved_build` passes `getattr(self._runtime, "admission_service", None)`;
  - `BuildDispatcher` gains `set_admission` and a class attribute `_admission = None`, and passes `self._admission`; `ProbOSRuntime.start` calls `self.build_dispatcher.set_admission(self.admission_service)` right after it keeps the dispatcher.
- **The census.** The Pending row becomes a `Sink` whose check is `execute_approved_build`, whose service is `admission_service` and whose `via` is `("_run_targeted_tests",)`. The totals become Sink 12 launches in 8 rows, System 19, OutsideRuntime 5, Unreached 3, Pending 0; 39 in all.
- **The guards.** EC3 accepts the third service form. EC4 does not search a link whose function is nested in the one before it, and asserts that the builder's is the one such link. BT1 pins the three calls' keyword by AST.
- **The tests.** BT2 boots a real runtime and checks each caller's hand-off. BT3 (the crossing test) drives the real resolve route and executor, and BT4 (the golden test) the real executor, each with `subprocess.run`, `subprocess.Popen` and asyncio's two subprocess constructors replaced.

## 3. Decisions (numbered after M3e2a's D174 to D184)

- **D185 The classification: a sink.** The launch runs pytest on test files a model wrote into the build tree (`builder.py:2982`; `_map_source_to_tests` includes changed files that are test files, `:2943-2949`). That is D163's criterion: a launch that model text directs. The sandbox (M3e2a) is the precedent.
  - Rejected:
    - `System` (D178's git runs fixed verbs on data; here the executed code is the model's);
    - `Unreached` (the router and the dispatcher reach it);
    - `Pending` (D160).
- **D186 The place: in `execute_approved_build`, in the awaiting task, before each attempt's `_run_targeted_tests` call.** The census row's `via` is `("_run_targeted_tests",)`. A repair's new test files are run on the next attempt (`:3563-3564`), so each attempt is checked.
  - Rejected:
    - inside `_run_targeted_tests` after its no-tests return (it would check only a launching run). The service would have to reach it as a keyword at `:3566`, and twelve test replacements have no `**kwargs` and no `admission_service` parameter (Absence Verified): `tests/test_bf896_executor_identity_and_blocks.py:628`, `:764`, `:778`; `tests/test_bf897_build_pipeline_scale_and_checkout.py:667`; `tests/test_bf904a_git_hardening.py:235`; `tests/test_bf904b_fix_loop_state.py:113`, `:210`, `:268`, `:316`; `tests/test_bf904b_sealed_core_observation.py:127`; `tests/test_builder_agent.py:2221`, `:2714`;
    - once before the loop (a repair's tests would run unchecked);
    - on the executor thread (D179).
- **D187 The plumbing: a keyword on the executor, passed by each `src` call.**
  - The router and the pipeline hold a runtime and read its service with `getattr` defaults, as the M3c sites do. The router's runtime double in `tests/test_bf904b_sealed_core_observation.py` has no `admission_service` (`:140-142`).
  - The dispatcher is built in `init_structural_services`, which takes no runtime or service, so the runtime hands it the service with `set_admission`, as D175 does for the installer (`runtime.py:3097-3098`).
  - Ranked:
    1. this (correct at every caller, compatible: an appended keyword with a default; the executor's replacements in tests are `AsyncMock`s or functions taking `**kwargs`, Absence Verified);
    2. reading `getattr(runtime, "admission_service", None)` from the executor's own `runtime` parameter (no signature change, but only the pipeline passes a runtime, and no `src` code calls it: production checks nothing);
    3. a keyword on `_run_targeted_tests` (D186);
    4. a context variable set by the callers (a second, hidden carrier read by a global lookup).
  - Rejected for the dispatcher: a constructor keyword from `init_structural_services` (a wider startup signature, D175).
  - The pattern is BF-904b's `enforce_sealed_core` (`routers/build.py:448`, `build_dispatcher.py:231`, `startup/structural_services.py:130`).
- **D188 The presented id: None.** `BuildSpec` names no agent (`builder.py:115-122`). `QueuedBuild.builder_id` (`build_queue.py:50`) is never assigned in `src` (Absence Verified). The router's failure cache holds no requester (`routers/build.py:474-480`).
  - Rejected:
    - the literal `system:ship_computer` (it would say the Ship's Computer wrote the tests; EC5 asserts that no seam statement presents a `system:` literal, `tests/test_ad1346_admission_effect_census.py:262`);
    - `builder_id` (always empty).
- **D189 The carrier, from the code.** `rg -n "hold_at\(|\.hold\(|CURRENT_TICKET" src/probos/routers/build.py src/probos/build_dispatcher.py src/probos/build_pipeline.py src/probos/cognitive/builder.py src/probos/api.py` prints nothing and exits 1.
  - The dispatcher's builds run in tasks its loop creates (`build_dispatcher.py:138`). The loop is a task created at `start` (`:89`), during boot.
  - The resolve route's build runs in a task `_track_task` creates (`api.py:224`) from the request handler.
  - BT3 measures `ticket_missing` for a check outside any hold, and `ticket_live` and `ticket_revoked` inside a hold the test makes.
  - M3e5 decides a build issue point (R37, R38): the work kind, the principal and the hold for the dispatcher's and the resolve route's builds. This slice leaves the check reading the carrier; a later hold around those entries is counted with no change here.
- **D190 The census and its pins.**
  - The row: `Sink("execute_approved_build", "None", service=_PARAMETER_SERVICE, via=("_run_targeted_tests",))`, with `_PARAMETER_SERVICE = "admission_service"`.
  - EC2: Sink 12 in 8 rows, System 19, OutsideRuntime 5, Pending 0, Unreached 3, and no Pending row.
  - EC3: the third form.
  - EC4: the builder joins the split rows. A link whose function is nested in the one before it is not searched, since Python binds a nested function's name in the function that defines it, and EC4 asserts that the builder's is the one such link.
  - The `Pending` class stays, unused by any row.
  - SK7 needs no edit: `subprocess_sink_functions()` yields `("src/probos/cognitive/builder.py", "execute_approved_build")`.
  - T16: `named` gains `build_dispatcher.py`, `build_pipeline.py`, `cognitive/builder.py` and `routers/build.py`; `importers` gains `cognitive/builder.py`; the routers become four.
  - BF-892's floor stays 39.
  - Rejected: deleting `Pending` (more edits, and a later new launch may need it before its sink lands).
- **D191 Tests.** A new file, BT1 to BT4.
  - BT2 boots a real runtime with `admission.shadow_enabled` true, as `tests/test_ad1346_admission_ticket_sinks.py:544` does, so the dispatcher's and the pipeline's hand-offs are measured on the objects `ProbOSRuntime.start` builds (M3e1's F1). It calls `resolve_build` with that runtime as its `runtime` argument, not through its `Depends(get_runtime)` (`routers/build.py:101`; `routers/deps.py:15-17`).
  - Rejected: an AST pin alone (BT1 stays, for a fourth caller).
- **D192 Cost, config and class size.**
  - One `check_at` call per targeted-test attempt: at most `1 + max_fix_attempts` per `execute_approved_build` call, 3 with the default (`builder.py:3249`, `:3562`). D169 holds; no new measurement.
  - No `SystemConfig` field is added or changed.
  - `BuildDispatcher` goes from 13 to 14 direct methods; its span from `:37` to the file's last line `:428` is 392 lines, and M1-06 and M1-07 add 7 (`wc -l src/probos/build_dispatcher.py` prints 435 after M1). No class gains a trigger.
- **D193 Register rows.** R76 is resolved; R70 is resolved for all 11 launches. R37 and R38 stay with M3e5 (D189). New: R84 to R89. None refused.

## 4. Milestones and focused gates

| Milestone | Files | Focused gate |
|---|---|---|
| M1 | `src/probos/cognitive/builder.py`, `src/probos/routers/build.py`, `src/probos/build_dispatcher.py`, `src/probos/build_pipeline.py`, `src/probos/runtime.py`, `src/probos/admission/service.py`, `src/probos/admission/seam.py`, `tests/fixtures/ad1346_effect_census.py`, `tests/test_ad1346_admission_effect_census.py`, `tests/test_ad1346_admission_service.py` | `pytest tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_ticket_sinks.py tests/test_ad1346_admission_service.py tests/test_ad1346_admission_subprocess_plumbing.py tests/test_ad1346_admission_tickets.py tests/test_ad1346_admission_ticket_issue.py tests/test_ad1346_identity_service.py tests/test_bf892_spawn_env_guard.py tests/test_bf892_spawn_env.py tests/test_builder_agent.py tests/test_builder_guardrails.py tests/test_builder_api.py tests/test_build_dispatcher.py tests/test_bf894_builder_write_boundary.py tests/test_bf896_executor_identity_and_blocks.py tests/test_bf896_dispatcher_confinement_seam.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_bf898_fix_loop_grader_protection.py tests/test_bf904a_failed_build_restore.py tests/test_bf904a_git_hardening.py tests/test_bf904a_unapplied_blocks.py tests/test_bf904b_fix_loop_state.py tests/test_bf904b_sealed_core_observation.py tests/test_bf904b_dispatch_and_visiting.py tests/test_ad1344_constitution_write_refusal.py tests/test_ad476_specialized_builders.py tests/test_ad521_swe_pipeline_separation.py tests/test_ad1270_night_orders_triggers.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_layer_boundaries.py -n 0`; `python -P scripts/check_architecture_principles.py --check`; `python -P scripts/check_store_registry.py --check` |
| M2 | new `tests/test_ad1346_admission_build_test_sink.py` | `git add` the new file, then `pytest tests/test_ad1346_admission_build_test_sink.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_ticket_sinks.py -n 0`; `pytest tests/test_ad1346_admission_build_test_sink.py --collect-only -q -p no:cacheprovider -n 0` (record the count: 4) |
| M3 | `PROGRESS.md`, `DECISIONS.md`; regenerated `docs/development/open-ads-report.md`, `docs/development/ad-ledger-snapshot.json` | `python -P scripts/gen_ad_ledger.py`, then `python -P scripts/gen_ad_ledger.py --check`, then `pytest tests/test_ad1184_ad_ledger.py -n 0` |

## 5. Consumers of every value this changes

- **`execute_approved_build`'s signature.** One parameter is appended after `enforce_sealed_core`, with a default. The BF-896 signature test reads the parameters before it and requires a default after `work_dir`. `tests/test_ad476_specialized_builders.py:180-185` reads `specialty` only.
  - Tests that replace the executor use `AsyncMock` or a function taking `**kwargs` (Absence Verified).
  - Tests that replace `_run_targeted_tests` are called with the same arguments: M1 does not edit the call (`:3566`).
- **The check statement.** It is an expression statement whose value is discarded; `check_at` returns None and raises only what `check_ticket` raises, and the real `check_ticket` lets no `Exception` out (`seam.py:49-53`; `service.py:230-238`). Its argument is a local name.
  - With `run_tests` false, or a build holding a refusal, the loop does not run and nothing is checked.
  - An attempt whose files map to no test is checked and launches nothing (register R84).
- **`BuildDispatcher`.** It gains `set_admission` and a class attribute `_admission = None`. Its call passes `self._admission`, read inside `_execute_build`'s `try` (`:174`), whose `except Exception` (`:299`) handles a raise.
- **`ProbOSRuntime.start`.** After `self.build_dispatcher = struct.build_dispatcher`, when that is not None, it calls `set_admission(self.admission_service)`. An `Exception` raised by that call propagates from `start`.
- **The router and the pipeline.** Their `getattr(..., "admission_service", None)` is an argument expression, evaluated before the executor runs (register R89).
- **The service's counts.** With a registry, a check the service makes counts its finding under the operation `subprocess` (BT3's and BT4's `tickets.tally()`). With a recorder, `_check_ticket` offers it to `ShadowRecorder.offer_ticket` (`service.py:258`).
- **SK7** is unchanged (D190); **EC2 to EC4 and T16** are updated as §6 lists.

## 6. Tests

| File | M | Cases | What |
|---|---|---|---|
| `tests/test_ad1346_admission_build_test_sink.py` | M2 | 4 | BT1 to BT4: the three calls' keyword and the dispatcher's hand-off by AST; the hand-off on a booted runtime at each caller; the crossing test over the resolve route; the golden test over the executor |
| `tests/test_ad1346_admission_effect_census.py` | M1 | unchanged count | the docstring's EC2 to EC4 bullets; EC2's counts and Pending list; EC3's third form; EC4's nested link |
| `tests/test_ad1346_admission_service.py` | M1 | unchanged count | the module's T16 bullet, T16's docstring and its three sets |

## 7. The contract

### 7.1 M1

**M1-01** (`src/probos/cognitive/builder.py`)

SEARCH:
```
from typing import TYPE_CHECKING, Any

from probos.cognitive.builder_paths import (
```
REPLACE:
```
from typing import TYPE_CHECKING, Any

from probos.admission.seam import check_at
from probos.admission.taxonomy import EFFECT_SUBPROCESS
from probos.cognitive.builder_paths import (
```

**M1-02** (`src/probos/cognitive/builder.py`)

SEARCH:
```
    expected_git_dir: str | None = None,
    enforce_sealed_core: bool | None = None,
) -> BuildResult:
```
REPLACE:
```
    expected_git_dir: str | None = None,
    enforce_sealed_core: bool | None = None,
    admission_service: object = None,
) -> BuildResult:
```

**M1-03** (`src/probos/cognitive/builder.py`)

SEARCH:
```
            and the dispatcher pass the flag, because they pass no runtime.
    """
    result = BuildResult(success=False, spec=spec)
```
REPLACE:
```
            and the dispatcher pass the flag, because they pass no runtime.
        admission_service: AD-1346 M3e2b. The service the targeted-test sink
            checks each attempt's run with, in shadow (``check_at``); anything
            but an exact ``AdmissionService``, None by default, checks nothing.
            The /api/build resolve route and ``BuildPipeline`` read it from their
            runtime; the dispatcher passes the one ``ProbOSRuntime.start`` hands it.
    """
    result = BuildResult(success=False, spec=spec)
```

**M1-04** (`src/probos/cognitive/builder.py`)

SEARCH:
```
            for attempt in range(1 + max_fix_attempts):
                # BF-904b (#1585): read at the start of each attempt, so a file an earlier repair created is targeted.
                all_changed_files = written + modified_files
                # Targeted tests only (AD-344). BF-897: there is no full-suite phase here.
```
REPLACE:
```
            for attempt in range(1 + max_fix_attempts):
                # BF-904b (#1585): read at the start of each attempt, so a file an earlier repair created is targeted.
                all_changed_files = written + modified_files
                check_at(admission_service, effect=EFFECT_SUBPROCESS, presented_id=None)  # AD-1346 M3e2b: the targeted-test sink, in shadow, in the awaiting task before each attempt's run; it blocks nothing (D188: no principal)
                # Targeted tests only (AD-344). BF-897: there is no full-suite phase here.
```

**M1-05** (`src/probos/routers/build.py`)

SEARCH:
```
            escalation_hook=None,
            enforce_sealed_core=sealed_core_enforced(rt),  # BF-904b (#1585): the runtime's flag; no runtime is passed
        )
```
REPLACE:
```
            escalation_hook=None,
            enforce_sealed_core=sealed_core_enforced(rt),  # BF-904b (#1585): the runtime's flag; no runtime is passed
            admission_service=getattr(rt, "admission_service", None),  # AD-1346 M3e2b: the targeted-test sink's service; None checks nothing
        )
```

**M1-06** (`src/probos/build_dispatcher.py`)

SEARCH:
```
    def enforce_sealed_core(self) -> bool:
        """BF-904b (#1585): whether the builds this dispatcher runs observe writes to sealed-core paths."""
        return self._enforce_sealed_core
```
REPLACE:
```
    def enforce_sealed_core(self) -> bool:
        """BF-904b (#1585): whether the builds this dispatcher runs observe writes to sealed-core paths."""
        return self._enforce_sealed_core

    _admission: object = None  # AD-1346 M3e2b (set_admission): None checks nothing

    def set_admission(self, service: object) -> None:
        """AD-1346 M3e2b: late-bind the service the targeted tests of the builds this dispatcher runs are checked with, in shadow; it blocks nothing."""
        self._admission = service
```

**M1-07** (`src/probos/build_dispatcher.py`)

SEARCH:
```
                expected_git_dir=expected_git_dir,
                enforce_sealed_core=self._enforce_sealed_core,  # BF-904b (#1585): AD-481f's observation
            )
```
REPLACE:
```
                expected_git_dir=expected_git_dir,
                enforce_sealed_core=self._enforce_sealed_core,  # BF-904b (#1585): AD-481f's observation
                admission_service=self._admission,  # AD-1346 M3e2b: the service ProbOSRuntime.start hands the dispatcher; None checks nothing
            )
```

**M1-08** (`src/probos/build_pipeline.py`)

SEARCH:
```
            builder_source=builder_source,
            runtime=self._runtime,
            specialty=specialty,
        )
```
REPLACE:
```
            builder_source=builder_source,
            runtime=self._runtime,
            specialty=specialty,
            admission_service=getattr(self._runtime, "admission_service", None),  # AD-1346 M3e2b: the targeted-test sink's service; None checks nothing
        )
```

**M1-09** (`src/probos/runtime.py`)

SEARCH:
```
        self.build_queue = struct.build_queue
        self.build_dispatcher = struct.build_dispatcher
        self.service_profiles = struct.service_profiles
```
REPLACE:
```
        self.build_queue = struct.build_queue
        self.build_dispatcher = struct.build_dispatcher
        if self.build_dispatcher is not None:  # AD-1346 M3e2b: the targeted-test sink's service for the dispatcher's builds; None checks nothing
            self.build_dispatcher.set_admission(self.admission_service)
        self.service_profiles = struct.service_profiles
```

**M1-10** (`src/probos/admission/service.py`)

SEARCH:
```
AD-1346 M3e1: ``check_at`` is also called at subprocess sinks (five from M3e1, seven from AD-1346 M3e2a) with the effect
```
REPLACE:
```
AD-1346 M3e1: ``check_at`` is also called at subprocess sinks (five from M3e1, seven from AD-1346 M3e2a, eight from AD-1346 M3e2b) with the effect
```

**M1-11** (`src/probos/admission/service.py`)

SEARCH:
```
        subprocess sinks (seven from AD-1346 M3e2a). It reads the carrier in the
```
REPLACE:
```
        subprocess sinks (seven from AD-1346 M3e2a, eight from AD-1346 M3e2b). It reads the carrier in the
```

**M1-12** (`src/probos/admission/seam.py`)

SEARCH:
```
M3e2a (``tests/test_ad1346_admission_effect_census.py``, EC3). It returns None, awaits nothing and raises no ``Exception``:
```
REPLACE:
```
M3e2a and eight from AD-1346 M3e2b (``tests/test_ad1346_admission_effect_census.py``, EC3). It returns None, awaits nothing and raises only what ``check_ticket`` raises:
```

**M1-13** (`tests/fixtures/ad1346_effect_census.py`)

SEARCH:
```
    "subprocess": "AD-1346 M3e1 and M3e2a: SUBPROCESS_SITES; its Pending row, AD-1346 M3e2b",
```
REPLACE:
```
    "subprocess": "AD-1346 M3e1, M3e2a and M3e2b: SUBPROCESS_SITES",
```

**M1-14** (`tests/fixtures/ad1346_effect_census.py`)

SEARCH:
```
#: AD-1346 M3e2a (D175): the service a component handed it passes to ``check_at``.
_COMPONENT_SERVICE: Final = "self._admission"
```
REPLACE:
```
#: AD-1346 M3e2a (D175): the service a component handed it passes to ``check_at``.
_COMPONENT_SERVICE: Final = "self._admission"
#: AD-1346 M3e2b (D187): the executor of an approved build passes its own parameter to ``check_at``.
_PARAMETER_SERVICE: Final = "admission_service"
```

**M1-15** (`tests/fixtures/ad1346_effect_census.py`)

SEARCH:
```
    # Pending: the launching code holds no service today (register R76).
    ("src/probos/cognitive/builder.py", "_run_targeted_tests._sync_run"): (1, Pending("M3e2b", "model-authored tests of an approved build")),
```
REPLACE:
```
    # AD-1346 M3e2b: the executor of an approved build, handed the service by the three src calls of it (D185 to D187).
    ("src/probos/cognitive/builder.py", "_run_targeted_tests._sync_run"): (1, Sink("execute_approved_build", "None", service=_PARAMETER_SERVICE, via=("_run_targeted_tests",))),
```

**M1-16** (`tests/test_ad1346_admission_effect_census.py`)

SEARCH:
```
- EC2  every (file, function) of BF-892's scan is a row with its launch count, and every row is one; the census holds
       11 sink launches in 7 rows, 19 system, 5 command-line, 3 unreached and 1 pending launch, the pending one
       M3e2b's (AD-1346 M3e2a).
- EC3  each sink function holds one ``check_at`` call, a statement of its own, with the row's service (the runtime's or,
       from AD-1346 M3e2a, ``self._admission``), the effect ``EFFECT_SUBPROCESS`` and the row's presented id, on a line
       before its launch or its reference to the next function of its chain.
- EC4  a sink whose launch is in another function: in its file, each function of its chain after the sink's function
       (AD-1346 M3e2a: through ``via``, to the launching one) is referenced only in the function before it and in its own.
```
REPLACE:
```
- EC2  every (file, function) of BF-892's scan is a row with its launch count, and every row is one; the census holds
       12 sink launches in 8 rows, 19 system, 5 command-line and 3 unreached launches, and no pending one (AD-1346
       M3e2b).
- EC3  each sink function holds one ``check_at`` call, a statement of its own, with the row's service (the runtime's,
       from AD-1346 M3e2a ``self._admission``, or from AD-1346 M3e2b the executor's parameter ``admission_service``),
       the effect ``EFFECT_SUBPROCESS`` and the row's presented id, on a line before its launch or its reference to the
       next function of its chain.
- EC4  a sink whose launch is in another function: in its file, each function of its chain after the sink's function
       (AD-1346 M3e2a: through ``via``, to the launching one) is referenced only in the function before it and in its own;
       a function nested in the one before it is not searched, since its name is local to that function (AD-1346
       M3e2b: the builder's ``_run_targeted_tests._sync_run`` is the one such link).
```

**M1-17** (`tests/test_ad1346_admission_effect_census.py`)

SEARCH:
```
    assert by_kind == {Sink: 11, System: 19, OutsideRuntime: 5, Pending: 1, Unreached: 3}, by_kind  # AD-1346 M3e2a
    assert sum(type(cover) is Sink for _count, cover in SUBPROCESS_SITES.values()) == 7
    assert {cover.owner for _count, cover in SUBPROCESS_SITES.values() if type(cover) is Pending} == {"M3e2b"}
```
REPLACE:
```
    assert by_kind == {Sink: 12, System: 19, OutsideRuntime: 5, Pending: 0, Unreached: 3}, by_kind  # AD-1346 M3e2b
    assert sum(type(cover) is Sink for _count, cover in SUBPROCESS_SITES.values()) == 8
    assert [site for site, (_count, cover) in SUBPROCESS_SITES.items() if type(cover) is Pending] == []  # AD-1346 M3e2b: D160's zero
```

**M1-18** (`tests/test_ad1346_admission_effect_census.py`)

SEARCH:
```
        assert cover.service in (SERVICE_EXPR, "self._admission"), (path, cover.check)  # AD-1346 M3e2a: the two forms
```
REPLACE:
```
        assert cover.service in (SERVICE_EXPR, "self._admission", "admission_service"), (path, cover.check)  # AD-1346 M3e2b: the three forms
```

**M1-19** (`tests/test_ad1346_admission_effect_census.py`)

SEARCH:
```
    """EC4."""
    rows = [(path, scope, cover) for (path, scope), (_n, cover) in SUBPROCESS_SITES.items() if isinstance(cover, Sink)]
    split = [(path, scope, cover) for path, scope, cover in rows if cover.check != scope]
    assert {path for path, _scope, _cover in split} == {
        "src/probos/agents/shell_command.py", "src/probos/agents/red_team.py", "src/probos/execution/isolation.py",
    }
    for path, scope, cover in split:
        tree = ast.parse(src_sources()[path], filename=path)
        chain = (cover.check, *cover.via, scope)  # AD-1346 M3e2a: each link, in call order
        for index in range(1, len(chain)):
            caller, callee = chain[index - 1], chain[index]
            assert references_outside(tree, callee.rsplit(".", 1)[-1], (caller, callee)) == [], (path, callee)
```
REPLACE:
```
    """EC4: in its file, each function of a sink's chain after its check function is referenced only in the function
    before it and in itself; a function nested in the one before it is not searched (AD-1346 M3e2b), and the builder's
    is the one such link."""
    rows = [(path, scope, cover) for (path, scope), (_n, cover) in SUBPROCESS_SITES.items() if isinstance(cover, Sink)]
    split = [(path, scope, cover) for path, scope, cover in rows if cover.check != scope]
    assert {path for path, _scope, _cover in split} == {
        "src/probos/agents/shell_command.py", "src/probos/agents/red_team.py", "src/probos/execution/isolation.py",
        "src/probos/cognitive/builder.py",  # AD-1346 M3e2b
    }
    nested: list[tuple[str, str]] = []
    for path, scope, cover in split:
        tree = ast.parse(src_sources()[path], filename=path)
        chain = (cover.check, *cover.via, scope)  # AD-1346 M3e2a: each link, in call order
        for index in range(1, len(chain)):
            caller, callee = chain[index - 1], chain[index]
            if callee.startswith(f"{caller}."):  # AD-1346 M3e2b: a nested function's name is local to the one that defines it
                nested.append((path, callee))
                continue
            assert references_outside(tree, callee.rsplit(".", 1)[-1], (caller, callee)) == [], (path, callee)
    assert nested == [("src/probos/cognitive/builder.py", "_run_targeted_tests._sync_run")]  # AD-1346 M3e2b
```

**M1-20** (`tests/test_ad1346_admission_service.py`)

SEARCH:
```
- T16 outside the package the service is named only by ``runtime.py``, ``startup/shutdown.py``, ``startup/finalize.py``
      (which hands it to the Ward Room router and the crew session finalizer) and twelve shadowed-site files, which read
      it from a runtime or take it in a constructor; the package is imported only by ``runtime.py``, the fourteen
      shadowed-site files and, from AD-1346 M3d3a, the model gateway's module ``cognitive/llm_client.py``; the only
      routers that do either are the three whose routes AD-1346 M3c2 shadows, and none of them serves a route #1604
      property 11 keeps ungated.
```
REPLACE:
```
- T16 outside the package, the files whose text names ``admission_service`` and those that import ``probos.admission``
      are the two sets the test lists; the routers among them are the three whose routes AD-1346 M3c2 shadows and,
      from AD-1346 M3e2b, ``routers/build.py``, and none of them serves a route #1604 property 11 keeps ungated.
```

**M1-21** (`tests/test_ad1346_admission_service.py`)

SEARCH:
```
    imports the package.
    The only routers that name the service or import the package are the three whose routes M3c2
    shadows, and none of them is a module of #1604 property 11's routes, which are never admission-gated."""
```
REPLACE:
```
    imports the package.
    From AD-1346 M3e2b ``cognitive/builder.py`` takes it as ``execute_approved_build``'s ``admission_service`` and
    imports the package; ``routers/build.py`` and ``build_pipeline.py`` read it from their runtime and pass it to the
    executor, and ``build_dispatcher.py`` passes the service ``runtime.py`` hands it through ``set_admission``.
    The routers that name the service or import the package are the three whose routes M3c2 shadows and, from AD-1346
    M3e2b, ``routers/build.py``, and none of them is a module of #1604 property 11's routes, which are never
    admission-gated."""
```

**M1-22** (`tests/test_ad1346_admission_service.py`)

SEARCH:
```
        "probos/agents/code_runner.py", "probos/execution/isolation.py", "probos/tools/code_execution_tool.py",  # AD-1346 M3e2a
    }, sorted(named)
```
REPLACE:
```
        "probos/agents/code_runner.py", "probos/execution/isolation.py", "probos/tools/code_execution_tool.py",  # AD-1346 M3e2a
        "probos/build_dispatcher.py", "probos/build_pipeline.py", "probos/cognitive/builder.py", "probos/routers/build.py",  # AD-1346 M3e2b
    }, sorted(named)
```

**M1-23** (`tests/test_ad1346_admission_service.py`)

SEARCH:
```
        "probos/cognitive/dependency_resolver.py", "probos/execution/isolation.py",  # AD-1346 M3e2a
    }, sorted(importers)
```
REPLACE:
```
        "probos/cognitive/dependency_resolver.py", "probos/execution/isolation.py",  # AD-1346 M3e2a
        "probos/cognitive/builder.py",  # AD-1346 M3e2b
    }, sorted(importers)
```

**M1-24** (`tests/test_ad1346_admission_service.py`)

SEARCH:
```
    assert routes == {"probos/routers/agent_actions.py", "probos/routers/agents.py", "probos/routers/thread_fanout.py"}, sorted(routes)
```
REPLACE:
```
    assert routes == {
        "probos/routers/agent_actions.py", "probos/routers/agents.py", "probos/routers/thread_fanout.py",
        "probos/routers/build.py",  # AD-1346 M3e2b: the resolve route hands it to the executor
    }, sorted(routes)
```

### 7.2 M2 new file: `tests/test_ad1346_admission_build_test_sink.py`

```python
"""AD-1346 M3e2b (#1604): the subprocess sink of the builder's targeted tests of an approved build, and its wiring.

- BT1  by AST: ``src`` holds three calls by the executor's two names (``execute_approved_build`` in the
       resolve route's ``_execute_build`` and in ``BuildDispatcher._execute_build``, ``_legacy_execute_approved_build`` in
       ``BuildPipeline.execute_approved_build``), each passing ``admission_service`` as ``_EXECUTOR_CALLS`` records,
       and ``ProbOSRuntime.start`` calls ``self.build_dispatcher.set_admission(self.admission_service)``.
- BT2  the production hand-off: after ``ProbOSRuntime.start`` with ``admission.shadow_enabled`` true, the resolve route
       on that runtime, its build dispatcher and its build pipeline each hand the executor the runtime's service; the
       executor is replaced in each.
- BT3  #1604 property 1's crossing test at the new sink: the resolve route over a runtime double holding the service runs
       the real executor; its targeted-test check counts ``ticket_missing`` outside any hold, ``ticket_live`` inside a
       hold the test makes and ``ticket_revoked`` after a Captain's stop, and each run emits the same event types.
- BT4  #1604 property 12 at the new sink: the executor answers the same with the service and without it, with nothing
       carried, under a live ticket and after a Captain's stop; with ``run_tests`` false it checks nothing.

BT3 and BT4 answer each ``subprocess.run`` call (git's with ``main``, every other with a pass), make
``asyncio.create_subprocess_exec`` return a process that already ended with exit 1, and make ``subprocess.Popen`` and
``asyncio.create_subprocess_shell`` recorders that raise ``OSError``; each asserts that the raising recorders saw no
call and that each exec call was git's. BT2 boots a real runtime, as ``tests/test_bf904b_sealed_core_observation.py``'s
S7 does, and replaces none of those four.
"""

from __future__ import annotations

import ast
import asyncio
import shutil
import subprocess
import unicodedata
from collections.abc import AsyncIterator, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from probos.admission import AdmissionService
from probos.admission.tickets import TicketRegistry
from probos.agent_stop import AgentStopService
from probos.api_models import BuildResolveRequest
from probos.cognitive.builder import BuildFailureReport, BuildResult, BuildSpec, execute_approved_build
from probos.cognitive.copilot_adapter import CopilotBuilderAdapter
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.events import EventType
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.worktree_manager import WorktreeInfo, WorktreeManager
from tests.fixtures.ad1343_seam_census import calls, function
from tests.fixtures.ad1346_effect_census import src_sources

INSTANCE_ID = "ad1346-m3e2b-ship"
VESSEL_NAME = "Ad1346m3e2b"
AGENT_A = "ad1346-m3e2b-agent-a"
BUILD_ID = "ad1346m3e2b"
WIDGET = "src/probos/widget.py"
_CHANGES: tuple[dict[str, str], ...] = ({"path": WIDGET, "mode": "create", "content": "w = 1\n"},)
_EXECUTOR_NAMES = ("execute_approved_build", "_legacy_execute_approved_build")
#: (file, function) -> (the executor name it calls, its ``admission_service`` keyword as ``ast.unparse`` renders it).
_EXECUTOR_CALLS: dict[tuple[str, str], tuple[str, str]] = {
    ("src/probos/routers/build.py", "_execute_build"): ("execute_approved_build", "getattr(rt, 'admission_service', None)"),
    ("src/probos/build_dispatcher.py", "BuildDispatcher._execute_build"): ("execute_approved_build", "self._admission"),
    ("src/probos/build_pipeline.py", "BuildPipeline.execute_approved_build"): (
        "_legacy_execute_approved_build", "getattr(self._runtime, 'admission_service', None)",
    ),
}


class _Clock:
    """A fixed clock: no test in this file moves it."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class _Finished:
    """What the replaced exec constructor returns: a process that already ended with exit 1 and no output."""

    returncode = 1

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


class _Launches:
    """What the replaced launchers saw: each non-git ``subprocess.run`` argv, each exec call, and each call of a raising one."""

    def __init__(self) -> None:
        self.tests: list[list[str]] = []
        self.execs: list[tuple[Any, ...]] = []
        self.refused: list[tuple[Any, ...]] = []


@pytest_asyncio.fixture
async def identity_registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def identities(tmp_path: Path, identity_registry: AgentIdentityRegistry) -> IdentityService:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "surgeon.yaml").write_text("callsign: Meridian\n", encoding="utf-8")
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(AgentRegistry())
    return IdentityService(identity_registry, callsigns)


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest.fixture
def tickets(stops: AgentStopService) -> TicketRegistry:
    return TicketRegistry(stops, max_depth=1, clock=_Clock())


def _route() -> Any:
    """``probos.routers.build``; it takes its failure cache from ``probos.api``, so that module loads first."""
    import probos.api  # noqa: F401
    from probos.routers import build as build_router

    return build_router


def _spec() -> BuildSpec:
    return BuildSpec(title="ad1346 m3e2b", description="d")


def _changes() -> list[dict[str, str]]:
    return [dict(change) for change in _CHANGES]


def _seed(work: Path) -> str:
    """A fresh tree at ``work`` holding the one test file the change maps to (``tests/test_widget.py``)."""
    shutil.rmtree(work, ignore_errors=True)
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_widget.py").write_text("def test_widget():\n    pass\n", encoding="utf-8")
    return str(work)


def _cached(work_dir: str) -> dict[str, Any]:
    """A failed build in the resolve route's cache, with the four keys ``resolve_build`` reads."""
    return {"file_changes": _changes(), "spec": _spec(), "work_dir": work_dir, "report": BuildFailureReport()}


def _handed(executor: AsyncMock) -> object:
    assert executor.await_args is not None, "premise: the caller reached the executor"
    return executor.await_args.kwargs["admission_service"]


def _no_launch(monkeypatch: pytest.MonkeyPatch) -> _Launches:
    """Answer git's ``subprocess.run`` with ``main`` and record and pass every other call; the exec constructor
    answers a finished process; ``subprocess.Popen`` and the shell constructor raise."""
    seen = _Launches()

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, stdout=b"main\n", stderr=b"")
        seen.tests.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=b"1 passed\n", stderr=b"")

    async def exec_(*args: Any, **kwargs: Any) -> _Finished:
        seen.execs.append(args)
        return _Finished()

    def popen(*args: Any, **kwargs: Any) -> Any:
        seen.refused.append(args)
        raise OSError("ad1346-m3e2b: no process is started")

    async def shell(*args: Any, **kwargs: Any) -> Any:
        seen.refused.append(args)
        raise OSError("ad1346-m3e2b: no process is started")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", exec_)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", shell)
    return seen


def test_the_three_executor_calls_pass_their_service_and_the_runtime_hands_the_dispatcher_its_own() -> None:
    """BT1 (D187)."""
    found = sorted(
        (rel, name)
        for rel, source in src_sources().items() if "execute_approved_build" in unicodedata.normalize("NFKC", source)
        for node in ast.walk(ast.parse(source, filename=rel))
        for name in _EXECUTOR_NAMES if calls(name)(node)
    )
    assert found == sorted((rel, callee) for (rel, _qualname), (callee, _service) in _EXECUTOR_CALLS.items()), found
    for (rel, qualname), (callee, service) in _EXECUTOR_CALLS.items():
        (call,) = [node for node in ast.walk(function(rel, qualname)) if calls(callee)(node)]
        keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords}
        assert keywords.get("admission_service") == service, (rel, qualname, keywords)
    start = function("src/probos/runtime.py", "ProbOSRuntime.start")
    handed = {ast.unparse(node) for node in ast.walk(start) if calls("set_admission")(node)}
    assert "self.build_dispatcher.set_admission(self.admission_service)" in handed, sorted(handed)


async def test_a_booted_runtime_hands_its_service_to_the_resolve_route_the_dispatcher_and_the_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BT2 (D187, the production hand-off; kills EQ-3 to EQ-6)."""
    config = SystemConfig()
    config.admission.shadow_enabled = True
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await asyncio.wait_for(runtime.start(), timeout=600)
    try:
        service = runtime.admission_service
        assert type(service) is AdmissionService, "premise: the boot built the shadow service"
        stopped = BuildResult(success=False, spec=_spec(), error="ad1346-m3e2b: stop after the executor")
        handed: dict[str, object] = {}

        build_router = _route()
        monkeypatch.setattr(build_router, "_pending_failures", {BUILD_ID: _cached(str(tmp_path / "route"))})
        scheduled: list[Coroutine[Any, Any, None]] = []
        request = BuildResolveRequest(build_id=BUILD_ID, resolution="retry_targeted")
        with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
            await build_router.resolve_build(request, runtime=runtime, track_task=lambda coro, name=None: scheduled.append(coro))
            await asyncio.wait_for(scheduled[0], timeout=120)
        handed["route"] = _handed(executor)

        dispatcher = runtime.build_dispatcher
        build = runtime.build_queue.enqueue(BuildSpec(title="ad1346 m3e2b dispatch", description="d"))
        runtime.build_queue.update_status(build.id, "dispatched")
        worktrees = MagicMock(spec=WorktreeManager)
        worktrees.create = AsyncMock(return_value=WorktreeInfo(
            path=str(tmp_path / "wt"), branch=f"builder-{build.id[:8]}", build_id=build.id, created_at=0.0,
        ))
        monkeypatch.setattr(dispatcher, "_worktree_mgr", worktrees)
        generated = MagicMock()
        generated.success = True
        generated.file_blocks = _changes()
        generated.error = ""
        adapter = MagicMock(spec=CopilotBuilderAdapter)
        adapter.start = AsyncMock()
        adapter.stop = AsyncMock()
        adapter.execute = AsyncMock(return_value=generated)
        with patch("probos.build_dispatcher._SDK_AVAILABLE", True), \
             patch("probos.build_dispatcher.CopilotBuilderAdapter", return_value=adapter) as adapter_cls, \
             patch("probos.build_dispatcher.repository_identity", new_callable=AsyncMock, return_value=str(tmp_path / "wt" / ".git")), \
             patch("probos.build_dispatcher.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
            adapter_cls.is_available.return_value = True
            await asyncio.wait_for(dispatcher._execute_build(build), timeout=120)
        handed["dispatcher"] = _handed(executor)

        with patch("probos.cognitive.builder.execute_approved_build", new_callable=AsyncMock, return_value=stopped) as executor:
            assert await runtime.build_pipeline.execute_approved_build(_changes(), _spec(), str(tmp_path / "pipe")) is stopped
        handed["pipeline"] = _handed(executor)
        assert handed == dict.fromkeys(("route", "dispatcher", "pipeline"), service), handed
    finally:
        await asyncio.wait_for(runtime.stop(), timeout=600)


async def test_the_resolve_routes_targeted_tests_count_missing_outside_a_hold_then_live_and_revoked(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """BT3 (#1604 property 1, the crossing test at the targeted-test sink; kills EQ-2): no build entry holds a ticket
    (register R86), so the hold here is the test's. The check presents no principal (D188)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    seen = _no_launch(monkeypatch)
    build_router = _route()
    cache: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(build_router, "_pending_failures", cache)
    events: list[tuple[Any, dict[str, Any]]] = []
    runtime = SimpleNamespace(admission_service=service, emit_event=lambda kind, data: events.append((kind, data)))
    work = tmp_path / "work"

    async def resolve() -> list[Any]:
        cache[BUILD_ID] = _cached(_seed(work))
        scheduled: list[Coroutine[Any, Any, None]] = []
        request = BuildResolveRequest(build_id=BUILD_ID, resolution="retry_targeted")
        answer = await build_router.resolve_build(request, runtime=runtime, track_task=lambda coro, name=None: scheduled.append(coro))
        assert answer == {"status": "ok", "resolution": "retry_targeted", "build_id": BUILD_ID}
        start = len(events)
        await asyncio.wait_for(scheduled[0], timeout=120)
        return [kind for kind, _data in events[start:]]

    outside = await resolve()
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        live = await resolve()
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e2b: the Captain stops a run in flight")
        revoked = await resolve()
    finally:
        hold.end()
    assert outside == live == revoked and outside[-1] in (EventType.BUILD_SUCCESS, EventType.BUILD_FAILURE), outside
    assert tickets.tally() == {
        ("subprocess", "ticket_missing"): 1, ("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 1,
        ("subprocess", "ticket_revoked"): 1,
    }
    assert len(seen.tests) == 3 and seen.refused == [] and service.failures == 0
    assert all(args[0] == "git" for args in seen.execs), seen.execs


async def test_with_and_without_the_service_an_approved_build_answers_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """BT4 (#1604 property 12 at the targeted-test sink; kills EQ-1)."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    seen = _no_launch(monkeypatch)
    work = tmp_path / "work"

    async def answer(held: object, *, run_tests: bool = True) -> BuildResult:
        build = execute_approved_build(_changes(), _spec(), _seed(work), run_tests=run_tests, admission_service=held)
        return await asyncio.wait_for(build, timeout=120)

    first = (await answer(service), await answer(None))
    hold = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    try:
        second = (await answer(service), await answer(None))
        await stops.issue_stop(AGENT_A, reason="ad1346-m3e2b: the golden test's stop")
        third = (await answer(service), await answer(None))
    finally:
        hold.end()
    await answer(service, run_tests=False)
    assert first[0] == first[1] == second[0] == second[1] == third[0] == third[1]
    assert first[0].metadata.get("targeted_tests") == "passed", "premise: the targeted tests ran and passed"
    assert tickets.tally() == {
        ("subprocess", "ticket_missing"): 1, ("issue", "ticket_issued"): 1, ("subprocess", "ticket_live"): 1,
        ("subprocess", "ticket_revoked"): 1,
    }, "one check for each build with the service and its tests on, none without the service or with its tests off"
    assert len(seen.tests) == 6 and seen.refused == [] and service.failures == 0
    assert all(args[0] == "git" for args in seen.execs), seen.execs
```

## 8. Tracking (M3's commit)

**Date rule.** If M3 is committed on a local date other than 2026-10-31, the Builder substitutes the committing machine's local date for `2026-10-31` in exactly two strings, both new: the paragraph head `**AD-1346 (2026-10-31), #1604 M3e2b -- ` in M3-01's REPLACE, and the heading `### AD-1346 M3e2b -- the builder's targeted-test subprocess sink and the census's last pending launch (2026-10-31, #1604)` in M3-02's REPLACE. Substitute before committing. The machine's local time is UTC-6, so its date changes at 06:00Z. M3-01's SEARCH is M3e2a's head as merged; if M3e2a's own date rule gave it another date, use that date in the SEARCH. No other deviation is permitted.

Then regenerate the ledger with `python -P scripts/gen_ad_ledger.py` (write mode) and commit both files as the tool writes them.

**Where the entries land.** M3-01 puts the new paragraph between `# ProbOS Progress` and M3e2a's paragraph (`PROGRESS.md:3` on `34fce0da`). M3-02 puts the entry directly above `### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)` (`DECISIONS.md:1102` on `34fce0da`), the heading that follows M3e2a's entry (`:1087`), so the AD-1346 entries run oldest first. Neither new head carries a status keyword of `scripts/gen_ad_ledger.py:126-132` in its first 120 characters (`:139`).

**M3-01** (`PROGRESS.md`)

SEARCH:
```
# ProbOS Progress

**AD-1346 (2026-10-31), #1604 M3e2a -- 
```
REPLACE:
```
# ProbOS Progress

**AD-1346 (2026-10-31), #1604 M3e2b -- the builder's targeted-test subprocess sink.** `execute_approved_build` gains a shadow sink check (`check_at`) before each attempt's targeted test run, with a new `admission_service` keyword: the resolve route and the build pipeline pass their runtime's service, and the build dispatcher passes the service `ProbOSRuntime.start` hands it through `set_admission`; nothing is refused. The census (`tests/fixtures/ad1346_effect_census.py`) has no pending launch: 12 sink launches in 8 rows, 19 system, 5 command-line and 3 unreached. A new test file boots a runtime to check each caller's hand-off, and drives the resolve route and the executor with `subprocess.run`, `subprocess.Popen` and asyncio's two subprocess constructors replaced. The contract is `prompts/ad-1346-m3e2b-build-test-sink.md`.

**AD-1346 (2026-10-31), #1604 M3e2a -- 
```

**M3-02** (`DECISIONS.md`)

SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```
### AD-1346 M3e2b -- the builder's targeted-test subprocess sink and the census's last pending launch (2026-10-31, #1604)

AD-1346 M3e2b is the second part of D160's M3e2. It adds the shadow subprocess sink check to the executor of an approved build, before each attempt's targeted test run, and hands it the service from its three src calls. The subprocess census has no pending launch. It advances #1604 property 1 for the subprocess class and property 12 at the new sink. The contract is `prompts/ad-1346-m3e2b-build-test-sink.md`.

- *D185 (the classification).* A sink: the targeted run executes test files a model wrote. Rejected: `System`, which is for fixed verbs on data.
- *D186 (the place).* In `execute_approved_build`, in the awaiting task, before each attempt's `_run_targeted_tests` call. Rejected: a keyword on `_run_targeted_tests`, which twelve of its test replacements do not accept.
- *D187 (the plumbing).* A keyword on the executor: the resolve route and the pipeline read their runtime's service, and the runtime hands the boot-built dispatcher its service with `set_admission`. Rejected: the executor's `runtime` parameter, which the route and the dispatcher do not pass.
- *D188 (the presented id).* None.
- *D189 (the carrier).* No build entry holds a ticket; M3e5 decides the build issue point.
- *D190 (the census).* The pending row becomes a sink row through `_run_targeted_tests`; EC4 does not search a nested link.
- *D192.* No new cost measurement (D169); no config; no class gains a size trigger.
- *Tests.* One new file (BT1 to BT4); EC2 to EC4 and T16 are updated.
- *Residual, accepted.* Register R84 to R89 of the contract.
- *Reversal.* Revert the M3e2b commits. The statement, the keyword, `set_admission` and the row go; findings a vessel already wrote under `subprocess` stay in `ticket_findings` and the rings, which M3d3b1's `prune` and ring trims bound.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

## 9. What this does NOT change

- `src/probos/admission/*` code (only three docstring passages change); `check_at`, `check_ticket`, `hold`, the schema and every persisted key.
- `_run_targeted_tests`, `_run_git`, `_run_tests`, `_is_dirty_working_tree` and `_map_source_to_tests`; every launch's argv, environment and return path.
- `startup/structural_services.py`, `api.py`, `build_queue.py`, `worktree_manager.py`, `config.py`, `config/system.yaml`.
- BF-892's inventories and floor; `docs/development/architecture-baseline.yaml`; `docs/development/store-baseline.yaml`.
- The other seven sink rows, the system, command-line and unreached rows.
- The egress and store-write classes (M3e3, M3e4); the build issue point (M3e5).

## 10. Mutation rows (one campaign of record on the M2 tree, after an unmutated baseline passes)

`--tests`: every row runs against `tests/test_ad1346_admission_build_test_sink.py tests/test_ad1346_admission_effect_census.py`. No two rows mutate the same line. Each Line is a stripped line that occurs once in its file on M2's tree (Builder: confirm with `grep -c -F` before the campaign; a count other than 1 is a hard stop for the Architect).

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| EQ-1 | M1 | `src/probos/cognitive/builder.py` | `check_at(admission_service, effect=EFFECT_SUBPROCESS, presented_id=None)  # AD-1346 M3e2b: the targeted-test sink, in shadow, in the awaiting task before each attempt's run; it blocks nothing (D188: no principal)` | `pass` | `test_with_and_without_the_service_an_approved_build_answers_identically` |
| EQ-2 | M1 | `src/probos/routers/build.py` | `admission_service=getattr(rt, "admission_service", None),  # AD-1346 M3e2b: the targeted-test sink's service; None checks nothing` | `admission_service=None,` | `test_the_resolve_routes_targeted_tests_count_missing_outside_a_hold_then_live_and_revoked` |
| EQ-3 | M1 | `src/probos/build_dispatcher.py` | `admission_service=self._admission,  # AD-1346 M3e2b: the service ProbOSRuntime.start hands the dispatcher; None checks nothing` | `admission_service=None,` | `test_a_booted_runtime_hands_its_service_to_the_resolve_route_the_dispatcher_and_the_pipeline` |
| EQ-4 | M1 | `src/probos/build_pipeline.py` | `admission_service=getattr(self._runtime, "admission_service", None),  # AD-1346 M3e2b: the targeted-test sink's service; None checks nothing` | `admission_service=None,` | `test_a_booted_runtime_hands_its_service_to_the_resolve_route_the_dispatcher_and_the_pipeline` |
| EQ-5 | M1 | `src/probos/runtime.py` | `self.build_dispatcher.set_admission(self.admission_service)` | `pass` | `test_a_booted_runtime_hands_its_service_to_the_resolve_route_the_dispatcher_and_the_pipeline` |
| EQ-6 | M1 | `src/probos/build_dispatcher.py` | `self._admission = service` | `self._admission = None` | `test_a_booted_runtime_hands_its_service_to_the_resolve_route_the_dispatcher_and_the_pipeline` |
| EQ-7 | M1 | `tests/test_ad1346_admission_effect_census.py` | `if callee.startswith(f"{caller}."):  # AD-1346 M3e2b: a nested function's name is local to the one that defines it` | `if True:` | `test_the_references_along_a_sinks_chain` |

**Pinned with no row:**
- the check's presented id changed to a literal (EC3's keyword equality);
- the check moved above `if run_tests and ...` (BT4's `run_tests=False` build, outside the hold, adds a `ticket_missing`);
- the check moved after the `_run_targeted_tests` call (EC3's `call.lineno < before`);
- the row's `via` emptied (EC3's `min()` over no reference to `_sync_run` in `execute_approved_build` raises `ValueError`);
- a fourth `src` call named `execute_approved_build` or `_legacy_execute_approved_build` (BT1).

**Expected to survive, among them:**
- the check moved above the `for` loop: each build in BT3 and BT4 runs one attempt;
- `BuildDispatcher._admission`'s class default changed to another non-service value: `check_at` passes over anything but an exact `AdmissionService`.

## 11. Verified Against Codebase (2026-10-31, read on `34fce0da`, tree `3f97cf46`)

```
git log --oneline -5           -> 34fce0da (M3e2a oracle trk), 663ee329 (M2), 36d681eb (M1), a7a08c23 (contract), 9f78d3ec (M3e1 merge)
git rev-parse HEAD HEAD^{tree} -> 34fce0dac1ec6e756de331cd8e5ec52cb9cb3792, 3f97cf467593a824f42a8f20b3efe55e1dae56af
Read tests/fixtures/ad1346_effect_census.py (whole): :11-17 coverage list; :41 SERVICE_EXPR; :51 EFFECT_CLASSES subprocess; :59-87 Sink..Unreached; :92-93 _COMPONENT_SERVICE; :108-109 Pending row; :158-160 subprocess_sink_functions; :175-191 references_outside
Read tests/test_ad1346_admission_effect_census.py :1-256: :11-18 EC2-EC4 bullets; :202-213 EC2; :216-239 EC3 (:226 forms, :231-239 before); :242-254 EC4; :257-279 EC5-EC7 (:262 presented == set(); :277 keys only)
Read src/probos/cognitive/builder.py :1-53, :112-200, :1595-1680, :1804-1822, :1984-2047, :2927-3000, :3050-3087, :3171-3343, :3520-3594
  :22 typing import; :115-122 BuildSpec; :126-145 BuildResult; :149-178 BuildFailureReport; :1607/:1625 and :2903/:2923 other _sync_run; :1638-1641 symbolic-ref; :1673-1679 branch create
  :2961 _run_targeted_tests; :2975-2976 no-tests return; :2980 _sync_run; :2982 model-authored; :2984 launch; :2998-2999 executor
  :3244 execute_approved_build; :3249 max_fix_attempts; :3253 runtime; :3256 enforce_sealed_core; :3272-3275 docstring; :3343 pre_flight; :3552 test gate; :3562 loop; :3563-3566 anchor and call
Grep builder.py "runtime" -> :3176-3177, :3274-3275, :3343-3345, :3878-3881 (the runtime-only behaviours)
Grep builder.py "_sync_run" -> :1607, :1625, :2903, :2923, :2980, :2999
Read src/probos/routers/build.py :1-191, :370-494: :24 failure cache from api; :50-64 submit; :67-95 approve refuses; :98-190 resolve (:111-113, :126 keys; :164-167, :183-186 track_task); :417 _execute_build; :431 try; :441-449 call; :474-480 cache; :487 except
Grep src/probos/routers/deps.py -> :15-17 get_runtime, :34-36 get_task_tracker
Read src/probos/api.py :216-231 (_track_task: asyncio.create_task at :224)
Read src/probos/build_dispatcher.py :1-374; Grep defs -> :37 class; 13 direct methods (:40 to :416); wc -l -> 428
  :40-66 __init__; :79-82 enforce_sealed_core; :89 loop task; :114 sleep; :138 create_task; :159 _execute_build; :174 try; :224-232 call; :299 except Exception; :362-368 on_build_complete
Read src/probos/build_pipeline.py (whole): :36-39 Ship's Computer service, no agent identity; :53-54; :56-67 signature; :89-100 legacy call
Read src/probos/startup/structural_services.py :1-175: :126-131 BuildDispatcher(...), :132 start
Grep src/probos/runtime.py -> :1243 admission_service None; :2926 shadow_enabled; :2966 service built; :3097-3098 resolver set_admission; :3290-3308 init_structural_services; :3327-3329 anchor; :3435, :3437 set_admission; :3730 BuildPipeline(runtime=self); :2786 start, :3790 next def
Read src/probos/runtime.py :2203-2216 _on_build_complete (emits BUILD_QUEUE_ITEM)
Read src/probos/admission/seam.py (whole): :15-19; :49-53 check_at
Read src/probos/admission/service.py :24-31, :216-270: :27, :221-222 counts; :230 CURRENT_TICKET.get(); :250 no registry; :258 offer_ticket
Read src/probos/cognitive/dependency_resolver.py :74-83 (the set_admission precedent)
Read tests/test_ad1346_admission_service.py :26-35, :577-641
Read tests/test_ad1346_admission_ticket_sinks.py :239-275, :495-527 (SK7; the boot config precedent)
Read tests/test_ad1346_admission_tickets.py :440-465 (K15); Grep K5 :255-272; I11 :582-589; identity_service :468-481
Read tests/test_ad1346_admission_subprocess_plumbing.py (whole)
Read tests/test_bf904b_sealed_core_observation.py :255-346 (S5 to S8), :161-166; Grep :140-154
Read tests/test_bf896_executor_identity_and_blocks.py :698-715; tests/test_ad476_specialized_builders.py :168-185; tests/test_ad521_swe_pipeline_separation.py :44-60, :118-158
Read tests/test_builder_agent.py :2170-2238; tests/test_bf904b_fix_loop_state.py :1-160; tests/test_builder_api.py :320-411
Read scripts/check_architecture_principles.py :548-592; Grep :187-188, :256
Read scripts/gen_ad_ledger.py :124-141
Grep src/probos/cognitive/builder_paths.py :447-472 (operator_checkout_refusal)
Grep src/probos/api_models.py :137-140 (BuildResolveRequest)
Grep src/probos/build_queue.py :39-53 (QueuedBuild fields)
Bash head PROGRESS.md -> :3 M3e2a head (2026-10-31); Grep DECISIONS.md -> :1070 M3e1, :1087 M3e2a, :1102 the anchor heading
Grep counts of SEARCH first lines -> each once in its file (builder.py :22, :3256, :3275, :3563; routers/build.py :447, :448; build_dispatcher.py :82, :230, :231; build_pipeline.py :97, :98, :99; runtime.py :3328)
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py -> CEILING AD-1355 (GitHub issue titles); no number allocated
```

## Absence Verified (2026-10-31, run on `34fce0da`)

```
CLAIM: no file on the build entries' paths holds a ticket
RUN:   Grep "hold_at\(|\.hold\(|CURRENT_TICKET" src/probos (files)
FOUND: cognitive/cognitive_agent.py, cognitive/agentic_dispatch.py, agents/shell_command.py, agents/red_team.py, admission/seam.py, admission/service.py, admission/carrier.py
HOLDS: yes (not builder.py, build_dispatcher.py, build_pipeline.py, routers/build.py or api.py)

CLAIM: src calls the executor at three sites
RUN:   Grep "execute_approved_build" src
FOUND: calls at build_dispatcher.py:224, routers/build.py:441, build_pipeline.py:89 (_legacy_execute_approved_build); the other hits are the defs (builder.py:3244, build_pipeline.py:56), imports (build_dispatcher.py:22, build_pipeline.py:81, routers/build.py:429), docstrings and comments
HOLDS: yes

CLAIM: no src code calls BuildPipeline.execute_approved_build
RUN:   Grep "\.execute_approved_build\b|build_pipeline\b" src
FOUND: builder_paths.py:288, :412 (path strings); runtime.py:153, :1350, :3730; swe_harness/native_builder.py:187 (imports BuildPipeline for parse_file_blocks, :189)
HOLDS: yes

CLAIM: src calls the router's _execute_build only in resolve_build
RUN:   Grep "_execute_build\(" src
FOUND: build_dispatcher.py:138, :159 (the dispatcher's own method); routers/build.py:165, :184 (resolve_build), :417 (def)
HOLDS: yes

CLAIM: no src code assigns QueuedBuild.builder_id
RUN:   Grep "builder_id" src
FOUND: build_queue.py:50 (the field); routers/build.py:266, :293 and runtime.py:2216 (reads)
HOLDS: yes

CLAIM: each test replacement of execute_approved_build accepts a new keyword
RUN:   Grep "execute_approved_build[\"']|\"execute_approved_build\"|execute_approved_build =|\.execute_approved_build\b" tests
FOUND: AsyncMock patches: test_bf904b_sealed_core_observation.py:309, test_builder_api.py:168, :347, :393, test_build_dispatcher.py:128, :181; functions taking **kwargs: test_bf896_dispatcher_confinement_seam.py:825, :851, :992, :1174, :1219; the other hits are a census row, signature tests, a docstring, log-record tuples and a real pipeline call
HOLDS: yes

CLAIM: among the replacements of _run_targeted_tests, twelve take (work_dir, changed_files, timeout) with no **kwargs (D186)
RUN:   Grep "(async )?def (__call__|_fail_targeted_tests|_passing|_swap_then_pass|targeted|control_targeted|runner|control_runner|mock_run_targeted|fake|tests_that_change_the_file|tests_that_leave_an_alias|tests_then_arm|delete_the_saved_file_once)\(" over tests/test_{bf89*,bf904*,builder_agent,ad1344*}.py
FOUND: test_bf896_executor_identity_and_blocks.py:628, :764, :778; test_bf897_build_pipeline_scale_and_checkout.py:667; test_bf904a_git_hardening.py:235; test_bf904b_fix_loop_state.py:113, :210, :268, :316; test_bf904b_sealed_core_observation.py:127; test_builder_agent.py:2221, :2714
HOLDS: yes

CLAIM: in src and tests, the pending owner M3e2b and the census's Pending row appear only on lines M1 edits, the class, its import and annotations
RUN:   Grep "M3e2b|Pending\b" over {src,tests}/**/*.py
FOUND: fixture :16 (definition, kept), :51 (M1-13), :79, :98 (class, annotation), :108-109 (M1-15); EC :13 (M1-16), :81, :208 (import, kind list), :210, :212 (M1-17); every other hit is another subsystem's word
HOLDS: yes

CLAIM: in src/probos/admission the subprocess-sink counts are on the lines M1 edits
RUN:   Grep "seven|M3e2|subprocess sink" src/probos/admission
FOUND: service.py:27 (M1-10), :222 (M1-11); seam.py:17-18 (M1-12 edits :18); taxonomy.py:25 (the effect's definition, no count)
HOLDS: yes

CLAIM: none of the four executor-call files names admission today
RUN:   Grep "admission" in routers/build.py; Read build_pipeline.py and build_dispatcher.py; Grep "admission" builder.py
FOUND: none
HOLDS: yes
```

## 12. Deterministic gate checks, resolved up front

- `python -P scripts/check_architecture_principles.py --check` exits 0: `BuildDispatcher` holds 14 direct methods (trigger above 15) and a span under 500 (D192); `ProbOSRuntime` keeps the triggers it has.
- `python -P scripts/check_store_registry.py --check` exits 0: no store is added.
- `rg -c "admission_service=" src/probos/routers/build.py src/probos/build_dispatcher.py src/probos/build_pipeline.py` prints each path with `:1`, exit 0.
- `rg -n "set_admission\(self\.admission_service\)" src/probos/runtime.py` prints four lines after M1 (three before), exit 0.
- BF-892's floor is asserted by `tests/test_bf892_spawn_env_guard.py` in M1's gate; EC2 asserts the total of 39.
- M2's collect-only count is 4.

## 13. Prior Art and Blind Spots

- **Internal.** BF-904b's `enforce_sealed_core` is the precedent for D187's shape: a keyword on the executor, given by the route (`routers/build.py:448`), the dispatcher (`build_dispatcher.py:231`) and through the pipeline's runtime, with the dispatcher's value from boot. M3e2a's `DependencyResolver.set_admission` (`cognitive/dependency_resolver.py:77-81` on `34fce0da`) is the precedent for the late-bound dispatcher. M3e1's F1 (`tests/test_ad1346_admission_sink_wiring.py`) is the reason for BT2. `tests/test_bf904b_sealed_core_observation.py` S6 and S7 are BT2's shape.
- **External.** Skipped: ProbOS-specific plumbing with no outside analogue. `docs/research/reference-projects.md` was not examined this session.
- **Blind spots, decided.**
  - The Captain's `commit_override` reruns a build with `run_tests=False` (`routers/build.py:165`): no tests, no check.
  - `/api/build/approve` refuses and executes no build (`routers/build.py:67-95`).
  - Tests call `_run_targeted_tests` directly (`tests/test_bf892_spawn_env.py:80`, `tests/test_bf897_build_pipeline_scale_and_checkout.py:576-618`, `tests/test_bf898_fix_loop_grader_protection.py:908`); in `src` it is reached through `execute_approved_build` (EC4's first link).
  - An attempt with no mapped test is checked and launches nothing (register R84).
  - The dispatcher's loop starts before it is handed the service (register R85).

## 14. Diff Reviewer: properties to verify

1. **No answer changes.** The new `check_at` statement is an expression statement whose value is discarded; `check_at` returns None and raises only what `check_ticket` raises, and the real `check_ticket` lets no `Exception` out (`seam.py:49-53`; `service.py:230-238`). The three calls pass one more keyword; `set_admission` assigns one attribute.
2. **Placement.** The check follows `all_changed_files = written + modified_files` and precedes the `_run_targeted_tests` call, inside `for attempt in range(1 + max_fix_attempts):`, inside `if run_tests and (written or modified_files) and not validation_errors:`.
3. **The wiring.** The route passes `getattr(rt, "admission_service", None)`, the pipeline `getattr(self._runtime, "admission_service", None)`, the dispatcher `self._admission`; `ProbOSRuntime.start` calls `set_admission` only when `self.build_dispatcher is not None`.
4. **The signature.** `admission_service` is the last parameter and defaults to None; the eleven parameters BF-896's test names keep their names, indices and kind.
5. **The census.** The 39 launches split 12/19/5/3/0; the builder's row has `via=("_run_targeted_tests",)`; EC4's one nested link is the builder's.
6. **No launch added** (BF-892's floor 39); no class gains an `srp-size` trigger.
7. **The text scanners pass on the new `src` text:** K5 and K15 (`tests/test_ad1346_admission_tickets.py`), T16, I11 (`tests/test_ad1346_admission_ticket_issue.py`), the helper in `tests/test_ad1346_admission_ticket_sinks.py`, and `tests/test_ad1346_identity_service.py:475`.
8. **BT3's and BT4's launch assertions.** Each asserts that the `subprocess.Popen` and shell recorders saw no call and that each exec call was git's.
9. **Every SEARCH text occurs once**, in pair order, on the merged base.

## 15. Acceptance criteria

- All three milestones' focused gates pass; the broad gate passes once with its receipt.
- The campaign of §10 kills every row by its named test on the M2 tree.
- `rg -n "monkeypatch.setattr\((subprocess|asyncio)," tests/test_ad1346_admission_build_test_sink.py` prints four lines (`"run"`, `"Popen"`, `"create_subprocess_exec"`, `"create_subprocess_shell"`), exit 0.
- `rg -n "data_dir=" tests/test_ad1346_admission_build_test_sink.py` prints three lines, each with `tmp_path`.
- `rg -n "ProbOSRuntime\(" tests/test_ad1346_admission_build_test_sink.py` prints one line (BT2's boot), exit 0. BT2 boots a real runtime under `tmp_path`, as `tests/test_bf904b_sealed_core_observation.py:319-331` does; this contract does not establish which processes or sockets a boot opens.
- `rg -n "os\.environ|getenv|socket" tests/test_ad1346_admission_build_test_sink.py` prints nothing and exits 1.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Corrections to this contract

**A1 (2026-10-31, after the orchestrator's pre-build run).** A1-1 deletes the Status paragraph's parenthetical that called AD-1346 the ceiling. A1-2 makes every line number this contract cites a record of `34fce0da`. A1-3 says BT3 and BT4 follow SP4's and SP5's fixtures and launch replacement. A1-4 replaces §1's sentence on the architecture checker's baseline identity with what its `:256-257` says. A1-5 says BT4 drives the executor alone and names the four launchers BT3 and BT4 replace. A1-6 narrows D186's rejected option to twelve test replacements. A1-7 drops S7 as a precedent for `admission.shadow_enabled`, scopes BT2's construction-path sentence to the dispatcher and the pipeline, and says BT2 calls `resolve_build` with its runtime, not through `Depends(get_runtime)`. A1-8 bounds the check count per `execute_approved_build` call and counts M1-07's line in `BuildDispatcher`'s span. A1-9 restates §5's sentence on the call to `_run_targeted_tests`, and its sentence on what `check_at` raises. A1-10 says SK7 is unchanged instead of citing §6 for it. A1-11 narrows the raise sentence in M1-12's seam docstring line (LANDING). A1-12 to A1-16 narrow the new test file's docstrings: BT1 to calls by the executor's two names, BT3's runtime to a double, the `subprocess.run` answer and `_Launches`' and `_no_launch`'s descriptions to every non-git call, and BT2's launcher sentence to the four named (LANDING). A1-17 narrows the `DECISIONS.md` entry's D186 rejection to twelve test replacements (LANDING). A1-18 scopes §10's fourth-call pin to the executor's two names. A1-19 deletes the EQ-7 `if False:` bullet from the survivors list. A1-20 deletes §12's `Pending` grep. A1-21 says the approve route executes no build. A1-22 and A1-23 restate §14's properties 1 and 8. A1-24 restates R84's verb and bound. A1-25 writes this paragraph and deletes §17's items 1 to 3, which the pre-build run measured.

**A2 (2026-10-31, after M3e2a's merge; the orchestrator's mechanical ripple of M3e2a's review amendments, contract-only apart from four lines of the new-file block).** A2-1 rewrites the head's M3e2a bullet as the merge record, and the Anchors and records bullets name the two pairs A2 moved. A2-2 gives M1-16's SEARCH and REPLACE EC4's module-docstring bullet as M3e2a's amendment A4-5 words it. A2-3 starts M1-19's SEARCH at EC4's docstring as A4-8 leaves it (`"""EC4."""`); its REPLACE docstring is unchanged. A2-4 names EC4's new name, `test_the_references_along_a_sinks_chain`, in EQ-7's Killed-by cell. A2-5 and A2-6 apply M3e2a's treatment of SP3 (its A4-14, A4-15 and A4-17) to BT1 in the new-file block: its module bullet starts "by AST:" and its docstring is `"""BT1 (D187)."""`, since the test checks that the calls and the keyword are in `src`, not their placement, which BT2 executes on a booted runtime; and its prefilter tests the NFKC form of the text (`import unicodedata`), the form Python compares names in. A2-7 writes this paragraph.

**A3 (2026-10-31, after review round 1; the orchestrator's mechanical amendment, contract-only).** A3-1 deletes the clause that `PROGRESS.md` runs newest first from §8's "Where the entries land" paragraph. A3-2 writes this paragraph.

## 17. Claims not yet confirmed

1. The campaign of record on the M2 tree (§10: EQ-1 to EQ-7).
2. `python -P scripts/gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` after M3's regeneration.

## For the register (#1604)

- **R70** (M3e1): resolved for all 11 launches.
- **R76** (M3e2a): resolved by this slice.
- **R84:** the check is made at each attempt, including one whose changed files map to no test file, which launches nothing (`builder.py:2975-2976`); at most `1 + max_fix_attempts` per `execute_approved_build` call.
- **R85:** `init_structural_services` starts the dispatcher's loop (`structural_services.py:132`) before `ProbOSRuntime.start` hands it the service; a build it runs before then passes None. The loop sleeps `poll_interval` (default 5.0 s, `build_dispatcher.py:46`, `:114`) before each poll.
- **R86:** no build entry holds a ticket (D189); with a registry their checks count `ticket_missing`. M3e5 (R37, R38) decides the build issue point for the dispatcher's builds and the resolve route's.
- **R87:** the sink presents no principal (D188), so a principal mismatch there is not recorded; `QueuedBuild.builder_id` is never assigned in src.
- **R88:** `BuildPipeline.execute_approved_build` has no src caller; it passes the service for when one is added (BT2 drives it).
- **R89:** the three callers' service expressions are evaluated before the executor runs, outside `check_at`'s guarantee. The route's and the dispatcher's are inside `try` blocks whose `except Exception` handles a raise (`routers/build.py:431`, `:487`; `build_dispatcher.py:174`, `:299`); the pipeline's is not.
