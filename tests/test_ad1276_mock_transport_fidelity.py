"""AD-1276 Section 0: MockNATSBus must be able to witness the transport.

Three fidelity gaps made the mock unable to prove anything about a
consumer-side authorization check: a delivered message's disposition was
unobservable, ``js_publish`` reported a route production never produces, and
a reply message could not carry the request's headers, so the reply budget
never saw a real echo cost.
"""

from __future__ import annotations

import pytest

from probos.mesh.nats_bus import MockNATSBus, NATSMessage


@pytest.fixture
async def bus():
    mock = MockNATSBus()
    await mock.start()
    yield mock
    await mock.stop()


class TestJsPublishReportsARealRoute:
    async def test_js_publish_reports_the_route_the_real_bus_reports(self, bus):
        outcome = await bus.js_publish("intent.dispatch.agent-1", {"intent": "x"})

        assert outcome == "jetstream", (
            "the mock reported %r; the real bus reports 'jetstream', "
            "'core_nats' or 'dropped', and dispatch_async branches on it"
            % (outcome,)
        )

    async def test_js_publish_outcome_is_a_string_not_none(self, bus):
        outcome = await bus.js_publish("intent.dispatch.agent-1", {"intent": "x"})

        assert isinstance(outcome, str)


class TestADeliveredMessageCanReportItsDisposition:
    @staticmethod
    async def _deliver(bus, disposition):
        seen: list[NATSMessage] = []

        async def _cb(msg):
            seen.append(msg)
            await getattr(msg, disposition)()

        await bus.subscribe("intent.dispatch.agent-1", _cb)
        await bus.js_publish("intent.dispatch.agent-1", {"intent": "x"})
        assert seen, "the subscriber never ran; nothing below discriminates"
        return seen[0]

    async def test_a_delivered_jetstream_message_can_be_acked_and_the_ack_is_visible(
        self, bus
    ):
        await self._deliver(bus, "ack")

        assert len(bus.acks) == 1
        assert bus.acks[0].endswith("intent.dispatch.agent-1")

    async def test_a_delivered_jetstream_message_can_be_termed_and_the_term_is_visible(
        self, bus
    ):
        await self._deliver(bus, "term")

        assert len(bus.terms) == 1
        assert bus.terms[0].endswith("intent.dispatch.agent-1")

    async def test_ack_and_term_are_distinguishable_not_merely_both_recorded(
        self, bus
    ):
        await self._deliver(bus, "term")

        assert bus.terms and not bus.acks, (
            "a term must not also register as an ack, or the mutant "
            "term() -> ack() is INERT rather than killed"
        )

    async def test_a_nak_records_its_delay(self, bus):
        seen = []

        async def _cb(msg):
            seen.append(msg)
            await msg.nak(delay=60)

        await bus.subscribe("intent.dispatch.agent-1", _cb)
        await bus.js_publish("intent.dispatch.agent-1", {"intent": "x"})

        assert seen, "the subscriber never ran"
        assert bus.naks == [(bus.naks[0][0], 60)]
        assert not bus.acks and not bus.terms


class TestRequestReplyCarriesTheRequestsHeaders:
    async def test_a_request_reply_message_carries_the_requests_headers_for_budgeting(
        self, bus
    ):
        budgets: list[int] = []

        async def _cb(msg):
            budgets.append(msg.reply_body_budget(1_000_000))

        await bus.subscribe("intent.agent-1", _cb)
        await bus.request(
            "intent.agent-1", {"intent": "x"}, headers={"X-Pad": "p" * 4000}
        )

        assert budgets, "the subscriber never ran"
        assert budgets[0] < 1_000_000 - 4000, (
            "the echoed headers cost nothing (budget=%d); a budgeted denial "
            "cannot be exercised against a real echo cost" % budgets[0]
        )

    async def test_a_request_with_no_headers_leaves_the_budget_whole(self, bus):
        budgets: list[int] = []

        async def _cb(msg):
            budgets.append(msg.reply_body_budget(1_000_000))

        await bus.subscribe("intent.agent-1", _cb)
        await bus.request("intent.agent-1", {"intent": "x"})

        assert budgets == [1_000_000], (
            "the no-header case must stay free, or every existing reply site "
            "silently loses budget"
        )


class TestExistingDeliveryIsUnchanged:
    async def test_publish_still_delivers_to_every_matching_subscriber(self, bus):
        first: list[str] = []
        second: list[str] = []

        await bus.subscribe("intent.dispatch.*", lambda m: _record(first, m))
        await bus.subscribe("intent.dispatch.agent-1", lambda m: _record(second, m))
        await bus.publish("intent.dispatch.agent-1", {"intent": "x"})

        assert len(first) == 1 and len(second) == 1, (
            "19 test files rely on this fan-out; the AD-1276 _msg stub must "
            "not change who receives a message"
        )

    async def test_publish_still_records_the_payload_for_inspection(self, bus):
        await bus.publish("intent.dispatch.agent-1", {"intent": "x"})

        assert bus.published[-1][1] == {"intent": "x"}

    async def test_request_still_returns_the_subscribers_reply(self, bus):
        async def _cb(msg):
            await msg.respond({"ok": True})

        await bus.subscribe("intent.agent-1", _cb)
        reply = await bus.request("intent.agent-1", {"intent": "x"})

        assert reply is not None and reply.data == {"ok": True}

    async def test_request_with_no_subscriber_still_returns_none(self, bus):
        assert await bus.request("intent.nobody", {"intent": "x"}) is None


async def _record(sink: list[str], msg: NATSMessage) -> None:
    sink.append(msg.subject)
