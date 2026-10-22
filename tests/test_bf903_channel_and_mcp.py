"""BF-903 (#1581) M3: a paired channel sender and an inbound MCP call are scoped like any visiting officer.

Real objects: a real ``AgentIdentityRegistry`` in ``tmp_path``, the real ``VisitingOfficerRegistry`` with an
injected clock, the real ``PairingRegistry`` and ``PairingService``, a real ``CallsignRegistry`` loaded from a
profile in ``tmp_path``, a ``ChannelAdapter`` subclass whose only code is the platform I/O, the real
``SlackAdapter``, and the real ``FederationMCPServer`` driven through ``build_mcp_app`` over an in-process ASGI
transport with a real ``IntentBus`` and ``MCPAppRegistry``. The trust network behind ``FederationPeerRegistry`` is
BF-875's double; it is not under test. Nothing reads the live data directory.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from sqlite3 import OperationalError as _OperationalError  # the standard library's, not a ProbOS name
from typing import Any

import pytest
from httpx import ASGITransport as _ASGITransport  # httpx's names, not ProbOS's
from httpx import AsyncClient as _AsyncClient
from httpx import MockTransport as _MockTransport
from httpx import Response as _Response

from probos.channels.base import (
    _PAIRED_DM_REFUSED,
    _PAIRED_NO_COMMANDS,
    _PAIRED_NO_CONVERSATION,
    _PAIRING_LOOKUP_FAILED,
    ChannelAdapter,
    ChannelConfig,
    ChannelMessage,
    PairingLookupError,
    PairingNotificationError,
)
from probos.channels.slack_adapter import SlackAdapter
from probos.config import FederationMCPServerConfig, SlackConfig
from probos.crew_profile import CallsignRegistry
from probos.events import EventType
from probos.federation.mcp_server import (
    _VISITOR_REFUSALS,
    MAX_ARGUMENT_VALUES,
    REFUSED_ARGUMENTS_UNWALKED,
    REFUSED_VISITOR_UNBOUND,
    FederationMCPServer,
    build_mcp_app,
    visitor_argument_refusal,
)
from probos.federation.peer import FederationPeerRegistry
from probos.identity import AgentIdentityRegistry
from probos.mcp_apps.registry import MCPAppRegistry
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.security.pairing import PairingRegistry, PairingService
from probos.types import IntentDescriptor, IntentMessage, IntentResult
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_REGISTRY_OFF,
)
from tests.test_bf903_visitor_scope import (
    CREW_SLOT,
    INSTANCE_ID,
    VESSEL_NAME,
    Events,
    _Clock,
    _crew,
    _officers,
    _refusals,
)

CHANNEL = "bf903chan"
SESSION_TTL = 60.0
DM_TEXT = "@Counselor are you free?"
STATUS_TEXT = "what is the ship's status?"
ECHO_INTENT = "bf903_echo"
MOVE_TOOL = "bf903-move"
TOKEN = "bf903" * 8  # synthetic: 40 visible characters
CSP = "default-src 'self'"


@pytest.fixture
async def identities(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield registry
    finally:
        await registry.stop()


# ---------------------------------------------------------------- channels


class _Runtime:
    """The runtime members ``handle_message`` and ``SlackAdapter.receive`` read, holding the real registries."""

    def __init__(
        self, pairing_service: Any, visiting_officers: Any, callsign_registry: CallsignRegistry, processed: list[str],
        intent_bus: IntentBus,
    ) -> None:
        self.pairing_service = pairing_service
        self.visiting_officers = visiting_officers
        self.callsign_registry = callsign_registry
        self.processed = processed
        self.intent_bus = intent_bus  # A4: the real bus, so a resolved DM reaches a live receiver

    async def process_natural_language(self, text: str, **kwargs: Any) -> dict[str, Any]:
        self.processed.append(text)
        return {"response": "all systems nominal"}

    def emit_event(self, event: Any, data: Any = None) -> None:
        return None


class _Adapter(ChannelAdapter):
    """A pairing adapter whose only code is the platform I/O; ``handle_message`` is the base class's."""

    channel_name = CHANNEL

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, ChannelConfig(enabled=True))
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_response(self, channel_id: str, response: str, **kwargs: Any) -> None:
        self.sent.append((channel_id, response))


class _OptedOut(_Adapter):
    """An adapter with no ``channel_name``: the supported opt-out of pairing (``WebhookAdapter``)."""

    channel_name = ""


class _OnDuty:
    """The two members ``CallsignRegistry.resolve`` reads from a live agent (A4)."""

    def __init__(self, agent_id: str) -> None:
        self.id = agent_id
        self.is_alive = True


class _Roster:
    """The agent registry's one method ``resolve`` calls: the Counselor's pool holds one live agent (A4)."""

    def get_by_pool(self, agent_type: str) -> list[_OnDuty]:
        return [_OnDuty(CREW_SLOT)] if agent_type == "counselor" else []


class _Rig:
    """The real registries and pairing service behind one ``_Adapter``; the Counselor is on duty and receives its
    direct messages over a real ``IntentBus`` (A4)."""

    def __init__(self, identities: AgentIdentityRegistry, tmp_path: Path) -> None:
        self.clock = _Clock()
        self.events: Events = []
        self.processed: list[str] = []
        self.delivered: list[IntentMessage] = []
        self.officers = _officers(identities, self.clock, self.events)
        self.store = PairingRegistry(tmp_path / "pairings.db")
        self.pairing = PairingService(self.store, self.officers)
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        (profiles / "counselor.yaml").write_text("callsign: Counselor\ndepartment: medical\n", encoding="utf-8")
        callsigns = CallsignRegistry()
        callsigns.load_from_profiles(str(profiles))
        callsigns.bind_registry(_Roster())
        bus = IntentBus(SignalManager())
        bus.subscribe(CREW_SLOT, self._receive, intent_names=["direct_message"])
        self.runtime = _Runtime(self.pairing, self.officers, callsigns, self.processed, bus)
        self.adapter = _Adapter(self.runtime)

    async def _receive(self, intent: IntentMessage) -> IntentResult:
        """The Counselor's direct-message handler: records what reached the crew member (A4)."""
        self.delivered.append(intent)
        return IntentResult(intent_id=intent.id, agent_id=CREW_SLOT, success=True, result="aye", confidence=0.9)

    async def pair(self, user_id: str, capabilities: list[str] | None = None) -> str:
        """Pair ``user_id`` as the Captain would: a pending code, then approval."""
        code = await self.pairing.request_pairing(CHANNEL, user_id)
        paired = await self.pairing.approve_pairing(
            CHANNEL, code, capabilities_override=capabilities, session_ttl_seconds=SESSION_TTL,
        )
        return paired.did


@pytest.fixture
async def rig(identities: AgentIdentityRegistry, tmp_path: Path) -> _Rig:
    return _Rig(identities, tmp_path)


def _message(user_id: str, text: str) -> ChannelMessage:
    return ChannelMessage(text=text, channel_id="room-1", user_id=user_id)


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        ("/status", _PAIRED_NO_COMMANDS),
        (STATUS_TEXT, _PAIRED_NO_CONVERSATION),
        ("@Nobody are you there?", _PAIRED_NO_CONVERSATION),
    ],
    ids=["slash-command", "natural-language", "unknown-callsign"],
)
async def test_a_paired_sender_is_refused_commands_and_conversation(rig: _Rig, text: str, reply: str) -> None:
    """P1: a paired sender is a visiting officer; no declared capability grants a slash command or a turn with the
    ship's computer, so each gets a reply naming the reason, and nothing runs."""
    did = await rig.pair("u-1")
    message = _message("u-1", text)
    assert await rig.adapter.handle_message(message) == reply
    assert message.paired_did == did
    assert rig.processed == []
    assert _refusals(rig.events) == []


async def test_a_paired_sender_holding_dm_send_reaches_the_crew_member(rig: _Rig) -> None:
    """P2: AD-802's default capabilities hold dm.send, which is enough for an @callsign direct message. The
    Counselor is on duty (A4), so the DM is delivered once, over the real bus, to its live agent, and its answer is
    the reply."""
    did = await rig.pair("u-2")
    session = rig.officers.get(did)
    assert session is not None and CAP_DM_SEND in session.capabilities
    assert await rig.adapter.handle_message(_message("u-2", DM_TEXT)) == "Counselor: aye"
    assert [(i.intent, i.target_agent_id) for i in rig.delivered] == [("direct_message", CREW_SLOT)]
    assert rig.processed == []
    assert _refusals(rig.events) == []


@pytest.mark.parametrize("lapse", ["capability-missing", "session-expired", "registry-off"])
async def test_a_paired_dm_without_a_live_dm_send_is_refused(rig: _Rig, lapse: str) -> None:
    """P3: the DM is checked against the sender's session at use: a session without dm.send, one that has expired
    (before any sweep) and a registry that is not attached each refuse it with the code; nothing reaches the crew."""
    expected = {
        "capability-missing": REFUSED_CAPABILITY, "session-expired": REFUSED_EXPIRED,
        "registry-off": REFUSED_REGISTRY_OFF,
    }
    await rig.pair("u-3", [CAP_DM_RECEIVE] if lapse == "capability-missing" else None)
    if lapse == "session-expired":
        rig.clock.now += SESSION_TTL
    elif lapse == "registry-off":
        rig.runtime.visiting_officers = None
    assert rig.runtime.callsign_registry.resolve("Counselor")["agent_id"] == CREW_SLOT  # A4: deliverable if allowed
    reply = await rig.adapter.handle_message(_message("u-3", DM_TEXT))
    assert reply == _PAIRED_DM_REFUSED.format(reason=expected[lapse])
    assert rig.delivered == []  # A4: nothing reached the crew member, before the check or after it
    assert rig.processed == []
    surfaces = [p["surface"] for p in _refusals(rig.events)]
    assert surfaces == ([] if lapse == "registry-off" else [f"channel.{CHANNEL}.dm"])


async def test_an_unreadable_pairing_store_refuses_the_message_and_its_callers_still_catch_it(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P4: when the pairing store cannot be read the message is refused, not admitted: PairingLookupError is a
    PairingNotificationError naming only the channel, with the cause chained, so the callers that catch the parent
    (here Slack's webhook, which returns "") still catch it. Nothing is processed and nothing is sent."""
    def _unreadable(_channel: str, _raw_id: str) -> None:
        raise _OperationalError("database is locked")

    monkeypatch.setattr(rig.store, "lookup_by_raw_id", _unreadable)
    message = _message("u-4", STATUS_TEXT)
    with pytest.raises(PairingLookupError) as refused:
        await rig.adapter.handle_message(message)
    assert isinstance(refused.value, PairingNotificationError)
    assert str(refused.value) == _PAIRING_LOOKUP_FAILED.format(channel=CHANNEL)
    assert isinstance(refused.value.__cause__, _OperationalError)
    assert message.paired_did is None
    assert rig.adapter.sent == []
    async with _AsyncClient(transport=_MockTransport(lambda _r: _Response(200, json={"ok": True}))) as client:
        slack = SlackAdapter(rig.runtime, SlackConfig(enabled=True, bot_token="xoxb-test"), client=client)
        assert await slack.receive(text="hi", channel_id="C1", user_id="U42") == ""
    assert rig.processed == []


@pytest.mark.parametrize("gate", ["no-pairing-service", "adapter-opted-out"])
async def test_a_sender_the_gate_does_not_pair_is_served_as_before(rig: _Rig, gate: str) -> None:
    """P5 golden: with no pairing service, or on an adapter that opts out of pairing, a sender is not paired and its
    natural language is processed exactly as before BF-903."""
    if gate == "no-pairing-service":
        rig.runtime.pairing_service = None
        adapter: _Adapter = rig.adapter
    else:
        adapter = _OptedOut(rig.runtime)
    message = _message("u-5", STATUS_TEXT)
    assert await adapter.handle_message(message) == "all systems nominal"
    assert message.paired_did is None
    assert rig.processed == [STATUS_TEXT]


# ---------------------------------------------------------------- MCP


class _Trust:
    """BF-875's trust-network double: the members ``FederationPeerRegistry`` calls. Not under test."""

    def create_with_prior(self, agent_id: str, alpha: float, beta: float) -> None:
        return None

    def record_outcome(
        self, agent_id: str, success: bool, weight: float = 1.0, intent_type: str = "",
        episode_id: str = "", verifier_id: str = "", source: str = "verification",
    ) -> float:
        return 0.5

    def get_score(self, agent_id: str) -> float:
        return 0.5


class _McpRuntime:
    """The runtime members the MCP server reads: the real bus, peer registry and app registry, and the identities."""

    def __init__(
        self, identities: AgentIdentityRegistry, apps: MCPAppRegistry, events: list[tuple[Any, dict[str, Any]]],
    ) -> None:
        self.identity_registry = identities
        self.intent_bus = IntentBus(SignalManager())
        self.federation_peer_registry = FederationPeerRegistry(trust_network=_Trust())
        self.mcp_app_registry = apps
        self.recorded = events

    def emit_event(self, event: Any, data: Any = None) -> None:
        self.recorded.append((event, dict(data or {})))


class _Mcp:
    """The real inbound MCP server with one exposed intent and one app tool, each recording what it is sent."""

    def __init__(self, identities: AgentIdentityRegistry) -> None:
        self.calls: list[dict[str, Any]] = []
        self.moves: list[dict[str, Any]] = []
        self.events: list[tuple[Any, dict[str, Any]]] = []
        apps = MCPAppRegistry(internal_default_csp=CSP, external_default_csp=CSP)
        apps.register_app_tool(name=MOVE_TOOL, description="", input_schema={}, ui_resource_uri="", handler=self._move)
        self.runtime = _McpRuntime(identities, apps, self.events)
        self.runtime.intent_bus.subscribe("bf903-echo", self._echo, intent_names=[ECHO_INTENT])
        echo = IntentDescriptor(name=ECHO_INTENT, params={"note": "any value"}, description="records its arguments")
        self.server = FederationMCPServer(
            runtime=self.runtime,
            config=FederationMCPServerConfig(auth_token=TOKEN, exposed_intents=[ECHO_INTENT]),
            collect_intent_descriptors_fn=lambda: [echo],
        )

    async def _move(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.moves.append(arguments)
        return {"isError": False, "content": [{"type": "text", "text": "moved"}]}

    async def _echo(self, intent: IntentMessage) -> IntentResult:
        self.calls.append(dict(intent.params))
        return IntentResult(intent_id=intent.id, agent_id="bf903-echo", success=True, result={"ok": True}, confidence=0.9)

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """One authenticated tools/call through the app ``start()`` serves (door A)."""
        app = build_mcp_app(path="/mcp", auth_token=TOKEN, handle_jsonrpc=self.server.handle_jsonrpc)
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        async with _AsyncClient(transport=_ASGITransport(app=app), base_url="http://mcp.test") as client:
            response = await client.post("/mcp", json=request, headers={"Authorization": f"Bearer {TOKEN}"})
        return response.json()

    def failures(self) -> list[dict[str, Any]]:
        return [data for event, data in self.events if event == EventType.MCP_BRIDGE_FAILED]


_NAMING: dict[str, tuple[str, Any]] = {
    "intent-did": (ECHO_INTENT, lambda did, uuid: {"note": did}),
    "intent-certificate-uuid": (ECHO_INTENT, lambda did, uuid: {"note": uuid}),
    "object-key": (ECHO_INTENT, lambda did, uuid: {"note": {did: "post"}}),
    "list-item": (ECHO_INTENT, lambda did, uuid: {"note": ["crew", uuid]}),
    "nested-value": (ECHO_INTENT, lambda did, uuid: {"note": {"on_behalf": {"of": [1, {"actor": did}]}}}),
    "deregistered-visitor": (ECHO_INTENT, lambda did, uuid: {"note": did}),
    "app-tool": (MOVE_TOOL, lambda did, uuid: {"player": did}),
}


@pytest.mark.parametrize("shape", list(_NAMING))
async def test_a_tools_call_naming_a_visitor_is_refused_before_either_branch(
    identities: AgentIdentityRegistry, shape: str,
) -> None:
    """Q1: a visiting officer's DID or certificate UUID anywhere in the arguments, as a value, a key or a list item,
    at any depth, refuses the call before the intent and app-tool branches; a deregistered visitor is still one."""
    mcp = _Mcp(identities)
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_DM_SEND])
    if shape == "deregistered-visitor":
        officers.deregister(session.did)
    tool, arguments = _NAMING[shape]
    reply = await mcp.call(tool, arguments(session.did, session.did.rsplit(":", 1)[1]))
    assert reply["error"] == {
        "code": -32602, "message": _VISITOR_REFUSALS[REFUSED_VISITOR_UNBOUND].format(name=tool),
    }
    assert (mcp.calls, mcp.moves) == ([], [])
    assert len(mcp.runtime.federation_peer_registry) == 0  # A4: the refusal registers no peer
    assert mcp.failures() == [
        {"side": "server", "method": "tools/call", "reason": REFUSED_VISITOR_UNBOUND, "detail": tool},
    ]


@pytest.mark.parametrize("shape", ["crew-did", "crew-certificate-uuid", "slot-id", "prose-with-a-visitor-did"])
async def test_crew_ids_and_prose_that_mentions_a_visitor_are_dispatched(
    identities: AgentIdentityRegistry, shape: str,
) -> None:
    """Q2: only a whole value that is a visiting officer's id refuses; a crew DID or certificate UUID (looked up, not
    a visitor), a slot id (never looked up) and prose that mentions a visitor's DID are dispatched."""
    mcp = _Mcp(identities)
    session = await _officers(identities, _Clock(), []).register("visitor", [CAP_DM_SEND])
    crew = await _crew(identities)
    note = {
        "crew-did": crew.did, "crew-certificate-uuid": crew.agent_uuid, "slot-id": CREW_SLOT,
        "prose-with-a-visitor-did": f"ask {session.did} to stand by",
    }[shape]
    reply = await mcp.call(ECHO_INTENT, {"note": note})
    assert json.loads(reply["result"]["content"][0]["text"]) == {"ok": True}
    assert mcp.calls == [{"note": note}]
    assert len(mcp.runtime.federation_peer_registry) == 1  # A4: a dispatched call registers its peer, so Q1's zero is observable
    assert mcp.failures() == []


async def test_the_argument_walk_reads_up_to_its_bound_and_refuses_past_it(identities: AgentIdentityRegistry) -> None:
    """Q3: the walk counts the object, its key, the list and each item. At the bound the arguments pass; one value
    past it they are refused unread rather than dispatched with values nobody checked."""
    at_bound = {"items": list(range(MAX_ARGUMENT_VALUES - 3))}
    past_bound = {"items": list(range(MAX_ARGUMENT_VALUES - 2))}
    assert visitor_argument_refusal(at_bound, identities) is None
    assert visitor_argument_refusal(past_bound, identities) == REFUSED_ARGUMENTS_UNWALKED
    mcp = _Mcp(identities)
    reply = await mcp.call(ECHO_INTENT, past_bound)
    assert reply["error"] == {
        "code": -32602, "message": _VISITOR_REFUSALS[REFUSED_ARGUMENTS_UNWALKED].format(name=ECHO_INTENT),
    }
    assert mcp.calls == []
    assert [f["reason"] for f in mcp.failures()] == [REFUSED_ARGUMENTS_UNWALKED]


class _CountingList(list[int]):
    """A JSON array that counts the items read from it; ``list.extend`` iterates a list subclass through ``__iter__``."""

    def __init__(self, items: range) -> None:
        super().__init__(items)
        self.read = 0

    def __iter__(self) -> Any:
        for item in super().__iter__():
            self.read += 1
            yield item


async def test_the_argument_walk_counts_a_container_before_it_reads_one(identities: AgentIdentityRegistry) -> None:
    """Q4 (A4): the walk counts an array's items and an object's keys and values from their length before it reads
    them, so a container that takes the call past the bound is refused with none of its items read or queued; under
    the bound every item is read, which shows the counter sees the walk. Before A4 all 10,000 items were enumerated
    and queued before the refusal."""
    wide = _CountingList(range(MAX_ARGUMENT_VALUES))
    assert visitor_argument_refusal({"items": wide}, identities) == REFUSED_ARGUMENTS_UNWALKED
    assert wide.read == 0
    narrow = _CountingList(range(MAX_ARGUMENT_VALUES - 3))
    assert visitor_argument_refusal({"items": narrow}, identities) is None
    assert narrow.read == MAX_ARGUMENT_VALUES - 3
    wide_object = {f"k{i}": i for i in range(MAX_ARGUMENT_VALUES // 2)}
    assert visitor_argument_refusal(wide_object, identities) == REFUSED_ARGUMENTS_UNWALKED
