# Copyright 2026 Sean Galliher. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""AD-536: Tests for procedure promotion shell commands in commands_procedure.py."""

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


def _make_runtime(store_mock=None, directive_store_mock=None):
    rt = MagicMock()
    rt.procedure_store = store_mock or MagicMock()
    rt.directive_store = directive_store_mock
    rt.ward_room = None
    rt.ontology = None
    return rt


def _make_pending_item(proc_id="abc123def456", name="Test Proc", level=4,
                       completions=15, effective_rate=0.85):
    return {
        "procedure_id": proc_id,
        "name": name,
        "compilation_level": level,
        "evolution_type": "CAPTURED",
        "intent_types": ["code_review"],
        "total_completions": completions,
        "effective_rate": effective_rate,
        "criticality": "low",
        "requested_at": "2026-04-01T12:00:00Z",
    }


def _make_promoted_item(proc_id="abc123def456", name="Promoted Proc", level=4,
                        completions=20, effective_rate=0.9):
    return {
        "procedure_id": proc_id,
        "name": name,
        "compilation_level": level,
        "evolution_type": "CAPTURED",
        "intent_types": ["code_review"],
        "total_completions": completions,
        "effective_rate": effective_rate,
        "decided_by": "captain",
        "directive_id": "dir-999",
    }


def _make_procedure_obj(proc_id="abc123def456", name="Test Proc"):
    """Create a mock Procedure object with required attributes."""
    from probos.cognitive.procedures import Procedure, ProcedureStep
    return Procedure(
        id=proc_id,
        name=name,
        description="test",
        steps=[ProcedureStep(step_number=1, action="do something")],
        intent_types=["code_review"],
        origin_agent_ids=["engineer_agent"],
    )


# ===========================================================================
# Shell command tests
# ===========================================================================


class TestProcedureCommands:
    """Tests for cmd_procedure shell command dispatch."""

    @pytest.mark.asyncio
    async def test_list_pending_with_items(self):
        """list-pending with pending items -> shows table."""
        store = MagicMock()
        store.get_pending_promotions = AsyncMock(return_value=[_make_pending_item()])
        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, "list-pending")

        text = output.getvalue()
        assert "Test Proc" in text
        assert "abc123de" in text  # truncated ID

    @pytest.mark.asyncio
    async def test_list_pending_empty(self):
        """list-pending with no items -> shows 'No pending'."""
        store = MagicMock()
        store.get_pending_promotions = AsyncMock(return_value=[])
        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, "list-pending")

        text = output.getvalue()
        assert "No pending" in text

    @pytest.mark.asyncio
    async def test_approve_calls_store(self):
        """approve test123 -> calls store.approve_promotion and creates directive."""
        proc_id = "test123fullid"
        store = MagicMock()
        store.get_promotion_status = AsyncMock(return_value="pending")
        store.get = AsyncMock(return_value=_make_procedure_obj(proc_id=proc_id))
        store.get_quality_metrics = AsyncMock(return_value={
            "effective_rate": 0.85,
            "total_completions": 15,
        })
        store.approve_promotion = AsyncMock()

        # Directive store mock
        directive_mock = MagicMock()
        directive_mock.id = "dir-123-456"
        ds = MagicMock()
        ds.create_directive = MagicMock(return_value=(directive_mock, "ok"))

        rt = _make_runtime(store_mock=store, directive_store_mock=ds)
        con, output = _make_console()

        await cmd_procedure(rt, con, f"approve {proc_id}")

        store.approve_promotion.assert_awaited_once_with(proc_id, "captain", "dir-123-456")

    @pytest.mark.asyncio
    async def test_reject_calls_store(self):
        """reject test123 --reason bad quality -> calls store.reject_promotion."""
        proc_id = "test123fullid"
        store = MagicMock()
        store.get_promotion_status = AsyncMock(return_value="pending")
        store.get = AsyncMock(return_value=_make_procedure_obj(proc_id=proc_id))
        store.get_pending_promotions = AsyncMock(return_value=[])
        store.reject_promotion = AsyncMock()

        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, f"reject {proc_id} --reason bad quality")

        store.reject_promotion.assert_awaited_once_with(proc_id, "captain", "bad quality")

    @pytest.mark.asyncio
    async def test_list_promoted_shows_table(self):
        """list-promoted -> shows promoted table."""
        store = MagicMock()
        store.get_promoted_procedures = AsyncMock(return_value=[_make_promoted_item()])
        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, "list-promoted")

        text = output.getvalue()
        assert "Promoted Proc" in text
        assert "captain" in text

    @pytest.mark.asyncio
    async def test_empty_args_shows_help(self):
        """Empty args -> shows help text."""
        rt = _make_runtime()
        con, output = _make_console()

        await cmd_procedure(rt, con, "")

        text = output.getvalue()
        assert "list-pending" in text
        assert "approve" in text
        assert "reject" in text

    @pytest.mark.asyncio
    async def test_approve_no_id_shows_usage(self):
        """approve with no ID -> shows usage."""
        rt = _make_runtime()
        con, output = _make_console()

        await cmd_procedure(rt, con, "approve")

        text = output.getvalue()
        assert "Usage" in text

    @pytest.mark.asyncio
    async def test_reject_no_reason_shows_required(self):
        """reject test123 without --reason -> shows reason required."""
        store = MagicMock()
        store.get_promotion_status = AsyncMock(return_value="pending")
        rt = _make_runtime(store_mock=store)
        con, output = _make_console()

        await cmd_procedure(rt, con, "reject test123")

        text = output.getvalue()
        assert "reason" in text.lower()
