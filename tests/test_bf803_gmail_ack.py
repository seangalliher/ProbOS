"""BF-803 (#1267): Gmail inbound delivery must be at-least-once.

`_fetch_one` used to set ``\\Seen`` while fetching, so a message whose
processing raised was already acknowledged, was never re-fetched, and was
dropped in silence. BF-802 narrowed the blast radius from the batch to one
message without making delivery reliable.

The defect lived in the ORDER of two individually correct operations, so a
unit test of either one could not see it. Every test here drives the real
`_poll_loop` against the real `_fetch_unseen` / `_acknowledge` and an IMAP
double, and the double refuses the sequence-number commands outright: a
deferred acknowledgement necessarily lands in a later session, where a
retained sequence number may address a different message.

Two properties are load-bearing and easy to fake away, so the double models
both and each is pinned by its own control:

* RFC 3501 6.4.5 -- retrieving ``RFC822`` or ``BODY[]`` sets ``\\Seen``
  implicitly, whatever the addressing. A double that flagged only on STORE
  reported an empty `seen` set either way, which let a first fix ship UID
  addressing over an unchanged ``(RFC822)`` fetch that still flagged the
  mail on a real server.
* A reply is delivered only when the SMTP server accepts it. A test that
  installs its own raising `send_response` exercises the loop, not the
  adapter, so the SMTP tests below drive the real `send_response` /
  `_send_sync` against an SMTP double.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any, Callable

import pytest

import probos.channels.gmail_adapter as gmail_adapter
from probos.channels.base import ChannelMessage
from probos.channels.gmail_adapter import (
    _ACK_CACHE_MAX,
    GmailAdapter,
    GmailDeliveryError,
    _InboundMail,
)
from probos.channels.gmail_config import GmailAdapterConfig

_LEGACY_COMMANDS = ("search", "fetch", "store")


# --------------------------------------------------------------------------
# The IMAP double
# --------------------------------------------------------------------------


class _FakeIMAP:
    """An ``IMAP4_SSL`` double that only speaks UID.

    ``search`` / ``fetch`` / ``store`` record the attempt and then raise. A
    double that quietly accepted the sequence-number forms would let the
    regression BF-803 exists to prevent pass unnoticed.

    The mailbox is keyed by the EXACT UID token ``UID SEARCH`` returned, so a
    UID that does not round-trip byte-for-byte simply fails to fetch.

    ``seen`` is mutated by an explicit STORE **and** by any non-PEEK body
    fetch, because RFC 3501 6.4.5 makes the latter set ``\\Seen`` implicitly.
    `test_the_double_flags_mail_on_a_non_peek_fetch` is the control for that.

    ``store_refuse`` narrows the STORE failure to named UIDs, so one message
    can fail persistently while the rest of the batch is acknowledged
    normally -- the traffic that must not cost the failing one its entry.
    """

    def __init__(
        self, mailbox: dict[bytes, bytes], uidvalidity: bytes = b"1000"
    ) -> None:
        self.messages = dict(mailbox)
        self.seen: set[bytes] = set()
        self.uidvalidity = uidvalidity
        self.calls: list[tuple[Any, ...]] = []
        self.selects: list[str] = []
        self.logins = 0
        self.logouts = 0
        self.store_status = "OK"
        self.store_error: Exception | None = None
        self.store_refuse: set[bytes] = set()

    # -- imaplib surface ---------------------------------------------------

    def login(self, address: str, password: str) -> tuple[str, list[Any]]:
        self.logins += 1
        return ("OK", [b"logged in"])

    def select(self, mailbox: str) -> tuple[str, list[Any]]:
        self.selects.append(mailbox)
        self.calls.append(("select", mailbox))
        return ("OK", [str(len(self.messages)).encode()])

    def response(self, code: str) -> tuple[str, list[Any]]:
        self.calls.append(("response", code))
        if code == "UIDVALIDITY":
            return ("UIDVALIDITY", [self.uidvalidity])
        return (code, [None])

    def uid(self, command: str, *args: Any) -> tuple[str, list[Any]]:
        self.calls.append(("uid", command, *args))
        if command == "SEARCH":
            unseen = b" ".join(u for u in self.messages if u not in self.seen)
            return ("OK", [unseen])
        if command == "FETCH":
            uid = args[0]
            items = str(args[1]).upper() if len(args) > 1 else ""
            raw = self.messages.get(uid)
            if raw is None:
                return ("NO", [None])
            # RFC 3501 6.4.5: RFC822 is functionally equivalent to BODY[] and
            # retrieving either sets \Seen implicitly. Only BODY.PEEK[] does
            # not. Switching the ADDRESSING to UID does not change this, which
            # is exactly what a double that flagged only on STORE could not
            # show.
            if "BODY.PEEK[" not in items:
                self.seen.add(uid)
            # The server never echoes PEEK; RFC 3501 7.4.2 names it BODY[].
            item = b"BODY[]" if "BODY" in items else b"RFC822"
            envelope = b"1 (UID " + uid + b" " + item + b" {%d}" % len(raw)
            return ("OK", [(envelope, raw), b")"])
        if command == "STORE":
            if self.store_error is not None:
                raise self.store_error
            if args[0] in self.store_refuse:
                return ("NO", [b""])
            if self.store_status == "OK":
                self.seen.add(args[0])
            return (self.store_status, [b""])
        raise AssertionError(f"unexpected UID command: {command!r}")

    def search(self, *args: Any) -> tuple[str, list[Any]]:
        self.calls.append(("search", *args))
        raise AssertionError("BF-803: sequence-number SEARCH must not be used")

    def fetch(self, *args: Any) -> tuple[str, list[Any]]:
        self.calls.append(("fetch", *args))
        raise AssertionError("BF-803: sequence-number FETCH must not be used")

    def store(self, *args: Any) -> tuple[str, list[Any]]:
        self.calls.append(("store", *args))
        raise AssertionError("BF-803: sequence-number STORE must not be used")

    def close(self) -> tuple[str, list[Any]]:
        return ("OK", [b"closed"])

    def logout(self) -> tuple[str, list[Any]]:
        self.logouts += 1
        return ("BYE", [b"bye"])


# --------------------------------------------------------------------------
# The SMTP double
# --------------------------------------------------------------------------


class _FakeSMTP:
    """An ``smtplib.SMTP`` double that stands in for the module attribute.

    It is callable, so the same object is both the patched constructor and the
    record of what the adapter did with the session. ``delivered`` grows only
    when the server actually accepted a message, which is the distinction the
    acknowledgement gate turns on.

    The three error hooks separate the phases the adapter must treat
    differently: a refused connection and a refused message are delivery
    failures, while a refused QUIT happens after acceptance. ``refuse`` narrows
    ``send_error`` to named recipients so one session can fail for one message
    and succeed for the next.
    """

    def __init__(
        self,
        *,
        connect_error: Exception | None = None,
        send_error: Exception | None = None,
        refuse: set[str] | None = None,
        quit_error: Exception | None = None,
    ) -> None:
        self.connect_error = connect_error
        self.send_error = send_error
        self.refuse = refuse
        self.quit_error = quit_error
        self.attempts: list[tuple[str, int]] = []
        self.delivered: list[str] = []

    def __call__(
        self, host: str, port: int, timeout: float | None = None
    ) -> "_FakeSMTP":
        self.attempts.append((host, port))
        if self.connect_error is not None:
            raise self.connect_error
        return self

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        # smtplib.SMTP.__exit__ issues QUIT and lets a bad reply escape, so
        # this is how a session fails AFTER the message was accepted.
        if self.quit_error is not None:
            raise self.quit_error
        return False

    def ehlo(self) -> None:
        return None

    def starttls(self, context: Any = None) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        return None

    def send_message(self, msg: Any) -> dict[str, Any]:
        to = str(msg["To"])
        if self.send_error is not None and (
            self.refuse is None or to in self.refuse
        ):
            raise self.send_error
        self.delivered.append(to)
        return {}


# --------------------------------------------------------------------------
# Probes and fixtures
# --------------------------------------------------------------------------


def _uid_calls(calls: list[tuple[Any, ...]], command: str) -> list[tuple[Any, ...]]:
    return [c for c in calls if c[0] == "uid" and c[1] == command]


def _stored_uids(calls: list[tuple[Any, ...]]) -> list[Any]:
    return [c[2] for c in _uid_calls(calls, "STORE")]


def _legacy_calls(calls: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [c for c in calls if c[0] in _LEGACY_COMMANDS]


def _assert_store_probe_discriminates() -> None:
    """Control for every "nothing was flagged" assertion in this file.

    A probe that cannot see a flag mutation reports the same empty list
    whether or not one happened, which would make those assertions vacuous.
    """
    probe = [("uid", "STORE", b"7", "+FLAGS", r"(\Seen)")]
    assert _stored_uids(probe) == [b"7"], "the STORE probe must detect a STORE"


def _assert_legacy_probe_discriminates() -> None:
    """Control for the "no sequence-number command" assertions."""
    assert _legacy_calls([("store", b"1", "+FLAGS", r"(\Seen)")]), (
        "the sequence-number probe must detect a sequence-number command"
    )


def _raw(sender: str, message_id: str, body: str = "what is the status?") -> bytes:
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = "me@gmail.com"
    msg["Subject"] = "question"
    msg["Message-ID"] = message_id
    return msg.as_bytes()


class _FakeRuntime:
    pairing_service = None


def _adapter(**over: Any) -> GmailAdapter:
    cfg = GmailAdapterConfig(
        enabled=True, address="me@gmail.com", app_password="pw", **over
    )
    return GmailAdapter(_FakeRuntime(), cfg)


def _install(monkeypatch: pytest.MonkeyPatch, server: _FakeIMAP) -> None:
    """Every IMAP session in the test opens onto the same fake mailbox."""
    monkeypatch.setattr(
        gmail_adapter.imaplib, "IMAP4_SSL", lambda host, port: server
    )


def _install_smtp(monkeypatch: pytest.MonkeyPatch, smtp: _FakeSMTP) -> None:
    """Route the adapter's real `_send_sync` at the SMTP double."""
    monkeypatch.setattr(gmail_adapter.smtplib, "SMTP", smtp)


async def _drive_one_poll(
    adapter: GmailAdapter,
    ready: Callable[[], bool],
    *,
    settle: float = 0.05,
    timeout: float = 5.0,
) -> None:
    """Run one `_poll_loop` batch, then stop the loop.

    `settle` deliberately lets the loop run on past `ready()`. Without it an
    assertion that something did NOT happen could pass merely because the
    loop was stopped before it had the chance.
    """
    adapter._stop.clear()
    task = asyncio.create_task(adapter._poll_loop())
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not ready() and loop.time() < deadline:
            await asyncio.sleep(0.005)
        await asyncio.sleep(settle)
    finally:
        adapter._stop.set()
        await asyncio.wait_for(task, timeout=timeout)


# --------------------------------------------------------------------------
# Nothing is acknowledged before it is processed
# --------------------------------------------------------------------------


async def test_no_flag_is_set_before_the_reply_has_been_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact ordering BF-803 inverts, observed from inside the loop."""
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    adapter = _adapter()
    at_handler: list[list[tuple[Any, ...]]] = []
    at_send: list[list[tuple[Any, ...]]] = []

    async def _handle(message: ChannelMessage) -> str:
        at_handler.append(list(server.calls))
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        at_send.append(list(server.calls))

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert _stored_uids(server.calls) == [b"7"], (
        "control: the mail must end up flagged, or the snapshots below prove "
        "nothing"
    )
    assert _stored_uids(at_handler[0]) == [], "nothing may be flagged before handling"
    assert _stored_uids(at_send[0]) == [], "nothing may be flagged before the send"


async def test_nothing_is_ever_flagged_when_mark_seen_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`mark_seen=False` must mean zero flag mutation on every path."""
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    adapter = _adapter(mark_seen=False)
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(sent))

    assert sent == ["alice@example.com"], "control: the mail really was processed"
    _assert_store_probe_discriminates()
    assert _stored_uids(server.calls) == []
    assert server.seen == set()


def test_the_double_flags_mail_on_a_non_peek_fetch() -> None:
    """Control for every "the fetch flagged nothing" assertion in this file.

    RFC 3501 6.4.5 makes ``RFC822`` and ``BODY[]`` set ``\\Seen`` implicitly;
    only ``BODY.PEEK[]`` does not. If the double could not express that, an
    empty `seen` set would say nothing about which item production asked for
    -- which is precisely how a fix that switched only the ADDRESSING to UID
    passed while still flagging the mail on a real server.
    """
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    assert server.seen == set(), "precondition: nothing is flagged yet"

    server.uid("FETCH", b"7", "(RFC822)")
    assert server.seen == {b"7"}, "RFC822 must flag the mail in the double"

    server.seen.clear()
    server.uid("FETCH", b"7", "(BODY[])")
    assert server.seen == {b"7"}, "BODY[] is functionally equivalent to RFC822"

    server.seen.clear()
    server.uid("FETCH", b"7", "(BODY.PEEK[])")
    assert server.seen == set(), "only BODY.PEEK[] leaves the flag alone"


def test_the_fetch_phase_issues_no_flag_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_fetch_unseen` / `_fetch_one` mutate no flag on any path.

    `server.seen` is the assertion that carries the weight. The double flags
    on any non-PEEK fetch, so an empty set here means production really did
    ask for ``BODY.PEEK[]`` rather than merely skipping the explicit STORE.
    """
    server = _FakeIMAP(
        {
            b"7": _raw("alice@example.com", "<a@x>"),
            b"9": _raw("bob@example.com", "<b@x>"),
        }
    )
    _install(monkeypatch, server)

    inbound = _adapter()._fetch_unseen()

    assert [i.uid for i in inbound] == [b"7", b"9"], "control: the fetch really ran"
    assert [c[3] for c in _uid_calls(server.calls, "FETCH")] == [
        "(BODY.PEEK[])",
        "(BODY.PEEK[])",
    ], "RFC 3501 6.4.5: every other body item sets \\Seen during the fetch"
    _assert_store_probe_discriminates()
    _assert_legacy_probe_discriminates()
    assert _stored_uids(server.calls) == []
    assert _legacy_calls(server.calls) == []
    assert server.seen == set()


def test_a_fetched_message_stays_unseen_until_it_is_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property the whole issue turns on, stated end to end.

    Fetching alone must not consume the mail. Against a non-PEEK item the
    double flags it during the first fetch, the second ``UID SEARCH`` returns
    nothing, and the second list comes back empty.
    """
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    adapter = _adapter()

    first = adapter._fetch_unseen()
    second = adapter._fetch_unseen()

    assert [i.uid for i in first] == [b"7"], "control: the mail was fetched at all"
    assert [i.uid for i in second] == [b"7"], (
        "an unacknowledged message must still be UNSEEN on the next poll"
    )


def test_the_fetch_path_addresses_mail_by_uid_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UID SEARCH then UID FETCH, and no sequence-number command at all."""
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)

    inbound = _adapter()._fetch_unseen()

    assert len(inbound) == 1, "control: the fetch really produced a message"
    assert [c[1] for c in server.calls if c[0] == "uid"] == ["SEARCH", "FETCH"]
    _assert_legacy_probe_discriminates()
    assert _legacy_calls(server.calls) == []


# --------------------------------------------------------------------------
# A failure leaves the mail retrievable
# --------------------------------------------------------------------------


async def test_a_failed_handle_message_leaves_the_mail_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The message the whole issue is about: reasoning failed, so retry it."""
    server = _FakeIMAP(
        {
            b"7": _raw("alice@example.com", "<a@x>"),
            b"9": _raw("bob@example.com", "<b@x>"),
        }
    )
    _install(monkeypatch, server)
    adapter = _adapter()
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        if message.user_id == "alice@example.com":
            raise RuntimeError("the LLM turn blew up")
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    # bob's UID being flagged proves the probe sees acknowledgements, so
    # alice's absence is a real refusal rather than a blind spot.
    assert sent == ["bob@example.com"]
    assert _stored_uids(server.calls) == [b"9"]
    assert [i.uid for i in adapter._fetch_unseen()] == [b"7"], (
        "the unprocessed mail must still be retrievable on the next poll"
    )


async def test_a_failed_send_leaves_the_mail_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reply that was composed but never delivered is not a delivery.

    This pins the LOOP half only: `send_response` is stubbed, so it proves
    `_poll_loop` refuses to acknowledge when the send raises, and nothing
    about whether the real sender ever raises.
    `test_a_refused_smtp_delivery_leaves_the_mail_unread` is the half that
    drives the real `send_response` / `_send_sync`.
    """
    server = _FakeIMAP(
        {
            b"7": _raw("alice@example.com", "<a@x>"),
            b"9": _raw("bob@example.com", "<b@x>"),
        }
    )
    _install(monkeypatch, server)
    adapter = _adapter()
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        if channel_id == "alice@example.com":
            raise RuntimeError("SMTP refused")
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert sent == ["bob@example.com"]
    assert _stored_uids(server.calls) == [b"9"]
    assert [i.uid for i in adapter._fetch_unseen()] == [b"7"], (
        "mail whose reply never left must still be retrievable"
    )


async def test_a_refused_smtp_delivery_leaves_the_mail_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ack gate driven by the REAL sender, not a stubbed one.

    `_send_sync` used to catch SMTPException/OSError and return, so
    `send_response` completed having delivered nothing and `_poll_loop`
    acknowledged. No test above `_send_sync` could tell the difference,
    which is what made the gate look like a gate without being one.

    Bob's message carries the control, and carries it in ORDER rather than on
    a timer: the batch is processed in sequence, so bob can only be
    acknowledged after alice's refusal has already been decided.
    """
    server = _FakeIMAP(
        {
            b"7": _raw("alice@example.com", "<a@x>"),
            b"9": _raw("bob@example.com", "<b@x>"),
        }
    )
    _install(monkeypatch, server)
    smtp = _FakeSMTP(
        send_error=smtplib.SMTPServerDisconnected("connection lost"),
        refuse={"alice@example.com"},
    )
    _install_smtp(monkeypatch, smtp)
    adapter = _adapter()
    handled: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        handled.append(message.user_id)
        return "all systems nominal"

    adapter.handle_message = _handle          # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert handled == ["alice@example.com", "bob@example.com"], (
        "control: both messages were processed"
    )
    assert smtp.delivered == ["bob@example.com"], (
        "control: the real _send_sync reached the server, which took one "
        "message and refused the other"
    )
    _assert_store_probe_discriminates()
    assert _stored_uids(server.calls) == [b"9"], (
        "control: the acknowledgement path is reachable in this harness, and "
        "the refused message did not take it"
    )
    assert server.seen == {b"9"}
    assert [i.uid for i in adapter._fetch_unseen()] == [b"7"], (
        "mail whose reply was refused must still be retrievable"
    )


async def test_the_same_smtp_harness_acknowledges_a_successful_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An accepted reply is acknowledged and never delivered again."""
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    smtp = _FakeSMTP()
    _install_smtp(monkeypatch, smtp)
    adapter = _adapter()

    async def _handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    adapter.handle_message = _handle          # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert smtp.delivered == ["alice@example.com"], "the reply really was sent"
    assert _stored_uids(server.calls) == [b"7"]
    assert server.seen == {b"7"}
    assert adapter._fetch_unseen() == [], "an answered message is not re-delivered"


async def test_a_failure_after_the_server_accepted_the_reply_still_acknowledges(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Log-and-degrade for anything that is NOT a delivery failure.

    `smtplib.SMTP.__exit__` issues QUIT and lets a bad reply escape, so a
    session can fail after `send_message` was accepted. Calling that a
    delivery failure would leave the mail unread and email the sender twice.
    """
    caplog.set_level(logging.WARNING, logger="probos.channels.gmail_adapter")
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    smtp = _FakeSMTP(
        quit_error=smtplib.SMTPResponseException(451, b"try again later")
    )
    _install_smtp(monkeypatch, smtp)
    adapter = _adapter()

    async def _handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    adapter.handle_message = _handle          # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert smtp.delivered == ["alice@example.com"], (
        "control: the server DID accept the message before the session failed"
    )
    assert _stored_uids(server.calls) == [b"7"], (
        "a teardown failure must not un-deliver an accepted reply"
    )
    assert "BF-803" in caplog.text, "the tolerated failure must still be logged"


def test_send_sync_raises_a_delivery_error_when_the_connection_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure has to leave `_send_sync` as an exception to be a gate."""
    smtp = _FakeSMTP(connect_error=OSError("connection refused"))
    _install_smtp(monkeypatch, smtp)
    adapter = _adapter()

    with pytest.raises(GmailDeliveryError):
        adapter._send_sync("alice@example.com", "hi", None, "")

    assert smtp.attempts, "control: the connection really was attempted"
    assert smtp.delivered == []


def test_send_sync_raises_a_delivery_error_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No credentials means nothing was delivered, so nothing may be acked."""
    smtp = _FakeSMTP()
    _install_smtp(monkeypatch, smtp)
    adapter = GmailAdapter(_FakeRuntime(), GmailAdapterConfig(enabled=True))

    with pytest.raises(GmailDeliveryError):
        adapter._send_sync("alice@example.com", "hi", None, "")

    assert smtp.attempts == [], "it must not open a session it cannot log into"


async def test_filtered_mail_is_never_acknowledged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The allow-list drops mail without answering it, so it stays UNSEEN."""
    server = _FakeIMAP(
        {
            b"7": _raw("stranger@example.com", "<s@x>"),
            b"9": _raw("bob@example.com", "<b@x>"),
        }
    )
    _install(monkeypatch, server)
    adapter = _adapter(allowed_senders=["bob@example.com"])
    handled: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        handled.append(message.user_id)
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        return None

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert handled == ["bob@example.com"]
    assert _stored_uids(server.calls) == [b"9"]
    assert server.seen == {b"9"}


# --------------------------------------------------------------------------
# The acknowledgement cannot target a different message
# --------------------------------------------------------------------------


async def test_the_stored_uid_is_the_exact_token_the_search_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The identity has to survive the session boundary byte-for-byte.

    The double keys its mailbox by the exact ``UID SEARCH`` token, so a UID
    that changed type or representation would have failed the FETCH first.
    """
    server = _FakeIMAP({b"31337": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    adapter = _adapter()

    async def _handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        return None

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    fetched = [c[2] for c in _uid_calls(server.calls, "FETCH")]
    stored = _stored_uids(server.calls)
    assert fetched == [b"31337"], "control: the fetch addressed the token"
    assert stored == fetched, "the STORE must address the token that was fetched"
    assert all(type(u) is bytes for u in stored)
    _assert_legacy_probe_discriminates()
    assert _legacy_calls(server.calls) == [], (
        "no acknowledgement may be addressed by a sequence number"
    )


async def test_a_changed_uidvalidity_blocks_the_store_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A renumbered mailbox means the UID may now be somebody else's mail."""
    caplog.set_level(logging.WARNING, logger="probos.channels.gmail_adapter")
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")}, uidvalidity=b"1000")
    _install(monkeypatch, server)
    adapter = _adapter()

    async def _handle(message: ChannelMessage) -> str:
        server.uidvalidity = b"2000"
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        return None

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: len(server.selects) >= 2)

    assert server.selects == ["INBOX", "INBOX"], (
        "control: the acknowledgement session must have re-selected the "
        "mailbox, or refusing to STORE proves nothing"
    )
    _assert_store_probe_discriminates()
    assert _stored_uids(server.calls) == []
    assert "INBOX" in caplog.text
    assert "1000" in caplog.text and "2000" in caplog.text, (
        f"the warning must name both UIDVALIDITY values: {caplog.text}"
    )


# --------------------------------------------------------------------------
# Retry is bounded to the acknowledgement
# --------------------------------------------------------------------------


async def test_an_empty_reply_is_still_acknowledged_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to say is a successful outcome, not a failed delivery."""
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    adapter = _adapter()
    sent: list[str] = []
    handled: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        handled.append(message.user_id)
        return ""

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert handled == ["alice@example.com"], "control: the mail was processed"
    assert _stored_uids(server.calls) == [b"7"], "acknowledged exactly once"
    assert sent == [], "an empty reply must not become an empty email"


async def test_a_failed_store_retries_only_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At-least-once must not mean the Captain is answered twice.

    The mail is still UNSEEN on the next poll, so it comes back. The
    acknowledged-set is what stops it reaching the LLM and the SMTP send a
    second time.
    """
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    server.store_status = "NO"
    _install(monkeypatch, server)
    adapter = _adapter()
    handled: list[str] = []
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        handled.append(message.user_id)
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))
    assert handled == ["alice@example.com"], "precondition: answered once"
    assert len(_stored_uids(server.calls)) == 1

    await _drive_one_poll(
        adapter, lambda: len(_stored_uids(server.calls)) >= 2
    )

    assert len(_stored_uids(server.calls)) == 2, (
        "control: the second poll must have retried the acknowledgement"
    )
    assert handled == ["alice@example.com"], "no second LLM turn"
    assert sent == ["alice@example.com"], "no second email"


async def test_a_settled_acknowledgement_leaves_nothing_outstanding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The set holds OUTSTANDING acknowledgements, not lifetime traffic.

    A Seen message can never be fetched again, so its key suppresses nothing
    and only spends the bound. The refused message is the control: it proves
    the set is populated on this path at all, so the absent key below is a
    deliberate drop rather than an insertion that never happened.
    """
    server = _FakeIMAP(
        {
            b"7": _raw("alice@example.com", "<a@x>"),
            b"9": _raw("bob@example.com", "<b@x>"),
        }
    )
    server.store_refuse = {b"9"}
    _install(monkeypatch, server)
    adapter = _adapter()

    async def _handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        return None

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(
        adapter, lambda: len(_uid_calls(server.calls, "STORE")) >= 2
    )

    assert _stored_uids(server.calls) == [b"7", b"9"], (
        "control: both acknowledgements were attempted"
    )
    assert server.seen == {b"7"}, (
        "control: one flag stuck and the other was refused, so the two "
        "outcomes really are distinguishable here"
    )
    assert list(adapter._acknowledged) == [("1000", b"9")], (
        "only the refused acknowledgement stays outstanding"
    )


async def test_mark_seen_off_keeps_the_entry_that_suppresses_re_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With `mark_seen` off the set is the ONLY re-processing suppression.

    `_acknowledge` returns True there without touching the mailbox, so
    reading that True as "settled" would drop the entry -- and the message,
    still UNSEEN and still returned by every UID SEARCH, would be answered
    again on every poll.
    """
    server = _FakeIMAP({b"7": _raw("alice@example.com", "<a@x>")})
    _install(monkeypatch, server)
    adapter = _adapter(mark_seen=False)
    handled: list[str] = []
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        handled.append(message.user_id)
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(sent))
    assert handled == ["alice@example.com"], "precondition: answered once"

    await _drive_one_poll(
        adapter,
        lambda: len(_uid_calls(server.calls, "FETCH")) >= 2,
        settle=0.2,
    )

    assert len(_uid_calls(server.calls, "FETCH")) >= 2, (
        "control: the mail is still UNSEEN, so the second poll really did "
        "re-fetch it and the counts below were given the chance to grow"
    )
    assert handled == ["alice@example.com"], "no second LLM turn"
    assert sent == ["alice@example.com"], "no second email"
    assert list(adapter._acknowledged) == [("1000", b"7")], (
        "nothing settled the mail, so its entry must stay"
    )


def test_the_acknowledged_set_is_bounded_and_evicts_oldest_first() -> None:
    """An unbounded set would leak for the lifetime of the vessel.

    The bound is a safety valve on acknowledgements that never stick, not a
    working size: settled entries are dropped by `_try_acknowledge`.
    """
    adapter = _adapter()
    message = ChannelMessage(text="hi", channel_id="a@x", user_id="a@x")
    overflow = 5

    for i in range(_ACK_CACHE_MAX + overflow):
        adapter._remember_acknowledged(
            _InboundMail(uid=str(i).encode(), uidvalidity="1000", message=message)
        )

    assert len(adapter._acknowledged) == _ACK_CACHE_MAX
    assert ("1000", b"0") not in adapter._acknowledged, "the oldest must go first"
    assert ("1000", str(overflow).encode()) in adapter._acknowledged, (
        "control: entries just past the evicted window must survive"
    )


async def test_settled_traffic_cannot_evict_an_outstanding_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two properties above, held at the SAME time.

    `test_a_failed_store_retries_only_the_store` proves one stuck message is
    not answered twice, and
    `test_the_acknowledged_set_is_bounded_and_evicts_oldest_first` proves the
    set is bounded. Neither can see the interaction between them: if a settled
    acknowledgement is retained, `_ACK_CACHE_MAX` later messages evict the one
    key still doing work, the stuck mail misses the set on the next poll, and
    the Captain is answered a second time -- by ordinary successful traffic,
    which is why nothing in the failure path looks wrong.

    Every message here is acknowledged successfully except the oldest, so the
    eviction pressure is real traffic rather than a batch of failures.
    """
    stuck_uid = b"1"
    mailbox = {stuck_uid: _raw("stuck@example.com", "<stuck@x>")}
    for i in range(2, _ACK_CACHE_MAX + 2):
        mailbox[str(i).encode()] = _raw(f"bulk{i}@example.com", f"<b{i}@x>")
    total = len(mailbox)
    assert total > _ACK_CACHE_MAX, (
        "precondition: the batch must overflow the bound, or no eviction is "
        "reached and the second poll proves nothing"
    )

    server = _FakeIMAP(mailbox)
    server.store_refuse = {stuck_uid}
    _install(monkeypatch, server)
    adapter = _adapter()
    handled: list[str] = []
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        handled.append(message.user_id)
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(
        adapter,
        lambda: len(_uid_calls(server.calls, "STORE")) >= total,
        timeout=60.0,
    )

    assert len(handled) == total, "precondition: the whole batch was answered"
    assert handled.count("stuck@example.com") == 1
    assert sent.count("stuck@example.com") == 1
    assert stuck_uid not in server.seen, (
        "precondition: the oldest message's STORE really was refused"
    )
    assert len(server.seen) == total - 1, (
        "control: every OTHER acknowledgement did stick, so what follows is "
        "pressure from settled traffic and not from a batch of failures"
    )

    first_poll_stores = len(_uid_calls(server.calls, "STORE"))
    await _drive_one_poll(
        adapter,
        lambda: len(_uid_calls(server.calls, "STORE")) > first_poll_stores,
        timeout=60.0,
    )

    assert _stored_uids(server.calls)[first_poll_stores:] == [stuck_uid], (
        "control: the second poll re-fetched the stuck mail and retried its "
        "flag, so the counts below were given the chance to grow"
    )
    assert handled.count("stuck@example.com") == 1, (
        "settled traffic must not evict an outstanding acknowledgement: the "
        "stuck mail may not reach the LLM a second time"
    )
    assert sent.count("stuck@example.com") == 1, (
        "and its sender may not be emailed a second time"
    )
    assert list(adapter._acknowledged) == [("1000", stuck_uid)], (
        f"a batch of {total} messages with one failing acknowledgement must "
        "leave exactly that one entry outstanding"
    )


async def test_an_acknowledgement_failure_does_not_abort_the_batch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Log-and-degrade, and never conflated with a processing failure.

    The STORE raises an error `_acknowledge` does not expect, which is the
    case that would otherwise escape into `_poll_loop` and cost the rest of
    the batch its BF-802 isolation.
    """
    caplog.set_level(logging.WARNING, logger="probos.channels.gmail_adapter")
    server = _FakeIMAP(
        {
            b"7": _raw("alice@example.com", "<a@x>"),
            b"9": _raw("bob@example.com", "<b@x>"),
        }
    )
    server.store_error = RuntimeError("connection reset by peer")
    _install(monkeypatch, server)
    adapter = _adapter()
    sent: list[str] = []

    async def _handle(message: ChannelMessage) -> str:
        return "all systems nominal"

    async def _send(channel_id: str, response: str, **kwargs: Any) -> None:
        sent.append(channel_id)

    adapter.handle_message = _handle          # type: ignore[method-assign]
    adapter.send_response = _send             # type: ignore[method-assign]

    await _drive_one_poll(
        adapter, lambda: len(_uid_calls(server.calls, "STORE")) >= 2
    )

    assert sent == ["alice@example.com", "bob@example.com"], (
        "a failed acknowledgement must not skip the rest of the batch"
    )
    assert len(_uid_calls(server.calls, "STORE")) == 2, (
        "control: both acknowledgements were attempted and both failed"
    )
    assert "BF-803" in caplog.text


# --------------------------------------------------------------------------
# The shared contract stays where it was
# --------------------------------------------------------------------------


def test_channel_message_is_structurally_unchanged() -> None:
    """The acknowledgement identity travels in `_InboundMail`, not here.

    Every adapter shares `ChannelMessage`; widening it for one of them is
    what the private carrier exists to avoid.
    """
    assert tuple(f.name for f in dataclasses.fields(ChannelMessage)) == (
        "text",
        "channel_id",
        "user_id",
        "user_display_name",
        "reply_to_message_id",
        "paired_did",
    )
