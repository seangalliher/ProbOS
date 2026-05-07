"""AD-562: Tests for GET /api/records/timeline."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.routers.records import get_records_timeline


class _FakeStore:
    def __init__(self, entries):
        self._entries = entries

    async def list_entries(self, **_):
        return [{"path": e["path"], "frontmatter": e.get("frontmatter", {})} for e in self._entries]

    async def read_entry(self, path, *, reader_id="captain", **_):
        for e in self._entries:
            if e["path"] == path:
                return {"frontmatter": e.get("frontmatter", {}), "content": ""}
        return None


def _runtime(service) -> MagicMock:
    rt = MagicMock(spec=[])
    rt.knowledge_browser = service
    return rt


@pytest.mark.asyncio
async def test_timeline_day_buckets_with_dept_stacking() -> None:
    entries = [
        {"path": "n1.md", "frontmatter": {"created": "2026-05-01T10:00:00Z", "department": "science"}},
        {"path": "n2.md", "frontmatter": {"created": "2026-05-01T11:00:00Z", "department": "medical"}},
        {"path": "n3.md", "frontmatter": {"created": "2026-05-02T09:00:00Z", "department": "science"}},
    ]
    svc = KnowledgeBrowserService(_FakeStore(entries))
    res = await get_records_timeline(runtime=_runtime(svc))
    assert res["bucket"] == "day"
    assert res["total"] == 3
    days = {b["date"]: b for b in res["buckets"]}
    assert days["2026-05-01"]["count"] == 2
    assert days["2026-05-01"]["by_department"] == {"science": 1, "medical": 1}
    assert days["2026-05-02"]["count"] == 1


@pytest.mark.asyncio
async def test_timeline_unsupported_bucket_returns_400() -> None:
    svc = KnowledgeBrowserService(_FakeStore([]))
    res = await get_records_timeline(bucket="week", runtime=_runtime(svc))
    assert getattr(res, "status_code", 200) == 400
