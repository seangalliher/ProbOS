"""BF-940 slice 3 (#1686, F7-1): a record the reader parsed is a record the Ship's Records routes can answer.

FastAPI writes what a handler returns as JSON after the handler has returned, outside the handler's own error boundary. A record the
reader parsed but the JSON writer cannot write (a mapping nested about 100 levels deep, bytes that are not UTF-8, a value that holds
itself) was therefore an unhandled HTTP 500 on the read route and on every route that returns a frontmatter. Real ``RecordsStore``
over ``tmp_path`` with ``~`` moved, hand-made records, the real router through ``TestClient(raise_server_exceptions=False)`` (so the
500 is a response a test can assert on, not an exception out of ``get``), no network.

The class is strict xfail until M2 (each case fails at an ``assert`` of its own body on the unfixed tree, after its premise); the
module's functions are guards and pass on both trees. A case asserts its premise first: the healthy records alone are answered, and
the reader itself parsed the record (``read_entry`` returns it), so a failure cannot mean the record was never read. The inventory
test reads the router object, not its source.
"""

from __future__ import annotations

import datetime
import logging
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from probos.config import RecordsConfig, SystemConfig
from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.knowledge.records_store import RecordsStore
from probos.routers.records import router

_HEALTHY = "---\nauthor: alice\nclassification: ship\ntopic: healthy\ntags: [coolant]\n---\n\ncoolant healthy body\n"
_NOTE = "notebooks/alice/ok.md"
_LOG = "captains-log/ok.md"
_BAD_NOTE = "notebooks/alice/case.md"
_BAD_LOG = "captains-log/case.md"
_MARKER = "VALUE-MARKER-917"
_READ = f"/api/records/documents/{_BAD_NOTE}"
_LISTINGS = [
    pytest.param("/api/records/documents", id="documents"),
    pytest.param("/api/records/notebooks/alice", id="notebook"),
    pytest.param("/api/records/captains-log", id="captains-log"),
    pytest.param("/api/records/browse", id="browse"),
    pytest.param("/api/records/search?q=coolant", id="search"),
]
# (the YAML value of one key, a text that must never reach a log line)
_UNWRITABLE = [
    pytest.param("{a: " * 100 + _MARKER + "}" * 100, _MARKER, id="nested-100"),
    pytest.param("{a: " * 450 + _MARKER + "}" * 450, _MARKER, id="nested-450"),
    pytest.param("!!binary //4=", "xff", id="bytes-not-utf-8"),
    pytest.param("&a [*a]", "[...]", id="holds-itself"),
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
    ("GET", "/api/records/backlinks/{path:path}"): "holds no record value",
    ("GET", "/api/records/graph"): "holds a record value",
    ("GET", "/api/records/timeline"): "holds no record value",
}
_DRIVEN = {
    ("GET", "/api/records/documents"), ("GET", "/api/records/documents/{path:path}"), ("GET", "/api/records/captains-log"),
    ("GET", "/api/records/notebooks/{callsign}"), ("GET", "/api/records/search"), ("GET", "/api/records/browse"),
    ("GET", "/api/records/graph"),
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
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        config=SystemConfig(), records_store=store, _records_store=store, knowledge_browser=KnowledgeBrowserService(store),
    )
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.get(url)


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
async def test_a_record_nested_ninety_levels_is_answered_by_every_route(tmp_path, url):
    """Guard: ninety levels is below the depth at which the writer stops, on the read route and in a listing."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _LOG: _HEALTHY, _BAD_NOTE: _record("meta", _nested(90)), _BAD_LOG: _record("meta", _nested(90))})
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
    """Guard: ``?format=prov-jsonld`` holds no value of the record, so it is answered where the record itself is not."""
    store = _make_store(tmp_path, {_BAD_NOTE: _record("meta", value)})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    response = _get(store, f"{_READ}?format=prov-jsonld")
    assert response.status_code == 200 and set(response.json()) == {"@context", "@graph"}


@pytest.mark.parametrize("url", ["/api/records/backlinks/notebooks/alice/case.md", "/api/records/timeline"])
async def test_a_route_that_holds_no_record_value_answers_while_such_a_record_exists(tmp_path, url):
    """Guard: the backlinks and the timeline hold only text and counts, so a record the writer cannot write does not reach their bodies."""
    store = _make_store(tmp_path, {_NOTE: _HEALTHY, _BAD_NOTE: _record("topic", _nested(450))})
    assert await store.read_entry(_BAD_NOTE, reader_id="captain") is not None, "premise: the reader parsed the record"
    assert _get(store, url).status_code == 200


def test_every_route_of_the_module_is_classified():
    """Guard: a route added to ``routers/records.py`` fails here until it is classified, and a route that holds a record value must be driven by the class below."""
    found = {(method, route.path) for route in router.routes for method in route.methods}
    assert found == set(_ROUTES), "a route was added, moved or renamed: classify it in _ROUTES (does its body hold a record value?)"
    assert {key for key, kind in _ROUTES.items() if kind == "holds a record value"} == _DRIVEN, "a route that holds a record value is not driven by the class below"


@pytest.mark.xfail(reason="BF-940 slice 3 M2: not built", raises=AssertionError, strict=True)
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
        """A listing nests a record two levels below the body's top, so the writer stops two levels sooner there than on the read route."""
        adapter = TypeAdapter(Any)

        def writes(body: Any) -> bool:
            try:
                adapter.dump_json(body)
            except ValueError:  # PydanticSerializationError is a ValueError
                return False
            return True

        store = _make_store(tmp_path, {_NOTE: _HEALTHY})
        found = None
        for depth in range(60, 140):
            (store.repo_path / _BAD_NOTE).write_text(_record("meta", _nested(depth)), encoding="utf-8")
            entry = await store.read_entry(_BAD_NOTE, reader_id="captain")
            if not writes({"documents": [{"path": _BAD_NOTE, "frontmatter": entry["frontmatter"]}]}):
                found = depth
                break
        assert found is not None and writes(entry), "premise: a depth at which the read route's body still writes and a listing's does not"
        assert _get(store, _READ).status_code == 200, "premise: the read route answers the record"
        response = _get(store, "/api/records/documents")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == [_NOTE]

    async def test_the_captains_log_limit_counts_the_records_it_returns(self, tmp_path):
        def entry(created: str, extra: str = "") -> str:
            return f"---\nauthor: captain\nclassification: ship\ncreated: '{created}'\n{extra}---\n\nentry body\n"

        store = _make_store(tmp_path, {
            "captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01"),
            "captains-log/c.md": entry("2026-03-01", f"meta: {_nested(450)}\n"),
        })
        healthy = _make_store(tmp_path / "healthy", {"captains-log/a.md": entry("2026-01-01"), "captains-log/b.md": entry("2026-02-01")})
        assert [item["path"] for item in _items(_get(healthy, "/api/records/captains-log?limit=1"))] == ["captains-log/b.md"], "premise: b is the newest healthy entry"
        assert await store.read_entry("captains-log/c.md", reader_id="captain") is not None, "premise: the reader parsed the newest entry"
        response = _get(store, "/api/records/captains-log?limit=1")
        assert response.status_code == 200
        assert [item["path"] for item in _items(response)] == ["captains-log/b.md"]

    @pytest.mark.parametrize(("value", "marker"), [_UNWRITABLE[1], _UNWRITABLE[2]])
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
