"""AD-720c: Google Drive provider (v1 working provider, Wave 168).

Scope: ``https://www.googleapis.com/auth/drive.file`` — least-privilege
(app-created files only). Operator-supplied OAuth client (BYOC) via
``cfg.cloud_pickers.google_drive``.

Refresh-token discipline (AD-720c-5b): consent URL includes
``access_type=offline&prompt=consent`` so Google issues a refresh_token on
every authorization (not just the very first ever for a user/scope tuple —
Google's documented behavior without ``prompt=consent`` is to omit the
refresh_token on subsequent authorizations).
"""
from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from probos.cloud_pickers.provider import (
    ProviderError,
    ProviderFile,
    ReauthorizationRequired,
)
from probos.cloud_pickers.tokens import OAuthTokenBundle

logger = logging.getLogger(__name__)


_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - URL not secret
_FILES_LIST_URL = "https://www.googleapis.com/drive/v3/files"
_FILES_GET_URL = "https://www.googleapis.com/drive/v3/files/{file_id}"
_SCOPE = "https://www.googleapis.com/auth/drive.file"


class GoogleDriveProvider:
    """AD-720c: Google Drive OAuth provider."""

    provider_id = "google_drive"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http_client_factory: Any = None,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError(
                "AD-720c: GoogleDriveProvider requires client_id and client_secret"
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri.format(provider=self.provider_id)
        # http_client_factory: zero-arg callable returning an httpx.AsyncClient.
        # Test fixtures inject a transport-mocked client; default constructs
        # a vanilla one per call (closed via async-with).
        self._http_factory = http_client_factory or (lambda: httpx.AsyncClient(timeout=30.0))

    # -- 1. Authorization URL --------------------------------------------

    def start_authorization(self, *, state: str) -> str:
        # AD-720c: access_type=offline → request refresh_token issuance.
        # prompt=consent → force consent screen even on re-authorization so
        # refresh_token is re-issued (Google's documented behavior — without
        # this, only the FIRST ever authorization for a (user, client_id,
        # scope) tuple receives a refresh_token).
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    # -- 2. Callback (code → bundle) -------------------------------------

    async def handle_callback(self, *, code: str) -> OAuthTokenBundle:
        body = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }
        async with self._http_factory() as client:
            try:
                r = await client.post(_TOKEN_URL, data=body)
            except httpx.HTTPError as e:
                logger.warning(
                    "AD-720c: Google token exchange transport error: %s; "
                    "surfacing oauth_exchange_failed to caller",
                    type(e).__name__,
                )
                raise ProviderError(502, "oauth_exchange_failed") from e
        if r.status_code != 200:
            logger.warning(
                "AD-720c: Google token exchange failed status=%d body=%s",
                r.status_code,
                _truncate_body(r.text),
            )
            raise ProviderError(502, "oauth_exchange_failed")
        payload = r.json()
        return _bundle_from_payload(payload, prior_refresh_token=None)

    # -- 3. List files ---------------------------------------------------

    async def list_files(
        self,
        *,
        bundle: OAuthTokenBundle,
        query: str | None = None,
        page_token: str | None = None,
    ) -> tuple[list[ProviderFile], str | None, OAuthTokenBundle | None]:
        async def do_request(active: OAuthTokenBundle) -> httpx.Response:
            params = {
                "pageSize": "50",
                "fields": "files(id,name,mimeType,size,modifiedTime),nextPageToken",
            }
            if query:
                params["q"] = f"name contains '{_escape_drive_query(query)}'"
            if page_token:
                params["pageToken"] = page_token
            async with self._http_factory() as client:
                return await client.get(
                    _FILES_LIST_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {active.access_token}"},
                )

        r, refreshed = await self._with_refresh_retry(bundle, do_request)
        if r.status_code != 200:
            logger.warning(
                "AD-720c: Google list_files non-200 status=%d body=%s",
                r.status_code,
                _truncate_body(r.text),
            )
            raise ProviderError(502, "provider_list_failed")
        payload = r.json()
        files: list[ProviderFile] = []
        for entry in payload.get("files", []) or []:
            files.append(
                ProviderFile(
                    id=str(entry.get("id", "")),
                    name=str(entry.get("name", "")),
                    mime=str(entry.get("mimeType", "application/octet-stream")),
                    size_bytes=int(entry.get("size", 0) or 0),
                    modified_at=str(entry.get("modifiedTime", "")),
                )
            )
        return files, payload.get("nextPageToken"), refreshed

    # -- 4. Download file ------------------------------------------------

    async def download_file(
        self,
        *,
        bundle: OAuthTokenBundle,
        file_id: str,
    ) -> tuple[bytes, str, str, OAuthTokenBundle | None]:
        if not file_id or "/" in file_id:
            raise ProviderError(400, "invalid_file_id")

        async def do_meta(active: OAuthTokenBundle) -> httpx.Response:
            async with self._http_factory() as client:
                return await client.get(
                    _FILES_GET_URL.format(file_id=file_id),
                    params={"fields": "id,name,mimeType,size"},
                    headers={"Authorization": f"Bearer {active.access_token}"},
                )

        meta_resp, refreshed_a = await self._with_refresh_retry(bundle, do_meta)
        if meta_resp.status_code != 200:
            logger.warning(
                "AD-720c: Google meta GET non-200 status=%d body=%s",
                meta_resp.status_code,
                _truncate_body(meta_resp.text),
            )
            raise ProviderError(502, "provider_metadata_failed")
        meta = meta_resp.json()
        filename = str(meta.get("name", "download.bin"))
        mime = str(meta.get("mimeType", "application/octet-stream"))

        active_bundle = refreshed_a or bundle

        async def do_blob(active: OAuthTokenBundle) -> httpx.Response:
            async with self._http_factory() as client:
                return await client.get(
                    _FILES_GET_URL.format(file_id=file_id),
                    params={"alt": "media"},
                    headers={"Authorization": f"Bearer {active.access_token}"},
                )

        blob_resp, refreshed_b = await self._with_refresh_retry(active_bundle, do_blob)
        if blob_resp.status_code != 200:
            logger.warning(
                "AD-720c: Google download non-200 status=%d", blob_resp.status_code
            )
            raise ProviderError(502, "provider_download_failed")
        # Effective "refreshed" is whichever exchange happened (at most one).
        final_refreshed = refreshed_b or refreshed_a
        return blob_resp.content, mime, filename, final_refreshed

    # -- 5. Refresh-on-401 helper ----------------------------------------

    async def _with_refresh_retry(
        self,
        bundle: OAuthTokenBundle,
        do_request: Any,
    ) -> tuple[httpx.Response, OAuthTokenBundle | None]:
        """Run ``do_request(bundle)``; on 401 refresh and retry once.

        Returns ``(response, refreshed_bundle_or_None)``. ``refreshed_bundle``
        is non-None when a refresh happened (caller must persist).
        Raises :class:`ReauthorizationRequired` on refresh failure.
        """
        r = await do_request(bundle)
        if r.status_code != 401:
            return r, None
        # 401 → attempt refresh.
        if not bundle.refresh_token:
            raise ReauthorizationRequired(self.provider_id)
        try:
            refreshed = await self._refresh(bundle)
        except ProviderError:
            raise ReauthorizationRequired(self.provider_id)
        # Retry exactly once. A second 401 → reauth (avoid loops).
        r2 = await do_request(refreshed)
        if r2.status_code == 401:
            raise ReauthorizationRequired(self.provider_id)
        return r2, refreshed

    async def _refresh(self, bundle: OAuthTokenBundle) -> OAuthTokenBundle:
        body = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": bundle.refresh_token or "",
            "grant_type": "refresh_token",
        }
        async with self._http_factory() as client:
            try:
                r = await client.post(_TOKEN_URL, data=body)
            except httpx.HTTPError as e:
                raise ProviderError(502, "refresh_transport_error") from e
        if r.status_code != 200:
            logger.warning(
                "AD-720c: Google refresh non-200 status=%d body=%s",
                r.status_code,
                _truncate_body(r.text),
            )
            raise ProviderError(502, "refresh_failed")
        payload = r.json()
        # Preserve the original refresh_token if the response omits one
        # (Google does NOT rotate refresh_tokens on refresh exchanges).
        return _bundle_from_payload(payload, prior_refresh_token=bundle.refresh_token)


def _bundle_from_payload(
    payload: dict[str, Any], *, prior_refresh_token: str | None
) -> OAuthTokenBundle:
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise ProviderError(502, "oauth_no_access_token")
    refresh = payload.get("refresh_token") or prior_refresh_token
    expires_in = payload.get("expires_in")
    expires_at = (
        time.time() + float(expires_in) if isinstance(expires_in, (int, float)) else 0.0
    )
    return OAuthTokenBundle(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) and refresh else None,
        expires_at=expires_at,
        token_type=str(payload.get("token_type", "Bearer")),
    )


def _escape_drive_query(s: str) -> str:
    # Google Drive q-syntax: backslash-escape single quotes + backslashes.
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _truncate_body(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"
