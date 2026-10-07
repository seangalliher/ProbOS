"""AD-1198 slice 2b-ii (#1135, AD-1196 R-8): stored incoming transfer certificates judged again by every chain identity.db
stores for the ship that issued them.

Tests are named by subject. m0 pins today's code: a certificate accepted on a branch that a recovery then replaces stays
stored, readable and unjudged, and identity.db has no marks table without the re-check. m1 covers AD-1196's verifier over
many certificates of one chain (``verify_transfer_attestations``) and the marks (``TransferMarks``) on real registries:
marked by a branch change and by a compromise point; unchanged when the verdict is; kept by a reset and judged again by
the next chain stored, which may clear them or record a new reason; replayed at a restart; created and judged at the
first armed start of an identity.db written without them; left untouched by a registry without them and corrected at
the next armed start; committed with the chain or not at all; held in memory as committed when the import's caller is
cancelled while it commits; a stored credential that names no issuer is not judged, and is logged; and a start whose
re-check fails starts, logs and reports the marks as not known. Amendment A-1 adds: a stored row or a stored chain that
cannot be read fails alone, at an import and at a start, while every other ship's certificates are judged; a restart
whose load fails reports the marks as not known, on the registry and the endpoint, and the next import decides from the
committed rows; and a start that failed before creating the table leaves the next import to create it. m2 covers the
wiring (armed only with peer admission) and the agent identity endpoint. m3 is the production path: a held peer's
recovery, the automatic resync that re-anchors the hold, and the
transfer accepted from the replaced branch marked. Real AD-1196 keys over the in-memory duck keyring, real registries,
envelope stores, seam, exchange and bridge on the mock bus. No test opens a socket, reaches the real OS keyring
(AD-1196's autouse guard is imported) or a live service.

M0 runs on the unmodified base: write this module up to the ``M1`` marker without the slice-2b-ii import block.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import keyring
import pytest

from probos.identity import AgentIdentityRegistry
from probos.identity_keys import generate_recovery_keypair, verify_transfer_attestation
from probos.mobility import TransferCertificate
from tests.test_ad1196_did_key_binding import _armed, _birth, _DuckKeyring, _table_names
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (no OS keyring)
from tests.test_ad1198_fork_resolution import _recover

SHIP_B = "did:probos:ship-b"
_NOT_ANCHORED = "transfer certificate is not anchored on the origin's ledger"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


@dataclasses.dataclass
class _Ships:
    """Ship-a (a recovery key committed at its inception), a copy of it that parted from it by one rotation, and ship-b
    holding Alpha's transfer, which ship-a issued before the copy, and Bravo's, which the copy issued after parting."""

    a: AgentIdentityRegistry
    a_binding: Any
    private: str
    public: str
    duck: _DuckKeyring
    copy_chain: list[dict[str, Any]]
    alpha: TransferCertificate
    bravo: TransferCertificate


async def _copied(
    stack: contextlib.AsyncExitStack, source: Path, duck: _DuckKeyring, public: str, directory: Path,
) -> tuple[AgentIdentityRegistry, Any]:
    """A ship over a copy of ``source``'s identity.db and keys as they are now; its next key event parts from them."""
    directory.mkdir()
    with contextlib.closing(sqlite3.connect(source / "identity.db")) as given, contextlib.closing(
        sqlite3.connect(directory / "identity.db"),
    ) as made:
        given.backup(made)
    copied = _DuckKeyring()
    copied.entries.update(duck.entries)
    return await stack.enter_async_context(_armed(directory, copied, recovery_public_key=public, instance_id="ship-a"))


async def _origin(
    stack: contextlib.AsyncExitStack, tmp: Path, b: AgentIdentityRegistry,
) -> tuple[AgentIdentityRegistry, Any, str, str, _DuckKeyring, TransferCertificate, Any]:
    """Ship-a with Alpha and Bravo born and Alpha transferred to ship-b, which stores ship-a's chain and Alpha's
    transfer; ship-a's binding, recovery key halves and keys, Alpha's certificate and Bravo's birth."""
    private, public = generate_recovery_keypair()
    duck = _DuckKeyring()
    a, a_binding = await stack.enter_async_context(_armed(tmp / "a", duck, recovery_public_key=public, instance_id="ship-a"))
    alpha_birth = await _birth(a, "Alpha")
    bravo_birth = await _birth(a, "Bravo")
    alpha = await a.issue_transfer_certificate(alpha_birth.agent_uuid, SHIP_B)
    assert (await b.import_chain(await a.export_chain()))[0], "premise: ship-b stores ship-a's chain"
    assert (await b.import_transfer_certificate(alpha))[0], "premise: ship-b holds Alpha's transfer"
    return a, a_binding, private, public, duck, alpha, bravo_birth


async def _ships(stack: contextlib.AsyncExitStack, tmp: Path, b: AgentIdentityRegistry) -> _Ships:
    """``_origin``, then a copy of ship-a that rotates once and transfers Bravo, whose chain and transfer ship-b stores."""
    a, a_binding, private, public, duck, alpha, bravo_birth = await _origin(stack, tmp, b)
    copy, copy_binding = await _copied(stack, tmp / "a", duck, public, tmp / "copy")
    await copy_binding.rotate()  # the copy parts from ship-a here
    bravo = await copy.issue_transfer_certificate(bravo_birth.agent_uuid, SHIP_B)
    copy_chain = await copy.export_chain()
    assert (await b.import_chain(copy_chain))[0], "premise: ship-b stores the copy's chain, which extends ship-a's"
    assert (await b.import_transfer_certificate(bravo))[0], "premise: ship-b holds Bravo's transfer from the copy"
    return _Ships(a, a_binding, private, public, duck, copy_chain, alpha, bravo)


async def _recovered(ships: _Ships, reason: str = "lost") -> list[dict[str, Any]]:
    """Ship-a's chain after a recovery signed by its committed recovery key, from the state it shares with the copy."""
    await _recover(ships.a_binding, ships.private, reason=reason)
    return await ships.a.export_chain()


def _vc(certificate: TransferCertificate) -> dict[str, Any]:
    """A certificate's credential as identity.db stores it: through JSON."""
    return json.loads(json.dumps(certificate.to_verifiable_credential()))


# --------------------------------------------------------------------------- #
# M0 -- today's code (passes on the unmodified base)
# --------------------------------------------------------------------------- #


async def test_s2bii_m0_a_certificate_accepted_on_a_replaced_branch_stays_stored_readable_and_unjudged(
    tmp_path: Path,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b, _ = await stack.enter_async_context(_armed(tmp_path / "b", _DuckKeyring(), instance_id="ship-b"))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships)
        replaced = await b.import_chain(chain_r, supersede=True)
        record = b.get_by_uuid(ships.bravo.agent_uuid)
        rows = await b.get_transfer_certificates_for(ships.bravo.did)
    verdict = verify_transfer_attestation(
        chain_r, credential=_vc(ships.bravo), certificate_hash=ships.bravo.certificate_hash, subject_did=ships.bravo.did,
    )
    assert replaced[0] is True, "premise: the recovery's branch replaced the copy's in identity.db"
    assert verdict == (False, _NOT_ANCHORED, None)  # the chain stored now does not support Bravo's transfer
    assert record is not None and record.did == ships.bravo.did  # yet its record stays readable
    assert [row["direction"] for row in rows] == ["incoming"]
    assert "transfer_marks" not in _table_names(tmp_path / "b" / "identity.db")


# M1 marker
# --------------------------------------------------------------------------- #
# slice 2b-ii names (M1 onward; omit this block for the M0 run on the unmodified base)
# --------------------------------------------------------------------------- #

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402

import probos.identity_keys as identity_keys  # noqa: E402
from probos.federation.envelope import POLICY_REQUIRE  # noqa: E402
from probos.federation.mock_transport import MockFederationTransport  # noqa: E402
from probos.identity_key_binding import IdentityKeyBinding  # noqa: E402
from probos.identity_key_store import KeyringKeyStore  # noqa: E402
from probos.identity_keys import verify_transfer_attestations  # noqa: E402
from probos.identity_transfer_marks import TransferMark, TransferMarks  # noqa: E402
from probos.routers import agents as agents_router  # noqa: E402
from probos.routers.deps import get_runtime  # noqa: E402
from probos.types import FederationMessage, IntentMessage  # noqa: E402
from tests.test_ad1196_did_key_binding import _boot_identity, _KeyringProbe, _registry, _stop_identity  # noqa: E402
from tests.test_ad1197_signed_envelopes import _active_key, _Node, _RecordingIntentBus, _Wire, _wrap  # noqa: E402
from tests.test_ad1198_fork_resolution import _held_on_copy, _owner  # noqa: E402
from tests.test_ad1198_identity_continuity import _exchange, _exchange_bridge, _messages, _until  # noqa: E402
from tests.test_ad1198_peer_admission import _admit  # noqa: E402
from tests.test_ad1198_peer_reset import _joined  # noqa: E402
from tests.test_bf885_identity_db_units import _rows, _SharedFactory  # noqa: E402

_MARKS_LOGGER = "probos.identity_transfer_marks"
_REGISTRY_LOGGER = "probos.identity"
_MARK_COLUMNS = "certificate_hash, subject_did, origin_ship_did, action, reason, chain_head, chain_blocks"
SHIP_Z = "did:probos:ship-z"
_DEEP = '{"issuer": "' + SHIP_Z + '", "nested": ' + "[" * 50_000 + "0" + "]" * 50_000 + "}"  # A-1 deeper than JSON decodes


@contextlib.asynccontextmanager
async def _receiver(directory: Path, duck: _DuckKeyring, *, marks: bool = True, connection_factory: Any = None) -> Any:
    """Ship-b's registry with a key binding over ``duck`` and, when ``marks``, the re-check; started and always stopped."""
    extra: dict[str, Any] = {"key_binding": IdentityKeyBinding(KeyringKeyStore(backend=duck))}
    if marks:
        extra["transfer_marks"] = TransferMarks()
    if connection_factory is not None:
        extra["connection_factory"] = connection_factory
    async with _registry(directory, instance_id="ship-b", **extra) as registry:
        yield registry


def _mark_rows(data_dir: Path) -> list[tuple[Any, ...]]:
    """The committed rows of ``transfer_marks``, in order, without their time."""
    return _rows(data_dir / "identity.db", f"SELECT {_MARK_COLUMNS} FROM transfer_marks ORDER BY seq")


def _row(certificate: TransferCertificate, action: str, reason: str, chain: list[dict[str, Any]]) -> tuple[Any, ...]:
    return (
        certificate.certificate_hash, certificate.did, certificate.origin_ship_did, action, reason,
        chain[-1]["block_hash"], len(chain),
    )


def _mark(certificate: TransferCertificate, reason: str, chain: list[dict[str, Any]], judged_at: float) -> TransferMark:
    return TransferMark(
        certificate.certificate_hash, certificate.did, certificate.origin_ship_did, reason, chain[-1]["block_hash"],
        len(chain), judged_at,
    )


def _void(chain: list[dict[str, Any]], certificate: TransferCertificate) -> str:
    """AD-1196's reason for a transfer signed after its key's declared compromise point, at the block that anchors it."""
    index = next(block["index"] for block in chain if block["certificate_hash"] == certificate.certificate_hash)
    return f"the transfer at block {index} was signed after its key's declared compromise point"


def _marked_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return _messages(caplog, _MARKS_LOGGER, logging.WARNING)


def _unattributed(rowid: int, why: str) -> str:
    """A-1: the line naming a stored row that cannot be attributed to the ship that issued it."""
    return (
        f"AD-1198: the stored incoming transfer certificate in row {rowid} of transfer_certificates cannot be attributed "
        f"to the ship that issued it ({why}); it is not judged and keeps the standing last recorded for it, and every "
        "later re-check reads it again"
    )


def _unreadable_chain(origin: str, error: str) -> str:
    """A-1: the line naming a ship whose stored chain's head cannot be read."""
    return (
        f"AD-1198: the stored incoming transfer certificates issued by {origin} cannot be judged: the chain identity.db "
        f"stores for it is malformed ({error}); they keep the standing last recorded for them, and the next chain stored "
        "for that ship judges them again"
    )


def _store_incoming(data_dir: Path, rows: list[tuple[Any, ...]]) -> dict[Any, int]:
    """A-1: rows written into ``transfer_certificates`` directly -- stored data this code did not write; every row's rowid,
    by its certificate hash."""
    with contextlib.closing(sqlite3.connect(data_dir / "identity.db")) as db:
        db.executemany(
            "INSERT INTO transfer_certificates (did, transfer_timestamp, direction, certificate_hash, "
            "certificate_vc_json) VALUES (?, ?, 'incoming', ?, ?)",
            rows,
        )
        db.commit()
        return dict(db.execute("SELECT certificate_hash, rowid FROM transfer_certificates").fetchall())


def _app(runtime: Any) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app


async def _identity(registry: Any, slot: str) -> httpx.Response:
    """``GET /api/agent/{slot}/identity`` on the production router, over ``registry``."""
    transport = httpx.ASGITransport(app=_app(SimpleNamespace(identity_registry=registry)))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(f"/api/agent/{slot}/identity")


# --------------------------------------------------------------------------- #
# M1 -- AD-1196's verifier over many certificates of one chain
# --------------------------------------------------------------------------- #


async def test_s2bii_m1_verify_transfer_attestations_gives_each_single_verdict_in_order_and_verifies_the_chain_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b, _ = await stack.enter_async_context(_armed(tmp_path / "b", _DuckKeyring(), instance_id="ship-b"))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships, "compromised")
    certificates = [
        (_vc(ships.alpha), ships.alpha.certificate_hash, ships.alpha.did),
        (_vc(ships.bravo), ships.bravo.certificate_hash, ships.bravo.did),
        ({"not": {"a", "credential"}}, ships.alpha.certificate_hash, ships.alpha.did),  # a set has no RFC 8785 form
    ]
    singles = {
        name: [
            verify_transfer_attestation(chain, credential=credential, certificate_hash=digest, subject_did=did)
            for credential, digest, did in certificates
        ]
        for name, chain in (("copy", ships.copy_chain), ("recovered", chain_r))
    }
    calls: list[int] = []
    verify = identity_keys.verify_chain_signatures

    def counted(blocks: Any) -> Any:
        calls.append(len(blocks))
        return verify(blocks)

    monkeypatch.setattr(identity_keys, "verify_chain_signatures", counted)
    batch = {
        "copy": verify_transfer_attestations(ships.copy_chain, certificates),
        "recovered": verify_transfer_attestations(chain_r, certificates),
    }
    odd = verify_transfer_attestations(chain_r, [(_vc(ships.alpha), ships.alpha.certificate_hash)])  # type: ignore[list-item]

    assert calls == [len(ships.copy_chain), len(chain_r), len(chain_r)]  # one verification of each chain per call
    assert batch == {name: tuple(verdicts) for name, verdicts in singles.items()}
    assert [verdict.accepted for verdict in batch["copy"]] == [True, True, False]
    assert [verdict.reason for verdict in batch["recovered"]] == [
        _void(chain_r, ships.alpha), _NOT_ANCHORED, "malformed transfer attestation (ValueError)",
    ]
    assert odd == ((False, "malformed transfer attestation (ValueError)", None),)


async def test_s2bii_m1_verify_transfer_attestations_refuses_all_on_a_chain_that_does_not_verify_and_accepts_unsigned(
    tmp_path: Path,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b, _ = await stack.enter_async_context(_armed(tmp_path / "b", _DuckKeyring(), instance_id="ship-b"))
        ships = await _ships(stack, tmp_path, b)
        unsigned = await stack.enter_async_context(_registry(tmp_path / "unsigned", instance_id="ship-a"))
        unsigned_chain = await unsigned.export_chain()
    tampered = json.loads(json.dumps(ships.copy_chain))
    event = next(block for block in tampered if (block.get("attestation") or {}).get("kind") == "key_event")
    event["attestation"]["signatures"] = {role: "x" + jws[1:] for role, jws in event["attestation"]["signatures"].items()}
    certificates = [(_vc(ships.alpha), ships.alpha.certificate_hash, ships.alpha.did)]
    refused = verify_transfer_attestations(tampered, certificates)
    accepted = verify_transfer_attestations(unsigned_chain, certificates)
    assert not identity_keys.verify_chain_signatures(tampered).ok, "premise: the tampered chain does not verify"
    assert len(refused) == 1 and not refused[0].accepted
    assert refused[0].reason.startswith("the origin chain's signatures do not verify: ")
    assert accepted == ((True, "origin has no bound key; transfer accepted unsigned", None),)
    assert verify_transfer_attestations(ships.copy_chain, []) == ()


# --------------------------------------------------------------------------- #
# M1 -- the marks
# --------------------------------------------------------------------------- #


async def test_s2bii_m1_a_recovery_branch_marks_the_certificate_accepted_on_the_replaced_branch_and_keeps_everything(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_MARKS_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        ships = await _ships(stack, tmp_path, b)
        assert b.transfer_marks(ships.bravo.did) == (), "premise: nothing is marked while the copy's chain is stored"
        assert (await b.reassign_slot(ships.bravo.agent_uuid, "slot-bravo"))[0], "premise: Bravo holds a slot here"
        chain_r = await _recovered(ships)
        replaced = await b.import_chain(chain_r, supersede=True)
        marks = b.transfer_marks(ships.bravo.did)
        kept = (
            b.get_by_uuid(ships.bravo.agent_uuid), b.get_by_slot("slot-bravo"),
            await b.get_transfer_certificates_for(ships.bravo.did), b.transfer_marks(ships.alpha.did),
        )
    assert replaced == (True, f"Chain imported: {len(chain_r)} blocks from {ships.bravo.origin_ship_did}")
    assert len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(ships.bravo, _NOT_ANCHORED, chain_r, marks[0].judged_at),)
    assert kept[0] is not None and kept[0].did == ships.bravo.did and kept[1] is kept[0]  # the record and its slot stay
    assert [row["certificate_hash"] for row in kept[2]] == [ships.bravo.certificate_hash]  # the certificate stays
    assert kept[3] == ()  # the transfer ship-a issued before the copy parted stays supported
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)]
    assert _marked_lines(caplog) == [
        f"AD-1198: the incoming transfer certificate {ships.bravo.certificate_hash} of {ships.bravo.did} is not supported "
        f"by the chain identity.db stores for {ships.bravo.origin_ship_did} ({_NOT_ANCHORED}; head "
        f"{chain_r[-1]['block_hash']}, {len(chain_r)} blocks); it is marked, never deleted, and the agent's record stays "
        "readable",
    ]


async def test_s2bii_m1_a_recovery_declaring_a_compromise_marks_a_transfer_signed_after_the_compromise_point(
    tmp_path: Path,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        a, a_binding, private, _, _, alpha, _ = await _origin(stack, tmp_path, b)
        await _recover(a_binding, private, reason="compromised")
        extended = await a.export_chain()
        imported = await b.import_chain(extended)  # an extension: no branch change
        marks = b.transfer_marks(alpha.did)
    assert imported[0] is True
    assert len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(alpha, _void(extended, alpha), extended, marks[0].judged_at),)
    assert _mark_rows(tmp_path / "b") == [_row(alpha, "mark", _void(extended, alpha), extended)]


async def test_s2bii_m1_a_chain_that_still_supports_every_certificate_records_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_MARKS_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        a, a_binding, _, _, _, alpha, bravo_birth = await _origin(stack, tmp_path, b)
        await a_binding.rotate()  # a rotation retires a key; it voids nothing signed before it
        bravo = await a.issue_transfer_certificate(bravo_birth.agent_uuid, SHIP_B)
        longer = await a.export_chain()
        first = await b.import_chain(longer)
        transferred = await b.import_transfer_certificate(bravo)
        again = await b.import_chain(longer)
        marks = (b.transfer_marks(alpha.did), b.transfer_marks(bravo.did))
    assert first[0] and transferred[0] and again[0]
    assert marks == ((), ())
    assert _mark_rows(tmp_path / "b") == []
    assert [record.getMessage() for record in caplog.records if record.name == _MARKS_LOGGER] == []


async def test_s2bii_m1_a_reset_keeps_the_marks_and_the_next_chain_stored_judges_them_again_and_may_clear_them(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_MARKS_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships)
        assert (await b.import_chain(chain_r, supersede=True))[0], "premise: the recovery's branch is stored"
        marked = b.transfer_marks(ships.bravo.did)
        forgotten = await b.forget_foreign_chain(ships.bravo.origin_ship_did)  # slice 2c's reset, in identity.db
        after_reset = (b.transfer_marks(ships.bravo.did), _mark_rows(tmp_path / "b"))
        stored = await b.import_chain(ships.copy_chain)  # the first chain stored after the reset: the copy's
        after_copy = (b.transfer_marks(ships.bravo.did), b.transfer_marks(ships.alpha.did))
    assert len(marked) == 1 and forgotten == len(chain_r)
    assert after_reset == (marked, [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)])  # a reset keeps the marks
    assert stored[0] is True and after_copy == ((), ())  # the copy's chain supports Bravo's transfer again
    clearing = next(
        verdict.reason for verdict in verify_transfer_attestations(
            ships.copy_chain, [(_vc(ships.bravo), ships.bravo.certificate_hash, ships.bravo.did)],
        )
    )
    assert _mark_rows(tmp_path / "b") == [
        _row(ships.bravo, "mark", _NOT_ANCHORED, chain_r), _row(ships.bravo, "clear", clearing, ships.copy_chain),
    ]
    assert _messages(caplog, _MARKS_LOGGER, logging.INFO)[-1] == (
        f"AD-1198: the incoming transfer certificate {ships.bravo.certificate_hash} of {ships.bravo.did} is supported "
        f"again by the chain identity.db stores for {ships.bravo.origin_ship_did} ({clearing}); its mark is cleared"
    )


async def test_s2bii_m1_a_marks_new_reason_is_recorded_and_an_unchanged_reason_is_not(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        private, public = generate_recovery_keypair()
        duck = _DuckKeyring()
        a, a_binding = await stack.enter_async_context(_armed(tmp_path / "a", duck, recovery_public_key=public, instance_id="ship-a"))
        alpha_birth = await _birth(a, "Alpha")
        early, early_binding = await _copied(stack, tmp_path / "a", duck, public, tmp_path / "early")  # before Alpha leaves
        alpha = await a.issue_transfer_certificate(alpha_birth.agent_uuid, SHIP_B)
        assert (await b.import_chain(await a.export_chain()))[0] and (await b.import_transfer_certificate(alpha))[0]
        await _recover(a_binding, private, reason="compromised")
        voided = await a.export_chain()
        assert (await b.import_chain(voided))[0], "premise: the compromise is stored"
        await b.forget_foreign_chain(alpha.origin_ship_did)
        await early_binding.rotate()
        early_chain = await early.export_chain()  # it never anchored Alpha's transfer
        first = await b.import_chain(early_chain)
        again = await b.import_chain(early_chain)
        marks = b.transfer_marks(alpha.did)
    assert first[0] and again[0]
    assert len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(alpha, _NOT_ANCHORED, early_chain, marks[0].judged_at),)
    assert _mark_rows(tmp_path / "b") == [
        _row(alpha, "mark", _void(voided, alpha), voided), _row(alpha, "mark", _NOT_ANCHORED, early_chain),
    ]


async def test_s2bii_m1_marks_are_held_again_after_a_restart_as_their_newest_rows_record(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", duck))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships, "compromised")
        assert (await b.import_chain(chain_r, supersede=True))[0], "premise: the recovery's branch is stored"
        before = (b.transfer_marks(ships.alpha.did), b.transfer_marks(ships.bravo.did))
        await b.stop()
        async with _receiver(tmp_path / "b", duck) as restarted:
            after = (restarted.transfer_marks(ships.alpha.did), restarted.transfer_marks(ships.bravo.did))
            assert (await restarted.forget_foreign_chain(ships.bravo.origin_ship_did)) == len(chain_r)
            assert (await restarted.import_chain(ships.copy_chain))[0], "premise: the copy's chain is stored again"
        async with _receiver(tmp_path / "b", duck) as again:
            cleared = (again.transfer_marks(ships.alpha.did), again.transfer_marks(ships.bravo.did))
    assert len(before[0]) == 1 and len(before[1]) == 1
    assert after == before  # replayed from the log, with no new row at start
    assert cleared == ((), ())  # a clear's row is the newest
    assert [row[3] for row in _mark_rows(tmp_path / "b")] == ["mark", "mark", "clear", "clear"]


async def test_s2bii_m1_an_identity_db_written_without_the_re_check_gains_its_table_and_marks_at_the_first_armed_start(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_MARKS_LOGGER)
    duck = _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        async with _receiver(tmp_path / "b", duck, marks=False) as unarmed:
            ships = await _ships(stack, tmp_path, unarmed)
            chain_r = await _recovered(ships)
            assert (await unarmed.import_chain(chain_r, supersede=True))[0], "premise: identity.db stores the recovery"
        tables = _table_names(tmp_path / "b" / "identity.db")
        async with _receiver(tmp_path / "b", duck) as armed:
            marks = armed.transfer_marks(ships.bravo.did)
    assert "transfer_marks" not in tables, "premise: written without the re-check"
    assert len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(ships.bravo, _NOT_ANCHORED, chain_r, marks[0].judged_at),)
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)]
    assert len(_marked_lines(caplog)) == 1


async def test_s2bii_m1_a_registry_without_the_re_check_leaves_the_marks_untouched_and_the_next_armed_start_corrects_them(
    tmp_path: Path,
) -> None:
    duck = _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        async with _receiver(tmp_path / "b", duck) as armed:
            ships = await _ships(stack, tmp_path, armed)
            chain_r = await _recovered(ships)
            assert (await armed.import_chain(chain_r, supersede=True))[0], "premise: the recovery's branch is stored"
        marked_rows = _mark_rows(tmp_path / "b")
        async with _receiver(tmp_path / "b", duck, marks=False) as unarmed:
            unarmed_marks = unarmed.transfer_marks(ships.bravo.did)
            forgotten = await unarmed.forget_foreign_chain(ships.bravo.origin_ship_did)
            stored = await unarmed.import_chain(ships.copy_chain)
            record = unarmed.get_by_uuid(ships.bravo.agent_uuid)
        untouched = _mark_rows(tmp_path / "b")
        async with _receiver(tmp_path / "b", duck) as rearmed:
            corrected = rearmed.transfer_marks(ships.bravo.did)
    assert marked_rows == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)], "premise: a mark was committed"
    assert unarmed_marks == () and forgotten == len(chain_r) and stored[0] is True and record is not None
    assert untouched == marked_rows  # the registry without the re-check never writes the table
    assert corrected == ()  # the next armed start judges against the chain stored now
    assert [row[3] for row in _mark_rows(tmp_path / "b")] == ["mark", "clear"]


async def test_s2bii_m1_the_marks_and_the_chain_commit_together_or_not_at_all(tmp_path: Path) -> None:
    factory = _SharedFactory()
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring(), connection_factory=factory))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships)

        def state() -> tuple[Any, ...]:
            return (
                b.get_foreign_chain(ships.bravo.origin_ship_did), b.transfer_marks(ships.bravo.did),
                _rows(tmp_path / "b" / "identity.db", "SELECT chain_json FROM foreign_chains"), _mark_rows(tmp_path / "b"),
            )

        factory.shared.fail_prefix = "INSERT INTO transfer_marks"
        with pytest.raises(sqlite3.OperationalError, match="injected statement failure"):
            await b.import_chain(chain_r, supersede=True)
        failed_mark = state()
        factory.shared.fail_commit = True  # the unit's COMMIT fails after its statements ran, the mark's among them
        with pytest.raises(sqlite3.OperationalError, match="COMMIT not completed"):
            await b.import_chain(chain_r, supersede=True)
        failed_commit = state()
        retried = await b.import_chain(chain_r, supersede=True)
        marks = b.transfer_marks(ships.bravo.did)
    before = (ships.copy_chain, (), [(json.dumps(ships.copy_chain),)], [])
    assert failed_mark == before  # memory and identity.db hold what committed: nothing of the failed unit
    assert failed_commit == before  # a unit whose COMMIT failed is rolled back, and memory never held its mark
    assert retried[0] is True and len(marks) == 1
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)]


async def test_s2bii_m1_an_import_cancelled_while_it_commits_holds_its_marks_in_memory_as_committed(tmp_path: Path) -> None:
    factory, duck = _SharedFactory(), _DuckKeyring()
    importing: asyncio.Task[tuple[bool, str]] | None = None
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", duck, connection_factory=factory))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships)
        gate = factory.shared.hold_inflight = asyncio.Event()
        try:
            importing = asyncio.create_task(b.import_chain(chain_r, supersede=True))
            await asyncio.wait_for(factory.held.wait(), 5)  # its COMMIT is queued and running
            importing.cancel()
            await asyncio.wait({importing}, timeout=0.5)
            kept = not importing.done()
            gate.set()
            await asyncio.wait({importing}, timeout=10)
        finally:
            gate.set()
            await _joined(importing, factory.shared.inflight)
        held = (b.get_foreign_chain(ships.bravo.origin_ship_did), b.transfer_marks(ships.bravo.did))
    assert importing is not None and importing.cancelled() and kept  # the cancellation is raised once the unit has ended
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)], "premise: it committed"
    assert held[0] == chain_r and len(held[1]) == 1  # memory holds what committed: the chain and its mark


async def test_s2bii_m1_a_stored_credential_that_names_no_issuer_is_not_judged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_MARKS_LOGGER)
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships)
        other = dict(_vc(ships.bravo), issuer="did:probos:ship-z")
        with contextlib.closing(sqlite3.connect(tmp_path / "b" / "identity.db")) as db:
            db.executemany(
                "INSERT INTO transfer_certificates (did, transfer_timestamp, direction, certificate_hash, "
                "certificate_vc_json) VALUES (?, ?, 'incoming', ?, ?)",
                [
                    ("did:probos:x:1", 1.0, "1" * 64, "not json"),
                    ("did:probos:x:2", 2.0, "2" * 64, "[1, 2]"),
                    ("did:probos:x:3", 3.0, "3" * 64, json.dumps({"type": ["VerifiableCredential"]})),
                    ("did:probos:x:4", 4.0, "4" * 64, json.dumps({"issuer": ["not", "a", "did"]})),
                    ("did:probos:x:5", 5.0, "5" * 64, json.dumps(other)),
                ],
            )
            db.commit()
        imported = await b.import_chain(chain_r, supersede=True)
        rowids = dict(_rows(tmp_path / "b" / "identity.db", "SELECT certificate_hash, rowid FROM transfer_certificates"))
    assert imported[0] is True
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)]  # only ship-a's certificates
    # A-1: each row that cannot be attributed is logged, with why, and fails nothing else; another ship's row is not logged
    lines = _marked_lines(caplog)
    assert len(lines) == 5, lines  # four rows that cannot be attributed, then Bravo's mark
    assert lines[:4] == [
        _unattributed(rowids["1" * 64], "its credential is not JSON (JSONDecodeError)"),
        _unattributed(rowids["2" * 64], "its credential is not a JSON object"),
        _unattributed(rowids["3" * 64], "its credential names no issuer as text"),
        _unattributed(rowids["4" * 64], "its credential names no issuer as text"),
    ]


async def test_s2bii_m1_a_start_whose_re_check_fails_starts_logs_and_reports_the_marks_as_not_known(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_REGISTRY_LOGGER)

    class _FailingAtStart(_SharedFactory):
        async def connect(self, db_path: str) -> Any:
            connection = await super().connect(db_path)
            connection.fail_prefix = "INSERT INTO transfer_marks"  # the start's first mark fails once
            return connection

    duck = _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        async with _receiver(tmp_path / "b", duck, marks=False) as unarmed:
            ships = await _ships(stack, tmp_path, unarmed)
            chain_r = await _recovered(ships)
            assert (await unarmed.import_chain(chain_r, supersede=True))[0], "premise: identity.db stores the recovery"
        async with _receiver(tmp_path / "b", duck, connection_factory=_FailingAtStart()) as started:
            at_start = (started.get_ship_certificate(), started.transfer_marks(ships.bravo.did), _mark_rows(tmp_path / "b"))
            again = await started.import_chain(chain_r)  # the next chain stored loads the marks and judges again
            marks = started.transfer_marks(ships.bravo.did)
    # A-1: this test asserted `at_start[1] == ()` and that the marks "stay as last committed" -- a failed start's unloaded
    # marks shown as none, review round 1's F-R1-2. They are now reported as not known (None) until a unit loads them.
    assert at_start[0] is not None and at_start[1] is None and at_start[2] == []  # started; not known; nothing committed
    assert [line for line in _messages(caplog, _REGISTRY_LOGGER, logging.WARNING) if "at start" in line] == [
        "AD-1198: the stored incoming transfer certificates could not be judged again at start (OperationalError); their "
        "marks are not loaded -- the registry and the agent identity endpoint report them as not known -- until a unit "
        "that reads them commits, as the next chain identity.db stores does, and the next chain stored for each origin "
        "judges its certificates again",
    ]
    assert marks is not None and len(marks) == 1, marks  # one mark, before its fields are compared
    assert again[0] is True and marks == (_mark(ships.bravo, _NOT_ANCHORED, chain_r, marks[0].judged_at),)


async def test_s2bii_m1_transfer_marks_names_only_that_dids_marks_and_none_without_the_re_check(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships, "compromised")
        assert (await b.import_chain(chain_r, supersede=True))[0], "premise: the recovery's branch is stored"
        alpha, bravo, nobody = b.transfer_marks(ships.alpha.did), b.transfer_marks(ships.bravo.did), b.transfer_marks("x")
        unarmed, _ = await stack.enter_async_context(_armed(tmp_path / "unarmed", _DuckKeyring(), instance_id="ship-u"))
        without = unarmed.transfer_marks(ships.bravo.did)
    assert len(alpha) == 1, alpha  # one mark, before its fields are compared
    assert alpha == (_mark(ships.alpha, _void(chain_r, ships.alpha), chain_r, alpha[0].judged_at),)
    assert len(bravo) == 1, bravo  # one mark, before its fields are compared
    assert bravo == (_mark(ships.bravo, _NOT_ANCHORED, chain_r, bravo[0].judged_at),)
    assert nobody == () and without == ()


async def test_s2bii_m1_an_unreadable_stored_row_fails_alone_and_an_import_still_judges_its_ships_certificates(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_MARKS_LOGGER)
    blob = bytes(range(32))  # a certificate hash stored as a BLOB: no certificate's hash is one
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        ships = await _ships(stack, tmp_path, b)
        chain_r = await _recovered(ships)
        rowids = _store_incoming(tmp_path / "b", [
            ("did:probos:z:1", 1.0, "9" * 64, _DEEP),  # another ship's certificate, by its text, which the decoder rejects
            ("did:probos:x:blob", 2.0, blob, json.dumps(_vc(ships.bravo))),  # ship-a's credential under a BLOB hash
        ])
        types = _rows(tmp_path / "b" / "identity.db", "SELECT typeof(certificate_hash) FROM transfer_certificates WHERE did = 'did:probos:x:blob'")
        assert types == [("blob",)], "premise: that row's hash is stored as a BLOB"
        with pytest.raises(RecursionError):
            json.loads(_DEEP)  # premise: the decoder rejects that row (review round 1's F-R1-1)
        imported = await b.import_chain(chain_r, supersede=True)
        stored = b.get_foreign_chain(ships.bravo.origin_ship_did)
        marks = b.transfer_marks(ships.bravo.did)
    assert imported == (True, f"Chain imported: {len(chain_r)} blocks from {ships.bravo.origin_ship_did}")
    assert stored == chain_r  # rows the import cannot read do not fail the import of ship-a's chain
    assert marks is not None and len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(ships.bravo, _NOT_ANCHORED, chain_r, marks[0].judged_at),)
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)]  # neither row is judged
    lines = _marked_lines(caplog)
    assert len(lines) == 3, lines  # the two rows that cannot be attributed, then Bravo's mark
    assert lines[:2] == [
        _unattributed(rowids["9" * 64], "its credential is not JSON (RecursionError)"),
        _unattributed(rowids[blob], "its hash or agent DID is not text"),
    ]
    assert lines[2].startswith(f"AD-1198: the incoming transfer certificate {ships.bravo.certificate_hash} of {ships.bravo.did} ")


async def test_s2bii_m1_at_start_an_unreadable_row_or_stored_chain_fails_alone_and_every_other_ship_is_judged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_MARKS_LOGGER)
    caplog.set_level(logging.WARNING, logger=_REGISTRY_LOGGER)
    duck = _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        async with _receiver(tmp_path / "b", duck, marks=False) as unarmed:
            ships = await _ships(stack, tmp_path, unarmed)
            chain_r = await _recovered(ships)
            assert (await unarmed.import_chain(chain_r, supersede=True))[0], "premise: identity.db stores the recovery"
        rowids = _store_incoming(tmp_path / "b", [
            ("did:probos:z:1", 1.0, "8" * 64, json.dumps(dict(_vc(ships.bravo), issuer=SHIP_Z))),  # a ship-z certificate
            ("did:probos:z:2", 2.0, "9" * 64, _DEEP),  # a row the decoder rejects
        ])
        with contextlib.closing(sqlite3.connect(tmp_path / "b" / "identity.db")) as db:
            db.execute("INSERT INTO foreign_chains (origin_ship_did, chain_json, imported_at) VALUES (?, '[]', 1.0)", (SHIP_Z,))
            db.commit()  # ship-z's stored chain has no head
        with pytest.raises(RecursionError):
            json.loads(_DEEP)  # premise: the decoder rejects that row (review round 1's F-R1-1)
        async with _receiver(tmp_path / "b", duck) as armed:
            z_chain = armed.get_foreign_chain(SHIP_Z)
            marks = armed.transfer_marks(ships.bravo.did)
    assert z_chain == [], "premise: the start judges against ship-z's stored chain, which has no head"
    assert marks is not None and len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(ships.bravo, _NOT_ANCHORED, chain_r, marks[0].judged_at),)
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)]  # ship-z's is not judged
    assert [line for line in _messages(caplog, _REGISTRY_LOGGER, logging.WARNING) if "at start" in line] == []  # committed
    lines = _marked_lines(caplog)
    assert len(lines) == 3, lines  # the row, ship-z's chain, then Bravo's mark
    assert lines[:2] == [
        _unattributed(rowids["9" * 64], "its credential is not JSON (RecursionError)"),
        _unreadable_chain(SHIP_Z, "IndexError"),
    ]
    assert lines[2].startswith(f"AD-1198: the incoming transfer certificate {ships.bravo.certificate_hash} of {ships.bravo.did} ")


async def test_s2bii_m1_a_restart_whose_load_fails_reports_the_marks_as_not_known_and_decides_from_the_committed_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=_REGISTRY_LOGGER)

    class _FailingLoad(_SharedFactory):
        async def connect(self, db_path: str) -> Any:
            connection = await super().connect(db_path)
            connection.fail_prefix = "SELECT certificate_hash, subject_did, origin_ship_did, action"  # the start's load, once
            return connection

    duck = _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        async with _receiver(tmp_path / "b", duck) as b:
            ships = await _ships(stack, tmp_path, b)
            assert (await b.reassign_slot(ships.bravo.agent_uuid, "slot-bravo"))[0], "premise: Bravo holds a slot here"
            chain_r = await _recovered(ships)
            assert (await b.import_chain(chain_r, supersede=True))[0], "premise: the recovery's branch is stored"
        committed = _rows(tmp_path / "b" / "identity.db", f"SELECT {_MARK_COLUMNS}, judged_at FROM transfer_marks ORDER BY seq")
        async with _receiver(tmp_path / "b", duck, connection_factory=_FailingLoad()) as restarted:
            degraded = (restarted.transfer_marks(ships.bravo.did), restarted.transfer_marks(ships.alpha.did))
            record = restarted.get_by_slot("slot-bravo")
            response = await _identity(restarted, "slot-bravo")
            unchanged = await restarted.import_chain(chain_r)  # the chain identity.db stores, again
            healed = (restarted.transfer_marks(ships.bravo.did), _mark_rows(tmp_path / "b"))
            assert (await restarted.forget_foreign_chain(ships.bravo.origin_ship_did)) == len(chain_r)
            supporting = await restarted.import_chain(ships.copy_chain)  # a chain that supports Bravo's transfer again
            cleared = (restarted.transfer_marks(ships.bravo.did), _mark_rows(tmp_path / "b"))
        async with _receiver(tmp_path / "b", duck) as again:
            after_restart = (again.transfer_marks(ships.bravo.did), again.transfer_marks(ships.alpha.did), _mark_rows(tmp_path / "b"))
    clearing = next(
        verdict.reason for verdict in verify_transfer_attestations(
            ships.copy_chain, [(_vc(ships.bravo), ships.bravo.certificate_hash, ships.bravo.did)],
        )
    )
    marked, clear = _row(ships.bravo, "mark", _NOT_ANCHORED, chain_r), _row(ships.bravo, "clear", clearing, ships.copy_chain)
    warnings = [line for line in _messages(caplog, _REGISTRY_LOGGER, logging.WARNING) if "at start" in line]
    assert [row[:-1] for row in committed] == [marked], "premise: one mark committed before the restart"
    assert len(warnings) == 1 and "(OperationalError)" in warnings[0], "premise: the restart's load failed, and only it"
    assert degraded == (None, None)  # not known -- never shown as none (review round 1's F-R1-2)
    assert record is not None and response.status_code == 200, response.text
    assert response.json() == {
        "sovereign_id": ships.bravo.agent_uuid, "did": ships.bravo.did,
        "birth_certificate": json.loads(json.dumps(record.to_verifiable_credential())), "transfer_marks": None,
    }
    held = (_mark(ships.bravo, _NOT_ANCHORED, chain_r, committed[0][-1]),)  # the committed row, as memory holds a mark
    assert unchanged[0] is True and healed == (held, [marked])  # no second row; memory is the committed row
    assert supporting[0] is True
    assert cleared == ((), [marked, clear])  # exactly one clear
    assert after_restart == ((), (), [marked, clear])  # across a restart memory is the committed rows, and it writes none


async def test_s2bii_m1_a_start_that_fails_before_creating_the_table_leaves_the_next_import_to_create_it(
    tmp_path: Path,
) -> None:
    class _FailingCreate(_SharedFactory):
        async def connect(self, db_path: str) -> Any:
            connection = await super().connect(db_path)
            connection.fail_prefix = "CREATE TABLE IF NOT EXISTS transfer_marks"  # the start's first statement, once
            return connection

    duck = _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        async with _receiver(tmp_path / "b", duck, marks=False) as unarmed:
            ships = await _ships(stack, tmp_path, unarmed)
            chain_r = await _recovered(ships)
            assert (await unarmed.import_chain(chain_r, supersede=True))[0], "premise: identity.db stores the recovery"
        async with _receiver(tmp_path / "b", duck, connection_factory=_FailingCreate()) as started:
            at_start = (started.transfer_marks(ships.bravo.did), _table_names(tmp_path / "b" / "identity.db"))
            assert "transfer_marks" not in at_start[1], "premise: the start failed before the table was created"
            again = await started.import_chain(chain_r)  # the next chain stored: it creates the table, loads and judges
            marks = started.transfer_marks(ships.bravo.did)
            tables = _table_names(tmp_path / "b" / "identity.db")
    assert at_start[0] is None  # not known
    assert again[0] is True and "transfer_marks" in tables
    assert marks is not None and len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(ships.bravo, _NOT_ANCHORED, chain_r, marks[0].judged_at),)
    assert _mark_rows(tmp_path / "b") == [_row(ships.bravo, "mark", _NOT_ANCHORED, chain_r)]


# --------------------------------------------------------------------------- #
# M2 -- the wiring and the agent identity endpoint
# --------------------------------------------------------------------------- #


async def test_s2bii_m2_peer_admission_arms_the_re_check_at_boot_and_identity_keys_alone_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.config import FederationConfig, SystemConfig

    monkeypatch.setattr(keyring, "get_keyring", _KeyringProbe(_DuckKeyring()))
    armed = SystemConfig(federation=FederationConfig(
        identity_keys_enabled=True, envelope_signing_enabled=True, peer_admission_enabled=True,
    ))
    keys_only = SystemConfig(federation=FederationConfig(identity_keys_enabled=True))
    tables: dict[str, list[str]] = {}
    for name, config in (("armed", armed), ("keys-only", keys_only)):
        result = await _boot_identity(tmp_path / name, config)
        try:
            tables[name] = _table_names(tmp_path / name / "identity.db")
            assert result.identity_registry.transfer_marks("did:probos:anyone") == ()
        finally:
            await _stop_identity(result)
    assert "transfer_marks" in tables["armed"]
    assert "transfer_marks" not in tables["keys-only"]
    assert set(tables["armed"]) - set(tables["keys-only"]) == {"transfer_marks"}


async def test_s2bii_m2_the_agent_identity_endpoint_shows_the_marks_of_a_marked_foreign_record(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        ships = await _ships(stack, tmp_path, b)
        assert (await b.reassign_slot(ships.bravo.agent_uuid, "slot-bravo"))[0], "premise: Bravo holds a slot here"
        chain_r = await _recovered(ships)
        assert (await b.import_chain(chain_r, supersede=True))[0], "premise: the recovery's branch is stored"
        marks = b.transfer_marks(ships.bravo.did)
        record = b.get_by_slot("slot-bravo")
        response = await _identity(b, "slot-bravo")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "sovereign_id": ships.bravo.agent_uuid, "did": ships.bravo.did,
        "birth_certificate": json.loads(json.dumps(record.to_verifiable_credential())),
        "transfer_marks": [dataclasses.asdict(mark) for mark in marks],
    }
    assert len(marks) == 1


async def test_s2bii_m2_the_agent_identity_endpoint_is_unchanged_for_every_record_without_marks(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        b = await stack.enter_async_context(_receiver(tmp_path / "b", _DuckKeyring()))
        ships = await _ships(stack, tmp_path, b)
        native = await _birth(b, "Delta", instance_id="ship-b")
        assert (await b.reassign_slot(ships.alpha.agent_uuid, "slot-alpha"))[0], "premise: Alpha holds a slot here"
        chain_r = await _recovered(ships)  # a lost key: Alpha's transfer stays supported
        assert (await b.import_chain(chain_r, supersede=True))[0], "premise: the recovery's branch is stored"
        unarmed, _ = await stack.enter_async_context(_armed(tmp_path / "unarmed", _DuckKeyring(), instance_id="ship-u"))
        unarmed_native = await _birth(unarmed, "Echo", instance_id="ship-u")
        responses = {
            "native": await _identity(b, "slot-Delta"),
            "foreign": await _identity(b, "slot-alpha"),
            "unarmed": await _identity(unarmed, "slot-Echo"),
            "missing": await _identity(b, "slot-nobody"),
            "no registry": await _identity(None, "slot-Delta"),
        }
    for name, did in (("native", native.did), ("foreign", ships.alpha.did), ("unarmed", unarmed_native.did)):
        assert responses[name].status_code == 200, (name, responses[name].text)
        assert set(responses[name].json()) == {"sovereign_id", "did", "birth_certificate"} and responses[name].json()["did"] == did
    assert (responses["missing"].status_code, responses["missing"].json()) == (404, {"error": "No birth certificate found"})
    assert (responses["no registry"].status_code, responses["no registry"].json()) == (
        503, {"error": "Identity registry not available"},
    )


# --------------------------------------------------------------------------- #
# M3 -- the production path: a held peer's recovery, the automatic resync, the mark
# --------------------------------------------------------------------------- #


async def _marked_node(stack: contextlib.AsyncExitStack, wire: _Wire, tmp: Path, name: str) -> _Node:
    """``name`` as AD-1197's ``_node`` builds it, with the re-check armed in its registry."""
    duck = _DuckKeyring()
    binding = IdentityKeyBinding(KeyringKeyStore(backend=duck))
    registry = await stack.enter_async_context(_registry(
        tmp / f"{name}-identity", instance_id=name.replace("node", "ship"), key_binding=binding, transfer_marks=TransferMarks(),
    ))
    data_dir = tmp / f"{name}-data"
    data_dir.mkdir()
    inner = MockFederationTransport(name, wire.bus)
    dispatched: list[FederationMessage] = []
    guard, transport = await _wrap(stack, name, inner, binding, data_dir, dispatched, policy=POLICY_REQUIRE)
    return _Node(name, binding, registry, duck, inner, data_dir, guard, transport, dispatched)


async def test_s2bii_m3_a_resync_that_re_anchors_on_a_recovery_marks_the_transfer_accepted_from_the_replaced_branch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_MARKS_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, private, public = await _owner(stack, wire, tmp_path)
        b = await _marked_node(stack, wire, tmp_path, "node-b")
        _, pin_a = await _active_key(a.binding)
        _, pin_b = await _active_key(b.binding)
        await _admit(stack, a, pins={"node-b": pin_b})
        await _admit(stack, b, pins={"node-a": pin_a})
        exchange_a, exchange_b = _exchange(a, {"node-b": pin_b}), _exchange(b, {"node-a": pin_a})
        stack.push_async_callback(exchange_a.stop)
        stack.push_async_callback(exchange_b.stop)
        bridge_a = await _exchange_bridge(stack, a, exchange_a, _RecordingIntentBus("node-a"), peer="node-b")
        bridge_b = await _exchange_bridge(stack, b, exchange_b, _RecordingIntentBus("node-b"), peer="node-a")
        alpha_birth = await _birth(a.registry, "Alpha")
        assert await bridge_b.request_chain("node-a") == await a.registry.export_chain(), "premise: each holds the other"
        b.transport.chain_seam.on_history_gap(exchange_b.history_gap)
        x = await _held_on_copy(wire, a, b, exchange_b, tmp_path, public, stack)
        alpha = await x.registry.issue_transfer_certificate(alpha_birth.agent_uuid, SHIP_B)
        assert (await exchange_b.import_chain_from("node-a", await x.registry.export_chain()))[0], "premise: chain stored"
        assert await exchange_b.import_transfer_from("node-a", alpha) == (True, f"Certificate imported: {alpha.did}")
        assert (await b.registry.reassign_slot(alpha.agent_uuid, "slot-alpha"))[0], "premise: Alpha holds a slot here"
        assert b.registry.transfer_marks(alpha.did) == (), "premise: the copy's chain supports Alpha's transfer"
        await _recover(a.binding, private, reason="lost")
        a_chain = await a.registry.export_chain()
        missed = await bridge_a.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))
        await _until(lambda: b.registry.transfer_marks(alpha.did) != (), what="the mark")
        held = b.transport.chain_seam.held("node-a")
        marks = b.registry.transfer_marks(alpha.did)
        response = await _identity(b.registry, "slot-alpha")
    assert list(missed) == []  # node-b refused the recovered node-a's envelope and resynchronised
    assert held is not None and b.registry.get_foreign_chain(alpha.origin_ship_did) == a_chain  # both holds moved
    assert len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == (_mark(alpha, _NOT_ANCHORED, a_chain, marks[0].judged_at),)
    assert response.status_code == 200 and response.json()["transfer_marks"] == [dataclasses.asdict(marks[0])]
    assert len(_marked_lines(caplog)) == 1
