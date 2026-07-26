"""ProbOS API — Ship's Records routes (AD-434)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from probos.knowledge.provo import project_record_frontmatter
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/records", tags=["records"])

# AD-1145 DD-7: the only accepted value of the opt-in ``format`` parameter.
_PROV_JSONLD_FORMAT = "prov-jsonld"


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
async def read_record(
    path: str,
    reader: str = "captain",
    format: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Read a specific document from Ship's Records.

    AD-1145 DD-7: ``?format=prov-jsonld`` opts in to a read-only W3C PROV-O
    projection of the document's provenance frontmatter. The parameter is
    default-OFF -- absent it, the response body is byte-identical to what this
    endpoint has always returned, and the projection is never invoked.
    """
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    if format and format != _PROV_JSONLD_FORMAT:
        return JSONResponse(
            {"error": f"Unsupported format; expected '{_PROV_JSONLD_FORMAT}'"},
            status_code=400,
        )
    try:
        entry = await runtime._records_store.read_entry(path, reader_id=reader)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if entry is None:
        return JSONResponse({"error": "Not found or access denied"}, status_code=404)
    if format == _PROV_JSONLD_FORMAT:
        return project_record_frontmatter(
            entry.get("path") or path, entry.get("frontmatter") or {}
        )
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


# AD-562: Knowledge Browser endpoints (Phases 1-4 OSS)


@router.get("/browse")
async def browse_records(
    author: str = "",
    department: str = "",
    classification: str = "",
    directory: str = "",
    tags: str = "",
    since: str = "",
    until: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 1: unified entry list across all Ship's Records sub-directories."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
    try:
        entries = await runtime._records_store.list_entries(
            directory=directory,
            author=author,
            classification=classification,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        logger.warning("AD-562: browse list_entries failed; returning empty", exc_info=True)
        entries = []
    filtered = []
    for e in entries:
        fm = e.get("frontmatter") or {}
        if department and (fm.get("department") or "").lower() != department.lower():
            continue
        if tag_list:
            entry_tags = {str(t).lower() for t in (fm.get("tags") or [])}
            if not set(tag_list).issubset(entry_tags):
                continue
        created = fm.get("created", "")
        if since and isinstance(created, str) and created and created[:10] < since:
            continue
        if until and isinstance(created, str) and created and created[:10] > until:
            continue
        filtered.append(e)
    return {
        "documents": filtered,
        "count": len(filtered),
        "filters_applied": {
            "author": author, "department": department, "classification": classification,
            "directory": directory, "tags": tag_list, "since": since, "until": until,
        },
    }


@router.get("/backlinks/{path:path}")
async def get_backlinks(
    path: str,
    include_suggested: bool = True,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 2: backlinks for a single entry."""
    service = getattr(runtime, "knowledge_browser", None)
    if service is None:
        return JSONResponse({"error": "Knowledge Browser not available"}, status_code=503)
    try:
        result = await service.get_backlinks(path, include_suggested=include_suggested)
    except Exception:
        logger.warning("AD-562: get_backlinks failed for %s", path, exc_info=True)
        return JSONResponse({"error": "backlink lookup failed"}, status_code=500)
    if result is None:
        return JSONResponse({"error": "Not found in index"}, status_code=404)
    return result


@router.get("/graph")
async def get_records_graph(
    max_nodes: int = 500,
    max_edges: int = 1000,
    include_suggested: bool = False,
    include_quality: bool = False,
    department: str = "",
    classification: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 3+4: 3D force-directed knowledge graph payload."""
    service = getattr(runtime, "knowledge_browser", None)
    if service is None:
        return JSONResponse({"error": "Knowledge Browser not available"}, status_code=503)
    capped_nodes = max(0, min(max_nodes, 2000))
    capped_edges = max(0, min(max_edges, 5000))
    try:
        return await service.get_graph(
            max_nodes=capped_nodes,
            max_edges=capped_edges,
            include_suggested=include_suggested,
            include_quality=include_quality,
            department_filter=department,
            classification_filter=classification,
        )
    except Exception:
        logger.warning("AD-562: get_graph failed", exc_info=True)
        return JSONResponse({"error": "graph assembly failed"}, status_code=500)


@router.get("/timeline")
async def get_records_timeline(
    bucket: str = "day",
    since: str = "",
    until: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 1: entry-creation timeline (day-buckets, dept-stacked)."""
    service = getattr(runtime, "knowledge_browser", None)
    if service is None:
        return JSONResponse({"error": "Knowledge Browser not available"}, status_code=503)
    try:
        return await service.get_timeline(bucket=bucket, since=since, until=until)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        logger.warning("AD-562: get_timeline failed", exc_info=True)
        return JSONResponse({"error": "timeline assembly failed"}, status_code=500)
