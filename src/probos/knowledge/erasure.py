"""AD-754: user-directed data erasure manager ("forget this")."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from probos.security.audit_log import AuditLog

logger = logging.getLogger(__name__)

_ATTACHMENT_ID_RE = re.compile(r"\b[a-f0-9]{64}\b")

# BF-868 (#1343): the ONLY places a genuine attachment id is written into an
# episode. Enumerated against the live tree by walking every ``Episode(`` and
# ``store_episode(`` call in ``src/``, because under-erasing is the worse
# failure of the two -- data the Captain asked to be forgotten surviving is
# worse than an unrelated file being kept.
#
#   anchors.visual_attachment_ref         AD-987 group fan-out
#                                         (thread_fanout.py, types.py:502)
#   outcomes[].attachment_ids             AD-720d-3 Captain-chat vision
#                                         (routers/chat.py)
#   outcomes[].attachment_ref             AD-733 perception anchors
#                                         (routers/perception.py,
#                                          perception/consumer.py)
#   outcomes[].per_attachment_timing[]    AD-720d-1 per-attachment latency
#     .attachment_id                      (dm/reply_pipeline.py, chat.py).
#                                         On the 1:1 DM path this is the ONLY
#                                         carrier -- that episode has no
#                                         ``attachment_ids`` key at all.
#   <metadata>.attachment_id              AD-730-3 image gen
#                                         (cognitive/image_gen_dispatch.py),
#                                         reachable only through the flat
#                                         metadata shape below.
#
# All are typed fields holding bare SHA-256 hex. No production path embeds an
# attachment id in free text, so the free-text scan had no genuine producer to
# serve -- it was pure risk.
_ANCHOR_ATTACHMENT_FIELDS = ("visual_attachment_ref",)
_OUTCOME_ATTACHMENT_KEYS = ("attachment_ids", "attachment_ref")
# Outcome keys holding a LIST OF RECORDS, each record carrying an id.
_OUTCOME_RECORD_LIST_KEYS: dict[str, tuple[str, ...]] = {
    "per_attachment_timing": ("attachment_id",),
}
_METADATA_ATTACHMENT_KEYS = ("attachment_id",)

# ``get_episode_metadata`` returns the raw ChromaDB row, which stores
# ``outcomes``/``anchors`` as JSON STRINGS (episodic.py:3550-3557) rather than
# nested objects. Decoded back to the nested shape before extraction.
_FLAT_JSON_FIELDS = (("outcomes_json", "outcomes"), ("anchors_json", "anchors"))


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
        """Collect every attachment id this episode declares.

        BF-868 reachability scope, recorded rather than left to be rediscovered.
        The metadata fallback runs ONLY when ``get_by_ids`` yields nothing, so a
        producer that writes into episode METADATA (rather than into the
        ``Episode`` dataclass) is seen on this path and not through the
        ``forget_resource`` / ``forget_agent_memory`` cascades -- those rehydrate
        a dataclass, which is a non-empty payload, so the fallback never runs.

        Accepted deliberately rather than fixed by querying both stores for
        every episode, which would add a second round trip per episode to every
        cascade. The only metadata-shaped producer is AD-730-3 image generation,
        and it is currently DEAD at the write side: it is guarded by
        ``hasattr(episodic, "store_episode")`` and ``EpisodicMemory`` has no
        such method (verified by execution, twice). The key is still extracted
        so that repairing that guard does not silently reintroduce an
        under-erase.

        If a live metadata-shaped producer ever appears, merge the two payloads
        here instead of treating them as alternatives.
        """
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
        """Read attachment ids from the fields DECLARED to carry them.

        BF-868 (#1343): this used to scan every string anywhere in the payload
        with a bare ``[a-f0-9]{64}`` regex, inferring identity from SHAPE. Any
        coincidentally-shaped token -- a hash-suffixed MCP tool name, a channel
        label, a hex string the Captain typed, a digest an LLM echoed into
        ``outcomes[].response`` -- was treated as an attachment id and unlinked.

        ``AttachmentStore.unlink`` is a HARD delete with no refcount, so one
        wrong id is permanent loss of a file nothing referenced.

        The scan is now keyed on structure instead of shape. Values are still
        shape-CHECKED before use, so a malformed entry in a declared field is
        skipped rather than passed to ``unlink``.

        Known and accepted: an attachment id embedded in free text is no longer
        erased. No production path does that today (enumerated above), and the
        alternative -- deleting unrelated files on a coincidence -- is worse.
        A future producer must write into a declared field, not free prose.
        """
        found: set[str] = set()
        payload = self._normalize_payload(payload)
        if not payload:
            return found

        for key in _METADATA_ATTACHMENT_KEYS:
            found.update(self._ids_from_value(payload.get(key)))

        anchors = payload.get("anchors")
        if isinstance(anchors, dict):
            for field_name in _ANCHOR_ATTACHMENT_FIELDS:
                found.update(self._ids_from_value(anchors.get(field_name)))

        outcomes = payload.get("outcomes")
        if isinstance(outcomes, list):
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                for key in _OUTCOME_ATTACHMENT_KEYS:
                    found.update(self._ids_from_value(outcome.get(key)))
                for list_key, record_keys in _OUTCOME_RECORD_LIST_KEYS.items():
                    records = outcome.get(list_key)
                    if not isinstance(records, (list, tuple)):
                        continue
                    for record in records:
                        if not isinstance(record, dict):
                            continue
                        for record_key in record_keys:
                            found.update(self._ids_from_value(record.get(record_key)))
        return found

    @staticmethod
    def _normalize_payload(payload: Any) -> dict[str, Any]:
        """Bring the flat ``get_episode_metadata`` row into the nested shape.

        BF-868 (#1343): ``_attachment_ids_for_episode`` has two sources.
        ``get_by_ids`` yields a dataclass, so ``asdict`` gives nested
        ``outcomes``/``anchors``. The ``get_episode_metadata`` fallback yields
        the raw ChromaDB row, where those live as JSON strings under
        ``outcomes_json``/``anchors_json``. Without this decode the fallback
        extracted nothing at all, so any episode reached that way erased zero
        attachments -- silent under-erase.
        """
        if not isinstance(payload, dict):
            return {}
        normalized = dict(payload)
        for json_key, nested_key in _FLAT_JSON_FIELDS:
            if nested_key in normalized:
                continue
            raw = normalized.get(json_key)
            # Empty is the legitimate "no anchors" encoding, not a failure.
            if not isinstance(raw, str) or not raw:
                continue
            try:
                normalized[nested_key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                # Degrade rather than raise, but never silently: erasing
                # nothing is the exact failure this decode exists to fix.
                logger.warning(
                    "BF-868: could not decode %s while resolving attachments for "
                    "erasure; that half of the episode contributes no attachment "
                    "ids, so a referenced file may survive the erase",
                    json_key, exc_info=True,
                )
        return normalized

    @staticmethod
    def _ids_from_value(value: Any) -> set[str]:
        """Accept a bare id or a list of them, keeping only well-formed ones.

        ``fullmatch``, not ``search``: a declared field holds an id, so a value
        that merely CONTAINS one is malformed and not something to salvage.
        """
        if isinstance(value, str):
            candidates: list[Any] = [value]
        elif isinstance(value, (list, tuple)):
            candidates = list(value)
        else:
            return set()
        cleaned = (
            item.strip().lower() for item in candidates if isinstance(item, str)
        )
        # Return the CLEANED value, not the original: validating the stripped
        # form and then unlinking the padded one would silently under-erase,
        # because the store never matches a key with surrounding whitespace.
        return {value for value in cleaned if _ATTACHMENT_ID_RE.fullmatch(value)}

    def _episode_to_dict(self, episode: Any) -> dict[str, Any]:
        if dataclasses.is_dataclass(episode):
            return dataclasses.asdict(episode)
        if isinstance(episode, dict):
            return episode
        data = getattr(episode, "__dict__", {})
        return dict(data) if isinstance(data, dict) else {}

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()
