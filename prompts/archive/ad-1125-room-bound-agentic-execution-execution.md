# AD-1125 Builder Execution - Room-bound agentic execution

**Verdict:** APPROVED FOR BUILDER HANDOFF AFTER ISSUE #1044 BODY AMENDMENT
**Binding specification:** `prompts/ad-1125-room-bound-agentic-execution.md`
**Binding SHA-256:** `de9ba005ab1a5101a50b40519165d89c4b2784362328036afe2256adf9d8e779`
**Parent epic / issue:** #1041 / #1044
**Dependency:** #1043 / AD-1124 is closed and landed
**Next boundary:** #1045 / AD-1126 remains open
**Exact base:** clean `D:\ProbOS` `main` at `31c1b648a91bdf21c27aa577d2d6000c99f61051`
**Exact base subject:** `AD-1124: add durable crew session contract (closes #1043)`
**Numbering:** build AD-1125 only; current ceilings AD-1124 / BF-673
**Mode:** red-first, real substrate, one local commit, no push, no GitHub mutation

## Authority

The binding prompt is authoritative for architecture, issue correction, room/session ownership, exact context/evidence/artifact contracts, terminal mapping, file scope, hashes, acceptance, and AD-1126+ boundaries.

This execution document is authoritative for mutation order, exact test commands, Git/status discipline, three-pass Builder review, diagnostics, closeout, archival, staging, and handback.

Do not implement from this summary alone. If the documents conflict, if the binding hash differs, or if live code differs from the verified base, stop and return to the Architect.

---

## Pre-flight - before any Builder mutation

1. Read in full:
   - `.github/copilot-instructions.md`;
   - `prompts/_TEMPLATE.md`;
   - `prompts/review-criteria.md`;
   - `prompts/ad-1125-room-bound-agentic-execution.md`;
   - this execution document;
   - issue #1044 and parent #1041;
   - issue #1045 for the AD-1126 boundary;
   - `DECISIONS.md` AD-1124;
   - archived AD-1124 binding/execution prompts;
   - every production/reference/test file named by the binding prompt and gates.
2. Verify all three refs equal the exact base:

```powershell
git rev-parse HEAD
git rev-parse origin/main
git ls-remote origin refs/heads/main
git log -1 --pretty=%s
```

Expected subject:

```text
AD-1124: add durable crew session contract (closes #1043)
```

3. `git status --short` must contain exactly:

```text
?? prompts/ad-1125-room-bound-agentic-execution-execution.md
?? prompts/ad-1125-room-bound-agentic-execution.md
```

There must be no staged path, tracked modification/deletion, or other untracked path.
4. Recompute the binding prompt SHA-256 and require exactly:

```text
de9ba005ab1a5101a50b40519165d89c4b2784362328036afe2256adf9d8e779
```

5. Read issue #1044 and require all exact amended markers:

```text
An initialized AD-1124 `crew_session` already owns one exact bound room
```

```text
skip the current verifier and synthesizer after fan-out
```

```text
Token-budget handling in this AD is persistence of the existing AgenticResult stop reason, not a new configuration policy.
```

Read-only verification is allowed. Do not edit, comment, label, close, assign, or otherwise mutate GitHub.
6. Confirm live issue states: #1041 OPEN, #1043 CLOSED, #1044 OPEN, #1045 OPEN.
7. Confirm `PROGRESS.md` and `DECISIONS.md` identify AD-1124 as the top-level ceiling and BF-673 as the BF ceiling. Confirm no AD-1125 implementation/tracker entry has landed.
8. Recompute every existing allowlisted and frozen SHA-256 in the binding prompt. Every value must match.
9. Confirm `tests/test_ad1125_room_bound_execution.py` does not exist.
10. Confirm Python environment is `D:\ProbOS\.venv` on Python 3.12.x.
11. Confirm no background pytest/task owns the shared terminal before starting a gate.

Any mismatch is a hard stop. Do not fetch, pull, merge, rebase, cherry-pick, switch, reset, restore, clean, stash, stage, commit, push, regenerate either prompt, or mutate GitHub.

---

## Exact allowlist

### Builder may modify production

- `src/probos/workforce.py`
- `src/probos/cognitive/agentic_dispatch.py`
- `src/probos/cognitive/crew_executor.py`
- `src/probos/cognitive/crew_orchestrator.py`
- `src/probos/tools/code_execution_tool.py`
- `src/probos/startup/finalize.py`

### Builder may create/modify tests

- `tests/test_ad1125_room_bound_execution.py` - new
- `tests/test_ad859_crew_executor.py` - obsolete assertions/fake signature only; add no test function
- `tests/test_ad925_auto_task_room.py` - obsolete helper/fake signature only; add no test function

### Architect documents - do not edit; move unchanged only at closeout

- `prompts/ad-1125-room-bound-agentic-execution.md`
- `prompts/ad-1125-room-bound-agentic-execution-execution.md`

### Conditional closeout after all gates/reviews

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- prompt destinations under `prompts/archive/`

No other path is authorized.

Frozen means no edit, formatting, import sort, generated churn, or test update. In particular, do not touch config/YAML/runtime, AgenticLoop/tool-call protocol, CrewSession service/contract, verifier, synthesizer, Artifact/Attachment/ChatThread stores, group-chat service, DmReplyPipeline, events, API/UI/desktop, manifests, or any other test.

---

## Red-first execution sequence

### Step 1 - Create the complete AD-1125 test module only

Create `tests/test_ad1125_room_bound_execution.py` and no production edit.

Implement every binding Section 1 test family. The headline flow must use real WorkItem/ChatThread/Artifact/FilesystemAttachment stores, real CrewSessionService, real ToolRegistry/ToolPermissionStore, real WorkItemAgenticExecutor/AgenticLoop/CodeExecutionTool/SubprocessSandbox, real Pydantic config, and a hand-written scripted multi-iteration LLM.

Use hand-written narrow fakes only for agent registry identity, orchestration verifier/synth call recording, deterministic clocks/id factories, and targeted failure injection around a real store. Do not use a mock library at a substrate boundary.

The new test file must contain none of:

```text
MagicMock
AsyncMock
unittest.mock.Mock
unittest.mock.patch
```

Do not weaken the complete test module after red. A test expectation may change only if the binding prompt is revised by the Architect.

### Step 2 - Run and retain the mandatory red

Use this exact headline node name in the new module:

```text
test_real_room_bound_run_python_persists_child_evidence_and_parent_executing
```

Run:

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1125_red_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1125_room_bound_execution.py::test_real_room_bound_run_python_persists_child_evidence_and_parent_executing -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected RED must be attributable to the missing AD-1125 surface, for example:

- child call records `thread_id == ""`;
- no `WorkItemAgenticOutcome.total_tokens` or `.artifact_refs`;
- `artifact_details` lacks authoritative id/hash/thread identity;
- no `metadata["crew_execution"]` / `actual_tokens` / terminal status;
- parent projection conflict or verifier/synth invoked.

Record exact command, node, exception/assertion, and why it proves missing AD-1125 behavior. If it passes, does not collect, or fails for environment/test-shape reasons, stop.

### Step 3 - Implement the store-owned token delta first

Modify only `src/probos/workforce.py`:

1. add keyword-only `actual_tokens_delta: int = 0` to `merge_work_item_metadata`;
2. validate exact non-boolean nonnegative integer and checked cumulative overflow;
3. write the delta in the same row-locked SQL/commit as metadata and optional validated status;
4. keep the zero-delta code path and all existing caller semantics unchanged;
5. add no schema, lock, connection, or public method.

Run only the new store-token tests plus the frozen AD-1124 merge/CAS tests. If an old AD-1124 test needs an edit, stop; production parity is wrong.

### Step 4 - Extend authoritative artifact output and outcome collection

Modify only:

- `src/probos/tools/code_execution_tool.py`;
- `src/probos/cognitive/agentic_dispatch.py`.

Implement binding DD-4/DD-5 exactly:

1. return the seven exact artifact fields from the actual Artifact row;
2. preserve all existing top-level tool output keys and filename list;
3. attach one synchronous raw-result recorder through inherited `add_post_hook`;
4. validate/detach only bounded same-thread `run_python` artifact details;
5. set additive `total_tokens` and `artifact_refs` outcome fields;
6. preserve trace persistence and AgenticLoop behavior.

Run the new artifact/outcome tests and existing AD-545/859a/1066/1074d files.

### Step 5 - Implement room resolution, session start, and terminal child persistence

Modify only `src/probos/cognitive/crew_executor.py`:

1. inject optional CrewSessionService through a type-only import;
2. load the existing parent and children;
3. resolve one room existing-first, with `limit=2` and `asyncio.to_thread` for the synchronous thread store;
4. require the exact existing bound room for a `crew_session`;
5. transition the session to `executing` before any task creation;
6. pass the one room id plus exact two-key bounded extra context to every child;
7. centralize exact evidence construction and row-locked persistence;
8. map all terminal statuses/reasons exactly;
9. persist and return dependency-blocked children;
10. keep cancellation propagation, semaphore bound, and strong task refs.

Update only obsolete fake signatures/assertions in `tests/test_ad859_crew_executor.py` and `tests/test_ad925_auto_task_room.py`. Add no test function there. Replace invalid placeholder trace strings with canonical 64-hex refs only where the new exact evidence validator requires it.

Run the new module plus both modified legacy files before continuing.

### Step 6 - Enforce the AD-1125/1126 orchestrator boundary

Modify only `src/probos/cognitive/crew_orchestrator.py`:

1. classify the existing parent by `work_type` before direct promotion;
2. retain the entire current path for non-session parents;
3. skip direct parent promotion for `crew_session`;
4. assignment and fan-out still run;
5. return the exact partial SynthesisResult after fan-out for a session;
6. do not call verifier/synth or move beyond `executing`.

Run new session-boundary tests and the frozen AD-867/868 tests. Any frozen legacy assertion failure is a blocker; do not edit those files.

### Step 7 - Inject the landed service

Modify only `_wire_crew_orchestrator` in `src/probos/startup/finalize.py`:

1. resolve public `runtime.crew_session_service` after the landed service wirer;
2. pass it to CrewTaskExecutor;
3. do not construct another service;
4. preserve gate false, legacy missing-dependency behavior, and startup ordering.

Run the new wiring tests plus frozen AD-1124/867 runtime tests.

### Step 8 - Run all gates and three Builder reviews

Run Gates 0-4 below verbatim. Report exact count, duration, skips, warnings, and every triage. Complete all three reviews before tracker edits.

---

## Exact test gates

All serial gates use a unique `PROBOS_DATA_DIR`, forced local/offline embeddings, no pytest cache, `-n 0`, per-test timeout 90 seconds, short tracebacks, and `RuntimeWarning` promoted to error. Do not use `-n auto`.

Let `N` be the final exact collected/pass count in `tests/test_ad1125_room_bound_execution.py`. Do not add test functions to either modified legacy module; their base counts stay fixed.

### Gate 0 - AD-1125 module

Expected: exactly `N passed`, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1125_module_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1125_room_bound_execution.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 1 - Directly affected focused surface

Pinned existing baseline: **127 passed**. Expected post-build: exactly `127 + N passed`, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1125_gate1_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1125_room_bound_execution.py tests/test_ad545_agentic_loop.py tests/test_ad859a_agentic_executor.py tests/test_ad1066_code_execution_tool.py tests/test_ad1074d_round_trip_edit.py tests/test_ad859_crew_executor.py tests/test_ad925_auto_task_room.py tests/test_ad867_crew_orchestrator.py tests/test_ad1124_crew_session_contract.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 2 - Remaining direct executor/code-tool callers

Pinned exact baseline: **72 passed / 1 skipped**, no warnings. Expected post-build: exactly the same result.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1125_gate2_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1007_capability_gate.py tests/test_ad1068_use_skill_tool.py tests/test_ad1072_agentic_tools.py tests/test_ad1073_loop_dependency_install.py tests/test_ad993_isolation.py tests/test_ad994_code_runner.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 3 - Crew/workforce/thread/runtime blast

Pinned existing baseline: **349 passed**. Expected post-build: exactly `349 + N passed`, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1125_gate3_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1125_room_bound_execution.py tests/test_ad545_agentic_loop.py tests/test_ad859a_agentic_executor.py tests/test_ad1066_code_execution_tool.py tests/test_ad1074d_round_trip_edit.py tests/test_ad859_crew_executor.py tests/test_ad925_auto_task_room.py tests/test_ad867_crew_orchestrator.py tests/test_ad1124_crew_session_contract.py tests/test_workforce.py tests/test_ad860_crew_verifier.py tests/test_ad861_crew_synth.py tests/test_ad866_dept_verifier.py tests/test_ad868_self_originated_crew.py tests/test_ad791_chat_threads.py tests/test_ad862_crew_tasks_api.py tests/test_runtime.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 4 - Full repository parallel gate

Pinned exact-base result recorded by AD-1124: **19,643 passed / 33 skipped / 0 failed / 455 warnings**.

Expected post-build:

- at least `19,643 + N` passed;
- 33 skips unless independently explained;
- zero failures after serial triage;
- zero warning sourced from an AD-1125 changed/new path;
- no unexplained new warning family;
- aggregate warning variance is accepted only when every extra warning traces to a dependency or HEAD-identical pre-existing source/test.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1125_gate4_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/ -p no:cacheprovider -n 4 --dist=loadfile --timeout=90 -q --tb=short } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

For every Gate 4 failure, rerun the complete failing file serially under the same isolated/offline settings before classification:

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1125_triage_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest <failing-file> -p no:cacheprovider -n 0 --timeout=90 -q --tb=short } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

If it passes serially, classify it as parallel/order/environmental with exact evidence. If it fails serially and points to AD-1125, repair only inside the allowlist and rerun the affected gate. If it fails serially outside the allowlist, hard stop; do not quarantine or patch unrelated code in this AD.

Do not poll a running full gate and do not run another command in the same terminal while it owns pytest. Wait for natural completion or the tool's completion notification.

---

## Required implementation reviews

### Builder Pass 1 - Behavior/spec

Before tracker edits:

1. map every DD and acceptance item to code and named tests;
2. trace durable-session order: load parent -> assign children -> resolve one bound room -> service transition -> spawn children -> persist outcomes -> session-only partial return;
3. prove no child starts before state `executing` and no session reaches verifier/synth;
4. trace legacy parent order and prove it is unchanged through verifier/synth completion;
5. enumerate every terminal mapping, including dependency-blocked returned results and no-unblock behavior;
6. inspect the second real LLM request and prove the actual tool result, artifact id/hash/thread id, and staged-input outcome are present;
7. prove exact context/evidence/artifact allowlists, caps, detachment, and refs-not-blobs;
8. prove cumulative tokens and metadata/status commit together;
9. prove semaphore bound and cancellation propagation/task cleanup.

Verdict must be `APPROVED`; otherwise stop.

### Builder Pass 2 - Verify-first/code

1. re-grep all `WorkItemAgenticExecutor` constructors/callers and state the exact count; verify additive defaults protect every untouched caller;
2. re-grep all `CrewTaskExecutor` constructors/callers and confirm startup injects the landed service once;
3. re-grep `artifact_details` consumers and confirm no string parser or filename inference was added;
4. re-grep `merge_work_item_metadata` callers; confirm zero-delta compatibility and no wrapper Protocol break;
5. inspect every direct WorkItem status write in changed code; only validated merge/transition paths are allowed;
6. inspect the post-hook recorder: it must not mutate/suppress tool results or raise into AgenticLoop;
7. inspect artifact extraction against hostile subclasses/types, scan cap, output cap, same-thread rule, and mutable aliasing;
8. inspect evidence serializer against exact keys/types/bytes and forbidden content;
9. inspect ordinary exceptions versus `CancelledError`; cancellation must not become failed;
10. run editor diagnostics on all changed files and the new test;
11. recompute every frozen hash.

Verdict must be `APPROVED`; otherwise stop.

### Builder Pass 3 - Scope/safety

1. inspect `git diff --name-only`, `--stat`, `--numstat`, and deletion set against the exact allowlist;
2. require empty diffs for every frozen source/test/config/YAML/API/UI path;
3. confirm no schema/DDL, config field, event, runtime attribute, dependency, task runner, ingress, dedup, EventLog, trust, notifier, or HXI addition;
4. confirm no AD-1126 verification/finalization behavior exists;
5. confirm new tests use real substrate and contain no forbidden mock token;
6. confirm the mandatory red record is retained;
7. confirm no GitHub/branch/push mutation occurred;
8. confirm prompt bytes remain exact before archival.

Verdict must be `APPROVED`; otherwise stop.

---

## Diagnostics and source audits

Run editor diagnostics on:

- `src/probos/workforce.py`;
- `src/probos/cognitive/agentic_dispatch.py`;
- `src/probos/cognitive/crew_executor.py`;
- `src/probos/cognitive/crew_orchestrator.py`;
- `src/probos/tools/code_execution_tool.py`;
- `src/probos/startup/finalize.py`;
- `tests/test_ad1125_room_bound_execution.py`;
- `tests/test_ad859_crew_executor.py`;
- `tests/test_ad925_auto_task_room.py`.

Any new error attributable to AD-1125 is a blocker.

Before tracker edits:

```powershell
git status --short
git diff --check
git diff --stat
git diff --numstat
git diff --name-only
git diff --name-only --diff-filter=D
git diff -- src/probos/config.py config/system.yaml src/probos/runtime.py src/probos/cognitive/swe_harness/agentic_loop.py src/probos/cognitive/swe_harness/tool_call.py src/probos/cognitive/crew_session.py src/probos/cognitive/crew_verifier.py src/probos/cognitive/crew_synth.py src/probos/artifacts/__init__.py src/probos/attachments src/probos/threads src/probos/cognitive/dm src/probos/events.py src/probos/protocols.py src/probos/startup/shutdown.py ui desktop
git diff --no-index --check -- NUL prompts/ad-1125-room-bound-agentic-execution.md
git diff --no-index --check -- NUL prompts/ad-1125-room-bound-agentic-execution-execution.md
```

The frozen-path diff must be empty. For `--no-index`, exit code 1 is expected because a non-empty file differs from NUL; emitted whitespace diagnostics are not allowed.

Run changed-production forbidden-shape searches and inspect every hit in the diff:

```powershell
Select-String -Path src/probos/workforce.py,src/probos/cognitive/agentic_dispatch.py,src/probos/cognitive/crew_executor.py,src/probos/cognitive/crew_orchestrator.py,src/probos/tools/code_execution_tool.py,src/probos/startup/finalize.py -Pattern 'ensure_future|aiosqlite\.connect|sqlite3\.connect|CREATE TABLE|ALTER TABLE|CREATE INDEX|EventLog|record_outcome|hebbian|Notification|DmReplyPipeline|transition_session\(.*"verifying"|transition_session\(.*"done"|transition_session\(.*"failed"'
```

Existing unrelated hits in large files are acceptable only outside the AD-1125 diff. No executable forbidden addition is allowed.

Audit the new test file:

```powershell
Select-String -Path tests/test_ad1125_room_bound_execution.py -Pattern 'MagicMock|AsyncMock|unittest\.mock\.Mock|unittest\.mock\.patch'
```

Expected: no output.

Verify no test-function count was added to the two modified legacy files by comparing their collected node counts to the exact base. Their assertion/signature updates must not alter the 127/349 formulas.

---

## Closeout - only after all gates and three-pass approval

### Trackers

Apply exactly these three closeout updates:

1. `PROGRESS.md` - prepend one concise AD-1125 shipped block with exact new/focused/caller/blast/full counts, one-room/session ordering, child evidence/status/token mapping, post-tool reasoning proof, legacy parity, no AD-1126+/config work, AD-1125 ceiling, and BF-673 unchanged.
2. `DECISIONS.md` - prepend `### AD-1125 (2026-07-18) - room-bound agentic execution (#1044)` under Era V with:
   - Context: AD-925 discarded room id; child evidence/failure state was not durable; direct parent promotion/synthesis conflicted with AD-1124;
   - Decision: existing-first one-room resolver, service-owned start, exact child evidence/token/artifact refs, durable terminal mapping, session stop before AD-1126;
   - Tests: exact gate results and final APPROVED verdict.
3. `docs/development/roadmap.md` - add one AD-1125 row immediately after AD-1124 in the Crew Autonomy table, reference epic #1041 and issue #1044, priority 1, marked shipped / #1044 closes on push.

Do not add future AD-1126 through AD-1133 rows in this commit. Do not edit era files.

### Hash-preserving prompt archival

1. Compute SHA-256 for both active prompts.
2. Require the binding prompt still equals `de9ba005ab1a5101a50b40519165d89c4b2784362328036afe2256adf9d8e779`.
3. Move original bytes to:
   - `prompts/archive/ad-1125-room-bound-agentic-execution.md`;
   - `prompts/archive/ad-1125-room-bound-agentic-execution-execution.md`.
4. Recompute both hashes and require exact pre/post equality.
5. Do not reconstruct, patch, or rewrite either prompt during the move.

### Stage and commit

Stage explicit allowlisted implementation/test/tracker paths and the two prompt renames only. Do not use `git add -A`.

Run:

```powershell
git diff --cached --check
git diff --cached --name-only
git diff --cached --name-only --diff-filter=D
git diff --cached --stat
git diff --cached --numstat
git status --short
```

No unexpected path and no unexplained deletion is allowed. The active prompt deletions must pair with archive additions as renames.

Commit exactly:

```text
AD-1125: bind crew execution to work rooms (closes #1044)
```

Do not push. Do not create/edit/comment/label/close/assign any GitHub issue. Do not create or switch a branch.

---

## Highest-risk invariants

1. AD-1124 CrewSessionService alone owns durable parent state/projection.
2. The exact existing bound room is required for a durable session; no replacement room is created/selected.
3. Room id is resolved once and shared by every child; no per-child lookup drift.
4. Tool result reaches the next LLM turn before final text; raw result is not used as a terminal chat answer.
5. Artifact evidence is server-owned persisted identity, never filename inference.
6. Child metadata/status/tokens commit through one store-owned locked operation.
7. Failed/unassigned/budget/dependency outcomes are durable and never unblock dependents or remain silently in progress.
8. `crew_session` stops after fan-out in `executing`; AD-1126 verifier/synth/final result remains absent.
9. Legacy parent full pipeline is unchanged.
10. Context/metadata carry bounded refs/summaries only; bus and WorkItem metadata carry no blobs.
11. No config/YAML/schema/runtime/API/UI/trust/notifier/EventLog/lifecycle/ingress change.
12. Real stores and real loop/tool edges prove the headline path; no permissive mock substrate.

---

## Hard stops

Stop immediately for any binding-prompt hard stop, plus:

1. preflight status is not exactly the two Architect artifacts;
2. issue #1044 lacks the exact amendment markers;
3. binding hash differs;
4. mandatory red passes, does not collect, or fails environmentally;
5. any existing test beyond AD-859/925 must change;
6. any new test function is needed in a legacy test file;
7. a frozen hash changes;
8. room correctness appears to require thread-store/schema/group-service edits;
9. evidence correctness appears to require AgenticLoop/tool-call/CrewSession/Artifact/Attachment changes;
10. child terminal persistence would bypass WorkType validation or require raw SQL outside WorkItemStore;
11. session execution would call verifier/synth or transition beyond executing;
12. legacy orchestrator behavior cannot remain green unchanged;
13. new module contains a forbidden mock token or fake store/service;
14. Gate 1, 2, or 3 has a warning or non-additive count without an exact explained collection change;
15. a Gate 4 failure reproduces serially outside the allowlist;
16. a changed-path or unexplained warning family appears;
17. prompt archival changes either hash;
18. closeout would include any non-allowlisted path or future AD work;
19. any request to push or mutate GitHub appears.

---

## Final handback format

Return one compact table containing:

- local commit SHA and exact subject;
- exact changed/created/moved paths;
- retained red-before command, node, and exact failure;
- new AD-1125 module collected/pass count `N`;
- Gate 1 exact `127 + N` result;
- Gate 2 exact `72 passed / 1 skipped` result;
- Gate 3 exact `349 + N` result;
- Gate 4 pass/skip/fail/warning result and every serial triage;
- three Builder pass verdicts;
- final SHA-256 for every implementation/test file and both archived prompts;
- exact room id, child token count, trace ref, artifact id/hash/thread id, child terminal status, and parent fine/coarse state observed in the headline test;
- proof verifier/synth were not invoked for the session and were invoked for the legacy control;
- issue states (#1041 open, #1043 closed, #1044 closes only on push, #1045 open);
- ceilings AD-1125 / BF-673;
- confirmation: no push, no GitHub mutation, no config/YAML/schema/runtime/AgenticLoop/verifier/synth/API/UI/trust/notifier/EventLog/lifecycle/ingress work;
- deviations, which must be none unless the Architect issued a revised binding prompt and hash.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.