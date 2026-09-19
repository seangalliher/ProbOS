"""AD-1187: governed discovery and exact-ID ownership of published standalone work.

Success outputs are accepted, pre-rendered Python-literal objects, not raw
containers or JSON. The invocation's ToolResultPresentation owns rendering and
admission; the store alone owns eligibility, assignment, transactions and events.
"""

from __future__ import annotations

import logging
import time
from dataclasses import fields, replace
from typing import Any, Callable, Literal, Protocol

from probos.tools.protocol import (
    ToolResult, ToolResultPresentation, ToolType, refuse_undeclared_params,
)
from probos.workforce import BookableResource, Booking, ReadyWorkPage, WorkItem

logger = logging.getLogger(__name__)

WORK_PULL_ROOM_CONTEXT_KEYS = frozenset({"_crew_session_id", "_crew_work_item_id"})
_DESCRIPTION_BYTES = 16_384
_PREVIEW_CHARS = 256


class WorkItemPullStore(Protocol):
    async def list_claimable_work_items(
        self, resource_id: str, *, work_type: str | None = None,
        limit: int = 20, offset: int = 0,
    ) -> ReadyWorkPage: ...

    async def claim_work_item(
        self, resource_id: str, work_type: str | None = None,
        department: str | None = None, *, work_item_id: str | None = None,
        agent_pull: bool = False,
        prepare_claim: Callable[[WorkItem, Booking], None] | None = None,
    ) -> tuple[WorkItem, Booking] | None: ...


PullResourceResolver = Callable[
    [str, Literal["discover", "claim", "assign", "resume"], bool],
    BookableResource | None,
]


class _ResultBudgetError(ValueError):
    def __init__(self) -> None:
        super().__init__("work_pull_result_budget")


def _text(value: Any, *, nonempty: bool = False) -> str:
    if type(value) is not str or (nonempty and not value):
        raise ValueError("work_pull_projection_invalid")
    value.encode("utf-8", errors="strict")
    return value


def _omissions(
    model: type[WorkItem] | type[Booking], exposed: set[str], prefix: str,
) -> dict[str, str]:
    return {
        f"{prefix}.{field.name}": "not_exposed"
        for field in fields(model) if field.name not in exposed
    }


def _item_projection(item: WorkItem) -> dict[str, Any]:
    if type(item.id) is not str or not 1 <= len(item.id) <= 128:
        raise ValueError("work_pull_projection_invalid")
    title = _text(item.title)
    if type(item.priority) is not int:
        raise ValueError("work_pull_projection_invalid")
    return {
        "id": _text(item.id, nonempty=True),
        "title": title[:_PREVIEW_CHARS],
        "title_truncated": len(title) > _PREVIEW_CHARS,
        "work_type": _text(item.work_type, nonempty=True),
        "priority": item.priority,
    }


def _claim_projection(item: WorkItem, booking: Booking) -> dict[str, Any]:
    projected = _item_projection(item)
    description = _text(item.description)
    byte_count = len(description.encode("utf-8", errors="strict"))
    projected.update({
        "description": description if byte_count <= _DESCRIPTION_BYTES else None,
        "description_utf8_bytes": byte_count,
        "status": _text(item.status, nonempty=True),
        "assigned_to": _text(item.assigned_to, nonempty=True),
    })
    projected_booking = {
        "id": _text(booking.id, nonempty=True),
        "work_item_id": _text(booking.work_item_id, nonempty=True),
        "resource_id": _text(booking.resource_id, nonempty=True),
        "status": _text(booking.status, nonempty=True),
    }
    if (
        projected["id"] != projected_booking["work_item_id"]
        or projected["assigned_to"] != projected_booking["resource_id"]
    ):
        raise ValueError("work_pull_projection_invalid")
    omitted = {
        **_omissions(WorkItem, set(projected), "work_item"),
        **_omissions(Booking, set(projected_booking), "booking"),
    }
    if projected["description"] is None:
        omitted["work_item.description"] = "size_limit"
    return {
        "owned": True, "work_item": projected,
        "booking": projected_booking, "omitted_fields": omitted,
    }


def _render(
    presentation: ToolResultPresentation, value: dict[str, Any],
) -> str | None:
    rendered = presentation.render_complete(value)
    if rendered is not None and (type(rendered) is not str or not rendered):
        raise ValueError("work_pull_presentation_invalid")
    return rendered


class _WorkItemPullTool:
    def __init__(
        self, *, store: WorkItemPullStore, pull_resource_resolver: PullResourceResolver,
    ) -> None:
        if store is None or not callable(pull_resource_resolver):
            raise ValueError("work_pull_dependencies_required")
        self._store = store
        self._resolve_resource = pull_resource_resolver

    @property
    def tool_type(self) -> ToolType:
        return ToolType.INFRA_SERVICE

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "string",
            "description": (
                "Complete pre-rendered Python-literal object (not JSON). "
                "Discovery has items, next_offset and omitted_fields; claim has "
                "owned, work_item, booking and omitted_fields, or owned=False "
                "with reason=not_claimable. Omission reasons and original byte "
                "counts are part of the object, never silently elided."
            ),
        }

    @staticmethod
    def _presentation(context: dict[str, Any] | None) -> ToolResultPresentation:
        if type(context) is not dict:
            raise ValueError("work_pull_presentation_required")
        presentation = context.get("_tool_result_presentation")
        if type(presentation) is not ToolResultPresentation or not callable(presentation.render_complete):
            raise ValueError("work_pull_presentation_required")
        return presentation

    def _actor(
        self, context: dict[str, Any], action: Literal["discover", "claim"],
    ) -> str:
        if any(key in context for key in WORK_PULL_ROOM_CONTEXT_KEYS):
            raise PermissionError("work_pull_room_denied")
        actor = context.get("agent_id")
        if type(actor) is not str or not actor:
            raise PermissionError("work_pull_authority_denied")
        resource = self._resolve_resource(actor, action, True)
        if (
            resource is None or resource.resource_id != actor
            or resource.active is not True
        ):
            raise PermissionError("work_pull_authority_denied")
        return actor

    @staticmethod
    def _error(
        reason: str, presentation: ToolResultPresentation | None, started: float,
    ) -> ToolResult:
        logger.warning(
            "Work pull failed (%s); an ownership/discovery receipt is not "
            "returned; correct the refusal or use exact-ID replay after a fault",
            reason,
        )
        error = reason
        if presentation is not None:
            try:
                rendered = presentation.render_complete(reason)
                if type(rendered) is not str or rendered != reason:
                    error = "!"
            except Exception:
                error = "!"
        return ToolResult(
            error=error, duration_ms=(time.monotonic() - started) * 1000.0,
            metadata={"reason": reason},
        )


class DiscoverWorkItemsTool(_WorkItemPullTool):
    @property
    def tool_id(self) -> str:
        return "discover_work_items"

    @property
    def name(self) -> str:
        return "Discover Ready Work"

    @property
    def description(self) -> str:
        return (
            "Discover explicitly published standalone work that you may choose "
            "to own. This is an advisory snapshot, not an assignment. Select "
            "an exact returned id with claim_work_item. Follow next_offset even "
            "when items is empty; descriptions here are previews only. The "
            "result is a complete serialized Python-literal object."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "work_type": {"type": "string", "minLength": 1, "maxLength": 64},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "additionalProperties": False,
        }

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        started = time.monotonic()
        presentation = None
        try:
            presentation = self._presentation(context)
            assert context is not None
            if type(params) is not dict or refuse_undeclared_params(self, params) is not None:
                raise ValueError("work_pull_parameters_invalid")
            work_type = params.get("work_type")
            limit, offset = params.get("limit", 20), params.get("offset", 0)
            if (
                ("work_type" in params and (
                    type(work_type) is not str or not 1 <= len(work_type) <= 64
                ))
                or type(limit) is not int or not 1 <= limit <= 50
                or type(offset) is not int or offset < 0
            ):
                raise ValueError("work_pull_parameters_invalid")
            actor = self._actor(context, "discover")
            page = await self._store.list_claimable_work_items(
                actor, work_type=work_type, limit=limit, offset=offset,
            )
            if (
                len(page.item_offsets) != len(page.items)
                or any(type(value) is not int or value < offset for value in page.item_offsets)
                or tuple(sorted(set(page.item_offsets))) != page.item_offsets
            ):
                raise ValueError("work_pull_projection_invalid")
            items: list[dict[str, Any]] = []
            for item in page.items:
                projected = _item_projection(item)
                description = _text(item.description)
                projected.update({
                    "description_preview": description[:_PREVIEW_CHARS],
                    "description_truncated": len(description) > _PREVIEW_CHARS,
                    "description_utf8_bytes": len(description.encode("utf-8", errors="strict")),
                })
                items.append(projected)
            omitted = _omissions(
                WorkItem, {"id", "title", "description", "work_type", "priority"}, "items[]",
            )
            omitted["items[].description"] = "preview_only"
            value = {"items": items, "next_offset": page.next_offset, "omitted_fields": omitted}
            rendered = _render(presentation, value)
            if rendered is None and items:
                omitted["items"] = "result_budget"
                for count in range(len(items) - 1, 0, -1):
                    value = {
                        "items": items[:count], "next_offset": page.item_offsets[count],
                        "omitted_fields": omitted,
                    }
                    rendered = _render(presentation, value)
                    if rendered is not None:
                        break
            if rendered is None:
                raise _ResultBudgetError()
            return ToolResult(output=rendered, duration_ms=(time.monotonic() - started) * 1000.0)
        except _ResultBudgetError:
            return self._error("work_pull_result_budget", presentation, started)
        except PermissionError:
            return self._error("work_pull_authority_denied", presentation, started)
        except (ValueError, UnicodeError):
            return self._error("work_pull_input_or_projection_invalid", presentation, started)
        except Exception:
            return self._error("work_pull_discovery_failed", presentation, started)


class ClaimWorkItemTool(_WorkItemPullTool):
    @property
    def tool_id(self) -> str:
        return "claim_work_item"

    @property
    def name(self) -> str:
        return "Claim Selected Work"

    @property
    def description(self) -> str:
        return (
            "Claim exactly one published standalone work item you selected. "
            "Supply its complete id, never a prefix. owned=True confirms "
            "persisted ownership or same-owner replay, not execution or resume. "
            "Read status and description omission reasons before acting. Full "
            "instructions are included only within 16384 UTF-8 bytes and this "
            "invocation's result budget; otherwise description is None with "
            "the original byte count and an explicit reason. The result is a "
            "complete serialized Python-literal object."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "work_item_id": {"type": "string", "minLength": 1, "maxLength": 128},
            },
            "required": ["work_item_id"],
            "additionalProperties": False,
        }

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        started = time.monotonic()
        presentation = None
        try:
            presentation = self._presentation(context)
            assert context is not None
            if type(params) is not dict or refuse_undeclared_params(self, params) is not None:
                raise ValueError("work_pull_parameters_invalid")
            wanted = params.get("work_item_id")
            if type(wanted) is not str or not 1 <= len(wanted) <= 128:
                raise ValueError("work_pull_parameters_invalid")
            actor = self._actor(context, "claim")
            prepared: ToolResult | None = None

            def prepare(item: WorkItem, booking: Booking) -> None:
                nonlocal prepared
                if item.id != wanted or item.assigned_to != actor or booking.resource_id != actor:
                    raise ValueError("work_pull_projection_invalid")
                value = _claim_projection(item, booking)
                rendered = _render(presentation, value)
                if rendered is None and value["work_item"]["description"] is not None:
                    value["work_item"]["description"] = None
                    value["omitted_fields"]["work_item.description"] = "result_budget"
                    rendered = _render(presentation, value)
                if rendered is None:
                    raise _ResultBudgetError()
                prepared = ToolResult(output=rendered)

            result = await self._store.claim_work_item(
                actor, work_item_id=wanted, agent_pull=True, prepare_claim=prepare,
            )
            if result is None:
                rendered = _render(presentation, {"owned": False, "reason": "not_claimable"})
                if rendered is None:
                    raise _ResultBudgetError()
                return ToolResult(
                    output=rendered, duration_ms=(time.monotonic() - started) * 1000.0,
                )
            if prepared is None:
                raise RuntimeError("work_pull_preparation_missing")
            return replace(prepared, duration_ms=(time.monotonic() - started) * 1000.0)
        except _ResultBudgetError:
            return self._error("work_pull_result_budget", presentation, started)
        except PermissionError:
            return self._error("work_pull_authority_denied", presentation, started)
        except (ValueError, UnicodeError):
            return self._error("work_pull_input_or_projection_invalid", presentation, started)
        except Exception:
            return self._error("work_pull_claim_failed", presentation, started)
