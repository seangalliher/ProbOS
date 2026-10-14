"""AD-1326 (#1510), milestone 3a: ``ProcedureChallenger`` -- prepare, submit, run_cycle, build.

Contract: ``prompts/ad-1326-procedure-challenger-champion.md`` (the challenger tests, D1-D6; the ``R1`` tests are
review round 1, D9; the ``R2`` tests are review round 2, D10; the ``R3`` tests are review round 3, D11).

Every test runs a real ``ProcedureStore`` and its challenger ledger on ``tmp_path`` (the
``store`` fixture stops it, pass or fail), real ``Procedure`` / ``ProcedureStep`` / ``Episode``
objects, and the real ``ProcedureJudge`` over a seeded ``random.Random``. The doubles carry what
the real seam carries:

* ``_FakeJudgeLLM`` receives the real ``LLMRequest`` the judge built, works out from its text which
  candidate is shown first and which situation it is, and returns a real ``LLMResponse`` with
  ``answered_tier`` / ``answered_model`` set the way ``OpenAICompatibleClient`` sets them (a verifier
  attempt that fell back answers with ``answered_tier="standard"``).
* ``_FakeEpisodes`` implements ``get_by_ids(ids, *, for_evidence=False)`` over real episodes, honours
  missing ids and records ``update_episode_validity``.
* ``_FakeEmit`` records ``(event_type, payload)``.

The store builds its ledger itself (with the default clock), so there is no clock to inject; the
only randomness, the judge's order pick, is seeded.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import random
import re
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Callable, Collection, Iterator, Sequence
from contextlib import ExitStack, asynccontextmanager, closing, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from probos.cognitive.procedure_challenger import (
    ChallengeCycleReport,
    ProcedureChallenger,
    build_procedure_challenger,
    split_held_out,
)
from probos.cognitive.procedure_challenges import ChallengeRecord, ProcedureChallengeLedger
from probos.cognitive.procedure_judge import ProcedureJudge
from probos.cognitive.procedure_ranking import PairOutcome, bradley_terry
from probos.cognitive.procedure_store import ProcedureStore
from probos.cognitive.procedures import EvolutionResult, Procedure, ProcedureStep
from probos.cognitive.verifier_independence import VerifierJudgePolicy
from probos.config import CognitiveConfig, DreamingConfig, SystemConfig
from probos.config_models.cognition import PROCEDURE_EVOLUTION_EPISODE_LIMIT
from probos.event_persistence import is_routed
from probos.events import EventType
from probos.storage.sqlite_factory import default_factory
from probos.types import (
    EPISODE_PLAN_MODE_KEY,
    Episode,
    LLMRequest,
    LLMResponse,
    episode_ran_in_plan_mode,
)

CHAMPION_ID = "champion-1"
CHALLENGER_LOGGER = "probos.cognitive.procedure_challenger"
PROCEDURES_DB = "procedures.db"
LEDGER_DB = "procedures_challenges.db"
LLM_REASON = "SENTINEL judge reasoning"
_SEED = 1326

# The payload ``ProcedureChallenger._emit`` builds: ids, decision, reason code and counts.
_PAYLOAD_KEYS = frozenset({
    "challenger_id", "champion_id", "decision", "reason", "wins", "losses", "ties", "decisions",
    "held_out_wins", "held_out_decisions", "strength", "judge_independence",
})

# The sections of ``build_judge_prompt``; each candidate's first line is its description (``render_candidate``
# no longer opens with ``Purpose:``, R1 F2).
_PROMPT = re.compile(
    r"=== READ-ONLY SITUATION[^\n]*\nRequest: (?P<situation>\S+)\n.*?\n=== END SITUATION ===\n\n"
    r"=== CANDIDATE 1 ===\nroutine of (?P<first>\S+)\n.*?\n=== END CANDIDATE 1 ===\n\n"
    r"=== CANDIDATE 2 ===\nroutine of (?P<second>\S+)\n.*?\n=== END CANDIDATE 2 ===",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _JudgeCall:
    situation: str
    challenger: str
    first_shown: str
    tier: str


class _Script:
    """What the judge double answers for a (situation, challenger) pair.

    An outcome is ``challenger``, ``champion`` or ``tie`` (a valid reply, the same in both orders), or
    ``unreadable`` (no JSON), ``llm_error`` (an error response), ``raises`` (the call raises) or
    ``<winner>-fallback`` (a valid reply answered by the ``standard`` tier instead of the one asked).
    """

    def __init__(self, default: str = "challenger") -> None:
        self.default = default
        self.by_pair: dict[tuple[str, str], str] = {}
        self.by_situation: dict[str, str] = {}

    def for_challenger(self, challenger: str, outcomes: Sequence[str]) -> _Script:
        """``outcomes[i]`` is the answer for situation ``ep-i``."""
        for index, outcome in enumerate(outcomes):
            self.by_pair[(f"ep-{index}", challenger)] = outcome
        return self

    def __call__(self, situation: str, challenger: str) -> str:
        if (situation, challenger) in self.by_pair:
            return self.by_pair[(situation, challenger)]
        return self.by_situation.get(situation, self.default)


class _FakeJudgeLLM:
    """The judge's LLM client: reads the real prompt, answers per ``script`` in whichever order it is shown."""

    def __init__(
        self, script: Callable[[str, str], str], *, model: str = "claude-sonnet-4-6",
        fallback_model: str = "claude-sonnet-4-6",
    ) -> None:
        self._script = script
        self.model = model
        self.fallback_model = fallback_model
        self.requests: list[LLMRequest] = []
        self.calls: list[_JudgeCall] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        match = _PROMPT.search(request.prompt)
        assert match is not None, "the judge prompt no longer has the sections this double reads"
        situation, first, second = match["situation"], match["first"], match["second"]
        challenger = second if first == CHAMPION_ID else first
        outcome = self._script(situation, challenger)
        self.calls.append(_JudgeCall(situation, challenger, first, request.tier))
        if outcome == "raises":
            raise RuntimeError("judge provider unavailable")
        answered_tier: str | None = request.tier
        answered_model: str | None = self.model
        if outcome.endswith("-fallback"):
            outcome = outcome.removesuffix("-fallback")
            answered_tier, answered_model = "standard", self.fallback_model
        if outcome == "llm_error":
            return LLMResponse(
                content="", model=self.model, tier=request.tier, error="upstream 503",
                answered_tier=answered_tier, answered_model=answered_model,
            )
        if outcome == "unreadable":
            content = "Both candidates look reasonable; this reply is not JSON."
        elif outcome == "tie":
            content = json.dumps({"preferred": "tie", "reason": f"{LLM_REASON}: tie"})
        else:
            winner = challenger if outcome == "challenger" else CHAMPION_ID
            content = json.dumps({"preferred": "1" if first == winner else "2", "reason": f"{LLM_REASON}: {outcome}"})
        return LLMResponse(
            content=content, model=self.model, tier=request.tier, tokens_used=3,
            answered_tier=answered_tier, answered_model=answered_model,
        )


class _FakeEpisodes:
    """Real episodes by id; an id it does not hold is missing from the answer, as in the real store."""

    def __init__(self, episodes: Sequence[Episode]) -> None:
        self._by_id = {episode.id: episode for episode in episodes}
        self.unreadable: str | None = None  # "empty" (returns []) or "raises"
        self.calls: list[tuple[list[str], bool]] = []
        self.validity_updates: list[tuple[str, float]] = []

    async def get_by_ids(self, episode_ids: list[str], *, for_evidence: bool = False) -> list[Episode]:
        self.calls.append((list(episode_ids), for_evidence))
        if self.unreadable == "raises":
            raise RuntimeError("episodic memory unavailable")
        if self.unreadable == "empty":
            return []
        return [self._by_id[episode_id] for episode_id in episode_ids if episode_id in self._by_id]

    async def update_episode_validity(self, episode_id: str, *, valid_until: float) -> bool:
        self.validity_updates.append((episode_id, valid_until))
        return True


class _FakeEmit:
    """``emit_event_fn``: records ``(event_type, payload)``; raises ``error`` after recording when given one."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[EventType, dict[str, Any]]] = []
        self._error = error

    def __call__(self, event_type: EventType, payload: dict[str, Any]) -> None:
        self.calls.append((event_type, payload))
        if self._error is not None:
            raise self._error


class _CrashingStore:
    """The real store, except that one step of a promotion raises once -- the process dying there."""

    def __init__(self, inner: ProcedureStore, fail_on: str) -> None:
        self._inner = inner
        self._fail_on = fail_on
        self.crashed = False

    async def get(self, procedure_id: str) -> Any:
        return await self._inner.get(procedure_id)

    async def save(self, procedure: Any, *, content_diff: str = "", change_summary: str = "") -> str:
        if self._fail_on == "save" and procedure.is_active and not self.crashed:
            self.crashed = True
            raise RuntimeError("process died before the challenger was activated")
        return await self._inner.save(procedure, content_diff=content_diff, change_summary=change_summary)

    async def deactivate(self, procedure_id: str, superseded_by: str = "") -> None:
        if self._fail_on == "deactivate" and not self.crashed:
            self.crashed = True
            raise RuntimeError("process died before the champion was retired")
        await self._inner.deactivate(procedure_id, superseded_by=superseded_by)

    async def get_evolution_metadata(self, procedure_id: str) -> dict[str, str]:
        return await self._inner.get_evolution_metadata(procedure_id)

    async def sync_routing_index(self, procedure_id: str) -> bool:
        return await self._inner.sync_routing_index(procedure_id)

    async def routing_state(self, procedure_id: str) -> tuple[bool, str] | None:
        # R6 (R6-1): the challenger takes every activity decision from the columns through this method.
        return await self._inner.routing_state(procedure_id)


class _FakeLedgerConnection:
    """The ledger's real connection, except that the first ``commit`` after the ``terminal`` status UPDATE raises.

    The UPDATE runs on the real connection and its transaction is left open, as a commit that failed at the end of
    a ledger write leaves it (R3-2); every other call, ``ROLLBACK`` included, passes through. ``failures`` counts
    how often the injected failure fired, so a test can show that its setup reached it.
    """

    def __init__(self, inner: Any, terminal: str) -> None:
        self._inner = inner
        self._terminal = terminal
        self._terminal_update_run = False
        self.failures = 0

    async def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        parameters = args[0] if args else kwargs.get("parameters")
        if sql.startswith("UPDATE procedure_challenges SET status") and parameters and parameters[0] == self._terminal:
            self._terminal_update_run = True
        return await self._inner.execute(sql, *args, **kwargs)

    async def commit(self) -> None:
        if self._terminal_update_run and self.failures == 0:
            self.failures += 1
            raise sqlite3.OperationalError("disk I/O error")
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FakeLedgerFactory:
    """The default connection factory, except that the challenger ledger's connection is a ``_FakeLedgerConnection``."""

    def __init__(self, terminal: str) -> None:
        self._terminal = terminal
        self.ledger_connection: _FakeLedgerConnection | None = None

    async def connect(self, db_path: str) -> Any:
        connection = await default_factory.connect(db_path)
        if Path(db_path).name != LEDGER_DB:
            return connection
        self.ledger_connection = _FakeLedgerConnection(connection, self._terminal)
        return self.ledger_connection


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _episodes(count: int = 4, *, plan_mode: Sequence[int] = ()) -> list[Episode]:
    """``ep-0`` ... ``ep-{count-1}``, newest first; ``plan_mode`` lists the indexes recorded under plan mode."""
    return [
        Episode(
            id=f"ep-{index}",
            user_input=f"ep-{index}",
            timestamp=1000.0 - index,
            outcomes=[
                {"intent": "read_file", "success": True},
                *([{EPISODE_PLAN_MODE_KEY: True}] if index in plan_mode else []),
            ],
        )
        for index in range(count)
    ]


def _procedure(
    procedure_id: str, *, evolution_type: str = "CAPTURED", parents: Sequence[str] = (), generation: int = 0,
) -> Procedure:
    return Procedure(
        id=procedure_id,
        name="Read a file",
        description=f"routine of {procedure_id}",
        steps=[
            ProcedureStep(step_number=1, action="Open the file", expected_output="the file is open"),
            ProcedureStep(step_number=2, action="Summarise its contents", fallback_action="Report the error"),
        ],
        intent_types=["read_file"],
        extraction_date=1_000.0,
        evolution_type=evolution_type,
        generation=generation,
        parent_procedure_ids=list(parents),
    )


def _champion() -> Procedure:
    return _procedure(CHAMPION_ID)


def _fix_result(
    challenger_id: str, *, evolution_type: str = "FIX", parents: Sequence[str] | None = None,
    tier: str = "deep", model: str = "claude-sonnet-5.5",
) -> EvolutionResult:
    """What a FIX rewrite returns: an ACTIVE procedure, a diff and the optimizer's provenance."""
    procedure = _procedure(
        challenger_id, evolution_type=evolution_type,
        parents=[CHAMPION_ID] if parents is None else parents, generation=1,
    )
    return EvolutionResult(
        procedure=procedure,
        content_diff=f"--- {CHAMPION_ID}\n+++ {challenger_id}\n",
        change_summary=f"{challenger_id} fixes the failing step",
        optimizer_tier=tier,
        optimizer_model=model,
    )


@dataclass
class _Rig:
    store: ProcedureStore
    ledger: ProcedureChallengeLedger
    episodes: _FakeEpisodes
    llm: _FakeJudgeLLM
    events: _FakeEmit
    dreaming: DreamingConfig
    policy: VerifierJudgePolicy
    champion: Procedure
    challenger: ProcedureChallenger

    def challenger_over(self, store_like: Any) -> ProcedureChallenger:
        """A fresh service over ``store_like`` with the same ledger, doubles and config (a restart)."""
        return ProcedureChallenger(
            store=store_like,
            ledger=self.ledger,
            episodes=self.episodes,
            judge=ProcedureJudge(self.llm, self.policy, rng=random.Random(_SEED)),
            config=self.dreaming,
            emit_event_fn=self.events,
        )


async def _rig(
    store: ProcedureStore,
    *,
    script: Callable[[str, str], str] | None = None,
    available: Sequence[Episode] | None = None,
    verifier: str | None = None,
    dreaming: dict[str, Any] | None = None,
    emit: _FakeEmit | None = None,
    store_proxy: Any = None,
) -> _Rig:
    """The champion saved active, the challenger service wired over ``store``'s own ledger."""
    champion = _champion()
    await store.save(champion)
    ledger = store.challenges
    assert ledger is not None, "the store's challenger ledger did not open"
    rig = _Rig(
        store=store,
        ledger=ledger,
        episodes=_FakeEpisodes(_episodes() if available is None else available),
        llm=_FakeJudgeLLM(script or _Script(), model=verifier or "claude-sonnet-4-6"),
        events=emit or _FakeEmit(),
        dreaming=DreamingConfig(**(dreaming or {})),
        policy=VerifierJudgePolicy.from_cognitive(CognitiveConfig(llm_model_verifier=verifier)),
        champion=champion,
        challenger=None,  # type: ignore[arg-type]
    )
    rig.challenger = rig.challenger_over(store if store_proxy is None else store_proxy)
    return rig


async def _pend(rig: _Rig, challenger_id: str, *, optimizer_model: str | None = None) -> Procedure:
    """``prepare`` then ``submit`` over four default episodes: a pending challenger on four situations.

    ``optimizer_model`` is the model the rewrite reports having been answered by (``_fix_result``'s default when ``None``).
    """
    plan = await rig.challenger.prepare(rig.champion, _episodes())
    assert plan is not None, "prepare refused the default four episodes"
    result = _fix_result(challenger_id) if optimizer_model is None else _fix_result(challenger_id, model=optimizer_model)
    saved = await rig.challenger.submit(plan, result)
    assert saved is not None, f"submit refused challenger {challenger_id}"
    return saved


async def _record(rig: _Rig, challenger_id: str) -> ChallengeRecord:
    record = await rig.ledger.get(challenger_id)
    assert record is not None, f"no ledger row for {challenger_id}"
    return record


async def _routed_ids(store: ProcedureStore) -> list[str]:
    return sorted(row["id"] for row in await store.list_active())


def _counts(report: ChallengeCycleReport) -> tuple[int, int, int, int, int]:
    """(judge calls, situations judged, deferred, promoted, retired)."""
    return (report.judge_calls, report.comparisons, report.deferred, report.promoted, report.retired)


def _decisions(events: _FakeEmit) -> list[tuple[str, str, str]]:
    return [(payload["challenger_id"], payload["decision"], payload["reason"]) for _kind, payload in events.calls]


async def _matched_ids(store: ProcedureStore) -> list[str]:
    """What routing finds for the champion's description: ``find_matching`` reads the semantic index, not SQLite."""
    return sorted(row["id"] for row in await store.find_matching(_champion().description))


async def _activate(store: ProcedureStore, procedure_id: str) -> None:
    """Save a stored procedure active again, keeping its diff and summary: how a promoted challenger's row looks."""
    stored = await store.get(procedure_id)
    assert stored is not None, f"no procedure {procedure_id} to activate"
    meta = await store.get_evolution_metadata(procedure_id)
    await store.save(
        replace(stored, is_active=True),
        content_diff=meta.get("content_diff", ""), change_summary=meta.get("change_summary", ""),
    )


async def _count_win(rig: _Rig, challenger_id: str, episode_id: str = "ep-0") -> None:
    """One counted win recorded in the ledger the way a judged situation is, without running the judge."""
    pending = await _record(rig, challenger_id)
    await rig.ledger.record_comparison(
        challenger_id=challenger_id, champion_id=CHAMPION_ID, episode_id=episode_id,
        split="held_out" if episode_id in pending.held_out_episode_ids else "used",
        first_shown="challenger", outcome="challenger", counted=True, judgements=[],
    )


async def _after(created_at: float) -> None:
    """Wait until the clock the ledger stamps rows with has moved past ``created_at`` (it can tick coarsely)."""
    while time.time() <= created_at:
        await asyncio.sleep(0.005)


def _index_says_active(store: ProcedureStore, procedure_id: str) -> bool:
    """What the live semantic index holds for ``procedure_id``: its entry's ``is_active`` flag.

    SQLite decides routing (R2-1: ``find_matching`` admits a match only through an active row), so
    ``_matched_ids`` no longer shows a stale entry; this reads the entry itself, the thing a retry must repair.
    """
    collection = store._chroma_collection
    assert collection is not None, "the store has no semantic index to read"
    entry = collection.get(ids=[procedure_id], include=["metadatas"])
    assert entry["metadatas"], f"the semantic index holds no entry for {procedure_id}"
    return entry["metadatas"][0]["is_active"]


@contextmanager
def _index_outage(
    store: ProcedureStore, method: str, *, only_ids: Collection[str] | None = None,
) -> Iterator[list[str]]:
    """The store's live Chroma collection raises from ``method`` inside the block; yields the ids it was hit for.

    With ``only_ids`` it raises only for a call whose ``ids`` contain one of them, and every other call passes
    through to the real method (R2-2: the outage of one procedure's entry, the rest of the index healthy).
    A test asserts the outage was hit: one whose setup never reached the failing write proves nothing.
    The method is restored when the block ends, pass or fail.
    """
    collection = store._chroma_collection
    assert collection is not None, "the store has no semantic index to take down"
    real = getattr(collection, method)
    hit: list[str] = []

    def fail(*args: Any, **kwargs: Any) -> Any:
        ids = list(kwargs.get("ids", []))
        if only_ids is not None and not any(identifier in only_ids for identifier in ids):
            return real(*args, **kwargs)
        hit.extend(ids)
        raise RuntimeError(f"the semantic index {method} is down")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(collection, method, fail)
        yield hit


@asynccontextmanager
async def _started_store(data_dir: Path, *, connection_factory: Any = None) -> AsyncIterator[ProcedureStore]:
    """A real store started on ``data_dir``, stopped when the block ends, pass or fail (a second store in one test)."""
    procedure_store = ProcedureStore(data_dir=data_dir, connection_factory=connection_factory)
    await procedure_store.start()
    try:
        yield procedure_store
    finally:
        await procedure_store.stop()


def _ledger_status(data_dir: Path, challenger_id: str) -> str | None:
    """The status an independent reader of the ledger file finds: only what has been committed to it."""
    with closing(sqlite3.connect(str(data_dir / LEDGER_DB))) as reader:
        row = reader.execute(
            "SELECT status FROM procedure_challenges WHERE challenger_id = ?", (challenger_id,),
        ).fetchone()
    return None if row is None else row[0]


def _checkpoint(path: Path) -> None:
    """Fold ``path``'s write-ahead log into its main file, test-side: the one thing a raw copy of the main file carries."""
    with closing(sqlite3.connect(str(path))) as connection:
        busy = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
    assert busy == 0, f"{path.name} could not be checkpointed"


def _wal_size(path: Path) -> int:
    """Bytes in ``path``'s write-ahead log file (0 when there is none)."""
    wal = path.with_name(f"{path.name}-wal")
    return wal.stat().st_size if wal.exists() else 0


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[ProcedureStore]:
    procedure_store = ProcedureStore(data_dir=tmp_path / "procedures")
    await procedure_store.start()
    try:
        yield procedure_store
    finally:
        await procedure_store.stop()


# ---------------------------------------------------------------------------
# split_held_out
# ---------------------------------------------------------------------------

# (episodes recalled, held-out setting, positions held out). At most the setting, never more than half.
_SPLIT_CASES = [
    (0, 0, []), (0, 2, []), (0, 10, []),
    (1, 0, []), (1, 2, []), (1, 10, []),
    (2, 0, []), (2, 2, [1]), (2, 10, [1]),
    (3, 0, []), (3, 2, [1]), (3, 10, [1]),
    (5, 0, []), (5, 2, [1, 3]), (5, 10, [1, 3]),
    (10, 0, []), (10, 2, [1, 3]), (10, 10, [1, 3, 5, 7, 9]),
]


@pytest.mark.parametrize(
    ("count", "held_out", "held_positions"), _SPLIT_CASES,
    ids=[f"{count}-episodes-held-out-{held_out}" for count, held_out, _ in _SPLIT_CASES],
)
def test_split_held_out_takes_odd_positions_and_at_most_half(
    count: int, held_out: int, held_positions: list[int],
) -> None:
    evolution, kept = split_held_out(_episodes(count), held_out)

    assert [episode.id for episode in kept] == [f"ep-{index}" for index in held_positions]
    assert [episode.id for episode in evolution] == [
        f"ep-{index}" for index in range(count) if index not in held_positions
    ]
    assert len(kept) <= min(held_out, count // 2)


@dataclass(frozen=True)
class _Plain:
    """A plain object with an ``id``: all that ``split_held_out`` reads of an episode."""

    id: str


def test_split_held_out_fills_around_pinned_episodes() -> None:
    """R2 R2-4: pinned episodes lead the evolution half and are never held out, yet the ceiling is the whole recall's."""
    recalled = [_Plain(f"e{index}") for index in range(10)]
    layouts: list[tuple[set[str], list[str], list[str]]] = [
        # (pinned, held out in recalled order, evolution: the pinned first, then the rest in recalled order).
        # Fill order with held_out=5: odd positions 1, 3, 5, 7, 9, then even positions 8, 6, 4, 2 and 0 last.
        ({"e1"}, ["e3", "e5", "e7", "e8", "e9"], ["e1", "e0", "e2", "e4", "e6"]),
        ({"e1", "e3", "e5", "e7", "e9"}, ["e0", "e2", "e4", "e6", "e8"], ["e1", "e3", "e5", "e7", "e9"]),
        ({"e0"}, ["e1", "e3", "e5", "e7", "e9"], ["e0", "e2", "e4", "e6", "e8"]),
        # More than half the recall pinned: held-out falls short of the ceiling of five (the documented limit).
        ({f"e{index}" for index in range(6)}, ["e6", "e7", "e8", "e9"], [f"e{index}" for index in range(6)]),
    ]

    for pinned, held_ids, evolution_ids in layouts:
        evolution, held = split_held_out(recalled, 5, pinned=pinned)

        assert [e.id for e in held] == held_ids, f"pinned {sorted(pinned)}: held out"
        assert [e.id for e in evolution] == evolution_ids, f"pinned {sorted(pinned)}: evolution"
        assert not {e.id for e in held} & pinned, f"pinned {sorted(pinned)}: a pinned episode was held out"
        assert sorted(e.id for e in (*evolution, *held)) == sorted(e.id for e in recalled), (
            f"pinned {sorted(pinned)}: an episode was lost or repeated"
        )

    # Nothing pinned: exactly the call without ``pinned``, and the odd-position split (at most ``held_out``, at most half).
    for count in range(0, 11):
        episodes = [_Plain(f"e{index}") for index in range(count)]
        for held_out in range(0, 7):
            held_ids = [f"e{index}" for index in range(1, count, 2)][: min(held_out, count // 2)]
            plain = split_held_out(episodes, held_out)

            assert split_held_out(episodes, held_out, pinned=frozenset()) == plain, f"{count} episodes, {held_out}"
            assert [e.id for e in plain[1]] == held_ids, f"{count} episodes, held out {held_out}: held out"
            assert [e.id for e in plain[0]] == [e.id for e in episodes if e.id not in held_ids], (
                f"{count} episodes, held out {held_out}: evolution"
            )


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def _blank_id_episodes() -> list[Episode]:
    """Four episodes of which two have no id: only two are usable situations."""
    return [Episode(id="ep-0"), Episode(id=""), Episode(id="ep-2"), Episode(id="")]


@pytest.mark.parametrize(
    "recalled",
    [
        pytest.param(_episodes(0), id="none"),
        pytest.param(_episodes(1), id="one"),
        pytest.param(_episodes(2), id="two"),
        pytest.param(_blank_id_episodes(), id="two-of-four-have-no-id"),
    ],
)
async def test_prepare_refuses_when_situations_are_below_min_decisions(
    store: ProcedureStore, recalled: list[Episode],
) -> None:
    rig = await _rig(store)

    assert await rig.challenger.prepare(rig.champion, recalled) is None

    # The boundary: three episodes give the three situations the default min_decisions asks for.
    plan = await rig.challenger.prepare(rig.champion, _episodes(3))
    assert plan is not None
    assert plan.context_episode_ids == ("ep-0", "ep-2", "ep-1")
    assert rig.llm.requests == []
    assert await rig.ledger.pending_count(CHAMPION_ID) == 0


async def test_prepare_plans_used_and_held_out_situations_from_ten_episodes(store: ProcedureStore) -> None:
    rig = await _rig(store)

    plan = await rig.challenger.prepare(rig.champion, _episodes(10))

    assert plan is not None
    assert plan.champion_id == CHAMPION_ID
    assert [episode.id for episode in plan.held_out_episodes] == ["ep-1", "ep-3"]
    assert [episode.id for episode in plan.evolution_episodes] == [f"ep-{i}" for i in (0, 2, 4, 5, 6, 7, 8, 9)]
    # The rewrite sees every evolution episode; only the first two are comparison situations, plus the held-out ones.
    assert plan.context_episode_ids == ("ep-0", "ep-2", "ep-1", "ep-3")


@pytest.mark.parametrize("limit", [1, 2])
async def test_prepare_refuses_at_max_pending_per_champion(store: ProcedureStore, limit: int) -> None:
    rig = await _rig(store, dreaming={"procedure_challenger_max_pending_per_champion": limit})
    recalled = _episodes()

    for index in range(limit):
        assert await rig.challenger.prepare(rig.champion, recalled) is not None, f"below the limit at {index}"
        await _pend(rig, f"ch-{index}")

    assert await rig.ledger.pending_count(CHAMPION_ID) == limit
    assert await rig.challenger.prepare(rig.champion, recalled) is None
    assert rig.llm.requests == []
    # The limit is per champion: another champion with nothing pending is still planned for.
    assert await rig.challenger.prepare(_procedure("champion-2"), recalled) is not None


def _turn_episodes(count: int = 6) -> list[Episode]:
    """``_episodes(count)`` with ``ep-1`` and ``ep-3`` recorded under one correlation id: the turn ``turn-1``."""
    return [
        replace(episode, correlation_id="turn-1") if episode.id in ("ep-1", "ep-3") else episode
        for episode in _episodes(count)
    ]


async def test_prepare_never_holds_out_the_source_turn(store: ProcedureStore) -> None:
    """R1 F3: the turn whose response the rewrite prompt quotes is rewrite evidence, so it is never held out."""
    rig = await _rig(store)
    recalled = _turn_episodes()
    turn = [(ep.id, ep.correlation_id) for ep in recalled if ep.correlation_id]
    assert turn == [("ep-1", "turn-1"), ("ep-3", "turn-1")]

    plain = await rig.challenger.prepare(rig.champion, recalled)

    # The premise: without the parameter the split is split_held_out's, and it holds both turn episodes out.
    assert plain is not None
    assert [ep.id for ep in plain.held_out_episodes] == ["ep-1", "ep-3"]
    assert [ep.id for ep in plain.evolution_episodes] == ["ep-0", "ep-2", "ep-4", "ep-5"]
    assert plain.context_episode_ids == ("ep-0", "ep-2", "ep-1", "ep-3")

    pinned = await rig.challenger.prepare(rig.champion, recalled, source_correlation_id="turn-1")

    assert pinned is not None
    # R2 (R2-4) moved these three lines and the two ledger lines below. They pinned the split of the non-turn
    # episodes ALONE (held out ["ep-2", "ep-5"], evolution ["ep-1", "ep-3", "ep-0", "ep-4"]), so the held-out
    # ceiling was half of a smaller pool and the validator's count was not exact. The ceiling is now the whole
    # recall's, min(2, 6 // 2) == 2, and the fill order is positions 1, 3, 5, 4, 2, 0 minus the pinned 1 and 3.
    assert [ep.id for ep in pinned.evolution_episodes] == ["ep-1", "ep-3", "ep-0", "ep-2"]  # the turn leads
    assert [ep.id for ep in pinned.held_out_episodes] == ["ep-4", "ep-5"]  # positions 5 and 4: the turn is skipped
    assert pinned.context_episode_ids == ("ep-1", "ep-3", "ep-4", "ep-5")
    for ignored in ("", None, 7, b"turn-1"):  # no source turn named: the plain split
        plan = await rig.challenger.prepare(
            rig.champion, recalled, source_correlation_id=ignored,  # type: ignore[arg-type]
        )
        assert plan == plain, f"source_correlation_id={ignored!r} must leave split_held_out's split"
    # Across the seam: the ledger records the pinned split, so the turn's situations are judged as "used".
    assert await rig.challenger.submit(pinned, _fix_result("ch-a")) is not None
    record = await _record(rig, "ch-a")
    assert record.used_episode_ids == ("ep-1", "ep-3", "ep-0", "ep-2")
    assert record.held_out_episode_ids == ("ep-4", "ep-5")
    assert record.context_episode_ids == pinned.context_episode_ids


@pytest.mark.parametrize(
    "turn_positions",
    [(0,), (1,), (5,), (9,), (1, 3), (1, 3, 5, 7, 9), (0, 2, 4, 6, 8)],
    ids=lambda positions: "turn-at-" + "-".join(str(position) for position in positions),
)
async def test_source_pinned_recall_reaches_the_same_situations(
    store: ProcedureStore, turn_positions: tuple[int, ...],
) -> None:
    """R2 R2-4: pinning the source turn costs no comparison situation the validator counted."""
    rig = await _rig(store)
    limit = PROCEDURE_EVOLUTION_EPISODE_LIMIT
    recalled = [
        replace(episode, correlation_id="turn-1") if index in turn_positions else episode
        for index, episode in enumerate(_episodes(limit))
    ]
    turn_ids = [episode.id for episode in recalled if episode.correlation_id == "turn-1"]
    assert len(turn_ids) == len(turn_positions)  # the premise: the turn is where the parameter says
    assert await rig.ledger.pending_count(CHAMPION_ID) == 0  # an empty ledger: only the situations can refuse

    async def planned(config: DreamingConfig, source: str) -> Any:
        return await replace(rig, dreaming=config).challenger_over(store).prepare(
            rig.champion, recalled, source_correlation_id=source,
        )

    def situations(plan: Any) -> int:
        return 0 if plan is None else len(plan.context_episode_ids)

    reached_a_plan = 0
    for used in range(0, 11):
        for held_out in range(0, 6):
            # Unvalidated, measured with min_decisions=1 as test_every_accepted_configuration_can_produce_a_challenge does.
            measuring = DreamingConfig.model_construct(
                procedure_challenger_used_contexts=used,
                procedure_challenger_held_out_episodes=held_out,
                procedure_challenger_min_decisions=1,
            )
            ceiling = min(held_out, limit // 2)
            expected = min(used, limit - ceiling) + ceiling
            without_turn, with_turn = await planned(measuring, ""), await planned(measuring, "turn-1")
            where = f"used {used}, held out {held_out}, turn at {turn_positions}"

            assert situations(without_turn) == expected, f"{where}: the plain split's situations"
            assert situations(with_turn) == expected, f"{where}: the turn-pinned split's situations"
            if with_turn is None:
                continue
            reached_a_plan += 1
            assert all(ep.correlation_id != "turn-1" for ep in with_turn.held_out_episodes), f"{where}: held out"
            assert [ep.id for ep in with_turn.evolution_episodes][: len(turn_ids)] == turn_ids, f"{where}: lead"
    assert reached_a_plan == 11 * 6 - 1  # every configuration but (used 0, held out 0), which has no situation at all

    # The reviewer's six accepted configurations (used, held out, min_decisions): each validates, and the turn pinned
    # (the item turn-at-1 is the reviewer's own case) still leaves exactly min_decisions situations.
    for used, held_out, min_decisions in [(0, 5, 5), (1, 5, 6), (2, 5, 7), (3, 5, 8), (4, 5, 9), (5, 5, 10)]:
        config = DreamingConfig(
            procedure_challenger_used_contexts=used,
            procedure_challenger_held_out_episodes=held_out,
            procedure_challenger_min_decisions=min_decisions,
        )
        plan = await planned(config, "turn-1")
        assert plan is not None, f"({used}, {held_out}, {min_decisions}) with the turn at {turn_positions}: no plan"
        assert len(plan.context_episode_ids) == min_decisions, (used, held_out, min_decisions, turn_positions)


async def test_every_accepted_configuration_can_produce_a_challenge(store: ProcedureStore) -> None:
    """R1 F6: the validator neither admits a configuration that cannot decide nor refuses one that can."""
    rig = await _rig(store)
    limit = PROCEDURE_EVOLUTION_EPISODE_LIMIT
    recalled = _episodes(limit)
    assert await rig.ledger.pending_count(CHAMPION_ID) == 0  # an empty ledger: only the situations can refuse

    async def planned(config: DreamingConfig) -> Any:
        return await replace(rig, dreaming=config).challenger_over(store).prepare(rig.champion, recalled)

    accepted: set[tuple[int, int, int]] = set()
    cannot_decide: set[tuple[int, int, int]] = set()
    out_of_bounds: set[tuple[int, int, int]] = set()
    for used in range(0, 13):
        for held_out in range(0, 8):
            # What prepare assembles from a full recall, measured with min_decisions=1 (never refuses on the count
            # unless there is no situation at all). Unvalidated: min_decisions=1 is itself refused when there is none.
            measuring = DreamingConfig.model_construct(
                procedure_challenger_used_contexts=used,
                procedure_challenger_held_out_episodes=held_out,
                procedure_challenger_min_decisions=1,
            )
            measured_plan = await planned(measuring)
            situations = 0 if measured_plan is None else len(measured_plan.context_episode_ids)
            for min_decisions in range(0, 13):
                combination = (used, held_out, min_decisions)
                in_bounds = used <= limit and held_out <= limit // 2 and 1 <= min_decisions <= limit
                try:
                    config = DreamingConfig(
                        procedure_challenger_used_contexts=used,
                        procedure_challenger_held_out_episodes=held_out,
                        procedure_challenger_min_decisions=min_decisions,
                    )
                except ValidationError as error:
                    if "challenge can have" in str(error):
                        assert in_bounds, f"{combination}: refused as unreachable although it is out of bounds"
                        assert situations < min_decisions, (
                            f"{combination}: refused as unreachable, but prepare assembles {situations} situations"
                        )
                        cannot_decide.add(combination)
                    else:
                        assert not in_bounds, f"{combination}: refused for a reason other than its bounds: {error}"
                        out_of_bounds.add(combination)
                    continue
                assert in_bounds, f"{combination}: accepted although it is out of bounds"
                plan = await planned(config)
                assert plan is not None, f"{combination}: accepted, but prepare never returns a plan for it"
                assert len(plan.context_episode_ids) >= min_decisions, combination
                accepted.add(combination)

    assert len(accepted) + len(cannot_decide) + len(out_of_bounds) == 13 * 8 * 13
    # The grid reached both sides of every boundary (a grid that never refused or never accepted proves nothing).
    assert {(10, 5, 10), (2, 2, 4)} <= accepted  # the largest configuration, and the default's own limit
    assert {(0, 0, 1), (2, 2, 5)} <= cannot_decide
    assert {(11, 0, 1), (0, 6, 1), (2, 2, 0), (2, 2, 11)} <= out_of_bounds


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


async def test_submit_saves_the_challenger_inactive_and_routing_keeps_the_champion(store: ProcedureStore) -> None:
    rig = await _rig(store)
    plan = await rig.challenger.prepare(rig.champion, _episodes())
    assert plan is not None
    result = _fix_result("ch-a", tier="deep", model="claude-sonnet-5.5")
    assert result.procedure.is_active is True  # a rewrite hands back an active procedure

    saved = await rig.challenger.submit(plan, result)

    assert saved is not None and saved.id == "ch-a"
    assert saved.is_active is False
    assert await _routed_ids(store) == [CHAMPION_ID]
    stored = await store.get("ch-a")
    assert stored is not None and stored.is_active is False
    assert stored.evolution_type == "FIX" and stored.parent_procedure_ids == [CHAMPION_ID]
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is True and champion.superseded_by == ""
    record = await _record(rig, "ch-a")
    assert (record.status, record.champion_id) == ("pending", CHAMPION_ID)
    assert (record.optimizer_tier, record.optimizer_model) == ("deep", "claude-sonnet-5.5")
    assert record.used_episode_ids == ("ep-0", "ep-2")
    assert record.held_out_episode_ids == ("ep-1", "ep-3")
    assert record.context_episode_ids == plan.context_episode_ids
    assert await store.get_evolution_metadata("ch-a") == {
        "content_diff": result.content_diff, "change_summary": result.change_summary,
    }


@pytest.mark.parametrize(
    ("evolution_type", "parents"),
    [
        pytest.param("DERIVED", [CHAMPION_ID], id="derived"),
        pytest.param("CAPTURED", [CHAMPION_ID], id="captured"),
        pytest.param("FIX", ["some-other-procedure"], id="fix-of-another-parent"),
        pytest.param("FIX", [CHAMPION_ID, "some-other-procedure"], id="fix-with-an-extra-parent"),
        pytest.param("FIX", [], id="fix-without-a-parent"),
    ],
)
async def test_submit_refuses_non_fix_or_wrong_parent(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture, evolution_type: str, parents: list[str],
) -> None:
    rig = await _rig(store)
    plan = await rig.challenger.prepare(rig.champion, _episodes())
    assert plan is not None

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
        saved = await rig.challenger.submit(plan, _fix_result("ch-a", evolution_type=evolution_type, parents=parents))

    assert saved is None
    assert any("not a FIX of champion" in record.getMessage() for record in caplog.records)
    assert await store.get("ch-a") is None  # nothing was saved
    assert await rig.ledger.get("ch-a") is None  # nothing was recorded
    assert await _routed_ids(store) == [CHAMPION_ID]


async def test_submit_failure_leaves_the_champion_unchanged(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture,
) -> None:
    rig = await _rig(store)
    plan = await rig.challenger.prepare(rig.champion, _episodes())
    assert plan is not None
    rig.ledger.detach()
    with pytest.raises(RuntimeError):  # the premise: a detached ledger refuses every call
        await rig.ledger.get("ch-a")

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
        saved = await rig.challenger.submit(plan, _fix_result("ch-a"))

    assert saved is None
    failures = [r for r in caplog.records if r.levelno == logging.WARNING and "could not be recorded" in r.getMessage()]
    assert len(failures) == 1
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is True and champion.superseded_by == ""
    assert await _routed_ids(store) == [CHAMPION_ID]


async def test_overlapping_submits_never_exceed_the_pending_cap(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture,
) -> None:
    """R1 F5: the cap is enforced where the challenger is recorded, not only checked when the rewrite is planned."""
    rig = await _rig(store, dreaming={"procedure_challenger_max_pending_per_champion": 2})
    await _pend(rig, "ch-a")
    # Two rewrites of the champion start while one challenger is pending: both are planned, the cap is not reached yet.
    first = await rig.challenger.prepare(rig.champion, _episodes())
    second = await rig.challenger.prepare(rig.champion, _episodes())
    assert first is not None and second is not None
    assert await rig.ledger.pending_count(CHAMPION_ID) == 1

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
        kept = await rig.challenger.submit(first, _fix_result("ch-b"))
        over = await rig.challenger.submit(second, _fix_result("ch-c"))

    assert kept is not None and kept.id == "ch-b"
    assert (await _record(rig, "ch-b")).status == "pending"
    assert over is None
    refused = await _record(rig, "ch-c")
    assert refused.status == "retired" and refused.decision_reason.startswith("pending_limit:")
    saved = await store.get("ch-c")
    assert saved is not None and saved.is_active is False  # its inactive row stays accounted for in the ledger
    assert _decisions(rig.events) == [("ch-c", "retired", "pending_limit")]
    _kind, payload = rig.events.calls[0]
    assert (payload["wins"], payload["decisions"], payload["strength"]) == (0, 0, None)
    assert payload["judge_independence"] == []
    assert await rig.ledger.pending_count(CHAMPION_ID) == 2
    assert await _routed_ids(store) == [CHAMPION_ID]
    limits = [r for r in caplog.records if r.levelno == logging.WARNING and "pending_limit" in r.getMessage()]
    assert len(limits) == 1 and "ch-c" in limits[0].getMessage()


# ---------------------------------------------------------------------------
# run_cycle: nothing to do, budgets, unresolved challengers
# ---------------------------------------------------------------------------


async def test_no_pending_challengers_cycle_is_a_no_op(store: ProcedureStore) -> None:
    rig = await _rig(store)

    report = await rig.challenger.run_cycle()

    assert report == ChallengeCycleReport()
    assert rig.llm.requests == []
    assert rig.episodes.calls == []
    assert rig.events.calls == []
    assert await rig.ledger.recent_cycles() == []
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is True and champion.superseded_by == ""
    assert await _routed_ids(store) == [CHAMPION_ID]


async def test_budget_exhaustion_defers_and_never_promotes(store: ProcedureStore) -> None:
    rig = await _rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 0})
    await _pend(rig, "ch-a")

    for cycle in range(1, 5):
        report = await rig.challenger.run_cycle()
        assert _counts(report) == (0, 0, 4, 0, 0), f"cycle {cycle}: four situations deferred, nothing judged"
        record = await _record(rig, "ch-a")
        assert (record.status, record.cycles_pending) == ("pending", cycle)
    last = await rig.challenger.run_cycle()

    assert _counts(last) == (0, 0, 4, 0, 1)
    record = await _record(rig, "ch-a")
    assert record.status == "retired" and record.decision_reason.startswith("expired:")
    assert rig.llm.requests == []
    assert await rig.ledger.list_by_status("promoted") == []
    assert _decisions(rig.events) == [("ch-a", "retired", "expired")]
    assert await _routed_ids(store) == [CHAMPION_ID]
    cycles = await rig.ledger.recent_cycles()
    assert len(cycles) == 5
    assert all(row["judge_calls"] == 0 and row["deferred"] == 4 for row in cycles)


async def test_budget_of_two_judges_one_situation_per_cycle(store: ProcedureStore) -> None:
    rig = await _rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 2})
    await _pend(rig, "ch-a")
    order = ["ep-0", "ep-2", "ep-1", "ep-3"]  # the situations in the order the plan listed them

    for cycle in range(1, 5):
        report = await rig.challenger.run_cycle()
        assert (report.judge_calls, report.comparisons, report.deferred) == (2, 1, 4 - cycle), f"cycle {cycle}"
        assert len(rig.llm.requests) == 2 * cycle
        assert [c.episode_id for c in await rig.ledger.comparisons("ch-a")] == order[:cycle]
        if cycle < 4:
            record = await _record(rig, "ch-a")
            assert (record.status, record.cycles_pending) == ("pending", cycle)
            assert report.promoted == 0

    assert report.promoted == 1  # the fourth situation completes the evidence
    assert (await _record(rig, "ch-a")).status == "promoted"


@pytest.mark.parametrize("max_cycles", [1, 3, 5])
async def test_unresolved_challenger_expires_after_n_cycles(store: ProcedureStore, max_cycles: int) -> None:
    rig = await _rig(
        store, script=_Script("unreadable"), dreaming={"procedure_challenger_max_pending_cycles": max_cycles},
    )
    await _pend(rig, "ch-a")

    for cycle in range(1, max_cycles):
        report = await rig.challenger.run_cycle()
        record = await _record(rig, "ch-a")
        assert (record.status, record.cycles_pending) == ("pending", cycle)
        assert (report.promoted, report.retired) == (0, 0)
    final = await rig.challenger.run_cycle()

    record = await _record(rig, "ch-a")
    assert record.status == "retired" and record.decision_reason.startswith("expired:")
    assert (final.promoted, final.retired) == (0, 1)
    comparisons = await rig.ledger.comparisons("ch-a")
    assert len(comparisons) == 4 * max_cycles  # every open situation was asked again each cycle
    assert all(row.outcome == "invalid" and row.counted is False for row in comparisons)
    assert await rig.ledger.list_by_status("promoted") == []
    assert _decisions(rig.events) == [("ch-a", "retired", "expired")]
    assert await _routed_ids(store) == [CHAMPION_ID]


@pytest.mark.parametrize(
    ("kind", "recorded_outcome"),
    [
        pytest.param("unreadable", "invalid", id="unreadable-reply"),
        pytest.param("llm_error", "invalid", id="error-response"),
        pytest.param("raises", "invalid", id="call-raises"),
        pytest.param("challenger-fallback", "challenger", id="fallback-answer-is-not-counted"),
    ],
)
async def test_invalid_judgements_leave_situations_open_for_next_cycle(
    store: ProcedureStore, kind: str, recorded_outcome: str,
) -> None:
    script = _Script()
    script.by_situation["ep-1"] = kind
    # A dedicated independent verifier: only an answer from the tier asked for counts, so a fallback is recorded, not counted.
    rig = await _rig(store, script=script, verifier="gpt-5.1")
    await _pend(rig, "ch-a")

    first = await rig.challenger.run_cycle()

    assert _counts(first) == (8, 4, 0, 0, 0)
    record = await _record(rig, "ch-a")
    assert (record.status, record.cycles_pending) == ("pending", 1)
    rows = await rig.ledger.comparisons("ch-a")
    open_row = next(row for row in rows if row.episode_id == "ep-1")
    assert (open_row.outcome, open_row.counted) == (recorded_outcome, False)
    assert sum(row.counted for row in rows) == 3

    del script.by_situation["ep-1"]
    asked_before = len(rig.llm.calls)
    second = await rig.challenger.run_cycle()

    assert [call.situation for call in rig.llm.calls[asked_before:]] == ["ep-1", "ep-1"]  # only the open one, in both orders
    assert (second.judge_calls, second.comparisons, second.promoted) == (2, 1, 1)
    rows = await rig.ledger.comparisons("ch-a")
    ep1 = [(row.outcome, row.counted) for row in rows if row.episode_id == "ep-1"]
    assert ep1 == [(recorded_outcome, False), ("challenger", True)]
    decided = await _record(rig, "ch-a")
    assert decided.status == "promoted" and "decisions=4" in decided.decision_reason


# ---------------------------------------------------------------------------
# run_cycle: episodes that are unreadable, missing or plan-mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("unreadable", ["empty", "raises"])
async def test_unreadable_episodes_defer_instead_of_retiring(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture, unreadable: str,
) -> None:
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    rig.episodes.unreadable = unreadable

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
        reports = [await rig.challenger.run_cycle(), await rig.challenger.run_cycle()]

    assert reports == [ChallengeCycleReport(), ChallengeCycleReport()]
    record = await _record(rig, "ch-a")
    assert (record.status, record.cycles_pending) == ("pending", 2)
    assert rig.llm.requests == []
    assert rig.events.calls == []
    assert await rig.ledger.recent_cycles() == []
    assert any("could not be read" in r.getMessage() for r in caplog.records) is (unreadable == "raises")

    rig.episodes.unreadable = None  # readable again: the same challenger is judged and decided
    recovered = await rig.challenger.run_cycle()
    assert (recovered.comparisons, recovered.promoted) == (4, 1)


@pytest.mark.parametrize(
    ("present", "decided"),
    [
        pytest.param(["ep-0"], "insufficient_evidence", id="one-left"),
        pytest.param(["ep-0", "ep-2"], "insufficient_evidence", id="two-left"),
        pytest.param(["ep-0", "ep-2", "ep-1"], "won", id="three-left-is-enough"),
    ],
)
async def test_missing_episodes_retire_with_insufficient_evidence(
    store: ProcedureStore, present: list[str], decided: str,
) -> None:
    rig = await _rig(store, available=[episode for episode in _episodes() if episode.id in present])
    await _pend(rig, "ch-a")

    report = await rig.challenger.run_cycle()

    assert [c.episode_id for c in await rig.ledger.comparisons("ch-a")] == present
    assert (report.judge_calls, report.comparisons) == (2 * len(present), len(present))
    record = await _record(rig, "ch-a")
    assert record.decision_reason.startswith(f"{decided}:")
    assert f"decisions={len(present)}" in record.decision_reason
    if decided == "won":
        assert (record.status, report.promoted, report.retired) == ("promoted", 1, 0)
        assert _decisions(rig.events) == [("ch-a", "promoted", "won")]
    else:
        assert (record.status, report.promoted, report.retired) == ("retired", 0, 1)
        assert _decisions(rig.events) == [("ch-a", "retired", "insufficient_evidence")]
        assert await _routed_ids(store) == [CHAMPION_ID]


@pytest.mark.parametrize("plan_index", [0, 1], ids=["used-situation", "held-out-situation"])
async def test_plan_mode_episode_is_not_a_comparison_context(store: ProcedureStore, plan_index: int) -> None:
    available = _episodes(plan_mode=(plan_index,))
    assert episode_ran_in_plan_mode(available[plan_index]) is True  # the premise, from the real predicate
    rig = await _rig(store, available=available)
    await _pend(rig, "ch-a")
    skipped = f"ep-{plan_index}"

    report = await rig.challenger.run_cycle()

    assert skipped not in {call.situation for call in rig.llm.calls}
    assert skipped not in [c.episode_id for c in await rig.ledger.comparisons("ch-a")]
    assert (report.judge_calls, report.comparisons) == (6, 3)
    assert (await _record(rig, "ch-a")).status == "promoted"  # three counted situations are enough
    contexts_read_ids, contexts_read_for_evidence = rig.episodes.calls[0]
    assert skipped in contexts_read_ids  # it was read, then dropped
    assert contexts_read_for_evidence is True


# ---------------------------------------------------------------------------
# run_cycle: decisions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("better", ["ch-a", "ch-b"])
async def test_two_challengers_top_by_bradley_terry_is_promoted_and_the_other_replaced(
    store: ProcedureStore, better: str,
) -> None:
    other = "ch-b" if better == "ch-a" else "ch-a"
    script = _Script()
    script.for_challenger(better, ["challenger"] * 4)  # 4 wins, 0 losses: strength 4.5 / 0.5 = 9
    script.for_challenger(other, ["challenger", "challenger", "champion", "challenger"])  # 3 wins, 1 loss: 3.5 / 1.5
    rig = await _rig(store, script=script)
    await _pend(rig, "ch-a")
    await _pend(rig, "ch-b")

    report = await rig.challenger.run_cycle()

    assert _counts(report) == (16, 8, 0, 1, 1)
    assert (await _record(rig, better)).status == "promoted"
    replaced = await _record(rig, other)
    assert replaced.status == "retired" and replaced.decision_reason.startswith("champion_replaced:")
    assert "wins=3 losses=1 ties=0 decisions=4" in replaced.decision_reason  # it would have won alone: 3 / 4 > 0.6
    promoted = await _record(rig, better)
    assert promoted.decision_reason == "won: wins=4 losses=0 ties=0 decisions=4 held_out=2/2 promote_above=0.60"
    top, loser, champion = await store.get(better), await store.get(other), await store.get(CHAMPION_ID)
    assert top is not None and top.is_active is True
    assert loser is not None and loser.is_active is False
    assert champion is not None and champion.is_active is False and champion.superseded_by == better
    assert await _routed_ids(store) == [better]
    assert sorted(_decisions(rig.events)) == sorted(
        [(better, "promoted", "won"), (other, "retired", "champion_replaced")]
    )
    promoted_payload = next(p for _kind, p in rig.events.calls if p["decision"] == "promoted")
    assert promoted_payload["strength"] == pytest.approx(9.0, abs=1e-5)
    assert sorted(episode.id for episode in report.superseded_episodes) == ["ep-0", "ep-1", "ep-2", "ep-3"]
    assert rig.episodes.validity_updates == []  # the report carries the episodes; the dream step expires them


@pytest.mark.parametrize(
    ("top_outcomes", "bottom_outcomes", "top_strength", "bottom_strength"),
    [
        # 2 wins 2 losses (2.5 / 2.5) against 1 win 3 losses (1.5 / 3.5): the top wins half, not above 0.6.
        pytest.param(
            ["challenger", "challenger", "champion", "champion"], ["champion", "champion", "champion", "challenger"],
            1.0, 1.5 / 3.5, id="top-wins-half",
        ),
        # Four ties (0 + 2 + 0.5 over 0 + 2 + 0.5) against four losses (0.5 / 4.5): ties count against the challenger.
        pytest.param(["tie"] * 4, ["champion"] * 4, 1.0, 0.5 / 4.5, id="top-only-ties"),
    ],
)
async def test_top_candidate_that_does_not_beat_the_champion_retires_all_complete(
    store: ProcedureStore, top_outcomes: list[str], bottom_outcomes: list[str],
    top_strength: float, bottom_strength: float,
) -> None:
    script = _Script().for_challenger("ch-a", top_outcomes).for_challenger("ch-b", bottom_outcomes)
    rig = await _rig(store, script=script)
    await _pend(rig, "ch-a")
    await _pend(rig, "ch-b")

    report = await rig.challenger.run_cycle()

    assert _counts(report) == (16, 8, 0, 0, 2)
    for challenger_id in ("ch-a", "ch-b"):
        record = await _record(rig, challenger_id)
        assert record.status == "retired" and record.decision_reason.startswith("lost:")
        assert "promote_above=0.60" in record.decision_reason
        row = await store.get(challenger_id)
        assert row is not None and row.is_active is False
    assert sorted(_decisions(rig.events)) == [("ch-a", "retired", "lost"), ("ch-b", "retired", "lost")]
    strengths = {p["challenger_id"]: p["strength"] for _kind, p in rig.events.calls}
    assert strengths["ch-a"] == pytest.approx(top_strength, abs=1e-5)
    assert strengths["ch-b"] == pytest.approx(bottom_strength, abs=1e-5)
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is True and champion.superseded_by == ""
    assert await _routed_ids(store) == [CHAMPION_ID]
    assert report.superseded_episodes == ()


@pytest.mark.parametrize("how", ["deactivated", "deleted"])
async def test_champion_inactive_retires_its_challengers(store: ProcedureStore, how: str) -> None:
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    await _pend(rig, "ch-b")
    if how == "deactivated":
        await store.deactivate(CHAMPION_ID, superseded_by="a-newer-procedure")
    else:
        assert await store.delete(CHAMPION_ID) is True

    report = await rig.challenger.run_cycle()

    assert _counts(report) == (0, 0, 0, 0, 2)
    for challenger_id in ("ch-a", "ch-b"):
        record = await _record(rig, challenger_id)
        assert record.status == "retired" and record.decision_reason.startswith("champion_inactive:")
    assert rig.llm.requests == [] and rig.episodes.calls == []
    assert sorted(_decisions(rig.events)) == [
        ("ch-a", "retired", "champion_inactive"), ("ch-b", "retired", "champion_inactive"),
    ]
    assert (await rig.ledger.recent_cycles())[0]["retired"] == 2
    champion = await store.get(CHAMPION_ID)
    if how == "deactivated":
        assert champion is not None and champion.is_active is False and champion.superseded_by == "a-newer-procedure"
    else:
        assert champion is None
    assert await _routed_ids(store) == []  # a challenger is never promoted into a vacated champion's place


@pytest.mark.parametrize("sibling", [False, True], ids=["alone", "with-a-healthy-sibling"])
async def test_challenger_missing_is_retired(store: ProcedureStore, sibling: bool) -> None:
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    if sibling:
        await _pend(rig, "ch-b")
    assert await store.delete("ch-a") is True

    report = await rig.challenger.run_cycle()

    gone = await _record(rig, "ch-a")
    assert gone.status == "retired" and gone.decision_reason.startswith("challenger_missing:")
    if sibling:
        assert {call.challenger for call in rig.llm.calls} == {"ch-b"}  # nothing was spent on the missing one
        assert _counts(report) == (8, 4, 0, 1, 1)
        assert (await _record(rig, "ch-b")).status == "promoted"
        # The winner's cycle does not decide the missing challenger a second time (champion_replaced).
        assert sorted(_decisions(rig.events)) == [("ch-a", "retired", "challenger_missing"), ("ch-b", "promoted", "won")]
    else:
        assert _counts(report) == (0, 0, 0, 0, 1)
        assert rig.llm.requests == []
        assert _decisions(rig.events) == [("ch-a", "retired", "challenger_missing")]
        assert await _routed_ids(store) == [CHAMPION_ID]


@pytest.mark.parametrize(
    "fail_on",
    [
        pytest.param("save", id="challenger-still-inactive"),
        pytest.param("deactivate", id="challenger-active-champion-not-yet-retired"),
    ],
)
async def test_interrupted_promotion_is_finished_next_cycle(store: ProcedureStore, fail_on: str) -> None:
    proxy = _CrashingStore(store, fail_on)
    rig = await _rig(store, store_proxy=proxy)
    await _pend(rig, "ch-a")  # the challenger is saved inactive through the proxy: that save does not crash
    meta_before = await store.get_evolution_metadata("ch-a")

    with pytest.raises(RuntimeError, match="process died"):
        await rig.challenger.run_cycle()

    assert proxy.crashed is True
    stuck = await _record(rig, "ch-a")
    assert stuck.status == "promoting"
    assert len(await rig.ledger.comparisons("ch-a")) == 4  # the evidence was recorded before the crash
    assert rig.events.calls == []
    interrupted = await store.get("ch-a")
    assert interrupted is not None and interrupted.is_active is (fail_on == "deactivate")
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is True

    asked_before = len(rig.llm.requests)
    finisher = rig.challenger_over(store)  # a restart: a fresh service over the same store and ledger
    report = await finisher.run_cycle()

    assert (report.judge_calls, report.comparisons, report.promoted) == (0, 0, 1)
    assert len(rig.llm.requests) == asked_before  # finishing does not judge again
    assert (await _record(rig, "ch-a")).status == "promoted"
    activated = await store.get("ch-a")
    assert activated is not None and activated.is_active is True
    superseded = await store.get(CHAMPION_ID)
    assert superseded is not None and superseded.is_active is False and superseded.superseded_by == "ch-a"
    assert await _routed_ids(store) == ["ch-a"]
    assert await store.get_evolution_metadata("ch-a") == meta_before  # re-saving kept the diff and summary
    assert len(rig.events.calls) == 1
    kind, payload = rig.events.calls[0]
    assert kind is EventType.PROCEDURE_CHALLENGE_DECIDED
    assert (payload["challenger_id"], payload["decision"], payload["reason"]) == ("ch-a", "promoted", "won")
    assert (payload["wins"], payload["decisions"]) == (4, 4)
    assert sorted(episode.id for episode in report.superseded_episodes) == ["ep-0", "ep-1", "ep-2", "ep-3"]
    assert await finisher.run_cycle() == ChallengeCycleReport()  # nothing is finished twice
    assert len(rig.events.calls) == 1


async def test_fully_judged_challenger_is_decided_without_judging_again(store: ProcedureStore) -> None:
    """A cycle that finds every situation already counted (an earlier cycle ended before it could decide) decides now.

    Nothing is left to read, so an empty id list must not be taken for "episodes unreadable this cycle".
    """
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    pending = await _record(rig, "ch-a")
    for episode_id in pending.context_episode_ids:
        await rig.ledger.record_comparison(
            challenger_id="ch-a", champion_id=CHAMPION_ID, episode_id=episode_id,
            split="held_out" if episode_id in pending.held_out_episode_ids else "used",
            first_shown="challenger", outcome="challenger", counted=True, judgements=[],
        )

    report = await rig.challenger.run_cycle()

    assert (report.judge_calls, report.comparisons, report.promoted) == (0, 0, 1)
    assert rig.llm.requests == []
    assert (await _record(rig, "ch-a")).status == "promoted"
    assert await _routed_ids(store) == ["ch-a"]


# ---------------------------------------------------------------------------
# run_cycle: ties, routing and early retirements (review round 1, D9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("older", "newer", "champion_between"),
    [
        pytest.param("ch-a", "ch-b", False, id="older-has-the-smaller-id"),
        pytest.param("ch-b", "ch-a", False, id="older-has-the-larger-id"),
        # R2 (R2-6): the champion's id sorts BETWEEN the challengers' ids, the layout in which the reverted closed
        # form's roundoff separates equal records (the ids above both sort before it).
        pytest.param(
            "11111111-0000-4000-8000-000000000000", "dddddddd-0000-4000-8000-000000000000", True,
            id="champion-between-older-low",
        ),
        pytest.param(
            "dddddddd-0000-4000-8000-000000000000", "11111111-0000-4000-8000-000000000000", True,
            id="champion-between-older-high",
        ),
    ],
)
async def test_equal_strengths_fall_to_the_creation_time_tie_break(
    store: ProcedureStore, older: str, newer: str, champion_between: bool,
) -> None:
    """R1 F4: equal records give ``==`` strengths, so the creation time decides whichever id sorts first."""
    # The premise (R2-6): where the champion's id sorts among the two challengers' ids is the layout named.
    assert (min(older, newer) < CHAMPION_ID < max(older, newer)) is champion_between
    script = _Script()
    script.for_challenger(older, ["challenger", "challenger", "challenger", "champion"])  # 3 wins, 1 loss
    script.for_challenger(newer, ["challenger", "challenger", "tie", "tie"])  # 2 wins, 2 ties: three of four as well
    rig = await _rig(
        store, script=script,
        dreaming={"procedure_challenger_min_decisions": 4, "procedure_challenger_max_judge_calls_per_cycle": 16},
    )
    await _pend(rig, older)
    await _after((await _record(rig, older)).created_at)  # the ledger's clock can tick coarsely
    await _pend(rig, newer)
    assert (await _record(rig, older)).created_at < (await _record(rig, newer)).created_at  # the premise

    report = await rig.challenger.run_cycle()

    assert _counts(report) == (16, 8, 0, 1, 1)
    # The premise: the two records are a draw in strength, so only the creation time can put one ahead.
    as_result = {"challenger": "first", "champion": "second", "tie": "tie"}
    outcomes = [
        PairOutcome(challenger_id, CHAMPION_ID, as_result[comparison.outcome])  # type: ignore[arg-type]
        for challenger_id in (older, newer)
        for comparison in await rig.ledger.comparisons(challenger_id)
        if comparison.counted
    ]
    strengths = bradley_terry(outcomes, reference=CHAMPION_ID)
    assert strengths[older] == strengths[newer] and strengths[older] > 1.0
    winner = await _record(rig, older)
    assert winner.status == "promoted" and winner.decision_reason.startswith("won: wins=3 losses=1 ties=0 decisions=4")
    replaced = await _record(rig, newer)
    assert replaced.status == "retired" and replaced.decision_reason.startswith("champion_replaced:")
    assert "wins=2 losses=0 ties=2 decisions=4" in replaced.decision_reason
    assert await _routed_ids(store) == [older]
    assert sorted(_decisions(rig.events)) == sorted(
        [(older, "promoted", "won"), (newer, "retired", "champion_replaced")]
    )


@pytest.mark.parametrize("outage", ["upsert_fails", "update_fails", "champion_index_fails"])
async def test_promotion_is_sealed_only_when_the_routing_index_agrees(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture, outage: str,
) -> None:
    """R1 F1: ``find_matching`` reads only the semantic index, so ``promoted`` waits until it agrees with SQLite.

    R2 (R2-2): the challenger's entry is confirmed BEFORE the champion is deactivated, so the champion keeps routing
    while that confirmation fails (``upsert_fails``); the champion's own entry is confirmed before the seal
    (``champion_index_fails``), and routing already drops its stale entry because SQLite says it is inactive.
    """
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    assert await _matched_ids(store) == [CHAMPION_ID]  # the premise: routing starts on the champion
    methods = {
        "upsert_fails": ["upsert"], "update_fails": ["update"], "champion_index_fails": ["update", "upsert"],
    }[outage]
    only_ids = [CHAMPION_ID] if outage == "champion_index_fails" else None  # the champion's entry alone is down

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER), ExitStack() as down:
        hits = [down.enter_context(_index_outage(store, method, only_ids=only_ids)) for method in methods]
        report = await rig.challenger.run_cycle()

    assert (report.judge_calls, report.comparisons) == (8, 4)  # the challenger won every situation
    for method, hit in zip(methods, hits):
        assert hit, f"the semantic index {method} outage was never reached"
    challenger, champion = await store.get("ch-a"), await store.get(CHAMPION_ID)
    assert challenger is not None and challenger.is_active is True  # SQLite took the activation in every variant
    assert champion is not None
    promotion = await _record(rig, "ch-a")
    if outage == "update_fails":
        # Only the champion's deactivation could not reach the index, and deactivate() hides that; the sync
        # rewrote the champion's entry from SQLite, so the same cycle seals the promotion.
        assert champion.is_active is False and champion.superseded_by == "ch-a"
        assert CHAMPION_ID in hits[0]
        assert (report.promoted, promotion.status) == (1, "promoted")
        assert sorted(ep.id for ep in report.superseded_episodes) == ["ep-0", "ep-1", "ep-2", "ep-3"]
        assert _decisions(rig.events) == [("ch-a", "promoted", "won")]
        assert await _matched_ids(store) == ["ch-a"]
    else:
        # The decision is not sealed: nothing is emitted, nothing is expired, and the next cycle repeats it.
        assert (report.promoted, promotion.status) == (0, "promoting")
        assert report.superseded_episodes == ()  # the dream step expires these: not for an unsealed promotion
        assert rig.events.calls == []
        assert any(
            r.name == CHALLENGER_LOGGER and r.levelno == logging.WARNING and "stays promoting" in r.getMessage()
            for r in caplog.records
        )
        if outage == "upsert_fails":
            # R2 (R2-2) replaced what this variant used to pin: the champion inactive in SQLite and
            # `_matched_ids == []` ("neither procedure is routable"), the window in which a promotion that could not
            # confirm the challenger's entry left the lineage without a route. The challenger's entry is now
            # confirmed BEFORE the champion is touched, so the champion is never deactivated and keeps routing.
            assert champion.is_active is True and champion.superseded_by == ""  # never touched
            assert _index_says_active(store, "ch-a") is False  # the challenger's entry never took the activation
            assert await _matched_ids(store) == [CHAMPION_ID]  # the lineage keeps routing
        else:
            # champion_index_fails: the challenger's entry was confirmed, the champion's could not be rewritten.
            assert champion.is_active is False and champion.superseded_by == "ch-a"
            assert _index_says_active(store, "ch-a") is True
            assert _index_says_active(store, CHAMPION_ID) is True  # the premise: the champion's entry is stale
            assert {identifier for hit in hits for identifier in hit} == {CHAMPION_ID}  # nothing else was taken down
            assert await _matched_ids(store) == ["ch-a"]  # 3g: routing asks SQLite, which says the champion is inactive
        asked = len(rig.llm.requests)

        again = await rig.challenger.run_cycle()  # the index is back: the blocks that took it down have ended

        assert (again.judge_calls, again.comparisons, again.promoted) == (0, 0, 1)
        assert sorted(ep.id for ep in again.superseded_episodes) == ["ep-0", "ep-1", "ep-2", "ep-3"]
        assert len(rig.llm.requests) == asked  # finishing a decision never judges again
        assert (await _record(rig, "ch-a")).status == "promoted"
        assert _decisions(rig.events) == [("ch-a", "promoted", "won")]
        resumed = await store.get(CHAMPION_ID)
        assert resumed is not None and resumed.is_active is False and resumed.superseded_by == "ch-a"
        assert _index_says_active(store, CHAMPION_ID) is False  # its entry now agrees with SQLite
        assert await _matched_ids(store) == ["ch-a"]  # the challenger routes and the champion does not


async def test_repeated_promotion_does_not_deactivate_the_champion_again(store: ProcedureStore) -> None:
    """A promotion that waits on the champion's index entry repeats next cycle without touching the champion again.

    ``deactivate`` rewrites ``superseded_by`` and ``updated_at``, so the guard on ``champion.is_active`` is what keeps
    a repeat from rewriting the lineage pointer of a champion that is already inactive.
    """
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    deactivated: list[str] = []
    real_deactivate = store.deactivate

    async def counting_deactivate(procedure_id: str, superseded_by: str = "") -> None:
        deactivated.append(procedure_id)
        await real_deactivate(procedure_id, superseded_by)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(store, "deactivate", counting_deactivate)
        with _index_outage(store, "update", only_ids=[CHAMPION_ID]), _index_outage(store, "upsert", only_ids=[CHAMPION_ID]):
            first = await rig.challenger.run_cycle()
        assert (first.promoted, (await _record(rig, "ch-a")).status) == (0, "promoting")  # the premise: it waits
        assert deactivated == [CHAMPION_ID]  # the premise: the first cycle deactivated the champion once

        again = await rig.challenger.run_cycle()  # the index is back

    assert (again.promoted, (await _record(rig, "ch-a")).status) == (1, "promoted")
    assert deactivated == [CHAMPION_ID]  # the repeat found the champion inactive and left it alone
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is False and champion.superseded_by == "ch-a"


async def test_repeated_promotion_does_not_save_the_active_challenger_again(store: ProcedureStore) -> None:
    """A promotion that waits on the champion's index entry repeats next cycle without re-saving the active challenger.

    ``save`` rewrites the row from the object it is given, whose snapshot can be older than the columns (counters an
    active challenger has accumulated since), so the guard on the challenger's ``is_active`` column is what keeps a
    repeat from overwriting them.
    """
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    saved: list[str] = []
    real_save = store.save

    async def counting_save(procedure: Procedure, **kwargs: Any) -> str:
        saved.append(procedure.id)
        return await real_save(procedure, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(store, "save", counting_save)
        with _index_outage(store, "update", only_ids=[CHAMPION_ID]), _index_outage(store, "upsert", only_ids=[CHAMPION_ID]):
            first = await rig.challenger.run_cycle()
        assert (first.promoted, (await _record(rig, "ch-a")).status) == (0, "promoting")  # the premise: it waits
        assert saved == ["ch-a"]  # the premise: the first cycle activated the challenger once

        again = await rig.challenger.run_cycle()  # the index is back

    assert (again.promoted, (await _record(rig, "ch-a")).status) == (1, "promoted")
    assert saved == ["ch-a"]  # the repeat found the challenger active in its column and left it alone


async def test_restored_pair_with_a_completed_promotion_is_recorded_promoted(store: ProcedureStore) -> None:
    """R1 F7: a ``procedures.db`` that already holds the promotion, paired with an older ledger, is recorded."""
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    await _count_win(rig, "ch-a")
    await _activate(store, "ch-a")  # procedures.db as the restore leaves it: the promotion is in the file ...
    await store.deactivate(CHAMPION_ID, superseded_by="ch-a")
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is False and champion.superseded_by == "ch-a"
    assert (await _record(rig, "ch-a")).status == "pending"  # ... and the older ledger does not know it
    assert await _routed_ids(store) == ["ch-a"]
    # R4 (R4-2) moved this premise. R3 (R3-5) pinned `_matched_ids == []` here ("neither routes until the first dream
    # cycle records the promotion", the cost D11 accepted), which no longer holds: admission does not bar a pending
    # challenger whose champion is inactive and superseded by it, which is exactly the completed promotion
    # procedures.db holds. It routes before the first dream cycle (D12, R4-2); the assertions after the cycle are
    # unchanged.
    assert await _matched_ids(store) == ["ch-a"]
    assert rig.llm.requests == []

    report = await rig.challenger.run_cycle()

    assert (report.judge_calls, report.comparisons, report.promoted, report.retired) == (0, 0, 1, 0)
    assert rig.llm.requests == []
    record = await _record(rig, "ch-a")
    assert record.status == "promoted" and record.decision_reason.startswith("restored_promotion: wins=1")
    assert len(rig.events.calls) == 1
    kind, payload = rig.events.calls[0]
    assert kind is EventType.PROCEDURE_CHALLENGE_DECIDED
    assert (payload["challenger_id"], payload["decision"], payload["reason"]) == (
        "ch-a", "promoted", "restored_promotion",
    )
    assert (payload["wins"], payload["decisions"]) == (1, 1)
    assert await _matched_ids(store) == ["ch-a"]
    assert sorted(episode.id for episode in report.superseded_episodes) == ["ep-0", "ep-1", "ep-2", "ep-3"]
    assert await rig.challenger.run_cycle() == ChallengeCycleReport()  # the decision is not repeated
    assert len(rig.events.calls) == 1


class _RecordingFactory:
    """The default connection factory, except that it keeps each connection it opens, by file name.

    It hands a test the store's own ``procedures.db`` connection through the factory the store was given (no private
    attribute of the store is read), here to put a SQLite authorizer on that connection (R5 R5-2).
    """

    def __init__(self) -> None:
        self.connected: dict[str, Any] = {}

    async def connect(self, db_path: str) -> Any:
        connection = await default_factory.connect(db_path)
        self.connected[Path(db_path).name] = connection
        return connection


@asynccontextmanager
async def _snapshot_update_refused(connection: Any) -> AsyncIterator[list[str]]:
    """SQLite refuses every UPDATE of ``procedure_records.content_snapshot`` on ``connection`` inside the block.

    Yields what the authorizer refused, as ``table.column``: a test asserts the refusal fired, because one whose setup
    never reached it proves nothing. Every other statement is authorized. ``deactivate`` commits the ``is_active`` and
    ``superseded_by`` columns and then swallows exactly this failure, so the block leaves the state a failed snapshot
    write leaves in production. The authorizer is removed when the block ends, pass or fail.
    """
    refused: list[str] = []

    def authorize(action: int, table: str | None, column: str | None, database: str | None, source: str | None) -> int:
        if action == sqlite3.SQLITE_UPDATE and table == "procedure_records" and column == "content_snapshot":
            refused.append(f"{table}.{column}")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    await connection.set_authorizer(authorize)
    try:
        yield refused
    finally:
        await connection.set_authorizer(None)


def _stored_row(data_dir: Path, procedure_id: str) -> tuple[tuple[int, str], dict[str, Any]]:
    """A procedure's ``(is_active, superseded_by)`` columns and its decoded JSON snapshot, read on an independent connection."""
    with closing(sqlite3.connect(str(data_dir / PROCEDURES_DB))) as reader:
        row = reader.execute(
            "SELECT is_active, superseded_by, content_snapshot FROM procedure_records WHERE id = ?", (procedure_id,),
        ).fetchone()
    assert row is not None, f"procedures.db holds no row for {procedure_id}"
    return (row[0], row[1]), json.loads(row[2])


async def test_restored_completed_promotion_with_a_stale_champion_snapshot_is_recorded_promoted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """R5 R5-2: a completed promotion whose champion's JSON snapshot is stale is recorded, not undone.

    ``deactivate`` commits the champion's ``is_active`` and ``superseded_by`` columns and then swallows a failed
    snapshot UPDATE, so the snapshot keeps saying the champion is active and unsuperseded. Admission reads the columns,
    but ``_reconcile`` read the snapshot through ``get``: it saw an active champion, took the routing challenger for a
    stray pending one and deactivated it, so one enabled dream cycle left the ledger ``pending``, the challenger
    inactive and nothing routing. The budget is zero: a judge would otherwise promote the challenger in the ordinary
    way and mask the defect. The stale snapshot is made by the real swallow path, a refused snapshot UPDATE.
    """
    data_dir = tmp_path / "procedures"
    factory = _RecordingFactory()
    async with _started_store(data_dir, connection_factory=factory) as store:
        rig = await _rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 0})  # nothing is judged
        await _pend(rig, "ch-a")
        await _count_win(rig, "ch-a")
        await _activate(store, "ch-a")  # procedures.db as the restore leaves it: the promotion is in the file ...
        async with _snapshot_update_refused(factory.connected[PROCEDURES_DB]) as refused:
            # ... and the champion's deactivation commits its columns, then fails to write its snapshot, which it swallows.
            await store.deactivate(CHAMPION_ID, superseded_by="ch-a")

        # The premises, each read independently of the code under test.
        assert refused == ["procedure_records.content_snapshot"]  # the injected refusal fired, once
        columns, snapshot = _stored_row(data_dir, CHAMPION_ID)
        assert columns == (0, "ch-a")  # the columns, which admission reads: inactive, superseded by the challenger
        assert (snapshot["is_active"], snapshot["superseded_by"]) == (True, "")  # the snapshot `get` used to read: stale
        assert (await _record(rig, "ch-a")).status == "pending"  # the older ledger does not know the promotion
        assert await _matched_ids(store) == ["ch-a"]  # admission routes the challenger on the columns
        assert rig.llm.requests == []

        with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
            report = await rig.challenger.run_cycle()

        assert (report.judge_calls, report.comparisons, report.promoted, report.retired) == (0, 0, 1, 0)
        assert rig.llm.requests == []
        record = await _record(rig, "ch-a")
        assert record.status == "promoted" and record.decision_reason.startswith("restored_promotion")
        challenger = await store.get("ch-a")
        assert challenger is not None and challenger.is_active is True
        assert _stored_row(data_dir, "ch-a")[0] == (1, "")  # read on its own: the challenger was not deactivated
        assert await _matched_ids(store) == ["ch-a"]
        # No WARNING at all, so none is the "was routable" one that deactivating the routing challenger logged.
        warnings = [r.getMessage() for r in caplog.records if r.name == CHALLENGER_LOGGER and r.levelno == logging.WARNING]
        assert warnings == []


async def test_a_restored_promotion_with_a_stale_champion_snapshot_retires_the_other_open_challengers(
    tmp_path: Path,
) -> None:
    """R6 R6-1: the champion's gate reads its columns, so a second open challenger is retired, never judged.

    The state is the R5 test's: ``ch-a`` is active and the champion's columns say it was superseded by ``ch-a``, while
    the champion's snapshot (a swallowed failed UPDATE) still says it is active, and ``_reconcile`` records the
    completed promotion. ``ch-b`` is still pending and inactive. A ``_contest`` gate read from ``get``'s snapshot (base
    ``get``; R5-2's merged ``get`` closed this by accident) sees an active champion and judges ``ch-b`` against the
    superseded one, and a judge that prefers challengers could promote it beside ``ch-a``: two active in one lineage.
    The budget allows four judge calls, so a judged ``ch-b`` shows as judge calls; the gate retires it without one.
    """
    data_dir = tmp_path / "procedures"
    factory = _RecordingFactory()
    async with _started_store(data_dir, connection_factory=factory) as store:
        rig = await _rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 4})  # the judge favours challengers
        await _pend(rig, "ch-a")
        await _pend(rig, "ch-b")  # a second open challenger of the champion: inactive, holding no comparisons
        await _count_win(rig, "ch-a")
        await _activate(store, "ch-a")  # procedures.db as the restore leaves it: the promotion is in the file ...
        async with _snapshot_update_refused(factory.connected[PROCEDURES_DB]) as refused:
            # ... and the champion's deactivation commits its columns, then fails to write its snapshot, which it swallows.
            await store.deactivate(CHAMPION_ID, superseded_by="ch-a")

        # The premises, each read independently of the code under test.
        assert refused == ["procedure_records.content_snapshot"]  # the injected refusal fired, once
        columns, snapshot = _stored_row(data_dir, CHAMPION_ID)
        assert columns == (0, "ch-a")  # the columns, which admission and the challenger read: superseded by ch-a
        assert snapshot["is_active"] is True  # the snapshot `get` reads: stale, still active
        assert _stored_row(data_dir, "ch-b")[0] == (0, "")  # the second challenger is inactive ...
        assert len(await rig.ledger.comparisons("ch-b")) == 0  # ... and holds no comparisons
        assert [(await _record(rig, name)).status for name in ("ch-a", "ch-b")] == ["pending", "pending"]
        assert await _matched_ids(store) == ["ch-a"]  # admission routes ch-a on the columns
        assert rig.llm.requests == []

        report = await rig.challenger.run_cycle()

        assert (report.judge_calls, report.promoted, report.retired) == (0, 1, 1)
        assert rig.llm.requests == []  # ch-b was never judged against the superseded champion
        promoted = await _record(rig, "ch-a")
        assert promoted.status == "promoted" and promoted.decision_reason.startswith("restored_promotion")
        retired = await _record(rig, "ch-b")
        assert retired.status == "retired" and retired.decision_reason.startswith("champion_inactive:")
        assert sorted(_decisions(rig.events)) == [
            ("ch-a", "promoted", "restored_promotion"), ("ch-b", "retired", "champion_inactive"),
        ]
        assert await store.routing_state("ch-b") == (False, "")  # no second active challenger in the lineage
        assert await _matched_ids(store) == ["ch-a"]


async def test_a_promotion_activates_a_challenger_whose_snapshot_says_active(
    store: ProcedureStore, tmp_path: Path,
) -> None:
    """R6 R6-1: the promotion's activity checks read the columns, so a stale-active snapshot cannot skip the re-save.

    A swallowed snapshot UPDATE can leave ``ch-a`` with ``is_active`` 0 in its column and true in its snapshot, and
    base ``get`` reports the snapshot. A ``_complete_promotion`` check read from ``get`` skips the re-save, retires the
    champion and seals ``promoted`` with nothing routing: neither procedure is active. Read from the column through
    ``routing_state``, the check re-saves the challenger, so it routes and the lineage keeps an active procedure.
    """
    data_dir = tmp_path / "procedures"  # the ``store`` fixture's data dir
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    await _activate(store, "ch-a")
    await store.deactivate("ch-a")  # the column and the snapshot now both say inactive ...
    with closing(sqlite3.connect(str(data_dir / PROCEDURES_DB))) as writer:  # ... until an independent connection
        stored = writer.execute("SELECT content_snapshot FROM procedure_records WHERE id = ?", ("ch-a",)).fetchone()
        assert stored is not None, "procedures.db holds no row for ch-a"
        stale = json.loads(stored[0])
        stale["is_active"] = True  # rewrites the snapshot as a swallowed snapshot UPDATE leaves it
        writer.execute("UPDATE procedure_records SET content_snapshot = ? WHERE id = ?", (json.dumps(stale), "ch-a"))
        writer.commit()
    # The deciding cycle won and crashed before activating: the interrupted promotion the next cycle finishes.
    assert await rig.ledger.set_status("ch-a", "promoting", reason="won: test", expected=("pending",))

    # The premises, each read independently of the code under test.
    columns, snapshot = _stored_row(data_dir, "ch-a")
    assert columns == (0, "")  # the column, which the promotion must read: inactive
    assert snapshot["is_active"] is True  # the snapshot: stale, active
    challenger = await store.get("ch-a")
    assert challenger is not None and challenger.is_active is True  # `get` reports the snapshot: the trap
    assert (await _record(rig, "ch-a")).status == "promoting"
    assert await _routed_ids(store) == [CHAMPION_ID]  # the column is what routes: only the champion does
    assert rig.llm.requests == []

    report = await rig.challenger.run_cycle()

    assert (report.judge_calls, report.promoted, report.retired) == (0, 1, 0)
    assert rig.llm.requests == []
    assert (await _record(rig, "ch-a")).status == "promoted"
    assert await store.routing_state("ch-a") == (True, "")  # the promotion re-saved the challenger: its column says active
    assert await store.routing_state(CHAMPION_ID) == (False, "ch-a")
    assert await _matched_ids(store) == ["ch-a"]


async def test_restored_pending_challenger_that_routes_is_deactivated(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture,
) -> None:
    """R1 F7: a pending challenger a restore left routable is deactivated: only a win may route it."""
    rig = await _rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 0})  # nothing is judged
    await _pend(rig, "ch-a")
    await _activate(store, "ch-a")  # procedures.db as the restore leaves it: the challenger routes beside its champion
    assert await _routed_ids(store) == sorted([CHAMPION_ID, "ch-a"])
    # R3 (R3-5) moved this premise. It pinned `_matched_ids == sorted([CHAMPION_ID, "ch-a"])` ("it really is routable"),
    # which no longer holds: admission also refuses a challenger the ledger holds `pending`, whatever the index entry
    # and SQLite say. The premise now reads the entry itself, and routing is asserted to veto it before the cycle.
    assert _index_says_active(store, "ch-a") is True  # the premise: the index entry (and SQLite) admit the challenger ...
    assert await _matched_ids(store) == [CHAMPION_ID]  # ... but its ledger row is pending, so only the champion routes
    assert (await _record(rig, "ch-a")).status == "pending"

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
        report = await rig.challenger.run_cycle()

    assert _counts(report) == (0, 0, 4, 0, 0)  # deferred by the budget: nothing was decided
    challenger, champion = await store.get("ch-a"), await store.get(CHAMPION_ID)
    assert challenger is not None and challenger.is_active is False
    assert champion is not None and champion.is_active is True and champion.superseded_by == ""
    assert (await _record(rig, "ch-a")).status == "pending"
    assert await _routed_ids(store) == [CHAMPION_ID]
    assert await _matched_ids(store) == [CHAMPION_ID]
    warnings = [r for r in caplog.records if r.name == CHALLENGER_LOGGER and r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "ch-a" in warnings[0].getMessage()


async def test_pending_challenger_with_a_stale_index_entry_is_rewritten_from_sqlite(store: ProcedureStore) -> None:
    """R1 F7: each cycle rewrites a pending challenger's index entry from SQLite, so a stale one is repaired."""
    rig = await _rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 0})  # nothing is judged
    await _pend(rig, "ch-a")
    await _activate(store, "ch-a")
    with _index_outage(store, "update") as hit:
        await store.deactivate("ch-a")  # SQLite now says inactive; the failed index update leaves its entry active
    assert hit == ["ch-a"], "the index outage was not reached"
    stored = await store.get("ch-a")
    assert stored is not None and stored.is_active is False
    # R2 (R2-1) moved this premise. It was `_matched_ids == [CHAMPION_ID, "ch-a"]` (the stale entry routing the
    # challenger), which no longer holds: find_matching admits a match only through an active SQLite row (3g). The
    # premise now reads the stale entry itself, and routing is asserted to drop it.
    assert _index_says_active(store, "ch-a") is True  # the premise: the stale entry is in the index ...
    assert await _matched_ids(store) == [CHAMPION_ID]  # ... but routing asks SQLite and drops it

    report = await rig.challenger.run_cycle()

    assert _counts(report) == (0, 0, 4, 0, 0)  # deferred by the budget: nothing was decided
    assert (await _record(rig, "ch-a")).status == "pending"
    assert _index_says_active(store, "ch-a") is False  # the cycle rewrote the entry from SQLite (row 47 skips this sync)
    assert await _matched_ids(store) == [CHAMPION_ID]


async def test_retirement_is_sealed_only_when_the_routing_index_agrees(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture,
) -> None:
    """R2 R2-1: ``retired`` is sealed only once the challenger's index entry agrees with SQLite; a later cycle retries."""
    rig = await _rig(
        store,
        dreaming={"procedure_challenger_max_judge_calls_per_cycle": 0, "procedure_challenger_max_pending_cycles": 1},
    )
    await _pend(rig, "ch-a")
    await _activate(store, "ch-a")  # the activation-only restored pair: the challenger routes beside its champion
    # R3 (R3-5) moved this premise. It pinned `_matched_ids == sorted([CHAMPION_ID, "ch-a"])` ("it really is routable"),
    # which no longer holds: admission also refuses a challenger the ledger holds `pending`, whatever the index entry
    # and SQLite say. The premise now reads the entry itself, and routing is asserted to veto it before the cycle.
    assert _index_says_active(store, "ch-a") is True  # the premise: the index entry admits the challenger ...
    assert await _matched_ids(store) == [CHAMPION_ID]  # ... but its ledger row is pending, so only the champion routes
    assert (await _record(rig, "ch-a")).status == "pending"

    with (
        caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER),
        _index_outage(store, "update") as updates,
        _index_outage(store, "upsert") as upserts,
    ):
        first = await rig.challenger.run_cycle()

    assert "ch-a" in updates and "ch-a" in upserts, "the index outage was not reached"
    stored = await store.get("ch-a")
    assert stored is not None and stored.is_active is False  # SQLite deactivated it ...
    assert (await _record(rig, "ch-a")).status == "pending"  # ... but the ledger does not seal the retirement
    assert first.retired == 0 and rig.events.calls == []
    unsealed = [
        r for r in caplog.records
        if r.name == CHALLENGER_LOGGER and r.levelno == logging.WARNING and "is not retired" in r.getMessage()
    ]
    assert len(unsealed) == 1 and "ch-a" in unsealed[0].getMessage()
    assert _index_says_active(store, "ch-a") is True  # the stale entry the retry must repair
    assert await _matched_ids(store) == [CHAMPION_ID]  # 3g: routing asks SQLite, so the stale entry does not route it

    second = await rig.challenger.run_cycle()  # the index is back: the blocks that took it down have ended

    assert second.retired == 1
    record = await _record(rig, "ch-a")
    assert record.status == "retired" and record.decision_reason.startswith("expired:")
    assert _index_says_active(store, "ch-a") is False  # the retry rewrote the entry from SQLite
    assert _decisions(rig.events) == [("ch-a", "retired", "expired")]
    assert await _matched_ids(store) == [CHAMPION_ID]


async def test_retirement_leaves_no_routable_challenger(store: ProcedureStore) -> None:
    """R1 F7: a retired challenger never routes, even when a restore left it active beside a superseded champion."""
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    await _activate(store, "ch-a")
    await store.deactivate(CHAMPION_ID, superseded_by="a-newer-procedure")  # superseded by another id, not by ch-a
    assert (await _record(rig, "ch-a")).status == "pending"
    # R3 (R3-5) moved this premise. It pinned `_matched_ids == ["ch-a"]` (the challenger routes and its champion does
    # not), which no longer holds: admission refuses a challenger the ledger holds `pending`, so neither routes until
    # the cycle below decides it. The premise now reads the entry itself, and routing is asserted to veto it.
    assert _index_says_active(store, "ch-a") is True  # the premise: the index entry still admits the challenger ...
    assert await _matched_ids(store) == []  # ... but its ledger row is pending and its champion is superseded

    report = await rig.challenger.run_cycle()

    assert (report.judge_calls, report.promoted, report.retired) == (0, 0, 1)
    record = await _record(rig, "ch-a")
    assert record.status == "retired" and record.decision_reason.startswith("champion_inactive:")
    challenger = await store.get("ch-a")
    assert challenger is not None and challenger.is_active is False
    assert await _routed_ids(store) == []
    assert await _matched_ids(store) == []
    assert _decisions(rig.events) == [("ch-a", "retired", "champion_inactive")]


async def test_ledger_newer_than_procedures_keeps_the_champion_routing(store: ProcedureStore) -> None:
    """R1 F7 (the documented residual, pinned): a ledger newer than ``procedures.db`` leaves the older routing."""
    rig = await _rig(store)
    await _pend(rig, "ch-a")
    decided = "won: wins=4 losses=0 ties=0 decisions=4 held_out=2/2 promote_above=0.60"
    # The ledger as a restore pairs it with an older procedures.db: it says promoted, the file does not hold it.
    assert await rig.ledger.set_status("ch-a", "promoted", reason=decided, expected=("pending",)) is True
    assert await _routed_ids(store) == [CHAMPION_ID]
    assert await _matched_ids(store) == [CHAMPION_ID]

    report = await rig.challenger.run_cycle()

    assert report == ChallengeCycleReport()  # decided rows are not rescanned: nothing changes
    assert rig.events.calls == [] and rig.llm.requests == []
    assert await rig.ledger.recent_cycles() == []
    record = await _record(rig, "ch-a")
    assert (record.status, record.decision_reason) == ("promoted", decided)
    challenger, champion = await store.get("ch-a"), await store.get(CHAMPION_ID)
    assert challenger is not None and challenger.is_active is False
    assert champion is not None and champion.is_active is True and champion.superseded_by == ""
    assert await _routed_ids(store) == [CHAMPION_ID]
    assert await _matched_ids(store) == [CHAMPION_ID]


@pytest.mark.parametrize("damage", ["champion_inactive", "challenger_missing"])
async def test_early_retirement_reports_the_recorded_evidence(store: ProcedureStore, damage: str) -> None:
    """R1 F8: a challenger retired before it could be judged further is reported with the evidence already recorded."""
    rig = await _rig(
        store, verifier="gpt-5.1", dreaming={"procedure_challenger_max_judge_calls_per_cycle": 2},
    )
    await _pend(rig, "ch-a")
    first = await rig.challenger.run_cycle()  # budget 2: one situation is judged, three are deferred
    assert _counts(first) == (2, 1, 3, 0, 0)
    evidence = await rig.ledger.comparisons("ch-a")
    assert [(c.episode_id, c.outcome, c.counted) for c in evidence] == [("ep-0", "challenger", True)]
    recorded = sorted({j["judge"]["independence"] for c in evidence for j in c.judgements})
    assert recorded == ["independent"]
    assert rig.events.calls == []
    if damage == "champion_inactive":
        await store.deactivate(CHAMPION_ID, superseded_by="a-newer-procedure")
    else:
        assert await store.delete("ch-a") is True
    asked = len(rig.llm.requests)

    second = await rig.challenger.run_cycle()

    assert _counts(second) == (0, 0, 0, 0, 1)
    assert len(rig.llm.requests) == asked  # retiring does not judge
    record = await _record(rig, "ch-a")
    assert record.status == "retired"
    assert record.decision_reason.startswith(f"{damage}: wins=1 losses=0 ties=0 decisions=1")
    assert len(rig.events.calls) == 1
    _kind, payload = rig.events.calls[0]
    assert (payload["decision"], payload["reason"]) == ("retired", damage)
    assert (payload["wins"], payload["decisions"]) == (1, 1)
    assert payload["judge_independence"] == recorded


# ---------------------------------------------------------------------------
# run_cycle: the optimizer's own judge, a failed terminal commit and the raw-copy restore (review round 3, D11)
# ---------------------------------------------------------------------------


async def test_challenger_judged_by_its_optimizers_model_is_never_promoted(
    store: ProcedureStore, tmp_path: Path,
) -> None:
    """R3 R3-1: a judgement by the model that wrote the rewrite is ``same_model``: recorded, not counted, never promoting."""
    # Budget 8 is exactly one pass over the four situations, so a cycle that judged any more would exceed it.
    dreaming = {"procedure_challenger_max_judge_calls_per_cycle": 8}
    # The positive control (premise): the same rig, judge and verdicts with a rewrite answered by another model promote.
    async with _started_store(tmp_path / "control") as control_store:
        control = await _rig(control_store, verifier="gpt-5.1", dreaming=dreaming)
        await _pend(control, "ch-a", optimizer_model="claude-opus-4-6")
        assert (await control.challenger.run_cycle()).promoted == 1
        assert (await _record(control, "ch-a")).status == "promoted"
        control_rows = await control.ledger.comparisons("ch-a")
        assert len(control_rows) == 4 and all(row.counted for row in control_rows)
        assert {j["judge"]["independence"] for row in control_rows for j in row.judgements} == {"independent"}

    rig = await _rig(store, verifier="gpt-5.1", dreaming=dreaming)
    await _pend(rig, "ch-a", optimizer_model="gpt-5.1")  # the rewrite was answered by the very model that judges it
    assert (await _record(rig, "ch-a")).optimizer_model == "gpt-5.1"
    budget = rig.dreaming.procedure_challenger_max_judge_calls_per_cycle
    expiry = rig.dreaming.procedure_challenger_max_pending_cycles

    for cycle in range(1, expiry + 1):
        asked = len(rig.llm.calls)
        report = await rig.challenger.run_cycle()

        assert report.promoted == 0
        assert report.retired == (1 if cycle == expiry else 0)
        assert 0 < report.judge_calls <= budget  # re-judged every cycle, never past the per-cycle budget
        assert len(rig.llm.calls) - asked == report.judge_calls  # the double saw exactly the calls the report counts
        assert (await _record(rig, "ch-a")).status == ("retired" if cycle == expiry else "pending")
        assert await _routed_ids(store) == [CHAMPION_ID]  # the champion routes throughout
        assert await _matched_ids(store) == [CHAMPION_ID]

    rows = await rig.ledger.comparisons("ch-a")
    judges = [j["judge"] for row in rows for j in row.judgements]
    # The premise: valid verdicts for the challenger, answered on the requested tier by the verifier model, no fallback ...
    assert len(rows) == 4 * expiry and {row.outcome for row in rows} == {"challenger"}
    assert {call.tier for call in rig.llm.calls} == {"verifier"}
    assert {(j["tier"], j["model"], j["fallback"]) for j in judges} == {("verifier", "gpt-5.1", False)}
    # ... and still none of them counts: the rewrite's own model is not an independent judge of it.
    assert all(row.counted is False for row in rows)
    assert all([j["judge"]["independence"] for j in row.judgements] == ["same_model", "same_model"] for row in rows)
    record = await _record(rig, "ch-a")
    assert record.status == "retired" and record.decision_reason.startswith("expired: wins=0 losses=0 ties=0 decisions=0")
    assert _decisions(rig.events) == [("ch-a", "retired", "expired")]


@pytest.mark.parametrize(
    ("terminal", "earlier", "winner", "reason", "routed"),
    [
        pytest.param("promoted", "promoting", "challenger", "won", ["ch-a"], id="promoted"),
        pytest.param("retired", "pending", "champion", "lost", [CHAMPION_ID], id="retired"),
    ],
)
async def test_failed_terminal_commit_is_finished_by_the_next_cycle(
    tmp_path: Path, terminal: str, earlier: str, winner: str, reason: str, routed: list[str],
) -> None:
    """R3 R3-2: a ledger write whose commit fails is rolled back, so the next cycle finishes the decision and emits it."""
    data_dir = tmp_path / "procedures"
    factory = _FakeLedgerFactory(terminal)
    async with _started_store(data_dir, connection_factory=factory) as wrapped_store:
        rig = await _rig(wrapped_store, script=_Script(winner))
        await _pend(rig, "ch-a")
        connection = factory.ledger_connection
        assert connection is not None and connection.failures == 0, "the ledger's connection was not wrapped"

        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            await rig.challenger.run_cycle()

        assert connection.failures == 1  # the premise: the injected failure fired at the terminal commit
        assert len(await rig.ledger.comparisons("ch-a")) == 4  # the evidence was committed before the decision
        assert rig.events.calls == []  # the event follows the commit, so none was emitted for the undecided row
        assert _ledger_status(data_dir, "ch-a") == earlier  # an independent reader sees only the committed status ...
        assert (await _record(rig, "ch-a")).status == earlier  # ... and so does the ledger's own connection
        asked = len(rig.llm.calls)

        report = await rig.challenger.run_cycle()

        assert connection.failures == 1  # it failed once only
        assert (report.promoted, report.retired) == ((1, 0) if terminal == "promoted" else (0, 1))
        assert report.judge_calls == 0 and len(rig.llm.calls) == asked  # finishing the decision does not judge again
        assert _decisions(rig.events) == [("ch-a", terminal, reason)]
        assert (await _record(rig, "ch-a")).status == terminal
        assert _ledger_status(data_dir, "ch-a") == terminal
        assert await _routed_ids(wrapped_store) == routed


async def test_raw_copy_fallback_pair_never_routes_the_pending_challenger(
    store: ProcedureStore, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """R3 R3-5: the backup's raw-copy fallback pairs an older ledger image with a newer ``procedures.db``; it never routes."""
    source = tmp_path / "procedures"  # the ``store`` fixture's data dir
    rig = await _rig(store, dreaming={"procedure_challenger_max_judge_calls_per_cycle": 0})  # nothing is judged
    await _pend(rig, "ch-a")
    _checkpoint(source / LEDGER_DB)  # the challenger, pending with no comparisons, is now in the ledger's main file
    for episode_id in (await _record(rig, "ch-a")).context_episode_ids:
        await _count_win(rig, "ch-a", episode_id)
    decided = "won: wins=4 losses=0 ties=0 decisions=4 held_out=2/2 promote_above=0.60"
    assert await rig.ledger.set_status("ch-a", "promoting", reason=decided, expected=("pending",)) is True
    assert _wal_size(source / LEDGER_DB) > 0  # the premise: those commits sit in procedures_challenges.db-wal
    await _activate(store, "ch-a")  # the promotion's first step: the challenger is saved active
    _checkpoint(source / PROCEDURES_DB)  # procedures.db carries it in its main file (its own log would not be copied)
    live = await _record(rig, "ch-a")
    assert live.status == "promoting" and len(await rig.ledger.comparisons("ch-a")) == 4  # the live ledger is newer

    restored_dir = tmp_path / "restored"
    restored_dir.mkdir()
    for name in (PROCEDURES_DB, LEDGER_DB):  # the fallback's own call (backup.py:799): procedures.db first, no -wal/-shm
        shutil.copyfile(source / name, restored_dir / name)

    async with _started_store(restored_dir) as restored:
        ledger = restored.challenges
        assert ledger is not None, "the restored store's challenger ledger did not open"
        older = await ledger.get("ch-a")
        assert older is not None and older.status == "pending"  # the premises: the older ledger image ...
        assert await ledger.comparisons("ch-a") == []
        assert await _routed_ids(restored) == sorted([CHAMPION_ID, "ch-a"])  # ... beside a procedures.db that has it active
        assert _index_says_active(restored, "ch-a") is True  # and the rebuilt index entry admits it too

        assert await _matched_ids(restored) == [CHAMPION_ID]  # admission refuses the pending challenger: the champion only

        restarted = replace(rig, store=restored, ledger=ledger)
        restarted.challenger = restarted.challenger_over(restored)
        with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
            report = await restarted.challenger.run_cycle()

        assert _counts(report) == (0, 0, 4, 0, 0)  # deferred by the budget: nothing was decided
        challenger, champion = await restored.get("ch-a"), await restored.get(CHAMPION_ID)
        assert challenger is not None and challenger.is_active is False  # _reconcile deactivated it
        assert champion is not None and champion.is_active is True and champion.superseded_by == ""
        assert (await _record(restarted, "ch-a")).status == "pending"
        assert await _routed_ids(restored) == [CHAMPION_ID]
        assert await _matched_ids(restored) == [CHAMPION_ID]
        warnings = [r for r in caplog.records if r.name == CHALLENGER_LOGGER and r.levelno == logging.WARNING]
        assert len(warnings) == 1 and "ch-a" in warnings[0].getMessage()


# ---------------------------------------------------------------------------
# The decision event
# ---------------------------------------------------------------------------


async def test_decision_emits_one_durable_event_with_counts_only(store: ProcedureStore) -> None:
    rig = await _rig(store, verifier="gpt-5.1")
    await _pend(rig, "ch-a")

    report = await rig.challenger.run_cycle()

    assert report.promoted == 1
    assert len(rig.events.calls) == 1
    kind, payload = rig.events.calls[0]
    assert kind is EventType.PROCEDURE_CHALLENGE_DECIDED
    assert is_routed(EventType.PROCEDURE_CHALLENGE_DECIDED.name)  # DURABLE and written by the router
    assert set(payload) == _PAYLOAD_KEYS
    assert (payload["challenger_id"], payload["champion_id"]) == ("ch-a", CHAMPION_ID)
    assert (payload["decision"], payload["reason"]) == ("promoted", "won")
    assert (payload["wins"], payload["losses"], payload["ties"], payload["decisions"]) == (4, 0, 0, 4)
    assert (payload["held_out_wins"], payload["held_out_decisions"]) == (2, 2)
    assert payload["strength"] == pytest.approx(9.0, abs=1e-5)
    assert payload["judge_independence"] == ["independent"]
    # Counts only: no judge reasoning and no candidate text; everything is a scalar or a list of codes.
    encoded = json.dumps(payload)
    assert LLM_REASON not in encoded and "Open the file" not in encoded and "Summarise" not in encoded
    assert all(
        value is None or isinstance(value, (str, int, float)) or (isinstance(value, list) and all(type(v) is str for v in value))
        for value in payload.values()
    )

    again = await rig.challenger.run_cycle()  # a second cycle has nothing to decide, so it emits nothing

    assert again == ChallengeCycleReport()
    assert len(rig.events.calls) == 1


async def test_event_strength_is_rounded_to_six_places(store: ProcedureStore) -> None:
    script = _Script().for_challenger("ch-a", ["challenger", "challenger", "challenger", "champion"])
    rig = await _rig(store, script=script)
    await _pend(rig, "ch-a")

    report = await rig.challenger.run_cycle()

    assert report.promoted == 1
    _kind, payload = rig.events.calls[0]
    assert (payload["wins"], payload["losses"]) == (3, 1)
    assert payload["strength"] == 2.333333  # 3.5 / 1.5 = 2.3333333333..., carried to six places


@pytest.mark.parametrize(
    ("default_outcome", "status", "champion_stays"),
    [
        pytest.param("challenger", "promoted", False, id="promotion"),
        pytest.param("champion", "retired", True, id="retirement"),
    ],
)
async def test_event_emit_failure_keeps_the_decision(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture, default_outcome: str, status: str, champion_stays: bool,
) -> None:
    rig = await _rig(store, script=_Script(default_outcome), emit=_FakeEmit(error=RuntimeError("event bus down")))
    await _pend(rig, "ch-a")

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
        report = await rig.challenger.run_cycle()

    assert len(rig.events.calls) == 1  # the emit was attempted, once
    assert any("could not be emitted" in r.getMessage() for r in caplog.records)
    assert (await _record(rig, "ch-a")).status == status
    assert (report.promoted, report.retired) == ((0, 1) if champion_stays else (1, 0))
    champion = await store.get(CHAMPION_ID)
    assert champion is not None and champion.is_active is champion_stays
    assert await _routed_ids(store) == ([CHAMPION_ID] if champion_stays else ["ch-a"])
    assert len(await rig.ledger.recent_cycles()) == 1  # the cycle was still recorded


# ---------------------------------------------------------------------------
# build_procedure_challenger
# ---------------------------------------------------------------------------


def _build(
    config: SystemConfig, procedure_store: Any, *, episodes: Any = None, llm: Any = None, events: Any = None,
) -> ProcedureChallenger | None:
    return build_procedure_challenger(
        config=config,
        procedure_store=procedure_store,
        episodic_memory=_FakeEpisodes(_episodes()) if episodes is None else episodes,
        llm_client=_FakeJudgeLLM(_Script()) if llm is None else llm,
        emit_event_fn=events,
        rng=random.Random(_SEED),
    )


def test_build_returns_none_when_disabled(store: ProcedureStore) -> None:
    disabled = SystemConfig(dreaming=DreamingConfig(procedure_challenger_enabled=False))

    assert _build(disabled, store) is None
    assert isinstance(_build(SystemConfig(), store), ProcedureChallenger)  # the flag alone decides


@pytest.mark.parametrize("kind", ["magicmock-store", "ledger-not-open"])
async def test_build_returns_none_without_a_real_ledger(
    store: ProcedureStore, caplog: pytest.LogCaptureFixture, kind: str,
) -> None:
    if kind == "magicmock-store":
        target: Any = MagicMock()  # its ``challenges`` is a MagicMock, not a ProcedureChallengeLedger
    else:
        await store.stop()  # a stopped store has no ledger; the fixture's own stop is then a no-op
        assert store.challenges is None
        target = store

    with caplog.at_level(logging.WARNING, logger=CHALLENGER_LOGGER):
        built = _build(SystemConfig(), target)

    assert built is None
    assert any("ledger is not open" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("missing", ["procedure_store", "llm_client", "episodic_memory"])
def test_build_returns_none_when_a_collaborator_is_missing(store: ProcedureStore, missing: str) -> None:
    collaborators: dict[str, Any] = {
        "procedure_store": store, "llm_client": _FakeJudgeLLM(_Script()), "episodic_memory": _FakeEpisodes(_episodes()),
    }
    collaborators[missing] = None

    built = build_procedure_challenger(
        config=SystemConfig(), emit_event_fn=None, rng=random.Random(_SEED), **collaborators,
    )

    assert built is None


@pytest.mark.parametrize(
    ("verifier", "tier", "independence"),
    [
        pytest.param("gpt-5.1", "verifier", "independent", id="dedicated-verifier"),
        pytest.param(None, "standard", "same_model", id="no-verifier-uses-the-standard-tier"),
    ],
)
async def test_build_uses_the_verifier_policy_tier(
    store: ProcedureStore, verifier: str | None, tier: str, independence: str,
) -> None:
    config = SystemConfig(cognitive=CognitiveConfig(llm_model_verifier=verifier))
    champion = _champion()
    await store.save(champion)
    llm = _FakeJudgeLLM(_Script(), model=verifier or "claude-sonnet-4-6")
    events = _FakeEmit()
    built = _build(config, store, llm=llm, events=events)
    assert built is not None

    plan = await built.prepare(champion, _episodes())
    assert plan is not None
    assert await built.submit(plan, _fix_result("ch-a")) is not None
    report = await built.run_cycle()

    assert report.promoted == 1
    assert len(llm.requests) == 8
    assert {request.tier for request in llm.requests} == {tier}  # never the deep tier the rewrite ran on
    assert events.calls[0][1]["judge_independence"] == [independence]


# ---------------------------------------------------------------------------
# One owner for the ledger's writes and the event
# ---------------------------------------------------------------------------

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "probos"
_LEDGER_MODULE = "probos.cognitive.procedure_challenges"
_LEDGER_WRITERS = frozenset({"add_challenger", "set_status", "record_comparison", "increment_cycles", "record_cycle"})
_EVENT_MEMBER = "PROCEDURE_CHALLENGE_DECIDED"
_CHALLENGER_FILE = "cognitive/procedure_challenger.py"


def _source_trees() -> dict[str, ast.Module]:
    """Every module under ``src/probos``, keyed by its posix path relative to it."""
    return {
        path.relative_to(_SRC_ROOT).as_posix(): ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for path in sorted(_SRC_ROOT.rglob("*.py"))
    }


def _from_module(package: list[str], node: ast.ImportFrom) -> str:
    """The dotted module a ``from ... import`` names, relative imports resolved against ``package``."""
    if node.level == 0:
        return node.module or ""
    anchor = package[: len(package) - (node.level - 1)]
    return ".".join([*anchor, *([node.module] if node.module else [])])


def _imported_modules(relative_path: str, tree: ast.Module) -> set[str]:
    """Dotted modules ``tree`` imports: import statements anywhere in it, and literal ``import_module`` calls."""
    package = ["probos", *relative_path.split("/")[:-1]]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _from_module(package, node)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and node.args:
            callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            target = node.args[0]
            if callee in ("import_module", "__import__") and isinstance(target, ast.Constant) and isinstance(target.value, str):
                found.add(target.value)
    return found


def _writer_names(tree: ast.Module) -> set[str]:
    """Ledger-writer names ``tree`` refers to as an attribute (``x.set_status``) or a bare name."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _LEDGER_WRITERS:
            names.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in _LEDGER_WRITERS:
            names.add(node.id)
    return names


def test_ledger_writes_and_the_event_have_one_owner() -> None:
    trees = _source_trees()
    assert _CHALLENGER_FILE in trees, "the census did not find the challenger module under src/probos"

    # (a) the modules that import the ledger module
    importers = {path for path, tree in trees.items() if _LEDGER_MODULE in _imported_modules(path, tree)}
    assert importers == {
        "cognitive/procedure_store.py", "cognitive/procedure_judge.py", "cognitive/procedure_challenger.py",
    }, f"modules importing {_LEDGER_MODULE}: {sorted(importers)}"

    # (b) attribute reads of ``.challenges``: the store's property is a definition, not a read
    readers = {
        path for path, tree in trees.items()
        if any(
            isinstance(node, ast.Attribute) and node.attr == "challenges" and isinstance(node.ctx, ast.Load)
            for node in ast.walk(tree)
        )
    }
    assert readers == {_CHALLENGER_FILE}, f"modules reading a .challenges attribute: {sorted(readers)}"

    # (c) per module, not per name: ``set_status`` is also a task_sessions / tray method, so only the store and
    # the judge are checked, and the same census must see every writer in the challenger (a detector that works)
    detected = _writer_names(trees[_CHALLENGER_FILE])
    assert detected == _LEDGER_WRITERS, f"ledger writers the census sees in {_CHALLENGER_FILE}: {sorted(detected)}"
    writer_refs = {
        (path, name)
        for path in ("cognitive/procedure_store.py", "cognitive/procedure_judge.py")
        for name in _writer_names(trees[path])
    }
    assert writer_refs == set(), f"ledger writers referenced in the store or the judge: {sorted(writer_refs)}"

    # (d) references to EventType.PROCEDURE_CHALLENGE_DECIDED (its definition in events.py is not a reference)
    emitters = {
        path for path, tree in trees.items()
        if any(
            (isinstance(node, ast.Attribute) and node.attr == _EVENT_MEMBER)
            or (isinstance(node, ast.Name) and node.id == _EVENT_MEMBER and isinstance(node.ctx, ast.Load))
            for node in ast.walk(tree)
        )
    }
    assert emitters == {_CHALLENGER_FILE}, f"modules referencing EventType.{_EVENT_MEMBER}: {sorted(emitters)}"
