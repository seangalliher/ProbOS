"""AD-1198 slice 2c (#1135): the operator's audited reset between two real ProbOS processes.

Two real ProbOS processes from the shipped ``config/node-1.yaml`` and ``config/node-2.yaml`` on slice 1's cluster
harness (``tests/fixtures/federation_cluster.py``), in the shipped (direct) topology over real ZeroMQ sockets on
127.0.0.1, each serving its production main API on its own 127.0.0.1 port with a crew-scope token configured. Both ship
keys are minted with federation off; each node then boots pinned to the other's minted key under envelope policy
``require`` with peer admission armed. Gossip is slowed to an hour on both nodes, so the only envelopes are the test's own.

Node-2 holds node-1's history and, after a transfer, node-1's chain in its identity.db. Node-1 re-incepts its key through
its own AD-1196 route (no recovery key is committed at mint). Node-2 refuses node-1's next intent (``held history``);
the operator re-pins node-1 at node-2 to its new key and restarts node-2, which then refuses node-1's held history at
start for its pin -- a refusal no resync reaches and only a reset heals. The operator resets node-1 at node-2 over HTTP:
a request without the bearer is refused 401 and a wrong confirm literal 422; the reset answers what it forgot. Node-1's
next intent is a first contact under its new pin and is served, and its next transfer imports its re-incepted chain into
node-2's identity.db, which kept the earlier transfer's birth and transfer certificates.

The harness kills every child process when it closes. No test reaches the real OS keyring (AD-1196's autouse guard is
imported, H5) or a live service.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fixtures.federation_cluster import NODES, ClusterHarness, node_dir
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)

pytestmark = [pytest.mark.slow, pytest.mark.heavy_fixture]

_TOKENS = {"node-1": "ad1198-s2c-node-1-crew-scope-token", "node-2": "ad1198-s2c-node-2-crew-scope-token"}
_EXTRAS = {
    name: {"federation": {"gossip_interval_seconds": 3600}, "auth": {"crew_scope_token": _TOKENS[name]}}
    for name in NODES
}
_RESET = "/api/identity/peers/node-1/reset"


def _post(cluster: ClusterHarness, name: str, path: str, body: dict[str, Any], token: str | None) -> httpx.Response:
    """A POST to ``name``'s production main API, as the operator sends it."""
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=cluster.api_url(name), trust_env=False, timeout=30.0) as client:
        return client.post(path, json=body, headers=headers)


@pytest.mark.timeout(480)
def test_s2c_an_operator_reset_over_http_lets_a_re_incepted_peer_back_in_between_two_real_nodes(tmp_path: Path) -> None:
    with ClusterHarness(tmp_path, topology="direct", http=True, extras=_EXTRAS) as cluster:
        minted = cluster.mint()
        ready = cluster.boot()
        assert all(ready[name]["identity_exchange"] is True for name in NODES), ready  # armed: both exchanges wired
        path, _ = cluster.write_token("node-2")
        assert cluster.forward(path)["ok"]  # node-2 holds node-1 at its minted key
        first = cluster.transfer("node-1", "node-2")  # node-2's identity.db now stores node-1's chain
        assert first["accepted"] is True, first
        stored = cluster.foreign("node-2", first["agent_uuid"], first["did"], first["origin_ship_did"])

        reincepted = _post(
            cluster, "node-1", "/api/identity/keys/reinception", {"reason": "lost", "confirm": "abandon-key-continuity"},
            _TOKENS["node-1"],
        )
        assert reincepted.status_code == 200, reincepted.text
        new_key = cluster.status("node-1")["public_key"]
        refused = cluster.forward(path)
        cluster.wait_for_log("node-2", "envelope 'intent_request' from 'node-1' rejected (held history)")
        cluster.minted["node-1"] = dataclasses.replace(minted["node-1"], public_key=new_key)  # the operator re-pins node-1
        cluster.restart("node-2")
        cluster.wait_for_log("node-2", "the key history held for 'node-1' does not satisfy its identity pin (pin (key))")
        still = cluster.forward(path)

        unauthorised = _post(cluster, "node-2", _RESET, {"confirm": "forget-held-key-history"}, None)
        wrong = _post(cluster, "node-2", _RESET, {"confirm": "forget"}, _TOKENS["node-2"])
        reset = _post(
            cluster, "node-2", _RESET, {"confirm": "forget-held-key-history", "note": "node-1 re-incepted after a lost key"},
            _TOKENS["node-2"],
        )
        after = cluster.forward(path)  # node-1's next envelope: a first contact under its new pin
        second = cluster.transfer("node-1", "node-2")  # its re-incepted chain is imported as a first one
        arrived = cluster.foreign("node-2", second["agent_uuid"], second["did"], second["origin_ship_did"])
        cluster.stop(*NODES)

        assert (refused["ok"], still["ok"], after["ok"]) == (False, False, True)
        assert (unauthorised.status_code, wrong.status_code) == (401, 422)
        assert reset.status_code == 200, reset.text
        assert reset.json() == {
            "node_id": "node-1", "forgotten": True, "did": minted["node-1"].did, "key_seq": None,
            "refused_at_start": True, "identity_chain_blocks": stored["foreign_chain_blocks"],
        }
        assert second["accepted"] is True, second
        assert arrived["foreign_chain_blocks"] is not None and arrived["foreign_chain_blocks"] > stored["foreign_chain_blocks"]
        assert sorted(arrived["transfers"]) == sorted([["incoming", first["certificate_hash"]], ["incoming", second["certificate_hash"]]])
        ((_, did, key_seq, key_ids),) = [row for row in cluster.store_rows("node-2") if row[0] == "node-1"]
        assert (did, key_seq, len(json.loads(key_ids))) == (minted["node-1"].did, 1, 2)  # held again from its first contact
        with contextlib.closing(sqlite3.connect(node_dir(tmp_path, "node-2") / "d" / "identity.db")) as db:
            births = db.execute("SELECT did FROM foreign_birth_certificates").fetchall()
        assert births == [(first["did"],)]  # the transferred crew member's record is kept through the reset
        assert "AD-1198: reset the key history held for 'node-1' on the operator's request" in cluster.log("node-2")
        assert cluster.refusal_lines("node-1") == []
        assert len(cluster.port_retries) <= 1, cluster.port_retries
