"""AD-641g: tests for chain subject schema + ChainNATSBridge publish-side."""
from __future__ import annotations

import asyncio
import json
import pytest

from probos.cognitive.chain_nats_bridge import ChainNATSBridge
from probos.cognitive.chain_subjects import (
    CHAIN_STREAM,
    chain_stream_subjects,
    chain_subject,
    chain_wildcard,
)
from probos.cognitive.sub_task import (
    SubTaskExecutor,
    SubTaskResult,
    SubTaskSpec,
    SubTaskType,
)
from probos.config import SubTaskConfig
from probos.mesh.nats_bus import MockNATSBus


def _make_bus(connected: bool = True) -> MockNATSBus:
    bus = MockNATSBus(subject_prefix="probos.test")
    bus._connected = connected  # bypass start() to keep tests synchronous
    return bus


def _make_bridge(*, enabled: bool = True, connected: bool = True, payload_max: int = 16384) -> tuple[ChainNATSBridge, MockNATSBus]:
    cfg = SubTaskConfig(nats_publish_enabled=enabled, nats_payload_max_bytes=payload_max)
    bus = _make_bus(connected=connected)
    return ChainNATSBridge(nats_bus=bus, config=cfg), bus


# ---------------------------------------------------------------------------
# Subject schema
# ---------------------------------------------------------------------------


def test_chain_subject_format() -> None:
    assert chain_subject("alice", SubTaskType.ANALYZE) == "chain.alice.analyze.complete"
    assert chain_subject("alice", SubTaskType.COMPOSE, "error") == "chain.alice.compose.error"


def test_chain_subject_sanitizes_agent_id() -> None:
    # Colons, spaces, slashes — none are valid NATS token chars.
    assert chain_subject("agent:42", SubTaskType.QUERY) == "chain.agent_42.query.complete"
    assert chain_subject("a b/c", SubTaskType.QUERY) == "chain.a_b_c.query.complete"


def test_chain_wildcard_and_stream_subjects() -> None:
    assert chain_wildcard() == "chain.*.*.>"
    assert chain_wildcard("alice") == "chain.alice.*.>"
    assert chain_stream_subjects() == ["chain.>"]
    assert CHAIN_STREAM == "COGNITIVE_CHAIN"


# ---------------------------------------------------------------------------
# Bridge enabled-flag semantics
# ---------------------------------------------------------------------------


def test_bridge_disabled_when_flag_false() -> None:
    bridge, _ = _make_bridge(enabled=False)
    assert bridge.enabled is False


def test_bridge_disabled_when_nats_disconnected() -> None:
    bridge, _ = _make_bridge(enabled=True, connected=False)
    assert bridge.enabled is False


def test_bridge_enabled_when_flag_true_and_connected() -> None:
    bridge, _ = _make_bridge(enabled=True, connected=True)
    assert bridge.enabled is True


# ---------------------------------------------------------------------------
# Publish behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_step_complete_publishes_to_correct_subject() -> None:
    bridge, bus = _make_bridge()
    result = SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-thread",
        result={"intended_actions": ["ward_room_post"]},
        duration_ms=12.5,
        success=True,
    )
    bridge.publish_step_complete(
        agent_id="alice", step=SubTaskType.ANALYZE, result=result, intent_id="i1",
    )
    # Drain pending tasks
    await asyncio.gather(*list(bridge._publish_tasks))
    assert any(s.endswith("chain.alice.analyze.complete") for s, _ in bus.published)
    subject, payload = next(
        (s, p) for s, p in bus.published if s.endswith("chain.alice.analyze.complete")
    )
    assert payload["agent_id"] == "alice"
    assert payload["step"] == "analyze"
    assert payload["ok"] is True
    assert payload["intent_id"] == "i1"
    assert payload["result"] == {"intended_actions": ["ward_room_post"]}


@pytest.mark.asyncio
async def test_publish_step_complete_routes_failure_to_error_subject() -> None:
    bridge, bus = _make_bridge()
    result = SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-reply",
        result={},
        success=False,
        error="LLM timeout",
    )
    bridge.publish_step_complete(
        agent_id="alice", step=SubTaskType.COMPOSE, result=result,
    )
    await asyncio.gather(*list(bridge._publish_tasks))
    subjects = [s for s, _ in bus.published]
    assert any(s.endswith("chain.alice.compose.error") for s in subjects)


@pytest.mark.asyncio
async def test_publish_step_error_publishes_error_payload() -> None:
    bridge, bus = _make_bridge()
    bridge.publish_step_error(
        agent_id="bob", step=SubTaskType.QUERY, error="missing handler", intent_id="i2",
    )
    await asyncio.gather(*list(bridge._publish_tasks))
    subject, payload = bus.published[-1]
    assert subject.endswith("chain.bob.query.error")
    assert payload["ok"] is False
    assert payload["error"] == "missing handler"
    assert payload["intent_id"] == "i2"


@pytest.mark.asyncio
async def test_disabled_bridge_publish_is_noop() -> None:
    bridge, bus = _make_bridge(enabled=False)
    result = SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="x", result={})
    bridge.publish_step_complete(agent_id="alice", step=SubTaskType.ANALYZE, result=result)
    bridge.publish_step_error(agent_id="alice", step=SubTaskType.ANALYZE, error="e")
    await asyncio.sleep(0)
    assert bus.published == []


# ---------------------------------------------------------------------------
# Payload truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payload_oversize_truncates_result() -> None:
    bridge, bus = _make_bridge(payload_max=256)
    big_blob = "x" * 4096
    result = SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="huge",
        result={"data": big_blob},
        success=True,
    )
    bridge.publish_step_complete(agent_id="alice", step=SubTaskType.ANALYZE, result=result)
    await asyncio.gather(*list(bridge._publish_tasks))
    _, payload = bus.published[-1]
    assert payload["result"].get("truncated") is True
    assert payload["result"].get("size", 0) > 256


@pytest.mark.asyncio
async def test_payload_non_serializable_result_replaced() -> None:
    bridge, bus = _make_bridge()
    # A set is not JSON-serializable.
    result = SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="bad",
        result={"thing": {1, 2, 3}},
        success=True,
    )
    bridge.publish_step_complete(agent_id="alice", step=SubTaskType.ANALYZE, result=result)
    await asyncio.gather(*list(bridge._publish_tasks))
    _, payload = bus.published[-1]
    assert payload["result"] == {"truncated": True, "reason": "non-serializable"}


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_failure_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge, bus = _make_bridge()

    async def boom(*_a, **_kw):
        raise RuntimeError("nats down")

    monkeypatch.setattr(bus, "js_publish", boom)
    result = SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="x", result={}, success=True)
    # Must not raise even though js_publish always errors.
    bridge.publish_step_complete(agent_id="alice", step=SubTaskType.ANALYZE, result=result)
    await asyncio.gather(*list(bridge._publish_tasks), return_exceptions=True)


# ---------------------------------------------------------------------------
# Stream provisioning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_stream_idempotent_and_skips_when_disabled() -> None:
    bridge_off, bus_off = _make_bridge(enabled=False)
    await bridge_off.ensure_stream()
    assert CHAIN_STREAM not in bus_off._streams

    bridge_on, bus_on = _make_bridge(enabled=True)
    await bridge_on.ensure_stream()
    await bridge_on.ensure_stream()  # second call short-circuits
    assert CHAIN_STREAM in bus_on._streams


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_publishes_per_step_when_bridge_attached() -> None:
    from probos.cognitive.sub_task import SubTaskChain

    bridge, bus = _make_bridge()
    cfg = SubTaskConfig(nats_publish_enabled=True)

    async def query_handler(spec, ctx, prior):
        return SubTaskResult(sub_task_type=spec.sub_task_type, name=spec.name, result={"hits": 1}, success=True)

    async def analyze_handler(spec, ctx, prior):
        return SubTaskResult(sub_task_type=spec.sub_task_type, name=spec.name, result={"intended_actions": []}, success=True)

    executor = SubTaskExecutor(config=cfg, nats_bridge=bridge)
    executor.register_handler(SubTaskType.QUERY, query_handler)
    executor.register_handler(SubTaskType.ANALYZE, analyze_handler)

    chain = SubTaskChain(steps=[
        SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="browse"),
        SubTaskSpec(sub_task_type=SubTaskType.ANALYZE, name="think"),
    ])
    await executor.execute(chain, {}, agent_id="alice", agent_type="A", intent="t", intent_id="i9")
    await asyncio.gather(*list(bridge._publish_tasks))

    subjects = [s for s, _ in bus.published]
    assert any(s.endswith("chain.alice.query.complete") for s in subjects), subjects
    assert any(s.endswith("chain.alice.analyze.complete") for s in subjects), subjects
