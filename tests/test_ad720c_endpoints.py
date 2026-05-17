"""AD-720c: cloud-picker REST endpoint tests.

Real ``SystemConfig`` (BF-287: no MagicMock at the config boundary). Real
``EncryptedFileCredentialVault`` per BF-287 substrate-boundary rule. The
HTTP layer is exercised with ``httpx.MockTransport`` injected via the
provider's ``http_client_factory``.

AD-731 invariant: the ``/attach`` endpoint response carries only the SHA
ref + metadata; the file bytes are stored in ``AttachmentStore``. Tests
assert the response body contains ``attachment_id`` (sha256) and NOT
``blob_b64`` / raw bytes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from probos.api import create_app
from probos.cloud_pickers import google_drive as gd_module
from probos.cloud_pickers.tokens import OAuthTokenBundle
from probos.config import SystemConfig
from probos.routers.cloud_pickers import _clear_state_stores
from probos.tools.browser.credentials import (
    CredentialScope,
    EncryptedFileCredentialVault,
    _derive_kek,
)


# ── Helpers ─────────────────────────────────────────────────────


def _build_config(tmp_path: Path, *, enabled: bool = True, provider_configured: bool = True) -> SystemConfig:
    cfg = SystemConfig()
    cfg.cloud_pickers.enabled = enabled
    if provider_configured:
        cfg.cloud_pickers.google_drive.enabled = True
        cfg.cloud_pickers.google_drive.client_id = "test-cid"
        cfg.cloud_pickers.google_drive.client_secret = "test-csec"
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    return cfg


def _build_vault(tmp_path: Path) -> EncryptedFileCredentialVault:
    token = "wave168-test-crew-token"
    return EncryptedFileCredentialVault(
        path=tmp_path / "vault.json",
        kek=_derive_kek(token),
        crew_scope_token=token,
    )


def _build_runtime(cfg: SystemConfig, vault: Any = None) -> MagicMock:
    """Minimal MagicMock runtime carrying a REAL config + REAL vault.

    BF-287: config and vault are the substrate boundary — they must be
    real. The remaining runtime surface (registry, intent_bus, etc.) is
    untouched by the cloud-pickers router and stays MagicMock.
    """
    runtime = MagicMock()
    runtime.config = cfg
    runtime.credential_vault = vault
    runtime.add_event_listener = MagicMock()
    return runtime


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Patch :class:`GoogleDriveProvider` to inject the mock transport."""
    original = gd_module.GoogleDriveProvider.__init__

    def _patched_init(self, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["http_client_factory"] = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), timeout=5.0
        )
        original(self, **kwargs)

    monkeypatch.setattr(gd_module.GoogleDriveProvider, "__init__", _patched_init)


@pytest.fixture(autouse=True)
def _reset_state_stores():
    _clear_state_stores()
    yield
    _clear_state_stores()


# ── Tests ──────────────────────────────────────────────────────


def test_start_endpoint_503_when_feature_disabled(tmp_path: Path) -> None:
    cfg = _build_config(tmp_path, enabled=False)
    runtime = _build_runtime(cfg, vault=_build_vault(tmp_path))
    client = TestClient(create_app(runtime))
    r = client.post("/api/cloud-pickers/google_drive/start")
    assert r.status_code == 503
    assert r.json()["detail"] == "feature_disabled"


def test_start_endpoint_503_when_vault_unavailable(tmp_path: Path) -> None:
    cfg = _build_config(tmp_path)
    runtime = _build_runtime(cfg, vault=None)
    client = TestClient(create_app(runtime))
    r = client.post("/api/cloud-pickers/google_drive/start")
    assert r.status_code == 503
    assert r.json()["detail"] == "credential_vault_unavailable"


def test_start_endpoint_503_when_provider_not_configured(tmp_path: Path) -> None:
    cfg = _build_config(tmp_path, provider_configured=False)
    cfg.cloud_pickers.google_drive.enabled = True  # enabled but missing creds
    runtime = _build_runtime(cfg, vault=_build_vault(tmp_path))
    client = TestClient(create_app(runtime))
    r = client.post("/api/cloud-pickers/google_drive/start")
    assert r.status_code == 503
    assert r.json()["detail"] == "provider_not_configured"


def test_start_endpoint_returns_auth_url_and_state(tmp_path: Path) -> None:
    cfg = _build_config(tmp_path)
    runtime = _build_runtime(cfg, vault=_build_vault(tmp_path))
    client = TestClient(create_app(runtime))
    r = client.post("/api/cloud-pickers/google_drive/start")
    assert r.status_code == 200
    body = r.json()
    assert body["auth_url"].startswith("https://accounts.google.com/")
    assert "access_type=offline" in body["auth_url"]
    assert "prompt=consent" in body["auth_url"]
    assert isinstance(body["state"], str) and len(body["state"]) >= 32


def test_callback_invalid_state_returns_403(tmp_path: Path, monkeypatch) -> None:
    cfg = _build_config(tmp_path)
    runtime = _build_runtime(cfg, vault=_build_vault(tmp_path))
    _install_mock_transport(monkeypatch, lambda req: httpx.Response(200, json={}))
    client = TestClient(create_app(runtime))
    r = client.get(
        "/api/cloud-pickers/google_drive/callback",
        params={"code": "c", "state": "not-minted"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid_state_token"


def test_callback_round_trip_persists_bundle_in_vault(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _build_config(tmp_path)
    vault = _build_vault(tmp_path)
    runtime = _build_runtime(cfg, vault=vault)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.fake",
                "refresh_token": "1//refresh-fake",
                "expires_in": 3600,
            },
        )

    _install_mock_transport(monkeypatch, handler)
    client = TestClient(create_app(runtime))
    # Mint state via /start so callback can consume it.
    start = client.post("/api/cloud-pickers/google_drive/start").json()
    state = start["state"]
    r = client.get(
        "/api/cloud-pickers/google_drive/callback",
        params={"code": "auth-c", "state": state},
    )
    assert r.status_code == 200
    # Bundle is in the vault under the AD-706f ref shape.
    import asyncio

    raw = asyncio.run(
        vault.read(
            ref="cloud_provider:google_drive:captain",
            requesting_agent_id="captain",
        )
    )
    assert raw is not None
    bundle = OAuthTokenBundle.model_validate_json(raw)
    assert bundle.access_token == "ya29.fake"
    assert bundle.refresh_token == "1//refresh-fake"


def test_list_files_returns_401_when_no_token_in_vault(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _build_config(tmp_path)
    runtime = _build_runtime(cfg, vault=_build_vault(tmp_path))
    _install_mock_transport(monkeypatch, lambda req: httpx.Response(200, json={}))
    client = TestClient(create_app(runtime))
    r = client.get("/api/cloud-pickers/google_drive/files")
    assert r.status_code == 401
    assert r.json()["detail"] == "oauth_not_authorized"


def test_attach_endpoint_returns_sha_ref_not_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    """AD-731 invariant: response contains attachment_id (sha256), NOT raw bytes."""
    cfg = _build_config(tmp_path)
    vault = _build_vault(tmp_path)
    runtime = _build_runtime(cfg, vault=vault)

    # Pre-seed the vault with a valid bundle so /attach can proceed.
    import asyncio
    bundle = OAuthTokenBundle(access_token="access-1", refresh_token="r-1")
    asyncio.run(
        vault.store(
            ref="cloud_provider:google_drive:captain",
            value=bundle.model_dump_json(),
            scope=CredentialScope(),
        )
    )

    # Mock provider: meta GET returns a PNG; media GET returns valid PNG bytes.
    # PNG magic header chosen so AD-720a magic-byte validator accepts it.
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        if "alt=media" in str(req.url):
            return httpx.Response(200, content=png_bytes)
        return httpx.Response(
            200,
            json={
                "id": "fid",
                "name": "pixel.png",
                "mimeType": "image/png",
                "size": str(len(png_bytes)),
            },
        )

    _install_mock_transport(monkeypatch, handler)
    client = TestClient(create_app(runtime))
    r = client.post(
        "/api/cloud-pickers/google_drive/attach",
        json={"file_id": "fid"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # AD-731 invariant: response carries the SHA ref + metadata, NOT bytes.
    assert "attachment_id" in body
    assert len(body["attachment_id"]) == 64  # sha256 hex
    assert body["mime"] == "image/png"
    assert body["size_bytes"] == len(png_bytes)
    assert "blob_b64" not in body
    assert "blob" not in body
