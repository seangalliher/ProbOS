# AD-1126 Builder Execution - Verified CrewSession finalization

**Verdict:** READY FOR REPAIR HANDOFF
**Binding specification:** `prompts/ad-1126-verified-crew-session-finalization.md`
**Binding SHA-256:** `d43e337c979ec5d3fa1ff0fe759174e63f4fd5175ac0c92d5e04741e2fc24797`
**Binding byte size:** `104,577`
**Parent epic / issue:** #1041 / #1045
**Dependency:** #1044 / AD-1125 is closed and landed
**Exact base:** `D:\ProbOS` `main` at `cedd01e7d219eac39721d36decbeafd4ffc3b571`; the live tree contains the authorized uncommitted AD-1126 implementation pinned below
**Exact base subject:** `AD-1125: bind crew execution to work rooms (closes #1044)`
**Numbering:** build AD-1126 only; current ceilings AD-1125 / BF-673
**Authoritative base gate:** 19,731 passed / 33 skipped / 431 provenance-only warnings / 0 failed
**Mode:** focused adjudication repairs -> Architect approval -> exact Gate 2 -> exact Gate 3 -> one authoritative Gate 4; real substrate, one local commit, no push, no GitHub mutation

## Authority

The binding prompt is authoritative for architecture, exact contracts, failure classification, independence, persistence order, bounds, scope, hashes, acceptance, and AD-1127+ boundaries.

This execution document is authoritative for repair-tree preflight, focused mutation order, exact commands, focused evidence, Architect approval, blast/static/full gates, diagnostics, closeout, archival, staging, commit, and handback.

Do not implement from this summary alone. If these documents conflict, if the binding hash or byte size differs, or if live code differs from the exact authorized repair-input hashes/status below, stop and return to the Architect. Do not reset or reconstruct the repair tree from the clean base.

---

## Preflight - before any repair mutation

1. Read in full:
   - `.github/copilot-instructions.md`;
   - `prompts/_TEMPLATE.md`;
   - `prompts/review-criteria.md`;
   - `prompts/ad-1126-verified-crew-session-finalization.md`;
   - this execution document;
   - live issue #1045, parent #1041, and dependency #1044;
   - `PROGRESS.md` AD-1125 block;
   - `DECISIONS.md` AD-1124/1125 entries;
   - archived AD-1124/1125 binding and execution prompts;
   - every production/reference/test file named by the binding prompt and gates.
2. Verify exact refs and subject:

```powershell
Set-Location 'D:\ProbOS'
git rev-parse HEAD
git rev-parse origin/main
git ls-remote origin refs/heads/main
git log -1 --pretty=%s
```

Required local HEAD and `origin/main`:

```text
cedd01e7d219eac39721d36decbeafd4ffc3b571
```

Required subject:

```text
AD-1125: bind crew execution to work rooms (closes #1044)
```

If the live remote is temporarily scheduler/CI-stuck, that is not permission to alter or pull the base. A remote SHA mismatch is still a hard stop.
3. `git status --short --untracked-files=all` must contain exactly this authorized dirty tree, compared as a sorted set:

```text
 M src/probos/cognitive/crew_orchestrator.py
 M src/probos/cognitive/crew_session.py
 M src/probos/cognitive/crew_synth.py
 M src/probos/cognitive/crew_verifier.py
 M src/probos/startup/finalize.py
 M src/probos/workforce.py
 M tests/test_ad1124_crew_session_contract.py
?? prompts/ad-1126-verified-crew-session-finalization-execution.md
?? prompts/ad-1126-verified-crew-session-finalization.md
?? src/probos/cognitive/crew_finalizer.py
?? tests/test_ad1126_verified_finalization.py
```

There must be no staged path, tracked deletion, or other modified/untracked path.
4. Recompute the binding prompt SHA-256 and byte size:

```powershell
(Get-FileHash -Algorithm SHA256 -LiteralPath 'prompts/ad-1126-verified-crew-session-finalization.md').Hash.ToLowerInvariant()
(Get-Item -LiteralPath 'prompts/ad-1126-verified-crew-session-finalization.md').Length
```

Require exactly the header values above.
5. Read GitHub issues read-only and require #1041 OPEN, #1044 CLOSED, and #1045 OPEN. Do not edit, comment, label, close, assign, or otherwise mutate GitHub.
6. Confirm `PROGRESS.md` states AD-1125 is the top-level ceiling, BF-673 is the BF ceiling, and the exact base full gate is 19,731 passed / 33 skipped / 431 warnings.
7. Recompute these exact authorized repair-input SHA-256 values before editing. Each must match:

| Path | Repair-input SHA-256 |
|---|---|
| `src/probos/workforce.py` | `2f9c6b0c67aa48fb3e4018f7355916cef6dddcb22785505a5a72de1ae7d7525d` |
| `src/probos/cognitive/crew_session.py` | `71cbfa07479a548bb3dfd87b9abea216458b84468f9faf9e1800f19cc8266ec9` |
| `src/probos/cognitive/crew_verifier.py` | `427ffb6737e4565fbf927715e1dde0dfa8da5f337d339c9da528b582cbab37cd` |
| `src/probos/cognitive/crew_synth.py` | `4de1bf6b6e35414d112ac643f31d7cf24395da44cefd823ecad03af37d8d5075` |
| `src/probos/cognitive/crew_finalizer.py` | `0645dc97cfcf093f5f5ce668ee23d9371260e530fef31470d0e2b4a0bad88400` |
| `src/probos/cognitive/crew_orchestrator.py` | `91008f49da99cbdcc8d5a24e9b894b42c76617aaf58aa1f0ed06415081c8a044` |
| `src/probos/startup/finalize.py` | `51b5a344e109b7a92a6a81373b87ed4eb3e9fc49cb3c7b6bd37b9effd2f7d31c` |
| `tests/test_ad1124_crew_session_contract.py` | `38db5998c1192e90bc2d25392ccc7f792b7ac3ce2b6fef4a0994bafc114dee3c` |
| `tests/test_ad1126_verified_finalization.py` | `460315e5d68d36c9b9418db3113c1a21a0b0bcd7f83f4cf0ded7947260661a58` |

Recompute every frozen SHA-256 in the binding prompt and require equality. The mutable hashes in the binding prompt are clean-base parity references, not repair-input requirements.
8. Confirm both authorized new paths exist and are untracked. Do not recreate, delete, or move them.
9. Record executable AST hashes for the seven legacy methods named in the binding prompt and compare each directly with `git show cedd01e7:<path>`. Use `ast.parse`, locate the exact class method, normalize with `ast.dump(..., include_attributes=False)`, and SHA-256 the UTF-8 dump. Do not use source-text slicing.
10. Confirm Python environment is `D:\ProbOS\.venv` on Python 3.12.x without installing or changing packages.
11. Confirm no background pytest owns the shared terminal and no test process is running against the repository.

Any mismatch is a hard stop. Do not fetch, pull, merge, rebase, cherry-pick, switch, reset, restore, clean, stash, stage, commit, push, regenerate either prompt, or mutate GitHub during repair preflight.

---

## Exact allowlist

### Builder may modify production

- `src/probos/workforce.py`
- `src/probos/cognitive/crew_session.py`
- `src/probos/cognitive/crew_verifier.py`
- `src/probos/cognitive/crew_synth.py`
- `src/probos/cognitive/crew_finalizer.py` - new
- `src/probos/cognitive/crew_orchestrator.py`
- `src/probos/startup/finalize.py`

### Builder may modify tests

- `tests/test_ad1126_verified_finalization.py` - new
- `tests/test_ad1124_crew_session_contract.py` - modify only `test_public_service_api_and_annotations_are_exact` for the additive service method/signature and `test_transition_session_generic_status_interleaving_conflicts_without_mutation` so recorded `expected_assigned_to` is `facilitator-1`; add no test function and change nothing else

### Architect documents - revised and binding; Builder must never edit, hash-preserving move only at closeout

- `prompts/ad-1126-verified-crew-session-finalization.md`
- `prompts/ad-1126-verified-crew-session-finalization-execution.md`

### Conditional closeout after all gates and reviews

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- exact destinations under `prompts/archive/`

No other path is authorized. In particular, do not edit CrewTaskExecutor, WorkItemAgenticExecutor, AgenticLoop, runtime construction, config, tracked YAML, events, ArtifactStore, AttachmentStore, ChatThreadStore, AgentRegistry, any other existing test or assertion, API/router/UI/desktop, manifests, dependencies, or commercial files.

---

## Focused adjudication repair sequence

The original RED/build sequence is complete in the live uncommitted tree and must not be replayed. Preserve all existing AD-1126 behavior except where the binding prompt's RA-1 through RA-5 explicitly supersede it. Add the twelve exact named tests before or with their owning repair; never weaken an existing passing test to accommodate the implementation.

The test module must continue to contain none of:

```text
MagicMock
AsyncMock
unittest.mock.Mock
unittest.mock.patch
```

Narrow protocol-faithful connection/store wrappers are allowed only when they delegate to the real substrate through public constructor/API seams. Tests may not access `_work_item_row_write_lock`, `_db`, cache internals, finalizer private methods, or private runtime state.

### Step 1 - Repair the final store-owned child barrier

Modify only `src/probos/workforce.py`, `src/probos/cognitive/crew_session.py`, `src/probos/cognitive/crew_finalizer.py`, the exact public-API assertion in `tests/test_ad1124_crew_session_contract.py`, and `tests/test_ad1126_verified_finalization.py`:

1. add the binding's exact public `publish_work_item_metadata_with_child_barrier(...)` API beside the existing store CAS methods;
2. validate/detach the exact 23-key durable child semantic snapshots before lock admission, covering every WorkItem field except server-maintained `updated_at`, with at most 1,572,864 canonical UTF-8 bytes per child and a 33,554,432-byte running aggregate ceiling;
3. under the existing row lock, execute `BEGIN IMMEDIATE` before parent/child reads, re-query at most 1,001 direct children, require exact id set plus exact post-verification semantics, then update/commit parent done on that same connection transaction;
4. extend the CrewSession store protocol and `publish_verified_result(...)` with `expected_direct_children`;
5. retain each child verification CAS return, form the sorted detached snapshot tuple, and pass it once at final publication;
6. keep generic metadata merge, schema, global locking, and restart recovery unchanged; add no per-child post-CAS reconciliation beyond retaining the existing child-CAS authoritative return because the final barrier is authoritative.

Add and pass exactly:

```text
test_final_publication_rejects_changed_direct_child_set_after_verification
test_final_publication_rejects_post_cas_child_row_drift
test_final_publication_child_barrier_is_atomic_with_parent_done
```

The atomicity test must pause through a public/protocol-faithful connection wrapper after barrier proof and before parent update, race a same-store public child writer, and prove that writer cannot interleave before the parent transaction commits. The drift test must cover at least one previously unguarded non-`updated_at` field such as `priority`, `tags`, or `required_capabilities`, in addition to verification/token state.

### Step 2 - Repair correction capability projection

Modify only additive session-specific code in `src/probos/cognitive/crew_verifier.py` and its tests:

1. replace the empty private registry with the binding's detached event-neutral projected registry and narrow immutable runtime facade;
2. project active static grants, mesh definitions, currently visible MCP definitions, and enabled runtime-contributed stable ids through public surfaces only;
3. register public definitions for every selected id and use a private projected ToolRegistry override: explicit-denial ids raise `ToolPermissionDenied` before grants, source-backed ids delegate the complete invocation to source `check_and_invoke(...)`, and local mesh ids use the detached registry; no selected capability silently disappears;
4. preserve source permission, department/rank/restriction, MCP risk/consensus, and exclusive-lock authority at invocation time;
5. call `mcp_workbench.dispatch_tool_ids(agent_id)` only when public source `get("find_mcp_tool")` already exists, making its registration branch a no-op; otherwise derive public MCP registrations and expose stable `find_mcp_tool` plus unavailable ids as explicit denials without reading workbench private state;
6. resolve duplicate ids in ordinary category order: a valid source-backed registration wins, local mesh wins only without one, and explicit denial applies only when no safe governed representation exists;
7. keep the shared registry identity/content unchanged and never pass raw runtime or a generic forwarding facade;
8. preserve next-request tool-result parity and emit no finalization-specific event, episode, metric, trust, or gap write.

Do not modify `agentic_dispatch.py`, `ToolRegistry`, runtime, tool implementations, config, or startup. Add and pass exactly:

```text
test_session_correction_projects_static_mesh_mcp_and_runtime_tools
test_session_correction_projected_tool_result_reaches_next_request_without_events
test_session_correction_projection_preserves_permission_and_exclusive_denial
```

### Step 3 - Repair local claim semantics

Modify only `src/probos/cognitive/crew_finalizer.py` and its tests:

1. a first authoritative load of `verifying` always raises `crew_session_finalization_in_progress`, including with a local owner;
2. a caller that first loaded `executing` may wait only for one local owner's claim attempt to settle, reload exactly once, and receive exactly one claim retry only when pre-claim cancellation left the session executing;
3. post-claim cancellation leaves verifying; the waiter returns a non-completed observation and performs zero work;
4. signal claim-attempt completion in every success/error/cancellation path immediately after transition settlement and clean the claim map by event identity at that boundary; do not hold the map entry through finalization;
5. add no recursive call, retry loop, resume, lease, watchdog, or recovery.

Add and pass exactly:

```text
test_finalize_starting_in_verifying_raises_during_local_owner
test_waiter_retries_claim_once_after_precommit_owner_cancellation
test_waiter_observes_verifying_after_postcommit_owner_cancellation_without_work
```

### Step 4 - Repair post-commit publication proof

Modify only `src/probos/cognitive/crew_session.py` and its tests. Keep `expected_present_keys` in admission. Remove unrelated sibling presence/value from post-commit reconciliation; prove only exact parent done authority, assignment, `crew_session`, `crew_synth`, and result/provenance refs. Never restore a sibling.

Add and pass exactly:

```text
test_publish_verified_result_postcommit_sibling_deletion_returns_done
```

Retain the existing pre-commit sibling-deletion conflict test; the two races have intentionally different outcomes.

### Step 5 - Repair denied-tool totality

Modify only `src/probos/cognitive/crew_verifier.py`, the existing finalizer serialization path if it currently revalidates denied ids, and tests:

1. use one total validator for classification and persistence;
2. preserve valid whitespace-only exact ids;
3. map invalid container/type, empty id, duplicate, NUL, invalid UTF-8/unpaired surrogate, count, code-point, or byte overflow to `correction_execution_defect` without raising;
4. inspect at most 65 entries and never retain hostile/raw input.

Add and pass exactly:

```text
test_denied_tool_whitespace_is_preserved_as_exact_capability_denial
test_denied_tool_unpaired_surrogate_maps_to_correction_execution_defect
```

### Step 6 - Focused repair evidence and Architect checkpoint

Run the exact focused command below after the five repairs. It includes the twelve adjudication nodes plus existing anchors for accepted-count, convergence identity, Artifact evidence, cancellation, and output-only behavior. Repeat only this focused command while repairing.

```powershell
Set-Location 'D:\ProbOS'
$nodes=@(
  'tests/test_ad1126_verified_finalization.py::test_final_publication_rejects_changed_direct_child_set_after_verification',
  'tests/test_ad1126_verified_finalization.py::test_final_publication_rejects_post_cas_child_row_drift',
  'tests/test_ad1126_verified_finalization.py::test_final_publication_child_barrier_is_atomic_with_parent_done',
  'tests/test_ad1126_verified_finalization.py::test_session_correction_projects_static_mesh_mcp_and_runtime_tools',
  'tests/test_ad1126_verified_finalization.py::test_session_correction_projected_tool_result_reaches_next_request_without_events',
  'tests/test_ad1126_verified_finalization.py::test_session_correction_projection_preserves_permission_and_exclusive_denial',
  'tests/test_ad1126_verified_finalization.py::test_finalize_starting_in_verifying_raises_during_local_owner',
  'tests/test_ad1126_verified_finalization.py::test_waiter_retries_claim_once_after_precommit_owner_cancellation',
  'tests/test_ad1126_verified_finalization.py::test_waiter_observes_verifying_after_postcommit_owner_cancellation_without_work',
  'tests/test_ad1126_verified_finalization.py::test_publish_verified_result_postcommit_sibling_deletion_returns_done',
  'tests/test_ad1126_verified_finalization.py::test_denied_tool_whitespace_is_preserved_as_exact_capability_denial',
  'tests/test_ad1126_verified_finalization.py::test_denied_tool_unpaired_surrogate_maps_to_correction_execution_defect',
  'tests/test_ad1126_verified_finalization.py::test_rejected_history_then_missing_producer_counts_zero_accepted',
  'tests/test_ad1126_verified_finalization.py::test_session_correction_preserves_identity_and_round_zero_evidence',
  'tests/test_ad1126_verified_finalization.py::test_final_manifest_prioritizes_terminal_revision_and_resolves_every_ref',
  'tests/test_ad1126_verified_finalization.py::test_publish_verified_result_commit_then_cancel_returns_authoritative_done',
  'tests/test_ad1126_verified_finalization.py::test_cancellation_propagates_and_never_publishes_done',
  'tests/test_ad1126_verified_finalization.py::test_legacy_verifier_synthesizer_and_ordinary_orchestrator_remain_unchanged'
); $gateId=[guid]::NewGuid().ToString('N'); $gateDir=Join-Path $env:TEMP ('probos_ad1126_repair_' + $gateId); New-Item -ItemType Directory -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest $nodes -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Then run the complete AD-1126 module serially to discover exact `N` and prove all prior repaired requirements remain green:

```powershell
Set-Location 'D:\ProbOS'
$gateId=[guid]::NewGuid().ToString('N'); $gateDir=Join-Path $env:TEMP ('probos_ad1126_module_' + $gateId); New-Item -ItemType Directory -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad1126_verified_finalization.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Record its exact passed count as `N`; never hardcode the current pre-repair count. Then stop for the Architect's three-pass implementation review: architectural correctness, live signatures/paths, and internal consistency/scope. Do not run Gate 2, Gate 3, or Gate 4 until the Architect records `APPROVED` on all three passes.

---

## Exact validation commands

All test gates use a unique temporary data directory, forced local/offline embeddings, no pytest cache, 90-second per-test timeout, short tracebacks, and no `-n auto`.

Use the exact `N` measured by the focused full-module pass before Architect approval. Because the base has no AD-1126 module and the only existing test edit adds no function, the final full-suite formula is exactly `19,731 + N`.

### Gate 2 - Store/artifact/attachment/thread/startup blast, serial

Run only after all three Architect checkpoint passes are `APPROVED`. Required: all pass; no new warning family and zero changed-path warning. Report exact passed/skipped/warning counts.

```powershell
Set-Location 'D:\ProbOS'
$gateId=[guid]::NewGuid().ToString('N'); $gateDir=Join-Path $env:TEMP ('probos_ad1126_gate2_' + $gateId); New-Item -ItemType Directory -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/test_ad477_naval.py tests/test_ad720_attachment_store.py tests/test_ad731_attachment_ref_wire_format.py tests/test_ad791_chat_threads.py tests/test_ad791a_chat_threads_wiring.py tests/test_ad797_artifacts.py tests/test_artifact_store.py tests/test_artifact_pipeline.py tests/test_ad1124_crew_session_contract.py tests/test_ad1125_room_bound_execution.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 3 - Syntax, editor diagnostics, exact scope, hashes, and AST parity

Run syntax compilation only for changed/new Python:

```powershell
Set-Location 'D:\ProbOS'
& 'D:\ProbOS\.venv\Scripts\python.exe' -m py_compile src/probos/workforce.py src/probos/cognitive/crew_session.py src/probos/cognitive/crew_verifier.py src/probos/cognitive/crew_synth.py src/probos/cognitive/crew_finalizer.py src/probos/cognitive/crew_orchestrator.py src/probos/startup/finalize.py tests/test_ad1126_verified_finalization.py
if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE }
```

Then use the editor `get_errors` tool on exactly those eight paths. Any new error is a hard stop.

Run whitespace checks. Because new files are untracked, check each directly as well as the tracked diff:

```powershell
Set-Location 'D:\ProbOS'
git diff --check
git diff --no-index --check -- NUL src/probos/cognitive/crew_finalizer.py
if($LASTEXITCODE -notin 0,1){ exit $LASTEXITCODE }
git diff --no-index --check -- NUL tests/test_ad1126_verified_finalization.py
if($LASTEXITCODE -notin 0,1){ exit $LASTEXITCODE }
git diff --no-index --check -- NUL prompts/ad-1126-verified-crew-session-finalization.md
if($LASTEXITCODE -notin 0,1){ exit $LASTEXITCODE }
git diff --no-index --check -- NUL prompts/ad-1126-verified-crew-session-finalization-execution.md
if($LASTEXITCODE -notin 0,1){ exit $LASTEXITCODE }
```

Scope audit before closeout must show only:

```text
 M src/probos/cognitive/crew_orchestrator.py
 M src/probos/cognitive/crew_session.py
 M src/probos/cognitive/crew_synth.py
 M src/probos/cognitive/crew_verifier.py
 M src/probos/startup/finalize.py
 M src/probos/workforce.py
 M tests/test_ad1124_crew_session_contract.py
?? prompts/ad-1126-verified-crew-session-finalization-execution.md
?? prompts/ad-1126-verified-crew-session-finalization.md
?? src/probos/cognitive/crew_finalizer.py
?? tests/test_ad1126_verified_finalization.py
```

Use a sorted comparison rather than relying on display order. There must be no staged paths.

Recompute all binding frozen hashes and verify the mutable AD-1124 test diff contains only the binding-authorized public signature plus facilitator-assignment assertion changes relative to `cedd01e7`. Recompute legacy executable AST hashes and require exact clean-base equality for:

- `SubtaskVerifier.verify`;
- `SubtaskVerifier.converge`;
- `CrewSynthesizer.synthesize`;
- `CrewOrchestrator._verify`;
- `CrewOrchestrator._synthesize`;
- `CrewTaskExecutor.run` and `_run_child`.

For `CrewOrchestrator.run_crew_task`, inspect the diff and require the only executable change is replacement of the AD-1125 durable-session early return with the injected finalizer path. Run `git diff --stat`, `git diff --name-status`, and targeted `git diff --` for every mutable production path.

### Gate 4 - One full authoritative suite, xdist 4 loadfile

Run exactly once after Gate 2 and Gate 3 pass. Required exact result:

$$
19{,}731 + N\ \text{passed},\quad 33\ \text{skipped},\quad 0\ \text{failed}
$$

```powershell
Set-Location 'D:\ProbOS'
$gateId=[guid]::NewGuid().ToString('N'); $gateDir=Join-Path $env:TEMP ('probos_ad1126_gate4_' + $gateId); $gateLog=Join-Path $env:TEMP ('probos_ad1126_gate4_' + $gateId + '.log'); if(Test-Path -LiteralPath $gateDir){ throw 'Gate directory collision' }; New-Item -ItemType Directory -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR=$gateDir; $env:PROBOS_EMBEDDINGS='local'; $env:HF_HUB_OFFLINE='1'; $env:TRANSFORMERS_OFFLINE='1'; try { & 'D:\ProbOS\.venv\Scripts\python.exe' -m pytest tests/ -p no:cacheprovider -n 4 --dist=loadfile --timeout=90 -q --tb=short *> $gateLog; $exit=$LASTEXITCODE; Get-Content -LiteralPath $gateLog -Tail 320; Write-Output ('GATE4_LOG=' + $gateLog); Write-Output ('GATE4_EXIT=' + $exit); if($exit -ne 0){ exit $exit } } finally { Remove-Item Env:PROBOS_DATA_DIR,Env:PROBOS_EMBEDDINGS,Env:HF_HUB_OFFLINE,Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Warnings are provenance-audited, not accepted by scalar alone:

1. start from the exact 431-warning base record;
2. classify every family in Gate 4 output;
3. require zero warning originating from any changed/new AD-1126 path;
4. require zero new first-party warning family;
5. explain any dependency-family scalar variance with exact source/category;
6. treat any unexplained warning as failure.

If Gate 4 fails under xdist, rerun only the failing file with the same isolated environment and `-n 0`. If it passes serially, classify environmental/order-dependent per Architect rules; if it fails serially, it is a real blocker. Do not quarantine, skip, xfail, or edit unrelated tests without Architect direction.

Serial failing-file triage is not a second Gate 4. Do not rerun the full suite after triage without a new Architect adjudication.

---

## Three-pass Architect checkpoint

Complete and record all three passes after the focused repair command and before Gate 2. Any `CONDITIONAL` or `NOT READY` verdict returns to the focused repair loop; do not widen validation.

### Pass 1 - Architectural correctness

Review the implementation against every DD and acceptance item:

- one finalizer and existing authorities only;
- all children required and exact-set matched;
- live producer/facilitator/verifier identity proof;
- no self/contributor verification;
- output-only verifier/synth paths with no learning/event side effects;
- child CAS, claim CAS, publication CAS, failure mapping, cancellation, orphan behavior;
- final direct-child re-query/proof and parent done share one WorkItem row lock/connection transaction;
- correction projection uses public surfaces, explicit denials, source permission/LOTO authority, no shared mutation, and no raw runtime forwarding;
- local claim waiters obey the one-reload/one-preclaim-retry contract;
- post-commit proof ignores unrelated sibling deletion while pre-commit admission still protects sibling presence;
- denied-tool classification/persistence share one total exact validator;
- exact publication order and both refs required for done;
- no AD-1127+ feature leakage.

Verdict must be `APPROVED` or stop.

### Pass 2 - Live-code signatures and caller safety

Re-read every changed file and all direct callers. Verify:

- import paths and constructor keyword names;
- sync/async boundaries and every `asyncio.to_thread` call;
- exact registry/store/session/Artifact/Attachment return shapes;
- exact RA-1 store/service signatures and 23-key durable child snapshot semantics;
- exact per-child and aggregate canonical snapshot byte ceilings, with incremental validation before lock admission;
- exact ToolRegistry `get`/`list_tools`/`check_and_invoke`, permission-store, intent-grant, and public MCP/runtime surfaces used by RA-2;
- deterministic duplicate-id precedence and explicit denial only when no safe governed representation exists;
- no private reach-through or raw DB;
- all public APIs fully annotated;
- strict JSON type handling and byte/count bounds;
- legacy AST hashes and frozen file hashes;
- startup ordering and default-off zero-read behavior.

Verdict must be `APPROVED` or stop.

### Pass 3 - Internal consistency, test arithmetic, and scope

Verify:

- all twelve exact adjudication test names exist once and the focused command passed;
- exact `N` comes from the focused complete-module pass; no pre-repair scalar is treated as final;
- every acceptance branch has a named real-substrate test;
- no existing test edit beyond the two exact AD-1124 assertions;
- exact allowlist/status shape, including only the one authorized existing-test assertion;
- the binding prompt hash/size equal this header and both prompt hashes are recorded for closeout;
- tracker statements use measured counts only;
- commit subject and no-push/no-GitHub rules.

Verdict must be `APPROVED` or stop. After approval, run Gate 2, then Gate 3, then exactly one Gate 4. Do not move this checkpoint after Gate 4.

---

## Closeout after all gates and reviews

Do not start closeout early.

1. Record pre-move hashes of both active prompt files.
2. Update only:
   - `PROGRESS.md` with one top AD-1126 shipped block, exact tests/gates/warnings, state/publication/failure/concurrency behavior, no AD-1127+ work, and ceilings AD-1126/BF-673;
   - `DECISIONS.md` with `### AD-1126 (2026-07-20) - verified CrewSession finalization (#1045)` under Era V, containing Context / Decision / Tests;
   - `docs/development/roadmap.md` with one shipped AD-1126 row immediately after AD-1125 in the Crew Autonomy table, referencing #1041/#1045.
3. Move, do not reconstruct, both files byte-for-byte:

```text
prompts/ad-1126-verified-crew-session-finalization.md
  -> prompts/archive/ad-1126-verified-crew-session-finalization.md

prompts/ad-1126-verified-crew-session-finalization-execution.md
  -> prompts/archive/ad-1126-verified-crew-session-finalization-execution.md
```

4. Recompute post-move SHA-256 and require exact equality with pre-move values.
5. Run `git diff --check` and direct `--no-index --check` for every remaining untracked new file.
6. Require exact final status paths: seven production files (including new finalizer), two test files (one new plus the two-assertion AD-1124 update), three trackers, and two archived prompts; no active prompt copies and no other path.
7. Stage explicit paths only. Do not use `git add .`, `git add -A`, wildcard staging, or interactive staging.
8. Inspect `git diff --cached --check`, `git diff --cached --name-status`, and `git diff --cached --stat`.
9. Commit exactly:

```text
AD-1126: add verified CrewSession finalization (closes #1045)
```

10. Verify commit subject, committed path set, clean worktree, prompt hashes in the commit, and no accidental deletion/reconstruction.
11. Do not push. Do not mutate, close, comment on, label, or assign GitHub issue #1045. It closes only when the Captain pushes the commit.

---

## Acceptance criteria

1. The exact authorized dirty repair tree and all nine repair-input hashes pass preflight without reset, reconstruction, staging, or unrelated mutation.
2. Repair order follows final child barrier -> correction projection -> local claims -> post-commit proof -> denied-tool totality, with focused validation and Architect review before any broad gate.
3. Every binding acceptance item has a passing named test in the real-substrate module, including all twelve exact adjudication names.
4. Frozen existing tests and legacy method AST hashes remain exact; the AD-1124 test diff contains only the two authorized assertion updates, and no legacy behavior is rewritten to make the session path pass.
5. Focused repairs and the complete-module run pass with exact measured `N`, all three Architect checkpoint verdicts are `APPROVED`, Gate 2 passes, Gate 3 is clean, and the one authoritative Gate 4 passes exactly `19,731 + N` / 33 skipped / 0 failed with warning provenance classified.
6. Scope/hash/whitespace/editor diagnostics and all three Architect reviews are approved before closeout.
7. Trackers contain measured facts only; prompts move byte-for-byte; staging is explicit; commit subject is exact.
8. No push or GitHub mutation occurs.
9. Verify all changes comply with the Engineering Principles in .github/copilot-instructions.md.

---

## Deferred boundary - do not build

- **AD-1127:** no scheduling runner, restart recovery/resume, lease, watchdog, shutdown admission/drain, or automatic retry.
- **AD-1128:** no Captain/agent ingress, semantic dedup, provisioning transaction, duplicate-resume update, room repair, or trigger path.
- **AD-1129:** no EventLog tool, endpoint, query surface, or arbitrary event access.
- **AD-1130:** no trust, Hebbian, Shapley, outcome credit, or learning update.
- **AD-1131:** no notification, metric, completion/verification event, episode, or new EventType.
- **AD-1132:** no HXI/API/status/result projection or passive-rail removal.
- **AD-1133:** no WebSocket push or live-refresh transport.
- No schema/DDL/migration/new database, config or `config/system.yaml`, generic CrewSession bypass, private reach-through, raw database connection, inline blobs, AgenticLoop edit, second store/orchestrator, optional-child invention, or prose-to-file inference.
- No global shared SQLite transaction ownership across booking, journal, or other WorkItem writers. That is a later follow-up issue, not AD-1126.
- No cross-store Artifact/Attachment pin, reservation, or distributed commit semantics. Keep the existing read-back/orphan policy and defer stronger retention to a later follow-up.
- No per-child post-CAS reconciliation beyond the existing child-CAS authoritative return. The final store-owned child barrier is authoritative.

---

## Hard stops

Stop and return to the Architect if:

1. any preflight ref, authorized dirty status, issue state, ceiling, baseline, binding hash/size, repair-input/frozen hash, or required-path assertion differs;
2. any exact adjudication node does not collect, times out, or fails outside its owning repair;
3. a file outside the exact allowlist must change or any existing test beyond the two exact AD-1124 assertions named in the allowlist needs an edit;
4. exact absent `crew_synth`, expected sibling presence, and the complete direct-child barrier cannot be protected in the same store-owned row-lock transaction as parent done;
5. any legacy verifier/synth/orchestrator method AST changes beyond the durable branch;
6. session work calls trust-writing/episode/event-producing legacy APIs;
7. producer/facilitator/verifier identity cannot be proven from current registry objects;
8. any contributor can verify its own content or malformed verdict truthiness can accept;
9. a required child can be skipped or optionality/file requirements require prose inference;
10. correction loses real instructions/task text/room/tool-result iteration/tokens/traces/artifacts, mutates the shared registry, forwards raw runtime, weakens permission/LOTO/MCP governance, or silently drops a selected static/mesh/MCP/runtime capability;
11. any row/blob/artifact/provenance/CAS/cancellation failure can produce done;
12. parent publication requires two writes rather than one session-owned metadata/status/direct-child-barrier CAS;
13. implementing the contract requires schema/DDL/raw DB/new store/config/YAML/runtime/AgenticLoop/event/API/UI work;
14. focused or serial regression persists outside AD-1126;
15. editor/py_compile/diff/hash/AST/scope audit fails;
16. any changed/new path emits a warning or a new warning family is unexplained;
17. Gate 4 arithmetic, skips, or failures differ after serial triage;
18. either prompt changes after its final recorded hash or its archive move changes bytes;
19. tracker/commit scope includes anything beyond AD-1126 closeout;
20. any request to push or mutate GitHub appears.
21. a call loaded in `verifying` is resumed/observed instead of raising, an executing waiter retries more than one claim, or a post-claim-cancellation waiter performs work.
22. post-commit reconciliation requires or restores an unrelated sibling, or pre-commit admission stops requiring observed sibling presence.
23. denied-tool classification and persistence use different validators, strip valid whitespace, or leak an exception for malformed Unicode/type/container input.

---

## Builder handback report

Return one concise report containing:

- final verdict `READY FOR CAPTAIN PUSH` or `NOT READY`;
- base SHA and created commit SHA/subject;
- focused adjudication result and all three Architect checkpoint verdicts;
- exact `N` and Gate 2/Gate 3/one authoritative Gate 4 results/durations/skips/warnings;
- warning provenance and any xdist serial triage;
- exact changed/committed paths;
- repair-input/frozen/legacy AST and both final prompt-hash audit results;
- barrier/projection/claim/sibling/denied-tool plus prior publication/concurrency/cancellation decisions actually implemented;
- current `git status --short`;
- explicit confirmation: no push and no GitHub mutation.

---

## Re-review (2026-07-20) - Prompt pair

**Verdict:** APPROVED - execution companion is consistent with the authoritative binding.

### Pass 1 - Architecture

**Required:** none. The sequence repairs the five adjudicated implementation boundaries, preserves prior repaired behavior, and excludes global transaction ownership, cross-store reservations, per-child reconciliation, and AD-1127 recovery.

### Pass 2 - Live signatures and paths

**Required:** none. The companion uses only the binding's additive public store/service APIs and live public registry/runtime surfaces; frozen modules remain outside the allowlist. `BEGIN IMMEDIATE` makes the child proof plus parent done one explicit publication transaction on the existing store connection.

### Pass 3 - Internal consistency

**Required:** none. The companion contains all twelve exact test names, measures `N` after repair, requires Architect approval before exact Gate 2/Gate 3, permits one authoritative Gate 4, binds the final specification hash, and retains the standing Engineering Principles acceptance sentence.
