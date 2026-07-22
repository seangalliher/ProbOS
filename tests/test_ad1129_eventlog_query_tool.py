"""AD-1129 governed, bounded EventLog query Tool contracts."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest

import probos.substrate.event_log as event_log_module
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.engineering_officer import EngineeringAgent
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolCallResult,
    ToolUseBlock,
)
from probos.consensus.trust import TrustNetwork
from probos.protocols import (
    EventLogProtocol,
    EventLogQueryAudit,
    EventLogQueryAuditSink,
    EventLogQueryBatch,
    EventLogQuerySpec,
    EventLogReaderProtocol,
)
from probos.startup.communication import _register_event_log_query_tool
from probos.substrate.registry import AgentRegistry
from probos.substrate.event_log import EventLog
from probos.tools.event_log_query_tool import EventLogQueryTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from probos.types import LLMResponse


_START = datetime(2026, 7, 13, tzinfo=timezone.utc)
_END = datetime(2026, 7, 18, tzinfo=timezone.utc)
_ROW_KEYS = {
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
}
_AUTHORIZED_CONTEXT: dict[str, object] = {
    "agent_id": "laforge-1",
    "agent_department": "engineering",
    "agent_rank": "lieutenant",
    "agent_types": ["engineering_officer"],
    "permission": "read",
}


class _ControlledDateTime(datetime):
    current = _START

    @classmethod
    def now(cls, tz: timezone | None = None) -> datetime:
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


class _OrdinaryTool:
    @property
    def tool_id(self) -> str:
        return "ordinary_tool"

    @property
    def name(self) -> str:
        return "Ordinary Tool"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return "An unrelated Tool registration."

    @property
    def input_schema(self) -> dict[str, object]:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict[str, object]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, object],
        context: dict[str, object] | None = None,
    ) -> ToolResult:
        return ToolResult(output={"ok": True})


class _FailureAuditSink:
    def __init__(self) -> None:
        self.audits: list[EventLogQueryAudit] = []

    async def audit_governed_query(self, audit: EventLogQueryAudit) -> bool:
        self.audits.append(audit)
        return False


class _CancellationAuditSink:
    async def audit_governed_query(self, audit: EventLogQueryAudit) -> bool:
        raise asyncio.CancelledError


class _AvailableReader:
    async def query_governed(self, spec: EventLogQuerySpec) -> EventLogQueryBatch:
        return EventLogQueryBatch(
            available=True,
            rows=(),
            matched_count=0,
            scanned_count=0,
            truncated=False,
            aggregate=None,
        )


class _CountingReader(_AvailableReader):
    def __init__(self) -> None:
        self.specs: list[EventLogQuerySpec] = []

    async def query_governed(self, spec: EventLogQuerySpec) -> EventLogQueryBatch:
        self.specs.append(spec)
        return await super().query_governed(spec)


class _FailureReader:
    async def query_governed(self, spec: EventLogQuerySpec) -> EventLogQueryBatch:
        raise RuntimeError("database-password=must-not-leak")


class _CancellationReader:
    async def query_governed(self, spec: EventLogQuerySpec) -> EventLogQueryBatch:
        raise asyncio.CancelledError


class _AggregateScriptedLLM:
    def __init__(self, params: dict[str, object]) -> None:
        self._params = params
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: object) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMResponse(
                content="",
                tokens_used=3,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            name="event_log_query",
                            arguments=self._params,
                            id="event-log-call",
                        )
                    )
                ],
            )
        observed = (
            "'total_rows': 61" in request.prompt
            and "'valid_signature_rows': 61" in request.prompt
            and "'count': 49" in request.prompt
        )
        final_text = (
            "Observed 61 cooperation rows with a 49-row leading signature."
            if observed
            else "Aggregate evidence missing from the reasoning turn."
        )
        return LLMResponse(
            content=final_text,
            tokens_used=3,
            content_blocks=[TextBlock(text=final_text)],
        )


class _ToolScriptedLLM:
    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: object) -> LLMResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return LLMResponse(
                content="",
                tokens_used=1,
                content_blocks=[
                    ToolUseBlock(
                        tool_call=ToolCallRequest(
                            name=self._tool_id,
                            arguments={},
                            id="context-call",
                        )
                    )
                ],
            )
        return LLMResponse(
            content="complete",
            tokens_used=1,
            content_blocks=[TextBlock(text="complete")],
        )


class _NoCallLLM:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: object) -> LLMResponse:
        self.requests.append(request)
        raise AssertionError("identity failure must precede LLM execution")


class _ContextCaptureTool:
    def __init__(self) -> None:
        self.contexts: list[dict[str, Any]] = []

    @property
    def tool_id(self) -> str:
        return "context_capture"

    @property
    def name(self) -> str:
        return "Context Capture"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return "Capture the governed invocation context for a boundary test."

    @property
    def input_schema(self) -> dict[str, object]:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict[str, object]:
        return {"type": "object"}

    async def invoke(
        self,
        params: dict[str, object],
        context: dict[str, object] | None = None,
    ) -> ToolResult:
        self.contexts.append(dict(context or {}))
        return ToolResult(output={"captured": True})


class _RecordingEventLogQueryTool(EventLogQueryTool):
    def __init__(
        self,
        *,
        reader: EventLogReaderProtocol,
        audit_sink: EventLogQueryAuditSink,
    ) -> None:
        super().__init__(reader=reader, audit_sink=audit_sink)
        self.contexts: list[dict[str, Any]] = []

    async def invoke(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        self.contexts.append(dict(context or {}))
        return await super().invoke(params, context)


class _EngineeringOntology:
    def get_agent_department(self, agent_type: str) -> str | None:
        return "engineering" if agent_type == "engineering_officer" else None


class _FailingOntology:
    def get_agent_department(self, agent_type: str) -> str | None:
        raise RuntimeError("ontology internals must not leak")


class _FailingTrust:
    def get_score(self, agent_id: str) -> float:
        raise RuntimeError("trust internals must not leak")


class _MismatchedAgentRegistry:
    def __init__(self, agent: EngineeringAgent) -> None:
        self._agent = agent

    def get(self, agent_id: str) -> EngineeringAgent:
        return self._agent


@pytest.fixture
async def event_log(tmp_path: Path) -> AsyncIterator[EventLog]:
    log = EventLog(tmp_path / "events.db")
    await log.start()
    try:
        yield log
    finally:
        await log.stop()


async def _seed_records(
    event_log: EventLog,
    records: list[dict[str, object]],
) -> list[int]:
    original_datetime = event_log_module.datetime
    row_ids: list[int] = []
    event_log_module.datetime = _ControlledDateTime
    try:
        for record in records:
            timestamp = record["timestamp"]
            assert type(timestamp) is datetime
            _ControlledDateTime.current = timestamp
            raw_data = record.get("data")
            assert raw_data is None or type(raw_data) is dict
            row_id = await event_log.log(
                category=str(record.get("category", "test")),
                event=str(record.get("event", "event")),
                agent_id=(
                    str(record["agent_id"])
                    if record.get("agent_id") is not None
                    else None
                ),
                agent_type=(
                    str(record["agent_type"])
                    if record.get("agent_type") is not None
                    else None
                ),
                pool=(
                    str(record["pool"])
                    if record.get("pool") is not None
                    else None
                ),
                detail=(
                    str(record["detail"])
                    if record.get("detail") is not None
                    else None
                ),
                correlation_id=(
                    str(record["correlation_id"])
                    if record.get("correlation_id") is not None
                    else None
                ),
                data=raw_data,
            )
            assert type(row_id) is int
            row_ids.append(row_id)
    finally:
        event_log_module.datetime = original_datetime
    return row_ids


def _spec(
    *,
    category: str | None = "test",
    event: str | None = None,
    correlation_id: str | None = None,
    agent_id: str | None = None,
    limit: int = 50,
    order: str = "newest_first",
    aggregate: str = "none",
    start_time: datetime = _START,
    end_time: datetime = _END,
) -> EventLogQuerySpec:
    return EventLogQuerySpec(
        start_time=start_time,
        end_time=end_time,
        category=category,
        event=event,
        correlation_id=correlation_id,
        agent_id=agent_id,
        limit=limit,
        order=order,  # type: ignore[arg-type]
        aggregate=aggregate,  # type: ignore[arg-type]
    )


def _params(
    *,
    category: str = "test",
    event: str | None = None,
    correlation_id: str | None = None,
    agent_id: str | None = None,
    limit: int = 50,
    order: str = "newest_first",
    aggregate: str = "none",
    start_time: datetime = _START,
    end_time: datetime = _END,
) -> dict[str, object]:
    params: dict[str, object] = {
        "start_time": start_time.isoformat().replace("+00:00", "Z"),
        "end_time": end_time.isoformat().replace("+00:00", "Z"),
        "category": category,
        "limit": limit,
        "order": order,
        "aggregate": aggregate,
    }
    if event is not None:
        params["event"] = event
    if correlation_id is not None:
        params["correlation_id"] = correlation_id
    if agent_id is not None:
        params["agent_id"] = agent_id
    return params


def _registered_event_tool(
    event_log: EventLog,
    permission_store: ToolPermissionStore | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    if permission_store is not None:
        registry.set_permission_store(permission_store)
    _register_event_log_query_tool(
        tool_registry=registry,
        enabled=True,
        event_log_reader=event_log,
        event_log_audit_sink=event_log,
    )
    return registry


def _register_recording_event_tool(
    registry: ToolRegistry,
    tool: _RecordingEventLogQueryTool,
) -> None:
    registry.register(
        tool,
        provider="event_log",
        tags=["event_log_query", "event_log", "diagnostics", "read_only"],
        allowed_departments=("engineering", "science", "security"),
        default_permissions={
            "ensign": ToolPermission.NONE,
            "lieutenant": ToolPermission.READ,
            "commander": ToolPermission.READ,
            "senior_officer": ToolPermission.READ,
        },
    )


def _agentic_runtime(
    *,
    tool_registry: ToolRegistry,
    permission_store: ToolPermissionStore,
    identity_services: dict[str, object] | None = None,
) -> SimpleNamespace:
    values: dict[str, object] = {
        "tool_registry": tool_registry,
        "tool_permission_store": permission_store,
        "intent_bus": None,
        "intent_grant_store": None,
        "mcp_workbench": None,
        "cognitive_skill_catalog": None,
        "attachment_store": None,
        "emit_event": None,
        "config": SimpleNamespace(
            execution=SimpleNamespace(enabled=False),
            mcp=SimpleNamespace(agent_tools_enabled=False),
            agentic_tools=SimpleNamespace(
                tool_search_enabled=False,
                delegation_enabled=False,
            ),
        ),
    }
    if identity_services is not None:
        values.update(identity_services)
    return SimpleNamespace(**values)


async def _invoke_authorized(
    registry: ToolRegistry,
    params: dict[str, object],
    *,
    context: dict[str, object] | None = None,
) -> ToolResult:
    return await registry.check_and_invoke(
        "laforge-1",
        "event_log_query",
        params,
        agent_department="engineering",
        agent_rank="lieutenant",
        agent_types=["engineering_officer"],
        context=context,
    )


async def _seed_signature_fixture(event_log: EventLog) -> None:
    records: list[dict[str, object]] = []
    for index in range(61):
        if index < 49:
            intents = ["team_info", "introspect", "team_info"]
            avg_weight = 0.9954
        else:
            intents = ["read_page", "search_files"]
            avg_weight = 0.7512
        records.append(
            {
                "timestamp": _START + timedelta(minutes=index),
                "category": "emergent",
                "event": "cooperation_cluster",
                "data": {
                    "evidence": {
                        "intents": intents,
                        "avg_weight": avg_weight,
                    }
                },
            }
        )
    await _seed_records(event_log, records)


@pytest.mark.asyncio
async def test_query_governed_conjoins_filters_normalizes_utc_and_orders_ties(
    event_log: EventLog,
) -> None:
    exact = {
        "category": "emergent",
        "event": "cooperation_cluster",
        "correlation_id": "corr-1",
        "agent_id": "agent-1",
    }
    records = [
        {"timestamp": _START, **exact},
        {"timestamp": _START + timedelta(minutes=1), **exact},
        {"timestamp": _START + timedelta(minutes=1), **exact},
        {"timestamp": _START + timedelta(minutes=2), **exact, "agent_id": "other"},
        {"timestamp": _END, **exact},
    ]
    row_ids = await _seed_records(event_log, records)
    offset = timezone(timedelta(hours=-4))
    base = _spec(
        category="emergent",
        event="cooperation_cluster",
        correlation_id="corr-1",
        agent_id="agent-1",
        start_time=_START.astimezone(offset),
        end_time=_END.astimezone(offset),
    )

    oldest = await event_log.query_governed(
        EventLogQuerySpec(**{**base.__dict__, "order": "oldest_first"})
    )
    newest = await event_log.query_governed(base)
    empty = await event_log.query_governed(
        EventLogQuerySpec(**{**base.__dict__, "correlation_id": "absent"})
    )

    assert [row.id for row in oldest.rows] == row_ids[:3]
    assert [row.id for row in newest.rows] == list(reversed(row_ids[:3]))
    assert oldest.matched_count == oldest.scanned_count == 3
    assert all(row.timestamp.tzinfo == timezone.utc for row in oldest.rows)
    assert row_ids[4] not in {row.id for row in oldest.rows}
    assert empty.rows == ()
    assert empty.matched_count == empty.scanned_count == 0
    assert empty.truncated is False


@pytest.mark.asyncio
async def test_query_governed_normal_and_aggregate_use_201st_row_sentinel(
    event_log: EventLog,
) -> None:
    await _seed_records(
        event_log,
        [
            {
                "timestamp": _START + timedelta(seconds=index),
                "category": "emergent",
                "event": "cooperation_cluster",
                "data": {
                    "evidence": {
                        "intents": ["introspect", "team_info"],
                        "avg_weight": 0.995,
                    }
                },
            }
            for index in range(201)
        ],
    )
    normal_spec = _spec(
        category="emergent",
        event="cooperation_cluster",
        limit=200,
        order="oldest_first",
    )
    aggregate_spec = EventLogQuerySpec(
        **{**normal_spec.__dict__, "aggregate": "cooperation_signature"}
    )

    normal = await event_log.query_governed(normal_spec)
    aggregate = await event_log.query_governed(aggregate_spec)

    assert len(normal.rows) == normal.matched_count == 200
    assert normal.scanned_count == 201
    assert normal.truncated is True
    assert aggregate.rows == ()
    assert aggregate.matched_count == 200
    assert aggregate.scanned_count == 201
    assert aggregate.truncated is True
    assert aggregate.aggregate is not None
    assert aggregate.aggregate.total_rows == 200
    assert aggregate.aggregate.valid_signature_rows == 200
    assert aggregate.aggregate.truncated is True


@pytest.mark.asyncio
async def test_tool_projects_exact_rows_redacts_and_caps_raw_and_serialized_data(
    event_log: EventLog,
) -> None:
    await _seed_records(
        event_log,
        [
            {
                "timestamp": _START + timedelta(minutes=1),
                "category": "diagnostic",
                "event": "sensitive",
                "agent_id": "laforge@example.com",
                "agent_type": "engineering_officer",
                "pool": "engineering",
                "detail": "captain@example.com " + "d" * 1000,
                "correlation_id": "corr-sensitive",
                "data": {
                    "nested": {
                        "email": "crew@example.com",
                        "phone": "425-555-0199",
                        "url": "https://example.test/private",
                        "authorization": "Bearer query-secret",
                        "password": {"never": "traverse-this"},
                    },
                    "long": "x" * 600,
                    "non_finite": float("nan"),
                    "huge_integer": 2**80,
                },
            },
            {
                "timestamp": _START + timedelta(minutes=2),
                "category": "diagnostic",
                "event": "raw_data_cap",
                "data": {"blob": "z" * 20_000},
            },
            {
                "timestamp": _START + timedelta(minutes=3),
                "category": "diagnostic",
                "event": "row_cap",
                "data": {f"key-{index}": "v" * 200 for index in range(32)},
            },
        ],
    )
    registry = _registered_event_tool(event_log)

    result = await _invoke_authorized(
        registry,
        _params(category="diagnostic", order="oldest_first"),
    )

    assert result.error is None
    output = result.output
    assert type(output) is dict
    assert output["aggregate"] is None
    assert output["returned_count"] == 3
    rows = output["rows"]
    assert type(rows) is list
    assert all(set(row) == _ROW_KEYS for row in rows)
    by_event = {row["event"]: row for row in rows}
    sensitive = by_event["sensitive"]
    assert sensitive["agent_id"] == "***@***.***"
    assert "captain@example.com" not in str(sensitive["detail"])
    assert len(sensitive["detail"]) <= 512
    nested = sensitive["data"]["nested"]
    assert nested["email"] == "***@***.***"
    assert nested["phone"] == "***-***-****"
    assert nested["url"] == "[REDACTED_URL]"
    assert nested["authorization"] == "[REDACTED]"
    assert nested["password"] == "[REDACTED]"
    assert "traverse-this" not in json.dumps(sensitive, sort_keys=True)
    assert sensitive["data"]["long"].endswith("[TRUNCATED]")
    assert sensitive["data"]["non_finite"] == {"_truncated": True}
    assert sensitive["data"]["huge_integer"] == {"_truncated": True}
    assert by_event["raw_data_cap"]["data"] == {"_truncated": True}
    assert by_event["row_cap"]["data"] == {"_truncated": True}
    assert all(
        len(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        <= 4_096
        for row in rows
    )
    assert output["truncated"] is True


def test_json_detacher_rejects_hostile_subclasses_and_non_json_values() -> None:
    from probos.substrate.event_log import _detach_json_value

    class _HostileDict(dict):
        def items(self) -> Any:
            raise AssertionError("hostile dict must not be traversed")

    class _HostileList(list):
        def __iter__(self) -> Any:
            raise AssertionError("hostile list must not be traversed")

    for value in (_HostileDict(), _HostileList(), object(), float("inf"), 2**80):
        detached, truncated = _detach_json_value(value)
        assert detached == {"_truncated": True}
        assert truncated is True

    detached, truncated = _detach_json_value(
        {"level1": {"level2": {"level3": {"level4": {"secret": "x"}}}}}
    )
    assert truncated is True
    assert "secret" not in str(detached)


@pytest.mark.asyncio
async def test_tool_enforces_canonical_and_agentic_live_output_byte_caps(
    event_log: EventLog,
) -> None:
    payload = {f"field-{index:02d}": "x" * 80 for index in range(32)}
    await _seed_records(
        event_log,
        [
            {
                "timestamp": _START + timedelta(minutes=index),
                "category": "byte_cap",
                "event": f"row-{index:02d}",
                "data": payload,
            }
            for index in range(30)
        ],
    )
    result = await _invoke_authorized(
        _registered_event_tool(event_log),
        _params(category="byte_cap", limit=30, order="oldest_first"),
    )

    assert result.error is None
    output = result.output
    canonical_size = len(
        json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    live_result = ToolCallResult.from_tool_result("tool-call", result, 0.0)
    assert canonical_size <= 65_536
    assert len(live_result.output.encode("utf-8")) <= 65_536
    assert live_result.output == str(output)
    assert output["matched_count"] == 30
    assert 0 < output["returned_count"] < output["matched_count"]
    assert output["truncated"] is True


@pytest.mark.asyncio
async def test_public_adapter_reproduces_exact_61_49_cooperation_signature(
    event_log: EventLog,
) -> None:
    await _seed_signature_fixture(event_log)

    batch = await event_log.query_governed(
        _spec(
            category="emergent",
            event="cooperation_cluster",
            limit=200,
            order="oldest_first",
            aggregate="cooperation_signature",
        )
    )

    assert batch.rows == ()
    assert batch.matched_count == batch.scanned_count == 61
    assert batch.truncated is False
    assert batch.aggregate is not None
    assert batch.aggregate.total_rows == 61
    assert batch.aggregate.valid_signature_rows == 61
    assert batch.aggregate.truncated is False
    assert batch.aggregate.groups[0].intents == ("introspect", "team_info")
    assert batch.aggregate.groups[0].avg_weight == 0.995
    assert batch.aggregate.groups[0].count == 49


@pytest.mark.asyncio
async def test_aggregate_output_trims_groups_to_both_final_byte_caps(
    event_log: EventLog,
) -> None:
    await _seed_records(
        event_log,
        [
            {
                "timestamp": _START + timedelta(minutes=group_index),
                "category": "emergent",
                "event": "cooperation_cluster",
                "data": {
                    "evidence": {
                        "intents": [
                            f"g{group_index:02d}-i{intent_index:02d}-" + "x" * 430
                            for intent_index in range(24)
                        ],
                        "avg_weight": group_index / 10,
                    }
                },
            }
            for group_index in range(10)
        ],
    )
    result = await _invoke_authorized(
        _registered_event_tool(event_log),
        _params(
            category="emergent",
            event="cooperation_cluster",
            limit=200,
            aggregate="cooperation_signature",
        ),
    )

    assert result.error is None
    output = result.output
    aggregate = output["aggregate"]
    assert output["returned_count"] == 0
    assert output["rows"] == []
    assert aggregate["valid_signature_rows"] == 10
    assert 0 < len(aggregate["groups"]) < 10
    assert aggregate["truncated"] is True
    assert output["truncated"] is True
    assert len(
        json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ) <= 65_536
    assert len(str(output).encode("utf-8")) <= 65_536


@pytest.mark.asyncio
async def test_public_adapter_caps_aggregate_to_ten_ordered_groups(
    event_log: EventLog,
) -> None:
    await _seed_records(
        event_log,
        [
            {
                "timestamp": _START + timedelta(minutes=index),
                "category": "emergent",
                "event": "cooperation_cluster",
                "data": {
                    "evidence": {
                        "intents": [f"intent-{index:02d}"],
                        "avg_weight": index / 100,
                    }
                },
            }
            for index in range(12)
        ],
    )

    batch = await event_log.query_governed(
        _spec(
            category="emergent",
            event="cooperation_cluster",
            limit=200,
            aggregate="cooperation_signature",
        )
    )

    assert batch.aggregate is not None
    assert batch.aggregate.total_rows == 12
    assert batch.aggregate.valid_signature_rows == 12
    assert len(batch.aggregate.groups) == 10
    assert [group.intents for group in batch.aggregate.groups] == [
        (f"intent-{index:02d}",) for index in range(10)
    ]
    assert batch.aggregate.truncated is True
    assert batch.truncated is True


@pytest.mark.asyncio
async def test_aggregate_rejects_bool_weight_and_malformed_signature_rows(
    event_log: EventLog,
) -> None:
    await _seed_records(
        event_log,
        [
            {
                "timestamp": _START + timedelta(minutes=index),
                "category": "emergent",
                "event": "cooperation_cluster",
                "data": data,
            }
            for index, data in enumerate(
                [
                    {
                        "evidence": {
                            "intents": ["introspect", "team_info"],
                            "avg_weight": 0.995,
                        }
                    },
                    {
                        "evidence": {
                            "intents": ["introspect", "team_info"],
                            "avg_weight": True,
                        }
                    },
                    {
                        "evidence": {
                            "intents": ["introspect", 7],
                            "avg_weight": 0.995,
                        }
                    },
                    {"evidence": {"intents": [], "avg_weight": 0.995}},
                    {"evidence": "not-an-object"},
                ]
            )
        ],
    )

    batch = await event_log.query_governed(
        _spec(
            category="emergent",
            event="cooperation_cluster",
            limit=200,
            aggregate="cooperation_signature",
        )
    )

    assert batch.aggregate is not None
    assert batch.aggregate.total_rows == 5
    assert batch.aggregate.valid_signature_rows == 1
    assert len(batch.aggregate.groups) == 1
    assert batch.aggregate.groups[0].count == 1


@pytest.mark.asyncio
async def test_tool_rejects_complete_invalid_input_matrix_with_stable_codes(
    event_log: EventLog,
) -> None:
    tool = EventLogQueryTool(reader=event_log, audit_sink=event_log)
    valid = _params(category="private-filter-value")

    class _ParamsSubclass(dict):
        pass

    cases: list[tuple[object, str]] = [
        ({}, "time_required"),
        ({"start_time": valid["start_time"]}, "time_required"),
        (
            {
                "start_time": valid["start_time"],
                "end_time": valid["end_time"],
            },
            "filter_required",
        ),
        ({**valid, "category": None}, "category"),
        ({**valid, "category": ""}, "category"),
        ({**valid, "unknown": "forbidden-value"}, "unknown_parameter"),
        ({**valid, 7: "forbidden-value"}, "parameter_name"),
        (
            {
                "start_time": valid["start_time"],
                "end_time": valid["end_time"],
                "category": "test",
                **{f"unknown-{index}": index for index in range(7)},
            },
            "too_many_parameters",
        ),
        ({**valid, "limit": True}, "limit"),
        ({**valid, "limit": -1}, "limit"),
        ({**valid, "limit": 0}, "limit"),
        ({**valid, "limit": 201}, "limit"),
        ({**valid, "limit": 10**100}, "limit"),
        ({**valid, "start_time": "2026-07-13T00:00:00"}, "start_time"),
        ({**valid, "start_time": "not-a-time"}, "start_time"),
        ({**valid, "start_time": valid["end_time"]}, "time_order"),
        (
            {
                **valid,
                "start_time": "2026-07-19T00:00:00Z",
                "end_time": "2026-07-18T00:00:00Z",
            },
            "time_order",
        ),
        (
            {
                **valid,
                "start_time": "2026-07-01T00:00:00Z",
                "end_time": "2026-07-09T00:00:00Z",
            },
            "window",
        ),
        ({**valid, "order": None}, "order"),
        ({**valid, "order": "sideways"}, "order"),
        ({**valid, "aggregate": None}, "aggregate"),
        (
            {**valid, "aggregate": "cooperation_signature"},
            "aggregate_filters",
        ),
        (_ParamsSubclass(valid), "params_type"),
        ([], "params_type"),
    ]

    for params, code in cases:
        result = await tool.invoke(  # type: ignore[arg-type]
            params,
            dict(_AUTHORIZED_CONTEXT),
        )
        assert result.output is None
        assert result.error == f"event_log_query_invalid:{code}"

    audits = await event_log.query_structured(
        category="audit",
        event="event_log_query",
        limit=100,
    )
    assert len(audits) == len(cases)
    serialized = json.dumps(audits, sort_keys=True)
    assert "forbidden-value" not in serialized
    assert "private-filter-value" not in serialized
    assert all(row["data"]["outcome"] == "invalid" for row in audits)
    assert all(row["data"]["matched_count"] == 0 for row in audits)


@pytest.mark.asyncio
async def test_invalid_extreme_limits_do_not_query_rows(event_log: EventLog) -> None:
    reader = _CountingReader()
    tool = EventLogQueryTool(reader=reader, audit_sink=event_log)

    for invalid_limit in (-1, 10**100):
        result = await tool.invoke(
            {**_params(category="limit-validation"), "limit": invalid_limit},
            dict(_AUTHORIZED_CONTEXT),
        )
        assert result.output is None
        assert result.error == "event_log_query_invalid:limit"

    assert reader.specs == []


@pytest.mark.asyncio
async def test_unavailable_database_and_ordinary_failures_never_leak_rows(
    tmp_path: Path,
    event_log: EventLog,
) -> None:
    unavailable = EventLog(tmp_path / "not-started.db")
    unavailable_tool = EventLogQueryTool(
        reader=unavailable,
        audit_sink=unavailable,
    )
    unavailable_result = await unavailable_tool.invoke(
        _params(),
        dict(_AUTHORIZED_CONTEXT),
    )
    assert unavailable_result.error == "event_log_query_unavailable"
    assert unavailable_result.output is None
    assert not (tmp_path / "not-started.db").exists()

    reader_failure_tool = EventLogQueryTool(
        reader=_FailureReader(),
        audit_sink=event_log,
    )
    reader_failure = await reader_failure_tool.invoke(
        _params(),
        dict(_AUTHORIZED_CONTEXT),
    )
    assert reader_failure.error == "event_log_query_failed"
    assert reader_failure.output is None
    assert "password" not in reader_failure.error

    assert event_log._db is not None
    await event_log._db.execute("DROP TABLE events")
    await event_log._db.commit()
    database_failure_tool = EventLogQueryTool(
        reader=event_log,
        audit_sink=event_log,
    )
    database_failure = await database_failure_tool.invoke(
        _params(),
        dict(_AUTHORIZED_CONTEXT),
    )
    assert database_failure.error == "event_log_query_failed"
    assert database_failure.output is None


@pytest.mark.asyncio
async def test_success_audit_failure_suppresses_prepared_rows(
    event_log: EventLog,
) -> None:
    await _seed_records(
        event_log,
        [{"timestamp": _START, "category": "test", "event": "sensitive-row"}],
    )
    audit_sink = _FailureAuditSink()
    tool = EventLogQueryTool(reader=event_log, audit_sink=audit_sink)

    result = await tool.invoke(_params(), dict(_AUTHORIZED_CONTEXT))

    assert result.error == "event_log_query_failed"
    assert result.output is None
    assert len(audit_sink.audits) == 1
    assert audit_sink.audits[0].outcome == "success"
    assert audit_sink.audits[0].matched_count == 1
    assert audit_sink.audits[0].returned_count == 1


@pytest.mark.asyncio
async def test_query_and_audit_cancellation_propagate_unchanged(
    event_log: EventLog,
) -> None:
    query_cancel_tool = EventLogQueryTool(
        reader=_CancellationReader(),
        audit_sink=event_log,
    )
    with pytest.raises(asyncio.CancelledError):
        await query_cancel_tool.invoke(_params(), dict(_AUTHORIZED_CONTEXT))

    await _seed_records(
        event_log,
        [{"timestamp": _START, "category": "test", "event": "row"}],
    )
    audit_cancel_tool = EventLogQueryTool(
        reader=event_log,
        audit_sink=_CancellationAuditSink(),
    )
    with pytest.raises(asyncio.CancelledError):
        await audit_cancel_tool.invoke(_params(), dict(_AUTHORIZED_CONTEXT))


@pytest.mark.asyncio
async def test_direct_defense_in_depth_denial_and_audit_failure_stay_stable() -> None:
    failing_sink = _FailureAuditSink()
    tool = EventLogQueryTool(
        reader=_AvailableReader(),
        audit_sink=failing_sink,
    )

    denied = await tool.invoke(
        _params(category="denied-secret-value"),
        {
            "agent_id": "medical-actor",
            "agent_department": "medical",
            "agent_rank": "commander",
            "permission": "full",
        },
    )
    invalid = await tool.invoke(
        {**_params(category="invalid-secret-value"), "limit": True},
        dict(_AUTHORIZED_CONTEXT),
    )

    assert denied.error == "event_log_query_denied"
    assert denied.output is None
    assert invalid.error == "event_log_query_invalid:limit"
    assert invalid.output is None
    assert [audit.outcome for audit in failing_sink.audits] == [
        "denied",
        "invalid",
    ]
    serialized = repr(failing_sink.audits)
    assert "denied-secret-value" not in serialized
    assert "invalid-secret-value" not in serialized


@pytest.mark.asyncio
async def test_registry_denial_audit_cancellation_propagates() -> None:
    registry = ToolRegistry()
    _register_event_log_query_tool(
        tool_registry=registry,
        enabled=True,
        event_log_reader=_AvailableReader(),
        event_log_audit_sink=_CancellationAuditSink(),
    )

    with pytest.raises(asyncio.CancelledError):
        await registry.check_and_invoke(
            "medical-actor",
            "event_log_query",
            {"category": "secret-value"},
            agent_department="medical",
            agent_rank="commander",
        )


@pytest.mark.asyncio
async def test_authorization_matrix_grants_restrictions_and_fail_closed_scope(
    tmp_path: Path,
    event_log: EventLog,
) -> None:
    store = ToolPermissionStore(str(tmp_path / "permissions.db"))
    await store.start()
    try:
        registry = _registered_event_tool(event_log, store)
        for department in ("engineering", "science", "security"):
            for rank in ("lieutenant", "commander", "senior_officer"):
                assert registry.resolve_permission(
                    f"{department}-{rank}",
                    "event_log_query",
                    agent_department=department,
                    agent_rank=rank,
                ) is ToolPermission.READ
            assert registry.resolve_permission(
                f"{department}-ensign",
                "event_log_query",
                agent_department=department,
                agent_rank="ensign",
            ) is ToolPermission.NONE

        await store.issue_grant(
            "eligible-ensign",
            "event_log_query",
            ToolPermission.READ,
        )
        assert registry.resolve_permission(
            "eligible-ensign",
            "event_log_query",
            agent_department="engineering",
            agent_rank="ensign",
        ) is ToolPermission.READ

        await store.issue_grant(
            "restricted-lieutenant",
            "event_log_query",
            ToolPermission.NONE,
            is_restriction=True,
        )
        assert registry.resolve_permission(
            "restricted-lieutenant",
            "event_log_query",
            agent_department="science",
            agent_rank="lieutenant",
        ) is ToolPermission.NONE

        for agent_id, department, rank in (
            ("wrong-department", "medical", "commander"),
            ("unknown-rank", "engineering", "captain"),
        ):
            await store.issue_grant(
                agent_id,
                "event_log_query",
                ToolPermission.FULL,
            )
            assert registry.resolve_permission(
                agent_id,
                "event_log_query",
                agent_department=department,
                agent_rank=rank,
            ) is ToolPermission.NONE
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_registry_overwrites_forged_context_and_audits_success_and_denial(
    tmp_path: Path,
    event_log: EventLog,
) -> None:
    correlation_value = "Bearer top-secret-filter"
    await _seed_records(
        event_log,
        [
            {
                "timestamp": _START,
                "category": "diagnostic",
                "event": "probe",
                "correlation_id": correlation_value,
                "detail": "row-secret-content",
            }
        ],
    )
    store = ToolPermissionStore(str(tmp_path / "context-permissions.db"))
    await store.start()
    try:
        registry = _registered_event_tool(event_log, store)
        forged_context = {
            "agent_id": "forged-actor",
            "agent_department": "medical",
            "agent_rank": "senior_officer",
            "agent_types": ["forged-type"],
            "permission": "full",
        }
        success = await _invoke_authorized(
            registry,
            _params(
                category="diagnostic",
                event="probe",
                correlation_id=correlation_value,
            ),
            context=forged_context,
        )
        assert success.error is None
        assert success.output["returned_count"] == 1

        with pytest.raises(ToolPermissionDenied):
            await registry.check_and_invoke(
                "medical-actor",
                "event_log_query",
                {"category": "private-denial-value"},
                agent_department="medical",
                agent_rank="commander",
                context={
                    "agent_id": "forged-allowed",
                    "agent_department": "engineering",
                    "agent_rank": "senior_officer",
                    "permission": "full",
                },
            )

        audits = await event_log.query_structured(
            category="audit",
            event="event_log_query",
            limit=10,
        )
        assert len(audits) == 2
        by_outcome = {row["data"]["outcome"]: row["data"] for row in audits}
        assert by_outcome["success"]["actor_id"] == "laforge-1"
        assert by_outcome["success"]["department"] == "engineering"
        assert by_outcome["success"]["rank"] == "lieutenant"
        assert by_outcome["denied"]["actor_id"] == "medical-actor"
        assert by_outcome["denied"]["department"] == "medical"
        assert by_outcome["denied"]["rank"] == "commander"
        serialized = json.dumps(audits, sort_keys=True)
        for forbidden in (
            "top-secret-filter",
            "private-denial-value",
            "row-secret-content",
            "forged-actor",
            "forged-allowed",
            "SELECT ",
        ):
            assert forbidden not in serialized
        assert by_outcome["success"]["parameter_names"] == [
            "aggregate",
            "category",
            "correlation_id",
            "end_time",
            "event",
            "limit",
            "order",
            "start_time",
        ]
        assert by_outcome["success"]["matched_count"] == 1
        assert by_outcome["success"]["returned_count"] == 1
        assert by_outcome["denied"]["parameter_names"] == ["category"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_audit_query_does_not_recursively_include_its_current_audit(
    event_log: EventLog,
) -> None:
    await event_log.audit_governed_query(
        EventLogQueryAudit(
            actor_id="prior-actor",
            department="engineering",
            rank="lieutenant",
            outcome="success",
            parameter_names=("category",),
            window_seconds=60,
            aggregate="none",
            matched_count=0,
            returned_count=0,
            truncated=False,
        )
    )
    before = await event_log.query_structured(
        category="audit", event="event_log_query", limit=10
    )
    now = datetime.now(timezone.utc)
    result = await _invoke_authorized(
        _registered_event_tool(event_log),
        _params(
            category="audit",
            event="event_log_query",
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(minutes=1),
            order="oldest_first",
        ),
    )
    after = await event_log.query_structured(
        category="audit", event="event_log_query", limit=10
    )

    assert result.error is None
    assert result.output["matched_count"] == len(before) == 1
    assert result.output["returned_count"] == 1
    assert len(after) == len(before) + 1
    returned_ids = {row["id"] for row in result.output["rows"]}
    assert returned_ids == {before[0]["id"]}
    assert after[0]["id"] not in returned_ids


@pytest.mark.asyncio
async def test_startup_registration_gate_metadata_discovery_and_idempotency(
    event_log: EventLog,
) -> None:
    registry = ToolRegistry()
    _register_event_log_query_tool(
        tool_registry=registry,
        enabled=False,
        event_log_reader=event_log,
        event_log_audit_sink=event_log,
    )
    _register_event_log_query_tool(
        tool_registry=registry,
        enabled=True,
        event_log_reader=None,
        event_log_audit_sink=event_log,
    )
    _register_event_log_query_tool(
        tool_registry=registry,
        enabled=True,
        event_log_reader=event_log,
        event_log_audit_sink=None,
    )
    assert registry.get("event_log_query") is None

    _register_event_log_query_tool(
        tool_registry=registry,
        enabled=True,
        event_log_reader=event_log,
        event_log_audit_sink=event_log,
    )
    _register_event_log_query_tool(
        tool_registry=registry,
        enabled=True,
        event_log_reader=event_log,
        event_log_audit_sink=event_log,
    )

    assert registry.count() == 1
    registration = registry.get("event_log_query")
    assert registration is not None
    serialized = registration.to_dict()
    assert serialized["provider"] == "event_log"
    assert serialized["tags"] == [
        "event_log_query",
        "event_log",
        "diagnostics",
        "read_only",
    ]
    assert serialized["allowed_departments"] == [
        "engineering",
        "science",
        "security",
    ]
    assert serialized["default_permissions"] == {
        "ensign": "none",
        "lieutenant": "read",
        "commander": "read",
        "senior_officer": "read",
    }
    schema = registration.tool.input_schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["start_time", "end_time"]
    assert set(schema["properties"]) == {
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
    output_schema = registration.tool.output_schema
    assert output_schema["additionalProperties"] is False
    assert set(output_schema["properties"]) == set(output_schema["required"])
    row_schema = output_schema["properties"]["rows"]["items"]
    assert set(row_schema["properties"]) == _ROW_KEYS
    assert set(row_schema["required"]) == _ROW_KEYS
    assert [
        item.tool_id for item in registry.list_tools(department="engineering")
    ] == ["event_log_query"]
    assert registry.list_tools(department="medical") == []
    assert isinstance(event_log, EventLogProtocol)
    assert isinstance(event_log, EventLogReaderProtocol)
    assert isinstance(event_log, EventLogQueryAuditSink)


@pytest.mark.asyncio
async def test_work_item_agentic_executor_uses_61_49_result_in_later_turn(
    event_log: EventLog,
) -> None:
    await _seed_signature_fixture(event_log)
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        registry = _registered_event_tool(event_log, permission_store)
        params = _params(
            category="emergent",
            event="cooperation_cluster",
            limit=200,
            aggregate="cooperation_signature",
            order="oldest_first",
        )
        llm = _AggregateScriptedLLM(params)
        agent_registry = AgentRegistry()
        trust_network = TrustNetwork()
        runtime = _agentic_runtime(
            tool_registry=registry,
            permission_store=permission_store,
            identity_services={
                "registry": agent_registry,
                "ontology": _EngineeringOntology(),
                "trust_network": trust_network,
            },
        )
        engineering = EngineeringAgent(
            agent_id="laforge-1",
            llm_client=llm,
            runtime=runtime,
        )
        await agent_registry.register(engineering)
        executor = WorkItemAgenticExecutor(llm_client=llm)

        outcome = await executor.run(
            agent_id=engineering.id,
            instructions="Use governed evidence and report the leading signature.",
            task_text="Analyze cooperation clusters.",
            runtime=runtime,
            max_iterations=3,
            tier="standard",
        )

        assert outcome.final_text == (
            "Observed 61 cooperation rows with a 49-row leading signature."
        )
        assert outcome.stopped_reason == "complete"
        assert outcome.denied_tools == []
        assert len(llm.requests) == 2
        offered = {
            tool["function"]["name"] for tool in llm.requests[0].tools
        }
        assert offered == {"event_log_query"}
        assert "'total_rows': 61" in llm.requests[1].prompt
        assert "'valid_signature_rows': 61" in llm.requests[1].prompt
        assert "'count': 49" in llm.requests[1].prompt
        audits = await event_log.query_structured(
            category="audit",
            event="event_log_query",
            limit=10,
        )
        assert audits[0]["data"]["actor_id"] == engineering.id
        assert audits[0]["data"]["department"] == "engineering"
        assert audits[0]["data"]["rank"] == "lieutenant"
    finally:
        await permission_store.stop()


@pytest.mark.asyncio
async def test_agentic_identity_failures_precede_discovery_and_invocation(
    event_log: EventLog,
) -> None:
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        no_call_llm = _NoCallLLM()
        engineering = EngineeringAgent(
            agent_id="laforge-1",
            llm_client=no_call_llm,
            runtime=None,
        )
        registered_agents = AgentRegistry()
        await registered_agents.register(engineering)
        unregistered_agents = AgentRegistry()
        trust_network = TrustNetwork()
        empty_tools = ToolRegistry()
        governed_tools = _registered_event_tool(event_log, permission_store)
        scenarios = [
            (
                _agentic_runtime(
                    tool_registry=empty_tools,
                    permission_store=permission_store,
                    identity_services={"registry": registered_agents},
                ),
                engineering.id,
            ),
            (
                _agentic_runtime(
                    tool_registry=empty_tools,
                    permission_store=permission_store,
                    identity_services={
                        "registry": unregistered_agents,
                        "ontology": _EngineeringOntology(),
                        "trust_network": trust_network,
                    },
                ),
                engineering.id,
            ),
            (
                _agentic_runtime(
                    tool_registry=empty_tools,
                    permission_store=permission_store,
                    identity_services={
                        "registry": _MismatchedAgentRegistry(engineering),
                        "ontology": _EngineeringOntology(),
                        "trust_network": trust_network,
                    },
                ),
                "different-agent-id",
            ),
            (
                _agentic_runtime(
                    tool_registry=empty_tools,
                    permission_store=permission_store,
                    identity_services={
                        "registry": registered_agents,
                        "ontology": _FailingOntology(),
                        "trust_network": trust_network,
                    },
                ),
                engineering.id,
            ),
            (
                _agentic_runtime(
                    tool_registry=empty_tools,
                    permission_store=permission_store,
                    identity_services={
                        "registry": registered_agents,
                        "ontology": _EngineeringOntology(),
                        "trust_network": _FailingTrust(),
                    },
                ),
                engineering.id,
            ),
            (
                _agentic_runtime(
                    tool_registry=governed_tools,
                    permission_store=permission_store,
                ),
                engineering.id,
            ),
        ]

        for runtime, agent_id in scenarios:
            executor = WorkItemAgenticExecutor(llm_client=no_call_llm)
            with pytest.raises(
                RuntimeError,
                match="^agentic_identity_unresolved$",
            ):
                await executor.run(
                    agent_id=agent_id,
                    instructions="Do not run.",
                    task_text="Do not discover tools.",
                    runtime=runtime,
                )
        assert no_call_llm.requests == []
    finally:
        await permission_store.stop()


@pytest.mark.asyncio
async def test_legacy_event_neutral_runtime_retains_explicit_identity_fallback() -> None:
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        registry = ToolRegistry()
        registry.set_permission_store(permission_store)
        capture_tool = _ContextCaptureTool()
        registry.register(capture_tool, provider="test")
        await permission_store.issue_grant(
            "legacy-agent",
            capture_tool.tool_id,
            ToolPermission.READ,
        )
        llm = _ToolScriptedLLM(capture_tool.tool_id)
        runtime = _agentic_runtime(
            tool_registry=registry,
            permission_store=permission_store,
        )

        outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id="legacy-agent",
            instructions="Use the available test tool.",
            task_text="Capture the legacy context.",
            runtime=runtime,
            department="science",
            rank="commander",
            thread_id="legacy-thread",
            max_iterations=3,
        )

        assert outcome.final_text == "complete"
        assert len(capture_tool.contexts) == 1
        assert capture_tool.contexts[0]["agent_id"] == "legacy-agent"
        assert capture_tool.contexts[0]["department"] == "science"
        assert capture_tool.contexts[0]["rank"] == "commander"
        assert capture_tool.contexts[0]["thread_id"] == "legacy-thread"
    finally:
        await permission_store.stop()


@pytest.mark.asyncio
async def test_authoritative_context_overwrites_forged_reserved_values(
    event_log: EventLog,
) -> None:
    await _seed_signature_fixture(event_log)
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        registry = ToolRegistry()
        registry.set_permission_store(permission_store)
        recording_tool = _RecordingEventLogQueryTool(
            reader=event_log,
            audit_sink=event_log,
        )
        _register_recording_event_tool(registry, recording_tool)
        params = _params(
            category="emergent",
            event="cooperation_cluster",
            limit=200,
            aggregate="cooperation_signature",
        )
        llm = _AggregateScriptedLLM(params)
        agent_registry = AgentRegistry()
        trust_network = TrustNetwork()
        runtime = _agentic_runtime(
            tool_registry=registry,
            permission_store=permission_store,
            identity_services={
                "registry": agent_registry,
                "ontology": _EngineeringOntology(),
                "trust_network": trust_network,
            },
        )
        engineering = EngineeringAgent(
            agent_id="laforge-1",
            llm_client=llm,
            runtime=runtime,
        )
        await agent_registry.register(engineering)

        outcome = await WorkItemAgenticExecutor(llm_client=llm).run(
            agent_id=engineering.id,
            instructions="Use governed evidence.",
            task_text="Analyze cooperation clusters.",
            runtime=runtime,
            thread_id="authoritative-thread",
            max_iterations=3,
            extra_context={
                "agent_id": "forged-agent",
                "department": "medical",
                "rank": "senior_officer",
                "thread_id": "forged-thread",
                "_delegation_depth": 4,
                "_crew_session_id": "crew-session-1",
                "_crew_work_item_id": "crew-item-1",
            },
        )

        assert outcome.final_text == (
            "Observed 61 cooperation rows with a 49-row leading signature."
        )
        assert len(recording_tool.contexts) == 1
        invocation_context = recording_tool.contexts[0]
        assert invocation_context["agent_id"] == engineering.id
        assert invocation_context["department"] == "engineering"
        assert invocation_context["rank"] == "lieutenant"
        assert invocation_context["thread_id"] == "authoritative-thread"
        assert invocation_context["_delegation_depth"] == 4
        assert invocation_context["_crew_session_id"] == "crew-session-1"
        assert invocation_context["_crew_work_item_id"] == "crew-item-1"
        assert invocation_context["agent_department"] == "engineering"
        assert invocation_context["agent_rank"] == "lieutenant"

        audits = await event_log.query_structured(
            category="audit",
            event="event_log_query",
            limit=10,
        )
        assert audits[0]["data"]["actor_id"] == engineering.id
        assert audits[0]["data"]["department"] == "engineering"
        assert audits[0]["data"]["rank"] == "lieutenant"
        assert "forged-agent" not in json.dumps(audits, sort_keys=True)

        no_call_llm = _NoCallLLM()
        with pytest.raises(ValueError, match="^agentic_context_invalid$"):
            await WorkItemAgenticExecutor(llm_client=no_call_llm).run(
                agent_id=engineering.id,
                instructions="Do not run.",
                task_text="Reject unbound context.",
                runtime=runtime,
                extra_context={"unbound": "forbidden"},
            )
        assert no_call_llm.requests == []
    finally:
        await permission_store.stop()


@pytest.mark.asyncio
async def test_legacy_eventlog_and_unrelated_registry_shapes_remain_unchanged(
    event_log: EventLog,
) -> None:
    root_id = await event_log.log(
        category="legacy",
        event="root",
        data={"key": "value"},
    )
    child_id = await event_log.log(
        category="legacy",
        event="child",
        correlation_id="legacy-chain",
        parent_event_id=root_id,
    )
    assert type(root_id) is int
    assert type(child_id) is int

    query_rows = await event_log.query(category="legacy", limit=10)
    structured_rows = await event_log.query_structured(
        correlation_id="legacy-chain",
        event="child",
        limit=10,
    )
    chain = await event_log.get_event_chain(child_id)
    chain_ok, broken_at = await event_log.verify_chain()

    assert [row["event"] for row in query_rows] == ["child", "root"]
    assert structured_rows[0]["event"] == "child"
    assert [row["event"] for row in chain] == ["root", "child"]
    assert (chain_ok, broken_at) == (True, None)

    registry = ToolRegistry()
    registration = registry.register(
        _OrdinaryTool(),
        provider="test",
        tags=["ordinary"],
    )
    serialized = registration.to_dict()
    assert "allowed_departments" not in serialized
    assert registry.resolve_permission(
        "any-agent", "ordinary_tool", agent_rank="unknown-rank"
    ) is ToolPermission.READ
    result = await registry.check_and_invoke(
        "any-agent", "ordinary_tool", {}
    )
    assert result.output == {"ok": True}