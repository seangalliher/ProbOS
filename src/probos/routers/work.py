"""Semantic work layer API endpoints (AD-750).

Provides CRUD-style access to tasks, commitments, and full-text search
over the SemanticStore. Graceful 503 degradation when the store is not
initialised.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, TypedDict

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/work", tags=["work"])


def _503() -> JSONResponse:
    return JSONResponse(
        {"error": "Semantic work layer not available"},
        status_code=503,
    )


def _get_store(runtime: Any) -> Any:
    return getattr(runtime, "_semantic_store", None)


# ------------------------------------------------------------------
# Task endpoints
# ------------------------------------------------------------------


@router.get("/tasks")
async def list_tasks(
    completed: bool = False,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Return tasks owned by the Captain, filtered by completion status."""
    store = _get_store(runtime)
    if store is None:
        return _503()
    tasks = await store.query_tasks(completed=completed)
    return [dataclasses.asdict(t) for t in tasks]


# ------------------------------------------------------------------
# Commitment endpoints
# ------------------------------------------------------------------


@router.get("/commitments")
async def list_commitments(
    status: str = "open",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Return crew commitments filtered by status."""
    store = _get_store(runtime)
    if store is None:
        return _503()
    commitments = await store.query_commitments(status=status)
    return [dataclasses.asdict(c) for c in commitments]


# ------------------------------------------------------------------
# Search endpoint
# ------------------------------------------------------------------


@router.get("/search")
async def search_work(
    query: str,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Full-text search across all work entities."""
    store = _get_store(runtime)
    if store is None:
        return _503()
    if not query.strip():
        return []
    results = await store.search(query)
    return [dataclasses.asdict(e) for e in results]


# ------------------------------------------------------------------
# Link endpoint
# ------------------------------------------------------------------


class LinkRequest(BaseModel):
    source_id: str
    target_ids: list[str]
    link_type: str


@router.post("/link")
async def link_entities_route(
    body: LinkRequest,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Create cross-references between work entities."""
    store = _get_store(runtime)
    if store is None:
        return _503()
    if not body.source_id or not body.target_ids:
        return JSONResponse(
            {"error": "source_id and at least one target_id are required"},
            status_code=422,
        )
    await store.link_entities(
        source_id=body.source_id,
        target_ids=body.target_ids,
        link_type=body.link_type or "related",
    )
    return {"linked": len(body.target_ids), "source_id": body.source_id}


# ------------------------------------------------------------------
# AD-756 endpoints
# ------------------------------------------------------------------


class SuggestedAction(TypedDict):
    id: str
    label: str
    emoji: str
    agent: str
    score: float
    metadata: dict[str, str]


@router.get("/suggested-actions")
async def get_suggested_actions(runtime: Any = Depends(get_runtime)) -> list[SuggestedAction]:
    """Return bounded suggested actions for the Captain's next steps."""
    # Placeholder: in future this is ranked via Hebbian/attention context.
    # OSS scope: return actions within local policy/capability boundaries.
    _ = runtime
    return [
        {
            "id": "1",
            "label": "Review meeting notes",
            "emoji": "review",
            "agent": "ArchitectAgent",
            "score": 0.92,
            "metadata": {"intent": "review_notes", "context": "meeting"},
        },
        {
            "id": "2",
            "label": "Approve PR",
            "emoji": "approve",
            "agent": "SkillAgent",
            "score": 0.85,
            "metadata": {"intent": "approve_pr", "context": "repo"},
        },
    ]


class DailyBriefing(TypedDict):
    inboxSummary: str
    calendarSummary: str
    suggestedActions: list[str]


@router.get("/daily-briefing")
async def get_daily_briefing(runtime: Any = Depends(get_runtime)) -> DailyBriefing:
    """Return start-of-day briefing summary for the Captain."""
    _ = runtime
    return {
        "inboxSummary": "Overnight inbox: 12 new emails (3 flagged)",
        "calendarSummary": "Calendar: 5 meetings today, 2 free slots",
        "suggestedActions": ["Review meeting notes", "Approve PR"],
    }
