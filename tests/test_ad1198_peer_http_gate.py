"""AD-1198 slice 3a (#1135) M8: a pinned peer fetches an attachment over real HTTP, with no bearer token.

Two real ProbOS processes from the shipped ``config/node-1.yaml`` and ``config/node-2.yaml`` on slice 1's cluster
harness (``tests/fixtures/federation_cluster.py``), extended to serve each node's production main API
(``create_app(runtime)``) with uvicorn on its own 127.0.0.1 port, which the other node names as that peer's
``api_url``. Both ship keys are minted with federation off; each node then boots pinned to the other's minted key
under envelope policy ``require`` with peer admission armed. Node-1 serves attachments and holds a crew-scope
token; node-2 auto-resolves attachments and holds no crew token and no A2A outbound peer. Before node-2 boots,
real HTTP to node-1 shows the crew token refused on both routes, a malformed request refused, an impostor of
node-2 refused at first contact and an unconfigured ship refused. Then node-1 forwards an intent that references
the attachment, and node-2 fetches it with a signed request before its broadcast.

The test is synchronous (in-test signing runs through ``asyncio.run``), and its own HTTP client ignores proxy
variables (H6). The harness kills every child process when it closes. No test reaches the real OS keyring
(AD-1196's autouse guard is imported, H5) or a live service.
"""

from __future__ import annotations

import secrets
from pathlib import Path

import httpx
import pytest

from tests.fixtures.federation_cluster import NODES, ClusterHarness, child_env, node_dir
from tests.test_ad1196_did_key_binding import _no_real_os_keyring  # noqa: F401 -- the autouse guard (H5)
from tests.test_ad1198_cluster_gate import _sealed_wire

pytestmark = [pytest.mark.slow, pytest.mark.heavy_fixture]

_PNG = b"\x89PNG\r\n\x1a\n" + b"ad1198-slice-3a-cross-process-attachment"
_DID_PREFIX = "did:probos:"
_JSON = {"Content-Type": "application/json"}
_REFUSED = {"detail": "peer_request_refused"}


@pytest.mark.timeout(300)
def test_s3_pinned_peer_fetches_an_attachment_over_real_http_with_no_bearer_token(tmp_path: Path) -> None:
    crew = secrets.token_urlsafe(32)
    extras = {
        "node-1": {
            "attachments": {"serve_remote_enabled": True}, "auth": {"crew_scope_token": crew},
            "federation": {"forward_timeout_ms": 10000},
        },
        "node-2": {"attachments": {"auto_resolve_remote_enabled": True}},
    }
    with ClusterHarness(tmp_path, topology="direct", http=True, extras=extras) as cluster:
        minted = cluster.mint()
        cluster.boot("node-1")
        sha = cluster.put_attachment("node-1", _PNG, "image/png")
        node_2_did = minted["node-2"].did
        assert node_2_did.startswith(_DID_PREFIX)  # premise: the impostor below copies a did:probos DID
        impostor = _sealed_wire(
            tmp_path / "imp", instance_id=node_2_did.removeprefix(_DID_PREFIX), source="node-2", target="node-1",
            kind="attachment_request", payload={"content_hash": sha},
        )
        unconfigured = _sealed_wire(
            tmp_path / "x", instance_id="ship-x", source="node-x", target="node-1", kind="attachment_request",
            payload={"content_hash": sha},
        )
        route = f"/api/federation/attachments/{sha}"
        with httpx.Client(base_url=cluster.api_url("node-1"), trust_env=False, timeout=30.0) as http:
            crew_get = http.get(route, headers={"Authorization": f"Bearer {crew}"})
            assert (crew_get.status_code, crew_get.json()) == (403, {"detail": "federation_peer_request_required"})
            cluster.wait_for_log("node-1", "crew-scope token was presented")
            empty = http.post(route, content=b"{}", headers=_JSON)
            assert (empty.status_code, empty.json()) == (401, _REFUSED)
            crew_post = http.post(route, content=impostor, headers={**_JSON, "Authorization": f"Bearer {crew}"})
            assert (crew_post.status_code, crew_post.json()) == (401, _REFUSED)
            cluster.wait_for_log("node-1", "presented this ship's crew-scope token")
            refused_impostor = http.post(route, content=impostor, headers=_JSON)
            assert (refused_impostor.status_code, refused_impostor.json()) == (401, _REFUSED)
            impostor_line = cluster.wait_for_log(
                "node-1", "envelope 'attachment_request' from 'node-2' rejected (pin (key))",
            )
            refused_unconfigured = http.post(route, content=unconfigured, headers=_JSON)
            assert (refused_unconfigured.status_code, refused_unconfigured.json()) == (401, _REFUSED)
            unconfigured_line = cluster.wait_for_log("node-1", "from 'node-x' refused (unconfigured source)")

        cluster.boot("node-2")
        config_text = (node_dir(tmp_path, "node-2") / "pinned.yaml").read_text(encoding="utf-8")
        environment = child_env(tmp_path, "node-2", node_dir(tmp_path, "node-2") / "d")
        for needle in (crew, "outbound_peers"):  # F-6 isolation premise: node-2 holds no crew token, no outbound peer
            assert needle not in config_text, needle
            assert not any(needle in value for value in environment.values()), needle
        assert not cluster.has_attachment("node-2", sha)  # premise: node-2 does not hold the attachment yet
        token_path, _ = cluster.write_token("node-2")

        out = cluster.forward(token_path, params={"attachment_ref": sha})

        assert out["ok"], out
        assert cluster.has_attachment("node-2", sha)
        cluster.stop(*NODES)
        for name in NODES:
            assert cluster.last_stopped[name]["peer_requests_released"] is True, name
        assert cluster.refusal_lines("node-1") == [impostor_line, unconfigured_line]
        assert cluster.refusal_lines("node-2") == []
        assert len(cluster.port_retries) <= 1, cluster.port_retries
