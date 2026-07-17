"""AD-916: file sharing in group chat (refs-not-blobs) tests.

BF-287 discipline: real ``FilesystemAttachmentStore`` on ``tmp_path`` (a
valid 1x1 PNG + a ``text/plain`` blob written with their real sha256), real
``ChatThreadStore`` on ``tmp_path``, real ``IntentBus(SignalManager(
reap_interval=1.0))``, and real-but-fake registry / callsign / profile stubs
(NOT ``MagicMock``) at the substrate/bus boundary. The two pure helpers
(``resolve_attachment_refs`` / ``build_chat_vision_messages``) take the store
explicitly (Dependency Inversion) so they unit-test without cache seeding;
the end-to-end ``group_chat_fanout`` + REST cases seed
``chat._ATTACHMENT_STORE_CACHE[id(runtime)]`` so ``_get_attachment_store``
returns the tmp store (byte-identical to the proven DM path).
"""
from __future__ import annotations

import base64
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import AttachmentsConfig
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers import chat as chat_router
from probos.routers.thread_fanout import (
    build_chat_vision_messages,
    crew_agent_participants,
    group_chat_fanout,
    resolve_attachment_refs,
)
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult

# Canonical 1x1 transparent PNG — correct magic bytes (BF-287 realism).
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_TXT_BLOB = b"hello from a text attachment\n"


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


# ---------------- BF-287 real-but-fake substrate stubs ----------------


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type  # real attr; is_crew_agent reads .agent_type


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)


class _FakeCallsigns:
    """Extends the AD-914 callsign stub with ``get_profile`` so the AD-916
    ``vision_capable`` gate (mirroring ``agents.py:1963``) is exercisable."""

    def __init__(
        self,
        callsigns: dict[str, str] | None = None,
        profiles: dict[str, dict] | None = None,
    ) -> None:
        self._cs = callsigns or {}  # agent_type -> callsign
        self._pf = profiles or {}   # agent_type -> profile dict

    def get_callsign(self, agent_type: str) -> str:
        return self._cs.get(agent_type, "")

    def get_profile(self, agent_type: str):
        return self._pf.get(agent_type)


def _seq_clock():
    """Deterministic monotonic clock so created_at ordering (and the
    ``before=`` history filter) is exact regardless of wall-clock speed."""
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _make_recording_handler(received: dict, agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        # Capture the full params dict so the vision_messages wire can be
        # asserted directly (and its absence for non-vision participants).
        received[agent_id] = dict(intent.params)
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=True,
            result=f"reply::{agent_id}",
        )

    return _h


@pytest.fixture(autouse=True)
def _clear_attachment_cache():
    """The module-level ``_ATTACHMENT_STORE_CACHE`` is keyed by ``id(runtime)``
    which can be reused after GC — clear before and after each test so a
    seeded tmp store never leaks across tests (or in from other files)."""
    chat_router._ATTACHMENT_STORE_CACHE.clear()
    yield
    chat_router._ATTACHMENT_STORE_CACHE.clear()


async def _make_attach_store(tmp_path) -> FilesystemAttachmentStore:
    """Real FilesystemAttachmentStore seeded with the PNG + text blobs by
    their real sha256 (mirrors the already-uploaded state the upload endpoint
    leaves behind)."""
    store = FilesystemAttachmentStore(tmp_path / "attach")
    await store.write(_sha(_PNG_1x1), _PNG_1x1, "image/png")
    await store.write(_sha(_TXT_BLOB), _TXT_BLOB, "text/plain")
    return store


async def _seed_image_refs(
    store: FilesystemAttachmentStore,
    count: int,
) -> list[str]:
    refs: list[str] = []
    for index in range(count):
        blob = _PNG_1x1 + index.to_bytes(2, "big")
        content_hash = _sha(blob)
        await store.write(content_hash, blob, "image/png")
        refs.append(content_hash)
    return refs


def _build_env(
    tmp_path,
    attach_store: FilesystemAttachmentStore,
    *,
    agents: dict[str, str],
    callsigns: dict[str, str] | None = None,
    profiles: dict[str, dict] | None = None,
    attachments_enabled: bool = True,
    subscribe=None,
):
    """agents: {agent_id: agent_type}. Returns (thread_store, runtime, received).

    Seeds ``chat._ATTACHMENT_STORE_CACHE[id(runtime)]`` with ``attach_store``
    so ``_get_attachment_store(runtime)`` (REST + fan-out paths) returns it.
    """
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(callsigns, profiles),
        project_store=None,
        config=SimpleNamespace(
            attachments=AttachmentsConfig(enabled=attachments_enabled)
        ),
    )
    chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] = attach_store
    received: dict[str, dict] = {}
    sub_ids = list(agents.keys()) if subscribe is None else list(subscribe)
    for aid in sub_ids:
        bus.subscribe(aid, _make_recording_handler(received, aid), intent_names=["direct_message"])
    return store, runtime, received


def _rest_client(runtime) -> TestClient:
    from probos.routers import threads as threads_router
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(threads_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# ---------------- resolve_attachment_refs (DI, no runtime) ----------------


async def test_resolve_attachment_refs_roundtrip(tmp_path):
    store = await _make_attach_store(tmp_path)
    png_sha = _sha(_PNG_1x1)
    refs = await resolve_attachment_refs(store, [png_sha])
    assert refs == [{"content_hash": png_sha, "mime": "image/png"}]


async def test_resolve_attachment_refs_missing_id_skipped(tmp_path):
    store = await _make_attach_store(tmp_path)
    # Valid 64-hex format but absent from the store -> mime_for None -> skipped.
    refs = await resolve_attachment_refs(store, ["00" * 32])
    assert refs == []


async def test_resolve_attachment_refs_empty_list(tmp_path):
    store = await _make_attach_store(tmp_path)
    assert await resolve_attachment_refs(store, []) == []


async def test_resolve_attachment_refs_mixed_image_and_text(tmp_path):
    store = await _make_attach_store(tmp_path)
    png_sha, txt_sha = _sha(_PNG_1x1), _sha(_TXT_BLOB)
    refs = await resolve_attachment_refs(store, [png_sha, txt_sha])
    assert refs == [
        {"content_hash": png_sha, "mime": "image/png"},
        {"content_hash": txt_sha, "mime": "text/plain"},
    ]


# ---------------- metadata persistence (store + REST) ----------------


async def test_message_to_dict_carries_attachments(tmp_path):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    t = store.create_thread(title="room", participants=["scout1"])
    png_sha = _sha(_PNG_1x1)
    refs = [{"content_hash": png_sha, "mime": "image/png"}]
    store.append_message(
        t.id, author_id="captain", role="captain", body="see this",
        metadata={"attachments": refs},
    )
    # Reload from disk so the JSON persist + parse round-trip is exercised.
    reloaded = store.list_messages(t.id, limit=10)[-1]
    assert reloaded.to_dict()["metadata"]["attachments"] == refs


async def test_append_message_persists_attachments_metadata(tmp_path):
    attach = await _make_attach_store(tmp_path)
    # Single crew participant -> no fan-out; focus on ref persistence.
    store, runtime, _ = _build_env(tmp_path, attach, agents={"scout1": "scout"})
    t = store.create_thread(title="1:1", participants=["scout1"])
    png_sha = _sha(_PNG_1x1)
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "look",
            "metadata": {
                "attachments": [
                    {"content_hash": "forged", "mime": "image/jpeg"}
                ],
                "sibling_marker": "preserved",
            },
            "attachment_ids": [png_sha],
        },
    )
    assert r.status_code == 200
    msgs = client.get(f"/api/threads/{t.id}/messages").json()["messages"]
    cap = next(m for m in msgs if m["role"] == "captain")
    assert cap["metadata"]["attachments"] == [{"content_hash": png_sha, "mime": "image/png"}]
    assert cap["metadata"]["sibling_marker"] == "preserved"


async def test_append_message_no_attachment_ids_metadata_unchanged(tmp_path):
    attach = await _make_attach_store(tmp_path)
    store, runtime, _ = _build_env(tmp_path, attach, agents={"scout1": "scout"})
    t = store.create_thread(title="1:1", participants=["scout1"])
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "captain", "role": "captain", "body": "plain"},
    )
    assert r.status_code == 200
    assert "attachments" not in r.json()["metadata"]


async def test_append_message_unknown_attachment_id_skipped(tmp_path):
    attach = await _make_attach_store(tmp_path)
    store, runtime, _ = _build_env(tmp_path, attach, agents={"scout1": "scout"})
    t = store.create_thread(title="1:1", participants=["scout1"])
    client = _rest_client(runtime)
    r = client.post(
        f"/api/threads/{t.id}/messages",
        json={"author_id": "captain", "role": "captain", "body": "ghost ref",
              "attachment_ids": ["00" * 32]},
    )
    # Tier-2 skip: message persisted, no attachments key, no 500.
    assert r.status_code == 200
    assert "attachments" not in r.json()["metadata"]


async def test_group_ingress_rejects_nine_images_before_persist_or_dispatch(
    tmp_path,
):
    class _RecordingProjectStore:
        def __init__(self) -> None:
            self.touched: list[str] = []

        def touch(self, project_id: str) -> None:
            self.touched.append(project_id)

    class _RecordingEpisodeStore:
        def __init__(self) -> None:
            self.stored: list[object] = []

        async def store(self, episode: object) -> None:
            self.stored.append(episode)

    attach = await _make_attach_store(tmp_path)
    image_refs = await _seed_image_refs(attach, 9)
    store, runtime, received = _build_env(
        tmp_path,
        attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
        profiles={
            "scout": {"vision_capable": True},
            "counselor": {"vision_capable": False},
        },
    )
    project_store = _RecordingProjectStore()
    episode_store = _RecordingEpisodeStore()
    runtime.project_store = project_store
    runtime.episodic_memory = episode_store
    thread = store.create_thread(
        title="room",
        participants=["scout1", "counselor1"],
        project_id="project-1",
    )
    assert crew_agent_participants(runtime, thread.participants) == [
        "scout1",
        "counselor1",
    ]
    initial_participants = list(thread.participants)

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "nine images",
            "attachment_ids": image_refs,
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "AD-731a-1d: group message exceeds the hard cap of 8 images "
        "(observed 9). Reduce the image count and resend."
    )
    assert store.list_messages(thread.id, limit=1000) == []
    assert store.get_thread(thread.id).participants == initial_participants
    assert project_store.touched == []
    assert episode_store.stored == []
    assert received == {}


@pytest.mark.parametrize("forged_count", [0, 8])
async def test_group_ingress_caller_metadata_attachments_cannot_bypass_cap(
    tmp_path,
    forged_count: int,
):
    attach = await _make_attach_store(tmp_path)
    image_refs = await _seed_image_refs(attach, 9)
    store, runtime, received = _build_env(
        tmp_path,
        attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
    )
    thread = store.create_thread(
        title="room", participants=["scout1", "counselor1"]
    )
    forged = [
        {"content_hash": content_hash, "mime": "image/png"}
        for content_hash in image_refs[:forged_count]
    ]

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "forged metadata cannot reduce the authoritative count",
            "metadata": {
                "attachments": forged,
                "sibling_marker": "preserve-on-success",
            },
            "attachment_ids": image_refs,
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == (
        "AD-731a-1d: group message exceeds the hard cap of 8 images "
        "(observed 9). Reduce the image count and resend."
    )
    assert store.list_messages(thread.id, limit=1000) == []
    assert received == {}


async def test_append_message_strips_caller_metadata_attachments_without_attachment_ids(
    tmp_path,
):
    attach = await _make_attach_store(tmp_path)
    store, runtime, _ = _build_env(
        tmp_path, attach, agents={"scout1": "scout"}
    )
    thread = store.create_thread(title="1:1", participants=["scout1"])
    forged = [{"content_hash": _sha(_PNG_1x1), "mime": "image/png"}]

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "caller metadata is not authoritative",
            "metadata": {
                "attachments": forged,
                "sibling_marker": "preserved",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "sibling_marker": "preserved"
    }
    captain_row = next(
        message
        for message in store.list_messages(thread.id, limit=1000)
        if message.role == "captain"
    )
    assert captain_row.metadata == {"sibling_marker": "preserved"}


async def test_resolver_failure_does_not_restore_caller_metadata_attachments(
    tmp_path,
    monkeypatch,
):
    async def _raise_resolution_failure(*_args, **_kwargs):
        raise RuntimeError("injected attachment resolver failure")

    monkeypatch.setattr(
        "probos.routers.thread_fanout.resolve_attachment_refs",
        _raise_resolution_failure,
    )
    attach = await _make_attach_store(tmp_path)
    store, runtime, _ = _build_env(
        tmp_path, attach, agents={"scout1": "scout"}
    )
    thread = store.create_thread(title="1:1", participants=["scout1"])
    png_sha = _sha(_PNG_1x1)

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "resolution degrades to text only",
            "metadata": {
                "attachments": [
                    {"content_hash": png_sha, "mime": "image/png"}
                ],
                "sibling_marker": "preserved",
            },
            "attachment_ids": [png_sha],
        },
    )

    assert response.status_code == 200
    assert response.json()["metadata"] == {
        "sibling_marker": "preserved"
    }
    captain_row = next(
        message
        for message in store.list_messages(thread.id, limit=1000)
        if message.role == "captain"
    )
    assert captain_row.metadata == {"sibling_marker": "preserved"}


@pytest.mark.parametrize(
    "registry_case",
    ["absent", "none", "missing_get", "non_callable_get", "raising_get"],
)
async def test_minimal_runtime_with_resolved_attachments_preserves_prior_append(
    tmp_path,
    registry_case: str,
):
    class _RaisingRegistry:
        def get(self, _agent_id: str):
            raise RuntimeError("injected registry classification failure")

    attach = await _make_attach_store(tmp_path)
    image_refs = await _seed_image_refs(attach, 9)
    store = ChatThreadStore(tmp_path / "minimal-threads.db", clock=_seq_clock())
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=IntentBus(SignalManager(reap_interval=1.0)),
        attachment_store=attach,
        callsign_registry=_FakeCallsigns(),
        project_store=None,
        config=SimpleNamespace(attachments=AttachmentsConfig(enabled=True)),
    )
    if registry_case == "none":
        runtime.registry = None
    elif registry_case == "missing_get":
        runtime.registry = SimpleNamespace()
    elif registry_case == "non_callable_get":
        runtime.registry = SimpleNamespace(get=42)
    elif registry_case == "raising_get":
        runtime.registry = _RaisingRegistry()
    chat_router._ATTACHMENT_STORE_CACHE[id(runtime)] = attach
    thread = store.create_thread(
        title="minimal",
        participants=["scout1", "counselor1"],
    )

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "minimal runtime keeps prior append behavior",
            "attachment_ids": image_refs,
        },
    )

    assert response.status_code == 200
    expected_refs = [
        {"content_hash": content_hash, "mime": "image/png"}
        for content_hash in image_refs
    ]
    assert response.json()["metadata"]["attachments"] == expected_refs
    captain_row = next(
        message
        for message in store.list_messages(thread.id, limit=1000)
        if message.role == "captain"
    )
    assert captain_row.metadata["attachments"] == expected_refs


async def test_group_ingress_accepts_eight_images_and_all_non_image_attachments(
    tmp_path,
):
    attach = await _make_attach_store(tmp_path)
    image_refs = await _seed_image_refs(attach, 8)
    text_ref = _sha(_TXT_BLOB)
    attachment_ids = [*image_refs, text_ref]
    store, runtime, received = _build_env(
        tmp_path,
        attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
        profiles={
            "scout": {"vision_capable": True},
            "counselor": {"vision_capable": False},
        },
    )
    thread = store.create_thread(
        title="room", participants=["scout1", "counselor1"]
    )

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "eight images and a text file",
            "attachment_ids": attachment_ids,
        },
    )

    assert response.status_code == 200
    captain_row = next(
        message
        for message in store.list_messages(thread.id, limit=1000)
        if message.role == "captain"
    )
    assert captain_row.metadata["attachments"] == [
        *[
            {"content_hash": content_hash, "mime": "image/png"}
            for content_hash in image_refs
        ],
        {"content_hash": text_ref, "mime": "text/plain"},
    ]
    vision_content = received["scout1"]["vision_messages"][0]["content"]
    image_blocks = [block for block in vision_content if block["type"] == "image"]
    assert [block["source"]["sha256"] for block in image_blocks] == image_refs
    assert len(image_blocks) == 8


@pytest.mark.parametrize("configured_cap", [0, 99])
async def test_group_ingress_fixed_cap_ignores_config_disable_or_raise(
    tmp_path,
    configured_cap: int,
):
    attach = await _make_attach_store(tmp_path)
    image_refs = await _seed_image_refs(attach, 9)
    store, runtime, received = _build_env(
        tmp_path,
        attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
    )
    runtime.config.attachments.images_per_dm_hard_cap = configured_cap
    thread = store.create_thread(
        title="room", participants=["scout1", "counselor1"]
    )

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "fixed group cap",
            "attachment_ids": image_refs,
        },
    )

    assert response.status_code == 413
    assert store.list_messages(thread.id, limit=1000) == []
    assert received == {}


@pytest.mark.parametrize("configured_cap", [0, 99])
async def test_single_agent_thread_does_not_inherit_group_fixed_cap(
    tmp_path,
    configured_cap: int,
):
    attach = await _make_attach_store(tmp_path)
    image_refs = await _seed_image_refs(attach, 9)
    store, runtime, received = _build_env(
        tmp_path,
        attach,
        agents={"scout1": "scout"},
        profiles={"scout": {"vision_capable": True}},
    )
    runtime.config.attachments.images_per_dm_hard_cap = configured_cap
    thread = store.create_thread(title="1:1", participants=["scout1"])

    response = _rest_client(runtime).post(
        f"/api/threads/{thread.id}/messages",
        json={
            "author_id": "captain",
            "role": "captain",
            "body": "nine images in a non-group thread",
            "attachment_ids": image_refs,
        },
    )

    assert response.status_code == 200
    assert response.json()["metadata"]["attachments"] == [
        {"content_hash": content_hash, "mime": "image/png"}
        for content_hash in image_refs
    ]
    assert received == {}


# ---------------- build_chat_vision_messages (DI) ----------------


async def test_build_chat_vision_messages_image_present(tmp_path):
    store = await _make_attach_store(tmp_path)
    cfg = AttachmentsConfig()
    png_sha = _sha(_PNG_1x1)
    refs = [{"content_hash": png_sha, "mime": "image/png"}]
    messages = await build_chat_vision_messages(store, cfg, "caption", refs)
    assert messages is not None
    content = messages[0]["content"]
    assert {
        "type": "image",
        "source": {"type": "attachment_ref", "sha256": png_sha, "media_type": "image/png"},
    } in content


async def test_build_chat_vision_messages_non_image_returns_none(tmp_path):
    store = await _make_attach_store(tmp_path)
    cfg = AttachmentsConfig()
    refs = [{"content_hash": _sha(_TXT_BLOB), "mime": "text/plain"}]
    assert await build_chat_vision_messages(store, cfg, "caption", refs) is None


async def test_build_chat_vision_messages_no_attachments_returns_none(tmp_path):
    store = await _make_attach_store(tmp_path)
    cfg = AttachmentsConfig()
    assert await build_chat_vision_messages(store, cfg, "caption", []) is None


async def test_build_chat_vision_messages_text_block_carries_caption(tmp_path):
    store = await _make_attach_store(tmp_path)
    cfg = AttachmentsConfig()
    refs = [{"content_hash": _sha(_PNG_1x1), "mime": "image/png"}]
    messages = await build_chat_vision_messages(store, cfg, "the caption", refs)
    assert messages is not None
    assert messages[0]["content"][0] == {"type": "text", "text": "the caption"}


# ---------------- group_chat_fanout vision threading (e2e) ----------------


async def test_group_chat_fanout_vision_participant_gets_image_ref(tmp_path):
    attach = await _make_attach_store(tmp_path)
    store, runtime, received = _build_env(
        tmp_path, attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        profiles={"scout": {"vision_capable": True}, "counselor": {"vision_capable": False}},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    png_sha = _sha(_PNG_1x1)
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="look at this",
        metadata={"attachments": [{"content_hash": png_sha, "mime": "image/png"}]},
    )
    await group_chat_fanout(runtime, t.id, captain_body="look at this", captain_msg=cap)
    vm = received["scout1"].get("vision_messages")
    assert vm is not None
    assert {
        "type": "image",
        "source": {"type": "attachment_ref", "sha256": png_sha, "media_type": "image/png"},
    } in vm[0]["content"]


async def test_group_chat_fanout_non_vision_participant_no_vision_messages(tmp_path):
    attach = await _make_attach_store(tmp_path)
    store, runtime, received = _build_env(
        tmp_path, attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
        callsigns={"scout": "Scout", "counselor": "Troi"},
        profiles={"scout": {"vision_capable": True}, "counselor": {"vision_capable": False}},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    png_sha = _sha(_PNG_1x1)
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="look",
        metadata={"attachments": [{"content_hash": png_sha, "mime": "image/png"}]},
    )
    await group_chat_fanout(runtime, t.id, captain_body="look", captain_msg=cap)
    # Non-vision participant params are byte-identical to AD-914 (no vision key).
    assert "vision_messages" not in received["counselor1"]
    assert received["counselor1"]["from"] == "hxi_profile"


async def test_group_chat_fanout_non_image_attachment_link_only(tmp_path):
    attach = await _make_attach_store(tmp_path)
    store, runtime, received = _build_env(
        tmp_path, attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
        profiles={"scout": {"vision_capable": True}, "counselor": {"vision_capable": True}},
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    txt_sha = _sha(_TXT_BLOB)
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="here is a file",
        metadata={"attachments": [{"content_hash": txt_sha, "mime": "text/plain"}]},
    )
    await group_chat_fanout(runtime, t.id, captain_body="here is a file", captain_msg=cap)
    # No vision dispatch for a non-image ref, even to vision-capable agents.
    for aid in ("scout1", "counselor1"):
        assert "vision_messages" not in received[aid]
    # Link-only: the ref bytes are still readable from the store...
    assert await attach.read(txt_sha) == _TXT_BLOB
    # ...and the ref is still present on the persisted Captain message.
    cap_row = next(m for m in store.list_messages(t.id, limit=100) if m.role == "captain")
    assert cap_row.metadata["attachments"] == [{"content_hash": txt_sha, "mime": "text/plain"}]


async def test_group_chat_fanout_attachments_disabled_no_vision(tmp_path):
    attach = await _make_attach_store(tmp_path)
    store, runtime, received = _build_env(
        tmp_path, attach,
        agents={"scout1": "scout", "counselor1": "counselor"},
        profiles={"scout": {"vision_capable": True}, "counselor": {"vision_capable": True}},
        attachments_enabled=False,
    )
    t = store.create_thread(title="room", participants=["scout1", "counselor1"])
    png_sha = _sha(_PNG_1x1)
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="look",
        metadata={"attachments": [{"content_hash": png_sha, "mime": "image/png"}]},
    )
    await group_chat_fanout(runtime, t.id, captain_body="look", captain_msg=cap)
    # attachments disabled -> build-once block short-circuits -> no vision key.
    for aid in ("scout1", "counselor1"):
        assert "vision_messages" not in received[aid]
