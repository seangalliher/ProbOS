"""AD-720c: ``CloudPickerProvider`` Protocol + helpers.

Three concrete providers implement this Protocol:

* ``google_drive.GoogleDriveProvider`` — v1 working provider (Wave 168).
* ``onedrive.OneDriveProvider`` — stub; forward marker AD-720c-1.
* ``dropbox.DropboxProvider`` — stub; forward marker AD-720c-2.

All HTTP via ``httpx.AsyncClient`` (no new pip deps; AD-720c reuses Wave-162
``httpx`` resident dep).
"""
from __future__ import annotations

from typing import Protocol

from probos.cloud_pickers.tokens import OAuthTokenBundle


class ProviderError(Exception):
    """AD-720c: provider-side failure with structured detail.

    ``status`` mirrors the HTTP-ish failure category; ``detail`` is a stable
    machine-readable string surfaced to the API caller in
    ``HTTPException.detail``.
    """

    def __init__(self, status: int, detail: str, *, message: str = "") -> None:
        super().__init__(message or detail)
        self.status = status
        self.detail = detail


class ReauthorizationRequired(ProviderError):
    """AD-720c: refresh failed (or no refresh_token) — Captain must reauthorize."""

    def __init__(self, provider_id: str) -> None:
        super().__init__(
            status=401,
            detail="reauthorization_required",
            message=(
                f"AD-720c: provider {provider_id!r} requires reauthorization; "
                f"OAuth refresh exchange failed or no refresh_token was issued."
            ),
        )
        self.provider_id = provider_id


class ProviderFile(dict):
    """AD-720c: typed file dict returned by ``list_files()``.

    Keys: ``id`` (str), ``name`` (str), ``mime`` (str), ``size_bytes`` (int),
    ``modified_at`` (str ISO8601). dict-subclass for cheap JSON-serialization
    from the router layer.
    """


class CloudPickerProvider(Protocol):
    """AD-720c: OAuth-bound file source for chat attachments."""

    provider_id: str  # 'google_drive' / 'onedrive' / 'dropbox'

    def start_authorization(self, *, state: str) -> str:
        """Return the provider's OAuth consent URL.

        Caller (router) is responsible for storing ``state`` in a session-scoped
        CSRF guard before returning the URL to the client.
        """
        ...

    async def handle_callback(self, *, code: str) -> OAuthTokenBundle:
        """Exchange the authorization ``code`` for an :class:`OAuthTokenBundle`.

        On failure, raise :class:`ProviderError`. The router writes the bundle
        to the credential vault under ``cloud_provider:{provider_id}:{captain}``.
        """
        ...

    async def list_files(
        self,
        *,
        bundle: OAuthTokenBundle,
        query: str | None = None,
        page_token: str | None = None,
    ) -> tuple[list[ProviderFile], str | None, OAuthTokenBundle | None]:
        """List files for the authorized provider.

        Returns ``(files, next_page_token, refreshed_bundle)``. ``refreshed_bundle``
        is non-None when a 401 triggered a successful refresh exchange and the
        caller should persist the new bundle to the vault.

        Raises :class:`ReauthorizationRequired` on refresh failure.
        """
        ...

    async def download_file(
        self,
        *,
        bundle: OAuthTokenBundle,
        file_id: str,
    ) -> tuple[bytes, str, str, OAuthTokenBundle | None]:
        """Download a file by id.

        Returns ``(blob, declared_mime, declared_filename, refreshed_bundle)``.
        Size validation against ``cfg.cloud_pickers.max_file_size_bytes`` is
        performed by the caller (router) — providers do NOT enforce it.
        Raises :class:`ReauthorizationRequired` on refresh failure.
        """
        ...
