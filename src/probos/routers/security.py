"""AD-754 security endpoints."""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from probos.cognitive.episode_archive import (
    LOOKUP_DEFAULT_LIMIT,
    LOOKUP_MAX_LIMIT,
    ArchivedEpisode,
    EpisodeArchiveConflict,
    EpisodeArchiveError,
    EpisodeArchiveNotFound,
    EpisodeArchiveUnavailable,
)
from probos.credential_store import crew_scope_token
from probos.knowledge.archive_promotion import exit_note_citations
from probos.knowledge.archive_store import ArchiveStore
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager
from probos.knowledge.erasure import ExitNotesBlockErasure
from probos.knowledge.records_store import RecordsStore
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.security.audit_log import AuditLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/security", tags=["security"])


class ForgetRequest(BaseModel):
    episode_id: str | None = None
    resource_path: str | None = None
    agent_id: str | None = None
    reason: str = "user_request"

    @model_validator(mode="after")
    def _validate_target(self) -> "ForgetRequest":
        provided = [
            bool(self.episode_id),
            bool(self.resource_path),
            bool(self.agent_id),
        ]
        if sum(1 for flag in provided if flag) != 1:
            raise ValueError("exactly one of episode_id/resource_path/agent_id is required")
        return self


def _install_root() -> Path:
    """AD-1025b: the ProbOS install/repo root. ``src/probos/routers/security.py``
    -> ``parents[3]`` (security->routers->probos->src->root). Mirrors
    ``__main__.py``'s ``project_root`` and ``piper_backend._probos_root`` (the
    bundled ``tools/`` anchor). NEVER the CWD."""
    return Path(__file__).resolve().parents[3]


def _get_audit_log(runtime: Any) -> AuditLog:
    existing = getattr(runtime, "_assistant_audit_log", None)
    if isinstance(existing, AuditLog):
        return existing

    retention = int(getattr(runtime.config.security_infra, "audit_retention_days", 90))
    data_dir = getattr(runtime, "data_dir", None)
    if data_dir is None:
        data_dir = _install_root() / "data"
    data_dir = Path(data_dir)
    log = AuditLog(db_path=str(data_dir / "assistant_audit.db"), retention_days=retention)
    runtime._assistant_audit_log = log
    return log


async def _pending_exit_note_citations(runtime: Any, archive: Any) -> dict[str, tuple[str, ...]] | None:
    """AD-1341 S4 (D14, D16): which episodes the exit notes the next reset would archive cite; None checks nothing.

    Only a real Ship's Records store is read (a runtime double's attribute is none), and only while the archive is
    enabled: a disabled archive promotes nothing. An enabled archive that is not open (failed at boot, or closed) is
    still checked, with every valid note counted, because the next reset opens the archive and would promote them
    (S3 register R2, for notes). A failed read propagates, so nothing is erased.
    """
    records = getattr(runtime, "records_store", None)
    section = getattr(getattr(runtime, "config", None), "archive", None)
    if not isinstance(records, RecordsStore) or getattr(section, "enabled", False) is not True:
        return None
    return await exit_note_citations(records, archive if isinstance(archive, ArchiveStore) else None)


@router.post("/forget")
async def request_erasure(
    request: ForgetRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """User-directed erasure for episode, resource, or agent memory.

    AD-1341 S3: while a Ship's Archive entry cites an episode this request would erase, nothing is erased and the
    answer is 409 with the entries' ids. The archive is append-only for agents and services, so this route never
    erases an entry: the Captain erases each with ``probos archive erase ENTRY_ID --reason TEXT``, then retries.
    """
    archive = getattr(runtime, "archive_store", None)  # AD-1341 S3: consulted only when it is a real store
    citations = await _pending_exit_note_citations(runtime, archive)  # AD-1341 S4 (D14): once, before any erase
    manager = ErasureManager(
        episodic_memory=getattr(runtime, "episodic_memory", None),
        attachment_store=getattr(runtime, "attachment_store", None),
        audit_log=_get_audit_log(runtime),
        exit_note_citations=citations,  # AD-1341 S4 (D14): the pending notes' citations
        archive_store=archive if isinstance(archive, ArchiveStore) else None,  # AD-1341 S3: a real store, or none
    )

    try:
        if request.episode_id:
            result = await manager.forget_episode(request.episode_id, reason=request.reason)
        elif request.resource_path:
            result = await manager.forget_resource(request.resource_path)
        elif request.agent_id:
            result = await manager.forget_agent_memory(request.agent_id)
        else:
            return JSONResponse(
                {"error": "one erasure target is required"},
                status_code=400,
            )
    except ExitNotesBlockErasure as exc:  # AD-1341 S4 (D14): nothing was erased
        logger.warning(
            "AD-1341 S4: an AD-754 erasure was refused: %d exit note(s) awaiting promotion cite its episodes",
            len(exc.paths),
        )
        return JSONResponse(
            {
                "error": "exit_notes_cite_erased_episodes",
                "exit_note_paths": list(exc.paths),
                "next": "probos archive veto PATH --reason TEXT for each, then retry",
            },
            status_code=409,
        )
    except ArchiveCitationsBlockErasure as exc:  # AD-1341 S3 (D8): nothing was erased
        logger.warning(
            "AD-1341 S3: an AD-754 erasure was refused: %d Ship's Archive entr(ies) cite its episodes",
            len(exc.entry_ids),
        )
        return JSONResponse(
            {
                "error": "archive_entries_cite_erased_episodes",
                "archive_entry_ids": list(exc.entry_ids),
                "next": "probos archive erase ENTRY_ID --reason TEXT for each, then retry",
            },
            status_code=409,
        )

    return {
        "deleted_count": result.count,
        "timestamps": result.timestamps,
        "deleted_episode_ids": result.deleted_episode_ids,
        "deleted_attachment_ids": result.deleted_attachment_ids,
    }


_ARCHIVE_LOOKUP_ACCESSOR = "captain:/api/security/archive/lookup"
_ARCHIVE_LOOKUP_TOKEN_REQUIRED = "episode_archive_lookup_requires_token"
_NON_FINITE_NUMBER_IN_BODY = "non_finite_number_in_body"
_UNPAIRED_SURROGATE_IN_BODY = "unpaired_surrogate_in_body"  # AD-1340 S2b A3


class ArchiveLookupRequest(BaseModel):
    """AD-1340 S2a: exactly one of ``episode_id`` or ``agent_id``; ``since``/``until``/``limit`` go with ``agent_id``."""

    model_config = {"extra": "forbid"}

    episode_id: str | None = Field(default=None, min_length=1, max_length=256)
    agent_id: str | None = Field(default=None, min_length=1, max_length=256)
    since: float | None = None
    until: float | None = None
    limit: int = Field(default=LOOKUP_DEFAULT_LIMIT, ge=1, le=LOOKUP_MAX_LIMIT)

    @model_validator(mode="after")
    def _validate_lookup(self) -> "ArchiveLookupRequest":
        if bool(self.episode_id) == bool(self.agent_id):
            raise ValueError("exactly one of episode_id/agent_id is required")
        if self.episode_id and self.model_fields_set & {"since", "until", "limit"}:
            raise ValueError("since/until/limit apply only to an agent_id lookup")
        for bound in (self.since, self.until):
            if bound is not None and not math.isfinite(bound):
                raise ValueError("since/until must be finite")
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("since must be earlier than until")
        return self


def _archived_episode_body(item: ArchivedEpisode) -> dict[str, Any]:
    return {
        "episode_id": item.record.episode_id,
        "content_hash": item.record.content_hash,
        "agent_id": item.agent_id,
        "episode_timestamp": item.episode_timestamp,
        "archived_at": item.archived_at,
        "reason": item.reason,
        "document": item.record.document,
        "metadata": dict(item.record.metadata),
    }


class _NonFiniteNumberInBody(ValueError):
    """AD-1340 S2a: a request body holds NaN, Infinity or a number that overflows a float."""


def _refuse_constant(name: str) -> float:
    raise _NonFiniteNumberInBody(name)


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _NonFiniteNumberInBody(text)
    return value


def _holds_unpaired_surrogate(parsed: Any) -> bool:
    """AD-1340 S2b A3: whether a parsed JSON body holds, in any key or value at any depth, an unpaired surrogate.

    ``json`` joins an escaped surrogate pair into one character and decodes raw bytes with ``surrogatepass``, so an
    unpaired one, escaped or raw, survives parsing. Strict UTF-8, which the framework's 422 renderer uses, cannot
    encode it. Iterative, so a body nested as deep as the parser allows cannot exhaust the stack.
    """
    pending: list[Any] = [parsed]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return False


async def _refuse_non_finite_numbers(request: Request) -> None:
    """AD-1340 S2a: 422 for a body holding a non-finite number, before validation runs.

    The framework's 422 handler echoes the offending input, cannot JSON-encode NaN or Infinity, and answers 500
    (follow-up on #1523). Re-reads the body the framework already cached; reads no runtime state, writes nothing.
    AD-1340 S2b A3: the same for an unpaired surrogate, which that handler cannot encode as UTF-8. A non-finite
    number is refused first (while parsing). Neither answer echoes the body. The name is kept for S2a's anchors.
    """
    try:
        parsed = json.loads(await request.body(), parse_constant=_refuse_constant, parse_float=_finite_float)
    except _NonFiniteNumberInBody as exc:
        raise HTTPException(status_code=422, detail=_NON_FINITE_NUMBER_IN_BODY) from exc
    except ValueError:
        return  # AD-1340 S2a: malformed JSON is the framework's to refuse (it parses first)
    # AD-1340 S2b A3: outside the try, and a bool rather than a raise: UnicodeEncodeError is a ValueError.
    if _holds_unpaired_surrogate(parsed):
        raise HTTPException(status_code=422, detail=_UNPAIRED_SURROGATE_IN_BODY)


@router.post(
    "/archive/lookup",
    dependencies=[Depends(require_crew_scope), Depends(_refuse_non_finite_numbers)],
)
async def lookup_archived_episodes(
    request: ArchiveLookupRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1340 S2a: the Captain's audited read of archived episodes, by id or by primary agent and time.

    Refused (403) while no crew-scope token is configured, before anything is read: ``require_crew_scope``
    passes every caller through when the token is empty, and decoded episodes are never served through an
    open gate (the AD-1196 / AD-731a-1 rule). Every returned episode has one committed ``archive_access`` row.
    """
    if not crew_scope_token(runtime):  # AD-1340 S2a: never serve archived episodes through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_LOOKUP_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="episodic_memory_unavailable")
    try:
        if request.episode_id:
            result = await memory.lookup_archived_by_id(request.episode_id, accessor=_ARCHIVE_LOOKUP_ACCESSOR)
        else:
            result = await memory.lookup_archived_by_agent(
                request.agent_id, since=request.since, until=request.until, limit=request.limit,
                accessor=_ARCHIVE_LOOKUP_ACCESSOR,
            )
    except EpisodeArchiveUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EpisodeArchiveError as exc:
        code = _archive_error_code(exc, "episode_archive_lookup_failed")  # AD-1340 S2b A2: the lookup logs a code too
        logger.error("AD-1340 S2a: archive lookup failed: %s (%s)", code, type(exc.__cause__ or exc).__name__)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    kind = "episode_id" if request.episode_id else "agent"
    logger.info(
        "AD-1340 S2a: archive lookup by %s returned %d (undecodable %d, withdrawn %d, truncated %s)",
        kind, len(result.episodes), result.undecodable, result.withdrawn, result.truncated,
    )
    body: dict[str, Any] = {
        "lookup": kind,
        "episodes": [_archived_episode_body(item) for item in result.episodes],
        "count": len(result.episodes),
        "truncated": result.truncated,
        "undecodable": result.undecodable,
        "withdrawn": result.withdrawn,
    }
    if request.agent_id:
        body["agent_match"] = "primary_agent_only"
    return body


_ARCHIVE_RESTORE_ACCESSOR = "captain:/api/security/archive/restore"
_ARCHIVE_RESTORE_TOKEN_REQUIRED = "episode_archive_restore_requires_token"
# AD-1340 S2b A2: the shape of an archive error code ("name" or "name:qualifier"); anything else is free text.
_ARCHIVE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}(?::[a-z0-9_]{1,32})?")


def _archive_error_code(exc: BaseException, fallback: str) -> str:
    """AD-1340 S2b A2: the exception's text when the whole of it is an error code, else ``fallback``.

    A 500 detail and its log line carry a code, never free text: an exception text can quote a stored value
    (A1.9 F1). Every archive raise site passes a constant code today; this keeps a future one honest.
    """
    text = str(exc)
    return text if _ARCHIVE_ERROR_CODE.fullmatch(text) else fallback


class ArchiveRestoreRequest(BaseModel):
    """AD-1340 S2b: the id of one archived episode to put back in the live store."""

    model_config = {"extra": "forbid"}

    episode_id: str = Field(min_length=1, max_length=256)


@router.post(
    "/archive/restore",
    dependencies=[Depends(require_crew_scope), Depends(_refuse_non_finite_numbers)],  # AD-1340 S2b: D8, then A2
)
async def restore_archived_episode(
    request: ArchiveRestoreRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1340 S2b: the Captain's restore of one archived episode into the live store.

    Refused (403) while no crew-scope token is configured, before anything is read (S2a D8). All or nothing
    (``EpisodicMemory.restore_from_archive``): a 200 means the episode is live with every wired index row, in the
    version the lookup route shows. One ``archive_access`` row names this route. A restored episode decays under
    the ordinary rules, so an unrecalled one returns to the archive at a later Step 12. A 500
    ``episode_archive_restore_unconfirmed`` may have made the episode live: a retry then answers 409
    ``episode_archive_restore_live_id``. AD-1340 S2b A2/A3: an error is logged as the ``repr`` of the id's first 8
    characters, the error code and an exception type name, never an exception's text or its cause's.
    """
    if not crew_scope_token(runtime):  # AD-1340 S2b: never restore through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_RESTORE_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="episodic_memory_unavailable")
    try:
        episode = await memory.restore_from_archive(request.episode_id, accessor=_ARCHIVE_RESTORE_ACCESSOR)
    except EpisodeArchiveUnavailable as exc:  # AD-1340 S2b: an archive or memory that is absent, failed or stopped
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EpisodeArchiveNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EpisodeArchiveConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EpisodeArchiveError as exc:
        code = _archive_error_code(exc, "episode_archive_restore_failed")  # AD-1340 S2b A2: a code, never the text
        # AD-1340 S2b A3: %r escapes a line break or ESC in caller text; the 8-character cut is a bound, not a sanitiser.
        logger.error("AD-1340 S2b: archive restore of %r failed: %s (%s)", request.episode_id[:8], code, type(exc.__cause__ or exc).__name__)
        raise HTTPException(status_code=500, detail=code) from exc
    except Exception as exc:
        logger.error("AD-1340 S2b: archive restore of %r failed unexpectedly: episode_archive_restore_failed (%s)", request.episode_id[:8], type(exc).__name__)
        raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc
    logger.info("AD-1340 S2b: archive restore of %r completed", episode.id)
    return {"episode_id": episode.id, "restored": True}
