"""AD-520: Tests for _wire_spatial_explorer."""

from __future__ import annotations

from types import SimpleNamespace

from probos.config import SpatialExplorerConfig, SystemConfig
from probos.ontology.spatial import SpatialLayout
from probos.startup.finalize import _wire_spatial_explorer


def _make_config(*, enabled: bool, path: str = "") -> SystemConfig:
    # BF-653: a REAL SystemConfig (not a MagicMock) so this test fails if
    # ``spatial_explorer`` is ever dropped from the model again -- it was
    # silently glued into the ``tts`` line's comment for ~6 weeks, so
    # ``getattr(config, "spatial_explorer", None)`` was always None and
    # ``_wire_spatial_explorer`` was dead. A MagicMock config masked that.
    return SystemConfig(
        spatial_explorer=SpatialExplorerConfig(enabled=enabled, spatial_layout_path=path)
    )


def test_spatial_explorer_is_a_registered_systemconfig_field() -> None:
    # BF-653 regression: the field must exist on the REAL model, not just a mock.
    assert "spatial_explorer" in SystemConfig.model_fields
    assert isinstance(SystemConfig().spatial_explorer, SpatialExplorerConfig)


def test_wire_spatial_explorer_skips_when_disabled() -> None:
    rt = SimpleNamespace(spatial_layout=None)
    cfg = _make_config(enabled=False)
    assert _wire_spatial_explorer(runtime=rt, config=cfg) is False
    assert rt.spatial_layout is None


def test_wire_spatial_explorer_constructs_layout_when_enabled() -> None:
    rt = SimpleNamespace(spatial_layout=None)
    cfg = _make_config(enabled=True, path="")
    assert _wire_spatial_explorer(runtime=rt, config=cfg) is True
    assert isinstance(rt.spatial_layout, SpatialLayout)
    assert len(rt.spatial_layout.decks) >= 6
