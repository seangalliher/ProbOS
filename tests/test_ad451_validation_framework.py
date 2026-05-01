"""AD-451: Tests for Validation Framework Hardening."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.validation_framework import (
    ReconciliationEscalator,
    ReconciliationOutcome,
    SelfVerificationHook,
    TwoStageOutcome,
    TwoStageVerifier,
    _MetadataCheck,
)
from probos.config import ValidationFrameworkConfig
from probos.events import EventType
from probos.types import IntentMessage, IntentResult, VerificationResult


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRedTeam:
    """Simulated RedTeamAgent with configurable verify response."""

    def __init__(
        self,
        agent_id: str = "rt-fake",
        verify_result: VerificationResult | None = None,
    ) -> None:
        self.id = agent_id
        self._verify_result = verify_result
        self.verify_calls = 0

    async def verify(
        self,
        target_agent_id: str,
        intent: IntentMessage,
        claimed: IntentResult,
    ) -> VerificationResult:
        self.verify_calls += 1
        if self._verify_result is not None:
            return self._verify_result
        return VerificationResult(
            verifier_id=self.id,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            verified=True,
            confidence=0.9,
        )


class _FakeRuntime:
    def __init__(self, red_team_agents: list[_FakeRedTeam] | None = None) -> None:
        self.red_team_agents: list[_FakeRedTeam] = red_team_agents or []


def _make_intent() -> IntentMessage:
    return IntentMessage(intent="read_file", params={"path": "/tmp/x"})


def _make_result(success: bool = True, error: str | None = None) -> IntentResult:
    return IntentResult(
        intent_id="i1",
        agent_id="a1",
        success=success,
        result={"data": "ok"},
        error=error,
    )


def _make_verification(
    verifier_id: str,
    *,
    verified: bool,
    confidence: float,
) -> VerificationResult:
    return VerificationResult(
        verifier_id=verifier_id,
        target_agent_id="target",
        intent_id="i1",
        verified=verified,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Tests — EventTypes & Config
# ---------------------------------------------------------------------------


def test_event_type_validation_reconciliation_requested_exists() -> None:
    assert EventType.VALIDATION_RECONCILIATION_REQUESTED.value == "validation_reconciliation_requested"


def test_event_type_validation_outcome_verified_exists() -> None:
    assert EventType.VALIDATION_OUTCOME_VERIFIED.value == "validation_outcome_verified"


def test_config_defaults() -> None:
    cfg = ValidationFrameworkConfig()
    assert cfg.enabled is True
    assert cfg.metadata_threshold == 0.85
    assert cfg.min_confidence_delta == 0.20


# ---------------------------------------------------------------------------
# Tests — TwoStageVerifier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_stage_verifier_metadata_only_path() -> None:
    rt = _FakeRedTeam()
    verifier = TwoStageVerifier(red_team=rt)
    outcome = await verifier.verify(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(success=True),
    )
    assert outcome.metadata_only is True
    assert outcome.live_confidence == 0.0
    assert outcome.verified is True
    assert rt.verify_calls == 0


@pytest.mark.asyncio
async def test_two_stage_verifier_escalates_on_error() -> None:
    rt = _FakeRedTeam(
        verify_result=_make_verification("rt-fake", verified=False, confidence=0.7),
    )
    verifier = TwoStageVerifier(red_team=rt)
    outcome = await verifier.verify(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(success=False, error="boom"),
    )
    assert outcome.metadata_only is False
    assert rt.verify_calls == 1
    assert outcome.verified is False
    assert outcome.live_confidence == 0.7


@pytest.mark.asyncio
async def test_two_stage_verifier_escalates_on_low_confidence() -> None:
    rt = _FakeRedTeam(
        verify_result=_make_verification("rt-fake", verified=True, confidence=0.6),
    )
    verifier = TwoStageVerifier(red_team=rt, metadata_threshold=0.99)
    outcome = await verifier.verify(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(success=True),
    )
    # Threshold 0.99 forces live path even on clean metadata (which scores 0.95)
    assert outcome.metadata_only is False
    assert rt.verify_calls == 1


@pytest.mark.asyncio
async def test_two_stage_verifier_emits_outcome_event() -> None:
    emit = MagicMock()
    verifier = TwoStageVerifier(red_team=_FakeRedTeam(), emit_event=emit)
    await verifier.verify(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(success=True),
    )
    assert emit.call_count == 1
    args = emit.call_args.args
    assert args[0] == EventType.VALIDATION_OUTCOME_VERIFIED
    payload = args[1]
    assert payload["verified"] is True
    assert payload["metadata_only"] is True
    assert payload["target_agent_id"] == "target"


# ---------------------------------------------------------------------------
# Tests — ReconciliationEscalator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_agreement_no_third_invoked() -> None:
    runtime = _FakeRuntime(red_team_agents=[_FakeRedTeam(f"rt{i}") for i in range(3)])
    escalator = ReconciliationEscalator(runtime=runtime)
    primary = _make_verification("rtA", verified=True, confidence=0.6)
    secondary = _make_verification("rtB", verified=True, confidence=0.5)
    outcome = await escalator.reconcile(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(),
        primary=primary,
        secondary=secondary,
    )
    assert outcome.reason == "agreement"
    assert outcome.third_invoked is False
    assert outcome.chosen_verdict is True


@pytest.mark.asyncio
async def test_reconciliation_confidence_delta_resolves() -> None:
    runtime = _FakeRuntime(red_team_agents=[_FakeRedTeam(f"rt{i}") for i in range(3)])
    escalator = ReconciliationEscalator(runtime=runtime)
    primary = _make_verification("rtA", verified=True, confidence=0.9)
    secondary = _make_verification("rtB", verified=False, confidence=0.5)  # delta 0.4 >= 0.2
    outcome = await escalator.reconcile(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(),
        primary=primary,
        secondary=secondary,
    )
    assert outcome.reason == "confidence_delta"
    assert outcome.third_invoked is False
    assert outcome.chosen_verdict is True  # higher-confidence (primary) verdict


@pytest.mark.asyncio
async def test_reconciliation_majority_vote_invokes_third() -> None:
    # Third red team returns verified=True with metadata-only fast-path
    third_rt = _FakeRedTeam("rtC")
    runtime = _FakeRuntime(red_team_agents=[
        _FakeRedTeam("rtA"), _FakeRedTeam("rtB"), third_rt,
    ])
    escalator = ReconciliationEscalator(runtime=runtime)
    primary = _make_verification("rtA", verified=True, confidence=0.55)
    secondary = _make_verification("rtB", verified=False, confidence=0.50)  # delta 0.05 < 0.2
    outcome = await escalator.reconcile(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(success=True),
        primary=primary,
        secondary=secondary,
    )
    assert outcome.reason == "majority_vote"
    assert outcome.third_invoked is True
    # primary True + secondary False + third (metadata-fast-path) True = 2 → True
    assert outcome.chosen_verdict is True


@pytest.mark.asyncio
async def test_reconciliation_third_excludes_primary_secondary_ids() -> None:
    rtA = _FakeRedTeam("rtA")
    rtB = _FakeRedTeam("rtB")
    rtC = _FakeRedTeam("rtC")
    runtime = _FakeRuntime(red_team_agents=[rtA, rtB, rtC])
    escalator = ReconciliationEscalator(runtime=runtime)
    primary = _make_verification("rtA", verified=True, confidence=0.55)
    secondary = _make_verification("rtB", verified=False, confidence=0.50)
    # Run several iterations to ensure rtA / rtB are NEVER picked
    for _ in range(20):
        await escalator.reconcile(
            target_agent_id="target",
            intent=_make_intent(),
            claimed=_make_result(success=True),
            primary=primary,
            secondary=secondary,
        )
    # rtA and rtB were never invoked as the third (they are excluded)
    assert rtA.verify_calls == 0
    assert rtB.verify_calls == 0


@pytest.mark.asyncio
async def test_reconciliation_third_unavailable_when_only_two_eligible() -> None:
    # Pool has only 2 agents, both already used as primary/secondary
    runtime = _FakeRuntime(red_team_agents=[_FakeRedTeam("rtA"), _FakeRedTeam("rtB")])
    escalator = ReconciliationEscalator(runtime=runtime)
    primary = _make_verification("rtA", verified=True, confidence=0.55)
    secondary = _make_verification("rtB", verified=False, confidence=0.50)
    outcome = await escalator.reconcile(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(),
        primary=primary,
        secondary=secondary,
    )
    assert outcome.reason == "third_unavailable"
    assert outcome.third_invoked is False
    # log-and-degrade: higher-confidence verdict picked
    assert outcome.chosen_verdict is True


@pytest.mark.asyncio
async def test_reconciliation_emit_includes_chosen_verdict() -> None:
    emit = MagicMock()
    runtime = _FakeRuntime(red_team_agents=[_FakeRedTeam(f"rt{i}") for i in range(3)])
    escalator = ReconciliationEscalator(runtime=runtime, emit_event=emit)
    primary = _make_verification("rtA", verified=True, confidence=0.9)
    secondary = _make_verification("rtB", verified=False, confidence=0.5)
    await escalator.reconcile(
        target_agent_id="target",
        intent=_make_intent(),
        claimed=_make_result(),
        primary=primary,
        secondary=secondary,
    )
    # confidence_delta path emits
    assert emit.call_count >= 1
    final_call = emit.call_args_list[-1]
    assert final_call.args[0] == EventType.VALIDATION_RECONCILIATION_REQUESTED
    payload = final_call.args[1]
    assert "chosen_verdict" in payload
    assert isinstance(payload["chosen_verdict"], bool)


# ---------------------------------------------------------------------------
# Tests — SelfVerificationHook + Runtime attribute
# ---------------------------------------------------------------------------


def test_self_verification_hook_protocol_runtime_checkable() -> None:
    """Decorated @runtime_checkable so isinstance() works against duck types."""
    class ConcreteHook:
        async def self_verify(self, intent: Any, result: Any) -> tuple[bool, str]:
            return (True, "")

    impl = ConcreteHook()
    assert isinstance(impl, SelfVerificationHook)


def test_runtime_attribute_is_public() -> None:
    """When wired, runtime.reconciliation_escalator exists with no underscore."""
    runtime = _FakeRuntime()
    escalator = ReconciliationEscalator(runtime=runtime)
    runtime.reconciliation_escalator = escalator
    assert hasattr(runtime, "reconciliation_escalator")
    assert not hasattr(runtime, "_reconciliation_escalator")
