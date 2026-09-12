"""BF-866 (#1338 items 2-4): the three artifact-channel seams in AD-1285.

AD-1285 gave the write-claim guard a marker half. Adversarial review of the
shipped diff found three seams in it, all reproduced at ``f6ffd642``:

* **item 2** — ``<artifact>`` markup inside a fenced *example* was extracted by
  pass 1 and, on persistence failure, disclosed. Probe at HEAD:
  ``ARTIFACT_TAG_INSIDE_FENCE -> consulted=['artifact'] wrote_nothing=['artifact']
  disclosure=True``. An agent explaining the markup was told its save failed.
* **item 3** — ``step_4f`` returned at ``if not extracted: return`` before the
  marker fallback, and the extractor deliberately skips a tag with a missing
  ``mime``. Probe at HEAD: ``MALFORMED_TAG_NO_MIME -> consulted=[] wrote=[]
  wrote_nothing=[] disclosure=False`` — the turn read as unassessed.
* **item 4** — any non-empty persisted list recorded ``wrote=True``. Probe at
  HEAD: ``PARTIAL_SUCCESS_ONE_OF_TWO -> wrote=['artifact'] wrote_nothing=[]
  disclosure=False``, with the unsaved block still in the Captain-visible reply.

**The governing constraint is that a false accusation is the severe failure.**
AD-1285 deleted an entire branch rather than narrow it, because a disclosure on
a truthful reply trains the Captain to ignore the signal and costs the control
itself. Every fix here fails toward ABSTAIN:

* item 2 removes an accusation path outright;
* item 3 accuses only on a fence-free tag that persisted nothing — true by
  construction, and silent again the moment the tag is inside a fence;
* item 4's partial verdict is scoped to explicit pass-1 tags, so
  ``explicit_persisted`` and ``marked`` come from the *same* fence-aware scan
  and the verdict is unreachable when every save the agent asked for landed.
  ``test_a_failed_passive_lift_beside_a_persisted_tag_is_not_partial`` is the
  test that pins that, and it is the one that matters most in this file.

BF-287 discipline: REAL fixtures, no ``MagicMock(spec=...)``, and every double
below takes the store's real keyword-only signature rather than ``**kwargs`` —
a permissive double passes for the wrong reason when a signature drifts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.artifacts import Artifact, ArtifactStore
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE, is_capability_gap
from probos.cognitive.dm.artifact_extractor import (
    ArtifactPersistCounts,
    count_explicit_artifact_markers,
    extract_artifacts,
    has_explicit_artifact_marker,
    replace_with_stubs,
)
from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply
from probos.cognitive.dm.write_ledger import (
    WRITE_CHANNEL_ARTIFACT,
    WRITE_CHANNEL_NOTEBOOK,
    ClaimVerdict,
    WriteLedger,
    assess_write_claim,
    disclosure_for,
)
from probos.config import RecordsConfig, WriteClaimGuardConfig
from probos.dm_reply import ToolFailures, call_signature, failure_key, require_rendered
from probos.knowledge.records_store import RecordsStore
from probos.proactive import ProactiveCognitiveLoop
from probos.types import Episode

#: The AD-1285 total-failure sentence.
NOTHING_FRAGMENT = "A durable write was attempted on this turn"
#: The BF-866 partial-failure sentence.
PARTIAL_FRAGMENT = "at least one did not complete"


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #


class _FakeAttachmentStore:
    """AD-797's blob sink, with ``write``'s real signature."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def write(
        self, content_hash: str, blob: bytes, mime: str,
        *, origin: str = "chat_attachment",
    ) -> Path:
        self.blobs[content_hash] = blob
        return Path("/fake") / content_hash


class _FailingArtifactStore:
    """Extraction reaches persistence, and only persistence fails.

    ``list_thread_latest`` must work, or ``step_4f`` bails at its first call and
    the test passes without ever reaching the ledger.
    """

    def list_thread_latest(self, thread_id: str) -> list[Artifact]:
        return []

    def add_version(
        self, *, thread_id: str, name: str, content_hash: str, mime: str,
        size_bytes: int, created_by: str,
    ) -> Artifact:
        raise RuntimeError("artifact store unavailable")


class _SelectivelyFailingStore:
    """Persists everything except the names in ``fail_names``.

    Real ``ArtifactStore`` underneath, so a persisted row is a real row with a
    real auto-assigned version — the partial case is only meaningful if the
    half that succeeds actually succeeds.
    """

    def __init__(self, db_path: Path, fail_names: set[str]) -> None:
        self._real = ArtifactStore(db_path)
        self._fail_names = set(fail_names)
        self.attempted: list[str] = []

    def list_thread_latest(self, thread_id: str) -> list[Artifact]:
        return self._real.list_thread_latest(thread_id)

    def add_version(
        self, *, thread_id: str, name: str, content_hash: str, mime: str,
        size_bytes: int, created_by: str,
    ) -> Artifact:
        self.attempted.append(name)
        if name in self._fail_names:
            raise RuntimeError(f"artifact store unavailable for {name}")
        return self._real.add_version(
            thread_id=thread_id, name=name, content_hash=content_hash,
            mime=mime, size_bytes=size_bytes, created_by=created_by,
        )


def _runtime(store) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            write_claim_guard=WriteClaimGuardConfig(enabled=True),
            cognitive=SimpleNamespace(artifact_fenced_threshold_lines=40),
        ),
        artifact_store=store,
        attachment_store=_FakeAttachmentStore(),
        proactive_loop=None,
    )


def _make_ctx(runtime: SimpleNamespace, response_text: str) -> DmReplyContext:
    return DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id="a1", agent_type="yeoman"),
        agent_id="a1",
        callsign="Yeo",
        req_message="Please save that.",
        reply=DmReply(body=response_text),
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text="Please save that.",
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="t1",
    )


def _run(store, response_text: str) -> DmReplyContext:
    ctx = _make_ctx(_runtime(store), response_text)
    asyncio.run(DmReplyPipeline(ctx).run())
    return ctx


def _long_fence(lang: str = "python", lines: int = 60) -> str:
    body = "\n".join(f"x = {i}" for i in range(lines))
    return f"```{lang}\n{body}\n```"


#: An agent explaining the markup rather than asking for a save.
FENCED_EXPLAINER = (
    "To save a file, emit a tag like this:\n"
    "```markdown\n"
    '<artifact name="example.md" mime="text/markdown">\n'
    "# Your content here\n"
    "</artifact>\n"
    "```\n"
    "That is all it takes."
)

#: An explicit save request the extractor refuses: no ``mime``.
MALFORMED_TAG = (
    "Saving that for you now.\n"
    '<artifact name="notes.md">\n'
    "# Notes\n"
    "</artifact>\n"
    "Done."
)


def _two_tags(first: str = "first.md", second: str = "second.md") -> str:
    return (
        "Here are both files:\n"
        f'<artifact name="{first}" mime="text/markdown">\n'
        "# First\n"
        "</artifact>\n"
        f'<artifact name="{second}" mime="text/markdown">\n'
        "# Second\n"
        "</artifact>\n"
        "Both saved."
    )


# --------------------------------------------------------------------------- #
# item 2: a tag inside a fenced span is an example, not a save request         #
# --------------------------------------------------------------------------- #


def test_a_tag_inside_a_fence_is_not_extracted() -> None:
    """At HEAD pass 1 extracted ``example.md`` out of the fenced example."""
    assert extract_artifacts(FENCED_EXPLAINER, fenced_threshold_lines=40) == []


def test_a_tag_inside_a_fence_is_not_a_marker() -> None:
    """The detector and pass-1 admission must agree, or the fallback disclosure
    fires on content the extractor never touched."""
    assert has_explicit_artifact_marker(FENCED_EXPLAINER) is False
    assert count_explicit_artifact_markers(FENCED_EXPLAINER) == 0


def test_a_fenced_example_that_fails_to_persist_is_not_disclosed() -> None:
    """Crosses 4f -> ledger -> 4m. The whole point of item 2: the guard must
    abstain on a reply that described no save."""
    ctx = _run(_FailingArtifactStore(), FENCED_EXPLAINER)

    assert ctx.write_ledger.consulted == frozenset()
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert NOTHING_FRAGMENT not in ctx.response_text
    assert PARTIAL_FRAGMENT not in ctx.response_text


def test_a_tag_whose_body_contains_a_fence_is_still_extracted() -> None:
    """Containment, not overlap.

    A legitimate ``<artifact>`` holding a code fence *encloses* that fence
    rather than sitting inside it. Testing overlap instead would silently stop
    extracting every artifact that contains fenced code — the regression this
    pins, and the reason the check is not the obvious span-intersection.
    """
    text = (
        '<artifact name="doc.md" mime="text/markdown">\n'
        "# Doc\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "</artifact>"
    )

    extracted = extract_artifacts(text, fenced_threshold_lines=40)

    assert [e.name for e in extracted] == ["doc.md"]
    assert extracted[0].explicit is True
    assert count_explicit_artifact_markers(text) == 1


def test_a_long_fenced_example_is_still_eligible_for_the_passive_lift() -> None:
    """Declining to read tags out of a fence must not exempt the fence itself
    from pass 2 — that would be a second, opposite regression."""
    fenced = (
        "```python\n"
        '<artifact name="example.md" mime="text/markdown">\n'
        + "\n".join(f"x = {i}" for i in range(60))
        + "\n</artifact>\n```"
    )

    extracted = extract_artifacts(fenced, fenced_threshold_lines=40)

    assert len(extracted) == 1
    assert extracted[0].explicit is False, "a lifted fence is not a save request"


# --------------------------------------------------------------------------- #
# item 2b: the other markdown "this is an example" forms (BF-866b)             #
# --------------------------------------------------------------------------- #

#: The tag every variant below quotes. Multi-line, as an agent would write it.
_QUOTED_TAG = '<artifact name="a.md" mime="text/markdown">\n# x\n</artifact>'
#: Single-line form, for the inline-code variants.
_QUOTED_TAG_1L = '<artifact name="a.md" mime="text/markdown"># x</artifact>'

#: Each of these was ``marker=1 -> disclosure=True`` before BF-866b: the guard
#: told the Captain a save had failed for text that was only explanatory
#: markup. ``_FENCE_RE`` matched triple backticks and nothing else.
NON_CLAIM_VARIANTS: dict[str, str] = {
    "tilde_fence": f"To save a file, emit:\n~~~markdown\n{_QUOTED_TAG}\n~~~\nDone.",
    "long_tilde_fence": f"Emit:\n~~~~\n{_QUOTED_TAG}\n~~~~\nDone.",
    "indented_code": (
        "To save a file, emit:\n\n"
        + "\n".join("    " + ln for ln in _QUOTED_TAG.split("\n"))
        + "\n\nDone."
    ),
    "tab_indented_code": (
        "To save a file, emit:\n\n"
        + "\n".join("\t" + ln for ln in _QUOTED_TAG.split("\n"))
        + "\n\nDone."
    ),
    "unterminated_backtick_fence": f"To save a file, emit:\n```markdown\n{_QUOTED_TAG}\n",
    "unterminated_tilde_fence": f"To save a file, emit:\n~~~markdown\n{_QUOTED_TAG}\n",
    "inline_backticks": f"To save a file, emit `{_QUOTED_TAG_1L}` and you are done.",
    "double_inline_backticks": f"Emit ``{_QUOTED_TAG_1L}`` to save.",
}

#: The other half of the same detector: replies that ARE save requests and must
#: stay disclosable. Widening the span set is only correct if it does not also
#: swallow these.
CLAIM_CONTROLS: dict[str, str] = {
    "bare_tag": f"Saving that now.\n{_QUOTED_TAG}\nDone.",
    "tag_body_holds_a_fence": (
        '<artifact name="doc.md" mime="text/markdown">\n'
        "# Doc\n```python\nx = 1\n```\n</artifact>"
    ),
    "tag_body_holds_a_tilde_fence": (
        '<artifact name="doc.md" mime="text/markdown">\n'
        "# Doc\n~~~python\nx = 1\n~~~\n</artifact>"
    ),
    "tag_body_holds_inline_code": (
        '<artifact name="doc.md" mime="text/markdown">\n'
        "Use the `foo` helper.\n</artifact>"
    ),
    "tag_after_a_closed_fence": (
        "For example:\n```python\nx = 1\n```\nAnd here is the real one:\n"
        f"{_QUOTED_TAG}"
    ),
    "tag_after_a_lone_prose_backtick": (
        # An unterminated INLINE backtick is literal text, not a code span:
        # extending it to end of text would drop real saves out of ordinary
        # prose that quoted nothing. Only an unterminated FENCE runs to EOF.
        f"The `<artifact> tag is how you save.\n{_QUOTED_TAG}"
    ),
    "tag_between_a_lone_backtick_and_a_later_literal": (
        # The lone backtick must not pair with the one before ``foo`` across
        # two blank lines and swallow the save request between them. A PAIRED
        # literal on the first line does not discriminate here: the non-greedy
        # match closes on the same line and the blank-line bound never runs.
        "The `<artifact> tag is how you save.\n\n"
        f"{_QUOTED_TAG}\n\nUse `foo` afterwards."
    ),
    "tag_indented_but_continuing_a_paragraph": (
        # No blank line before the indent, so this is a wrapped paragraph
        # rather than a code block.
        "Saving that now:\n"
        + "\n".join("    " + ln for ln in _QUOTED_TAG.split("\n"))
    ),
}


@pytest.mark.parametrize("name", sorted(NON_CLAIM_VARIANTS))
def test_a_quoted_tag_variant_is_not_a_marker(name: str) -> None:
    """Before BF-866b each of these counted as an explicit save request,
    because the span detector matched ``` and nothing else."""
    text = NON_CLAIM_VARIANTS[name]
    assert text.count("<artifact ") == 1, "fixture no longer quotes a tag"

    assert count_explicit_artifact_markers(text) == 0
    assert has_explicit_artifact_marker(text) is False
    assert extract_artifacts(text, fenced_threshold_lines=40) == []


@pytest.mark.parametrize("name", sorted(NON_CLAIM_VARIANTS))
def test_a_quoted_tag_variant_is_not_disclosed(name: str) -> None:
    """Crosses 4f -> ledger -> 4m with persistence forced to fail. The severe
    failure this AD exists to prevent is the Captain being told a save failed
    for text that only described the markup."""
    ctx = _run(_FailingArtifactStore(), NON_CLAIM_VARIANTS[name])

    assert ctx.write_ledger.consulted == frozenset()
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert NOTHING_FRAGMENT not in ctx.response_text
    assert PARTIAL_FRAGMENT not in ctx.response_text


@pytest.mark.parametrize("name", sorted(CLAIM_CONTROLS))
def test_a_real_save_request_survives_the_widened_spans(name: str) -> None:
    """The opposite regression. A span set wide enough to swallow these would
    silence the guard everywhere, which is the same control loss by the other
    route."""
    text = CLAIM_CONTROLS[name]

    assert count_explicit_artifact_markers(text) == 1

    ctx = _run(_FailingArtifactStore(), text)

    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert NOTHING_FRAGMENT in ctx.response_text


def test_an_unterminated_fence_hides_a_later_real_tag_by_design() -> None:
    """The accepted cost, pinned so it stays a decision.

    An unterminated fence runs to end of text, so a genuine ``<artifact>``
    after one is read as still-quoted and is neither saved nor disclosed. That
    is a silent miss worth one turn; the alternative -- reading the tail as
    unfenced -- accuses on every quoted example and costs the control itself.
    """
    text = f"Example:\n```markdown\nnot closed\n\nSaving now.\n{_QUOTED_TAG}"

    assert count_explicit_artifact_markers(text) == 0
    assert extract_artifacts(text, fenced_threshold_lines=40) == []

    ctx = _run(_FailingArtifactStore(), text)

    assert ctx.write_ledger.consulted == frozenset()
    assert NOTHING_FRAGMENT not in ctx.response_text


def test_a_long_tilde_example_is_still_eligible_for_the_passive_lift() -> None:
    """Pass 2 keeps using ``_FENCE_RE`` -- widening the non-claim spans must not
    change what gets lifted, only what may reach a verdict."""
    fenced = (
        "~~~python\n"
        + "\n".join(f"x = {i}" for i in range(60))
        + "\n~~~\n```python\n"
        + "\n".join(f"y = {i}" for i in range(60))
        + "\n```"
    )

    extracted = extract_artifacts(fenced, fenced_threshold_lines=40)

    assert [e.explicit for e in extracted] == [False], (
        "only the backtick fence is lifted; pass 2 is untouched by BF-866b"
    )


# --------------------------------------------------------------------------- #
# item 3: a malformed explicit tag is a save that was asked for                #
# --------------------------------------------------------------------------- #


def test_a_malformed_tag_is_skipped_by_the_extractor_but_still_counted() -> None:
    """The two halves that used to disagree, pinned side by side."""
    assert extract_artifacts(MALFORMED_TAG, fenced_threshold_lines=40) == []
    assert count_explicit_artifact_markers(MALFORMED_TAG) == 1


def test_a_malformed_explicit_tag_is_disclosed() -> None:
    """At HEAD this returned at ``if not extracted: return`` and recorded
    nothing, so the turn looked unassessed rather than attempted-and-failed."""
    ctx = _run(_FailingArtifactStore(), MALFORMED_TAG)

    assert ctx.write_ledger.consulted == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert ctx.write_ledger.wrote == frozenset()
    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert NOTHING_FRAGMENT in ctx.response_text


def test_an_empty_name_is_also_a_save_that_was_asked_for() -> None:
    """The extractor's other skip path. Same defect, different attribute.

    Note ``name="../../etc/passwd"`` does NOT reach it: ``_sanitize_name``
    strips the traversal and returns ``passwd``, so that tag is admitted
    normally. Only a name with no allowed characters left is skipped.
    """
    text = (
        "Saving.\n"
        '<artifact name="..." mime="text/plain">\nx\n</artifact>'
    )
    assert extract_artifacts(text, fenced_threshold_lines=40) == []

    ctx = _run(_FailingArtifactStore(), text)

    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert NOTHING_FRAGMENT in ctx.response_text


def test_a_malformed_tag_inside_a_fence_stays_silent() -> None:
    """Items 2 and 3 must compose. Item 3 widens what can be disclosed, so the
    fence exclusion has to hold underneath it or item 2's false accusation
    returns through the new path."""
    text = (
        "Here is what a broken tag looks like:\n"
        "```markdown\n"
        '<artifact name="notes.md">\n# Notes\n</artifact>\n'
        "```\n"
        "Note the missing mime."
    )

    ctx = _run(_FailingArtifactStore(), text)

    assert ctx.write_ledger.consulted == frozenset()
    assert NOTHING_FRAGMENT not in ctx.response_text


def test_a_reply_with_no_tag_at_all_is_byte_identical() -> None:
    """The abstain floor: no marker, nothing extracted, no channel recorded."""
    ctx = _run(_FailingArtifactStore(), "Nothing to save here.")

    assert ctx.write_ledger == WriteLedger()
    assert ctx.response_text == "Nothing to save here."


# --------------------------------------------------------------------------- #
# item 4: partial persistence is neither success nor total failure             #
# --------------------------------------------------------------------------- #


def test_replace_with_stubs_reports_explicit_attempted_and_persisted(
    tmp_path,
) -> None:
    """The counts a non-empty row list could not carry.

    The passive lift is in the fixture on purpose: without it ``len(extracted)``
    and the explicit count coincide, and the assertion cannot tell an
    explicit-scoped count from an all-artifacts one. It survived a mutation to
    ``len(extracted)`` before the fence was added.
    """
    text = _two_tags() + f"\nAnd some illustrative code:\n{_long_fence()}\n"
    extracted = extract_artifacts(text, fenced_threshold_lines=40)
    assert [e.explicit for e in extracted] == [True, True, False], (
        "premise: two explicit tags and one passive lift"
    )
    store = _SelectivelyFailingStore(tmp_path / "a.db", {"second.md"})

    _new_text, persisted, counts = asyncio.run(
        replace_with_stubs(
            text, extracted,
            artifact_store=store,
            attachment_store=_FakeAttachmentStore(),
            thread_id="t1",
            created_by="a1",
        )
    )

    assert store.attempted == ["first.md", "second.md", "artifact-1.py"], (
        "premise: the second persist must be attempted, or the count proves "
        "nothing"
    )
    assert [a.name for a in persisted] == ["first.md", "artifact-1.py"]
    assert counts == ArtifactPersistCounts(
        explicit_attempted=2, explicit_persisted=1,
    ), "the passive lift must be in neither count"


def test_partial_persistence_is_recorded_and_disclosed(tmp_path) -> None:
    """At HEAD: ``wrote=['artifact'] wrote_nothing=[] disclosure=False``.

    One artifact landed and one did not, and the Captain was told nothing while
    the unsaved block sat in the reply.
    """
    store = _SelectivelyFailingStore(tmp_path / "a.db", {"second.md"})

    ctx = _run(store, _two_tags())

    assert store.attempted == ["first.md", "second.md"]
    assert ctx.write_ledger.wrote == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert ctx.write_ledger.wrote_nothing == frozenset()
    assert ctx.write_ledger.wrote_partially == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert PARTIAL_FRAGMENT in ctx.response_text
    assert NOTHING_FRAGMENT not in ctx.response_text
    assert "[Artifact: first.md v1" in ctx.response_text


def test_both_artifacts_persisting_never_flags_partial(tmp_path) -> None:
    """The false-accusation floor for item 4: everything asked for landed."""
    store = _SelectivelyFailingStore(tmp_path / "a.db", set())

    ctx = _run(store, _two_tags())

    assert store.attempted == ["first.md", "second.md"]
    assert ctx.write_ledger.wrote_partially == frozenset()
    assert assess_write_claim(ctx.write_ledger) is ClaimVerdict.ABSTAIN
    assert PARTIAL_FRAGMENT not in ctx.response_text
    assert NOTHING_FRAGMENT not in ctx.response_text


def test_a_failed_passive_lift_beside_a_persisted_tag_is_not_partial(
    tmp_path,
) -> None:
    """**The test that matters most in this file.**

    One explicit tag (persists) and one long fenced block the agent never
    claimed to save (fails). A partial verdict counted over ALL extracted
    artifacts would fire here and accuse a reply whose every stated save
    succeeded — reintroducing, through item 4's new path, exactly the
    false-positive class AD-1285 deleted a branch to remove. The counts are
    scoped to pass-1 tags so this is unreachable rather than merely unlikely.
    """
    text = (
        '<artifact name="kept.md" mime="text/markdown">\n# Kept\n</artifact>\n'
        f"And some illustrative code:\n{_long_fence()}\n"
    )
    store = _SelectivelyFailingStore(tmp_path / "a.db", {"artifact-1.py"})

    ctx = _run(store, text)

    assert store.attempted == ["kept.md", "artifact-1.py"], (
        "premise: both must reach the store, or the passive failure this test "
        "exists to ignore never happened"
    )
    assert ctx.write_ledger.wrote == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert ctx.write_ledger.wrote_partially == frozenset()
    assert PARTIAL_FRAGMENT not in ctx.response_text
    assert NOTHING_FRAGMENT not in ctx.response_text


def test_all_explicit_tags_failing_beside_a_persisted_lift_is_total(
    tmp_path,
) -> None:
    """The opposite corner: the only thing that landed is something the agent
    never claimed. Reporting that as a write would be the confabulation this
    guard exists to catch, so the verdict is total failure, not partial."""
    text = (
        '<artifact name="claimed.md" mime="text/markdown">\n# C\n</artifact>\n'
        f"{_long_fence()}\n"
    )
    store = _SelectivelyFailingStore(tmp_path / "a.db", {"claimed.md"})

    ctx = _run(store, text)

    assert store.attempted == ["claimed.md", "artifact-1.py"]
    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert NOTHING_FRAGMENT in ctx.response_text


# --------------------------------------------------------------------------- #
# the ledger value and the new verdict                                         #
# --------------------------------------------------------------------------- #


def test_partial_is_recorded_only_alongside_a_write() -> None:
    """``partial`` without ``wrote`` is an inconsistent pair; the stronger and
    truer total-failure verdict must win rather than be downgraded."""
    ledger = WriteLedger().consulted_with(
        WRITE_CHANNEL_ARTIFACT, wrote=False, partial=True,
    )

    assert ledger.wrote_partially == frozenset()
    assert ledger.wrote_nothing == frozenset({WRITE_CHANNEL_ARTIFACT})
    assert assess_write_claim(ledger) is ClaimVerdict.MARKER_WROTE_NOTHING


def test_partial_defaults_off_so_existing_callers_are_unchanged() -> None:
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_ARTIFACT, wrote=True)

    assert ledger.wrote_partially == frozenset()
    assert assess_write_claim(ledger) is ClaimVerdict.ABSTAIN


def test_a_partial_channel_yields_the_partial_verdict() -> None:
    ledger = WriteLedger().consulted_with(
        WRITE_CHANNEL_ARTIFACT, wrote=True, partial=True,
    )

    assert ledger.wrote_nothing == frozenset()
    assert assess_write_claim(ledger) is ClaimVerdict.MARKER_WROTE_PARTIALLY


def test_a_channel_that_wrote_nothing_outranks_a_partial_sibling() -> None:
    """Both sentences are true of the turn; the Captain needs the stronger."""
    ledger = (
        WriteLedger()
        .consulted_with(WRITE_CHANNEL_ARTIFACT, wrote=True, partial=True)
        .consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
    )

    assert assess_write_claim(ledger) is ClaimVerdict.MARKER_WROTE_NOTHING


def test_partial_is_copy_on_write() -> None:
    original = WriteLedger()
    derived = original.consulted_with(
        WRITE_CHANNEL_ARTIFACT, wrote=True, partial=True,
    )

    assert original.wrote_partially == frozenset()
    assert derived is not original


def test_partial_disclosure_does_not_match_the_capability_gap_regex() -> None:
    """A match would misclassify the turn as a capability gap and trigger
    self-modification. The REAL compiled regex, not a restatement."""
    text = disclosure_for(ClaimVerdict.MARKER_WROTE_PARTIALLY)

    assert not _CAPABILITY_GAP_RE.search(text), (
        "partial disclosure matches the capability-gap regex: "
        f"{_CAPABILITY_GAP_RE.search(text)}"
    )


def test_every_verdict_except_abstain_carries_a_disclosure() -> None:
    """Adding a verdict without a sentence would silently abstain."""
    for verdict in ClaimVerdict:
        text = disclosure_for(verdict)
        if verdict is ClaimVerdict.ABSTAIN:
            assert text == ""
        else:
            assert text.startswith("\n\n") and text.strip(), verdict


class _RecordingRecordsStore(RecordsStore):
    def __init__(self, config: RecordsConfig, fail_topics: set[str]) -> None:
        super().__init__(config)
        self.fail_topics = set(fail_topics)
        self.attempted: list[str] = []
        self.similarity_results: list[dict[str, Any]] = []

    async def write_notebook(
        self, callsign: str, topic_slug: str, content: str, *,
        department: str = "", tags: list[str] | None = None,
        classification: str | None = None,
        metrics: dict[str, Any] | None = None,
        extra_frontmatter: dict[str, Any] | None = None,
    ) -> str:
        self.attempted.append(topic_slug)
        if topic_slug in self.fail_topics:
            raise RuntimeError("injected notebook persistence failure")
        return await super().write_notebook(
            callsign, topic_slug, content, department=department, tags=tags,
            classification=classification, metrics=metrics,
            extra_frontmatter=extra_frontmatter,
        )

    async def check_notebook_similarity(
        self, callsign: str, topic_slug: str, new_content: str, *,
        similarity_threshold: float = 0.8, staleness_hours: float = 72.0,
        max_scan_entries: int = 20,
    ) -> dict[str, Any]:
        result = await super().check_notebook_similarity(
            callsign, topic_slug, new_content,
            similarity_threshold=similarity_threshold,
            staleness_hours=staleness_hours, max_scan_entries=max_scan_entries,
        )
        self.similarity_results.append(dict(result))
        return result


class _CapturingEpisodicMemory:
    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)


async def _real_write_runtime(
    tmp_path: Path, fail_artifacts: set[str], fail_notebook: bool,
) -> SimpleNamespace:
    records_config = RecordsConfig(
        repo_path=str(tmp_path / "records"), enabled=True, auto_commit=False,
    )
    records = _RecordingRecordsStore(
        records_config, {"decision"} if fail_notebook else set(),
    )
    await records.initialize()
    runtime = _runtime(
        _SelectivelyFailingStore(tmp_path / "artifacts.db", fail_artifacts),
    )
    runtime.config.records = records_config
    runtime.attachment_store = FilesystemAttachmentStore(tmp_path / "attachments")
    runtime.episodic_memory = _CapturingEpisodicMemory()
    runtime._records_store = records
    runtime.proactive_loop = ProactiveCognitiveLoop()
    runtime.proactive_loop.set_runtime(runtime)
    return runtime


_FAILED_WRITE_NOTICE = (
    "\n\n[A durable write was attempted on this turn and did not "
    "complete; that write was not saved.]"
)
_NOTE_CONTENT = "Record the agreed maintenance decision for the next watch."
_NOTE_REPLY = f"Recorded. [NOTEBOOK decision]{_NOTE_CONTENT}[/NOTEBOOK]"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_artifacts, fail_notebook, long_reply", [
    pytest.param(set(), True, False, id="artifact-saved-notebook-failed"),
    pytest.param({"first.md", "second.md"}, False, False, id="notebook-saved-artifacts-failed"),
    pytest.param({"first.md", "second.md"}, True, False, id="all-writes-failed"),
    pytest.param(set(), False, False, id="all-writes-saved"),
    pytest.param({"second.md"}, True, False, id="partial-artifact-notebook-failed"),
    pytest.param({"second.md"}, False, False, id="partial-artifact-notebook-saved"),
    pytest.param(set(), True, True, id="mixed-long-history-projection"),
])
async def test_real_writes_reach_delivery_and_episode(
    tmp_path: Path, fail_artifacts: set[str], fail_notebook: bool, long_reply: bool,
) -> None:
    runtime = await _real_write_runtime(tmp_path, fail_artifacts, fail_notebook)
    records = runtime._records_store
    prefix = "Neutral context. " * 40 if long_reply else ""
    ctx = _make_ctx(runtime, prefix + _two_tags() + "\n" + _NOTE_REPLY)
    scope = "aaaaaaaaaaaa"
    failures = ToolFailures.from_mapping({
        failure_key(scope, scope, call_signature("web_search", None)): "web_search",
    })
    ctx.reply = DmReply(body=ctx.response_text, tool_failures=failures)
    assert ctx.write_ledger == WriteLedger()
    pipeline = DmReplyPipeline(ctx)

    await pipeline.run()

    assert runtime.artifact_store.attempted == ["first.md", "second.md"]
    assert records.attempted == ["decision"]
    assert len(records.similarity_results) == 1
    assert records.similarity_results[0]["action"] != "suppress"
    rows = runtime.artifact_store.list_thread_latest("t1")
    expected_blobs = {"first.md": b"# First", "second.md": b"# Second"}
    assert {row.name for row in rows} == set(expected_blobs) - fail_artifacts
    for row in rows:
        assert row.version == 1
        assert await runtime.attachment_store.read(row.content_hash) == expected_blobs[row.name]
    note = await records.read_entry("notebooks/yeoman/decision.md", "yeoman")
    if fail_notebook:
        assert note is None
    else:
        assert note is not None
        assert note["content"].strip() == _NOTE_CONTENT

    expected_failed = set()
    expected_wrote = set()
    if len(fail_artifacts) == 2:
        expected_failed.add(WRITE_CHANNEL_ARTIFACT)
    else:
        expected_wrote.add(WRITE_CHANNEL_ARTIFACT)
    if fail_notebook:
        expected_failed.add(WRITE_CHANNEL_NOTEBOOK)
    else:
        expected_wrote.add(WRITE_CHANNEL_NOTEBOOK)
    assert ctx.write_ledger.consulted == frozenset({"artifact", "notebook"})
    assert ctx.write_ledger.wrote == frozenset(expected_wrote)
    assert ctx.write_ledger.wrote_nothing == frozenset(expected_failed)
    assert ctx.write_ledger.wrote_partially == (
        frozenset({"artifact"}) if len(fail_artifacts) == 1 else frozenset()
    )
    expected_verdict = (
        ClaimVerdict.MARKER_WROTE_NOTHING if expected_failed else
        ClaimVerdict.MARKER_WROTE_PARTIALLY if len(fail_artifacts) == 1 else
        ClaimVerdict.ABSTAIN
    )
    assert assess_write_claim(ctx.write_ledger) is expected_verdict
    rendered = pipeline.build_response()["response"]
    assert require_rendered(rendered, sink="http") is rendered
    assert require_rendered(rendered, sink="thread") is rendered
    assert ctx.reply.tool_failures == failures
    assert "web_search" in rendered
    assert rendered.startswith(ctx.response_text)
    assert "nothing was saved" not in rendered
    if expected_failed:
        assert disclosure_for(expected_verdict) == _FAILED_WRITE_NOTICE
        assert ctx.response_text.endswith(_FAILED_WRITE_NOTICE)
        assert rendered.count(_FAILED_WRITE_NOTICE) == 1
        assert PARTIAL_FRAGMENT not in rendered
    elif len(fail_artifacts) == 1:
        assert ctx.response_text.endswith(disclosure_for(expected_verdict))
        assert PARTIAL_FRAGMENT in rendered
        assert NOTHING_FRAGMENT not in rendered
    else:
        assert NOTHING_FRAGMENT not in rendered
        assert PARTIAL_FRAGMENT not in rendered
    assert is_capability_gap("I cannot perform that operation.") is True
    assert is_capability_gap(rendered) is False
    assert len(runtime.episodic_memory.stored) == 1
    episode = runtime.episodic_memory.stored[0]
    assert episode.self_contradicted_channels == sorted(expected_failed)
    assert episode.outcomes[0]["success"] is True
    assert episode.outcomes[0]["response"] == ctx.response_text[:500]
    assert episode.failed_tool_names == ["web_search"]
    assert episode.failed_tool_call_count == 1
    if expected_failed and not long_reply:
        assert _FAILED_WRITE_NOTICE in episode.outcomes[0]["response"]
    if long_reply:
        assert len(episode.outcomes[0]["response"]) == 500
        assert _FAILED_WRITE_NOTICE not in episode.outcomes[0]["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize("agree", [False, True], ids=["distinct-prefixes", "agreeing-prefixes"])
@pytest.mark.parametrize("artifacts, artifact_failure, notebook, raw_fallback", [
    pytest.param(False, "none", "success", False, id="notebook-success"),
    pytest.param(False, "none", "failure", False, id="notebook-failure"),
    pytest.param(True, "none", None, False, id="artifacts-success"),
    pytest.param(True, "all", None, False, id="artifacts-failure"),
    pytest.param(True, "partial", None, False, id="artifacts-partial-only"),
    pytest.param(True, "partial", "failure", False, id="partial-artifacts-notebook-failure"),
    pytest.param(True, "all", "success", False, id="failed-artifacts-notebook-success"),
    pytest.param(False, "none", "failure", True, id="raw-notebook-failure"),
    pytest.param(True, "partial", "failure", True, id="raw-mixed-failure"),
])
async def test_four_speaker_real_writes_preserve_semantic_trust_across_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agree: bool,
    artifacts: bool, artifact_failure: str, notebook: str | None, raw_fallback: bool,
) -> None:
    from probos.avatars.divergence_detector import strip_intent_self_tag
    from probos.cognitive.chat_facilitator import (
        ChatFacilitator, project_persisted_convergence_body,
    )
    from probos.cognitive.conversation_trust import extract_conversation_trust_outcomes
    from probos.cognitive.dm.a2ui_extractor import build_a2ui_stub
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.routers import thread_fanout
    from tests.test_ad933_group_chat_escalation import _build_env

    agents = {
        "voice1": "scout", "voice2": "counselor",
        "voice3": "diagnostician", "voice4": "architect",
    }
    choices = ["Choose quartz.", "Prefer velvet.", "Select copper.", "Pick marble."]
    names = {agent_id: (f"{agent_id}-first.md", f"{agent_id}-second.md") for agent_id in agents}
    topics = {agent_id: f"decision-{agent_id}" for agent_id in agents}
    fail_names = {
        name for first, second in names.values() for name in (first, second)
        if artifacts and (artifact_failure == "all" or artifact_failure == "partial" and name == second)
    }
    ui_stub = build_a2ui_stub("a2ui-choice-1.json", 1, "choice")
    inputs = {
        agent_id: "\n".join(part for part in (
            "We should ship the release this sprint." if agree else choices[index],
            _two_tags(*names[agent_id]) if artifacts else "",
            f"[NOTEBOOK {topics[agent_id]}]{_NOTE_CONTENT}[/NOTEBOOK]" if notebook else "",
            ui_stub if artifacts else "",
        ) if part)
        for index, agent_id in enumerate(agents)
    }
    escalate = DmReplyPipeline.run_escalation_only
    record_trust = thread_fanout._record_conversation_trust
    comparisons: list[dict[str, Any]] = []
    for guard_enabled in (False, True):
        arm_path = tmp_path / ("guard-on" if guard_enabled else "guard-off")
        effects = await _real_write_runtime(arm_path, fail_names, False)
        records = effects._records_store
        records.fail_topics = set(topics.values()) if notebook == "failure" else set()
        store, runtime = _build_env(
            arm_path, agents=agents, replies=inputs,
            callsigns={agent_type: agent_type.title() for agent_type in agents.values()},
        )
        runtime.config = SystemConfig()
        runtime.config.records = effects.config.records
        runtime.config.group_chat.agent_reactivity_enabled = False
        runtime.config.group_chat.conversation_trust_enabled = True
        runtime.config.write_claim_guard.enabled = guard_enabled
        runtime._records_store = records
        runtime.artifact_store = effects.artifact_store
        runtime.attachment_store = effects.attachment_store
        runtime.episodic_memory = effects.episodic_memory
        runtime.proactive_loop = effects.proactive_loop
        runtime.proactive_loop.set_runtime(runtime)
        runtime.trust_network = TrustNetwork()
        for agent_id in agents:
            record = runtime.trust_network.get_or_create(agent_id)
            assert (record.alpha, record.beta) == (2.0, 2.0)
        assert runtime.trust_network.get_recent_events() == []
        contexts: list[DmReplyContext] = []
        producer_inputs: list[tuple[str, str]] = []
        failures: list[str] = []
        semantic_replies: list[dict[str, str]] = []
        blob_attempts: list[tuple[str, bytes, str]] = []
        write_blob = runtime.attachment_store.write

        async def record_blob(
            content_hash: str, blob: bytes, mime: str, *, origin: str = "chat_attachment",
        ) -> Path:
            blob_attempts.append((content_hash, blob, origin))
            return await write_blob(content_hash, blob, mime, origin=origin)

        async def record_escalation(pipeline: DmReplyPipeline) -> None:
            producer_inputs.append((pipeline.ctx.agent_id, pipeline.ctx.response_text))
            await escalate(pipeline)
            contexts.append(pipeline.ctx)
            if raw_fallback:
                assert pipeline.ctx.write_ledger.evaluated
                assert pipeline.ctx.pre_write_disclosure_body is not None
                failures.append(pipeline.ctx.agent_id)
                raise RuntimeError("Injected outer failure after real writes and guard completed")

        def capture_trust(
            runtime: Any, thread: Any, replies: list[dict[str, str]], participants: list[str],
        ) -> None:
            semantic_replies.extend(replies)
            record_trust(runtime, thread, replies, participants)

        with monkeypatch.context() as patch:
            patch.setattr(runtime.attachment_store, "write", record_blob)
            patch.setattr(DmReplyPipeline, "run_escalation_only", record_escalation)
            patch.setattr(thread_fanout, "_record_conversation_trust", capture_trust)
            thread = store.create_thread(title="write outcomes", participants=list(agents))
            captain = store.append_message(
                thread.id, author_id="captain", role="captain", body="Compare the alternatives.",
            )
            replies = await thread_fanout.group_chat_fanout(
                runtime, thread.id, captain_body=captain.body, captain_msg=captain,
            )

        messages = [message for message in store.list_messages(thread.id) if message.role == "agent"]
        episodes = runtime.episodic_memory.stored
        assert len(producer_inputs) == len(contexts) == len(replies) == len(messages) == len(episodes) == 4
        assert sorted(producer_inputs) == sorted(inputs.items())
        assert len({message.author_id for message in messages}) == 4
        assert len({context.agent_id for context in contexts}) == 4
        assert len({episode.agent_ids[0] for episode in episodes}) == 4
        assert sorted(failures) == (sorted(agents) if raw_fallback else [])
        assert len(semantic_replies) == 4
        assert [reply["agent_id"] for reply in semantic_replies] == [reply["agent_id"] for reply in replies]
        assert all(set(reply) == {"agent_id", "callsign", "text"} for reply in semantic_replies)
        assert all(set(reply) == {"agent_id", "callsign", "text", "message"} for reply in replies)
        for reply in replies:
            receipt = reply["message"]
            assert receipt is not None
            matching = [message for message in messages if message.id == receipt["id"]]
            assert len(matching) == 1
            stored = matching[0]
            assert receipt == stored.to_dict()
            assert receipt["thread_id"] == stored.thread_id == thread.id
            assert receipt["author_id"] == stored.author_id == reply["agent_id"]
            assert receipt["role"] == stored.role == "agent"
            assert receipt["body"] == stored.body == reply["text"]
            assert receipt["created_at"] == stored.created_at
            assert receipt["metadata"] == stored.metadata
        assert len({reply["message"]["id"] for reply in replies}) == len(replies)
        rows = {message.author_id: message for message in messages}
        by_context = {context.agent_id: context for context in contexts}
        assert {reply["agent_id"]: reply["text"] for reply in replies} == {
            agent_id: message.body for agent_id, message in rows.items()
        }
        assert len(blob_attempts) == (8 if artifacts else 0)
        assert all(origin == "agent_artifact" for _, _, origin in blob_attempts)
        assert sorted(runtime.artifact_store.attempted) == (
            sorted(name for pair in names.values() for name in pair) if artifacts else []
        )
        artifact_rows = runtime.artifact_store.list_thread_latest(thread.id)
        expected_blobs = {
            name: content for first, second in names.values()
            for name, content in ((first, b"# First"), (second, b"# Second"))
        } if artifacts else {}
        assert len(artifact_rows) == len(expected_blobs) - len(fail_names)
        assert {row.name for row in artifact_rows} == set(expected_blobs) - fail_names
        for artifact in artifact_rows:
            assert artifact.version == 1
            assert await runtime.attachment_store.read(artifact.content_hash) == expected_blobs[artifact.name]
            owner = next(agent_id for agent_id, pair in names.items() if artifact.name in pair)
            assert f"[Artifact: {artifact.name} v1" in by_context[owner].pre_write_disclosure_body
        for content_hash, blob, _ in blob_attempts:
            assert await runtime.attachment_store.read(content_hash) == blob
        assert sorted(records.attempted) == (sorted(topics.values()) if notebook else [])
        assert len(records.similarity_results) == (4 if notebook else 0)
        assert all(result["action"] != "suppress" for result in records.similarity_results)
        for agent_id, agent_type in agents.items():
            note = await records.read_entry(f"notebooks/{agent_type}/{topics[agent_id]}.md", agent_type)
            if notebook == "success":
                assert note is not None and note["content"].strip() == _NOTE_CONTENT
            else:
                assert note is None
        expected_failed = set()
        if artifacts and artifact_failure == "all":
            expected_failed.add("artifact")
        if notebook == "failure":
            expected_failed.add("notebook")
        consulted = ({"artifact"} if artifacts else set()) | ({"notebook"} if notebook else set())
        expected_partial = {"artifact"} if artifacts and artifact_failure == "partial" else set()
        verdict = (
            ClaimVerdict.MARKER_WROTE_NOTHING if expected_failed else
            ClaimVerdict.MARKER_WROTE_PARTIALLY if expected_partial else ClaimVerdict.ABSTAIN
        )
        expected_semantics: dict[str, str] = {}
        for context in contexts:
            ledger = context.write_ledger
            assert ledger.consulted == frozenset(consulted)
            assert ledger.wrote_nothing == frozenset(expected_failed)
            assert ledger.wrote == frozenset(consulted - expected_failed)
            assert ledger.wrote_partially == frozenset(expected_partial)
            assert assess_write_claim(ledger) is verdict
            prefix = context.pre_write_disclosure_body
            assert prefix is not None
            assert (ui_stub in prefix) is artifacts
            suffix = disclosure_for(verdict) if guard_enabled else ""
            assert context.response_text == prefix + suffix
            assert context.write_disclosure_suffix == (suffix or None)
            delivered = inputs[context.agent_id] if raw_fallback else context.response_text
            assert rows[context.agent_id].body == strip_intent_self_tag(delivered)
            expected_semantics[context.agent_id] = strip_intent_self_tag(
                inputs[context.agent_id] if raw_fallback else prefix,
            )
            assert project_persisted_convergence_body(
                rows[context.agent_id].body, rows[context.agent_id].metadata,
            ) == expected_semantics[context.agent_id]
            assert ("ad1305_convergence" in rows[context.agent_id].metadata) is bool(suffix and not raw_fallback)
        assert {reply["agent_id"]: reply["text"] for reply in semantic_replies} == expected_semantics
        for episode in episodes:
            assert episode.outcomes[0]["success"] is True
            assert episode.outcomes[0]["session_type"] == "group"
            assert episode.outcomes[0]["response"] == rows[episode.agent_ids[0]].body[:500]
            assert episode.self_contradicted_channels == sorted(expected_failed)
            assert episode.anchors.chat_thread_id == thread.id
        facilitator = ChatFacilitator.from_config(runtime.config)
        control_replies = [
            {"agent_id": reply["agent_id"], "callsign": reply["callsign"], "text": expected_semantics[reply["agent_id"]]}
            for reply in replies
        ]
        assert semantic_replies == control_replies
        outcomes = extract_conversation_trust_outcomes(
            control_replies, facilitator=facilitator, intent_type="write outcomes",
            positive_weight=0.05, max_outcomes=4,
        )
        converged = facilitator.is_converged(list(expected_semantics.items()))
        if not artifacts and not raw_fallback:
            assert converged is agree
        assert len(outcomes) == (4 if converged else 0)
        events = runtime.trust_network.get_recent_events()
        assert len(events) == len(outcomes)
        assert sorted((event.agent_id, event.verifier_id, event.weight, event.success) for event in events) == sorted(
            (outcome.agent_id, outcome.verifier_id, outcome.weight, outcome.success) for outcome in outcomes
        )
        for event in events:
            assert event.weight == 0.05 and event.success is True
            assert event.verifier_id in agents and event.verifier_id != event.agent_id
        for agent_id in agents:
            record = runtime.trust_network.get_record(agent_id)
            assert record is not None
            assert (record.alpha, record.beta) == (2.05 if converged else 2.0, 2.0)
        comparisons.append({
            "semantics": expected_semantics, "trust": runtime.trust_network.raw_scores(),
            "outcomes": outcomes, "blob_count": len(blob_attempts),
            "artifact_count": len(artifact_rows), "notebook_attempts": sorted(records.attempted),
        })
    assert len(comparisons) == 2
    assert comparisons[0] == comparisons[1]


@pytest.mark.asyncio
async def test_real_notebook_dedup_preserves_durable_note_without_disclosure(
    tmp_path: Path,
) -> None:
    runtime = await _real_write_runtime(tmp_path, set(), False)
    records = runtime._records_store
    first = _make_ctx(runtime, _NOTE_REPLY)
    await DmReplyPipeline(first).run()
    assert records.attempted == ["decision"]
    assert first.write_ledger.wrote == frozenset({"notebook"})
    before = await records.read_entry("notebooks/yeoman/decision.md", "yeoman")
    assert before is not None
    assert before["content"].strip() == _NOTE_CONTENT
    note_path = records.repo_path / "notebooks" / "yeoman" / "decision.md"
    before_bytes = note_path.read_bytes()

    second = _make_ctx(runtime, _NOTE_REPLY)
    pipeline = DmReplyPipeline(second)
    await pipeline.run()

    assert len(records.similarity_results) == 2
    assert records.similarity_results[0]["action"] != "suppress"
    assert records.similarity_results[1]["action"] == "suppress"
    assert records.attempted == ["decision"]
    assert await records.read_entry("notebooks/yeoman/decision.md", "yeoman") == before
    assert note_path.read_bytes() == before_bytes
    assert second.write_ledger.wrote == frozenset({"notebook"})
    assert second.write_ledger.wrote_nothing == frozenset()
    assert assess_write_claim(second.write_ledger) is ClaimVerdict.ABSTAIN
    rendered = pipeline.build_response()["response"]
    assert require_rendered(rendered, sink="thread") is rendered
    assert rendered == first.response_text == "Recorded."
    assert NOTHING_FRAGMENT not in rendered
    assert PARTIAL_FRAGMENT not in rendered
    assert len(runtime.episodic_memory.stored) == 2
    assert runtime.episodic_memory.stored[1].self_contradicted_channels == []
    assert runtime.episodic_memory.stored[1].outcomes[0]["success"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("artifacts, fail_artifacts, notebook", [
    pytest.param(False, set(), "success", id="notebook-success"),
    pytest.param(False, set(), "dedup", id="notebook-existing-note"),
    pytest.param(True, set(), None, id="artifacts-all-success"),
    pytest.param(True, {"first.md", "second.md"}, None, id="artifacts-all-failure"),
    pytest.param(True, {"second.md"}, None, id="artifacts-partial-only"),
    pytest.param(True, set(), "failure", id="artifacts-success-notebook-failure"),
    pytest.param(True, {"first.md", "second.md"}, "success", id="artifacts-failure-notebook-success"),
    pytest.param(True, {"second.md"}, "failure", id="artifacts-partial-notebook-failure"),
    pytest.param(True, {"second.md"}, "success", id="artifacts-partial-notebook-success"),
    pytest.param(True, set(), "success", id="all-channels-success"),
    pytest.param(True, {"first.md", "second.md"}, "failure", id="all-channels-failure"),
])
async def test_group_real_write_outcomes_reach_durable_effects_and_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    artifacts: bool, fail_artifacts: set[str], notebook: str | None,
) -> None:
    from probos.cognitive.dm.a2ui_extractor import build_a2ui_stub
    from probos.cognitive.episodic import EpisodicMemory
    from probos.consensus.trust import TrustNetwork
    from probos.routers.thread_fanout import group_chat_fanout
    from tests.test_ad933_group_chat_escalation import _agent_rows, _build_env

    effects = await _real_write_runtime(tmp_path, fail_artifacts, notebook == "failure")
    records = effects._records_store
    ui_stub = build_a2ui_stub("a2ui-choice-1.json", 1, "choice")
    text = "\n".join(
        part for part in (_two_tags() if artifacts else "", _NOTE_REPLY if notebook else "")
        if part
    ) + f'\n{ui_stub} <intent emotion="warm">'
    peer_text = "The crew morale is steady."
    store, runtime = _build_env(
        tmp_path, agents={"scout1": "scout", "counselor1": "counselor"},
        replies={"scout1": text, "counselor1": peer_text},
        callsigns={"scout": "Scout", "counselor": "Counselor"},
    )
    runtime.config = effects.config
    runtime._records_store = records
    runtime.artifact_store = effects.artifact_store
    runtime.attachment_store = effects.attachment_store
    runtime.proactive_loop = effects.proactive_loop
    runtime.proactive_loop.set_runtime(runtime)
    runtime.trust_network = TrustNetwork()
    trust_before: dict[str, tuple[float, float]] = {}
    for agent_id in ("scout1", "counselor1"):
        record = runtime.trust_network.get_or_create(agent_id)
        trust_before[agent_id] = (record.alpha, record.beta)
    assert runtime.trust_network.get_recent_events() == []
    contexts: list[DmReplyContext] = []
    guard_inputs: dict[str, list[str]] = {}
    guard = DmReplyPipeline.step_4m_write_claim_guard
    escalate = DmReplyPipeline.run_escalation_only

    async def record_guard_input(pipeline: DmReplyPipeline) -> None:
        guard_inputs.setdefault(pipeline.ctx.agent_id, []).append(pipeline.ctx.response_text)
        await guard(pipeline)

    async def record_escalation(pipeline: DmReplyPipeline) -> None:
        await escalate(pipeline)
        contexts.append(pipeline.ctx)

    monkeypatch.setattr(DmReplyPipeline, "step_4m_write_claim_guard", record_guard_input)
    monkeypatch.setattr(DmReplyPipeline, "run_escalation_only", record_escalation)
    memory = EpisodicMemory(
        db_path=tmp_path / "memory" / "episodes.db", max_episodes=100,
        relevance_threshold=0.0, agent_recall_threshold=0.0,
        self_contradiction_recall_enabled=True,
    )
    await memory.start()
    try:
        runtime.episodic_memory = memory
        thread = store.create_thread(title="write outcomes", participants=["scout1", "counselor1"])
        expected_failed: set[str] = set()
        expected_wrote: set[str] = set()
        if artifacts:
            (expected_failed if len(fail_artifacts) == 2 else expected_wrote).add("artifact")
        if notebook:
            (expected_failed if notebook == "failure" else expected_wrote).add("notebook")
        expected_partial = {"artifact"} if artifacts and len(fail_artifacts) == 1 else set()
        verdict = (
            ClaimVerdict.MARKER_WROTE_NOTHING if expected_failed else
            ClaimVerdict.MARKER_WROTE_PARTIALLY if expected_partial else ClaimVerdict.ABSTAIN
        )
        before_bytes: bytes | None = None
        receipt_ids: set[str] = set()
        for turn in range(2 if notebook == "dedup" else 1):
            captain = store.append_message(
                thread.id, author_id="captain", role="captain", body="Save the maintenance decision.",
            )
            replies = await group_chat_fanout(
                runtime, thread.id, captain_body=captain.body, captain_msg=captain,
            )
            assert len(replies) == 2
            assert all(set(reply) == {"agent_id", "callsign", "text", "message"} for reply in replies)
            rows = _agent_rows(store, thread.id)
            assert rows == {reply["agent_id"]: reply["text"] for reply in replies}
            assert rows["counselor1"] == peer_text
            assert "<intent" not in rows["scout1"]
            assert "[NOTEBOOK" not in rows["scout1"]
            assert rows["scout1"].count(ui_stub) == 1
            for agent_id, expected_trust in trust_before.items():
                record = runtime.trust_network.get_record(agent_id)
                assert record is not None
                assert (record.alpha, record.beta) == expected_trust
            assert runtime.trust_network.get_recent_events() == []
            writer_contexts = [ctx for ctx in contexts if ctx.agent_id == "scout1"]
            assert len(writer_contexts) == turn + 1
            ledger = writer_contexts[-1].write_ledger
            assert ledger.consulted == frozenset(expected_failed | expected_wrote)
            assert ledger.wrote == frozenset(expected_wrote)
            assert ledger.wrote_nothing == frozenset(expected_failed)
            assert ledger.wrote_partially == frozenset(expected_partial)
            assert assess_write_claim(ledger) is verdict
            captured = writer_contexts[-1].pre_write_disclosure_body
            assert len(guard_inputs["scout1"]) == turn + 1
            assert captured == guard_inputs["scout1"][-1]
            assert captured is not None and ui_stub in captured
            assert writer_contexts[-1].response_text == captured + disclosure_for(verdict)
            assert all(
                ctx.pre_write_disclosure_body == peer_text
                for ctx in contexts if ctx.agent_id == "counselor1"
            )
            assert all(ctx.tool_invocations is None for ctx in contexts)
            assert all(ctx.write_ledger == WriteLedger() for ctx in contexts if ctx.agent_id == "counselor1")
            assert is_capability_gap("I cannot perform that operation.") is True
            assert _CAPABILITY_GAP_RE.search("I cannot perform that operation.") is not None
            for candidate in (ClaimVerdict.MARKER_WROTE_NOTHING, ClaimVerdict.MARKER_WROTE_PARTIALLY):
                notice = disclosure_for(candidate)
                assert writer_contexts[-1].response_text.count(notice) == int(verdict is candidate)
                assert rows["scout1"].count(notice.strip()) == int(verdict is candidate)
                assert _CAPABILITY_GAP_RE.search(notice) is None
            assert is_capability_gap(rows["scout1"]) is False
            assert runtime.artifact_store.attempted == (["first.md", "second.md"] if artifacts else [])
            artifact_rows = runtime.artifact_store.list_thread_latest(thread.id)
            expected_blobs = {"first.md": b"# First", "second.md": b"# Second"} if artifacts else {}
            assert {row.name for row in artifact_rows} == set(expected_blobs) - fail_artifacts
            for row in artifact_rows:
                assert row.version == 1
                assert await runtime.attachment_store.read(row.content_hash) == expected_blobs[row.name]
                assert f"[Artifact: {row.name} v1" in rows["scout1"]
            assert records.attempted == (["decision"] if notebook else [])
            note = await records.read_entry("notebooks/scout/decision.md", "scout")
            if notebook in {"success", "dedup"}:
                assert note is not None
                assert note["content"].strip() == _NOTE_CONTENT
                note_bytes = (records.repo_path / "notebooks/scout/decision.md").read_bytes()
                if turn:
                    assert records.similarity_results[-1]["action"] == "suppress"
                    assert note_bytes == before_bytes
                else:
                    assert records.similarity_results[0]["action"] != "suppress"
                    before_bytes = note_bytes
            else:
                assert note is None
            assert len(records.similarity_results) == (turn + 1 if notebook else 0)
            messages = [message for message in store.list_messages(thread.id, limit=1000) if message.role == "agent"]
            episodes = await memory.list_episodes()
            assert len(messages) == len(episodes) == 2 * (turn + 1)
            for reply in replies:
                receipt = reply["message"]
                assert receipt is not None
                matching = [message for message in messages if message.id == receipt["id"]]
                assert len(matching) == 1
                stored = matching[0]
                assert receipt == stored.to_dict()
                assert receipt["thread_id"] == stored.thread_id == thread.id
                assert receipt["author_id"] == stored.author_id == reply["agent_id"]
                assert receipt["role"] == stored.role == "agent"
                assert receipt["body"] == stored.body == reply["text"]
                assert receipt["created_at"] == stored.created_at
                assert receipt["metadata"] == stored.metadata
                assert receipt["id"] not in receipt_ids
                receipt_ids.add(receipt["id"])
            assert len(receipt_ids) == len(messages)
            writers = [episode for episode in episodes if episode.agent_ids == ["scout1"]]
            peers = [episode for episode in episodes if episode.agent_ids == ["counselor1"]]
            assert len(writers) == len(peers) == turn + 1
            for episode in writers:
                assert episode.self_contradicted_channels == sorted(expected_failed)
                assert episode.outcomes[0]["success"] is True
                assert episode.outcomes[0]["session_type"] == "group"
                assert episode.anchors.chat_thread_id == thread.id
            assert all(episode.self_contradicted_channels == [] for episode in peers)
            assert all(episode.outcomes[0]["response"] == peer_text for episode in peers)
            if expected_partial and not expected_failed:
                writer_ids = {episode.id for episode in writers}
                assert writer_ids <= {
                    episode.id for episode in await memory.recall_for_agent(
                        "scout1", "maintenance decision", k=10, include_self_contradicted=True,
                    )
                }
                assert writer_ids <= {
                    episode.id for episode in await memory.recall_for_agent("scout1", "maintenance decision", k=10)
                }
                assert {episode.id for episode in await memory.get_by_ids(list(writer_ids), for_evidence=True)} == writer_ids
    finally:
        await memory.stop()
