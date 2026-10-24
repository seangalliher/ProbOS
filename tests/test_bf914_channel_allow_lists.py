"""BF-914 (#1621): a channel adapter's user allow-list fails closed.

An empty ``allowed_user_ids`` used to mean "everyone", and with no pairing
service wired every admitted sender's slash text reached the ship's shell.
These tests drive the REAL filters -- Discord's ``on_message`` closure, Slack's
poll and webhook entry points -- over fake transports, and record what reaches
``probos.api._handle_slash_command`` instead of running it. Every refusal test
carries a control on the same harness that shows a delivery is observable, so a
harness that never delivered cannot pass.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from types import ModuleType
from typing import Any

import pytest
from httpx import AsyncClient as _AsyncClient
from httpx import MockTransport as _MockTransport
from httpx import Request as _Request
from httpx import Response as _Response

from probos.channels.discord_adapter import DiscordAdapter
from probos.channels.slack_adapter import SlackAdapter
from probos.channels.slack_client import SlackClient
from probos.config import DiscordConfig, SlackConfig
from probos.doctor.checks.channel_discord_check import _ChannelDiscordCheck
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.experience.shell import ProbOSShell

_BASE_LOGGER = "probos.channels.base"
_REFUSAL = "BF-914: refused a message from sender"
_SECRET = "SECRET-TEXT-914"


class _Runtime:
    """The runtime members the base ``handle_message`` and Slack's emitters reach."""

    def __init__(self) -> None:
        self.pairing_service = None  # the production state: no pairing service is wired
        self.processed: list[str] = []

    def emit_event(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def process_natural_language(self, text: str, **_kwargs: Any) -> dict[str, Any]:
        self.processed.append(text)
        return {"response": "all systems nominal"}


@pytest.fixture
def shell_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every text that reaches the ship's shell dispatcher; run none of them."""
    calls: list[str] = []

    async def _record(text: str, _runtime: Any) -> dict[str, Any]:
        calls.append(text)
        return {"response": "recorded"}

    monkeypatch.setattr("probos.api._handle_slash_command", _record)
    return calls


# --- Discord: the real on_message closure over a fake bot ------------------------------------


class _Typing:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


class _Channel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.posted: list[str] = []

    def typing(self) -> _Typing:
        return _Typing()

    async def send(self, content: str) -> None:
        self.posted.append(content)


class _BotUser:
    id = 1
    name = "probos"
    bot = True


class _Bot:
    """The slice of the discord client that the event handlers and ``send_response`` touch."""

    def __init__(self, channel: _Channel) -> None:
        self.user = _BotUser()
        self.handlers: dict[str, Any] = {}
        self._channels = {channel.id: channel}

    def event(self, fn: Any) -> Any:
        self.handlers[fn.__name__] = fn
        return fn

    def get_channel(self, channel_id: int) -> _Channel | None:
        return self._channels.get(channel_id)


class _Author:
    def __init__(self, author_id: int) -> None:
        self.id = author_id
        self.bot = False
        self.display_name = f"sender-{author_id}"


class _Message:
    def __init__(self, channel: _Channel, author_id: int, content: str) -> None:
        self.channel = channel
        self.author = _Author(author_id)
        self.content = content


def _discord(
    monkeypatch: pytest.MonkeyPatch, config: DiscordConfig, runtime: _Runtime | None = None,
) -> tuple[Any, _Channel]:
    """Build the REAL ``on_message`` closure; discord.py is not installed, so a bare module stands in."""
    monkeypatch.setitem(sys.modules, "discord", ModuleType("discord"))
    adapter = DiscordAdapter(runtime or _Runtime(), config)
    channel = _Channel(4242)
    adapter._bot = _Bot(channel)
    adapter._setup_event_handlers()
    return adapter._bot.handlers["on_message"], channel


async def test_discord_an_unlisted_sender_never_reaches_the_shell(
    monkeypatch: pytest.MonkeyPatch, shell_calls: list[str],
) -> None:
    """N1, #1621's acceptance: the real filter and a fake transport; an unlisted user's text is not passed on."""
    assert "/prune" in ProbOSShell.COMMANDS, "premise: /prune is a shell command a sender could reach"
    on_message, channel = _discord(monkeypatch, DiscordConfig(enabled=True, token="t", allowed_user_ids=[7]))

    await on_message(_Message(channel, 7, "!prune agent-1"))
    assert shell_calls == ["/prune agent-1"], "control: a listed sender reaches the shell, so a delivery is observable"
    assert channel.posted == ["recorded"]

    await on_message(_Message(channel, 42, "!prune agent-2"))
    assert shell_calls == ["/prune agent-1"], "an unlisted sender's command must not reach the shell"
    assert channel.posted == ["recorded"], "and the unlisted sender is told nothing"


async def test_discord_an_empty_allow_list_refuses_every_sender(
    monkeypatch: pytest.MonkeyPatch, shell_calls: list[str],
) -> None:
    """N2: the shipped shape (both lists empty) answers no one; the explicit opt-in answers everyone."""
    runtime = _Runtime()
    on_message, channel = _discord(monkeypatch, DiscordConfig(enabled=True, token="t"), runtime)
    for author in (7, 42):
        await on_message(_Message(channel, author, "!prune agent-1"))
        await on_message(_Message(channel, author, "status report"))
    assert shell_calls == []
    assert runtime.processed == []
    assert channel.posted == []

    # Control on the same harness: the opt-in admits the same sender to both paths.
    opened_runtime = _Runtime()
    opened, opened_channel = _discord(
        monkeypatch, DiscordConfig(enabled=True, token="t", allow_all_users=True), opened_runtime,
    )
    await opened(_Message(opened_channel, 42, "!prune agent-1"))
    await opened(_Message(opened_channel, 42, "status report"))
    assert shell_calls == ["/prune agent-1"]
    assert opened_runtime.processed == ["status report"]
    assert opened_channel.posted == ["recorded", "all systems nominal"]


async def test_a_refused_sender_is_logged_once_without_its_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, shell_calls: list[str],
) -> None:
    """N3: two overlapping refusals of one sender and a third log one line; a second sender gets its own.

    Control on the same closure: the listed sender is still delivered and answered, without a refusal line.
    """
    on_message, channel = _discord(monkeypatch, DiscordConfig(enabled=True, token="t", allowed_user_ids=[7]))
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        await asyncio.gather(
            on_message(_Message(channel, 42, f"!prune {_SECRET}")),
            on_message(_Message(channel, 42, f"!prune {_SECRET}")),
        )
        await on_message(_Message(channel, 42, f"status {_SECRET}"))
        await on_message(_Message(channel, 43, f"status {_SECRET}"))
    refusals = [r.getMessage() for r in caplog.records if _REFUSAL in r.getMessage()]
    assert len(refusals) == 2, refusals
    assert "'42'" in refusals[0]
    assert "'43'" in refusals[1]
    assert not any(_SECRET in r.getMessage() for r in caplog.records), "a refusal must not log the message text"
    assert shell_calls == []
    assert channel.posted == []

    # Control on the same closure: the listed sender's command reaches the shell and is answered, so a
    # delivery is observable here, and admitting it adds no refusal line.
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        await on_message(_Message(channel, 7, "!prune agent-1"))
    assert shell_calls == ["/prune agent-1"], "control: the listed sender still reaches the shell on this closure"
    assert channel.posted == ["recorded"]
    assert [r.getMessage() for r in caplog.records if _REFUSAL in r.getMessage()] == refusals


def test_the_refusal_log_is_bounded(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """N4: a repeat before the cap is not named again; past the cap, one line says further senders go unnamed,
    and nothing more is logged. Control: a listed id and the opt-in are admitted on the same adapter, without a line.
    """
    monkeypatch.setattr("probos.channels.base._REFUSED_SENDER_LOG_CAP", 2)
    adapter = SlackAdapter(_Runtime(), SlackConfig(enabled=True, bot_token="xoxb-test"))
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        admitted = [
            adapter._sender_admitted(user, [], allow_all_users=False)
            for user in ("U1", "U1", "U2", "U3", "U4", "U1")
        ]
    assert admitted == [False] * 6
    lines = [r.getMessage() for r in caplog.records if "BF-914" in r.getMessage()]
    assert len([line for line in lines if _REFUSAL in line]) == 2
    assert len([line for line in lines if "not logged by id" in line]) == 1
    assert len(lines) == 3
    named = [line for line in lines if _REFUSAL in line]
    assert "'U1'" in named[0], named
    assert "'U2'" in named[1], named  # the repeat of U1 before the cap is not named a second time

    # Control on the same adapter: a listed id and the opt-in are admitted, and neither adds a line.
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        assert adapter._sender_admitted("U9", ["U9"], allow_all_users=False) is True
        assert adapter._sender_admitted("U8", [], allow_all_users=True) is True
    assert [r.getMessage() for r in caplog.records if "BF-914" in r.getMessage()] == lines


# --- Slack: the real adapter over a fake Web API -----------------------------------------------


class _SlackApi:
    """A fake Slack Web API: identity, no member channels, a fixed history, recorded posts."""

    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.posted: list[str] = []

    def __call__(self, request: _Request) -> _Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "auth.test":
            return _Response(200, json={"ok": True, "user_id": "U_BOT", "team": "T1"})
        if method == "conversations.list":
            return _Response(200, json={"ok": True, "channels": []})
        if method == "conversations.history":
            return _Response(200, json={"ok": True, "messages": self.history})
        if method == "chat.postMessage":
            self.posted.append(json.loads(request.content)["text"])
            return _Response(200, json={"ok": True, "ts": "9.0"})
        return _Response(200, json={"ok": False, "error": f"unexpected {method}"})


@pytest.fixture
async def slack_api() -> AsyncIterator[tuple[_SlackApi, SlackClient]]:
    api = _SlackApi()
    async with _AsyncClient(transport=_MockTransport(api)) as http:
        yield api, SlackClient(bot_token="xoxb-test", http=http)


async def test_slack_poll_refuses_an_unlisted_sender_before_the_shell(
    slack_api: tuple[_SlackApi, SlackClient], shell_calls: list[str],
) -> None:
    """N5: the real poll path; only the listed sender reaches the shell and is answered."""
    api, client = slack_api
    api.history = [  # Slack answers newest first
        {"user": "U_OUT", "text": f"/prune agent-2 {_SECRET}", "ts": "2.0"},
        {"user": "U_IN", "text": "/prune agent-1", "ts": "1.0"},
    ]
    config = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=["U_IN"])
    adapter = SlackAdapter(_Runtime(), config, client=client)
    await adapter._process_channel("C1")
    assert shell_calls == ["/prune agent-1"], "control: the listed sender was delivered; the unlisted one was not"
    assert api.posted == ["recorded"]


async def test_slack_receive_refuses_on_an_empty_list_and_admits_with_the_opt_in(
    slack_api: tuple[_SlackApi, SlackClient], shell_calls: list[str],
) -> None:
    """N6: the webhook entry point, both directions, on one client."""
    _api, client = slack_api
    closed = SlackAdapter(_Runtime(), SlackConfig(enabled=True, bot_token="xoxb-test"), client=client)
    assert await closed.receive(text="/prune agent-1", channel_id="C1", user_id="U_ANY") == ""
    assert shell_calls == []
    opened_config = SlackConfig(enabled=True, bot_token="xoxb-test", allow_all_users=True)
    opened = SlackAdapter(_Runtime(), opened_config, client=client)
    assert await opened.receive(text="/prune agent-1", channel_id="C1", user_id="U_ANY") == "recorded"
    assert shell_calls == ["/prune agent-1"], "control: the same entry point delivers once the opt-in is on"


@pytest.mark.parametrize(
    ("allowed", "allow_all", "user", "admitted"),
    [
        ([], False, "U1", False),
        (["U1"], False, "U1", True),
        (["U1"], False, "U2", False),
        ([], True, "U2", True),
        (["U1"], True, "U2", True),
    ],
)
def test_slack_convert_message_applies_the_rule(
    allowed: list[str], allow_all: bool, user: str, admitted: bool,
) -> None:
    """N7: the boundary table of the one rule, on the real poll filter."""
    config = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=allowed, allow_all_users=allow_all)
    adapter = SlackAdapter(_Runtime(), config)
    converted = adapter._convert_message("C1", {"user": user, "text": "hi", "ts": "1.0"})
    assert (converted is not None) is admitted


@pytest.mark.parametrize(
    ("allowed", "allow_all", "expected"),
    [
        ([], False, "channels.slack.allowed_user_ids is empty, so this adapter refuses every sender"),
        (["U1"], False, None),
        ([], True, "channels.slack.allow_all_users is on"),
    ],
)
async def test_slack_start_states_who_it_admits(
    slack_api: tuple[_SlackApi, SlackClient], caplog: pytest.LogCaptureFixture,
    allowed: list[str], allow_all: bool, expected: str | None,
) -> None:
    """N8: the start warning names an adapter that will admit no one, or everyone, and is silent otherwise."""
    _api, client = slack_api
    config = SlackConfig(enabled=True, bot_token="xoxb-test", allowed_user_ids=allowed, allow_all_users=allow_all)
    adapter = SlackAdapter(_Runtime(), config, client=client)
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        await adapter.start()
    assert adapter._started is True, "control: start ran to the end"
    lines = [r.getMessage() for r in caplog.records if "BF-914" in r.getMessage()]
    if expected is None:
        assert lines == []
    else:
        assert len(lines) == 1
        assert expected in lines[0]


class _StubIntents:
    message_content = False

    @classmethod
    def default(cls) -> _StubIntents:
        return cls()


class _StubClient:
    def __init__(self, *, intents: _StubIntents) -> None:
        self.intents = intents
        self.handlers: dict[str, Any] = {}

    def event(self, fn: Any) -> Any:
        self.handlers[fn.__name__] = fn
        return fn

    async def start(self, _token: str) -> None:
        return None


async def test_discord_start_warns_when_it_admits_no_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """N9: the Discord start path, through a stub discord module (discord.py is not installed here)."""
    stub = ModuleType("discord")
    stub.Intents = _StubIntents  # type: ignore[attr-defined]
    stub.Client = _StubClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "discord", stub)
    adapter = DiscordAdapter(_Runtime(), DiscordConfig(enabled=True, token="t"))
    with caplog.at_level(logging.WARNING, logger=_BASE_LOGGER):
        await adapter.start()
        assert adapter._bot_task is not None
        await adapter._bot_task
    assert adapter._started is True, "control: start ran to the end"
    lines = [r.getMessage() for r in caplog.records if "BF-914" in r.getMessage()]
    assert len(lines) == 1
    assert "channels.discord.allowed_user_ids is empty, so this adapter refuses every sender" in lines[0]


# --- The doctor and the defaults ----------------------------------------------------------------


class _Channels:
    def __init__(self, discord: DiscordConfig) -> None:
        self.discord = discord


class _Config:
    def __init__(self, discord: DiscordConfig) -> None:
        self.channels = _Channels(discord)


@pytest.mark.parametrize(
    ("allowed", "allow_all", "outcome", "phrase"),
    [
        ([789], False, CheckOutcome.OK, "1 user allow-list"),
        ([], False, CheckOutcome.WARN, "refuses every sender"),
        ([], True, CheckOutcome.WARN, "every sender who can reach the bot is admitted"),
        ([789], True, CheckOutcome.WARN, "every sender who can reach the bot is admitted"),
    ],
)
async def test_doctor_channel_discord_judges_the_user_allow_list(
    tmp_path: Any, allowed: list[int], allow_all: bool, outcome: CheckOutcome, phrase: str,
) -> None:
    """N10, #1621's acceptance: the doctor names an empty allow-list and an open adapter."""
    discord = DiscordConfig(enabled=True, token="t", allowed_user_ids=allowed, allow_all_users=allow_all)
    ctx = DoctorContext(config=_Config(discord), home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _ChannelDiscordCheck().run(ctx)
    assert result.outcome is outcome
    assert phrase in result.message
    if outcome is CheckOutcome.WARN:
        assert "channels.discord" in result.remediation


@pytest.mark.parametrize("model", [DiscordConfig, SlackConfig])
def test_the_opt_in_is_off_by_default_and_a_copy_of_todays_block_keeps_it_off(model: Any) -> None:
    """N11: config/system.yaml's channel blocks name no opt-in, so a copy of them admits no one."""
    shipped = {"enabled": True, "allowed_channel_ids": [], "allowed_user_ids": []}
    assert model().allow_all_users is False
    assert model(**shipped).allow_all_users is False
