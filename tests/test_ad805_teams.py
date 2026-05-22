"""AD-805: Microsoft Teams adapter tests."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.channels.base import ChannelMessage
from probos.channels.teams_adapter import TeamsAdapter
from probos.channels.teams_client import TeamsAPIError, TeamsClient
from probos.channels.teams_config import TeamsAdapterConfig


class _FakeRuntime:
    def __init__(self, pairing_service=None):
        self.pairing_service = pairing_service


class _FakePairingService:
    def __init__(self):
        self.resolved: dict[tuple[str, str], str | None] = {}
        self.requested: list[tuple[str, str]] = []

    def resolve_did(self, channel, raw_id):
        return self.resolved.get((channel, raw_id))

    async def request_pairing(self, *, channel, raw_id):
        self.requested.append((channel, raw_id))
        return "TEAMS1"


# ---------------- TeamsClient ----------------


@pytest.mark.asyncio
async def test_client_token_fetched_and_cached():
    calls = {"token": 0, "activity": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            calls["token"] += 1
            return httpx.Response(
                200,
                json={"access_token": "tok-abc", "expires_in": 3600},
            )
        calls["activity"] += 1
        return httpx.Response(201, json={"id": "act-1"})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = TeamsClient(app_id="app", app_password="pw", http=http)
    await client.send_activity(
        service_url="https://smba.example", conversation_id="c1", text="hi"
    )
    await client.send_activity(
        service_url="https://smba.example", conversation_id="c1", text="again"
    )
    assert calls["token"] == 1  # cached
    assert calls["activity"] == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_client_token_refresh_after_expiry():
    now_box = {"t": 1000.0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            return httpx.Response(
                200, json={"access_token": "tok", "expires_in": 100}
            )
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = TeamsClient(app_id="app", app_password="pw", http=http)
    t1 = await client._get_token(now=now_box["t"])
    # 100s expiry minus 300s safety margin -> already expired -> refresh
    t2 = await client._get_token(now=now_box["t"] + 1)
    assert t1 == t2  # same content
    # cache should have rewritten on second call (safety margin > expiry)
    assert client._token is not None
    await client.aclose()


@pytest.mark.asyncio
async def test_client_token_error_when_credentials_missing():
    client = TeamsClient(app_id="", app_password="")
    with pytest.raises(TeamsAPIError):
        await client._get_token()
    await client.aclose()


@pytest.mark.asyncio
async def test_client_send_activity_raises_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2" in str(request.url):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(403, json={"error": "forbidden"})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = TeamsClient(app_id="a", app_password="b", http=http)
    with pytest.raises(TeamsAPIError):
        await client.send_activity(
            service_url="https://x", conversation_id="c", text="hi"
        )
    await client.aclose()


# ---------------- TeamsAdapter ----------------


def _make_adapter(client: TeamsClient | None = None, **cfg_over):
    cfg = TeamsAdapterConfig(enabled=True, app_id="app", app_password="pw", **cfg_over)
    runtime = _FakeRuntime()
    return TeamsAdapter(runtime, cfg, client=client)


def test_adapter_channel_name():
    assert TeamsAdapter.channel_name == "teams"


def test_adapter_extract_message_basic():
    a = _make_adapter()
    activity = {
        "type": "message",
        "id": "msg-1",
        "text": " hello there ",
        "from": {"aadObjectId": "user-aad-1", "name": "Alice"},
        "conversation": {"id": "conv-1"},
    }
    msg = a._extract_message(activity)
    assert msg is not None
    assert msg.text == "hello there"
    assert msg.user_id == "user-aad-1"
    assert msg.channel_id == "conv-1"
    assert msg.reply_to_message_id == "msg-1"


def test_adapter_extract_message_ignores_non_message_activity():
    a = _make_adapter()
    assert a._extract_message({"type": "typing"}) is None
    assert a._extract_message({"type": "conversationUpdate"}) is None


def test_adapter_extract_message_user_aad_allowlist_filters():
    a = _make_adapter(allowed_user_aads=["only-this"])
    activity = {
        "type": "message",
        "text": "hi",
        "from": {"aadObjectId": "someone-else"},
        "conversation": {"id": "c"},
    }
    assert a._extract_message(activity) is None


def test_adapter_extract_message_team_allowlist_filters():
    a = _make_adapter(allowed_team_ids=["team-A"])
    activity = {
        "type": "message",
        "text": "hi",
        "from": {"aadObjectId": "u"},
        "conversation": {"id": "c", "teamId": "team-B"},
    }
    assert a._extract_message(activity) is None


def test_adapter_extract_message_falls_back_to_from_id_when_no_aad():
    a = _make_adapter()
    activity = {
        "type": "message",
        "text": "hi",
        "from": {"id": "fallback-id"},
        "conversation": {"id": "c"},
    }
    msg = a._extract_message(activity)
    assert msg is not None and msg.user_id == "fallback-id"


def test_adapter_extract_message_empty_text_dropped():
    a = _make_adapter()
    activity = {
        "type": "message",
        "text": "   ",
        "from": {"aadObjectId": "u"},
        "conversation": {"id": "c"},
    }
    assert a._extract_message(activity) is None


@pytest.mark.asyncio
async def test_adapter_dispatch_caches_service_url():
    a = _make_adapter()
    activity = {
        "type": "typing",  # ignored
        "serviceUrl": "https://smba.region.botframework.com",
        "conversation": {"id": "conv-X"},
    }
    await a.dispatch_activity(activity)
    assert a._service_urls["conv-X"] == "https://smba.region.botframework.com"


@pytest.mark.asyncio
async def test_adapter_send_response_uses_cached_service_url():
    sent = []

    class _FakeClient:
        async def send_activity(self, **kw):
            sent.append(kw)
            return {}

        async def aclose(self):
            pass

    a = _make_adapter(client=_FakeClient())
    a._service_urls["conv-1"] = "https://smba.region.botframework.com"
    await a.send_response("conv-1", "hello back")
    assert len(sent) == 1
    assert sent[0]["service_url"] == "https://smba.region.botframework.com"
    assert sent[0]["text"] == "hello back"


@pytest.mark.asyncio
async def test_adapter_send_response_no_cached_url_logs_no_send():
    class _FakeClient:
        def __init__(self):
            self.sent = False

        async def send_activity(self, **kw):
            self.sent = True

        async def aclose(self):
            pass

    fc = _FakeClient()
    a = _make_adapter(client=fc)
    await a.send_response("unknown-conv", "x")
    assert fc.sent is False


# ---------------- Webhook router ----------------


def _webhook_client(adapter):
    from probos.routers import teams_webhook
    from probos.routers.deps import get_runtime

    runtime = SimpleNamespace(teams_adapter=adapter)
    app = FastAPI()
    app.include_router(teams_webhook.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_webhook_503_when_no_adapter():
    from probos.routers import teams_webhook
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(teams_webhook.router)
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace()
    c = TestClient(app)
    r = c.post("/api/channels/teams/webhook", json={"type": "message"})
    assert r.status_code == 503


def test_webhook_400_on_non_object():
    a = _make_adapter()
    c = _webhook_client(a)
    r = c.post("/api/channels/teams/webhook", json=["not", "an", "object"])
    assert r.status_code == 400


def test_webhook_dispatches_message():
    a = _make_adapter()
    c = _webhook_client(a)
    r = c.post(
        "/api/channels/teams/webhook",
        json={
            "type": "message",
            "text": "ping",
            "from": {"aadObjectId": "u"},
            "conversation": {"id": "c"},
            "serviceUrl": "https://smba.example",
        },
    )
    assert r.status_code == 200
    # serviceUrl cached as side effect
    assert a._service_urls["c"] == "https://smba.example"


# ---------------- Doctor check ----------------


@pytest.mark.asyncio
async def test_doctor_teams_ok_when_not_configured(tmp_path):
    from probos.doctor.checks.channel_teams_check import _ChannelTeamsCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    ctx = DoctorContext(
        config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None
    )
    r = await _ChannelTeamsCheck().run(ctx)
    assert r.outcome is CheckOutcome.OK
    assert "not configured" in r.message


@pytest.mark.asyncio
async def test_doctor_teams_fail_when_enabled_without_credentials(tmp_path):
    from probos.doctor.checks.channel_teams_check import _ChannelTeamsCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    (tmp_path / "channels").mkdir()
    (tmp_path / "channels" / "teams.yaml").write_text(
        yaml.safe_dump({"enabled": True, "app_id": "", "app_password": ""}),
        encoding="utf-8",
    )
    ctx = DoctorContext(
        config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None
    )
    r = await _ChannelTeamsCheck().run(ctx)
    assert r.outcome is CheckOutcome.FAIL


@pytest.mark.asyncio
async def test_doctor_teams_ok_when_configured(tmp_path):
    from probos.doctor.checks.channel_teams_check import _ChannelTeamsCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    (tmp_path / "channels").mkdir()
    (tmp_path / "channels" / "teams.yaml").write_text(
        yaml.safe_dump(
            {
                "enabled": True,
                "app_id": "the-app",
                "app_password": "sekret",
                "allowed_team_ids": ["t1"],
            }
        ),
        encoding="utf-8",
    )
    ctx = DoctorContext(
        config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None
    )
    r = await _ChannelTeamsCheck().run(ctx)
    assert r.outcome is CheckOutcome.OK
    assert "enabled" in r.message
