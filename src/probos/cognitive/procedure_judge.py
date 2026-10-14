"""AD-1326 (#1510): the head-to-head judge for a procedure challenger and its champion.

A procedure's output is what replay hands the agent: its step list (AD-534 replay
replaces the LLM call with the steps, ``cognitive_agent._format_procedure_replay``).
So a comparison shows the judge one real situation -- an episode the procedure is
for -- and both candidates as "Candidate 1" and "Candidate 2", each rendered as
replay renders it after replay's two header lines, which name the procedure: the
description, every step with its agent role, expected output and fallback, and the
postconditions (``test_render_candidate_is_the_replay_body``), then bounded by
``bounded_text`` to ``MAX_CANDIDATE_CHARS``. A body of at most 4,000 characters with no
NUL or lone surrogate reaches the judge unchanged; a longer one is cut there, so steps
past the cut are not shown (``test_render_candidate_is_the_bounded_replay_body_at_the_cut``).
Replay does not show
preconditions, so neither does the judge. Nothing names or dates a candidate: no
name, id, generation, evolution type, parents or tags
(``test_render_candidate_hides_identity``).

Each situation is judged twice, once in each order; ``rng`` picks the order asked
first. A candidate wins the situation only when it wins in both orders; a split, or
a tie in either order, is a tie. A judge that always prefers one position therefore
produces ties and nothing else (``test_position_biased_judge_yields_only_ties``;
MT-Bench's swap check, Zheng et al. 2023, arXiv:2306.05685).

The judge is AD-1327's crew-verifier judge (``VerifierJudgePolicy``): it requests the
``verifier`` tier when ``cognitive.llm_model_verifier`` is set, else ``standard`` --
the policy admits no other tier, so never the ``deep`` tier the rewrite ran on.
Every judgement records its ``JudgeProvenance``. When the configured judge is
independent of every crew tier, a situation counts only if both its judgements were
answered independently; a fallback answer is recorded and not counted. The model that
answered the rewrite (``optimizer_model``) is one more model each judgement is compared
with, so a judge answering as the optimizer is not independent of it (review round 3,
R3-1); whether independence is required is still the configured policy's decision.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, Protocol

from probos.cognitive.crew_verdict import JudgeProvenance, judge_to_json
from probos.cognitive.procedure_challenges import bounded_text
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.procedures import Procedure
    from probos.cognitive.verifier_independence import VerifierJudgePolicy
    from probos.types import Episode, LLMResponse

logger = logging.getLogger(__name__)

Side = Literal["champion", "challenger"]
Winner = Literal["champion", "challenger", "tie", "invalid"]
Preference = Literal["1", "2", "tie", "invalid"]

MAX_REASON_CHARS = 500
MAX_CANDIDATE_CHARS = 4000
MAX_SITUATION_CHARS = 2000
JUDGE_MAX_TOKENS = 512

JUDGE_SYSTEM_PROMPT = (
    "You compare two candidate procedures for the same kind of task. Each candidate is the "
    "step list an agent would follow. Decide which candidate would better handle the situation "
    "shown. Position, length and wording style are not evidence. Answer with one JSON object "
    'only: {"preferred": "1" or "2" or "tie", "reason": "<one or two sentences>"}.'
)


class JudgeLLM(Protocol):
    """The one LLM-client method the judge uses."""

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


@dataclass(frozen=True)
class Judgement:
    """One call: the side shown first, the side that won it, why, and who judged."""

    shown_first: Side
    winner: Winner
    reason: str
    judge: JudgeProvenance


@dataclass(frozen=True)
class SituationVerdict:
    """One situation judged in both orders."""

    first_shown: Side
    outcome: Winner
    counted: bool
    judgements: tuple[Judgement, Judgement]


def judgement_to_json(judgement: Judgement) -> dict[str, Any]:
    return {
        "shown_first": judgement.shown_first,
        "winner": judgement.winner,
        "reason": judgement.reason,
        "judge": judge_to_json(judgement.judge),
    }


def render_candidate(procedure: Procedure) -> str:
    """The candidate as ``cognitive_agent._format_procedure_replay`` renders it, bounded.

    Replay's first two lines (``[Procedure Replay: <name>]`` and the match-score line)
    and the blank line after them are left out: they name the procedure. A role-only
    repair therefore reaches the judge as replay would hand it to the agent. The body
    then passes ``bounded_text(..., MAX_CANDIDATE_CHARS)``: it equals replay's body when
    that has at most 4,000 characters and no NUL or lone surrogate, and is replay's body
    cut at 4,000 characters otherwise (a long description can crowd out every step).
    """
    lines: list[str] = []
    if procedure.description:
        lines.append(procedure.description)
        lines.append("")
    for step in procedure.steps:
        role = step.agent_role
        head = f"**Step {step.step_number} [{role}]:**" if role else f"**Step {step.step_number}:**"
        lines.append(f"{head} {step.action}")
        if step.expected_output:
            lines.append(f"  → Expected: {step.expected_output}")
        if step.fallback_action:
            lines.append(f"  ⚠ Fallback: {step.fallback_action}")
    if procedure.postconditions:
        lines.append("")
        lines.append("**Postconditions:**")
        for item in procedure.postconditions:
            lines.append(f"  - {item}")
    return bounded_text("\n".join(lines), MAX_CANDIDATE_CHARS)


def render_situation(episode: Episode) -> str:
    """The episode's request and recorded outcome, bounded."""
    try:
        outcomes = json.dumps(episode.outcomes, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        outcomes = "<unrenderable>"
    return bounded_text(f"Request: {episode.user_input}\nRecorded outcome: {outcomes}", MAX_SITUATION_CHARS)


def build_judge_prompt(situation: str, first: str, second: str) -> str:
    return (
        "=== READ-ONLY SITUATION (a real episode; do not modify) ===\n"
        f"{situation}\n"
        "=== END SITUATION ===\n\n"
        "=== CANDIDATE 1 ===\n"
        f"{first}\n"
        "=== END CANDIDATE 1 ===\n\n"
        "=== CANDIDATE 2 ===\n"
        f"{second}\n"
        "=== END CANDIDATE 2 ==="
    )


def parse_preference(text: object) -> tuple[Preference, str]:
    """The preferred position and the reason; anything unreadable is ``invalid``."""
    if type(text) is not str:
        return "invalid", ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return "invalid", ""
    try:
        payload = json.loads(text[start : end + 1])
    except ValueError:
        return "invalid", ""
    if type(payload) is not dict:
        return "invalid", ""
    preferred = payload.get("preferred")
    if type(preferred) is int and preferred in (1, 2):
        preferred = str(preferred)
    reason = bounded_text(payload.get("reason"), MAX_REASON_CHARS)
    if type(preferred) is not str or preferred not in ("1", "2", "tie"):
        return "invalid", reason
    return preferred, reason  # type: ignore[return-value]


def combine_orders(one: Winner, two: Winner) -> Winner:
    """The situation's outcome from its two judgements."""
    if "invalid" in (one, two):
        return "invalid"
    if one == two:
        return one
    return "tie"  # the orders disagree: position decided it, so nobody wins


class ProcedureJudge:
    """AD-1326: judges a challenger against its champion on one situation, in both orders."""

    def __init__(self, llm_client: JudgeLLM, policy: VerifierJudgePolicy, *, rng: random.Random) -> None:
        self._llm = llm_client
        self._policy = policy
        self._rng = rng
        self._requires_independent = policy.assess() == "independent"

    @property
    def request_tier(self) -> str:
        return self._policy.request_tier

    @property
    def requires_independent(self) -> bool:
        """Whether only independently answered judgements count (an independent judge is configured)."""
        return self._requires_independent

    async def compare(
        self, *, champion: Procedure, challenger: Procedure, episode: Episode, optimizer_model: str = "",
    ) -> SituationVerdict:
        """Judge one situation in both orders.

        ``optimizer_model`` is the model that answered the challenger's rewrite (the ledger's
        ``optimizer_model``; ``""`` when not reported). It joins the crew models each answer is
        classified against, so an answer by that model is ``same_model`` and, when an
        independent judge is required, not counted
        (``test_judgement_by_the_optimizers_model_is_not_independent``). Whether independence
        is required is decided by the configured policy alone. A label is never raised by it:
        an answer the augmented policy calls ``independent`` keeps the configured policy's label
        when that is weaker, as with an empty crew basis (review round 4, R4-3,
        ``test_optimizer_model_never_raises_a_label``).
        """
        extra = (optimizer_model,) if type(optimizer_model) is str and optimizer_model else ()
        policy = replace(self._policy, crew_models=(*self._policy.crew_models, *extra))
        situation = render_situation(episode)
        rendered: dict[str, str] = {
            "champion": render_candidate(champion),
            "challenger": render_candidate(challenger),
        }
        first: Side = "champion" if self._rng.random() < 0.5 else "challenger"
        second: Side = "challenger" if first == "champion" else "champion"
        first_verdict = await self._ask(policy, situation, rendered, first, second)
        second_verdict = await self._ask(policy, situation, rendered, second, first)
        outcome = combine_orders(first_verdict.winner, second_verdict.winner)
        counted = outcome != "invalid" and (
            not self._requires_independent
            or all(j.judge.independence == "independent" for j in (first_verdict, second_verdict))
        )
        return SituationVerdict(first, outcome, counted, (first_verdict, second_verdict))

    async def _ask(
        self,
        policy: VerifierJudgePolicy,
        situation: str,
        rendered: dict[str, str],
        shown_first: Side,
        shown_second: Side,
    ) -> Judgement:
        request = LLMRequest(
            prompt=build_judge_prompt(situation, rendered[shown_first], rendered[shown_second]),
            system_prompt=JUDGE_SYSTEM_PROMPT,
            tier=policy.request_tier,
            temperature=0.0,
            max_tokens=JUDGE_MAX_TOKENS,
        )
        try:
            response = await self._llm.complete(request)
        except Exception as exc:
            # Log-and-degrade: an unanswered judgement is recorded invalid; the situation stays open.
            logger.warning(
                "AD-1326: a procedure comparison call failed (%s); it is recorded invalid and the "
                "situation is judged again next dream cycle",
                type(exc).__name__,
            )
            return Judgement(
                shown_first, "invalid", "llm_call_failed",
                policy.provenance(answered_tier=None, answered_model=None),
            )
        judge = policy.provenance(answered_tier=response.answered_tier, answered_model=response.answered_model)
        baseline = self._policy.provenance(answered_tier=response.answered_tier, answered_model=response.answered_model)
        if judge.independence == "independent" and baseline.independence != "independent":
            judge = baseline  # R4-3: adding the optimizer's model never raises a label
        if response.error:
            return Judgement(shown_first, "invalid", bounded_text(f"llm_error: {response.error}", MAX_REASON_CHARS), judge)
        preferred, reason = parse_preference(response.content)
        if preferred == "invalid":
            return Judgement(shown_first, "invalid", reason, judge)
        if preferred == "tie":
            return Judgement(shown_first, "tie", reason, judge)
        return Judgement(shown_first, shown_first if preferred == "1" else shown_second, reason, judge)
