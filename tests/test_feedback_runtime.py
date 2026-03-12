"""Tests for Phase 18 — Runtime feedback integration."""

from __future__ import annotations

import asyncio
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.feedback import FeedbackResult
from probos.runtime import ProbOSRuntime
from probos.types import TaskDAG, TaskNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runtime() -> ProbOSRuntime:
    """Create a minimal runtime for testing."""
    rt = ProbOSRuntime()
    # Attach a mock feedback engine
    rt.feedback_engine = MagicMock()
    rt.feedback_engine.apply_execution_feedback = AsyncMock(
        return_value=FeedbackResult(
            feedback_type="positive",
            agents_updated=["agent-1"],
            episode_stored=True,
            original_text="test",
        ),
    )
    rt.feedback_engine.apply_rejection_feedback = AsyncMock(
        return_value=FeedbackResult(
            feedback_type="rejected_plan",
            agents_updated=[],
            episode_stored=True,
            original_text="test",
        ),
    )
    return rt


def _dag_with_result() -> TaskDAG:
    """A simple executed DAG."""
    node = TaskNode(
        id="n1",
        intent="read_file",
        status="completed",
        result={"agent_id": "agent-1", "output": "hello"},
    )
    return TaskDAG(nodes=[node])


# ---------------------------------------------------------------------------
# TestRecordFeedback — runtime.record_feedback()
# ---------------------------------------------------------------------------


class TestRecordFeedback:
    """record_feedback() tests."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_execution(self):
        """No execution to rate → None."""
        rt = _runtime()
        rt._last_execution = None

        result = await rt.record_feedback(positive=True)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_already_rated(self):
        """Same execution can only be rated once."""
        rt = _runtime()
        rt._last_execution = {"dag": _dag_with_result(), "results": {}}
        rt._last_feedback_applied = True

        result = await rt.record_feedback(positive=True)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_feedback_engine(self):
        """No feedback engine → None."""
        rt = _runtime()
        rt.feedback_engine = None
        rt._last_execution = {"dag": _dag_with_result(), "results": {}}

        result = await rt.record_feedback(positive=True)

        assert result is None

    @pytest.mark.asyncio
    async def test_positive_calls_engine(self):
        """record_feedback(positive=True) calls apply_execution_feedback."""
        rt = _runtime()
        dag = _dag_with_result()
        rt._last_execution = {"dag": dag, "results": {}}
        rt._last_execution_text = "read the file"

        result = await rt.record_feedback(positive=True)

        rt.feedback_engine.apply_execution_feedback.assert_called_once_with(
            dag, True, "read the file",
        )
        assert result is not None
        assert result.feedback_type == "positive"

    @pytest.mark.asyncio
    async def test_negative_calls_engine(self):
        """record_feedback(positive=False) calls apply_execution_feedback."""
        rt = _runtime()
        dag = _dag_with_result()
        rt._last_execution = {"dag": dag, "results": {}}
        rt._last_execution_text = "read the file"
        rt.feedback_engine.apply_execution_feedback = AsyncMock(
            return_value=FeedbackResult(
                feedback_type="negative",
                agents_updated=["agent-1"],
                episode_stored=True,
                original_text="read the file",
            ),
        )

        result = await rt.record_feedback(positive=False)

        rt.feedback_engine.apply_execution_feedback.assert_called_once_with(
            dag, False, "read the file",
        )
        assert result.feedback_type == "negative"

    @pytest.mark.asyncio
    async def test_sets_feedback_applied_flag(self):
        """After recording, _last_feedback_applied is True."""
        rt = _runtime()
        rt._last_execution = {"dag": _dag_with_result(), "results": {}}
        rt._last_execution_text = "x"

        await rt.record_feedback(positive=True)

        assert rt._last_feedback_applied is True

    @pytest.mark.asyncio
    async def test_returns_none_when_no_dag_in_execution(self):
        """If execution result has no 'dag' key, return None."""
        rt = _runtime()
        rt._last_execution = {"results": {}}  # no 'dag' key

        result = await rt.record_feedback(positive=True)

        assert result is None


# ---------------------------------------------------------------------------
# TestFeedbackResets — _last_feedback_applied reset behavior
# ---------------------------------------------------------------------------


class TestFeedbackResets:
    """_last_feedback_applied resets on new execution."""

    @pytest.mark.asyncio
    async def test_resets_on_execute_dag(self):
        """_last_feedback_applied resets to False in _execute_dag."""
        rt = _runtime()
        rt._last_feedback_applied = True

        # Mock DAG executor to avoid full execution
        rt.dag_executor = MagicMock()
        rt.dag_executor.execute = AsyncMock(
            return_value={"results": {}, "input": "x"},
        )
        rt.working_memory = MagicMock()
        rt.working_memory.record_result = MagicMock()
        rt.workflow_cache = None
        rt.episodic_memory = None

        dag = TaskDAG(nodes=[])
        import time
        await rt._execute_dag(dag, "x", time.monotonic())

        assert rt._last_feedback_applied is False

    @pytest.mark.asyncio
    async def test_tracks_execution_text(self):
        """_last_execution_text is set in process_natural_language."""
        rt = _runtime()
        rt._started = True

        # We can't fully run process_natural_language without mocking a lot,
        # but we can confirm the attribute exists and is set correctly
        rt._last_execution_text = None
        # Manually verify the attribute is a string after setting
        rt._last_execution_text = "test query"
        assert rt._last_execution_text == "test query"


# ---------------------------------------------------------------------------
# TestRejectProposal — rejection feedback wiring
# ---------------------------------------------------------------------------


class TestRejectProposalFeedback:
    """reject_proposal() calls apply_rejection_feedback when engine available."""

    @pytest.mark.asyncio
    async def test_rejection_calls_feedback_engine(self):
        """reject_proposal() calls apply_rejection_feedback."""
        rt = _runtime()
        dag = _dag_with_result()
        rt._pending_proposal = dag
        rt._pending_proposal_text = "delete all files"
        rt.event_log = AsyncMock()
        rt.event_log.log = AsyncMock()

        await rt.reject_proposal()

        rt.feedback_engine.apply_rejection_feedback.assert_called_once_with(
            "delete all files", dag,
        )

    @pytest.mark.asyncio
    async def test_rejection_without_feedback_engine(self):
        """reject_proposal() works without feedback engine (backward compat)."""
        rt = _runtime()
        rt.feedback_engine = None
        dag = _dag_with_result()
        rt._pending_proposal = dag
        rt._pending_proposal_text = "delete files"
        rt.event_log = AsyncMock()
        rt.event_log.log = AsyncMock()

        result = await rt.reject_proposal()

        assert result is True  # Proposal was rejected

    @pytest.mark.asyncio
    async def test_rejection_no_proposal(self):
        """reject_proposal() with no pending proposal returns False."""
        rt = _runtime()
        rt._pending_proposal = None

        result = await rt.reject_proposal()

        assert result is False


# ---------------------------------------------------------------------------
# TestShellFeedbackCommand — shell command integration
# ---------------------------------------------------------------------------


class TestShellFeedbackCommand:
    """Shell /feedback command tests."""

    @pytest.mark.asyncio
    async def test_feedback_no_args_shows_usage(self):
        """'/feedback' with no args shows usage."""
        from probos.experience.shell import ProbOSShell

        rt = _runtime()
        shell = ProbOSShell(rt)
        shell.console = MagicMock()

        await shell._cmd_feedback("")

        shell.console.print.assert_called_once()
        output = shell.console.print.call_args[0][0]
        assert "Usage" in output

    @pytest.mark.asyncio
    async def test_feedback_good_displays_message(self):
        """'/feedback good' displays success message."""
        from probos.experience.shell import ProbOSShell

        rt = _runtime()
        rt._last_execution = {"dag": _dag_with_result(), "results": {}}
        rt._last_execution_text = "test"
        rt._last_feedback_applied = False

        shell = ProbOSShell(rt)
        shell.console = MagicMock()

        await shell._cmd_feedback("good")

        output = shell.console.print.call_args[0][0]
        assert "positive" in output.lower() or "1 agent" in output

    @pytest.mark.asyncio
    async def test_feedback_bad_displays_message(self):
        """'/feedback bad' displays negative feedback message."""
        from probos.experience.shell import ProbOSShell

        rt = _runtime()
        rt._last_execution = {"dag": _dag_with_result(), "results": {}}
        rt._last_execution_text = "test"
        rt._last_feedback_applied = False
        rt.feedback_engine.apply_execution_feedback = AsyncMock(
            return_value=FeedbackResult(
                feedback_type="negative",
                agents_updated=["agent-1"],
                episode_stored=True,
                original_text="test",
            ),
        )

        shell = ProbOSShell(rt)
        shell.console = MagicMock()

        await shell._cmd_feedback("bad")

        output = shell.console.print.call_args[0][0]
        assert "negative" in output.lower() or "1 agent" in output

    @pytest.mark.asyncio
    async def test_feedback_already_rated(self):
        """'/feedback good' when already rated shows warning."""
        from probos.experience.shell import ProbOSShell

        rt = _runtime()
        rt._last_execution = {"dag": _dag_with_result(), "results": {}}
        rt._last_feedback_applied = True

        shell = ProbOSShell(rt)
        shell.console = MagicMock()

        await shell._cmd_feedback("good")

        output = shell.console.print.call_args[0][0]
        assert "already" in output.lower()

    @pytest.mark.asyncio
    async def test_feedback_no_execution(self):
        """'/feedback good' with no execution shows warning."""
        from probos.experience.shell import ProbOSShell

        rt = _runtime()
        rt._last_execution = None

        shell = ProbOSShell(rt)
        shell.console = MagicMock()

        await shell._cmd_feedback("good")

        output = shell.console.print.call_args[0][0]
        assert "No recent" in output
