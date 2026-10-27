"""AD-1341 S5 (#1569), M1: the after-action report's format, its chain-of-command review rule and its promotion.

Real Ship's Records and a real Ship's Archive on ``tmp_path``. M1 writes reports directly, in the shape M2's service
writes them; M2's tests cross that seam with the real service.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.oracle_service import OracleService
from probos.knowledge.archive_promotion import (
    exit_note_citations,
    plan_promotion,
    promote_ship_records,
    review_promotion,
)
from probos.knowledge.archive_store import PromotionOutcome, SourceKind
from probos.knowledge.lessons import (
    AFTER_ACTION_KEY,
    AFTER_ACTION_SUBJECT_MAX_CHARS,
    EXIT_NOTE_AGENT_TYPE_MAX_CHARS,
    EXIT_NOTE_CALLSIGN_MAX_CHARS,
    EXIT_NOTE_TIMELINE_MAX_CHARS,
    LESSON_MAX_CHARS,
    LessonLearned,
    after_action_body,
    after_action_path,
    after_action_review_ok,
    parse_lesson,
)
from probos.tools.oracle_query_tool import _MAX_ENTRY_CHARS, OracleQueryTool
from tests.test_ad1341_s1_archive_store import _rows, _store
from tests.test_ad1341_s1_reset_and_erase import _NEXT_SHIP, _SHIP, _data_dir, _records
from tests.test_ad1341_s4_lessons import _LESSON, _WORST_LABEL, _WORST_MARKER

_FLAGGED = "20261027T015500Z"
_DID = f"did:probos:{_SHIP}:pulaski"
_SUPERIOR = {
    "stage": "superior", "outcome": "endorsed", "callsign": "Bones", "agent_type": "diagnostician",
    "did": f"did:probos:{_SHIP}:bones",
}
_SECOND = {
    "stage": "counselor_or_xo", "outcome": "endorsed", "callsign": "Troi", "agent_type": "counselor",
    "did": f"did:probos:{_SHIP}:troi",
}


def _review(*changes: dict[str, Any]) -> list[dict[str, Any]]:
    """The two endorsed stages, each updated with the matching entry of ``changes``."""
    entries = [dict(_SUPERIOR), dict(_SECOND)]
    for entry, change in zip(entries, changes):
        entry.update(change)
    return entries


def _envelope(**changes: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "version": 1, "timeline_id": _SHIP, "callsign": "Pulaski", "agent_type": "surgeon", "author_did": _DID,
        "flagged_at": _FLAGGED, "subject": "Coolant drift alarm, night watch", "source_episode_ids": ["ep-000"],
        "review": _review(),
    }
    envelope.update(changes)
    return envelope


def _without(key: str) -> dict[str, Any]:
    return {name: value for name, value in _envelope().items() if name != key}


async def _write_report(
    records: Any,
    *,
    envelope: Any = None,
    body: str | None = None,
    author: str = "Pulaski",
    classification: str = "ship",
    path: str | None = None,
) -> str:
    """A report in the shape M2's service writes it, written here directly."""
    return await records.write_entry(
        author=author,
        path=path or after_action_path(_SHIP, "surgeon", _FLAGGED),
        content=body if body is not None else after_action_body("Pulaski", "surgeon", _SHIP, _LESSON),
        message="test: an after-action report",
        classification=classification,
        status="submitted",
        topic="After-action report of Pulaski",
        tags=["after-action"],
        extra_frontmatter={AFTER_ACTION_KEY: envelope if envelope is not None else _envelope()},
    )


def test_a_report_has_one_path_per_timeline_billet_and_flag() -> None:
    assert after_action_path("Ship-DID Alpha/0001", "data_analyst", _FLAGGED) == (
        "after-action/ship-did-alpha-0001/data-analyst-20261027t015500z.md"
    )
    for bad in ("2026-10-27T01:55:00Z", "20261027T015500", "20261027T015500Z\n", "", None):
        with pytest.raises(ValueError):
            after_action_path(_SHIP, "surgeon", bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        after_action_path(_SHIP, "///", _FLAGGED)


_REVIEWS: list[tuple[str, object, bool]] = [
    ("both-endorsed", _review(), True),
    ("superior-vacant", _review({"outcome": "vacant", "callsign": "", "agent_type": "", "did": ""}), True),
    ("second-vacant", _review({}, {"outcome": "vacant"}), True),
    ("both-vacant", _review({"outcome": "vacant"}, {"outcome": "vacant"}), False),
    ("superior-returned", _review({"outcome": "returned"}), False),
    ("second-not-reviewed", _review({}, {"outcome": "not_reviewed"}), False),
    ("unknown-outcome", _review({"outcome": "approved"}), False),
    ("stages-swapped", list(reversed(_review())), False),
    ("one-stage", _review()[:1], False),
    ("three-entries", [*_review(), dict(_SECOND)], False),
    ("reviewer-holds-the-author-s-billet", _review({"agent_type": "surgeon"}), False),
    ("one-billet-endorses-twice", _review({}, {"agent_type": "diagnostician"}), False),
    ("callsign-on-two-lines", _review({"callsign": "Bones\nTroi"}), False),
    ("no-did", _review({"did": ""}), False),
    ("not-a-list", "endorsed", False),
    ("entry-not-a-mapping", [dict(_SUPERIOR), "endorsed"], False),
]


@pytest.mark.parametrize(("review", "admitted"), [case[1:] for case in _REVIEWS], ids=[case[0] for case in _REVIEWS])
def test_the_review_rule_admits_only_a_chain_that_endorsed(review: object, admitted: bool) -> None:
    assert after_action_review_ok(review, "surgeon") is admitted


async def test_a_reviewed_report_is_promoted_with_its_own_provenance(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_report(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        report = await promote_ship_records(records, archive, timeline_id=_NEXT_SHIP)
    finally:
        await archive.close()

    assert report.created == (path,)
    rows = _rows(
        tmp_path / "archive.db",
        "SELECT timeline_id, source_kind, category, title, author_callsign, author_agent_type, author_did, "
        "source_episode_ids, classification, content, metadata FROM archive",
    )
    assert len(rows) == 1
    timeline, kind, category, title, callsign, agent_type, did, cited, classification, content, metadata = rows[0]
    assert (timeline, kind, category) == (_SHIP, "after_action", "after_action")  # the timeline that wrote it
    assert (title, callsign, agent_type, did) == ("After-action report of Pulaski", "Pulaski", "surgeon", _DID)
    assert (cited, classification) == ('["ep-000"]', "ship")
    assert content == after_action_body("Pulaski", "surgeon", _SHIP, _LESSON)
    assert '"endorsed_by": ["Bones", "Troi"]' in metadata
    assert '"subject": "Coolant drift alarm, night watch"' in metadata


_BREAKS: dict[str, dict[str, Any]] = {
    "version-true": {"envelope": _envelope(version=True)},
    "version-2": {"envelope": _envelope(version=2)},
    "another-timeline": {"envelope": _envelope(timeline_id=_NEXT_SHIP)},
    "callsign-on-two-lines": {"envelope": _envelope(callsign="Pulaski\nBones")},
    "flag-not-a-stamp": {"envelope": _envelope(flagged_at="2026-10-27")},
    "subject-too-long": {"envelope": _envelope(subject="s" * (AFTER_ACTION_SUBJECT_MAX_CHARS + 1))},
    "subject-on-two-lines": {"envelope": _envelope(subject="Coolant\ndrift")},
    "subject-missing": {"envelope": _without("subject")},
    "thirteen-citations": {"envelope": _envelope(source_episode_ids=[f"ep-{i:03d}" for i in range(13)])},
    "a-citation-twice": {"envelope": _envelope(source_episode_ids=["ep-000", "ep-000"])},
    "review-returned": {"envelope": _envelope(review=_review({"outcome": "returned"}))},
    "review-missing": {"envelope": _without("review")},
    "envelope-not-a-mapping": {"envelope": "after action"},
    "author-not-the-callsign": {"author": "Bones"},
    "body-with-a-preamble": {"body": "Preamble.\n\n" + after_action_body("Pulaski", "surgeon", _SHIP, _LESSON)},
    "body-not-in-the-format": {"body": "We should log every alarm."},
    "department-classified": {"classification": "department"},
}


@pytest.mark.parametrize("case", sorted(_BREAKS))
async def test_a_report_that_breaks_the_rule_is_withheld_and_stops_nothing(tmp_path: Path, case: str) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_report(records, **_BREAKS[case])

    plan = await plan_promotion(records, timeline_id=_NEXT_SHIP)

    assert plan.records == () and plan.withheld == (path,)
    assert await exit_note_citations(records, None) == {}  # one rule: the erasure's read never counts it either


async def test_a_report_is_archived_once_whichever_promotion_archives_it(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_report(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        first = await promote_ship_records(records, archive, timeline_id=_SHIP)
        second = await promote_ship_records(records, archive, timeline_id=_NEXT_SHIP)
    finally:
        await archive.close()

    assert first.created == (path,)
    assert second.created == () and second.present == (path,)


async def test_the_erasure_read_counts_a_report_only_while_the_next_promotion_would_archive_it(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_report(records)
    later = "20261027T020000Z"
    returned = await _write_report(
        records, envelope=_envelope(flagged_at=later, review=_review({"outcome": "returned"})),
        path=after_action_path(_SHIP, "surgeon", later),
    )
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        before = await exit_note_citations(records, archive)
        await archive.veto_source(SourceKind.AFTER_ACTION_REPORT, path, "not canon")  # the veto lands between the reads
        after = await exit_note_citations(records, archive)
        promoted = await promote_ship_records(records, archive, timeline_id=_SHIP)
    finally:
        await archive.close()

    assert before == {"ep-000": (path,)}  # the endorsed report counts; the returned one never does
    assert after == {}
    assert promoted.vetoed == (path,) and promoted.created == ()
    assert returned in promoted.withheld


async def test_a_report_at_every_bound_reaches_a_later_crew_whole_through_the_oracle_tool(tmp_path: Path) -> None:
    """S4's L6 for a report: the lesson at ``LESSON_MAX_CHARS`` and the callsign, agent type and timeline at their
    bounds reach a later crew whole through the real Oracle tool, with room for the longest label and marker."""
    names = ("OBS_BODY", "DISCUSSION_BODY", "LESSON_BODY", "RECOMMENDATION_BODY")
    bodies = tuple(f"{name} " + "x" * (LESSON_MAX_CHARS // 4 - len(name) - 1) for name in names)
    longest = LessonLearned(*bodies)
    assert parse_lesson(longest.render()) == longest  # premise: at the bound
    callsign, agent_type, timeline = (
        "C" * EXIT_NOTE_CALLSIGN_MAX_CHARS, "a" * EXIT_NOTE_AGENT_TYPE_MAX_CHARS, "t" * EXIT_NOTE_TIMELINE_MAX_CHARS,
    )
    records = _records(_data_dir(tmp_path))
    path = await _write_report(
        records,
        author=callsign,
        body=after_action_body(callsign, agent_type, timeline, longest),
        envelope=_envelope(
            timeline_id=timeline, callsign=callsign, agent_type=agent_type,
            subject="s" * AFTER_ACTION_SUBJECT_MAX_CHARS,
        ),
        path=after_action_path(timeline, agent_type, _FLAGGED),
    )
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        assert (await promote_ship_records(records, archive, timeline_id=_NEXT_SHIP)).created == (path,)
        oracle = OracleService(archive_store=archive)
        oracle.attach_current_timeline(_NEXT_SHIP)  # a later crew reads it
        result = await OracleQueryTool(oracle=oracle).invoke({"query": "RECOMMENDATION_BODY", "kind": "archive"})
    finally:
        await archive.close()

    assert not result.error and result.metadata["returned_count"] == 1
    entry = result.output[result.output.index("[source:archive"):].rstrip("\n")
    marker, label = entry.splitlines()[:2]
    assert label.startswith("[Inherited from ")  # S2's label first: inherited, never the agent's own memory
    assert "[entry shortened]" not in entry
    for body in bodies:
        assert body in entry
    worst = len(entry) - len(marker) - len(label) + len(_WORST_MARKER) + len(_WORST_LABEL)
    assert worst <= _MAX_ENTRY_CHARS


async def test_the_captain_s_review_lists_a_report_with_what_promoting_it_would_do(tmp_path: Path) -> None:
    records = _records(_data_dir(tmp_path))
    path = await _write_report(records)
    archive = _store(tmp_path)
    await archive.initialize()
    try:
        review = await review_promotion(records, archive, timeline_id=_SHIP)
    finally:
        await archive.close()

    assert [(source.record.source_ref, source.record.source_kind, source.state.outcome) for source in review.sources] == [
        (path, SourceKind.AFTER_ACTION_REPORT, PromotionOutcome.CREATED),
    ]


def _alias_document(field: str, shape: str) -> str:
    """A published report whose ``field`` is a YAML alias graph (register F-661): a deep chain, or a doubling graph."""
    if shape == "alias-chain-5000":
        anchors = ["n0: &n0 [x]", *(f"n{i}: &n{i} [*n{i - 1}]" for i in range(1, 5000))]
        top = 4999
    else:
        anchors = ["n0: &n0 [x]", *(f"n{i}: &n{i} [*n{i - 1}, *n{i - 1}]" for i in range(1, 23))]
        top = 22
    values = {
        "author": "Bones", "classification": "ship", "status": "published", "topic": "Alias report",
        "department": "medical",
    }
    lines = [f"{name}: {value}" for name, value in values.items() if name != field]
    return "---\n" + "\n".join([*lines, *anchors, f"{field}: *n{top}"]) + "\n---\n\nReport body.\n"


@pytest.mark.parametrize("shape", ["alias-chain-5000", "alias-dag-22x2"])
@pytest.mark.parametrize("field", ["topic", "department", "author"])
async def test_a_frontmatter_value_that_is_a_container_is_archived_as_no_value(
    tmp_path: Path, field: str, shape: str,
) -> None:
    records = _records(_data_dir(tmp_path))
    target = records.repo_path / "reports" / "alias.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_alias_document(field, shape), encoding="utf-8")

    started = time.perf_counter()
    plan = await plan_promotion(records, timeline_id=_SHIP)

    # A hang guard only: a walked graph raises RecursionError or fails the assertions below. A CI runner took 2.1 s here (0.65 s on the author's host).
    assert time.perf_counter() - started < 30.0
    [record] = plan.records
    assert record.source_ref == "reports/alias.md"
    if field == "topic":
        assert record.title == "alias"  # the file name, as for a blank topic (S1 A3)
    elif field == "department":
        assert record.metadata["department"] == ""
    else:
        assert record.author_callsign == ""
