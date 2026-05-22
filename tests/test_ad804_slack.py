"""AD-804: tests for the Slack adapter substrate (client + polling + pairing-gate + doctor)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from probos.channels.base import ChannelMessage
from probos.channels.slack_adapter import SlackAdapter
from probos.channels.slack_client import SlackAPIError, SlackClient
from probos.config import SlackConfig


def _make_client(handler, token: str = "xoxb-TEST") -> SlackClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://slack.com/api", timeout=2.0)
    return SlackClient(bot_token=token, http=http)


class _FakeRuntime:
    def __init__(self, pairing_service=None):
        self.pairing_service = pairing_service

    def emit_event(self, *_a, **_kw):
        pass


class _FakePairingService:
    def __init__(self):
        self.requested: list[tuple[str, str]] = []
        self.resolved: dict[tuple[str, str], str | None] = {}

    def resolve_did(self, channel: str, raw_id: str) -> str | None:
        return self.resolved.get((channel, raw_id))

    async def request_pairing(self, *, channel: str, raw_id: str) -> str:
        self.requested.append((channel, raw_id))
        return "ABC123"


# ----- SlackClient -----


@pytest.mark.asyncio
async def test_client_auth_test_returns_identity():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/auth.test")
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        return httpx.Response(200, json={"ok": True, "user_id": "U1", "team": "T1", "url": "https://t.slack.com"})
    client = _make_client(handler)
    me = await client.auth_test()
    assert me["user_id"] == "U1"
    await client.close()


@pytest.mark.asyncio
async def test_client_conversations_history_passes_oldest():
    captured: dict[str, Any] = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True, "messages": [{"ts": "1.0", "user": "U2", "text": "hi"}]})
    client = _make_client(handler)
    msgs = await client.conversations_history("C1", oldest="0.5", limit=10)
    assert captured["body"]["channel"] == "C1"
    assert captured["body"]["oldest"] == "0.5"
    assert msgs[0]["text"] == "hi"
    await client.close()


@pytest.mark.asyncio
async def test_client_chat_post_message_builds_body():
    captured: dict[str, Any] = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True, "ts": "9.0"})
    client = _make_client(handler)
    result = await client.chat_post_message("C1", "hello", thread_ts="1.0")
    assert result["ts"] == "9.0"
    assert captured["body"]["channel"] == "C1"
    assert captured["body"]["text"] == "hello"
    assert captured["body"]["thread_ts"] == "1.0"
    await client.close()


@pytest.mark.asyncio
async def test_client_raises_on_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    client = _make_client(handler)
    with pytest.raises(SlackAPIError) as exc:
        await client.auth_test()
    assert "invalid_auth" in str(exc.value)
    await client.close()


# ----- SlackAdapter._convert_message filters -----


def test_convert_message_returns_message_for_user_text():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    adapter = SlackAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    msg = {"user": "U42", "text": "hi", "ts": "1.5"}
    cm = adapter._convert_message("C123", msg)
    assert cm is not None
    assert cm.text == "hi"
    assert cm.channel_id == "C123"
    assert cm.user_id == "U42"
    assert cm.reply_to_message_id == "1.5"


def test_convert_message_drops_bot_subtype():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    adapter = SlackAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    assert adapter._convert_message("C1", {"subtype": "bot_message", "user": "U1", "text": "hi", "ts": "1"}) is None
    assert adapter._convert_message("C1", {"bot_id": "B1", "user": "U1", "text": "hi", "ts": "1"}) is None
    assert adapter._convert_message("C1", {"subtype": "channel_join", "user": "U1", "ts": "1"}) is None


def test_convert_message_drops_self_messages():
    """Messages from our own bot user are filtered out."""
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    adapter = SlackAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    adapter._bot_user_id = "U_BOT"
    assert adapter._convert_message("C1", {"user": "U_BOT", "text": "i am bot", "ts": "1"}) is None
    assert adapter._convert_message("C1", {"user": "U_HUMAN", "text": "i am human", "ts": "1"}) is not None


def test_convert_message_honors_allowed_channel_ids():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_channel_ids=["C_ALLOWED"])
    adapter = SlackAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    assert adapter._convert_message("C_OTHER", {"user": "U1", "text": "hi", "ts": "1"}) is None
    assert adapter._convert_message("C_ALLOWED", {"user": "U1", "text": "hi", "ts": "1"}) is not None


# ----- AD-802a pairing hook on Slack adapter -----


@pytest.mark.asyncio
async def test_slack_check_pairing_passes_through_with_no_pairing_service():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    adapter = SlackAdapter(_FakeRuntime(), cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    msg = ChannelMessage(text="hi", channel_id="C1", user_id="U1")
    assert await adapter._check_pairing(msg) is True


@pytest.mark.asyncio
async def test_slack_check_pairing_mints_code_for_unknown_sender():
    sent: list[tuple[str, str]] = []
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        sent.append((body.get("channel"), body.get("text", "")))
        return httpx.Response(200, json={"ok": True, "ts": "1.0"})
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    ps = _FakePairingService()
    runtime = _FakeRuntime(pairing_service=ps)
    adapter = SlackAdapter(runtime, cfg, client=_make_client(handler))
    msg = ChannelMessage(text="hi", channel_id="C1", user_id="U42")
    proceed = await adapter._check_pairing(msg)
    assert proceed is False
    assert ps.requested == [("slack", "U42")]
    assert len(sent) == 1
    assert "probos pairing approve slack ABC123" in sent[0][1]


@pytest.mark.asyncio
async def test_slack_check_pairing_attaches_did_for_known_sender():
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    ps = _FakePairingService()
    ps.resolved[("slack", "U42")] = "did:foo:1"
    runtime = _FakeRuntime(pairing_service=ps)
    adapter = SlackAdapter(runtime, cfg, client=_make_client(lambda r: httpx.Response(200, json={"ok": True})))
    msg = ChannelMessage(text="hi", channel_id="C1", user_id="U42")
    assert await adapter._check_pairing(msg) is True
    assert msg.paired_did == "did:foo:1"


# ----- Adapter lifecycle -----


@pytest.mark.asyncio
async def test_adapter_start_validates_token_and_spawns_poll_task():
    calls: list[str] = []
    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method == "auth.test":
            return httpx.Response(200, json={"ok": True, "user_id": "UBOT", "team": "T1"})
        if method == "conversations.list":
            return httpx.Response(200, json={"ok": True, "channels": [
                {"id": "C1", "is_member": True}, {"id": "C2", "is_member": False},
            ]})
        # conversations.history returns empty so polling loop spins quietly.
        return httpx.Response(200, json={"ok": True, "messages": []})
    cfg = SlackConfig(enabled=True, bot_token="xoxb-test", poll_interval_s=2.0)
    adapter = SlackAdapter(_FakeRuntime(), cfg, client=_make_client(handler))
    await adapter.start()
    assert adapter._bot_user_id == "UBOT"
    assert adapter._channels == ["C1"]
    assert adapter._poll_task is not None
    await asyncio.sleep(0.05)
    await adapter.stop()
    assert adapter._poll_task is None
    assert "auth.test" in calls


@pytest.mark.asyncio
async def test_adapter_start_with_empty_token_refuses():
    cfg = SlackConfig(enabled=True, bot_token="")
    adapter = SlackAdapter(_FakeRuntime(), cfg)
    await adapter.start()
    assert adapter._started is False


# ----- doctor channel_slack_check -----


@pytest.mark.asyncio
async def test_doctor_channel_slack_ok_when_not_configured(tmp_path):
    from probos.doctor.checks.channel_slack_check import _ChannelSlackCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelSlackCheck().run(ctx)
    assert result.outcome is CheckOutcome.OK
    assert "not configured" in result.message


@pytest.mark.asyncio
async def test_doctor_channel_slack_fail_on_invalid_token(tmp_path, monkeypatch):
    import yaml
    channels = tmp_path / "channels"
    channels.mkdir()
    (channels / "slack.yaml").write_text(
        yaml.safe_dump({"enabled": True, "bot_token": "xoxb-bad"}),
        encoding="utf-8",
    )

    from probos.channels import slack_client as sc_module
    from probos.doctor.checks import channel_slack_check as csc

    class _BadClient:
        def __init__(self, *_a, **_kw):
            pass
        async def auth_test(self):
            raise sc_module.SlackAPIError("invalid_auth")
        async def close(self):
            return None

    monkeypatch.setattr(csc, "SlackClient", _BadClient)
    monkeypatch.setattr(csc, "SlackAPIError", sc_module.SlackAPIError)

    from probos.doctor.checks.channel_slack_check import _ChannelSlackCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelSlackCheck().run(ctx)
    assert result.outcome is CheckOutcome.FAIL
    assert "auth.test failed" in result.message
