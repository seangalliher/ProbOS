# AD-730-4 — Directed federated vision DMs

**Issue:** #634 — `AD-730-4: Federation peer-to-peer vision DMs`
**Repo:** OSS (`D:\ProbOS`)
**Exact executable base:** `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa` (`AD-731a-1d: enable reference-only federation attachment send (closes #638)`)
**Numbering:** issue #634 uniquely pre-reserves **AD-730-4**. Highest landed top-level remains **AD-1122**; highest landed BF remains **BF-672**. AD-730-4 is not a new top-level number and changes neither ceiling.
**Status:** **RE-APPROVED / CORRECTION EXECUTABLE.** Protocol viability was verified against live HEAD on 2026-07-16, the temporal contract was corrected on 2026-07-17, and two live-implementation reviews were BLOCKED then resolved in this packet. C1–C6 remain binding; C7–C9 below are the latest highest-precedence corrections.
**Dependencies:** AD-397 targeted local dispatch; AD-441/Phase-14c stable agent identities; AD-479/480 federation; AD-637e NATS transport; AD-730 vision DM consumption; AD-731 reference-only payloads; AD-731a-1 authenticated HTTP fetch; AD-731a-1d validated reference send; BF-672 prefetch-before-local-delivery.
**Current correction baseline:** the uncommitted AD module collected **85 tests** before C1–C6 and collects **211 tests** before C7–C9. Add the adversarial cases named below in that same uncommitted module and report the final observed collection count; no existing **committed** test-file edit is authorized.
**License disposition:** none — no external code, asset, model, package, or dependency.

AD-730-4 adds one **DM-only addressed federation path**. It does not turn arbitrary targeted intents into remote calls, advertise a remote roster, synchronize chat threads, or weaken the existing broadcast federation path. The wire carries text and canonical SHA-256 references only. Attachment bytes remain in `AttachmentStore` and are fetched from the authenticated origin HTTP endpoint before the one named receiver runs.

---

## BLOCKED implementation review correction packet (binding, 2026-07-17)

This section is the binding continuation contract for the live uncommitted diff. It preserves every prior DM-only, exact-target, reference-only, prefetch-before-send, cancellation, privacy, no-fallback, and legacy-untargeted requirement. Where earlier wording says only “strict JSON round-trip,” unconditional pending-map replacement, open-shaped response parsing, or clean two-doc pre-flight, this section replaces that wording.

### Latest BLOCKED re-review correction (C7–C9; highest precedence, 2026-07-17)

Preserve C1–C6 and every prior behavior. C7–C9 correct three defects in the current live implementation and supersede only conflicting wording in C1 item 5, C6's marker-classification mechanism, and any statement that the legacy validator literal may change. Do not reopen architecture, limits, error precedence, gates, or scope.

#### C7 — Reject image data-URL prefixes in every admitted response string position

Use one private exact-string helper for **all response strings**: scalar `result` strings, exact built-in dict keys, and the six-key result's `error` string. Invoke it only after that string has passed its existing per-string character admission. Result scalars/keys keep C1's accounting; `error` must be charged once to the same cumulative response-string UTF-8 budget before response assembly.

The helper is exact and work-bounded:

1. Require `type(value) is str`; callers already enforce this.
2. Skip leading ASCII-whitespace characters from the exact set `" \t\n\r\v\f"` only within the string's already-admitted character bound, then inspect exactly the next 11 candidate characters for `data:image/`. This is bounded by 65,536 character inspections for a result scalar/key and 4,096 for `error`; perform no subtype/delimiter scan.
3. Compare the candidate prefix case-insensitively with per-character ASCII folding over only those 11 candidate characters (or an equivalently constant-size slice); do **not** lowercase/copy/regex-scan the full string.
4. Reject whenever the first non-skipped characters are case-insensitively exactly `data:image/`, regardless of MIME subtype length, subtype contents, delimiter, or whether `;base64,` appears. This closes the live 128-character subtype loophole.
5. Allow ordinary prose that does not begin with that prefix after the bounded whitespace allowance, including `"The terms image_url and data:image are prohibited."`.

For a dict key, perform existing node admission, depth admission, exact-string type admission, character admission, cumulative UTF-8 byte accounting, and this prefix check **before** scheduling/admitting its value or inserting the key into the detached dict. For `error`, perform its existing exact type/4,096-character admission, cumulative UTF-8 byte accounting, and this same prefix check before response assembly. The `error` string is part of the response string budget even though it is outside the `result` subtree. The helper does not increment nodes itself: retain C1's root/item/key/value node accounting exactly once per position. Exact key preflight remains coherent because the outer six-key schema is still checked before field extraction, while arbitrary keys inside `result` are checked during bounded detachment.

Any forbidden scalar/key/error string is `federation_result_not_serializable` at both receiver finalization and origin parsing. Keep malformed non-string/oversized `error` as `federation_response_invalid` per C5. Add full receiver/origin tests for a scalar prefix, a dict key prefix, an `error` prefix, and a subtype longer than 128 characters; include mixed case and allowed ordinary prose. Prove the receiver emits only the fixed synthetic error and the origin never returns the rejected remote content.

#### C8 — Classify targeted responses without untrusted mapping operations

In each of `NATSFederationTransport.deliver_response()`, `FederationTransport.deliver_response()`, and `MockFederationTransport.deliver_response()`, replace the live `dict.get(message.payload, "delivery_mode")` classifier with one exact helper/inline algorithm:

1. `payload = message.payload`; only `type(payload) is dict` is eligible. Dict subclasses are legacy/non-targeted for this classifier and no override may run.
2. Iterate top-level entries with `dict.items(payload)` only. Never use `payload.get`, `payload[...]`, `key in payload`, `dict.get`, `dict.__contains__`, equality against a non-exact key, or any operation that can dispatch a payload/key/value subclass override.
3. For each entry, check `type(key) is str` **before** comparing it to the literal `"delivery_mode"`. Only when the exact key matches, count targeted mode if and only if `type(value) is str and value == "targeted_dm"`; then stop. A string-subclass value does not count.
4. If there is no exact built-in key/value marker, treat the response as legacy for queue behavior. Unknown, malformed, duplicate-impossible exact-dict state, subclass key/value, and dict-subclass payload do not count as targeted.
5. Preserve C6 ordering: perform pending lookup only for safe exact source/message IDs. An exact targeted marker with no owner drops; an exact targeted marker with malformed ID drops; any non-exact/malformed marker follows the legacy peer queue unchanged.

Hostile dict/key/value subclasses must record **zero override calls**. Add NATS/mock/socket-free ZeroMQ tests for exact targeted drop, malformed safe-ID marker queueing, malformed-ID exact-targeted drop, dict-subclass/key-subclass/value-subclass legacy queueing, and zero override invocation.

Work claim is intentionally narrow: the exact classifier scans the open legacy top-level payload in $O(n)$ until it finds the exact marker or exhausts entries. C7/C8 do **not** claim a constant global bound for legacy payload classification and do not add a top-level cap to the byte-identical legacy protocol. Network serializers/message ceilings remain the outer bound for real NATS/ZeroMQ traffic; in-memory direct calls can still present a large exact dict. Do not describe C8 as bounded work.

#### C9 — Preserve the exact legacy validator log literal

Restore this exact UTF-8 source literal in the unchanged legacy `forward_intent()` validator catch:

```text
Federation message validator failed — message passed without validation
```

The current worktree contains mojibake `â€”`; the exact base contains the single Unicode em dash `—` (UTF-8 bytes `E2 80 94`). This is a regression in a legacy executable body and violates byte-identical behavior. Change only those corrupted source characters; do not alter the logger call, level, arguments, `exc_info=True`, or legacy log semantics. C3's type-only rule applies only to the four new directed exception boundaries and does not authorize rewriting this pre-existing legacy record.

Add a direct regression in the uncommitted AD test module: read `git show HEAD:src/probos/federation/bridge.py` and the worktree source as UTF-8, parse both with `ast.parse`, locate the unique string constant beginning `Federation message validator failed`, and assert exact literal equality to the text above in both trees. Encode each extracted AST constant itself and assert the exact UTF-8 bytes contain `E2 80 94` and not the UTF-8 encoding of `â€”`; do not rely on a whole-file byte search because unrelated directed prose may contain em dashes. Do not modify any committed test.

### Latest correction resolution matrix

| Finding | Binding correction |
|---|---|
| 7. Data-URL detection misses dict keys/`error` and permits long subtypes | C7 applies one bounded prefix helper to every admitted response string position and rejects `data:image/` independently of subtype/delimiter. |
| 8. Transport marker classification invokes untrusted mapping equality/get behavior | C8 uses exact dicts, unbound `dict.items`, exact key/value types, and preserves malformed-marker legacy queue behavior. |
| 9. Legacy validator log em dash became mojibake | C9 restores the exact base UTF-8 literal and adds base-vs-worktree AST/byte regression coverage. |

### Exact continuation state

HEAD and origin remain `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa`. The correction starts with no staged paths and exactly this visible working tree:

```text
 M src/probos/federation/bridge.py
 M src/probos/federation/mock_transport.py
 M src/probos/federation/nats_transport.py
 M src/probos/federation/transport.py
 M src/probos/mesh/intent.py
?? prompts/ad-730-4-directed-federated-vision-dm-execution.md
?? prompts/ad-730-4-directed-federated-vision-dm.md
?? tests/test_ad730_4_directed_federated_vision_dm.py
```

`logs/ad730_4_issue_update.md` remains ignored. The current `IntentBus.has_subscriber()` addition is accepted and frozen: **do not edit `src/probos/mesh/intent.py` during this correction**. Correction edits are authorized only in the four federation implementation files plus the one AD test module listed under “Correction allowlist.” Trackers, Git, and GitHub remain untouched until all unchanged Gates 1–4 pass and Architect review is green.

### Six required findings — resolution matrix

| Finding | Binding correction |
|---|---|
| 1. Result JSON work is open-ended and shape-blind | Replace direct `json.dumps()` admission with the iterative bounded result policy in C1. Validate exact built-ins, depth/nodes/text/bytes, cycles, finite numbers, and forbidden image/blob shapes before final JSON detach. |
| 2. Pending entries can overwrite/cancel one another and register after stop | Apply unique-key admission, owner-conditional cleanup, and a closed registration gate in C2 to all three transports. Preserve register-before-send for synchronous mock responses. |
| 3. Four new exception boundaries leak messages/tracebacks | Apply the safe logging templates in C3: safe IDs plus `type(exc).__name__` only; never exception text, `repr`, traceback, result, params, DM text, token, or blob. |
| 4. Directed envelope/correlation/marker schemas are not exact or bounded | Apply the exact seven-key request payload, safe correlation ID, exact response envelope, and canonical four-name marker policy in C4. Reject oversized metadata before iterating it. |
| 5. Remote `IntentResult` fields are accepted by `.get()` without types | Apply the exact six-key schema and finite-confidence gate in C5 before constructing `IntentResult` or invoking `_validate_fn`. |
| 6. Correlation hardening could regress malformed legacy responses | Apply C6: pending lookup only for safe exact string IDs; malformed directed response IDs drop; malformed legacy response IDs retain the old peer queue path. |

### C1 — Iterative bounded JSON-safe result policy

Use one directed-only bounded value validator/detacher for the `result` subtree in both directions. The receiver first requires `type(local_result) is IntentResult`, extracts its six fields, and validates them via C5; the origin first requires C5's exact six-key built-in dict. Both then pass only the `result` field through the same C1 value helper before response construction/`IntentResult` construction. Do **not** recurse and do not call `json.dumps()` on an unvalidated target object. Use an explicit LIFO stack and exact built-in operations only.

Pinned limits:

```text
_DIRECTED_RESULT_MAX_DEPTH = 16              # root value is depth 0
_DIRECTED_RESULT_MAX_NODES = 4_096           # root + every list item + every dict key + every dict value
_DIRECTED_RESULT_MAX_STRING_CHARS = 65_536   # each exact string, including keys
_DIRECTED_RESULT_MAX_UTF8_BYTES = 262_144     # cumulative exact-string UTF-8 bytes
_DIRECTED_RESPONSE_MAX_JSON_BYTES = 262_144  # complete two-key response payload, compact UTF-8 JSON
_DIRECTED_ERROR_MAX_CHARS = 4_096
```

These bounds do not conflict with current outputs: the live `CognitiveAgent` direct-message path returns reply text. Text tiers use the 2,048-token `LLMRequest` default, while the live vision-tier override is 8,192 tokens; even a conservative four characters/token is about 32 KiB. Existing object results are shallow JSON dictionaries/lists. A 64-Ki-character individual string and a 256-KiB complete response leave substantial headroom while remaining below the default 1-MiB NATS message ceiling. Depth 16 and 4,096 nodes admit ordinary nested objects but bound adversarial traversal.

The policy is exact:

1. Admit only `None`, exact `bool`, exact `int`, exact `float`, exact `str`, exact `list`, and exact `dict`. Reject tuples, sets, mappings/sequences, dataclasses, custom objects, and **all subclasses**. Check with `type(value) is ...`; never use polymorphic iteration, `str(value)`, `float(value)`, `repr(value)`, `.items()`, `.get()`, or other overrideable methods on an untrusted non-exact object.
2. Admit exact integers only in signed 64-bit range. Admit exact floats only when `math.isfinite(value)`. `bool` is handled before `int`. Reject NaN and both infinities.
3. For an exact list, use built-in list operations; for an exact dict, use built-in dict operations and require every key to be an exact string. Preserve insertion order in the detached copy. Use explicit stack enter/exit frames and an active-path container-ID set: add an ID on enter, remove it on its exit frame, and reject only an ID already active. Repeated aliases outside the active path are allowed and become independent detached copies.
4. Increment the node counter **before** admitting each root/item/key/value and stop at 4,096. Check string character length and cumulative UTF-8 bytes incrementally. Do not scan beyond the first over-limit node/string.
5. Apply C7's one bounded helper to every admitted response string position: scalar result strings, exact dict keys, and `error`. After skipping only leading ASCII whitespace within the already-admitted per-string bound, reject a case-insensitive `data:image/` prefix regardless of subtype/delimiter. Do not lowercase/copy/regex-scan the full string. Free prose not beginning with that prefix remains ordinary text.
6. Reject image/blob object shapes without banning ordinary `data` objects: reject an exact dict when `type == "image_url"`; when it contains the exact key `image_url`; when `type == "base64"` with a `data` key; when `type == "image"` with a `data` key; or when its exact-dict `source` contains `type == "base64"` or any `data` key. Ordinary results such as `{"data": {"rows": [1, 2]}, "summary": "ok"}` remain valid.
7. Reject exact `bytes`, `bytearray`, and `memoryview` as unsupported before any conversion. Their subclasses are rejected by the unsupported-type rule without invoking overrides.
8. After building the detached exact-built-in tree and admitting/accounting C7's `error` string, assemble the exact six-key result object from C5 and compact-serialize the complete directed response payload with `json.dumps(..., ensure_ascii=False, allow_nan=False, separators=(",", ":"))`. Encode UTF-8 and require at most 262,144 bytes, then `json.loads()` that validated JSON for final wire detachment. No truncation, coercion, or replacement is permitted.

Any local target result that fails exact type/schema, bounded value policy, cycle, or final response byte limit is replaced with one safe synthetic `IntentResult(error="federation_result_not_serializable")`. Validate/serialize that fixed small synthetic response through the same exact response helper; if even that invariant cannot serialize, drop rather than forwarding rejected data. The rejected value is never serialized or logged. At the origin, a structurally exact six-key result whose `result` subtree violates this policy returns the same stable `federation_result_not_serializable`; malformed outer result schema/types use `federation_response_invalid` per C5. Legitimate text/object results are copied unchanged.

### C2 — Pending-map ownership and lifecycle admission

Apply this contract independently to `NATSFederationTransport`, `FederationTransport`, and `MockFederationTransport`:

Keep the public signature exactly `request_peer(...) -> FederationMessage | None`. `None` means response timeout only. The method raises only lifecycle control (`CancelledError`) or the pinned internal admission/invariant `ValueError`/`RuntimeError` codes below; the bridge converts those ordinary internal exceptions to its existing `IntentResult` error matrix.

- Add a private request-admission flag initialized **open** for direct-construction compatibility. `start()` reopens it only after that transport's existing startup work succeeds; a failed/cancelled start leaves it closed. `stop()` closes it as its first request-lifecycle action, before snapshot/cancel/clear or any await.
- `request_peer()` first requires `isinstance(message, FederationMessage)` (message dataclass subclasses are not traversed here), a safe exact peer ID using the existing node-ID contract (`type is str`, 1–128, `[A-Za-z0-9_-]+`), and a safe exact correlation ID from C4. Invalid peer/correlation input raises `ValueError("federation_correlation_id_invalid")` before map/send work. C1's exact-type rule still governs every untrusted result container/scalar.
- Post-stop admission raises `RuntimeError("federation_transport_closed")` immediately, performs zero send, and leaves no pending entry.
- If `(peer_node_id, message.message_id)` is already present, raise `RuntimeError("federation_request_key_in_use")` immediately. Never replace, cancel, or otherwise touch the existing owner; perform zero send.
- Otherwise create and register the future before the first await and before `send_to_peer()`. This ordering is load-bearing because the mock/NATS callback can synchronously deliver a response during the send await.
- In `finally`, remove only by identity: `if self._pending_requests.get(key) is pending: pop`. Cancel only that request's still-pending future. An older request resuming after stop/restart must never pop or cancel a newer same-key owner.
- `stop()` closes admission, snapshots owned futures, clears the map, and cancels those futures before awaiting any receive task/socket teardown. No request can register after the snapshot. `CancelledError` propagates from callers exactly as before.
- Preserve direct-construction compatibility: the bridge directed-admission gate is open at construction. `FederationBridge.stop()` closes it before awaiting gossip cancellation. A new `forward_direct_message()` after bridge stop returns `federation_target_node_unavailable` with zero transport work. A successful `FederationBridge.start()` reopens the bridge gate. An already-admitted request is transport-owned and is cancelled by transport stop; do not add a bridge task registry.

Bridge mappings are exact:

| Transport outcome | Bridge result |
|---|---|
| bridge already stopped or `RuntimeError("federation_transport_closed")` | `federation_target_node_unavailable` |
| `RuntimeError("federation_request_key_in_use")`, invalid correlation invariant, or other ordinary request exception | `federation_target_delivery_failed` |
| `request_peer()` returns `None` | `federation_peer_timeout` |
| caller cancellation | propagate `CancelledError` |

**NATS/legacy send decision:** do not change `send_to_peer()`'s signature or legacy swallow-and-log behavior. Therefore `request_peer()` cannot distinguish a NATS publish failure, a ZeroMQ missing dealer no-op, or an unreachable configured mock peer from silence. Those cases wait for the directed timeout, return `None`, and map to `federation_peer_timeout`. Do not invent immediate “unavailable” detection or a new send return value in AD-730-4.

### C3 — Safe logging at the four new exception boundaries

The four ordinary-exception boundaries are: outbound `request_peer`, remote-result validator, inbound attachment resolver, and exact target delivery. Catch as `except Exception as exc` and log only:

- already-validated node/message/intent/agent IDs appropriate to that boundary;
- the literal stable next action/error code; and
- `type(exc).__name__` through an `exception_type=%s` field.

Never use `exc_info=True`, `logger.exception`, `%s`/`%r` with `exc`, `str(exc)`, `repr(exc)`, traceback formatting, or exception chaining in these four records. Never include DM text, params, result body, bearer token, attachment bytes/ref contents, source URL, or rejected object. Tests must use exceptions whose message contains a canary secret/blob marker and assert for all four boundaries that the canary and traceback are absent, `record.exc_info is None`, the exception class name is present, and only safe IDs/stable action text remain. This correction does not rewrite pre-existing legacy logging methods; it prevents every newly introduced directed bridge record from adding a leak.

### C4 — Exact directed envelopes, safe correlation, and canonical marker

The directed request payload is an **exact built-in dict of exactly seven keys**:

```text
delivery_mode, target_node_id, target_agent_id, intent, params, id, ttl_seconds
```

Require `dict.__len__(payload) == 7` before iterating and require its exact key set to equal those seven names. Missing or unknown keys are `federation_payload_invalid`; no resolver or local delivery runs. The enclosing `FederationMessage` must have exact `type == "intent_request"`, a configured safe source, and a safe correlation ID before server-owned provenance is installed. Valid sender-local `timestamp` remains ignored.

The safe correlation ID contract is:

```text
type(value) is str
1..128 characters
full match: ^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$
```

It admits the production default `uuid.uuid4().hex` and every verified current federation ID shape (`test-123`, `resp-456`, `gossip-1`, `ping-123`, `bf672-designed-agent`) plus the current AD test IDs. It rejects empty, oversized, whitespace, punctuation, non-string, and string-subclass IDs. A directed request with a malformed correlation ID is dropped without response, resolver, local send, provenance injection, or log content because no safe response correlation exists.

At origin, require the newly constructed `FederationMessage.message_id` to satisfy this contract before calling `request_peer()`; failure is the bridge's internal invalid-correlation invariant and maps to `federation_target_delivery_failed` with zero send. Do not replace or normalize it.

The directed response payload is an exact built-in two-key dict `{delivery_mode, results}`; `delivery_mode` is exact `targeted_dm`; `results` is an exact built-in list of length one. The sole entry follows C5. Unknown/missing response keys are `federation_response_invalid`.

`_transport_stripped` has one canonical producer/receiver vocabulary and order:

```text
("attachment_ref", "attachment_refs", "vision_messages", "has_image_attachment")
```

Outbound recomputes it from the sanitizer and ignores any caller marker. If present inbound, require an exact built-in list with length 1..4 **before inspecting an item**, then require exact strings and equality to an ordered unique subsequence of that tuple. Empty, duplicate, reordered, unknown, non-string, subclass, or length >4 is `federation_payload_invalid`. The directed params dict itself is exact, has at most these six keys before iteration—`text`, `attachment_ref`, `attachment_refs`, `vision_messages`, `has_image_attachment`, `_transport_stripped`—and contains no unknown key. A million-entry marker or million-key payload is rejected by O(1) length admission before element/key traversal.

### C5 — Exact serialized `IntentResult` schema before validation

The one serialized directed result is an exact built-in dict with exactly these six keys and no defaults or unknown fields:

```text
intent_id, agent_id, success, result, error, confidence
```

Require:

- `intent_id`: exact safe intent-ID string, then exact equality to the original intent ID;
- `agent_id`: exact safe agent-ID string, then exact equality to the requested target;
- `success`: exact `bool`;
- `result`: C1 bounded JSON-safe value (including `None`);
- `error`: exact `None` or exact string of at most 4,096 characters;
- `confidence`: exact built-in `int` or `float`, not `bool`; guarded conversion to float; finite. Preserve the finite normalized float. Do not add a new range restriction in this AD.

When `error` is a string, apply C7's cumulative UTF-8 accounting and bounded image-prefix rejection after the 4,096-character admission. At the receiver require `type(local_result) is IntentResult` before reading fields, then build/validate the six-key object. At the origin perform exact key-count/key-set/type/finite/result-policy checks **before** constructing `IntentResult` and before `_validate_fn`. Only after that gate apply intent/agent correlation and the optional validator. Validator cancellation propagates; its ordinary exception keeps the prior directed log-and-pass semantics but uses C3-safe logging.

Error precedence is stable: malformed outer response type/source/message-id/two-key envelope/results container/count or malformed six-key container/key/type/error/confidence is `federation_response_invalid`; exact IDs of the wrong value retain `federation_result_correlation_mismatch` / `federation_result_target_mismatch`; unsafe bounded `result` content is `federation_result_not_serializable`; validator false is `federation_result_validation_failed`.

### C6 — Directed drop vs legacy malformed-ID queue parity

In each transport, compute pending lookup eligibility only when both `from_node_id` and `message.message_id` satisfy the exact safe built-in-string contracts. Never index `_pending_requests` with a malformed correlation ID.

Classify the exact directed marker only with C8's exact-dict/unbound-`dict.items` algorithm. Do not use `.get()`, membership, subscription, or polymorphic key/value comparison on the untrusted payload. A malformed/non-exact marker is legacy; only the exact built-in key/value pair counts as targeted.

- Safe exact key + owner present: resolve that owner only.
- No owner + exact directed payload marker: drop.
- Malformed correlation ID + exact directed payload marker: drop.
- Malformed correlation ID + legacy response payload (no `delivery_mode="targeted_dm"`): execute the pre-AD peer-keyed queue path unchanged. The malformed legacy message ID is opaque legacy data and must still be returned by `receive_with_timeout()`.

Do not tighten, normalize, regenerate, or reject legacy message IDs in `_deserialize()`, `deliver_response()`, or the peer queue. This carve-out is deliberate: correlation hardening is new-path-only.

### Required correction tests

Add these exact behaviors to the existing AD module; parameterize transport cases over NATS, mock, and socket-free/fake-socket ZeroMQ as applicable:

1. `test_directed_result_policy_accepts_legitimate_text_and_shallow_object_unchanged`
2. `test_directed_result_policy_rejects_binary_nonfinite_cycle_depth_nodes_string_and_json_byte_limits`
3. `test_directed_result_policy_rejects_data_url_image_url_and_base64_source_shapes_but_not_prose_or_ordinary_data_object`
4. `test_directed_result_policy_rejects_hostile_container_and_scalar_subclasses_without_invoking_overrides`
5. `test_directed_result_policy_bounds_million_item_work_before_json_serialization`
6. `test_directed_request_payload_requires_exact_seven_keys_before_prefetch_or_send`
7. `test_directed_response_requires_exact_two_key_envelope_and_one_exact_six_key_result`
8. `test_directed_result_rejects_non_bool_success_bad_error_and_nonfinite_confidence_before_validator`
9. `test_transport_stripped_requires_canonical_ordered_unique_subset_and_rejects_million_entries_without_scan`
10. `test_directed_malformed_request_message_id_drops_before_provenance_prefetch_send_or_response`
11. `test_request_peer_duplicate_live_key_rejected_without_replacing_owner` on all three transports
12. `test_request_peer_owner_cleanup_cannot_remove_new_same_key_owner` on all three transports
13. `test_request_peer_post_stop_rejected_without_registration_or_send` on all three transports
14. `test_request_peer_start_reopens_admission` on all three transports
15. `test_request_peer_stop_restart_old_finally_cannot_remove_new_same_key_owner` on all three transports
16. `test_request_peer_registers_before_synchronous_mock_response`
17. `test_bridge_post_stop_rejects_and_start_reopens_directed_admission`
18. `test_nats_swallowed_publish_error_remains_timeout_not_immediate_unavailable`
19. `test_directed_malformed_response_message_id_is_dropped` on all three transports
20. `test_legacy_malformed_response_message_id_preserves_peer_queue_behavior` on all three transports
21. `test_directed_exception_logs_are_type_only_without_message_traceback_or_payload` with four boundary case IDs
22. `test_directed_result_policy_rejects_data_image_prefix_in_scalar_dict_key_error_and_long_subtype_at_receiver_and_origin`
23. `test_transport_targeted_marker_classifier_uses_exact_builtins_without_hostile_overrides` on NATS, mock, and socket-free ZeroMQ
24. `test_transport_malformed_marker_preserves_legacy_queue_but_exact_targeted_malformed_id_drops` on all three transports
25. `test_legacy_validator_log_literal_matches_base_utf8_em_dash`

For million-entry guards, combine a real oversized built-in container stress case with an AST/control-flow assertion that the exact-length rejection dominates any iteration/comprehension in the dedicated marker/envelope helper; do not rely only on a flaky wall-clock threshold. Keep every existing temporal, attachment, no-fallback, deep-detach, serializer-parity, and legacy-envelope test.

### Correction allowlist

Builder may now edit only:

- `src/probos/federation/bridge.py`
- `src/probos/federation/nats_transport.py`
- `src/probos/federation/transport.py`
- `src/probos/federation/mock_transport.py`
- `tests/test_ad730_4_directed_federated_vision_dm.py`

This is the exact active **five-path** Builder allowlist. No other production or test path may change during C7–C9.

`src/probos/mesh/intent.py` remains part of the eventual AD final diff, but its current uncommitted `has_subscriber()` implementation is accepted and **must remain unchanged** during correction. The two active prompt docs and ignored issue update are Architect-owned. Do not edit trackers, stage, commit, push, or mutate GitHub during correction.

---

## Protocol viability verdict

**Verdict: viable on live HEAD; no separate prerequisite AD is required.** The addressed primitive is small enough to live inside AD-730-4, but it must remain restricted to `direct_message`. A generic addressed-federation primitive for arbitrary intents would let a peer call a named side-effecting agent through `IntentBus.send()` and bypass broadcast-time authorization/consensus. That broader primitive is not a prerequisite and is explicitly forbidden here.

### Required answers (a)–(g)

| Question | Binding answer |
|---|---|
| **(a) How does the origin name exactly one remote node?** | By the exact operator-configured `PeerConfig.node_id`, supplied as the `target_node_id` argument to new public `FederationBridge.forward_direct_message(target_node_id, intent)`. It is not a vessel name, callsign, URL, trust rank, or router-selected node. The bridge requires one non-empty NATS-safe ID, requires it in `config.federation.peers`, requires it in `transport.connected_peers`, rejects self-targeting, and calls `send_to_peer()` once. |
| **(b) How does it name exactly one remote agent?** | By `IntentMessage.target_agent_id`, using the receiver's exact live `BaseAgent.id` / `AgentRegistry` slot key. Pool-created IDs are deterministic via `generate_agent_id()` and survive restart/recycle. The pair `(target_node_id, target_agent_id)` disambiguates identical slot names on different nodes. Callsigns are mutable/non-unique presentation data and must never be resolved on this wire. Sovereign UUID/DID remains identity provenance, but is not the current `IntentBus` subscriber key and is not silently translated here. |
| **(c) Is `target_agent_id` currently carried by federation?** | **No.** `IntentMessage` has it and local NATS serialization carries it, but `FederationBridge.forward_intent()` omits it from `FederationMessage.payload`; inbound reconstruction leaves it `None`, then calls local `broadcast()`. AD-730-4 adds it only to a new `delivery_mode="targeted_dm"` envelope. |
| **(d) How does the receiver deliver targeted with zero fallback/fan-out?** | Validate directed envelope/source/node/intent/target first; confirm `IntentBus.has_subscriber(target_agent_id)`; run BF-672 attachment resolution; construct an `IntentMessage` with the exact target; call `await intent_bus.send(intent)` exactly once. Never call `broadcast()` for a targeted envelope, never resolve a callsign, never select a replacement, and never retry another local agent. A decoy subscribed to `direct_message` must observe zero calls. |
| **(e) What response/error shape is used when the target is absent?** | Reuse the existing `IntentResult` shape inside the existing `intent_response.payload["results"]` list: exactly one result with the original `intent_id`, requested stable `agent_id`, `success=False`, `result=None`, `error="federation_target_not_found"`, `confidence=0.0`. No roster, callsign, alternative IDs, exception text, or fallback result is exposed. |
| **(f) Privacy, trust, time, and loop behavior?** | Only bounded DM text + canonical refs cross; session history, caller context/urgency, authority/qualification flags, project/recall/tool state, and unknown params are dropped, while the receiver installs server-owned federation provenance/session fields. Directed requests are admitted only from/to statically configured peers; unknown/spoofed `source_node` is dropped without response (avoids reflection), self-source is dropped, and a payload naming the wrong receiver node is rejected without local delivery. This is configured-peer admission, **not cryptographic source authentication**; AD-730-4 does not overclaim otherwise. Existing NATS/ZeroMQ deployment security remains the outer trust boundary. `FederationMessage.timestamp` is sender-local monotonic metadata and is never compared with the receiver's clock. The bounded TTL controls the origin wait and the newly reconstructed receiver-local `IntentMessage` handling budget only; this AD provides no receiver age or replay defense. The exact destination bypasses capability/affinity selection but not the configured peer allowlist. Malformed/absent/denied routes do not update agent trust. Valid remote results may use the bridge's already-optional result validation hooks when wired, but this AD does not activate dormant trust wiring because legacy behavior must remain byte-identical. `federated=False` is unnecessary on `send()`; no broadcast occurs, and inbound handling never calls the outbound directed method, so there is no loop. Attachment HTTP fetch remains bearer-gated and SHA/MIME/size verified. |
| **(g) Is a generic addressed-federation primitive a prerequisite?** | **No separate prerequisite.** AD-730-4 adds a narrowly reusable transport-correlated request seam plus a public **DM-only** bridge method. Arbitrary-intent remote targeting is explicitly not built because its governance semantics are unresolved. |

### Identity/discovery limitation — explicit and accepted

`NodeSelfModel` gossips only node ID, capabilities, pool sizes, agent count, health, uptime, and timestamp. It does **not** advertise an agent roster. Therefore the caller must already possess the exact stable `(node_id, agent_id)` pair from an operator-controlled directory/configuration or another governed surface. AD-730-4 transports an address; it does not discover one. No callsign map or live registry contents cross gossip.

---

## Verified root cause at the exact base

1. `IntentMessage.target_agent_id` exists at `src/probos/types.py:68`.
2. Local `IntentBus.send()` requires a target and looks up only `self._subscribers[target_agent_id]` on the direct path; `broadcast()` delegates to `send()` when a target exists.
3. Local NATS intent serialization includes `target_agent_id` at `mesh/intent.py:1117` and restores it at `:1136`.
4. Federation outbound payload at `federation/bridge.py:304-312` carries `intent`, `params`, `urgency`, `context`, `id`, and `ttl_seconds` only — no target node or target agent.
5. Federation peer selection uses `FederationRouter.select_peers(...)`, which may return multiple capability/trust/affinity-ranked nodes.
6. Federation inbound reconstruction at `bridge.py:396-404` creates an untargeted `IntentMessage`; after BF-672 prefetch it calls `intent_bus.broadcast(intent, federated=False)` at `:422`, which can fan out locally.
7. `NodeSelfModel` has no agent IDs. Local `AgentRegistry.get(agent_id)` and `IntentBus` subscriptions are keyed by `BaseAgent.id`; pool IDs are deterministic through `substrate.identity.generate_agent_id()`.
8. The 1:1 API builds `direct_message` with exact `target_agent_id=agent_id`; `CognitiveAgent.handle_intent()` treats a targeted `direct_message` to `self.id` as direct; its vision branch consumes `params["vision_messages"]`.
9. AD-731a-1d sanitizes federation attachment surfaces to canonical SHA refs and rejects inline base64/data/image URLs/Python bytes. BF-672 calls the injected resolver before local consumption. AD-731a-1 fetches bytes through an authenticated ASGI route and verifies SHA, MIME, and size before store.
10. NATS addresses one node using raw subject `federation.intent.{node_id}`; ZeroMQ uses one configured DEALER per peer. Both serialize the same `FederationMessage` fields. Existing response queues are peer-keyed only, so concurrent same-peer directed requests need exact `message_id` correlation before #634 can be correct.
11. Raw federation `source_node` is asserted by the envelope. ZeroMQ receives a socket identity but currently discards it; NATS exposes no publisher identity to the bridge. Therefore this AD can reject an unconfigured/self source but cannot claim cryptographic anti-spoofing. No signing prerequisite exists in the current AD-480 configured-peer model; adding signatures/CURVE/NATS account credentials is a separate federation-security decision.
12. Production `organize_fleet()` currently constructs the bridge/router and attaches BF-672's narrow resolver. No new runtime back-reference is needed.
13. Every production `FederationMessage` created by `FederationBridge` stamps `time.monotonic()`. Both transports serialize/deserialize that float, but no production consumer currently interprets the envelope timestamp as wall-clock time or request age. It is not comparable across processes, hosts, or boots.
14. `IntentMessage` has no `is_expired()` method. `SignalManager.is_alive()` / `_reap()` compare receiver-local UTC wall time with `IntentMessage.created_at`, but `IntentBus.send()` does not call either one: it uses `ttl_seconds` only as a fresh per-call handler/NATS timeout. The directed receiver constructs a new `IntentMessage` without supplying `created_at`, so its default factory starts the lifetime locally at reconstruction and no origin creation time crosses federation.
15. Exact `(peer_node_id, message_id)` response correlation prevents cross-talk between outstanding origin requests and isolates late responses; it does **not** deduplicate or reject replayed inbound requests. An authenticated wall-clock/nonce envelope and replay store are separate future security work.

---

## Pinned design decisions

### DD-730-4-1 — New method, not an overload of legacy federation

Add this fully annotated public method to `FederationBridge`:

```python
async def forward_direct_message(
    self,
    target_node_id: str,
    intent: IntentMessage,
) -> IntentResult:
```

Preconditions:

- `type(target_node_id) is str`, 1–128 chars, exact pattern `[A-Za-z0-9_-]+`;
- target is not `self._node_id`;
- target is in the exact configured `PeerConfig.node_id` set;
- target is in `transport.connected_peers` at call time;
- `intent.intent == "direct_message"` exactly;
- `type(intent.target_agent_id) is str`, 1–256 chars, exact pattern `[A-Za-z0-9_-]+`;
- `type(intent.params) is dict`.

A failed precondition returns one local synthetic `IntentResult` with a stable machine-code error and performs zero transport, resolver, local delivery, trust, or fallback work. Do not raise for caller input. `asyncio.CancelledError` remains lifecycle control and always propagates.

Do not add `target_node_id` to `IntentMessage`. Node addressing belongs to the federation bridge/transport boundary; the local message continues to describe one local subscriber target.

Do not alter `forward_intent()` or register the new method as `IntentBus._federation_fn`. Legacy untargeted federation remains on `forward_intent` exactly.

### DD-730-4-2 — Exact directed wire envelope

The new method constructs one `FederationMessage(type="intent_request", source_node=self._node_id, ...)` with this exact payload shape:

```text
{
  "delivery_mode": "targeted_dm",
  "target_node_id": <exact configured node id>,
  "target_agent_id": <exact stable local subscriber id>,
  "intent": "direct_message",
  "params": <strict JSON-detached, privacy-minimized DM params>,
  "id": <original IntentMessage.id>,
  "ttl_seconds": <finite positive value capped to 60.0>
}
```

Do not carry `thread_id`: origin and receiver chat-thread namespaces are local and unsynchronized. Cross-node thread synchronization is not part of #634.

Do not carry caller-authored `context` or `urgency`. The receiver constructs
`context="federation:<source_node>"` and uses neutral urgency `0.5`; a remote
peer cannot inject local authority/priority framing through those fields.
The new request wait uses this same normalized DM TTL in milliseconds, not the
legacy `FederationConfig.forward_timeout_ms` query timeout (default 5 seconds):
real CognitiveAgent DM/vision turns already use a 60-second local TTL and would
otherwise time out before a normal LLM response. This is new-path-only; legacy
`forward_intent()` continues to use `forward_timeout_ms` exactly.

The origin TTL contract is exact and new-path-only: reject `bool`, non-built-in
numeric types, strings, non-finite values, zero, and negatives. First require
`type(value) in (int, float)`, then convert inside `try/except (OverflowError,
TypeError, ValueError)` to a local float; require `math.isfinite(normalized)` and
`normalized > 0.0`, then emit `min(normalized, 60.0)`. Conversion failure is a
normal `federation_payload_invalid` result, never a raised caller-input error.
Convert the capped TTL to the transport's integer `timeout_ms` with `max(1,
math.ceil(ttl_seconds * 1000.0))`. The receiver applies the same exact-type,
guarded-conversion, and finite/positive checks to wire `ttl_seconds`, additionally
requires the normalized value to be no greater than `60.0`, and rejects an
over-cap wire value rather than silently normalizing peer input.

The validated TTL has only two meanings: it bounds the origin's correlated
response wait, and it becomes the `ttl_seconds` of the newly reconstructed
receiver-local `IntentMessage`. Do not supply `created_at`; its default factory
starts a new local lifetime, and no origin `created_at` is carried.
`IntentBus.send()` does not check `created_at` or call
`SignalManager.is_alive()`—it uses the TTL as a fresh handler/NATS timeout from
the local send call. Therefore this is a bounded execution/wait budget, not a
transport-age assertion.

Keep `FederationMessage.timestamp=time.monotonic()` unchanged for wire parity
and diagnostics, but **never compare it with a receiver clock and never use it
for directed admission**. Monotonic epochs are process/host/boot-local. This AD
intentionally provides no receiver request-age check, nonce deduplication, or
replay protection. Exact response correlation is not replay defense. Do not add
an unauthenticated wall-clock field: clock skew and sender forgery would make it
an unreliable security boundary. Authenticated wall-clock/nonce envelopes plus
bounded replay state require a separate federation-security AD.

The response remains `FederationMessage(type="intent_response", source_node=<receiver>, message_id=<request message_id>)` with:

```text
{
  "delivery_mode": "targeted_dm",
  "results": [<exactly one serialized IntentResult>]
}
```

Every valid directed response carries exactly one result. Zero or multiple results is protocol-invalid and becomes `federation_response_invalid` at the origin.

### DD-730-4-3 — Reuse the attachment sanitizer inside a privacy-minimized DM allowlist, then detach through strict JSON

Call `_sanitize_attachment_params_for_federation(intent.params)` exactly once. Preserve its 8-unique-SHA, 64-plural-position, and 64-vision-position ceilings and its current hostile-key totality. Retain `_transport_stripped` exactly as legacy federation does when attachment keys were processed.

The directed DM wire does **not** inherit legacy federation's open generic-param
contract. Reconstruct a new params dict from these fields only:

- `text`: exact built-in string, at most 65,536 characters;
- sanitized `attachment_ref`, `attachment_refs`, `vision_messages`, and derived
  `has_image_attachment` when retained by AD-731a-1d;
- `_transport_stripped` when the sanitizer reports processed attachment keys.

Require non-empty `text` or at least one retained canonical attachment ref.
Silently drop every other caller-authored key, including `from`, `to`,
`author_id`, `is_captain`, `was_mentioned`, `_qualification_test`, `session`,
`session_history`, `captain_message`, `_visual_scene`, `_visual_novelty`,
`_visual_summary`, project/recall blocks, tool state, and arbitrary nested
metadata. This is the cross-mesh privacy and minimal-authority boundary: one DM
turn crosses, not the origin mesh's private conversation/context state.

At the receiver, add only server-owned values after validation and detachment:

```text
from = "federation:<source_node>"
federation_source_node = <source_node>
federation_message_id = <FederationMessage.message_id>
session = false
session_history = []
```

Caller-supplied values for those names never survive. The server-owned `from`
value also prevents a remote peer from impersonating local `hxi_profile` or
`captain`, and avoids the dedicated-local-API episode skip in
`CognitiveAgent._store_action_episode`; an otherwise valid federated DM remains
eligible for the generic action-episode safety net.

Known limitation: the shared `direct_message` prompt renderer currently labels
all DM text as `Captain says:`. AD-730-4 does not alter that established local
prompt/golden contract or `CognitiveAgent`; the server-owned federation
provenance fields make the true source machine-readable to downstream memory
and future prompt work. A sender-aware human-readable DM label is a separate
prompt-semantics AD, not permission to accept caller-authored `from` here.

Then strict-JSON round-trip the **directed request copy only** (`json.dumps(..., allow_nan=False)` → `json.loads(...)`) before placing it in the message. Request fields are already bounded and canonical. Result values use the stronger iterative C1 validator **before** any JSON serialization. This:

- proves the directed wire is JSON serializable before network work;
- rejects Python `bytes`, `bytearray`, `memoryview`, non-finite floats, and other non-wire objects;
- breaks every nested alias between the caller's params and the transport payload;
- mirrors the real NATS/ZeroMQ wire boundary even under the in-memory `MockNATSBus`;
- does not change the legacy untargeted path.

Known attachment surfaces may carry canonical lowercase 64-hex SHA refs and approved MIME only. Inline base64 blocks, data URLs, image URLs, Python byte containers, and raw image bytes must not occur in NATS dicts, ZeroMQ bytes, receiver params, responses, or logs.

Apply C1 and C5 to the directed response payload. A non-serializable target result becomes one `federation_result_not_serializable` error; raw bytes are never forwarded.

### DD-730-4-4 — Exact request correlation is transport-owned

Add a new method with the same signature to `NATSFederationTransport`, `FederationTransport`, and `MockFederationTransport`:

```python
async def request_peer(
    self,
    peer_node_id: str,
    message: FederationMessage,
    timeout_ms: int,
) -> FederationMessage | None:
```

Each transport owns a private pending map keyed by `(peer_node_id, message.message_id)` and implements the C2 unique-owner/lifecycle contract. It registers the future **before** calling `send_to_peer()`. `deliver_response()` performs only a C4/C6-safe exact pending lookup. If none exists:

- a response whose payload has `delivery_mode == "targeted_dm"` and has no exact pending key is an unmatched directed response and is dropped (never poison the legacy peer queue; no clock-age judgment is made);
- every legacy response follows the existing peer-keyed queue behavior byte-for-byte.

`request_peer()` returns `None` on timeout, propagates `CancelledError`, rejects duplicate/closed admission with C2's stable internal exceptions, and removes/cancels only its identity-owned pending future in `finally`. `stop()` closes admission before cancelling/clearing outstanding pending futures. `start()` reopens admission.

Do not change `send_to_peer()`'s signature or swallow behavior. In particular, NATS publish failures remain indistinguishable from an unreachable peer to `request_peer()` and therefore become timeout/`federation_peer_timeout`, not an immediate unavailable result.

Do not change `send_to_peer()`, `receive_with_timeout()`, or legacy `deliver_response()` behavior/signatures. Do not switch federation to JetStream.

### DD-730-4-5 — Receiver branch is fail-closed and DM-only

At the top of `_handle_intent_request()` after the existing receive-stat increment:

- `delivery_mode` absent ⇒ execute the existing legacy body unchanged;
- `delivery_mode == "targeted_dm"` ⇒ call a new private `_handle_direct_message_request()` and return;
- any other present value ⇒ no local dispatch/resolver; return one `federation_delivery_mode_invalid` result only when the source is a configured peer.

Directed inbound validation order is binding:

1. exact `FederationMessage.type == "intent_request"`, exact built-in safe `source_node`, configured-peer membership, and non-self source;
2. C4-safe exact correlation `message_id`; malformed directed IDs are dropped because no safe response can be correlated;
3. exact built-in seven-key request payload, with no missing/unknown key;
4. exact `target_node_id == self._node_id`;
5. exact `intent == "direct_message"`;
6. exact safe stable target-agent ID;
7. exact safe original intent ID;
8. exact DD-730-4-2 wire TTL (`type` is built-in `int`/`float`, finite, `0 < ttl_seconds <= 60.0`);
9. exact built-in bounded params plus the DD-730-4-3/C4 text/ref/marker admission rule;
10. `intent_bus.has_subscriber(target_agent_id)`.

`FederationMessage.timestamp` is not an admission input. Do not reject a valid
directed request because its sender-local monotonic value appears old, future,
zero, or otherwise unrelated to the receiver's monotonic epoch. This is an
explicit no-age/no-replay posture, not a freshness guarantee.

Unknown/self/spoofed source is dropped without response, resolver, local delivery, or target-existence disclosure. A configured source with wrong target node, invalid intent, malformed target, malformed params, or absent target receives one structured error result and no resolver/local delivery. Caller-authored authority/provenance/session fields are never delivered; receiver-owned values from DD-730-4-3 are applied only after admission.

Do not inspect `AgentRegistry`, `CallsignRegistry`, `NodeSelfModel`, pool membership, capability descriptors, or agent type. The subscriber ID is the dispatch authority.

### DD-730-4-6 — Prefetch before the one target; never before admission/target existence

After all directed validation and subscriber-existence checks pass, reconstruct the targeted `IntentMessage`, including `target_agent_id`. Then invoke the already-injected BF-672 `attachment_resolver(intent.params, message.source_node)` before `IntentBus.send()`.

- Resolver `CancelledError` propagates and no target runs.
- Ordinary resolver failure logs a contextual warning and continues to the same one target, preserving BF-672's honest-degrade behavior (the agent may receive a failed-to-load marker).
- No refs / already-local refs cause zero HTTP calls through the existing resolver.
- Absent/malformed/wrong-node/spoofed requests perform zero attachment HTTP calls and zero store writes.

### DD-730-4-7 — Exact local delivery and zero fallback

Add this public, side-effect-free query to `IntentBus`:

```python
def has_subscriber(self, agent_id: str) -> bool:
    """Return whether an exact local subscriber is registered for agent_id."""
```

It is an exact `_subscribers` membership check. It does not inspect the intent index, queues, NATS subscriptions, registry, callsigns, or capabilities.

After prefetch, call `await self._intent_bus.send(intent)` exactly once. Never call `broadcast()` in the directed branch. Interpret outcomes:

- concrete `IntentResult` ⇒ serialize it;
- `None` after a positive precheck ⇒ `federation_target_declined`;
- `asyncio.TimeoutError` is already represented by `IntentBus.send()` as an error result;
- ordinary exception ⇒ log locally and return `federation_target_delivery_failed` without exception text on the wire;
- `CancelledError` ⇒ propagate, no synthetic response.

Never retry another subscriber. Never fall back to local broadcast, remote router selection, a callsign, pool peer, capability peer, or another node.

### DD-730-4-8 — Stable machine-code errors and result validation

Use the existing `IntentResult` dataclass. Do not introduce a new response type or event. Required error codes:

| Condition | `IntentResult.error` |
|---|---|
| malformed/self target node at origin | `federation_target_node_invalid` |
| configured target unavailable/not connected | `federation_target_node_unavailable` |
| malformed target agent at origin/receiver | `federation_target_agent_invalid` |
| directed intent is not `direct_message` | `federation_directed_intent_not_allowed` |
| params/result cannot strict-JSON serialize | `federation_payload_not_serializable` / `federation_result_not_serializable` |
| missing/oversize text with no retained ref, malformed ID, non-exact/non-finite/non-positive/over-60 wire TTL, or invalid directed payload shape | `federation_payload_invalid` |
| payload names another receiver node | `federation_target_node_mismatch` |
| exact target subscriber absent | `federation_target_not_found` |
| target returned `None` | `federation_target_declined` |
| target raised an ordinary exception | `federation_target_delivery_failed` |
| no response by timeout | `federation_peer_timeout` |
| malformed response / zero or multiple results | `federation_response_invalid` |
| returned result intent ID differs | `federation_result_correlation_mismatch` |
| returned result agent ID differs | `federation_result_target_mismatch` |
| existing remote-result validator returns false | `federation_result_validation_failed` |

Internal transport admission is not a wire error vocabulary: `federation_transport_closed` maps to `federation_target_node_unavailable`; `federation_request_key_in_use` and an invalid-correlation invariant map to `federation_target_delivery_failed`. A swallowed NATS publish failure or missing ZeroMQ dealer remains a timeout and maps to `federation_peer_timeout`.

Every synthetic result uses the original intent ID when it is a safe exact string, the requested stable target ID when safe (else empty), `success=False`, `result=None`, and `confidence=0.0`. The four newly introduced directed exception records follow C3 exactly: safe IDs/stable action plus `type(exc).__name__` only, never exception text/traceback, attachment bytes, bearer token, message text, full params, or result body.

At the origin, accept a remote result only if:

- response type is `intent_response`;
- response source equals the one named target node;
- response message ID is a C4-safe exact string and matched the transport pending key (a malformed directed response ID is dropped by C6 and therefore normally manifests as timeout);
- payload mode is `targeted_dm`;
- there is exactly one result;
- result `intent_id == intent.id`;
- result `agent_id == intent.target_agent_id`.

Before those correlation checks, require C5's exact six-key result schema, exact field types, finite confidence, and C1-bounded result. After all structural checks, if the bridge already has `_validate_fn`, apply
the same existing remote-result validation call used by legacy federation. A
`False` verdict becomes `federation_result_validation_failed`; validator
`CancelledError` propagates; an ordinary validator exception preserves the
legacy log-and-pass behavior. Production currently supplies a validator only
when `validate_remote_results` is enabled, and this does not activate dormant
trust/Hebbian handles. No mismatched or validation-rejected result reaches the
caller as a success.

### DD-730-4-9 — Router/gossip/trust behavior is intentionally unchanged

The directed method does not call `FederationRouter.select_peers()` because an explicit address is not a selection problem. It validates against the configured/connected peer set directly. It does not add agent IDs to `NodeSelfModel`, gossip a roster, use callsigns, or infer a destination from capability/trust/Hebbian weights.

Do not wire `trust_network`, `FederationHebbianMap`, or `FederationClusterMonitor` into production as part of this AD: those optional handles are currently dormant in `organize_fleet()`, and activating them would change legacy untargeted behavior. Configured-peer admission is the current raw-federation trust boundary. Record no trust outcome for malformed source/node/target, absent target, resolver failure, or local routing failure. If an existing optional bridge trust/result validator is already supplied by a direct construction, it may validate/record a concrete matching remote target result using the existing semantics only.

### DD-730-4-10 — Legacy untargeted federation is byte-identical

For every `IntentMessage` sent through existing `forward_intent()`:

- the same peers are selected in the same order;
- the same sanitizer runs once;
- the `FederationMessage` type/source/message ID/timestamp and payload keys/values are unchanged;
- no `delivery_mode`, `target_node_id`, or `target_agent_id` key appears;
- receiver still prefetches then calls `broadcast(intent, federated=False)`;
- local subscriber selection/fan-out and result list are unchanged;
- legacy response queues/timeouts remain peer-keyed and unchanged;
- stats, trust, validation, and loop behavior remain unchanged.

Add a hardcoded exact legacy envelope test and compare NATS JSON and ZeroMQ JSON bytes/dicts to the pre-AD shape. Do not “clean up” legacy serialization, error handling, response correlation, router wiring, or queue retention in this AD.

### DD-730-4-11 — Cancellation and ordinary errors

`CancelledError` propagates through bridge, resolver, target send, and `request_peer`; every request removes/cancels only its identity-owned pending response future in `finally`; no response/fallback is fabricated. Ordinary target/resolver/serialization/transport failures follow the stable result/log-and-degrade rules above and C3-safe logging. Tests must exercise cancellation at minimum while waiting for a response and while resolving attachments, plus ordinary resolver and target-handler exceptions.

### DD-730-4-12 — No new user-facing surface or discovery

This AD supplies the protocol/public bridge method and closes the transport/delivery gap proven by #634. It does not add a REST route, UI remote-recipient picker, slash command, cross-node chat-thread store, roster gossip, notification, episode schema, or sender-agent identity field. Those require separate consumers/governance decisions if demanded. The headline real-bridge test is the executable protocol consumer.

---

## Ordered implementation record

Sections marked Historical are completed audit history. Active correction work is governed by C1–C9 and the “Correction allowlist” above; any older generic JSON, cleanup, marker-classification, literal, pre-flight, or closeout wording is superseded.

### Section 0 — Event types

No new `EventType`. Do not edit `src/probos/events.py`.

### Historical Section 1 — Red-before tests (completed; do not rerun)

Create only `tests/test_ad730_4_directed_federated_vision_dm.py` before production edits. The first test must be the full two-node integration named:

`test_directed_vision_dm_two_organized_bridges_prefetches_and_targets_only`

It must fail against the exact base because `FederationBridge.forward_direct_message` does not exist. The fixture must use:

- one shared, started real `MockNATSBus`;
- two separate real `IntentBus(SignalManager())` instances;
- two bridges/transports produced by real `organize_fleet()` calls (do not construct `FederationBridge` in the headline test);
- two separate real `FilesystemAttachmentStore` roots on `tmp_path`;
- one real FastAPI/ASGI origin app mounting `federation_attachments.router`;
- one real `httpx.AsyncClient(ASGITransport(...))` used by the receiver resolver;
- exact `PeerConfig.node_id`/`A2APeerConfig.node_id` mapping;
- one deterministic-ID recording target agent and one deterministic-ID decoy agent, both real objects subscribed to the receiver's real bus for `direct_message`;
- canonical AD-731 vision blocks and no inline bytes;
- target assertions that the ref is present, receiver store already contains and returns the exact origin bytes, and only then a result is returned;
- decoy call count exactly zero;
- one ASGI fetch exactly;
- original nested params graph/value unchanged.

Run only this node and record its fail-before reason. No source edit before this red proof.

### Historical Section 2 — Exact local subscriber query (completed and frozen)

In `src/probos/mesh/intent.py`, add `has_subscriber()` beside `subscriber_count`. Do not expose `_subscribers`, add a registry dependency, or alter `send()`, `broadcast()`, intent indexing, NATS, queues, metrics, close semantics, or re-subscription behavior.

### Historical Section 3 — Correlated request seam in all three transports (correction active under C2/C4/C6)

Modify only:

- `src/probos/federation/nats_transport.py`;
- `src/probos/federation/transport.py`;
- `src/probos/federation/mock_transport.py`.

Correct the existing pending map/request implementation to DD-730-4-4 plus C2/C4/C6 behavior. Preserve current serializers and legacy response queues. Do not add a base class/protocol or edit `MockNATSBus`; the production and test transports already share a structural interface.

Required transport tests live in the new AD-730-4 test file:

- same-peer concurrent responses completing in reverse order correlate by message ID;
- timeout returns `None` and leaves no pending future;
- caller cancellation propagates and leaves no pending future;
- stop clears pending futures;
- duplicate same-key request rejects before send and cannot replace/cancel the owner;
- stop closes admission before cancellation, post-stop registration rejects, and start reopens;
- old stop/restart cleanup cannot remove a newer same-key owner;
- synchronous mock response is accepted because registration precedes send;
- late directed response does not enter the legacy peer queue;
- legacy response still enters and is read from the legacy queue;
- malformed directed response ID drops while malformed legacy response ID preserves peer-queue behavior;
- swallowed NATS publish failure follows timeout rather than immediate-unavailable semantics;
- NATS and ZeroMQ serializers remain semantically identical for the directed envelope;
- legacy serializer envelope remains exact.

Do not open real sockets. Exercise NATS through shared `MockNATSBus`; exercise ZeroMQ serialization using `object.__new__(FederationTransport)` as the existing AD-731a-1d parity test does.

### Historical Section 4 — Directed bridge outbound (correction active under C1/C3/C4/C5)

In `src/probos/federation/bridge.py`:

1. add private exact ID validators and one private synthetic-result helper;
2. keep strict JSON detach for bounded directed requests and add C1's iterative bounded result validator/detacher;
3. add `forward_direct_message()` exactly per DD-730-4-1/2/3/8;
4. call `transport.request_peer()` once;
5. validate the exact response/result envelope and C5 field types/finite confidence before returning or invoking the optional validator;
6. preserve cancellation and stable ordinary-error results;
7. never call the router or local bus from the outbound method.

Do not alter `forward_intent()` except, if unavoidable, a comment that explicitly states it remains the legacy untargeted path. Any executable diff inside its body is a hard stop unless required to reuse the existing sanitizer without changing output; prefer a private helper called by the new method only.

### Historical Section 5 — Directed bridge inbound (correction active under C1/C3/C4/C5)

In the same file, add the minimal mode branch and private directed handler per DD-730-4-5/6/7/8. Keep the existing legacy body text/order intact below the branch.

Validation precedes resolver. Subscriber-existence precedes resolver. Resolver precedes `send()`. `send()` occurs once. Response occurs once except unknown/self source (drop) and cancellation (propagate). No broadcast/fallback.

### Historical Section 6 — Original behavioral suite (retain; C1–C6 cases already added, now add C7–C9)

The new test module must include explicit named coverage for at least these behaviors:

1. `test_directed_vision_dm_two_organized_bridges_prefetches_and_targets_only`
2. `test_directed_text_dm_targets_only_and_performs_zero_fetches`
3. `test_absent_target_returns_one_correlated_not_found_result_without_prefetch`
4. `test_callsign_is_not_resolved_as_remote_agent_id`
5. `test_malformed_target_agent_id_fails_before_network`
6. `test_unconfigured_target_node_fails_before_network`
7. `test_self_target_node_fails_before_network`
8. `test_inbound_wrong_target_node_returns_mismatch_without_delivery_or_prefetch`
9. `test_inbound_unconfigured_spoofed_source_is_dropped_without_response`
10. `test_inbound_self_spoofed_source_is_dropped_without_response`
11. `test_non_direct_message_targeted_envelope_is_rejected_without_send`
12. `test_malformed_directed_params_never_fall_back_to_broadcast`
13. `test_origin_rejects_nonfinite_or_nonpositive_ttl_before_network`
14. `test_origin_caps_ttl_at_sixty_for_wire_and_request_wait`
15. `test_receiver_rejects_nonfinite_nonpositive_or_over_cap_ttl_before_prefetch_or_send`
16. `test_receiver_does_not_compare_sender_monotonic_timestamp_and_starts_local_intent_lifetime`
17. `test_receiver_replaces_spoofed_authority_and_session_fields_with_server_owned_provenance`
18. `test_directed_wire_drops_private_session_history_context_and_unknown_params`
19. `test_target_handler_exception_returns_delivery_failed_and_decoy_is_untouched`
20. `test_target_handler_cancellation_propagates_without_response_or_fallback`
21. `test_resolver_exception_still_delivers_only_to_target`
22. `test_resolver_cancellation_propagates_before_target_delivery`
23. `test_concurrent_same_peer_responses_correlate_by_message_id`
24. `test_response_intent_id_mismatch_is_rejected`
25. `test_response_agent_id_mismatch_is_rejected`
26. `test_zero_or_multiple_results_are_protocol_invalid`
27. `test_existing_remote_result_validator_can_reject_directed_result`
28. `test_request_timeout_returns_correlated_peer_timeout`
29. `test_request_cancellation_cleans_pending_future`
30. `test_late_directed_response_does_not_poison_legacy_queue`
31. `test_nats_and_zmq_directed_serializer_parity`
32. `test_directed_wire_contains_only_sha_refs_and_no_inline_binary_forms`
33. `test_directed_request_and_response_are_deeply_detached_from_callers`
34. `test_original_nested_params_unchanged_on_success_error_and_cancellation`
35. `test_legacy_untargeted_federation_envelope_is_exact_and_has_no_directed_fields`
36. `test_legacy_untargeted_direct_message_still_broadcasts_to_all_matching_local_agents`
37. `test_intent_bus_has_subscriber_is_exact_and_index_independent`
38. `test_new_public_signatures_are_exact_and_forward_direct_message_accepts_positional_call`

Retain all **211 currently collected cases** (85 before C1–C6, 211 before C7–C9) and add every correction test in C7–C9. The final count is observed, not guessed. Safe-log tests cover all four new exception boundaries. Stress tests prove C1 bounded work by construction/AST plus real oversized built-in containers; do not use timing alone. Do not claim C8's open legacy top-level classifier is constant-bounded.

Use parametrization for malformed IDs/inline forms, but every behavior must be explicit in node name or case ID. Tests must avoid `MagicMock` at bus, bridge, store, config, agent, and transport boundaries. Small recording fakes are permitted only for target behavior or injected clocks/events; the headline uses real objects listed above.

TTL case IDs must include at least `bool`, string, numeric subclass/non-built-in
numeric, zero, negative, NaN, positive/negative infinity, an oversized built-in
integer whose float conversion raises `OverflowError`, receiver `60.0001`,
origin `120 -> 60`, and a tiny positive TTL whose `timeout_ms` is clamped to 1.
Every rejected receiver case proves zero resolver and zero target calls.

### Historical Section 7 — Conditional trackers, issue closeout, and prompt archival

Only after all exact gates and three-pass review are green:

1. prepend one concise `AD-730-4 shipped` block to `PROGRESS.md`, naming #634, the exact `(node_id, agent_id)` protocol, DM-only scope, SHA-only/prefetch-before-target invariant, no-fanout errors, exact gate counts, and unchanged AD-1122/BF-672 ceilings;
2. prepend `### AD-730-4 (2026-07-16) — directed federated vision DMs (#634)` under Era V in `DECISIONS.md`, with Context / Decision / Tests. Explicitly state configured-peer admission is not cryptographic authentication and generic arbitrary-intent addressing is not built;
3. add/mark the AD-730-4 row in the Wave 151/152 vision table in `docs/development/roadmap.md` as shipped/closed via directed DM-only addressing + AD-731a Option B; do not add commercial/pricing text;
4. move both prompt docs to `prompts/archive/` as the final pre-commit file operation. Do not edit their contents during Builder execution;
5. final commit subject exactly:

`AD-730-4: add directed federated vision DMs (closes #634)`

Do not post the ignored issue-update draft. The commit trailer closes #634 when the Captain pushes.

---

## Exact file allowlist

### Production — eventual AD final diff

- `src/probos/federation/bridge.py`
- `src/probos/federation/nats_transport.py`
- `src/probos/federation/transport.py`
- `src/probos/federation/mock_transport.py`
- `src/probos/mesh/intent.py`

### Active correction production allowlist

- `src/probos/federation/bridge.py`
- `src/probos/federation/nats_transport.py`
- `src/probos/federation/transport.py`
- `src/probos/federation/mock_transport.py`

`src/probos/mesh/intent.py` is already modified in the live AD diff and remains authorized in the eventual commit, but its accepted `has_subscriber()` implementation is frozen during correction.

### Tests — eventual AD file; continue editing during correction

- `tests/test_ad730_4_directed_federated_vision_dm.py` **(NEW)**

No existing test file should need modification. If one does, stop and report the obsolete/conflicting contract before changing it.

### Conditional closeout after all gates

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- move (not rewrite) `prompts/ad-730-4-directed-federated-vision-dm.md` → `prompts/archive/ad-730-4-directed-federated-vision-dm.md`
- move (not rewrite) `prompts/ad-730-4-directed-federated-vision-dm-execution.md` → `prompts/archive/ad-730-4-directed-federated-vision-dm-execution.md`

### Reference-only / forbidden

- `src/probos/types.py`
- `src/probos/runtime.py`
- `src/probos/config.py`
- `src/probos/startup/fleet_organization.py`
- `src/probos/substrate/registry.py`
- `src/probos/substrate/identity.py`
- `src/probos/agent_onboarding.py`
- `src/probos/federation/attachment_resolve.py`
- `src/probos/federation/attachment_fetch.py`
- `src/probos/routers/federation_attachments.py`
- `src/probos/routers/agents.py`
- `src/probos/cognitive/cognitive_agent.py`
- `src/probos/mesh/nats_bus.py`
- `config/system.yaml` and all config
- all dependency manifests/locks, UI/desktop, workflows, era archives, data, and logs

The ignored `logs/ad730_4_issue_update.md` is Architect research output only. It may be revised only by the Architect, must remain ignored, and must not be staged.

---

## Exact original baselines and unchanged gates

All baseline runs were executed on exact HEAD with a unique temporary `PROBOS_DATA_DIR`, local embeddings, Hugging Face/Transformers offline, no pytest cache, serial `-n 0`, per-test timeout 90 seconds, and `RuntimeWarning` promoted to error.

The earlier correction baseline was **85 tests collected** before C1–C6. The latest live module collects **211 tests** before C7–C9. Do not rerun the original red gate: production and tests already exist in the live uncommitted diff. Gates 1–4 below remain byte-for-byte unchanged and are the only execution gates after correction.

| Baseline | Existing files | Result |
|---|---|---:|
| Directed/federation/attachment focused | `test_federation.py`, `test_federation_nats.py`, `test_targeted_dispatch.py`, AD-731a-1d/1c/remote | **148 passed in 55.95s** |
| Local serializer/target/lifecycle | `test_intent.py`, federation/NATS, targeted dispatch, AD-637z, AD-654a/b, BF-296 close | **188 passed in 55.67s** |
| Vision/reference chain | AD-731a-1d/1c/remote, AD-731 wire, BF-265, AD-730, AD-720d, BF-266 | **141 passed in 5.24s** |
| Governance/runtime/lifecycle | AD-479, AD-480, AD-443, runtime, AD-447, BF-296 shutdown, BF-598 | **243 passed with 2 dependency deprecation warnings in 205.68s** |

Exact pre-build per-file inventory:

- `tests/test_federation.py` 42
- `tests/test_federation_nats.py` 11
- `tests/test_targeted_dispatch.py` 5
- `tests/test_intent.py` 56
- `tests/test_ad731a_1d_reference_only_federation_send.py` 51
- `tests/test_ad731a_1c_auto_resolve.py` 26
- `tests/test_ad731a_remote_attachment.py` 13
- `tests/test_ad730_agent_chat_vision.py` 12
- `tests/test_ad731_attachment_ref_wire_format.py` 12
- `tests/test_bf265_transport_stripped_params.py` 9
- `tests/test_ad637z_nats_cleanup.py` 13
- `tests/test_ad654a_async_dispatch.py` 29
- `tests/test_ad654b_cognitive_queue.py` 25
- `tests/test_bf296_intent_bus_close.py` 7
- `tests/test_ad479_federation_hardening.py` 62
- `tests/test_ad480_federation_mcp_a2a.py` 73
- `tests/test_ad443_mobility.py` 57
- `tests/test_runtime.py` 29
- `tests/test_ad447_phase_gates_pool_group.py` 8
- `tests/test_bf296_shutdown_phase_ordering.py` 5
- `tests/test_bf598_shutdown_idempotency.py` 9

### Historical red gate — already completed; do not rerun during correction

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_red_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py::test_directed_vision_dm_two_organized_bridges_prefetches_and_targets_only -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Expected pre-production result: fail because `FederationBridge.forward_direct_message` is absent. Record, do not weaken.

### Gate 1 — new AD-730-4 module + focused current contracts

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_federation.py tests/test_federation_nats.py tests/test_targeted_dispatch.py tests/test_ad731a_1d_reference_only_federation_send.py tests/test_ad731a_1c_auto_resolve.py tests/test_ad731a_remote_attachment.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing baseline contribution: **148** plus the exact observed new-module collection count.

### Gate 2 — serializer, targeted delivery, queue, and close parity

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_transport_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_intent.py tests/test_federation.py tests/test_federation_nats.py tests/test_targeted_dispatch.py tests/test_ad637z_nats_cleanup.py tests/test_ad654a_async_dispatch.py tests/test_ad654b_cognitive_queue.py tests/test_bf296_intent_bus_close.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing baseline contribution: **188** plus the new module.

### Gate 3 — reference-only vision chain

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_vision_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_ad731a_1d_reference_only_federation_send.py tests/test_ad731a_1c_auto_resolve.py tests/test_ad731a_remote_attachment.py tests/test_ad731_attachment_ref_wire_format.py tests/test_bf265_transport_stripped_params.py tests/test_ad730_agent_chat_vision.py tests/test_ad720d_vision_pipethrough.py tests/test_bf266_vision_context_folding.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing baseline contribution: **141** plus the new module.

### Gate 4 — federation governance/runtime/lifecycle blast

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad7304_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad730_4_directed_federated_vision_dm.py tests/test_ad479_federation_hardening.py tests/test_ad480_federation_mcp_a2a.py tests/test_ad443_mobility.py tests/test_runtime.py tests/test_ad447_phase_gates_pool_group.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Existing baseline contribution: **243** plus the new module. The two known third-party deprecation warnings are not `RuntimeWarning` and were present at baseline; report them exactly if they recur.

Do not run `-n auto`, live NATS/ZeroMQ sockets, a live model, or the live data directory. No UI gate is required.

---

## Acceptance criteria

1. The exact base/origin remain `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa` until the authorized implementation commit, and correction resumes from the exact eight-path live status pinned above (the ignored log does not appear in status).
2. Issue #634 remains open and uniquely reserves AD-730-4 before build; AD-1122/BF-672 remain the ceilings.
3. Origin node addressing is exact `PeerConfig.node_id`; target addressing is exact stable `IntentMessage.target_agent_id`; no callsign or roster inference occurs.
4. Current local `IntentMessage`/IntentBus serialization remains unchanged; no `target_node_id` field is added to `IntentMessage`.
5. Directed outbound sends one message to one configured/connected non-self node and bypasses router selection without changing router behavior.
6. Directed inbound validates source/node/intent/params/target, proves exact subscriber existence, prefetched missing refs through BF-672, then calls `IntentBus.send()` once.
7. Target sees canonical refs and exact prefetched bytes before its handler; decoy sees nothing. The headline test uses two real `organize_fleet()` bridges, one shared `MockNATSBus`, real separate stores, and real ASGI serve/fetch.
8. Absent target returns exactly one correlated `IntentResult(error="federation_target_not_found")`; no prefetch, local fan-out, alternative, callsign resolution, or roster disclosure occurs.
9. Text-only targeted DM uses the same addressed path with zero attachment HTTP calls.
10. Unknown/self source is dropped without response; wrong target node, malformed target, malformed params, and non-DM directed intent produce stable fail-closed behavior with no delivery/fetch.
11. Origin TTL accepts only exact built-in finite positive numerics, caps the emitted/request-wait budget at 60 seconds, and receiver TTL accepts only exact built-in finite values in `(0, 60]` before fetch/send. Receiver reconstruction starts a local `IntentMessage.created_at`; `IntentBus.send()` uses TTL as a fresh local timeout and does not enforce message age.
12. The directed wire carries only bounded text plus canonical attachment refs; private session history, caller context/urgency, local-authority and qualification flags, project/recall/tool state, and unknown params are dropped. Receiver-owned federation provenance replaces spoofed `from`/authority/session fields and leaves the generic action-episode safety net eligible.
13. `FederationMessage.timestamp` remains sender-local monotonic metadata and is never compared with a receiver clock. No receiver age/replay claim is made; exact safe `(peer_node_id, FederationMessage.message_id)` correlation supports concurrent same-peer calls, rejects duplicate owners, closes admission before stop cancellation, reopens on start, cleans by identity, and prevents late-response queue poisoning only—it is not inbound replay protection.
14. Directed requests use an exact seven-key payload and safe 1–128-character correlation ID; directed responses use an exact two-key envelope and exact six-key typed result. Result intent/agent mismatches, malformed types/nonfinite confidence, zero/multiple results, malformed envelopes, validation rejection, and non-serializable results never reach the caller as success.
15. The wire and responses contain no Python binary object, inline base64 image block, response string beginning (after leading ASCII whitespace) with case-insensitive `data:image/` in a scalar, exact dict key, or `error`, image URL object, raw PNG/JPEG bytes, nonfinite number, cycle, hostile subclass, or attachment bearer token. C1 bounds result work to depth 16, 4,096 nodes, 65,536 characters per string, 262,144 cumulative UTF-8 response-string bytes, and a 262,144-byte compact response. Canonical lowercase 64-hex refs are the only image payload authority; ordinary prose and ordinary `data` objects remain valid.
16. Request and response payloads are deeply detached; receiver/caller mutation cannot mutate the origin intent/target result. Original nested params remain unchanged on success, ordinary error, timeout, and cancellation.
17. `CancelledError` propagates at request wait, resolver, validator, and local target boundaries; ordinary failures use C3-safe logs containing only safe IDs, stable action, and `type(exc).__name__`; no exception message/traceback/secret/blob is logged; pending futures are always cleaned by owner.
18. Legacy `forward_intent()` and inbound untargeted broadcast behavior, exact envelope, selected peers, local fan-out, loop prevention, serializer bytes, response queues, stats, validation, trust behavior, and the exact UTF-8 validator warning literal `Federation message validator failed — message passed without validation` remain byte-identical.
19. No generic arbitrary-intent addressed federation, REST/UI/discovery/thread-sync/roster-gossip/signature/CURVE/NATS-account-auth work is introduced.
20. No new config, event, agent, pool, DB/store, dependency, background task, JetStream stream, or persistence is introduced.
21. All four exact unchanged gates pass and exact observed counts/durations/final new-module collection are recorded; no existing test edit or skip is needed.
22. Trackers close #634 only after green gates; roadmap receives the technical OSS row; both prompt docs are moved unchanged to archive; ignored issue-update draft remains untracked.
23. Final commit subject is exactly `AD-730-4: add directed federated vision DMs (closes #634)`.
24. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## What this does NOT change / Do Not Build

- Do not add arbitrary remote targeting for `write_file`, `run_command`, `http_fetch`, tool invocation, device actuation, work assignment, or any intent other than `direct_message`.
- Do not modify `IntentMessage`, `IntentResult`, `NodeSelfModel`, `BaseAgent`, `AgentRegistry`, `CallsignRegistry`, identity certificates, or agent onboarding.
- Do not advertise agent IDs/callsigns/DIDs through gossip or add a remote-agent directory.
- Do not accept callsigns, vessel names, display names, agent types, DIDs, sovereign UUIDs, or pool names as target aliases.
- Do not change the 1:1 REST/UI flow or add a remote-recipient picker, API route, slash command, HXI panel, notification, or chat-thread synchronization.
- Do not transport raw bytes, base64, data URLs, image URLs, multipart bodies, attachment-store paths, or binary frames through NATS/ZeroMQ.
- Do not add NATS Object Store/JetStream replication. AD-731a Option B authenticated pull is the chosen correctness path; replication remains availability-only.
- Do not modify the authenticated serve/fetch helpers, their token behavior, SHA/MIME/size checks, or A2A peer mapping.
- Do not wire dormant AD-479 trust/Hebbian/cluster handles into production or change legacy router selection.
- Do not claim configured-peer admission is cryptographic authentication. Do not add signatures, keys, CURVE, NATS credentials/accounts, TLS hot rotation, or OAuth.
- Do not compare `FederationMessage.timestamp` or `NodeSelfModel.timestamp` with a receiver clock for this path. Do not add an unauthenticated wall-clock field, nonce/replay store, request-age claim, or replay-protection claim; those require a separate authenticated-envelope AD.
- Do not change legacy peer-keyed response behavior except the exact late-directed-response non-poisoning guard.
- Do not switch federation to JetStream or durable delivery.
- Do not add retries/fallbacks to another node/agent. Do not broadcast after any directed error.
- Do not add a feature flag: the new method is inert until explicitly invoked and federation remains globally default-off.
- Do not modify config/system.yaml, dependencies, UI, desktop, workflows, era files, commercial files, pricing, or competitive material.
- Do not create a new top-level AD or BF; this is the pre-reserved AD-730-4 only.

---

## Hard stops

Stop and return to the Architect if:

1. HEAD/origin differs from the exact base, staged paths exist, or the correction-start visible tree differs from the exact eight-path live status above.
2. #634 is no longer open/uniquely reserved, or the AD/BF ceilings changed.
3. Correctness requires modifying `IntentMessage`, `BaseAgent`, `AgentRegistry`, `NodeSelfModel`, runtime/startup wiring, config, authenticated attachment helpers, or any path outside the allowlist.
4. A target cannot be delivered through exact `IntentBus.send()` without callsign/registry/pool fallback.
5. Exact owner-safe response correlation cannot be implemented inside the three transport classes without changing legacy `send_to_peer()` or `receive_with_timeout()` signatures/semantics.
6. The headline test cannot use two real `organize_fleet()` bridges, shared real `MockNATSBus`, real buses/stores/ASGI route, and target+decoy objects.
7. Any binary/inline image form appears in serialized directed request/response data; C1/C7 cannot bound result-string work without corrupting legitimate text/object results; or C8 invokes an untrusted payload/key/value override. C8's honest $O(n)$ exact-dict top-level scan alone is not a hard stop.
8. A needed existing test assertion change is not anticipated by this prompt.
9. Any gate fails in an existing file and reproduces serially; do not broaden scope or weaken tests.
10. A deletion, bulk reformat, dependency/config/UI/tracker-before-green, or commercial-boundary leak appears.
11. Either active prompt doc changes again during Builder correction before its final unchanged archive move.
12. Any implementation or test compares sender `FederationMessage.timestamp` with receiver time, emits `federation_request_expired`, or describes response correlation/TTL as request-age or replay protection.
13. A fix changes legacy send signatures to surface NATS/ZeroMQ availability, routes malformed legacy response IDs away from their peer queue, or performs pending lookup on malformed IDs.
14. Any of the four directed exception boundaries logs an exception message, traceback, params, result, text, token, URL, or blob.
15. The exact legacy validator warning literal differs from the HEAD AST constant or its UTF-8 em dash is mojibake.

---

## Three-pass Builder self-review

### Pass 1 — Behavior/protocol

Map each DD and acceptance criterion to a named test. Walk valid vision, valid text, absent target, malformed target, wrong node, unknown/self source, invalid/capped TTL, unrelated sender monotonic epochs, private/authority/session-field stripping, non-DM, resolver error/cancel, target error/cancel, timeout, mismatched/validator-rejected result, C7 scalar/key/error/long-subtype rejection, concurrent correlation, and late response manually. Confirm only C8's exact built-in targeted marker drops, malformed markers preserve legacy queueing, no branch can fall into legacy broadcast after an exact directed mode marker, no rejected branch reaches the resolver/target, and no code compares the sender's monotonic timestamp with receiver time or claims replay defense.

### Pass 2 — Verify-first/code

Re-grep every changed symbol/caller. Confirm `forward_intent()` executable body is unchanged except restoration of C9's exact base literal; the new bridge method calls exactly one `request_peer`; directed inbound calls exactly one resolver and one `send`; `has_subscriber` stayed unchanged during correction; all pending maps enforce unique owner/closed admission/identity cleanup; all three marker classifiers use exact dict + unbound `dict.items` and invoke zero hostile overrides; NATS/ZeroMQ serializers are parity-equal; exact schemas and C1/C7 bounds dominate result traversal/serialization; no raw bytes/base64 survive; no private cross-module reach-through or new task exists.

### Pass 3 — Scope/privacy/license

Confirm exact correction allowlist, C3-safe type-only logs, no content/token/body/traceback logging, no callsign/roster leak, no trust overclaim, no dependency/config/UI/commercial content, no deletion, no whitespace diagnostics, license none, and revised prompt hashes unchanged before archive move.

---

## Verified Against Codebase (2026-07-16, exact HEAD `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa`)

```text
REPOSITORY / ISSUE / NUMBERING
git status --short
  <empty before Architect docs>
git rev-parse HEAD
  9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa
git rev-parse origin/main
  9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa
gh issue view 634
  OPEN — AD-730-4: Federation peer-to-peer vision DMs
gh issue view 638
  CLOSED — AD-731a attachment distribution
AD/BF maximum in PROGRESS.md + DECISIONS.md
  AD-1122 / BF-672
git log --all --grep AD-730-4
  no implementation commit; only parent AD-730 mentions the marker
DECISIONS.md:4769
  AD-730-4: federation peer-to-peer vision DMs — inherits AD-480 governance review

MESSAGE / LOCAL TARGETING
src/probos/types.py:58
  class IntentMessage
src/probos/types.py:68
  target_agent_id: str | None = None
src/probos/types.py:65-67
  ttl_seconds defaults to 60.0; created_at defaults to receiver-local UTC now
src/probos/types.py:78
  class IntentResult
src/probos/mesh/intent.py:558
  async def send(self, intent: IntentMessage) -> IntentResult | None
src/probos/mesh/intent.py:588
  handler = self._subscribers.get(intent.target_agent_id)
src/probos/mesh/intent.py:634/647/663
  broadcast documents and delegates targeted messages to send
src/probos/mesh/intent.py:1096/1117
  local serializer includes target_agent_id
src/probos/mesh/intent.py:1121/1136
  local deserializer restores target_agent_id

INTENT TTL / CREATION SEMANTICS
src/probos/types.py:58-75
  IntentMessage has ttl_seconds and created_at fields but no is_expired method
src/probos/mesh/intent.py:558-618
  send requires a target and uses ttl_seconds only as direct-handler/NATS wait timeout; it does not inspect created_at or SignalManager
src/probos/mesh/intent.py:634-681
  broadcast tracks the signal and uses ttl_seconds as its wait timeout; targeted broadcast delegates to send before signal tracking
src/probos/mesh/signal.py:33-47 / 77-84
  SignalManager track/is_alive/reap compare local UTC now with IntentMessage.created_at; this is not invoked by direct send
src/probos/mesh/intent.py:1103-1137
  local NATS serialization carries created_at, but federation bridge payload does not

FEDERATION TIMESTAMP SEMANTICS
src/probos/types.py:926-934
  FederationMessage.timestamp is an untyped-semantics float with default 0.0
src/probos/federation/bridge.py:301-312 / 375-379 / 436-441 / 464-643
  every production bridge-created federation envelope uses time.monotonic()
src/probos/federation/transport.py:184-203
  ZeroMQ transport only serializes/deserializes FederationMessage.timestamp
src/probos/federation/nats_transport.py:180-197
  NATS transport only serializes/deserializes FederationMessage.timestamp
src/probos/federation/bridge.py:358-389
  handle_inbound dispatches by type and never interprets FederationMessage.timestamp
src/probos/federation/bridge.py:445-456 / src/probos/federation/cluster_monitor.py:90-101
  separate NodeSelfModel payload timestamp is consumed by existing gossip liveness code; AD-730-4 must not reuse that cross-host comparison

FEDERATION GAP
src/probos/federation/bridge.py:284
  async def forward_intent(self, intent: IntentMessage) -> list[IntentResult]
src/probos/federation/bridge.py:289
  router.select_peers(intent.intent, transport.connected_peers)
src/probos/federation/bridge.py:304-312
  current payload omits target_node_id and target_agent_id
src/probos/federation/bridge.py:391
  async def _handle_intent_request
src/probos/federation/bridge.py:396-404
  inbound IntentMessage reconstruction has no target
src/probos/federation/bridge.py:411
  BF-672 resolver runs before local delivery
src/probos/federation/bridge.py:422
  local_results = await self._intent_bus.broadcast(intent, federated=False)
src/probos/federation/bridge.py:439-440
  response reuses request message_id and payload.results

ROUTER / GOSSIP
src/probos/federation/router.py:36
  update_peer_model
src/probos/federation/router.py:40
  select_peers
src/probos/federation/router.py:91
  peer_has_capability
src/probos/types.py:848-860
  NodeSelfModel carries node/capabilities/pool sizes/count/health/uptime/timestamp, no roster
src/probos/runtime.py:4655
  _build_self_model builds that node-only capability summary

STABLE LOCAL IDS / DIRECT MESSAGE
src/probos/substrate/identity.py:17-37
  generate_agent_id is deterministic from agent_type/pool/index
src/probos/substrate/registry.py:58
  AgentRegistry.get exact agent id
src/probos/agent_onboarding.py:172
  IntentBus subscription key is agent.id
src/probos/agent_onboarding.py:381-391
  identity registry resolves sovereign provenance, but agent.sovereign_id is separate from subscriber key
src/probos/routers/agents.py:2485
  agent_chat route
src/probos/routers/agents.py:3093-3094
  vision_messages added to params
src/probos/routers/agents.py:3108
  target_agent_id=agent_id
src/probos/cognitive/cognitive_agent.py:3363
  vision_messages consumed
src/probos/cognitive/cognitive_agent.py:5643/5653
  targeted direct_message to self.id is accepted

ATTACHMENT OPTION B
src/probos/federation/attachment_resolve.py:38
  extract_attachment_shas
src/probos/federation/attachment_resolve.py:86
  source_node -> configured A2A peer mapping
src/probos/federation/attachment_resolve.py:103
  resolve_missing_attachments
src/probos/federation/attachment_fetch.py:24
  fetch_remote_attachment verifies and stores
src/probos/routers/federation_attachments.py:54
  authenticated serving route
src/probos/federation/bridge.py:20-27
  existing 8 / 64 / 64 federation attachment bounds
DECISIONS.md:13-19 / PROGRESS.md:3
  AD-731a-1d + BF-672 shipped; AD-1122/BF-672 ceilings retained

TRANSPORTS
src/probos/federation/nats_transport.py:37-40
  per-node raw NATS subject design
src/probos/federation/nats_transport.py:73
  configured connected_peers
src/probos/federation/nats_transport.py:114/119
  send_to_peer publishes once to federation.intent.{peer}
src/probos/federation/nats_transport.py:133
  peer-keyed receive_with_timeout
src/probos/federation/nats_transport.py:180/190
  FederationMessage serializer/deserializer
src/probos/federation/transport.py:67
  configured ZeroMQ DEALER peers
src/probos/federation/transport.py:83
  DEALER identity is local node_id
src/probos/federation/transport.py:111
  send_to_peer selects one DEALER
src/probos/federation/transport.py:132
  peer-keyed receive_with_timeout
src/probos/federation/transport.py:184/195
  JSON bytes serializer/deserializer
src/probos/federation/mock_transport.py:21/54
  in-memory federation test transport pair
src/probos/mesh/nats_bus.py:1235/1251
  shared MockNATSBus raw publish/subscribe

PRODUCTION COMPOSITION
src/probos/runtime.py:1958
  attachment_resolver_fn=self._resolve_federated_attachments
src/probos/startup/fleet_organization.py:159/170
  configured peer IDs feed NATS transport
src/probos/startup/fleet_organization.py:205
  router = FederationRouter()
src/probos/startup/fleet_organization.py:211-219
  bridge construction with narrow attachment resolver
src/probos/startup/fleet_organization.py:223
  only legacy bridge.forward_intent is registered on IntentBus

NEW SYMBOL / KEY COLLISION CHECK
production grep for targeted_dm / forward_direct_message / request_peer /
has_subscriber / federation_source_node / literal federation:<
  zero hits at the exact base; all are introduced by this prompt

SECURITY BOUNDARY
src/probos/identity.py:10-14
  identity proof is a content hash, not a cryptographic signature; future Ed25519 when federation requires it
src/probos/config.py:3003-3009
  federation TLS surface; ZeroMQ CURVE remains deferred
src/probos/config.py:3045-3088
  federation default off, static peers, min trust default 0
src/probos/startup/fleet_organization.py:205
  production router currently constructed without trust/Hebbian/cluster handles

BASELINES
focused federation/attachment: 148 passed in 55.95s
serializer/target/lifecycle: 188 passed in 55.67s
vision/reference chain: 141 passed in 5.24s
governance/runtime/lifecycle: 243 passed, 2 dependency deprecation warnings, in 205.68s
```

---

## Final Architect three-pass review (2026-07-16; superseded on temporal semantics by the 2026-07-17 re-review below)

- **Pass 1 — protocol/behavior:** APPROVED. Exact node+agent addressing, DM-only authorization, error shape, correlation, prefetch ordering, cancellation, no-fallback, privacy, and legacy invariants are pinned and test-mapped.
- **Pass 2 — verify-first:** APPROVED. Every asserted field/signature/path was read at exact HEAD. Post-build entities are identified as prompt-introduced, not pre-build phantoms.
- **Pass 3 — scope/boundary:** APPROVED. Five production files, one new test, three conditional trackers, two unchanged archive moves; no config/UI/dependency/commercial expansion. License none.

**Builder approval: APPROVED / EXECUTABLE on the exact base.**

---

## Protocol-contradiction re-review (2026-07-17)

**Verdict: APPROVED / EXECUTABLE after required correction.**

### Required — resolved

1. Removed every receiver comparison between sender-local `FederationMessage.timestamp=time.monotonic()` and receiver-local time.
2. Removed `federation_request_expired` and all stale/future/same-boot/replay-protection claims from the directed protocol, error matrix, tests, acceptance criteria, and Builder handoff.
3. Pinned exact TTL semantics: origin validates finite positive built-in numerics and caps at 60; receiver validates exact wire TTL in `(0, 60]`; TTL bounds origin wait and receiver-local handling only.
4. Documented the live `IntentBus.send()` contract: it starts a fresh timeout, does not inspect `created_at`, and bypasses `SignalManager`; receiver reconstruction starts local `created_at`.
5. Explicitly deferred request-age and replay protection until an authenticated wall-clock/nonce envelope plus bounded replay state exists. No unauthenticated wall-clock field was added.

### Verified

- All production `FederationBridge` envelope producers use sender-local `time.monotonic()`.
- NATS and ZeroMQ transports preserve but do not interpret the envelope timestamp.
- `FederationBridge.handle_inbound()` does not currently consume the envelope timestamp.
- Exact response correlation prevents outstanding-request cross-talk and late-response queue poisoning only; it does not suppress inbound request replay.
- Every other approved DD, file allowlist, test gate, scope boundary, and the exact Engineering Principles acceptance line remains intact.

**Builder approval: APPROVED / EXECUTABLE on exact base `9053edd7eb1b8e9ec79c20fee5385b71a4ce81fa`.**

---

## Historical re-review — C1–C6 BLOCKED implementation correction (superseded for handoff by C7–C9 below; 2026-07-17)

**Verdict:** ✅ **RE-APPROVED / CORRECTION EXECUTABLE**

**All six implementation findings are now pinned without changing the DM-only architecture, legacy send signatures, or `IntentBus.has_subscriber()`.**

### Required — resolved

1. Directed results now have an iterative exact-built-in policy with depth 16, 4,096 nodes, 65,536 characters per string, 262,144 cumulative string bytes, and 262,144 compact response bytes. Binary, nonfinite, cyclic, hostile-subclass, actual image data URL, `image_url`, and base64-source/data shapes reject as `federation_result_not_serializable`; ordinary prose and `data` objects remain valid.
2. All transports now require unique pending-key ownership, identity-conditional cleanup, registration-before-send, stop-close-before-cancel, post-stop rejection, and start reopen. Bridge stop/start admission and exact error mapping are pinned.
3. The four new ordinary-exception boundaries log only safe IDs, stable action, and `type(exc).__name__`; no exception message, traceback, params, result, DM text, token, URL, or blob.
4. Directed requests are exact seven-key payloads; responses are exact two-key envelopes; correlation IDs are exact built-in strings matching `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`; `_transport_stripped` is a bounded canonical ordered unique subset of four producer names.
5. Serialized results are exact six-key typed records. `success` is exact bool, `error` is bounded string/None, and confidence is exact built-in finite numeric before `IntentResult` construction and validator invocation.
6. Malformed directed response IDs drop; pending lookup never receives malformed IDs; malformed legacy response IDs preserve the old peer queue behavior.

### Contradiction resolved

`NATSFederationTransport.send_to_peer()` already swallows publish exceptions and returns `None`. AD-730-4 does not change that legacy signature/behavior. Consequently `request_peer()` cannot distinguish publish failure or peer silence: it waits to timeout and the bridge returns `federation_peer_timeout`. Immediate `federation_target_node_unavailable` is reserved for preflight disconnected/configured-state failure, bridge stopped, or the transport admission gate being closed.

### Verified against the live uncommitted implementation

- `bridge.py` currently applies unbounded `_strict_json_detach(raw_result)` and open `.get()` field reads; C1/C5 directly replace that shape.
- All three transports currently overwrite `_pending_requests[key]`, unconditionally pop by key, and allow post-stop registration; C2 directly closes those races.
- The four directed bridge catches currently use `exc_info=True`; C3 replaces only those new records.
- Current inbound code accepts unknown top-level directed payload keys and an unbounded `_transport_stripped` list; C4 makes both exact and bounded before iteration.
- Production correlation IDs default to 32-character UUID hex; verified legacy/current IDs use only alphanumeric, hyphen, and underscore and fit the 128-character cap.
- Current DM results are strings/shallow objects; the 64-Ki-character string cap exceeds the live 8,192-token vision reply budget at the repository's four-characters/token planning ratio, and the 256-KiB response cap remains below NATS's default 1-MiB ceiling.
- Current AD module collects 85 tests before correction additions.
- `src/probos/mesh/intent.py` contains only the accepted exact-membership `has_subscriber()` AD addition and is frozen during correction.

### Review tiers

## Required (must fix before building)

None. C1–C6 are binding correction instructions.

## Recommended

None beyond the named adversarial/stress/lifecycle tests.

## Nits

- Report the final test collection count rather than estimating it.

## Verified

- Exact base/origin unchanged.
- No production/test/tracker/Git/GitHub mutation was performed during this Architect revision.
- Active correction allowlist is four federation source files plus the existing new AD test module; `mesh/intent.py` is unchanged.
- Gates 1–4 remain exactly unchanged.
- The exact Engineering Principles acceptance line remains criterion 24.

**Builder handoff:** apply C1–C6 to the live uncommitted diff, run the unchanged four gates, then return for implementation review. Do not stage, commit, update trackers, archive prompts, push, or mutate #634 before review.

---

## Re-review — latest three implementation blockers (2026-07-17)

**Verdict:** ✅ **RE-APPROVED / CORRECTION EXECUTABLE**

**C1–C6 and every prior behavior remain binding. C7–C9 precisely close the latest three findings without changing gates or scope.**

## Required (must fix before closeout)

1. Apply C7 to scalar result strings, exact result-dict keys, and `error`, including origin/receiver long-subtype coverage.
2. Apply C8 identically in NATS, mock, and ZeroMQ response classifiers, preserving malformed-marker legacy queue behavior and proving zero hostile overrides.
3. Apply C9's exact base UTF-8 em-dash literal and base-vs-worktree AST/byte regression in the existing uncommitted AD test module.

## Recommended

None. Do not broaden C8 into a legacy payload-size migration; report its top-level $O(n)$ scan honestly.

## Nits

- Report the final collection count after the live **211-test** pre-C7–C9 baseline.

## Verified

- `bridge.py` live `_is_forbidden_result_data_url()` examines only a 128-character prefix and requires `;base64,`, is called only for scalar `result` strings, and does not inspect arbitrary dict keys or `error`.
- All three live `deliver_response()` methods classify with `dict.get(message.payload, "delivery_mode")`, which can invoke hostile key comparison; C8 replaces that exact shape.
- Exact HEAD AST literal is `Federation message validator failed — message passed without validation`; the live worktree AST contains mojibake `â€”`.
- C7 scans at most the already-admitted 65,536 characters for a scalar/key or 4,096 for `error`, then compares only the 11-character prefix; C8 is deliberately described as an open legacy top-level $O(n)$ scan.
- Exact base/origin and eight visible status paths are unchanged. `src/probos/mesh/intent.py` SHA-256 remains `8815E98B2ABFE5A668E7F18EE1BF88F548231F725BFFC51C9A31E477DF89640E` and is frozen.
- Active Builder correction allowlist remains exactly four federation source files plus `tests/test_ad730_4_directed_federated_vision_dm.py`; no existing committed test is editable.
- Gates 1–4 are unchanged. Production, tests, trackers, Git, and GitHub were not mutated by this Architect revision.
- The exact Engineering Principles acceptance line remains criterion 24.

**Builder handoff:** apply C7–C9 to the live uncommitted implementation while preserving C1–C6, run the module and unchanged four gates, and return for review. Do not stage, commit, update trackers, archive prompts, push, or mutate #634.
