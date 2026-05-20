"""AD-753 permission mode model and read-only auto-approval checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from probos.security.destructive_ops import DESTRUCTIVE_INTENTS


READ_ONLY_INTENTS: set[str] = {
    "outlook_read_inbox",
    "teams_list_chats",
    "teams_search_channel",
    "calendar_list_events",
    "calendar_find_time",
    "sharepoint_search",
    "onedrive_search",
    "search_files",
    "read_file",
    "list_directory",
}


class PermissionMode(str, Enum):
    """Permission posture for unattended decisioning."""

    MANUAL = "manual"
    AUTOPILOT = "autopilot"
    YOLO = "yolo"


@dataclass(slots=True)
class PermissionConfig:
    """Runtime permission controls for unattended operations."""

    mode: PermissionMode = PermissionMode.MANUAL
    auto_approve_read_only: bool = False
    read_only_whitelist: set[str] = field(default_factory=lambda: set(READ_ONLY_INTENTS))
    read_only_expiry_window_sec: int = 3600


async def should_auto_approve(intent: str, config: PermissionConfig) -> bool:
    """Return true when an intent can be auto-approved under current policy."""
    if intent in DESTRUCTIVE_INTENTS:
        return False
    if config.mode != PermissionMode.AUTOPILOT:
        return False
    if not config.auto_approve_read_only:
        return False
    return intent in config.read_only_whitelist
