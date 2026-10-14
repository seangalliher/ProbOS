"""AD-1326 (#1510), milestone 2: the head-to-head judge (``cognitive/procedure_judge.py``).

Every test crosses the real seam the judge sits on. The LLM double receives the real
``LLMRequest`` the judge builds and answers with a real ``LLMResponse`` that carries
``tier``, ``answered_tier`` and ``answered_model`` the way ``OpenAICompatibleClient`` sets them:
``tier`` stays the tier asked for, ``answered_tier`` names the tier whose attempt answered (a
verifier attempt that fell back answers with ``answered_tier="standard"``), ``answered_model`` is
the model id the reply named. Procedures and episodes are the real ``Procedure``,
``ProcedureStep`` and ``Episode``. Model ids are ones ``model_registry.model_family`` knows,
taken from ``tests/test_ad1327_verifier_independence.py``.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import json
import random
import re
from collections import Counter
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.procedure_judge import (
    MAX_CANDIDATE_CHARS,
    ProcedureJudge,
    SituationVerdict,
    build_judge_prompt,
    combine_orders,
    judgement_to_json,
    parse_preference,
    render_candidate,
    render_situation,
)
from probos.cognitive.procedures import PROCEDURE_REWRITE_TIER, Procedure, ProcedureStep
from probos.cognitive.verifier_independence import VerifierJudgePolicy, classify_independence
from probos.config import CognitiveConfig
from probos.types import Episode, LLMRequest, LLMResponse

# The AD-1327 tests' ``_CLAUDE_CREW``: the fast, standard and deep tiers' models.
_CREW = ("claude-sonnet-4-6", "claude-sonnet-4-6", "claude-opus-4-6")
_MARKER = "RUN-THE-CHECKSUM-MARKER"
_AS_REQUESTED = "<as-requested>"

_CANDIDATE_RE = re.compile(r"=== CANDIDATE (\d) ===\n(.*?)\n=== END CANDIDATE \1 ===", re.DOTALL)
_SITUATION_RE = re.compile(r"=== READ-ONLY SITUATION[^\n]*===\n(.*?)\n=== END SITUATION ===", re.DOTALL)


# ------------------------------------------------------------------ doubles and builders


class _Answered(NamedTuple):
    """What a response says answered it: ``LLMResponse.answered_tier`` and ``answered_model``."""

    tier: str | None
    model: str | None


class _FakeLLM:
    """The judge's LLM seam: records every real request, answers with what ``reply`` returns or raises."""

    def __init__(self, reply: Callable[[LLMRequest, int], LLMResponse | BaseException]) -> None:
        self.requests: list[LLMRequest] = []
        self._reply = reply

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        outcome = self._reply(request, len(self.requests) - 1)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _response(
    request: LLMRequest,
    content: str,
    *,
    answered_tier: str | None = _AS_REQUESTED,
    answered_model: str | None = "gpt-5.1",
    error: str | None = None,
) -> LLMResponse:
    """A reply as the client builds it: ``tier`` is the one asked for; ``answered_*`` say who answered."""
    return LLMResponse(
        content=content,
        model="id-sent-to-the-provider",
        tier=request.tier,
        answered_tier=request.tier if answered_tier == _AS_REQUESTED else answered_tier,
        answered_model=answered_model,
        error=error,
    )


def _pick(preferred: object, reason: str = "because") -> str:
    return json.dumps({"preferred": preferred, "reason": reason})


def _tie_judge(reason: str = "because") -> _FakeLLM:
    return _FakeLLM(lambda request, call: _response(request, _pick("tie", reason)))


def _candidates(prompt: str) -> tuple[str, str]:
    """The text a real judge prompt shows as Candidate 1 and Candidate 2."""
    shown = {int(number): text for number, text in _CANDIDATE_RE.findall(prompt)}
    return shown[1], shown[2]


def _situation_of(prompt: str) -> str:
    match = _SITUATION_RE.search(prompt)
    assert match is not None, "the prompt shows no situation block"
    return match.group(1)


def _marker_judge(*answers: _Answered) -> _FakeLLM:
    """A judge of content: it prefers the candidate that carries the marker step, wherever it is shown.

    With ``answers`` the nth call is answered by the nth tier and model; without, the requested tier answers.
    """

    def reply(request: LLMRequest, call: int) -> LLMResponse:
        first, second = _candidates(request.prompt)
        preferred = {(True, False): "1", (False, True): "2"}.get((_MARKER in first, _MARKER in second), "tie")
        if answers:
            return _response(
                request, _pick(preferred), answered_tier=answers[call].tier, answered_model=answers[call].model,
            )
        return _response(request, _pick(preferred))

    return _FakeLLM(reply)


def _independent_policy() -> VerifierJudgePolicy:
    policy = VerifierJudgePolicy("verifier", "gpt-5.1", _CREW)
    assert policy.assess() == "independent"  # premise: gpt-5.1 is another family from the Claude crew
    return policy


def _standard_policy() -> VerifierJudgePolicy:
    return VerifierJudgePolicy("standard", "claude-sonnet-4-6", _CREW)


def _procedure(name: str, *actions: str) -> Procedure:
    return Procedure(
        id=f"{name}-id",
        name=name,
        steps=[ProcedureStep(step_number=number, action=action) for number, action in enumerate(actions, start=1)],
    )


def _plain() -> Procedure:
    return _procedure("plain", "Revoke the old key", "Issue the new key")


def _marked() -> Procedure:
    return _procedure("marked", "Revoke the old key", f"Run {_MARKER} on the new key", "Issue the new key")


def _episode(user_input: str = "Rotate the signing key for the build service", outcomes: Any = None) -> Episode:
    return Episode(
        id="episode-1",
        user_input=user_input,
        outcomes=[{"intent": "rotate_key", "success": True}] if outcomes is None else outcomes,
    )


async def _compare(
    llm: _FakeLLM,
    *,
    policy: VerifierJudgePolicy | None = None,
    seed: int = 0,
    champion: Procedure | None = None,
    challenger: Procedure | None = None,
    episode: Episode | None = None,
) -> SituationVerdict:
    judge = ProcedureJudge(llm, policy or _standard_policy(), rng=random.Random(seed))
    return await judge.compare(
        champion=champion or _procedure("alpha", "Revoke the old key"),
        challenger=challenger or _procedure("beta", "Issue the new key"),
        episode=episode or _episode(),
    )


# ------------------------------------------------------------------ what the judge is shown


def test_render_candidate_hides_identity() -> None:
    procedure = Procedure(
        id="id-sentinel-7f3a",
        name="Name Sentinel Runbook",
        description="Rotate one credential.",
        steps=[
            ProcedureStep(
                step_number=1, action="Revoke the old key", agent_role="key_revocation",
                expected_output="the old key is refused", fallback_action="page the key owner",
            ),
            ProcedureStep(
                step_number=2, action="Issue the new key", agent_role="key_issuance",
                expected_output="the new key is accepted",
            ),
        ],
        preconditions=["the caller holds the rotate permission"],
        postconditions=["only the new key is valid"],
        evolution_type="DERIVED",
        generation=4242,
        parent_procedure_ids=["parent-sentinel-91bc"],
        tags=["tag-sentinel-ops"],
    )

    rendered = render_candidate(procedure)

    hidden = {
        "name": procedure.name,
        "id": procedure.id,
        "generation": "4242",
        "evolution_type": "DERIVED",
        "parent id": "parent-sentinel-91bc",
        "tag": "tag-sentinel-ops",
    }
    leaked = [label for label, text in hidden.items() if text.lower() in rendered.lower()]
    assert leaked == []
    shown = {
        "step 1": "Revoke the old key",
        "step 1 agent role": "**Step 1 [key_revocation]:**",
        "step 1 expected output": "the old key is refused",
        "step 1 fallback": "page the key owner",
        "step 2": "Issue the new key",
        "step 2 agent role": "**Step 2 [key_issuance]:**",
        "step 2 expected output": "the new key is accepted",
        "postcondition": "only the new key is valid",
    }
    missing = [label for label, text in shown.items() if text not in rendered]
    assert missing == []
    # Review round 1 (F2): this test used to list the precondition among what is shown. The rendering is now
    # replay's own body line for line (test_render_candidate_is_the_replay_body) and replay never shows
    # preconditions, so the judge does not either; the old line pinned a rendering richer than replay's.
    assert "the caller holds the rotate permission" not in rendered


def _replay(procedure: Procedure) -> str:
    """What AD-534 replay hands the agent for ``procedure``, from the real formatter.

    ``_format_procedure_replay`` and the ``_format_single_step`` it calls read only their arguments,
    so an agent that was never initialised is enough.
    """
    agent = CognitiveAgent.__new__(CognitiveAgent)
    return CognitiveAgent._format_procedure_replay(agent, procedure)


_REPLAY_PARTS = ("description", "agent_role", "expected_output", "fallback", "postconditions")


def _replay_procedure(parts: tuple[bool, ...]) -> Procedure:
    """Three steps; each step part that is on is set on steps 1 and 3 and left off step 2."""
    description, role, expected, fallback, postconditions = parts
    steps = [
        ProcedureStep(
            step_number=number,
            action=action,
            agent_role=f"role_{number}" if role and number != 2 else "",
            expected_output=f"expected output {number}" if expected and number != 2 else "",
            fallback_action=f"fallback {number}" if fallback and number != 2 else "",
        )
        for number, action in enumerate(("Revoke the old key", "Issue the new key", "Verify the new key"), start=1)
    ]
    return Procedure(
        name="Replay Sentinel Runbook",
        description="Rotate one credential." if description else "",
        steps=steps,
        postconditions=["only the new key is valid", "the old key is refused"] if postconditions else [],
    )


# Every on/off combination of the five parts replay can show, then two procedures that have no steps.
_REPLAY_CASES = [
    pytest.param(
        functools.partial(_replay_procedure, parts),
        id="+".join(name for name, on in zip(_REPLAY_PARTS, parts, strict=True) if on) or "bare_steps",
    )
    for parts in itertools.product((False, True), repeat=len(_REPLAY_PARTS))
] + [
    pytest.param(lambda: Procedure(name="Empty Runbook"), id="no_steps_at_all"),
    pytest.param(
        lambda: Procedure(
            name="Stepless Runbook", description="Rotate one credential.", postconditions=["only the new key is valid"],
        ),
        id="no_steps_with_a_description_and_postconditions",
    ),
]


@pytest.mark.parametrize("build", _REPLAY_CASES)
def test_render_candidate_is_the_replay_body(build: Callable[[], Procedure]) -> None:
    # Review round 1 (F2): the judge is shown what replay hands the agent, so a repair to a step's agent role,
    # expected output or fallback, or to the postconditions, is a difference the judge can see and prefer.
    procedure = build()

    lines = _replay(procedure).split("\n")

    # Premise: replay opens with two header lines that name the procedure and a blank line, then the body.
    assert lines[:3] == [
        f"[Procedure Replay: {procedure.name}]",
        f"Match score: 0.000 | Steps: {len(procedure.steps)}",
        "",
    ]
    body = "\n".join(lines[3:])
    assert len(body) < 4000  # under the candidate bound: nothing is truncated, so the match below is exact
    assert render_candidate(procedure) == body


@pytest.mark.parametrize(
    ("body_length", "shown_whole"),
    [
        pytest.param(3999, True, id="one_under_the_cut"),
        pytest.param(4000, True, id="at_the_cut"),
        pytest.param(4001, False, id="one_over_the_cut"),
        pytest.param(4200, False, id="the_reviewers_4200"),
    ],
)
def test_render_candidate_is_the_bounded_replay_body_at_the_cut(body_length: int, shown_whole: bool) -> None:
    # Review round 2 (R2-5): "exactly" and "line for line" were too strong. The judge is shown replay's body through
    # bounded_text: whole up to MAX_CANDIDATE_CHARS characters, cut there beyond it, so a long description can
    # crowd every step out (the reviewer's 4,200-character case).
    def procedure_with(description_length: int) -> Procedure:
        return Procedure(
            name="Bound Sentinel Runbook",
            description=("0123456789" * 500)[:description_length],  # ASCII, so a cut is a plain slice
            steps=[ProcedureStep(step_number=1, action="Compute the result")],
        )

    def replay_body(procedure: Procedure) -> str:
        return "\n".join(_replay(procedure).split("\n")[3:])  # after replay's two header lines and the blank line

    overhead = len(replay_body(procedure_with(1))) - 1  # replay's blank line and step around the description
    procedure = procedure_with(body_length - overhead)
    body = replay_body(procedure)

    # Premises: the cut the cases straddle, the body's length, and replay (which never cuts) holding the step.
    assert MAX_CANDIDATE_CHARS == 4000
    assert len(body) == body_length
    assert "**Step 1:** Compute the result" in body

    rendered = render_candidate(procedure)

    assert rendered == body[:MAX_CANDIDATE_CHARS]
    assert (rendered == body) is shown_whole  # up to the cut that is the whole body; beyond it, its head
    assert len(rendered) == min(body_length, MAX_CANDIDATE_CHARS)
    assert ("**Step 1:** Compute the result" in rendered) is shown_whole  # a step past the cut is not shown


async def test_render_candidate_distinguishes_a_role_only_repair() -> None:
    # Review round 1 (F2), the reviewer's pair: one step, repaired only in its agent role. Both candidates
    # used to render the same, so the judge saw two identical candidates and the repair could never win.
    calculation = Procedure(
        name="Compute", steps=[ProcedureStep(step_number=1, action="Compute the result", agent_role="calculation")],
    )
    formatting = Procedure(
        name="Compute", steps=[ProcedureStep(step_number=1, action="Compute the result", agent_role="formatting")],
    )
    assert _replay(calculation) != _replay(formatting)  # premise: replay hands the agent two different step lists

    shown_calculation, shown_formatting = render_candidate(calculation), render_candidate(formatting)

    assert shown_calculation != shown_formatting
    assert "**Step 1 [calculation]:**" in shown_calculation
    assert "**Step 1 [formatting]:**" in shown_formatting
    # The seam: both real judge requests carry the two renderings, so the judge can tell the pair apart.
    llm = _tie_judge()
    await _compare(llm, champion=calculation, challenger=formatting)
    assert len(llm.requests) == 2
    for request in llm.requests:
        assert set(_candidates(request.prompt)) == {shown_calculation, shown_formatting}


async def test_prompts_never_name_roles() -> None:
    champion = _procedure("champion", "Revoke the old key")
    challenger = _procedure("challenger", "Issue the new key")  # names and ids that say the role must not leak
    llm = _tie_judge()

    await _compare(llm, champion=champion, challenger=challenger)

    assert len(llm.requests) == 2
    for request in llm.requests:
        for text in (request.system_prompt, request.prompt):
            lowered = text.lower()
            assert "champion" not in lowered
            assert "challenger" not in lowered


@pytest.mark.parametrize("seed", range(6))
async def test_each_situation_is_asked_in_both_orders(seed: int) -> None:
    episode = _episode()
    alpha, beta = _procedure("alpha", "ALPHA-STEP one"), _procedure("beta", "BETA-STEP two")
    llm = _tie_judge("same quality")

    verdict = await _compare(llm, seed=seed, champion=alpha, challenger=beta, episode=episode)

    assert len(llm.requests) == 2
    shown = {"champion": render_candidate(alpha), "challenger": render_candidate(beta)}
    first_side = verdict.first_shown
    other_side = "challenger" if first_side == "champion" else "champion"
    first_request, second_request = llm.requests
    assert _candidates(first_request.prompt) == (shown[first_side], shown[other_side])
    assert _candidates(second_request.prompt) == (shown[other_side], shown[first_side])  # the second call reverses it
    for request, (one, two) in zip(llm.requests, [(first_side, other_side), (other_side, first_side)], strict=True):
        assert request.prompt == build_judge_prompt(render_situation(episode), shown[one], shown[two])
    assert [j.shown_first for j in verdict.judgements] == [first_side, other_side]
    assert [j.reason for j in verdict.judgements] == ["same quality", "same quality"]


async def test_rng_chooses_the_first_order_deterministically() -> None:
    first_shown: set[str] = set()
    for seed in range(20):
        runs: list[tuple[str, list[str]]] = []
        for _ in range(2):
            llm = _tie_judge()
            verdict = await _compare(llm, seed=seed)
            runs.append((verdict.first_shown, [request.prompt for request in llm.requests]))
        assert runs[0] == runs[1], f"seed {seed} did not give the same exchange twice"
        first_shown.add(runs[0][0])
    assert first_shown == {"champion", "challenger"}  # seeds 0..19 produce both orders


# ------------------------------------------------------------------ the outcome of a situation


@pytest.mark.parametrize("position", ["1", "2"])
async def test_position_biased_judge_yields_only_ties(position: str) -> None:
    outcomes: Counter[str] = Counter()
    for seed in range(20):
        llm = _FakeLLM(lambda request, call: _response(request, _pick(position)))

        verdict = await _compare(llm, seed=seed)

        outcomes[verdict.outcome] += 1
        assert verdict.counted is True, f"seed {seed}: a tie of two readable judgements counts"
        # Position decided each call, so the two calls favoured different sides.
        assert {j.winner for j in verdict.judgements} == {"champion", "challenger"}, f"seed {seed}"
    assert outcomes == Counter({"tie": 20})


@pytest.mark.parametrize("seed", range(20))
async def test_content_judge_outcome_ignores_position_and_role(seed: int) -> None:
    challenger_has_it = await _compare(_marker_judge(), seed=seed, champion=_plain(), challenger=_marked())

    assert (challenger_has_it.outcome, challenger_has_it.counted) == ("challenger", True)
    assert {j.winner for j in challenger_has_it.judgements} == {"challenger"}  # both orders agree

    champion_has_it = await _compare(_marker_judge(), seed=seed, champion=_marked(), challenger=_plain())

    assert (champion_has_it.outcome, champion_has_it.counted) == ("champion", True)  # the win follows the content
    assert {j.winner for j in champion_has_it.judgements} == {"champion"}


_SIDES = ("champion", "challenger", "tie", "invalid")
# Row = the first order's winner; column = the second order's winner, in the order of ``_SIDES``.
_COMBINED = {
    "champion": ("champion", "tie", "tie", "invalid"),
    "challenger": ("tie", "challenger", "tie", "invalid"),
    "tie": ("tie", "tie", "tie", "invalid"),
    "invalid": ("invalid", "invalid", "invalid", "invalid"),
}


@pytest.mark.parametrize(
    ("one", "two", "expected"),
    [
        pytest.param(one, two, expected, id=f"{one}+{two}")
        for one, row in _COMBINED.items()
        for two, expected in zip(_SIDES, row, strict=True)
    ],
)
def test_combine_orders_table(one: str, two: str, expected: str) -> None:
    assert combine_orders(one, two) == expected  # type: ignore[arg-type]


# ------------------------------------------------------------------ replies that cannot be read


_FAILURES: list[Any] = [
    pytest.param(lambda request: _response(request, "Candidate 1 reads better, I would pick it."), id="not_json"),
    pytest.param(lambda request: _response(request, _pick("3")), id="preferred_out_of_range"),
    pytest.param(lambda request: _response(request, _pick(True)), id="preferred_is_a_boolean"),
    pytest.param(
        lambda request: _response(request, "", answered_tier=None, answered_model=None, error="upstream 503"),
        id="response_carries_an_error",
    ),
    pytest.param(lambda request: RuntimeError("endpoint unreachable"), id="llm_call_raises_runtime_error"),
]


@pytest.mark.parametrize("bad_calls", [(0,), (1,), (0, 1)], ids=["first_order", "second_order", "both_orders"])
@pytest.mark.parametrize("failure", _FAILURES)
async def test_invalid_reply_error_or_exception_is_invalid_and_not_counted(
    failure: Callable[[LLMRequest], LLMResponse | BaseException], bad_calls: tuple[int, ...],
) -> None:
    def reply(request: LLMRequest, call: int) -> LLMResponse | BaseException:
        return failure(request) if call in bad_calls else _response(request, _pick("1"))

    verdict = await _compare(_FakeLLM(reply))

    assert (verdict.outcome, verdict.counted) == ("invalid", False)  # unreadable in either order: the situation stays open
    assert len(verdict.judgements) == 2
    for call, judgement in enumerate(verdict.judgements):
        if call in bad_calls:
            assert judgement.winner == "invalid"
        else:
            assert judgement.winner in ("champion", "challenger")  # the readable half is still recorded


@pytest.mark.parametrize("cancelled_call", [0, 1], ids=["first_order", "second_order"])
async def test_cancelled_error_from_the_llm_propagates_instead_of_being_recorded_invalid(cancelled_call: int) -> None:
    def reply(request: LLMRequest, call: int) -> LLMResponse | BaseException:
        return asyncio.CancelledError() if call == cancelled_call else _response(request, _pick("tie"))

    llm = _FakeLLM(reply)

    with pytest.raises(asyncio.CancelledError):
        await _compare(llm)

    assert len(llm.requests) == cancelled_call + 1  # the judge did not go on asking after the cancellation


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param('{"preferred": "1", "reason": "r"}', ("1", "r"), id="string_1"),
        pytest.param('{"preferred": "2", "reason": "r"}', ("2", "r"), id="string_2"),
        pytest.param('{"preferred": "tie", "reason": "r"}', ("tie", "r"), id="string_tie"),
        pytest.param('{"preferred": 1, "reason": "r"}', ("1", "r"), id="int_1"),
        pytest.param('{"preferred": 2, "reason": "r"}', ("2", "r"), id="int_2"),
        pytest.param('```json\n{"preferred": 2, "reason": "r"}\n```', ("2", "r"), id="int_in_a_code_fence"),
        pytest.param('My verdict: {"preferred": "1", "reason": "r"} Done.', ("1", "r"), id="string_inside_prose"),
        pytest.param('{"preferred": "tie"}', ("tie", ""), id="no_reason_given"),
    ],
)
def test_parse_preference_accepts_strings_and_ints(text: str, expected: tuple[str, str]) -> None:
    assert parse_preference(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param(b'{"preferred": "1"}', id="bytes"),
        pytest.param("no braces at all", id="no_json"),
        pytest.param('{"preferred": "1"', id="unterminated_object"),
        pytest.param('["1"]', id="not_an_object"),
        pytest.param('{"preferred": 3}', id="int_out_of_range"),
        pytest.param('{"preferred": 0}', id="int_zero"),
        pytest.param('{"preferred": "3"}', id="string_out_of_range"),
        pytest.param('{"preferred": true}', id="boolean"),
        pytest.param('{"preferred": null}', id="null"),
        pytest.param('{"reason": "no preference given"}', id="no_preference"),
    ],
)
def test_parse_preference_unreadable_input_is_invalid(text: object) -> None:
    assert parse_preference(text)[0] == "invalid"


# ------------------------------------------------------------------ bounds


_PROVIDER_JSON = '{"preferred": "1", "reason": "x\\ud800\\u0000' + "y" * 1997 + '"}'  # a 2,000-character reason
_ERROR_TEXT = "x\ud800\x00" + "y" * 1997  # 2,000 characters, with a lone surrogate and a NUL


@pytest.mark.parametrize(
    ("respond", "prefix"),
    [
        pytest.param(lambda request: _response(request, _PROVIDER_JSON), "x?y", id="provider_json_reason"),
        pytest.param(
            lambda request: _response(request, "", answered_tier=None, answered_model=None, error=_ERROR_TEXT),
            "llm_error: x?y",
            id="llm_error_text",
        ),
    ],
)
async def test_reason_is_bounded(respond: Callable[[LLMRequest], LLMResponse], prefix: str) -> None:
    verdict = await _compare(_FakeLLM(lambda request, call: respond(request)))

    for judgement in verdict.judgements:
        reason = judgement.reason
        assert len(reason) == 500
        assert "\x00" not in reason
        assert reason.startswith(prefix)  # the surrogate became "?"
        assert reason.encode("utf-8")  # strict UTF-8: raises on a lone surrogate
        assert json.dumps(judgement_to_json(judgement), ensure_ascii=False).encode("utf-8")  # the record can persist


async def test_situation_and_candidates_are_bounded() -> None:
    hostile = "x\x00\ud800" + "u" * 10_000
    situation = render_situation(_episode(user_input=hostile))
    assert len(situation) == 2000
    assert "\x00" not in situation
    assert situation.encode("utf-8")  # strict UTF-8: the lone surrogate was replaced

    loop: list[Any] = []
    loop.append(loop)
    unrenderable = {"a_key_json_refuses": [{("a", "b"): 1}], "a_circular_outcome": [{"outcome": loop}]}
    for label, outcomes in unrenderable.items():
        rendered = render_situation(_episode(user_input="Rotate the key", outcomes=outcomes))
        assert "<unrenderable>" in rendered, label
        assert "Rotate the key" in rendered, label  # the request is still shown

    giant = Procedure(steps=[ProcedureStep(step_number=1, action="a" * 20_000)])
    assert len(render_candidate(giant)) == 4000

    llm = _tie_judge()
    await _compare(llm, champion=giant, challenger=giant, episode=_episode(user_input=hostile))
    assert len(llm.requests) == 2
    for request in llm.requests:
        assert len(_situation_of(request.prompt)) == 2000
        assert [len(text) for text in _candidates(request.prompt)] == [4000, 4000]


# ------------------------------------------------------------------ who judged


@pytest.mark.parametrize(
    ("cognitive", "tier"),
    [
        pytest.param(CognitiveConfig(), "standard", id="no_verifier_configured"),
        pytest.param(CognitiveConfig(llm_model_verifier="gpt-5.1"), "verifier", id="verifier_configured"),
    ],
)
async def test_judge_requests_the_policy_tier_never_deep(cognitive: CognitiveConfig, tier: str) -> None:
    policy = VerifierJudgePolicy.from_cognitive(cognitive)
    llm = _tie_judge()
    judge = ProcedureJudge(llm, policy, rng=random.Random(5))

    await judge.compare(champion=_plain(), challenger=_marked(), episode=_episode())

    assert judge.request_tier == tier
    assert len(llm.requests) == 2
    for request in llm.requests:
        assert request.tier == tier
        assert request.tier != "deep"
        assert request.tier != PROCEDURE_REWRITE_TIER  # not the tier the rewrite ran on
        assert request.max_tokens == 512
        assert request.temperature == 0.0


_ANSWERS = {
    # name: (what the response says answered it, the judge record the policy must make of it)
    "verifier_answered": (_Answered("verifier", "gpt-5.1"), ("verifier", "gpt-5.1", "independent", False)),
    "another_independent_family": (
        _Answered("verifier", "gemini-2.5-pro"), ("verifier", "gemini-2.5-pro", "independent", False),
    ),
    "verifier_tier_named_a_crew_model": (
        _Answered("verifier", "claude-opus-4-6"), ("verifier", "claude-opus-4-6", "same_model", False),
    ),
    "fell_back_to_a_crew_model": (
        _Answered("standard", "claude-sonnet-4-6"), ("verifier", "claude-sonnet-4-6", "same_model", True),
    ),
    "fell_back_but_names_the_independent_model": (
        _Answered("standard", "gpt-5.1"), ("verifier", "gpt-5.1", "unknown", True),
    ),
    "nothing_reported": (_Answered(None, None), ("verifier", "", "unknown", True)),
}
_ANSWER_NAMES = list(_ANSWERS)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # Each row is paired with the next, so the two calls of one situation never share an answer.
        pytest.param(name, _ANSWER_NAMES[(index + 1) % len(_ANSWER_NAMES)], id=name)
        for index, name in enumerate(_ANSWER_NAMES)
    ],
)
async def test_provenance_is_recorded_from_the_answered_fields(first: str, second: str) -> None:
    (first_answered, first_record), (second_answered, second_record) = _ANSWERS[first], _ANSWERS[second]
    llm = _marker_judge(first_answered, second_answered)

    verdict = await _compare(llm, policy=_independent_policy(), champion=_plain(), challenger=_marked())

    recorded = [(j.judge.tier, j.judge.model, j.judge.independence, j.judge.fallback) for j in verdict.judgements]
    assert recorded == [first_record, second_record]  # each call keeps its own answered tier and model
    # Both calls asked for the verifier tier (the recorded ``tier``), so an answer from "standard" is a fallback.
    assert all(request.tier == "verifier" for request in llm.requests)


_VERIFIER_ANSWERED = _Answered("verifier", "gpt-5.1")
_FELL_BACK_TO_CREW = _Answered("standard", "claude-sonnet-4-6")


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(_VERIFIER_ANSWERED, _FELL_BACK_TO_CREW, id="second_order_fell_back"),
        pytest.param(_FELL_BACK_TO_CREW, _VERIFIER_ANSWERED, id="first_order_fell_back"),
        pytest.param(_FELL_BACK_TO_CREW, _FELL_BACK_TO_CREW, id="both_orders_fell_back"),
        pytest.param(_VERIFIER_ANSWERED, _Answered("standard", "gpt-5.1"), id="fallback_names_the_independent_model"),
        pytest.param(_VERIFIER_ANSWERED, _Answered(None, None), id="answered_tier_not_reported"),
    ],
)
async def test_fallback_judgement_is_recorded_not_counted_when_an_independent_judge_is_configured(
    first: _Answered, second: _Answered,
) -> None:
    judge = ProcedureJudge(_marker_judge(first, second), _independent_policy(), rng=random.Random(3))

    verdict = await judge.compare(champion=_plain(), challenger=_marked(), episode=_episode())

    assert judge.requires_independent is True
    assert verdict.outcome == "challenger"  # both orders agreed on the content: a real win...
    assert verdict.counted is False  # ...that a crew tier's answer must not turn into a promotion
    assert [j.winner for j in verdict.judgements] == ["challenger", "challenger"]  # both judgements are recorded
    assert [j.judge.fallback for j in verdict.judgements] == [first.tier != "verifier", second.tier != "verifier"]


async def test_independently_answered_situation_counts_when_an_independent_judge_is_configured() -> None:
    judge = ProcedureJudge(
        _marker_judge(_VERIFIER_ANSWERED, _VERIFIER_ANSWERED), _independent_policy(), rng=random.Random(3),
    )

    verdict = await judge.compare(champion=_plain(), challenger=_marked(), episode=_episode())

    assert judge.requires_independent is True
    assert (verdict.outcome, verdict.counted) == ("challenger", True)
    assert [j.judge.independence for j in verdict.judgements] == ["independent", "independent"]


@pytest.mark.parametrize(
    ("policy", "answered", "recorded"),
    [
        pytest.param(
            VerifierJudgePolicy("standard", "claude-sonnet-4-6", _CREW),
            _Answered("standard", "claude-sonnet-4-6"), "same_model", id="no_verifier_configured",
        ),
        pytest.param(
            VerifierJudgePolicy("verifier", "claude-opus-4-6", _CREW),
            _Answered("verifier", "claude-opus-4-6"), "same_model", id="verifier_is_a_crew_model",
        ),
        pytest.param(
            VerifierJudgePolicy("verifier", "claude-opus-4-6", ("claude-sonnet-4-6",)),
            _Answered("verifier", "claude-opus-4-6"), "same_family", id="verifier_of_a_crew_family",
        ),
        pytest.param(
            VerifierJudgePolicy("verifier", "mystery-7b", _CREW),
            _Answered("verifier", "mystery-7b"), "unknown", id="verifier_family_unknown",
        ),
    ],
)
async def test_same_model_judge_counts_when_no_independent_judge_is_configured(
    policy: VerifierJudgePolicy, answered: _Answered, recorded: str,
) -> None:
    judge = ProcedureJudge(_marker_judge(answered, answered), policy, rng=random.Random(3))

    verdict = await judge.compare(champion=_plain(), challenger=_marked(), episode=_episode())

    assert judge.requires_independent is False
    assert (verdict.outcome, verdict.counted) == ("challenger", True)  # every valid judgement counts...
    assert [j.judge.independence for j in verdict.judgements] == [recorded, recorded]  # ...and says how independent


# R3 (R3-1). The model that answered a challenger's rewrite is one more model each judgement is compared with: it can
# lower a recorded label, while which judgements count stays the configured policy's decision.


@pytest.mark.parametrize(
    ("optimizer_model", "label"),
    [
        pytest.param("gpt-5.1", "same_model", id="the_optimizer_is_the_judges_own_model"),
        # tests/test_ad1327_verifier_independence.py names no second model of gpt-5.1's family (openai). "gpt-4o" is
        # one that ``model_family`` knows by its "gpt" marker; the premise below checks it is not the judge's model.
        pytest.param("gpt-4o", "same_family", id="the_optimizer_is_of_the_judges_family"),
        pytest.param("mystery-7b", "unknown", id="the_optimizer_is_of_no_known_family"),
    ],
)
async def test_judgement_by_the_optimizers_model_is_not_independent(optimizer_model: str, label: str) -> None:
    # The reviewer's case: the verifier is gpt-5.1 over a Claude crew, the rewrite was answered by gpt-5.1, and the
    # judge answers as gpt-5.1. A judge told which model wrote the challenger must record its answer as that model's
    # and, an independent judge being required, not count it. The comparison is still made.
    assert classify_independence("gpt-5.1", (optimizer_model,)) == label  # premise: the row is what its id says
    unaware = ProcedureJudge(
        _marker_judge(_VERIFIER_ANSWERED, _VERIFIER_ANSWERED), _independent_policy(), rng=random.Random(3),
    )
    before = await unaware.compare(champion=_plain(), challenger=_marked(), episode=_episode())
    # Premise: a judge not told the optimizer's model records both judgements independent and counts them.
    assert [j.judge.independence for j in before.judgements] == ["independent", "independent"]
    assert (before.outcome, before.counted) == ("challenger", True)

    llm = _marker_judge(_VERIFIER_ANSWERED, _VERIFIER_ANSWERED)
    judge = ProcedureJudge(llm, _independent_policy(), rng=random.Random(3))
    verdict = await judge.compare(
        champion=_plain(), challenger=_marked(), episode=_episode(), optimizer_model=optimizer_model,
    )

    assert judge.requires_independent is True  # still the configured policy's decision, not recomputed
    assert [j.judge.independence for j in verdict.judgements] == [label, label]
    assert verdict.counted is False  # recorded, not counted
    assert verdict.outcome == "challenger"  # the comparison was still made: both orders preferred the marked candidate
    assert [j.winner for j in verdict.judgements] == ["challenger", "challenger"]
    # Only the label moved: tier, model and fallback are the answered ones, and the tier asked for is unchanged.
    assert [(j.judge.tier, j.judge.model, j.judge.fallback) for j in verdict.judgements] == [
        ("verifier", "gpt-5.1", False), ("verifier", "gpt-5.1", False),
    ]
    assert [request.tier for request in llm.requests] == ["verifier", "verifier"]


@pytest.mark.parametrize(
    ("make_policy", "answered"),
    [
        pytest.param(_independent_policy, _VERIFIER_ANSWERED, id="independent_policy"),
        # The standard policy configures no verifier, so it counts every valid judgement. The model that answers is
        # outside the crew, which is what lets a recorded label show a difference when the optimizer's model is real.
        pytest.param(_standard_policy, _Answered("standard", "gpt-5.1"), id="same_model_policy"),
    ],
)
@pytest.mark.parametrize(
    "not_reported",
    [
        pytest.param("", id="empty"),
        pytest.param(None, id="none"),
        pytest.param(7, id="int"),
        pytest.param(b"gpt-5.1", id="bytes"),
        pytest.param(["gpt-5.1"], id="list"),
    ],
)
async def test_empty_optimizer_model_changes_nothing(
    make_policy: Callable[[], VerifierJudgePolicy], answered: _Answered, not_reported: Any,
) -> None:
    # R3 (R3-1). A challenger whose rewrite reported no model, or a value that is not text, is judged exactly as it
    # was before the optimizer's model was an input, under either kind of policy.
    async def verdict(seed: int, **kwargs: Any) -> SituationVerdict:
        judge = ProcedureJudge(_marker_judge(answered, answered), make_policy(), rng=random.Random(seed))
        return await judge.compare(champion=_plain(), challenger=_marked(), episode=_episode(), **kwargs)

    baseline = await verdict(0)
    assert (baseline.outcome, baseline.counted) == ("challenger", True)  # premise: a real, counted verdict is compared
    # Premise: this setup shows a difference when the optimizer's model is real (the model that answered).
    assert await verdict(0, optimizer_model=answered.model) != baseline

    for seed in range(5):
        assert await verdict(seed, optimizer_model=not_reported) == await verdict(seed), f"seed {seed}"


@pytest.mark.parametrize(
    ("make_policy", "answered", "independent_required", "optimizer_model", "label_before", "label_after"),
    [
        # No verifier is configured: every valid judgement counts, so the optimizer's model (here the model that
        # answered, which is outside the crew) changes the recorded label and nothing else.
        pytest.param(
            _standard_policy, _Answered("standard", "gpt-5.1"), False, "gpt-5.1", "independent", "same_model",
            id="no_verifier_every_valid_judgement_still_counts",
        ),
        # An independent verifier and an optimizer that is a crew model: nothing new to compare gpt-5.1 with.
        pytest.param(
            _independent_policy, _VERIFIER_ANSWERED, True, "claude-opus-4-6", "independent", "independent",
            id="a_crew_model_optimizer_leaves_an_independent_judge_independent",
        ),
    ],
)
async def test_optimizer_model_never_relaxes_the_counting_rule(
    make_policy: Callable[[], VerifierJudgePolicy], answered: _Answered, independent_required: bool,
    optimizer_model: str, label_before: str, label_after: str,
) -> None:
    # R3 (R3-1). The optimizer's model can lower a recorded label; it does not decide which judgements count. That
    # stays the configured policy's: no verifier counts every valid judgement, an independent verifier counts only
    # the independent ones.
    assert classify_independence("gpt-5.1", (optimizer_model,)) == label_after  # premise: what it makes of gpt-5.1
    unaware = ProcedureJudge(_marker_judge(answered, answered), make_policy(), rng=random.Random(3))
    assert unaware.requires_independent is independent_required  # premise: the configured policy's rule
    before = await unaware.compare(champion=_plain(), challenger=_marked(), episode=_episode())
    assert [j.judge.independence for j in before.judgements] == [label_before, label_before]  # premise
    assert (before.outcome, before.counted) == ("challenger", True)

    aware = ProcedureJudge(_marker_judge(answered, answered), make_policy(), rng=random.Random(3))
    after = await aware.compare(
        champion=_plain(), challenger=_marked(), episode=_episode(), optimizer_model=optimizer_model,
    )

    assert aware.requires_independent is independent_required  # the optimizer's model never changes what is required
    assert [j.judge.independence for j in after.judgements] == [label_after, label_after]
    assert (after.outcome, after.counted) == ("challenger", True)  # and every valid judgement still counts


# R4 (R4-3). The optimizer's model joins the basis each answer is classified against, but it never raises a recorded
# label. With an empty crew basis (the configuration accepts ("", "", "")) the configured policy has nothing to compare
# the judge with and records ``unknown``; the optimizer's model alone would give the classifier a basis, and the answer
# would be recorded ``independent``, a label no configured model supports. Which judgements count stays the
# configured policy's decision.


@pytest.mark.parametrize(
    ("crew", "optimizer_model", "label_without", "label_augmented", "label", "required", "counted"),
    [
        # The reviewer's case: an empty basis, and an optimizer of another family than the judge's.
        pytest.param(
            ("", "", ""), "claude-opus-4-6", "unknown", "independent", "unknown", False, True, id="empty_basis",
        ),
        # The R3-1 case: the optimizer is the judge's own model, so the label is lowered and the answer not counted.
        pytest.param(_CREW, "gpt-5.1", "independent", "same_model", "same_model", True, False, id="lowers"),
        # An optimizer that is a crew model gives an independent judge nothing new to be compared with.
        pytest.param(
            _CREW, "claude-opus-4-6", "independent", "independent", "independent", True, True, id="unchanged",
        ),
        # A weak augmented label is kept: it is not replaced by the baseline's ``unknown``.
        pytest.param(
            ("", "", ""), "gpt-5.1", "unknown", "same_model", "same_model", False, True,
            id="empty_basis_judge_is_optimizer",
        ),
    ],
)
async def test_optimizer_model_never_raises_a_label(
    crew: tuple[str, str, str], optimizer_model: str, label_without: str, label_augmented: str, label: str,
    required: bool, counted: bool,
) -> None:
    policy = VerifierJudgePolicy("verifier", "gpt-5.1", crew)
    # Premises: the two classifications the judge makes of one answer, over the configured basis and over the basis
    # that also holds the optimizer's model. In the empty_basis case the second is independent where the first is
    # unknown: the augmented basis would raise the label.
    assert classify_independence("gpt-5.1", crew) == label_without
    assert classify_independence("gpt-5.1", (*crew, optimizer_model)) == label_augmented
    unaware = ProcedureJudge(_marker_judge(_VERIFIER_ANSWERED, _VERIFIER_ANSWERED), policy, rng=random.Random(3))
    without = await unaware.compare(champion=_plain(), challenger=_marked(), episode=_episode())
    # Premise: a judge not told the optimizer's model records the configured label; this is the verdict compared with.
    assert unaware.requires_independent is required
    assert [j.judge.independence for j in without.judgements] == [label_without, label_without]
    assert (without.outcome, without.counted) == ("challenger", True)

    judge = ProcedureJudge(_marker_judge(_VERIFIER_ANSWERED, _VERIFIER_ANSWERED), policy, rng=random.Random(3))
    verdict = await judge.compare(
        champion=_plain(), challenger=_marked(), episode=_episode(), optimizer_model=optimizer_model,
    )

    assert judge.requires_independent is required  # still the configured policy's decision, never recomputed
    assert [j.judge.independence for j in verdict.judgements] == [label, label]
    assert (verdict.outcome, verdict.counted) == ("challenger", counted)  # the comparison is still made

    def unlabelled(situation: SituationVerdict) -> list[tuple[Any, ...]]:
        return [
            (j.shown_first, j.winner, j.reason, j.judge.model_dump(exclude={"independence"}))
            for j in situation.judgements
        ]

    # Only the label can differ from the call without the optimizer's model (the same order, winners, tier, model
    # and fallback), so the two verdicts are equal exactly when the label did not move.
    assert (verdict.first_shown, unlabelled(verdict)) == (without.first_shown, unlabelled(without))
    assert (verdict == without) is (label == label_without)
