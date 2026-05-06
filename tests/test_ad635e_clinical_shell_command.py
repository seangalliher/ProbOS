"""Tests for AD-635e clinical telemetry shell command."""
from __future__ import annotations

import pytest
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from rich.console import Console

from probos.cognitive.clinical_telemetry import ClinicalTelemetryService
from probos.experience.commands import commands_clinical
from probos.experience.shell import ProbOSShell
from probos.runtime import ProbOSRuntime


@pytest.fixture
def console():
    # Plain-text console: disable ANSI/highlighting so substring assertions
    # see the literal token "/clinical dreams" without color escapes splitting
    # the path. Markup (`[bold]...[/bold]`) is still parsed and stripped.
    return Console(
        file=StringIO(),
        width=120,
        force_terminal=False,
        no_color=True,
        highlight=False,
        markup=True,
    )


def get_output(con: Console) -> str:
    con.file.seek(0)
    return con.file.read()


def _make_service_runtime(*, agent_type: str = "") -> MagicMock:
    """Build a minimal runtime stub for ClinicalTelemetryService.

    `_resolve_agent_type` reads `runtime.registry.get(agent_id).agent_type`.
    Defaulting to `""` ensures the captain is NOT in CLINICAL_ROLES so the
    captain bypass branch is exercised.
    """
    rt = MagicMock()
    fake_agent = MagicMock()
    fake_agent.agent_type = agent_type
    rt.registry.get = MagicMock(return_value=fake_agent)
    rt.acm = MagicMock()
    rt.acm.get = MagicMock(return_value=None)
    rt.ontology = None
    rt.clearance_grant_store = None
    return rt


# ---------------------------------------------------------------------------
# 1) Service-side captain bypass
# ---------------------------------------------------------------------------

class TestServiceCaptainOverride:
    @pytest.mark.asyncio
    async def test_query_dream_history_captain_override_bypasses_gate(self):
        rt = _make_service_runtime(agent_type="")
        rt._emergent_detector = MagicMock()
        rt._emergent_detector.recent_dreams = MagicMock(
            return_value=[{"ts": 1.0, "episodes_replayed": 5}]
        )
        service = ClinicalTelemetryService(rt)

        rows = await service.query_dream_history(
            requester_agent_id="captain", captain_override=True
        )
        assert rows == [{"ts": 1.0, "episodes_replayed": 5}]
        assert service.audit_log[-1]["granted"] is True

    @pytest.mark.asyncio
    async def test_query_dream_history_captain_override_audits_by_captain(self):
        rt = _make_service_runtime(agent_type="")
        rt._emergent_detector = MagicMock()
        rt._emergent_detector.recent_dreams = MagicMock(return_value=[])
        service = ClinicalTelemetryService(rt)

        await service.query_dream_history(
            requester_agent_id="captain", captain_override=True
        )
        assert service.audit_log[-1]["by_captain"] is True

    @pytest.mark.asyncio
    async def test_query_dream_history_default_no_by_captain_field(self):
        rt = _make_service_runtime(agent_type="diagnostician")
        rt._emergent_detector = MagicMock()
        rt._emergent_detector.recent_dreams = MagicMock(return_value=[])
        service = ClinicalTelemetryService(rt)

        # No captain_override -> default False; existing entries must NOT
        # include `by_captain` (additive-field contract).
        await service.query_dream_history(requester_agent_id="diag-1")
        assert "by_captain" not in service.audit_log[-1]

    @pytest.mark.asyncio
    async def test_query_agent_chain_traces_captain_override_bypasses_gate(self):
        rt = _make_service_runtime(agent_type="")
        rt.cognitive_journal = MagicMock()
        rt.cognitive_journal.get_recent_chain_traces = AsyncMock(
            return_value=[{"chain_id": "abc", "outcome": "ok"}]
        )
        service = ClinicalTelemetryService(rt)

        rows = await service.query_agent_chain_traces(
            requester_agent_id="captain",
            target_agent_id="alice",
            captain_override=True,
        )
        assert rows == [{"chain_id": "abc", "outcome": "ok"}]
        assert service.audit_log[-1]["granted"] is True

    @pytest.mark.asyncio
    async def test_query_agent_chain_traces_captain_override_audits_by_captain(self):
        rt = _make_service_runtime(agent_type="")
        rt.cognitive_journal = MagicMock()
        rt.cognitive_journal.get_recent_chain_traces = AsyncMock(return_value=[])
        service = ClinicalTelemetryService(rt)

        await service.query_agent_chain_traces(
            requester_agent_id="captain",
            target_agent_id="alice",
            captain_override=True,
        )
        assert service.audit_log[-1]["by_captain"] is True

    @pytest.mark.asyncio
    async def test_query_circuit_breaker_history_captain_override_bypasses_gate(self):
        rt = _make_service_runtime(agent_type="")
        store = MagicMock()
        store.recent = AsyncMock(
            return_value=[{"agent_id": "alice", "state": "OPEN"}]
        )
        service = ClinicalTelemetryService(
            rt, circuit_breaker_history_store=store
        )

        rows = await service.query_circuit_breaker_history(
            requester_agent_id="captain", captain_override=True
        )
        assert rows == [{"agent_id": "alice", "state": "OPEN"}]
        last = service.audit_log[-1]
        assert last["granted"] is True
        assert last["by_captain"] is True


# ---------------------------------------------------------------------------
# 2) Shell registration
# ---------------------------------------------------------------------------

class TestShellRegistration:
    def test_clinical_command_in_COMMANDS(self):
        assert "/clinical" in ProbOSShell.COMMANDS

    def test_clinical_command_help_text_mentions_captain_authority(self):
        assert "Captain" in ProbOSShell.COMMANDS["/clinical"]

    def test_cmd_clinical_proxy_exists(self):
        assert hasattr(ProbOSShell, "_cmd_clinical")
        assert callable(ProbOSShell._cmd_clinical)


# ---------------------------------------------------------------------------
# 3) cmd_clinical dispatch
# ---------------------------------------------------------------------------

class TestCmdClinicalDispatch:
    @pytest.mark.asyncio
    async def test_service_disabled_prints_message(self, console):
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = None
        await commands_clinical.cmd_clinical(rt, console, "")
        out = get_output(console).lower()
        assert "not enabled" in out

    @pytest.mark.asyncio
    async def test_no_args_prints_usage(self, console):
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = MagicMock()
        await commands_clinical.cmd_clinical(rt, console, "")
        out = get_output(console)
        assert "/clinical dreams" in out
        assert "/clinical traces" in out

    @pytest.mark.asyncio
    async def test_unknown_subcommand_prints_error(self, console):
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = MagicMock()
        await commands_clinical.cmd_clinical(rt, console, "frobulate")
        out = get_output(console)
        assert "Unknown subcommand: frobulate" in out
        assert "/clinical dreams" in out

    @pytest.mark.asyncio
    async def test_dreams_invalid_limit_prints_usage_error(self, console):
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = MagicMock()
        await commands_clinical.cmd_clinical(rt, console, "dreams notanumber")
        out = get_output(console)
        assert "Usage" in out
        assert "notanumber" in out

    @pytest.mark.asyncio
    async def test_traces_missing_agent_id_prints_usage_error(self, console):
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = MagicMock()
        await commands_clinical.cmd_clinical(rt, console, "traces")
        out = get_output(console)
        assert "Usage: /clinical traces <agent_id>" in out


# ---------------------------------------------------------------------------
# 4) cmd_clinical query happy paths
# ---------------------------------------------------------------------------

class TestCmdClinicalQueries:
    @pytest.mark.asyncio
    async def test_dreams_calls_service_with_captain_override(self, console):
        service = MagicMock()
        service.query_dream_history = AsyncMock(
            return_value=[{"ts": 1.0, "episodes_replayed": 5}]
        )
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = service

        await commands_clinical.cmd_clinical(rt, console, "dreams 7")
        assert service.query_dream_history.await_args.kwargs == {
            "requester_agent_id": "captain",
            "limit": 7,
            "captain_override": True,
        }

    @pytest.mark.asyncio
    async def test_traces_calls_service_per_agent(self, console):
        service = MagicMock()
        service.query_agent_chain_traces = AsyncMock(return_value=[])
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = service

        await commands_clinical.cmd_clinical(rt, console, "traces alice 5")
        kwargs = service.query_agent_chain_traces.await_args.kwargs
        assert kwargs["requester_agent_id"] == "captain"
        assert kwargs["target_agent_id"] == "alice"
        assert kwargs["limit"] == 5
        assert kwargs["captain_override"] is True

    @pytest.mark.asyncio
    async def test_breakers_no_agent_id_calls_fleet_wide(self, console):
        service = MagicMock()
        service.query_circuit_breaker_history = AsyncMock(return_value=[])
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = service

        await commands_clinical.cmd_clinical(rt, console, "breakers")
        kwargs = service.query_circuit_breaker_history.await_args.kwargs
        assert kwargs["target_agent_id"] is None
        assert kwargs["captain_override"] is True

    @pytest.mark.asyncio
    async def test_audit_uses_audit_log_property_with_slice(self, console):
        service = MagicMock()
        entries = [
            {
                "ts": float(i),
                "requester_agent_id": f"agent-{i}",
                "query_type": "dream_history",
                "granted": True,
                "result_count": 0,
            }
            for i in range(5)
        ]
        type(service).audit_log = PropertyMock(return_value=entries)
        rt = MagicMock(spec=ProbOSRuntime)
        rt.clinical_telemetry = service

        await commands_clinical.cmd_clinical(rt, console, "audit 2")
        out = get_output(console)
        # Last 2 entries -> agent-3 and agent-4 must appear; agent-0 must not.
        assert "agent-3" in out
        assert "agent-4" in out
        assert "agent-0" not in out
