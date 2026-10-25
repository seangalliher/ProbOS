"""BF-924 (#1654) M1: the AD-535/536 procedure-compilation clamp reads the agent's live trust.

The clamp and the promotion step read ``getattr(self, "_trust_score", 0.5)``, which nothing assigns,
so every agent counted as a Lieutenant. Each test drives the clamp through its production caller
(``decide`` or ``handle_intent``) on a real ``CognitiveAgent`` whose runtime carries a real
``TrustNetwork``.
"""

from __future__ import annotations

import asyncio
import logging
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.llm_client import BaseLLMClient, MockLLMClient
from probos.cognitive.procedure_store import ProcedureStore
from probos.config import COMPILATION_PROMOTION_THRESHOLD, DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.types import LLMRequest, LLMResponse, Priority
from tests.test_fallback_learning import _make_cognitive_agent as _make_lifecycle_agent
from tests.test_fallback_learning import _make_dreaming_engine, _make_intent, _make_procedure
from tests.test_fallback_learning import _make_store_mock as _make_lifecycle_store
from tests.test_replay_dispatch import (
    ReplayTestAgent,
    _make_runtime_with_store,
    _make_store_mock,
    _MockProcedure,
)


def trust_network_at(agent_id: str, score: float) -> TrustNetwork:
    """A real ``TrustNetwork`` in which ``agent_id`` holds trust ``score`` (a Beta prior of weight 10).

    Shared with ``test_graduated_compilation.py`` and ``test_level_5_dispatch.py`` (BF-924), whose
    agents reached the clamp through a hand-set ``_trust_score`` that production never sets.
    """
    network = TrustNetwork()
    alpha = 10.0 * score
    network.create_with_prior(agent_id, alpha=alpha, beta=10.0 - alpha)
    return network


class _UnreadableTrustNetwork:
    """Stands in for a failing trust store: ``get_score`` is the only method the clamp calls."""

    def get_score(self, agent_id: str) -> float:
        raise RuntimeError("trust store unavailable")


_OBSERVATION = {"intent": "test_intent", "params": {"message": "do it"}}


@pytest.fixture(autouse=True)
def _clear_decision_caches():
    from probos.cognitive.cognitive_agent import _CACHE_HITS, _CACHE_MISSES, _DECISION_CACHES

    _DECISION_CACHES.clear()
    _CACHE_HITS.clear()
    _CACHE_MISSES.clear()


def _level_4_runtime() -> MagicMock:
    """A runtime whose procedure store matches one stored Level 4 procedure."""
    proc = _MockProcedure(id="proc-bf924", name="Handle test task", compilation_level=4)
    store = _make_store_mock(
        find_result=[{"id": proc.id, "name": proc.name, "score": 0.9}],
        get_result=proc,
    )
    return _make_runtime_with_store(store)


@pytest.mark.asyncio
async def test_an_ensign_runs_a_stored_level_4_procedure_as_guided() -> None:
    """An Ensign (trust 0.3) is held to Level 2: the LLM runs with the procedure as hints."""
    llm = MockLLMClient()
    rt = _level_4_runtime()
    agent = ReplayTestAgent(llm_client=llm, runtime=rt)
    rt.trust_network = trust_network_at(agent.id, 0.3)

    result = await agent.decide(dict(_OBSERVATION))

    assert result.get("guided_by_procedure") is True
    assert result.get("compilation_level") == 2
    assert result.get("procedure_id") == "proc-bf924"
    assert result.get("cached") is not True
    assert llm.call_count >= 1


@pytest.mark.asyncio
async def test_a_lieutenant_still_replays_a_stored_level_4_procedure() -> None:
    """The premise: at trust 0.5 the clamp allows Level 4, a zero-token replay, as before."""
    llm = MockLLMClient()
    rt = _level_4_runtime()
    agent = ReplayTestAgent(llm_client=llm, runtime=rt)
    rt.trust_network = trust_network_at(agent.id, 0.5)

    result = await agent.decide(dict(_OBSERVATION))

    assert result.get("cached") is True
    assert result.get("procedure_id") == "proc-bf924"
    assert llm.call_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("trust_network", [_UnreadableTrustNetwork(), None], ids=["raises", "absent"])
async def test_an_unreadable_trust_is_held_to_level_2_and_warned(trust_network, caplog) -> None:
    """Fail closed: an unknown trust takes the Ensign cap and says so at WARNING."""
    rt = _level_4_runtime()
    agent = ReplayTestAgent(llm_client=MockLLMClient(), runtime=rt)
    rt.trust_network = trust_network
    # Spy on the Level 2 builder: it replaces only the Guided LLM call, so the clamp's is the only trust read.
    guided = AsyncMock(return_value={
        "action": "execute", "guided_by_procedure": True, "procedure_id": "proc-bf924", "compilation_level": 2,
    })

    with patch.object(agent, "_build_guided_decision", guided), caplog.at_level(
        logging.WARNING, logger="probos.cognitive.cognitive_agent",
    ):
        result = await agent.decide(dict(_OBSERVATION))

    guided.assert_awaited_once()
    assert guided.await_args.args[0].id == "proc-bf924"
    assert result.get("cached") is not True
    assert any(
        record.levelno == logging.WARNING and "BF-924" in record.getMessage() for record in caplog.records
    )


def _lifecycle_runtime(store: AsyncMock, agent_id: str, score: float) -> MagicMock:
    runtime = MagicMock()
    runtime.procedure_store = store
    runtime.cognitive_journal = None
    runtime.emit_event = MagicMock()
    runtime.trust_network = trust_network_at(agent_id, score)
    return runtime


async def _handle_once(agent):
    with patch.object(
        agent, "_recall_relevant_memories", new_callable=AsyncMock,
        return_value={"intent": "test_intent", "params": {"message": "test query"}},
    ), patch.object(agent, "_store_action_episode", new_callable=AsyncMock):
        return await agent.handle_intent(_make_intent())


@pytest.mark.asyncio
async def test_a_commanders_approved_procedure_is_promoted_to_level_5() -> None:
    """AD-536's Level 5 path, unreachable while every agent counted as 0.5."""
    agent = _make_lifecycle_agent()
    proc = _make_procedure(compilation_level=4)
    store = _make_lifecycle_store()
    store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
    store.get.return_value = proc
    store.record_consecutive_success.return_value = COMPILATION_PROMOTION_THRESHOLD
    store.get_promotion_status = AsyncMock(return_value="approved")
    agent._runtime = _lifecycle_runtime(store, agent.id, 0.8)

    result = await _handle_once(agent)

    assert result is not None and result.success is True
    store.promote_compilation_level.assert_awaited_once_with(proc.id, 5)


@pytest.mark.asyncio
async def test_an_ensigns_successes_do_not_promote_it_past_level_2() -> None:
    """An Ensign's Guided successes complete (premise) but no longer promote the procedure to Level 3."""
    agent = _make_lifecycle_agent(llm_client=MockLLMClient())
    proc = _make_procedure(compilation_level=2)
    store = _make_lifecycle_store()
    store.find_matching.side_effect = [[], [{"id": proc.id, "name": proc.name, "score": 0.9}]]
    store.get.return_value = proc
    store.record_consecutive_success.return_value = COMPILATION_PROMOTION_THRESHOLD
    agent._runtime = _lifecycle_runtime(store, agent.id, 0.3)

    result = await _handle_once(agent)

    assert result is not None and result.success is True
    store.record_completion.assert_awaited_once_with(proc.id)
    store.promote_compilation_level.assert_not_awaited()


# --- A2 (review round 1): a real ProcedureStore, the trust guard and the completion event ----------------


class _KnownMatchStore(ProcedureStore):
    """A real ``ProcedureStore`` whose semantic ranking is fixed: every active procedure matches at 0.9.

    Only ChromaDB is left out (``_init_chroma`` opens nothing, ``find_matching`` ranks from SQLite);
    persistence, ``get``, the counters, promotion and the promotion status are the real store's.
    """

    async def _init_chroma(self) -> None:
        return None

    async def find_matching(self, query, *, n_results=5, min_compilation_level=0, exclude_negative=True):
        if not exclude_negative:
            return []  # the negative-procedure check: no anti-pattern is stored
        entries = await self.list_active(min_compilation_level=min_compilation_level)
        return [{**entry, "score": 0.9} for entry in entries][:n_results]


async def _store_rig(tmp_path, score: float, level: int, *, approved: bool = False) -> SimpleNamespace:
    """A ``ReplayTestAgent`` at trust ``score`` whose runtime holds a real store with one procedure at ``level``."""
    store = _KnownMatchStore(tmp_path / "procedures")
    await store.start()
    proc = _make_procedure(id="proc-bf924-store", compilation_level=level)
    await store.save(proc)
    if approved:
        await store.approve_promotion(proc.id, "captain", "directive-bf924")
    events: list[tuple] = []
    runtime = SimpleNamespace(
        procedure_store=store, trust_network=TrustNetwork(), cognitive_journal=None, episodic_memory=None,
        emit_event=lambda *args, **kwargs: events.append(args),
        ward_room=SimpleNamespace(
            get_or_create_dm_channel=AsyncMock(return_value=SimpleNamespace(id="dm-bf924")),
            create_thread=AsyncMock(),
        ),
    )
    llm = MockLLMClient()
    agent = ReplayTestAgent(llm_client=llm, runtime=runtime)
    runtime.trust_network = trust_network_at(agent.id, score)
    return SimpleNamespace(store=store, proc=proc, agent=agent, runtime=runtime, llm=llm, events=events)


async def _handle_on_store(agent, *, succeed: bool = True):
    """One matched intent through ``handle_intent``; ``succeed=False`` makes the action fail and skips the recovery."""
    intent = _make_intent(target_agent_id=agent.id)
    with patch.object(
        agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda _intent, observation: observation),
    ), patch.object(agent, "_store_action_episode", new=AsyncMock()):
        if succeed:
            return await agent.handle_intent(intent)
        with patch.object(agent, "act", new=AsyncMock(return_value={"success": False, "error": "chosen failure"})), \
                patch.object(agent, "_run_llm_fallback", new=AsyncMock(return_value=None)):
            return await agent.handle_intent(intent)


class _FixedScoreTrustNetwork:
    """Returns one score for every agent: a Beta mean is never infinite, so an infinity can only come from a double."""

    def __init__(self, score: float) -> None:
        self._score = score

    def get_score(self, agent_id: str) -> float:
        return self._score


class _RuntimeWithUnreadableTrustNetwork:
    """A runtime whose ``trust_network`` attribute read raises; every other attribute is the wrapped runtime's."""

    def __init__(self, inner: SimpleNamespace) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    @property
    def trust_network(self):
        raise RuntimeError("trust network unavailable")


def _warned(caplog) -> bool:
    return any(record.levelno == logging.WARNING and "BF-924" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [float("nan"), 2.0, math.inf], ids=["nan", "above-one", "inf"])
async def test_a_trust_that_is_not_a_score_is_held_to_level_2_and_warned(tmp_path, score, caplog) -> None:
    """Finding 3 (review round 1): NaN failed both comparisons and took the Level 4 cap; 2.0 and infinity passed."""
    r = await _store_rig(tmp_path, 0.5, 4)
    try:
        # A real TrustNetwork holds the finite cases (a corrupt Beta record); a Beta mean is never infinite.
        r.runtime.trust_network = (
            _FixedScoreTrustNetwork(score) if math.isinf(score) else trust_network_at(r.agent.id, score)
        )
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert decision.get("guided_by_procedure") is True
        assert decision.get("compilation_level") == 2
        assert decision.get("cached") is not True
        assert _warned(caplog)
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_an_infinite_trust_does_not_promote_an_approved_procedure_to_level_5(tmp_path) -> None:
    """Finding 3 (review round 1): ``inf >= TRUST_COMMANDER`` promoted an approved Level 4 procedure to Level 5."""
    r = await _store_rig(tmp_path, 0.8, 4, approved=True)
    try:
        r.runtime.trust_network = _FixedScoreTrustNetwork(math.inf)
        results = [await _handle_on_store(r.agent) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]

        assert all(result is not None and result.success is True for result in results)  # premise: the step ran
        assert [entry["compilation_level"] for entry in await r.store.list_active()] == [4]
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_runtime_whose_trust_network_cannot_be_read_is_held_to_level_2_and_warned(tmp_path, caplog) -> None:
    """Finding 4 (review round 1): the attribute was read before the ``try``, so its failure failed ``decide``."""
    r = await _store_rig(tmp_path, 0.6, 4)
    try:
        r.agent._runtime = _RuntimeWithUnreadableTrustNetwork(r.runtime)
        with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert decision.get("guided_by_procedure") is True
        assert decision.get("cached") is not True
        assert _warned(caplog)
    finally:
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "stored_level", "used_procedure", "attempts"),
    [(0.3, 4, False, 1), (0.5, 2, False, 1), (0.5, 4, True, 0)],
    ids=["ensign-clamped-to-guided", "lieutenant-stored-guided", "lieutenant-replay"],
)
async def test_a_clamped_guided_run_reaches_the_reactive_trigger_as_a_stored_level_2_run_does(
    tmp_path, score, stored_level, used_procedure, attempts,
) -> None:
    """D9 (review round 1, finding 1): AD-532e's reactive check takes a Guided run, clamped or stored, as an LLM run.

    The completion event reports ``used_procedure`` from ``cached`` (AD-532e), and a Guided decision is not cached
    because the LLM ran (AD-535). Producer and consumer are real; the store is real but for its ranking.
    """
    r = await _store_rig(tmp_path, score, stored_level)
    try:
        # Degraded (effective rate 0.4) yet above the dispatch gate (0.3), so the reactive check diagnoses it.
        for n in range(10):
            await r.store.record_selection(r.proc.id)
            await r.store.record_applied(r.proc.id)
            await (r.store.record_completion if n < 4 else r.store.record_fallback)(r.proc.id)

        result = await _handle_on_store(r.agent)
        assert result is not None and result.success is True
        payloads = [args[1] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE]
        assert len(payloads) == 1  # premise: the real lifecycle emitted one completion

        engine = _make_dreaming_engine(procedure_store=r.store, llm_client=MockLLMClient())
        # Never reached: the mock's confirmation is not YES, so the attempt stops at the gate (review round 2 measured
        # one confirmation call and no recall). Kept so that a YES would still find no evidence.
        engine.episodic_memory.recall_by_intent = AsyncMock(return_value=[])
        attempt = AsyncMock(wraps=engine._attempt_procedure_evolution)
        engine._attempt_procedure_evolution = attempt
        await engine.on_task_execution_complete(payloads[0])

        assert payloads[0]["used_procedure"] is used_procedure
        assert attempt.await_count == attempts
    finally:
        await r.store.stop()


# --- A3 (review round 2): the evolution window and Records off (A7: Level 3 validation and the promotion request are slice 2's) ---


class _ConfirmationLLM(BaseLLMClient):
    """A real ``BaseLLMClient`` that answers NO; with ``hold`` each call stays in flight until ``release`` is set."""

    def __init__(self, *, hold: bool = False) -> None:
        self.requests: list[LLMRequest] = []
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        await self.release.wait()
        return LLMResponse(content="NO")

    def confirmations(self) -> int:
        """AD-532e's confirmation gate calls (``confirm_evolution_with_llm``'s question), not evolution rewrites."""
        return sum("Should this procedure be evolved?" in request.prompt for request in self.requests)


def _constructed_dreaming_engine(r, llm: BaseLLMClient) -> DreamingEngine:
    """A ``DreamingEngine`` built by its constructor alone: startup leaves it so when Ship's Records is disabled."""
    return DreamingEngine(
        router=SimpleNamespace(), trust_network=r.runtime.trust_network,
        episodic_memory=SimpleNamespace(recall_by_intent=AsyncMock(return_value=[])),
        config=DreamingConfig(), llm_client=llm, procedure_store=r.store,
    )


async def _degrade(r) -> None:
    """Effective rate 0.4 over 10 selections: unhealthy for AD-534, yet above the dispatch gate (0.3)."""
    for n in range(10):
        await r.store.record_selection(r.proc.id)
        await r.store.record_applied(r.proc.id)
        await (r.store.record_completion if n < 4 else r.store.record_fallback)(r.proc.id)


async def _guided_completion(r, agent) -> dict:
    """One successful run through ``handle_intent``; returns its ``TASK_EXECUTION_COMPLETE`` payload."""
    result = await _handle_on_store(agent)
    assert result is not None and result.success is True
    return [args[1] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE][-1]


def _hold_first_load(store):
    """Holds the first ``store.get`` (a dream step's parent load) until released; later loads pass through."""
    original = store.get
    entered, release = asyncio.Event(), asyncio.Event()
    loads = 0

    async def get(procedure_id):
        nonlocal loads
        loads += 1
        if loads == 1:
            entered.set()
            await release.wait()
        return await original(procedure_id)

    return get, entered, release


@pytest.mark.asyncio
async def test_overlapping_completions_of_one_procedure_make_one_evolution_attempt(tmp_path) -> None:
    """Finding 2 (review round 2): the 72 h window was checked before the confirmation ``await`` and recorded after
    it, so two agents' overlapping completions both passed it (two confirmation calls; ``runtime.py:1987`` runs
    each listener as its own task). E9's bound is now enforced."""
    r = await _store_rig(tmp_path, 0.3, 4)
    try:
        await _degrade(r)
        second = ReplayTestAgent(llm_client=MockLLMClient(), runtime=r.runtime)
        r.runtime.trust_network.create_with_prior(second.id, alpha=3.0, beta=7.0)
        payloads = [await _guided_completion(r, r.agent), await _guided_completion(r, second)]
        assert {payload["agent_id"] for payload in payloads} == {r.agent.id, second.id}  # premise: two cooldowns
        llm = _ConfirmationLLM(hold=True)
        engine = _constructed_dreaming_engine(r, llm)

        tasks = [asyncio.create_task(engine.on_task_execution_complete(payload)) for payload in payloads]

        async def settled() -> None:  # one attempt in flight and the other refused, or both in flight
            while not (sum(task.done() for task in tasks) >= 1 or llm.confirmations() == 2):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(settled(), timeout=10)
        llm.release.set()
        await asyncio.gather(*tasks)

        assert llm.confirmations() == 1
    finally:
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("step", ["7b", "7d"])
async def test_a_completion_during_a_dream_step_does_not_attempt_the_procedure_again(tmp_path, step) -> None:
    """Finding 2 (review round 2): Step 7b (``_evolve_degraded_procedures``) and Step 7d
    (``_process_fallback_learning``) checked the window, then awaited the parent load before recording it, so a
    completion delivered meanwhile passed the same check. They now claim it first, as the reactive path does."""
    r = await _store_rig(tmp_path, 0.3, 4)
    try:
        await _degrade(r)
        payload = await _guided_completion(r, r.agent)
        llm = _ConfirmationLLM()
        engine = _constructed_dreaming_engine(r, llm)
        get, entered, release = _hold_first_load(r.store)
        with patch.object(r.store, "get", new=get):
            if step == "7b":
                dream = asyncio.create_task(engine._evolve_degraded_procedures([], []))
            else:
                await engine.on_procedure_fallback_learning({
                    "procedure_id": r.proc.id, "fallback_type": "execution_failure", "intent_type": "test_intent",
                    "llm_response": "recovered", "rejection_reason": "chosen failure", "correlation_id": "",
                })
                dream = asyncio.create_task(engine._process_fallback_learning())
            await asyncio.wait_for(entered.wait(), timeout=10)  # the dream step passed the window and is loading
            await engine.on_task_execution_complete(payload)
            release.set()
            await asyncio.wait_for(dream, timeout=10)

        assert llm.confirmations() == 0
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_fallback_reaches_step_7d_when_ships_records_is_disabled(tmp_path) -> None:
    """Finding 3 (review round 2): the fallback queue was created in ``set_records_store``, which startup skips when
    Ship's Records is disabled (``startup/finalize.py:5417-5418``), so a real fallback was dropped with
    ``AttributeError``. The engine here is built by its constructor alone, as startup leaves it then."""
    r = await _store_rig(tmp_path, 0.5, 4)
    try:
        intent = _make_intent(target_agent_id=r.agent.id)
        actions = AsyncMock(side_effect=[
            {"success": False, "error": "chosen replay failure"}, {"success": True, "result": "recovered"},
        ])
        with patch.object(
            r.agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda _intent, observation: observation),
        ), patch.object(r.agent, "_store_action_episode", new=AsyncMock()), \
                patch.object(r.agent, "act", new=actions), \
                patch.object(r.agent, "_run_llm_fallback", new=AsyncMock(return_value={"action": "execute", "llm_output": "recovered"})):
            result = await r.agent.handle_intent(intent)
        assert result is not None and result.success is True  # premise: the replay failed and the LLM recovered
        payloads = [args[1] for args in r.events if args[0] is EventType.PROCEDURE_FALLBACK_LEARNING]
        assert [payload["fallback_type"] for payload in payloads] == ["execution_failure"]
        engine = _constructed_dreaming_engine(r, _ConfirmationLLM())

        await engine.on_procedure_fallback_learning(payloads[0])
        stats = await engine._process_fallback_learning()

        assert stats["processed"] == 1
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_step_7e_runs_when_ships_records_is_disabled() -> None:
    """Finding 3 (review round 2): the observed-thread set was created in the same setter, so Step 7e raised
    ``AttributeError`` on its first thread when Ship's Records is disabled."""
    engine = DreamingEngine(
        router=SimpleNamespace(), trust_network=TrustNetwork(), episodic_memory=SimpleNamespace(),
        config=DreamingConfig(), llm_client=_ConfirmationLLM(), procedure_store=SimpleNamespace(),
        ward_room=SimpleNamespace(browse_threads=AsyncMock(
            return_value=[SimpleNamespace(id="thread-bf924", channel_name="dm:captain")],
        )),
        agent_id="observer-bf924",
    )

    stats = await engine._process_observational_learning()

    assert stats == {"observed": 0, "scanned": 1}  # a DM thread is scanned and skipped (the teaching path)
