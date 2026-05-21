"""AD-763: M365 connectors router tests.

Per principles: tests use real SystemConfig instances; only the token manager
and httpx layer are mocked. The Phantom-via-MagicMock anti-pattern (BF-287) is
avoided by referencing `runtime.config` as a real Pydantic model.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import ProactiveScanConfig, SystemConfig
from probos.routers.connectors import router


def _make_runtime(token: str | None = "tok-123") -> Any:
    """Build a runtime whose config is a real SystemConfig and whose token
    manager honest-degrades to the chosen value."""
    runtime = MagicMock()
    runtime.config = SystemConfig()  # real, validates field accesses
    if token is None:
        runtime._m365_token_manager = None
    else:
        tm = MagicMock()
        tm.get_token = AsyncMock(return_value=token)
        runtime._m365_token_manager = tm
    return runtime


@pytest.fixture
def app_with_runtime() -> tuple[FastAPI, Any]:
    app = FastAPI()
    app.include_router(router)
    return app, None


def _client(runtime: Any) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


# ── /m365/mail-folders ────────────────────────────────────────────────


class TestMailFoldersEndpoint:
    def test_mail_folders_happy_path(self) -> None:
        runtime = _make_runtime()
        graph_body = {
            "value": [
                {"id": "f1", "displayName": "Inbox", "parentFolderId": None, "totalItemCount": 7},
                {"id": "f2", "displayName": "Archive", "parentFolderId": "f1", "totalItemCount": 100},
            ]
        }
        with patch("probos.routers.connectors._graph_get", AsyncMock(return_value=(200, graph_body))):
            res = _client(runtime).get("/api/connectors/m365/mail-folders")
        assert res.status_code == 200
        data = res.json()
        assert len(data["folders"]) == 2
        assert data["folders"][0]["displayName"] == "Inbox"

    def test_mail_folders_401_when_no_token(self) -> None:
        runtime = _make_runtime(token=None)
        res = _client(runtime).get("/api/connectors/m365/mail-folders")
        assert res.status_code == 401

    def test_mail_folders_502_when_graph_down(self) -> None:
        runtime = _make_runtime()
        with patch("probos.routers.connectors._graph_get", AsyncMock(return_value=(0, None))):
            res = _client(runtime).get("/api/connectors/m365/mail-folders")
        assert res.status_code == 502


# ── /m365/calendars ───────────────────────────────────────────────────


class TestCalendarsEndpoint:
    def test_calendars_happy_path(self) -> None:
        runtime = _make_runtime()
        graph_body = {
            "value": [
                {"id": "c1", "name": "Calendar", "isDefaultCalendar": True, "canEdit": True},
                {"id": "c2", "name": "Team", "isDefaultCalendar": False, "canEdit": False},
            ]
        }
        with patch("probos.routers.connectors._graph_get", AsyncMock(return_value=(200, graph_body))):
            res = _client(runtime).get("/api/connectors/m365/calendars")
        assert res.status_code == 200
        data = res.json()
        assert len(data["calendars"]) == 2
        assert data["calendars"][0]["isDefaultCalendar"] is True

    def test_calendars_401_when_no_token(self) -> None:
        runtime = _make_runtime(token=None)
        res = _client(runtime).get("/api/connectors/m365/calendars")
        assert res.status_code == 401

    def test_calendars_502_when_graph_500(self) -> None:
        runtime = _make_runtime()
        with patch("probos.routers.connectors._graph_get", AsyncMock(return_value=(500, None))):
            res = _client(runtime).get("/api/connectors/m365/calendars")
        assert res.status_code == 502


# ── /scan-config ──────────────────────────────────────────────────────


class TestScanConfigEndpoints:
    def test_get_returns_defaults(self) -> None:
        runtime = _make_runtime()
        res = _client(runtime).get("/api/connectors/scan-config")
        assert res.status_code == 200
        data = res.json()
        assert data["inbox"]["folders"] == ["Inbox"]
        assert data["calendar"]["calendar_ids"] == ["primary"]
        assert data["inbox"]["importance_filter"] == "any"

    def test_put_round_trip(self) -> None:
        runtime = _make_runtime()
        client = _client(runtime)
        payload = {
            "inbox": {
                "folders": ["Inbox", "Important"],
                "importance_filter": "high",
                "unread_only": True,
            },
            "calendar": {"calendar_ids": ["team"]},
        }
        put_res = client.put("/api/connectors/scan-config", json=payload)
        assert put_res.status_code == 200
        persisted = put_res.json()
        assert persisted["inbox"]["folders"] == ["Inbox", "Important"]
        assert persisted["inbox"]["importance_filter"] == "high"
        assert persisted["inbox"]["unread_only"] is True
        assert persisted["calendar"]["calendar_ids"] == ["team"]
        # GET should now reflect the change
        get_res = client.get("/api/connectors/scan-config")
        assert get_res.status_code == 200
        assert get_res.json()["inbox"]["folders"] == ["Inbox", "Important"]

    def test_put_validation_rejects_bad_importance(self) -> None:
        runtime = _make_runtime()
        res = _client(runtime).put(
            "/api/connectors/scan-config",
            json={"inbox": {"importance_filter": "medium"}},
        )
        assert res.status_code == 422

    def test_put_rejects_non_object_inbox(self) -> None:
        runtime = _make_runtime()
        res = _client(runtime).put(
            "/api/connectors/scan-config",
            json={"inbox": "garbage"},
        )
        assert res.status_code == 400

    def test_put_preserves_unchanged_section(self) -> None:
        runtime = _make_runtime()
        client = _client(runtime)
        # Set calendar first
        client.put("/api/connectors/scan-config", json={"calendar": {"lookahead_hours": 48}})
        # Then change only inbox
        res = client.put("/api/connectors/scan-config", json={"inbox": {"lookback_hours": 6}})
        assert res.status_code == 200
        data = res.json()
        assert data["inbox"]["lookback_hours"] == 6
        assert data["calendar"]["lookahead_hours"] == 48  # preserved

    def test_get_does_not_require_token(self) -> None:
        """scan-config is local config; no token needed."""
        runtime = _make_runtime(token=None)
        res = _client(runtime).get("/api/connectors/scan-config")
        assert res.status_code == 200

    def test_put_does_not_require_token(self) -> None:
        runtime = _make_runtime(token=None)
        res = _client(runtime).put("/api/connectors/scan-config", json={})
        assert res.status_code == 200
