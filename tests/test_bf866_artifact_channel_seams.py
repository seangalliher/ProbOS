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

import pytest

from probos.artifacts import Artifact, ArtifactStore
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
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
from probos.config import WriteClaimGuardConfig

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


def _run(store, response_text: str) -> DmReplyContext:
    ctx = DmReplyContext(
        runtime=_runtime(store),
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
