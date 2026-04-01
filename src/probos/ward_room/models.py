"""Ward Room data models — dataclasses, schema, and utility functions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WardRoomChannel:
    id: str
    name: str
    channel_type: str  # "ship" | "department" | "custom" | "dm"
    department: str     # For department channels, empty otherwise
    created_by: str     # agent_id of creator
    created_at: float
    archived: bool = False
    description: str = ""


@dataclass
class WardRoomThread:
    id: str
    channel_id: str
    author_id: str
    title: str
    body: str
    created_at: float
    last_activity: float
    pinned: bool = False
    locked: bool = False
    thread_mode: str = "discuss"  # AD-424: "inform" | "discuss" | "action"
    max_responders: int = 0       # AD-424: 0 = unlimited, >0 = cap
    reply_count: int = 0
    net_score: int = 0
    # ViewMeta denormalization (Aether pattern)
    author_callsign: str = ""
    channel_name: str = ""


@dataclass
class WardRoomPost:
    id: str
    thread_id: str
    parent_id: str | None  # None = direct reply to thread, str = nested reply
    author_id: str
    body: str
    created_at: float
    edited_at: float | None = None
    deleted: bool = False
    delete_reason: str = ""
    deleted_by: str = ""
    net_score: int = 0
    author_callsign: str = ""


@dataclass
class WardRoomEndorsement:
    id: str
    target_id: str        # thread_id or post_id
    target_type: str      # "thread" | "post"
    voter_id: str
    direction: str        # "up" | "down"
    created_at: float


@dataclass
class ChannelMembership:
    agent_id: str
    channel_id: str
    subscribed_at: float
    last_seen: float = 0.0
    notify: bool = True
    role: str = "member"  # "member" | "moderator"


@dataclass
class WardRoomCredibility:
    agent_id: str
    total_posts: int = 0
    total_endorsements: int = 0  # Net lifetime
    credibility_score: float = 0.5  # Rolling weighted [0, 1]
    restrictions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_activity REAL NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    thread_mode TEXT NOT NULL DEFAULT 'discuss',
    max_responders INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,
    net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '',
    channel_name TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    parent_id TEXT,
    author_id TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    edited_at REAL,
    deleted INTEGER NOT NULL DEFAULT 0,
    delete_reason TEXT NOT NULL DEFAULT '',
    deleted_by TEXT NOT NULL DEFAULT '',
    net_score INTEGER NOT NULL DEFAULT 0,
    author_callsign TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (thread_id) REFERENCES threads(id)
);

CREATE TABLE IF NOT EXISTS endorsements (
    id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    voter_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_endorsement_unique
    ON endorsements(target_id, voter_id);

CREATE TABLE IF NOT EXISTS memberships (
    agent_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    subscribed_at REAL NOT NULL,
    last_seen REAL NOT NULL DEFAULT 0.0,
    notify INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL DEFAULT 'member',
    PRIMARY KEY (agent_id, channel_id)
);

CREATE TABLE IF NOT EXISTS credibility (
    agent_id TEXT PRIMARY KEY,
    total_posts INTEGER NOT NULL DEFAULT 0,
    total_endorsements INTEGER NOT NULL DEFAULT 0,
    credibility_score REAL NOT NULL DEFAULT 0.5,
    restrictions TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS mod_actions (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    moderator_id TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_threads_channel ON threads(channel_id);
CREATE INDEX IF NOT EXISTS idx_posts_thread ON posts(thread_id);
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);
CREATE INDEX IF NOT EXISTS idx_mod_actions_channel ON mod_actions(channel_id);
"""


_MENTION_PATTERN = re.compile(r'@(\w+)')


def extract_mentions(text: str) -> list[str]:
    """Extract @callsign mentions from text."""
    return _MENTION_PATTERN.findall(text)
