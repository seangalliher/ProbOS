"""AD-1003c: GET /api/packs — read-only installed-pack inventory endpoint.

Surfaces the AD-1003b scanner. Default OFF (packs.enabled=False) -> empty;
when enabled, scans the configured dir. Nothing is installed/loaded/executed.

BF-287: real FastAPI TestClient + real tmp_path pack dirs + a real config-shaped
runtime (SimpleNamespace) — no MagicMock at the boundary.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers import packs as packs_router
from probos.routers.deps import get_runtime


def _client(runtime) -> TestClient:
    app = FastAPI()
    app.include_router(packs_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _runtime(*, enabled: bool, packs_dir: str, data_dir: str | None = None):
    return SimpleNamespace(
        config=SimpleNamespace(packs=SimpleNamespace(enabled=enabled, packs_dir=packs_dir)),
        data_dir=data_dir,
    )


def _write_pack(packs_dir: Path, name: str, manifest: dict) -> None:
    p = packs_dir / name / "plugin.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest), encoding="utf-8")


def test_packs_disabled_returns_empty(tmp_path: Path):
    rt = _runtime(enabled=False, packs_dir=str(tmp_path))
    with _client(rt) as client:
        resp = client.get("/api/packs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["packs"] == []
    assert body["counts"] == {"total": 0, "valid": 0, "error": 0}


def test_packs_enabled_lists_installed(tmp_path: Path):
    packs = tmp_path / "packs"
    _write_pack(packs, "dev-tools", {"name": "dev-tools-pack", "version": "1.0.0", "hooks": "hooks.json"})
    _write_pack(packs, "broken", {"name": "Bad_Name"})  # invalid -> error entry
    rt = _runtime(enabled=True, packs_dir=str(packs))
    with _client(rt) as client:
        resp = client.get("/api/packs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["counts"] == {"total": 2, "valid": 1, "error": 1}
    by_name = {p["name"]: p for p in body["packs"]}
    assert by_name["dev-tools-pack"]["ok"] is True
    assert by_name["dev-tools-pack"]["has_hooks"] is True
    assert by_name["broken"]["ok"] is False


def test_packs_relative_dir_resolved_against_data_dir(tmp_path: Path):
    # packs_dir is relative -> resolved under the runtime data dir.
    data_dir = tmp_path / "datadir"
    _write_pack(data_dir / "data" / "packs", "p1", {"name": "rel-pack"})
    rt = _runtime(enabled=True, packs_dir="data/packs", data_dir=str(data_dir))
    with _client(rt) as client:
        resp = client.get("/api/packs")
    body = resp.json()
    assert [p["name"] for p in body["packs"]] == ["rel-pack"]
    assert body["packs_dir"].endswith("packs")


def test_packs_missing_dir_honest_degrades(tmp_path: Path):
    rt = _runtime(enabled=True, packs_dir=str(tmp_path / "nonexistent"))
    with _client(rt) as client:
        resp = client.get("/api/packs")
    assert resp.status_code == 200
    assert resp.json()["packs"] == []


def test_packs_no_config_returns_empty():
    rt = SimpleNamespace(config=SimpleNamespace())  # no .packs
    with _client(rt) as client:
        resp = client.get("/api/packs")
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
