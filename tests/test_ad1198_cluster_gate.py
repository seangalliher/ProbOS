"""AD-1198 (#1135) M6: the two-node cluster gate -- authenticated peer admission on real sockets.

Two real ProbOS processes from the shipped ``config/node-1.yaml`` and ``config/node-2.yaml``
(``tests/fixtures/federation_cluster.py``): offline (closed-port LLM URLs and an injected ``MockLLMClient``), an
isolated home, data directory and knowledge repo per node, and real ZeroMQ between them. Each test first mints
both ship keys with federation off, then boots the nodes pinned to each other's minted public key under
envelope policy ``require`` with peer admission armed. In the ``mitm`` topology every payload crosses a
blocking-pyzmq proxy that can drop, duplicate and replay; in the ``direct`` topology (the shipped one) forged
messages and a routing-id squatter reach a node's ROUTER directly.

The tests are synchronous: blocking waits must not starve an event loop, and in-test signing runs through
``asyncio.run``. The harness kills every child process when it closes. No test reaches the real OS keyring
(AD-1196's autouse guard is imported, H5) or a live service.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import zmq

from probos.federation.envelope import POLICY_REQUIRE, EnvelopeGuard
from probos.federation_envelope_store import ENVELOPE_DB_NAME, EnvelopeStore
from probos.identity_keys import jws_kid
from probos.types import FederationMessage
from tests.fixtures.federation_cluster import NODES, ClusterHarness, WireProxy
from tests.test_ad1196_did_key_binding import (  # noqa: F401 -- importing the autouse guard applies it here (H5)
    _armed,
    _DuckKeyring,
    _no_real_os_keyring,
)

pytestmark = [pytest.mark.slow, pytest.mark.heavy_fixture]

_DUPLICATE = "AD-1197: envelope 'intent_request' from 'node-1' rejected (duplicate)"
_STALE_KEY = "AD-1197: envelope 'intent_request' from 'node-1' rejected (stale key)"
_UNSIGNED_FROM_NODE_1 = "AD-1198: envelope 'ping' from 'node-1' refused (unsigned from a pinned peer)"
_DID_PREFIX = "did:probos:"


def _sealed_wire(
    tmp: Path, *, instance_id: str, source: str, target: str, kind: str, payload: dict[str, Any],
) -> bytes:
    """``payload`` sealed as ``source`` by a fresh ship key whose DID is ``did:probos:<instance_id>``, in ZeroMQ
    wire form (``transport.py`` ``_serialize``)."""

    async def _seal() -> FederationMessage | None:
        async with _armed(tmp / "identity", _DuckKeyring(), instance_id=instance_id) as (_, binding):
            guard = EnvelopeGuard(
                signer=binding, store=EnvelopeStore(tmp / ENVELOPE_DB_NAME), local_node_id=source,
                policy=POLICY_REQUIRE,
            )
            await guard.start()
            try:
                return await guard.seal(
                    FederationMessage(type=kind, source_node=source, payload=payload, timestamp=1.0), target,
                )
            finally:
                await guard.stop()

    tmp.mkdir(parents=True, exist_ok=True)
    sealed = asyncio.run(_seal())
    assert sealed is not None and sealed.auth is not None, "premise: the fresh ship key signed the envelope"
    return json.dumps({
        "type": sealed.type, "source_node": sealed.source_node, "message_id": sealed.message_id,
        "payload": sealed.payload, "timestamp": sealed.timestamp, "auth": sealed.auth,
    }).encode()


def _send_raw(port: int, payload: bytes, identity: bytes) -> None:
    """One payload to the ROUTER on ``port`` from a blocking DEALER claiming ``identity``, flushed before close."""
    context = zmq.Context()
    try:
        dealer = context.socket(zmq.DEALER)
        dealer.setsockopt(zmq.IDENTITY, identity)
        dealer.setsockopt(zmq.LINGER, 5_000)
        dealer.connect(f"tcp://127.0.0.1:{port}")
        dealer.send(payload)
        dealer.close()
    finally:
        context.term()  # returns once the payload is out (the linger bounds it at 5 s)


def _unsigned_ping(message_id: str) -> bytes:
    return json.dumps({
        "type": "ping", "source_node": "node-1", "message_id": message_id, "payload": {}, "timestamp": 1.0,
    }).encode()


def _received(cluster: ClusterHarness, name: str = "node-2") -> int:
    return int(cluster.status(name)["federation"]["intents_received"])


def _proxy(cluster: ClusterHarness) -> WireProxy:
    assert cluster.proxy is not None, "premise: the mitm topology runs a proxy"
    return cluster.proxy


def _wire_kid(wire: bytes) -> str:
    kid = jws_kid(json.loads(wire)["auth"]["jws"])
    assert kid is not None
    return kid


@pytest.mark.timeout(300)
def test_m6_pinned_cluster_does_cross_ship_work_with_signed_provenance(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="mitm") as cluster:
        minted = cluster.mint()
        cluster.boot()
        path, _ = cluster.write_token("node-2")

        out = cluster.forward(path)

        assert out["ok"] and (out["answered"], out["admitted"], out["unknown"]) == (1, 1, 0), out
        assert _received(cluster) == 1
        proxy = _proxy(cluster)
        for lane in ("1to2", "2to1"):
            payloads = proxy.seen(lane)
            assert payloads, lane  # premise: traffic crossed the lane
            for payload in payloads:
                auth = json.loads(payload).get("auth")
                assert type(auth) is dict and type(auth.get("jws")) is str and auth["jws"], payload[:300]
        (request,) = proxy.seen("1to2", "intent_request")
        (response,) = proxy.seen("2to1", "intent_response")
        assert json.loads(response)["message_id"] == json.loads(request)["message_id"]
        cluster.stop(*NODES)
        for receiver, sender in (("node-2", "node-1"), ("node-1", "node-2")):
            ((source, did, key_seq, key_ids_json),) = cluster.store_rows(receiver)
            assert (source, did, key_seq) == (sender, minted[sender].did, minted[sender].key_seq), receiver
            assert minted[sender].kid in json.loads(key_ids_json), receiver
        for name in NODES:
            assert cluster.refusal_lines(name) == [], name
        assert cluster.port_retries == []


@pytest.mark.timeout(300)
def test_m6_partition_admits_nothing_and_heals_without_rekeying(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="mitm") as cluster:
        minted = cluster.mint()
        cluster.boot()
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]  # premise: the proxied path works
        assert _received(cluster) == 1

        _proxy(cluster).set_drop(True)
        cut = cluster.forward(path)

        assert not cut["ok"] and (cut["unknown"], cut["answered"]) == (1, 0), cut
        assert _received(cluster) == 1  # nothing crossed the partition
        _proxy(cluster).set_drop(False)
        healed = cluster.forward(path)
        assert healed["ok"], healed
        assert _received(cluster) == 2
        for name in NODES:
            assert cluster.status(name)["kid"] == minted[name].kid, name  # healed without re-keying
            assert cluster.refusal_lines(name) == [], name


@pytest.mark.timeout(300)
def test_m6_duplicate_runs_once_and_restart_refuses_a_pre_restart_replay(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="mitm") as cluster:
        cluster.mint()
        cluster.boot()
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]

        _proxy(cluster).duplicate_next("1to2")
        assert cluster.forward(path)["ok"]
        assert cluster.forward(path)["ok"]  # a barrier: node-2 handles its inbound in order

        assert len(_proxy(cluster).seen("1to2", "intent_request")) == 3  # premise: three requests, one doubled
        assert _received(cluster) == 3
        first_run = cluster.run_of("node-2")
        assert cluster.log("node-2", first_run).count(_DUPLICATE) == 1
        pre = _proxy(cluster).seen("1to2", "intent_request")[0]
        cluster.restart("node-2")
        restarted = cluster.run_of("node-2")
        assert restarted == first_run + 1
        assert cluster.forward(path)["ok"]
        assert _received(cluster) == 1  # the counter is per process (H12)
        _proxy(cluster).inject("1to2", pre)
        assert cluster.forward(path)["ok"]  # a barrier
        assert _received(cluster) == 2
        assert _DUPLICATE in cluster.log("node-2", restarted)


@pytest.mark.timeout(300)
def test_m6_stale_key_replay_is_refused_after_rotation(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="mitm") as cluster:
        minted = cluster.mint()
        cluster.boot()
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]
        (pre,) = _proxy(cluster).seen("1to2", "intent_request")

        rotated = cluster.rotate("node-1")

        assert rotated["key_seq"] == minted["node-1"].key_seq + 1 and rotated["kid"] != minted["node-1"].kid
        assert cluster.forward(path)["ok"]  # node-2's hold grows to the rotated key
        assert _STALE_KEY not in cluster.log("node-2")  # premise: nothing stale yet
        _proxy(cluster).inject("1to2", pre)
        assert cluster.forward(path)["ok"]  # a barrier
        assert _received(cluster) == 3
        assert _STALE_KEY in cluster.log("node-2")


@pytest.mark.timeout(300)
def test_m6_malicious_peers_are_refused_and_the_genuine_peer_is_admitted(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="direct") as cluster:
        minted = cluster.mint()
        cluster.boot("node-2")
        node_1_did = minted["node-1"].did
        assert node_1_did.startswith(_DID_PREFIX)
        request = {"intent": "read_file", "params": {"path": "/never/read"}, "id": "t5-request"}
        unconfigured = _sealed_wire(
            tmp_path / "x", instance_id="ship-x", source="node-x", target="node-2", kind="intent_request",
            payload=request,
        )
        impostor = _sealed_wire(
            tmp_path / "imp", instance_id=node_1_did.removeprefix(_DID_PREFIX), source="node-1", target="node-2",
            kind="intent_request", payload=request,
        )
        impostor_kid = _wire_kid(impostor)
        assert impostor_kid.split("#")[0] == node_1_did and impostor_kid != minted["node-1"].kid  # premise

        for payload, identity in (
            (unconfigured, b"t5-unconfigured"), (impostor, b"t5-impostor"), (_unsigned_ping("t5-unsigned"), b"t5-unsigned"),
        ):
            _send_raw(cluster.router_port("node-2"), payload, identity)

        cluster.wait_for_log("node-2", "from 'node-x' refused (unconfigured source)")
        cluster.wait_for_log("node-2", "from 'node-1' rejected (pin (key))")
        cluster.wait_for_log("node-2", "from 'node-1' refused (unsigned from a pinned peer)")
        assert _received(cluster) == 0
        cluster.boot("node-1")
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]
        assert _received(cluster) == 1
        cluster.stop(*NODES)
        ((source, did, _, key_ids_json),) = cluster.store_rows("node-2")
        assert (source, did) == ("node-1", node_1_did)
        key_ids = json.loads(key_ids_json)
        assert minted["node-1"].kid in key_ids and impostor_kid not in key_ids


@pytest.mark.timeout(300)
def test_m6_restarted_peer_is_not_locked_out_by_a_routing_id_squatter(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="direct") as cluster:
        cluster.mint()
        cluster.boot()
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]
        cluster.stop("node-1")
        context = zmq.Context()
        squatter = context.socket(zmq.DEALER)
        try:
            squatter.setsockopt(zmq.LINGER, 0)
            squatter.setsockopt(zmq.IDENTITY, b"node-1")
            squatter.connect(f"tcp://127.0.0.1:{cluster.router_port('node-2')}")
            squatter.send(_unsigned_ping("t6-squatter"))
            cluster.wait_for_log("node-2", _UNSIGNED_FROM_NODE_1)  # premise: the squatter holds the routing id

            cluster.boot("node-1")
            out = cluster.forward(path)  # while the squatter is still connected

            assert out["ok"] and out["answered"] == 1, out  # without hardening this times out (probe PQ Q-b)
        finally:
            squatter.close(linger=0)
            context.term()
