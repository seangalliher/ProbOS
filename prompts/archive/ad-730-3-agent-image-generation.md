# AD-730-3 — Agent image generation in DM replies

**Wave:** 169.
**Status:** ready for Builder.
**Closes:** [#633](https://github.com/seangalliher/ProbOS/issues/633).
**Parent:** AD-730 (Wave 151, image consumption, commit `033b838`), AD-731 (Wave 151, AttachmentStore SHA-256 refs, no inline blobs), AD-732 + 8-guard catalog (Wave 153, vision tier as fourth peer of `_LLM_TIERS`), AD-727 (avatar capability-surface governance).
**Estimated:** ~3–3.5 h. Test delta: +14 pytest. No UI gate in v1 (response wire-format change is backward-compat-additive; HXI render of inline images is forward marker). No new pip deps in v1.

## Problem

AD-730 (W151) made agents able to **see** images attached to DMs. Agents cannot **emit** images. The Captain has asked for the inverse: an agent (e.g. Diagnostician generating a sensor-data chart) attaches a generated image to its reply. The issue body:

> 1. Image-generation tier configuration (e.g. DALL-E or equivalent).
> 2. Storage-write capability for generated images (return as `attachment_id` in chat response).
> 3. Counselor wellness review (per AD-727-style safety): an agent generating images of itself or peers needs governance.

This is a new capability surface — comparable safety class to AD-732 vision (consumption) plus a write-capability superset.

## Solution

A new `image_gen` LLM tier as the **sixth peer** of `_LLM_TIERS` (`fast/standard/deep/vision/compute_use/image_gen`), an OpenAI-shape `images/generations` endpoint client method, a bracket-marker (`[GEN_IMAGE prompt]`) parsed in the DM reply pipeline that writes bytes through `AttachmentStore.write` per AD-731 and returns the SHA-256 as `attachment_ids: list[str]` on the chat response, AND a Counselor wellness-review hook fired on the first image-gen invocation per agent per process lifetime.

**Vendor choice (researched):** the **OpenAI Images API v1 shape** (`POST /v1/images/generations` returning `data[].b64_json` or `data[].url`) is the de-facto OpenAI-compatible standard. This is what:
- OpenAI itself uses (DALL-E 3, `gpt-image-1`).
- Ollama-compatible front-ends supporting image gen accept.
- Open-source proxies (litellm, openrouter) standardise on.

Local image-gen via Ollama-proper does NOT exist (Ollama is text-only as of 2026). Operators wanting local image gen typically run AUTOMATIC1111 / ComfyUI / SD.next, all of which support OpenAI-shape adapters via plugins. The endpoint config is therefore `llm_base_url_image_gen` (operator-supplied; no default) + `llm_model_image_gen` (e.g. `dall-e-3` / `gpt-image-1` / a local SD model name). When unconfigured, the bracket marker honest-degrades to a strip-and-log no-op identical to AD-728d's invalid-reason path.

**Bracket marker shape:** `[GEN_IMAGE <prompt>]` where `<prompt>` is a free-form image description up to a strict char cap (default 512). One marker per reply honored; additional markers stripped silently. Identical contract shape to AD-728d's `[SELF_CHECK reason]`.

## What This Does NOT Change

- **HXI render of generated images.** v1 returns `attachment_ids` on the response; the existing HXI attachment renderer already knows how to render incoming `attachment_id` via `/api/chat/attachments/{sha}`. If the HXI does not currently render `attachment_ids` on the **agent's** reply (only on the Captain's outbound), Builder files **AD-730-3-4** as forward marker — do NOT extend the HXI in this wave.
- **Cost / rate-gating budget enforcement** — forward marker **AD-730-3-1**.
- **Image moderation / safety classifier** — forward marker **AD-730-3-2**.
- **Provenance watermarking / "generated-by-AI" metadata** — forward marker **AD-730-3-3**.
- **Ward Room (multi-agent) channel image gen** — bracket marker is wired ONLY into the DM reply pipeline (`step_4c_image_gen_parse`). WR wiring deferred (forward marker **AD-730-3-5**).
- **ModelRouter (AD-463) integration** — image_gen tier explicitly bypasses ModelRouter (BF-273 lesson: tier-unaware routers misroute to text models). The vendor config is authoritative.
- **Fallback chain** — image_gen NOT added to `_TIER_ORDER` (BF-269 lesson: text tiers can't generate images).
- **Cache** — image generation requests bypass `LLMResponseCache` (BF-272 lesson: degenerate cache keys for non-text payloads).
- **Health probe** — image_gen tier health probe uses `min(tc.timeout, 30)` (BF-270 pattern), but probe path tests are forward marker if not trivially testable.

## Eight-Guard Catalog Audit (per user-memory 2026-05-12 lesson)

Every tier-enumerating piece of cross-cutting infrastructure must explicitly handle `image_gen` or explicitly bypass:

| # | Surface | Handling for `image_gen` |
|---|---------|--------------------------|
| 1 | `_LLM_TIERS` constant (`cognitive/llm_client.py:31`) | **Added** as sixth peer. |
| 2 | `_TIER_ORDER` (`cognitive/llm_client.py:38`) | **Excluded** (text tiers can't generate images). |
| 3 | `cognitive.tier_config(tier)` per-tier maps (`config.py:270+`) | **All 6 maps extended**: `url_map`, `key_map`, `model_map`, `timeout_map`, `format_map`, `temp_map`, `top_p_map`, `max_tokens_map`. |
| 4 | `is_vision_tier_configured(...)` (`cognitive/vision_dispatch.py`) | **NOT extended** — separate helper `is_image_gen_tier_configured` added. Mirrors honest-degrade message pattern. |
| 5 | ModelRouter `by_tier()` (`cognitive/model_router.py`) | **Explicit bypass** in the image_gen call path. |
| 6 | LLMResponseCache | **Explicit bypass** for image_gen requests. |
| 7 | Health probe / per-tier status surface | **Tier added** to status dict; probe timeout `min(tc.timeout, 30)`. |
| 8 | Fallback recovery chain | **Excluded** — failures return honest-degrade dict, never fall back to text. |

The Builder MUST verify each of these 8 sites is touched (positively or explicitly with a comment documenting bypass) before the AD ships.

## Verified Against Codebase (2026-05-17)

```text
grep -n "_LLM_TIERS" src/probos/cognitive/llm_client.py
  31: _LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use")

grep -n "_TIER_ORDER" src/probos/cognitive/llm_client.py
  38: _TIER_ORDER: tuple[str, ...] = ("fast", "standard", "deep")

grep -n "def tier_config" src/probos/config.py
  270:     def tier_config(self, tier: str) -> dict:

grep -n "is_vision_tier_configured" src/probos/cognitive/vision_dispatch.py
  (defined alongside VISION_UNCONFIGURED_MESSAGE; Builder grep at build time)

grep -n "class AttachmentStore" src/probos/attachments/store.py
  14: class AttachmentStore(Protocol):
  22:     async def write(self, content_hash: str, blob: bytes, mime: str) -> Path:

grep -n "extract_self_check\|strip_self_check" src/probos/cognitive/dm_sanity_gate.py
  207:     def extract_self_check(self, text: str) -> list[str]:
  227:     def strip_self_check(self, text: str) -> str:

grep -n "step_4_self_check_parse" src/probos/cognitive/dm/reply_pipeline.py
  81:             self.step_4_self_check_parse,
  268:     async def step_4_self_check_parse(self) -> None:

grep -n "build_response" src/probos/cognitive/dm/reply_pipeline.py
  505:     def build_response(self) -> dict[str, Any]:

grep -n "_validate_and_store_attachment" src/probos/routers/chat.py
  621: async def _validate_and_store_attachment(

grep -n "class ChatResponse\|class DmReplyContext" src/probos/cognitive/dm/reply_pipeline.py src/probos/api_models.py
  src/probos/cognitive/dm/reply_pipeline.py:28: class DmReplyContext:
  src/probos/api_models.py:34: class ChatResponse(BaseModel):

grep -n "captain_card_enabled\|render_self_check_enabled" src/probos/config.py
  (verified — AvatarsConfig is the analogous config class shape)

grep -n "AgentChatRequest\|AgentChatResponse" src/probos/api_models.py
  146: class AgentChatRequest(BaseModel):
  (response is currently an untyped dict from build_response — see Section 6)
```

## Sections

### Section 0: Config — `CognitiveConfig` image_gen tier

**File:** `src/probos/config.py`, `class CognitiveConfig` block (around line 195 onward, mirroring the existing vision + compute_use blocks).

Add the new tier fields adjacent to the AD-706c-2 compute_use block:

```python
    # AD-730-3: image_gen tier — sixth peer of fast/standard/deep/vision/
    # compute_use. Image generation via OpenAI-compatible
    # POST /v1/images/generations (DALL-E 3 / gpt-image-1 / local SD via
    # ComfyUI/A1111 OpenAI-shape adapter). Default unconfigured; opt-in
    # via system.yaml. When unconfigured OR unhealthy, agent
    # [GEN_IMAGE ...] markers honest-degrade to silent strip.
    # Does NOT participate in the fast→standard→deep fallback chain
    # (text tiers can't generate images, per BF-269 lesson).
    # ModelRouter bypassed at call site (BF-273 lesson).
    # LLMResponseCache bypassed (BF-272 lesson).
    llm_base_url_image_gen: str | None = None
    llm_api_key_image_gen: str | None = None
    llm_model_image_gen: str | None = None
    llm_timeout_image_gen: float | None = None
    llm_api_format_image_gen: str | None = None  # "openai" (only supported shape)
```

Extend ALL maps inside `tier_config(self, tier: str)` (Builder MUST extend every map — `url_map`, `key_map`, `model_map`, `timeout_map`, `format_map`, `temp_map`, `top_p_map`, `max_tokens_map`) so `tier_config("image_gen")` returns a resolved dict. For temp/top_p/max_tokens, image_gen does not need overrides today; map entries can be `None`-valued for parity with vision/compute_use.

### Section 1: `_LLM_TIERS` constant

**File:** `src/probos/cognitive/llm_client.py`.

```python
# BEFORE:
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use")
# AFTER:
_LLM_TIERS: tuple[str, ...] = ("fast", "standard", "deep", "vision", "compute_use", "image_gen")
```

`_TIER_ORDER` is **NOT** modified. Add a one-line comment beside the constant documenting that `image_gen` joins `vision` and `compute_use` in the exclusion set.

### Section 2: AvatarsConfig knobs (governance + safety)

**File:** `src/probos/config.py`, `class AvatarsConfig`.

These knobs gate the capability and the wellness review:

```python
    # AD-730-3: agent image generation in DM replies.
    image_gen_enabled: bool = Field(
        default=False,
        description=(
            "AD-730-3: master switch for agent image generation via "
            "[GEN_IMAGE ...] bracket marker. Default OFF (transitional). "
            "Requires CognitiveConfig.llm_base_url_image_gen to be set."
        ),
    )
    image_gen_max_prompt_chars: int = Field(
        default=512,
        ge=8,
        le=4000,
        description=(
            "AD-730-3: hard cap on the [GEN_IMAGE ...] prompt length. "
            "Markers exceeding this are silently stripped and a single "
            "WARNING is logged."
        ),
    )
    image_gen_wellness_review_required: bool = Field(
        default=True,
        description=(
            "AD-730-3: when True, the FIRST image_gen invocation per "
            "agent per process triggers a Counselor wellness review log "
            "entry (AD-727 governance pattern). Subsequent invocations "
            "by the same agent skip the review until process restart."
        ),
    )
    image_gen_max_image_bytes: int = Field(
        default=4 * 1024 * 1024,  # 4 MB
        ge=64 * 1024,
        le=25 * 1024 * 1024,
        description=(
            "AD-730-3: per-image size cap on bytes written to AttachmentStore. "
            "Defense in depth alongside the upstream API's own limits."
        ),
    )
    image_gen_mime: str = Field(
        default="image/png",
        description=(
            "AD-730-3: declared MIME for stored images. PNG is OpenAI's "
            "default. Operator may set to image/jpeg if their endpoint "
            "returns JPEG."
        ),
    )
```

### Section 3: `image_gen` client + honest-degrade helpers

**New file:** `src/probos/cognitive/image_gen_dispatch.py` (≈180 lines).

```python
"""AD-730-3: agent image generation via OpenAI-compatible Images API.

Sixth peer tier (image_gen) handler. Mirrors vision_dispatch shape:
honest-degrade constants, configuration probe, request adapter.

Critical invariants:
  * AD-731 — bytes flow through AttachmentStore.write(sha, blob, mime).
    Source-scan asserts no inline base64 in the bus or response shape.
  * BF-269 — does NOT participate in fast→standard→deep fallback.
  * BF-272 — bypasses LLMResponseCache (image bytes are non-cacheable).
  * BF-273 — bypasses ModelRouter (router only knows text tiers).
  * AD-727 — first invocation per agent emits a Counselor wellness
    review log line.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


IMAGE_GEN_UNCONFIGURED_MESSAGE = (
    "(image generation unavailable — operator has not configured the "
    "image_gen tier; the [GEN_IMAGE ...] marker was stripped)"
)
IMAGE_GEN_DISABLED_MESSAGE = (
    "(image generation disabled — AvatarsConfig.image_gen_enabled is False)"
)
IMAGE_GEN_FAILED_MESSAGE = (
    "(image generation failed — endpoint returned an error; reply preserved "
    "without image)"
)
IMAGE_GEN_TOO_LARGE_MESSAGE = (
    "(image generation rejected — returned bytes exceeded the "
    "AvatarsConfig.image_gen_max_image_bytes cap)"
)


def is_image_gen_tier_configured(cognitive_cfg: Any) -> bool:
    """Mirrors is_vision_tier_configured. Returns True iff base_url AND
    model are non-empty strings on the cognitive config block.
    """
    base = getattr(cognitive_cfg, "llm_base_url_image_gen", None)
    model = getattr(cognitive_cfg, "llm_model_image_gen", None)
    return bool(base) and bool(model)


async def dispatch_image_gen(
    runtime: Any,
    *,
    agent_id: str,
    prompt: str,
) -> dict[str, Any]:
    """Generate an image, persist to AttachmentStore, return attachment_id.

    Returns a flat dict:
      * Success: ``{"ok": True, "attachment_id": str, "mime": str,
        "size_bytes": int, "prompt": str}``.
      * Honest-degrade: ``{"ok": False, "reason": str, "message": str}``.

    NEVER raises. Tier-2 throughout. ModelRouter bypassed; cache bypassed;
    no fallback to text tiers.
    """
    cfg_root = getattr(runtime, "config", None)
    cog_cfg = getattr(cfg_root, "cognitive", None)
    av_cfg = getattr(cfg_root, "avatars", None)

    if not bool(getattr(av_cfg, "image_gen_enabled", False)):
        return {"ok": False, "reason": "image_gen_disabled",
                "message": IMAGE_GEN_DISABLED_MESSAGE}
    if not is_image_gen_tier_configured(cog_cfg):
        return {"ok": False, "reason": "image_gen_unconfigured",
                "message": IMAGE_GEN_UNCONFIGURED_MESSAGE}

    # AD-727 wellness review: emit on first invocation per agent per process.
    if bool(getattr(av_cfg, "image_gen_wellness_review_required", True)):
        _maybe_emit_wellness_review(runtime, agent_id)

    tc = cog_cfg.tier_config("image_gen")
    base_url = tc["base_url"].rstrip("/")
    api_key = tc.get("api_key") or ""
    model = tc["model"]
    timeout_s = float(tc.get("timeout") or 60.0)

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url}/images/generations"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except Exception:
        logger.warning(
            "AD-730-3: image_gen endpoint call raised for agent=%s",
            agent_id, exc_info=True,
        )
        return {"ok": False, "reason": "transport_error",
                "message": IMAGE_GEN_FAILED_MESSAGE}

    if resp.status_code >= 400:
        logger.warning(
            "AD-730-3: image_gen endpoint returned %d for agent=%s body=%s",
            resp.status_code, agent_id, resp.text[:512],
        )
        return {"ok": False, "reason": f"http_{resp.status_code}",
                "message": IMAGE_GEN_FAILED_MESSAGE}

    try:
        data = resp.json()
        b64 = data["data"][0]["b64_json"]
        blob = base64.b64decode(b64, validate=True)
    except Exception:
        logger.warning(
            "AD-730-3: image_gen response parse failed for agent=%s",
            agent_id, exc_info=True,
        )
        return {"ok": False, "reason": "parse_error",
                "message": IMAGE_GEN_FAILED_MESSAGE}

    max_bytes = int(getattr(av_cfg, "image_gen_max_image_bytes", 4 * 1024 * 1024))
    if len(blob) > max_bytes:
        return {"ok": False, "reason": "too_large",
                "message": IMAGE_GEN_TOO_LARGE_MESSAGE}

    sha = hashlib.sha256(blob).hexdigest()
    mime = str(getattr(av_cfg, "image_gen_mime", "image/png"))
    store = getattr(runtime, "attachment_store", None)
    if store is None:
        return {"ok": False, "reason": "store_unavailable",
                "message": IMAGE_GEN_FAILED_MESSAGE}

    try:
        await store.write(sha, blob, mime)
    except Exception:
        logger.warning(
            "AD-730-3: AttachmentStore.write failed for agent=%s sha=%s",
            agent_id, sha[:12], exc_info=True,
        )
        return {"ok": False, "reason": "store_write_error",
                "message": IMAGE_GEN_FAILED_MESSAGE}

    return {
        "ok": True,
        "attachment_id": sha,
        "mime": mime,
        "size_bytes": len(blob),
        "prompt": prompt,
    }


_WELLNESS_REVIEW_SEEN: set[str] = set()


def _maybe_emit_wellness_review(runtime: Any, agent_id: str) -> None:
    """AD-727: first image_gen call per agent per process triggers a
    Counselor wellness review log line. Subsequent calls are no-op.

    Process-scoped — intentionally NOT persisted. Restart resets the
    review interval. Suitable for v1 governance signal; persistence is
    a forward marker.
    """
    if agent_id in _WELLNESS_REVIEW_SEEN:
        return
    _WELLNESS_REVIEW_SEEN.add(agent_id)
    logger.warning(
        "AD-727/AD-730-3 WELLNESS REVIEW: agent=%s has invoked image "
        "generation for the first time this process; counselor should "
        "review capability use during next scheduled wellness check",
        agent_id,
    )
```

**License audit:** `httpx` already resident (per Wave 162). `base64` / `hashlib` / `logging` stdlib. **0-line license diff.**

### Section 4: Bracket-marker parser in `DmSanityGate`

**File:** `src/probos/cognitive/dm_sanity_gate.py`, adjacent to `extract_self_check`/`strip_self_check`.

```python
# AD-730-3: image generation marker. Prompt is 1..N chars of free-form
# text. The strict regex captures the prompt for dispatch; the lax
# regex strips well-formed AND malformed markers to prevent leakage.
# Closing bracket terminates the prompt; embedded ] is not supported in v1.
_GEN_IMAGE_RE = re.compile(r"\[GEN_IMAGE\s+([^\]\n]{1,4000})\]")
_GEN_IMAGE_STRIP_RE = re.compile(r"\[GEN_IMAGE\b[^\]\n]*\]?")
```

(Place the prompt-length cap in the regex at 4000 chars — final enforcement happens against `AvatarsConfig.image_gen_max_prompt_chars` at extraction time, NOT at regex level. The 4000 above is just to prevent runaway regex backtracking.)

Add the two methods adjacent to `extract_self_check`/`strip_self_check`:

```python
    def extract_gen_image(self, text: str, *, max_chars: int = 512) -> list[str]:
        """AD-730-3: return all valid [GEN_IMAGE prompt] prompts in order.

        Prompts exceeding ``max_chars`` are excluded from the result but
        still stripped by :meth:`strip_gen_image`. Callers should
        dispatch only the FIRST returned prompt; additional ones are
        informational and stripped silently.
        """
        if not text:
            return []
        prompts: list[str] = []
        for m in _GEN_IMAGE_RE.finditer(text):
            p = m.group(1).strip()
            if 1 <= len(p) <= max_chars:
                prompts.append(p)
        return prompts

    def strip_gen_image(self, text: str) -> str:
        """AD-730-3: remove ALL [GEN_IMAGE ...] markers from reply text.

        Strips both well-formed and malformed variants so no bracket
        marker leaks into Captain-visible output. Mirrors the
        :meth:`strip_self_check` contract including trailing ``.strip()``.
        """
        if not text:
            return text
        return _GEN_IMAGE_STRIP_RE.sub("", text).strip()
```

### Section 5: `DmReplyPipeline` step + response wiring

**File:** `src/probos/cognitive/dm/reply_pipeline.py`.

(a) Extend `DmReplyContext` with an attachment-ids slot. Place adjacent to `_self_check_task`:

```python
    # AD-730-3: SHA-256 refs of images generated by the agent for this
    # reply. Surfaced on the response payload as ``attachment_ids``.
    # AD-731 invariant: refs only — bytes live in AttachmentStore.
    generated_attachment_ids: list[str] = field(default_factory=list)
    # AD-730-3: fire-and-forget tracking — held to prevent GC mid-flight.
    _image_gen_task: "asyncio.Task[None] | None" = None
```

(b) Add new step `step_4c_image_gen_parse` AFTER `step_4_self_check_parse` and BEFORE `step_4b_dm_outbound_parse`. **Important:** the step is added with letter suffix (`4c`) to avoid renumbering the trailing 5 steps and breaking AD-728d's atomicity invariant.

```python
    async def step_4c_image_gen_parse(self) -> None:
        """AD-730-3: parse [GEN_IMAGE prompt] markers and dispatch image
        generation. Strips the marker before downstream steps see the
        text. First marker dispatched; additional markers stripped with
        single WARNING. Honest-degrade on disabled / unconfigured tier.
        """
        gate = self.ctx.sanity_gate
        if gate is None:
            return
        runtime = self.ctx.runtime
        cfg = getattr(runtime, "config", None)
        av_cfg = getattr(cfg, "avatars", None)
        max_chars = int(getattr(av_cfg, "image_gen_max_prompt_chars", 512))
        try:
            prompts = gate.extract_gen_image(self.ctx.response_text, max_chars=max_chars)
        except Exception:
            logger.warning(
                "AD-730-3: extract_gen_image raised for agent=%s",
                self.ctx.agent_id, exc_info=True,
            )
            return
        # Always strip BEFORE returning so markers don't leak even on
        # disabled/unconfigured tiers.
        try:
            self.ctx.response_text = gate.strip_gen_image(self.ctx.response_text)
        except Exception:
            pass
        if not prompts:
            return
        if len(prompts) > 1:
            logger.warning(
                "AD-730-3: agent=%s emitted %d GEN_IMAGE markers in one reply; "
                "dispatching first only",
                self.ctx.agent_id, len(prompts),
            )
        # Dispatch sync-await (not fire-and-forget) so the SHA can be
        # attached to THIS reply's response payload. Cap by image_gen
        # tier timeout via dispatch_image_gen's own timeout_s.
        from probos.cognitive.image_gen_dispatch import dispatch_image_gen
        result = await dispatch_image_gen(
            runtime, agent_id=self.ctx.agent_id, prompt=prompts[0],
        )
        if result.get("ok"):
            self.ctx.generated_attachment_ids.append(result["attachment_id"])
        else:
            # Honest-degrade: leave reply intact, prepend the honest-
            # degrade message to the response text so the Captain sees
            # why no image came through.
            self.ctx.response_text = (
                f"{self.ctx.response_text}\n\n{result.get('message', '')}"
            ).strip()
```

(c) Add to the step tuple in `run()`:

```python
        for step in (
            self.step_1_sanity_gate_retry,
            self.step_2_challenge_parse,
            self.step_3_move_parse,
            self.step_4_self_check_parse,
            self.step_4c_image_gen_parse,   # AD-730-3
            self.step_4b_dm_outbound_parse,
            self.step_5_episodic_store,
            ...
        ):
```

(d) Extend `build_response` to surface the attachment_ids:

```python
    def build_response(self) -> dict[str, Any]:
        response: dict[str, Any] = {
            "response": self.ctx.response_text,
            "callsign": self.ctx.callsign,
            "agentId": self.ctx.agent_id,
            "emotion": self.ctx.emotion,
        }
        # AD-730-3: generated images attached as SHA refs (AD-731).
        if self.ctx.generated_attachment_ids:
            response["attachment_ids"] = list(self.ctx.generated_attachment_ids)
        if self.ctx.game_move_result:
            response["gameMoveExecuted"] = True
            response["gameStatus"] = self.ctx.game_move_result.get("state", {}).get("status", "")
        return response
```

### Section 6: Anchored episodic record (per user-memory 2026-05-12 BF-274 lesson)

**File:** new helper inside `image_gen_dispatch.py` OR inside the pipeline step, depending on Builder preference. The intent: record an `anchored` episode for every successful image generation so future recall does NOT hallucinate that the agent generated an image when they did not.

Per AD-541b reconsolidation protection, the episodic write should set high importance and an `anchored=True` marker. Builder MUST verify the episodic-write signature in the existing AD-728c `record_observation` call site for parity and either invoke through the same path OR file a one-line forward marker if the episodic-write API surface differs.

```python
    # AD-730-3 + AD-541b: anchored episode on success.
    try:
        episodic = getattr(runtime, "episodic_memory", None)
        if episodic is not None and hasattr(episodic, "store_episode"):
            await episodic.store_episode(
                agent_id=agent_id,
                content=f"Generated image (sha={sha[:12]}) for prompt: {prompt[:160]}",
                importance=8,
                metadata={"anchored": True, "ad": "AD-730-3",
                          "attachment_id": sha, "mime": mime},
            )
    except Exception:
        logger.warning("AD-730-3: episode anchor write failed for agent=%s",
                       agent_id, exc_info=True)
```

If `episodic.store_episode` does NOT exist with that signature, Builder should grep for the canonical write path (e.g. `runtime.episodic_memory.write` or similar) and adapt. If no clean signature exists, drop the episode write from v1 and file **AD-730-3-6: anchored episode for image_gen** as forward marker.

### Section 7: Tests

**New file:** `tests/test_ad730_3_agent_image_gen.py`. Real `SystemConfig()` per BF-287. Hand-rolled `_FakeAttachmentStore` (in-memory dict), `_FakeRuntime`, monkey-patched httpx mock transport. Target +14 tests:

1. `test_dispatch_unconfigured_returns_honest_degrade` — tier unconfigured → `{"ok": False, "reason": "image_gen_unconfigured"}`.
2. `test_dispatch_master_switch_off_returns_honest_degrade` — `image_gen_enabled=False`.
3. `test_dispatch_happy_path_writes_to_store_returns_sha` — mock 200 with b64_json → SHA returned matches `sha256(blob).hexdigest()`, store contains blob.
4. `test_dispatch_http_500_returns_honest_degrade` — mock 500 → `reason="http_500"`.
5. `test_dispatch_parse_error_returns_honest_degrade` — mock returns malformed JSON.
6. `test_dispatch_too_large_returns_honest_degrade` — blob exceeds `image_gen_max_image_bytes`.
7. `test_dispatch_transport_error_returns_honest_degrade` — httpx raises.
8. `test_wellness_review_emitted_on_first_call_only` — same agent_id called twice; WARNING log fires once.
9. `test_is_image_gen_tier_configured_negative_when_base_url_missing` and `_positive_when_both_set`.
10. `test_extract_gen_image_returns_first_valid_prompt`.
11. `test_extract_gen_image_truncated_when_exceeds_max_chars` — prompt longer than `max_chars` excluded from result but stripped.
12. `test_strip_gen_image_removes_well_and_malformed_markers`.
13. `test_pipeline_step_4c_attaches_sha_on_success` — full pipeline run with image gen wired in; `build_response()` includes `attachment_ids`.
14. `test_pipeline_step_4c_strips_marker_when_disabled` — `image_gen_enabled=False`; marker stripped from response, `attachment_ids` absent from response dict, honest-degrade message appended.

**Eight-guard regression tests** (additive within the same test file or a sibling):

- `test_image_gen_in_LLM_TIERS` — `"image_gen" in _LLM_TIERS`.
- `test_image_gen_NOT_in_TIER_ORDER` — `"image_gen" not in _TIER_ORDER`.
- `test_tier_config_image_gen_resolves` — `CognitiveConfig().tier_config("image_gen")` returns a dict with all expected keys (None values OK).
- `test_no_inline_base64_in_response_payload` — source-scan `dm/reply_pipeline.py` for `b64encode`/`b64_json` (allowed only in image_gen_dispatch.py at the API boundary).

These four eight-guard tests are LOW-COST and should be included in v1 — they protect against future tier-enumerating regressions.

### Section 8: HXI display surface (assessment only — do NOT build)

Builder MUST run a one-grep check on `ui/src/**` for `attachment_ids` handling in `agent_chat` reply rendering. If the HXI does not already render `attachment_ids` on the AGENT's outbound reply (most likely — the field is new on that surface), file **AD-730-3-4: HXI render of agent-generated attachment_ids** as forward marker and do NOT extend the HXI in this AD.

If the HXI already renders, document the rendering call site in the build report and verify the existing test coverage.

## Forward Markers (per AD-722c-3 — TECHNICAL triggers)

- **AD-730-3-1** — Per-conversation + per-day cost gating budget enforcement (config flag + counter + Captain ACK on overrun). *Trigger:* operator reports >$5/day image-gen cost OR ≥3 agents reach ≥10 generations/day without Captain approval.
- **AD-730-3-2** — Image moderation classifier (NSFW / safety / policy). *Trigger:* image_gen is exercised in production for ≥30 days AND a single moderation incident is documented in a ProbOS deployment.
- **AD-730-3-3** — Provenance watermarking + C2PA-shape metadata embedding. *Trigger:* operator deployment publishes generated images to a third-party channel (Ward Room cross-posts, public link sharing).
- **AD-730-3-4** — HXI rendering of agent-generated `attachment_ids` on the DM reply surface. *Trigger:* this AD merges AND Captain reports inability to see generated images in the HXI.
- **AD-730-3-5** — Ward Room wiring of `[GEN_IMAGE ...]` bracket marker in the WR reply pipeline. *Trigger:* documented WR use-case requiring agent-generated images (e.g. multi-agent chart construction).
- **AD-730-3-6** — Anchored episode write (if Section 6 path doesn't cleanly fit the existing episodic API).

## Invariants Preserved

- **AD-731** (refs not blobs): every image byte path flows through `AttachmentStore.write(sha, blob, mime)`. Source-scan asserts NO `IntentMessage` constructor accepts inline base64 image data. The bus carries refs; the store carries bytes.
- **AD-732 / 8-guard** (vision pattern): `image_gen` is added to `_LLM_TIERS` and `tier_config` maps, explicitly excluded from `_TIER_ORDER` and `LLMResponseCache`, ModelRouter bypassed at call site.
- **AD-727** (capability-surface governance): first invocation per agent emits a Counselor wellness review log line.
- **AD-728d** (bracket-marker atomicity): new step is `step_4c_image_gen_parse` (letter suffix) so the trailing 5 steps are NOT renumbered.
- **AD-541b** (reconsolidation protection): successful image gen writes an anchored, high-importance episode.
- **BF-269** (no fallback to text tiers).
- **BF-272** (no cache for non-cacheable payloads).
- **BF-273** (no ModelRouter participation for non-text tiers).
- **BF-274** (single-replace adjacent edits — Builder uses `replace_string_in_file` for the step tuple insert, NOT `multi_replace_string_in_file`).
- **BF-286/287** (real config + real fixtures in tests; NO MagicMock at substrate boundary).

## License Posture

**0-line license diff expected.** No new pip deps, no new npm deps. `httpx` already resident (Wave 162). `base64`, `hashlib`, `logging`, `re`, `asyncio` stdlib.

The image_gen endpoint contract is **OpenAI Images API v1 shape**, which is a vendor-neutral wire format used by OpenAI, openrouter, litellm, and OpenAI-compat plugins for AUTOMATIC1111 / ComfyUI / SD.next. No SDK dependency on the OpenAI Python client — we POST raw httpx requests.

## Tracking

- `DECISIONS.md`: append `### AD-730-3 — Agent image generation in DM replies (Wave 169)` entry with the 8-guard catalog reproduced inline.
- `progress-era-5-unification.md`: append AD-730-3 closed entry with file list + +14 test count + invariants + 8-guard verification.
- `docs/development/roadmap.md`: AD-730-3 moved from forward markers to shipped row in the Wave 169 batch. AD-730-3-1 through AD-730-3-6 added as forward markers with technical triggers.
- `gh issue close 633` with closing comment referencing AD-730-3 + the 5–6 forward markers.
- GH forward-marker issues filed for AD-730-3-1 through AD-730-3-5 (AD-730-3-6 only if Section 6 falls back to forward marker).

## Acceptance Criteria

1. `tests/test_ad730_3_agent_image_gen.py` adds +14 (or +14-N if Section 6 falls back to forward marker) passing tests; full gate strictly increases.
2. The 4 eight-guard tests pass.
3. `dispatch_image_gen` honest-degrades on every documented failure mode without raising.
4. `[GEN_IMAGE prompt]` markers are stripped from `response_text` even when image gen is disabled.
5. `build_response()` surfaces `attachment_ids: list[str]` ONLY when at least one image was generated; absent when none.
6. `image_gen` is in `_LLM_TIERS` (test 15), NOT in `_TIER_ORDER` (test 16).
7. `CognitiveConfig().tier_config("image_gen")` returns a fully resolved dict.
8. Source-scan: `dm/reply_pipeline.py` contains NO `b64encode` or `b64_json`. Source-scan: `image_gen_dispatch.py` does NOT call `model_router.by_tier`, `_TIER_ORDER`, `LLMResponseCache`, or perform fallback.
9. First `dispatch_image_gen` call per agent emits ONE WARNING log line containing `WELLNESS REVIEW`; second call by same agent emits NONE.
10. `gh issue close 633` posted with closing comment referencing the AD and the filed forward markers.
11. `git status` clean post-commit.
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Build Order

1. Section 0 (CognitiveConfig tier fields + tier_config map extensions) — apply, run config tests.
2. Section 1 (`_LLM_TIERS`) — one-line constant change, run llm_client tests.
3. Section 2 (AvatarsConfig knobs) — apply.
4. Section 3 (new `image_gen_dispatch.py` module) — write, run new module tests in isolation.
5. Section 4 (DmSanityGate regex + helpers) — apply, run dm_sanity_gate tests.
6. Section 5 (pipeline step + ctx + build_response) — apply with `replace_string_in_file` ONLY (BF-274), run AD-728d + AD-726 pipeline tests + AD-730-3 pipeline tests.
7. Section 6 (anchored episode) — verify episodic API signature; if mismatch, file AD-730-3-6 and skip.
8. Section 7 (full test file) — finalise, run full gate.
9. Section 8 (HXI assessment) — run one grep; file AD-730-3-4 forward marker.
10. Tracking updates + `gh issue close` + GH forward-marker issues filed.

If Section 6 reveals episodic API drift OR if Section 5's pipeline step insertion forces an unexpected step renumber, hard-stop and surface to architect.

## Reviewer Acknowledgement Notes

- The choice of OpenAI Images API v1 shape over alternatives (Anthropic, Stability inference REST, local SD direct API) is documented in this prompt and in the DECISIONS entry. Operators wanting other vendors layer a translator OR use openrouter as the base_url.
- The Counselor wellness review in v1 is a logger.WARNING line, NOT an interactive ACK. The interactive ACK form is implicit in AD-727 governance pattern but the issue specifies "review", not "block". v1 follows the issue's wording literally; interactive ACK is AD-730-3-1 territory.
- Process-scoped wellness-review set (`_WELLNESS_REVIEW_SEEN`) resets on restart by design. Persistent dedupe is a forward marker.
- The `[GEN_IMAGE ...]` marker syntax mirrors AD-728d's `[SELF_CHECK reason]` shape so the LLM-side reasoning surface is consistent. The skill catalog wiring (an actual augmentation skill at `config/skills/image-generation/SKILL.md`) is OPTIONAL in v1 — if Builder finds the AD-728d skill-wiring pattern trivial to extend in <30 min, add it; otherwise file as **AD-730-3-7: image-generation augmentation skill** and ship the marker-only path.
