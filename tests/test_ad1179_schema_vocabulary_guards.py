"""AD-1179: generic drift guards over the whole registered tool surface.

BF-701 and BF-706 were the same defect twice: a vocabulary declared in several
places, one of which is the executable gate, where the two silently disagree and
the agent is the one who finds out. BF-867 was the third — one layer further
down, inside a handler, on a parameter the schema never declared.

Five browser drift guards already exist and all five missed BF-867, for one
reason: **every one of them compares a top-level ``input_schema`` enum against
the handler map.** A handler's own private parameter vocabulary is invisible to
that shape. G2 below is written specifically to close that class.

What each guard catches, and what it does not — stated without rounding up:

* **(a) an enum value the handler rejects** — caught. G1 forces the schema and
  the gate to read one constant, so they cannot differ.
* **(b) a handler branch with no enum value** — *prevented, not detected*. There
  is deliberately no "every handler must be offered" rule: ``_HANDLERS``
  registers twenty verbs, sixteen are agent-facing, and ``test_bf706`` enforces
  that the other four stay off. The residual gap — a verb added to ``_HANDLERS``
  and to neither vocabulary — stays invisible, by design.
* **(c) a required parameter the handler ignores** — caught by G3 within the
  coverage set G3 enumerates by name.
* **(d) a parameter the handler requires that the schema omits** — caught by G3,
  plus G2 for the dispatch-key special case that shipped BF-867.

Every guard carries a negative control. A guard that passes on a clean tree and
would also pass on a broken one proves nothing, and this repository has shipped
that shape more than once.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

import pytest

from tests.test_ad1179_tool_schema_golden import (
    EXPECTED_TOOL_IDS,
    build_pinned_instances,
)

# ══ shared AST scanners ═══════════════════════════════════════════
# Factored out so each guard can be driven against deliberately-broken synthetic
# source in its own negative control.


_DERIVING_CALLS = frozenset({"list", "tuple", "sorted"})


def enum_nodes_in(source: str, class_name: str) -> list[tuple[int, ast.AST]]:
    """Every ``enum`` value node inside ``class_name``'s ``input_schema``.

    Walks the whole ``input_schema`` subtree, so a nested enum (``items.enum``,
    a ``oneOf`` branch) is covered as well as a top-level property.
    """
    tree = ast.parse(textwrap.dedent(source))
    target: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            target = node
            break
    if target is None:
        raise AssertionError(f"class {class_name} not found in source")

    schemas: list[ast.AST] = []
    for member in target.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if member.name == "input_schema":
                schemas.append(member)
        elif isinstance(member, ast.AnnAssign):
            if isinstance(member.target, ast.Name) and member.target.id == "input_schema":
                if member.value is not None:
                    schemas.append(member.value)
        elif isinstance(member, ast.Assign):
            for tgt in member.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "input_schema":
                    schemas.append(member.value)

    found: list[tuple[int, ast.AST]] = []
    for schema in schemas:
        for node in ast.walk(schema):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "enum":
                    found.append((getattr(value, "lineno", 0), value))
    return found


def classify_enum_node(node: ast.AST) -> str:
    """``"derived"`` when the enum reads a named constant, else ``"literal"``.

    Accepted derived forms, both already proven in this repository:

    * ``list(_SOME_TUPLE)`` / ``tuple(...)`` / ``sorted(...)`` over a Name or
      Attribute — the ``_AGENT_ACTIONS`` pattern.
    * ``[*SOME_TUPLE, "extra"]`` — the ``oracle.kind`` / ``SIGMA_TIERS`` pattern.

    Anything else fails closed: an unrecognised shape is reported as a literal
    rather than waved through, because the point of the guard is that a
    hand-typed vocabulary is refused at review time instead of at runtime.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in _DERIVING_CALLS and len(node.args) == 1:
            if isinstance(node.args[0], (ast.Name, ast.Attribute)):
                return "derived"
    if isinstance(node, ast.List):
        for element in node.elts:
            if isinstance(element, ast.Starred) and isinstance(
                element.value, (ast.Name, ast.Attribute)
            ):
                return "derived"
    return "literal"


def reads_dispatch_key(source: str, key: str = "action") -> list[int]:
    """Line numbers where ``params`` is read for ``key``.

    ``params.get("action")``, ``params["action"]`` and ``params.pop("action")``
    all count. This is BF-867's exact shape: ``tool.py`` reads the dispatch key
    out of ``params`` without removing it and forwards the same dict, so a
    handler reading that key gets the verb's own name, never a sub-verb.
    """
    tree = ast.parse(textwrap.dedent(source))
    hits: list[int] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "params"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == key
        ):
            hits.append(node.lineno)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "params"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == key
        ):
            hits.append(node.lineno)
    return sorted(hits)


def params_keys_read(source: str, param: str = "params") -> set[str]:
    """String keys read directly off the ``params`` argument.

    Alias-tracked one hop (``p = params or {}``) so the common
    ``(params or {}).get("x")`` and its bound form are both seen. Result and
    context dicts are deliberately not followed — they are a different dict and
    counting them would manufacture false undeclared keys.
    """
    tree = ast.parse(textwrap.dedent(source))
    aliases = {param}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            if isinstance(value, ast.Name) and value.id in aliases:
                aliases.add(target.id)
            elif isinstance(value, ast.BoolOp) and any(
                isinstance(v, ast.Name) and v.id in aliases for v in value.values
            ):
                aliases.add(target.id)
            elif isinstance(value, ast.IfExp) and any(
                isinstance(v, ast.Name) and v.id in aliases
                for v in (value.body, value.orelse)
            ):
                # ``raw = params if type(params) is dict else {}`` is a real
                # shape in this tree. Without this branch the scanner reports
                # an EMPTY key set for such a tool, which reads exactly like
                # "declares nothing undeclared" -- a guard that passes because
                # it is blind is worse than no guard.
                aliases.add(target.id)

    def rooted_in_params(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in aliases
        if isinstance(node, ast.BoolOp):
            return any(rooted_in_params(v) for v in node.values)
        if isinstance(node, ast.IfExp):
            return rooted_in_params(node.body) or rooted_in_params(node.orelse)
        return False

    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "pop")
            and rooted_in_params(node.func.value)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
        if (
            isinstance(node, ast.Subscript)
            and rooted_in_params(node.value)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            keys.add(node.slice.value)
    return keys


def _tools_by_id() -> dict[str, Any]:
    return {tool.tool_id: tool for tool in build_pinned_instances()}


# ══ G1 — every schema enum reads a named constant ═════════════════


@pytest.mark.parametrize("tool_id", sorted(EXPECTED_TOOL_IDS))
def test_g1_no_schema_enum_is_a_hand_typed_literal(tool_id: str) -> None:
    """The assertion that makes a future hand-typed enum fail at review time
    instead of at runtime, one agent turn later."""
    tool = _tools_by_id()[tool_id]
    cls = type(tool)
    source = inspect.getsource(inspect.getmodule(cls))
    literals = [
        (lineno, ast.dump(node))
        for lineno, node in enum_nodes_in(source, cls.__name__)
        if classify_enum_node(node) == "literal"
    ]
    assert not literals, (
        f"{tool_id}: schema enum written as a literal rather than read from a "
        f"named constant: {literals}"
    )


def test_g1_covers_the_tools_that_actually_declare_an_enum() -> None:
    """Premise assertion. If the scanner stops matching production, every
    parametrized case above passes on an empty list and the guard is silently
    doing nothing."""
    with_enums = set()
    for tool_id, tool in _tools_by_id().items():
        cls = type(tool)
        source = inspect.getsource(inspect.getmodule(cls))
        if enum_nodes_in(source, cls.__name__):
            with_enums.add(tool_id)
    # The nine enum-bearing input schemas censused for AD-1179. Two were already
    # derived (browser.action, oracle.kind); the other seven are this slice.
    assert with_enums == {
        "browser",
        "oracle_query",
        "standing_orders_lookup",
        "event_log_query",
        "search_capabilities",
        "publish_finding",
    }, sorted(with_enums)


def test_g1_negative_control_flags_a_hand_typed_enum() -> None:
    """A synthetic tool that violates the rule must fail the guard."""
    broken = '''
class _BrokenTool:
    @property
    def input_schema(self):
        return {"properties": {"mode": {"type": "string", "enum": ["a", "b"]}}}
'''
    nodes = enum_nodes_in(broken, "_BrokenTool")
    assert nodes, "scanner found no enum in the synthetic tool"
    assert [classify_enum_node(n) for _, n in nodes] == ["literal"]


def test_g1_negative_control_accepts_both_derived_forms() -> None:
    """And must not fail a compliant one, in either accepted spelling."""
    ok = '''
class _OkTool:
    @property
    def input_schema(self):
        return {
            "properties": {
                "mode": {"enum": list(_MODES)},
                "kind": {"enum": [*TIERS, "all"]},
            }
        }
'''
    nodes = enum_nodes_in(ok, "_OkTool")
    assert len(nodes) == 2
    assert {classify_enum_node(n) for _, n in nodes} == {"derived"}


# ══ G2 — no action handler reads the dispatch key ═════════════════


def _resolve_browser_handlers() -> tuple[dict[str, Any], set[str]]:
    """``{action: handler}`` for every offered browser verb, plus the set of
    actions resolved OUTSIDE ``_HANDLERS``.

    ``_HANDLERS`` is not the complete implementation registry — ``verify`` is
    dispatched through ``action_verify``, imported directly by ``tool.py``. An
    action that resolves nowhere is a failure, not a silent skip.
    """
    from probos.tools.browser import actions as browser_actions
    from probos.tools.browser.tool import _AGENT_ACTIONS

    outside: set[str] = set()
    resolved: dict[str, Any] = {}
    for action in _AGENT_ACTIONS:
        handler = browser_actions._HANDLERS.get(action)  # noqa: SLF001
        if handler is None:
            handler = getattr(browser_actions, f"action_{action}", None)
            if handler is not None:
                outside.add(action)
        assert handler is not None, f"{action} resolves to no handler at all"
        resolved[action] = handler
    return resolved, outside


def test_g2_accounts_for_every_offered_action() -> None:
    from probos.tools.browser.tool import _AGENT_ACTIONS

    resolved, outside = _resolve_browser_handlers()
    assert set(resolved) == set(_AGENT_ACTIONS)
    # Named, not tolerated: if a second verb starts resolving outside
    # ``_HANDLERS`` that is a real change to the dispatch surface and should be
    # a deliberate edit here.
    assert outside == {"verify"}, sorted(outside)


@pytest.mark.parametrize("action", sorted(_resolve_browser_handlers()[0]))
def test_g2_no_handler_reads_the_dispatch_key(action: str) -> None:
    """The guard that catches BF-867.

    ``dispatch_action(session, action, params)`` forwards the same dict the
    dispatch key was read from, so a handler reading ``params["action"]`` gets
    its own verb name — always, unconditionally. ``mouse_button`` did exactly
    that and was refused on every call it ever received.
    """
    handler = _resolve_browser_handlers()[0][action]
    hits = reads_dispatch_key(inspect.getsource(handler))
    assert not hits, (
        f"browser action {action!r} reads params['action'], which is the "
        f"dispatch key and is always {action!r} here (lines {hits})"
    )


def test_g2_negative_control_flags_a_handler_that_reads_the_dispatch_key() -> None:
    """This is the pre-fix ``_action_mouse_button``, reduced to its defect."""
    broken = '''
async def _action_broken(session, params):
    sub_verb = params.get("action", "click")
    if sub_verb not in ("down", "up", "click"):
        raise ValueError("bad")
'''
    assert reads_dispatch_key(broken) == [3]


def test_g2_negative_control_passes_the_repaired_shape() -> None:
    ok = '''
async def _action_ok(session, params):
    press = params.get("press", "click")
    return press
'''
    assert reads_dispatch_key(ok) == []


# ══ G3 — no handler reads an undeclared parameter ═════════════════

# Tools whose ``invoke`` admits keys through a dedicated validator instead of
# reading them inline. Their keys are gated by ``_ALLOWED_KEYS`` frozensets the
# scanner cannot see, so including them would make the guard pass vacuously on
# an empty read set. Named here rather than filtered silently: a guard whose
# coverage set is implicit is a guard that quietly shrinks.
#
# ``oracle_query`` and ``publish_finding`` USED to sit here. They did not
# belong: both read their keys inline off ``raw = params if ... else {}``, and
# the scanner simply could not follow a ternary, so they reported an empty set
# and looked like delegators. Teaching the scanner ``ast.IfExp`` (slice 2
# review) revealed real reads -- ``kind``, ``query`` -- every one of them
# declared. They are now covered by G3 proper.
G3_DELEGATED_ADMISSION: frozenset[str] = frozenset({
    "event_log_query",   # -> _parse_query, a MODULE function with no instance
})
# ``browser`` reads the dispatch key and the session id inline and hands the rest
# to sixteen action handlers; those are covered by G2 above, not here.


@pytest.mark.parametrize(
    "tool_id", sorted(EXPECTED_TOOL_IDS - G3_DELEGATED_ADMISSION)
)
def test_g3_every_key_a_handler_reads_is_declared(tool_id: str) -> None:
    tool = _tools_by_id()[tool_id]
    source = inspect.getsource(type(tool).invoke)
    read = params_keys_read(source)
    declared = set((tool.input_schema or {}).get("properties", {}))
    assert read <= declared, (
        f"{tool_id} reads undeclared parameter(s) {sorted(read - declared)}; "
        f"an accepted key the schema never names is the same defect as a "
        f"declared key nothing reads, one direction over"
    )


def test_g3_the_scan_actually_found_something() -> None:
    """Premise assertion. A scanner that stops matching production would make
    every case above pass on an empty set."""
    covered = EXPECTED_TOOL_IDS - G3_DELEGATED_ADMISSION
    total: set[str] = set()
    tools = _tools_by_id()
    for tool_id in covered:
        total |= params_keys_read(inspect.getsource(type(tools[tool_id]).invoke))
    assert len(total) >= 20, sorted(total)


def test_g3_the_delegating_tools_really_do_delegate() -> None:
    """The exclusion list must stay honest: each excluded tool reads nothing
    inline, which is why excluding it costs no coverage."""
    tools = _tools_by_id()
    for tool_id in sorted(G3_DELEGATED_ADMISSION):
        read = params_keys_read(inspect.getsource(type(tools[tool_id]).invoke))
        assert read == set(), (
            f"{tool_id} now reads {sorted(read)} inline, so it no longer "
            f"delegates key admission and must leave G3_DELEGATED_ADMISSION"
        )


def test_g3_negative_control_flags_an_undeclared_read() -> None:
    broken = '''
async def invoke(self, params, context=None):
    query = (params or {}).get("query") or (params or {}).get("concept") or ""
    return query
'''
    assert params_keys_read(broken) == {"query", "concept"}


def test_g3_negative_control_follows_a_one_hop_alias() -> None:
    """``p = params or {}`` then ``p.get(...)`` must still be seen, or the
    scanner would report an empty set for a whole family of handlers."""
    aliased = '''
async def invoke(self, params, context=None):
    p = params or {}
    return p.get("path"), p["limit"]
'''
    assert params_keys_read(aliased) == {"path", "limit"}


def test_g3_negative_control_ignores_a_different_dict() -> None:
    """Reads off ``context`` or a result dict must not be counted as params
    keys — that would manufacture false undeclared parameters."""
    other = '''
async def invoke(self, params, context=None):
    agent = (context or {}).get("agent_id", "")
    return params.get("path"), agent
'''
    assert params_keys_read(other) == {"path"}


def test_g3_follows_a_ternary_alias() -> None:
    """``raw = params if type(params) is dict else {}`` is a real shape in this
    tree (oracle_query, publish_finding). Before this branch the scanner
    returned an EMPTY set for such a tool, which is indistinguishable from
    "reads nothing undeclared" -- so those two passed G3 because the scanner
    was blind, not because they delegate. Found by review of slice 2."""
    ternary = '''
async def invoke(self, params, context=None):
    raw = params if type(params) is dict else {}
    return raw.get("kind"), raw.get("undeclared_thing")
'''
    assert params_keys_read(ternary) == {"kind", "undeclared_thing"}


def test_g3_follows_a_ternary_used_inline_without_an_alias() -> None:
    """The same shape read directly, never bound to a name."""
    inline = '''
async def invoke(self, params, context=None):
    return (params if isinstance(params, dict) else {}).get("path")
'''
    assert params_keys_read(inline) == {"path"}


# ---------------------------------------------------------------------------
# The retired ``concept`` alias must refuse by name, not answer emptily.
# ---------------------------------------------------------------------------


class _StubWorkbench:
    """Records the search text find_mcp_tool actually issued."""

    def __init__(self) -> None:
        self.searched: list[str] = []

    async def find_mcp_tool(self, agent_id: str, query: str) -> list[dict]:
        self.searched.append(query)
        return [{"server": "s", "tool": "t"}]

    async def pull_tool(self, agent_id: str, server: str, tool: str) -> None:
        return None


def _find_tool() -> tuple:
    from probos.cognitive.mcp_workbench import _FindMcpToolTool

    bench = _StubWorkbench()
    return _FindMcpToolTool(bench), bench


@pytest.mark.asyncio
async def test_a_real_query_still_searches_and_pulls() -> None:
    """Happy path: the declared key works and reaches the workbench."""
    tool, bench = _find_tool()
    result = await tool.invoke({"query": "read a file"}, {"agent_id": "a1"})
    assert result.error is None
    assert bench.searched == ["read a file"]
    assert result.output["matches"] == [{"server": "s", "tool": "t"}]


@pytest.mark.asyncio
async def test_the_retired_concept_alias_is_refused_by_name() -> None:
    """AD-1179 review finding. Dropping the undeclared ``concept`` alias made a
    concept-only call search for "" and return an EMPTY match list inside a
    SUCCESS envelope — indistinguishable from "the mesh has no such tool". A
    caller reads a wrong answer as a true one. It must refuse, and the refusal
    must name the key to use instead."""
    tool, bench = _find_tool()
    result = await tool.invoke({"concept": "read a file"}, {"agent_id": "a1"})
    assert result.output is None
    assert "concept" in result.error and "query" in result.error
    assert bench.searched == [], "must not search on behalf of a retired key"


@pytest.mark.asyncio
async def test_an_absent_query_is_refused_rather_than_searched_for_nothing() -> None:
    """The schema marks ``query`` required; an empty one must not reach the
    workbench and come back as a confident empty result."""
    tool, bench = _find_tool()
    for params in ({}, {"query": ""}):
        result = await tool.invoke(params, {"agent_id": "a1"})
        assert result.output is None
        assert "query" in result.error
    assert bench.searched == []
