# AD-731 — Content-Addressable Vision Payloads (Wave 152)

**Status:** Ready for Builder
**Dependencies:** AD-720 (FilesystemAttachmentStore, shipped), AD-720a (multipart upload, shipped), AD-720d (vision pipe-through for /api/chat, shipped), AD-730 (per-agent DM vision pipe-through, shipped — Wave 151), BF-265 (transport strip, shipped — Wave 151), BF-266 (vision context folding, shipped — Wave 151), BF-267 (REVERTED 2026-05-11, commit `8b4b39f`)
**GH issues:** [#637 (AD-731)](https://github.com/seangalliher/ProbOS/issues/637), [#639 (AD-637z2)](https://github.com/seangalliher/ProbOS/issues/639) (auto-closes when this ships)
**Estimated tests:** ≥ 12 new (`tests/test_ad731_attachment_ref_wire_format.py`) + existing AD-730 + BF-265 + BF-266 suites must stay green with updated assertions where they assert on `base64` shape (those flip to `attachment_ref` shape)

---

## Captain decisions baked in

1. **Refs, not URLs.** Bus messages carry content-addressable SHA-256 refs to the existing `AttachmentStore`. NOT public URLs, NOT base64. This matches the universal pattern (Ray/Dask object refs, Erlang BEAM refs, IPFS, Git, OCI, MCP resource handles).
2. **Provider-agnostic ref shape on the wire; adapt at the LLM client.** The bus message format stays neutral. The Anthropic-shape base64 source block is reconstructed at the last moment inside the LLM client, immediately before the HTTP POST. We do not bind the bus to Anthropic's content-block schema.
3. **BF-265 transport strip becomes unnecessary and IS REVERTED in this AD.** When the wire payload is ~70 bytes per image instead of 150 KB-1 MB, the strip has no purpose. Removing it restores the uniform-NATS-transport invariant — AD-637z2 (#639) auto-closes.
4. **Single-host attachment store assumption (AD-731a Option A).** v1 assumes all agent processes share the same filesystem path. Multi-host distribution (HTTP fetch, NATS Object Store) is explicitly deferred to AD-731a forward markers ([#638](https://github.com/seangalliher/ProbOS/issues/638)).
5. **Graceful degrade on missing refs.** A missing attachment never crashes the LLM call. The image block is replaced with a `failed_to_load` text marker (existing pattern from `vision_dispatch._resolve_one`), warning logged, conversation continues.

---

## Problem (verified diagnostic baseline — 2026-05-11)

The Captain attached an image to a per-agent DM. Ezri (Counselor) responded: *"No image is coming through on my end, Captain — just the text of your message."* Reproduced twice (curl + HXI paperclip), two different images, identical response.

Root cause chain:
1. AD-730 packed Anthropic-shape `vision_messages` (containing inline base64 image bytes) into `IntentMessage.params['vision_messages']`.
2. NATS request/reply serialization triggered #636 (1 MB allocation failure) when retry buffers accumulated the inline base64.
3. BF-265 added `_TRANSPORT_STRIPPED_PARAM_KEYS = ("vision_messages",)` to `IntentBus._serialize_intent`, stripping the entire vision_messages payload before NATS transport. This fixed the crash but means the receiver's deserialized `IntentMessage` never has `vision_messages`. The agent's LLM call sees text only.
4. BF-267 attempted to fix this by bypassing NATS for local-process targets ("local-first dispatch"). It broke ALL DMs — including text — because the local handler is async and returns immediately (cognitive queue enqueue), so `await handler(intent)` returned `None`. Reverted (commit `8b4b39f`).

Today's state at HEAD: text DMs work; image DMs lose the image during NATS round-trip due to BF-265.

The architectural error is not BF-265 (the strip was a correct emergency response to OOM) and not BF-267 (the local-first idea was a wrong-direction reflex). The architectural error is **inline base64 in `IntentMessage.params`**. AD-730 should have referenced the already-existing `AttachmentStore` (shipped AD-720) instead of inlining bytes. This AD does what AD-730 should have done.

## Solution

Replace inline base64 with content-addressable refs on the wire. Bytes never cross the bus. Receiver dereferences from the local `AttachmentStore` immediately before the LLM HTTP call.

The store, the SHA-256 IDs, and the upload path already exist. This AD is plumbing, not new construction.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `src/probos/cognitive/vision_dispatch.py` | `build_multimodal_messages` emits `{"type":"image","source":{"type":"attachment_ref","sha256":"..."}}` instead of `{"type":"base64",...}`. Drop the `base64.b64encode` step. |
| `src/probos/cognitive/llm_client.py` | `OpenAICompatibleClient._call_openai` — before posting, walk `messages` content arrays and resolve any `attachment_ref` source to a base64 source block via the runtime's `AttachmentStore`. New method: `_resolve_attachment_refs_for_openai`. |
| `src/probos/mesh/intent.py` | Revert BF-265 strip: remove `_TRANSPORT_STRIPPED_PARAM_KEYS` class attribute and the strip branch in `_serialize_intent`. Keep the rest of `_serialize_intent` intact. |
| `src/probos/cognitive/llm_client.py` | `OpenAICompatibleClient.__init__` gains a new **keyword-only** parameter `attachment_store: AttachmentStore \| None = None` placed AFTER the existing `*, model_router=None`. Stored as `self._attachment_store`. None disables ref resolution (no-op pass-through). Dependency Inversion — depend on the Protocol, not `FilesystemAttachmentStore`. |
| `src/probos/runtime.py` | Add a public `attachment_store` property on `ProbOSRuntime` that returns `_get_attachment_store(self)` (the existing module-level helper in `routers/chat.py`). Update `routers/chat.py:_get_attachment_store` to remain available (the property delegates to it) — or move the cached store onto the runtime if cleaner. Builder's call: pick the smaller diff. |
| `src/probos/__main__.py` | Wire `attachment_store=runtime.attachment_store` (post-runtime-init) into both `OpenAICompatibleClient(...)` construction sites. Verified locations: line ~181 and line ~834. |
| `tests/test_ad731_attachment_ref_wire_format.py` | NEW — 12+ tests (see Section 5) |
| `tests/test_bf265_transport_stripped_params.py` | UPDATE — invert assertions: `vision_messages` no longer stripped; small refs survive NATS serialization. Keep tests as regression for "no inline base64 ever crosses serialization." |
| `tests/test_bf266_vision_context_folding.py` | VERIFY — `_enrich_vision_messages_with_context` still works on the new `attachment_ref` shape. The image-block detection in cognitive_agent.py uses `item.get("type") == "image"` which is shape-agnostic — should pass unchanged. Re-run to confirm. |
| `tests/test_ad730_agent_chat_vision.py` | UPDATE — assertions that inspect content blocks now expect `attachment_ref` source type. Tier routing, vision_tier health, fallback to text-only, and end-to-end flow logic unchanged. |
| `PROGRESS.md` | Status line + entry under Wave 152. |
| `DECISIONS.md` | Append AD-731 closure block. AD-637z2 (#639) auto-closes as part of this AD. |
| `docs/development/roadmap.md` | Mark AD-731 shipped. Mark AD-637z2 closed-as-part-of-AD-731. Keep AD-731a / AD-731a-1 (HTTP fetch) / AD-731a-2 (NATS Object Store) as forward markers. |

**Do NOT touch:**
- `src/probos/routers/agents.py` (the sender already calls `build_multimodal_messages`; the shape change happens inside it).
- `src/probos/routers/chat.py` (same — uses `build_multimodal_messages`, benefits automatically).
- BF-266 enrichment logic in `cognitive_agent.py`.
- The HXI / TypeScript UI (no wire format change at the HTTP boundary; UI still uploads via `/api/chat/attachments/multipart` and sends `attachment_ids`).
- `AgentChatRequest` model (no API change).

---

## Section 1 — Sender: emit attachment_ref shape

### 1a. Locate the current base64 emission

`src/probos/cognitive/vision_dispatch.py:117-127` (verified):

```python
        if mime.startswith("image/"):
            image_ids.append(attachment_id)
            data = base64.b64encode(blob).decode("ascii")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": data,
                },
            })
            continue
```

### 1b. Replace with ref shape

**SEARCH:**
```python
        if mime.startswith("image/"):
            image_ids.append(attachment_id)
            data = base64.b64encode(blob).decode("ascii")
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": data,
                },
            })
            continue
```

**REPLACE:**
```python
        if mime.startswith("image/"):
            image_ids.append(attachment_id)
            # AD-731: emit a content-addressable ref instead of inline base64.
            # The receiver dereferences from the local AttachmentStore inside
            # the LLM client immediately before the HTTP POST. This keeps the
            # bus message ~70 bytes per image instead of 150 KB-1 MB and
            # restores the uniform-NATS-transport invariant (AD-637z2).
            content.append({
                "type": "image",
                "source": {
                    "type": "attachment_ref",
                    "sha256": attachment_id,
                    "media_type": mime,
                },
            })
            continue
```

### 1c. Remove the now-unused `_resolve_one` blob read for image attachments

Image blocks no longer need `blob` — only the `mime`. Audit `_resolve_one` (lines 25-78):

- It still needs to call `store.read(attachment_id)` for non-image attachments (text extraction path).
- For image attachments, the `blob` is unused after this change.

Smallest safe change: keep `_resolve_one` unchanged (it always returns the blob). The image branch in `build_multimodal_messages` simply discards `blob`. This avoids touching the `_resolve_one` signature and its test surface.

**Trade-off acknowledged:** This reads the image blob from disk at sender time even though we no longer use it. Acceptable for v1 — local FS read of a small blob is microseconds. AD-731a-3 (forward marker) can add a mime-only fast path if profiling shows it matters.

### 1d. Drop the unused `base64` import if no other call sites remain in the file

Verify after the edit. If `base64.b64encode` is not used anywhere else in `vision_dispatch.py`, remove `import base64` from line 12 to keep imports clean. If it is used (e.g., `augment_prompt_with_attachment_text`), leave it.

---

## Section 2 — Receiver: resolve refs inside the LLM client

The live class is `OpenAICompatibleClient` (NOT `LLMClient` — that name does not exist). `BaseLLMClient` is the ABC; `MockLLMClient` subclasses it for tests. All vision flows through `OpenAICompatibleClient._call_openai`. The Ollama path (`_call_ollama_native`) builds messages from `system_prompt + prompt` only and never consumes `request.messages` — no resolution needed there.

### 2a. New constructor parameter on `OpenAICompatibleClient`

`src/probos/cognitive/llm_client.py`. The existing signature is:
```python
def __init__(self, base_url=..., api_key=..., models=None, timeout=30.0,
             default_tier=..., config=None, rate_config=None, *, model_router=None):
```
Add `attachment_store: AttachmentStore | None = None` as a new **keyword-only** parameter AFTER `model_router=None` (preserves all existing positional and keyword callers). Store as `self._attachment_store: AttachmentStore | None = attachment_store`. Default `None` preserves existing behavior for any test/caller that constructs without the store (Dependency Inversion + backward compatibility).

Type annotation must use the Protocol:
```python
from probos.attachments.store import AttachmentStore
```

### 2b. New method: `_resolve_attachment_refs_for_openai`

In `OpenAICompatibleClient`, add:

```python
async def _resolve_attachment_refs_for_openai(
    self, messages: list[dict]
) -> list[dict]:
    """AD-731: resolve ``attachment_ref`` source blocks to OpenAI/Anthropic-
    compatible base64 source blocks just before the HTTP POST.

    Walks each message's ``content`` array. For each image content block
    whose ``source.type == "attachment_ref"``, reads bytes from
    ``self._attachment_store`` and replaces the block with a ``base64``
    source. Other blocks pass through unchanged.

    Tier-2 log-and-degrade: a missing attachment is replaced with a
    ``failed_to_load`` text marker and a warning is logged. Never raises.

    Returns a NEW messages list — does not mutate the input.

    No-op when ``self._attachment_store is None`` (returns the input as-is).
    """
    if self._attachment_store is None:
        return messages
    import base64
    resolved_messages: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            resolved_messages.append(msg)
            continue
        new_content: list[dict] = []
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "image"
                and isinstance(block.get("source"), dict)
                and block["source"].get("type") == "attachment_ref"
            ):
                sha = block["source"].get("sha256", "")
                mime = block["source"].get("media_type", "")
                try:
                    blob = await self._attachment_store.read(sha)
                    new_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": base64.b64encode(blob).decode("ascii"),
                        },
                    })
                except FileNotFoundError:
                    logger.warning(
                        "AD-731: attachment_ref %s not found in store; "
                        "replacing image block with failed_to_load text marker",
                        sha[:16],
                    )
                    new_content.append({
                        "type": "text",
                        "text": (
                            f'<ATTACHMENT id="{sha}" mime="{mime}" '
                            f'note="failed_to_load_at_dereference" />'
                        ),
                    })
            else:
                new_content.append(block)
        resolved_messages.append({**msg, "content": new_content})
    return resolved_messages
```

### 2c. Wire into `_call_openai`

At `src/probos/cognitive/llm_client.py:671-672` (verified):

```python
        if request.messages is not None:
            messages = list(request.messages)
            if request.system_prompt and not (messages and messages[0].get("role") == "system"):
                messages.insert(0, {"role": "system", "content": request.system_prompt})
```

**SEARCH:**
```python
        if request.messages is not None:
            messages = list(request.messages)
            if request.system_prompt and not (messages and messages[0].get("role") == "system"):
                messages.insert(0, {"role": "system", "content": request.system_prompt})
```

**REPLACE:**
```python
        if request.messages is not None:
            messages = list(request.messages)
            # AD-731: resolve attachment_ref source blocks to base64 just
            # before the HTTP POST. No-op when attachment_store is unwired
            # (e.g., unit tests constructing LLMClient directly).
            messages = await self._resolve_attachment_refs_for_openai(messages)
            if request.system_prompt and not (messages and messages[0].get("role") == "system"):
                messages.insert(0, {"role": "system", "content": request.system_prompt})
```

### 2d. Ollama path needs no change

The second `messages` construction at `src/probos/cognitive/llm_client.py:~784` is inside `_call_ollama_native`. Verified: it builds messages from `request.system_prompt + request.prompt` ONLY and does not consume `request.messages`. Vision flows exclusively through `_call_openai`. No ref-resolution call is needed in the Ollama path.

---

## Section 3 — Revert BF-265 transport strip

### 3a. Locate the strip

`src/probos/mesh/intent.py:823-857` (verified).

### 3b. Remove the class attribute and strip branch

**SEARCH:**
```python
    # BF-265 / Wave 151 fallout: params keys whose values are large in-memory
    # transient data and must NEVER cross NATS transport. AD-730 added
    # vision_messages (base64 image bytes, often 150KB-1MB per attachment).
    # JetStream retries on these payloads accumulated buffers that contributed
    # to the 2026-05-11 memory-exhaustion crash (#636). Strip on serialize;
    # callers that need the data have in-process access via the original
    # IntentMessage object (the perception path uses observation.params not
    # the round-tripped NATS payload).
    _TRANSPORT_STRIPPED_PARAM_KEYS: tuple[str, ...] = (
        "vision_messages",  # AD-730 — base64 image content
    )

    @staticmethod
    def _serialize_intent(intent: IntentMessage) -> dict[str, Any]:
        """Serialize IntentMessage for NATS transport.

        All fields must be JSON-serializable. params dict values that are
        not JSON-serializable will raise TypeError — fail fast.

        BF-265: large in-process payloads (vision_messages, etc.) are
        stripped before transport. Receivers needing those payloads consume
        them in-process from the live IntentMessage object, not from the
        NATS-deserialized copy. The stripped-keys allowlist is the
        ``_TRANSPORT_STRIPPED_PARAM_KEYS`` class attribute.
        """
        params = intent.params
        if any(k in params for k in IntentBus._TRANSPORT_STRIPPED_PARAM_KEYS):
            # Build a stripped copy; original is untouched (caller keeps it).
            params = {
                k: v
                for k, v in params.items()
                if k not in IntentBus._TRANSPORT_STRIPPED_PARAM_KEYS
            }
            # Leave a marker so log/replay readers know data was stripped.
            params = dict(params)  # ensure mutable
            params["_transport_stripped"] = list(
                k for k in IntentBus._TRANSPORT_STRIPPED_PARAM_KEYS
                if k in intent.params
            )
        return {
            "intent": intent.intent,
            "params": params,
```

**REPLACE:**
```python
    @staticmethod
    def _serialize_intent(intent: IntentMessage) -> dict[str, Any]:
        """Serialize IntentMessage for NATS transport.

        All fields must be JSON-serializable. params dict values that are
        not JSON-serializable will raise TypeError — fail fast.

        AD-731 (2026-05-11): BF-265's transport strip removed. Vision
        attachments are now carried as content-addressable refs (~70 bytes
        per image) instead of inline base64. The receiver dereferences from
        the local AttachmentStore inside the LLM client. The bus carries
        only refs; payload size is bounded; the uniform-NATS-transport
        invariant is restored. AD-637z2 closes as part of this AD.
        """
        return {
            "intent": intent.intent,
            "params": intent.params,
```

The closing `}` and remaining fields of the dict are unchanged.

### 3c. Federation strip — leave intact, add forward-marker comment

Verified: [src/probos/federation/bridge.py](src/probos/federation/bridge.py#L113) already has its own local `_stripped_keys = ("vision_messages",)` constant. It does NOT reference `IntentBus._TRANSPORT_STRIPPED_PARAM_KEYS`. Removing the IntentBus constant breaks nothing on the federation side.

Action: leave federation/bridge.py's `_stripped_keys` and its strip behavior intact. Add a one-line comment above the constant referencing AD-731a:

```python
# AD-731a forward marker (#638): cross-mesh attachment distribution unsolved.
# Receiving meshes may not have the local AttachmentStore, so strip
# vision_messages from federation transport until AD-731a-1 (HTTP fetch) or
# AD-731a-2 (NATS Object Store) ships. In-mesh delivery uses attachment_ref
# shape (AD-731) which is small enough to cross NATS safely.
_stripped_keys = ("vision_messages",)
```

Do a final grep for `_TRANSPORT_STRIPPED_PARAM_KEYS` and `_transport_stripped` to confirm no other readers exist. If any tests reference these symbols, update them per Section 5b.

---

## Section 4 — Wire the attachment store into `OpenAICompatibleClient` construction

Verified: there is no `runtime.attachment_store` property today. The only accessor is the module-level `_get_attachment_store(runtime)` helper in [src/probos/routers/chat.py](src/probos/routers/chat.py#L505) with a per-runtime `_ATTACHMENT_STORE_CACHE`.

### 4a. Promote to public runtime property

In `src/probos/runtime.py`, add a public `attachment_store` property on `ProbOSRuntime`:

```python
@property
def attachment_store(self) -> "AttachmentStore":
    """AD-731: public accessor for the runtime's content-addressable
    attachment store. Delegates to the cached helper in routers/chat.py
    so the per-runtime cache stays in one place.
    """
    from probos.routers.chat import _get_attachment_store
    return _get_attachment_store(self)
```

Keep `routers/chat.py:_get_attachment_store` intact (the property delegates to it). The existing `routers/chat.py` and `routers/agents.py` call sites can stay as they are — promotion is additive.

### 4b. Wire into both `OpenAICompatibleClient` construction sites

Verified construction sites (do not re-grep — these are exact):
- [src/probos/__main__.py](src/probos/__main__.py#L181): `client = OpenAICompatibleClient(config=cog, rate_config=config.llm_rate)`
- [src/probos/__main__.py](src/probos/__main__.py#L834): `client = OpenAICompatibleClient(config=cfg.cognitive)`

Both need `attachment_store=runtime.attachment_store` added. Note that at line 181 the `runtime` object may not yet be constructed at that point — Builder must verify ordering and wire it AFTER `ProbOSRuntime` is constructed (line numbers may have shifted). If the LLM client is constructed BEFORE the runtime, wire it with a deferred setter (`client.set_attachment_store(runtime.attachment_store)` — add the setter alongside the constructor parameter) OR restructure init so the store is available first. Builder picks the smaller diff.

### 4c. Test-only construction sites

Any test that constructs `OpenAICompatibleClient` directly without an `attachment_store` gets `None` by default and the ref-resolution becomes a no-op (Section 2b). Existing tests do not need to be updated unless they specifically test vision flow.

---

## Section 5 — Tests (≥ 12 new in `tests/test_ad731_attachment_ref_wire_format.py`)

Required coverage. Each test = one behavior. Use `pytest-asyncio`, `tmp_path`, `_Fake*` stubs. No mock chains where a real `FilesystemAttachmentStore` over `tmp_path` will do.

1. **`test_build_multimodal_messages_emits_attachment_ref_shape`** — `build_multimodal_messages` with one image returns a content block with `source.type == "attachment_ref"`, `source.sha256 == attachment_id`, `source.media_type == "image/png"`. No `data` field, no base64.
2. **`test_build_multimodal_messages_text_attachment_unchanged`** — non-image attachment (e.g., `text/plain`) still produces the existing text-extraction content block. No regression.
3. **`test_build_multimodal_messages_mixed_image_and_text`** — array contains one image (ref shape) and one text-extracted block in correct order.
4. **`test_llm_client_resolves_attachment_ref_to_base64_pre_post`** — construct `LLMClient` with a real `FilesystemAttachmentStore` over `tmp_path`, write a known PNG blob, call `_resolve_attachment_refs_for_openai` with a single-image message. Result: source becomes `base64`, `data` decodes to the original blob bytes, `media_type` preserved.
5. **`test_llm_client_resolves_missing_ref_to_failed_to_load_marker`** — same setup but the SHA does not exist on disk. Result: image block replaced with `{"type":"text", "text": "<ATTACHMENT id=... note=\"failed_to_load_at_dereference\" />"}`. No exception. Warning logged.
6. **`test_llm_client_resolves_no_op_when_store_is_none`** — construct `LLMClient` with `attachment_store=None`. Call `_resolve_attachment_refs_for_openai` with a ref-bearing message. Result: messages returned unchanged (no resolution attempted, no exception).
7. **`test_llm_client_resolves_does_not_mutate_input`** — input messages list/dicts unchanged after the call (deep equality assertion on a deep-copied baseline).
8. **`test_llm_client_resolves_passes_through_non_ref_blocks`** — message with a `text` block and a `tool_use` block: both pass through untouched.
9. **`test_intent_bus_serialize_no_longer_strips_vision_messages`** — `IntentBus._serialize_intent(intent_with_vision_messages_refs)` round-trips `vision_messages` intact. No `_transport_stripped` marker.
10. **`test_intent_bus_serialize_size_bound_with_refs`** — construct an IntentMessage with 5 ref-shape image blocks. Assert `len(json.dumps(IntentBus._serialize_intent(intent))) < 2048`. Then construct one with 10 ref-shape image blocks and assert `< 4096`. Documents the size-bounded invariant — refs scale linearly at ~70-100 bytes per image plus message overhead.
11. **`test_end_to_end_vision_dm_with_real_store`** — integration: write a PNG to a real `FilesystemAttachmentStore` over `tmp_path`. Build vision_messages with ref shape. Construct an `OpenAICompatibleClient` with the store wired in. Capture the outgoing HTTP payload by monkeypatching `httpx.AsyncClient.post` (the class creates its own `httpx.AsyncClient` instances internally — no public transport-injection seam). Submit an `LLMRequest(messages=vision_messages)`. Assert the captured payload contains a `base64` source whose `data` decodes to the original PNG bytes.
12. **`test_federation_bridge_still_strips_vision_messages_v1`** — verify the federation strip is preserved as a deliberate forward-marker (AD-731a). Pin the current behavior so a future AD-731a-1 / AD-731a-2 has a regression target to flip.

### 5b. Existing test updates

- `tests/test_bf265_transport_stripped_params.py` — **invert assertions.** `vision_messages` is no longer stripped; instead, assert `vision_messages` survives round-trip. Rename to `tests/test_ad731_no_inline_base64_in_bus.py` if the file's identity is now "no inline base64 ever crosses serialization." Keep at least one test that asserts "if someone re-introduces inline base64 in vision_messages content blocks, the size-bound assertion fires" — this is the regression sentinel for the original mistake.
- `tests/test_bf266_vision_context_folding.py` — re-run only. The image-block detection uses `item.get("type") == "image"` which is shape-agnostic. Should pass unchanged. If any test asserts `source.type == "base64"`, update to `attachment_ref`.
- `tests/test_ad730_agent_chat_vision.py` — update any assertions that inspect `source.type` or `source.data`. The routing logic (tier check, vision-tier fallback to text-only, etc.) is unchanged.

### 5c. Test gates

After Section 1 (sender shape change): run `pytest tests/test_ad731* tests/test_ad730* tests/test_bf26* -q`. Expect Section 5b updates needed before green.
After Section 2 (receiver resolution): full vision suite green.
After Section 3 (BF-265 revert): `pytest tests/test_intent.py -q` + full vision suite. The BF-265 strip-removal must not break NATS serialization of plain DMs.
After Section 4 (wiring): boot the full runtime via the existing integration test harness, send a DM with an image via the test API, assert the LLM client received a base64 payload. If no such harness exists, an end-to-end test in `test_ad731*.py` using `_FakeLLMTransport` is sufficient.

Final gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`. All pre-existing tests must remain green.

---

## Section 6 — Observability

- `vision_dispatch.build_multimodal_messages` — log at `info`: `"AD-731: emitting %d attachment_ref block(s) for vision DM (total wire size ~%d bytes)"` after building the message. This makes the wire-size delta visible in logs.
- `LLMClient._resolve_attachment_refs_for_openai` — log at `info` when refs are resolved: `"AD-731: resolved %d attachment_ref(s) to base64 for %s tier"`. Log at `warning` for each missing ref (already specified above).
- No new EventType. No HXI surface change.

---

## Section 7 — Documentation

- `DECISIONS.md` — append AD-731 closure block. Include: problem, decision (refs not URLs not base64), why (industry pattern; named comparisons: Anthropic API source types, Ray object refs, Erlang BEAM refs, MCP resources, Git, IPFS), what's deferred (AD-731a Options B/C). Reference AD-637z2 as auto-closed.
- `PROGRESS.md` — Wave 152 entry. Confirm test count delta. Note BF-265 reverted as part of AD-731 (transport strip no longer needed). Note AD-637z2 closed.
- `docs/development/roadmap.md` — Mark AD-731 shipped. Mark AD-637z2 closed-as-part-of-AD-731 (#639). AD-731a remains open as parent forward marker, with three sub-markers:
  - AD-731a-1: HTTP fetch distribution for cross-host single-tenant
  - AD-731a-2: NATS Object Store distribution for federation
  - AD-731a-3 (optional): mime-only fast path in sender (skip blob read for image attachments)
- `.github/copilot-instructions.md` — add a new bullet under "Common Review Flags": *"Inline blob in IntentMessage.params: ANY new code path that puts >4 KB into IntentMessage.params should be flagged. Use a content-addressable ref to AttachmentStore (AD-731 pattern). The bus carries refs; the store carries bytes."*

---

## Engineering Principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`. Specifically:

- **Single Responsibility**: `_resolve_attachment_refs_for_openai` is a single-purpose helper. `_serialize_intent` is simpler after the BF-265 revert, not more complex.
- **Dependency Inversion**: `LLMClient` depends on the `AttachmentStore` Protocol, not on `FilesystemAttachmentStore`.
- **Defense in Depth**: ref resolution validates both `source.type == "attachment_ref"` AND `isinstance(source, dict)` before reading.
- **Fail Fast / Log-and-Degrade**: missing attachments hit the Tier-2 path (log warning, replace with marker, continue). Never raise into the LLM call.
- **Cloud-Ready Storage**: the receiver uses the existing Protocol seam. Commercial overlay's S3-backed store works without code change.
- **Async hygiene**: no `create_task` introduced. `_resolve_attachment_refs_for_openai` is async because `store.read` is async.
- **Type annotations**: new public method `_resolve_attachment_refs_for_openai` is fully typed.
- **Logging quality**: each log line includes what failed, what the system did about it, and (where relevant) the SHA prefix for correlation.

---

## Out of scope (explicit Do-Not-Build list)

- **Do not build HTTP fetch for cross-host attachment distribution.** That is AD-731a-1 (#638 sub-marker).
- **Do not build NATS Object Store integration.** That is AD-731a-2 (#638 sub-marker).
- **Do not change the federation strip behavior.** Cross-mesh attachment distribution is unsolved; the strip is a deliberate forward-marker.
- **Do not change the HTTP API.** `AgentChatRequest` and `/api/agent/{id}/chat` are unchanged.
- **Do not change the HXI UI.** The paperclip + upload flow stays exactly as it is.
- **Do not refactor `LLMClient` beyond the constructor parameter and the new helper.** No tier system changes, no retry logic changes, no health-probe changes.
- **Do not re-introduce local-first dispatch (BF-267 pattern).** The fix is the wire format, not the transport.
- **Do not bind the bus message format to Anthropic's content-block schema.** The `attachment_ref` shape is internal and provider-agnostic. Adaptation happens at the LLM client.

---

## Acceptance criteria

- ✅ Sender (`build_multimodal_messages`) emits `attachment_ref` shape for image content blocks. Zero `base64.b64encode` calls remain in the sender path.
- ✅ Receiver (`LLMClient._resolve_attachment_refs_for_openai`) dereferences refs to base64 immediately before the HTTP POST.
- ✅ BF-265 transport strip removed from `IntentBus._serialize_intent`. NATS payload size for a 10-image vision DM stays < 4 KB.
- ✅ AD-637z2 (#639) auto-closes as part of this AD. PR description must include `Closes #637` and `Closes #639`.
- ✅ End-to-end test: a real PNG written to a real FilesystemAttachmentStore round-trips through the full IntentMessage → NATS-serialize → deserialize → LLMClient resolve → captured-payload pipeline. The captured payload's base64 decodes to the original PNG bytes.
- ✅ Federation strip preserved with explicit AD-731a forward-marker comment.
- ✅ All pre-existing tests green: `pytest tests/ -q -n 4 --dist=loadfile`.
- ✅ Manual smoke test post-merge: restart HXI, paperclip-upload a fresh image, send to Ezri. Expected reply: an accurate visual description (colors, shapes, content). NOT "I don't see an image."
- ✅ `DECISIONS.md` AD-731 entry includes the industry-comparison citations (Ray, Erlang, MCP, Anthropic API source types, Git, IPFS) and explicit reference to the user-memory lesson under "Don't change the architecture to fix a symptom (2026-05-11)".
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Builder notes

- **Pre-flight already done by Architect (2026-05-11):** all file paths, line numbers, function signatures, and protocol shapes verified against HEAD. Cross-reference before each edit if HEAD has moved.
- **Commit shape:** one commit per Section (Sections 1-4 + tests + docs). Use the AD-731 prefix on every commit. Final commit message must include `Closes #637\nCloses #639`.
- **If you discover a Section is no-op at HEAD** (e.g., the runtime already has `runtime.attachment_store` as a property), mark the Section's commit as `verify-only: <reason>` and move on. Do not invent work.
- **If you discover a phantom API in this prompt during build, STOP** and report. Do not silently work around it — the verify-first principle in user memory means the Architect needs to know.
