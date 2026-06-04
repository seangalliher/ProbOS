"""AD-861: result synthesis + Shapley attribution -> parent completion.

``CrewSynthesizer`` folds the verified :class:`ConvergenceOutcome`s produced by
AD-860 into a single parent completion: it synthesises the parent output, moves
the parent to ``done`` through the *validated* AD-498 state machine, computes
Shapley attribution across producers and verifiers, records each crew member's
success against the trust ledger, stores a collaboration episode (guarded), and
emits :attr:`EventType.CREW_TASK_COMPLETED`.

Per BF-287 these tests use a REAL :class:`WorkItemStore` (so a phantom attribute
on the substrate boundary cannot hide behind a MagicMock) and a REAL
:class:`TrustNetwork`. The LLM, attachment store, and episodic memory are small
``_Fake*`` stubs with the exact public shapes the synthesiser calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_synth import CrewSynthesizer, SynthesisResult
from probos.cognitive.crew_verifier import ConvergenceOutcome, VerificationVerdict
from probos.consensus.trust import TrustNetwork
from probos.events import EventType
from probos.workforce import WorkItemStore


# ------------------------------------------------------------------ fakes

class _FakeLLM:
    """Scripted LLM: ``complete`` pops the next response and records the request."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kw: Any) -> Any:
        self.requests.append(request)
        content = self._responses.pop(0) if self._responses else ""
        return SimpleNamespace(content=content)


class _RaisingLLM:
    """LLM stub that always raises, to exercise the honest-degrade path."""

    async def complete(self, request: Any, **_kw: Any) -> Any:
        raise RuntimeError("llm boom")


class _FakeAttachmentStore:
    """Records ``write`` calls so provenance-as-ref can be asserted."""

    def __init__(self, fail: bool = False) -> None:
        self.writes: list[dict[str, Any]] = []
        self._fail = fail

    async def write(self, *, content_hash: str, blob: bytes, mime: str,
                    origin: str = "chat_attachment") -> Any:
        if self._fail:
            raise OSError("disk full")
        self.writes.append({
            "content_hash": content_hash, "blob": blob, "mime": mime, "origin": origin,
        })
        return content_hash


class _FakeEpisodic:
    """Records stored episodes so the collaboration-episode payoff can be asserted."""

    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, episode: Any) -> None:
        self.stored.append(episode)


# ------------------------------------------------------------------ builders

def _verdict(*, accepted: bool, confidence: float = 0.9, verifier_id: str = "verifier",
             critique: str = "ok") -> VerificationVerdict:
    return VerificationVerdict(
        accepted=accepted, confidence=confidence, critique=critique,
        verifier_agent_id=verifier_id,
    )


def _outcome(
    *,
    output: str = "produced output",
    producer: str = "producer",
    accepted: bool = True,
    confidence: float = 0.9,
    verifier_id: str = "verifier",
    status: str = "converged",
    spec_id: str = "spec-1",
    work_item_id: str = "child-1",
) -> ConvergenceOutcome:
    return ConvergenceOutcome(
        result=SubtaskResult(
            work_item_id=work_item_id,
            spec_id=spec_id,
            agent_id=producer,
            output=output,
            status="done",
        ),
        verdict=_verdict(accepted=accepted, confidence=confidence, verifier_id=verifier_id),
        status=status,
    )


# ------------------------------------------------------------------ fixtures

@pytest.fixture
async def store(tmp_path):
    s = WorkItemStore(
        db_path=str(tmp_path / "crew_synth.db"),
        emit_event=MagicMock(),
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def _make_parent(store: WorkItemStore, *, in_progress: bool = True) -> str:
    """Create a ``task`` parent and (optionally) move it to ``in_progress`` so a
    later ``in_progress -> done`` transition is valid under the AD-498 machine."""
    parent = await store.create_work_item(
        title="parent", work_type="task", assigned_to="lead",
    )
    if in_progress:
        moved = await store.transition_work_item(parent.id, "in_progress", source="test")
        assert moved is not None and moved.status == "in_progress"
    return parent.id


def _make_synth(
    *,
    store: WorkItemStore,
    llm: Any = None,
    trust: TrustNetwork | None = None,
    episodic: Any = None,
    attachments: Any = None,
    emit_fn: Any = None,
) -> tuple[CrewSynthesizer, _FakeLLM, TrustNetwork]:
    real_trust = trust or TrustNetwork()
    fake_llm = llm if llm is not None else _FakeLLM(["synthesised parent answer"])
    synth = CrewSynthesizer(
        llm_client=fake_llm,
        work_item_store=store,
        trust_network=real_trust,
        episodic_memory=episodic,
        attachment_store=attachments if attachments is not None else _FakeAttachmentStore(),
        runtime=SimpleNamespace(),
        emit_fn=emit_fn,
    )
    return synth, fake_llm, real_trust


# ------------------------------------------------------------------ tests

async def test_synthesize_accepted_outcomes_completes_parent_via_validated_transition(store):
    """Accepted outcomes synthesise into the parent and move it to ``done``
    through the validated state machine (NOT a raw status update)."""
    parent_id = await _make_parent(store)
    synth, llm, _ = _make_synth(store=store)

    result = await synth.synthesize(parent_id, [_outcome(), _outcome(spec_id="spec-2")])

    assert isinstance(result, SynthesisResult)
    assert result.completed is True
    assert result.final_output == "synthesised parent answer"
    # The validated machine landed the parent on a terminal 'done' status.
    item = await store.get_work_item(parent_id)
    assert item.status == "done"
    # The LLM was asked to fold the outputs (synthesis happened, not a fallback).
    assert len(llm.requests) == 1
    assert llm.requests[0].tier == "standard"


async def test_synthesize_invalid_transition_honest_degrades_not_silent_success(store):
    """A parent whose work type cannot reach ``done`` from its current status is
    an honest-degrade: ``completed`` is False and the status is unchanged."""
    # An 'open' task cannot transition straight to 'done' (needs in_progress first).
    parent_id = await _make_parent(store, in_progress=False)
    synth, _, _ = _make_synth(store=store)

    result = await synth.synthesize(parent_id, [_outcome()])

    assert result.completed is False
    item = await store.get_work_item(parent_id)
    assert item.status == "open"  # never silently flipped to done


async def test_shapley_spans_producers_and_verifiers_with_agent_id_keys(store):
    """Shapley attribution covers both producers and verifiers, keyed by
    ``agent_id``."""
    parent_id = await _make_parent(store)
    synth, _, _ = _make_synth(store=store)

    outcomes = [
        _outcome(producer="alice", verifier_id="vera", spec_id="s1", work_item_id="c1"),
        _outcome(producer="bob", verifier_id="vance", spec_id="s2", work_item_id="c2"),
    ]
    result = await synth.synthesize(parent_id, outcomes)

    assert set(result.shapley_values) == {"alice", "vera", "bob", "vance"}
    assert all(0.0 <= v <= 1.0 for v in result.shapley_values.values())


async def test_shapley_merges_agent_that_is_both_producer_and_verifier(store):
    """An agent that is both a producer and a verifier in the same set is merged
    into a single attribution key (intentional, not a silent overwrite)."""
    parent_id = await _make_parent(store)
    synth, _, _ = _make_synth(store=store)

    # 'carol' produced spec-1 AND verified spec-2 -> one merged key.
    outcomes = [
        _outcome(producer="carol", verifier_id="dave", spec_id="s1", work_item_id="c1"),
        _outcome(producer="erin", verifier_id="carol", spec_id="s2", work_item_id="c2"),
    ]
    result = await synth.synthesize(parent_id, outcomes)

    assert "carol" in result.shapley_values
    assert set(result.shapley_values) == {"carol", "dave", "erin"}


async def test_trust_ledger_records_each_crew_member_success(store):
    """Each attributed crew member gets a success recorded against the trust
    ledger (real TrustNetwork, no MagicMock at the trust boundary)."""
    parent_id = await _make_parent(store)
    trust = TrustNetwork()
    before = trust.get_score("alice")
    synth, _, real_trust = _make_synth(store=store, trust=trust)

    await synth.synthesize(
        parent_id, [_outcome(producer="alice", verifier_id="vera")],
    )

    # A recorded success moves the Beta mean above the prior.
    assert real_trust.get_score("alice") > before


async def test_collaboration_episode_stored_when_episodic_present(store):
    """A collaboration episode is stored (with shapley + agent ids) when episodic
    memory is wired."""
    parent_id = await _make_parent(store)
    episodic = _FakeEpisodic()
    synth, _, _ = _make_synth(store=store, episodic=episodic)

    result = await synth.synthesize(
        parent_id, [_outcome(producer="alice", verifier_id="vera")],
    )

    assert len(episodic.stored) == 1
    episode = episodic.stored[0]
    assert episode.shapley_values == result.shapley_values
    assert set(episode.agent_ids) == {"alice", "vera"}
    assert episode.source == "crew_collaboration"


async def test_episode_guarded_when_episodic_memory_disabled(store):
    """When episodic memory is ``None`` the synthesiser must not crash — the
    collaboration still completes."""
    parent_id = await _make_parent(store)
    synth, _, _ = _make_synth(store=store, episodic=None)

    result = await synth.synthesize(parent_id, [_outcome()])

    assert result.completed is True  # no crash, parent still completed


async def test_provenance_stored_as_ref_not_inline(store):
    """Provenance is persisted as a content-addressable ref (AD-731); the parent
    metadata carries the hash, not the inline blob."""
    parent_id = await _make_parent(store)
    attachments = _FakeAttachmentStore()
    synth, _, _ = _make_synth(store=store, attachments=attachments)

    result = await synth.synthesize(parent_id, [_outcome()])

    assert result.provenance_ref is not None
    assert len(attachments.writes) == 1
    write = attachments.writes[0]
    assert write["content_hash"] == result.provenance_ref
    assert write["mime"] == "application/json"
    assert write["origin"] == "crew_synth_provenance"
    # The parent metadata stores the REF, never the bytes.
    item = await store.get_work_item(parent_id)
    crew = item.metadata["crew_synth"]
    assert crew["provenance_ref"] == result.provenance_ref
    assert isinstance(crew["provenance_ref"], str)


async def test_partial_collaboration_synthesizes_from_accepted_only(store):
    """A partial collaboration (some refuted/unverified) synthesises from the
    accepted outcomes only and records a caveat."""
    parent_id = await _make_parent(store)
    synth, llm, _ = _make_synth(store=store)

    outcomes = [
        _outcome(producer="alice", verifier_id="vera", spec_id="s1", work_item_id="c1"),
        _outcome(producer="bob", accepted=False, status="unverified", spec_id="s2",
                 work_item_id="c2"),
    ]
    result = await synth.synthesize(parent_id, outcomes)

    assert result.accepted_count == 1
    assert result.total_count == 2
    # Only the accepted producer/verifier are attributed.
    assert set(result.shapley_values) == {"alice", "vera"}
    item = await store.get_work_item(parent_id)
    assert "partial" in item.metadata["crew_synth"]["caveat"]


async def test_no_accepted_outcomes_degrades_to_empty_synthesis(store):
    """When nothing is accepted the synthesiser degrades to an empty output and
    attributes no one — without crashing."""
    parent_id = await _make_parent(store)
    synth, llm, _ = _make_synth(store=store)

    outcome = _outcome(producer="bob", accepted=False, status="unverified")
    result = await synth.synthesize(parent_id, [outcome])

    assert result.accepted_count == 0
    assert result.final_output == ""  # deterministic empty fallback
    assert result.shapley_values == {}
    # No LLM call when there is nothing to fold.
    assert llm.requests == []


async def test_llm_failure_degrades_to_concatenated_fallback(store):
    """An LLM that raises must not abort synthesis — the parent output degrades
    to a deterministic concatenation of accepted outputs."""
    parent_id = await _make_parent(store)
    synth, _, _ = _make_synth(store=store, llm=_RaisingLLM())

    outcomes = [
        _outcome(output="part one", spec_id="s1", work_item_id="c1"),
        _outcome(output="part two", spec_id="s2", work_item_id="c2"),
    ]
    result = await synth.synthesize(parent_id, outcomes)

    assert "part one" in result.final_output
    assert "part two" in result.final_output
    assert result.completed is True


async def test_crew_task_completed_event_emitted(store):
    """``CREW_TASK_COMPLETED`` is emitted with the attribution payload."""
    parent_id = await _make_parent(store)
    events: list[tuple[EventType, dict[str, Any]]] = []
    synth, _, _ = _make_synth(store=store, emit_fn=lambda et, data: events.append((et, data)))

    await synth.synthesize(parent_id, [_outcome(producer="alice", verifier_id="vera")])

    completed_events = [e for e in events if e[0] == EventType.CREW_TASK_COMPLETED]
    assert len(completed_events) == 1
    payload = completed_events[0][1]
    assert payload["parent_id"] == parent_id
    assert payload["completed"] is True
    assert set(payload["shapley_values"]) == {"alice", "vera"}


async def test_attachment_store_unwired_degrades_provenance_to_none(store):
    """No attachment store wired -> provenance_ref is None, but completion still
    succeeds."""
    parent_id = await _make_parent(store)
    synth = CrewSynthesizer(
        llm_client=_FakeLLM(["answer"]),
        work_item_store=store,
        trust_network=TrustNetwork(),
        episodic_memory=None,
        attachment_store=None,
        runtime=SimpleNamespace(),
    )

    result = await synth.synthesize(parent_id, [_outcome()])

    assert result.provenance_ref is None
    assert result.completed is True
