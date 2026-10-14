"""AD-1326 (#1510) acceptance: a FIX evolution replaces its champion only by winning a head-to-head.

``prompts/ad-1326-procedure-challenger-champion.md``, Milestone 3. Every link of the chain is the
production object: the dream engine's evolution site rewrites a degraded champion on the deep tier,
``ProcedureChallenger.submit`` saves the rewrite inactive and files it in the real
``ProcedureChallengeLedger`` of a real ``ProcedureStore`` (SQLite and Chroma on ``tmp_path``),
``run_cycle`` judges it against the champion through the real ``ProcedureJudge`` on real ``Episode``
objects, and the store then routes to whichever procedure won.

Only what needs a model or a vector index of its own is a double, and each double carries what the
real seam carries:

* ``_MarkerLLM`` -- one stateful LLM. A request on the ``deep`` tier is the rewrite and is answered with
  a FIX procedure whose second step carries ``_MARKER``; any other tier is the judge's (the verifier
  policy's tier, ``standard`` here) and is answered by locating the marker in Candidate 1 or Candidate 2.
  Every answer is a real ``LLMResponse`` with ``model``, ``tier``, ``answered_tier`` and
  ``answered_model`` set as ``OpenAICompatibleClient`` sets them.
* ``_Episodes`` -- the episodic memory over five real ``Episode`` objects ``e0..e4`` of the champion's
  intent: ``recall_by_intent``, ``get_by_ids(ids, *, for_evidence=False)`` (a missing id is left out, as
  ``EpisodicMemory`` leaves it out) and ``update_episode_validity``, whose calls are recorded.
* ``_Events`` -- the emit seam, recording ``(event_type, payload)``.

The judge's random order comes from a seeded ``random.Random``, so a run is repeatable.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.procedure_challenger import ProcedureChallenger, build_procedure_challenger
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.config import DreamingConfig, SystemConfig
from probos.events import EventType
from probos.types import Episode, LLMRequest, LLMResponse

_INTENT = "reconcile_ledger"
_MARKER = "MARKER-STEP"
_DEEP_MODEL = "claude-opus-4-6"
_JUDGE_MODEL = "claude-sonnet-4-6"
_BATCHES = ("amber", "birch", "cedar", "dahlia", "elm")  # the batch each of e0..e4 reconciled
_STATUSES = ("pending", "promoting", "promoted", "retired")
_FIX_DIAGNOSIS = "FIX: high fallback rate"
_ALL_FIVE = ["e0", "e1", "e2", "e3", "e4"]

_FIX_PROCEDURE: dict[str, Any] = {
    "name": "Reconcile a ledger batch (verified)",
    "description": "Reconcile one ledger batch against the bank feed and verify every total",
    "steps": [
        {"step_number": 1, "action": "Open the ledger batch", "expected_output": "the batch is open"},
        {
            "step_number": 2,
            "action": f"{_MARKER}: cross-check every total against the bank feed",
            "expected_output": "every total agrees with the feed",
            "fallback_action": "flag the batch for review",
        },
    ],
    "preconditions": ["the bank feed is reachable"],
    "postconditions": ["the batch is reconciled"],
    "change_summary": "Added a verification step against the bank feed.",
}


# -- the doubles --------------------------------------------------------------------------------------------


def _candidate(prompt: str, number: int) -> str:
    """The text between ``=== CANDIDATE n ===`` and ``=== END CANDIDATE n ===`` in a judge prompt."""
    return prompt.split(f"=== CANDIDATE {number} ===\n", 1)[1].split(f"\n=== END CANDIDATE {number} ===", 1)[0]


class _MarkerLLM:
    """One LLM for both seams: the deep-tier FIX rewrite and the policy-tier head-to-head judge."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []
        self.prefers = "marker"  # which candidate the judge prefers: "marker" or "champion"
        self.marker_positions: list[int] = []  # per judge request: 1 or 2, the candidate holding the marker
        self.unplaced: list[str] = []  # judge prompts whose marker was not in exactly one candidate

    @property
    def rewrites(self) -> list[LLMRequest]:
        return [request for request in self.requests if request.tier == "deep"]

    @property
    def judge_requests(self) -> list[LLMRequest]:
        return [request for request in self.requests if request.tier != "deep"]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.tier == "deep":
            return self._answer(request, json.dumps(_FIX_PROCEDURE), _DEEP_MODEL)
        return self._answer(request, self._judgement(request.prompt), _JUDGE_MODEL)

    def _judgement(self, prompt: str) -> str:
        holders = [number for number in (1, 2) if _MARKER in _candidate(prompt, number)]
        if len(holders) != 1:
            self.unplaced.append(prompt)
            return json.dumps({"preferred": "tie", "reason": "the marker is not in exactly one candidate"})
        self.marker_positions.append(holders[0])
        preferred = holders[0] if self.prefers == "marker" else 3 - holders[0]
        return json.dumps({"preferred": str(preferred), "reason": f"candidate {preferred} verifies the totals"})

    @staticmethod
    def _answer(request: LLMRequest, content: str, model: str) -> LLMResponse:
        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier,
            tokens_used=64,
            request_id=request.id,
            answered_tier=request.tier,
            answered_model=model,
        )


class _Episodes:
    """The episodic memory the dream engine and the challenger read, with the expiry calls recorded."""

    def __init__(self, episodes: list[Episode]) -> None:
        self.episodes = list(episodes)
        self.validity_updates: list[tuple[str, float]] = []

    async def recall_by_intent(
        self, intent_type: str, k: int = 5, *, include_self_contradicted: bool = False,
    ) -> list[Episode]:
        matching = [ep for ep in self.episodes if any(item.get("intent") == intent_type for item in ep.outcomes)]
        return matching[:k]

    async def get_by_ids(self, episode_ids: list[str], *, for_evidence: bool = False) -> list[Episode]:
        by_id = {ep.id: ep for ep in self.episodes}
        return [by_id[episode_id] for episode_id in episode_ids if episode_id in by_id]

    async def update_episode_validity(self, episode_id: str, valid_until: float) -> bool:
        self.validity_updates.append((episode_id, valid_until))
        return True


class _Events:
    """The emit seam: records ``(event_type, payload)``."""

    def __init__(self) -> None:
        self.emitted: list[tuple[EventType, dict[str, Any]]] = []

    def emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.emitted.append((event_type, payload))

    def decided(self) -> list[dict[str, Any]]:
        return [payload for kind, payload in self.emitted if kind == EventType.PROCEDURE_CHALLENGE_DECIDED]


# -- the world ----------------------------------------------------------------------------------------------


def _episodes() -> list[Episode]:
    """``e0..e4``, newest first: the order the memory recalls them in and the challenger splits them in."""
    return [
        Episode(
            id=f"e{index}",
            timestamp=2_000.0 - index,
            user_input=f"Reconcile the {batch} ledger batch against the bank feed",
            outcomes=[{"intent": _INTENT, "success": True, "response": f"{batch} batch reconciled"}],
            agent_ids=["agent-ledger"],
        )
        for index, batch in enumerate(_BATCHES)
    ]


def _champion() -> Procedure:
    return Procedure(
        id="champion-ledger",
        name="Reconcile a ledger batch",
        description="Reconcile one ledger batch against the bank feed",
        steps=[
            ProcedureStep(step_number=1, action="Open the ledger batch"),
            ProcedureStep(step_number=2, action="Compare the totals once", expected_output="totals compared"),
        ],
        intent_types=[_INTENT],
        origin_cluster_id="cluster-ledger",
        origin_agent_ids=["agent-ledger"],
        extraction_date=1_000.0,
    )


@dataclass
class _World:
    store: ProcedureStore
    memory: _Episodes
    llm: _MarkerLLM
    events: _Events
    champion: Procedure
    metrics: dict[str, Any]
    challenger: ProcedureChallenger
    engine: DreamingEngine


def _engine(
    memory: _Episodes, llm: _MarkerLLM, store: ProcedureStore, challenger: ProcedureChallenger | None,
) -> DreamingEngine:
    return DreamingEngine(
        MagicMock(), MagicMock(), memory, DreamingConfig(),
        llm_client=llm, procedure_store=store, procedure_challenger=challenger,
    )


@asynccontextmanager
async def _open_world(tmp_path: Path) -> AsyncIterator[_World]:
    """A started store holding a degraded champion (5 selections, 3 fallbacks), the five episodes, the doubles."""
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    try:
        champion = _champion()
        await store.save(champion)
        for _ in range(5):
            await store.record_selection(champion.id)
        for _ in range(3):
            await store.record_fallback(champion.id)
        metrics = await store.get_quality_metrics(champion.id)
        assert metrics is not None
        assert metrics["fallback_rate"] == pytest.approx(0.6)

        memory, llm, events = _Episodes(_episodes()), _MarkerLLM(), _Events()
        challenger = build_procedure_challenger(
            config=SystemConfig(),
            procedure_store=store,
            episodic_memory=memory,
            llm_client=llm,
            emit_event_fn=events.emit,
            rng=random.Random(1326),
        )
        assert challenger is not None
        yield _World(store, memory, llm, events, champion, metrics, challenger, _engine(memory, llm, store, challenger))
    finally:
        await store.stop()


@pytest.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    async with _open_world(tmp_path) as opened:
        yield opened


async def _active_ids(store: ProcedureStore) -> list[str]:
    return [entry["id"] for entry in await store.list_active()]


async def _matching_ids(store: ProcedureStore, query: str) -> list[str]:
    return [match["id"] for match in await store.find_matching(query)]


async def _ledger_is_empty(store: ProcedureStore) -> bool:
    ledger = store.challenges
    assert ledger is not None
    return not any([await ledger.list_by_status(status) for status in _STATUSES]) and not await ledger.recent_cycles()


# -- the acceptance tests -----------------------------------------------------------------------------------


async def test_challenger_wins_and_routing_uses_it(world: _World) -> None:
    w = world
    assert await w.engine._attempt_procedure_evolution(w.champion, _FIX_DIAGNOSIS, w.metrics) is True

    # Only a challenger so far: saved inactive, linked to its champion, never routed to, nothing expired.
    [pending] = await w.store.challenges.list_by_status("pending")
    challenger_id = pending.challenger_id
    saved = await w.store.get(challenger_id)
    assert saved is not None
    assert saved.is_active is False
    assert saved.evolution_type == "FIX"
    assert saved.parent_procedure_ids == [w.champion.id]
    assert pending.champion_id == w.champion.id
    assert await _active_ids(w.store) == [w.champion.id]
    assert await _matching_ids(w.store, w.champion.description) == [w.champion.id]
    assert w.memory.validity_updates == []
    # The rewrite ran on the optimizer tier, and who answered it reached the ledger.
    [rewrite] = w.llm.rewrites
    assert (rewrite.tier, rewrite.min_tier) == ("deep", "standard")
    assert (pending.optimizer_tier, pending.optimizer_model) == ("deep", _DEEP_MODEL)

    report = await w.challenger.run_cycle()  # the judge prefers the marker, which only the challenger carries

    assert report.promoted == 1
    assert report.retired == 0
    assert report.judge_calls == 8
    assert report.comparisons == 4
    assert report.deferred == 0
    # The champion is replaced, exactly as legacy supersession replaces it.
    champion_now = await w.store.get(w.champion.id)
    assert champion_now is not None
    assert champion_now.is_active is False
    assert champion_now.superseded_by == challenger_id
    assert await _active_ids(w.store) == [challenger_id]
    # Routing uses the winner: a search for the champion's own description finds the challenger and not the champion.
    assert await _matching_ids(w.store, w.champion.description) == [challenger_id]
    # The promotion's re-save kept the rewrite's own change summary.
    assert (await w.store.get_evolution_metadata(challenger_id))["change_summary"] == _FIX_PROCEDURE["change_summary"]
    # The evidence: four counted situations, two of them held out, the judge asked in both orders.
    rows = await w.store.challenges.comparisons(challenger_id)
    assert len(rows) == 4
    assert all(row.counted and row.outcome == "challenger" for row in rows)
    assert sorted(row.episode_id for row in rows if row.split == "held_out") == ["e1", "e3"]
    assert sorted(row.episode_id for row in rows if row.split == "used") == ["e0", "e2"]
    assert len(w.llm.judge_requests) == 8
    assert {request.tier for request in w.llm.judge_requests} == {"standard"}  # the policy tier, never the rewrite's
    assert w.llm.unplaced == []
    for index, row in enumerate(rows):
        asked = w.llm.marker_positions[2 * index : 2 * index + 2]
        assert sorted(asked) == [1, 2]
        assert row.first_shown == ("challenger" if asked[0] == 1 else "champion")
    # One durable decision event, and the ledger agrees with it.
    [decided] = w.events.decided()
    assert decided["decision"] == "promoted"
    assert decided["reason"] == "won"
    assert decided["challenger_id"] == challenger_id
    assert decided["champion_id"] == w.champion.id
    assert (decided["wins"], decided["losses"], decided["ties"], decided["decisions"]) == (4, 0, 0, 4)
    assert (decided["held_out_wins"], decided["held_out_decisions"]) == (2, 2)
    record = await w.store.challenges.get(challenger_id)
    assert record is not None
    assert record.status == "promoted"
    assert record.decision_reason.startswith("won:")
    [cycle] = await w.store.challenges.recent_cycles()
    assert (cycle["judge_calls"], cycle["comparisons"], cycle["promoted"], cycle["retired"]) == (8, 4, 1, 0)
    # The promoted challenger's source episodes are the five, handed on for expiry.
    assert sorted(episode.id for episode in report.superseded_episodes) == _ALL_FIVE


async def test_challenger_loses_and_the_champion_keeps_routing(world: _World) -> None:
    w = world
    assert await w.engine._attempt_procedure_evolution(w.champion, _FIX_DIAGNOSIS, w.metrics) is True
    [pending] = await w.store.challenges.list_by_status("pending")
    challenger_id = pending.challenger_id
    w.llm.prefers = "champion"  # the judge now prefers the candidate without the marker

    report = await w.challenger.run_cycle()

    assert report.promoted == 0
    assert report.retired == 1
    assert report.judge_calls == 8
    assert report.superseded_episodes == ()
    record = await w.store.challenges.get(challenger_id)
    assert record is not None
    assert record.status == "retired"
    assert record.decision_reason.startswith("lost:")
    # The champion keeps routing and keeps its place; the challenger stays an inactive record.
    champion_now = await w.store.get(w.champion.id)
    assert champion_now is not None
    assert champion_now.is_active is True
    assert champion_now.superseded_by == ""
    challenger_now = await w.store.get(challenger_id)
    assert challenger_now is not None
    assert challenger_now.is_active is False
    assert await _active_ids(w.store) == [w.champion.id]
    assert await _matching_ids(w.store, w.champion.description) == [w.champion.id]
    # Retirement keeps the evidence.
    rows = await w.store.challenges.comparisons(challenger_id)
    assert len(rows) == 4
    assert all(row.counted and row.outcome == "champion" for row in rows)
    [decided] = w.events.decided()
    assert decided["decision"] == "retired"
    assert decided["reason"] == "lost"
    assert decided["challenger_id"] == challenger_id
    assert (decided["wins"], decided["losses"], decided["decisions"]) == (0, 4, 4)


async def test_held_out_episodes_never_reach_the_rewrite_prompt_and_are_judged(world: _World) -> None:
    w = world
    inputs = {episode.id: episode.user_input for episode in w.memory.episodes}
    batches = dict(zip(_ALL_FIVE, _BATCHES))
    assert await w.engine._attempt_procedure_evolution(w.champion, _FIX_DIAGNOSIS, w.metrics) is True

    [rewrite] = w.llm.rewrites
    assert "Fresh successful episodes (3):" in rewrite.prompt
    for kept in ("e0", "e2", "e4"):
        assert f"Episode ID: {kept}\n" in rewrite.prompt
        assert inputs[kept] in rewrite.prompt
    for held_out in ("e1", "e3"):
        assert f"Episode ID: {held_out}\n" not in rewrite.prompt
        assert inputs[held_out] not in rewrite.prompt
        assert batches[held_out] not in rewrite.prompt  # nor anything else the held-out episode recorded

    report = await w.challenger.run_cycle()

    assert report.judge_calls == 8
    judge_prompts = [request.prompt for request in w.llm.judge_requests]
    for judged in ("e0", "e1", "e2", "e3"):  # the first two the rewrite saw, and every held-out episode
        assert sum(inputs[judged] in prompt for prompt in judge_prompts) == 2  # once in each order
    assert not any(inputs["e4"] in prompt for prompt in judge_prompts)  # seen by the rewrite, beyond the used contexts


async def test_derived_evolution_is_unchanged_under_the_challenger_flow(world: _World) -> None:
    w = world

    assert await w.engine._attempt_procedure_evolution(w.champion, "DERIVED: low effective rate", w.metrics) is True

    ids = await _active_ids(w.store)
    derived_ids = [procedure_id for procedure_id in ids if procedure_id != w.champion.id]
    assert len(ids) == 2
    assert len(derived_ids) == 1
    derived = await w.store.get(derived_ids[0])
    assert derived is not None
    assert derived.evolution_type == "DERIVED"
    assert derived.is_active is True  # saved active, as before
    assert derived.parent_procedure_ids == [w.champion.id]
    champion_now = await w.store.get(w.champion.id)
    assert champion_now is not None
    assert champion_now.is_active is True  # the parent stays active
    assert champion_now.superseded_by == ""
    assert await _ledger_is_empty(w.store)
    assert w.llm.judge_requests == []
    assert w.events.emitted == []
    assert sorted(episode_id for episode_id, _ in w.memory.validity_updates) == _ALL_FIVE  # AD-579c, as before


async def test_flag_off_restores_immediate_supersession(world: _World) -> None:
    w = world
    off = SystemConfig(dreaming=DreamingConfig(procedure_challenger_enabled=False))
    built = build_procedure_challenger(
        config=off,
        procedure_store=w.store,
        episodic_memory=w.memory,
        llm_client=w.llm,
        emit_event_fn=w.events.emit,
        rng=random.Random(1326),
    )
    assert built is None
    legacy = _engine(w.memory, w.llm, w.store, built)

    assert await legacy._attempt_procedure_evolution(w.champion, _FIX_DIAGNOSIS, w.metrics) is True

    [replacement_id] = await _active_ids(w.store)  # the FIX replaced its parent on save
    assert replacement_id != w.champion.id
    replacement = await w.store.get(replacement_id)
    assert replacement is not None
    assert replacement.evolution_type == "FIX"
    assert replacement.is_active is True
    assert replacement.parent_procedure_ids == [w.champion.id]
    parent = await w.store.get(w.champion.id)
    assert parent is not None
    assert parent.is_active is False
    assert parent.superseded_by == replacement_id
    assert await _ledger_is_empty(w.store)
    assert w.llm.judge_requests == []
    assert w.events.emitted == []
    assert sorted(episode_id for episode_id, _ in w.memory.validity_updates) == _ALL_FIVE  # expired at once


# -- review round 1 (F3): the turn whose response the Step 7d rewrite prompt quotes --------------------------


_FALLBACK_TURN = "turn-1"  # the correlation id of the turn whose LLM response the fallback event carries
_FALLBACK_RESPONSE = "OBSERVATION_1"


def _fallback_payload(champion: Procedure) -> dict[str, Any]:
    """A ``PROCEDURE_FALLBACK_LEARNING`` payload with the keys ``CognitiveAgent`` emits (its ``emit_event`` call)."""
    return {
        "agent_id": "agent-ledger",
        "intent_type": _INTENT,
        "fallback_type": "execution_failure",
        "procedure_id": champion.id,
        "procedure_name": champion.name,
        "near_miss_score": 0.0,
        "rejection_reason": "the replayed totals drifted from the bank feed",
        "llm_response": _FALLBACK_RESPONSE,
        "timestamp": time.time(),
        "correlation_id": _FALLBACK_TURN,
    }


async def test_fallback_rewrite_prompt_quotes_no_held_out_turn(world: _World) -> None:
    # R1 (F3). Step 7d's rewrite prompt quotes the LLM response of the fallback turn, so that turn's episode
    # (matched by correlation id) is rewrite evidence and must not also be a situation the judge holds out: the
    # rewrite would already have read it. e1 is that turn's episode, and it sits at a held-out position.
    w = world
    w.memory.episodes[1] = replace(w.memory.episodes[1], correlation_id=_FALLBACK_TURN)
    w.engine.set_records_store(None)  # startup binds it, and with it the fallback queue that Step 7d drains
    inputs = {episode.id: episode.user_input for episode in w.memory.episodes}

    # Premises: five episodes; e1 alone is from the turn the event names (its response is the one quoted); and,
    # with no source turn named, the split holds e1 out.
    payload = _fallback_payload(w.champion)
    recalled = await w.memory.recall_by_intent(_INTENT)
    assert [episode.id for episode in recalled] == _ALL_FIVE
    assert [episode.id for episode in recalled if episode.correlation_id == payload["correlation_id"]] == ["e1"]
    unpinned = await w.challenger.prepare(w.champion, recalled)
    assert unpinned is not None
    assert [episode.id for episode in unpinned.held_out_episodes] == ["e1", "e3"]

    await w.engine.on_procedure_fallback_learning(payload)
    stats = await w.engine._process_fallback_learning()

    assert (stats["evolved"], stats["processed"]) == (1, 1)
    ledger = w.store.challenges
    assert ledger is not None
    [pending] = await ledger.list_by_status("pending")  # one challenger is recorded
    assert pending.champion_id == w.champion.id
    assert "e1" not in pending.held_out_episode_ids
    assert pending.used_episode_ids[0] == "e1"  # the turn's episode is first among the rewrite's
    held_out = await w.memory.get_by_ids(list(pending.held_out_episode_ids))
    assert held_out  # an empty held-out set would make the check below vacuous
    assert all(episode.correlation_id != _FALLBACK_TURN for episode in held_out)
    [rewrite] = w.llm.rewrites
    assert _FALLBACK_RESPONSE in rewrite.prompt  # the turn's response is quoted ...
    assert "Episode ID: e1\n" in rewrite.prompt  # ... beside the turn's own episode
    assert inputs["e1"] in rewrite.prompt
    for held_out_id in pending.held_out_episode_ids:  # and no held-out situation reaches the prompt
        assert f"Episode ID: {held_out_id}\n" not in rewrite.prompt
        assert inputs[held_out_id] not in rewrite.prompt
