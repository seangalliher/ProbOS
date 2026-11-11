"""BF-952 (#1751): Ship's Records keyword search matches whole words and ranks rare ones first.

On the base ``RecordsStore.search`` scored a record by the fraction of query words found as substrings
of the raw file, YAML keys included, and broke ties by path: ``i`` matched "ship", ``status`` matched
every record, and a conversational question matched every record at one score, so the paths that sort
first won. It also ran its whole walk on the event loop. Real fixtures throughout: a real
``RecordsStore`` on ``tmp_path`` with records written to disk as a person or the store writes them,
the real ``OracleService`` (T9), the real self-monitoring pull (T10) and the real ``search_records``
route function (T19). Nothing here replaces ``RecordsStore.search``; T14 wraps the path methods and
module functions the walk calls only to observe the thread each runs on.
"""

from __future__ import annotations

import itertools
import sys
import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi.responses import JSONResponse

from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore
from probos.knowledge.semantic import SemanticKnowledgeLayer
from probos.routers.records import search_records
from tests.test_bf940_frontmatter_framing import reframed
from tests.test_bf949_notebook_reader_identity import _self_monitoring

_QUESTION = (
    "I may have beaten you twice, can you check your memory to verify? "
    "I'm wondering if that memory was pruned."
)
_TARGET = "notebooks/Ezri/pruning.md"
_GAME = "recreation/games/tictactoe/game-1.md"
_EARLY = "2026-01-01T00:00:00+00:00"
_LATE = "2026-06-01T00:00:00+00:00"


async def _store(root: Path) -> RecordsStore:
    store = RecordsStore(RecordsConfig(repo_path=str(root / "ship-records"), auto_commit=False))
    await store.initialize()
    return store


def _write(store: RecordsStore, path: str, body: str, **frontmatter: Any) -> None:
    """A record written straight to disk, so the test sets every frontmatter value (``updated`` included)."""
    values = {"author": "captain", "classification": "ship", "status": "published", **frontmatter}
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\n{yaml.safe_dump(values, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")


async def _paths(store: RecordsStore, query: str, **reader: Any) -> list[str]:
    return [hit["path"] for hit in await store.search(query, scope="ship", **reader)]


async def _scores(store: RecordsStore, query: str, **reader: Any) -> dict[str, float]:
    return {hit["path"]: hit["score"] for hit in await store.search(query, scope="ship", **reader)}


@pytest.mark.asyncio
async def test_a_question_made_mostly_of_stopwords_finds_the_record_holding_its_rare_terms(tmp_path: Path) -> None:
    """#1751 acceptance 1: the Captain's question no longer matches every record, and the record holding its
    rare terms leads. On the base its ``i`` and ``if`` were substrings of every file here (both are inside the
    ``classification`` key), so every file matched it."""
    store = await _store(tmp_path)
    for index in range(6):
        _write(store, f"reports/filler-{index}.md", "I think that if you can, it is to be done. Was it a good watch?")
    for index in range(3):
        _write(store, f"notebooks/Alpha/memory-{index}.md", "Memory drills went well today.")
    _write(store, _TARGET, "Records show the Captain has beaten me twice; my memory of it was pruned.")
    paths = await _paths(store, _QUESTION, reader_id="captain")
    assert not any(path.startswith("reports/filler-") for path in paths)
    assert len(paths) == 4
    assert paths[0] == _TARGET


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "query", "found"), [
    pytest.param("ship status nominal", "i", False, id="i-is-not-found-inside-ship"),
    pytest.param("ship status nominal", "a to", False, id="a-and-to-are-not-substrings"),
    pytest.param("The starship docked.", "ship", False, id="ship-is-not-found-inside-starship"),
    pytest.param("Ready when I am.", "i", True, id="a-query-of-stopwords-only-still-matches-the-whole-word"),
])
async def test_words_match_whole_never_as_substrings(tmp_path: Path, body: str, query: str, found: bool) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", body)
    assert await _paths(store, query, reader_id="captain") == (["reports/entry.md"] if found else [])


@pytest.mark.asyncio
@pytest.mark.parametrize(("first_written", "last_written"), [
    pytest.param({"updated": _EARLY}, {"updated": _LATE}, id="iso-text"),
    pytest.param({"updated": _EARLY}, {"updated": date(2026, 6, 1)}, id="a-yaml-date"),
    pytest.param({"updated": _EARLY}, {"created": _LATE}, id="created-when-there-is-no-updated"),
    pytest.param({}, {"updated": _EARLY}, id="an-undated-record-goes-last"),
    pytest.param({"updated": "not-a-date"}, {"updated": _EARLY}, id="an-unparsable-date-goes-last"),
])
async def test_equal_scores_put_the_newer_record_first(
    tmp_path: Path, first_written: dict[str, Any], last_written: dict[str, Any],
) -> None:
    """#1751 acceptance 3: ``a-first.md`` sorts first by path, and ``z-last.md`` is the newer or the only dated
    record, so it must lead. On the base the path decided."""
    store = await _store(tmp_path)
    _write(store, "reports/a-first.md", "reactor coolant log", **first_written)
    _write(store, "reports/z-last.md", "reactor coolant log", **last_written)
    hits = await store.search("reactor", scope="ship", reader_id="captain")
    assert hits[0]["score"] == hits[1]["score"]  # premise: a tie on score
    assert [hit["path"] for hit in hits] == ["reports/z-last.md", "reports/a-first.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "found"), [
    pytest.param("status", False, id="a-yaml-key"),
    pytest.param("classification", False, id="another-yaml-key"),
    pytest.param("published", False, id="the-status-value"),
    pytest.param("ship", False, id="the-classification-value"),
    pytest.param("survey", True, id="the-title"),
    pytest.param("café", True, id="an-escaped-title-value"),
    pytest.param("reactor", True, id="the-topic"),
    pytest.param("manual", True, id="a-tag"),
    pytest.param("engineering", True, id="the-department"),
    pytest.param("captain", True, id="the-author"),
])
async def test_frontmatter_keys_are_not_scored_and_its_meaningful_values_are(
    tmp_path: Path, query: str, found: bool,
) -> None:
    """``yaml.safe_dump`` writes the title's ``é`` as an escape, so ``café`` is found only in the parsed value,
    never in the raw file: the substring check runs on parsed text (RK7)."""
    store = await _store(tmp_path)
    _write(
        store, "reports/review.md", "Coolant pressure holds.",
        title="Quarterly Warp Survey, Café", topic="reactor-review", tags=["manual"], department="engineering",
    )
    assert await _paths(store, query, reader_id="captain") == (["reports/review.md"] if found else [])


@pytest.mark.asyncio
async def test_a_term_in_a_tag_outranks_the_same_term_in_the_body(tmp_path: Path) -> None:
    """Equal coverage, equal length and equal dates: the tag hit weighs more. On the base the path put the
    body hit first."""
    store = await _store(tmp_path)
    _write(store, "reports/z-tagged.md", "core report", tags=["warp"], updated=_EARLY)
    _write(store, "reports/a-body.md", "warp core report", updated=_EARLY)
    hits = await store.search("warp", scope="ship", reader_id="captain")
    assert hits[0]["score"] == hits[1]["score"] == 1.0  # premise: both hold the only query term
    assert [hit["path"] for hit in hits] == ["reports/z-tagged.md", "reports/a-body.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "expected"), [
    pytest.param("bf-952", {"reports/filed.md"}, id="the-whole-identifier"),
    pytest.param("BF-952", {"reports/filed.md"}, id="in-capitals"),
    pytest.param("952", {"reports/filed.md", "reports/apart.md"}, id="one-part"),
])
async def test_an_identifier_matches_whole_and_by_its_parts(tmp_path: Path, query: str, expected: set[str]) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/filed.md", "Filed as BF-952 today.")
    _write(store, "reports/apart.md", "The bf team logged 952 hours.")
    assert set(await _paths(store, query, reader_id="captain")) == expected


@pytest.mark.asyncio
async def test_scores_are_between_zero_and_one_and_never_rise_down_the_list(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/all.md", "reactor coolant pressure nominal")
    _write(store, "reports/two.md", "reactor coolant flush")
    _write(store, "reports/one.md", "reactor inspection")
    _write(store, "reports/none.md", "warp field survey")
    hits = await store.search("reactor coolant pressure", scope="ship", reader_id="captain")
    scores = [hit["score"] for hit in hits]
    assert [hit["path"] for hit in hits] == ["reports/all.md", "reports/two.md", "reports/one.md"]
    assert scores[0] == 1.0 and all(0.0 < score <= 1.0 for score in scores)
    assert scores == sorted(scores, reverse=True) and scores[-1] < 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(("hidden_path", "hidden_frontmatter", "reader"), [
    pytest.param(
        "notebooks/Bravo/coolant.md", {"author": "Bravo", "classification": "private"}, "alice",
        id="another-crew-members-private-note",
    ),
    pytest.param("_archived/coolant.md", {}, "captain", id="an-archived-record"),
])
async def test_a_record_the_reader_cannot_read_does_not_move_the_scores_it_is_shown(
    tmp_path: Path, hidden_path: str, hidden_frontmatter: dict[str, Any], reader: str,
) -> None:
    """A4: term rarity is counted over what the reader may read. A withheld record that holds a query term
    leaves every score the reader is shown unchanged; the same text where the reader can read it moves it."""
    store = await _store(tmp_path)
    _write(store, "reports/reactor.md", "reactor log")
    _write(store, "reports/warp.md", "warp log")
    before = await _scores(store, "reactor coolant", reader_id=reader)
    assert 0.0 < before["reports/reactor.md"] < 1.0  # control: a partial match, so its score depends on rarity
    _write(store, hidden_path, "coolant coolant coolant", **hidden_frontmatter)
    assert await _scores(store, "reactor coolant", reader_id=reader) == before
    _write(store, "reports/coolant.md", "coolant")
    visible = await _scores(store, "reactor coolant", reader_id=reader)
    assert visible["reports/reactor.md"] != before["reports/reactor.md"]  # control: a readable record does


@pytest.mark.asyncio
async def test_the_oracle_puts_the_game_record_first_for_a_question_naming_the_game(tmp_path: Path) -> None:
    """#1751 acceptance 5 on a fixture, through the real Oracle. On the base the roster notes, which hold the
    question's ``can``, ``you``, ``check``, ``our`` and ``games``, outranked the game record."""
    store = await _store(tmp_path)
    for index in range(4):
        _write(store, f"notebooks/Able/roster-{index}.md", "Can you check the duty roster? Our games night is on hold.")
    _write(store, _GAME, "Tictactoe games: Captain against Ezri. Result: Captain wins.", topic="tictactoe")
    oracle = OracleService(records_store=store)
    results = await oracle.query(
        "can you check our tictactoe games", agent_id="captain", k_per_tier=3, tiers=["records"],
    )
    assert results[0].metadata["path"] == _GAME
    # BF-952 keeps ``score`` in 0..1, and the Oracle still divides the keyword score by ten (RK4).
    assert 0.0 < results[0].score <= 0.1


@pytest.mark.asyncio
async def test_the_notebook_pull_finds_a_note_whose_department_is_only_in_its_frontmatter(tmp_path: Path) -> None:
    """RK1: the self-monitoring pull searches by department name, and the ``department`` value is scored."""
    store = await _store(tmp_path)
    await store.write_notebook("Zephyr", "calibration", "my own calibration log", department="engineering")
    result = await _self_monitoring(store, "Zephyr")
    assert result["notebook_content"]["topic"] == "calibration"


@pytest.mark.asyncio
@pytest.mark.parametrize("frontmatter_text", [
    pytest.param("- a\n- b\n", id="a-yaml-list"),
    pytest.param("just text\n", id="a-yaml-scalar"),
])
async def test_a_record_whose_frontmatter_is_not_a_mapping_is_skipped_not_raised(
    tmp_path: Path, frontmatter_text: str,
) -> None:
    """RK5: on the base such a record raised ``AttributeError`` out of every search that matched it."""
    store = await _store(tmp_path)
    _write(store, "reports/good.md", "warp core report")
    (store.repo_path / "reports" / "bad.md").write_text(
        f"---\n{frontmatter_text}---\n\nwarp core report\n", encoding="utf-8",
    )
    assert await _paths(store, "warp", reader_id="captain") == ["reports/good.md"]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    pytest.param("", id="empty"),
    pytest.param("   ", id="blank"),
    pytest.param("?!", id="punctuation"),
])
async def test_a_query_with_no_words_finds_nothing(tmp_path: Path, query: str) -> None:
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "Ready?! Yes.")
    assert await store.search(query, scope="ship", reader_id="captain") == []


_LIBYAML = bool(getattr(yaml, "__with_libyaml__", False))
#: T23's lines: a tab after a key, which PyYAML's scanner refuses and libyaml scans, with values libyaml builds and
#: values it cannot (A4, round 4), and plain lines to pair them with.
_TAB_GRID_LINES = (
    "classification:\tprivate", "author:\tbob", "updated:\t2026-06-01", "updated:\t2026-13-05",
    "updated:\t2026-02-30", "count:\t!!int 7", "count:\t!!int word", "ratio:\t!!float warp",
    "author: alice", "classification: private", "updated: 2026-13-05", "broken: [unclosed",
)


@pytest.mark.parametrize(("raw", "frontmatter", "body"), [
    pytest.param(
        "---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n",
        {"author": "bones", "classification": "ship"}, "Warp report.", id="the-store-shape",
    ),
    pytest.param(
        "---\nauthor: bones\n---\nabove\n---\nbelow", {"author": "bones"}, "above\n---\nbelow",
        id="a-body-holding-a-rule",
    ),
    pytest.param("---\nupdated: 2026-06-01\n---\nbody", {"updated": date(2026, 6, 1)}, "body", id="a-yaml-date"),
    pytest.param('---\ntitle: "Caf\\xE9"\n---\nbody', {"title": "Café"}, "body", id="an-escaped-value"),
    pytest.param("---\n---\nbody", {}, "body", id="empty-frontmatter"),
    pytest.param("---\n[]\n---\nbody", {}, "body", id="a-falsy-frontmatter-reads-as-empty"),
    pytest.param("---\nkey: [unclosed\n---\nbody", {}, "body", id="malformed-yaml"),
    pytest.param(
        "---\nclassification:\tprivate\n---\nbody", {}, "body",
        id="a-tab-only-libyaml-accepts",
    ),
    pytest.param("no frontmatter at all", {}, "no frontmatter at all", id="no-frontmatter"),
    pytest.param(
        "---\nauthor: alice\nclassification: private --- the closing marker is inline\nbody",
        {"author": "alice", "classification": "private"}, "the closing marker is inline\nbody",
        id="closed-inside-a-line-as-the-base-framed-it",
    ),
    pytest.param(
        "---\nauthor: bones --- warp notes\n", {"author": "bones"}, "warp notes",
        id="closed-inside-a-line-naming-no-classification",
    ),
    pytest.param(
        "---\nauthor: alice\nclassification: private\nbody", {}, "---\nauthor: alice\nclassification: private\nbody",
        id="never-closed-has-no-frontmatter-L18",
    ),
])
def test_every_reader_frames_and_loads_a_document_alike(
    tmp_path: Path, raw: str, frontmatter: dict[str, Any], body: str,
) -> None:
    """A1 (finding 6), A3, A5, A6: every reader but the search reads with ``_parse_document``, the base's own text
    (A6), and the search frames alike. A frontmatter block no loader accepts reads as ``{}``, as on the base. A tab
    after a key is refused by PyYAML's scanner and accepted by libyaml, so with libyaml installed only the search
    reads it (RK8, A5). A value holding ``---`` is BF-940's (#1686), not this file's."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert store._parse_document(raw) == (frontmatter, body)
    searched = _rk8_read(raw) or (frontmatter, body)
    assert records_store_module._search_read_document(raw)[:2] == searched


@pytest.mark.asyncio
async def test_a_search_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RK7: the walk, the reads, the parse and the ranking all run in a worker thread, so a search never blocks
    the event loop. The test records the thread of each step: the walk (``_markdown_files``; ``rglob`` before
    BF-958), ``read_text`` on the store's own path class, and the module functions the search calls. On the base
    the whole walk ran on the loop's thread (and ``_search_read_document`` does not exist there, so the test fails
    at setup)."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    seen: dict[str, list[int]] = {"walk": [], "read_text": [], "parse": [], "count": [], "rank": [], "admit": []}
    path_type = type(store.repo_path)

    def _recording(step: str, function: Any) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            seen[step].append(threading.get_ident())
            return function(*args, **kwargs)
        return record

    monkeypatch.setattr(records_store_module, "_markdown_files", _recording("walk", records_store_module._markdown_files))
    monkeypatch.setattr(path_type, "read_text", _recording("read_text", path_type.read_text))
    monkeypatch.setattr(
        records_store_module, "_search_read_document", _recording("parse", records_store_module._search_read_document),
    )
    monkeypatch.setattr(
        records_store_module, "_base_reading_admits", _recording("admit", records_store_module._base_reading_admits),
    )
    monkeypatch.setattr(
        records_store_module, "_search_record_counts", _recording("count", records_store_module._search_record_counts),
    )
    monkeypatch.setattr(
        records_store_module, "record_write_time", _recording("rank", records_store_module.record_write_time),
    )
    assert await _paths(store, "warp", reader_id="captain") == ["reports/entry.md"]
    loop_thread = threading.get_ident()
    assert all(seen.values()), seen  # premise: every step ran
    assert not any(loop_thread in threads for threads in seen.values()), seen


@pytest.mark.asyncio
@pytest.mark.parametrize(("topic", "query", "found"), [
    pytest.param(314159, "314159", True, id="an-integer-topic"),
    pytest.param(2.5, "2.5", True, id="a-float-topic"),
    pytest.param(True, "true", False, id="a-boolean-topic-is-not-text"),
])
async def test_a_numeric_frontmatter_value_is_scored_and_a_boolean_is_not(
    tmp_path: Path, topic: Any, query: str, found: bool,
) -> None:
    """Finding 2: ``POST /api/records/notebooks/{callsign}`` hands its JSON ``topic`` to ``write_notebook`` as it
    came (``routers/records.py:146``, ``:151-160``), so a number is stored as a number. The base found it as a
    substring of the raw file, and the candidate before A1 dropped it; a list's numbers were already scored. A
    boolean is not text, alone or in a list."""
    store = await _store(tmp_path)
    path = await store.write_notebook("Ezri", topic, "coolant log")
    assert await _paths(store, query, reader_id="captain") == ([path] if found else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("updated", [
    pytest.param("2026-13-05", id="month-13"),
    pytest.param("2026-02-30", id="february-30"),
    pytest.param("2026-01-01 25:00:00", id="hour-25"),
])
async def test_a_record_whose_frontmatter_cannot_be_constructed_is_withheld_not_raised(
    tmp_path: Path, updated: str,
) -> None:
    """Finding 5: YAML reads each of these as a timestamp and its constructor raises ``ValueError``, which is not a
    ``YAMLError``. On the base a search that matched such a record raised; before A1 every search raised."""
    store = await _store(tmp_path)
    _write(store, "reports/good.md", "warp core report")
    (store.repo_path / "reports" / "bad.md").write_text(
        f"---\nauthor: captain\nclassification: ship\nupdated: {updated}\n---\n\nwarp core report\n", encoding="utf-8",
    )
    for reader in ("captain", "alice"):
        assert await _paths(store, "warp", reader_id=reader) == ["reports/good.md"]


@pytest.mark.asyncio
async def test_the_records_search_route_confines_a_search_to_a_directory(tmp_path: Path) -> None:
    """RK11 (finding 3): the HXI's notebook search filters the route's results to ``notebooks/`` after the cap of
    20, so twenty better matches elsewhere cut the note. ``directory=notebooks`` confines the walk instead, and a
    directory outside the repository is HTTP 400. On the base the route took no ``directory``."""
    store = await _store(tmp_path)
    for index in range(20):
        _write(store, f"reports/reactor-{index}.md", "reactor reactor coolant", tags=["reactor"])
    _write(store, "notebooks/Ezri/reactor-note.md", "reactor note")
    runtime = SimpleNamespace(_records_store=store)
    everywhere = await search_records(q="reactor", scope="ship", runtime=runtime)
    assert "notebooks/Ezri/reactor-note.md" not in [hit["path"] for hit in everywhere["results"]]  # premise: cut
    confined = await search_records(q="reactor", scope="ship", directory="notebooks", runtime=runtime)
    assert [hit["path"] for hit in confined["results"]] == ["notebooks/Ezri/reactor-note.md"]
    outside = await search_records(q="reactor", scope="ship", directory="../outside", runtime=runtime)
    assert isinstance(outside, JSONResponse) and outside.status_code == 400


_INLINE_CLOSE = "---\nauthor: alice\nclassification: private --- the closing marker is inline\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(("raw", "kept"), [
    pytest.param(_INLINE_CLOSE + "warp core notes\n", True, id="closed-inside-a-line"),
    # BF-940 (#1686): the four hand-made shapes with a closing line after the inline marker read to that line now. They moved
    # to tests/test_bf940_frontmatter_framing.py, which pins each at its new reading (L3 of BF-940's contract).
    pytest.param("---\nauthor: alice\nclassification: private\n---\nwarp core notes\n", True, id="closed-on-its-own-line"),
    pytest.param("---\nauthor: alice\nclassification: private\nwarp core notes\n", False, id="never-closed-L18"),
])
async def test_a_frontmatter_closed_inside_a_line_keeps_the_classification_the_base_read(
    tmp_path: Path, raw: str, kept: bool,
) -> None:
    """A2 (round 2, finding 1), through ``read_entry`` and ``search``. A hand-made or legacy file closed inside a line, with no
    closing line after it, read as ``private`` on the base and still does: BF-940's rule frames a text with no closing line
    as the base did. The four cases that had a closing line after the inline marker (rounds 2 and 3) moved to BF-940's file
    (#1686), where each is pinned at the reading the rule gives it. The next is the store's own shape. The last has no
    closing marker and reads as on the base, with no frontmatter (L18, kept by BF-940)."""
    store = await _store(tmp_path)
    path = "notebooks/alice/framing.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw, encoding="utf-8")
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and "warp" in own["content"].lower()
    assert await _paths(store, "warp", reader_id="alice") == [path]
    other = await store.read_entry(path, reader_id="bob")
    if kept:
        assert own["frontmatter"]["classification"] == "private"
        assert other is None
        assert await _paths(store, "warp", reader_id="bob") == []
    else:
        assert own["frontmatter"] == {} and other is not None
        assert await _paths(store, "warp", reader_id="bob") == [path]


@pytest.mark.asyncio
async def test_a_rewritten_note_is_indexed_at_the_classification_it_keeps(tmp_path: Path) -> None:
    """A2 (round 2, finding 2; AD-1157a): a notebook rewrite that names no classification keeps the note's own, and
    ``write_entry`` handed the semantic index the caller's default (``private``) instead, so a note that reads as
    ``ship`` on disk was missing from another reader's semantic results (on the base too). Real
    ``SemanticKnowledgeLayer`` and Chroma, as in ``test_ad1138_records_semantic_index.py``."""
    store = await _store(tmp_path)
    layer = SemanticKnowledgeLayer(db_path=tmp_path / "semantic", episodic_memory=None)
    await layer.start()
    try:
        store.set_semantic_indexer(layer)
        path = await store.write_notebook("Ezri", "coolant", "reactor coolant log", classification="ship")
        await store.write_notebook("Ezri", "coolant", "reactor coolant log, revised")
        on_disk = await store.read_entry(path, reader_id="alice")
        assert on_disk is not None and on_disk["frontmatter"]["classification"] == "ship"  # premise: AD-1157a kept it
        rows = await layer.search(
            "reactor coolant", types=["records"], limit=20, records_scope="ship", reader_id="alice",
        )
        indexed = [row.get("metadata") or {} for row in rows]
        assert [meta.get("classification") for meta in indexed if meta.get("path") == path] == ["ship"]
    finally:
        await layer.stop()


def _base_read(raw: str) -> tuple[Any, str]:
    """``RecordsStore._parse_document`` of the base (``a745e447``, ``records_store.py:1265-1275``), verbatim but for
    ``self``: T22's oracle. It is a reference, not a statement that the base frames correctly: BF-940 (#1686) owns
    the framing, replaces this oracle with its own rule and rewrites T22."""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                fm = {}
            return fm, parts[2].strip()
    return {}, raw


def _read_or_error(read: Any, raw: str) -> Any:
    """``read(raw)``, or the name of the exception it raised: a constructor error must be the same error."""
    try:
        return read(raw)
    except Exception as exc:  # noqa: BLE001 -- compared, never swallowed: the test asserts on it
        return type(exc).__name__


_GRID_LINES = (
    "author: alice", "author: alice --- legacy", "author: Ezri---Prime",
    "classification: private", "classification: private --- legacy", "classification: ship",
    "department: medical", "topic: Review --- nominal", "topic: 2026-13-05---nominal",
    "topic: 'Inspection --- status: nominal'", "broken: [unclosed", "updated: 2026-13-05",
)
_GRID_CLOSES = ("---\n", "----\n", "")
_GRID_BODIES = ("", "warp notes\n", "classification: ship\nauthor: bob\n", "---\nmore notes\n")


def test_every_document_reads_as_on_the_base(tmp_path: Path) -> None:
    """A3 (round 3, findings 1 to 3): BF-952 changes no reader's reading of a document. BF-940 (#1686) reframes 2,388 of the
    3,747 shapes (a ``---`` inside a line before the first closing line, or a closing line of more than three hyphens);
    those are its T9's. The other 1,359 are this test's: over the three rounds' lines, closing markers, bodies and both
    line endings, each reads under ``_parse_document`` exactly as the base read it, a constructor error included, and the
    search reads it so too (A5): no line holds a tab, so libyaml and PyYAML read each alike. The tab shapes, RK8's and
    round 4's, are T23's."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    shapes = [
        "---\n" + "".join(f"{line}\n" for line in lines) + close + body
        for count in (1, 2)
        for lines in itertools.product(_GRID_LINES, repeat=count)
        for close in _GRID_CLOSES
        for body in _GRID_BODIES
    ]
    shapes += [shape.replace("\n", "\r\n") for shape in shapes]
    shapes += ["no frontmatter", "-- two hyphens\n---\nbody", "\n---\nauthor: alice\n---\nbody"]
    assert len(shapes) == 3747  # premise: (12 + 144) line sequences x 3 closes x 4 bodies x 2 line endings, + 3
    shapes = [shape for shape in shapes if not reframed(shape)]  # BF-940: the shapes it reframes are its own
    assert len(shapes) == 1359  # premise: 3,747 less the 2,388 that BF-940's rule frames otherwise
    differ = []
    for shape in shapes:
        expected = _read_or_error(_base_read, shape)
        if (
            _read_or_error(store._parse_document, shape) != expected
            or _read_or_error(_search_read, shape) != expected
        ):
            differ.append(shape)
    assert differ == [], (len(differ), differ[:5])


def _search_read(raw: str) -> tuple[Any, str]:
    """The search's reading of ``raw``: ``_search_read_document``'s frontmatter and body (A5)."""
    return records_store_module._search_read_document(raw)[:2]


def _rk8_read(raw: str) -> Any:
    """RK8's one admitted difference, computed here from the two loaders: where libyaml loads the base framing's
    frontmatter and ``yaml.safe_load`` raises ``YAMLError``, the search reads libyaml's value (``{}`` for a falsy
    one; A5: no other reader does). ``None`` for any other document, which the search reads as on the base."""
    if not _LIBYAML or not raw.startswith("---"):
        return None
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        yaml.safe_load(parts[1])
    except yaml.YAMLError:
        pass
    except Exception:  # noqa: BLE001 -- PyYAML raised as the base raised: not RK8, the base's reading applies
        return None
    else:
        return None
    try:
        frontmatter = yaml.load(parts[1], Loader=yaml.CSafeLoader)
    except Exception:  # noqa: BLE001 -- libyaml cannot load it either: not RK8, the base's reading applies
        return None
    return (frontmatter or {}), parts[2].strip()


def test_a_frontmatter_libyaml_cannot_load_reads_as_on_the_base(tmp_path: Path) -> None:
    """A4 (round 4, finding 1): PyYAML's scanner refuses a tab after a key and libyaml scans it. Where libyaml then
    cannot build a value (``updated:<TAB>2026-13-05`` and ``count:<TAB>!!int word`` raise ``ValueError``), A1's
    ``_load_frontmatter`` let the error escape, so ``read_entry`` raised and ``list_entries`` dropped the record; on
    the base ``yaml.safe_load`` raised ``ScannerError`` and every reader read ``{}``. Now a block libyaml cannot load,
    for any reason, is read as the base read it. Over tab and plain lines, one or two to a frontmatter and both line
    endings, every shape reads under ``_parse_document`` (the base's own text, A6) as on the base, a constructor error
    included (A5: RK8's shapes too), and under the search as on the base or, where libyaml loads it and PyYAML's
    scanner refuses it, as libyaml read it (RK8). T22 holds no tab."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    shapes = [
        "---\n" + "".join(f"{line}\n" for line in lines) + "---\nwarp notes\n"
        for count in (1, 2)
        for lines in itertools.product(_TAB_GRID_LINES, repeat=count)
    ]
    shapes += [shape.replace("\n", "\r\n") for shape in shapes]
    assert len(shapes) == 312  # premise: (12 + 144) line sequences x 2 line endings
    differ: list[str] = []
    admitted = 0
    for shape in shapes:
        base = _read_or_error(_base_read, shape)
        rk8 = _rk8_read(shape)
        searched = base if rk8 is None else rk8
        admitted += rk8 is not None and rk8 != base
        if (
            _read_or_error(store._parse_document, shape) != base
            or _read_or_error(_search_read, shape) != searched
        ):
            differ.append(shape)
    assert differ == [], (len(differ), differ[:5])
    if _LIBYAML:  # premise: the grid holds round 4's class and RK8's
        for block in ("\nupdated:\t2026-13-05\n", "\ncount:\t!!int word\n"):
            with pytest.raises(ValueError):
                yaml.load(block, Loader=yaml.CSafeLoader)
            with pytest.raises(yaml.YAMLError):
                yaml.safe_load(block)
        assert admitted > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("line", [
    pytest.param("updated:\t2026-13-05", id="tab-plus-bad-date"),
    pytest.param("count:\t!!int word", id="tab-plus-bad-int-tag"),
])
async def test_a_record_libyaml_cannot_build_is_read_listed_and_found_as_on_the_base(
    tmp_path: Path, line: str,
) -> None:
    """A4 (round 4, finding 1), through the real readers. Before A4, libyaml's ``ValueError`` escaped: ``read_entry``
    raised (the route's HTTP 400), ``list_entries`` dropped the record and the search withheld it. On the base every
    reader read ``{}``, and does again. ``{}`` names no classification; what another reader may then read is the
    base's default and BF-940's (#1686), and this test asserts nothing about it, nor about ``publish``'s rewrite."""
    raw = f"---\nauthor: alice\nclassification: private\n{line}\n---\n\nwarp core notes\n"
    if _LIBYAML:  # premise: the shape is the class round 4 found
        with pytest.raises(ValueError):
            yaml.load(raw.split("---", 2)[1], Loader=yaml.CSafeLoader)
    assert _base_read(raw) == ({}, "warp core notes")  # premise: the base reads it as {}
    store = await _store(tmp_path)
    path = "notebooks/alice/tabbed.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw, encoding="utf-8")
    assert await store.read_entry(path, reader_id="captain") == {
        "frontmatter": {}, "content": "warp core notes", "path": path,
    }
    assert [(entry["path"], entry["frontmatter"]) for entry in await store.list_entries("notebooks")] == [(path, {})]
    assert await _paths(store, "warp", reader_id="captain") == [path]


def _nested(depth: int, style: str) -> str:
    """A5 (round 5, finding 1): a record whose frontmatter nests ``depth`` collections deep, its mapping included,
    in flow (``[[...]]``) or block (``- - ... deep``) style."""
    inner = depth - 1
    nest = "[" * inner + "]" * inner if style == "flow" else "\n" + "- " * inner + "deep"
    return f"---\nauthor: alice\nclassification: ship\nnest: {nest}\n---\n\nwarp core notes\n"


@pytest.mark.parametrize(("depth", "style"), [
    pytest.param(99, "flow", id="flow-just-below-the-search-limit"),
    pytest.param(100, "flow", id="flow-at-the-search-limit"),
    pytest.param(150, "flow", id="flow-below-the-base-limit"),
    pytest.param(600, "flow", id="flow-past-the-base-limit"),
    pytest.param(150, "block", id="block-below-the-base-limit"),
    pytest.param(600, "block", id="block-past-the-base-limit"),
])
def test_a_deeply_nested_frontmatter_reads_as_on_the_base(tmp_path: Path, depth: int, style: str) -> None:
    """A5 (round 5, finding 1): libyaml loads a frontmatter nesting about 330 collections deep or more, where the
    base's ``yaml.safe_load`` raised ``RecursionError``, which is not a ``YAMLError``; through A4 every reader read
    what the base raised on. Every reader but the search now reads with the base's call, and the search hands
    libyaml only a block nesting fewer than 100 deep. Each shape reads under ``_parse_document`` (the base's own
    text, A6) and the search as on the base, the ``RecursionError`` included."""
    raw = _nested(depth, style)
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    expected = _read_or_error(_base_read, raw)
    if depth >= 600:  # premise: the shape is the class round 5 found
        assert expected == "RecursionError"
        if _LIBYAML:
            assert type(yaml.load(raw.split("---", 2)[1], Loader=yaml.CSafeLoader)) is dict
    else:  # premise: PyYAML reads it
        assert type(expected[0]) is dict and expected[0]["classification"] == "ship"
    assert _read_or_error(store._parse_document, raw) == expected
    assert _read_or_error(_search_read, raw) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [
    pytest.param(150, id="below-the-base-limit"),
    pytest.param(600, id="past-the-base-limit"),
])
async def test_a_deeply_nested_record_is_read_listed_published_and_found_as_on_the_base(
    tmp_path: Path, depth: int,
) -> None:
    """A5 (round 5, finding 1), through the real readers. Through A4 libyaml read a 600-level frontmatter for every
    reader: ``read_entry`` returned it, ``list_entries`` listed it and update-in-place kept its ``created``. On the
    base ``read_entry`` and ``publish`` raised ``RecursionError`` and ``list_entries`` skipped the record, and they
    do again; the search withholds it. Below the base's limit every reader reads it, as on the base."""
    raw = _nested(depth, "flow")
    store = await _store(tmp_path)
    path = "notebooks/alice/nested.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(raw, encoding="utf-8")
    base = _read_or_error(_base_read, raw)
    if depth >= 600:
        assert base == "RecursionError"  # premise
        with pytest.raises(RecursionError):
            await store.read_entry(path, reader_id="captain")
        with pytest.raises(RecursionError):
            await store.publish(path, author="captain")
        assert await store.list_entries("notebooks") == []
        assert await _paths(store, "warp", reader_id="captain") == []
    else:
        frontmatter, body = base
        assert await store.read_entry(path, reader_id="bob") == {
            "frontmatter": frontmatter, "content": body, "path": path,
        }
        listed = [(entry["path"], entry["frontmatter"]) for entry in await store.list_entries("notebooks")]
        assert listed == [(path, frontmatter)]
        assert await _paths(store, "warp", reader_id="bob") == [path]


@pytest.mark.asyncio
@pytest.mark.parametrize(("frontmatter_line", "readers"), [
    pytest.param(
        "classification: private", {"alice": True, "bob": False, "captain": True}, id="the-base-reading-withholds",
    ),
    pytest.param(
        "updated: 2026-13-05", {"alice": False, "bob": False, "captain": False}, id="the-base-reading-raises",
    ),
])
async def test_the_search_returns_no_record_the_base_reading_withholds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frontmatter_line: str, readers: dict[str, bool],
) -> None:
    """A5 (round 5): the search returns a record only where the base's reading of it, ``read_entry``'s and the
    semantic index's, admits the reader too. The search's own load is replaced here by one that reads every
    frontmatter as a ``ship`` record, standing for any difference between libyaml's reading and the base's. The
    record is still shown only to readers the base's reading admits, and a record ranked after it still fills
    the list."""
    store = await _store(tmp_path)
    hidden = "notebooks/alice/hidden.md"
    target = store.repo_path / hidden
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\nauthor: alice\n{frontmatter_line}\n---\n\nwarp warp core notes\n", encoding="utf-8")
    _write(store, "reports/open.md", "warp report")
    monkeypatch.setattr(
        records_store_module, "_search_load_frontmatter", lambda block: {"author": "alice", "classification": "ship"},
    )
    for reader, shown in readers.items():
        expected = sorted(([hidden] if shown else []) + ["reports/open.md"])
        assert sorted(await _paths(store, "warp", reader_id=reader)) == expected, reader


@pytest.mark.asyncio
async def test_a_record_only_libyaml_reads_is_found_only_where_both_readings_admit_it(tmp_path: Path) -> None:
    """A5 (RK8, L28): PyYAML's scanner refuses a tab after a key and libyaml reads it, so ``read_entry`` reads
    alice's private note as ``{}`` while the search reads it as private. BF-940 slice 4 (L19): a document whose
    frontmatter PyYAML refuses is private to the owner of its notebook directory, so ``read_entry`` withholds it
    from bob and shows it to alice and the Captain, and the search, with or without libyaml, finds it for the
    same two and not for bob: the two readers agree on this note, whose author is the owner of its directory (where
    libyaml's reading names another author the search can miss it for its owner: BF-940 slice 4, L11). (It was the
    base's reading, ``ship`` for every reader, which
    this test pinned and BF-940 owned.)"""
    store = await _store(tmp_path)
    path = "notebooks/alice/tabbed-private.md"
    target = store.repo_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\nauthor:\talice\nclassification:\tprivate\n---\n\nwarp core notes\n", encoding="utf-8")
    assert await store.read_entry(path, reader_id="bob") is None
    own = await store.read_entry(path, reader_id="alice")
    assert own is not None and own["frontmatter"] == {}  # PyYAML's reading, which read_entry keeps
    assert await _paths(store, "warp", reader_id="alice") == [path]
    assert await _paths(store, "warp", reader_id="captain") == [path]
    assert await _paths(store, "warp", reader_id="bob") == []


def test_libyaml_is_given_only_a_block_nesting_fewer_than_the_limit_deep() -> None:
    """A5: ``_nests_below`` counts open collections in the parser's event stream, so siblings add no depth, and a
    block that does not parse is not below the limit (the base's call reads it)."""
    limit = records_store_module._SEARCH_LIBYAML_DEPTH_LIMIT
    assert limit == 100
    nests_below = records_store_module._nests_below
    assert nests_below("nest: " + "[" * 98 + "]" * 98, limit)  # 99 deep, the mapping included
    assert not nests_below("nest: " + "[" * 99 + "]" * 99, limit)  # 100 deep
    assert nests_below("tags: [" + ", ".join(["[warp]"] * 150) + "]", limit)  # 3 deep, 152 collections
    assert not nests_below("broken: [unclosed", limit)


def _frontier(read: Any) -> int:
    """A6 (round 6, finding 1): the deepest flow nesting ``read`` reads when called from here, by bisection.

    PyYAML's composer recurses about two Python frames a nesting level, so where a reader raises ``RecursionError``
    depends on the frames between its caller and ``yaml.safe_load``. Every reader compared is called from this frame.
    """
    low, high = 2, sys.getrecursionlimit()
    assert _read_or_error(read, _nested(low, "flow")) != "RecursionError"  # premise: the low end reads
    assert _read_or_error(read, _nested(high, "flow")) == "RecursionError"  # premise: the high end raises
    while high - low > 1:
        middle = (low + high) // 2
        if _read_or_error(read, _nested(middle, "flow")) == "RecursionError":
            high = middle
        else:
            low = middle
    return low


def test_parse_document_raises_at_the_base_recursion_frontier(tmp_path: Path) -> None:
    """A6 (round 6, finding 1): A5 sent ``_parse_document`` through two more frames before ``yaml.safe_load``, so a
    document nesting one level below the base's limit raised ``RecursionError`` where the base read it, and
    update-in-place reset its ``created``, ``revision`` and classification. ``_parse_document`` is the base's own
    text again: called from the same frame as the base's (``_base_read``), it reads to the same depth."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert _frontier(store._parse_document) == _frontier(_base_read)


@pytest.mark.asyncio
async def test_read_entry_reads_with_parse_document_as_on_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A6 (round 6, finding 1): ``read_entry`` reads a document with ``self._parse_document(raw)``, the base's own
    call, so its reading and the depth at which it raises ``RecursionError`` are the base's from every caller. A5
    called a module function two frames deeper instead."""
    store = await _store(tmp_path)
    path = "notebooks/alice/warp.md"
    _write(store, path, "warp core notes", author="alice")
    parsed: list[str] = []
    parse = store._parse_document

    def _recording(raw: str) -> tuple[dict, str]:
        parsed.append(raw)
        return parse(raw)

    monkeypatch.setattr(store, "_parse_document", _recording)
    entry = await store.read_entry(path, reader_id="captain")
    assert entry is not None and entry["content"] == "warp core notes"
    assert parsed == [(store.repo_path / path).read_text(encoding="utf-8")]
