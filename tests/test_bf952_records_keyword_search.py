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


@pytest.mark.parametrize(("raw", "frontmatter", "body"), [
    pytest.param(
        "---\nauthor: bones\nclassification: ship\n---\n\nWarp report.\n",
        {"author": "bones", "classification": "ship"}, "Warp report.", id="the-store-shape",
    ),
    pytest.param(
        "---\ntopic: Inspection --- nominal\nclassification: private\n---\nbody",
        {"topic": "Inspection --- nominal", "classification": "private"}, "body", id="a-value-holding-three-hyphens",
    ),
    pytest.param(
        "---\ntopic: 'Inspection --- status: nominal'\nclassification: private\n---\nbody",
        {"topic": "Inspection --- status: nominal", "classification": "private"}, "body",
        id="a-quoted-value-holding-a-key",
    ),
    pytest.param(
        "---\nauthor: bones\n---\nabove\n---\nbelow", {"author": "bones"}, "above\n---\nbelow",
        id="a-body-holding-a-rule",
    ),
    pytest.param("---\nupdated: 2026-06-01\n---\nbody", {"updated": date(2026, 6, 1)}, "body", id="a-yaml-date"),
    pytest.param('---\ntitle: "Caf\\xE9"\n---\nbody', {"title": "Café"}, "body", id="an-escaped-value"),
    pytest.param("---\n---\nbody", {}, "body", id="empty-frontmatter"),
    pytest.param("---\n[]\n---\nbody", {}, "body", id="a-falsy-frontmatter-reads-as-empty"),
    pytest.param("---\nkey: [unclosed\n---\nbody", None, "body", id="malformed-yaml"),
    pytest.param(
        "---\nclassification:\tprivate\n---\nbody", {"classification": "private"} if _LIBYAML else None, "body",
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
    tmp_path: Path, raw: str, frontmatter: dict[str, Any] | None, body: str,
) -> None:
    """A1 (BF-940, #1686; finding 6): ``_read_document`` is the one parse. ``_parse_document`` reads ``None`` (a
    frontmatter block no loader accepts) as ``{}``, as on the base. The base cut the second and third cases at the
    ``---`` inside the topic, and the third then did not parse. A tab after a key is refused by PyYAML's scanner
    and accepted by libyaml, so with libyaml installed every reader now reads it."""
    store = RecordsStore(RecordsConfig(repo_path=str(tmp_path / "ship-records"), auto_commit=False))
    assert records_store_module._read_document(raw) == (frontmatter, body)
    assert store._parse_document(raw) == ({} if frontmatter is None else frontmatter, body)


@pytest.mark.asyncio
async def test_a_search_runs_off_the_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RK7: the walk, the reads, the parse and the ranking all run in a worker thread, so a search never blocks
    the event loop. The test records the thread of each step: ``rglob`` and ``read_text`` on the store's own path
    class, and the module functions the walk calls. On the base the whole walk ran on the loop's thread (and
    ``_read_document`` does not exist there, so the test fails at setup)."""
    store = await _store(tmp_path)
    _write(store, "reports/entry.md", "warp core report")
    seen: dict[str, list[int]] = {"rglob": [], "read_text": [], "parse": [], "count": [], "rank": []}
    path_type = type(store.repo_path)

    def _recording(step: str, function: Any) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            seen[step].append(threading.get_ident())
            return function(*args, **kwargs)
        return record

    monkeypatch.setattr(path_type, "rglob", _recording("rglob", path_type.rglob))
    monkeypatch.setattr(path_type, "read_text", _recording("read_text", path_type.read_text))
    monkeypatch.setattr(records_store_module, "_read_document", _recording("parse", records_store_module._read_document))
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
@pytest.mark.parametrize(("author", "values"), [
    pytest.param("Ezri---Prime", {}, id="an-author-holding-three-hyphens"),
    pytest.param("Ezri", {"topic": "Inspection --- status: nominal"}, id="a-quoted-topic-holding-a-key"),
    pytest.param("Ezri", {"topic": "first line\n---\nlast line"}, id="a-multi-line-topic-holding-a-rule"),
    pytest.param("Ezri", {"tags": ["warp --- core"]}, id="a-tag-holding-three-hyphens"),
])
async def test_a_frontmatter_value_holding_three_hyphens_is_read_whole_and_stays_private(
    tmp_path: Path, author: str, values: dict[str, Any],
) -> None:
    """Finding 1 and BF-940 (#1686), through ``write_entry``, ``read_entry``, ``search`` and update-in-place. The
    base ended the frontmatter at the first ``---`` anywhere. The author's case kept only ``author``, and neither
    topic case parsed, so each read as ``ship`` and another reader was shown the private record; the tag's case
    kept its classification, and its body began with the rest of the tag. The multi-line case checks that
    ``yaml.dump`` starts no line of a value with ``---``."""
    store = await _store(tmp_path)
    path = "notebooks/Ezri/inspection.md"
    write: dict[str, Any] = {
        "author": author, "path": path, "content": "PRIVATE_BODY_PROOF the coolant", "message": "probe",
        "classification": "private", **values,
    }
    await store.write_entry(**write)
    own = await store.read_entry(path, reader_id=author)
    assert own is not None and own["frontmatter"]["classification"] == "private"
    assert {key: own["frontmatter"][key] for key in values} == values
    assert own["content"] == "PRIVATE_BODY_PROOF the coolant"
    assert await store.read_entry(path, reader_id="alice") is None
    assert await _paths(store, "coolant", reader_id="alice") == []
    assert await _paths(store, "coolant", reader_id=author) == [path]
    await store.write_entry(**write)  # update-in-place carries ``created`` forward and counts the revision
    again = await store.read_entry(path, reader_id=author)
    assert again is not None and again["frontmatter"]["revision"] == 2
    assert again["frontmatter"]["created"] == own["frontmatter"]["created"]


@pytest.mark.asyncio
async def test_a_record_whose_frontmatter_does_not_parse_is_shown_to_the_captain_alone(tmp_path: Path) -> None:
    """RK10 (finding 1's injected reach): such a record names no classification. The base read it as ``{}``, so as
    ``ship``, and every reader was shown it. Now ``read_entry`` and ``search`` show it to the Captain alone; its
    author is unknown, so the author is not shown it either."""
    store = await _store(tmp_path)
    _write(store, "reports/open.md", "warp core report")
    (store.repo_path / "notebooks" / "Bravo").mkdir(parents=True, exist_ok=True)
    (store.repo_path / "notebooks" / "Bravo" / "secret.md").write_text(
        "---\nauthor: Bravo\nclassification: private\ntitle: [unclosed\n---\n\nwarp core secret\n", encoding="utf-8",
    )
    assert await store.read_entry("notebooks/Bravo/secret.md", reader_id="alice") is None
    assert await store.read_entry("notebooks/Bravo/secret.md", reader_id="Bravo") is None
    captain = await store.read_entry("notebooks/Bravo/secret.md", reader_id="captain")
    assert captain is not None and captain["frontmatter"] == {} and captain["content"] == "warp core secret"
    assert await _paths(store, "warp", reader_id="alice") == ["reports/open.md"]
    assert set(await _paths(store, "warp", reader_id="captain")) == {"reports/open.md", "notebooks/Bravo/secret.md"}


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
    pytest.param(
        _INLINE_CLOSE + "status: nominal\n---\nwarp core notes\n", True, id="closed-inside-a-line-then-a-key-and-a-rule",
    ),
    pytest.param(
        _INLINE_CLOSE + "Warp core notes, in prose.\n---\nmore warp notes\n", True,
        id="closed-inside-a-line-then-prose-and-a-rule",
    ),
    pytest.param(
        _INLINE_CLOSE + "classification: ship\n---\nwarp core notes\n", True,
        id="closed-inside-a-line-then-a-repeated-key-and-a-rule",
    ),
    pytest.param("---\nauthor: alice\nclassification: private\n---\nwarp core notes\n", True, id="closed-on-its-own-line"),
    pytest.param("---\nauthor: alice\nclassification: private\nwarp core notes\n", False, id="never-closed-L18"),
])
async def test_a_frontmatter_closed_inside_a_line_keeps_the_classification_the_base_read(
    tmp_path: Path, raw: str, kept: bool,
) -> None:
    """A2 (round 2, finding 1), through ``read_entry`` and ``search``. A1 ended a frontmatter only at a line
    beginning ``---``, so a hand-made or legacy file closed inside a line read as ``{}`` (the first case) or took
    its body as YAML: the second case then read an unknown classification, the third did not parse (its author
    lost it) and the fourth read the repeated ``ship``. Each read as ``private`` on the base, and does again. The
    fifth is the store's own shape. The last has no closing marker and reads as on the base, with no frontmatter
    (L18); BF-956 owns any change to it and updates this case."""
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
