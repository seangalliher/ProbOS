"""AD-754: user-directed data erasure manager ("forget this")."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from typing import Any

from probos.security.audit_log import AuditLog
from probos.types import EvictionDisposition

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
_OUTCOME_ATTACHMENT_KEYS = ("attachment_ids", "attachment_ref", "attachment_refs")
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


class ErasureCascadeIncomplete(Exception):
    """AD-1340: a cascade erased what it could, and some matching episodes are not erased.

    ``result`` is what was erased, ``failures`` maps each episode id whose erase raised to the original error, and
    ``enumeration_error`` is the first scan failure, the live scan's before the archive's (BF-905); the matches both
    scans found were erased all the same. The message carries counts only: no id and no content.
    """

    def __init__(
        self, result: ErasureResult, failures: dict[str, Exception], enumeration_error: Exception | None,
    ) -> None:
        super().__init__(
            f"erasure_cascade_incomplete:failed={len(failures)},scan_failed={enumeration_error is not None}"
        )
        self.result = result
        self.failures = failures
        self.enumeration_error = enumeration_error


async def _live_episodes(memory: Any) -> AsyncIterator[Any]:
    """BF-905: every live episode, through the memory's fail-closed erasure read ``iter_live_episodes``.

    No fallback to ``list_episodes``: that is AD-689's best-effort backfill read, which returns nothing for a stopped
    store or a failed read and skips rows it cannot rebuild. A memory without ``iter_live_episodes`` cannot be scanned,
    so its ``AttributeError`` becomes the live scan's error and the cascade raises after erasing what the archive scan
    found. A module function, not a method: ``ErasureManager`` stays within the SRP review trigger of 15 direct methods.
    """
    async for episode in memory.iter_live_episodes():
        yield episode


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
        """Delete one episode and related attachment refs, then mark audit rows.

        The attachments are unlinked BEFORE the episode is erased (AD-1340): delete what a record names before
        you delete the record. The attachment ids exist only in the episode's own records, and a failed erase has
        already removed them by the time it raises, so a retry could never find them again. ``mark_deleted`` runs
        only after a successful erase; an erase failure is raised as the original typed error, unwrapped.
        """
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        unlinked = await self._delete_attachments(attachment_ids)
        deleted_episodes = 0
        if self._episodic_memory is not None and hasattr(self._episodic_memory, "evict_by_ids"):
            # AD-1340: erasure is explicit, never derived from the caller's
            # free-text reason (routers/security.py:23,73).
            deleted_episodes = int(
                await self._episodic_memory.evict_by_ids(
                    [episode_id], reason=reason, disposition=EvictionDisposition.ERASE,
                )
            )

        if self._audit_log is not None:
            await self._audit_log.mark_deleted(episode_id)

        return ErasureResult(
            count=deleted_episodes + len(unlinked),
            timestamps=[self._now_iso()],
            deleted_episode_ids=[episode_id] if deleted_episodes > 0 else [],
            deleted_attachment_ids=unlinked,
        )

    async def forget_resource(self, resource_path: str) -> ErasureResult:
        """Delete all episodes that mention a resource path.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase.
        """
        needle = resource_path.lower()

        def mentions_resource(episode: Any) -> bool:
            serialized = json.dumps(self._episode_to_dict(episode), sort_keys=True, default=str).lower()
            return needle in serialized

        matching_ids, enumeration_error = await self._matching_ids(mentions_resource)
        return await self._forget_all(matching_ids, enumeration_error)

    async def forget_agent_memory(self, agent_id: str) -> ErasureResult:
        """Delete all episodes involving a specific agent.

        Erases every match it can and raises ``ErasureCascadeIncomplete`` if any did not erase.
        """

        def involves_agent(episode: Any) -> bool:
            return agent_id in list(getattr(episode, "agent_ids", []) or [])

        matching_ids, enumeration_error = await self._matching_ids(involves_agent)
        return await self._forget_all(matching_ids, enumeration_error)

    async def _matching_ids(self, matches: Callable[[Any], bool]) -> tuple[list[str], Exception | None]:
        """The ids of the candidate episodes ``matches`` accepts, and the first error that cut a scan short, if any.

        BF-905: the live store and the archive are scanned separately, live first, so a failure of one never skips
        the other. A failed scan keeps the matches it found before failing; the caller erases every match from both
        scans, then raises ``ErasureCascadeIncomplete`` carrying the FIRST scan error (``_scan`` logs each at ERROR).
        Under-erasing is the worse failure (BF-868). An archived version is NOT dropped because its id is also live
        (AD-1340 R1): deterministic ids can have a live rewrite that differs from the archived version, and the
        predicate must see both; duplicate ids are removed here.
        """
        memory = self._episodic_memory
        if memory is None:
            return [], None  # F-130 (#1523) owns the unwired case: no episodic memory, nothing to scan
        live, live_error = await self._scan("live", _live_episodes(memory), matches)
        archived, archive_error = await self._scan("archive", self._archived_episodes(), matches)
        enumeration_error = live_error if live_error is not None else archive_error
        found = live + archived
        return list(dict.fromkeys(episode_id for episode_id in found if episode_id)), enumeration_error

    async def _scan(
        self, store: str, episodes: AsyncIterator[Any], matches: Callable[[Any], bool],
    ) -> tuple[list[str], Exception | None]:
        """BF-905: the ids ``matches`` accepts in one store's scan, and the error that cut it short, if any."""
        found: list[str] = []
        try:
            async for episode in episodes:
                if matches(episode):
                    found.append(str(getattr(episode, "id", "")))
        except Exception as exc:
            logger.error(
                "BF-905: the %s erasure scan failed after finding %d match(es); "
                "they are erased, then the failure is raised",
                store, len(found), exc_info=True,
            )
            return found, exc  # BF-905: the matches found before the failure are still erased
        return found, None

    async def _forget_all(self, episode_ids: list[str], enumeration_error: Exception | None) -> ErasureResult:
        """Erase each episode in turn; raise ``ErasureCascadeIncomplete`` if the scan or any erase failed."""
        total_count = 0
        deleted_episodes: list[str] = []
        deleted_attachments: set[str] = set()
        failures: dict[str, Exception] = {}
        for episode_id in episode_ids:
            try:
                result = await self.forget_episode(episode_id)
            except Exception as exc:
                failures[episode_id] = exc  # erase the rest, then raise one error naming every failure
                logger.error(
                    "AD-1340: erasing episode %s failed: %r; "
                    "the remaining episodes are still erased, then the failure is raised",
                    episode_id, exc,
                )
                continue
            total_count += result.count
            deleted_episodes.extend(result.deleted_episode_ids)
            deleted_attachments.update(result.deleted_attachment_ids)

        erased = ErasureResult(
            count=total_count,
            timestamps=[self._now_iso()],
            deleted_episode_ids=deleted_episodes,
            deleted_attachment_ids=sorted(deleted_attachments),
        )
        if failures or enumeration_error is not None:
            cause = enumeration_error if enumeration_error is not None else next(iter(failures.values()))
            raise ErasureCascadeIncomplete(erased, failures, enumeration_error) from cause
        return erased

    async def _archived_episodes(self) -> AsyncIterator[Any]:
        """Every archived version (AD-1340 R1); ``iter_archived_episodes`` already fails closed.

        Under-erasing is the worse failure (BF-868): a cascade that skipped the archive would leave the Captain's
        forgotten episode recoverable.
        """
        if self._episodic_memory is None or not hasattr(self._episodic_memory, "iter_archived_episodes"):
            return
        async for episode in self._episodic_memory.iter_archived_episodes():
            yield episode  # every archived version: the predicate decides, _matching_ids deduplicates

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

        AD-1340 R1: every archived version's raw metadata is always added.
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
        # AD-1340 R1: EVERY archived version's raw metadata (the same flat shape
        # _normalize_payload decodes) is always added to the live episode's, not
        # only when the episode is not live: ERASE deletes every archive row for
        # the id, so every version's attachments are in scope.
        ids = self._extract_attachment_ids(episode_payload)
        if hasattr(self._episodic_memory, "get_archived_metadata_versions"):
            for archived_meta in await self._episodic_memory.get_archived_metadata_versions(episode_id):
                ids |= self._extract_attachment_ids(archived_meta)
        return ids

    async def _delete_attachments(self, attachment_ids: set[str]) -> list[str]:
        """Unlink each attachment; return the sorted ids the store reported as removed."""
        if self._attachment_store is None:
            return []
        unlinked: list[str] = []
        for attachment_id in sorted(attachment_ids):
            if await self._attachment_store.unlink(attachment_id):
                unlinked.append(attachment_id)
        return unlinked

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
