"""AD-1231 (#1116): Design Principle 1 is hybrid, and says so in one voice.

The written contract said *"No central scheduler."* The running system has had
`CrewOrchestrator` owning scheduling admission, parent-keyed tasks, recovery and
durable state transitions across nine live boots. Both were defensible; together
they meant a crew change could not be reviewed against a stable principle,
because the principle and the code disagreed about what the system is.

The Captain's resolution, verbatim: *"the idea was to not have a central
scheduler bottle neck like other multi agent orchestration architectures. There
are times where a central scheduler is needed and times where agents can decide
when what they want to work on. So really what we should now define as a
principle is a hybrid."*

That reframes the objection precisely. The thing to avoid is **one planner
becoming the single point of thought** — every decision queueing behind it, the
system's ceiling set by its context window. A service that sequences durable
state while N agents reason concurrently is not that.

So the boundary is about *what* is decided, not *who* decides:

- a service may decide **when a durable step runs, in what order, whether twice**
- an agent decides **what the work is, whether to take it, how to do it**

These tests pin the documents to that boundary. They are deliberately coherence
tests rather than behavioural ones: the defect #1116 reports is not that the
code is wrong, it is that the code and the contract describe different systems.
A behavioural test cannot catch that — it was the absence of this kind of
assertion that let the drift persist.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INSTRUCTIONS = _REPO_ROOT / ".github" / "copilot-instructions.md"


@pytest.fixture(scope="module")
def instructions() -> str:
    return _INSTRUCTIONS.read_text(encoding="utf-8")


# ── the contract states the hybrid ────────────────────────────────


def test_principle_one_no_longer_claims_there_is_no_central_scheduler(
    instructions: str,
) -> None:
    """The bare claim was false against nine live boots. Its replacement has to
    say something a reviewer can apply, not merely something true.
    """
    assert "No central scheduler." not in instructions


def test_principle_one_names_both_halves(instructions: str) -> None:
    principle = _principle_one(instructions)
    assert "hybrid" in principle.lower()
    # The half that must never erode.
    assert "no central dispatcher deciding which agent thinks about what" in (
        principle.lower()
    )
    # The half that exists for guarantees an emergent negotiation cannot make.
    assert "durable workflow time" in principle.lower()


def test_principle_one_gives_a_test_a_reviewer_can_apply(instructions: str) -> None:
    """A principle that cannot decide a case is decoration. This one has to
    answer "does this change belong in the mesh or behind a service?".
    """
    principle = _principle_one(instructions).lower()
    assert "boundary test" in principle
    assert "which agent" in principle       # the service-side violation
    assert "durable transition" in principle  # the agent-side violation


def test_principle_one_names_the_bottleneck_being_avoided(
    instructions: str,
) -> None:
    """The Captain's actual objection. Without it the principle reads as a
    grudging concession rather than a design position, and the next reviewer
    re-litigates it.
    """
    principle = _principle_one(instructions).lower()
    assert "single point of thought" in principle


# ── the code says the same thing ──────────────────────────────────


def test_the_orchestrator_states_where_its_authority_stops() -> None:
    """#1116's acceptance: the instructions, the design docs and the production
    ownership model must describe the same contract. This is the code end.
    """
    from probos.cognitive import crew_orchestrator

    doc = inspect.getdoc(crew_orchestrator) or ""
    assert "AD-1231" in doc
    assert "durable workflow time" in doc
    # And the limit, not just the grant.
    assert "which agent is best suited" in doc


def test_the_orchestrator_does_not_claim_to_rank_agents_or_work() -> None:
    """The service-side violation named in the principle. If a future change
    adds agent selection here, this is the assertion that should be revisited
    deliberately rather than deleted quietly.
    """
    from probos.cognitive import crew_orchestrator

    doc = inspect.getdoc(crew_orchestrator) or ""
    assert "capability matching and Hebbian routing" in doc


def _principle_one(instructions: str) -> str:
    """The text of Design Principle 1, up to Principle 2."""
    start = instructions.index("1. **Agent-native OS")
    end = instructions.index("2. **Probabilistic consensus", start)
    return instructions[start:end]
