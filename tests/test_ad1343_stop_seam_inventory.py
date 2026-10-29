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
9. SHADOW (AD-1346 M3c): each stop check is in ``SHADOW_SITES`` or ``SHADOW_PENDING``; each shadowed function calls
   ``shadow_at`` the registered number of times, after its check with no await between, with the check's seam and its work
   kind; and nothing else calls it.

Not seen (stated bounds): an entry reached through an alias or ``getattr``; a tool held
under a name not ending in ``tool``; a synchronous method that starts work
(``resume_promoted_turn`` is named below as S2 scope).
"""

from __future__ import annotations

import ast
from pathlib import Path

from probos import agent_stop
from probos.security.url_guard import validate_public_url
# AD-1343 M0: the census and its tables are shared with the seam registry guard (tests/test_ad1343_seam_registry.py);
# imported under their S1 names so the tests below are unchanged.
from tests.fixtures.ad1343_seam_census import (
    IMPLEMENTATION as _IMPLEMENTATION,
    ROOT as _ROOT,
    STOP_CALLEES as _STOP_CALLEES,
    calls as _calls,
    census as _census,
    first_line as _first_line,
    function as _function,
)
from tests.fixtures.ad1343_seam_registry import (
    ADMITTED_SYNTHESIS_SITES as _ADMITTED_SYNTHESIS_SITES,
    ADMITTED_TURN_SITES as _ADMITTED_TURN_SITES,
    AGENTIC_RUN_OWNERS as _AGENTIC_RUN_OWNERS,
    COGNITIVE_AGENT_COROUTINES as _COGNITIVE_AGENT_COROUTINES,
    CREW_MODEL_CALLS as _CREW_MODEL_CALLS,
    DIRECT_TOOL_INVOKES as _DIRECT_TOOL_INVOKES,
    SHADOW_PENDING as _SHADOW_PENDING,
    SHADOW_SITES as _SHADOW_SITES,
    SOURCE_ORDER as _SOURCE_ORDER,
    STANDING_STOP_SITES as _STANDING_STOP_SITES,
    STOP_CHECK_SITES as _STOP_CHECK_SITES,
    SYNC_WORK_STARTERS as _SYNC_WORK_STARTERS,
    VERIFIER_STOP_SITES as _VERIFIER_STOP_SITES,
)


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


def test_every_stop_check_is_shadowed_or_pending() -> None:
    """9a (AD-1346 M3c): each S1 stop check is in exactly one of SHADOW_SITES and SHADOW_PENDING."""
    assert not set(_SHADOW_SITES) & set(_SHADOW_PENDING)
    both = set(_SHADOW_SITES) | set(_SHADOW_PENDING)
    assert both == set(_STOP_CHECK_SITES), sorted(both ^ set(_STOP_CHECK_SITES))


def test_each_shadowed_site_calls_shadow_at_beside_its_check() -> None:
    """9b (AD-1346 M3c): the number, keywords and place of each site's shadow statements; removing one fails here."""
    keywords = {"presented_id", "work_kind", "seam", "origin", "origin_id", "refused"}
    for (rel, qualname, callee), (work_kind, count) in _SHADOW_SITES.items():
        fn = _function(rel, qualname)
        shadows = [n for n in ast.walk(fn) if _calls("shadow_at")(n)]
        assert len(shadows) == count, (qualname, len(shadows))
        check = _first_line(fn, _calls(callee))
        for call in shadows:
            given = {k.arg: k.value for k in call.keywords}
            assert set(given) == keywords and len(call.args) == 1, (qualname, sorted(given))
            assert ast.unparse(given["seam"]) == _STOP_CHECK_SITES[(rel, qualname, callee)], qualname
            assert isinstance(given["work_kind"], ast.Constant) and given["work_kind"].value == work_kind, qualname
            assert call.lineno > check, (qualname, call.lineno, check)
            between = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Await) and check < n.lineno < call.lineno]
            assert between == [], (qualname, between)


def test_shadow_at_is_called_only_at_the_shadowed_sites() -> None:
    """9c (AD-1346 M3c): a shadow statement outside SHADOW_SITES fails here."""
    found = {(c.file, c.function) for c in _census() if c.callee == "shadow_at"}
    assert found == {(rel, qualname) for rel, qualname, _ in _SHADOW_SITES}, sorted(found)
