"""M365 connector protocol and concrete agent implementations."""

from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import datetime, timezone
from typing import Any, Protocol

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor

logger = logging.getLogger(__name__)


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
        """Retrieve changes since timestamp for emails."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Outlook: token unavailable; cannot list changes")
            return []
        # Placeholder: actual Microsoft Graph API call would go here
        return []

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
        """Retrieve changes since timestamp for calendar events."""
        token = await self._token_manager.get_token()
        if not token:
            logger.warning("Calendar: token unavailable; cannot list changes")
            return []
        return []

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
