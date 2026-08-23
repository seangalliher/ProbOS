"""BF-784 (#1248): the durable record could not tell a refusal from a defect.

BF-777 introduced `VerificationVerdict.verification_defect`, which separates
"the verifier failed" from "the work was refused" -- the distinction that stops
a verifier protocol error being handed to the producer as substantive
criticism, and why `converge()` terminates on a defect instead of re-running.

Both durable payloads dropped it. The provenance blob and the episodic
`episode_outcomes` payload carried `accepted` alone, so a reader of the audit
trail saw "refused" and could not tell whether an agent's work was judged and
found wanting, or never judged at all.

Not a live behaviour defect -- `crew_synth` does not branch on it and BF-778
removed the verifier trust write. It is a fidelity defect in what the ship
remembers, and it blocks two things being built on that memory: BF-782 needs to
exclude defects from any signal it learns from, and the self-diagnosis epic
reads episodic data to find them. A verifier failing silently 30% of the time is
invisible if every failure is recorded as an ordinary refusal.

These tests drive the REAL `CrewSynthesizer.synthesize()` and read the bytes it
actually persisted. The first version mirrored the production dict and asserted
a source-string count instead; review showed four of its five tests passed with
the production fix reverted, and the count could pass with both keys in the
wrong payload.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.crew_executor import SubtaskResult
from probos.cognitive.crew_synth import CrewSynthesizer
from probos.cognitive.crew_verifier import ConvergenceOutcome, VerificationVerdict
from probos.consensus.trust import TrustNetwork
from probos.workforce import WorkItemStore


class _CapturingAttachments:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    async def write(self, *, content_hash: str, blob: bytes, mime: str,
                    origin: str = "chat_attachment") -> Any:
        self.writes.append({"content_hash": content_hash, "blob": blob})
        return content_hash


class _CapturingEpisodic:
    def __init__(self) -> None:
        self.stored: list[Any] = []

    async def store(self, episode: Any) -> None:
        self.stored.append(episode)


class _FakeLLM:
    async def complete(self, *a: Any, **kw: Any) -> str:
        return "synthesised parent answer"

    async def generate(self, *a: Any, **kw: Any) -> str:
        return "synthesised parent answer"


def _outcome(*, defect: bool, work_item_id: str) -> ConvergenceOutcome:
    """A REFUSED outcome. ``accepted`` is False either way -- the flag is the
    only thing separating "judged and found wanting" from "never judged"."""
    return ConvergenceOutcome(
        result=SubtaskResult(
            work_item_id=work_item_id,
            spec_id=f"spec-{work_item_id}",
            agent_id="producer",
            output="produced output",
            status="done",
        ),
        verdict=VerificationVerdict(
            accepted=False,
            confidence=0.4,
            critique="no",
            verifier_agent_id="verifier",
            verification_defect=defect,
        ),
        status="unverified",
    )


@pytest.fixture
async def store(tmp_path):
    s = WorkItemStore(
        db_path=str(tmp_path / "bf784.db"),
        emit_event=MagicMock(),
        tick_interval=1000,
    )
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def _run(store) -> tuple[dict, Any]:
    """Synthesise one refused-only and one refused-and-defective outcome.

    Returns the decoded provenance blob and the stored Episode.
    """
    parent = await store.create_work_item(
        title="parent", work_type="task", assigned_to="lead",
    )
    await store.transition_work_item(parent.id, "in_progress", source="test")

    attachments, episodic = _CapturingAttachments(), _CapturingEpisodic()
    synth = CrewSynthesizer(
        llm_client=_FakeLLM(),
        work_item_store=store,
        trust_network=TrustNetwork(),
        episodic_memory=episodic,
        attachment_store=attachments,
        runtime=SimpleNamespace(),
        emit_fn=None,
    )

    await synth.synthesize(parent.id, [
        _outcome(defect=False, work_item_id="plain"),
        _outcome(defect=True, work_item_id="broken"),
    ])

    assert attachments.writes, "no provenance blob was persisted"
    blob = json.loads(attachments.writes[0]["blob"].decode("utf-8"))
    assert episodic.stored, "no episode was stored"
    return blob, episodic.stored[0]


# ── the durable records ───────────────────────────────────────────


async def test_the_persisted_provenance_blob_separates_them(store) -> None:
    blob, _episode = await _run(store)

    by_id = {s["work_item_id"]: s for s in blob["subtasks"]}
    assert by_id["plain"]["verification_defect"] is False
    assert by_id["broken"]["verification_defect"] is True

    # Both refused. Without the flag these two rows are identical.
    assert by_id["plain"]["accepted"] is False
    assert by_id["broken"]["accepted"] is False


async def test_the_stored_episode_separates_them(store) -> None:
    _blob, episode = await _run(store)

    by_id = {o["work_item_id"]: o for o in episode.outcomes}
    assert by_id["plain"]["verification_defect"] is False
    assert by_id["broken"]["verification_defect"] is True


async def test_the_flag_survives_as_a_json_boolean_not_a_string(store) -> None:
    """``_store_provenance`` serialises with ``default=str``, which would render
    a non-JSON-native value as ``"True"`` -- truthy whatever it was."""
    blob, _episode = await _run(store)

    for subtask in blob["subtasks"]:
        assert isinstance(subtask["verification_defect"], bool), subtask


# ── the premise, so the assertions above cannot pass vacuously ────


def test_the_field_defaults_to_not_a_defect() -> None:
    """If the default flipped, every ordinary refusal would record as a verifier
    failure and the signal would invert."""
    verdict = VerificationVerdict(
        accepted=False, confidence=0.5, critique="no", verifier_agent_id="v",
    )
    assert verdict.verification_defect is False
