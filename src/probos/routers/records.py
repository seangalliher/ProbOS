"""ProbOS API — Ship's Records routes (AD-434)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from probos.knowledge.provo import project_record_frontmatter
from probos.routers.deps import get_runtime
from probos.routers.readiness import failed_read, unavailable_dependency

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/records", tags=["records"])

# AD-1145 DD-7: the only accepted value of the opt-in ``format`` parameter.
_PROV_JSONLD_FORMAT = "prov-jsonld"


def _read_failure(message: str, code: str, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        {"error": message, "availability": failed_read(message, code, status_code)},
        status_code=status_code,
    )


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

    Read failures retain ``error`` and add ``availability`` with state, code,
    controlled message and retryable. Missing documents remain HTTP 404;
    absent storage is HTTP 503, with disabled reserved for typed config-off.
    """
    store = getattr(runtime, "records_store", None)
    if store is None:
        return JSONResponse({
            "error": "Ship's Records not available",
            "availability": unavailable_dependency(getattr(runtime, "config", None), "records"),
        }, status_code=503)
    if format and format != _PROV_JSONLD_FORMAT:
        return _read_failure(
            f"Unsupported format; expected '{_PROV_JSONLD_FORMAT}'",
            "records.invalid_format", 400,
        )
    try:
        entry = await store.read_entry(path, reader_id=reader)
    except HTTPException:
        raise
    except ValueError:
        return _read_failure("Invalid document parameters", "records.invalid_parameters", 400)
    except Exception:
        logger.warning("Records document read failed; document unavailable; returning HTTP 503")
        return _read_failure("Record document unavailable", "records.read_failed", 503)
    if entry is None:
        return _read_failure("Not found or access denied", "records.not_found", 404)
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
            # AD-1157a: absent means no preference — default on create, keep
            # the existing classification on update.
            classification=body.get("classification"),
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
    store = getattr(runtime, "records_store", None)
    if store is None:
        return JSONResponse({
            "error": "Ship's Records not available",
            "availability": unavailable_dependency(getattr(runtime, "config", None), "records"),
        }, status_code=503)
    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
    try:
        entries = await store.list_entries(
            directory=directory,
            author=author,
            classification=classification,
        )
    except ValueError:
        return _read_failure("Invalid records browse parameters", "records.invalid_parameters", 400)
    except Exception:
        logger.warning("Records browse storage read failed; results unavailable; returning HTTP 503")
        return _read_failure("Records browse unavailable", "records.read_failed", 503)
    if entries is None:
        logger.warning("Records browse storage returned no result; results unavailable; returning HTTP 503")
        return _read_failure("Records browse unavailable", "records.read_failed", 503)
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
        return JSONResponse({
            "error": "Knowledge Browser not available",
            "availability": unavailable_dependency(getattr(runtime, "config", None), "knowledge_browser"),
        }, status_code=503)
    try:
        result = await service.get_backlinks(path, include_suggested=include_suggested)
    except Exception:
        logger.warning("Knowledge Browser backlink lookup failed; results unavailable; returning HTTP 500")
        return _read_failure("backlink lookup failed", "knowledge_browser.backlinks_failed")
    if result is None:
        return _read_failure("Not found in index", "knowledge_browser.not_found", 404)
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
        return JSONResponse({
            "error": "Knowledge Browser not available",
            "availability": unavailable_dependency(getattr(runtime, "config", None), "knowledge_browser"),
        }, status_code=503)
    capped_nodes = max(0, min(max_nodes, 2000))
    capped_edges = max(0, min(max_edges, 5000))
    try:
        result = await service.get_graph(
            max_nodes=capped_nodes,
            max_edges=capped_edges,
            include_suggested=include_suggested,
            include_quality=include_quality,
            department_filter=department,
            classification_filter=classification,
        )
    except Exception:
        logger.warning("Knowledge Browser graph assembly failed; results unavailable; returning HTTP 500")
        return _read_failure("graph assembly failed", "knowledge_browser.graph_failed")
    if result is None:
        return _read_failure("graph assembly failed", "knowledge_browser.graph_failed")
    return result


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
        return JSONResponse({
            "error": "Knowledge Browser not available",
            "availability": unavailable_dependency(getattr(runtime, "config", None), "knowledge_browser"),
        }, status_code=503)
    try:
        result = await service.get_timeline(bucket=bucket, since=since, until=until)
    except ValueError:
        return _read_failure("Invalid timeline parameters", "knowledge_browser.invalid_parameters", 400)
    except Exception:
        logger.warning("Knowledge Browser timeline assembly failed; results unavailable; returning HTTP 500")
        return _read_failure("timeline assembly failed", "knowledge_browser.timeline_failed")
    if result is None:
        return _read_failure("timeline assembly failed", "knowledge_browser.timeline_failed")
    return result
