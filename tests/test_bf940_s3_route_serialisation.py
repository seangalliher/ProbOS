"""BF-940 slice 3 (#1686, F7-1): a record the reader parsed is a record the Ship's Records routes can answer.

FastAPI writes what a handler returns as JSON after the handler has returned, outside the handler's own error boundary. A record the
reader parsed but the JSON writer cannot write (a mapping nested deeper than the writer's recursion guard allows, bytes that are not UTF-8, a lone
surrogate, a value that holds itself) was therefore an unhandled HTTP 500 on the read route, on its PROV-O projection and on every route that returns a
frontmatter value. Real ``RecordsStore``
over ``tmp_path`` with ``~`` moved, hand-made records, the real router through ``TestClient(raise_server_exceptions=False)`` (so the
500 is a response a test can assert on, not an exception out of ``get``), no network.

The writer's depth stop is pydantic-core's recursion guard, a compiled constant that differs by platform (the read route's body first fails at nesting 97
on Windows and 253 on Linux), so no test pins a depth: the module asks its own ``TypeAdapter(Any)`` at import where the read route's body and a listing's
stop, and derives every depth below from the answer. The reader's own stop (``RecursionError`` at about 490 levels on Windows and on Linux, Python 3.12) is
that of pure-Python PyYAML and does not depend on the writer. A lone surrogate reaches a record as an ASCII escape, ``\\ud800``, in the JSON a notebook
route is sent or in the YAML of a hand-made record: a literal one cannot be written to a file as UTF-8.

The class is strict xfail until M2 (each case fails at an ``assert`` of its own body on the unfixed tree, after its premise); the
module's functions are guards and pass on both trees. A case asserts its premise first: the healthy records alone are answered, and
the reader itself parsed the record (``read_entry`` returns it), so a failure cannot mean the record was never read. The inventory
test reads the router object, not its source.
"""

from __future__ import annotations

import datetime
import json
import logging
import math
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.knowledge.provo import project_record_frontmatter
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import router

_HEALTHY = "---\nauthor: alice\nclassification: ship\ntopic: healthy\ntags: [coolant]\n---\n\ncoolant healthy body\n"
_NOTE = "notebooks/alice/ok.md"
_LOG = "captains-log/ok.md"
_BAD_NOTE = "notebooks/alice/case.md"
_BAD_LOG = "captains-log/case.md"
_MARKER = "VALUE-MARKER-917"
_LONE = "\ud800"  # a lone surrogate: a JSON escape gives one to ``json.loads``, a YAML escape to the reader; never write one to a file
_JSON = {"content-type": "application/json"}
_READ = f"/api/records/documents/{_BAD_NOTE}"
_LISTINGS = [
    pytest.param("/api/records/documents", id="documents"),
    pytest.param("/api/records/notebooks/alice", id="notebook"),
    pytest.param("/api/records/captains-log", id="captains-log"),
    pytest.param("/api/records/browse", id="browse"),
    pytest.param("/api/records/search?q=coolant", id="search"),
]

_WRITER = TypeAdapter(Any)  # the call FastAPI makes for a handler annotated ``-> Any``


def _writes(body: Any) -> bool:
    try:
        _WRITER.dump_json(body)
    except (ValueError, RecursionError):  # PydanticSerializationError is a ValueError
        return False
    return True


def _mapping(depth: int) -> Any:
    """What ``_nested(depth)`` parses to: ``depth`` single-key mappings around a leaf."""
    value: Any = 1
    for _ in range(depth):
        value = {"a": value}
    return value


def _read_body(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """The body of the read route: the record itself."""
    return {"path": _BAD_NOTE, "frontmatter": frontmatter}


def _listing_body(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """The body of a listing: the record two levels below the body's top (``{key: [record]}``)."""
    return {"documents": [_read_body(frontmatter)]}


def _first_refused(body_of: Callable[[dict[str, Any]], dict[str, Any]]) -> int:
    """The least nesting at which the writer refuses the body ``body_of`` builds around it, asked of the writer that runs."""
    for depth in range(1, 300):
        if not _writes(body_of({"meta": _mapping(depth)})):
            return depth
    raise AssertionError("premise: the writer wrote every body up to 299 levels deep, so there is no depth stop to derive the depths of this file from")


# The writer's depth stop is pydantic-core's recursion guard, a compiled constant that differs by platform (255, or 99 on Windows): it is asked of the
# writer here and written nowhere as a number. A listing's body holds a record two levels below its top, so it stops two levels sooner.
_READ_LIMIT = _first_refused(_read_body)
_LISTING_LIMIT = _first_refused(_listing_body)
_JUST_BELOW = _LISTING_LIMIT - 5  # written by the read route and by every listing, on any platform
_JUST_OVER = _LISTING_LIMIT + 5  # refused by the read route and by every listing, on any platform
_FAR_OVER = _READ_LIMIT + 50  # refused likewise, and far inside the reader's reach: the reader raised RecursionError at about 490 levels
assert _READ_LIMIT == _LISTING_LIMIT + 2 and _LISTING_LIMIT > 5, "premise: the writer stops a listing's body two levels before the read route's"
assert (
    _writes(_listing_body({"meta": _mapping(_JUST_BELOW)}))
    and not _writes(_read_body({"meta": _mapping(_JUST_OVER)}))
    and not _writes(_read_body({"meta": _mapping(_FAR_OVER)}))
), "premise: each depth the cases use is on the side of the writer's limit that its case needs"

# (the YAML value of one key, a text that must never reach a log line). ``nested-over-limit`` is five levels over a listing's limit, so over the read
# route's too; ``nested-far-over-limit`` is fifty levels over the read route's, a record the reader still parses with room to spare. Each case asserts
# that the reader parsed its record, so a reader that stops sooner fails at a premise line, not at a status. ``lone-surrogate`` is the ASCII YAML
# escape, never a literal one.
_UNWRITABLE = [
    pytest.param("{a: " * _JUST_OVER + _MARKER + "}" * _JUST_OVER, _MARKER, id="nested-over-limit"),
    pytest.param("{a: " * _FAR_OVER + _MARKER + "}" * _FAR_OVER, _MARKER, id="nested-far-over-limit"),
    pytest.param("!!binary //4=", "xff", id="bytes-not-utf-8"),
    pytest.param("&a [*a]", "[...]", id="holds-itself"),
    pytest.param('"\\ud800"', "ud800", id="lone-surrogate"),
]
_SHAPES = (
    "---\nauthor: alice\nclassification: ship\nwhen: 2026-11-09T01:02:03Z\nday: 2026-11-09\nkinds: !!set {p: null}\nraw: !!binary aGk=\n"
    "1: \u00e9\nnot_a_number: .nan\ntags: [coolant]\n---\n\ncoolant shapes body\n"
)
_SHAPES_JSON = {
    "author": "alice", "classification": "ship", "when": "2026-11-09T01:02:03Z", "day": "2026-11-09", "kinds": ["p"], "raw": "hi",
    "1": "\u00e9", "not_a_number": None, "tags": ["coolant"],
}
_ROUTES = {
    ("GET", "/api/records/stats"): "holds no record value",
    ("GET", "/api/records/documents"): "holds a record value",
    ("GET", "/api/records/documents/{path:path}"): "holds a record value",
    ("POST", "/api/records/captains-log"): "holds no record value",
    ("GET", "/api/records/captains-log"): "holds a record value",
    ("GET", "/api/records/notebooks/{callsign}"): "holds a record value",
    ("POST", "/api/records/notebooks/{callsign}"): "holds no record value",
    ("GET", "/api/records/search"): "holds a record value",
    ("GET", "/api/records/history/{path:path}"): "holds no record value",
    ("GET", "/api/records/browse"): "holds a record value",
    ("GET", "/api/records/backlinks/{path:path}"): "holds a record value",
    ("GET", "/api/records/graph"): "holds a record value",
    ("GET", "/api/records/timeline"): "holds a record value",
}
_DRIVEN = {
    ("GET", "/api/records/documents"), ("GET", "/api/records/documents/{path:path}"), ("GET", "/api/records/captains-log"),
    ("GET", "/api/records/notebooks/{callsign}"), ("GET", "/api/records/search"), ("GET", "/api/records/browse"),
    ("GET", "/api/records/graph"), ("GET", "/api/records/backlinks/{path:path}"), ("GET", "/api/records/timeline"),
}


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"


def _nested(depth: int) -> str:
    return "{a: " * depth + "1" + "}" * depth


def _record(key: str, value: str) -> str:
    return f"---\nauthor: alice\nclassification: ship\n{key}: {value}\ntags: [coolant]\n---\n\ncoolant case body\n"


def _make_store(root: Path, files: dict[str, str]) -> RecordsStore:
    repo = root / "ship-records"
    repo.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    return RecordsStore(RecordsConfig(repo_path=str(repo), auto_commit=False))


def _get(store: RecordsStore, url: str) -> Any:
    return _send(store, "GET", url)


def _send(store: RecordsStore, method: str, url: str, **kwargs: Any) -> Any:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        config=SystemConfig(), records_store=store, _records_store=store, knowledge_browser=KnowledgeBrowserService(store),
    )
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.request(method, url, **kwargs)


def _items(response: Any) -> list[dict[str, Any]]:
    body = response.json()
    return next(body[key] for key in ("documents", "entries", "results") if key in body)


def _shape(url: str, body: dict[str, Any]) -> Any:
    """What must not change when a record is left out of a listing: all of the body, but for the search's scores, which count the whole corpus."""
    if url.startswith("/api/records/search"):
        return {"paths": [hit["path"] for hit in body["results"]], "count": body["count"]}
    return body


async def test_a_record_holding_every_shape_the_reader_builds_is_answered_as_it_always_was(tmp_path):
    """Guard (passes on every tree): a UTC datetime, a date, a set, UTF-8 bytes, a unicode value under an int key and ``nan`` are written as they were."""
    path = "notebooks/alice/shapes.md"
    store = _make_store(tmp_path, {path: _SHAPES})
    frontmatter = (await store.read_entry(path, reader_id="captain"))["frontmatter"]
    assert type(frontmatter["when"]) is datetime.datetime and frontmatter["when"].tzinfo is not None
    assert type(frontmatter["day"]) is datetime.date and frontmatter["kinds"] == {"p"} and frontmatter["raw"] == b"hi"
    assert frontmatter[1] == "\u00e9" and math.isnan(frontmatter["not_a_number"]), "premise: the reader builds each shape"
    read = _get(store, f"/api/records/documents/{path}")
    assert read.status_code == 200 and read.json()["frontmatter"] == _SHAPES_JSON
    listing = _get(store, "/api/records/documents")
    assert listing.status_code == 200 and listing.json()["documents"][0]["frontmatter"] == _SHAPES_JSON


@pytest.mark.parametrize("url", [pytest.param(_READ, id="read"), *_LISTINGS])
async def test_a_record_just_below_the_writers_limit_is_answered_by_every_route(tmp_path, url):
    """Guard: five levels below the depth at which the writer stops a listing's body, the record is answered on the read route and in every listing."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _LOG: _HEALTHY, _BAD_NOTE: _record("meta", _nested(_JUST_BELOW)), _BAD_LOG: _record("meta", _nested(_JUST_BELOW))})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    response = _get(store, url)
    assert response.status_code == 200 and "case.md" in response.text


async def test_a_record_beyond_the_readers_own_limit_keeps_its_answers(tmp_path):
    """Guard: the reader raises ``RecursionError`` for 600 levels, the read route answers its 503 and a listing leaves the record out, as before."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("meta", _nested(600))})
    with pytest.raises(RecursionError):
        await store.read_entry(_BAD_NOTE, reader_id="captain")
    read = _get(store, _READ)
    assert read.status_code == 503 and read.json()["availability"]["code"] == "records.read_failed"
    listing = _get(store, "/api/records/documents")
    assert listing.status_code == 200 and [item["path"] for item in _items(listing)] == [_NOTE]


@pytest.mark.parametrize(("value", "marker"), _UNWRITABLE)
async def test_the_provenance_projection_of_a_record_the_writer_cannot_write_is_still_answered(tmp_path, value, marker):
    """Guard: ``?format=prov-jsonld`` copies no ``meta`` value, so it is answered where the record itself is not (the one value it copies, ``created``, is the class below)."""
    store = _make_store(tmp_path, {_BAD_NOTE: _record("meta", value)})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    response = _get(store, f"{_READ}?format=prov-jsonld")
    assert response.status_code == 200 and set(response.json()) == {"@context", "@graph"}


@pytest.mark.parametrize("url", ["/api/records/backlinks/notebooks/alice/case.md", "/api/records/timeline"])
async def test_the_backlinks_and_the_timeline_answer_a_record_whose_unwritable_value_they_do_not_carry(tmp_path, url):
    """Guard: the backlinks carry a record's tags and topic slug and the timeline its department and day, so a topic that is not text reaches neither body."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", _nested(_FAR_OVER))})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    assert _get(store, url).status_code == 200


def test_every_route_of_the_module_is_classified():
    """Guard: a route added to ``routers/records.py`` fails here until it is classified, and a route that holds a record value must be driven by the class below."""
    found = {(method, route.path) for route in router.routes for method in route.methods}
    assert found == set(_ROUTES), "a route was added, moved or renamed: classify it in _ROUTES (does its body hold a record value?)"
    assert {key for key, kind in _ROUTES.items() if kind == "holds a record value"} == _DRIVEN, "a route that holds a record value is not driven by the class below"


class TestARecordTheReaderParsedIsAnsweredByEveryRoute:
    @pytest.mark.parametrize(("value", "marker"), _UNWRITABLE)
    async def test_the_read_route_answers_a_record_the_writer_cannot_write_with_the_controlled_503(self, tmp_path, caplog, value, marker):
        store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("meta", value)})
        assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
        assert _get(store, f"/api/records/documents/{_NOTE}").status_code == 200, "premise: a healthy record is answered"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, _READ)
        assert response.status_code == 503
        assert response.json() == {
            "error": "Record document unavailable",
            "availability": {"state": "unavailable", "code": "records.read_failed", "message": "Record document unavailable", "retryable": True},
        }
        assert "returning HTTP 503" in caplog.text and marker not in caplog.text and marker not in response.text

    @pytest.mark.parametrize("url", _LISTINGS)
    @pytest.mark.parametrize(("value", "marker"), _UNWRITABLE)
    async def test_a_listing_leaves_out_a_record_the_writer_cannot_write_and_keeps_the_rest(self, tmp_path, caplog, url, value, marker):
        healthy = {_NOTE: _HEALTHY, _LOG: _HEALTHY}
        reference = _get(_make_store(tmp_path / "healthy", healthy), url)
        assert reference.status_code == 200 and _items(reference), "premise: the healthy records alone are listed"
        store = _make_store(tmp_path / "both", {**healthy, _BAD_NOTE: _record("meta", value), _BAD_LOG: _record("meta", value)})
        assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, url)
        assert response.status_code == 200
        assert _shape(url, response.json()) == _shape(url, reference.json())
        assert "left out of the listing" in caplog.text and "case.md" in caplog.text and marker not in caplog.text

    async def test_a_record_the_read_route_can_write_is_left_out_of_a_listing_two_levels_deeper(self, tmp_path):
        """A listing nests a record two levels below the body's top, so the writer stops two levels sooner there than on the read route: a window around the listing's limit, derived at import, is scanned through the real store."""
        store = _make_store(tmp_path, {_NOTE: _HEALTHY})
        found = None
        for depth in range(_LISTING_LIMIT - 3, _LISTING_LIMIT + 3):
            (store.repo_path / _BAD_NOTE).write_text(_record("meta", _nested(depth)), encoding="utf-8")
            entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
            if not _writes(_listing_body(entry["frontmatter"])):
                found = depth
                break
        assert found == _LISTING_LIMIT and _writes(entry), "premise: the first depth at which a listing's body is refused is the derived limit, and the read route's body still writes there"
        assert _get(store, _READ).status_code == 200, "premise: the read route answers the record"
        response = _get(store, "/api/records/documents")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == [_NOTE]

    async def test_the_captains_log_limit_counts_the_records_it_returns(self, tmp_path):
        def entry(created: str, extra: str = "") -> str:
            return f"---\nauthor: captain\nclassification: ship\ncreated: '{created}'\n{extra}---\n\nentry body\n"

        store = _make_store(tmp_path, {
            "captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01"),
            "captains-log/c.md": entry("2026-03-01", f"meta: {_nested(_FAR_OVER)}\n"),
        })
        healthy = _make_store(tmp_path / "healthy", {"captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01")})
        assert [item["path"] for item in _items(_get(healthy, "/api/records/captains-log?limit=1"))] == ["captains-log/b.md"], "premise: b is the newest healthy entry"
        assert await store.read_entry("captains-log/c.md", reader_id="captain") is not None, "premise: the reader parsed the newest entry"
        response = _get(store, "/api/records/captains-log?limit=1")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == ["captains-log/b.md"]

    @pytest.mark.parametrize(("value", "marker"), [_UNWRITABLE[1], _UNWRITABLE[2], _UNWRITABLE[4]])
    async def test_the_graph_answers_a_record_whose_topic_the_writer_cannot_write_with_its_own_envelope(self, tmp_path, caplog, value, marker):
        assert _get(_make_store(tmp_path / "healthy", {_NOTE: _HEALTHY}), "/api/records/graph").status_code == 200, "premise: the healthy graph is answered"
        store = _make_store(tmp_path / "both", {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", value)})
        entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
        assert entry is not None and "topic" in entry["frontmatter"], "premise: the reader parsed the record"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, "/api/records/graph")
        assert response.headers["content-type"].startswith("application/json")
        assert response.status_code == 500
        assert response.json() == {
            "error": "graph assembly failed",
            "availability": {"state": "failed", "code": "knowledge_browser.graph_failed", "message": "graph assembly failed", "retryable": True},
        }
        assert "returning HTTP 500" in caplog.text and marker not in caplog.text

    @pytest.mark.parametrize(
        ("field", "url", "message", "code"),
        [
            pytest.param("tags", f"/api/records/backlinks/{_BAD_NOTE}", "backlink lookup failed", "knowledge_browser.backlinks_failed", id="tags-backlinks"),
            pytest.param("department", "/api/records/timeline", "timeline assembly failed", "knowledge_browser.timeline_failed", id="department-timeline"),
        ],
    )
    async def test_a_note_the_notebook_route_accepts_is_answered_by_the_backlinks_and_the_timeline_with_their_own_envelope(self, tmp_path, caplog, field, url, message, code):
        store = _make_store(tmp_path, {})
        write = "/api/records/notebooks/alice"
        healthy = {"topic": "ok", "content": "coolant healthy body", "tags": ["coolant"], "department": "science"}
        assert _send(store, "POST", write, content=json.dumps(healthy), headers=_JSON).status_code == 200, "premise: the notebook route writes a healthy note"
        control = f"/api/records/backlinks/{_NOTE}" if field == "tags" else url
        assert _get(store, control).status_code == 200, "premise: the healthy note alone is answered"
        poisoned = {"topic": "case", "content": "coolant case body", field: [_LONE] if field == "tags" else _LONE}
        posted = _send(store, "POST", write, content=json.dumps(poisoned), headers=_JSON)
        assert posted.status_code == 200 and posted.json() == {"path": _BAD_NOTE, "status": "written"}, "premise: the notebook route accepts the note"
        entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
        assert entry is not None and entry["frontmatter"][field] in (_LONE, [_LONE]), "premise: the reader gives the lone surrogate back"
        service = KnowledgeBrowserService(store)
        body = await (service.get_backlinks(_BAD_NOTE) if field == "tags" else service.get_timeline())
        assert not _writes(body), "premise: the body this route builds is one the writer refuses"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, url)
        assert response.headers["content-type"].startswith("application/json")
        assert response.status_code == 500
        assert response.json() == {"error": message, "availability": {"state": "failed", "code": code, "message": message, "retryable": True}}
        assert "returning HTTP 500" in caplog.text and "ud800" not in caplog.text

    async def test_the_provenance_projection_of_a_created_the_writer_cannot_write_is_answered_with_the_controlled_503(self, tmp_path, caplog):
        created = '"2026-11-09\\ud80001:02:03"'  # datetime.fromisoformat takes any one character between the date and the time, a lone surrogate included
        store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("created", created)})
        entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
        assert entry is not None and entry["frontmatter"]["created"] == "2026-11-09\ud80001:02:03", "premise: the reader parsed the record"
        assert not _writes(project_record_frontmatter(_BAD_NOTE, entry["frontmatter"])), "premise: the projection of this record is one the writer refuses"
        assert _get(store, f"/api/records/documents/{_NOTE}?format=prov-jsonld").status_code == 200, "premise: a healthy record's projection is answered"
        with caplog.at_level(logging.WARNING, logger="probos.routers.records"):
            response = _get(store, f"{_READ}?format=prov-jsonld")
        assert response.status_code == 503
        assert response.json() == {
            "error": "Record document unavailable",
            "availability": {"state": "unavailable", "code": "records.read_failed", "message": "Record document unavailable", "retryable": True},
        }
        assert "returning HTTP 503" in caplog.text and "ud800" not in caplog.text
