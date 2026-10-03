"""AD-1198 slice 3b (#1135): a pinned peer calls a ship's A2A server over real HTTP, as itself.

Two real ProbOS processes from the shipped ``config/node-1.yaml`` and ``config/node-2.yaml`` on slice 1's cluster
harness (``tests/fixtures/federation_cluster.py``) with ``a2a=True``: each pinned node's A2A server is bound to its
own reserved 127.0.0.1 port, and node-1's is enabled, with a bearer token and ``read_file`` exposed. Both ship keys
are minted with federation off; each node then boots pinned to the other's minted key under envelope policy
``require`` with peer admission armed. Before node-2 boots, real HTTP to node-1's A2A server shows the agent card
unchanged, and a request with no credential, an impostor of node-2 and an unconfigured ship all refused with
BF-876's 401. Then node-2 signs an A2A request with its own runtime's peer requests: node-1 runs it as
``a2a-node:node-2`` whatever ``x-a2a-peer-id`` says, serves a bearer holder as the one caller ``a2a-bearer``
whatever ``x-a2a-peer-id`` says, keeps each caller's task of the same id apart, and refuses a replay of node-2's body.

The test is synchronous (in-test signing runs through ``asyncio.run``), and its own HTTP clients ignore proxy
variables (H6). The harness kills every child process when it closes. No test reaches the real OS keyring
(AD-1196's autouse guard is imported, H5) or a live service.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.fixtures.federation_cluster import NODES, ClusterHarness
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)
from tests.test_ad1198_cluster_gate import _sealed_wire

pytestmark = [pytest.mark.slow, pytest.mark.heavy_fixture]

_DID_PREFIX = "did:probos:"
_JSON = {"Content-Type": "application/json"}
_REFUSED = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request: authentication failed"}}
_CARD_TIMEOUT_S = 30.0


def _read_file(path: str, *, request_id: str, task_id: str) -> dict[str, Any]:
    """A ``tasks/send`` of ``read_file(path)``, shaped as ``A2AClient.send_task`` sends one."""
    text = "read_file:" + json.dumps({"path": path})
    return {"jsonrpc": "2.0", "id": request_id, "method": "tasks/send", "params": {
        "id": task_id, "sessionId": "", "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
    }}


def _get(task_id: str, *, request_id: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tasks/get", "params": {"id": task_id}}


def _artifact(result: dict[str, Any]) -> str:
    return str(result["artifacts"][0]["parts"][0]["text"])


def _refused(response: httpx.Response) -> bool:
    """BF-876's 401 for a request with no valid credential, byte for byte in its JSON."""
    return (response.status_code, response.headers.get("www-authenticate"), response.json()) == (401, "Bearer", _REFUSED)


def _card(http: httpx.Client) -> dict[str, Any]:
    """Node-1's agent card once its A2A server answers: a bounded poll, never a bare sleep."""
    deadline = time.monotonic() + _CARD_TIMEOUT_S
    while True:
        try:
            response = http.get("/.well-known/agent.json")
            if response.status_code == 200:
                return dict(response.json())
        except httpx.TransportError:
            pass
        if time.monotonic() >= deadline:
            raise AssertionError(f"node-1's A2A server did not answer within {_CARD_TIMEOUT_S:g} s")
        time.sleep(0.1)


@pytest.mark.timeout(300)
def test_s3b_pinned_peer_calls_a2a_over_real_http_as_itself(tmp_path: Path) -> None:
    token = secrets.token_urlsafe(32)
    extras = {"node-1": {"federation.a2a": {"enabled": True, "auth_token": token, "exposed_intents": ["read_file"]}}}
    with ClusterHarness(tmp_path, topology="direct", a2a=True, extras=extras) as cluster:
        minted = cluster.mint()
        cluster.boot("node-1")
        bearer_path, bearer_secret = cluster.write_token("node-1")
        peer_path, peer_secret = cluster.write_token("node-1")
        node_2_did = minted["node-2"].did
        assert node_2_did.startswith(_DID_PREFIX)  # premise: the impostor below copies a did:probos DID
        impostor = _sealed_wire(
            tmp_path / "imp", instance_id=node_2_did.removeprefix(_DID_PREFIX), source="node-2", target="node-1",
            kind="a2a_request", payload=_read_file(peer_path, request_id="i1", task_id="shared"),
        )
        unconfigured = _sealed_wire(
            tmp_path / "x", instance_id="ship-x", source="node-x", target="node-1", kind="a2a_request",
            payload=_read_file(peer_path, request_id="x1", task_id="shared"),
        )
        with httpx.Client(base_url=cluster.a2a_url("node-1"), trust_env=False, timeout=30.0) as http:
            card = _card(http)
            assert card["security"] == [{"bearer": []}]  # the card is BF-876's, armed or not
            assert _refused(http.post("/a2a", json=_read_file(bearer_path, request_id="n1", task_id="shared")))
            assert _refused(http.post("/a2a", content=impostor, headers=_JSON))
            impostor_line = cluster.wait_for_log("node-1", "envelope 'a2a_request' from 'node-2' rejected (pin (key))")
            assert _refused(http.post("/a2a", content=unconfigured, headers=_JSON))
            unconfigured_line = cluster.wait_for_log(
                "node-1", "envelope 'a2a_request' from 'node-x' refused (unconfigured source)",
            )

        cluster.boot("node-2")
        sent = cluster.a2a_post(
            "node-2", "node-1", _read_file(peer_path, request_id="p1", task_id="shared"),
            headers={"x-a2a-peer-id": "node-x"},
        )
        assert sent["signed"] is True and sent["status"] == 200, sent
        assert sent["response"]["result"]["status"]["state"] == "completed", sent
        assert peer_secret in _artifact(sent["response"]["result"]) and bearer_secret not in json.dumps(sent)
        with httpx.Client(base_url=cluster.a2a_url("node-1"), trust_env=False, timeout=30.0) as http:
            bearer = http.post(
                "/a2a", json=_read_file(bearer_path, request_id="b1", task_id="shared"),
                headers={"Authorization": f"Bearer {token}", "x-a2a-peer-id": "node-2"},
            )
            assert bearer.status_code == 200 and bearer.json()["result"]["status"]["state"] == "completed", bearer.text
            assert bearer_secret in _artifact(bearer.json()["result"])
            assert _refused(http.post("/a2a", content=bytes.fromhex(sent["body"]), headers=_JSON))  # a replay
            duplicate_line = cluster.wait_for_log("node-1", "envelope 'a2a_request' from 'node-2' rejected (duplicate)")
            theirs = http.post("/a2a", json=_get("shared", request_id="b2"), headers={"Authorization": f"Bearer {token}"})
            assert theirs.status_code == 200 and theirs.json()["result"] == bearer.json()["result"]
        mine = cluster.a2a_post("node-2", "node-1", _get("shared", request_id="p2"))
        assert mine["status"] == 200 and mine["response"]["result"] == sent["response"]["result"], mine
        assert cluster.a2a_callers("node-1") == [["a2a-bearer", "a2a-bearer"], ["a2a-node:node-2", "a2a-node:node-2"]]
        cluster.stop(*NODES)
        assert cluster.refusal_lines("node-1") == [impostor_line, unconfigured_line, duplicate_line]
        assert cluster.refusal_lines("node-2") == []
        assert len(cluster.port_retries) <= 1, cluster.port_retries
