"""ProbOS API — Ship's Records routes (AD-434)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/records", tags=["records"])


@router.get("/stats")
async def get_records_stats(runtime: Any = Depends(get_runtime)) -> Any:
    """Get Ship's Records repository statistics."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    return await runtime._records_store.get_stats()


@router.get("/documents")
async def list_records(
    directory: str = "",
    author: str = "",
    status: str = "",
    classification: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """List documents in Ship's Records."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    try:
        entries = await runtime._records_store.list_entries(
            directory=directory, author=author, status=status, classification=classification,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"documents": entries, "count": len(entries)}


@router.get("/documents/{path:path}")
async def read_record(path: str, reader: str = "captain", runtime: Any = Depends(get_runtime)) -> Any:
    """Read a specific document from Ship's Records."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    try:
        entry = await runtime._records_store.read_entry(path, reader_id=reader)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if entry is None:
        return JSONResponse({"error": "Not found or access denied"}, status_code=404)
    return entry


@router.post("/captains-log")
async def post_captains_log(request: Request, runtime: Any = Depends(get_runtime)) -> Any:
    """Append a Captain's Log entry."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    body = await request.json()
    content = body.get("content", "")
    if not content:
        return JSONResponse({"error": "content required"}, status_code=400)
    path = await runtime._records_store.append_captains_log(content, body.get("message", ""))
    return {"path": path, "status": "appended"}


@router.get("/captains-log")
async def get_captains_log(limit: int = 7, runtime: Any = Depends(get_runtime)) -> Any:
    """Get recent Captain's Log entries."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    entries = await runtime._records_store.list_entries("captains-log")
    entries.sort(key=lambda e: e.get("frontmatter", {}).get("created", ""), reverse=True)
    return {"entries": entries[:limit]}


@router.get("/notebooks/{callsign}")
async def list_notebook(callsign: str, runtime: Any = Depends(get_runtime)) -> Any:
    """List a crew member's notebook entries."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    try:
        entries = await runtime._records_store.list_entries(f"notebooks/{callsign}")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"callsign": callsign, "entries": entries}


@router.post("/notebooks/{callsign}")
async def write_notebook_entry(callsign: str, request: Request, runtime: Any = Depends(get_runtime)) -> Any:
    """Write to a crew member's notebook."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    body = await request.json()
    topic = body.get("topic", "untitled")
    content = body.get("content", "")
    if not content:
        return JSONResponse({"error": "content required"}, status_code=400)
    try:
        path = await runtime._records_store.write_notebook(
            callsign=callsign,
            topic_slug=topic,
            content=content,
            department=body.get("department", ""),
            tags=body.get("tags", []),
            classification=body.get("classification", "department"),
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"path": path, "status": "written"}


@router.get("/search")
async def search_records(q: str = "", scope: str = "ship", runtime: Any = Depends(get_runtime)) -> Any:
    """Search Ship's Records by keyword."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    if not q:
        return JSONResponse({"error": "query parameter 'q' required"}, status_code=400)
    results = await runtime._records_store.search(q, scope=scope)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/history/{path:path}")
async def get_record_history(path: str, limit: int = 20, runtime: Any = Depends(get_runtime)) -> Any:
    """Get git history for a specific record."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    try:
        history = await runtime._records_store.get_history(path, limit=limit)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"path": path, "history": history}
