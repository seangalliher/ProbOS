"""AD-720c-2: Dropbox provider stub. Forward marker.

**Trigger to implement:** operator demand (issue mention OR Captain ruling),
once the Google Drive provider has been exercised end-to-end in production
for at least one wave.
"""
from __future__ import annotations

from probos.cloud_pickers.provider import ProviderFile
from probos.cloud_pickers.tokens import OAuthTokenBundle


_NOT_IMPLEMENTED = (
    "AD-720c-2 forward marker: Dropbox provider stub. "
    "Trigger to implement: operator demand."
)


class DropboxProvider:
    """AD-720c-2: Dropbox provider stub (not yet implemented)."""

    provider_id = "dropbox"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http_client_factory=None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri.format(provider=self.provider_id)
        self._http_factory = http_client_factory

    def start_authorization(self, *, state: str) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def handle_callback(self, *, code: str) -> OAuthTokenBundle:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def list_files(
        self,
        *,
        bundle: OAuthTokenBundle,
        query: str | None = None,
        page_token: str | None = None,
    ) -> tuple[list[ProviderFile], str | None, OAuthTokenBundle | None]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def download_file(
        self,
        *,
        bundle: OAuthTokenBundle,
        file_id: str,
    ) -> tuple[bytes, str, str, OAuthTokenBundle | None]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
