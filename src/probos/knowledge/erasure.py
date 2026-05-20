"""AD-754: user-directed data erasure manager ("forget this")."""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime, timezone
from typing import Any

from probos.security.audit_log import AuditLog

_ATTACHMENT_ID_RE = re.compile(r"\b[a-f0-9]{64}\b")


@dataclasses.dataclass(frozen=True)
class ErasureResult:
    count: int
    timestamps: list[str]
    deleted_episode_ids: list[str]
    deleted_attachment_ids: list[str]


class ErasureManager:
    def __init__(
        self,
        episodic_memory: Any | None,
        attachment_store: Any | None,
        audit_log: AuditLog | None,
    ) -> None:
        self._episodic_memory = episodic_memory
        self._attachment_store = attachment_store
        self._audit_log = audit_log

    async def forget_episode(self, episode_id: str, reason: str = "user_request") -> ErasureResult:
        """Delete one episode and related attachment refs, then mark audit rows."""
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        deleted_episodes = 0
        if self._episodic_memory is not None and hasattr(self._episodic_memory, "evict_by_ids"):
            deleted_episodes = int(
                await self._episodic_memory.evict_by_ids([episode_id], reason=reason)
            )

        deleted_attachments = await self._delete_attachments(attachment_ids)

        if self._audit_log is not None:
            await self._audit_log.mark_deleted(episode_id)

        return ErasureResult(
            count=deleted_episodes + deleted_attachments,
            timestamps=[self._now_iso()],
            deleted_episode_ids=[episode_id] if deleted_episodes > 0 else [],
            deleted_attachment_ids=sorted(attachment_ids)[:deleted_attachments],
        )

    async def forget_resource(self, resource_path: str) -> ErasureResult:
        """Delete all episodes that mention a resource path."""
        episodes = await self._list_episodes()
        matching_ids: list[str] = []
        needle = resource_path.lower()
        for episode in episodes:
            serialized = json.dumps(self._episode_to_dict(episode), sort_keys=True, default=str).lower()
            if needle in serialized:
                matching_ids.append(str(getattr(episode, "id", "")))

        total_count = 0
        deleted_episodes: list[str] = []
        deleted_attachments: set[str] = set()
        for episode_id in matching_ids:
            if not episode_id:
                continue
            result = await self.forget_episode(episode_id)
            total_count += result.count
            deleted_episodes.extend(result.deleted_episode_ids)
            deleted_attachments.update(result.deleted_attachment_ids)

        return ErasureResult(
            count=total_count,
            timestamps=[self._now_iso()],
            deleted_episode_ids=deleted_episodes,
            deleted_attachment_ids=sorted(deleted_attachments),
        )

    async def forget_agent_memory(self, agent_id: str) -> ErasureResult:
        """Delete all episodes involving a specific agent."""
        episodes = await self._list_episodes()
        matching_ids = [
            str(getattr(ep, "id", ""))
            for ep in episodes
            if agent_id in list(getattr(ep, "agent_ids", []) or [])
        ]

        total_count = 0
        deleted_episodes: list[str] = []
        deleted_attachments: set[str] = set()
        for episode_id in matching_ids:
            if not episode_id:
                continue
            result = await self.forget_episode(episode_id)
            total_count += result.count
            deleted_episodes.extend(result.deleted_episode_ids)
            deleted_attachments.update(result.deleted_attachment_ids)

        return ErasureResult(
            count=total_count,
            timestamps=[self._now_iso()],
            deleted_episode_ids=deleted_episodes,
            deleted_attachment_ids=sorted(deleted_attachments),
        )

    async def _list_episodes(self) -> list[Any]:
        if self._episodic_memory is None or not hasattr(self._episodic_memory, "list_episodes"):
            return []
        return list(await self._episodic_memory.list_episodes(limit=None))

    async def _attachment_ids_for_episode(self, episode_id: str) -> set[str]:
        if self._episodic_memory is None:
            return set()

        episode_payload: dict[str, Any] = {}
        if hasattr(self._episodic_memory, "get_by_ids"):
            found = await self._episodic_memory.get_by_ids([episode_id])
            if found:
                episode_payload = self._episode_to_dict(found[0])
        if not episode_payload and hasattr(self._episodic_memory, "get_episode_metadata"):
            meta = await self._episodic_memory.get_episode_metadata(episode_id)
            if isinstance(meta, dict):
                episode_payload = meta

        return self._extract_attachment_ids(episode_payload)

    async def _delete_attachments(self, attachment_ids: set[str]) -> int:
        if self._attachment_store is None:
            return 0
        deleted = 0
        for attachment_id in attachment_ids:
            if await self._attachment_store.unlink(attachment_id):
                deleted += 1
        return deleted

    def _extract_attachment_ids(self, payload: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(payload, str):
            found.update(_ATTACHMENT_ID_RE.findall(payload.lower()))
            return found
        if isinstance(payload, dict):
            for value in payload.values():
                found.update(self._extract_attachment_ids(value))
            return found
        if isinstance(payload, list):
            for value in payload:
                found.update(self._extract_attachment_ids(value))
            return found
        return found

    def _episode_to_dict(self, episode: Any) -> dict[str, Any]:
        if dataclasses.is_dataclass(episode):
            return dataclasses.asdict(episode)
        if isinstance(episode, dict):
            return episode
        data = getattr(episode, "__dict__", {})
        return dict(data) if isinstance(data, dict) else {}

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
