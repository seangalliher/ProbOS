# AD-731a-1d — Reference-only federation attachment send (final nested-key correction)

**Verdict:** ✅ RE-APPROVED FOR FINAL BUILDER CORRECTION
**One-line:** Keep the reference-only bridge design and all prior valid corrections, but make every recognized nested exact-dict lookup hostile-key-safe through one DRY pure helper before forwarding.

**Re-review date:** 2026-07-16
**Live state:** revise the existing uncommitted Builder diff in place; do not reset/discard it
**Numbering:** highest landed top-level remains AD-1122 and BF ceiling remains BF-672; AD-731a-1d is pre-reserved, so this correction mints neither a new AD nor a new BF
**Second-review input hashes:** binding `9c545d555073d1f4ac84682dc6d0662724d460f951f5a9e9732d1c9cc353c767`; execution `b9799fdea41eafc550b17791e218b86d2d71ca180acaf82b498bb03dfa153a53`; issue draft `55cdb7d49540bdccdbe10df85ca941c154ecf7eba962cfc911260bcf8fafb907`
**Final-correction input hashes:** binding `146787639ea52ec2f1973d1213abb93fd07751b093641173f530551759b48743`; execution `2de547bb167a35b3337486892b55fa9fd5338819d8456020a5090b44af8c75ea`; issue draft `b0d8a97b45b820d3e3547468dcf107736d74ef2934eb333978db7648f57233a8`
**Builder handoff hashes:** see the Architect handoff response; hash the three artifacts at Builder start and require byte equality through handback

## Binding revision

This compact packet is authoritative. Only the pre-revision provisions explicitly incorporated under “Retained original packet provisions” remain binding; all other pre-revision text is superseded.

### Final blocked review — nested exact-dict hostile-key correction

The top-level preflight is valid, but the active sanitizer still calls `first_message.get(...)`, `block.get(...)`, and `source.get(...)`. An exact built-in `dict` can contain an armed `str` subclass or non-string key inserted before arming. A lookup by an approved exact-string name may then invoke the resident hostile key's `__eq__`; the sanitizer's exact-container check alone is insufficient.

Add one DRY, module-private, pure helper in `bridge.py` and use it for **every** recognized nested message/block/source mapping:

```python
def _preflight_exact_dict_fields(
  mapping: Any,
  approved_keys: frozenset[str],
) -> tuple[bool, dict[str, Any]]:
  """Validate exact-string keys and return approved fields only."""
```

The name may differ, but the contract and algorithm may not:

1. If `type(mapping) is not dict`, return `(False, {})` before any mapping operation.
2. Enumerate only with `dict.items(mapping)`.
3. For each yielded pair, `type(key) is str` is the **first and only operation involving that key before safety is known**. If false, immediately return `(False, {})`. Do not compare, hash, stringify, format, serialize, insert, or inspect the value first.
4. During this first pass, save each yielded `(key, value)` pair in a temporary list only after the key is proven exact `str`; do not inspect, compare, copy into the result, or otherwise touch the value. If a later key is unsafe, return `(False, {})` and no earlier value has been semantically consumed.
5. Only after the complete key-safety pass succeeds, compare saved exact-string keys to the fixed approved-key set. Exact-string unknown keys are ignored **without traversing, comparing, copying, serializing, or otherwise touching their values**. For an approved key, copy its value into the helper-owned plain result dict. Duplicate exact keys are impossible in a dict. Return `(True, fields)` after this second pass.
6. Callers access approved fields only from the returned plain dict using exact keys. Never subsequently call `.get`, `[]`, membership, `dict.get`, or `dict.__contains__` on the untrusted original mapping.
7. Never use `dict(mapping)`, `dict.copy(mapping)`, a comprehension that inserts unknown keys, or equality/comparison of the original mapping. Never catch `BaseException`.

Approved sets are exact and narrow:

- first message: `frozenset({'content'})`;
- content block: `frozenset({'type', 'source'})`;
- source: `frozenset({'type', 'sha256', 'media_type'})`.

Apply these degradation semantics exactly:

- **Unsafe first-message mapping:** reject the complete vision envelope. Remove `vision_messages` and its companion `has_image_attachment`; preserve unrelated params and independently safe singular/plural refs. This is text-only for the vision surface.
- **Unsafe block mapping:** skip only that block candidate. Continue in order so safe block siblings before and after it survive.
- **Unsafe source mapping:** skip only that block candidate. Continue in order so safe block siblings before and after it survive.
- **Unknown exact-string nested keys:** ignore them without traversing their values. They do not make an otherwise safe message/block/source unsafe.
- **Marker authority:** `vision_messages` remains present once processed in the exact canonical `_transport_stripped` order. `has_image_attachment` is added to the marker only when the companion flag is removed under the existing rules. Do not replace this with a nested-key marker and do not expose hostile key text.

Media/source copy safety conclusion: no generic nested copy is allowed or needed. Reconstruct the normalized block solely from already validated exact built-in values and constant exact-string keys. Do not compare a source/block dict to an allowlist, call `set(source)`, use `source.items()` outside the helper, or preserve extra source/block fields. SHA admission remains safe only after `type(sha) is str`; MIME membership remains safe only after `type(media_type) is str`; source/block type equality remains safe only after `type(value) is str`. The final reconstructed dictionaries contain no attacker-controlled keys and therefore add no further key/value comparison hazard.

Required final regressions in `tests/test_ad731a_1d_reference_only_federation_send.py` must drive the real `FederationBridge.forward_intent()` and both real serializers:

1. Parameterize message, block, and source levels with an armed recognized-looking `str` subclass key and an armed unrelated `str` subclass key. Include a hostile non-string hashable key at each level. Arm only after insertion. Override `__hash__`, `__eq__`, `__str__`, `__repr__`, `__iter__`, `__len__`, and membership hooks to raise the custom `BaseException`; assert the call log stays empty.
2. Message-level cases include unrelated safe params plus safe singular/plural refs. Assert unsafe first message removes `vision_messages` and `has_image_attachment`, preserves those independent safe siblings, and emits the canonical authoritative marker.
3. Block-level and source-level cases put a safe ref block before and after the unsafe candidate. Assert both safe siblings survive in order (subject only to the existing per-surface SHA dedup), only the unsafe candidate is skipped, the companion flag remains only when exact boolean `True`, and marker order is unchanged.
4. Add unknown exact-string keys at message, block, and source levels whose values are hostile attribute/container objects. Assert those values are never traversed or serialized and safe approved fields still forward.
5. Assert exact reconstructed source/block key sets through ordinary safe output inspection and assert the original graph remains deeply unchanged.
6. Do not satisfy these tests by directly calling the helper or sanitizer; use real `forward_intent()`, then invoke both NATS and ZeroMQ serializers on the resulting message.

All top-level exact-key, 64-position candidate-scan, server-owned metadata, positive crew-classification, prefetch, vendor-bound, and gate requirements below remain binding.

### Second blocked review — exact corrections

| Finding | Required correction |
|---|---|
| Exact dict still invokes hostile key overrides | Enumerate the exact top-level dict only with `dict.items(params)`. For each pair, evaluate `type(key) is str` before any membership, equality, hash, formatting, serialization, or insertion involving that key. Exact-string keys follow normal recognized/unrelated handling. Any non-exact-string key makes the complete top-level mapping unsafe: return only `({}, ['params'])`; do not continue, preserve earlier keys, invoke the hostile key, or add a key-specific marker. Never use `any(key in params ...)`, `params.get(...)`, a comprehension filtered by key, `dict(params)`, or `dict.copy(params)` before the full key-safety pass. Do not catch `BaseException`. |
| “Bounded sanitizer” overclaims global work | The 64-position plural and vision limits bound **recognized attachment-candidate traversal only**. Exact top-level key validation and shallow preservation of unrelated generic params still inspect every top-level entry because `IntentMessage.params` is an existing open mapping contract. Nested unrelated values are not traversed. Do not call the complete sanitizer or transport payload globally work-/size-bounded. |
| Caller metadata can bypass the group cap | Make `body.attachment_ids` the sole API authority for message attachment refs. Build `_meta` from caller metadata with top-level `attachments` removed unconditionally, then add `attachments` only from refs successfully returned by `resolve_attachment_refs()`. Caller-supplied `metadata.attachments` is silently ignored; every other metadata field is preserved. No current source/UI caller intentionally submits it; direct `ChatThreadStore.append_message(... metadata={'attachments': ...})` fixtures are a separate store-level contract and remain unchanged. |
| Crew classification can break prior append | Apply the 413 only after guarded, positive identification of at least two crew agents. Missing registry, `registry is None`, missing/non-callable `registry.get`, or any classification exception means “group not positively identified”: skip the cap check and preserve the prior append/honest-degrade path. A normal production runtime with two real crew still rejects nine images. Do not infer group status merely from two participant IDs. |

### Corrected producer audit

The claim that all accepted first-party paths were already `<=8` is **withdrawn**.

- `threads.AppendMessageRequest.attachment_ids` has no max. `append_message()` resolves and persists every ref, then `group_chat_fanout()` calls `build_chat_vision_messages()`, which selects every image and invokes `build_multimodal_messages()` without `ImagePolicyEnforcer`. `_send_one()` forwards the complete array to vision-capable agents.
- Clean-base empirical probe: a nine-image group build emitted 9 refs with `images_per_dm_hard_cap=8`, and also 9 with the policy disabled (`0`).
- Per-agent 1:1 produces ref-only messages but its hard cap is configurable; `0` disables and values above 8 raise it. It is not proof of a universal ceiling.
- Fused perception emits two refs (singular alias + plural pair); singular perception emits one.
- `/api/chat`, avatar verification/divergence/self-render, perception describe/identity, and browser verify/compute-use call `LLMRequest` directly. They are not ref-bearing federation `IntentMessage` producers.

After this revision, the first-party paths with a canonical fixed producer bound are group `<=8`, fused perception `2`, and singular perception `1`. The configurable 1:1 path may still produce more than eight when an operator raises/disables its policy; if federation forwarding applies, the bridge intentionally reduces only its transport copy to eight and records `_transport_stripped`. Old peers, plugins, restored agents, and direct callers receive the same defense. Do not claim overflow is impossible or silently lossless.

### Selected producer-boundary behavior

The smallest correct seam is `append_message()` in `src/probos/routers/threads.py`, not the shared vision builder:

1. Start with `_meta = dict(body.metadata or {})`, then unconditionally remove `_meta['attachments']` if present. Preserve all sibling metadata exactly. This is source ownership, not validation of caller-provided refs.
2. Resolve `body.attachment_ids` once through existing `resolve_attachment_refs()`. Only successfully resolved refs may repopulate `_meta['attachments']`; empty/unknown/failure leaves the key absent. The caller's metadata cannot restore it.
3. For `body.role == 'captain'`, load the target thread and positively identify group status through existing `crew_agent_participants()` only behind a narrow ordinary-exception guard around classification. Treat absent/invalid registry infrastructure as unknown/non-group for this new pre-append check; do not raise and do not reject.
4. Once group status is positively established as at least two crew agents, count successfully resolved refs whose MIME starts with `image/`.
5. If group image count is greater than eight, raise **before** Captain-message persistence, project touch, participant mutation, fan-out, episode, or bus dispatch:

```python
HTTPException(
  status_code=413,
  detail=(
    "AD-731a-1d: group message exceeds the hard cap of 8 images "
    f"(observed {image_count}). Reduce the image count and resend."
  ),
)
```

6. At eight images, persist all server-resolved refs, including any number of non-image attachments, in original resolved order. Never slice `attachment_ids`, resolved metadata, or `vision_messages`.
7. Unknown refs retain existing skip behavior and do not count. Resolver/backend failure retains existing text-only honest-degrade behavior and cannot fall back to caller-supplied `metadata.attachments`.
8. The fixed group ceiling remains eight when `images_per_dm_hard_cap` is `0` or `99`; do not read that config for this check.
9. Single-agent/non-group thread append behavior remains unchanged except for the intentional security contract that caller-supplied `metadata.attachments` is removed. Minimal/no-registry runtimes continue to append successfully.

This makes overflow observable and prevents a Captain transcript row from claiming attachments that were silently omitted from dispatch. No UI edit is authorized. The live group HXI currently parses the FastAPI JSON response without checking `res.ok`; UI error presentation is forward work, while the HTTP contract is still observable to API callers and the existing `threadApi.appendMessage()` wrapper already degrades non-OK to `null`.

### Sanitizer safety and scoped work bounds

Keep `_sanitize_attachment_params_for_federation()` in `bridge.py`, with:

```text
_FEDERATED_ATTACHMENT_REF_LIMIT = 8
_FEDERATED_ATTACHMENT_CANDIDATE_SCAN_LIMIT = 64
_FEDERATED_VISION_SCAN_LIMIT = 64
```

Binding rules:

1. `type(params) is not dict` returns `({}, ['params'])` before membership, copy, `.items()`, or iteration. No unrelated value can be preserved from a hostile top-level mapping without traversing it; the authoritative marker makes that fail-closed discard observable.
2. For an exact dict, perform a complete key-safety pass with the unbound built-in operation `dict.items(params)`. The first operation on each yielded key is `type(key) is str`. Do not hash, compare, stringify, format, serialize, insert, or test membership first. If any key is not exact `str` — including a recognized-looking `str` subclass such as `EvilStr('attachment_ref')`, an unrelated `EvilStr('note')`, or any other hashable object — fail closed for the whole mapping as `({}, ['params'])`. The unsafe key's overrides must never run.
3. Only after every top-level key is proven exact `str`, process the saved `(key, value)` pairs. This second pass may compare exact strings, build the recognized-key list, and shallowly preserve unrelated values. Never traverse or mutate unrelated values. Deep immutability means the input graph is not mutated; it does not require recursive copying of unrelated payloads.
4. SHA and MIME values require `type(value) is str` **before** `len`, character iteration, equality, membership, or hashing.
5. Message/block/source values require exact dict and the final correction's shared exact-key preflight helper before field access. No `.get()`, `[]`, or membership may touch the original nested mapping.
6. `vision_messages` and `content` require exact list. Plural refs accept exact list or exact tuple only.
7. Reject dict/list/tuple/str subclasses without calling their `__contains__`, `items`, `get`, `__iter__`, `__getitem__`, `__len__`, `__hash__`, or comparison overrides.
8. Arbitrary recognized values (`None`, bool/int, bytes/bytearray/memoryview, generators, custom Mapping/Iterable, hostile attribute objects) degrade without escape or serialization failure.
9. Plural inspection stops after 64 positions independently of eight accepted outputs. Invalid/duplicate entries consume the 64. Candidate 65 is not touched.
10. Vision inspection keeps the existing first-message-only exact envelope and stops after 64 content positions; every position consumes budget.
11. Preserve the existing global eight-unique SHA admission order singular → plural → vision and cross-surface alias semantics.
12. Preserve exact ref reconstruction, mixed-safe retention, inline-only text degrade, marker authority, no inline bytes/URLs, and deep non-mutation. Unsafe first-message mapping rejects the vision surface; unsafe block/source mappings skip only that candidate and retain safe siblings.
13. Scope statement: only plural/vision attachment-candidate traversal and normalized attachment output are fixed-bounded. The full top-level pass is $O(n)$ in the caller's number of generic params, and unrelated generic values remain the existing unbounded-by-this-AD transport contract. Existing serializer/transport limits still apply downstream; this AD does not create a global generic-param bound.

### Revised exact file allowlist

**Production:**

- `src/probos/federation/bridge.py`
- `src/probos/federation/attachment_resolve.py`
- **newly authorized:** `src/probos/routers/threads.py`

**Tests:**

- `tests/test_ad731a_1d_reference_only_federation_send.py`
- `tests/test_bf265_transport_stripped_params.py`
- `tests/test_ad731_attachment_ref_wire_format.py`
- `tests/test_ad731a_1c_auto_resolve.py`
- **newly authorized:** `tests/test_ad916_chat_file_sharing.py`

No other source/test path is authorized. In particular: no `thread_fanout.py`, `vision_dispatch.py`, `image_policy.py`, `config.py`, UI file, dependency, or `config/system.yaml`.

### Required second-review tests

In the new AD-731a-1d test file:

1. Retain the nested hostile-container/value tests already added.
2. Add the final nested exact-dict matrix for message/block/source recognized-looking hostile `str`, unrelated hostile `str`, and hostile non-string keys; prove safe siblings before/after, unknown-key value non-traversal, real `forward_intent()`, both serializers, no override calls, exact degradation, marker authority, and deep non-mutation.
3. Retain `test_top_level_recognized_looking_hostile_str_key_fails_closed_without_override` — create and insert an armed-after-insertion `str` subclass whose `__hash__`, `__eq__`, `__str__`, `__repr__`, `__iter__`, `__len__`, and membership hooks raise the custom `BaseException`; key text is `attachment_ref`. Drive real `forward_intent()` and assert outbound params are exactly `{'_transport_stripped': ['params']}`, both serializers succeed, and no override runs.
4. Retain `test_top_level_unrelated_hostile_keys_fail_closed_without_override` — cover at least an armed unrelated `str` subclass (`note`) and a hostile non-string hashable object key. Include safe entries before and after the unsafe key. Assert the whole mapping is discarded with only the `params` marker; no partial preservation and no override invocation.
5. Retain `test_top_level_exact_string_keys_preserve_generic_params_and_attachment_marker_order` — exact unrelated keys/values remain shallowly preserved, recognized keys still sanitize in canonical order, and the input graph remains unchanged.
6. Retain the 64-position plural/vision tests, but describe them as recognized candidate-scan bounds, not a global sanitizer bound.

In `tests/test_ad916_chat_file_sharing.py` using its real stores/router/bus fixtures:

6. Retain `test_group_ingress_rejects_nine_images_before_persist_or_dispatch` and ensure it uses two positively identified production crew types.
7. Retain the eight-image+non-image, config `0/99`, and single-agent cases.
8. Add `test_group_ingress_caller_metadata_attachments_cannot_bypass_cap` — send nine real resolved `attachment_ids` plus caller metadata containing a forged/truncated `attachments` list of zero or eight images and a sibling marker. Assert exact 413/no side effects; caller metadata cannot reduce the authoritative count.
9. Add `test_append_message_strips_caller_metadata_attachments_without_attachment_ids` — on a normal non-group request, caller `metadata.attachments` is absent from response/persistence while a sibling metadata marker is preserved.
10. Add `test_resolver_failure_does_not_restore_caller_metadata_attachments` — force existing resolution honest-degrade, supply forged caller attachments plus a sibling marker, and assert HTTP 200 text-only persistence with no attachments key and sibling preserved.
11. Add `test_minimal_runtime_with_resolved_attachments_preserves_prior_append` — runtime has store/config/attachment store but no `registry`; two participant IDs and nine successfully resolved images must return HTTP 200 and persist the Captain row because group status was not positively identified. The later existing AD-914 fan-out guard may log/degrade exactly as before.
12. Add `test_production_group_positive_identification_still_rejects_nine` or strengthen test 6 to explicitly prove the same participant list under the real fake registry is 413. This is the counter-pair to test 11.

Retain all 29 current AD-731a-1d tests, the cross-host serve/fetch/store-before-broadcast proof, vendor-bound byte round trip, failure continuation matrix, historical strip-pin inversions, and plural extraction/fetch tests.

### Revised gates

Use isolated `PROBOS_DATA_DIR`, local/offline embeddings, `-p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning`.

Add `tests/test_ad914_group_chat_fanout.py` and `tests/test_ad916_chat_file_sharing.py` to the original focused gate. Recalculate the final focused count rather than predicting it.

Add this first-party producer audit gate:

```text
tests/test_ad730_agent_chat_vision.py
tests/test_ad720d_vision_pipethrough.py
tests/test_ad720d_1_multi_image.py
tests/test_ad730_2_image_policy.py
tests/test_ad916_chat_file_sharing.py
tests/test_ad914_group_chat_fanout.py
tests/test_ad733_frame_endpoint.py
tests/test_ad746_vision_aggregator.py
tests/test_ad728_render_verification.py
tests/test_ad728c_render_self_check.py
tests/test_ad706c2_compute_use.py
tests/test_ad706c_1_browser_verify.py
```

Clean-base-equivalent result on 2026-07-16: **144 passed, 11 pre-existing BF-326 UserWarnings in 13.21s**. A narrower group/file/policy baseline was **40 passed in 3.27s**. Retain the original blast gate (clean-base **163 passed in 221.10s**).

### Revised hard stops

Stop if any hostile recognized value/key escapes or invokes an override; any non-exact top-level key is partially preserved or produces anything other than the sole `params` marker; candidate 65 is inspected; the packet claims global work/size boundedness for generic params; caller `metadata.attachments` survives or influences the authoritative count; a minimal/no-registry runtime 500s or rejects under the new cap; a positively identified production group accepts nine resolved images; group overflow is truncated; 413 occurs after persistence/fan-out; non-image refs are lost; a needed edit is outside the revised allowlist; or any config/YAML/UI/tracker/Git/GitHub mutation occurs before review.

Also stop if any original nested message/block/source mapping is accessed by `.get()`, `[]`, or membership; any nested non-exact key invokes an override; an unsafe first message leaves `vision_messages` or its companion flag; an unsafe block/source drops safe siblings; an unknown exact-string key's value is touched; or reconstruction copies/comparisons retain attacker-controlled nested keys.

### Revised acceptance additions

1. Exact top-level dict traversal uses `dict.items(params)` and checks `type(key) is str` before every operation that could invoke a key override; any unsafe key fails the whole mapping closed as `({}, ['params'])`.
2. Plural and vision attachment-candidate work are each fixed at 64; invalid and duplicates consume budget; position 65 is untouched. Generic top-level params are explicitly not globally bounded by this AD.
3. Caller-supplied `metadata.attachments` is always removed at the API boundary and only successfully resolved `attachment_ids` can repopulate persisted attachment metadata.
4. Group >8 authoritative resolved images returns exact 413 before all side effects and never truncates; a forged smaller metadata list cannot bypass it.
5. Group eight images plus non-images preserves all server-resolved non-images.
6. Group cap is fixed independently of 1:1 policy disable/raise, but only after positive crew identification; minimal/no-registry append behavior remains available.
7. No claim remains that all current first-party paths were already <=8 or that arbitrary generic params are globally work-/size-bounded.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
9. Every recognized nested exact dict is preflighted through one DRY pure helper using `dict.items(mapping)` and `type(key) is str` before exact approved-key lookup; no hostile nested key override runs.
10. Unsafe first-message mappings remove the complete vision surface and companion flag; unsafe blocks/sources skip only themselves; safe siblings survive; exact unknown nested keys are ignored without touching values; normalized reconstruction uses only approved values and constant keys.

### Re-review verdict

**✅ Builder is re-approved to correct the current uncommitted diff in place.** Preserve every valid prior correction; add the shared nested exact-dict preflight and named hostile-key regressions; return uncommitted for final review.


## Retained original packet provisions

The following original provisions remain binding and are incorporated by reference from the first packet: the cross-host NATS red-before topology; exact AD-731 reference envelope; mixed-safe retention and inline/base64/data-URL/raw-bytes rejection; authoritative `_transport_stripped` behavior; deep input non-mutation; receiver plural extraction; BF-672 prefetch-before-local-broadcast ordering and cancellation semantics; authenticated HTTP fetch with MIME/size/SHA verification before store; attachment-envelope NATS/ZeroMQ size assertions under the named short generic payload fixtures; failure-continuation matrix; conditional #638 closeout; no replication/backend/config/UI scope; and the three-pass review process. The second-review correction above supersedes every earlier claim that the complete sanitizer or arbitrary generic transport payload is globally work-/size-bounded.

## Full exact gates

All commands run from `D:\ProbOS` with a unique isolated data directory and:

```text
PROBOS_EMBEDDINGS=local
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
-p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning
```

### Focused correction files

```text
tests/test_ad731a_1d_reference_only_federation_send.py
tests/test_bf265_transport_stripped_params.py
tests/test_ad731_attachment_ref_wire_format.py
tests/test_ad731a_1c_auto_resolve.py
tests/test_ad731a_remote_attachment.py
tests/test_ad730_agent_chat_vision.py
tests/test_ad730_2_image_policy.py
tests/test_ad730_5_vision_tier_override.py
tests/test_ad720d_vision_pipethrough.py
tests/test_ad720d_1_multi_image.py
tests/test_ad720d_2_1_vision_approval.py
tests/test_ad720d2_vision_capable.py
tests/test_ad720d3_vision_episode_write.py
tests/test_bf266_vision_context_folding.py
tests/test_ad916_chat_file_sharing.py
tests/test_ad914_group_chat_fanout.py
tests/test_ad734_wire_shape_contract.py
tests/test_federation.py
tests/test_federation_nats.py
```

Prior pre-revision focused baseline was 195 passed plus seven known BF-326 UserWarnings. Recalculate after the additional group tests; do not predict a total.

### First-party producer audit files

```text
tests/test_ad730_agent_chat_vision.py
tests/test_ad720d_vision_pipethrough.py
tests/test_ad720d_1_multi_image.py
tests/test_ad730_2_image_policy.py
tests/test_ad916_chat_file_sharing.py
tests/test_ad914_group_chat_fanout.py
tests/test_ad733_frame_endpoint.py
tests/test_ad746_vision_aggregator.py
tests/test_ad728_render_verification.py
tests/test_ad728c_render_self_check.py
tests/test_ad706c2_compute_use.py
tests/test_ad706c_1_browser_verify.py
```

Clean-base-equivalent result: **144 passed, 11 pre-existing BF-326 UserWarnings in 13.21s**.

### Blast files

```text
tests/test_ad479_federation_hardening.py
tests/test_ad443_mobility.py
tests/test_runtime.py
tests/test_bf296_shutdown_phase_ordering.py
tests/test_bf598_shutdown_idempotency.py
tests/test_distribution.py::TestFastAPIEndpoints::test_create_app_returns_fastapi
```

Clean-base result: **163 passed in 221.10s**.

## Conditional closeout

Only after final Architect approval: update `PROGRESS.md`, `DECISIONS.md`, and only the #638 rows in `docs/development/roadmap.md`; archive both prompt docs; use the ignored issue draft as proposed text; then commit/push/comment/close through the normal orchestrator. During Builder correction, do none of these.

## Three-pass re-review

1. **Behavior:** map every revised and retained acceptance item to tests; prove no inline blob, top-level and nested unsafe-key fail-closed/skip behavior, safe sibling preservation, unknown-value non-traversal, exact 64 recognized candidate-scan bounds, server-owned attachment metadata, positive group identification, observable group 413, minimal-runtime append preservation, non-image preservation, prefetch order, and vendor-bound dereference.
2. **Verify-first:** re-read every changed method/caller; confirm `dict.items(params)` plus `type(key) is str` precedes every top-level key operation; confirm the shared helper does the same for message/block/source and no original nested mapping receives `.get()`, `[]`, or membership; exact built-in checks precede every recognized-value operation; caller attachments are removed before resolver handling; group check precedes persistence; plural extraction is unchanged outside its addition.
3. **Scope/safety:** exact allowlist only; no config/YAML/UI/dependency; no blob/secret logging; prompts/draft unchanged from correction-start hashes; no Git/GitHub mutation.

## Verified against live code and clean base (2026-07-16)

```text
HEAD/origin = 4236230f7188b88a69aef1f1f010e5747325ef38
highest landed top-level = AD-1122; BF ceiling = BF-672
AD-731a-1d is pre-reserved

threads.py
  AppendMessageRequest.attachment_ids: no max
  append_message: resolves refs, then persists before group fan-out

thread_fanout.py
  resolve_attachment_refs: all found refs
  build_chat_vision_messages: all image refs; no ImagePolicyEnforcer
  _send_one: complete vision array assigned to vision-capable agent

image_policy.py/config.py
  1:1 cap configurable; <=0 disables; default 8
  production enforcer use is routers/agents.py only

ProfileChatTab.tsx
  group POST sends complete attachmentIds; parses FastAPI JSON without res.ok check

empirical clean-base producer probe
  group builder with 9 refs and config 8 -> 9 image blocks
  group builder with 9 refs and config 0 -> 9 image blocks

empirical active-diff security probe
  hostile builtin subclasses escaped RuntimeError at recognized nodes
  2,000,000 duplicate plural refs consumed ~3.95 seconds
  existing AD-731a-1d tests: 29 passed but did not cover these findings

second blocked-review probes
  armed top-level EvilStr('attachment_ref') key -> _HostileOverrideInvoked escaped
  armed top-level EvilStr('unrelated') key -> _HostileOverrideInvoked escaped
  exact dict enumeration via dict.items(params) yielded hostile key objects without invoking overrides
  ordinary membership against recognized-looking hostile key invoked __eq__
  source/UI caller audit: 0 thread-append API callers submit metadata.attachments
  ProfileChatTab.tsx:1056-1063 group POST supplies attachment_ids
  threadApi.ts:239-243 exposes metadata and attachment_ids as separate request fields
  GroupChatHeader.tsx:112-116 supplies legitimate sibling metadata meeting_end/participant_count; it must survive
  direct metadata.attachments writes: 11 ChatThreadStore-level test fixtures only
    test_ad916_chat_file_sharing.py:231,514,537,556,581
    test_ad926_inputs_folder.py:137,179,187,214,293,351
  no production source constructs AppendMessageRequest directly
  thread_fanout.py:120-125 crew_agent_participants dereferences runtime.registry.get without its own guard
  active threads.py:380-388 invokes crew_agent_participants before the existing post-persistence AD-914 try/except
  minimal runtime without registry currently appends successfully via the existing post-persistence AD-914 degrade path

final nested-key blocked-review probes
  active sanitizer uses first_message.get('content'), block.get('type'/'source'), and source.get('type'/'sha256'/'media_type')
  exact built-in dict with an armed resident EvilStr('type') invokes EvilStr.__eq__ under dict.get(mapping, 'type') and dict.__contains__(mapping, 'type')
  dict.items(mapping) enumerates the same armed key without invoking its overrides
  dict.copy(mapping) also avoided overrides empirically, but is deliberately rejected here because it copies hostile/unknown keys and values into a later comparison/serialization hazard
  safe solution is one pure approved-field preflight plus constant-key reconstruction; no nested generic copy is required

clean-base-equivalent tests
  group/file/policy: 40 passed in 3.27s
  expanded producer audit: 144 passed, 11 warnings in 13.21s
```

## Final revised acceptance

1. Exact built-in type checks make recognized-value handling safe, and exact top-level key preflight fails the whole mapping closed without invoking hostile key overrides.
2. Plural and vision attachment-candidate scans each stop at 64 inspected positions; invalid and duplicates consume budget; position 65 is untouched. Generic top-level params remain the existing unbounded contract.
3. Eight unique SHA normalized-output cap, exact ref envelope, no-inline invariant, marker authority, and deep non-mutation hold.
4. Message attachment metadata is server-owned: caller `metadata.attachments` is removed unconditionally and only resolver output from `attachment_ids` is persisted.
5. Nine authoritative resolved group images return exact HTTP 413 before persistence or dispatch; no silent truncation or forged-metadata bypass.
6. Eight group images plus non-images pass and preserve every server-resolved non-image ref.
7. Fixed group cap ignores 1:1 config disable/raise and applies to positively identified production groups; minimal/no-registry runtimes preserve prior append behavior.
8. Receiver plural extraction, prefetch-before-broadcast, authenticated/hash-verifying fetch, vendor-bound conversion, and failure/cancellation behavior remain green.
9. No config/system.yaml, UI, protocol/dataclass, transport implementation, backend, dependency, tracker, Git, or GitHub change during build.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
11. Every message/block/source exact dict is key-preflighted by the shared helper before approved field access; hostile nested keys cannot invoke overrides, unsafe message/block/source degradation follows the exact level-specific semantics, and unknown exact-string values are not traversed.

## Revised Architect verdict

**✅ RE-APPROVED FOR FINAL BUILDER CORRECTION.** Implement only the revised allowlist against the live uncommitted diff, preserve all prior valid corrections/gates, and return uncommitted for final review.
