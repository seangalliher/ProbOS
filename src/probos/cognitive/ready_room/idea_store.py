"""AD-475: IdeaCaptureStore -- stdlib JSON-backed idea queue.

Persists to runtime.data_dir/ready_room/ideas.json with atomic writes.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


_VALID_STATUSES = ("open", "in_session", "resolved", "deferred")


@dataclass(frozen=True)
class Idea:
    """A captured strategic idea.

    status transitions: open -> in_session -> resolved | deferred.
    """

    id: str
    title: str
    body: str
    captured_at: float
    captured_by: str = ""        # callsign or "captain"
    status: str = "open"
    tags: list[str] = field(default_factory=list)


class IdeaCaptureStore:
    """v1 persistent idea queue.

    Public API:
      - capture(title, body, captured_by, tags) -> Idea
      - list_ideas(status='open'|'all') -> list[Idea]
      - mark_status(idea_id, status) -> bool
      - get_idea(idea_id) -> Idea | None
    """

    def __init__(
        self,
        *,
        store_path: Path | None = None,
        emit_event: Any | None = None,
    ) -> None:
        self._store_path = store_path
        self._emit_event = emit_event
        self._ideas: dict[str, Idea] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded or self._store_path is None:
            return
        if self._store_path.exists():
            try:
                raw = json.loads(self._store_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    for entry in raw:
                        if isinstance(entry, dict) and "id" in entry:
                            self._ideas[entry["id"]] = Idea(
                                id=str(entry.get("id", "")),
                                title=str(entry.get("title", "")),
                                body=str(entry.get("body", "")),
                                captured_at=float(entry.get("captured_at", 0.0) or 0.0),
                                captured_by=str(entry.get("captured_by", "")),
                                status=str(entry.get("status", "open")),
                                tags=list(entry.get("tags", []) or []),
                            )
            except (json.JSONDecodeError, OSError):
                logger.warning(
                    "AD-475: idea store read failed (path=%s); starting empty",
                    self._store_path, exc_info=True,
                )
        self._loaded = True

    def _save(self) -> bool:
        if self._store_path is None:
            return False
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._store_path.with_suffix(".json.tmp")
            payload = [
                {
                    "id": i.id,
                    "title": i.title,
                    "body": i.body,
                    "captured_at": i.captured_at,
                    "captured_by": i.captured_by,
                    "status": i.status,
                    "tags": list(i.tags),
                }
                for i in self._ideas.values()
            ]
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, self._store_path)
            return True
        except OSError:
            logger.error(
                "AD-475: idea store write failed (path=%s)",
                self._store_path, exc_info=True,
            )
            return False

    def capture(
        self, *, title: str, body: str = "", captured_by: str = "",
        tags: list[str] | None = None,
    ) -> Idea:
        self._load()
        idea = Idea(
            id=uuid.uuid4().hex,
            title=title,
            body=body,
            captured_at=time.time(),
            captured_by=captured_by,
            status="open",
            tags=list(tags or []),
        )
        self._ideas[idea.id] = idea
        self._save()
        self._emit_captured(idea)
        return idea

    def list_ideas(self, *, status: str = "open") -> list[Idea]:
        self._load()
        if status == "all":
            return list(self._ideas.values())
        return [i for i in self._ideas.values() if i.status == status]

    def get_idea(self, idea_id: str) -> Idea | None:
        self._load()
        return self._ideas.get(idea_id)

    def mark_status(self, idea_id: str, status: str) -> bool:
        if status not in _VALID_STATUSES:
            return False
        self._load()
        idea = self._ideas.get(idea_id)
        if idea is None:
            return False
        self._ideas[idea_id] = replace(idea, status=status)
        self._save()
        return True

    def _emit_captured(self, idea: Idea) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(
                EventType.IDEA_CAPTURED,
                {
                    "idea_id": idea.id,
                    "title": idea.title[:200],
                    "captured_by": idea.captured_by,
                    "tags": list(idea.tags),
                },
            )
        except Exception:
            logger.warning(
                "AD-475: IDEA_CAPTURED emit failed (id=%s)", idea.id, exc_info=True,
            )
