"""AD-1203: read the flight recorder from outside the process.

Every agentic run persists a complete tool trace to the AttachmentStore under
``origin="crew_trace"`` (AD-1151), and ``trace_analysis`` (AD-1171) can already
summarise one. What was missing was a way to *find* and *read* one without
walking the attachment index by hand.

AD-1203 was filed after an agent produced a report quoting five project
homepages and five separate surfaces all came back empty, so there was no way
to tell whether it had fetched anything at all. The premise has since shifted:
the record does exist and is durable. Only the surface was missing, and the
absence cost real time -- on 2026-08-09, answering "did the agent read the
artifact back or just repeat the conversation?" meant sorting the raw
attachment index by ``written_at`` and decoding blobs by hand. The trace gave
the answer in one line; getting to the trace was the expensive part.

**Scope, stated honestly.** These routes key on *agent and time*, not on a
specific turn. Traces are sparse enough that this is sufficient in practice --
it is how the 2026-08-09 investigation was actually resolved -- but it is not
the per-turn link AD-1203 asks for. That link needs the ref to travel from
``AgenticResult.tool_trace_ref`` (already populated) out to the caller, and
``IntentResult`` has no field to carry it. Adding one is a core-type change
across the mesh and is deliberately not attempted here; the crew path already
records the ref (``fault_report.tool_trace_ref``), the 1:1 DM path drops it.

Strictly read-only: these routes decode and summarise what is already stored
and mutate nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from probos.cognitive.trace_analysis import (
    analyse_trace,
    load_trace,
    sanitise_for_transport,
)
from probos.cognitive.trace_evidence import build_consulted_receipt
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/traces", tags=["traces"])

# A trace ref is a SHA-256 content hash. Bounded so a hostile path segment
# cannot reach the store as an unbounded key.
_REF_MIN = 8
_REF_MAX = 64

# Listing decodes and summarises each trace, so the page size is a decision:
# 20 covers "what has this agent been doing" without turning one request into
# an unbounded number of blob reads.
_LIST_LIMIT_DEFAULT = 20
_LIST_LIMIT_MAX = 100
# BF-774 review: an index row's requests list is multiplied by the page size.
# At the full 40 per row and limit=100 a measured response reached ~5 MB, so
# index rows carry only what a summary would render.
_LIST_REQUESTS_MAX = 6


class _TraceReader(Protocol):
    async def read(self, content_hash: str) -> bytes | bytearray | str | None: ...


class _ConsultedTraceReader:
    """Keep the legacy loader's exception diagnostics off this safe surface."""

    def __init__(self, reader: _TraceReader) -> None:
        self._reader = reader

    async def read(self, content_hash: str) -> bytes | bytearray | str | None:
        try:
            blob = await self._reader.read(content_hash)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-1243: consulted trace storage read failed; the receipt is "
                "unavailable and this request returns a safe unreadable response",
            )
            return None
        if blob is None:
            return None
        try:
            if type(blob) not in (bytes, bytearray, str):
                raise ValueError("trace_bytes_invalid")
            # Preserve bytes, not a parse/reserialize approximation. Checking
            # them here prevents load_trace's legacy exc_info logging without
            # changing that loader's behavior for the verifier or raw routes.
            json.loads(blob.decode("utf-8") if isinstance(blob, (bytes, bytearray)) else blob)
        except Exception:
            logger.warning(
                "AD-1243: stored consulted trace is unreadable; no evidence can "
                "be projected and this request returns a safe unreadable response",
            )
            return None
        return blob


def _store(runtime: Any):
    store = getattr(runtime, "attachment_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Attachment store not available")
    return store


def _clean_ref(ref: str) -> str:
    ref = str(ref or "").strip().lower()
    if not (_REF_MIN <= len(ref) <= _REF_MAX) or any(
        ch not in "0123456789abcdef" for ch in ref
    ):
        raise HTTPException(status_code=400, detail="Invalid trace reference")
    return ref


def _summary_dict(entries: list[Any], *, max_requests: int | None = None) -> dict:
    summary = analyse_trace(entries)
    requests = list(summary.requests)
    if max_requests is not None:
        requests = requests[:max_requests]
    return {
        "total_calls": summary.total_calls,
        "failed_calls": summary.failed_calls,
        "tools_used": list(summary.tools_used),
        # BF-774: what each call asked, not just which tools ran. A run that
        # succeeded against the wrong target has nothing in the failure fields.
        # ``requests`` is capped, so ``requests_total`` travels with it -- a
        # client that renders the list needs to know it is not the whole list.
        "requests": requests,
        "requests_total": summary.requests_total,
        "repeated_failures": [asdict(f) for f in summary.repeated_failures],
        "last_success_index": summary.last_success_index,
        "trailing_failure_count": summary.trailing_failure_count,
        "stalled": summary.stalled,
        "render": summary.render(),
    }


@router.get("")
async def list_traces(
    limit: int = Query(_LIST_LIMIT_DEFAULT, ge=1, le=_LIST_LIMIT_MAX),
    runtime: Any = Depends(get_runtime),
) -> dict:
    """Newest-first index of persisted tool traces, with a summary of each.

    ``list_by_origin`` returns ``[(content_hash, written_at)]`` ascending, so
    the tail is the newest and is reversed here.
    """
    store = _store(runtime)
    try:
        entries = await store.list_by_origin("crew_trace")
    except Exception:
        logger.warning(
            "AD-1203: could not enumerate crew_trace attachments; returning an "
            "empty index rather than failing the request", exc_info=True,
        )
        return {"traces": [], "total": 0}

    ordered = list(reversed(entries or []))[:limit]
    out: list[dict] = []
    for content_hash, written_at in ordered:
        record: dict[str, Any] = {
            "ref": content_hash,
            "written_at": float(written_at or 0.0),
        }
        decoded = await load_trace(store, content_hash)
        if decoded is None:
            # The index knows about it and the bytes are gone or unreadable.
            # Say so rather than omitting the row: a trace that cannot be read
            # is itself a finding.
            record["readable"] = False
        else:
            record["readable"] = True
            # An index row is multiplied by the page size, so it carries only
            # the requests the render would show. ``requests_total`` still
            # reports the true count, and /{ref} serves the summary's full
            # bounded list (up to _REQUESTS_MAX) plus the raw calls.
            record["summary"] = _summary_dict(decoded, max_requests=_LIST_REQUESTS_MAX)
        out.append(record)
    return {"traces": out, "total": len(entries or [])}


@router.get("/{ref}")
async def get_trace(ref: str, runtime: Any = Depends(get_runtime)) -> JSONResponse:
    """The full decoded trace for one run: every call, its arguments, and
    whether it errored -- plus the AD-1171 summary over it.

    This is the answer to "what did the agent actually do?", which its own
    account of the run is only a hypothesis about.

    BF-775: returns ``JSONResponse`` explicitly rather than an annotated
    ``dict``. FastAPI's serializer for the latter raises "Circular reference
    detected (depth exceeded)" from about 96 levels down, and the only
    production writer accepts nested ``ToolCallRequest.arguments`` -- 496
    levels were observed persisting fine. Since ``sanitise_for_transport`` has
    already made the payload JSON-safe, that intermediate pass adds a failure
    mode without adding a guarantee.
    """
    store = _store(runtime)
    clean = _clean_ref(ref)
    entries = await load_trace(store, clean)
    if entries is None:
        raise HTTPException(status_code=404, detail="Trace not found or unreadable")
    # `calls` is documented as verbatim, so when the echo is altered the
    # response says so rather than quietly differing.
    safe_entries, sanitised = sanitise_for_transport(entries)
    payload: dict[str, Any] = {
        "ref": clean,
        "calls": safe_entries,
        "summary": _summary_dict(entries),
    }
    if sanitised:
        logger.warning(
            "BF-775: trace %s carries values that cannot be rendered as JSON; "
            "`calls` was normalised for transport and is not byte-exact",
            clean[:12],
        )
        payload["calls_sanitised"] = True
    return JSONResponse(content=payload)


@router.get("/{ref}/consulted")
async def get_consulted(
    ref: str,
    request: Request,
    authorization: str | None = Header(default=None),
    runtime: Any = Depends(get_runtime),
) -> JSONResponse:
    """AD-1243: a bounded, redacted "what was consulted" projection.

    A second, unrelated consumer of a stored trace needs to show that
    something was consulted without ever receiving raw tool arguments,
    outputs, or error bodies -- the ``/{ref}`` route above is explicitly a
    verbatim echo and is not safe for that purpose. This route runs the
    stored trace back through the AD-1242 sanitisation policy (now shared via
    :mod:`probos.cognitive.trace_evidence`) and bounds the whole response to
    16 KiB.

    Auth is checked before any storage access -- a request that fails the
    (default-off) crew-scope check learns nothing about whether the store is
    configured or the ref exists. Every response, success or error, carries
    ``Cache-Control: no-store``: this is evidence about what an agent did,
    not something a shared cache should ever retain.
    """
    no_store = {"Cache-Control": "no-store"}
    try:
        try:
            await require_crew_scope(request, authorization, runtime)
        except HTTPException as exc:
            if exc.status_code not in (401, 403):
                raise
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": "Crew authorization required"},
                headers=no_store,
            )
        try:
            clean = _clean_ref(ref)
        except HTTPException:
            return JSONResponse(
                status_code=400, content={"detail": "Invalid trace reference"},
                headers=no_store,
            )
        try:
            store = _store(runtime)
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            return JSONResponse(
                status_code=503, content={"detail": "Attachment store not available"},
                headers=no_store,
            )
        entries = await load_trace(_ConsultedTraceReader(store), clean)
        if entries is None:
            return JSONResponse(
                status_code=404, content={"detail": "Trace not found or unreadable"},
                headers=no_store,
            )
        payload = build_consulted_receipt(entries, clean)
        return JSONResponse(status_code=200, content=payload, headers=no_store)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "AD-1243: consulted-evidence projection failed for a trace ref; "
            "returning a sanitised 500 rather than leaking exception detail",
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Could not build consulted evidence"},
            headers=no_store,
        )
