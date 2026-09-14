"""AD-562: Tests for GET /api/records/browse."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.routers.records import browse_records


class _FakeStore:
    def __init__(self, entries=None, raise_exc: Exception | None = None) -> None:
        self._entries = entries or []
        self._raise = raise_exc

    async def list_entries(self, *, directory="", author="", classification="", **_):
        if self._raise:
            raise self._raise
        return list(self._entries)


def _runtime(store) -> MagicMock:
    rt = MagicMock()
    rt.records_store = store
    return rt


@pytest.mark.asyncio
async def test_browse_happy_path_no_filters() -> None:
    store = _FakeStore(entries=[
        {"path": "notebooks/chapel/n1.md", "frontmatter": {"author": "chapel"}},
        {"path": "captains-log/c1.md", "frontmatter": {"author": "captain"}},
    ])
    res = await browse_records(runtime=_runtime(store))
    assert isinstance(res, dict)
    assert res["count"] == 2
    assert len(res["documents"]) == 2


@pytest.mark.asyncio
async def test_browse_filters_by_department_and_tags() -> None:
    store = _FakeStore(entries=[
        {"path": "n1.md", "frontmatter": {"department": "science", "tags": ["trust", "routing"]}},
        {"path": "n2.md", "frontmatter": {"department": "engineering", "tags": ["trust"]}},
        {"path": "n3.md", "frontmatter": {"department": "science", "tags": ["unrelated"]}},
    ])
    res = await browse_records(department="science", tags="trust", runtime=_runtime(store))
    paths = [d["path"] for d in res["documents"]]
    assert paths == ["n1.md"]
    assert res["filters_applied"]["department"] == "science"
    assert res["filters_applied"]["tags"] == ["trust"]


@pytest.mark.asyncio
async def test_browse_returns_503_when_store_missing() -> None:
    rt = MagicMock()
    rt.records_store = None
    res = await browse_records(runtime=rt)
    assert getattr(res, "status_code", 200) == 503


@pytest.mark.asyncio
async def test_browse_store_exception_returns_503_not_successful_empty() -> None:
    store = _FakeStore(raise_exc=RuntimeError("boom"))
    res = await browse_records(runtime=_runtime(store))
    assert res.status_code == 503
    assert b'"state":"unavailable"' in res.body
    assert b'"documents"' not in res.body
