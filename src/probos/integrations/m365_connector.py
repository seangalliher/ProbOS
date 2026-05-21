"""M365 connector protocol and concrete agent implementations."""

from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
# AD-763: hard pagination cap per scan. Operator-tunable knob deferred to AD-763d.
_PAGINATION_PAGE_CAP = 5


def _sender_matches(sender: str, patterns: list[str]) -> bool:
    """Return True if a sender address matches any allow/deny pattern.

    Pattern shapes accepted (case-insensitive):
      - 'user@acme.com'  -> exact full-address match
      - '@acme.com'      -> domain match (any address on that domain)
      - 'acme.com'       -> domain match (treated as '@acme.com')
    """
    if not sender or not patterns:
        return False
    s = sender.strip().lower()
    for raw in patterns:
        pat = raw.strip().lower()
        if not pat:
            continue
        if pat.startswith("@"):
            if s.endswith(pat):
                return True
        elif "@" in pat:
            if s == pat:
                return True
        else:
            # Bare domain
            if s.endswith("@" + pat):
                return True
    return False


async def _graph_get(
    url: str,
    token: str,
    *,
    timeout: float = 30.0,
) -> tuple[int, dict[str, Any] | None]:
    """GET a Graph endpoint. Returns (status_code, json_body_or_none).

    Does not raise; logs warnings on transport failure. Caller branches on status.
    """
    try:
        import httpx
    except ImportError:
        logger.error("httpx unavailable; cannot reach Microsoft Graph")
        return (0, None)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
    except Exception:
        logger.warning("Graph GET transport error url=%s; returning honest-degrade", url, exc_info=True)
        return (0, None)

    body: dict[str, Any] | None
    try:
        body = response.json() if response.content else None
    except ValueError:
        body = None
    return (response.status_code, body)


class M365Connector(Protocol):
    """Base interface for M365-backed agents (Outlook/Teams/Calendar/SharePoint/OneDrive).
    
    All M365 agents must implement this to be routable by Yeo + crew.
    """

    async def refresh_token(self) -> bool:
        """Ensure current token is valid. Return True if operational."""
        ...

    async def list_changes(self, since: datetime) -> list[dict[str, Any]]:
        """Retrieve changes since timestamp for this connector's resource."""
        ...

    async def get_audit_entry(self, resource_id: str) -> dict[str, Any]:
        """Return dict with: resource_id, action, timestamp, success, error."""
        ...


class OutlookAgent(CognitiveAgent):
    """Outlook email connector agent."""

    agent_type = "outlook"
    tier = "domain"
    callsign = "Outlook"

    default_capabilities = [
        {
            "name": "read_inbox",
            "description": "Read emails from inbox",
        },
        {
            "name": "draft_message",
            "description": "Draft an email message",
        },
        {
            "name": "flag_email",
            "description": "Flag or snooze an email",
        },
        {
            "name": "search_emails",
            "description": "Search for emails",
        },
    ]

    intent_descriptors = [
        IntentDescriptor(
            name="outlook_read_inbox",
            description="Read emails from inbox",
            params={"max_count": "max number of messages to retrieve"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="outlook_draft",
            description="Draft an email message",
            params={"to": "recipient email", "subject": "message subject"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="outlook_flag",
            description="Flag or snooze an email",
            params={"email_id": "message ID to flag"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="outlook_search",
            description="Search for emails",
            params={"query": "search query string"},
            requires_consensus=False,
        ),
    ]

    instructions = (
        "You are the Outlook email agent. You handle email reading, drafting, "
        "flagging, and searching using Microsoft 365 Outlook API."
    )

    def __init__(self, runtime: Any, token_manager: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._token_manager = token_manager

    async def refresh_token(self) -> bool:
        """Ensure current token is valid. Return True if operational."""
        token = await self._token_manager.get_token()
        return token is not None

    async def list_changes(self, since: datetime) -> list[dict[str, Any]]:
        """Retrieve mail changes since timestamp, scoped to ProactiveScanConfig.inbox.

        AD-763: honors operator scoping (folders, lookback, importance, unread,
        sender allow/deny). The Graph `$filter` query handles receivedDateTime,
        importance, and isRead; sender allow/deny is applied in-process.
        Returns whatever was collected even if some folders 5xx — honest-degrade.
        """
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Outlook: token unavailable; cannot list changes")
            return []

        cfg = self._scan_config()
        # since arg is a hard floor; lookback caps it from going further back than configured.
        lookback_floor = datetime.now(timezone.utc) - timedelta(hours=cfg.lookback_hours)
        effective_since = max(since.astimezone(timezone.utc) if since.tzinfo else since.replace(tzinfo=timezone.utc), lookback_floor)
        since_str = effective_since.strftime("%Y-%m-%dT%H:%M:%SZ")

        filters = [f"receivedDateTime ge {since_str}"]
        if cfg.importance_filter == "high":
            filters.append("importance eq 'high'")
        if cfg.unread_only:
            filters.append("isRead eq false")
        filter_expr = " and ".join(filters)

        collected: list[dict[str, Any]] = []
        for folder_id in cfg.folders or ["Inbox"]:
            url: str | None = (
                f"{GRAPH_BASE_URL}/me/mailFolders/{folder_id}/messages"
                f"?$filter={filter_expr}&$top=100"
                "&$select=id,subject,from,receivedDateTime,importance,isRead,bodyPreview"
            )
            pages = 0
            while url and pages < _PAGINATION_PAGE_CAP:
                status, body = await _graph_get(url, token)
                if status == 401:
                    logger.warning("Outlook: 401 from Graph; token refresh required")
                    raise PermissionError("M365 token rejected by Graph (401)")
                if status == 429:
                    logger.warning("Outlook: 429 from Graph folder=%s; honoring Retry-After by stopping page loop", folder_id)
                    break
                if status >= 500 or status == 0:
                    logger.warning("Outlook: Graph %s for folder=%s; returning partial results", status, folder_id)
                    break
                if status != 200 or body is None:
                    logger.warning("Outlook: Graph status=%s for folder=%s; skipping", status, folder_id)
                    break
                value = body.get("value", []) if isinstance(body, dict) else []
                for item in value:
                    sender = (
                        item.get("from", {}).get("emailAddress", {}).get("address", "")
                        if isinstance(item.get("from"), dict)
                        else ""
                    )
                    if cfg.sender_denylist and _sender_matches(sender, cfg.sender_denylist):
                        continue
                    if cfg.sender_allowlist and not _sender_matches(sender, cfg.sender_allowlist):
                        continue
                    collected.append({**item, "_folder_id": folder_id})
                next_link = body.get("@odata.nextLink") if isinstance(body, dict) else None
                url = next_link
                pages += 1
            if pages >= _PAGINATION_PAGE_CAP and url:
                logger.info(
                    "AD-763: pagination cap reached for folder=%s (page_cap=%d)",
                    folder_id, _PAGINATION_PAGE_CAP,
                )
        return collected

    def _scan_config(self) -> Any:
        """Return ProactiveScanConfig.inbox for this runtime; defaults if unconfigured."""
        cfg = getattr(getattr(self._runtime, "config", None), "proactive_scan", None)
        if cfg is None:
            from probos.config import ProactiveScanConfig
            cfg = ProactiveScanConfig()
        return cfg.inbox

    async def get_audit_entry(self, resource_id: str) -> dict[str, Any]:
        """Return audit entry for an email."""
        return {
            "resource_id": resource_id,
            "action": "read",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "error": None,
        }

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Receive an intent from the mesh."""
        logger.debug("Outlook perceive: %s", intent)
        return intent

    async def decide(self, observation: Any) -> Any:
        """Determine action based on observation."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Outlook: token unavailable; cannot act")
            return {"error": "NotAuthorizedError", "message": "No M365 token available"}
        return observation

    async def act(self, plan: Any) -> Any:
        """Execute the planned action."""
        # Placeholder for actual API interaction
        logger.debug("Outlook act: %s", plan)
        return {"status": "success"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package result for broadcast to the mesh."""
        return {"agent": self.agent_type, "result": result}


class TeamsAgent(CognitiveAgent):
    """Microsoft Teams connector agent."""

    agent_type = "teams"
    tier = "domain"
    callsign = "Teams"

    default_capabilities = [
        {
            "name": "list_chats",
            "description": "List Teams chats and conversations",
        },
        {
            "name": "read_channel_messages",
            "description": "Read channel messages",
        },
        {
            "name": "search_teams",
            "description": "Search Teams messages and content",
        },
    ]

    intent_descriptors = [
        IntentDescriptor(
            name="teams_list_chats",
            description="List Teams chats",
            params={},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="teams_read_channel",
            description="Read channel messages",
            params={"channel_id": "Teams channel ID"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="teams_search",
            description="Search Teams content",
            params={"query": "search query string"},
            requires_consensus=False,
        ),
    ]

    instructions = (
        "You are the Microsoft Teams agent. You handle chat listing, message reading, "
        "and content searching using Microsoft 365 Teams API."
    )

    def __init__(self, runtime: Any, token_manager: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._token_manager = token_manager

    async def refresh_token(self) -> bool:
        """Ensure current token is valid. Return True if operational."""
        token = await self._token_manager.get_token()
        return token is not None

    async def list_changes(self, since: datetime) -> list[dict[str, Any]]:
        """Retrieve changes since timestamp for Teams."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Teams: token unavailable; cannot list changes")
            return []
        return []

    async def get_audit_entry(self, resource_id: str) -> dict[str, Any]:
        """Return audit entry for a Teams resource."""
        return {
            "resource_id": resource_id,
            "action": "read",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "error": None,
        }

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Receive an intent from the mesh."""
        logger.debug("Teams perceive: %s", intent)
        return intent

    async def decide(self, observation: Any) -> Any:
        """Determine action based on observation."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Teams: token unavailable; cannot act")
            return {"error": "NotAuthorizedError", "message": "No M365 token available"}
        return observation

    async def act(self, plan: Any) -> Any:
        """Execute the planned action."""
        logger.debug("Teams act: %s", plan)
        return {"status": "success"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package result for broadcast to the mesh."""
        return {"agent": self.agent_type, "result": result}


class CalendarAgent(CognitiveAgent):
    """Calendar connector agent."""

    agent_type = "calendar"
    tier = "domain"
    callsign = "Calendar"

    default_capabilities = [
        {
            "name": "find_time",
            "description": "Find available meeting times",
        },
        {
            "name": "book_meeting",
            "description": "Book a meeting on calendar",
        },
        {
            "name": "list_events",
            "description": "List calendar events",
        },
    ]

    intent_descriptors = [
        IntentDescriptor(
            name="calendar_find_time",
            description="Find available meeting times",
            params={"attendees": "attendee email list"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="calendar_book",
            description="Book a meeting",
            params={"title": "meeting title", "start_time": "start time", "end_time": "end time"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="calendar_list",
            description="List calendar events",
            params={"days_ahead": "number of days ahead"},
            requires_consensus=False,
        ),
    ]

    instructions = (
        "You are the Calendar agent. You handle finding available times, "
        "booking meetings, and listing calendar events using Microsoft 365 Calendar API."
    )

    def __init__(self, runtime: Any, token_manager: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._token_manager = token_manager

    async def refresh_token(self) -> bool:
        """Ensure current token is valid. Return True if operational."""
        token = await self._token_manager.get_token()
        return token is not None

    async def list_changes(self, since: datetime) -> list[dict[str, Any]]:
        """Retrieve calendar events in the lookahead window, scoped to ProactiveScanConfig.calendar.

        AD-763: honors operator scoping (calendar_ids, lookahead_hours, include_declined).
        Uses Graph `calendarView` (expands recurring events) per selected calendar.
        Returns whatever was collected even if some calendars 5xx — honest-degrade.
        """
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Calendar: token unavailable; cannot list changes")
            return []

        cfg = self._scan_config()
        start_dt = datetime.now(timezone.utc)
        end_dt = start_dt + timedelta(hours=cfg.lookahead_hours)
        start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        collected: list[dict[str, Any]] = []
        for raw_cal_id in cfg.calendar_ids or ["primary"]:
            # 'primary' alias -> default Graph calendar path /me/calendar
            if raw_cal_id == "primary":
                base = f"{GRAPH_BASE_URL}/me/calendar/calendarView"
            else:
                base = f"{GRAPH_BASE_URL}/me/calendars/{raw_cal_id}/calendarView"
            url: str | None = (
                f"{base}?startDateTime={start_str}&endDateTime={end_str}&$top=100"
                "&$select=id,subject,start,end,organizer,attendees,responseStatus,isCancelled"
            )
            pages = 0
            while url and pages < _PAGINATION_PAGE_CAP:
                status, body = await _graph_get(url, token)
                if status == 401:
                    logger.warning("Calendar: 401 from Graph; token refresh required")
                    raise PermissionError("M365 token rejected by Graph (401)")
                if status == 429:
                    logger.warning("Calendar: 429 from Graph calendar=%s; stopping page loop", raw_cal_id)
                    break
                if status >= 500 or status == 0:
                    logger.warning("Calendar: Graph %s for calendar=%s; returning partial results", status, raw_cal_id)
                    break
                if status != 200 or body is None:
                    logger.warning("Calendar: Graph status=%s for calendar=%s; skipping", status, raw_cal_id)
                    break
                value = body.get("value", []) if isinstance(body, dict) else []
                for item in value:
                    if not cfg.include_declined:
                        response = (
                            item.get("responseStatus", {}).get("response", "")
                            if isinstance(item.get("responseStatus"), dict)
                            else ""
                        )
                        if response == "declined":
                            continue
                    collected.append({**item, "_calendar_id": raw_cal_id})
                next_link = body.get("@odata.nextLink") if isinstance(body, dict) else None
                url = next_link
                pages += 1
            if pages >= _PAGINATION_PAGE_CAP and url:
                logger.info(
                    "AD-763: pagination cap reached for calendar=%s (page_cap=%d)",
                    raw_cal_id, _PAGINATION_PAGE_CAP,
                )
        return collected

    def _scan_config(self) -> Any:
        """Return ProactiveScanConfig.calendar for this runtime; defaults if unconfigured."""
        cfg = getattr(getattr(self._runtime, "config", None), "proactive_scan", None)
        if cfg is None:
            from probos.config import ProactiveScanConfig
            cfg = ProactiveScanConfig()
        return cfg.calendar

    async def get_audit_entry(self, resource_id: str) -> dict[str, Any]:
        """Return audit entry for a calendar event."""
        return {
            "resource_id": resource_id,
            "action": "read",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "error": None,
        }

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Receive an intent from the mesh."""
        logger.debug("Calendar perceive: %s", intent)
        return intent

    async def decide(self, observation: Any) -> Any:
        """Determine action based on observation."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Calendar: token unavailable; cannot act")
            return {"error": "NotAuthorizedError", "message": "No M365 token available"}
        return observation

    async def act(self, plan: Any) -> Any:
        """Execute the planned action."""
        logger.debug("Calendar act: %s", plan)
        return {"status": "success"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package result for broadcast to the mesh."""
        return {"agent": self.agent_type, "result": result}


class SharePointAgent(CognitiveAgent):
    """SharePoint connector agent."""

    agent_type = "sharepoint"
    tier = "domain"
    callsign = "SharePoint"

    default_capabilities = [
        {
            "name": "search_sites",
            "description": "Search SharePoint sites",
        },
        {
            "name": "read_permissions",
            "description": "Read SharePoint permissions",
        },
        {
            "name": "list_items",
            "description": "List SharePoint list items",
        },
    ]

    intent_descriptors = [
        IntentDescriptor(
            name="sharepoint_search_sites",
            description="Search SharePoint sites",
            params={"query": "search query"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="sharepoint_read_perms",
            description="Read SharePoint permissions",
            params={"site_id": "SharePoint site ID"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="sharepoint_list_items",
            description="List SharePoint items",
            params={"list_id": "SharePoint list ID"},
            requires_consensus=False,
        ),
    ]

    instructions = (
        "You are the SharePoint agent. You handle site searching, permission reading, "
        "and item listing using Microsoft 365 SharePoint API."
    )

    def __init__(self, runtime: Any, token_manager: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._token_manager = token_manager

    async def refresh_token(self) -> bool:
        """Ensure current token is valid. Return True if operational."""
        token = await self._token_manager.get_token()
        return token is not None

    async def list_changes(self, since: datetime) -> list[dict[str, Any]]:
        """Retrieve changes since timestamp for SharePoint."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("SharePoint: token unavailable; cannot list changes")
            return []
        return []

    async def get_audit_entry(self, resource_id: str) -> dict[str, Any]:
        """Return audit entry for a SharePoint resource."""
        return {
            "resource_id": resource_id,
            "action": "read",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "error": None,
        }

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Receive an intent from the mesh."""
        logger.debug("SharePoint perceive: %s", intent)
        return intent

    async def decide(self, observation: Any) -> Any:
        """Determine action based on observation."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("SharePoint: token unavailable; cannot act")
            return {"error": "NotAuthorizedError", "message": "No M365 token available"}
        return observation

    async def act(self, plan: Any) -> Any:
        """Execute the planned action."""
        logger.debug("SharePoint act: %s", plan)
        return {"status": "success"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package result for broadcast to the mesh."""
        return {"agent": self.agent_type, "result": result}


class OneDriveAgent(CognitiveAgent):
    """OneDrive connector agent."""

    agent_type = "onedrive"
    tier = "domain"
    callsign = "OneDrive"

    default_capabilities = [
        {
            "name": "search_files",
            "description": "Search files in OneDrive",
        },
        {
            "name": "get_file_metadata",
            "description": "Get file metadata",
        },
        {
            "name": "read_permissions",
            "description": "Read file permissions",
        },
    ]

    intent_descriptors = [
        IntentDescriptor(
            name="onedrive_search",
            description="Search OneDrive files",
            params={"query": "search query"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="onedrive_metadata",
            description="Get OneDrive file metadata",
            params={"file_id": "OneDrive file ID"},
            requires_consensus=False,
        ),
        IntentDescriptor(
            name="onedrive_perms",
            description="Read OneDrive file permissions",
            params={"file_id": "OneDrive file ID"},
            requires_consensus=False,
        ),
    ]

    instructions = (
        "You are the OneDrive agent. You handle file searching, metadata retrieval, "
        "and permission reading using Microsoft 365 OneDrive API."
    )

    def __init__(self, runtime: Any, token_manager: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._runtime = runtime
        self._token_manager = token_manager

    async def refresh_token(self) -> bool:
        """Ensure current token is valid. Return True if operational."""
        token = await self._token_manager.get_token()
        return token is not None

    async def list_changes(self, since: datetime) -> list[dict[str, Any]]:
        """Retrieve changes since timestamp for OneDrive."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("OneDrive: token unavailable; cannot list changes")
            return []
        return []

    async def get_audit_entry(self, resource_id: str) -> dict[str, Any]:
        """Return audit entry for a OneDrive resource."""
        return {
            "resource_id": resource_id,
            "action": "read",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "success": True,
            "error": None,
        }

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Receive an intent from the mesh."""
        logger.debug("OneDrive perceive: %s", intent)
        return intent

    async def decide(self, observation: Any) -> Any:
        """Determine action based on observation."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("OneDrive: token unavailable; cannot act")
            return {"error": "NotAuthorizedError", "message": "No M365 token available"}
        return observation

    async def act(self, plan: Any) -> Any:
        """Execute the planned action."""
        logger.debug("OneDrive act: %s", plan)
        return {"status": "success"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package result for broadcast to the mesh."""
        return {"agent": self.agent_type, "result": result}
