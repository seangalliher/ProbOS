# AD-730-4 Builder Execution — Directed federated vision DMs

**Verdict:** **RE-APPROVED / CORRECTION EXECUTABLE — latest three blockers pinned as C7–C9; C1–C6 preserved (2026-07-17)**
**Binding specification:** `prompts/ad-730-4-directed-federated-vision-dm.md`
**Issue:** #634 — `AD-730-4: Federation peer-to-peer vision DMs`
**Exact base HEAD/origin:** `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa`
**Exact base subject:** `AD-731a-1d: enable reference-only federation attachment send (closes #638)`
**Numbering:** AD-730-4 is uniquely pre-reserved by #634; top-level ceiling **AD-1122** and BF ceiling **BF-672** remain unchanged.
**Scope:** one DM-only addressed federation path; reference-only attachments with BF-672 prefetch before exact-target delivery; legacy untargeted federation byte-identical.
**License disposition:** none.

Do not implement from this execution document alone. Read the binding main prompt fully. Its required answers (a)–(g), DD-730-4-1 through DD-730-4-12, test matrix, allowlist, gates, acceptance criteria, Do Not Build list, hard stops, and verified evidence control the build.

The main prompt's **“Latest BLOCKED re-review correction” (C7–C9)** is now highest precedence. C1–C6 and every prior invariant remain binding except where C7–C9 explicitly supersede their narrower mechanism. Continue from the live uncommitted implementation; do not restart, discard, restore, stash, or rewrite the accepted work.

---

## Pre-flight — exact live correction state

Before any Builder correction mutation:

1. `git rev-parse HEAD` must equal `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa`.
2. `git rev-parse origin/main` must equal the same SHA.
3. There must be no staged paths, and `git status --short` must show exactly:
   - ` M src/probos/federation/bridge.py`
   - ` M src/probos/federation/mock_transport.py`
   - ` M src/probos/federation/nats_transport.py`
   - ` M src/probos/federation/transport.py`
   - ` M src/probos/mesh/intent.py`
   - `?? prompts/ad-730-4-directed-federated-vision-dm-execution.md`
   - `?? prompts/ad-730-4-directed-federated-vision-dm.md`
   - `?? tests/test_ad730_4_directed_federated_vision_dm.py`
4. `logs/ad730_4_issue_update.md` exists but is ignored; it must not appear in status or staging.
5. There must be no deletion or other tracked/untracked path. `src/probos/mesh/intent.py` is accepted and frozen during correction.
6. Read #634 with `gh issue view 634 --repo seangalliher/ProbOS`; it must remain open and uniquely reserve AD-730-4. Read-only only.
7. Reconfirm #638 is closed and exact base is its AD-731a-1d close commit.
8. Reconfirm `PROGRESS.md`/`DECISIONS.md` ceilings are AD-1122 and BF-672.
9. Re-grep every anchor in the main prompt's Verified and C1–C9 sections. The historical pre-C1–C6 module collected **85 tests**; the current live module must collect **211 tests** before C7–C9 additions. If any live signature, caller, payload, transport, resolver, or inventory otherwise differs, stop for Architect re-verification.
10. Do not fetch, pull, rebase, merge, cherry-pick, switch branch, reset, restore, clean, stash, stage, commit, push, or mutate GitHub during pre-flight.

The only authorized Builder mutation after pre-flight is the exact active correction allowlist. Trackers, archive moves, staging, commit, push, and GitHub remain forbidden until all tests and Architect implementation review are green.

---

## Read first

Read these fully before writing tests or code:

- `.github/copilot-instructions.md`
- `prompts/_TEMPLATE.md`
- `prompts/review-criteria.md`
- `prompts/ad-730-4-directed-federated-vision-dm.md` — **binding**
- `src/probos/types.py`
- `src/probos/mesh/intent.py`
- `src/probos/mesh/nats_bus.py` — reference only
- `src/probos/federation/bridge.py`
- `src/probos/federation/router.py` — reference only
- `src/probos/federation/nats_transport.py`
- `src/probos/federation/transport.py`
- `src/probos/federation/mock_transport.py`
- `src/probos/federation/attachment_resolve.py` — reference only
- `src/probos/federation/attachment_fetch.py` — reference only
- `src/probos/startup/fleet_organization.py` — reference only
- `src/probos/substrate/registry.py` — reference only
- `src/probos/substrate/identity.py` — reference only
- `src/probos/agent_onboarding.py` — reference only
- `src/probos/routers/federation_attachments.py` — reference only
- `src/probos/routers/agents.py` — reference only
- `src/probos/cognitive/cognitive_agent.py` — reference only
- all existing tests in Gates 1–4
- `PROGRESS.md`, `DECISIONS.md`, and the Wave 151/152 vision table in `docs/development/roadmap.md`

Do not use the original May issue statement's “carry binary blobs” suggestion. AD-731 superseded it: refs cross the bus, bytes cross authenticated HTTP only.

---

## Exact live-correction allowlist

### Production — may modify exactly four files

- `src/probos/federation/bridge.py`
- `src/probos/federation/nats_transport.py`
- `src/probos/federation/transport.py`
- `src/probos/federation/mock_transport.py`

`src/probos/mesh/intent.py` remains an authorized path in the eventual AD final diff, but its current exact-membership `has_subscriber()` addition is accepted and frozen. Do not edit it during correction.

### Tests — may continue editing exactly one existing uncommitted file

- `tests/test_ad730_4_directed_federated_vision_dm.py`

**Exact active Builder allowlist (five paths, no others):**

1. `src/probos/federation/bridge.py`
2. `src/probos/federation/nats_transport.py`
3. `src/probos/federation/transport.py`
4. `src/probos/federation/mock_transport.py`
5. `tests/test_ad730_4_directed_federated_vision_dm.py`

`src/probos/mesh/intent.py` remains in the eventual AD diff but is frozen at SHA-256 `8815E98B2ABFE5A668E7F18EE1BF88F548231F725BFFC51C9A31E477DF89640E` during C7–C9.

No existing test file is authorized for edit. An obsolete/conflicting existing assertion is a hard stop and must be reported, not silently changed.

### Conditional closeout — only after all four gates and a new Architect implementation review

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- move the two unchanged active prompt docs to `prompts/archive/`

### Forbidden / reference-only

Everything else, especially:

- `src/probos/types.py`
- `src/probos/runtime.py`
- `src/probos/config.py`
- `src/probos/startup/fleet_organization.py`
- `src/probos/substrate/registry.py`
- `src/probos/substrate/identity.py`
- `src/probos/agent_onboarding.py`
- `src/probos/federation/router.py`
- `src/probos/federation/attachment_resolve.py`
- `src/probos/federation/attachment_fetch.py`
- `src/probos/routers/federation_attachments.py`
- `src/probos/routers/agents.py`
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/mesh/nats_bus.py`
- all config/YAML, dependencies/locks, UI/desktop, workflows, era archives, data, and logs

No production protocol/base-class extraction is authorized. Structural parity across the three transport classes is deliberate and bounded.

---

## Highest-risk invariants — redundant standing order

1. **Address pair:** exactly one configured stable node ID plus one exact stable local subscriber ID. Never callsigns.
2. **DM-only:** `direct_message` is the only remotely addressable intent. Reject every other intent before transport/local send.
3. **No `IntentMessage` schema edit:** node address is a bridge argument/envelope field, not a local message field.
4. **New path only:** existing `forward_intent()` remains executable-byte-identical and stays the only `IntentBus` federation handler.
5. **One node:** directed outbound calls `send_to_peer()` once through `request_peer()`; it never invokes `FederationRouter.select_peers()`.
6. **One local target:** directed inbound calls `IntentBus.send()` once; it never calls `broadcast()`, callsign resolution, registry/pool/capability selection, or a decoy.
7. **Admission before fetch:** validate configured source, target node, DM intent, target ID, params, and subscriber existence before BF-672 resolution.
8. **Fetch before delivery:** for an admitted existing target, resolver completes before target handler begins.
9. **SHA refs only:** preserve AD-731a-1d's 8 / 64 / 64 ceilings and strict approved ref blocks. No inline image/binary form anywhere.
10. **Privacy/minimal authority:** carry only bounded text plus canonical refs. Drop private session history, caller context/urgency, local-authority/qualification flags, project/recall/tool state, and unknown params. Replace spoofable provenance/session fields with receiver-owned `federation:<source_node>` values.
11. **DM timeout:** normalize to a finite positive maximum of 60 seconds and use that same value for the directed request wait. Do not reuse the legacy five-second `forward_timeout_ms`; do not change legacy timeout behavior.
12. **TTL is not age:** origin accepts only exact built-in finite positive numerics and caps at 60; receiver accepts exact built-in finite wire TTL only in `(0, 60]`. TTL bounds the origin wait and fresh receiver-local `IntentMessage` handling only.
13. **No cross-host clock comparison:** preserve sender-local `FederationMessage.timestamp=time.monotonic()` on the wire, but never compare it with receiver time or use it for admission. No request-age or replay protection exists in this AD.
14. **Bounded result detach:** never call JSON serialization on an unvalidated result. Use C1's iterative exact-built-in validator: depth 16, 4,096 nodes, 65,536 characters/string, 262,144 cumulative UTF-8 response-string bytes, and 262,144 compact response bytes. C7 applies one bounded case-insensitive `data:image/` prefix helper after leading ASCII whitespace within each already-admitted string to scalar result strings, exact dict keys, and `error`, regardless of subtype/delimiter. Reject binary, nonfinite, cycle, hostile subclass, `image_url`, and base64-source/data shapes without rejecting ordinary prose or ordinary `data` objects.
15. **Exact schemas:** request payload is exactly seven keys; response payload exactly `{delivery_mode, results}`; result exactly six typed keys with finite confidence before validator; `_transport_stripped` is an ordered unique subset of the four canonical producer names, length 1..4 before inspection.
16. **Exact correlation:** safe ID is an exact built-in string matching `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`. Pending key is `(peer_node_id, message_id)`, unique-owner admitted, and registered before synchronous mock delivery can respond. Correlation is response routing, not inbound replay defense.
17. **Lifecycle ownership:** duplicate key and post-stop admission reject before send; cleanup removes only its future by identity; stop closes admission before cancel/clear; start reopens; an old finally cannot remove a newer same-key owner.
18. **Late response isolation:** only a payload with an exact built-in `delivery_mode` key and exact built-in `"targeted_dm"` value is targeted. Unmatched or malformed-ID exact-targeted responses are dropped, never placed in legacy peer queues.
19. **Legacy queues unchanged:** classify with exact dict + unbound `dict.items`, never `.get()`/membership/subscription on payload. Malformed/non-exact markers and unmatched legacy responses, including malformed/non-string message IDs, still use the current peer-keyed queue. Hostile payload/key/value subclasses invoke zero overrides. Never perform pending lookup on a malformed ID. The open legacy top-level marker scan is honestly $O(n)$; do not claim a constant global work bound.
20. **Stable errors:** use one existing `IntentResult`; no exception text/content/roster on the wire. Bridge-stopped/transport-closed maps unavailable; duplicate-key/ordinary request failure maps delivery-failed; timeout maps peer-timeout.
21. **Legacy send signatures unchanged:** NATS publish exceptions and ZeroMQ missing dealers remain swallowed/no-op in `send_to_peer`; `request_peer` can observe only timeout. Do not invent immediate unavailable detection.
22. **No-fallback:** absent/declined/failed/timed-out target never broadcasts or selects another agent/node.
23. **Cancellation:** `CancelledError` always propagates and pending futures are removed only when identity-owned.
24. **Ordinary errors:** at the four new boundaries log only safe IDs, stable action, and `type(exc).__name__`; never exception message/traceback, text, params, result body, bytes, token, or URL.
25. **Configured-peer trust boundary only:** unknown/self source is dropped. Do not claim cryptographic source authentication; a configured-ID claim relies on current transport ACL/deployment trust.
26. **No dormant-governance activation:** do not wire production trust/Hebbian/cluster handles or change legacy router behavior.
27. **No roster gossip/discovery:** caller already knows exact stable `(node_id, agent_id)`.
28. **No thread sync:** do not carry `thread_id` across node-local chat namespaces.
29. **No new task/background loop:** pending futures are request-scoped, not tasks.
30. **No config flag:** the public method is inert unless explicitly called; global federation remains default-off.
31. **Headline fixture stays green:** two `organize_fleet()` bridges, shared started `MockNATSBus`, real separate buses/stores/ASGI route, target and decoy.
32. **Legacy literal exact:** restore only `Federation message validator failed — message passed without validation` in the legacy validator catch; match the exact HEAD AST literal and UTF-8 em dash. Do not otherwise edit that logger call.
33. **Prompt hashes stable:** Builder never rewrites these revised docs; final closeout moves them unchanged.

---

## Ordered Builder checklist

### Step 1 — Preserve the completed implementation baseline

The fail-before phase, `has_subscriber()` addition, headline integration, 85-case pre-C1–C6 baseline, and current 211-case pre-C7–C9 baseline already exist in the live diff. Do not recreate, restore, or rerun the historical red gate. Run collection only and require 211 tests before adding C7–C9 cases. Preserve all existing tests unless C7–C9 explicitly supersede an assertion; no existing committed test-file edits are authorized.

### Step 2 — Correct every response string position (C7)

In `bridge.py`, preserve C1/C4/C5 and correct the live data-URL helper exactly per C7:

- one work-bounded helper: skip ASCII whitespace only within the admitted 65,536/4,096 character limit, then inspect 11 candidate characters;
- reject case-insensitive `data:image/` regardless of subtype length/delimiter;
- call it for scalar result strings, exact result-dict keys, and `error`;
- preserve exact node counting and charge dict keys + `error` to cumulative UTF-8 response-string bytes;
- preserve malformed non-string/oversized `error` precedence as `federation_response_invalid`;
- preserve stable `federation_result_not_serializable` for forbidden content at both receiver and origin.

Add receiver/origin tests for scalar, dict key, `error`, mixed case, subtype >128 characters, bounded whitespace, and allowed ordinary prose.

### Step 3 — Correct exact transport marker classification (C8)

In all three transports preserve C2/C4/C6 and replace only the live marker classifier:

- only `type(payload) is dict` is eligible;
- iterate with unbound `dict.items(payload)`;
- require `type(key) is str` before key comparison and exact built-in string value before `"targeted_dm"` comparison;
- never use payload `.get()`, membership, subscription, `dict.get`, or `dict.__contains__`;
- exact targeted + malformed ID drops; malformed/non-exact marker follows legacy queue;
- hostile dict/key/value subclasses invoke zero overrides;
- do not add a legacy payload cap or claim bounded top-level work; classification is $O(n)$ over the open legacy payload.

Add NATS/mock/socket-free ZeroMQ tests for exact targeted drop, malformed marker queue parity, malformed-ID exact-targeted drop, hostile subclasses, and zero overrides.

### Step 4 — Restore exact legacy UTF-8 literal (C9)

Change only mojibake `â€”` back to the exact UTF-8 em dash in `Federation message validator failed — message passed without validation`. Preserve logger level, call, arguments, `exc_info=True`, and semantics. Add the main prompt's direct HEAD-vs-worktree AST/UTF-8 regression in the uncommitted AD test module. Do not modify a committed test.

### Step 5 — Run focused new-module gate

Run the new AD module alone under the same temp/offline/serial/strict-warning environment as Gates 1–4. Report the exact final collection/pass count. Fix only C7–C9 defects while preserving C1–C6 inside the active correction allowlist.

### Step 6 — Run exact unchanged Gates 1–4

Run the commands below exactly. Do not edit the gate commands or baseline contributions.

### Step 7 — Three-pass correction review

In addition to the prior protocol checks, prove:

- C1/C7 bounded result work dominates traversal/JSON serialization and every response string position is covered;
- exact seven/two/six schemas and finite confidence precede validator;
- no hostile subclass override can execute in C1/C7 or C8;
- pending map has one owner, closed admission, and identity cleanup;
- malformed markers and malformed legacy IDs still reach legacy queue; exact targeted malformed IDs drop;
- C8's top-level legacy classifier is reported as $O(n)$, not falsely bounded;
- NATS swallowed publish failure yields timeout, not unavailable;
- four directed logs have no message/traceback/secret/blob;
- exact legacy validator AST literal/base UTF-8 em dash match;
- `src/probos/mesh/intent.py` is byte-for-byte unchanged from the correction-start diff.

### Step 8 — Return to Architect before closeout

Return the required report and live diff for Architect implementation review. Do **not** update trackers, archive prompts, stage, commit, push, or mutate GitHub yet.

### Step 9 — Conditional closeout after explicit Architect approval

Only after a new approval, perform the already-specified tracker edits and unchanged prompt archive moves. Re-run scope/deletion/whitespace/hash audits. Commit only if separately authorized.

---

## Historical completed build checklist (superseded by Steps 1–9 above)

The following records the original build order for audit only. Do not execute it again. Any historical wording about unconditional cleanup, generic strict-JSON response detachment, open result fields, or pre-correction closeout is superseded by C1–C6 and active Steps 1–9.

### Historical Step 1 — Create fail-before headline test

Create `tests/test_ad730_4_directed_federated_vision_dm.py` and first implement only:

`test_directed_vision_dm_two_organized_bridges_prefetches_and_targets_only`

The test setup is binding:

- shared started `MockNATSBus`;
- origin and receiver `SystemConfig` with exact static peer IDs and A2A node mapping;
- two real `IntentBus(SignalManager())` objects;
- two real `organize_fleet()` calls yielding `NATSFederationTransport` + `FederationBridge`;
- separate real `FilesystemAttachmentStore` roots;
- real origin FastAPI app + `federation_attachments.router` + ASGI transport/client;
- canonical PNG bytes stored only at origin before send;
- one deterministic stable-ID target and one deterministic stable-ID decoy subscribed to receiver `direct_message`;
- target handler deep-captures refs, reads receiver store, and asserts exact bytes are already there;
- decoy handler records any invocation and must remain at zero;
- origin intent contains only text and canonical AD-731 SHA ref blocks;
- one fetch; exact correlated success; original nested params unchanged.

Run the exact red node. It must fail because the public directed method is absent. Record the node/reason in the build report. If it fails first for fixture drift, repair only the test setup until the missing method is the proven blocker.

### Historical Step 2 — Complete fail-before suite

Historical instruction: add the remainder of the main prompt's original named behaviors before production edits. This is complete; do not execute it again. Prefer parametrization for any new C1–C6 cases, with explicit case IDs.

Use BF-287 discipline:

- no `MagicMock` at config, bus, bridge, store, agent, or transport boundary;
- use real `SystemConfig`/`FederationConfig`/`PeerConfig`/`A2APeerConfig`;
- use tiny concrete recording target/decoy objects or handlers;
- no sleeps for correlation/cancellation — use events/deferred futures;
- no real network/model/socket.

Run the new module to capture a concise fail-before set. Do not weaken expected no-fanout, correlation, or no-inline assertions.

### Historical Step 3 — Add `IntentBus.has_subscriber`

Implement the exact public query beside `subscriber_count`:

```python
def has_subscriber(self, agent_id: str) -> bool:
```

Exact membership only. Fully annotate. No logging or mutation. No intent-index or NATS query. Add happy/unknown/empty/index-independence tests in the new module.

### Historical Step 4 — Add exact correlated request seam

In each of the three federation transport classes:

- initialize private pending futures keyed `(peer_node_id, message_id)`;
- add fully annotated `request_peer(peer_node_id, message, timeout_ms)`;
- register before send;
- resolve exact pending future in `deliver_response`;
- late directed response without pending match is dropped;
- legacy response without pending match follows current peer queue path;
- timeout returns `None`;
- cancellation propagates;
- `finally` removes the exact entry;
- stop cancels/clears remaining pending futures.

Do not alter current public method signatures or message serializers. Do not edit `MockNATSBus`, add a transport base protocol, or change NATS subjects/JetStream.

Run transport/correlation nodes before bridge implementation.

### Historical Step 5 — Add directed outbound bridge method

In `bridge.py`, implement main-prompt DD-730-4-1/2/3/8:

- exact built-in identifier validation;
- configured + connected + non-self target node;
- `direct_message` only;
- exact stable target agent ID;
- existing reference sanitizer once;
- bounded text/ref-only param reconstruction with private/session/authority fields dropped;
- `_transport_stripped` parity;
- directed-only strict JSON detach;
- exact directed envelope;
- exact origin TTL type check, guarded float conversion, finite/positive validation, 60-second cap, and `max(1, math.ceil(ttl_seconds * 1000.0))` wait conversion;
- one `request_peer` call;
- timeout/cancel/ordinary error behavior;
- exact response/source/mode/result-count/intent/agent validation;
- one returned `IntentResult`.

Do not edit the executable body of `forward_intent()`. Use no router selection and no local bus call.

### Historical Step 6 — Add directed inbound branch

At `_handle_intent_request()`:

- absent mode → existing legacy code unchanged;
- exact `targeted_dm` → private directed handler and return;
- unknown present mode → configured-source error only, no local work.

Private directed handler order:

1. exact built-in payload/source preflight;
2. configured non-self source;
3. target node equals self;
4. intent equals `direct_message`;
5. target ID valid;
6. original intent ID valid;
7. wire TTL is exact built-in `int`/`float`, finite, and `0 < ttl_seconds <= 60.0`;
8. params exact dict plus bounded text/ref admission;
9. `intent_bus.has_subscriber` true;
10. reconstruct targeted `IntentMessage` with neutral urgency/context, validated TTL, no explicit `created_at` (use its receiver-local default factory), and receiver-owned federation provenance/session fields only;
11. BF-672 resolver (cancel propagates, ordinary failure logs/degrades);
12. one `intent_bus.send()`;
13. normalize one result/error;
14. strict JSON detach response;
15. send one correlated response.

`FederationMessage.timestamp` is deliberately absent from this validation
sequence. Do not compare it with `time.monotonic()`, `time.time()`, or any
receiver clock. `IntentBus.send()` does not enforce `created_at` age; it starts
a fresh local timeout from the send call. Do not add a wall-clock field or
nonce/replay store in this AD.

Unknown/self source: drop with no response. Every other admitted error: one response. Never fall through to legacy broadcast.

### Historical Step 7 — Complete protocol tests

Run every named case from the main prompt. Pay particular attention to:

- target/decoy counters;
- zero fetch/store touch on rejected/absent target;
- bounded text/ref-only wire and dropped session history/context/urgency/private unknown fields;
- spoofed `from`/Captain/qualification/session fields replaced by receiver-owned federation provenance;
- configured source vs unknown/self spoof limitation;
- wrong node and result-target spoof rejection;
- origin invalid-TTL rejection and 60-second cap; receiver non-exact/non-finite/non-positive/over-cap TTL rejection before fetch/send;
- TTL hostile cases include bool/string/non-built-in numeric, NaN/infinities, oversized-int conversion overflow, receiver `60.0001`, origin `120 -> 60`, and tiny-positive `timeout_ms == 1`;
- sender monotonic values from unrelated epochs (including zero/very large values) do not affect directed admission; receiver reconstruction has a fresh local `created_at`;
- explicit proof that TTL/correlation are not described or implemented as request-age/replay protection;
- non-vision text DM exact targeting;
- resolver ordinary-error continuation vs cancellation stop;
- target ordinary error vs cancellation;
- reverse-order concurrent same-peer responses;
- timeout/cancel/stop pending cleanup;
- late-directed vs legacy queue split;
- existing optional remote-result validator false/cancel/ordinary-error semantics;
- NATS/ZeroMQ serializer semantic parity;
- hardcoded legacy untargeted envelope and no directed keys;
- legacy untargeted `direct_message` still fans out to every matching local subscriber;
- no inline/binary form in request/response/log captures;
- deep detachment and origin immutability on every exit.

### Historical Step 8 — Run exact Gates 1–4

Run the commands copied below exactly. Fix only AD-730-4 defects inside the allowlist. No xdist, broad full suite, live runtime data, live NATS server, live ZeroMQ socket, or live model.

### Historical Step 9 — Three-pass self-review

Perform all three passes in the main prompt. In particular:

- inspect the exact diff of `forward_intent()` and reject any executable change;
- grep all calls to new `request_peer`, `forward_direct_message`, and `has_subscriber`;
- verify all three transport cleanup paths;
- inspect captured request/response JSON for bytes/base64/data URLs/token/content;
- prove no branch sees `targeted_dm` then invokes `broadcast`;
- prove no branch compares `FederationMessage.timestamp` with a receiver clock or emits `federation_request_expired`;
- prove no dormant trust/router wiring was activated.

### Historical Step 10 — Conditional closeout

Only after every gate and review is green:

- update `PROGRESS.md`, `DECISIONS.md`, and the roadmap exactly as the main prompt specifies;
- record exact observed new test count and Gate 1–4 counts/durations;
- move both prompt docs unchanged into `prompts/archive/`;
- leave the ignored issue-update draft untouched;
- perform scope/deletion/whitespace/hash audits;
- hand the final uncommitted diff to the Architect unless the orchestrator explicitly authorizes the local commit.

### Historical Step 11 — Optional authorized local commit

If and only if the orchestrator authorizes commit after review:

1. stage explicit allowlisted production/test/tracker/archive paths only — never `git add -A`;
2. verify ignored log absent;
3. run cached/staged scope/deletion/whitespace checks;
4. commit exactly:

`AD-730-4: add directed federated vision DMs (closes #634)`

Do not push or directly mutate #634. Captain controls push; the commit trailer closes it when pushed.

---

## Exact gates

Run from `D:\ProbOS`. Each uses a unique temp data directory, local embeddings, offline model flags, no cache, serial execution, per-test 90-second timeout, short tracebacks, and strict `RuntimeWarning`.

### Historical red gate — audit record only; do not rerun

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_red_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py::test_directed_vision_dm_two_organized_bridges_prefetches_and_targets_only -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Gate 1 — focused directed federation + current attachment contract

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_federation.py tests/test_federation_nats.py tests/test_targeted_dispatch.py tests/test_ad731a_1d_reference_only_federation_send.py tests/test_ad731a_1c_auto_resolve.py tests/test_ad731a_remote_attachment.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing contribution: **148** plus the new module.

### Gate 2 — targeted/local/transport lifecycle parity

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_transport_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_intent.py tests/test_federation.py tests/test_federation_nats.py tests/test_targeted_dispatch.py tests/test_ad637z_nats_cleanup.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_bf296_intent_bus_close.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing contribution: **188** plus the new module.

### Gate 3 — reference-only vision chain

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_vision_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_ad731a_1d_reference_only_federation_send.py tests/test_ad731a_1c_auto_resolve.py tests/test_ad731a_remote_attachment.py tests/test_ad731_attachment_ref_wire_format.py tests/test_bf265_transport_stripped_params.py tests/test_ad730_agent_chat_vision.py tests/test_ad720d_vision_pipethrough.py tests/test_bf266_vision_context_folding.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing contribution: **141** plus the new module.

### Gate 4 — federation governance/runtime/lifecycle blast

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_ad479_federation_hardening.py tests/test_ad480_federation_mcp_a2a.py tests/test_ad443_mobility.py tests/test_runtime.py tests/test_ad447_phase_gates_pool_group.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing contribution: **243** plus the new module. Two third-party deprecation warnings existed in the exact baseline; report them if unchanged.

---

## Scope, deletion, whitespace, and prompt-hash audit

Before tracker edits and before staging:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D 9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa --
git diff --stat
git diff --numstat
git check-ignore -v logs/ad730_4_issue_update.md
git diff -- config/system.yaml
git diff -- src/probos/types.py src/probos/runtime.py src/probos/config.py src/probos/startup/fleet_organization.py src/probos/federation/router.py src/probos/federation/attachment_resolve.py src/probos/federation/attachment_fetch.py src/probos/routers/federation_attachments.py src/probos/routers/agents.py src/probos/cognitive/cognitive_agent.py src/probos/mesh/nats_bus.py
git diff --no-index --check -- NUL prompts/ad-730-4-directed-federated-vision-dm.md
git diff --no-index --check -- NUL prompts/ad-730-4-directed-federated-vision-dm-execution.md
Get-FileHash prompts/ad-730-4-directed-federated-vision-dm.md -Algorithm SHA256
Get-FileHash prompts/ad-730-4-directed-federated-vision-dm-execution.md -Algorithm SHA256
```

For untracked no-index checks, exit code 1 is expected because the document differs from empty; emitted whitespace diagnostics are failures.

Before archive move, compare hashes to the Architect handoff hashes recorded in the final report. After move, hash archive paths and require exact equality.

Final Architect handoff hashes (SHA-256, uppercase):

- binding prompt and this execution document: **use the final hashes in the Architect handoff response**
- frozen `src/probos/mesh/intent.py`: `8815E98B2ABFE5A668E7F18EE1BF88F548231F725BFFC51C9A31E477DF89640E`

The ignored issue-draft hash is audit-only and must never be staged or archived with the prompt packet.

Expected pre-closeout paths:

- two active Architect docs;
- five modified production files in the eventual AD diff, of which only the four federation files may change during correction;
- one new test module.

Expected post-closeout paths additionally include the three trackers and show the prompt docs as archive additions/root deletions (a rename in Git's final diff). There must be no other path and no deletion of production/test/tracker content.

If a local commit is authorized, stage explicit paths only and run:

```powershell
git diff --cached --check
git diff --cached --name-only
git diff --cached --name-only --diff-filter=D
git diff --cached --stat
git diff --cached --numstat
git diff --cached -- config/system.yaml
git diff --cached -- logs/ad730_4_issue_update.md
```

Never stage the ignored log or use `git add -A`.

---

## Required Builder report

Return a concise table containing:

- exact base/origin and exact eight-path live correction-start status;
- #634/#638 states and verified AD-1122/BF-672 ceilings;
- historical fail-before node/reason plus confirmation it was not rerun;
- exact historical pre-C1–C6 85-test collection, exact pre-C7–C9 211-test collection, and exact final new-module collection count;
- Gate 1–4 exact pass/fail/skip/warning counts and durations;
- changed/created/moved files;
- exact public signatures for `forward_direct_message`, `request_peer`, and `has_subscriber`;
- positional-call compatibility for `forward_direct_message(target_node_id, intent)` and exact signature introspection evidence;
- node/agent stable address validation and callsign non-resolution proof;
- headline two-organized-bridge evidence: target saw refs + prefetched exact bytes; decoy zero; fetch one; original graph unchanged;
- text-only zero-fetch evidence;
- malformed/unknown/self source, wrong node, malformed/absent target, non-DM, no-fallback outcomes;
- exact origin TTL validation/cap and receiver wire-TTL rejection evidence;
- proof sender-local monotonic timestamp is not a receiver admission input, reconstructed `IntentMessage.created_at` is local, and no request-age/replay protection is claimed;
- bounded text/ref-only allowlist evidence; private session history, caller context/urgency, authority/qualification flags, project/recall/tool state, and unknown params absent from the wire;
- receiver-owned `from="federation:<source_node>"`, source/message provenance, empty session state, spoof stripping, and generic action-episode eligibility evidence;
- explicit statement that configured source claims inherit current transport ACL trust and are not cryptographically authenticated;
- C1 bounds and exact acceptance/rejection evidence for legitimate text/object, binary/nonfinite/cycle/depth/nodes/string/bytes, actual image shapes, prose/ordinary-data carve-outs, hostile subclasses, and million-entry work;
- C7 origin/receiver evidence for case-insensitive `data:image/` rejection in scalar values, exact dict keys, and `error`, including a subtype longer than 128 characters and allowed ordinary prose; exact cumulative-byte/node accounting evidence;
- exact seven-key request, two-key response, six-key typed result, finite-confidence-before-validator, safe correlation ID, and canonical bounded `_transport_stripped` evidence;
- correlation reverse-order, duplicate-owner rejection, ownership cleanup, post-stop rejection, start reopen, stop/restart stale-finally safety, synchronous response registration, timeout/cancellation, late-directed queue isolation, malformed-directed drop, and malformed-legacy queue parity;
- C8 NATS/mock/ZeroMQ evidence that only the exact built-in targeted marker drops, malformed/non-exact markers queue as legacy, exact-targeted malformed IDs drop, and hostile dict/key/value subclasses invoke zero overrides; explicitly report the open top-level scan as $O(n)$;
- exact stable error matrix including bridge/transport closed, duplicate key, timeout, and NATS swallowed-publish timeout semantics;
- safe-log evidence for all four boundaries: class name present, canary/traceback absent, `record.exc_info is None`;
- NATS/ZeroMQ serializer parity, no-inline/binary proof, and bounded request/response deep-detach proof;
- legacy untargeted exact-envelope/fan-out byte-identity proof;
- C9 HEAD-vs-worktree AST literal equality and exact UTF-8 em-dash bytes for the legacy validator warning;
- cancellation vs ordinary-error behavior;
- no router/trust/Hebbian/cluster/config/event/dependency/task/JetStream/UI/thread-sync/discovery work;
- before closeout approval: confirmation trackers/archive/Git/GitHub are untouched and ignored log remains ignored; after separately approved closeout: tracker/roadmap and archive hash evidence;
- three-pass review verdict and license none;
- deletion/whitespace/scope audit;
- local commit SHA only if explicitly authorized; confirmation no push/direct GitHub mutation.

---

## Stop conditions

Stop and report to the Architect if:

1. exact base/origin/eight-path correction-start tree/issue reservation/ceilings differ;
2. any needed path is outside the allowlist;
3. correctness requires changing `IntentMessage`, runtime/startup/config/registry/identity/router/attachment helpers/NATS bus;
4. exact one-agent delivery needs callsign, pool, registry, capability, or alternate-node fallback;
5. unique-owner correlation cannot remain transport-owned while legacy send signatures and malformed-ID peer queues stay unchanged;
6. source spoofing can only be solved by adding credentials/signatures/CURVE/NATS accounts — report the current transport limitation rather than broadening #634;
7. request-age/replay correctness appears to require comparing sender monotonic time, adding wall-clock/nonce fields, or introducing replay persistence — stop rather than expanding this AD;
8. headline test cannot use the required real composition and stores/ASGI route;
9. raw/inline image bytes appear anywhere on the federation wire, C1 work cannot be explicitly bounded, or legitimate text/ordinary object results would be corrupted;
10. an existing test requires an unanticipated edit or a gate regression reproduces serially outside the new module;
11. a deletion, bulk reformat, config/dependency/UI/commercial leak, prompt rewrite, pre-approval tracker edit/archive move, staging, commit, push, or GitHub mutation occurs;
12. any directed exception log contains exception message/traceback or secret/blob content;
13. a fix changes legacy `send_to_peer()` signatures or classifies swallowed NATS publish failure as immediate unavailable;
14. `src/probos/mesh/intent.py` changes during correction.

Do not guess around a hard stop.

---

## Acceptance

The correction handoff is complete when every main-prompt acceptance criterion and C1–C9 behavior is proven, all four exact unchanged gates pass, every response string position uses C7, transport classification satisfies C8 without hostile overrides, C9's exact legacy UTF-8 literal matches HEAD, result validation remains explicitly bounded and exact, pending ownership/lifecycle remains race-safe, logs are type-only and secret-safe, malformed markers/legacy response IDs retain peer-queue behavior, the directed path remains DM-only/exact-target/no-fallback, BF-672 prefetch precedes target delivery, no inline/binary payload exists, and legacy untargeted federation remains byte-identical. Return to the Architect before trackers, archive moves, staging, commit, push, or GitHub mutation.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Final Architect review (2026-07-16; temporal contract re-reviewed 2026-07-17)

- **Pass 1 — behavior/spec:** APPROVED after correction. Cross-host monotonic freshness was removed; exact TTL-only local handling and explicit no-age/no-replay posture are pinned.
- **Pass 2 — verify-first:** APPROVED. Live signatures/payloads/transports/composition/tests were read at the exact base; no post-build entity is misreported as a pre-build API.
- **Pass 3 — scope/privacy:** APPROVED. Exact five-production/one-test allowlist, technical trackers only, unchanged archive move, no dependency/config/UI/commercial scope, license none.

**Builder approval: APPROVED / EXECUTABLE.**

---

## Historical re-review — C1–C6 blockers resolved in design (superseded for handoff by C7–C9 below; 2026-07-17)

**Verdict:** ✅ **RE-APPROVED / CORRECTION EXECUTABLE**

## Required (must fix before closeout)

1. Implement main-prompt C1–C6 exactly in the four active federation source files and the existing AD test module.
2. Run the new module, then unchanged Gates 1–4.
3. Return the uncommitted diff/report for Architect implementation review before any tracker/archive/Git/GitHub action.

## Recommended

None. The adversarial/stress/lifecycle/log cases are required, not optional.

## Nits

- Report final collection rather than estimating it.

## Verified

- Exact base/origin remain `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa`.
- Live correction starts from five modified production files, two active prompt docs, and one new test module; ignored issue draft remains ignored.
- `src/probos/mesh/intent.py` is accepted/frozen; active correction is four federation files plus the AD test module.
- NATS `send_to_peer()` swallows publish exceptions, so unavailable-vs-timeout is resolved toward timeout without changing the legacy signature.
- UUID hex and every verified current test/legacy message ID fit `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`.
- Current AD module collects 85 tests before correction additions.
- Gates 1–4 are unchanged.
- No production, test, tracker, Git, or GitHub mutation was made by the Architect.

**Builder next step:** apply C1–C6 to the live diff. Do not touch `mesh/intent.py`, trackers, prompt docs, Git staging/history, or GitHub.

---

## Re-review — latest C7–C9 correction handoff (2026-07-17)

**Verdict:** ✅ **RE-APPROVED / CORRECTION EXECUTABLE**

## Required (must fix before closeout)

1. Apply main-prompt C7 to scalar result strings, exact result-dict keys, and `error`; add full receiver/origin mixed-case and >128-character-subtype cases.
2. Apply C8 identically to NATS, mock, and ZeroMQ using exact dict + unbound `dict.items`; preserve malformed-marker legacy queues and prove zero hostile overrides.
3. Apply C9's exact UTF-8 em-dash restoration and direct HEAD-vs-worktree AST/byte regression in the existing uncommitted AD test module.
4. Run the module, then unchanged Gates 1–4, and return before any closeout action.

## Recommended

None. Preserve C1–C6; do not add a legacy payload cap to make an inaccurate bounded-work claim.

## Nits

- Report final collection from the verified **211-test** pre-C7–C9 baseline.

## Verified

- Exact base/origin remain `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa`.
- Live correction still has five modified production files, two active prompt docs, and one new AD test module; ignored issue draft remains ignored.
- `src/probos/mesh/intent.py` remains accepted/frozen with SHA-256 `8815E98B2ABFE5A668E7F18EE1BF88F548231F725BFFC51C9A31E477DF89640E`.
- The live module collects 211 tests before C7–C9.
- Live result prefix logic has the 128-character/subtype and scalar-only gaps; all three transport classifiers use `dict.get`; live legacy validator literal is mojibake while HEAD has the exact em dash.
- Active Builder allowlist remains exactly `bridge.py`, the three transports, and the one new AD test module. Intent is frozen; trackers, Git, GitHub, and committed tests remain forbidden.
- Gates 1–4 are unchanged.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Builder next step:** apply C7–C9 while preserving C1–C6. Do not touch `mesh/intent.py`, trackers, prompt docs, Git staging/history, or GitHub.
