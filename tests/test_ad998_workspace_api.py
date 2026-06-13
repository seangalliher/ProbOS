"""AD-998: GET /api/agent/{id}/workspace — the working-folder read surface.

BF-287: a REAL ``ExecutionConfig`` at the config boundary (a MagicMock would
make ``getattr(cfg, "enabled", False)`` truthy and defeat the gating). The
workspace is seeded on disk under tmp_path so the file listing is real.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from probos.config import AuthConfig, ExecutionConfig


def _client(tmp_path: Path, *, enabled=True, persistent=True, agent=None):
    from probos.api import create_app

    exec_cfg = ExecutionConfig(
        enabled=enabled,
        persistent_workspaces=persistent,
        workspace_root=str(tmp_path / "ws"),
    )
    agent = agent or SimpleNamespace(id="cr-1", callsign="", agent_type="code_runner")
    runtime = MagicMock()
    runtime.registry.get = MagicMock(return_value=agent)
    cfg = MagicMock()
    cfg.execution = exec_cfg          # REAL config (not a mock) — gating depends on it
    cfg.auth = AuthConfig()
    runtime.config = cfg
    return TestClient(create_app(runtime)), runtime


def _seed(tmp_path: Path, owner: str, name: str, body: str) -> None:
    ws = tmp_path / "ws" / owner
    ws.mkdir(parents=True, exist_ok=True)
    (ws / name).write_text(body, encoding="utf-8")


def test_workspace_lists_files(tmp_path: Path):
    _seed(tmp_path, "code_runner", "result.txt", "hello")
    client, _ = _client(tmp_path)
    resp = client.get("/api/agent/cr-1/workspace")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["persistent"] is True
    assert body["owner"] == "code_runner"
    assert body["exists"] is True
    assert body["path"].endswith("code_runner")
    names = {f["name"] for f in body["files"]}
    assert "result.txt" in names
    assert body["total_bytes"] >= 5


def test_workspace_empty_when_no_runs(tmp_path: Path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/agent/cr-1/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["exists"] is False
    assert body["files"] == []


def test_workspace_disabled_reports_off(tmp_path: Path):
    _seed(tmp_path, "code_runner", "x.txt", "x")  # files present but execution off
    client, _ = _client(tmp_path, enabled=False)
    resp = client.get("/api/agent/cr-1/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["path"] is None
    assert body["files"] == []


def test_workspace_ephemeral_reports_nothing_to_show(tmp_path: Path):
    client, _ = _client(tmp_path, persistent=False)
    resp = client.get("/api/agent/cr-1/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["persistent"] is False
    assert body["path"] is None


def test_workspace_keyed_by_callsign(tmp_path: Path):
    _seed(tmp_path, "ezri", "note.md", "hi")
    agent = SimpleNamespace(id="counselor-1", callsign="Ezri", agent_type="counselor")
    client, _ = _client(tmp_path, agent=agent)
    resp = client.get("/api/agent/counselor-1/workspace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner"] == "ezri"
    assert {f["name"] for f in body["files"]} == {"note.md"}


def test_workspace_unknown_agent_404(tmp_path: Path):
    client, runtime = _client(tmp_path)
    runtime.registry.get = MagicMock(return_value=None)
    resp = client.get("/api/agent/ghost/workspace")
    assert resp.status_code == 404
