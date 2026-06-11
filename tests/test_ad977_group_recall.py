"""AD-977 (Natural Conversation epic #882): group-thread episodic continuity.

Both crew agents flagged that recall of GROUP conversations was patchy (an
honest no-confabulation report). AD-933a writes a group episode per reply, but
the embedded document (``EpisodicMemory._prepare_document``) and the FTS5
sidecar index ``user_input`` + ``reflection`` — NOT ``outcomes[].response``.
The AD-933a group episode set ``user_input = "[group chat] <trigger>"`` (the
Captain's prompt) and NO ``reflection``, so the agent's OWN reply lived only in
``outcomes`` and was never indexed. Net: a group episode was findable by the
Captain's trigger text but never by the agent's contribution — the group-vs-1:1
recall gap (the 1:1 ``_store_action_episode`` indexes the response via
``reflection="<callsign> handled <intent>: <response>"``).

AD-977 mirrors the 1:1 pattern: the group episode now carries
``reflection="<callsign> said in group chat: <reply>"`` so the agent can recall
what it said in the room.

BF-287 discipline: real ``ChatThreadStore`` / ``IntentBus`` + a real-but-fake
recording ``episodic_memory`` (NOT MagicMock) exposing ``async def store``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadStore
from probos.types import IntentMessage, IntentResult


class _FakeAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type


class _FakeRegistry:
    def __init__(self, agents):
        self._a = agents

    def get(self, agent_id):
        return self._a.get(agent_id)


class _FakeCallsigns:
    def __init__(self, mapping):
        self._m = mapping

    def get_callsign(self, agent_type):
        return self._m.get(agent_type, "")


class _RecordingEpisodicMemory:
    def __init__(self):
        self.episodes: list = []

    async def store(self, episode):
        self.episodes.append(episode)


def _seq_clock():
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


_CALLSIGNS = {"scout": "Scout", "diagnostician": "Bones"}


def _make_handler(agent_id, text):
    async def _h(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, result=text
        )

    return _h


def _build_env(tmp_path, *, replies):
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    agents = {"scout1": _FakeAgent("scout"), "bones1": _FakeAgent("diagnostician")}
    episodic = _RecordingEpisodicMemory()
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=_FakeRegistry(agents),
        ontology=None,
        callsign_registry=_FakeCallsigns(_CALLSIGNS),
        project_store=None,
        episodic_memory=episodic,
        config=SimpleNamespace(group_chat=None, communications=None, perception=None),
    )
    for aid, txt in replies.items():
        bus.subscribe(aid, _make_handler(aid, txt), intent_names=["direct_message"])
    return store, runtime, episodic


@pytest.mark.asyncio
async def test_group_episode_reflection_carries_agent_reply(tmp_path):
    # The agent's OWN reply text must appear in the episode's reflection so it
    # is indexed (the recall gap fix).
    store, runtime, episodic = _build_env(
        tmp_path,
        replies={
            "scout1": "I scouted the northern ridge and found a coolant trail.",
            "bones1": "Vitals on the away team are stable.",
        },
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="report?")
    await group_chat_fanout(runtime, t.id, captain_body="report?", captain_msg=cap)

    assert episodic.episodes, "group fan-out should write episodes"
    by_agent = {ep.agent_ids[0]: ep for ep in episodic.episodes if ep.agent_ids}
    # Each agent's episode reflection contains ITS OWN reply (recallable).
    assert "coolant trail" in by_agent["scout1"].reflection
    assert "Vitals on the away team" in by_agent["bones1"].reflection
    # And names the speaker (mirrors the 1:1 _store_action_episode shape).
    assert "Scout" in by_agent["scout1"].reflection
    assert "Bones" in by_agent["bones1"].reflection


@pytest.mark.asyncio
async def test_reflection_is_indexable_content_not_just_trigger(tmp_path):
    # The trigger (user_input) is the Captain prompt; the reflection is the
    # agent's contribution. Both differ -> the embedded document now spans both.
    store, runtime, episodic = _build_env(
        tmp_path, replies={"scout1": "The relay array needs realignment.", "bones1": "Agreed."}
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(
        t.id, author_id="captain", role="captain", body="status of the relay?"
    )
    await group_chat_fanout(runtime, t.id, captain_body="status of the relay?", captain_msg=cap)

    scout_ep = next(ep for ep in episodic.episodes if ep.agent_ids == ["scout1"])
    # user_input = the trigger; reflection = the agent's reply. Distinct content.
    assert "group chat" in scout_ep.user_input
    assert "status of the relay" in scout_ep.user_input
    assert "relay array needs realignment" in scout_ep.reflection
    assert "relay array needs realignment" not in scout_ep.user_input


@pytest.mark.asyncio
async def test_reply_still_in_outcomes_unchanged(tmp_path):
    # AD-977 is additive: outcomes[].response (full reply, untruncated to 500)
    # is preserved alongside the new reflection.
    store, runtime, episodic = _build_env(
        tmp_path, replies={"scout1": "Detailed scouting report.", "bones1": "Noted."}
    )
    t = store.create_thread(title="room", participants=["scout1", "bones1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="report?")
    await group_chat_fanout(runtime, t.id, captain_body="report?", captain_msg=cap)

    scout_ep = next(ep for ep in episodic.episodes if ep.agent_ids == ["scout1"])
    assert scout_ep.outcomes[0]["response"] == "Detailed scouting report."
    assert scout_ep.outcomes[0]["session_type"] == "group"
