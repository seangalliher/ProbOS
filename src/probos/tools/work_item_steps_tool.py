from __future__ import annotations

import logging
import time
from typing import Any

from probos import work_item_steps as owned_steps
from probos.tools.protocol import (
    ToolResult,
    ToolResultPresentation,
    ToolType,
    refuse_undeclared_params,
)

logger = logging.getLogger(__name__)


class ReadOwnedStepsTool:
    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    @property
    def tool_id(self) -> str:
        return "read_owned_steps"

    @property
    def name(self) -> str:
        return "Read Owned Steps"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    @property
    def description(self) -> str:
        return (
            "Read one immutable governed page of the current crew-owned steps. "
            "Use cursor for another page or row_id for an exact row. The result "
            "is read-only and includes absolute ordinals, actions, view_id, "
            "cursors, omissions, and authenticated detail recovery."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "work_item_id": {"type": "string"},
                "cursor": {"type": "string"},
                "row_id": {"type": "string"},
            },
            "required": ["work_item_id"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "string"}

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        started = time.monotonic()
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        invocation = context if type(context) is dict else {}
        presentation = invocation.get("_tool_result_presentation")
        if (
            type(presentation) is not ToolResultPresentation
            or not callable(presentation.render_complete)
        ):
            return self._error(
                "owned_steps_presentation_required",
                started,
            )
        work_item_id = params.get("work_item_id")
        cursor = params.get("cursor")
        row_id = params.get("row_id")
        if (
            type(work_item_id) is not str
            or not work_item_id
            or (cursor is not None and type(cursor) is not str)
            or (row_id is not None and type(row_id) is not str)
            or (cursor is not None and row_id is not None)
        ):
            return self._error("owned_steps_tool_input_invalid", started)
        agent_id = invocation.get("agent_id")
        thread_id = invocation.get("thread_id")
        turn_id = invocation.get("owned_steps_turn_id")
        if (
            type(agent_id) is not str
            or not agent_id
            or type(thread_id) is not str
            or type(turn_id) is not str
            or not turn_id
        ):
            return self._error("owned_steps_actual_context_invalid", started)
        owner = getattr(self._runtime, "crew_orchestrator", None)
        service = getattr(self._runtime, "crew_session_service", None)
        if owner is None or service is None:
            return self._error("owned_steps_view_unavailable", started)
        try:
            actual_context = await owner.owned_steps_actual_context(
                service.agent_principal(agent_id),
                work_item_id=work_item_id,
                turn_id=turn_id,
            )
            if actual_context.thread_id != thread_id:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_view_scope_conflict",
                    parent_id=actual_context.parent_id,
                )
            reference = await owner.capture_owned_steps_view(
                actual_context,
                requested_item_id=work_item_id,
                cursor=row_id or cursor,
            )
            view = await owner.resolve_owned_steps_view(
                reference,
                actual_context,
            )
            value = {
                "reference": reference.model_dump(mode="json"),
                "view": view.model_dump(mode="json"),
            }
            rendered = presentation.render_complete(value)
            if type(rendered) is not str or not rendered:
                raise owned_steps.OwnedStepsError(
                    "owned_steps_view_budget",
                    parent_id=view.parent_id,
                    view_id=view.view_id,
                    actions=("page", "detail", "view_budget"),
                )
            return ToolResult(
                output=rendered,
                duration_ms=(time.monotonic() - started) * 1000.0,
                metadata={
                    "owned_steps_view_reference": reference.model_dump(
                        mode="json"
                    )
                },
            )
        except owned_steps.OwnedStepsError as exc:
            return self._error(
                owned_steps.render_owned_steps_feedback(exc),
                started,
            )
        except Exception as exc:
            logger.warning(
                "Owned-steps tool read failed (%s); no presentation authority "
                "was granted and the model receives an explicit refusal",
                type(exc).__name__,
                exc_info=True,
            )
            return self._error("owned_steps_read_failed", started)

    @staticmethod
    def _error(reason: str, started: float) -> ToolResult:
        return ToolResult(
            error=reason,
            duration_ms=(time.monotonic() - started) * 1000.0,
            metadata={"reason": reason},
        )
