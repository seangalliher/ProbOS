"""AD-1299 S1b (#1352): the persisted first-trusted-digest ledger for repair evidence.

S1a records a sha256 per piece of evidence but takes no expected digest, so a
change is detectable only by a consumer that kept an earlier trusted digest
(S1a review round 1, F2). This store is that memory. For each evidence
reference -- ``(candidate digest, evidence kind, evidence ref)`` -- it keeps the
FIRST digest of a ``present`` link and reports a later, different digest for
the same reference as a change. It never replaces the first digest, and once a
change is observed the reference stays ``changed`` even if the bytes later
return to the first digest. New evidence (a gate rerun, a new review round) is
recorded under a new reference.

The database enforces immutability as well as this class (the AD-1286
precedent): triggers abort every UPDATE, every DELETE and every replacing
INSERT on both tables, which are ``WITHOUT ROWID``, and named ``CHECK``
constraints on the four string-valued columns admit only stored values that meet
the Python validators' rules for the stored text (TEXT storage class, no NUL,
ASCII, owned-id references; reference columns have no declared type, so no
affinity turns a bound number into text first; a NaN binds as NULL, which
``NOT NULL`` refuses). SQLite sees storage classes, not Python types: a ``str``
subclass is stored as the plain text it contains; the exact-``str`` rule the
validators apply to references and digests is ``check_and_record``'s, applied
before any write, not the engine's. Every operation opens its own
connection through the injected ``ConnectionFactory`` and closes it in
``finally``; one lock serialises in-process calls. A write that fails, or is
cancelled, before its COMMIT is queued leaves nothing: its uncommitted rows die
with their connection. Otherwise a cancelled call's outcome is unknown to the
caller: it may have been recorded (``check_and_record`` states the contract).

Detection, not prevention: the file lives under ProbOS's own OS identity, so a
writer with that identity can delete or rewrite it (D-B2). Nothing here
authenticates a producer, claims containment or grants authority.
``assess_candidate_evidence`` is the in-slice consumer. Not wired into the
runtime: S2 constructs and starts this store when admission exists.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import math
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol

from probos.cognitive.repair_candidate import (
    AuthorityClass,
    EvidenceCompleteness,
    EvidenceLink,
    RepairCandidate,
    ReviewAttestation,
    bind_reviews,
    evaluate_completion,
    is_evidence_ref,
    is_sha256_hex,
    verify_gate_receipt,
)
from probos.protocols import ConnectionFactory

logger = logging.getLogger(__name__)

REPAIR_EVIDENCE_STORE_SCHEMA_VERSION: Final = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repair_evidence_first_digests (
    candidate_digest TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_ref NOT NULL, -- first table: no declared type, so no affinity turns a bound number into TEXT before the CHECK
    first_sha256 TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    recorded_at REAL NOT NULL,
    CONSTRAINT repair_evidence_first_candidate_shape CHECK (typeof(candidate_digest) = 'text' AND length(CAST(candidate_digest AS BLOB)) = 64 AND length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'),
    CONSTRAINT repair_evidence_first_kind_shape CHECK (typeof(evidence_kind) = 'text' AND length(CAST(evidence_kind AS BLOB)) = length(evidence_kind) AND evidence_kind IN ('gate_receipt', 'review_set')),
    CONSTRAINT repair_evidence_first_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(CAST(evidence_ref AS BLOB)) = length(evidence_ref) AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref GLOB '[A-Za-z0-9]*' AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),
    CONSTRAINT repair_evidence_first_sha256_shape CHECK (typeof(first_sha256) = 'text' AND length(CAST(first_sha256 AS BLOB)) = 64 AND length(first_sha256) = 64 AND first_sha256 NOT GLOB '*[^0-9a-f]*'),
    PRIMARY KEY (candidate_digest, evidence_kind, evidence_ref)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS repair_evidence_digest_changes (
    candidate_digest TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    evidence_ref NOT NULL, -- change table: no declared type, so no affinity turns a bound number into TEXT before the CHECK
    first_changed_sha256 TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    observed_at REAL NOT NULL,
    CONSTRAINT repair_evidence_change_candidate_shape CHECK (typeof(candidate_digest) = 'text' AND length(CAST(candidate_digest AS BLOB)) = 64 AND length(candidate_digest) = 64 AND candidate_digest NOT GLOB '*[^0-9a-f]*'),
    CONSTRAINT repair_evidence_change_kind_shape CHECK (typeof(evidence_kind) = 'text' AND length(CAST(evidence_kind AS BLOB)) = length(evidence_kind) AND evidence_kind IN ('gate_receipt', 'review_set')),
    CONSTRAINT repair_evidence_change_ref_shape CHECK (typeof(evidence_ref) = 'text' AND length(CAST(evidence_ref AS BLOB)) = length(evidence_ref) AND length(evidence_ref) BETWEEN 1 AND 128 AND evidence_ref GLOB '[A-Za-z0-9]*' AND evidence_ref NOT GLOB '*[^A-Za-z0-9_.:-]*'),
    CONSTRAINT repair_evidence_change_sha256_shape CHECK (typeof(first_changed_sha256) = 'text' AND length(CAST(first_changed_sha256 AS BLOB)) = 64 AND length(first_changed_sha256) = 64 AND first_changed_sha256 NOT GLOB '*[^0-9a-f]*'),
    PRIMARY KEY (candidate_digest, evidence_kind, evidence_ref),
    FOREIGN KEY (candidate_digest, evidence_kind, evidence_ref)
        REFERENCES repair_evidence_first_digests (candidate_digest, evidence_kind, evidence_ref)
) WITHOUT ROWID;
CREATE TRIGGER IF NOT EXISTS repair_evidence_first_digests_no_update BEFORE UPDATE ON repair_evidence_first_digests
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_first_digests_no_delete BEFORE DELETE ON repair_evidence_first_digests
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_first_digests_no_replace BEFORE INSERT ON repair_evidence_first_digests
WHEN EXISTS (SELECT 1 FROM repair_evidence_first_digests WHERE candidate_digest = NEW.candidate_digest
             AND evidence_kind = NEW.evidence_kind AND evidence_ref = NEW.evidence_ref)
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_digest_changes_no_update BEFORE UPDATE ON repair_evidence_digest_changes
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_digest_changes_no_delete BEFORE DELETE ON repair_evidence_digest_changes
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
CREATE TRIGGER IF NOT EXISTS repair_evidence_digest_changes_no_replace BEFORE INSERT ON repair_evidence_digest_changes
WHEN EXISTS (SELECT 1 FROM repair_evidence_digest_changes WHERE candidate_digest = NEW.candidate_digest
             AND evidence_kind = NEW.evidence_kind AND evidence_ref = NEW.evidence_ref)
BEGIN SELECT RAISE(ABORT, 'repair_evidence_immutable'); END;
"""

TrustedDigestStatus = Literal["first_recorded", "unchanged", "changed"]
_STATUSES: Final = frozenset({"first_recorded", "unchanged", "changed"})


class RepairEvidenceStoreUnavailable(RuntimeError):
    """The store has not been started, has stopped, or its clock is not a finite real."""


class RepairEvidenceIntegrityError(ValueError):
    """A stored row no longer validates (data integrity: logged at ERROR, then propagated)."""


@dataclass(frozen=True, slots=True)
class TrustedDigestCheck:
    """What the ledger holds for one evidence reference after one observation."""

    status: TrustedDigestStatus
    candidate_digest: str
    kind: str
    evidence_ref: str
    first_sha256: str
    observed_sha256: str

    def __post_init__(self) -> None:
        if type(self.status) is not str or self.status not in _STATUSES:
            raise ValueError("trusted_digest_check_invalid")

    @property
    def changed(self) -> bool:
        """True once this reference has been observed with a digest other than its first."""
        return self.status == "changed"


class TrustedDigestRecorder(Protocol):
    """The one ledger operation ``assess_candidate_evidence`` needs."""

    async def check_and_record(self, evidence_ref: str, link: EvidenceLink) -> TrustedDigestCheck: ...


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    """One assessment: the derived links, the ledger's answer for each recorded one, and C9 completion."""

    completeness: EvidenceCompleteness
    links: tuple[EvidenceLink, ...]
    checks: tuple[TrustedDigestCheck, ...]


def _checked_now(clock: Callable[[], float]) -> float:
    """A finite ``now``; a bad clock refuses the write, because the row could never be corrected."""
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise RepairEvidenceStoreUnavailable("repair_evidence_clock_invalid")
    return float(now)


def _integrity_error(table: str, key: tuple[str, str, str]) -> RepairEvidenceIntegrityError:
    logger.error(
        "AD-1299 S1b: a stored %s row for %s evidence %s of candidate %s no longer validates; "
        "the observation is refused and nothing is recorded",
        table, key[1], key[2], key[0][:12],
    )
    return RepairEvidenceIntegrityError("repair_evidence_integrity")


async def _query(db: Any, sql: str, params: tuple[Any, ...]) -> list[Any]:
    cursor = await db.execute(sql, params)
    return list(await cursor.fetchall())


async def _first_digest(db: Any, key: tuple[str, str, str]) -> str | None:
    rows = await _query(
        db,
        "SELECT first_sha256, schema_version FROM repair_evidence_first_digests "
        "WHERE candidate_digest = ? AND evidence_kind = ? AND evidence_ref = ?",
        key,
    )
    if not rows:
        return None
    first, version = rows[0][0], rows[0][1]
    if type(version) is not int or version != REPAIR_EVIDENCE_STORE_SCHEMA_VERSION or not is_sha256_hex(first):
        raise _integrity_error("first-digest", key)
    return first


async def _first_change(db: Any, key: tuple[str, str, str], first: str) -> str | None:
    rows = await _query(
        db,
        "SELECT first_changed_sha256, schema_version FROM repair_evidence_digest_changes "
        "WHERE candidate_digest = ? AND evidence_kind = ? AND evidence_ref = ?",
        key,
    )
    if not rows:
        return None
    changed, version = rows[0][0], rows[0][1]
    if (
        type(version) is not int
        or version != REPAIR_EVIDENCE_STORE_SCHEMA_VERSION
        or not is_sha256_hex(changed)
        or changed == first
    ):
        raise _integrity_error("digest-change", key)
    return changed


class RepairEvidenceLinkStore:
    """Insert-only first-trusted-digest ledger for repair evidence references.

    Public API:
        start() / stop() -- lifecycle; idempotent
        check_and_record(evidence_ref, link) -> TrustedDigestCheck

    Raises:
        RepairEvidenceStoreUnavailable: not started, stopped, or a clock that is not a finite real.
        RepairEvidenceIntegrityError: a stored row that decides the observation no longer validates.
    """

    def __init__(
        self,
        db_path: str,
        connection_factory: ConnectionFactory | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Nothing is opened until :meth:`start`. ``""`` and ``":memory:"`` are refused: a ledger
        that forgets on restart defeats its purpose."""
        if type(db_path) is not str or not db_path or db_path == ":memory:":
            raise ValueError("repair_evidence_store_path_invalid")
        self._db_path = db_path
        self._clock = clock
        self._started = False
        self._lock = asyncio.Lock()
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            connection_factory = default_factory
        self._connection_factory: ConnectionFactory = connection_factory

    async def start(self) -> None:
        """Apply the schema, then admit operations. Idempotent; a failure leaves the store stopped."""
        async with self._lock:
            if self._started:
                return
            async with self._open() as db:
                await db.execute("PRAGMA journal_mode=WAL")
                await db.executescript(_SCHEMA)
                await db.commit()
            self._started = True
        logger.info(
            "AD-1299 S1b: RepairEvidenceLinkStore started (db=%s); first trusted digests are insert-only",
            self._db_path,
        )

    async def stop(self) -> None:
        """Stop admitting new operations. Waits for the lock, so a call holding it returns or raises
        first; a COMMIT queued by a cancelled call may still run afterwards. Idempotent."""
        async with self._lock:
            was_started, self._started = self._started, False
        if was_started:
            logger.info(
                "AD-1299 S1b: RepairEvidenceLinkStore stopped (db=%s); calls raise unavailable until start()",
                self._db_path,
            )

    @contextlib.asynccontextmanager
    async def _open(self) -> AsyncIterator[Any]:
        """One connection for one operation, with its own pragmas. Once ``connect`` has returned,
        ``close()`` is awaited in ``finally`` on every exit path (a repeated cancellation can
        interrupt that wait); a ``close()`` that raises is logged, not raised, and that connection
        may then stay open until it is released."""
        db = await self._connection_factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            try:
                await db.close()
            except Exception:  # noqa: BLE001 -- log-and-degrade: the operation's own result or error stands
                logger.warning(
                    "AD-1299 S1b: closing a repair evidence connection failed; its uncommitted work was never "
                    "visible to other connections, and later writes may wait on its lock until it is released",
                    exc_info=True,
                )

    async def check_and_record(self, evidence_ref: str, link: EvidenceLink) -> TrustedDigestCheck:
        """Record ``link``'s digest as the first trusted digest for its reference, or compare with it.

        ``first_recorded`` the first time; ``unchanged`` while no observation has differed; ``changed``
        once any observation differed (that first different digest is recorded once, and the status
        stays ``changed`` for this reference). The first digest is never replaced. Records what it is
        given: pass only a link derived from the evidence itself (``assess_candidate_evidence`` does).

        Cancellation contract (what a caller may rely on): ``CancelledError`` propagates and is not
        swallowed, and it means the outcome is unknown: the observation may or may not have been
        recorded. A retry with the identical link is safe: it answers the same for completion either
        way (``first_recorded`` if the cancelled call did not record, ``unchanged`` if it did;
        ``changed`` for a digest that differs from a recorded first). An abandoned observation of
        different evidence may leave this reference ``changed``: its digest may have become the
        first digest or the recorded change. Such a record can move a later answer only to
        ``changed``, which blocks completion. No promise is made about when ``CancelledError``
        arrives relative to the connection's cleanup, the lock's release or the queued COMMIT.

        Implementation note (not part of the contract; observed with aiosqlite 0.22.1): nothing is
        shielded. A call cancelled before its COMMIT is queued records nothing. Under a single
        cancellation, ``CancelledError`` arrives after the queued COMMIT and the connection's close
        (queued behind it on the same worker) have run, with the lock held until then. A repeated
        cancellation can interrupt the close and aiosqlite's ``stop()`` wait, so the call can end,
        and the lock be released, while the queued COMMIT is still pending; that COMMIT can still
        run afterwards.

        Raises ``ValueError`` for an invalid reference or a link that is not ``present`` with a digest,
        and ``TypeError`` for a non-``EvidenceLink``.
        """
        if not is_evidence_ref(evidence_ref):
            raise ValueError("repair_evidence_ref_invalid")
        if type(link) is not EvidenceLink:
            raise TypeError("repair_evidence_link_required")
        if not link.current or not link.evidence_sha256:
            raise ValueError("repair_evidence_link_untrusted")
        key = (link.candidate_digest, link.kind, evidence_ref)
        observed = link.evidence_sha256
        async with self._lock:
            if not self._started:
                raise RepairEvidenceStoreUnavailable("repair_evidence_store_unavailable")
            now = _checked_now(self._clock)
            async with self._open() as db:
                await db.execute("BEGIN IMMEDIATE")
                first = await _first_digest(db, key)
                if first is None:
                    await db.execute(
                        "INSERT INTO repair_evidence_first_digests (candidate_digest, evidence_kind, "
                        "evidence_ref, first_sha256, schema_version, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (*key, observed, REPAIR_EVIDENCE_STORE_SCHEMA_VERSION, now),
                    )
                    first, status = observed, "first_recorded"
                else:
                    changed = await _first_change(db, key, first)
                    if changed is None and observed != first:
                        await db.execute(
                            "INSERT INTO repair_evidence_digest_changes (candidate_digest, evidence_kind, "
                            "evidence_ref, first_changed_sha256, schema_version, observed_at) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (*key, observed, REPAIR_EVIDENCE_STORE_SCHEMA_VERSION, now),
                        )
                        changed = observed
                    status = "unchanged" if changed is None else "changed"
                await db.commit()  # not shielded: a COMMIT queued before a cancel may still run (D4a N2)
        return TrustedDigestCheck(status, key[0], key[1], key[2], first, observed)


async def assess_candidate_evidence(
    recorder: TrustedDigestRecorder,
    candidate: RepairCandidate,
    authority_class: AuthorityClass,
    *,
    receipt_ref: str,
    receipt_bytes: bytes | None,
    review_ref: str,
    reviews: Sequence[ReviewAttestation] | None,
    expected_assignee: str,
    expected_label: str | None = None,
    required_reviewers: int = 1,
) -> EvidenceAssessment:
    """Derive both links from the evidence, record each ``present`` one, then evaluate C9.

    The links are derived here, never accepted pre-built. A link that is not ``present`` is not
    recorded. A reference the ledger reports ``changed`` blocks completion as ``evidence_changed``,
    which takes precedence over every other reason. Argument errors raise before anything is
    recorded; every ledger exception propagates; nothing returns complete on an error. Complete
    evidence is not authority: the Captain's approval is separate (S2).
    """
    if not is_evidence_ref(receipt_ref) or not is_evidence_ref(review_ref):
        raise ValueError("repair_evidence_ref_invalid")
    links = (
        verify_gate_receipt(candidate, receipt_bytes, expected_label=expected_label),
        bind_reviews(
            candidate, reviews, expected_assignee=expected_assignee, required_reviewers=required_reviewers,
        ),
    )
    completeness = evaluate_completion(candidate, authority_class, links)
    checks: list[TrustedDigestCheck] = []
    for ref, link in zip((receipt_ref, review_ref), links, strict=True):
        if link.current:
            checks.append(await recorder.check_and_record(ref, link))
    if any(check.changed for check in checks):
        for check in checks:
            if check.changed:
                logger.warning(
                    "AD-1299 S1b: %s evidence %s for candidate %s has a recorded digest change (first trusted "
                    "digest %s, observed now %s); completion stays blocked for this reference even when the "
                    "observed digest equals the first again, so new evidence must be recorded under a new reference",
                    check.kind, check.evidence_ref, check.candidate_digest[:12],
                    check.first_sha256[:12], check.observed_sha256[:12],
                )
        completeness = dataclasses.replace(completeness, reason="evidence_changed")
    return EvidenceAssessment(completeness, links, tuple(checks))
