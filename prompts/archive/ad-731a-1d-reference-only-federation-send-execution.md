# AD-731a-1d Final Builder Correction — Reference-only federation attachment send

**Verdict:** RE-APPROVED / APPLY THE FINAL NESTED-KEY CORRECTION TO THE LIVE UNCOMMITTED DIFF
**Revision:** 2026-07-16 final blocked-review correction is binding; read the binding prompt's `Final blocked review — nested exact-dict hostile-key correction` first. It supersedes conflicts below while preserving every compatible second-review requirement.
**Second-review input hashes:** binding `9c545d555073d1f4ac84682dc6d0662724d460f951f5a9e9732d1c9cc353c767`; execution `b9799fdea41eafc550b17791e218b86d2d71ca180acaf82b498bb03dfa153a53`; issue draft `55cdb7d49540bdccdbe10df85ca941c154ecf7eba962cfc911260bcf8fafb907`
**Final-correction input hashes:** binding `146787639ea52ec2f1973d1213abb93fd07751b093641173f530551759b48743`; execution `2de547bb167a35b3337486892b55fa9fd5338819d8456020a5090b44af8c75ea`; issue draft `b0d8a97b45b820d3e3547468dcf107736d74ef2934eb333978db7648f57233a8`
**Builder handoff hashes:** use the exact three hashes in the Architect handoff response; require byte equality through Builder handback
**Parent issue:** seangalliher/ProbOS#638 — https://github.com/seangalliher/ProbOS/issues/638
**Binding specification:** `prompts/ad-731a-1d-reference-only-federation-send.md`; read fully and execute exactly
**Temporary issue reconciliation:** `logs/ad731a_1d_issue_update.md`; ignored/read-only, never stage or post during Builder execution
**Exact base:** `4236230f7188b88a69aef1f1f010e5747325ef38`
**Base commit:** `BF-672: wire narrow federation attachment resolver (closes #1039)`
**Numbering:** highest top-level is **AD-1122**, BF ceiling is **BF-672**; **AD-731a-1d is pre-reserved** in `PROGRESS.md:117` and `DECISIONS.md:321,324`; do not mint AD-1123
**Scope:** three production files, one new test file, four existing test updates; tracker/roadmap/prompt archival only after final Architect approval
**License disposition:** none

## Pre-flight

The old clean-status precondition no longer applies: the Builder diff is intentionally present. Confirm it contains only the existing AD-731a-1d files plus these Architect-revised prompt docs. Do not reset, restore, stash, checkout, clean, or discard it.

Before any production/test edit:

1. Read `.github/copilot-instructions.md`, `prompts/_TEMPLATE.md`, `prompts/review-criteria.md`, and the complete binding prompt.
2. `git rev-parse HEAD` and `git rev-parse origin/main` must both equal `4236230f7188b88a69aef1f1f010e5747325ef38`.
3. `git status --short` must show the known live AD-731a-1d Builder diff, including `src/probos/routers/threads.py` and `tests/test_ad916_chat_file_sharing.py`, plus the two revised prompt files; the ignored issue draft must exist but remain absent. No unrelated path may appear.
4. Hash the two prompts and ignored draft at start; they must remain byte-identical during Builder execution.
5. Do not fetch, pull, rebase, merge, cherry-pick, reset, checkout, clean, stash, restore, stage, commit, push, or mutate GitHub.
6. Do not edit trackers or archive prompts during Builder execution.
7. Re-run the exact live evidence before editing:
   - one `forward_intent()` semantic send boundary;
   - whole-key strip at `bridge.py:113-124`;
   - BF-672 callback at `bridge.py:233-236` before broadcast;
   - current producer ref shape at `vision_dispatch.py:247`;
   - vendor-only data URL at `llm_client.py:1336-1337`;
   - plural perception refs at `aggregator.py:192` and current extractor gap at `attachment_resolve.py:39-78`.
8. If any premise differs, stop.

## Revision delta — binding standing order

1. Keep the current bridge sanitizer/ref-envelope and plural extraction direction.
2. Before any top-level key lookup/copy/comparison/hash, enumerate only with `dict.items(params)` and require `type(key) is str` as the first operation on every key. Any non-exact key fails the entire mapping closed as `({}, ['params'])`; do not catch `BaseException`.
3. Add one module-private, typed, pure DRY helper for every recognized nested message/block/source mapping. It takes `Any` plus a fixed `frozenset[str]`, rejects non-exact dicts, enumerates only with `dict.items(mapping)`, and checks `type(key) is str` before any other operation involving each key or value. First save only key-safe pairs without inspecting values; after the complete key pass succeeds, ignore exact unknown keys without touching values and copy only approved values into a fresh plain result dict. Callers access only that safe result; no `.get()`, `[]`, membership, copy, or equality may touch an original nested mapping.
4. Approved nested sets are exactly message `{'content'}`, block `{'type', 'source'}`, and source `{'type', 'sha256', 'media_type'}`. At every recognized list/tuple/str value node use exact built-in checks (`type(value) is X`). Never invoke subclass overrides.
5. Unsafe first-message mapping rejects/removes `vision_messages` and `has_image_attachment` while preserving unrelated params and independently safe singular/plural refs. Unsafe block/source skips only that candidate; safe ref siblings before and after survive in order. Exact unknown nested keys are ignored without traversing their values. `_transport_stripped` remains canonical and authoritative.
6. Reconstruct normalized blocks/sources only from validated exact built-in values and constant exact-string keys. Do not copy, compare, iterate, call `set()` on, or preserve extras from an original nested mapping.
7. Preserve fixed `_FEDERATED_ATTACHMENT_CANDIDATE_SCAN_LIMIT = 64` and `_FEDERATED_VISION_SCAN_LIMIT = 64`. Invalid, duplicate, already-admitted, and overflow candidates consume budget. Position 65 is never touched. These bound recognized attachment-candidate traversal only; generic top-level params remain the existing unbounded contract.
8. Make `attachment_ids` the sole API attachment source: remove `attachments` from caller `body.metadata` unconditionally, preserve sibling metadata, and repopulate only from successfully resolved refs.
9. Keep the fixed group producer cap in `routers/threads.py` only after guarded positive identification of >=2 crew. Missing/invalid registry or classification exceptions skip this new rejection and preserve prior append behavior. A positively identified group with >8 resolved image refs raises exact HTTP 413 **before** message persistence/fan-out. Never truncate.
10. Exact detail: `AD-731a-1d: group message exceeds the hard cap of 8 images (observed N). Reduce the image count and resend.`
11. Eight images plus non-image refs passes and persists every server-resolved ref. Unknown IDs keep existing skip behavior.
12. Group cap stays eight when `images_per_dm_hard_cap` is `0` or `99`; single-agent/non-group append stays unchanged except caller attachment metadata is intentionally stripped.
13. No `thread_fanout.py`, `vision_dispatch.py`, `image_policy.py`, `config.py`, UI, or `config/system.yaml` edit.
14. Add every named second-review and final nested-key regression from the binding packet before handback.

## Highest-risk constraints — standing order

1. **Do not blindly remove the strip.** Replace it with exact allowlist reconstruction.
2. **Current first-party producers are ref-only, but group was not <=8 and 1:1 remains configurable.** Correct only the fixed group ingress in `routers/threads.py`; a raised/disabled 1:1 policy may produce >8 and is deliberately transport-sanitized/marked. Do not rewrite `vision_dispatch`, `agents`, `thread_fanout`, perception producers, or the LLM resolver.
3. **Bridge owns semantic sanitization once.** Do not duplicate policy in NATS, ZeroMQ, Mock transport, or IntentBus.
4. **Narrow attachment traversal only.** Inspect `attachment_ref`, `attachment_refs`, exact first-message `vision_messages[].content[].source`, and the `has_image_attachment` companion flag; do not heuristically recurse through unrelated params.
5. **Exact rebuilt vision envelope:** exactly one user message, sourced only from the live first message's content; each block is only `type=image` and `source={type:attachment_ref, sha256, media_type}`; no copied extras or additional messages.
6. **Reject inline forms:** base64 source/data, `image_url`, data URLs, bytes, bytearray, memoryview, malformed/unknown blocks.
7. **Mixed block/source input keeps safe refs.** Do not discard an entire vision array merely because one block or source sibling is unsafe. The final unsafe first-message rule is the deliberate exception because no approved field can be read safely from that envelope.
8. **Inline-only input becomes text-only.** Remove `vision_messages` and `has_image_attachment` when no safe vision ref survives; with safe vision refs preserve only exact boolean `True`, never a spoofed/non-boolean flag.
8a. **Nested hostile-key semantics are level-specific.** Unsafe first message makes the complete vision surface text-only; unsafe block or source removes only that candidate. Safe siblings before/after survive. Unknown exact-string keys are ignored without touching their values.
9. **Validate bare/plural refs.** Lowercase 64-hex only; singular→plural→vision share one first-seen admission set and one global eight-unique-SHA budget; dedup within each surface while preserving required aliases across surfaces; extend receiver extraction for plural refs.
10. **Fixed attachment-surface bounds:** eight unique SHAs globally, at most 17 normalized structural occurrences (1 singular + 8 plural + 8 vision), at most 64 inspected plural candidates, and at most 64 inspected vision content blocks. These do **not** bound top-level generic-param count, traversal needed to preserve unrelated keys, nested generic payload size, or final transport size when unrelated params are large; no config.
11. **Deep immutability:** original `IntentMessage.params` and all nested containers remain unchanged.
12. **Transport marker is authoritative on sanitation:** any present recognized attachment field is validated/rebuilt and named once in exact order `attachment_ref`, `attachment_refs`, `vision_messages`, `has_image_attachment` (only when processed); replace any caller marker on that path. `params` is the sole non-key marker for non-dict top-level input **or an exact dict containing any non-exact-string key**. With an all-exact-string-key mapping and no recognized attachment field present, preserve the complete params mapping (including an existing marker) exactly.
13. **Unrelated params are preserved after the exact-key preflight.** No global text/content/file/tool filtering. Therefore the top-level pass is $O(n)$ in generic key count and is intentionally not globally capped by this AD; nested unrelated values are not traversed.
14. **Non-dict or unsafe-key params fail safely.** An untyped non-dict top-level value or exact dict containing any non-exact-string key becomes empty params plus authoritative `_transport_stripped=["params"]`; never partially preserve that mapping.
15. **BF-672 ordering stays exact:** fetch after inbound `IntentMessage` construction and before local broadcast.
16. **Ordinary resolver failure continues; cancellation propagates.** Do not alter either branch.
17. **AD-731a-1 integrity stays exact:** authenticated GET, size/MIME checks, SHA verify before store.
18. **Vendor conversion stays last-mile only.** Federation output may never contain data URLs/base64 image bytes.
19. **No new resource/task/client/lock/cache.** Pure helper only.
19a. **No generic nested copy/reconstruction hazard.** Rebuild block/source only from validated exact built-in values and constant exact-string keys. Do not use `dict.copy`, `dict(original)`, whole-mapping equality, `set(mapping)`, or retained extras on untrusted nested mappings.
20. **No config/system.yaml.** No config field at all.
21. **No NATS Object Store/replication/backend redesign.** Those are not #638 v1 acceptance.
22. **No issue close/comment during build.** Closeout is conditional on green implementation + final review.
23. **No top-level AD.** AD-1122 remains the ceiling.

## Exact Builder-edit allowlist

### Production

- `src/probos/federation/bridge.py`
- `src/probos/federation/attachment_resolve.py`
- `src/probos/routers/threads.py` — NEW authorization: fixed group-ingress cap only

### Tests

- `tests/test_ad731a_1d_reference_only_federation_send.py` — NEW
- `tests/test_bf265_transport_stripped_params.py`
- `tests/test_ad731_attachment_ref_wire_format.py`
- `tests/test_ad731a_1c_auto_resolve.py`
- `tests/test_ad916_chat_file_sharing.py` — NEW authorization: real group API boundary tests

### Read-only Architect artifacts

- `prompts/ad-731a-1d-reference-only-federation-send.md`
- `prompts/ad-731a-1d-reference-only-federation-send-execution.md`
- `logs/ad731a_1d_issue_update.md`

### Architect-controlled post-review closeout only

- `PROGRESS.md`
- `DECISIONS.md`
- `docs/development/roadmap.md`
- prompt archival under `prompts/archive/`

Everything else is read/run-only. A needed edit outside this allowlist is a hard stop.

## Corrected implementation sequence

1. Add red tests for the nested message/block/source hostile-key matrix, including recognized-looking `str`, unrelated `str`, non-string keys, safe siblings before/after, unknown-key hostile values, both serializers, and no override calls. Retain the top-level, caller-metadata, and minimal/no-registry regressions.
2. Correct `bridge.py` with the two-pass top-level exact-key preflight, one shared nested approved-field preflight helper, exact recognized-value admission, level-specific degradation, constant-key reconstruction, and fixed recognized candidate scans.
3. In `threads.py`, remove caller `metadata.attachments` before resolution, repopulate only from resolved `attachment_ids`, and run the pre-persistence image-count check only after guarded positive crew identification.
4. Retain eight-image+non-image, config `0/99`, and non-group regressions; add forged metadata, resolver-failure, minimal-runtime, and production-positive-identification counter-tests in AD-916.
5. Run the original focused gate with both AD-914 and AD-916 files included, then the new first-party producer audit gate, then the original blast gate.
6. Hand back uncommitted with correction-start/end hashes of both prompts and ignored draft.

Hostile tests must arm key subclasses only after insertion into an exact dict, then make traversal/access/hash/comparison/stringification overrides raise a custom `BaseException`; success means the override was never called, not that production swallowed it. Retain top-level recognized-looking `EvilStr('attachment_ref')`, unrelated `EvilStr('note')`, and a non-string hashable key. Add equivalent recognized-looking, unrelated, and non-string keys at first-message, block, and source levels. The nested test path must use real `forward_intent()` and then both real serializers; no direct helper/sanitizer test is sufficient.

## First-party producer audit gate

Run serial/offline with the standard flags:

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

Clean-base-equivalent baseline: **144 passed, 11 pre-existing BF-326 UserWarnings in 13.21s**. Recalculate after corrections.

## Read first

- all files listed as reference-only in the binding prompt;
- the complete four editable test files (after the new test file exists);
- `tests/test_ad916_chat_file_sharing.py`;
- `tests/test_ad730_agent_chat_vision.py`;
- `tests/test_ad730_2_image_policy.py`;
- `tests/test_ad730_5_vision_tier_override.py`;
- `tests/test_ad720d_vision_pipethrough.py`;
- `tests/test_ad720d_1_multi_image.py`;
- `tests/test_ad720d_2_1_vision_approval.py`;
- `tests/test_ad720d2_vision_capable.py`;
- `tests/test_ad720d3_vision_episode_write.py`;
- `tests/test_bf266_vision_context_folding.py`;
- `tests/test_ad734_wire_shape_contract.py`;
- `tests/test_federation.py`;
- `tests/test_federation_nats.py`;
- `tests/test_ad479_federation_hardening.py`;
- `tests/test_ad443_mobility.py`.

## Ordered implementation

### Step 1 — Headline red-before

Create only `test_cross_host_nats_reference_only_prefetches_before_vision_dm_broadcast` first.

Required composition:

- two real `NATSFederationTransport` instances;
- one shared `MockNATSBus`, started exactly once before both `organize_fleet()` calls and never restarted between them;
- two real `FederationBridge` instances created through two real `organize_fleet()` calls (no direct bridge construction);
- real origin/receiver `FilesystemAttachmentStore`s on `tmp_path`;
- real origin `federation_attachments.router` on a bare FastAPI app;
- real `AttachmentsConfig`/`AuthConfig` and `httpx.ASGITransport`;
- real receiver `IntentBus(SignalManager())` subscriber;
- real `resolve_missing_attachments(..., http=asgi_client)` resolver closure;
- real origin `forward_intent()` invocation on the bridge returned by `organize_fleet()`;
- no direct bridge construction, sanitizer call, callback call, private field mutation, or payload injection.

Run the exact red node. Record the assertion: receiver lacks `vision_messages`, the ASGI fetch counter is zero, and the blob is absent because the origin bridge stripped the key. A different failure is a hard stop until understood.

### Step 2 — Pure bridge sanitizer

In `bridge.py`:

1. add fixed constants and the fully typed pure helper after `AttachmentResolver`;
2. reject a non-exact top-level dict as `({}, ['params'])`;
3. for an exact dict, materialize top-level pairs only from `dict.items(params)` while checking `type(key) is str` before every other operation on each key; if any key is unsafe, return `({}, ['params'])` without partial preservation;
4. only after the complete key pass, copy unrelated exact-string-key params shallowly into a new dict; any present recognized attachment key starts the sanitation path, on which caller `_transport_stripped` is replaced by the authoritative processed-key list;
5. add the shared nested mapping helper immediately above the sanitizer or as a focused sibling helper; it must use `dict.items(mapping)` and `type(key) is str` before every other operation involving each key or value, complete the full key-safety pass before inspecting/copying any value, then copy approved values only and never touch unknown-key values;
6. use approved field snapshots for first-message, each block, and each source; never call `.get()`, `[]`, membership, copy, whole-mapping equality, or `set()` on those untrusted originals;
7. unsafe first message removes the full vision surface and companion flag; unsafe block/source skips only itself, preserving safe siblings before/after;
8. validate/rebuild singular, plural, and vision attachment surfaces per DD-1 through DD-4 using only constant output keys and validated exact built-in values;
9. admit the first eight unique valid SHAs across singular→plural→vision, dedup within each surface, and preserve required cross-surface aliases without consuming another slot;
10. scan at most 64 plural candidates and 64 content blocks; do not describe the full helper as globally bounded because all top-level generic keys must be inspected/preserved;
11. return changed recognized keys;
12. in `forward_intent()`, replace only the current whole-key strip block with the helper call + authoritative marker;
13. leave the remainder of `forward_intent()` unchanged.

Do not log rejected inline data. Tests assert behavior; transport marker provides shape-level observability.

### Step 3 — Receiver plural extraction

In `attachment_resolve.py`:

1. update module/docstring language from “only singular crosses” to the 1d reality;
2. add list/tuple traversal of `attachment_refs` between singular and vision paths;
3. reuse `_add` for validation/dedup;
4. change nothing else.

### Step 4 — Complete counterfactual/security/boundary tests

Implement every named test in the binding prompt. At minimum prove:

- current safe ref happy path;
- inline base64 only;
- data URL/image_url;
- raw bytes/bytearray/memoryview;
- mixed safe + unsafe;
- valid ref plus unsafe extra fields;
- empty/malformed/text-only;
- bad SHA/MIME matrix;
- first-eight normalized-output cap and recognized attachment candidate-scan bounds;
- bare/plural validation;
- original deep immutability;
- unrelated params + marker authority;
- NATS and ZeroMQ serialized byte thresholds for the named short-generic-payload attachment fixtures;
- receiver singular/plural/vision dedup;
- no-attachment value-equality;
- receive prefetch then LLM vendor-bound decode.
- real inbound prefetch failure matrix (404/500, missing MIME, oversize, tamper, store failure) with non-store + broadcast-continuation proof.
- top-level recognized-looking hostile `str` key, unrelated hostile `str` key, and hostile non-string key, all fail-closed as the sole `params` marker without invoking overrides;
- first-message, block, and source recognized-looking hostile `str`, unrelated hostile `str`, and hostile non-string keys, all without invoking overrides;
- unsafe first-message text-only degradation plus independent singular/plural preservation; unsafe block/source candidate-only skip with safe siblings before and after;
- unknown exact-string message/block/source keys whose hostile values are never traversed or serialized;
- caller `metadata.attachments` is always stripped, sibling metadata remains, and resolver failure cannot restore caller refs;
- forged caller attachment metadata cannot reduce the authoritative nine-image count;
- minimal/no-registry runtime with resolved attachments still appends, paired with a positively identified real group that rejects nine.

Use a 500 KiB inline sentinel. Assert it is absent without printing it.

### Step 5 — Update only obsolete federation-strip assertions

- Keep all IntentBus/in-mesh assertions and inline-balloon sentinels.
- Replace only tests that explicitly pin federation's old whole-key strip.
- Drive the real bridge; do not reimplement production sanitizer logic in tests.
- Do not weaken exact ref/no-inline assertions.

### Step 6 — Exact gates

Run the focused and blast commands below. Fix only AD-731a-1d regressions inside the allowlist. A serial failure needing another file is a hard stop.

### Step 7 — Three-pass self-review

Run the binding prompt's behavior, verify-first, and scope/security passes. Confirm:

- no inline conversion added outside the LLM client;
- no transport/config/runtime/store policy duplicated;
- no caller mutation;
- no original nested message/block/source `.get()`, `[]`, membership, generic copy, `set()`, or whole-mapping comparison;
- shared nested helper is pure and DRY; normalized dictionaries use constant keys only;
- no secret/blob logging;
- exact file allowlist;
- prompt/draft hashes unchanged from their Architect-revised correction-start values;
- no staged or deleted path.

### Step 8 — Hand back uncommitted

Return the implementation and report to the Architect. Do not edit trackers, archive prompts, stage, commit, push, or mutate #638.

After final approval, the orchestrator may perform the exact conditional closeout from the binding prompt, archive both prompts, commit, push, and post/close #638 using the ignored reconciliation draft as source text.

## Exact Windows gates

Clean-HEAD baselines at `4236230f`:

| Gate | Baseline |
|---|---:|
| Focused | **195 passed / 7 pre-existing BF-326 UserWarnings in 63.20s** |
| Blast | **163 passed in 221.10s** |
| Old strip pins | **2 passed in 0.60s** |

The seven focused warnings are the pre-existing BF-326 `MagicMock/`-directory `UserWarning`s from the reference-only approval suite. Do not edit that file or warning policy; report the count separately from failures/skips.

### Red-before

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad731a1d_red_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad731a_1d_reference_only_federation_send.py::test_cross_host_nats_reference_only_prefetches_before_vision_dm_broadcast -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad731a1d_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad731a_1d_reference_only_federation_send.py tests/test_bf265_transport_stripped_params.py tests/test_ad731_attachment_ref_wire_format.py tests/test_ad731a_1c_auto_resolve.py tests/test_ad731a_remote_attachment.py tests/test_ad730_agent_chat_vision.py tests/test_ad730_2_image_policy.py tests/test_ad730_5_vision_tier_override.py tests/test_ad720d_vision_pipethrough.py tests/test_ad720d_1_multi_image.py tests/test_ad720d_2_1_vision_approval.py tests/test_ad720d2_vision_capable.py tests/test_ad720d3_vision_episode_write.py tests/test_bf266_vision_context_folding.py tests/test_ad916_chat_file_sharing.py tests/test_ad914_group_chat_fanout.py tests/test_ad734_wire_shape_contract.py tests/test_federation.py tests/test_federation_nats.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast

```powershell
$gateDir = Join-Path $env:TEMP ("probos_ad731a1d_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad479_federation_hardening.py tests/test_ad443_mobility.py tests/test_runtime.py tests/test_bf296_shutdown_phase_ordering.py tests/test_bf598_shutdown_idempotency.py tests/test_distribution.py::TestFastAPIEndpoints::test_create_app_returns_fastapi -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

No parallel/full/live-data substitution.

## Required transport/security assertions

The byte thresholds below apply only to the named short-generic-payload attachment fixtures. They prove the normalized attachment envelope is small; they do not bound an arbitrary preserved unrelated param payload.

- Eight safe vision refs: sanitized vision envelope `< 2 KiB`; complete short-text NATS and ZeroMQ intent request `< 4 KiB`.
- Worst normalized combined surface (1 singular + 8 plural + 8 vision occurrences over 8 unique SHAs): both transport forms `< 4 KiB`.
- 500 KiB inline-only input: inline sentinel absent; text-only transport result.
- 500 KiB mixed input: safe ref retained; inline sentinel absent; output `< 4 KiB`.
- Raw bytes never reach either serializer and never raise a JSON serialization error after sanitization.
- Valid ref plus extra `data`/URL/custom fields is reconstructed without extras.
- Caller `_transport_stripped` cannot hide a sanitation event; a no-attachment payload preserves it like every other unrelated param.
- Any non-exact top-level key fails the entire params mapping closed with the sole authoritative `params` marker before serializer contact; exact unrelated keys retain the existing open/unbounded generic-param contract.
- Every recognized nested mapping is preflighted through the shared pure helper. Unsafe first message removes vision and companion flag; unsafe block/source skips only itself; unknown exact-string keys are ignored without touching values; reconstructed outputs contain only constant keys and validated exact values.
- Caller `metadata.attachments` never reaches persistence or group classification; only successfully resolved `attachment_ids` own that field.
- Original input equals a `copy.deepcopy()` baseline after sending.
- Receiver store contains origin bytes before local handler begins.
- LLM vendor data URL decodes exactly to those bytes.

## Deletion/whitespace/scope audit

Before handback:

```powershell
git status --short
git diff --check
git diff --name-only --diff-filter=D 4236230f7188b88a69aef1f1f010e5747325ef38 --
git diff --stat
git diff --numstat
git diff --no-index --check -- NUL prompts/ad-731a-1d-reference-only-federation-send.md
git diff --no-index --check -- NUL prompts/ad-731a-1d-reference-only-federation-send-execution.md
git check-ignore -v logs/ad731a_1d_issue_update.md
```

For each no-index command, exit code 1 is expected because the untracked prompt differs from empty; emitted whitespace diagnostics are not expected.

Expected Builder-handback status is limited to:

- `M src/probos/federation/bridge.py`
- `M src/probos/federation/attachment_resolve.py`
- `M src/probos/routers/threads.py`
- `?? tests/test_ad731a_1d_reference_only_federation_send.py`
- `M tests/test_bf265_transport_stripped_params.py`
- `M tests/test_ad731_attachment_ref_wire_format.py`
- `M tests/test_ad731a_1c_auto_resolve.py`
- `M tests/test_ad916_chat_file_sharing.py`
- the two untracked prompt docs

No tracker changes yet. The ignored draft must not appear.

## Required Builder report

Return a concise table containing:

- exact base/origin and initial artifact-only status;
- red-before node + exact assertion failure;
- changed files;
- sanitizer signature/constants and scoped attachment-candidate/output bounds, with explicit acknowledgement that generic top-level params remain unbounded by this AD;
- hostile top-level key matrix: recognized-looking string subclass, unrelated string subclass, and non-string key, including exact fail-closed marker results;
- hostile nested key matrix at message/block/source: recognized-looking string subclass, unrelated string subclass, and non-string key; exact level-specific degradation, safe siblings before/after, unknown-value non-traversal, no override calls, marker result, and both serializer results;
- shared nested preflight helper signature/approved sets and confirmation that no attacker-controlled nested keys enter reconstructed output;
- current first-party producer ref-only verification;
- safe, inline-only, data-URL, bytes, mixed, malformed, SHA/MIME, cap, and marker results;
- deep-immutability result;
- server-authoritative metadata results: forged bypass rejected, caller-only attachments stripped, resolver-failure fallback text-only, sibling metadata retained;
- positive group classification pair: minimal/no-registry append succeeds and production two-crew group rejects nine;
- NATS/ZeroMQ exact serialized byte counts;
- plural extraction result;
- real origin serve/fetch + receiver store-before-broadcast result;
- receiver LLM vendor-bound byte round-trip result;
- BF-672 cancellation/failure compatibility;
- focused/blast exact counts/skips/failures/durations;
- three-pass verdict;
- scope/deletion/whitespace audit;
- prompt/draft hash equality;
- license `none`;
- confirmation of no tracker/archive/stage/commit/push/GitHub mutation;
- whether all #638 close criteria are met or any exact unmet criterion remains.

## Hard stops

Stop if any binding-prompt hard stop fires, especially if:

- the red test needs direct sanitizer/callback invocation;
- a first-party producer is not ref-only;
- correctness needs another production file, transport fork, config, endpoint, protocol, store backend, task/resource, or global recursive sanitizer;
- any implementation globally caps/drops exact unrelated top-level params to make the sanitizer appear bounded;
- any hostile top-level key override is invoked, or unsafe-key failure preserves a partial mapping;
- any hostile nested key override is invoked, any original nested mapping is accessed after preflight, unsafe first-message degradation is not text-only, unsafe block/source drops safe siblings, unknown-key values are touched, or reconstruction copies hostile/unknown keys;
- caller `metadata.attachments` survives, influences the group count, or is restored after resolver failure;
- missing/minimal registry infrastructure makes the pre-persistence cap reject/500 instead of preserving prior append;
- another producer that should have a fixed canonical bound (other than the deliberately configurable 1:1 path) can exceed eight after the group-ingress correction;
- a serial gate failure needs weakening/quarantine/unallowlisted edits;
- NATS Object Store/replication is discovered to be required for the issue's reconciled v1 acceptance;
- prompt/draft hashes change; or
- any tracker/Git/GitHub mutation occurs before review.

## Acceptance

The Builder handoff is complete only when the red-before is recorded, every binding acceptance item is mapped to a passing test, exact focused/blast gates pass, named attachment fixtures meet their serialized byte thresholds without claiming a generic-payload bound, no inline attachment representation crosses federation, every nested hostile-key matrix passes through real forwarding and both serializers without override invocation, the original message remains unchanged, BF-672 prefetch order is proven, final status is allowlisted, and the uncommitted report returns to the Architect.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
