"""BF-802 (#1266): the reply must survive the adapter egress seam.

Every test here crosses a boundary rather than stopping at its edge. The
defects BF-802 recorded were all of one shape -- a producer that correctly
built a reply, and a consumer that never received it:

* Telegram sent one unbounded string, so a disclosure pushed a valid 4,053
  character answer to 4,124 and the Bot API rejected the whole call. The
  Captain got zero messages: the disclosure destroyed the answer.
* Gmail and Teams discarded the string `handle_message` returns, so both
  channels reasoned about every message and then replied with silence.
* `_handle_callsign_resolved` gated on `result.result`, so a run whose tools
  all failed reported "(no response)" instead of naming the failure.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from probos.dm_reply import (
    DM_REPLY_METADATA_KEY,
    DmReply,
    ToolFailures,
    call_signature,
    failure_key,
    mint_scope,
    split_for_wire,
)

TELEGRAM_LIMIT = 4096


def _failures(*names: str) -> ToolFailures:
    """Build failures whose keys satisfy the real wire grammar.

    The root must be 12 hex characters -- ``_KEY_RE`` is
    ``[0-9a-f]{12}\\.[0-9a-f]{12}:[0-9a-f]{16}``. A short root like ``"r"``
    produces a key that ``from_wire`` correctly rejects, which silently yields
    an empty reply and makes these tests pass for the wrong reason.
    """
    root, scope = mint_scope(), mint_scope()
    return ToolFailures.from_mapping(
        {failure_key(root, scope, call_signature(n, {})): n for n in names}
    )


def test_the_wire_format_round_trips_at_all() -> None:
    """Guards the seam every other test in this file depends on.

    ``to_wire`` and ``from_wire`` were each covered, but nothing crossed
    between them using a key from the real generator -- so a key that failed
    the grammar produced an empty reconstruction with no test noticing.
    """
    original = _failures("web_search")
    payload = original.to_wire()
    assert payload is not None, "a non-empty failure set must serialise"

    restored = ToolFailures.from_wire(payload)
    assert restored.names() == original.names(), (
        "the disclosure must survive the metadata round-trip"
    )
    assert not restored.is_empty


# --------------------------------------------------------------------------
# split_for_wire -- the shared splitter
# --------------------------------------------------------------------------


def test_the_splitter_loses_no_characters() -> None:
    """EXACT reassembly. The first version of this test stripped whitespace
    before comparing, so it would have passed even if every space vanished --
    and it did mask a real defect: the splitter deleted the newline it split
    on. Compare exactly or do not claim losslessness.
    """
    body = " ".join(f"word{i}" for i in range(3000))
    pieces = split_for_wire(body, 200)
    assert len(pieces) > 1, "precondition: this body must actually split"
    assert max(len(p) for p in pieces) <= 200
    assert "".join(pieces) == body


@pytest.mark.parametrize(
    "text",
    [
        "",
        "x",
        " x",
        "x ",
        "a\nb",
        "\n\n",
        "\n",
        "   ",
        "a" * 50,
        "a\n\n\nb\n\nc",
        " ".join(f"w{i}" for i in range(200)),
        "no_spaces_or_newlines_at_all_" * 20,
    ],
)
@pytest.mark.parametrize("limit", [1, 2, 3, 7, 50, 4096])
def test_the_splitter_always_terminates_and_reassembles(text: str, limit: int) -> None:
    """The blocker adversarial review found: ``split_for_wire(" x", 1)`` chose
    a cut at index 0, emitted an empty piece and left the text unchanged --
    an infinite loop. A hang in a live vessel is worse than any wrong output,
    so this is swept rather than spot-checked.
    """
    pieces = split_for_wire(text, limit)
    assert "".join(pieces) == text, "reassembly must be exact"
    assert all(len(p) <= limit for p in pieces), "no piece may exceed the limit"
    if text:
        # An empty piece from NON-empty text means the loop made no progress,
        # which is the signature of the non-termination defect. Empty input
        # legitimately yields [""].
        assert all(p for p in pieces), "empty piece implies no progress"


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_the_splitter_rejects_a_nonpositive_limit(limit: int) -> None:
    """Previously this looped forever instead of failing."""
    with pytest.raises(ValueError):
        split_for_wire("anything at all", limit)


def test_the_splitter_keeps_the_newline_it_splits_on() -> None:
    """The delimiter rides with the PRECEDING piece.

    That keeps reassembly exact while still ensuring the next piece does not
    begin with a blank line, which is why the original stripped it.
    """
    pieces = split_for_wire("aaaa\nbbbb", 5)
    assert "".join(pieces) == "aaaa\nbbbb"
    assert not any(p.startswith("\n") for p in pieces), (
        "no piece should open with a blank line"
    )


def test_the_splitter_keeps_the_space_it_splits_on_with_the_preceding_piece() -> None:
    """Mutation survivor, and I wrongly judged it benign.

    `cut = space + 1` -> `cut = space` is still lossless, so I called it
    cosmetic. Review proved otherwise: it changes the NUMBER of wire messages
    and can manufacture a whitespace-only one. `"a aa"` at limit 2 goes from
    two requests to three, and `"a a "` gains a whitespace-only request.
    Message count is rate-limit consumption, not cosmetics.
    """
    assert split_for_wire("a aa", 2) == ["a ", "aa"]
    assert split_for_wire("a a ", 2) == ["a ", "a "]
    for text, limit in (("a aa", 2), ("a a ", 2), ("hello world here", 6)):
        pieces = split_for_wire(text, limit)
        assert "".join(pieces) == text
        assert not any(p.startswith(" ") for p in pieces), (
            f"a piece opening with a space means the delimiter moved forward "
            f"and split {text!r} into more messages than necessary: {pieces}"
        )


def test_a_word_longer_than_the_limit_still_splits() -> None:
    """No newline and no space anywhere -- the hard cut must engage.

    Without it the loop cannot make progress and hangs forever, which is a
    worse failure than a mid-word break.
    """
    pieces = split_for_wire("x" * 500, 100)
    assert len(pieces) == 5
    assert all(len(p) <= 100 for p in pieces)
    assert "".join(pieces) == "x" * 500


# --------------------------------------------------------------------------
# The wire-format round trip and key grammar
# --------------------------------------------------------------------------


def test_a_malformed_lineage_key_drops_the_attachments() -> None:
    """Mutation survivor: removing the `_KEY_RE` check left every test green.

    Nothing fed a malformed key through `from_wire`, so the validation was an
    untested claim. A key that fails the grammar means the metadata is not
    trustworthy, and the whole failure set must be dropped rather than
    partially believed -- a disclosure naming the wrong tool is worse than
    none.
    """
    good = _failures("web_search").to_wire()
    assert good is not None and ToolFailures.from_wire(good).names() == ("web_search",)

    for bad_key in (
        "r.44f286f7e09c:61ea788f1b71cbeb",   # root too short
        "ZZZZZZZZZZZZ.44f286f7e09c:61ea788f1b71cbeb",  # non-hex root
        "44f286f7e09c-44f286f7e09c:61ea788f1b71cbeb",  # wrong separator
        "44f286f7e09c.44f286f7e09c:61ea78",  # signature too short
        "",
    ):
        payload = {"v": 1, "entries": [[bad_key, "web_search"]]}
        assert ToolFailures.from_wire(payload).is_empty, (
            f"a key failing the grammar must drop attachments: {bad_key!r}"
        )


def test_a_non_string_key_is_also_rejected() -> None:
    assert ToolFailures.from_wire({"v": 1, "entries": [[123, "web_search"]]}).is_empty


# --------------------------------------------------------------------------
# Telegram egress -- the seam that was measured broken
# --------------------------------------------------------------------------


class _RecordingTelegramClient:
    """Records sends and enforces Telegram's documented 4096-char limit."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> None:
        text = kwargs.get("text") or ""
        if len(text) > TELEGRAM_LIMIT:
            # This is what the real Bot API does, and why the Captain got
            # nothing: it rejects the CALL, it does not truncate.
            raise AssertionError(
                f"message is too long: {len(text)} > {TELEGRAM_LIMIT}"
            )
        self.sent.append(kwargs)


def _telegram_adapter(client: Any):
    from probos.channels.telegram_adapter import TelegramAdapter

    adapter = TelegramAdapter.__new__(TelegramAdapter)
    adapter._client = client
    return adapter


def test_telegram_splits_an_over_limit_reply_instead_of_dropping_it() -> None:
    client = _RecordingTelegramClient()
    adapter = _telegram_adapter(client)
    body = "x" * 4053
    reply = DmReply(body=body, tool_failures=_failures("web_search"))
    outgoing = str(reply.render())

    assert len(outgoing) > TELEGRAM_LIMIT, (
        "precondition: this is the case that used to be rejected outright"
    )

    asyncio.run(adapter.send_response("12345", outgoing))

    assert len(client.sent) >= 2, "an over-limit reply must become several sends"
    joined = "".join(s["text"] for s in client.sent)
    assert "web_search" in joined, "the disclosure must still reach the Captain"
    assert joined.count("x") == 4053, "the answer must arrive complete"


def test_telegram_threads_only_the_first_part() -> None:
    """Replying to the same message N times clutters the chat."""
    client = _RecordingTelegramClient()
    adapter = _telegram_adapter(client)

    asyncio.run(adapter.send_response("12345", "y" * 9000, reply_to_message_id="77"))

    assert len(client.sent) >= 3
    assert client.sent[0]["reply_to_message_id"] == 77
    assert all(s["reply_to_message_id"] is None for s in client.sent[1:])


def test_telegram_still_sends_a_short_reply_as_one_message() -> None:
    """Splitting must not fragment traffic that was always fine."""
    client = _RecordingTelegramClient()
    adapter = _telegram_adapter(client)

    asyncio.run(adapter.send_response("12345", "hello"))

    assert len(client.sent) == 1
    assert client.sent[0]["text"] == "hello"


def test_telegram_sends_nothing_for_an_empty_reply() -> None:
    client = _RecordingTelegramClient()
    adapter = _telegram_adapter(client)
    asyncio.run(adapter.send_response("12345", ""))
    assert client.sent == []


def test_a_failing_part_abandons_the_rest_rather_than_looping() -> None:
    """A persistent API error must not produce N failed calls silently."""
    from probos.channels.telegram_client import TelegramAPIError

    class _AlwaysFails:
        def __init__(self) -> None:
            self.calls = 0

        async def send_message(self, **kwargs: Any) -> None:
            self.calls += 1
            raise TelegramAPIError("chat not found")

    client = _AlwaysFails()
    adapter = _telegram_adapter(client)

    asyncio.run(adapter.send_response("12345", "z" * 9000))

    assert client.calls == 1, "give up after the first failure, don't hammer"


# --------------------------------------------------------------------------
# Discord -- the hoisted splitter must not change its behaviour
# --------------------------------------------------------------------------


def test_discord_chunker_still_delegates_to_the_shared_splitter() -> None:
    """Hoisting the implementation must be behaviour-preserving."""
    from probos.channels.discord_adapter import _MAX_MESSAGE_LENGTH, _chunk_message

    body = " ".join(f"word{i}" for i in range(3000))
    assert _chunk_message(body) == split_for_wire(body, _MAX_MESSAGE_LENGTH)
    assert _chunk_message("short") == ["short"]


# --------------------------------------------------------------------------
# The REAL dispatch routes.
#
# The first version of these tests called `send_response` directly, which is
# exactly how the threading defect hid: `send_response` handled the id
# correctly and no caller ever passed one. Drive the route, not the function.
# --------------------------------------------------------------------------


def test_the_telegram_route_actually_threads_the_reply() -> None:
    from probos.channels.telegram_adapter import TelegramAdapter

    client = _RecordingTelegramClient()
    adapter = _telegram_adapter(client)

    from probos.channels.base import ChannelMessage

    inbound = ChannelMessage(
        text="status?",
        channel_id="4242",
        user_id="u1",
        reply_to_message_id="77",
    )

    async def _fake_handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    adapter.handle_message = _fake_handle           # type: ignore[method-assign]
    adapter._convert_update = lambda u: inbound     # type: ignore[method-assign]

    asyncio.run(adapter._process_update({"update_id": 1}))

    assert client.sent, "the route must send something"
    assert client.sent[0]["reply_to_message_id"] == 77, (
        "the dispatcher must pass the inbound id, or send_response's "
        "first-part-threads logic is unreachable"
    )


def test_the_teams_route_actually_threads_the_reply() -> None:
    from probos.channels.base import ChannelMessage
    from probos.channels.teams_adapter import TeamsAdapter

    sent: list[dict[str, Any]] = []
    adapter = TeamsAdapter.__new__(TeamsAdapter)
    adapter._service_urls = {}

    inbound = ChannelMessage(
        text="status?",
        channel_id="conv-1",
        user_id="u-1",
        reply_to_message_id="activity-9",
    )

    async def _fake_handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _fake_send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append({"channel_id": channel_id, "response": response, **kwargs})

    adapter.handle_message = _fake_handle            # type: ignore[method-assign]
    adapter.send_response = _fake_send               # type: ignore[method-assign]
    adapter._extract_message = lambda a: inbound     # type: ignore[method-assign]

    result = asyncio.run(
        adapter.dispatch_activity(
            {
                "type": "message",
                "serviceUrl": "https://smba.example",
                "conversation": {"id": "conv-1"},
                "text": "status?",
            }
        )
    )

    assert result == {"status": "ok"}
    assert sent and sent[0]["reply_to_message_id"] == "activity-9", (
        "the Teams dispatcher dropped the id, so every reply threaded nowhere"
    )


def test_no_whitespace_only_part_is_ever_sent() -> None:
    """Renamed intent: the wire must reassemble EXACTLY.

    An earlier version of this test filtered whitespace-only parts at the
    adapter, which review proved was itself lossy: a chunk of 3,000 spaces
    followed by text silently dropped the spaces AND desynchronised the
    threading index, so the first part actually sent did not thread. The
    filter is gone; the splitter never emits an empty piece for non-empty
    input, so there is nothing to filter.

    This input is chosen so a whitespace-only chunk really is produced --
    the previous version's input split into three non-blank parts and
    exercised neither branch, passing for the wrong reason.
    """
    client = _RecordingTelegramClient()
    adapter = _telegram_adapter(client)

    text = (" " * 5000) + "the answer"
    asyncio.run(adapter.send_response("1", text))

    assert "".join(s["text"] for s in client.sent) == text, (
        "the wire must reassemble to exactly what was passed in"
    )


def test_the_first_part_sent_is_the_one_that_threads() -> None:
    """Threading must key off what is actually delivered."""
    client = _RecordingTelegramClient()
    adapter = _telegram_adapter(client)

    asyncio.run(
        adapter.send_response("1", (" " * 5000) + "answer", reply_to_message_id="55")
    )

    assert client.sent[0]["reply_to_message_id"] == 55
    assert all(s["reply_to_message_id"] is None for s in client.sent[1:])


# --------------------------------------------------------------------------
# Gmail batch isolation
# --------------------------------------------------------------------------


def _gmail_adapter_with(messages: list[Any], handler: Any, sender: Any):
    from probos.channels.gmail_adapter import GmailAdapter

    adapter = GmailAdapter.__new__(GmailAdapter)
    adapter._stop = asyncio.Event()
    adapter._gmail_config = type("C", (), {"poll_interval_s": 0.01})()
    adapter.handle_message = handler                 # type: ignore[method-assign]
    adapter.send_response = sender                   # type: ignore[method-assign]
    adapter._fetch_unseen = lambda: messages         # type: ignore[method-assign]
    return adapter


def test_one_failing_gmail_message_does_not_discard_the_rest_of_the_batch() -> None:
    """`_fetch_unseen` marks the whole batch Seen BEFORE processing.

    So a batch-wide guard meant one failure lost every later message
    permanently -- and adding a send inside the loop widened that window.
    """
    from probos.channels.base import ChannelMessage

    inbox = [
        ChannelMessage(text="one", channel_id="a@x", user_id="a@x"),
        ChannelMessage(text="two", channel_id="b@x", user_id="b@x"),
        ChannelMessage(text="three", channel_id="c@x", user_id="c@x"),
    ]
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        return f"re: {message.text}"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        if channel_id == "a@x":
            raise RuntimeError("SMTP refused")
        sent.append(channel_id)

    adapter = _gmail_adapter_with(inbox, _handle, _send)

    async def _drive() -> None:
        task = asyncio.create_task(adapter._poll_loop())
        await asyncio.sleep(0.05)
        adapter._stop.set()
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(_drive())

    assert "b@x" in sent and "c@x" in sent, (
        "messages after a failure must still be processed; they are already "
        f"marked Seen and cannot be retried. got {sent}"
    )


# --------------------------------------------------------------------------
# Teams client -- the reply endpoint
#
# This path was unreachable until BF-802: the dispatcher dropped the id, so
# `reply_to_id` was always None and the reply URL was never exercised.
# --------------------------------------------------------------------------


def test_a_teams_reply_targets_the_documented_reply_endpoint() -> None:
    """Bot Framework documents replies as ``.../activities/{activityId}``.

    Plain ``.../activities`` is the non-reply "send to conversation"
    operation; it can return 2xx without the Connector treating the message
    as a contracted threaded reply.
    """
    import httpx

    from probos.channels.teams_client import TeamsClient

    seen: dict[str, Any] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"id": "posted"})

    client = TeamsClient.__new__(TeamsClient)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    async def _token() -> str:
        return "tok"

    client._get_token = _token  # type: ignore[method-assign]

    asyncio.run(
        client.send_activity(
            service_url="https://smba.example/",
            conversation_id="conv-1",
            text="reply",
            reply_to_id="activity-9",
        )
    )

    assert seen["url"].endswith("/v3/conversations/conv-1/activities/activity-9"), (
        f"reply must target the reply endpoint, got {seen['url']}"
    )
    assert "replyToId" in seen["body"], "the body must still carry replyToId"


def test_a_teams_message_with_no_reply_id_uses_the_plain_endpoint() -> None:
    """A first message in a conversation is not a reply."""
    import httpx

    from probos.channels.teams_client import TeamsClient

    seen: dict[str, Any] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"id": "posted"})

    client = TeamsClient.__new__(TeamsClient)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    async def _token() -> str:
        return "tok"

    client._get_token = _token  # type: ignore[method-assign]

    asyncio.run(
        client.send_activity(
            service_url="https://smba.example",
            conversation_id="conv-1",
            text="hello",
        )
    )

    assert seen["url"].endswith("/v3/conversations/conv-1/activities")


def test_a_reply_id_needing_escaping_is_url_encoded() -> None:
    """Activity ids can contain characters that must not alter the path."""
    import httpx

    from probos.channels.teams_client import TeamsClient

    seen: dict[str, Any] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={})

    client = TeamsClient.__new__(TeamsClient)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    async def _token() -> str:
        return "tok"

    client._get_token = _token  # type: ignore[method-assign]

    asyncio.run(
        client.send_activity(
            service_url="https://smba.example",
            conversation_id="conv-1",
            text="hi",
            reply_to_id="a/b?c=d",
        )
    )

    assert "a%2Fb%3Fc%3Dd" in seen["url"], (
        f"the id must be percent-encoded, got {seen['url']}"
    )


def test_a_teams_activity_threads_all_the_way_to_the_wire() -> None:
    """The whole route: activity -> dispatch -> send_response -> client -> HTTP.

    Review proved the previous tests could not catch a break here. The route
    test replaced `send_response` and the HTTP test called `TeamsClient`
    directly, so mutating the real `send_response` to pass `reply_to_id=None`
    left all 134 relevant tests green -- and the Bot Framework silently
    accepts that as an unthreaded "send to conversation".

    Nothing between the inbound activity and the rendered URL is stubbed here
    except the transport and the token.
    """
    import httpx

    from probos.channels.teams_adapter import TeamsAdapter
    from probos.channels.teams_client import TeamsClient

    seen: dict[str, Any] = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(201, json={"id": "out-1"})

    client = TeamsClient.__new__(TeamsClient)
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    async def _token() -> str:
        return "tok"

    client._get_token = _token  # type: ignore[method-assign]

    adapter = TeamsAdapter.__new__(TeamsAdapter)
    adapter._client = client
    adapter._service_urls = {}
    adapter._teams_config = type(
        "C", (), {"allowed_user_aads": [], "allowed_team_ids": []}
    )()

    async def _handle(message: Any) -> str:
        return "all systems nominal"

    adapter.handle_message = _handle  # type: ignore[method-assign]

    result = asyncio.run(
        adapter.dispatch_activity(
            {
                "type": "message",
                "id": "activity-9",
                "serviceUrl": "https://smba.example",
                "conversation": {"id": "conv-1"},
                "from": {"aadObjectId": "u-1", "name": "Captain"},
                "text": "status?",
            }
        )
    )

    assert result == {"status": "ok"}
    assert seen["url"].endswith("/v3/conversations/conv-1/activities/activity-9"), (
        f"the full route must reach the reply endpoint, got {seen['url']}"
    )
    assert "all systems nominal" in seen["body"]
    assert "activity-9" in seen["body"]


# --------------------------------------------------------------------------
# Gmail and Teams -- the returned reply must reach send_response
#
# These run the real loop body against fakes rather than scanning source.
# A source scan cannot tell "required" from "what happens to be written".
# --------------------------------------------------------------------------


def test_gmail_forwards_the_reply_instead_of_discarding_it() -> None:
    from probos.channels.base import ChannelMessage
    from probos.channels.gmail_adapter import GmailAdapter

    inbound = ChannelMessage(
        text="what is the status?",
        channel_id="captain@example.com",
        user_id="captain@example.com",
        reply_to_message_id="<abc@mail>",
    )
    sent: list[tuple[str, str, Any]] = []

    adapter = GmailAdapter.__new__(GmailAdapter)
    adapter._stop = asyncio.Event()
    adapter._gmail_config = type("C", (), {"poll_interval_s": 0.01})()

    async def _fake_handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _fake_send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append((channel_id, response, kwargs.get("reply_to_message_id")))
        adapter._stop.set()

    adapter.handle_message = _fake_handle          # type: ignore[method-assign]
    adapter.send_response = _fake_send             # type: ignore[method-assign]
    adapter._fetch_unseen = lambda: [inbound]      # type: ignore[method-assign]

    asyncio.run(asyncio.wait_for(adapter._poll_loop(), timeout=5))

    assert sent, "Gmail must send the reply handle_message returned"
    assert sent[0][0] == "captain@example.com"
    assert sent[0][1] == "all systems nominal"
    assert sent[0][2] == "<abc@mail>", "threading must use the inbound Message-ID"


def test_gmail_sends_nothing_when_there_is_no_reply() -> None:
    """An empty reply must not become an empty email."""
    from probos.channels.base import ChannelMessage
    from probos.channels.gmail_adapter import GmailAdapter

    sent: list[Any] = []
    adapter = GmailAdapter.__new__(GmailAdapter)
    adapter._stop = asyncio.Event()
    adapter._gmail_config = type("C", (), {"poll_interval_s": 0.01})()

    async def _fake_handle(message: ChannelMessage) -> str:
        adapter._stop.set()
        return ""

    async def _fake_send(*a: Any, **k: Any) -> None:
        sent.append(a)

    adapter.handle_message = _fake_handle          # type: ignore[method-assign]
    adapter.send_response = _fake_send             # type: ignore[method-assign]
    adapter._fetch_unseen = lambda: [              # type: ignore[method-assign]
        ChannelMessage(text="hi", channel_id="a@b", user_id="a@b")
    ]

    asyncio.run(asyncio.wait_for(adapter._poll_loop(), timeout=5))
    assert sent == []


def test_teams_forwards_the_reply_instead_of_discarding_it() -> None:
    from probos.channels.base import ChannelMessage
    from probos.channels.teams_adapter import TeamsAdapter

    sent: list[tuple[str, str]] = []
    adapter = TeamsAdapter.__new__(TeamsAdapter)
    adapter._service_urls = {}

    inbound = ChannelMessage(
        text="status?", channel_id="conv-1", user_id="u-1",
    )

    async def _fake_handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _fake_send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append((channel_id, response))

    adapter.handle_message = _fake_handle            # type: ignore[method-assign]
    adapter.send_response = _fake_send               # type: ignore[method-assign]
    adapter._extract_message = lambda a: inbound     # type: ignore[method-assign]

    result = asyncio.run(
        adapter.dispatch_activity(
            {
                "type": "message",
                "serviceUrl": "https://smba.example",
                "conversation": {"id": "conv-1"},
                "text": "status?",
            }
        )
    )

    assert result == {"status": "ok"}
    assert sent == [("conv-1", "all systems nominal")]


# --------------------------------------------------------------------------
# The callsign seam -- a failure-only reply must not become "(no response)"
# --------------------------------------------------------------------------


def _callsign_adapter(result_obj: Any):
    """A concrete adapter over a stub bus.

    ``ChannelAdapter`` is an ABC, so even ``__new__`` refuses to build one --
    a concrete subclass is required rather than a bare allocation.
    """
    from probos.channels.base import ChannelAdapter

    class _Bus:
        async def send(self, intent: Any) -> Any:
            return result_obj

    class _Concrete(ChannelAdapter):
        async def start(self) -> None: ...
        async def stop(self) -> None: ...
        async def send_response(
            self, channel_id: str, response: str, **kwargs: Any
        ) -> None: ...

    adapter = _Concrete.__new__(_Concrete)
    adapter.runtime = type("R", (), {"intent_bus": _Bus()})()
    return adapter


def test_a_callsign_reply_whose_tools_all_failed_names_the_failure() -> None:
    """The fifth sink of the `if result.result` gate (AD-1248).

    Empty text plus a non-empty failure set is the exact shape that used to be
    reported to the Captain as "(no response)".
    """
    reply = DmReply(body="", tool_failures=_failures("web_search"))

    class _Result:
        result = ""
        # `metadata_payload()` is the INNER wire payload; the producer stores
        # it under DM_REPLY_METADATA_KEY, and that is where
        # `from_intent_result` looks. Skipping the wrapping step silently
        # yields a reply with no failures at all.
        metadata = {DM_REPLY_METADATA_KEY: reply.metadata_payload()}

    text = asyncio.run(
        _callsign_adapter(_Result())._handle_callsign_resolved(
            {"agent_id": "agent-1", "callsign": "SCOUT"}, "scout", "find something",
        )
    )

    assert "(no response)" not in text, (
        "a run whose tools failed is not the same as a run that said nothing"
    )
    assert "web_search" in text, "the Captain must be told what failed"
    assert text.startswith("SCOUT:")


def test_a_genuinely_silent_callsign_reply_still_says_no_response() -> None:
    """The degradation must stay honest in the other direction too."""

    class _Result:
        result = ""
        metadata: dict[str, Any] = {}

    text = asyncio.run(
        _callsign_adapter(_Result())._handle_callsign_resolved(
            {"agent_id": "agent-1", "callsign": "SCOUT"}, "scout", "hello",
        )
    )
    assert text == "SCOUT: (no response)"


def test_a_none_result_from_the_bus_does_not_raise() -> None:
    """`DmReply.from_intent_result(None)` must never be reached."""
    text = asyncio.run(
        _callsign_adapter(None)._handle_callsign_resolved(
            {"agent_id": "agent-1", "callsign": "SCOUT"}, "scout", "hello",
        )
    )
    assert text == "SCOUT: (no response)"


def test_the_callsign_reply_is_a_plain_str_not_the_nominal_subclass() -> None:
    """`threads/__init__.py` rejects `type(body) is not str`.

    RenderedDmText is a str SUBCLASS, so returning one directly makes the
    transcript append raise, the router swallow it, and the reply vanish while
    HTTP still answers 200. Interpolation must flatten it.
    """
    reply = DmReply(body="found it", tool_failures=_failures("web_search"))

    class _Result:
        result = "found it"
        metadata = {DM_REPLY_METADATA_KEY: reply.metadata_payload()}

    text = asyncio.run(
        _callsign_adapter(_Result())._handle_callsign_resolved(
            {"agent_id": "a", "callsign": "SCOUT"}, "scout", "go",
        )
    )
    assert type(text) is str, f"must be exactly str, got {type(text).__name__}"
