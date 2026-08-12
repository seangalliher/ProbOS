"""BF-754: an MCP adapter the provider will actually accept, with its contract.

Code review of BF-753 found three defects that sat directly behind it. BF-753
restored the workbench; these would have broken the very first turn that used it.

**The name.** ``_McpTool.tool_id`` is ``mcp:{server}:{tool}``, and
``tool_registration_to_llm_definition`` copied ``tool.tool_id`` into the LLM
function name verbatim. OpenAI-compatible providers accept
``^[A-Za-z0-9_-]{1,64}$``. Probed against the live Copilot proxy:

    valid_docs_search                        -> HTTP 200, valid tool call
    mcp:microsoft-learn:microsoft_docs_search -> HTTP 500,
        "only alphanumeric characters, hyphens, and underscores are allowed"

That fails the WHOLE request, not just the offending tool -- so the first turn
that preloaded an MCP adapter would have broken the agent's entire turn. Every
built-in tool id happens to be legal, which is why this survived unnoticed.

**The contract.** ``_enumerate_tools`` kept only name and description, and
registration hardcoded ``{"type": "object"}``. The live Microsoft Learn server
advertises ``query`` (required), ``url`` (required), ``language`` (optional).
The model was told the tools existed and never told what to pass them.

**The cost.** ``pull_tool`` re-enumerated the server on every pull, so a preload
of N tools across S servers cost S+N ``tools/list`` round trips per agentic
turn -- 25 for one server at the default limit of 24.

Sanitising alone is not enough for the name: ``a:b`` and ``a_b`` both become
``a_b``. The alias therefore carries a digest of the canonical id.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.mcp_workbench import (
    MCPWorkbench,
    _safe_description,
    _safe_input_schema,
)
from probos.cognitive.swe_harness.tool_call import (
    dedupe_llm_definitions,
    llm_function_name,
    resolve_llm_function_name,
    tool_registration_to_llm_definition,
)
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolType
from probos.tools.registry import ToolRegistry

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")
# BF-757: no anchors + fullmatch. This oracle was written as ``^...$`` with
# ``.match``, which is the exact bug it exists to catch -- ``$`` also matches
# before a trailing newline, so it would have vouched for "browser\n".
_PROVIDER_LEGAL = __import__("re").compile(r"[A-Za-z0-9_-]{1,64}")


# ---------------------------------------------------------------------------
# The name
# ---------------------------------------------------------------------------

def test_an_mcp_tool_id_is_not_a_legal_function_name() -> None:
    """The premise, stated so the rest of this file has a reason to exist."""
    assert not _PROVIDER_LEGAL.fullmatch("mcp:microsoft-learn:microsoft_docs_search")


def test_the_alias_is_legal_for_the_provider() -> None:
    name = llm_function_name("mcp:microsoft-learn:microsoft_docs_search")

    assert _PROVIDER_LEGAL.fullmatch(name), name


@pytest.mark.parametrize(
    "tool_id",
    [
        "mcp:microsoft-learn:microsoft_docs_search",
        "mcp:a:b",
        "mcp:" + "x" * 200 + ":y",
        "mcp::",
        ":::",
    ],
)
def test_every_alias_is_legal_and_bounded(tool_id: str) -> None:
    name = llm_function_name(tool_id)

    assert _PROVIDER_LEGAL.fullmatch(name), f"{tool_id!r} -> {name!r}"
    assert len(name) <= 64


def test_a_legal_id_is_left_alone() -> None:
    """Every built-in tool must keep the exact name it has always had, or this
    fix silently renames the whole toolset."""
    for tool_id in ("browser", "http_fetch", "run_python", "find_mcp_tool"):
        assert llm_function_name(tool_id) == tool_id


def test_the_alias_is_stable_across_calls() -> None:
    """The model may see the name across turns; it must not drift."""
    a = llm_function_name("mcp:microsoft-learn:microsoft_docs_search")
    b = llm_function_name("mcp:microsoft-learn:microsoft_docs_search")

    assert a == b


def test_ids_that_sanitise_alike_do_not_collide() -> None:
    """Replacing colons alone would map both of these to the same name, and one
    tool would silently invoke the other."""
    assert llm_function_name("mcp:a:b") != llm_function_name("mcp_a_b")
    assert llm_function_name("mcp:a_b") != llm_function_name("mcp_a:b")


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

def test_a_returned_alias_maps_back_to_the_canonical_id() -> None:
    canonical = "mcp:microsoft-learn:microsoft_docs_search"
    offered = ["browser", canonical, "http_fetch"]

    assert resolve_llm_function_name(llm_function_name(canonical), offered) == canonical


def test_an_ambiguous_name_resolves_to_nothing_rather_than_guessing() -> None:
    """BF-757 REPLACED this assertion. It read "a real tool named like another's
    alias must still resolve to itself" and asserted the exact id won.

    Writing the inverse (alias wins) made it fail, which is the useful part:
    neither is decidable here. dedupe_llm_definitions keeps the FIRST of two
    colliding names, so which tool the model was actually shown depends on the
    order they were OFFERED in -- and this function only receives a list of ids.
    Guessing either way silently invokes a tool the model never saw, so an
    ambiguous name is refused and the caller keeps its not-found path.
    """
    canonical = "mcp:a:b"
    alias = llm_function_name(canonical)

    assert resolve_llm_function_name(alias, [alias, canonical]) is None
    assert resolve_llm_function_name(alias, [canonical, alias]) is None, (
        "the reversed order must not change the answer either"
    )


def test_an_unambiguous_alias_still_resolves() -> None:
    """The refusal above must not cost the ordinary case -- which is every real
    MCP tool, none of which collide."""
    canonical = "mcp:a:b"

    assert resolve_llm_function_name(
        llm_function_name(canonical), ["browser", canonical]
    ) == canonical


def test_an_id_the_provider_accepts_still_resolves_to_itself() -> None:
    """BF-757: an id that needs no alias is its own alias, so it still resolves
    to itself and is NOT treated as self-ambiguous."""
    assert resolve_llm_function_name("browser", ["browser", "http_fetch"]) == "browser"


def test_a_trailing_newline_is_not_passed_through(caplog) -> None:
    """BF-757: ``re.match`` with ``$`` also matches before a trailing newline,
    so ``"browser\\n"`` was handed to the provider verbatim -- HTTP 500, whole
    request. ``fullmatch`` sends it down the alias path instead."""
    assert llm_function_name("browser\n") != "browser\n"
    assert "\n" not in llm_function_name("browser\n")


def test_the_digest_is_wide_enough_to_resist_collision() -> None:
    """BF-757: 8 hex is 32 bits and a real collision was found by scanning
    117,239 candidate ids. Two tools under one name is HTTP 500 "Tool names
    must be unique" -- again fatal to the whole request."""
    from probos.cognitive.swe_harness.tool_call import _LLM_DIGEST_LEN

    assert _LLM_DIGEST_LEN >= 16


def test_an_unknown_name_resolves_to_nothing() -> None:
    """None, not a guess -- the caller keeps its own not-found path."""
    assert resolve_llm_function_name("no_such_tool", ["browser"]) is None


@pytest.mark.asyncio
async def test_the_executor_accepts_the_alias_the_model_was_shown() -> None:
    """The crossing test: definition out, alias back, canonical tool invoked."""
    from probos.tools.executor import ToolExecutor

    class _Tool:
        tool_id = "mcp:echo:echo"
        name = "Echo"
        description = "echo back arguments"
        input_schema = {"type": "object"}
        output_schema = {"type": "object"}
        tool_type = None

    registry = ToolRegistry()
    calls: list[str] = []

    class _Registry:
        def get(self, tool_id: str) -> Any:
            return object() if tool_id == "mcp:echo:echo" else None

        def list_ids(self) -> list[str]:
            return ["browser", "mcp:echo:echo"]

        async def check_and_invoke(
            self, agent_id: str, tool_id: str, params: dict, **kwargs: Any
        ) -> Any:
            calls.append(tool_id)
            from probos.tools.protocol import ToolResult

            return ToolResult(output={"ok": True})

    executor = ToolExecutor(registry=_Registry())
    alias = llm_function_name("mcp:echo:echo")
    assert alias != "mcp:echo:echo"

    await executor.invoke(agent_id="a1", tool_id=alias, params={"q": "hi"})

    assert calls == ["mcp:echo:echo"], (
        "the alias never resolved back, so the model's call reached nothing"
    )
    assert registry.list_ids() == []  # the real registry was untouched


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

def test_a_declared_schema_survives() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    assert _safe_input_schema(schema, "s", "t") == schema


@pytest.mark.parametrize(
    "raw",
    [None, "not a dict", {"type": "array"}, {"type": "object", "properties": []}],
)
def test_an_unusable_schema_falls_back_without_losing_the_tool(raw: Any) -> None:
    """Falling back keeps the tool callable -- the model just infers arguments,
    which is exactly where we were before."""
    assert _safe_input_schema(raw, "s", "t") == {"type": "object"}


def test_a_hostile_schema_is_bounded() -> None:
    """Remote input that goes straight into an LLM request. A broken or hostile
    server must not be able to blow up the prompt."""
    huge = {
        "type": "object",
        "properties": {f"p{i}": {"type": "string"} for i in range(500)},
    }

    assert _safe_input_schema(huge, "s", "t") == {"type": "object"}


def test_a_schema_too_large_in_bytes_is_bounded() -> None:
    fat = {
        "type": "object",
        "properties": {"q": {"type": "string", "description": "x" * 20_000}},
    }

    assert len(json.dumps(fat)) > 16_384
    assert _safe_input_schema(fat, "s", "t") == {"type": "object"}


# ---------------------------------------------------------------------------
# End to end against the real echo server
# ---------------------------------------------------------------------------

async def _stub_consensus(server_url: str, tool: str, args: dict) -> dict:
    return {"committed": True, "invoke_result": {"ok": 1}, "consensus": None}


class _CountingBridge(MCPBridge):
    def __init__(self) -> None:
        super().__init__(
            request_timeout=5.0, stdio_enabled=True,
            command_allowlist=[sys.executable],
        )
        self.list_tools_calls = 0

    def get_client(self, server_url: str) -> Any:
        client = super().get_client(server_url)
        if client is None:
            return None
        outer = self

        class _Counting:
            def __getattr__(self, item: str) -> Any:
                return getattr(client, item)

            async def list_tools(self) -> list[dict]:
                outer.list_tools_calls += 1
                return await client.list_tools()

        return _Counting()


@pytest.fixture
async def env(tmp_path):
    bridge = _CountingBridge()
    assert await bridge.register_stdio_server(
        name="echo", command=sys.executable, args=[FIXTURE], env={}, cwd="",
        timeout=5.0,
    ) is True
    server_store = McpServerStore(db_path=str(tmp_path / "srv.db"))
    await server_store.start()
    await server_store.create(
        McpServerRecord(
            name="echo", type="stdio", command=sys.executable,
            args=[FIXTURE], default_risk="open",
        )
    )
    perm_store = ToolPermissionStore(db_path=str(tmp_path / "perm.db"))
    await perm_store.start()
    await perm_store.issue_grant("a1", "mcp:echo", permission=ToolPermission.WRITE)
    registry = ToolRegistry()
    wb = MCPWorkbench(
        tool_registry=registry, bridge=bridge, consensus_invoke=_stub_consensus,
        episode_writer=None, server_store=server_store, perm_store=perm_store,
        dept_grant_store=None, risk_store=None, ontology=None, agent_registry=None,
    )
    yield types.SimpleNamespace(
        bridge=bridge, registry=registry, wb=wb,
        server_store=server_store, perm_store=perm_store,
    )
    await bridge.close_all()
    await server_store.stop()
    await perm_store.stop()


@pytest.mark.asyncio
async def test_the_offered_definition_is_callable_and_carries_its_schema(env) -> None:
    """The whole point: what reaches the provider must be acceptable to it AND
    tell the model what to send."""
    pulled = await env.wb.preload_open_tools("a1", limit=24)
    assert "mcp:echo:echo" in pulled

    definition = tool_registration_to_llm_definition(env.registry.get("mcp:echo:echo"))
    fn = definition["function"]

    assert _PROVIDER_LEGAL.fullmatch(fn["name"]), fn["name"]
    assert fn["parameters"]["required"] == ["q"]
    assert "q" in fn["parameters"]["properties"]


@pytest.mark.asyncio
async def test_preloading_enumerates_each_server_once(env) -> None:
    """Was S+N round trips per turn; the descriptor from the initial
    enumeration is now carried into registration."""
    env.bridge.list_tools_calls = 0

    await env.wb.preload_open_tools("a1", limit=24)

    assert env.bridge.list_tools_calls == 1, (
        f"{env.bridge.list_tools_calls} tools/list calls for one server"
    )


# ---------------------------------------------------------------------------
# BF-757: the schema must be VALID, not merely small
#
# Each shape below was sent to the live Copilot proxy at 127.0.0.1:8080. Each
# returned HTTP 500 and failed the WHOLE request -- every other tool in the
# same turn went down with it. The BF-754 pass checked size and called that
# validation, so all of these were forwarded verbatim.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad, why",
    [
        ({"type": "object", "required": "q"},
         "required: Input should be a valid array"),
        ({"type": "object", "properties": {"q": "not-a-schema"}},
         "JSON schema is invalid"),
        ({"type": "object", "properties": {"q": {"description": 7}}},
         "a non-string description"),
        ({"type": "object", "properties": {"q": {"type": "bogus"}}},
         "a type outside the seven simple types"),
        ({"type": "object", "required": ["q", 7]},
         "a non-string entry in required"),
        ({"type": "object", "properties": {"q": {"enum": "ab"}}},
         "a non-list enum"),
        ({"type": "object", "properties": {"q": {"oneOf": []}}},
         "an empty oneOf"),
        ({"type": "object", "additionalProperties": "nope"},
         "additionalProperties that is neither schema nor boolean"),
        ({"type": "object", "properties": {"q": {"minimum": "zero"}}},
         "a non-numeric minimum"),
        ({"type": "object", "properties": {"q": {"format": 7}}},
         "a non-string format"),
    ],
)
def test_an_invalid_schema_degrades_to_the_permissive_fallback(bad, why) -> None:
    assert _safe_input_schema(bad, "srv", "t") == {"type": "object"}, why


@pytest.mark.parametrize(
    "good, why",
    [
        ({"type": "object",
          "properties": {"q": {"$ref": "#/$defs/x"}},
          "$defs": {"x": {"type": "string"}}},
         "$defs plus a local $ref"),
        ({"type": "object", "properties": {"q": {"type": "array", "items": True}}},
         "boolean items"),
        ({"type": "object", "properties": {"q": {"type": ["string", "null"]}}},
         "a nullable union"),
        ({"type": "object",
          "properties": {"q": {"type": "array",
                               "items": {"type": "object",
                                         "properties": {"n": {"type": "integer"}}}}}},
         "nested arrays of objects"),
        ({"type": "object", "properties": {"q": {"type": "string", "format": "uri"}}},
         "format"),
    ],
)
def test_a_valid_schema_the_provider_accepts_is_not_stripped(good, why) -> None:
    """BF-757 re-review: the first hand-rolled walk REJECTED every shape here,
    all of which the live proxy answers HTTP 200. A false rejection silently
    costs a well-behaved server its parameters -- the exact failure BF-754
    existed to fix, reintroduced by the fix for it."""
    assert _safe_input_schema(good, "srv", "t") == good, why


def test_a_deeply_nested_schema_is_kept_because_the_provider_keeps_it() -> None:
    """Also inverted by re-review. The hand-rolled walk capped depth at 8; the
    proxy accepted 80 levels. The cap that matters is bytes, which is measured
    against what actually reaches the wire."""
    node: dict[str, Any] = {"type": "string"}
    for _ in range(40):
        node = {"type": "object", "properties": {"n": node}}

    assert _safe_input_schema(node, "srv", "t") == node


def test_a_valid_schema_is_still_passed_through_untouched() -> None:
    good = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "what to search for"},
            "limit": {"type": ["integer", "null"]},
            "mode": {"type": "string", "enum": ["fast", "deep"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
    }

    assert _safe_input_schema(good, "srv", "t") == good


def test_a_nan_schema_does_not_serialise_into_the_request() -> None:
    """json.dumps emits a bare ``NaN`` by default, which is not JSON. It would
    serialise here and die at the provider."""
    assert _safe_input_schema(
        {"type": "object", "properties": {"q": {"default": float("nan")}}},
        "srv", "t",
    ) == {"type": "object"}


def test_an_oversized_schema_is_refused() -> None:
    fat = {
        "type": "object",
        "properties": {f"p{i}": {"type": "string", "description": "x" * 400}
                       for i in range(40)},
    }
    assert len(json.dumps(fat)) > 16_384

    assert _safe_input_schema(fat, "srv", "t") == {"type": "object"}


def test_the_returned_schema_is_always_plain_json_data() -> None:
    """BF-757 re-review found the real bound. ``isinstance(x, dict)`` admits
    subclasses; one that serialises as ``{}`` while its ``get`` synthesises
    250,000 nodes made the previous walk visit all of them. Round-tripping
    through json is what bounds the work, and the returned object must be the
    plain result -- never the caller's object."""

    class _Hostile(dict):
        def get(self, key, default=None):  # noqa: D102
            if key == "properties":
                return {f"p{i}": {"type": "string"} for i in range(250_000)}
            return super().get(key, default)

    hostile = _Hostile({"type": "object"})
    out = _safe_input_schema(hostile, "srv", "t")

    assert type(out) is dict, "a subclass must never be handed onward"
    assert not isinstance(out, _Hostile)
    assert len(json.dumps(out)) < 1_000, "the synthesised nodes must not appear"


# ---------------------------------------------------------------------------
# BF-757: a duplicated function name is fatal to the whole request
# ---------------------------------------------------------------------------

def test_two_tools_offered_under_one_name_lose_only_the_later_one() -> None:
    """The provider answers HTTP 500 "Tool names must be unique" and drops the
    ENTIRE request, so a collision would cost the agent every tool, not one."""
    from probos.cognitive.swe_harness.tool_call import dedupe_llm_definitions

    defs = [
        {"function": {"name": "alpha"}},
        {"function": {"name": "beta"}},
        {"function": {"name": "alpha", "description": "the collision"}},
    ]

    kept = dedupe_llm_definitions(defs, agent_id="a1")

    assert [d["function"]["name"] for d in kept] == ["alpha", "beta"]
    assert kept[0]["function"].get("description") is None, "first occurrence wins"


def test_dedupe_leaves_a_collision_free_toolset_byte_identical() -> None:
    defs = [{"function": {"name": n}} for n in ("browser", "http_fetch", "run_python")]

    assert dedupe_llm_definitions(defs, agent_id="a1") == defs


# ---------------------------------------------------------------------------
# BF-757: the description is remote input on the same path
# ---------------------------------------------------------------------------

def test_a_non_string_description_never_reaches_the_provider() -> None:
    assert _safe_description({"nested": "dict"}) == ""
    assert _safe_description(None) == ""
    assert _safe_description(7) == ""


def test_a_huge_description_is_bounded() -> None:
    """24 tools advertising 100 KB descriptions rendered a 2,788,502-byte tool
    block (~697k tokens) -- past the context window, so the turn dies before it
    begins."""
    out = _safe_description("x" * 100_000)

    assert len(out) < 5_000
    assert out.startswith("x")


def test_an_ordinary_description_is_untouched() -> None:
    assert _safe_description("Search Microsoft Learn.") == "Search Microsoft Learn."


# ---------------------------------------------------------------------------
# BF-757 CROSSING TESTS
#
# The first BF-757 pass had none, and re-review proved it: under line tracing
# all 43 tests passed while NEITHER dedupe call site executed, so deleting the
# wiring left the file green. Every test below crosses a seam -- helper to the
# component that has to use it -- rather than exercising the helper alone.
# ---------------------------------------------------------------------------

def test_a_natural_alias_collision_is_no_longer_reachable() -> None:
    """The pair below collided under the 8-hex digest and was found by scanning
    117,239 ids. At 16 hex it does not, which is the point of widening it --
    dedupe is the backstop, not the primary defence."""
    stem = "mcp:" + "a" * 80

    assert llm_function_name(f"{stem}:82537") != llm_function_name(f"{stem}:117239")


class _NamedTool:
    tool_type = ToolType.MCP_SERVER
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        self.name = tool_id
        self.description = f"tool {tool_id}"
        self.input_schema: dict[str, Any] = {"type": "object"}
        self.invoked = False

    async def invoke(self, params: dict, context: dict | None = None):
        from probos.tools.protocol import ToolResult

        self.invoked = True
        return ToolResult(output={"ran": self.tool_id})


def test_the_dispatch_module_applies_dedupe_to_the_offered_tools() -> None:
    """CROSSING: pins that the assembled offer is passed THROUGH dedupe before
    it reaches AgenticLoop. BF-755 moved the assembly into a ``_build_tools``
    closure so the same code can run again mid-turn; this repointed with it,
    and now also pins that dedupe is INSIDE that one builder -- so the refresh
    path cannot bypass it."""
    import inspect

    from probos.cognitive import agentic_dispatch as ad

    source = inspect.getsource(ad)
    start = source.index("def _build_tools(")
    builder = source[start:source.index("tools = _build_tools(")]

    assert "return dedupe_llm_definitions(built, agent_id=agent_id)" in builder, (
        "the offer must dedupe; a duplicate name makes the provider reject the "
        "whole request"
    )
    assert builder.index("built.append(definition)") < builder.index(
        "return dedupe_llm_definitions("
    )


def test_the_build_harness_applies_dedupe_to_its_tools() -> None:
    """CROSSING: the second wiring site, same requirement."""
    import inspect

    from probos.cognitive.swe_harness import native_builder

    source = inspect.getsource(
        native_builder.NativeBuilderHarness._select_build_tools
    )

    assert "dedupe_llm_definitions(defs" in source


@pytest.mark.asyncio
async def test_the_executor_refuses_an_ambiguous_name_and_invokes_nothing() -> None:
    """CROSSING, and the finding that mattered most: the refusal lived in the
    helper while ``_resolve_tool_id`` short-circuited past it on an exact
    match, then turned ``None`` back into the colliding id. Measured, the model
    was shown one tool's definition and the executor ran the other."""
    from probos.tools.executor import ToolExecutor

    canonical = "mcp:a:b"
    alias = llm_function_name(canonical)
    registry = ToolRegistry()
    aliased_tool, exact_tool = _NamedTool(canonical), _NamedTool(alias)
    registry.register(aliased_tool)
    registry.register(exact_tool)

    result = await ToolExecutor(registry=registry).invoke("a1", alias, {})

    assert result.error is not None and "ambiguous" in result.error
    assert not aliased_tool.invoked and not exact_tool.invoked, (
        "refusing means invoking NEITHER -- picking one runs a tool the model "
        "may never have been offered"
    )


@pytest.mark.asyncio
async def test_the_executor_still_resolves_an_unambiguous_alias() -> None:
    """The refusal must not cost the ordinary case, which is every real MCP
    tool -- none of which collide."""
    from probos.tools.executor import ToolExecutor

    registry = ToolRegistry()
    tool = _NamedTool("mcp:a:b")
    registry.register(tool)

    result = await ToolExecutor(registry=registry).invoke(
        "a1", llm_function_name("mcp:a:b"), {}
    )

    assert result.error is None, result.error
    assert tool.invoked


@pytest.mark.asyncio
async def test_enumeration_applies_the_guards_not_just_the_helpers(env) -> None:
    """CROSSING: the description/name guards must run inside ``_enumerate_tools``.
    Calling ``_safe_description`` directly proves nothing about the pull path."""
    record = McpServerRecord(
        name="echo", type="stdio", command=sys.executable, args=[FIXTURE],
        default_risk="open",
    )

    async def _hostile_list_tools() -> list[dict]:
        return [
            {"name": "good", "description": "fine", "inputSchema": {"type": "object"}},
            {"name": "fat", "description": "x" * 100_000, "inputSchema": {}},
            {"name": "dict_desc", "description": {"not": "a string"}},
            {"name": "bad_schema", "description": "d",
             "inputSchema": {"type": "object", "required": "q"}},
            {"name": 7, "description": "non-string name"},
            {"name": "", "description": "empty name"},
        ]

    env.bridge.get_client = lambda url: types.SimpleNamespace(
        list_tools=_hostile_list_tools
    )
    tools = await env.wb._enumerate_tools(record)

    by_name = {t["name"]: t for t in tools}
    assert set(by_name) == {"good", "fat", "dict_desc", "bad_schema"}, (
        "a tool with a non-string or empty name is unusable and must be dropped"
    )
    assert all(isinstance(t["description"], str) for t in tools)
    assert by_name["dict_desc"]["description"] == ""
    assert len(by_name["fat"]["description"]) < 5_000
    assert by_name["bad_schema"]["input_schema"] == {"type": "object"}
    assert by_name["good"]["input_schema"] == {"type": "object"}
