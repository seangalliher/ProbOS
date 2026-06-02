"""AD-833 v1: proposal grounding gate tests."""

from __future__ import annotations

import pytest

from probos.cognitive.self_improvement.approval_gate import ApprovalGate
from probos.cognitive.self_improvement.grounding import (
    GroundingFinding,
    ProposalGroundingResult,
    ProposalGroundingVerifier,
    SymbolExistenceProvider,
    _GROUNDING_VERIFIED_THRESHOLD,
)
from probos.cognitive.self_improvement.proposal import CapabilityProposal, ProposalStore


class _FakeCodebaseIndex:
    """Real-shaped stub (NO MagicMock at the index boundary).

    Resolves any token in ``known`` via query(); everything else is unresolved.
    """

    def __init__(self, known: set[str] | None = None) -> None:
        self._known = known or set()

    def query(self, concept: str) -> dict:
        if concept in self._known:
            return {
                "matching_files": [
                    {"path": f"src/{concept}.py", "docstring": "", "relevance": 1.0}
                ],
                "matching_agents": [],
                "matching_methods": [],
                "layer": "cognitive",
            }
        return {
            "matching_files": [],
            "matching_agents": [],
            "matching_methods": [],
            "layer": None,
        }

    def find_callers(self, method_name: str, max_results: int = 10) -> list[dict]:
        return []

    def get_full_api_surface(self) -> dict[str, list[dict]]:
        return {}


def _proposal(
    summary: str = "",
    fit_assessment: str = "",
    pid: str = "p1",
) -> CapabilityProposal:
    return CapabilityProposal(
        id=pid,
        source="scout",
        source_url="http://example.invalid",
        summary=summary,
        relevance=0.5,
        fit_assessment=fit_assessment,
        integration_effort_hours=1.0,
    )


# --- SymbolExistenceProvider -------------------------------------------------


@pytest.mark.asyncio
async def test_symbol_existence_real_symbol_verified_true() -> None:
    index = _FakeCodebaseIndex(known={"CapabilityProposal", "vision_observation"})
    provider = SymbolExistenceProvider(index)
    proposal = _proposal(
        summary="The CapabilityProposal flow drops vision_observation events.",
    )
    finding = await provider.check(proposal)
    assert finding.verified is True
    assert finding.score == 1.0
    assert finding.provider_name == "symbol_existence"


@pytest.mark.asyncio
async def test_symbol_existence_phantom_verified_false_evidence() -> None:
    index = _FakeCodebaseIndex(known={"CapabilityProposal"})
    provider = SymbolExistenceProvider(index)
    proposal = _proposal(
        summary="CapabilityProposal collides with FooBarNonexistentAgent.",
    )
    finding = await provider.check(proposal)
    assert finding.verified is False
    assert finding.score < 1.0
    assert any("FooBarNonexistentAgent: UNRESOLVED" in e for e in finding.evidence)


@pytest.mark.asyncio
async def test_symbol_existence_prose_only_verified_none() -> None:
    index = _FakeCodebaseIndex()
    provider = SymbolExistenceProvider(index)
    proposal = _proposal(summary="this adds about thirty ms of latency to the path")
    finding = await provider.check(proposal)
    assert finding.verified is None
    assert finding.score == 0.0


@pytest.mark.asyncio
async def test_symbol_existence_resolves_via_api_surface() -> None:
    class _SurfaceIndex(_FakeCodebaseIndex):
        def query(self, concept: str) -> dict:
            return {
                "matching_files": [],
                "matching_agents": [],
                "matching_methods": [],
                "layer": None,
            }

        def get_full_api_surface(self) -> dict[str, list[dict]]:
            return {"ProposalStore": [{"method": "attach_grounding", "signature": "()"}]}

    provider = SymbolExistenceProvider(_SurfaceIndex())
    proposal = _proposal(summary="extend ProposalStore with attach_grounding")
    finding = await provider.check(proposal)
    assert finding.verified is True
    assert finding.score == 1.0


# --- ProposalGroundingVerifier ----------------------------------------------


@pytest.mark.asyncio
async def test_verifier_aggregation_happy_path() -> None:
    index = _FakeCodebaseIndex(known={"CapabilityProposal"})
    verifier = ProposalGroundingVerifier(providers=[SymbolExistenceProvider(index)])
    result = await verifier.verify(_proposal(summary="touch CapabilityProposal"))
    assert result.verified is True
    assert result.score >= _GROUNDING_VERIFIED_THRESHOLD
    assert result.confidence == 1.0
    assert len(result.findings) == 1


@pytest.mark.asyncio
async def test_verifier_empty_providers_default_verified() -> None:
    verifier = ProposalGroundingVerifier(providers=[])
    result = await verifier.verify(_proposal(summary="anything"))
    assert result.verified is True
    assert result.score == 1.0
    assert result.confidence == 0.0
    assert result.findings == []


@pytest.mark.asyncio
async def test_verifier_raising_provider_degraded_logged(caplog) -> None:
    class _Boom:
        name = "boom"

        async def check(self, proposal: CapabilityProposal) -> GroundingFinding:
            raise RuntimeError("provider exploded")

    verifier = ProposalGroundingVerifier(providers=[_Boom()])
    with caplog.at_level("WARNING"):
        result = await verifier.verify(_proposal(summary="x"))
    # No findings -> empty-aggregate defaults; not fatal.
    assert result.findings == []
    assert result.verified is True
    assert any("AD-833" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_verifier_confidence_reflects_determinations() -> None:
    class _Abstain:
        name = "abstain"

        async def check(self, proposal: CapabilityProposal) -> GroundingFinding:
            return GroundingFinding(
                provider_name=self.name, verified=None, score=0.0, evidence=[]
            )

    class _Determine:
        name = "determine"

        async def check(self, proposal: CapabilityProposal) -> GroundingFinding:
            return GroundingFinding(
                provider_name=self.name, verified=True, score=1.0, evidence=[]
            )

    verifier = ProposalGroundingVerifier(providers=[_Abstain(), _Determine()])
    result = await verifier.verify(_proposal(summary="x"))
    assert result.confidence == 0.5
    assert len(result.findings) == 2


@pytest.mark.asyncio
async def test_verifier_false_finding_forces_unverified() -> None:
    class _Contradict:
        name = "contradict"

        async def check(self, proposal: CapabilityProposal) -> GroundingFinding:
            return GroundingFinding(
                provider_name=self.name, verified=False, score=1.0, evidence=[]
            )

    verifier = ProposalGroundingVerifier(providers=[_Contradict()])
    result = await verifier.verify(_proposal(summary="x"))
    # High score but a False finding -> not verified.
    assert result.verified is False


# --- ProposalStore grounding association ------------------------------------


def test_proposal_store_attach_get_roundtrip() -> None:
    store = ProposalStore()
    pid = store.submit(_proposal(summary="x", pid="rt1"))
    result = ProposalGroundingResult(score=0.9, verified=True, findings=[], confidence=1.0)
    store.attach_grounding(pid, result)
    assert store.get_grounding(pid) is result


def test_proposal_store_attach_unknown_id_noop_warning(caplog) -> None:
    store = ProposalStore()
    result = ProposalGroundingResult(score=0.0, verified=False, findings=[], confidence=0.0)
    with caplog.at_level("WARNING"):
        store.attach_grounding("nope", result)
    assert store.get_grounding("nope") is None
    assert any("AD-833" in r.message for r in caplog.records)


def test_proposal_store_get_grounding_unknown_none() -> None:
    store = ProposalStore()
    assert store.get_grounding("missing") is None


def test_proposal_store_submit_signature_unchanged() -> None:
    store = ProposalStore()
    pid = store.submit(_proposal(summary="x", pid="sig1"))
    assert pid == "sig1"
    assert store.get_grounding(pid) is None


# --- ApprovalGate ------------------------------------------------------------


def test_approval_gate_list_pending_unchanged() -> None:
    store = ProposalStore()
    gate = ApprovalGate(proposal_store=store)
    gate.enqueue(_proposal(summary="x", pid="lp1"))
    pending = gate.list_pending()
    assert all(isinstance(p, CapabilityProposal) for p in pending)
    assert [p.id for p in pending] == ["lp1"]


def test_approval_gate_list_pending_grounded_none_when_absent() -> None:
    store = ProposalStore()
    gate = ApprovalGate(proposal_store=store)
    gate.enqueue(_proposal(summary="x", pid="lpg1"))
    grounded = gate.list_pending_grounded()
    assert len(grounded) == 1
    proposal, grounding = grounded[0]
    assert proposal.id == "lpg1"
    assert grounding is None


@pytest.mark.asyncio
async def test_approval_gate_enqueue_grounded_with_verifier_attaches() -> None:
    store = ProposalStore()
    index = _FakeCodebaseIndex(known={"CapabilityProposal"})
    verifier = ProposalGroundingVerifier(providers=[SymbolExistenceProvider(index)])
    gate = ApprovalGate(proposal_store=store, grounding_verifier=verifier)
    pid = await gate.enqueue_grounded(_proposal(summary="touch CapabilityProposal", pid="eg1"))
    result = store.get_grounding(pid)
    assert result is not None
    assert result.verified is True


@pytest.mark.asyncio
async def test_approval_gate_enqueue_grounded_none_verifier() -> None:
    store = ProposalStore()
    gate = ApprovalGate(proposal_store=store, grounding_verifier=None)
    pid = await gate.enqueue_grounded(_proposal(summary="x", pid="eg2"))
    assert pid == "eg2"
    assert store.get_grounding(pid) is None


@pytest.mark.asyncio
async def test_approval_gate_enqueue_grounded_raising_verifier_still_submits(caplog) -> None:
    store = ProposalStore()

    class _BoomVerifier:
        async def verify(self, proposal: CapabilityProposal) -> ProposalGroundingResult:
            raise RuntimeError("verify exploded")

    gate = ApprovalGate(proposal_store=store, grounding_verifier=_BoomVerifier())
    with caplog.at_level("WARNING"):
        pid = await gate.enqueue_grounded(_proposal(summary="x", pid="eg3"))
    assert pid == "eg3"
    assert store.get_grounding(pid) is None
    assert any("AD-833" in r.message for r in caplog.records)
