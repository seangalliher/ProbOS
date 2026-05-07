"""AD-520: Tests for _wire_spatial_explorer."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.config import SpatialExplorerConfig
from probos.ontology.spatial import SpatialLayout
from probos.startup.finalize import _wire_spatial_explorer


def _make_config(*, enabled: bool, path: str = "") -> MagicMock:
    cfg = MagicMock()
    cfg.spatial_explorer = SpatialExplorerConfig(enabled=enabled, spatial_layout_path=path)
    return cfg


def test_wire_spatial_explorer_skips_when_disabled() -> None:
    rt = MagicMock()
    rt.spatial_layout = None
    cfg = _make_config(enabled=False)
    assert _wire_spatial_explorer(runtime=rt, config=cfg) is False
    assert rt.spatial_layout is None


def test_wire_spatial_explorer_constructs_layout_when_enabled() -> None:
    rt = MagicMock()
    rt.spatial_layout = None
    cfg = _make_config(enabled=True, path="")
    assert _wire_spatial_explorer(runtime=rt, config=cfg) is True
    assert isinstance(rt.spatial_layout, SpatialLayout)
    assert len(rt.spatial_layout.decks) >= 6
