"""AD-869: Yeo's Tier-2 "do-and-report" — synchronous inline mesh reads.

AD-845 built Yeo's *escalation* path ([CREATE_TASK] → async tracked work).
AD-869 builds the lightweight *default*: when the Captain asks for a quick
read-only lookup Yeo can answer *this turn*, Yeo emits a
``[MESH <intent> key=value ...]`` reply tag. ``DmReplyPipeline``'s new
``step_4h_mesh_read_parse`` resolves ONE read-only intent synchronously via a
single targeted ``IntentBus.send`` (~5s ceiling), renders the result inline,
and strips the tag.

The allowlist (:data:`_MESH_READ_INTENT_POOLS`) is the safety boundary:
writes and the consensus-gated ``http_fetch`` are excluded, because a
single-turn synchronous read is structurally incapable of mutation
(consensus cannot resolve in one turn).

These tests use a REAL ``IntentBus`` (+ ``SignalManager``), a REAL
``AgentRegistry``, a REAL ``DmSanityGate``, and a REAL subscribed handler —
no ``MagicMock`` at the substrate boundary (Phantom-via-MagicMock trap, repo
conventions).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.dm.reply_pipeline import (
    _MESH_READ_INTENT_POOLS,
    _MESH_READ_NETWORK_TTL_SECONDS,
    _MESH_READ_TTL_BY_INTENT,
    _MESH_READ_TTL_SECONDS,
    DmReplyContext,
    DmReplyPipeline,
)
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.substrate.registry import AgentRegistry
from probos.types import IntentMessage, IntentResult


# ---------------------------------------------------------------------------
# Fixtures / fakes (substrate-honest: real bus, real registry, real handler)
# ---------------------------------------------------------------------------


def _stub_agent(agent_id: str, pool: str) -> SimpleNamespace:
    """Minimal BaseAgent stand-in for registry.get_by_pool (reads .id/.pool)."""
    return SimpleNamespace(
        id=agent_id, agent_type=pool, pool=pool, capabilities=[], is_alive=True,
    )


async def _make_runtime(
    *,
    intent_name: str,
    pool: str,
    handler,
    register_agent: bool = True,
) -> tuple[SimpleNamespace, IntentBus, list[IntentMessage]]:
    """Build a runtime with a REAL IntentBus + AgentRegistry.

    When ``register_agent`` is True a stub agent is registered in ``pool`` and
    ``handler`` is subscribed under its id. Returns (runtime, bus, seen) where
    ``seen`` accumulates every IntentMessage the handler received.
    """
    bus = IntentBus(SignalManager())
    registry = AgentRegistry()
    seen: list[IntentMessage] = []

    async def _wrapped(intent: IntentMessage) -> IntentResult:
        seen.append(intent)
        return await handler(intent)

    if register_agent:
        agent = _stub_agent(f"{pool}-agent-0", pool)
        await registry.register(agent)
        bus.subscribe(agent.id, _wrapped, [intent_name])

    runtime = SimpleNamespace(intent_bus=bus, registry=registry)
    return runtime, bus, seen


def _make_pipeline(
    *, runtime: object, response_text: str, sanity_gate: DmSanityGate | None,
) -> DmReplyPipeline:
    ctx = DmReplyContext(
        runtime=runtime,
        agent=SimpleNamespace(id="yeoman-001", agent_type="yeoman"),
        agent_id="yeoman-001",
        callsign="Yeo",
        req_message="What's in the config directory?",
        response_text=response_text,
        has_image_attachment=False,
        per_attachment=[],
        sanity_gate=sanity_gate,
        params={},
        message_text="What's in the config directory?",
        sampling_state=None,
        avatar_event_bus=None,
    )
    return DmReplyPipeline(ctx)


# ===========================================================================
# Sanity-gate unit tests: extract_mesh_read / strip_mesh_read
# ===========================================================================


def test_extract_mesh_read_single_param() -> None:
    gate = DmSanityGate()
    parsed = gate.extract_mesh_read("Sure. [MESH list_directory path=/etc] one sec.")
    assert parsed == ("list_directory", {"path": "/etc"})


def test_extract_mesh_read_multiword_value() -> None:
    gate = DmSanityGate()
    parsed = gate.extract_mesh_read("[MESH web_search query=Nvidia SPARK RTX devices]")
    assert parsed == ("web_search", {"query": "Nvidia SPARK RTX devices"})


def test_extract_mesh_read_preserves_embedded_equals_in_url() -> None:
    gate = DmSanityGate()
    parsed = gate.extract_mesh_read("[MESH read_page url=https://x.test/p?a=b&c=d]")
    assert parsed is not None
    intent, params = parsed
    assert intent == "read_page"
    assert params["url"] == "https://x.test/p?a=b&c=d"


def test_extract_mesh_read_no_tag_returns_none() -> None:
    gate = DmSanityGate()
    assert gate.extract_mesh_read("Just a normal reply, Captain.") is None


def test_extract_mesh_read_parameterless_treated_malformed() -> None:
    gate = DmSanityGate()
    # No key=value pairs -> regex requires a params blob; a bare intent has
    # none, so this is malformed and yields None (stripped, never dispatched).
    assert gate.extract_mesh_read("[MESH list_directory]") is None


def test_strip_mesh_read_removes_wellformed_and_malformed() -> None:
    gate = DmSanityGate()
    text = "Here [MESH list_directory path=/x] and a [MESH oops] tail."
    stripped = gate.strip_mesh_read(text)
    assert "[MESH" not in stripped
    assert "Here" in stripped and "tail." in stripped


# ===========================================================================
# Pipeline integration tests: step_4h_mesh_read_parse
# ===========================================================================


def test_mesh_read_allowlisted_executes_renders_and_strips() -> None:
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id or "x",
                success=True,
                result={"entries": ["node-1.yaml", "system.yaml"]},
            )

        runtime, bus, seen = await _make_runtime(
            intent_name="list_directory", pool="directory", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="Here's the config dir. [MESH list_directory path=config]",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()

        # The read ran exactly once, targeted at the resolved agent.
        assert len(seen) == 1
        assert seen[0].intent == "list_directory"
        assert seen[0].params == {"path": "config"}
        assert seen[0].target_agent_id == "directory-agent-0"
        # Tag stripped; result rendered inline.
        assert "[MESH" not in pipeline.ctx.response_text
        assert "system.yaml" in pipeline.ctx.response_text

    asyncio.run(_run())


def test_mesh_read_non_allowlisted_intent_not_executed() -> None:
    async def _run() -> None:
        called = {"n": 0}

        async def handler(intent: IntentMessage) -> IntentResult:
            called["n"] += 1
            return IntentResult(intent_id=intent.id, agent_id="x", success=True)

        # http_fetch is consensus-gated and deliberately NOT in the allowlist.
        assert "http_fetch" not in _MESH_READ_INTENT_POOLS
        runtime, bus, seen = await _make_runtime(
            intent_name="http_fetch", pool="http", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="[MESH http_fetch url=https://x.test] checking.",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()

        # Never executed; tag stripped; reply shipped.
        assert called["n"] == 0
        assert len(seen) == 0
        assert "[MESH" not in pipeline.ctx.response_text
        assert "checking." in pipeline.ctx.response_text

    asyncio.run(_run())


def test_mesh_read_no_tag_is_noop() -> None:
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(intent_id=intent.id, agent_id="x", success=True)

        runtime, bus, seen = await _make_runtime(
            intent_name="list_directory", pool="directory", handler=handler,
        )
        original = "Just a plain conversational reply, Captain."
        pipeline = _make_pipeline(
            runtime=runtime, response_text=original, sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()

        assert len(seen) == 0
        assert pipeline.ctx.response_text == original

    asyncio.run(_run())


def test_mesh_read_intent_bus_none_degrades() -> None:
    async def _run() -> None:
        runtime = SimpleNamespace(intent_bus=None, registry=AgentRegistry())
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="One sec. [MESH list_directory path=config]",
            sanity_gate=DmSanityGate(),
        )
        # Must not raise; tag stripped; reply still shipped.
        await pipeline.step_4h_mesh_read_parse()
        assert "[MESH" not in pipeline.ctx.response_text
        assert "One sec." in pipeline.ctx.response_text

    asyncio.run(_run())


def test_mesh_read_no_capable_agent_appends_honest_note() -> None:
    async def _run() -> None:
        # Real bus + registry but NO agent registered in the target pool.
        bus = IntentBus(SignalManager())
        runtime = SimpleNamespace(intent_bus=bus, registry=AgentRegistry())
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="Checking. [MESH list_directory path=config]",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()
        assert "[MESH" not in pipeline.ctx.response_text
        assert "list_directory" in pipeline.ctx.response_text  # honest note
        # Degrade note must not trip the decomposer capability-gap regex.
        assert not _CAPABILITY_GAP_RE.search(pipeline.ctx.response_text)

    asyncio.run(_run())


def test_mesh_read_send_failure_appends_honest_note() -> None:
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            raise RuntimeError("boom")

        runtime, bus, seen = await _make_runtime(
            intent_name="search_files", pool="search", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="Looking. [MESH search_files query=spark]",
            sanity_gate=DmSanityGate(),
        )
        # Handler raises -> send propagates -> step degrades, never raises.
        await pipeline.step_4h_mesh_read_parse()
        assert "[MESH" not in pipeline.ctx.response_text
        assert "search_files" in pipeline.ctx.response_text
        assert not _CAPABILITY_GAP_RE.search(pipeline.ctx.response_text)

    asyncio.run(_run())


def test_mesh_read_unsuccessful_result_renders_empty_note() -> None:
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id="x",
                success=False,
                error="Agent did not respond in time.",
            )

        runtime, bus, seen = await _make_runtime(
            intent_name="read_file", pool="filesystem", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="Reading. [MESH read_file path=README.md]",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()
        assert "[MESH" not in pipeline.ctx.response_text
        assert "read_file" in pipeline.ctx.response_text
        assert not _CAPABILITY_GAP_RE.search(pipeline.ctx.response_text)

    asyncio.run(_run())


def test_mesh_read_large_payload_truncated() -> None:
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id="x",
                success=True,
                result="X" * 5000,
            )

        runtime, bus, seen = await _make_runtime(
            intent_name="read_file", pool="filesystem", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="Reading. [MESH read_file path=big.txt]",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()
        assert "truncated" in pipeline.ctx.response_text
        # The full 5000-char payload is not inlined verbatim.
        assert len(pipeline.ctx.response_text) < 5000

    asyncio.run(_run())


# ===========================================================================
# BF-609: per-intent TTL — network + LLM-bound reads get a larger ceiling
# ===========================================================================


def test_mesh_read_web_search_dispatched_with_network_ttl() -> None:
    # BF-609: web_search mesh-fetches DuckDuckGo (rate-limited) then runs an
    # LLM (requires_reflect) — realistically 8-20s. The flat 5s ceiling timed
    # it out every time. It must dispatch with the larger network ceiling.
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id or "x",
                success=True,
                result="top result",
            )

        runtime, bus, seen = await _make_runtime(
            intent_name="web_search", pool="web_search", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="Looking that up. [MESH web_search query=Nvidia SPARK]",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()

        assert len(seen) == 1
        assert seen[0].intent == "web_search"
        assert seen[0].ttl_seconds == _MESH_READ_NETWORK_TTL_SECONDS
        assert _MESH_READ_NETWORK_TTL_SECONDS > _MESH_READ_TTL_SECONDS
        assert "[MESH" not in pipeline.ctx.response_text

    asyncio.run(_run())


def test_mesh_read_read_page_dispatched_with_network_ttl() -> None:
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id or "x",
                success=True,
                result="page summary",
            )

        runtime, bus, seen = await _make_runtime(
            intent_name="read_page", pool="page_reader", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="Reading it. [MESH read_page url=https://x.test/p]",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()

        assert len(seen) == 1
        assert seen[0].ttl_seconds == _MESH_READ_NETWORK_TTL_SECONDS

    asyncio.run(_run())


def test_mesh_read_local_io_keeps_default_ttl() -> None:
    # Local-IO reads finish in ms; they must keep the tight default ceiling.
    async def _run() -> None:
        async def handler(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id or "x",
                success=True,
                result={"entries": ["a"]},
            )

        runtime, bus, seen = await _make_runtime(
            intent_name="list_directory", pool="directory", handler=handler,
        )
        pipeline = _make_pipeline(
            runtime=runtime,
            response_text="One sec. [MESH list_directory path=config]",
            sanity_gate=DmSanityGate(),
        )
        await pipeline.step_4h_mesh_read_parse()

        assert len(seen) == 1
        assert seen[0].ttl_seconds == _MESH_READ_TTL_SECONDS

    asyncio.run(_run())


def test_network_ttl_map_covers_exactly_the_network_intents() -> None:
    # The override map must target only the network + LLM-bound reads.
    assert set(_MESH_READ_TTL_BY_INTENT) == {"web_search", "read_page"}
    for intent_name in _MESH_READ_TTL_BY_INTENT:
        assert intent_name in _MESH_READ_INTENT_POOLS


# ===========================================================================
# Allowlist + safety invariants
# ===========================================================================


def test_allowlist_excludes_writes_and_consensus_gated_intents() -> None:
    # Tier-2 safety boundary: only read-only intents are inline-runnable.
    for forbidden in ("http_fetch", "write_file", "run_command", "delete_file"):
        assert forbidden not in _MESH_READ_INTENT_POOLS
    # The allowlist contents are exactly the read intents (AD-989 added the
    # read-only ``search_content`` content-grep capability).
    assert set(_MESH_READ_INTENT_POOLS) == {
        "list_directory", "read_file", "stat_file",
        "search_files", "search_content", "web_search", "read_page",
    }


def test_no_direct_http_clients_in_mesh_read_source() -> None:
    # Mesh-delegated HTTP only (Design Principle #10): no httpx/requests in
    # the reply pipeline or sanity gate.
    root = Path(__file__).resolve().parents[1] / "src" / "probos" / "cognitive"
    for rel in ("dm/reply_pipeline.py", "dm_sanity_gate.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "import httpx" not in src
        assert "import requests" not in src
