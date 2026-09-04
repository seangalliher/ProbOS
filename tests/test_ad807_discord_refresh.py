"""AD-807: tests for the Discord adapter refresh — channel_name + AD-802a hook + doctor check."""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from probos.channels.base import ChannelMessage, PairingNotificationError
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


# ---------------------------------------------------------------------------
# BF-804: a sender who could not be told how to pair is told nothing at all
# ---------------------------------------------------------------------------


class _FailingPairingService(_FakePairingService):
    """`request_pairing` fails, so no code exists and no notice can be sent."""

    async def request_pairing(self, *, channel: str, raw_id: str) -> str:
        self.requested.append((channel, raw_id))
        raise RuntimeError("the pairing store is unreachable")


class _OnMessageRuntime(_FakeRuntime):
    """Adds the one runtime member the base `handle_message` body reaches."""

    def __init__(
        self, pairing_service=None, *, process_error: Exception | None = None
    ) -> None:
        super().__init__(pairing_service)
        self.process_error = process_error

    async def process_natural_language(
        self, text: str, **kwargs: Any
    ) -> dict[str, Any]:
        if self.process_error is not None:
            raise self.process_error
        return {"response": "all systems nominal"}


class _NullTyping:
    """`async with message.channel.typing():` and nothing more."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc_info: Any) -> bool:
        return False


class _FakeChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.posted: list[str] = []

    def typing(self) -> _NullTyping:
        return _NullTyping()

    async def send(self, content: str) -> None:
        self.posted.append(content)


class _FakeBot:
    """The slice of `discord.Client` that `_setup_event_handlers` touches."""

    def __init__(self) -> None:
        self.user = SimpleNamespace(id=1, name="probos", bot=True)
        self.handlers: dict[str, Any] = {}
        self.channels: dict[int, _FakeChannel] = {}

    def event(self, fn: Any) -> Any:
        self.handlers[fn.__name__] = fn
        return fn

    def get_channel(self, channel_id: int) -> _FakeChannel | None:
        return self.channels.get(channel_id)


class _FakeDiscordMessage:
    def __init__(self, channel: _FakeChannel, author_id: int, content: str) -> None:
        self.channel = channel
        self.content = content
        self.author = SimpleNamespace(
            id=author_id, bot=False, display_name="Ensign Ro"
        )


def _wire_on_message(
    monkeypatch: pytest.MonkeyPatch, runtime: _FakeRuntime
) -> tuple[Any, _FakeChannel]:
    """Build the REAL `on_message` closure over a doubled bot and channel.

    `_setup_event_handlers` imports discord at call time; the extra is not
    installed in this environment, so a bare stub module stands in. Nothing in
    the closure under test touches it -- only `on_ready`, which is never
    invoked here, uses the namespace.
    """
    monkeypatch.setitem(sys.modules, "discord", ModuleType("discord"))
    adapter = DiscordAdapter(runtime, DiscordConfig(enabled=True, token="dummy"))
    bot = _FakeBot()
    channel = _FakeChannel(4242)
    bot.channels[channel.id] = channel
    adapter._bot = bot
    adapter._setup_event_handlers()
    return bot.handlers["on_message"], channel


@pytest.mark.asyncio
async def test_discord_posts_nothing_when_pairing_instructions_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BF-804: the broad handler would post "Processing error: <class>" into
    the channel, changing AD-807's observable behaviour AND disclosing an
    internal exception class to an unpaired, unauthenticated sender. The
    narrow arm must run first and post nothing.
    """
    service = _FailingPairingService()
    on_message, channel = _wire_on_message(
        monkeypatch, _OnMessageRuntime(pairing_service=service)
    )

    await on_message(_FakeDiscordMessage(channel, 42, "status report"))

    assert service.requested == [("discord", "42")], (
        "control: the message really reached the AD-802a gate"
    )
    assert channel.posted == [], "an unpaired sender must be told nothing"
    assert not any("Processing error" in p for p in channel.posted)
    assert not any(
        PairingNotificationError.__name__ in p for p in channel.posted
    ), "the exception class name must never reach the channel"


@pytest.mark.asyncio
async def test_discord_still_reports_other_processing_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DISCRIMINATION CONTROL for the test above.

    The narrow arm must not swallow everything. A paired sender whose
    processing blows up still gets the broad handler's report, which proves
    the probe can observe a channel post at all -- so the empty `posted` list
    above is a real refusal, not a blind spot.
    """
    service = _FakePairingService()
    service.resolved[("discord", "42")] = "did:probos:ro"
    runtime = _OnMessageRuntime(
        pairing_service=service, process_error=RuntimeError("the LLM turn blew up")
    )
    on_message, channel = _wire_on_message(monkeypatch, runtime)

    await on_message(_FakeDiscordMessage(channel, 42, "status report"))

    assert channel.posted == ["Processing error: RuntimeError"], (
        "control: an ordinary failure is still reported to the channel"
    )


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
