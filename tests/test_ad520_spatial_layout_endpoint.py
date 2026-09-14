"""AD-520: Tests for GET /api/ontology/spatial-layout."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from unittest.mock import MagicMock

from probos.config import SystemConfig
from probos.ontology.spatial import _DEFAULT_LAYOUT
from probos.routers.ontology import get_spatial_layout, router


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


def _app(config: object | None, layout: object | None = None) -> FastAPI:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(config=config, spatial_layout=layout)
    app.include_router(router)
    return app


@pytest.mark.parametrize("enabled", [False, True, None])
def test_spatial_layout_missing_http_availability(enabled: bool | None) -> None:
    config = None if enabled is None else SystemConfig.model_validate({
        "spatial_explorer": {"enabled": enabled},
    })
    with TestClient(_app(config)) as client:
        response = client.get("/api/ontology/spatial-layout")
    assert response.status_code == 503
    assert response.json()["error"] == (
        "Spatial explorer not enabled" if enabled is False else "Spatial layout not available"
    )
    assert response.json()["availability"]["state"] == ("disabled" if enabled is False else "unavailable")
    assert response.json()["availability"]["retryable"] is (enabled is not False)


class _FakeLayout:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def to_dict(self) -> Any:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.mark.parametrize("payload", [_DEFAULT_LAYOUT.to_dict(), {"schema_version": 1, "decks": []}])
def test_spatial_layout_success_http_body_unchanged(payload: dict[str, Any]) -> None:
    layout = _FakeLayout(payload)
    with TestClient(_app(SystemConfig(), layout)) as client:
        response = client.get("/api/ontology/spatial-layout")
    assert layout.calls == 1
    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.parametrize("raises", [False, True])
def test_spatial_layout_read_failure_http_controlled(
    raises: bool, caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "token=private C:/private/layout.yaml"
    layout = _FakeLayout(error=OSError(secret) if raises else None)
    with TestClient(_app(SystemConfig(), layout)) as client:
        response = client.get("/api/ontology/spatial-layout")
    assert layout.calls == 1
    assert response.status_code == 500
    assert response.json() == {
        "error": "Spatial layout unavailable",
        "availability": {
            "state": "failed", "code": "spatial_explorer.read_failed",
            "message": "Spatial layout unavailable", "retryable": True,
        },
    }
    assert "returning HTTP 500" in caplog.text
    assert secret not in response.text + caplog.text


@pytest.mark.parametrize("status", [401, 403])
def test_spatial_layout_http_authorization_not_reclassified(status: int) -> None:
    layout = _FakeLayout(error=HTTPException(status_code=status, detail="Access denied"))
    with TestClient(_app(SystemConfig(), layout)) as client:
        response = client.get("/api/ontology/spatial-layout")
    assert layout.calls == 1
    assert response.status_code == status
    assert response.json() == {"detail": "Access denied"}
