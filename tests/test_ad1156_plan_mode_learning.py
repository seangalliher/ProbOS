"""AD-1156 A-4 (#1083): a plan-mode reply is kept as a conversation and never learned
from as work, and a reply that bypasses the pipeline is shown as plan mode leaves it.

What is proven here, and where:

* The marker (``types.episode_ran_in_plan_mode``): one total predicate over an
  episode's outcomes. It survives the vector store's metadata round trip and the
  knowledge store's episode files; an episode written before A-4, in execute mode
  or with the modes off reads False.
* The producers: step 5, through the pipeline's runner as ``run()`` runs it,
  stores a plan-mode turn's episode with the marker and the reply as the passes
  left it, the notice whole within 500 characters and nothing it held back;
  execute mode and no gate store HEAD's outcome, key for key. The agent's own
  record of a turn (AD-430c) and a promoted run's episode (AD-1166) carry the
  marker when the turn ran in plan mode, and nothing else changes.
* The consumer, the real ``DreamingEngine`` over the episodes the real step 5
  stored: ``micro_dream``, ``_consolidate_trust`` and the shutdown consolidation
  leave Hebbian weights and trust where they were, while execute mode learns
  exactly as before; a dream cycle neither pre-warms, clusters nor finds a
  contradiction on them; procedure evolution never recalls them; and memory
  upkeep still reinforces them.
* The bypasses: AD-1230's replay, through the real finalize wiring and the real
  deferred-turn queue, and AD-1165's report, through the real
  ``run_with_promotion``, each post the reply as the route shows a plan-mode
  reply, and exactly what they posted before outside plan mode.
* The censuses: every outcome learner in dreaming reads through the one filter,
  every procedure-evolution recall goes through the one helper, and every
  ``direct_message`` episode a plan-mode turn can write is classified.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import inspect
import itertools
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import dreaming as dreaming_module
from probos.cognitive import turn_promotion
from probos.cognitive.agent_mode import (
    AGENT_MODE_FLOOR_PARAM,
    PlanModeReplyGate,
    TurnAgentMode,
    open_plan_mode_reply_gate,
    open_plan_mode_replay_gate,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.deferred_turns import _ANSWER_PREFIX
from probos.cognitive.dm import reply_pipeline as reply_pipeline_module
from probos.cognitive.dm.bypass_egress import compose_bypass_reply
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline, project_plan_mode_reply
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.procedures import Procedure
from probos.config import DmAgenticConfig, DreamingConfig, KnowledgeConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.dm_reply import DmReply
from probos.knowledge.store import KnowledgeStore
from probos.mesh.routing import REL_INTENT, HebbianRouter
from probos.startup.finalize import _wire_deferred_turns
from probos.threads import ChatThreadStore
from probos.types import EPISODE_PLAN_MODE_KEY, Episode, IntentMessage, IntentResult, episode_ran_in_plan_mode
from probos.workforce import WorkItemStore
from tests.test_ad1156_plan_execute_mode import (
    _AGENT as _DM_AGENT,
    _Grants,
    _ScriptedLLM,
    _Tool,
    _dm_agent,
    _registry,
    _runtime,
)

_AGENT = "a-ezri"
_PLAN = "Here is the plan. " + " ".join(
    f"Step {i}: gather the SEC-ALPHA figures for quarter {i} and cross-check them." for i in range(1, 9)
)
_SHORT_PLAN = "Here is the plan. Step 1: gather the SEC-ALPHA figures."
_DM = "[DM @Worf] Please pull the SEC-BRAVO figures. [/DM]"
_NOTE = "[NOTEBOOK plan-notes] Record the SEC-CHARLIE baseline. [/NOTEBOOK]"
_LONG = f"{_PLAN}\n{_DM}\n{_NOTE}"
_SHORT = f"{_SHORT_PLAN}\n{_DM}\n{_NOTE}"
_NOTICE = (
    "(Plan mode held back a message to a crewmate and a notebook entry; none of it "
    "was sent, saved or started. Once this conversation is in execute mode, ask again.)"
)
_HEAD_OUTCOME_KEYS = [
    "intent", "success", "response", "session_type", "callsign", "source", "agent_type",
    "has_image_attachment", "image_count", "failed_image_count", "per_attachment_timing",
]


# ── fixtures and fakes ──────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> ChatThreadStore:
    ticks = itertools.count(1_000)
    return ChatThreadStore(tmp_path / "threads.db", clock=lambda: float(next(ticks)))


def _config(*, modes: bool = True) -> SystemConfig:
    cfg = SystemConfig()
    cfg.dm_agentic.enabled = True
    cfg.dm_agentic.agent_modes_enabled = modes
    cfg.dm_agentic.hold_degraded_turns = True
    return cfg


def _thread(store: ChatThreadStore, mode: str | None, agent: str = _AGENT) -> Any:
    thread = store.get_or_create_default_for_agent(agent, "Ezri")
    if mode is not None:
        store.set_agent_mode(thread.id, mode, changed_by="captain")
    return store.get_thread(thread.id)


class _CountingStore:
    """The real thread store, with ``get_thread`` counted."""

    def __init__(self, inner: ChatThreadStore) -> None:
        self._inner = inner
        self.reads = 0

    def get_thread(self, thread_id: str) -> Any:
        self.reads += 1
        return self._inner.get_thread(thread_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def _reply_turn(
    store: ChatThreadStore, memory: MockEpisodicMemory, text: str, *, modes: bool = True,
) -> tuple[str, Episode]:
    """One reply through the route's pipeline, as the route opens its gate and runs it."""
    runtime = SimpleNamespace(
        config=_config(modes=modes), episodic_memory=memory, chat_thread_store=store,
        dm_sanity_gate=DmSanityGate(), recreation_service=None,
    )
    thread = _thread(store, None)
    ctx = DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id=_AGENT, agent_type="counselor", callsign="Ezri"),
        agent_id=_AGENT, callsign="Ezri", req_message="Plan the quarterly report.",
        reply=DmReply(body=text), has_image_attachment=False, per_attachment=[],
        sanity_gate=runtime.dm_sanity_gate, params={"thread_id": thread.id, "dm_turn_id": "turn-1"},
        message_text="Plan the quarterly report.", sampling_state=None, avatar_event_bus=None,
        chat_thread_id=thread.id, plan_mode_gate=open_plan_mode_reply_gate(runtime, store, thread, agent_id=_AGENT),
    )
    await DmReplyPipeline(ctx).run()
    [episode] = await memory.recent(1)
    return ctx.response_text, episode


def _dream_config(**overrides: Any) -> DreamingConfig:
    return DreamingConfig(
        idle_threshold_seconds=1.0, dream_interval_seconds=1.0, replay_episode_count=50,
        pathway_strengthening_factor=0.03, pathway_weakening_factor=0.02, prune_threshold=0.01,
        trust_boost=0.1, trust_penalty=0.1, pre_warm_top_k=5, **overrides,
    )


def _engine(memory: Any, **kwargs: Any) -> tuple[DreamingEngine, HebbianRouter, TrustNetwork]:
    router = HebbianRouter(decay_rate=0.995, reward=0.05)
    trust = TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999)
    config = kwargs.pop("config", None) or _dream_config()
    return DreamingEngine(router, trust, memory, config, **kwargs), router, trust


async def _conversation(store: ChatThreadStore, mode: str, turns: int = 3) -> MockEpisodicMemory:
    """``turns`` replies on a thread in ``mode``, each stored by the real step 5."""
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    _thread(store, mode)
    for _ in range(turns):
        await _reply_turn(store, memory, _SHORT)
    return memory


async def _same_embeddings(ids: list[str]) -> dict[str, list[float]]:
    return {i: [1.0, 0.0, 0.0] for i in ids}


def _trust(trust: TrustNetwork, agent: str) -> tuple[float, float] | None:
    record = trust.get_record(agent)
    return None if record is None else (round(record.alpha, 3), round(record.beta, 3))


# ── 1. the marker ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("episode", "planned"),
    [
        (Episode(outcomes=[{"intent": "direct_message", "success": True, EPISODE_PLAN_MODE_KEY: True}]), True),
        ({"outcomes": [{"intent": "direct_message", EPISODE_PLAN_MODE_KEY: True}]}, True),
        (Episode(outcomes=[{"kind": "note"}, {EPISODE_PLAN_MODE_KEY: True}]), True),
        (Episode(outcomes=[{"intent": "direct_message", "success": True}]), False),
        (Episode(), False),
        (Episode(outcomes=[{EPISODE_PLAN_MODE_KEY: "true"}]), False),
        (Episode(outcomes=[{EPISODE_PLAN_MODE_KEY: 1}]), False),
        (Episode(outcomes=[EPISODE_PLAN_MODE_KEY]), False),  # type: ignore[list-item]
        ({"outcomes": {EPISODE_PLAN_MODE_KEY: True}}, False),
        (Episode(outcomes=7), False),  # type: ignore[arg-type]
        (SimpleNamespace(), False),
        (None, False),
    ],
    ids=[
        "marked", "marked-mapping", "marked-second-outcome", "unmarked", "no-outcomes",
        "marker-a-string", "marker-one", "outcome-not-a-mapping", "outcomes-not-a-list",
        "outcomes-not-iterable", "no-outcomes-attribute", "none",
    ],
)
def test_the_marker_is_one_total_predicate(episode: Any, planned: bool) -> None:
    assert episode_ran_in_plan_mode(episode) is planned


async def test_the_marker_survives_the_vector_store_and_the_knowledge_store(tmp_path: Path) -> None:
    planned = Episode(
        id="ep-plan", timestamp=1000.0, user_input="[1:1 with Ezri] Captain: Plan it.", agent_ids=[_AGENT],
        outcomes=[{"intent": "direct_message", "success": True, "response": "A plan.", EPISODE_PLAN_MODE_KEY: True}],
    )
    worked = dataclasses.replace(
        planned, id="ep-work", outcomes=[{"intent": "direct_message", "success": True, "response": "Done."}],
    )
    for episode, expected in ((planned, True), (worked, False)):
        back = EpisodicMemory._metadata_to_episode(
            episode.id, episode.user_input, EpisodicMemory._episode_to_metadata(episode),
        )
        assert episode_ran_in_plan_mode(back) is expected

    knowledge = KnowledgeStore(KnowledgeConfig(
        enabled=True, repo_path=str(tmp_path / "knowledge"), auto_commit=False,
    ))
    await knowledge.initialize()
    for episode in (planned, worked):
        await knowledge.store_episode(episode)
    loaded = {episode.id: episode for episode in await knowledge.load_episodes()}

    assert episode_ran_in_plan_mode(loaded["ep-plan"]) is True
    assert episode_ran_in_plan_mode(loaded["ep-work"]) is False


# ── 2. the producers ────────────────────────────────────────────────────────


async def test_a_plan_mode_episode_stores_the_reply_as_plan_mode_left_it(store: ChatThreadStore) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    _thread(store, "plan")

    shown, episode = await _reply_turn(store, memory, _LONG)
    outcome = episode.outcomes[0]

    # The Captain's text is A-3's: the reply, the unsent DM and the note shown, the notice last.
    assert shown.startswith(_PLAN) and shown.endswith(f"\n\n{_NOTICE}")
    assert _DM in shown and "Record the SEC-CHARLIE baseline." in shown and "[NOTEBOOK" not in shown
    # The episode keeps HEAD's keys and adds the marker; its text is the reply as
    # the passes left it, cut so the notice is whole, and nothing held back.
    assert list(outcome) == [*_HEAD_OUTCOME_KEYS, EPISODE_PLAN_MODE_KEY]
    assert (outcome["success"], outcome[EPISODE_PLAN_MODE_KEY]) == (True, True)
    assert outcome["response"] == f"{_PLAN[:500 - len(_NOTICE) - 2].rstrip()}\n\n{_NOTICE}"
    assert len(outcome["response"]) <= 500
    assert "SEC-BRAVO" not in outcome["response"] and "SEC-CHARLIE" not in outcome["response"]


async def test_a_short_plan_mode_reply_is_stored_whole_with_the_notice(store: ChatThreadStore) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    _thread(store, "plan")

    _, episode = await _reply_turn(store, memory, _SHORT)

    assert episode.outcomes[0]["response"] == f"{_SHORT_PLAN}\n\n{_NOTICE}"


async def test_a_plan_mode_reply_that_held_nothing_is_marked_and_stored_as_written(
    store: ChatThreadStore,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    _thread(store, "plan")
    text = "Here is the plan. Step 1: read the figures."

    shown, episode = await _reply_turn(store, memory, text)

    assert shown == text
    assert episode.outcomes[0]["response"] == text
    assert episode.outcomes[0][EPISODE_PLAN_MODE_KEY] is True


def _held_gate(**held: int) -> PlanModeReplyGate:
    gate = PlanModeReplyGate(None, "t-1", TurnAgentMode(mode="plan", record=None), agent_id=_AGENT)
    for kind, count in held.items():
        gate.record(kind, count)
    return gate


def _episode_text(reply: str, gate: PlanModeReplyGate) -> str:
    ctx = DmReplyContext(
        runtime=SimpleNamespace(), agent=None, agent_id=_AGENT, callsign=None, req_message="",
        reply=DmReply(body=reply), has_image_attachment=False, per_attachment=[], sanity_gate=None,
        params={}, message_text="", sampling_state=None, avatar_event_bus=None, plan_mode_gate=gate,
    )
    return reply_pipeline_module._plan_mode_episode_response(ctx, gate)


def test_the_notice_stays_whole_when_every_kind_is_held() -> None:
    gate = _held_gate(**{kind: 12 for kind in (
        "create_task", "dm", "challenge", "action", "move", "image", "follow_up", "notebook", "todos",
    )})
    notice = gate.notice()

    stored = _episode_text("x" * 1000, gate)

    assert stored.endswith(f"\n\n{notice}") and stored.startswith("x") and len(stored) == 500


def test_a_notice_longer_than_the_bound_is_cut_to_it() -> None:
    # A-5 repoint (was ``..._is_stored_whole_without_the_reply``, which pinned a stored
    # text past the bound as expected -- the review's Low): the text never exceeds 500
    # characters, so a notice that alone would not fit is cut to them. Only a held
    # count of 23 digits or more makes a notice that long.
    # A-6 repoint (A-5 pinned ``stored == gate.notice()[:500]``, a cut of the notice's
    # end that lost its clause -- the round-5 review's Low): the list of what was held
    # is cut instead, so the stored text keeps the bound and says none of it was sent.
    gate = _held_gate(dm=10 ** 480)

    # A reply longer than the notice's overrun, so a negative room would keep part of it.
    stored = _episode_text("x" * 5_000, gate)

    assert len(gate.notice()) > 500
    assert len(stored) == 500
    assert stored.startswith("(Plan mode held back 1000")
    assert stored.endswith(
        "...; none of it was sent, saved or started. Once this conversation is in "
        "execute mode, ask again.)"
    )


def test_a_bounded_notice_keeps_its_clause_and_cuts_only_the_list() -> None:
    clause = "; none of it was sent, saved or started. Once this conversation is in execute mode, ask again.)"
    short = _held_gate(dm=2)
    long = _held_gate(**{kind: 10 ** 40 for kind in (
        "create_task", "dm", "challenge", "action", "move", "image", "follow_up", "notebook", "todos",
    )})

    # A notice that fits is returned whole, and the notice the Captain is shown is never cut.
    assert short.notice(500) == short.notice()
    assert len(long.notice()) > 500
    for bound in (200, 300, 500):
        cut = long.notice(bound)
        assert len(cut) == bound
        assert cut.startswith("(Plan mode held back 10000") and cut.endswith("..." + clause)


async def test_a_projection_runs_only_the_passes_and_the_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    for name in sorted(reply_pipeline_module._PLAN_MODE_ALLOWED_STEPS - {"step_4p_plan_mode_notice"}):
        async def _step(self: Any, _name: str = name) -> None:
            ran.append(_name)

        _step.__name__ = name
        monkeypatch.setattr(DmReplyPipeline, name, _step)

    reply, stored = await project_plan_mode_reply(
        DmReply(body=_SHORT), runtime=SimpleNamespace(dm_sanity_gate=DmSanityGate()),
        agent_id=_AGENT, chat_thread_id="t-1", gate=_held_gate(),
    )

    assert ran == []
    assert reply.body.startswith(_SHORT_PLAN) and reply.body.endswith(f"\n\n{_NOTICE}") and _DM in reply.body
    assert stored == f"{_SHORT_PLAN}\n\n{_NOTICE}"


@pytest.mark.parametrize(("modes", "mode"), [(True, "execute"), (False, "plan")], ids=["execute", "modes-off"])
async def test_outside_plan_mode_the_episode_is_heads_key_for_key(
    store: ChatThreadStore, modes: bool, mode: str,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    _thread(store, mode)

    shown, episode = await _reply_turn(store, memory, _LONG, modes=modes)
    outcome = episode.outcomes[0]

    assert list(outcome) == _HEAD_OUTCOME_KEYS
    assert outcome["response"] == shown[:500]
    assert episode_ran_in_plan_mode(episode) is False


async def test_the_agent_marks_its_own_record_of_a_plan_mode_turn_and_asks_for_a_plan_mode_report(
    store: ChatThreadStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = _thread(store, None, agent=_DM_AGENT)
    promoted: list[list[str]] = []

    async def _spy(work: Any, **kwargs: Any) -> str:
        promoted.append(sorted(kwargs))
        return await work()

    monkeypatch.setattr(turn_promotion, "run_with_promotion", _spy)

    async def _turn(cfg: DmAgenticConfig) -> Any:
        runtime = _runtime(_registry(_Tool("http_fetch")), _Grants(["http_fetch"]), cfg=cfg, store=store)
        observation = {"intent": "direct_message", "params": {"text": "Plan it."}, "thread_id": thread.id}
        agent = _dm_agent(runtime, _ScriptedLLM(["A plan."]))
        agent._promoted_turn_tasks = set()  # set by ``__init__``, which the harness skips
        await agent._decide_via_llm(observation)
        return observation.get("_plan_mode_turn"), promoted[-1]

    off = DmAgenticConfig(enabled=True, max_iterations=3, promote_to_task_after_seconds=30.0)
    on = DmAgenticConfig(
        enabled=True, max_iterations=3, promote_to_task_after_seconds=30.0, agent_modes_enabled=True,
    )
    legacy = await _turn(off)
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    planned = await _turn(on)
    off_with_a_plan_record = await _turn(off)
    store.set_agent_mode(thread.id, "execute", changed_by="captain")
    executed = await _turn(on)

    assert planned == (True, sorted([*legacy[1], "plan_mode"]))
    assert legacy[0] is None and "plan_mode" not in legacy[1]
    assert legacy == off_with_a_plan_record == executed


async def test_the_agents_own_record_carries_the_marker_only_for_a_plan_mode_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    monkeypatch.setattr("probos.crew_utils.is_crew_agent", lambda agent, ontology: True)
    agent = _dm_agent(SimpleNamespace(episodic_memory=memory, ontology=object()), None)
    intent = IntentMessage(
        intent="direct_message", params={"text": "Plan it.", "from": "channel"}, target_agent_id=_DM_AGENT,
    )

    for planned in (True, False):
        observation: dict[str, Any] = {"params": dict(intent.params)}
        if planned:
            observation["_plan_mode_turn"] = True
        await agent._store_action_episode(intent, observation, {"success": True, "result": "A plan."})
    marked, unmarked = sorted(await memory.recent(2), key=lambda e: episode_ran_in_plan_mode(e), reverse=True)

    assert marked.outcomes[0][EPISODE_PLAN_MODE_KEY] is True
    assert {**marked.outcomes[0]} == {**unmarked.outcomes[0], EPISODE_PLAN_MODE_KEY: True}
    assert EPISODE_PLAN_MODE_KEY not in unmarked.outcomes[0]


# ── 3. the consumer: dreaming ───────────────────────────────────────────────


@pytest.mark.parametrize(("mode", "weight"), [("plan", 0.0), ("execute", 0.09)])
async def test_micro_dream_learns_no_hebbian_weight_from_a_plan_mode_reply(
    store: ChatThreadStore, mode: str, weight: float,
) -> None:
    memory = await _conversation(store, mode)
    engine, router, _ = _engine(memory)
    [latest] = await memory.recent(1)

    report = await engine.micro_dream()

    assert report["episodes_replayed"] == 3
    assert router.get_weight("direct_message", latest.agent_ids[0], REL_INTENT) == pytest.approx(weight)


@pytest.mark.parametrize(("mode", "trust"), [("plan", None), ("execute", (2.1, 2.0))])
async def test_trust_consolidation_scores_no_plan_mode_reply(
    store: ChatThreadStore, mode: str, trust: tuple[float, float] | None,
) -> None:
    memory = await _conversation(store, mode)
    [latest] = await memory.recent(1)
    agent = latest.agent_ids[0]

    engine, _, network = _engine(memory)
    engine._consolidate_trust(await memory.recent(50))
    at_shutdown, router, shutdown_network = _engine(memory)
    await at_shutdown.consolidate_for_shutdown()

    assert _trust(network, agent) == trust
    assert _trust(shutdown_network, agent) == trust
    assert (router.get_weight("direct_message", agent, REL_INTENT) > 0.0) is (mode == "execute")


@pytest.mark.parametrize(
    ("mode", "pre_warm", "clusters"),
    [("plan", [], []), ("execute", ["direct_message"], [(3, True)])],
)
async def test_a_dream_cycle_neither_prewarms_nor_clusters_on_plan_mode_replies(
    store: ChatThreadStore, mode: str, pre_warm: list[str], clusters: list[tuple[int, bool]],
) -> None:
    memory = await _conversation(store, mode)
    memory.get_embeddings = _same_embeddings  # type: ignore[attr-defined]
    engine, _, _ = _engine(memory)

    await engine.dream_cycle()

    assert engine.pre_warm_intents == pre_warm
    assert [(len(c.episode_ids), c.is_success_dominant) for c in engine._last_clusters] == clusters


@pytest.mark.parametrize(("mode", "found"), [("plan", 0), ("execute", 1)])
async def test_contradiction_detection_passes_over_a_plan_mode_reply(
    store: ChatThreadStore, mode: str, found: int,
) -> None:
    memory = await _conversation(store, mode, turns=1)
    [stored] = await memory.recent(1)
    await memory.store(Episode(
        timestamp=stored.timestamp + 1.0, user_input=stored.user_input, agent_ids=list(stored.agent_ids),
        outcomes=[{"intent": "direct_message", "success": False}],
    ))
    resolved: list[Any] = []
    engine, _, _ = _engine(memory, contradiction_resolve_fn=resolved.extend)

    report = await engine.dream_cycle()

    assert (report.contradictions_found, len(resolved)) == (found, found)


class _Procedures:
    """The procedure store's evolution surface, for one degraded procedure."""

    def __init__(self, parent: Procedure) -> None:
        self.parent = parent

    async def list_active(self) -> list[dict[str, Any]]:
        return [{"id": self.parent.id}]

    async def get_quality_metrics(self, procedure_id: str) -> dict[str, Any]:
        return {"total_selections": 10, "fallback_rate": 1.0}

    async def get(self, procedure_id: str) -> Procedure:
        return self.parent


@pytest.mark.parametrize("with_work", [False, True], ids=["plan-only", "plan-and-work"])
async def test_procedure_evolution_recalls_no_plan_mode_reply(
    store: ChatThreadStore, monkeypatch: pytest.MonkeyPatch, with_work: bool,
) -> None:
    memory = await _conversation(store, "plan", turns=2)
    worked = Episode(
        timestamp=9_000.0, user_input="[1:1 with Ezri] Captain: Run it.", agent_ids=[_AGENT],
        outcomes=[{"intent": "direct_message", "success": True, "response": "Done."}],
    )
    if with_work:
        await memory.store(worked)
    evolved_from: list[list[str]] = []

    async def _evolve(parent: Any, diagnosis: str, metrics: Any, episodes: list[Any], llm: Any) -> None:
        evolved_from.append([episode.id for episode in episodes])

    monkeypatch.setattr(dreaming_module, "evolve_fix_procedure", _evolve)
    parent = Procedure(id="p-dm", name="Answer the Captain", intent_types=["direct_message"])
    engine, _, _ = _engine(memory, procedure_store=_Procedures(parent), llm_client=object())

    await engine._evolve_degraded_procedures([], [])

    assert len(await memory.recall_by_intent("direct_message")) == (3 if with_work else 2)
    assert evolved_from == ([[worked.id]] if with_work else [])


class _Activation:
    def __init__(self) -> None:
        self.batches: list[tuple[list[str], str]] = []

    async def record_batch_access(self, ids: list[str], access_type: str = "") -> None:
        self.batches.append((sorted(ids), access_type))


async def test_memory_upkeep_still_reinforces_plan_mode_replies(store: ChatThreadStore) -> None:
    memory = await _conversation(store, "plan", turns=2)
    tracker = _Activation()
    engine, router, _ = _engine(
        memory, config=_dream_config(activation_enabled=True), activation_tracker=tracker,
    )

    await engine.micro_dream()

    ids = sorted(episode.id for episode in await memory.recent(10))
    assert tracker.batches == [(ids, "dream_replay")]
    assert router.get_weight("direct_message", _AGENT, REL_INTENT) == 0.0


# ── 4. the bypasses ─────────────────────────────────────────────────────────


class _Bus:
    def __init__(self, text: str) -> None:
        self.text = text

    async def send(self, message: Any) -> IntentResult:
        return IntentResult(
            intent_id="i-1", agent_id=message.target_agent_id, success=True, result=self.text, metadata={},
        )


async def _replay(
    store: ChatThreadStore, *, modes: bool, floor: str | None, switch_to: str | None = None,
    hand_to: str | None = None,
) -> tuple[str, int]:
    """One held turn replayed by the real queue through the real finalize wiring. With
    ``hand_to`` (A-9), that agent takes the thread while the turn is held, and its own
    execute mode is set there, before the replay runs."""
    counting = _CountingStore(store)
    cfg = _config(modes=modes)
    runtime = SimpleNamespace(
        config=cfg, chat_thread_store=counting, intent_bus=_Bus(_LONG), dm_sanity_gate=DmSanityGate(),
        recreation_service=None,
        llm_client=SimpleNamespace(get_health_status=lambda: {"tiers": {"fast": {
            "status": "operational", "endpoint_cooldown_remaining_seconds": 0.0,
        }}}),
    )
    thread = _thread(store, None)
    assert _wire_deferred_turns(runtime=runtime, config=cfg)
    queue = runtime.deferred_turn_queue
    try:
        params: dict[str, Any] = {"text": "Plan the quarterly report.", "from": "hxi_profile"}
        if floor is not None:
            params[AGENT_MODE_FLOOR_PARAM] = floor
        assert queue.offer(thread_id=thread.id, agent_id=_AGENT, params=params)
        if switch_to is not None:
            store.set_agent_mode(thread.id, switch_to, changed_by="captain")
        if hand_to is not None:
            store.add_participant(thread.id, hand_to)
            store.remove_participant(thread.id, _AGENT)
            store.set_agent_mode(thread.id, "execute", changed_by="captain", expected_participant=hand_to)
        counting.reads = 0
        assert await queue.drain_once() == 1
    finally:
        await queue.stop()
    [row] = [
        m for m in store.list_messages(thread.id, limit=20, newest=True)
        if (m.metadata or {}).get("source") == "deferred_turn"
    ]
    prefix = _ANSWER_PREFIX.format(ago="a moment ago")
    assert row.body.startswith(prefix)
    return row.body[len(prefix):], counting.reads


async def _route_plan_mode_text(tmp_path: Path) -> str:
    """The route's plan-mode reply for the same text, on a thread of its own."""
    other = ChatThreadStore(tmp_path / "route.db")
    _thread(other, "plan")
    shown, _ = await _reply_turn(other, MockEpisodicMemory(relevance_threshold=0.3), _LONG)
    return compose_bypass_reply(shown)


@pytest.mark.parametrize("switch_to", [None, "execute"], ids=["plan-thread", "execute-since-it-was-held"])
async def test_a_replayed_plan_mode_turn_is_posted_as_the_route_shows_a_plan_mode_reply(
    store: ChatThreadStore, tmp_path: Path, switch_to: str | None,
) -> None:
    _thread(store, "plan")

    posted, _ = await _replay(store, modes=True, floor="plan", switch_to=switch_to)

    assert posted == await _route_plan_mode_text(tmp_path)
    assert posted.endswith(f"\n\n{_NOTICE}") and posted.count(_DM) == 1 and "[NOTEBOOK" not in posted


@pytest.mark.parametrize(
    ("modes", "mode", "floor", "reads"),
    [(False, "plan", "plan", 0), (True, "execute", None, 2)],
    ids=["modes-off-with-a-plan-record-and-floor", "execute"],
)
async def test_outside_plan_mode_the_replay_posts_what_it_posted_before(
    store: ChatThreadStore, modes: bool, mode: str, floor: str | None, reads: int,
) -> None:
    _thread(store, mode)

    posted, thread_reads = await _replay(store, modes=modes, floor=floor)

    assert posted == compose_bypass_reply(str(DmReply(body=_LONG).render()))
    assert thread_reads == reads


async def test_a_replay_is_held_when_its_thread_changed_hands_while_the_turn_was_held(
    store: ChatThreadStore, tmp_path: Path,
) -> None:
    # A-9: the route held the turn outside plan mode (no floor); while it was held another
    # agent took the thread and its own execute mode was set there. The staged candidate's
    # replay gate read that record for the held turn and posted the answer as it came.
    posted, _ = await _replay(store, modes=True, floor=None, hand_to="science-dax")

    # The premise: the thread is the other agent's now, with its own execute record.
    taken = store.find_default_for_agent("science-dax")
    assert (taken.metadata["agent_mode"]["mode"], taken.metadata["agent_mode"]["agent_id"]) == (
        "execute", "science-dax",
    )
    # The replay's gate reads for the held turn's agent: held, so the answer is posted as
    # plan mode leaves a reply -- the held requests taken out, and the notice.
    assert posted.endswith(f"\n\n{_NOTICE}") and posted.count(_DM) == 1 and "[NOTEBOOK" not in posted
    assert posted == await _route_plan_mode_text(tmp_path)


def test_the_replay_gate_opens_only_with_modes_the_loop_and_a_store(store: ChatThreadStore) -> None:
    thread = _thread(store, "execute")
    on = SimpleNamespace(config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=True, agent_modes_enabled=True)))
    no_loop = SimpleNamespace(config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=False, agent_modes_enabled=True)))
    off = SimpleNamespace(config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=True)))

    assert open_plan_mode_replay_gate(off, store, thread.id, "plan", agent_id=_AGENT) is None
    assert open_plan_mode_replay_gate(no_loop, store, thread.id, "plan", agent_id=_AGENT) is None
    assert open_plan_mode_replay_gate(on, None, thread.id, "plan", agent_id=_AGENT) is None
    floored = open_plan_mode_replay_gate(on, store, thread.id, "plan", agent_id=_AGENT)
    unfloored = open_plan_mode_replay_gate(on, store, thread.id, None, agent_id=_AGENT)
    assert floored is not None and floored.planned_at_dispatch and floored.withholds()
    assert unfloored is not None and not unfloored.planned_at_dispatch and not unfloored.withholds()


async def test_a_projection_through_a_gate_that_holds_nothing_changes_nothing() -> None:
    gate = PlanModeReplyGate(None, "t-1", None, agent_id=_AGENT)

    reply, stored = await project_plan_mode_reply(
        DmReply(body=_LONG), runtime=SimpleNamespace(dm_sanity_gate=DmSanityGate()),
        agent_id=_AGENT, chat_thread_id="t-1", gate=gate,
    )

    assert (reply.body, stored) == (_LONG, _LONG[:500])


async def _promoted(
    store: ChatThreadStore, memory: MockEpisodicMemory, *, plan: bool, fail: bool = False,
) -> str:
    """One run promoted by the real ``run_with_promotion``; returns the report posted."""
    items = WorkItemStore(db_path=":memory:")
    await items.start()
    runtime = SimpleNamespace(
        config=_config(), work_item_store=items, chat_thread_store=store, episodic_memory=memory,
        registry=None, dm_sanity_gate=DmSanityGate(), event_log=None, recreation_service=None,
    )
    thread = _thread(store, None)
    before = {m.id for m in store.list_messages(thread.id, limit=50, newest=True)}

    async def _work() -> str:
        await asyncio.sleep(0.05)
        if fail:
            raise RuntimeError("the run failed")
        return _LONG

    hold: set[Any] = set()
    try:
        await turn_promotion.run_with_promotion(
            _work, promote_after_seconds=0.01, runtime=runtime, agent_id=_AGENT, thread_id=thread.id,
            request_text="Plan the quarterly report.", hold=hold, **({"plan_mode": True} if plan else {}),
        )
        for _ in range(20):
            if not hold:
                break
            await asyncio.gather(*list(hold), return_exceptions=True)
    finally:
        await items.stop()
    [report] = [
        m.body for m in store.list_messages(thread.id, limit=50, newest=True)
        if m.role == "agent" and m.id not in before
    ]
    return report


async def test_a_promoted_plan_mode_run_reports_as_plan_mode_leaves_a_reply(
    store: ChatThreadStore, tmp_path: Path,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    _thread(store, "plan")

    report = await _promoted(store, memory, plan=True)
    [episode] = await memory.recent(1)
    outcome = episode.outcomes[0]

    assert report == await _route_plan_mode_text(tmp_path)
    assert (outcome["success"], outcome["complete"], outcome[EPISODE_PLAN_MODE_KEY]) == (True, True, True)
    assert outcome["response"] == f"{_PLAN[:500 - len(_NOTICE) - 2].rstrip()}\n\n{_NOTICE}"
    # The passes and the notice ran on the text alone: no pipeline step stored
    # an episode of its own.
    assert [e.user_input for e in await memory.recent(10)] == [
        "[1:1 background task] Captain: Plan the quarterly report.",
    ]


async def test_a_promoted_run_outside_plan_mode_reports_and_is_stored_as_before(store: ChatThreadStore) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)

    report = await _promoted(store, memory, plan=False)
    [episode] = await memory.recent(1)

    assert report == compose_bypass_reply(_LONG)
    assert episode.outcomes[0] == {
        "intent": "direct_message", "success": True, "complete": True, "response": report[:500],
        "session_type": "1:1", "source": turn_promotion.PROMOTION_SOURCE,
        "work_item_id": episode.outcomes[0]["work_item_id"],
    }


@pytest.mark.parametrize(("plan", "trust"), [(True, None), (False, (2.0, 2.1))])
async def test_a_failed_plan_mode_run_is_marked_and_not_scored_for_trust(
    store: ChatThreadStore, plan: bool, trust: tuple[float, float] | None,
) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)

    reports = [await _promoted(store, memory, plan=plan, fail=True) for _ in range(2)]
    episodes = await memory.recent(10)
    engine, _, network = _engine(memory)
    engine._consolidate_trust(episodes)

    assert reports == [turn_promotion._REPORT_FAILED] * 2
    assert [(e.outcomes[0]["success"], episode_ran_in_plan_mode(e)) for e in episodes] == [(False, plan)] * 2
    assert _trust(network, episodes[0].agent_ids[0]) == trust


@pytest.mark.parametrize("plan", [True, False])
async def test_an_expired_promoted_run_is_marked_when_it_ran_in_plan_mode(plan: bool) -> None:
    memory = MockEpisodicMemory(relevance_threshold=0.3)
    runtime = SimpleNamespace(episodic_memory=memory, work_item_store=None, config=_config())

    await turn_promotion._close_expired_unconfirmed_turn(
        runtime=runtime, agent_id=_AGENT, thread_id="t-1", work_item_id="wi-1",
        request_text="Plan the quarterly report.", grace_seconds=1.0, **({"plan_mode": True} if plan else {}),
    )
    [episode] = await memory.recent(1)

    assert episode.outcomes[0]["success"] is False
    assert episode_ran_in_plan_mode(episode) is plan
    assert episode.outcomes[0]["response"] == turn_promotion._REPORT_ABANDON_UNCONFIRMED[:500]


@pytest.mark.parametrize("plan", [True, False])
async def test_the_reporter_hands_the_plan_flag_to_a_run_that_outlived_its_grace(
    monkeypatch: pytest.MonkeyPatch, plan: bool,
) -> None:
    ended: list[dict[str, Any]] = []

    async def _ended(**kwargs: Any) -> None:
        ended.append(kwargs)

    class _Unconfirmed:
        async def result(self) -> str:
            raise turn_promotion._RunAbandoned(elapsed=1.0, stopped=False)

    monkeypatch.setattr(turn_promotion, "_close_expired_unconfirmed_turn", _ended)
    run = asyncio.create_task(asyncio.sleep(30))
    try:
        await turn_promotion._finish_promoted_turn(
            run, runtime=SimpleNamespace(work_item_store=None), agent_id=_AGENT, thread_id="t-1",
            work_item_id="wi-1", request_text="Plan it.", supervisor=_Unconfirmed(),
            unconfirmed_grace_seconds=0.01, **({"plan_mode": True} if plan else {}),
        )
    finally:
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)

    assert [call["plan_mode"] for call in ended] == [plan]


# ── 5. the censuses ─────────────────────────────────────────────────────────


def _functions(module: Any) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(ast.parse(inspect.getsource(module)))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        call for call in ast.walk(node)
        if isinstance(call, ast.Call) and (
            (isinstance(call.func, ast.Name) and call.func.id == name)
            or (isinstance(call.func, ast.Attribute) and call.func.attr == name)
        )
    ]


def test_every_outcome_learner_in_dreaming_reads_through_the_filter() -> None:
    """A dream step that learns from what an outcome says was done reads
    ``_outcome_evidence``; the memory steps read the whole window. A new learner
    fails here until it is placed on one side or the other."""
    functions = {fn.name: fn for fn in _functions(dreaming_module)}
    filtered = sorted(name for name, fn in functions.items() if _calls(fn, "_outcome_evidence"))

    assert filtered == [
        "_compute_pre_warm", "_consolidate_trust", "_recall_evidence_by_intent", "_replay_episodes", "dream_cycle",
    ]
    cycle = functions["dream_cycle"]
    [contradictions] = _calls(cycle, "detect_contradictions")
    assert _calls(contradictions.args[0], "_outcome_evidence")
    [grouping] = [
        loop for loop in ast.walk(cycle)
        if isinstance(loop, ast.For) and _calls(loop.iter, "_outcome_evidence")
    ]
    assert any(
        isinstance(target, ast.Name) and target.id == "primary_intent"
        for node in ast.walk(grouping) if isinstance(node, ast.Assign) for target in node.targets
    )
    assert sorted(name for name, fn in functions.items() if _calls(fn, "recall_by_intent")) == [
        "_recall_evidence_by_intent",
    ]
    assert sorted(name for name, fn in functions.items() if _calls(fn, "_recall_evidence_by_intent")) == [
        "_attempt_procedure_evolution", "_evolve_degraded_procedures", "_process_fallback_learning",
    ]


def test_every_direct_message_episode_a_plan_mode_turn_can_write_is_classified() -> None:
    """Every outcome in ``src`` built as ``"intent": "direct_message"``. A function
    that builds one and constructs an ``Episode`` writes a direct-message turn's
    episode, and carries the marker, unless its turn cannot run in plan mode: only a
    group turn is let off, because it sends ``is_group_chat`` and a group turn never
    reads a mode. The federation payload is not an episode. A new producer fails here
    until it is marked or shown to be a group turn's. A-5 repoint: A-4 let the CLI
    ``/session`` off as recorded (F-38) although plan mode can govern its turn; an
    unmarked producer outside a group turn now fails, and the session is marked. The
    agent's own record (AD-430c) builds its intent from the turn and is proven above."""
    root = Path(dreaming_module.__file__).resolve().parents[1]
    builders: dict[tuple[str, str], ast.AST] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "intent"
                and isinstance(v, ast.Constant) and v.value == "direct_message"
                for k, v in zip(node.keys, node.values)
            ):
                owner: ast.AST = node
                while not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = parents[owner]
                builders[(path.relative_to(root).as_posix(), owner.name)] = owner
    producers = {key for key, fn in builders.items() if _calls(fn, "Episode")}
    marked = {
        key for key in producers
        if any(isinstance(n, ast.Name) and n.id == "EPISODE_PLAN_MODE_KEY" for n in ast.walk(builders[key]))
    }
    group_turns = {
        key for key in producers
        if any(
            isinstance(n, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "is_group_chat"
                and isinstance(v, ast.Constant) and v.value is True
                for k, v in zip(n.keys, n.values)
            )
            for n in ast.walk(builders[key])
        )
    }
    fanout = ("routers/thread_fanout.py", "_fan_one_round")
    on = SimpleNamespace(config=SimpleNamespace(dm_agentic=DmAgenticConfig(enabled=True, agent_modes_enabled=True)))

    assert set(builders) == {
        ("cognitive/dm/reply_pipeline.py", "step_5_episodic_store"),
        ("cognitive/turn_promotion.py", "_store_promoted_episode"),
        ("experience/commands/session.py", "handle_message"),
        fanout,
        ("federation/bridge.py", "forward_direct_message"),
    }
    assert set(builders) - producers == {("federation/bridge.py", "forward_direct_message")}
    assert producers - marked == {fanout} and fanout in group_turns
    # A group turn never reads a mode: the loop that reads it refuses the turn.
    will_run = CognitiveAgent._conversational_agentic_will_run
    assert will_run(SimpleNamespace(_runtime=on), {"intent": "direct_message", "params": {}}) is True
    assert will_run(
        SimpleNamespace(_runtime=on), {"intent": "direct_message", "params": {"is_group_chat": True}},
    ) is False
