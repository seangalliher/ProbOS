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

# AD-1269: ``observed_as`` is LAST, and stays last. ``ALTER TABLE ADD COLUMN``
# can only append, so a database migrated in place and one created fresh have
# identical physical layout only if the CREATE names it in the same position.
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
    resolution TEXT NOT NULL DEFAULT '',
    observed_as TEXT NOT NULL DEFAULT ''
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

# AD-1269: the shape :func:`error_signature` produces. :attr:`ToolDefect.signature`
# always has it, so this guards the one remaining way a wrong shape can arrive --
# a subclass overriding the property, which still passes ``isinstance``. Using
# such a value would key a durable row on something no other occurrence can
# reproduce. ``fullmatch`` rather than ``match`` for BF-757's reason: ``$`` also
# matches before a trailing newline, so ``"<64 hex>\n"`` would pass an anchored
# ``match`` and be stored verbatim.
_SIGNATURE_RE = re.compile(r"[0-9a-f]{64}")


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


# AD-1170: a stalled turn has more than one possible cause, and until now the
# system only modelled one of them.
#
# AD-1164 asks "do you want me to keep going?", which is the right question when
# the turn simply needed more room. It is the wrong question when a tool is
# broken -- more room buys more attempts at something that will keep failing.
#
# BF-701 is the case. The agent asked the browser tool for ``key_type`` at step
# 2, was told ``unknown browser action: 'key_type'``, asked again at step 15,
# got the same answer, and burned the steps between on workarounds. It then
# filed a continue request, because that was the only verdict available. The
# diagnosis was sitting in its own results the whole time.
#
# Two occurrences is the threshold. Once is a transient -- a timeout, a race, a
# page that had not settled -- and retrying is the correct response. Twice is a
# pattern: the same tool answered the same way, and the agent already tried the
# obvious thing in between.
#
# The detection reads the outcome's OWN ``tool_calls``/``tool_results``, joined
# on request id. No classifier, no extra model call, no re-reading the persisted
# trace -- the same discipline as AD-1165 promoting on elapsed time. Evidence
# the turn already produced cannot be wrong about what it measures.
#
# AD-1257 moved this and :func:`detect_tool_defect` here from
# ``cognitive.continue_or_ask``. The detector's only production caller could not
# supply the evidence it reads (BF-793), and the scope that CAN
# (``WorkItemAgenticExecutor.run``) must not grow a runtime import edge into
# ``continue_or_ask``. Foundation is the tier both can reach.
_DEFECT_MIN_OCCURRENCES: int = 2

# A repeat count is bounded by the loop's own iteration cap in practice. This is
# a sanity bound so a hostile or malformed value cannot reach Captain-facing
# formatting: ``int`` is arbitrary-precision, and ``"%d" % 10**5000`` raises
# ValueError once it exceeds the interpreter's integer-to-string limit. Review
# measured exactly that crash from a value that passed every other check.
_DEFECT_COUNT_MAX: int = 1_000_000


@dataclass(frozen=True)
class ToolDefect:
    """AD-1257: one tool answering the same way more than once, in a bounded form.

    Carries what a fault report needs and nothing else. The raw call/result pairs
    stay in the loop's scope (AD-731); this crosses the executor boundary in their
    place.

    ``signature`` is a read-only :func:`property`, not a field: see
    :meth:`signature`. ``error_key`` is the material it hashes.

    AD-1269: ``tool_id`` is the CANONICAL registered id and ``observed_as`` is
    the name the model actually used, empty when the two agree. Identity and
    provenance are separated because five consumers need the registered id (the
    Captain-facing rationale, the repair approval's ``scope_key``,
    ``get_by_tool``, ``idx_faults_tool``, the ``FAULT_REPORTED`` payload) and
    one -- AD-1173's argument recovery -- needs the observed name, because the
    persisted trace records ``ToolCallRequest.name``.
    """

    tool_id: str = ""
    error_text: str = ""
    count: int = 0
    # The hashed half of the signature material. Always overwritten below, so a
    # value handed to the constructor cannot survive.
    error_key: str = ""
    observed_as: str = ""

    def __post_init__(self) -> None:
        # ORDER IS LOAD-BEARING. The key is taken from the UNTRUNCATED text,
        # because that is what the detector tallied on: ``normalise_error``
        # collapses whitespace and THEN truncates, so normalising first and
        # cutting later is not the same identity as cutting first and
        # normalising later. Deriving it after the truncation below split one
        # detected defect into two durable fault rows in a single turn --
        # measured with two whitespace-equivalent long errors: identical
        # detector identity, two rows, occurrences [1, 1] where one row with 2
        # was correct. Consumers must read ``signature`` rather than recompute
        # from ``error_text``, or they reintroduce the split.
        #
        # ``normalise_error`` already bounds its own output to ``_ERROR_MAX``,
        # so this field needs no separate cut.
        object.__setattr__(self, "error_key", normalise_error(self.error_text))
        # Bounded at CONSTRUCTION, to the same two limits the fault row itself
        # is bounded to, so this value can never be larger than the row it
        # becomes. A tool result is unbounded; everything downstream of here is
        # not, and the truncation belongs at the boundary rather than at each
        # consumer.
        object.__setattr__(
            self, "tool_id", str(self.tool_id or "")[:_TOOL_ID_MAX],
        )
        # Bounded to the same limit as ``tool_id``: it is the same kind of
        # value, and it lands in the same row.
        object.__setattr__(
            self, "observed_as", str(self.observed_as or "")[:_TOOL_ID_MAX],
        )
        object.__setattr__(
            self, "error_text", str(self.error_text or "")[:_ERROR_MAX],
        )
        # ``bool`` is an ``int`` subclass and is never an honest repeat count.
        count = self.count
        if type(count) is not int:
            count = 0
        object.__setattr__(self, "count", max(0, min(count, _DEFECT_COUNT_MAX)))

    @property
    def signature(self) -> str:
        """AD-1269: this defect's identity, DERIVED on every read.

        Deliberately not a stored field. A stored digest has no owner: round 2
        checked that a supplied one was 64 lowercase hex and never that it
        belonged to the tool named beside it, so a carrier naming ``run_python``
        holding ``browser``'s real digest incremented the BROWSER row and left
        ``run_python`` with no row at all -- measured against a reopened SQLite
        store as ``[('browser', 'df36654b938d', 2)]``. Deriving it from this
        carrier's OWN ``tool_id`` makes that carrier unconstructible rather
        than merely rejected, and ``object.__setattr__`` on a property with no
        setter raises instead of planting.

        Byte-identical to :func:`error_signature` over the untruncated text:
        ``tool_id`` is bounded in ``__post_init__`` by the same
        ``[:_TOOL_ID_MAX]`` that function applies, and ``error_key`` is its
        ``normalise_error(error_text)``.
        """
        material = f"{self.tool_id}|{self.error_key}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _canonical_tool_id(
    observed: str, resolve_tool_id: Callable[[str], str] | None,
) -> str:
    """AD-1269: the registered id behind an observed name, or the name verbatim.

    The resolver is INJECTED rather than imported. This module is foundation and
    stdlib-only; the authority that can answer the question
    (``llm_function_name_claimants`` over ``ToolRegistry.list_ids``) lives under
    ``cognitive/``, and reaching for it here would invert the layering. The
    caller that already holds a registry supplies the callable.

    Degrades to *observed* for every failure mode -- no resolver, a raising
    resolver, a resolver that answers with something that is not a non-empty
    string. A fault filed against the name the model used is still a true
    record; one filed against ``None`` is not.
    """
    if resolve_tool_id is None:
        return observed
    try:
        resolved = resolve_tool_id(observed)
    except Exception:
        logger.debug(
            "AD-1269: resolving the canonical id for %r raised; the fault is "
            "filed against the observed name", observed, exc_info=True,
        )
        return observed
    if type(resolved) is not str or not resolved:
        logger.warning(
            "AD-1269: the tool-id resolver answered %r for %r; filing against "
            "the observed name, because a fault row must name something",
            resolved, observed,
        )
        return observed
    return resolved


def detect_tool_defect(
    outcome: Any,
    *,
    resolve_tool_id: Callable[[str], str] | None = None,
) -> ToolDefect | None:
    """AD-1170: find a tool that failed the same way more than once.

    Returns a :class:`ToolDefect` for the most-repeated failing (tool, error)
    pair when it reaches the threshold, else ``None``.

    ``ToolCallResult`` carries the request id and the error text but not the
    tool name, and ``ToolCallRequest`` carries the id and the name -- so the two
    are joined on id. Both lists live on the outcome the caller already holds.

    AD-1269: ``resolve_tool_id`` maps the OBSERVED name to its canonical
    registered id, and it is applied BEFORE the tally. Grouping on the observed
    name splits one tool's failures across its alias and its own id: review
    measured ``mcp:docs:search`` invoked once under each, failing the same way
    both times, and the detector answered ``None`` while both same-name controls
    answered with a count of 2. The same split can also hand the win to a
    less-frequent competing defect. Each distinct name is resolved once per
    call; the ``max()`` and the threshold are otherwise unchanged.

    Never raises: a malformed outcome yields ``None`` and the caller takes the
    ordinary step-limit path, which is exactly today's behaviour.
    """
    try:
        calls = getattr(outcome, "tool_calls", None) or []
        results = getattr(outcome, "tool_results", None) or []
        if not calls or not results:
            return None

        name_by_id: dict[str, str] = {}
        for call in calls:
            call_id = getattr(call, "id", None)
            name = getattr(call, "name", None)
            if type(call_id) is str and type(name) is str and name:
                name_by_id[call_id] = name

        canonical_by_observed: dict[str, str] = {}

        def _canonical(observed_name: str) -> str:
            cached = canonical_by_observed.get(observed_name)
            if cached is None:
                cached = _canonical_tool_id(observed_name, resolve_tool_id)
                canonical_by_observed[observed_name] = cached
            return cached

        # (canonical tool, normalised error) -> [count, first raw error text,
        # first observed name]. The observed name is retained because the
        # persisted trace records it, and AD-1173 matches on it.
        tally: dict[tuple[str, str], list[Any]] = {}
        for result in results:
            if getattr(result, "is_error", False) is not True:
                continue
            observed = name_by_id.get(getattr(result, "id", ""), "")
            if not observed:
                continue
            raw = getattr(result, "output", "")
            raw_text = raw if type(raw) is str else str(raw)
            key = (_canonical(observed), normalise_error(raw_text))
            entry = tally.get(key)
            if entry is None:
                tally[key] = [1, raw_text, observed]
            else:
                entry[0] += 1

        if not tally:
            return None
        (canonical, _sig), (count, raw_text, observed) = max(
            tally.items(), key=lambda kv: kv[1][0],
        )
        if count < _DEFECT_MIN_OCCURRENCES:
            return None
        return ToolDefect(
            tool_id=canonical,
            error_text=raw_text,
            count=count,
            # Empty when the two agree, which is every non-MCP tool: the
            # provider's name regex accepts an ordinary id verbatim, so
            # canonicalisation is a no-op and the row carries no provenance it
            # does not need.
            observed_as="" if canonical == observed else observed,
        )
    except Exception:
        logger.debug(
            "AD-1170: defect detection raised; the turn takes the ordinary "
            "step-limit path", exc_info=True,
        )
        return None


def resolve_tool_defect(outcome: Any) -> ToolDefect | None:
    """AD-1257: the verdict for an outcome, whichever form it can carry.

    :func:`detect_tool_defect` joins ``tool_calls`` to ``tool_results``. The 1:1
    DM path's ``WorkItemAgenticOutcome`` has neither -- that is BF-793 -- so it
    instead carries an already-derived ``tool_defect``, computed in the one
    scope that held the pairs. Consumers that must work on both paths ask here.

    **The discriminator is provenance, not shape.** ``hasattr(outcome,
    "tool_calls")`` asks *what shape is this?*; the question is *what does this
    object know?* So: raw pairs that are actually POPULATED answer, else a
    verdict the producer marked as evaluated answers -- including when that
    verdict is ``None`` -- else nothing.

    Both hazards die on that ordering. A future projection with empty-default
    pair fields and a real verdict reads the verdict, so BF-793 cannot recur by
    a field being added. An object holding real pairs never defers to a verdict
    a later pass superseded, and the consumer files a fault report and quotes
    the tool to the Captain -- so a stale verdict is a fabricated claim, not a
    stale cache.

    Never raises, for the same reason :func:`detect_tool_defect` does not.
    """
    try:
        calls = getattr(outcome, "tool_calls", None) or []
        results = getattr(outcome, "tool_results", None) or []
        if calls and results:
            return detect_tool_defect(outcome)
        if getattr(outcome, "tool_defect_evaluated", False) is not True:
            # Unmarked. Either nobody evaluated, or the producer predates the
            # marker -- and an unmarked ``tool_defect`` is indistinguishable
            # from a default, so it is not evidence.
            return None
        carried = getattr(outcome, "tool_defect", None)
        if carried is None:
            return None
        # Exact type, not isinstance: a subclass can override the derived
        # ``signature`` property or skip ``__post_init__``, so "is a ToolDefect"
        # does not imply "was bounded by one". This value is quoted to the
        # Captain and keys a fault row.
        if type(carried) is not ToolDefect:
            logger.warning(
                "AD-1257: ignoring a carried tool defect of type %s; only a "
                "ToolDefect is bounded and trustworthy enough to quote to the "
                "Captain, so this turn takes the ordinary step-limit path",
                type(carried).__name__,
            )
            return None
        if carried.count < _DEFECT_MIN_OCCURRENCES or not carried.tool_id:
            # The carried path applies the same bar as the joined one, so a
            # producer cannot lower it by construction.
            return None
        if not carried.signature:
            # ``ToolDefect.signature`` is a sha256 hexdigest and is never empty,
            # so this is reachable only through a subclass overriding it --
            # which still passes the ``isinstance`` gate above. Without a
            # signature the dedup key is empty and every defect collides.
            logger.warning(
                "AD-1257: ignoring a carried tool defect for %r with no "
                "signature; it cannot be deduplicated against an existing "
                "fault, so this turn takes the ordinary step-limit path",
                carried.tool_id,
            )
            return None
        return carried
    except Exception:
        logger.debug(
            "AD-1257: resolving a tool defect raised; the turn takes the "
            "ordinary step-limit path", exc_info=True,
        )
        return None


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
    # AD-1269: the name the model actually used, when it is not ``tool_id``.
    # Empty for every tool whose id the provider's name regex accepts verbatim,
    # which today is everything except ``mcp:{server}:{tool}``. Last, matching
    # the column order an ``ALTER TABLE`` can produce.
    observed_as: str = ""

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
            "observed_as": self.observed_as,
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
        await self._migrate_observed_as_column()
        await self._load_cache()

    async def _migrate_observed_as_column(self) -> None:
        """AD-1269: add ``observed_as`` to a pre-AD-1269 15-column table.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op against an existing table, and
        the live vessel already has one -- empty, but present. Without this,
        :meth:`_load_cache` would fail on the next boot with ``no such column:
        observed_as`` and the store would come up with an empty cache, so every
        recurring fault would file a fresh row. Guarded on ``PRAGMA table_info``
        so a fresh DB skips it and a restart is idempotent. Same shape as
        ``CapabilityRequestStore._migrate_payload_column``.
        """
        if not self._db:
            return
        async with self._db.execute(
            "PRAGMA table_info(fault_reports)"
        ) as cursor:
            columns = {row[1] async for row in cursor}
        if "observed_as" in columns:
            return
        await self._db.execute(
            "ALTER TABLE fault_reports ADD COLUMN observed_as TEXT NOT NULL "
            "DEFAULT ''"
        )
        await self._db.commit()
        logger.info(
            "AD-1269: migrated fault_reports to 16 columns (added observed_as); "
            "existing rows load with observed_as='', which reads as 'the model "
            "used the tool's own id'"
        )

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
            "first_seen_at, last_seen_at, resolved_at, resolution, observed_as "
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
            observed_as=row[15] or "",
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
        defect: "ToolDefect | None" = None,
    ) -> FaultReport:
        """Record a fault, or note another occurrence of a known one.

        AD-1269: ``defect`` is the detector's own verdict, and every identity
        field of the row -- signature, ``tool_id``, ``observed_as`` -- is taken
        from it. The signature must be the one the detector derived, from the
        UNTRUNCATED error text: recomputing here would key the row on the
        truncated text instead, and ``normalise_error`` collapses digit and hex
        runs and *then* truncates, so the collapse frees room that the raw cut
        already spent. Measured: a 3,046-character digit-run error gives a
        different signature before and after the cut, which splits one fault
        across two rows and stops either reaching the repair threshold.

        Optional, so the fourteen callers that pass nothing get exactly today's
        behaviour, and TYPED rather than a bare digest string. Review measured
        the string form: supplying one tool's signature while naming another
        filed the second call onto the FIRST tool's row and gave the second
        tool no row at all. A digest has no owner and cannot be checked against
        the name beside it; :attr:`ToolDefect.signature` is derived from that
        carrier's own ``tool_id`` on every read, so a well-formed digest for
        the wrong tool is unconstructible rather than merely unlikely --
        planting one raises, because a property with no setter refuses even
        ``object.__setattr__``.

        Never raises: an agent that cannot file a fault must still finish its
        turn. A broken reporting channel is a smaller harm than a lost turn,
        which is the same judgement AD-1165 makes about promotion.
        """
        resolved_signature, resolved_tool_id, observed_as = (
            self._resolve_identity(defect, tool_id=tool_id, error_text=error_text)
        )
        now = time.time()

        existing = self._cache.get(resolved_signature)
        # A repaired fault that recurs is a NEW fault: the repair did not hold,
        # and silently incrementing the old row would hide a regression.
        if existing is not None and existing.status in ("open", "diagnosing"):
            existing.occurrences += 1
            existing.last_seen_at = now
            # AD-1269: provenance may go absent -> present, never the reverse.
            # The first occurrence of a fault may have been filed by a path
            # holding no trace ref; a later one that has one makes the repair
            # path's argument recovery possible, and there is no reason to keep
            # the emptier record. Overwriting an existing ref would be the
            # reverse trade -- discarding a trace that has already been proven
            # to exist for one that may not have been persisted yet.
            if not existing.tool_trace_ref and tool_trace_ref:
                existing.tool_trace_ref = str(tool_trace_ref)[:_TRACE_REF_MAX]
                # The observed name belongs TO that trace, so it moves with it,
                # including when the adopting occurrence has none. Review
                # measured both directions of the mismatch -- canonical row
                # keeping occurrence 1's name over occurrence 2's trace, and the
                # reverse -- and in each case ``find_failing_arguments`` scanned
                # the adopted trace for a name that is not in it and returned
                # None. A trace the reader cannot match is no better than none.
                existing.observed_as = str(observed_as or "")[:_TOOL_ID_MAX]
            await self._persist_occurrence(existing)
            # AD-1267: the recurrence IS the signal. Emitting only on the create
            # branch meant every event carried occurrences=1 while the repair
            # dispatcher requires >= 2, so no repair could ever be proposed.
            self._emit_fault("FAULT_REPORTED", existing)
            return existing

        report = FaultReport(
            id=uuid.uuid4().hex[:12],
            signature=resolved_signature,
            tool_id=resolved_tool_id,
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
            observed_as=observed_as,
        )
        self._cache[resolved_signature] = report
        await self._persist_new(report)
        self._emit_fault("FAULT_REPORTED", report)
        logger.warning(
            "AD-1169: fault reported against tool %r by agent %s: %s",
            report.tool_id, report.agent_id or "<unknown>",
            report.error_text[:200],
        )
        return report

    def _resolve_identity(
        self, defect: Any, *, tool_id: Any, error_text: Any,
    ) -> tuple[str, str, str]:
        """This row's ``(signature, tool_id, observed_as)`` and where they came from.

        The three travel together on a typed carrier or not at all. A carrier is
        trusted only when it is EXACTLY a :class:`ToolDefect`, whose signature is
        derived from its own ``tool_id`` and therefore cannot name a tool other
        than the one it carries -- anything else either computed the identity
        some other way or reached here by accident, and keying a durable row on
        it would mean no later occurrence of the same fault could ever coalesce
        onto it.

        ``type(...) is`` rather than ``isinstance``: a subclass overriding the
        ``signature`` property passes ``isinstance`` while returning ANOTHER
        tool's valid digest, and review measured that permanently incrementing
        the wrong durable row -- an ``Evil(ToolDefect)`` named ``run_python``
        reopened as ``[('browser', ..., 2)]`` with no ``run_python`` row. A
        subclass can also skip ``__post_init__`` entirely, so the bounds below
        are re-checked here rather than assumed: the same probe persisted a
        2,001-character ``tool_id``. No subclass exists in this tree; this keeps
        it that way at the one boundary where it would become durable.
        """
        if defect is None:
            return (
                error_signature(tool_id=tool_id, error_text=error_text),
                str(tool_id or "")[:_TOOL_ID_MAX],
                "",
            )
        supplied = getattr(defect, "signature", None)
        if (
            type(defect) is not ToolDefect
            or type(supplied) is not str
            or not _SIGNATURE_RE.fullmatch(supplied)
            or type(defect.tool_id) is not str
            or len(defect.tool_id) > _TOOL_ID_MAX
            or type(defect.observed_as) is not str
            or len(defect.observed_as) > _TOOL_ID_MAX
            or type(defect.error_key) is not str
            or len(defect.error_key) > _ERROR_MAX
        ):
            logger.warning(
                "AD-1269: ignoring a fault identity carrier of type %s for tool "
                "%r -- only a ToolDefect built through its own constructor "
                "derives a bounded signature from its own tool_id, so the "
                "identity is recomputed from the error text instead",
                type(defect).__name__, tool_id,
            )
            return (
                error_signature(tool_id=tool_id, error_text=error_text),
                str(tool_id or "")[:_TOOL_ID_MAX],
                "",
            )
        return (supplied, defect.tool_id, defect.observed_as)

    async def _persist_new(self, report: FaultReport) -> None:
        if not self._db:
            return
        try:
            await self._db.execute(
                "INSERT INTO fault_reports (id, signature, tool_id, error_text, "
                "attempted, agent_id, thread_id, work_item_id, tool_trace_ref, "
                "status, occurrences, first_seen_at, last_seen_at, resolved_at, "
                "resolution, observed_as) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    report.id, report.signature, report.tool_id,
                    report.error_text, report.attempted, report.agent_id,
                    report.thread_id, report.work_item_id,
                    report.tool_trace_ref, report.status, report.occurrences,
                    report.first_seen_at, report.last_seen_at,
                    report.resolved_at, report.resolution, report.observed_as,
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
                "UPDATE fault_reports SET occurrences = ?, last_seen_at = ?, "
                "tool_trace_ref = ?, observed_as = ? WHERE id = ?",
                (
                    report.occurrences, report.last_seen_at,
                    report.tool_trace_ref, report.observed_as, report.id,
                ),
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
