"""AD-754 security endpoints."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from probos.cognitive.episode_archive import (
    LOOKUP_DEFAULT_LIMIT,
    LOOKUP_MAX_LIMIT,
    ArchivedEpisode,
    EpisodeArchiveError,
    EpisodeArchiveUnavailable,
)
from probos.knowledge.erasure import ErasureManager
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


@router.post("/forget")
async def request_erasure(
    request: ForgetRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """User-directed erasure for episode, resource, or agent memory."""
    manager = ErasureManager(
        episodic_memory=getattr(runtime, "episodic_memory", None),
        attachment_store=getattr(runtime, "attachment_store", None),
        audit_log=_get_audit_log(runtime),
    )

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

    return {
        "deleted_count": result.count,
        "timestamps": result.timestamps,
        "deleted_episode_ids": result.deleted_episode_ids,
        "deleted_attachment_ids": result.deleted_attachment_ids,
    }


_ARCHIVE_LOOKUP_ACCESSOR = "captain:/api/security/archive/lookup"
_ARCHIVE_LOOKUP_TOKEN_REQUIRED = "episode_archive_lookup_requires_token"
_NON_FINITE_NUMBER_IN_BODY = "non_finite_number_in_body"


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


async def _refuse_non_finite_numbers(request: Request) -> None:
    """AD-1340 S2a: 422 for a body holding a non-finite number, before validation runs.

    The framework's 422 handler echoes the offending input, cannot JSON-encode NaN or Infinity, and answers 500
    (follow-up on #1523). Re-reads the body the framework already cached; reads no runtime state, writes nothing.
    """
    try:
        json.loads(await request.body(), parse_constant=_refuse_constant, parse_float=_finite_float)
    except _NonFiniteNumberInBody as exc:
        raise HTTPException(status_code=422, detail=_NON_FINITE_NUMBER_IN_BODY) from exc
    except ValueError:
        return  # AD-1340 S2a: malformed JSON is the framework's to refuse (it parses first)


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
    if not runtime.config.auth.crew_scope_token:  # AD-1340 S2a: never serve archived episodes through an open gate
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
        logger.error("AD-1340 S2a: archive lookup failed: %s", exc, exc_info=True)
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
