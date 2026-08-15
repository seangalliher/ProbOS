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

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from probos.cognitive.trace_analysis import analyse_trace, load_trace
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
async def get_trace(ref: str, runtime: Any = Depends(get_runtime)) -> dict:
    """The full decoded trace for one run: every call, its arguments, and
    whether it errored -- plus the AD-1171 summary over it.

    This is the answer to "what did the agent actually do?", which its own
    account of the run is only a hypothesis about.
    """
    store = _store(runtime)
    clean = _clean_ref(ref)
    entries = await load_trace(store, clean)
    if entries is None:
        raise HTTPException(status_code=404, detail="Trace not found or unreadable")
    return {
        "ref": clean,
        "calls": entries,
        "summary": _summary_dict(entries),
    }
