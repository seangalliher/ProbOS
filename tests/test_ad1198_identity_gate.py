"""AD-1198 slice 2a (#1135): identity continuity between two real ProbOS processes -- a resync heals a key-history gap,
and a crew member transfers from one ship to the other with its provenance (AD-443e/f), with no shared filesystem or
database.

Two real ProbOS processes from the shipped ``config/node-1.yaml`` and ``config/node-2.yaml`` on slice 1's cluster
harness (``tests/fixtures/federation_cluster.py``), in the shipped (direct) topology over real ZeroMQ sockets on
127.0.0.1. Both ship keys are minted with federation off; each node then boots pinned to the other's minted key under
envelope policy ``require`` with peer admission armed, which also arms the identity exchange. Gossip is slowed to an
hour on both nodes, so the only envelopes are the test's own.

The resync: node-2 holds node-1's history after one forwarded intent; node-1 rotates 33 times, more than an envelope
carries; its next intent is refused at node-2 for a key history gap, node-2 fetches node-1's chain over the bridge and
resynchronises, and node-1's next intent is served; node-2 then restarts, judges the resynchronised hold's pin on the
chain its identity.db stores for node-1 (Amendment A-1), and serves node-1's next intent again. The transfer: node-1 issues a transfer certificate for one of its
crew and sends it with its chain; node-2 refuses one that names another ship, accepts one that names node-2, and its
identity registry then holds the crew member's record from node-1's vessel, the incoming certificate and node-1's chain.

The harness kills every child process when it closes. No test reaches the real OS keyring (AD-1196's autouse guard is
imported, H5) or a live service.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

import pytest

from probos.federation.envelope import MAX_KEY_EVENTS
from tests.fixtures.federation_cluster import NODES, ClusterHarness, node_dir
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)

pytestmark = [pytest.mark.slow, pytest.mark.heavy_fixture]

_QUIET = {name: {"federation": {"gossip_interval_seconds": 3600}} for name in NODES}  # no envelope but the test's own
_GAP = MAX_KEY_EVENTS + 1


@pytest.mark.timeout(300)
def test_s2a_a_key_history_gap_heals_by_resync_between_two_real_nodes_and_stays_healed_after_a_restart(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="direct", extras=_QUIET) as cluster:
        minted = cluster.mint()
        ready = cluster.boot()
        assert all(ready[name]["identity_exchange"] is True for name in NODES), ready  # armed: both exchanges wired
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]  # node-2 holds node-1 at its minted key, and node-1 holds node-2
        for _ in range(_GAP):
            cluster.rotate("node-1")
        assert cluster.status("node-1")["key_seq"] == minted["node-1"].key_seq + _GAP  # premise: 33 unseen key events

        missed = cluster.forward(path)
        gap = cluster.wait_for_log("node-2", "envelope 'intent_request' from 'node-1' rejected (key history gap)")
        cluster.wait_for_log(
            "node-2", f"resynchronised the key history held for 'node-1' from its chain (key seq {_GAP})",
        )
        again = cluster.forward(path)

        assert (missed["ok"], missed["unknown"]) == (False, 1), missed
        assert again["ok"] is True, again
        restarted = cluster.restart("node-2")  # A-1: the resynchronised hold is judged at start on identity.db's chain
        assert restarted["identity_exchange"] is True, restarted
        cluster.wait_for_log(
            "node-2", f"the key history held for it satisfies its identity pin (key seq {_GAP}); it is held",
        )
        after = cluster.forward(path)
        assert after["ok"] is True, after
        cluster.stop(*NODES)
        assert all(cluster.last_stopped[name]["identity_exchange_released"] is True for name in NODES)
        ((_, did, key_seq, key_ids),) = [row for row in cluster.store_rows("node-2") if row[0] == "node-1"]
        assert (did, key_seq) == (minted["node-1"].did, _GAP)
        assert len(json.loads(key_ids)) == _GAP + 1  # every key node-1 used, the ones the gap introduced included
        assert cluster.refusal_lines("node-2") == [gap]
        assert cluster.refusal_lines("node-1") == []
        assert "AD-1198: identity" not in cluster.log("node-2")  # no identity exchange refusal on the way
        assert "does not satisfy its identity pin" not in cluster.log("node-2")  # A-1: the hold was kept at the restart
        assert len(cluster.port_retries) <= 1, cluster.port_retries


@pytest.mark.timeout(300)
def test_s2a_a_crew_member_transfers_between_two_real_nodes_with_its_provenance(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="direct", extras=_QUIET) as cluster:
        minted = cluster.mint()
        ready = cluster.boot()
        assert all(ready[name]["identity_exchange"] is True for name in NODES), ready

        elsewhere = cluster.transfer("node-1", "node-2", target_did="did:probos:ship-x")
        moved = cluster.transfer("node-1", "node-2")
        arrived = cluster.foreign("node-2", moved["agent_uuid"], moved["did"], moved["origin_ship_did"])
        left = cluster.foreign("node-1", moved["agent_uuid"], moved["did"], moved["origin_ship_did"])

        assert (elsewhere["accepted"], elsewhere["message"]) == (False, "identity exchange refused (not for this ship)")
        assert (moved["accepted"], moved["message"]) == (True, f"Certificate imported: {moved['did']}"), moved
        assert moved["origin_ship_did"] == minted["node-1"].did
        assert (arrived["found"], arrived["did"], arrived["vessel_name"]) == (True, moved["did"], moved["origin_vessel"])
        assert arrived["transfers"] == [["incoming", moved["certificate_hash"]]]
        assert arrived["foreign_chain_blocks"] is not None and arrived["foreign_chain_blocks"] > 2
        assert left["transfers"] == sorted([["outgoing", elsewhere["certificate_hash"]], ["outgoing", moved["certificate_hash"]]])
        assert left["foreign_chain_blocks"] is None
        cluster.stop(*NODES)
        assert all(cluster.last_stopped[name]["identity_exchange_released"] is True for name in NODES)
        databases = {name: node_dir(tmp_path, name) / "d" / "identity.db" for name in NODES}
        assert all(path.is_file() for path in databases.values()) and len(set(databases.values())) == 2
        with contextlib.closing(sqlite3.connect(databases["node-2"])) as db:
            foreign = db.execute("SELECT did, origin_ship_did FROM foreign_birth_certificates").fetchall()
            chains = db.execute("SELECT origin_ship_did FROM foreign_chains").fetchall()
        with contextlib.closing(sqlite3.connect(databases["node-1"])) as db:
            outgoing = db.execute("SELECT certificate_hash FROM transfer_certificates WHERE direction = 'outgoing'").fetchall()
        assert foreign == [(moved["did"], minted["node-1"].did)] and chains == [(minted["node-1"].did,)]
        assert sorted(outgoing) == sorted([(elsewhere["certificate_hash"],), (moved["certificate_hash"],)])
        assert cluster.refusal_lines("node-1") == [] and cluster.refusal_lines("node-2") == []
        assert len(cluster.port_retries) <= 1, cluster.port_retries
