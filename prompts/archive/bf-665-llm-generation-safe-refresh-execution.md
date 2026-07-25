# BF-665 Builder Execution — Generation-safe shared LLM refresh

**Verdict:** APPROVED FOR BUILDER
**GitHub issue:** #1031 — https://github.com/seangalliher/ProbOS/issues/1031
**Exact base:** `5e28b579765c28b86a9033a6a6b832ebe679e1c6`
**Scope:** Execute only `prompts/bf-665-llm-generation-safe-refresh.md`. BF-665 is a backend LLM-client bug fix; no AD and no UI work.

## Pre-flight — exact base and authorized initial tree

Before reading implementation details or editing:

1. `git rev-parse HEAD` must equal exactly `5e28b579765c28b86a9033a6a6b832ebe679e1c6`.
2. `git status --short` may show **only** these two architect-authored untracked files:
   - `?? prompts/bf-665-llm-generation-safe-refresh.md`
   - `?? prompts/bf-665-llm-generation-safe-refresh-execution.md`
3. There must be no staged file and no tracked modification.
4. Do not stash, restore, checkout, reset, stage, commit, push, or mutate GitHub state during pre-flight.
5. Any base/tree difference is a hard stop for Architect re-verification.

Current numbering at this exact base is AD-1121 / BF-664. Use the issue-reserved BF-665 only. Do not mint an AD or edit `DECISIONS.md`.

## Read first

- `.github/copilot-instructions.md`
- `prompts/bf-665-llm-generation-safe-refresh.md`
- `prompts/bf-659-llm-endpoint-concurrency-correctness.md`
- `prompts/bf-659-llm-endpoint-concurrency-correctness-execution.md`
- `src/probos/cognitive/llm_client.py`
- `src/probos/config.py`
- `src/probos/types.py`
- `src/probos/startup/shutdown.py`
- `tests/test_bf612_empty_content_retry.py`
- `tests/test_bf654_endpoint_concurrency_cap.py`
- `tests/test_llm_client.py`
- `tests/test_bf069_llm_health.py`
- `tests/test_bf246_llm_health_probe.py`
- every reference/run-only blast file listed in the main prompt before final gate

Do not implement from this execution summary alone. The main prompt’s DD-1 through DD-10 are binding.

---

## Exact allowlist

### Builder may modify

- `src/probos/cognitive/llm_client.py`
- `tests/test_bf612_empty_content_retry.py`
- `tests/test_bf654_endpoint_concurrency_cap.py`
- `tests/test_llm_client.py`
- `tests/test_bf069_llm_health.py`
- `tests/test_bf246_llm_health_probe.py`

### Already present; include in an authorized final commit but do not rewrite or archive

- `prompts/bf-665-llm-generation-safe-refresh.md`
- `prompts/bf-665-llm-generation-safe-refresh-execution.md`

### Conditional closeout only, and only if the orchestrator explicitly directs it

- `PROGRESS.md`

No new test file is authorized. No other source, test, config, workflow, UI, tracker, roadmap, decision, archive, dependency, or issue file is authorized.

---

## Highest-risk invariants — redundant standing order

1. **State is endpoint-keyed.** One pool state per `_client_key()`; sibling tiers share generation, locks, borrowers, and retired clients.
2. **`_clients` stays current-client map.** Do not replace its `httpx.AsyncClient` values with wrappers; verified tests inject `MockTransport` clients there.
3. **Every production transport borrower leases.** Both completion transports and `_check_endpoint()` acquire/release a generation lease. Direct low-level `_call_openai()`/`_call_ollama_native()` tests with caller-owned clients do not.
4. **Health is background capacity.** Probe explicitly overrides `_ENDPOINT_GOVERNED` to `True` with token/reset, then uses the existing endpoint semaphore plus lifetime lease. It must not inherit CRITICAL bypass. CRITICAL completion itself still bypasses the endpoint semaphore.
5. **Lock order:** lane → endpoint → refresh → state. Never acquire upward; never await transport/sleep/close under refresh or state lock.
6. **Refresh evidence is generation.** `_refresh_client(tier, *, observed_generation)` swaps only if that generation is still current. A stale caller does nothing.
7. **Atomic swap has no await.** Build + current-map install + generation increment + retirement mutation form one state-lock critical section. Cancellation before the lock changes nothing; cancellation after the swap may only delay propagation until retirement cleanup drains.
8. **Close beats queued refresh.** Refresh rechecks the client-wide/endpoint closing gates under the state lock and cannot publish after close admission shuts.
9. **Close only retired zero-borrower generations.** No refresh closes a leased peer. The final borrower or the swapper is the unique closer; close outside all locks.
10. **No fire-and-forget cleanup.** Locally retain, shield, drain, then propagate cancellation. Never `ensure_future`; never swallow `CancelledError`.
11. **Permit scope stays BF-659-correct.** Endpoint permit spans jitter/refresh/retry and 429 backoff; each network call has its own shorter lifetime lease.
12. **Refresh budget is `(client_key, generation)`.** Do not retain `_refreshed_tiers` as the correctness guard. One request cannot refresh the same shared generation through sibling tiers.
13. **Persistent empty is failure.** After one refresh retry, revalidate `content/content_blocks/error/api_format`; if still empty, exactly one tier failure, dwell reset, `last_failure`, no `last_success`, no cache, then fallback.
14. **Cache precedence stays.** “All tiers empty → error” is tested on a cache miss. Existing cache fallback remains.
15. **Tool/Ollama boundaries stay.** Tool-call blocks are successful; Ollama completion remains non-refreshing. Health may reject an empty Ollama HTTP 200 but never refresh it.
16. **Probe cannot recover on empty.** Empty/malformed HTTP 200 returns false and resets partial success dwell; it does not increment/clear failure count or refresh.
17. **No production fallback for incomplete `__new__` tests.** Update the BF-069 fixture to the real private state shape or use the constructor.
18. **No public/sealed churn.** Preserve `complete`, `_complete_inner`, `_endpoint_permit`, `_check_endpoint`, `_call_api`, request, response, and tier contracts except the explicitly authorized private `_refresh_client` signature.
19. **Generation-aware close.** Stop health first, close lease admission, wait without polling for admitted borrowers, then close current+retired distinct clients once. Second close is a no-op; cancellation propagates only after cleanup.
20. **No UI/config/dependency change.** This is one backend lifecycle fix.

---

## Ordered checklist

### Step 1 — Baseline contract capture

- Confirm the two production `_clients` transport lookup paths by grep.
- Record initial `_clients`/endpoint-key dedupe behavior.
- Read all existing BF-612 and BF-659 cancellation tests before edits.
- Do not run a broad baseline suite; the user explicitly reserved broad testing for the Builder after implementation.

### Step 2 — Private generation state

- Add private lease/state dataclasses.
- Initialize one state per distinct current-client key after `_clients` construction.
- Preserve `_clients` values and endpoint semaphore construction.
- Run syntax/error diagnostics on `llm_client.py`.

### Step 3 — Lease and cleanup primitive

- Add `_client_lease(tier)`.
- Increment under state lock before yield.
- Release exactly once under state lock.
- Pop the sole close candidate under lock; close outside lock.
- Shield/drain cleanup under cancellation and re-raise.
- Add focused lease/retirement tests before changing refresh.

### Step 4 — Generation-conditional refresh

- Change `_refresh_client` private signature as pinned.
- Add endpoint refresh lock singleflight.
- Compare observed generation under lock.
- Build/swap/retire atomically with no await.
- Close immediately only when old generation has zero borrowers.
- Adapt direct BF-612 refresh tests.

Hard gate: N observed-G callers cause one replacement and a stale caller cannot close the replacement.

### Step 5 — Completion path

- Keep `_endpoint_permit(attempt_tier)` scope.
- Lease initial transport, release before jitter/refresh.
- Refresh from observed generation.
- Lease current generation; retry only if its generation differs from the empty response's observed generation. If client construction failed and the generation is unchanged, fail the tier without a second transport.
- Key per-call budget by endpoint generation.
- Route persistent empty into existing failure/fallback/cache envelope.
- Preserve 429, tool, Ollama, model, suffix, vision, and cache behavior.

### Step 6 — Health path

- Wrap `_check_endpoint` in endpoint permit and lifetime lease.
- Force task-local endpoint governance for the probe and reset the ContextVar in `finally`.
- Validate non-empty assistant content/reasoning for HTTP 200 only.
- Never refresh from health.
- Reset success dwell on false connectivity result; preserve failure count.

### Step 7 — Close barrier

- Stop the health task before closing lease admission.
- Reject new `_client_lease()` acquisition after the closing flag.
- Await borrower-zero notifications without sleep/polling.
- Detach and close current plus retired distinct clients exactly once outside locks.
- Prove idempotence and cancellation-deferred completion.

### Step 8 — Cancellation matrix

Behaviorally cover every main-prompt row:

- endpoint wait;
- lease state-lock wait;
- initial transport;
- jitter;
- refresh-lock wait;
- swap state-lock wait;
- post-swap retirement close;
- retry transport;
- 429 backoff;
- final-borrower close;
- health transport.
- health invocation under an inherited CRITICAL-bypass context.
- client `close()` while a lease is active and while a client close is blocked.

After each cancellation assert exact lane/endpoint count, borrower/retired maps, generation/current-client identity, close count, and no lingering cleanup task. Use Events/locks; do not rely on arbitrary sleeps.

### Step 9 — Focused then blast gates

Run the exact commands below. Fix only BF-665 regressions within the allowlist. A reproducible need outside the allowlist is a hard stop.

### Step 10 — Final diff and deletion audit

Before any requested closeout:

- inspect `git status --short`;
- run `git diff --check` for tracked edits;
- because the prompt files began untracked, also run the direct no-index whitespace checks below;
- confirm every changed path is allowlisted;
- run deletion sanity check against the base;
- inspect the production diff for accidental fallback/retry/cache/model/vision/config changes.

### Step 11 — Conditional closeout

Only if the orchestrator explicitly directs commit/closeout after review:

- update `PROGRESS.md` only, with exact counts;
- keep the two prompt files in `prompts/` (current BF-659/661/662/664 convention; do not archive);
- leave `DECISIONS.md`, roadmap, era files, and issue metadata untouched;
- stage only allowlisted paths;
- re-run deletion sanity check on the staged diff;
- commit exactly `BF-665: make shared LLM refresh generation-safe (closes #1031)`.

Do not push and do not run `gh issue close` unless separately directed. The Builder does not autonomously commit, push, or close the issue.

---

## Exact test gates

Run from `D:\ProbOS`.

### Focused

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf665_focused_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf612_empty_content_retry.py tests/test_bf654_endpoint_concurrency_cap.py tests/test_llm_client.py tests/test_bf069_llm_health.py tests/test_bf246_llm_health_probe.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

### Blast radius

```powershell
Set-Location 'D:\ProbOS'
$gateDir = Join-Path $env:TEMP ("probos_bf665_blast_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $gateDir | Out-Null
$env:PROBOS_DATA_DIR = $gateDir
$env:PROBOS_EMBEDDINGS = 'local'
try {
    & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_bf612_empty_content_retry.py tests/test_bf654_endpoint_concurrency_cap.py tests/test_llm_client.py tests/test_bf069_llm_health.py tests/test_bf246_llm_health_probe.py tests/test_ad463_model_routing.py tests/test_ad543_tool_call_protocol.py tests/test_ad617_llm_rate_governance.py tests/test_ad636_llm_priority_scheduling.py tests/test_ad637f_priority.py tests/test_ad706c2_compute_use.py tests/test_ad720d_vision_pipethrough.py tests/test_ad730_3_agent_image_gen.py tests/test_ad731_attachment_ref_wire_format.py tests/test_ad732_vision_tier.py tests/test_ad734_wire_shape_contract.py tests/test_ad742a_vision_fast_tier.py tests/test_ad835_tier_adaptation.py tests/test_per_tier_llm.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
} finally {
    Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue
}
```

Do not run `tests/` broadly in this handoff. Do not use `-n auto`, `-n 4`, a live endpoint, or pytest cache.

---

## Final repository audit

### Tracked whitespace and scope

```powershell
Set-Location 'D:\ProbOS'
git diff --check
git status --short
git diff --name-only 5e28b579765c28b86a9033a6a6b832ebe679e1c6 --
```

### Untracked architect-document whitespace

`git diff --check` does not inspect untracked files. Before staging them, run:

```powershell
git diff --no-index --check -- NUL prompts/bf-665-llm-generation-safe-refresh.md
git diff --no-index --check -- NUL prompts/bf-665-llm-generation-safe-refresh-execution.md
```

Exit code 1 is expected because the files differ from empty; any emitted whitespace-error line is not acceptable.

### Pre-commit deletion sanity check

Run before staging, and again against `--cached` only if commit is explicitly authorized:

```powershell
$allowedDeleted = @()
$deleted = @(git diff --diff-filter=D --name-only 5e28b579765c28b86a9033a6a6b832ebe679e1c6 --)
$unexpected = @($deleted | Where-Object { $_ -notin $allowedDeleted })
if ($unexpected.Count -gt 0) {
    throw "Unexpected deleted paths: $($unexpected -join ', ')"
}
```

For an authorized staged commit:

```powershell
$stagedDeleted = @(git diff --cached --diff-filter=D --name-only --)
if ($stagedDeleted.Count -gt 0) {
    throw "Unexpected staged deleted paths: $($stagedDeleted -join ', ')"
}
```

No deletion or archive move is authorized.

---

## Hard stops

Stop immediately and report exact evidence if:

- base HEAD or initial working tree differs from pre-flight;
- a third pre-existing file is modified/untracked/staged;
- production pooled-client borrowers exceed `_complete_inner` and `_check_endpoint`;
- a fix requires config, types, public/sealed protocols, startup/shutdown, UI, dependency, EventType, or a new test file;
- `_clients` must stop containing current `httpx.AsyncClient` values;
- any path acquires locks out of lane→endpoint→refresh→state order;
- any path awaits transport/sleep/close under refresh/state lock;
- any refresh can act on a non-current observed generation;
- any client closes while its borrower count is non-zero;
- cancellation can leak ownership or requires untracked background work;
- close can poll, accept new leases, double-close, or return with owned current/retired clients;
- a queued refresh can publish after the closing gate is set;
- CRITICAL would be endpoint-throttled;
- health would bypass the endpoint cap (including through inherited CRITICAL ContextVar state) or refresh a client;
- persistent empty can reach success/cache/return or cache precedence must change;
- tool-call/Ollama/fallback/retry/RPM/429/model/vision behavior must change;
- a focused/blast failure reproduces serially and cannot be fixed within the allowlist;
- any deletion or archive move appears;
- or the orchestrator has not explicitly authorized a requested Git/GitHub mutation.

Do not guess through a hard stop.

---

## Builder report

Return, without committing unless directed:

- verdict and one-paragraph implementation summary;
- exact files changed;
- generation-state shape and exact lock order;
- proof that cap>1 in-flight peers survive refresh;
- observed N-callers/one-swap count;
- old-generation final-borrower close count;
- CRITICAL lease/bypass result;
- persistent-empty failure/fallback/all-tier-error accounting values;
- empty-probe health state before/after;
- cancellation matrix results and zero lingering cleanup tasks;
- focused and blast exact pass counts;
- `git status --short`, `git diff --check`, no-index prompt checks, and deletion sanity result;
- any deviation or hard stop.

Do not commit, push, archive prompts, edit trackers, or close #1031 unless explicitly directed by the orchestrator.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
