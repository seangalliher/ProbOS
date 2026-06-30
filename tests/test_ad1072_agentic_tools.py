"""AD-1072: tool-search (``search_capabilities``) + sub-agent delegation
(``delegate_task``) for the AD-1065 conversational ``AgenticLoop``.

Substrate-honest fixtures per BF-287: a REAL ``ToolRegistry`` / ``ToolPermissionStore``,
a REAL ``CognitiveSkillCatalog`` scanning a fixture skill on disk, a REAL
``CallsignRegistry`` (so the AD-1076 is_alive trap is exercised), and the REAL
``WorkItemAgenticExecutor`` driven by a scripted-LLM loop. No MagicMock at the
registry / executor boundary. The delegation depth guard is proven with a
*counting* fake executor (it must never be constructed at max depth).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from probos.artifacts import ArtifactStore
from probos.config import AgenticToolsConfig, ExecutionConfig
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from probos.crew_profile import CallsignRegistry
from probos.tools.delegate_task_tool import DelegateTaskTool
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.tools.search_capabilities_tool import SearchCapabilitiesTool


# ── shared real Tool stubs ────────────────────────────────────────────────
class _StubTool:
    """A real Tool-protocol object with controllable id / name / description
    (so the capability catalog has deterministic candidates to rank)."""

    def __init__(self, tool_id: str, name: str, description: str) -> None:
        self._tool_id, self._name, self._description = tool_id, name, description

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    async def invoke(self, params, context=None) -> ToolResult:
        return ToolResult(output={})


class _ProbeTool:
    """A real probe tool that records the invocation context (used to prove a
    nested delegated run carries the incremented ``_delegation_depth`` and runs
    as the target agent)."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen_depth = None
        self.seen_agent_id = None

    @property
    def tool_id(self) -> str:
        return "nested_probe"

    @property
    def name(self) -> str:
        return "Nested Probe"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return "Test probe that records its invocation context."

    @property
    def input_schema(self) -> dict:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    async def invoke(self, params, context=None) -> ToolResult:
        ctx = context or {}
        self.calls += 1
        self.seen_depth = ctx.get("_delegation_depth")
        self.seen_agent_id = ctx.get("agent_id")
        return ToolResult(output={"ok": True})


class _FakeAttachmentStore:
    """Protocol-faithful in-memory AttachmentStore (AD-720 write signature)."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple] = {}

    async def write(self, content_hash, blob, mime, *, origin="chat_attachment"):
        self.blobs[content_hash] = (blob, mime, origin)
        return Path(f"/fake/{content_hash}")


# ── scripted-LLM loop harness (mirrors AD-1066/1068) ──────────────────────
class _FakeLLMResponse:
    def __init__(self, content_blocks, content="", tokens=1):
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.last_tools = None

    async def complete(self, req, **_kwargs):
        self.last_tools = list(getattr(req, "tools", None) or [])
        if self._responses:
            return self._responses.pop(0)
        return _FakeLLMResponse(content_blocks=[], content="done")


def _tool_use(tool_id, args):
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    return _FakeLLMResponse(
        content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(name=tool_id, arguments=args))],
        content="",
        tokens=1,
    )


def _text(text):
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _tool_names(last_tools):
    return [
        (t.get("function", {}) or {}).get("name") or t.get("name")
        for t in (last_tools or [])
    ]


# ── skill-catalog fixtures (mirror AD-1068) ───────────────────────────────
def _write_skill(skills_root: Path, name: str, *, description: str) -> Path:
    d = skills_root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {name}\n\n{description}\n",
        encoding="utf-8",
    )
    return d


async def _catalog(skills_root: Path) -> CognitiveSkillCatalog:
    cat = CognitiveSkillCatalog(skills_dir=skills_root)
    await cat.start()  # db_path=None ⇒ in-memory scan only
    return cat


# ════════════════════════════════════════════════════════════════════════
# search_capabilities
# ════════════════════════════════════════════════════════════════════════
def _search_runtime(*, catalog=None) -> SimpleNamespace:
    reg = ToolRegistry()
    reg.register(_StubTool("docx_maker", "Word Document Maker", "Create a Word document"), provider="test")
    reg.register(_StubTool("doc_conv", "Document Converter", "Convert any document"), provider="test")
    reg.register(_StubTool("pdf_exp", "PDF Exporter", "Export a PDF file"), provider="test")
    return SimpleNamespace(
        tool_registry=reg,
        cognitive_skill_catalog=catalog,
        registry=None,                 # held_by maps empty (honest-degrade)
        tool_permission_store=None,
        skill_grant_store=None,
        config=SimpleNamespace(mcp=None),
    )


async def test_search_ranks_results_by_keyword_overlap() -> None:
    tool = SearchCapabilitiesTool(runtime=_search_runtime())

    result = await tool.invoke({"query": "word document"}, {"agent_id": "ezri"})

    assert result.error is None
    names = [r["name"] for r in result.output["results"]]
    # Name + description overlap → "Word Document Maker" outranks the converter.
    assert names[0] == "Word Document Maker"
    assert "Document Converter" in names
    # Zero token overlap → dropped entirely.
    assert "PDF Exporter" not in names
    assert result.output["count"] == len(result.output["results"])


async def test_search_kind_filter_narrows_to_skills(tmp_path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills, "document-helper", description="A skill that creates a document file.")
    cat = await _catalog(skills)
    tool = SearchCapabilitiesTool(runtime=_search_runtime(catalog=cat))

    # 'all' spans both axes; the query matches tools AND the skill.
    res_all = await tool.invoke({"query": "document", "kind": "all"}, {"agent_id": "ezri"})
    kinds_all = {r["kind"] for r in res_all.output["results"]}
    assert "tool" in kinds_all and "skill" in kinds_all

    # 'skill' narrows to the skill axis only.
    res_skill = await tool.invoke({"query": "document", "kind": "skill"}, {"agent_id": "ezri"})
    assert res_skill.output["results"]
    assert all(r["kind"] == "skill" for r in res_skill.output["results"])
    assert any(r["name"] == "document-helper" for r in res_skill.output["results"])


async def test_search_empty_query_returns_empty_no_error() -> None:
    tool = SearchCapabilitiesTool(runtime=_search_runtime())

    result = await tool.invoke({"query": "   "}, {"agent_id": "ezri"})

    assert result.error is None
    assert result.output == {"results": [], "count": 0, "message": "query required"}


async def test_search_honest_degrades_on_raising_catalog(monkeypatch) -> None:
    async def _raiser(_rt):
        raise RuntimeError("boom")

    monkeypatch.setattr("probos.routers.tools.list_capability_catalog", _raiser)
    tool = SearchCapabilitiesTool(runtime=_search_runtime())

    result = await tool.invoke({"query": "document"}, {"agent_id": "ezri"})

    # Tier-2 honest-degrade: an error ToolResult, never a raise.
    assert result.error is not None
    assert result.error.startswith("search_failed")


def test_search_tool_protocol_shape() -> None:
    tool = SearchCapabilitiesTool(runtime=SimpleNamespace())
    assert tool.tool_id == "search_capabilities"
    assert isinstance(tool.input_schema, dict)
    assert "query" in tool.input_schema["properties"]
    assert tool.tool_type is ToolType.UTILITY_AGENT


# ════════════════════════════════════════════════════════════════════════
# delegate_task
# ════════════════════════════════════════════════════════════════════════
class _Agent:
    """Minimal real agent stub (the only attributes resolve()/DelegateTaskTool read)."""

    def __init__(
        self, agent_id: str, pool: str, *, is_alive: bool = True,
        instructions: str = "", department: str = "", rank: str = "ensign",
    ) -> None:
        self.id = agent_id
        self.pool = pool
        self.is_alive = is_alive
        self.instructions = instructions
        self.department = department
        self.rank = rank


class _AgentRegistry:
    """Real small stub with the real get_by_pool / all surface (BF-287:
    surfaces an attribute typo where MagicMock would auto-fake it)."""

    def __init__(self, agents) -> None:
        self._agents = list(agents)

    def get_by_pool(self, pool_name: str) -> list:
        return [a for a in self._agents if a.pool == pool_name]

    def all(self) -> list:
        return list(self._agents)


def _callsign_registry(tmp_path, agents):
    """A REAL CallsignRegistry loaded from fixture profiles + bound to a real
    agent-registry stub (exercises the AD-1076 is_alive-gated resolve path)."""
    pdir = tmp_path / "profiles"
    pdir.mkdir(parents=True, exist_ok=True)
    for pool in {a.pool for a in agents}:
        (pdir / f"{pool}.yaml").write_text(
            f"callsign: {pool.capitalize()}\n"
            f"display_name: {pool.capitalize()}\n"
            "department: medical\n",
            encoding="utf-8",
        )
    cs = CallsignRegistry()
    cs.load_from_profiles(str(pdir))
    areg = _AgentRegistry(agents)
    cs.bind_registry(areg)
    return cs, areg


def _delegation_runtime(tmp_path, *, cs, agent_registry, extra_tools=(), agentic_tools=None):
    reg = ToolRegistry()
    for t in extra_tools:
        reg.register(t, provider="test")
    return SimpleNamespace(
        callsign_registry=cs,
        registry=agent_registry,
        tool_registry=reg,
        tool_permission_store=ToolPermissionStore(),
        intent_bus=None,
        intent_grant_store=None,
        mcp_workbench=None,
        attachment_store=_FakeAttachmentStore(),
        artifact_store=ArtifactStore(tmp_path / "artifacts.db"),
        cognitive_skill_catalog=None,
        emit_event=None,
        config=SimpleNamespace(
            execution=ExecutionConfig(enabled=False, scratch_dir=str(tmp_path / "scratch")),
            mcp=None,
            agentic_tools=agentic_tools or AgenticToolsConfig(),
        ),
    )


async def test_delegate_depth_guard_refuses_without_constructing_executor(tmp_path, monkeypatch) -> None:
    """At ``_delegation_depth == max_depth`` the tool must refuse BEFORE any
    nested executor is constructed (recursion / fan-out guard)."""

    class _CountingExecutor:
        instances = 0

        def __init__(self, **_kw):
            type(self).instances += 1

        async def run(self, **_kw):
            raise AssertionError("nested executor must not run at max depth")

    monkeypatch.setattr(
        "probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", _CountingExecutor,
    )
    cs, areg = _callsign_registry(tmp_path, [_Agent("bashir-1", "bashir")])
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg)
    tool = DelegateTaskTool(
        runtime=runtime, llm_client=_ScriptedLLM([]),
        max_depth=1, max_iterations=3, tier="standard",
    )

    result = await tool.invoke(
        {"task": "do it", "to": "bashir"},
        {"agent_id": "ezri-1", "_delegation_depth": 1},
    )

    assert result.error is None
    assert result.output == {"delegated": False, "reason": "max_delegation_depth_reached"}
    assert _CountingExecutor.instances == 0


async def test_delegate_happy_path_returns_result_and_increments_depth(tmp_path) -> None:
    cs, areg = _callsign_registry(
        tmp_path,
        [_Agent("bashir-1", "bashir", instructions="You are Dr. Bashir.",
                department="medical", rank="lieutenant")],
    )
    probe = _ProbeTool()
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg, extra_tools=[probe])
    # The nested loop (the tool's own client): probe the context, then answer.
    nested_llm = _ScriptedLLM([_tool_use("nested_probe", {}), _text("Sickbay nominal")])
    tool = DelegateTaskTool(
        runtime=runtime, llm_client=nested_llm,
        max_depth=1, max_iterations=4, tier="standard",
    )

    result = await tool.invoke(
        {"task": "check sickbay", "to": "bashir"},
        {"agent_id": "ezri-1", "thread_id": "t"},
    )

    assert result.error is None
    assert result.output["delegated"] is True
    assert result.output["to"] == "Bashir"
    assert result.output["result"] == "Sickbay nominal"
    # The nested run ran AS the target, at depth 0 + 1.
    assert probe.calls == 1
    assert probe.seen_agent_id == "bashir-1"
    assert probe.seen_depth == 1


async def test_delegate_resting_agent_still_resolves(tmp_path) -> None:
    """AD-1076: a resting (is_alive=False) crew member yields agent_id=None from
    resolve(), but the tool's get_by_pool fallback still finds the agent object."""
    cs, areg = _callsign_registry(
        tmp_path,
        [_Agent("bashir-1", "bashir", is_alive=False, instructions="You are Dr. Bashir.")],
    )
    probe = _ProbeTool()
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg, extra_tools=[probe])
    nested_llm = _ScriptedLLM([_text("Reporting in.")])
    tool = DelegateTaskTool(
        runtime=runtime, llm_client=nested_llm,
        max_depth=1, max_iterations=3, tier="standard",
    )

    result = await tool.invoke(
        {"task": "report", "to": "bashir"}, {"agent_id": "ezri-1"},
    )

    assert result.error is None
    assert result.output["delegated"] is True
    assert result.output["result"] == "Reporting in."


async def test_delegate_unknown_callsign_target_not_found(tmp_path) -> None:
    cs, areg = _callsign_registry(tmp_path, [_Agent("bashir-1", "bashir")])
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg)
    tool = DelegateTaskTool(
        runtime=runtime, llm_client=_ScriptedLLM([]),
        max_depth=1, max_iterations=3, tier="standard",
    )

    result = await tool.invoke({"task": "x", "to": "nobody"}, {"agent_id": "ezri-1"})

    assert result.error is None
    assert result.output == {"delegated": False, "reason": "target_not_found"}


async def test_delegate_non_crew_callsign_target_not_found(tmp_path) -> None:
    # The callsign registry only knows crew; a non-crew name → resolve None.
    cs, areg = _callsign_registry(tmp_path, [_Agent("bashir-1", "bashir")])
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg)
    tool = DelegateTaskTool(
        runtime=runtime, llm_client=_ScriptedLLM([]),
        max_depth=1, max_iterations=3, tier="standard",
    )

    result = await tool.invoke({"task": "x", "to": "the-warp-core"}, {"agent_id": "ezri-1"})

    assert result.error is None
    assert result.output["delegated"] is False
    assert result.output["reason"] == "target_not_found"


async def test_delegate_self_target_not_found(tmp_path) -> None:
    cs, areg = _callsign_registry(tmp_path, [_Agent("ezri-1", "ezri")])
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg)
    tool = DelegateTaskTool(
        runtime=runtime, llm_client=_ScriptedLLM([]),
        max_depth=1, max_iterations=3, tier="standard",
    )

    # ezri-1 tries to delegate to the "ezri" callsign, which resolves to itself.
    result = await tool.invoke({"task": "x", "to": "ezri"}, {"agent_id": "ezri-1"})

    assert result.error is None
    assert result.output == {"delegated": False, "reason": "target_not_found"}


async def test_delegate_missing_task_or_to_degrades(tmp_path) -> None:
    cs, areg = _callsign_registry(tmp_path, [_Agent("bashir-1", "bashir")])
    runtime = _delegation_runtime(tmp_path, cs=cs, agent_registry=areg)
    tool = DelegateTaskTool(
        runtime=runtime, llm_client=_ScriptedLLM([]),
        max_depth=1, max_iterations=3, tier="standard",
    )

    no_task = await tool.invoke({"task": "  ", "to": "bashir"}, {"agent_id": "ezri-1"})
    no_to = await tool.invoke({"task": "do it", "to": ""}, {"agent_id": "ezri-1"})

    for r in (no_task, no_to):
        assert r.error is None
        assert r.output == {"delegated": False, "reason": "task_and_to_required"}


def test_delegate_tool_protocol_shape() -> None:
    tool = DelegateTaskTool(
        runtime=SimpleNamespace(), llm_client=None,
        max_depth=1, max_iterations=5, tier="standard",
    )
    assert tool.tool_id == "delegate_task"
    assert isinstance(tool.input_schema, dict)
    assert set(tool.input_schema["required"]) == {"task", "to"}
    assert tool.tool_type is ToolType.UTILITY_AGENT


# ════════════════════════════════════════════════════════════════════════
# registration gating in WorkItemAgenticExecutor.run
# ════════════════════════════════════════════════════════════════════════
def _registration_runtime(tmp_path, *, agentic_tools) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(enabled=False, scratch_dir=str(tmp_path / "scratch")),
            mcp=None,
            agentic_tools=agentic_tools,
        ),
        tool_registry=ToolRegistry(),
        tool_permission_store=ToolPermissionStore(),
        intent_bus=None,
        intent_grant_store=None,
        mcp_workbench=None,
        attachment_store=_FakeAttachmentStore(),
        artifact_store=ArtifactStore(tmp_path / "artifacts.db"),
        cognitive_skill_catalog=None,
        emit_event=None,
    )


async def test_registration_both_flags_off_registers_neither(tmp_path) -> None:
    runtime = _registration_runtime(tmp_path, agentic_tools=AgenticToolsConfig())  # defaults OFF
    llm = _ScriptedLLM([_text("ok")])
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="ezri", instructions="You are Ezri.", task_text="hi",
        runtime=runtime, thread_id="t", max_iterations=2,
    )

    assert outcome.final_text == "ok"
    # Neither tool registered, neither offered (byte-identical to the AD-1068 set).
    assert runtime.tool_registry.get("search_capabilities") is None
    assert runtime.tool_registry.get("delegate_task") is None
    offered = _tool_names(llm.last_tools)
    assert "search_capabilities" not in offered
    assert "delegate_task" not in offered


async def test_registration_flags_on_registers_each_once_idempotent(tmp_path) -> None:
    runtime = _registration_runtime(
        tmp_path,
        agentic_tools=AgenticToolsConfig(tool_search_enabled=True, delegation_enabled=True),
    )
    llm1 = _ScriptedLLM([_text("first")])
    await WorkItemAgenticExecutor(llm_client=llm1).run(
        agent_id="ezri", instructions="You are Ezri.", task_text="hi",
        runtime=runtime, thread_id="t", max_iterations=2,
    )

    assert runtime.tool_registry.get("search_capabilities") is not None
    assert runtime.tool_registry.get("delegate_task") is not None
    offered1 = _tool_names(llm1.last_tools)
    assert "search_capabilities" in offered1
    assert "delegate_task" in offered1
    reg_search = runtime.tool_registry.get("search_capabilities")
    reg_delegate = runtime.tool_registry.get("delegate_task")

    # A second run on the same registry must NOT re-register (idempotent).
    llm2 = _ScriptedLLM([_text("second")])
    await WorkItemAgenticExecutor(llm_client=llm2).run(
        agent_id="ezri", instructions="You are Ezri.", task_text="hi again",
        runtime=runtime, thread_id="t", max_iterations=2,
    )

    assert runtime.tool_registry.get("search_capabilities") is reg_search
    assert runtime.tool_registry.get("delegate_task") is reg_delegate


# ════════════════════════════════════════════════════════════════════════
# end-to-end: parent loop → delegate_task → nested governed executor → back
# ════════════════════════════════════════════════════════════════════════
async def test_loop_delegate_task_runs_nested_executor_and_returns_into_transcript(tmp_path) -> None:
    """THE AD-1072 HEADLINE: a scripted parent loop emits a ``delegate_task``
    call → a nested governed ``WorkItemAgenticExecutor`` runs the target agent →
    its result returns into the parent transcript."""
    cs, areg = _callsign_registry(
        tmp_path,
        [_Agent("bashir-1", "bashir", instructions="You are Dr. Bashir.",
                department="medical", rank="lieutenant")],
    )
    probe = _ProbeTool()
    runtime = _delegation_runtime(
        tmp_path, cs=cs, agent_registry=areg, extra_tools=[probe],
        agentic_tools=AgenticToolsConfig(delegation_enabled=True),
    )
    # One scripted LLM drives BOTH the parent loop and (since the delegate tool
    # is registered with self._llm) the nested loop, in pop order.
    parent_llm = _ScriptedLLM([
        _tool_use("delegate_task", {"task": "check sickbay", "to": "bashir"}),  # parent
        _tool_use("nested_probe", {}),                                          # nested
        _text("Sickbay nominal"),                                              # nested final
        _text("Captain, Bashir reports sickbay nominal."),                    # parent final
    ])
    executor = WorkItemAgenticExecutor(llm_client=parent_llm)

    outcome = await executor.run(
        agent_id="ezri-1",
        instructions="You are Ezri.",
        task_text="ask bashir to check sickbay",
        runtime=runtime,
        department="counseling",
        rank="lieutenant",
        thread_id="thread-deleg",
        max_iterations=6,
    )

    # The delegated result flowed back into the parent's final answer.
    assert outcome.final_text == "Captain, Bashir reports sickbay nominal."
    assert "delegate_task" in _tool_names(parent_llm.last_tools)
    # The nested governed executor ran AS bashir, at delegation depth 1.
    assert probe.calls == 1
    assert probe.seen_agent_id == "bashir-1"
    assert probe.seen_depth == 1
