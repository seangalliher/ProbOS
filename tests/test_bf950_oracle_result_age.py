"""BF-950 (#1742): an oracle_query result is aged by its own write time, not by its retrieval.

On the base every marker read ``age:0s``: ``ProvenanceEnvelope.from_oracle_result`` stamped the
retrieval time and the tool rendered the marker in the same call, so ``STALE`` could never appear.
Real fixtures where the chain matters: a real ``RecordsStore`` on ``tmp_path`` read through the real
``OracleService`` and ``OracleQueryTool`` (T1), and the real self-monitoring pull read back through
both ``<notebook>`` renderers (T9). Names the fix adds are reached inside tests, never imported at
module level, so the file collects on the base.
"""

from __future__ import annotations

import math
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

import probos.cognitive.provenance as provenance
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.oracle_service import OracleResult, OracleService, make_reader_identity_resolver
from probos.cognitive.provenance import ProvenanceEnvelope, ProvenanceTag, query_with_provenance
from probos.config import RecordsConfig
from probos.crew_profile import Rank
from probos.knowledge.records_store import RecordsStore
from probos.proactive import ProactiveCognitiveLoop
from probos.tools.oracle_query_tool import _ORACLE_DISPOSITION, OracleQueryTool


_DAY = 86400.0
_FORTY_DAYS_AGO = 40 * _DAY + 3600.0


def _result(
    tier: str, metadata: Any, *, score: float = 0.5, content: str = "entry body",
) -> OracleResult:
    return OracleResult(source_tier=tier, content=content, score=score, metadata=metadata, provenance=f"[{tier}]")


def _marker(result: OracleResult) -> str:
    return ProvenanceEnvelope.from_oracle_result(result).tag.format_inline()


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _entry_marker(output: str, needle: str) -> str:
    """The provenance marker of the one rendered entry whose body holds ``needle``."""
    entries = [chunk for chunk in output.split("\n[source:")[1:] if needle in chunk]
    assert len(entries) == 1, output  # premise: the entry was rendered once
    return "[source:" + entries[0].splitlines()[0]


class _ScriptedOracle:
    def __init__(self, results: list[OracleResult]) -> None:
        self._results = list(results)

    async def query(self, query_text: str = "", **_kwargs: Any) -> list[OracleResult]:
        return list(self._results)


async def _records(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


def _rewrite_frontmatter(store: RecordsStore, path: str, **fields: Any) -> dict[str, Any]:
    """Set ``fields`` in a written entry's frontmatter, in the store's own YAML form; returns what loads back."""
    file = store.repo_path / path
    _, header, body = file.read_text(encoding="utf-8").split("---", 2)
    frontmatter = yaml.safe_load(header)
    frontmatter.update(fields)
    file.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)}---{body}", encoding="utf-8",
    )
    _, reread, _ = file.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(reread)


async def _self_monitoring(store: Any, callsign: str, *, pending: str | None = None) -> dict[str, Any]:
    """BF-949's harness (``tests/test_bf949_notebook_reader_identity.py``): trust 0.75, no posts, no episodes."""
    agent = SimpleNamespace(
        id=f"id-{callsign}", agent_type="engineering_agent", callsign=callsign,
        rank=Rank.COMMANDER, department="engineering", sovereign_id=f"id-{callsign}",
    )
    trust = MagicMock()
    trust.get_score = MagicMock(return_value=0.75)
    ward_room = MagicMock()
    ward_room.get_posts_by_author = AsyncMock(return_value=[])
    runtime = SimpleNamespace(
        ward_room=ward_room, episodic_memory=None, _records_store=store, trust_network=trust,
        _lifecycle_state="warm_boot", _start_time_wall=time.time() - 7200,
    )
    loop = ProactiveCognitiveLoop(interval=120.0, cooldown=300.0)
    if pending is not None:
        loop._pending_notebook_reads[agent.id] = pending
    return await loop._build_self_monitoring_context(agent, callsign, runtime)


def _sensorium_render(self_monitoring: dict[str, Any]) -> str:
    agent = CognitiveAgent.__new__(CognitiveAgent)
    return agent._sensorium_ext_self_monitoring({"_context_parts": {"self_monitoring": self_monitoring}})


async def _proactive_render(self_monitoring: dict[str, Any]) -> str:
    """The proactive prompt, built as ``tests/test_self_monitoring.py`` builds it."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._recent_post_count = 0
    agent._temporal_context = None
    agent._build_temporal_context = lambda: ""
    agent._format_memory_section = lambda memories: ["(memories)"]
    observation = {
        "intent": "proactive_think",
        "params": {
            "context_parts": {"self_monitoring": self_monitoring},
            "trust_score": 0.65,
            "agency_level": "suggestive",
            "rank": "lieutenant",
            "duty": None,
        },
    }
    return await agent._build_user_message(observation)


def _notebook_tags(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("<notebook ")]


def _mock_records(entry: dict[str, Any]) -> MagicMock:
    records = MagicMock()
    records.list_entries = AsyncMock(return_value=[])
    records.read_entry = AsyncMock(return_value=entry)
    return records


# ── M2: the age is the content's own ──────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["hand-written-date", "store-written-iso"])
async def test_an_old_record_reaches_the_agent_with_its_own_age_and_marked_stale(tmp_path: Path, shape: str) -> None:
    """Acceptance 1 through the real store, Oracle and tool. ``updated`` is 185 days back: a YAML date (an
    operator's hand edit) or the ISO text ``RecordsStore.write_entry`` writes."""
    store = await _records(tmp_path)
    path = "notebooks/Anvil/deck12-inspection.md"
    await store.write_notebook(
        "Anvil", "deck12-inspection", "zxqdecktwelve inspection closed without findings",
        department="engineering", classification="ship",
    )
    old = datetime.now(timezone.utc) - timedelta(days=185)
    updated: Any = old.date() if shape == "hand-written-date" else old.isoformat(timespec="seconds")
    loaded = _rewrite_frontmatter(store, path, updated=updated, revision=4)
    assert loaded["updated"] == updated  # premise: the YAML round trip keeps the shape
    written = (
        datetime(old.year, old.month, old.day, tzinfo=timezone.utc).timestamp()
        if shape == "hand-written-date"
        else datetime.fromisoformat(updated).timestamp()
    )
    oracle = OracleService(records_store=store)
    oracle.attach_reader_identity_resolver(make_reader_identity_resolver(
        registry=SimpleNamespace(
            get=lambda aid: SimpleNamespace(agent_type="engineer", callsign="WRENCH", sovereign_id="")
            if aid == "agent-b" else None,
            all=lambda: [],
        ),
        ontology=SimpleNamespace(get_agent_department=lambda _t: "engineering"),
    ))

    result = await OracleQueryTool(oracle=oracle).invoke(
        {"query": "zxqdecktwelve", "kind": "records"}, {"agent_id": "agent-b"},
    )

    assert result.error is None  # premise
    marker = _entry_marker(result.output, "zxqdecktwelve inspection closed")
    match = re.fullmatch(r"\[source:records relevance:\d\.\d{2} age:(\d+)d STALE\]", marker)
    assert match is not None, marker
    expected = int((time.time() - written) // _DAY)
    assert expected - 1 <= int(match.group(1)) <= expected + 1


_TIMESTAMPED = [
    pytest.param("records", lambda ts: {"path": "p.md", "frontmatter": {"updated": _iso(ts)}}, id="records-updated"),
    pytest.param("records", lambda ts: {"path": "p.md", "frontmatter": {"created": _iso(ts)}}, id="records-created-only"),
    pytest.param(
        "records", lambda ts: {"path": "p.md", "frontmatter": {"updated": "not a date", "created": _iso(ts)}},
        id="records-bad-updated-uses-created",
    ),
    pytest.param("archive", lambda ts: {"archive_id": "a1", "archived_at": ts}, id="archive"),
    pytest.param("operational", lambda ts: {"timestamp": ts}, id="operational"),
    pytest.param("semantic", lambda ts: {"id": "skill_x", "type": "skill", "indexed_at": ts}, id="semantic"),
    pytest.param("episodic", lambda ts: {"episode_id": "ep-1", "timestamp": ts}, id="episodic"),
]


@pytest.mark.parametrize(("tier", "metadata"), _TIMESTAMPED)
def test_each_tier_is_aged_by_its_own_write_time(tier: str, metadata: Any) -> None:
    written = time.time() - _FORTY_DAYS_AGO
    assert _marker(_result(tier, metadata(written))) == f"[source:{tier} relevance:0.50 age:40d STALE]"


@pytest.mark.parametrize(("tier", "metadata"), [
    pytest.param("graph", {"edge_id": "e1", "relation": "reports_to", "weight": 1.0}, id="graph"),
    pytest.param("health", {"metric": "pool", "pool": "builders", "current_size": 2}, id="health"),
])
def test_a_tier_that_records_no_write_time_shows_no_age(tier: str, metadata: dict[str, Any]) -> None:
    envelope = ProvenanceEnvelope.from_oracle_result(_result(tier, metadata))
    assert envelope.render().splitlines()[0] == f"[source:{tier} relevance:0.50]"
    assert envelope.tag.age_seconds is None and envelope.tag.is_stale is False


@pytest.mark.parametrize(("ago", "age", "stale"), [
    pytest.param(-3600.0, "0s", False, id="written-in-the-future"),
    pytest.param(5.0, "5s", False, id="seconds"),
    pytest.param(29 * _DAY + 3600.0, "29d", False, id="twenty-nine-days"),
    pytest.param(31 * _DAY, "31d", True, id="thirty-one-days"),
])
def test_stale_marks_only_content_older_than_thirty_days(ago: float, age: str, stale: bool) -> None:
    assert provenance.STALE_AFTER_SECONDS == 30 * _DAY
    tag = ProvenanceTag(
        source_tier="records", retrieval_timestamp=time.time(), relevance=0.5, content_hash="abcdef12",
        content_timestamp=time.time() - ago,
    )
    assert tag.format_inline() == f"[source:records relevance:0.50 age:{age}{' STALE' if stale else ''}]"
    assert tag.is_stale is stale
    assert tag.age_seconds >= 0


_UNPARSEABLE = [
    pytest.param({"updated": "yesterday"}, id="words"),
    pytest.param({"updated": ""}, id="empty-text"),
    pytest.param({"updated": None}, id="none"),
    pytest.param({"updated": True}, id="a-bool"),
    pytest.param({"updated": 0}, id="zero"),
    pytest.param({"updated": -5}, id="negative"),
    pytest.param({"updated": math.nan}, id="nan"),
    pytest.param({"updated": math.inf}, id="infinity"),
    pytest.param({"updated": 10**400}, id="too-large-for-a-float"),
    pytest.param({"updated": 1e13}, id="after-the-year-9999"),
    pytest.param({"updated": date(1960, 1, 1)}, id="before-1970"),
    pytest.param({"updated": ["2026-05-03"]}, id="a-list"),
    pytest.param("updated: 2026-05-03", id="frontmatter-not-a-mapping"),
]


@pytest.mark.parametrize("frontmatter", _UNPARSEABLE)
def test_a_write_time_that_does_not_parse_shows_no_age(frontmatter: Any) -> None:
    tag = ProvenanceEnvelope.from_oracle_result(
        _result("records", {"path": "p.md", "frontmatter": frontmatter}),
    ).tag
    assert tag.format_inline() == "[source:records relevance:0.50]"
    assert tag.age_seconds is None and tag.is_stale is False


@pytest.mark.asyncio
async def test_one_bad_write_time_does_not_empty_the_result() -> None:
    """``query_with_provenance`` answers any exception with ``[]``, so a parser that raised would drop every entry."""
    written = time.time() - _FORTY_DAYS_AGO
    oracle = _ScriptedOracle([
        _result("records", {"path": "p.md", "frontmatter": {"updated": 10**400}}, score=0.9, content="RECORD body"),
        _result("archive", {"archive_id": "a1", "archived_at": written}, score=0.8, content="ARCHIVE body"),
    ])

    result = await OracleQueryTool(oracle=oracle).invoke({"query": "anything"})

    assert result.error is None and result.metadata["returned_count"] == 2
    assert _entry_marker(result.output, "RECORD body") == "[source:records relevance:0.90]"
    assert _entry_marker(result.output, "ARCHIVE body") == "[source:archive relevance:0.80 age:40d STALE]"


@pytest.mark.asyncio
async def test_the_oracle_order_and_relevance_are_unchanged() -> None:
    """Acceptance 4: provenance renders only. Passes on the base and after."""
    results = [
        _result("records", {"path": "a.md", "frontmatter": {}}, score=0.9, content="first"),
        _result("graph", {"edge_id": "e1"}, score=0.4, content="second"),
        _result("archive", {"archive_id": "a1", "archived_at": 1.0e9}, score=0.7, content="third"),
    ]

    envelopes = await query_with_provenance(
        _ScriptedOracle(results), query_text="q", tiers=["records", "graph", "archive"],
    )

    assert [e.content for e in envelopes] == ["first", "second", "third"]
    assert [e.tag.relevance for e in envelopes] == [0.9, 0.4, 0.7]
    assert [e.tag.source_tier for e in envelopes] == ["records", "graph", "archive"]
    assert all(e.tag.metadata is r.metadata for e, r in zip(envelopes, results))


# ── M3: the preamble and the description ──────────────────────────────


def test_the_preamble_and_the_description_say_what_the_marker_carries() -> None:
    assert "where its store records when the entry was written" in _ORACLE_DISPOSITION
    assert "marked STALE past thirty days" in _ORACLE_DISPOSITION
    assert "an entry with no age has no recorded write time" in _ORACLE_DISPOSITION
    assert getattr(provenance, "STALE_AFTER_SECONDS", None) == 30 * _DAY  # the words and the constant agree
    description = OracleQueryTool(oracle=None).description
    assert "a retrieval relevance score and, where its store records when it was written, its age." in description
    assert "and an age" not in description
    for text in (_ORACLE_DISPOSITION, description):
        assert _CAPABILITY_GAP_RE.search(text) is None


def test_the_crew_consult_preamble_promises_only_what_its_entries_carry() -> None:
    """Review round 1 (F2): the crew consult's own preamble promised every entry an age and a STALE flag.

    ``crew_executor._render_commons_entry`` dates an entry only from a numeric ``metadata["timestamp"]`` and
    never writes ``STALE``, so a forty-day-old entry is rendered with an age and no flag. The preamble and the
    renderer are held together here, as AD-1294's crossing test holds the other fields.
    """
    from probos.cognitive.crew_executor import _COMMONS_DISPOSITION, _render_commons_entry

    rendered = _render_commons_entry(
        _result("operational", {"timestamp": time.time() - _FORTY_DAYS_AGO}, score=0.71),
    )
    assert "40d ago" in rendered  # premise: an old entry with a numeric timestamp is dated
    assert ("STALE" in _COMMONS_DISPOSITION) == ("STALE" in rendered)
    assert "and sometimes an age, so weigh a weakly-matching or old entry lightly." in _COMMONS_DISPOSITION
    assert _CAPABILITY_GAP_RE.search(_COMMONS_DISPOSITION) is None


# ── M4: the notebook read-back ────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["semantic-pull", "pending-read"])
async def test_the_notebook_read_back_carries_the_entrys_date_and_revision(tmp_path: Path, path: str) -> None:
    """Acceptance 3: a real store, the real pull, and both renderers of the block."""
    store = await _records(tmp_path)
    await store.write_notebook("Zephyr", "own-topic", "engineering notes of my own", department="engineering")
    _rewrite_frontmatter(store, "notebooks/Zephyr/own-topic.md", updated="2026-05-03T10:00:00+00:00", revision=4)

    result = await _self_monitoring(store, "Zephyr", pending="own-topic" if path == "pending-read" else None)

    content = result["notebook_content"]
    assert content["topic"] == "own-topic" and "engineering notes of my own" in content["snippet"]  # premise
    expected = '<notebook topic="own-topic" updated="2026-05-03T10:00:00+00:00" revision="4">'
    assert _notebook_tags(_sensorium_render(result)) == [expected]
    proactive_tags = _notebook_tags(await _proactive_render(result))
    assert proactive_tags and set(proactive_tags) == {expected}


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", [
    pytest.param({"content": "Notebook body"}, id="no-frontmatter"),
    pytest.param(
        {"content": "Notebook body", "frontmatter": {"updated": "yesterday", "revision": "4"}}, id="nothing-parses",
    ),
    pytest.param(
        {"content": "Notebook body", "frontmatter": {"updated": None, "revision": True}}, id="none-and-a-bool",
    ),
])
async def test_a_read_back_with_nothing_that_parses_keeps_the_bare_tag(entry: dict[str, Any]) -> None:
    """Compatibility: passes on the base and after."""
    result = await _self_monitoring(_mock_records(entry), "Bones", pending="my-topic")
    assert result["notebook_content"]["snippet"] == "Notebook body"  # premise: the pending read ran
    assert _notebook_tags(_sensorium_render(result)) == ['<notebook topic="my-topic">']


@pytest.mark.asyncio
@pytest.mark.parametrize(("frontmatter", "expected"), [
    pytest.param(
        {"updated": date(2026, 5, 3), "revision": True},
        '<notebook topic="my-topic" updated="2026-05-03T00:00:00+00:00">', id="a-yaml-date-and-a-bool-revision",
    ),
    pytest.param(
        {"updated": "2026-05-03T10:00:00", "revision": 0},
        '<notebook topic="my-topic" updated="2026-05-03T10:00:00+00:00">', id="naive-text-and-revision-zero",
    ),
    pytest.param(
        {"created": "2026-04-01T08:00:00+00:00", "revision": 7},
        '<notebook topic="my-topic" updated="2026-04-01T08:00:00+00:00" revision="7">', id="created-only",
    ),
])
async def test_a_read_back_keeps_what_parses_and_drops_what_does_not(
    frontmatter: dict[str, Any], expected: str,
) -> None:
    result = await _self_monitoring(
        _mock_records({"content": "Notebook body", "frontmatter": frontmatter}), "Bones", pending="my-topic",
    )
    assert result["notebook_content"]["snippet"] == "Notebook body"  # premise
    assert _notebook_tags(_sensorium_render(result)) == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["a-yaml-date-beside-text", "a-text-revision", "a-list-topic"])
async def test_one_hand_edited_entry_does_not_cost_the_read_back(tmp_path: Path, shape: str) -> None:
    """Review round 1 (F1): one notebook entry edited outside the store ended the whole block for the cycle.

    The index sorted the raw ``updated`` (a YAML date beside the store's text raised), the repetition check
    compared the raw ``revision`` (text raised), and the topic count hashed the raw ``topic``; each sat inside
    the error boundary of the read-back, so the agent lost the read-back with the index. A real store, its
    files edited as a person would edit them.
    """
    store = await _records(tmp_path)
    now = time.time()
    await store.write_notebook("Zephyr", "first-topic", "engineering notes, first", department="engineering")
    await store.write_notebook("Zephyr", "second-topic", "engineering notes, second", department="engineering")
    first, second = "notebooks/Zephyr/first-topic.md", "notebooks/Zephyr/second-topic.md"
    if shape == "a-yaml-date-beside-text":
        assert type(_rewrite_frontmatter(store, first, updated=date(2026, 5, 3))["updated"]) is date  # premise
        assert type(_rewrite_frontmatter(store, second)["updated"]) is str  # premise: the store writes text
    elif shape == "a-text-revision":
        assert type(_rewrite_frontmatter(store, first, updated=_iso(now), revision="4")["revision"]) is str  # premise
        _rewrite_frontmatter(store, second, updated=_iso(now - 3600), revision=5)
    else:
        assert type(_rewrite_frontmatter(store, first, topic=["engines", "warp"])["topic"]) is list  # premise

    result = await _self_monitoring(store, "Zephyr")

    content = result["notebook_content"]
    assert content["topic"] in {"first-topic", "second-topic"} and "engineering notes" in content["snippet"]
    tags = _notebook_tags(_sensorium_render(result))
    assert len(tags) == 1 and tags[0].startswith(f'<notebook topic="{content["topic"]}" updated="'), tags
    if shape == "a-yaml-date-beside-text":
        assert [entry["topic"] for entry in result["notebook_index"]] == ["second-topic", "first-topic"]
    elif shape == "a-text-revision":
        warnings = result.get("notebook_repetition_warnings", [])
        assert len(warnings) == 1 and "second-topic 5 times" in warnings[0], warnings


@pytest.mark.asyncio
@pytest.mark.parametrize(("topic", "updated"), [
    pytest.param(17, None, id="a-number-topic"),
    pytest.param(None, False, id="a-null-topic"),
    pytest.param(["engines", "warp"], None, id="a-list-topic"),
    pytest.param("", None, id="a-blank-topic"),
])
async def test_an_index_topic_that_is_not_text_does_not_end_the_block(
    tmp_path: Path, topic: Any, updated: Any,
) -> None:
    """Review round 2 (F3): an index entry with an empty ``updated`` is rendered by its bare topic.

    So a topic edited outside the store into a number or a null raised in ``", ".join`` in both renderers,
    and the sensorium dispatcher dropped the whole self-monitoring extension, read-back included. A list
    topic ended the index at the topic count, and a blank one rendered as an empty item. The index now names
    such an entry by its file. A real store, its file edited as a person would edit it.
    """
    store = await _records(tmp_path)
    await store.write_notebook("Zephyr", "first-topic", "engineering notes, first", department="engineering")
    await store.write_notebook("Zephyr", "second-topic", "engineering notes, second", department="engineering")
    first, second = "notebooks/Zephyr/first-topic.md", "notebooks/Zephyr/second-topic.md"
    edited = _rewrite_frontmatter(store, first, topic=topic, updated=updated)
    assert edited["topic"] == topic and edited["updated"] is updated  # premise
    second_updated = _rewrite_frontmatter(store, second)["updated"]
    assert type(second_updated) is str  # premise: the store writes text

    result = await _self_monitoring(store, "Zephyr")

    expected_items = {"first-topic", f"second-topic (updated {second_updated})"}
    for text in (_sensorium_render(result), await _proactive_render(result)):
        lines = [line for line in text.splitlines() if line.startswith("Your notebooks: [")]
        assert lines and len(set(lines)) == 1, text
        assert set(lines[0][len("Your notebooks: ["):-1].split(", ")) == expected_items, lines[0]
        assert any(tag.startswith('<notebook topic="') for tag in _notebook_tags(text)), text
    assert result["notebook_summary"] == {"total_entries": 2, "total_topics": 2}
    assert "engineering notes" in result["notebook_content"]["snippet"]


@pytest.mark.asyncio
async def test_two_files_named_by_their_files_stay_two_items(tmp_path: Path) -> None:
    """Review round 3 (F5): an index entry named by its file kept nothing of an embedded ``.md``.

    Amendment 2 names an entry whose topic is not text by its file, and that fallback removed every ``.md``.
    So ``notes.md`` and ``notes.md.md`` (the store names a file ``f"{slug}.md"``) both showed as ``notes``,
    and the topic count fell from 2 to 1. A real store, both files edited as a person would edit them.
    """
    store = await _records(tmp_path)
    await store.write_notebook("Zephyr", "notes", "engineering notes, first", department="engineering")
    await store.write_notebook("Zephyr", "notes.md", "engineering notes, second", department="engineering")
    for path, topic in (("notebooks/Zephyr/notes.md", 17), ("notebooks/Zephyr/notes.md.md", 27)):
        edited = _rewrite_frontmatter(store, path, topic=topic, updated=None)
        assert edited["topic"] == topic and edited["updated"] is None  # premise

    result = await _self_monitoring(store, "Zephyr")

    for text in (_sensorium_render(result), await _proactive_render(result)):
        lines = [line for line in text.splitlines() if line.startswith("Your notebooks: [")]
        assert lines and len(set(lines)) == 1, text
        assert sorted(lines[0][len("Your notebooks: ["):-1].split(", ")) == ["notes", "notes.md"], lines[0]
    assert result["notebook_summary"] == {"total_entries": 2, "total_topics": 2}
    assert "engineering notes" in result["notebook_content"]["snippet"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "frontmatter", "shown"), [
    pytest.param("notebooks/Zephyr/notes.md.md", {"topic": 27}, "notes.md", id="an-embedded-md"),
    pytest.param("notebooks/Zephyr/.md.md", {}, ".md", id="a-doubled-bare-md"),
    pytest.param("notebooks/Zephyr/.md", {"topic": None}, ".md", id="a-bare-md"),
    pytest.param("notebooks/Zephyr/notes.md", {"topic": 27}, "notes", id="a-plain-file"),
])
async def test_an_index_name_from_the_file_keeps_all_but_its_final_md(
    path: str, frontmatter: dict[str, Any], shown: str,
) -> None:
    """Review round 3 (F5): the fallback removes only the final ``.md``, and shows the whole name when nothing is left.

    The records API names a file ``f"{topic}.md"`` from any JSON topic, so ``""`` gives ``.md`` and ``.md`` gives
    ``.md.md``; every-``.md`` removal showed both as an empty item. A listing as ``list_entries`` returns it, so no
    dot-file listing rule is assumed. ``a-plain-file`` is the unchanged case; it passed on M13, before the fix.
    """
    records = MagicMock()
    records.list_entries = AsyncMock(return_value=[{"path": path, "frontmatter": frontmatter}])
    records.read_entry = AsyncMock(return_value=None)
    records.search = AsyncMock(return_value=[])

    result = await _self_monitoring(records, "Zephyr")

    assert [entry["topic"] for entry in result["notebook_index"]] == [shown]
    assert result["notebook_summary"] == {"total_entries": 1, "total_topics": 1}
    for text in (_sensorium_render(result), await _proactive_render(result)):
        assert f"Your notebooks: [{shown}]" in text.splitlines(), text


@pytest.mark.asyncio
async def test_a_failed_index_does_not_cost_the_read_back() -> None:
    """§16 item 14 under mutation (NBM-12): the read-back runs whenever the listing returned entries.

    Since Amendment 2 no frontmatter a real store lists is known to end the index (L15), so the failure is
    injected: a listing entry without the ``path`` that ``RecordsStore.list_entries`` always sets.
    Passes on M10 and after.
    """
    records = MagicMock()
    records.list_entries = AsyncMock(return_value=[{"frontmatter": {"author": "Bones"}}])
    records.search = AsyncMock(return_value=[{
        "path": "notebooks/Bones/own-topic.md", "snippet": "engineering notes of my own",
        "frontmatter": {"updated": "2026-05-03T10:00:00+00:00"},
    }])

    result = await _self_monitoring(records, "Bones")

    assert "notebook_summary" not in result and "notebook_index" not in result  # premise: the enrichment raised
    assert result["notebook_content"]["topic"] == "own-topic"
    assert _notebook_tags(_sensorium_render(result)) == [
        '<notebook topic="own-topic" updated="2026-05-03T10:00:00+00:00">',
    ]
