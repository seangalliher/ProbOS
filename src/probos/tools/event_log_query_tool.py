"""Governed, bounded EventLog query tool (AD-1129)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from probos.protocols import (
    CooperationSignatureAggregate,
    EventLogAggregateKind,
    EventLogJsonValue,
    EventLogQueryAudit,
    EventLogQueryAuditSink,
    EventLogQueryBatch,
    EventLogQueryRow,
    EventLogQuerySpec,
    EventLogReaderProtocol,
)
from probos.tools.protocol import (
    ToolPermission,
    ToolResult,
    ToolType,
    permission_includes,
)

logger = logging.getLogger(__name__)

_ALLOWED_DEPARTMENTS = frozenset({"engineering", "science", "security"})
_ALLOWED_RANKS = frozenset(
    {"ensign", "lieutenant", "commander", "senior_officer"}
)
_ALLOWED_KEYS = frozenset(
    {
        "start_time",
        "end_time",
        "category",
        "event",
        "correlation_id",
        "agent_id",
        "limit",
        "order",
        "aggregate",
    }
)
_FILTER_FIELDS = (
    ("category", 128),
    ("event", 128),
    ("correlation_id", 256),
    ("agent_id", 256),
)
# AD-1179: the ``order`` and ``aggregate`` vocabularies, declared ONCE.
#
# ``order`` was restated twice (input schema, output schema) and ``aggregate``
# three times (input schema, ``_parse_query``'s gate, ``_raw_audit_details``'s
# gate). Every restatement beside an executable gate is a place the two can
# drift, which is the BF-701 defect class this AD exists to close.
#
# Ordered tuples, never sets: per-process string-hash randomisation would
# reorder a set-derived enum on every boot.
_ORDERS: tuple[str, ...] = ("newest_first", "oldest_first")
_AGGREGATIONS: tuple[str, ...] = ("none", "cooperation_signature")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_MAX_WINDOW_SECONDS = 7 * 24 * 60 * 60
_MAX_OUTPUT_BYTES = 65_536


class _InvalidRequest(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _ParsedQuery:
    spec: EventLogQuerySpec
    parameter_names: tuple[str, ...]
    window_seconds: int


def _parse_rfc3339(value: object, field: str) -> datetime:
    if type(value) is not str or not value or len(value) > 64:
        raise _InvalidRequest(field)
    if _RFC3339_RE.fullmatch(value) is None:
        raise _InvalidRequest(field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _InvalidRequest(field) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _InvalidRequest(field)
    return parsed.astimezone(timezone.utc)


def _parameter_names(params: object, limit: int) -> tuple[str, ...]:
    if type(params) is not dict:
        return ()
    names: list[str] = []
    for index, key in enumerate(params):
        if index >= limit:
            break
        if type(key) is str:
            names.append(key[:64])
    return tuple(sorted(names))


def _parse_query(params: object) -> _ParsedQuery:
    if type(params) is not dict:
        raise _InvalidRequest("params_type")
    if len(params) > 9:
        raise _InvalidRequest("too_many_parameters")
    parameter_names: list[str] = []
    for key in params:
        if type(key) is not str:
            raise _InvalidRequest("parameter_name")
        parameter_names.append(key[:64])
        if key not in _ALLOWED_KEYS:
            raise _InvalidRequest("unknown_parameter")
    if "start_time" not in params or "end_time" not in params:
        raise _InvalidRequest("time_required")
    start_time = _parse_rfc3339(params["start_time"], "start_time")
    end_time = _parse_rfc3339(params["end_time"], "end_time")
    if start_time >= end_time:
        raise _InvalidRequest("time_order")
    window_seconds = (end_time - start_time).total_seconds()
    if window_seconds > _MAX_WINDOW_SECONDS:
        raise _InvalidRequest("window")

    filters: dict[str, str | None] = {}
    for name, cap in _FILTER_FIELDS:
        if name not in params:
            filters[name] = None
            continue
        value = params[name]
        if type(value) is not str or not value or len(value) > cap:
            raise _InvalidRequest(name)
        filters[name] = value
    if not any(value is not None for value in filters.values()):
        raise _InvalidRequest("filter_required")

    limit = params.get("limit", 50)
    if type(limit) is not int or not 1 <= limit <= 200:
        raise _InvalidRequest("limit")
    order = params.get("order", "newest_first")
    if type(order) is not str or order not in _ORDERS:
        raise _InvalidRequest("order")
    aggregate = params.get("aggregate", "none")
    if type(aggregate) is not str or aggregate not in _AGGREGATIONS:
        raise _InvalidRequest("aggregate")
    if aggregate == "cooperation_signature" and (
        filters["category"] != "emergent"
        or filters["event"] != "cooperation_cluster"
    ):
        raise _InvalidRequest("aggregate_filters")

    return _ParsedQuery(
        spec=EventLogQuerySpec(
            start_time=start_time,
            end_time=end_time,
            category=filters["category"],
            event=filters["event"],
            correlation_id=filters["correlation_id"],
            agent_id=filters["agent_id"],
            limit=limit,
            order=order,
            aggregate=aggregate,
        ),
        parameter_names=tuple(sorted(parameter_names)),
        window_seconds=int(window_seconds),
    )


def _raw_audit_details(
    params: object,
) -> tuple[tuple[str, ...], int | None, EventLogAggregateKind]:
    names = _parameter_names(params, 10)
    aggregate: EventLogAggregateKind = "none"
    if type(params) is dict:
        raw_aggregate = params.get("aggregate")
        if type(raw_aggregate) is str and raw_aggregate in _AGGREGATIONS:
            aggregate = raw_aggregate
        try:
            start_time = _parse_rfc3339(params.get("start_time"), "start_time")
            end_time = _parse_rfc3339(params.get("end_time"), "end_time")
            seconds = (end_time - start_time).total_seconds()
            if start_time < end_time and seconds <= _MAX_WINDOW_SECONDS:
                return names, int(seconds), aggregate
        except _InvalidRequest:
            pass
    return names, None, aggregate


def _wire_json(value: EventLogJsonValue) -> object:
    if type(value) is tuple:
        return [_wire_json(item) for item in value]
    if type(value) is dict:
        return {key: _wire_json(item) for key, item in value.items()}
    return value


def _row_to_output(row: EventLogQueryRow) -> dict[str, object]:
    return {
        "id": row.id,
        "timestamp": row.timestamp.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "category": row.category,
        "event": row.event,
        "agent_id": row.agent_id,
        "agent_type": row.agent_type,
        "pool": row.pool,
        "detail": row.detail,
        "correlation_id": row.correlation_id,
        "parent_event_id": row.parent_event_id,
        "data": _wire_json(row.data),
    }


def _aggregate_to_output(
    aggregate: CooperationSignatureAggregate | None,
) -> dict[str, object] | None:
    if aggregate is None:
        return None
    return {
        "kind": aggregate.kind,
        "total_rows": aggregate.total_rows,
        "valid_signature_rows": aggregate.valid_signature_rows,
        "groups": [
            {
                "intents": list(group.intents),
                "avg_weight": group.avg_weight,
                "count": group.count,
            }
            for group in aggregate.groups
        ],
        "truncated": aggregate.truncated,
    }


def _output_fits(envelope: dict[str, object]) -> bool:
    canonical_bytes = len(
        json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    live_bytes = len(str(envelope).encode("utf-8"))
    return canonical_bytes <= _MAX_OUTPUT_BYTES and live_bytes <= _MAX_OUTPUT_BYTES


def _build_output(
    parsed: _ParsedQuery,
    batch: EventLogQueryBatch,
) -> dict[str, object]:
    if type(batch) is not EventLogQueryBatch:
        raise ValueError("invalid EventLog query batch")
    aggregate = _aggregate_to_output(batch.aggregate)
    source_groups: list[dict[str, object]] = []
    if aggregate is not None:
        raw_groups = aggregate["groups"]
        if type(raw_groups) is not list:
            raise ValueError("invalid EventLog aggregate groups")
        source_groups = raw_groups
        aggregate = {
            **aggregate,
            "groups": [],
            "truncated": True,
        }
    envelope: dict[str, object] = {
        "status": "ok",
        "window": {
            "start_time": parsed.spec.start_time.isoformat().replace(
                "+00:00", "Z"
            ),
            "end_time": parsed.spec.end_time.isoformat().replace("+00:00", "Z"),
        },
        "order": parsed.spec.order,
        "matched_count": batch.matched_count,
        "returned_count": 0,
        "scanned_count": batch.scanned_count,
        "truncated": batch.truncated or bool(source_groups),
        "rows": [],
        "aggregate": aggregate,
    }
    if not _output_fits(envelope):
        raise ValueError("EventLog query metadata exceeds output limit")
    if parsed.spec.aggregate != "none":
        if aggregate is None:
            raise ValueError("EventLog aggregate result is missing")
        groups = aggregate["groups"]
        if type(groups) is not list:
            raise ValueError("invalid EventLog aggregate output groups")
        for group in source_groups:
            candidate_aggregate = {**aggregate, "groups": [*groups, group]}
            candidate = {**envelope, "aggregate": candidate_aggregate}
            if not _output_fits(candidate):
                break
            groups.append(group)
        omitted_groups = len(groups) < len(source_groups)
        aggregate["truncated"] = bool(
            batch.aggregate is not None
            and (batch.aggregate.truncated or omitted_groups)
        )
        envelope["truncated"] = batch.truncated or omitted_groups
        if not _output_fits(envelope):
            while groups and not _output_fits(envelope):
                groups.pop()
                aggregate["truncated"] = True
                envelope["truncated"] = True
        if not _output_fits(envelope):
            raise ValueError("EventLog query aggregate exceeds output limit")
        return envelope

    rows: list[dict[str, object]] = []
    envelope["rows"] = rows
    for row in batch.rows:
        if type(row) is not EventLogQueryRow:
            raise ValueError("invalid EventLog query row")
        projected = _row_to_output(row)
        candidate = dict(envelope)
        candidate["rows"] = [*rows, projected]
        candidate["returned_count"] = len(rows) + 1
        if not _output_fits(candidate):
            envelope["truncated"] = True
            break
        rows.append(projected)
        envelope["returned_count"] = len(rows)
    if len(rows) < len(batch.rows):
        envelope["truncated"] = True
    if not _output_fits(envelope):
        raise ValueError("EventLog query output exceeds output limit")
    return envelope


class EventLogQueryTool:
    """Read-only governed EventLog query surface for authorized agents."""

    def __init__(
        self,
        *,
        reader: EventLogReaderProtocol,
        audit_sink: EventLogQueryAuditSink,
    ) -> None:
        self._reader = reader
        self._audit_sink = audit_sink

    @property
    def tool_id(self) -> str:
        return "event_log_query"

    @property
    def name(self) -> str:
        return "Event Log Query"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return (
            "Query a bounded, redacted EventLog window using fixed filters or "
            "the fixed cooperation-signature aggregate."
        )

    @property
    def input_schema(self) -> dict[str, object]:
        filter_schema = {"type": "string", "minLength": 1}
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["start_time", "end_time"],
            "properties": {
                "start_time": {"type": "string", "maxLength": 64},
                "end_time": {"type": "string", "maxLength": 64},
                "category": {**filter_schema, "maxLength": 128},
                "event": {**filter_schema, "maxLength": 128},
                "correlation_id": {**filter_schema, "maxLength": 256},
                "agent_id": {**filter_schema, "maxLength": 256},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
                "order": {
                    "type": "string",
                    "enum": list(_ORDERS),
                    "default": "newest_first",
                },
                "aggregate": {
                    "type": "string",
                    "enum": list(_AGGREGATIONS),
                    "default": "none",
                },
            },
        }

    @property
    def output_schema(self) -> dict[str, object]:
        nullable_string = {"type": ["string", "null"]}
        row_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "timestamp",
                "category",
                "event",
                "agent_id",
                "agent_type",
                "pool",
                "detail",
                "correlation_id",
                "parent_event_id",
                "data",
            ],
            "properties": {
                "id": {"type": "integer"},
                "timestamp": {"type": "string"},
                "category": {"type": "string"},
                "event": {"type": "string"},
                "agent_id": nullable_string,
                "agent_type": nullable_string,
                "pool": nullable_string,
                "detail": nullable_string,
                "correlation_id": nullable_string,
                "parent_event_id": {"type": ["integer", "null"]},
                "data": {},
            },
        }
        aggregate_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "kind",
                "total_rows",
                "valid_signature_rows",
                "groups",
                "truncated",
            ],
            "properties": {
                "kind": {"const": "cooperation_signature"},
                "total_rows": {"type": "integer"},
                "valid_signature_rows": {"type": "integer"},
                "groups": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["intents", "avg_weight", "count"],
                        "properties": {
                            "intents": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "avg_weight": {"type": "number"},
                            "count": {"type": "integer"},
                        },
                    },
                },
                "truncated": {"type": "boolean"},
            },
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status",
                "window",
                "order",
                "matched_count",
                "returned_count",
                "scanned_count",
                "truncated",
                "rows",
                "aggregate",
            ],
            "properties": {
                "status": {"const": "ok"},
                "window": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["start_time", "end_time"],
                    "properties": {
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                    },
                },
                "order": {
                    "type": "string",
                    "enum": list(_ORDERS),
                },
                "matched_count": {"type": "integer"},
                "returned_count": {"type": "integer"},
                "scanned_count": {"type": "integer"},
                "truncated": {"type": "boolean"},
                "rows": {
                    "type": "array",
                    "maxItems": 200,
                    "items": row_schema,
                },
                "aggregate": {
                    "oneOf": [aggregate_schema, {"type": "null"}],
                },
            },
        }

    async def invoke(
        self,
        params: dict[str, object],
        context: dict[str, object] | None = None,
    ) -> ToolResult:
        actor_id, department, rank, held = self._authorization_context(context)
        if (
            department not in _ALLOWED_DEPARTMENTS
            or rank not in _ALLOWED_RANKS
            or held is None
            or not permission_includes(held, ToolPermission.READ)
        ):
            await self._best_effort_audit(
                EventLogQueryAudit(
                    actor_id=actor_id,
                    department=department,
                    rank=rank,
                    outcome="denied",
                    parameter_names=_parameter_names(params, 10),
                    window_seconds=None,
                    aggregate="none",
                    matched_count=0,
                    returned_count=0,
                    truncated=False,
                ),
                log_failure=True,
            )
            return ToolResult(error="event_log_query_denied")

        try:
            parsed = _parse_query(params)
        except _InvalidRequest as exc:
            names, window_seconds, aggregate = _raw_audit_details(params)
            await self._best_effort_audit(
                EventLogQueryAudit(
                    actor_id=actor_id,
                    department=department,
                    rank=rank,
                    outcome="invalid",
                    parameter_names=names,
                    window_seconds=window_seconds,
                    aggregate=aggregate,
                    matched_count=0,
                    returned_count=0,
                    truncated=False,
                ),
                log_failure=True,
            )
            return ToolResult(error=f"event_log_query_invalid:{exc.code}")

        try:
            batch = await self._reader.query_governed(parsed.spec)
            if not batch.available:
                return ToolResult(error="event_log_query_unavailable")
            output = _build_output(parsed, batch)
        except Exception:
            logger.warning(
                "Governed EventLog query failed before return; suppressing all "
                "rows and returning the stable failure code"
            )
            await self._best_effort_audit(
                EventLogQueryAudit(
                    actor_id=actor_id,
                    department=department,
                    rank=rank,
                    outcome="failed",
                    parameter_names=parsed.parameter_names,
                    window_seconds=parsed.window_seconds,
                    aggregate=parsed.spec.aggregate,
                    matched_count=0,
                    returned_count=0,
                    truncated=False,
                ),
                log_failure=True,
            )
            return ToolResult(error="event_log_query_failed")

        audit = EventLogQueryAudit(
            actor_id=actor_id,
            department=department,
            rank=rank,
            outcome="success",
            parameter_names=parsed.parameter_names,
            window_seconds=parsed.window_seconds,
            aggregate=parsed.spec.aggregate,
            matched_count=batch.matched_count,
            returned_count=int(output["returned_count"]),
            truncated=bool(output["truncated"]),
        )
        try:
            if await self._audit_sink.audit_governed_query(audit) is not True:
                raise RuntimeError("governance audit did not commit")
        except Exception:
            logger.warning(
                "Governed EventLog success audit failed; suppressing all rows "
                "and returning the stable failure code"
            )
            return ToolResult(error="event_log_query_failed")
        return ToolResult(output=output)

    async def audit_denied_invocation(
        self,
        *,
        actor_id: str,
        department: str,
        rank: str,
        required: ToolPermission,
        held: ToolPermission,
        parameter_names: tuple[str, ...],
    ) -> None:
        audit = EventLogQueryAudit(
            actor_id=actor_id,
            department=department,
            rank=rank,
            outcome="denied",
            parameter_names=tuple(sorted(parameter_names[:10])),
            window_seconds=None,
            aggregate="none",
            matched_count=0,
            returned_count=0,
            truncated=False,
        )
        if await self._audit_sink.audit_governed_query(audit) is not True:
            raise RuntimeError(
                "governance denial audit did not commit for required="
                f"{required.value} held={held.value}"
            )

    @staticmethod
    def _authorization_context(
        context: object,
    ) -> tuple[str, str, str, ToolPermission | None]:
        if type(context) is not dict:
            return "", "", "", None
        actor_id = context.get("agent_id")
        department = context.get("agent_department")
        rank = context.get("agent_rank")
        permission = context.get("permission")
        actor = actor_id if type(actor_id) is str else ""
        department_value = department if type(department) is str else ""
        rank_value = rank if type(rank) is str else ""
        if type(permission) is not str:
            return actor, department_value, rank_value, None
        try:
            held = ToolPermission(permission)
        except ValueError:
            held = None
        return actor, department_value, rank_value, held

    async def _best_effort_audit(
        self,
        audit: EventLogQueryAudit,
        *,
        log_failure: bool,
    ) -> None:
        try:
            committed = await self._audit_sink.audit_governed_query(audit)
            if committed is not True and log_failure:
                logger.warning(
                    "Governed EventLog attempt audit was unavailable; preserving "
                    "the stable denied, invalid, or failed result"
                )
        except Exception:
            if log_failure:
                logger.warning(
                    "Governed EventLog attempt audit failed; preserving the "
                    "stable denied, invalid, or failed result"
                )