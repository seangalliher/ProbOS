"""AD-803a: tests for the Telegram adapter substrate (client + adapter + pairing-gate + doctor)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.channels.base import ChannelMessage
from probos.channels.telegram_adapter import TelegramAdapter
from probos.channels.telegram_client import TelegramAPIError, TelegramClient
from probos.channels.telegram_config import TelegramAdapterConfig


# ----- helpers -----


def _make_mock_transport(handler):
    return httpx.MockTransport(handler)


def _make_client(handler, token: str = "TEST-TOKEN") -> TelegramClient:
    transport = _make_mock_transport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://api.telegram.org", timeout=2.0)
    return TelegramClient(token=token, http=http)


class _FakeRuntime:
    """Minimal stand-in for ProbOSRuntime — adapters only touch
    ``runtime.pairing_service`` in the pairing-gate path and
    ``runtime.process_natural_language`` / ``runtime.intent_bus`` /
    ``runtime.callsign_registry`` for the message body. The pairing-gate
    tests below short-circuit before any of that runs.
    """

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


# ----- TelegramClient -----


@pytest.mark.asyncio
async def test_client_get_me_parses_username():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/getMe")
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "yeobot"}})
    client = _make_client(handler)
    me = await client.get_me()
    assert me["username"] == "yeobot"
    await client.close()


@pytest.mark.asyncio
async def test_client_get_updates_builds_correct_body():
    captured: dict[str, Any] = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8") or "{}")
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 7}]})
    client = _make_client(handler)
    updates = await client.get_updates(offset=42, timeout=10, allowed_updates=["message"])
    assert updates == [{"update_id": 7}]
    assert captured["body"]["offset"] == 42
    assert captured["body"]["timeout"] == 10
    assert captured["body"]["allowed_updates"] == ["message"]
    assert captured["url"].endswith("/getUpdates")
    await client.close()


@pytest.mark.asyncio
async def test_client_send_message_posts_body():
    captured: dict[str, Any] = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8") or "{}")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})
    client = _make_client(handler)
    result = await client.send_message(12345, "hello", reply_to_message_id=42)
    assert result["message_id"] == 99
    assert captured["body"]["chat_id"] == 12345
    assert captured["body"]["text"] == "hello"
    assert captured["body"]["reply_to_message_id"] == 42
    await client.close()


@pytest.mark.asyncio
async def test_client_raises_on_api_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    client = _make_client(handler)
    with pytest.raises(TelegramAPIError) as exc:
        await client.get_me()
    assert "Unauthorized" in str(exc.value)
    await client.close()


# ----- TelegramAdapter._convert_update -----


def test_convert_update_returns_message_for_text():
    cfg = TelegramAdapterConfig(token="t")
    adapter = TelegramAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    update = {
        "update_id": 1,
        "message": {
            "message_id": 99,
            "chat": {"id": -100},
            "from": {"id": 42, "username": "alice"},
            "text": "hi",
        },
    }
    msg = adapter._convert_update(update)
    assert msg is not None
    assert msg.text == "hi"
    assert msg.channel_id == "-100"
    assert msg.user_id == "42"
    assert msg.user_display_name == "alice"


def test_convert_update_returns_none_for_non_text():
    cfg = TelegramAdapterConfig(token="t")
    adapter = TelegramAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    update = {
        "update_id": 2,
        "message": {
            "message_id": 100,
            "chat": {"id": 1},
            "from": {"id": 2, "first_name": "Bob"},
            "voice": {"file_id": "fileabc", "duration": 3},
        },
    }
    assert adapter._convert_update(update) is None


# ----- AD-802a pairing-gate hook on the base -----


@pytest.mark.asyncio
async def test_check_pairing_passes_through_when_no_pairing_service():
    """No pairing_service on the runtime — adapter must pass through."""
    cfg = TelegramAdapterConfig(token="t")
    runtime = _FakeRuntime(pairing_service=None)
    adapter = TelegramAdapter(runtime, cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    msg = ChannelMessage(text="hi", channel_id="1", user_id="42")
    assert await adapter._check_pairing(msg) is True
    assert msg.paired_did is None


@pytest.mark.asyncio
async def test_check_pairing_attaches_did_for_known_sender():
    cfg = TelegramAdapterConfig(token="t")
    ps = _FakePairingService()
    ps.resolved[("telegram", "42")] = "did:foo:1"
    runtime = _FakeRuntime(pairing_service=ps)
    adapter = TelegramAdapter(runtime, cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    msg = ChannelMessage(text="hi", channel_id="1", user_id="42")
    assert await adapter._check_pairing(msg) is True
    assert msg.paired_did == "did:foo:1"


@pytest.mark.asyncio
async def test_check_pairing_mints_code_for_unknown_sender():
    """Unknown sender -> pairing minted + instructions sent + returns False."""
    sent: list[tuple[str, str]] = []
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        sent.append((str(body["chat_id"]), body["text"]))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    cfg = TelegramAdapterConfig(token="t")
    ps = _FakePairingService()
    runtime = _FakeRuntime(pairing_service=ps)
    adapter = TelegramAdapter(runtime, cfg, client=_make_client(handler))
    msg = ChannelMessage(text="hi", channel_id="123", user_id="42")
    proceed = await adapter._check_pairing(msg)
    assert proceed is False
    assert ps.requested == [("telegram", "42")]
    assert len(sent) == 1
    assert sent[0][0] == "123"
    assert "probos pairing approve telegram ABC123" in sent[0][1]


# ----- Adapter lifecycle -----


@pytest.mark.asyncio
async def test_adapter_start_validates_token_and_spawns_poll_task():
    calls: list[str] = []
    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "yeobot"}})
        # getUpdates: respond with empty so the loop spins without
        # doing anything, then sleep so the test can cancel.
        return httpx.Response(200, json={"ok": True, "result": []})
    cfg = TelegramAdapterConfig(token="t", polling_timeout_s=1)
    adapter = TelegramAdapter(_FakeRuntime(), cfg, client=_make_client(handler))
    await adapter.start()
    assert adapter._bot_username == "yeobot"
    assert adapter._poll_task is not None
    assert not adapter._poll_task.done()
    # Let the loop tick once.
    await asyncio.sleep(0.05)
    await adapter.stop()
    assert adapter._poll_task is None
    assert "getMe" in calls


@pytest.mark.asyncio
async def test_poll_loop_advances_offset_past_seen_updates(monkeypatch):
    """offset must be (last update_id + 1) on every subsequent request."""
    seen_offsets: list[int | None] = []
    served_once = {"sent": False}

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "yeobot"}})
        if method == "getUpdates":
            body = json.loads(request.content.decode("utf-8") or "{}")
            seen_offsets.append(body.get("offset"))
            if not served_once["sent"]:
                served_once["sent"] = True
                return httpx.Response(200, json={
                    "ok": True,
                    "result": [{"update_id": 100, "message": {
                        "message_id": 1, "chat": {"id": 5},
                        "from": {"id": 7, "first_name": "Sean"},
                        "text": "ignored",
                    }}],
                })
            return httpx.Response(200, json={"ok": True, "result": []})
        if method == "sendMessage":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})
        return httpx.Response(404, json={"ok": False, "description": "?"})

    # Short-circuit handle_message so the test focuses on poll offsets.
    async def _short_circuit(self, message: ChannelMessage) -> str:  # noqa: ARG001
        return ""

    monkeypatch.setattr(TelegramAdapter, "handle_message", _short_circuit, raising=True)

    cfg = TelegramAdapterConfig(token="t", polling_timeout_s=1)
    adapter = TelegramAdapter(_FakeRuntime(), cfg, client=_make_client(handler))
    await adapter.start()
    # Give the loop time for at least 2 round trips.
    await asyncio.sleep(0.2)
    await adapter.stop()
    # First call had no offset; the second call must use offset=101.
    assert seen_offsets[0] is None
    assert 101 in seen_offsets


# ----- doctor channel_telegram_check -----


@pytest.mark.asyncio
async def test_doctor_channel_telegram_ok_when_not_configured(tmp_path):
    from probos.doctor.checks.channel_telegram_check import _ChannelTelegramCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelTelegramCheck().run(ctx)
    assert result.outcome is CheckOutcome.OK
    assert "not configured" in result.message


@pytest.mark.asyncio
async def test_doctor_channel_telegram_fail_on_invalid_token(tmp_path, monkeypatch):
    """Token present but getMe fails -> FAIL."""
    import yaml
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "telegram.yaml").write_text(
        yaml.safe_dump({"enabled": True, "token": "badtoken"}),
        encoding="utf-8",
    )

    # Patch TelegramClient.get_me to fail without making real network calls.
    from probos.channels import telegram_client as tc_module
    from probos.doctor.checks import channel_telegram_check as ctc

    class _BadClient:
        def __init__(self, *_a, **_kw):
            pass
        async def get_me(self):
            raise tc_module.TelegramAPIError("Unauthorized")
        async def close(self):
            return None

    monkeypatch.setattr(ctc, "TelegramClient", _BadClient)
    monkeypatch.setattr(ctc, "TelegramAPIError", tc_module.TelegramAPIError)

    from probos.doctor.checks.channel_telegram_check import _ChannelTelegramCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelTelegramCheck().run(ctx)
    assert result.outcome is CheckOutcome.FAIL
    assert "getMe failed" in result.message
