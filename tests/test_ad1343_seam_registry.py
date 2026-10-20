"""AD-1343 M0 (#1595): the seam registry is the living list of every place agent work can start, each with its guard.

Each test reads the AST census of ``src/probos`` (``tests/fixtures/ad1343_seam_census.py``) against the registry
(``tests/fixtures/ad1343_seam_registry.py``):

- R1  every call that starts another agent's work is registered, and every registered call still exists;
- R2  every registered call and every indexed seam names a guard that still holds: its stop check is still found where
      the registry says, a same-function check still comes first, a named S1 exception is still in ``S1_SCOPE``, and a
      module named as starting no work still starts none; every ``agent_stop.SEAM_*`` value is indexed;
- R3  the scanner's rule on a fixed source: the caller's own calls, ``super()`` calls, bare calls and non-agent
      receivers of the generic names are not seams;
- R4  the model-call report covers the model calls outside the crew modules and gates none of them;
- R5  the registry imports nothing, so #1601 M3 can add a column without a cycle.

Not seen (stated bounds, as in S1): a call through an alias, ``getattr`` or a stored reference
(``handler=agent.handle_intent``; the sink still refuses it), and a model call outside the crew modules (reported, not
gated, until #1601 M3).
"""

from __future__ import annotations

import ast
from pathlib import Path

from probos import agent_stop
from tests.fixtures import ad1343_seam_census as seam_census
from tests.fixtures import ad1343_seam_registry as seam_registry
from tests.fixtures.ad1343_seam_census import (
    GUARD_CALLEES,
    ROOT,
    agent_work_calls,
    calls,
    census,
    first_line,
    function,
    model_call_report,
    scan,
)
from tests.fixtures.ad1343_seam_registry import AGENT_WORK_CALLS, FIRST_RUN_DOOR, MODEL_CALLS_OUTSIDE_CREW, RECOVERY_TRANSIENT_SITES, SEAM_INDEX

_WORK_STARTERS = seam_census.AGENT_WORK_METHODS | {"WorkItemAgenticExecutor", "invoke", "complete"}


def _guard_sites() -> frozenset[tuple[str, str, str]]:
    return frozenset((c.file, c.function, c.callee) for c in census() if c.callee in GUARD_CALLEES)


def _assert_guard(where: object, guard: tuple[object, ...], primitive: tuple[str, str, str] | None) -> None:
    kind, *refs = guard
    assert refs, (where, guard)
    if kind in {"sink", "check", "upstream", "at"}:
        found = _guard_sites()
        for ref in refs:
            assert ref in found, (where, "the guard is no longer found", ref)
        if kind == "check":
            assert primitive is not None and len(refs) == 1, (where, guard)
            rel, qualname, callee = refs[0]
            assert (rel, qualname) == primitive[:2], (where, "a check guards only calls in its own function")
            fn = function(rel, qualname)
            assert first_line(fn, calls(callee)) < first_line(fn, calls(primitive[2])), (where, "the check is no longer first")
    elif kind == "exception":
        scope_key, phrase = refs[0]
        assert phrase in agent_stop.S1_SCOPE[scope_key], (where, scope_key, phrase)
    elif kind == "none":
        rel = refs[0]
        assert (ROOT / rel).is_file(), (where, rel)
        starters = {(c.function, c.callee) for c in census() if c.file == rel and c.callee in _WORK_STARTERS}
        assert starters == set(), (where, sorted(starters))
    else:
        raise AssertionError((where, "unknown guard kind", kind))


# R1
def test_every_agent_work_call_is_registered() -> None:
    found = agent_work_calls()
    assert ("src/probos/activation/dispatcher.py", "Dispatcher.dispatch", "handle_intent") in found  # premise: the scan sees a sink caller
    assert found == set(AGENT_WORK_CALLS), sorted(found ^ set(AGENT_WORK_CALLS))


# R2
def test_every_registered_call_names_a_guard_that_still_holds() -> None:
    for key, guard in AGENT_WORK_CALLS.items():
        assert guard[0] in {"sink", "check", "upstream", "exception"}, (key, guard)
        _assert_guard(key, guard, key)


# R2
def test_every_indexed_seam_names_a_guard_that_still_holds() -> None:
    seams = {
        getattr(agent_stop, name) for name in dir(agent_stop)
        if name.startswith("SEAM_") and isinstance(getattr(agent_stop, name), str)
    }
    assert seams <= set(SEAM_INDEX), sorted(seams - set(SEAM_INDEX))
    for name, (what, guard) in SEAM_INDEX.items():
        assert what, name
        assert guard[0] in {"at", "exception", "none"}, (name, guard)
        _assert_guard(name, guard, None)


# R3
def test_the_scan_counts_only_calls_that_start_another_agents_work() -> None:
    source = (
        "class Loop:\n"
        "    async def run(self, agent, store, organ, bus):\n"
        "        await self.decide(1)\n"
        "        await super().handle_intent(2)\n"
        "        await resume_promoted_turn(3)\n"
        "        await store.decide(4)\n"
        "        organ.act(5)\n"
        "        await agent.decide(6)\n"
        "        await self.ctx.agent.check_own_render()\n"
        "        await bus.handle_intent(7)\n"
    )
    found = {
        (c.function, c.callee, c.receiver)
        for c in scan(source, "src/probos/example.py")
        if seam_census.is_agent_work_call(c)
    }
    assert found == {
        ("Loop.run", "decide", "agent"),
        ("Loop.run", "check_own_render", "self.ctx.agent"),
        ("Loop.run", "handle_intent", "bus"),
    }, sorted(found)


# R4
def test_the_model_call_report_covers_the_sites_outside_the_crew_modules_and_gates_nothing() -> None:
    report = model_call_report()
    rows = {(file, fn) for file, fn, _receiver, _how in report}
    assert rows  # premise: there are model calls outside the crew modules
    assert not any(file.startswith(seam_census.CREW_PREFIX) for file, _fn in rows)
    assert all(how for *_rest, how in report)
    assert any(how == "agent class CognitiveAgent" for *_rest, how in report)  # premise: CognitiveAgent's own calls are recognised
    assert set(MODEL_CALLS_OUTSIDE_CREW) <= rows, sorted(set(MODEL_CALLS_OUTSIDE_CREW) - rows)  # no stale hand row


# R5
def test_the_registry_imports_nothing() -> None:
    tree = ast.parse(Path(seam_registry.__file__).read_bytes())
    assert [type(n).__name__ for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))] == []


# N1
def test_every_recovery_transient_is_classified() -> None:
    found = {(c.file, c.function, c.seam) for c in census() if c.callee == "CrewRecoveryTransientError"}
    assert found == set(RECOVERY_TRANSIENT_SITES), sorted(found ^ set(RECOVERY_TRANSIENT_SITES))


# N1 (P1)
def test_the_first_run_finalize_door_is_reached_only_without_a_session_service() -> None:
    found = {(c.file, c.function, c.callee) for c in census() if c.callee in {"finalize", "run_crew_task"}}
    assert found == FIRST_RUN_DOOR, sorted(found ^ FIRST_RUN_DOOR)
    owner = function("src/probos/cognitive/crew_orchestrator.py", "CrewOrchestrator._run_owned_parent")
    assert "self._crew_session_service is None" in ast.unparse(owner)  # the run_crew_task branch needs no service
