"""AD-730-2: Boundary tests for the multi-image DM policy enforcer.

Nine tests cover: hard-cap gates, downscale tiers, budget tier, and the
AD-731 invariant (originals preserved, downscale produces NEW refs).
"""

from __future__ import annotations

import hashlib
import io
import time
from collections import deque
from types import SimpleNamespace
from typing import Any

import pytest

from probos.attachments.image_policy import (
    ImagePolicyEnforcer,
    ImagePolicyError,
)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


class _FakeStore:
    """Minimal AttachmentStore stand-in — keyed by content_hash."""

    def __init__(self) -> None:
        self._bytes: dict[str, bytes] = {}
        self._mime: dict[str, str] = {}

    def add(self, blob: bytes, mime: str) -> str:
        h = hashlib.sha256(blob).hexdigest()
        self._bytes[h] = blob
        self._mime[h] = mime
        return h

    async def mime_for(self, content_hash: str) -> str | None:
        return self._mime.get(content_hash)

    async def read(self, content_hash: str) -> bytes | None:
        return self._bytes.get(content_hash)

    async def write(self, content_hash: str, blob: bytes, mime: str) -> Any:
        self._bytes[content_hash] = blob
        self._mime[content_hash] = mime
        return None


def _png_bytes(w: int, h: int) -> bytes:
    """Generate a small valid PNG via PIL."""
    from PIL import Image
    img = Image.new("RGB", (w, h), color=(64, 128, 192))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _cfg(**over: Any) -> SimpleNamespace:
    base = dict(
        images_per_dm_hard_cap=8,
        image_max_dimension=1024,
        daily_image_budget_per_captain=50,
    )
    base.update(over)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# 1-3 hard cap                                                                #
# --------------------------------------------------------------------------- #


def test_hard_cap_zero_disables_gate() -> None:
    e = ImagePolicyEnforcer(SimpleNamespace(), _cfg(images_per_dm_hard_cap=0))
    e.check_hard_cap(100)  # no raise


def test_hard_cap_exceeded_raises_413() -> None:
    e = ImagePolicyEnforcer(SimpleNamespace(), _cfg(images_per_dm_hard_cap=8))
    with pytest.raises(ImagePolicyError) as exc:
        e.check_hard_cap(9)
    assert exc.value.status_code == 413


def test_hard_cap_at_boundary_passes() -> None:
    e = ImagePolicyEnforcer(SimpleNamespace(), _cfg(images_per_dm_hard_cap=8))
    e.check_hard_cap(8)  # no raise


# --------------------------------------------------------------------------- #
# 4-7 downscale                                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_downscale_zero_disables() -> None:
    e = ImagePolicyEnforcer(SimpleNamespace(), _cfg(image_max_dimension=0))
    store = _FakeStore()
    h = store.add(_png_bytes(2048, 2048), "image/png")
    out = await e.downscale_if_needed([h], store)
    assert out == [h]


@pytest.mark.asyncio
async def test_downscale_oversize_image_substitutes_ref() -> None:
    e = ImagePolicyEnforcer(SimpleNamespace(), _cfg(image_max_dimension=512))
    store = _FakeStore()
    h_orig = store.add(_png_bytes(2048, 2048), "image/png")
    out = await e.downscale_if_needed([h_orig], store)
    assert out != [h_orig]
    assert len(out) == 1
    new_h = out[0]
    assert new_h != h_orig
    # AD-731 invariant: original preserved.
    assert await store.read(h_orig) is not None
    # Downscaled bytes decode under 512 max dim.
    from PIL import Image
    img = Image.open(io.BytesIO(await store.read(new_h)))
    assert max(img.size) <= 512


@pytest.mark.asyncio
async def test_downscale_undersize_image_pass_through() -> None:
    e = ImagePolicyEnforcer(SimpleNamespace(), _cfg(image_max_dimension=1024))
    store = _FakeStore()
    h = store.add(_png_bytes(512, 512), "image/png")
    out = await e.downscale_if_needed([h], store)
    assert out == [h]


@pytest.mark.asyncio
async def test_downscale_pil_failure_returns_original() -> None:
    e = ImagePolicyEnforcer(SimpleNamespace(), _cfg(image_max_dimension=512))
    store = _FakeStore()
    bad_h = hashlib.sha256(b"not-an-image").hexdigest()
    store._bytes[bad_h] = b"not-an-image"
    store._mime[bad_h] = "image/png"
    out = await e.downscale_if_needed([bad_h], store)
    assert out == [bad_h]


# --------------------------------------------------------------------------- #
# 8-9 budget                                                                  #
# --------------------------------------------------------------------------- #


def test_budget_under_limit_passes() -> None:
    rt = SimpleNamespace(image_budget_tracker={"cap": deque([(time.time(), 10)])})
    e = ImagePolicyEnforcer(rt, _cfg(daily_image_budget_per_captain=50))
    e.check_budget("cap", 5)
    # Queue gained one entry.
    assert len(rt.image_budget_tracker["cap"]) == 2


def test_budget_exceeded_raises_429_with_retry_after() -> None:
    six_hours_ago = time.time() - 6 * 3600
    rt = SimpleNamespace(
        image_budget_tracker={"cap": deque([(six_hours_ago, 8)])},
    )
    e = ImagePolicyEnforcer(rt, _cfg(daily_image_budget_per_captain=10))
    with pytest.raises(ImagePolicyError) as exc:
        e.check_budget("cap", 5)
    assert exc.value.status_code == 429
    assert exc.value.retry_after_seconds is not None
    # Oldest entry ages out ~18h from now.
    assert 17 * 3600 < exc.value.retry_after_seconds < 19 * 3600
