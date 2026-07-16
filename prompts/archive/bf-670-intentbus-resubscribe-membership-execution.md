# BF-670 Builder Execution — Replace stale IntentBus re-subscribe memberships

**Verdict:** APPROVED / EXECUTABLE AT THE PINNED CLEAN BASE
**GitHub issue:** seangalliher/ProbOS#1037 — https://github.com/seangalliher/ProbOS/issues/1037
**Exact base:** `9a23705e5f4fa41d5dcc02209496bdcff56f09e7`
**Exact base commit:** `BF-671: unify chat and call audio control (closes #1038)`
**Scope:** Execute only `prompts/bf-670-intentbus-resubscribe-membership.md`. BF-670 is an OSS mesh-routing bug fix; no new AD, public API, config, dependency, UI, decision, or roadmap work.
**Numbering:** current highest is **AD-1122 / BF-671**; issue #1037 reserves **BF-670**.
**License disposition:** none.

## Pre-flight — exact base and authorized initial tree

Before implementation, test edits, staging, commit, or any mutation beyond the two Architect docs already present:

1. Read `.github/copilot-instructions.md`, `prompts/_TEMPLATE.md`, `prompts/review-criteria.md`, and the complete main BF-670 prompt.
2. `git rev-parse HEAD` must equal exactly `9a23705e5f4fa41d5dcc02209496bdcff56f09e7`.
3. `git rev-parse origin/main` must equal the same SHA.
4. `git status --short` must show exactly these two untracked Architect files and nothing else:
   - `?? prompts/bf-670-intentbus-resubscribe-membership.md`
   - `?? prompts/bf-670-intentbus-resubscribe-membership-execution.md`
5. There must be no staged path, tracked modification, deletion, generated output, or other untracked file.
6. Read issue #1037 read-only if needed. Do not comment, close, label, assign, or edit it.
7. If base/origin/status differs, stop. Do not fetch, pull, rebase, merge, cherry-pick, reset, checkout, clean, stash, restore, or repair the tree.
8. Do not stage, commit, push, edit `PROGRESS.md`, or mutate Git/GitHub during Builder execution.

The autonomous orchestrator may perform Architect-controlled review/closeout later. The Builder itself returns an uncommitted implementation.

## Read first

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/review-criteria.md`
- `prompts/bf-670-intentbus-resubscribe-membership.md` — **binding; read fully**
- `src/probos/mesh/intent.py` — complete file, especially `subscribe`, NATS/JetStream adapters, `unsubscribe`, `send`, `broadcast`, `dispatch_async`, and `_invoke_handler`
- `src/probos/self_mod_manager.py` — reference only; no production edit
- `src/probos/agent_onboarding.py` — reference only
- all eight production subscription sites listed in the main prompt — reference only
- `tests/test_intent.py`
- `tests/test_correction_runtime.py`
- every test file in both exact gate commands before changing assertions
- `prompts/bf-668-intent-handler-latency-classes.md` — reference for callable/class sidecar and in-flight snapshot contracts
- `prompts/bf-668-intent-handler-latency-classes-execution.md` — reference only

Do not implement from this summary alone. Main-prompt DD-1 through DD-6, required tests, acceptance criteria, do-not-build list, hard stops, and verified evidence are binding.

---

## Exact authorized files

### Builder may modify production — exactly one file

- `src/probos/mesh/intent.py`

### Builder may modify existing tests — exactly two files

- `tests/test_intent.py`
- `tests/test_correction_runtime.py`

### Architect documents — retain byte-for-byte

- `prompts/bf-670-intentbus-resubscribe-membership.md`
- `prompts/bf-670-intentbus-resubscribe-membership-execution.md`

### Architect-controlled closeout — Builder must not edit

- `PROGRESS.md`

No new source or test file is authorized. No other source, test, config/YAML, workflow, standing order, UI, dependency/lockfile, tracker, roadmap, decision, era, archive, data/log, prompt, Git, or GitHub path is authorized.

Reference/run-only gate files must remain unchanged. A needed edit outside this allowlist is a hard stop.

---

## Highest-risk constraints — redundant standing order

1. **Exact membership, not additive union.** Successful same-ID `subscribe()` leaves the ID in exactly the newly supplied truthy intent-name sets.
2. **Sweep all old memberships first.** Removing only names not present in the new sequence via partial logic is unnecessary and risks drift; use one all-values discard helper.
3. **Preserve empty keys.** Discard IDs from sets; never delete keys or rebuild the dict from non-empty values.
4. **Known-empty differs from never-indexed.** Existing broadcast behavior depends on `dict.get()` returning an empty set versus `None`.
5. **`None` and `[]` mean fallback.** Both produce zero memberships. Do not add validation or distinguish them.
6. **No name validation expansion.** Duplicate names retain set semantics; an empty string in a truthy list retains current key behavior. No coercion/rejection work.
7. **Validation before mutation.** Existing `latency_class` enum check remains the only subscribe validation. The helper runs only after it succeeds.
8. **Raw callable map stays raw.** `_subscribers[agent_id]` remains the handler; do not wrap subscriber state.
9. **BF-668 sidecar stays aligned.** Re-subscribe replaces handler and `HandlerLatencyClass`; in-flight broadcast retains its old captured pair.
10. **One private helper.** It touches `_intent_index` values only, returns `None`, contains no await/task/log, and is reused by unsubscribe.
11. **Never call public unsubscribe from subscribe.** That would remove the queue and tear down NATS/JetStream state.
12. **Queue survives replacement.** Registered cognitive queue identity must remain untouched.
13. **No transport teardown.** Re-subscribe must not call `remove_tracked_subscription` or `delete_consumer`.
14. **Existing subscribe scheduling remains.** Do not redesign/deduplicate same-ID NATS or JetStream subscribe tasks in BF-670.
15. **Targeted send ignores membership.** Preserve direct and NATS targeted delivery to the current replacement handler.
16. **Do not edit broadcast.** Candidate filtering is correct once the index is correct.
17. **Do not edit `_invoke_handler`.** BF-668 metrics/warnings/errors/cancellation remain exact.
18. **Completion order and cancellation remain exact.** One task per candidate, concurrent start, completion-order results, timeout cancellation/no sample.
19. **Federation remains after local resolution.** Enabled/disabled behavior and remote result merge are unchanged.
20. **Hot replacement behavior must be real.** `tests/test_correction_runtime.py` uses a real `IntentBus`, not a mocked bus, to prove changed descriptors cannot dispatch patched code through the old intent.
21. **No self-mod production edit.** Use narrow unrelated fakes around the real bus. Do not fix the unrelated unawaited registry call or `_id`/`id` mismatch.
22. **No public/reverse API.** No reverse index, lock, generation, config, event, metric, persistence, endpoint, or protocol.
23. **No new file.** Extend existing tests only.
24. **No Builder closeout.** Builder leaves `PROGRESS.md`, staging, commit, push, and GitHub untouched.

---

## Ordered Builder checklist

### Step 1 — Pre-flight and fail-before

- Confirm exact SHA/origin/two-doc-only tree.
- Re-grep the live `subscribe()`/`unsubscribe()` signatures and all eight production subscribe sites.
- Add the three headline counterfactual tests before production edits:
  1. old→new stale membership invokes new handler on old intent;
  2. indexed→`None`/`[]` fails fallback restoration;
  3. real self-mod replacement with changed descriptors leaves old route live.
- Run only those nodes and record exact fail-before assertion reasons.
- Do not run a broad baseline; Architect baselines are pinned below.

### Step 2 — Implement the index-only helper

In `IntentBus`, add one private typed helper that loops over `self._intent_index.values()` and calls `discard(agent_id)`.

Hard gate:

- no key deletion;
- no state touch outside the index values;
- no await/task/log/reverse map;
- idempotent for an unknown ID.

### Step 3 — Wire authoritative replacement and unsubscribe reuse

- Keep the exact public `subscribe()` signature.
- Keep existing latency-class validation first.
- Preserve raw handler/class replacement.
- Invoke the helper once before adding supplied names.
- Preserve the existing `if intent_names` set-creation/add loop.
- Preserve the complete NATS/JetStream scheduling block.
- Replace only unsubscribe's duplicate inline sweep with the helper.
- Preserve handler/class/queue removal and NATS/JetStream teardown order.

Hard gate: do not call `unsubscribe()` from `subscribe()`.

### Step 4 — Complete direct regression matrix

In `tests/test_intent.py`, implement the main prompt's parameterized set-algebra, fallback, validation-no-mutation, queue identity, transport-no-teardown, targeted delivery, and unsubscribe cases.

Extend the existing in-flight BF-668 snapshot case rather than adding a second near-duplicate. After replacement, it must prove old intent is silent and new intent uses the new handler/class.

Use real bus behavior. Narrow fakes are permitted only for transport teardown recording; do not mock the membership owner itself.

### Step 5 — Real hot-replacement integration

In the existing hot-replacement section of `tests/test_correction_runtime.py`:

- replace/extend the mocked-bus-only BF-668 assertion with a real bus;
- old membership is `old.intent`;
- patched class declares `new.intent` only;
- run real `_apply_agent_correction()`;
- prove callable/class replacement, known-empty old key, no old dispatch, one new dispatch;
- use narrow fakes for unrelated registry/spawner/pool/capability collaborators.

Do not edit self-mod production.

### Step 6 — Exact focused and blast gates

Run the two exact commands below. Fix only BF-670 regressions inside the three-file implementation/test allowlist. A serial failure needing another file is a hard stop.

### Step 7 — Three-pass self-review and scope audit

Perform all three passes in the main prompt. Keep both Architect docs byte-for-byte. Do not stage or edit `PROGRESS.md`.

### Step 8 — Stop and hand back

Return the uncommitted diff and required report to the Architect/orchestrator. Do not stage, commit, push, or mutate issue #1037.

After final Architect approval, the orchestrator alone may:

- update only `PROGRESS.md`;
- stage explicit allowlisted paths;
- commit exactly `BF-670: replace IntentBus re-subscribe memberships (closes #1037)`;
- decide whether to push/close through the existing commit trailer flow.

---

## Exact gates

Run from `D:\ProbOS`.

Both commands use unique temporary `PROBOS_DATA_DIR`, `PROBOS_EMBEDDINGS=local`, `-n 0`, `--timeout=90`, `-p no:cacheprovider`, and `-W error::RuntimeWarning` exactly as required.

Clean-HEAD baselines:

| Gate | Baseline |
|---|---:|
| Focused | 106 passed in 2.79s |
| Blast | 306 passed in 316.81s |

Report exact post-build counts, skips, failures, and durations. Counts must be observed, not projected.

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf670_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_intent.py tests/test_ad470_intent_bus_enhancements.py tests/test_performance_p0.py tests/test_correction_runtime.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf670_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_targeted_dispatch.py tests/test_ad637z_nats_cleanup.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_bf296_intent_bus_close.py tests/test_federation.py tests/test_onboarding.py tests/test_cognitive_skill_596b.py tests/test_ad733a_vision_consumer.py tests/test_ad746_vision_aggregator.py tests/test_yeoman_agent.py tests/test_runtime.py tests/test_sif.py tests/test_ad843c1_device_actuation.py tests/test_ad843c2_device_consensus.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Do not substitute parallel xdist, full `tests/`, live model/network, or live platform data. Do not add `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`; this packet's required environment is exact.

---

## Deletion, whitespace, and scope audit

Run from `D:\ProbOS` without staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D 9a23705e5f4fa41d5dcc02209496bdcff56f09e7 --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/bf-670-intentbus-resubscribe-membership.md
git diff --no-index --check -- NUL prompts/bf-670-intentbus-resubscribe-membership-execution.md
```

For each no-index command, exit code `1` is expected because the untracked file differs from empty; any emitted whitespace diagnostic is a failure.

Expected final status is exactly:

- `M src/probos/mesh/intent.py`
- `M tests/test_intent.py`
- `M tests/test_correction_runtime.py`
- `?? prompts/bf-670-intentbus-resubscribe-membership.md`
- `?? prompts/bf-670-intentbus-resubscribe-membership-execution.md`

There must be no deletion, staged path, `PROGRESS.md`, new test/source file, config/YAML, generated output, UI, dependency, tracker, Git, or GitHub mutation.

Hash both Architect docs at Builder start/end and report equality. Do not edit them.

---

## Required Builder report

Return a concise table containing:

- exact base/origin and initial two-doc-only status;
- fail-before node IDs and exact stale-membership/fallback/hot-replacement reasons;
- exact three changed implementation/test files plus two unchanged prompt docs;
- helper name and proof it touches only index values/leaves keys;
- final disjoint/subset/superset/overlap/repeated/duplicate-name membership results;
- `None`/`[]` fallback and fallback→indexed results;
- invalid latency-class full no-mutation evidence;
- in-flight old handler/class versus later old-silent/new-current behavior;
- raw callable and BF-668 sidecar alignment;
- queue identity across re-subscribe;
- proof re-subscribe called neither targeted-NATS removal nor JetStream delete;
- targeted direct/broadcast behavior;
- unsubscribe full teardown and empty-key behavior;
- real hot-replacement old/new route result;
- focused/blast exact counts/skips/failures/durations;
- confirmation targeted send, NATS/prefix, JetStream, dispatch_async, cognitive queues, close/in-flight, completion order, timeout cancellation, metrics, and federation stayed green;
- three-pass review verdict;
- deletion/whitespace/scope audit;
- prompt hash equality;
- license `none`;
- confirmation of no tracker/stage/commit/push/GitHub mutation;
- unresolved hard stops, if any.

---

## Stop conditions

Stop and report to the Architect if:

- exact base/origin/two-doc-only tree fails;
- a needed file is outside the allowlist;
- correctness needs a reverse index, lock, public API, validation expansion, config, event, metric, persistence, dependency, or new file;
- empty keys must be deleted or known-empty/no-index behavior changes;
- subscribe must call unsubscribe or tear down/recreate queue/NATS/JetStream state;
- broadcast, `_invoke_handler`, send, dispatch_async, queue, close, federation, BF-668 telemetry, or production self-mod needs an edit;
- the real hot-replacement behavior cannot be tested through the existing seam with a real bus and narrow unrelated fakes;
- a serial gate failure requires an unallowlisted edit, skip, quarantine, weak assertion, or broad run;
- either prompt changes, a deletion/bulk reformat appears, or any tracker/staging/commit/push/GitHub mutation occurs.

Do not guess around a hard stop.

## Do NOT build

- Do not redesign routing, add a reverse index/cache/lock/generation, or wrap subscribers.
- Do not change public signatures/protocols/messages/descriptors/agents.
- Do not add intent-name/handler/ID validation or normalization.
- Do not delete empty index keys.
- Do not call `unsubscribe()` from `subscribe()`.
- Do not unregister queues or remove/recreate/deduplicate NATS/JetStream subscriptions during replacement.
- Do not edit broadcast/task creation/invoke/metrics/warnings/errors/cancellation/completion order.
- Do not edit targeted send, NATS, JetStream, dispatch_async, cognitive queues, close/shutdown, federation, trust, Hebbian, consensus, capability, onboarding, registry, pool, or self-mod production.
- Do not fix unrelated SelfModManager registry-await or identity-field issues.
- Do not add config/YAML/env/dependency/event/endpoint/persistence/UI/log/metric/tracker/AD/decision/roadmap/era changes.
- Do not add a test/source file or edit blast-only tests.
- Do not stage, commit, push, or mutate GitHub.

## Acceptance

The Builder handoff is complete only when every main-prompt acceptance criterion is behaviorally proven, the two exact gates pass, final status is exactly five authorized paths, both Architect docs are byte-identical, and the uncommitted implementation/report returns to the Architect.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Three-pass Architect packet review (2026-07-16)

**Verdict:** ✅ APPROVED FOR BUILDER

### Required

- None. The issue's stale-membership assumption reproduces at exact HEAD.

### Recommended

- Keep the test matrix parameterized and reuse the existing in-flight snapshot case; avoid repetitive fixtures.

### Nits

- None.

### Verified

- Exact clean base and origin are `9a23705e`.
- Current highest is AD-1122/BF-671; BF-670 is reserved by #1037.
- Exactly eight production subscribe sites and zero production direct unsubscribe sites were enumerated.
- The smallest production change is one private values-only discard helper plus two call sites in `intent.py`.
- BF-668 callable/class snapshot, targeted send, NATS/JetStream, queues, close, completion/cancellation, and federation are covered by exact gates.
- Hot replacement is a real trigger, but its existing test is mock-only; the packet corrects it to a real-bus behavior test without authorizing self-mod production edits.
- Tracker precedent supports `PROGRESS.md` only; no decision/roadmap entry.
- Exact focused/blast baselines are green: 106 and 306 passed.
