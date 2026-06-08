"""AD-918: agent-initiated group-chat creation tests.

BF-287 discipline: real ``ChatThreadStore`` on ``tmp_path``, real
``IntentBus(SignalManager(reap_interval=1.0))``, real-but-fake registry /
callsign stubs (NOT ``MagicMock``) at the substrate/bus boundary, and an
injectable deterministic clock so the cooldown + sliding-window cap are
exercised without wall-clock flakiness. Test 4 uses the REAL
``CallsignRegistry`` (loaded from the shipped crew profiles) to prove the
callsign-resolution path. Crew ``agent_type``s are drawn from the legacy
``crew_utils._WARD_ROOM_CREW`` set so ``ontology_provider=None`` resolves
crew correctly.
"""
from __future__ import annotations

from types import SimpleNamespace

from probos.config import GroupChatConfig
from probos.crew_profile import CallsignRegistry
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import crew_agent_participants
from probos.threads import ChatThreadStore
from probos.threads.agent_group_chat import (
    CREATE_GROUP_CHAT,
    GROUP_CHAT_COORDINATOR_ID,
    AgentGroupChatService,
)
from probos.types import IntentMessage


# ---------------- BF-287 real-but-fake substrate stubs ----------------


class _FakeAgent:
    def __init__(self, agent_id: str, agent_type: str, *, is_alive: bool = True) -> None:
        self.id = agent_id
        self.agent_type = agent_type      # is_crew_agent reads .agent_type
        self.is_alive = is_alive          # CallsignRegistry.resolve reads .is_alive


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)

    def get_by_pool(self, agent_type: str):
        return [a for a in self._a.values() if a.agent_type == agent_type]


class _NoCallsigns:
    """Callsign registry stub whose resolve always misses (agent_id-only path)."""

    def resolve(self, callsign: str):
        return None


class _Clock:
    """Deterministic injectable monotonic clock (real fixture, not MagicMock)."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


def _make_service(
    tmp_path,
    *,
    agents: dict[str, _FakeAgent],
    callsign_registry=None,
    config: GroupChatConfig | None = None,
    clock: _Clock | None = None,
) -> tuple[AgentGroupChatService, ChatThreadStore, _FakeRegistry]:
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    registry = _FakeRegistry(agents)
    svc = AgentGroupChatService(
        store=store,
        registry=registry,
        callsign_registry=callsign_registry or _NoCallsigns(),
        config=config or GroupChatConfig(),
        ontology_provider=None,
        clock=clock or _Clock(),
    )
    return svc, store, registry


# ---------------- 1. create + persist + tag ----------------


def test_create_named_chat_persisted_and_tagged(tmp_path):
    svc, store, _ = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(creator_id="forge-1", title="Coord")
    assert res.ok
    assert res.thread is not None
    persisted = store.get_thread(res.thread.id)
    assert persisted is not None
    assert persisted.title == "Coord"
    assert persisted.metadata["created_by_agent"] == "forge-1"
    assert "forge-1" in persisted.participants


def test_creator_auto_added_when_participants_empty(tmp_path):
    svc, _, _ = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(creator_id="forge-1", title="Solo", participants=None)
    assert res.ok
    assert res.participants_added == ["forge-1"]


# ---------------- 2. participant resolution ----------------


def test_add_second_crew_participant_by_agent_id(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    svc, store, _ = _make_service(tmp_path, agents=agents)
    # creator passed again in participants -> must dedupe, not duplicate.
    res = svc.create_group_chat(
        creator_id="forge-1", title="Pair", participants=["forge-1", "bones-1"]
    )
    assert res.ok
    persisted = store.get_thread(res.thread.id)
    assert persisted.participants == ["forge-1", "bones-1"]


def test_add_participant_by_callsign(tmp_path):
    # Real CallsignRegistry loaded from the shipped crew profiles. "Bones"
    # maps to agent_type "diagnostician" (a crew type).
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    registry = _FakeRegistry(agents)
    cs = CallsignRegistry()
    cs.load_from_profiles()
    cs.bind_registry(registry)
    store = ChatThreadStore(tmp_path / "chat_threads.db")
    svc = AgentGroupChatService(
        store=store,
        registry=registry,
        callsign_registry=cs,
        config=GroupChatConfig(),
        ontology_provider=None,
        clock=_Clock(),
    )
    # "Bones" resolves to bones-1; a bogus callsign is dropped (Tier-2).
    res = svc.create_group_chat(
        creator_id="forge-1", title="Sickbay", participants=["Bones", "Zzznotacallsign"]
    )
    assert res.ok
    persisted = store.get_thread(res.thread.id)
    assert "bones-1" in persisted.participants
    assert persisted.participants == ["forge-1", "bones-1"]


def test_non_crew_participant_filtered(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "civ-1": _FakeAgent("civ-1", "captain"),  # not in _WARD_ROOM_CREW
    }
    svc, store, _ = _make_service(tmp_path, agents=agents)
    res = svc.create_group_chat(
        creator_id="forge-1", title="Mixed", participants=["civ-1"]
    )
    assert res.ok
    persisted = store.get_thread(res.thread.id)
    assert persisted.participants == ["forge-1"]


# ---------------- 3. task_id linkage ----------------


def test_task_id_linkage_when_provided(tmp_path):
    svc, store, _ = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(creator_id="forge-1", title="Linked", task_id="wi-123")
    assert res.ok
    persisted = store.get_thread(res.thread.id)
    assert persisted.task_id == "wi-123"


def test_task_id_none_default(tmp_path):
    svc, store, _ = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(creator_id="forge-1", title="Unlinked")
    assert res.ok
    persisted = store.get_thread(res.thread.id)
    assert persisted.task_id is None


# ---------------- 4. optional first message ----------------


def test_first_message_posted_when_provided(tmp_path):
    svc, store, _ = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(
        creator_id="forge-1", title="Kickoff", first_message="kick off"
    )
    assert res.ok
    msgs = store.list_messages(res.thread.id)
    assert len(msgs) == 1
    assert msgs[0].role == "agent"
    assert msgs[0].author_id == "forge-1"
    assert msgs[0].body == "kick off"


def test_no_first_message_when_omitted(tmp_path):
    svc, store, _ = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    res = svc.create_group_chat(creator_id="forge-1", title="Quiet")
    assert res.ok
    assert store.list_messages(res.thread.id) == []


# ---------------- 5. rate limiting ----------------


def test_cooldown_blocks_rapid_second_create(tmp_path):
    clock = _Clock(1000.0)
    cfg = GroupChatConfig(
        agent_create_cooldown_seconds=60.0,
        agent_create_max_per_window=5,
        agent_create_window_seconds=3600.0,
    )
    svc, store, _ = _make_service(
        tmp_path,
        agents={"forge-1": _FakeAgent("forge-1", "builder")},
        config=cfg,
        clock=clock,
    )
    first = svc.create_group_chat(creator_id="forge-1", title="One")
    assert first.ok
    clock.advance(10.0)  # < cooldown
    second = svc.create_group_chat(creator_id="forge-1", title="Two")
    assert second.ok is False
    assert second.error == "rate_limited"
    assert second.thread is None
    assert len(store.list_threads()) == 1


def test_window_cap_blocks_after_max(tmp_path):
    clock = _Clock(1000.0)
    cfg = GroupChatConfig(
        agent_create_cooldown_seconds=60.0,
        agent_create_max_per_window=3,
        agent_create_window_seconds=3600.0,
    )
    svc, store, _ = _make_service(
        tmp_path,
        agents={"forge-1": _FakeAgent("forge-1", "builder")},
        config=cfg,
        clock=clock,
    )
    for i in range(3):  # three allowed, each past cooldown
        res = svc.create_group_chat(creator_id="forge-1", title=f"Room{i}")
        assert res.ok
        clock.advance(61.0)
    blocked = svc.create_group_chat(creator_id="forge-1", title="Overflow")
    assert blocked.ok is False
    assert blocked.error == "rate_limited"
    assert len(store.list_threads()) == 3


def test_rate_resets_after_window(tmp_path):
    clock = _Clock(1000.0)
    cfg = GroupChatConfig(
        agent_create_cooldown_seconds=10.0,
        agent_create_max_per_window=1,
        agent_create_window_seconds=100.0,
    )
    svc, _, _ = _make_service(
        tmp_path,
        agents={"forge-1": _FakeAgent("forge-1", "builder")},
        config=cfg,
        clock=clock,
    )
    first = svc.create_group_chat(creator_id="forge-1", title="One")
    assert first.ok
    clock.advance(200.0)  # past the window -> old timestamp pruned
    again = svc.create_group_chat(creator_id="forge-1", title="Two")
    assert again.ok


# ---------------- 6. rejection paths ----------------


def test_non_crew_creator_rejected(tmp_path):
    svc, store, _ = _make_service(
        tmp_path, agents={"civ-1": _FakeAgent("civ-1", "captain")}
    )
    res = svc.create_group_chat(creator_id="civ-1", title="Nope")
    assert res.ok is False
    assert res.error == "not_crew"
    assert store.list_threads() == []
    # budget not consumed — the rate gate is reached only after the crew check.
    assert "civ-1" not in svc._create_times


def test_empty_title_rejected(tmp_path):
    svc, store, _ = _make_service(
        tmp_path, agents={"forge-1": _FakeAgent("forge-1", "builder")}
    )
    blank = svc.create_group_chat(creator_id="forge-1", title="")
    assert blank.ok is False
    assert blank.error == "empty_title"
    whitespace = svc.create_group_chat(creator_id="forge-1", title="   ")
    assert whitespace.ok is False
    assert whitespace.error == "empty_title"
    assert store.list_threads() == []


# ---------------- 7. bus handler ----------------


async def test_handle_intent_creates_thread_via_real_bus(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
    }
    svc, store, _ = _make_service(tmp_path, agents=agents)
    bus = IntentBus(SignalManager(reap_interval=1.0))
    bus.subscribe(
        GROUP_CHAT_COORDINATOR_ID,
        svc.handle_intent,
        intent_names=[CREATE_GROUP_CHAT],
    )
    results = await bus.broadcast(
        IntentMessage(
            intent=CREATE_GROUP_CHAT,
            params={
                "created_by_agent": "forge-1",
                "title": "Bridge",
                "participants": ["bones-1"],
            },
        )
    )
    assert len(results) == 1
    assert results[0].success
    thread_id = results[0].result["thread_id"]
    persisted = store.get_thread(thread_id)
    assert persisted is not None
    assert persisted.metadata["created_by_agent"] == "forge-1"
    assert persisted.participants == ["forge-1", "bones-1"]


# ---------------- 8. created thread is a normal ChatThread ----------------


async def test_created_thread_is_normal_chatthread_for_ad913_and_ad914(tmp_path):
    agents = {
        "forge-1": _FakeAgent("forge-1", "builder"),
        "bones-1": _FakeAgent("bones-1", "diagnostician"),
        "num1-1": _FakeAgent("num1-1", "architect"),
    }
    svc, store, registry = _make_service(tmp_path, agents=agents)
    res = svc.create_group_chat(
        creator_id="forge-1", title="Ops", participants=["bones-1"]
    )
    assert res.ok
    tid = res.thread.id

    # AD-913: add/remove_participant operate on the created thread as normal.
    updated = store.add_participant(tid, "num1-1")
    assert "num1-1" in updated.participants
    pruned = store.remove_participant(tid, "num1-1")
    assert "num1-1" not in pruned.participants

    # AD-914: the thread is fan-out-ready (crew participants resolve) even
    # though NO fan-out auto-ran on create (no captain message exists).
    fake_runtime = SimpleNamespace(registry=registry, ontology=None)
    crew = crew_agent_participants(fake_runtime, pruned.participants)
    assert set(crew) == {"forge-1", "bones-1"}
    assert store.list_messages(tid) == []  # no captain post -> no auto-fan

    # handle_intent self-deselects (returns None) for a non-matching intent.
    declined = await svc.handle_intent(IntentMessage(intent="something_else"))
    assert declined is None
