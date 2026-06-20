"""Session continuity model for Yeo and crew agents (AD-750).

Implements the AionUi-style session pattern: sessions are persistent JSON
files in data/sessions/, enabling working-memory recovery after restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _install_root() -> Path:
    """AD-1025b: ProbOS install root (session_manager.py -> parents[3]); NEVER the CWD."""
    return Path(__file__).resolve().parents[3]


def _default_session_dir() -> Path:
    """AD-1025b: use-time default sessions dir, anchored to the install root,
    resolved on each call (never at import)."""
    return _install_root() / "data" / "sessions"


@dataclass
class Session:
    """A single assistant session with its working-memory snapshot."""

    id: str  # UUID
    platform: str  # "desktop" | "web" | etc.
    user_id: str  # Captain identifier
    agent_type: str  # "Yeo" | "ArchitectAgent", etc.
    started_at: datetime
    last_activity: datetime
    active_tasks: list[str] = field(default_factory=list)  # Task.ids active in session
    context: dict[str, Any] = field(default_factory=dict)  # working memory snapshot


def _session_to_dict(session: Session) -> dict[str, Any]:
    d = asdict(session)
    d["started_at"] = session.started_at.isoformat()
    d["last_activity"] = session.last_activity.isoformat()
    return d


def _dict_to_session(d: dict[str, Any]) -> Session:
    return Session(
        id=d["id"],
        platform=d["platform"],
        user_id=d["user_id"],
        agent_type=d["agent_type"],
        started_at=datetime.fromisoformat(d["started_at"]),
        last_activity=datetime.fromisoformat(d["last_activity"]),
        active_tasks=d.get("active_tasks", []),
        context=d.get("context", {}),
    )



class SessionManager:
    """Manages assistant sessions with JSON persistence.

    Sessions are stored in data/sessions/<session_id>.json.
    Closed sessions are moved to data/sessions/archive/.
    """
    async def restore_active_session(self, captain_id: str) -> Session | None:
        """On startup, recover last active session if within 24h."""
        # For demo: scan all sessions, find latest for captain_id within 24h
        now = datetime.now(timezone.utc)
        latest = None
        for session_file in self._dir.glob("*.json"):
            try:
                with session_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("user_id") == captain_id:
                    last_activity = datetime.fromisoformat(data["last_activity"])
                    if (now - last_activity).total_seconds() < 86400:
                        if not latest or last_activity > latest.last_activity:
                            latest = _dict_to_session(data)
            except Exception:
                continue
        if latest:
            # Restore context, resume pending tasks
            latest.context = latest.context  # placeholder for _restore_context
            return latest
        return None

    async def resume_delegated_tasks(self, session: Session) -> list[str]:
        """List incomplete tasks from session (active_tasks field)."""
        return session.active_tasks

    def __init__(
        self,
        sessions_dir: str | Path | None = None,
        user_id: str = "captain",
    ) -> None:
        if sessions_dir is None:
            sessions_dir = _default_session_dir()
        self._dir = Path(sessions_dir)
        self._archive_dir = self._dir / "archive"
        self._user_id = user_id
        self._dir.mkdir(parents=True, exist_ok=True)
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_session(self, agent_type: str, platform: str = "desktop") -> Session:
        """Start a new session and persist it to disk."""
        now = datetime.now(timezone.utc)
        session = Session(
            id=uuid.uuid4().hex,
            platform=platform,
            user_id=self._user_id,
            agent_type=agent_type,
            started_at=now,
            last_activity=now,
        )
        await self._write(session)
        logger.info(
            "SessionManager: created session id=%s agent=%s", session.id, agent_type
        )
        return session

    async def restore_session(self, session_id: str) -> Session | None:
        """Load a session from disk; returns None if not found or corrupt."""
        path = self._path(session_id)
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, path.read_text, "utf-8")
            session = _dict_to_session(json.loads(data))
            logger.info("SessionManager: restored session id=%s", session_id)
            return session
        except FileNotFoundError:
            logger.warning(
                "SessionManager.restore_session: session %s not found; "
                "returning None (graceful degradation)",
                session_id,
            )
            return None
        except Exception:
            logger.warning(
                "SessionManager.restore_session: session %s could not be loaded; "
                "returning None",
                session_id,
                exc_info=True,
            )
            return None

    async def update_session_context(
        self, session_id: str, context: dict[str, Any]
    ) -> None:
        """Merge new context into session's working memory and persist."""
        session = await self.restore_session(session_id)
        if session is None:
            logger.warning(
                "SessionManager.update_session_context: session %s not found; "
                "skipping context update",
                session_id,
            )
            return
        session.context.update(context)
        session.last_activity = datetime.now(timezone.utc)
        await self._write(session)

    async def close_session(self, session_id: str) -> None:
        """Mark session complete and archive to history."""
        path = self._path(session_id)
        archive_path = self._archive_dir / f"{session_id}.json"
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, path.rename, archive_path)
            logger.info("SessionManager: archived session id=%s", session_id)
        except FileNotFoundError:
            logger.warning(
                "SessionManager.close_session: session %s not found; "
                "nothing to archive",
                session_id,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _write(self, session: Session) -> None:
        loop = asyncio.get_running_loop()
        data = json.dumps(_session_to_dict(session), indent=2)
        await loop.run_in_executor(None, self._path(session.id).write_text, data, "utf-8")
