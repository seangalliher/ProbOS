"""AD-721e: skeletal animation library tests.

Covers:
- AnimationManifest license whitelist (CC0 accepted, AGPL rejected).
- AnimationManifest.get / list_available semantics.
- SHA-256 integrity check on registration when the file is present.
- GET /api/avatars/animations returns empty list when disabled or empty.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.avatars.asset_manifest import AnimationClipEntry, AnimationManifest
from probos.config import AvatarsConfig
from probos.routers.deps import get_runtime


# ---------------------------------------------------------------------------
# AnimationManifest unit tests
# ---------------------------------------------------------------------------


def test_register_accepts_cc0_entry_when_file_missing(tmp_path):
    """File-missing is a legitimate honest-degrade state -- the manifest
    accepts the entry but list_available() will exclude it until the file
    lands. License must still be whitelisted."""
    m = AnimationManifest()
    entry = AnimationClipEntry(
        name="idle",
        file_path=tmp_path / "idle.glb",  # missing on purpose
        sha256="00" * 32,
        license="CC0",
        source_url="https://quaternius.com",
        duration_s=4.2,
    )
    m.register(entry)
    assert m.get("idle") is entry
    # list_available filters to files that exist on disk.
    assert m.list_available() == []


def test_register_rejects_agpl_license(tmp_path):
    """AGPL is not on the AD-721i-1 whitelist; register must raise."""
    m = AnimationManifest()
    entry = AnimationClipEntry(
        name="bad",
        file_path=tmp_path / "bad.glb",
        sha256="00" * 32,
        license="AGPL-3.0",
        source_url="https://example.com",
        duration_s=1.0,
    )
    with pytest.raises(ValueError, match="whitelist"):
        m.register(entry)
    assert m.get("bad") is None


def test_get_returns_none_for_unknown_clip():
    m = AnimationManifest()
    assert m.get("does-not-exist") is None
    assert m.list_available() == []


def test_list_available_returns_registered_names_with_files(tmp_path):
    """list_available is sorted and only contains entries whose files exist."""
    m = AnimationManifest()
    # Two real files + one missing.
    for name in ("idle", "talking"):
        path = tmp_path / f"{name}.glb"
        path.write_bytes(b"GLB-fake-" + name.encode())
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        m.register(AnimationClipEntry(
            name=name, file_path=path, sha256=sha,
            license="CC0", source_url="x", duration_s=1.0,
        ))
    m.register(AnimationClipEntry(
        name="zzz_missing",
        file_path=tmp_path / "zzz_missing.glb",
        sha256="ab" * 32,
        license="CC0",
        source_url="x",
        duration_s=1.0,
    ))
    assert m.list_available() == ["idle", "talking"]


def test_register_rejects_sha_mismatch(tmp_path):
    """When the file is present, register integrity-checks the SHA."""
    m = AnimationManifest()
    path = tmp_path / "tampered.glb"
    path.write_bytes(b"original-bytes")
    # Wrong SHA -- must reject.
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        m.register(AnimationClipEntry(
            name="tampered",
            file_path=path,
            sha256="ff" * 32,  # wrong
            license="CC0",
            source_url="x",
            duration_s=1.0,
        ))


# ---------------------------------------------------------------------------
# GET /api/avatars/animations endpoint tests
# ---------------------------------------------------------------------------


async def _build_client(animations_enabled: bool, animations_dir: Path):
    import probos.routers.avatars as avatars_router_mod

    avatars_cfg = AvatarsConfig(
        animations_enabled=animations_enabled,
        animations_dir=str(animations_dir),
    )
    rt = SimpleNamespace(config=SimpleNamespace(avatars=avatars_cfg))
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test"), rt


@pytest.mark.asyncio
async def test_endpoint_returns_empty_when_animations_disabled(tmp_path):
    async with (await _build_client(False, tmp_path))[0] as ac:
        resp = await ac.get("/api/avatars/animations")
    assert resp.status_code == 200
    assert resp.json() == {"clips": []}


@pytest.mark.asyncio
async def test_endpoint_returns_empty_when_manifest_missing(tmp_path):
    async with (await _build_client(True, tmp_path))[0] as ac:
        resp = await ac.get("/api/avatars/animations")
    assert resp.status_code == 200
    assert resp.json() == {"clips": []}


@pytest.mark.asyncio
async def test_endpoint_lists_clips_from_manifest(tmp_path):
    # Stage a fake clip + manifest.json on disk.
    glb_path = tmp_path / "idle.glb"
    blob = b"GLB-fake-idle"
    glb_path.write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "clips": [
            {
                "name": "idle",
                "file": "idle.glb",
                "sha256": sha,
                "license": "CC0",
                "source_url": "https://quaternius.com",
                "duration_s": 4.2,
            },
            {
                # Skipped: AGPL violates whitelist; endpoint logs and continues.
                "name": "bad_clip",
                "file": "bad.glb",
                "sha256": "ff" * 32,
                "license": "AGPL-3.0",
                "source_url": "https://example.com",
                "duration_s": 1.0,
            },
        ],
    }), encoding="utf-8")

    async with (await _build_client(True, tmp_path))[0] as ac:
        resp = await ac.get("/api/avatars/animations")
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, dict)
    names = [c["name"] for c in payload["clips"]]
    assert names == ["idle"]
    assert payload["clips"][0]["url"] == "/api/avatars/animations/idle"
    assert payload["clips"][0]["license"] == "CC0"
    assert payload["clips"][0]["duration_s"] == 4.2


@pytest.mark.asyncio
async def test_endpoint_clip_bytes_404_on_unknown(tmp_path):
    async with (await _build_client(True, tmp_path))[0] as ac:
        resp = await ac.get("/api/avatars/animations/no_such_clip")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_clip_bytes_rejects_path_traversal(tmp_path):
    async with (await _build_client(True, tmp_path))[0] as ac:
        resp = await ac.get("/api/avatars/animations/..%2Fetc%2Fpasswd")
    # FastAPI URL-decodes %2F so the path arg includes a slash; the inline
    # sanity check rejects with 400.
    # If the request resolves to a different route shape due to encoding,
    # accept either 400 or 404 as a non-leak.
    assert resp.status_code in (400, 404)
