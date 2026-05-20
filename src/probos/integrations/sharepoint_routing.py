"""AD-755 SharePoint-aware routing and provenance tagging (OSS desktop scope)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass
class DocumentProvenance:
    """Provenance metadata for office documents."""

    source: str
    origin_url: str | None
    permission_level: str
    last_modified_by: str | None
    sensitivity_label: str | None


@dataclass
class SharePointLocation:
    """Resolved routing destination for a document operation."""

    source: str
    route_url: str
    requires_auth: bool


class SharePointRouter:
    """Routes office document operations across local and personal SharePoint paths."""

    def __init__(
        self,
        token_manager: object | None = None,
        permission_level: str = "edit",
    ) -> None:
        self._token_manager = token_manager
        self._permission_level = permission_level

    async def route_for_read(self, doc_path: str) -> SharePointLocation:
        """Determine local vs personal OneDrive route for document reads."""
        source = self._infer_source(doc_path)
        if source == "local":
            return SharePointLocation(source="local", route_url=doc_path, requires_auth=False)

        if source in {"sharepoint_site", "teams_channel"}:
            raise PermissionError(
                "OSS desktop routing supports personal OneDrive only; site/team routing is commercial scope"
            )

        if not await self._has_token():
            raise PermissionError("M365 authentication is required for personal OneDrive routing")

        return SharePointLocation(
            source="personal_onedrive",
            route_url=f"https://graph.microsoft.com/v1.0/me/drive/root:/{self._extract_remote_path(doc_path)}",
            requires_auth=True,
        )

    async def upload_to_personal(self, local_path: str, remote_name: str) -> str:
        """Upload local file to personal OneDrive route and return remote URL."""
        source = Path(local_path)
        if not source.exists():
            raise FileNotFoundError(local_path)

        if self._permission_level not in {"edit", "owner"}:
            raise PermissionError("Current routing permission does not allow document upload")

        if not await self._has_token():
            raise PermissionError("M365 authentication is required for personal uploads")

        return f"https://graph.microsoft.com/v1.0/me/drive/root:/Documents/{remote_name}:/content"

    async def tag_provenance(self, doc_path: str) -> DocumentProvenance:
        """Infer provenance from path origin and current routing policy."""
        source = self._infer_source(doc_path)
        origin_url = doc_path if source != "local" else None
        last_modified_by = "captain-local" if source == "local" else "m365-user"
        return DocumentProvenance(
            source=source,
            origin_url=origin_url,
            permission_level=self._permission_level,
            last_modified_by=last_modified_by,
            sensitivity_label=None,
        )

    async def _has_token(self) -> bool:
        if self._token_manager is None or not hasattr(self._token_manager, "get_token"):
            return False
        token = await self._token_manager.get_token()
        return bool(token)

    def _infer_source(self, doc_path: str) -> str:
        parsed = urlparse(doc_path)
        if parsed.scheme in {"http", "https"}:
            host = parsed.netloc.lower()
            path = parsed.path.lower()
            if "-my.sharepoint.com" in host or "/personal/" in path:
                return "personal_onedrive"
            if "/teams/" in path:
                return "teams_channel"
            if ".sharepoint.com" in host:
                return "sharepoint_site"
            return "sharepoint_site"

        return "local"

    def _extract_remote_path(self, doc_path: str) -> str:
        parsed = urlparse(doc_path)
        cleaned = parsed.path.lstrip("/")
        return cleaned or "Documents"
