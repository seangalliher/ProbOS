"""AD-755 tests for SharePoint routing and provenance."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.integrations.sharepoint_routing import SharePointRouter


class _TokenManager:
    def __init__(self, token: str | None) -> None:
        self._token = token

    async def get_token(self) -> str | None:
        return self._token


@pytest.mark.asyncio
async def test_route_for_read_personal_onedrive_detected_and_guarded() -> None:
    personal_url = "https://contoso-my.sharepoint.com/personal/captain/Documents/report.docx"

    router = SharePointRouter(token_manager=_TokenManager(token="token"), permission_level="edit")
    location = await router.route_for_read(personal_url)

    assert location.source == "personal_onedrive"
    assert location.requires_auth is True
    assert location.route_url.startswith("https://graph.microsoft.com/v1.0/me/drive/root:/")

    router_no_auth = SharePointRouter(token_manager=_TokenManager(token=None), permission_level="edit")
    with pytest.raises(PermissionError):
        await router_no_auth.route_for_read(personal_url)


@pytest.mark.asyncio
async def test_tag_provenance_local_file() -> None:
    router = SharePointRouter(permission_level="owner")

    provenance = await router.tag_provenance(str(Path("notes") / "daily.docx"))

    assert provenance.source == "local"
    assert provenance.origin_url is None
    assert provenance.permission_level == "owner"
    assert provenance.sensitivity_label is None
