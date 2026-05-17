"""AD-720c: Google Drive provider tests.

Uses ``httpx.MockTransport`` to inject deterministic responses. No real
network. Validates: auth-URL params (access_type=offline + prompt=consent
per Section 5b), token exchange shape, list_files mapping, download blob
roundtrip, and the refresh-on-401 retry path.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from probos.cloud_pickers.google_drive import GoogleDriveProvider
from probos.cloud_pickers.provider import ReauthorizationRequired
from probos.cloud_pickers.tokens import OAuthTokenBundle


def _make_provider(handler) -> GoogleDriveProvider:
    transport = httpx.MockTransport(handler)
    return GoogleDriveProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://127.0.0.1:8081/api/cloud-pickers/{provider}/callback",
        http_client_factory=lambda: httpx.AsyncClient(transport=transport, timeout=5.0),
    )


def test_start_authorization_includes_offline_and_consent() -> None:
    """AD-720c-5b: refresh_token requires access_type=offline + prompt=consent."""
    p = _make_provider(lambda req: httpx.Response(200, json={}))
    url = p.start_authorization(state="state-xyz")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["state"] == ["state-xyz"]
    assert params["scope"] == ["https://www.googleapis.com/auth/drive.file"]
    assert params["response_type"] == ["code"]
    assert params["client_id"] == ["test-client-id"]
    assert params["redirect_uri"] == [
        "http://127.0.0.1:8081/api/cloud-pickers/google_drive/callback"
    ]


@pytest.mark.asyncio
async def test_handle_callback_exchanges_code_for_bundle() -> None:
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["body"] = req.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.access",
                "refresh_token": "1//refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    p = _make_provider(handler)
    bundle = await p.handle_callback(code="auth-code-1")
    assert isinstance(bundle, OAuthTokenBundle)
    assert bundle.access_token == "ya29.access"
    assert bundle.refresh_token == "1//refresh"
    assert bundle.expires_at > 0
    assert captured["url"] == "https://oauth2.googleapis.com/token"
    assert "grant_type=authorization_code" in captured["body"]
    assert "code=auth-code-1" in captured["body"]


@pytest.mark.asyncio
async def test_list_files_maps_drive_payload_to_provider_files() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers.get("authorization") == "Bearer access-1"
        return httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "fid1",
                        "name": "report.pdf",
                        "mimeType": "application/pdf",
                        "size": "12345",
                        "modifiedTime": "2026-01-02T03:04:05Z",
                    },
                ],
                "nextPageToken": "page-2",
            },
        )

    p = _make_provider(handler)
    bundle = OAuthTokenBundle(access_token="access-1")
    files, next_token, refreshed = await p.list_files(bundle=bundle)
    assert len(files) == 1
    assert files[0]["id"] == "fid1"
    assert files[0]["name"] == "report.pdf"
    assert files[0]["mime"] == "application/pdf"
    assert files[0]["size_bytes"] == 12345
    assert next_token == "page-2"
    assert refreshed is None  # No 401 → no refresh.


@pytest.mark.asyncio
async def test_download_file_returns_bytes_and_metadata() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "alt=media" in str(req.url):
            return httpx.Response(200, content=b"hello-world-bytes")
        return httpx.Response(
            200,
            json={
                "id": "fid",
                "name": "hello.txt",
                "mimeType": "text/plain",
                "size": "17",
            },
        )

    p = _make_provider(handler)
    bundle = OAuthTokenBundle(access_token="access-1")
    blob, mime, filename, refreshed = await p.download_file(
        bundle=bundle, file_id="fid"
    )
    assert blob == b"hello-world-bytes"
    assert mime == "text/plain"
    assert filename == "hello.txt"
    assert refreshed is None
    # Meta GET first, then media GET (single source of truth path order).
    assert len(calls) == 2
    assert "alt=media" not in calls[0]
    assert "alt=media" in calls[1]


@pytest.mark.asyncio
async def test_list_files_refresh_on_401_persists_new_bundle() -> None:
    """AD-720c-5b: 401 → refresh exchange → retry once."""
    counter = {"list": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if url == "https://oauth2.googleapis.com/token":
            assert "grant_type=refresh_token" in req.content.decode()
            return httpx.Response(
                200,
                json={"access_token": "access-2", "expires_in": 3600},
            )
        counter["list"] += 1
        token = req.headers.get("authorization", "")
        # First call uses access-1, returns 401. Second call (post-refresh)
        # uses access-2, returns 200.
        if token == "Bearer access-1":
            return httpx.Response(401, json={"error": "invalid_token"})
        if token == "Bearer access-2":
            return httpx.Response(200, json={"files": [], "nextPageToken": None})
        return httpx.Response(500, json={"error": "unexpected"})

    p = _make_provider(handler)
    bundle = OAuthTokenBundle(access_token="access-1", refresh_token="r-1")
    files, _next, refreshed = await p.list_files(bundle=bundle)
    assert files == []
    assert refreshed is not None
    assert refreshed.access_token == "access-2"
    # Google rotates refresh_tokens rarely → original preserved.
    assert refreshed.refresh_token == "r-1"
    assert counter["list"] == 2  # 401 + retry


@pytest.mark.asyncio
async def test_list_files_401_without_refresh_token_raises_reauth() -> None:
    """No refresh_token → ReauthorizationRequired (no refresh attempt)."""
    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://oauth2.googleapis.com/token":
            pytest.fail("must NOT attempt refresh when refresh_token is None")
        return httpx.Response(401, json={"error": "invalid_token"})

    p = _make_provider(handler)
    bundle = OAuthTokenBundle(access_token="access-1", refresh_token=None)
    with pytest.raises(ReauthorizationRequired):
        await p.list_files(bundle=bundle)


@pytest.mark.asyncio
async def test_list_files_refresh_failure_raises_reauth() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                400, json={"error": "invalid_grant"}
            )
        return httpx.Response(401, json={"error": "invalid_token"})

    p = _make_provider(handler)
    bundle = OAuthTokenBundle(access_token="access-1", refresh_token="rt")
    with pytest.raises(ReauthorizationRequired):
        await p.list_files(bundle=bundle)
