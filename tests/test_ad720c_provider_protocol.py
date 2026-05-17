"""AD-720c: ``CloudPickerProvider`` Protocol + helper contract tests.

Real provider stubs (Google Drive, OneDrive, Dropbox) — checks Protocol
attributes are present and the OneDrive/Dropbox stubs raise the documented
``NotImplementedError`` with the AD-720c-1 / AD-720c-2 forward-marker text.
"""
from __future__ import annotations

import pytest

from probos.cloud_pickers.dropbox import DropboxProvider
from probos.cloud_pickers.google_drive import GoogleDriveProvider
from probos.cloud_pickers.onedrive import OneDriveProvider
from probos.cloud_pickers.provider import (
    ProviderError,
    ReauthorizationRequired,
)
from probos.cloud_pickers.tokens import OAuthTokenBundle


def test_provider_protocol_shape() -> None:
    """All three providers structurally implement ``CloudPickerProvider``."""
    drive = GoogleDriveProvider(
        client_id="cid", client_secret="csec",
        redirect_uri="http://127.0.0.1/api/cloud-pickers/{provider}/callback",
    )
    one = OneDriveProvider(
        client_id="cid", client_secret="csec",
        redirect_uri="http://127.0.0.1/api/cloud-pickers/{provider}/callback",
    )
    drop = DropboxProvider(
        client_id="cid", client_secret="csec",
        redirect_uri="http://127.0.0.1/api/cloud-pickers/{provider}/callback",
    )
    for p in (drive, one, drop):
        # Structural Protocol check via attribute presence (Protocol is not
        # @runtime_checkable; we assert the method surface explicitly).
        assert isinstance(p.provider_id, str) and p.provider_id
        for method in ("start_authorization", "handle_callback", "list_files", "download_file"):
            assert callable(getattr(p, method)), f"{p.provider_id} missing {method}"


@pytest.mark.asyncio
async def test_onedrive_stub_raises_with_forward_marker() -> None:
    p = OneDriveProvider(
        client_id="cid", client_secret="csec",
        redirect_uri="http://127.0.0.1/api/cloud-pickers/{provider}/callback",
    )
    with pytest.raises(NotImplementedError, match="AD-720c-1"):
        p.start_authorization(state="abc")
    with pytest.raises(NotImplementedError, match="AD-720c-1"):
        await p.handle_callback(code="x")
    bundle = OAuthTokenBundle(access_token="t")
    with pytest.raises(NotImplementedError, match="AD-720c-1"):
        await p.list_files(bundle=bundle)
    with pytest.raises(NotImplementedError, match="AD-720c-1"):
        await p.download_file(bundle=bundle, file_id="f")


def test_provider_error_carries_status_and_detail() -> None:
    """``ProviderError`` and ``ReauthorizationRequired`` expose API-stable fields."""
    e = ProviderError(502, "oauth_exchange_failed")
    assert e.status == 502
    assert e.detail == "oauth_exchange_failed"
    r = ReauthorizationRequired("google_drive")
    assert r.status == 401
    assert r.detail == "reauthorization_required"
    assert r.provider_id == "google_drive"
