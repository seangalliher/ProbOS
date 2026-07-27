"""AD-1139 governed, read-only Oracle query tool contracts.

Real ``ToolRegistry`` / ``ToolPermissionStore`` throughout (BF-287) — no mock
stands in at the registry boundary, because the department + rank gate this AD
turns on is exactly the thing a mock would paper over.
"""

from __future__ import annotations

import json
import re
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.oracle_service import OracleResult, OracleService
from probos.cognitive.swe_harness.tool_call import (
    TextBlock,
    ToolCallRequest,
    ToolUseBlock,
)
from probos.config import AgenticToolsConfig
from probos.startup.communication import _register_oracle_query_tool
from probos.tools.oracle_query_tool import (
    SIGMA_TIERS,
    SOVEREIGN_TIER,
    OracleQueryTool,
    _MAX_ENTRY_CHARS,
    _MAX_OUTPUT_CHARS,
    _MAX_QUERY_CHARS,
    _MAX_RESULTS,
    _ORACLE_DISPOSITION,
)
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult
from probos.tools.registry import ToolRegistry
from probos.types import LLMResponse

_ALL_DEPARTMENTS = (
    "engineering",
    "science",
    "medical",
    "security",
    "operations",
    "bridge",
)
_PROVENANCE_MARKER_RE = re.compile(
    r"^\[source:(\w+) confidence:\d\.\d{2} age:\d+[smh]( STALE)?\]$",
    re.MULTILINE,
)
_OMISSION_NOTE_RE = re.compile(
    r"\n\(\d+ further entr(?:y|ies) elided[^)]*\)\n?\Z"
)


class _RecordingOracle:
    """Captures every ``query`` kwarg set and replays scripted results."""

    def __init__(self, results: list[OracleResult] | None = None) -> None:
        self._results = list(results or [])
        self.calls: list[dict[str, Any]] = []

    async def query(self, query_text: str = "", **kwargs: Any) -> list[OracleResult]:
        self.calls.append({"query_text": query_text, **kwargs})
        return list(self._results)


class _RaisingOracle:
    def __init__(self) -> None:
        self.calls = 0

    async def query(self, *_args: Any, **_kwargs: Any) -> list[OracleResult]:
        self.calls += 1
        raise RuntimeError("oracle internals must not escape the tool")


class _ScriptedLLM:
    """One tool call, then a final answer that quotes what it received."""

    def __init__(self, arguments: dict[str, Any], *, needle: str) -> None:
        self._arguments = arguments
        self._needle = needle
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
                            name="oracle_query",
                            arguments=self._arguments,
                            id="oracle-call",
                        )
                    )
                ],
            )
        seen = self._needle in request.prompt
        text = "commons consulted" if seen else "commons evidence missing"
        return LLMResponse(
            content=text,
            tokens_used=1,
            content_blocks=[TextBlock(text=text)],
        )


class _NoToolLLM:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any, **_kwargs: object) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            content="done",
            tokens_used=1,
            content_blocks=[TextBlock(text="done")],
        )


class _FakeRecordsStore:
    """Tier 2 keyword path — records the ``scope`` the Oracle applies."""

    def __init__(self) -> None:
        self.scopes: list[Any] = []
        self.readers: list[tuple[Any, Any]] = []

    async def search(
        self,
        _query: str,
        *,
        scope: Any = None,
        reader_id: Any = None,
        reader_department: Any = "",
    ) -> list[dict[str, Any]]:
        self.scopes.append(scope)
        self.readers.append((reader_id, reader_department))
        return [
            {
                "path": "records/eng/deck12.md",
                "snippet": "KEYWORD deck twelve entry",
                "score": 8,
            }
        ]


class _FakeSemanticLayer:
    """AD-1138 shape: the records collection fails closed without a scope."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def search(
        self,
        _query: str,
        *,
        types: list[str] | None = None,
        limit: int = 5,
        include_episodes: bool = True,
        records_scope: str | None = None,
        reader_id: str | None = None,
        reader_department: str = "",
    ) -> list[dict[str, Any]]:
        if types != ["records"]:
            return []
        self.calls.append(
            {
                "types": types,
                "include_episodes": include_episodes,
                "records_scope": records_scope,
                "reader_id": reader_id,
                "reader_department": reader_department,
            }
        )
        if records_scope is None:
            return []
        return [
            {
                "id": "r1",
                "score": 0.9,
                "document": "SEMANTIC deck twelve entry",
                "metadata": {
                    "path": "records/eng/deck12.md",
                    "snippet": "SEMANTIC deck twelve entry",
                    "frontmatter_json": json.dumps({"classification": "ship"}),
                },
            }
        ]


def _result(
    tier: str,
    content: str,
    *,
    score: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> OracleResult:
    return OracleResult(
        source_tier=tier,
        content=content,
        score=score,
        metadata=metadata or {},
        provenance=f"[{tier}]",
    )


def _registered_oracle_tool(
    oracle: Any,
    permission_store: ToolPermissionStore | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    if permission_store is not None:
        registry.set_permission_store(permission_store)
    _register_oracle_query_tool(
        tool_registry=registry, enabled=True, oracle=oracle,
    )
    return registry


def _agentic_runtime(
    *,
    tool_registry: ToolRegistry,
    permission_store: ToolPermissionStore,
) -> SimpleNamespace:
    return SimpleNamespace(
        tool_registry=tool_registry,
        tool_permission_store=permission_store,
        intent_bus=None,
        intent_grant_store=None,
        mcp_workbench=None,
        cognitive_skill_catalog=None,
        attachment_store=None,
        emit_event=None,
        registry=None,
        ontology=None,
        trust_network=None,
        config=SimpleNamespace(
            execution=SimpleNamespace(enabled=False),
            mcp=SimpleNamespace(agent_tools_enabled=False),
            agentic_tools=SimpleNamespace(
                tool_search_enabled=False,
                delegation_enabled=False,
            ),
        ),
    )


async def _invoke(
    registry: ToolRegistry,
    params: dict[str, Any],
    *,
    agent_id: str = "crewman-1",
    department: str = "science",
    rank: str = "ensign",
) -> ToolResult:
    return await registry.check_and_invoke(
        agent_id,
        "oracle_query",
        params,
        agent_department=department,
        agent_rank=rank,
    )


# ── DD-1: Σ tiers only; never the sovereign episodic shard ────────────


def test_sigma_tier_list_is_the_commons_and_excludes_the_sovereign_shard() -> None:
    assert SOVEREIGN_TIER == "episodic"
    assert SOVEREIGN_TIER not in SIGMA_TIERS
    assert SIGMA_TIERS == (
        "records",
        "semantic",
        "graph",
        "archive",
        "operational",
        "health",
    )


@pytest.mark.asyncio
async def test_every_accepted_input_queries_only_sigma_tiers() -> None:
    oracle = _RecordingOracle([_result("records", "warp core service log")])
    tool = OracleQueryTool(oracle=oracle)

    await tool.invoke({"query": "warp core"})
    await tool.invoke({"query": "warp core", "kind": "all"})
    await tool.invoke({"query": "warp core", "kind": ""})
    for tier in SIGMA_TIERS:
        await tool.invoke({"query": "warp core", "kind": tier})

    assert len(oracle.calls) == 3 + len(SIGMA_TIERS)
    for call in oracle.calls:
        tiers = call["tiers"]
        assert SOVEREIGN_TIER not in tiers
        assert set(tiers) <= set(SIGMA_TIERS)
    assert oracle.calls[0]["tiers"] == list(SIGMA_TIERS)
    assert oracle.calls[3]["tiers"] == ["records"]


@pytest.mark.asyncio
async def test_caller_cannot_inject_the_sovereign_tier_through_params() -> None:
    oracle = _RecordingOracle([_result("records", "shared record")])
    tool = OracleQueryTool(oracle=oracle)

    by_kind = await tool.invoke({"query": "sensor logs", "kind": "episodic"})
    by_extra_param = await tool.invoke(
        {"query": "sensor logs", "tiers": ["episodic"]}
    )
    by_unknown_kind = await tool.invoke({"query": "sensor logs", "kind": "memory"})

    assert by_kind.error == "oracle_query_invalid:kind"
    assert by_extra_param.error == "oracle_query_invalid:parameter"
    assert by_unknown_kind.error == "oracle_query_invalid:kind"
    assert oracle.calls == []


@pytest.mark.asyncio
async def test_episodic_labelled_results_are_dropped_for_a_senior_caller() -> None:
    """BF-675 relabels episode-derived Tier 5 rows as ``episodic``.

    A ``senior_officer`` is the rank that resolves to ``RecallTier.ORACLE`` for
    the passive injection path, so this is the caller most able to argue for
    episode access. The tool still hands back commons material only.
    """
    oracle = _RecordingOracle(
        [
            _result("episodic", "PRIVATE SHARD: I felt uneasy on deck twelve"),
            _result("records", "Deck twelve inspection closed without findings"),
        ]
    )
    registry = _registered_oracle_tool(oracle)

    result = await _invoke(
        registry,
        {"query": "deck twelve"},
        agent_id="picard-1",
        department="bridge",
        rank="senior_officer",
    )

    assert result.error is None
    assert "PRIVATE SHARD" not in result.output
    assert f"source:{SOVEREIGN_TIER}" not in result.output
    assert "Deck twelve inspection closed" in result.output
    assert "[source:records" in result.output
    assert result.metadata["returned_count"] == 1
    tiers = {m.group(1) for m in _PROVENANCE_MARKER_RE.finditer(result.output)}
    assert tiers == {"records"}


# ── DD-2: framing is mandatory and inline ─────────────────────────────


@pytest.mark.asyncio
async def test_output_carries_the_disposition_preamble_and_per_item_provenance() -> None:
    oracle = _RecordingOracle(
        [
            _result("records", "Dilithium recrystallisation procedure", score=0.82),
            _result("graph", "laforge reports_to picard", score=0.70),
        ]
    )
    tool = OracleQueryTool(oracle=oracle)

    result = await tool.invoke({"query": "dilithium"})

    assert result.error is None
    output = result.output
    assert output.startswith("## Cross-Tier Knowledge (Ship's Records)")
    assert _ORACLE_DISPOSITION in output
    # The four things the framing must state.
    assert "shared knowledge stores" in output      # where it came from
    assert "not from your own memory" in output     # it is not the agent's memory
    assert "confidence" in output and "weigh" in output   # how much to trust it
    assert "Cite an entry" in output                # citing expected
    assert "do not narrate this lookup" in output   # narrating is not
    markers = _PROVENANCE_MARKER_RE.findall(output)
    assert len(markers) == 2
    assert {tier for tier, _stale in markers} == {"records", "graph"}
    assert "[source:records confidence:0.82 age:0s]" in output
    assert "[source:graph confidence:0.70 age:0s]" in output


@pytest.mark.asyncio
async def test_empty_commons_still_arrives_framed_and_explicit() -> None:
    tool = OracleQueryTool(oracle=_RecordingOracle([]))

    result = await tool.invoke({"query": "no such subject"})

    assert result.error is None
    assert result.output.startswith("## Cross-Tier Knowledge (Ship's Records)")
    assert _ORACLE_DISPOSITION in result.output
    assert "returned nothing for this query" in result.output
    assert result.metadata["returned_count"] == 0


# ── DD-3: wording must never trip the capability-gap regex ────────────


@pytest.mark.asyncio
async def test_rendered_output_never_matches_the_capability_gap_regex() -> None:
    populated = OracleQueryTool(
        oracle=_RecordingOracle(
            [_result(tier, f"{tier} entry body") for tier in SIGMA_TIERS]
        )
    )
    empty = OracleQueryTool(oracle=_RecordingOracle([]))
    failing = OracleQueryTool(oracle=_RaisingOracle())
    bulk = OracleQueryTool(
        oracle=_RecordingOracle(
            [_result("records", "x" * 4000) for _ in range(_MAX_RESULTS + 6)]
        )
    )

    outputs = [
        (await populated.invoke({"query": "commons"})).output,
        (await empty.invoke({"query": "commons"})).output,
        (await failing.invoke({"query": "commons"})).output,
        (await bulk.invoke({"query": "commons"})).output,
    ]

    for output in outputs:
        match = _CAPABILITY_GAP_RE.search(output)
        assert match is None, f"gap-regex hit {match.group(0)!r} in {output[:200]!r}"
    assert _CAPABILITY_GAP_RE.search(_ORACLE_DISPOSITION) is None
    assert _CAPABILITY_GAP_RE.search(populated.description) is None


# ── DD-4: bounded output ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_large_result_set_is_capped_by_count_entry_size_and_characters() -> None:
    oracle = _RecordingOracle(
        [
            _result("records", f"entry-{index} " + "y" * 5000)
            for index in range(_MAX_RESULTS + 12)
        ]
    )
    tool = OracleQueryTool(oracle=oracle)

    result = await tool.invoke({"query": "everything"})

    assert result.error is None
    assert len(result.output) <= _MAX_OUTPUT_CHARS
    rendered = result.metadata["returned_count"]
    assert 0 < rendered <= _MAX_RESULTS
    assert result.metadata["candidate_count"] == _MAX_RESULTS + 12
    assert "…[entry shortened]" in result.output
    assert "elided to stay inside the context budget" in result.output
    body = _OMISSION_NOTE_RE.sub("", result.output)
    entries = ["[source:" + chunk for chunk in body.split("\n[source:")[1:]]
    assert len(entries) == rendered
    for entry in entries:
        assert len(entry.rstrip("\n")) <= _MAX_ENTRY_CHARS


@pytest.mark.asyncio
async def test_small_result_set_is_returned_whole_without_an_omission_note() -> None:
    oracle = _RecordingOracle([_result("archive", "short archive entry")])
    tool = OracleQueryTool(oracle=oracle)

    result = await tool.invoke({"query": "archive"})

    assert "short archive entry" in result.output
    assert "…[entry shortened]" not in result.output
    assert "elided to stay inside the context budget" not in result.output


@pytest.mark.asyncio
async def test_bounding_degrades_locally_when_the_shared_helper_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DD-4: an unreachable ``truncate_tool_output`` still yields a bounded result."""
    monkeypatch.setitem(
        sys.modules, "probos.cognitive.swe_harness.agentic_loop", None
    )
    tool = OracleQueryTool(
        oracle=_RecordingOracle(
            [_result("records", f"entry-{i} " + "z" * 4000) for i in range(_MAX_RESULTS)]
        )
    )

    result = await tool.invoke({"query": "everything"})

    assert result.error is None
    assert len(result.output) <= _MAX_OUTPUT_CHARS
    assert _ORACLE_DISPOSITION in result.output


# ── Tier 2 survives the AD-1138 records fail-closed gate ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("records_semantic_enabled", [False, True])
async def test_tier_two_records_survive_the_ad1138_scope_gate(
    records_semantic_enabled: bool,
) -> None:
    """AD-1138 made the records collection fail closed without ``records_scope``.

    ``OracleService`` passes ``_RECORDS_QUERY_SCOPE`` on *both* Tier 2 paths, so
    this tool inherits the scope and Tier 2 keeps returning records. Asserted
    against a real ``OracleService`` rather than a stub oracle, because the
    scope is applied inside the service, not by the tool.

    BF-679: the invocation carries no ``context``, so there is no actor to
    resolve — both paths therefore receive the anonymous reader (``""``), which
    is the documented fail-closed state.

    BF-684: both axes now run on every query and are fused by reciprocal rank,
    rather than keyword being a fallback entered only when semantic returned
    nothing. That makes the scope assertion below *stronger*: the gate is
    proven on both paths simultaneously, not on whichever one happened to
    serve. Both fakes return the same ``path``, so fusion dedupes to a single
    result and the semantic payload wins — hence one result and the SEMANTIC
    body in both branches.
    """
    records_store = _FakeRecordsStore()
    semantic_layer = _FakeSemanticLayer()
    oracle = OracleService(
        records_store=records_store,
        semantic_layer=semantic_layer,
        records_semantic_enabled=records_semantic_enabled,
    )

    result = await OracleQueryTool(oracle=oracle).invoke(
        {"query": "deck twelve", "kind": "records"}
    )

    assert result.error is None
    assert "[source:records" in result.output
    assert result.metadata["returned_count"] == 1
    # The keyword axis runs either way, always scoped and always with the
    # anonymous reader.
    assert records_store.scopes == ["ship"]
    assert records_store.readers == [("", "")]
    if records_semantic_enabled:
        assert semantic_layer.calls == [
            {
                "types": ["records"],
                "include_episodes": False,
                "records_scope": "ship",
                "reader_id": "",
                "reader_department": "",
            }
        ]
        assert "SEMANTIC deck twelve entry" in result.output
    else:
        assert "KEYWORD deck twelve entry" in result.output
        assert semantic_layer.calls == []


# ── DD-5: registration + offer ────────────────────────────────────────


def test_registration_gate_metadata_and_idempotency() -> None:
    registry = ToolRegistry()
    oracle = _RecordingOracle()

    _register_oracle_query_tool(
        tool_registry=registry, enabled=False, oracle=oracle,
    )
    _register_oracle_query_tool(
        tool_registry=registry, enabled=True, oracle=None,
    )
    assert registry.get("oracle_query") is None

    _register_oracle_query_tool(
        tool_registry=registry, enabled=True, oracle=oracle,
    )
    _register_oracle_query_tool(
        tool_registry=registry, enabled=True, oracle=oracle,
    )
    assert registry.count() == 1

    registration = registry.get("oracle_query")
    assert registration is not None
    serialized = registration.to_dict()
    assert serialized["provider"] == "oracle"
    assert serialized["tags"] == [
        "oracle_query",
        "oracle",
        "knowledge",
        "read_only",
    ]
    assert serialized["allowed_departments"] == list(_ALL_DEPARTMENTS)
    assert serialized["default_permissions"] == {
        "ensign": "read",
        "lieutenant": "read",
        "commander": "read",
        "senior_officer": "read",
    }
    schema = registration.tool.input_schema
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["query"]
    assert set(schema["properties"]) == {"query", "kind"}
    assert schema["properties"]["kind"]["enum"] == [*SIGMA_TIERS, "all"]
    assert SOVEREIGN_TIER not in schema["properties"]["kind"]["enum"]


def test_all_six_departments_hold_read_from_ensign_upward() -> None:
    registry = _registered_oracle_tool(_RecordingOracle())

    for department in _ALL_DEPARTMENTS:
        for rank in ("ensign", "lieutenant", "commander", "senior_officer"):
            assert registry.check_permission(
                f"{department}-1",
                "oracle_query",
                ToolPermission.READ,
                agent_department=department,
                agent_rank=rank,
            ), f"{department}/{rank} must hold read on the commons"
        assert [
            reg.tool_id for reg in registry.list_tools(department=department)
        ] == ["oracle_query"]


def test_unknown_department_or_rank_is_denied_and_never_offered() -> None:
    registry = _registered_oracle_tool(_RecordingOracle())

    assert not registry.check_permission(
        "civilian-1",
        "oracle_query",
        ToolPermission.READ,
        agent_department="hospitality",
        agent_rank="ensign",
    )
    assert not registry.check_permission(
        "ghost-1",
        "oracle_query",
        ToolPermission.READ,
        agent_department="",
        agent_rank="ensign",
    )
    assert not registry.check_permission(
        "cadet-1",
        "oracle_query",
        ToolPermission.READ,
        agent_department="science",
        agent_rank="cadet",
    )
    assert registry.list_tools(department="hospitality") == []


@pytest.mark.asyncio
async def test_denied_agent_silently_receives_no_oracle_tool() -> None:
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        registry = _registered_oracle_tool(_RecordingOracle(), permission_store)
        runtime = _agentic_runtime(
            tool_registry=registry, permission_store=permission_store,
        )
        llm = _NoToolLLM()
        executor = WorkItemAgenticExecutor(llm_client=llm)

        outcome = await executor.run(
            agent_id="civilian-1",
            instructions="Work the task.",
            task_text="Summarise deck twelve.",
            runtime=runtime,
            department="hospitality",
            rank="ensign",
            max_iterations=2,
            tier="standard",
        )

        assert outcome.stopped_reason == "complete"
        assert outcome.denied_tools == []
        assert llm.requests[0].tools == []
    finally:
        await permission_store.stop()


@pytest.mark.asyncio
async def test_captain_grant_does_not_route_around_the_department_gate() -> None:
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        registry = _registered_oracle_tool(_RecordingOracle(), permission_store)
        await permission_store.issue_grant(
            "civilian-1",
            "oracle_query",
            ToolPermission.READ,
            reason="AD-1139 department-gate probe",
        )
        runtime = _agentic_runtime(
            tool_registry=registry, permission_store=permission_store,
        )
        llm = _NoToolLLM()
        executor = WorkItemAgenticExecutor(llm_client=llm)

        outcome = await executor.run(
            agent_id="civilian-1",
            instructions="Work the task.",
            task_text="Summarise deck twelve.",
            runtime=runtime,
            department="hospitality",
            rank="ensign",
            max_iterations=2,
            tier="standard",
        )

        assert outcome.stopped_reason == "complete"
        assert llm.requests[0].tools == []
    finally:
        await permission_store.stop()


@pytest.mark.asyncio
async def test_crew_child_reads_the_framed_commons_in_a_later_turn() -> None:
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        oracle = _RecordingOracle(
            [_result("records", "Deck twelve inspection closed without findings")]
        )
        registry = _registered_oracle_tool(oracle, permission_store)
        runtime = _agentic_runtime(
            tool_registry=registry, permission_store=permission_store,
        )
        llm = _ScriptedLLM(
            {"query": "deck twelve"},
            needle="Deck twelve inspection closed without findings",
        )
        executor = WorkItemAgenticExecutor(llm_client=llm)

        outcome = await executor.run(
            agent_id="crewman-1",
            instructions="Consult the commons before answering.",
            task_text="What is the state of deck twelve?",
            runtime=runtime,
            department="operations",
            rank="ensign",
            max_iterations=3,
            tier="standard",
        )

        assert outcome.final_text == "commons consulted"
        assert outcome.stopped_reason == "complete"
        assert outcome.denied_tools == []
        offered = {tool["function"]["name"] for tool in llm.requests[0].tools}
        assert offered == {"oracle_query"}
        # DD-2: the framing reaches the agent's own reasoning turn, not just
        # the ToolResult.
        assert _ORACLE_DISPOSITION in llm.requests[1].prompt
        assert "[source:records" in llm.requests[1].prompt
        assert oracle.calls[0]["tiers"] == list(SIGMA_TIERS)
        # BF-679: the loop's identity now reaches the Oracle, because Tier 2
        # resolves Ship's Records classification against it. DD-1's actual
        # invariant is unchanged and asserted alongside it: the sovereign tier
        # is still never requested, so identity can only narrow the result.
        assert oracle.calls[0].get("agent_id", "") == "crewman-1"
        assert SOVEREIGN_TIER not in oracle.calls[0]["tiers"]
    finally:
        await permission_store.stop()


@pytest.mark.asyncio
async def test_default_off_leaves_the_offered_tool_set_byte_identical() -> None:
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        registry = ToolRegistry()
        registry.set_permission_store(permission_store)
        _register_oracle_query_tool(
            tool_registry=registry, enabled=False, oracle=_RecordingOracle(),
        )
        runtime = _agentic_runtime(
            tool_registry=registry, permission_store=permission_store,
        )
        llm = _NoToolLLM()
        executor = WorkItemAgenticExecutor(llm_client=llm)

        outcome = await executor.run(
            agent_id="crewman-1",
            instructions="Work the task.",
            task_text="What is the state of deck twelve?",
            runtime=runtime,
            department="operations",
            rank="ensign",
            max_iterations=2,
            tier="standard",
        )

        assert outcome.stopped_reason == "complete"
        assert llm.requests[0].tools == []
        assert AgenticToolsConfig().oracle_query_enabled is False
    finally:
        await permission_store.stop()


# ── DD-6: read-only, honest-degrade ───────────────────────────────────


@pytest.mark.asyncio
async def test_oracle_failure_returns_a_framed_empty_result_without_raising() -> None:
    raising = OracleQueryTool(oracle=_RaisingOracle())
    unwired = OracleQueryTool(oracle=None)

    for tool in (raising, unwired):
        result = await tool.invoke({"query": "warp core"})
        assert result.error is None
        assert result.output.startswith("## Cross-Tier Knowledge (Ship's Records)")
        assert _ORACLE_DISPOSITION in result.output
        assert "returned nothing for this query" in result.output
        assert result.metadata["returned_count"] == 0


@pytest.mark.asyncio
async def test_unreachable_provenance_helper_degrades_to_a_framed_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DD-6: the outer guard covers a projection/import failure, not just the Oracle."""
    monkeypatch.setitem(sys.modules, "probos.cognitive.provenance", None)
    oracle = _RecordingOracle([_result("records", "unreachable body")])

    result = await OracleQueryTool(oracle=oracle).invoke({"query": "warp core"})

    assert result.error is None
    assert "unreachable body" not in result.output
    assert "returned nothing for this query" in result.output
    assert _CAPABILITY_GAP_RE.search(result.output) is None


@pytest.mark.asyncio
async def test_invalid_parameters_are_rejected_with_stable_codes() -> None:
    oracle = _RecordingOracle([_result("records", "body")])
    tool = OracleQueryTool(oracle=oracle)

    cases: list[tuple[Any, str]] = [
        ({}, "oracle_query_invalid:query"),
        ({"query": ""}, "oracle_query_invalid:query"),
        ({"query": "   "}, "oracle_query_invalid:query"),
        ({"query": 7}, "oracle_query_invalid:query"),
        ({"query": None}, "oracle_query_invalid:query"),
        ({"query": "x" * (_MAX_QUERY_CHARS + 1)}, "oracle_query_invalid:query"),
        ({"query": "ok", "kind": 3}, "oracle_query_invalid:kind"),
        ({"query": "ok", "limit": 5}, "oracle_query_invalid:parameter"),
        ("not-a-dict", "oracle_query_invalid:query"),
    ]
    for params, expected in cases:
        result = await tool.invoke(params)  # type: ignore[arg-type]
        assert result.error == expected, params
        assert result.output is None
    assert oracle.calls == []

    accepted = await tool.invoke({"query": "x" * _MAX_QUERY_CHARS})
    assert accepted.error is None
    assert len(oracle.calls) == 1


@pytest.mark.asyncio
async def test_tool_is_read_only_and_needs_only_read_permission() -> None:
    permission_store = ToolPermissionStore()
    await permission_store.start()
    try:
        registry = _registered_oracle_tool(_RecordingOracle(), permission_store)
        registration = registry.get("oracle_query")
        assert registration is not None
        assert registration.concurrency == "concurrent"
        assert not hasattr(registration.tool, "write")
        assert (
            registry.resolve_permission(
                "crewman-1",
                "oracle_query",
                agent_department="medical",
                agent_rank="senior_officer",
            )
            is ToolPermission.READ
        )
    finally:
        await permission_store.stop()
