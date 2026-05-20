"""Semantic mapper — hydrates the semantic work layer from existing data (AD-750).

Maps episodic ChromaDB entries tagged as task/meeting/commitment into the
SemanticStore, and syncs M365 connector data (Outlook tasks, Calendar
meetings) into the store.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from probos.knowledge.semantic_store import SemanticStore
from probos.types import (
    Commitment,
    Meeting,
    SemanticEntity,
    Task,
)

if TYPE_CHECKING:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.integrations.m365_connector import M365Connector

logger = logging.getLogger(__name__)

_TASK_KEYWORDS = ("task", "todo", "to-do", "to do", "action item")
_MEETING_KEYWORDS = ("meeting", "call", "standup", "sync", "review", "interview")
_COMMITMENT_KEYWORDS = ("commit", "committed", "promise", "deliver", "owe")


def _classify_document(doc: str, metadata: dict) -> str | None:
    """Return entity_type for a ChromaDB document, or None if unclassifiable."""
    entity_type = metadata.get("entity_type", "")
    if entity_type in ("task", "meeting", "commitment"):
        return entity_type
    text = doc.lower()
    for kw in _TASK_KEYWORDS:
        if kw in text:
            return "task"
    for kw in _MEETING_KEYWORDS:
        if kw in text:
            return "meeting"
    for kw in _COMMITMENT_KEYWORDS:
        if kw in text:
            return "commitment"
    return None


def _make_entity_from_episode(
    doc_id: str,
    doc: str,
    metadata: dict,
    entity_type: str,
    owner_id: str,
) -> SemanticEntity:
    """Construct a SemanticEntity from a ChromaDB episode entry."""
    now = datetime.now(timezone.utc)
    raw_ts = metadata.get("timestamp", 0.0)
    try:
        created_at = datetime.fromtimestamp(float(raw_ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        created_at = now

    base_kwargs: dict[str, Any] = dict(
        id=metadata.get("episode_id", doc_id) or uuid.uuid4().hex,
        entity_type=entity_type,
        owner_id=owner_id,
        created_at=created_at,
        modified_at=now,
        content=doc[:2000],  # cap at 2000 chars
    )

    if entity_type == "task":
        return Task(
            **base_kwargs,
            title=metadata.get("title", doc[:80]),
        )
    if entity_type == "meeting":
        return Meeting(
            **base_kwargs,
            title=metadata.get("title", doc[:80]),
        )
    if entity_type == "commitment":
        return Commitment(
            **base_kwargs,
            description=doc[:500],
            stake_agent=metadata.get("agent_id", ""),
        )
    # Fallback to base entity
    return SemanticEntity(**base_kwargs)


class SemanticMapper:
    """Hydrates the SemanticStore from episodic memory and M365 connectors.

    The episodic_memory is accepted as an opaque Any to avoid the circular
    import between integrations/ and cognitive/episodic.py (which imports
    knowledge/embeddings.py). The constructor validates it via duck-typing.
    """

    def __init__(
        self,
        store: SemanticStore,
        owner_id: str = "captain",
        episodic_memory: Any = None,  # EpisodicMemory | None
    ) -> None:
        self._store = store
        self._owner_id = owner_id
        self._episodic = episodic_memory

    async def bootstrap_from_episodic(self, store: SemanticStore) -> int:
        """Scan ChromaDB for task/meeting/commitment episodes and insert into store.

        Returns the count of entities successfully migrated.
        """
        if self._episodic is None:
            logger.info(
                "SemanticMapper.bootstrap_from_episodic: no episodic memory wired; "
                "returning 0"
            )
            return 0

        collection = getattr(self._episodic, "_collection", None)
        if collection is None:
            logger.warning(
                "SemanticMapper.bootstrap_from_episodic: episodic collection not "
                "initialised; returning 0"
            )
            return 0

        try:
            result = collection.get(include=["documents", "metadatas"])
        except Exception:
            logger.warning(
                "SemanticMapper.bootstrap_from_episodic: ChromaDB get() failed",
                exc_info=True,
            )
            return 0

        documents: list[str] = result.get("documents") or []
        metadatas: list[dict] = result.get("metadatas") or []
        ids: list[str] = result.get("ids") or []

        count = 0
        for doc_id, doc, meta in zip(ids, documents, metadatas):
            if not doc:
                continue
            entity_type = _classify_document(doc, meta or {})
            if entity_type is None:
                continue
            entity = _make_entity_from_episode(
                doc_id=doc_id,
                doc=doc,
                metadata=meta or {},
                entity_type=entity_type,
                owner_id=self._owner_id,
            )
            try:
                await store.insert_entity(entity)
                count += 1
            except Exception:
                logger.warning(
                    "SemanticMapper.bootstrap_from_episodic: failed to insert "
                    "entity id=%s; skipping",
                    entity.id,
                    exc_info=True,
                )

        logger.info(
            "SemanticMapper.bootstrap_from_episodic: migrated %d entities", count
        )
        return count

    async def sync_m365_to_semantic(self, connectors: list[M365Connector]) -> int:
        """Fetch current tasks/meetings from M365 connectors and upsert into store.

        Returns count of entities inserted or updated.
        """
        now = datetime.now(timezone.utc)
        # Default sync window: changes since far past (full sync)
        since = datetime(2000, 1, 1, tzinfo=timezone.utc)

        count = 0
        for connector in connectors:
            connector_type = getattr(connector, "agent_type", "unknown")
            try:
                changes: list[dict] = await connector.list_changes(since=since)
            except Exception:
                logger.warning(
                    "SemanticMapper.sync_m365_to_semantic: list_changes failed "
                    "for %s; skipping",
                    connector_type,
                    exc_info=True,
                )
                continue

            for change in changes:
                entity = self._change_to_entity(change, connector_type, now)
                if entity is None:
                    continue
                try:
                    await self._store.insert_entity(entity)
                    count += 1
                except Exception:
                    logger.warning(
                        "SemanticMapper.sync_m365_to_semantic: insert failed for "
                        "change id=%s; skipping",
                        change.get("id", "?"),
                        exc_info=True,
                    )

        logger.info(
            "SemanticMapper.sync_m365_to_semantic: synced %d entities from "
            "%d connector(s)",
            count,
            len(connectors),
        )
        return count

    def _change_to_entity(
        self, change: dict, connector_type: str, now: datetime
    ) -> SemanticEntity | None:
        """Convert an M365 change record to a SemanticEntity."""
        resource_type = change.get("resource_type", connector_type)
        entity_id = change.get("id") or uuid.uuid4().hex
        created_str = change.get("created_at") or change.get("timestamp")
        try:
            created_at = (
                datetime.fromisoformat(str(created_str))
                if created_str
                else now
            )
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            created_at = now

        base_kwargs: dict[str, Any] = dict(
            id=entity_id,
            owner_id=self._owner_id,
            created_at=created_at,
            modified_at=now,
            content=change.get("subject") or change.get("title") or str(change)[:200],
        )

        if "calendar" in connector_type.lower() or resource_type == "event":
            start_raw = change.get("start") or change.get("start_time")
            end_raw = change.get("end") or change.get("end_time")
            try:
                start = datetime.fromisoformat(str(start_raw)) if start_raw else now
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                start = now
            try:
                end = datetime.fromisoformat(str(end_raw)) if end_raw else now
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                end = now
            return Meeting(
                **base_kwargs,
                entity_type="meeting",
                title=change.get("subject") or change.get("title") or "",
                start_time=start,
                end_time=end,
                attendees=change.get("attendees") or [],
                location=change.get("location"),
            )

        if "outlook" in connector_type.lower() or resource_type == "task":
            due_raw = change.get("due") or change.get("due_date")
            try:
                due = datetime.fromisoformat(str(due_raw)) if due_raw else None
                if due and due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                due = None
            return Task(
                **base_kwargs,
                entity_type="task",
                title=change.get("subject") or change.get("title") or "",
                due_date=due,
            )

        # Fallback: store as base entity
        return SemanticEntity(**base_kwargs, entity_type="document")
