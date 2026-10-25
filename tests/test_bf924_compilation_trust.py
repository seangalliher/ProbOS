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

from probos.cognitive.counselor import CounselorAgent
from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.llm_client import BaseLLMClient, MockLLMClient, OpenAICompatibleClient
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import ProcedureStep
from probos.config import COMPILATION_PROMOTION_THRESHOLD, TRUST_COMMANDER, DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.routers.procedures import TeachRequest, teach_procedure
from probos.substrate.registry import AgentRegistry
from probos.types import AgentState, LLMRequest, LLMResponse, Priority
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
    # BF-924 (#1654, A5): the promotion is conditional on the level and count the step read (D24)
    store.promote_compilation_level.assert_awaited_once_with(
        proc.id, 5, expected_level=4, min_consecutive=COMPILATION_PROMOTION_THRESHOLD,
    )


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
async def test_a_commanders_promotion_to_level_5_reaches_get_and_the_teaching_route(tmp_path) -> None:
    """D10 (review round 1, finding 2): a promotion moved only the index column; ``get`` and teaching read the snapshot."""
    r = await _store_rig(tmp_path, 0.7, 4, approved=True)
    try:
        assert r.runtime.trust_network.get_score(r.agent.id) >= TRUST_COMMANDER  # premise: Commander trust, exactly
        results = [await _handle_on_store(r.agent) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]
        assert all(result is not None and result.success is True for result in results)
        assert [entry["compilation_level"] for entry in await r.store.list_active()] == [5]  # premise: the column

        loaded = await r.store.get(r.proc.id)
        metrics = await r.store.get_quality_metrics(r.proc.id)
        reply = await teach_procedure(
            TeachRequest(procedure_id=r.proc.id, target_callsign="Learner"), runtime=r.runtime,
        )

        assert loaded is not None and loaded.compilation_level == 5
        assert (metrics["total_completions"], metrics["consecutive_successes"]) == (3, 0)  # counters kept
        assert reply.get("success") is True, reply
        r.runtime.ward_room.create_thread.assert_awaited_once()
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_demoted_procedure_is_dispatched_at_its_demoted_level(tmp_path) -> None:
    """D10 (review round 1, finding 2): a failure demoted only the index column, so the procedure kept replaying."""
    r = await _store_rig(tmp_path, 0.5, 4)
    try:
        failed = await _handle_on_store(r.agent, succeed=False)
        assert failed is not None and failed.success is False  # premise: the failure branch ran
        loaded = await r.store.get(r.proc.id)
        assert loaded is not None and loaded.compilation_level == 2

        decision = await r.agent.decide(dict(_OBSERVATION))

        assert decision.get("guided_by_procedure") is True
        assert decision.get("cached") is not True
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


# --- A3 (review round 2): Level 3 validation, the promotion request, the evolution window, Records off --------


def _replies(*first: LLMResponse | BaseException):
    """``complete``'s side effect: ``first`` in order (an exception is raised), then an ordinary LLM decision."""
    queue = list(first)

    async def reply(request: LLMRequest, **_kwargs: object) -> LLMResponse:
        item = queue.pop(0) if queue else LLMResponse(content="an LLM decision")
        if isinstance(item, BaseException):
            raise item
        return item

    return reply


async def _level_3_rig(tmp_path, *replies: LLMResponse | BaseException):
    """A Lieutenant's stored Level 3 procedure with a postcondition, validated through a real ``OpenAICompatibleClient``.

    Only the client's ``complete`` is replaced, as the reviewer's probe did (review round 2): a call to any other
    name fails as in production. The client is never contacted.
    """
    r = await _store_rig(tmp_path, 0.5, 3)
    r.proc.postconditions = ["the boundary result was checked"]
    await r.store.save(r.proc)
    client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    r.agent._llm_client = client  # replaced after construction, as the reviewer's probe did
    return r, client, AsyncMock(side_effect=_replies(*replies))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "calls", "replayed"),
    [("YES, the result was checked", 1, True), ("NO: nothing was checked", 2, False)],
    ids=["yes", "no"],
)
async def test_a_level_3_replay_is_validated_through_the_client_interface(tmp_path, answer, calls, replayed) -> None:
    """Finding 1 (review round 2): the validator called ``generate``, which no client has; the ``AttributeError``
    was caught as "passing by default", so every Level 3 replay was cached as validated with no request made.
    A NO now sends the intent to the LLM (its second request), as AD-535 specifies."""
    r, client, complete = await _level_3_rig(tmp_path, LLMResponse(content=answer))
    try:
        with patch.object(client, "complete", complete):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert complete.await_count == calls
        validation = complete.await_args_list[0].args[0]
        assert isinstance(validation, LLMRequest) and "the boundary result was checked" in validation.prompt
        assert bool(decision.get("cached")) is replayed
        assert (decision.get("compilation_level") == 3) is replayed
    finally:
        await client.close()
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [RuntimeError("provider down"), LLMResponse(content="", error="All LLM tiers unavailable")],
    ids=["raises", "error-reply"],
)
async def test_a_failed_level_3_validation_call_passes_by_default_and_warns(tmp_path, failure, caplog) -> None:
    """AD-535 (Part 5 and its acceptance): a validation call that fails passes by default. A3 keeps that rule and
    counts an error reply, which the client returns instead of raising (``llm_client.py:2092``), as a failed call."""
    r, client, complete = await _level_3_rig(tmp_path, failure)
    try:
        with patch.object(client, "complete", complete), \
                caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
            decision = await r.agent.decide(dict(_OBSERVATION))

        assert complete.await_count == 1  # the validation request, and no LLM decision after it
        assert decision.get("cached") is True and decision.get("compilation_level") == 3
        assert any("Level 3 validation call failed" in record.getMessage() for record in caplog.records)
    finally:
        await client.close()
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_lieutenants_promotion_to_level_4_requests_institutional_promotion_as_the_agent(tmp_path) -> None:
    """E11 (A3, D16): with D10 a Lieutenant's procedure reaches Level 4, and AD-536 requests institutional
    promotion, which no run reached before. The request was posted as ``getattr(self, "_agent_id", agent_type)``
    and ``_callsign``, attributes no agent has, so its author was the agent type."""
    r = await _store_rig(tmp_path, 0.5, 3)
    try:
        r.agent.callsign = "Wesley"
        r.runtime.ontology = None
        r.runtime.ward_room.list_channels = AsyncMock(return_value=[SimpleNamespace(id="all-hands", name="All Hands")])
        for _ in range(10):  # AD-536's floor: 10 completions at an effective rate of at least 0.7
            await r.store.record_selection(r.proc.id)
            await r.store.record_applied(r.proc.id)
            await r.store.record_completion(r.proc.id)
        results = [await _handle_on_store(r.agent) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]

        assert all(result is not None and result.success is True for result in results)
        assert [entry["compilation_level"] for entry in await r.store.list_active()] == [4]  # premise: promoted
        assert await r.store.get_promotion_status(r.proc.id) == "pending"  # premise: AD-536's request ran (E11)
        thread = r.runtime.ward_room.create_thread.await_args_list[0].kwargs
        assert (thread["author_id"], thread["author_callsign"]) == (r.agent.id, "Wesley")
        assert r.runtime.ward_room.get_or_create_dm_channel.await_args.args[0] == r.agent.id
    finally:
        await r.store.stop()


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
            while not (sum(task.done() for task in tasks) == 1 or llm.confirmations() == 2):
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


# --- A4 (review round 3): every result of a Level 3 to 5 replay reaches AD-535's accounting once -----------

_STEP_POOL = "bf924-step-worker"


async def _compound_rig(
    tmp_path, level: int, step_reply: LLMResponse, *, score: float = 0.5, approved: bool = False,
) -> SimpleNamespace:
    """A stored two-step compound procedure at ``level`` whose steps reach a real target agent through a real
    ``IntentBus`` and ``AgentRegistry``, as the reviewer's probe built it (review round 3).

    Only the agent's ``OpenAICompatibleClient.complete`` is replaced (by ``_compound_run``): the overall validation
    (100 tokens) answers YES, each step validation (50 tokens) gets ``step_reply``, and any other request (a Guided
    or recovery decision) is an ordinary LLM decision. The client is never contacted.
    """
    r = await _store_rig(tmp_path, score, level)
    r.client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    r.agent._llm_client = r.client  # replaced after construction, as the probe did
    r.bus, registry = IntentBus(SignalManager()), AgentRegistry()
    r.runtime.intent_bus, r.runtime.registry = r.bus, registry
    r.target = ReplayTestAgent(llm_client=MockLLMClient(), runtime=r.runtime, pool=_STEP_POOL)
    r.target.state = AgentState.ACTIVE
    await registry.register(r.target)
    r.bus.subscribe(r.target.id, r.target.handle_intent, intent_names=["compound_step_replay"])
    r.proc.steps = [
        ProcedureStep(
            step_number=n, action=f"perform operation {n}", expected_output=f"operation {n} complete",
            agent_role=_STEP_POOL, resolved_agent_type=_STEP_POOL,
        )
        for n in (1, 2)
    ]
    await r.store.save(r.proc)
    if approved:  # after the re-save, as the Captain approves a stored procedure
        await r.store.approve_promotion(r.proc.id, "captain", "directive-bf924")
    r.requests, r.delivered = [], []
    send_original = r.bus.send

    async def send(intent, **kwargs):
        r.delivered.append(intent)
        return await send_original(intent, **kwargs)

    async def complete(request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        r.requests.append(request)
        if request.max_tokens == 50:
            return step_reply
        if request.max_tokens == 100:
            return LLMResponse(content="YES")
        return LLMResponse(content="an LLM decision")

    r.send, r.complete = send, complete
    return r


async def _compound_run(r) -> SimpleNamespace:
    """One matched intent through ``handle_intent``, and what the client, the bus, the store and the events saw."""
    calls, deliveries = len(r.requests), len(r.delivered)
    with patch.object(r.client, "complete", new=r.complete), patch.object(r.bus, "send", new=r.send):
        result = await _handle_on_store(r.agent)
    turn = r.requests[calls:]
    metrics = await r.store.get_quality_metrics(r.proc.id)
    loaded = await r.store.get(r.proc.id)
    return SimpleNamespace(
        result=result, level=loaded.compilation_level, consecutive=metrics["consecutive_successes"],
        completions=metrics["total_completions"], fallbacks=metrics["total_fallbacks"],
        delivered=len(r.delivered) - deliveries,
        validations=[request.max_tokens for request in turn if request.max_tokens in (50, 100)],
        ordinary=sum(request.max_tokens not in (50, 100) for request in turn),
        event=[args[1] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE][-1],
    )


def _fallback_events(r) -> list[dict]:
    return [args[1] for args in r.events if args[0] is EventType.PROCEDURE_FALLBACK_LEARNING]


async def _close_compound_rig(r) -> None:
    r.bus.unsubscribe(r.target.id)
    await r.client.close()
    await r.store.stop()


@pytest.mark.asyncio
async def test_a_rejected_compound_step_is_a_failed_replay_that_the_llm_recovers(tmp_path) -> None:
    """Finding 1 (review round 3): the step validator's NO returned ``compound_aborted``, which the lifecycle
    ignored: it ran ``act()`` on the unchanged cached decision, reported success and counted it toward promotion
    (three rejections reached Level 4). A rejected step is now a failed replay: no ``act()`` on the replay,
    ``record_fallback``, AD-535's demotion and AD-534b's service recovery, whose event names the step."""
    r = await _compound_rig(tmp_path, 3, LLMResponse(content="NO"))
    try:
        run = await _compound_run(r)

        assert (run.delivered, run.validations) == (1, [100, 50])  # premise: step 1 ran and its validator said NO
        assert run.ordinary == 1  # the service recovery's LLM decision
        assert run.result is not None and run.result.success is True
        assert "[Procedure Replay" not in str(run.result.result)  # the recovered answer, not the rejected replay
        assert (run.completions, run.fallbacks) == (0, 1)
        assert (run.level, run.consecutive) == (2, 0)
        assert (run.event["used_procedure"], run.event["success"]) == (True, True)
        assert [
            (event["fallback_type"], event["procedure_id"], event["rejection_reason"]) for event in _fallback_events(r)
        ] == [("execution_failure", r.proc.id, "Compound step 1 output failed Level 3 validation")]
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
async def test_a_rejected_compound_step_without_recovery_fails_and_never_acts_on_the_replay(tmp_path) -> None:
    """Finding 1 (review round 3): when the recovery yields no decision, the intent fails with the step named, and
    ``act()`` never runs on the rejected replay (it ran once, and reported success, before A4)."""
    r = await _compound_rig(tmp_path, 3, LLMResponse(content="NO"))
    try:
        act = AsyncMock(wraps=r.agent.act)
        with patch.object(r.agent, "act", new=act), \
                patch.object(r.agent, "_run_llm_fallback", new=AsyncMock(return_value=None)):
            run = await _compound_run(r)

        assert (run.delivered, run.validations) == (1, [100, 50])  # premise: step 1 ran and its validator said NO
        assert act.await_count == 0
        assert run.result is not None and run.result.success is False
        assert run.result.error == "Compound step 1 output failed Level 3 validation"
        assert (run.completions, run.fallbacks, run.level) == (0, 1, 2)
        assert (run.event["used_procedure"], run.event["success"]) == (True, False)
        assert _fallback_events(r) == []  # AD-534b emits the learning event only for a recovered run
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "step_reply",
    [LLMResponse(content="YES"), LLMResponse(content="", error="All LLM tiers unavailable")],
    ids=["yes", "error-reply"],
)
async def test_dispatched_compound_replays_count_toward_promotion_once_per_run(tmp_path, step_reply) -> None:
    """Finding 2 (review round 3): a dispatched compound replay recorded its completion and returned before
    AD-535's promotion step, so it never counted a success: the procedure stayed at Level 3, paying three
    validation calls a run. A failed step-validation call passes by default (AD-535), so it counts as YES does."""
    r = await _compound_rig(tmp_path, 3, step_reply)
    try:
        runs = [await _compound_run(r) for _ in range(COMPILATION_PROMOTION_THRESHOLD + 1)]

        assert all((run.delivered, run.ordinary) == (2, 0) for run in runs)  # premise: every step dispatched
        assert all(run.result is not None and run.result.success is True for run in runs)
        assert [(run.level, run.consecutive) for run in runs] == [(3, 1), (3, 2), (4, 0), (4, 1)]
        assert [run.validations for run in runs] == [[100, 50, 50]] * 3 + [[]]  # Level 4 makes no validation call
        assert [run.completions for run in runs] == [1, 2, 3, 4]  # the compound branch's own write, once a run
        assert sum(args[0] is EventType.TASK_EXECUTION_COMPLETE for args in r.events) == 4
        assert all(run.event.get("compound_dispatched") is True for run in runs)
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
async def test_a_commanders_approved_compound_procedure_reaches_level_5(tmp_path) -> None:
    """Finding 2 at Level 4 (review round 3): the same early return kept an approved compound procedure from
    AD-536's Level 5, which a single-step procedure reaches after three successes."""
    r = await _compound_rig(tmp_path, 4, LLMResponse(content="YES"), score=0.7, approved=True)
    try:
        assert r.runtime.trust_network.get_score(r.agent.id) >= TRUST_COMMANDER  # premise: Commander trust
        runs = [await _compound_run(r) for _ in range(COMPILATION_PROMOTION_THRESHOLD)]

        assert all((run.delivered, run.validations, run.ordinary) == (2, [], 0) for run in runs)  # premise: Level 4
        assert [run.level for run in runs] == [4, 4, 5]
    finally:
        await _close_compound_rig(r)


@pytest.mark.asyncio
async def test_a_level_3_no_demotes_the_procedure_and_resets_its_count(tmp_path) -> None:
    """D22 (A4): a NO hands the intent to the LLM (D15) and left the count untouched, so three YES answers that
    were not consecutive still promoted. AD-535 demotes on any failure and resets the count; the near-miss event
    and the completion event's ``used_procedure`` (D9) are unchanged."""
    r, client, complete = await _level_3_rig(tmp_path, LLMResponse(content="NO: nothing was checked"))
    try:
        for _ in range(COMPILATION_PROMOTION_THRESHOLD - 1):
            await r.store.record_consecutive_success(r.proc.id)
        with patch.object(client, "complete", complete):
            result = await _handle_on_store(r.agent)

        assert result is not None and result.success is True  # the LLM served the intent
        assert complete.await_count == 2  # premise: the validation request, then the LLM decision
        loaded = await r.store.get(r.proc.id)
        metrics = await r.store.get_quality_metrics(r.proc.id)
        assert (loaded.compilation_level, metrics["consecutive_successes"]) == (2, 0)
        assert [
            args[1]["used_procedure"] for args in r.events if args[0] is EventType.TASK_EXECUTION_COMPLETE
        ] == [False]
        assert [event["fallback_type"] for event in _fallback_events(r)] == ["validation_failure"]
    finally:
        await client.close()
        await r.store.stop()


# --- A5 (review round 4): a promotion is conditional; the recovery decision and the step failure ------------------


_CAS_ID = "proc-bf924-cas"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("since_read", "applied", "after"),
    [
        ("nothing", True, (4, 0)),
        ("demoted", False, (2, 0)),
        ("demoted-and-recounted", False, (2, COMPILATION_PROMOTION_THRESHOLD)),
        ("count-reset", False, (3, 0)),
        ("promoted", False, (4, 0)),
        ("column-disagrees", True, (4, 0)),
        ("unconditional", True, (4, 0)),
    ],
    ids=["nothing", "demoted", "demoted-and-recounted", "count-reset", "promoted", "column-disagrees", "unconditional"],
)
async def test_a_conditional_promotion_applies_only_to_the_level_and_count_it_read(
    tmp_path, since_read, applied, after,
) -> None:
    """Finding 1 (review round 4), at the store: the accounting reads the count and ``get``'s level, then promotes
    across awaits. With ``expected_level`` and ``min_consecutive`` the write applies only while the snapshot's level
    (what ``get`` returns, not the column: R10's rows differ) is still the one read and the count still reaches the
    threshold, and it says whether it applied. With neither argument it is unconditional, as before."""
    store = _KnownMatchStore(tmp_path / "procedures")
    await store.start()
    try:
        await store.save(_make_procedure(id=_CAS_ID, compilation_level=3))
        for _ in range(COMPILATION_PROMOTION_THRESHOLD):
            await store.record_consecutive_success(_CAS_ID)
        read_level = (await store.get(_CAS_ID)).compilation_level
        assert read_level == 3  # premise: the level the success read
        if since_read in ("demoted", "demoted-and-recounted", "unconditional"):
            await store.demote_compilation_level(_CAS_ID, 2)
        if since_read == "demoted-and-recounted":  # the count reached the threshold again, at Level 2
            for _ in range(COMPILATION_PROMOTION_THRESHOLD):
                await store.record_consecutive_success(_CAS_ID)
        if since_read == "count-reset":  # a failure at a stored level of 2 or below resets without demoting
            await store.reset_consecutive_successes(_CAS_ID)
        if since_read == "promoted":
            await store.promote_compilation_level(_CAS_ID, 4)
        if since_read == "column-disagrees":  # R10: a row whose column moved without its snapshot
            await store._db.execute("UPDATE procedure_records SET compilation_level = 2 WHERE id = ?", (_CAS_ID,))
            await store._db.commit()

        if since_read == "unconditional":
            result = await store.promote_compilation_level(_CAS_ID, read_level + 1)
        else:
            result = await store.promote_compilation_level(
                _CAS_ID, read_level + 1,
                expected_level=read_level, min_consecutive=COMPILATION_PROMOTION_THRESHOLD,
            )

        assert result is applied
        loaded = await store.get(_CAS_ID)
        metrics = await store.get_quality_metrics(_CAS_ID)
        assert (loaded.compilation_level, metrics["consecutive_successes"]) == after
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_a_stale_success_does_not_overwrite_another_agents_later_demotion(tmp_path) -> None:
    """Finding 1 (review round 4), through ``handle_intent`` with two agents on one real store: a success read the
    count (3) and the level (3); across its awaits the other agent's Level 3 NO demoted the shared procedure to
    Level 2 (D22); the older success then wrote Level 4, so the procedure replayed with no validation right after the
    validator rejected it. The promotion is now conditional on what it read, and nothing is announced."""
    r, client, complete = await _level_3_rig(tmp_path, LLMResponse(content="YES"))
    peer_client = OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1")
    peer = ReplayTestAgent(llm_client=peer_client, runtime=r.runtime)
    network = TrustNetwork()
    for agent in (r.agent, peer):
        network.create_with_prior(agent.id, alpha=5.0, beta=5.0)  # both Lieutenants (0.5)
    r.runtime.trust_network = network
    peer_complete = AsyncMock(side_effect=_replies(LLMResponse(content="NO: nothing was checked")))
    for _ in range(COMPILATION_PROMOTION_THRESHOLD - 1):
        await r.store.record_consecutive_success(r.proc.id)
    held, released = asyncio.Event(), asyncio.Event()
    state: dict[str, object] = {"task": None}
    get_original = r.store.get
    outcome_original = r.agent._record_compilation_outcome

    async def outcome(procedure_id, success, **kwargs):  # BF-924 (#1654, A6): forwards executed_level
        if procedure_id and success:
            state["task"] = asyncio.current_task()
        return await outcome_original(procedure_id, success, **kwargs)

    async def get(procedure_id):
        loaded = await get_original(procedure_id)
        if asyncio.current_task() is state["task"] and not held.is_set():
            held.set()  # the success has read its count and the level: hold it here
            await asyncio.wait_for(released.wait(), 10)
        return loaded

    request = AsyncMock(return_value=None)
    try:
        with patch.object(client, "complete", complete), patch.object(peer_client, "complete", peer_complete), \
                patch.object(r.agent, "_record_compilation_outcome", new=outcome), \
                patch.object(r.agent, "_request_procedure_promotion", new=request), \
                patch.object(r.store, "get", new=get):
            success_run = asyncio.create_task(_handle_on_store(r.agent))
            await asyncio.wait_for(held.wait(), 10)
            demoted = await _handle_on_store(peer)  # the peer's Level 3 NO
            released.set()
            succeeded = await asyncio.wait_for(success_run, 10)

        assert succeeded is not None and succeeded.success is True
        assert demoted is not None and demoted.success is True  # the LLM served the peer's intent
        assert peer_complete.await_count == 2  # premise: the peer's validation request (NO), then its LLM decision
        loaded = await get_original(r.proc.id)
        metrics = await r.store.get_quality_metrics(r.proc.id)
        assert (loaded.compilation_level, metrics["consecutive_successes"]) == (2, 0)
        request.assert_not_awaited()
    finally:
        released.set()
        await client.close()
        await peer_client.close()
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("duty", [None, {"duty_id": "bf924-duty"}], ids=["no-duty", "duty"])
async def test_the_service_recovery_decision_carries_the_intent_and_duty_the_replay_had(tmp_path, duty) -> None:
    """Finding 2 (review round 4): AD-534b's recovery passed ``act()`` a decision without the intent (AD-398) and
    the duty (BF-177) the normal path adds after ``decide``, so an agent whose ``act`` branches on them (the
    Counselor, Surgeon, Builder, Architect, Scout) treated the recovered answer as a task."""
    r = await _store_rig(tmp_path, 0.5, 4)
    params = {"message": "test query", **({"duty": duty} if duty else {})}
    intent = _make_intent(target_agent_id=r.agent.id, params=params)
    decisions: list[dict] = []

    async def act(decision):
        decisions.append(dict(decision))
        if len(decisions) == 1:
            return {"success": False, "error": "chosen failure"}
        return {"success": True, "result": decision.get("llm_output", "")}

    try:
        with patch.object(
            r.agent, "_recall_relevant_memories", new=AsyncMock(side_effect=lambda _intent, observation: observation),
        ), patch.object(r.agent, "_store_action_episode", new=AsyncMock()), patch.object(r.agent, "act", new=act), \
                patch.object(
                    r.agent, "_run_llm_fallback", new=AsyncMock(return_value={"action": "execute", "llm_output": "recovered"}),
                ):
            result = await r.agent.handle_intent(intent)

        assert len(decisions) == 2 and decisions[0].get("cached") is True  # premise: a failed replay, then the recovery
        assert result is not None and (result.success, result.result) == (True, "recovered")
        assert decisions[1].get("intent") == decisions[0].get("intent") == "test_intent"
        assert decisions[1].get("duty") == decisions[0].get("duty") == duty
    finally:
        await r.store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("recovers", [True, False], ids=["recovered", "no-recovery"])
async def test_a_counselors_rejected_compound_step_reaches_its_act_and_report(tmp_path, recovers) -> None:
    """Findings 2 and 3 (review round 4), through the real ``CounselorAgent``: its ``act`` passes a conversational
    answer through only for a decision that names its intent, and its ``report`` keeps a dict only when it has
    ``result``. The recovery decision lacked the intent, so a healthy recovered answer became a failure; the step
    failure lacked ``result``, so the report nested it and the step reason was lost."""
    r = await _compound_rig(tmp_path, 3, LLMResponse(content="NO"))
    counselor = CounselorAgent(llm_client=r.client, runtime=r.runtime)
    counselor.state = AgentState.ACTIVE
    await r.runtime.registry.register(counselor)
    r.runtime.trust_network = trust_network_at(counselor.id, 0.5)
    intent = _make_intent("direct_message", target_agent_id=counselor.id)
    try:
        with patch.object(r.client, "complete", new=r.complete), patch.object(r.bus, "send", new=r.send), \
                patch.object(
                    counselor, "_recall_relevant_memories",
                    new=AsyncMock(side_effect=lambda _intent, observation: observation),
                ), patch.object(counselor, "_store_action_episode", new=AsyncMock()):
            if recovers:
                result = await counselor.handle_intent(intent)
            else:
                with patch.object(counselor, "_run_llm_fallback", new=AsyncMock(return_value=None)):
                    result = await counselor.handle_intent(intent)

        assert [request.max_tokens for request in r.requests][:2] == [100, 50]  # premise: the step validator said NO
        metrics = await r.store.get_quality_metrics(r.proc.id)
        assert (metrics["total_completions"], metrics["total_fallbacks"]) == (0, 1)
        if recovers:
            assert result is not None and (result.success, result.result) == (True, "an LLM decision")
            assert [event["rejection_reason"] for event in _fallback_events(r)] == [
                "Compound step 1 output failed Level 3 validation",
            ]
        else:
            assert result is not None and result.success is False
            assert result.error == "Compound step 1 output failed Level 3 validation"
    finally:
        await _close_compound_rig(r)


# --- A6 (review round 5): a success counts only toward the level it was executed at ----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("since_save", "expected_level", "returned", "count"),
    [
        ("nothing", 3, 1, 1),
        ("promoted", 3, None, 0),
        ("column-disagrees", 3, 1, 1),
        ("nothing", None, 1, 1),
    ],
    ids=["same-level", "level-moved", "column-disagrees", "unconditional"],
)
async def test_a_success_counts_only_at_the_level_it_was_executed_at(
    tmp_path, since_save, expected_level, returned, count,
) -> None:
    """Finding 1 (review round 5), at the store: the increment was unconditional, so a success executed at one level
    counted toward the next level's threshold once another intent had promoted the shared procedure. With
    ``expected_level`` it applies only while the snapshot's level (what ``get`` returns; R10's column may differ) is
    still that level, and returns ``None`` when it is not; without it, it is unconditional and returns the count."""
    store = _KnownMatchStore(tmp_path / "procedures")
    await store.start()
    try:
        await store.save(_make_procedure(id=_CAS_ID, compilation_level=3))
        if since_save == "promoted":  # another intent's promotion since this outcome was dispatched at Level 3
            await store.promote_compilation_level(_CAS_ID, 4)
        if since_save == "column-disagrees":  # R10: a row whose column moved without its snapshot
            await store._db.execute("UPDATE procedure_records SET compilation_level = 2 WHERE id = ?", (_CAS_ID,))
            await store._db.commit()

        if expected_level is None:
            result = await store.record_consecutive_success(_CAS_ID)
        else:
            result = await store.record_consecutive_success(_CAS_ID, expected_level=expected_level)

        metrics = await store.get_quality_metrics(_CAS_ID)
        assert (result, metrics["consecutive_successes"]) == (returned, count)
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "stored", "approved", "executed", "count"),
    [(0.3, 4, False, 2, 0), (0.5, 4, False, 4, 1), (0.5, 5, False, 4, 0), (0.7, 5, True, 5, 1)],
    ids=["ensign-guided-at-4", "lieutenant-at-4", "lieutenant-at-5", "commander-at-5"],
)
async def test_a_success_is_credited_only_to_the_level_it_ran_at(
    tmp_path, score, stored, approved, executed, count,
) -> None:
    """Finding 1 (review round 5), per decision shape: the Guided decision names Level 2 and the Level 3 decision
    Level 3, but the Level 4 and 5 replay named no level, and every success was credited to the stored level. A
    clamped Ensign's Guided run of a stored Level 4 procedure, and a Lieutenant's Level 4 replay of a stored Level 5
    one, ran below the stored level: they count toward no threshold. A run at the stored level counts once."""
    r = await _store_rig(tmp_path, score, stored, approved=approved)
    try:
        decision = await r.agent.decide(dict(_OBSERVATION))
        result = await _handle_on_store(r.agent)
        metrics = await r.store.get_quality_metrics(r.proc.id)

        assert decision.get("compilation_level") == executed
        assert result is not None and result.success is True
        assert metrics["consecutive_successes"] == count
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_a_success_without_an_executed_level_is_not_counted(tmp_path) -> None:
    """A6 (D28): every replay decision names the level it ran at; a success that names none earns no count."""
    r = await _store_rig(tmp_path, 0.5, 2)
    try:
        await r.agent._record_compilation_outcome(r.proc.id, True)
        await r.agent._record_compilation_outcome(r.proc.id, True, executed_level=2)
        metrics = await r.store.get_quality_metrics(r.proc.id)
        assert metrics["consecutive_successes"] == 1
    finally:
        await r.store.stop()


@pytest.mark.asyncio
async def test_guided_outcomes_pending_across_a_promotion_do_not_count_toward_level_4(tmp_path) -> None:
    """Finding 1 (review round 5), through ``handle_intent``: four agents' Guided runs of one Level 2 procedure (count
    2), each held at its LLM call, completed after the first had promoted the shared procedure to Level 3; the other
    three counted toward Level 4 and committed it with no Level 3 validation, and the next intent replayed with no LLM
    call. Per-agent serialisation does not cover a shared procedure. A success now counts only while the procedure is
    at the level it ran at, so Level 3 is committed once and the next intent is a validated Level 3 replay."""
    r = await _store_rig(tmp_path, 0.5, 2)
    r.proc.postconditions = ["the boundary result was checked"]
    await r.store.save(r.proc)  # a re-save resets the count, so the count is set after it
    for _ in range(COMPILATION_PROMOTION_THRESHOLD - 1):
        await r.store.record_consecutive_success(r.proc.id)
    clients = [OpenAICompatibleClient(base_url="http://127.0.0.1:9/v1") for _ in range(4)]
    agents = [ReplayTestAgent(llm_client=client, runtime=r.runtime) for client in clients]
    network = TrustNetwork()
    for agent in agents:
        network.create_with_prior(agent.id, alpha=5.0, beta=5.0)  # four Lieutenants (0.5): the cap is Level 4
    r.runtime.trust_network = network
    held = [asyncio.Event() for _ in agents]
    released = [asyncio.Event() for _ in agents]
    validations: list[tuple[int, int]] = []

    def complete_for(index: int):
        async def complete(request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
            if request.max_tokens in (50, 100):
                validations.append((index, request.max_tokens))
                return LLMResponse(content="YES")
            held[index].set()  # a Guided decision's LLM call: held until the test releases it
            await asyncio.wait_for(released[index].wait(), 10)
            return LLMResponse(content="an LLM decision")

        return complete

    for index, client in enumerate(clients):
        client.complete = complete_for(index)  # only this test's clients, each closed below
    tasks: list[asyncio.Task] = []
    rows: list[tuple[int, int]] = []
    try:
        tasks = [asyncio.create_task(_handle_on_store(agent)) for agent in agents]
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in held)), 10)
        assert validations == []  # premise: four Guided decisions of the Level 2 procedure, each at its LLM call
        for index, task in enumerate(tasks):
            released[index].set()
            result = await asyncio.wait_for(task, 10)
            assert result is not None and result.success is True
            loaded = await r.store.get(r.proc.id)
            metrics = await r.store.get_quality_metrics(r.proc.id)
            rows.append((loaded.compilation_level, metrics["consecutive_successes"]))
        after = await _handle_on_store(agents[0])

        # The round-5 candidate committed [(3, 0), (3, 1), (3, 2), (4, 0)]: three Guided runs supplied Level 4's threshold
        assert rows == [(3, 0)] * 4
        assert after is not None and after.success is True
        assert validations == [(0, 100)]  # the next intent is a validated Level 3 replay, not a Level 4 one
        metrics = await r.store.get_quality_metrics(r.proc.id)
        assert ((await r.store.get(r.proc.id)).compilation_level, metrics["consecutive_successes"]) == (3, 1)
    finally:
        for event in released:
            event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        for client in clients:
            await client.close()
        await r.store.stop()
