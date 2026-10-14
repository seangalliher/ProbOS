"""AD-1326 (#1510): a FIX evolution is a challenger; it replaces its champion only after winning.

MASS (arXiv:2610.12176; docs/research/mass-self-supervision-absorption.md) found
that text-space self-improvement regresses sharply without a guard, and that the
guard which worked is a champion that only a pairwise win replaces. Here:

1. ``prepare`` runs before a FIX rewrite. It splits the recalled episodes into the
   ones the rewrite sees and held-out ones it does not (``split_held_out``), and
   returns ``None`` -- no rewrite -- when the champion already has its maximum of
   pending challengers or there could never be enough situations to decide.
2. ``submit`` runs after the rewrite. It saves the FIX procedure inactive, so
   routing keeps the champion, linked to the champion through
   ``parent_procedure_ids``, and records it ``pending``.
3. ``run_cycle`` is dream Step 7d-2. It judges pending challengers within the
   cycle's judge-call budget, ranks the complete ones with Bradley-Terry, and
   promotes the top one only if it also beats the champion; the others are retired
   with their evidence kept. A challenger still pending after
   ``procedure_challenger_max_pending_cycles`` cycles is retired, not promoted.

``ProcedureChallengeLedger`` is the durable authority for every transition. In
``src/probos`` this module alone calls the ledger's writers and emits
``PROCEDURE_CHALLENGE_DECIDED`` (``test_ledger_writes_and_the_event_have_one_owner``).
Promotion is ``promoting`` -> challenger saved active and its routing-index entry
rewritten from SQLite -> champion deactivated with ``superseded_by`` and its entry
rewritten -> ``promoted``; the champion is not touched until the challenger's entry has
taken, so the lineage keeps routing through an index outage. Each cycle first finishes a
promotion an earlier cycle left at ``promoting``
(``test_interrupted_promotion_is_finished_next_cycle``,
``test_promotion_is_sealed_only_when_the_routing_index_agrees``). A retirement ``_retire``
decides is sealed only once the challenger's entry is rewritten from SQLite as well
(``test_retirement_is_sealed_only_when_the_routing_index_agrees``). A challenger over the
pending cap is recorded ``retired`` (``pending_limit``) by ``add_challenger`` without that
step: ``submit`` saved it inactive just before, so it was never routable, and admission
refuses a ``retired`` row anyway (review round 3, R3-7). ``PROCEDURE_CHALLENGE_DECIDED`` is
emitted at most once per decision, after the terminal status commits; a process that stops
between that commit and the emit leaves the decision in the ledger with no event (R3-8;
the ledger, not the event, is the authority). Before judging, each
pending challenger's routing is reconciled with its ledger row, because the ledger and
``procedures.db`` are separate files a restore can pair from different moments
(``_reconcile``). The pending cap is enforced where the challenger is recorded
(``ProcedureChallengeLedger.add_challenger``), not only checked in ``prepare``.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

from probos.cognitive.procedure_challenges import (
    ChallengeRecord,
    ComparisonRecord,
    ProcedureChallengeLedger,
)
from probos.cognitive.procedure_judge import ProcedureJudge, judgement_to_json
from probos.cognitive.procedure_ranking import PairOutcome, beats_champion, bradley_terry
from probos.cognitive.verifier_independence import VerifierJudgePolicy
from probos.events import EventType
from probos.types import episode_ran_in_plan_mode

if TYPE_CHECKING:
    from probos.cognitive.procedures import EvolutionResult, Procedure
    from probos.config import DreamingConfig, SystemConfig

logger = logging.getLogger(__name__)

JUDGE_CALLS_PER_CONTEXT = 2
_PAIR_RESULT = {"challenger": "first", "champion": "second", "tie": "tie"}


class ChallengeProcedureStore(Protocol):
    """The ``ProcedureStore`` methods the challenger service uses."""

    async def get(self, procedure_id: str) -> Any: ...

    async def save(self, procedure: Any, *, content_diff: str = "", change_summary: str = "") -> str: ...

    async def deactivate(self, procedure_id: str, superseded_by: str = "") -> None: ...

    async def get_evolution_metadata(self, procedure_id: str) -> dict[str, str]: ...

    async def sync_routing_index(self, procedure_id: str) -> bool: ...

    async def routing_state(self, procedure_id: str) -> tuple[bool, str] | None: ...


class ChallengeEpisodes(Protocol):
    """The ``EpisodicMemory`` method the challenger service uses."""

    async def get_by_ids(self, episode_ids: list[str], *, for_evidence: bool = False) -> list[Any]: ...


@dataclass(frozen=True)
class ChallengePlan:
    """What ``prepare`` decided before a FIX rewrite runs."""

    champion_id: str
    evolution_episodes: tuple[Any, ...]
    held_out_episodes: tuple[Any, ...]
    context_episode_ids: tuple[str, ...]


@dataclass(frozen=True)
class ChallengeCycleReport:
    """One Step 7d-2 run. ``superseded_episodes`` are a promoted challenger's source episodes."""

    judge_calls: int = 0
    comparisons: int = 0
    deferred: int = 0
    promoted: int = 0
    retired: int = 0
    superseded_episodes: tuple[Any, ...] = ()


@dataclass(frozen=True)
class Tally:
    """A challenger's counted judgements against its champion."""

    wins: int = 0
    losses: int = 0
    ties: int = 0
    held_out_wins: int = 0
    held_out_decisions: int = 0
    independence: tuple[str, ...] = ()

    @property
    def decisions(self) -> int:
        return self.wins + self.losses + self.ties


@dataclass
class _CycleCounts:
    calls: int = 0
    comparisons: int = 0
    deferred: int = 0
    promoted: int = 0
    retired: int = 0

    def any(self) -> bool:
        return any((self.calls, self.comparisons, self.deferred, self.promoted, self.retired))


def split_held_out(
    episodes: Sequence[Any], held_out: int, *, pinned: Collection[str] = frozenset(),
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """AD-1326: ``(evolution, held_out)`` episodes.

    Held-out episodes come from odd positions (1, 3, ...) so both halves span the
    recency order; at most ``held_out``, and never more than half of ``episodes``, are
    held out. An episode whose ``id`` is in ``pinned`` is never held out and leads the
    evolution half in recalled order, but it still counts toward the half: pinning does
    not lower the ceiling (review round 2, R2-4). When pinned episodes take odd positions,
    the unpinned even positions fill in from the oldest down, position 0 (the newest) last
    (``test_split_held_out_fills_around_pinned_episodes``). Held-out falls short of the
    ceiling only when fewer unpinned episodes remain than it asks for.
    """
    n = len(episodes)
    count = max(0, min(held_out, n // 2))
    order = [*range(1, n, 2), *reversed(range(0, n, 2))]
    eligible = [index for index in order if not pinned or episodes[index].id not in pinned]
    held_positions = set(eligible[:count])
    lead = tuple(ep for ep in episodes if pinned and ep.id in pinned)
    evolution = lead + tuple(
        ep for index, ep in enumerate(episodes)
        if index not in held_positions and not (pinned and ep.id in pinned)
    )
    kept = tuple(ep for index, ep in enumerate(episodes) if index in held_positions)
    return evolution, kept


def _counted(comparisons: Sequence[ComparisonRecord]) -> list[ComparisonRecord]:
    """The first counted comparison per situation, in recorded order."""
    seen: set[str] = set()
    kept: list[ComparisonRecord] = []
    for comparison in comparisons:
        if comparison.counted and comparison.episode_id not in seen:
            seen.add(comparison.episode_id)
            kept.append(comparison)
    return kept


def tally(comparisons: Sequence[ComparisonRecord]) -> Tally:
    wins = losses = ties = held_out_wins = held_out_decisions = 0
    independence: set[str] = set()
    for comparison in _counted(comparisons):
        if comparison.outcome == "challenger":
            wins += 1
        elif comparison.outcome == "champion":
            losses += 1
        else:
            ties += 1
        if comparison.split == "held_out":
            held_out_decisions += 1
            held_out_wins += int(comparison.outcome == "challenger")
        for judgement in comparison.judgements:
            judge = judgement.get("judge") if type(judgement) is dict else None
            if type(judge) is dict and type(judge.get("independence")) is str:
                independence.add(judge["independence"])
    return Tally(wins, losses, ties, held_out_wins, held_out_decisions, tuple(sorted(independence)))


def _pair_outcomes(record: ChallengeRecord, comparisons: Sequence[ComparisonRecord]) -> list[PairOutcome]:
    return [
        PairOutcome(record.challenger_id, record.champion_id, _PAIR_RESULT[comparison.outcome])  # type: ignore[arg-type]
        for comparison in _counted(comparisons)
    ]


def _threshold(config: DreamingConfig) -> float:
    """The win share a challenger must exceed: ``0.5 + procedure_challenger_promotion_margin``."""
    return 0.5 + config.procedure_challenger_promotion_margin


def _decision_text(reason: str, result: Tally, threshold: float) -> str:
    return (
        f"{reason}: wins={result.wins} losses={result.losses} ties={result.ties} "
        f"decisions={result.decisions} held_out={result.held_out_wins}/{result.held_out_decisions} "
        f"promote_above={threshold:.2f}"
    )


class ProcedureChallenger:
    """AD-1326: the single writer of challenger transitions and the single emitter of their event."""

    def __init__(
        self,
        *,
        store: ChallengeProcedureStore,
        ledger: ProcedureChallengeLedger,
        episodes: ChallengeEpisodes,
        judge: ProcedureJudge,
        config: DreamingConfig,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._store = store
        self._ledger = ledger
        self._episodes = episodes
        self._judge = judge
        self._config = config
        self._emit_event_fn = emit_event_fn

    async def prepare(
        self, champion: Procedure, episodes: Sequence[Any], *, source_correlation_id: str = "",
    ) -> ChallengePlan | None:
        """Split ``episodes`` for a FIX rewrite of ``champion``; ``None`` means do not rewrite.

        ``source_correlation_id`` names the turn whose LLM response the rewrite prompt quotes
        (Step 7d's fallback event). That turn's episodes are rewrite evidence already, so they
        go first in the rewrite set and are never held out
        (``test_prepare_never_holds_out_the_source_turn``). The held-out ceiling is taken from
        the whole usable recall, so pinning does not cost situations the validator counted
        (``test_source_pinned_recall_reaches_the_same_situations``).
        """
        cfg = self._config
        usable = [ep for ep in episodes if type(ep.id) is str and ep.id]
        source = source_correlation_id if type(source_correlation_id) is str else ""
        pinned_ids = {ep.id for ep in usable if source and ep.correlation_id == source}
        evolution, held_out = split_held_out(usable, cfg.procedure_challenger_held_out_episodes, pinned=pinned_ids)
        contexts = tuple(ep.id for ep in evolution[: cfg.procedure_challenger_used_contexts]) + tuple(
            ep.id for ep in held_out
        )
        if len(contexts) < cfg.procedure_challenger_min_decisions:
            logger.debug(
                "AD-1326: procedure %s has %d comparison situations, fewer than the %d a decision "
                "needs; no rewrite this time",
                champion.id, len(contexts), cfg.procedure_challenger_min_decisions,
            )
            return None
        if await self._ledger.pending_count(champion.id) >= cfg.procedure_challenger_max_pending_per_champion:
            logger.debug(
                "AD-1326: procedure %s already has %d pending challengers; no rewrite this time",
                champion.id, cfg.procedure_challenger_max_pending_per_champion,
            )
            return None
        return ChallengePlan(champion.id, evolution, held_out, contexts)

    async def submit(self, plan: ChallengePlan, result: EvolutionResult) -> Procedure | None:
        """Save ``result`` inactive and record it ``pending`` (``retired`` over the pending cap); ``None`` leaves the champion as it was."""
        procedure = result.procedure
        if procedure.evolution_type != "FIX" or list(procedure.parent_procedure_ids) != [plan.champion_id]:
            logger.warning(
                "AD-1326: refusing a challenger that is not a FIX of champion %s; nothing was saved",
                plan.champion_id,
            )
            return None
        challenger = replace(procedure, is_active=False)
        try:
            await self._store.save(
                challenger, content_diff=result.content_diff, change_summary=result.change_summary,
            )
            record = await self._ledger.add_challenger(
                challenger_id=challenger.id,
                champion_id=plan.champion_id,
                used_episode_ids=[ep.id for ep in plan.evolution_episodes],
                held_out_episode_ids=[ep.id for ep in plan.held_out_episodes],
                context_episode_ids=list(plan.context_episode_ids),
                optimizer_tier=result.optimizer_tier,
                optimizer_model=result.optimizer_model,
                max_pending=self._config.procedure_challenger_max_pending_per_champion,
            )
        except Exception:
            logger.warning(
                "AD-1326: challenger %s of champion %s could not be recorded; the champion keeps routing",
                challenger.id, plan.champion_id, exc_info=True,
            )
            return None
        if record.status != "pending":
            # Another rewrite of this champion was recorded while this one ran (prepare's check
            # is not a reservation); the ledger kept the cap and recorded this one retired.
            logger.warning(
                "AD-1326: champion %s reached its %d pending challengers while challenger %s was "
                "written; it is recorded retired (pending_limit), kept inactive, and the champion "
                "keeps routing",
                plan.champion_id, self._config.procedure_challenger_max_pending_per_champion, challenger.id,
            )
            self._emit(record, "retired", "pending_limit", Tally(), None)
            return None
        logger.info(
            "AD-1326: procedure challenger %s saved inactive against champion %s (%d situations, "
            "%d held out; rewrite answered by %s)",
            challenger.id, plan.champion_id, len(plan.context_episode_ids), len(plan.held_out_episodes),
            result.optimizer_tier or "an unreported tier",
        )
        return challenger

    async def run_cycle(self) -> ChallengeCycleReport:
        """Dream Step 7d-2: finish interrupted promotions, judge within budget, decide, age the rest."""
        counts = _CycleCounts()
        superseded: list[Any] = []
        for record in await self._ledger.list_by_status("promoting"):
            superseded.extend(await self._complete_promotion(record, counts))
        groups: dict[str, list[ChallengeRecord]] = {}
        for record in await self._ledger.list_by_status("pending"):
            groups.setdefault(record.champion_id, []).append(record)
        for champion_id, records in groups.items():
            superseded.extend(await self._contest(champion_id, records, counts))
        await self._age(counts)
        if counts.any():
            await self._ledger.record_cycle(
                judge_calls=counts.calls, comparisons=counts.comparisons, deferred=counts.deferred,
                promoted=counts.promoted, retired=counts.retired,
            )
            logger.info(
                "AD-1326: procedure challengers -- %d judge calls, %d situations judged, %d deferred by "
                "the budget, %d promoted, %d retired",
                counts.calls, counts.comparisons, counts.deferred, counts.promoted, counts.retired,
            )
        return ChallengeCycleReport(
            judge_calls=counts.calls, comparisons=counts.comparisons, deferred=counts.deferred,
            promoted=counts.promoted, retired=counts.retired, superseded_episodes=tuple(superseded),
        )

    async def _contest(self, champion_id: str, records: list[ChallengeRecord], counts: _CycleCounts) -> list[Any]:
        champion = await self._store.get(champion_id)
        # R6-1: activity and supersession come from the columns admission reads, not get's snapshot.
        champion_state = await self._store.routing_state(champion_id)
        superseded: list[Any] = []
        open_records: list[ChallengeRecord] = []
        for record in records:
            settled = await self._reconcile(champion_state, record, counts)
            if settled is None:
                open_records.append(record)
            else:
                superseded.extend(settled)
        if champion is None or champion_state is None or not champion_state[0]:
            for record in open_records:
                recorded = tally(await self._ledger.comparisons(record.challenger_id))
                await self._retire(record, "champion_inactive", recorded, counts)
            return superseded
        complete: list[tuple[ChallengeRecord, list[ComparisonRecord]]] = []
        for record in open_records:
            evidence = await self._judge_record(champion, record, counts)
            if evidence is None:
                continue
            if tally(evidence).decisions < self._config.procedure_challenger_min_decisions:
                await self._retire(record, "insufficient_evidence", tally(evidence), counts)
                continue
            complete.append((record, evidence))
        if not complete:
            return superseded
        return superseded + await self._decide(champion_id, open_records, complete, counts)

    async def _reconcile(
        self, champion_state: tuple[bool, str] | None, record: ChallengeRecord, counts: _CycleCounts,
    ) -> list[Any] | None:
        """Make a pending challenger's routing agree with its ledger row; ``None`` means still pending.

        A restore can pair this ledger with a ``procedures.db`` written after a promotion. A
        challenger that is active while its champion is inactive and superseded by it is that
        completed promotion: it is recorded ``promoted`` (reason ``restored_promotion``) with
        the evidence the ledger holds. Any other active pending challenger is deactivated, so
        a pending or retired challenger never routes. A missing one is retired with its
        evidence. The entry of a challenger that stays pending is rewritten from SQLite. Both
        procedures' activity and supersession are the columns admission reads
        (``ProcedureStore.routing_state``, ``champion_state`` from ``_contest``), so this records
        exactly the pairs routing already admits (review round 6, R6-1).
        """
        state = await self._store.routing_state(record.challenger_id)
        if state is None:
            missing = tally(await self._ledger.comparisons(record.challenger_id))
            await self._retire(record, "challenger_missing", missing, counts)
            return []
        if state[0]:  # R6-1: the challenger's column
            if champion_state == (False, record.challenger_id):
                result = tally(await self._ledger.comparisons(record.challenger_id))
                reason = _decision_text("restored_promotion", result, _threshold(self._config))
                if not await self._ledger.set_status(
                    record.challenger_id, "promoting", reason=reason, expected=("pending",),
                ):
                    return []
                promoting = replace(record, status="promoting", decision_reason=reason)
                return await self._complete_promotion(promoting, counts, result=result)
            logger.warning(
                "AD-1326: pending challenger %s of %s was routable (its ledger row and procedures.db "
                "disagree, e.g. after a restore); it is deactivated until it wins",
                record.challenger_id, record.champion_id,
            )
            await self._store.deactivate(record.challenger_id)
        if not await self._store.sync_routing_index(record.challenger_id):
            logger.warning(
                "AD-1326: the routing index entry of pending challenger %s could not be rewritten; "
                "the next dream cycle tries again",
                record.challenger_id,
            )
        return None

    async def _judge_record(
        self, champion: Procedure, record: ChallengeRecord, counts: _CycleCounts,
    ) -> list[ComparisonRecord] | None:
        """Judge ``record``'s open situations; its evidence when complete, else ``None``."""
        challenger = await self._store.get(record.challenger_id)
        if challenger is None:  # removed since _reconcile; the next cycle retires it with its evidence
            return None
        counted = {c.episode_id for c in await self._ledger.comparisons(record.challenger_id) if c.counted}
        open_ids = [eid for eid in record.context_episode_ids if eid not in counted]
        available = await self._contexts(open_ids)
        if available is None:
            return None
        budget = self._config.procedure_challenger_max_judge_calls_per_cycle
        for episode_id in open_ids:
            episode = available.get(episode_id)
            if episode is None:
                continue
            if counts.calls + JUDGE_CALLS_PER_CONTEXT > budget:
                counts.deferred += 1
                continue
            verdict = await self._judge.compare(
                champion=champion, challenger=challenger, episode=episode,
                optimizer_model=record.optimizer_model,  # R3-1: the rewrite's own model is not an independent judge
            )
            counts.calls += JUDGE_CALLS_PER_CONTEXT
            counts.comparisons += 1
            await self._ledger.record_comparison(
                challenger_id=record.challenger_id,
                champion_id=record.champion_id,
                episode_id=episode_id,
                split="held_out" if episode_id in record.held_out_episode_ids else "used",
                first_shown=verdict.first_shown,
                outcome=verdict.outcome,
                counted=verdict.counted,
                judgements=[judgement_to_json(j) for j in verdict.judgements],
            )
            if verdict.counted:
                counted.add(episode_id)
        if any(eid in available and eid not in counted for eid in open_ids):
            return None
        return await self._ledger.comparisons(record.challenger_id)

    async def _decide(
        self,
        champion_id: str,
        records: list[ChallengeRecord],
        complete: list[tuple[ChallengeRecord, list[ComparisonRecord]]],
        counts: _CycleCounts,
    ) -> list[Any]:
        outcomes = [outcome for record, evidence in complete for outcome in _pair_outcomes(record, evidence)]
        strengths = bradley_terry(outcomes, reference=champion_id)
        ranked = sorted(
            complete,
            key=lambda item: (-strengths[item[0].challenger_id], item[0].created_at, item[0].challenger_id),
        )
        top, top_evidence = ranked[0]
        top_tally = tally(top_evidence)
        if beats_champion(
            wins=top_tally.wins,
            decisions=top_tally.decisions,
            min_decisions=self._config.procedure_challenger_min_decisions,
            margin=self._config.procedure_challenger_promotion_margin,
        ):
            promoted, episodes = await self._promote(top, top_tally, strengths[top.challenger_id], counts)
            if promoted:
                for record in records:
                    if record.challenger_id != top.challenger_id:
                        others = tally(await self._ledger.comparisons(record.challenger_id))
                        await self._retire(record, "champion_replaced", others, counts)
            return episodes
        for record, evidence in complete:
            await self._retire(record, "lost", tally(evidence), counts, strength=strengths[record.challenger_id])
        return []

    async def _promote(
        self, record: ChallengeRecord, result: Tally, strength: float, counts: _CycleCounts,
    ) -> tuple[bool, list[Any]]:
        reason = _decision_text("won", result, _threshold(self._config))
        if not await self._ledger.set_status(record.challenger_id, "promoting", reason=reason, expected=("pending",)):
            return False, []
        promoting = replace(record, status="promoting", decision_reason=reason)
        return True, await self._complete_promotion(promoting, counts, result=result, strength=strength)

    async def _complete_promotion(
        self,
        record: ChallengeRecord,
        counts: _CycleCounts,
        *,
        result: Tally | None = None,
        strength: float | None = None,
    ) -> list[Any]:
        """Activate and confirm the challenger, then retire and confirm the champion, then mark ``promoted``. Safe to repeat."""
        if result is None:
            result = tally(await self._ledger.comparisons(record.challenger_id))
        challenger = await self._store.get(record.challenger_id)
        if challenger is None:
            await self._retire(record, "challenger_missing", result, counts, expected=("promoting",))
            return []
        state = await self._store.routing_state(record.challenger_id)
        if state is None or not state[0]:  # R6-1: activate unless the column says active
            meta = await self._store.get_evolution_metadata(record.challenger_id)
            await self._store.save(
                replace(challenger, is_active=True),
                content_diff=meta.get("content_diff", ""),
                change_summary=meta.get("change_summary", ""),
            )
        # Routing (find_matching) finds a procedure through the semantic index, and save()/deactivate()
        # report an index failure only in the log. The challenger's entry is confirmed BEFORE the
        # champion is deactivated, so the lineage keeps routing through an index outage (review
        # round 2, R2-2); the decision is sealed once the champion's entry is rewritten as well.
        # Until then it stays ``promoting`` and the next cycle repeats this method.
        if not await self._store.sync_routing_index(challenger.id):
            logger.warning(
                "AD-1326: the promotion of %s over %s waits: the challenger's routing index entry could "
                "not be written, so the champion keeps routing; it stays promoting and the next dream "
                "cycle retries it",
                record.challenger_id, record.champion_id,
            )
            return []
        champion_state = await self._store.routing_state(record.champion_id)
        if champion_state is not None and champion_state[0]:  # R6-1: the champion's column
            await self._store.deactivate(record.champion_id, superseded_by=record.challenger_id)
        if not await self._store.sync_routing_index(record.champion_id):
            logger.warning(
                "AD-1326: the promotion of %s over %s is in SQLite but the champion's routing index entry "
                "did not take it; it stays promoting and the next dream cycle retries it",
                record.challenger_id, record.champion_id,
            )
            return []
        if not await self._ledger.set_status(
            record.challenger_id, "promoted", reason=record.decision_reason, expected=("promoting",),
        ):
            return []
        counts.promoted += 1
        self._emit(record, "promoted", record.decision_reason.split(":", 1)[0] or "won", result, strength)
        logger.info(
            "AD-1326: procedure %s replaced champion %s after winning %d of %d judgements (%d of %d held out)",
            record.challenger_id, record.champion_id, result.wins, result.decisions,
            result.held_out_wins, result.held_out_decisions,
        )
        return await self._source_episodes(record)

    async def _retire(
        self,
        record: ChallengeRecord,
        reason: str,
        result: Tally,
        counts: _CycleCounts,
        *,
        expected: tuple[str, ...] = ("pending",),
        strength: float | None = None,
    ) -> bool:
        detail = _decision_text(reason, result, _threshold(self._config))
        # A retired challenger never routes: the decision is sealed only once its index entry is
        # rewritten from SQLite (inactive, or no row); until then the row keeps its status and a
        # later cycle retries (review round 2, R2-1).
        if not await self._store.sync_routing_index(record.challenger_id):  # R2-1: sealed only when routing agrees
            logger.warning(
                "AD-1326: challenger %s of %s is not retired (%s) yet: its routing index entry could not "
                "be rewritten; the next dream cycle tries again",
                record.challenger_id, record.champion_id, reason,
            )
            return False
        if not await self._ledger.set_status(record.challenger_id, "retired", reason=detail, expected=expected):  # type: ignore[arg-type]
            return False
        counts.retired += 1
        self._emit(record, "retired", reason, result, strength)
        logger.info(
            "AD-1326: procedure challenger %s of %s retired (%s); its evidence is kept",
            record.challenger_id, record.champion_id, reason,
        )
        return True

    async def _age(self, counts: _CycleCounts) -> None:
        for record in await self._ledger.list_by_status("pending"):
            cycles = await self._ledger.increment_cycles(record.challenger_id)
            if cycles >= self._config.procedure_challenger_max_pending_cycles:
                expired = tally(await self._ledger.comparisons(record.challenger_id))
                await self._retire(record, "expired", expired, counts)

    async def _contexts(self, ids: list[str]) -> dict[str, Any] | None:
        """Episodes for ``ids`` by id, plan-mode turns dropped; ``None`` when unreadable this cycle."""
        if not ids:
            return {}
        try:
            found = await self._episodes.get_by_ids(list(ids), for_evidence=True)
        except Exception:
            logger.warning(
                "AD-1326: comparison episodes could not be read; the challengers that need them wait "
                "for the next dream cycle",
                exc_info=True,
            )
            return None
        if not found:  # nothing came back: unreadable this cycle, not missing
            return None
        return {ep.id: ep for ep in found if not episode_ran_in_plan_mode(ep)}

    async def _source_episodes(self, record: ChallengeRecord) -> list[Any]:
        try:
            return list(await self._episodes.get_by_ids([*record.used_episode_ids, *record.held_out_episode_ids]))
        except Exception:
            logger.warning(
                "AD-1326: the source episodes of promoted procedure %s could not be read; they are not "
                "expired this cycle",
                record.challenger_id, exc_info=True,
            )
            return []

    def _emit(
        self, record: ChallengeRecord, decision: str, reason: str, result: Tally, strength: float | None,
    ) -> None:
        if self._emit_event_fn is None:
            return
        payload: dict[str, Any] = {
            "challenger_id": record.challenger_id,
            "champion_id": record.champion_id,
            "decision": decision,
            "reason": reason,
            "wins": result.wins,
            "losses": result.losses,
            "ties": result.ties,
            "decisions": result.decisions,
            "held_out_wins": result.held_out_wins,
            "held_out_decisions": result.held_out_decisions,
            "strength": None if strength is None else round(strength, 6),
            "judge_independence": list(result.independence),
        }
        try:
            self._emit_event_fn(EventType.PROCEDURE_CHALLENGE_DECIDED, payload)
        except Exception:
            logger.warning(
                "AD-1326: the %s event for challenger %s could not be emitted; the ledger holds the decision",
                decision, record.challenger_id, exc_info=True,
            )


def build_procedure_challenger(
    *,
    config: SystemConfig,
    procedure_store: Any,
    episodic_memory: Any,
    llm_client: Any,
    emit_event_fn: Callable[..., Any] | None,
    rng: random.Random | None = None,
) -> ProcedureChallenger | None:
    """AD-1326: the challenger service, or ``None`` for the legacy FIX handling."""
    dreaming = config.dreaming
    if not dreaming.procedure_challenger_enabled:
        logger.info(
            "AD-1326: procedure challengers are off (dreaming.procedure_challenger_enabled=false); "
            "FIX evolution follows its legacy handling"
        )
        return None
    if procedure_store is None or llm_client is None or episodic_memory is None:
        return None
    ledger = procedure_store.challenges
    if not isinstance(ledger, ProcedureChallengeLedger):
        logger.warning(
            "AD-1326: the procedure challenger ledger is not open; FIX evolution follows its legacy "
            "handling until it is"
        )
        return None
    policy = VerifierJudgePolicy.from_cognitive(config.cognitive)
    judge = ProcedureJudge(llm_client, policy, rng=rng or random.Random())
    logger.info(
        "AD-1326: procedure challengers are judged on the %s tier (%s); only independent judgements "
        "count: %s",
        policy.request_tier, policy.assess(), judge.requires_independent,
    )
    return ProcedureChallenger(
        store=procedure_store,
        ledger=ledger,
        episodes=episodic_memory,
        judge=judge,
        config=dreaming,
        emit_event_fn=emit_event_fn,
    )
