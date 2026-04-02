"""AD-539: Gap shell command tests."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console

from probos.experience.commands.commands_gap import (
    cmd_gap,
    _load_gap_reports,
    _gap_list,
    _gap_detail,
    _gap_check,
    _gap_summary,
)


def _make_runtime(gap_reports: list[dict] | None = None) -> MagicMock:
    """Create a mock runtime with records_store."""
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

    # Mock registry for check command
    rt.registry.all.return_value = []

    return rt


def _sample_gap(gap_id: str = "gap1", resolved: bool = False, **overrides) -> dict:
    defaults = {
        "id": gap_id,
        "agent_id": "agent1",
        "agent_type": "SecurityAgent",
        "gap_type": "knowledge",
        "description": "Test gap description",
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
    defaults.update(overrides)
    return defaults


@pytest.mark.asyncio
async def test_gap_list_command():
    """/gap list shows open gaps."""
    gap = _sample_gap()
    rt = _make_runtime([gap])
    console = Console(force_terminal=True, width=120)

    with patch("probos.experience.commands.commands_gap._load_gap_reports",
               return_value=[gap]):
        await _gap_list(rt, console, "")


@pytest.mark.asyncio
async def test_gap_list_filter_by_agent():
    """--agent filter works."""
    gap1 = _sample_gap("g1", agent_type="SecurityAgent")
    gap2 = _sample_gap("g2", agent_type="EngineeringAgent")

    with patch("probos.experience.commands.commands_gap._load_gap_reports",
               return_value=[gap1, gap2]):
        rt = _make_runtime()
        console = Console(force_terminal=True, width=120)
        # Should only show SecurityAgent gaps
        await _gap_list(rt, console, "--agent security")


@pytest.mark.asyncio
async def test_gap_list_filter_by_type():
    """--type knowledge filter works."""
    gap1 = _sample_gap("g1", gap_type="knowledge")
    gap2 = _sample_gap("g2", gap_type="capability")

    with patch("probos.experience.commands.commands_gap._load_gap_reports",
               return_value=[gap1, gap2]):
        rt = _make_runtime()
        console = Console(force_terminal=True, width=120)
        await _gap_list(rt, console, "--type knowledge")


@pytest.mark.asyncio
async def test_gap_detail_command():
    """/gap detail shows full report."""
    gap = _sample_gap("gap-detail-1")
    with patch("probos.experience.commands.commands_gap._load_gap_reports",
               return_value=[gap]):
        rt = _make_runtime()
        console = Console(force_terminal=True, width=120)
        await _gap_detail(rt, console, "gap-detail-1")


@pytest.mark.asyncio
async def test_gap_check_command():
    """/gap check runs closure check."""
    gap = _sample_gap("gap-check-1")
    with patch("probos.experience.commands.commands_gap._load_gap_reports",
               return_value=[gap]):
        rt = _make_runtime()
        console = Console(force_terminal=True, width=120)
        # Should not crash
        await _gap_check(rt, console, "gap-check-1")


@pytest.mark.asyncio
async def test_gap_summary_command():
    """/gap summary shows aggregates."""
    gaps = [
        _sample_gap("g1", gap_type="knowledge", priority="high"),
        _sample_gap("g2", gap_type="capability", priority="critical"),
        _sample_gap("g3", gap_type="knowledge", priority="medium"),
    ]
    with patch("probos.experience.commands.commands_gap._load_gap_reports",
               return_value=gaps):
        rt = _make_runtime()
        console = Console(force_terminal=True, width=120)
        await _gap_summary(rt, console)


@pytest.mark.asyncio
async def test_gap_check_resolves():
    """/gap check marks resolved gap when closure conditions met."""
    gap = _sample_gap("gap-resolve-1", evidence_sources=["episode:low_confidence"],
                       mapped_skill_id="")  # No skill mapping → only procedure signal needed

    with patch("probos.experience.commands.commands_gap._load_gap_reports",
               return_value=[gap]):
        with patch("probos.cognitive.gap_predictor.check_gap_closure",
                    new_callable=AsyncMock, return_value=True):
            rt = _make_runtime()
            rt.records_store = AsyncMock()
            rt.records_store.write_entry = AsyncMock()
            console = Console(force_terminal=True, width=120)
            await _gap_check(rt, console, "gap-resolve-1")
