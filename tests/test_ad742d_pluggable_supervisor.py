"""AD-742d: pluggable supervisor strategies (motion / scene_change / never / always)."""
from __future__ import annotations

import logging
from io import BytesIO
from types import SimpleNamespace

import pytest

from probos.config import PerceptionConfig
from probos.perception.supervisor import (
    STRATEGY_REGISTRY,
    AlwaysAdmitStrategy,
    MotionStrategy,
    NeverDescribeStrategy,
    PerceptualHashStrategy,
    SceneChangeStrategy,
    SupervisorStrategy,
    build_strategy,
)


def _solid_jpeg(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    """Make a solid-color JPEG via PIL."""
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_strategy_registry_contains_all_five() -> None:
    assert set(STRATEGY_REGISTRY) == {"ahash", "motion", "scene_change", "never", "always"}


def test_each_strategy_conforms_to_protocol() -> None:
    for name in ("ahash", "motion", "scene_change", "never", "always"):
        strat = build_strategy(
            name,
            min_interval_seconds=1.0,
            novelty_threshold=0.1,
            baseline_max_age_seconds=30.0,
        )
        assert isinstance(strat, SupervisorStrategy)


def test_build_strategy_resolves_each_name() -> None:
    pairs = [
        ("ahash", PerceptualHashStrategy),
        ("motion", MotionStrategy),
        ("scene_change", SceneChangeStrategy),
        ("never", NeverDescribeStrategy),
        ("always", AlwaysAdmitStrategy),
    ]
    for name, cls in pairs:
        s = build_strategy(
            name,
            min_interval_seconds=1.0,
            novelty_threshold=0.1,
            baseline_max_age_seconds=30.0,
        )
        assert isinstance(s, cls)


def test_build_strategy_unknown_name_falls_back_to_ahash(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="probos.perception.supervisor"):
        s = build_strategy(
            "clip",
            min_interval_seconds=1.0,
            novelty_threshold=0.1,
            baseline_max_age_seconds=30.0,
        )
    assert isinstance(s, PerceptualHashStrategy)
    assert any("AD-742d" in r.message and "unknown" in r.message for r in caplog.records)


def test_motion_strategy_admits_first_frame() -> None:
    s = MotionStrategy(min_interval_seconds=3.0, novelty_threshold=0.04)
    d = s.evaluate(_solid_jpeg((10, 10, 10)), now=0.0)
    assert d.allow is True
    assert d.reason == "first_frame"


def test_motion_strategy_throttles_within_interval() -> None:
    s = MotionStrategy(min_interval_seconds=3.0, novelty_threshold=0.04)
    s.evaluate(_solid_jpeg((10, 10, 10)), now=0.0)
    d = s.evaluate(_solid_jpeg((200, 200, 200)), now=0.5)
    assert d.allow is False
    assert d.reason == "throttled"


def test_motion_strategy_admits_on_pixel_diff() -> None:
    s = MotionStrategy(min_interval_seconds=1.0, novelty_threshold=0.04,
                      baseline_max_age_seconds=0.0)
    s.evaluate(_solid_jpeg((10, 10, 10)), now=0.0)
    d = s.evaluate(_solid_jpeg((250, 250, 250)), now=10.0)
    assert d.allow is True
    assert d.novelty_score > 0.5
    assert d.reason == "novel"


def test_scene_change_strategy_admits_lighting_shift() -> None:
    s = SceneChangeStrategy(min_interval_seconds=1.0, novelty_threshold=0.10,
                            baseline_max_age_seconds=0.0)
    # First a dark frame, then a bright frame — large value-channel delta.
    s.evaluate(_solid_jpeg((10, 10, 10)), now=0.0)
    d = s.evaluate(_solid_jpeg((250, 250, 250)), now=5.0)
    assert d.allow is True
    assert d.reason == "novel"


def test_never_strategy_drops_every_frame() -> None:
    s = NeverDescribeStrategy()
    for i in range(5):
        d = s.evaluate(_solid_jpeg((i * 40, 0, 0)), now=float(i))
        assert d.allow is False
        assert d.reason == "never_strategy"


def test_always_strategy_admits_every_frame() -> None:
    s = AlwaysAdmitStrategy()
    for i in range(5):
        d = s.evaluate(_solid_jpeg((i * 40, 0, 0)), now=float(i))
        assert d.allow is True
        assert d.reason == "always_strategy"


def test_config_validator_rejects_unknown_strategy() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PerceptionConfig(vision_supervisor_strategy="clip")


def test_consumer_init_uses_configured_strategy() -> None:
    from probos.perception.consumer import VisionConsumer
    # Real runtime stub — just needs .config.perception present for any
    # introspection paths. VisionConsumer.__init__ only reads kwargs.
    runtime = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig()),
    )
    consumer = VisionConsumer(runtime, supervisor_strategy_name="motion")
    assert isinstance(consumer._supervisor._strategy, MotionStrategy)
