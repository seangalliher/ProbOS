"""AD-1198 slice 2a (#1135): identity continuity -- the armed identity exchange, and the resync that heals a key-history gap.

Tests are named by subject. m0 pins today's code: a bridge without an identity exchange answers both identity requests
``identity_registry not wired``, byte for byte, and a key-history gap refuses the very chain answer that would heal it.
m1 covers the guard's resync (``EnvelopeGuard.resync``) and its gap listener; m2 the exchange's chain serving and its
sender-bound chain and transfer imports; m3 the resync driver and the chain seam it uses; m4 the wiring (the bridge,
fleet organization, shutdown). The build milestones group them (contract section 5): M1 runs m0 to m3 and the bridge
test, M2 the other two m4 tests. a1 is Amendment A-1 (review round 1): a late resync answer reaches no intent, an armed
import only extends the chain identity.db stores, identity.db holds a resync's chain before its hold is recorded, a
resynchronised hold keeps its pin across a restart, and a failed fleet organization stops what it built.
a2 is Amendment A-2 (review round 2): a chain identity.db stores is relied on only when it verifies in full
(``verified_chain_state``), so a resync or a transfer over an unsigned or corrupted stored snapshot is judged on a
verified chain or refused; the start-up proof checks every block hash and link (``verify_chain_structure``, the
registry's own check); and a cancellation during a failed fleet organization's cleanup skips no stop. Nodes are real
AD-1196 keys over the in-memory duck keyring with real envelope stores
on the mock bus, rebuilt with peer admission through the production ``build_signed_transport``. No test opens a socket,
reaches the real OS keyring (AD-1196's autouse guard is imported, H5) or a live service.

M0 runs on the unmodified base: write this module up to the ``M1`` marker without the slice-2a import block.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.config import FederationConfig, PeerConfig
from probos.federation.admission import PeerAdmission
from probos.federation.bridge import FederationBridge
from probos.federation.envelope import MAX_KEY_EVENTS, POLICY_REQUIRE, POLICY_SIGN, EnvelopeGuard
from probos.federation.router import FederationRouter
from probos.federation_envelope_store import ENVELOPE_DB_NAME, EnvelopeStore
from probos.identity import generate_ship_did
from probos.identity_keys import KeyEvent, keeps_held_key_events
from probos.types import FederationMessage, IntentMessage, NodeSelfModel
from tests.test_ad1196_did_key_binding import _armed, _birth, _DuckKeyring, _new_key  # noqa: F401
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)
from tests.test_ad1197_signed_envelopes import (
    _ENVELOPE_LOGGER,
    _active_key,
    _bridge,
    _node,
    _Node,
    _recorded_key_ids,
    _RecordingIntentBus,
    _rejections,
    _rows,
    _seal,
    _SwitchableSigner,
    _unsigned,
    _Wire,
)
from tests.test_ad1198_peer_admission import _admit

# slice 2a names (M1 onward; omit this block for the M0 run on the unmodified base)
import probos.federation.continuity as continuity_module  # noqa: E402
import probos.federation.envelope as envelope_module  # noqa: E402
from probos.federation.continuity import (  # noqa: E402
    MAX_CHAIN_BLOCKS,
    MAX_CHAIN_BYTES,
    RESYNC_INTERVAL_S,
    IdentityExchange,
    chain_key_history,
    within_chain_bounds,
)
from probos.federation.envelope import CHAIN_REQUEST, CHAIN_RESPONSE  # noqa: E402
from probos.federation.signed_transport import SignedChainSeam  # noqa: E402
import functools  # noqa: E402
import hashlib  # noqa: E402
import probos.federation.signed_transport as signed_transport_module  # noqa: E402
from probos.federation.continuity import stored_key_history  # noqa: E402
from probos.federation.signed_transport import MAX_ENDED_RESYNCS, build_signed_transport  # noqa: E402
from probos.identity import LedgerBlock  # noqa: E402
from probos.federation.continuity import verified_chain_state  # noqa: E402
from probos.identity import AgentIdentityRegistry, verify_chain_structure  # noqa: E402
from probos.identity_keys import verify_chain_signatures  # noqa: E402
from probos.identity_keys import derive_key_state, verify_transfer_attestation  # noqa: E402
from probos.startup.fleet_organization import organize_fleet  # noqa: E402
from probos.startup.results import FleetOrganizationResult  # noqa: E402
from probos.startup.shutdown import shutdown  # noqa: E402
from tests.fixtures.runtime_lifecycle import BareRuntime, RecordedService  # noqa: E402
from tests.test_ad1197_envelope_wiring import _nats_bus, _RecordingIntentBus as _WiringIntentBus  # noqa: E402
from tests.test_ad1198_admission_wiring import _admission_config  # noqa: E402

_CONTINUITY_LOGGER = "probos.federation.continuity"
_RESYNC_REFUSED = (
    "AD-1198: chain response from %r not admitted for a resync (%s); the key history held for it is unchanged"
)
_NOT_WIRED_CHAIN = {"blocks": [], "error": "identity_registry not wired"}
_GAP = MAX_KEY_EVENTS + 1  # rotations a holder misses to refuse its sender for a key history gap


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


async def _holder(stack: contextlib.AsyncExitStack, tmp: Path, *, pins: dict[str, str]) -> tuple[EnvelopeGuard, Path]:
    """Node-b's armed guard with peer admission over a fresh store (the slice-1 pattern); and its store path."""
    _, signer = await stack.enter_async_context(_armed(tmp / "holder-identity", _DuckKeyring(), instance_id="ship-b"))
    store_dir = tmp / "holder-data"
    store_dir.mkdir()
    guard = EnvelopeGuard(
        signer=signer, store=EnvelopeStore(store_dir / ENVELOPE_DB_NAME), local_node_id="node-b",
        policy=POLICY_REQUIRE, identity_policy=PeerAdmission(local_node_id="node-b", pins=pins),
    )
    stack.push_async_callback(guard.stop)
    await guard.start()
    return guard, store_dir / ENVELOPE_DB_NAME


async def _rotate(node: _Node, times: int) -> None:
    for _ in range(times):
        await node.binding.rotate()


async def _answer(node: _Node, target: str, *, blocks: list[dict[str, Any]] | None = None) -> FederationMessage:
    """``node``'s chain answer for ``target``, sealed by its own AD-1197 guard, carrying its exported chain."""
    chain = await node.registry.export_chain() if blocks is None else blocks
    sealed = await node.guard.seal(
        FederationMessage(type="chain_response", source_node=node.name, message_id="r1", payload={"blocks": chain}, timestamp=2.0),
        target,
    )
    assert sealed is not None and sealed.auth is not None, "premise: the ship key signs"
    return sealed


async def _pinned_pair(
    stack: contextlib.AsyncExitStack, wire: _Wire, tmp: Path,
) -> tuple[_Node, _Node, str, str]:
    """Node-a and node-b, each rebuilt with peer admission pinning the other; their public keys."""
    a = await _node(stack, wire, tmp, "node-a")
    b = await _node(stack, wire, tmp, "node-b")
    _, pin_a = await _active_key(a.binding)
    _, pin_b = await _active_key(b.binding)
    await _admit(stack, a, pins={"node-b": pin_b})
    await _admit(stack, b, pins={"node-a": pin_a})
    return a, b, pin_a, pin_b


def _exchange(node: _Node, pins: dict[str, str], *, timeout_ms: int = 2_000) -> IdentityExchange:
    return IdentityExchange(
        node_id=node.name, registry=node.registry, seam=node.transport.chain_seam,
        admission=PeerAdmission(local_node_id=node.name, pins=pins), timeout_ms=timeout_ms,
    )


async def _exchange_bridge(
    stack: contextlib.AsyncExitStack, node: _Node, exchange: IdentityExchange | None, intent_bus: Any, *, peer: str,
) -> FederationBridge:
    """The bridge as fleet organization builds it while armed: over the node's armed transport, with ``exchange``."""
    bridge = FederationBridge(
        node_id=node.name, transport=node.transport, router=FederationRouter(), intent_bus=intent_bus,
        config=FederationConfig(
            enabled=True, node_id=node.name, forward_timeout_ms=2_000, gossip_interval_seconds=1_000.0,
            peers=[PeerConfig(node_id=peer, address="tcp://127.0.0.1:65530")],
        ),
        self_model_fn=lambda: NodeSelfModel(node_id=node.name), identity_exchange=exchange,
    )
    stack.push_async_callback(bridge.stop)
    await bridge.start()
    return bridge


def _resync_refusals(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.args[1]  # type: ignore[index]
        for record in caplog.records
        if record.name == _ENVELOPE_LOGGER and record.msg == _RESYNC_REFUSED
    ]


def _messages(caplog: pytest.LogCaptureFixture, logger_name: str, level: int) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == logger_name and record.levelno == level]


async def _until(predicate: Any, *, what: str) -> None:
    """A bounded wait for an asynchronous effect: never a bare sleep."""
    for _ in range(2_000):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


# --------------------------------------------------------------------------- #
# M0 -- today's code (passes on the unmodified base)
# --------------------------------------------------------------------------- #


async def test_s2a_m0_a_bridge_without_an_identity_exchange_answers_identity_registry_not_wired(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        _, pin_a = await _active_key(a.binding)
        _, pin_b = await _active_key(b.binding)
        await _admit(stack, a, pins={"node-b": pin_b})
        await _admit(stack, b, pins={"node-a": pin_a})
        await _bridge(stack, "node-a", a.transport, _RecordingIntentBus("node-a"), peers=("node-b",))
        bridge_b = await _bridge(stack, "node-b", b.transport, _RecordingIntentBus("node-b"), peers=("node-a",))
        troi = await _birth(b.registry, "Troi", instance_id="ship-b")
        xfer = await b.registry.issue_transfer_certificate(troi.agent_uuid, generate_ship_did("ship-a"))
        before = len(wire.sent)

        blocks = await bridge_b.request_chain("node-a")
        moved = await bridge_b.request_transfer("node-a", xfer, await b.registry.export_chain())

        answers = [message for target, message in wire.sent[before:] if target == "node-b" and message.type != "chain_request"]
        assert blocks == []
        assert moved == (False, "identity_registry not wired")
        assert [(message.type, message.payload) for message in answers] == [
            ("chain_response", _NOT_WIRED_CHAIN),
            ("transfer_response", {"accepted": False, "message": "identity_registry not wired", "agent_uuid": None}),
        ]
        assert all(message.auth is not None for message in answers)  # signed: the armed seam carried them
        assert a.registry.get_foreign_chain(generate_ship_did("ship-b")) is None


async def test_s2a_m0_a_key_history_gap_refuses_the_chain_answer_that_would_heal_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        _, pin_a = await _active_key(a.binding)
        guard, store = await _holder(stack, tmp_path, pins={"node-a": pin_a})
        assert await guard.admit(await _seal(a, "node-b"))  # premise: node-b holds node-a at its inception
        await _rotate(a, _GAP)
        answer = await _answer(a, "node-b")
        held_rows = _rows(store)["senders"]

        assert await guard.admit(answer) is False

        assert _rejections(caplog)[-1] == ("chain_response", "node-a", "key history gap")
        assert _rows(store)["senders"] == held_rows
        blocks = answer.payload["blocks"]
        history = tuple(
            KeyEvent(index=block["index"], payload=block["attestation"]["event"],
                     signatures=block["attestation"]["signatures"], digest=block["certificate_hash"])
            for block in blocks if (block.get("attestation") or {}).get("kind") == "key_event"
        )
        assert len(history) == _GAP + 1
        held_run = tuple(
            KeyEvent(index=event["index"], payload=event["event"], signatures=event["signatures"], digest="")
            for event in json.loads(_rows_events(store, "node-a"))
        )
        assert keeps_held_key_events(held_run, history, carried_head=_GAP) == (True, "keeps")  # what a resync can use


def _rows_events(store: Path, source: str) -> str:
    import sqlite3

    with contextlib.closing(sqlite3.connect(store)) as db:
        return str(db.execute("SELECT key_events_json FROM envelope_senders WHERE source_node = ?", (source,)).fetchone()[0])


# --------------------------------------------------------------------------- #
# M1 -- the guard's resync and its gap listener
# --------------------------------------------------------------------------- #


async def test_s2a_m1_resync_admits_a_chain_answer_across_the_gap_and_records_every_key_it_introduced(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        _, pin_a = await _active_key(a.binding)
        guard, store = await _holder(stack, tmp_path, pins={"node-a": pin_a})
        assert await guard.admit(await _seal(a, "node-b"))
        await _rotate(a, _GAP)
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])
        assert [event.payload["seq"] for event in history] == list(range(_GAP + 1))  # premise: inception and 33 rotations
        windows = _rows(store)["windows"]

        assert await guard.resync(answer, history) is True

        held = guard.held("node-a")
        assert held is not None and held.state.seq == _GAP
        assert [event.payload["seq"] for event in held.events] == list(range(2, _GAP + 1))  # the newest 32
        assert sorted(_recorded_key_ids(store, "node-a")) == sorted(event.payload["key"]["kid"] for event in history)
        assert len(_recorded_key_ids(store, "node-a")) == _GAP + 1  # the key seq 1 introduced too, older than the hold
        assert _rows(store)["senders"] == [("node-a", history[0].payload["did"], _GAP, history[-1].digest)]
        assert _rows(store)["windows"] != windows  # the answer was recorded in its replay window
        assert await guard.admit(await _seal(a, "node-b")) is True  # node-a is admitted again
        assert await guard.admit(answer) is False and _rejections(caplog)[-1][2] == "duplicate"
        assert await guard.resync(answer, history) is False and _resync_refusals(caplog) == ["duplicate"]


async def test_s2a_m1_resync_refuses_what_it_cannot_prove_and_changes_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        _, pin_a = await _active_key(a.binding)
        guard, store = await _holder(stack, tmp_path, pins={"node-a": pin_a})
        assert await guard.admit(await _seal(a, "node-b"))
        await _rotate(a, _GAP)
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])
        rows = _rows(store)
        fresh_dir = tmp_path / "fresh"
        fresh_dir.mkdir()
        fresh, fresh_store = await _holder(stack, fresh_dir, pins={"node-a": pin_a})
        plain = EnvelopeGuard(
            signer=SimpleNamespace(key_status="active"), store=EnvelopeStore(tmp_path / "plain.db"),
            local_node_id="node-b", policy=POLICY_REQUIRE,
        )
        stack.push_async_callback(plain.stop)
        await plain.start()
        forked = (dataclasses.replace(history[0], signatures={**history[0].signatures, "new": history[1].signatures["new"]}), *history[1:])
        altered = dataclasses.replace(answer, payload={"blocks": answer.payload["blocks"][:-1]})

        refused = [
            await plain.resync(answer, history),  # no peer admission: AD-1197 alone never resyncs
            await guard.resync(dataclasses.replace(answer, type="intent_response"), history),
            await fresh.resync(answer, history),  # nothing held for node-a: a first contact carries its own run
            await guard.resync(answer, history[:-1]),  # the history ends before the head the answer was signed under
            await guard.resync(answer, forked),  # the held event is changed
            await guard.resync(altered, history),  # the body is not what was signed
            await guard.resync(answer, ("not a key event",)),  # type: ignore[arg-type]
        ]
        monkeypatch.setattr(envelope_module, "MAX_HELD_KEY_IDS", _GAP)
        refused.append(await guard.resync(answer, history))  # 34 key ids past a bound of 33
        await guard.stop()
        refused.append(await guard.resync(answer, history))  # a stopped guard resyncs nothing

        assert refused == [False] * 9
        assert _resync_refusals(caplog) == [
            "not armed", "topic", "not held", "stale key", "held history", "signature", "malformed (AttributeError)",
            "key history too long", "not armed",
        ]
        assert _rows(store) == rows
        held = guard.held("node-a")
        assert held is not None and held.state.seq == 0
        assert fresh.held("node-a") is None and _rows(fresh_store)["senders"] == []


async def test_s2a_m1_a_cancelled_resync_propagates_and_changes_nothing(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        _, pin_a = await _active_key(a.binding)
        _, signer = await stack.enter_async_context(_armed(tmp_path / "holder-identity", _DuckKeyring(), instance_id="ship-b"))
        store = _PausingStore(tmp_path / ENVELOPE_DB_NAME)
        guard = EnvelopeGuard(
            signer=signer, store=store, local_node_id="node-b", policy=POLICY_REQUIRE,
            identity_policy=PeerAdmission(local_node_id="node-b", pins={"node-a": pin_a}),
        )
        stack.push_async_callback(guard.stop)
        await guard.start()
        assert await guard.admit(await _seal(a, "node-b"))
        await _rotate(a, _GAP)
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])
        rows = _rows(tmp_path / ENVELOPE_DB_NAME)
        store.gate.clear()
        store.paused.clear()

        pending = asyncio.create_task(guard.resync(answer, history))
        await store.paused.wait()
        pending.cancel()

        with pytest.raises(asyncio.CancelledError):
            await pending
        held = guard.held("node-a")
        assert held is not None and held.state.seq == 0
        assert _rows(tmp_path / ENVELOPE_DB_NAME) == rows
        store.gate.set()
        assert await guard.resync(answer, history) is True  # the lock was released: the same answer still resyncs


class _PausingStore(EnvelopeStore):
    """An envelope store whose ``key_ids`` waits at a gate, so a resync can be cancelled before it records.

    AD-1198 A-1 (slice 2b-i) moved the gate here from ``record``: a store write that has begun is now waited for -- to
    its end, or for at most ``STORE_WRITE_SETTLE_S`` (A-2) -- before a cancellation is raised (the a1 and a2 tests of
    ``tests/test_ad1198_fork_resolution.py``), so "changes nothing" holds for a cancellation that arrives before the
    write. The test's assertions are unchanged.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.paused = asyncio.Event()
        self.gate = asyncio.Event()
        self.gate.set()

    async def key_ids(self, source: str) -> frozenset[str]:
        self.paused.set()
        await self.gate.wait()
        return await super().key_ids(source)


async def test_s2a_m1_a_key_history_gap_tells_the_listener_and_a_duplicate_or_an_unconfigured_source_does_not(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    # AD-1198 slice 2b renamed this test from test_s2a_m1_only_a_key_history_gap_tells_the_listener: a held source's held
    # history or stale key now tells the listener too (tests/test_ad1198_fork_resolution.py); its assertions are unchanged.
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        c = await _node(stack, wire, tmp_path, "node-c")
        _, pin_a = await _active_key(a.binding)
        guard, _ = await _holder(stack, tmp_path, pins={"node-a": pin_a})
        told: list[str] = []
        guard.on_history_gap(told.append)
        first = await _seal(a, "node-b")
        assert await guard.admit(first) is True
        assert guard.held("node-a") is not None and guard.held("node-c") is None

        assert await guard.admit(first) is False  # a duplicate
        assert await guard.admit(await _seal(c, "node-b")) is False  # an unconfigured source
        assert told == []
        await _rotate(a, _GAP)
        gapped = await _seal(a, "node-b")
        assert await guard.admit(gapped) is False
        assert await guard.admit(await _seal(a, "node-b")) is False
        assert told == ["node-a", "node-a"]  # every gap is told; the exchange keeps one resync at a time
        guard.on_history_gap(None)
        assert await guard.admit(await _seal(a, "node-b")) is False
        assert told == ["node-a", "node-a"]
        assert [reason for *_, reason in _rejections(caplog)] == [
            "duplicate", "unconfigured source", "key history gap", "key history gap", "key history gap",
        ]


# --------------------------------------------------------------------------- #
# M2 -- the exchange: chain serving and sender-bound imports
# --------------------------------------------------------------------------- #


def test_s2a_m2_a_chain_is_bounded_to_the_block_and_to_the_byte() -> None:
    assert (MAX_CHAIN_BLOCKS, MAX_CHAIN_BYTES, RESYNC_INTERVAL_S) == (1_024, 917_504, 60.0)
    assert within_chain_bounds([0] * MAX_CHAIN_BLOCKS) is True
    assert within_chain_bounds([0] * (MAX_CHAIN_BLOCKS + 1)) is False
    exact = ["x" * (MAX_CHAIN_BYTES - 4)]
    assert len(json.dumps(exact)) == MAX_CHAIN_BYTES  # premise: exactly the byte bound
    assert within_chain_bounds(exact) is True
    assert within_chain_bounds(["x" * (MAX_CHAIN_BYTES - 3)]) is False
    assert within_chain_bounds([]) is False
    assert within_chain_bounds({"blocks": [0]}) is False
    assert within_chain_bounds([object()]) is False


async def test_s2a_m2_the_exchange_serves_this_ships_chain_to_a_pinned_peer_within_its_bounds_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, pin_b = await _pinned_pair(stack, wire, tmp_path)
        exchange = _exchange(a, {"node-b": pin_b, "node-c": ""})
        exported = await a.registry.export_chain()

        assert await exchange.for_sender("node-b").export_chain() == exported
        assert await exchange.for_sender("node-c").export_chain() == []  # configured but not pinned
        assert await exchange.for_sender("node-z").export_chain() == []  # not configured
        assert exchange.refusal_counts == {"unpinned peer": 2}
        size = len(json.dumps(exported))
        monkeypatch.setattr(continuity_module, "MAX_CHAIN_BYTES", size - 1)
        assert await exchange.for_sender("node-b").export_chain() == []
        assert any("is not served to 'node-b'" in line for line in _messages(caplog, _CONTINUITY_LOGGER, logging.WARNING))
        monkeypatch.setattr(continuity_module, "MAX_CHAIN_BYTES", size)
        assert await exchange.for_sender("node-b").export_chain() == exported

        await _exchange_bridge(stack, a, exchange, _RecordingIntentBus("node-a"), peer="node-b")
        bridge_b = await _bridge(stack, "node-b", b.transport, _RecordingIntentBus("node-b"), peers=("node-a",))
        assert await bridge_b.request_chain("node-a") == exported  # over the armed seam, signed both ways


async def test_s2a_m2_a_transfer_imports_its_senders_own_chain_and_certificate(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        bridge_a = await _bridge(stack, "node-a", a.transport, _RecordingIntentBus("node-a"), peers=("node-b",))
        await _exchange_bridge(stack, b, _exchange(b, {"node-a": pin_a}), _RecordingIntentBus("node-b"), peer="node-a")
        troi = await _birth(a.registry, "Troi", instance_id="ship-a")
        ship_b = b.registry.get_ship_certificate()
        assert ship_b is not None
        xfer = await a.registry.issue_transfer_certificate(troi.agent_uuid, ship_b.ship_did)
        chain = await a.registry.export_chain()

        accepted, message = await bridge_a.request_transfer("node-b", xfer, chain)

        assert (accepted, message) == (True, f"Certificate imported: {troi.did}")
        arrived = b.registry.get_by_uuid(troi.agent_uuid)
        assert arrived is not None and (arrived.did, arrived.vessel_name) == (troi.did, "Ship-A")
        assert [row["direction"] for row in await b.registry.get_transfer_certificates_for(troi.did)] == ["incoming"]
        assert b.registry.get_foreign_chain(xfer.origin_ship_did) == chain


async def test_s2a_m2_a_chain_or_certificate_that_is_not_the_senders_own_is_refused_and_nothing_is_stored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        c = await _node(stack, wire, tmp_path, "node-c")
        _, pin_c = await _active_key(c.binding)
        exchange = _exchange(b, {"node-a": pin_a, "node-c": pin_c})
        unpinned = _exchange(b, {"node-a": ""})
        a_did = (await a.binding.status())["did"]
        stale = await a.registry.export_chain()  # node-a's chain at its inception
        await a.binding.rotate()
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # node-b now holds node-a at key seq 1
        assert b.transport.chain_seam.held("node-a") is not None  # premise
        chain = await a.registry.export_chain()
        stripped = [{k: v for k, v in block.items() if k != "attestation"} for block in chain]
        relinked = [dict(block) for block in chain]
        relinked[1] = {**relinked[1], "block_hash": "0" * 64}
        troi = await _birth(a.registry, "Troi", instance_id="ship-a")
        signed_birth = await a.registry.export_chain()
        misattested = [dict(block) for block in signed_birth]
        misattested[-1] = {**misattested[-1], "attestation": {**misattested[-1]["attestation"], "jws": signed_birth[1]["attestation"]["signatures"]["new"]}}
        ship_b = b.registry.get_ship_certificate()
        assert ship_b is not None
        for_b = await a.registry.issue_transfer_certificate(troi.agent_uuid, ship_b.ship_did)
        for_x = await a.registry.issue_transfer_certificate(troi.agent_uuid, generate_ship_did("ship-x"))
        worf = await _birth(c.registry, "Worf", instance_id="ship-c")
        from_c = await c.registry.issue_transfer_certificate(worf.agent_uuid, ship_b.ship_did)
        monkeypatch.setattr(continuity_module, "MAX_CHAIN_BLOCKS", len(chain) - 1)
        over = await exchange.import_chain_from("node-a", chain)
        monkeypatch.setattr(continuity_module, "MAX_CHAIN_BLOCKS", 1_024)

        outcomes = [
            over,
            await unpinned.import_chain_from("node-a", chain),
            await exchange.import_chain_from("node-c", await c.registry.export_chain()),  # node-c was never held
            await exchange.import_chain_from("node-a", stripped),
            await exchange.import_chain_from("node-a", relinked),
            await exchange.import_chain_from("node-a", [1, 2]),
            await exchange.import_chain_from("node-a", misattested),
            await exchange.import_chain_from("node-a", await c.registry.export_chain()),
            await exchange.import_chain_from("node-a", stale),
            await unpinned.import_transfer_from("node-a", for_b),
            await exchange.import_transfer_from("node-a", from_c),
            await exchange.import_transfer_from("node-a", for_x),
        ]

        reasons = [
            "over the bounds", "unpinned peer", "not held", "unverified chain", "unverified chain", "unverified chain",
            "unverified chain", "not the sender's chain", "stale key", "unpinned peer", "not the sender's ship",
            "not for this ship",
        ]
        assert outcomes == [(False, f"identity exchange refused ({reason})") for reason in reasons]
        assert b.registry.get_foreign_chain(a_did) is None
        assert b.registry.get_by_uuid(troi.agent_uuid) is None and b.registry.get_by_uuid(worf.agent_uuid) is None
        bridge_a = await _bridge(stack, "node-a", a.transport, _RecordingIntentBus("node-a"), peers=("node-b",))
        await _exchange_bridge(stack, b, _exchange(b, {"node-a": pin_a}), _RecordingIntentBus("node-b"), peer="node-a")
        moved = await bridge_a.request_transfer("node-b", from_c, await c.registry.export_chain())
        assert moved == (False, "chain rejected: identity exchange refused (not the sender's chain)")
        assert b.registry.get_by_uuid(worf.agent_uuid) is None
        await a.binding.reincept(reason="lost", compromised_after_index=None)  # last: node-b now refuses node-a's envelopes
        reincepted = await a.registry.export_chain()
        assert await exchange.import_chain_from("node-a", reincepted) == (False, "identity exchange refused (pin (continuity))")
        assert exchange.refusal_counts["unverified chain"] == 4 and unpinned.refusal_counts == {"unpinned peer": 2}


# --------------------------------------------------------------------------- #
# M3 -- the resync driver and the chain seam
# --------------------------------------------------------------------------- #


class _Requests:
    """A wrapped transport whose directed requests are recorded and answered with ``answer``."""

    def __init__(self, node_id: str, answer: FederationMessage | None) -> None:
        self.node_id = node_id
        self.answer = answer
        self.requests: list[FederationMessage] = []

    async def request_peer(self, peer_node_id: str, message: FederationMessage, timeout_ms: int) -> FederationMessage | None:
        self.requests.append(message)
        return self.answer


async def test_s2a_m3_the_chain_seam_asks_only_a_pinned_peer_and_returns_only_an_admitted_answer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        _, pin_a = await _active_key(a.binding)
        guard, _ = await _holder(stack, tmp_path, pins={"node-a": pin_a})
        assert await guard.admit(await _seal(a, "node-b"))
        await _rotate(a, _GAP)
        answer = await _answer(a, "node-b")
        history = chain_key_history(answer.payload["blocks"])
        admission = PeerAdmission(local_node_id="node-b", pins={"node-a": pin_a, "node-c": ""})
        request = FederationMessage(type=CHAIN_REQUEST, source_node="node-b", payload={})

        async def full(_answer: FederationMessage) -> tuple[KeyEvent, ...] | None:
            return history

        async def short(_answer: FederationMessage) -> tuple[KeyEvent, ...] | None:
            return history[:-1]

        async def none(_answer: FederationMessage) -> tuple[KeyEvent, ...] | None:
            return None

        quiet = _Requests("node-b", answer)
        unsigned = _Requests("node-b", dataclasses.replace(answer, auth=None))
        silent = _Requests("node-b", None)
        assert await SignedChainSeam(quiet, guard, None).request_resync("node-a", request, 50, full) is None
        assert await SignedChainSeam(quiet, guard, admission).request_resync("node-c", request, 50, full) is None
        intent = dataclasses.replace(request, type="intent_request")
        assert await SignedChainSeam(quiet, guard, admission).request_resync("node-a", intent, 50, full) is None
        assert quiet.requests == []  # nothing asked of an unpinned peer, without admission, or for another topic
        assert await SignedChainSeam(silent, guard, admission).request_resync("node-a", request, 50, full) is None
        assert await SignedChainSeam(unsigned, guard, admission).request_resync("node-a", request, 50, full) is None
        assert admission.refusal_counts == {"unsigned from a pinned peer": 1}
        assert await SignedChainSeam(quiet, guard, admission).request_resync("node-a", request, 50, none) is None
        assert await SignedChainSeam(quiet, guard, admission).request_resync("node-a", request, 50, short) is None
        assert _resync_refusals(caplog) == ["stale key"]
        held = guard.held("node-a")
        assert held is not None and held.state.seq == 0  # nothing above moved the hold
        sent = quiet.requests[-1]
        assert (sent.type, sent.source_node, sent.auth is not None, sent.auth["target"]) == (CHAIN_REQUEST, "node-b", True, "node-a")

        assert await SignedChainSeam(quiet, guard, admission).request_resync("node-a", request, 50, full) is answer

        held = guard.held("node-a")
        assert held is not None and held.state.seq == _GAP


async def test_s2a_m3_a_chain_seam_that_cannot_sign_sends_nothing(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN, signer=_SwitchableSigner)
        b.signer.off = True
        quiet = _Requests("node-b", None)
        admission = PeerAdmission(local_node_id="node-b", pins={"node-a": _new_key().public})
        request = FederationMessage(type=CHAIN_REQUEST, source_node="node-b", payload={})

        async def full(_answer: FederationMessage) -> tuple[KeyEvent, ...] | None:
            raise AssertionError("no answer may be judged")

        assert await SignedChainSeam(quiet, b.guard, admission).request_resync("node-a", request, 50, full) is None
        assert quiet.requests == []  # under 'sign' an unsignable resync request is not sent unsigned


async def test_s2a_m3_a_key_history_gap_heals_through_one_automatic_resync(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, pin_b = await _pinned_pair(stack, wire, tmp_path)
        exchange_a = _exchange(a, {"node-b": pin_b})
        exchange_b = _exchange(b, {"node-a": pin_a})
        stack.push_async_callback(exchange_a.stop)
        stack.push_async_callback(exchange_b.stop)
        b.transport.chain_seam.on_history_gap(exchange_b.history_gap)
        bus_b = _RecordingIntentBus("node-b")
        bridge_a = await _exchange_bridge(stack, a, exchange_a, _RecordingIntentBus("node-a"), peer="node-b")
        bridge_b = await _exchange_bridge(stack, b, exchange_b, bus_b, peer="node-a")
        assert await bridge_b.request_chain("node-a") == await a.registry.export_chain()  # each now holds the other
        a_did = (await a.binding.status())["did"]
        assert b.registry.get_foreign_chain(a_did) is None
        await _rotate(a, _GAP)

        missed = await bridge_a.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))
        await _until(lambda: (held := b.transport.chain_seam.held("node-a")) is not None and held.state.seq == _GAP, what="the resync")
        await _until(lambda: b.registry.get_foreign_chain(a_did) is not None, what="identity.db to follow the hold")
        answered = await bridge_a.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))

        assert list(missed) == [] and bus_b.broadcasts[:-1] == []  # the gap refused the first intent
        assert [result.result for result in answered] == ["done by node-b"] and len(bus_b.broadcasts) == 1
        assert b.registry.get_foreign_chain(a_did) == await a.registry.export_chain()  # identity.db followed the hold
        assert _messages(caplog, _CONTINUITY_LOGGER, logging.INFO) == [
            f"AD-1198: resynchronised the key history held for 'node-a' from its chain (key seq {_GAP})",
        ]


class _FakeSeam:
    """A chain seam whose resync requests are recorded and held until released."""

    def __init__(self, answer: FederationMessage | None = None, *, raises: BaseException | None = None) -> None:
        self.answer = answer
        self.raises = raises
        self.calls: list[tuple[str, str, str, int]] = []
        self.release = asyncio.Event()
        self.listener: Any = "unset"

    def held(self, source: str) -> Any:
        return None

    def on_history_gap(self, listener: Any) -> None:
        self.listener = listener

    async def request_resync(
        self, peer_node_id: str, request: FederationMessage, timeout_ms: int, history_of: Any, before_record: Any = None,
    ) -> Any:
        self.calls.append((peer_node_id, request.type, request.source_node, timeout_ms))
        await self.release.wait()
        if self.raises is not None:
            raise self.raises
        return self.answer


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_s2a_m3_resync_is_single_flight_and_waits_its_interval_for_each_pinned_peer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    seam = _FakeSeam()
    now = [1_000.0]
    exchange = IdentityExchange(
        node_id="node-b", registry=SimpleNamespace(), seam=seam,
        admission=PeerAdmission(local_node_id="node-b", pins={"node-a": _new_key().public, "node-c": ""}),
        timeout_ms=750, clock=lambda: now[0],
    )

    for _ in range(3):
        exchange.history_gap("node-a")
    exchange.history_gap("node-c")  # configured, not pinned
    exchange.history_gap("node-z")  # not configured
    await _settle()
    assert seam.calls == [("node-a", CHAIN_REQUEST, "node-b", 750)]
    now[0] += 2 * RESYNC_INTERVAL_S  # the first resync is still running long after its interval
    exchange.history_gap("node-a")
    await _settle()
    assert len(seam.calls) == 1  # never two resyncs of one peer at once
    seam.release.set()
    await _settle()
    exchange.history_gap("node-a")  # the first ended; its interval has passed
    await _settle()
    assert len(seam.calls) == 2
    second = now[0]
    now[0] = second + RESYNC_INTERVAL_S - 0.001
    exchange.history_gap("node-a")
    await _settle()
    assert len(seam.calls) == 2
    now[0] = second + RESYNC_INTERVAL_S
    exchange.history_gap("node-a")
    await _settle()
    assert len(seam.calls) == 3
    await exchange.stop()
    now[0] += 10 * RESYNC_INTERVAL_S
    exchange.history_gap("node-a")
    await _settle()

    assert len(seam.calls) == 3 and seam.listener is None
    assert _messages(caplog, _CONTINUITY_LOGGER, logging.WARNING)[0] == (
        "AD-1198: no resync of 'node-a': no admitted chain answer; its envelopes stay refused until a later attempt"
    )


async def test_s2a_m3_a_failed_resync_is_logged_and_leaves_the_hold_as_it_was(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_CONTINUITY_LOGGER)
    failing = _FakeSeam(raises=RuntimeError("federation_transport_closed"))
    failing.release.set()
    exchange = IdentityExchange(
        node_id="node-b", registry=SimpleNamespace(), seam=failing,
        admission=PeerAdmission(local_node_id="node-b", pins={"node-a": _new_key().public}), timeout_ms=50,
    )
    exchange.history_gap("node-a")
    await _settle()
    assert _messages(caplog, _CONTINUITY_LOGGER, logging.WARNING) == [
        "AD-1198: the resync of 'node-a' failed (RuntimeError); its envelopes stay refused until a later attempt",
    ]
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, pin_b = await _pinned_pair(stack, wire, tmp_path)
        c = await _node(stack, wire, tmp_path, "node-c")
        exchange_b = _exchange(b, {"node-a": pin_a}, timeout_ms=500)
        stack.push_async_callback(exchange_b.stop)
        await _exchange_bridge(stack, a, None, _RecordingIntentBus("node-a"), peer="node-b")  # answers "not wired"
        bridge_b = await _exchange_bridge(stack, b, exchange_b, _RecordingIntentBus("node-b"), peer="node-a")
        assert await bridge_b.request_chain("node-a") == []  # premise: node-b holds node-a; node-a serves nothing
        await _rotate(a, _GAP)

        assert await exchange_b.resync("node-a") is False

        held = b.transport.chain_seam.held("node-a")
        assert held is not None and held.state.seq == 0
        assert exchange_b.refusal_counts == {"over the bounds": 1}  # "identity_registry not wired" carries no chain
        exchange_c = _exchange(a, {"node-b": pin_b})
        exchange_c.for_sender = lambda sender: SimpleNamespace(export_chain=c.registry.export_chain)  # type: ignore[method-assign]
        await _exchange_bridge(stack, a, exchange_c, _RecordingIntentBus("node-a"), peer="node-b")  # serves node-c's chain
        assert await exchange_b.resync("node-a") is False
        assert exchange_b.refusal_counts == {"over the bounds": 1, "not the sender's chain": 1}
        held = b.transport.chain_seam.held("node-a")
        assert held is not None and held.state.seq == 0


async def test_s2a_a1_a_resync_whose_chain_identity_db_refuses_records_no_hold(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange_b, _ = await _resync_pair(stack, wire, tmp_path)
        a_did = (await a.binding.status())["did"]
        await _rotate(a, _GAP)
        before = _rows(b.store_path)
        asked: list[tuple[int, int]] = []

        async def refusing(blocks: list[dict[str, Any]]) -> tuple[bool, str]:
            held = b.transport.chain_seam.held("node-a")
            asked.append((len(blocks), -1 if held is None else held.state.seq))
            return False, "Registry not started"

        async def failing(blocks: list[dict[str, Any]]) -> tuple[bool, str]:
            raise RuntimeError("disk I/O error")

        monkeypatch.setattr(b.registry, "import_chain", refusing)
        refused = await exchange_b.resync("node-a")
        monkeypatch.setattr(b.registry, "import_chain", failing)
        failed = await exchange_b.resync("node-a")

        held = b.transport.chain_seam.held("node-a")
        assert (refused, failed) == (False, False)
        assert asked == [(len(await a.registry.export_chain()), 0)]  # identity.db was asked first, the hold unmoved
        assert held is not None and held.state.seq == 0  # no hold recorded: the peer stays gapped until a later attempt
        assert _rows(b.store_path) == before  # nothing recorded, no replay window either
        assert b.registry.get_foreign_chain(a_did) is None
        assert _resync_refusals(caplog) == ["identity.db: Registry not started", "identity.db: RuntimeError"]


async def test_s2a_m3_stop_cancels_a_running_resync_and_detaches_the_listener() -> None:
    seam = _FakeSeam()
    exchange = IdentityExchange(
        node_id="node-b", registry=SimpleNamespace(), seam=seam,
        admission=PeerAdmission(local_node_id="node-b", pins={"node-a": _new_key().public}), timeout_ms=50,
    )
    exchange.history_gap("node-a")
    await _settle()
    (running,) = [task for task in asyncio.all_tasks() if task.get_name() == "ad1198-resync-node-a"]

    await exchange.stop()

    assert running.cancelled() and seam.listener is None
    assert [task for task in asyncio.all_tasks() if task.get_name() == "ad1198-resync-node-a"] == []


# --------------------------------------------------------------------------- #
# M4 -- wiring: the bridge, fleet organization and shutdown
# --------------------------------------------------------------------------- #


class _RecordingView:
    def __init__(self, calls: list[tuple[str, ...]], sender: str) -> None:
        self.calls = calls
        self.sender = sender

    async def export_chain(self) -> list[dict[str, Any]]:
        self.calls.append(("export_chain", self.sender))
        return [{"index": 0}]

    async def import_chain(self, blocks: list[dict[str, Any]]) -> tuple[bool, str]:
        self.calls.append(("import_chain", self.sender))
        return True, "chain ok"

    async def import_transfer_certificate(self, cert: Any) -> tuple[bool, str]:
        self.calls.append(("import_transfer_certificate", self.sender))
        return True, "cert ok"


class _SentTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, FederationMessage]] = []

    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None:
        self.sent.append((peer_node_id, message))


async def test_s2a_m4_the_bridge_answers_identity_requests_through_the_exchange_bound_to_their_sender(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []
    exchange = SimpleNamespace(for_sender=lambda sender: _RecordingView(calls, sender))
    transport = _SentTransport()
    registry_calls: list[tuple[str, ...]] = []
    registry = _RecordingView(registry_calls, "registry")
    async with _armed(tmp_path / "identity", _DuckKeyring()) as (origin, _):
        troi = await _birth(origin, "Troi")
        xfer = await origin.issue_transfer_certificate(troi.agent_uuid, generate_ship_did("ship-b"))
        cert = xfer.to_dict()
    for exchange_or_none, recorded in ((exchange, calls), (None, registry_calls)):
        bridge = FederationBridge(
            node_id="node-b", transport=transport, router=FederationRouter(), intent_bus=SimpleNamespace(),
            config=FederationConfig(node_id="node-b"), self_model_fn=lambda: NodeSelfModel(node_id="node-b"),
            identity_registry=registry, identity_exchange=exchange_or_none,  # type: ignore[arg-type]
        )
        await bridge.handle_inbound(FederationMessage(type="chain_request", source_node="node-x", message_id="m1"))
        await bridge.handle_inbound(FederationMessage(
            type="transfer_request", source_node="node-x", message_id="m2", payload={"cert_dict": cert, "chain_blocks": []},
        ))
        owner = "node-x" if exchange_or_none is not None else "registry"
        assert recorded == [("export_chain", owner), ("import_chain", owner), ("import_transfer_certificate", owner)]
    answers = [(peer, message.type, message.payload) for peer, message in transport.sent]
    served = ("node-x", "chain_response", {"blocks": [{"index": 0}]})
    moved = ("node-x", "transfer_response", {"accepted": True, "message": "cert ok", "agent_uuid": troi.agent_uuid})
    assert answers == [served, moved, served, moved]


@contextlib.asynccontextmanager
async def _organized(config: Any, *, bus: Any, binding: Any, registry: Any, data_dir: Path) -> Any:
    from probos.substrate.pool_group import PoolGroupRegistry

    result = None
    try:
        result = await organize_fleet(
            config=config, pools={}, pool_groups=PoolGroupRegistry(), escalation_manager=SimpleNamespace(),
            intent_bus=_WiringIntentBus(), trust_network=SimpleNamespace(), llm_client=SimpleNamespace(),
            build_pool_intent_map_fn=dict, find_consensus_pools_fn=set,
            build_self_model_fn=lambda: NodeSelfModel(node_id="node-a"), validate_remote_result_fn=None,
            attachment_resolver_fn=None, nats_bus=bus, identity_key_binding=binding, data_dir=data_dir,
            identity_registry=registry,
        )
        yield result
    finally:
        if result is not None and result.federation_identity_exchange is not None:
            await result.federation_identity_exchange.stop()
        if result is not None and result.federation_bridge is not None:
            await result.federation_bridge.stop()
        if result is not None and result.federation_transport is not None:
            await result.federation_transport.stop()


async def test_s2a_m4_fleet_organization_wires_the_identity_exchange_only_while_admission_is_armed(tmp_path: Path) -> None:
    pin_b = _new_key().public
    armed = _admission_config(pin_b, admission=True)
    disabled = armed.model_copy(update={"federation": armed.federation.model_copy(update={"enabled": False})})
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (registry, binding):
        data_dir = tmp_path / "armed"
        data_dir.mkdir()
        async with _organized(armed, bus=bus, binding=binding, registry=registry, data_dir=data_dir) as result:
            exchange = result.federation_identity_exchange
            assert type(exchange) is IdentityExchange
            assert vars(result.federation_bridge)["_identity_exchange"] is exchange
            guard = vars(result.federation_transport.chain_seam)["_guard"]
            assert vars(guard)["_gap_listener"] == exchange.history_gap  # a key history gap asks this exchange
            ledger = vars(guard)["_ledger"]  # A-1: its start may judge a held history's pin on identity.db's chain
            assert (ledger.func, ledger.args) == (stored_key_history, (registry,))
        cases = (
            ("signing only", _admission_config(pin_b, admission=False), registry),
            ("disabled", disabled, registry),
            ("armed, no registry", armed, None),
        )
        for label, config, given in cases:
            data_dir = tmp_path / label.replace(" ", "-").replace(",", "")
            data_dir.mkdir()
            async with _organized(config, bus=bus, binding=binding, registry=given, data_dir=data_dir) as result:
                assert result.federation_identity_exchange is None, label
                if result.federation_bridge is not None:
                    assert vars(result.federation_bridge)["_identity_exchange"] is None, label
                if result.federation_transport is not None:  # A-1: no ledger unless admission is armed with a registry
                    assert vars(vars(result.federation_transport.chain_seam)["_guard"])["_ledger"] is None, label
    assert FleetOrganizationResult(
        pool_scaler=None, federation_bridge=None, federation_transport=None,
    ).federation_identity_exchange is None


async def test_s2a_m4_shutdown_stops_the_identity_exchange_before_the_bridge_and_the_transport(tmp_path: Path) -> None:
    runtime = BareRuntime(tmp_path / "data")
    runtime.federation_identity_exchange = RecordedService(runtime.calls, "federation_identity_exchange")
    runtime.federation_bridge = RecordedService(runtime.calls, "federation_bridge")
    runtime._federation_transport = RecordedService(runtime.calls, "_federation_transport")

    await shutdown(runtime, reason="test")  # type: ignore[arg-type]

    stops = [call for call in runtime.calls if call.startswith(("federation_", "_federation_"))]
    assert stops == ["federation_identity_exchange.stop", "federation_bridge.stop", "_federation_transport.stop"]
    assert vars(runtime)["federation_identity_exchange"] is None


# --------------------------------------------------------------------------- #
# a1 -- Amendment A-1 (review round 1)
# --------------------------------------------------------------------------- #


async def _resync_pair(
    stack: contextlib.AsyncExitStack, wire: _Wire, tmp: Path, *, timeout_ms: int = 2_000,
) -> tuple[_Node, _Node, str, IdentityExchange, FederationBridge]:
    """Node-a and node-b pinned to each other, each with an exchange behind an armed bridge and each holding the other;
    node-a's pin, and node-b's exchange (its resyncs wait ``timeout_ms``) and bridge."""
    a, b, pin_a, pin_b = await _pinned_pair(stack, wire, tmp)
    exchange_a = _exchange(a, {"node-b": pin_b})
    exchange_b = _exchange(b, {"node-a": pin_a}, timeout_ms=timeout_ms)
    stack.push_async_callback(exchange_a.stop)
    stack.push_async_callback(exchange_b.stop)
    await _exchange_bridge(stack, a, exchange_a, _RecordingIntentBus("node-a"), peer="node-b")
    bridge_b = await _exchange_bridge(stack, b, exchange_b, _RecordingIntentBus("node-b"), peer="node-a")
    assert await bridge_b.request_chain("node-a") == await a.registry.export_chain()  # premise: each holds the other
    return a, b, pin_a, exchange_b, bridge_b


async def test_s2a_a1_a_late_answer_to_an_ended_resync_is_dropped_and_answers_no_intent(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange_b, bridge_b = await _resync_pair(stack, wire, tmp_path, timeout_ms=200)
        withheld: list[FederationMessage] = []
        send = a.inner.send_to_peer

        async def withholding(peer: str, message: FederationMessage) -> None:
            if message.type == CHAIN_RESPONSE:
                withheld.append(message)
                return
            await send(peer, message)

        a.inner.send_to_peer = withholding  # type: ignore[method-assign]
        assert await exchange_b.resync("node-a") is False  # node-a's genuine answer is held back past the 200 ms
        a.inner.send_to_peer = send  # type: ignore[method-assign]
        (late,) = withheld
        await wire.inject("node-b", late)  # the answer arrives after its resync ended
        await wire.inject("node-b", late)  # and once more

        assert await b.transport.receive_with_timeout("node-a", 100) is None  # nothing was queued where intents read
        first = IntentMessage(intent="read_file", params={"path": "/1"})
        second = IntentMessage(intent="read_file", params={"path": "/2"})
        outcomes = [await bridge_b.forward_intent(first), await bridge_b.forward_intent(second)]
        assert [[result.intent_id for result in outcome] for outcome in outcomes] == [[first.id], [second.id]]
        assert [outcome.peers_unknown for outcome in outcomes] == [0, 0]


class _EndingInner:
    """A wrapped transport whose correlated requests end as told: an answer, a timeout (``None``) or an exception."""

    node_id = "node-b"

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[FederationMessage] = []

    async def request_peer(self, peer_node_id: str, message: FederationMessage, timeout_ms: int) -> Any:
        self.requests.append(message)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


async def test_s2a_a1_the_chain_seam_remembers_each_ended_resync_request_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with contextlib.AsyncExitStack() as stack:
        guard, _ = await _holder(stack, tmp_path, pins={"node-a": _new_key().public})
        unsigned = FederationMessage(type=CHAIN_RESPONSE, source_node="node-a", payload={"blocks": []})
        inner = _EndingInner(None, RuntimeError("federation_transport_closed"), asyncio.CancelledError(), unsigned)
        seam = SignedChainSeam(inner, guard, PeerAdmission(local_node_id="node-b", pins={"node-a": _new_key().public}))

        async def nothing(answer: FederationMessage) -> Any:
            return None

        def request() -> FederationMessage:
            return FederationMessage(type=CHAIN_REQUEST, source_node="node-b", payload={})

        def answer(message_id: Any, *, kind: str = CHAIN_RESPONSE) -> FederationMessage:
            return FederationMessage(type=kind, source_node="node-a", message_id=message_id, payload={"blocks": []})

        assert await seam.request_resync("node-a", request(), 50, nothing) is None  # no answer in time
        with pytest.raises(RuntimeError):
            await seam.request_resync("node-a", request(), 50, nothing)  # the transport failed
        with pytest.raises(asyncio.CancelledError):
            await seam.request_resync("node-a", request(), 50, nothing)  # cancelled while it waited
        assert await seam.request_resync("node-a", request(), 50, nothing) is None  # answered unsigned: not admitted
        ended = [message.message_id for message in inner.requests]

        assert [seam.ended_answer("node-a", answer(message_id)) for message_id in ended] == [True] * 4
        assert seam.ended_answer("node-c", answer(ended[0])) is False  # another peer
        assert seam.ended_answer("node-a", answer(ended[0], kind="intent_response")) is False  # another topic
        assert seam.ended_answer("node-a", answer("never-asked")) is False  # another request
        assert seam.ended_answer("node-a", answer(["not", "hashable"])) is False  # a malformed id
        assert seam.ended_answer(["node-a"], answer(ended[0])) is False  # a malformed source
        assert seam.ended_answer("node-a", object()) is False
        assert MAX_ENDED_RESYNCS == 256
        monkeypatch.setattr(signed_transport_module, "MAX_ENDED_RESYNCS", 2)
        inner.outcomes.extend([None, None])
        await seam.request_resync("node-a", request(), 50, nothing)
        await seam.request_resync("node-a", request(), 50, nothing)
        latest = [message.message_id for message in inner.requests[-3:]]
        assert [seam.ended_answer("node-a", answer(message_id)) for message_id in latest] == [False, True, True]
        assert seam.ended_answer("node-a", answer(ended[0])) is False  # the oldest ended request is forgotten first


async def test_s2a_a1_an_older_snapshot_changes_nothing_and_its_transfer_is_judged_against_the_stored_chain(
    tmp_path: Path,
) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        exchange = _exchange(b, {"node-a": pin_a})
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        assert b.transport.chain_seam.held("node-a") is not None  # premise
        a_did = (await a.binding.status())["did"]
        ship_b = b.registry.get_ship_certificate()
        assert ship_b is not None
        troi = await _birth(a.registry, "Troi", instance_id="ship-a")
        first = await a.registry.issue_transfer_certificate(troi.agent_uuid, ship_b.ship_did)
        older = await a.registry.export_chain()
        worf = await _birth(a.registry, "Worf", instance_id="ship-a")
        second = await a.registry.issue_transfer_certificate(worf.agent_uuid, ship_b.ship_did)
        newer = await a.registry.export_chain()

        assert await exchange.import_chain_from("node-a", newer) == (True, f"Chain imported: {len(newer)} blocks from {a_did}")
        assert await exchange.import_transfer_from("node-a", second) == (True, f"Certificate imported: {worf.did}")
        kept = await exchange.import_chain_from("node-a", older)  # the earlier transfer's chain arrives last
        moved = await exchange.import_transfer_from("node-a", first)

        assert kept == (True, f"Chain kept: the {len(newer)} blocks stored for {a_did} already hold these {len(older)}")
        assert moved == (True, f"Certificate imported: {troi.did}")
        assert b.registry.get_foreign_chain(a_did) == newer  # the longer chain stands
        for cert in (first, second):  # both accepted certificates still verify against what identity.db stores
            verdict = verify_transfer_attestation(
                newer, credential=cert.to_verifiable_credential(), certificate_hash=cert.certificate_hash,
                subject_did=cert.did,
            )
            assert verdict.accepted, verdict


def _diverged(chain: list[dict[str, Any]], at: int, note: str, *, then: int = 0) -> list[dict[str, Any]]:
    """``chain`` up to block ``at``, then ``1 + then`` unsigned blocks of its own: every hash and link verifies, and from
    block ``at`` on the history is not ``chain``'s."""
    blocks = [dict(block) for block in chain[:at]]
    template = {key: value for key, value in chain[at].items() if key != "attestation"}
    for offset in range(1 + then):
        block = {
            **template, "index": at + offset, "previous_hash": blocks[-1]["block_hash"],
            "certificate_hash": hashlib.sha256(f"{note}-{offset}".encode()).hexdigest(),
        }
        block["block_hash"] = LedgerBlock(
            index=block["index"], timestamp=block["timestamp"], certificate_hash=block["certificate_hash"],
            agent_did=block["agent_did"], previous_hash=block["previous_hash"],
        ).compute_hash()
        blocks.append(block)
    return blocks


async def test_s2a_a1_an_armed_import_only_extends_the_stored_chain_one_import_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        exchange = _exchange(b, {"node-a": pin_a})
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        assert b.transport.chain_seam.held("node-a") is not None  # premise
        a_did = (await a.binding.status())["did"]
        chains: list[list[dict[str, Any]]] = []
        for callsign in ("Troi", "Worf", "Data", "Riker", "Crusher"):
            await _birth(a.registry, callsign, instance_id="ship-a")
            chains.append(await a.registry.export_chain())
        first, second, third, fourth, fifth = chains
        tip = len(second) - 1
        not_extending = [
            _diverged(second, tip, "same length"), _diverged(second, tip - 1, "shorter"),
            _diverged(third, tip, "longer", then=2),
        ]

        assert (await exchange.import_chain_from("node-a", second))[0] is True  # nothing stored: imported
        refused = [await exchange.import_chain_from("node-a", chain) for chain in not_extending]
        # each passed every check of a sender's own chain (that reason comes only after them) and is refused for this one
        assert refused == [(False, "identity exchange refused (does not extend the stored chain)")] * 3
        assert b.registry.get_foreign_chain(a_did) == second
        assert exchange.refusal_counts == {"does not extend the stored chain": 3}
        assert await exchange.import_chain_from("node-a", first) == (
            True, f"Chain kept: the {len(second)} blocks stored for {a_did} already hold these {len(first)}",
        )
        assert await exchange.import_chain_from("node-a", third) == (True, f"Chain imported: {len(third)} blocks from {a_did}")

        imports: list[int] = []
        release = asyncio.Event()
        real_import = b.registry.import_chain

        async def slow(blocks: list[dict[str, Any]]) -> tuple[bool, str]:
            imports.append(len(blocks))
            await release.wait()
            return await real_import(blocks)

        monkeypatch.setattr(b.registry, "import_chain", slow)
        newest = asyncio.create_task(exchange.import_chain_from("node-a", fifth))
        await _settle()
        older = asyncio.create_task(exchange.import_chain_from("node-a", fourth))  # extends what is stored now
        await _settle()
        assert imports == [len(fifth)]  # the second import waits for the first
        release.set()
        assert (await newest)[0] is True
        assert await older == (True, f"Chain kept: the {len(fifth)} blocks stored for {a_did} already hold these {len(fourth)}")
        assert imports == [len(fifth)] and b.registry.get_foreign_chain(a_did) == fifth


async def test_s2a_a1_a_resync_stopped_while_identity_db_imports_records_no_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange_b, _ = await _resync_pair(stack, wire, tmp_path)
        await _rotate(a, _GAP)
        before = _rows(b.store_path)
        entered = asyncio.Event()
        seen: list[int] = []

        async def paused(blocks: list[dict[str, Any]]) -> tuple[bool, str]:
            held = b.transport.chain_seam.held("node-a")
            seen.append(-1 if held is None else held.state.seq)
            entered.set()
            await asyncio.Event().wait()  # stop() arrives while identity.db imports
            return True, "unreachable"

        monkeypatch.setattr(b.registry, "import_chain", paused)
        exchange_b.history_gap("node-a")
        await asyncio.wait_for(entered.wait(), 10)
        await exchange_b.stop()

        held = b.transport.chain_seam.held("node-a")
        assert seen == [0]  # identity.db is asked before the hold moves
        assert held is not None and held.state.seq == 0  # stopped there, nothing is recorded
        assert _rows(b.store_path) == before


async def _rearmed(stack: contextlib.AsyncExitStack, node: _Node, pins: dict[str, str], ledger: Any) -> None:
    """Restart ``node``'s armed transport on the same store through the production builder, with ``ledger``."""
    await node.transport.stop()
    transport = build_signed_transport(
        node.inner, policy=POLICY_REQUIRE, key_binding=node.binding, data_dir=node.data_dir,
        admission=PeerAdmission(local_node_id=node.name, pins=pins), ledger=ledger,
    )

    async def _dispatch(message: FederationMessage) -> None:
        node.dispatched.append(message)

    transport._inbound_handler = _dispatch  # the bridge's own handler contract (bridge.py:1059), as _admit does
    stack.push_async_callback(transport.stop)
    await transport.start()
    node.transport = transport


def _pin_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage() for record in caplog.records
        if record.name == _ENVELOPE_LOGGER and "identity pin" in record.getMessage()
    ]


async def test_s2a_a1_a_resynchronised_hold_keeps_its_pin_across_restarts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, exchange_b, _ = await _resync_pair(stack, wire, tmp_path)
        await _rotate(a, _GAP)
        assert await exchange_b.resync("node-a") is True
        await exchange_b.stop()
        pins = {"node-a": pin_a}
        ledger = functools.partial(stored_key_history, b.registry)

        await _rearmed(stack, b, pins, None)  # premise: without identity.db's chain the start refuses it, as before
        assert b.transport.chain_seam.held("node-a") is None
        await _rearmed(stack, b, pins, ledger)
        kept = b.transport.chain_seam.held("node-a")
        sent = _unsigned("node-a")
        await a.transport.send_to_peer("node-b", sent)
        await a.binding.rotate()  # one key event past identity.db's chain, carried by the next envelope
        grown = _unsigned("node-a")
        await a.transport.send_to_peer("node-b", grown)
        grew = b.transport.chain_seam.held("node-a")
        await _rearmed(stack, b, pins, ledger)
        joined = b.transport.chain_seam.held("node-a")
        again = _unsigned("node-a")
        await a.transport.send_to_peer("node-b", again)

        assert kept is not None and kept.state.seq == _GAP
        assert grew is not None and grew.state.seq == _GAP + 1
        assert joined is not None and joined.state.seq == _GAP + 1  # the held events continue identity.db's chain
        assert [message.message_id for message in b.dispatched[-3:]] == [sent.message_id, grown.message_id, again.message_id]
        assert _pin_lines(caplog) == [
            "AD-1198: the key history held for 'node-a' does not satisfy its identity pin (pin (key)); its envelopes are "
            "refused until its pin or its hold is corrected",
            "AD-1198: on the chain identity.db stores for 'node-a', the key history held for it satisfies its identity "
            f"pin (key seq {_GAP}); it is held",
            "AD-1198: on the chain identity.db stores for 'node-a', the key history held for it satisfies its identity "
            f"pin (key seq {_GAP + 1}); it is held",
        ]


async def test_s2a_a1_a_held_history_identity_db_cannot_prove_is_refused_at_start_as_before(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, exchange_b, _ = await _resync_pair(stack, wire, tmp_path)
        await _rotate(a, _GAP)
        assert await exchange_b.resync("node-a") is True
        await exchange_b.stop()
        found = stored_key_history(b.registry, (await a.binding.status())["did"])
        assert found is not None  # premise: identity.db's chain alone would keep the hold
        history, full = found
        inception = derive_key_state(history[:1])
        assert inception is not None
        changed = (*history[:-1], dataclasses.replace(history[-1], signatures={"new": "changed"}))

        def unreadable(did: str) -> Any:
            raise RuntimeError("identity.db unreadable")

        ledgers = [
            lambda did: None,  # nothing stored
            unreadable,
            lambda did: (history[:1], inception),  # ends before the held events begin: the two do not join
            lambda did: (changed, full),  # a held event changed
            lambda did: (history, inception),  # a state that is not its history's: the held events do not replay from it
            lambda did: (history, dataclasses.replace(full, broken_at=(full.seq + 10_000,))),  # re-incepted past the pin
        ]
        for ledger in ledgers:
            await _rearmed(stack, b, {"node-a": pin_a}, ledger)
            assert b.transport.chain_seam.held("node-a") is None
        await _rearmed(stack, b, {"node-a": pin_a}, functools.partial(stored_key_history, b.registry))

        assert b.transport.chain_seam.held("node-a") is not None  # the genuine chain keeps it
        reasons = [line.split("identity pin (")[1].split("); its")[0] for line in _pin_lines(caplog)[:-1]]
        assert reasons == ["pin (key)", "pin (key)", "pin (key)", "pin (key)", "pin (key)", "pin (continuity)"]


async def test_s2a_a1_stored_key_history_is_only_a_verified_chain_of_that_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _armed(tmp_path / "identity", _DuckKeyring()) as (registry, binding):
        did = (await binding.status())["did"]
        await binding.rotate()
        await _birth(registry, "Troi")
        chain = await registry.export_chain()
    misattested = [dict(block) for block in chain]
    misattested[-1] = {**misattested[-1], "attestation": {**misattested[-1]["attestation"], "jws": chain[1]["attestation"]["signatures"]["new"]}}
    stripped = [{key: value for key, value in block.items() if key != "attestation"} for block in chain]

    def stores(blocks: Any) -> Any:
        return SimpleNamespace(get_foreign_chain=lambda origin: blocks if origin == did else None)

    found = stored_key_history(stores(chain), did)
    assert found is not None
    history, state = found
    assert ([event.payload["seq"] for event in history], state.did, state.seq) == ([0, 1], did, 1)
    assert stored_key_history(stores(None), did) is None  # nothing stored
    assert stored_key_history(stores(stripped), did) is None  # no key history
    assert stored_key_history(stores(misattested), did) is None  # a signature does not verify
    assert stored_key_history(SimpleNamespace(get_foreign_chain=lambda origin: chain), "did:probos:another") is None
    monkeypatch.setattr(continuity_module, "MAX_CHAIN_BLOCKS", len(chain) - 1)
    assert stored_key_history(stores(chain), did) is None  # over the bounds


@pytest.mark.parametrize("where", ["after-start", "during-start", "a-stop-fails", "signing-only"])
async def test_s2a_a1_a_fleet_organization_that_fails_after_its_transport_started_stops_what_it_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, where: str,
) -> None:
    """``after-start``: the intent bus refuses the bridge's handler; ``during-start``: the bridge's start raises once its
    gossip task runs; ``a-stop-fails``: as after-start, and the bridge's own stop raises; ``signing-only``: as after-start
    with peer admission off, so there is no identity exchange to stop."""
    from probos.substrate.pool_group import PoolGroupRegistry

    caplog.set_level(logging.WARNING, logger="probos.startup.fleet_organization")
    built: list[Any] = []
    bridges: list[FederationBridge] = []
    real_build = signed_transport_module.build_signed_transport
    real_start = FederationBridge.start
    real_stop = FederationBridge.stop

    def recording_build(*args: Any, **kwargs: Any) -> Any:
        built.append(real_build(*args, **kwargs))
        return built[-1]

    async def recording_start(self: FederationBridge) -> None:
        bridges.append(self)
        await real_start(self)
        if where == "during-start":
            raise RuntimeError("injected")

    async def failing_stop(self: FederationBridge) -> None:
        await real_stop(self)
        raise RuntimeError("the bridge's stop failed")

    class _FailingIntentBus(_WiringIntentBus):
        def set_federation_handler(self, handler: Any) -> None:
            raise RuntimeError("injected")

    monkeypatch.setattr(signed_transport_module, "build_signed_transport", recording_build)
    monkeypatch.setattr(FederationBridge, "start", recording_start)
    if where == "a-stop-fails":
        monkeypatch.setattr(FederationBridge, "stop", failing_stop)
    intent_bus = _WiringIntentBus() if where == "during-start" else _FailingIntentBus()
    config = _admission_config(_new_key().public, admission=where != "signing-only")
    running: list[tuple[Any, ...]] = []
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (registry, binding):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        try:
            with pytest.raises(RuntimeError, match="^injected$"):
                await organize_fleet(
                    config=config, pools={}, pool_groups=PoolGroupRegistry(), escalation_manager=SimpleNamespace(),
                    intent_bus=intent_bus, trust_network=SimpleNamespace(), llm_client=SimpleNamespace(),
                    build_pool_intent_map_fn=dict, find_consensus_pools_fn=set,
                    build_self_model_fn=lambda: NodeSelfModel(node_id="node-a"), validate_remote_result_fn=None,
                    attachment_resolver_fn=None, nats_bus=bus, identity_key_binding=binding, data_dir=data_dir,
                    identity_registry=registry,
                )
        finally:  # record what is still running, then stop it here, so a missing stop fails this test instead of hanging it
            for transport in built:
                guard = vars(transport.chain_seam)["_guard"]
                running.append((vars(transport)["_inner_started"], vars(guard)["_mode"], vars(guard)["_gap_listener"]))
            for bridge in bridges:
                running.append((vars(bridge)["_gossip_task"],))
                await real_stop(bridge)
            for transport in built:
                await transport.stop()

    assert (len(built), len(bridges)) == (1, 1)
    assert running == [(False, "stopped", None), (None,)]  # the transport and its guard stopped, no listener, no gossip task
    warnings = _messages(caplog, "probos.startup.fleet_organization", logging.WARNING)
    assert warnings[0] == (
        "AD-1198: fleet organization failed after its federation transport was built; stopping the federation it "
        "built before the error propagates"
    )
    expected = ["AD-1198: the federation bridge of a failed fleet organization did not stop cleanly (RuntimeError); continuing"]
    assert warnings[1:] == (expected if where == "a-stop-fails" else [])


# --------------------------------------------------------------------------- #
# a2 -- Amendment A-2 (review round 2)
# --------------------------------------------------------------------------- #


def _stripped(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``chain`` without its attestations, as an unarmed node's import leaves it: every block hash and link still
    verifies (a block hash does not cover the attestation), and it carries no key history."""
    return [{key: value for key, value in block.items() if key != "attestation"} for block in chain]


def _appended(chain: list[dict[str, Any]], note: str) -> list[dict[str, Any]]:
    """``chain`` and one more unsigned block of its own, linked to it."""
    return _diverged([*chain, chain[-1]], len(chain), note)


def _rehashed(block: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """``block`` with ``changes`` and its block hash recomputed, so only what changed can fail to verify."""
    changed = {**block, **changes}
    changed["block_hash"] = LedgerBlock(
        index=changed["index"], timestamp=changed["timestamp"], certificate_hash=changed["certificate_hash"],
        agent_did=changed["agent_did"], previous_hash=changed["previous_hash"],
    ).compute_hash()
    return changed


def _mismatched(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``chain`` with its first block's timestamp changed and its block hash kept, which no longer matches it."""
    return [{**chain[0], "timestamp": chain[0]["timestamp"] + 1.0}, *chain[1:]]


def _unlinked(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``chain`` with its last block linked to nothing (its own hash recomputed), so the link to the block before fails."""
    return [*chain[:-1], _rehashed(chain[-1], previous_hash="0" * 64)]


@pytest.mark.parametrize("stored", ["equal", "shorter"])
async def test_s2a_a2_a_resync_over_an_unverified_stored_snapshot_it_contains_replaces_it_and_survives_a_restart(
    tmp_path: Path, stored: str,
) -> None:
    """identity.db stores an unsigned snapshot of node-a's chain, as an unarmed node's import leaves it: all of the
    chain the resync fetches (``equal``), or all but its last block (``shorter``)."""
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, exchange_b, _ = await _resync_pair(stack, wire, tmp_path)
        await _rotate(a, _GAP)
        a_did = (await a.binding.status())["did"]
        chain = await a.registry.export_chain()
        assert (await b.registry.import_chain(_stripped(chain if stored == "equal" else chain[:-1])))[0] is True  # premise
        assert stored_key_history(b.registry, a_did) is None  # premise: that snapshot proves nothing at start-up

        resynced = await exchange_b.resync("node-a")
        replaced = b.registry.get_foreign_chain(a_did)
        await exchange_b.stop()
        await _rearmed(stack, b, {"node-a": pin_a}, functools.partial(stored_key_history, b.registry))
        kept = b.transport.chain_seam.held("node-a")
        sent = _unsigned("node-a")
        await a.transport.send_to_peer("node-b", sent)

        assert resynced is True
        assert replaced == chain  # the verified chain the resync fetched replaced the snapshot
        assert kept is not None and kept.state.seq == _GAP  # so the hold it recorded survives the restart
        assert b.dispatched[-1].message_id == sent.message_id


@pytest.mark.parametrize("stored", ["longer", "garbled"])
async def test_s2a_a2_an_unverified_stored_chain_a_resync_does_not_contain_refuses_it_and_records_no_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, stored: str,
) -> None:
    """identity.db stores, for node-a, an unsigned snapshot one block longer than node-a's chain (``longer``), or a copy
    one of whose blocks is not a block (``garbled``, read back as a corrupted identity.db would return it). Neither
    verifies, and the chain the resync fetches does not begin with it: the resync is refused and identity.db kept."""
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, _, exchange_b, _ = await _resync_pair(stack, wire, tmp_path)
        await _rotate(a, _GAP)
        a_did = (await a.binding.status())["did"]
        chain = await a.registry.export_chain()
        stored_chain = b.registry.get_foreign_chain
        snapshot: list[Any] = _stripped(_appended(chain, "later")) if stored == "longer" else [*chain[:-1], "not a block"]
        if stored == "longer":
            assert (await b.registry.import_chain(snapshot))[0] is True  # premise: identity.db takes an unsigned snapshot
        else:
            monkeypatch.setattr(b.registry, "get_foreign_chain", lambda did: snapshot if did == a_did else stored_chain(did))
        before = _rows(b.store_path)

        resynced = await exchange_b.resync("node-a")

        reason = "the stored chain does not verify and this one does not contain it"
        held = b.transport.chain_seam.held("node-a")
        assert resynced is False
        assert held is not None and held.state.seq == 0 and _rows(b.store_path) == before  # no hold is recorded
        assert stored_chain(a_did) == (snapshot if stored == "longer" else None)  # identity.db is unchanged
        assert exchange_b.refusal_counts == {reason: 1}
        assert _resync_refusals(caplog) == [f"identity.db: identity exchange refused ({reason})"]


@pytest.mark.parametrize("stored", ["equal", "longer"])
async def test_s2a_a2_a_transfer_over_an_unverified_stored_snapshot_is_judged_on_the_verified_chain(
    tmp_path: Path, stored: str,
) -> None:
    """identity.db stores an unsigned snapshot of node-a's chain: the chain the transfer carries (``equal``), or that and
    one block more (``longer``). The certificate is not anchored on the chain it carries (issued after it was exported):
    judged on that verified chain it is refused, and with the longer snapshot the chain itself is; nothing is imported."""
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        bridge_a = await _bridge(stack, "node-a", a.transport, _RecordingIntentBus("node-a"), peers=("node-b",))
        await _exchange_bridge(stack, b, _exchange(b, {"node-a": pin_a}), _RecordingIntentBus("node-b"), peer="node-a")
        a_did = (await a.binding.status())["did"]
        ship_b = b.registry.get_ship_certificate()
        assert ship_b is not None
        troi = await _birth(a.registry, "Troi", instance_id="ship-a")
        chain = await a.registry.export_chain()  # before the transfer is anchored on node-a's ledger
        xfer = await a.registry.issue_transfer_certificate(troi.agent_uuid, ship_b.ship_did)
        snapshot = _stripped(chain if stored == "equal" else _appended(chain, "later"))
        assert (await b.registry.import_chain(snapshot))[0] is True  # premise: identity.db takes an unsigned snapshot

        moved = await bridge_a.request_transfer("node-b", xfer, chain)

        expected = {
            "equal": "transfer certificate is not anchored on the origin's ledger",
            "longer": "chain rejected: identity exchange refused (the stored chain does not verify and this one does not "
            "contain it)",
        }
        assert moved == (False, expected[stored])
        assert b.registry.get_by_uuid(troi.agent_uuid) is None
        assert await b.registry.get_transfer_certificates_for(troi.did) == []
        assert b.registry.get_foreign_chain(a_did) == (chain if stored == "equal" else snapshot)


async def test_s2a_a2_a_certificate_is_judged_only_against_a_verified_chain_of_its_ship(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, _ = await _pinned_pair(stack, wire, tmp_path)
        exchange = _exchange(b, {"node-a": pin_a})
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        assert b.transport.chain_seam.held("node-a") is not None  # premise
        a_did = (await a.binding.status())["did"]
        ship_b = b.registry.get_ship_certificate()
        assert ship_b is not None
        troi = await _birth(a.registry, "Troi", instance_id="ship-a")
        xfer = await a.registry.issue_transfer_certificate(troi.agent_uuid, ship_b.ship_did)
        chain = await a.registry.export_chain()  # anchors the transfer

        nothing = await exchange.import_transfer_from("node-a", xfer)
        assert (await b.registry.import_chain(_stripped(chain)))[0] is True  # premise: identity.db takes an unsigned copy
        unsigned = await exchange.import_transfer_from("node-a", xfer)
        arrived = b.registry.get_by_uuid(troi.agent_uuid)
        imported = await exchange.import_chain_from("node-a", chain)
        moved = await exchange.import_transfer_from("node-a", xfer)

        refused = (False, "identity exchange refused (no verified chain of the sender's ship)")
        assert [nothing, unsigned] == [refused, refused]
        assert arrived is None
        assert imported == (True, f"Chain imported: {len(chain)} blocks from {a_did}")  # it replaces the unsigned copy
        assert moved == (True, f"Certificate imported: {troi.did}")
        assert exchange.refusal_counts == {"no verified chain of the sender's ship": 2}


async def test_s2a_a2_the_start_up_proof_refuses_a_stored_chain_whose_hashes_or_links_do_not_verify(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a, b, pin_a, exchange_b, _ = await _resync_pair(stack, wire, tmp_path)
        await _rotate(a, _GAP)
        assert await exchange_b.resync("node-a") is True
        await exchange_b.stop()
        a_did = (await a.binding.status())["did"]
        chain = b.registry.get_foreign_chain(a_did)
        assert chain is not None
        corrupted = [_mismatched(chain), _unlinked(chain)]

        def stores(blocks: Any) -> Any:
            return SimpleNamespace(get_foreign_chain=lambda did: blocks)

        for blocks in corrupted:
            await _rearmed(stack, b, {"node-a": pin_a}, functools.partial(stored_key_history, stores(blocks)))
            assert b.transport.chain_seam.held("node-a") is None
        await _rearmed(stack, b, {"node-a": pin_a}, functools.partial(stored_key_history, b.registry))

        assert [verify_chain_structure(blocks) for blocks in corrupted] == [
            (False, "Block 0: hash mismatch"), (False, f"Block {chain[-1]['index']}: chain linkage broken"),
        ]
        assert [verify_chain_signatures(blocks).ok for blocks in corrupted] == [True, True]  # premise: signatures verify
        assert [stored_key_history(stores(blocks), a_did) for blocks in corrupted] == [None, None]
        assert b.transport.chain_seam.held("node-a") is not None  # the chain identity.db stores keeps it
        reasons = [line.split("identity pin (")[1].split("); its")[0] for line in _pin_lines(caplog)[:-1]]
        assert reasons == ["pin (key)", "pin (key)"]


async def test_s2a_a2_verified_chain_state_is_the_key_state_of_a_chain_that_verifies_in_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _armed(tmp_path / "identity", _DuckKeyring()) as (registry, binding):
        did = (await binding.status())["did"]
        await binding.rotate()
        chain = await registry.export_chain()

    state = verified_chain_state(chain)

    assert state is not None and (state.did, state.seq) == (did, 1)
    assert verified_chain_state(chain, did) == state
    assert verified_chain_state(chain, "did:probos:another") is None  # another DID's
    unverified = [None, [], [1, 2], _stripped(chain), _mismatched(chain), _unlinked(chain)]
    assert [verified_chain_state(blocks) for blocks in unverified] == [None] * len(unverified)  # and it never raises
    monkeypatch.setattr(continuity_module, "MAX_CHAIN_BLOCKS", len(chain) - 1)
    assert verified_chain_state(chain) is None  # over the bounds


async def test_s2a_a2_verify_chain_structure_is_the_check_the_registry_makes(tmp_path: Path) -> None:
    async with _armed(tmp_path / "identity", _DuckKeyring()) as (registry, binding):
        await binding.rotate()
        chain = await registry.export_chain()
    cases = [
        chain, [], [chain[0], {key: value for key, value in chain[1].items() if key != "block_hash"}],
        _mismatched(chain), _unlinked(chain), [_rehashed(chain[0], previous_hash="1" * 64), *chain[1:]],
    ]
    unstarted = AgentIdentityRegistry(data_dir=tmp_path / "unused")

    found = [verify_chain_structure(blocks) for blocks in cases]

    assert found == [await unstarted.verify_remote_chain(blocks) for blocks in cases]
    assert found == [
        (True, f"Chain valid: {len(chain)} blocks"), (False, "Empty chain"), (False, "Block 1: missing field 'block_hash'"),
        (False, "Block 0: hash mismatch"), (False, f"Block {chain[-1]['index']}: chain linkage broken"),
        (False, "Genesis block: invalid previous_hash (expected all zeros)"),
    ]
    with pytest.raises(TypeError):
        verify_chain_structure([1, 2])  # a block that is not a mapping raises, as the registry's check always has


@pytest.mark.parametrize("how", ["caller-cancelled", "cancelled-twice", "stop-cancelled", "start-cancelled"])
async def test_s2a_a2_a_cancellation_during_fleet_cleanup_still_stops_every_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, how: str,
) -> None:
    """Fleet organization fails once its bridge started (the intent bus refuses the bridge's handler), and
    ``caller-cancelled``: its task is cancelled while the cleanup waits for the identity exchange's stop;
    ``cancelled-twice``: and cancelled again while it still waits; ``stop-cancelled``: the identity exchange's own stop
    ends cancelled. ``start-cancelled``: its task is cancelled while the bridge starts, and the cleanup runs for that."""
    from probos.substrate.pool_group import PoolGroupRegistry

    caplog.set_level(logging.WARNING, logger="probos.startup.fleet_organization")
    built: list[Any] = []
    bridges: list[FederationBridge] = []
    exchanges: list[IdentityExchange] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    real_build = signed_transport_module.build_signed_transport
    real_start = FederationBridge.start
    real_stop = FederationBridge.stop
    real_exchange_stop = IdentityExchange.stop

    def recording_build(*args: Any, **kwargs: Any) -> Any:
        built.append(real_build(*args, **kwargs))
        return built[-1]

    async def recording_start(self: FederationBridge) -> None:
        bridges.append(self)
        await real_start(self)
        if how == "start-cancelled":
            entered.set()
            await asyncio.Event().wait()  # the caller is cancelled here

    async def exchange_stop(self: IdentityExchange) -> None:
        exchanges.append(self)
        if how in ("caller-cancelled", "cancelled-twice"):
            entered.set()
            await release.wait()  # the caller is cancelled while the cleanup waits here
        await real_exchange_stop(self)
        if how == "stop-cancelled":
            raise asyncio.CancelledError  # it stopped, and its stop ends cancelled

    class _FailingIntentBus(_WiringIntentBus):
        def set_federation_handler(self, handler: Any) -> None:
            raise RuntimeError("injected")

    monkeypatch.setattr(signed_transport_module, "build_signed_transport", recording_build)
    monkeypatch.setattr(FederationBridge, "start", recording_start)
    monkeypatch.setattr(IdentityExchange, "stop", exchange_stop)
    intent_bus = _WiringIntentBus() if how == "start-cancelled" else _FailingIntentBus()
    running: list[tuple[Any, ...]] = []
    async with _nats_bus() as bus, _armed(tmp_path / "identity", _DuckKeyring()) as (registry, binding):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        organizing = asyncio.create_task(organize_fleet(
            config=_admission_config(_new_key().public, admission=True), pools={}, pool_groups=PoolGroupRegistry(),
            escalation_manager=SimpleNamespace(), intent_bus=intent_bus, trust_network=SimpleNamespace(),
            llm_client=SimpleNamespace(), build_pool_intent_map_fn=dict, find_consensus_pools_fn=set,
            build_self_model_fn=lambda: NodeSelfModel(node_id="node-a"), validate_remote_result_fn=None,
            attachment_resolver_fn=None, nats_bus=bus, identity_key_binding=binding, data_dir=data_dir,
            identity_registry=registry,
        ))
        try:
            if how != "stop-cancelled":
                await asyncio.wait_for(entered.wait(), 10)
                organizing.cancel()
                if how == "cancelled-twice":
                    await _settle()
                    organizing.cancel()
                await _settle()
                release.set()
            await asyncio.wait({organizing}, timeout=10)
        finally:  # record what is still running, then stop it here, so a missing stop fails this test instead of hanging it
            release.set()
            if not organizing.done():
                organizing.cancel()
                await asyncio.gather(organizing, return_exceptions=True)
            for transport in built:
                guard = vars(transport.chain_seam)["_guard"]
                running.append((vars(transport)["_inner_started"], vars(guard)["_mode"], vars(guard)["_gap_listener"]))
            for bridge in bridges:
                running.append((vars(bridge)["_gossip_task"],))
            for exchange in exchanges:
                await real_exchange_stop(exchange)
            for bridge in bridges:
                await real_stop(bridge)
            for transport in built:
                await transport.stop()

    outcome = "cancelled" if organizing.cancelled() else repr(organizing.exception())
    assert outcome == ("RuntimeError('injected')" if how == "stop-cancelled" else "cancelled")
    assert running == [(False, "stopped", None), (None,)]  # the exchange, the transport and its guard, and the bridge
    warnings = _messages(caplog, "probos.startup.fleet_organization", logging.WARNING)
    assert warnings[0].startswith("AD-1198: fleet organization failed after its federation transport was built")
    cancelled = [
        "AD-1198: the federation identity exchange of a failed fleet organization was cancelled while it stopped; "
        "continuing",
        "AD-1198: the cleanup of a failed fleet organization was itself cancelled; a component it could not stop may "
        "stay running until the process exits",
    ]
    assert warnings[1:] == (cancelled if how == "stop-cancelled" else [])
