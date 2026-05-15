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

import hashlib
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
                raw = await store.read(h)
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
                new_hash = hashlib.sha256(new_bytes).hexdigest()
                await store.write(new_hash, new_bytes, mime)
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
