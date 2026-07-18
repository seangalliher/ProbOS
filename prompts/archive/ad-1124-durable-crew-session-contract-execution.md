# AD-1124 Builder Execution - Durable CrewSession contract

**Verdict:** APPROVED FOR BUILDER HANDOFF AFTER ISSUE #1043 BODY AMENDMENT
**Binding specification:** `prompts/ad-1124-durable-crew-session-contract.md`
**Parent epic / issue:** #1041 / #1043
**Dependency:** #1042 / BF-673 is closed
**Exact base:** clean `D:\ProbOS` `main` at `00884a6148aeac6167f2025795e475281aa6de1f`
**Exact base subject:** `BF-673: correct group trigger provenance`
**Numbering:** build AD-1124 only; current ceilings AD-1123 / BF-673
**Mode:** red-first, one local commit, no push, no GitHub mutation

## Authority

The binding prompt is authoritative for architecture, exact contract fields/bounds, state/projection matrices, API signatures, file scope, acceptance, hashes, and closeout.

This execution document is authoritative for mutation order, test commands, status/Git discipline, three-pass Builder review, staging, and handback.

Do not implement from this summary alone. If these documents conflict, stop and return to the Architect.

---

## Pre-flight - before any Builder mutation

1. Read in full:
   - `.github/copilot-instructions.md`
   - `prompts/_TEMPLATE.md`
   - `prompts/review-criteria.md`
   - `prompts/ad-1124-durable-crew-session-contract.md`
   - this execution document
   - every production/reference/test file named in the binding prompt's verified section and four gates.
2. Verify all three refs equal the exact base:

```powershell
git rev-parse HEAD
git rev-parse origin/main
git ls-remote origin refs/heads/main
```

3. `git status --short` must contain exactly:

```text
?? prompts/ad-1124-durable-crew-session-contract-execution.md
?? prompts/ad-1124-durable-crew-session-contract.md
```

There must be no staged path, tracked modification/deletion, or other untracked path.
4. Read issue #1043 and require the exact amended decision marker:

```text
The authoritative fine session state lives in the strict, versioned `WorkItem.metadata["crew_session"]["state"]` contract
```

Also require the exact coarse mapping and `draft` pre-bind wording from the binding prompt. Read-only verification is allowed. Do not edit/comment/label/close/assign any issue.
5. Confirm #1041 and #1043 are open and #1042 is closed/completed.
6. Verify `PROGRESS.md` identifies BF-673 as shipped, `DECISIONS.md` identifies AD-1123 as the top-level ceiling, and no AD-1124 has landed.
7. Recompute every binding SHA-256. Every existing allowlisted and frozen file must match.
8. Confirm these paths do not exist:
   - `src/probos/cognitive/crew_session.py`
   - `tests/test_ad1124_crew_session_contract.py`
9. Confirm Python environment is `D:\ProbOS\.venv` on Python 3.12.x.

Any mismatch is a hard stop. Do not fetch, pull, merge, rebase, cherry-pick, switch, reset, restore, clean, stash, stage, commit, push, regenerate the prompt, or mutate GitHub.

---

## Exact allowlist

### Builder may modify production

- `src/probos/workforce.py`
- `src/probos/cognitive/crew_session.py` - new
- `src/probos/routers/workforce.py`
- `src/probos/cognitive/crew_synth.py`
- `src/probos/runtime.py`
- `src/probos/startup/finalize.py`

### Builder may create tests

- `tests/test_ad1124_crew_session_contract.py` - new

### Architect documents - do not edit; move unchanged only at closeout

- `prompts/ad-1124-durable-crew-session-contract.md`
- `prompts/ad-1124-durable-crew-session-contract-execution.md`

### Conditional closeout after all gates/reviews

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- prompt destinations under `prompts/archive/`

No existing test file is editable. No other path is authorized.

---

## Red-first execution sequence

### Step 1 - Create the complete test module only

Create `tests/test_ad1124_crew_session_contract.py` and no production file.

Follow every test family in binding Section 1. Use real `WorkItemStore`, real `ChatThreadStore`, real `SystemConfig`, deterministic clocks, real temporary databases, and narrow hand-written recorders/barriers. The new test module must contain none of:

```text
MagicMock
AsyncMock
unittest.mock.Mock
unittest.mock.patch
```

Monkeypatch is allowed only for a non-substrate source/clock/import guard when a hand-written seam cannot prove it; prefer dependency injection.

### Step 2 - Run and record the mandatory red

Run one headline initialization test (use its final exact node id):

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1124_red_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1124_crew_session_contract.py::test_initialize_session_persists_strict_contract_and_generic_projection -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected RED: import/collection failure for the absent `probos.cognitive.crew_session` surface, or an assertion showing the absent built-in/merge API. Record exact command, node, exception, and reason. If it passes or fails for unrelated environment/test-shape reasons, stop.

Do not weaken tests after red.

### Step 3 - Implement WorkType and merge primitive

Modify only `src/probos/workforce.py`:

1. add the exact DD-2 built-in descriptor;
2. add one runtime-local merge lock on `WorkItemStore`;
3. share that lock with every existing same-store path that mutates WorkItem metadata/work-type/status/assignment, holding it from authoritative row load through commit but not across snapshot refresh or event emission;
4. add the exact `expected_work_type`, `expected_status`, and `expected_assigned_to` row preconditions from revised DD-7, checked inside the lock with stable `work_item_state_conflict` failure;
5. extract/reuse one private status-validation helper so `transition_work_item` and `merge_work_item_metadata(..., new_status=...)` cannot drift;
6. add the exact fully annotated public merge method;
7. preserve every existing transition no-op/gate/event behavior and avoid nested acquisition deadlocks in helper/caller paths.

Run the WorkType/merge/concurrency subset of the new test module before continuing.

### Step 4 - Implement the strict contract/service

Create only `src/probos/cognitive/crew_session.py`:

- exact 27-key v1 model and bounds;
- exact state/projection maps and pure transition helper;
- narrow local WorkItem/ChatThread Protocols;
- one service with exactly the three public methods;
- async-to-sync room access through `asyncio.to_thread`;
- no runtime/orchestrator/executor/verifier/EventLog/trust/notifier/router/config import;
- no task/lifecycle/provisioning path.

Run the full new module. Fix only failures inside the active production/test allowlist.

### Step 5 - Migrate the two parent metadata writers

Modify only:

1. `src/probos/routers/workforce.py::attach_work_item_inputs`;
2. `src/probos/cognitive/crew_synth.py::_complete_parent`.

Each writes only its owned top-level key through `merge_work_item_metadata`. Preserve current return shapes, ref dedup, transition behavior, trust/episode behavior, and honest-degrade behavior. Do not integrate the synth with fine session state.

Run the relevant new integration cases plus the existing 164-test workforce baseline gate.

### Step 6 - Wire the service behind the existing gate

Modify only:

1. `src/probos/runtime.py` - public optional annotation and explicit `None` initialization;
2. `src/probos/startup/finalize.py` - `_wire_crew_session_service` and one invocation immediately before `_wire_crew_orchestrator`.

Gate false must return before store lookup/lazy import. Enabled missing dependencies warn and do not attach. Enabled real stores attach one service; repeat wiring preserves object identity.

Do not edit config, shutdown, startup results, orchestrator, executor, verifier, or any test outside the new module.

### Step 7 - Run focused and regression gates

Run the four gate levels below verbatim. Report exact count, duration, skips, warnings, and any triage.

---

## Exact test gates

All focused/serial gates use a unique `PROBOS_DATA_DIR`, local/offline embedding settings, no pytest cache, `-n 0`, timeout 90, short tracebacks, and `RuntimeWarning` promoted to error. Do not use `-n auto`.

Let `N` be the final exact count collected in `tests/test_ad1124_crew_session_contract.py`.

### Gate 0 - AD-1124 module

Expected: exactly `N passed`, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1124_module_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1124_crew_session_contract.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 1 - Workforce, metadata writers, block/resume, and Todo state

Pinned existing baseline: **164 passed**. Expected post-build: exactly `164 + N passed`, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1124_gate1_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1124_crew_session_contract.py tests/test_workforce.py tests/test_ad855_block_resume.py tests/test_ad1080_work_item_steps.py tests/test_ad861_crew_synth.py tests/test_ad926a_task_file_upload.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 2 - Threads, crew pipeline adjacency, task rooms, and startup wiring

Pinned existing baseline: **104 passed**. Expected post-build: exactly `104 + N passed`, no warnings.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1124_gate2_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1124_crew_session_contract.py tests/test_ad791_chat_threads.py tests/test_ad859_crew_executor.py tests/test_ad862_crew_tasks_api.py tests/test_ad867_crew_orchestrator.py tests/test_ad868_self_originated_crew.py tests/test_ad925_auto_task_room.py tests/test_runtime.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 3 - Full repository parallel gate

Pinned exact-base result: **19,585 passed / 33 skipped / 1 failed / 453 warnings**. The one failure was `tests/test_ward_room.py::TestEndorsementActivation::test_browse_threads_sort_recent`; the complete file passed **92/92** serially.

Expected post-build:

- pass count is at least `19,585 + N` if the same environmental failure recurs, or at least `19,586 + N` if it does not;
- skips remain 33 unless independently explained;
- warnings do not exceed 453 without exact pre-existing provenance;
- zero warning points to an AD-1124 changed path;
- zero AD-1124 test fails.

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1124_gate3_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/ -p no:cacheprovider -n 4 --dist=loadfile --timeout=90 -q --tb=short } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

For every Gate 3 failure, rerun the entire failing file serially under the same isolated env before classification:

```powershell
$gateDir = Join-Path $env:TEMP ('probos_ad1124_triage_' + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest <failing-file> -p no:cacheprovider -n 0 --timeout=90 -q --tb=short } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

A failure that passes serially is environmental/order noise and must be documented. A failure that reproduces serially is a hard stop unless it is an AD-1124 changed-path failure fixed inside the allowlist.

---

## Required implementation reviews

### Builder Pass 1 - Behavior/spec

Before tracker edits:

1. map every DD and acceptance item to code and named tests;
2. enumerate all 36 fine-state pairs and every coarse WorkType edge;
3. trace initialize, normal transition, blocked/resume, terminal refusal, same-state no-op, progress update, and stale CAS;
4. prove every timestamp is server-owned;
5. prove exact one-room validation occurs on initialize/get/transition;
6. force parent reassignment/work-type/status changes after service load and require `work_item_state_conflict` with no session mutation;
7. force a generic status writer to contend after merge admission and prove it cannot interleave before the merge commit;
8. prove no creation/provisioning/execution path exists.

Verdict must be `APPROVED`; otherwise stop.

### Builder Pass 2 - Verify-first/code

1. re-grep every `merge_work_item_metadata` call; only service, task-input writer, and crew-synth writer may call it in this AD;
2. re-grep all parent metadata whole-column writes and confirm the binding no-clobber claim is exactly scoped;
3. enumerate every direct `work_items` row writer and prove each metadata/work-type/status/assignment writer shares the runtime-local row-write lock without nested acquisition;
4. compare the extracted shared transition validator against every pre-AD `transition_work_item` branch;
5. confirm initialization passes exact expected work-type/status/assignee and transition passes exact expected work-type/status into merge admission;
6. confirm injected-connection tests cover update failure, commit failure, SQL rollback attempt, cancellation propagation, and lock release;
7. confirm new service uses narrow Protocols, real public methods, and `asyncio.to_thread` for room reads;
8. confirm no raw SQLite connection or schema/index change;
9. confirm all new public APIs are fully annotated and Pydantic is strict/extra-forbid;
10. inspect logs for what/why/next and content leakage;
11. recompute every frozen hash.

Verdict must be `APPROVED`; otherwise stop.

### Builder Pass 3 - Scope/safety

1. inspect `git diff --name-only`, `--stat`, `--numstat`, and deletion set against the exact allowlist;
2. confirm config/YAML/events/protocols/threads/orchestrator/executor/verifier/shutdown/UI/API surface remains frozen as specified;
3. confirm default-off wiring performs no store work and no service construction;
4. confirm no tasks, subscriptions, scans, retries, EventLog/trust/notifier/learning side effects;
5. confirm no issue/branch/push mutation occurred;
6. confirm prompt bytes are unchanged before move.

Verdict must be `APPROVED`; otherwise stop.

---

## Diagnostics and source audits

Run editor diagnostics on all six production files and the new test file. Any new error attributable to AD-1124 is a blocker.

Before tracker edits:

```powershell
git status --short
git diff --check
git diff --stat
git diff --numstat
git diff --name-only --diff-filter=D
git diff -- src/probos/config.py config/system.yaml src/probos/threads/__init__.py src/probos/cognitive/crew_orchestrator.py src/probos/cognitive/crew_executor.py src/probos/cognitive/crew_verifier.py src/probos/events.py src/probos/protocols.py src/probos/startup/shutdown.py
git diff --no-index --check -- NUL prompts/ad-1124-durable-crew-session-contract.md
git diff --no-index --check -- NUL prompts/ad-1124-durable-crew-session-contract-execution.md
```

The frozen-path diff must be empty. For `--no-index`, exit code 1 is expected because a non-empty file differs from NUL; emitted whitespace diagnostics are not allowed.

Search changed production code for forbidden shapes and inspect every hit:

```powershell
Select-String -Path src/probos/cognitive/crew_session.py,src/probos/workforce.py,src/probos/routers/workforce.py,src/probos/cognitive/crew_synth.py,src/probos/runtime.py,src/probos/startup/finalize.py -Pattern 'create_task|ensure_future|EventLog|record_outcome|hebbian|Notification|IntentMessage|aiosqlite\.connect|sqlite3\.connect|CREATE TABLE|ALTER TABLE|CREATE INDEX|open_or_resume|schedule\(|async def start|async def stop'
```

No executable forbidden addition is allowed. Existing unrelated occurrences in large files must be outside the AD-1124 diff.

---

## Closeout - only after gates and three-pass approval

### Trackers

Apply exactly the binding prompt's three tracker updates:

1. `PROGRESS.md` - prepend one concise shipped block with exact counts/warnings and ceilings AD-1124 / BF-673.
2. `DECISIONS.md` - prepend the AD-1124 Context / Decision / Tests entry under Era V.
3. `docs/development/roadmap.md` - add the one AD-1124 row immediately after AD-862 in the Crew Autonomy table; reference epic #1041 and issue #1043, priority 1, and `SHIPPED / #1043 CLOSES ON PUSH`.

Do not add future AD-1125 through AD-1133 rows in this commit. Do not edit era files.

### Hash-preserving prompt archival

1. Compute SHA-256 for both active prompts.
2. Move their original bytes to:
   - `prompts/archive/ad-1124-durable-crew-session-contract.md`
   - `prompts/archive/ad-1124-durable-crew-session-contract-execution.md`
3. Recompute and require exact pre/post equality.
4. Do not reconstruct or rewrite the files during the move.

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

No unexpected path and no unexplained deletion is allowed. The two active prompt deletions must pair with their archive additions as renames.

Commit exactly:

```text
AD-1124: add durable crew session contract (closes #1043)
```

Do not push. Do not create/edit/comment/label/close/assign any GitHub issue. Do not create/switch a branch.

---

## Highest-risk invariants

1. Fine state is metadata authority; no fine string enters global WorkItem status semantics.
2. Generic status is the exact coarse projection and commits with metadata in one store update.
3. Unbound rows are `draft`; default-off cannot create live/open sessions.
4. One parent binds to one existing task-linked room; duplicates fail closed without DDL.
5. Merge is store-owned, shallow top-level, runtime-local, expected-value protected for metadata plus parent work-type/status/assignment, and preserves unrelated keys; one shared lock excludes every same-store writer of those row fields through commit.
6. Existing input and synth writers use the same merge primitive.
7. Contract is exact 27-key v1, strictly bounded, refs-not-blobs, server-time-only.
8. No parent/room provisioning or cross-database atomicity claim.
9. No orchestration integration, work execution, verifier, lifecycle runner, ingress, dedup, EventLog, trust, notifier, UI, API, YAML, event, or dependency.
10. Real SQLite and real thread store tests; no permissive mocks.

---

## Hard stops

Stop immediately for any condition in the binding prompt, plus:

1. issue #1043 is not amended exactly before Step 1;
2. preflight status is not exactly the two Architect artifacts;
3. any existing test must be edited;
4. any baseline hash differs;
5. runtime/service wiring would require startup result or shutdown changes;
6. coarse/fine state cannot commit atomically without changing a public Protocol;
7. two-room prevention appears to require a unique index;
8. `CrewSessionService` needs Runtime, executor, verifier, artifact, trust, EventLog, notifier, or API dependencies;
9. any new module test uses `MagicMock`, `Mock`, or `AsyncMock`;
10. a Gate 3 failure reproduces serially outside the allowlist;
11. prompt archival changes either hash;
12. the requested commit would include anything beyond AD-1124 and closeout;
13. any request to push or mutate GitHub appears.
14. a service load-to-merge interleaving can overwrite a parent work-type/status/assignment change, or an existing same-store WorkItem row writer can enter after merge admission and before commit.

---

## Final handback format

Return a compact table containing:

- local commit SHA and exact subject;
- exact changed/created/moved paths;
- retained red-before command and exact failure;
- new module collected/pass count `N`;
- Gate 1 exact `164 + N` result;
- Gate 2 exact `104 + N` result;
- Gate 3 pass/skip/fail/warning result and every serial triage result;
- three-pass Builder verdicts;
- final SHA-256 for every implementation/test file and both archived prompts;
- exact `work_items` pre/post column-list migration proof;
- issue states (#1041 open, #1042 closed, #1043 closes only on push);
- ceilings AD-1124 / BF-673;
- confirmation: no push, no GitHub mutation, no config/YAML/schema/UI/execution work;
- deviations (must be none unless Architect approved a revised prompt).

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Implementation re-review (2026-07-17)

**Verdict:** BLOCKED. Resume at Step 3 and implement the binding prompt's revised DD-7 CAS/lock contract, add the deterministic interleaving and injected-connection rollback/cancellation tests, then rerun Gates 0-3 and all three Builder reviews. Do not perform closeout while this section remains unresolved.

## Final implementation re-review (2026-07-17)

**Verdict:** BLOCKED. The prior shared-lock/row-precondition correction is green, but the metadata CAS still uses Python equality and is not exact for JSON types.

Resume at Step 3. Replace expected metadata comparison with JSON-type-exact nested comparison while preserving the one intentional initialization rule: a missing top-level `crew_session` key satisfies `expected={"crew_session": None}`. Add both (1) a direct nested boolean/numeric alias conflict test and (2) a deterministic real-store service barrier test in which a generic writer installs a Python-equal/JSON-different malformed contract before merge admission. The service must raise `work_item_metadata_conflict`, preserve the concurrent value, and leave status/session transition state unchanged.

Then rerun Gate 0 through Gate 3, all three Builder reviews, diagnostics, compile, scope, schema, and hash audits. Report the new exact `N` and derived gate counts. Do not update trackers, archive prompts, stage, commit, push, or mutate GitHub while this section remains unresolved.