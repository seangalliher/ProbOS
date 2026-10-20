"""AD-1343 S1 (#1595): the stop's seam inventory is pinned, so a later dispatch path cannot bypass it silently.

An AST census of ``src/probos`` in this checkout, in the manner of the AD-1195 pair freeze:

1. STOP CHECKS: every call that consults the Captain's stop (``active_stop(...)``,
   ``tool_refusal(...)`` or ``<x>.refusal(...)``) outside ``probos/agent_stop.py``, by
   (file, enclosing function, callee) and the seam it names. A check removed, added or
   moved fails until this table and the contract's seam inventory change together.
2. ENTRY POINTS: every public coroutine on ``CognitiveAgent``, classified.
3. TOOL BYPASSES: every ``<receiver>.invoke(...)`` whose receiver name ends in ``tool``.
4. ORDER: each sink consults the stop first; each source check precedes the work it guards.
5. REACH: only the Captain's routes issue or lift a stop; the URL floor refuses its routes.
6. RUNS (A2): every construction of ``WorkItemAgenticExecutor``, by enclosing function; the run entry
   refuses first; only the agent's own admitted turns pass ``admitted_turn``.
7. CREW (A2): crew eligibility consults the stop before any lookup, and its one construction is wired.
8. CREW MODEL WORK (A3): every model call in the crew modules is classified; each one under a crew agent's name is preceded by
   a stop question with no await between them; the verifier asks at every pick; the session finalizer is given the stop; the
   crew run asks eligibility right before its run entry, so it needs no ``AgentStopped`` catch.

Not seen (stated bounds): an entry reached through an alias or ``getattr``; a tool held
under a name not ending in ``tool``; a synchronous method that starts work
(``resume_promoted_turn`` is named below as S2 scope).
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import probos
from probos import agent_stop
from probos.security.url_guard import validate_public_url

_PACKAGE = Path(probos.__file__).resolve().parent
_ROOT = _PACKAGE.parents[1]
_IMPLEMENTATION = "src/probos/agent_stop.py"
_STOP_CALLEES = frozenset({"active_stop", "tool_refusal", "refusal", "refuse_new_run"})
_RECORDED = _STOP_CALLEES | {
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
    "CrewSessionFinalizer", "_stopped", "complete",  # A3
}
_PINNED_KEYWORDS = frozenset({"admitted_turn", "agent_stops", "admitted_synthesis"})  # recorded as "name=value" on any call passing one

# (file, enclosing function, callee) -> the seam constant it names.
_STOP_CHECK_SITES: dict[tuple[str, str, str], str] = {
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_intent", "refusal"): "SEAM_INTENT",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_consultation_request", "refusal"): "SEAM_CONSULTATION",
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "tool_refusal"): "SEAM_TOOL",
    ("src/probos/proactive.py", "ProactiveCognitiveLoop._run_cycle", "active_stop"): "SEAM_PROACTIVE",
    ("src/probos/ward_room_router.py", "WardRoomRouter._route_to_agents", "active_stop"): "SEAM_WARD_ROOM",
    ("src/probos/routers/agents.py", "_agent_chat_impl", "active_stop"): "SEAM_DM_ROUTE",
    ("src/probos/routers/thread_fanout.py", "_fan_one_round._send_one_impl", "active_stop"): "SEAM_GROUP_FANOUT",
    ("src/probos/routers/agent_actions.py", "ack_action", "active_stop"): "SEAM_BROWSER_ACTION",
    ("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor.run", "refuse_new_run"): "SEAM_AGENTIC_RUN",
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke", "active_stop"): "SEAM_DELEGATION",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "active_stop"): "SEAM_TOOL",
}

# Every public coroutine on CognitiveAgent. sink: consults the stop itself; within_turn: runs
# only inside a turn a sink admitted; dm_route: reached only after the DM route's check;
# captain_persona / s2_in_flight / lifecycle: named S1 exceptions, reported in S1_SCOPE.
_COGNITIVE_AGENT_COROUTINES: dict[str, str] = {
    "handle_intent": "sink",
    "handle_consultation_request": "sink",
    "perceive": "within_turn",
    "decide": "within_turn",
    "act": "within_turn",
    "report": "within_turn",
    "consult": "within_turn",
    "interpret_recall": "within_turn",
    "interpret_own_dream": "within_turn",
    "observe_self_avatar": "dm_route",
    "check_own_render": "dm_route",
    "propose_appearance": "captain_persona",
    "propose_voice_profile": "captain_persona",
    "recover_promoted_turn": "s2_in_flight",
    "stop": "lifecycle",
}
_SYNC_WORK_STARTERS: dict[str, str] = {
    "resume_promoted_turn": "s2_in_flight: AD-855 resume of a turn begun before the stop; tool calls refused",
}

# Direct tool invocations: each skips ToolRegistry.check_and_invoke unless it is that method.
_DIRECT_TOOL_INVOKES: dict[tuple[str, str, str], str] = {
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "tool"): "the tool sink, after its check",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "browser_tool"):
        "after its own stop check at SEAM_TOOL (A2, F2): a turn admitted before the order proposes and runs no action",
    ("src/probos/routers/agent_actions.py", "ack_action", "browser_tool"): "after SEAM_BROWSER_ACTION",
}

_SOURCE_ORDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("src/probos/proactive.py", "ProactiveCognitiveLoop._run_cycle", ("_check_unread_dms", "_think_for_agent")),
    ("src/probos/ward_room_router.py", "WardRoomRouter._route_to_agents", ("count_posts_by_author", "dispatch_async")),
    ("src/probos/routers/agents.py", "_agent_chat_impl", ("get_or_create_default_for_agent", "send")),
    ("src/probos/routers/thread_fanout.py", "_fan_one_round._send_one_impl", ("_capture_owned_steps_turn",)),
    ("src/probos/routers/agent_actions.py", "ack_action", ("invoke", "mark_executed", "mark_failed")),
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke", ("admit", "bind_delegated_run", "WorkItemAgenticExecutor")),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge", ("admit_correction", "run")),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", ("admit_correction", "run")),
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session", ("complete",)),
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", ("_claim_owned_synthesis", "synthesize_for_session")),
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", ("register", "invoke")),
)

# A2: every place a WorkItemAgenticExecutor is built, and how a stopped agent is refused there.
_AGENTIC_RUN_OWNERS: dict[tuple[str, str], str] = {
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._run_agentic_dispatch"): "admitted turn (handle_intent)",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._maybe_run_conversational_agentic"): "admitted turn",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn"): "S2 promoted resume",
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke"): "SEAM_DELEGATION, then the run entry",
    ("src/probos/startup/finalize.py", "_wire_crew_orchestrator"): "crew eligibility, correction rounds, the run entry",
}
_ADMITTED_TURN_SITES: frozenset[tuple[str, str, str]] = frozenset({
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._run_agentic_dispatch", "admitted_turn=True"),
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._maybe_run_conversational_agentic._run_pass", "admitted_turn=True"),
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn._recovered_pass", "admitted_turn=True"),
})
# A4 (F1): the one place a synthesis is admitted past the facilitator's stop: the owned resume, from its own claim.
_ADMITTED_SYNTHESIS_SITES: frozenset[tuple[str, str, str]] = frozenset({
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "admitted_synthesis=admission is not None"),
})

# A3 (R1): every model call in the crew modules, by enclosing function, and whose name it runs under.
_CREW_MODEL_CALLS: dict[tuple[str, str], str] = {
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify"): "verifier: picked stop-free, re-checked before the call",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify_for_session"): "verifier: picked stop-free, re-checked before the call",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session"):
        "facilitator: SEAM_AGENTIC_RUN at the entry, unless the owned resume claimed it after its own check (I18)",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer._synthesize_output"): "ship: the generic _SYSTEM_PROMPT, no crew identity or instructions",
}
# A3 (R1): the verifier's stop question, and every place that asks it.
_VERIFIER_STOP_SITES: frozenset[tuple[str, str]] = frozenset({
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_independent_verifier"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_department_peer"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_authority_chief"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_live_session_verifier"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify_for_session"),
})
_STANDING_STOP_SITES: frozenset[tuple[str, str]] = frozenset({
    ("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._stopped"),
})


@dataclass(frozen=True)
class _Call:
    file: str
    function: str
    callee: str
    receiver: str
    seam: str
    keywords: tuple[str, ...] = ()


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self._rel = rel
        self._scope: list[str] = []
        self.calls: list[_Call] = []

    def _enter(self, node: ast.AST, name: str) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            callee, receiver = func.attr, ast.unparse(func.value)
        elif isinstance(func, ast.Name):
            callee, receiver = func.id, ""
        else:
            callee, receiver = "", ""
        keywords = tuple(f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords if k.arg in _PINNED_KEYWORDS)
        if callee in _RECORDED or keywords:
            seam = ""
            if callee == "refusal" and len(node.args) >= 2:
                seam = ast.unparse(node.args[1])
            elif callee == "active_stop" and len(node.args) >= 3:
                seam = ast.unparse(node.args[2])
            elif callee == "tool_refusal":
                seam = "SEAM_TOOL"
            elif callee == "refuse_new_run":
                seam = "SEAM_AGENTIC_RUN"
            self.calls.append(_Call(self._rel, ".".join(self._scope) or "<module>", callee, receiver, seam, keywords))
        self.generic_visit(node)


@functools.lru_cache(maxsize=1)
def _census() -> tuple[_Call, ...]:
    calls: list[_Call] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        visitor = _Visitor(rel)
        visitor.visit(ast.parse(path.read_bytes(), filename=rel))
        calls += visitor.calls
    return tuple(calls)


def _function(rel: str, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse((_ROOT / rel).read_bytes(), filename=rel)

    def walk(body: list[ast.stmt], prefix: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{node.name}" if prefix else node.name
                if name == qualname and not isinstance(node, ast.ClassDef):
                    return node
                hit = walk(node.body, name)
                if hit is not None:
                    return hit
        return None

    found = walk(tree.body, "")
    assert found is not None, (rel, qualname)
    return found


def _calls(name: str) -> Callable[[ast.AST], bool]:
    def match(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (isinstance(func, ast.Attribute) and func.attr == name) or (
            isinstance(func, ast.Name) and func.id == name
        )
    return match


def _first_line(node: ast.AST, predicate: Callable[[ast.AST], bool]) -> int:
    lines = [n.lineno for n in ast.walk(node) if predicate(n)]
    assert lines, f"nothing matched in {getattr(node, 'name', node)}"
    return min(lines)


def test_census_premise_reads_this_checkout() -> None:
    """Premise: the census scans this checkout and sees the intent sink."""
    assert (_ROOT / _IMPLEMENTATION).resolve() == Path(agent_stop.__file__).resolve()
    assert any(
        c.function == "CognitiveAgent.handle_intent" and c.callee == "refusal" for c in _census()
    )


def test_stop_checks_are_exactly_the_inventory() -> None:
    found = {
        (c.file, c.function, c.callee): c.seam
        for c in _census()
        if c.callee in _STOP_CALLEES and c.file != _IMPLEMENTATION
    }
    assert found == _STOP_CHECK_SITES, sorted(set(found.items()) ^ set(_STOP_CHECK_SITES.items()))


def test_every_seam_is_checked_and_no_check_names_an_unknown_seam() -> None:
    declared = {
        name for name in dir(agent_stop)
        if name.startswith("SEAM_") and isinstance(getattr(agent_stop, name), str)
    }
    assert {getattr(agent_stop, name) for name in declared} == agent_stop.SEAMS
    assert set(_STOP_CHECK_SITES.values()) == declared


def test_cognitive_agent_entry_points_are_classified() -> None:
    tree = ast.parse((_ROOT / "src/probos/cognitive/cognitive_agent.py").read_bytes())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CognitiveAgent")
    coroutines = {n.name for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and not n.name.startswith("_")}
    assert coroutines == set(_COGNITIVE_AGENT_COROUTINES), sorted(coroutines ^ set(_COGNITIVE_AGENT_COROUTINES))
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert set(_SYNC_WORK_STARTERS) <= methods
    sinks = {name for name, kind in _COGNITIVE_AGENT_COROUTINES.items() if kind == "sink"}
    assert sinks == {key[1].split(".")[1] for key in _STOP_CHECK_SITES if key[1].startswith("CognitiveAgent.")}


def test_direct_tool_invocations_are_exactly_the_inventory() -> None:
    found = {
        (c.file, c.function, c.receiver)
        for c in _census()
        if c.callee == "invoke" and c.receiver.split(".")[-1].endswith("tool")
    }
    assert found == set(_DIRECT_TOOL_INVOKES), sorted(found ^ set(_DIRECT_TOOL_INVOKES))


def test_each_sink_consults_the_stop_first() -> None:
    for rel, qualname, limit in (
        ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_intent", 3),
        ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_consultation_request", 4),
    ):
        body = _function(rel, qualname).body
        index = next(i for i, stmt in enumerate(body) if any(_calls("refusal")(n) for n in ast.walk(stmt)))
        assert index <= limit, (qualname, index)
        assert not any(isinstance(n, ast.Await) for stmt in body[:index] for n in ast.walk(stmt)), qualname
    check = _function("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke")
    stop = _first_line(check, _calls("tool_refusal"))
    assert stop < _first_line(check, _calls("resolve_permission"))
    assert stop < _first_line(check, lambda n: isinstance(n, ast.Call) and ast.unparse(n.func) == "self._tools.get")
    assert stop < _first_line(check, _calls("start_permitted_effect"))


def test_each_source_check_precedes_the_work_it_guards() -> None:
    for rel, qualname, guarded in _SOURCE_ORDER:
        fn = _function(rel, qualname)
        stop = _first_line(fn, _calls("active_stop"))
        for name in guarded:
            assert stop < _first_line(fn, _calls(name)), (qualname, name)


def test_only_the_captain_routes_issue_or_lift_a_stop() -> None:
    callers = {(c.file, c.function, c.callee) for c in _census() if c.callee in {"issue_stop", "lift_stop"}}
    assert callers == {
        ("src/probos/routers/agent_stop.py", "issue_agent_stop", "issue_stop"),
        ("src/probos/routers/agent_stop.py", "lift_agent_stop", "lift_stop"),
    }


def test_agent_fetch_and_browser_tools_cannot_reach_the_stop_routes() -> None:
    for url in ("http://127.0.0.1:18900/api/stops/counselor_0", "http://[::1]:18900/api/stops/counselor_0/lift"):
        assert validate_public_url(url) is not None, url


def test_every_agentic_run_is_built_by_a_classified_owner() -> None:
    found = {(c.file, c.function) for c in _census() if c.callee == "WorkItemAgenticExecutor"}
    assert found == set(_AGENTIC_RUN_OWNERS), sorted(found ^ set(_AGENTIC_RUN_OWNERS))


def test_the_run_entry_refuses_before_anything_else() -> None:
    body = _function("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor.run").body
    index = next(i for i, stmt in enumerate(body) if any(_calls("refuse_new_run")(n) for n in ast.walk(stmt)))
    assert index == 1, index  # after the docstring: before owned-steps validation, the browser reservation and the run
    assert not any(isinstance(n, ast.Await) for stmt in body[:index] for n in ast.walk(stmt))


def test_only_the_agents_own_turns_pass_admitted_turn() -> None:
    found = {(c.file, c.function, k) for c in _census() for k in c.keywords if k.startswith("admitted_turn=")}
    assert found == _ADMITTED_TURN_SITES, sorted(found ^ _ADMITTED_TURN_SITES)


def test_only_the_owned_resume_passes_admitted_synthesis() -> None:
    """I18 (A4, F1): a synthesis passes the facilitator's stop only when the owned resume has just claimed it."""
    found = {(c.file, c.function, k) for c in _census() for k in c.keywords if k.startswith("admitted_synthesis=")}
    assert found == _ADMITTED_SYNTHESIS_SITES, sorted(found ^ _ADMITTED_SYNTHESIS_SITES)


def test_crew_eligibility_consults_the_stop_first_and_is_wired() -> None:
    check = _function("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility")

    def registry_get(node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and ast.unparse(node.func) == "self._agent_registry.get"

    assert _first_line(check, _calls("standing_stop")) < _first_line(check, registry_get)
    built = {(c.file, c.function, c.keywords) for c in _census() if c.callee == "CrewAssignmentResolver"}
    assert built == {(
        "src/probos/startup/finalize.py", "_wire_crew_orchestrator", ("agent_stops=getattr(runtime, 'agent_stops', None)",),
    )}, built


def test_every_crew_model_call_is_classified() -> None:
    """I14 (A3): a new model call in a crew module fails here until it is classified."""
    found = {(c.file, c.function) for c in _census() if c.callee == "complete" and c.file.startswith("src/probos/cognitive/crew_")}
    assert found == set(_CREW_MODEL_CALLS), sorted(found ^ set(_CREW_MODEL_CALLS))


def test_each_attributed_crew_model_call_is_checked_with_no_await_between() -> None:
    """I15 (A3): the last stop question before a crew agent's model call has no await between it and the call."""
    for (rel, qualname), how in _CREW_MODEL_CALLS.items():
        if how.startswith("ship:"):
            continue
        fn = _function(rel, qualname)
        model = _first_line(fn, _calls("complete"))
        check = "_stopped" if how.startswith("verifier:") else "active_stop"
        checks = [n.lineno for n in ast.walk(fn) if _calls(check)(n) and n.lineno < model]
        assert checks, (qualname, check)
        between = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Await) and max(checks) < n.lineno < model]
        assert between == [], (qualname, between)


def test_the_verifier_asks_the_stop_at_every_pick_and_judgment() -> None:
    """I15b (A3): removing a verifier stop question fails here as well as in its behaviour test."""
    asked = {(c.file, c.function) for c in _census() if c.callee == "_stopped"}
    assert asked == _VERIFIER_STOP_SITES, sorted(asked ^ _VERIFIER_STOP_SITES)
    standing = {(c.file, c.function) for c in _census() if c.callee == "standing_stop" and c.file != _IMPLEMENTATION}
    assert standing == _STANDING_STOP_SITES, sorted(standing ^ _STANDING_STOP_SITES)


def test_the_session_finalizer_is_given_the_stop() -> None:
    """I16 (A3)."""
    built = {(c.file, c.function, c.keywords) for c in _census() if c.callee == "CrewSessionFinalizer"}
    assert built == {(
        "src/probos/startup/finalize.py", "_wire_crew_orchestrator", ("agent_stops=getattr(runtime, 'agent_stops', None)",),
    )}, built


def test_the_crew_run_asks_eligibility_right_before_its_run_entry() -> None:
    """I17 (A3): CrewTaskExecutor has no AgentStopped catch and needs none. Its eligibility question (synchronous, and its
    answer includes the stop) is the statement right before the awaited run entry, so no stop can land between them."""
    rel = "src/probos/cognitive/crew_executor.py"
    fn = _function(rel, "CrewTaskExecutor._run_agentic_with_outer_loop")
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and any(_calls("_require_eligible")(m) for s in n.body for m in ast.walk(s))]
    assert len(tries) == 1, len(tries)
    body = tries[0].body
    index = next(i for i, stmt in enumerate(body) if any(_calls("_require_eligible")(n) for n in ast.walk(stmt)))
    after = body[index + 1]
    assert isinstance(after, ast.Assign) and isinstance(after.value, ast.Await), ast.dump(after)
    assert ast.unparse(after.value.value.func) == "self._executor.run"
    assert isinstance(_function(rel, "CrewTaskExecutor._require_eligible"), ast.FunctionDef)  # synchronous
