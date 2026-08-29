"""AD-1285 (#1087 / BF-687): a turn that claims a save must prove one.

2026-07-26 22:40, live, an agent replied "I wrote the finding and it's saved to
my notebook under the slug ``ward-room-escalation-decision``". No such file
exists and ``publish_finding`` never appears in the log. The turn was healthy;
a working turn produced a specific, plausible, entirely fictional slug, and
nothing marked it as suspect.

These tests cover the per-turn :class:`WriteLedger` and the guard that reads
it. The verdict is **entirely structural** -- ``assess_write_claim`` takes no
reply text at all, which is #1087's own criterion ("detection is structural
(invocation record), not string-matching the reply") and is what makes a false
positive against a truthful reply unreachable rather than merely unlikely.
Test 11 pins that signature.

PARTIAL by design: this closes the *marker* half. A turn that carried no write
marker -- the observed 22:40 turn included -- leaves ``consulted`` empty and the
guard abstains. Closing that half needs a name-addressable tool-success set out
of ``WorkItemAgenticOutcome``; see #1087.

BF-287 discipline and the AD-1284 lesson: REAL fixtures only, and no
``MagicMock(spec=...)`` for the pipeline or the ledger -- a spec'd double
auto-mocks any new public name, so an assertion passes for the wrong reason.
Every ledger value below is a real ``WriteLedger``.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

from probos.artifacts import ArtifactStore
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply  # AD-1248
from probos.cognitive.dm.write_ledger import (
    WRITE_CHANNEL_ARTIFACT,
    WRITE_CHANNEL_NOTEBOOK,
    ClaimVerdict,
    WriteLedger,
    assess_write_claim,
    disclosure_for,
)
from probos.config import WriteClaimGuardConfig

#: A reply carrying a notebook marker. The marker is what makes the channel
#: run; the prose around it is never read by the guard.
MARKED_REPLY = (
    "Noted. [NOTEBOOK finding]Ward room escalation decision.[/NOTEBOOK]"
)

#: What ``_FakeProactiveLoop`` leaves behind once it strips the marker.
CLEANED_REPLY = "Noted. Ward room escalation decision."

#: The sentence appended when a channel ran and wrote nothing.
DISCLOSURE_FRAGMENT = "A durable write was attempted on this turn"


# --------------------------------------------------------------------------- #
# BF-287 real-but-fake stubs                                                   #
# --------------------------------------------------------------------------- #


class _FakeProactiveLoop:
    """Real attribute object standing in for ``ProactiveLoop``.

    Only ``extract_and_execute_notebooks`` is needed: it returns the
    ``(cleaned, actions)`` pair whose ``actions`` half was previously logged
    and dropped. ``actions`` is what the ledger now reads.
    """

    def __init__(self, *, actions: list | None = None, raises: bool = False) -> None:
        self._actions = list(actions or [])
        self._raises = raises
        self.calls: list[str] = []

    async def extract_and_execute_notebooks(self, agent, text: str):
        self.calls.append(text)
        if self._raises:
            raise RuntimeError("notebook store unavailable")
        cleaned = text.replace("[NOTEBOOK finding]", "").replace(
            "[/NOTEBOOK]", ""
        ).strip()
        return cleaned, self._actions


class _FakeAttachmentStore:
    """AD-797's blob sink. ``replace_with_stubs`` awaits ``write`` and uses the
    returned path for logging only."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def write(
        self, content_hash: str, blob: bytes, mime: str,
        *, origin: str = "chat_attachment",
    ) -> Path:
        self.blobs[content_hash] = blob
        return Path("/fake") / content_hash


def _runtime(*, proactive=None, guard_enabled: bool = True) -> SimpleNamespace:
    """A runtime carrying a REAL ``WriteClaimGuardConfig`` and nothing else.

    Every other pipeline step honest-degrades on the missing attribute, which
    is the point: a ship with no write channel wired must be byte-identical.
    """
    cfg = SimpleNamespace(
        write_claim_guard=WriteClaimGuardConfig(enabled=guard_enabled),
    )
    return SimpleNamespace(config=cfg, proactive_loop=proactive)


def _make_ctx(*, runtime, response_text: str) -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id="a1", agent_type="yeoman"),
        agent_id="a1",
        callsign="Yeo",
        req_message="Please write that finding down.",
        reply=DmReply(body=response_text),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="Please write that finding down.",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="t1",
    )


# --------------------------------------------------------------------------- #
# 1. the ledger value                                                          #
# --------------------------------------------------------------------------- #


def test_default_ledger_is_unevaluated_and_empty() -> None:
    """AD-1269 distinction: a ledger nobody populated must not read as
    "no write occurred"."""
    ledger = WriteLedger()
    assert ledger.evaluated is False
    assert ledger.consulted == frozenset()
    assert ledger.wrote == frozenset()
    assert ledger.wrote_nothing == frozenset()


def test_consulted_with_wrote_true_records_both_sets() -> None:
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=True)
    assert ledger.consulted == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert ledger.wrote == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert ledger.evaluated is True
    assert ledger.wrote_nothing == frozenset()


def test_consulted_with_wrote_false_records_consulted_only() -> None:
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
    assert ledger.consulted == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert ledger.wrote == frozenset()
    assert ledger.evaluated is True
    assert ledger.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})


def test_consulted_with_is_copy_on_write() -> None:
    """Frozen + copy-on-write, so a step cannot retroactively mutate a value
    another step already read."""
    original = WriteLedger()
    derived = original.consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=True)

    assert original.consulted == frozenset()
    assert original.wrote == frozenset()
    assert original.evaluated is False
    assert derived is not original


def test_two_channels_accumulate_independently() -> None:
    ledger = (
        WriteLedger()
        .consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
        .consulted_with(WRITE_CHANNEL_ARTIFACT, wrote=True)
    )
    assert ledger.consulted == frozenset(
        {WRITE_CHANNEL_NOTEBOOK, WRITE_CHANNEL_ARTIFACT}
    )
    assert ledger.wrote == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert ledger.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})


def test_recording_the_same_channel_twice_is_idempotent() -> None:
    """Sets, not counters. step_4i can reach ``consulted_with`` from both the
    normal path and the ``except`` path on one turn."""
    once = WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
    twice = once.consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)

    assert len(twice.consulted) == len(once.consulted) == 1
    assert len(twice.wrote) == len(once.wrote) == 0
    assert twice.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})


# --------------------------------------------------------------------------- #
# 2. the verdict                                                               #
# --------------------------------------------------------------------------- #


def test_unpopulated_ledger_abstains() -> None:
    """The false-positive floor.

    No channel ran, so there is nothing to contradict. A ship with no write
    channel wired -- and every turn that carried no write marker -- must be
    byte-identical, so "nobody ran" can never produce a flag.
    """
    assert assess_write_claim(WriteLedger()) is ClaimVerdict.ABSTAIN


def test_a_genuine_write_is_never_flagged() -> None:
    """The acceptance criterion, asserted directly: a genuinely successful
    write is never flagged."""
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=True)
    assert assess_write_claim(ledger) is ClaimVerdict.ABSTAIN


def test_channel_that_ran_and_wrote_nothing_is_flagged() -> None:
    """The defect this AD closes: the marker ran, the write did not land, and
    step_4i then strips the marker -- leaving a reply that reads exactly like a
    successful save."""
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
    assert assess_write_claim(ledger) is ClaimVerdict.MARKER_WROTE_NOTHING


def test_a_sibling_write_does_not_mask_a_channel_that_wrote_nothing() -> None:
    """Masking regression, and the reason the check is ``consulted - wrote``.

    A ledger-wide ``if self.wrote`` returns ABSTAIN here, because the artifact
    channel wrote. The notebook channel still ran and still produced nothing,
    and the reply still confabulates that save. This test is what forbids the
    ledger-wide shape.
    """
    ledger = (
        WriteLedger()
        .consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
        .consulted_with(WRITE_CHANNEL_ARTIFACT, wrote=True)
    )
    assert ledger.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert assess_write_claim(ledger) is ClaimVerdict.MARKER_WROTE_NOTHING


def test_assess_write_claim_takes_the_ledger_and_nothing_else() -> None:
    """The property the whole revision turns on: the verdict must never become
    text-dependent.

    Rev 1 carried a second branch that read the reply, and on the live vessel
    -- where ``publish_finding_enabled`` and ``dm_agentic.enabled`` are both
    true -- a genuine tool save leaves this ledger empty, so that branch
    appended "unconfirmed" to a TRUE statement. Reading no text at all deletes
    that false-positive class rather than narrowing it.
    """
    params = list(inspect.signature(assess_write_claim).parameters)
    assert params == ["ledger"]


# --------------------------------------------------------------------------- #
# 3. the disclosure                                                            #
# --------------------------------------------------------------------------- #


def test_disclosure_does_not_match_the_capability_gap_regex() -> None:
    """A match on ``decomposer._CAPABILITY_GAP_RE`` would misclassify the turn
    as a capability gap and trigger self-modification. The REAL compiled regex
    is imported rather than restated."""
    text = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    assert not _CAPABILITY_GAP_RE.search(text), (
        "disclosure matches the capability-gap regex: "
        f"{_CAPABILITY_GAP_RE.search(text)}"
    )


def test_disclosure_is_non_empty_and_separated() -> None:
    text = disclosure_for(ClaimVerdict.MARKER_WROTE_NOTHING)
    assert text.startswith("\n\n")
    assert text.strip()


def test_abstain_has_no_disclosure() -> None:
    assert disclosure_for(ClaimVerdict.ABSTAIN) == ""


# --------------------------------------------------------------------------- #
# 4. pipeline integration -- the seam, not the halves                          #
# --------------------------------------------------------------------------- #


def test_notebook_marker_that_wrote_nothing_reaches_the_captain_marked() -> None:
    """The one test that crosses 4i -> ledger -> 4m.

    A marker present, the channel executed, zero actions produced. The tag is
    stripped, so without this the Captain sees a reply that reads exactly like
    a successful save.
    """
    proactive = _FakeProactiveLoop(actions=[])
    ctx = _make_ctx(runtime=_runtime(proactive=proactive), response_text=MARKED_REPLY)

    asyncio.run(DmReplyPipeline(ctx).run())

    assert proactive.calls, "the notebook channel must have actually run"
    assert ctx.write_ledger.consulted == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert ctx.write_ledger.wrote == frozenset()
    assert DISCLOSURE_FRAGMENT in ctx.response_text
    assert "[NOTEBOOK" not in ctx.response_text


def test_notebook_channel_that_raised_is_flagged_through_the_pipeline() -> None:
    """The ``except`` path in step_4i records ``wrote=False``.

    A raising store is the same hazard as an empty ``actions`` list -- the
    marker is unwrapped by the safety net either way -- so it must reach the
    Captain marked too.
    """
    proactive = _FakeProactiveLoop(raises=True)
    ctx = _make_ctx(runtime=_runtime(proactive=proactive), response_text=MARKED_REPLY)

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert DISCLOSURE_FRAGMENT in ctx.response_text
    assert "[NOTEBOOK" not in ctx.response_text


def test_notebook_marker_that_wrote_leaves_the_reply_alone() -> None:
    """One action produced -> a real write -> no disclosure, and the body is
    otherwise unchanged."""
    proactive = _FakeProactiveLoop(
        actions=[{"type": "notebook_write", "topic": "ward-room-escalation"}]
    )
    ctx = _make_ctx(runtime=_runtime(proactive=proactive), response_text=MARKED_REPLY)

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.wrote == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert DISCLOSURE_FRAGMENT not in ctx.response_text
    assert ctx.response_text == CLEANED_REPLY


def test_a_deduped_notebook_write_is_not_flagged() -> None:
    """AD-550/AD-911 dedup suppresses a write because a highly-similar entry
    already exists, so the note IS durably present and "I saved it" is true.
    Flagging it would be the false-positive class this guard must never
    produce."""
    proactive = _FakeProactiveLoop(
        actions=[
            {
                "type": "notebook_suppressed",
                "topic": "ward-room-escalation",
                "reason": "near_duplicate",
            }
        ]
    )
    ctx = _make_ctx(runtime=_runtime(proactive=proactive), response_text=MARKED_REPLY)

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.wrote == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert DISCLOSURE_FRAGMENT not in ctx.response_text


def test_an_unrecognised_notebook_action_does_not_count_as_a_write() -> None:
    """The ledger matches on action TYPE, not list truthiness. A future action
    kind that is not a write must not silently satisfy the channel -- that is
    the failure truthiness would have hidden."""
    proactive = _FakeProactiveLoop(actions=[{"type": "notebook_queued"}])
    ctx = _make_ctx(runtime=_runtime(proactive=proactive), response_text=MARKED_REPLY)

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.wrote == frozenset()
    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert DISCLOSURE_FRAGMENT in ctx.response_text


def test_runtime_without_a_proactive_loop_is_byte_identical() -> None:
    """No channel exists, which is a different fact from "a channel ran and
    wrote nothing". The unwired ship stays byte-identical, and the safety net
    still unwraps the marker so the Captain never sees a raw block."""
    ctx = _make_ctx(runtime=_runtime(), response_text=MARKED_REPLY)

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.consulted == frozenset()
    assert DISCLOSURE_FRAGMENT not in ctx.response_text
    assert "[NOTEBOOK" not in ctx.response_text
    assert ctx.response_text == CLEANED_REPLY


def test_guard_disabled_is_byte_identical() -> None:
    off_ctx = _make_ctx(
        runtime=_runtime(
            proactive=_FakeProactiveLoop(actions=[]), guard_enabled=False,
        ),
        response_text=MARKED_REPLY,
    )
    asyncio.run(DmReplyPipeline(off_ctx).run())
    assert off_ctx.response_text == CLEANED_REPLY

    # And the same fixture with the guard ON does append, so the assertion
    # above is discriminating rather than vacuous.
    on_ctx = _make_ctx(
        runtime=_runtime(
            proactive=_FakeProactiveLoop(actions=[]), guard_enabled=True,
        ),
        response_text=MARKED_REPLY,
    )
    asyncio.run(DmReplyPipeline(on_ctx).run())
    assert on_ctx.response_text != off_ctx.response_text


def test_a_flagged_turn_is_logged_and_an_abstaining_turn_is_not(caplog) -> None:
    """The turn is marked in the log so this is diagnosable after the fact, and
    the marker names the channels that ran without writing.

    The negative half matters as much: an abstaining turn must stay silent, or
    the marker is useless for grepping. The reply body is never logged.
    """
    caplog.set_level("WARNING", logger="probos.cognitive.dm.reply_pipeline")

    quiet = _make_ctx(
        runtime=_runtime(
            proactive=_FakeProactiveLoop(
                actions=[{"type": "notebook_write", "topic": "s"}]
            )
        ),
        response_text=MARKED_REPLY,
    )
    asyncio.run(DmReplyPipeline(quiet).run())
    assert not [r for r in caplog.records if "AD-1285" in r.getMessage()]

    caplog.clear()
    loud = _make_ctx(
        runtime=_runtime(proactive=_FakeProactiveLoop(actions=[])),
        response_text=MARKED_REPLY,
    )
    asyncio.run(DmReplyPipeline(loud).run())
    marked = [r for r in caplog.records if "AD-1285" in r.getMessage()]
    assert len(marked) == 1
    message = marked[0].getMessage()
    assert "write-claim guard" in message
    assert "marker_wrote_nothing" in message
    assert "ran_without_writing=['notebook']" in message
    assert "agent=a1" in message
    assert "Ward room escalation decision" not in message


def test_an_extracted_artifact_never_flags_the_turn(tmp_path) -> None:
    """A persisted artifact records ``wrote=True`` and never flags the turn.

    Crosses 4f -> ledger -> 4m; a mutation to ``wrote=False`` at the call site
    is invisible to every other suite.
    """
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            write_claim_guard=WriteClaimGuardConfig(enabled=True),
            cognitive=SimpleNamespace(artifact_fenced_threshold_lines=40),
        ),
        artifact_store=ArtifactStore(tmp_path / "artifacts.db"),
        attachment_store=_FakeAttachmentStore(),
        proactive_loop=None,
    )
    ctx = _make_ctx(
        runtime=runtime,
        response_text=(
            "Here is the file:\n"
            '<artifact name="hello.md" mime="text/markdown">\n'
            "# Hello\n\nWorld\n"
            "</artifact>\n"
            "Anything else?"
        ),
    )

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.wrote == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert DISCLOSURE_FRAGMENT not in ctx.response_text
    assert "[Artifact: hello.md v1 - 3 lines, text/markdown]" in ctx.response_text


class _FailingArtifactStore:
    """Extraction reaches persistence, and only persistence fails.

    ``list_thread_latest`` must work, or ``step_4f`` bails at its first call
    and the test passes without ever reaching the ledger -- which is how the
    first draft of these two tests passed for the wrong reason.
    """

    def list_thread_latest(self, thread_id):
        return []

    def add_version(self, *args, **kwargs):
        raise RuntimeError("artifact store unavailable")


def _artifact_runtime(store) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            write_claim_guard=WriteClaimGuardConfig(enabled=True),
            cognitive=SimpleNamespace(artifact_fenced_threshold_lines=40),
        ),
        artifact_store=store,
        attachment_store=_FakeAttachmentStore(),
        proactive_loop=None,
    )


def test_a_marked_artifact_that_failed_to_persist_is_disclosed() -> None:
    """An explicit <artifact> tag asked for a save and nothing persisted.

    Before this, ``replace_with_stubs`` swallowed the ``add_version`` failure,
    ``_artifacts`` came back empty, the channel was never recorded, 4m
    abstained, and a FAILED artifact write reached the Captain reading exactly
    like a success -- the same shape as the notebook defect this AD exists to
    close.
    """
    ctx = _make_ctx(
        runtime=_artifact_runtime(_FailingArtifactStore()),
        response_text=(
            "Here is the file:\n"
            '<artifact name="hello.md" mime="text/markdown">\n'
            "# Hello\n\nWorld\n"
            "</artifact>\n"
            "Anything else?"
        ),
    )

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.wrote == frozenset()
    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert DISCLOSURE_FRAGMENT in ctx.response_text


def test_a_passive_fenced_lift_that_failed_to_persist_is_not_disclosed() -> None:
    """The control for the test above, and the reason it is gated on the tag.

    Pass 2 lifts ANY fenced block of >= 40 lines even though the agent never
    claimed to save it. Disclosing a failure there would append a save
    disclosure to a reply that described no save -- the false-positive class
    this revision deleted Branch 2 to remove.
    """
    fenced = "```python\n" + "\n".join(f"x = {i}" for i in range(60)) + "\n```"
    ctx = _make_ctx(
        runtime=_artifact_runtime(_FailingArtifactStore()),
        response_text=f"Here is some code:\n{fenced}\nAnything else?",
    )

    asyncio.run(DmReplyPipeline(ctx).run())

    assert ctx.write_ledger.consulted == frozenset()
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert DISCLOSURE_FRAGMENT not in ctx.response_text


# --------------------------------------------------------------------------- #
# 5. ordering                                                                  #
# --------------------------------------------------------------------------- #

def test_guard_runs_after_the_deliberate_re_roll_and_before_episodic_store() -> None:
    """After 4j so the guard reads the text the Captain will actually see;
    before 5 so the stored episode carries the corrected text. Absent from the
    escalation subset: the group sink is unverified (#1087 forward marker)."""
    pipeline = DmReplyPipeline.__new__(DmReplyPipeline)
    names = [s.__name__ for s in DmReplyPipeline._full_steps(pipeline)]

    assert "step_4m_write_claim_guard" in names
    assert names.index("step_4j_deliberate_parse") < names.index(
        "step_4m_write_claim_guard"
    )
    assert names.index("step_4m_write_claim_guard") < names.index(
        "step_5_episodic_store"
    )

    escalation = [s.__name__ for s in DmReplyPipeline._escalation_steps(pipeline)]
    assert "step_4m_write_claim_guard" not in escalation
