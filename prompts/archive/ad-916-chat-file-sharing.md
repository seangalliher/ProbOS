# AD-916 — File Sharing in Group Chat (refs-not-blobs)

**Epic:** Ad-hoc Crew Collaboration (group chat → meeting)
**Status:** Ready to build · **Target repo:** OSS (`d:\ProbOS`)
**Depends on:** AD-914 (group fan-out, `routers/thread_fanout.py`), AD-731 (refs-not-blobs vision pipeline), AD-720/AD-730 (AttachmentStore + vision dispatch).
**Current highest committed AD:** AD-915 (`468fb301`).
**Estimated tests:** +16 (`tests/test_ad916_chat_file_sharing.py`), floor ≥ 14.

---

## One-line summary

A chat message carries **content-addressable attachment refs** (SHA-256, AD-731 refs-not-blobs) persisted on `chat_thread_messages.metadata`; in the AD-914 group fan-out, a **vision-capable** participant receives the image refs through `IntentMessage.params["vision_messages"]` (the existing AD-730/731 vision pipe). Bytes are stored **once** in the `AttachmentStore` (by the existing upload endpoint) and referenced by SHA-256 everywhere else.

---

## Problem

AD-914 fans the Captain's turn out to all crew-agent participants, but the fan-out intent only carries `text` + `session_history` (verified `thread_fanout.py:199-210`). There is no way to share a file in a group chat:

- The thread message row has a `metadata` JSON column (`threads/__init__.py:64`, `chat_thread_messages.metadata TEXT`) but nothing writes attachment refs into it.
- `AppendMessageRequest` (`routers/threads.py:64-68`) has only `author_id / role / body / metadata` — no `attachment_ids`.
- The proven per-agent DM vision path (`routers/agents.py:1850-2010`) threads images via `IntentMessage.params["vision_messages"]`, but that path is `/api/agent/{id}/chat`-only; the group fan-out never builds a vision array.

The infrastructure to do this correctly already exists and must be **reused, not reinvented**:

- `AttachmentStore` content-addressable blob store (AD-720) with the upload defense-in-depth chain (AD-720a).
- `build_multimodal_messages` (AD-730) emits exactly the AD-731 `attachment_ref` image-block shape the LLM client resolves.
- `cognitive_agent.py` already routes `params["vision_messages"]` through the vision tier.

AD-916 wires these together for the group-chat substrate. **v1 = persist refs + thread image refs to vision participants; non-image = stored + referenced + link-only.**

---

## Verified context (file:line — grepped live, not from memory)

### AttachmentStore — exact signatures
- `src/probos/attachments/store.py:38-56` — `async def write(self, content_hash: str, blob: bytes, mime: str, *, origin: str = "chat_attachment") -> Path` (idempotent; `chat_attachment` origin never sweeps by age).
- `store.py:58` — `async def read(self, content_hash: str) -> bytes` (raises `FileNotFoundError` if absent).
- `store.py:62` — `async def exists(self, content_hash: str) -> bool`.
- `src/probos/attachments/filesystem_store.py:359` — `async def mime_for(self, content_hash: str) -> str | None` (the mime lookup the vision path uses; **not** on the `Protocol`, lives on `FilesystemAttachmentStore`).

### Two store accessors (use `_get_attachment_store` for consistency with the proven path)
- `src/probos/routers/chat.py:757` — `def _get_attachment_store(runtime) -> Any` — lazy per-runtime `FilesystemAttachmentStore` cache (`_ATTACHMENT_STORE_CACHE`, keyed by `id(runtime)`). This is what the **working** vision DM path uses (`routers/agents.py` `_mime_lookup` → `store.mime_for`).
- `runtime.attachment_store` also exists (`__main__.py:483` `llm_client.set_attachment_store(runtime.attachment_store)`; `routers/crew_tasks.py:51` `store = runtime.attachment_store`). Both resolve to the **same on-disk root** (`_resolve_attachments_dir(cfg.attachments_dir)`), so a SHA written via one is readable via the other. **AD-916 uses `_get_attachment_store(runtime)`** (lazy import, mirrors `agents.py`) so the produced `attachment_ref` blocks resolve identically to the proven DM path.

### Existing upload path (reuse — do NOT add a new blob path)
- `chat.py:772` — `async def _validate_and_store_attachment(runtime, blob, declared_mime, declared_filename, declared_hash_or_None, *, origin="chat_attachment") -> tuple[bool, dict]` — feature gate → MIME allowlist → size cap → sha256 → magic-byte validate → idempotent `store.write`. Returns `{"attachment_id": <sha>, "url": "/api/chat/attachments/<sha>", "mime", "size_bytes", "sha256"}`.
- Endpoints `POST /api/chat/attachments` (JSON+base64) and `/multipart` already store bytes once and return the SHA. **AD-916 references already-uploaded SHAs** (same contract as `agents.py` `req.attachment_ids`); it does NOT re-validate bytes (the "stored once" invariant). It only resolves SHA → mime via `mime_for` + persists the ref.

### Config (AttachmentsConfig — fields confirmed)
- `config.py:2098` `class AttachmentsConfig` — `enabled`, `max_attachment_bytes` (`:2109`), `allowed_mime_types` (`:2110`), `vision_tier="vision"` (`:2139`), `text_extraction_max_bytes` (`:2141`), `pdf_extraction_enabled` (read by `agents.py` / `vision_dispatch.py`). No new config field needed.

### Vision pipeline (AD-730/731 — the reusable atoms)
- `src/probos/cognitive/vision_dispatch.py:160` — `async def build_multimodal_messages(prompt, attachment_ids, store, mime_lookup, *, text_extraction_max_bytes, pdf_extraction_enabled) -> tuple[messages, image_ids, per_attachment]`.
- `vision_dispatch.py:244-251` — image block shape it emits (AD-731 / BF-278): `{"type": "image", "source": {"type": "attachment_ref", "sha256": <sha>, "media_type": <mime>}}`.
- `src/probos/cognitive/llm_client.py:878` `_resolve_attachment_refs_for_openai` — at `:919` matches `source.type == "attachment_ref"`, reads bytes from `self._attachment_store` (= `runtime.attachment_store`), emits OpenAI `image_url` data-URL just before POST.
- `src/probos/cognitive/cognitive_agent.py:2451` — `_vision_messages = observation.get("params", {}).get("vision_messages")`; when present → `LLMRequest(prompt="", messages=_enriched_messages, system_prompt=composed, tier=vision_tier)`. **The agent side already consumes `params["vision_messages"]`** — AD-916 only has to populate it.
- `routers/agents.py:1963-1972` — the `vision_capable` gate to mirror: `_prof = runtime.callsign_registry.get_profile(agent.agent_type)`; `if not (_prof or {}).get("vision_capable", False): image_ids = []`.
- `src/probos/crew_profile.py:765` — `def get_profile(self, agent_type: str) -> dict | None` (returns `{"display_name", "department", "vision_capable"}`).

### Group fan-out (the wiring seam)
- `src/probos/routers/thread_fanout.py:147` `async def group_chat_fanout(runtime, thread_id, *, captain_body, captain_msg)`.
- `thread_fanout.py:191` `async def _send_one(agent_id)` resolves `agent = runtime.registry.get(agent_id)` for callsign, then `thread_fanout.py:199-210` builds `IntentMessage(intent="direct_message", params={"text","from","session","session_history"}, target_agent_id=agent_id, ttl_seconds=60.0, thread_id=thread_id)`.

### ChatThreadStore message + metadata (no schema change needed)
- `threads/__init__.py:64` — `chat_thread_messages.metadata TEXT` (JSON dict) column already exists.
- `threads/__init__.py:649` — `def append_message(self, thread_id, *, author_id, role, body, metadata=None) -> ChatThreadMessage | None` (serializes `metadata` to JSON).
- `threads/__init__.py:135-146` — `ChatThreadMessage.to_dict()` returns `"metadata": dict(self.metadata)` → refs survive `to_dict()` / `GET /messages` for free.
- `routers/threads.py:212-271` — `POST /{thread_id}/messages`: appends, then (`:254-271`) on `role=="captain"` AND ≥2 crew participants calls `group_chat_fanout`.

### Refs-in-metadata precedent (the "store-once, ref-by-SHA in a metadata column" pattern)
- `threads/__init__.py:758` — `projects.pinned_attachment_ids: list[str]` — JSON list of SHA-256 refs persisted in a metadata-shaped column (AD-793).
- `avatars/render_verification.py:281` — threads bytes as `attachment_ids=[backend_render_ref]` (SHA-256 ref, AD-731 invariant). **NOTE:** the requested "Ward Room attach backend" does not exist as a distinct backend; this AD-720/731 store + `pinned_attachment_ids` JSON-refs pattern is the real precedent.

---

## Solution

`metadata.attachments = [{"content_hash": <sha256>, "mime": <mime>}]` on the message row (a list of refs, never blobs). Three small wirings + one request-model field, all Tier-2 log-and-degrade:

1. **Persist refs** — `AppendMessageRequest.attachment_ids`; the `POST /messages` handler resolves each SHA → `{content_hash, mime}` via `mime_for` and folds them into `metadata.attachments` **before** `append_message`. No store schema change (reuses the existing `metadata` column).
2. **Build the group vision array** — a helper reads `captain_msg.metadata["attachments"]`, filters image mimes, and calls `build_multimodal_messages` (the exact AD-731 block shape) to produce `vision_messages`.
3. **Thread to vision participants only** — `group_chat_fanout._send_one` adds `params["vision_messages"]` for participants whose `get_profile(agent_type)["vision_capable"]` is True (mirrors the `agents.py:1963` gate). Non-vision participants are byte-identical to AD-914.

Non-image attachments are persisted + referenced (link-only via `metadata.attachments`, served by the existing `GET /api/chat/attachments/{sha}`); they are **not** threaded into agent prompts in v1.

---

## Implementation

### Section 1 — `AppendMessageRequest.attachment_ids` (`routers/threads.py`)

Add the field (mirrors `api_models.py:157` `attachment_ids: list[str] = Field(default_factory=list)`):

```python
class AppendMessageRequest(BaseModel):
    author_id: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., pattern="^(captain|agent|system)$")
    body: str = Field(..., min_length=1)
    metadata: dict | None = None
    # AD-916: SHA-256 refs of attachments already uploaded via
    # POST /api/chat/attachments. Resolved to metadata.attachments on append.
    attachment_ids: list[str] = Field(default_factory=list)
```

> `body` stays `min_length=1` — an image-only message must carry at least a caption/space. v1 constraint; the AD-917 UI defaults the caption.

### Section 2 — resolve refs at append time (`routers/threads.py`, `POST /{thread_id}/messages`)

`append_message` currently calls `store.append_message(..., metadata=body.metadata)` (`threads.py:219-225`). Replace that single call with ref-resolution + merge **before** the append. Tier-2: a SHA not in the store is skipped (logged), attachments-disabled is a no-op, any failure degrades to the plain message.

```python
    store = _get_store(runtime)
    _meta = dict(body.metadata or {})
    if body.attachment_ids:
        try:
            cfg_attach = getattr(runtime.config, "attachments", None)
            if cfg_attach is not None and getattr(cfg_attach, "enabled", False):
                from probos.routers.chat import _get_attachment_store
                from probos.routers.thread_fanout import resolve_attachment_refs
                refs = await resolve_attachment_refs(
                    _get_attachment_store(runtime), body.attachment_ids
                )
                if refs:
                    _meta["attachments"] = refs
        except Exception:
            logger.warning(
                "AD-916: attachment ref resolution failed for thread=%s; "
                "persisting message without attachment refs",
                thread_id, exc_info=True,
            )
    msg = store.append_message(
        thread_id,
        author_id=body.author_id,
        role=body.role,
        body=body.body,
        metadata=_meta,
    )
```

(Lazy `import` of `_get_attachment_store` avoids a `chat.py`↔`threads.py` module-load cycle — same lazy pattern `agents.py` uses.)

### Section 3 — two helpers in `routers/thread_fanout.py`

Both take the store **explicitly** (Dependency Inversion → unit-testable with a real `FilesystemAttachmentStore(tmp_path)`, no cache-seeding). Tier-2 throughout.

```python
async def resolve_attachment_refs(store: Any, attachment_ids: list[str]) -> list[dict[str, str]]:
    """AD-916: resolve already-uploaded SHA-256 attachment_ids to persisted
    ref records ``{"content_hash", "mime"}``. An id absent from the store
    (``mime_for`` returns None) is skipped with a warning — never raises,
    never fabricates a mime. Order-preserving."""
    refs: list[dict[str, str]] = []
    for aid in attachment_ids:
        try:
            mime = await store.mime_for(aid)
        except Exception:
            logger.warning("AD-916: mime lookup failed for attachment %s; skipping", aid, exc_info=True)
            continue
        if not mime:
            logger.warning("AD-916: attachment %s not found in store; skipping ref", aid)
            continue
        refs.append({"content_hash": aid, "mime": mime})
    return refs


async def build_chat_vision_messages(
    store: Any, cfg_attach: Any, prompt: str, attachments: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """AD-916: build the AD-730/731 ``vision_messages`` array from the IMAGE
    subset of persisted attachment refs. Returns None when there are no image
    refs (so the caller falls back to the AD-914 text-only fan-out). Reuses
    ``build_multimodal_messages`` → the emitted blocks are the exact AD-731
    ``attachment_ref`` shape the LLM client resolves. Tier-2: any failure
    returns None (text-only)."""
    image_shas = [
        a["content_hash"] for a in attachments
        if str(a.get("mime", "")).startswith("image/") and a.get("content_hash")
    ]
    if not image_shas:
        return None
    try:
        from probos.cognitive.vision_dispatch import build_multimodal_messages

        async def _mime_lookup(content_hash: str) -> str | None:
            return await store.mime_for(content_hash)

        messages, image_ids, _ = await build_multimodal_messages(
            prompt=prompt,
            attachment_ids=image_shas,
            store=store,
            mime_lookup=_mime_lookup,
            text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
            pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
        )
    except Exception:
        logger.warning("AD-916: vision_messages build failed; text-only fan-out", exc_info=True)
        return None
    return messages if image_ids else None
```

### Section 4 — thread image refs into the fan-out (`thread_fanout.py:group_chat_fanout`)

Build the vision array **once** before `_send_one` (between the facilitator block and `_send_one`’s definition), then gate it per participant inside `_send_one`. Reuse the `agent` already resolved for the callsign — do NOT re-fetch.

Build once (Tier-2; `[]`/no-image → `None` → AD-914 path unchanged):

```python
    # AD-916: build the group vision array once from the Captain message's
    # persisted attachment refs. None => no image refs => AD-914 text-only.
    vision_messages: list[dict[str, Any]] | None = None
    try:
        _attachments = (getattr(captain_msg, "metadata", None) or {}).get("attachments") or []
        _cfg_attach = getattr(getattr(runtime, "config", None), "attachments", None)
        if _attachments and _cfg_attach is not None and getattr(_cfg_attach, "enabled", False):
            from probos.routers.chat import _get_attachment_store
            vision_messages = await build_chat_vision_messages(
                _get_attachment_store(runtime), _cfg_attach, captain_body, _attachments
            )
    except Exception:
        logger.warning(
            "AD-916: group vision build failed for thread=%s; text-only fan-out",
            thread_id, exc_info=True,
        )
        vision_messages = None
```

Inside `_send_one`, change the `params` to a local dict and gate the vision key on the participant's `vision_capable` profile (mirrors `agents.py:1963-1972`):

```python
        params: dict[str, Any] = {
            "text": captain_body,
            "from": "hxi_profile",
            "session": bool(session_history),
            "session_history": session_history,
        }
        # AD-916: only vision-capable participants receive image refs. The
        # ``agent`` above was already resolved for the callsign — reuse it.
        if vision_messages is not None:
            try:
                prof = (
                    runtime.callsign_registry.get_profile(agent.agent_type)
                    if (agent is not None and hasattr(runtime, "callsign_registry"))
                    else None
                )
                if (prof or {}).get("vision_capable", False):
                    params["vision_messages"] = vision_messages
            except Exception:
                logger.debug("AD-916: vision_capable gate failed for %s", agent_id, exc_info=True)
        intent = IntentMessage(
            intent="direct_message",
            params=params,
            target_agent_id=agent_id,
            ttl_seconds=60.0,
            thread_id=thread_id,
        )
```

> The agent-side consumer (`cognitive_agent.py:2451`) already routes `params["vision_messages"]` through the configured vision tier — no agent-side change.

---

## Tests — `tests/test_ad916_chat_file_sharing.py`

**BF-287 discipline:** real `FilesystemAttachmentStore(tmp_path)` (write a valid 1×1 PNG with correct magic bytes + a `text/plain` blob, capture their real sha256), real `ChatThreadStore(tmp_path)`, real `IntentBus(SignalManager(reap_interval=1.0))`, real-but-fake registry/callsign stubs (extend the AD-914 `_FakeCallsigns` with `get_profile(agent_type) -> {"vision_capable": ...}`; **no `MagicMock`** at the store/bus boundary). Use the AD-914 recording-handler pattern to assert `intent.params`. For `group_chat_fanout` end-to-end cases, seed `chat._ATTACHMENT_STORE_CACHE[id(runtime)] = <real tmp store>` so `_get_attachment_store(runtime)` returns the tmp store. REST cases mount the real `threads` router via `dependency_overrides[get_runtime]` (mirror AD-914).

Required cases (≥14; 16 named):

1. `test_resolve_attachment_refs_roundtrip` — write PNG → `resolve_attachment_refs([png_sha])` == `[{"content_hash": png_sha, "mime": "image/png"}]`.
2. `test_resolve_attachment_refs_missing_id_skipped` — unknown sha → `[]`.
3. `test_resolve_attachment_refs_empty_list` — `[]` → `[]`.
4. `test_resolve_attachment_refs_mixed_image_and_text` — `[png_sha, txt_sha]` → two refs with correct mimes, order preserved.
5. `test_message_to_dict_carries_attachments` — `append_message(metadata={"attachments": [...]})` → `to_dict()["metadata"]["attachments"]` round-trips (survives JSON persist + reload).
6. `test_append_message_persists_attachments_metadata` (REST) — `POST /messages` with `attachment_ids=[png_sha]` → `GET /messages` → message `metadata.attachments == [{content_hash, mime}]`.
7. `test_append_message_no_attachment_ids_metadata_unchanged` (REST) — POST without `attachment_ids` → no `attachments` key (AD-914/791 byte-identical).
8. `test_append_message_unknown_attachment_id_skipped` (REST) — `attachment_ids=["00"*32]` → message persisted, no `attachments` key (Tier-2 skip, no 500).
9. `test_build_chat_vision_messages_image_present` — image ref → messages contain a block `{"type":"image","source":{"type":"attachment_ref","sha256": png_sha,"media_type":"image/png"}}`.
10. `test_build_chat_vision_messages_non_image_returns_none` — only `text/plain` ref → `None`.
11. `test_build_chat_vision_messages_no_attachments_returns_none` — `[]` → `None`.
12. `test_build_chat_vision_messages_text_block_carries_caption` — the text block of `messages[0]["content"]` == `captain_body`.
13. `test_group_chat_fanout_vision_participant_gets_image_ref` — 2 crew, one `vision_capable=True`; captain_msg metadata has png ref → the vision agent's recorded `intent.params["vision_messages"]` carries the `attachment_ref` block with `png_sha`.
14. `test_group_chat_fanout_non_vision_participant_no_vision_messages` — `vision_capable=False` agent → `"vision_messages"` NOT in its `intent.params` (AD-914 params byte-identical).
15. `test_group_chat_fanout_non_image_attachment_link_only` — captain_msg metadata has a `text/plain` ref → NO `vision_messages` for any participant; the ref is still readable from the store (link-only) and present on the persisted message.
16. `test_group_chat_fanout_attachments_disabled_no_vision` — `cfg.attachments.enabled=False` → no `vision_messages` even with an image ref + vision-capable agent.

---

## What this does NOT change / Do NOT build

- **No PDF/doc/text extraction** — non-image attachments are stored + referenced + link-only. (`build_chat_vision_messages` passes only image SHAs; the `pdf_extraction_enabled` path is never hit.)
- **No new blob store** — reuse `AttachmentStore` / `_get_attachment_store`. Bytes are uploaded once via the existing `POST /api/chat/attachments` endpoints; AD-916 only references stored SHAs.
- **No UI drag-drop / paste / preview** — that is AD-917 (UI group-chat experience).
- **No agent-initiated attachments** — agents do not attach files in v1 (AD-918 territory).
- **No new store method or schema migration** — refs live in the existing `chat_thread_messages.metadata` JSON column.
- **No new config field** — reuse `AttachmentsConfig`.
- **No `IntentMessage` / `BaseAgent` protocol change** — `params["vision_messages"]` is the established AD-730 key.
- **No AD-730-2 image hard-cap/downscale/budget in the fan-out** — those are the `agents.py` DM-side enforcer; v1 group fan-out passes images through (Captain controls the attach). Forward marker for a later AD if group attachments need the same gates.
- **Do NOT touch** the `chat.py` AD-719 @-mention branch, the AD-914 history-injection / facilitator logic, or `cognitive_agent.py` vision consumer.
- **1:1 threads** (single crew participant) only persist the ref (link-only) — their vision dispatch is the existing AD-720/730 `/api/agent/{id}/chat` path, untouched here.

---

## Tracking

- `PROGRESS.md` — add AD-916 CLOSED line (one-line: group-chat file sharing, refs-not-blobs, vision threading to vision-capable participants; +16 tests; gate count).
- `docs/development/roadmap.md` — flip the AD-916 epic row to `SHIPPED <date> gate-verified` (match the AD-914/AD-915 row convention).
- `DECISIONS.md` — append AD-916 (refs-not-blobs on `chat_thread_messages.metadata`; reuse AD-731 vision pipe; `vision_capable` gate in group fan-out).
- Session memory `group-chat-epic.md` — append AD-916 status line.

---

## Acceptance criteria

- `AppendMessageRequest.attachment_ids` accepted; `POST /messages` with uploaded SHAs persists `metadata.attachments = [{content_hash, mime}]`; refs survive `to_dict()` / `GET /messages`.
- In a ≥2-crew thread, a `vision_capable=True` participant's fan-out intent carries `params["vision_messages"]` with the AD-731 `attachment_ref` image block; a `vision_capable=False` participant's params are byte-identical to AD-914.
- Non-image attachments are stored + referenced (link-only); no agent vision dispatch.
- Attachments-disabled and unknown-SHA paths degrade Tier-2 (no 500, no fabricated mime).
- `tests/test_ad916_chat_file_sharing.py` adds ≥14 tests (16 named), all BF-287 real-fixture; focused gate green; blast-radius gate `-k "thread or chat or fanout or attachment or vision"` green.
- No new config field, no store schema change, no protocol change.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Hard-stop conditions (Builder → surface to Architect)

- `build_multimodal_messages` / `mime_for` / `get_profile` signatures differ from the verified shapes above (phantom-API drift).
- `_get_attachment_store(runtime)` and `runtime.attachment_store` resolve to **different on-disk roots** (would mean refs built here won't resolve in the LLM client — escalate before shipping).
- A `chat.py`↔`threads.py` or `chat.py`↔`thread_fanout.py` circular import surfaces despite the lazy import (re-seat the import or invert the dependency; do not move the store accessor).
