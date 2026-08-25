"""AD-853: Unified capability-request model + single approval queue.

The crew self-unblock loop produces three kinds of capability needs —
clearance grants, dependency installs, and agent builds. Before AD-853 each
flowed through a separate ad-hoc path. This module unifies them behind one
``CapabilityRequest`` record and one ``CapabilityRequestStore`` approval queue,
so the Captain reviews a single pending list regardless of request kind.

SQLite-backed with an in-memory cache, following the ConnectionFactory pattern
for cloud-ready storage (mirrors ``ClearanceGrantStore``). Emits lifecycle
events via ``EventEmitterMixin`` and, on decision, records a trust outcome for
the requesting agent when a trust network is wired.

AD-1154 adds a FOURTH kind, ``"action"``: an ask about *performing* a specific
tool action, rather than about *acquiring* a capability. It is a fourth kind on
this store rather than a fifth store because everything an approval inbox needs
already exists here and is already wired — the AD-857 REST decision surface, the
AD-857 Captain-DM notifier, the AD-855 resume driver, and a kind-agnostic HXI
panel that renders a new kind with no UI change. A parallel store would have put
the ask on a surface nobody polls.

The ``payload`` column carries the action shape (``tool_id`` / ``action`` /
``params`` / ``scope_key`` / ``session_id`` / ``thread_id``) because ``target``
is a bare string. It is NULL for every ``grant`` / ``install`` / ``build`` row,
so those paths are byte-identical.

**Approval of an ``action`` request does NOT replay the parked action** — see
:meth:`file_action_request`. The recorded ``session_id`` is forensic only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, Literal

from probos.events import EventType
from probos.protocols import EventEmitterMixin

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, TrustNetworkProtocol

logger = logging.getLogger(__name__)

_RATIONALE_MAX = 280

# AD-1154 / DD-1: exact-key validation for a ``kind="action"`` payload, applied
# on write AND on read. A hand-edited DB row is an untrusted input, so the read
# side re-validates rather than trusting what the write side once accepted.
_ACTION_PAYLOAD_MAX_CHARS = 4000
_ACTION_PAYLOAD_KEYS: frozenset[str] = frozenset(
    {"tool_id", "action", "params", "scope_key", "session_id", "thread_id"}
)
_TOOL_ID_RE = re.compile(r"^[a-z0-9_:.-]{1,64}$")
_ACTION_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_MAX_ACTION_PARAM_KEYS = 20
_SCOPE_KEY_MAX = 253
_SESSION_ID_MAX = 64
_THREAD_ID_MAX = 64

_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_requests (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    work_item_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    decided_at REAL,
    decided_by TEXT NOT NULL DEFAULT '',
    decision_reason TEXT NOT NULL DEFAULT '',
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_caprequests_status ON capability_requests(status);
CREATE INDEX IF NOT EXISTS idx_caprequests_agent ON capability_requests(agent_id);
"""

RequestKind = Literal["grant", "install", "build", "action"]
RequestStatus = Literal["pending", "approved", "denied", "fulfilled", "failed"]


def _canonical_json(value: Any) -> str:
    """Deterministic JSON for hashing and storage. Raises on unserialisable input."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def validate_action_payload(payload: Any) -> dict[str, Any] | None:
    """Return ``payload`` when it is a well-formed AD-1154 action payload, else None.

    Exact-key validation in both directions (DD-1): the decoded value must be a
    dict with EXACTLY the six keys, each within its declared bound, and the whole
    thing must serialise to at most ``_ACTION_PAYLOAD_MAX_CHARS``. Returns None
    rather than raising so a corrupt row degrades to ``payload=None`` instead of
    preventing the store from starting.
    """
    if type(payload) is not dict:
        return None
    if set(payload) != _ACTION_PAYLOAD_KEYS:
        return None

    tool_id = payload["tool_id"]
    action = payload["action"]
    params = payload["params"]
    scope_key = payload["scope_key"]
    session_id = payload["session_id"]
    thread_id = payload["thread_id"]

    if type(tool_id) is not str or _TOOL_ID_RE.fullmatch(tool_id) is None:
        return None
    if type(action) is not str or _ACTION_RE.fullmatch(action) is None:
        return None
    if type(params) is not dict or len(params) > _MAX_ACTION_PARAM_KEYS:
        return None
    if any(type(key) is not str for key in params):
        return None
    if type(scope_key) is not str or len(scope_key) > _SCOPE_KEY_MAX:
        return None
    if session_id is not None and (
        type(session_id) is not str or len(session_id) > _SESSION_ID_MAX
    ):
        return None
    if type(thread_id) is not str or len(thread_id) > _THREAD_ID_MAX:
        return None

    try:
        encoded = _canonical_json(payload)
    except (TypeError, ValueError, OverflowError):
        return None
    if len(encoded) > _ACTION_PAYLOAD_MAX_CHARS:
        return None
    # BF-854: refuse what the dedup key cannot hash. A lone surrogate is a legal
    # ``str`` and survives ``json.loads``; ``_canonical_json`` then passes it
    # through untouched because it sets ``ensure_ascii=False``, so neither the
    # guard above nor the length check sees anything wrong. ``action_dedup_key``
    # raises ``UnicodeEncodeError`` on it -- and because ``_find_pending_action``
    # re-derives the key for EVERY cached row on every filing, one such row makes
    # ``file_action_request`` raise for every unrelated caller until it is
    # removed. The same encode is what SQLite performs when binding the column.
    #
    # Checked on the canonical form rather than field by field: ``scope_key`` and
    # both the keys and values of ``params`` feed the key material, and anything
    # anywhere in the payload has to be encodable to be persisted at all.
    #
    # Deliberately NOT expressed by switching the bound above to bytes. That
    # would tighten the limit for payloads already persisted and accepted, and
    # ``_decode_payload`` re-validates on read -- silently dropping the payload
    # of approvals that were valid when they were written.
    try:
        encoded.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return payload


def _decode_payload(raw: Any) -> dict[str, Any] | None:
    """Decode + re-validate a stored ``payload`` column. Never raises."""
    if raw is None:
        return None
    if type(raw) is not str:
        logger.warning(
            "AD-1154: capability_requests.payload is %s, not TEXT; "
            "loading the row with payload=None",
            type(raw).__name__,
        )
        return None
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning(
            "AD-1154: capability_requests.payload is not valid JSON; "
            "loading the row with payload=None"
        )
        return None
    validated = validate_action_payload(decoded)
    if validated is None:
        logger.warning(
            "AD-1154: capability_requests.payload failed exact-key validation; "
            "loading the row with payload=None"
        )
    return validated


def action_dedup_key(
    *,
    agent_id: str,
    payload: dict[str, Any],
    work_item_id: str | None,
) -> str:
    """AD-1154 / DD-1: stable identity of an action ask, recomputed from the row.

    Deliberately NOT a twelfth column — recomputing it on cache load keeps the
    schema at one added column and needs no second index. A model that retries a
    refused call three times therefore files ONE ask, not three.
    """
    try:
        canonical_params = _canonical_json(payload.get("params"))
    except (TypeError, ValueError, OverflowError):
        canonical_params = "\ufffd"
    material = "|".join(
        [
            agent_id,
            str(payload.get("tool_id", "")),
            str(payload.get("action", "")),
            str(payload.get("scope_key", "")),
            work_item_id or "",
            canonical_params,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class CapabilityRequest:
    """A single capability need filed by a crew agent for Captain review."""

    id: str = ""
    agent_id: str = ""
    kind: RequestKind = "grant"
    target: str = ""
    rationale: str = ""
    work_item_id: str | None = None
    status: RequestStatus = "pending"
    created_at: float = 0.0
    decided_at: float | None = None
    decided_by: str = ""
    decision_reason: str = ""
    # AD-1154 / DD-1: appended LAST so no existing positional index shifts.
    # NULL for kind in (grant, install, build).
    payload: dict[str, Any] | None = None


class CapabilityRequestStore(EventEmitterMixin):
    """Single approval queue for clearance/install/build capability requests.

    - file_request() inserts a pending request, caches it, emits FILED
    - decide() approves/denies, records a trust outcome, emits DECIDED
    - list_pending() / get() are async cache reads (zero I/O after start)
    - start() loads all requests into cache; stop() closes the DB
    """

    def __init__(
        self,
        db_path: str = "",
        connection_factory: "ConnectionFactory | None" = None,
        emit_event: Callable[..., Any] | None = None,
        trust_network: "TrustNetworkProtocol | None" = None,
    ) -> None:
        self.db_path = db_path
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        self._emit_event = emit_event
        self._trust_network = trust_network
        self._db: Any = None
        # In-memory cache: request_id -> CapabilityRequest
        self._cache: dict[str, CapabilityRequest] = {}

    async def start(self) -> None:
        if self.db_path:
            self._db = await self._connection_factory.connect(self.db_path)
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=5000")
            await self._db.execute("PRAGMA synchronous=NORMAL")
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            await self._migrate_payload_column()
            await self._refresh_cache()
            logger.info("CapabilityRequestStore started (db=%s)", self.db_path)

    async def _migrate_payload_column(self) -> None:
        """AD-1154 / DD-1: add ``payload`` to a pre-AD-1154 11-column table.

        ``CREATE TABLE IF NOT EXISTS`` is a no-op against an existing table, so an
        operator upgrading in place would otherwise hit ``table has no column named
        payload`` on the first INSERT. Guarded on ``PRAGMA table_info`` so a
        fresh DB (already 12 columns) skips it and a restart is idempotent.
        """
        if not self._db:
            return
        async with self._db.execute(
            "PRAGMA table_info(capability_requests)"
        ) as cursor:
            columns = {row[1] async for row in cursor}
        if "payload" in columns:
            return
        await self._db.execute(
            "ALTER TABLE capability_requests ADD COLUMN payload TEXT"
        )
        await self._db.commit()
        logger.info(
            "AD-1154: migrated capability_requests to 12 columns "
            "(added payload); existing rows load with payload=None"
        )

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def _refresh_cache(self) -> None:
        """Load all requests into the in-memory cache."""
        self._cache.clear()
        if not self._db:
            return
        async with self._db.execute(
            "SELECT id, agent_id, kind, target, rationale, work_item_id, "
            "status, created_at, decided_at, decided_by, decision_reason, "
            "payload "
            "FROM capability_requests"
        ) as cursor:
            async for row in cursor:
                req = self._row_to_request(row)
                self._cache[req.id] = req

    async def file_request(
        self,
        agent_id: str,
        kind: RequestKind,
        target: str,
        rationale: str = "",
        work_item_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> CapabilityRequest:
        """File a new pending capability request. Writes DB + cache, emits FILED.

        ``payload`` (AD-1154) is the ``kind="action"`` action shape; existing
        callers pass nothing and the column is written NULL.
        """
        encoded_payload: str | None = None
        if payload is not None:
            encoded_payload = _canonical_json(payload)
        req = CapabilityRequest(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            kind=kind,
            target=target,
            rationale=(rationale or "")[:_RATIONALE_MAX],
            work_item_id=work_item_id,
            status="pending",
            created_at=time.time(),
            payload=payload,
        )
        if self._db:
            await self._db.execute(
                "INSERT INTO capability_requests "
                "(id, agent_id, kind, target, rationale, work_item_id, "
                "status, created_at, decided_at, decided_by, decision_reason, "
                "payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, '', '', ?)",
                (req.id, req.agent_id, req.kind, req.target, req.rationale,
                 req.work_item_id, req.status, req.created_at, encoded_payload),
            )
            await self._db.commit()
        self._cache[req.id] = req
        self._emit(EventType.CAPABILITY_REQUEST_FILED, {
            "id": req.id,
            "agent_id": req.agent_id,
            "kind": req.kind,
            "target": req.target,
            "work_item_id": req.work_item_id,
        })
        logger.info(
            "AD-853: Capability request filed — %s wants %s '%s' (id=%s)",
            agent_id[:12], kind, target, req.id[:12],
        )
        return req

    async def file_action_request(
        self,
        agent_id: str,
        payload: dict[str, Any],
        *,
        rationale: str = "",
        work_item_id: str | None = None,
    ) -> CapabilityRequest | None:
        """AD-1154: file (or dedup onto) a ``kind="action"`` ask.

        The ask records that an unattended agent reached a consequential tool
        action and did NOT perform it. Returns the request, or ``None`` when the
        payload fails DD-1 validation (the caller refuses either way — a payload
        that cannot be recorded must never become an admission).

        **Approval does not replay the action.** ``BrowserToolConfig.
        session_max_duration_seconds`` is 1800 s and a human decision takes
        minutes to days, so the ``session_id`` in the payload almost certainly
        names a reaped session; replaying a page-relative selector against a
        fresh session and a changed page is a different act from the one the
        Captain approved. The ``session_id`` is retained for forensics and is
        never passed to a browser API. What approval buys is a durable record, a
        trust signal and — optionally — a standing rule that lets the NEXT run
        proceed without asking.

        Idempotent on ``sha256(agent_id | tool_id | action | scope_key |
        work_item_id | canonical_params)``: an existing PENDING ask with the same
        key is returned unchanged rather than inserted again, so a model that
        retries a refused call files one ask.
        """
        validated = validate_action_payload(payload)
        if validated is None:
            logger.warning(
                "AD-1154: rejected an action payload from %s that failed "
                "exact-key validation; no request was filed and the caller "
                "refuses the action",
                agent_id[:12],
            )
            return None
        key = action_dedup_key(
            agent_id=agent_id, payload=validated, work_item_id=work_item_id
        )
        existing = self._find_pending_action(key)
        if existing is not None:
            logger.info(
                "AD-1154: action ask from %s deduped onto pending request %s "
                "(same agent/tool/action/scope/work-item/params)",
                agent_id[:12], existing.id[:12],
            )
            return existing
        target = f"{validated['tool_id']}.{validated['action']}"
        if validated["scope_key"]:
            target = f"{target} @ {validated['scope_key']}"
        return await self.file_request(
            agent_id=agent_id,
            kind="action",
            target=target,
            rationale=rationale,
            work_item_id=work_item_id,
            payload=validated,
        )

    def _find_pending_action(self, key: str) -> CapabilityRequest | None:
        """Return the pending ``action`` request whose dedup key matches, if any."""
        for req in self._cache.values():
            if req.status != "pending" or req.kind != "action" or req.payload is None:
                continue
            if (
                action_dedup_key(
                    agent_id=req.agent_id,
                    payload=req.payload,
                    work_item_id=req.work_item_id,
                )
                == key
            ):
                return req
        return None

    def count_pending_sync(self, agent_id: str, *, stale_before: float = 0.0) -> int:
        """AD-1154 / DD-6: pending asks for ``agent_id``, excluding stale ones.

        Zero-I/O cache read. A stale ask (``created_at <= stale_before``) is
        excluded from the COUNT only — it keeps ``status="pending"`` and keeps
        appearing in :meth:`list_pending`, because auto-approving on timeout
        would make walking away the approval mechanism and auto-denying would
        silently discard a decision the Captain may still want to make.
        """
        return sum(
            1
            for req in self._cache.values()
            if req.agent_id == agent_id
            and req.status == "pending"
            and req.created_at > stale_before
        )

    async def decide(
        self,
        request_id: str,
        approve: bool,
        reason: str = "",
        decided_by: str = "captain",
    ) -> CapabilityRequest | None:
        """Approve or deny a request. Updates DB + cache, records trust, emits DECIDED.

        Returns the updated request, or None if the id is unknown.

        BF-722: the decision is built as a NEW object, committed, and only then
        published into the cache. :meth:`get` hands out the cached instance
        itself, so mutating it before the write made the in-memory queue report
        a decision the durable row had not taken; a failed lock or commit left
        the card gone from ``list_pending()`` and the row still ``pending``,
        resurrected on the next restart. The exception propagates untouched —
        the caller decides how to degrade — and the cache still holds the
        pending original. Trust and DECIDED follow the commit for the same
        reason: a decision that did not persist must not move trust or wake a
        blocked work item.
        """
        req = await self.get(request_id)
        if req is None:
            logger.warning(
                "AD-853: decide() called for unknown request %s; ignoring",
                request_id[:12],
            )
            return None
        updated = replace(
            req,
            status="approved" if approve else "denied",
            decided_at=time.time(),
            decided_by=decided_by,
            decision_reason=reason,
        )
        if self._db:
            await self._db.execute(
                "UPDATE capability_requests SET status = ?, decided_at = ?, "
                "decided_by = ?, decision_reason = ? WHERE id = ?",
                (updated.status, updated.decided_at, updated.decided_by,
                 updated.decision_reason, updated.id),
            )
            await self._db.commit()
        self._cache[updated.id] = updated
        if self._trust_network is not None:
            try:
                self._trust_network.record_outcome(
                    updated.agent_id,
                    approve,
                    weight=1.0,
                    intent_type="capability_request",
                    source="capability_request",
                )
            except Exception as e:  # noqa: BLE001 — trust update is non-critical
                logger.warning(
                    "AD-853: trust outcome failed for %s on request %s: %s; "
                    "decision still recorded",
                    updated.agent_id[:12], updated.id[:12], e,
                )
        self._emit(EventType.CAPABILITY_REQUEST_DECIDED, {
            "id": updated.id,
            "agent_id": updated.agent_id,
            "kind": updated.kind,
            "status": updated.status,
            "decided_by": updated.decided_by,
            "decision_reason": updated.decision_reason,
        })
        logger.info(
            "AD-853: Capability request %s — %s (by=%s)",
            updated.id[:12], updated.status, decided_by,
        )
        return updated

    async def mark_fulfilled(self, request_id: str) -> CapabilityRequest | None:
        """Mark a request fulfilled once its rung's fulfiller has completed.

        Updates DB + cache and emits FULFILLED. Returns the updated request, or
        None if the id is unknown.

        BF-722: same commit-then-publish ordering as :meth:`decide`, and for the
        same reason — FULFILLED is what resumes a blocked work item, so emitting
        it for a write that did not land would resume an item whose durable row
        still says the capability is outstanding.
        """
        req = await self.get(request_id)
        if req is None:
            logger.warning(
                "AD-854: mark_fulfilled() called for unknown request %s; ignoring",
                request_id[:12],
            )
            return None
        updated = replace(req, status="fulfilled")
        if self._db:
            await self._db.execute(
                "UPDATE capability_requests SET status = ? WHERE id = ?",
                (updated.status, updated.id),
            )
            await self._db.commit()
        self._cache[updated.id] = updated
        self._emit(EventType.CAPABILITY_REQUEST_FULFILLED, {
            "id": updated.id,
            "agent_id": updated.agent_id,
            "kind": updated.kind,
            "status": updated.status,
        })
        logger.info(
            "AD-854: Capability request %s — fulfilled",
            updated.id[:12],
        )
        return updated

    async def list_pending(self) -> list[CapabilityRequest]:
        """Return all requests still awaiting a decision."""
        return [r for r in self._cache.values() if r.status == "pending"]

    async def get(self, request_id: str) -> CapabilityRequest | None:
        """Return a request by id, or None if unknown."""
        return self._cache.get(request_id)

    @staticmethod
    def _row_to_request(row: tuple) -> CapabilityRequest:
        return CapabilityRequest(
            id=row[0],
            agent_id=row[1],
            kind=row[2],
            target=row[3],
            rationale=row[4],
            work_item_id=row[5],
            status=row[6],
            created_at=row[7],
            decided_at=row[8],
            decided_by=row[9],
            decision_reason=row[10],
            # AD-1154: appended LAST, matching the schema / dataclass / SELECT.
            payload=_decode_payload(row[11]),
        )
