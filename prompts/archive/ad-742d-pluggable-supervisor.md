# AD-742d — Pluggable VisionSupervisor strategies

**Wave:** 175
**Closes:** #672
**Status:** drafting → GATE 1
**Dependencies:** AD-733a (`SupervisorStrategy` Protocol shipped at
`supervisor.py:31`), BF-308 (live tuning setters), BF-309 (baseline refresh).
**Estimated tests:** +12 pytest, 0 vitest.
**License posture:** 0-line diff (no new deps; pure-PIL strategies).

---

## Problem

`SupervisorStrategy(Protocol)` exists as the v1 forward-marker seam, but
`PerceptualHashStrategy` is the only implementation. Different camera
setups want different admission policies:

- **aHash** (current): good general-purpose. Sensitive to position
  changes; weaker on motion within a static frame.
- **Motion**: catches small object/person motion that aHash misses
  (per-pixel diff after downscale).
- **Scene change**: catches lighting changes + new objects entering via
  HSV histogram delta.
- **Null strategies**: `never` for cost-tight deployments that want
  describe only on force-describe / DM-receive; `always` for tests +
  debugging.

Forward marker file: `src/probos/perception/supervisor.py:9-11` already
reserves AD-742d for this work.

## Solution

Ship 4 new strategy classes implementing the same `SupervisorStrategy`
Protocol. Add operator-selectable choice via
`PerceptionConfig.vision_supervisor_strategy`. Default stays `"ahash"` —
current behavior preserved bit-for-bit. Selection is **restart-required**
(strategy swap re-initializes state); cap/threshold values remain
hot-reload via existing BF-308 setters.

---

## Section 0: Configuration

### File: `src/probos/config.py`

Add to `PerceptionConfig` (anchor after `working_memory_capacity` at line
2005; this section is independent of AD-742f's anchor so build-order
permits either-first):

```
===SEARCH===
    vision_baseline_max_age_seconds: float = Field(default=30.0, ge=0.0, le=600.0,
        description="BF-309: after this many seconds with no admit, the supervisor re-baselines on the next frame. Prevents static-scene anchoring where a steady pose makes every later frame look low-novelty against a stale baseline. 0 = disable.",
    )
    working_memory_capacity: int = Field(default=8, ge=1, le=64,
===REPLACE===
    vision_baseline_max_age_seconds: float = Field(default=30.0, ge=0.0, le=600.0,
        description="BF-309: after this many seconds with no admit, the supervisor re-baselines on the next frame. Prevents static-scene anchoring where a steady pose makes every later frame look low-novelty against a stale baseline. 0 = disable.",
    )
    vision_supervisor_strategy: str = Field(default="ahash",
        description="AD-742d: frame-admission strategy. 'ahash' (default, perceptual-hash diff), 'motion' (per-pixel diff), 'scene_change' (HSV histogram delta), 'never' (drop all frames; describe only on force / DM), 'always' (admit all; debug/test only). Restart required to swap.",
    )
    working_memory_capacity: int = Field(default=8, ge=1, le=64,
===END REPLACE===
```

Pydantic validator (append to the same class, after the field block, BEFORE
the next config class):

```
===SEARCH===
    proactive_novelty_threshold: float = Field(default=0.50, ge=0.0, le=1.0,
        description="Minimum novelty score for a high-novelty proactive trigger (separate from supervisor admission threshold).",
    )


class LipSyncConfig(BaseModel):
===REPLACE===
    proactive_novelty_threshold: float = Field(default=0.50, ge=0.0, le=1.0,
        description="Minimum novelty score for a high-novelty proactive trigger (separate from supervisor admission threshold).",
    )

    @field_validator("vision_supervisor_strategy")
    @classmethod
    def _validate_supervisor_strategy(cls, v: str) -> str:
        allowed = {"ahash", "motion", "scene_change", "never", "always"}
        v = v.strip().lower()
        if v not in allowed:
            raise ValueError(
                f"vision_supervisor_strategy must be one of {sorted(allowed)}, got {v!r}"
            )
        return v


class LipSyncConfig(BaseModel):
===END REPLACE===
```

### File: `src/probos/perception/__init__.py`

Append a FieldDescriptor (NOT hot-reload — strategy swap re-inits state):

```
===SEARCH===
        FieldDescriptor(
            "perception.vision_baseline_max_age_seconds",
            "Baseline refresh window (s)",
            "float",
            description="BF-309: after this many seconds with no admit, re-baseline on the next frame. Prevents static-scene lock-up. 30s default. 0 = disable.",
            hot_reload=True,
        ),
===REPLACE===
        FieldDescriptor(
            "perception.vision_baseline_max_age_seconds",
            "Baseline refresh window (s)",
            "float",
            description="BF-309: after this many seconds with no admit, re-baseline on the next frame. Prevents static-scene lock-up. 30s default. 0 = disable.",
            hot_reload=True,
        ),
        FieldDescriptor(
            "perception.vision_supervisor_strategy",
            "Supervisor strategy",
            "str",
            description="AD-742d: 'ahash' (default), 'motion', 'scene_change', 'never', 'always'. Restart required to swap.",
        ),
===END REPLACE===
```

> If AD-742f's prompt is built first and inserts its own
> `wm_persistence_enabled` FieldDescriptor at the same anchor, replace the
> SEARCH block with the equivalent context including AD-742f's
> FieldDescriptor — the Builder must keep both inserts.

---

## Section 1: Strategy implementations

### File: `src/probos/perception/supervisor.py`

Append AFTER `PerceptualHashStrategy` (and the existing `_ahash_jpeg_bytes`
helper — leave it untouched). Strategies share two helpers (`_decode_frame`,
`_downscale`) to avoid duplicate PIL imports:

```
===SEARCH===
        if novelty < self._threshold:
            return SupervisorDecision(allow=False, novelty_score=novelty, reason="low_novelty")

        self._last_allow_at = now
        self._last_hash = current_hash
        return SupervisorDecision(allow=True, novelty_score=novelty, reason="novel")

===REPLACE===
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
        from PIL import Image
        from io import BytesIO
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
===END REPLACE===
```

---

## Section 2: VisionConsumer wiring

### File: `src/probos/perception/consumer.py`

Replace the hardcoded `PerceptualHashStrategy` in `__init__` with a call to
the resolver. Add a `supervisor_strategy_name` kwarg defaulting to `"ahash"`:

```
===SEARCH===
        max_describe_tokens: int = 220,
        describe_timeout_s: float = 30.0,
    ) -> None:
        from probos.perception.supervisor import (
            PerceptualHashStrategy,
            VisionSupervisor,
        )

        self._runtime = runtime
        self._supervisor = VisionSupervisor(
            strategy=PerceptualHashStrategy(
                min_interval_seconds=min_interval_seconds,
                novelty_threshold=novelty_threshold,
                baseline_max_age_seconds=baseline_max_age_seconds,
            )
        )
===REPLACE===
        max_describe_tokens: int = 220,
        describe_timeout_s: float = 30.0,
        supervisor_strategy_name: str = "ahash",
    ) -> None:
        from probos.perception.supervisor import VisionSupervisor, build_strategy

        self._runtime = runtime
        self._strategy_name = str(supervisor_strategy_name)
        self._supervisor = VisionSupervisor(
            strategy=build_strategy(
                self._strategy_name,
                min_interval_seconds=min_interval_seconds,
                novelty_threshold=novelty_threshold,
                baseline_max_age_seconds=baseline_max_age_seconds,
            )
        )
===END REPLACE===
```

### File: `src/probos/startup/finalize.py`

Thread the config value through (anchor in the same VisionConsumer
construction block):

```
===SEARCH===
            consumer = VisionConsumer(
                runtime,
                min_interval_seconds=_perception_cfg.vision_min_interval_seconds,
                novelty_threshold=_perception_cfg.vision_novelty_threshold,
                baseline_max_age_seconds=_perception_cfg.vision_baseline_max_age_seconds,
                working_memory_capacity=_perception_cfg.working_memory_capacity,
                vision_tier=_perception_cfg.vision_tier,
                vision_fast_tier=_perception_cfg.vision_fast_tier,
            )
===REPLACE===
            consumer = VisionConsumer(
                runtime,
                min_interval_seconds=_perception_cfg.vision_min_interval_seconds,
                novelty_threshold=_perception_cfg.vision_novelty_threshold,
                baseline_max_age_seconds=_perception_cfg.vision_baseline_max_age_seconds,
                working_memory_capacity=_perception_cfg.working_memory_capacity,
                vision_tier=_perception_cfg.vision_tier,
                vision_fast_tier=_perception_cfg.vision_fast_tier,
                supervisor_strategy_name=getattr(
                    _perception_cfg, "vision_supervisor_strategy", "ahash"
                ),
            )
===END REPLACE===
```

---

## Section 3: Tests

### New file: `tests/test_ad742d_pluggable_supervisor.py`

Use real PIL + synthesized JPEG frames (PIL.Image.new + .save to BytesIO).
No MagicMock. BF-287 compliance.

1. `test_strategy_registry_contains_all_five` — assert
   `set(STRATEGY_REGISTRY) == {"ahash", "motion", "scene_change", "never", "always"}`.
2. `test_each_strategy_conforms_to_protocol` — for each strategy class,
   instantiate and assert `isinstance(strat, SupervisorStrategy)` via the
   `@runtime_checkable` Protocol.
3. `test_build_strategy_resolves_each_name` — call `build_strategy` for
   each name, confirm returned instance is the expected class.
4. `test_build_strategy_unknown_name_falls_back_to_ahash` — pass `"clip"`,
   assert returns `PerceptualHashStrategy` instance + WARNING logged
   (use `caplog`).
5. `test_motion_strategy_admits_first_frame` — fresh strategy, call
   `evaluate(jpeg_bytes, now=0)`, assert `allow=True reason="first_frame"`.
6. `test_motion_strategy_throttles_within_interval` — first frame at t=0,
   second frame (different content) at t=0.5 with `min_interval=3`, assert
   `allow=False reason="throttled"`.
7. `test_motion_strategy_admits_on_pixel_diff` — first frame solid red,
   second frame solid blue at t=10, assert `allow=True novelty_score>0.5`.
8. `test_scene_change_strategy_admits_lighting_shift` — synthesize a dark
   frame then a bright frame of the same scene, assert `allow=True
   reason="novel"`.
9. `test_never_strategy_drops_every_frame` — call evaluate 5 times, assert
   all return `allow=False reason="never_strategy"`.
10. `test_always_strategy_admits_every_frame` — call evaluate 5 times,
    assert all return `allow=True reason="always_strategy"`.
11. `test_config_validator_rejects_unknown_strategy` — construct
    `PerceptionConfig(vision_supervisor_strategy="clip")`, assert
    `ValidationError`.
12. `test_consumer_init_uses_configured_strategy` — construct a real
    `VisionConsumer` with `supervisor_strategy_name="motion"` and a real
    runtime stub (just needs `.config.perception` to exist), assert
    `isinstance(consumer._supervisor._strategy, MotionStrategy)`.

### Acceptance: `pytest tests/test_ad742d_pluggable_supervisor.py -v -n 0` → 12 passed.

Also: `pytest tests/test_ad733a_vision_consumer.py -v -n 0` MUST still pass
(default `"ahash"` preserves bit-for-bit behavior).

---

## What this does NOT change

- BF-308 / BF-309 setters — every new strategy implements the same 3
  setters (`set_min_interval_seconds`, `set_novelty_threshold`,
  `set_baseline_max_age_seconds`) so hot-reload of cap values still works
  uniformly. The null strategies (`never`, `always`) accept and ignore.
- PerceptionModeController BF-308 driver path — unchanged. It calls the
  setters via duck-typing; every new strategy responds.
- `_ahash_jpeg_bytes` helper — untouched. Other strategies use the
  `_load_pil_image` helper instead.
- vision_observation intent shape — unchanged.

## Forward markers

- **AD-742d-1** — CLIP-embedding strategy (semantic novelty: "the cat
  walked away" vs "a new mug appeared" classified differently). Requires a
  CLIP pip dep + embedding cache; not in scope tonight. License gate:
  open-clip-torch is MIT but model weights vary.
- **AD-742d-2** — Per-session strategy override (a calibration session
  uses `always`; production sessions use `ahash`). Out of scope tonight;
  config-level switch is sufficient for Captain's current setup.

File both as GitHub issues at wave close.

---

## AD-722c-3 forward-marker triggers

None new.

## License posture

0-line diff on all 5 license files. PIL is already a dependency
(used by `_ahash_jpeg_bytes` and the camera frame pipeline).

## Acceptance criteria

- 12 new pytest in `tests/test_ad742d_pluggable_supervisor.py` green at `-n 0`.
- Full gate `pytest tests/ -q -n 4 --dist=loadfile` net-green vs baseline.
- `tests/test_ad733a_vision_consumer.py` AND `tests/test_ad733c2_mode_controller.py`
  unchanged + still pass (default strategy preserves behavior; BF-308
  setters still operate).
- Captain can switch strategy via Settings panel, restart, and the live
  supervisor uses the new strategy (manual verification step).
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-18)

```
grep -n "class SupervisorStrategy" src/probos/perception/supervisor.py
  31: class SupervisorStrategy(Protocol):

grep -n "class PerceptualHashStrategy" src/probos/perception/supervisor.py
  36: class PerceptualHashStrategy:

grep -n "set_min_interval_seconds\|set_novelty_threshold\|set_baseline_max_age_seconds" src/probos/perception/supervisor.py
  58:     def set_min_interval_seconds(self, value: float) -> None:
  62:     def set_novelty_threshold(self, value: float) -> None:
  66:     def set_baseline_max_age_seconds(self, value: float) -> None:

grep -n "PerceptualHashStrategy" src/probos/perception/consumer.py
  80:         from probos.perception.supervisor import (
  82:             PerceptualHashStrategy,
  88:             strategy=PerceptualHashStrategy(

grep -n "vision_supervisor_strategy" src/probos/config.py
  (no hits — new field)

grep -n "VisionConsumer(" src/probos/startup/finalize.py
  4017:             consumer = VisionConsumer(

grep -n "field_validator" src/probos/config.py
  (multiple existing — pattern confirmed)
```

The Protocol + setter-based driver pattern means VisionConsumer doesn't
need a branching dispatch — the controller's BF-308 calls go through the
strategy interface transparently for all 5 implementations.
