"""BF-952 (#1751): Ship's Records keyword search matches whole words and ranks rare ones first.

On the base ``RecordsStore.search`` scored a record by the fraction of query words found as substrings
of the raw file, YAML keys included, and broke ties by path: ``i`` matched "ship", ``status`` matched
every record, and a conversational question matched every record at one score, so the paths that sort
first won. It also ran its whole walk on the event loop. Real fixtures throughout: a real
``RecordsStore`` on ``tmp_path`` with records written to disk as a person or the store writes them,
the real ``OracleService`` (T9) and the real self-monitoring pull (T10). Nothing here replaces
``RecordsStore.search``; T14 wraps its parse function only to observe the thread it runs on.
"""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from probos.cognitive.oracle_service import OracleService
from probos.config import RecordsConfig
from probos.knowledge import records_store as records_store_module
from probos.knowledge.records_store import RecordsStore
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
    rare terms leads. On the base its ``i``, ``to`` and ``if`` were substrings of every file."""
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


@pytest.mark.parametrize("raw", [
    pytest.param("---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n", id="the-store-shape"),
    pytest.param("---\nupdated: 2026-06-01\n---\nbody", id="a-yaml-date"),
    pytest.param('---\ntitle: "Caf\\xE9"\n---\nbody', id="an-escaped-value"),
    pytest.param("---\n- a\n- b\n---\nbody", id="a-yaml-list"),
    pytest.param("---\n---\nbody", id="empty-frontmatter"),
    pytest.param("---\nkey: [unclosed\n---\nbody", id="malformed-yaml"),
    pytest.param("no frontmatter at all", id="no-frontmatter"),
])
def test_search_reads_a_document_as_the_store_reads_it(tmp_path: Path, raw: str) -> None:
    """RK8: the search parse (libyaml when installed) returns exactly what ``_parse_document`` returns."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert records_store_module._search_document(raw) == store._parse_document(raw)


@pytest.mark.asyncio
async def test_a_search_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RK7: the walk, parse and ranking run in a worker thread, so a search never blocks the event loop.
    On the base the whole walk ran on the loop's thread."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    threads: list[int] = []
    parse = records_store_module._search_document

    def _recording_parse(raw: str) -> tuple[Any, str]:
        threads.append(threading.get_ident())
        return parse(raw)

    monkeypatch.setattr(records_store_module, "_search_document", _recording_parse)
    assert await _paths(store, "warp", reader_id="captain") == ["reports/entry.md"]
    assert threads and threading.get_ident() not in threads
