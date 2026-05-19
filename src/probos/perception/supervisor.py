"""AD-733a: VisionSupervisor — frame-admission gate for vision LLM calls.

NeuralCompanion pattern (MIT, absorbed): VisionSource -> VisionSupervisor ->
VisionConsumer. The supervisor answers "is this frame worth an LLM call?"
without itself spending an LLM call. v1 strategy: temporal throttle (min
seconds between LLM calls) + perceptual aHash diff (64-bit hash on an 8x8
downscaled grayscale, Hamming distance > threshold).

AD-742d forward marker: pluggable Strategy Protocol so motion / CLIP /
scene-change classifier can replace this in future. v1 ships
PerceptualHashStrategy as the default; the Protocol is the public surface.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorDecision:
    """Result of one supervisor pass over a frame."""
    allow: bool
    novelty_score: float  # 0.0 (identical to last) -> 1.0 (totally novel)
    reason: str           # "throttled" | "low_novelty" | "first_frame" | "novel"


@runtime_checkable
class SupervisorStrategy(Protocol):
    """Pluggable Protocol — AD-742d will add motion / CLIP / classifier variants."""
    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision: ...


class PerceptualHashStrategy:
    """v1 default — aHash diff + temporal throttle. Pure Python; no new deps."""

    def __init__(
        self,
        *,
        min_interval_seconds: float = 3.0,
        novelty_threshold: float = 0.08,
        baseline_max_age_seconds: float = 30.0,
    ) -> None:
        self._min_interval = float(min_interval_seconds)
        self._threshold = float(novelty_threshold)
        # BF-309: after this many seconds with no admit, the supervisor
        # re-baselines on the next frame. Prevents the "static scene
        # anchors forever" lock-up where holding a steady pose makes
        # every subsequent frame look low-novelty against the stale
        # baseline. 0 = disable (legacy behavior).
        self._baseline_max_age = float(baseline_max_age_seconds)
        self._last_allow_at: float = 0.0
        self._last_hash: int | None = None

    def set_min_interval_seconds(self, value: float) -> None:
        """BF-308: live update without reconstructing the strategy."""
        self._min_interval = float(value)

    def set_novelty_threshold(self, value: float) -> None:
        """BF-308: live update without reconstructing the strategy."""
        self._threshold = float(value)

    def set_baseline_max_age_seconds(self, value: float) -> None:
        """BF-309: live update of the baseline-refresh window."""
        self._baseline_max_age = float(value)

    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
        # Tier-2: if hash computation fails (corrupt JPEG, PIL not available),
        # honest-degrade to "allow first frame, then throttle" — never raise.
        try:
            current_hash: int | None = _ahash_jpeg_bytes(frame_bytes)
        except Exception:
            logger.debug(
                "AD-733a: aHash failed; defaulting to throttle-only for this frame",
                exc_info=True,
            )
            current_hash = None

        if self._last_hash is None and self._last_allow_at == 0.0:
            self._last_hash = current_hash
            self._last_allow_at = now
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="first_frame")

        # BF-309: baseline-refresh. If we've gone too long without an admit
        # (static scene below threshold for the whole window), drop the
        # stale baseline and treat this frame as a fresh first_frame.
        # 0 disables the refresh entirely.
        if (
            self._baseline_max_age > 0
            and (now - self._last_allow_at) >= self._baseline_max_age
        ):
            self._last_hash = current_hash
            self._last_allow_at = now
            return SupervisorDecision(
                allow=True, novelty_score=1.0, reason="baseline_refresh"
            )

        elapsed = now - self._last_allow_at
        if elapsed < self._min_interval:
            return SupervisorDecision(allow=False, novelty_score=0.0, reason="throttled")

        if current_hash is None or self._last_hash is None:
            # Hash unavailable -> allow (we already passed the throttle gate)
            self._last_allow_at = now
            self._last_hash = current_hash
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="novel")

        # 64-bit aHash -> bit-difference / 64 = novelty in [0,1]
        diff_bits = bin(current_hash ^ self._last_hash).count("1")
        novelty = diff_bits / 64.0

        if novelty < self._threshold:
            return SupervisorDecision(allow=False, novelty_score=novelty, reason="low_novelty")

        self._last_allow_at = now
        self._last_hash = current_hash
        return SupervisorDecision(allow=True, novelty_score=novelty, reason="novel")


# ---------------------------------------------------------------------------
# AD-742d: alternative SupervisorStrategy implementations.
# Each conforms to the SupervisorStrategy Protocol (evaluate -> SupervisorDecision).
# Selection happens in PerceptionConfig.vision_supervisor_strategy; the
# VisionConsumer resolves the name to an instance at __init__.
# All strategies tier-2 honest-degrade: on any decode failure they ALLOW
# the first frame and then throttle — never raise.
# ---------------------------------------------------------------------------


def _load_pil_image(frame_bytes: bytes):
    """Lazy PIL import + JPEG decode. Returns Image or None on failure."""
    try:
        from io import BytesIO

        from PIL import Image
        return Image.open(BytesIO(frame_bytes))
    except Exception:
        return None


class MotionStrategy:
    """Per-pixel absolute diff after downscale + grayscale. Catches small
    motion in otherwise-static scenes (typing, head turn) that aHash blurs."""

    DOWNSCALE = (32, 32)

    def __init__(
        self,
        *,
        min_interval_seconds: float = 3.0,
        novelty_threshold: float = 0.04,
        baseline_max_age_seconds: float = 30.0,
    ) -> None:
        self._min_interval = float(min_interval_seconds)
        self._threshold = float(novelty_threshold)
        self._baseline_max_age = float(baseline_max_age_seconds)
        self._last_allow_at: float = 0.0
        self._last_pixels: bytes | None = None

    def set_min_interval_seconds(self, value: float) -> None:
        self._min_interval = float(value)

    def set_novelty_threshold(self, value: float) -> None:
        self._threshold = float(value)

    def set_baseline_max_age_seconds(self, value: float) -> None:
        self._baseline_max_age = float(value)

    def _extract(self, frame_bytes: bytes) -> bytes | None:
        img = _load_pil_image(frame_bytes)
        if img is None:
            return None
        try:
            return img.convert("L").resize(self.DOWNSCALE).tobytes()
        except Exception:
            return None

    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
        pixels = self._extract(frame_bytes)
        if self._last_pixels is None and self._last_allow_at == 0.0:
            self._last_pixels = pixels
            self._last_allow_at = now
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="first_frame")
        if (
            self._baseline_max_age > 0
            and (now - self._last_allow_at) >= self._baseline_max_age
        ):
            self._last_pixels = pixels
            self._last_allow_at = now
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="baseline_refresh")
        elapsed = now - self._last_allow_at
        if elapsed < self._min_interval:
            return SupervisorDecision(allow=False, novelty_score=0.0, reason="throttled")
        if pixels is None or self._last_pixels is None:
            self._last_allow_at = now
            self._last_pixels = pixels
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="novel")
        # Per-pixel L1 diff normalized to [0,1].
        total = sum(abs(a - b) for a, b in zip(pixels, self._last_pixels))
        novelty = total / (len(pixels) * 255.0)
        if novelty < self._threshold:
            return SupervisorDecision(allow=False, novelty_score=novelty, reason="low_novelty")
        self._last_allow_at = now
        self._last_pixels = pixels
        return SupervisorDecision(allow=True, novelty_score=novelty, reason="novel")


class SceneChangeStrategy:
    """HSV histogram delta. Catches lighting changes + new objects entering
    the frame even when overall pixel layout is similar."""

    DOWNSCALE = (64, 64)
    BINS = 16

    def __init__(
        self,
        *,
        min_interval_seconds: float = 3.0,
        novelty_threshold: float = 0.15,
        baseline_max_age_seconds: float = 30.0,
    ) -> None:
        self._min_interval = float(min_interval_seconds)
        self._threshold = float(novelty_threshold)
        self._baseline_max_age = float(baseline_max_age_seconds)
        self._last_allow_at: float = 0.0
        self._last_hist: tuple[int, ...] | None = None

    def set_min_interval_seconds(self, value: float) -> None:
        self._min_interval = float(value)

    def set_novelty_threshold(self, value: float) -> None:
        self._threshold = float(value)

    def set_baseline_max_age_seconds(self, value: float) -> None:
        self._baseline_max_age = float(value)

    def _hist(self, frame_bytes: bytes) -> tuple[int, ...] | None:
        img = _load_pil_image(frame_bytes)
        if img is None:
            return None
        try:
            hsv = img.convert("HSV").resize(self.DOWNSCALE)
            pixels = hsv.tobytes()  # H,S,V triples
            bins = [0] * (self.BINS * 3)
            step = 256 // self.BINS
            for idx, byte in enumerate(pixels):
                channel = idx % 3
                bin_idx = channel * self.BINS + min(byte // step, self.BINS - 1)
                bins[bin_idx] += 1
            return tuple(bins)
        except Exception:
            return None

    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
        hist = self._hist(frame_bytes)
        if self._last_hist is None and self._last_allow_at == 0.0:
            self._last_hist = hist
            self._last_allow_at = now
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="first_frame")
        if (
            self._baseline_max_age > 0
            and (now - self._last_allow_at) >= self._baseline_max_age
        ):
            self._last_hist = hist
            self._last_allow_at = now
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="baseline_refresh")
        elapsed = now - self._last_allow_at
        if elapsed < self._min_interval:
            return SupervisorDecision(allow=False, novelty_score=0.0, reason="throttled")
        if hist is None or self._last_hist is None:
            self._last_allow_at = now
            self._last_hist = hist
            return SupervisorDecision(allow=True, novelty_score=1.0, reason="novel")
        # Chi-square-style normalized distance.
        total = sum(self._last_hist) or 1
        diff = sum(abs(a - b) for a, b in zip(hist, self._last_hist))
        novelty = min(1.0, diff / (2.0 * total))
        if novelty < self._threshold:
            return SupervisorDecision(allow=False, novelty_score=novelty, reason="low_novelty")
        self._last_allow_at = now
        self._last_hist = hist
        return SupervisorDecision(allow=True, novelty_score=novelty, reason="novel")


class NeverDescribeStrategy:
    """Drops every frame. Useful for cost-tight deployments that want
    describe only on explicit force / DM-receive paths."""

    def __init__(self, **_kwargs) -> None:
        pass  # ignores tuning knobs

    def set_min_interval_seconds(self, value: float) -> None:
        pass

    def set_novelty_threshold(self, value: float) -> None:
        pass

    def set_baseline_max_age_seconds(self, value: float) -> None:
        pass

    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
        return SupervisorDecision(allow=False, novelty_score=0.0, reason="never_strategy")


class AlwaysAdmitStrategy:
    """Admits every frame (still subject to BF-304 single-flight). Debug
    + test scaffolding; do NOT use in production — collapses cost discipline."""

    def __init__(self, **_kwargs) -> None:
        pass

    def set_min_interval_seconds(self, value: float) -> None:
        pass

    def set_novelty_threshold(self, value: float) -> None:
        pass

    def set_baseline_max_age_seconds(self, value: float) -> None:
        pass

    def evaluate(self, frame_bytes: bytes, *, now: float) -> SupervisorDecision:
        return SupervisorDecision(allow=True, novelty_score=1.0, reason="always_strategy")


# AD-742d: name -> class mapping for VisionConsumer resolution.
STRATEGY_REGISTRY: dict[str, type] = {
    "ahash": PerceptualHashStrategy,
    "motion": MotionStrategy,
    "scene_change": SceneChangeStrategy,
    "never": NeverDescribeStrategy,
    "always": AlwaysAdmitStrategy,
}


def build_strategy(
    name: str,
    *,
    min_interval_seconds: float,
    novelty_threshold: float,
    baseline_max_age_seconds: float,
) -> SupervisorStrategy:
    """Resolve a config strategy name to an instance. Honest-degrade to
    aHash on unknown name + WARNING log (config validator should catch
    this first; this is a defense-in-depth fallback)."""
    cls = STRATEGY_REGISTRY.get(name.strip().lower())
    if cls is None:
        logger.warning(
            "AD-742d: unknown supervisor strategy %r — falling back to aHash",
            name,
        )
        cls = PerceptualHashStrategy
    return cls(
        min_interval_seconds=min_interval_seconds,
        novelty_threshold=novelty_threshold,
        baseline_max_age_seconds=baseline_max_age_seconds,
    )


def _ahash_jpeg_bytes(jpeg_bytes: bytes) -> int:
    """Average-hash 64-bit. Uses Pillow if available; raises otherwise."""
    from io import BytesIO

    from PIL import Image  # Pillow is a transitive dep via image processing

    img = Image.open(BytesIO(jpeg_bytes)).convert("L").resize((8, 8), Image.NEAREST)
    pixels = list(img.getdata())
    avg = sum(pixels) / 64.0
    bits = 0
    for i, p in enumerate(pixels):
        if p >= avg:
            bits |= 1 << i
    return bits


class VisionSupervisor:
    """Per-(runtime+session) admission gate wrapping a SupervisorStrategy."""

    def __init__(self, strategy: SupervisorStrategy | None = None) -> None:
        self._strategy: SupervisorStrategy = strategy or PerceptualHashStrategy()

    def admit(self, frame_bytes: bytes) -> SupervisorDecision:
        return self._strategy.evaluate(frame_bytes, now=time.monotonic())


__all__ = [
    "VisionSupervisor",
    "SupervisorDecision",
    "SupervisorStrategy",
    "PerceptualHashStrategy",
    "MotionStrategy",
    "SceneChangeStrategy",
    "NeverDescribeStrategy",
    "AlwaysAdmitStrategy",
    "STRATEGY_REGISTRY",
    "build_strategy",
]
