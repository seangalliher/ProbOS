"""AD-594a v1: Consultation workspace tests."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import yaml

from probos.consultation import (
    ConsultationWorkspaceSummary,
    InputProcessor,
    WorkspaceLifecycleState,
    WorkspaceRegistry,
    parse_workspace_refs,
    render_workspace_refs_md,
)
from probos.knowledge.records_store import RecordsStore


def _make_records_store(tmp_path: Path) -> RecordsStore:
    cfg = SimpleNamespace(repo_path=str(tmp_path / "records"), auto_commit=False)
    return RecordsStore(cfg)


@pytest_asyncio.fixture
async def records(tmp_path: Path) -> RecordsStore:
    rs = _make_records_store(tmp_path)
    await rs.initialize()
    return rs


@pytest.fixture
def clock():
    state = {"t": 1700000000.0}

    def _tick() -> float:
        state["t"] += 1.0
        return state["t"]

    return _tick


@pytest_asyncio.fixture
async def registry(records: RecordsStore, clock) -> WorkspaceRegistry:
    return WorkspaceRegistry(records, clock=clock)


# 1
def test_workspace_lifecycle_state_enum() -> None:
    assert WorkspaceLifecycleState.INITIATED == 0
    assert WorkspaceLifecycleState.CONSULTING == 1
    assert WorkspaceLifecycleState.PLAN_REVIEW == 2
    assert WorkspaceLifecycleState.APPROVED == 3
    assert WorkspaceLifecycleState.EXECUTING == 4
    assert WorkspaceLifecycleState.COMPLETED == 5
    assert WorkspaceLifecycleState.ARCHIVED == 6
    assert len(list(WorkspaceLifecycleState)) == 7


# 2
def test_parse_workspace_refs_extracts_patterns() -> None:
    text = "see [workspace:abc/plan/plan_v1.md] and [workspace:def/inputs/x.txt] and [workspace:abc/journal.md]"
    refs = parse_workspace_refs(text)
    assert len(refs) == 3
    assert refs[0].workspace_id == "abc"
    assert refs[0].path == "plan/plan_v1.md"
    assert refs[1].workspace_id == "def"
    assert refs[2].workspace_id == "abc"
    assert parse_workspace_refs("") == []
    assert parse_workspace_refs("no refs here") == []


# 3
def test_parse_workspace_refs_handles_duplicates_and_case() -> None:
    text = "[workspace:ABC/x.md] [workspace:abc/x.md] [WORKSPACE:abc/x.md]"
    refs = parse_workspace_refs(text)
    assert len(refs) == 3
    # Duplicates preserved
    assert all(r.path == "x.md" for r in refs)


# 4
def test_render_workspace_refs_md_substitutes_links() -> None:
    text = "go to [workspace:abc123/plan/plan_v1.md] now"
    out = render_workspace_refs_md(text)
    assert out == "go to [abc123/plan/plan_v1.md](/api/consultations/abc123/files/plan/plan_v1.md) now"
    # Empty
    assert render_workspace_refs_md("") == ""
    # Custom base url
    out2 = render_workspace_refs_md("[workspace:x/y.md]", base_url="/foo")
    assert out2 == "[x/y.md](/foo/x/files/y.md)"


# 5
@pytest.mark.asyncio
async def test_workspace_registry_create_produces_correct_dir_structure(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(
        title="X", owner_agent_id="captain", participants=["a", "b"]
    )
    repo = records.repo_path / "consultations" / ws.id
    for sub in ("inputs", "advisory", "plan", "artifacts", "outputs", "workitems"):
        assert (repo / sub).is_dir(), f"missing subdir {sub}"
    assert (repo / "manifest.yaml").is_file()
    assert (repo / "journal.md").is_file()
    assert (repo / "delivery.yaml").is_file()
    paths = await ws.list_paths()
    assert set(paths.keys()) == {"inputs", "advisory", "plan", "artifacts", "outputs", "workitems"}


# 6
@pytest.mark.asyncio
async def test_workspace_registry_create_manifest_schema(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(
        title="Topic", owner_agent_id="captain", participants=["a", "b"]
    )
    text = (records.repo_path / "consultations" / ws.id / "manifest.yaml").read_text("utf-8")
    m = yaml.safe_load(text)
    assert m["schema_version"] == 1
    assert m["id"] == ws.id
    assert m["title"] == "Topic"
    assert m["owner"] == "captain"
    assert m["participants"] == ["a", "b"]
    assert m["lifecycle_state"] == "INITIATED"
    assert isinstance(m["created_at"], float)
    assert isinstance(m["updated_at"], float)
    assert m["template"] == ""


# 7
@pytest.mark.asyncio
async def test_lifecycle_full_happy_path(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    sequence = [
        WorkspaceLifecycleState.CONSULTING,
        WorkspaceLifecycleState.PLAN_REVIEW,
        WorkspaceLifecycleState.APPROVED,
        WorkspaceLifecycleState.EXECUTING,
        WorkspaceLifecycleState.COMPLETED,
        WorkspaceLifecycleState.ARCHIVED,
    ]
    for s in sequence:
        ok = await ws.transition_to(s)
        assert ok is True, f"transition to {s.name} failed"
    assert ws.lifecycle_state == WorkspaceLifecycleState.ARCHIVED
    journal = (records.repo_path / "consultations" / ws.id / "journal.md").read_text("utf-8")
    # 7 lifecycle entries (one per transition above is 6, plus the create entry... but
    # we count "lifecycle:" prefix lines for state transitions only).
    lifecycle_lines = [ln for ln in journal.splitlines() if "lifecycle:" in ln]
    assert len(lifecycle_lines) == 6


# 8
@pytest.mark.asyncio
async def test_lifecycle_rejects_invalid_transition(
    registry: WorkspaceRegistry, records: RecordsStore, caplog
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    # Drive to EXECUTING
    for s in (
        WorkspaceLifecycleState.CONSULTING,
        WorkspaceLifecycleState.PLAN_REVIEW,
        WorkspaceLifecycleState.APPROVED,
        WorkspaceLifecycleState.EXECUTING,
    ):
        assert await ws.transition_to(s) is True
    import logging
    with caplog.at_level(logging.WARNING):
        ok = await ws.transition_to(WorkspaceLifecycleState.INITIATED)
    assert ok is False
    assert ws.lifecycle_state == WorkspaceLifecycleState.EXECUTING
    assert any("invalid lifecycle transition" in r.message for r in caplog.records)


# 9
@pytest.mark.asyncio
async def test_lifecycle_plan_review_can_revert_to_consulting(
    registry: WorkspaceRegistry,
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    assert await ws.transition_to(WorkspaceLifecycleState.CONSULTING) is True
    assert await ws.transition_to(WorkspaceLifecycleState.PLAN_REVIEW) is True
    assert await ws.transition_to(WorkspaceLifecycleState.CONSULTING) is True
    assert ws.lifecycle_state == WorkspaceLifecycleState.CONSULTING


# 10
class _UpperProcessor:
    name = "upper"

    def process(self, filename: str, content: bytes) -> tuple[str, bytes]:
        return filename + ".proc", content.upper()


@pytest.mark.asyncio
async def test_add_input_routes_through_input_processor(
    records: RecordsStore, clock
) -> None:
    proc: InputProcessor = _UpperProcessor()
    reg = WorkspaceRegistry(records, clock=clock, input_processor=proc)
    ws = await reg.create(title="X", owner_agent_id="captain", participants=[])
    await ws.add_input("report.txt", b"hello world")
    target = records.repo_path / "consultations" / ws.id / "inputs" / "report.txt.proc"
    assert target.is_file()
    assert target.read_text("utf-8") == "HELLO WORLD"


# 11
@pytest.mark.asyncio
async def test_add_advisory_writes_to_advisory_dir_with_agent_filename(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    path = await ws.add_advisory("medical", "Detailed body text", summary="Quick note")
    fname = Path(path).name
    assert fname.startswith("medical_") and fname.endswith(".md")
    full = records.repo_path / "consultations" / ws.id / "advisory" / fname
    assert full.is_file()
    text = full.read_text("utf-8")
    assert "# Advisory Report — medical" in text
    assert "Quick note" in text
    assert "Detailed body text" in text


# 12
@pytest.mark.asyncio
async def test_add_plan_iteration_creates_versioned_files(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    await ws.add_plan_iteration("# v1\n")
    await ws.add_plan_iteration("# v2\n")
    await ws.add_plan_iteration("# v3\n")
    plan_dir = records.repo_path / "consultations" / ws.id / "plan"
    assert (plan_dir / "plan_v1.md").is_file()
    assert (plan_dir / "plan_v2.md").is_file()
    assert (plan_dir / "plan_v3.md").is_file()


# 13
@pytest.mark.asyncio
async def test_add_artifact_and_add_output_write_to_their_dirs(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    await ws.add_artifact("data.txt", "blob")
    await ws.add_output("final.md", "# done")
    base = records.repo_path / "consultations" / ws.id
    assert (base / "artifacts" / "data.txt").is_file()
    assert (base / "outputs" / "final.md").is_file()


# 14
@pytest.mark.asyncio
async def test_add_work_item_serializes_yaml_under_workitems(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    spec = {"id": "abc-123", "title": "Do thing", "owner": "engineer"}
    path = await ws.add_work_item(spec)
    fname = Path(path).name
    assert fname == "wi_abc-123.yaml"
    text = (records.repo_path / "consultations" / ws.id / "workitems" / fname).read_text("utf-8")
    loaded = yaml.safe_load(text)
    assert loaded == spec
    # Fallback to uuid8 when no id present
    path2 = await ws.add_work_item({"title": "no-id"})
    fname2 = Path(path2).name
    assert fname2.startswith("wi_") and fname2.endswith(".yaml")
    assert fname2 != "wi_abc-123.yaml"


# 15
@pytest.mark.asyncio
async def test_journal_appended_on_every_state_change(
    registry: WorkspaceRegistry, records: RecordsStore
) -> None:
    ws = await registry.create(title="X", owner_agent_id="captain", participants=[])
    journal_path = records.repo_path / "consultations" / ws.id / "journal.md"
    initial_lines = len(journal_path.read_text("utf-8").splitlines())
    await ws.add_advisory("medical", "body")
    await ws.transition_to(WorkspaceLifecycleState.CONSULTING)
    await ws.add_input("note.txt", b"hi")
    final_lines = len(journal_path.read_text("utf-8").splitlines())
    assert final_lines - initial_lines == 3


# 16
@pytest.mark.asyncio
async def test_list_active_filters_archived(
    registry: WorkspaceRegistry,
) -> None:
    ws1 = await registry.create(title="alpha", owner_agent_id="captain", participants=["x"])
    ws2 = await registry.create(title="beta", owner_agent_id="captain", participants=["y", "z"])
    # archive ws1
    for s in (
        WorkspaceLifecycleState.CONSULTING,
        WorkspaceLifecycleState.PLAN_REVIEW,
        WorkspaceLifecycleState.APPROVED,
        WorkspaceLifecycleState.EXECUTING,
        WorkspaceLifecycleState.COMPLETED,
        WorkspaceLifecycleState.ARCHIVED,
    ):
        assert await ws1.transition_to(s) is True
    active = await registry.list_active()
    assert len(active) == 1
    summary = active[0]
    assert isinstance(summary, ConsultationWorkspaceSummary)
    assert summary.id == ws2.id
    assert summary.title == "beta"
    assert summary.participant_count == 2
    assert summary.state == WorkspaceLifecycleState.INITIATED
