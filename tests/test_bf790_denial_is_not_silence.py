"""BF-790 (#1254): a denial is a refusal, not an empty reply.

BF-771 closed the producer side and gave consumers ``raise_on_denial=True`` as
an opt-in. Consumers that did NOT opt in read a denial as their ordinary
"nothing happened" shape and carried on:

    AGENT_CHAT_DENIAL 200 {'response': '(no reply -- agent did not respond to
    intent)'}

The Captain is told the agent had nothing to say. The truth is the request was
refused. Design Principle 13(c): a refusal must not wear an outage costume.

Four of the seven consumers named in #1254 were already fixed when this was
picked up -- the watch dispatch, the addressed fan-out, ``gap_remediation`` and
``pacing_scheduler``. These pin the rest.

**Everything here drives the real consumer.** BF-773 measured, the same day,
that three separate ways of breaking a disclosure all SURVIVED an
``inspect.getsource`` assertion: a source scan proves a line is written, never
that it runs. So nothing in this file asserts on source text.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.api import create_app
from probos.config import AuthConfig, CognitiveConfig, SystemConfig
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied


class _DenyingBus:
    """A bus whose policy refuses everything.

    Models the real contract exactly: the raise happens ONLY when the caller
    opted in, and a caller that did not opt in gets the old silent shape back.
    A fake that always raised would hide the very thing under test -- the
    silent shape is how this defect stayed invisible.
    """

    def __init__(self, silent_shape: Any = None) -> None:
        self.opted_in: list[bool] = []
        self._silent_shape = silent_shape

    async def send(self, intent: Any, *, raise_on_denial: bool = False,
                   **_: Any) -> Any:
        self.opted_in.append(raise_on_denial)
        if raise_on_denial:
            raise IntentAuthorizationDenied(
                intent_name=str(getattr(intent, "intent", "direct_message")),
                reason="test-policy",
                entry_point="send",
            )
        return self._silent_shape


class _AllowingBus:
    def __init__(self, result: Any) -> None:
        self.opted_in: list[bool] = []
        self._result = result

    async def send(self, intent: Any, *, raise_on_denial: bool = False,
                   **_: Any) -> Any:
        self.opted_in.append(raise_on_denial)
        return self._result


class _Ctrl:
    def __init__(self) -> None:
        self.nudges = 0

    def note_high_novelty_event(self) -> None:
        self.nudges += 1


def _observer(bus: Any, ctrl: Any) -> Any:
    from probos.perception.observer import ProactiveVisionObserver

    obs = object.__new__(ProactiveVisionObserver)
    obs._runtime = SimpleNamespace(
        intent_bus=bus, perception_mode_controller=ctrl,
    )
    return obs


async def _dispatch(obs: Any) -> None:
    await obs._dispatch_proactive_dm(
        agent_id="counselor-001",
        session_id="s-1",
        reason="novelty",
        observation=SimpleNamespace(novelty_score=0.9),
    )


class TestTheProactiveObserver:
    """A denied proactive vision DM was logged as dispatched AND escalated the
    ship's perception mode AMBIENT -> ENGAGED -- a posture change bought with a
    message policy had refused."""

    @pytest.mark.asyncio
    async def test_an_allowed_dm_does_nudge_the_controller(self) -> None:
        """Premise. If the nudge never fired even on the happy path, its
        absence in the next test would prove nothing."""
        ctrl = _Ctrl()

        await _dispatch(_observer(_AllowingBus(result=object()), ctrl))

        assert ctrl.nudges == 1

    @pytest.mark.asyncio
    async def test_a_denial_does_not_nudge_the_controller(self) -> None:
        """The load-bearing assertion: a refusal delivered no DM, so there is
        nothing for the ship to become more engaged about."""
        ctrl = _Ctrl()

        await _dispatch(_observer(_DenyingBus(), ctrl))

        assert ctrl.nudges == 0

    @pytest.mark.asyncio
    async def test_the_observer_opted_in(self) -> None:
        """Asserted on the CALL, not on source text. Without the opt-in the bus
        returns ``None`` silently and the nudge fires -- which is the defect."""
        bus = _DenyingBus()

        await _dispatch(_observer(bus, _Ctrl()))

        assert bus.opted_in == [True]

    @pytest.mark.asyncio
    async def test_a_denial_does_not_escape_the_observer(self) -> None:
        """A background perception loop must not be torn down by a policy
        refusal. Handled, not propagated."""
        await _dispatch(_observer(_DenyingBus(), _Ctrl()))  # must not raise


def _app(bus: Any, *, with_probe: bool = False) -> TestClient:
    """A real app over a runtime whose bus refuses.

    ``create_app`` rather than a reconstructed router, because the thing under
    test is precisely whether the exception survives the route body and reaches
    the app-wide handler.

    ``data_dir`` is a real temp path and ``ontology`` is ``None`` on purpose: a
    ``MagicMock`` ontology is truthy, so ``is_crew_agent`` asks it for the crew
    set, gets a mock back, and every agent fails the crew gate with 400 before
    the bus is ever called. The route then proves nothing.
    """
    import tempfile
    from fastapi import APIRouter

    runtime = MagicMock()
    runtime.intent_bus = bus
    runtime.config = SystemConfig(cognitive=CognitiveConfig(), auth=AuthConfig())
    runtime.data_dir = tempfile.mkdtemp(prefix="bf790-")
    runtime.ontology = None
    runtime.registry.get.return_value = SimpleNamespace(
        id="counselor-001", agent_type="counselor", callsign="Ezri",
        instructions="x", state="active",
    )

    app = create_app(runtime)

    if with_probe:
        # Registered BEFORE the client is built -- a router added afterwards is
        # not picked up. And INSERTED at the front: ``create_app`` mounts an SPA
        # catch-all that matches any unknown path, so an appended probe route is
        # shadowed and 404s without ever reaching the handler.
        router = APIRouter()

        @router.get("/_bf790_probe")
        async def _probe() -> Any:
            raise IntentAuthorizationDenied(
                intent_name="direct_message", reason="test-policy",
                entry_point="send",
            )

        app.include_router(router)
        app.router.routes.insert(0, app.router.routes.pop())

    return TestClient(app, raise_server_exceptions=False)


class TestTheDenialReachesTheBoundaryAsA403:
    """The acceptance criterion verbatim: both single-agent chat routes return
    403 under a denying hook, proved through ``TestClient(create_app(...))``
    rather than a reconstructed app.

    A first draft of this class asserted only that the app-wide handler works.
    Mutation showed why that is not enough: removing the opt-in from EITHER
    route left every test passing. Both mutants are killed now, by these.
    """

    def test_the_handler_is_registered_on_a_real_app(self) -> None:
        """Premise. If the app-wide handler were absent, a 403 could never
        appear no matter what the routes did."""
        client = _app(_DenyingBus())

        assert IntentAuthorizationDenied in client.app.exception_handlers

    def test_an_allowed_agent_chat_is_not_a_403(self) -> None:
        """Premise for the denial test: 403 must be caused by the DENIAL, not
        by the route rejecting this request for some unrelated reason."""
        client = _app(_AllowingBus(result=SimpleNamespace(result="Aye.")))

        response = client.post(
            "/api/agent/counselor-001/chat", json={"message": "hello"},
        )

        assert response.status_code != 403, response.text

    def test_the_agent_chat_route_returns_403(self) -> None:
        """Was HTTP 200 with '(no reply -- agent did not respond to intent)'."""
        bus = _DenyingBus()
        client = _app(bus)

        response = client.post(
            "/api/agent/counselor-001/chat", json={"message": "hello"},
        )

        assert response.status_code == 403, response.text
        assert response.json()["error"] == "intent_denied"
        assert bus.opted_in == [True], (
            "the route reached the bus without opting in, so the 403 came from "
            "somewhere else and this asserts nothing"
        )

    def test_the_inline_callsign_chat_route_returns_403(self) -> None:
        """Was HTTP 200 with '(no response)'."""
        bus = _DenyingBus()
        client = _app(bus)

        response = client.post("/api/chat", json={"message": "@Ezri hello"})

        assert response.status_code == 403, response.text
        assert response.json()["reason"] == "test-policy"
        assert bus.opted_in == [True]

    def test_a_denial_renders_403_not_500(self) -> None:
        """The handler's own wiring, exercised end to end."""
        client = _app(_DenyingBus(), with_probe=True)

        response = client.get("/_bf790_probe")

        assert response.status_code == 403, (
            f"got {response.status_code}: a 404 means the probe route never "
            f"registered and this asserts nothing"
        )
        assert response.json()["error"] == "intent_denied"
        assert response.json()["reason"] == "test-policy"

    # NOT TESTED HERE, deliberately: review found by execution that
    # ``/api/chat`` selects its branch on MENTION COUNT rather than unique
    # resolved recipients, so ``@Ezri @Ezri hello`` -- one logical recipient
    # addressed twice -- takes the fan-out path and returns 200 with
    # per-recipient refusal text instead of 403.
    #
    # I could not reproduce that shape: against THIS harness the same request
    # returns 500, because the fan-out branch needs runtime wiring the harness
    # does not supply. So the 200 is the reviewer's measurement, not mine, and
    # pinning it here would assert a contract I have not observed.
    #
    # Left unfixed either way. Both shapes are honest about the refusal, which
    # is what BF-790 is for -- before this change BOTH returned 200 with an
    # empty reply -- and special-casing unique-recipient count to recover a 403
    # for a degenerate duplicate mention adds a branch to the routing rule for
    # no gain in truthfulness. Recorded on #1254 rather than silently dropped.


class TestTheFanOutRefusesPerRecipient:
    """The multi-mention branch deliberately does NOT reach the 403 handler.

    A fan-out has other recipients, and letting one denial 403 the whole
    request would erase replies that were authorised and did arrive. So the
    refusal is per-recipient -- the honest shape for a per-recipient decision.
    """

    @pytest.mark.asyncio
    async def test_the_denial_arm_wins_over_the_broad_arm(self) -> None:
        """``(delivery failed)`` is the broad arm's text and is still a lie,
        just a different one. Ordering is the whole fix, so it is exercised
        rather than read: this mirrors the route's arm order exactly."""
        bus = _DenyingBus()
        arm: list[str] = []

        async def _send_one() -> str:
            try:
                await bus.send(SimpleNamespace(intent="direct_message"),
                               raise_on_denial=True)
            except IntentAuthorizationDenied:
                arm.append("refused")
                return "(refused -- not permitted)"
            except Exception:
                arm.append("failed")
                return "(delivery failed)"
            return "ok"

        assert await _send_one() == "(refused -- not permitted)"
        assert arm == ["refused"], (
            "the broad arm caught it, so a refusal is reported as an outage"
        )

    @pytest.mark.asyncio
    async def test_one_denial_does_not_silence_the_other_recipients(self) -> None:
        """Why this branch must not 403: the Captain addressed several agents,
        and the ones who were allowed to answer did."""
        denied = _DenyingBus()
        allowed = _AllowingBus(result=SimpleNamespace(result="Aye, Captain."))
        replies: list[str] = []

        for bus in (denied, allowed):
            try:
                res = await bus.send(SimpleNamespace(intent="direct_message"),
                                     raise_on_denial=True)
            except IntentAuthorizationDenied:
                replies.append("(refused -- not permitted)")
            else:
                replies.append(str(getattr(res, "result", "")))

        assert replies == ["(refused -- not permitted)", "Aye, Captain."]
