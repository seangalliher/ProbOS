# AD-722b-5a Builder Execution - Federation avatar telemetry relay

**Binding specification:** `prompts/ad-722b-5a-federation-telemetry-relay.md`
**Binding SHA-256:** `d188db9eb967218fe27b56d9059f8dd4dad318e6aa24b141790013bfffc1dbad`; a mismatch is a hard stop
**Exact base:** clean `D:\ProbOS` `main` and `origin/main` at `44a697558eae15f88df5ff64dfe53ce70a23eb9e`
**Numbering:** build reserved sub-AD **AD-722b-5a** only; top-level ceiling remains **AD-1123**; BF ceiling remains **BF-672**
**GitHub:** issue #659 stays read-only; Builder must not comment, edit, label, assign, close, or otherwise mutate it
**Mode:** red-first, continuous execution through implementation/review/gates/closeout/commit; no push

---

## Decision

The architecture is settled by the binding prompt. Implement exactly one default-inert, explicitly configured avatar telemetry topic/producer/cache path on AD-1123. Palette policy B keeps the narrow wire grammar and projects every unsupported exact-string palette hint to `""` only on a detached federation copy; local WebSocket data is unchanged. The startup helper remains strict/self-cleaning and raises, while its post-`finalize_startup()` call in `ProbOSRuntime.start()` contains ordinary `Exception`, logs reason/impact/action, sets relay `None`, and completes boot; cancellation/other `BaseException` propagate. Do not redesign this into a finalization, bridge/transport, WebSocket relay, dynamic subscription protocol, open event/intent relay, remote registry, persistent store, or UI feature.

If any binding requirement is impossible on the exact base, hard-stop with the concrete missing seam. Do not improvise another file, protocol, config shape, source field, callback contract, task owner, or sink.

---

## Pre-flight: exact two-document tree

Read in full before any build edit:

1. `.github/copilot-instructions.md`
2. `prompts/ad-722b-5a-federation-telemetry-relay.md`
3. this execution document
4. the live source/test files named in the binding verification footer and allowlist
5. `prompts/archive/ad-1123-bounded-federation-relay.md`
6. `prompts/archive/ad-1123-bounded-federation-relay-execution.md`

Run:

```powershell
Set-Location 'D:\ProbOS'
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
git log -1 --format='%H%n%s'
Get-FileHash -Algorithm SHA256 prompts/ad-722b-5a-federation-telemetry-relay.md
```

Expected HEAD and origin are both:

```text
44a697558eae15f88df5ff64dfe53ce70a23eb9e
AD-1123: add bounded federation one-way relay
```

Expected status before Builder edits is exactly:

```text
## main...origin/main
?? prompts/ad-722b-5a-federation-telemetry-relay-execution.md
?? prompts/ad-722b-5a-federation-telemetry-relay.md
```

No staged path, deletion, other tracked modification, or third untracked path is allowed. Do not stash, restore, reset, clean, fetch, pull, rebase, merge, cherry-pick, switch branch, stage, commit, push, or mutate GitHub during pre-flight.

Verify the binding SHA once the Architect has populated it. Verify these frozen hashes:

| Path | SHA-256 |
|---|---|
| `src/probos/federation/relay.py` | `6809979d39f65dcbe0c7c510dff5994c725e6b3620ed0e72aa1aa590d460c70e` |
| `src/probos/federation/bridge.py` | `690a6d00a32b7e51cd25777d9b49db40433ea3269d104ca8d93393bc47b0b30f` |
| `src/probos/startup/fleet_organization.py` | `7b9e17dd24bf020ef5c2797d3601c97fac62996c5c5fa53a21a1c2a6494abbc8` |
| `src/probos/startup/finalize.py` | `211f7428270b82660cbd35fd8efee026e9a9f070511315967392ae998ee1992b` |
| `src/probos/avatars/telemetry.py` | `59986fad1161664d5f6d2d2e13258fbe06767fdcac0f4cd4cf56f61feb3a23e7` |
| `src/probos/avatars/events.py` | `d83e655966abf91747d47bba08c1fbbb5ab0d655f9d6a38087ea9f504a8ee233` |
| `src/probos/avatars/sampling_state.py` | `decd156546628a9c289fe0f46371a719bc73c3e17364e430933cc687eb905a00` |
| `src/probos/avatars/snapshot_diff.py` | `7124edaf5dfed5f15268810e8b73638d680cf83053d3f37ad8143e6f365886ab` |
| `tests/test_ad1123_bounded_federation_relay.py` | `c16b02eb5fc0b1ac5db9858480802a595b5cf7f675f4543351969677e9d740f5` |

Verify `PROGRESS.md`, `DECISIONS.md`, and roadmap still identify AD-1123/BF-672 as ceilings and #659/AD-722b-5a as open. A mismatch is a hard stop; do not renumber.

---

## Builder edit allowlist

Before closeout, edit only:

```text
src/probos/avatars/telemetry_frames.py                         NEW
src/probos/federation/telemetry_relay.py
src/probos/startup/federation_telemetry.py                    NEW
src/probos/config.py
src/probos/runtime.py
src/probos/routers/agents.py
src/probos/startup/shutdown.py
tests/test_ad722b_5a_federation_telemetry_relay.py             NEW
tests/test_ad722b_5_federation_telemetry.py
```

Architect-owned active prompts are read-only during implementation.

After all gates and Architect approval, additionally edit only:

```text
PROGRESS.md
DECISIONS.md
docs/development/roadmap.md
```

Then move these two files byte-preservingly:

```text
prompts/ad-722b-5a-federation-telemetry-relay.md
  -> prompts/archive/ad-722b-5a-federation-telemetry-relay.md
prompts/ad-722b-5a-federation-telemetry-relay-execution.md
  -> prompts/archive/ad-722b-5a-federation-telemetry-relay-execution.md
```

No other file is authorized. In particular, do not edit `startup/finalize.py`, bridge/relay primitive/transport files, `fleet_organization.py`, any other test, YAML, UI, API, event, protocol, type, registry, intent, dependency, package, data, log, workflow, era, or commercial file.

---

## Execution order

### Step 1 - Write complete tests first

Create the new AD-722b-5a module with every test category and named headline from the binding prompt, including policy-B projection/local parity and the post-finalize ordinary-error/config-error/partial-start/cancellation/sentinel-`BaseException` cases. The new module must collect at least 66 cases. Use real boundary objects and narrow typed fakes only. Do not edit production or the old eight-test module yet.

### Step 2 - Record red-before

Run the exact headline red command from binding Section 1. Then run the focused schema/rate/cache/no-subscription/lifecycle reds named there. Record command, collected count, failing test names, and exact failure reasons. Do not weaken tests.

### Step 3 - Build the pure shared frame helper

Create `avatars/telemetry_frames.py`; run its focused tests plus snapshot-diff and local WS tests. Add the exact policy-B projector there: supported wire values remain exact, every other exact string maps to `""` on a fresh federation copy, malformed/non-string shapes still reject, and no source/cursor/WS value is mutated. Keep all existing side effects and JSON shape unchanged.

### Step 4 - Build typed relay producer/schema/cache

Modify only `federation/telemetry_relay.py` and migrate the old eight tests. Apply the policy-B projection after raw frame selection and before semantic parsing/payload assembly. Enforce exact schema, task/config caps, bool callback accounting, monotonic pre-await rate claims, event/timer producer ownership, stream/sequence state, and 256-entry remote cache exactly as binding.

### Step 5 - Build config and production wiring

Add only the default-empty `PeerConfig` field, create the startup helper module, wire topic before bridge and producer after `finalize_startup()`, and add runtime read methods. The helper cleanup scope must stop/reap partial tasks/subscriptions/state and bare-raise the original ordinary or lifecycle exception. Wrap only the post-finalize helper call in runtime `try/except Exception`; on failure log the exact helper reason plus telemetry-disabled/startup-continues impact/action, set relay `None`, and continue to `_startup_complete=True`. Do not catch `CancelledError`/other `BaseException`. Then stop producer -> bridge -> clear cache -> transport at shutdown. Do not edit `startup/finalize.py`, `organize_fleet()`, or a transport/bridge file.

### Step 6 - Focused validation after each logical edit

After each production step run the narrow new tests that falsify that step before editing the next slice. If a failure supports the design and exposes a local defect, fix only that slice and rerun. If it requires another file/protocol, hard-stop.

### Step 7 - Run all binding gates and audits

Run the focused module, Gates 1-4, final full parallel gate, editor diagnostics, targeted compile, source/privacy scans, diff checks, and frozen hashes exactly as binding. Do not substitute `-n auto`, a shared data directory, online embeddings, a partial test list, or a warning downgrade.

### Step 8 - Return for Architect implementation review

Before tracker/archive/Git mutation, return the uncommitted implementation with:

- red-before evidence;
- exact changed-path list;
- new module collected/pass count;
- Gates 1-4 and full-gate results/warnings;
- task/rate/cache/schema/privacy/lifecycle evidence;
- policy-B federation-only projection plus unchanged local palette/WS evidence;
- ordinary-error containment with `_startup_complete=True`, explicit unknown/duplicate-peer/global-cap logs, zero leaked telemetry tasks/event subscriptions, and cancellation/other-`BaseException` propagation evidence;
- frozen and changed-file SHA-256;
- deviations (must be none unless this execution hard-stopped).

Do not update trackers, archive prompts, stage, commit, push, or mutate GitHub until Architect approves.

### Step 9 - Conditional closeout after approval

Apply only the tracker wording specified in binding DD-9/Section 7. Keep AD-1123/BF-672 ceilings unchanged. State configured-peer admission is not cryptographic authentication. State AD-722b-5b remains the UI/API/origin badge follow-up.

Compute both active prompt hashes, move original bytes, and verify archived hashes match exactly. Do not rewrite prompts through a patch during archival.

### Step 10 - Deletion and staging sanity

Before staging:

```powershell
git status --short
git diff --check
git diff --stat
git diff --name-only
git diff --diff-filter=D --name-only
```

Before archival, deletion output must be empty. After archival, it may contain exactly the two active prompt paths and each must have a matching archive addition with identical SHA-256. No production/test/tracker deletion is allowed.

Stage explicit paths only; never `git add -A` or `git add .`. Verify:

```powershell
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git status --short
```

The staged set must equal the final allowlist and two prompt renames. No logs, data, cache, local YAML, build output, or unrelated file.

### Step 11 - Commit only

Commit exactly:

```text
AD-722b-5a: wire federation avatar telemetry relay (closes #659)
```

Do not push. Do not run `gh issue close`, edit #659, comment, label, assign, or otherwise mutate GitHub. The commit trailer closes the issue only if/when the Captain later pushes it.

---

## Gate summary

The binding prompt owns the exact commands. Required outcomes:

| Gate | Existing baseline | Required result |
|---|---:|---:|
| Focused | new | all pass; new module >=66 cases; old module stays 8; no warning |
| Gate 1 relay/federation | 224 | 224 + new module count; no warning |
| Gate 2 directed/transport | 466 | 466 + new module count; no warning |
| Gate 3 local avatar/WS | 77 | unchanged 77; only five known BF-326 warnings |
| Gate 4 runtime/lifecycle | 376 | 376 + new module count; only two known dependency deprecations |
| Full | current repository | all pass under `-n 4 --dist=loadfile`; triage any xdist failure serially |

Any new warning is a failure. An unchanged test that fails at `-n 0` is a hard stop unless it also fails on exact clean HEAD and is returned to Architect as pre-existing baseline rot; do not quarantine it in this AD.

---

## Hard stops

1. Exact base/status/hash/ceiling/issue pre-flight fails.
2. Any file outside the implementation or conditional closeout allowlist is needed or changes unexpectedly.
3. Any frozen AD-1123/transport/fleet/avatar primitive/`startup/finalize.py`/test hash changes.
4. A `startup/finalize.py`, bridge, transport, federation message, IntentBus, EventType, registry, API, UI, YAML, or dependency edit becomes necessary.
5. Schema needs unknown fields, arbitrary nested data, payload-authored source/origin, raw profile/URL/asset/binary/secret content, or a larger/open payload; arbitrary CSS is admitted on wire; or unsupported exact-string palettes cannot project to `""` without changing local WS data.
6. Static default-empty config cannot express production use without dynamic wire subscription/wildcards/auto-expansion.
7. Zero-browser production cannot be proven through the real startup helper and real organized bridge/bus path.
8. Producer tasks are unbounded/unreferenced, start before the post-finalize complete-registry seam, change popout sampling, leak, or survive stop/restart; helper cleanup swallows/normalizes an error; runtime lets an ordinary optional helper error abort the already-announced boot or misses `_startup_complete=True`; runtime catches cancellation/another `BaseException`; or unknown-ID/duplicate-peer/global-cap errors are not explicit with zero surviving telemetry resources.
9. Callback `False` counts as dispatch or failed attempts avoid capacity.
10. Cache is no-op/unbounded/persistent, accepts diff before snapshot/gaps/stale frames, trusts sender clock for order, or mutates local runtime learning/registry/UI state.
11. Local WS shape/behavior or pinned warning baseline changes.
12. Red evidence is missing/fabricated or tests are weakened.
13. Tracker closeout changes the ceilings, omits the AD-722b-5a decision, claims cryptographic auth, or folds AD-722b-5b into this build.
14. Prompt archival changes bytes/hashes.
15. Builder is asked to push or mutate GitHub.

---

## Final handback

Return one compact table containing:

- commit hash/subject or `uncommitted` at implementation review;
- exact paths changed/added/moved/deleted;
- original red commands and failures;
- focused/new collected and passed count;
- Gates 1-4 and full gate exact counts/warnings;
- no-browser real-composition result;
- schema/privacy/policy-B projection/local parity/rate/order/cache/task/lifecycle audit result;
- runtime ordinary-failure containment, `_startup_complete=True`, zero-leak, and cancellation/other-`BaseException` propagation result;
- frozen hash audit;
- final SHA-256 for every changed/new production/test/tracker file and both archived prompts;
- `#659: commit closes on push; no Builder GitHub mutation`;
- ceilings `AD-1123 / BF-672 unchanged`;
- deviations/hard stops.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Architect correction re-review (2026-07-17)

### Pass 1 - Required correctness

**Verdict:** APPROVED. The execution contract now binds the corrected main prompt, preserves strict helper cleanup/raise semantics, contains only ordinary post-finalize telemetry failures at runtime, propagates cancellation/other `BaseException`, and encodes the closed policy-B palette projection without changing local WS data.

### Pass 2 - Engineering quality

**Verdict:** APPROVED. `startup/finalize.py` is explicitly frozen, the production/test allowlists are unchanged, the new-module floor is 66, and handback evidence requires exact configuration reasons, zero telemetry leaks, `_startup_complete=True`, and palette/local-parity proof.

### Pass 3 - Dispatch readiness

**Verdict:** APPROVED pending Builder red/green execution. Exact HEAD, final binding hash, issue read-only rule, gates/count formulas, no AD-1124, no bridge/transport/UI/API/finalize change, closeout order, and no-push discipline are consistent with the binding prompt.

---

# HIGHEST-PRECEDENCE LIVE CONTINUATION (2026-07-17)

**Authority:** This continuation supersedes every conflicting pre-flight status, frozen AD-1123 test hash, test allowlist, unchanged-test hard stop, count formula, and execution-order instruction above. Follow it together with the main prompt's highest-precedence continuation/correction packet. All other architecture, primitive freezes, privacy/security guards, closeout restrictions, and Git/GitHub prohibitions remain binding.

**Binding main prompt:** SHA-256 `8b1254b708a57fb62a4e0be6bd9d4095a2ae430aec3f705d83be412f0923c7f3`.

**Verdict:** CONTINUE WITH THREE NARROW CORRECTIONS. Do not discard, stash, restore, reset, stage, or overwrite any live Builder work.

## Live evidence to preserve

- HEAD/base: `44a697558eae15f88df5ff64dfe53ce70a23eb9e`; `main...origin/main`; zero staged paths.
- Worktree: only the original nine implementation/test paths and the two active prompts.
- Sections 1-5 complete.
- New module: **198 collected** before this packet.
- Focused: **212 passed** before this packet.
- Local WS-focused subset: **44 passed**, exactly **two known BF-326 warnings**.
- Gate 1: **422 collected; 420 passed; exactly two failed**, both in `tests/test_ad1123_bounded_federation_relay.py`:
  - `test_real_fleet_composition_with_explicit_empty_registry_is_inert`
  - `test_authorized_scope_has_no_transport_telemetry_event_config_or_shutdown_diff`
- Parent test pre-correction SHA-256: `c16b02eb5fc0b1ac5db9858480802a595b5cf7f675f4543351969677e9d740f5`.
- Generic bridge/relay, NATS/ZeroMQ/mock transports, shared types/events/protocols/mesh, fleet organization, and finalizer are unchanged from base. Their freezes remain absolute.

The two Gate 1 failures are the red evidence for the parent-test correction. Test-first repetition is unnecessary for those failures. Preserve their output and edit only the source assertion, guard name, and guard tuple specified below. Do not weaken the explicit-empty behavior or any generic security assertion.

## Exact parent-test correction

Temporarily add exactly one test path to the implementation allowlist:

```text
tests/test_ad1123_bounded_federation_relay.py
```

It is authorized only for these changes:

1. In `test_real_fleet_composition_with_explicit_empty_registry_is_inert`, retain all real-fleet explicit-empty setup and behavioral assertions. Delete only the trailing `inspect.getsource(ProbOSRuntime.start)` block and `assert "relay_topics=()," in runtime_source`. Add no replacement child assertion.
2. Rename `test_authorized_scope_has_no_transport_telemetry_event_config_or_shutdown_diff` to `test_authorized_scope_has_no_generic_relay_protocol_transport_or_fleet_diff`.
3. Replace only that guard's `forbidden` tuple with:

```python
  forbidden = (
    "src/probos/federation/bridge.py",
    "src/probos/federation/relay.py",
    "src/probos/federation/nats_transport.py",
    "src/probos/federation/transport.py",
    "src/probos/federation/mock_transport.py",
    "src/probos/types.py",
    "src/probos/events.py",
    "src/probos/protocols.py",
    "src/probos/mesh/intent.py",
    "src/probos/mesh/nats_bus.py",
    "src/probos/startup/fleet_organization.py",
  )
```

Keep `git diff --name-only` and `changed.isdisjoint(forbidden)` unchanged. The four permitted child-owned paths are `federation/telemetry_relay.py`, `routers/agents.py`, `startup/shutdown.py`, and `config.py`; do not hide their changes.

The exact authorized CRLF/no-BOM result must hash to:

```text
c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45
```

Report both pre/final hashes. A different final hash is a hard stop. This is the only superseded frozen-test/hash rule; every production/federation primitive and every other test remains frozen exactly as before.

## Independent producer-start correction

Review found one real exception-observation gap in the existing allowlist. `_producer_loop()` sets its readiness event in `finally`, so a task that raises during `event_bus.subscribe()` can wake `start()` and be mistaken for a healthy running producer.

Use only the already-authorized paths `src/probos/federation/telemetry_relay.py` and `tests/test_ad722b_5a_federation_telemetry_relay.py`:

1. Add `test_producer_subscription_failure_is_observed_cleans_and_permits_restart` with two exported agents and a test event bus that raises `RuntimeError("subscribe-fault")` on the second subscription. Record the focused red. Assert propagation, first-task reaping/unsubscription, complete producer/rate/cursor/tick/stream/sequence reset, and successful restart after disabling the fault.
2. Immediately after `await ready.wait()` in `FederationTelemetryRelay.start()`, add:

```python
        if task.done():
          task.result()
```

Do not catch `task.result()`. The existing enclosing `except BaseException` owns cleanup and exact re-raise. No other implementation/test change is authorized by this finding.

## Required continuation order

1. Preserve all prior evidence.
2. Add and run the one producer-subscription regression red; apply the exact observation fix; rerun that regression green.
3. Apply only the parent-test corrections and verify final hash `c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45`.
4. Immediately rerun the exact Gate 1 command. No intervening source/test inspection, refactor, or edit is permitted. Expected: new module **199 collected**; Gate 1 **423 passed, no warnings**.
5. Continue Gate 2 **665 passed/no warnings**; Gate 3 **77 passed/only five BF-326 warnings**; Gate 4 **575 passed/only two dependency deprecations**; then the full `-n 4 --dist=loadfile` gate and every compile/editor/source/privacy/diff/hash audit from binding.
6. Return the still-uncommitted implementation for Architect review with prior red evidence, new regression red/green, all exact counts/warnings, the parent test before/after hashes, and final hashes for every changed/new file and both prompts.

Do not touch trackers, archive prompts, stage, commit, push, or mutate GitHub before Architect review. The proposed #659 body requires no correction; do not update the issue.

## Continuation three-pass self-review

### Pass 1 - Required correctness

**Verdict:** APPROVED. The parent correction removes only AD-1123 state that the child intentionally supersedes and preserves explicit-empty behavior plus generic ownership guards. The producer correction surfaces task failure at the exact readiness boundary and preserves cleanup and lifecycle-exception semantics.

### Pass 2 - Scope and engineering quality

**Verdict:** APPROVED. Exactly one additional test path is authorized and deterministically hash-pinned. The independent fix remains within two original allowlist paths with one regression. No generic relay/transport/fleet/finalizer or closeout surface changes.

### Pass 3 - Continuation readiness

**Verdict:** APPROVED through corrections, exact Gate 1, Gates 2-4, full gate, and audits only. Tracker/archive/Git/GitHub mutation remains blocked until the next Architect implementation review.

---

# HIGHEST-PRECEDENCE IMPLEMENTATION-REVIEW CONTINUATION (2026-07-17)

**Authority:** This continuation supersedes every conflicting scalar-sequence instruction, lifecycle-transition instruction, config-bound assumption, mutation-window rule, waiter-creation rule, test/gate count, approval verdict, and main-prompt hash above. Follow it together with the main prompt's highest-precedence C4-C9 implementation-review packet. Prior C1-C3 evidence and the parent-test correction remain accepted.

**Binding main prompt SHA-256:** `d188db9eb967218fe27b56d9059f8dd4dad318e6aa24b141790013bfffc1dbad`. Any mismatch is a hard stop.

**Verdict:** BLOCKED PENDING C4-C9. Preserve the entire live Builder tree. Do not close out, stash, restore, reset, stage, commit, push, or mutate GitHub.

## Accepted evidence and unchanged freezes

- HEAD/origin/base remain `44a697558eae15f88df5ff64dfe53ce70a23eb9e`; nothing is staged.
- Existing implementation evidence is accepted through 199 new cases, focused 212, Gates 1-4 at 423/665/77/575, and full 19,575 passed plus 33 skipped.
- Parent test remains exactly `c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45` and receives no further edit.
- Generic bridge/relay/transports/fleet/finalizer, avatar primitives, UI, YAML, trackers, archives, commercial files, Git, and GitHub remain frozen/read-only.

## Exact correction scope

Edit only these production paths:

```text
src/probos/avatars/telemetry_frames.py
src/probos/federation/telemetry_relay.py
src/probos/config.py
```

Edit only this test path:

```text
tests/test_ad722b_5a_federation_telemetry_relay.py
```

The exact required behavior is C4-C9 in the binding main prompt:

1. Replace the relay-wide scalar sequence with a bounded per-agent sequence map; one frame's copies share a sequence, but another agent cannot create a cache gap.
2. Share `MAX_AVATAR_SAMPLING_RATE_MS = 2_147_483_647` between semantic validation and parse-time `SamplingRatesConfig` upper-bound validation.
3. Serialize full `start()`/`stop()` transitions with one relay lock; reject subscription/callback mutation during either transition; retrieve and contextually report any producer that dies after readiness.
4. Create both temporary event/timer waiters inside a cleanup scope and reap any partial pair.
5. Reject a `PeerConfig` telemetry list longer than 32 before importing/calling the ID predicate or inspecting entries.
6. Make diff-fallback logging include agent ID and exception type but no traceback, exception text, keys, or values.

Do not change stream-ID scope, cache ordering, receiver resync, rate-claim timing, callback accounting, startup/runtime/shutdown composition, local WebSocket behavior, or any privacy/governance boundary.

## Tests first and exact red

Add exactly these six cases:

```text
test_multi_agent_sequences_are_per_agent_and_shared_across_peer_copies
test_sampling_rate_config_upper_bound_matches_wire_contract
test_late_producer_failure_is_observed_without_unretrieved_exception
test_stop_and_concurrent_restart_are_serialized_without_orphaning_new_producer
test_temporary_waiter_second_create_failure_reaps_first_waiter
test_peer_config_oversized_list_rejects_before_entry_validation
```

Strengthen, but do not duplicate, this existing case:

```text
test_select_frame_diff_exception_falls_back_full
```

Update only existing new-module assertions that refer to scalar `_sequence`; they must assert exact `_sequences` map state. Do not reduce or rename any other case.

Before production edits, run the exact isolated seven-node command in the main prompt's `Required red and green` section. Expected red is **7 failed**, each for its named pre-correction defect. Record the exact output. Apply C4-C9, then rerun the identical command: **7 passed, no warnings**.

Next run those seven nodes together with:

```text
test_producer_subscription_failure_is_observed_cleans_and_permits_restart
```

Expected: **8 passed, no warnings**. This is the regression guard that the new lifecycle lock did not weaken C3 readiness propagation/cleanup.

## Exact continuation order

1. Verify this execution prompt binds main hash `d188db9eb967218fe27b56d9059f8dd4dad318e6aa24b141790013bfffc1dbad`.
2. Add the six cases and strengthen the fallback case. Record the exact seven-case red before any production edit.
3. Implement C4 first; rerun only the multi-agent sequence case green.
4. Implement C5 and C8; rerun only the two config/schema cases green.
5. Implement C6 and C7; rerun only the three lifecycle/waiter cases plus the prior C3 subscription case green.
6. Implement C9; rerun the strengthened fallback case green.
7. Run the complete seven-case set, then the complete eight-case set.
8. Run the original focused gate, Gates 1-4, full parallel gate, diagnostics, compile, source/privacy, diff/stage/deletion, and hash audits with the revised outcomes below.
9. Return the still-uncommitted tree for Architect implementation review.

Do not make an adjacent refactor between a correction and its focused green. A need for any fifth file is a hard stop.

## Revised exact collection and gates

Six new cases raise the new module from 199 to exactly **205**. Required outcomes are:

| Gate | Required result |
|---|---:|
| Seven review nodes | **7 passed**, no warnings |
| C3 plus seven review nodes | **8 passed**, no warnings |
| Focused binding gate | **218 passed**, no warnings |
| Gate 1 relay/federation | **429 passed**, no warnings |
| Gate 2 directed/transport | **671 passed**, no warnings |
| Gate 3 local avatar/WS | **77 passed**, only five pinned BF-326 warnings |
| Gate 4 runtime/config/shutdown | **581 passed**, only two pinned dependency deprecations |
| Full `tests/ -n 4 --dist=loadfile` | **19,581 passed, 33 skipped**, no warning beyond the accepted **454** repository-wide baseline |

Any different collection count, new warning, serial failure, unresolved task warning, parent-test hash drift, frozen-file diff, or extra path is a hard stop.

## Required handback

Return one compact implementation report containing:

- preserved original/C3 red-green evidence plus the new seven-case red-green evidence;
- exact 205 collection and revised gate/full counts;
- two-agent per-key contiguous cache proof and same-frame peer-copy sequence proof;
- valid-config-to-wire sampling bound proof;
- late-task observation, serialized stop/restart, transition mutation lockout, and partial-waiter reap proof;
- privacy-safe fallback log proof;
- exact final hashes for every changed/new path and both active prompts;
- parent hash `c78697b48da4235999ecc8966ac320c6d27a4e3724ad61d2e5db513c01d86a45` and all frozen hashes unchanged;
- no deletions, no staged paths, no tracker/archive/Git/GitHub mutation;
- ceilings `AD-1123 / BF-672` unchanged.

Closeout remains blocked until the next Architect review. Do not update #659; its corrected body and scope are unchanged.

## Continuation three-pass verdict

### Pass 1 - Correctness

**Verdict:** APPROVED TO FIX C4-C5 ONLY AS SPECIFIED. Multi-agent sequence and live-config/schema totality are blocking.

### Pass 2 - Lifecycle and quality

**Verdict:** APPROVED TO FIX C6-C9 ONLY AS SPECIFIED. No producer exception or temporary task may remain unobserved, and lifecycle mutation/restart must be serialized.

### Pass 3 - Dispatch

**Verdict:** CONTINUE THROUGH RED/GREEN, REVISED GATES, AND AUDITS ONLY. Tracker/archive/stage/commit/push/GitHub mutation remains prohibited.

---

# HIGHEST-PRECEDENCE LIVE COUNT EXECUTION CORRECTION (2026-07-17)

**Authority:** This correction supersedes every conflicting main-prompt binding hash, focused-count expectation, C4-C9 implementation status, and continuation-order instruction above. All other architectural constraints, file freezes, warning budgets, audit requirements, closeout restrictions, and Git/GitHub prohibitions remain binding.

**Binding main prompt SHA-256:** `a7dda6e7d6138b8541b02aad1c808d3c1dbfe1c76fe2203c42d62a305e4053ea`. Any mismatch is a hard stop.

**Verdict:** APPROVED TO RESUME DIRECTLY AT GATE 1. Accept the completed C4-C9 evidence and focused **219 passed, no warnings** run. Do not rerun focused and do not edit production or tests.

## Accepted execution evidence

- Authoritative seven-node red: **7 failed** for the exact named defects.
- Authoritative seven-node green: **7 passed, no warnings**.
- C3 plus seven review nodes: **8 passed, no warnings**.
- New AD-722b-5a module: exactly **205** collected.
- Exact three-module focused command: **219 passed, no warnings**.
- All C4-C9 behavior proofs are green; editor diagnostics are clear; no path is staged or deleted; frozen hashes remain intact.
- Existing migrated module: exactly **8** tests. Frozen `tests/test_ad722b_3_snapshot_diff.py`: exactly **6** tests and live blob `c62f51360098d90e4f24799cc3cbcfeec8f39642`, identical to HEAD.

## Authoritative counts

| Gate | Arithmetic | Required result |
|---|---:|---:|
| Focused binding gate | `205 + 8 + 6` | **219 passed, no warnings** |
| Gate 1 relay/federation | `224 + 205` | **429 passed, no warnings** |
| Gate 2 directed/transport | `466 + 205` | **671 passed, no warnings** |
| Gate 3 local avatar/WS | fixed baseline | **77 passed**, only five pinned BF-326 warnings |
| Gate 4 runtime/config/shutdown | `376 + 205` | **581 passed**, only two pinned dependency deprecations |
| Full `tests/ -n 4 --dist=loadfile` | `19,575 + 6` | **19,581 passed, 33 skipped**, no warning beyond the accepted **454** repository-wide baseline |

The prior **19,575** full result already included C3 and the 199-case new module; only the six C4-C9 cases are added. The focused total is the sole revised arithmetic error. Producing any one-test-short focused total would require deleting a required test or editing a fifth frozen path, neither of which is authorized.

## Execution handback

1. Verify the corrected main-prompt binding hash above.
2. Do not rerun the focused gate and do not make any code or test edit.
3. Resume at Gate 1, then run Gates 2-4, the full parallel gate, and all already-required audits with the authoritative counts above.
4. Return the still-uncommitted tree for Architect review. Do not update trackers, archive prompts, stage, commit, push, mutate GitHub, or update #659.

## Execution-correction three-pass verdict

### Pass 1 - Binding

**Verdict:** APPROVED. This execution correction binds the corrected main prompt at `a7dda6e7d6138b8541b02aad1c808d3c1dbfe1c76fe2203c42d62a305e4053ea`.

### Pass 2 - Arithmetic

**Verdict:** APPROVED WITH FOCUSED COUNT CORRECTED TO 219. All other revised gate and full counts are consistent.

### Pass 3 - Dispatch

**Verdict:** RESUME AT GATE 1. Focused rerun, code/test edits, tracker/archive changes, and Git/GitHub mutation remain prohibited.

---

# HIGHEST-PRECEDENCE FULL-GATE WARNING-EVIDENCE EXECUTION CORRECTION (2026-07-17)

**Authority:** This correction supersedes every conflicting execution instruction that treats the final full parallel gate's aggregate warning count, including **454**, as an exact deterministic ceiling. It does not supersede focused or Gate 1-4 warning contracts, behavioral counts, architecture/privacy requirements, file freezes, audits, closeout restrictions, or Git/GitHub prohibitions.

**Binding corrected main prompt SHA-256:** `878e95c0b5153729ef9bd65aeab1db86c27a0263686d943354cc783c21bb9fdc`. Any mismatch is a hard stop.

**Pre-correction execution prompt SHA-256:** `1533be80f92f5ab62b06fa3409e933b4df4d1f25125d8aabed45ab68d5e57685`.

**Verdict:** ACCEPT the completed fresh full gate at **19,581 passed, 33 skipped, 458 warnings**. Do not rerun focused, Gates 1-4, or full. Resume only with outstanding static/hash audits, then return the still-uncommitted tree for Architect implementation review.

## Accepted execution evidence

- C4-C9: **7 red then 7 green**; C3 plus review: **8 green**; new module: **205**; focused: **219 passed, no warnings**.
- Gate 1: **429 passed, no warnings**. Gate 2: **671 passed, no warnings**. Gate 3: **77 passed**, exactly five pinned BF-326 warnings. Fresh Gate 4 rerun: **581 passed**, exactly two pinned dependency deprecations. Ignore the earlier teardown-interrupted 86% attempt.
- The full summary names no changed/new implementation or test path. It is confined to 98 BF-326 summary blocks at `_pytest/fixtures.py`, one scheduling-dependent AD-889 aiosqlite thread block at `_pytest/threadexception.py`, and unchanged RuntimeWarning blocks at frozen `cognitive/gap_predictor.py` (one), `startup/finalize.py` (four), `substrate/event_log.py` (two), and `tests/test_proactive_quality.py` (one). Repeated warnings are folded into those summary blocks.
- The AD-889 warning node is `tests/test_ad889_commission_chain.py::test_recommission_preserves_manual_restriction`. That unchanged standalone test does not construct `ProbOSRuntime`; its duplicate `await store.stop()` sequence is byte-identical to HEAD and can race the xdist event-loop teardown.
- Every repository warning-source blob is unchanged from HEAD. All remaining source locations are third-party pytest internals. The complete 205-case new module and all six C4-C9 additions are serial warning-clean with `-W error::RuntimeWarning`.
- Static explicit-export admission plus referenced/cancelled/gathered producer and waiter tasks provide no causal path from AD-722b-5a to the frozen warnings.

## Binding warning forcing function

The accepted **458** is this run's observed aggregate, not a raised warning budget or reusable ceiling. For full-suite warning adjudication:

1. No warning source, node, traceback, or summary text may name a changed/new AD-722b-5a path.
2. Every aggregate variance must trace to third-party code or a repository source/test file proven byte-identical to HEAD and to a pre-existing warning family or scheduling race.
3. Focused and Gate 1-4 warning contracts remain exact and cannot be relaxed by provenance review.
4. Any changed-path warning, new warning source/family, unresolved-task or unawaited-coroutine evidence tied to changed code, untraceable variance, or frozen-blob drift is a hard stop.
5. On such a hard stop, return to Architect for the smallest source-focused serial reproducer; do not automatically rerun the 18-minute full gate.

## Execution handback

1. Verify the corrected main prompt hash above and this execution prompt's final hash.
2. Accept all completed test evidence; run no test gate again and make no production/test edit.
3. Complete only the already-required outstanding editor/targeted-compile, source/privacy, diff, staged/deleted-path, changed-file hash, and frozen-hash audits.
4. Return the still-uncommitted implementation and audit ledger for Architect review.
5. Do not edit trackers, archive, stage, commit, push, mutate GitHub, or update #659.

## Warning-correction execution verdict

**Verdict:** RESUME AT STATIC/HASH AUDITS, THEN IMPLEMENTATION REVIEW. The exact behavioral gates stand; aggregate warning provenance, not the historical scalar 454, is binding.
