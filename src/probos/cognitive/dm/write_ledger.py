"""AD-1285 (#1087 / BF-687): the per-turn record of what was actually written.

A reply that claims a durable save must be checkable against something. Before
this module there was nothing to check against: the agentic loop's
``tool_calls``/``tool_results`` die at ``WorkItemAgenticOutcome`` (BF-793), the
``ToolFailures`` projection cannot name a success once ``to_wire`` drops its
tombstones, and ``step_4i_notebook_parse`` logged its action count and threw it
away. This is the missing record.

An unpopulated ledger abstains. "No channel ran" and "a channel ran and wrote
nothing" are deliberately different values, for the AD-1269 reason -- a verdict
of *nothing happened* must never be reachable from a field nobody set.

This ledger sees the **marker** channels only. The AD-1065 tool loop runs
upstream of the pipeline and writes without telling it, so a ``wrote`` set that
is empty means "no marker channel wrote", never "this turn wrote nothing". No
verdict here may assume otherwise. Closing that half needs a name-addressable
tool-success set carried out of ``WorkItemAgenticOutcome``; see #1087.

AD-1295 (#1087) closed that half. The tool loop now declares itself through
``WRITE_CHANNEL_FINDING``, so an empty ``wrote`` set on a turn where the tool
channel WAS consulted does mean "this turn wrote nothing" -- for that channel.
The paragraph above still governs every channel that has not declared itself:
the verdict is per channel, and silence from one is not evidence about another.

Layer: COGNITIVE, and runtime-free by construction -- no runtime import, no LLM
client, no store. A pure value plus a pure function, so the verdict is testable
without a ship.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

__all__ = [
    "WRITE_CHANNEL_NOTEBOOK",
    "WRITE_CHANNEL_ARTIFACT",
    "WRITE_CHANNEL_FINDING",
    "WriteLedger",
    "ClaimVerdict",
    "assess_write_claim",
    "disclosure_for",
]

#: Durable-write channels. The ledger is keyed by channel NAME rather than by a
#: fixed set of fields so a later slice can add ``publish_finding`` without
#: changing the value's shape.
WRITE_CHANNEL_NOTEBOOK = "notebook"
WRITE_CHANNEL_ARTIFACT = "artifact"
#: AD-1295 (#1087): the AD-1065 tool-loop durable-write channel -- the "later
#: slice" the line above anticipated. It cost exactly this constant: no change
#: to :class:`WriteLedger`, to :func:`assess_write_claim`, or to the
#: disclosures, which was the whole point of keying by name.
WRITE_CHANNEL_FINDING = "finding"


@dataclass(frozen=True)
class WriteLedger:
    """What this turn consulted, and what this turn actually wrote.

    Frozen and copy-on-write: every mutator returns a new value, so a step
    cannot retroactively change a value another step already read. The set
    fields are ``frozenset`` for the same reason ``ToolFailures`` uses a sorted
    tuple rather than a ``Mapping`` (``dm_reply.py:212``) -- a mutable field on
    a nominally frozen dataclass retains the caller's object.
    """

    #: Channels whose step actually ran its execution path this turn.
    consulted: frozenset[str] = frozenset()
    #: Channels that produced at least one write.
    wrote: frozenset[str] = frozenset()

    @property
    def evaluated(self) -> bool:
        """Whether any durable-write channel ran on this turn."""
        return bool(self.consulted)

    def consulted_with(self, channel: str, *, wrote: bool) -> "WriteLedger":
        """Record that ``channel`` ran, and whether it wrote."""
        return WriteLedger(
            consulted=self.consulted | {channel},
            wrote=(self.wrote | {channel}) if wrote else self.wrote,
        )

    @property
    def wrote_nothing(self) -> frozenset[str]:
        """Channels that ran and produced no write.

        Per channel, deliberately. A turn that persisted an artifact and ran a
        notebook channel that wrote nothing still confabulates the notebook,
        and a ledger-wide ``if self.wrote`` would mask it.
        """
        return self.consulted - self.wrote


class ClaimVerdict(enum.Enum):
    """The outcomes of comparing a turn against its own write ledger."""

    #: Nothing to say: no channel ran, or every channel that ran also wrote.
    ABSTAIN = "abstain"
    #: A write channel ran and produced nothing. Structural; no text is read.
    MARKER_WROTE_NOTHING = "marker_wrote_nothing"


def assess_write_claim(ledger: WriteLedger) -> ClaimVerdict:
    """Compare what this turn ran against what it wrote.

    Takes no reply text. The verdict is entirely structural, which is the
    #1087 criterion -- "detection is structural (invocation record), not
    string-matching the reply" -- and is what makes a false positive against a
    truthful reply unreachable rather than merely unlikely.

    Abstains when no channel ran, so a turn with no write marker is
    byte-identical.
    """
    if not ledger.evaluated:
        return ClaimVerdict.ABSTAIN
    if ledger.wrote_nothing:
        return ClaimVerdict.MARKER_WROTE_NOTHING
    return ClaimVerdict.ABSTAIN


#: The appended sentence, per verdict. Deliberately free of every phrase in
#: ``decomposer._CAPABILITY_GAP_RE`` -- a match there would misclassify the turn
#: as a capability gap and trigger self-modification. Guarded by a test.
#:
#: Phrased so it stays true when the reply made no prose claim at all: the
#: verdict reads no text, so it cannot know whether one was made.
_DISCLOSURES: dict[ClaimVerdict, str] = {
    ClaimVerdict.MARKER_WROTE_NOTHING: (
        "\n\n[A durable write was attempted on this turn and did not "
        "complete — nothing was saved.]"
    ),
}


def disclosure_for(verdict: ClaimVerdict) -> str:
    """The honest sentence appended for ``verdict``; empty for ABSTAIN."""
    return _DISCLOSURES.get(verdict, "")
