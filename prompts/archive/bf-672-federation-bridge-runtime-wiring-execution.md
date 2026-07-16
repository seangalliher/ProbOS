# BF-672 Builder Execution — Production-wire the FederationBridge attachment resolver

**Verdict:** APPROVED / EXECUTABLE AT THE PINNED CLEAN BASE
**Parent GitHub issue:** seangalliher/ProbOS#638 — https://github.com/seangalliher/ProbOS/issues/638
**Temporary issue draft:** `logs/bf672_issue_body.md` — ignored; do not stage or mutate GitHub
**Exact base:** `34a3425c5e1a6217a3cab2564ea437cd7de6426b`
**Exact base commit:** `BF-670: replace IntentBus re-subscribe memberships (closes #1037)`
**Scope:** Execute only `prompts/bf-672-federation-bridge-runtime-wiring.md`. BF-672 is an OSS startup/dependency-wiring bug fix; no new AD, config, endpoint, protocol, dependency, UI, decision, or roadmap work.
**Numbering:** current highest is **AD-1122 / BF-671**; **BF-672 is the next unused sequential BF**.
**License disposition:** none.

## Pre-flight — exact base and authorized initial tree

Before implementation, test edits, staging, commit, or any mutation beyond the two Architect docs and ignored draft already present:

1. Read `.github/copilot-instructions.md`, `prompts/_TEMPLATE.md`, `prompts/review-criteria.md`, and the complete main BF-672 prompt.
2. `git rev-parse HEAD` must equal exactly `34a3425c5e1a6217a3cab2564ea437cd7de6426b`.
3. `git rev-parse origin/main` must equal the same SHA.
4. `git status --short` must show exactly these two untracked Architect files and nothing else:
   - `?? prompts/bf-672-federation-bridge-runtime-wiring.md`
   - `?? prompts/bf-672-federation-bridge-runtime-wiring-execution.md`
5. `logs/bf672_issue_body.md` is ignored and must exist, but must not appear in status or be staged.
6. There must be no staged path, tracked modification, deletion, generated output, or other untracked file.
7. Read issue #638 read-only if needed. Do not comment, close, label, assign, or edit it. BF-672 does not close #638.
8. If base/origin/status/draft differs, stop. Do not fetch, pull, rebase, merge, cherry-pick, reset, checkout, clean, stash, restore, or repair the tree.
9. Do not stage, commit, push, edit `PROGRESS.md`, archive prompts, or mutate Git/GitHub during Builder execution.

The Builder returns an uncommitted implementation. Architect/orchestrator controls review, closeout, archival, commit, and any later GitHub action.

## Read first

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/review-criteria.md`
- `prompts/bf-672-federation-bridge-runtime-wiring.md` — **binding; read fully**
- `src/probos/federation/bridge.py` — complete
- `src/probos/federation/attachment_resolve.py` — complete; reference only
- `src/probos/federation/attachment_fetch.py` — reference only
- `src/probos/startup/fleet_organization.py` — complete
- `src/probos/runtime.py` — imports/types, constructor federation attrs, full `start()`, federation methods, startup-complete boundary
- `src/probos/startup/finalize.py` — federation servers + self-mod manager construction; reference only
- `src/probos/startup/shutdown.py` — federation shutdown block; reference only
- `src/probos/cognitive/agent_designer.py` — complete; reference only
- `src/probos/cognitive/code_validator.py` — complete; reference only
- `src/probos/cognitive/self_mod.py` — constructor/public properties/registration path; reference only
- `tests/test_ad731a_1c_auto_resolve.py`
- `tests/test_ad479_federation_hardening.py`
- `tests/test_federation_nats.py`
- `tests/test_ad447_phase_gates_pool_group.py`
- every reference-only test in both exact gates before changing assertions
- `logs/bf672_issue_body.md` — read-only during build

Do not implement from this execution summary alone. The main prompt's DD-1 through DD-7, required tests, acceptance criteria, do-not-build list, hard stops, and verified evidence are binding.

---

## Exact authorized files

### Builder may modify production — exactly three files

- `src/probos/federation/bridge.py`
- `src/probos/startup/fleet_organization.py`
- `src/probos/runtime.py`

### Builder may modify existing tests — at most four files

- `tests/test_ad731a_1c_auto_resolve.py`
- `tests/test_ad479_federation_hardening.py`
- `tests/test_federation_nats.py` — direct-call signature/integration only
- `tests/test_ad447_phase_gates_pool_group.py` — mechanical direct-call signature update only

### Architect documents — retain byte-for-byte

- `prompts/bf-672-federation-bridge-runtime-wiring.md`
- `prompts/bf-672-federation-bridge-runtime-wiring-execution.md`

### Ignored Architect issue draft — retain byte-for-byte; never stage

- `logs/bf672_issue_body.md`

### Architect-controlled closeout — Builder must not edit

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config/YAML, workflow, standing order, UI, dependency/lockfile, tracker, roadmap, decision, era, archive, data/log, prompt, Git, or GitHub path is authorized.

Reference/run-only gate files must remain unchanged. A needed edit outside this allowlist is a hard stop.

---

## Highest-risk constraints — redundant standing order

1. **Do not wire `set_runtime_ref(self)`.** That broad handle feeds both the attachment resolver and incomplete AD-479e reconstruction.
2. **No runtime back-reference under another name.** Bridge receives one narrow async callback only.
3. **Composition root owns wiring.** Runtime supplies callback to `organize_fleet`; `organize_fleet` constructor-injects it before `bridge.start()`.
4. **Headline proof must use production construction.** No direct bridge construction, setter call, private mutation, or direct resolver call in the red-before test.
5. **Ordering is load-bearing.** The injected callback completes before local broadcast; adapter delegation plus unchanged resolver tests prove that a successful real callback stores/fetches before returning.
6. **Reuse existing resolver unchanged.** Runtime adapter delegates once; no duplicated config/store/peer/fetch policy.
7. **Default-off remains real.** Callback may exist while `auto_resolve_remote_enabled=False`; resolver must call no attachment-store method and make no network request.
8. **No callback remains valid.** Direct bridge constructors keep backward-compatible no-resolution behavior.
9. **Bridge contains no runtime/cognitive/store/http dependency.** Keep federation layer narrow.
10. **Remove `_runtime_ref` and `set_runtime_ref`.** Zero definitions, reads, calls, or manual-test activation after build.
11. **AD-479e stays dormant.** `_reconstruct_designed_agent()` returns `no_runtime_handle`, depends on no registration API, and emits no receive event.
12. **Do not delete AD-479e wire surface.** Keep payload parameter/key/hook/event enum; this BF quarantines activation only.
13. **No phantom API creation.** Do not add `register_designed_template_from_payload` or `validate_text`.
14. **No private reach-through.** Never use `self_mod_pipeline._designer/_validator/_sandbox` or spawner internals.
15. **No send-side work.** Federation still strips `vision_messages`; #638 remains open.
16. **No resolver/fetch/store/config edits.** Existing hash/auth/MIME/size/idempotence behavior is authoritative.
17. **Contain ordinary callback errors; propagate cancellation.** Ordinary exceptions allow broadcast/response; `CancelledError` re-raises with no post-cancellation broadcast.
18. **No new resource.** No task/client/lock/cache/provider object or shutdown step.
19. **Lifecycle stays exact.** Bridge/transport start-stop and shutdown ordering remain unchanged.
20. **No broad tests.** Exact serial isolated gates only.
21. **No prompt/draft edits.** Hash all three Architect artifacts at start/end.
22. **No Builder closeout.** No `PROGRESS.md`, archival, staging, commit, push, or GitHub mutation.

---

## Ordered Builder checklist

### Step 1 — Pre-flight and fail-before

- Confirm exact SHA/origin/two-doc-only status and ignored draft existence.
- Re-run the production AST inventory:
  - one `FederationBridge(...)` call in `startup/fleet_organization.py`;
  - zero production `set_runtime_ref()` calls;
  - `_runtime_ref` reads at attachment and AD-479e consumers only.
- Add the headline production `organize_fleet()` test first using a real `IntentBus(SignalManager())`, a real subscribed handler that records store state at dispatch, and a recording bound callback installed on a lightweight runtime-shaped composition owner before `organize_fleet()` is called. The callback writes a known blob; do not invoke the real HTTP resolver in this headline test.
- Run only that node and record the exact failure reason: local broadcast observes the attachment missing because no production callback is installed.
- Add supporting tests only after the headline failure is proven.
- Do not run a broad baseline; Architect baseline counts are pinned below.

### Step 2 — Add the narrow bridge callback

- Add fully typed optional constructor callback at the end of the parameter list.
- Store `_attachment_resolver`.
- Remove `_runtime_ref` and `set_runtime_ref()`.
- In inbound intent handling, invoke callback before broadcast when present.
- Catch `CancelledError` separately and re-raise; ordinary exceptions log-and-continue.
- Do not edit any other bridge behavior.

### Step 3 — Add runtime adapter and Phase-3 constructor injection

- Add private fully typed `_resolve_federated_attachments()` near runtime federation methods.
- Lazy-import and delegate to the existing resolver.
- Extend internal `organize_fleet()` with a required typed callback argument.
- Pass callback into bridge constructor before start.
- Supply runtime bound method at the sole runtime call.
- Update the two direct test callers explicitly.
- Add a narrow source/AST contract assertion that the sole production `organize_fleet()` call passes `self._resolve_federated_attachments`; this supports, but does not replace, the behavioral production-construction test.

Hard gate: do not pass runtime into bridge/startup and do not use a post-start setter/private assignment.

### Step 4 — Quarantine AD-479e activation

- Make `_reconstruct_designed_agent()` explicitly return `no_runtime_handle`.
- Retain signature, async contract, payload hook, and transfer message note.
- Remove tests that manually construct fake production runtime APIs.
- Add/retain transfer-level dormant behavior proof.
- Do not edit cognitive/self-mod production.

### Step 5 — Complete boundaries

Using real config/store and no-network HTTP seams, cover:

- production callback threading/order with a recorded ref;
- runtime adapter delegation to the real resolver;
- default-off zero attachment-store method/network;
- empty/no/malformed refs and empty/unmapped source;
- already local;
- callback ordinary error;
- callback cancellation propagation with no later broadcast;
- absent callback;
- dormant incoming designed payload.

Do not duplicate every AD-731a-1 fetch test; rely on existing unchanged integrity tests for 404/500/tamper/MIME/size and add only production-wiring assertions needed to prove broadcast continuity.

### Step 6 — Exact gates

Run the two exact commands below. Fix only BF-672 regressions inside the allowlist. A serial failure needing another file is a hard stop.

### Step 7 — Three-pass self-review and scope audit

Perform all three passes in the main prompt. Keep both prompt docs and the issue draft byte-for-byte. Do not stage or edit `PROGRESS.md`.

### Step 8 — Stop and hand back

Return the uncommitted diff and required report to the Architect/orchestrator. Do not archive prompts, stage, commit, push, or mutate issue #638.

After final Architect approval only, the orchestrator may:

- update only `PROGRESS.md`;
- archive the two prompts;
- stage explicit allowlisted/approved paths (never the ignored issue draft);
- commit with a separately approved message; and
- leave #638 open until its remaining send-side scope is complete.

---

## Exact gates

Run from `D:\ProbOS`.

Both use unique temporary `PROBOS_DATA_DIR`, local/offline embeddings, `-n 0`, `--timeout=90`, `-p no:cacheprovider`, and `-W error::RuntimeWarning` exactly as required.

Clean-HEAD baselines:

| Gate | Baseline |
|---|---:|
| Focused | 228 passed in 56.64s |
| Blast | 44 passed in 206.93s |

Report exact post-build counts, skips, failures, and durations. Counts must be observed, not projected.

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf672_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad731a_1c_auto_resolve.py tests/test_ad731a_remote_attachment.py tests/test_ad731_attachment_ref_wire_format.py tests/test_bf265_transport_stripped_params.py tests/test_ad479_federation_hardening.py tests/test_federation.py tests/test_federation_nats.py tests/test_ad443_mobility.py tests/test_ad447_phase_gates_pool_group.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf672_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_runtime.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py tests/test_distribution.py::TestFastAPIEndpoints::test_create_app_returns_fastapi -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Do not substitute parallel xdist, full `tests/`, live model/network, or live platform data.

---

## Deletion, whitespace, and scope audit

Run from `D:\ProbOS` without staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D 34a3425c5e1a6217a3cab2564ea437cd7de6426b --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/bf-672-federation-bridge-runtime-wiring.md
git diff --no-index --check -- NUL prompts/bf-672-federation-bridge-runtime-wiring-execution.md
git check-ignore -v logs/bf672_issue_body.md
```

For each no-index command, exit code `1` is expected because the untracked file differs from empty; any emitted whitespace diagnostic is a failure.

Expected final status is limited to:

- `M src/probos/federation/bridge.py`
- `M src/probos/startup/fleet_organization.py`
- `M src/probos/runtime.py`
- `M tests/test_ad731a_1c_auto_resolve.py`
- `M tests/test_ad479_federation_hardening.py`
- optionally `M tests/test_federation_nats.py`
- optionally `M tests/test_ad447_phase_gates_pool_group.py`
- `?? prompts/bf-672-federation-bridge-runtime-wiring.md`
- `?? prompts/bf-672-federation-bridge-runtime-wiring-execution.md`

`logs/bf672_issue_body.md` must remain ignored and absent from status. There must be no deletion, staged path, `PROGRESS.md`, new test/source file, config/YAML, generated output, UI, dependency, tracker, Git, or GitHub mutation.

Hash both Architect docs and the ignored draft at Builder start/end and report equality. Do not edit them.

---

## Required Builder report

Return a concise table containing:

- exact base/origin and initial two-doc-only status plus ignored draft existence;
- headline fail-before node ID and exact missing-production-wire assertion;
- exact changed implementation/test files plus three unchanged Architect artifacts;
- callback type/name and constructor-before-start proof;
- runtime adapter delegation proof;
- AST proof of zero `_runtime_ref`/`set_runtime_ref` after build;
- production callback store-before-broadcast result plus real-runtime-adapter delegation result;
- default-off zero-store/zero-network result;
- empty/malformed/no-source/unmapped/local-hit results;
- callback ordinary-error continuation and cancellation-propagation results;
- no-callback compatibility result;
- AD-479e dormant transfer result and proof of no receive event or registration dependency;
- send-side strip/attachment integrity/mobility/transport/lifecycle regressions green;
- focused/blast exact counts/skips/failures/durations;
- three-pass review verdict;
- deletion/whitespace/scope audit;
- prompt/draft hash equality;
- license `none`;
- confirmation of no tracker/archive/stage/commit/push/GitHub mutation;
- unresolved hard stops, if any.

---

## Stop conditions

Stop and report to the Architect if:

- exact base/origin/two-doc-only tree/ignored draft preflight fails;
- production proof needs direct bridge construction, setter use, or private mutation;
- a needed file is outside the allowlist;
- correctness needs a runtime back-reference, second setter, config change, resolver edit, new resource/task, public API, event, metric, persistence, dependency, or new file;
- AD-479e cannot stay dormant without cognitive/self-mod production work or wire-field deletion;
- send-side strip, transport, mobility, IntentBus, startup order, or shutdown needs an edit;
- a serial gate failure requires an unallowlisted edit, skip, quarantine, weak assertion, or broad run;
- either prompt or the issue draft changes, a deletion/bulk reformat appears, or any tracker/staging/commit/push/GitHub mutation occurs.

Do not guess around a hard stop.

## Do NOT build

- Do not wire or retain a runtime back-reference.
- Do not activate or complete designed-agent rehydration.
- Do not add phantom public methods or reach through private self-mod fields.
- Do not alter send-side federation payloads or complete #638.
- Do not edit resolver/fetch/store/config/auth/endpoint/protocol/message/event/metric/status.
- Do not edit transports, router, IntentBus, mobility, startup phase order, shutdown, or UI.
- Do not add tasks/clients/locks/resources/dependencies/config/YAML/workflows/standing orders.
- Do not add a source/test file or edit blast-only tests.
- Do not edit trackers, archive prompts, stage, commit, push, or mutate GitHub.

## Acceptance

The Builder handoff is complete only when every main-prompt acceptance criterion is behaviorally proven, the two exact gates pass, final status contains only authorized paths, both Architect docs and the ignored issue draft are byte-identical, and the uncommitted implementation/report returns to the Architect.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
