"""BF-947 (#1724) M1: the confinement's answered verdict and its record of admitted results.

The real ``ToolCallConfinement``; the gates and the records are plain functions. On the base this file fails at import
(``CONFINED_CALL_ANSWERED``).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import (
    CONFINED_CALL_ANSWERED,
    CONFINEMENT_ADMIT,
    CONFINEMENT_ANSWERED,
    ToolCallConfinement,
    classify_tool_fault_error,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.tools.protocol import ToolResult

READ_SET = frozenset({"event_log_query"})


async def _answered(agent_id: str, tool_id: Any, params: Any) -> str:
    return CONFINEMENT_ANSWERED


async def _admit(agent_id: str, tool_id: Any, params: Any) -> str:
    return CONFINEMENT_ADMIT


# MC10
async def test_an_answered_call_never_runs_and_its_refusal_is_a_never_ran_policy_outcome() -> None:
    result = await ToolCallConfinement(READ_SET, _answered).refuse_or_admit("forge-1", "hull_survey", {})
    assert result is not None and result.error == CONFINED_CALL_ANSWERED
    assert CONFINED_CALL_ANSWERED in agentic_dispatch._NEVER_RAN_REFUSALS
    assert not is_capability_gap(CONFINED_CALL_ANSWERED)
    assert classify_tool_fault_error(CONFINED_CALL_ANSWERED) == "permission_denied"
    assert await ToolCallConfinement(READ_SET, _admit).refuse_or_admit("forge-1", "hull_survey", {}) is None


# MC11
def test_an_admitted_result_is_handed_to_record_and_a_record_that_raises_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: list[tuple[Any, ...]] = []
    result = ToolResult(output="Hull integrity 98 percent; survey record written.")
    ToolCallConfinement(READ_SET, _admit, record=lambda *call: seen.append(call)).record_admitted(
        "forge-1", "hull_survey", {"deck": "1"}, result,
    )
    assert seen == [("forge-1", "hull_survey", {"deck": "1"}, result)]
    ToolCallConfinement(READ_SET, _admit).record_admitted("forge-1", "hull_survey", {}, result)  # no record set

    def broken(*call: Any) -> None:
        raise RuntimeError("store down")

    with caplog.at_level(logging.WARNING):
        ToolCallConfinement(READ_SET, _admit, record=broken).record_admitted("forge-1", "hull_survey", {}, result)
    assert "was not kept for a later run" in caplog.text
    with pytest.raises(ValueError, match="tool_call_confinement_invalid"):
        ToolCallConfinement(READ_SET, _admit, record="not callable")  # type: ignore[arg-type]
