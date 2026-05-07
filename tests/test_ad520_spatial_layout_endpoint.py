"""AD-520: Tests for GET /api/ontology/spatial-layout."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from probos.ontology.spatial import _DEFAULT_LAYOUT
from probos.routers.ontology import get_spatial_layout


@pytest.mark.asyncio
async def test_spatial_layout_returns_503_when_not_wired() -> None:
    rt = MagicMock()
    rt.spatial_layout = None
    res = await get_spatial_layout(runtime=rt)
    assert getattr(res, "status_code", 200) == 503


@pytest.mark.asyncio
async def test_spatial_layout_happy_path_returns_default_shape() -> None:
    rt = MagicMock()
    rt.spatial_layout = _DEFAULT_LAYOUT
    res = await get_spatial_layout(runtime=rt)
    assert isinstance(res, dict)
    assert res["schema_version"] == 1
    assert len(res["decks"]) >= 6
    deck_ids = {d["deck_id"] for d in res["decks"]}
    assert {"bridge", "engineering", "sickbay", "tactical", "science_lab", "computer_core"}.issubset(deck_ids)
