"""AD-1206: fault-store-owned journal for approved external issue writes."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from probos.config_models.agentic import valid_github_repository
from probos.protocols import DatabaseConnection

if TYPE_CHECKING:
    from probos.fault_report import FaultReport

logger = logging.getLogger(__name__)

FilingDisposition = Literal[
    "declined", "retryable_failure", "attempting", "filed", "outcome_unknown",
]
FAILURE_CODES = frozenset({
    "", "missing_repository", "missing_credential", "pre_send_failure", "rejected",
    "remote_uncertain", "malformed_receipt", "cancelled", "reconciliation_unconfirmed",
})
ISSUE_FILING_SCHEMA = """
CREATE TABLE IF NOT EXISTS fault_issue_filings (
    signature TEXT PRIMARY KEY,
    fault_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN
        ('declined', 'retryable_failure', 'attempting', 'filed', 'outcome_unknown')),
    issue_number INTEGER,
    issue_url TEXT NOT NULL DEFAULT '',
    failure_code TEXT NOT NULL DEFAULT ''
);
"""
_FILING_COLUMNS = (
    "signature, fault_id, request_id, repository, attempt_id, disposition, "
    "issue_number, issue_url, failure_code"
)
_FAULT_COLUMNS = (
    "id", "signature", "tool_id", "error_text", "attempted", "agent_id", "thread_id",
    "work_item_id", "tool_trace_ref", "status", "occurrences", "first_seen_at",
    "last_seen_at", "resolved_at", "resolution", "observed_as",
)


def _valid_github_url(
    repository: str, url: object, *, issue_number: int | None = None,
) -> bool:
    if not valid_github_repository(repository) or type(url) is not str:
        return False
    prefix = r"https://api\.github\.com/repos" if issue_number is None else r"https://github\.com"
    suffix = "" if issue_number is None else f"/issues/{issue_number}"
    match = re.fullmatch(prefix + r"/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)" + suffix, url)
    return match is not None and "/".join(match.groups()).lower() == repository.lower()


def valid_repository_url(repository: str, url: object) -> bool:
    return _valid_github_url(repository, url)


def valid_occurrence_count(value: object) -> bool:
    return type(value) is int and 1 <= value <= 2**63 - 1


@dataclass(frozen=True)
class IssueReceipt:
    number: int
    url: str


def valid_issue_receipt(repository: str, receipt: IssueReceipt) -> bool:
    return (
        type(receipt.number) is int and receipt.number > 0
        and _valid_github_url(repository, receipt.url, issue_number=receipt.number)
    )


@dataclass(frozen=True)
class IssueFiling:
    signature: str
    fault_id: str
    request_id: str
    repository: str
    attempt_id: str
    disposition: FilingDisposition
    issue_number: int | None = None
    issue_url: str = ""
    failure_code: str = ""


@dataclass(frozen=True)
class FilingClaim:
    acquired: bool
    filing: IssueFiling
    fault: FaultReport


class FilingUnavailable(RuntimeError):
    """The journal cannot establish durable authority; no remote write is safe."""


@asynccontextmanager
async def fault_transaction(
    connection: DatabaseConnection | None, lock: asyncio.Lock,
) -> AsyncIterator[DatabaseConnection]:
    """Own the whole shared-connection transaction, including cancellation."""
    async with lock:
        if connection is None:
            raise FilingUnavailable("fault_store_unavailable")
        try:
            await connection.execute("BEGIN IMMEDIATE")
            yield connection
            await connection.commit()
        except BaseException:
            try:
                await connection.execute("ROLLBACK")
            except Exception:
                logger.error(
                    "AD-1206: fault database rollback failed; durable filing "
                    "authority is unavailable and the operation is refused"
                )
            raise


async def _read_filing(db: DatabaseConnection, signature: str) -> IssueFiling | None:
    cursor = await db.execute(
        f"SELECT {_FILING_COLUMNS} FROM fault_issue_filings WHERE signature = ?",
        (signature,),
    )
    row = await cursor.fetchone()
    return IssueFiling(*row) if row is not None else None


async def _read_fault(
    db: DatabaseConnection, *, fault_id: str, signature: str, tool_id: str,
    agent_id: str, thread_id: str, work_item_id: str | None,
) -> FaultReport:
    from probos.fault_report import FaultReport

    cursor = await db.execute(
        f"SELECT {', '.join(_FAULT_COLUMNS)} FROM fault_reports "
        "WHERE id = ? AND signature = ? AND tool_id = ?",
        (fault_id, signature, tool_id),
    )
    row = await cursor.fetchone()
    if row is None:
        raise FilingUnavailable("fault_not_durable")
    fault = FaultReport(**dict(zip(_FAULT_COLUMNS, row)))
    if (
        re.fullmatch(r"[0-9a-f]{64}", signature) is None
        or agent_id != (fault.agent_id or "system")
        or thread_id != fault.thread_id[:64]
        or work_item_id not in (None, fault.work_item_id)
    ):
        raise FilingUnavailable("fault_identity_mismatch")
    if not valid_occurrence_count(fault.occurrences):
        raise FilingUnavailable("durable_qualification_unavailable")
    return fault


class FaultIssueFilings:
    """One journal on the fault store's connection and persistence lock."""

    def __init__(self, persistence_lock: asyncio.Lock) -> None:
        self._lock = persistence_lock
        self._db: DatabaseConnection | None = None

    def bind(self, connection: DatabaseConnection | None) -> None:
        self._db = connection

    async def get(self, signature: str) -> IssueFiling | None:
        async with fault_transaction(self._db, self._lock) as db:
            filing = await _read_filing(db, signature)
        return filing

    async def claim(
        self, *, fault_id: str, signature: str, tool_id: str, request_id: str,
        repository: str, agent_id: str, thread_id: str, work_item_id: str | None,
        minimum_occurrences: int,
    ) -> FilingClaim:
        if not valid_occurrence_count(minimum_occurrences):
            raise ValueError("invalid_minimum_occurrences")
        if not request_id or (repository and not valid_github_repository(repository)):
            raise ValueError("invalid_filing_identity")
        async with fault_transaction(self._db, self._lock) as db:
            fault = await _read_fault(
                db, fault_id=fault_id, signature=signature, tool_id=tool_id,
                agent_id=agent_id, thread_id=thread_id, work_item_id=work_item_id,
            )
            existing = await _read_filing(db, signature)
            acquired = existing is None or existing.disposition in {"declined", "retryable_failure"}
            if acquired:
                if fault.occurrences < minimum_occurrences:
                    raise FilingUnavailable("durable_qualification_unavailable")
                filing = IssueFiling(
                    signature, fault_id, request_id, repository, uuid.uuid4().hex, "attempting",
                )
                await db.execute(
                    f"INSERT INTO fault_issue_filings ({_FILING_COLUMNS}) "
                    "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(signature) DO UPDATE SET "
                    "fault_id=excluded.fault_id, request_id=excluded.request_id, "
                    "repository=excluded.repository, attempt_id=excluded.attempt_id, "
                    "disposition=excluded.disposition, issue_number=NULL, "
                    "issue_url='', failure_code=''",
                    (signature, fault_id, request_id, repository, filing.attempt_id,
                     "attempting", None, "", ""),
                )
            else:
                filing = existing
        return FilingClaim(acquired, filing, fault)

    async def complete(
        self, signature: str, attempt_id: str, *, disposition: FilingDisposition,
        receipt: IssueReceipt | None = None, failure_code: str = "",
    ) -> IssueFiling | None:
        if (
            disposition not in {"filed", "retryable_failure", "outcome_unknown"}
            or failure_code not in FAILURE_CODES
            or (disposition == "filed") != (receipt is not None)
            or (receipt is not None and failure_code)
        ):
            raise ValueError("invalid_filing_outcome")
        async with fault_transaction(self._db, self._lock) as db:
            current = await _read_filing(db, signature)
            if current is None or current.attempt_id != attempt_id:
                return None
            if current.disposition not in {"attempting", "outcome_unknown"}:
                return None
            if current.disposition == "outcome_unknown" and disposition == "retryable_failure":
                raise ValueError("uncertain_attempt_cannot_be_retried")
            if receipt is not None and not valid_issue_receipt(current.repository, receipt):
                raise ValueError("invalid_issue_receipt")
            await db.execute(
                "UPDATE fault_issue_filings SET disposition=?, issue_number=?, "
                "issue_url=?, failure_code=? WHERE signature=? AND attempt_id=?",
                (disposition, receipt.number if receipt else None,
                 receipt.url if receipt else "", failure_code, signature, attempt_id),
            )
            filing = await _read_filing(db, signature)
        return filing

    async def decline(
        self, *, fault_id: str, signature: str, tool_id: str, request_id: str,
        agent_id: str, thread_id: str, work_item_id: str | None,
    ) -> IssueFiling:
        if not request_id:
            raise ValueError("invalid_filing_identity")
        async with fault_transaction(self._db, self._lock) as db:
            await _read_fault(
                db, fault_id=fault_id, signature=signature, tool_id=tool_id,
                agent_id=agent_id, thread_id=thread_id, work_item_id=work_item_id,
            )
            existing = await _read_filing(db, signature)
            if existing is None or existing.disposition in {"declined", "retryable_failure"}:
                await db.execute(
                    f"INSERT INTO fault_issue_filings ({_FILING_COLUMNS}) "
                    "VALUES (?,?,?,'','','declined',NULL,'','') "
                    "ON CONFLICT(signature) DO UPDATE SET disposition='declined', "
                    "fault_id=excluded.fault_id, request_id=excluded.request_id, failure_code=''",
                    (signature, fault_id, request_id),
                )
            filing = await _read_filing(db, signature)
        return filing
