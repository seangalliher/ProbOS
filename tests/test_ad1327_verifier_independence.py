"""AD-1327 (#1511): the crew verifier's judge is classified, labelled and persisted.

Milestone 2 covers the classification contract (tests 18-23), the verifier's request
tier and judge record (24-28) and the persisted judge record across every boundary a
verdict crosses (29-35). Every producer -> consumer chain is crossed end to end: the
real ``OpenAICompatibleClient`` over an in-process transport feeds the real
``SubtaskVerifier``, whose verdict is written to the durable records and read back.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import threading
import typing
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError
from rich.console import Console

import probos.__main__ as main_mod
import probos.cognitive.crew_verifier as crew_verifier_mod
from probos import provider_setup as ps
from probos import work_item_steps
from probos.cognitive import crew_finalizer, crew_trust
from probos.doctor import checks as _doctor_checks  # noqa: F401  (registers every check)
from probos.doctor.checks import verifier_check
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.doctor.registry import iter_checks
from probos.cognitive.verifier_independence import VERIFIER_REMEDIATION, verifier_independence_report

from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_finalizer import CrewSessionFinalizer, _VerdictRecord
from probos.cognitive.crew_orchestrator import CrewOrchestrator
from probos.cognitive.crew_session import CrewSessionService
from probos.cognitive.crew_synth import CrewSynthesizer
from probos.cognitive.crew_verdict import JudgeProvenance, judge_to_json, parse_judge
from probos.cognitive.crew_verifier import (
    ConvergenceOutcome,
    SessionVerificationPass,
    SubtaskVerifier,
    VerificationVerdict,
)
from probos.cognitive.llm_client import _LLM_TIERS, TEXT_TIERS, VERIFIER_TIER, OpenAICompatibleClient
from probos.cognitive.model_registry import model_family, normalise_model_id
from probos.cognitive.verifier_independence import VerifierJudgePolicy, classify_independence
from probos.config import CognitiveConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.types import LLMRequest, LLMResponse
from tests.test_ad860_crew_verifier import _FakeStore, _result
from tests.test_ad1126_verified_finalization import (
    _Agent,
    _Registry,
    _ScriptedLLM,
    _StaticAgenticExecutor,
    _TrustRecorder,
    _make_finalizer,
    _make_synthesizer,
    _registry_for,
    _runtime,
    _text,
)
from tests.test_ad1130_outcome_only_room_trust import _round, _verification
from tests.test_ad1192_owned_steps_finalization import (
    _Delegator,
    _Episodes,
    _FakeContent,
    _Resolver,
    _SynthLLM,
    _Verifier,
    _Worker,
    _executor,
    store,  # noqa: F401  (the owned-steps WorkItemStore fixture)
)
from tests.test_ad1137_doctor import _Connectivity
from tests.test_ad1244_verdict_criteria import (
    _PauseBeforeArtifact,
    _canonical,
    _derive,
    _executed_session,
    _historical_verdict,
    stores,  # noqa: F401  (the real isolated stores fixture)
)
from tests.test_ad1125_room_bound_execution import stores as _execution_stores
from tests.test_ad1327_verifier_tier import _HOSTS, _NAMES, _cognitive, _FakeEndpoints

_CLAUDE_CREW = ("claude-sonnet-4-6", "claude-sonnet-4-6", "claude-opus-4-6")
_ACCEPT = json.dumps({"accepted": True, "confidence": 0.8, "critique": "Checked."})
_EXPECTED = "Supply repository evidence."
_JUDGE = JudgeProvenance(tier="verifier", model="gpt-5.1", independence="independent", fallback=False)
_VALID_JUDGE: dict[str, Any] = {
    "tier": "verifier", "model": "gpt-5.1", "independence": "independent", "fallback": False,
}

# Every invalid persisted judge record, shared by tests 20, 31 and 33. The lone surrogate (a JSON ``\ud800``
# escape decoded; review round 2) is a detector in 20 and 31 (the bound in ``is_persistable_judge_model``);
# in 33 it passes with or without the bound, since ``crew_trust._exact_json_bytes`` encodes strictly.
_INVALID: list[tuple[str, Any]] = [
    ("none", None),
    ("list", [dict(_VALID_JUDGE)]),
    ("fallback-int", {**_VALID_JUDGE, "fallback": 1}),
    ("unknown-independence", {**_VALID_JUDGE, "independence": "very_independent"}),
    ("fallback-independent", {**_VALID_JUDGE, "fallback": True}),
    ("empty-model-known-outcome", {**_VALID_JUDGE, "model": "", "independence": "same_model"}),
    ("nul-in-model", {**_VALID_JUDGE, "model": "gpt\x00-5.1"}),
    ("long-model", {**_VALID_JUDGE, "model": "m" * 257}),
    ("model-not-text", {**_VALID_JUDGE, "model": 7}),
    ("lone-surrogate-model", {**_VALID_JUDGE, "model": "gpt-\ud800-5"}),
    ("extra-key", {**_VALID_JUDGE, "extra": "x"}),
]
_INVALID_JUDGES = [pytest.param(value, id=name) for name, value in _INVALID]


def _dedicated_policy() -> VerifierJudgePolicy:
    return VerifierJudgePolicy.from_cognitive(CognitiveConfig(llm_model_verifier="gpt-5.1"))


class _FakeJudgeLLM:
    """Answers each ``complete`` with an ``LLMResponse`` naming ``model``; records every request.

    Carries what the real client carries (AD-1327 D9/D10): ``answered_model`` is the model named and
    ``answered_tier`` is the tier the request asked for. ``answered_model`` (review round 2) names a
    different model than the one sent, so a reply can claim an id the request never asked for.
    ``provenance=False`` returns the plain
    response instead (the absent-provenance case: a double that does not say who answered).
    """

    def __init__(
        self, model: str, contents: list[str] | None = None, *, error: BaseException | None = None,
        provenance: bool = True, answered_model: str | None = None,
    ) -> None:
        self.model = model
        self.contents = list(contents if contents is not None else [_ACCEPT])
        self.error = error
        self.provenance = provenance
        self.answered_model = answered_model
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **_kw: Any) -> LLMResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.contents, "the fake judge was asked more often than the test scripted"
        content = self.contents.pop(0)
        if not self.provenance:
            return LLMResponse(content=content, model=self.model, tokens_used=3)
        return LLMResponse(
            content=content, model=self.model, tokens_used=3,
            answered_model=self.model if self.answered_model is None else self.answered_model,
            answered_tier=request.tier,
        )


def _verifier(
    llm: Any, policy: VerifierJudgePolicy | None, *, independent: bool = True,
) -> SubtaskVerifier:
    registry = _Registry([_Agent("producer"), *([_Agent("judge")] if independent else [])])
    return SubtaskVerifier(
        llm_client=llm,
        work_item_store=_FakeStore({"expected_output": _EXPECTED}),
        agent_registry=registry,
        trust_network=TrustNetwork(),
        agentic_executor=_StaticAgenticExecutor(),
        runtime=SimpleNamespace(),
        judge_policy=policy,
    )


async def _run(flow: str, verifier: SubtaskVerifier) -> VerificationVerdict | SessionVerificationPass:
    if flow == "legacy":
        return await verifier.verify(_result())
    return await verifier.verify_for_session(
        _result(), expected_output=_EXPECTED, excluded_agent_ids=frozenset({"producer"}),
    )


class _VerdictEndpoints(_FakeEndpoints):
    """``_FakeEndpoints`` whose 200 body carries a valid verdict, so the real verifier can parse it."""

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((request.url.host, body["model"]))
        self.bodies.append(body)
        if request.url.host in self.down:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": _ACCEPT}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 2, "prompt_tokens": 1},
            "model": body["model"],  # an honest provider echo (AD-1327 D9: ``answered_model``)
        })


@pytest.fixture
def verdict_endpoints(monkeypatch: pytest.MonkeyPatch) -> _VerdictEndpoints:
    monkeypatch.delenv("PROBOS_LLM_URL", raising=False)
    fake = _VerdictEndpoints()

    def build(client: OpenAICompatibleClient, tier: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=client._tier_configs[tier]["base_url"],
            transport=httpx.MockTransport(fake.handle),
        )

    monkeypatch.setattr(OpenAICompatibleClient, "_build_client", build)
    return fake


def _same_model_cognitive(**overrides: Any) -> CognitiveConfig:
    return _cognitive(
        llm_model_fast="claude-sonnet-4-6", llm_model_standard="claude-sonnet-4-6",
        llm_model_deep="claude-sonnet-4-6", **overrides,
    )


# ------------------------------------------------------------------ classification and contract

# 18
def test_model_family_and_normalisation() -> None:
    assert model_family("claude-sonnet-4-6") == "anthropic"
    assert model_family("claude-opus-4-6") == "anthropic"
    assert model_family("gpt-5.1") == "openai"
    assert model_family("ollama/qwen3:32b") == "alibaba"
    assert model_family("deepseek-r1-distill-qwen-32b") is None  # two families in one name
    assert model_family("mystery-7b") is None
    assert model_family("") is None
    assert normalise_model_id("anthropic/Claude-Sonnet-4-6") == "claude-sonnet-4-6"


# 19
@pytest.mark.parametrize(
    ("judge", "crew", "expected"),
    [
        pytest.param("anthropic/Claude-Sonnet-4-6", ("claude-sonnet-4-6",), "same_model", id="same-id-after-normalising"),
        pytest.param("claude-opus-4-6", ("claude-sonnet-4-6",), "same_family", id="same-family"),
        pytest.param("gpt-5.1", ("claude-sonnet-4-6",), "independent", id="independent"),
        pytest.param("mystery-7b", ("claude-sonnet-4-6",), "unknown", id="unknown-judge-family"),
        pytest.param("gpt-5.1", ("claude-sonnet-4-6", "mystery-7b"), "unknown", id="unknown-crew-family"),
        pytest.param("mystery-7b", ("claude-sonnet-4-6", "mystery-8b"), "unknown", id="unknown-judge-and-crew-families"),
        pytest.param("gpt-5.1", ("", "claude-sonnet-4-6"), "independent", id="empty-crew-names-are-ignored"),
        pytest.param("", ("claude-sonnet-4-6",), "unknown", id="empty-judge"),
        pytest.param("gpt-5.1", (), "unknown", id="empty-crew"),
    ],
)
def test_classify_independence_outcomes(judge: str, crew: tuple[str, ...], expected: str) -> None:
    assert classify_independence(judge, crew) == expected


# 20
@pytest.mark.parametrize("invalid", _INVALID_JUDGES)
def test_judge_provenance_validates_persisted_records(invalid: Any) -> None:
    judge = parse_judge(dict(_VALID_JUDGE))  # the valid record round-trips (and is the control for each refusal)
    assert judge == _JUDGE
    assert judge_to_json(judge) == _VALID_JUDGE
    assert parse_judge(json.loads(json.dumps(judge_to_json(judge)))) == judge
    with pytest.raises(ValueError):
        parse_judge(judge)  # a validated in-memory record is not a persisted JSON object
    with pytest.raises(ValueError):
        parse_judge(invalid)


# 21
def test_judge_provenance_tier_names_are_llm_tiers() -> None:
    names = set(typing.get_args(JudgeProvenance.model_fields["tier"].annotation))
    assert names and names <= set(_LLM_TIERS)
    assert VERIFIER_TIER in names


# 22
def test_policy_from_cognitive() -> None:
    unset = CognitiveConfig()
    policy = VerifierJudgePolicy.from_cognitive(unset)
    assert policy.request_tier == "standard" and policy.dedicated is False
    assert policy.configured_model == unset.tier_config("standard")["model"]
    assert policy.crew_models == tuple(unset.tier_config(tier)["model"] for tier in TEXT_TIERS)
    assert policy.assess() == "same_model"

    configured = VerifierJudgePolicy.from_cognitive(CognitiveConfig(llm_model_verifier="gpt-5.1"))
    assert configured.request_tier == "verifier" and configured.dedicated is True
    assert configured.configured_model == "gpt-5.1"
    assert configured.assess() == "independent"

    with pytest.raises(ValueError):
        VerifierJudgePolicy("deep", "m", ())


# 23
def test_provenance_never_raises_and_labels_fallback() -> None:
    policy = VerifierJudgePolicy("verifier", "gpt-5.1", _CLAUDE_CREW)
    # The dedicated tier answered, but the model it names is unusable: recorded as "" and unknown, not a fallback.
    for unusable in (None, 7, "", "x\x00", "a" * 257, "gpt-\ud800-5"):
        judge = policy.provenance(answered_tier="verifier", answered_model=unusable)
        assert (judge.model, judge.independence, judge.fallback) == ("", "unknown", False), repr(unusable)
    # Control: non-ASCII scalar text is a usable model id and is kept verbatim.
    scalar = policy.provenance(answered_tier="verifier", answered_model="gpt-é-5")
    assert (scalar.model, scalar.fallback) == ("gpt-é-5", False)

    answered = policy.provenance(answered_tier="verifier", answered_model="GPT-5.1")
    assert (answered.model, answered.independence, answered.fallback) == ("GPT-5.1", "independent", False)

    # The dedicated tier answered with a crew model's id: same_model, and not a fallback (the tier decides, not the id).
    same = policy.provenance(answered_tier="verifier", answered_model="claude-sonnet-4-6")
    assert (same.independence, same.fallback) == ("same_model", False)

    fell_back = policy.provenance(answered_tier="standard", answered_model="claude-sonnet-4-6")
    assert (fell_back.independence, fell_back.fallback) == ("same_model", True)

    # The model a fallback answered with is independent of the crew on its own; the label must still not say so.
    assert classify_independence("gemini-2.5-pro", _CLAUDE_CREW) == "independent"  # premise
    other = policy.provenance(answered_tier="standard", answered_model="gemini-2.5-pro")
    assert (other.independence, other.fallback) == ("unknown", True)

    # Provenance absent (None) or not a string: a fallback, never independent, whatever model is named.
    assert classify_independence("gpt-5.1", _CLAUDE_CREW) == "independent"  # premise
    for absent in (None, 7):
        judge = policy.provenance(answered_tier=absent, answered_model="gpt-5.1")
        assert (judge.model, judge.independence, judge.fallback) == ("gpt-5.1", "unknown", True), repr(absent)

    # No verifier model is configured: the standard tier itself answering with another model id is not a fallback.
    unset = VerifierJudgePolicy("standard", "claude-sonnet-4-6", _CLAUDE_CREW)
    chained = unset.provenance(answered_tier="standard", answered_model="claude-opus-4-6")
    assert (chained.tier, chained.model, chained.independence, chained.fallback) == (
        "standard", "claude-opus-4-6", "same_model", False,
    )
    # Only the requested tier counts as answered: the fast tier answering for the standard policy (the fast/deep chain) is a fallback.
    chain_fell = unset.provenance(answered_tier="fast", answered_model="claude-sonnet-4-6")
    assert chain_fell.fallback is True


# ------------------------------------------------------------------ verifier

# 24
@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_unset_verifier_requests_match_the_pre_ad1327_golden(flow: str) -> None:
    unset_policy = VerifierJudgePolicy.from_cognitive(CognitiveConfig())
    assert unset_policy.request_tier == "standard"  # premise: the policy under test is the unset one
    requests: list[dict[str, Any]] = []
    for policy in (None, unset_policy):
        llm = _FakeJudgeLLM("claude-sonnet-4-6")
        verdict = await _run(flow, _verifier(llm, policy))
        assert len(llm.requests) == 1, "the judge call did not execute"
        # A swallowed judge error would also leave no judge: an accepted verdict shows the reply was judged, not degraded.
        assert verdict.accepted is True
        assert (verdict.judge is None) == (policy is None)
        requests.append({k: v for k, v in dataclasses.asdict(llm.requests[0]).items() if k != "id"})
    assert requests[0]["prompt"] == requests[1]["prompt"]
    assert "the produced output" in requests[0]["prompt"] and _EXPECTED in requests[0]["prompt"]
    golden = {
        "prompt": requests[0]["prompt"],
        "system_prompt": SubtaskVerifier._JUDGE_SYSTEM_PROMPT,
        "tier": "standard",
        "temperature": 0.0,
        "top_p": None,
        "max_tokens": 2048,
        "tools": None,
        "tool_choice": "auto",
        "messages": None,
        "agent_id": None,
        "work_item_id": None,
        "min_tier": None,
        "tier_choice_reason": None,
        "exact_tier": False,
    }
    assert requests[0] == golden
    assert requests[1] == golden


# 25
@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_configured_verifier_judges_through_config_client_and_verifier(
    flow: str, verdict_endpoints: _VerdictEndpoints,
) -> None:
    cfg = _same_model_cognitive(
        llm_model_verifier="gpt-5.1", llm_base_url_verifier="https://judge.invalid/v1",
    )
    client = OpenAICompatibleClient(config=cfg)
    try:
        verdict = await _run(flow, _verifier(client, VerifierJudgePolicy.from_cognitive(cfg)))
    finally:
        await client.close()
    assert verdict.accepted is True
    assert verdict_endpoints.calls == [("judge.invalid", "gpt-5.1")]
    assert verdict.judge == JudgeProvenance(
        tier="verifier", model="gpt-5.1", independence="independent", fallback=False,
    )


# 26
@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_verifier_endpoint_down_falls_back_to_standard_and_labels_the_verdict(
    flow: str, verdict_endpoints: _VerdictEndpoints,
) -> None:
    verdict_endpoints.down = {"judge.invalid"}
    cfg = _same_model_cognitive(
        llm_model_verifier="gpt-5.1", llm_base_url_verifier="https://judge.invalid/v1",
    )
    client = OpenAICompatibleClient(config=cfg)
    try:
        verdict = await _run(flow, _verifier(client, VerifierJudgePolicy.from_cognitive(cfg)))
    finally:
        await client.close()
    assert "judge.invalid" in verdict_endpoints.hosts, "the configured judge endpoint was not attempted"
    assert verdict_endpoints.calls[-1] == (_HOSTS["standard"], "claude-sonnet-4-6")
    assert _HOSTS["fast"] not in verdict_endpoints.hosts and _HOSTS["deep"] not in verdict_endpoints.hosts
    assert verdict.accepted is True
    assert verdict.judge is not None
    assert verdict.judge.fallback is True
    assert verdict.judge.independence == "same_model"
    assert (verdict.judge.tier, verdict.judge.model) == ("verifier", "claude-sonnet-4-6")


# 27
@pytest.mark.parametrize(
    ("flow", "content", "defect"),
    [
        pytest.param("legacy", _ACCEPT, False, id="legacy-accepted"),
        pytest.param("legacy", "not-json", True, id="legacy-unparseable"),
        pytest.param("session", _ACCEPT, False, id="session-accepted"),
        pytest.param("session", "not-json", True, id="session-malformed"),
    ],
)
async def test_wired_verifier_records_a_judge_on_every_answered_verdict(
    flow: str, content: str, defect: bool,
) -> None:
    llm = _FakeJudgeLLM("gpt-5.1", [content])
    verdict = await _run(flow, _verifier(llm, _dedicated_policy()))
    assert len(llm.requests) == 1 and llm.requests[0].tier == "verifier"
    if flow == "legacy":
        assert isinstance(verdict, VerificationVerdict)
        assert verdict.verification_defect is defect
    else:
        assert isinstance(verdict, SessionVerificationPass)
        assert (verdict.status == "malformed") is defect
    assert verdict.judge == _JUDGE


# 27 (absent provenance)
@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_response_without_provenance_is_a_fallback_and_never_independent(flow: str) -> None:
    # Negative control: the same double with provenance is the independent judge (test 27).
    carried = await _run(flow, _verifier(_FakeJudgeLLM("gpt-5.1"), _dedicated_policy()))
    assert carried.judge == _JUDGE

    llm = _FakeJudgeLLM("gpt-5.1", provenance=False)
    verdict = await _run(flow, _verifier(llm, _dedicated_policy()))

    assert len(llm.requests) == 1 and llm.requests[0].tier == "verifier"
    assert verdict.accepted is True
    assert verdict.judge == JudgeProvenance(tier="verifier", model="", independence="unknown", fallback=True)


# 28
@pytest.mark.parametrize("flow", ["legacy", "session"])
@pytest.mark.parametrize("case", ["no_independent_verifier", "llm_raises"])
async def test_unanswered_verdicts_carry_no_judge(flow: str, case: str) -> None:
    # Negative control: the same wiring does record a judge when a judge answers.
    answered = await _run(flow, _verifier(_FakeJudgeLLM("gpt-5.1"), _dedicated_policy()))
    assert answered.judge == _JUDGE

    if case == "no_independent_verifier":
        llm = _FakeJudgeLLM("gpt-5.1")
        verdict = await _run(flow, _verifier(llm, _dedicated_policy(), independent=False))
        assert llm.requests == [], "no judge may be asked when there is no independent verifier"
    else:
        llm = _FakeJudgeLLM("gpt-5.1", error=RuntimeError("scripted provider outage"))
        verdict = await _run(flow, _verifier(llm, _dedicated_policy()))
        assert len(llm.requests) == 1, "the judge call did not execute"
    assert verdict.accepted is False
    assert verdict.judge is None


# ------------------------------------------------------------------ persistence

# 29
def test_historical_verdict_without_judge_keeps_its_bytes() -> None:
    original = _historical_verdict(accepted=True, critique="Checked.")
    original_bytes = _canonical(original)
    verdict = _VerdictRecord.model_validate(json.loads(original_bytes)).to_verdict()
    assert verdict.judge is None
    document = CrewSessionFinalizer._verdict_document(verdict)
    assert "judge" not in document
    restored_bytes = _canonical(document)
    assert restored_bytes == original_bytes
    assert hashlib.sha256(restored_bytes).digest() == hashlib.sha256(original_bytes).digest()


# 30
def test_judge_round_trips_through_the_verdict_record() -> None:
    verdict = SessionVerificationPass(
        status="accepted", accepted=True, confidence=0.8, critique="Checked.",
        verifier_agent_id="judge", tokens_used=7, failure_code=None, judge=_JUDGE,
    )
    document = CrewSessionFinalizer._verdict_document(verdict)
    assert document["judge"] == judge_to_json(_JUDGE)
    restored = _VerdictRecord.model_validate(json.loads(_canonical(document))).to_verdict()
    assert restored.judge == _JUDGE
    assert restored == verdict
    assert _canonical(CrewSessionFinalizer._verdict_document(restored)) == _canonical(document)


# 31
@pytest.mark.parametrize("invalid", _INVALID_JUDGES)
def test_persisted_judge_is_validated_not_trusted(invalid: Any) -> None:
    valid = _VerdictRecord.model_validate({**_historical_verdict(), "judge": dict(_VALID_JUDGE)})
    assert valid.judge == _JUDGE  # negative control: a valid judge is accepted
    with pytest.raises(ValidationError):
        _VerdictRecord.model_validate({**_historical_verdict(), "judge": invalid})


# 32
async def test_session_checkpoint_restart_restores_the_judge(tmp_path: Any) -> None:
    llm = _FakeJudgeLLM("gpt-5.1", [_ACCEPT, _ACCEPT])
    async with _executed_session(tmp_path) as case:
        stores_ = case.stores
        registry = _registry_for([case.child])
        runtime = _runtime(stores_, tmp_path, case.service)
        verifier = SubtaskVerifier(
            llm_client=llm, work_item_store=stores_.work, agent_registry=registry,
            trust_network=_TrustRecorder(),
            agentic_executor=_StaticAgenticExecutor(final_text="Corrected durable evidence", trace_ref=None),
            runtime=runtime, judge_policy=_dedicated_policy(),
        )
        pause = _PauseBeforeArtifact()
        finalizer = _make_finalizer(
            stores=stores_, service=case.service, registry=registry, verifier=verifier,
            synthesizer=_make_synthesizer(llm=_ScriptedLLM([_text("Durable final report")]), stores=stores_, runtime=runtime),
            artifact_store=pause,
        )
        with pytest.raises(asyncio.CancelledError, match="durable verdict checkpoints"):
            await finalizer.finalize(case.parent.id, case.results)
        assert pause.calls == 1 and len(llm.requests) == 2
        recovery = await case.service.get_recovery(case.parent.id)
        assert recovery is not None and recovery.final_verification_ref is not None
        child = await stores_.work.get_work_item(case.child.id)
        assert child is not None
        child_ref = child.metadata["crew_verification_recovery"]["convergence_ref"]
        checkpoint_bytes = {
            ref: await stores_.attachments.read(ref) for ref in (child_ref, recovery.final_verification_ref)
        }
        final_document = json.loads(checkpoint_bytes[recovery.final_verification_ref])
        assert final_document["verdict"]["judge"] == judge_to_json(_JUDGE)
        assert child.verification["rounds"][-1]["verdict"]["judge"] == judge_to_json(_JUDGE)
        old_verification_bytes = _canonical(child.verification)
        parent_id, child_id = case.parent.id, case.child.id

    generator = _execution_stores.__wrapped__(tmp_path)
    restarted = await generator.__anext__()
    try:
        service = CrewSessionService(work_item_store=restarted.work, chat_thread_store=restarted.chat)
        restored_child = await restarted.work.get_work_item(child_id)
        assert restored_child is not None
        registry = _registry_for([restored_child])
        runtime = _runtime(restarted, tmp_path, service)
        unused_judge = _FakeJudgeLLM("gpt-5.1", [])
        unused_synth = _ScriptedLLM([])
        finalizer = _make_finalizer(
            stores=restarted, service=service, registry=registry,
            verifier=SubtaskVerifier(
                llm_client=unused_judge, work_item_store=restarted.work, agent_registry=registry,
                trust_network=_TrustRecorder(), agentic_executor=_StaticAgenticExecutor(),
                runtime=runtime, judge_policy=_dedicated_policy(),
            ),
            synthesizer=_make_synthesizer(llm=unused_synth, stores=restarted, runtime=runtime),
        )
        completed = await finalizer.resume(parent_id)
        assert completed.completed is True
        assert unused_judge.requests == [] and unused_synth.requests == []
        restored_child = await restarted.work.get_work_item(child_id)
        assert restored_child is not None
        assert _canonical(restored_child.verification) == old_verification_bytes
        for ref, blob in checkpoint_bytes.items():
            assert await restarted.attachments.read(ref) == blob
        provenance = json.loads(await restarted.attachments.read(completed.provenance_ref))
        # The published record is rebuilt from the verdict the checkpoint restored, judge included.
        assert provenance["final_verification"] == final_document["verdict"]
        assert provenance["final_verification"]["judge"] == judge_to_json(_JUDGE)
        assert provenance["children"][0]["verification"] == restored_child.verification
    finally:
        await generator.aclose()


# 33
def test_trust_evidence_rejects_an_invalid_judge_and_hashes_exact_json() -> None:
    def _evidence(judge: Any = None, *, present: bool = True) -> dict[str, Any]:
        round_record = _round(0, status="accepted")
        assert "judge" not in round_record["verdict"]  # premise: today's payload has no judge key
        if present:
            round_record["verdict"]["judge"] = judge
        return _verification(rounds=(round_record,), accepted=True)

    for name, invalid in _INVALID:
        with pytest.raises(ValueError, match="crew_trust_evidence_invalid"):
            _derive(_evidence(invalid))  # the invalid record is `name`

    def _hashes(evidence: dict[str, Any]) -> tuple[bytes, set[str]]:
        before = _canonical(evidence)
        effects = [effect for effect in _derive(evidence) if effect.role.startswith("child_")]
        assert _canonical(evidence) == before, "deriving the effects changed the evidence"
        assert len(effects) == 2
        return before, {effect.evidence_sha256 for effect in effects}

    without_bytes, without_hashes = _hashes(_evidence(present=False))
    assert without_hashes == {hashlib.sha256(without_bytes).hexdigest()}
    with_bytes, with_hashes = _hashes(_evidence(dict(_VALID_JUDGE)))  # a valid judge is accepted
    assert with_hashes == {hashlib.sha256(with_bytes).hexdigest()}
    assert with_bytes != without_bytes and with_hashes != without_hashes


# 34
async def test_synth_provenance_and_episodes_carry_the_judge(
    stores: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,  # noqa: F811
) -> None:
    from probos.cognitive.episodic import EpisodicMemory
    from probos.knowledge import embeddings

    monkeypatch.setattr(embeddings, "get_embedding_function", lambda: None)
    monkeypatch.setenv("ANONYMIZED_TELEMETRY", "False")
    parent = await stores.work.create_work_item(title="Repository evidence", work_type="task", assigned_to="lead")
    await stores.work.transition_work_item(parent.id, "in_progress", source="test")
    children = [
        await stores.work.create_work_item(
            title=label, work_type="task", parent_id=parent.id, assigned_to=label, status="done",
        )
        for label in ("judged-producer", "unjudged-producer")
    ]
    registry = _Registry([_Agent("judge"), *[_Agent(child.assigned_to) for child in children]])
    runtime = SimpleNamespace(work_item_store=stores.work, attachment_store=stores.attachments)
    judged_llm, unjudged_llm = _FakeJudgeLLM("gpt-5.1"), _FakeJudgeLLM("gpt-5.1")
    verifiers = [
        SubtaskVerifier(
            llm_client=llm, work_item_store=stores.work, agent_registry=registry,
            trust_network=TrustNetwork(), agentic_executor=_StaticAgenticExecutor(), runtime=runtime,
            judge_policy=policy,
        )
        for llm, policy in ((judged_llm, _dedicated_policy()), (unjudged_llm, None))
    ]
    outcomes: list[ConvergenceOutcome] = []
    for child, verifier in zip(children, verifiers, strict=True):
        result = SubtaskResult(
            work_item_id=child.id, spec_id=child.id, agent_id=child.assigned_to,
            output="Produced repository report", status="done",
        )
        verdict = await verifier.verify(result)
        outcomes.append(ConvergenceOutcome(
            result=result, verdict=verdict, status="converged" if verdict.accepted else "unverified",
        ))
    assert len(judged_llm.requests) == len(unjudged_llm.requests) == 1
    assert outcomes[0].verdict.judge == _JUDGE and outcomes[1].verdict.judge is None
    memory = EpisodicMemory(db_path=tmp_path / "episodes" / "episodes.db")
    await memory.start()
    try:
        assert memory.is_available
        synth = CrewSynthesizer(
            llm_client=_ScriptedLLM([_text("Evidence-backed repository report")]),
            work_item_store=stores.work, trust_network=TrustNetwork(),
            episodic_memory=memory, attachment_store=stores.attachments, runtime=runtime,
        )
        completed = await synth.synthesize(parent.id, outcomes)
        assert completed.completed and completed.provenance_ref
        provenance = json.loads(await stores.attachments.read(completed.provenance_ref))
        by_id = {item["work_item_id"]: item for item in provenance["subtasks"]}
        assert by_id[children[0].id]["judge"] == judge_to_json(_JUDGE)
        assert "judge" not in by_id[children[1].id]
        episodes = await memory.recent(k=10)
        assert len(episodes) == 1, "the real episodic store did not persist the collaboration"
        recorded = {item["work_item_id"]: item for item in episodes[0].outcomes}
        assert recorded[children[0].id]["judge"] == judge_to_json(_JUDGE)
        assert "judge" not in recorded[children[1].id]
    finally:
        await memory.stop()


# 35
class _JudgedVerifier(_Verifier):
    async def verify(self, result: Any) -> VerificationVerdict:
        return replace(await super().verify(result), judge=_JUDGE)


class _RecordingSynthesizer(CrewSynthesizer):
    seen: list[ConvergenceOutcome]

    async def synthesize_owned_legacy(self, parent_id: str, outcomes: list[ConvergenceOutcome], **kwargs: Any) -> Any:
        self.seen = list(outcomes)
        return await super().synthesize_owned_legacy(parent_id, outcomes, **kwargs)


@pytest.mark.parametrize("judged", [True, False], ids=["judged", "unjudged"])
async def test_owned_legacy_review_restores_the_judge(store: Any, judged: bool) -> None:  # noqa: F811
    parent = await store.create_work_item(id="judge-parent", title="Judge parent")
    await store.create_work_item(
        id="judge-child", title="Judge child", parent_id=parent.id, assigned_to="worker-a",
        metadata={"spec_id": "spec-0"},
    )
    worker = _Worker()
    executor = _executor(store, worker)
    verifier = _JudgedVerifier() if judged else _Verifier()
    episodes = _Episodes()
    synth = _RecordingSynthesizer(
        llm_client=_SynthLLM(), work_item_store=store, trust_network=TrustNetwork(),
        episodic_memory=episodes, attachment_store=_FakeContent(), runtime=SimpleNamespace(),
    )
    orchestrator = CrewOrchestrator(
        assignment_resolver=_Resolver(), delegator=_Delegator(), crew_executor=executor,
        verifier=verifier, synthesizer=synth, work_item_store=store, runtime=SimpleNamespace(),
        config=SystemConfig(),
    )
    results = await executor.run(parent.id)
    assert len(results) == 1 and len(worker.calls) == 1
    snapshot = await store.get_owned_steps(parent.id)
    assert snapshot is not None
    converged = await verifier.converge(results[0], owned_steps_snapshot=snapshot)
    assert converged.verdict.judge == (_JUDGE if judged else None)  # premise: the fake returns what the test means
    await orchestrator.record_legacy_convergence(parent.id, converged)

    reviewed = await store.get_owned_steps(parent.id)
    assert reviewed is not None
    row = next(row for row in reviewed.control.rows if row.child is not None)
    record = await store.get_owned_step_evidence(parent.id, reviewed.control.incarnation, "review", row.reviewed_result)
    payload = json.loads((await store.read_owned_steps_content(record.verification)).decode("utf-8"))
    if judged:
        assert payload["judge"] == judge_to_json(_JUDGE)
    else:
        assert "judge" not in payload

    final = await orchestrator.run_crew_task(parent.id)
    assert final.completed is True
    assert len(worker.calls) == 1, "the recovered review must not re-run the worker"
    assert len(synth.seen) == 1
    recovered = synth.seen[0]
    assert isinstance(recovered, ConvergenceOutcome)
    assert recovered.verdict.judge == (_JUDGE if judged else None)

    # The owned-legacy episode payload is a second persistence site for the verdict: it must carry the judge too.
    assert len(episodes.stored) == 1
    (recorded,) = episodes.stored[0].outcomes
    assert recorded["work_item_id"] == "judge-child"
    if judged:
        assert recorded["judge"] == judge_to_json(_JUDGE)
    else:
        assert "judge" not in recorded


# ---------------------------------------------------------------------------
# Milestone 3: reports and wiring (tests 36-41)
# ---------------------------------------------------------------------------

_REPORT_CREW = {
    "llm_model_fast": "claude-sonnet-4-6-fast",
    "llm_model_standard": "claude-sonnet-4-6",
    "llm_model_deep": "claude-haiku-4-5",
}


def _report_config(*, orchestrator: bool, verifier_model: str = "", **extra: Any) -> SystemConfig:
    fields: dict[str, Any] = {**_REPORT_CREW, **extra}
    if verifier_model:
        fields["llm_model_verifier"] = verifier_model
    cfg = SystemConfig(cognitive=CognitiveConfig(**fields))
    cfg.agentic_dispatch.orchestrator_enabled = orchestrator
    return cfg


def _doctor_ctx(config: Any, tmp_path: Path) -> DoctorContext:
    return DoctorContext(config=config, home_dir=tmp_path, data_dir=tmp_path, config_path=None)


_OUTCOMES = [
    ("same_model", "", CheckOutcome.WARN),
    ("same_family", "claude-opus-4-6", CheckOutcome.WARN),
    ("independent", "gpt-5.1", CheckOutcome.OK),
    ("unknown", "mystery-7b", CheckOutcome.WARN),
]


@pytest.mark.parametrize(("outcome", "model", "expected"), _OUTCOMES, ids=[o[0] for o in _OUTCOMES])
async def test_doctor_reports_each_independence_outcome(
    outcome: str, model: str, expected: CheckOutcome, tmp_path: Path,
) -> None:
    cfg = _report_config(orchestrator=True, verifier_model=model)
    # Premise: the config really classifies as the outcome this case names.
    assert VerifierJudgePolicy.from_cognitive(cfg.cognitive).assess() == outcome

    result = await verifier_check._VerifierIndependenceCheck().run(_doctor_ctx(cfg, tmp_path))

    assert result.outcome == expected
    assert result.message.startswith(f"Crew verifier: {outcome} --")
    source = "cognitive.llm_model_verifier" if model else "the standard tier; cognitive.llm_model_verifier is unset"
    assert f"({source})" in result.message
    if expected is CheckOutcome.WARN:
        assert result.remediation == VERIFIER_REMEDIATION
    else:
        assert not result.remediation


async def test_doctor_is_ok_when_the_orchestrator_is_off(tmp_path: Path) -> None:
    check = verifier_check._VerifierIndependenceCheck()
    default = SystemConfig()
    assert default.agentic_dispatch.orchestrator_enabled is False  # premise: the shipped default is off

    off = await check.run(_doctor_ctx(default, tmp_path))
    missing = await check.run(_doctor_ctx(None, tmp_path))

    assert off.outcome == CheckOutcome.OK
    assert "not in use" in off.message
    assert missing.outcome == CheckOutcome.WARN
    assert "skipped" in missing.message


async def test_doctor_and_banner_redact_a_key_in_the_verifier_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "sk-ad1327-verifier-key-7Q2M"
    base = "https://verifier.example.test/v1"
    ps.validate_key_transport(base, key, allow_insecure_http=False)  # premise: setup accepts this key
    cfg = _report_config(
        orchestrator=True, verifier_model=key, llm_base_url_verifier=base, llm_api_key_verifier=key,
    )
    policy = VerifierJudgePolicy.from_cognitive(cfg.cognitive)
    _, detail = verifier_independence_report(policy)
    assert ps.carries_key(detail, key)  # negative control: the unredacted line does carry the key
    answer = {tier: True for tier in _LLM_TIERS}
    monkeypatch.setattr(main_mod, "OpenAICompatibleClient", lambda **kwargs: _Connectivity(answer))
    buffer = StringIO()

    await main_mod._create_llm_client(cfg, Console(file=buffer, width=240))
    checked = await verifier_check._VerifierIndependenceCheck().run(_doctor_ctx(cfg, tmp_path))

    out = buffer.getvalue()
    assert "Crew verifier:" in out and "Crew verifier:" in checked.message  # premise: both reports were produced
    assert not ps.carries_key(out, key)
    assert not ps.carries_key(f"{checked.message}\n{checked.remediation}", key)


@pytest.mark.parametrize(("outcome", "model", "expected"), _OUTCOMES, ids=[o[0] for o in _OUTCOMES])
async def test_boot_banner_reports_each_independence_outcome(
    outcome: str, model: str, expected: CheckOutcome, monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = {tier: True for tier in _LLM_TIERS}
    monkeypatch.setattr(main_mod, "OpenAICompatibleClient", lambda **kwargs: _Connectivity(answer))

    async def banner(cfg: SystemConfig) -> str:
        buffer = StringIO()
        await main_mod._create_llm_client(cfg, Console(file=buffer, width=240))
        return buffer.getvalue()

    on = await banner(_report_config(orchestrator=True, verifier_model=model))
    off = await banner(_report_config(orchestrator=False, verifier_model=model))

    lines = [line for line in on.splitlines() if f"Crew verifier: {outcome} --" in line]
    assert len(lines) == 1
    mark = "\u2713" if expected is CheckOutcome.OK else "\u26a0"
    assert mark in lines[0]
    assert "Crew verifier" not in off
    assert "Checking LLM endpoints" in off  # negative control: the banner ran, the line is what is absent


@pytest.mark.parametrize(("model", "level"), [("", logging.WARNING), ("gpt-5.1", logging.INFO)], ids=["same_model", "independent"])
def test_wired_crew_orchestrator_injects_the_judge_policy_and_logs_it(
    model: str, level: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.startup.finalize import _wire_crew_orchestrator

    captured: list[dict[str, Any]] = []

    class _RecordingVerifier(SubtaskVerifier):
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(crew_verifier_mod, "SubtaskVerifier", _RecordingVerifier)
    cfg = _report_config(orchestrator=True, verifier_model=model)
    cfg.attachments.attachments_dir = str(tmp_path / "attachments")
    runtime = SimpleNamespace(
        config=cfg, work_item_store=MagicMock(), registry=MagicMock(), capability_registry=MagicMock(),
        ontology=MagicMock(), trust_network=MagicMock(), llm_client=MagicMock(), crew_session_service=MagicMock(),
        chat_thread_store=MagicMock(), artifact_store=MagicMock(), order_manager=MagicMock(),
        episodic_memory=MagicMock(), emit_event=lambda *a, **k: None,
    )

    with caplog.at_level(logging.INFO, logger="probos.startup.finalize"):
        assert _wire_crew_orchestrator(runtime=runtime, config=cfg) is True

    assert len(captured) == 1  # premise: the wirer built exactly one verifier, through the patched class
    assert captured[0]["judge_policy"] == VerifierJudgePolicy.from_cognitive(cfg.cognitive)
    records = [r for r in caplog.records if r.getMessage().startswith("AD-1327: crew verifier:")]
    assert len(records) == 1
    assert records[0].levelno == level
    if level == logging.WARNING:
        assert records[0].getMessage().startswith("AD-1327: crew verifier: same_model")


async def test_quickstart_shape_doctor_has_no_new_warning(tmp_path: Path) -> None:
    one = {f"llm_model_{tier}": "one-model" for tier in TEXT_TIERS}
    cfg = SystemConfig(cognitive=CognitiveConfig(**one))
    assert cfg.agentic_dispatch.orchestrator_enabled is False  # premise: the quickstart leaves the orchestrator off
    assert VerifierJudgePolicy.from_cognitive(cfg.cognitive).assess() == "same_model"  # negative control: it would warn if on

    result = await verifier_check._VerifierIndependenceCheck().run(_doctor_ctx(cfg, tmp_path))

    assert result.outcome == CheckOutcome.OK
    names = [check.name for check in iter_checks()]
    assert names[names.index("extras") + 1] == "verifier_independence"


# ------------------------------------------------------------------ seam: real client over a loopback server (review round 1)

_AUTH_SCHEME = "Bearer"  # the scheme ``_build_client`` bakes into a pool's Authorization header
_OMIT = object()  # a provider reply that names no model at all


def _bearer(key: str) -> str:
    return f"{_AUTH_SCHEME} {key}"


class _Loopback:
    """A real HTTP server on 127.0.0.1. The first path segment picks the behaviour.

    Per segment: ``status`` (default 200), ``echo`` (the reply's ``model``; default the model sent,
    ``_OMIT`` leaves the field out), ``refuse`` (a predicate on the recorded request; True answers 401) and
    ``empty_first`` (a model id: the first 200 reply for it carries empty content, the BF-612 recovery trigger).
    Every request is recorded as ``{"segment", "path", "auth", "model", "status", "empty"}``.
    """

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        self.rules: dict[str, dict[str, Any]] = {}
        self.emptied: set[tuple[str, str]] = set()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                segment = self.path.split("/")[1]
                rule = owner.rules.get(segment, {})
                entry: dict[str, Any] = {
                    "segment": segment, "path": self.path,
                    "auth": self.headers.get("Authorization"), "model": body.get("model"),
                }
                refuse = rule.get("refuse")
                status = 401 if refuse is not None and refuse(entry) else rule.get("status", 200)
                entry["status"] = status
                empty_first = rule.get("empty_first")
                empty = (
                    status == 200 and empty_first is not None and body.get("model") == empty_first
                    and (segment, empty_first) not in owner.emptied
                )
                if empty:
                    owner.emptied.add((segment, empty_first))
                entry["empty"] = empty
                owner.seen.append(entry)
                payload: dict[str, Any] = {
                    "choices": [{"message": {"content": "" if empty else _ACCEPT}, "finish_reason": "stop"}],
                    "usage": {"total_tokens": 2, "prompt_tokens": 1, "completion_tokens": 1},
                }
                echo = rule["echo"] if "echo" in rule else body.get("model")
                if echo is not _OMIT:
                    payload["model"] = echo
                data = json.dumps(payload if status == 200 else {"error": "refused"}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def url(self, segment: str) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/{segment}/v1"

    def requests_to(self, segment: str) -> list[dict[str, Any]]:
        return [entry for entry in self.seen if entry["segment"] == segment]

    def first_appearances(self) -> list[str]:
        order: list[str] = []
        for entry in self.seen:
            if entry["segment"] not in order:
                order.append(entry["segment"])
        return order

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def loopback(monkeypatch: pytest.MonkeyPatch) -> typing.Iterator[_Loopback]:
    # A proxy in the environment could intercept loopback traffic; the test must reach the server itself.
    for name in ("PROBOS_LLM_URL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                 "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    server = _Loopback()
    try:
        yield server
    finally:
        server.close()


async def _judge_over_http(flow: str, cfg: CognitiveConfig) -> VerificationVerdict | SessionVerificationPass:
    """The real client and the real verifier judge one verdict over the network."""
    client = OpenAICompatibleClient(config=cfg)
    try:
        return await _run(flow, _verifier(client, VerifierJudgePolicy.from_cognitive(cfg)))
    finally:
        await client.close()


def _as_tuple(judge: JudgeProvenance | None) -> tuple[str, str, str, bool]:
    assert judge is not None
    return judge.tier, judge.model, judge.independence, judge.fallback


# 46
@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_f1_verifier_key_reaches_a_shared_endpoint_e2e(flow: str, loopback: _Loopback) -> None:
    shared, judge_key = "shared-k", "judge-k"
    cfg = CognitiveConfig(
        llm_base_url=loopback.url("shared"), llm_api_key=shared,
        llm_model_fast="claude-sonnet-4-6", llm_model_standard="claude-sonnet-4-6",
        llm_model_deep="claude-sonnet-4-6",
        llm_model_verifier="gpt-5.1", llm_api_key_verifier=judge_key,
    )
    # The server refuses a gpt-5.1 request that does not carry the verifier's own key.
    loopback.rules["shared"] = {"refuse": lambda e: e["model"] == "gpt-5.1" and e["auth"] != _bearer(judge_key)}

    verdict = await _judge_over_http(flow, cfg)

    judged = [e for e in loopback.seen if e["model"] == "gpt-5.1"]  # premise: the verifier request arrived
    assert judged and judged[0]["path"].startswith("/shared/")
    assert judged[0]["auth"] == _bearer(judge_key)
    assert judged[0]["status"] == 200
    assert verdict.accepted is True
    assert verdict.judge == JudgeProvenance(tier="verifier", model="gpt-5.1", independence="independent", fallback=False)

    # Negative control: the server refuses the verifier's key, so the check sees the header. The verifier
    # request is refused and the standard model answers: a fallback with the crew's own model.
    loopback.seen.clear()
    loopback.rules["shared"] = {"refuse": lambda e: e["auth"] == _bearer(judge_key)}
    refused = await _judge_over_http(flow, cfg)
    refused_requests = [e for e in loopback.seen if e["model"] == "gpt-5.1"]
    assert refused_requests and refused_requests[0]["auth"] == _bearer(judge_key)
    assert refused_requests[0]["status"] == 401
    assert [e for e in loopback.seen if e["model"] == "claude-sonnet-4-6" and e["status"] == 200]
    assert _as_tuple(refused.judge) == ("verifier", "claude-sonnet-4-6", "same_model", True)


_F2_CASES = [
    pytest.param("gpt-5.1", ("verifier", "gpt-5.1", "same_model", False), id="crew-model-echoed"),
    pytest.param(None, ("verifier", "", "unknown", False), id="null"),
    pytest.param(7, ("verifier", "", "unknown", False), id="int"),
    pytest.param("x\x00", ("verifier", "", "unknown", False), id="nul"),
    pytest.param("a" * 257, ("verifier", "", "unknown", False), id="too-long"),
    pytest.param("gpt-\ud800-5", ("verifier", "", "unknown", False), id="lone-surrogate"),  # sent as a ``\ud800`` escape
    pytest.param(_OMIT, ("verifier", "", "unknown", False), id="absent"),
    pytest.param("claude-sonnet-4-6", ("verifier", "claude-sonnet-4-6", "independent", False), id="control-honest-echo"),
]


# 47
@pytest.mark.parametrize("flow", ["legacy", "session"])
@pytest.mark.parametrize(("echo", "expected"), _F2_CASES)
async def test_f2_judge_record_names_the_providers_model_e2e(
    flow: str, echo: Any, expected: tuple[str, str, str, bool], loopback: _Loopback,
) -> None:
    cfg = CognitiveConfig(
        llm_base_url=loopback.url("shared"), llm_api_key="shared-k",
        llm_model_fast="gpt-5.1", llm_model_standard="gpt-5.1", llm_model_deep="gpt-5.1",
        llm_model_verifier="claude-sonnet-4-6", llm_base_url_verifier=loopback.url("judge"),
    )
    loopback.rules["judge"] = {"echo": echo}

    verdict = await _judge_over_http(flow, cfg)

    # Premise: the verifier request reached the judge path with the model the test means; the reply's model is the variable.
    sent = loopback.requests_to("judge")
    assert [(e["model"], e["status"]) for e in sent] == [("claude-sonnet-4-6", 200)]
    assert loopback.requests_to("shared") == []
    assert verdict.accepted is True
    assert _as_tuple(verdict.judge) == expected


# 48
@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_f3_dedicated_endpoint_down_same_model_id_is_a_fallback_e2e(flow: str, loopback: _Loopback) -> None:
    cfg = CognitiveConfig(
        llm_base_url=loopback.url("shared"), llm_api_key="shared-k",
        llm_base_url_fast=loopback.url("fast"), llm_base_url_standard=loopback.url("standard"),
        llm_base_url_deep=loopback.url("deep"),
        llm_model_fast="claude-sonnet-4-6", llm_model_standard="claude-sonnet-4-6",
        llm_model_deep="claude-sonnet-4-6",
        llm_model_verifier="claude-sonnet-4-6", llm_base_url_verifier=loopback.url("judge"),
    )

    # Control: with the dedicated path up it answers; the same model id as the crew is same_model, not a fallback.
    up = await _judge_over_http(flow, cfg)
    assert loopback.first_appearances() == ["judge"]
    assert _as_tuple(up.judge) == ("verifier", "claude-sonnet-4-6", "same_model", False)

    loopback.seen.clear()
    loopback.rules["judge"] = {"status": 503}
    down = await _judge_over_http(flow, cfg)

    # Premise: the 503 verifier request was recorded before the standard one answered.
    assert loopback.first_appearances()[:2] == ["judge", "standard"]
    assert loopback.requests_to("judge")[0]["status"] == 503
    assert loopback.requests_to("standard")[0]["status"] == 200
    assert down.accepted is True
    assert _as_tuple(down.judge) == ("verifier", "claude-sonnet-4-6", "same_model", True)


# Review round 2 (F4): a sibling tier's recovery rebuilds the shared pool with ITS key.
_F4_FAST_KEY, _F4_STANDARD_KEY = "a-k", "b-k"


def _f4_config(loopback: _Loopback, **overrides: Any) -> CognitiveConfig:
    fields: dict[str, Any] = {
        "llm_base_url": loopback.url("shared"), "llm_api_key": _F4_FAST_KEY,
        "llm_api_key_standard": _F4_STANDARD_KEY, "llm_api_key_verifier": _F4_FAST_KEY,
        "llm_model_fast": "claude-sonnet-4-6", "llm_model_standard": "claude-sonnet-4-6",
        "llm_model_deep": "claude-sonnet-4-6", "llm_model_verifier": "gpt-5.1",
    }
    fields.update(overrides)
    return CognitiveConfig(**fields)


def _f4_rules(loopback: _Loopback) -> None:
    """401 to a ``gpt-5.1`` request without ``a-k``; the first ``claude-sonnet-4-6`` reply is empty (BF-612)."""
    loopback.rules["shared"] = {
        "refuse": lambda e: e["model"] == "gpt-5.1" and e["auth"] != _bearer(_F4_FAST_KEY),
        "empty_first": "claude-sonnet-4-6",
    }


async def _recover_standard_then_judge(
    flow: str, cfg: CognitiveConfig, loopback: _Loopback,
) -> tuple[VerificationVerdict | SessionVerificationPass, list[dict[str, Any]], tuple[str, str]]:
    """One standard request (the empty reply and its recovery), then the verifier path on the same client.

    Returns the verdict, the ``claude-sonnet-4-6`` requests the server recorded, and the client's
    ``(verifier, standard)`` pool keys.
    """
    client = OpenAICompatibleClient(config=cfg)
    try:
        crew = await client.complete(LLMRequest(prompt="crew work", tier="standard"))
        assert crew.error is None and crew.content  # the recovery succeeded
        standard = [e for e in loopback.seen if e["model"] == "claude-sonnet-4-6"]
        verdict = await _run(flow, _verifier(client, VerifierJudgePolicy.from_cognitive(cfg)))
        keys = (client._client_key("verifier"), client._client_key("standard"))
    finally:
        await client.close()
    return verdict, standard, keys


# 50
@pytest.mark.parametrize("flow", ["legacy", "session"])
async def test_f4_sibling_refresh_keeps_the_verifier_key_e2e(flow: str, loopback: _Loopback) -> None:
    cfg = _f4_config(loopback)
    _f4_rules(loopback)

    verdict, standard, (verifier_key, standard_key) = await _recover_standard_then_judge(flow, cfg, loopback)

    # Premise: two standard requests reached the server, the second after the empty one, on the rebuilt pool.
    assert [(e["empty"], e["status"]) for e in standard] == [(True, 200), (False, 200)]
    assert [e["auth"] for e in standard] == [_bearer(_F4_FAST_KEY), _bearer(_F4_STANDARD_KEY)]
    judged = [e for e in loopback.seen if e["model"] == "gpt-5.1"]  # premise: the verifier request arrived
    assert len(judged) == 1 and judged[0]["path"].startswith("/shared/")
    assert loopback.seen.index(judged[0]) > loopback.seen.index(standard[1])
    assert judged[0]["auth"] == _bearer(_F4_FAST_KEY)
    assert judged[0]["status"] == 200
    assert verdict.accepted is True
    assert verdict.judge == JudgeProvenance(tier="verifier", model="gpt-5.1", independence="independent", fallback=False)
    assert verifier_key == standard_key + "|verifier"  # the verifier's own pool: a sibling's rebuild cannot reach it

    # Control: every key equal is one shared pool and the same judge.
    loopback.seen.clear()
    loopback.emptied.clear()
    same = _f4_config(loopback, llm_api_key_standard=None, llm_api_key_verifier=None)
    same_verdict, same_standard, (same_verifier_key, same_standard_key) = await _recover_standard_then_judge(
        flow, same, loopback,
    )
    assert [e["empty"] for e in same_standard] == [True, False]  # premise: the same recovery happened
    same_judged = [e for e in loopback.seen if e["model"] == "gpt-5.1"]
    assert [(e["auth"], e["status"]) for e in same_judged] == [(_bearer(_F4_FAST_KEY), 200)]
    assert same_verdict.judge == verdict.judge
    assert same_verifier_key == same_standard_key

    # Control: the verifier unset while standard has its own key: the judge request goes out as the standard tier.
    loopback.seen.clear()
    loopback.emptied.clear()
    unset = _f4_config(loopback, llm_model_verifier=None, llm_api_key_verifier=None)
    unset_verdict, _unset_standard, _keys = await _recover_standard_then_judge(flow, unset, loopback)
    unset_judged = [e for e in loopback.seen if e["model"] == "claude-sonnet-4-6" and not e["empty"]]
    assert len(unset_judged) == 2  # premise: the recovered crew request and the judge request
    assert _as_tuple(unset_verdict.judge) == ("standard", "claude-sonnet-4-6", "same_model", False)


# 51
_LONE_SURROGATE_MODEL = "gpt-\ud800-5"
_UNENCODABLE_RECORD = {"tier": "verifier", "model": "", "independence": "unknown", "fallback": False}


def test_f5_unencodable_reply_model_is_recorded_as_an_encodable_judge() -> None:
    # Premise: the hazard is visible to this probe (a strict UTF-8 encoder cannot write the lone surrogate).
    with pytest.raises(ValueError, match="^e$"):
        crew_finalizer._compact_bytes({"model": _LONE_SURROGATE_MODEL}, maximum=10_000, error="e")

    judge = _dedicated_policy().provenance(answered_tier="verifier", answered_model=_LONE_SURROGATE_MODEL)
    record = judge_to_json(judge)
    assert record == _UNENCODABLE_RECORD
    # The encoders of the checkpoint, the owned-steps manifest and the trust evidence, as their call sites use them.
    document = {"verdict": {"judge": record}}
    assert json.loads(crew_finalizer._compact_bytes(
        document, maximum=10_000, error="crew_finalization_checkpoint_too_large",
    )) == document
    assert json.loads(work_item_steps.owned_json_bytes(document)) == document
    assert json.loads(crew_trust._exact_json_bytes(
        document, error="crew_trust_evidence_invalid", maximum=crew_trust._MAX_EVIDENCE_BYTES,
    )) == document

    # Control: non-ASCII scalar text is written verbatim by all three.
    scalar = judge_to_json(_dedicated_policy().provenance(answered_tier="verifier", answered_model="gpt-é-5"))
    assert scalar["model"] == "gpt-é-5"
    scalar_document = {"verdict": {"judge": scalar}}
    assert json.loads(crew_finalizer._compact_bytes(
        scalar_document, maximum=10_000, error="crew_finalization_checkpoint_too_large",
    )) == scalar_document
    assert json.loads(work_item_steps.owned_json_bytes(scalar_document)) == scalar_document
    assert json.loads(crew_trust._exact_json_bytes(
        scalar_document, error="crew_trust_evidence_invalid", maximum=crew_trust._MAX_EVIDENCE_BYTES,
    )) == scalar_document


@pytest.mark.parametrize("answered", [_LONE_SURROGATE_MODEL, "gpt-é-5"], ids=["lone-surrogate", "control-scalar-text"])
async def test_f5_unencodable_reply_model_still_writes_the_checkpoint(answered: str, tmp_path: Any) -> None:
    expected = judge_to_json(_dedicated_policy().provenance(answered_tier="verifier", answered_model=answered))
    if answered == _LONE_SURROGATE_MODEL:
        assert expected == _UNENCODABLE_RECORD
    else:
        assert expected["model"] == answered  # the control: written verbatim
    llm = _FakeJudgeLLM("gpt-5.1", [_ACCEPT, _ACCEPT], answered_model=answered)
    probe = await _FakeJudgeLLM("gpt-5.1", [_ACCEPT], answered_model=answered).complete(
        LLMRequest(prompt="premise", tier="verifier"),
    )
    assert probe.answered_model == answered  # premise: the fake's responses carry the model under test

    async with _executed_session(tmp_path) as case:
        stores_ = case.stores
        registry = _registry_for([case.child])
        runtime = _runtime(stores_, tmp_path, case.service)
        verifier = SubtaskVerifier(
            llm_client=llm, work_item_store=stores_.work, agent_registry=registry,
            trust_network=_TrustRecorder(),
            agentic_executor=_StaticAgenticExecutor(final_text="Corrected durable evidence", trace_ref=None),
            runtime=runtime, judge_policy=_dedicated_policy(),
        )
        pause = _PauseBeforeArtifact()
        finalizer = _make_finalizer(
            stores=stores_, service=case.service, registry=registry, verifier=verifier,
            synthesizer=_make_synthesizer(llm=_ScriptedLLM([_text("Durable final report")]), stores=stores_, runtime=runtime),
            artifact_store=pause,
        )
        # The pause is reached: the checkpoints were written, not refused as "too large" (an unencodable record).
        with pytest.raises(asyncio.CancelledError, match="durable verdict checkpoints"):
            await finalizer.finalize(case.parent.id, case.results)
        assert pause.calls == 1 and len(llm.requests) == 2
        recovery = await case.service.get_recovery(case.parent.id)
        assert recovery is not None and recovery.final_verification_ref is not None
        final_document = json.loads(await stores_.attachments.read(recovery.final_verification_ref))
        assert final_document["verdict"]["judge"] == expected
