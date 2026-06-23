"""AD-731a-1c: receive-side auto-resolution of cross-host attachment refs (#638).

BF-287: real ``FilesystemAttachmentStore`` on ``tmp_path`` + real
``AttachmentsConfig`` / ``FederationConfig`` / ``A2APeerConfig`` — NO MagicMock
at the substrate boundary. The fetch seam uses httpx ``MockTransport`` so no
real network is touched, and the request counter proves the off path is
byte-identical (zero requests).
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import (
    A2APeerConfig,
    AttachmentsConfig,
    FederationA2AConfig,
    FederationConfig,
)
from probos.federation.attachment_resolve import (
    extract_attachment_shas,
    resolve_missing_attachments,
    resolve_sender_peer,
)


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body-for-ad731a-1c"
_PNG_SHA = hashlib.sha256(_PNG_BYTES).hexdigest()
_PNG_MIME = "image/png"
_OTHER_SHA = hashlib.sha256(b"a-different-attachment").hexdigest()


# ---------------------------------------------------------------------------
# Helpers — real store + real config + httpx MockTransport (BF-287)
# ---------------------------------------------------------------------------

def _make_runtime(
    tmp_path,
    *,
    auto_resolve_remote_enabled: bool,
    peers: list[A2APeerConfig],
) -> tuple[Any, FilesystemAttachmentStore]:
    """Real-ish runtime stub: real Pydantic config + real filesystem store."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    config = SimpleNamespace(
        attachments=AttachmentsConfig(
            auto_resolve_remote_enabled=auto_resolve_remote_enabled
        ),
        federation=FederationConfig(
            a2a=FederationA2AConfig(outbound_peers=peers)
        ),
    )
    runtime = SimpleNamespace(config=config, attachment_store=store)
    return runtime, store


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serving_handler(calls: dict) -> Any:
    """200 + matching bytes + good mime; records each request."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        calls["auth"] = request.headers.get("authorization", "")
        calls["url"] = str(request.url)
        return httpx.Response(
            200, content=_PNG_BYTES, headers={"content-type": _PNG_MIME}
        )
    return handler


def _peer(node_id: str = "peer-A") -> A2APeerConfig:
    return A2APeerConfig(peer_url="http://peer", auth_token="tok", node_id=node_id)


# ---------------------------------------------------------------------------
# 1. off -> byte-identical
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_off_byte_identical_no_fetch(tmp_path):
    """Flag False + missing ref + valid sender -> 0, ZERO requests, not stored."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=False, peers=[_peer()]
    )
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 0
    assert not await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 2. on + missing + known A2A sender -> fetched + stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_missing_known_sender_fetches_and_stores(tmp_path):
    """Flag on + missing ref + matching peer.node_id -> 1, stored, bytes match."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 1
    assert calls["n"] == 1
    assert calls["auth"] == "Bearer tok"
    assert calls["url"].endswith(f"/api/federation/attachments/{_PNG_SHA}")
    assert await store.exists(_PNG_SHA)
    assert await store.read(_PNG_SHA) == _PNG_BYTES


# ---------------------------------------------------------------------------
# 3. on + already-local -> idempotent, no fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_already_local_is_idempotent_no_fetch(tmp_path):
    """Pre-stored sha -> 0 and the peer is NOT called for it."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 0
    assert await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 4. on + non-A2A sender -> no fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_unmapped_sender_no_fetch(tmp_path):
    """source_node matches no peer node_id (and an empty-node_id peer) -> 0."""
    runtime, store = _make_runtime(
        tmp_path,
        auto_resolve_remote_enabled=True,
        peers=[A2APeerConfig(peer_url="http://peer", auth_token="tok")],  # node_id=""
    )
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 0
    assert not await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 5. fetch-failure -> swallowed, non-blocking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_failure_swallowed_returns_zero(tmp_path):
    """Peer 500 -> orchestrator swallows, returns 0, no exception, not stored."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    client = _mock_client(handler)
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 1  # the fetch WAS attempted, then degraded
    assert not await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 6. tamper still rejected -> not stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tamper_rejected_not_stored(tmp_path):
    """Bytes whose sha256 != requested -> fetch False, store.write NOT called."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    tampered = b"TAMPERED-bytes-do-not-match-the-requested-sha"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=tampered, headers={"content-type": _PNG_MIME}
        )

    client = _mock_client(handler)
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert not await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 7. pure resolve_sender_peer
# ---------------------------------------------------------------------------

def test_resolve_sender_peer_matching_and_misses():
    """Matches non-empty node_id; None on empty/no-match/all-empty node_ids."""
    matched = _peer("peer-A")
    a2a = FederationA2AConfig(outbound_peers=[matched])
    assert resolve_sender_peer(a2a, "peer-A") is matched
    # Empty source_node -> None.
    assert resolve_sender_peer(a2a, "") is None
    # No matching node_id -> None.
    assert resolve_sender_peer(a2a, "peer-Z") is None
    # All peers have empty node_id -> never an auto-resolution source.
    a2a_empty = FederationA2AConfig(
        outbound_peers=[A2APeerConfig(peer_url="http://p", auth_token="t")]
    )
    assert resolve_sender_peer(a2a_empty, "peer-A") is None


# ---------------------------------------------------------------------------
# 8. pure extract_attachment_shas
# ---------------------------------------------------------------------------

def test_extract_attachment_shas_shapes_dedup_and_validation():
    """Bare ref; vision_messages source.sha256; dedup; drop non-64-hex."""
    # Bare ref shape.
    assert extract_attachment_shas({"attachment_ref": _PNG_SHA}) == [_PNG_SHA]
    # Vision-block shape.
    vision = {
        "vision_messages": [
            {"content": [
                {"type": "image", "source": {"sha256": _OTHER_SHA}},
                {"type": "text", "text": "ignored"},
            ]}
        ]
    }
    assert extract_attachment_shas(vision) == [_OTHER_SHA]
    # Dedup across both shapes, first-seen order preserved.
    both = {
        "attachment_ref": _PNG_SHA,
        "vision_messages": [
            {"content": [
                {"type": "image", "source": {"sha256": _PNG_SHA}},
                {"type": "image", "source": {"sha256": _OTHER_SHA}},
            ]}
        ],
    }
    assert extract_attachment_shas(both) == [_PNG_SHA, _OTHER_SHA]
    # Drop non-64-hex / non-string / wrong-length / no refs.
    assert extract_attachment_shas({"attachment_ref": "not-a-hash"}) == []
    assert extract_attachment_shas({"attachment_ref": "a" * 63}) == []
    assert extract_attachment_shas({"attachment_ref": 12345}) == []
    assert extract_attachment_shas({}) == []
    assert extract_attachment_shas({"vision_messages": "garbage"}) == []


# ---------------------------------------------------------------------------
# 9. runtime None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_runtime_none_returns_zero():
    """resolve_missing_attachments(None, ...) -> 0 (no config access)."""
    n = await resolve_missing_attachments(
        None, {"attachment_ref": _PNG_SHA}, "peer-A"
    )
    assert n == 0


# ---------------------------------------------------------------------------
# 10. config defaults
# ---------------------------------------------------------------------------

def test_config_defaults_are_off_and_empty():
    """auto_resolve_remote_enabled default False; node_id default ''."""
    assert AttachmentsConfig().auto_resolve_remote_enabled is False
    assert A2APeerConfig(peer_url="x").node_id == ""
