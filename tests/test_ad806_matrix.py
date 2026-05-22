"""AD-806: tests for the Matrix adapter substrate (client + sync loop + pairing-gate + doctor)."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from probos.channels.base import ChannelMessage
from probos.channels.matrix_adapter import MatrixAdapter
from probos.channels.matrix_client import MatrixAPIError, MatrixClient
from probos.channels.matrix_config import MatrixAdapterConfig


def _make_client(handler) -> MatrixClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, timeout=2.0)
    return MatrixClient(
        homeserver="https://matrix.test",
        access_token="syt-TEST",
        http=http,
    )


class _FakeRuntime:
    def __init__(self, pairing_service=None):
        self.pairing_service = pairing_service


class _FakePairingService:
    def __init__(self):
        self.requested: list[tuple[str, str]] = []
        self.resolved: dict[tuple[str, str], str | None] = {}

    def resolve_did(self, channel: str, raw_id: str) -> str | None:
        return self.resolved.get((channel, raw_id))

    async def request_pairing(self, *, channel: str, raw_id: str) -> str:
        self.requested.append((channel, raw_id))
        return "ABC123"


# ----- MatrixClient -----


@pytest.mark.asyncio
async def test_client_whoami_returns_user_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/account/whoami" in request.url.path
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        return httpx.Response(200, json={"user_id": "@yeo:matrix.test"})
    client = _make_client(handler)
    uid = await client.whoami()
    assert uid == "@yeo:matrix.test"
    await client.close()


@pytest.mark.asyncio
async def test_client_login_password_returns_token_and_stores_it():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/login" in request.url.path
        body = json.loads(request.content.decode("utf-8"))
        assert body["type"] == "m.login.password"
        assert body["identifier"]["user"] == "@yeo:matrix.test"
        return httpx.Response(200, json={"access_token": "syt-NEW", "user_id": "@yeo:matrix.test"})
    client = MatrixClient(homeserver="https://matrix.test", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    token = await client.login_password("@yeo:matrix.test", "hunter2")
    assert token == "syt-NEW"
    assert client.access_token == "syt-NEW"
    await client.close()


@pytest.mark.asyncio
async def test_client_sync_passes_since_and_timeout():
    captured: dict = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"next_batch": "s2", "rooms": {}})
    client = _make_client(handler)
    payload = await client.sync(since="s1", timeout_ms=5000)
    assert captured["params"]["since"] == "s1"
    assert captured["params"]["timeout"] == "5000"
    assert payload["next_batch"] == "s2"
    await client.close()


@pytest.mark.asyncio
async def test_client_send_message_posts_to_room():
    captured: dict = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"event_id": "$evt-1"})
    client = _make_client(handler)
    evt = await client.send_message("!room:matrix.test", "hello")
    assert evt == "$evt-1"
    assert "/rooms/" in captured["path"]
    assert "/send/m.room.message/" in captured["path"]
    assert captured["body"]["msgtype"] == "m.text"
    assert captured["body"]["body"] == "hello"
    await client.close()


@pytest.mark.asyncio
async def test_client_raises_on_error_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errcode": "M_UNKNOWN_TOKEN", "error": "Invalid access token"})
    client = _make_client(handler)
    with pytest.raises(MatrixAPIError) as exc:
        await client.whoami()
    assert exc.value.errcode == "M_UNKNOWN_TOKEN"
    assert exc.value.status_code == 401
    await client.close()


# ----- MatrixAdapter._convert_event -----


def test_convert_event_returns_message_for_m_text():
    cfg = MatrixAdapterConfig(access_token="t", homeserver="https://matrix.test")
    adapter = MatrixAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={})))
    event = {
        "type": "m.room.message",
        "sender": "@alice:matrix.test",
        "event_id": "$evt-1",
        "content": {"msgtype": "m.text", "body": "hi"},
    }
    cm = adapter._convert_event("!room:matrix.test", event)
    assert cm is not None
    assert cm.text == "hi"
    assert cm.channel_id == "!room:matrix.test"
    assert cm.user_id == "@alice:matrix.test"
    assert cm.reply_to_message_id == "$evt-1"


def test_convert_event_drops_encrypted_and_non_text():
    cfg = MatrixAdapterConfig(access_token="t", homeserver="https://matrix.test")
    adapter = MatrixAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={})))
    # Encrypted event - AD-806b territory
    assert adapter._convert_event("!r", {"type": "m.room.encrypted", "sender": "@a:t", "content": {}}) is None
    # m.image - AD-806b territory
    assert adapter._convert_event("!r", {
        "type": "m.room.message", "sender": "@a:t",
        "content": {"msgtype": "m.image", "body": "img"},
    }) is None
    # Reactions etc.
    assert adapter._convert_event("!r", {"type": "m.reaction", "sender": "@a:t", "content": {}}) is None


def test_convert_event_drops_self_messages():
    cfg = MatrixAdapterConfig(access_token="t", homeserver="https://matrix.test")
    adapter = MatrixAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={})))
    adapter._bot_user_id = "@yeo:matrix.test"
    event = {
        "type": "m.room.message", "sender": "@yeo:matrix.test",
        "content": {"msgtype": "m.text", "body": "i am bot"},
    }
    assert adapter._convert_event("!r", event) is None


# ----- AD-802a pairing hook on Matrix adapter -----


@pytest.mark.asyncio
async def test_matrix_check_pairing_attaches_did_for_known_sender():
    cfg = MatrixAdapterConfig(access_token="t", homeserver="https://matrix.test")
    ps = _FakePairingService()
    ps.resolved[("matrix", "@alice:matrix.test")] = "did:foo:1"
    adapter = MatrixAdapter(
        _FakeRuntime(pairing_service=ps),
        cfg,
        client=_make_client(lambda r: httpx.Response(200, json={})),
    )
    msg = ChannelMessage(text="hi", channel_id="!r", user_id="@alice:matrix.test")
    assert await adapter._check_pairing(msg) is True
    assert msg.paired_did == "did:foo:1"


@pytest.mark.asyncio
async def test_matrix_check_pairing_mints_code_for_unknown_sender():
    sent: list[tuple[str, str]] = []
    def handler(request: httpx.Request) -> httpx.Response:
        if "/send/m.room.message/" in request.url.path:
            body = json.loads(request.content.decode("utf-8"))
            sent.append((request.url.path, body.get("body", "")))
            return httpx.Response(200, json={"event_id": "$evt-1"})
        return httpx.Response(200, json={})
    cfg = MatrixAdapterConfig(access_token="t", homeserver="https://matrix.test")
    ps = _FakePairingService()
    adapter = MatrixAdapter(
        _FakeRuntime(pairing_service=ps),
        cfg,
        client=_make_client(handler),
    )
    msg = ChannelMessage(text="hi", channel_id="!r", user_id="@bob:matrix.test")
    proceed = await adapter._check_pairing(msg)
    assert proceed is False
    assert ps.requested == [("matrix", "@bob:matrix.test")]
    assert len(sent) == 1
    assert "probos pairing approve matrix ABC123" in sent[0][1]


# ----- Adapter lifecycle -----


@pytest.mark.asyncio
async def test_adapter_start_without_token_refuses():
    cfg = MatrixAdapterConfig(homeserver="https://matrix.test", access_token="")
    adapter = MatrixAdapter(_FakeRuntime(), cfg)
    await adapter.start()
    assert adapter._started is False


@pytest.mark.asyncio
async def test_adapter_start_validates_via_whoami_and_spawns_sync():
    calls: list[str] = []
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        if "/account/whoami" in path:
            return httpx.Response(200, json={"user_id": "@yeo:matrix.test"})
        if "/sync" in path:
            return httpx.Response(200, json={"next_batch": "s1", "rooms": {}})
        return httpx.Response(404, json={"errcode": "?"})
    cfg = MatrixAdapterConfig(access_token="t", homeserver="https://matrix.test", sync_timeout_ms=1000)
    adapter = MatrixAdapter(_FakeRuntime(), cfg, client=_make_client(handler))
    await adapter.start()
    assert adapter._bot_user_id == "@yeo:matrix.test"
    assert adapter._sync_task is not None
    await asyncio.sleep(0.05)
    await adapter.stop()
    assert adapter._sync_task is None
    assert any("whoami" in c for c in calls)


# ----- doctor channel_matrix_check -----


@pytest.mark.asyncio
async def test_doctor_channel_matrix_ok_when_not_configured(tmp_path):
    from probos.doctor.checks.channel_matrix_check import _ChannelMatrixCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelMatrixCheck().run(ctx)
    assert result.outcome is CheckOutcome.OK


@pytest.mark.asyncio
async def test_doctor_channel_matrix_fail_on_invalid_token(tmp_path, monkeypatch):
    import yaml
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "matrix.yaml").write_text(
        yaml.safe_dump({"enabled": True, "access_token": "bad", "homeserver": "https://matrix.test"}),
        encoding="utf-8",
    )

    from probos.channels import matrix_client as mc_module
    from probos.doctor.checks import channel_matrix_check as cmc

    class _BadClient:
        def __init__(self, *_a, **_kw):
            pass
        async def whoami(self):
            raise mc_module.MatrixAPIError("M_UNKNOWN_TOKEN")
        async def close(self):
            return None

    monkeypatch.setattr(cmc, "MatrixClient", _BadClient)
    monkeypatch.setattr(cmc, "MatrixAPIError", mc_module.MatrixAPIError)

    from probos.doctor.checks.channel_matrix_check import _ChannelMatrixCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelMatrixCheck().run(ctx)
    assert result.outcome is CheckOutcome.FAIL
    assert "whoami failed" in result.message
