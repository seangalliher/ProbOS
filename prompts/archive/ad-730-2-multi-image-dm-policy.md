# AD-730-2 — Multi-image DM policy (hard cap, downscale, per-Captain daily budget)

**AD:** AD-730-2. **GH issue closed:** [#632](https://github.com/seangalliher/ProbOS/issues/632).
**Parent ADs:** AD-720 (image paste), AD-720d-1 (multi-image batch + soft warn threshold, Wave 154), AD-730 (vision pipe-through, Wave 151), AD-731 (content-addressable refs), AD-732 (vision tier).
**Wave:** 160. **Estimated tests:** +9 pytest. **Estimated wall-time:** ~1.5h. **Risk:** LOW — additive policy layer wrapped around existing `build_multimodal_messages`; honest-degrade throughout.

---

## Solution Overview

AD-720d-1 introduced `AttachmentsConfig.multi_image_warn_threshold = 5` — a SOFT warning logged when a DM exceeds 5 images. The policy is observation-only: no truncation, no rejection, no compression. Vision-LLM token cost scales linearly with image count and image dimension. A Captain dragging 12 high-res phone photos into one DM produces a 12-image vision call at full resolution.

AD-730-2 converts the soft warning into a structured three-tier policy:

1. **Hard cap (`images_per_dm_hard_cap`, default 8).** When `len(image_ids) > cap`, the handler rejects with HTTP 413 `payload_too_large` and a structured reason naming the cap and observed count. The soft warn threshold (5) is preserved — the operator sees a warning at 5 and a hard rejection at 8.
2. **Downscale (`image_max_dimension`, default 1024).** Before the bytes flow into `build_multimodal_messages`, every image whose width OR height exceeds the threshold is downscaled in-memory by `PIL.Image.thumbnail(...)` (which preserves aspect ratio and caps the bounding box). The downscaled bytes are content-addressed via a NEW SHA-256 and stored as a NEW attachment ref; the ORIGINAL ref is preserved (AD-731 invariant — refs are immutable). The multimodal messages array references the downscaled ref. Original ref unblocked for future retrieval (the original IS the attachment Captain uploaded; do NOT replace it).
3. **Per-Captain daily budget (`daily_image_budget_per_captain`, default 50).** A rolling 24-hour window per Captain ID (using `runtime.captain_id` or a fallback). On budget exhaustion, the handler returns HTTP 429 with a `Retry-After: <seconds>` header indicating when the oldest counted image ages out of the window. Budget tracking is in-memory (volatile across restart — AD-730-2-1 forward marker for persistence).

**Tier-2 throughout:**
- Downscale failure (PIL raises on an unusual MIME) ⇒ log WARNING, ship the ORIGINAL bytes (degradation = no compression). Never reject on compression failure.
- Budget tracking failure (e.g. `runtime.image_budget_tracker` not wired) ⇒ log WARNING, proceed without budget gate. Never reject on infrastructure failure.
- Hard cap is the ONE strict reject (it's the cost gate; "honest-degrade" on a hard cost gate would defeat the purpose).

**Pillow status:** verified installed in venv via `import PIL; print(PIL.__version__)` ⇒ `12.2.0`. NO new pip dep introduced.

**Folded:** none.

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/config.py` | `AttachmentsConfig` (line 1189..1260) | Add `images_per_dm_hard_cap`, `image_max_dimension`, `daily_image_budget_per_captain`. |
| `src/probos/attachments/image_policy.py` | NEW (~180 lines) | `ImagePolicyEnforcer` class — cap check, downscale, budget tracking. |
| `src/probos/routers/agents.py` | line ~1075 (after `image_ids` is populated, before the `vision_messages = ...` build) | Hook the policy enforcer. |
| `src/probos/runtime.py` | startup wiring | Allocate `runtime.image_budget_tracker` (in-memory `dict[str, deque[tuple[float, int]]]`). |
| `tests/test_ad730_2_image_policy.py` | NEW | 9 boundary tests. |

**Verified anchors:**
- `AttachmentsConfig` def: `src/probos/config.py:1189`. Existing `multi_image_warn_threshold: int = 5` at line 1239.
- `build_multimodal_messages` call: `src/probos/routers/agents.py:1076` (verified — `messages, image_ids, per_attachment = await build_multimodal_messages(...)`).
- `_get_attachment_store(runtime)` helper: `from probos.routers.chat import _get_attachment_store` (verified at line ~1067).
- AttachmentStore API: `store.mime_for(content_hash) -> str | None`, `store.get(content_hash) -> bytes | None`, `store.put(bytes, mime_type) -> str` (Builder verifies the `put` signature in `src/probos/attachments/filesystem_store.py`; if different, adjust).
- Pillow: `PIL.Image.open(BytesIO(bytes)).thumbnail((max_dim, max_dim))` — preserves aspect ratio.

---

## Section 1 — Config extension

In `src/probos/config.py` `AttachmentsConfig`, append AFTER `multi_image_warn_threshold` (line 1239) and BEFORE `vision_tier_overrides` (line 1245):

```python
    # AD-730-2: hard cap on images per DM. When len(image_ids) exceeds
    # this, the handler returns HTTP 413. multi_image_warn_threshold
    # (soft warn) fires at 5; hard cap fires at 8 by default. Set to 0
    # to disable the hard cap (warning still fires).
    images_per_dm_hard_cap: int = 8

    # AD-730-2: downscale bounding box for inbound vision images. When
    # either image dimension exceeds this, the policy enforcer calls
    # PIL.Image.thumbnail to fit a (image_max_dimension, image_max_dimension)
    # box (aspect ratio preserved). The downscaled bytes are stored as a
    # NEW content-addressable ref; the ORIGINAL ref is preserved
    # (AD-731 invariant — refs are immutable). Set to 0 to disable
    # downscaling.
    image_max_dimension: int = 1024

    # AD-730-2: per-Captain daily image budget (rolling 24h window). When
    # the count of images included in DMs from this Captain in the last
    # 24h exceeds the budget, the handler returns HTTP 429 with a
    # Retry-After header. Tracking is in-memory (volatile across restart;
    # AD-730-2-1 forward marker for persistence). Set to 0 to disable
    # the budget gate entirely.
    daily_image_budget_per_captain: int = 50
```

## Section 2 — `src/probos/attachments/image_policy.py` (NEW)

Create the file:

```python
"""AD-730-2: multi-image DM policy enforcer.

Three tiers (in this order, applied per-DM):
1. Hard cap on image count → HTTP 413 (the ONE strict reject).
2. Downscale oversized images → in-place via PIL; falls back to
   originals on compression failure (Tier-2).
3. Per-Captain daily budget → HTTP 429 (Tier-2; budget-tracking
   failure proceeds without the gate).

Stateless apart from the per-Captain budget tracker, which is held
on ``runtime.image_budget_tracker`` (allocated in runtime startup).
"""

from __future__ import annotations

import io
import logging
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)


class ImagePolicyError(Exception):
    """Raised when a hard policy gate blocks the DM.

    ``status_code`` selects the HTTP response (413 or 429).
    ``retry_after_seconds`` is set ONLY on 429.
    """

    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


class ImagePolicyEnforcer:
    """Applies AD-730-2 multi-image DM policy."""

    def __init__(self, runtime: Any, cfg: Any) -> None:
        self.runtime = runtime
        self.cfg = cfg

    def check_hard_cap(self, image_count: int) -> None:
        """Raise ``ImagePolicyError(413)`` when count exceeds the cap."""
        cap = int(getattr(self.cfg, "images_per_dm_hard_cap", 0))
        if cap > 0 and image_count > cap:
            raise ImagePolicyError(
                status_code=413,
                detail=(
                    f"AD-730-2: DM exceeds hard cap of {cap} images "
                    f"(observed {image_count}). Reduce the image count and resend."
                ),
            )

    async def downscale_if_needed(
        self,
        content_hashes: list[str],
        store: Any,
    ) -> list[str]:
        """Return a list of (possibly new) content hashes after downscale.

        For each input hash whose image dimensions exceed ``image_max_dimension``
        on either axis, fetch the bytes, downscale via PIL, store the new
        bytes as a NEW ref, and substitute. Originals are NOT modified
        (AD-731 invariant).

        Tier-2 throughout: per-image PIL failure logs WARNING and keeps
        the ORIGINAL hash in the returned list.
        """
        max_dim = int(getattr(self.cfg, "image_max_dimension", 0))
        if max_dim <= 0:
            return content_hashes

        try:
            from PIL import Image  # Pillow 12+ in venv; verified 2026-05-14.
        except Exception:
            logger.warning(
                "AD-730-2: PIL import failed; skipping downscale entirely",
                exc_info=True,
            )
            return content_hashes

        out: list[str] = []
        for h in content_hashes:
            try:
                mime = await store.mime_for(h)
                if mime is None or not mime.startswith("image/"):
                    out.append(h)
                    continue
                # Skip GIFs — animated frames complicate thumbnail semantics
                # and the savings are usually minor (file size dominated by
                # frame count, not dimensions).
                if mime == "image/gif":
                    out.append(h)
                    continue
                raw = await store.get(h)
                if raw is None:
                    out.append(h)
                    continue
                img = Image.open(io.BytesIO(raw))
                w, h_dim = img.size
                if w <= max_dim and h_dim <= max_dim:
                    out.append(h)
                    continue
                img.thumbnail((max_dim, max_dim))
                buf = io.BytesIO()
                # Preserve format when possible; PNG fallback otherwise.
                fmt = img.format or "PNG"
                img.save(buf, format=fmt)
                new_bytes = buf.getvalue()
                new_hash = await store.put(new_bytes, mime)
                logger.info(
                    "AD-730-2: downscaled %s -> %s (original=%dx%d, max=%d, bytes=%d->%d)",
                    h[:12], new_hash[:12], w, h_dim, max_dim, len(raw), len(new_bytes),
                )
                out.append(new_hash)
            except Exception:
                logger.warning(
                    "AD-730-2: downscale failed for %s; shipping original",
                    h[:12], exc_info=True,
                )
                out.append(h)
        return out

    def check_budget(self, captain_id: str, image_count: int) -> None:
        """Raise ``ImagePolicyError(429)`` when adding ``image_count`` would
        exceed the rolling 24h budget for this Captain.

        Tier-2 on tracker failure: log + proceed without the gate.
        """
        budget = int(getattr(self.cfg, "daily_image_budget_per_captain", 0))
        if budget <= 0 or image_count <= 0:
            return
        tracker = getattr(self.runtime, "image_budget_tracker", None)
        if tracker is None:
            logger.warning(
                "AD-730-2: runtime.image_budget_tracker missing; budget gate disabled",
            )
            return
        try:
            now = time.time()
            window = 24 * 3600.0
            cutoff = now - window
            q = tracker.setdefault(captain_id, deque())
            while q and q[0][0] < cutoff:
                q.popleft()
            used = sum(n for _, n in q)
            if used + image_count > budget:
                # Retry-After = seconds until the oldest counted image
                # ages out of the window. If queue is empty, retry-after
                # is 0 (shouldn't happen given used > 0, but defensive).
                if q:
                    retry_after = max(0.0, (q[0][0] + window) - now)
                else:
                    retry_after = 0.0
                raise ImagePolicyError(
                    status_code=429,
                    detail=(
                        f"AD-730-2: daily image budget exceeded for captain "
                        f"{captain_id} (used={used}, requested={image_count}, "
                        f"budget={budget})"
                    ),
                    retry_after_seconds=retry_after,
                )
            q.append((now, image_count))
        except ImagePolicyError:
            raise
        except Exception:
            logger.warning(
                "AD-730-2: budget tracker raised for captain=%s; proceeding without gate",
                captain_id, exc_info=True,
            )
```

## Section 3 — Hook the enforcer into `agent_chat`

In `src/probos/routers/agents.py`, find the existing `build_multimodal_messages` call (line ~1076) AND the existing soft-warn block (around line 1086-1095 — the `AD-720d-1: soft warning when image count exceeds the operator threshold` block).

**Insert IMMEDIATELY AFTER the soft-warn `if image_ids and warn_threshold ...` block and BEFORE the `if image_ids:` vision-tier-or-fallback branch (around line 1097):**

```python
                # AD-730-2: hard cap + downscale + budget gates.
                # Order: cap check first (cheapest), then downscale
                # (rebuilds image_ids when any image was resized), then
                # budget (after downscale because budget tracks final
                # delivered images, not pre-compression count).
                if image_ids:
                    from probos.attachments.image_policy import (
                        ImagePolicyEnforcer, ImagePolicyError,
                    )
                    _enforcer = ImagePolicyEnforcer(runtime, cfg_attach)
                    try:
                        _enforcer.check_hard_cap(len(image_ids))
                    except ImagePolicyError as e:
                        raise HTTPException(
                            status_code=e.status_code, detail=e.detail,
                        )
                    # Downscale rebuilds image_ids; messages array is
                    # rebuilt below if any hash changed. For simplicity,
                    # rebuild the full multimodal payload when the
                    # downscaled list differs from the original.
                    _downscaled = await _enforcer.downscale_if_needed(
                        image_ids, store,
                    )
                    if _downscaled != image_ids:
                        # Re-run build_multimodal_messages with a new
                        # attachment_ids tuple where image refs are the
                        # downscaled hashes. Non-image refs are unchanged.
                        # The simplest approach: walk req.attachment_ids,
                        # substitute hash-for-hash via a translation map.
                        _trans = dict(zip(image_ids, _downscaled))
                        _new_attach_ids = [
                            _trans.get(a, a) for a in req.attachment_ids
                        ]
                        messages, image_ids, per_attachment = await build_multimodal_messages(
                            prompt=req.message,
                            attachment_ids=_new_attach_ids,
                            store=store,
                            mime_lookup=_mime_lookup,
                            text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                            pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                        )
                    # Budget last — operates on the final delivered count.
                    _captain_id = getattr(runtime, "captain_id", None) or "default"
                    try:
                        _enforcer.check_budget(_captain_id, len(image_ids))
                    except ImagePolicyError as e:
                        headers = {}
                        if e.retry_after_seconds is not None:
                            headers["Retry-After"] = str(int(e.retry_after_seconds))
                        raise HTTPException(
                            status_code=e.status_code,
                            detail=e.detail,
                            headers=headers,
                        )
```

**Builder verification before insertion:**

1. Confirm `HTTPException` accepts a `headers` kwarg in the FastAPI version pinned in `pyproject.toml`. (Standard FastAPI ≥0.95 supports it. If older, fall back to constructing a `JSONResponse` with explicit headers.)
2. Confirm `runtime.captain_id` exists. If not, the `getattr` fallback to `"default"` handles it (single-captain-per-deployment is the v1 assumption); Builder greps `runtime.captain_id` and notes the result in the build report. If a Captain-multitenancy field exists under a different name, substitute.
3. Confirm `store.put(bytes, mime)` signature in `src/probos/attachments/filesystem_store.py`. If the signature is `put(bytes, mime_type=None)` or `put(bytes, *, mime: str)`, adjust the call in `downscale_if_needed`.

## Section 4 — Runtime allocation

In `src/probos/runtime.py`, find a clean spot in the startup wiring (near other `divergence_results` / `divergence_corrections` allocations) and add:

```python
        # AD-730-2: per-Captain daily image budget tracker. In-memory
        # rolling 24h window. Volatile across restart — AD-730-2-1
        # forward marker for persistent backend (file-based or DB-backed
        # deployments requiring restart-survival).
        from collections import deque
        self.image_budget_tracker: dict[str, deque[tuple[float, int]]] = {}
```

## Section 5 — Tests

`tests/test_ad730_2_image_policy.py` — 9 boundary tests:

1. `test_hard_cap_zero_disables_gate` — `images_per_dm_hard_cap=0` ⇒ no rejection even at 100 images.
2. `test_hard_cap_exceeded_raises_413` — cap=8, count=9 ⇒ `ImagePolicyError(413)`.
3. `test_hard_cap_at_boundary_passes` — cap=8, count=8 ⇒ no raise.
4. `test_downscale_zero_disables` — `image_max_dimension=0` ⇒ returns hashes unchanged.
5. `test_downscale_oversize_image_substitutes_ref` — provide a 2048x2048 PNG via a `_FakeStore`; verify the returned hash differs and the stored bytes decode to ≤1024 on max dim.
6. `test_downscale_undersize_image_pass_through` — 512x512 PNG ⇒ same hash returned.
7. `test_downscale_pil_failure_returns_original` — `store.get` returns malformed bytes ⇒ logs warning, returns original hash.
8. `test_budget_under_limit_passes` — used=10, requested=5, budget=50 ⇒ no raise; deque appended.
9. `test_budget_exceeded_raises_429_with_retry_after` — budget=10, prior usage = 8 over the last 6 hours; requested=5 ⇒ `ImagePolicyError(429, retry_after_seconds=...)` where `retry_after_seconds` is approximately 18h (the oldest entry's age complement).

Use `_FakeStore` (minimal in-memory dict for `mime_for` / `get` / `put`); test image bytes can be a 4×4 PNG generated via PIL at test setup.

---

## What This Does NOT Change

- AD-720d-1 soft-warn threshold (5) — preserved as observation. Hard cap (8) is the new layer.
- AD-731 invariant — original refs are never mutated. Downscale produces NEW refs; the originals stay accessible.
- Non-image attachments — PDF / text / audio refs pass through every gate untouched.
- The chain path (`_execute_chain_with_intent_routing`) — DM-path only.
- The text-only fallback path (when `image_ids` is empty post-build) — no images, no policy.
- AD-732 vision tier health checks.

---

## Verification Commands

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad730_2_image_policy.py -v -n 0 | Select-Object -Last 30
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad730_*.py tests/test_ad720d_1_*.py tests/test_ad731_*.py -v -n 0 | Select-Object -Last 30
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile | Select-Object -Last 3
```

No UI files modified — `npm run build` not required.

---

## Tracker Updates

- **PROGRESS.md:** `AD-730-2 — Multi-image DM policy (+9 pytest tests; closes #632). Hard cap (8, 413), in-place PIL downscale to 1024px bounding box (Tier-2; AD-731 invariant preserved via NEW refs), per-Captain rolling 24h budget (50, 429 with Retry-After). No new pip deps (Pillow 12.2.0 already in venv).`
- **roadmap.md:** remove #632; add forward markers AD-730-2-1 (persistent budget tracker — for deployments where restart-survival of budget state matters), AD-730-2-2 (per-agent_type budget override — analytics workloads may need higher budgets than dialogue agents).
- **DECISIONS.md:** append `### AD-730-2 — Multi-image DM policy`.

---

## License Disposition

All-internal Apache 2.0. Pillow (PIL) is already a venv dependency (verified `import PIL; PIL.__version__` ⇒ `12.2.0`). NO new pip dep introduced. Pillow itself is HPND license (permissive, compatible with Apache 2.0).

---

## Forward markers (technical-trigger language)

- **AD-730-2-1 — Persistent budget tracker.** Advances when a deployment requires budget enforcement to survive runtime restart (e.g., a continuously-running production node where Captain hits the budget early in a session and the restart-induced reset would silently grant a 2x budget).
- **AD-730-2-2 — Per-agent_type budget override.** Advances when analytics workloads (e.g., a Vision-only agent that explicitly ingests Captain image streams) need a higher budget than dialogue agents.

---

## Acceptance Criteria

- ✅ Config fields added.
- ✅ `image_policy.py` module added with `ImagePolicyEnforcer` + `ImagePolicyError`.
- ✅ `agent_chat` hooks enforcer between message build and vision dispatch.
- ✅ `runtime.image_budget_tracker` allocated in startup.
- ✅ 9 tests pass.
- ✅ Existing AD-720 / AD-720d-1 / AD-730 / AD-731 / AD-732 test files stay green UNCHANGED.
- ✅ Full gate green.
- ✅ No new pip dep in `pyproject.toml`.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-14)

```
AttachmentsConfig:
  src/probos/config.py:1189: class AttachmentsConfig(BaseModel):
  src/probos/config.py:1239: multi_image_warn_threshold: int = 5
  src/probos/config.py:1245: vision_tier_overrides: dict[str, str] = Field(default_factory=dict)

build_multimodal_messages call:
  src/probos/routers/agents.py:1076: messages, image_ids, per_attachment = await build_multimodal_messages(

Soft-warn block:
  src/probos/routers/agents.py:1086-1095 (AD-720d-1 warning)

Pillow availability:
  d:/ProbOS/.venv/Scripts/python.exe -c "import PIL; print(PIL.__version__)"
  -> 12.2.0
```
