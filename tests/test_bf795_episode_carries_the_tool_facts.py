"""BF-795 (#1259): the episode carries the AD-1248 facts, not a rendering.

``step_5_episodic_store`` built its ``Episode`` without reading
``ctx.reply.tool_failures`` -- a field on the same context object and in scope
at that line -- so the mesh's durable record of a turn said nothing about the
tools that failed during it. That matters one layer deeper than the reply:
``procedures.py`` synthesises procedures from stored responses, so a turn that
reads "I fetched the versions" after a failed fetch teaches the mesh a
falsehood about its own capability.

**The filed fix does not work, and this file proves why before building on it.**
The issue proposed composing the disclosure before ``step_5``. But ``step_5``
stores ``response_text[:500]`` -- truncated from the FRONT -- and the AD-1248
disclosure is a TAIL, so for any reply longer than 500 characters it would
still be absent. ``test_composing_the_disclosure_earlier_would_not_have_helped``
measures that directly.

Two further reasons not to store the rendered text: the disclosure is composed
per route per variant (the HTTP route renders at ``reply_pipeline.py:2067``,
the channel route renders separately and prefixes a callsign at
``channels/base.py:231``), so there is no single rendering an episode could
keep; and ``outcomes[0]["response"]`` is read as *what the agent said* by
``procedures.py``, ``importance_scorer.py`` and ``episodic.py``.

So the structured facts are stored instead, following AD-1293's
``self_contradicted_channels`` exactly: first-class ``Episode`` fields, stamped
at encode time, deliberately outside ``compute_episode_hash``.

TWO fields, not one. ``failed_call_count`` is not derivable from ``names()``:
two failed ``web_search`` calls are two failures and one name. That is the
original AD-1248 count bug, and storing only names would re-introduce it.

The metadata round-trip test is mandatory rather than nice-to-have: a field
that encodes but never decodes is inert and looks identical to a working one.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash
from probos.config import WriteClaimGuardConfig
from probos.dm_reply import DmReply, ToolFailures
from probos.types import Episode

#: The opening of the composed AD-1248 disclosure.
DISCLOSURE_FRAGMENT = "could not complete this using"


class _CapturingEpisodicMemory:
    """Records what ``step_5_episodic_store`` actually stored.

    A plain attribute object, not ``MagicMock(spec=...)``: a spec'd mock would
    auto-mock the new fields and make every assertion below pass for the wrong
    reason (the AD-1284 lesson, inherited from the AD-1293 fixture).
    """

    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)


def _failures(*names: str, calls: int | None = None) -> ToolFailures:
    """A PRECISE failure set. ``calls`` adds repeat calls to the first name."""
    entries = {f"k{i}": n for i, n in enumerate(names)}
    if calls is not None:
        for extra in range(len(names), calls):
            entries[f"k{extra}"] = names[0]
    return ToolFailures.from_mapping(entries)


def _store(reply: object, *, message: str = "What versions are current?") -> Episode:
    """Run ONLY step_5 against a given reply and return the stored episode."""
    episodic = _CapturingEpisodicMemory()
    ctx = DmReplyContext(
        runtime=SimpleNamespace(
            config=SimpleNamespace(write_claim_guard=WriteClaimGuardConfig(enabled=True)),
            proactive_loop=None,
            episodic_memory=episodic,
        ),
        agent=SimpleNamespace(id="a1", agent_type="yeoman"),
        agent_id="a1",
        callsign="Yeo",
        req_message=message,
        reply=reply,  # type: ignore[arg-type]
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=None,
        params={},
        message_text=message,
        sampling_state=None,
        avatar_event_bus=None,
        chat_thread_id="t1",
    )
    asyncio.run(DmReplyPipeline(ctx).step_5_episodic_store())
    assert episodic.stored, "step_5 stored nothing -- the fixture never reached the branch"
    return episodic.stored[0]


# --------------------------------------------------------------------------- #
# The premise the issue got wrong                                              #
# --------------------------------------------------------------------------- #


def test_composing_the_disclosure_earlier_would_not_have_helped() -> None:
    """``[:500]`` truncates from the front; the disclosure is a tail.

    This is why the facts are stored rather than the rendering. If this ever
    starts passing the other way, the whole design below is worth revisiting.
    """
    reply = DmReply(body="x" * 900, tool_failures=_failures("web_search"))
    rendered = str(reply.render())
    assert DISCLOSURE_FRAGMENT in rendered, "premise: the disclosure must be composed"
    assert len(rendered) > 500, "premise: only a reply past the bound discriminates"
    assert DISCLOSURE_FRAGMENT not in rendered[:500], (
        "if the disclosure survived front-truncation, composing earlier would "
        "have been a working fix and this AD is solving the wrong problem"
    )


# --------------------------------------------------------------------------- #
# PRODUCER -- the facts reach the episode                                      #
# --------------------------------------------------------------------------- #


def test_a_failed_tool_reaches_the_episode_as_facts() -> None:
    episode = _store(DmReply(body="Here is what I found.", tool_failures=_failures("web_search")))
    assert episode.failed_tool_names == ["web_search"]
    assert episode.failed_tool_call_count == 1


def test_two_failures_of_one_tool_are_two_calls_and_one_name() -> None:
    """The count is not derivable from the names -- the AD-1248 count bug."""
    failures = _failures("web_search", calls=2)
    assert failures.names() == ("web_search",), "premise: one distinct name"
    assert failures.failed_call_count == 2, "premise: two failed calls"

    episode = _store(DmReply(body="Here is what I found.", tool_failures=failures))
    assert episode.failed_tool_names == ["web_search"]
    assert episode.failed_tool_call_count == 2, (
        "storing only the names would report one failure for two, which is "
        "exactly the bug AD-1248 fixed in the render"
    )


def test_several_failed_tools_all_reach_the_episode() -> None:
    episode = _store(
        DmReply(body="Partial answer.", tool_failures=_failures("web_search", "http_fetch"))
    )
    assert episode.failed_tool_names == ["http_fetch", "web_search"]
    assert episode.failed_tool_call_count == 2


def test_a_clean_turn_stores_empty_facts() -> None:
    """Empty, never ``None`` -- "this turn disclosed no tool failure"."""
    episode = _store(DmReply(body="All good."))
    assert episode.failed_tool_names == []
    assert episode.failed_tool_call_count == 0


def test_the_rendered_disclosure_is_not_stored_in_the_response() -> None:
    """Pins the decision: the episode keeps facts, not a rendering.

    ``outcomes[0]["response"]`` is consumed as *what the agent said* by three
    subsystems, and the disclosure is composed per route per variant, so there
    is no single rendering this field could honestly carry.
    """
    episode = _store(DmReply(body="Here is what I found.", tool_failures=_failures("web_search")))
    assert DISCLOSURE_FRAGMENT not in episode.outcomes[0]["response"]
    assert episode.outcomes[0]["response"] == "Here is what I found."


def test_step_5_still_stores_when_tool_failures_is_absent() -> None:
    """A reply stand-in without the attachment must not break the store.

    ``step_5`` sits inside a broad ``try/except`` that logs and drops, so a
    raise here would silently lose the episode rather than surface.
    """
    episode = _store(SimpleNamespace(body="Answer without a DmReply."))
    assert episode.failed_tool_names == []
    assert episode.failed_tool_call_count == 0
    assert episode.outcomes[0]["response"] == "Answer without a DmReply."


# --------------------------------------------------------------------------- #
# CONSUMER -- the facts survive storage                                        #
# --------------------------------------------------------------------------- #


def test_facts_survive_the_metadata_round_trip() -> None:
    """The half-chain test. A field that encodes but never decodes is inert.

    Producer and consumer each passing proves nothing about the seam between
    them, which is where this repo's defects live.
    """
    original = Episode(
        id="ep-1",
        timestamp=1234.5,
        user_input="What versions are current?",
        failed_tool_names=["http_fetch", "web_search"],
        failed_tool_call_count=3,
    )
    metadata = EpisodicMemory._episode_to_metadata(original)
    assert "failed_tool_names_json" in metadata, "the encode leg never ran"

    restored = EpisodicMemory._metadata_to_episode(
        "ep-1", original.user_input, metadata
    )
    assert restored.failed_tool_names == ["http_fetch", "web_search"]
    assert restored.failed_tool_call_count == 3


@pytest.mark.asyncio
async def test_facts_survive_a_real_store_and_recall(tmp_path) -> None:
    """The whole chain against a real ``EpisodicMemory``, not a fake.

    A fake that cannot fail is not a test (BF-287 / AD-1284).
    """
    memory = EpisodicMemory(
        db_path=tmp_path / "episodes.db", max_episodes=100, relevance_threshold=0.3,
    )
    await memory.start()
    try:
        await memory.store(
            Episode(
                id="ep-real",
                timestamp=1234.5,
                user_input="What versions are current?",
                failed_tool_names=["web_search"],
                failed_tool_call_count=2,
            )
        )
        restored_all = await memory.get_by_ids(["ep-real"])
        assert restored_all, "the fixture stored nothing to read back"
        restored = restored_all[0]
        assert restored.failed_tool_names == ["web_search"]
        assert restored.failed_tool_call_count == 2
    finally:
        await memory.stop()


def test_pre_bf795_metadata_rehydrates_with_empty_facts() -> None:
    """An episode stored before this fix lacks both keys and must not raise."""
    restored = EpisodicMemory._metadata_to_episode("old", "hi", {"timestamp": 1.0})
    assert restored.failed_tool_names == []
    assert restored.failed_tool_call_count == 0


@pytest.mark.parametrize(
    "names_raw, count_raw",
    [
        ("not json", "not a number"),
        ('{"a": 1}', None),          # valid JSON, wrong shape
        ('"web_search"', 1.9),       # valid JSON, not a list
        (None, []),
        ("", ""),
    ],
)
def test_malformed_facts_metadata_degrades_to_empty(names_raw, count_raw) -> None:
    """Honest-degrade at the decode boundary, never a raise.

    A malformed value must read as "no facts recorded", not corrupt the whole
    episode -- the same trade the AD-1293 and AD-871 blocks above it make.
    """
    restored = EpisodicMemory._metadata_to_episode(
        "bad",
        "hi",
        {
            "timestamp": 1.0,
            "failed_tool_names_json": names_raw,
            "failed_tool_call_count": count_raw,
        },
    )
    assert restored.failed_tool_names == []
    assert restored.failed_tool_call_count in (0, 1), (
        "a malformed count must degrade, not propagate a wrong number"
    )


# --------------------------------------------------------------------------- #
# The mass-auto-heal guard                                                     #
# --------------------------------------------------------------------------- #


def test_episode_hash_is_unchanged_by_the_new_fields() -> None:
    """Both fields stay OUT of ``compute_episode_hash``.

    Adding a field there invalidates every stored episode's hash and triggers
    a mass auto-heal -- the reason given for ``correlation_id`` and
    ``self_contradicted_channels`` before them.
    """
    base = Episode(
        id="ep", timestamp=1.0, user_input="hi", outcomes=[{"intent": "direct_message"}],
    )
    marked = Episode(
        id="ep",
        timestamp=1.0,
        user_input="hi",
        outcomes=[{"intent": "direct_message"}],
        failed_tool_names=["web_search", "http_fetch"],
        failed_tool_call_count=7,
    )
    assert compute_episode_hash(base) == compute_episode_hash(marked)

    changed = Episode(
        id="ep", timestamp=1.0, user_input="hi", outcomes=[{"intent": "other"}],
    )
    assert compute_episode_hash(base) != compute_episode_hash(changed), (
        "premise: this hash must be sensitive to something, or the assertion "
        "above holds trivially"
    )
