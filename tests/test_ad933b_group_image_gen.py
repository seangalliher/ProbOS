"""AD-933b: agent image generation inside a group chat + ref surfacing.

AD-933 wired five channel-agnostic escalation steps into the group fan-out.
AD-933b adds ONE more — ``step_4c_image_gen_parse`` (AD-730-3 ``[GEN_IMAGE]``)
— so an agent can generate an image in a room, and surfaces the generated
SHA refs onto the persisted group message metadata (AD-916 ref carriage). The
``step_4d_follow_up`` step is deliberately NOT added (forward marker AD-933b-2).

Two facets are proven here:

* **Pipeline level** (tests 1-2): ``run_escalation_only()`` now runs exactly the
  six escalation steps including 4c, in run()-order; ``run()`` still executes
  the full 17-step chain byte-identical (regression guard). The 17 step methods
  are replaced with async spies so only invocation/order is asserted.

* **Fan-out level** (tests 3-5): a real ``group_chat_fanout`` end-to-end with a
  real ``ChatThreadStore`` / ``IntentBus`` / ``DmSanityGate``. ``dispatch_image_gen``
  is monkeypatched at its source module ``probos.cognitive.image_gen_dispatch``
  (step_4c imports it function-locally, so that is the resolvable name) to
  return the AD-730-3 success / honest-degrade shapes. A ``[GEN_IMAGE a cat]``
  marker surfaces the SHA ref on the persisted message metadata; a disabled
  tier honest-degrades (marker stripped, operator message appended, no ref); a
  plain reply leaves the metadata byte-identical to the AD-914 baseline.

BF-287 discipline: real substrate everywhere; a real-but-fake registry /
callsign stub (NOT ``MagicMock``) at the bus boundary; canned ``dispatch_image_gen``
is a plain async function, not a mock. Mirrors ``tests/test_ad933_group_chat_escalation.py``.
"""
from __future__ import annotations

from types import SimpleNamespace

import probos.cognitive.image_gen_dispatch as image_gen_dispatch
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.thread_fanout import group_chat_fanout
from probos.threads import ChatThreadMessage, ChatThreadStore
from probos.types import IntentMessage, IntentResult
from probos.cognitive.dm.reply_value import DmReply  # AD-1248


# ---------------- pipeline-level step inventory ----------------

# The full 18-step chain in load-bearing order (mirrors ``_full_steps``).
_ALL_STEPS = (
    "step_1_sanity_gate_retry",
    "step_2_challenge_parse",
    "step_3_move_parse",
    "step_4_self_check_parse",
    "step_4c_image_gen_parse",
    "step_4d_follow_up_parse",
    "step_4e_action_dispatch",
    "step_4b_dm_outbound_parse",
    "step_4i_notebook_parse",
    "step_4h_mesh_read_parse",
    "step_4f_extract_artifacts",
    "step_4g_create_task_parse",
    "step_4j_deliberate_parse",
    "step_5_episodic_store",
    "step_6_working_memory_record",
    "step_7_divergence_check",
    "step_8_mark_emitted",
    "step_9_emotion_resolve",
)
# The escalation subset reused by the group fan-out, in run()-order
# (4c added by AD-933b, first because it precedes 4e in ``_full_steps``;
# 4j added by AD-934, appended last after 4g).
_ESCALATION_STEPS = (
    "step_4c_image_gen_parse",
    "step_4e_action_dispatch",
    "step_4i_notebook_parse",
    "step_4h_mesh_read_parse",
    "step_4f_extract_artifacts",
    "step_4g_create_task_parse",
    "step_4j_deliberate_parse",
)


def _minimal_ctx() -> DmReplyContext:
    """A constructible ctx for the spy tests. The step bodies never run (they
    are replaced by spies), so placeholder fields are sufficient."""
    return DmReplyContext(
        runtime=SimpleNamespace(),
        agent=SimpleNamespace(),
        agent_id="a1",
        callsign="A",
        req_message="hi",
        reply=DmReply(body="hi"),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="hi",
        sampling_state=None,
        avatar_event_bus=None,
    )


def _spy_all_steps(pipeline: DmReplyPipeline, recorder: list[str]) -> None:
    """Replace every step method on the instance with an async recorder.

    ``_full_steps``/``_escalation_steps`` reference ``self.step_X`` at call
    time, so instance attributes shadow the class methods and the recorder
    sees exactly which steps the runner invoked and in what order.
    """
    def _make(name: str):
        async def _spy() -> None:
            recorder.append(name)
        return _spy

    for name in _ALL_STEPS:
        setattr(pipeline, name, _make(name))


# ---------------- fan-out-level BF-287 real-but-fake substrate ----------------


class _FakeAgent:
    def __init__(self, agent_type: str, agent_id: str) -> None:
        self.agent_type = agent_type  # is_crew_agent + callsign read .agent_type
        self.id = agent_id


class _FakeRegistry:
    def __init__(self, agents: dict[str, _FakeAgent]) -> None:
        self._a = agents

    def get(self, agent_id: str):
        return self._a.get(agent_id)

    def get_by_pool(self, pool: str):
        # AD-869 mesh-read: empty pool makes step_4h fast-degrade (no bus send,
        # no TTL wait) — never reached here since replies carry no [MESH] tag.
        return []


class _FakeCallsigns:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._m = mapping  # agent_type -> callsign

    def get_callsign(self, agent_type: str) -> str:
        return self._m.get(agent_type, "")

    def resolve(self, ref: str):
        # AD-845 specialist resolution: never reached (no [CREATE_TASK] tag).
        return None


def _seq_clock():
    """Deterministic monotonic clock so created_at ordering (and the
    ``before=`` history filter) is exact regardless of wall-clock speed."""
    n = {"t": 0}

    def _c() -> float:
        n["t"] += 1
        return float(n["t"])

    return _c


def _canned_handler(reply: str, agent_id: str):
    async def _h(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=True,
            result=reply,
        )

    return _h


def _build_env(
    tmp_path,
    *,
    agents: dict[str, str],
    replies: dict[str, str],
    callsigns: dict[str, str] | None = None,
):
    """agents: {agent_id: agent_type}. replies: {agent_id: canned_reply}.

    Builds a real runtime whose ``config.avatars.image_gen_max_prompt_chars``
    is set (so step_4c's ``extract_gen_image`` uses an explicit cap, never
    rejecting the short test prompts) and a real ``DmSanityGate`` (so step_4c's
    marker extract/strip is real). Returns (store, runtime).
    """
    store = ChatThreadStore(tmp_path / "threads.db", clock=_seq_clock())
    bus = IntentBus(SignalManager(reap_interval=1.0))
    registry = _FakeRegistry({aid: _FakeAgent(at, aid) for aid, at in agents.items()})
    runtime = SimpleNamespace(
        chat_thread_store=store,
        intent_bus=bus,
        registry=registry,
        ontology=None,
        callsign_registry=_FakeCallsigns(callsigns or {}),
        project_store=None,
        dm_sanity_gate=DmSanityGate(),
        work_item_store=None,
        # Minimal real-but-fake config: only ``avatars`` is read by step_4c.
        # No ``group_chat`` attr => ChatFacilitator.from_config uses all-speak
        # defaults (convergence cannot fire on a fresh 2-agent thread).
        config=SimpleNamespace(
            avatars=SimpleNamespace(image_gen_max_prompt_chars=512),
        ),
    )
    for aid in agents:
        bus.subscribe(aid, _canned_handler(replies[aid], aid), intent_names=["direct_message"])
    return store, runtime


def _agent_messages(store: ChatThreadStore, thread_id: str) -> dict[str, ChatThreadMessage]:
    """Persisted role='agent' messages keyed by author_id (ground truth)."""
    return {
        m.author_id: m
        for m in store.list_messages(thread_id, limit=1000)
        if m.role == "agent"
    }


# Canned ``dispatch_image_gen`` replacements (AD-730-3 flat-dict shapes).
async def _fake_dispatch_ok(runtime, *, agent_id: str, prompt: str) -> dict:
    return {"ok": True, "attachment_id": "sha-xyz"}


async def _fake_dispatch_disabled(runtime, *, agent_id: str, prompt: str) -> dict:
    return {"ok": False, "message": "image tier disabled"}


# ---------------- 1. run_escalation_only() now runs 6 steps incl. 4c ----------------


async def test_run_escalation_only_runs_six_steps_including_4c():
    recorder: list[str] = []
    pipeline = DmReplyPipeline(_minimal_ctx())
    _spy_all_steps(pipeline, recorder)

    await pipeline.run_escalation_only()

    # Exactly the seven escalation steps, in run()-order (4c first, 4j last),
    # nothing else.
    assert tuple(recorder) == _ESCALATION_STEPS
    assert set(recorder) == set(_ESCALATION_STEPS)
    # The other eleven steps were NOT invoked.
    assert set(_ALL_STEPS) - set(recorder) == {
        "step_1_sanity_gate_retry",
        "step_2_challenge_parse",
        "step_3_move_parse",
        "step_4_self_check_parse",
        "step_4d_follow_up_parse",
        "step_4b_dm_outbound_parse",
        "step_5_episodic_store",
        "step_6_working_memory_record",
        "step_7_divergence_check",
        "step_8_mark_emitted",
        "step_9_emotion_resolve",
    }


# ---------------- 2. run() still 18 steps, byte-identical order ----------------


async def test_run_still_eighteen_steps_in_order():
    recorder: list[str] = []
    pipeline = DmReplyPipeline(_minimal_ctx())
    _spy_all_steps(pipeline, recorder)

    await pipeline.run()

    # Regression guard: the full chain is unchanged except the AD-934 4j
    # insertion between 4g and 5 (4c remains where AD-730-3 put it).
    assert tuple(recorder) == _ALL_STEPS
    assert len(recorder) == 18


# ---------------- 3. group [GEN_IMAGE] surfaces the SHA ref ----------------


async def test_group_gen_image_surfaces_ref(tmp_path, monkeypatch):
    monkeypatch.setattr(image_gen_dispatch, "dispatch_image_gen", _fake_dispatch_ok)
    store, runtime = _build_env(
        tmp_path,
        agents={"yeo1": "scout", "scout1": "counselor"},
        replies={
            "yeo1": "Here you go, Captain. [GEN_IMAGE a cat]",
            "scout1": "Standing by, Captain.",
        },
        callsigns={"scout": "Yeo", "counselor": "Scout"},
    )
    t = store.create_thread(title="room", participants=["yeo1", "scout1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="draw a cat")

    replies = await group_chat_fanout(runtime, t.id, captain_body="draw a cat", captain_msg=cap)
    assert len(replies) == 2

    msgs = _agent_messages(store, t.id)
    # The image-gen agent's persisted reply carries the SHA ref; marker stripped.
    assert msgs["yeo1"].metadata.get("generated_attachment_ids") == ["sha-xyz"]
    assert "[GEN_IMAGE" not in msgs["yeo1"].body
    assert "Here you go, Captain." in msgs["yeo1"].body
    # The other speaker's plain reply carries no ref key.
    assert "generated_attachment_ids" not in msgs["scout1"].metadata
    assert msgs["scout1"].body == "Standing by, Captain."


# ---------------- 4. disabled tier honest-degrades ----------------


async def test_group_gen_image_disabled_tier_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(image_gen_dispatch, "dispatch_image_gen", _fake_dispatch_disabled)
    store, runtime = _build_env(
        tmp_path,
        agents={"yeo1": "scout", "scout1": "counselor"},
        replies={
            "yeo1": "On it. [GEN_IMAGE a cat]",
            "scout1": "Aye, Captain.",
        },
        callsigns={"scout": "Yeo", "counselor": "Scout"},
    )
    t = store.create_thread(title="room", participants=["yeo1", "scout1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="draw a cat")

    replies = await group_chat_fanout(runtime, t.id, captain_body="draw a cat", captain_msg=cap)
    assert len(replies) == 2  # no crash; the fan-out still returns both replies

    msgs = _agent_messages(store, t.id)
    yeo = msgs["yeo1"]
    # Marker stripped, operator-facing degrade message appended, reply persisted.
    assert "[GEN_IMAGE" not in yeo.body
    assert "On it." in yeo.body
    assert "image tier disabled" in yeo.body
    # No image was generated -> no ref key on the degraded message.
    assert "generated_attachment_ids" not in yeo.metadata


# ---------------- 5. plain reply leaves metadata byte-identical ----------------


async def test_group_plain_reply_metadata_unchanged(tmp_path, monkeypatch):
    # A plain (no-marker) reply must never call dispatch_image_gen: extract
    # returns [] and step_4c returns early. Patch it to raise to prove that.
    async def _boom(runtime, *, agent_id, prompt):
        raise AssertionError("dispatch_image_gen must not be called for a plain reply")

    monkeypatch.setattr(image_gen_dispatch, "dispatch_image_gen", _boom)
    store, runtime = _build_env(
        tmp_path,
        agents={"yeo1": "scout", "scout1": "counselor"},
        replies={"yeo1": "Aye, Captain.", "scout1": "Standing by."},
        callsigns={"scout": "Yeo", "counselor": "Scout"},
    )
    t = store.create_thread(title="room", participants=["yeo1", "scout1"])
    cap = store.append_message(t.id, author_id="captain", role="captain", body="status?")

    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)

    msgs = _agent_messages(store, t.id)
    # Metadata is EXACTLY the AD-914 baseline — no new key, for every speaker.
    assert set(msgs["yeo1"].metadata.keys()) == {"intent_id", "fanout"}
    assert set(msgs["scout1"].metadata.keys()) == {"intent_id", "fanout"}
