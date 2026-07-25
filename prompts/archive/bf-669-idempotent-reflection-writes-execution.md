# BF-669 Builder Execution — Expected-idempotent reflection writes

**Verdict:** APPROVED HANDOFF, NOT EXECUTABLE — BF-668 EXACT-BASE CI FAILED
**GitHub issue:** #1035 — https://github.com/seangalliher/ProbOS/issues/1035
**Exact base:** `2417bfb97d48fb9a867c387bf9e8eb71365550d6`
**Exact base commit:** `BF-668: classify IntentBus handler latency (closes #1034)`
**Scope:** Execute only `prompts/bf-669-idempotent-reflection-writes.md`. BF-669 is an OSS episodic-write/accounting bug fix; no AD, no `DECISIONS.md`, no UI, no dependency.
**License disposition:** none.

## Pre-flight — exact base, CI, and authorized initial tree

Before implementation, test edits, staging, commit, or any other mutation:

1. `git rev-parse HEAD` must equal exactly `2417bfb97d48fb9a867c387bf9e8eb71365550d6`.
2. `git rev-parse origin/main` must equal exactly the same SHA.
3. `git status --short` may show **only** these two Architect-authored untracked files:
   - `?? prompts/bf-669-idempotent-reflection-writes.md`
   - `?? prompts/bf-669-idempotent-reflection-writes-execution.md`
4. There must be no staged path, tracked modification, or other untracked path.
5. CI run `29351723371` for exact SHA `2417bfb97d48fb9a867c387bf9e8eb71365550d6` is currently **completed / failure**: UI succeeded; Python had one failure (`TestGitIntegration::test_auto_commit_after_debounce`) after 18,740 passes / 36 skips. Required serial isolated triage passed 1/1 in 0.90s, making it a parallel/full-gate timing-artifact candidate, but this does **not** waive the explicit CI-success precondition. Builder must see a completed/success replacement run on the unchanged exact base, or stop for Architect re-verification of a moved base.
6. Verify issue #1034 remains closed and #1035 remains open, read-only only.
7. If HEAD/origin moved, CI is not successful, or initial status differs, stop. Do not rebase, merge, cherry-pick, reset, clean, stash, restore, checkout, or regenerate against a different base.
8. Do not stage, commit, push, close/comment/edit an issue, or otherwise mutate Git/GitHub during pre-flight.

Current numbering at this exact base is **AD-1121 / BF-668**. Use issue-reserved **BF-669** only. Do not mint an AD or edit `DECISIONS.md`.

The only authorized initial mutation is implementation/test editing after this pre-flight passes. GitHub mutation is never authorized by this document.

## Read first

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/review-criteria.md`
- `prompts/bf-669-idempotent-reflection-writes.md` — **binding; read fully**
- `src/probos/types.py`
- `src/probos/cognitive/episodic.py`
- `src/probos/cognitive/episodic_mock.py`
- `src/probos/cognitive/dreaming.py`
- `src/probos/cognitive/dream_wm_bridge.py` — reference only; no production edit
- `src/probos/protocols.py`
- `src/probos/cognitive/storage_gate.py` — reference only
- `src/probos/cognitive/temporal_context.py` — reference only
- `src/probos/cognitive/activation_tracker.py` — reference only
- `src/probos/cognitive/procedure_store.py` — reference only
- `src/probos/startup/shutdown.py` — reference only
- every test in the exact allowlist
- every test in the three exact gate commands before changing assertions

Do not implement from this execution summary alone. Main-prompt DD-1 through DD-10, required tests, acceptance criteria, do-not-build list, hard stops, and verified evidence are binding.

---

## Exact allowlist

### Builder may modify production

- `src/probos/types.py`
- `src/probos/cognitive/episodic.py`
- `src/probos/cognitive/episodic_mock.py`
- `src/probos/cognitive/dreaming.py`
- `src/probos/protocols.py`

### Builder may modify existing tests

- `tests/test_ad541b_reconsolidation.py`
- `tests/test_ad599_reflection_episodes.py`
- `tests/test_episodic.py`
- `tests/test_episodic_chromadb.py`
- `tests/test_ad541e_content_hashing.py`
- `tests/test_ad598_importance_scoring.py`
- `tests/test_ad601_tcm_temporal_context.py`
- `tests/test_ad608_retroactive_evolution.py`
- `tests/test_ad610_storage_gating.py`
- `tests/test_ad673_anomaly_window.py`
- `tests/test_ad1037_affect_capture.py`
- `tests/test_ad979e_reconsolidation.py`
- `tests/test_ad980b_dream_attribution.py`
- `tests/test_ad671_dream_wm_integration.py`
- `tests/test_ad573d_dream_to_working_memory.py`
- `tests/test_ad873_episode_decay.py`
- `tests/test_dreaming.py`

### Architect documents already present; retain byte-for-byte

- `prompts/bf-669-idempotent-reflection-writes.md`
- `prompts/bf-669-idempotent-reflection-writes-execution.md`

### Conditional closeout after green gates and final review

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config YAML, workflow, standing order, UI, dependency, tracker, roadmap, decision, era, archive, data/log, Git, or GitHub file is authorized.

Reference-only gate files must remain unchanged. A needed edit outside this allowlist is a hard stop.

---

## Highest-risk invariants — redundant standing order

1. **Storage owns idempotency.** No caller-side `exists()`/get-before-store.
2. **Typed three-way result.** `EpisodeStoreOutcome.{STORED,DUPLICATE,SKIPPED}`; no bool-only contract and no duplicate exception.
3. **Typed policy.** `EpisodeDuplicatePolicy.{UNEXPECTED,EXPECT_SAME_REFLECTION}`; default remains `UNEXPECTED` and every untouched caller keeps warning on same-ID collisions.
4. **Step 15 opts in explicitly.** Only AD-599 passes `EXPECT_SAME_REFLECTION`.
5. **Reflection source alone is insufficient.** Full deterministic ID + source + anchor + DAG + stable-content proof is mandatory.
6. **Timestamp-only drift is expected.** AD-599 regenerates `now`; timestamp-bearing canonical hashes differ. Do not require full dataclass/direct-hash equality for replay.
7. **Reuse the canonical projection with neutral time.** Equivalence is `compute_episode_hash(dataclasses.replace(ep, timestamp=0.0))` plus exact deterministic ID and AD-599 dream envelope. Retention metadata and non-trigger anchor/anomaly drift are not content conflicts.
8. **Canonical/envelope mismatches conflict.** Malformed ID, wrong suffix/content/reflection/source/dream trigger/DAG/agents/outcomes/duration/Shapley/trust canonical field remains WARNING.
9. **`DUPLICATE` is no-write, not global equivalence.** Expected and conflicting same-ID both return `DUPLICATE`; log classification carries the distinction.
10. **`SKIPPED` is admission only.** Never use it for same-ID collision or backend failure.
11. **Same-ID authority is checked before stateful admission.** StorageGate/rate/content dedup must not turn a concurrent same-ID replay into `SKIPPED`.
12. **Primary write truth only.** `STORED` means this call newly added the authoritative Chroma row.
13. **Chroma `add()` is not proof.** Verified same-ID add can return normally and preserve the first row.
14. **One runtime-local lock.** No per-ID/global/process/file/distributed/SQLite lock.
15. **Serialized primary window.** Existing-ID read first; for new IDs only, current synchronous admission/transforms → final metadata → TCM → Chroma add; no await; release before all secondary work.
16. **First write stays authoritative.** No upsert/update/delete/reinsert/retry/merge on duplicate.
17. **Duplicate/skip has zero side effects.** No TCM, FTS, participant, review, evolution, eviction.
18. **`asyncio.CancelledError` propagates.** Never convert it to an outcome or ordinary failure; lock must release.
19. **Secondary cancellation may follow a real primary write.** Propagate; replay later returns duplicate.
20. **Mock parity is mandatory.** Canonical mock must no longer append duplicate IDs.
21. **Do not sweep every fake.** Only Step 15 outcome-consuming doubles must return `STORED`; ignored-return fakes remain compatible.
22. **Created means new primary rows.** Step 15 increments only for `STORED`.
23. **Duplicate-only rerun is quiet and truthful.** Zero Created INFO, zero WARNING, zero reflection-created WM priming.
24. **Mixed rerun counts only new rows.** No candidate-attempt count.
25. **Ordinary failure continues per candidate.** Later candidates still run; no retry.
26. **No public duplicate metric/event.** Existing `DreamReport.reflections_created` is corrected; no new field.
27. **Hash/ID contract stays exact.** No change to `compute_episode_hash`, `_hash_v`, `reflection-{sha256(text)[:16]}`.
28. **No persistence expansion.** No new KnowledgeStore reflection dual-write.
29. **Shutdown remains Step-15-free.** AD-959 lean consolidation and BF-207/296/598 behavior unchanged.
30. **No broad tests.** Exact serial, isolated, local/offline gates only.
31. **No prompt edits.** Both Architect docs remain byte-for-byte.
32. **No GitHub.** Do not push, close, comment, label, or edit issue #1035.

---

## Ordered Builder checklist

### Step 1 — Pre-flight and fail-before

- Confirm exact SHA, origin, CI success, issue states, and two-doc-only status.
- Re-grep the live store signature, all early returns, write-once read/add, TCM/secondary ordering, Step 15 IDs/store/increment, mock, protocol, and all direct store callers.
- Add the headline tests first and prove current behavior fails:
  - real deterministic replay returns `1` then `1` with one row;
  - canonical mock stores two equal IDs;
  - typed policy/outcome absent;
  - conflict warning truncates ID/lacks hashes;
  - concurrent outcomes unavailable.
- Capture exact node IDs and failure reasons for the build report.
- Do not run a broad baseline; Architect baseline counts are pinned in the main prompt.

### Step 2 — Add the shared typed contract

- Add exact policy/outcome `StrEnum`s.
- Update the protocol exact signature.
- Add signature/value/type-boundary tests.

Hard gate: old one-argument store calls remain valid; raw strings are rejected before mutation.

### Step 3 — Implement exact AD-599 proof

- Add one private pure helper in `episodic.py`.
- Test timestamp-only replay and every mismatch axis.
- Fail closed on malformed stored metadata.

Hard gate: no full-hash equality requirement, no source-only shortcut, no duplicate helper in the mock.

### Step 4 — Implement real-store outcomes and lock

- Map early returns to `SKIPPED`.
- Add one instance lock plus `__new__`-safe accessor.
- Under it, check authoritative ID first; for a new ID only, preserve the current synchronous admission/transformation order, then final metadata, TCM, and Chroma add.
- Release before first secondary await and all other secondary work.
- Return `STORED` only for new primary row; duplicate returns `DUPLICATE`.
- Preserve primary exceptions/cancellation.

Hard gate: no upsert/update/delete/reinsert/retry and no side effects on duplicate/skip.

### Step 5 — Align canonical mock

- Match exact signature/outcomes/log rules.
- First-wins by ID under one local lock.
- Reuse the real pure helper.
- Preserve recall/capacity behavior for unique rows.

Hard gate: same deterministic replay produces one list row.

### Step 6 — Make Step 15 consume the outcome

- Pass expected policy keyword.
- Increment only on `STORED`.
- Consume duplicate/skip without another Step 15 log; the storage boundary owns the one duplicate diagnostic.
- Invalid return is a dependency contract failure, not success.
- Update only the Step 15 storage doubles to return `STORED`.
- Preserve ordinary-exception continuation and cancellation propagation.

Hard gate: no caller-side precheck and no candidate/ID/attribution change.

### Step 7 — Prove report/log/WM/lifecycle

- First run 1, rerun 0, mixed run exact new count.
- No duplicate WARNING or false Created INFO.
- No reflection-created WM insight for duplicate-only rerun.
- No new event/metric/report field.
- Full-dream scheduler and shutdown consolidation unchanged.

### Step 8 — Exact gates

Run the main prompt's exact focused, adjacency, and blast commands. Fix only BF-669 regressions inside the allowlist. A reproducible need outside it is a hard stop.

### Step 9 — Three-pass review

**Pass 1 — Behavior/spec:** map every DD/test/acceptance item; inspect every return/exception/cancellation path and count/log/WM semantics.

**Pass 2 — Verify-first/code:** re-grep signatures/callers; inspect lock line-by-line, exact reflection proof, full-ID/hash logs, Chroma first-authority behavior, `__new__` paths, and unchanged hash/seed/migration/_force_update.

**Pass 3 — Scope/safety/license:** verify exact allowlist, no deletion/broad reformat, prompt docs unchanged, no warning suppression/source shortcut/schema/config/dependency/UI/AD/GitHub drift. License remains none.

### Step 10 — Gate and deletion audit

Without staging:

- `git status --short` contains only the two prompt docs plus authorized production/tests and `PROGRESS.md` after closeout.
- `git diff --check` for tracked edits.
- Direct no-index whitespace checks for both untracked Architect docs.
- No deletion relative to exact base.
- Inspect `git diff --stat`, `git diff --numstat`, and exact diff for unrelated churn.
- Confirm reference-only files, YAML, workflows, UI, manifests, decisions, roadmap, era files are absent.

### Step 11 — Closeout and exact commit

After green gates and final self-review:

1. update only `PROGRESS.md` with concise BF-669 closeout, exact counts/skips, #1035, no new AD/BF-669 ceiling;
2. retain both prompt docs unchanged;
3. stage only allowlisted paths;
4. rerun staged name/deletion/whitespace audits;
5. commit exactly:

`BF-669: make reflection writes idempotent (closes #1035)`

Do not push or mutate GitHub. Hand the local commit SHA, test counts, changed paths, and any observations back to the Architect/orchestrator.

---

## Exact gates

Run from `D:\ProbOS`. All use a unique temporary data directory, local/offline embeddings, serial execution, no pytest cache, a 90-second per-test timeout, short tracebacks, and `RuntimeWarning` promoted to error.

Architect baseline at the exact base: focused **301 passed**; adjacency **50 passed**; exact blast **616 passed, 1 skipped**. Report post-build counts and durations for each command.

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf669_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad541b_reconsolidation.py tests/test_ad599_reflection_episodes.py tests/test_episodic.py tests/test_episodic_chromadb.py tests/test_ad541e_content_hashing.py tests/test_ad598_importance_scoring.py tests/test_ad601_tcm_temporal_context.py tests/test_ad608_retroactive_evolution.py tests/test_ad610_storage_gating.py tests/test_ad673_anomaly_window.py tests/test_ad1037_affect_capture.py tests/test_ad979e_reconsolidation.py tests/test_ad980b_dream_attribution.py tests/test_ad671_dream_wm_integration.py tests/test_ad573d_dream_to_working_memory.py tests/test_ad873_episode_decay.py tests/test_dreaming.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Adjacency

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf669_adjacent_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_participant_index.py tests/test_memory_integrity.py tests/test_selective_encoding.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf669_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad818_schema_versions.py tests/test_ad818a_paginated_migrations.py tests/test_ad818a2_paginated_migrations.py tests/test_ad959_shutdown_light_consolidation.py tests/test_bf207_shutdown_episodic_integrity.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py tests/test_knowledge_store.py tests/test_semantic_knowledge.py tests/test_procedure_store.py tests/test_procedure_decay.py tests/test_procedure_archival.py tests/test_procedure_dedup.py tests/test_finalize.py tests/test_public_apis.py tests/test_layer_boundaries.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Report exact passed/failed/skipped counts and durations. Do not substitute `-n auto`, parallel xdist, full `tests/`, live endpoint/model/network, or live runtime data.

---

## Deletion and scope audit commands

Run before staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D 2417bfb97d48fb9a867c387bf9e8eb71365550d6 --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/bf-669-idempotent-reflection-writes.md
git diff --no-index --check -- NUL prompts/bf-669-idempotent-reflection-writes-execution.md
```

For each no-index command, exit code `1` is expected because the file differs from empty; any emitted whitespace diagnostic is a failure.

Expected final paths are only the two prompt docs, the production/test allowlists, and `PROGRESS.md`. Any deletion, unrelated path, or bulk reformat is a hard stop.

After staging, also run:

```powershell
git diff --cached --check
git diff --cached --name-only
git diff --cached --name-only --diff-filter=D
git diff --cached --stat
git diff --cached --numstat
```

Do not use `git add -A`; stage explicit allowlisted paths only.

---

## Required Builder report

Return a concise table containing:

- exact base and exact local commit SHA;
- BF-668 CI run result verified before build;
- fail-before node IDs and reasons;
- final focused/adjacency/blast counts, skips, durations;
- changed file list;
- exact store signature and enum values;
- exact early-ID/new-ID admission/primary-write lock window and proof no await occurs inside;
- exact replay/conflict/concurrency outcomes;
- Step 15 first/rerun/mixed count/log/WM results;
- protocol/mock corrections made;
- issue-text corrections followed (timestamp-only drift, no duplicate exception, `DUPLICATE` for conflict, no KnowledgeStore change);
- license `none`;
- three-pass review verdict;
- confirmation of no deletion, YAML/UI/dependency/AD/DECISIONS/roadmap/era/GitHub mutation;
- confirmation no push was performed.

---

## Stop conditions

Stop and report to the Architect if:

- exact base/origin/two-doc-only tree fails;
- BF-668 exact-base CI remains failed (the current state), is pending/cancelled, or is superseded without Architect re-verification;
- any needed file is outside the allowlist;
- correctness needs a config/dependency/event/API/schema/table/cache/distributed/process/file lock or ID/hash change;
- Chroma duplicate semantics invalidate the store-local serialized read/add decision;
- the primary lock must span an await or secondary work;
- expected replay cannot be proved through the timestamp-neutral existing canonical projection plus exact AD-599 deterministic ID/dream envelope without changing the producer/hash contract;
- a conflict would be overwritten, silenced, or returned as stored/skipped;
- a duplicate/skip path causes TCM/FTS/participant/review/evolution/eviction side effects;
- cancellation is swallowed/converted or the lock can remain held;
- Step 15 needs caller-side precheck, broad caller migration, candidate/order/cap change, or return-type change;
- a serial gate failure requires an unallowlisted edit, skip, quarantine, weakened assertion, or broad run;
- either prompt changes;
- any config YAML, workflow, UI, dependency, decision/roadmap/era, unapproved tracker, GitHub, or push mutation appears.

Do not guess around a hard stop.

## Do NOT build

- Do not suppress all duplicate warnings or classify all reflections as expected.
- Do not use bool-only outcomes, a duplicate exception, caller precheck, or direct timestamp-bearing canonical-hash equality for AD-599 replay.
- Do not overwrite/update/upsert/delete/reinsert/retry/merge duplicate rows.
- Do not add distributed/file/SQLite/per-ID locks or hold the local lock across awaits/sidecars/eviction.
- Do not change hash version, reflection ID format/length, Chroma/FTS/participant schema, seed/migrations/_force_update.
- Do not broadly edit all store callers/fakes or add reflection KnowledgeStore persistence.
- Do not change dream candidates/order/cap/cadence, attribution, recall, Ebbinghaus, trust, Hebbian, procedure lifecycle, scheduler, or shutdown.
- Do not add metrics/events/API/config/dependency/UI/AD/DECISIONS/roadmap/era/workflow/standing-order/GitHub changes.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
