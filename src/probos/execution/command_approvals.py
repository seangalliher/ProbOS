"""AD-1328 S2b (#1530): command approvals -- the Captain's decision on one escalated
``run_command``, in one scope, and every run that decision admitted.

An escalated command is filed as an AD-1154 ``action`` request (tool ``run_command``,
action ``execute``) by ``probos.execution.command_escalation``; the request store stays
the authority for the ask. This store holds what the decision allows afterwards.

* A row is written only from a decided request (``record_decision``), keyed on the
  request id, and names what the decision is for: the asking agent, the scope
  (``work_item:<id>``, ``thread:<id>`` or ``""``), the command's canonical key and the
  policy digest. Approval writes ``active``; denial writes ``denied``. A replay of the
  decision changes nothing.
* A live denial dominates (repair r1): while an unexpired ``denied`` row exists for the
  same agent, scope, canonical key and digest -- under any request id -- ``use`` admits
  no run (checked inside its compare-and-set) and ``record_decision`` records no
  ``active`` row. A run admitted before the denial stands; nothing after it is admitted.
* ``use`` admits one run by one compare-and-set, committed before the caller starts
  the command: the first is the ``approved_run``, any later one a ``reuse``, each row
  naming the original request. Only a work-item scope admits more than one run, and a
  partial unique index makes a second ``approved_run`` for one approval impossible.
* A row admits nothing for another agent, scope, canonical key or digest; nothing at or
  past ``expires_at`` (``NOT NULL``); and nothing approved by anyone but the Captain
  under the Captain's authority (every ``action`` request is Captain-reserved,
  ``probos.delegated_approvals.classify_capability_request``). A change of who may
  approve is a change of ``approver_authority``, which strands every older row.
* Whether a work item is still open is the caller's question (it holds the work-item
  store); this module reads no other store and imports nothing from the runtime.

Rows are never deleted: approvals, denials and uses are governance evidence. Storage
goes through :class:`probos.protocols.ConnectionFactory`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal

from probos.capability_request import THREAD_ID_MAX_CHARS, validate_action_payload
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

#: The AD-1154 action shape a command escalation is filed under.
COMMAND_APPROVAL_TOOL_ID: Final = "run_command"
COMMAND_APPROVAL_ACTION: Final = "execute"
#: The only approver, and the only authority, a command approval is honoured under.
CAPTAIN: Final = "captain"
APPROVER_AUTHORITY: Final = "captain"
WORK_ITEM_SCOPE_PREFIX: Final = "work_item:"
THREAD_SCOPE_PREFIX: Final = "thread:"
#: Ceilings. A work-item approval also ends with its work item (checked by the caller).
REUSABLE_APPROVAL_TTL_SECONDS: Final = 7 * 86400.0
SINGLE_USE_APPROVAL_TTL_SECONDS: Final = 3600.0
#: Statuses that end a work-item scope; every per-type terminal set in probos.workforce
#: is a subset (tests pin it against probos.workforce._TERMINAL_STATUSES).
ENDED_WORK_ITEM_STATUSES: Final = frozenset({"done", "cancelled", "failed"})

_KEY_RE = re.compile(r"[0-9a-f]{64}")
_WORK_ITEM_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_MAX_TEXT = 128

_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_approvals (
    request_id TEXT PRIMARY KEY CHECK (length(request_id) > 0),
    agent_id TEXT NOT NULL CHECK (length(agent_id) > 0),
    scope_key TEXT NOT NULL,
    canonical_key TEXT NOT NULL CHECK (length(canonical_key) = 64),
    policy_digest TEXT NOT NULL CHECK (length(policy_digest) > 0),
    state TEXT NOT NULL CHECK (state IN ('active', 'denied')),
    approver TEXT NOT NULL,
    approver_authority TEXT NOT NULL,
    decided_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0 CHECK (uses >= 0)
);
CREATE INDEX IF NOT EXISTS idx_command_approvals_identity
    ON command_approvals(agent_id, scope_key, canonical_key, policy_digest, state);
CREATE TABLE IF NOT EXISTS command_approval_uses (
    use_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    use_kind TEXT NOT NULL CHECK (use_kind IN ('approved_run', 'reuse')),
    used_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_command_approval_first_use
    ON command_approval_uses(request_id) WHERE use_kind = 'approved_run';
CREATE INDEX IF NOT EXISTS idx_command_approval_uses_request
    ON command_approval_uses(request_id);
"""
_COLUMNS = (
    "request_id, agent_id, scope_key, canonical_key, policy_digest, state, approver, "
    "approver_authority, decided_at, expires_at, uses"
)
_USE_COLUMNS = "use_id, request_id, agent_id, scope_key, use_kind, used_at"

ApprovalState = Literal["active", "denied"]
UseKind = Literal["approved_run", "reuse"]


@dataclass(frozen=True)
class CommandApproval:
    """One decided command escalation."""

    request_id: str
    agent_id: str
    scope_key: str
    canonical_key: str
    policy_digest: str
    state: str
    approver: str
    approver_authority: str
    decided_at: float
    expires_at: float
    uses: int


@dataclass(frozen=True)
class CommandApprovalUse:
    """One run an approval admitted; ``request_id`` is the original approval."""

    use_id: str
    request_id: str
    agent_id: str
    scope_key: str
    use_kind: str
    used_at: float


@dataclass(frozen=True)
class CommandApprovalAsk:
    """What a filed command escalation asks approval for, read from its request."""

    request_id: str
    agent_id: str
    scope_key: str
    work_item_id: str | None
    canonical_key: str
    policy_digest: str


def scope_work_item_id(scope_key: object) -> str | None:
    """The work item a ``work_item:<id>`` scope names, else None."""
    if type(scope_key) is not str or not scope_key.startswith(WORK_ITEM_SCOPE_PREFIX):
        return None
    work_item_id = scope_key[len(WORK_ITEM_SCOPE_PREFIX):]
    return work_item_id if _WORK_ITEM_ID_RE.fullmatch(work_item_id) else None


def valid_scope_key(scope_key: object) -> bool:
    """``""``, ``work_item:<id>`` or ``thread:<id>`` (at most the AD-1154 thread bound)."""
    if type(scope_key) is not str:
        return False
    if scope_key == "":
        return True
    if scope_key.startswith(WORK_ITEM_SCOPE_PREFIX):
        return scope_work_item_id(scope_key) is not None
    if scope_key.startswith(THREAD_SCOPE_PREFIX):
        return 0 < len(scope_key) - len(THREAD_SCOPE_PREFIX) <= THREAD_ID_MAX_CHARS
    return False


def approval_ttl_seconds(scope_key: str) -> float:
    """How long a decision in ``scope_key`` can be used, at most."""
    if scope_work_item_id(scope_key) is not None:
        return REUSABLE_APPROVAL_TTL_SECONDS
    return SINGLE_USE_APPROVAL_TTL_SECONDS


def command_approval_request(req: Any) -> CommandApprovalAsk | None:
    """The identity a capability request asks approval for, when it is a well-formed
    command escalation (``action`` / ``run_command`` / ``execute``), else None.

    The payload is re-validated (``validate_action_payload``); a work-item scope must
    name the request's own work item.
    """
    if getattr(req, "kind", None) != "action":
        return None
    payload = validate_action_payload(getattr(req, "payload", None))
    if payload is None:
        return None
    if payload["tool_id"] != COMMAND_APPROVAL_TOOL_ID or payload["action"] != COMMAND_APPROVAL_ACTION:
        return None
    params = payload["params"]
    canonical_key = params.get("canonical_key")
    policy_digest = params.get("policy_digest")
    if type(canonical_key) is not str or _KEY_RE.fullmatch(canonical_key) is None:
        return None
    if type(policy_digest) is not str or not 0 < len(policy_digest) <= _MAX_TEXT:
        return None
    scope_key = payload["scope_key"]
    if not valid_scope_key(scope_key):
        return None
    work_item_id = scope_work_item_id(scope_key)
    if work_item_id is not None and getattr(req, "work_item_id", None) != work_item_id:
        return None
    request_id = getattr(req, "id", None)
    agent_id = getattr(req, "agent_id", None)
    if type(request_id) is not str or not request_id or len(request_id) > _MAX_TEXT:
        return None
    if type(agent_id) is not str or not agent_id or len(agent_id) > _MAX_TEXT:
        return None
    return CommandApprovalAsk(request_id, agent_id, scope_key, work_item_id, canonical_key, policy_digest)


def _check_identity(
    request_id: object, agent_id: object, scope_key: object, canonical_key: object, policy_digest: object,
) -> None:
    for name, value in (("request_id", request_id), ("agent_id", agent_id), ("policy_digest", policy_digest)):
        if type(value) is not str or not value or len(value) > _MAX_TEXT:
            raise ValueError(f"command_approval_{name}_invalid")
    if not valid_scope_key(scope_key):
        raise ValueError("command_approval_scope_invalid")
    if type(canonical_key) is not str or _KEY_RE.fullmatch(canonical_key) is None:
        raise ValueError("command_approval_canonical_key_invalid")


def _row_to_approval(row: Any) -> CommandApproval:
    return CommandApproval(
        request_id=row[0], agent_id=row[1], scope_key=row[2], canonical_key=row[3],
        policy_digest=row[4], state=row[5], approver=row[6], approver_authority=row[7],
        decided_at=float(row[8]), expires_at=float(row[9]), uses=int(row[10]),
    )


async def _rollback(db: Any) -> None:
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1328: rollback found no open transaction")


class SqliteCommandApprovalStore:
    """SQLite-backed command approvals; see the module docstring for the guarantees.

    Public API:
        start() / stop()
        record_decision(...) -> CommandApproval | None   first decision wins
        find(agent, scope, key, digest, *, state)        newest usable row, else None
        use(request_id, *, agent_id, scope_key)          one admitted run, else None
        get(request_id) / list_uses(request_id)
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db_path = db_path
        self._db: Any = None
        self._clock = clock
        self._lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Open the database and apply the schema."""
        self._db = await self._connection_factory.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        logger.info("AD-1328: command approval store started (db=%s)", self._db_path)

    async def stop(self) -> None:
        """Close the database; later calls fail closed."""
        db, self._db = self._db, None
        if db is not None:
            await db.close()

    def _now(self) -> float:
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise RuntimeError("AD-1328: the command approval store clock is not a finite real")
        return float(now)

    def _require_db(self) -> Any:
        if self._db is None:
            raise RuntimeError("AD-1328: the command approval store is not running")
        return self._db

    async def record_decision(
        self,
        *,
        request_id: str,
        agent_id: str,
        scope_key: str,
        canonical_key: str,
        policy_digest: str,
        state: ApprovalState,
        approver: str,
        ttl_seconds: float,
    ) -> CommandApproval | None:
        """Write the decision on one filed escalation; the first decision wins.

        Returns the row as stored, or None when an ``active`` decision was not recorded
        because a live denial of the same identity stands (repair r1). Raises
        ``ValueError`` for an identity that is not well formed. ``approver_authority``
        is always the Captain's.
        """
        _check_identity(request_id, agent_id, scope_key, canonical_key, policy_digest)
        if state not in ("active", "denied"):
            raise ValueError("command_approval_state_invalid")
        if type(approver) is not str or not approver.strip() or len(approver) > _MAX_TEXT:
            raise ValueError("command_approval_approver_invalid")
        if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("command_approval_ttl_invalid")
        db = self._require_db()
        now = self._now()
        async with self._lock:
            try:
                await db.execute(
                    f"INSERT OR IGNORE INTO command_approvals ({_COLUMNS}) "
                    "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0 "
                    "WHERE ? = 'denied' OR NOT EXISTS (SELECT 1 FROM command_approvals "
                    "WHERE agent_id = ? AND scope_key = ? AND canonical_key = ? AND policy_digest = ? "
                    "AND state = 'denied' AND expires_at > ?)",
                    (
                        request_id, agent_id, scope_key, canonical_key, policy_digest, state,
                        approver, APPROVER_AUTHORITY, now, now + float(ttl_seconds),
                        state, agent_id, scope_key, canonical_key, policy_digest, now,
                    ),
                )
                await db.commit()
            except BaseException:
                await _rollback(db)
                raise
        return await self.get(request_id)

    async def find(
        self,
        agent_id: str,
        scope_key: str,
        canonical_key: str,
        policy_digest: str,
        *,
        state: ApprovalState,
    ) -> CommandApproval | None:
        """The newest unexpired row of ``state`` for exactly this identity. An ``active``
        row outside a work-item scope is found only while it is unused."""
        db = self._require_db()
        now = self._now()
        async with db.execute(
            f"SELECT {_COLUMNS} FROM command_approvals "
            "WHERE agent_id = ? AND scope_key = ? AND canonical_key = ? AND policy_digest = ? "
            "AND state = ? AND expires_at > ? "
            "AND (state <> 'active' OR substr(scope_key, 1, 10) = 'work_item:' OR uses = 0) "
            "ORDER BY decided_at DESC LIMIT 1",
            (agent_id, scope_key, canonical_key, policy_digest, state, now),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_approval(row)

    async def use(self, request_id: str, *, agent_id: str, scope_key: str) -> CommandApprovalUse | None:
        """Admit one run under an active approval; None when it admits none.

        One transaction: the compare-and-set on the approval, then the use row. It is
        committed before the caller starts the command, so a crash afterwards can lose
        a run but never repeat one (nothing replays it). The compare-and-set also fails
        while a live denial of the same agent, scope, canonical key and digest stands,
        under any request id (repair r1).
        """
        db = self._require_db()
        now = self._now()
        async with self._lock:
            try:
                cursor = await db.execute(
                    "UPDATE command_approvals SET uses = uses + 1 "
                    "WHERE request_id = ? AND agent_id = ? AND scope_key = ? AND state = 'active' "
                    "AND expires_at > ? AND approver = ? AND approver_authority = ? "
                    "AND NOT EXISTS (SELECT 1 FROM command_approvals AS denial "
                    "WHERE denial.agent_id = command_approvals.agent_id "
                    "AND denial.scope_key = command_approvals.scope_key "
                    "AND denial.canonical_key = command_approvals.canonical_key "
                    "AND denial.policy_digest = command_approvals.policy_digest "
                    "AND denial.state = 'denied' AND denial.expires_at > ?) "
                    "AND (substr(scope_key, 1, 10) = 'work_item:' OR uses = 0)",
                    (request_id, agent_id, scope_key, now, CAPTAIN, APPROVER_AUTHORITY, now),
                )
                if int(cursor.rowcount) != 1:
                    await _rollback(db)
                    return None
                async with db.execute(
                    "SELECT uses FROM command_approvals WHERE request_id = ?", (request_id,),
                ) as cur:
                    row = await cur.fetchone()
                use = CommandApprovalUse(
                    use_id=uuid.uuid4().hex,
                    request_id=request_id,
                    agent_id=agent_id,
                    scope_key=scope_key,
                    use_kind="approved_run" if int(row[0]) == 1 else "reuse",
                    used_at=now,
                )
                await db.execute(
                    f"INSERT INTO command_approval_uses ({_USE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                    (use.use_id, use.request_id, use.agent_id, use.scope_key, use.use_kind, use.used_at),
                )
                await db.commit()
            except BaseException:
                await _rollback(db)  # a failed use record must not leave the increment
                raise
        return use

    async def get(self, request_id: str) -> CommandApproval | None:
        db = self._require_db()
        async with db.execute(
            f"SELECT {_COLUMNS} FROM command_approvals WHERE request_id = ?", (request_id,),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else _row_to_approval(row)

    async def list_uses(self, request_id: str) -> list[CommandApprovalUse]:
        """Every run one approval admitted, oldest first."""
        db = self._require_db()
        out: list[CommandApprovalUse] = []
        async with db.execute(
            f"SELECT {_USE_COLUMNS} FROM command_approval_uses WHERE request_id = ? "
            "ORDER BY used_at, rowid",
            (request_id,),
        ) as cur:
            async for row in cur:
                out.append(CommandApprovalUse(row[0], row[1], row[2], row[3], row[4], float(row[5])))
        return out
