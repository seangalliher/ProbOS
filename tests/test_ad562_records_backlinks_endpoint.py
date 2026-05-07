"""AD-562: Tests for GET /api/records/backlinks/{path}."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.routers.records import get_backlinks


class _FakeService:
    def __init__(self, payload, *, raise_exc: Exception | None = None) -> None:
        self._payload = payload
        self._raise = raise_exc
        self.calls: list[tuple[str, bool]] = []

    async def get_backlinks(self, path: str, *, include_suggested: bool = True):
        self.calls.append((path, include_suggested))
        if self._raise:
            raise self._raise
        return self._payload


def _runtime(service) -> MagicMock:
    rt = MagicMock(spec=[])
    rt.knowledge_browser = service
    return rt


@pytest.mark.asyncio
async def test_backlinks_happy_path() -> None:
    payload = {"path": "x.md", "references": [{"kind": "callsign", "target": "chapel", "raw_match": "@chapel"}], "referenced_by": ["y.md"], "suggested": [{"path": "z.md", "similarity": 0.5}]}
    svc = _FakeService(payload)
    res = await get_backlinks("x.md", runtime=_runtime(svc))
    assert res == payload
    assert svc.calls == [("x.md", True)]


@pytest.mark.asyncio
async def test_backlinks_returns_404_when_not_in_index() -> None:
    svc = _FakeService(None)
    res = await get_backlinks("missing.md", runtime=_runtime(svc))
    assert getattr(res, "status_code", 200) == 404


@pytest.mark.asyncio
async def test_backlinks_returns_503_when_service_none() -> None:
    rt = MagicMock(spec=[])
    res = await get_backlinks("x.md", runtime=rt)
    assert getattr(res, "status_code", 200) == 503


@pytest.mark.asyncio
async def test_backlinks_include_suggested_false_propagates() -> None:
    svc = _FakeService({"path": "x.md", "references": [], "referenced_by": [], "suggested": []})
    await get_backlinks("x.md", include_suggested=False, runtime=_runtime(svc))
    assert svc.calls == [("x.md", False)]
