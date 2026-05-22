"""AD-807: tests for the Discord adapter refresh — channel_name + AD-802a hook + doctor check."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.channels.base import ChannelMessage
from probos.channels.discord_adapter import DiscordAdapter
from probos.config import DiscordConfig


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


def test_discord_adapter_has_channel_name_for_ad802a():
    """AD-807: DiscordAdapter MUST expose channel_name='discord' so the
    base-class AD-802a pairing-gate fires.
    """
    assert DiscordAdapter.channel_name == "discord"


@pytest.mark.asyncio
async def test_discord_check_pairing_attaches_did_for_known_sender():
    cfg = DiscordConfig(enabled=True, token="dummy")
    ps = _FakePairingService()
    ps.resolved[("discord", "U42")] = "did:foo:1"
    adapter = DiscordAdapter(_FakeRuntime(pairing_service=ps), cfg)
    msg = ChannelMessage(text="hi", channel_id="C1", user_id="U42")
    assert await adapter._check_pairing(msg) is True
    assert msg.paired_did == "did:foo:1"


@pytest.mark.asyncio
async def test_discord_check_pairing_mints_code_for_unknown_sender():
    sent: list[tuple[str, str]] = []

    class _CapturingAdapter(DiscordAdapter):
        async def send_response(self, channel_id, response, **kwargs):
            sent.append((channel_id, response))

    cfg = DiscordConfig(enabled=True, token="dummy")
    ps = _FakePairingService()
    adapter = _CapturingAdapter(_FakeRuntime(pairing_service=ps), cfg)
    msg = ChannelMessage(text="hi", channel_id="C1", user_id="U42")
    proceed = await adapter._check_pairing(msg)
    assert proceed is False
    assert ps.requested == [("discord", "U42")]
    assert len(sent) == 1
    assert "probos pairing approve discord ABC123" in sent[0][1]


@pytest.mark.asyncio
async def test_doctor_channel_discord_ok_when_disabled(tmp_path):
    from probos.doctor.checks.channel_discord_check import _ChannelDiscordCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    config = SimpleNamespace(channels=SimpleNamespace(discord=DiscordConfig(enabled=False)))
    ctx = DoctorContext(config=config, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelDiscordCheck().run(ctx)
    assert result.outcome is CheckOutcome.OK
    assert "disabled" in result.message


@pytest.mark.asyncio
async def test_doctor_channel_discord_fail_when_enabled_but_no_token(tmp_path):
    from probos.doctor.checks.channel_discord_check import _ChannelDiscordCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    config = SimpleNamespace(channels=SimpleNamespace(discord=DiscordConfig(enabled=True, token="")))
    ctx = DoctorContext(config=config, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelDiscordCheck().run(ctx)
    assert result.outcome is CheckOutcome.FAIL


@pytest.mark.asyncio
async def test_doctor_channel_discord_ok_when_token_present(tmp_path):
    from probos.doctor.checks.channel_discord_check import _ChannelDiscordCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    config = SimpleNamespace(
        channels=SimpleNamespace(
            discord=DiscordConfig(
                enabled=True,
                token="MTIzNDU2.dummy.token",
                allowed_channel_ids=[123, 456],
                allowed_user_ids=[789],
            ),
        ),
    )
    ctx = DoctorContext(config=config, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelDiscordCheck().run(ctx)
    assert result.outcome is CheckOutcome.OK
    assert "token present" in result.message
