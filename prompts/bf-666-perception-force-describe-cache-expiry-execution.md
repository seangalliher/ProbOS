# BF-666 Builder Execution — Perception force-describe cache expiry

**Verdict:** APPROVED FOR BUILDER
**GitHub issue:** #1032 — https://github.com/seangalliher/ProbOS/issues/1032
**Exact base:** `2d595dad0df6d0a1daeed8d02d8e5d324cd483f5`
**Scope:** Execute only `prompts/bf-666-perception-force-describe-cache-expiry.md`. BF-666 is a backend perception-cache bug fix; no AD, no `DECISIONS.md`, and no UI.
**License disposition:** none.

## Pre-flight — exact base and authorized initial tree

Before implementation or test edits:

1. `git rev-parse HEAD` must equal exactly `2d595dad0df6d0a1daeed8d02d8e5d324cd483f5`.
2. `git status --short` may show **only** these two Architect-authored untracked files:
   - `?? prompts/bf-666-perception-force-describe-cache-expiry.md`
   - `?? prompts/bf-666-perception-force-describe-cache-expiry-execution.md`
3. There must be no staged file and no tracked modification.
4. BF-665 is already committed/pushed at this base; its CI may still be running. Do not query, edit, rerun, cancel, comment on, or otherwise mutate GitHub. If an orchestrator reports that BF-665 CI failed or HEAD moved, hard-stop for Architect re-verification.
5. Do not stash, restore, checkout, reset, stage, commit, push, or mutate GitHub state during pre-flight.
6. Any base/tree difference is a hard stop.

Current numbering at this exact base is AD-1121 / BF-665. Use issue-reserved BF-666 only. Do not mint an AD or edit `DECISIONS.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-666-perception-force-describe-cache-expiry.md`
- `src/probos/perception/consumer.py`
- `src/probos/attachments/store.py`
- `src/probos/attachments/filesystem_store.py`
- `src/probos/attachments/reaper.py`
- `src/probos/config.py`
- `config/system.yaml`
- `src/probos/perception/aggregator.py`
- `src/probos/perception/supervisor.py`
- `src/probos/perception/working_memory.py`
- `src/probos/perception/wm_store.py`
- `src/probos/routers/perception.py`
- `src/probos/routers/agents.py`
- `src/probos/routers/thread_fanout.py`
- `src/probos/startup/finalize.py`
- `src/probos/startup/shutdown.py`
- every reference/run-only test in the main prompt before the blast gate

Do not implement from this execution summary alone. The main prompt's DD-1 through DD-8 are binding.

---

## Exact allowlist

### Builder may modify

- `src/probos/perception/consumer.py`

### Builder may create

- `tests/test_bf666_force_describe_cache_expiry.py`

### Builder may modify for one verified obsolete fixture only

- `tests/test_ad746a_force_describe_mirror.py`

### Already present; include only in an explicitly authorized final commit, do not rewrite/archive

- `prompts/bf-666-perception-force-describe-cache-expiry.md`
- `prompts/bf-666-perception-force-describe-cache-expiry-execution.md`

### Conditional closeout only, and only if the orchestrator explicitly directs it

- `PROGRESS.md`

No other existing test modification is authorized. No other source, test, config, workflow, UI, tracker, roadmap, decision, archive, dependency, log/data, or issue file is authorized.

---

## Highest-risk invariants — redundant standing order

1. **Complete tuple is identity.** Cache/clear compares `(sha, captured_at)`, never SHA alone.
2. **Clear every exact alias atomically.** One compare-and-clear removes all session entries and global only when each equals the original complete candidate. Nonmatching/newer entries survive.
3. **One shared cache lock.** Snapshot, monotonic write, and compare-clear use one private `threading.Lock`. Never hold it over an await. Do not reuse BF-304's `_describe_lock`.
4. **Early force singleflight.** A separate `_force_describe_lock: asyncio.Lock` plus private async-context-manager permit guards selection through postcheck. The permit uses a 1ms bounded `wait_for(lock.acquire())`, yields false on timeout, releases only after successful acquire, and propagates cancellation. Concurrent force calls must not meaningfully queue or touch storage. Do not reuse or broaden `_describe_lock`.
5. **Synchronous upload API stays synchronous.** `record_uploaded_frame(sha, session_id, captured_at) -> None` cannot become async. The tiny cache lock covers dictionary work only.
6. **Writes are monotonic.** Finite incoming `captured_at >= current` may replace; older input cannot regress. Reject `NaN`/`+Inf`/`-Inf`. Session/global comparisons are independent. Equal timestamp remains last-write-wins.
7. **Carry exact ambient candidate.** `_handle()` retains the candidate returned by the write helper and passes it through private `_process(..., cache_candidate=...)`; never reconstruct a missing-`captured_at` fallback with a second clock read.
8. **Fresh low-novelty remains useful.** `_handle()` records before supervisor admission exactly as today. Do not evict merely because the supervisor drops.
9. **Effective age is bounded.** Prompt freshness `<=0` uses retention; otherwise `min(retention, prompt freshness)`. Use strict `>` and wall-clock `captured_at`.
10. **Selection validates eagerly.** Stale candidates clear before store work. Missing public `exists()` preflight clears before `_process()`.
11. **`exists()` is not proof.** Reaper can delete after preflight. Initial `store.read()` `FileNotFoundError` in `_process()` must independently compare-clear.
12. **Postcheck closes the late race.** After normal `_process()` return, a second public `exists()` clears the original tuple if the blob disappeared after read/during processing; return `None` but do not delete/undo a completed WM observation.
13. **Expected absence is quiet.** No WARNING/traceback. DEBUG only when a matching slot was actually removed.
14. **Unexpected backend errors preserve.** WARN with context/traceback, return `None`, retain candidate for transient recovery.
15. **Cancellation remains cancellation.** Explicitly re-raise `CancelledError`; do not clear a still-valid candidate solely because preflight/process/postcheck was cancelled. Release force/cache locks; no leaked task.
16. **BF-304 is untouched.** Keep describe singleflight/drop-not-queue semantics. Do not cancel a valid in-flight describe.
17. **WM and cache are different lifecycles.** Do not delete in-memory or persisted `VisionObservation` rows. AD-1055/BF-294 freshness rendering remains the historical-context guard.
18. **Public storage seam only.** `read()`/`exists()`; no `_index`, `_root`, `_lock`, `_find`, runtime private store field, or router cache access in production.
19. **Real fixture, no production bypass.** Correct AD-746a's malformed `"sha123"`/missing-store force fixture to a valid 64-hex real-store candidate. Never weaken preflight for that test.
20. **No lifecycle redesign.** No task, callback, polling, reaper coupling, retention change, camera-stop API, startup/shutdown edit, or aggregator edit.
21. **No issue-assumption overreach.** The live recheck found 19 warnings, not the issue snapshot's 16. Exact count is not a test contract.
22. **Unrelated aggregator shutdown gap stays out.** `VisionAggregator.stop()` has no current runtime shutdown caller; do not fix it in BF-666.
23. **No UI.** This is one backend cache/read correction.

---

## Ordered checklist

### Step 1 — Baseline contract capture

- Confirm exact base/tree.
- Grep all production reads/writes of `_latest_frame_by_session` / `_latest_frame_global`.
- Grep all production callers of `force_describe_current_frame()` and `record_uploaded_frame()`.
- Confirm `AttachmentStore.read()` / `exists()` public signatures and filesystem TOCTOU semantics.
- Confirm no BF-666 test file exists.
- Do not run broad baseline tests.

### Step 2 — Cache ownership primitives

- Add the typed complete-candidate alias.
- Add one private synchronous cache lock and one private bounded/cancellation-safe force-call permit, both separate from `_describe_lock`.
- Add monotonic write, session-first/global-fallback snapshot, all-alias compare-clear, and effective-age helpers.
- Keep every helper private and fully annotated.
- Make the existing test reset helper respect cache ownership.

Hard gate: no helper holds the cache lock across any await; public signatures unchanged.

### Step 3 — Route both writers

- `_handle()` delegates to the monotonic helper before `_process()`.
- `_handle()` carries the exact returned tuple into the backward-compatible private `_process(..., cache_candidate=...)` keyword, including missing-`captured_at` fallback.
- `record_uploaded_frame()` delegates to the same helper.
- Preserve empty-SHA no-op, low-novelty availability, and upload mirror behavior.
- Prove older delayed `_handle()` cannot regress a newer upload mirror.

### Step 4 — Force-describe selection validation

- Drop a concurrent force call through the bounded permit before cache/store selection; do not meaningfully queue.
- Snapshot one complete candidate inside the admitted force-call context.
- Age-check using the pinned effective max.
- Clear stale exact aliases before storage/LLM work.
- Public `store.exists()` preflight: false/`FileNotFoundError` quiet-clear; unexpected error warns/preserves; cancellation re-raises.
- Keep synthetic message fields and timeout shape unchanged.

### Step 5 — Authoritative read and post-process races

- In `_process()`, parse candidate `captured_at` before initial read.
- Add only a private keyword-only `cache_candidate=None`; keep direct `_process(msg)` callers valid.
- Order catches: `CancelledError`, `FileNotFoundError`, broad `Exception`.
- Missing read compare-clears exact aliases; unexpected error warns/preserves.
- After normal `_process()`, public `exists()` recheck and compare-clear original tuple if reaped.
- Do not clear for timeout/busy/low-novelty/empty LLM/cancellation absent independent stale/missing proof.

### Step 6 — Focused tests

Create only `tests/test_bf666_force_describe_cache_expiry.py`. Implement all required behaviors from main prompt Section 6:

- prompt-freshness stale clear;
- freshness-disabled retention bound;
- missing preflight + repeated-call no-reread;
- all-alias vs nonmatching preservation;
- concurrent newer different SHA;
- same SHA/newer capture;
- exists-true/read-missing TOCTOU;
- post-process reap plus concurrent newer-write survival;
- out-of-order `_handle()` monotonicity;
- independent session/global monotonicity;
- equal timestamp replacement;
- unexpected exists/read errors;
- cancellation independently at preflight and process, with force-lock reuse;
- stale camera-off WM non-reanimation;
- fresh upload restoration; and
- real-supervisor low-novelty cache preservation without ambient LLM;
- empty-string/`None` and missing-session global fallback;
- concurrent force-call bounded-no-queue/no-reread plus permit-wait cancellation; and
- `_handle()` with no inbound `captured_at` exact-clear behavior; and
- non-finite timestamp rejection without cache poisoning.

Use real config/store/consumer/WM where behavior crosses those seams. Obtain the shared store through a real runtime's public `attachment_store` property or the established `_get_attachment_store(runtime)` fixture helper, then instrument only public `exists`/`read`/`unlink` methods. Do not patch the helper, seed `_ATTACHMENT_STORE_CACHE`, set a private/phantom runtime store field, or access private store state. Use typed event-gated async callables/delegating stores only for races/errors. No arbitrary sleeps and no MagicMock-created storage API.

### Step 7 — Correct the AD-746a mirror fixture

- Modify only `test_force_describe_resolves_mirrored_sha_without_handle` and minimal helper/import plumbing in `tests/test_ad746a_force_describe_mirror.py`.
- Use `tmp_path`, a real `FilesystemAttachmentStore`, a valid 64-hex SHA, and a stored blob.
- Keep `_process()` stubbed with a fully annotated async signature; accept/assert the private `cache_candidate` keyword.
- Keep the no-`_handle()` mirror headline and both other AD-746a test behaviors.
- Do not add a production malformed-SHA or missing-blob bypass.

### Step 8 — Focused then blast gates

Run the exact commands below. Fix only BF-666 regressions within the allowlist. A reproducible need outside it is a hard stop.

### Step 9 — Final scope, whitespace, and deletion audit

Without staging:

- inspect `git status --short`;
- run `git diff --check` for tracked edits;
- run direct no-index whitespace checks for the two Architect docs and new test;
- confirm every path is allowlisted;
- run deletion sanity against exact base;
- inspect production diff for private-store access, task/lifecycle/config/router drift, catch ordering, lock-over-await, SHA-only clear, and public signature changes.

### Step 10 — Conditional closeout

Only if the orchestrator explicitly directs closeout after review:

- update `PROGRESS.md` only, with exact focused/blast counts and #1032;
- retain the prompt pair in `prompts/`;
- leave `DECISIONS.md`, roadmap, era files, issue metadata, and GitHub untouched;
- stage only allowlisted paths;
- rerun staged deletion sanity;
- commit exactly `BF-666: evict expired force-describe frame refs (closes #1032)`.

Do not autonomously stage, commit, push, or run any `gh` command. The commit trailer closes #1032 only when an authorized push reaches GitHub.

---

## Exact test gates

Run from `D:\ProbOS`.

### Focused

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf666_focused_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf666_force_describe_cache_expiry.py tests/test_ad733c1_force_describe.py tests/test_ad746a_force_describe_mirror.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

### Blast radius

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf666_blast_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf666_force_describe_cache_expiry.py tests/test_ad720_attachment_store.py tests/test_ad733_frame_endpoint.py tests/test_ad733_2_screen_source.py tests/test_camera_frame_origin.py tests/test_ad733a_vision_consumer.py tests/test_ad733c1_force_describe.py tests/test_ad742f_wm_persistence.py tests/test_ad746_vision_aggregator.py tests/test_ad746a_force_describe_mirror.py tests/test_ad978_group_perception.py tests/test_bf617_shared_meeting_vision.py tests/test_bf620_shared_meeting_vision_restart.py tests/test_bf624_stale_meeting_vision_refresh.py tests/test_attachment_reaper.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Do not run `tests/` broadly, use xdist/`-n auto`/`-n 4`, contact a live vision/LLM endpoint, use pytest cache, or query the operator's live runtime data during Builder gates.

---

## Final repository audit

### Status, tracked whitespace, and scope

```powershell
Set-Location 'D:\ProbOS'
git status --short
git diff --check
git diff --name-only 2d595dad0df6d0a1daeed8d02d8e5d324cd483f5 --
```

Expected unstaged paths after implementation:

```text
 M src/probos/perception/consumer.py
 M tests/test_ad746a_force_describe_mirror.py
?? prompts/bf-666-perception-force-describe-cache-expiry.md
?? prompts/bf-666-perception-force-describe-cache-expiry-execution.md
?? tests/test_bf666_force_describe_cache_expiry.py
```

`PROGRESS.md` appears only after explicit closeout direction.

### Untracked-file whitespace

`git diff --check` ignores untracked files. Before any staging, run:

```powershell
git diff --no-index --check -- NUL prompts/bf-666-perception-force-describe-cache-expiry.md
git diff --no-index --check -- NUL prompts/bf-666-perception-force-describe-cache-expiry-execution.md
git diff --no-index --check -- NUL tests/test_bf666_force_describe_cache_expiry.py
```

Exit code 1 is expected because each file differs from empty; any emitted whitespace-error line is unacceptable.

### Pre-commit deletion sanity

Run before staging, and again against `--cached` only if commit is explicitly authorized:

```powershell
$allowedDeleted = @()
$deleted = @(git diff --diff-filter=D --name-only 2d595dad0df6d0a1daeed8d02d8e5d324cd483f5 --)
$unexpected = @($deleted | Where-Object { $_ -notin $allowedDeleted })
if ($unexpected.Count -gt 0) {
    throw "Unexpected deleted paths: $($unexpected -join ', ')"
}
```

For an explicitly authorized staged commit:

```powershell
$stagedDeleted = @(git diff --cached --diff-filter=D --name-only --)
if ($stagedDeleted.Count -gt 0) {
    throw "Unexpected staged deleted paths: $($stagedDeleted -join ', ')"
}
```

No deletion or archive move is authorized.

---

## Hard stops

Stop immediately and return exact evidence if:

- base HEAD or initial tree differs from pre-flight;
- a third pre-existing file is modified/untracked/staged;
- an orchestrator reports BF-665 CI failure or base movement before implementation;
- another production cache writer/caller/owner appears;
- production correctness needs any file beyond `consumer.py`;
- test correctness needs an existing test edit beyond the authorized AD-746a fixture or another new test file;
- a public/sealed signature, config field/default, AttachmentStore protocol, retention policy, router, runtime/startup/shutdown, aggregator, or WM schema must change;
- one synchronous cache lock cannot cover `record_uploaded_frame()` and async-path non-awaiting cache sections without signature churn;
- the cache lock is held across an await, the force permit can over-release/swallow cancellation/meaningfully queue callers, or `_describe_lock` is reused/broadened;
- any write can regress a newer timestamp or global/session comparisons become coupled;
- any clear uses SHA/session/all-cache instead of exact complete tuple;
- one exact stale alias can survive while another matching alias clears;
- a concurrent different-SHA or same-SHA/newer-time replacement can be erased;
- `exists()` is treated as authoritative and read-race handling is omitted;
- expected absence still WARNs or unexpected backend errors are swallowed/clear the candidate;
- cancellation is swallowed, converted to `None`, leaks state, leaves either lock held, or clears a valid candidate;
- low-novelty, upload mirror, session/global fallback, BF-304, WM sentinel/persistence, observer/episode, or ref-only wire behavior cannot remain intact;
- a task/callback/poll/reaper coupling, retention extension, camera-stop API, private store access, UI, dependency, AD, or `DECISIONS.md` edit appears;
- the unrelated `VisionAggregator.stop()` shutdown gap is pulled into scope;
- focused/blast failure reproduces serially and cannot be fixed within allowlist;
- any deletion/archive move appears; or
- stage/commit/push/GitHub mutation is not explicitly directed by the orchestrator.

Do not guess through a hard stop.

---

## Builder report

Return without staging/committing unless directed:

- verdict and concise implementation summary;
- exact files changed/created;
- cache candidate type, lock type, and proof no await occurs under it;
- force-call guard proof that a concurrent caller returns without queuing/store work;
- monotonic session/global write results, including equal timestamp;
- exact all-alias clear behavior;
- different-SHA and same-SHA/newer-time race results;
- stale age calculation for freshness-on and freshness-disabled;
- preflight-missing, exists→read TOCTOU, and post-process-reap results;
- first-call vs second-call storage/LLM counts;
- expected-vs-unexpected logging results;
- cancellation propagation/task-cleanup result;
- missing-`captured_at` exact candidate propagation result;
- AD-746a real-store fixture correction result;
- low-novelty, fresh upload, session/global fallback, BF-304, and camera-off WM preservation results;
- focused and blast exact pass counts;
- `git status --short`, `git diff --check`, all three no-index checks, and deletion sanity result;
- any deviation or hard stop.

No UI report is needed because no UI work is authorized.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
