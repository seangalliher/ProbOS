"""AD-1198 slice 2b-iii (#1135): a recovery heals a held fork between two real ProbOS processes -- node-2's resync moves
both of its holds onto node-1's branch (slice 2b-i) and marks the transfer it accepted from the replaced branch (slice
2b-ii), as node-2's agent identity endpoint shows before and after node-2 restarts.

Two real ProbOS processes from the shipped ``config/node-1.yaml`` and ``config/node-2.yaml`` on slice 1's cluster
harness (``tests/fixtures/federation_cluster.py``), in the shipped (direct) topology over real ZeroMQ sockets on
127.0.0.1, each serving its production main API on its own 127.0.0.1 port with a crew-scope token configured. Node-1's
mint commits the Captain's recovery public key at its inception; the private half never leaves this (the parent)
process. Both nodes then boot pinned to each other's minted key under envelope policy ``require`` with peer admission
armed. Gossip is slowed to an hour on both nodes, so the only envelopes are the test's own.

The fork: node-1 stops and the harness copies its data directory to a fresh root, from which a fork boots as node-1 --
the same node id, ports, ledger and keys; one run per node, so the fork never runs beside node-1; nothing on disk is
shared. The fork rotates its key and transfers a crew member to node-2: node-2's envelope hold follows the fork's branch,
and its identity.db stores the fork's chain and accepts the transfer, which is anchored only on that branch. The fork
stops, and node-1 boots from its own data directory, which never saw the fork's rotation, and recovers its key through
its own AD-1196 route: prepared on node-1, signed here with the recovery key, applied on node-1. Node-1's next intent is
refused at node-2 for a held history; node-2's resync fetches node-1's chain, whose recovery takes precedence over the
fork's rotation, and moves identity.db's stored chain -- marking the transfer in the same unit, never deleting it -- and
then the envelope hold onto node-1's branch. Node-1's next intent is served; node-2 restarts, its endpoint shows the
same mark, and node-1's intent is served again.

A second test drives the fork producer's own refusals without starting a process. The harness kills every child process
when it closes. No test reaches the real OS keyring (AD-1196's autouse guard is imported, H5) or a live service.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.identity_keys import generate_recovery_keypair, sign_recovery_authorization
from tests.fixtures.federation_cluster import NODES, ClusterHarness, Identity, node_dir
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)

pytestmark = [pytest.mark.slow, pytest.mark.heavy_fixture]

_SLOT = "ad1198-s2biii-transferred"
_NOT_ANCHORED = "transfer certificate is not anchored on the origin's ledger"
_HELD_HISTORY = "AD-1197: envelope 'intent_request' from 'node-1' rejected (held history); not delivered"
_RESYNCED = "AD-1198: resynchronised the key history held for 'node-1' from its chain (key seq 1)"
_REANCHORED = (
    "AD-1198: re-anchored the key history held for 'node-1' on the branch its chain carries: the recovery at key seq 1 "
    "takes precedence over the held events from there (key seq 1 -> 1); its replay windows start again, and the 3 key ids "
    "recorded for it, of both branches, stay recorded"
)
_MARKED = "is not supported by the chain identity.db stores"
_RESYNC_S = 60.0  # bounds the resync: node-2's 2 s chain request, BF-885's 6 s identity.db unit, the guard's 6 s store write


def _api(
    cluster: ClusterHarness, tokens: dict[str, str], name: str, method: str, path: str, body: dict[str, Any] | None = None,
) -> httpx.Response:
    """One request to ``name``'s production main API with ``name``'s crew-scope token from this test's ``tokens``, as
    the operator sends it."""
    headers = {"Authorization": f"Bearer {tokens[name]}"}
    with httpx.Client(base_url=cluster.api_url(name), trust_env=False, timeout=30.0) as client:
        return client.request(method, path, json=body, headers=headers)


def _identity(cluster: ClusterHarness) -> httpx.Response:
    """Node-2's agent identity endpoint for the transferred crew member's slot (the route takes no token)."""
    with httpx.Client(base_url=cluster.api_url("node-2"), trust_env=False, timeout=30.0) as client:
        return client.get(f"/api/agent/{_SLOT}/identity")


def _recover(
    cluster: ClusterHarness, tokens: dict[str, str], recovery_private_key: str,
) -> tuple[httpx.Response, httpx.Response]:
    """Node-1 recovers its key, reason ``lost``, through its own AD-1196 route: prepared on node-1, the payload it returns
    signed here with the Captain's offline recovery key, then applied on node-1."""
    body = {"reason": "lost", "note": "AD-1198 slice 2b-iii: node-1 recovers its key after a fork"}
    prepared = _api(cluster, tokens, "node-1", "POST", "/api/identity/keys/recovery", body)
    assert prepared.status_code == 200 and prepared.json()["stage"] == "authorize", prepared.text  # premise: prepared
    authorization = sign_recovery_authorization(recovery_private_key, prepared.json()["signing_payload"])
    applied = _api(cluster, tokens, "node-1", "POST", "/api/identity/keys/recovery", {**body, "authorization": authorization})
    return prepared, applied


def _rows(database: Path, query: str) -> list[tuple[Any, ...]]:
    """``query``'s rows from a stopped node's ``database``."""
    assert database.is_file(), database
    with contextlib.closing(sqlite3.connect(database)) as db:
        return db.execute(query).fetchall()


def _lines(log: str, text: str) -> list[int]:
    """The numbers of ``log``'s lines that contain ``text``."""
    return [number for number, line in enumerate(log.splitlines()) if text in line]


@pytest.mark.timeout(480)  # a cap over the harness's own bounds for seven boots, as slice 2c's four-boot gate caps its own
def test_s2biii_a_recovery_re_anchors_a_held_fork_and_marks_its_transfer_between_two_real_nodes(tmp_path: Path) -> None:
    private, public = generate_recovery_keypair()  # the Captain's recovery key: only its public half reaches a node
    tokens = {name: secrets.token_urlsafe(32) for name in NODES}  # each node's crew-scope token, new in every run
    extras = {
        name: {"federation": {"gossip_interval_seconds": 3600}, "auth": {"crew_scope_token": tokens[name]}}
        for name in NODES
    }
    with ClusterHarness(
        tmp_path, topology="direct", http=True, extras=extras, recovery_public_keys={"node-1": public},
    ) as cluster:
        minted = cluster.mint()
        ready = cluster.boot()
        assert all(ready[name]["identity_exchange"] is True for name in NODES), ready  # armed: both exchanges wired
        keys = _api(cluster, tokens, "node-1", "GET", "/api/identity/keys")
        assert keys.status_code == 200 and keys.json()["recovery_committed"] is True, keys.text  # premise: committed at mint
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]  # node-2 holds node-1 at its minted key

        cluster.stop("node-1")
        copy = cluster.fork("node-1", tmp_path / "fork")
        cluster.boot("node-1")  # the fork, as node-1, from the copy: the harness asserts its minted key id
        rotated = cluster.rotate("node-1")  # the fork's branch parts from node-1's here
        moved = cluster.transfer("node-1", "node-2")  # node-2's hold follows the fork; identity.db stores its chain
        slotted = cluster.slot("node-2", moved["agent_uuid"], _SLOT)
        unmarked = _identity(cluster)
        cluster.stop("node-1")
        cluster.unfork("node-1")

        cluster.boot("node-1")  # node-1 from its own data directory, which never saw the fork's rotation
        before = cluster.status("node-1")
        prepared, applied = _recover(cluster, tokens, private)
        recovered = cluster.status("node-1")
        ledger = _api(cluster, tokens, "node-1", "GET", "/api/identity/ledger")
        assert cluster.refusal_lines("node-2") == [], "premise: node-2's first resync of node-1 is the one the recovery asks"
        refused = cluster.forward(path)
        held_history = cluster.wait_for_log("node-2", _HELD_HISTORY)
        cluster.wait_for_log("node-2", _RESYNCED, timeout=_RESYNC_S)
        served = cluster.forward(path)
        marked = _identity(cluster)
        resynced_run = cluster.run_of("node-2")
        cluster.restart("node-2")
        restarted = _identity(cluster)
        again = cluster.forward(path)
        restart_run = cluster.run_of("node-2")
        cluster.stop(*NODES)

        resync_log, restart_log = cluster.log("node-2", resynced_run), cluster.log("node-2", restart_run)
        node_1_refusals, node_2_refusals = cluster.refusal_lines("node-1"), cluster.refusal_lines("node-2")
        ((_, held_did, held_seq, held_kids),) = [row for row in cluster.store_rows("node-2") if row[0] == "node-1"]

    origin = minted["node-1"].did
    chain = ledger.json()["chain"]
    mark = {
        "certificate_hash": moved["certificate_hash"], "subject_did": moved["did"], "origin_ship_did": origin,
        "reason": _NOT_ANCHORED, "chain_head": chain[-1]["block_hash"], "chain_blocks": len(chain),
    }
    # the fork: a copy of node-1 that booted as node-1, parted from it by its own rotation and issued the transfer
    assert copy == node_dir(tmp_path / "fork", "node-1") / "d"
    assert (rotated["did"], rotated["key_seq"]) == (origin, 1) and rotated["kid"] != minted["node-1"].kid
    assert (moved["accepted"], moved["message"]) == (True, f"Certificate imported: {moved['did']}"), moved
    assert moved["origin_ship_did"] == origin and slotted["assigned"] is True, slotted
    assert unmarked.status_code == 200, unmarked.text
    assert unmarked.json()["did"] == moved["did"] and set(unmarked.json()) == {"sovereign_id", "did", "birth_certificate"}
    # node-1's own data never saw the fork: its key history is its own, and its recovery is signed by the committed key
    assert (before["kid"], before["key_seq"]) == (minted["node-1"].kid, 0)
    assert (prepared.status_code, applied.status_code) == (200, 200), applied.text
    assert applied.json()["stage"] == "applied" and applied.json()["kid"] == recovered["kid"], applied.text
    assert recovered["key_seq"] == 1 and recovered["kid"] not in {minted["node-1"].kid, rotated["kid"]}
    assert ledger.status_code == 200 and ledger.json()["valid"] is True and ledger.json()["block_count"] == len(chain)
    # node-2: one refusal and one resync; identity.db moved first and marked the transfer in its unit, then the hold moved
    assert (refused["ok"], refused["unknown"]) == (False, 1), refused
    assert served["ok"] is True and again["ok"] is True, (served, again)
    assert node_2_refusals == [held_history] and node_1_refusals == []
    replaced = _lines(resync_log, f"AD-1198: the chain stored for {origin} is replaced by one whose recovery at key seq 1 ")
    marked_lines = _lines(resync_log, (
        f"AD-1198: the incoming transfer certificate {mark['certificate_hash']} of {mark['subject_did']} {_MARKED} for "
        f"{origin} ({_NOT_ANCHORED}; head {mark['chain_head']}, {mark['chain_blocks']} blocks); it is marked, never "
        "deleted, and the agent's record stays readable"
    ))
    reanchored, resynced = _lines(resync_log, _REANCHORED), _lines(resync_log, _RESYNCED)
    assert len(replaced) == len(marked_lines) == len(reanchored) == len(resynced) == 1, (replaced, marked_lines, reanchored, resynced)
    assert replaced[0] < marked_lines[0] < reanchored[0] < resynced[0]  # identity.db first (2b-i A-1), the mark in its unit
    assert _MARKED not in restart_log and "re-anchored" not in restart_log  # the restart judges again and changes nothing
    # the endpoint: the mark, before and after node-2 restarts -- the same row, loaded again at start
    assert marked.status_code == 200 and restarted.status_code == 200, (marked.text, restarted.text)
    marks = marked.json()["transfer_marks"]
    assert len(marks) == 1, marks  # one mark, before its fields are compared
    assert marks == [{**mark, "judged_at": marks[0]["judged_at"]}] and type(marks[0]["judged_at"]) is float
    assert marked.json() == {**unmarked.json(), "transfer_marks": marks}
    assert restarted.json() == marked.json()
    # both holds on node-1's branch, kept across the restart; the replaced branch's key id stays recorded
    assert (held_did, held_seq) == (origin, 1)
    assert sorted(json.loads(held_kids)) == sorted({minted["node-1"].kid, rotated["kid"], recovered["kid"]})
    databases = {
        "node-1": node_dir(tmp_path, "node-1") / "d" / "identity.db", "fork": copy / "identity.db",
        "node-2": node_dir(tmp_path, "node-2") / "d" / "identity.db",
    }
    assert len({path.resolve() for path in databases.values()}) == 3  # three identity.db files: nothing is shared
    stored = _rows(databases["node-2"], f"SELECT chain_json FROM foreign_chains WHERE origin_ship_did = '{origin}'")
    assert [json.loads(row[0]) for row in stored] == [chain]
    assert _rows(databases["node-2"], (
        "SELECT certificate_hash, subject_did, origin_ship_did, action, reason, chain_head, chain_blocks, judged_at "
        "FROM transfer_marks ORDER BY seq"
    )) == [(
        mark["certificate_hash"], mark["subject_did"], origin, "mark", _NOT_ANCHORED, mark["chain_head"],
        mark["chain_blocks"], marks[0]["judged_at"],
    )]
    assert _rows(databases["node-2"], "SELECT direction, certificate_hash FROM transfer_certificates") == [
        ("incoming", moved["certificate_hash"]),
    ]
    assert _rows(databases["node-2"], "SELECT did, origin_ship_did FROM foreign_birth_certificates") == [(moved["did"], origin)]
    assert (_SLOT, moved["agent_uuid"]) in _rows(databases["node-2"], "SELECT slot_id, agent_uuid FROM slot_mappings")
    outgoing = "SELECT certificate_hash FROM transfer_certificates WHERE direction = 'outgoing'"
    assert _rows(databases["fork"], outgoing) == [(moved["certificate_hash"],)] and _rows(databases["node-1"], outgoing) == []
    assert len(cluster.port_retries) <= 1, cluster.port_retries


def test_s2biii_a_fork_is_refused_unless_its_root_is_fresh_and_names_no_other_node(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="direct") as cluster:
        cluster.minted = {name: Identity(f"did:probos:{name}", f"did:probos:{name}#key-0", f"{name}-key", 0) for name in NODES}
        data = node_dir(tmp_path, "node-1") / "d"
        data.mkdir(parents=True)  # premise: a stopped node's data directory
        (data / "identity.db").write_bytes(b"node-1")
        with pytest.raises(AssertionError) as stale:
            cluster.fork("node-1", tmp_path)  # node-1's own directory is not a fresh root
        refused: dict[str, tuple[Path, str]] = {}
        for label, root in (("own", node_dir(tmp_path, "node-1") / "x"), ("other", node_dir(tmp_path, "node-2") / "x")):
            copy = cluster.fork("node-1", root)
            with pytest.raises(AssertionError) as named:
                cluster.boot("node-1")  # refused before any process starts
            cluster.unfork("node-1")
            refused[label] = (copy, str(named.value))
        started = cluster.run_of("node-1")

    own, other = node_dir(node_dir(tmp_path, "node-1") / "x", "node-1"), node_dir(node_dir(tmp_path, "node-2") / "x", "node-1")
    assert str(stale.value) == str((data, node_dir(tmp_path, "node-1")))
    assert refused == {
        "own": (own / "d", str((own, node_dir(tmp_path, "node-1")))),
        "other": (other / "d", str((other, node_dir(tmp_path, "node-2")))),
    }
    assert (own / "d" / "identity.db").read_bytes() == (other / "d" / "identity.db").read_bytes() == b"node-1"
    assert started == 0  # no process was started
