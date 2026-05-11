# AD-730 — Vision Pipe-Through for Per-Agent DMs

**Status:** Ready for Builder
**Dependencies:** AD-720d (Wave 139, shipped); BF 2026-05-11 (today's AgentChatRequest.attachment_ids + vision_dispatch augmentation)
**GH issue:** [#630](https://github.com/seangalliher/ProbOS/issues/630)
**Estimated tests:** ≥ 10 backend (new `tests/test_ad730_agent_chat_vision.py`) + ≥ 2 Vitest (existing ProfileChatTab attachment-send test extension)

**Captain decisions baked in (from issue body):**
- **Choice (a):** Pass multimodal `messages` array through `IntentMessage.params['vision_messages']`. Agent routes to vision tier when present.
- **Tier inheritance:** Reuse `runtime.config.attachments.vision_tier` from AD-720d. No per-agent vision tier in v1.
- **Standing Orders:** No new EventType; ride existing `direct_message` event with `has_image_attachment: True` data field for AD-722a / Counselor observability.
- **v1 single-image:** First `image/*` MIME wins; additional images get text markers via existing `augment_prompt_with_attachment_text` (text-only fallback).

---

## Problem

`/api/chat` (Wave 139, AD-720d) routes images through the vision tier via `build_multimodal_messages()` → `LLMRequest(messages=...)` → vision-tier `runtime.llm_client.complete()`. The per-agent DM path `/api/agent/{id}/chat` (used by `ProfileChatTab` and the WardRoom DM sync path) has no equivalent. Today it calls `augment_prompt_with_attachment_text()` which only embeds non-image text content + literal `[Captain attached an image (id=...)]` markers. The agent's LLM never sees the bytes.

The vision-capable model is already configured (Claude via Copilot proxy at `attachments.vision_tier`). Only the plumbing past the agent prompt boundary is missing.

## Solution

Three changes:

1. **`routers/agents.py`:** Replace the existing `augment_prompt_with_attachment_text()` call with the same vision-aware branch as `/api/chat`. When `image_ids` is non-empty AND the vision tier is operational, build `vision_messages` and pass them through `IntentMessage.params['vision_messages']` along with the original text prompt. When degraded, fall back to today's text-only augmentation.
2. **`cognitive/cognitive_agent.py`:** In the `direct_message` perception path, check for `params['vision_messages']` and route the LLM call to the configured vision tier with `LLMRequest(messages=vision_messages, ...)` instead of the standard text-only `LLMRequest(prompt=..., system_prompt=...)`.
3. **Episodic tagging:** When `vision_messages` is present, store the episode with `has_image_attachment=True` in its `outcomes` payload (AD-430b episode-storage pattern). No new EventType; this is a data flag.

The vision tier health probe is identical to `/api/chat:309-325` — reused verbatim, not re-implemented.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `src/probos/routers/agents.py` | Replace `augment_prompt_with_attachment_text` block with vision-aware branch mirroring `/api/chat:285-355` |
| `src/probos/cognitive/cognitive_agent.py` | In `_build_user_message` direct_message branch (or LLM-call site for DM path), check `observation.get('vision_messages')` and pass to `LLMRequest(messages=...)` when present |
| `src/probos/cognitive/cognitive_agent.py` | Episodic storage path: set `has_image_attachment` on outcomes payload when `vision_messages` present |
| `tests/test_ad730_agent_chat_vision.py` | NEW — 10+ test cases |
| `ui/src/__tests__/ProfileChatTab.test.tsx` | EXTEND — assert attachment send still works (no UI changes needed; backend transparently upgrades) |
| `PROGRESS.md` | Status line update |
| `DECISIONS.md` | Append AD-730 closure block under existing AD-730 entry |
| `docs/development/roadmap.md` | Mark AD-730 shipped + add 5 forward marker rows |

---

## Section 1 — Router: vision branch in `agent_chat`

### 1a. Locate the existing augmentation block

Current state at `src/probos/routers/agents.py:885-915` (verified pre-build):

```python
    # BF (2026-05-11): augment message with attachment text + image markers so
    # the agent's direct_message handler (text-only) at least sees attachments.
    # Tier-2 log-and-degrade: failures fall back to the original message.
    message_text = req.message
    if req.attachment_ids:
        cfg_attach = getattr(runtime.config, "attachments", None)
        if cfg_attach is not None and getattr(cfg_attach, "enabled", False):
            try:
                from probos.cognitive.vision_dispatch import (
                    augment_prompt_with_attachment_text,
                )
                from probos.routers.chat import _get_attachment_store

                store = _get_attachment_store(runtime)

                async def _mime_lookup(content_hash: str) -> str | None:
                    return await store.mime_for(content_hash)

                message_text = await augment_prompt_with_attachment_text(
                    prompt=req.message,
                    attachment_ids=list(req.attachment_ids),
                    store=store,
                    mime_lookup=_mime_lookup,
                    text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                    pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                )
            except Exception as e:
                logger.warning(
                    "agent_chat attachment augmentation failed for %s: %s: %s; "
                    "falling back to text-only message",
                    agent_id, type(e).__name__, e,
                )
```

### 1b. Replace with vision-aware branch

**SEARCH:**
```python
    # BF (2026-05-11): augment message with attachment text + image markers so
    # the agent's direct_message handler (text-only) at least sees attachments.
    # Tier-2 log-and-degrade: failures fall back to the original message.
    message_text = req.message
    if req.attachment_ids:
        cfg_attach = getattr(runtime.config, "attachments", None)
        if cfg_attach is not None and getattr(cfg_attach, "enabled", False):
            try:
                from probos.cognitive.vision_dispatch import (
                    augment_prompt_with_attachment_text,
                )
                from probos.routers.chat import _get_attachment_store

                store = _get_attachment_store(runtime)

                async def _mime_lookup(content_hash: str) -> str | None:
                    return await store.mime_for(content_hash)

                message_text = await augment_prompt_with_attachment_text(
                    prompt=req.message,
                    attachment_ids=list(req.attachment_ids),
                    store=store,
                    mime_lookup=_mime_lookup,
                    text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                    pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                )
            except Exception as e:
                logger.warning(
                    "agent_chat attachment augmentation failed for %s: %s: %s; "
                    "falling back to text-only message",
                    agent_id, type(e).__name__, e,
                )
```

**REPLACE:**
```python
    # AD-730 (Wave 151): vision pipe-through for per-agent DMs.
    # When req.attachment_ids includes an image MIME AND attachments.vision_tier
    # is operational, build the Anthropic-shape multimodal messages array and
    # pass it through IntentMessage.params['vision_messages']. The receiving
    # agent's direct_message handler routes that to LLMRequest(messages=...)
    # via the configured vision tier. When images are absent OR vision tier is
    # degraded, fall back to AD-720d's text-only augmentation (markers + extracted
    # text) so the agent at least sees the attachment names.
    # Tier-2 log-and-degrade throughout: failures revert to the original message.
    message_text = req.message
    vision_messages: list[dict[str, object]] | None = None
    has_image_attachment = False
    if req.attachment_ids:
        cfg_attach = getattr(runtime.config, "attachments", None)
        if cfg_attach is not None and getattr(cfg_attach, "enabled", False):
            try:
                from probos.cognitive.vision_dispatch import (
                    augment_prompt_with_attachment_text,
                    build_multimodal_messages,
                )
                from probos.routers.chat import _get_attachment_store

                store = _get_attachment_store(runtime)

                async def _mime_lookup(content_hash: str) -> str | None:
                    return await store.mime_for(content_hash)

                # Build the multimodal array once; we may use either the
                # vision-tier path (image_ids present + tier operational) or
                # extract the text-only augmented prompt from it as fallback.
                messages, image_ids = await build_multimodal_messages(
                    prompt=req.message,
                    attachment_ids=list(req.attachment_ids),
                    store=store,
                    mime_lookup=_mime_lookup,
                    text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                    pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                )

                if image_ids:
                    # Vision tier health probe — same pattern as /api/chat:309-325.
                    tier = cfg_attach.vision_tier
                    health = runtime.llm_client.get_health_status()
                    tier_status = (
                        health.get("tiers", {}).get(tier) or {}
                    ).get("status")
                    if tier_status == "operational":
                        vision_messages = messages
                        has_image_attachment = True
                        # Keep message_text as the original (the LLM sees the
                        # full multimodal array; episodic memory keeps the
                        # original Captain text so search/recall remains text-friendly).
                    else:
                        logger.warning(
                            "AD-730 vision tier=%s unavailable (status=%s) for "
                            "agent=%s; falling back to text-only augmentation. "
                            "attachment_ids=%s",
                            tier, tier_status, agent_id, list(req.attachment_ids),
                        )
                        # Fall through to text-only augmentation below.

                if vision_messages is None:
                    # Text-only path: either no images, or vision degraded.
                    message_text = await augment_prompt_with_attachment_text(
                        prompt=req.message,
                        attachment_ids=list(req.attachment_ids),
                        store=store,
                        mime_lookup=_mime_lookup,
                        text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                        pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                    )
            except Exception as e:
                logger.warning(
                    "agent_chat attachment augmentation failed for %s: %s: %s; "
                    "falling back to text-only message",
                    agent_id, type(e).__name__, e,
                )
```

### 1c. Pass vision_messages through IntentMessage.params

Locate the existing `IntentMessage(intent="direct_message", ...)` construction immediately after the augmentation block.

**SEARCH:**
```python
    from probos.types import IntentMessage
    intent = IntentMessage(
        intent="direct_message",
        params={
            "text": message_text,
            "from": "hxi_profile",
            "session": bool(req.history),
            "session_history": req.history[-10:] if req.history else [],
        },
        target_agent_id=agent_id,
        ttl_seconds=60.0,  # AD-636: Extended TTL for Captain DMs
    )
```

**REPLACE:**
```python
    from probos.types import IntentMessage
    _params: dict[str, object] = {
        "text": message_text,
        "from": "hxi_profile",
        "session": bool(req.history),
        "session_history": req.history[-10:] if req.history else [],
    }
    # AD-730: thread vision messages through to the agent's LLM-call site.
    # When present, the agent routes to attachments.vision_tier with
    # LLMRequest(messages=vision_messages); otherwise the standard text path.
    if vision_messages is not None:
        _params["vision_messages"] = vision_messages
        _params["has_image_attachment"] = True
    intent = IntentMessage(
        intent="direct_message",
        params=_params,
        target_agent_id=agent_id,
        ttl_seconds=60.0,  # AD-636: Extended TTL for Captain DMs
    )
```

---

## Section 2 — Agent: route DM perception turn to vision tier when present

### 2a. Locate the DM LLM-call site

The DM path's primary LLM call is in `cognitive_agent.py` around line 2036 (`request = LLMRequest(prompt=user_message, system_prompt=composed, tier=...)`). Builder MUST grep first to verify the exact site is the one that handles `direct_message` intents (the agent has multiple LLM-call sites for different intents).

```bash
grep -n "request = LLMRequest" src/probos/cognitive/cognitive_agent.py
```

Expected output: line 2036 (the primary `decide()` LLM call), and several others (skill execution, etc.). The DM path runs through `decide()` which builds the request at ~2036.

### 2b. Add vision-tier branch

In the body of the method that contains line 2036 (`decide()` or equivalent — Builder verifies), BEFORE the `LLMRequest(...)` construction, add the vision branch:

**SEARCH:**
```python
        request = LLMRequest(
            prompt=user_message,
            system_prompt=composed,
            tier=_per_call_tier or self._resolve_tier(),
        )
```

**REPLACE:**
```python
        # AD-730 (Wave 151): vision pipe-through for DM perception.
        # When the intent params carry vision_messages (Captain attached an
        # image to the DM), route through attachments.vision_tier with the
        # multimodal array instead of the standard text path. The system_prompt
        # is still passed — Claude vision accepts system + multimodal user content.
        _vision_messages = observation.get("params", {}).get("vision_messages")
        if _vision_messages:
            _vision_tier = (
                getattr(getattr(self._runtime, "config", None), "attachments", None)
            )
            _resolved_vision_tier = (
                getattr(_vision_tier, "vision_tier", None)
                if _vision_tier is not None else None
            )
            request = LLMRequest(
                prompt="",  # content lives in messages
                messages=_vision_messages,
                system_prompt=composed,
                tier=_resolved_vision_tier or (_per_call_tier or self._resolve_tier()),
            )
        else:
            request = LLMRequest(
                prompt=user_message,
                system_prompt=composed,
                tier=_per_call_tier or self._resolve_tier(),
            )
```

### 2c. Episodic tag

Locate the AD-430b episode storage in agent_chat (it lives in `routers/agents.py`, not `cognitive_agent.py`). Builder greps for `from probos.cognitive.episodic import resolve_sovereign_id` to find the existing episode-build block. In the existing `outcomes=[{...}]` dict that's already constructed for the episode, add `has_image_attachment` keyed off the local variable from Section 1.

**SEARCH** (in routers/agents.py, in the episodic storage block — Builder finds the exact text via grep for `"intent": "direct_message"` inside the outcomes dict):
```python
            outcomes=[{
                "intent": "direct_message",
                "success": True,
                "response": response_text[:500],
                "session_type": "1:1",
                "callsign": callsign,
                "source": "hxi_profile",
                "agent_type": agent.agent_type,
            }],
```

**REPLACE:**
```python
            outcomes=[{
                "intent": "direct_message",
                "success": True,
                "response": response_text[:500],
                "session_type": "1:1",
                "callsign": callsign,
                "source": "hxi_profile",
                "agent_type": agent.agent_type,
                # AD-730: tag DM episodes that included an image so Counselor
                # wellness and AD-722a divergence analysis can filter on it.
                "has_image_attachment": has_image_attachment,
            }],
```

---

## Section 3 — Tests

Create `tests/test_ad730_agent_chat_vision.py`. Mirror the stub-runtime pattern from `tests/test_ad720d_vision_dispatch.py` (existing).

### Required tests (≥ 10)

1. **`test_dm_image_routes_to_vision_tier`** — POST `/api/agent/{id}/chat` with an image attachment_id; assert `runtime.llm_client.complete` was called with `messages` arg matching the multimodal array shape AND `tier == cfg_attach.vision_tier`.

2. **`test_dm_image_passes_vision_messages_through_intent_params`** — capture the `IntentMessage` dispatched to the intent bus; assert `params['vision_messages']` is present and contains an `image` content block.

3. **`test_dm_image_with_degraded_vision_tier_falls_back_to_text_augmentation`** — mock `llm_client.get_health_status` to return `tier_status='degraded'`; assert vision_messages not set, message_text contains the `[Captain attached an image]` marker.

4. **`test_dm_no_attachments_unchanged_path`** — text-only DM (no attachment_ids); assert no vision branch entered, no `vision_messages` key in params.

5. **`test_dm_text_only_attachment_no_vision_branch`** — DM with a `.txt` attachment_id; assert vision_messages absent (no image_ids), message_text has the extracted text inline (AD-720d behavior).

6. **`test_dm_image_episode_has_image_attachment_flag`** — successful DM with image; assert the stored episode's `outcomes[0]['has_image_attachment'] == True`.

7. **`test_dm_no_attachments_episode_has_image_attachment_false`** — text-only DM; assert episode's `outcomes[0]['has_image_attachment'] == False` (default).

8. **`test_dm_vision_messages_preserves_system_prompt`** — image DM; capture the LLMRequest; assert `system_prompt` is non-empty (compose_instructions output) AND `messages` is the multimodal array.

9. **`test_dm_vision_tier_resolution_when_per_call_tier_set`** — image DM with `_per_call_tier='fast'`; assert the vision tier wins over per-call tier (vision takes precedence when vision_messages is present).

10. **`test_dm_image_with_attachments_disabled_falls_back_silently`** — `cfg.attachments.enabled = False`; assert no augmentation runs, original message_text used, no log error.

11. **`test_dm_first_image_only_in_multi_image_attachment`** *(forward-marker prep)* — DM with TWO image attachments; assert v1 wins on first image only OR all images included per `build_multimodal_messages` behavior (whichever the function actually does — Builder verifies and writes the test to match observed behavior). Document the result in AD-730-2 forward marker.

12. **`test_dm_augmentation_exception_falls_back_to_original_message`** — make `build_multimodal_messages` raise; assert `message_text == req.message` and no exception propagates.

### Frontend test extension (`ui/src/__tests__/ProfileChatTab.test.tsx`)

Add 2 cases:
1. **`sends image attachment and renders agent response`** — verify the existing paperclip + send flow still works; mock fetch to return a Counselor-style response describing the image.
2. **`shows attachment chip after upload and clears on send`** — UI parity check.

---

## Section 4 — Tracker updates

- `PROGRESS.md` — status line update with Wave 151 + close #630.
- `DECISIONS.md` — under existing AD-730 entry, append a closure block with commit SHA + test delta.
- `docs/development/roadmap.md` — mark AD-730 shipped; add 5 forward marker rows (AD-730-1 through AD-730-5).

---

## What this does NOT change

- `build_multimodal_messages()` signature, behavior, or call sites outside `agent_chat`.
- `/api/chat` main composer vision path — unchanged.
- `augment_prompt_with_attachment_text()` — unchanged (still used as fallback when vision tier degraded).
- WardRoom DM panel UI — backend will transparently route correctly when WardRoomThreadDetail eventually adds an attach button (AD-730-1).
- `IntentMessage` schema — `params` already accepts arbitrary dict; new key `vision_messages` is additive.
- `AvatarTelemetryConfig` or any AD-722* surface — divergence detector continues to receive the LLM's text response unchanged.
- Default behavior — vision pipe-through is *unconditional* when image attachment + operational vision tier; no new feature flag.

---

## Acceptance criteria

1. All ≥ 10 backend tests pass.
2. All ≥ 2 Vitest tests pass; existing ProfileChatTab tests stay green.
3. Pre-existing tests stay green: AD-720d (33 cases), AD-720d-1 (PDF), AD-722a (taxonomy migration), AD-722a-5 (history dashboard), AD-722a-7 (intent modulation).
4. Full parallel gate `pytest tests/ -q -n 4 --dist=loadfile` green (modulo 4 documented pre-existing flakes).
5. Phantom-API precheck zero new phantoms (modulo known false positives: `TestClient`, `SelfImageTab.tsx`, `LLMRequest.messages` parameter).
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Forward markers (file at retrospective)

| Marker | Scope |
|---|---|
| AD-730-1 | Vision UI attach button in WardRoomThreadDetail (backend already routes — UI surface only) |
| AD-730-2 | Multi-image DMs (≥2 attachments). v1 supports first image only (or all images, per `build_multimodal_messages` behavior — TBD by Test 11) |
| AD-730-3 | Agent image generation in DM replies (requires generation tier + storage-write capability) |
| AD-730-4 | Federation peer-to-peer vision DMs (inherits AD-480 governance review) |
| AD-730-5 | Per-agent vision tier override (e.g. hypothetical Imaging Officer) |

---

## Engineering Principles compliance

- **(S)** `agent_chat` vision branch is a single responsibility added inline; logic factored where possible.
- **(O)** Extends `IntentMessage.params` with a new optional key (`vision_messages`); existing callers unaffected.
- **(D)** Vision tier read via `runtime.config.attachments.vision_tier`; no hardcoded model names.
- **Defense in depth** — vision branch only fires when (a) `cfg.attachments.enabled`, (b) `image_ids` non-empty, (c) tier health is `operational`. Three gates before vision dispatch.
- **Three-tier exceptions** — Tier-2 log-and-degrade on any augmentation failure (existing pattern preserved).
- **Async hygiene** — All new awaits inside existing async function; no new `create_task`.
- **Type annotations** — `vision_messages: list[dict[str, object]] | None` declared explicitly.
- **Logging quality** — Tier-degradation log carries tier name, status, agent_id, and what the system did (fell back).
- **Configuration** — No new config fields. Inherits `attachments.vision_tier` from AD-720d.
- **Test isolation** — Each test builds its own stub runtime; no shared state.
- **Boundary tests** — Happy / vision degraded / no images / mixed / exception fallback all covered.

---

## Verified Against Codebase (2026-05-11)

```
grep -n "async def build_multimodal_messages" src/probos/cognitive/vision_dispatch.py
  81:async def build_multimodal_messages(
grep -n "async def augment_prompt_with_attachment_text" src/probos/cognitive/vision_dispatch.py
  187:async def augment_prompt_with_attachment_text(
grep -n "vision_tier\|tier_status" src/probos/routers/chat.py
  310:                tier = cfg_attach.vision_tier
  311:                health = runtime.llm_client.get_health_status()
  312:                tier_status = (health.get("tiers", {}).get(tier) or {}).get("status")
grep -n "request = LLMRequest" src/probos/cognitive/cognitive_agent.py
  2036:        request = LLMRequest(
  3178:        request = LLMRequest(
  3405:        request = LLMRequest(
  4550:                llm_request = LLMRequest(
grep -n "messages.*list" src/probos/types.py
  243:    messages: list[dict] | None = None
grep -n "augment_prompt_with_attachment_text" src/probos/routers/agents.py
  893:                    augment_prompt_with_attachment_text,
  902:                message_text = await augment_prompt_with_attachment_text(
grep -n "attachment_ids" src/probos/api_models.py
  24:    attachment_ids: list[str] = Field(default_factory=list)
  153:    attachment_ids: list[str] = Field(default_factory=list)
```

Symbols introduced by this prompt (do NOT flag as phantoms):
- `IntentMessage.params['vision_messages']` (new dict key — runtime data, not API surface)
- `IntentMessage.params['has_image_attachment']` (same)
- `outcomes[0]['has_image_attachment']` (episodic outcome data field)
