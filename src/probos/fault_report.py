"""AD-1169: a fault report — the noun the crew was missing.

ProbOS could already say **"I need a capability I don't have."** That is
``CapabilityGapDriver`` (AD-855), and it works: it files a ``CapabilityRequest``,
blocks the work item, and resumes it on approval.

It could not say **"what I have is broken."**

BF-701 is the demonstration. ``key_type`` was not a missing capability. It
existed, it was advertised in the browser tool's own description, it was listed
in the tool's schema — and it was refused at the gate, because AD-1160 added it
everywhere except the one set inside ``invoke()`` that admits an action. The
agent asked for it at step 2, was told ``unknown browser action: 'key_type'``,
asked again at step 15, and spent the steps in between guessing at CSS
selectors and canvas coordinates before a ``goto`` reloaded the page over its
own work.

``RequestKind`` is ``grant | install | build | action``. None of those means
"broken", so the only verdict available was AD-1164's *"I need more room to
keep trying."* The agent was not lacking agency. It was lacking a noun.

**Deliberately separate from ``CapabilityRequest``.** A capability gap means
"build me something new" and routes to the design pipeline; a fault means
"something existing is not behaving as advertised" and routes to diagnosis.
Conflating them would have sent BF-701 to the Architect as a feature request
for an action that already existed — which is precisely the wrong repair.

**Coalescing is the point.** A tool broken for every caller produces one report
with a rising occurrence count, not a flood of identical rows. The same
mechanism means an agent that retries a refused call five times files one
fault, which is what makes it safe to file without a Captain round-trip.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:
    from probos.storage.sqlite_factory import ConnectionFactory

logger = logging.getLogger(__name__)

FaultStatus = Literal["open", "diagnosing", "repaired", "dismissed"]

# Bounds. A fault report is a diagnostic record, not a log sink: the error text
# is the evidence, and anything past this is noise that would bloat every row.
_TOOL_ID_MAX = 128
_ERROR_MAX = 2000
_ATTEMPTED_MAX = 1000
_AGENT_ID_MAX = 128
_THREAD_ID_MAX = 128
_TRACE_REF_MAX = 128

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fault_reports (
    id TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    error_text TEXT NOT NULL DEFAULT '',
    attempted TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    thread_id TEXT NOT NULL DEFAULT '',
    work_item_id TEXT,
    tool_trace_ref TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    occurrences INTEGER NOT NULL DEFAULT 1,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    resolved_at REAL,
    resolution TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_faults_signature ON fault_reports(signature);
CREATE INDEX IF NOT EXISTS idx_faults_status ON fault_reports(status);
CREATE INDEX IF NOT EXISTS idx_faults_tool ON fault_reports(tool_id);
"""

# Normalisation: what varies between two occurrences of the SAME fault, and
# what identifies it.
#
# ``unknown browser action: 'key_type'`` -- the quoted name IS the signal, so
# quoted content is preserved. ``Page.click: Timeout 30000ms exceeded`` -- the
# duration is noise, so digit runs collapse. A session id or content hash in an
# error is per-run noise, so long hex runs collapse.
#
# Collapsing too aggressively merges distinct faults into one report and hides
# the second; collapsing too little files a fresh report per occurrence and
# defeats coalescing. These three rules were chosen against real error strings
# from the live instance, listed in the tests.
_HEX_RUN_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
_DIGIT_RUN_RE = re.compile(r"\d+")
_WS_RE = re.compile(r"\s+")


def normalise_error(text: Any) -> str:
    """Reduce an error string to what identifies the fault."""
    flat = _WS_RE.sub(" ", str(text or "")).strip().lower()
    flat = _HEX_RUN_RE.sub("<id>", flat)
    flat = _DIGIT_RUN_RE.sub("<n>", flat)
    return flat[:_ERROR_MAX]


def error_signature(*, tool_id: Any, error_text: Any) -> str:
    """Stable identity of a fault: which tool, failing which way.

    Mirrors ``capability_request.action_dedup_key`` — a SHA-256 over a joined
    material string — so the two dedup mechanisms read the same way and neither
    needs its own column.
    """
    material = "|".join([
        str(tool_id or "")[:_TOOL_ID_MAX],
        normalise_error(error_text),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class FaultReport:
    """One tool behaving other than as advertised."""

    id: str = ""
    signature: str = ""
    tool_id: str = ""
    error_text: str = ""
    attempted: str = ""
    agent_id: str = ""
    thread_id: str = ""
    work_item_id: str | None = None
    tool_trace_ref: str | None = None
    status: FaultStatus = "open"
    occurrences: int = 1
    first_seen_at: float = 0.0
    last_seen_at: float = 0.0
    resolved_at: float | None = None
    resolution: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "signature": self.signature,
            "tool_id": self.tool_id,
            "error_text": self.error_text,
            "attempted": self.attempted,
            "agent_id": self.agent_id,
            "thread_id": self.thread_id,
            "work_item_id": self.work_item_id,
            "tool_trace_ref": self.tool_trace_ref,
            "status": self.status,
            "occurrences": self.occurrences,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "resolved_at": self.resolved_at,
            "resolution": self.resolution,
        }


class FaultReportStore:
    """Durable, coalescing store of fault reports.

    Mirrors ``CapabilityRequestStore`` deliberately: same ``ConnectionFactory``
    injection, same ``db_path=""`` cache-only mode, same start/stop lifecycle.
    A reader who knows one knows the other, and the cloud-ready storage seam is
    identical.
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: "ConnectionFactory | None" = None,
        emit_event: Callable[..., Any] | None = None,
    ) -> None:
        self.db_path = db_path
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory
        self._emit_event = emit_event
        self._db: Any = None
        # Signature -> report. The cache is authoritative for reads so a fault
        # filed mid-turn is visible to the next one without a round trip.
        self._cache: dict[str, FaultReport] = {}

    async def start(self) -> None:
        if not self.db_path:
            return
        self._db = await self._connection_factory.connect(self.db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        await self._load_cache()

    async def stop(self) -> None:
        if self._db is not None:
            try:
                await self._db.close()
            finally:
                self._db = None

    async def _load_cache(self) -> None:
        if not self._db:
            return
        async with self._db.execute(
            "SELECT id, signature, tool_id, error_text, attempted, agent_id, "
            "thread_id, work_item_id, tool_trace_ref, status, occurrences, "
            "first_seen_at, last_seen_at, resolved_at, resolution "
            "FROM fault_reports"
        ) as cursor:
            async for row in cursor:
                report = self._row_to_report(row)
                self._cache[report.signature] = report

    @staticmethod
    def _row_to_report(row: Any) -> FaultReport:
        return FaultReport(
            id=row[0],
            signature=row[1],
            tool_id=row[2],
            error_text=row[3],
            attempted=row[4],
            agent_id=row[5],
            thread_id=row[6],
            work_item_id=row[7],
            tool_trace_ref=row[8],
            status=row[9],
            occurrences=int(row[10]),
            first_seen_at=float(row[11]),
            last_seen_at=float(row[12]),
            resolved_at=None if row[13] is None else float(row[13]),
            resolution=row[14] or "",
        )

    async def file_fault(
        self,
        *,
        tool_id: str,
        error_text: str,
        attempted: str = "",
        agent_id: str = "",
        thread_id: str = "",
        work_item_id: str | None = None,
        tool_trace_ref: str | None = None,
    ) -> FaultReport:
        """Record a fault, or note another occurrence of a known one.

        Never raises: an agent that cannot file a fault must still finish its
        turn. A broken reporting channel is a smaller harm than a lost turn,
        which is the same judgement AD-1165 makes about promotion.
        """
        signature = error_signature(tool_id=tool_id, error_text=error_text)
        now = time.time()

        existing = self._cache.get(signature)
        # A repaired fault that recurs is a NEW fault: the repair did not hold,
        # and silently incrementing the old row would hide a regression.
        if existing is not None and existing.status in ("open", "diagnosing"):
            existing.occurrences += 1
            existing.last_seen_at = now
            await self._persist_occurrence(existing)
            return existing

        report = FaultReport(
            id=uuid.uuid4().hex[:12],
            signature=signature,
            tool_id=str(tool_id or "")[:_TOOL_ID_MAX],
            error_text=str(error_text or "")[:_ERROR_MAX],
            attempted=str(attempted or "")[:_ATTEMPTED_MAX],
            agent_id=str(agent_id or "")[:_AGENT_ID_MAX],
            thread_id=str(thread_id or "")[:_THREAD_ID_MAX],
            work_item_id=work_item_id,
            tool_trace_ref=(
                None if tool_trace_ref is None
                else str(tool_trace_ref)[:_TRACE_REF_MAX]
            ),
            status="open",
            occurrences=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        self._cache[signature] = report
        await self._persist_new(report)
        self._emit_fault("FAULT_REPORTED", report)
        logger.warning(
            "AD-1169: fault reported against tool %r by agent %s: %s",
            report.tool_id, report.agent_id or "<unknown>",
            report.error_text[:200],
        )
        return report

    async def _persist_new(self, report: FaultReport) -> None:
        if not self._db:
            return
        try:
            await self._db.execute(
                "INSERT INTO fault_reports (id, signature, tool_id, error_text, "
                "attempted, agent_id, thread_id, work_item_id, tool_trace_ref, "
                "status, occurrences, first_seen_at, last_seen_at, resolved_at, "
                "resolution) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    report.id, report.signature, report.tool_id,
                    report.error_text, report.attempted, report.agent_id,
                    report.thread_id, report.work_item_id,
                    report.tool_trace_ref, report.status, report.occurrences,
                    report.first_seen_at, report.last_seen_at,
                    report.resolved_at, report.resolution,
                ),
            )
            await self._db.commit()
        except Exception:
            logger.warning(
                "AD-1169: could not persist fault %s against %r; it is held in "
                "memory for this session only",
                report.id, report.tool_id, exc_info=True,
            )

    async def _persist_occurrence(self, report: FaultReport) -> None:
        if not self._db:
            return
        try:
            await self._db.execute(
                "UPDATE fault_reports SET occurrences = ?, last_seen_at = ? "
                "WHERE id = ?",
                (report.occurrences, report.last_seen_at, report.id),
            )
            await self._db.commit()
        except Exception:
            logger.warning(
                "AD-1169: could not persist occurrence %d of fault %s",
                report.occurrences, report.id, exc_info=True,
            )

    async def resolve(
        self, signature_or_id: str, *, status: FaultStatus, resolution: str = "",
    ) -> FaultReport | None:
        """Move a fault out of ``open``. Returns None when nothing matched."""
        report = self._cache.get(signature_or_id)
        if report is None:
            report = next(
                (r for r in self._cache.values() if r.id == signature_or_id),
                None,
            )
        if report is None:
            return None
        report.status = status
        report.resolution = str(resolution or "")[:_ERROR_MAX]
        report.resolved_at = time.time() if status in ("repaired", "dismissed") else None
        if self._db:
            try:
                await self._db.execute(
                    "UPDATE fault_reports SET status = ?, resolution = ?, "
                    "resolved_at = ? WHERE id = ?",
                    (report.status, report.resolution, report.resolved_at, report.id),
                )
                await self._db.commit()
            except Exception:
                logger.warning(
                    "AD-1169: could not persist resolution of fault %s",
                    report.id, exc_info=True,
                )
        self._emit_fault("FAULT_RESOLVED", report)
        return report

    def list_open(self) -> list[FaultReport]:
        """Open faults, most recently seen first."""
        return sorted(
            (r for r in self._cache.values() if r.status in ("open", "diagnosing")),
            key=lambda r: r.last_seen_at,
            reverse=True,
        )

    def get_by_tool(self, tool_id: str) -> list[FaultReport]:
        return [r for r in self._cache.values() if r.tool_id == tool_id]

    def get(self, signature_or_id: str) -> FaultReport | None:
        found = self._cache.get(signature_or_id)
        if found is not None:
            return found
        return next(
            (r for r in self._cache.values() if r.id == signature_or_id), None,
        )

    def _emit_fault(self, event_name: str, report: FaultReport) -> None:
        """Emit a first-class ``EventType`` so listeners can subscribe.

        Imported lazily and by name: this module sits below the event layer and
        must stay importable by a store test that never boots a runtime.
        """
        if self._emit_event is None:
            return
        try:
            from probos.events import EventType

            self._emit_event(getattr(EventType, event_name), {
                "fault_id": report.id,
                "tool_id": report.tool_id,
                "signature": report.signature,
                "occurrences": report.occurrences,
                "status": report.status,
            })
        except Exception:
            logger.debug(
                "AD-1169: fault event %s failed to emit", event_name, exc_info=True,
            )
