"""AD-1293 (#1200): the turn's act-record must reach the episode, and a
self-contradicted claim must not be recalled as evidence.

The AD-1285 write-claim verdict was computed at ``step_4m`` and thrown away by
``step_5_episodic_store`` -- the very next step -- which built its ``Episode``
without ever reading ``ctx.write_ledger`` (a field declared on the same context
object and in scope throughout). The stored DM episode then asserted
``"success": True`` as a literal.

Measured on the live vessel before this AD: 1507 episodes, ``success=False``
present 741 times across the store but 0/20 on the ``direct_message`` path, so
that field recorded nothing here rather than recording genuine success. And
``contradicted_by_json`` was present on 1342 episodes with the value ``[]`` on
every one -- AD-871's contradiction machinery inert at both ends.

``outcomes[].success`` is nonetheless left as the literal ``True``. An earlier
revision of this AD made it conditional on the marker; five consumers
(``decomposer``, ``retrieval_practice``, ``contradiction_detector``,
``dreaming``'s trust consolidation, ``importance_scorer``) read that boolean as
TASK-EXECUTION truth, and a turn that answered the Captain executed -- only a
claimed durable side-effect is missing. Overloading it would have penalised an
agent's trust for an infrastructure failure it did not cause.
``self_contradicted_channels`` carries the signal instead, on its own field.

Two properties are pinned here, and the pair is the point: a marker with no
consumer is the exact defect this AD removes.

  * PRODUCER -- the verdict reaches the episode, at encode time. Nothing is
    retracted, so no id transport exists to go stale.
  * CONSUMER -- a marked episode is absent from every EVIDENCE surface (any
    surface whose result can reach an LLM prompt), INCLUDING after hybrid
    fusion, while remaining reachable by id. This repo supersedes; it does not
    rewrite.

BF-287 / AD-1284 discipline: REAL ``EpisodicMemory`` on ``tmp_path`` for every
recall test, and no ``MagicMock(spec=...)`` anywhere. The reverted first attempt
at #1200 (``a16c6c53``) used a hand-written fake that returned ``None`` from
``store`` and ``True`` from the marker, and therefore could not have caught two
of the four findings that reverted it. A fake that cannot fail is not a test.

Every exclusion test below first asserts the episode IS returned with
``include_self_contradicted=True``, so "found nothing" is distinguishable from
"the fixture never stored anything".
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from probos.cognitive.dm.reply_pipeline import DmReplyContext, DmReplyPipeline
from probos.cognitive.dm.reply_value import DmReply
from probos.cognitive.dm.write_ledger import (
    WRITE_CHANNEL_ARTIFACT,
    WRITE_CHANNEL_NOTEBOOK,
    WriteLedger,
)
from probos.cognitive.episodic import EpisodicMemory
from probos.config import SelfContradictionRecallConfig, WriteClaimGuardConfig
from probos.types import AnchorFrame, Episode, episode_is_self_contradicted

#: The sentence step_4m appends when a channel ran and wrote nothing.
DISCLOSURE_FRAGMENT = "A durable write was attempted on this turn"

#: A reply carrying a notebook marker -- the marker is what makes the channel
#: run. The guard never reads the prose around it.
MARKED_REPLY = "Noted. [NOTEBOOK finding]Ward room escalation.[/NOTEBOOK]"


# --------------------------------------------------------------------------- #
# BF-287 real-but-fake stubs                                                   #
# --------------------------------------------------------------------------- #


class _CapturingEpisodicMemory:
    """Records what ``step_5_episodic_store`` actually stored.

    A plain attribute object, not a spec'd mock: a ``MagicMock(spec=...)``
    would auto-mock ``self_contradicted_channels`` and make every assertion
    below pass for the wrong reason (the AD-1284 lesson).
    """

    def __init__(self) -> None:
        self.stored: list[Episode] = []

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)


class _FakeProactiveLoop:
    """Stands in for ``ProactiveLoop``. ``actions`` is what the ledger reads:
    an empty list means the notebook channel ran and wrote nothing."""

    def __init__(self, *, actions: list | None = None) -> None:
        self._actions = list(actions or [])

    async def extract_and_execute_notebooks(self, agent, text: str):
        cleaned = (
            text.replace("[NOTEBOOK finding]", "").replace("[/NOTEBOOK]", "").strip()
        )
        return cleaned, self._actions


def _runtime(*, episodic, proactive=None) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(write_claim_guard=WriteClaimGuardConfig(enabled=True)),
        proactive_loop=proactive,
        episodic_memory=episodic,
    )


def _make_ctx(*, runtime, response_text: str = "Noted.") -> DmReplyContext:
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


def _store_and_capture(ledger: WriteLedger) -> Episode:
    """Run ONLY step_5 with a pre-set ledger and return the stored episode."""
    episodic = _CapturingEpisodicMemory()
    ctx = _make_ctx(runtime=_runtime(episodic=episodic))
    ctx.write_ledger = ledger
    asyncio.run(DmReplyPipeline(ctx).step_5_episodic_store())
    assert episodic.stored, "step_5 stored nothing -- fixture never reached the branch"
    return episodic.stored[0]


# --------------------------------------------------------------------------- #
# Real EpisodicMemory fixtures                                                 #
# --------------------------------------------------------------------------- #


@pytest.fixture
async def mem(tmp_path):
    m = EpisodicMemory(
        db_path=tmp_path / "episodes.db",
        max_episodes=100,
        relevance_threshold=0.3,
    )
    await m.start()
    yield m
    await m.stop()


def _dm_anchors() -> AnchorFrame:
    """The frame ``step_5_episodic_store`` actually builds, so the anchor
    surface is reachable. ``recall_by_anchor`` refuses to dump the whole
    collection, so an ``agent_id``-only call returns [] for every episode and
    would make the exclusion assertion pass without testing anything."""
    return AnchorFrame(
        channel="dm",
        trigger_type="direct_message",
        trigger_agent="captain",
        participants=["captain", "Yeo"],
    )


def _marked_episode() -> Episode:
    """A DM episode contradicted by its own act-record.

    ``user_input`` starts with ``[1:1 with`` so the AD-610 storage gate stores
    it unconditionally -- otherwise a test could pass because nothing was ever
    written rather than because the filter worked.
    """
    return Episode(
        id="marked-1",
        user_input="[1:1 with Yeo] Captain: log the reactor coolant finding",
        reflection="Yeo said the coolant finding was saved to the notebook.",
        timestamp=2000.0,
        agent_ids=["a1"],
        anchors=_dm_anchors(),
        self_contradicted_channels=[WRITE_CHANNEL_NOTEBOOK],
        outcomes=[{"intent": "direct_message", "success": False}],
    )


def _clean_episode() -> Episode:
    return Episode(
        id="clean-1",
        user_input="[1:1 with Yeo] Captain: log the reactor coolant finding",
        reflection="Yeo recorded the coolant finding in the notebook.",
        timestamp=1000.0,
        agent_ids=["a1"],
        anchors=_dm_anchors(),
        outcomes=[{"intent": "direct_message", "success": True}],
    )


async def _store_both(mem) -> None:
    await mem.store(_clean_episode())
    await mem.store(_marked_episode())


# =========================================================================== #
# 1-5. representation (Sections 1-2)                                          #
# =========================================================================== #


def test_episode_defaults_self_contradicted_channels_to_empty() -> None:
    assert Episode(user_input="hello").self_contradicted_channels == []


def test_metadata_round_trip_preserves_a_populated_marker() -> None:
    ep = Episode(
        user_input="x", self_contradicted_channels=["artifact", "notebook"],
    )
    meta = EpisodicMemory._episode_to_metadata(ep)

    assert json.loads(meta["self_contradicted_json"]) == ["artifact", "notebook"]

    back = EpisodicMemory._metadata_to_episode(ep.id, "x", meta)
    assert back.self_contradicted_channels == ["artifact", "notebook"]


def test_legacy_metadata_without_the_key_materialises_empty() -> None:
    """Pre-AD-1293 episodes carry no such key and must decode, not raise."""
    legacy = {"timestamp": 1.0, "user_input": "old"}
    ep = EpisodicMemory._metadata_to_episode("legacy-1", "old", legacy)

    assert ep.self_contradicted_channels == []
    assert episode_is_self_contradicted(ep) is False


@pytest.mark.parametrize("raw", ["not-json", '{"a": 1}', "17", "null", '"notebook"'])
def test_malformed_marker_degrades_to_empty(raw: str) -> None:
    """Non-list or unparseable values degrade to ``[]``, never raise -- the
    same defensive shape ``contradicted_by_json`` already uses."""
    ep = EpisodicMemory._metadata_to_episode(
        "x", "doc", {"timestamp": 1.0, "self_contradicted_json": raw},
    )
    assert ep.self_contradicted_channels == []


def test_episode_is_self_contradicted_predicate() -> None:
    assert episode_is_self_contradicted(Episode(self_contradicted_channels=["n"]))
    assert not episode_is_self_contradicted(Episode())


# =========================================================================== #
# 6-11. producer (Section 3)                                                   #
# =========================================================================== #


def test_unevaluated_ledger_marks_nothing() -> None:
    """AD-1269: "no channel ran" must not read as "a channel wrote nothing"."""
    ep = _store_and_capture(WriteLedger())
    assert ep.self_contradicted_channels == []


def test_channel_that_wrote_marks_nothing() -> None:
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=True)
    ep = _store_and_capture(ledger)
    assert ep.self_contradicted_channels == []


def test_channel_that_ran_and_wrote_nothing_is_marked() -> None:
    ledger = WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
    ep = _store_and_capture(ledger)
    assert ep.self_contradicted_channels == [WRITE_CHANNEL_NOTEBOOK]


def test_only_the_failing_channel_is_marked_and_the_list_is_sorted() -> None:
    """Per channel, deliberately: a turn that persisted an artifact and ran a
    notebook channel that wrote nothing still confabulates the notebook."""
    ledger = (
        WriteLedger()
        .consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
        .consulted_with(WRITE_CHANNEL_ARTIFACT, wrote=True)
    )
    ep = _store_and_capture(ledger)

    assert ep.self_contradicted_channels == [WRITE_CHANNEL_NOTEBOOK]
    assert ep.self_contradicted_channels == sorted(ep.self_contradicted_channels)


def test_outcome_success_stays_true_and_the_marker_carries_the_signal() -> None:
    """``outcomes[].success`` is task-execution truth and must NOT be overloaded.

    This assertion previously read ``marked.outcomes[0]["success"] is False``,
    pinning a conditional ``success`` that an earlier revision introduced. That
    was wrong: five consumers (``decomposer``, ``retrieval_practice``,
    ``contradiction_detector``, ``dreaming`` trust consolidation,
    ``importance_scorer``) read the boolean as "did the task execute", and the
    turn DID answer the Captain -- only a claimed durable write is missing.
    Encoding that as failure would penalise an agent's trust for an
    infrastructure fault it did not cause. Inverted here so the field is pinned
    CONSTANT and the marker field alone carries the contradiction.
    """
    marked = _store_and_capture(
        WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=False)
    )
    assert marked.outcomes[0]["success"] is True
    assert marked.self_contradicted_channels == [WRITE_CHANNEL_NOTEBOOK]

    wrote = _store_and_capture(
        WriteLedger().consulted_with(WRITE_CHANNEL_NOTEBOOK, wrote=True)
    )
    assert wrote.outcomes[0]["success"] is True
    assert wrote.self_contradicted_channels == []

    unevaluated = _store_and_capture(WriteLedger())
    assert unevaluated.outcomes[0]["success"] is True
    assert unevaluated.self_contradicted_channels == []


def test_the_guard_disclosure_and_the_episode_marker_agree_on_one_turn() -> None:
    """THE CROSSING TEST -- step_4m to step_5 in one run.

    Each half working separately is precisely what shipped this defect: the
    verdict was computed correctly and then discarded by the next step. A test
    that stops at either boundary cannot see that.
    """
    episodic = _CapturingEpisodicMemory()
    ctx = _make_ctx(
        runtime=_runtime(
            episodic=episodic, proactive=_FakeProactiveLoop(actions=[]),
        ),
        response_text=MARKED_REPLY,
    )

    asyncio.run(DmReplyPipeline(ctx).run())

    # step_4m saw it...
    assert ctx.write_ledger.wrote_nothing == frozenset({WRITE_CHANNEL_NOTEBOOK})
    assert DISCLOSURE_FRAGMENT in ctx.response_text
    # ...and step_5 carried the same verdict into the episode.
    assert episodic.stored, "the pipeline stored no episode"
    assert episodic.stored[0].self_contradicted_channels == [WRITE_CHANNEL_NOTEBOOK]
    # This line previously asserted ``outcomes[0]["success"] is False``, which
    # pinned the overload described in the module docstring. The crossing
    # property is that the MARKER survives step_4m -> step_5; ``success`` is a
    # different concept and is pinned constant here to prove it stayed out of it.
    assert episodic.stored[0].outcomes[0]["success"] is True


# =========================================================================== #
# 12-23. consumer (Section 4)                                                  #
# =========================================================================== #


@pytest.mark.asyncio
async def test_marked_episode_is_absent_from_recall_for_agent(mem) -> None:
    await _store_both(mem)

    included = await mem.recall_for_agent(
        "a1", "coolant finding", k=10, include_self_contradicted=True,
    )
    assert "marked-1" in {e.id for e in included}, "probe never reached the branch"

    assert "marked-1" not in {
        e.id for e in await mem.recall_for_agent("a1", "coolant finding", k=10)
    }


@pytest.mark.asyncio
async def test_marked_episode_is_absent_from_recent(mem) -> None:
    await _store_both(mem)

    assert "marked-1" in {
        e.id for e in await mem.recent(k=10, include_self_contradicted=True)
    }
    assert "marked-1" not in {e.id for e in await mem.recent(k=10)}


@pytest.mark.asyncio
async def test_marked_episode_is_absent_from_recall_by_intent(mem) -> None:
    await _store_both(mem)

    assert "marked-1" in {
        e.id
        for e in await mem.recall_by_intent(
            "direct_message", k=10, include_self_contradicted=True,
        )
    }
    assert "marked-1" not in {
        e.id for e in await mem.recall_by_intent("direct_message", k=10)
    }


@pytest.mark.asyncio
async def test_marked_episode_is_absent_from_global_recall(mem) -> None:
    await _store_both(mem)

    assert "marked-1" in {
        e.id
        for e in await mem.recall("coolant finding", k=10, include_self_contradicted=True)
    }
    assert "marked-1" not in {e.id for e in await mem.recall("coolant finding", k=10)}


@pytest.mark.asyncio
async def test_marked_episode_is_absent_from_the_anchor_path(mem) -> None:
    await _store_both(mem)

    assert "marked-1" in {
        e.id
        for e in await mem.recall_by_anchor(
            channel="dm", agent_id="a1", limit=10, include_self_contradicted=True,
        )
    }
    assert "marked-1" not in {
        e.id for e in await mem.recall_by_anchor(channel="dm", agent_id="a1", limit=10)
    }


@pytest.mark.asyncio
async def test_marked_episode_is_absent_from_recent_for_agent(mem) -> None:
    await _store_both(mem)

    assert "marked-1" in {
        e.id
        for e in await mem.recent_for_agent("a1", k=10, include_self_contradicted=True)
    }
    assert "marked-1" not in {e.id for e in await mem.recent_for_agent("a1", k=10)}


@pytest.mark.asyncio
async def test_marked_episode_is_absent_after_hybrid_fusion(tmp_path) -> None:
    """Section 4c. The reverted attempt filtered BEFORE fusion, and the fusion
    tail re-hydrated the excluded id through ``get_by_ids`` -- which is
    deliberately unfiltered so history stays reachable. The filter therefore
    has to sit after fusion, not before it.
    """
    m = EpisodicMemory(
        db_path=tmp_path / "episodes.db",
        max_episodes=100,
        relevance_threshold=0.3,
        hybrid_recall_enabled=True,
    )
    await m.start()
    try:
        await _store_both(m)
        assert m._fts_db is not None, "FTS sidecar absent -- fusion never ran"

        included = await m.recall(
            "coolant finding", k=10, include_self_contradicted=True,
        )
        assert "marked-1" in {e.id for e in included}, "probe never reached fusion"

        assert "marked-1" not in {
            e.id for e in await m.recall("coolant finding", k=10)
        }
    finally:
        await m.stop()


@pytest.mark.asyncio
async def test_a_result_emptied_by_exclusion_does_not_report_strong(mem) -> None:
    """Section 4c, second half. The band is computed from the raw similarity
    distribution BEFORE the exclusion, so an emptied result would otherwise
    still report ``strong`` and suppress cross-agent recovery."""
    await mem.store(_marked_episode())

    kept, conf_kept = await mem.recall_with_confidence(
        "log the reactor coolant finding", k=5, include_self_contradicted=True,
    )
    assert kept, "probe never reached the branch -- nothing was recalled at all"
    assert conf_kept.band == "strong", (
        "fixture does not discriminate: the band was not strong even WITH the "
        "episode, so an assertion that it is not strong without it proves nothing"
    )

    emptied, conf = await mem.recall_with_confidence(
        "log the reactor coolant finding", k=5,
    )
    assert emptied == []
    assert conf.band != "strong"


@pytest.mark.asyncio
async def test_marked_episode_is_absent_from_recall_weighted(mem) -> None:
    """``recall_weighted`` backs ``oracle_service`` and ``spreading_activation``
    -- squarely EVIDENCE."""
    await _store_both(mem)

    included = await mem.recall_weighted(
        "a1", "coolant finding", k=10, include_self_contradicted=True,
    )
    assert "marked-1" in {rs.episode.id for rs in included}, "probe never reached it"

    kept = await mem.recall_weighted("a1", "coolant finding", k=10)
    assert "marked-1" not in {rs.episode.id for rs in kept}


@pytest.mark.asyncio
async def test_a_keyword_only_hit_cannot_bypass_the_filter_in_recall_weighted(
    tmp_path,
) -> None:
    """``recall_weighted`` merges a SECOND, keyword-only channel that the
    semantic filter never sees, so filtering only its delegate leaks.

    The thresholds are pinned at 0.99 so the semantic pool is provably empty
    and the episode can ONLY arrive through the FTS merge. Both premises are
    asserted below -- without them this test would pass even if the keyword
    branch were never reached.
    """
    m = EpisodicMemory(
        db_path=tmp_path / "episodes.db",
        max_episodes=100,
        relevance_threshold=0.99,
        agent_recall_threshold=0.99,
    )
    await m.start()
    try:
        await m.store(_marked_episode())
        assert m._fts_db is not None, "no FTS sidecar -- the keyword axis never ran"

        # PREMISE 1: the semantic axis returns nothing at this threshold.
        semantic = await m.recall_for_agent_scored(
            "a1", "coolant finding", k=10, include_self_contradicted=True,
        )
        assert semantic == [], (
            "semantic pool is non-empty, so this test does not isolate the "
            "keyword branch it claims to test"
        )

        # PREMISE 2: the keyword axis DOES reach it.
        hits = await m.keyword_search("coolant finding", k=10)
        assert "marked-1" in {eid for eid, _ in hits}, "keyword axis never matched"

        # Therefore anything returned here arrived via the keyword merge alone.
        assert "marked-1" in {
            rs.episode.id
            for rs in await m.recall_weighted(
                "a1", "coolant finding", k=10, include_self_contradicted=True,
            )
        }
        assert "marked-1" not in {
            rs.episode.id
            for rs in await m.recall_weighted("a1", "coolant finding", k=10)
        }
    finally:
        await m.stop()


@pytest.mark.asyncio
async def test_get_by_ids_still_returns_a_marked_episode(mem) -> None:
    """HISTORY is preserved: suppressed, never deleted, never rewritten."""
    await _store_both(mem)

    got = await mem.get_by_ids(["marked-1"])
    assert [e.id for e in got] == ["marked-1"]
    assert got[0].self_contradicted_channels == [WRITE_CHANNEL_NOTEBOOK]


@pytest.mark.asyncio
async def test_get_by_ids_for_evidence_excludes_the_marked_episode(mem) -> None:
    """The classification belongs to the CALL SITE, not to the method.

    ``get_by_ids`` is unfiltered by default so erasure can still reach a marked
    record. But two callers -- ``proactive`` trace exemplars and
    ``diagnostic_context`` procedure exemplars -- put the result straight into
    an LLM prompt, which makes them evidence producers. Same store, same ids,
    two answers, and the unmarked episode is unaffected either way.
    """
    await _store_both(mem)

    ids = ["marked-1", "clean-1"]
    assert {e.id for e in await mem.get_by_ids(ids)} == {"marked-1", "clean-1"}, (
        "premise failed: the fixture did not store both episodes"
    )
    assert {e.id for e in await mem.get_by_ids(ids, for_evidence=True)} == {"clean-1"}


@pytest.mark.asyncio
async def test_get_by_ids_for_evidence_respects_the_config_switch(tmp_path) -> None:
    """Turning the control off restores pre-AD-1293 behaviour on this path too,
    so the evidence flag cannot become a second, unswitchable filter."""
    m = EpisodicMemory(
        db_path=tmp_path / "episodes.db",
        max_episodes=100,
        relevance_threshold=0.3,
        self_contradiction_recall_enabled=False,
    )
    await m.start()
    try:
        await _store_both(m)
        got = await m.get_by_ids(["marked-1"], for_evidence=True)
        assert [e.id for e in got] == ["marked-1"]
    finally:
        await m.stop()


@pytest.mark.asyncio
async def test_list_episodes_is_unfiltered_so_erasure_can_still_reach_it(mem) -> None:
    """``list_episodes`` backs ``knowledge/erasure.py`` and
    ``knowledge/backfill.py``. Filtering it would make a marked episode
    un-erasable -- a data-integrity defect, not a safety control."""
    await _store_both(mem)

    assert "marked-1" in {e.id for e in await mem.list_episodes()}


@pytest.mark.asyncio
async def test_an_unmarked_episode_is_returned_by_every_evidence_surface(mem) -> None:
    """#1200's binding constraint: no true statement becomes less recallable."""
    await _store_both(mem)

    assert "clean-1" in {e.id for e in await mem.recall("coolant finding", k=10)}
    assert "clean-1" in {
        e.id for e in await mem.recall_for_agent("a1", "coolant finding", k=10)
    }
    assert "clean-1" in {e.id for e in await mem.recent(k=10)}
    assert "clean-1" in {e.id for e in await mem.recent_for_agent("a1", k=10)}
    assert "clean-1" in {e.id for e in await mem.recall_by_intent("direct_message", k=10)}
    assert "clean-1" in {
        e.id for e in await mem.recall_by_anchor(channel="dm", agent_id="a1", limit=10)
    }


@pytest.mark.asyncio
async def test_config_off_restores_pre_ad1293_recall(tmp_path) -> None:
    m = EpisodicMemory(
        db_path=tmp_path / "episodes.db",
        max_episodes=100,
        relevance_threshold=0.3,
        self_contradiction_recall_enabled=False,
    )
    await m.start()
    try:
        await _store_both(m)
        assert "marked-1" in {e.id for e in await m.recent(k=10)}
        assert "marked-1" in {e.id for e in await m.recall("coolant finding", k=10)}
    finally:
        await m.stop()


@pytest.mark.asyncio
async def test_marker_survives_a_store_and_reload(mem) -> None:
    """Persistence: the marker must round-trip through Chroma, not just the
    in-memory dataclass."""
    await mem.store(_marked_episode())

    reloaded = await mem.get_by_ids(["marked-1"])
    assert reloaded[0].self_contradicted_channels == [WRITE_CHANNEL_NOTEBOOK]


def test_config_defaults_on() -> None:
    """Default ON: a safety control, not a capability (#13(a))."""
    assert SelfContradictionRecallConfig().enabled is True
