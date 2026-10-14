"""AD-1326 (#1510) Milestone 3: the dream engine's three FIX sites and Step 7d-2 under the challenger flow.

``prompts/ad-1326-procedure-challenger-champion.md``. Each FIX site of ``DreamingEngine`` asks the
challenger service ``prepare`` before the rewrite and ``submit`` after it: Step 7b
(``_evolve_degraded_procedures``), Step 7d (``_process_fallback_learning``) and the proactive scan
(``_attempt_procedure_evolution``). Step 7d-2 runs the challenger cycle inside ``dream_cycle`` and expires
the source episodes of a promoted challenger; ``consolidate_for_shutdown`` never runs it.

Three groups of test, by what each needs:

* The step 7d-2 and shutdown tests need no store and no model, only the engine and the cycle's
  report, so they use a stub challenger (``_StubChallenger``) whose ``run_cycle`` returns a fixed
  ``ChallengeCycleReport`` or raises.
* The site tests run a real ``ProcedureChallenger`` from ``build_procedure_challenger`` over a real
  ``ProcedureStore`` on ``tmp_path`` (its real ledger), because what they check is what a site hands
  the challenger and what it does with the answer: a refusal, a challenger saved inactive, the rewrite's
  episodes. The LLM (``_ScriptedLLM``) and the episodic memory (``_Episodes``) are doubles carrying what
  the real seams carry: real ``LLMRequest``/``LLMResponse`` with ``answered_tier``/``answered_model``, and
  real ``Episode`` objects with ``get_by_ids(ids, *, for_evidence=False)`` and a recorded
  ``update_episode_validity``.
* One test (``test_dream_cycle_files_judges_and_promotes_a_challenger_and_expires_its_sources``) goes beyond
  the contract's bullets: it drives that real stack through a single ``dream_cycle()``, the one place where
  the real challenger's report reaches the real expiry step, which the stub tests cannot cross.

The engine helper follows ``tests/test_ad1156_plan_mode_learning.py``: a real ``HebbianRouter`` and
``TrustNetwork`` and a ``DreamingConfig`` sized for a test.
"""

from __future__ import annotations

import inspect
import json
import logging
import random
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.procedure_challenger import ChallengeCycleReport, build_procedure_challenger
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import Procedure, ProcedureStep
from probos.config import DreamingConfig, SystemConfig
from probos.config_models.cognition import PROCEDURE_EVOLUTION_EPISODE_LIMIT
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.types import DreamReport, Episode, LLMRequest, LLMResponse

_INTENT = "reconcile_ledger"
_MARKER = "MARKER-STEP"
_DEEP_MODEL = "claude-opus-4-6"
_STANDARD_MODEL = "claude-sonnet-4-6"  # answers the standard tier: the evolution gate and the judge
_BATCHES = ("amber", "birch", "cedar", "dahlia", "elm")  # the batch each of e0..e4 reconciled
_EPISODE_ID_LINES = re.compile(r"^Episode ID: (\S+)$", re.MULTILINE)
_REWRITE_EPISODES = ["e0", "e2", "e4"]  # of e0..e4 the held-out e1 and e3 stay out of the rewrite

_FIX_PROCEDURE: dict[str, Any] = {
    "name": "Reconcile a ledger batch (verified)",
    "description": "Reconcile one ledger batch against the bank feed and verify every total",
    "steps": [
        {"step_number": 1, "action": "Open the ledger batch", "expected_output": "the batch is open"},
        {
            "step_number": 2,
            "action": f"{_MARKER}: cross-check every total against the bank feed",
            "fallback_action": "flag it",
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


class _ScriptedLLM:
    """The calls a dream makes: the deep-tier rewrite, the standard-tier evolution gate, the head-to-head judge.

    The judge prefers whichever candidate carries ``_MARKER``, which only the rewrite's procedure does.
    """

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    @property
    def rewrites(self) -> list[LLMRequest]:
        return [request for request in self.requests if request.tier == "deep"]

    @property
    def judge_requests(self) -> list[LLMRequest]:
        return [request for request in self.requests if "=== CANDIDATE 1 ===" in request.prompt]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.tier == "deep":
            content, model = json.dumps(_FIX_PROCEDURE), _DEEP_MODEL
        elif "=== CANDIDATE 1 ===" in request.prompt:
            preferred = 1 if _MARKER in _candidate(request.prompt, 1) else 2
            content, model = json.dumps({"preferred": str(preferred), "reason": "it verifies the totals"}), _STANDARD_MODEL
        else:
            content, model = "YES\nthe diagnosis holds", _STANDARD_MODEL
        return LLMResponse(
            content=content,
            model=model,
            tier=request.tier,
            tokens_used=32,
            request_id=request.id,
            answered_tier=request.tier,
            answered_model=model,
        )


class _Episodes:
    """The episodic memory a dream cycle and the challenger read, with the expiry calls, sweeps and recalls recorded."""

    def __init__(self, episodes: list[Episode]) -> None:
        self.episodes = list(episodes)
        self.validity_updates: list[tuple[str, float]] = []
        self.sweeps = 0
        self.recalls: list[tuple[str, int]] = []  # the (intent_type, k) of each ``recall_by_intent`` call

    async def get_stats(self) -> dict[str, int]:
        return {"total": len(self.episodes)}

    async def recent(self, k: int = 10) -> list[Episode]:
        return list(self.episodes[:k])

    async def get_embeddings(self, episode_ids: list[str]) -> dict[str, list[float]]:
        return {}  # no embeddings: the cycle skips clustering, which these tests do not need

    async def sweep_episode_decay(self, activation_tracker: Any) -> dict[str, int]:
        self.sweeps += 1  # Step 7f2, which runs after Step 7d-2
        return {"swept": 0, "reinforced": 0}

    async def recall_by_intent(
        self, intent_type: str, k: int = 5, *, include_self_contradicted: bool = False,
    ) -> list[Episode]:
        self.recalls.append((intent_type, k))
        matching = [ep for ep in self.episodes if any(item.get("intent") == intent_type for item in ep.outcomes)]
        return matching[:k]

    async def get_by_ids(self, episode_ids: list[str], *, for_evidence: bool = False) -> list[Episode]:
        by_id = {ep.id: ep for ep in self.episodes}
        return [by_id[episode_id] for episode_id in episode_ids if episode_id in by_id]

    async def update_episode_validity(self, episode_id: str, valid_until: float) -> bool:
        self.validity_updates.append((episode_id, valid_until))
        return True


class _StubChallenger:
    """A challenger whose cycle returns a fixed report or raises; every call it gets is recorded."""

    def __init__(self, report: ChallengeCycleReport | None = None, *, raises: Exception | None = None) -> None:
        self._report = report or ChallengeCycleReport()
        self._raises = raises
        self.calls: list[str] = []

    async def run_cycle(self) -> ChallengeCycleReport:
        self.calls.append("run_cycle")
        if self._raises is not None:
            raise self._raises
        return self._report


# -- the engine and the world -------------------------------------------------------------------------------


def _dream_config(**overrides: Any) -> DreamingConfig:
    return DreamingConfig(
        idle_threshold_seconds=1.0, dream_interval_seconds=1.0, replay_episode_count=50,
        pathway_strengthening_factor=0.03, pathway_weakening_factor=0.02, prune_threshold=0.01,
        trust_boost=0.1, trust_penalty=0.1, pre_warm_top_k=5, **overrides,
    )


def _engine(memory: Any, **kwargs: Any) -> DreamingEngine:
    router = HebbianRouter(decay_rate=0.995, reward=0.05)
    trust = TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999)
    config = kwargs.pop("config", None) or _dream_config()
    engine = DreamingEngine(router, trust, memory, config, **kwargs)
    # Startup binds the records store late (startup/finalize.py), and the fallback-learning queue and the
    # observed-thread set are created inside that setter, not in ``__init__``: a bare engine has no queue for
    # Step 7d to drain. Binding it the way startup does keeps the engine as production builds it.
    engine.set_records_store(None)
    return engine


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
class _Stack:
    store: ProcedureStore
    memory: _Episodes
    llm: _ScriptedLLM
    champion: Procedure
    engine: DreamingEngine


@asynccontextmanager
async def _stack(
    tmp_path: Path, episodes: list[Episode], *, dreaming: DreamingConfig | None = None,
) -> AsyncIterator[_Stack]:
    """A started store holding a degraded champion (5 selections, 3 fallbacks) and an engine with a real challenger.

    ``dreaming`` sets the settings the challenger reads (the defaults when omitted)."""
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    try:
        champion = _champion()
        await store.save(champion)
        for _ in range(5):
            await store.record_selection(champion.id)
        for _ in range(3):
            await store.record_fallback(champion.id)
        memory, llm = _Episodes(episodes), _ScriptedLLM()
        challenger = build_procedure_challenger(
            config=SystemConfig() if dreaming is None else SystemConfig(dreaming=dreaming),  # the challenger's settings
            procedure_store=store,
            episodic_memory=memory,
            llm_client=llm,
            emit_event_fn=None,
            rng=random.Random(1326),
        )
        assert challenger is not None
        engine = _engine(memory, llm_client=llm, procedure_store=store, procedure_challenger=challenger)
        yield _Stack(store, memory, llm, champion, engine)
    finally:
        await store.stop()


def _fallback_event(champion: Procedure, fallback_type: str) -> dict[str, Any]:
    return {
        "procedure_id": champion.id,
        "procedure_name": champion.name,
        "fallback_type": fallback_type,
        "llm_response": "The batch was reconciled by cross-checking every total against the bank feed.",
        "rejection_reason": "the replayed totals drifted from the bank feed",
        "intent_type": _INTENT,
    }


def _rewrite_episode_ids(request: LLMRequest) -> list[str]:
    """The ids of the episodes a rewrite prompt shows, in order."""
    return _EPISODE_ID_LINES.findall(request.prompt)


async def _active_ids(store: ProcedureStore) -> list[str]:
    return [entry["id"] for entry in await store.list_active()]


# -- Step 7d-2 ----------------------------------------------------------------------------------------------


async def test_step_7d2_runs_the_cycle_and_expires_superseded_sources() -> None:
    memory = _Episodes(_episodes())
    carried = (memory.episodes[1], memory.episodes[3])  # e1 and e3: a promoted challenger's source episodes
    stub = _StubChallenger(ChallengeCycleReport(judge_calls=8, comparisons=4, promoted=1, superseded_episodes=carried))
    engine = _engine(memory, procedure_challenger=stub)

    before = time.time()
    report = await engine.dream_cycle()
    after = time.time()

    assert isinstance(report, DreamReport)
    assert stub.calls == ["run_cycle"]
    assert sorted(episode_id for episode_id, _ in memory.validity_updates) == ["e1", "e3"]  # both, and only those
    assert all(before <= valid_until <= after for _, valid_until in memory.validity_updates)


async def test_step_7d2_failure_is_logged_and_the_cycle_continues(caplog: pytest.LogCaptureFixture) -> None:
    memory = _Episodes(_episodes())
    stub = _StubChallenger(raises=RuntimeError("ledger unavailable"))
    engine = _engine(memory, procedure_challenger=stub)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.dreaming"):
        report = await engine.dream_cycle()

    failures = [
        record for record in caplog.records
        if record.name == "probos.cognitive.dreaming"
        and record.levelno == logging.WARNING
        and "Step 7d-2" in record.getMessage()
    ]
    assert len(failures) == 1
    assert "ledger unavailable" in failures[0].getMessage()
    assert stub.calls == ["run_cycle"]
    assert isinstance(report, DreamReport)
    assert memory.sweeps == 1  # Step 7f2 runs after Step 7d-2: the cycle went on
    assert memory.validity_updates == []  # and nothing was expired on the strength of a failed cycle


# -- the three FIX sites ------------------------------------------------------------------------------------


async def test_degraded_scan_fix_becomes_a_challenger(tmp_path: Path) -> None:
    async with _stack(tmp_path, _episodes()) as s:
        procedures: list[Procedure] = []

        evolved = await s.engine._evolve_degraded_procedures(s.memory.episodes, procedures)  # Step 7b

        assert evolved == 1  # counted
        [pending] = await s.store.challenges.list_by_status("pending")
        assert pending.champion_id == s.champion.id
        assert [procedure.id for procedure in procedures] == [pending.challenger_id]  # appended to the cycle's list
        assert procedures[0].evolution_type == "FIX"
        assert procedures[0].is_active is False
        stored = await s.store.get(pending.challenger_id)
        assert stored is not None
        assert stored.is_active is False
        parent = await s.store.get(s.champion.id)
        assert parent is not None
        assert parent.is_active is True
        assert parent.superseded_by == ""
        assert await _active_ids(s.store) == [s.champion.id]
        [rewrite] = s.llm.rewrites
        assert _rewrite_episode_ids(rewrite) == _REWRITE_EPISODES  # the held-out e1 and e3 never reach it
        assert s.memory.validity_updates == []  # the champion keeps its sources until a challenger wins


@pytest.mark.parametrize("fallback_type", ["execution_failure", "quality_gate"])
async def test_fallback_fix_becomes_a_challenger_for_failure_and_near_miss(
    tmp_path: Path, fallback_type: str,
) -> None:
    async with _stack(tmp_path, _episodes()) as s:
        await s.engine.on_procedure_fallback_learning(_fallback_event(s.champion, fallback_type))

        stats = await s.engine._process_fallback_learning()  # Step 7d

        assert stats["evolved"] == 1
        assert stats["processed"] == 1
        [pending] = await s.store.challenges.list_by_status("pending")
        assert pending.champion_id == s.champion.id
        result = await s.store.get(pending.challenger_id)
        assert result is not None
        assert result.evolution_type == "FIX"
        assert result.is_active is False  # the result is a challenger, not a replacement
        assert result.parent_procedure_ids == [s.champion.id]
        parent = await s.store.get(s.champion.id)  # legacy deactivated it on an execution_failure
        assert parent is not None
        assert parent.is_active is True
        assert parent.superseded_by == ""
        assert await _active_ids(s.store) == [s.champion.id]
        [rewrite] = s.llm.rewrites
        assert _rewrite_episode_ids(rewrite) == _REWRITE_EPISODES
        assert s.memory.validity_updates == []


async def test_fallback_without_episodes_skips_the_rewrite_under_challengers(tmp_path: Path) -> None:
    async with _stack(tmp_path, []) as s:
        await s.engine.on_procedure_fallback_learning(_fallback_event(s.champion, "execution_failure"))
        before = time.time()

        stats = await s.engine._process_fallback_learning()

        assert stats == {"evolved": 0, "processed": 1, "skipped_cooldown": 0, "negative_veto_flagged": 0}
        assert s.llm.requests == []  # no rewrite, no call of any kind
        assert s.engine._addressed_degradations[s.champion.id] >= before  # the cooldown is recorded
        assert await s.store.challenges.list_by_status("pending") == []
        parent = await s.store.get(s.champion.id)
        assert parent is not None
        assert parent.is_active is True
        # The cooldown holds: the same fallback again is skipped, and still nothing is asked.
        await s.engine.on_procedure_fallback_learning(_fallback_event(s.champion, "execution_failure"))
        again = await s.engine._process_fallback_learning()
        assert (again["evolved"], again["skipped_cooldown"]) == (0, 1)
        assert s.llm.requests == []


async def _drive_step_7b(stack: _Stack) -> int:
    return await stack.engine._evolve_degraded_procedures(stack.memory.episodes, [])


async def _drive_proactive_scan(stack: _Stack) -> int:
    return (await stack.engine.proactive_procedure_scan())["evolved"]


@pytest.mark.parametrize("drive", [_drive_step_7b, _drive_proactive_scan], ids=["step-7b", "proactive-scan"])
async def test_prepare_refusal_records_the_cooldown(
    tmp_path: Path, drive: Callable[[_Stack], Awaitable[int]],
) -> None:
    # Two episodes are fewer comparison situations than a decision needs, so the challenger service
    # refuses before any rewrite; the site must still record that it tried.
    async with _stack(tmp_path, _episodes()[:2]) as s:
        before = time.time()

        assert await drive(s) == 0

        assert s.llm.rewrites == []  # the refusal came before the rewrite
        assert await s.store.challenges.list_by_status("pending") == []
        assert s.engine._addressed_degradations[s.champion.id] >= before  # the cooldown is recorded
        parent = await s.store.get(s.champion.id)
        assert parent is not None
        assert parent.is_active is True
        asked = len(s.llm.requests)  # the proactive scan's evolution gate is a call; Step 7b makes none
        # The cooldown holds: a second pass asks nothing more and rewrites nothing.
        assert await drive(s) == 0
        assert len(s.llm.requests) == asked
        assert s.llm.rewrites == []


async def test_proactive_evolution_reports_false_when_the_challenger_cannot_be_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The plan passes and the rewrite runs; then the ledger refuses the row, so `submit` answers None and the
    # proactive path must say nothing evolved rather than announce a challenger that does not exist.
    async with _stack(tmp_path, _episodes()) as s:

        async def refuse(**_fields: Any) -> None:
            raise RuntimeError("ledger unavailable")

        monkeypatch.setattr(s.store.challenges, "add_challenger", refuse)
        metrics = await s.store.get_quality_metrics(s.champion.id)
        assert metrics is not None

        evolved = await s.engine._attempt_procedure_evolution(s.champion, "FIX: high fallback rate", metrics)

        assert evolved is False
        assert len(s.llm.rewrites) == 1  # the rewrite did run
        assert await s.store.challenges.list_by_status("pending") == []
        assert await _active_ids(s.store) == [s.champion.id]


# -- review round 1 (F6): what the three producers hand the challenger -----------------------------------------


_SECOND_INTENT = "reconcile_invoice"
_INVOICE_BATCHES = ("fig", "grape", "hazel")  # the batch each of e5..e7 reconciled


def _eight_episodes() -> list[Episode]:
    """``e0..e4`` of the champion's first intent, then ``e5..e7`` of its second, newest first."""
    invoices = [
        Episode(
            id=f"e{index}",
            timestamp=2_000.0 - index,
            user_input=f"Reconcile the {batch} invoice batch against the supplier statement",
            outcomes=[{"intent": _SECOND_INTENT, "success": True, "response": f"{batch} invoice batch reconciled"}],
            agent_ids=["agent-ledger"],
        )
        for index, batch in enumerate(_INVOICE_BATCHES, start=5)
    ]
    return [*_episodes(), *invoices]


class _RecordingChallenger:
    """A challenger that records the episode ids each site offers ``prepare`` and refuses, so no rewrite follows."""

    def __init__(self) -> None:
        self.offered: list[list[str]] = []  # one list of episode ids per ``prepare`` call, in call order

    async def prepare(self, champion: Procedure, episodes: list[Any], *, source_correlation_id: str = "") -> None:
        self.offered.append([episode.id for episode in episodes])


@asynccontextmanager
async def _recording_stack(tmp_path: Path, challenger: _RecordingChallenger) -> AsyncIterator[_Stack]:
    """``_stack`` for a degraded champion of two intents over eight episodes, with ``challenger`` in the engine."""
    store = ProcedureStore(data_dir=tmp_path / "procedures")
    await store.start()
    try:
        champion = replace(_champion(), intent_types=[_INTENT, _SECOND_INTENT])
        await store.save(champion)
        for _ in range(5):
            await store.record_selection(champion.id)
        for _ in range(3):
            await store.record_fallback(champion.id)
        memory, llm = _Episodes(_eight_episodes()), _ScriptedLLM()
        engine = _engine(memory, llm_client=llm, procedure_store=store, procedure_challenger=challenger)
        yield _Stack(store, memory, llm, champion, engine)
    finally:
        await store.stop()


async def _drive_step_7d(stack: _Stack) -> int:
    await stack.engine.on_procedure_fallback_learning(_fallback_event(stack.champion, "execution_failure"))
    return (await stack.engine._process_fallback_learning())["evolved"]


@pytest.mark.parametrize(
    "drive", [_drive_step_7b, _drive_proactive_scan, _drive_step_7d], ids=["7b", "proactive", "7d"],
)
async def test_producers_cap_recall_at_the_shared_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drive: Callable[[_Stack], Awaitable[int]],
) -> None:
    # R1 (F6). The three producers cap what they recall at one limit, the one the challenger settings are
    # validated against; a site that stops capping, or caps at a limit of its own, offers `prepare` episodes the
    # validator never counted. The limit is lowered to 4. The memory recalls at most five episodes for one intent
    # (its default k), so eight recalled episodes take a champion of two intents: e0..e4 of the first and e5..e7
    # of the second.
    monkeypatch.setattr("probos.cognitive.dreaming.PROCEDURE_EVOLUTION_EPISODE_LIMIT", 4)
    recorder = _RecordingChallenger()
    async with _recording_stack(tmp_path, recorder) as s:
        recalled = [ep.id for intent in (_INTENT, _SECOND_INTENT) for ep in await s.memory.recall_by_intent(intent)]
        assert recalled == [f"e{index}" for index in range(8)]  # the premise: eight recalled, twice the limit

        assert await drive(s) == 0  # the recording challenger refuses, so nothing is rewritten

        assert recorder.offered == [["e0", "e1", "e2", "e3"]]  # exactly the first four, offered once


# R3 (R3-4). The real Step 7d recall: the test above lowers the limit and recalls through a recording challenger, so
# no test asks what ``_recall_evidence_by_intent`` itself asks of the memory.

_SOURCE_TURN = "turn-7f3a"  # the turn whose LLM response the fallback event's rewrite quotes
_TEN_BATCHES = ("amber", "birch", "cedar", "dahlia", "elm", "fig", "grape", "hazel", "iris", "juniper")


def _ten_episodes() -> list[Episode]:
    """``e0..e9`` of the champion's one intent, newest first; ``e1`` is the turn the fallback came from."""
    return [
        Episode(
            id=f"e{index}",
            timestamp=2_000.0 - index,
            user_input=f"Reconcile the {batch} ledger batch against the bank feed",
            outcomes=[{"intent": _INTENT, "success": True, "response": f"{batch} batch reconciled"}],
            agent_ids=["agent-ledger"],
            correlation_id=_SOURCE_TURN if index == 1 else "",
        )
        for index, batch in enumerate(_TEN_BATCHES)
    ]


async def test_step_7d_recalls_the_shared_limit_through_the_real_helper(tmp_path: Path) -> None:
    # The reviewer's case. The memory recalls five episodes unless it is asked for more, yet these settings, which the
    # validator accepts, need ten: five held out. So Step 7d's own recall helper must ask for the shared limit. Asking
    # for the default leaves `prepare` five episodes, two held out and three situations short of the five a decision
    # needs: it refuses, and the cooldown keeps the champion out of the next cycles.
    settings = _dream_config(
        procedure_challenger_used_contexts=0,
        procedure_challenger_held_out_episodes=5,
        procedure_challenger_min_decisions=5,
    )
    real_default = inspect.signature(EpisodicMemory.recall_by_intent).parameters["k"].default
    assert real_default == 5  # premise: the real memory recalls five episodes unless it is asked for more
    assert inspect.signature(_Episodes.recall_by_intent).parameters["k"].default == real_default  # the double's too
    assert PROCEDURE_EVOLUTION_EPISODE_LIMIT == 2 * real_default  # premise: ten are wanted and five come by default
    async with _stack(tmp_path, _ten_episodes(), dreaming=settings) as s:
        assert len(s.memory.episodes) == PROCEDURE_EVOLUTION_EPISODE_LIMIT  # premise: ten recallable episodes
        assert len(await s.memory.recall_by_intent(_INTENT)) == real_default  # premise: the default recall gives five
        s.memory.recalls.clear()  # that premise's recall is not the helper's
        await s.engine.on_procedure_fallback_learning(
            {**_fallback_event(s.champion, "execution_failure"), "correlation_id": _SOURCE_TURN},
        )

        stats = await s.engine._process_fallback_learning()  # Step 7d, through the real recall helper

        assert s.memory.recalls == [(_INTENT, PROCEDURE_EVOLUTION_EPISODE_LIMIT)]  # the helper asked for the limit
        assert stats == {"evolved": 1, "processed": 1, "skipped_cooldown": 0, "negative_veto_flagged": 0}
        [rewrite] = s.llm.rewrites  # one rewrite request
        [pending] = await s.store.challenges.list_by_status("pending")
        assert pending.champion_id == s.champion.id
        assert len(set(pending.held_out_episode_ids)) == 5  # five held-out ids...
        assert "e1" not in pending.held_out_episode_ids  # ...none of them the turn the fallback came from
        assert "e1" in _rewrite_episode_ids(rewrite)  # which the rewrite shows
        # The cooldown is not asserted: Step 7d records it after every rewrite attempt, repaired flow or not ("Record
        # attempt regardless of outcome"), so it cannot tell the two flows apart. The rewrite request does.


# -- the whole chain through one dream cycle (beyond the bullets: the seam the stub tests cannot cross) ----------


async def test_dream_cycle_files_judges_and_promotes_a_challenger_and_expires_its_sources(tmp_path: Path) -> None:
    # Step 7b files the challenger and Step 7d-2 judges it in the same cycle; the real challenger's own
    # report is what the cycle hands on for expiry, so nothing here is stubbed between the two steps.
    async with _stack(tmp_path, _episodes()) as s:
        report = await s.engine.dream_cycle()

        assert report.procedures_evolved == 1  # Step 7b counted the challenger
        [challenger] = [procedure for procedure in report.procedures if procedure.evolution_type == "FIX"]
        assert len(s.llm.rewrites) == 1
        assert len(s.llm.judge_requests) == 8  # Step 7d-2: four situations, each judged in both orders
        champion = await s.store.get(s.champion.id)
        assert champion is not None
        assert champion.is_active is False
        assert champion.superseded_by == challenger.id
        assert await _active_ids(s.store) == [challenger.id]
        assert sorted(episode_id for episode_id, _ in s.memory.validity_updates) == ["e0", "e1", "e2", "e3", "e4"]


# -- shutdown -----------------------------------------------------------------------------------------------


async def test_shutdown_consolidation_never_runs_the_challenger_cycle() -> None:
    memory = _Episodes(_episodes())
    stub = _StubChallenger(
        ChallengeCycleReport(judge_calls=8, comparisons=4, promoted=1, superseded_episodes=(memory.episodes[1],)),
    )
    engine = _engine(memory, procedure_challenger=stub)

    report = await engine.consolidate_for_shutdown()

    assert isinstance(report, DreamReport)
    assert report.episodes_replayed == 5  # the cheap steps ran
    assert stub.calls == []  # and the challenger cycle was not among them
    assert memory.validity_updates == []
