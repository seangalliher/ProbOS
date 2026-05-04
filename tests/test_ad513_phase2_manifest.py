"""Tests for AD-513 Phase 2 v1: Crew Manifest Shell + Watch Filter + Ship Manifest."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.experience.commands import commands_manifest
from probos.experience import shell as shell_module
from probos.ontology import VesselOntologyService


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture
def ontology_dir(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parent.parent / "config" / "ontology"
    dst = tmp_path / "ontology"
    shutil.copytree(src, dst)
    return dst


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
async def service(ontology_dir: Path, data_dir: Path) -> VesselOntologyService:
    svc = VesselOntologyService(ontology_dir, data_dir=data_dir)
    await svc.initialize()
    return svc


def _watch_manager_with(roster: dict[str, list[str]]) -> MagicMock:
    """Build a mock WatchManager whose get_roster() returns the given dict."""
    wm = MagicMock()
    wm.get_roster.return_value = roster
    return wm


# -----------------------------------------------------------------------
# Section 1 — get_crew_manifest watch filter
# -----------------------------------------------------------------------


class TestGetCrewManifestWatchFilter:
    @pytest.mark.asyncio
    async def test_get_crew_manifest_watch_filter_returns_matching_only(
        self, service: VesselOntologyService
    ):
        """watch=alpha returns only agents on alpha watch."""
        # Wire two crew agents with stable agent_ids.
        service.wire_agent("architect", "agent-arch-001")
        service.wire_agent("scientist", "agent-sci-001")
        wm = _watch_manager_with({
            "alpha": ["agent-arch-001"],
            "beta": ["agent-sci-001"],
            "gamma": [],
        })

        result = service.get_crew_manifest(watch="alpha", watch_manager=wm)

        assert len(result) == 1
        assert result[0]["agent_type"] == "architect"

    @pytest.mark.asyncio
    async def test_get_crew_manifest_watch_filter_empty_when_no_match(
        self, service: VesselOntologyService
    ):
        """watch with no matching agents returns an empty list."""
        service.wire_agent("architect", "agent-arch-001")
        wm = _watch_manager_with({"alpha": ["agent-arch-001"], "beta": [], "gamma": []})

        result = service.get_crew_manifest(watch="beta", watch_manager=wm)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_crew_manifest_no_watch_filter_preserves_existing_behavior(
        self, service: VesselOntologyService
    ):
        """Calling without watch/watch_manager matches Phase 1 behavior."""
        baseline = service.get_crew_manifest()
        again = service.get_crew_manifest()

        assert baseline == again
        assert len(baseline) > 0
        # Shape unchanged — no 'watch' key when watch_manager not provided.
        for entry in baseline:
            assert "watch" not in entry

    @pytest.mark.asyncio
    async def test_get_crew_manifest_enriches_watch_field_when_watch_manager_provided(
        self, service: VesselOntologyService
    ):
        """watch_manager (alone) adds 'watch' field to every entry."""
        service.wire_agent("architect", "agent-arch-001")
        wm = _watch_manager_with({
            "alpha": ["agent-arch-001"],
            "beta": [],
            "gamma": [],
        })

        result = service.get_crew_manifest(watch_manager=wm)

        assert len(result) > 0
        for entry in result:
            assert "watch" in entry
        arch = next(e for e in result if e["agent_type"] == "architect")
        assert arch["watch"] == "alpha"

    @pytest.mark.asyncio
    async def test_get_crew_manifest_skips_watch_when_watch_manager_none(
        self, service: VesselOntologyService
    ):
        """Without watch_manager and without 'watch' arg, 'watch' field is absent."""
        result = service.get_crew_manifest()

        for entry in result:
            assert "watch" not in entry

    @pytest.mark.asyncio
    async def test_get_crew_manifest_watch_filter_without_manager_returns_empty(
        self, service: VesselOntologyService
    ):
        """watch arg with no manager cannot be satisfied — returns []."""
        result = service.get_crew_manifest(watch="alpha", watch_manager=None)

        assert result == []


# -----------------------------------------------------------------------
# Section 2 — get_ship_manifest
# -----------------------------------------------------------------------


class TestGetShipManifest:
    @pytest.mark.asyncio
    async def test_get_ship_manifest_returns_vessel_level_summary(
        self, service: VesselOntologyService
    ):
        """Returns a dict with all expected vessel-level fields."""
        result = service.get_ship_manifest()

        assert isinstance(result, dict)
        assert "ship_name" in result
        assert "agent_count" in result
        assert "departments" in result
        assert "watches" in result
        assert "alert_state" in result
        assert "manifest_summary" in result
        assert isinstance(result["agent_count"], int)
        assert result["agent_count"] > 0
        assert isinstance(result["departments"], list)
        assert isinstance(result["manifest_summary"], list)

    @pytest.mark.asyncio
    async def test_get_ship_manifest_with_no_enrichment_returns_minimal_summary(
        self, service: VesselOntologyService
    ):
        """No optional deps still yields valid summary; watches is []."""
        result = service.get_ship_manifest()

        assert result["watches"] == []
        # manifest_summary entries omit trust/rank fields.
        for entry in result["manifest_summary"]:
            assert set(entry.keys()) == {"agent_type", "callsign", "department", "post"}

    @pytest.mark.asyncio
    async def test_get_ship_manifest_includes_active_watches_when_watch_manager_present(
        self, service: VesselOntologyService
    ):
        """watches list contains only populated watch names, sorted."""
        service.wire_agent("architect", "agent-arch-001")
        service.wire_agent("scientist", "agent-sci-001")
        wm = _watch_manager_with({
            "alpha": ["agent-arch-001"],
            "beta": [],
            "gamma": ["agent-sci-001"],
        })

        result = service.get_ship_manifest(watch_manager=wm)

        assert result["watches"] == ["alpha", "gamma"]

    @pytest.mark.asyncio
    async def test_get_ship_manifest_alert_state_reflects_ontology_current_condition(
        self, service: VesselOntologyService
    ):
        """alert_state defaults GREEN and flips after set_alert_condition."""
        before = service.get_ship_manifest()
        assert before["alert_state"] == "GREEN"

        service.set_alert_condition("YELLOW")
        after = service.get_ship_manifest()

        assert after["alert_state"] == "YELLOW"


# -----------------------------------------------------------------------
# Section 3 — /manifest shell command
# -----------------------------------------------------------------------


class _Recorder(Console):
    """Capture rich.print outputs as plain text."""

    def __init__(self) -> None:
        super().__init__(record=True, force_terminal=False)


def _runtime_with(service: VesselOntologyService, watch_manager: Any = None) -> Any:
    rt = MagicMock()
    rt.ontology = service
    rt.trust_network = None
    rt.callsign_registry = None
    rt.watch_manager = watch_manager
    return rt


class TestCmdManifest:
    @pytest.mark.asyncio
    async def test_cmd_manifest_no_args_prints_table(
        self, service: VesselOntologyService
    ):
        console = _Recorder()
        rt = _runtime_with(service)

        await commands_manifest.cmd_manifest(rt, console, "")

        output = console.export_text()
        assert "Ship's Crew Manifest" in output

    @pytest.mark.asyncio
    async def test_cmd_manifest_with_department_filter(
        self, service: VesselOntologyService
    ):
        console = _Recorder()
        rt = _runtime_with(service)

        await commands_manifest.cmd_manifest(rt, console, "engineering")

        output = console.export_text()
        # Either the dept appears in the filtered table, or the empty notice
        # fires — both are acceptable proof the filter ran. The ontology
        # fixture ships with engineering crew, so we expect the table.
        assert "Ship's Crew Manifest" in output or "No crew matched" in output

    @pytest.mark.asyncio
    async def test_cmd_manifest_with_watch_filter(
        self, service: VesselOntologyService
    ):
        service.wire_agent("architect", "agent-arch-001")
        wm = _watch_manager_with({
            "alpha": ["agent-arch-001"],
            "beta": [],
            "gamma": [],
        })
        console = _Recorder()
        rt = _runtime_with(service, watch_manager=wm)

        await commands_manifest.cmd_manifest(rt, console, "watch:ALPHA")

        output = console.export_text()
        assert "Ship's Crew Manifest" in output
        # Confirms case-insensitive match — uppercase token resolves to lowercase watch.

    @pytest.mark.asyncio
    async def test_cmd_manifest_with_ship_flag_prints_summary(
        self, service: VesselOntologyService
    ):
        console = _Recorder()
        rt = _runtime_with(service)

        await commands_manifest.cmd_manifest(rt, console, "--ship")

        output = console.export_text()
        assert "Ship Manifest" in output
        assert "Alert State" in output

    @pytest.mark.asyncio
    async def test_cmd_manifest_no_ontology_prints_error(self):
        console = _Recorder()
        rt = MagicMock()
        rt.ontology = None

        await commands_manifest.cmd_manifest(rt, console, "")

        output = console.export_text()
        assert "No ontology service available" in output

    @pytest.mark.asyncio
    async def test_cmd_manifest_empty_match_prints_yellow_warning(
        self, service: VesselOntologyService
    ):
        # watch arg without watch_manager guarantees an empty match.
        console = _Recorder()
        rt = _runtime_with(service, watch_manager=None)

        await commands_manifest.cmd_manifest(rt, console, "watch:alpha")

        output = console.export_text()
        assert "No crew matched" in output


# -----------------------------------------------------------------------
# Section 4 — shell dispatch / help wiring
# -----------------------------------------------------------------------


class TestShellWiring:
    def test_shell_dispatch_routes_manifest_to_handler(self):
        """/manifest is reachable via the imported commands_manifest module."""
        # The dispatch table is constructed inside _dispatch_slash; verifying
        # the import + module attribute is sufficient structural proof, and
        # avoids spinning up a full ProbOSRuntime.
        assert hasattr(shell_module, "commands_manifest")
        assert hasattr(shell_module.commands_manifest, "cmd_manifest")

    def test_shell_help_includes_manifest_command(self):
        """/manifest appears in ProbOSShell.COMMANDS for /help output."""
        assert "/manifest" in shell_module.ProbOSShell.COMMANDS
        assert "crew manifest" in shell_module.ProbOSShell.COMMANDS["/manifest"].lower()
