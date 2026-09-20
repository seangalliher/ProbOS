"""AD-1207: authenticated, read-only fault observations for the Bridge."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from probos.cognitive.trace_analysis import analyse_trace, load_trace
from probos.diagnostic_safety import SanitisedTraceReader, sanitise_diagnostic_value
from probos.fault_issue_filings import IssueFiling, IssueReceipt, valid_issue_receipt, valid_occurrence_count
from probos.fault_report import FaultReport, FaultStatus
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/faults", tags=["faults"], dependencies=[Depends(require_crew_scope)],
)

FaultID = Annotated[str, Field(pattern=r"^[0-9a-f]{12}$")]
Signature = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
OccurrenceCount = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$")]


class FaultIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str
    number: int = Field(gt=0)
    url: str


class FaultSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: FaultID
    signature: Signature
    tool_id: str = Field(max_length=128)
    summary: str = Field(max_length=160)
    status: FaultStatus
    occurrences: OccurrenceCount
    first_seen_at: float = Field(allow_inf_nan=False)
    last_seen_at: float = Field(allow_inf_nan=False)
    issue: FaultIssue | None
    issue_lookup_available: bool


class FaultList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    faults: list[FaultSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class FaultDetail(FaultSummary):
    error_text: str = Field(max_length=2000)
    attempted: str = Field(max_length=1000)
    recorded_agent_id: str = Field(max_length=128)
    thread_id: str = Field(max_length=128)
    work_item_id: str | None = Field(max_length=128)
    observed_as: str = Field(max_length=128)
    trace_summary: str = Field(max_length=4000)
    trace_available: bool
    clipped_fields: list[str]


class FaultDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fault: FaultDetail


class FilingReader(Protocol):
    async def get(self, signature: str) -> IssueFiling | None: ...


class FaultReader(Protocol):
    issue_filings: FilingReader

    def list_open(self) -> list[FaultReport]: ...

    def get(self, signature_or_id: str) -> FaultReport | None: ...


def _warn_trace_unavailable() -> None:
    logger.warning(
        "AD-1207: fault trace could not be read safely; fault detail "
        "will explicitly identify unavailable trace evidence"
    )


def _unavailable() -> HTTPException:
    logger.warning(
        "AD-1207: fault observations could not be read; current fault state is "
        "unknown and the read returns unavailable rather than empty"
    )
    return HTTPException(503, "fault_store_unavailable", headers={"Cache-Control": "no-store"})


def _store(runtime: Any) -> FaultReader:
    store = getattr(runtime, "fault_report_store", None)
    if store is None:
        raise _unavailable()
    return store


def _clip(value: str, limit: int, field: str, clipped: list[str]) -> str:
    if len(value) > limit:
        clipped.append(field)
    return value[:limit]


def _presentation(fault: FaultReport) -> tuple[dict[str, Any], list[str]]:
    # Sanitise the detached values before whitespace folding or any length limit.
    safe = sanitise_diagnostic_value(fault.to_dict())
    clipped: list[str] = []
    summary = " ".join(safe["error_text"].split()) or "Tool failure with no recorded error text."
    fields = {
        "summary": _clip(summary, 160, "summary", clipped),
        "tool_id": _clip(safe["tool_id"], 128, "tool_id", clipped),
    }
    for source, target, limit in (
        ("error_text", "error_text", 2000),
        ("attempted", "attempted", 1000),
        ("agent_id", "recorded_agent_id", 128),
        ("thread_id", "thread_id", 128),
        ("work_item_id", "work_item_id", 128),
        ("observed_as", "observed_as", 128),
    ):
        value = safe[source]
        fields[target] = None if value is None else _clip(value, limit, target, clipped)
    return fields, clipped


async def _issue(fault: FaultReport, store: FaultReader) -> tuple[FaultIssue | None, bool]:
    try:
        filing = await store.issue_filings.get(fault.signature)
        if (
            filing is not None and filing.signature == fault.signature
            and filing.disposition == "filed" and filing.issue_number is not None
        ):
            receipt = IssueReceipt(filing.issue_number, filing.issue_url)
            if valid_issue_receipt(filing.repository, receipt):
                return FaultIssue(
                    repository=filing.repository, number=receipt.number, url=receipt.url,
                ), True
        return None, True
    except Exception:
        logger.warning(
            "AD-1207: issue receipt lookup failed; the fault remains visible "
            "with linkage unknown until a later read succeeds"
        )
        return None, False


async def _summary(
    fault: FaultReport, store: FaultReader, fields: dict[str, Any],
) -> FaultSummary:
    if not valid_occurrence_count(fault.occurrences):
        raise ValueError("invalid_occurrence_count")
    issue, available = await _issue(fault, store)
    return FaultSummary(
        id=fault.id, signature=fault.signature, tool_id=fields["tool_id"],
        summary=fields["summary"], status=fault.status, occurrences=str(fault.occurrences),
        first_seen_at=fault.first_seen_at, last_seen_at=fault.last_seen_at,
        issue=issue, issue_lookup_available=available,
    )


@router.get("", response_model=FaultList)
async def list_faults(
    response: Response,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    runtime: Any = Depends(get_runtime),
) -> FaultList:
    store = _store(runtime)
    try:
        # Store rows are mutable. Detach the ENTIRE snapshot before the first await.
        snapshot = [replace(fault) for fault in store.list_open()]
        summaries = []
        for fault in snapshot[offset:offset + limit]:
            fields, _ = _presentation(fault)
            summaries.append(await _summary(fault, store, fields))
        result = FaultList(faults=summaries, total=len(snapshot), limit=limit, offset=offset)
    except Exception:
        raise _unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/{fault_id}", response_model=FaultDetailResponse)
async def get_fault(
    response: Response,
    fault_id: str = Path(pattern=r"^[0-9a-f]{12}$"),
    runtime: Any = Depends(get_runtime),
) -> FaultDetailResponse:
    store = _store(runtime)
    try:
        stored = store.get(fault_id)
        fault = replace(stored) if stored is not None else None
    except Exception:
        raise _unavailable() from None
    if fault is None:
        raise HTTPException(404, "fault_not_found", headers={"Cache-Control": "no-store"})
    try:
        fields, clipped = _presentation(fault)
        summary = await _summary(fault, store, fields)
        entries = await load_trace(
            SanitisedTraceReader(
                getattr(runtime, "attachment_store", None),
                warn_unavailable=_warn_trace_unavailable,
            ),
            fault.tool_trace_ref or "",
        )
        trace = (
            analyse_trace(entries).render() if entries
            else "Stored trace sample unavailable: no readable recorded tool calls."
        )
        detail = FaultDetail(
            **summary.model_dump(),
            **{key: value for key, value in fields.items() if key not in ("summary", "tool_id")},
            trace_summary=_clip(trace, 4000, "trace_summary", clipped),
            trace_available=bool(entries), clipped_fields=clipped,
        )
    except Exception:
        raise _unavailable() from None
    response.headers["Cache-Control"] = "no-store"
    return FaultDetailResponse(fault=detail)
