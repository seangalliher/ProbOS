# Copyright 2026 Sean Galliher. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""AD-537: Tests for observational learning shell commands (teach, observed)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.experience.commands.commands_procedure import cmd_procedure


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_console():
    output = StringIO()
    con = Console(file=output, no_color=True, force_terminal=False, width=120)
    return con, output


def _make_runtime(store_mock=None, ward_room_mock=None):
    rt = MagicMock()
    rt.procedure_store = store_mock or MagicMock()
    rt.directive_store = None
    rt.ward_room = ward_room_mock
    rt.ontology = None
    return rt


def _make_procedure_obj(proc_id="abc123def456", name="Test Proc",
                        compilation_level=5):
    """Create a mock Procedure object with required attributes."""
    from probos.cognitive.procedures import Procedure, ProcedureStep
    return Procedure(
        id=proc_id,
        name=name,
        description="test procedure",
        steps=[ProcedureStep(step_number=1, action="do something")],
        intent_types=["code_review"],
        origin_agent_ids=["engineer_agent"],
        compilation_level=compilation_level,
    )


def _make_observed_item(proc_id="obs-proc-001", name="Observed Proc",
                        learned_via="taught", learned_from="engineer_agent",
                        level=5, completions=10, effective_rate=0.9):
    return {
        "procedure_id": proc_id,
        "name": name,
        "learned_via": learned_via,
        "learned_from": learned_from,
        "compilation_level": level,
        "total_completions": completions,
        "effective_rate": effective_rate,
    }


# ===========================================================================
# Shell command tests
# ===========================================================================


class TestObservationalCommands:
    """Tests for AD-537 observational learning shell commands."""

    @pytest.mark.asyncio
    async def test_procedure_teach_command(self):
        """teach proc_id target -> calls ward_room DM flow."""
        proc_id = "teach_proc_001"
        target = "science_officer"
        store = MagicMock()
        store.get = AsyncMock(
            return_value=_make_procedure_obj(proc_id=proc_id, compilation_level=5)
        )
        store.get_promotion_status = AsyncMock(return_value="approved")
        store.get_quality_metrics = AsyncMock(return_value={
            "total_completions": 20,
            "effective_rate": 0.95,
        })

        dm_channel = MagicMock()
        dm_channel.id = "dm-chan-123"
        ward_room = MagicMock()
        ward_room.get_or_create_dm_channel = AsyncMock(return_value=dm_channel)
        ward_room.create_thread = AsyncMock()

        rt = _make_runtime(store_mock=store, ward_room_mock=ward_room)
        con, output = _make_console()

        await cmd_procedure(rt, con, f"teach {proc_id} {target}")

        ward_room.get_or_create_dm_channel.assert_awaited_once()
        ward_room.create_thread.assert_awaited_once()
        text = output.getvalue()
        assert "Teaching Sent" in text
        assert target in text

    @pytest.mark.asyncio
    async def test_procedure_teach_precondition_failure(self):
        """teach with procedure below Level 5 -> prints error."""
        proc_id = "low_level_proc"
        store = MagicMock()
        store.get = AsyncMock(
            return_value=_make_procedure_obj(proc_id=proc_id, compilation_level=3)
        )

        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, f"teach {proc_id} some_agent")

        text = output.getvalue()
        assert "Level 5" in text
        assert "current: Level 3" in text

    @pytest.mark.asyncio
    async def test_procedure_observed_list(self):
        """observed -> lists observed/taught procedures in a table."""
        store = MagicMock()
        store.get_observed_procedures = AsyncMock(return_value=[
            _make_observed_item(proc_id="obs-001", name="Observed Alpha",
                                learned_via="taught", learned_from="engineer"),
            _make_observed_item(proc_id="obs-002", name="Observed Beta",
                                learned_via="observed", learned_from="science"),
        ])

        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, "observed")

        store.get_observed_procedures.assert_awaited_once_with(agent=None)
        text = output.getvalue()
        assert "Observed Alpha" in text
        assert "Observed Beta" in text

    @pytest.mark.asyncio
    async def test_procedure_observed_filter_by_agent(self):
        """observed --agent test_agent -> passes agent filter to store."""
        store = MagicMock()
        store.get_observed_procedures = AsyncMock(return_value=[
            _make_observed_item(proc_id="obs-filtered", name="Filtered Proc",
                                learned_from="test_agent"),
        ])

        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, "observed --agent test_agent")

        store.get_observed_procedures.assert_awaited_once_with(agent="test_agent")
        text = output.getvalue()
        assert "Filtered Proc" in text

    @pytest.mark.asyncio
    async def test_procedure_observed_empty(self):
        """observed with no results -> prints 'No observed or taught procedures'."""
        store = MagicMock()
        store.get_observed_procedures = AsyncMock(return_value=[])

        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, "observed")

        text = output.getvalue()
        assert "No observed or taught procedures" in text
