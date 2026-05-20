"""AD-746 Layer 2 — Per-agent ``bound_sources`` filtering contract tests.

Verifies the ``PerceptionProfile.bound_sources`` field and
``VisionConsumer._filter_by_bound_sources`` semantics.
"""
from __future__ import annotations

from probos.crew_profile import PerceptionProfile


def test_default_bound_sources_is_both() -> None:
    """Default ``bound_sources`` = ['camera','screen'] (back-compat).
    Legacy profile JSON that omits the field reads the same."""
    p = PerceptionProfile()
    assert p.bound_sources == ["camera", "screen"]
    # from_dict on a legacy JSON without the key.
    legacy = PerceptionProfile.from_dict({})
    assert legacy.bound_sources == ["camera", "screen"]


def test_bound_sources_filter_restricts_wm_fan_out() -> None:
    """An agent bound to ``['camera']`` is dropped for a screen-only frame."""
    from unittest.mock import MagicMock
    from probos.perception.consumer import VisionConsumer
    from probos.config import SystemConfig

    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.intent_bus = MagicMock()

    # Real ProfileStore would be heavy here — we stub the .get() shape.
    profile_store = MagicMock()
    counselor_profile = MagicMock()
    counselor_profile.perception = PerceptionProfile(bound_sources=["camera"])
    ops_profile = MagicMock()
    ops_profile.perception = PerceptionProfile(bound_sources=["screen"])
    legacy_profile = MagicMock()
    legacy_profile.perception = PerceptionProfile()  # default both
    profile_store.get.side_effect = lambda aid: {
        "counselor": counselor_profile,
        "ops": ops_profile,
        "legacy": legacy_profile,
    }.get(aid)
    runtime.profile_store = profile_store

    consumer = VisionConsumer(runtime)
    # Screen-only frame.
    kept = consumer._filter_by_bound_sources(
        ["counselor", "ops", "legacy"], ["screen"],
    )
    assert "counselor" not in kept  # camera-bound; screen frame excluded
    assert "ops" in kept
    assert "legacy" in kept


def test_bound_sources_fused_visible_if_any_intersect() -> None:
    """Fused (camera+screen) tick: an agent bound to just camera should
    still see it (one source matches)."""
    from unittest.mock import MagicMock
    from probos.perception.consumer import VisionConsumer
    from probos.config import SystemConfig

    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.intent_bus = MagicMock()
    profile_store = MagicMock()
    p = MagicMock()
    p.perception = PerceptionProfile(bound_sources=["camera"])
    profile_store.get.return_value = p
    runtime.profile_store = profile_store
    consumer = VisionConsumer(runtime)
    kept = consumer._filter_by_bound_sources(["counselor"], ["camera", "screen"])
    assert kept == ["counselor"]


def test_bound_sources_invalid_values_dropped_in_post_init() -> None:
    """__post_init__ filters out unknown source names + dedupes."""
    p = PerceptionProfile(bound_sources=["camera", "audio", "camera", "screen"])
    assert p.bound_sources == ["camera", "screen"]
