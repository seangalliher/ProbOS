"""BF-804 (#1350): an unpaired sender who was never told how to pair must
not be acknowledged.

``ChannelAdapter._check_pairing`` collapsed three outcomes into one bool.
``False`` meant BOTH "unknown sender, instructions delivered, drop it" and
"unknown sender, instructions never left, drop it", and ``handle_message``
mapped both to ``""``. ``GmailAdapter._poll_loop`` reads a call that did not
raise as success, so its ``else:`` arm flagged the mail ``\\Seen``: the sender
got no instructions, no answer, and no retry, and the BF-803 at-least-once
guarantee was defeated from inside the shared base class.

THE TRAP this file exists to avoid: a test asserting ``_check_pairing(...) is
False`` PASSES against the unfixed code, because ``False`` is already the
correct return for an unpaired sender. The bool was never wrong -- it was
merely insufficient. Only the ACKNOWLEDGEMENT discriminates, so every
regression below drives the real ``_poll_loop`` against the BF-803 IMAP double
and reads ``_stored_uids(server.calls)``.

``handle_message`` is never stubbed here; the chain ``_check_pairing`` ->
``handle_message`` -> the acknowledge decision is traversed for real. Only
``send_response`` is doubled, because the SMTP transport is what has to fail.

Every "the UID was NOT flagged" assertion is paired with a second message in
the same batch whose UID IS flagged. Without that control the probe cannot
tell "refused to acknowledge" from "saw no acknowledgements at all", and a
half-chain test proving only the producer is this repository's most common
defect.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from probos.channels.base import (
    _PAIRING_NOTICE_FAILED,
    ChannelMessage,
    PairingNotificationError,
)
from probos.channels.gmail_adapter import GmailAdapter
from probos.channels.gmail_config import GmailAdapterConfig
from tests.test_bf803_gmail_ack import (
    _FakeIMAP,
    _assert_store_probe_discriminates,
    _drive_one_poll,
    _install,
    _raw,
    _stored_uids,
)

_ALICE = "alice@example.com"
_BOB = "bob@example.com"
_CAROL = "carol@example.com"


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class _FakePairingService:
    """The AD-802 surface `_check_pairing` actually touches.

    `paired` is the whole of `resolve_did`: anyone absent from it is an
    unknown sender and takes the mint-and-notify path, which is the only path
    BF-804 changes. `request_failure` / `fail_requests_for` make the mint fail
    for named senders so one message can fail while the rest of the batch is
    handled normally -- the traffic that must keep being acknowledged.
    """

    def __init__(
        self,
        *,
        paired: dict[str, str] | None = None,
        request_failure: Exception | None = None,
        fail_requests_for: set[str] | None = None,
    ) -> None:
        self.paired: dict[str, str] = paired or {}
        self.request_failure = request_failure
        self.fail_requests_for = fail_requests_for
        self.requested: list[tuple[str, str]] = []

    def resolve_did(self, channel: str, raw_id: str) -> str | None:
        return self.paired.get(raw_id)

    async def request_pairing(self, *, channel: str, raw_id: str) -> str:
        self.requested.append((channel, raw_id))
        if self.request_failure is not None and (
            self.fail_requests_for is None or raw_id in self.fail_requests_for
        ):
            raise self.request_failure
        return "ABC123"


class _Notifier:
    """Stands in for `GmailAdapter.send_response`.

    `sent` grows only when the transport ACCEPTED the message, which is the
    distinction the acknowledgement gate turns on. `attempts` grows either
    way, so a test can wait on a refused send. The recorded ``kwargs`` are how
    a pairing notice (two positional args) is told apart from an answer to the
    sender (which carries ``reply_to_message_id``).
    """

    def __init__(self, refuse: set[str] | None = None) -> None:
        self.refuse: set[str] = refuse or set()
        self.attempts: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str, dict[str, Any]]] = []

    async def __call__(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        self.attempts.append((channel_id, response))
        if channel_id in self.refuse:
            raise RuntimeError("SMTP refused the pairing instructions")
        self.sent.append((channel_id, response, dict(kwargs)))

    def recipients(self) -> list[str]:
        return [channel_id for channel_id, _, _ in self.sent]

    def answers(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Only the sends that answered the sender, not the pairing notices."""
        return [s for s in self.sent if "reply_to_message_id" in s[2]]


class _FakeRuntime:
    """Enough runtime for the paired branch to run for real.

    `process_natural_language` is the only member `handle_message` reaches for
    text with no slash command and no @callsign, so the paired control below
    exercises the true base-class body rather than a stub of it.
    """

    def __init__(self, pairing_service: _FakePairingService) -> None:
        self.pairing_service = pairing_service
        self.processed: list[str] = []

    async def process_natural_language(
        self, text: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.processed.append(text)
        return {"response": "all systems nominal"}


def _adapter(
    pairing_service: _FakePairingService, **over: Any
) -> tuple[GmailAdapter, _FakeRuntime]:
    cfg = GmailAdapterConfig(
        enabled=True, address="me@gmail.com", app_password="pw", **over
    )
    runtime = _FakeRuntime(pairing_service)
    return GmailAdapter(runtime, cfg), runtime


# --------------------------------------------------------------------------
# The regression: all three outcomes, observed at the acknowledgement
# --------------------------------------------------------------------------


async def test_undelivered_pairing_instructions_leave_the_mail_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deliverable. One batch, three senders, three distinct outcomes.

    * carol is PAIRED -> processed, answered, UID flagged.
    * bob is unpaired and his instructions were DELIVERED -> no answer, UID
      flagged. This is the outcome that must NOT start retrying forever.
    * alice is unpaired and her instructions were REFUSED -> UID NOT flagged
      and re-fetched on the next poll.

    bob's and carol's flags are the discrimination control: they prove the
    probe can see an acknowledgement, so alice's absence is a refusal rather
    than a blind spot.
    """
    server = _FakeIMAP(
        {
            b"7": _raw(_ALICE, "<a@x>"),
            b"9": _raw(_BOB, "<b@x>"),
            b"11": _raw(_CAROL, "<c@x>"),
        }
    )
    _install(monkeypatch, server)
    pairing = _FakePairingService(paired={_CAROL: "did:probos:carol"})
    adapter, runtime = _adapter(pairing)
    notifier = _Notifier(refuse={_ALICE})
    adapter.send_response = notifier          # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: len(_stored_uids(server.calls)) >= 2)

    # -- controls: the batch really ran, and the probe really discriminates --
    assert pairing.requested == [("gmail", _ALICE), ("gmail", _BOB)], (
        "control: only the two unknown senders reach the mint-and-notify path"
    )
    assert notifier.recipients() == [_BOB, _CAROL], (
        "control: bob's pairing notice and carol's answer both left"
    )
    assert len(runtime.processed) == 1 and "status" in runtime.processed[0], (
        "control: the paired sender was processed past the gate"
    )
    _assert_store_probe_discriminates()

    # -- outcome 3: the sender who was never told how to pair --
    assert _stored_uids(server.calls) == [b"9", b"11"], (
        "a sender who could not be told how to pair must NOT be acknowledged"
    )
    assert [i.uid for i in adapter._fetch_unseen()] == [b"7"], (
        "the unacknowledged mail must still be retrievable on the next poll"
    )


async def test_a_failed_request_pairing_leaves_the_mail_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other non-delivery path: no code was ever minted.

    Same acknowledgement probe, same control. `send_response` refuses nobody
    here, so the only thing that fails is the mint itself.
    """
    server = _FakeIMAP(
        {
            b"7": _raw(_ALICE, "<a@x>"),
            b"9": _raw(_BOB, "<b@x>"),
        }
    )
    _install(monkeypatch, server)
    pairing = _FakePairingService(
        request_failure=RuntimeError("the pairing store is unreachable"),
        fail_requests_for={_ALICE},
    )
    adapter, _ = _adapter(pairing)
    notifier = _Notifier()
    adapter.send_response = notifier          # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert pairing.requested == [("gmail", _ALICE), ("gmail", _BOB)], (
        "control: both senders reached the mint"
    )
    assert notifier.recipients() == [_BOB], (
        "control: only the sender whose code was minted could be notified"
    )
    _assert_store_probe_discriminates()
    assert _stored_uids(server.calls) == [b"9"], (
        "a sender whose pairing code was never minted must NOT be acknowledged"
    )
    assert [i.uid for i in adapter._fetch_unseen()] == [b"7"], (
        "the unacknowledged mail must still be retrievable on the next poll"
    )


async def test_the_retry_re_runs_the_pairing_gate_and_never_answers_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BF-803's at-most-once property survives the new retry.

    The mail left unread by BF-804 must come back through the FULL gate on the
    next poll -- a second notification attempt, not a second answer -- and be
    acknowledged once the transport recovers. Without the second poll the fix
    would be indistinguishable from "unpaired senders now retry forever".
    """
    server = _FakeIMAP({b"7": _raw(_ALICE, "<a@x>")})
    _install(monkeypatch, server)
    pairing = _FakePairingService()
    adapter, runtime = _adapter(pairing)
    notifier = _Notifier(refuse={_ALICE})
    adapter.send_response = notifier          # type: ignore[method-assign]

    await _drive_one_poll(adapter, lambda: bool(notifier.attempts))

    assert notifier.attempts, "control: the first notification was attempted"
    assert _stored_uids(server.calls) == [], "the refused notice must not settle"

    notifier.refuse.clear()

    await _drive_one_poll(adapter, lambda: bool(_stored_uids(server.calls)))

    assert pairing.requested == [("gmail", _ALICE), ("gmail", _ALICE)], (
        "the retry must re-run the pairing gate, not resume mid-way"
    )
    assert notifier.recipients() == [_ALICE], (
        "exactly one notification was ever accepted by the transport"
    )
    assert notifier.answers() == [], (
        "an unpaired sender is never answered, on either poll"
    )
    assert runtime.processed == [], (
        "the gate held on both polls: no LLM turn ran for an unpaired sender"
    )
    assert _stored_uids(server.calls) == [b"7"], (
        "once the sender has been told how to pair, the mail is acknowledged"
    )
    assert [i.uid for i in adapter._fetch_unseen()] == [], (
        "and it is not re-delivered a third time"
    )


# --------------------------------------------------------------------------
# The raise itself
# --------------------------------------------------------------------------


async def test_a_refused_pairing_notice_raises_rather_than_returning_false() -> None:
    """Supporting evidence only -- `is False` alone proves nothing here."""
    pairing = _FakePairingService()
    adapter, _ = _adapter(pairing)
    adapter.send_response = _Notifier(refuse={_ALICE})   # type: ignore[method-assign]
    message = ChannelMessage(text="hi", channel_id=_ALICE, user_id=_ALICE)

    with pytest.raises(PairingNotificationError):
        await adapter._check_pairing(message)


async def test_a_paired_sender_is_unaffected_and_gets_its_did() -> None:
    """Outcome 1, stated at the gate: True, and `paired_did` is attached."""
    pairing = _FakePairingService(paired={_CAROL: "did:probos:carol"})
    adapter, _ = _adapter(pairing)
    adapter.send_response = _Notifier()       # type: ignore[method-assign]
    message = ChannelMessage(text="hi", channel_id=_CAROL, user_id=_CAROL)

    assert await adapter._check_pairing(message) is True
    assert message.paired_did == "did:probos:carol"
    assert pairing.requested == [], "a paired sender never touches the mint"


@pytest.mark.parametrize(
    "make_pairing, make_notifier",
    [
        pytest.param(
            lambda: _FakePairingService(),
            lambda: _Notifier(refuse={_ALICE}),
            id="send_response-refused",
        ),
        pytest.param(
            lambda: _FakePairingService(
                request_failure=RuntimeError(
                    "the pairing store is unreachable at 10.0.0.7"
                )
            ),
            lambda: _Notifier(),
            id="request_pairing-failed",
        ),
    ],
)
async def test_the_error_text_names_the_channel_and_nothing_else(
    make_pairing: Callable[[], _FakePairingService],
    make_notifier: Callable[[], _Notifier],
) -> None:
    """`routers/teams_webhook.py:47` echoes `str(exc)` into an HTTP 200 body.

    The message therefore carries the channel name and a fixed phrase only.
    The sender id, the raw address and the underlying transport text stay on
    the `__cause__` and in the log line, where no unauthenticated party reads
    them.
    """
    adapter, _ = _adapter(make_pairing())
    adapter.send_response = make_notifier()   # type: ignore[method-assign]
    message = ChannelMessage(text="hi", channel_id=_ALICE, user_id=_ALICE)

    with pytest.raises(PairingNotificationError) as caught:
        await adapter._check_pairing(message)

    text = str(caught.value)
    assert text == _PAIRING_NOTICE_FAILED.format(channel="gmail")
    assert "gmail" in text, "control: the probe can see a channel name at all"
    assert _ALICE not in text and "alice" not in text.lower()
    cause = caught.value.__cause__
    assert cause is not None, "the transport failure is chained for the log"
    assert str(cause) not in text
    assert "SMTP" not in text and "10.0.0.7" not in text


# --- BF-804 round-1 review: Slack's operator-wired webhook must not start raising ---


@pytest.mark.asyncio
async def test_slack_webhook_entry_point_still_returns_empty_on_undelivered_notice():
    """`SlackAdapter.receive` is an operator-wired HTTP entry point.

    Before BF-804 it returned "" for an unpaired sender. Letting
    PairingNotificationError escape would surface as a 500 and invite an
    Events API retry, and Slack has no deferred acknowledgement to withhold,
    so the pre-BF-804 contract is kept deliberately rather than by accident.
    """
    import httpx

    from probos.channels.slack_adapter import SlackAdapter
    from probos.config import SlackConfig

    class _Runtime:
        def __init__(self, pairing_service: Any) -> None:
            self.pairing_service = pairing_service

        def emit_event(self, *_a: Any, **_kw: Any) -> None:
            return None

    class _RefusingPairing:
        def resolve_did(self, _channel: str, _raw_id: str) -> str | None:
            return None

        async def request_pairing(self, **_kw: Any) -> str:
            raise RuntimeError("the pairing store is unreachable at 10.0.0.7")

    cfg = SlackConfig(enabled=True, bot_token="xoxb-test")
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": True}))

    # Closed explicitly: an un-awaited AsyncClient leaks a socket, and this
    # suite has already produced one gate failure from Windows socket
    # exhaustion under sixteen xdist workers.
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = SlackAdapter(_Runtime(_RefusingPairing()), cfg, client=client)

        result = await adapter.receive(text="hi", channel_id="C1", user_id="U42")

        assert result == "", "the webhook contract predates BF-804 and must hold"

        # Control: the SAME entry point still answers a paired sender end to
        # end. Asserting on `_check_pairing` here would be no control at all --
        # an implementation whose `receive` unconditionally returned "" would
        # satisfy both halves. This calls `receive` and requires a real reply.
        class _Paired:
            def resolve_did(self, _channel: str, _raw_id: str) -> str:
                return "did:probos:alice"

        class _PairedRuntime(_Runtime):
            async def process_natural_language(self, *_a: Any, **_kw: Any) -> Any:
                return {"response": "acknowledged, Captain"}

        paired = SlackAdapter(_PairedRuntime(_Paired()), cfg, client=client)
        answered = await paired.receive(text="hi", channel_id="C1", user_id="U42")
        assert answered == "acknowledged, Captain", (
            "control: receive() must be capable of returning a non-empty "
            "reply, otherwise the assertion above proves nothing"
        )
