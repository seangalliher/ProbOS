"""AD-539: Gap API routing tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.routers.gaps import (
    list_gaps,
    get_gap,
    check_gap,
    gaps_summary,
)


def _mock_runtime(gap_reports: list[dict] | None = None) -> MagicMock:
    """Create a mock runtime with records_store returning gap data."""
    rt = MagicMock()
    records = AsyncMock()

    if gap_reports is None:
        gap_reports = []

    entries = []
    for gap in gap_reports:
        entries.append({
            "path": f"reports/gap-reports/{gap.get('id', 'test')}.md",
            "frontmatter": {"tags": ["ad-539"]},
        })

    records.list_entries = AsyncMock(return_value=entries)

    async def _read_entry(path, reader_id="system"):
        import yaml
        for gap in gap_reports:
            if gap.get("id", "") in path:
                return {
                    "frontmatter": {"tags": ["ad-539"]},
                    "content": yaml.dump(gap, default_flow_style=False),
                }
        return None

    records.read_entry = AsyncMock(side_effect=_read_entry)
    rt.records_store = records
    rt.registry.all.return_value = []
    return rt


def _sample_gap(gap_id: str = "g1", resolved: bool = False, **kw) -> dict:
    defaults = {
        "id": gap_id,
        "agent_id": "agent1",
        "agent_type": "SecurityAgent",
        "gap_type": "knowledge",
        "description": "Test gap",
        "evidence_sources": ["failure_cluster:c1"],
        "affected_intent_types": ["code_review"],
        "failure_rate": 0.5,
        "episode_count": 10,
        "mapped_skill_id": "duty_execution",
        "current_proficiency": 1,
        "target_proficiency": 3,
        "priority": "medium",
        "resolved": resolved,
    }
    defaults.update(kw)
    return defaults


@pytest.mark.asyncio
async def test_api_gaps_list_endpoint():
    """GET /api/gaps returns gaps."""
    gap = _sample_gap()
    rt = _mock_runtime([gap])
    with patch("probos.routers.gaps._load_gap_reports",
               return_value=[gap]):
        result = await list_gaps(runtime=rt)
        assert result["count"] == 1
        assert len(result["gaps"]) == 1


@pytest.mark.asyncio
async def test_api_gaps_filter():
    """Query params filter correctly."""
    g1 = _sample_gap("g1", gap_type="knowledge", priority="high")
    g2 = _sample_gap("g2", gap_type="capability", priority="critical")
    with patch("probos.routers.gaps._load_gap_reports",
               return_value=[g1, g2]):
        result = await list_gaps(type="knowledge", runtime=MagicMock())
        assert result["count"] == 1
        assert result["gaps"][0]["gap_type"] == "knowledge"


@pytest.mark.asyncio
async def test_api_gap_detail_endpoint():
    """GET /api/gaps/{id} returns single gap."""
    gap = _sample_gap("detail-gap-1")
    with patch("probos.routers.gaps._load_gap_reports",
               return_value=[gap]):
        result = await get_gap("detail-gap-1", runtime=MagicMock())
        assert result["gap"] is not None
        assert result["gap"]["id"] == "detail-gap-1"


@pytest.mark.asyncio
async def test_api_gap_check_endpoint():
    """POST /api/gaps/{id}/check runs closure."""
    gap = _sample_gap("check-gap-1", evidence_sources=["episode:low_confidence"],
                       mapped_skill_id="")
    with patch("probos.routers.gaps._load_gap_reports",
               return_value=[gap]):
        with patch("probos.cognitive.gap_predictor.check_gap_closure",
                    new_callable=AsyncMock, return_value=False):
            rt = _mock_runtime()
            result = await check_gap("check-gap-1", runtime=rt)
            assert result["resolved"] is False


@pytest.mark.asyncio
async def test_api_gaps_summary_endpoint():
    """GET /api/gaps/summary returns aggregates."""
    gaps = [
        _sample_gap("g1", gap_type="knowledge", priority="high"),
        _sample_gap("g2", gap_type="capability", priority="critical", resolved=True),
    ]
    with patch("probos.routers.gaps._load_gap_reports",
               return_value=gaps):
        result = await gaps_summary(runtime=MagicMock())
        assert result["total"] == 2
        assert result["open"] == 1
        assert result["resolved"] == 1
        assert "by_type" in result


@pytest.mark.asyncio
async def test_api_gaps_empty():
    """No gaps returns empty list."""
    with patch("probos.routers.gaps._load_gap_reports",
               return_value=[]):
        result = await list_gaps(runtime=MagicMock())
        assert result["count"] == 0
        assert result["gaps"] == []


@pytest.mark.asyncio
async def test_api_gap_not_found():
    """Bad ID returns error."""
    with patch("probos.routers.gaps._load_gap_reports",
               return_value=[]):
        result = await get_gap("nonexistent-id", runtime=MagicMock())
        assert result["gap"] is None
        assert "error" in result
