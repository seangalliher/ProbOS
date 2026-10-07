"""AD-1198 slice 2b-ii (#1135, AD-1196 R-8): the standing of stored incoming transfer certificates, judged again by every
chain identity.db stores for the ship that issued them.

A transfer certificate is accepted against the chain identity.db stores for its origin ship when it is imported
(AD-1196). That chain may later be replaced -- by a recovery whose branch takes precedence over it (slice 2b-i), or,
after an operator's reset forgot it (slice 2c), by the next chain of that ship -- or extended by a recovery that declares
a compromise point, which voids the signatures anchored after it. While ``federation.peer_admission_enabled`` is armed,
every chain identity.db stores judges again, with AD-1196's own verifier (``verify_transfer_attestations``), every
stored incoming transfer certificate that ship issued, inside that chain import's unit of identity.db's writer
(BF-885): the chain and the standing it gives them commit together, or neither. A certificate the chain no longer
supports is marked; one it supports again is cleared. Nothing is deleted: ``transfer_marks`` is an append-only log --
one row each time a certificate's standing, or the reason for it, changes, naming the head of the chain it was judged
against -- and the certificates, their foreign birth records and their slots are kept and stay readable. The registry
reports a DID's marks (``AgentIdentityRegistry.transfer_marks``), and the agent identity endpoint shows them.

Every armed start creates the table when it is missing -- an identity.db written before this slice, or by code without
it -- and judges every stored certificate against the chain stored for its origin, so the marks follow the chains
stored now, also after code that does not keep them has stored chains. Code without this slice never reads or writes
the table, so an identity.db that has it opens and works there unchanged.

Amendment A-1. Every decision -- a mark, no change, a clear -- is taken from each certificate's newest committed row,
read inside the unit, and memory is a copy of those rows, installed only once a unit that read them has committed; until
one has, the marks are not known (``None``), never shown as none. So a start whose re-check fails leaves them not known
until a unit that reads them commits -- as the next chain identity.db stores does, its re-check also creating the table
when it is missing. Stored data that cannot be read fails nothing but itself: a stored certificate that cannot be
attributed to the ship that issued it, and a ship whose stored chain's head cannot be read, are left unjudged and logged
while every other is judged; a failure of identity.db itself -- a statement, or the unit's COMMIT -- still fails the unit.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.identity_key_binding import TRANSFER_MARKS_SCHEMA
from probos.identity_keys import verify_transfer_attestations

if TYPE_CHECKING:
    from probos.identity_writer import UnitConnection

logger = logging.getLogger(__name__)

ACTION_MARK = "mark"  # AD-1198 slice 2b-ii the chain stored for its origin no longer supports the certificate
ACTION_CLEAR = "clear"  # AD-1198 slice 2b-ii it supports a marked certificate again


@dataclass(frozen=True)
class TransferMark:
    """An incoming transfer certificate the chain stored for its origin no longer supports -- public data only."""

    certificate_hash: str
    subject_did: str  # the transferred agent's DID
    origin_ship_did: str  # the ship that issued it, whose chain it was judged against
    reason: str  # AD-1196's verdict
    chain_head: str  # the block hash of that chain's head
    chain_blocks: int
    judged_at: float


def _attributed(did: Any, certificate_hash: Any, vc_json: Any) -> tuple[str, dict[str, Any]] | str:
    """A stored incoming certificate's issuing ship and credential -- or, when it cannot be attributed to one, why
    (AD-1198 slice 2b-ii A-1). It reads stored data only, so nothing it meets is a failure of identity.db: whatever fails
    here fails that row alone."""
    if not isinstance(did, str) or not isinstance(certificate_hash, str):  # AD-1198 slice 2b-ii A-1 a BLOB is no certificate's hash or DID
        return "its hash or agent DID is not text"
    try:
        credential = json.loads(vc_json)
    except Exception as exc:  # noqa: BLE001 -- stored-data boundary: the decode does no I/O, so what it raises (RecursionError included) is this row's
        return f"its credential is not JSON ({type(exc).__name__})"
    if not isinstance(credential, dict):
        return "its credential is not a JSON object"
    issuer = credential.get("issuer")
    if not isinstance(issuer, str):
        return "its credential names no issuer as text"
    return issuer, credential


async def _committed(db: UnitConnection) -> dict[str, TransferMark]:
    """Inside a unit: the marks ``transfer_marks`` records -- every certificate whose newest committed row marks it, in
    the order they were marked -- from which every decision of the unit is taken (AD-1198 slice 2b-ii A-1)."""
    marks: dict[str, TransferMark] = {}
    async with db.execute(
        "SELECT certificate_hash, subject_did, origin_ship_did, action, reason, chain_head, chain_blocks, judged_at "
        "FROM transfer_marks ORDER BY seq"
    ) as cursor:
        async for row in cursor:
            if row[3] == ACTION_MARK:  # AD-1198 slice 2b-ii a certificate's newest row decides its standing
                marks[row[0]] = TransferMark(row[0], row[1], row[2], row[4], row[5], row[6], row[7])
            else:
                marks.pop(row[0], None)
    return marks


class TransferMarks:
    """AD-1198 slice 2b-ii: the marks on stored incoming transfer certificates -- in identity.db, written only inside a
    unit of its writer, and in memory: a copy of the committed rows, installed only once a unit that read them has
    committed, and not loaded (``None``) until one has (A-1)."""

    def __init__(self) -> None:
        self._marks: dict[str, TransferMark] | None = None  # AD-1198 slice 2b-ii hash -> newest mark; A-1 None: not loaded

    def marks_for(self, did: str) -> tuple[TransferMark, ...] | None:
        """The marks held on ``did``'s incoming transfer certificates, in the order they were marked; ``None`` while they
        are not loaded (A-1): not known, never none."""
        if self._marks is None:  # AD-1198 slice 2b-ii A-1 no unit that read the marks has committed yet
            return None
        return tuple(mark for mark in self._marks.values() if mark.subject_did == did)

    async def recheck(self, db: UnitConnection, chains: Mapping[str, Sequence[Mapping[str, Any]]]) -> Callable[[], None]:
        """Inside a unit of identity.db's writer, once admitted: judge every stored incoming transfer certificate issued by
        a ship of ``chains`` against that ship's chain there -- the chain the unit stores -- with AD-1196's verifier, and
        append a row for each whose standing, or the reason for it, differs from its newest committed row. Returns what
        memory holds once the unit has committed -- the marks the committed rows record, this unit's included; memory
        changes only then.

        A-1: it first creates ``transfer_marks`` when it is missing (a start that failed may not have) and reads the
        committed rows, from which every decision is taken. A stored certificate that cannot be attributed to the ship
        that issued it, and a ship whose chain's head cannot be read, are left unjudged and logged while every other is
        judged; a failure of identity.db -- a statement here, or the unit's COMMIT -- fails the unit.
        """
        await db.execute(TRANSFER_MARKS_SCHEMA)
        marks = await _committed(db)  # AD-1198 slice 2b-ii A-1 the newest committed rows: every decision below is taken from them
        stored: dict[str, list[tuple[dict[str, Any], str, str]]] = {}
        async with db.execute(
            "SELECT rowid, did, certificate_hash, certificate_vc_json FROM transfer_certificates "
            "WHERE direction = 'incoming' ORDER BY rowid"
        ) as cursor:
            async for rowid, did, certificate_hash, vc_json in cursor:  # AD-1198 slice 2b-ii read inside the unit: what committed
                read = _attributed(did, certificate_hash, vc_json)
                if isinstance(read, str):  # AD-1198 slice 2b-ii A-1 a row that cannot be attributed fails alone
                    logger.warning(
                        "AD-1198: the stored incoming transfer certificate in row %d of transfer_certificates cannot be "
                        "attributed to the ship that issued it (%s); it is not judged and keeps the standing last recorded "
                        "for it, and every later re-check reads it again",
                        rowid, read,
                    )
                    continue
                issuer, credential = read
                if issuer in chains:  # AD-1198 slice 2b-ii only the certificates those ships issued
                    stored.setdefault(issuer, []).append((credential, certificate_hash, did))
        judged_at = time.time()
        changed: list[tuple[str, str, str, str, TransferMark | None]] = []
        for origin, certificates in stored.items():
            chain = chains[origin]
            try:
                head, blocks = str(chain[-1]["block_hash"]), len(chain)
            except Exception as exc:  # noqa: BLE001 -- stored-data boundary: a stored chain whose head cannot be read fails its own certificates only (A-1)
                logger.warning(
                    "AD-1198: the stored incoming transfer certificates issued by %s cannot be judged: the chain identity.db "
                    "stores for it is malformed (%s); they keep the standing last recorded for them, and the next chain "
                    "stored for that ship judges them again",
                    origin, type(exc).__name__,
                )
                continue
            verdicts = verify_transfer_attestations(chain, certificates)  # AD-1198 slice 2b-ii AD-1196's verifier, one chain verification
            for (_, certificate_hash, did), verdict in zip(certificates, verdicts, strict=True):
                held = marks.get(certificate_hash)  # AD-1198 slice 2b-ii A-1 its newest committed row, never memory
                if verdict.accepted and held is None:  # AD-1198 slice 2b-ii still supported: nothing to record
                    continue
                if not verdict.accepted and held is not None and held.reason == verdict.reason:  # AD-1198 slice 2b-ii marked as before
                    continue
                action = ACTION_CLEAR if verdict.accepted else ACTION_MARK
                await db.execute(
                    "INSERT INTO transfer_marks (certificate_hash, subject_did, origin_ship_did, action, reason, "
                    "chain_head, chain_blocks, judged_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (certificate_hash, did, origin, action, verdict.reason, head, blocks, judged_at),
                )
                mark = None if verdict.accepted else TransferMark(certificate_hash, did, origin, verdict.reason, head, blocks, judged_at)
                changed.append((certificate_hash, did, origin, verdict.reason, mark))

        def held() -> None:  # AD-1198 slice 2b-ii memory follows exactly what committed, whatever happened to the caller
            for certificate_hash, did, origin, reason, mark in changed:
                if mark is None:
                    marks.pop(certificate_hash, None)
                    logger.info(
                        "AD-1198: the incoming transfer certificate %s of %s is supported again by the chain identity.db "
                        "stores for %s (%s); its mark is cleared",
                        certificate_hash, did, origin, reason,
                    )
                    continue
                marks[certificate_hash] = mark
                logger.warning(
                    "AD-1198: the incoming transfer certificate %s of %s is not supported by the chain identity.db stores "
                    "for %s (%s; head %s, %d blocks); it is marked, never deleted, and the agent's record stays readable",
                    certificate_hash, did, origin, reason, mark.chain_head, mark.chain_blocks,
                )
            self._marks = marks  # AD-1198 slice 2b-ii A-1 the committed rows, this unit's included: loaded from now on

        return held
